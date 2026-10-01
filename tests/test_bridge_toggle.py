"""Run the bridge's reader toggle against a simulated Zotero reader.

The simulation follows Zotero's reader code: a reader tab or window is pushed to
Zotero.Reader._readers right after construction and loads its annotations after an await,
every annotation passes through ReaderInstance.prototype._getAnnotation, previews are not
pushed, and the toolbar's plugin section is re-rendered through the renderToolbar event.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from zotero_scholium import cli


BRIDGE = Path(__file__).resolve().parents[1] / "plugin/scholium-bridge/bootstrap.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const settle = async () => { for (let i = 0; i < 5; i++) await tick(); };

class El {
  constructor(doc, tag) {
    this.ownerDocument = doc; this.tagName = tag; this.children = []; this.attrs = {};
    this.listeners = {}; this.className = ''; this.parentNode = null; this.title = ''; this.tabIndex = 0;
  }
  get classList() {
    const el = this;
    const set = () => new Set(el.className.split(/\s+/).filter(Boolean));
    return {
      contains: c => set().has(c),
      toggle(c, force) {
        const s = set(); const on = force === undefined ? !s.has(c) : !!force;
        if (on) s.add(c); else s.delete(c);
        el.className = [...s].join(' ');
        return on;
      },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  append(...nodes) { for (const n of nodes) { if (n.parentNode) n.remove(); n.parentNode = this; this.children.push(n); } }
  replaceChildren(...nodes) { for (const n of this.children) n.parentNode = null; this.children = []; this.append(...nodes); }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter(n => n !== this);
    this.parentNode = null;
  }
  addEventListener(type, f) { (this.listeners[type] = this.listeners[type] || []).push(f); }
  click() { for (const f of this.listeners.click || []) f({ type: 'click' }); }
  matches(selector) {
    const parts = selector.trim().split(/\s+/).map(p => p.replace(/^\./, ''));
    if (!this.classList.contains(parts[parts.length - 1])) return false;
    let i = parts.length - 2;
    for (let n = this.parentNode; n && i >= 0; n = n.parentNode) if (n.classList.contains(parts[i])) i--;
    return i < 0;
  }
  closest(selector) { for (let n = this; n; n = n.parentNode) if (n.matches(selector)) return n; return null; }
  querySelectorAll(selector) {
    const out = [];
    const walk = node => { for (const c of node.children) { if (c.matches(selector)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
class Doc extends El {
  constructor() {
    super(null, '#document');
    this.ownerDocument = this;
    const toolbar = this.createElement('div'); toolbar.className = 'toolbar';
    const end = this.createElement('div'); end.className = 'end';
    this.sections = this.createElement('div'); this.sections.className = 'custom-sections';
    end.append(this.sections); toolbar.append(end); this.append(toolbar);
  }
  createElement(tag) { return new El(this, tag); }
  createElementNS(ns, tag) { return new El(this, tag); }
}

let nextID = 1;
const writes = [];
const annotation = (key, tags, type = 'highlight') => {
  const write = name => () => { writes.push([name, key]); };
  return {
    key, id: nextID++, annotationType: type, isAnnotation: () => true, getTags: () => tags.map(tag => ({ tag })),
    save: write('save'), saveTx: write('saveTx'), erase: write('erase'), eraseTx: write('eraseTx'),
    setTags: write('setTags'), addTag: write('addTag'), removeTag: write('removeTag'),
  };
};
const attachment = list => ({ id: nextID++, list, getAnnotations() { return this.list; } });
const attachments = new Map();

class ReaderInstance {
  constructor(item, toolbar) {
    this._item = item; this.toolbar = toolbar; this.view = new Set(); this.everShown = new Set();
    this._initPromise = new Promise(resolve => { this._resolveInitPromise = resolve; });
    this.doc = new Doc();
    this._iframeWindow = { document: this.doc };
    this._open();
  }
  get itemID() { return this._item.id; }
  async _open() {
    await null;   // Zotero.SyncedSettings.loadAll
    const loaded = (await Promise.all(this._item.getAnnotations().map(x => this._getAnnotation(x)))).filter(x => x);
    this._show(loaded);
    this._resolveInitPromise();
    if (this.toolbar) renderToolbar(this);
  }
  _show(list) { for (const a of list) { this.view.add(a.id); this.everShown.add(a.id); } }
  async _getAnnotation(item) {
    if (!item || !item.isAnnotation()) return null;
    return { id: item.key, tags: item.getTags().map(t => ({ name: t.tag })) };
  }
  async setAnnotations(items) {
    const list = [];
    for (const item of items) { const a = await this._getAnnotation(item); if (a) list.push(a); }
    if (list.length) { await this._initPromise; this._show(list); }
  }
  async unsetAnnotations(keys) { await this._initPromise; for (const k of keys) this.view.delete(k); }
}
class ReaderTab extends ReaderInstance { constructor(item) { super(item, true); } }
class ReaderPreview extends ReaderInstance { constructor(item) { super(item, false); } }
const originalGetAnnotation = ReaderInstance.prototype._getAnnotation;

let listeners = [];
function renderToolbar(reader) {
  const host = reader.doc.sections;
  host.replaceChildren();
  const append = (...nodes) => {
    const section = reader.doc.createElement('div'); section.className = 'section';
    section.append(...nodes); host.append(section);
  };
  for (const l of listeners) if (l.type === 'renderToolbar') l.handler({ type: 'renderToolbar', reader, doc: reader.doc, append, params: {} });
}
class ReaderManager {
  constructor() { this._readers = []; }
  registerEventListener(type, handler, pluginID) { listeners.push({ type, handler, pluginID }); }
  unregisterEventListener(type, handler) { listeners = listeners.filter(l => !(l.type === type && l.handler === handler)); }
  open(att) { const reader = new ReaderTab(att); this._readers.push(reader); return reader; }
  async openPreview(att) { await null; return new ReaderPreview(att); }
  notify(att, keys) {
    for (const r of this._readers) if (r._item === att) r.setAnnotations(att.getAnnotations().filter(a => keys.includes(a.key)));
  }
}

function boot(locale, prefs = {}) {
  const Reader = new ReaderManager();
  const store = new Map(Object.entries(prefs));
  const full = name => { if (!name.startsWith('extensions.scholium-bridge.')) throw Error('unexpected preference ' + name); };
  const context = vm.createContext({ Zotero: {
    debug() {}, locale, Reader, Items: { get: id => attachments.get(id) || null },
    Prefs: {
      get(name, global) { if (!global) throw Error('expected a full preference name'); full(name); return store.get(name); },
      set(name, value, global) { if (!global) throw Error('expected a full preference name'); full(name); store.set(name, value); },
    },
  } });
  vm.runInContext(source, context);
  return { Reader, toggle: context.ScholiumToggle, store };
}
const PREF = 'extensions.scholium-bridge.showAnnotations';
const sorted = set => [...set].sort();
const buttons = reader => reader.doc.querySelectorAll('.scholium-toggle');
const describe = button => ({
  title: button.title, pressed: button.getAttribute('aria-pressed'),
  active: button.classList.contains('active'), paths: button.children[0].children.length,
});
const own = () => [annotation('s1', ['zotero-scholium']), annotation('m1', ['zotero-scholium', 'personal'], 'text')];
// the user's annotations: other tags, tags resembling the tool's, and every annotation type
const user = () => [
  annotation('u1', []), annotation('p1', ['personal']),
  annotation('n1', ['scholium']), annotation('c1', ['Zotero-Scholium']), annotation('x1', ['zotero-scholium-old']),
  annotation('g1', ['zotero-marginalia']), annotation('g2', ['zotero-paper-annotate']),
  annotation('d1', ['zotero scholium'], 'underline'), annotation('t1', [], 'text'), annotation('o1', [], 'note'),
  annotation('i1', [], 'image'), annotation('k1', [], 'ink'),
];
const newAttachment = () => { const att = attachment([...user(), ...own()]); attachments.set(att.id, att); return att; };
const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

(async () => {
  const facts = {};

  // first run, nothing saved: two tabs, one click, updates, a third tab, previews, shutdown
  {
    const { Reader, toggle, store } = boot('en-US');
    toggle.start('scholium-bridge@zotero-scholium');
    facts.tag = toggle.tag;
    facts.hooksBeforeFirstReader = { push: hasOwn(Reader._readers, 'push'), openPreview: hasOwn(Reader, 'openPreview') };
    const att = newAttachment();
    const tab = Reader.open(att);
    await settle();
    facts.openView = sorted(tab.view);
    facts.openEverShown = sorted(tab.everShown);
    facts.hooksAfterFirstReader = { push: hasOwn(Reader._readers, 'push'), openPreview: hasOwn(Reader, 'openPreview') };
    const second = Reader.open(att);
    await settle();
    facts.secondOpen = sorted(second.view);
    facts.prefBeforeClick = store.has(PREF);
    facts.buttonsOnOpen = buttons(tab).length + buttons(second).length;
    facts.buttonHidden = describe(buttons(tab)[0]);

    buttons(tab)[0].click(); await settle();
    facts.shownViews = [sorted(tab.view), sorted(second.view)];
    facts.shownButtons = [describe(buttons(tab)[0]), describe(buttons(second)[0])];
    facts.prefAfterShow = store.get(PREF);

    att.list.push(annotation('s2', ['zotero-scholium']));
    Reader.notify(att, ['s2']); await settle();
    facts.addedWhileShown = sorted(tab.view);

    const third = Reader.open(att);
    await settle();
    facts.thirdOpenWhileShown = sorted(third.view);
    facts.thirdButton = describe(buttons(third)[0]);
    const shownPreview = await Reader.openPreview(att);
    await settle();
    facts.previewWhileShown = sorted(shownPreview.view);

    buttons(second)[0].click(); await settle();
    facts.hiddenViews = [sorted(tab.view), sorted(second.view), sorted(third.view)];
    facts.hiddenButtons = [tab, second, third].map(r => describe(buttons(r)[0]));
    facts.prefAfterHide = store.get(PREF);
    Reader.notify(att, ['s1', 'u1']); await settle();
    facts.modifiedWhileHidden = sorted(tab.view);
    const preview = await Reader.openPreview(att);
    await settle();
    facts.previewWhileHidden = sorted(preview.view);

    renderToolbar(tab);
    facts.rerender = { count: buttons(tab).length, button: describe(buttons(tab)[0]) };

    toggle.stop(); await settle();
    facts.afterStop = {
      restored: ReaderInstance.prototype._getAnnotation === originalGetAnnotation,
      listeners: listeners.length,
      buttons: [tab, second, third].reduce((n, r) => n + buttons(r).length, 0),
      views: [sorted(tab.view), sorted(second.view), sorted(third.view)],
    };
    listeners = [];
  }

  // a later session: the saved choice applies from the start, and shutdown leaves it alone
  {
    const { Reader, toggle, store } = boot('en-US', { [PREF]: true });
    toggle.start('scholium-bridge@zotero-scholium');
    const att = newAttachment();
    const tab = Reader.open(att);
    await settle();
    facts.restartView = sorted(tab.view);
    facts.restartButton = describe(buttons(tab)[0]);
    toggle.stop(); await settle();
    facts.restartAfterStop = sorted(tab.view);
    facts.restartPrefAfterStop = store.get(PREF);
    listeners = [];
  }

  // plugin started while a tab is already open, nothing saved
  {
    const { Reader, toggle, store } = boot('zh-CN');
    const att = newAttachment();
    const tab = Reader.open(att);
    await settle();
    facts.preexistingBeforeStart = sorted(tab.view);
    toggle.start('scholium-bridge@zotero-scholium');
    await settle();
    facts.preexistingAfterStart = sorted(tab.view);
    facts.preexistingButtons = buttons(tab).length;
    facts.preexistingTitle = buttons(tab)[0].title;
    buttons(tab)[0].click(); await settle();
    facts.preexistingShown = sorted(tab.view);
    facts.preexistingPref = store.get(PREF);
    toggle.stop();
    listeners = [];
  }

  // the first reader after start is an item-pane preview
  {
    const { Reader, toggle } = boot('en-US');
    toggle.start('scholium-bridge@zotero-scholium');
    const att = newAttachment();
    const preview = await Reader.openPreview(att);
    await settle();
    facts.previewFirst = sorted(preview.view);
    facts.previewFirstHooks = hasOwn(Reader, 'openPreview');
    toggle.stop();
    listeners = [];
  }

  facts.writes = writes;
  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@pytest.fixture(scope="module")
def facts():
    completed = subprocess.run(
        [NODE, "-e", HARNESS, str(BRIDGE)], encoding="utf-8", capture_output=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


USER = sorted(["u1", "p1", "n1", "c1", "x1", "g1", "g2", "d1", "t1", "o1", "i1", "k1"])
ALL = sorted(USER + ["m1", "s1"])
WITH_S2 = sorted(ALL + ["s2"])
HIDDEN_BUTTON = {"title": "Show scholium annotations", "pressed": "false", "active": False, "paths": 3}
SHOWN_BUTTON = {"title": "Hide scholium annotations", "pressed": "true", "active": True, "paths": 2}


def test_toggle_recognises_only_the_current_tag(facts):
    assert facts["tag"] == cli.TAG


def test_first_run_is_hidden_without_showing_them_first(facts):
    assert facts["hooksBeforeFirstReader"] == {"push": True, "openPreview": True}
    assert facts["openView"] == USER
    assert facts["openEverShown"] == USER
    assert facts["hooksAfterFirstReader"] == {"push": False, "openPreview": False}
    assert facts["secondOpen"] == USER
    assert facts["prefBeforeClick"] is False
    assert facts["buttonsOnOpen"] == 2
    assert facts["buttonHidden"] == HIDDEN_BUTTON


def test_one_click_switches_every_reader_and_is_saved(facts):
    assert facts["shownViews"] == [ALL, ALL]
    assert facts["shownButtons"] == [SHOWN_BUTTON, SHOWN_BUTTON]
    assert facts["prefAfterShow"] is True
    assert facts["hiddenViews"] == [USER, USER, USER]
    assert facts["hiddenButtons"] == [HIDDEN_BUTTON] * 3
    assert facts["prefAfterHide"] is False


def test_new_readers_and_updates_follow_the_current_state(facts):
    assert facts["addedWhileShown"] == WITH_S2
    assert facts["thirdOpenWhileShown"] == WITH_S2
    assert facts["thirdButton"] == SHOWN_BUTTON
    assert facts["previewWhileShown"] == WITH_S2
    assert facts["modifiedWhileHidden"] == USER
    assert facts["previewWhileHidden"] == USER
    assert facts["previewFirst"] == USER
    assert facts["previewFirstHooks"] is False
    assert facts["rerender"] == {"count": 1, "button": HIDDEN_BUTTON}


def test_saved_choice_applies_in_a_later_session(facts):
    assert facts["restartView"] == ALL
    assert facts["restartButton"] == SHOWN_BUTTON
    assert facts["restartAfterStop"] == ALL
    assert facts["restartPrefAfterStop"] is True


def test_shutdown_restores_zotero_and_shows_hidden_annotations(facts):
    assert facts["afterStop"] == {"restored": True, "listeners": 0, "buttons": 0, "views": [WITH_S2] * 3}


def test_reader_open_before_start_is_hidden_and_gets_a_button(facts):
    assert facts["preexistingBeforeStart"] == ALL
    assert facts["preexistingAfterStart"] == USER
    assert facts["preexistingButtons"] == 1
    assert facts["preexistingTitle"] == "显示 Scholium 批注"
    assert facts["preexistingShown"] == ALL
    assert facts["preexistingPref"] is True


def test_user_annotations_stay_visible_and_no_item_is_written(facts):
    views = [facts[k] for k in ("openView", "secondOpen", "modifiedWhileHidden", "previewWhileHidden",
                                "previewFirst", "preexistingAfterStart")] + facts["hiddenViews"]
    for view in views:
        assert set(USER) <= set(view)
    assert facts["writes"] == []
