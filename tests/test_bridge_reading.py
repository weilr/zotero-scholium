"""Asking about a passage selected in the reader: Ask Scholium in the selection popup puts the passage, with its page, as a
quote above the chat tab's box; it goes with the user's words to the agent, and the transcript shows it above them."""
import pytest

from bridge_harness import NODE, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const qInit = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
  const PASSAGE = 'We propose a kernel that is invariant to rotations.';
  // a selection in the reader: Ask Scholium shows the chat tab with the passage quoted above the box; it goes with the
  // words as the passage of page N, and the transcript shows it above them
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    const [button] = h.selection(PASSAGE, 3, '4');
    const label = button.textContent;
    button.click(); await settle(20);
    const cleared = h.log.selectionsCleared || 0;
    const quoted = { tab: pane.tab, box: pane.quoteBox.hidden ? null : pane.quoteBox.children[0].textContent };
    // the quote belongs to the chat tab: the annotation tab does not show it
    pane.tabAnnotate.click(); await settle(10);
    const onAnnotate = pane.quoteBox.hidden;
    pane.tabChat.click(); await settle(10);
    const back = pane.quoteBox.hidden;
    pane.input.type('这个核为什么不变？'); pane.send.click(); await settle(400);
    const prompt = convLines(h).find(l => l.subtype === 'prompt');
    const shown = pane.list.children.at(-1).children[0];
    facts.selection = { label, cleared, quoted, onAnnotate, back, after: pane.quoteBox.hidden, stdin: h.log.stdin[0], quote: prompt.quote,
                        shown: [shown.children[0].className, shown.children[0].textContent, shown.children[1].textContent] };
    // the quote can be taken away before sending
    h.selection('Another passage.', 0, '1')[0].click(); await settle(10);
    facts.selection.drop = [pane.quoteBox.children[1].className, labelOf(pane.quoteBox.children[1])];
    pane.quoteBox.children[1].click(); await settle(10);
    facts.selection.removed = [pane.quoteBox.hidden, pane.quote];
    // a selection without text has no button; the page falls back to its number
    facts.selection.empty = h.selection('   ', 0, '1').length;
    h.selection('No\n  label.', 6, '')[0].click(); await settle(10);
    facts.selection.noLabel = pane.quoteBox.children[0].textContent;
    // a conversation that goes on shows and tells the quote the same way: the turn of the log keeps it
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    facts.selection.turn = log.turns[0].quote;
    facts.selection.history = h.runner.historyParts(log.turns).whole[0].user;
  }
  // the passage chosen before the section is drawn waits for it, and shows on the chat tab
  {
    const h = harness({});
    h.runner.start('x');
    const [button] = h.selection(PASSAGE, 3, '4');
    button.click(); await settle(20);
    const waiting = h.runner.pendingQuotes.get('ATT1') || null;
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    facts.pending = { waiting, tab: pane.tab, box: pane.quoteBox.hidden ? null : pane.quoteBox.children[0].textContent,
                      left: h.runner.pendingQuotes.size };
    // a section drawn again keeps the quote
    h.log.sections[0].onRender({ doc: h.paneDoc, body: p.body, item: h.item1 }); await settle(10);
    const again = p.pane();
    facts.pending.again = again.quoteBox.hidden ? null : again.quote;
  }
  // the popup's listener is registered with the plugin and let go of with it
  {
    const h = harness({});
    h.runner.start('x');
    const had = h.log.listeners.some(l => l.type === 'renderTextSelectionPopup');
    h.runner.stop();
    facts.listener = { had, after: h.log.listeners.some(l => l.type === 'renderTextSelectionPopup') };
  }
  // a quote queued behind a run waits with its message and goes with it; a retry of a turn sends it again; an update
  // hands it over
  {
    const h = harness({ scripts: [[qInit, 'WAIT'], [qInit, 'HOLD', ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(100);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.input.type('追问二'); pane.send.click(); await settle(30);
    const queued = h.runner.queue.map(j => j.quote);
    const cleared = pane.quoteBox.hidden;
    h.runner.stop(true); await settle(40);
    const carried = JSON.parse(h.store.get('extensions.scholium-bridge.carryOver'));
    const h2 = harness({ prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify(carried) }, logs: ours(h),
                         scripts: [[qInit, 'HOLD', ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' })],
                                  [qInit, ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' })]] });
    h2.runner.start('x', true);
    for (let i = 0; i < 3000 && !h2.log.release; i++) await tick();
    await settle(20);
    facts.queuedQuote = { queued, cleared, carried: carried.jobs.map(j => [j.say, j.quote || null]),
                          restored: h2.runner.queue.filter(j => j.qid).map(j => [j.say, j.quote]) };
    h2.log.release();
    await settle(600);
    const lines = convLines(h2).filter(l => l.subtype === 'prompt').map(l => [l.text, l.quote || null]);
    facts.queuedQuote.prompts = lines;
    facts.queuedQuote.stdin = (h2.log.stdin.at(-1) || '').includes('> ' + PASSAGE);
    h2.runner.stop();
  }
  // Retry of a turn that carries a quote sends the quote again
  {
    const h = harness({ scripts: [[qInit, ev({ type: 'result', subtype: 'success', is_error: true, result: 'boom', session_id: 'S1' })],
                                  [qInit, ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.input.type('为什么'); pane.send.click(); await settle(400);
    const view = h.runner.viewOf(pane, 'chat');
    await h.runner.retryFromView(view); await settle(400);
    facts.retry = { stdin: h.log.stdin.map(s => s.includes('用户引用了第 4 页的这段原文：\n> ' + PASSAGE)),
                    quotes: convLines(h).filter(l => l.subtype === 'prompt').map(l => l.quote || null) };
  }
  // a steer keeps the quote for the next message; the words typed with it go as they are
  {
    const h = harness({ scripts: [[qInit, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(100);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    facts.steerKeeps = { quote: pane.quote, shown: !pane.quoteBox.hidden };
    h.runner.stop();
  }
  // a queued row steered into the answer under way tells the agent the passage; steering from the box keeps the quote
  // for the next message
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.followUpMode': 'queue' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.input.type('只看第 3 节'); pane.send.click(); await settle(50);
    const row = h.runner.queue.find(j => j.qid);
    await h.runner.steerQueued(pane, row.qid); await settle(50);
    facts.steerQueuedQuote = { steers: h.log.steers.map(s => JSON.stringify(s.input)), lines: convLines(h).filter(l => l.subtype === 'steer').map(l => l.text) };
    h.selection('Second.', 0, '1')[0].click(); await settle(10);
    pane.input.type('再看'); h.runner.sendFromPane(pane, true); await settle(50);
    facts.steerQueuedQuote.box = [pane.quote, pane.quoteBox.hidden];
    facts.steerQueuedQuote.sent = h.log.steers.map(s => JSON.stringify(s.input)).at(-1);
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    facts.steerQueuedQuote.lines = convLines(h).filter(l => l.subtype === 'steer').map(l => [l.text, l.quote || null]);
    facts.steerQueuedQuote.entries = log.entries.filter(e => e.kind === 'prompt' && e.steer).map(e => [e.text, e.quote || null]);
    facts.steerQueuedQuote.user = log.turns[0].user;
    const node = h.runner.entryNode(pane.doc, log.entries.filter(e => e.steer).at(-1));
    facts.steerQueuedQuote.node = node.children.map(c => [c.className, c.textContent]);
    h.runner.stop();
  }
  // words that did not reach the agent go back to the box with their quote, unless the box has a quote of its own
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const quote = { text: PASSAGE, page: '4' };
    h.runner.giveBack({ att: h.att1, say: '问', quote, kind: 'chat', agent: 'claude', conv: null });
    const back = [pane.input.value, pane.quote, pane.quoteBox.hidden];
    pane.input.type(''); pane.quote = { text: 'mine', page: '1' }; h.runner.paintQuote(pane);
    h.runner.unsent.clear();
    h.runner.giveBack({ att: h.att1, say: '又问', quote, kind: 'chat', agent: 'claude', conv: null });
    facts.giveBack = { back, other: [pane.input.value, pane.quote.text] };
  }
  // steering words into an annotation run takes no quote along
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); pane.input.type('只批注第 3 页'); pane.annotGo.click(); await settle(400);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.tabAnnotate.click(); await settle(10);
    pane.input.type('也看第 5 页'); h.runner.sendFromPane(pane, true); await settle(100);
    facts.annotateSteerNoQuote = { steers: h.log.steers.map(s => s.input[0].text), kept: pane.quote && pane.quote.page };
    h.runner.stop();
  }
  // the quote goes with the chat's messages only: words to an annotation session carry none
  {
    const h = harness({ scripts: [[qInit, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.tabAnnotate.click(); await settle(10);
    pane.annot.shownKey = 'ATT1'; pane.annot.shownConv = 'annotate-claude-20261001-120000';
    pane.input.type('改一下'); pane.send.click(); await settle(100);
    facts.annotateNoQuote = { told: h.log.stdin.some(t => t.includes(PASSAGE)), sent: h.log.stdin.length, kind: h.runner.job ? h.runner.job.source.kind : null, kept: pane.quote && pane.quote.page };
    h.runner.stop();
  }
  // a section drawn again with a quote waiting comes back on the chat tab
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    h.runner.pendingQuotes.set('ATT1', { text: 'T', page: '9' });
    h.log.sections[0].onRender({ doc: h.paneDoc, body: p.body, item: h.item1 }); await settle(10);
    facts.pendingTab = [p.pane().tab, p.pane().quote];
  }
  // the words of an English user go with the passage in English, in the first message of a conversation and in the next
  {
    const ok = ev({ type: 'result', subtype: 'success', is_error: false, result: 'ok', session_id: 'S1' });
    const h = harness({ locale: 'en-US', scripts: [[qInit, ok], [qInit, ok]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.input.type('Why?'); pane.send.click(); await settle(400);
    h.selection('Next one.', 0, '1')[0].click(); await settle(10);
    pane.input.type('And?'); pane.send.click(); await settle(400);
    facts.english = h.log.stdin.map(t => [t.includes('The user quotes this passage from page 4:\n> ' + PASSAGE + '\n\nWhy?'),
                                           t.includes('The user quotes this passage from page 1:\n> Next one.\n\nAnd?')]);
  }
  // the section of a paper in the window of the reader: not another window's, not another paper's
  {
    const h = harness({});
    h.runner.start('x');
    const a = await h.pane(h.item1); await settle(20);
    const win2 = Object.create(h.paneWin), doc2 = Object.create(h.paneDoc);
    doc2.defaultView = win2;
    const bodyB = new h.El('div');
    h.log.sections[0].onRender({ doc: doc2, body: bodyB, item: h.item1 });
    const c = await h.pane(h.item2); await settle(20);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(30);
    facts.paneFor = { a: a.pane().quote && a.pane().quote.page, b: h.runner.panes.get(bodyB).quote, c: c.pane().quote };
  }
  // a reader's own section, in its side pane: not the library's, which stays drawn (and visible to checkVisibility) behind the
  // reader's tab; a reader whose section is not drawn yet has the passage wait for it
  {
    const h = harness({});
    h.runner.start('x');
    const lib = await h.pane(h.item1); await settle(20);
    lib.body.checkVisibility = () => true;
    const inReader = tabID => sel => (sel === 'item-details' ? { tabID, _paneParent: new h.El('div') } : null);
    const rd = await h.pane(h.item1, { closest: inReader('TAB1') }); await settle(20);
    rd.body.checkVisibility = () => true;
    h.selection(PASSAGE, 3, '4', 'TAB1')[0].click(); await settle(30);
    const own = [lib.pane().quote, rd.pane().quote && rd.pane().quote.page];
    // the side pane of TAB2 holds the section, collapsed and not drawn yet: it is opened and scrolled to, which draws it
    const steps = [];
    const section = new h.El('collapsible-section'); section.open = false;
    const custom = { dataset: { pane: 'scholium-pane' }, querySelector: sel => (sel === 'collapsible-section' ? section : null) };
    const details2 = { tabID: 'TAB2', querySelectorAll: sel => (sel === 'item-pane-custom-section' ? [{ dataset: { pane: 'other' } }, custom] : []),
                       scrollToPane: async id => { steps.push([id, section.open]); } };
    h.paneDoc.getElementById = id => (id === 'TAB2-context' ? details2 : null);
    h.selection('Another passage.', 0, '1', 'TAB2')[0].click(); await settle(30);
    const waits = [lib.pane().quote, h.runner.pendingQuotes.get('ATT1') && h.runner.pendingQuotes.get('ATT1').page];
    const rd2 = await h.pane(h.item1, { closest: inReader('TAB2') }); await settle(20);
    facts.readerPane = { own, waits, steps, drawn: rd2.pane().quote && rd2.pane().quote.page, library: lib.pane().quote };
  }
  // a conversation that is no question's (an annotation prompt before the words, as a legacy conversation has) gets the passage
  // in the follow-up the agent is given
  {
    const log = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '批注', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '批注' })
      + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' });
    const h = harness({ logs: { [CONV1]: log }, scripts: [[qInit, ev({ type: 'result', subtype: 'success', is_error: false, result: 'ok', session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.input.type('这个核为什么不变？'); pane.send.click(); await settle(400);
    const args = h.log.calls[0].opts.arguments;
    facts.nonAsking = { resumed: args.includes('--resume'), told: h.log.stdin[0].includes('用户引用了第 4 页的这段原文：\n> ' + PASSAGE + '\n\n这个核为什么不变？'),
                        question: h.log.stdin[0].includes('用户的问题') };
  }
  {
    const log = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: 'annotate', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: 'annotate' })
      + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + ev({ type: 'result', subtype: 'success', is_error: false, result: 'done', session_id: 'S1' });
    const h = harness({ locale: 'en-US', logs: { [CONV1]: log }, scripts: [[qInit, ev({ type: 'result', subtype: 'success', is_error: false, result: 'ok', session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    pane.input.type('Why?'); pane.send.click(); await settle(400);
    facts.nonAskingEn = h.log.stdin[0].includes('The user quotes this passage from page 4:\n> ' + PASSAGE + '\n\nWhy?') && !h.log.stdin[0].includes("The user's question");
  }
  // a selection that has neither a page label nor a page index is quoted without a page
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.selection(PASSAGE, -1, '')[0].click(); await settle(10);
    const box = pane.quoteBox.children[0].textContent;
    pane.input.type('为什么'); pane.send.click(); await settle(400);
    const shown = pane.list.children.at(-1).children[0];
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    facts.noPage = { box, stdin: h.log.stdin[0], quote: convLines(h).find(l => l.subtype === 'prompt').quote, shown: shown.children[0].textContent,
                     said: [h.runner.said({ say: '问', quote: { text: 'a', page: '' } })],
                     history: h.runner.historyParts(log.turns).whole[0].user };
    h.runner.zh = () => false;
    facts.noPage.saidEn = h.runner.said({ say: 'Q', quote: { text: 'a', page: '' } });
  }
  // the quote of the text in a prompt without one keeps its structure
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const node = h.runner.entryNode(pane.doc, { kind: 'prompt', text: '问' });
    facts.plainPrompt = [node.className, node.children.length, node.textContent];
    const q = h.runner.entryNode(pane.doc, { kind: 'prompt', text: '问', quote: { text: 'T', page: '2' } });
    facts.quotedPrompt = [q.children.map(c => [c.tagName, c.className, c.textContent])];
    facts.entry = h.runner.entries({ type: 'scholium', subtype: 'prompt', text: '问', quote: { text: 'T', page: 2 } })
      .concat(h.runner.entries({ type: 'scholium', subtype: 'prompt', text: '问', quote: { text: '' } }));
    facts.said = [h.runner.said({ say: '问', quote: { text: 'a\nb', page: '2' } }), h.runner.said({ say: '问', quote: null })];
  }
  // the section is revealed in the reader's side pane: the context pane opens, the section opens, the item pane scrolls
  // to it; every step may fail without losing the quote
  {
    const run = async (setup) => {
      const h = harness({});
      h.runner.start('x');
      const steps = [];
      const section = new h.El('collapsible-section'); section.rect = { top: 0, left: 0, right: 300, bottom: 504, width: 300, height: 504 };
      section.open = false;
      const details = { _paneParent: null, scrollToPane: async id => { steps.push(['scroll', id, h.paneWin.ZoteroContextPane ? h.paneWin.ZoteroContextPane.collapsed : null, section.open]); return {}; } };
      const closest = sel => (sel === 'item-details' ? details : sel === 'collapsible-section' ? section : null);
      const p = await h.pane(h.item1, { closest });
      await settle(40);
      const pane = p.pane();
      setup(h, details, section);
      h.selection(PASSAGE, 3, '4')[0].click(); await settle(30);
      return { steps, open: section.open, collapsed: h.paneWin.ZoteroContextPane ? h.paneWin.ZoteroContextPane.collapsed : null,
               quote: pane.quote && pane.quote.page };
    };
    facts.reveal = {
      collapsed: await run(h => { h.paneWin.ZoteroContextPane = { collapsed: true }; }),
      open: await run(h => { h.paneWin.ZoteroContextPane = { collapsed: false }; }),
      noContext: await run(() => {}),
      scrollThrows: await run((h, details) => { details.scrollToPane = async () => { throw Error('no'); }; }),
      noScroll: await run((h, details) => { delete details.scrollToPane; }),
    };
    // without an item-details around the section, the quote lands anyway
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(30);
    facts.reveal.bare = p.pane().quote.page;
  }
  // [#id] in an answer: a chip with the page, when sentences.json has the sentence; a card on hover with the page, Locate
  // and the sentence; an id it does not have stays text
  {
    const SPATH = '/data/tmp/scholium/ATT1/sentences.json';
    const sentences = JSON.stringify({ pdf: 'x.pdf', sentences: [{ id: 12, page: 4, para: 3, text: 'We propose a kernel that is invariant to rotations.',
                                                                  rects: [[72, 600, 300, 612]] }] });
    const reply = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                   said('核在旋转下不变 [#12]，见附录 [#999]。'),
                   ev({ type: 'result', subtype: 'success', is_error: false, result: '…', session_id: 'S1' })];
    const h = harness({ scripts: [reply], logs: { [SPATH]: sentences } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('核为什么不变？'); pane.send.click(); await settle(500);
    const wait = ms => new Promise(r => setTimeout(r, ms));
    const lastAnswer = () => pane.list.children.at(-1).children.find(c => c.className.startsWith('scholium-entry text'));
    const answer = lastAnswer();
    const all = n => [n, ...(n.children || []).flatMap(all)];
    const chipOf = a => all(a).find(n => n.className === 'scholium-cite');
    const chip = chipOf(answer);
    chip.fire('mouseenter'); await settle(10);
    const card = pane.popover && pane.popover.name === 'cite' ? pane.popover.node : null;
    const head = card && card.children[0].children.map(c => c.textContent);
    const sentence = card.children[1].textContent;
    // the pointer leaves the chip for the card: it stays; it leaves the card: it closes
    chip.fire('mouseleave'); card.fire('mouseenter'); await wait(400);
    const stays = !!pane.popover;
    card.fire('mouseleave'); await wait(400);
    const closed = !pane.popover;
    chip.fire('mouseenter'); await settle(10);
    pane.popover.node.children[0].children[1].click(); await settle(50);
    const opened = h.log.readerOpened.at(-1).location;
    const viaLocate = [!pane.popover, h.log.readerOpened.length];
    chip.click(); await settle(50);
    facts.cites = { text: answer.textContent, chip: chip.textContent, id: chip.attrs && chip.attrs['data-id'], head, sentence, stays, closed,
                    opened, viaLocate, viaChip: [h.log.readerOpened.length, h.log.readerOpened.at(-1).itemID === h.att1.id], prompt: h.log.stdin[0],
                    opens: h.log.readerOpened.map(o => o.location), navigated: h.log.navigated };
    // the file as it was and unchanged is not read again by drawing anew; a changed file is read again
    const reads = () => h.log.reads.filter(r => r === SPATH).length;
    const r0 = reads();
    await h.runner.showConversation(pane); await settle(20);
    const r1 = reads();
    h.log.writes[SPATH] = JSON.stringify({ sentences: [{ id: 12, page: 5, para: 3, text: 'Changed.' }] });
    h.log.mtimes[SPATH] = h.log.clock + 1000;
    await h.runner.showConversation(pane); await settle(20);
    facts.cites.reads = [r0 > 0, r1 - r0, reads() - r1];
    facts.cites.again = chipOf(lastAnswer()).textContent;
    // the same time and another size is a changed file as well
    h.log.writes[SPATH] = JSON.stringify({ sentences: [{ id: 12, page: 6, para: 3, text: 'Changed again, and longer.' }] });
    await h.runner.showConversation(pane); await settle(20);
    facts.cites.bySize = chipOf(lastAnswer()).textContent;
    // a chip hovered while another layer is open leaves that layer alone
    pane.chip.click(); await settle(10);
    const layer = pane.popover && pane.popover.name;
    chipOf(lastAnswer()).fire('mouseenter'); await settle(10);
    facts.cites.layer = [layer, pane.popover && pane.popover.name];
  }
  // the annotation tab's answers to words get their chips too
  {
    const DIR = '/data/tmp/scholium/ATT1/conversations/';
    const SESSION = 'annotate-claude-20261030-101010';
    const sentences = JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] });
    const h = harness({ logs: {
      '/data/tmp/scholium/ATT1/sentences.json': sentences,
      [DIR + SESSION + '.jsonl']: ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问', at: Date.now() - 60000 })
        + ev({ type: 'scholium', subtype: 'prompt', text: '问', question: true })
        + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' }) + said('见 [#12]')
        + ev({ type: 'result', subtype: 'success', is_error: false, result: 'x', session_id: 'A0' }),
      [DIR + 'index.json']: JSON.stringify({ current: {}, titles: {}, annotation: { claude: SESSION } }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(30);
    const all = n => [n, ...(n.children || []).flatMap(all)];
    facts.citeAnnotation = all(pane.annot.list).filter(n => n.className === 'scholium-cite').map(n => n.textContent);
  }
  // an answer on its way gets its chips: the sentences written after the section was drawn are read when the run starts
  {
    const reply = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                   said('见 [#12]'), 'HOLD',
                   ev({ type: 'result', subtype: 'success', is_error: false, result: '…', session_id: 'S1' })];
    const h = harness({ scripts: [reply] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    h.log.writes['/data/tmp/scholium/ATT1/sentences.json'] = JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] });
    pane.input.type('q'); pane.send.click(); await settle(200);
    const all = n => [n, ...(n.children || []).flatMap(all)];
    facts.citeLive = [pane.live, all(pane.list).filter(n => n.className === 'scholium-cite').map(n => n.textContent)];
    // a live view shown anew while the sentences changed: drawn at once, then again with the new sentences
    h.log.writes['/data/tmp/scholium/ATT1/sentences.json'] = JSON.stringify({ sentences: [{ id: 12, page: 7, para: 3, text: 'S2 is longer.' }] });
    h.runner.showLive(pane, 'ATT1', 'chat'); await settle(30);
    facts.citeLive.push(all(pane.list).filter(n => n.className === 'scholium-cite').map(n => n.textContent));
    // the draft being written stays in the last run through that redraw, and keeps growing
    h.runner.growDraft('草稿', 0); h.runner.paintDraft();
    h.log.writes['/data/tmp/scholium/ATT1/sentences.json'] = JSON.stringify({ sentences: [{ id: 12, page: 8, para: 3, text: 'S3 is longer still.' }] });
    h.runner.showLive(pane, 'ATT1', 'chat'); await settle(30);
    const text = n => (n.children || []).map(text).join('') + (n.children && n.children.length ? '' : n.textContent || '');
    const atOnce = text(pane.list.children.at(-1)).includes('草稿');   // before anything paints it again
    h.runner.growDraft('续写', 0); h.runner.paintDraft();
    facts.citeDraft = [all(pane.list).filter(n => n.className === 'scholium-cite').map(n => n.textContent), atOnce, text(pane.list.children.at(-1)).includes('草稿续写')];
    h.log.release(); await settle(300);
  }
  // a sentences.json that does not parse is read once; a later change is read again
  {
    const DIR = '/data/tmp/scholium/ATT1/conversations/';
    const SESSION = 'annotate-claude-20261030-101010';
    const SPATH = '/data/tmp/scholium/ATT1/sentences.json';
    const h = harness({ logs: {
      [SPATH]: '{broken',
      [DIR + SESSION + '.jsonl']: ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问', at: Date.now() - 60000 })
        + ev({ type: 'scholium', subtype: 'prompt', text: '问', question: true })
        + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' }) + said('见 [#12]')
        + ev({ type: 'result', subtype: 'success', is_error: false, result: 'x', session_id: 'A0' }),
      [DIR + 'index.json']: JSON.stringify({ current: {}, titles: {}, annotation: { claude: SESSION } }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(30);
    await h.runner.showAnnotation(pane); await settle(10);
    const reads = () => h.log.reads.filter(r => r === SPATH).length;
    const first = reads();
    h.log.writes[SPATH] = JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] });
    h.log.mtimes[SPATH] = h.log.clock + 5000;
    await h.runner.showAnnotation(pane); await settle(10);
    const all = n => [n, ...(n.children || []).flatMap(all)];
    facts.citeBroken = [first, reads() - first, all(pane.annot.list).filter(n => n.className === 'scholium-cite').map(n => n.textContent)];
  }
  // a sentences.json that cannot be read (the agent is writing it) is tried again at the next draw
  {
    const DIR = '/data/tmp/scholium/ATT1/conversations/';
    const SESSION = 'annotate-claude-20261030-101010';
    const SPATH = '/data/tmp/scholium/ATT1/sentences.json';
    const unreadable = [SPATH];
    const h = harness({ unreadable, logs: {
      [SPATH]: JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] }),
      [DIR + SESSION + '.jsonl']: ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问', at: Date.now() - 60000 })
        + ev({ type: 'scholium', subtype: 'prompt', text: '问', question: true })
        + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' }) + said('见 [#12]')
        + ev({ type: 'result', subtype: 'success', is_error: false, result: 'x', session_id: 'A0' }),
      [DIR + 'index.json']: JSON.stringify({ current: {}, titles: {}, annotation: { claude: SESSION } }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(30);
    const reads = () => h.log.reads.filter(r => r === SPATH).length;
    const all = n => [n, ...(n.children || []).flatMap(all)];
    const chips = () => all(pane.annot.list).filter(n => n.className === 'scholium-cite').map(n => n.textContent);
    const first = [reads() > 0, chips()];
    const before = reads();
    await h.runner.showAnnotation(pane); await settle(10);
    const again = reads() - before;
    unreadable.length = 0;
    await h.runner.showAnnotation(pane); await settle(10);
    facts.citeUnreadable = [first, again, chips()];
  }
  // the question's prompt in English asks for the citation
  {
    const h = harness({ locale: 'en-US', scripts: [[qInit, ev({ type: 'result', subtype: 'success', is_error: false, result: 'ok', session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('Why?'); pane.send.click(); await settle(400);
    facts.citePromptEn = h.log.stdin[0];
  }
  // an answer drawn live gets its chips once the sentences are read; citations beside link-like brackets are chips, and none sits in a link
  {
    const sentences = JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] });
    const reply = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                   said('见 [链接 [#12]](https://x.org) 与 [#12]'),
                   ev({ type: 'result', subtype: 'success', is_error: false, result: '…', session_id: 'S1' })];
    const h = harness({ scripts: [reply], logs: { '/data/tmp/scholium/ATT1/sentences.json': sentences } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('q'); pane.send.click(); await settle(500);
    const answer = pane.list.children.at(-1).children.find(c => c.className.startsWith('scholium-entry text'));
    const all = n => [n, ...(n.children || []).flatMap(all)];
    const inLink = all(answer).filter(n => n.className === 'scholium-link').flatMap(all).filter(n => n.className === 'scholium-cite').length;
    facts.citeInLink = { inLink, chips: all(answer).filter(n => n.className === 'scholium-cite').length };
  }
  // no sentences.json: the id stays text
  {
    const reply = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                   said('原句 [#12]'),
                   ev({ type: 'result', subtype: 'success', is_error: false, result: '…', session_id: 'S1' })];
    const h = harness({ scripts: [reply] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('q'); pane.send.click(); await settle(500);
    const answer = pane.list.children.at(-1).children.find(c => c.className.startsWith('scholium-entry text'));
    facts.citeNone = answer.textContent;
  }
  // locate: the reader opens at the sentence's position (a tab there but not loaded is selected with it); a sentence
  // without a position opens its page
  {
    const RECTS = [[72.5, 600.1, 300, 612.4], [72.5, 588, 210.25, 600]];
    const run = async (kind, arg) => {
      const h = harness({});
      h.runner.start('x');
      await h.pane(h.item1); await settle(40);
      if (kind) h.log.readerKind = kind;
      const logged = [];
      h.zotero.debug = m => logged.push(m);
      let error = null;
      try { await h.runner.locate('ATT1', arg === undefined ? { id: 1, page: 4, text: 'A.', rects: RECTS } : arg); } catch (e) { error = String(e); }
      await settle(20);
      return { opened: h.log.readerOpened.map(o => o.location), navigated: h.log.navigated, finds: h.log.finds, error, logged };
    };
    facts.locate = { normal: await run(null), old: await run(null, { id: 1, page: 4, text: 'A.', rects: null }), unloaded: await run('unloaded'),
                     rejects: await run('rejects'), nulls: await run(null, null), nopage: await run(null, { id: 1, text: 'A.', rects: RECTS }) };
  }
  // the positions in sentences.json: only arrays of four finite numbers are kept; a sentence left without any opens the
  // page only
  {
    const SPATH = '/data/tmp/scholium/ATT1/sentences.json';
    const sentences = JSON.stringify({ sentences: [
      { id: 1, page: 4, text: 'A.', rects: [[1, 2, 3, 4], [5.5, 6, 7, 8.25]] },
      { id: 2, page: 4, text: 'B.', rects: [[1, 2, 3], [1, 2, 3, 4, 5], 'x', null, [1, 2, 'x', 4], [1, 2, null, 4], [1, 2, 'INF', 4], { 0: 1, 1: 2, 2: 3, 3: 4 }] },
      { id: 3, page: 4, text: 'C.', rects: [[1, 2, 3, 4], [1, 2, 3]] },
      { id: 4, page: 4, text: 'D.', rects: 'x' },
      { id: 5, page: 4, text: 'E.', rects: [] },
      { id: 6, page: 4, text: 'F.' }] }).replace('"INF"', '1e999');
    const h = harness({ logs: { [SPATH]: sentences } });
    h.runner.start('x');
    await h.pane(h.item1); await settle(40);
    await h.runner.loadCitations('ATT1');
    const map = h.runner.citations.get('ATT1').map;
    const rects = [1, 2, 3, 4, 5, 6].map(id => map.get(id).rects);
    await h.runner.locate('ATT1', map.get(2)); await settle(20);
    await h.runner.locate('ATT1', map.get(3)); await settle(20);
    facts.citeRects = { rects, opened: h.log.readerOpened.map(o => o.location) };
  }
  // a page whose label is not its number: the prompt and the history name the PDF's page, the prompt the label beside it;
  // the box and the transcript show the label. An update hands the label over with the quote
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.selection(PASSAGE, 8, '312')[0].click(); await settle(10);
    const box = pane.quoteBox.children[0].textContent;
    pane.input.type('这里说什么？'); pane.send.click(); await settle(400);
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    const shown = pane.list.children.at(-1).children[0];
    const en = harness({ locale: 'en-US' });
    const carried = { jobs: [{ key: 'ATT1', libraryID: 1, agent: 'claude', say: '问', kind: 'chat', conv: null, quote: { text: 'A.', page: '9', label: '312' } }],
                      paused: null, held: [] };
    const h3 = harness({ gateFirst: true, prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify(carried) } });
    h3.runner.start('x', true); await settle(200);
    const restored = (h3.runner.job ? h3.runner.job.source : h3.runner.queue[0] || {}).quote || null;
    h3.runner.cancel(); await settle(100);
    facts.pageLabel = { box, quote: convLines(h).find(l => l.subtype === 'prompt').quote, turn: log.turns[0].quote,
                        told: h.log.stdin[0].includes('用户引用了第 9 页（页码 312）的这段原文：\n> ' + PASSAGE + '\n\n这里说什么？'),
                        shown: shown.children[0].textContent, history: h.runner.historyParts(log.turns).whole[0].user,
                        en: en.runner.said({ say: 'Why?', quote: { text: 'A.', page: '9', label: '312' } }),
                        same: h.runner.said({ say: '问', quote: { text: 'A.', page: '4' } }), restored };
  }
  // a quote stays with the section's item: the section drawn again for another item has none
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(10);
    const section = h.log.sections[0];
    section.onRender({ doc: h.paneDoc, body: p.body, item: h.item1 }); await settle(10);
    const same = (h.runner.panes.get(p.body).quote || {}).text || null;
    section.onItemChange({ item: h.item2, setEnabled() {} });
    section.onRender({ doc: h.paneDoc, body: p.body, item: h.item2 }); await settle(10);
    facts.quoteItem = { same, other: h.runner.panes.get(p.body).quote || null };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


PASSAGE = "We propose a kernel that is invariant to rotations."


def test_ask_about_a_selection(facts):
    s = facts["selection"]
    assert s["label"] == "问 Scholium"
    assert s["quoted"] == {"tab": "chat", "box": "p.4 · " + PASSAGE}
    assert s["cleared"] == 1, "the selection popup closes: the view's selection is cleared"
    assert s["onAnnotate"] is True and s["back"] is False
    assert s["after"] is True
    assert "用户引用了第 4 页的这段原文：\n> " + PASSAGE + "\n\n这个核为什么不变？" in s["stdin"]
    assert s["quote"] == {"text": PASSAGE, "page": "4"}
    assert s["shown"] == ["scholium-prompt-quote", "p.4 · " + PASSAGE, "这个核为什么不变？"]
    assert s["removed"] == [True, None]
    assert s["drop"] == ["scholium-button quiet glyph close", "不引用这段"], "its ✕ is the close icon, its words its tooltip"


def test_a_selection_without_text_or_page_label(facts):
    s = facts["selection"]
    assert s["empty"] == 0
    assert s["noLabel"] == "p.7 · No label."


def test_the_log_keeps_the_quote_with_the_turn(facts):
    s = facts["selection"]
    assert s["turn"] == {"text": PASSAGE, "page": "4"}
    assert s["history"] == '[p.4] "' + PASSAGE + '"\n这个核为什么不变？'


def test_a_passage_chosen_before_the_section_is_drawn_waits_for_it(facts):
    p = facts["pending"]
    assert p["waiting"] == {"text": PASSAGE, "page": "4"}
    assert p["tab"] == "chat" and p["box"] == "p.4 · " + PASSAGE and p["left"] == 0
    assert p["again"] == {"text": PASSAGE, "page": "4"}


def test_the_popup_listener_comes_and_goes_with_the_plugin(facts):
    assert facts["listener"] == {"had": True, "after": False}


def test_a_queued_message_keeps_its_quote_through_an_update(facts):
    q = facts["queuedQuote"]
    quote = {"text": PASSAGE, "page": "4"}
    assert q["queued"] == [quote] and q["cleared"] is True
    assert ["追问二", quote] in q["carried"]
    assert q["restored"] == [["追问二", quote]]
    assert ["追问二", quote] in q["prompts"]
    assert q["stdin"] is True


def test_retry_sends_the_quote_again(facts):
    r = facts["retry"]
    assert r["stdin"] == [True, True]
    assert r["quotes"][0] == {"text": PASSAGE, "page": "4"}


def test_a_selection_made_while_the_paper_runs_waits_in_the_box(facts):
    assert facts["steerKeeps"] == {"quote": {"text": PASSAGE, "page": "4"}, "shown": True}


def test_the_prompt_node_keeps_its_structure_without_a_quote(facts):
    assert facts["plainPrompt"] == ["scholium-entry prompt", 1, "问"]
    assert facts["quotedPrompt"] == [[["div", "scholium-prompt-quote", "p.2 · T"], ["span", "scholium-content", "问"]]]
    assert "flex-direction: column" in css_rules()[".scholium-entry.prompt"], "the quote above the words, not beside them"
    e = facts["entry"]
    assert e[0]["quote"] == {"text": "T", "page": "2"} and "quote" not in e[1]
    assert facts["said"][0] == "用户引用了第 2 页的这段原文：\n> a\n> b\n\n问" and facts["said"][1] == "问"


def test_revealing_the_section(facts):
    r = facts["reveal"]
    scroll = ["scroll", "scholium-pane"]
    assert r["collapsed"] == {"steps": [scroll + [False, True]], "open": True, "collapsed": False, "quote": "4"}
    assert r["open"]["steps"] == [scroll + [False, True]] and r["open"]["open"] is True
    assert r["noContext"]["steps"] == [scroll + [None, True]] and r["noContext"]["open"] is True
    for k in ("scrollThrows", "noScroll"):
        assert r[k]["open"] is True and r[k]["quote"] == "4"
    assert r["scrollThrows"]["steps"] == [] and r["noScroll"]["steps"] == []
    assert r["bare"] == "4"


def test_a_queued_row_steered_tells_the_agent_the_passage(facts):
    f = facts["steerQueuedQuote"]
    assert len(f["steers"]) == 1
    assert PASSAGE in f["steers"][0] and "只看第 3 节" in f["steers"][0] and "用户引用了第 4 页" in f["steers"][0]
    assert f["box"] == [None, True]
    assert "再看" in f["sent"] and "Second." in f["sent"] and "用户引用了第 1 页" in f["sent"]
    assert f["lines"] == [["只看第 3 节", {"text": PASSAGE, "page": "4"}], ["再看", {"text": "Second.", "page": "1"}]]
    assert f["entries"] == f["lines"]
    assert f["user"].endswith('[p.4] "' + PASSAGE + '"\n只看第 3 节\n\n[p.1] "Second."\n再看')
    assert f["node"] == [["scholium-prompt-quote", "p.1 · Second."], ["scholium-content", "再看"]]


def test_given_back_words_bring_their_quote(facts):
    f = facts["giveBack"]
    assert f["back"] == ["问", {"text": PASSAGE, "page": "4"}, False]
    assert f["other"] == ["又问", "mine"]


def test_the_quote_goes_with_the_chat_only(facts):
    f = facts["annotateNoQuote"]
    assert f == {"told": False, "sent": 1, "kind": "annotate", "kept": "4"}


def test_a_waiting_quote_brings_the_chat_tab(facts):
    assert facts["pendingTab"] == ["chat", {"text": "T", "page": "9"}]


def test_the_words_of_an_english_user_go_with_the_passage_in_english(facts):
    assert facts["english"] == [[True, False], [False, True]]


def test_the_passage_goes_to_the_section_of_the_reader_window_and_paper(facts):
    assert facts["paneFor"] == {"a": "4", "b": None, "c": None}


def test_the_passage_goes_to_the_readers_own_section_not_the_librarys(facts):
    f = facts["readerPane"]
    assert f["own"] == [None, "4"], "the library's section behind the reader's tab is not the reader's"
    assert f["waits"] == [None, "1"] and f["drawn"] == "1" and f["library"] is None, "the passage waits for the reader's section"
    assert f["steps"] == [["scholium-pane", True]], "the reader's section is opened and scrolled to, so that Zotero draws it"


def test_steering_an_annotation_run_takes_no_quote(facts):
    f = facts["annotateSteerNoQuote"]
    assert f == {"steers": ["也看第 5 页"], "kept": "4"}


def test_a_conversation_that_is_no_questions_gets_the_passage(facts):
    f = facts["nonAsking"]
    assert f == {"resumed": True, "told": True, "question": False}





def test_a_selection_without_a_page_is_quoted_without_one(facts):
    f = facts["noPage"]
    assert f["box"] == PASSAGE and f["shown"] == PASSAGE
    assert "用户引用了这段原文：\n> " + PASSAGE + "\n\n为什么" in f["stdin"] and "页" not in f["stdin"].split("用户的问题：")[1]
    assert f["quote"] == {"text": PASSAGE, "page": ""}
    assert f["said"] == ["用户引用了这段原文：\n> a\n\n问"] and f["saidEn"] == "The user quotes this passage:\n> a\n\nQ"
    assert f["history"] == '"' + PASSAGE + '"\n为什么'


def test_the_english_follow_up_of_a_conversation_that_is_no_questions_gets_the_passage(facts):
    assert facts["nonAskingEn"] is True


def test_sentence_citations(facts):
    c = facts["cites"]
    assert c["text"] == "核在旋转下不变 p.4，见附录 [#999]。"
    assert c["chip"] == "p.4" and c["id"] == "12" and c["head"] == ["第 4 页", "定位 ↗"]
    assert c["sentence"] == "We propose a kernel that is invariant to rotations."
    assert c["opened"] == {"position": {"pageIndex": 3, "rects": [[72, 600, 300, 612]]}}
    assert c["viaLocate"] == [True, 1] and c["viaChip"] == [2, True]
    assert c["opens"] == [c["opened"]] * 2 and c["navigated"] == [], "the chip as Locate; the reader goes there as it opens"
    assert "[#123]" in c["prompt"] and "sentences.json" in c["prompt"]


RECTS = [[72.5, 600.1, 300, 612.4], [72.5, 588, 210.25, 600]]


def test_locate_opens_the_reader_at_the_sentence(facts):
    n = facts["locate"]["normal"]
    assert n["opened"] == [{"position": {"pageIndex": 3, "rects": RECTS}}] and n["error"] is None and n["logged"] == []
    assert n["navigated"] == [] and n["finds"] == [], "no navigation of its own, no find"


def test_locate_of_a_sentence_without_a_position_opens_the_page(facts):
    r = facts["locate"]["old"]
    assert r["opened"] == [{"pageIndex": 3}] and r["navigated"] == [] and r["finds"] == []
    assert r["error"] is None and r["logged"] == []


def test_locate_selects_a_tab_not_loaded_with_the_position(facts):
    r = facts["locate"]["unloaded"]
    assert r["opened"] == [{"position": {"pageIndex": 3, "rects": RECTS}}] and r["navigated"] == []
    assert r["error"] is None and r["logged"] == []


def test_locate_survives_a_reader_that_does_not_open(facts):
    r = facts["locate"]["rejects"]
    assert r["error"] is None and r["opened"] == [] and r["navigated"] == []
    assert len(r["logged"]) == 1 and "no reader" in r["logged"][0]


def test_locate_without_a_sentence_or_page_opens_nothing(facts):
    for k in ("nulls", "nopage"):
        r = facts["locate"][k]
        assert r["error"] is None and r["opened"] == [] and r["navigated"] == []


def test_positions_other_than_four_numbers_are_dropped(facts):
    f = facts["citeRects"]
    assert f["rects"] == [[[1, 2, 3, 4], [5.5, 6, 7, 8.25]], None, [[1, 2, 3, 4]], None, None, None]
    assert f["opened"] == [{"pageIndex": 3}, {"position": {"pageIndex": 3, "rects": [[1, 2, 3, 4]]}}], \
        "a sentence left without a position opens its page"


def test_the_card_stays_while_the_pointer_is_on_the_chip_or_the_card(facts):
    assert facts["cites"]["stays"] is True and facts["cites"]["closed"] is True


def test_sentences_are_read_again_only_when_the_file_changed(facts):
    assert facts["cites"]["reads"] == [True, 0, 1] and facts["cites"]["again"] == "p.5"


def test_citations_beside_link_like_brackets_are_chips_and_none_sits_in_a_link(facts):
    assert facts["citeInLink"] == {"inLink": 0, "chips": 2}


def test_an_answer_without_sentences_keeps_the_ids_as_text(facts):
    assert facts["citeNone"] == "原句 [#12]"


def test_a_changed_size_with_the_same_time_is_read_again(facts):
    assert facts["cites"]["bySize"] == "p.6"


def test_a_chip_hovered_under_another_layer_leaves_it_open(facts):
    assert facts["cites"]["layer"] == ["settings", "settings"]


def test_the_annotation_tab_answers_have_chips(facts):
    assert facts["citeAnnotation"] == ["p.4"]


def test_a_running_answer_has_chips(facts):
    assert facts["citeLive"] == [True, ["p.4"], ["p.7"]]


def test_the_draft_survives_the_redraw_for_new_sentences(facts):
    assert facts["citeDraft"] == [["p.8"], True, True]


def test_a_sentences_file_that_does_not_parse_is_read_once_until_it_changes(facts):
    assert facts["citeBroken"] == [1, 1, ["p.4"]]


def test_a_sentences_file_that_cannot_be_read_is_tried_again(facts):
    assert facts["citeUnreadable"] == [[True, []], 1, ["p.4"]]


def test_the_english_question_prompt_asks_for_sentence_numbers(facts):
    p = facts["citePromptEn"]
    assert "put its sentence number after it as [#123] (several: [#12][#15])" in p
    assert "/data/tmp/scholium/ATT1/sentences.json --out /data/tmp/scholium/ATT1/sentences.txt" in p


def test_a_quote_names_the_pdf_page_and_shows_its_label(facts):
    f = facts["pageLabel"]
    assert f["box"] == "p.312 · " + PASSAGE and f["shown"] == "p.312 · " + PASSAGE
    assert f["quote"] == {"text": PASSAGE, "page": "9", "label": "312"} and f["turn"] == f["quote"]
    assert f["told"] is True
    assert f["history"] == '[p.9] "' + PASSAGE + '"\n这里说什么？'
    assert f["en"] == "The user quotes this passage from page 9 (page label 312):\n> A.\n\nWhy?"
    assert f["same"] == "用户引用了第 4 页的这段原文：\n> A.\n\n问"
    assert f["restored"] == {"text": "A.", "page": "9", "label": "312"}


def test_a_quote_stays_only_with_its_item(facts):
    assert facts["quoteItem"] == {"same": PASSAGE, "other": None}
