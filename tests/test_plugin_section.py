"""The Scholium section's layout: the settings page, the tabs, the settings layer, the message box and its round
button, the context ring, the transcript by runs, the history layer, the saved prompts and the retry."""
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest

from plugin_harness import BOOTSTRAP, NODE, PLUGIN, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  // the settings page is registered once the plugin knows its root; the section's ⋯ menu opens it
  {
    const h = harness();
    h.runner.rootURI = 'jar:file:///x/scholium.xpi!/';
    h.runner.start('scholium@zotero-scholium');
    await settle(20);
    const o = h.log.prefPanes[0];
    facts.settingsPage = { src: o.src, scripts: o.scripts, label: o.label, pluginID: o.pluginID, id: h.runner.prefPaneID };
    h.runner.openSettings();
    facts.settingsPage.opened = h.log.openedPrefs;
    facts.settingsPage.defaults = [h.runner.sendShortcut(), h.runner.followUpMode(), h.runner.contextRingOn()];
    h.store.set('extensions.scholium.sendShortcut', 'enter');
    h.store.set('extensions.scholium.followUpMode', 'steer');
    h.store.set('extensions.scholium.contextRing', false);
    facts.settingsPage.set = [h.runner.sendShortcut(), h.runner.followUpMode(), h.runner.contextRingOn()];
    h.store.set('extensions.scholium.sendShortcut', 'bogus');
    facts.settingsPage.bogus = h.runner.sendShortcut();
    h.store.set('extensions.scholium.sendShortcut', 'cmdIfMultiline');
    facts.settingsPage.multiline = h.runner.sendShortcut();
    h.runner.stop();
    facts.settingsPage.afterStop = h.runner.prefPaneID;
    facts.settingsPage.noClaude = h.runner.text('noClaude');
    facts.settingsPage.noCodex = h.runner.text('noCodex');
    facts.settingsPage.settingsOpen = h.runner.text('settingsOpen');
  }
  {
    const h = harness({ locale: 'en-US' });
    facts.english = ['noClaude', 'noCodex', 'settingsOpen'].map(k => h.runner.text(k));
    facts.englishCard = h.runner.text('numHighlights', 5, 2);
    // the card's words follow its numbers: one of each, then two
    const card = n => h.runner.countsNode(h.paneDoc, { highlights: n, core: 1, margin: n, notes: n, readingNotes: n, turns: 0, tokens: 0 })
      .children[1].children.map(c => c.textContent);
    facts.englishCardWords = [card(1), card(2)];
    facts.chineseCardWords = (() => { const z = harness(); return [1, 2].map(n => ['numMargin', 'numNotes', 'numReading'].map(k => z.runner.text(k, n))
      .concat(z.runner.text('numHighlights', n, 1))); })();
  }
  // the settings chip opens a layer with the three selects; a click outside or Esc closes it; one layer at a time
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const chip = pane.chip.textContent;
    pane.chip.click();
    const open = { name: pane.popover && pane.popover.name, selects: [pane.agent, pane.model, pane.effort].every(s => pane.popover.node.contains(s)),
                   note: pane.popover.node.textContent.includes('对话不变，下一条消息由所选智能体回答') };
    // a choice in a select's dropdown, which Zotero puts in the window's #ContentSelectDropdown outside the layer
    const menulist = new h.El('menulist'); menulist.id = 'ContentSelectDropdown';
    const option = new h.El('menuitem'); menulist.append(option);
    option.closest = sel => { for (let x = option; x; x = x.parent) if (sel === '#' + x.id) return x; return null; };
    h.paneDoc.dispatch('mousedown', { target: option });
    const afterDropdown = pane.popover && pane.popover.name;
    h.paneDoc.dispatch('mousedown', { target: pane.list });
    const afterOutside = pane.popover;
    pane.chip.click(); key(pane.box, { key: 'Escape' });
    const afterEsc = pane.popover;
    pane.more.click();
    const menu = pane.popover.node.children.map(c => c.textContent);
    pane.chip.click();
    facts.chip = { chip, open, afterDropdown, afterOutside, afterEsc, menu, oneAtATime: pane.popover.name,
                   parts: pane.chip.children.map(c => [c.className, c.textContent]), tip: pane.chip.title };
    // a finished run's state: its line, and in its tooltip the line and the tokens' detail
    h.runner.notes.set('ATT1/chat', { text: '完成 · 21s · 4 轮 · 62k tokens', title: '输入 3 · 输出 640', at: Date.now() });
    h.runner.paintPane(pane);
    facts.chip.done = [pane.state.textContent, pane.state.title];
    h.runner.notes.delete('ATT1/chat'); h.runner.paintPane(pane);
    facts.chip.none = [pane.state.hidden, pane.state.title];
    pane.model.change('fable'); await settle(10);
    facts.chip.after = pane.chip.textContent;
    facts.chip.afterParts = pane.chip.children.map(c => c.className);
    // a section drawn once the models are known (no list asked for again) has the same parts
    const second = await h.pane(h.item2); await settle(20);
    facts.chip.secondParts = second.pane().chip.children.map(c => c.className);
    // a model without an effort shows only the model and the arrow
    h.store.set('extensions.scholium.claudeModel', 'haiku');
    h.runner.paintChip(pane);
    facts.chip.noEffort = pane.chip.children.map(c => [c.className, c.textContent]);
    // codex with no model saved: the name is the default's label, the tooltip still names the agent
    h.store.set('extensions.scholium.agent', 'codex');
    h.store.set('extensions.scholium.codexModel', '');
    h.runner.models.codex = [{ value: 'gpt-x', label: 'GPT X', title: '', efforts: ['low'] }];
    h.runner.paintChip(pane);
    facts.chip.codexDefault = { name: pane.chip.children[0].textContent, tip: pane.chip.title };
  }
  // the layer is fixed in the window's document: placed from the anchor's viewport rect, closed by a scroll, a resize, a
  // re-render and the section's destruction, leaving no node and no listener behind
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const root = h.paneDoc.documentElement;
    const scroller = new h.El('div');
    scroller.rect = { top: 100, left: 50, right: 350, bottom: 500, width: 300, height: 400 };
    p.body.closest = sel => (sel === 'item-details' ? { _paneParent: scroller } : null);
    const f = {};
    pane.chip.rect = { top: 120, left: 60, right: 200, bottom: 140, width: 140, height: 20 };
    pane.chip.click();
    f.parent = pane.popover.node.parent === root && !pane.box.contains(pane.popover.node);
    f.below = [pane.popover.node.style.top, pane.popover.node.style.bottom];
    f.maxWidth = pane.popover.node.style.maxWidth;
    pane.chip.click();
    pane.chip.rect = { top: 400, left: 340, right: 480, bottom: 420, width: 140, height: 20 };
    pane.chip.click();
    f.above = [pane.popover.node.style.top, pane.popover.node.style.bottom, pane.popover.node.style.left];
    f.listening = [(scroller.listeners.scroll || []).length, (h.paneWin.listeners.resize || []).length];
    scroller.listeners.scroll.forEach(g => g({}));
    f.afterScroll = [pane.popover, root.children.some(c => /scholium-popover/.test(c.className)), (scroller.listeners.scroll || []).length,
                     (h.paneWin.listeners.resize || []).length];
    pane.chip.click();
    h.paneWin.dispatch('resize');
    f.afterResize = [pane.popover, root.children.some(c => /scholium-popover/.test(c.className))];
    pane.more.click();
    const old = h.paneDoc.listeners.mousedown.length;
    h.log.sections[0].onRender({ doc: h.paneDoc, body: p.body, item: h.item1 });
    const fresh = p.pane();
    f.afterRender = [pane.popover, root.children.some(c => /scholium-popover/.test(c.className)), old, h.paneDoc.listeners.mousedown.length,
                     fresh !== pane];
    fresh.more.click();
    h.log.sections[0].onDestroy({ body: p.body });
    f.afterDestroy = [root.children.some(c => /scholium-popover/.test(c.className)), h.paneDoc.listeners.mousedown.length, (h.paneWin.listeners.resize || []).length];
    facts.layer = f;
  }
  // the section is as tall as the side pane shows, less the gaps around its body measured from the section; it follows the
  // pane's size, falls back to the window's resize and to the constants, and lets go of its listeners
  {
    const h = harness();
    h.runner.start('x');
    const scroller = new h.El('div'); scroller.clientHeight = 900;
    const section = new h.El('collapsible-section'); section.rect = { top: 0, left: 0, right: 300, bottom: 504, width: 300, height: 504 };
    const closest = sel => (sel === 'item-details' ? { _paneParent: scroller } : sel === 'collapsible-section' ? section : null);
    const p = await h.pane(h.item1, { closest });
    p.body.rect = { top: 30, left: 0, right: 300, bottom: 500, width: 300, height: 470 };
    await settle(40);
    const pane = p.pane();
    h.runner.fitPane(pane);
    const first = pane.box.style.height;
    scroller.clientHeight = 700; h.resize(scroller); await settle(5);
    const second = pane.box.style.height;
    scroller.clientHeight = 200; h.resize(scroller); await settle(5);
    const small = pane.box.style.height;
    section.rect = { top: 0, left: 0, right: 300, bottom: 600, width: 300, height: 600 };
    scroller.clientHeight = 900; h.resize(scroller); await settle(5);
    const measured = pane.box.style.height;
    const watched = h.observers.resize.filter(o => !o.off && o.el === scroller).length;
    h.log.sections[0].onRender({ doc: h.paneDoc, body: p.body, item: h.item1 });
    const afterRender = [h.observers.resize.filter(o => !o.off && o.el === scroller).length, watched];
    h.log.sections[0].onDestroy({ body: p.body });
    const afterDestroy = h.observers.resize.filter(o => !o.off).length;
    // without a section element: the constants; without ResizeObserver: the window's resize
    const g = harness();
    g.runner.start('x');
    const s2 = new g.El('div'); s2.clientHeight = 900;
    delete g.paneWin.ResizeObserver;
    const q = await g.pane(g.item1, { closest: sel => (sel === 'item-details' ? { _paneParent: s2 } : null) });
    await settle(40);
    const pane2 = q.pane();
    const fallback = pane2.box.style.height;
    s2.clientHeight = 700; g.paneWin.dispatch('resize');
    const viaWindow = pane2.box.style.height;
    g.log.sections[0].onDestroy({ body: q.body });
    // no scroller at all: the height is left to the stylesheet
    const k = harness();
    k.runner.start('x');
    const r = await k.pane(k.item1);
    await settle(40);
    // while the section is at the top of the pane, a section above it that grows leaves it there; scrolled away, it moves
    const t = harness();
    t.runner.start('x');
    const sc = new t.El('div'); sc.clientHeight = 900; sc.rect = { top: 100, left: 0, right: 300, bottom: 1000, width: 300, height: 900 };
    const above = new t.El('attachments-box'), own = new t.El('item-pane-custom-section');
    sc.append(above, own);
    const sec = new t.El('collapsible-section');
    const at = top => { sec.rect = { top, left: 0, right: 300, bottom: top + 900, width: 300, height: 900 }; };
    at(100);
    const kp = await t.pane(t.item1, { closest: sel => (sel === 'item-details' ? { _paneParent: sc } : sel === 'collapsible-section' ? sec
                                            : sel === 'item-pane-custom-section' ? own : null) });
    await settle(40);
    sc.scrollTop = 1296;
    at(125); t.resize(above);
    const kept = sc.scrollTop;
    at(100); sc.fire('scroll');
    at(100); t.resize(own); t.resize(above);
    const still = sc.scrollTop;
    at(400); sc.fire('scroll');
    at(425); t.resize(above);
    const away = sc.scrollTop;
    const ownWatched = t.observers.resize.some(o => !o.off && o.cb && o.els.includes(own));
    const scrollListeners = (sc.listeners.scroll || []).length;
    t.log.sections[0].onDestroy({ body: kp.body });
    facts.keepTop = { kept, still, away, ownWatched, scrollListeners, afterDestroy: (sc.listeners.scroll || []).length };
    // a section drawn while collapsed (Zotero gives it no async render) shows its conversation when it is opened
    {
      const o = harness();
      o.runner.start('x');
      const cs = new o.El('collapsible-section'); cs.open = false;
      const body = new o.El('div'); body.closest = sel => (sel === 'collapsible-section' ? cs : null);
      o.log.sections[0].onItemChange({ item: o.item1, setEnabled: () => {} });
      o.log.sections[0].onRender({ doc: o.paneDoc, body, item: o.item1 });
      await settle(30);
      const op = o.runner.panes.get(body);
      const before = op.list.children.length;
      cs.fire('toggle'); await settle(30);
      const closed = op.showing || 0;
      cs.open = true; cs.fire('toggle'); await settle(60);
      const after = op.list.children.map(c => c.className);
      cs.fire('toggle'); await settle(30);
      const again = op.showing;
      o.log.sections[0].onRender({ doc: o.paneDoc, body, item: o.item1 });
      const rendered = (cs.listeners.toggle || []).length;
      o.log.sections[0].onDestroy({ body });
      facts.openLoads = { before, closed, after, again, rendered, destroyed: (cs.listeners.toggle || []).length };
    }
    facts.fit = { first, second, small, measured, scroller: pane.scroller === scroller, afterRender, afterDestroy, fallback, viaWindow,
                  windowListeners: (g.paneWin.listeners.resize || []).length, none: r.pane().box.style.height || '',
                  noDrag: [typeof h.runner.logHeight, typeof h.runner.paneResized, h.runner.LOG_HEIGHT, r.pane().list.attrs.style || ''] };
  }
  // the menu's items close the layer, then act
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const f = {};
    pane.more.click();
    f.logDisabled = pane.popover.node.children[0].disabled;
    pane.popover.node.children[3].click();
    f.settings = [pane.popover, h.log.openedPrefs.length];
    pane.more.click();
    pane.more.click();
    f.toggled = pane.popover;
    pane.more.click();
    pane.popover.node.children[1].click();
    await settle(20);
    f.profile = [pane.popover, !!h.sheet()];
    // inside the layer a mousedown keeps it open, Esc in it closes it, the chip toggles it, and a second layer replaces the first
    const layers = () => h.paneDoc.documentElement.children.filter(c => /scholium-popover/.test(c.className)).length;
    pane.chip.click();
    h.paneDoc.dispatch('mousedown', { target: pane.model });
    f.inside = pane.popover && pane.popover.name;
    key(pane.popover.node, { key: 'Escape' });
    f.escInLayer = pane.popover;
    pane.chip.click(); pane.chip.click();
    f.chipToggled = pane.popover;
    pane.more.click(); pane.chip.click();
    f.layers = layers();
    facts.menuItems = f;
  }

  // the two tabs: the chat shows conversations; the annotation tab its own view; the state line follows the tab; the
  // other tab carries a dot while its run goes on
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const first = { tab: pane.tab, chatShown: !pane.chatView.hidden, annotShown: !pane.annotView.hidden };
    pane.tabAnnotate.click(); await settle(10);
    const second = { tab: pane.tab, chatShown: !pane.chatView.hidden, annotShown: !pane.annotView.hidden,
                     selected: [pane.tabChat.className, pane.tabAnnotate.className] };
    pane.tabChat.click(); pane.input.type('一个问题'); pane.send.click(); await settle(200);   // a chat run, held open
    const chatState = p.view().state, chatTitle = pane.state.title;
    const dotHere = pane.tabChatDot.hidden;
    pane.tabAnnotate.click(); await settle(10);
    facts.tabs = { first, second, chatState, chatTitle, dotHere, annotState: p.view().state, chatDot: pane.tabChatDot.hidden === false,
                   annotDot: pane.tabAnnotateDot.hidden === false };
    h.runner.cancel(); await settle(200);
  }
  // a run of the annotation kind shows its transcript in the annotation tab and not in the chat; the dot is on the other tab
  {
    const h = harness({ gateFirst: true });
    const real = h.runner.resolve.bind(h.runner);
    h.runner.resolve = async i => { const j = await real(i); if (j) j.kind = 'annotate'; return j; };
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const f = { chatBefore: pane.list.children.length, introBefore: pane.annot.list.children.includes(pane.annotIntro) };
    await h.runner.annotate([h.item1]); await settle(200);
    f.kind = h.runner.transcriptKind;
    f.chatTab = { entries: pane.list.children.length, state: p.view().state, annotDot: pane.tabAnnotateDot.hidden === false,
                  chatDot: pane.tabChatDot.hidden === false };
    pane.tabAnnotate.click(); await settle(10);
    f.annotTab = { entries: pane.annot.list.children.length, live: pane.annot.live, running: p.view().state !== null && p.view().stateKind === 'scholium-state running', intro: pane.annot.list.children.includes(pane.annotIntro),
                   annotDot: pane.tabAnnotateDot.hidden === false, chatDot: pane.tabChatDot.hidden === false, newChat: pane.newChat.hidden,
                   history: pane.historyButton.hidden };
    f.chatAfter = pane.list.children.length;
    pane.more.click();
    f.annotLog = pane.popover.node.children[1].disabled;
    h.runner.closePopover(pane);
    await h.runner.showConversation(pane);
    f.chatKept = [pane.live, pane.annot.live];
    h.runner.cancel(); await settle(300);
    facts.kindRouting = f;
  }
  // a waiting job of the other kind carries the dot as well
  {
    const h = harness({ gateFirst: true });
    const real = h.runner.resolve.bind(h.runner);
    h.runner.resolve = async i => { const j = await real(i); if (j && i === h.item2) j.kind = 'annotate'; return j; };
    h.runner.start('x');
    const p = await h.pane(h.item2);
    await settle(40);
    const pane = p.pane();
    await h.runner.annotate([h.item1]); await settle(100);
    await h.runner.annotate([h.item2]); await settle(50);
    const f = { chatBusy: h.runner.busyKind(pane, 'chat'), annotBusy: h.runner.busyKind(pane, 'annotate'),
                views: [h.runner.viewOf(pane, 'chat') === pane, h.runner.viewOf(pane, 'annotate') === pane.annot, h.runner.paneViews(pane).length],
                dot: pane.tabAnnotateDot.hidden === false };
    f.states = [p.view().state];
    pane.tabAnnotate.click(); await settle(10);
    f.states.push(p.view().state);
    facts.queuedDot = f;
    h.runner.cancel(); await settle(300);
  }
  // the annotation tab: the intro, the annotate button in the message row with the box's words as extra instructions, its ⋯ menu
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const f = { chatRow: [pane.annotGo.hidden, pane.send.hidden], lists: [pane.chatView.children.includes(pane.list), pane.annotView.children.includes(pane.annot.list)] };
    pane.tabAnnotate.click(); await settle(10);
    f.row = { intro: pane.annot.list.children.includes(pane.annotIntro), go: pane.annotGo.hidden, goText: pane.annotGo.textContent, send: pane.send.hidden,
              annotList: pane.annot.list.hidden, placeholder: pane.input.placeholder, old: [pane.annotate, pane.cancel, pane.remove, pane.profile, pane.log].map(x => x === undefined) };
    pane.more.click();
    f.menu = pane.popover.node.children.map(c => [c.textContent, !!c.disabled]);
    pane.popover.node.children[1].click();
    f.logClosed = pane.popover;
    pane.input.type('只标方法部分'); pane.annotGo.click(); await settle(300);
    f.extra = h.log.stdin.some(t => t.includes('只标方法部分'));
    pane.more.click();
    f.busyMenu = pane.popover.node.children.map(c => !!c.disabled);
    f.tabsKeepBusyMenu = pane.tab;
    h.runner.cancel(); await settle(200);
    facts.annotTab = f;
  }

  // the message an annotation run is writing is drawn in the annotation tab
  {
    const piece = text => ev({ type: 'stream_event', session_id: 'S1', parent_tool_use_id: null,
                               event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } } });
    const h = harness({ scripts: [[SCRIPT[0], piece('写到一半'), 'WAIT']] });
    const real = h.runner.resolve.bind(h.runner);
    h.runner.resolve = async i => { const j = await real(i); if (j) j.kind = 'annotate'; return j; };
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    await h.runner.annotate([h.item1]); await settle(300);
    await new Promise(r => setTimeout(r, 150));   // the draft is set a moment after its pieces
    facts.kindDraft = { annot: !!pane.annot.draft, chat: !!pane.draft, inAnnot: pane.annot.list.children.length && pane.annot.list.children.at(-1).textContent.includes('写到一半'),
                        inChat: pane.list.children.some(c => c.textContent.includes('写到一半')) };
    h.runner.cancel(); await settle(300);
  }
  // the state line of the annotation tab does not show the chat's outcome; a tab switch closes the layer
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(300);
    const chat = p.view().state;
    pane.more.click();
    pane.tabAnnotate.click(); await settle(10);
    facts.stateByTab = { chat, annot: p.view().state, layer: pane.popover };
  }
  // the round button: grey ↑ when empty, ↑ to send, ■ to stop while the paper runs with nothing typed, ↑ that queues while
  // it runs with words typed; the send shortcut; Esc twice stops
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const b = () => [pane.send.textContent, pane.send.disabled, pane.send.title];
    const idle = b();
    pane.input.type('第一个问题');
    const typed = b();
    const keyAt = (mode, opts, text = 'x') => { h.store.set('extensions.scholium.sendShortcut', mode); return h.runner.sendKey(Object.assign({ key: 'Enter' }, opts), text); };
    const keys = {
      always: [keyAt('cmdAlways', {}), keyAt('cmdAlways', { ctrlKey: true }), keyAt('cmdAlways', { ctrlKey: true, shiftKey: true })],
      enter: [keyAt('enter', {}), keyAt('enter', { shiftKey: true }), keyAt('enter', { ctrlKey: true })],
      multiline: [keyAt('cmdIfMultiline', {}, 'one line'), keyAt('cmdIfMultiline', {}, 'two\nlines'), keyAt('cmdIfMultiline', { ctrlKey: true }, 'two\nlines')] };
    keys.composing = h.runner.sendKey({ key: 'Enter', ctrlKey: true, isComposing: true }, 'x');
    keys.other = h.runner.sendKey({ key: 'a', ctrlKey: true }, 'x');
    h.store.set('extensions.scholium.sendShortcut', 'cmdAlways');
    // the hint line under each shortcut, in both languages; the key sends, and passes whether it inverts
    const hints = {};
    for (const mode of ['enter', 'cmdIfMultiline', 'cmdAlways']) { h.store.set('extensions.scholium.sendShortcut', mode); h.runner.paintPane(pane); hints[mode] = pane.hint.textContent; }
    h.store.set('extensions.scholium.sendShortcut', 'cmdAlways'); h.runner.paintPane(pane);
    const sends = [];
    const realSend = h.runner.sendFromPane;
    h.runner.sendFromPane = (pn, invert) => sends.push(invert);
    const press = opts => key(pane.input, Object.assign({ key: 'Enter' }, opts));
    const pressed = [press({ ctrlKey: true }).defaultPrevented, press({ ctrlKey: true, shiftKey: true }).defaultPrevented, press({}).defaultPrevented];
    h.runner.sendFromPane = realSend;
    const english = (() => { const e = harness({ locale: 'en-US' }); return ['sendTip', 'stopTip', 'queueTip', 'steerTip', 'escAgain', 'sendHintEnter', 'contextLabel', 'contextTitle2', 'partInput', 'partCache', 'partOutput']
      .map(k => e.runner.text(k)).concat([e.runner.text('sendHintMultiline', 'Ctrl'), e.runner.text('contextShare', '1k', '2k', 50), e.runner.text('tokens', '3k')]); })();
    pane.send.click(); await settle(200);                       // runs, held open
    const running = b();
    pane.input.type('下一个');
    const runningTyped = b();
    // follow-ups of a run: queued by default; steered when the setting says so and the agent can steer, or the key inverts it
    const follow = () => [h.runner.followUpFor(pane), h.runner.followUpFor(pane, true)];
    const followClaude = follow();
    h.store.set('extensions.scholium.followUpMode', 'steer');
    const followClaudeSteer = follow();
    const job = h.runner.job, agent = job.agent, cur = h.runner.current;
    job.agent = 'codex'; cur.steer = async () => {};                         // a Codex turn under way, which takes words
    const followCodex = follow();
    h.runner.paintSend(pane);
    const steerTitle = pane.send.title;
    pane.tab = 'annotate'; const followAnnot = follow(); pane.tab = 'chat';      // another tab's run is not this one's to steer
    const keys0 = pane.keys; pane.keys = []; const followElsewhere = follow(); pane.keys = keys0;
    h.store.set('extensions.scholium.followUpMode', 'queue');
    const followCodexQueue = follow();
    job.agent = agent; delete cur.steer;
    pane.input.type('');
    // the live ring: the running paper's context, repainted each second
    job.context = { used: 300000, window: 1000000 };
    await new Promise(r => setTimeout(r, 40)); await settle(20);
    const liveRing = pane.ring.hidden ? null : pane.ring.title;
    job.context = null;
    pane.tab = 'annotate'; h.runner.stopFromPane(pane); pane.tab = 'chat'; h.runner.paintPane(pane);      // the stop of another tab leaves this run be
    const keptOther = !!h.runner.job && !h.runner.current.cancelled;
    // Esc closes a layer first, without asking to stop
    pane.chip.click();
    key(pane.box, { key: 'Escape' });
    const layerFirst = [pane.popover, pane.escAt || 0, pane.hint.textContent];
    key(pane.box, { key: 'Escape' });
    const armed = [pane.hint.textContent, !!h.runner.current && !h.runner.current.cancelled, h.live().includes(h.runner.ESC_MS + 50)];
    pane.escAt = Date.now() - h.runner.ESC_MS - 10;              // too late: the hint lapses, and Esc asks again
    const lapse = h.timers.find(x => x.live && x.ms === h.runner.ESC_MS + 50); lapse.live = false; lapse.f();
    const lapsed = pane.hint.textContent;
    key(pane.box, { key: 'Escape' });
    const late = [pane.hint.textContent, !!h.runner.current && !h.runner.current.cancelled];
    key(pane.box, { key: 'Escape' }); await settle(200);
    const idleEsc = key(pane.box, { key: 'Escape' });            // nothing runs: Esc is left alone
    facts.button = { idle, typed, keys, hints, pressed, sends, english, running, runningTyped, follow: [followClaude, followClaudeSteer, followCodex, followCodexQueue],
                     steerTitle, followAnnot, followElsewhere, keptOther, liveRing, layerFirst, armed, lapsed, late, stopped: !h.runner.job, hintAfter: pane.hint.textContent, idleEsc: [idleEsc.defaultPrevented, idleEsc.stopped] };
  }
  // the context ring: hidden without a window, its tooltip in Codex's words, orange from 80 %, hidden when switched off
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.context = { used: 550000, window: 1000000, parts: { input: 60000, cache: 440000, output: 50000 } }; h.runner.paintPane(pane);
    const half = { shown: !pane.ring.hidden, cls: pane.ring.className, title: pane.ring.title, share: pane.ring.style.share };
    pane.ring.click();
    const bar = pane.popover.node.children;
    const parts = { names: bar.map(c => c.className), head: bar[0].textContent, segs: bar[1].children.map(s => [s.className, s.style.w]), legend: bar[2].children.map(c => c.textContent) };
    const boxes = { head: bar[0].children.map(c => [c.tagName || '#text', c.textContent]), legend: bar[2].children.map(c => c.children.map(x => [x.tagName || '#text', x.textContent])) };
    pane.ring.click();
    const toggled = pane.popover;
    pane.context = { used: 800000, window: 1000000 }; h.runner.paintPane(pane);
    const edge = pane.ring.className;
    pane.context = { used: 1100000, window: 1000000 }; h.runner.paintPane(pane);
    const over = pane.ring.style.share;
    pane.context = { used: 850000, window: 1000000 }; h.runner.paintPane(pane);
    const full = pane.ring.className;
    pane.ring.click();
    const layer = pane.popover && pane.popover.node.textContent;
    const noBar = pane.popover.node.children.length;
    h.store.set('extensions.scholium.contextRing', false); h.runner.paintPane(pane);
    const claude = h.runner.contextAfter({ type: 'assistant', message: { usage: { input_tokens: 2, cache_creation_input_tokens: 5000, cache_read_input_tokens: 40000, output_tokens: 100 } } }, null);
    const codex = h.runner.contextAfter({ method: 'thread/tokenUsage/updated', params: { tokenUsage: { modelContextWindow: 9000,
      last: { totalTokens: 1050, inputTokens: 1000, cachedInputTokens: 600, outputTokens: 50 } } } }, null);
    facts.ring = { half, parts, boxes, toggled, edge, over, full, layer, noBar, off: pane.ring.hidden, claude, codex,
                   k: [999, 550123, 1000000, 2567000, 2567600].map(n => h.runner.kTokens(n)) };
  }

  // a run in the transcript: the words, one line for its steps (what it does while it runs, then how long it worked; the
  // steps on a click), the answer, then the model and the time
  {
    const h = harness({ script: SCRIPT.concat(['HOLD', LAST, RESULT]) });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('这篇讲什么？'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    const last = () => pane.list.children.at(-1);
    const foldOf = n => n.children.find(c => c.className.startsWith('scholium-fold'));
    const liveLine = foldOf(last()).children[0].textContent;
    h.log.release(); await settle(300);
    const parts = last().children.map(c => c.className);
    const closed = [foldOf(last()).children[0].textContent, foldOf(last()).children.length];
    foldOf(last()).children[0].click(); await settle(5);
    const opened = foldOf(last()).children[1].children.map(c => c.className);
    foldOf(last()).children[0].click(); await settle(5);
    facts.runs = { liveLine, parts, closed, opened, reclosed: foldOf(last()).children.length, meta: last().children.at(-1).textContent };
    // a log of an earlier version, without run lines: one run all the same
    const g = harness({ logs: { [CONV1]: SCRIPT.concat([LAST, RESULT]).join('') } });
    g.runner.start('x');
    const q = await g.pane(g.item1);
    facts.runs.legacy = q.pane().list.children.map(r => r.children.map(c => c.className));
  }
  // steps opened while the run goes on stay open as it goes on and after it ended; the run stays one node; a reader
  // scrolled up stays where they are
  {
    const h = harness({ script: SCRIPT.slice(0, 6).concat(['HOLD'], SCRIPT.slice(6), [LAST, RESULT]) });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('这篇讲什么？'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    const fold = () => pane.list.children.at(-1).children.find(c => c.className === 'scholium-fold');
    const drawn = (await h.pane(h.item1)).pane();   // a section drawn while the run goes on
    const drawnHead = drawn.list.children.at(-1).children.find(c => c.className === 'scholium-fold').children[0].textContent;
    fold().children[0].click(); await settle(5);
    const during = [fold().children[0].textContent, fold().children[1].children.length, fold().children[0].className];
    Object.defineProperty(pane.list, 'scrollHeight', { get: () => 1000, configurable: true });
    pane.list.scrollTop = 0;
    h.log.release(); await settle(300);
    facts.foldKept = { drawnHead, during, after: [fold().children[0].textContent, fold().children[1].children.length, fold().children[0].className],
                       runs: pane.list.children.length,
                       scrollTop: pane.list.scrollTop };
  }
  // a run of the annotation kind leaves the chat's finished run as it was; each view knows its section
  {
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(300);
    const real = h.runner.resolve.bind(h.runner);
    h.runner.resolve = async i => { const j = await real(i); if (j) j.kind = 'annotate'; return j; };
    await h.runner.annotate([h.item1]); await settle(200);
    const head = () => pane.list.children.at(-1).children.find(c => c.className === 'scholium-fold').children[0];
    head().click(); await settle(5);
    facts.otherKindFold = { live: pane.live, kind: h.runner.transcriptKind, running: !!h.runner.job, head: head().textContent,
                            views: [pane.pane === pane, pane.annot.pane === pane] };
    h.runner.cancel(); await settle(300);
  }
  // the steps a reader opened belong to the conversation: another one shows its own closed
  {
    const conv = SCRIPT.concat([LAST, RESULT]).join('');
    const CONV0 = '/data/tmp/scholium/ATT1/conversations/claude-20260901-120000.jsonl';
    const h = harness({ logs: { [CONV1]: conv, [CONV0]: conv } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const fold = () => pane.list.children.at(-1).children.find(c => c.className === 'scholium-fold');
    fold().children[0].click(); await settle(5);
    const opened = fold().children.length;
    const first = pane.shownConv, second = first === 'claude-20260901-120000' ? 'claude-20261001-120000' : 'claude-20260901-120000';
    await h.runner.openConv(pane, { key: 'ATT1', id: second }); await settle(10);
    const other = [pane.shownConv === second, fold().children.length];
    fold().children[0].click(); await settle(5);
    await h.runner.showConversation(pane); await settle(10);
    // a run that is not there is left alone
    const nodes = pane.list.children.slice(), entries = pane.entries;
    h.runner.refreshRun(pane, 5);
    pane.entries = []; h.runner.refreshRun(pane, 0); pane.entries = entries;
    facts.foldPerConv = { opened, other, same: fold().children.length, untouched: pane.list.children.every((c, i) => c === nodes[i]) };
  }
  // another paper's run leaves a section's finished run as it was
  {
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), [SCRIPT[0], 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(300);
    await h.runner.annotate([h.item2]); await settle(200);
    const run = () => pane.list.children.at(-1);
    run().children.find(c => c.className === 'scholium-fold').children[0].click(); await settle(5);
    facts.otherPaperFold = { live: pane.live, running: h.runner.job && h.runner.job.key, prompt: run().children[0].textContent,
                             head: run().children.find(c => c.className === 'scholium-fold').children[0].textContent,
                             steps: run().children.find(c => c.className === 'scholium-fold').children[1].children.length };
    h.runner.cancel(); await settle(300);
  }
  // the message being written is the last thing of its run, when lines come and when another run begins; while the
  // run goes on its line says so, and the earlier runs are finished ones
  {
    const piece = text => ev({ type: 'stream_event', session_id: 'S1', parent_tool_use_id: null,
                               event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } } });
    const h = harness({ scripts: [[SCRIPT[0], said('先说一句'), piece('写到一半'), 'WAIT']],
                        logs: { [CONV1]: SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('') } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(300);
    await new Promise(r => setTimeout(r, 150));   // the draft is set a moment after its pieces
    const place = () => { const run = pane.list.children.at(-1); return [pane.list.children.length, run.children.at(-1) === pane.draft.node]; };
    const parts = pane.list.children.map(r => r.children.map(c => c.className));
    const thinking = pane.list.children[1].children[1].textContent;
    pane.list.children[0].children[0].children[0].click(); await settle(5);
    const earlier = pane.list.children[0].children[0].children[0].textContent;
    const first = place();
    pane.list.children[1].children.find(c => c.className === 'scholium-fold').children[0].click(); await settle(5);
    const clicked = place();   // the running run's steps opened: the message stays with it
    h.runner.appendEntries([{ kind: 'info', text: '一条提示' }]);
    const line = place();
    h.runner.appendEntries([{ kind: 'prompt', text: '插一句' }]);
    facts.draftPlace = { parts, thinking, earlier, first, clicked, line, run: place() };
    h.runner.cancel(); await settle(300);
  }
  // logs: one with run lines, timed by them; an earlier version's, split at the user's words
  {
    const at = Date.now() - 400000;
    const line = o => ev(Object.assign({ type: 'scholium' }, o));
    const timed = [line({ subtype: 'run', agent: 'claude', user: '这篇讲什么？', at }), line({ subtype: 'prompt', text: '这篇讲什么？' })]
      .concat(SCRIPT, [LAST, RESULT, line({ subtype: 'time', at: at + 377000 })]).join('');
    const h = harness({ logs: { [CONV1]: timed } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const run = p.pane().list.children.at(-1);
    const fold = run.children.find(c => c.className === 'scholium-fold');
    Object.defineProperty(p.pane().list, 'scrollHeight', { get: () => 1000, configurable: true });
    p.pane().list.scrollTop = 0;
    await h.runner.showConversation(p.pane());
    const scrollTop = p.pane().list.scrollTop;
    const failed = ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: '出错了', session_id: 'S1' });
    const legacy = [SCRIPT[0], failed, line({ subtype: 'prompt', text: '第二个问题' }), SCRIPT[0], said('回答 2'), said('补充'), RESULT,
                    line({ subtype: 'prompt', text: '第三个问题' }), said('回答 3'), RESULT].join('');
    const g = harness({ logs: { [CONV1]: legacy } });
    g.runner.start('x');
    const q = await g.pane(g.item1);
    await settle(40);                                 // the models are known: the default one is not named for a run without a model
    await g.runner.showConversation(q.pane());
    q.pane().list.children[1].children.at(-1).children[1].click();   // the copy button under the second run
    facts.logRuns = { runs: p.pane().list.children.length, head: fold.children[0].textContent, meta: run.children.at(-1).textContent, scrollTop,
                      clock: h.runner.clock(at + 377000), copied: g.log.copied, legacy: q.pane().list.children.map(r => r.children.map(c => [c.className, c.textContent])) };
  }
  // a run's lines before its first step or answer come above its line of steps, in their order and after the user's
  // words; the lines after its steps or answer come after them
  {
    const at = Date.now() - 400000;
    const line = o => ev(Object.assign({ type: 'scholium' }, o));
    const failed = ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: '出错了', session_id: 'S1' });
    const log = [line({ subtype: 'run', agent: 'claude', user: '批注这篇', at }), line({ subtype: 'prompt', text: '批注这篇' })]
      .concat(SCRIPT.slice(0, 4), [line({ subtype: 'end', outcome: 'failed', text: '中途失败' }),
              line({ subtype: 'run', agent: 'claude', user: null, at: at + 1000 }), line({ subtype: 'continue' })],
              SCRIPT.slice(0, 4), [LAST, RESULT, line({ subtype: 'time', at: at + 2000 }),
              line({ subtype: 'run', agent: 'claude', user: '第三个问题', at: at + 3000 }), line({ subtype: 'prompt', text: '第三个问题' }),
              SCRIPT[0], failed, line({ subtype: 'retry' }),
              line({ subtype: 'run', agent: 'claude', user: '第四个问题', at: at + 4000 }), line({ subtype: 'prompt', text: '第四个问题' }),
              SCRIPT[0], said('回答 4'), line({ subtype: 'end', outcome: 'failed', text: '后来失败' })]).join('');
    const h = harness({ logs: { [CONV1]: log } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    facts.leadLines = p.pane().list.children.map(r => r.children.map(c => c.className + (/info|final/.test(c.className) ? ': ' + c.textContent : '')));
  }
  // a run that ends without its conversation shown again is drawn as finished: a pause for the usage limit (and a line
  // that comes while nothing runs), the wait for a second try, a missing program; a run that starts draws the run
  // before it finished from the first moment
  {
    const ended = {};
    const runOf = view => view.list.children.at(-1);
    const headOf = view => { const f = runOf(view).children.find(c => c.className === 'scholium-fold'); return f ? [f.children[0].className, f.children[0].textContent] : null; };
    // the usage limit
    {
      const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
      h.runner.start('x');
      const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
      await settle(40);
      const other = p2.pane().annot.list.children[0];
      await h.runner.annotate([h.item1, h.item2]); await settle(300);
      ended.paused = [h.runner.job, !!h.runner.paused, headOf(p1.pane().annot), p2.pane().annot.list.children[0] === other];
      h.runner.appendEntries([{ kind: 'info', text: '一条提示' }]);
      ended.lineWhilePaused = headOf(p1.pane().annot);
      clearTimeout(h.runner.paused.timer);
    }
    // the wait for a second try
    {
      const ROUTING = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }),
                       turnDone({ status: 'failed', error: { message: 'workspace routing discovery timed out', codexErrorInfo: 'other' } })];
      const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [ROUTING] } });
      h.runner.NET_RETRY_MS = 60000;
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await h.runner.annotate([h.item1]); await settle(400);
      ended.retry = [h.runner.job, p.view('annotate').state, runOf(p.pane().annot).children.map(c => c.className)];
      h.runner.dequeue(['ATT1']); await settle(100);
    }
    // a missing program, in a conversation that has a run
    {
      const h = harness({ claudeExists: false, logs: { [CONV1]: SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('') } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(40);
      await h.runner.send(h.att1, '再问一句'); await settle(300);
      ended.noProgram = p.pane().list.children.map(r => r.children.map(c => c.className));
    }
    // the moment a run starts
    {
      const h = harness({ holdDirs: true, logs: { [CONV1]: SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('') } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(40);
      const queued = h.runner.send(h.att1, '再问一句');
      for (let i = 0; i < 2000 && !h.log.releaseDir; i++) await tick();
      ended.starting = [p.pane().list.children.map(r => r.children.map(c => c.className)), headOf(p.pane())];
      h.log.releaseDir(); await queued; await settle(300);
    }
    facts.ended = ended;
  }
  // the transcript keeps its latest lines: the runs drawn follow it when its first run goes, and the steps a reader
  // opened stay with their run
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane(), r = h.runner;
    const t0 = Date.now() - 100000;
    const simple = (at, words) => [{ kind: 'run', at }, { kind: 'prompt', text: words }, { kind: 'text', text: '答' + words }, { kind: 'time', at: at + 500, text: '' }];
    const show = entries => {
      r.transcript = entries; r.transcriptKey = 'ATT1'; r.transcriptKind = 'chat';
      Object.assign(pane, { shownKey: 'ATT1', live: true, foldOpen: new Map() });
      r.renderTranscript(pane, r.transcript, false);
    };
    const prompts = () => pane.list.children.map(n => n.children[0].textContent);
    // the first run goes and the steps opened in the second stay open
    const B = [{ kind: 'run', at: t0 + 2000 }, { kind: 'prompt', text: 'B' }, { kind: 'text', text: '先看' }, { kind: 'tool', name: 'Read', text: 'Read(x.txt)' },
               { kind: 'result', text: 'ok' }, { kind: 'text', text: '答B' }, { kind: 'time', at: t0 + 3000, text: '' }];
    show(simple(t0, 'A').concat(B));
    pane.list.children[1].children.find(c => c.className === 'scholium-fold').children[0].click();
    r.MAX_ENTRIES = B.length + 1;
    r.appendEntries([{ kind: 'info', text: '一条提示' }]);
    const kept = [prompts(), pane.list.children[0].children.find(c => c.className === 'scholium-fold').children.length];
    // the first run goes in the call that brings a run: as many runs as before, but not the same ones
    show(simple(t0, 'A').concat(simple(t0 + 2000, 'B')));
    r.MAX_ENTRIES = 5;
    r.appendEntries([{ kind: 'prompt', text: 'C' }]);
    facts.trimmed = { kept, shifted: prompts() };
    r.MAX_ENTRIES = 3000;
  }
  // the words of a run's line, in both languages
  {
    const hr = harness(), r = hr.runner;
    const step = (name, text) => ({ kind: 'tool', name, text });
    const foldView = hh => ({ doc: hh.paneDoc, foldOpen: new Map(), kind: 'chat' });
    r.models.codex = [{ value: '', label: 'Codex 默认' }, { value: 'gpt-6-luna', label: 'GPT-6-Luna' }];
    r.job = { started: Date.now() - 12000 };   // the live line's time is the running paper's
    facts.words = {
      live: [step('Read', 'Read(D:/x/sentences.txt)'), step('Bash', 'Bash(python scholium.py extract)'), undefined]
        .map(st => r.foldNode(foldView(hr), { start: Date.now() - 12000, end: 0, steps: st ? [st] : [] }, 0, true).children[0].textContent),
      durations: [0, 59400, 377000, 3725000].map(ms => r.durationWords(ms)),
      worked: [r.workedText({ start: 0, end: 5 }), r.workedText({ start: 1000, end: 378000 }), r.workedText({ start: 5000, end: 0 })],
      labels: [r.modelLabel('Claude Code · claude-opus-5-5'), r.modelLabel('claude-haiku-4-5-20251001'), r.modelLabel('Codex · gpt-6-luna'),
               r.modelLabel('Codex · gpt-x')],
      runLines: [r.entries({ type: 'scholium', subtype: 'run', agent: 'claude', at: 5 }), r.entries({ type: 'scholium', subtype: 'run', agent: 'claude' })],
    };
    r.job = null;
    const he = harness({ locale: 'en-US' }), e = he.runner;
    e.job = { started: Date.now() - 12000 };
    facts.words.english = [e.foldNode(foldView(he), { start: Date.now() - 12000, end: 0, steps: [step('Read', 'Read(a/b.txt)')] }, 0, true).children[0].textContent,
                           e.workedText({ start: 1000, end: 378000 }), e.workedText({ start: 0, end: 0 }),
                           ...[59400, 377000, 3725000].map(ms => e.durationWords(ms))];
    e.job = null;
  }
  // History is a layer of this PDF's conversations; a row opens one and closes the layer; an empty chat offers questions
  {
    const reply = n => [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q' + n }), said('回答 ' + n),
                        ev({ type: 'result', subtype: 'success', is_error: false, result: '回答 ' + n, session_id: 'Q' + n })];
    const h = harness({ scripts: [reply(1), reply(2)], secondPdf: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const keys = pane.keys.slice();
    const starters = pane.saved.children.filter(c => c.className === 'scholium-saved-item').map(c => c.children[0].textContent);
    pane.saved.children[0].children[0].click(); await settle(300);       // the first question
    const asked = h.log.stdin[0].includes('这篇论文要解决什么问题？');
    pane.newChat.click(); await settle(50);
    pane.input.type('第二个问题'); pane.send.click(); await settle(300);
    pane.historyButton.click(); await settle(50);
    const rows = pane.popover.node.children.filter(r => r.className.startsWith('scholium-history-row')).map(r => r.children[0].children[0].textContent);
    pane.popover.node.children.find(r => r.className.startsWith('scholium-history-row') && r.children[0].textContent.startsWith('这篇论文要解决')).children[0].click();
    await settle(100);
    facts.history = { keys, starters, asked, rows, after: [pane.popover, pane.shownConv && pane.shownConv.startsWith('chat-')],
                      shown: pane.list.children.at(-1).children.find(c => c.className === 'scholium-entry text').textContent };
  }
  // the layer toggles, is placed again once its rows are in, and goes when the paper runs; English starters; a group library has none
  {
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' }), said('回答'),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: '回答', session_id: 'Q1' })]], locale: 'en-US' });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const savedItems = pane.saved.children.filter(c => c.className === 'scholium-saved-item');
    const english = [savedItems.map(c => c.children[0].textContent), savedItems.map(c => c.children[0].title)];
    let placed = 0;
    const place = h.runner.placePopover;
    h.runner.placePopover = function (...a) { placed++; return place.apply(this, a); };
    pane.historyButton.click(); await settle(50);
    const opened = [pane.popover && pane.popover.name, placed >= 2, pane.popover.node.children.map(c => c.className)];
    pane.historyButton.click(); await settle(10);
    const toggled = pane.popover;
    pane.historyButton.click(); pane.more.click(); await settle(50);   // another layer opens before the rows are in
    const other = [pane.popover.name, pane.popover.node.children.map(c => c.textContent).length > 0 && !pane.popover.node.children.some(c => c.className.startsWith('scholium-history'))];
    pane.historyButton.click(); await settle(50);
    pane.input.type('hello'); pane.send.click(); await settle(30);
    const busy = pane.popover;
    await settle(200);
    const g = harness();
    g.item1.libraryID = 2;
    g.runner.start('x');
    const q = await g.pane(g.item1);
    await settle(40);
    facts.historyLayer = { english, opened, toggled, other, busy, group: q.pane().list.children.map(c => c.textContent), groupSaved: q.pane().saved.hidden };
  }
  // a failed question carries a Retry that runs the same words again in the same conversation, without a second prompt line;
  // the failure line is in the run's lead (it failed before any step) or among its other lines (after a step)
  for (const [name, before] of [['retry', []], ['retryAfterStep', [tool('Read', { file_path: 'x.txt' }, 'T1'), answer('ok', false, 'T1')]]]) {
    const failed = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }), ...before,
                    ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 500 internal', session_id: 'F1' }), 'EXIT:1'];
    const ok = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }), said('好了'),
                ev({ type: 'result', subtype: 'success', is_error: false, result: '好了', session_id: 'F1' })];
    const h = harness({ scripts: before.length ? [failed, ok] : [failed, failed, ok] });   // the automatic second try fails too (a run with steps gets none)
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('为什么要用这个核？'); pane.send.click();
    await settle(400); await new Promise(r => setTimeout(r, 120)); await settle(400);
    const run = pane.list.children.at(-1);
    const errorNode = run.children.find(c => c.className.includes('final'));
    const retry = errorNode && errorNode.children.find(c => c.className.includes('retry'));
    const label = labelOf(retry);
    const inLead = errorNode && run.children.indexOf(errorNode) < (run.children.findIndex(c => c.className === 'scholium-fold') + 1 || 99);
    retry.click(); await settle(400);
    const lines = convLines(h);
    facts[name] = { label, inLead, third: h.log.stdin.at(-1), prompts: lines.filter(l => l.subtype === 'prompt').length,
                    lastRun: lines.filter(l => l.subtype === 'run').at(-1).user, answer: pane.list.children.at(-1).children.some(c => c.textContent === '好了'),
                    buttons: pane.list.children.reduce((n, r) => n + r.children.filter(c => c.children.some(k => k.className.includes('retry'))).length, 0),
                    english: h.runner.text('retry') };
  }
  {
    const h = harness({ locale: 'en-US' });
    facts.retryEnglish = h.runner.text('retry');
  }
  // no Retry while the paper is busy (the pending second try); one once it is idle again
  {
    const failed = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }),
                    ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 500 internal', session_id: 'F1' }), 'EXIT:1'];
    const h = harness({ scripts: [failed, failed] });
    h.runner.NET_RETRY_MS = 400;
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const count = () => pane.list.children.reduce((n, r) => n + r.children.filter(c => c.children.some(k => k.className.includes('retry'))).length, 0);
    pane.input.type('问'); pane.send.click();
    await settle(150);
    const pending = [!!h.runner.queue.length, count()];
    await new Promise(r => setTimeout(r, 500)); await settle(400);
    facts.retryBusy = { pending, after: [!!h.runner.queue.length, !!h.runner.job, count()] };
    // busy: retryFromView leaves the conversation alone
    const g = harness({ scripts: [failed, failed] });
    g.runner.NET_RETRY_MS = 60000;
    g.runner.start('x');
    const q = await g.pane(g.item1);
    await settle(40);
    const gp = q.pane();
    const gcount = () => gp.list.children.reduce((n, r) => n + r.children.filter(c => c.children.some(k => k.className.includes('retry'))).length, 0);
    gp.input.type('问'); gp.send.click();
    await settle(200);
    const gpending = [!!g.runner.queue.length, gcount()];
    const conv = gp.shownConv;
    await g.runner.chooseConv('ATT1', null);
    await g.runner.retryFromView(gp); await settle(50);
    const untouched = (await g.runner.currentConv('ATT1')) === null && g.log.stdin.length;
    g.runner.dequeue(['ATT1']);
    const d = harness({ scripts: [failed, failed] });
    d.runner.NET_RETRY_MS = 60000;
    d.runner.start('x');
    const dq = await d.pane(d.item1);
    await settle(40);
    const dp = dq.pane();
    dp.input.type('问'); dp.send.click();
    await settle(200);
    const dpending = dp.list.children.at(-1).children.filter(c => c.children.some(k => k.className.includes('retry'))).length;
    d.runner.dequeue(['ATT1']); await settle(200);
    facts.retryBusy.cancelled = [gpending, !!untouched, dpending, dp.list.children.at(-1).children.filter(c => c.children.some(k => k.className.includes('retry'))).length,
                                 dp.list.children.at(-1).children.map(c => c.className)];
    // a pane opened later shows a failed last run with its button
    facts.retryBusy.later = (await h.pane(h.item1)).pane().list.children.reduce((n, r) => n + r.children.filter(c => c.children.some(k => k.className.includes('retry'))).length, 0);
    // the usage limit
    const l = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })].concat(LIMIT_HIT)] });
    l.runner.start('x');
    const lp = await l.pane(l.item1);
    await settle(40);
    const lpane = lp.pane();
    lpane.input.type('问'); lpane.send.click();
    await settle(300);
    facts.retryBusy.limit = [!!l.runner.paused, lpane.list.children.reduce((n, r) => n + r.children.filter(c => c.children.some(k => k.className.includes('retry'))).length, 0),
                             0];
    clearTimeout(l.runner.paused && l.runner.paused.timer);
  }
  // the annotation view draws the chat's Retry for words to its session only; the chat's retry runs the agent chosen; a
  // retry without a session
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const view = p.pane().annot;
    view.runCount = 1;
    const run = { start: 1, end: 2, prompt: null, lead: [], steps: [], answer: [], other: [{ kind: 'final', error: true, text: 'x' }], model: null };
    const hasRetry = n => n.children.some(c => c.children.some(k => k.className.includes('retry')));
    const chatView = p.pane();
    chatView.runCount = 1;
    facts.annotRetry = { annot: hasRetry(h.runner.renderRun(view, run, 0, false)), kind: view.kind, hasPane: !!view.pane, chat: hasRetry(h.runner.renderRun(chatView, run, 0, false)),
                         words: hasRetry(h.runner.renderRun(view, Object.assign({}, run, { turn: { kind: 'prompt', text: '改短' } }), 0, false)) };
  }
  {
    const failed = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }),
                    ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 500 internal', session_id: 'F1' }), 'EXIT:1'];
    const ok = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }), said('好了'),
                ev({ type: 'result', subtype: 'success', is_error: false, result: '好了', session_id: 'F1' })];
    const h = harness({ scripts: [failed, failed, ok] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问'); pane.send.click();
    await settle(400); await new Promise(r => setTimeout(r, 120)); await settle(400);
    const conv = pane.shownConv, codexBefore = h.log.codexCalls.length, claudeBefore = h.log.stdin.length;
    h.store.set('extensions.scholium.agent', 'codex');   // the chosen agent changes; the pane keeps showing the conversation
    await h.runner.retryFromView(pane); await settle(400);
    const after = await h.runner.readLog('ATT1', conv);
    facts.retryAgent = { claudeRan: h.log.stdin.length - claudeBefore, codexCalls: h.log.codexCalls.length - codexBefore, shown: pane.shownConv === conv,
                         current: await h.runner.currentConv('ATT1') === conv, turns: after.turns.map(t => [t.user, t.agent, !!t.reply]) };
  }
  {
    // (a) the first question fails before any session; (b) a later turn fails without one: the history stops before the retried turn
    const bare = (n) => [ev({ type: 'assistant', message: { content: [{ type: 'text', text: n }] } }), ev({ type: 'result', subtype: 'success', is_error: false, result: n })];
    const boom = ['STDERR:boom', 'EXIT:1'];
    const out = {};
    for (const [name, scripts, turns] of [['first', [boom, boom, bare('好了')], ['问一']], ['later', [bare('答一'), boom, boom, bare('好了')], ['问一', '问二']]]) {
      const h = harness({ scripts });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(40);
      const pane = p.pane();
      for (const t of turns) {
        pane.input.type(t); pane.send.click();
        await settle(400); await new Promise(r => setTimeout(r, 120)); await settle(400);
      }
      const before = h.log.stdin.length;
      const log = await h.runner.readLog('ATT1', pane.shownConv);
      await h.runner.retryFromView(pane); await settle(400);
      out[name] = { session: own(log, 'claude').session, turns: log.turns.length, ran: h.log.stdin.length - before, prompt: h.log.stdin.at(-1) };
    }
    facts.retryNoSession = out;
  }
  // send with retry keeps the conversation given, whichever is the paper's current one
  {
    const failed = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }),
                    ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 500 internal', session_id: 'F1' }), 'EXIT:1'];
    const ok = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }), said('好了'),
                ev({ type: 'result', subtype: 'success', is_error: false, result: '好了', session_id: 'F1' })];
    const h = harness({ scripts: [failed, failed, ok] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问'); pane.send.click();
    await settle(400); await new Promise(r => setTimeout(r, 120)); await settle(400);
    const old = pane.shownConv;
    await h.runner.chooseConv('ATT1', null);
    await h.runner.send(h.item1, '问', { retry: true, conv: old }); await settle(400);
    const log = await h.runner.readLog('ATT1', old);
    facts.sendRetry = { answered: log.entries.some(e => e.text === '好了'), prompts: log.turns.length, current: await h.runner.currentConv('ATT1') };
  }
  // the retry runs in the conversation shown, though the paper's current one is another; a run going on carries none
  {
    const failed = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }), tool('Read', { file_path: 'x.txt' }, 'T1'), answer('ok', false, 'T1'),
                    ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 500 internal', session_id: 'F1' }), 'EXIT:1'];
    const ok = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }), said('好了'),
                ev({ type: 'result', subtype: 'success', is_error: false, result: '好了', session_id: 'F1' })];
    const h = harness({ scripts: [failed, ok] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('为什么要用这个核？'); pane.send.click();
    await settle(400);
    const old = pane.shownConv;
    await h.runner.chooseConv('ATT1', null);   // the paper's current conversation is another (a new one); the pane still shows this one
    const before = [pane.shownConv === old];
    const run = pane.list.children.at(-1);
    const retry = run.children.flatMap(c => c.children).find(c => c.className.includes('retry'));
    retry.click(); await settle(400);
    pane.runCount = 1;
    const live = h.runner.renderRun(pane, { start: 1, end: 2, prompt: null, lead: [], steps: [], answer: [], other: [{ kind: 'final', error: true, text: 'x' }], model: null }, 0, true);
    facts.retryElsewhere = { shown: before[0], answer: (await h.runner.readLog('ATT1', old)).entries.some(e => e.text === '好了'),
                             log: (await h.runner.readLog('ATT1', old)).turns.length, stays: pane.shownConv === old && (await h.runner.currentConv('ATT1')) === old, liveButton: live.children.some(c => c.children.some(k => k.className.includes('retry'))) };
  }
  // the settings page asks the plugin for the programs it finds by itself, whatever is set there; gone once it stops
  {
    const h = harness({ prefs: { 'extensions.scholium.claudePath': '/custom/claude.exe',
                                 'extensions.scholium.codexPath': '/custom/codex.exe' } });
    h.runner.start('x');
    const api = h.zotero.Scholium;
    facts.found = { api: !!api, claude: api && await api.found('claude'), codex: api && await api.found('codex') };
    h.runner.stop();
    facts.found.after = 'Scholium' in h.zotero;
    const none = harness({ claudeExists: false, codex: { versions: {} } });
    none.runner.start('x');
    facts.found.none = [await none.zotero.Scholium.found('claude'), await none.zotero.Scholium.found('codex')];
    none.runner.stop();
  }
  // the annotation tab's introduction: its title and one line
  for (const locale of ['zh-CN', 'en-US']) {
    const h = harness({ locale });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(20);
    (facts.intro = facts.intro || {})[locale] = pane.annot.list.children[0].children.map(c => c.textContent);
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_settings_page_is_registered_and_opened(facts):
    s = facts["settingsPage"]
    assert s["src"] == "jar:file:///x/scholium.xpi!/settings.xhtml" and s["scripts"] == ["jar:file:///x/scholium.xpi!/settings.js"]
    assert s["label"] == "Scholium" and s["pluginID"] == "scholium@zotero-scholium"
    assert s["multiline"] == "cmdIfMultiline" and s["afterStop"] is None
    assert s["id"] == "scholium-pane-id" and s["opened"] == ["scholium-pane-id"]
    assert s["defaults"] == ["cmdAlways", "queue", True] and s["set"] == ["enter", "steer", False] and s["bogus"] == "cmdAlways"
    assert "Zotero 设置" in s["noClaude"] and "配置编辑器" not in s["noClaude"]
    assert "Zotero 设置" in s["noCodex"] and "配置编辑器" not in s["noCodex"]
    assert s["settingsOpen"] == "设置…"
    assert facts["english"] == ["Claude Code (claude) was not found. Set its program in Zotero Settings → Scholium.",
                                "Codex (codex) was not found. Set its program in Zotero Settings → Scholium.", "Settings…"]
    assert facts["englishCard"] == "highlights (2\u00a0core)", "the count stays with its word"


def test_the_english_card_words_follow_their_numbers(facts):
    assert facts["englishCardWords"] == [["1highlight (1\u00a0core)", "1margin note", "1sticky note", "1reading note"],
                                         ["2highlights (1\u00a0core)", "2margin notes", "2sticky notes", "2reading notes"]]
    assert facts["chineseCardWords"] == [["页边批注", "便签", "阅读笔记", "高亮（核心\u00a01）"]] * 2


def test_the_program_picker_takes_any_file():
    """The file picker of an agent's program shows every file: the claude and codex executables are no app bundles on
    macOS."""
    script = r'''
const vm = require('node:vm');
const fs = require('node:fs');
const filters = [];
class FilePicker {
  init() {} appendFilters(mask) { filters.push(mask); } async show() { return this.returnCancel; }
}
Object.assign(FilePicker.prototype, { filterAll: 0x001, filterApps: 0x040, modeOpen: 0, returnOK: 0, returnCancel: 1 });
const handlers = {};
// zotero runs the script first and parses the markup after it: the elements exist only when `load` reaches the root
let present = false, listener = null;
const document = {
  getElementById: id => (present ? { addEventListener: (t, f) => { handlers[id] = f; } } : null),
  addEventListener: (t, f, capture) => { if (t === 'load' && capture) listener = f; },
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  window: {}, document, Zotero: { Prefs: { set() {} } },
  ChromeUtils: { importESModule: () => ({ FilePicker }) },
});
(async () => {
  const before = Object.keys(handlers);
  present = true;
  const other = { classList: { contains: c => c === 'other' } };
  const root = { classList: { contains: c => c === 'scholium-settings' } };
  listener({ target: other });
  const afterOther = Object.keys(handlers);
  listener({ target: root });
  listener({ target: root });   // a second load wires nothing again
  for (const id of Object.keys(handlers)) { handlers[id](); await new Promise(r => setTimeout(r, 5)); }
  process.stdout.write(JSON.stringify({ before, afterOther, ids: Object.keys(handlers), filters }));
})();
'''
    out = subprocess.run([NODE, "-e", script, str(PLUGIN / "settings.js")], capture_output=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["before"] == [] and got["afterOther"] == [], "nothing is wired before the pane's markup is loaded"
    assert got["ids"] == ["scholium-claude-browse", "scholium-codex-browse"]
    assert got["filters"] == [0x001, 0x001], "all files, not only applications"


def test_the_readme_says_how_an_interrupted_run_goes_on():
    text = " ".join((PLUGIN.parent / "README.md").read_text(encoding="utf8").split())
    assert "**Send** continues it" not in text
    assert ("shows the run as interrupted; ↻ (**Retry**) on a run that ended before its answer runs it again, and a new message "
            "continues the conversation.") in text


def test_the_settings_page_binds_every_preference():
    ns = {"x": "http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul", "h": "http://www.w3.org/1999/xhtml"}
    src = (PLUGIN / "settings.xhtml").read_text(encoding="utf8")
    root = ET.fromstring("<root xmlns='%s' xmlns:html='%s'>%s</root>" % (ns["x"], ns["h"], src))
    prefs = {el.get("preference") for el in root.iter() if el.get("preference")}
    assert prefs == {"extensions.scholium." + p for p in ("sendShortcut", "followUpMode", "contextRing", "claudePath", "codexPath")}
    ids = {el.get("data-l10n-id") for el in root.iter() if el.get("data-l10n-id")}
    for locale in ("en-US", "zh-CN"):
        ftl = (PLUGIN / "locale" / locale / "scholium.ftl").read_text(encoding="utf8")
        defined = set(re.findall(r"^([a-z][\w-]*)\s*=", ftl, re.M))
        assert ids <= defined, (locale, ids - defined)
    defaults = (PLUGIN / "prefs.js").read_text(encoding="utf8")
    for p, v in (("sendShortcut", '"cmdAlways"'), ("followUpMode", '"queue"'), ("contextRing", "true"),
                 ("claudePath", '""'), ("codexPath", '""'), ("savedPrompts", '""')):
        assert f'pref("extensions.scholium.{p}", {v});' in defaults


def ftl_messages(locale):
    """{id: (value or None, {attribute names})} of the plugin's ftl of a locale."""
    out, last = {}, None
    for line in (PLUGIN / "locale" / locale / "scholium.ftl").read_text(encoding="utf8").splitlines():
        m = re.match(r"^([a-z][\w-]*)\s*=\s*(.*)$", line)
        if m:
            last = m.group(1)
            out[last] = (m.group(2) or None, set())
            continue
        a = re.match(r"^\s+\.([\w-]+)\s*=", line)
        if a and last:
            out[last][1].add(a.group(1))
    return out


def test_the_settings_page_controls_show_their_words():
    ns = {"x": "http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul", "h": "http://www.w3.org/1999/xhtml"}
    src = (PLUGIN / "settings.xhtml").read_text(encoding="utf8")
    root = ET.fromstring("<root xmlns='%s' xmlns:html='%s'>%s</root>" % (ns["x"], ns["h"], src))
    controls = {"{%s}%s" % (ns["x"], t) for t in ("menuitem", "radio", "checkbox", "button")}
    labelled = [el.get("data-l10n-id") for el in root.iter() if el.tag in controls]
    assert len(labelled) == 9
    picker = re.findall(r'"(scholium-settings-[a-z-]+)"', (PLUGIN / "settings.js").read_text(encoding="utf8"))
    assert picker == ["scholium-settings-claude", "scholium-settings-codex", "scholium-settings-not-found"]
    for locale in ("en-US", "zh-CN"):
        msgs = ftl_messages(locale)
        for i in labelled:
            assert msgs[i][0] is None and "label" in msgs[i][1], (locale, i, "a menu item, radio, checkbox or button shows its .label")
        for i in picker:
            assert msgs[i][0], (locale, i, "the file picker's title is a message's value")
    assert not [el for el in root.iter() if el.tag == "{%s}h2" % ns["h"]], "the page's heading is Zotero's"
    inputs = [el for el in root.iter() if el.tag == "{%s}input" % ns["h"]]
    assert [el.get("id") for el in inputs] == ["scholium-claude-path", "scholium-codex-path"]
    assert len(inputs) == 2 and all("flex: 1" in (el.get("style") or "") for el in inputs), "a path box takes the row"


def test_startup_gives_the_runner_its_root_before_it_starts():
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({
  Zotero: { initializationPromise: Promise.resolve(), debug() {}, DataDirectory: { dir: 'D' }, Utilities: { randomString: () => 'x'.repeat(40) },
            Server: { Endpoints: {} } },
  PathUtils: { join: (...p) => p.join('/') }, IOUtils: { exists: async () => false, writeUTF8: async () => {} },
  setTimeout: () => 0, clearTimeout() {},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const seen = [];
context.ScholiumRunner.start = () => { seen.push(context.ScholiumRunner.rootURI); };
context.startup({ id: 'x', version: '0.1.9', rootURI: 'jar:file:///x.xpi!/' }, 5)
  .then(() => process.stdout.write(JSON.stringify(seen)));
"""
    out = json.loads(subprocess.run([NODE, "-e", script, str(BOOTSTRAP)], text=True, capture_output=True, check=True, timeout=15).stdout)
    assert out == ["jar:file:///x.xpi!/"]


def test_the_release_workflow_zips_every_top_level_entry_of_the_plugin():
    workflow = (PLUGIN.parent.parent / ".github" / "workflows" / "release.yml").read_text(encoding="utf8")
    line = next(l for l in workflow.splitlines() if l.strip().startswith("zip ") and "scholium.xpi" in l)
    zipped = set(line.split("scholium.xpi", 1)[1].split())
    assert set(os.listdir(PLUGIN)) <= zipped, set(os.listdir(PLUGIN)) - zipped


def test_the_annotation_tab_introduction_is_one_line(facts):
    assert facts["intro"]["zh-CN"] == ["还没有批注这篇", "高亮重点句（外文论文附译文），加页边批注和阅读笔记。"]
    assert facts["intro"]["en-US"][1] == "Highlights key sentences (translated when the paper is in another language), adds margin notes and a reading note."


def test_the_chip_shows_the_default_label_when_no_model_is_saved(facts):
    d = facts["chip"]["codexDefault"]
    assert d["name"] and d["name"].startswith("Codex")
    assert d["tip"].startswith("Codex")


def test_the_settings_chip_and_its_layer(facts):
    c = facts["chip"]
    assert c["chip"] == "Opus 5.5medium▾"
    assert c["open"] == {"name": "settings", "selects": True, "note": True}
    assert c["afterDropdown"] == "settings", "a choice in a select's dropdown keeps the layer"
    assert c["afterOutside"] is None and c["afterEsc"] is None
    assert c["menu"] == ["打开日志", "个人配置 ↗", "", "设置…"] and c["oneAtATime"] == "settings"
    assert c["after"].startswith("Fable") and c["afterParts"] == ["scholium-chip-name", "scholium-chip-tail"]
    assert c["secondParts"] == ["scholium-chip-name", "scholium-chip-tail"]
    # the model is cut first; the effort, small and grey, and ▾ stay
    assert c["parts"] == [["scholium-chip-name", "Opus 5.5"], ["scholium-chip-tail", "medium▾"]]
    assert c["noEffort"] == [["scholium-chip-name", "Haiku 4.5"], ["scholium-chip-tail", "▾"]]
    assert c["tip"] == "Claude Code · Opus 5.5 · medium"
    assert c["done"] == ["完成 · 21s · 4 轮 · 62k tokens", "完成 · 21s · 4 轮 · 62k tokens\n输入 3 · 输出 640"]
    assert c["none"] == [True, ""]
    rules = css_rules()
    assert "display: flex" in rules[".scholium-chip"] and "align-items: center" in rules[".scholium-chip"]
    assert "flex: none" in rules[".scholium-chip-tail"]
    assert "color: var(--fill-secondary)" in rules[".scholium-chip-effort"]
    name = rules[".scholium-chip-name"]
    assert "min-width: 0" in name and "overflow: hidden" in name and "text-overflow: ellipsis" in name


def test_the_layer_is_fixed_in_the_document_and_leaves_nothing_behind(facts):
    f = facts["layer"]
    assert f["parent"] is True
    assert f["below"] == ["144px", ""]                    # the anchor is in the upper half: below it
    assert f["maxWidth"] == "300px", "a layer is no wider than the pane"
    assert f["above"][0] == "" and f["above"][1].endswith("px") and f["above"][2] == "50px"   # the lower half: above it, kept within the pane
    assert f["listening"] == [1, 1]
    assert f["afterScroll"] == [None, False, 0, 0]
    assert f["afterResize"] == [None, False]
    assert f["afterRender"] == [None, False, 1, 1, True]  # the old pane's listener went with it
    assert f["afterDestroy"] == [False, 0, 0]


def test_the_section_never_widens_the_item_pane():
    rules = css_rules()
    assert "contain: inline-size" in rules[".scholium-pane"]
    state = rules[".scholium-line .scholium-state"]
    for part in ("min-width: 0", "white-space: nowrap", "overflow: hidden", "text-overflow: ellipsis"):
        assert part in state, part
    assert "display: block" in rules[".scholium-state"], "an ellipsis needs the state's text in a block"
    assert "display: inline-block" in rules[".scholium-state::before"]


def test_the_empty_states_and_the_card_labels_sit_as_drawn():
    rules = css_rules()
    log = rules[".scholium-log"]
    assert "display: flex" in log and "flex-direction: column" in log, "the auto margins of the introduction need a column"
    assert "margin: auto 0" in rules[".scholium-annot-intro"]
    assert "word-break: keep-all" in rules[".scholium-card-nums span"]


def test_the_menu_items_close_the_layer_and_act(facts):
    f = facts["menuItems"]
    assert f["logDisabled"] is True                       # no log yet
    assert f["settings"] == [None, 1]
    assert f["toggled"] is None
    assert f["profile"] == [None, True]


def test_a_click_inside_keeps_the_layer_and_the_chip_toggles_it(facts):
    f = facts["menuItems"]
    assert f["inside"] == "settings" and f["escInLayer"] is None and f["chipToggled"] is None and f["layers"] == 1


def test_the_two_tabs(facts):
    t = facts["tabs"]
    assert t["first"] == {"tab": "chat", "chatShown": True, "annotShown": False}
    assert t["second"]["tab"] == "annotate" and t["second"]["chatShown"] is False and t["second"]["annotShown"] is True
    assert "on" in t["second"]["selected"][1] and "on" not in t["second"]["selected"][0]
    assert t["chatState"] == "" and re.fullmatch(r"正在处理 · 已用 \d+s", t["chatTitle"]), "a question's line is its dot; the tooltip has the time"
    assert t["annotState"] is None, "the annotation tab does not show the chat's run"
    assert t["chatDot"] is True and t["annotDot"] is False
    assert t["dotHere"] is True, "the tab being shown carries no dot"


def test_a_run_goes_to_the_view_of_its_kind(facts):
    f = facts["kindRouting"]
    assert f["kind"] == "annotate" and f["introBefore"] is True
    assert f["chatKept"] == [False, True], "showing the conversation leaves the annotation run in its tab"
    assert f["chatTab"]["entries"] == f["chatBefore"] and f["chatAfter"] == f["chatBefore"]
    assert f["chatTab"]["state"] is None, "the chat tab does not show the annotation run"
    assert f["chatTab"]["annotDot"] is True and f["chatTab"]["chatDot"] is False
    assert f["annotLog"] is False, "the annotation tab's log is its own run's"
    a = f["annotTab"]
    assert a["entries"] > 0 and a["live"] is True and a["running"] is True and a["intro"] is False
    assert a["annotDot"] is False and a["chatDot"] is False
    assert a["newChat"] is True and a["history"] is True


def test_a_waiting_job_of_the_other_kind_shows_the_dot(facts):
    f = facts["queuedDot"]
    assert f["views"] == [True, True, 2]
    assert f["states"] == [None, "排队中，前面还有 1 篇"], "a waiting job shows its state on its own tab"
    assert f["chatBusy"] is False and f["annotBusy"] is True and f["dot"] is True   # another paper runs; this one waits


def test_the_annotation_tab_and_its_menu(facts):
    f = facts["annotTab"]
    assert f["row"] == {"intro": True, "go": False, "goText": "批注这篇", "send": True, "annotList": False,
                    "placeholder": "附加要求（可不填），例如：只批注第 3–5 页", "old": [True] * 5}
    assert f["menu"] == [["个人配置 ↗", False], ["打开日志", True], ["删除批注", False], ["", False], ["设置…", False]]
    assert f["chatRow"] == [True, False] and f["lists"] == [True, True]
    assert f["logClosed"] is None and f["extra"] is True
    assert f["busyMenu"][2] is True and f["tabsKeepBusyMenu"] == "annotate"


def test_the_draft_of_an_annotation_run_is_in_the_annotation_tab(facts):
    f = facts["kindDraft"]
    assert f["annot"] is True and f["chat"] is False and f["inAnnot"] and f["inChat"] is False


def test_the_state_line_and_the_layer_follow_the_tab(facts):
    f = facts["stateByTab"]
    assert f["chat"] and f["chat"].startswith("完成") and f["annot"] is None
    assert f["layer"] is None


def test_the_round_button_and_the_send_shortcut(facts):
    b = facts["button"]
    assert b["idle"] == ["↑", True, "发送"] and b["typed"] == ["↑", False, "发送"]
    assert b["keys"]["always"] == [None, "send", "invert"]
    assert b["keys"]["enter"] == ["send", None, "invert"]
    assert b["keys"]["multiline"] == ["send", None, "send"]
    assert b["running"] == ["■", False, "停止"] and b["runningTyped"] == ["↑", False, "排队"]
    assert b["keys"]["composing"] is None and b["keys"]["other"] is None
    assert b["hints"] == {"enter": "Enter 发送 · Shift+Enter 换行", "cmdIfMultiline": "Enter 发送 · 多行时 Ctrl+Enter", "cmdAlways": "Ctrl+Enter 发送"}
    assert b["pressed"] == [True, True, False] and b["sends"] == [False, True]
    assert b["english"] == ["Send", "Stop", "Queue", "Steer", "Press Esc again to stop", "Enter to send · Shift+Enter for a new line", "Context window:",
                            "Context window", "Input", "Cache", "Output", "Enter to send · Ctrl+Enter for several lines", "1k / 2k (50%)", "3k tokens"]
    # queued unless the setting says steer and the agent can steer; the key inverts the setting for one message
    assert b["follow"] == [["queue", "queue"], ["queue", "queue"], ["steer", "queue"], ["queue", "steer"]]
    assert b["steerTitle"] == "引导"
    assert b["liveRing"] == "上下文窗口：\n30% 已用（剩余 70%）\n300k / 1,000k tokens"
    assert b["layerFirst"] == [None, 0, "Ctrl+Enter 发送"], "Esc closes the layer and nothing else"
    assert b["followAnnot"] == ["queue", "queue"] and b["followElsewhere"] == ["queue", "queue"]
    assert b["keptOther"] is True
    assert b["armed"] == ["再按一次 Esc 停止", True, True], "the first Esc only asks"
    assert b["lapsed"] == "Ctrl+Enter 发送", "and the question lapses"
    assert b["late"] == ["再按一次 Esc 停止", True], "a second Esc after the wait only asks again"
    assert b["stopped"] is True and b["hintAfter"] == "Ctrl+Enter 发送"
    assert b["idleEsc"] == [False, False], "with nothing running Esc is not taken"


def test_the_context_ring(facts):
    r = facts["ring"]
    assert r["half"]["shown"] and r["half"]["cls"] == "scholium-ring" and r["half"]["share"] == "55%"
    assert r["half"]["title"] == "上下文窗口：\n55% 已用（剩余 45%）\n550k / 1,000k tokens"
    assert r["parts"] == {"names": ["scholium-context-head", "scholium-context-bar", "scholium-context-legend", "scholium-context-compact"], "head": "上下文窗口550k / 1,000k（55%）",
                          "segs": [["seg input", "6.00%"], ["seg cache", "44.00%"], ["seg output", "5.00%"]], "legend": ["输入60k", "缓存440k", "输出50k"]}
    # each label and number is a box of its own row
    assert r["boxes"] == {"head": [["span", "上下文窗口"], ["span", "550k / 1,000k（55%）"]],
                          "legend": [[["span", "输入"], ["span", "60k"]], [["span", "缓存"], ["span", "440k"]], [["span", "输出"], ["span", "50k"]]]}
    assert r["toggled"] is None, "the ring toggles its layer"
    assert r["edge"] == "scholium-ring warn", "orange from 80 %"
    assert r["over"] == "100%"
    assert r["full"] == "scholium-ring warn"
    assert "上下文窗口" in r["layer"] and "850k / 1,000k（85%）" in r["layer"] and r["noBar"] == 2, "the bar needs the parts"
    assert r["off"] is True and r["k"] == ["999", "550k", "1,000k", "2,567k", "2,568k"]
    assert r["claude"] == {"used": 45102, "window": 0, "parts": {"input": 2, "cache": 45000, "output": 100}}
    assert r["codex"] == {"used": 1050, "window": 9000, "parts": {"input": 400, "cache": 600, "output": 50}}


def test_the_section_stays_at_the_top_of_the_pane_when_a_section_above_it_grows(facts):
    k = facts["keepTop"]
    assert k["kept"] == 1296 + 25, "at the top: scrolled down by what the section above grew"
    assert k["still"] == 1321, "nothing moved: nothing scrolled"
    assert k["away"] == 1321, "scrolled away from the top: left where it is"
    assert k["ownWatched"] is False and k["scrollListeners"] == 1 and k["afterDestroy"] == 0


def test_a_section_drawn_while_collapsed_shows_its_conversation_once_opened(facts):
    o = facts["openLoads"]
    assert o["before"] == 0 and o["closed"] == 0, "drawn collapsed: nothing shown, nothing on closing"
    assert o["after"] == [], "opened: the conversation (here an empty chat, without starters)"
    assert o["again"] == 1, "shown once"
    assert o["rendered"] == 1 and o["destroyed"] == 0, "the listener goes with its pane"


def test_the_section_fills_the_side_pane(facts):
    f = facts["fit"]
    assert f["first"] == "866px" and f["second"] == "666px" and f["small"] == "360px" and f["scroller"] is True
    assert f["measured"] == "770px"          # the gaps are measured at each fit: 900 - (30 + 100)
    assert f["afterRender"] == [1, 1] and f["afterDestroy"] == 0
    assert f["fallback"] == "866px" and f["viaWindow"] == "666px" and f["windowListeners"] == 0
    assert f["none"] == ""
    assert f["noDrag"] == ["undefined", "undefined", None, ""]


def test_the_transcript_by_runs(facts):
    r = facts["runs"]
    assert re.fullmatch(r"正在处理 \d+ 秒", r["liveLine"])
    assert r["parts"] == ["scholium-entry prompt editable", "scholium-fold", "scholium-entry text", "scholium-meta"]
    assert re.fullmatch(r"已处理 \d+ 秒 ›", r["closed"][0]) and r["closed"][1] == 1, "the steps are folded"
    assert r["opened"][0] == "scholium-entry text" and "scholium-entry tool" in r["opened"] and "scholium-entry result" in r["opened"]
    assert r["reclosed"] == 1
    assert re.fullmatch(r"Claude Code · Opus 5\.5 · \d\d:\d\d", r["meta"].replace("复制", "").strip())
    assert r["legacy"] == [["scholium-fold", "scholium-entry text", "scholium-meta"]]


def test_opened_steps_stay_open_and_a_reader_scrolled_up_stays(facts):
    f = facts["foldKept"]
    assert re.fullmatch(r"正在处理 \d+ 秒", f["drawnHead"]), "a section drawn meanwhile shows it live"
    assert re.fullmatch(r"正在处理 \d+ 秒 ⌄", f["during"][0]) and f["during"][1:] == [5, "scholium-fold-head live"]
    assert re.fullmatch(r"已处理 \d+ 秒 ⌄", f["after"][0]) and f["after"][1:] == [11, "scholium-fold-head"], "the reader's choice wins"
    assert f["runs"] == 1, "the run is drawn again in its place"
    assert f["scrollTop"] == 0


def test_a_run_of_the_other_kind_leaves_the_chats_run_finished(facts):
    f = facts["otherKindFold"]
    assert f["live"] is True and f["kind"] == "annotate" and f["running"] is True
    assert re.fullmatch(r"已处理 \d+ 秒 ⌄", f["head"])
    assert f["views"] == [True, True]


def test_opened_steps_belong_to_their_conversation(facts):
    assert facts["foldPerConv"] == {"opened": 2, "other": [True, 1], "same": 2, "untouched": True}


def test_another_papers_run_leaves_a_sections_run_as_it_was(facts):
    f = facts["otherPaperFold"]
    assert re.fullmatch(r"已处理 \d+ 秒 ⌄", f.pop("head"))
    assert f == {"live": True, "running": "ATT2", "prompt": "一个问题", "steps": 11}


def test_logs_are_read_as_runs(facts):
    f = facts["logRuns"]
    assert f["runs"] == 1 and f["head"] == "已处理 6 分 17 秒 ›" and f["meta"] == "Claude Code · Opus 5.5 · " + f["clock"]
    assert f["scrollTop"] == 1000, "at the latest"
    assert f["legacy"] == [
        [["scholium-entry final error", "出错了"]],
        [["scholium-entry prompt editable", "第二个问题"], ["scholium-entry text", "回答 2"], ["scholium-entry text", "补充"], ["scholium-meta", "Claude Code · Opus 5.5"]],
        [["scholium-entry prompt editable", "第三个问题"], ["scholium-entry text", "回答 3"], ["scholium-meta", ""]],
    ], "an earlier version's log: a run at each of the user's words"
    assert f["copied"] == ["回答 2\n\n补充"], "the whole answer"


def test_the_message_being_written_is_last_in_its_run(facts):
    f = facts["draftPlace"]
    assert f["parts"] == [["scholium-fold", "scholium-entry text", "scholium-meta"],
                          ["scholium-entry prompt editable", "scholium-fold", "scholium-entry text", "scholium-entry text draft"]], \
        "the earlier run is finished; the running one has its line and no line under it yet"
    assert re.fullmatch(r"正在处理 \d+ 秒", f["thinking"]) and f["earlier"] == "已处理 ⌄"
    assert f["first"] == [2, True] and f["line"] == [2, True] and f["run"] == [3, True]
    assert f["clicked"] == [2, True], "opening the running run's steps keeps the message being written"


def test_a_runs_lines_before_its_steps_come_above_them(facts):
    assert facts["leadLines"] == [
        ["scholium-entry prompt editable", "scholium-fold", "scholium-entry final error: 中途失败"],
        ["scholium-entry info: 额度已恢复，接着中断的地方继续", "scholium-fold", "scholium-entry text", "scholium-meta"],
        ["scholium-entry prompt editable", "scholium-entry final error: 出错了", "scholium-entry info: 连接失败，30 秒后自动重试一次"],
        ["scholium-entry prompt editable", "scholium-entry text", "scholium-entry final error: 后来失败", "scholium-meta"],
    ]


def test_a_run_that_ends_without_its_conversation_shown_again_is_drawn_finished(facts):
    e = facts["ended"]
    assert e["paused"] == [None, True, ["scholium-fold-head", "已处理 ›"], True], "paused: finished, another paper's section left alone"
    assert e["lineWhilePaused"] == ["scholium-fold-head", "已处理 ›"], "a line while nothing runs"
    assert e["retry"] == [None, "等待第二次尝试", ["scholium-entry prompt", "scholium-entry final error", "scholium-entry info"]]
    assert e["noProgram"] == [["scholium-fold", "scholium-entry text", "scholium-meta"], ["scholium-entry final error"]], \
        "the run before keeps its line; the failure is a run of its own"
    assert e["starting"][0] == [["scholium-fold", "scholium-entry text", "scholium-meta"], ["scholium-fold"]] \
        and e["starting"][1][0] == "scholium-fold-head live" and re.fullmatch(r"正在处理 \d+ 秒", e["starting"][1][1]), \
        "the run before is finished from the start"


def test_the_runs_drawn_follow_the_transcript_when_its_first_run_goes(facts):
    t = facts["trimmed"]
    assert t["kept"] == [["B"], 2], "the steps opened stay with their run"
    assert t["shifted"] == ["B", "C"]


def test_the_words_of_a_runs_line(facts):
    w = facts["words"]
    assert w["live"] == ["正在处理 12 秒"] * 3, "a live line says it works, whatever the last step is"
    assert w["durations"] == ["0 秒", "59 秒", "6 分 17 秒", "1 小时 2 分"]
    assert w["worked"] == ["已处理", "已处理 6 分 17 秒", "已处理"]
    assert w["labels"] == ["Opus 5.5", "Haiku 4.5", "GPT-6-Luna", "gpt-x"]
    assert w["runLines"] == [[{"kind": "run", "at": 5, "compact": False}], [{"kind": "run", "at": 0, "compact": False}]]
    assert w["english"] == ["Working for 12s", "Worked for 6m 17s", "Worked", "59s", "6m 17s", "1h 2m"]


def test_history_is_a_layer_of_this_pdfs_conversations(facts):
    h = facts["history"]
    assert h["keys"] == ["ATT1"], "the best PDF only, though the paper has two"
    assert h["starters"] == ["问题", "贡献", "方法", "实验"]
    assert h["asked"] is True
    assert h["rows"] == ["第二个问题", "这篇论文要解决什么问题？"]
    assert h["after"] == [None, True] and h["shown"] == "回答 1"


def test_the_history_layer_toggles_is_placed_for_its_rows_and_goes_when_the_paper_runs(facts):
    f = facts["historyLayer"]
    assert f["english"] == [["Problem", "Contributions", "Method", "Experiments"],
                            ["What problem does this paper address?", "What are its main contributions?",
                             "What is the core idea of the method?", "Which data and baselines do the experiments use?"]]
    assert f["opened"] == ["history", True, ["scholium-history-empty"]]
    assert f["toggled"] is None, "the button closes its own layer"
    assert f["other"] == ["menu", True], "rows drawn late do not land in another layer"
    assert f["busy"] is None, "no layer while the paper runs"
    assert f["group"] == ["这篇还没有运行记录。"] and f["groupSaved"] is True, "a group library's paper has no saved prompts"


@pytest.mark.parametrize("name", ["retry", "retryAfterStep"])
def test_a_failed_question_can_be_retried(facts, name):
    r = facts[name]
    assert r["label"] == "重试" and "为什么要用这个核？" in r["third"]
    assert r["prompts"] == 1 and r["lastRun"] is None and r["answer"] is True
    assert r["buttons"] == 0, "the button goes with the failure"


def test_the_retry_label_is_in_both_languages(facts):
    assert facts["retryEnglish"] == "Retry"


def test_the_retry_runs_in_the_conversation_shown_and_a_live_run_has_none(facts):
    r = facts["retryElsewhere"]
    assert r == {"shown": True, "answer": True, "log": 1, "liveButton": False, "stays": True}
    assert r["liveButton"] is False


def test_no_retry_while_the_paper_is_busy_and_one_when_it_is_idle_again(facts):
    r = facts["retryBusy"]
    assert r["pending"] == [True, 0] and r["after"] == [False, False, 1]


def test_retry_state_in_a_cancelled_wait_a_later_pane_and_the_usage_limit(facts):
    r = facts["retryBusy"]
    assert r["cancelled"][:4] == [[True, 0], True, 0, 1], "busy: none and the conversation untouched; cancelled while waiting: one"
    assert r["later"] == 1 and r["limit"][:2] == [True, 0]


def test_send_with_retry_keeps_the_given_conversation(facts):
    r = facts["sendRetry"]
    assert r["answered"] is True and r["prompts"] == 1 and r["current"] is None


def test_the_annotation_view_draws_retry_for_words_to_its_session_only(facts):
    r = facts["annotRetry"]
    assert r == {"annot": False, "kind": "annotate", "hasPane": True, "chat": True, "words": True}, "a run without words of its own has none"


def test_a_retry_runs_the_agent_chosen(facts):
    r = facts["retryAgent"]
    assert r == {"claudeRan": 0, "codexCalls": 1, "shown": True, "current": True, "turns": [["问", "codex", True]]}


def test_a_retry_without_a_session(facts):
    r = facts["retryNoSession"]
    first, later = r["first"], r["later"]
    assert first["session"] is None and first["ran"] == 1 and "用户的问题：\n问一" in first["prompt"] and "[第" not in first["prompt"], "the question's prompt, no history"
    assert later["session"] is None and later["ran"] == 1 and "新消息：\n问二" in later["prompt"]
    assert "[第 1 轮]\n用户：问一\n回答（Claude Code）：答一" in later["prompt"] and "[第 2 轮]" not in later["prompt"], "the turns before the retried one"


def test_the_settings_page_hears_the_programs_found(facts):
    f = facts["found"]
    assert f["api"] is True
    assert f["claude"] == "/appdata/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe", "not the path set on the page"
    assert f["codex"] == "/localappdata/OpenAI/Codex/bin/h1/codex.exe", "the newest copy found"
    assert f["after"] is False
    assert f["none"] == [None, None]


def test_the_program_boxes_show_the_program_found():
    script = r'''
const vm = require('node:vm');
const fs = require('node:fs');
const inputs = { 'scholium-claude-path': { placeholder: '' }, 'scholium-codex-path': { placeholder: '' } };
let present = false, listener = null;
const document = { getElementById: id => (present ? inputs[id] || ({ addEventListener() {} }) : null),
                   addEventListener: (t, f, capture) => { if (t === 'load' && capture) listener = f; },
                   l10n: { formatValue: async id => (id === 'scholium-settings-not-found' ? 'NOT FOUND' : id) } };
const found = { claude: 'C:/found/claude.exe', codex: null };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  window: {}, document, Zotero: { Prefs: { set() {} }, Scholium: { found: async agent => found[agent] } },
  ChromeUtils: { importESModule: () => ({}) },
});
const out = {};
setTimeout(() => {
  out.before = [inputs['scholium-claude-path'].placeholder, inputs['scholium-codex-path'].placeholder];
  present = true;
  listener({ target: { classList: { contains: c => c === 'scholium-settings' } } });
  setTimeout(() => { out.after = [inputs['scholium-claude-path'].placeholder, inputs['scholium-codex-path'].placeholder];
                     process.stdout.write(JSON.stringify(out)); }, 20);
}, 20);
'''
    out = subprocess.run([NODE, "-e", script, str(PLUGIN / "settings.js")], capture_output=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["before"] == ["", ""], "no boxes yet when the script runs"
    assert got["after"] == ["C:/found/claude.exe", "NOT FOUND"]
