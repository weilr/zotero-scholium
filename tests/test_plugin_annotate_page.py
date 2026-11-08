"""The annotation sessions and the annotation tab: an annotation opens a session of its own, apart from the chat; words
on the annotation tab continue it; runs, waits and stops are of a tab's kind."""
import re

import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const DIR = '/data/tmp/scholium/ATT1/conversations/';
  const annotLogs = (h, key = 'ATT1') => Object.keys(h.log.writes).filter(k => k.startsWith(`/data/tmp/scholium/${key}/conversations/annotate-`));
  const idOf = path => path.split('/').pop().slice(0, -'.jsonl'.length);
  // an annotation session logged before, as the paper's index names it
  const SESSION = 'annotate-claude-20261030-101010';
  const sessionLogs = () => ({
    [DIR + SESSION + '.jsonl']: ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '批注这篇', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '批注这篇', annotate: true, extra: '' })
      + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' }) + said('批注好了')
      + ev({ type: 'result', subtype: 'success', is_error: false, result: '批注好了', session_id: 'A0' }),
    [DIR + 'index.json']: JSON.stringify({ current: {}, titles: {}, annotation: { claude: SESSION } }),
  });

  // an annotation opens a session of its own: its own log and index entry, out of the chat's history; the chat goes on
  // where it was; words on the annotation tab continue the annotation session
  {
    const chat = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题一', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '问题一', question: true })
      + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'C0' }) + said('回答一')
      + ev({ type: 'result', subtype: 'success', is_error: false, result: '回答一', session_id: 'C0' });
    const edit = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), said('改好了'),
                  ev({ type: 'result', subtype: 'success', is_error: false, result: '改好了', session_id: 'S1' })];
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), edit], logs: { [CONV1]: chat } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const chatBefore = h.log.writes[CONV1];
    pane.tabAnnotate.click(); await settle(10);
    pane.annotGo.click(); await settle(600);
    const dir = '/data/tmp/scholium/ATT1/conversations/';
    const annotPath = Object.keys(h.log.writes).find(k => k.startsWith(dir + 'annotate-'));
    const annotConv = annotPath && annotPath.slice(dir.length, -'.jsonl'.length);
    const index = JSON.parse(h.log.writes[dir + 'index.json']);
    const annotShown = [pane.annot.shownConv === annotConv, pane.annot.live, pane.annot.list.children.map(c => c.className)];
    pane.tabChat.click(); await settle(50);
    pane.historyButton.click(); await settle(50);
    const historyRows = pane.popover.node.children.filter(r => r.className.startsWith('scholium-history-row')).length;
    h.runner.closePopover(pane);
    pane.tabAnnotate.click(); await settle(10);
    pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(400);
    const lines = h.log.writes[annotPath].trim().split('\n').map(l => JSON.parse(l));
    facts.annotSession = {
      annotConv, index, prompt: h.log.stdin[0], chatShown: pane.shownConv, chatSame: h.log.writes[CONV1] === chatBefore, historyRows,
      resumed: h.log.calls.at(-1).opts.arguments[h.log.calls.at(-1).opts.arguments.indexOf('--resume') + 1],
      annotPrompts: lines.filter(l => l.subtype === 'prompt').map(l => [l.text.split('\n')[0], !!l.annotate]),
      codexAgent: h.runner.convAgent('annotate-codex-20261030-101010'), chatAgent: h.runner.convAgent('codex-20261001-120000'),
      annotShown,
    };
    // several papers from the menu: a session each
    const g = harness({});
    g.runner.start('x');
    await g.runner.annotate([g.item1, g.item2]); await settle(1500);
    facts.annotSession.batch = Object.keys(g.log.writes).filter(k => /\/conversations\/annotate-claude-/.test(k)).map(k => k.split('/')[4]).sort();
  }

  // the annotation tab of a section drawn later shows the chosen agent's latest session, read from the paper's index; the
  // other agent has none; a session whose log is gone is none
  {
    const h = harness();
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(600);
    const id = idOf(annotLogs(h)[0]);
    const h2 = harness({ logs: ours(h) });
    h2.runner.start('x');
    const p = await h2.pane(h2.item1); await settle(40);
    const pane = p.pane();
    const reread = { shown: pane.annot.shownConv, runs: pane.annot.list.children.map(c => c.className), chat: pane.shownConv,
                     intro: pane.annot.list.children.includes(pane.annotIntro) };
    pane.agent.change('codex'); await settle(60);
    const codex = { shown: pane.annot.shownConv, intro: pane.annot.list.children.includes(pane.annotIntro) };
    const without = ours(h);
    delete without[annotLogs(h)[0]];
    const h3 = harness({ logs: without });
    h3.runner.start('x');
    const q = await h3.pane(h3.item1); await settle(40);
    const gone = { shown: q.pane().annot.shownConv, intro: q.pane().annot.list.children.includes(q.pane().annotIntro),
                   conv: await h3.runner.annotationConv('ATT1', 'claude') };
    facts.annotShown = { id, reread, codex, gone };
  }

  // the paper's chat runs: an annotation waits behind it; the agent stays as it is while either goes
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(200);        // a chat run, held open
    pane.tabAnnotate.click(); await settle(10);
    const before = { busy: pane.busy, go: pane.annotGo.disabled, agent: pane.agent.disabled };
    pane.annotGo.click(); await settle(100);
    facts.annotBehindChat = { before, queue: h.runner.queue.map(j => [j.att.key, j.kind, !!j.annotate]), running: h.runner.job && h.runner.job.source.kind,
                              busy: pane.busy, agent: pane.agent.disabled, stop: [!pane.send.hidden, pane.send.textContent, pane.annotGo.hidden] };
    h.runner.cancel(); await settle(800);
    facts.annotBehindChat.after = { calls: h.log.calls.length, sessions: annotLogs(h).length };
  }

  // an annotation runs: the chat tab is not busy (its history, ＋ and messages work, a message waits behind the
  // annotation), the annotation tab is; the agent stays as it is
  {
    const h = harness({ gateFirst: true, logs: { [CONV1]: SCRIPT.slice(0, 1).concat([LAST, RESULT]).join('') } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); pane.annotGo.click(); await settle(200);       // an annotation, held open
    const annotTab = { busy: pane.busy, round: pane.send.textContent, agent: pane.agent.disabled };
    pane.tabChat.click(); await settle(10);
    const chatTab = { busy: pane.busy, round: pane.send.textContent, agent: pane.agent.disabled, newChat: pane.newChat.disabled,
                      history: pane.historyButton.disabled, shown: pane.shownConv };
    const rowOf = () => pane.popover.node.children.find(r => r.className.startsWith('scholium-history-row'));
    pane.newChat.click(); await settle(50);
    const afterNew = pane.shownConv;
    pane.historyButton.click(); await settle(50);
    rowOf().children[0].click(); await settle(50);                           // the conversation opened again
    const reopened = pane.shownConv;
    pane.historyButton.click(); await settle(50);
    rowOf().children[2].click(); await settle(50);                           // deleted, then brought back
    const deleted = [h.runner.deleting.size, pane.shownConv];
    rowOf().children[1].click(); await settle(50);
    h.runner.closePopover(pane);
    const undone = [h.runner.deleting.size, pane.shownConv];
    pane.input.type('另一个问题'); pane.send.click(); await settle(50);
    facts.chatBesideAnnot = { annotTab, chatTab, afterNew, reopened, deleted, undone, queue: h.runner.queue.map(j => [j.att.key, j.kind, j.conv]),
                              input: pane.input.value };
    h.runner.cancel(); await settle(800);
    facts.chatBesideAnnot.answered = h.log.stdin.some(t => t.includes('另一个问题'));
  }

  // the context ring shows the context of the run its tab shows: the chat's own while an annotation runs, the
  // annotation's on its tab; so does the ring's layer, also in the moment a run starts
  {
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(400);       // a chat run, finished; the chat shows its run
    const chatLive = pane.live;
    pane.context = { used: 100000, window: 1000000 };
    let hold = true, release = null;
    const realApplied = h.runner.readApplied.bind(h.runner);
    h.runner.readApplied = async k => { if (hold) { hold = false; await new Promise(r => { release = r; }); } return realApplied(k); };
    pane.tabAnnotate.click(); pane.annotGo.click(); await settle(50);        // an annotation starts…
    pane.tabChat.click(); await settle(5);
    const starting = pane.ring.hidden ? null : pane.ring.title;
    release(); await settle(200);                                            // …and runs, held open
    h.runner.job.context = { used: 300000, window: 1000000 };
    h.runner.paintPane(pane);
    const chatRing = pane.ring.hidden ? null : pane.ring.title;
    pane.ring.click();
    const chatLayer = pane.popover && pane.popover.node.children[0].textContent;
    h.runner.closePopover(pane);
    pane.tabAnnotate.click(); await settle(5);
    const annotRing = pane.ring.hidden ? null : pane.ring.title;
    pane.ring.click();
    const annotLayer = pane.popover && pane.popover.node.children[0].textContent;
    h.runner.closePopover(pane);
    facts.ringByTab = { chatLive, starting, chatRing, chatLayer, annotRing, annotLayer };
    h.runner.cancel(); await settle(300);
  }

  // the steps a reader opened belong to the session shown: they stay while it goes on, and go when another session or
  // another agent's is shown
  {
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), SCRIPT.concat([LAST, RESULT]), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); pane.annotGo.click(); await settle(600);      // a first session, finished
    const fold = () => pane.annot.list.children[0].children.find(c => c.className === 'scholium-fold').children[0];
    fold().click(); await settle(5);                                         // its steps opened
    const opened = pane.annot.foldOpen.size;
    pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(600);   // the session goes on
    const same = [pane.annot.foldOpen.size, fold().textContent.endsWith('⌄')];
    pane.agent.change('codex'); await settle(60);
    pane.agent.change('claude'); await settle(60);
    const back = [pane.annot.foldOpen.size, fold().textContent.endsWith('›')];
    fold().click(); await settle(5);
    pane.annotGo.click(); await settle(200);                                 // a new session
    facts.foldBySession = { opened, same, back, fresh: pane.annot.foldOpen.size, live: pane.annot.live };
    h.runner.cancel(); await settle(300);
  }

  // a stop on a tab ends that tab's run or wait: the other tab's waiting message stays
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    await h.runner.annotate([h.item2]); await settle(100);                  // another paper runs
    pane.input.type('一个问题'); pane.send.click(); await settle(50);        // this paper's chat waits
    pane.tabAnnotate.click(); pane.annotGo.click(); await settle(50);        // and its annotation
    const before = h.runner.queue.map(j => [j.att.key, j.kind]);
    const round = pane.send.textContent;
    pane.send.click(); await settle(50);                                     // ■ on the annotation tab
    const afterAnnot = h.runner.queue.map(j => [j.att.key, j.kind]);
    pane.tabChat.click(); await settle(5);
    pane.send.click(); await settle(50);                                     // ■ on the chat tab
    facts.stopByKind = { before, round, afterAnnot, afterChat: h.runner.queue.map(j => [j.att.key, j.kind]), running: h.runner.job && h.runner.job.key };
    h.runner.cancel(); await settle(300);
  }
  // a chat that met the usage limit waits with its run begun: the stop of the annotation waiting behind it leaves it
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(300);
    const chat = convs(h)[0];
    pane.tabAnnotate.click(); pane.annotGo.click(); await settle(50);
    const before = h.runner.queue.map(j => [j.kind, h.runner.started(j)]);
    pane.send.click(); await settle(50);
    facts.stopBesideLimit = { before, after: h.runner.queue.map(j => j.kind), paused: !!h.runner.paused,
                              ends: h.log.writes[chat].trim().split('\n').map(l => JSON.parse(l)).filter(l => l.subtype === 'end').length };
    h.runner.stop();
  }

  // the words typed on each tab stay with it, and on the annotation tab with the agent's session
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问对话的半句');
    pane.tabAnnotate.click(); await settle(5);
    const onAnnot = pane.input.value;
    pane.input.type('批注要求的半句');
    pane.tabChat.click(); await settle(5);
    const backChat = pane.input.value;
    pane.tabAnnotate.click(); await settle(5);
    const backAnnot = pane.input.value;
    pane.agent.change('codex'); await settle(60);
    const codex = pane.input.value;
    pane.agent.change('claude'); await settle(60);
    facts.unsentByTab = { onAnnot, backChat, backAnnot, codex, claude: pane.input.value };
    // words put in the box without typing (a quote) stay with their tab as well
    pane.input.value = '放进去的话';
    pane.tabChat.click(); await settle(5);
    pane.tabAnnotate.click(); await settle(5);
    facts.unsentByTab.put = pane.input.value;
  }
  // an annotation started from the menu while the tab shows a session: the box is the new session's, the words typed to
  // the old one stay with it
  {
    const h = harness({ gateFirst: true, logs: sessionLogs() });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('给上一次的话');
    await h.runner.annotate([h.item1]); await settle(100);
    const during = pane.input.value;
    h.runner.cancel(); await settle(300);
    facts.unsentPerSession = { during, kept: h.runner.unsent.get(`1/ITEM1/annotate/claude/${SESSION}`) || null };
  }
  // the send key on the annotation tab: a new annotation with the box's words while the tab shows no session
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('只标方法部分');
    const pressed = key(pane.input, { key: 'Enter', ctrlKey: true }).defaultPrevented;
    await settle(600);
    const path = annotLogs(h)[0];
    facts.sendKeyAnnot = { pressed, prompt: path && h.log.writes[path].trim().split('\n').map(l => JSON.parse(l)).find(l => l.subtype === 'prompt'),
                           cleared: pane.input.value };
  }
  // words typed while a new session starts go on with it
  {
    const h = harness({ holdDirs: true, script: SCRIPT.concat(['WAIT']) });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); pane.annotGo.click(); await settle(100);      // the run waits for its folder
    pane.input.type('改短一点');
    h.log.releaseDir(); await settle(100);                                   // its session begins
    const shown = pane.annot.shownConv;
    const section = h.log.sections[0];                                       // the section drawn anew
    section.onRender({ doc: h.paneDoc, body: p.body, item: h.item1 });
    await section.onAsyncRender({ body: p.body }); await settle(20);
    const again = p.pane();
    const rerendered = [again !== pane, again.tab, again.input.value];
    again.tabChat.click(); await settle(5);
    again.tabAnnotate.click(); await settle(5);
    facts.unsentIntoSession = { shown: !!shown && shown.startsWith('annotate-claude-'), value: again.input.value, rerendered };
    h.runner.cancel(); await settle(300);
  }
  // words to the annotation session that did not reach the agent go back to the annotation tab's box
  {
    const h = harness({ claudeExists: false, logs: sessionLogs() });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    const shown = pane.annot.shownConv;
    pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(300);
    const back = pane.input.value;
    pane.tabChat.click(); await settle(5);
    const chat = pane.input.value;
    pane.tabAnnotate.click(); await settle(5);
    facts.givenBack = { shown, back, chat, again: pane.input.value };
  }

  // the annotation's line in its log carries the extra instructions, and so does its entry
  {
    const h = harness();
    h.runner.start('x');
    await h.runner.annotate([h.item1], { extra: '只标方法部分' }); await settle(600);
    const path = annotLogs(h)[0];
    const prompt = h.log.writes[path].trim().split('\n').map(l => JSON.parse(l)).find(l => l.subtype === 'prompt');
    const log = await h.runner.readLog('ATT1', idOf(path));
    facts.annotExtra = { line: [prompt.text, prompt.annotate, prompt.extra], entry: log.entries.find(e => e.kind === 'prompt'),
                         plain: h.runner.entries({ type: 'scholium', subtype: 'prompt', text: '一个问题', question: true }) };
  }
  // confirmed: no dialog before an annotation over the paper's Scholium annotations
  {
    const h = harness({ existing: [['zotero-scholium']], confirm: false });
    h.runner.start('x');
    const refused = await h.runner.annotate([h.item1]);
    const queued = await h.runner.annotate([h.item1], { confirmed: true }); await settle(600);
    facts.confirmed = { refused, queued, asked: h.log.confirms.length, sessions: annotLogs(h).length };
  }
  // words sent on the annotation tab without a session go with a new annotation as its extra wishes; they are not a question
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('只看第 3 页'); pane.send.click(); await settle(600);
    const path = annotLogs(h)[0];
    const lines = path ? h.log.writes[path].trim().split('\n').map(l => JSON.parse(l)) : [];
    facts.annotWords = { session: !!path, prompts: lines.filter(l => l.subtype === 'prompt').map(l => [l.text, !!l.question, !!l.annotate]),
                         chats: convs(h).filter(c => !c.includes('/annotate-')).length, chat: JSON.parse(h.log.writes[DIR + 'index.json']).chat || null };
  }

  // a section drawn while the paper's chat runs shows that run, and its annotation tab the session
  {
    const h = harness({ gateFirst: true, logs: sessionLogs() });
    h.runner.start('x');
    await h.runner.send(h.item1, '一个问题'); await settle(100);
    const p = await h.pane(h.item1); await settle(40);
    facts.annotBesideLiveChat = { chatLive: p.pane().live, annot: p.pane().annot.shownConv, runs: p.pane().annot.list.children.length };
    h.runner.cancel(); await settle(200);
  }
  // an annotation that starts while the tab reads its session is drawn as it runs
  {
    const h = harness({ gateFirst: true, logs: sessionLogs() });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    let release = null;
    const real = h.runner.annotationConv.bind(h.runner);
    h.runner.annotationConv = async (k, a) => { await new Promise(r => { release = r; }); return real(k, a); };
    const shown = h.runner.showAnnotation(pane);
    await h.runner.annotate([h.item1]); await settle(100);
    h.runner.annotationConv = real;
    release(); await shown; await settle(5);
    facts.annotRace = { live: pane.annot.live, conv: pane.annot.shownConv !== SESSION };
    h.runner.cancel(); await settle(200);
  }
  // a section being drawn while the paper's chat starts: the chat shows it, the annotation tab the session
  {
    const h = harness({ gateFirst: true, logs: sessionLogs() });
    h.runner.start('x');
    let release = null;
    const real = h.runner.currentConv.bind(h.runner);
    h.runner.currentConv = async k => { if (!release) await new Promise(r => { release = r; }); return real(k); };
    const drawing = h.pane(h.item1);
    for (let i = 0; i < 200 && !release; i++) await tick();
    await h.runner.send(h.item1, '一个问题'); await settle(100);
    release(); const p = await drawing; await settle(40);
    facts.annotBesideStartingChat = { chatLive: p.pane().live, annot: p.pane().annot.shownConv };
    h.runner.cancel(); await settle(200);
  }
  // an older reading of the annotation tab that ends late leaves what a newer one drew
  {
    const h = harness({ logs: sessionLogs() });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    let release = null;
    const real = h.runner.annotationConv.bind(h.runner);
    h.runner.annotationConv = async (k, a) => { if (!release) await new Promise(r => { release = r; }); return real(k, a); };
    const older = h.runner.showAnnotation(pane);                 // Claude Code's session, read slowly
    h.store.set('extensions.scholium.agent', 'codex');
    await h.runner.showAnnotation(pane);                         // Codex chosen meanwhile: none
    release(); await older; await settle(5);
    facts.annotLate = { shown: pane.annot.shownConv, intro: pane.annot.list.children.includes(pane.annotIntro) };
  }

  // the annotation tab's introduction is there only while it shows no session: not above a session drawn with the
  // section, nor above a run going on when the section is drawn
  {
    const kids = pane => ({ view: pane.annotView.children.map(c => c.className), list: pane.annot.list.children.map(c => c.className),
                            intro: pane.annot.list.children.includes(pane.annotIntro) || pane.annotView.children.includes(pane.annotIntro) });
    const h = harness({ logs: sessionLogs() });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.pane().tabAnnotate.click(); await settle(5);
    const withSession = kids(p.pane());
    const g = harness({ gateFirst: true });
    g.runner.start('x');
    await g.runner.annotate([g.item1]); await settle(200);
    const q = await g.pane(g.item1); await settle(40);
    q.pane().tabAnnotate.click(); await settle(5);
    const liveAtRender = kids(q.pane());
    g.runner.cancel(); await settle(300);
    const n = harness();
    n.runner.start('x');
    const r = await n.pane(n.item1); await settle(40);
    facts.introPlace = { withSession, liveAtRender, none: kids(r.pane()) };
  }
  // a section shows a run on its tab only: a run of the other kind that ends out of sight has its corner notices
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.see(true);
    const count = () => h.log.notices.length;
    let at = count();
    await h.runner.annotate([h.item1]); await settle(600);       // the chat tab is shown
    const annotOnChat = count() - at; at = count();
    pane.tabAnnotate.click(); await settle(5);
    await h.runner.annotate([h.item1]); await settle(600);       // its own tab is shown
    const annotOnAnnot = count() - at; at = count();
    await h.runner.send(h.item1, '一个问题'); await settle(600);   // a chat while the annotation tab is shown
    const chatOnAnnot = count() - at; at = count();
    pane.tabChat.click(); await settle(5);
    await h.runner.send(h.item1, '再问一句'); await settle(600);
    facts.noticeByTab = { annotOnChat, annotOnAnnot, chatOnAnnot, chatOnChat: count() - at };
  }
  // the outcome of each kind is kept apart: an annotation that ends leaves the chat's failure on the chat's state line
  {
    const failed = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }),
                    ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: '出错了', session_id: 'F1' }), 'EXIT:1'];
    const h = harness({ scripts: [failed, SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    await h.runner.send(h.item1, '一个问题'); await settle(400);
    const before = p.view('chat').state;
    await h.runner.annotate([h.item1]); await settle(600);
    facts.notesByKind = { before, after: p.view('chat').state, annotation: (h.runner.notes.get('ATT1/annotate') || {}).text || null };
  }
  // a chat that waits with its run begun, stopped on its tab: its state line says so
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('一个问题'); pane.send.click(); await settle(300);   // the usage limit: it waits
    const waiting = h.runner.queue.map(j => [j.kind, h.runner.started(j)]);
    pane.send.click(); await settle(200);                                  // ■
    facts.chatCancelledWait = { waiting, state: p.view().state, queue: h.runner.queue.length };
  }
  // words on the annotation tab go to the paper of its session, whichever PDF the chat shows
  {
    const h = harness({ secondPdf: true });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    await h.runner.annotate([h.item1]); await settle(600);      // a session of ATT1
    pane.shownKey = 'ATT3';                                       // the chat on the item's other PDF
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(400);
    facts.sendToTabsPaper = { resumed: h.log.calls.at(-1).opts.arguments.includes('--resume'),
                              other: Object.keys(h.log.writes).some(k => k.includes('/ATT3/conversations/')),
                              words: h.log.writes[annotLogs(h)[0]].includes('第 5 页那条译文改短') };
  }
  // an update hands over each waiting run with its kind; the new copy queues a paper's chat and annotation both
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    await h.runner.annotate([h.item2]); await settle(100);                  // another paper runs
    await h.runner.send(h.item1, '一个问题'); await h.runner.annotate([h.item1]); await settle(50);
    h.runner.stop(true); await settle(40);
    const carried = JSON.parse(h.store.get('extensions.scholium.carryOver'));
    const h2 = harness({ gateFirst: true, prefs: { 'extensions.scholium.carryOver': JSON.stringify(carried) }, logs: ours(h) });
    h2.runner.start('x', true); await settle(200);
    const restored = [h2.runner.job && [h2.runner.job.key, h2.runner.job.source.kind]].concat(h2.runner.queue.map(j => [j.att.key, j.kind]));
    h2.runner.cancel(); await settle(100); h2.runner.stop();
    // a chat of the paper runs in the new copy: its annotation is queued all the same
    const h3 = harness({ gateFirst: true, logs: ours(h) });
    h3.runner.start('x');
    await h3.runner.send(h3.item1, '另一个问题'); await settle(100);
    h3.store.set('extensions.scholium.carryOver', JSON.stringify({ jobs: carried.jobs.filter(j => j.key === 'ATT1' && j.kind === 'annotate') }));
    await h3.runner.restoreQueue();
    facts.handedKinds = { carried: carried.jobs.map(j => [j.key, j.kind]), restored, besideChat: h3.runner.queue.map(j => [j.att.key, j.kind]) };
    h3.runner.cancel(); await settle(100); h3.runner.stop();
  }

  // a button with this text inside a node
  const findButton = (node, text) => (node.tagName === 'button' && labelOf(node) === text ? node
    : (node.children || []).map(c => findButton(c, text)).find(Boolean) || null);
  const buttonsIn = (node, text) => (node.tagName === 'button' && labelOf(node) === text ? 1 : 0)
    + (node.children || []).reduce((n, c) => n + buttonsIn(c, text), 0);
  // the annotation tab: an introduction; while it runs, the six steps and what it does now; then the steps folded and a
  // card of the numbers counted in Zotero; Annotate again asks in place
  {
    const h = harness({ script: SCRIPT.concat(['HOLD', LAST, RESULT]), notes: [['zotero-scholium']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(20);
    const intro = { text: pane.annot.list.children[0].textContent, go: pane.annotGo.textContent, sendShown: !pane.send.hidden,
                    placeholder: pane.input.placeholder, confirmHidden: pane.confirmRow.hidden };
    pane.annotGo.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    pane.state.title = 'stale'; await new Promise(r => setTimeout(r, 40));   // the line's ticks keep its tooltip
    const run = () => pane.annot.list.children.at(-1);
    const during = { parts: run().children.map(c => c.className), go: pane.annotGo.hidden,
                     round: pane.send.textContent, sendShown: !pane.send.hidden,
                     live: run().children.find(c => c.className === 'scholium-fold').children[0].textContent,
                     step: h.runner.job.step, state: p.view().state, stateTitle: p.view().stateTitle };
    h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666'), h.ann('A2', 'highlight', '#ffd400'), h.ann('A3', 'underline', '#ff6666'),
                                   h.ann('A4', 'text', '#2ea8e5'), h.ann('A5', 'note', '#ffd400'), h.ann('U1', 'highlight', '#ff6666', [])];
    h.log.release(); await settle(400);
    const card = run().children.find(c => c.className === 'scholium-card');
    const after = { parts: run().children.map(c => c.className), title: card.children[0].textContent,
                    nums: card.children[1].children.map(n => [n.children[0].textContent, n.children[1].textContent]),
                    usage: card.children[2].textContent, go: pane.annotGo.textContent, placeholder: pane.input.placeholder,
                    sendShown: !pane.send.hidden, state: p.view().state,
                    counts: convLines(h, 'ATT1').filter(l => l.subtype === 'counts').map(({ type, subtype, at, ...rest }) => rest) };
    run().children.find(c => c.className === 'scholium-fold').children[0].click();   // the steps opened
    after.closing = run().children.find(c => c.className === 'scholium-fold').children[1].children.at(-1).textContent;
    pane.input.type('只批注第 3 页'); pane.annotGo.click(); await settle(20);
    const ask = { shown: !pane.confirmRow.hidden, text: pane.confirmRow.children.map(c => c.textContent), dialogs: h.log.confirms.length };
    pane.confirmRow.children[1].click(); await settle(20);          // 取消
    const cancelled = { hidden: pane.confirmRow.hidden, queued: h.runner.queue.length, kept: pane.input.value, erased: h.log.erased.length };
    pane.annotGo.click(); await settle(20);
    pane.confirmRow.children[2].click(); await settle(100);         // 替换
    const replaced = { erased: h.log.erased.slice(), trashed: h.log.trashed.slice(), left: h.att1.getAnnotations().map(a => a.key),
                       none: h.log.stdin.at(-1).includes('这篇论文目前没有本工具的注释。') };
    facts.annotPage = { intro, during, after, ask, cancelled, replaced, again: h.runner.job && h.runner.job.source.extra, dialogsAfter: h.log.confirms.length };
    h.runner.cancel(); h.log.release(); await settle(200);         // the second run held as the first
  }
  // the step the agent reached is in the state line's tooltip at once, not with its next line
  {
    const h = harness({ script: SCRIPT.slice(0, 11).concat(['HOLD'], SCRIPT.slice(11), [LAST, RESULT]) });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    facts.stepAtOnce = { step: h.runner.job.step, title: p.view().stateTitle };
    h.log.release(); await settle(300);
  }
  // a failed annotation: a red card with the reason and Retry, which starts it again with the same wishes
  {
    const failed = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }),
                    ev({ type: 'result', subtype: 'error_max_turns', is_error: true, result: '', session_id: 'F1' }), 'EXIT:1'];
    const h = harness({ scripts: [failed, SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); pane.input.type('只批注第 3 页'); pane.annotGo.click(); await settle(600);
    const card = pane.annot.list.children.at(-1).children.find(c => c.className.startsWith('scholium-card'));
    const failedCard = { cls: card.className, text: card.children[0].textContent, retry: labelOf(card.children.at(-1)),
                         parts: pane.annot.list.children.at(-1).children.map(c => c.className), state: p.view().state };
    card.children.at(-1).click(); await settle(600);
    facts.annotFailed = { failedCard, retried: h.log.stdin[1].includes('只批注第 3 页'), sessions: Object.keys(h.log.writes).filter(k => /annotate-claude-/.test(k)).length };
  }
  // no annotation session yet, but an earlier version wrote the paper's annotations: when, and by which agent
  {
    const at = new Date(2026, 9, 24, 10, 0).getTime();
    const h = harness({ logs: { '/data/tmp/scholium/ATT1/applied.json': JSON.stringify({ config: 'D:/x/config.json', agent: 'claude', conv: 'claude-run', at }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().tabAnnotate.click(); await settle(20);
    facts.annotApplied = p.pane().annot.list.children[0].children.map(c => c.textContent);
  }
  // the numbers: the core colour of the configuration that wrote the annotations; the warnings left as the closing words
  // say them, in English too, or nothing when they do not say
  {
    const ending = text => [said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1', num_turns: 3 })];
    const out = {};
    for (const [name, text, logs] of [['core', 'Done.\n' + SUMMARY, { '/data/c.json': JSON.stringify({ core_color: '#FFD400' }) }],
                                      ['english', 'Done. 30 highlights; remaining warnings: style_warnings: 2', {}],
                                      ['silent', 'Done.', {}],
                                      ['unplaced', 'Done.\n高亮 30 条，剩余警告：无法定位 2 句', {}],
                                      ['elsewhere', 'Dry run: no warnings.\n高亮 30 条，剩余警告：第 4 页“label”警告已接受', {}]]) {
      const h = harness({ script: SCRIPT.concat(ending(text)), logs });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      p.annotate();
      h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666'), h.ann('A2', 'highlight', '#ffd400'), h.ann('A3', 'underline', '#FFD400')];
      await settle(600);
      const card = p.pane().annot.list.children.at(-1).children.find(c => c.className === 'scholium-card');
      const line = convLines(h).find(l => l.subtype === 'counts') || {};
      out[name] = { core: line.core, warnings: line.warnings, title: card && card.children[0].textContent, usage: card && card.children[2].textContent };
    }
    facts.countsCases = out;
    const w = harness();
    facts.warningsTable = ['剩余警告：无', '高亮 3 条，剩余警告：无。', '剩余警告：没有', '剩余警告：无法定位 2 句', '剩余警告：没有找到第 2 页',
                           'remaining warnings: none', '30 highlights, remaining warnings: none.', 'No warnings.', 'no warnings\n剩余警告：label']
      .map(s => w.runner.warningsOf(s));
    // a count, as agents have written it in earlier logs
    facts.warningsCounted = [
      '高亮 25 条（核心 12 条），页边批注 7 条，笔记《Direct Preference Optimization》，剩余警告 1 条（第 8 页译文提到 "DPO" 未出现在原句中，属提示性质，已写入）。',
      '高亮 3 条，剩余警告2条：第 3 页译文偏长；第 5 页术语缺失。', '高亮 3 条，剩余警告 2 条。', '高亮 3 条，剩余警告 0 条。', '高亮 3 条，无剩余警告。',
      '25 highlights (12 core), 7 margin notes, note “DPO”, 1 remaining warning (page 8: “DPO” is not in the sentence).',
      '30 highlights, 2 remaining warnings.', '30 highlights, 0 remaining warnings.', '30 highlights, 2 remaining warnings: page 3 is long; page 5 lacks a term',
      '30 highlights, remaining warnings: 1 (page 8 translation is advisory).', '30 highlights, remaining warnings: 0.',
      '30 highlights, remaining warnings: 2 translation warnings on page 3',
    ].map(s => w.runner.warningsOf('Done.\n' + s));
  }
  // an annotation's second try after a failed connection, and its continuation after the usage limit, are drawn as the
  // annotation, with its card; the failure before them has no Retry
  {
    const parts = pane => pane.annot.list.children.map(r => r.children.map(c => c.className));
    const h = harness({ scripts: [[SCRIPT[0], ev({ type: 'result', subtype: 'success', is_error: true, result: 'API Error: Connection error.', session_id: 'S1' })],
                                  SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(300);
    const waiting = { parts: parts(p.pane()), retries: buttonsIn(p.pane().annot.list, '重试') };
    await new Promise(r => setTimeout(r, 60)); await settle(600);
    const cards = pane => pane.annot.list.children.flatMap(r => r.children).filter(c => /^scholium-card/.test(c.className)).map(c => c.className);
    const retried = { waiting, parts: parts(p.pane()), retries: buttonsIn(p.pane().annot.list, '重试'),
                      counts: convLines(h).filter(l => l.subtype === 'counts').length, cards: cards(p.pane()) };
    const limited = [LIMIT_HIT[0], ev({ type: 'result', subtype: 'success', is_error: true, result: 'You have hit your limit', session_id: 'S1' })];
    const g = harness({ scripts: [SCRIPT.slice(0, 3).concat(limited), SCRIPT.slice(3).concat([LAST, RESULT])] });
    g.runner.start('x');
    const q = await g.pane(g.item1); await settle(40);
    q.annotate(); await settle(300);
    const paused = { parts: parts(q.pane()), queued: g.runner.queue.length, retries: buttonsIn(q.pane().annot.list, '重试') };
    g.runner.resumeQueue(); await settle(600);
    facts.annotAgain = { retried, paused, continued: { parts: parts(q.pane()), retries: buttonsIn(q.pane().annot.list, '重试'),
                                                       counts: convLines(g).filter(l => l.subtype === 'counts').length, cards: cards(q.pane()) } };
  }
  // a failed message to the annotation session has the chat's Retry, which says it again in that session
  {
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' });
    const failed = [init, ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: '出错了', session_id: 'A0' }), 'EXIT:1'];
    const edit = [init, said('改好了'), ev({ type: 'result', subtype: 'success', is_error: false, result: '改好了', session_id: 'A0' })];
    const h = harness({ scripts: [failed, edit], logs: sessionLogs() });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(400);
    const last = pane.annot.list.children.at(-1);
    const button = findButton(last, '重试');
    const shown = { retry: !!button, card: last.children.some(c => /scholium-card/.test(c.className)) };
    if (button) button.click();
    await settle(400);
    const args = h.log.calls.at(-1).opts.arguments;
    facts.annotFollowRetry = { shown, calls: h.log.calls.length, resumed: args[args.indexOf('--resume') + 1],
                               answered: h.log.writes[DIR + SESSION + '.jsonl'].includes('改好了'),
                               chat: JSON.parse(h.log.writes[DIR + 'index.json']).chat || null, sessions: annotLogs(h).length };
  }
  // words of the annotation tab's kind without an annotation session go with a new annotation, as its extra wishes
  {
    const h = harness();
    h.runner.start('x');
    const sent = await h.runner.send(h.item1, '只看第 3 页', { kind: 'annotate' }); await settle(600);
    const paths = annotLogs(h);
    const lines = paths.length ? h.log.writes[paths[0]].trim().split('\n').map(l => JSON.parse(l)) : [];
    facts.sendAnnotWithout = { sent, sessions: paths.length, prompts: lines.filter(l => l.subtype === 'prompt').map(l => [l.text, !!l.annotate, l.extra || null]) };
  }
  // the annotation tab's button annotates the tab's paper, whichever PDF the chat shows
  {
    const h = harness({ secondPdf: true });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.shownKey = 'ATT3';                                       // the chat on the item's other PDF
    pane.tabAnnotate.click(); await settle(5);
    pane.annotGo.click(); await settle(600);
    facts.annotGoPaper = { att1: annotLogs(h, 'ATT1').length, att3: annotLogs(h, 'ATT3').length };
  }
  // the question in place belongs to the annotation tab: it goes when the chat is shown
  {
    const h = harness({ existing: [['zotero-scholium']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const atFirst = pane.confirmRow.hidden;
    pane.tabAnnotate.click(); pane.annotGo.click(); await settle(5);
    const asked = !pane.confirmRow.hidden, annotSend = !pane.send.hidden;
    pane.tabChat.click(); await settle(5);
    facts.confirmByTab = { atFirst, asked, chat: pane.confirmRow.hidden, queued: h.runner.queue.length, dialogs: h.log.confirms.length,
                           sends: [annotSend, !pane.send.hidden, pane.annotGo.hidden] };
  }
  // a long annotation whose first lines left the transcript is counted all the same
  {
    const h = harness();
    h.runner.MAX_ENTRIES = 4;
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(600);
    facts.countsLong = convLines(h).filter(l => l.subtype === 'counts').length;
  }
  // a failure while the run still goes is a line; the card comes once it ended
  {
    const h = harness({ script: [SCRIPT[0], ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: '出错了', session_id: 'S1' }), 'HOLD'] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    const parts = () => p.pane().annot.list.children.at(-1).children.map(c => c.className);
    const live = parts();
    h.log.release(); await settle(300);
    facts.failureWhileLive = { live, ended: parts() };
  }
  // the send key on the annotation tab without a session: its words with a new annotation, asked in place over the
  // paper's Scholium annotations; an empty box annotates as the button does
  {
    const h = harness({ existing: [['zotero-scholium']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('只看第 3 页');
    key(pane.input, { key: 'Enter', ctrlKey: true });
    await settle(20);
    const asked = { shown: !pane.confirmRow.hidden, dialogs: h.log.confirms.length, queued: h.runner.queue.length };
    const g = harness();
    g.runner.start('x');
    const q = await g.pane(g.item1); await settle(40);
    q.pane().tabAnnotate.click(); await settle(5);
    key(q.pane().input, { key: 'Enter', ctrlKey: true });
    await settle(600);
    facts.sendKeyInPlace = { asked, empty: { calls: g.log.calls.length, sessions: annotLogs(g).length } };
  }
  // a retry of words to the annotation session goes on in that session, whichever agent is chosen now
  {
    const edit = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' }), said('改好了'),
                  ev({ type: 'result', subtype: 'success', is_error: false, result: '改好了', session_id: 'A0' })];
    const h = harness({ scripts: [edit], logs: sessionLogs(), prefs: { 'extensions.scholium.agent': 'codex' } });
    h.runner.start('x');
    const sent = await h.runner.send(h.item1, '改短', { kind: 'annotate', retry: true, conv: SESSION, agent: 'claude' }); await settle(400);
    const args = h.log.calls.length ? h.log.calls[0].opts.arguments : [];
    facts.retryOtherAgent = { sent, calls: h.log.calls.length, codexCalls: h.log.codexCalls.length, resumed: args[args.indexOf('--resume') + 1] || null,
                              sessions: annotLogs(h).length };
  }
  // a run that fails before its log has a line of its own (no program) is no attempt of the turn before: no card and no
  // Retry, after an annotation as after words to the session; its words go back to the box
  {
    const out = {};
    const annotTurn = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '批注这篇', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '批注这篇\n附加要求：只看第 3 页', annotate: true, extra: '只看第 3 页' })
      + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' }) + said('批注好了')
      + ev({ type: 'result', subtype: 'success', is_error: false, result: '批注好了', session_id: 'A0' });
    const wordsTurn = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '改短', at: Date.now() - 30000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '改短' }) + said('改好了')
      + ev({ type: 'result', subtype: 'success', is_error: false, result: '改好了', session_id: 'A0' });
    for (const [name, log] of [['afterAnnotation', annotTurn], ['afterWords', annotTurn + wordsTurn]]) {
      const h = harness({ claudeExists: false, logs: { [DIR + SESSION + '.jsonl']: log,
                                                       [DIR + 'index.json']: JSON.stringify({ current: {}, titles: {}, annotation: { claude: SESSION } }) } });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      pane.tabAnnotate.click(); await settle(5);
      pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(300);
      const last = pane.annot.list.children.at(-1);
      out[name] = { parts: last.children.map(c => c.className), retries: buttonsIn(last, '重试'), box: pane.input.value };
    }
    facts.noProgramAfterTurn = out;
  }
  // words to the annotation session that write to Zotero: the state line names the step, as there is no list of steps
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 11).concat(['HOLD'])], logs: sessionLogs() });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('第 5 页那条译文改短'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    facts.wordsState = { state: p.view().state, title: p.view().stateTitle,
                         parts: pane.annot.list.children.at(-1).children.map(c => c.className) };
    h.runner.cancel(); h.log.release(); await settle(200);
  }
  // the card of an annotation that ended stays while something else of the paper waits: words to its session paused by
  // the limit, the chat paused by the limit, words to its session queued behind another paper
  {
    const out = {};
    const failedAnnot = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }),
                         ev({ type: 'result', subtype: 'error_max_turns', is_error: true, result: '', session_id: 'F1' }), 'EXIT:1'];
    const limited = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'F1' }), LIMIT_HIT[0],
                     ev({ type: 'result', subtype: 'success', is_error: true, result: 'You have hit your limit', session_id: 'F1' })];
    const cardsOf = list => list.children.flatMap(r => r.children).filter(c => /^scholium-card/.test(c.className)).map(c => c.className);
    for (const name of ['wordsPaused', 'chatPaused', 'wordsQueued']) {
      const h = harness({ scripts: [failedAnnot, name === 'wordsQueued' ? SCRIPT.concat(['WAIT']) : limited] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      p.annotate(); await settle(400);                                          // the annotation fails: its card
      if (name === 'wordsQueued') { await h.runner.annotate([h.item2]); await settle(100); }   // another paper runs
      if (name === 'chatPaused') { pane.tabChat.click(); await settle(5); }
      pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(400);
      await h.runner.showAnnotation(pane); await settle(5);                  // the tab drawn again
      out[name] = { waiting: h.runner.queue.map(j => [j.att.key, j.kind, h.runner.started(j)]), cards: cardsOf(pane.annot.list),
                    retries: buttonsIn(pane.annot.list, '重试'), chatRetries: buttonsIn(pane.list, '重试') };
      h.runner.stop();
    }
    facts.cardStays = out;
  }
  // the annotation tab's state line shows nothing of a finished annotation (its card does), and the outcome of Delete
  // annotations from its ⋯ menu, which the chat tab's does not; the section on that tab replaces the notice
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    p.annotate(); await settle(600);                                          // an annotation ends: its card
    const finished = { state: p.view('annotate').state, note: h.runner.notes.has('ATT1/annotate') };
    h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666'), h.ann('A2', 'highlight', '#ffd400')];
    h.see(true);
    const before = h.log.notices.length;
    pane.more.click(); pane.popover.node.children[2].click(); await settle(50);   // Delete annotations
    facts.annotStateLine = { finished, deleted: p.view('annotate').state, kind: p.view('annotate').stateKind, chat: p.view('chat').state,
                             notices: h.log.notices.length - before };
  }
  // the reader's eye button after an annotation: a user who never set it (the preference was never set) sees the
  // annotations from the first annotation that wrote, every open reader and button as a click switches them; a run that
  // wrote nothing, and a choice of the user's, are left as they are
  {
    const out = {};
    const fail = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), 'STDERR:boom\n', 'EXIT:1'];
    const silent = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), said('停在这里。'),
                    ev({ type: 'result', subtype: 'success', is_error: false, result: '停在这里。', session_id: 'S1' })];
    for (const [name, pref, script] of [['neverSetWrote', undefined, SCRIPT.concat([LAST, RESULT])], ['neverSetSilent', undefined, silent],
                                        ['neverSetFailed', undefined, fail], ['offWrote', false, SCRIPT.concat([LAST, RESULT])],
                                        ['onWrote', true, SCRIPT.concat([LAST, RESULT])]]) {
      const h = harness(Object.assign({ scripts: [script] }, pref === undefined ? {} : { prefs: { 'extensions.scholium.showAnnotations': pref } }));
      h.toggle.start('scholium@test');
      // an open reader of the paper with the eye button in its toolbar
      const button = { attrs: {}, classList: { toggle(c, on) { button.on = on; } }, setAttribute(k, v) { button.attrs[k] = v; }, title: '',
                       replaceChildren() {}, ownerDocument: { createElementNS: () => ({ setAttribute() {}, append() {} }) } };
      const reader = { itemID: 'ATT1', set: [], unset: [], _iframeWindow: { document: { querySelectorAll: () => [button] } },
                       setAnnotations: async a => { reader.set.push(a.map(x => x.key)); }, unsetAnnotations: async k => { reader.unset.push(k); } };
      h.zotero.Reader._readers = [reader];
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      pane.tabAnnotate.click(); await settle(10);
      pane.annotGo.click(); h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666')]; await settle(600);
      out[name] = { pref: h.store.has('extensions.scholium.showAnnotations') ? h.store.get('extensions.scholium.showAnnotations') : 'unset',
                    shown: h.toggle.shown, set: reader.set.slice(), unset: reader.unset.slice(), pressed: button.attrs['aria-pressed'] || null, done: !h.runner.job };
      h.runner.stop();
      h.toggle.stop();
    }
    facts.eyeAfterAnnotate = out;
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_an_annotation_has_its_own_session(facts):
    a = facts["annotSession"]
    assert re.fullmatch(r"annotate-claude-\d{8}-\d{6}", a["annotConv"])
    assert a["index"]["annotation"] == {"claude": a["annotConv"]} and a["index"]["chat"] == "claude-20261001-120000", \
        "the chat's conversation stays the paper's"
    assert "问题一" not in a["prompt"], "a new annotation session is not given the chat"
    assert a["chatShown"] == "claude-20261001-120000" and a["chatSame"] is True
    assert a["historyRows"] == 1, "annotation sessions stay out of the chat's history"
    assert a["resumed"] == "S1", "words on the annotation tab continue its session"
    assert a["annotPrompts"] == [["批注这篇", True], ["第 5 页那条译文改短", False]]
    assert a["codexAgent"] == "codex"
    assert a["batch"] == ["ATT1", "ATT2"]


def test_the_annotation_tab_shows_its_session(facts):
    a = facts["annotSession"]
    assert a["annotShown"] == [True, False, ["scholium-run"]], "the finished annotation stays on its tab, drawn from its log"
    assert a["chatAgent"] == "codex"
    s = facts["annotShown"]
    assert s["reread"] == {"shown": s["id"], "runs": ["scholium-run"], "chat": None, "intro": False}
    assert s["codex"] == {"shown": None, "intro": True}, "the other agent's tab has no session"
    assert s["gone"] == {"shown": None, "intro": True, "conv": None}, "a session counts while its log is there"


def test_an_annotation_waits_behind_the_papers_chat(facts):
    f = facts["annotBehindChat"]
    assert f["before"] == {"busy": False, "go": False, "agent": True}
    assert f["queue"] == [["ATT1", "annotate", True]] and f["running"] == "chat"
    assert f["busy"] is True and f["agent"] is True
    assert f["stop"] == [True, "■", True], "the waiting annotation, without a session yet, is stopped with ■"
    assert f["after"] == {"calls": 2, "sessions": 1}


def test_the_chat_tab_is_free_while_an_annotation_runs(facts):
    f = facts["chatBesideAnnot"]
    assert f["annotTab"] == {"busy": True, "round": "■", "agent": True}
    assert f["chatTab"] == {"busy": False, "round": "↑", "agent": True, "newChat": False, "history": False, "shown": "claude-20261001-120000"}
    assert f["afterNew"] is None and f["reopened"] == "claude-20261001-120000"
    assert f["deleted"] == [1, None] and f["undone"] == [0, "claude-20261001-120000"]
    assert f["queue"] == [["ATT1", "chat", "claude-20261001-120000"]] and f["input"] == ""
    assert f["answered"] is True


def test_the_ring_shows_the_context_of_its_tabs_run(facts):
    r = facts["ringByTab"]
    assert r["chatLive"] is True
    chat = "上下文窗口：\n10% 已用（剩余 90%）\n100k / 1,000k tokens"
    assert r["starting"] == chat, "a run that only starts is the annotation tab's"
    assert r["chatRing"] == chat and "100k / 1,000k（10%）" in r["chatLayer"]
    assert r["annotRing"] == "上下文窗口：\n30% 已用（剩余 70%）\n300k / 1,000k tokens" and "300k / 1,000k（30%）" in r["annotLayer"]


def test_opened_steps_belong_to_the_session_shown(facts):
    f = facts["foldBySession"]
    assert f["opened"] == 1 and f["same"] == [1, True], "they stay while the session goes on"
    assert f["back"] == [0, True], "another agent's tab shown between"
    assert f["fresh"] == 0 and f["live"] is True


def test_a_stop_ends_its_own_tabs_wait(facts):
    f = facts["stopByKind"]
    assert f["before"] == [["ATT1", "chat"], ["ATT1", "annotate"]] and f["round"] == "■"
    assert f["afterAnnot"] == [["ATT1", "chat"]], "the chat's message stays"
    assert f["afterChat"] == [] and f["running"] == "ATT2"
    s = facts["stopBesideLimit"]
    assert s["before"] == [["chat", True], ["annotate", False]]
    assert s["after"] == ["chat"] and s["paused"] is True and s["ends"] == 0, "the chat waiting for the limit is not ended"


def test_the_words_typed_stay_with_their_tab(facts):
    assert facts["unsentByTab"] == {"onAnnot": "", "backChat": "问对话的半句", "backAnnot": "批注要求的半句", "codex": "", "claude": "批注要求的半句",
                                    "put": "放进去的话"}
    assert facts["unsentPerSession"] == {"during": "", "kept": "给上一次的话"}
    assert facts["unsentIntoSession"] == {"shown": True, "value": "改短一点", "rerendered": [True, "annotate", "改短一点"]}
    assert facts["givenBack"] == {"shown": "annotate-claude-20261030-101010", "back": "第 5 页那条译文改短", "chat": "", "again": "第 5 页那条译文改短"}


def test_the_annotations_extra_instructions_are_logged(facts):
    f = facts["annotExtra"]
    assert f["line"] == ["批注这篇\n附加要求：只标方法部分", True, "只标方法部分"]
    assert f["entry"] == {"kind": "prompt", "text": "批注这篇\n附加要求：只标方法部分", "annotate": True, "extra": "只标方法部分", "turn": 0}
    assert f["plain"] == [{"kind": "prompt", "text": "一个问题"}]


def test_a_confirmed_annotation_asks_nothing(facts):
    assert facts["confirmed"] == {"refused": 0, "queued": 1, "asked": 1, "sessions": 1}


def test_words_on_the_annotation_tab_without_a_session(facts):
    assert facts["annotWords"] == {"session": True, "prompts": [["批注这篇\n附加要求：只看第 3 页", False, True]], "chats": 0, "chat": None}


def test_the_annotation_tab_beside_a_running_chat(facts):
    assert facts["annotBesideLiveChat"] == {"chatLive": True, "annot": "annotate-claude-20261030-101010", "runs": 1}
    assert facts["annotBesideStartingChat"] == {"chatLive": True, "annot": "annotate-claude-20261030-101010"}
    assert facts["annotRace"] == {"live": True, "conv": True}
    assert facts["annotLate"] == {"shown": None, "intro": True}


def test_the_send_key_on_the_annotation_tab(facts):
    f = facts["sendKeyAnnot"]
    assert f["pressed"] is True and f["cleared"] == ""
    assert f["prompt"] == {"type": "scholium", "subtype": "prompt", "text": "批注这篇\n附加要求：只标方法部分", "annotate": True, "extra": "只标方法部分"}


def test_the_introduction_only_without_a_session(facts):
    f = facts["introPlace"]
    assert f["withSession"] == {"view": ["scholium-log"], "list": ["scholium-run"], "intro": False}
    assert f["liveAtRender"] == {"view": ["scholium-log"], "list": ["scholium-run"], "intro": False}
    assert f["none"] == {"view": ["scholium-log"], "list": ["scholium-annot-intro"], "intro": True}


def test_a_run_out_of_sight_on_the_other_tab_has_its_notices(facts):
    assert facts["noticeByTab"] == {"annotOnChat": 2, "annotOnAnnot": 0, "chatOnAnnot": 2, "chatOnChat": 0}


def test_an_annotation_leaves_the_chats_outcome(facts):
    f = facts["notesByKind"]
    assert f["before"].startswith("失败") and f["after"] == f["before"]
    assert f["annotation"] is None, "an annotation's outcome is its card"
    assert facts["chatCancelledWait"] == {"waiting": [["chat", True]], "state": "已取消", "queue": 0}


def test_words_on_the_annotation_tab_go_to_its_sessions_paper(facts):
    assert facts["sendToTabsPaper"] == {"resumed": True, "other": False, "words": True}


def test_an_update_hands_over_the_kind(facts):
    f = facts["handedKinds"]
    assert f["carried"] == [["ATT2", "annotate"], ["ATT1", "chat"], ["ATT1", "annotate"]]
    assert f["restored"] == [["ATT2", "annotate"], ["ATT1", "chat"], ["ATT1", "annotate"]]
    assert f["besideChat"] == [["ATT1", "annotate"]]


def test_the_annotation_tab(facts):
    a = facts["annotPage"]
    assert "高亮重点句（外文论文附译文）" in a["intro"]["text"] and "阅读笔记" in a["intro"]["text"]
    assert a["intro"]["go"] == "批注这篇" and a["intro"]["sendShown"] is False
    assert a["intro"]["placeholder"] == "附加要求（可不填），例如：只批注第 3–5 页" and a["intro"]["confirmHidden"] is True
    d = a["during"]
    assert d["parts"] == ["scholium-entry prompt", "scholium-fold"], "no list of steps: the wishes, then what it does now"
    assert d["go"] is True and d["round"] == "■" and re.fullmatch(r"正在处理 \d+ 秒 详情 ›", d["live"])
    assert d["sendShown"] is True, "■ stops the annotation"
    assert d["step"] == "applying"
    assert d["state"] == "", "the state line has only its dot, as a question's"
    assert re.fullmatch(r"第 6/6 步 写入 Zotero · 已用 \d+s", d["stateTitle"]), "the tooltip has the step and the time"
    f = a["after"]
    assert f["parts"] == ["scholium-entry prompt", "scholium-fold", "scholium-card"], "the closing words go into the folded steps"
    assert f["closing"] == "Done.\n高亮 28 条（核心 12 条），页边批注 9 条，笔记《Deep latent》，无剩余警告。"
    assert f["title"] == "✓ 批注完成，没有剩余警告"
    assert f["nums"] == [["3", "高亮（核心\u00a02）"], ["1", "页边批注"], ["1", "便签"], ["1", "阅读笔记"]]
    assert re.fullmatch(r"26 轮 · 2,568k tokens · \d\d:\d\d", f["usage"])
    assert f["go"] == "重新批注" and f["placeholder"] == "接着这次批注修改，例如：第 5 页那条译文改短"
    assert f["sendShown"] is True and f["state"] is None, "the card has the outcome; the state line is for runs going on or waiting"
    assert f["counts"] == [{"highlights": 3, "core": 2, "margin": 1, "notes": 1, "readingNotes": 1, "warnings": "", "turns": 26, "tokens": 2568179}]
    assert a["ask"] == {"shown": True, "text": ["重新批注会先删除这篇的 5 条 Scholium 批注，1 篇阅读笔记移到回收站（你自己的不动）。", "取消", "替换"],
                        "dialogs": 0}
    assert a["cancelled"] == {"hidden": True, "queued": 0, "kept": "只批注第 3 页", "erased": 0}, "Cancel deletes nothing"
    r = a["replaced"]
    assert r["erased"] == ["A1", "A2", "A3", "A4", "A5"] and r["trashed"] == ["N0"] and r["left"] == ["U1"], \
        "Replace deletes the Scholium annotations and moves the Scholium note to the trash at once; the user's stay"
    assert r["none"] is True, "the new run is told the paper carries none of the tool's annotations"
    assert a["again"] == "只批注第 3 页" and a["dialogsAfter"] == 0, "the question in place was the confirmation"


def test_the_step_reached_shows_at_once(facts):
    f = facts["stepAtOnce"]
    assert f["step"] == "applying" and f["title"].startswith("第 6/6 步 写入 Zotero · 已用 ")


def test_a_failed_annotation(facts):
    f = facts["annotFailed"]
    assert f["failedCard"]["cls"] == "scholium-card failed" and f["failedCard"]["retry"] == "重试"
    assert f["failedCard"]["text"] == "达到轮数上限"
    assert f["failedCard"]["parts"] == ["scholium-entry prompt", "scholium-card failed"]
    assert f["failedCard"]["state"] is None
    assert f["retried"] is True and f["sessions"] == 2


def test_the_annotation_tab_without_a_session(facts):
    assert any(t == "上次由 Claude Code 在 10月24日 写入" for t in facts["annotApplied"])


def test_the_numbers_of_the_card(facts):
    c = facts["countsCases"]
    assert c["core"]["core"] == 2, "the core colour of the configuration that wrote the annotations"
    assert c["core"]["warnings"] == "" and c["core"]["title"] == "✓ 批注完成，没有剩余警告"
    assert c["english"]["core"] == 1 and c["english"]["warnings"] == "style_warnings: 2"
    assert c["english"]["title"] == "✓ 批注完成，剩余警告：style_warnings: 2"
    assert c["silent"]["warnings"] is None and c["silent"]["title"] == "✓ 批注完成"
    assert re.fullmatch(r"3 轮 · \d\d:\d\d", c["silent"]["usage"])
    # 无 is "none" only on its own; the reply's last line, the skill's summary, says it
    assert c["unplaced"]["warnings"] == "无法定位 2 句" and c["unplaced"]["title"] == "✓ 批注完成，剩余警告：无法定位 2 句"
    assert c["elsewhere"]["warnings"] == "第 4 页“label”警告已接受"
    assert facts["warningsTable"] == ["", "", "", "无法定位 2 句", "没有找到第 2 页", "", "", "", "label"]
    assert facts["warningsCounted"] == ['第 8 页译文提到 "DPO" 未出现在原句中，属提示性质，已写入', "第 3 页译文偏长；第 5 页术语缺失", "2 条", "", "",
                                        "page 8: “DPO” is not in the sentence", "2", "", "page 3 is long; page 5 lacks a term",
                                        "page 8 translation is advisory", "", "2 translation warnings on page 3"]


def test_a_second_try_and_a_continuation_are_the_annotations(facts):
    # a failed try that the annotation goes on from, or waits to go on from, is a line; the card is the end's
    r = facts["annotAgain"]["retried"]
    assert r["waiting"] == {"parts": [["scholium-entry prompt", "scholium-entry final error", "scholium-entry info"]], "retries": 0}
    assert r["parts"] == [["scholium-entry prompt", "scholium-entry final error", "scholium-entry info"], ["scholium-fold", "scholium-card none"]]
    assert r["cards"] == ["scholium-card none"], "one card of the end (the harness's run writes none), no red card"
    assert r["retries"] == 0 and r["counts"] == 1
    c = facts["annotAgain"]
    assert c["paused"] == {"parts": [["scholium-entry prompt", "scholium-fold", "scholium-entry final error"]], "queued": 1, "retries": 0}, \
        "the paper waits for the limit: no card, no Retry"
    assert c["continued"]["parts"] == [["scholium-entry prompt", "scholium-fold", "scholium-entry final error"],
                                       ["scholium-entry info", "scholium-fold", "scholium-card none"]]
    assert c["continued"]["cards"] == ["scholium-card none"], "the harness's run writes none"
    assert c["continued"]["retries"] == 0 and c["continued"]["counts"] == 1


def test_a_failed_message_to_the_annotation_session_has_retry(facts):
    f = facts["annotFollowRetry"]
    assert f["shown"] == {"retry": True, "card": False}
    assert f["calls"] == 2 and f["resumed"] == "A0" and f["answered"] is True
    assert f["chat"] is None, "the chat's conversation stays as it was: none"
    assert f["sessions"] == 1


def test_words_of_the_annotation_kind_without_a_session_annotate(facts):
    assert facts["sendAnnotWithout"] == {"sent": True, "sessions": 1, "prompts": [["批注这篇\n附加要求：只看第 3 页", True, "只看第 3 页"]]}


def test_the_annotate_button_takes_the_tabs_paper(facts):
    assert facts["annotGoPaper"] == {"att1": 1, "att3": 0}


def test_the_question_in_place_goes_with_the_tab(facts):
    assert facts["confirmByTab"] == {"atFirst": True, "asked": True, "chat": True, "queued": 0, "dialogs": 0, "sends": [False, True, True]}, \
        "the chat's send button, not Annotate, on the chat tab"


def test_a_long_annotation_is_counted(facts):
    assert facts["countsLong"] == 1


def test_a_failure_while_the_run_goes_is_a_line_until_it_ended(facts):
    f = facts["failureWhileLive"]
    assert f["live"] == ["scholium-entry prompt", "scholium-entry final error", "scholium-fold"]
    assert f["ended"] == ["scholium-entry prompt", "scholium-card failed"]


def test_the_send_key_asks_in_place_too(facts):
    f = facts["sendKeyInPlace"]
    assert f["asked"] == {"shown": True, "dialogs": 0, "queued": 0}
    assert f["empty"] == {"calls": 1, "sessions": 1}, "an empty box annotates as the button does"


def test_a_retry_goes_on_in_its_session_whichever_agent_is_chosen(facts):
    assert facts["retryOtherAgent"] == {"sent": True, "calls": 1, "codexCalls": 0, "resumed": "A0", "sessions": 1}


def test_a_run_without_a_log_line_is_no_attempt_of_the_turn_before(facts):
    for name in ("afterAnnotation", "afterWords"):
        f = facts["noProgramAfterTurn"][name]
        assert f["parts"] == ["scholium-entry final error"] and f["retries"] == 0, name
        assert f["box"] == "第 5 页那条译文改短", name


def test_words_to_the_annotation_session_name_their_step(facts):
    f = facts["wordsState"]
    assert f["state"] == "" and f["title"].startswith("第 6/6 步 写入 Zotero · 已用 ")
    assert "scholium-steps" not in f["parts"]


def test_the_card_of_an_ended_annotation_stays_while_something_else_waits(facts):
    f = facts["cardStays"]
    assert f["wordsPaused"] == {"waiting": [["ATT1", "annotate", True]], "cards": ["scholium-card failed"], "retries": 0, "chatRetries": 0}, \
        "the words' run waits, not the annotation's; Retry only on the last run"
    assert f["chatPaused"] == {"waiting": [["ATT1", "chat", True]], "cards": ["scholium-card failed"], "retries": 1, "chatRetries": 0}, \
        "the chat waits; its failure line has no Retry while it waits"
    assert f["wordsQueued"]["waiting"] == [["ATT1", "annotate", False]] and f["wordsQueued"]["cards"] == ["scholium-card failed"]


def test_the_annotation_tabs_state_line_shows_a_deletion(facts):
    f = facts["annotStateLine"]
    assert f["finished"] == {"state": None, "note": False}, "a finished annotation shows on its card only"
    assert f["deleted"] == "已删除 2 条 Scholium 批注。" and f["kind"] == "scholium-state ok"
    assert f["chat"] is None and f["notices"] == 0


def test_the_first_annotation_that_wrote_shows_the_annotations_once(facts):
    e = facts["eyeAfterAnnotate"]
    assert all(c["done"] for c in e.values())
    assert e["neverSetWrote"] == {"pref": True, "shown": True, "set": [["A1"]], "unset": [], "pressed": "true", "done": True}, \
        "never set: on, as a click turns it on, every open reader and button"
    for name in ("neverSetSilent", "neverSetFailed"):
        assert e[name] == {"pref": "unset", "shown": False, "set": [], "unset": [], "pressed": None, "done": True}, name
    assert e["offWrote"] == {"pref": False, "shown": False, "set": [], "unset": [], "pressed": None, "done": True}, "turned off by the user: stays off"
    assert e["onWrote"] == {"pref": True, "shown": True, "set": [], "unset": [], "pressed": None, "done": True}
