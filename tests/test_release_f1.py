"""Release fixes of the queue and its limits: a stop that keeps the user's words, a pause per agent, a log that refuses a
run's first line, words to an annotation that waits, the agent of an annotation session's queue, a compaction without a
session, an annotation's numbers over all of its parts, the threads still to archive, and the hand-over from v0.1.9."""
import json

import pytest

from bridge_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const DIR = '/data/tmp/scholium/ATT1/conversations/';
const OUT = '/data/tmp/scholium/ATT1/';
// a turn of Claude Code as the plugin logs it
const claudeTurn = (n, uuid, session = 'S1', at = 1000 + n) => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session })
  + L({ type: 'assistant', uuid, session_id: session, message: { usage: { input_tokens: 10 * n, cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0, output_tokens: 1 }, content: [{ type: 'text', text: '回答' + n }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: session,
        modelUsage: { 'claude-opus-5-5': { contextWindow: 200000 } } })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
// what a Claude Code run answers: its session and its words
const answered = (session, text) => [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session }),
  ev({ type: 'assistant', uuid: 'v-' + text, session_id: session, message: { content: [{ type: 'text', text }] } }),
  ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: session })];
// what a Codex turn answers
const codexSays = text => [note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
  coItem('completed', { type: 'agentMessage', id: 'a-' + text, text }), turnDone({ status: 'completed' })];
const linesOf = (h, path) => (h.log.writes[path] || '').trim().split('\n').filter(Boolean).map(l => JSON.parse(l));
const resumeOf = c => (c.opts.arguments.includes('--resume') ? c.opts.arguments[c.opts.arguments.indexOf('--resume') + 1] : null);
(async () => {
  const facts = {};

  // ■ and Esc twice on a paper whose message waits behind another paper's run: the words go back to its box and nothing
  // is logged; the other paper's run goes on
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    const pb = await h.pane(h.item2); await settle(40);
    await h.runner.send(h.att1, '问甲'); await settle(100);
    const P = pb.pane();
    P.input.value = '问乙';
    h.runner.sendFromPane(P); await settle(200);
    const waiting = [h.runner.queue.map(j => j.say), P.input.value, pb.view().round[0]];
    h.runner.stopFromPane(P); await settle(200);
    const stopped = { queue: h.runner.queue.length, box: P.input.value, running: h.runner.job && h.runner.job.key,
                      logsB: Object.keys(h.log.writes).filter(p => p.includes('/ATT2/')) };
    h.runner.sendFromPane(P); await settle(200);
    const again = [h.runner.queue.map(j => j.say), P.input.value];
    h.runner.escape(P); h.runner.escape(P); await settle(200);
    const escaped = { queue: h.runner.queue.length, box: P.input.value, running: h.runner.job && h.runner.job.key };
    facts.stopWaiting = { waiting, stopped, again, escaped };
    h.log.calls[0].proc.kill(); await settle(100);
  }
  // an annotation with extra wishes waiting behind another paper's run: ■ on its tab gives the wishes back to its box
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    const pb = await h.pane(h.item2); await settle(40);
    await h.runner.send(h.att1, '问甲'); await settle(100);
    const P = pb.pane();
    h.runner.setTab(P, 'annotate'); await settle(40);
    P.input.value = '只标方法部分';
    h.runner.sendFromPane(P); await settle(200);
    const waiting = [h.runner.queue.map(j => [j.att.key, j.kind, j.extra]), P.input.value];
    h.runner.stopFromPane(P); await settle(200);
    facts.stopWaitingAnnotation = { waiting, queue: h.runner.queue.length, box: P.input.value };
    h.log.calls[0].proc.kill(); await settle(100);
  }
  // Annotate again with wishes waits, over an earlier session; words typed on the tab queue for the coming session. ■ on
  // the tab: the wishes and the queued words come back to the box together, the earlier session shows again, and no row
  // is left that no tab shows
  {
    const old = 'annotate-claude-20261001-120000';
    const oldLog = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '批注这篇', at: 1000 })
      + L({ type: 'scholium', subtype: 'prompt', text: '批注这篇', annotate: true, extra: '' })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'OLD' })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '完成。', session_id: 'OLD' });
    const h = harness({ logs: { [DIR + old + '.jsonl']: oldLog, [DIR + 'index.json']: JSON.stringify({ chat: null, titles: {}, annotation: { claude: old } }) },
                        scripts: [SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    await h.runner.send(h.att2, '问乙'); await settle(100);
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    h.runner.setTab(P, 'annotate'); await settle(40);
    await h.runner.annotate([h.item1], { confirmed: true, extra: '只标方法' }); await settle(100);
    P.input.value = '着重第 3 节';
    h.runner.sendFromPane(P); await settle(100);
    const waiting = { queue: h.runner.queue.map(j => [j.att.key, j.kind, !!j.qid]), shown: P.annot.shownConv, rows: P.queueBox.children.length };
    h.runner.stopFromPane(P); await settle(300);
    facts.stopWaitingAnnotationRows = { waiting, queue: h.runner.queue.map(j => [j.att.key, j.kind]), held: h.runner.heldQueues.size,
                                        shown: P.annot.shownConv, rows: P.queueBox.children.length, box: P.input.value,
                                        busy: h.runner.busy('ATT1', 'annotate') };
    h.log.calls[0].proc.kill(); await settle(100);
  }
  // an edited question waiting behind another paper's run: ■ undoes the edit, the conversation comes back whole
  {
    const conv = 'chat-20261101-120000';
    const log = claudeTurn(1, 'u1', 'S1') + claudeTurn(2, 'u2', 'S1') + claudeTurn(3, 'u3', 'S1');
    const h = harness({ logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    await h.runner.send(h.att2, '问乙'); await settle(100);
    const P = pa.pane();
    const prompt = (await h.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
    const edited = await h.runner.editTurn(P, prompt, '问题二改'); await settle(100);
    const cut = (await h.runner.readLog('ATT1', conv)).turns.map(t => t.user);
    h.fire(); await settle(100);   // the Undo seconds pass while the edit waits: Undo stays until it starts
    const kept = h.runner.replaced.size;
    h.runner.stopFromPane(P); await settle(300);
    h.fire(); await settle(100);
    facts.stopWaitingEdit = { edited, cut, kept, queue: h.runner.queue.length, turns: (await h.runner.readLog('ATT1', conv)).turns.map(t => t.user),
                              whole: h.log.writes[DIR + conv + '.jsonl'] === log, replaced: h.runner.replaced.size,
                              running: h.runner.job && h.runner.job.key, calls: h.log.calls.length };
    h.log.calls[0].proc.kill(); await settle(100);
  }

  // one agent's usage limit holds its own runs only: Claude Code's limit on paper A, Codex asked on A and on B. B's
  // question runs at once; A's message waits behind A's paused run; Continue now in A's section continues Claude Code; ■
  // on A ends its wait and the pause with it, and the message held there goes on when resumed
  {
    const h = harness({ locale: 'en-US', scripts: [LIMIT_HIT, LIMIT_HIT], codex: { scripts: [codexSays('Codex on B'), codexSays('Codex on A')] } });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    const pa = await h.pane(h.item1); await settle(40);
    const pb = await h.pane(h.item2); await settle(40);
    await h.runner.send(h.att1, 'question on A'); await settle(600);
    const limited = { paused: Object.keys(h.runner.paused || {}), stateA: pa.view().state, resumeA: !pa.view().resumeHidden };
    h.runner.choose('agent', 'codex');
    h.runner.draining = true;   // the queue is looked at before it goes on
    await h.runner.send(h.att1, 'question on A, to Codex');
    await h.runner.send(h.att2, 'question on B, to Codex');
    const queued = { queue: h.runner.queue.map(j => [j.att.key, j.agent, !!j.qid]), stateA: pa.view().state, stateB: pb.view().state,
                     resumeA: !pa.view().resumeHidden, resumeB: !pb.view().resumeHidden };
    h.runner.draining = false;
    h.runner.drain(); await settle(800);
    const others = { codexTurns: h.log.codexTurns, claudeCalls: h.log.calls.length, queue: h.runner.queue.map(j => [j.att.key, j.agent, !!j.qid]),
                     stateA: pa.view().state, stateB: pb.view().state, resumeA: !pa.view().resumeHidden, resumeB: !pb.view().resumeHidden };
    pa.pane().resume.click(); await settle(800);
    const continued = { claudeCalls: h.log.calls.length, codexTurns: h.log.codexTurns, paused: Object.keys(h.runner.paused || {}),
                        queue: h.runner.queue.map(j => [j.att.key, j.agent, !!j.qid]) };
    h.runner.stopFromPane(pa.pane()); await settle(300);
    const stopped = { paused: h.runner.paused, queue: h.runner.queue.map(j => [j.att.key, j.agent, !!j.qid, h.runner.isHeld(j)]), waits: h.live() };
    h.runner.releaseQueue(h.runner.queue[0]); await settle(800);
    const resumed = { codexTurns: h.log.codexTurns, claudeCalls: h.log.calls.length, queue: h.runner.queue.length };
    facts.limitPerAgent = { limited, queued, others, continued, stopped, resumed };
  }
  // a Codex limit holds Codex only: a Claude Code question of another paper runs
  {
    const h = harness({ codex: { scripts: [CODEX_LIMIT] } });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    h.runner.choose('agent', 'codex');
    await h.runner.annotate([h.item1], { confirmed: true }); await settle(600);
    const paused = Object.keys(h.runner.paused || {});
    h.runner.choose('agent', 'claude');
    await h.runner.send(h.att2, '问乙'); await settle(600);
    facts.codexLimitOnly = { paused, claudeCalls: h.log.calls.length, codexTurns: h.log.codexTurns, queue: h.runner.queue.map(j => [j.att.key, j.agent]),
                             stateA: pa.view('annotate').state, clock: h.runner.clock(h.runner.paused.codex.until) };
    h.runner.stop();
  }
  // words queued to a running Claude Code annotation session while Codex is paused and chosen: they are Claude Code's
  // from the moment they are queued, so they wait for no Codex reset
  {
    const h = harness({ locale: 'en-US', scripts: [SCRIPT.concat(['WAIT']), answered('S1', '图注也译好了')], codex: { scripts: [CODEX_LIMIT] } });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    h.runner.choose('agent', 'codex');
    await h.runner.send(h.att2, '问乙'); await settle(800);
    const paused = Object.keys(h.runner.paused || {});
    h.runner.choose('agent', 'claude');
    await h.runner.annotate([h.item1], { confirmed: true }); await settle(200);
    const P = pa.pane();
    h.runner.setTab(P, 'annotate'); await settle(20);
    h.runner.choose('agent', 'codex');   // as another paper's section does
    P.input.value = '图注也翻译';
    h.runner.sendFromPane(P); await settle(100);
    const row = h.runner.queue.filter(j => j.qid).map(j => j.agent);
    h.log.calls[0].proc.kill(); await settle(800);   // the annotation ends
    facts.rowAgentWhileQueued = { paused, row, claudeCalls: h.log.calls.length, queue: h.runner.queue.map(j => [j.att.key, j.agent, !!j.qid]),
                                  stateA: pa.view('annotate').state, resumeA: !pa.view('annotate').resumeHidden };
    h.runner.stop();
  }
  // the pause an earlier copy hands over (one for the whole queue) is the pause of the agent of the paper it held, at
  // the head of the queue; this copy hands each agent's own over
  {
    const old = JSON.stringify({ jobs: [{ key: 'ATT1', libraryID: 1, agent: 'codex', extra: '', say: '', resume: 'T1', asked: false, question: false,
                                          annotate: false, own: 0, interrupted: false, updated: false, throttled: false, retried: false, retryAt: 0 },
                                        { key: 'ATT2', libraryID: 1, agent: 'claude', extra: '', say: '问乙', resume: null, asked: false, question: true,
                                          annotate: false, own: 0, interrupted: false, updated: false, throttled: false, retried: false, retryAt: 0 }],
                                 paused: { until: Date.now() + 600000, known: true, throttled: false } });
    const h = harness({ prefs: { 'extensions.scholium-bridge.carryOver': old } });
    h.runner.start('x', true); await settle(600);
    const restored = { paused: Object.keys(h.runner.paused || {}), claudeCalls: h.log.calls.length, codexTurns: h.log.codexTurns,
                       queue: h.runner.queue.map(j => [j.att.key, j.agent]) };
    h.runner.stop(true);
    const carried = JSON.parse(h.store.get('extensions.scholium-bridge.carryOver'));
    const h2 = harness({ prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify(carried) } });
    h2.runner.start('x', true); await settle(400);
    facts.carriedPausePerAgent = { restored, carried: Object.keys(carried.paused || {}), known: carried.paused && carried.paused.codex && carried.paused.codex.known,
                                   again: Object.keys(h2.runner.paused || {}), calls: h2.log.calls.length, turns: h2.log.codexTurns,
                                   queue: h2.runner.queue.map(j => [j.att.key, j.agent]) };
    h2.runner.stop();
  }

  // the log refuses the run's first line a moment: the words go back to the box, the log gains nothing, no earlier
  // answer is marked failed
  for (const [name, logs] of [['followUp', { [DIR + 'chat-20261101-120000.jsonl']: claudeTurn(1, 'u1', 'S1') + claudeTurn(2, 'u2', 'S1'),
                                               [DIR + 'index.json']: JSON.stringify({ chat: 'chat-20261101-120000', titles: {}, annotation: {} }) }],
                               ['firstMessage', {}]]) {
    const h = harness({ logs, failLogWrites: (p, t) => /"subtype":"run"/.test(t), scripts: [answered('S1', '没问到')] });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    P.input.value = '我仔细写的问题';
    h.runner.sendFromPane(P); await settle(800);
    const v = pa.view();
    const log = v.shownConv ? await h.runner.readLog('ATT1', v.shownConv) : null;
    facts['runLine_' + name] = { locked: !!h.log.lockedOnce, calls: h.log.calls.length, box: P.input.value, state: v.state,
                                 retry: v.flat.some(e => e[1].includes('重试')), entries: v.flat.length,
                                 turns: log ? log.turns.map(t => [t.user, t.reply, t.ended]) : null,
                                 ends: Object.keys(h.log.writes).filter(p => p.endsWith('.jsonl')).flatMap(p => linesOf(h, p)).filter(l => l.subtype === 'end').length };
  }

  // Annotate again waits behind another paper's run: the tab shows the coming session, and words typed there go to it,
  // after the annotation; the earlier session is left as it was
  {
    const ADIR = DIR;
    const old = 'annotate-claude-20261001-120000';
    const oldLog = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '批注这篇', at: 1000 })
      + L({ type: 'scholium', subtype: 'prompt', text: '批注这篇', annotate: true, extra: '' })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'OLD' })
      + L({ type: 'assistant', uuid: 'o1', session_id: 'OLD', message: { content: [{ type: 'text', text: '完成。' }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '完成。', session_id: 'OLD' })
      + L({ type: 'scholium', subtype: 'time', at: 2000 });
    const h = harness({ logs: { [ADIR + old + '.jsonl']: oldLog, [ADIR + 'index.json']: JSON.stringify({ chat: null, titles: {}, annotation: { claude: old } }) },
                        scripts: [SCRIPT.concat(['WAIT']), answered('NEW', '重新批注好了。'), answered('NEW', '第 3 节已着重。')] });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    await h.runner.send(h.att2, '问乙'); await settle(100);
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    h.runner.setTab(P, 'annotate'); await settle(40);
    const shownBefore = P.annot.shownConv;
    await h.runner.annotate([h.item1], { confirmed: true }); await settle(100);
    const shownWaiting = P.annot.shownConv;
    P.input.value = '着重第 3 节';
    h.runner.sendFromPane(P); await settle(100);
    const row = h.runner.queue.map(j => [j.att.key, j.kind, !!j.qid, j.conv || null, j.say || '']);
    const rows = P.queueBox.children.length;
    h.log.calls[0].proc.kill(); await settle(400);
    for (const q of h.runner.queue) if (q.qid) h.runner.releaseQueue(q);
    await settle(1500);
    const idx = JSON.parse(h.log.writes[ADIR + 'index.json']);
    const fresh = idx.annotation.claude;
    facts.annotateAgainWaiting = { shownBefore, shownWaiting, row, rows, oldKept: h.log.writes[ADIR + old + '.jsonl'] === oldLog,
                                   fresh: fresh !== old, runs: linesOf(h, ADIR + fresh + '.jsonl').filter(l => l.subtype === 'run').map(l => l.user),
                                   resumes: h.log.calls.map(resumeOf), tabShows: P.annot.shownConv === fresh };
  }
  // words queued to a running annotation session go to that session's agent, whichever agent is chosen meanwhile
  {
    const h = harness({ gateFirst: true, codex: { scripts: [codexSays('Codex 在批注会话里')] } });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    h.runner.choose('agent', 'claude');
    await h.runner.annotate([h.item1], { confirmed: true }); await settle(200);
    const P = pa.pane();
    h.runner.setTab(P, 'annotate'); await settle(20);
    const conv = h.runner.job && h.runner.job.source.conv;
    h.runner.choose('agent', 'codex');   // as another paper's section does
    P.input.value = '图注也翻译';
    h.runner.sendFromPane(P); await settle(100);
    h.runner.cancel(); await settle(400);
    for (const q of h.runner.queue) if (q.qid) h.runner.releaseQueue(q);
    await settle(1500);
    facts.annotationQueueAgent = { conv, codexTurns: h.log.codexTurns, claudeCalls: h.log.calls.length, resumes: h.log.calls.map(resumeOf),
                                   runs: linesOf(h, DIR + conv + '.jsonl').filter(l => l.subtype === 'run').map(l => [l.agent, l.user]) };
  }

  // /compact with a focus in a conversation whose session the agent no longer has: no new session is asked to compact
  {
    const conv = 'chat-20261101-120000';
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + claudeTurn(2, 'u2', 'S1'),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [CLAUDE_GONE, answered('S9', '没有可压缩的。')] });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    P.input.value = '/compact 保留公式';
    h.runner.sendFromPane(P); await settle(1500);
    const lines = linesOf(h, DIR + conv + '.jsonl').filter(l => l.type === 'scholium' && ['gone', 'run'].includes(l.subtype));
    facts.compactGone = { calls: h.log.calls.map(resumeOf), lines: lines.map(l => l.subtype + (l.resent !== undefined ? ':' + l.resent : '') + (l.compact ? ':compact' : '')),
                          state: pa.view().state, session: (await h.runner.readLog('ATT1', conv)).agents.claude.session };
  }
  // /compact typed while the chosen agent has no session in the conversation: a moment's line says there is nothing to
  // compact yet, and the words stay
  for (const locale of ['zh-CN', 'en-US']) {
    const conv = 'chat-20261101-120000';
    const h = harness({ locale, logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + claudeTurn(2, 'u2', 'S1'),
                                        [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    h.runner.choose('agent', 'codex');
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    P.input.value = '/compact';
    h.runner.fitInput(P);
    const round = pa.view().round;
    const hint = P.hint.textContent;
    key(P.input, { key: 'Enter', ctrlKey: true }); await settle(200);
    const said = P.hint.textContent;
    h.fire();   // the moment passes
    facts['compactNothing_' + locale] = { round, hint, said, later: P.hint.textContent, box: P.input.value,
                                          calls: h.log.calls.length + h.log.codexTurns };
  }

  // an annotation that hit the usage limit and finished after the reset: its card counts both parts
  {
    const firstPart = SCRIPT.concat([
      ev({ type: 'rate_limit_event', session_id: 'S1', rate_limit_info: { status: 'rejected', resetsAt: LIMIT_RESET, rateLimitType: 'five_hour', utilization: 1 } }),
      ev({ type: 'assistant', error: 'rate_limit', session_id: 'S1', message: { content: [{ type: 'text', text: "You've hit your limit · resets 9pm" }] } }),
      ev({ type: 'result', subtype: 'success', is_error: true, result: "You've hit your limit · resets 9pm", session_id: 'S1', num_turns: 20,
           usage: { input_tokens: 0, cache_creation_input_tokens: 100000, cache_read_input_tokens: 1100000, output_tokens: 30000 } })]);
    const rest = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), LAST,
      ev({ type: 'result', subtype: 'success', is_error: false, result: 'Done.\n' + SUMMARY, session_id: 'S1', num_turns: 6,
           usage: { input_tokens: 10, cache_creation_input_tokens: 1000, cache_read_input_tokens: 300000, output_tokens: 5000 } })];
    const h = harness({ scripts: [firstPart, rest] });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    await h.runner.annotate([h.item1], { confirmed: true }); await settle(600);
    const paused = !!h.runner.paused;
    h.runner.resumeQueue(); await settle(800);
    const conv = Object.keys(h.log.writes).find(p => p.includes('/conversations/annotate-'));
    facts.countsAfterPause = { paused, counts: linesOf(h, conv).filter(l => l.subtype === 'counts').map(c => [c.turns, c.tokens]) };
  }

  // the threads waiting to be archived stay listed until Codex archived them or refused them
  for (const [name, codex] of [['ended', { exitOn: 'thread/archive' }], ['refused', { refuse: { 'thread/archive': 'thread not found' } }], ['archived', {}]]) {
    const h = harness({ prefs: { 'extensions.scholium-bridge.codexArchive': JSON.stringify(['TA', 'TB', 'TC']), 'extensions.scholium-bridge.agent': 'codex' },
                        codex: Object.assign({ scripts: [codexSays('x')] }, codex) });
    h.runner.start('x');
    await h.runner.send(h.att1, '一个问题'); await settle(1500);
    facts['archive_' + name] = { asked: h.log.codexProcs.flatMap(p => p.sent).filter(m => m.method === 'thread/archive').map(m => m.params.threadId),
                                 left: h.store.get('extensions.scholium-bridge.codexArchive') || '' };
    h.runner.stop();   // a request sent after the server ended has no answer here
  }

  // v0.1.9 replaced in the middle of a question: it goes on as one turn with its words
  {
    const asked = L({ type: 'scholium', subtype: 'prompt', text: '第二节讲了什么？', question: true })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', message: { content: [{ type: 'text', text: '部分回答' }] } })
      + L({ type: 'scholium', subtype: 'end', outcome: 'interrupted', text: '运行被中断（插件更新或停用，或 Zotero 退出）', duration_ms: 0 });
    const undelivered = L({ type: 'scholium', subtype: 'prompt', text: '这篇怎么估计后验？', question: true })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' })
      + L({ type: 'scholium', subtype: 'end', outcome: 'interrupted', text: '运行被中断（插件更新或停用，或 Zotero 退出）', duration_ms: 0 });
    const followUp = L({ type: 'scholium', subtype: 'prompt', text: '方法是什么？', question: true })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', message: { content: [{ type: 'text', text: '变分推断。' }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '变分推断。', session_id: 'S1' })
      + L({ type: 'scholium', subtype: 'prompt', text: '那误差呢？' })
      + L({ type: 'scholium', subtype: 'end', outcome: 'interrupted', text: '运行被中断（插件更新或停用，或 Zotero 退出）', duration_ms: 0 });
    const job = more => Object.assign({ key: 'ATT1', libraryID: 1, agent: 'claude', extra: '', say: '', resume: null, asked: false, question: false,
                                        annotate: false, own: 0, interrupted: false, updated: false, throttled: false, retried: false, retryAt: 0 }, more);
    const cases = {
      answering: [asked, job({ resume: 'S1', asked: true, question: true, updated: true })],
      undelivered: [undelivered, job({ say: '这篇怎么估计后验？', question: true })],
      followUp: [followUp, job({ say: '那误差呢？', resume: 'S1' })],
    };
    for (const [name, [text, carried]] of Object.entries(cases)) {
      const h = harness({ logs: { [OUT + 'claude-run.jsonl']: text }, scripts: [answered('S1', '继续完成。')],
                          prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify({ jobs: [carried], paused: null }) } });
      h.runner.start('x', true);
      const p = await h.pane(h.item1);
      await settle(800);
      const log = await h.runner.readLog('ATT1', 'claude-run');
      const added = h.log.writes[OUT + 'claude-run.jsonl'].slice(text.length).trim().split('\n').map(l => JSON.parse(l))
        .filter(l => l.type === 'scholium').map(l => l.subtype + (l.subtype === 'run' ? ':' + l.user : l.subtype === 'prompt' ? ':' + l.text : l.reason ? ':' + l.reason : ''));
      facts['handOver019_' + name] = { shown: p.view().shownConv, added, turns: log.turns.map(t => [t.user, t.reply]),
                                       prompts: p.view().flat.filter(e => /prompt/.test(e[0])).length, asked: h.log.stdin.map(s => s.split(carried.say || 'none').length - 1),
                                       resume: h.log.calls.map(resumeOf) };
      h.runner.stop();
    }
  }
  // a v0.1.9 user's paper (no index) with both agents' logs opens on the chosen agent's; only the other's: on that one
  {
    const claudeLog = L({ type: 'scholium', subtype: 'prompt', text: '问 Claude', question: true })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' });
    const codexLog = L({ type: 'scholium', subtype: 'prompt', text: '问 Codex', question: true })
      + L({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: '答', session_id: 'T1' });
    const shown = async (agent, logs) => {
      const h = harness({ prefs: { 'extensions.scholium-bridge.agent': agent }, logs, logTimes: { [OUT + 'claude-run.jsonl']: 10, [OUT + 'codex-run.jsonl']: 20 } });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(60);
      const index = h.log.writes[DIR + 'index.json'];
      return [p.view().shownConv, index ? JSON.parse(index).chat : null];
    };
    const both = { [OUT + 'claude-run.jsonl']: claudeLog, [OUT + 'codex-run.jsonl']: codexLog };
    facts.legacyChosen = { claude: await shown('claude', both), codex: await shown('codex', both),
                           onlyCodex: await shown('claude', { [OUT + 'codex-run.jsonl']: codexLog }) };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_a_stop_on_a_paper_that_waits_gives_its_words_back(facts):
    s = facts["stopWaiting"]
    assert s["waiting"] == [["问乙"], "", "■"], "the question waits behind the other paper's run"
    assert s["stopped"] == {"queue": 0, "box": "问乙", "running": "ATT1", "logsB": []}, "back in the box, nothing logged"
    assert s["again"] == [["问乙"], ""]
    assert s["escaped"] == {"queue": 0, "box": "问乙", "running": "ATT1"}, "Esc twice does the same"


def test_a_stop_on_an_annotation_that_waits_gives_its_wishes_back(facts):
    s = facts["stopWaitingAnnotation"]
    assert s["waiting"] == [[["ATT2", "annotate", "只标方法部分"]], ""]
    assert s["queue"] == 0 and s["box"] == "只标方法部分"
    r = facts["stopWaitingAnnotationRows"]
    assert r["waiting"] == {"queue": [["ATT1", "annotate", False], ["ATT1", "annotate", True]], "shown": None, "rows": 1}
    assert r["queue"] == [] and r["held"] == 0 and r["rows"] == 0 and r["busy"] is False, "no row left that no tab shows"
    assert r["shown"] == "annotate-claude-20261001-120000", "the earlier session shows again"
    assert r["box"] == "只标方法\n\n着重第 3 节", "the wishes and the queued words, together"


def test_a_stop_on_an_edited_question_that_waits_undoes_the_edit(facts):
    s = facts["stopWaitingEdit"]
    assert s["edited"] is True and s["cut"] == ["问题1"]
    assert s["kept"] == 1, "the Undo seconds passed while it waited: it can still be undone"
    assert s["queue"] == 0 and s["replaced"] == 0
    assert s["whole"] is True and s["turns"] == ["问题1", "问题2", "问题3"], "the conversation is back as it was"
    assert s["running"] == "ATT2" and s["calls"] == 1, "the other paper's run goes on"


def test_one_agents_usage_limit_holds_its_own_runs_only(facts):
    f = facts["limitPerAgent"]
    assert f["limited"]["paused"] == ["claude"] and f["limited"]["resumeA"] is True
    assert f["limited"]["stateA"].startswith("Claude Code usage limit reached; continues by itself after "), "it names the agent"
    q = f["queued"]
    assert q["queue"] == [["ATT1", "claude", False], ["ATT1", "codex", True], ["ATT2", "codex", False]]
    assert q["stateA"].startswith("Claude Code usage limit reached"), "A's next run is Claude Code's"
    assert q["stateB"] == "Queued, 0 ahead", "B waits for nothing held by the limit"
    assert q["resumeA"] is True and q["resumeB"] is False
    o = f["others"]
    assert o["codexTurns"] == 1 and o["claudeCalls"] == 1, "Codex answers B at once"
    assert o["queue"] == [["ATT1", "claude", False], ["ATT1", "codex", True]], "A's message stays behind A's paused run"
    assert o["stateA"].startswith("Claude Code usage limit reached") and o["resumeA"] is True
    assert "usage limit" not in (o["stateB"] or "") and o["resumeB"] is False
    c = f["continued"]
    assert c["claudeCalls"] == 2 and c["codexTurns"] == 1 and c["paused"] == ["claude"], "Continue now continues Claude Code"
    s = f["stopped"]
    assert s["paused"] is None and s["queue"] == [["ATT1", "codex", True, True]] and s["waits"] == []
    assert f["resumed"] == {"codexTurns": 2, "claudeCalls": 2, "queue": 0}


def test_a_codex_limit_holds_codex_only(facts):
    c = facts["codexLimitOnly"]
    assert c["paused"] == ["codex"] and c["codexTurns"] == 1
    assert c["claudeCalls"] == 1 and c["queue"] == [["ATT1", "codex"]], "Claude Code answers the other paper"
    assert c["stateA"] == f"Codex 额度已用完，{c['clock']} 重置后自动继续", "it names the agent"


def test_words_queued_to_an_annotation_session_wait_on_its_agent(facts):
    r = facts["rowAgentWhileQueued"]
    assert r["paused"] == ["codex"] and r["row"] == ["claude"], "Claude Code's from the moment they are queued"
    assert r["claudeCalls"] == 2 and r["queue"] == [["ATT2", "codex", False]], "they ran after the annotation, not after Codex's reset"
    assert "usage limit" not in (r["stateA"] or "") and r["resumeA"] is False


def test_a_handed_over_pause_is_its_agents(facts):
    c = facts["carriedPausePerAgent"]
    r = c["restored"]
    assert r["paused"] == ["codex"], "the earlier copy's pause held the Codex paper at the head"
    assert r["claudeCalls"] == 1 and r["codexTurns"] == 0 and r["queue"] == [["ATT1", "codex"]]
    assert c["carried"] == ["codex"] and c["known"] is True
    assert c["again"] == ["codex"] and c["calls"] == 0 and c["turns"] == 0 and c["queue"] == [["ATT1", "codex"]]


def test_a_log_that_refuses_the_runs_first_line_loses_nothing(facts):
    f = facts["runLine_followUp"]
    assert f["locked"] is True and f["calls"] == 0
    assert f["box"] == "我仔细写的问题", "the words are back in the box"
    assert f["turns"] == [["问题1", "回答1", ""], ["问题2", "回答2", ""]], "no earlier answer is marked failed"
    assert f["ends"] == 0 and f["retry"] is False, "nothing to retry: the words are in the box"
    assert f["state"] == "失败 · NotWritableError", "the state line says why"
    g = facts["runLine_firstMessage"]
    assert g["locked"] is True and g["calls"] == 0 and g["box"] == "我仔细写的问题" and g["ends"] == 0
    assert not g["turns"] and g["retry"] is False and g["entries"] == 0 and g["state"] == "失败 · NotWritableError"


def test_words_to_an_annotation_that_waits_go_to_its_session(facts):
    a = facts["annotateAgainWaiting"]
    assert a["shownBefore"] == "annotate-claude-20261001-120000"
    assert a["shownWaiting"] is None, "the tab shows the session to come"
    assert a["row"] == [["ATT1", "annotate", False, None, ""], ["ATT1", "annotate", True, None, "着重第 3 节"]], \
        "the words wait behind the annotation, for its session"
    assert a["rows"] == 1, "the queued words show on the tab"
    assert a["oldKept"] is True and a["fresh"] is True
    assert a["runs"] == ["批注这篇", "着重第 3 节"], "after the annotation, in its session"
    assert a["resumes"] == [None, None, "NEW"]
    assert a["tabShows"] is True


def test_words_queued_to_an_annotation_session_go_to_its_agent(facts):
    a = facts["annotationQueueAgent"]
    assert a["conv"].startswith("annotate-claude-")
    assert a["codexTurns"] == 0 and a["claudeCalls"] == 2 and a["resumes"][1] == "S1", "Claude Code, in its session"
    assert [r[0] for r in a["runs"]] == ["claude", "claude"] and a["runs"][1][1] == "图注也翻译"


def test_a_compaction_whose_session_is_gone_starts_no_session(facts):
    c = facts["compactGone"]
    assert c["calls"] == ["S1"], "no second process without the session"
    assert c["lines"][-2:] == ["run:compact", "gone:false"], "the gone session is noted, nothing resent"
    assert c["session"] is None


def test_compact_without_a_session_says_there_is_nothing_to_compact(facts):
    z, e = facts["compactNothing_zh-CN"], facts["compactNothing_en-US"]
    assert z["round"][0] == "↑" and e["round"][0] == "↑"
    assert z["said"] == "还没有可压缩的内容" and e["said"] == "Nothing to compact yet"
    assert z["later"] == z["hint"] and e["later"] == e["hint"], "for a moment"
    assert z["box"] == "/compact" and e["box"] == "/compact" and z["calls"] == 0 and e["calls"] == 0


def test_an_annotations_card_counts_all_of_its_parts(facts):
    c = facts["countsAfterPause"]
    assert c["paused"] is True
    assert c["counts"] == [[26, 1230000 + 306010]]


def test_threads_to_archive_stay_until_codex_took_them(facts):
    assert facts["archive_ended"]["asked"] == ["TA"], "the server ended: the rest wait for the next run"
    assert json.loads(facts["archive_ended"]["left"]) == ["TA", "TB", "TC"], "nothing archived: all stay"
    assert facts["archive_refused"]["asked"] == ["TA", "TB", "TC"] and facts["archive_refused"]["left"] in ("", "[]")
    assert facts["archive_archived"]["asked"] == ["TA", "TB", "TC"] and facts["archive_archived"]["left"] in ("", "[]")


def test_a_question_v019_handed_over_goes_on_as_one_turn(facts):
    a = facts["handOver019_answering"]
    assert a["shown"] == "claude-run" and a["resume"] == ["S1"]
    assert a["added"] == ["run:null", "continue:update", "time"], "a continuation, no empty question"
    assert a["turns"] == [["第二节讲了什么？", "继续完成。"]] and a["prompts"] == 1
    u = facts["handOver019_undelivered"]
    assert u["added"] == ["run:null", "time"], "the question is in the log already: asked again in place"
    assert u["turns"] == [["这篇怎么估计后验？", "继续完成。"]] and u["prompts"] == 1 and u["asked"] == [1]
    f = facts["handOver019_followUp"]
    assert f["added"] == ["run:null", "time"] and f["resume"] == ["S1"] and f["asked"] == [1]
    assert [t[0] for t in f["turns"]] == ["方法是什么？", "那误差呢？"] and f["prompts"] == 2


def test_a_v019_paper_opens_on_the_chosen_agents_conversation(facts):
    c = facts["legacyChosen"]
    assert c["claude"] == ["claude-run", "claude-run"]
    assert c["codex"] == ["codex-run", "codex-run"]
    assert c["onlyCodex"] == ["codex-run", "codex-run"]
