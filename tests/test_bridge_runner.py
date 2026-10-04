"""Run the bridge's one-click annotation runner against a simulated Zotero, a scripted Claude Code and
a scripted Codex.

The simulated Subprocess replays stream-json output (split across chunks) and answers the model list
request; for Codex it plays `codex app-server`, answering its JSON-RPC requests and sending the
notifications of a turn. So the command line, the task prompt, the Scholium section of the item
pane (the models Claude Code reports, the remembered effort and the levels of each model, the
editor sheet of the personal profile, buttons, state line, resizable transcript, saved history, the message box), the self-closing
notices and the system notification (left out while the section is on screen in the focused
window), follow-ups, the usage limit, deletion, failures, cancellation and the queue are checked
without starting an agent. PathUtils behaves like Zotero's: it has no homeDir, and join()
rejects a first component that is not an absolute path.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugin/scholium-bridge"
BRIDGE = PLUGIN / "bootstrap.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
// an element as [tag.class[style][start=…][title=…], children or text…], to compare built pages
const tree = n => (n && n.tagName
  ? [n.tagName + (n.className ? '.' + n.className : '') + (n.attrs.style ? '[' + n.attrs.style + ']' : '')
     + (n.attrs.start ? '[start=' + n.attrs.start + ']' : '') + (n.title ? '[title=' + n.title + ']' : ''),
     ...(n.children.length ? n.children.map(tree) : n._text ? [n._text] : [])]
  : n.textContent);
// a key pressed in an element: its keydown listeners, and whether they kept the key to themselves
const key = (el, opts) => {
  const e = Object.assign({ defaultPrevented: false, stopped: false, preventDefault() { this.defaultPrevented = true; },
                            stopPropagation() { this.stopped = true; } }, opts);
  for (const f of el.listeners.keydown || []) f(e);
  return e;
};
const settle = async (n = 20) => { for (let i = 0; i < n; i++) await tick(); };

const CLAUDE = '/appdata/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe';
const ev = (obj) => JSON.stringify(obj) + '\n';
const tool = (name, input) => ev({ type: 'assistant', message: { content: [{ type: 'tool_use', name, input }] } });
const said = (text) => ev({ type: 'assistant', message: { content: [{ type: 'text', text }] } });
const answer = (content, is_error = false) => ev({ type: 'user', message: { content: [{ type: 'tool_result', content, is_error }] } });
const SCRIPT = [
  ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
  said('先加载技能，再提取句子。'),
  tool('Skill', { skill: 'zotero-scholium' }),
  answer('Launching skill: zotero-scholium'),
  tool('PowerShell', { command: 'python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json\nsecond line' }),
  answer([{ type: 'text', text: '412 sentences -> s.json\n1\n2\n3\n4\n5' }]),
  tool('Read', { file_path: 'D:\\Zotero\\tmp\\scholium\\ATT1\\sentences.txt' }),
  tool('Write', { file_path: 'D:\\Zotero\\tmp\\scholium\\ATT1\\config.json' }),
  tool('PowerShell', { command: 'python C:/skills/scholium.py --config c.json' }),
  answer('Exit code 2\nstyle_warnings: 1', true),
  tool('PowerShell', { command: 'python C:/skills/scholium.py --config c.json --apply' }),
  answer('{"applied": true}'),
  ev({ type: 'rate_limit_event', session_id: 'S1', rate_limit_info: { status: 'allowed_warning', rateLimitType: 'seven_day', utilization: 0.84,
       resetsAt: Math.floor(Date.now() / 1000) + 259200, unifiedWindows: {
         five_hour: { utilization: 0.16, resetsAt: Math.floor(Date.now() / 1000) + 7200 },
         seven_day: { utilization: 0.84, resetsAt: Math.floor(Date.now() / 1000) + 259200 } } } }),
];
const SUMMARY = '高亮 28 条（核心 12 条），页边批注 9 条，笔记《Deep latent》，无剩余警告。';
const LAST = said('Done.\n' + SUMMARY);      // Claude's last message; the result event repeats it
const RESULT = ev({ type: 'result', subtype: 'success', is_error: false, result: 'Done.\n' + SUMMARY, session_id: 'S1',
                     num_turns: 26, duration_ms: 376500,
                     usage: { input_tokens: 52, cache_creation_input_tokens: 111184, cache_read_input_tokens: 2410165, output_tokens: 46778 } });
// the usage limit, with and without a reset time
const LIMIT_RESET = Math.floor(Date.now() / 1000) + 7200;
const LIMIT_HIT = [
  ev({ type: 'rate_limit_event', session_id: 'S1', rate_limit_info: { status: 'rejected', resetsAt: LIMIT_RESET, rateLimitType: 'five_hour',
       utilization: 1, unifiedWindows: { five_hour: { utilization: 1, resetsAt: LIMIT_RESET }, seven_day: { utilization: 0.9, resetsAt: LIMIT_RESET + 259200 } } } }),
  ev({ type: 'assistant', error: 'rate_limit', session_id: 'S1', message: { content: [{ type: 'text', text: "You've hit your limit · resets 9pm" }] } }),
  ev({ type: 'result', subtype: 'success', is_error: true, result: "You've hit your limit · resets 9pm", session_id: 'S1' }),
];
const RATE_LIMITED = [
  ev({ type: 'assistant', error: 'rate_limit', session_id: 'S1', message: { content: [{ type: 'text', text: 'Rate limited' }] } }),
  ev({ type: 'result', subtype: 'success', is_error: true, result: 'Rate limited', session_id: 'S1' }),
];
const NSIFILE = { name: 'nsIFile' };
const PROFILE_PATH = '/data/zotero-scholium/profile.md';
const PROFILE_HEAD = '# Annotation profile (draft derived from the Zotero library)\n\nBased on 466 annotations on 50 papers.\n\n- Colours:\n  - `#ff6666` 75%\n';
const PROFILE_INTERPRETATION = '- colour meanings: `#ff6666` = anything important\n- reading note: yes';
const PROFILE_RULES = '- 高亮评论 = 中文翻译\n- 颜色只有两级：红 = 核心，黄 = 其他';
const PROFILE = PROFILE_HEAD + '\n## Interpretation (to be completed by the assistant from the statistics and confirmed by the user)\n\n'
  + PROFILE_INTERPRETATION + '\n\n## User\'s rules (always win)\n\nAnything written here overrides the learned statistics above.\n'
  + 'Re-running regenerates the statistics only.\n\n' + PROFILE_RULES + '\n';
// what Claude Code answers to the initialize request (abridged)
const LEVELS = ['low', 'medium', 'high', 'xhigh', 'max'];
const MODELS = [
  { value: 'default', resolvedModel: 'claude-fable-5-1', displayName: 'Default (recommended)', description: 'Fable 5.1',
    supportsEffort: true, supportedEffortLevels: LEVELS },
  { value: 'opus', resolvedModel: 'claude-opus-5-5', displayName: 'Opus 5.5', description: 'For complex work and everyday tasks',
    supportsEffort: true, supportedEffortLevels: LEVELS },
  { value: 'fable', resolvedModel: 'claude-fable-5-1', displayName: 'Fable 5.1', description: 'For your toughest challenges',
    supportsEffort: true, supportedEffortLevels: LEVELS },
  { value: 'haiku', resolvedModel: 'claude-haiku-4-5-20251001', displayName: 'Haiku 4.5', description: 'Fastest for quick answers' },
  { value: 'claude-opus-4-6', resolvedModel: 'claude-opus-4-6', displayName: 'Opus 4.6', description: 'Best for everyday, complex tasks',
    supportsEffort: true, supportedEffortLevels: ['low', 'medium', 'high', 'max'] },
  { value: 'claude-sonnet-4-6', resolvedModel: 'claude-sonnet-4-6', displayName: 'Sonnet 4.6', description: 'Efficient for routine tasks',
    supportsEffort: true, supportedEffortLevels: ['low', 'high', 'max'] },
];
const MODEL_ANSWER = [
  ev({ type: 'system', subtype: 'hook_started', hook_name: 'SessionStart' }),
  'a warning that is not JSON\n',
  ev({ type: 'control_response', response: { subtype: 'success', request_id: 'scholium-models',
       response: { models: MODELS, account: { email: 'someone@example.com' }, commands: [] } } }),
];
// Codex: where its copies are and what they answer to --version (h0 holds no codex.exe; the one in
// .local/bin does not answer)
const CODEX_BIN = '/localappdata/OpenAI/Codex/bin';
const CODEX_APP = CODEX_BIN + '/h1/codex.exe';
const CODEX_NPM = '/appdata/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe';
const CODEX_VERSIONS = {
  [CODEX_BIN + '/codex.exe']: 'codex-cli 0.130.0-alpha.5\n',
  [CODEX_APP]: 'codex-cli 0.160.0\n',
  [CODEX_NPM]: 'codex-cli 0.144.0\n',
  '/home/u/.cargo/bin/codex.exe': 'codex-cli 0.160.0-alpha.3\n',
  '/home/u/.local/bin/codex.exe': '',
};
// what model/list answers (abridged)
const CODEX_LEVELS = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'].map(reasoningEffort => ({ reasoningEffort, description: '' }));
const CODEX_MODELS = [
  { id: 'gpt-6.1-sol', model: 'gpt-6.1-sol', displayName: 'GPT-6.1-Sol', description: 'Latest workhorse model', hidden: false, isDefault: true,
    supportedReasoningEfforts: CODEX_LEVELS, defaultReasoningEffort: 'low' },
  { id: 'gpt-6-astra', model: 'gpt-6-astra', displayName: 'GPT-6-Astra', description: 'Frontier intelligence', hidden: false, isDefault: false,
    supportedReasoningEfforts: CODEX_LEVELS, defaultReasoningEffort: 'medium' },
  { id: 'gpt-6-luna', model: 'gpt-6-luna', displayName: 'GPT-6-Luna', description: 'Fast and affordable', hidden: false, isDefault: false,
    supportedReasoningEfforts: CODEX_LEVELS.slice(0, 5), defaultReasoningEffort: 'medium' },
  { id: 'gpt-reserve', model: 'gpt-reserve', displayName: 'GPT-Reserve', description: 'Hidden', hidden: true, isDefault: false,
    supportedReasoningEfforts: CODEX_LEVELS, defaultReasoningEffort: 'medium' },
  { id: 'gpt-5.5', model: 'gpt-5.5', displayName: 'GPT-5.5', description: 'Legacy coding model', hidden: false, isDefault: false,
    supportedReasoningEfforts: CODEX_LEVELS.slice(0, 4), defaultReasoningEffort: 'medium' },
];
// the notifications of a Codex turn; TURN stands for the id that turn/start gave
const note = (method, params) => ev({ method, params });
const coItem = (phase, item) => note('item/' + phase, { item, threadId: 'T1', turnId: 'TURN' });
const PWSH = '"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command ';
const shell = (id, command, done) => coItem(done ? 'completed' : 'started', Object.assign(
  { type: 'commandExecution', id, command: PWSH + "'" + command + "'", status: done ? done.status || 'completed' : 'inProgress' },
  done ? { exitCode: done.exitCode === undefined ? 0 : done.exitCode, aggregatedOutput: done.output } : {}));
const tok = (inputTokens, cachedInputTokens, outputTokens) => ({ totalTokens: inputTokens + outputTokens, inputTokens, cachedInputTokens,
                                                                cacheWriteInputTokens: 0, outputTokens, reasoningOutputTokens: 0 });
const usage = (total, last) => note('thread/tokenUsage/updated', { threadId: 'T1', turnId: 'TURN', tokenUsage: { total, last, modelContextWindow: null } });
const turnDone = turn => note('turn/completed', { threadId: 'T1', turn: Object.assign({ id: 'TURN', items: [], error: null, durationMs: null }, turn) });
const CODEX_SCRIPT = [
  note('mcpServer/startupStatus/updated', { name: 'node_repl', status: 'ready' }),
  note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
  coItem('completed', { type: 'userMessage', id: 'm0', content: [] }),
  coItem('completed', { type: 'reasoning', id: 'r1', summary: ['Planning the steps'], content: [] }),
  note('item/agentMessage/delta', { itemId: 'a1', delta: '先' }),
  coItem('completed', { type: 'agentMessage', id: 'a1', text: '先提取句子。' }),
  shell('c1', 'python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json'),
  note('item/commandExecution/outputDelta', { itemId: 'c1', delta: '412' }),
  shell('c1', 'python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json', { output: '412 sentences -> s.json\n1\n2\n3\n4\n5' }),
  usage(tok(100000, 60000, 1000), tok(100000, 60000, 1000)),
  shell('c2', 'Get-Content D:\\Zotero\\tmp\\scholium\\ATT1\\sentences.txt'),
  shell('c2', 'Get-Content D:\\Zotero\\tmp\\scholium\\ATT1\\sentences.txt', { output: '[1] First sentence.' }),
  ev({ id: 'q1', method: 'item/commandExecution/requestApproval', params: { threadId: 'T1', turnId: 'TURN', itemId: 'c9', command: 'pip install x' } }),
  ev({ id: 'q2', method: 'item/tool/requestUserInput', params: { threadId: 'T1', turnId: 'TURN', itemId: 'u1', questions: [] } }),
  ev({ id: 'q3', method: 'account/chatgptAuthTokens/refresh', params: {} }),
  coItem('completed', { type: 'fileChange', id: 'f1', status: 'completed',
                        changes: [{ path: 'D:\\Zotero\\tmp\\scholium\\ATT1\\config.json', kind: { type: 'add' }, diff: '' }] }),
  shell('c3', 'python C:/skills/scholium.py --config c.json'),
  shell('c3', 'python C:/skills/scholium.py --config c.json', { exitCode: 2, status: 'failed', output: 'style_warnings: 1' }),
  usage(tok(1300000, 1200000, 21000), tok(1200000, 1140000, 20000)),
  shell('c4', 'python C:/skills/scholium.py --config c.json --apply'),
  shell('c4', 'python C:/skills/scholium.py --config c.json --apply', { output: '{"applied": true}' }),
  note('account/rateLimits/updated', { rateLimits: { limitId: 'codex', primary: { usedPercent: 40, windowDurationMins: 10080,
                                                                                    resetsAt: Math.floor(Date.now() / 1000) + 259200 }, secondary: null } }),
  coItem('completed', { type: 'agentMessage', id: 'a2', text: 'Done.\n' + SUMMARY }),
  usage(tok(2600000, 2410000, 46778), tok(1300000, 1210000, 25778)),
  turnDone({ status: 'completed', durationMs: 376500 }),
];
// a follow-up in the same thread: the totals include the earlier turn
const CODEX_FOLLOW = [
  note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
  coItem('completed', { type: 'agentMessage', id: 'a3', text: '改好了：第 5 页的译文已缩短。' }),
  usage(tok(3000000, 2800000, 50000), tok(400000, 390000, 3222)),
  turnDone({ status: 'completed', durationMs: 65000 }),
];
const CODEX_RESET = Math.floor(Date.now() / 1000) + 7200;
const CODEX_LIMIT = [
  note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
  coItem('completed', { type: 'agentMessage', id: 'a1', text: '先提取句子。' }),
  note('account/rateLimits/updated', { rateLimits: { limitId: 'codex',
    primary: { usedPercent: 100, windowDurationMins: 300, resetsAt: CODEX_RESET },
    secondary: { usedPercent: 90, windowDurationMins: 10080, resetsAt: CODEX_RESET + 259200 } } }),
  note('error', { error: { message: "You've hit your usage limit.", codexErrorInfo: 'usageLimitExceeded' }, willRetry: false, threadId: 'T1', turnId: 'TURN' }),
  turnDone({ status: 'failed', error: { message: "You've hit your usage limit. Try again at 9:00 PM.", codexErrorInfo: 'usageLimitExceeded' } }),
];
const CODEX_INIT = ev({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T1' });
const CODEX_RESULT = ev({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: 'Done.\n' + SUMMARY, session_id: 'T1',
                          duration_ms: 376500, num_turns: 3,
                          usage: { input_tokens: 190000, cache_creation_input_tokens: 0, cache_read_input_tokens: 2410000, output_tokens: 46778 } });
class El {
  constructor(tag) { this.tagName = tag; this.attrs = {}; this.listeners = {}; this.hidden = false; this.disabled = false; this._text = '';
                     this.title = ''; this.className = ''; this.value = ''; this.parent = null; this.children = []; this.removed = false;
                     this.scrollTop = 0; this.clientHeight = 100; this.isConnected = true; this.style = {}; }
  get scrollHeight() { return this.children.length * 20; }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join('') : this._text; }
  set textContent(v) { this.children = []; this._text = String(v); }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === 'style') { const m = /(?:^|;)\s*height:\s*([^;]+)/.exec(String(v)); this.style = { height: m ? m[1].trim() : '' }; }
  }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  click() { for (const f of this.listeners.click || []) f({}); }
  type(value) { this.value = value; for (const f of this.listeners.input || []) f({}); }
  focus() { this.focused = true; }
  change(value) { this.value = value; for (const f of this.listeners.change || []) f({}); }
  append(...nodes) { for (const n of nodes) { if (n && typeof n === 'object') n.parent = this; this.children.push(n); } }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  insertBefore(n) { this.append(n); }
  querySelector() { return null; }
  closest() { return null; }
  remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; }
}

function harness({ locale = 'zh-CN', prefs = {}, existing = [], confirm = true, exitCode = 0, script = null, claudeExists = true, gateFirst = false,
                   home = 'dirsvc', eraseFails = false, logs = {}, models = 'ok', claudeAt = CLAUDE, scripts = [], readFails = false,
                   writeFails = false, codex = {}, logTimes = {}, notes = [], secondPdf = false } = {}) {
  const log = { calls: [], stdin: [], notices: [], alerts: [], confirms: [], kills: 0, menus: [], unregistered: [], listeners: [],
                writes: Object.assign({}, logs), notifications: [], revealed: [], erased: [], sections: [], unregisteredSections: [],
                ftl: [], tabs: [], selected: [], scrolled: [], modelCalls: [], modelStdin: [], modelStdinClosed: false, modelKills: 0,
                madeDirs: [], trashed: [], versionCalls: [], codexCalls: [], codexProcs: [], codexKills: 0, codexTurns: 0,
                mtimes: Object.assign({}, logTimes), clock: 10 };
  const co = Object.assign({ versions: CODEX_VERSIONS, scripts: [], skillAt: '/data', fail: null, failMessage: '' }, codex);
  const files = new Set((claudeExists ? [claudeAt] : []).concat(Object.keys(co.versions)));
  // 97-character chunks split JSON lines; 'WAIT' holds the stream open until the process is killed
  const chunksFor = (n) => {
    const entries = scripts[n] || (n === 0 && gateFirst ? SCRIPT.concat(['WAIT']) : script || SCRIPT.concat([LAST, RESULT]));
    const out = [];
    for (const e of entries) {
      if (e === 'WAIT') { out.push('WAIT'); continue; }
      for (let i = 0; i < e.length; i += 97) out.push(e.slice(i, i + 97));
    }
    return out;
  };
  class Proc {
    constructor() { this.chunks = chunksFor(log.calls.length); this.killed = false; this.gate = null; }
    get stdin() { return { write: async s => { log.stdin.push(s); }, close: async () => {} }; }
    get stdout() {
      const self = this;
      return { readString: async () => {
        await tick();
        if (self.killed) return '';
        const c = self.chunks.shift();
        if (c === 'WAIT') { await new Promise(r => { self.gate = r; }); return ''; }
        return c || '';
      } };
    }
    get stderr() { return { readString: async () => '' }; }
    async wait() { return { exitCode: this.killed ? 1 : exitCode }; }
    kill() { log.kills++; this.killed = true; if (this.gate) this.gate(); }
  }
  // the model list request: 'ok' answers, 'silent' ends without an answer (an older Claude Code)
  class ModelProc {
    constructor() {
      this.chunks = [];
      for (const e of (models === 'ok' ? MODEL_ANSWER : MODEL_ANSWER.slice(0, 2))) for (let i = 0; i < e.length; i += 97) this.chunks.push(e.slice(i, i + 97));
      this.killed = false;
    }
    get stdin() { return { write: async s => { log.modelStdin.push(s); }, close: async () => { log.modelStdinClosed = true; } }; }
    get stdout() { const self = this; return { readString: async () => { await tick(); return self.killed ? '' : (self.chunks.shift() || ''); } }; }
    async wait() { return { exitCode: 0 }; }
    kill() { log.modelKills++; this.killed = true; }
  }
  // codex --version
  class VersionProc {
    constructor(path) { this.out = co.versions[path] ? [co.versions[path]] : []; }
    get stdout() { return { readString: async () => { await tick(); return this.out.shift() || ''; } }; }
    async wait() { return { exitCode: 0 }; }
    kill() {}
  }
  // codex app-server: answers each request as Codex does; turn/start plays the next script, in
  // 97-character chunks; 'WAIT' holds the turn until it is interrupted or the server is killed
  class CodexProc {
    constructor() { this.out = []; this.sent = []; this.killed = false; this.wake = null; log.codexProcs.push(this); }
    emit(lines) {
      for (const line of lines) {
        if (line === 'WAIT') break;
        for (let i = 0; i < line.length; i += 97) this.out.push(line.slice(i, i + 97));
      }
      if (this.wake) { const w = this.wake; this.wake = null; w(); }
    }
    get stdin() {
      return { write: async text => { for (const line of String(text).split('\n')) if (line.trim()) this.receive(JSON.parse(line)); },
               close: async () => {} };
    }
    receive(msg) {
      this.sent.push(msg);
      if (typeof msg.method !== 'string' || msg.id === undefined) return;      // an answer of the plugin, or a notification
      const answer = result => this.emit([ev({ id: msg.id, result })]);
      const p = msg.params || {};
      if (co.fail === msg.method) return this.emit([ev({ id: msg.id, error: { code: -32600, message: co.failMessage } })]);
      switch (msg.method) {
        case 'initialize': return answer({ userAgent: 'scholium-bridge/0.160.0', codexHome: '/home/u/.codex' });
        case 'model/list': return answer({ data: CODEX_MODELS, nextCursor: null });
        case 'config/read': return answer({ config: { model: 'gpt-6-astra', mcp_servers: { s: { env: { TOKEN: 'secret-token' } } } } });
        case 'skills/list': return answer({ data: p.cwds.map(cwd => ({ cwd, errors: [], skills: [{ name: 'other', path: '/x/other/SKILL.md', enabled: true }]
          .concat(co.skillAt === cwd ? [{ name: 'zotero-scholium', path: cwd === '/data' ? '/data/.agents/skills/zotero-scholium/SKILL.md'
                                                                                      : '/home/u/.codex/skills/zotero-scholium/SKILL.md', enabled: true }] : []) })) });
        case 'skills/extraRoots/set': return answer({});
        case 'thread/start': return answer({ thread: { id: 'T1' }, model: p.model || 'gpt-6-astra' });
        case 'thread/resume': return answer({ thread: { id: p.threadId }, model: p.model || 'gpt-6-astra' });
        case 'turn/start': {
          log.codexTurns += 1;
          const id = 'U' + log.codexTurns;
          answer({ turn: { id, status: 'inProgress', items: [] } });
          return this.emit((co.scripts[log.codexTurns - 1] || CODEX_SCRIPT).map(l => l.split('"TURN"').join(JSON.stringify(id))));
        }
        case 'turn/interrupt':
          answer({});
          return this.emit([turnDone({ status: 'interrupted' }).split('"TURN"').join(JSON.stringify(p.turnId))]);
      }
      this.emit([ev({ id: msg.id, error: { code: -32601, message: 'unknown method ' + msg.method } })]);
    }
    get stdout() {
      return { readString: async () => {
        await tick();
        while (!this.out.length && !this.killed) await new Promise(r => { this.wake = r; });
        return this.killed ? '' : this.out.shift();
      } };
    }
    get stderr() { return { readString: async () => '' }; }
    async wait() { return { exitCode: this.killed ? 1 : 0 }; }
    kill() { log.codexKills++; this.killed = true; if (this.wake) { const w = this.wake; this.wake = null; w(); } }
  }
  const Subprocess = {
    call: async opts => {
      if (opts.arguments[0] === '--version') { log.versionCalls.push(opts.command); return new VersionProc(opts.command); }
      if (opts.arguments[0] === 'app-server') { log.codexCalls.push(opts); return new CodexProc(); }
      if (opts.arguments.includes('--input-format')) { log.modelCalls.push(opts); return new ModelProc(); }
      const p = new Proc(); log.calls.push({ opts, proc: p }); return p;
    },
    pathSearch: async () => { throw Error('not found'); },
  };
  class ProgressWindow {
    constructor(options) {
      const e = this.entry = { closeOnClick: options && options.closeOnClick, lines: [], errors: 0, descriptions: [], closeTimer: null, shown: false };
      log.notices.push(e);
      this.ItemProgress = class { constructor(icon, text) { e.lines.push(text); } setText(t) { e.lines.push(t); } setProgress() {} setError() { e.errors++; } };
    }
    changeHeadline() {} addDescription(t) { this.entry.descriptions.push(t); } show() { this.entry.shown = true; } startCloseTimer(ms) { this.entry.closeTimer = ms; }
  }
  const annotation = (key, tags) => ({ key, id: key, isAnnotation: () => true, getTags: () => tags.map(tag => ({ tag })) });
  const attachment = (key, parentID, anns) => ({
    key, id: key, parentID, libraryID: 1, attachmentContentType: 'application/pdf',
    isAttachment: () => true, isRegularItem: () => false, isPDFAttachment: () => true,
    getFilePathAsync: async () => `D:/Zotero/storage/${key}/paper.pdf`,
    getAnnotations: () => anns, getDisplayTitle: () => 'att ' + key, getItemTypeIconName: () => 'attachmentPDF',
  });
  const items = new Map();
  // child notes of ITEM1, N0, N1…, with the given tags; trashing takes a note from its paper
  const childNotes = { ITEM1: notes.map((tags, i) => ({ key: 'N' + i, id: 'N' + i, parentID: 'ITEM1', isNote: () => true, isAnnotation: () => false,
                                                         getTags: () => tags.map(tag => ({ tag })) })), ITEM2: [] };
  const regular = (key, att) => ({ key, id: key, libraryID: 1, isRegularItem: () => true, isAttachment: () => false, isPDFAttachment: () => false,
    getBestAttachment: async () => att, getDisplayTitle: () => 'Paper ' + key,
    getAttachments: () => [att.id].concat(secondPdf && key === 'ITEM1' ? ['ATT3'] : [], ['HTML_' + key]),
    getNotes: () => childNotes[key].map(n => n.id) });
  const att1 = attachment('ATT1', 'ITEM1', existing.map((t, i) => annotation('E' + i, t)));
  const att2 = attachment('ATT2', 'ITEM2', []);
  const item1 = regular('ITEM1', att1), item2 = regular('ITEM2', att2);
  const note = { key: 'NOTE', isRegularItem: () => false, isAttachment: () => false, isPDFAttachment: () => false };
  const html = key => ({ key, id: key, attachmentContentType: 'text/html', isAttachment: () => true, isRegularItem: () => false,
                         isPDFAttachment: () => false, getAnnotations: () => { throw Error('not a file attachment with annotations'); } });
  [item1, item2, att1, att2, attachment('ATT3', 'ITEM1', []), html('HTML_ITEM1'), html('HTML_ITEM2'), ...childNotes.ITEM1]
    .forEach(i => items.set(i.id, i));
  const store = new Map(Object.entries(prefs));
  const mainDoc = {
    bar: new El('hbox'),
    documentElement: new El('window'),
    getElementById(id) {
      if (id === 'zotero-items-toolbar') return this.bar;
      if (id === 'zotero-item-details') return { scrollToPane: async (paneID, how) => log.scrolled.push([paneID, how]) };
      return this.documentElement.children.find(c => c.id === id) || null;
    },
    querySelector: sel => (sel === '[href="scholium-bridge.ftl"]' && log.ftl.length ? { remove: () => log.ftl.push('removed') } : null),
    createElementNS: (ns, tag) => new El(tag),
  };
  const mainWin = {
    document: mainDoc,
    MozXULElement: { insertFTLIfNeeded: name => log.ftl.push(name) },
    Zotero_Tabs: { select: id => log.tabs.push(id) },
    ZoteroPane: { selectItem: async id => log.selected.push(id) },
  };
  // the item pane's window: whether the section is scrolled into view, its size, and the window focus
  const observers = { intersection: [], resize: [] };
  let focused = true;
  class IntersectionObserver { constructor(cb) { this.cb = cb; observers.intersection.push(this); } observe(el) { this.el = el; } disconnect() { this.off = true; } }
  class ResizeObserver { constructor(cb) { this.cb = cb; observers.resize.push(this); } observe(el) { this.el = el; } disconnect() { this.off = true; } }
  // the profile sheet goes into the page of the pane's window, over everything; the element that had the focus before
  const lastFocus = new El('button');
  const paneWin = { IntersectionObserver, ResizeObserver, listeners: {},
                    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
                    removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter(g => g !== f); },
                    dispatch(t) { for (const f of this.listeners[t] || []) f({}); } };
  const paneDoc = { createElement: tag => new El(tag), createTextNode: text => ({ textContent: text }), hasFocus: () => focused,
                    defaultView: paneWin, documentElement: new El('window'), activeElement: lastFocus };
  paneWin.document = paneDoc;
  const sheet = () => paneDoc.documentElement.children.find(c => c.id === 'scholium-profile-sheet') || null;
  const see = v => { for (const o of observers.intersection) if (!o.off) o.cb([{ isIntersecting: v }]); };
  const resize = el => { for (const o of observers.resize) if (!o.off && o.el === el) o.cb([]); };
  const focus = v => { focused = v; };
  const timers = [];
  const laterTimeout = (f, ms) => { if (ms < 1000) return setTimeout(f, ms); const t = { f, ms, live: true }; timers.push(t); return t; };
  const clearLater = t => { if (timers.includes(t)) t.live = false; else clearTimeout(t); };
  const fire = () => { for (const t of timers.slice()) if (t.live) { t.live = false; t.f(); } };
  const context = vm.createContext({
    setTimeout: laterTimeout, clearTimeout: clearLater,
    Zotero: {
      debug() {}, locale, DataDirectory: { dir: '/data' },
      Libraries: { userLibraryID: 1 },
      Prefs: { get: (n, g) => store.get(n), set: (n, v, g) => store.set(n, v) },
      Items: {
        get: id => (Array.isArray(id) ? id.map(i => items.get(i)).filter(Boolean) : items.get(id) || null),
        getByLibraryAndKey: (lib, key) => (lib === 1 ? items.get(key) || null : null),
        erase: async ids => {
          if (eraseFails) throw Error('library is read-only');
          log.erased.push(...ids);
          for (const a of [att1, att2]) { const keep = a.getAnnotations().filter(x => !ids.includes(x.id)); a.getAnnotations = () => keep; }
        },
        trashTx: async ids => {
          log.trashed.push(...ids);
          for (const k of Object.keys(childNotes)) childNotes[k] = childNotes[k].filter(n => !ids.includes(n.id));
        },
      },
      File: { reveal: p => log.revealed.push(p) },
      getMainWindow: () => mainWin,
      getMainWindows: () => [mainWin],
      Promise: { delay: ms => new Promise(r => setTimeout(r, 5)) },
      ProgressWindow,
      MenuManager: { registerMenu: o => { log.menus.push(o); return 'menu-1'; }, unregisterMenu: id => { log.unregistered.push(id); return true; } },
      ItemPaneManager: { registerSection: o => { log.sections.push(o); return 'scholium-pane'; },
                         unregisterSection: id => { log.unregisteredSections.push(id); return true; } },
      Reader: { registerEventListener: (type, handler, id) => log.listeners.push({ type, handler }),
                unregisterEventListener: (type, handler) => { log.listeners = log.listeners.filter(l => l.handler !== handler); } },
    },
    Services: {
      prompt: { alert: (w, t, m) => log.alerts.push(m),
                confirm: (w, t, m) => { log.confirms.push(m); return Array.isArray(confirm) ? confirm.shift() : confirm; } },
      env: { get: n => (n === 'APPDATA' ? '/appdata' : n === 'LOCALAPPDATA' ? '/localappdata' : n === 'USERPROFILE' && home === 'env' ? '/profile/u' : '') },
      dirsvc: { get: (key, iface) => {
        if (home !== 'dirsvc' || key !== 'Home' || iface !== NSIFILE) throw Error('NS_ERROR_FAILURE');
        return { path: '/home/u' };
      } },
      appinfo: { OS: 'WINNT' },
    },
    Components: {
      classes: { '@mozilla.org/alerts-service;1': { getService: () => ({
        showAlertNotification: (img, title, body) => log.notifications.push({ title, body }) }) } },
      interfaces: { nsIAlertsService: {}, nsIFile: NSIFILE },
    },
    PathUtils: { join: (...p) => {
      if (!p.every(x => typeof x === 'string') || !/^(\/|[A-Za-z]:[\\/])/.test(p[0])) {
        throw Error('PathUtils.join: Could not initialize path: NS_ERROR_FILE_UNRECOGNIZED_PATH');
      }
      return p.join('/');
    }, parent: p => p.replace(/\/[^/]*$/, '') },
    IOUtils: {
      exists: async p => files.has(p) || p in log.writes,
      makeDirectory: async p => { log.madeDirs.push(p); },
      getChildren: async p => { if (p !== CODEX_BIN) throw Error('NotFoundError'); return [CODEX_BIN + '/h0', CODEX_BIN + '/h1']; },
      stat: async p => { if (!(p in log.writes)) throw Error('NotFoundError'); return { lastModified: log.mtimes[p] || 0 }; },
      readUTF8: async p => {
        if (readFails && p === PROFILE_PATH) throw Error('NotReadableError');
        if (!(p in log.writes)) throw Error('missing');
        return log.writes[p];
      },
      writeUTF8: async (p, t, o) => {
        if (writeFails && p === PROFILE_PATH) throw Error('NotAllowedError');
        log.writes[p] = (o && o.mode === 'append' ? (log.writes[p] || '') : '') + t;
        log.mtimes[p] = ++log.clock;
      },
    },
    ChromeUtils: { importESModule: () => ({ Subprocess }) },
  });
  vm.runInContext(source, context);
  const runner = context.ScholiumRunner;
  // the item pane section as Zotero drives it: onItemChange, onRender, onAsyncRender
  const pane = async (item) => {
    const section = log.sections[0];
    const body = new El('div');
    let enabled = null;
    section.onItemChange({ item, setEnabled: v => { enabled = v; } });
    section.onRender({ doc: paneDoc, body, item });
    await section.onAsyncRender({ body });
    return { body, enabled, view: () => {
      const p = runner.panes.get(body);
      if (!p) return null;
      return { model: p.model.value, models: p.model.children.map(o => o.value), modelLabels: p.model.children.map(o => o.textContent),
               effort: p.effort.value, efforts: p.effort.children.map(o => o.value), effortDisabled: p.effort.disabled,
               state: p.state.hidden ? null : p.state.textContent, stateKind: p.state.className,
               annotateDisabled: p.annotate.disabled, removeDisabled: p.remove.disabled,
               cancelHidden: p.cancel.hidden, logDisabled: p.log.disabled, shownKey: p.shownKey, history: p.history,
               entries: p.list.children.map(c => [c.className, c.textContent]), stateTitle: p.state.title,
               resumeHidden: p.resume.hidden, stateDisplay: p.state.style.display, cancelDisplay: p.cancel.style.display,
               sendHidden: p.send.hidden, sendDisabled: p.send.disabled, placeholder: p.input.placeholder };
    }, pane: () => runner.panes.get(body) };
  };
  const styles = () => mainDoc.documentElement.children.map(c => [c.tagName, c.id, c.attrs.rel, c.attrs.href]);
  return { runner, log, item1, item2, att1, att2, note, pane, store, see, resize, focus, observers, timers, fire, styles, sheet, paneWin, paneDoc, lastFocus,
           chromePackage: context.chromePackage,
           live: () => timers.filter(t => t.live).map(t => t.ms), toolbarItems: () => mainDoc.bar.children.length };
}
const notice = n => ({ closeOnClick: n.closeOnClick, errors: n.errors, descriptions: n.descriptions, closeTimer: n.closeTimer, shown: n.shown });

(async () => {
  const facts = {};

  // registration, the item pane before, during and after a run, notices, shutdown
  {
    const h = harness();
    const { runner, log, item1, item2, note } = h;
    runner.start('scholium-bridge@zotero-scholium');
    const sec = log.sections[0];
    facts.section = { paneID: sec.paneID, header: sec.header, sidenav: sec.sidenav, ftl: log.ftl.slice(), styles: h.styles() };
    facts.contextMenus = { menus: log.menus.length, readerListeners: log.listeners.length };

    const before = await h.pane(item1);
    const forNote = await h.pane(note);
    await settle(40);                               // Claude Code answers the model list request
    facts.paneBefore = { enabled: before.enabled, noteEnabled: forNote.enabled, view: before.view() };

    const other = await h.pane(item2);             // a second pane: its selects follow the first one
    await settle(20);
    const m = log.modelCalls[0];
    facts.modelRequest = { calls: log.modelCalls.length, command: m.command, args: m.arguments, workdir: m.workdir, stderr: m.stderr,
                           stdin: log.modelStdin.map(s => JSON.parse(s)), closed: log.modelStdinClosed, kills: log.modelKills,
                           accountKept: JSON.stringify(runner.models).includes('someone@example.com') };
    const p1 = before.pane();
    p1.model.change('fable');
    p1.effort.change('high');
    facts.settings = { model: h.store.get('extensions.scholium-bridge.claudeModel'), effort: h.store.get('extensions.scholium-bridge.claudeEffort'),
                       otherModel: other.pane().model.value, otherEffort: other.pane().effort.value };

    // the transcript box: its own background, and a height dragged at its lower edge is kept
    facts.box = { cls: p1.list.className, height: p1.list.style.height };
    p1.list.style.height = '480px';
    h.resize(p1.list);
    facts.resized = { pref: h.store.get('extensions.scholium-bridge.logHeight'), other: other.pane().list.style.height };

    await runner.annotate([item1]);
    await settle(300);
    const call = log.calls[0].opts;
    facts.call = { command: call.command, args: call.arguments, workdir: call.workdir, env: call.environment, append: call.environmentAppend };
    facts.prompt = log.stdin[0];
    facts.notices = log.notices.map(notice);
    facts.logLines = (log.writes['/data/tmp/scholium/ATT1/claude-run.jsonl'] || '').trim().split('\n').length;
    facts.confirmsWithoutExisting = log.confirms.length;
    facts.paneAfter = before.view();
    facts.otherAfter = other.view();
    const toolNode = p1.list.children.find(c => c.className === 'scholium-entry tool');
    facts.look = { state: p1.state.className, tool: toolNode.children.map(c => [c.tagName, c.className]),
                   name: toolNode.children[1].children.map(c => c.tagName || 'text'),
                   buttons: [p1.annotate, p1.cancel, p1.resume, p1.profile, p1.remove, p1.log, p1.send].map(b => b.className),
                   parts: p1.body.children[0].children.map(c => c.className), selects: [p1.agent.className, p1.model.className, p1.effort.className],
                   input: p1.input.className, sendRow: p1.sendRow.className };
    const after = await h.pane(item1);              // rendered anew after the run: the transcript comes from memory
    facts.paneRerendered = after.view();
    facts.heightRerendered = after.pane().list.style.height;
    facts.finished = { notifications: log.notifications };

    before.pane().log.click();
    facts.revealed = log.revealed;

    runner.stop();
    facts.stopped = { sections: log.unregisteredSections, ftl: log.ftl.at(-1), panes: runner.panes.size, toolbarItems: h.toolbarItems(), styles: h.styles().length,
                      observers: h.observers.intersection.concat(h.observers.resize).filter(o => !o.off).length };
  }

  // the saved log of an earlier run is shown for a paper that has one
  {
    const earlier = SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('');
    const h = harness({ logs: { '/data/tmp/scholium/ATT1/claude-run.jsonl': earlier } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    facts.history = p.view();
  }
  {
    const h = harness({ logs: { '/data/tmp/scholium/ATT1/claude-run.jsonl': SCRIPT.slice(0, 4).concat([RESULT]).join('') } });
    h.runner.start('x');
    facts.historyWithoutLastMessage = (await h.pane(h.item1)).view().entries;
  }
  {
    const failed = SCRIPT.slice(0, 3).concat([ev({ type: 'result', subtype: 'error_during_execution', is_error: true,
                                                   result: 'scholium.py: style_warnings remain' })]).join('');
    const h = harness({ logs: { '/data/tmp/scholium/ATT1/claude-run.jsonl': failed } });
    h.runner.start('x');
    facts.failedHistory = (await h.pane(h.item1)).view().entries.at(-1);
  }

  // the saved effort is shown and passed; an unknown one gives medium; an empty model preference passes no --model
  {
    const efforts = {};
    for (const saved of ['xhigh', '', 'auto']) {
      const h = harness({ prefs: { 'extensions.scholium-bridge.claudeEffort': saved, 'extensions.scholium-bridge.claudeModel': '' } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await h.runner.annotate([h.item1]); await settle(300);
      const args = h.log.calls[0].opts.arguments;
      efforts[saved || 'empty'] = { shown: p.view().effort, passed: args[args.indexOf('--effort') + 1], model: args.includes('--model') };
    }
    facts.savedEfforts = efforts;
  }
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.claudeEffort': 'xhigh' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pick = () => { const v = p.view(); return { efforts: v.efforts, effort: v.effort, disabled: v.effortDisabled }; };
    const first = pick();
    p.pane().model.change('claude-opus-4-6');
    const opus46 = pick();
    p.pane().model.change('claude-sonnet-4-6');
    const sonnet46 = pick();
    p.pane().model.change('haiku');
    const haiku = pick();
    await h.runner.annotate([h.item1]); await settle(300);
    const args = h.log.calls[0].opts.arguments;
    p.pane().model.change('opus');
    const backToOpus = p.view().effort;
    p.pane().model.change('');
    await h.runner.annotate([h.item2]); await settle(300);
    const claudeDefault = { model: h.store.get('extensions.scholium-bridge.claudeModel'), passed: h.log.calls[1].opts.arguments.includes('--model') };
    facts.modelEfforts = { first, opus46, sonnet46, haiku, haikuArgs: { model: args[args.indexOf('--model') + 1], effort: args.includes('--effort') },
                           saved: h.store.get('extensions.scholium-bridge.claudeEffort'), backToOpus, claudeDefault };
  }

  // an older Claude Code without the model list: the default and the chosen model, asked once
  {
    const h = harness({ models: 'silent', prefs: { 'extensions.scholium-bridge.claudeModel': 'claude-sonnet-5-5' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.pane(h.item2);
    await settle(40);
    const v = p.view();
    facts.noModelList = { models: v.models, labels: v.modelLabels, efforts: v.efforts, calls: h.log.modelCalls.length, kills: h.log.modelKills };
  }

  // while the section is on screen in the focused window, it replaces the notices
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const p2 = await h.pane(h.item2);
    h.see(true);
    await h.runner.annotate([h.item1]); await settle(300);
    facts.inView = { notices: h.log.notices.length, notifications: h.log.notifications.length,
                     state: p.view().state, kind: p.view().stateKind, other: p2.view().state, otherKind: p2.view().stateKind };
    h.focus(false);
    await h.runner.annotate([h.item2]); await settle(300);
    facts.unfocused = { notices: h.log.notices.length, notifications: h.log.notifications.map(n => n.title) };
    h.focus(true);
    p.body.checkVisibility = () => false;
    p2.body.checkVisibility = () => false;
    await h.runner.annotate([h.item1]); await settle(300);
    facts.collapsed = { notices: h.log.notices.length };
    p.body.checkVisibility = () => true;
    p2.body.checkVisibility = () => true;
    h.see(false);
    await h.runner.annotate([h.item2]); await settle(300);
    facts.scrolledAway = { notices: h.log.notices.length };
  }
  {
    const h = harness({ existing: [['zotero-scholium'], ['zotero-scholium'], ['mine']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    h.see(true);
    const removed = await h.runner.removeAnnotations([h.item1]);
    facts.deleteInView = { removed, notices: h.log.notices.length, state: p.view().state, kind: p.view().stateKind };
  }

  // extra instructions with a new run, then a follow-up that continues its conversation
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const look = () => { const v = p.view(); return { placeholder: v.placeholder, sendHidden: v.sendHidden, sendDisabled: v.sendDisabled,
                                                       sendRowHidden: p.pane().sendRow.hidden }; };
    const before = look();
    p.pane().input.value = '只标注方法部分';
    p.pane().annotate.click();
    await settle(300);
    const logPath = '/data/tmp/scholium/ATT1/claude-run.jsonl';
    facts.extra = { before, after: look(), prompt: h.log.stdin[0], cleared: p.pane().input.value,
                    firstLogLine: JSON.parse(h.log.writes[logPath].split('\n')[0]), firstEntry: p.view().entries[0] };
    p.pane().input.value = '第 5 页那条译文改短';
    for (const f of p.pane().input.listeners.input) f({});
    facts.extra.typed = look();
    let prevented = false;
    for (const f of p.pane().input.listeners.keydown) f({ key: 'Enter', ctrlKey: true, preventDefault: () => { prevented = true; } });
    await settle(300);
    const args = h.log.calls[1].opts.arguments;
    const entries = p.view().entries;
    const lines = h.log.writes[logPath].trim().split('\n').map(l => JSON.parse(l));
    facts.followUp = { calls: h.log.calls.length, resume: args[args.indexOf('--resume') + 1], prompt: h.log.stdin[1], prevented,
                       cleared: p.pane().input.value, prompts: entries.filter(e => e[0] === 'scholium-entry prompt').map(e => e[1]),
                       entries: entries.length, markers: lines.filter(l => l.type === 'scholium').map(l => l.text),
                       inits: lines.filter(l => l.type === 'system' && l.subtype === 'init').length, state: p.view().state,
                       withoutSession: await h.runner.followUp(h.att2, 'x'), calls2: h.log.calls.length };
  }

  // the usage limit: the queue waits, and the interrupted paper continues its conversation after the reset
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1, h.item2]);
    await settle(300);
    facts.limit = { clock: h.runner.paused && h.runner.clock(h.runner.paused.until), calls: h.log.calls.length,
                    queue: h.runner.queue.map(j => [j.att.key, j.resume || null, j.say === undefined ? null : j.say]), waits: h.live(),
                    state1: p1.view().state, kind1: p1.view().stateKind, state2: p2.view().state, resumeShown: !p1.view().resumeHidden,
                    cancelShown: !p2.pane().cancel.hidden, notices: h.log.notices.map(notice), notifications: h.log.notifications.slice(),
                    last: p1.view().entries.at(-1),
                    followUpWhileQueued: await h.runner.followUp(h.att1, 'x'), queued: h.runner.queue.length };
    h.fire();
    await settle(800);
    const lines = h.log.writes['/data/tmp/scholium/ATT1/claude-run.jsonl'].trim().split('\n').map(l => JSON.parse(l));
    const args = h.log.calls[1].opts.arguments;
    facts.limitResumed = { calls: h.log.calls.length, resume: args[args.indexOf('--resume') + 1], prompt: h.log.stdin[1],
                           order: h.log.stdin.map(s => (s.match(/附件 key：(\w+)/) || [null, 'continue'])[1]),
                           entries: p1.view().entries.map(e => e[1]), markers: lines.filter(l => l.type === 'scholium').map(l => l.subtype),
                           inits: lines.filter(l => l.type === 'system' && l.subtype === 'init').length, state1: p1.view().state,
                           notifications: h.log.notifications.map(n => n.title), paused: h.runner.paused, waits: h.live() };
  }
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(RATE_LIMITED)] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1, h.item2]);
    await settle(300);
    facts.retry = { clock: h.runner.paused && h.runner.clock(h.runner.paused.until), waits: h.live(), state1: p1.view().state };
    p2.pane().cancel.click();                       // the waiting paper leaves the queue
    facts.retry.queue = h.runner.queue.map(j => j.att.key);
    p1.pane().resume.click();                       // continue now
    await settle(300);
    const args = h.log.calls[1].opts.arguments;
    facts.retry.after = { calls: h.log.calls.length, resume: args[args.indexOf('--resume') + 1], waits: h.live(), paused: h.runner.paused,
                          state1: p1.view().state, state2: p2.view().state };
  }
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(RATE_LIMITED)] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(300);
    p1.pane().cancel.click();                       // the interrupted paper leaves the queue, which ends the pause
    facts.pauseCancelled = { queue: h.runner.queue.length, paused: h.runner.paused, waits: h.live(), calls: h.log.calls.length };
  }

  // the content folder's chrome address carries the version, and every address of the plugin follows it
  {
    const h = harness();
    h.runner.chrome = 'chrome://' + h.chromePackage('0.1.3.10022049') + '/content/';
    h.runner.start('x');
    const sec = h.log.sections[0];
    facts.versioned = { pkg: h.chromePackage('0.1.3.10022049'), release: h.chromePackage('0.2.0'), icons: [sec.header.icon, sec.sidenav.icon],
                        style: h.styles()[0][3] };
  }

  // the personal profile: profile.md as it is, in a sheet over the Zotero window
  {
    const CRLF = PROFILE.replace(/\n/g, '\r\n');
    const h = harness({ logs: { [PROFILE_PATH]: CRLF }, confirm: [false, false] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const q = p.pane();
    const button = { text: q.profile.textContent, cls: q.profile.className };
    q.profile.click(); await settle(20);
    const root = h.sheet();
    const box = root.children[0];
    const [head, panes, foot] = box.children;
    const [input, preview] = panes.children;
    const [status, , cancel, save] = foot.children;
    const [title, about, pathLine] = head.children;
    const view = () => ({ status: status.textContent, error: status.className.includes('error'), saveDisabled: save.disabled,
                          inputDisabled: input.disabled, open: !!h.sheet() });
    const focusListeners = () => (h.paneWin.listeners.focus || []).length;
    const f = { button, root: [root.className, root.id], box: [box.className, box.attrs.role, box.attrs['aria-label']],
                title: [title.className, title.textContent], panes: [panes.className, input.className, preview.className],
                previewed: preview.children.length,
                head: [about, pathLine].map(c => [c.className, c.textContent]), pathTitle: pathLine.title,
                buttons: [cancel.textContent, save.textContent, cancel.className, save.className],
                text: input.value, focused: !!input.focused, opened: view(), unchanged: h.log.writes[PROFILE_PATH] === CRLF,
                focusListeners: focusListeners() };
    input.focused = false;
    q.profile.click(); await settle(20);
    f.again = { sheets: h.paneDoc.documentElement.children.filter(c => c.id === 'scholium-profile-sheet').length, focused: !!input.focused };
    input.type(input.value + '- 页边批注用蓝色\n');
    f.edited = view();
    let k = key(box, { key: 's', ctrlKey: true }); await settle(20);
    f.ctrlS = { prevented: k.defaultPrevented, stopped: k.stopped, saved: h.log.writes[PROFILE_PATH], view: view(), dirs: h.log.madeDirs.slice() };
    input.type(input.value + '- 公式不高亮\n');
    k = key(box, { key: 'Escape' });
    f.escape = { prevented: k.defaultPrevented, stopped: k.stopped, view: view() };
    cancel.click();
    f.cancel = view();
    save.click(); await settle(20);
    f.saved = { text: h.log.writes[PROFILE_PATH], view: view(), confirms: h.log.confirms.slice(), focusListeners: focusListeners(),
                refocused: !!h.lastFocus.focused };
    facts.profile = f;
  }
  {
    // a missing profile: the template, written on saving
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().profile.click(); await settle(20);
    const [, panes, foot] = h.sheet().children[0].children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    const before = { status: status.textContent, saveDisabled: save.disabled, written: PROFILE_PATH in h.log.writes, text: input.value };
    save.click(); await settle(20);
    facts.profileCreated = { before, saved: h.log.writes[PROFILE_PATH], dirs: h.log.madeDirs, open: !!h.sheet(), confirms: h.log.confirms.length };
  }
  {
    // the file changed elsewhere: asked before overwriting; back in Zotero, an unedited text follows the file
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, confirm: [false, true] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().profile.click(); await settle(20);
    const [, panes, foot] = h.sheet().children[0].children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    const f = {};
    h.log.writes[PROFILE_PATH] = PROFILE + '- 新统计\n';
    h.paneWin.dispatch('focus'); await settle(20);
    f.reloaded = input.value;
    input.type(input.value + '- 我的修改\n');
    h.log.writes[PROFILE_PATH] = PROFILE + '- 再次统计\n';
    h.paneWin.dispatch('focus'); await settle(20);
    f.keptEdits = input.value.endsWith('- 我的修改\n');
    save.click(); await settle(20);
    f.refused = { confirms: h.log.confirms.slice(), file: h.log.writes[PROFILE_PATH], status: status.textContent,
                  error: status.className.includes('error'), open: !!h.sheet() };
    save.click(); await settle(20);
    f.overwritten = { file: h.log.writes[PROFILE_PATH], open: !!h.sheet(), confirms: h.log.confirms.length };
    facts.profileElsewhere = f;
  }
  {
    // the preview beside the text: the text as Markdown as it is typed, scrolled with the text
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().profile.click(); await settle(20);
    const [input, preview] = h.sheet().children[0].children[1].children;
    input.type(input.value + '- **新规则**：`#2ea8e5` 用于方法\n');
    const f = { tree: preview.children.map(tree) };
    // the text box scrolled to 3/4 of its room: the preview goes to 3/4 of its own
    Object.defineProperty(input, 'scrollHeight', { value: 1100 });
    Object.defineProperty(preview, 'scrollHeight', { value: 2100 });
    input.scrollTop = 750;
    for (const g of input.listeners.scroll || []) g({});
    f.scrolled = preview.scrollTop;
    // typing moves the text box without a scroll event of its own: the rebuilt preview follows
    input.scrollTop = 500;
    input.type(input.value + '- x\n');
    f.scrolledAfterTyping = preview.scrollTop;
    facts.profilePreview = f;
  }
  {
    // an unedited text, which changes on disk: the preview follows the file
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().profile.click(); await settle(20);
    const [, preview] = h.sheet().children[0].children[1].children;
    h.log.writes[PROFILE_PATH] = PROFILE + '- 新统计\n';
    h.paneWin.dispatch('focus'); await settle(20);
    facts.profilePreviewReload = tree(preview.children[preview.children.length - 1]);
  }
  {
    // Markdown as the preview builds it
    const h = harness();
    const sample = ['# Title **bold** #', '', 'Para line one', 'line two with `code` and *em* and [link](https://x.y/z)', '',
                    '## Rules', '', '1. first', '2. second', '   - nested `#ff6666` red', '     continued', '- other list', '  1. inner ordered', '',
                    '> quote **q**', '', '```', '<script>alert(1)</script> **not bold**', '```', '', '---', '3. starts at three', '<b>raw</b>'].join('\r\n');
    facts.markdown = h.runner.renderMarkdown(h.paneDoc, sample).map(tree);
  }
  {
    // a profile that cannot be read is not overwritten; a failed save keeps the sheet and the text
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, readFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().profile.click(); await settle(20);
    const box = h.sheet().children[0];
    const [, panes, foot] = box.children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    key(box, { key: 's', ctrlKey: true }); await settle(20);
    facts.profileUnreadable = { status: status.textContent, error: status.className.includes('error'), inputDisabled: input.disabled,
                                saveDisabled: save.disabled, file: h.log.writes[PROFILE_PATH] === PROFILE, dirs: h.log.madeDirs.length };
  }
  {
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, writeFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().profile.click(); await settle(20);
    const box = h.sheet().children[0];
    const [, panes, foot] = box.children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    input.type(input.value + '- x\n');
    save.click(); await settle(20);
    facts.profileWriteFailed = { status: status.textContent, error: status.className.includes('error'), open: !!h.sheet(),
                                 saveDisabled: save.disabled, kept: input.value.endsWith('- x\n') };
    // Esc, and yes to discarding: closed after one question
    key(box, { key: 'Escape' });
    facts.profileDiscarded = { open: !!h.sheet(), confirms: h.log.confirms.slice() };
  }
  {
    // the window closes, or the plugin shuts down: the sheet goes without asking
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, confirm: false });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().profile.click(); await settle(20);
    h.sheet().children[0].children[1].children[0].type('changed');
    h.runner.removeFromWindow(h.paneWin);
    const unloaded = { open: !!h.sheet(), focusListeners: (h.paneWin.listeners.focus || []).length };
    p.pane().profile.click(); await settle(20);
    h.sheet().children[0].children[1].children[0].type('changed');
    h.runner.stop();
    facts.profileShutdown = { unloaded, open: !!h.sheet(), confirms: h.log.confirms.length };
  }

  // existing scholium annotations: confirm, and refusal starts nothing
  {
    const { runner, log, item1 } = harness({ existing: [['zotero-scholium'], ['zotero-scholium'], ['mine']], confirm: false });
    await runner.annotate([item1]); await settle(50);
    facts.refused = { confirms: log.confirms, calls: log.calls.length };
  }
  {
    const { runner, log, item1 } = harness({ existing: [['zotero-scholium'], ['mine']], confirm: true, locale: 'en-US' });
    await runner.annotate([item1]); await settle(300);
    facts.redo = { calls: log.calls.length, prompt: log.stdin[0] };
  }

  // failure: is_error result, non-zero exit
  {
    const failing = SCRIPT.slice(0, 3).concat([ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'scholium.py: style_warnings remain' })]);
    const h = harness({ script: failing, exitCode: 1 });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]); await settle(300);
    facts.failure = { notices: h.log.notices.map(notice), notifications: h.log.notifications,
                      last: p.view().entries.at(-1), state: p.view().state, kind: p.view().stateKind };
  }

  // cancel while running, from the item pane
  {
    const h = harness({ script: SCRIPT.slice(0, 3).concat(['WAIT']) });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const done = h.runner.annotate([h.item1]);
    await settle(80);
    facts.whileRunning = { view: p.view() };
    p.pane().cancel.click();
    await done; await settle(80);
    facts.cancel = { kills: h.log.kills, current: h.runner.current, last: p.view().entries.at(-1), view: p.view(), state: p.view().state,
                     notices: h.log.notices.map(notice), notifications: h.log.notifications.map(n => n.title) };
  }

  // queue: status while the first paper runs, duplicates ignored, the second follows
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1, h.item2, h.att1]);
    await h.runner.annotate([h.item2]);
    await settle(80);
    facts.queueWhileFirstRuns = { calls: h.log.calls.length, queued: h.runner.queue.length, alerts: h.log.alerts.length,
                                  pane1: p1.view(), pane2: p2.view() };
    h.log.calls[0].proc.kill();
    await settle(500);
    facts.queueDone = { calls: h.log.calls.length, prompts: h.log.stdin.map(s => (s.match(/附件 key：(\w+)/) || [])[1]),
                        notifications: h.log.notifications.map(n => n.title), pane2: p2.view() };
  }
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1]);
    await settle(60);
    facts.otherRunning = { state: p2.view().state, kind: p2.view().stateKind };
    h.log.calls[0].proc.kill();
    await settle(200);
  }
  {
    const { runner, log, item1, item2 } = harness({ gateFirst: true });
    await Promise.all([runner.annotate([item1]), runner.annotate([item2])]);
    await settle(80);
    facts.raceWhileFirstStarts = { calls: log.calls.length, queued: runner.queue.length };
    log.calls[0].proc.kill();
    await settle(500);
    facts.raceDone = log.calls.length;
  }

  // deleting scholium annotations: only the tool's tag, after a confirmation, never a running paper
  {
    const existing = [['zotero-scholium'], ['zotero-scholium', 'personal'], ['mine'], ['zotero-marginalia'], []];
    const h = harness({ existing, notes: [['zotero-scholium'], ['mine'], [], ['zotero-scholium', 'reading']] });
    h.runner.start('x');
    const removed = await h.runner.removeAnnotations([h.item1, h.att1, h.note]);
    facts.deleted = { removed, erased: h.log.erased, remaining: h.att1.getAnnotations().map(a => a.key), confirms: h.log.confirms,
                      notice: notice(h.log.notices.at(-1)), trashed: h.log.trashed, notesLeft: h.item1.getNotes() };
    const again = await h.runner.removeAnnotations([h.item1]);
    facts.deleteNothingLeft = { removed: again, alerts: h.log.alerts };
  }
  {
    // only the tool's note is left: it goes as well
    const h = harness({ notes: [['zotero-scholium']], locale: 'en-US', secondPdf: true });
    h.runner.start('x');
    facts.deleteNoteOnly = { removed: await h.runner.removeAnnotations([h.item2, h.item1]), trashed: h.log.trashed, erased: h.log.erased,
                             confirms: h.log.confirms, notice: notice(h.log.notices.at(-1)).descriptions };
  }
  {
    const h = harness({ existing: [['zotero-scholium']], confirm: false });
    facts.deleteRefused = { removed: await h.runner.removeAnnotations([h.item1]), erased: h.log.erased,
                            remaining: h.att1.getAnnotations().length };
  }
  {
    const h = harness({ existing: [['zotero-scholium']], eraseFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    facts.deleteFails = { removed: await h.runner.removeAnnotations([h.item1]), notice: notice(h.log.notices.at(-1)),
                          state: p.view().state, kind: p.view().stateKind };
  }
  {
    // a second PDF of the paper is free, but the paper's notes stay while its first PDF runs
    const h = harness({ existing: [['zotero-scholium']], gateFirst: true, notes: [['zotero-scholium']], secondPdf: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(60);
    facts.deleteWhileRunning = { removed: await h.runner.removeAnnotations([h.item1]), erased: h.log.erased, trashed: h.log.trashed, alerts: h.log.alerts,
                                 paneButtons: { annotate: p.view().annotateDisabled, remove: p.view().removeDisabled } };
    h.log.calls[0].proc.kill();
    await settle(200);
  }

  // no PDF, Claude missing, preferences, home directory sources
  {
    const { runner, log, note } = harness();
    await runner.annotate([note]); await settle(20);
    facts.noPdf = { alerts: log.alerts, calls: log.calls.length };
  }
  {
    const h = harness({ claudeExists: false });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]); await settle(80);
    facts.noClaude = { calls: h.log.calls.length, modelCalls: h.log.modelCalls.length, notices: h.log.notices.map(notice),
                       notifications: h.log.notifications.map(n => n.title), last: p.view().entries.at(-1), models: p.view().models,
                       state: p.view().state };
  }
  {
    const { runner, log, item1 } = harness({ prefs: { 'extensions.scholium-bridge.claudeModel': 'claude-sonnet-5-5',
      'extensions.scholium-bridge.claudePermissionMode': 'dontAsk' } });
    runner.start('x');
    await runner.annotate([item1]); await settle(300);
    facts.prefArgs = log.calls[0].opts.arguments;
  }
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.claudeModel': 'claude-sonnet-5-5' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    facts.customModelOptions = p.view().models;
  }
  {
    const { runner, log, item1 } = harness({ claudeAt: '/home/u/.local/bin/claude.exe' });
    await runner.annotate([item1]); await settle(300);
    facts.localClaude = log.calls.map(c => c.opts.command);
    facts.defaults = log.calls.map(c => [c.opts.arguments[c.opts.arguments.indexOf('--model') + 1],
                                         c.opts.arguments[c.opts.arguments.indexOf('--effort') + 1]]);
  }
  for (const home of ['env', 'none']) {
    const { runner, log, item1 } = harness({ home });
    await runner.annotate([item1]); await settle(300);
    const args = log.calls.length ? log.calls[0].opts.arguments : null;
    facts['home_' + home] = { calls: log.calls.length, addDir: args && args.includes('--add-dir') ? args[args.indexOf('--add-dir') + 1] : null,
                              notifications: log.notifications.map(n => n.title) };
  }

  // the last line of a run as notices show it
  facts.brief = ['高亮 47 条（核心 13 条），页边批注 24 条，笔记《Cooperative robotic exploration of a planetary skylight surface (v2, 2026-10-04)》，剩余警告：附件未包含补充材料。',
                 '28 highlights (12 core), 9 margin notes, the note title, remaining warnings: none.',
                 '第 5 页的译文已缩短；无剩余警告。', 'a'.repeat(60), '']
    .map(s => harness().runner.brief(s));

  // Codex: the newest of its copies; a configured path as it is; versions in order
  {
    const h = harness();
    facts.codexFound = { path: await h.runner.findCodex(), asked: h.log.versionCalls.slice() };
    const later = harness({ codex: { versions: Object.assign({}, CODEX_VERSIONS, { [CODEX_NPM]: 'codex-cli 0.161.0\n' }) } });
    facts.codexFound.npmNewer = await later.runner.findCodex();
    const h2 = harness({ prefs: { 'extensions.scholium-bridge.codexPath': '/custom/codex.exe' },
                         codex: { versions: { '/custom/codex.exe': 'codex-cli 0.1.0\n' } } });
    facts.codexConfigured = { path: await h2.runner.findCodex(), asked: h2.log.versionCalls.length };
    const h3 = harness({ prefs: { 'extensions.scholium-bridge.codexPath': '/custom/missing.exe' } });
    facts.codexConfiguredMissing = await h3.runner.findCodex();
    facts.codexNewer = [[[0, 160, 0, ''], [0, 160, 0, '-alpha.3']], [[0, 160, 0, '-alpha.3'], [0, 160, 0, '']], [[0, 161, 0, ''], [0, 160, 9, '']],
                        [[0, 9, 0, ''], [0, 10, 0, '']], [[1, 0, 0, ''], [0, 99, 99, '']], [[0, 160, 0, ''], [0, 160, 0, '']]]
      .map(([a, b]) => h.runner.newer(a, b));
    facts.shellCommands = ['"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command \'python a.py\'', "/bin/bash -lc 'ls -la'",
                           'pwsh.exe -NoProfile -Command "Get-Content x"', 'python a.py', '"C:\\x\\other.exe" -c \'x\'', "pwsh -Command 'it''s'"]
      .map(c => h.runner.shellCommand(c));
    facts.codexReset = [null, { primary: { usedPercent: 50, resetsAt: 100 } },
                        { primary: { usedPercent: 100, resetsAt: 100 }, secondary: { usedPercent: 100, resetsAt: 200 } },
                        { primary: { usedPercent: 100, resetsAt: 0 }, secondary: { usedPercent: 99, resetsAt: 300 } }].map(l => h.runner.codexReset(l));
  }

  // Codex chosen in the section: its models, asked from codex app-server; each agent keeps its own choices
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1), other = await h.pane(h.item2);
    await settle(40);
    p.pane().agent.change('codex');
    await settle(200);
    const v = p.view();
    const proc = h.log.codexProcs[0];
    const call = h.log.codexCalls[0];
    facts.codexModels = { agent: h.store.get('extensions.scholium-bridge.agent'), shown: p.pane().agent.value, otherShown: other.pane().agent.value,
                          agents: p.pane().agent.children.map(o => [o.value, o.textContent]),
                          models: v.models, labels: v.modelLabels, model: v.model, efforts: v.efforts, effort: v.effort,
                          call: { command: call.command, args: call.arguments, workdir: call.workdir }, sent: proc.sent.map(m => m.method),
                          hello: proc.sent[0].params, killed: proc.killed, secretKept: JSON.stringify(h.runner.models).includes('secret-token'),
                          calls: h.log.codexCalls.length };
    p.pane().model.change('gpt-5.5');
    p.pane().effort.change('max');                 // not a level of GPT-5.5
    facts.codexModels.legacy = { efforts: p.view().efforts, effort: p.view().effort };
    p.pane().model.change('gpt-6-luna');
    p.pane().effort.change('high');
    facts.codexModels.chosen = { model: h.store.get('extensions.scholium-bridge.codexModel'), effort: h.store.get('extensions.scholium-bridge.codexEffort'),
                                 claudeModel: h.store.get('extensions.scholium-bridge.claudeModel') || null,
                                 claudeEffort: h.store.get('extensions.scholium-bridge.claudeEffort') || null, otherModel: other.pane().model.value };
    p.pane().agent.change('claude');
    await settle(40);
    facts.codexModels.back = { model: p.view().model, effort: p.view().effort, labels: p.view().modelLabels.slice(0, 2) };
    p.pane().agent.change('codex');
    await settle(40);
    facts.codexModels.again = { model: p.view().model, effort: p.view().effort, calls: h.log.codexCalls.length };
  }

  // a Codex run, then a follow-up in the same conversation while Claude Code is chosen
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.codexModel': 'gpt-6-luna',
                                 'extensions.scholium-bridge.codexEffort': 'high' }, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    const before = h.log.codexCalls.length;
    await h.runner.annotate([h.item1]);
    await settle(500);
    const call = h.log.codexCalls[before];
    const sent = h.log.codexProcs[before].sent;
    const req = m => sent.find(x => x.method === m);
    const logPath = '/data/tmp/scholium/ATT1/codex-run.jsonl';
    const lines = () => h.log.writes[logPath].trim().split('\n').map(l => JSON.parse(l));
    const turn = req('turn/start').params;
    facts.codexRun = {
      call: { command: call.command, args: call.arguments, workdir: call.workdir, env: call.environment, append: call.environmentAppend },
      methods: sent.filter(m => typeof m.method === 'string').map(m => m.method),
      skillLists: sent.filter(m => m.method === 'skills/list').map(m => m.params.cwds),
      roots: req('skills/extraRoots/set').params.extraRoots,
      thread: req('thread/start').params,
      turn: Object.assign({}, turn, { input: turn.input.map(i => (i.type === 'text' ? { type: 'text', elements: i.text_elements } : i)) }),
      prompt: turn.input[0].text,
      answers: sent.filter(m => m.method === undefined),
      dirs: h.log.madeDirs.slice(),
      entries: p.view().entries, state: p.view().state, stateTitle: p.view().stateTitle,
      logged: lines().map(l => l.method || l.type), init: lines().find(l => l.type === 'system'), result: lines().find(l => l.type === 'result'),
      killed: h.log.codexProcs[before].killed, session: h.runner.sessions.get('ATT1'), notices: h.log.notices.map(notice),
      sendShown: !p.view().sendHidden, claudeCalls: h.log.calls.length,
    };
    p.pane().log.click();
    facts.codexRun.revealed = h.log.revealed.slice();
    p.pane().agent.change('claude');
    p.pane().input.value = '第 5 页那条译文改短';
    for (const f of p.pane().input.listeners.input) f({});
    p.pane().send.click();
    await settle(500);
    const sent2 = h.log.codexProcs.at(-1).sent;
    facts.codexFollowUp = { claudeCalls: h.log.calls.length, methods: sent2.filter(m => typeof m.method === 'string').map(m => m.method),
                            resume: sent2.find(m => m.method === 'thread/resume').params, input: sent2.find(m => m.method === 'turn/start').params.input,
                            effort: sent2.find(m => m.method === 'turn/start').params.effort, state: p.view().state,
                            entries: p.view().entries.slice(-4), results: lines().filter(l => l.type === 'result').length,
                            markers: lines().filter(l => l.type === 'scholium').map(l => l.text) };
  }

  // a Codex step by step: the skill, then the extraction, while the turn runs; cancelling interrupts the turn
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT.slice(0, 7).concat(['WAIT'])] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(300);
    const during = p.view().state;
    p.pane().cancel.click();
    await settle(300);
    const proc = h.log.codexProcs.at(-1);
    const logged = h.log.writes['/data/tmp/scholium/ATT1/codex-run.jsonl'].trim().split('\n').map(l => JSON.parse(l));
    facts.codexCancel = { during, interrupt: proc.sent.find(m => m.method === 'turn/interrupt').params, killed: proc.killed,
                          last: p.view().entries.at(-1), state: p.view().state, results: logged.filter(l => l.type === 'result').length,
                          waits: h.live(), current: h.runner.current };
  }
  {
    // the turn has begun with the skill: its first step; shutting down does not wait for the turn to end
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT.slice(0, 2).concat(['WAIT'])] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(300);
    facts.codexCancel.begun = p.view().state;
    h.runner.stop();
    facts.codexCancel.shutdown = h.log.codexProcs.at(-1).killed;
    await settle(100);
  }
  {
    // the skill in Codex's own skills folder: no extra root; no skill at all: the prompt alone
    const found = {};
    for (const skillAt of ['/data/tmp/scholium', null]) {
      const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { skillAt } });
      h.runner.start('x');
      await h.runner.annotate([h.item1]);
      await settle(400);
      const sent = h.log.codexProcs.at(-1).sent;
      found[skillAt || 'none'] = { methods: sent.filter(m => typeof m.method === 'string').map(m => m.method).filter(m => m.startsWith('skills/')),
                                   input: sent.find(m => m.method === 'turn/start').params.input.slice(1),
                                   model: 'model' in sent.find(m => m.method === 'thread/start').params };
    }
    facts.codexSkillFound = found;
  }

  // the Codex usage limit: the queue waits until the window resets, then the thread continues
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [CODEX_LIMIT, CODEX_FOLLOW] } });
    h.runner.start('x');
    const p1 = await h.pane(h.item1);
    await h.runner.annotate([h.item1, h.item2]);
    await settle(400);
    facts.codexLimit = { clock: h.runner.paused && h.runner.clock(h.runner.paused.until), expected: h.runner.clock(CODEX_RESET * 1000 + 60000),
                         known: h.runner.paused && h.runner.paused.known,
                         queue: h.runner.queue.map(j => [j.att.key, j.agent, j.resume || null]), notifications: h.log.notifications.map(n => n.title),
                         last: p1.view().entries.at(-1), state: p1.view().state };
    h.fire();
    await settle(900);
    const resumed = h.log.codexProcs.find(c => c.sent.some(m => m.method === 'thread/resume'));
    facts.codexLimit.after = { resume: resumed.sent.find(m => m.method === 'thread/resume').params.threadId,
                               prompt: resumed.sent.find(m => m.method === 'turn/start').params.input[0].text,
                               turns: h.log.codexTurns, state: p1.view().state, paused: h.runner.paused };
  }

  // Codex failing: a failed turn; a refused request; no Codex at all
  {
    const failing = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }),
                     coItem('completed', { type: 'agentMessage', id: 'a1', text: '先提取句子。' }),
                     turnDone({ status: 'failed', error: { message: 'stream disconnected before completion',
                                                           codexErrorInfo: { responseStreamDisconnected: { httpStatusCode: 502 } } } })];
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [failing] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(400);
    facts.codexFailed = { entries: p.view().entries.slice(-2), state: p.view().state, kind: p.view().stateKind, paused: h.runner.paused,
                          notices: h.log.notices.map(notice) };
  }
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.codexModel': 'gpt-9' },
                        codex: { fail: 'thread/start', failMessage: 'model gpt-9 is not available' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(400);
    facts.codexRefused = { last: p.view().entries.at(-1), state: p.view().state, killed: h.log.codexProcs.at(-1).killed, turns: h.log.codexTurns };
  }
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { versions: {} } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]);
    await settle(100);
    facts.noCodex = { codexCalls: h.log.codexCalls.length, last: p.view().entries.at(-1), state: p.view().state, models: p.view().models,
                      labels: p.view().modelLabels };
  }

  // the latest log is shown, whichever agent wrote it
  {
    const codexLog = [CODEX_INIT].concat(CODEX_SCRIPT.filter(l => l.includes('item/')), [CODEX_RESULT]).join('');
    const claudeLog = SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('');
    const shown = {};
    for (const [name, times] of [['codex', { claude: 1, codex: 2 }], ['claude', { claude: 3, codex: 2 }]]) {
      const h = harness({ logs: { '/data/tmp/scholium/ATT1/claude-run.jsonl': claudeLog, '/data/tmp/scholium/ATT1/codex-run.jsonl': codexLog },
                          logTimes: { '/data/tmp/scholium/ATT1/claude-run.jsonl': times.claude, '/data/tmp/scholium/ATT1/codex-run.jsonl': times.codex } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      p.pane().log.click();
      shown[name] = { first: p.view().entries[0], count: p.view().entries.length, state: p.view().state, session: h.runner.sessions.get('ATT1'),
                      revealed: h.log.revealed[0] };
    }
    facts.latestLog = shown;
  }

  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    # a file, since the harness is longer than a Windows command line may be
    script = tmp_path_factory.mktemp("bridge") / "harness.js"
    script.write_text(HARNESS, encoding="utf-8")
    completed = subprocess.run([NODE, str(script), str(BRIDGE)], encoding="utf-8", capture_output=True, timeout=180)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


CLAUDE = "/appdata/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
SUMMARY = "高亮 28 条（核心 12 条），页边批注 9 条，笔记《Deep latent》，无剩余警告。"
BRIEF = "高亮 28 条（核心 12 条）\n页边批注 9 条\n无剩余警告"   # the summary in a notice
DONE_NOTICE = ["完成 · 1 分钟"] + BRIEF.split("\n")
DONE_STATE = "完成 · 6 分钟 · 26 轮 · 257 万 token"
TOKEN_DETAIL = "输入 52 · 缓存写入 11.1 万 · 缓存读取 241 万 · 输出 4.7 万"
STARTED = "已在后台开始，通常需要 10–20 分钟。过程和进度见条目侧栏的 Scholium 区块。"
LEVELS = ["low", "medium", "high", "xhigh", "max"]
TRANSCRIPT = [
    ["scholium-entry info", "模型: claude-opus-5-5"],
    ["scholium-entry text", "⏺ 先加载技能，再提取句子。"],
    ["scholium-entry tool", "⏺ Skill(zotero-scholium)"],
    ["scholium-entry result", "⎿ Launching skill: zotero-scholium"],
    ["scholium-entry tool", "⏺ PowerShell(python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json)"],
    ["scholium-entry result", "⎿ 412 sentences -> s.json\n1\n2\n3\n… +2"],
    ["scholium-entry tool", "⏺ Read(D:\\Zotero\\tmp\\scholium\\ATT1\\sentences.txt)"],
    ["scholium-entry tool", "⏺ Write(D:\\Zotero\\tmp\\scholium\\ATT1\\config.json)"],
    ["scholium-entry tool", "⏺ PowerShell(python C:/skills/scholium.py --config c.json)"],
    ["scholium-entry result error", "⎿ Exit code 2\nstyle_warnings: 1"],
    ["scholium-entry tool", "⏺ PowerShell(python C:/skills/scholium.py --config c.json --apply)"],
    ["scholium-entry result", '⎿ {"applied": true}'],
    ["scholium-entry text", "⏺ Done.\n" + SUMMARY],
]


def test_section_is_registered_and_removed_without_menus_or_toolbar_status(facts):
    assert facts["section"] == {
        "paneID": "scholium",
        "header": {"l10nID": "scholium-section", "icon": "chrome://scholium-bridge/content/icon16.svg"},
        "sidenav": {"l10nID": "scholium-sidenav", "icon": "chrome://scholium-bridge/content/icon20.svg"},
        "ftl": ["scholium-bridge.ftl"],
        "styles": [["link", "scholium-bridge-style", "stylesheet", "chrome://scholium-bridge/content/scholium.css"]],
    }
    assert facts["contextMenus"] == {"menus": 0, "readerListeners": 0}
    assert facts["stopped"] == {"sections": ["scholium-pane"], "ftl": "removed", "panes": 0, "toolbarItems": 0, "observers": 0,
                                "styles": 0}


def test_models_come_from_claude_code(facts):
    r = facts["modelRequest"]
    assert r["calls"] == 1 and r["command"] == CLAUDE and r["workdir"] == "/data" and r["stderr"] == "stdout"
    assert r["args"] == ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
    assert r["stdin"] == [{"type": "control_request", "request_id": "scholium-models", "request": {"subtype": "initialize"}}]
    assert r["closed"] is True and r["kills"] == 1 and r["accountKept"] is False
    v = facts["paneBefore"]["view"]
    assert v["models"] == ["", "opus", "fable", "haiku", "claude-opus-4-6", "claude-sonnet-4-6"] and v["model"] == "opus"
    assert v["modelLabels"] == ["Claude Code 默认（Fable 5.1）", "Opus 5.5", "Fable 5.1", "Haiku 4.5", "Opus 4.6", "Sonnet 4.6"]
    assert facts["customModelOptions"] == ["", "opus", "fable", "haiku", "claude-opus-4-6", "claude-sonnet-4-6", "claude-sonnet-5-5"]
    n = facts["noModelList"]
    assert n == {"models": ["", "claude-sonnet-5-5"], "labels": ["Claude Code 默认", "claude-sonnet-5-5"], "efforts": LEVELS,
                 "calls": 1, "kills": 1}
    assert facts["noClaude"]["modelCalls"] == 0 and facts["noClaude"]["models"] == ["", "opus"]


def test_the_latest_opus_runs_at_the_remembered_effort(facts):
    v = facts["paneBefore"]["view"]
    assert v["efforts"] == LEVELS and v["effort"] == "medium" and v["effortDisabled"] is False
    assert facts["defaults"] == [["opus", "medium"]]
    e = facts["modelEfforts"]
    assert e["first"] == {"efforts": LEVELS, "effort": "xhigh", "disabled": False}
    assert e["opus46"] == {"efforts": ["low", "medium", "high", "max"], "effort": "medium", "disabled": False}
    assert e["sonnet46"] == {"efforts": ["low", "high", "max"], "effort": "low", "disabled": False}
    assert e["haiku"] == {"efforts": [""], "effort": "", "disabled": True}
    assert e["haikuArgs"] == {"model": "haiku", "effort": False}
    assert e["saved"] == "xhigh" and e["backToOpus"] == "xhigh"
    assert e["claudeDefault"] == {"model": "", "passed": False}
    assert facts["savedEfforts"] == {
        "xhigh": {"shown": "xhigh", "passed": "xhigh", "model": False},
        "empty": {"shown": "medium", "passed": "medium", "model": False},
        "auto": {"shown": "medium", "passed": "medium", "model": False},
    }


def test_section_offers_model_effort_and_actions(facts):
    b = facts["paneBefore"]
    assert b["enabled"] is True and b["noteEnabled"] is False
    v = b["view"]
    assert (v["annotateDisabled"], v["removeDisabled"], v["cancelHidden"], v["logDisabled"]) == (False, False, True, True)
    assert v["entries"] == [["scholium-entry info", "这篇还没有运行记录。"]] and v["state"] is None
    assert (v["stateDisplay"], v["cancelDisplay"]) == ("none", "none")   # hidden by display: the attribute alone is not enough in Zotero
    assert facts["settings"] == {"model": "fable", "effort": "high", "otherModel": "fable", "otherEffort": "high"}
    args = facts["call"]["args"]
    assert args[args.index("--model") + 1] == "fable" and args[args.index("--effort") + 1] == "high"


def css_rules():
    """The section's stylesheet as {selector: declarations}."""
    text = re.sub(r"/\*.*?\*/", "", (PLUGIN / "content" / "scholium.css").read_text(encoding="utf8"), flags=re.S)
    text = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}", "", text)
    assert text.count("{") == text.count("}")
    return {" ".join(sel.split()): body for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", text)}


def test_section_is_styled_by_its_stylesheet(facts):
    look = facts["look"]
    assert look["parts"] == ["scholium-settings", "scholium-actions", "scholium-state ok", "scholium-caption", "scholium-log",
                             "scholium-composer"]
    assert look["buttons"] == ["scholium-button primary", "scholium-button", "scholium-button", "scholium-button quiet",
                               "scholium-button quiet danger", "scholium-button quiet", "scholium-button primary small"]
    assert look["selects"] == ["scholium-select"] * 3 and look["input"] == "scholium-input"
    assert look["tool"] == [["span", "scholium-bullet"], ["span", "scholium-content"]] and look["name"] == ["b", "text"]
    rules = css_rules()
    for cls in ["scholium-pane", "scholium-settings", "scholium-field", "scholium-select", "scholium-actions", "scholium-spacer",
                "scholium-button", "scholium-state", "scholium-caption", "scholium-log", "scholium-entry", "scholium-bullet",
                "scholium-content", "scholium-composer", "scholium-input", "scholium-send-row", "scholium-hint"]:
        assert any(re.search(r"\." + re.escape(cls) + r"(?![\w-])", sel) for sel in rules), cls
    log = rules[".scholium-log"]
    for part in ("background: var(--material-background)", "color: var(--fill-primary)", "border: var(--material-border-quarternary)",
                 "resize: vertical", "overflow: auto", "min-height: 80px"):
        assert part in log, part
    assert "display: none !important" in rules[".scholium-pane [hidden]"]
    assert "var(--accent-green)" in rules[".scholium-entry.tool .scholium-bullet"]
    assert [sel for sel, body in rules.items() if "monospace" in body] == [".scholium-entry.tool, .scholium-entry.result", "#scholium-profile-sheet .scholium-editor",
                                                                               "#scholium-profile-sheet .scholium-preview code"]
    assert "var(--accent-blue10)" in rules[".scholium-entry.prompt"] and "auto" in rules[".scholium-entry.prompt"]
    assert "var(--accent-blue)" in rules[".scholium-button.primary"] and "var(--accent-red)" in rules[".scholium-button.danger"]
    assert "border-color: var(--accent-blue)" in rules[".scholium-composer:focus-within"]
    for kind, colour in (("running", "blue"), ("ok", "green"), ("error", "red"), ("paused", "orange")):
        assert f"var(--accent-{colour})" in rules[f".scholium-state.{kind}::before"], kind
    assert "animation: scholium-pulse" in rules[".scholium-state.running::before"]


def test_transcript_box_keeps_its_dragged_height(facts):
    box = facts["box"]
    assert box["cls"] == "scholium-log" and box["height"] == "320px"
    assert facts["resized"] == {"pref": 480, "other": "480px"}
    assert facts["heightRerendered"] == "480px"


def test_claude_is_started_headless_in_the_data_directory(facts):
    call = facts["call"]
    assert call["command"] == CLAUDE
    assert call["workdir"] == "/data"
    assert call["env"] == {"PYTHONIOENCODING": "utf-8"} and call["append"] is True
    args = call["args"]
    assert args[:6] == ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "auto"]
    assert args[args.index("--add-dir") + 1] == "/home/u/.claude/skills/zotero-scholium"
    i = args.index("--allowedTools")
    assert args[i + 1:i + 5] == ["Skill", "Read", "Write(/data/tmp/scholium/**)", "Edit(/data/tmp/scholium/**)"]


def test_prompt_names_the_paper_and_the_unattended_rules(facts):
    prompt = facts["prompt"]
    for part in ("zotero-scholium", "条目 key：ITEM1", "附件 key：ATT1", "PDF：D:/Zotero/storage/ATT1/paper.pdf",
                 "输出目录：/data/tmp/scholium/ATT1", "不要向用户提问", "不要启动子代理", "目前没有本工具的注释"):
        assert part in prompt, part
    assert facts["confirmsWithoutExisting"] == 0


def test_section_shows_the_transcript_like_claude_code(facts):
    a = facts["paneAfter"]
    assert a["entries"] == TRANSCRIPT
    assert not any(kind.startswith("scholium-entry final") for kind, _ in a["entries"])
    assert a["state"] == DONE_STATE and a["stateKind"] == "scholium-state ok" and a["stateTitle"] == TOKEN_DETAIL
    assert a["stateDisplay"] == ""
    assert (a["annotateDisabled"], a["cancelHidden"], a["logDisabled"], a["shownKey"]) == (False, True, False, "ATT1")
    assert facts["paneRerendered"]["entries"] == TRANSCRIPT
    o = facts["otherAfter"]
    assert o["entries"] == [["scholium-entry info", "这篇还没有运行记录。"]]
    assert o["state"] == "批注完成：Paper ITEM1" and o["stateKind"] == "scholium-state ok"
    assert facts["logLines"] == 15
    assert facts["revealed"] == ["/data/tmp/scholium/ATT1/claude-run.jsonl"]
    h = facts["history"]
    assert h["history"] is True and h["shownKey"] == "ATT1" and h["logDisabled"] is False
    assert h["entries"] == TRANSCRIPT[:4] + [TRANSCRIPT[-1]]
    assert h["state"] == "上次：" + DONE_STATE and h["stateKind"] == "scholium-state ok" and h["sendHidden"] is False
    assert facts["historyWithoutLastMessage"] == TRANSCRIPT[:4]
    assert facts["failedHistory"] == ["scholium-entry final error", "scholium.py: style_warnings remain"]


def test_corner_notices_close_by_themselves(facts):
    assert facts["notices"] == [
        {"closeOnClick": True, "errors": 0, "descriptions": [STARTED], "closeTimer": 6000, "shown": True},
        {"closeOnClick": True, "errors": 0, "descriptions": DONE_NOTICE, "closeTimer": 6000, "shown": True},
    ]
    assert facts["failure"]["notices"][-1]["errors"] == 1 and facts["failure"]["notices"][-1]["closeTimer"] == 12000
    assert facts["cancel"]["notices"][-1]["closeTimer"] == 12000


def test_a_section_on_screen_replaces_the_notices(facts):
    v = facts["inView"]
    assert (v["notices"], v["notifications"]) == (0, 0)
    assert v["state"] == DONE_STATE and v["kind"] == "scholium-state ok"
    assert v["other"] == "批注完成：Paper ITEM1" and v["otherKind"] == "scholium-state ok"
    assert facts["unfocused"] == {"notices": 2, "notifications": ["批注完成：Paper ITEM2"]}
    assert facts["collapsed"] == {"notices": 4}
    assert facts["scrolledAway"] == {"notices": 6}
    d = facts["deleteInView"]
    assert d == {"removed": 2, "notices": 0, "state": "已删除 1 篇论文上的 2 条 Scholium 批注。", "kind": "scholium-state ok"}


def test_section_shows_running_and_finished_state(facts):
    q = facts["queueWhileFirstRuns"]
    assert q["pane1"]["state"] == "第 6/6 步 写入 Zotero · 已用 1 分钟 · 另有 1 篇排队"
    assert q["pane1"]["stateKind"] == "scholium-state running" and q["pane1"]["cancelHidden"] is False
    assert q["pane2"]["state"] == "排队中，前面还有 1 篇" and q["pane2"]["annotateDisabled"] is True
    w = facts["whileRunning"]["view"]
    assert w["state"] == "第 1/6 步 加载技能 · 已用 1 分钟" and w["stateKind"] == "scholium-state running"
    assert (w["cancelHidden"], w["annotateDisabled"], w["removeDisabled"]) == (False, True, True)
    assert w["entries"] == TRANSCRIPT[:3]
    assert facts["otherRunning"] == {"state": "正在批注另一篇：Paper ITEM1", "kind": "scholium-state info"}
    f = facts["finished"]
    assert f["notifications"] == [{"title": "批注完成：Paper ITEM1", "body": BRIEF}]


def test_notices_put_each_part_of_the_last_line_on_its_own_line(facts):
    assert facts["brief"] == [
        "高亮 47 条（核心 13 条）\n页边批注 24 条\n剩余警告：附件未包含补充材料",
        "28 highlights (12 core)\n9 margin notes\nthe note title\nremaining warnings: none",
        "第 5 页的译文已缩短\n无剩余警告",
        "a" * 39 + "…",
        "",
    ]


def test_existing_annotations_need_confirmation(facts):
    assert facts["refused"]["calls"] == 0
    assert "2 条" in facts["refused"]["confirms"][0] and "1 篇" in facts["refused"]["confirms"][0]
    assert facts["redo"]["calls"] == 1
    assert "already carries 1 annotations of this tool; the user confirmed a complete redo" in facts["redo"]["prompt"]


def test_failure_and_cancel_are_reported(facts):
    f = facts["failure"]
    assert f["last"] == ["scholium-entry final error", "scholium.py: style_warnings remain"]
    assert f["notifications"] == [{"title": "批注失败：Paper ITEM1", "body": "scholium.py: style_warnings remain"}]
    assert f["state"] == "失败 · 1 分钟" and f["kind"] == "scholium-state error"
    c = facts["cancel"]
    assert c["kills"] == 1 and c["current"] is None
    assert c["last"] == ["scholium-entry final error", "已取消"]
    assert c["view"]["cancelHidden"] is True and c["view"]["annotateDisabled"] is False
    assert c["state"] == "已取消 · 1 分钟"
    assert c["notifications"] == ["批注失败：Paper ITEM1"]


def test_papers_run_one_after_another_without_duplicates(facts):
    q = facts["queueWhileFirstRuns"]
    assert (q["calls"], q["queued"], q["alerts"]) == (1, 1, 0)
    done = facts["queueDone"]
    assert done["calls"] == 2 and done["prompts"] == ["ATT1", "ATT2"]
    assert done["notifications"] == ["批注失败：Paper ITEM1", "批注完成：Paper ITEM2"]
    assert done["pane2"]["shownKey"] == "ATT2" and done["pane2"]["entries"][-1] == TRANSCRIPT[-1]
    assert done["pane2"]["state"] == DONE_STATE
    assert facts["raceWhileFirstStarts"] == {"calls": 1, "queued": 1}
    assert facts["raceDone"] == 2


def test_delete_removes_only_the_tools_annotations_and_notes_after_a_confirmation(facts):
    d = facts["deleted"]
    assert d["removed"] == 4 and d["erased"] == ["E0", "E1"]
    assert d["remaining"] == ["E2", "E3", "E4"]
    # the tool's notes go to the trash; the user's stay
    assert d["trashed"] == ["N0", "N3"] and d["notesLeft"] == ["N1", "N2"]
    assert d["confirms"] == ["将删除 1 篇论文上带 zotero-scholium 标签的 2 条批注和 2 篇阅读笔记。"
                             "批注永久删除，不能撤销；笔记移到回收站，可以恢复。你自己的批注和笔记都保留。删除会同步。继续吗？"]
    assert d["notice"] == {"closeOnClick": True, "errors": 0, "descriptions": ["已删除 1 篇论文上的 2 条 Scholium 批注，2 篇笔记已移到回收站。"],
                           "closeTimer": 6000, "shown": True}
    assert facts["deleteNothingLeft"] == {"removed": 0, "alerts": ["所选论文没有 Scholium 批注或笔记。"]}
    n = facts["deleteNoteOnly"]
    assert n["removed"] == 1 and n["trashed"] == ["N0"] and n["erased"] == []
    assert n["confirms"] == ["This deletes 0 annotations and 1 reading notes tagged zotero-scholium on 1 papers. The annotations are "
                             "deleted for good; the notes go to the trash, where they can be restored. Your own annotations and notes "
                             "are kept. The deletion syncs. Continue?"]
    assert n["notice"] == ["Deleted 0 Scholium annotations on 1 papers; 1 notes moved to the trash."]
    assert facts["deleteRefused"] == {"removed": 0, "erased": [], "remaining": 1}
    f = facts["deleteFails"]
    assert f["removed"] == 0 and f["notice"]["errors"] == 1
    assert f["notice"]["descriptions"] == ["删除失败：library is read-only", "已删除 0 篇论文上的 0 条 Scholium 批注。"]
    assert f["state"] == "删除失败：library is read-only" and f["kind"] == "scholium-state error"


def test_delete_skips_a_paper_being_annotated(facts):
    r = facts["deleteWhileRunning"]
    assert r["removed"] == 0 and r["erased"] == [] and r["trashed"] == []
    assert r["alerts"] == ["所选论文没有 Scholium 批注或笔记。\n\n1 篇论文正在批注或排队，不会删除。"]
    assert r["paneButtons"] == {"annotate": True, "remove": True}


def test_missing_pdf_missing_claude_and_preferences(facts):
    assert facts["noPdf"]["calls"] == 0 and len(facts["noPdf"]["alerts"]) == 1
    nc = facts["noClaude"]
    assert nc["calls"] == 0 and nc["notifications"] == ["批注失败：Paper ITEM1"]
    assert nc["last"][0] == "scholium-entry final error" and "extensions.scholium-bridge.claudePath" in nc["last"][1]
    assert nc["notices"][-1]["errors"] == 1 and nc["state"] == "失败"
    args = facts["prefArgs"]
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
    assert args[args.index("--effort") + 1] == "medium"


def test_home_directory_comes_from_the_directory_service_or_the_environment(facts):
    assert facts["localClaude"] == ["/home/u/.local/bin/claude.exe"]
    assert facts["home_env"] == {"calls": 1, "addDir": "/profile/u/.claude/skills/zotero-scholium",
                                 "notifications": ["批注完成：Paper ITEM1"]}
    assert facts["home_none"] == {"calls": 1, "addDir": None, "notifications": ["批注完成：Paper ITEM1"]}


def test_personal_profile_is_edited_as_markdown_over_the_zotero_window(facts):
    f = facts["profile"]
    assert f["button"] == {"text": "个人配置 ↗", "cls": "scholium-button quiet"}
    assert f["root"] == ["scholium-sheet-backdrop", "scholium-profile-sheet"] and f["box"] == ["scholium-sheet", "dialog", "个人配置"]
    assert f["title"] == ["scholium-sheet-title", "个人配置"]
    assert f["panes"] == ["scholium-editor-panes", "scholium-editor", "scholium-preview"] and f["previewed"] == 8
    assert f["head"][0][0] == "scholium-editor-about" and "Interpretation 和 User's rules 两节保持不变" in f["head"][0][1]
    assert f["head"][1] == ["scholium-editor-path", "/data/zotero-scholium/profile.md"]
    assert f["pathTitle"] == "/data/zotero-scholium/profile.md"
    assert f["buttons"] == ["取消", "保存", "scholium-button", "scholium-button primary"]
    # the file as it is, with the line ends of the text box; nothing is written by opening it
    assert "\r" not in f["text"] and f["text"].startswith("# Annotation profile (draft")
    assert f["text"].endswith("- 颜色只有两级：红 = 核心，黄 = 其他\n")
    assert f["focused"] is True and f["unchanged"] is True and f["focusListeners"] == 1
    assert f["opened"] == {"status": "Ctrl+S 保存 · Esc 关闭", "error": False, "saveDisabled": True, "inputDisabled": False, "open": True}
    assert f["again"] == {"sheets": 1, "focused": True}
    assert f["edited"] == {"status": "有未保存的修改", "error": False, "saveDisabled": False, "inputDisabled": False, "open": True}
    # Ctrl+S saves and stays; the file keeps its CRLF line ends; the key goes no further than the sheet
    c = f["ctrlS"]
    assert c["prevented"] is True and c["stopped"] is True and c["dirs"] == ["/data/zotero-scholium"]
    assert c["saved"].endswith("\r\n- 页边批注用蓝色\r\n") and "\n" not in c["saved"].replace("\r\n", "")
    assert re.fullmatch(r"已保存 \d\d:\d\d", c["view"]["status"]) and c["view"]["saveDisabled"] is True and c["view"]["open"] is True
    # unsaved changes: Esc and Cancel ask, and a refusal keeps the sheet
    assert f["escape"]["prevented"] is True and f["escape"]["stopped"] is True and f["escape"]["view"]["open"] is True
    assert f["cancel"] == {"status": "有未保存的修改", "error": False, "saveDisabled": False, "inputDisabled": False, "open": True}
    saved = f["saved"]
    assert saved["text"].endswith("\r\n- 页边批注用蓝色\r\n- 公式不高亮\r\n") and saved["view"]["open"] is False
    assert saved["confirms"] == ["放弃未保存的修改吗？", "放弃未保存的修改吗？"]
    assert saved["focusListeners"] == 0 and saved["refocused"] is True


def test_profile_preview_shows_the_text_as_markdown_as_it_is_typed(facts):
    f = facts["profilePreview"]
    t = f["tree"]
    assert t[0] == ["h1", "Annotation profile (draft derived from the Zotero library)"]
    assert t[1] == ["p", "Based on 466 annotations on 50 papers."]
    assert t[2] == ["ul", ["li", "Colours:", ["ul", ["li", ["code", ["span.scholium-swatch[background-color: #ff6666]"], "#ff6666"], " 75%"]]]]
    assert t[3] == ["h2", "Interpretation (to be completed by the assistant from the statistics and confirmed by the user)"]
    assert t[5][0] == "h2" and t[5][1] == "User's rules (always win)"
    # the unsaved rule is in the preview
    assert t[-1] == ["ul", ["li", "高亮评论 = 中文翻译"], ["li", "颜色只有两级：红 = 核心，黄 = 其他"],
                     ["li", ["strong", "新规则"], "：", ["code", ["span.scholium-swatch[background-color: #2ea8e5]"], "#2ea8e5"], " 用于方法"]]
    # 750 of 1000 in the text box: 1500 of 2000 in the preview; 500 after typing: 1000 in the rebuilt preview
    assert f["scrolled"] == 1500 and f["scrolledAfterTyping"] == 1000
    assert facts["profilePreviewReload"] == ["ul", ["li", "高亮评论 = 中文翻译"], ["li", "颜色只有两级：红 = 核心，黄 = 其他"], ["li", "新统计"]]


def test_markdown_preview_builds_elements_and_never_markup(facts):
    assert facts["markdown"] == [
        ["h1", "Title ", ["strong", "bold"]],
        ["p", "Para line one\nline two with ", ["code", "code"], " and ", ["em", "em"], " and ",
         ["span.scholium-link[title=https://x.y/z]", "link"]],
        ["h2", "Rules"],
        ["ol", ["li", "first"],
               ["li", "second", ["ul", ["li", "nested ", ["code", ["span.scholium-swatch[background-color: #ff6666]"], "#ff6666"],
                                        " red\ncontinued"]]]],
        ["ul", ["li", "other list", ["ol", ["li", "inner ordered"]]]],
        ["blockquote", ["p", "quote ", ["strong", "q"]]],
        ["pre", ["code", "<script>alert(1)</script> **not bold**"]],
        ["hr"],
        ["ol[start=3]", ["li", "starts at three\n<b>raw</b>"]],
    ]


def test_missing_profile_starts_as_the_template_and_is_written_on_saving(facts):
    c = facts["profileCreated"]
    assert c["before"]["status"] == "文件还不存在，保存后创建" and c["before"]["saveDisabled"] is False and c["before"]["written"] is False
    assert c["before"]["text"].startswith("# Annotation profile\n\n## User's rules (always win)\n\nRules recorded in this section take precedence")
    assert c["saved"] == c["before"]["text"] and c["dirs"] == ["/data/zotero-scholium"] and c["open"] is False and c["confirms"] == 0


def test_profile_changed_elsewhere_is_not_overwritten_unasked(facts):
    f = facts["profileElsewhere"]
    assert f["reloaded"].endswith("- 新统计\n") and f["keptEdits"] is True
    r = f["refused"]
    assert r["confirms"] == ["profile.md 在打开后被别处改动过（例如重新统计了文库）。用这里的内容覆盖它吗？"]
    assert r["file"].endswith("- 再次统计\n") and r["status"] == "未保存：文件已被别处改动" and r["error"] is True and r["open"] is True
    o = f["overwritten"]
    assert o["file"].endswith("- 新统计\n- 我的修改\n") and o["open"] is False and o["confirms"] == 2


def test_profile_read_and_write_failures_keep_the_file_and_the_text(facts):
    assert facts["profileUnreadable"] == {"status": "读不到画像文件：NotReadableError", "error": True, "inputDisabled": True,
                                          "saveDisabled": True, "file": True, "dirs": 0}
    assert facts["profileWriteFailed"] == {"status": "保存失败：NotAllowedError", "error": True, "open": True,
                                           "saveDisabled": False, "kept": True}
    assert facts["profileDiscarded"] == {"open": False, "confirms": ["放弃未保存的修改吗？"]}
    assert facts["profileShutdown"] == {"unloaded": {"open": False, "focusListeners": 0}, "open": False, "confirms": 0}


def test_profile_sheet_covers_the_window_in_zotero_colours():
    rules = css_rules()
    backdrop = rules[".scholium-sheet-backdrop"]
    for part in ("position: fixed", "inset: 0", "z-index: 10000"):
        assert part in backdrop, part
    preview = rules["#scholium-profile-sheet .scholium-preview"]
    assert "overflow: auto" in preview and "background: var(--material-background)" in preview
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in rules[".scholium-editor-panes"]
    assert "border-radius: 50%" in rules[".scholium-swatch"]
    assert "background: var(--material-sidepane)" in rules[".scholium-sheet"]
    editor = rules["#scholium-profile-sheet .scholium-editor"]
    assert "background: var(--material-background)" in editor and "color: var(--fill-primary)" in editor
    assert "var(--accent-red)" in rules[".scholium-hint.error"]
    assert not (PLUGIN / "content" / "profile.xhtml").exists()


def test_new_profile_keeps_its_rules_through_a_statistics_run(facts):
    from zotero_scholium import cli
    created = facts["profileCreated"]["saved"]
    assert cli.USER_RULES_MARK in created
    edited = created + "- 页边批注用蓝色\n"
    merged = cli.merge_profile_md("# Annotation profile\n\nBased on 999 annotations.\n\n## Interpretation (x)\n\n- colour meanings: ___\n", edited)
    assert "999 annotations" in merged and merged.rstrip().endswith("- 页边批注用蓝色")


def test_plugin_addresses_carry_the_version(facts):
    v = facts["versioned"]
    assert v["pkg"] == "scholium-bridge-0-1-3-10022049" and v["release"] == "scholium-bridge-0-2-0"
    base = "chrome://scholium-bridge-0-1-3-10022049/content/"
    assert v["icons"] == [base + "icon16.svg", base + "icon20.svg"]
    assert v["style"] == base + "scholium.css"


def test_plugin_ships_the_section_icons_and_localization():
    import xml.dom.minidom
    for name in ("icon16.svg", "icon20.svg"):
        svg = xml.dom.minidom.parse(str(PLUGIN / "content" / name)).documentElement
        assert svg.tagName == "svg" and "context-fill" in svg.toxml()
    assert (PLUGIN / "content" / "scholium.css").is_file()
    for lang in ("en-US", "zh-CN"):
        ftl = (PLUGIN / "locale" / lang / "scholium-bridge.ftl").read_text(encoding="utf8")
        assert "scholium-section =\n    .label = Scholium" in ftl and "scholium-sidenav =\n    .tooltiptext = Scholium" in ftl


def test_extra_instructions_and_follow_ups_continue_the_conversation(facts):
    e = facts["extra"]
    assert e["before"] == {"placeholder": "附加要求（可选），随「批注这篇」一起发送", "sendHidden": True, "sendDisabled": True,
                           "sendRowHidden": True}
    assert "用户的附加要求：\n只标注方法部分\n\n结束时" in e["prompt"] and e["cleared"] == ""
    assert e["firstLogLine"] == {"type": "scholium", "subtype": "prompt", "text": "附加要求：只标注方法部分"}
    assert e["firstEntry"] == ["scholium-entry prompt", "附加要求：只标注方法部分"]
    follow = "接着对话，例如：第 5 页那条译文改短一些"
    assert e["after"] == {"placeholder": follow, "sendHidden": False, "sendDisabled": True, "sendRowHidden": False}
    assert e["typed"] == {"placeholder": follow, "sendHidden": False, "sendDisabled": False, "sendRowHidden": False}
    f = facts["followUp"]
    assert f["calls"] == 2 and f["resume"] == "S1" and f["prevented"] is True and f["cleared"] == ""
    assert f["prompt"].startswith("下面是用户在 Zotero 里针对这篇论文的批注发来的后续要求。仍是无人值守：不要向用户提问，不要启动子代理")
    assert "\n\n第 5 页那条译文改短\n\n结束时最后一行只写一句：改了什么，剩余警告。" in f["prompt"]
    assert f["prompts"] == ["附加要求：只标注方法部分", "第 5 页那条译文改短"]
    assert f["entries"] == 2 * (1 + len(TRANSCRIPT))
    assert f["markers"] == ["附加要求：只标注方法部分", "第 5 页那条译文改短"] and f["inits"] == 2
    assert f["state"] == DONE_STATE
    assert f["withoutSession"] is False and f["calls2"] == 2


def test_usage_limit_pauses_the_queue_and_continues_after_the_reset(facts):
    m = facts["limit"]
    waiting = f"额度已用完，{m['clock']} 重置后自动继续"
    assert m["calls"] == 1 and m["queue"] == [["ATT1", "S1", ""], ["ATT2", None, None]]
    assert len(m["waits"]) == 1 and 7_190_000 < m["waits"][0] <= 7_260_000
    assert m["state1"] == waiting and m["kind1"] == "scholium-state paused"
    assert m["state2"] == "排队中，前面还有 1 篇\n" + waiting
    assert m["resumeShown"] is True and m["cancelShown"] is True
    assert m["notices"][-1]["errors"] == 1 and m["notices"][-1]["descriptions"] == [waiting]
    assert m["notifications"] == [{"title": "Claude 额度已用完", "body": waiting}]
    assert m["last"] == ["scholium-entry text error", "⏺ You've hit your limit · resets 9pm"]
    assert m["followUpWhileQueued"] is False and m["queued"] == 2
    r = facts["limitResumed"]
    assert r["calls"] == 3 and r["resume"] == "S1" and r["order"] == ["ATT1", "continue", "ATT2"]
    assert r["prompt"] == "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。"
    assert "额度已恢复，接着中断的地方继续" in r["entries"] and r["markers"] == ["continue"] and r["inits"] == 2
    assert r["state1"] == DONE_STATE and r["paused"] is None and r["waits"] == []
    assert r["notifications"] == ["Claude 额度已用完", "批注完成：Paper ITEM1", "批注完成：Paper ITEM2"]
    t = facts["retry"]
    assert t["waits"] == [600000] and t["state1"] == f"额度已用完，{t['clock']} 自动重试"
    assert t["queue"] == ["ATT1"]
    a = t["after"]
    assert a["calls"] == 2 and a["resume"] == "S1" and a["waits"] == [] and a["paused"] is None
    assert a["state1"] == DONE_STATE and a["state2"] == "批注完成：Paper ITEM1"
    assert facts["pauseCancelled"] == {"queue": 0, "paused": None, "waits": [], "calls": 1}


CODEX_APP = "/localappdata/OpenAI/Codex/bin/h1/codex.exe"
CODEX_NPM = "/appdata/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
CODEX_LEVELS = ["low", "medium", "high", "xhigh", "max", "ultra"]
CODEX_TRANSCRIPT = [
    ["scholium-entry info", "模型: gpt-6-luna"],
    ["scholium-entry text", "⏺ 先提取句子。"],
    ["scholium-entry tool", "⏺ Shell(python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json)"],
    ["scholium-entry result", "⎿ 412 sentences -> s.json\n1\n2\n3\n… +2"],
    ["scholium-entry tool", "⏺ Shell(Get-Content D:\\Zotero\\tmp\\scholium\\ATT1\\sentences.txt)"],
    ["scholium-entry result", "⎿ [1] First sentence."],
    ["scholium-entry tool", "⏺ Edit(D:\\Zotero\\tmp\\scholium\\ATT1\\config.json)"],
    ["scholium-entry tool", "⏺ Shell(python C:/skills/scholium.py --config c.json)"],
    ["scholium-entry result error", "⎿ style_warnings: 1"],
    ["scholium-entry tool", "⏺ Shell(python C:/skills/scholium.py --config c.json --apply)"],
    ["scholium-entry result", '⎿ {"applied": true}'],
    ["scholium-entry text", "⏺ Done.\n" + SUMMARY],
]


def test_codex_is_the_newest_copy_found(facts):
    f = facts["codexFound"]
    assert f["path"] == CODEX_APP and f["npmNewer"] == CODEX_NPM
    assert f["asked"] == [CODEX_APP, "/localappdata/OpenAI/Codex/bin/codex.exe",
                          "/appdata/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe",
                          "/home/u/.cargo/bin/codex.exe", "/home/u/.local/bin/codex.exe"]
    assert facts["codexConfigured"] == {"path": "/custom/codex.exe", "asked": 0} and facts["codexConfiguredMissing"] is None
    assert facts["codexNewer"] == [True, False, True, False, True, False]
    assert facts["shellCommands"] == ["python a.py", "ls -la", "Get-Content x", "python a.py", "\"C:\\x\\other.exe\" -c 'x'", "it's"]
    assert facts["codexReset"] == [None, None, 200000, None]


def test_codex_models_come_from_its_app_server(facts):
    m = facts["codexModels"]
    assert m["agent"] == "codex" and m["shown"] == "codex" and m["otherShown"] == "codex"
    assert m["agents"] == [["claude", "Claude Code"], ["codex", "Codex"]]
    assert m["call"] == {"command": CODEX_APP, "args": ["app-server"], "workdir": "/data"}
    assert m["sent"] == ["initialize", "initialized", "model/list", "config/read"] and m["killed"] is True
    assert m["hello"]["clientInfo"]["name"] == "scholium-bridge" and m["secretKept"] is False and m["calls"] == 1
    assert m["models"] == ["", "gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-5.5"] and m["model"] == ""
    assert m["labels"] == ["Codex 默认（GPT-6-Astra）", "GPT-6.1-Sol", "GPT-6-Astra", "GPT-6-Luna", "GPT-5.5"]
    assert m["efforts"] == CODEX_LEVELS and m["effort"] == "medium"
    assert m["legacy"] == {"efforts": ["low", "medium", "high", "xhigh"], "effort": "medium"}
    assert m["chosen"] == {"model": "gpt-6-luna", "effort": "high", "claudeModel": None, "claudeEffort": None, "otherModel": "gpt-6-luna"}
    assert m["back"] == {"model": "opus", "effort": "medium", "labels": ["Claude Code 默认（Fable 5.1）", "Opus 5.5"]}
    assert m["again"] == {"model": "gpt-6-luna", "effort": "high", "calls": 1}


def test_codex_runs_the_skill_in_a_sandbox_through_its_app_server(facts):
    r = facts["codexRun"]
    assert r["call"] == {"command": CODEX_APP, "args": ["app-server"], "workdir": "/data/tmp/scholium",
                         "env": {"PYTHONIOENCODING": "utf-8"}, "append": True}
    assert r["methods"] == ["initialize", "initialized", "skills/list", "skills/list", "skills/extraRoots/set", "thread/start", "turn/start"]
    assert r["skillLists"] == [["/data/tmp/scholium"], ["/data"]] and r["roots"] == ["/data/.agents/skills"]
    assert r["thread"] == {"cwd": "/data/tmp/scholium", "approvalPolicy": "on-request", "approvalsReviewer": "auto_review",
                           "sandbox": "workspace-write", "serviceName": "scholium-bridge", "model": "gpt-6-luna"}
    roots = ["/data/tmp/scholium", "/data/zotero-scholium", "/appdata/zotero-scholium"]
    assert r["turn"] == {"threadId": "T1", "model": "gpt-6-luna", "effort": "high",
                         "input": [{"type": "text", "elements": []},
                                   {"type": "skill", "name": "zotero-scholium", "path": "/data/.agents/skills/zotero-scholium/SKILL.md"}],
                         "sandboxPolicy": {"type": "workspaceWrite", "writableRoots": roots, "networkAccess": True,
                                           "excludeTmpdirEnvVar": False, "excludeSlashTmp": False}}
    assert all(d in r["dirs"] for d in roots)
    assert "附件 key：ATT1" in r["prompt"] and "不要向用户提问" in r["prompt"]
    # questions that reach the plugin are declined: nobody is there to answer
    assert r["answers"] == [{"id": "q1", "result": {"decision": "decline"}}, {"id": "q2", "result": {"answers": {}}},
                            {"id": "q3", "error": {"code": -32601, "message": "not handled by scholium-bridge"}}]
    assert r["killed"] is True and r["session"] == {"agent": "codex", "id": "T1"} and r["claudeCalls"] == 0


def test_codex_transcript_state_and_log_read_like_claude_codes(facts):
    r = facts["codexRun"]
    assert r["entries"] == CODEX_TRANSCRIPT
    assert r["state"] == "完成 · 6 分钟 · 3 轮 · 265 万 token"
    assert r["stateTitle"] == "输入 19 万 · 缓存写入 0 · 缓存读取 241 万 · 输出 4.7 万"
    # deltas and start-up chatter stay out of the log; the run starts and ends as Claude Code's does
    assert not any(m.endswith("Delta") or m.endswith("delta") or "startupStatus" in m for m in r["logged"])
    assert r["logged"][0] == "system" and r["logged"][-1] == "result" and "item/commandExecution/requestApproval" in r["logged"]
    assert r["init"] == {"type": "system", "subtype": "init", "agent": "codex", "model": "gpt-6-luna", "session_id": "T1"}
    assert r["result"] == {"type": "result", "agent": "codex", "subtype": "success", "is_error": False, "result": "Done.\n" + SUMMARY,
                           "session_id": "T1", "duration_ms": 376500, "num_turns": 3,
                           "usage": {"input_tokens": 190000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 2410000,
                                     "output_tokens": 46778}}
    assert r["notices"][-1]["descriptions"] == DONE_NOTICE
    assert r["sendShown"] is True and r["revealed"] == ["/data/tmp/scholium/ATT1/codex-run.jsonl"]
    latest = facts["latestLog"]
    assert latest["codex"] == {"first": ["scholium-entry info", "模型: gpt-6-luna"], "count": len(CODEX_TRANSCRIPT),
                               "state": "上次：完成 · 6 分钟 · 3 轮 · 265 万 token", "session": {"agent": "codex", "id": "T1"},
                               "revealed": "/data/tmp/scholium/ATT1/codex-run.jsonl"}
    assert latest["claude"]["first"] == ["scholium-entry info", "模型: claude-opus-5-5"]
    assert latest["claude"]["session"] == {"agent": "claude", "id": "S1"}
    assert latest["claude"]["revealed"] == "/data/tmp/scholium/ATT1/claude-run.jsonl"


def test_codex_follow_up_continues_its_thread_whatever_agent_is_chosen(facts):
    f = facts["codexFollowUp"]
    assert f["claudeCalls"] == 0
    assert f["methods"] == ["initialize", "initialized", "thread/resume", "turn/start"]
    assert f["resume"] == {"threadId": "T1", "cwd": "/data/tmp/scholium", "approvalPolicy": "on-request", "approvalsReviewer": "auto_review",
                           "sandbox": "workspace-write", "serviceName": "scholium-bridge", "model": "gpt-6-luna"}
    assert len(f["input"]) == 1 and f["input"][0]["text"].endswith("第 5 页那条译文改短\n\n结束时最后一行只写一句：改了什么，剩余警告。")
    assert f["effort"] == "high"
    # only this run's calls and tokens: the thread's totals include the earlier turn
    assert f["state"] == "完成 · 1 分钟 · 1 轮 · 40.3 万 token"
    assert f["entries"] == [["scholium-entry text", "⏺ Done.\n" + SUMMARY], ["scholium-entry prompt", "第 5 页那条译文改短"],
                            ["scholium-entry info", "模型: gpt-6-luna"], ["scholium-entry text", "⏺ 改好了：第 5 页的译文已缩短。"]]
    assert f["results"] == 2 and f["markers"] == ["第 5 页那条译文改短"]


def test_codex_steps_and_cancel(facts):
    c = facts["codexCancel"]
    assert c["during"] == "第 2/6 步 提取句子 · 已用 1 分钟"
    assert c["interrupt"] == {"threadId": "T1", "turnId": "U1"} and c["killed"] is True
    assert c["last"] == ["scholium-entry final error", "已取消"] and c["state"] == "已取消 · 1 分钟"
    assert c["results"] == 0 and c["waits"] == [] and c["current"] is None and c["shutdown"] is True
    assert c["begun"] == "第 1/6 步 加载技能 · 已用 1 分钟"
    s = facts["codexSkillFound"]
    assert s["/data/tmp/scholium"]["methods"] == ["skills/list"]
    assert s["/data/tmp/scholium"]["input"] == [{"type": "skill", "name": "zotero-scholium", "path": "/home/u/.codex/skills/zotero-scholium/SKILL.md"}]
    assert s["none"] == {"methods": ["skills/list", "skills/list"], "input": [], "model": False}


def test_codex_usage_limit_waits_for_the_reset(facts):
    l = facts["codexLimit"]
    assert l["clock"] == l["expected"] and l["known"] is True
    assert l["queue"] == [["ATT1", "codex", "T1"], ["ATT2", "codex", None]]
    assert l["notifications"] == ["Codex 额度已用完"]
    assert l["last"] == ["scholium-entry final error", "You've hit your usage limit. Try again at 9:00 PM."]
    a = l["after"]
    assert a["resume"] == "T1" and a["prompt"] == "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。"
    assert a["turns"] == 3 and a["paused"] is None and a["state"] == "完成 · 1 分钟 · 1 轮 · 40.3 万 token"


def test_codex_failures_are_reported(facts):
    f = facts["codexFailed"]
    assert f["entries"] == [["scholium-entry text", "⏺ 先提取句子。"], ["scholium-entry final error", "stream disconnected before completion"]]
    assert f["state"].startswith("失败") and f["kind"] == "scholium-state error" and f["paused"] is None
    assert f["notices"][-1]["descriptions"] == ["失败 · stream disconnected before completion"]
    r = facts["codexRefused"]
    assert r["last"] == ["scholium-entry final error", "model gpt-9 is not available"] and r["state"].startswith("失败")
    assert r["killed"] is True and r["turns"] == 0
    n = facts["noCodex"]
    assert n["codexCalls"] == 0 and n["state"] == "失败"
    assert n["last"] == ["scholium-entry final error", "找不到 Codex（codex.exe）。请在 about:config 中设置 extensions.scholium-bridge.codexPath。"]
    assert n["models"] == [""] and n["labels"] == ["Codex 默认"]
