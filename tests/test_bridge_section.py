"""The Scholium section's layout: the settings page, the tabs, the settings layer, the message box and its round
button, the context ring, the transcript by runs, the history layer, the starters and the retry."""
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest

from bridge_harness import BRIDGE, NODE, PLUGIN, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  // the settings page is registered once the plugin knows its root; the section's ⋯ menu opens it
  {
    const h = harness();
    h.runner.rootURI = 'jar:file:///x/scholium.xpi!/';
    h.runner.start('scholium-bridge@zotero-scholium');
    await settle(20);
    const o = h.log.prefPanes[0];
    facts.settingsPage = { src: o.src, scripts: o.scripts, label: o.label, pluginID: o.pluginID, id: h.runner.prefPaneID };
    h.runner.openSettings();
    facts.settingsPage.opened = h.log.openedPrefs;
    facts.settingsPage.defaults = [h.runner.sendShortcut(), h.runner.followUpMode(), h.runner.contextRingOn()];
    h.store.set('extensions.scholium-bridge.sendShortcut', 'enter');
    h.store.set('extensions.scholium-bridge.followUpMode', 'steer');
    h.store.set('extensions.scholium-bridge.contextRing', false);
    facts.settingsPage.set = [h.runner.sendShortcut(), h.runner.followUpMode(), h.runner.contextRingOn()];
    h.store.set('extensions.scholium-bridge.sendShortcut', 'bogus');
    facts.settingsPage.bogus = h.runner.sendShortcut();
    h.store.set('extensions.scholium-bridge.sendShortcut', 'cmdIfMultiline');
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
                   note: pane.popover.node.textContent.includes('换智能体会开一段新对话') };
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
    h.runner.notes.set('ATT1', { text: '完成 · 21s · 4 轮 · 62k tokens', title: '输入 3 · 输出 640', at: Date.now() });
    h.runner.paintPane(pane);
    facts.chip.done = [pane.state.textContent, pane.state.title];
    h.runner.notes.delete('ATT1'); h.runner.paintPane(pane);
    facts.chip.none = [pane.state.hidden, pane.state.title];
    pane.model.change('fable'); await settle(10);
    facts.chip.after = pane.chip.textContent;
    facts.chip.afterParts = pane.chip.children.map(c => c.className);
    // a section drawn once the models are known (no list asked for again) has the same parts
    const second = await h.pane(h.item2); await settle(20);
    facts.chip.secondParts = second.pane().chip.children.map(c => c.className);
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
    const chatState = p.view().state;
    const dotHere = pane.tabChatDot.hidden;
    pane.tabAnnotate.click(); await settle(10);
    facts.tabs = { first, second, chatState, dotHere, annotState: p.view().state, chatDot: pane.tabChatDot.hidden === false,
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
    const f = { chatBefore: pane.list.children.length, introBefore: !pane.annotIntro.hidden };
    await h.runner.annotate([h.item1]); await settle(200);
    f.kind = h.runner.transcriptKind;
    f.chatTab = { entries: pane.list.children.length, state: p.view().state, annotDot: pane.tabAnnotateDot.hidden === false,
                  chatDot: pane.tabChatDot.hidden === false };
    pane.tabAnnotate.click(); await settle(10);
    f.annotTab = { entries: pane.annot.list.children.length, live: pane.annot.live, running: !!p.view().state, intro: !pane.annotIntro.hidden,
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
    f.row = { intro: !pane.annotIntro.hidden, go: pane.annotGo.hidden, goText: pane.annotGo.textContent, send: pane.send.hidden,
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
    const keyAt = (mode, opts, text = 'x') => { h.store.set('extensions.scholium-bridge.sendShortcut', mode); return h.runner.sendKey(Object.assign({ key: 'Enter' }, opts), text); };
    const keys = {
      always: [keyAt('cmdAlways', {}), keyAt('cmdAlways', { ctrlKey: true }), keyAt('cmdAlways', { ctrlKey: true, shiftKey: true })],
      enter: [keyAt('enter', {}), keyAt('enter', { shiftKey: true }), keyAt('enter', { ctrlKey: true })],
      multiline: [keyAt('cmdIfMultiline', {}, 'one line'), keyAt('cmdIfMultiline', {}, 'two\nlines'), keyAt('cmdIfMultiline', { ctrlKey: true }, 'two\nlines')] };
    keys.composing = h.runner.sendKey({ key: 'Enter', ctrlKey: true, isComposing: true }, 'x');
    keys.other = h.runner.sendKey({ key: 'a', ctrlKey: true }, 'x');
    h.store.set('extensions.scholium-bridge.sendShortcut', 'cmdAlways');
    // the hint line under each shortcut, in both languages; the key sends, and passes whether it inverts
    const hints = {};
    for (const mode of ['enter', 'cmdIfMultiline', 'cmdAlways']) { h.store.set('extensions.scholium-bridge.sendShortcut', mode); h.runner.paintPane(pane); hints[mode] = pane.hint.textContent; }
    h.store.set('extensions.scholium-bridge.sendShortcut', 'cmdAlways'); h.runner.paintPane(pane);
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
    h.store.set('extensions.scholium-bridge.followUpMode', 'steer');
    const followClaudeSteer = follow();
    const job = h.runner.job, agent = job.agent;
    job.agent = 'codex';
    const followCodex = follow();
    h.runner.paintSend(pane);
    const steerTitle = pane.send.title;
    pane.tab = 'annotate'; const followAnnot = follow(); pane.tab = 'chat';      // another tab's run is not this one's to steer
    const keys0 = pane.keys; pane.keys = []; const followElsewhere = follow(); pane.keys = keys0;
    h.store.set('extensions.scholium-bridge.followUpMode', 'queue');
    const followCodexQueue = follow();
    job.agent = agent;
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
    h.store.set('extensions.scholium-bridge.contextRing', false); h.runner.paintPane(pane);
    const claude = h.runner.contextAfter({ type: 'assistant', message: { usage: { input_tokens: 2, cache_creation_input_tokens: 5000, cache_read_input_tokens: 40000, output_tokens: 100 } } }, null);
    const codex = h.runner.contextAfter({ method: 'thread/tokenUsage/updated', params: { tokenUsage: { modelContextWindow: 9000,
      last: { totalTokens: 1050, inputTokens: 1000, cachedInputTokens: 600, outputTokens: 50 } } } }, null);
    facts.ring = { half, parts, boxes, toggled, edge, over, full, layer, noBar, off: pane.ring.hidden, claude, codex,
                   k: [999, 550123, 1000000, 2567000, 2567600].map(n => h.runner.kTokens(n)) };
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
    assert s["label"] == "Scholium" and s["pluginID"] == "scholium-bridge@zotero-scholium"
    assert s["multiline"] == "cmdIfMultiline" and s["afterStop"] is None
    assert s["id"] == "scholium-pane-id" and s["opened"] == ["scholium-pane-id"]
    assert s["defaults"] == ["cmdAlways", "queue", True] and s["set"] == ["enter", "steer", False] and s["bogus"] == "cmdAlways"
    assert "Zotero 设置" in s["noClaude"] and "配置编辑器" not in s["noClaude"]
    assert "Zotero 设置" in s["noCodex"] and "配置编辑器" not in s["noCodex"]
    assert s["settingsOpen"] == "设置…"
    assert facts["english"] == ["Claude Code (claude) was not found. Set its program in Zotero Settings → Scholium.",
                                "Codex (codex) was not found. Set its program in Zotero Settings → Scholium.", "Settings…"]


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
const document = { getElementById: id => ({ addEventListener: (t, f) => { handlers[id] = f; } }) };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  window: {}, document, Zotero: { Prefs: { set() {} } },
  ChromeUtils: { importESModule: () => ({ FilePicker }) },
});
(async () => {
  for (const id of Object.keys(handlers)) { handlers[id](); await new Promise(r => setTimeout(r, 5)); }
  process.stdout.write(JSON.stringify({ ids: Object.keys(handlers), filters }));
})();
'''
    out = subprocess.run([NODE, "-e", script, str(PLUGIN / "settings.js")], capture_output=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["ids"] == ["scholium-claude-browse", "scholium-codex-browse"]
    assert got["filters"] == [0x001, 0x001], "all files, not only applications"


def test_the_settings_page_binds_every_preference():
    ns = {"x": "http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul", "h": "http://www.w3.org/1999/xhtml"}
    src = (PLUGIN / "settings.xhtml").read_text(encoding="utf8")
    root = ET.fromstring("<root xmlns='%s' xmlns:html='%s'>%s</root>" % (ns["x"], ns["h"], src))
    prefs = {el.get("preference") for el in root.iter() if el.get("preference")}
    assert prefs == {"extensions.scholium-bridge." + p for p in ("sendShortcut", "followUpMode", "contextRing", "claudePath", "codexPath")}
    ids = {el.get("data-l10n-id") for el in root.iter() if el.get("data-l10n-id")}
    for locale in ("en-US", "zh-CN"):
        ftl = (PLUGIN / "locale" / locale / "scholium-bridge.ftl").read_text(encoding="utf8")
        defined = set(re.findall(r"^([a-z][\w-]*)\s*=", ftl, re.M))
        assert ids <= defined, (locale, ids - defined)
    defaults = (PLUGIN / "prefs.js").read_text(encoding="utf8")
    for p, v in (("sendShortcut", '"cmdAlways"'), ("followUpMode", '"queue"'), ("contextRing", "true")):
        assert f'pref("extensions.scholium-bridge.{p}", {v});' in defaults


def ftl_messages(locale):
    """{id: (value or None, {attribute names})} of the plugin's ftl of a locale."""
    out, last = {}, None
    for line in (PLUGIN / "locale" / locale / "scholium-bridge.ftl").read_text(encoding="utf8").splitlines():
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
    assert len(labelled) == 8
    picker = re.findall(r'"(scholium-settings-[a-z-]+)"', (PLUGIN / "settings.js").read_text(encoding="utf8"))
    assert picker == ["scholium-settings-claude", "scholium-settings-codex"]
    for locale in ("en-US", "zh-CN"):
        msgs = ftl_messages(locale)
        for i in labelled:
            assert msgs[i][0] is None and "label" in msgs[i][1], (locale, i, "a menu item, radio, checkbox or button shows its .label")
        for i in picker:
            assert msgs[i][0], (locale, i, "the file picker's title is a message's value")
    assert not [el for el in root.iter() if el.tag == "{%s}h2" % ns["h"]], "the page's heading is Zotero's"
    inputs = [el for el in root.iter() if el.tag == "{%s}input" % ns["h"]]
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
    out = json.loads(subprocess.run([NODE, "-e", script, str(BRIDGE)], text=True, capture_output=True, check=True, timeout=15).stdout)
    assert out == ["jar:file:///x.xpi!/"]


def test_the_release_workflow_zips_every_top_level_entry_of_the_plugin():
    workflow = (PLUGIN.parent.parent / ".github" / "workflows" / "release.yml").read_text(encoding="utf8")
    line = next(l for l in workflow.splitlines() if l.strip().startswith("zip ") and "scholium-bridge.xpi" in l)
    zipped = set(line.split("scholium-bridge.xpi", 1)[1].split())
    assert set(os.listdir(PLUGIN)) <= zipped, set(os.listdir(PLUGIN)) - zipped


def test_the_settings_chip_and_its_layer(facts):
    c = facts["chip"]
    assert c["chip"] == "Claude Code · Opus 5.5 · medium ▾"
    assert c["open"] == {"name": "settings", "selects": True, "note": True}
    assert c["afterDropdown"] == "settings", "a choice in a select's dropdown keeps the layer"
    assert c["afterOutside"] is None and c["afterEsc"] is None
    assert c["menu"] == ["打开日志", "个人配置 ↗", "", "设置…"] and c["oneAtATime"] == "settings"
    assert c["after"].startswith("Claude Code · Fable") and c["afterParts"] == ["scholium-chip-name", "scholium-chip-tail"]
    assert c["secondParts"] == ["scholium-chip-name", "scholium-chip-tail"]
    # the agent and the model are cut first; the effort stays
    assert c["parts"] == [["scholium-chip-name", "Claude Code · Opus 5.5"], ["scholium-chip-tail", " · medium ▾"]]
    assert c["tip"] == "Claude Code · Opus 5.5 · medium"
    assert c["done"] == ["完成 · 21s · 4 轮 · 62k tokens", "完成 · 21s · 4 轮 · 62k tokens\n输入 3 · 输出 640"]
    assert c["none"] == [True, ""]
    rules = css_rules()
    assert "display: flex" in rules[".scholium-chip"] and "flex: none" in rules[".scholium-chip-tail"]
    assert "white-space: pre" in rules[".scholium-chip-tail"], "the space before · stays at the start of its box"
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
    assert t["chatState"] and not t["chatState"].startswith("上次")
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
    assert f["row"] == {"intro": True, "go": False, "goText": "批注这篇", "send": True, "annotList": True,
                    "placeholder": "附加要求（可选），例如：只标注方法部分", "old": [True] * 5}
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
    assert r["parts"] == {"names": ["scholium-context-head", "scholium-context-bar", "scholium-context-legend"], "head": "上下文窗口550k / 1,000k（55%）",
                          "segs": [["seg input", "6.00%"], ["seg cache", "44.00%"], ["seg output", "5.00%"]], "legend": ["输入60k", "缓存440k", "输出50k"]}
    # each label and number is a box of its own row
    assert r["boxes"] == {"head": [["span", "上下文窗口"], ["span", "550k / 1,000k（55%）"]],
                          "legend": [[["span", "输入"], ["span", "60k"]], [["span", "缓存"], ["span", "440k"]], [["span", "输出"], ["span", "50k"]]]}
    assert r["toggled"] is None, "the ring toggles its layer"
    assert r["edge"] == "scholium-ring warn", "orange from 80 %"
    assert r["over"] == "100%"
    assert r["full"] == "scholium-ring warn"
    assert "上下文窗口" in r["layer"] and "850k / 1,000k（85%）" in r["layer"] and r["noBar"] == 1, "the bar needs the parts"
    assert r["off"] is True and r["k"] == ["999", "550k", "1,000k", "2,567k", "2,568k"]
    assert r["claude"] == {"used": 45102, "window": 0, "parts": {"input": 2, "cache": 45000, "output": 100}}
    assert r["codex"] == {"used": 1050, "window": 9000, "parts": {"input": 400, "cache": 600, "output": 50}}


def test_the_section_stays_at_the_top_of_the_pane_when_a_section_above_it_grows(facts):
    k = facts["keepTop"]
    assert k["kept"] == 1296 + 25, "at the top: scrolled down by what the section above grew"
    assert k["still"] == 1321, "nothing moved: nothing scrolled"
    assert k["away"] == 1321, "scrolled away from the top: left where it is"
    assert k["ownWatched"] is False and k["scrollListeners"] == 1 and k["afterDestroy"] == 0


def test_the_section_fills_the_side_pane(facts):
    f = facts["fit"]
    assert f["first"] == "866px" and f["second"] == "666px" and f["small"] == "360px" and f["scroller"] is True
    assert f["measured"] == "770px"          # the gaps are measured at each fit: 900 - (30 + 100)
    assert f["afterRender"] == [1, 1] and f["afterDestroy"] == 0
    assert f["fallback"] == "866px" and f["viaWindow"] == "666px" and f["windowListeners"] == 0
    assert f["none"] == ""
    assert f["noDrag"] == ["undefined", "undefined", None, ""]
