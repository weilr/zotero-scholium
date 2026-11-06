// The plugin's test harness: a simulated Zotero, Claude Code and Codex. A test module appends its scenarios,
// which write their facts to stdout. Run through plugin_harness.py.
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
// an element as [tag.class[style][start=…][title=…], children or text…], to compare built pages
const tree = n => (n && n.tagName
  ? [n.tagName + (n.className ? '.' + n.className : '') + (n.attrs.style ? '[' + n.attrs.style + ']' : '')
     + (n.attrs.start ? '[start=' + n.attrs.start + ']' : '') + (n.title ? '[title=' + n.title + ']' : '')
     + (n.attrs['data-href'] ? '[href=' + n.attrs['data-href'] + ']' : ''),
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
// a button's words: its text, or for an icon button its aria-label
const labelOf = n => (n && (n.textContent || (n.getAttribute && n.getAttribute('aria-label')))) || '';
// a node's text with its icons as their words: an icon button or an img-role element counts as its aria-label
const textOf = n => {
  if (!n) return '';
  const label = n.getAttribute && n.getAttribute('aria-label');
  if (label && (n.tagName === 'button' || n.getAttribute('role') === 'img')) return n.textContent || label;
  return n.children && n.children.length ? n.children.map(textOf).join('') : (n.textContent || '');
};

const CLAUDE = '/appdata/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe';
const ev = (obj) => JSON.stringify(obj) + '\n';
const tool = (name, input, id = undefined) => ev({ type: 'assistant', message: { content: [{ type: 'tool_use', id, name, input }] } });
const said = (text) => ev({ type: 'assistant', message: { content: [{ type: 'text', text }] } });
const answer = (content, is_error = false, id = undefined) => ev({ type: 'user', message: { content: [{ type: 'tool_result', tool_use_id: id, content, is_error }] } });
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
  tool('PowerShell', { command: 'python C:/skills/scholium.py --config c.json --apply' }, 'toolu_apply'),
  answer('{"applied": true}', false, 'toolu_apply'),
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
// Claude Code asked to continue a conversation it no longer has: a result naming the error, the same on stderr, exit 1
const CLAUDE_GONE = [
  ev({ type: 'result', subtype: 'error_during_execution', duration_ms: 0, is_error: true, num_turns: 0, session_id: 'S1',
       errors: ['No conversation found with session ID: S1'] }),
  'STDERR:No conversation found with session ID: S1\n', 'EXIT:1',
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
const codexNote = note;   // harness() has a note of its own
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
                     this.scrollTop = 0; this.clientHeight = 100; this.isConnected = true; this.style = { setProperty: (k, v) => { this.style[k.replace(/^--/, '')] = v; } }; }
  get scrollHeight() { return this.children.length * 20; }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join('') : this._text; }
  set textContent(v) { this.children = []; this._text = String(v); }
  get localName() { return this.tagName; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  getAttributeNames() { return Object.keys(this.attrs); }
  removeAttribute(k) { delete this.attrs[k]; }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === 'style') { const m = /(?:^|;)\s*height:\s*([^;]+)/.exec(String(v)); this.style = { height: m ? m[1].trim() : '', setProperty: this.style.setProperty }; }
  }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  click() { for (const f of this.listeners.click || []) f({}); }
  // an event of this type, as the DOM gives it: preventDefault, and a dataTransfer for a drag
  fire(t, extra = {}) {
    const e = Object.assign({ preventDefault() { e.prevented = true; }, dataTransfer: { setData() {}, getData() { return ''; } } }, extra);
    for (const f of this.listeners[t] || []) f(e);
    return e;
  }
  type(value) { this.value = value; for (const f of this.listeners.input || []) f({}); }
  focus() { this.focused = true; }
  change(value) { this.value = value; for (const f of this.listeners.change || []) f({}); }
  // as the DOM: a node appended leaves its former parent
  append(...nodes) {
    for (const n of nodes) {
      if (n && typeof n === 'object') {
        if (n.parent) n.parent.children = n.parent.children.filter(c => c !== n);
        n.parent = this;
      }
      this.children.push(n);
    }
  }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  insertBefore(n) { this.append(n); }
  querySelector() { return null; }
  closest() { return null; }
  getBoundingClientRect() { return this.rect || { top: 0, left: 0, right: 300, bottom: 20, width: 300, height: 20 }; }
  get offsetWidth() { return this.getBoundingClientRect().width; }
  removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter(g => g !== f); }
  contains(n) { for (let x = n; x; x = x.parent) if (x === this) return true; return false; }
  remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; }
  replaceWith(n) {
    const p = this.parent;
    if (!p) return;
    if (n.parent) n.remove();
    p.children[p.children.indexOf(this)] = n;
    n.parent = p; n.removed = false;
    this.parent = null; this.removed = true;
  }
  get lastChild() { return this.children.length ? this.children[this.children.length - 1] : null; }
}
// markup as KaTeX writes it (elements, attributes in double quotes, text in the innermost elements) as El
class DOMParser {
  parseFromString(markup) {
    const root = new El('#document');
    const stack = [root];
    const decode = t => t.replace(/&(amp|lt|gt|quot|#x27|#39);|&#x([0-9a-f]+);|&#(\d+);/gi, (s, name, hex, dec) =>
      hex ? String.fromCodePoint(parseInt(hex, 16)) : dec ? String.fromCodePoint(+dec)
          : { amp: '&', lt: '<', gt: '>', quot: '"', '#x27': "'", '#39': "'" }[name]);
    const re = /<\/([\w-]+)>|<([\w-]+)((?:\s+[\w:-]+="[^"]*")*)\s*(\/?)>|([^<]+)/g;
    let m;
    while ((m = re.exec(markup))) {
      if (m[1]) stack.pop();
      else if (m[2]) {
        const el = new El(m[2]);
        for (const a of m[3].matchAll(/([\w:-]+)="([^"]*)"/g)) el.setAttribute(a[1], decode(a[2]));
        stack[stack.length - 1].append(el);
        if (!m[4]) stack.push(el);
      } else stack[stack.length - 1]._text += decode(m[5]);
    }
    const find = n => (n.tagName === 'math' ? n : n.children.map(find).find(Boolean) || null);
    return { querySelector: () => find(root) };
  }
}
const cloneEl = n => {
  const c = new El(n.tagName);
  c.attrs = Object.assign({}, n.attrs);
  c._text = n._text;
  c.className = n.className;
  for (const child of n.children) c.append(cloneEl(child));
  return c;
};
// the plugin's content folder, for Services.scriptloader (KaTeX)
const CONTENT = require('node:path').join(require('node:path').dirname(process.argv[2]), 'content');

function harness({ locale = 'zh-CN', prefs = {}, existing = [], confirm = true, exitCode = 0, script = null, claudeExists = true, gateFirst = false,
                   home = 'dirsvc', eraseFails = false, logs = {}, models = 'ok', claudeAt = CLAUDE, scripts = [], readFails = false,
                   writeFails = false, codex = {}, logTimes = {}, notes = [], secondPdf = false, failLogWrites = null, stdinFails = false, holdDirs = false,
                   unreadable = [], unremovable = [], addonManager = null, env = {}, present = [], dirs = {}, auth = 'in', python = {},
                   os = 'WINNT', shell = null, uv = {} } = {}) {
  const log = { calls: [], stdin: [], notices: [], alerts: [], confirms: [], kills: 0, menus: [], unregistered: [], listeners: [],
                writes: Object.assign({}, logs), notifications: [], revealed: [], erased: [], sections: [], unregisteredSections: [],
                ftl: [], tabs: [], selected: [], opened: [], scrolled: [], modelCalls: [], modelStdin: [], modelStdinClosed: false, modelKills: 0,
                prefPanes: [], openedPrefs: [], madeDirs: [], trashed: [], versionCalls: [], codexCalls: [], codexProcs: [], codexKills: 0, codexTurns: 0, steers: [],
                mtimes: Object.assign({}, logTimes), clock: Date.now(), copied: [], removed: [], threads: 0, tmpPaths: [], reads: [], readerOpened: [], navigated: [], finds: [],
                authCalls: [], pyCalls: [], checkKills: 0, shellCalls: [], shellKills: 0, uvCalls: [] };
  const co = Object.assign({ versions: CODEX_VERSIONS, scripts: [], skillAt: '/data', fail: null, failMessage: '' }, codex);
  // the files there are: Claude Code, Codex's copies, and a test's own (present)
  const files = new Set((claudeExists ? [claudeAt] : []).concat(Object.keys(co.versions), present));
  // 97-character chunks split JSON lines; 'WAIT' holds the stream open until the process is killed; 'STDERR:…' is what
  // the run writes to stderr and 'EXIT:n' its exit code
  const entriesFor = (n) => scripts[n] || (n === 0 && gateFirst ? SCRIPT.concat(['WAIT']) : script || SCRIPT.concat([LAST, RESULT]));
  const chunksFor = (n) => {
    const entries = entriesFor(n);
    const out = [];
    for (const e of entries) {
      if (/^(STDERR|EXIT):/.test(e)) continue;
      if (e === 'WAIT' || e === 'HOLD') { out.push(e); continue; }
      for (let i = 0; i < e.length; i += 97) out.push(e.slice(i, i + 97));
    }
    return out;
  };
  class Proc {
    constructor() {
      const entries = entriesFor(log.calls.length);
      this.chunks = chunksFor(log.calls.length); this.killed = false; this.gate = null;
      this.err = entries.filter(e => e.startsWith('STDERR:')).map(e => e.slice(7)).join('');
      const exit = entries.find(e => e.startsWith('EXIT:'));
      this.exit = exit ? Number(exit.slice(5)) : null;
    }
    get stdin() { return { write: async s => { if (stdinFails) throw Error('EPIPE'); log.stdin.push(s); }, close: async () => {} }; }
    get stdout() {
      const self = this;
      return { readString: async () => {
        await tick();
        if (self.killed) return '';
        let c = self.chunks.shift();
        if (c === 'WAIT') { await new Promise(r => { self.gate = r; }); return ''; }
        // 'HOLD' holds the stream open until log.release() is called
        if (c === 'HOLD') { await new Promise(r => { log.release = r; }); c = self.killed ? '' : self.chunks.shift(); }
        return c || '';
      } };
    }
    get stderr() { const self = this; return { readString: async () => { await tick(); const s = self.err; self.err = ''; return s; } }; }
    async wait() { return { exitCode: this.killed ? 1 : this.exit === null ? exitCode : this.exit }; }
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
  // a short command of the setup check: claude auth status (auth: 'in' or 'out' as Claude Code answers, with details the
  // plugin must not keep; 'fail' ends without an answer) and python -c (python: the output of each program path; none for
  // one that answers nothing). 'HOLD' holds it until it is killed
  const AUTH = {
    in: ['{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty","email":"someone@example.com","orgId":"org-1","subscriptionType":"max"}\n', 0],
    out: ['{"loggedIn":false,"authMethod":"none","apiProvider":"firstParty"}\n', 1],
    fail: ['', 1],
    HOLD: ['HOLD', 0],
  };
  class OutProc {
    constructor([out, exit]) { this.out = out === 'HOLD' ? null : [out]; this.exit = exit; this.killed = false; this.gate = null; }
    get stdin() { return { write: async () => {}, close: async () => {} }; }
    get stdout() {
      return { readString: async () => {
        await tick();
        if (!this.out && !this.killed) await new Promise(r => { this.gate = r; });
        return this.killed || !this.out ? '' : this.out.shift() || '';
      } };
    }
    async wait() { return { exitCode: this.killed ? 1 : this.exit }; }
    kill() { log.checkKills++; this.killed = true; if (this.gate) this.gate(); }
  }
  // codex app-server: answers each request as Codex does; turn/start plays the next script, in
  // 97-character chunks; 'WAIT' holds the turn until it is interrupted or the server is killed
  // co.stderr: what it writes to stderr
  class CodexProc {
    constructor() { this.out = []; this.sent = []; this.killed = false; this.wake = null; this.errOut = co.stderr || ''; log.codexProcs.push(this); }
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
      if (co.refuse && msg.method in co.refuse) return this.emit([ev({ id: msg.id, error: { code: -32600, message: co.refuse[msg.method] } })]);
      if (co.exitOn === msg.method) { this.killed = true; if (this.wake) { const w = this.wake; this.wake = null; w(); } return; }
      // co.answers: a test's own answer to a request ({ result } or { error }), 'HOLD' for none, or nothing for the usual one
      const custom = co.answers && co.answers[msg.method] && co.answers[msg.method](p);
      if (custom === 'HOLD') return;
      if (custom) return this.emit([ev(Object.assign({ id: msg.id }, custom))]);
      // a notification ahead of the answer: the request is still waiting while it is handled
      if (co.noticeBefore === msg.method) this.emit([ev({ method: 'thread/started', params: { thread: { id: 'T1' } } })]);
      switch (msg.method) {
        case 'initialize': return answer({ userAgent: 'scholium/0.160.0', codexHome: '/home/u/.codex' });
        case 'model/list': return answer({ data: CODEX_MODELS, nextCursor: null });
        case 'config/read': return answer({ config: { model: 'gpt-6-astra', mcp_servers: { s: { env: { TOKEN: 'secret-token' } } } } });
        // the user's server s, Codex's own apps server and a plugin's server, as Codex 0.166 lists them
        case 'mcpServerStatus/list': return answer({ data: [
          { name: 'codex_apps', pluginId: null, httpOrigin: 'https://chatgpt.com', authStatus: 'bearerToken', tools: {}, resources: [], resourceTemplates: [] },
          { name: 'cua_repl', pluginId: 'unified-computer-use@openai-bundled', authStatus: 'unsupported', tools: {}, resources: [], resourceTemplates: [] },
          { name: 's', pluginId: null, httpOrigin: null, authStatus: 'unsupported', tools: {}, resources: [], resourceTemplates: [] }], nextCursor: null });
        case 'skills/list': return answer({ data: p.cwds.map(cwd => ({ cwd, errors: co.skillErrors || [], skills: [{ name: 'other', path: '/x/other/SKILL.md', enabled: true }]
          .concat(co.skillAt === cwd ? [{ name: 'zotero-scholium', path: cwd === '/data' ? '/data/.agents/skills/zotero-scholium/SKILL.md'
                                                                                      : '/home/u/.codex/skills/zotero-scholium/SKILL.md', enabled: !co.skillOff }] : []) })) });
        case 'skills/extraRoots/set': return answer({});
        case 'plugin/installed': return answer({ marketplaces: [{ name: 'm', plugins: [
          { id: 'superpowers@m', installed: true, enabled: true }, { id: 'off@m', installed: true, enabled: false },
          { id: 'offered@m', installed: false, enabled: false }] }, { name: 'remote', plugins: [{ id: 'zotero@remote', installed: true, enabled: true }] }],
          marketplaceLoadErrors: [] });
        // each new thread its own id when co.newThreads: T1, T2, …
        case 'thread/start': return answer({ thread: { id: co.newThreads ? 'T' + (++log.threads) : 'T1' }, model: p.model || 'gpt-6-astra' });
        case 'thread/inject_items': return answer({});
        case 'thread/archive': return answer({});
        case 'thread/resume': return answer({ thread: { id: p.threadId }, model: p.model || 'gpt-6-astra' });
        case 'thread/fork': return answer({ thread: { id: co.forkId || 'F1' }, model: p.model || 'gpt-6-astra' });
        case 'turn/start': {
          log.codexTurns += 1;
          const id = 'U' + log.codexTurns;
          answer({ turn: { id, status: 'inProgress', items: [] } });
          return this.emit((co.scripts[log.codexTurns - 1] || CODEX_SCRIPT).map(l => l.split('"TURN"').join(JSON.stringify(id))));
        }
        // answers at once; the compaction then runs as a turn of its own, whose id the answer does not carry
        case 'thread/compact/start': {
          answer({});
          const c = { threadId: p.threadId, turnId: 'C1' };
          return this.emit(co.compactScript || [
            codexNote('thread/status/changed', { threadId: p.threadId, status: { type: 'active', activeFlags: [] } }),
            codexNote('turn/started', { threadId: p.threadId, turn: { id: 'C1', status: 'inProgress', items: [] } }),
            codexNote('item/started', Object.assign({ item: { type: 'contextCompaction', id: 'cc1' } }, c)),
            codexNote('thread/tokenUsage/updated', Object.assign({ tokenUsage: { last: tok(119000, 100000, 1000), total: tok(9000000, 8000000, 90000), modelContextWindow: 1000000 } }, c)),
            codexNote('item/completed', Object.assign({ item: { type: 'contextCompaction', id: 'cc1' } }, c)),
            codexNote('thread/status/changed', { threadId: p.threadId, status: { type: 'idle' } }),
            turnDone({ id: 'C1', status: 'completed' })]);
        }
        case 'turn/steer': log.steers.push(p); return answer({ turnId: p.expectedTurnId });
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
    get stderr() { return { readString: async () => { const s = this.errOut; this.errOut = ''; return s; } }; }
    async wait() { return { exitCode: this.killed ? 1 : 0 }; }
    kill() { log.codexKills++; this.killed = true; if (this.wake) { const w = this.wake; this.wake = null; w(); } }
  }
  // the login shell asked for its PATH (shell: its output, 'HOLD' until it is killed, { fails } when it does not start, or
  // null for a failing one); uv --version (uv: the output of each program path)
  class ShellProc extends OutProc { kill() { log.shellKills++; this.killed = true; if (this.gate) this.gate(); } }
  const Subprocess = {
    call: async opts => {
      if (opts.arguments[0] === '-ilc') {
        log.shellCalls.push(opts);
        if (shell && shell.fails) throw Error(shell.fails);
        return new ShellProc(typeof shell === 'string' ? [shell, 0] : ['', 1]);
      }
      if (/(?:^|\/)uv(?:\.exe)?$/.test(opts.command)) { log.uvCalls.push(opts); return new OutProc(opts.command in uv ? [uv[opts.command], 0] : ['', 1]); }
      if (opts.arguments[0] === '--version') { log.versionCalls.push(opts.command); return new VersionProc(opts.command); }
      if (opts.arguments[0] === 'app-server') {
        log.codexCalls.push(opts);
        if (co.startFails) throw Error(co.startFails);   // a program that does not start
        return new CodexProc();
      }
      if (opts.arguments[0] === 'auth') { log.authCalls.push(opts); return new OutProc(AUTH[auth]); }
      if (opts.arguments[0] === '-c') { log.pyCalls.push(opts); return new OutProc(opts.command in python ? [python[opts.command], 0] : ['', 1]); }
      if (opts.arguments.includes('--input-format')) { log.modelCalls.push(opts); return new ModelProc(); }
      const p = new Proc(); log.calls.push({ opts, proc: p }); return p;
    },
    getEnvironment: () => Object.assign({}, env),
  };
  class ProgressWindow {
    constructor(options) {
      const e = this.entry = { closeOnClick: options && options.closeOnClick, lines: [], errors: 0, descriptions: [], closeTimer: null, shown: false };
      log.notices.push(e);
      this.ItemProgress = class { constructor(icon, text) { e.lines.push(text); } setText(t) { e.lines.push(t); } setProgress() {} setError() { e.errors++; } };
    }
    changeHeadline() {} addDescription(t) { this.entry.descriptions.push(t); } show() { this.entry.shown = true; } startCloseTimer(ms) { this.entry.closeTimer = ms; }
  }
  const annotation = (key, tags, type = 'highlight', color = '#ffd400') =>
    ({ key, id: key, isAnnotation: () => true, getTags: () => tags.map(tag => ({ tag })), annotationType: type, annotationColor: color });
  const attachment = (key, parentID, anns) => ({
    key, id: key, parentID, parentItemKey: parentID, libraryID: 1, attachmentContentType: 'application/pdf', deleted: false,
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
  // Zotero's local API is on unless a test turns it off
  const store = new Map(Object.entries(Object.assign({ 'httpServer.localAPI.enabled': true }, prefs)));
  const mainDoc = {
    bar: new El('hbox'),
    documentElement: new El('window'),
    getElementById(id) {
      if (id === 'zotero-items-toolbar') return this.bar;
      if (id === 'zotero-item-details') return { scrollToPane: async (paneID, how) => log.scrolled.push([paneID, how]) };
      return this.documentElement.children.find(c => c.id === id) || null;
    },
    querySelector: sel => (sel === '[href="scholium.ftl"]' && log.ftl.length ? { remove: () => log.ftl.push('removed') } : null),
    createElementNS: (ns, tag) => new El(tag),
    hasFocus: () => focused,   // the item pane is in the main window: one focus for both
  };
  const mainWin = {
    document: mainDoc,
    MozXULElement: { insertFTLIfNeeded: name => log.ftl.push(name) },
    Zotero_Tabs: { select: id => log.tabs.push(id) },
    ZoteroPane: { selectItem: async id => log.selected.push(id), loadURI: uri => log.opened.push(uri) },
  };
  // the item pane's window: whether the section is scrolled into view, its size, and the window focus
  const observers = { intersection: [], resize: [] };
  let focused = true;
  class IntersectionObserver { constructor(cb) { this.cb = cb; observers.intersection.push(this); } observe(el) { this.el = el; } disconnect() { this.off = true; } }
  class ResizeObserver { constructor(cb) { this.cb = cb; this.els = []; observers.resize.push(this); } observe(el) { this.el = el; this.els.push(el); } disconnect() { this.off = true; } }
  // the profile sheet goes into the page of the pane's window, over everything; the element that had the focus before
  const lastFocus = new El('button');
  const paneWin = { IntersectionObserver, ResizeObserver, DOMParser, listeners: {},
                    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
                    removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter(g => g !== f); },
                    dispatch(t) { for (const f of this.listeners[t] || []) f({}); } };
  const paneDoc = { createElement: tag => new El(tag), createTextNode: text => ({ textContent: text }), hasFocus: () => focused,
                    importNode: n => cloneEl(n),
                    listeners: {},
                    addEventListener(t, f, c) { (this.listeners[t] = this.listeners[t] || []).push(f); },
                    removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter(g => g !== f); },
                    dispatch(t, init) { for (const f of (this.listeners[t] || []).slice()) f(Object.assign({}, init)); },
                    defaultView: paneWin, documentElement: new El('window'), activeElement: lastFocus };
  paneWin.document = paneDoc;
  const sheet = () => paneDoc.documentElement.children.find(c => c.id === 'scholium-profile-sheet') || null;
  const see = v => { for (const o of observers.intersection) if (!o.off) o.cb([{ isIntersecting: v }]); };
  const resize = el => { for (const o of observers.resize) if (!o.off && o.els.includes(el)) o.cb([]); };
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
      PreferencePanes: { register: async o => { log.prefPanes.push(o); return 'scholium-pane-id'; } },
      Utilities: { Internal: { copyTextToClipboard: text => log.copied.push(text), openPreferences: (id, o) => log.openedPrefs.push(id) } },
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
                unregisterEventListener: (type, handler) => { log.listeners = log.listeners.filter(l => l.handler !== handler); },
                open: async (itemID, location) => { if (log.readerKind === 'rejects') throw Error('no reader'); log.readerOpened.push({ itemID, location });
                                                    // log.readerKind: 'unloaded' is a tab there but not loaded, selected with the location; nothing comes back
                                                    if (log.readerKind === 'unloaded') return undefined;
                                                    // the reader goes to the location as it opens; a navigation or a find of the plugin's own lands in
                                                    // log.navigated or log.finds
                                                    return { navigate: async loc => { log.navigated.push(loc); },
                                                             _internalReader: { toggleFindPopup: o => log.finds.push(o),
                                                                                _handleFindStateChange: (primary, state) => log.finds.push(state) } }; } },
    },
    Services: {
      prompt: { alert: (w, t, m) => log.alerts.push(m),
                confirm: (w, t, m) => { log.confirms.push(m); return Array.isArray(confirm) ? confirm.shift() : confirm; } },
      // env: a test's own variables, PATH for one
      env: { get: n => (n in env ? env[n] : n === 'APPDATA' ? '/appdata' : n === 'LOCALAPPDATA' ? '/localappdata' : n === 'USERPROFILE' && home === 'env' ? '/profile/u' : '') },
      dirsvc: { get: (key, iface) => {
        if (home !== 'dirsvc' || key !== 'Home' || iface !== NSIFILE) throw Error('NS_ERROR_FAILURE');
        return { path: '/home/u' };
      } },
      appinfo: { OS: os },
      // the preferences of `prefs` by branch, as Firefox's preference service gives them; a value's type is its own
      prefs: { PREF_INVALID: 0, PREF_STRING: 32, PREF_INT: 64, PREF_BOOL: 128,
               getBranch: root => ({
                 getChildList: start => [...store.keys()].filter(k => k.startsWith(root + (start || ''))).map(k => k.slice(root.length)),
                 prefHasUserValue: n => store.has(root + n),
                 getPrefType: n => ({ string: 32, number: 64, boolean: 128 })[typeof store.get(root + n)] || 0,
                 getStringPref: n => store.get(root + n), getIntPref: n => store.get(root + n), getBoolPref: n => store.get(root + n),
                 setStringPref: (n, v) => { store.set(root + n, String(v)); }, setIntPref: (n, v) => { store.set(root + n, v | 0); },
                 setBoolPref: (n, v) => { store.set(root + n, !!v); }, clearUserPref: n => { store.delete(root + n); } }) },
      scriptloader: { loadSubScript: (url, scope) => {
        log.scripts = (log.scripts || 0) + 1;
        const rel = url.replace(/^chrome:\/\/[^/]+\/content\//, '');
        vm.runInNewContext(fs.readFileSync(require('node:path').join(CONTENT, rel), 'utf8'), scope);
      } },
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
      // holdDirs: a run's output folder is made once log.releaseDir() is called
      makeDirectory: async p => { log.madeDirs.push(p); if (holdDirs && /\/tmp\/scholium\/\w+$/.test(p)) await new Promise(r => { log.releaseDir = r; }); },
      // dirs: a test's own folders and what each holds
      getChildren: async p => {
        if (p in dirs) return dirs[p].slice();
        if (p === CODEX_BIN) return [CODEX_BIN + '/h0', CODEX_BIN + '/h1'];
        const inside = Object.keys(log.writes).filter(f => f.startsWith(p + '/') && !f.slice(p.length + 1).includes('/'));
        if (!inside.length) throw Error('NotFoundError');
        return inside;
      },
      remove: async p => { if (unremovable.includes(p)) throw Error('NotAllowedError'); log.removed.push(p); delete log.writes[p]; },
      stat: async p => { if (!(p in log.writes)) throw Error('NotFoundError'); return { lastModified: log.mtimes[p] || 0, size: log.writes[p].length }; },
      readUTF8: async p => {
        if (readFails && p === PROFILE_PATH) throw Error('NotReadableError');
        log.reads.push(p);
        if (unreadable.includes(p)) throw Object.assign(Error('NotReadableError'), { name: 'NotReadableError' });
        if (!(p in log.writes)) throw Object.assign(Error('missing'), { name: 'NotFoundError' });
        return log.writes[p];
      },
      // as IOUtils: "append" needs the file, "appendOrCreate" makes it; a log locked a moment refuses one write (failLogWrites:
      // the words it holds, or a test of the path, the text and the options)
      writeUTF8: async (p, t, o) => {
        if (writeFails && p === PROFILE_PATH) throw Error('NotAllowedError');
        const refused = typeof failLogWrites === 'function' ? failLogWrites(p, String(t), o) : String(t).includes(failLogWrites);
        if (failLogWrites && /\/conversations\/[\w-]+\.jsonl$/.test(p) && refused && !log.lockedOnce) {
          log.lockedOnce = true;
          throw Error('NotWritableError');
        }
        const mode = o && o.mode;
        if (mode === 'append' && !(p in log.writes)) throw Object.assign(Error('NotFoundError: ' + p), { name: 'NotFoundError' });
        log.writes[p] = (mode === 'append' || mode === 'appendOrCreate' ? (log.writes[p] || '') : '') + t;
        log.mtimes[p] = ++log.clock;
        if (o && o.tmpPath) log.tmpPaths.push(o.tmpPath);
      },
      write: async (p, bytes) => {
        log.writes[p] = Buffer.from(bytes).toString('utf8');
        log.mtimes[p] = ++log.clock;
      },
    },
    // AddonManager: a test's own, or none
    ChromeUtils: { importESModule: url => (/AddonManager/.test(url) ? { AddonManager: addonManager } : { Subprocess }) },
  });
  vm.runInContext(source, context);
  const runner = context.ScholiumRunner;
  runner.NET_RETRY_MS = 40;
  // each run's end as finish() is given it: its outcome and the tokens' detail (a chat's state line shows them, an
  // annotation's card the numbers)
  log.ended = [];
  const finish = runner.finish;
  runner.finish = function (job, ok, summary, outcome, detail) {
    log.ended.push({ key: job.att.key, kind: job.kind || 'chat', text: outcome || this.text(ok ? 'done' : 'failed'), title: detail || '' });
    return finish.apply(this, arguments);
  };
  // the item pane section as Zotero drives it: onItemChange, onRender, onAsyncRender
  const pane = async (item, opts = {}) => {
    const section = log.sections[0];
    const body = new El('div');
    if (opts.closest) body.closest = opts.closest;
    let enabled = null;
    section.onItemChange({ item, setEnabled: v => { enabled = v; } });
    section.onRender({ doc: paneDoc, body, item });
    await section.onAsyncRender({ body });
    // the ⋯ menu's items of a tab, read from the menu and closed again; none while another layer is open
    const menuOf = (p, tab) => {
      if (p.popover) return [];
      const was = p.tab;
      p.tab = tab;
      try {
        runner.openMoreMenu(p);
        return p.popover.node.children.map(c => ({ text: c.textContent, disabled: !!c.disabled }));
      } finally { runner.closePopover(p); p.tab = was; }
    };
    return { body, enabled,
      // the annotation tab's button; the section stays on that tab, which shows the run
      annotate: () => { const q = runner.panes.get(body); q.tabAnnotate.click(); q.annotGo.click(); },
      // what the section shows on a tab: the one it is on, or the one named, painted for the moment
      view: (tab = null) => {
      const p = runner.panes.get(body);
      if (!p) return null;
      const was = p.tab, other = !!tab && tab !== was;
      if (other) { p.tab = tab; runner.paintPane(p); }
      try {
        const v = runner.viewOf(p, p.tab);
        const chatMenu = menuOf(p, 'chat'), annotMenu = menuOf(p, 'annotate');
        const logItem = p.tab === 'annotate' ? annotMenu[1] : chatMenu[0];
        return { model: p.model.value, models: p.model.children.map(o => o.value), modelLabels: p.model.children.map(o => o.textContent),
                 effort: p.effort.value, efforts: p.effort.children.map(o => o.value), effortDisabled: p.effort.disabled,
                 state: p.state.hidden ? null : p.state.textContent, stateKind: p.state.className,
                 annotateDisabled: p.annotGo.disabled, removeDisabled: annotMenu.length ? annotMenu[2].disabled : null,
                 logDisabled: logItem ? logItem.disabled : null, shownKey: v.shownKey, history: v.history,
                 entries: v.list.children.map(c => [c.className, textOf(c)]), flat: flatNodes(runner, v).map(n => [n.className, textOf(n)]),
                 stateTitle: p.state.title,
                 resumeHidden: p.resume.hidden, stateDisplay: p.state.style.display,
                 sendHidden: p.send.hidden, sendDisabled: p.send.disabled, placeholder: p.input.placeholder,
                 shownConv: v.shownConv, newChatDisabled: p.newChat.disabled, historyDisabled: p.historyButton.disabled,
                 agentDisabled: p.agent.disabled, ring: p.ring.hidden ? null : p.ring.title, ringClass: p.ring.className, ctxUsed: v.context ? v.context.used : null, round: [p.send.textContent, p.send.title],
                 historyRows: !p.popover || p.popover.name !== 'history' ? null : p.popover.node.children.map(c => [c.className, textOf(c)]) };
      } finally { if (other) { p.tab = was; runner.paintPane(p); } }
    }, pane: () => runner.panes.get(body) };
  };
  const styles = () => mainDoc.documentElement.children.map(c => [c.tagName, c.id, c.attrs.rel, c.attrs.href]);
  return { runner, zotero: context.Zotero, log, item1, item2, att1, att2, note, pane, store, see, resize, focus, observers, timers, fire, styles, sheet, paneWin, paneDoc, lastFocus, El,
           ann: (key, type, color, tags = ['zotero-scholium']) => annotation(key, tags, type, color),
           flat: view => flatNodes(runner, view),
           chromePackage: context.chromePackage, replacing: context.replacing, takingOver: context.takingOver,
           startup: context.startup, shutdown: context.shutdown, endpoints: context.ScholiumEndpoints, toggle: context.ScholiumToggle,
           live: () => timers.filter(t => t.live).map(t => t.ms), toolbarItems: () => mainDoc.bar.children.length,
           // a right click on a text selection in the reader: the items its listener appends to the context menu, as
           // { textContent: label, click: command }; the reader keeps the selection as its selection popup's annotation
           selection: (text, pageIndex, pageLabel, tabID = undefined) => {
             const l = log.listeners.find(x => x.type === 'createViewContextMenu');
             const appended = [];
             const annotation = { text, pageLabel, position: { pageIndex, rects: [] } };
             const view = { clearSelection() { log.selectionsCleared = (log.selectionsCleared || 0) + 1; } };
             l.handler({ reader: { itemID: 'ATT1', _window: paneWin, tabID,
                                   _internalReader: { _primaryView: view, _lastViewPrimary: true, _state: { primaryViewSelectionPopup: { annotation } } } },
                         doc: {}, params: { x: 10, y: 10 }, append: (...items) => appended.push(...items) });
             return appended.map(i => ({ textContent: i.label, click: () => i.onCommand() }));
           } };
}
// a view's transcript as nodes with every run's steps opened: each run's parts in order, its folded line as its steps
// (an annotation's, on its tab, with its closing words)
const flatNodes = (runner, view) => {
  const runs = runner.runsOf(view.entries || []);
  const folded = r => (view.kind === 'annotate' && r.turn && r.turn.annotate ? r.steps.concat(r.answer) : r.steps);
  return view.list.children.flatMap((n, i) => n.className !== 'scholium-run' ? [n]
    : n.children.flatMap(c => c.className !== 'scholium-fold' ? [c] : folded(runs[i]).map(e => runner.entryNode(view.doc, e))));
};
// the ⋯ menu's personal profile and log items, on the tab the section is on
const profileFrom = pane => { pane.more.click(); pane.popover.node.children[pane.tab === 'annotate' ? 0 : 1].click(); };
const logFrom = pane => { pane.more.click(); pane.popover.node.children[pane.tab === 'annotate' ? 1 : 0].click(); };
const untimed = e => e[0] !== 'scholium-meta';   // the transcript without the line of the model and the time a run ended at
const notice = n => ({ closeOnClick: n.closeOnClick, errors: n.errors, descriptions: n.descriptions, closeTimer: n.closeTimer, shown: n.shown });
// a paper's conversations, in the order they were started, and the lines of one (the latest by default); the plugin's
// files of the papers, to start another harness with
const convs = (h, key = 'ATT1') => Object.keys(h.log.writes).filter(p => p.startsWith(`/data/tmp/scholium/${key}/conversations/`) && p.endsWith('.jsonl'));
const convText = (h, key = 'ATT1', i = -1) => h.log.writes[convs(h, key).at(i)] || '';
const convLines = (h, key = 'ATT1', i = -1) => convText(h, key, i).trim().split('\n').filter(Boolean).map(l => JSON.parse(l));
// an agent's own session of a conversation read from its log: the agent of the conversation's id
const own = (log, agent) => {
  if (!log) return log;
  if (!agent && /^chat-/.test(log.id)) throw new Error('own(): a chat-* conversation needs an explicit agent');
  return log.agents[agent || (/^(?:annotate-)?codex-/.test(log.id) ? 'codex' : 'claude')];
};
const ours = h => Object.fromEntries(Object.entries(h.log.writes).filter(([p]) => p.startsWith('/data/tmp/scholium/')));
const CONV1 = '/data/tmp/scholium/ATT1/conversations/claude-20261001-120000.jsonl';   // a conversation logged before
// the outcome of a paper's latest run that ended, of either kind (the chat's state line shows a chat's)
const latestNote = (h, key = 'ATT1') => h.log.ended.filter(e => e.key === key).at(-1) || null;
const noteOf = (h, key = 'ATT1') => (latestNote(h, key) || {}).text || null;

