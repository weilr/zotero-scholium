"""Run the bridge's one-click annotation runner against a simulated Zotero and a scripted Claude Code.

The simulated Subprocess replays stream-json output (split across chunks) and answers the model list
request, so the command line, the task prompt, the Scholium section of the item
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
                   writeFails = false } = {}) {
  const log = { calls: [], stdin: [], notices: [], alerts: [], confirms: [], kills: 0, menus: [], unregistered: [], listeners: [],
                writes: Object.assign({}, logs), notifications: [], revealed: [], erased: [], sections: [], unregisteredSections: [],
                ftl: [], tabs: [], selected: [], scrolled: [], modelCalls: [], modelStdin: [], modelStdinClosed: false, modelKills: 0,
                madeDirs: [] };
  const files = new Set(claudeExists ? [claudeAt] : []);
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
  const Subprocess = {
    call: async opts => {
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
  const regular = (key, att) => ({ key, id: key, libraryID: 1, isRegularItem: () => true, isAttachment: () => false, isPDFAttachment: () => false,
    getBestAttachment: async () => att, getAttachments: () => [att.id, 'HTML_' + key], getDisplayTitle: () => 'Paper ' + key });
  const att1 = attachment('ATT1', 'ITEM1', existing.map((t, i) => annotation('E' + i, t)));
  const att2 = attachment('ATT2', 'ITEM2', []);
  const item1 = regular('ITEM1', att1), item2 = regular('ITEM2', att2);
  const note = { key: 'NOTE', isRegularItem: () => false, isAttachment: () => false, isPDFAttachment: () => false };
  const html = key => ({ key, id: key, attachmentContentType: 'text/html', isAttachment: () => true, isRegularItem: () => false,
                         isPDFAttachment: () => false, getAnnotations: () => { throw Error('not a file attachment with annotations'); } });
  [item1, item2, att1, att2, html('HTML_ITEM1'), html('HTML_ITEM2')].forEach(i => items.set(i.id, i));
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
      env: { get: n => (n === 'APPDATA' ? '/appdata' : n === 'USERPROFILE' && home === 'env' ? '/profile/u' : '') },
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
    } },
    IOUtils: {
      exists: async p => files.has(p) || p in log.writes,
      makeDirectory: async p => { log.madeDirs.push(p); },
      readUTF8: async p => {
        if (readFails && p === PROFILE_PATH) throw Error('NotReadableError');
        if (!(p in log.writes)) throw Error('missing');
        return log.writes[p];
      },
      writeUTF8: async (p, t, o) => {
        if (writeFails && p === PROFILE_PATH) throw Error('NotAllowedError');
        log.writes[p] = (o && o.mode === 'append' ? (log.writes[p] || '') : '') + t;
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
                   parts: p1.body.children[0].children.map(c => c.className), selects: [p1.model.className, p1.effort.className],
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
    const h = harness({ existing });
    h.runner.start('x');
    const removed = await h.runner.removeAnnotations([h.item1, h.att1, h.note]);
    facts.deleted = { removed, erased: h.log.erased, remaining: h.att1.getAnnotations().map(a => a.key), confirms: h.log.confirms,
                      notice: notice(h.log.notices.at(-1)) };
    const again = await h.runner.removeAnnotations([h.item1]);
    facts.deleteNothingLeft = { removed: again, alerts: h.log.alerts };
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
    const h = harness({ existing: [['zotero-scholium']], gateFirst: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(60);
    facts.deleteWhileRunning = { removed: await h.runner.removeAnnotations([h.item1]), erased: h.log.erased, alerts: h.log.alerts,
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
    assert look["selects"] == ["scholium-select", "scholium-select"] and look["input"] == "scholium-input"
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
        {"closeOnClick": True, "errors": 0, "descriptions": ["完成 · 1 分钟\n" + SUMMARY], "closeTimer": 6000, "shown": True},
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
    assert f["notifications"] == [{"title": "批注完成：Paper ITEM1", "body": SUMMARY}]


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


def test_delete_removes_only_the_tools_annotations_after_a_confirmation(facts):
    d = facts["deleted"]
    assert d["removed"] == 2 and d["erased"] == ["E0", "E1"]
    assert d["remaining"] == ["E2", "E3", "E4"]
    assert d["confirms"] == ["将永久删除 1 篇论文上的 2 条 Scholium 批注（带 zotero-scholium 标签的批注）。"
                             "你自己的批注和阅读笔记都保留。删除会同步，不能撤销。继续吗？"]
    assert d["notice"] == {"closeOnClick": True, "errors": 0, "descriptions": ["已删除 1 篇论文上的 2 条 Scholium 批注。"],
                           "closeTimer": 6000, "shown": True}
    assert facts["deleteNothingLeft"] == {"removed": 0, "alerts": ["所选论文没有 Scholium 批注。"]}
    assert facts["deleteRefused"] == {"removed": 0, "erased": [], "remaining": 1}
    f = facts["deleteFails"]
    assert f["removed"] == 0 and f["notice"]["errors"] == 1
    assert f["notice"]["descriptions"] == ["删除失败：library is read-only\n已删除 0 篇论文上的 0 条 Scholium 批注。"]
    assert f["state"] == "删除失败：library is read-only" and f["kind"] == "scholium-state error"


def test_delete_skips_a_paper_being_annotated(facts):
    r = facts["deleteWhileRunning"]
    assert r["removed"] == 0 and r["erased"] == []
    assert r["alerts"] == ["所选论文没有 Scholium 批注。\n\n1 篇论文正在批注或排队，不会删除。"]
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
