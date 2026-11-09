"""Release fixes of the Scholium section (group F3): the settings layer's words on switching the agent, Ask Scholium in
PDF readers only and closing its popup on Zotero 7-9, the Annotations tab of a paper that already carries Scholium
annotations, Delete annotations of the PDF shown, focus rings and the ring's colour from Zotero's variables, the
keyboard (ring, citation chips, layers, tabs), the focus kept across redraws, a finished question's time in one place,
and the reader listeners on Zotero 7-9."""
import json
import re
import subprocess

import pytest

from plugin_harness import BOOTSTRAP, CORE, NODE, css_rules

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const DIR = '/data/tmp/scholium/ATT1/conversations/';
// a Claude turn of a chat log, with its context window
const claudeTurn = (n, uuid, session = 'S1', at = 1000 + n) => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session })
  + L({ type: 'assistant', uuid, session_id: session, message: { usage: { input_tokens: 10 * n, cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0, output_tokens: 1 }, content: [{ type: 'text', text: '回答' + n }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: session,
        modelUsage: { 'claude-opus-5-5': { contextWindow: 200000 } } })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
// the focus as a window gives it: the element focused last is the document's active element; the one it left gets blur and
// a bubbling focusout, the new one focus
let focusDoc = null;
El.prototype.focus = function () {
  const d = focusDoc;
  if (!d) { this.focused = true; return; }
  const prev = d.activeElement;
  if (prev === this) return;
  d.activeElement = this; this.focused = true;
  if (prev && prev.fire) { prev.fire('blur'); for (let x = prev; x; x = x.parent) x.fire('focusout'); }
  this.fire('focus');
};
// a click from the mouse (detail 1) or from the keyboard (detail 0, Enter or Space on a button)
const mouseClick = el => el.fire('click', { detail: 1 });
const keyClick = el => el.fire('click', { detail: 0 });
// the layer looks where the focus went once it moved: a moment later
const later = (ms = 10) => new Promise(r => setTimeout(r, ms));
const all = n => [n, ...((n && n.children) || []).filter(c => c && c.tagName).flatMap(all)];
(async () => {
  const facts = {};
  const errors = [];
  const step = async f => { try { await f(); } catch (e) { errors.push(String(e.stack || e).slice(0, 600)); } };
  // the settings layer: switching the agent keeps the conversation shown
  facts.switchNote = {};
  await step(async () => { for (const locale of ['zh-CN', 'en-US']) {
    const h = harness({ locale });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.chip.click();
    facts.switchNote[locale] = pane.popover.node.children.find(c => c.className === 'scholium-note').textContent;
  } });
  // Ask Scholium in the context menu: in a PDF's reader only, with text selected; the selection is the one the reader keeps
  // for the view used last; on Zotero 7-9 the PDF view has no clearSelection, on Zotero 10 it draws nothing by itself
  await step(async () => {
    const h = harness({ locale: 'en-US' });
    h.runner.start('x');
    const l = h.log.listeners.find(x => x.type === 'createViewContextMenu');
    const passage = (text, page) => ({ annotation: { text, pageLabel: page, position: { pageIndex: Number(page) - 1, rects: [] } } });
    const fire = (itemID, view, state = { primaryViewSelectionPopup: passage('A passage.', '3') }, lastPrimary = true) => {
      const appended = [];
      l.handler({ reader: { itemID, _window: h.paneWin, tabID: 'tab-r', _internalReader: { _primaryView: view, _lastViewPrimary: lastPrimary, _state: state } },
                  doc: {}, params: { x: 1, y: 1 }, append: (...n) => appended.push(...n) });
      return appended;
    };
    const snapshot = fire('HTML_ITEM1', { clearSelection() {} }).map(n => n.label);
    const none = { nothing: fire('ATT1', {}, {}).length, blank: fire('ATT1', {}, { primaryViewSelectionPopup: passage('  ', '3') }).length };
    const old = { ranges: [], rendered: 0, removed: 0 };
    const view = { _setSelectionRanges(r) { old.ranges.push(r === undefined ? 'none' : r); }, _render() { old.rendered++; },
                   _iframeWindow: { getSelection: () => ({ removeAllRanges() { old.removed++; } }) } };
    const pdf = fire('ATT1', view);
    pdf[0].onCommand(); await settle(30);
    // the secondary view used last: its passage
    h.runner.pendingQuotes.clear();
    fire('ATT1', {}, { primaryViewSelectionPopup: passage('In the first view.', '3'), secondaryViewSelectionPopup: passage('In the second view.', '5') }, false)[0].onCommand();
    await settle(30);
    const secondary = (h.runner.pendingQuotes.get('ATT1') || {}).quote;
    // Zotero 10's view: cleared, then drawn again
    const ten = { cleared: 0, rendered: 0 };
    fire('ATT1', { clearSelection() { ten.cleared++; }, _render() { ten.rendered++; } })[0].onCommand();
    await settle(30);
    facts.askReaders = { snapshot, none, pdf: pdf.map(n => n.label), old, pending: [...h.runner.pendingQuotes.keys()], secondary, ten };
  });
  // the first Ask Scholium of a reader tab: the section drawn then takes the passage and the focus
  await step(async () => {
    const h = harness({ locale: 'en-US' });
    h.runner.start('x');
    h.selection('A passage.', 2, '3', 'tab-r')[0].click(); await settle(30);
    const draw = async () => {
      const body = new El('div');
      h.log.sections[0].onItemChange({ item: h.att1, setEnabled: () => {} });
      h.log.sections[0].onRender({ doc: h.paneDoc, body, item: h.att1 });
      await h.log.sections[0].onAsyncRender({ body }); await settle(30);
      return h.runner.panes.get(body);
    };
    const pane = await draw();
    const plain = await draw();
    facts.firstAsk = { quote: !!pane.quote, focused: !!pane.input.focused, plainFocused: !!plain.input.focused };
  });
  // a paper annotated before this version (or by the skill alone): its Scholium annotations are counted
  await step(async () => { for (const locale of ['zh-CN', 'en-US']) {
    const h = harness({ locale, existing: [['zotero-scholium'], ['zotero-scholium'], ['zotero-scholium'], ['mine']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(20);
    const intro = () => pane.annot.list.children[0].children.map(c => c.textContent);
    const r = { intro: intro(), button: pane.annotGo.textContent, sendShown: !pane.send.hidden };
    pane.annotGo.click(); await settle(10);
    r.asked = pane.confirmRow.hidden ? null : pane.confirmRow.children[0].textContent;
    pane.confirmRow.children[1].click(); await settle(10);   // Cancel
    pane.more.click();
    pane.popover.node.children.find(c => /删除批注|Delete annotations/.test(c.textContent)).click(); await settle(60);
    r.afterDelete = { intro: intro(), button: pane.annotGo.textContent, erased: h.log.erased };
    facts['annotated_' + locale] = r;
  } });
  // the other agent wrote them: how many, by whom and when
  await step(async () => {
    const at = new Date(2026, 10, 4, 10, 0).getTime();
    const h = harness({ existing: [['zotero-scholium'], ['zotero-scholium']], prefs: { 'extensions.scholium.agent': 'codex' },
                        logs: { '/data/tmp/scholium/ATT1/applied.json': JSON.stringify({ config: 'D:/x/config.json', agent: 'claude', conv: 'annotate-claude-20261104-100000', at }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(20);
    facts.otherAgent = { intro: pane.annot.list.children[0].children.map(c => c.textContent), button: pane.annotGo.textContent };
  });
  // Delete annotations of the library's section: the PDF it shows, its outcome on the state line
  await step(async () => {
    const h = harness({ locale: 'en-US', secondPdf: true, existing: [['zotero-scholium']] });
    h.zotero.Items.get('ATT3').getAnnotations = () => [h.ann('X1', 'highlight', '#ff6666'), h.ann('X2', 'highlight', '#ffd400')];
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.see(true);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(20);
    pane.more.click();
    pane.popover.node.children.find(c => c.textContent === 'Delete annotations').click(); await settle(60);
    facts.deleteScope = { keys: pane.keys, confirms: h.log.confirms, erased: h.log.erased, state: pane.state.hidden ? null : pane.state.textContent,
                          notices: h.log.notices.map(n => n.descriptions) };
  });
  // the keyboard: the ring, a citation chip, the layers, the tabs
  await step(async () => {
    const SPATH = '/data/tmp/scholium/ATT1/sentences.json';
    const conv = 'chat-20261101-120000';
    const h = harness({ locale: 'en-US', logs: { [SPATH]: JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] }),
                                                  [DIR + conv + '.jsonl']: claudeTurn(1, 'u1').replace('回答1', 'see [#12]'),
                                                  [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    focusDoc = h.paneDoc;
    const doc = h.paneDoc;
    const active = () => { const a = doc.activeElement; return a ? (a.className || a.tagName) : null; };
    const k = {};
    k.ring = { tabindex: pane.ring.getAttribute('tabindex'), role: pane.ring.getAttribute('role'), shown: !pane.ring.hidden };
    // the ring from the keyboard: the focus goes to the layer itself, not to Compact; Esc brings it back
    pane.ring.focus();
    const enter = key(pane.ring, { key: 'Enter' });
    k.ring.enter = { layer: pane.popover && pane.popover.name, focus: active(), prevented: enter.defaultPrevented };
    key(pane.popover.node, { key: 'Escape' });
    k.ring.esc = { layer: (pane.popover && pane.popover.name) || null, back: doc.activeElement === pane.ring };
    const space = key(pane.ring, { key: ' ' });
    k.ring.space = { layer: pane.popover && pane.popover.name, prevented: space.defaultPrevented, focus: active() };
    h.runner.closePopover(pane);
    // the ring clicked while typing: its mousedown takes no focus, the layer opens, the message box keeps the focus
    pane.input.focus();
    const down = pane.ring.fire('mousedown');
    pane.ring.click();
    k.ring.mouse = { layer: pane.popover && pane.popover.name, box: doc.activeElement === pane.input, keepsFocus: !!down.prevented };
    key(pane.box, { key: 'Escape' });
    k.ring.mouse.esc = { layer: (pane.popover && pane.popover.name) || null, box: doc.activeElement === pane.input };
    // a citation chip focused from the keyboard: the card, without taking the focus; Enter locates the sentence
    const chip = all(pane.list).find(n => n.className === 'scholium-cite');
    k.chip = { tabindex: chip.getAttribute('tabindex'), role: chip.getAttribute('role') };
    chip.matches = sel => sel === ':focus-visible';
    chip.focus();
    k.chip.card = pane.popover && pane.popover.name;
    k.chip.stays = doc.activeElement === chip;
    const go = key(chip, { key: 'Enter' }); await settle(20);
    k.chip.located = h.log.readerOpened.length;
    k.chip.prevented = go.defaultPrevented;
    h.runner.closePopover(pane);
    pane.input.focus();
    // the settings layer, the ⋯ menu and the history from the keyboard: the focus goes in, and Esc brings it back
    pane.chip.focus(); keyClick(pane.chip);
    k.settings = { focus: doc.activeElement === pane.agent };
    key(pane.popover.node, { key: 'Escape' });
    k.settings.back = !pane.popover && doc.activeElement === pane.chip;
    pane.more.focus(); keyClick(pane.more);
    k.menu = { focus: active(), text: doc.activeElement.textContent };
    key(pane.popover.node, { key: 'Escape' });
    k.menu.back = !pane.popover && doc.activeElement === pane.more;
    pane.historyButton.focus(); keyClick(pane.historyButton); await settle(20);
    k.history = { focus: active() };
    key(pane.popover.node, { key: 'Escape' });
    k.history.back = !pane.popover && doc.activeElement === pane.historyButton;
    // the same with the mouse while typing: the layers open, the message box keeps the focus
    k.mouse = {};
    for (const [name, button] of [['settings', pane.chip], ['menu', pane.more], ['history', pane.historyButton]]) {
      pane.input.focus(); mouseClick(button); await settle(20);
      k.mouse[name] = { layer: pane.popover && pane.popover.name, box: doc.activeElement === pane.input };
      key(pane.box, { key: 'Escape' });
      k.mouse[name].closed = !pane.popover && doc.activeElement === pane.input;
    }
    // Tab out of a layer closes it; the focus leaving for nowhere (the app in the background, a control redrawn) does not
    pane.chip.focus(); keyClick(pane.chip);
    doc.activeElement = doc.documentElement;
    pane.popover.node.fire('focusout'); await later();
    k.tabOut = { nowhere: !!pane.popover };
    doc.activeElement = pane.list;
    pane.popover.node.fire('focusout'); await later();
    k.tabOut.away = (pane.popover && pane.popover.name) || null;
    // tabs and the history button
    k.tabs = { list: pane.tabChat.parent.getAttribute('role'), chat: pane.tabChat.getAttribute('aria-selected'),
               annotate: pane.tabAnnotate.getAttribute('aria-selected') };
    pane.tabAnnotate.click();
    k.tabs.after = [pane.tabChat.getAttribute('aria-selected'), pane.tabAnnotate.getAttribute('aria-selected')];
    pane.tabChat.click();
    k.history.label = pane.historyButton.getAttribute('aria-label');
    // the rename box leaves an input method's Enter to it
    keyClick(pane.historyButton); await settle(20);
    const row = pane.popover.node.children.find(c => /history-row/.test(c.className));
    row.children.find(c => /glyph edit/.test(c.className)).click(); await settle(5);
    const input = row.children[0];
    input.value = 'Half typed';
    const composing = key(input, { key: 'Enter', isComposing: true }); await settle(20);
    k.rename = { composing: composing.defaultPrevented, titles: JSON.parse(h.log.writes[DIR + 'index.json']).titles };
    key(input, { key: 'Enter' }); await settle(20);
    k.rename.done = JSON.parse(h.log.writes[DIR + 'index.json']).titles;
    facts.keyboard = k;
  });
  // a citation chip with the mouse: Locate in its card leaves the card closed; the chip clicked keeps the focus, and the
  // window's focus coming back to it brings no card
  await step(async () => {
    const SPATH = '/data/tmp/scholium/ATT1/sentences.json';
    const conv = 'chat-20261101-120000';
    const h = harness({ locale: 'en-US', logs: { [SPATH]: JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] }),
                                                  [DIR + conv + '.jsonl']: claudeTurn(1, 'u1').replace('回答1', 'see [#12]'),
                                                  [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    focusDoc = h.paneDoc;
    const chip = all(pane.list).find(n => n.className === 'scholium-cite');
    chip.matches = () => false;   // a focus from the mouse is not :focus-visible
    chip.fire('mouseenter');
    const card = pane.popover && pane.popover.node;
    chip.fire('mouseleave'); card.fire('mouseenter');
    await later(350);
    const locate = card.children[0].children[1];
    locate.focus(); locate.click(); await settle(20);
    const r = { located: h.log.readerOpened.length, afterLocate: (pane.popover && pane.popover.name) || null };
    chip.fire('mouseenter'); chip.focus(); chip.click(); chip.fire('mouseleave'); await later(400);
    r.afterClick = (pane.popover && pane.popover.name) || null;
    r.chipFocused = h.paneDoc.activeElement === chip;
    chip.fire('blur'); await later(400);
    chip.fire('focus'); await later(20);
    r.windowBack = (pane.popover && pane.popover.name) || null;
    facts.citeMouse = r;
  });
  // every finished run shows how long it worked, once: one without steps too, and one stopped before any step
  facts.stepless = {};
  await step(async () => { for (const locale of ['zh-CN', 'en-US']) {
    const reply = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                   said('An answer.'),
                   ev({ type: 'result', subtype: 'success', is_error: false, result: 'An answer.', session_id: 'S1', duration_ms: 14000, num_turns: 1,
                        usage: { input_tokens: 5, cache_creation_input_tokens: 0, cache_read_input_tokens: 4000, output_tokens: 90 } })];
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
    const h = harness({ locale, scripts: [reply, [init, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('Why?'); pane.send.click(); await settle(500);
    const lines = run => run.children.filter(c => c.className === 'scholium-fold')
      .map(c => ({ text: c.children[0].textContent, tag: c.children[0].tagName, cls: c.children[0].className }));
    const r = { state: pane.state.textContent, answered: lines(pane.list.children.at(-1)) };
    pane.input.type('Again?'); pane.send.click(); await settle(60);
    pane.send.click(); await settle(300);   // ■ before any step
    r.cancelled = lines(pane.list.children.at(-1));
    r.cancelledState = pane.state.textContent;
    facts.stepless[locale] = r;
  } });
  // Delete annotations: the PDF shown has none, another PDF of the paper has two; the PDF shown has one
  facts.deleteWords = {};
  await step(async () => { for (const locale of ['zh-CN', 'en-US']) for (const own of [[], [['zotero-scholium']]]) {
    const h = harness({ locale, secondPdf: true, existing: own });
    h.zotero.Items.get('ATT3').getAnnotations = () => [h.ann('X1', 'highlight', '#ff6666'), h.ann('X2', 'highlight', '#ffd400')];
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(20);
    pane.more.click();
    pane.popover.node.children.find(c => /删除批注|Delete annotations/.test(c.textContent)).click(); await settle(60);
    facts.deleteWords[locale + (own.length ? ' one' : ' none')] = { alerts: h.log.alerts, confirms: h.log.confirms, erased: h.log.erased };
  } });
  // the queue's rows and the quote strip are drawn again only when they change: a focused control stays
  await step(async () => {
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
    const h = harness({ locale: 'en-US', scripts: [[init, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.att1); await settle(40);
    const pane = p.pane();
    focusDoc = h.paneDoc;
    pane.input.type('First question'); pane.send.click(); await settle(60);
    pane.input.type('A follow-up'); pane.send.click(); await settle(20);
    const row = pane.queueBox.children.find(c => /scholium-queued/.test(c.className));
    const trash = row.children.find(c => /trash/.test(c.className || ''));
    trash.focus();
    h.runner.refresh(); h.runner.paintPane(pane);
    const queue = { kept: pane.queueBox.children.includes(row) && row.children.includes(trash), focus: h.paneDoc.activeElement === trash };
    pane.input.type('Another one'); pane.send.click(); await settle(20);
    queue.rows = pane.queueBox.children.filter(c => /scholium-queued/.test(c.className)).length;
    h.selection('A passage.', 2, '3')[0].click(); await settle(20);
    const drop = pane.quoteBox.children[1];
    drop.focus();
    h.runner.refresh(); h.runner.paintPane(pane);
    const quote = { kept: pane.quoteBox.children[1] === drop };
    drop.click();
    quote.gone = pane.quoteBox.hidden;
    facts.redraw = { queue, quote };
    h.runner.stop();
  });
  // a finished question: its time once, on its folded steps; the state line has the rest
  facts.finished = {};
  await step(async () => { for (const locale of ['zh-CN', 'en-US']) {
    const reply = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                   tool('Read', { file_path: 'D:\\x\\sentences.txt' }), answer('ok'), said('An answer.'),
                   ev({ type: 'result', subtype: 'success', is_error: false, result: 'An answer.', session_id: 'S1', duration_ms: 377000, num_turns: 3,
                        usage: { input_tokens: 5, cache_creation_input_tokens: 0, cache_read_input_tokens: 61000, output_tokens: 900 } })];
    const h = harness({ locale, scripts: [reply] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('Why?'); pane.send.click(); await settle(500);
    const run = pane.list.children.at(-1);
    facts.finished[locale] = { state: pane.state.textContent, fold: run.children.find(c => c.className === 'scholium-fold').children[0].textContent };
  } });
  // the reader's listeners on Zotero 7-9, whose unregisterEventListener keeps only the listener it is given, and on 10
  facts.readerListeners = {};
  const zoteroReader = fixed => ({ _registeredListeners: [],
    registerEventListener(type, handler, pluginID) { this._registeredListeners.push({ pluginID, type, handler }); },
    unregisterEventListener(type, handler) {
      this._registeredListeners = this._registeredListeners.filter(x => (fixed ? !(x.type === type && x.handler === handler) : x.type === type && x.handler === handler));
    },
    _unregisterEventListenerByPluginID(pluginID) { this._registeredListeners = this._registeredListeners.filter(x => x.pluginID !== pluginID); } });
  await step(async () => { for (const version of ['7.0.11', '8.0.4', '9.0.2', '10.0.7', 'unknown']) {
    const h = harness();
    const real = zoteroReader(/^1\d/.test(version));
    const other = () => {};
    real.registerEventListener('renderTextSelectionPopup', other, 'translate@example');
    real.registerEventListener('renderToolbar', other, 'translate@example');
    const calls = [];
    h.zotero.Reader.registerEventListener = (...a) => real.registerEventListener(...a);
    h.zotero.Reader.unregisterEventListener = (...a) => { calls.push(a[0]); real.unregisterEventListener(...a); };
    if (version !== 'unknown') h.zotero.version = version;
    const names = () => real._registeredListeners.map(l => l.pluginID + ':' + l.type);
    h.toggle.start('scholium'); h.runner.start('scholium');
    const ours = real._registeredListeners.filter(l => l.pluginID === 'scholium');
    h.runner.stop(); h.toggle.stop();
    const afterStop = names();
    // what a handler left registered does once its plugin stopped, and after it started again in the same copy
    const toolbar = [];
    h.toggle.onRenderToolbar = e => toolbar.push(e);
    const appended = [];
    const popup = () => ({ reader: { itemID: 'ATT1', _window: h.paneWin,
                                     _internalReader: { _lastViewPrimary: true, _state: { primaryViewSelectionPopup: { annotation: { text: 'A passage.', position: { pageIndex: 0, rects: [] } } } } } },
                           doc: { createElement: t => new El(t) }, params: { x: 1, y: 1 }, append: (...n) => appended.push(...n) });
    const fireAll = () => { for (const l of real._registeredListeners.filter(x => x.pluginID === 'scholium')) l.handler(popup()); };
    for (const l of ours) l.handler(popup());
    const stopped = { toolbar: toolbar.length, popup: appended.length };
    h.toggle.start('scholium'); h.runner.start('scholium');
    fireAll();
    const again = { toolbar: toolbar.length, popup: appended.length };
    h.runner.stop(); h.toggle.stop();
    real._unregisterEventListenerByPluginID('scholium');   // Zotero's own clean-up once the plugin stopped
    facts.readerListeners[version] = { afterStop, calls, stopped, again, afterObserver: names() };
  } });
  facts.errors = errors;
  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    # the harness with ScholiumToggle within reach, for the reader's listeners
    core = CORE.read_text(encoding="utf-8")
    patched = core.replace("return { runner, zotero: context.Zotero,", "return { runner, toggle: context.ScholiumToggle, zotero: context.Zotero,")
    assert patched != core
    script = tmp_path_factory.mktemp("plugin") / "harness.js"
    script.write_text(patched + "\n" + SCENARIOS, encoding="utf-8")
    completed = subprocess.run([NODE, str(script), str(BOOTSTRAP)], encoding="utf-8", capture_output=True, timeout=180)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_the_scenarios_ran_through(facts):
    assert facts["errors"] == []


def test_the_settings_layer_says_the_conversation_stays_when_the_agent_changes(facts):
    assert facts["switchNote"] == {"zh-CN": "对话不变，下一条消息由所选智能体回答；批注会话按智能体分开。",
                                   "en-US": "The conversation shown stays; the agent chosen answers the next message. "
                                            "Annotation sessions are each agent's own."}


def test_ask_scholium_shows_in_pdf_readers_only(facts):
    a = facts["askReaders"]
    assert a["snapshot"] == [], "an EPUB or snapshot reader has no Scholium section"
    assert a["none"] == {"nothing": 0, "blank": 0}, "no item without text selected"
    assert a["pdf"] == ["Ask Scholium"] and a["pending"] == ["ATT1"]


def test_ask_scholium_takes_the_selection_of_the_view_used_last(facts):
    assert facts["askReaders"]["secondary"] == {"text": "In the second view.", "page": "5"}


def test_ask_scholium_draws_zotero_10s_page_again_after_clearing_the_selection(facts):
    assert facts["askReaders"]["ten"] == {"cleared": 1, "rendered": 1}


def test_ask_scholium_closes_the_popup_on_zotero_7_to_9(facts):
    assert facts["askReaders"]["old"] == {"ranges": ["none"], "rendered": 1, "removed": 1}


def test_the_first_ask_of_a_reader_tab_focuses_the_message_box(facts):
    assert facts["firstAsk"] == {"quote": True, "focused": True, "plainFocused": False}


def test_the_annotations_tab_counts_the_papers_scholium_annotations(facts):
    zh, en = facts["annotated_zh-CN"], facts["annotated_en-US"]
    assert zh["intro"] == ["这篇已有 3 条 Scholium 批注", "高亮重点句并附译文，加页边批注和阅读笔记。"]
    assert en["intro"] == ["This paper carries 3 Scholium annotations",
                           "Highlights key sentences with translations, adds margin notes and a reading note."]
    assert zh["button"] == "重新批注" and en["button"] == "Annotate again"
    assert zh["sendShown"] is False, "no session to send words to"
    assert zh["asked"] == "重新批注会先删除这篇的 3 条 Scholium 批注（你自己的不动）。"
    # deleted: the introduction counts again
    assert zh["afterDelete"] == {"intro": ["还没有批注这篇", "高亮重点句并附译文，加页边批注和阅读笔记。"], "button": "批注这篇",
                                 "erased": ["E0", "E1", "E2"]}
    assert en["afterDelete"]["intro"][0] == "Not annotated yet" and en["afterDelete"]["button"] == "Annotate"


def test_the_annotations_tab_names_the_other_agent_that_wrote_them(facts):
    assert facts["otherAgent"] == {"intro": ["这篇已有 2 条 Scholium 批注", "高亮重点句并附译文，加页边批注和阅读笔记。",
                                             "上次由 Claude Code 在 11月4日 写入"], "button": "重新批注"}


def test_delete_annotations_of_the_section_deletes_the_pdf_shown(facts):
    d = facts["deleteScope"]
    assert d["keys"] == ["ATT1"]
    assert d["erased"] == ["E0"], "ATT3's annotations are another PDF's"
    assert d["state"] == "Deleted 1 Scholium annotation."
    assert d["notices"] == [], "the state line says it"


def test_delete_annotations_says_this_pdf(facts):
    w = facts["deleteWords"]
    assert w["zh-CN none"] == {"alerts": ["这个 PDF 没有 Scholium 批注，这篇论文也没有 Scholium 阅读笔记。\n\n"
                                          "这篇论文的另一个 PDF 上还有 2 条 Scholium 批注：打开那个 PDF 即可删除。"], "confirms": [], "erased": []}
    assert w["en-US none"] == {"alerts": ["This PDF carries no Scholium annotations, and the paper no Scholium reading notes.\n\n"
                                          "Another PDF of this paper carries 2 Scholium annotations: open that PDF to delete them."],
                               "confirms": [], "erased": []}
    assert w["zh-CN one"]["confirms"][0].startswith("将删除带 zotero-scholium 标签的这个 PDF 上的 1 条批注。")
    assert w["en-US one"]["confirms"][0].startswith("This deletes 1 annotation on this PDF, tagged zotero-scholium. ")
    assert w["zh-CN one"]["erased"] == w["en-US one"]["erased"] == ["E0"]


def test_focus_rings_and_the_ring_take_visible_zotero_colours():
    rules = css_rules()
    sheet = "\n".join(rules.values())
    assert "--color-focus-border" not in sheet
    rings = {sel: body for sel, body in rules.items() if ":focus-visible" in sel and "outline:" in body.replace(" ", "")}
    assert len(rings) >= 6
    for sel, body in rings.items():
        assert "var(--color-accent, var(--accent-blue))" in body, sel
    assert any(".scholium-ring:focus-visible" in sel for sel in rings) and any(".scholium-cite:focus-visible" in sel for sel in rings)
    warn = rules[".scholium-ring.warn"]
    assert "var(--accent-orange)" in warn and not re.search(r"#[0-9a-f]{3,6}\b", warn, re.I)


def test_the_ring_and_the_citation_chips_work_from_the_keyboard(facts):
    k = facts["keyboard"]
    assert k["ring"]["tabindex"] == "0" and k["ring"]["role"] == "button" and k["ring"]["shown"]
    # from the keyboard the context layer takes the focus itself: Enter or Space then cannot compact at once
    assert k["ring"]["enter"] == {"layer": "context", "focus": "scholium-popover context", "prevented": True}
    assert k["ring"]["esc"] == {"layer": None, "back": True}
    assert k["ring"]["space"] == {"layer": "context", "prevented": True, "focus": "scholium-popover context"}
    assert k["chip"] == {"tabindex": "0", "role": "button", "card": "cite", "stays": True, "located": 1, "prevented": True}


def test_the_ring_clicked_while_typing_leaves_the_focus_in_the_box(facts):
    assert facts["keyboard"]["ring"]["mouse"] == {"layer": "context", "box": True, "keepsFocus": True, "esc": {"layer": None, "box": True}}


def test_a_citation_card_comes_back_only_for_a_keyboard_focus(facts):
    assert facts["citeMouse"] == {"located": 1, "afterLocate": None, "afterClick": None, "chipFocused": True, "windowBack": None}


def test_a_layer_takes_the_focus_and_gives_it_back(facts):
    k = facts["keyboard"]
    assert k["settings"] == {"focus": True, "back": True}
    assert k["menu"]["focus"] == "scholium-menu-item" and k["menu"]["back"]
    assert k["history"]["focus"] == "scholium-history-open" and k["history"]["back"]
    assert k["tabOut"] == {"nowhere": True, "away": None}


def test_a_layer_opened_with_the_mouse_leaves_the_focus_in_the_box(facts):
    m = facts["keyboard"]["mouse"]
    assert m == {name: {"layer": name, "box": True, "closed": True} for name in ["settings", "menu", "history"]}


def test_the_tabs_and_the_history_button_carry_their_aria(facts):
    k = facts["keyboard"]
    assert k["tabs"] == {"list": "tablist", "chat": "true", "annotate": "false", "after": ["false", "true"]}
    assert k["history"]["label"] == "History"


def test_the_rename_box_leaves_an_input_methods_enter_alone(facts):
    r = facts["keyboard"]["rename"]
    assert r["composing"] is False and r["titles"] == {}
    assert r["done"] == {"chat-20261101-120000": "Half typed"}


def test_the_queue_and_the_quote_keep_a_focused_control_across_redraws(facts):
    r = facts["redraw"]
    assert r["queue"] == {"kept": True, "focus": True, "rows": 2}
    assert r["quote"] == {"kept": True, "gone": True}


def test_a_finished_questions_time_is_on_its_folded_steps_only(facts):
    f = facts["finished"]
    assert f["zh-CN"]["state"] == "完成 · 3 轮 · 62k tokens"
    assert f["en-US"]["state"] == "done · 3 turns · 62k tokens"
    assert f["zh-CN"]["fold"].startswith("已处理 ") and f["en-US"]["fold"].startswith("Worked for ")


def test_every_finished_run_shows_its_time_once(facts):
    for locale, worked, state, stopped in [("zh-CN", "已处理 ", "完成 · 1 轮 · 4k tokens", "已取消"),
                                           ("en-US", "Worked for ", "done · 1 turn · 4k tokens", "cancelled")]:
        f = facts["stepless"][locale]
        assert f["state"] == state and f["cancelledState"] == stopped, locale
        # without steps: the line, with nothing to open
        for line in (f["answered"], f["cancelled"]):
            assert len(line) == 1 and line[0]["text"].startswith(worked) and "›" not in line[0]["text"], (locale, line)
            assert line[0]["tag"] != "button" and line[0]["cls"] == "scholium-fold-head plain", (locale, line)
    assert "cursor: default" in css_rules()[".scholium-fold-head.plain"]


@pytest.mark.parametrize("version", ["7.0.11", "8.0.4", "9.0.2", "unknown"])
def test_zotero_7_to_9_keep_the_other_plugins_reader_listeners(facts, version):
    r = facts["readerListeners"][version]
    assert r["calls"] == [], "Zotero 7-9 drop every other listener in unregisterEventListener"
    assert r["afterStop"][:2] == ["translate@example:renderTextSelectionPopup", "translate@example:renderToolbar"]
    assert r["afterObserver"] == ["translate@example:renderTextSelectionPopup", "translate@example:renderToolbar"]
    assert r["stopped"] == {"toolbar": 0, "popup": 0}, "a handler left registered does nothing"
    assert r["again"] == {"toolbar": 1, "popup": 1}, "one call each after a restart of the same copy"


def test_zotero_10_unregisters_the_reader_listeners(facts):
    r = facts["readerListeners"]["10.0.7"]
    assert r["calls"] == ["createViewContextMenu", "renderToolbar"] * 2
    assert r["afterStop"] == ["translate@example:renderTextSelectionPopup", "translate@example:renderToolbar"]
    assert r["stopped"] == {"toolbar": 0, "popup": 0}
    assert r["again"] == {"toolbar": 1, "popup": 1}
