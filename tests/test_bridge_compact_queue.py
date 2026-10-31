"""Compaction of a conversation (Claude Code's /compact), its markers in the transcript and on the ring; the state line
of the running paper is painted on the tab of the run's kind only; follow-ups steered into the run or queued as rows
above the message box, as in Codex."""
import re

import pytest

from bridge_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const pause = ms => new Promise(r => setTimeout(r, ms));   // the ticks of the state line are timers
  // /compact in the box: Claude Code resumes the session with /compact and the focus; the transcript shows one marker,
  // in progress and then with the numbers; what Claude Code adds of the summary stays hidden; the ring takes the new size;
  // the conversation's last turn is still the question before
  {
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
    const first = [init, ev({ type: 'assistant', message: { content: [{ type: 'text', text: '回答一' }],
                                                           usage: { input_tokens: 10, cache_read_input_tokens: 849990, output_tokens: 0 } } }),
                   ev({ type: 'result', subtype: 'success', is_error: false, result: '回答一', session_id: 'S1',
                        modelUsage: { 'claude-opus-5-5': { contextWindow: 1000000 } } })];
    const compact = [init,
      ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }),
      'HOLD',
      ev({ type: 'system', subtype: 'status', status: null, compact_result: 'success', session_id: 'S1' }),
      ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1',
           compact_metadata: { trigger: 'manual', pre_tokens: 850000, post_tokens: 120000, duration_ms: 8000 } }),
      ev({ type: 'user', message: { role: 'user', content: 'This session is being continued from a previous conversation that ran out of context.' }, session_id: 'S1' }),
      ev({ type: 'user', message: { role: 'user', content: '<local-command-stdout>Compacted </local-command-stdout>' }, session_id: 'S1' }),
      ev({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'S1' })];
    const h = harness({ scripts: [first, compact] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(300);
    pane.input.type('/compact 侧重方法部分'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    const args = h.log.calls[1].opts.arguments;
    const during = { marker: pane.list.children.at(-1).textContent, state: p.view().state, stdin: h.log.stdin[1],
                     resumed: args[args.indexOf('--resume') + 1], round: pane.send.textContent };
    h.log.release(); await settle(400);
    const lines = convLines(h);
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    facts.compactClaude = {
      during, after: pane.list.children.at(-1).textContent, runs: pane.list.children.length,
      hidden: !/being continued|Compacted/.test(pane.list.textContent), ring: pane.ring.title,
      runLine: lines.filter(l => l.subtype === 'run').at(-1), marks: lines.filter(l => l.type === 'scholium' && /compact/.test(l.subtype)),
      turns: log.turns.map(t => [t.user, t.reply]), session: log.session,
    };
  }
  // compaction the agent does on its own in a run: a line in the run, and the ring follows
  {
    const auto = SCRIPT.slice(0, 4).concat([
      ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }),
      ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'auto', pre_tokens: 990000, post_tokens: 150000 } }),
      LAST, RESULT]);
    const h = harness({ script: auto });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().input.type('问题'); p.pane().send.click(); await settle(400);
    facts.compactAuto = p.pane().list.children.at(-1).children.map(c => c.textContent).filter(t => /压缩/.test(t));
    facts.compactAutoParts = p.pane().list.children.at(-1).children.map(c => c.className);
    // before its first step the run's lines are its lead
    const early = harness({ script: [SCRIPT[0], ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'auto', pre_tokens: 990000, post_tokens: 150000 } }),
                                    LAST, RESULT] });
    early.runner.start('x');
    const q = await early.pane(early.item1);
    await settle(40);
    q.pane().input.type('问题'); q.pane().send.click(); await settle(400);
    facts.compactAutoEarly = q.pane().list.children.at(-1).children.map(c => c.textContent).filter(t => /压缩/.test(t));
  }
  // a compaction stopped on the way
  {
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), said('好'),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: '好', session_id: 'S1' })],
                                  [ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }), 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问'); pane.send.click(); await settle(300);
    await h.runner.compactFromPane(pane);
    for (let i = 0; i < 3000 && !(h.runner.current && h.log.stdin.length >= 2); i++) await tick();
    pane.send.click(); await settle(300);                       // ■
    facts.compactStopped = pane.list.children.at(-1).textContent;
    const stopped = await h.runner.readLog('ATT1', pane.shownConv);
    facts.compactStoppedLog = { turns: stopped.turns.map(t => [t.user, t.reply, t.ended]), result: stopped.result && stopped.result.result };
  }
  // the run after a compaction does not continue it: it opens its own turn
  {
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
    const compacted = [init, ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'manual', pre_tokens: 8000, post_tokens: 900 } }),
                       ev({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'S1' })];
    const first = [init, said('回答一'), ev({ type: 'result', subtype: 'success', is_error: false, result: '回答一', session_id: 'S1' })];
    const third = [init, said('回答二'), ev({ type: 'result', subtype: 'success', is_error: false, result: '回答二', session_id: 'S1' })];
    const h = harness({ scripts: [first, compacted, third] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(300);
    await h.runner.compactFromPane(pane); await settle(300);
    pane.input.type('问题二'); pane.send.click(); await settle(300);
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    const runs = h.runner.runsOf(log.entries);
    facts.afterCompaction = { runs: runs.map(r => [!!r.compact, r.turn ? r.turn.text : null, !!r.continued]),
                              turns: log.turns.map(t => [t.user, t.reply]) };
  }
  // the state line of the running paper goes to the tab of the run's kind: the other tab's outcome stays
  {
    const h = harness({ script: SCRIPT.concat(['HOLD', LAST, RESULT]) });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    pane.annotGo.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await pause(40);
    const running = pane.state.textContent;
    pane.tabChat.click(); await pause(40);
    const chat = pane.state.textContent;
    pane.tabAnnotate.click(); await pause(40);
    const back = pane.state.textContent;
    h.log.release(); await settle(400);
    facts.tickAnnotation = { running, chat, back };
    const g = harness({ script: [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), 'HOLD', said('好'),
                                  ev({ type: 'result', subtype: 'success', is_error: false, result: '好', session_id: 'S1' })] });
    g.runner.start('x');
    const q = await g.pane(g.item1);
    await settle(40);
    const gp = q.pane();
    gp.input.type('问'); gp.send.click();
    for (let i = 0; i < 3000 && !g.log.release; i++) await tick();
    await pause(40);
    const chatRunning = gp.state.textContent;
    gp.tabAnnotate.click(); await pause(40);
    const annot = gp.state.textContent;
    g.log.release(); await settle(300);
    facts.tickChat = { chatRunning, annot };
  }
  // the line the plugin keeps of a compaction it did not see the boundary of: the size after it is the ring's
  {
    const log = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '问' })
      + ev({ type: 'assistant', message: { content: [{ type: 'text', text: '答' }], usage: { input_tokens: 5, output_tokens: 5 } }, session_id: 'S1' })
      + ev({ type: 'scholium', subtype: 'compacted', pre: 700, post: 90 });
    const h = harness({ logs: { [CONV1]: log } });
    h.runner.start('x');
    const parsed = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    facts.compactedLine = parsed.context.used;
  }
  // the run that goes on after a compaction goes on with the last turn, not with the compaction
  {
    const h = harness({});
    const runs = h.runner.runsOf([{ kind: 'run', at: 1 }, { kind: 'prompt', text: '问' }, { kind: 'run', at: 2, compact: true },
                                  { kind: 'compacted', trigger: 'manual', pre: 8000, post: 900 }, { kind: 'run', at: 3, continues: true },
                                  { kind: 'final', text: '断了', error: true }]);
    facts.goesOnAfterCompaction = runs.map(r => [!!r.compact, r.turn ? r.turn.text : null, !!r.continued]);
  }
  // a compaction goes to the conversation named, whichever is the paper's current one; one without a session of its
  // agent, or of Codex's, does not start
  {
    const DIR = '/data/tmp/scholium/ATT1/conversations/';
    const logOf = (agent, sid, q) => ev({ type: 'scholium', subtype: 'run', agent, user: q, at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: q })
      + (sid ? ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: sid }) + said('答')
        + ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: sid }) : '');
    const OLD = 'claude-20260901-100000', NEW = 'claude-20261001-120000', BARE = 'claude-20260801-100000', CODEX = 'codex-20260801-110000';
    const compacted = [ev({ type: 'system', subtype: 'compact_boundary', session_id: 'OLD', compact_metadata: { trigger: 'manual', pre_tokens: 800, post_tokens: 90 } }),
                       ev({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'OLD' })];
    const h = harness({ script: compacted, logs: { [DIR + OLD + '.jsonl']: logOf('claude', 'OLD', '旧'), [DIR + NEW + '.jsonl']: logOf('claude', 'NEW', '新'),
                                [DIR + BARE + '.jsonl']: logOf('claude', null, '无'), [DIR + CODEX + '.jsonl']: logOf('codex', 'T1', '码'),
                                [DIR + 'index.json']: JSON.stringify({ current: { claude: NEW }, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const bare = await h.runner.send(h.item1, '', { compact: true, conv: BARE, kind: 'chat' });
    const callsBefore = h.log.calls.length;
    h.focus(false);
    const old = await h.runner.send(h.item1, '侧重', { compact: true, conv: OLD, kind: 'chat' });
    await settle(300);
    const args = h.log.calls.at(-1).opts.arguments;
    facts.compactTarget = { bare, callsBefore, old, resumed: args[args.indexOf('--resume') + 1], stdin: h.log.stdin.at(-1), titles: h.log.notifications.map(n => n.title), bodies: h.log.notifications.map(n => n.body),
                            wrote: Object.keys(h.log.writes).filter(k => k.endsWith(OLD + '.jsonl')).length };
  }
  // an update hands a waiting compaction over as one
  {
    const log = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '问' })
      + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }) + said('答')
      + ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' });
    const h = harness({ gateFirst: true, logs: { [CONV1]: log } });
    h.runner.start('x');
    await h.runner.annotate([h.item2]); await settle(100);                  // another paper runs
    await h.runner.send(h.item1, '', { compact: true, conv: 'claude-20261001-120000', kind: 'chat' }); await settle(50);
    const waiting = h.runner.queue.filter(j => j.compact).map(j => h.runner.started(j));
    h.runner.stop(true); await settle(40);
    const carried = JSON.parse(h.store.get('extensions.scholium-bridge.carryOver'));
    const h2 = harness({ gateFirst: true, prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify(carried) }, logs: ours(h) });
    h2.runner.start('x', true); await settle(200);
    facts.compactHandover = { waiting, carried: carried.jobs.map(j => [j.key, !!j.compact]),
                              restored: [h2.runner.job && h2.runner.job.source].concat(h2.runner.queue).filter(Boolean).map(j => [j.att.key, !!j.compact]) };
    h2.runner.cancel(); await settle(100); h2.runner.stop();
  }
  // fixes of the review: the compaction keeps its conversation's result and time; it is no annotation; the update does
  // not run it twice; its words go back as typed; /compact alone and /compactify
  {
    const DIR = '/data/tmp/scholium/ATT1/conversations/';
    const log = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问', at: Date.now() - 60000 })
      + ev({ type: 'scholium', subtype: 'prompt', text: '问' })
      + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }) + said('答')
      + ev({ type: 'result', subtype: 'success', is_error: false, result: '答', session_id: 'S1' });
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
    const done = [init, ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'manual', pre_tokens: 800, post_tokens: 90 } }),
                  ev({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'S1' })];
    // the result and the time of the conversation after a compaction that began with init
    {
      const h = harness({ script: done, logs: { [CONV1]: log } });
      h.runner.start('x');
      await h.runner.send(h.item1, '', { compact: true, conv: 'claude-20261001-120000', kind: 'chat' }); await settle(300);
      const parsed = await h.runner.readLog('ATT1', 'claude-20261001-120000');
      const runs = convLines(h).filter(l => l.subtype === 'run');
      facts.afterCompactionLog = { result: parsed.result && parsed.result.result, lastAtIsTurns: parsed.lastAt === runs[0].at, runs: runs.length };
    }
    // a compaction sent on the annotation tab, the chosen agent being another one than the session's
    {
      const SESSION = 'annotate-claude-20261030-101010';
      const sessionLog = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: '批注这篇', at: Date.now() - 60000 })
        + ev({ type: 'scholium', subtype: 'prompt', text: '批注这篇', annotate: true, extra: '' })
        + ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A0' }) + said('批注好了')
        + ev({ type: 'result', subtype: 'success', is_error: false, result: '批注好了', session_id: 'A0' });
      const h = harness({ script: done, logs: { [DIR + SESSION + '.jsonl']: sessionLog,
                                                [DIR + 'index.json']: JSON.stringify({ current: {}, titles: {}, annotation: { claude: SESSION } }) } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(40);
      p.pane().agent.change('codex'); await settle(60);
      const sent = await h.runner.send(h.item1, '侧重', { compact: true, kind: 'annotate', conv: SESSION });
      await settle(300);
      facts.annotationCompaction = { sent, stdin: h.log.stdin, sessions: Object.keys(h.log.writes).filter(k => /\/annotate-/.test(k)).length };
    }
    // a compaction under way when an update lands is handed over as a compaction, its focus with it: the new copy
    // compacts again, and tells the agent nothing of an interrupted task
    {
      const h = harness({ scripts: [[init, ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }), 'WAIT']], logs: { [CONV1]: log } });
      h.runner.start('x');
      await h.runner.send(h.item1, '侧重方法', { compact: true, conv: 'claude-20261001-120000', kind: 'chat' });
      for (let i = 0; i < 3000 && !(h.runner.job && h.runner.job.delivered); i++) await tick();
      h.runner.stop(true); await settle(40);
      const carried = JSON.parse(h.store.get('extensions.scholium-bridge.carryOver'));
      const h2 = harness({ script: done, prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify(carried) }, logs: ours(h) });
      h2.runner.start('x', true); await settle(300);
      facts.compactDelivered = { carried: carried.jobs.map(j => [j.key, !!j.compact, j.resume, j.say]), stdin: h2.log.stdin,
                                 continued: convLines(h2).filter(l => l.subtype === 'continue').length };
    }
    // the words of a compaction that did not reach the agent go back as typed
    {
      const h = harness({ claudeExists: false, logs: { [CONV1]: log } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(40);
      for (const words of ['/compact 侧重方法部分', '/compact']) {
        p.pane().input.type(words); p.pane().send.click(); await settle(200);
        facts.givenBackCompaction = (facts.givenBackCompaction || []).concat([p.pane().input.value]);
        h.runner.clearInput(p.pane());
      }
    }
    // /compact on the annotation tab without a session compacts nothing and annotates nothing; /compact alone compacts;
    // /compactify is words
    {
      const h = harness({ scripts: [done, SCRIPT.concat([LAST, RESULT])], logs: { [CONV1]: log } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(40);
      const pane = p.pane();
      pane.tabAnnotate.click(); await settle(10);
      pane.input.type('/compact 侧重'); pane.send.click(); await settle(100);
      const noSession = { calls: h.log.calls.length, box: pane.input.value };
      h.runner.clearInput(pane);
      pane.tabChat.click(); await settle(10);
      pane.input.type('/compact'); pane.send.click(); await settle(300);
      const bare = h.log.stdin.at(-1);
      pane.input.type('/compactify'); pane.send.click(); await settle(300);
      facts.compactWords = { noSession, bare, words: h.log.stdin.at(-1).includes('/compactify'), plain: h.log.stdin.at(-1) !== '/compactify' };
    }
  }
  // Codex compacts with thread/compact/start in the thread it resumes, never with the words "/compact"; the compaction is a
  // turn of its own, whose end ends the run; one marker with the sizes before and after; the ring follows
  {
    const first = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
                   coItem('completed', { type: 'agentMessage', id: 'a1', text: '回答一' }),
                   usage(tok(849000, 800000, 1000), tok(849000, 800000, 1000)),
                   turnDone({ status: 'completed', durationMs: 1000 })];
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [first] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(500);
    const before = (await h.runner.readLog('ATT1', pane.shownConv)).context;
    const conv = pane.shownConv;
    h.focus(false); const ok = await h.runner.compactFromPane(pane, ''); await settle(500);
    const proc = h.log.codexProcs.at(-1);
    const sent = proc.sent.filter(m => typeof m.method === 'string').map(m => m.method);
    const lines = convLines(h);
    const log = await h.runner.readLog('ATT1', conv);
    facts.compactCodex = { ok, sent, before: before && before.used, after: pane.list.children.at(-1).textContent, ring: pane.ring.title,
                           words: proc.sent.some(m => JSON.stringify(m.params || m.result || {}).includes('/compact')), runs: pane.list.children.length,
                           exclude: (proc.sent.find(m => m.method === 'thread/resume') || { params: {} }).params.excludeTurns,
                           compacted: lines.filter(l => l.subtype === 'compacted').map(l => [l.pre, l.post]),
                           runLine: lines.filter(l => l.subtype === 'run').at(-1), turns: log.turns.map(t => [t.user, t.reply]),
                           titles: h.log.notifications.map(n => n.title).slice(-1), bodies: h.log.notifications.map(n => n.body).slice(-1) };
    // the agent's own compaction in a turn: a line without numbers
    const auto = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [[
      note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
      coItem('started', { type: 'contextCompaction', id: 'cc1' }), coItem('completed', { type: 'contextCompaction', id: 'cc1' }),
      coItem('completed', { type: 'agentMessage', id: 'a1', text: '好' }), turnDone({ status: 'completed' })]] } });
    auto.runner.start('x');
    const q = await auto.pane(auto.item1);
    await settle(40);
    q.pane().input.type('问'); q.pane().send.click(); await settle(400);
    facts.compactCodexAuto = q.pane().list.children.at(-1).children.map(c => c.textContent).filter(t => /压缩/.test(t));
    // a compaction that fails leaves no marker of sizes
    const bad = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [first], compactScript: [
      codexNote('turn/started', { threadId: 'T1', turn: { id: 'C1', status: 'inProgress' } }),
      turnDone({ id: 'C1', status: 'failed', error: { message: 'compaction failed' } })] } });
    bad.runner.start('x');
    const r = await bad.pane(bad.item1);
    await settle(40);
    r.pane().input.type('问题一'); r.pane().send.click(); await settle(500);
    await bad.runner.compactFromPane(r.pane(), ''); await settle(500);
    facts.compactCodexFailed = { after: r.pane().list.children.at(-1).textContent, marks: convLines(bad).filter(l => l.subtype === 'compacted').length };
    // a compaction under way when an update lands is handed over as the conversation going on, not as a compaction
    const wait = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [first], compactScript: ['WAIT'] } });
    wait.runner.start('x');
    const w = await wait.pane(wait.item1);
    await settle(40);
    w.pane().input.type('问题一'); w.pane().send.click(); await settle(500);
    await wait.runner.compactFromPane(w.pane(), '');
    for (let i = 0; i < 3000 && !(wait.runner.job && wait.runner.job.delivered); i++) await tick();
    wait.runner.stop(true); await settle(40);
    facts.compactCodexDelivered = JSON.parse(wait.store.get('extensions.scholium-bridge.carryOver')).jobs.map(j => [j.key, !!j.compact, j.resume]);
  }
  // the context layer's button compacts the conversation; it is greyed while the paper is busy or the conversation
  // has no session yet
  {
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                                   ev({ type: 'assistant', message: { content: [{ type: 'text', text: '好' }], usage: { input_tokens: 500000 } } }),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: '好', session_id: 'S1',
                                        modelUsage: { 'claude-opus-5-5': { contextWindow: 1000000 } } })],
                                  [ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }), 'HOLD']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问'); pane.send.click(); await settle(300);
    pane.ring.click(); await settle(10);
    const button = () => pane.popover.node.children.find(c => c.className === 'scholium-context-compact').children[0];
    const idle = { label: button().textContent, disabled: button().disabled,
                   note: pane.popover.node.children.find(c => c.className === 'scholium-context-compact').children[1].textContent };
    button().click(); await settle(50);
    const closed = pane.popover;
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    pane.ring.click(); await settle(10);
    facts.compactButton = { idle, closed, busy: button().disabled, stdin: h.log.stdin[1] };
    h.log.release(); await settle(200);
  }
  // greyed without a conversation shown, and without a size of the session
  {
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: '好', session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const disabled = () => {
      pane.ring.click();
      const d = pane.popover.node.children.find(c => c.className === 'scholium-context-compact').children[0].disabled;
      h.runner.closePopover(pane, 'context');
      return d;
    };
    pane.input.type('问'); pane.send.click(); await settle(300);
    const noSize = disabled();
    pane.context = { used: 100, window: 1000 };
    const sized = disabled();
    const conv = pane.shownConv; pane.shownConv = null;
    const noConv = disabled();
    pane.shownConv = conv;
    facts.compactButtonGreyed = { noSize, sized, noConv };
  }
  // the other tab's run of the paper greys the button too, as the compaction itself refuses then
  {
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }),
                                   ev({ type: 'assistant', message: { content: [{ type: 'text', text: '好' }], usage: { input_tokens: 500000 } } }),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: '好', session_id: 'S1',
                                        modelUsage: { 'claude-opus-5-5': { contextWindow: 1000000 } } })],
                                  [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'A1' }), 'HOLD']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问'); pane.send.click(); await settle(300);
    h.runner.annotate([h.item1]);
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await settle(20);
    pane.ring.click(); await settle(10);
    facts.compactButtonOtherTab = { tab: pane.tab, busyHere: !!pane.busy, disabled: pane.popover.node.children.find(c => c.className === 'scholium-context-compact').children[0].disabled };
    h.runner.closePopover(pane, 'context');
    h.log.release(); await settle(200);
  }
  // Steer with Codex: the words go into the turn under way (turn/steer with its id) without stopping it; they are the
  // user's in the transcript and the turn's words in the log; with Queue chosen a send while busy steers nothing, and
  // the inverted shortcut steers
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.followUpMode': 'queue' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    pane.input.type('只看第 3 节'); const tip = pane.send.title; pane.send.click(); await settle(50);          // Queue: no steer
    const queued = h.log.steers.length;
    // the words wait as a queued row, which is taken out again
    const queuedWords = { words: h.runner.queue.filter(j => j.qid).map(j => j.say), box: pane.input.value };
    h.runner.removeQueued(pane, h.runner.queue.find(j => j.qid).qid); await settle(10);
    queuedWords.after = h.runner.queue.filter(j => j.qid).length;
    const kills = h.log.codexKills;
    pane.input.type('只看第 3 节'); h.runner.sendFromPane(pane, true); await settle(100);   // the inverted shortcut: Steer
    const during = { runs: pane.list.children.length, last: pane.list.children.at(-1).children.map(c => c.className),
                     busy: pane.busy, stopped: h.log.codexKills - kills };
    const cur = h.runner.current, steerBefore = typeof cur.steer;
    const proc = h.log.codexProcs.at(-1);
    proc.emit([note('item/completed', { threadId: 'T1', turnId: 'U1', item: { type: 'agentMessage', id: 'm1', text: '好的' } }),
               turnDone({ id: 'U1', status: 'completed' })]);
    await settle(400);
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    const prompts = run => run.children.filter(c => c.className === 'scholium-entry prompt').map(c => c.textContent);
    facts.steerCodex = {
      steerFn: [steerBefore, typeof cur.steer], tip, queued, queuedWords, steers: h.log.steers.map(s => [s.threadId, s.expectedTurnId, s.input]), input: pane.input.value, during,
      runs: pane.list.children.map(r => [prompts(r), r.children.some(c => c.className === 'scholium-meta')]),
      lines: convLines(h).filter(l => l.subtype === 'steer').map(l => l.text), turns: log.turns.map(t => [t.user, t.reply]),
      reread: (await h.runner.readLog('ATT1', pane.shownConv)).entries.filter(e => e.kind === 'prompt').map(e => [e.text, !!e.steer]),
    };
    // a steer after the turn ended: nothing is steered, the words go as a turn of their own
    const late = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' } });
    late.runner.start('x');
    const q = await late.pane(late.item1);
    await settle(40);
    q.pane().input.type('问题一'); q.pane().send.click(); await settle(400);
    q.pane().input.type('晚了'); late.runner.sendFromPane(q.pane(), true); await settle(50);
    facts.steerLate = { steers: late.log.steers.length, input: q.pane().input.value, lines: convLines(late).filter(l => l.subtype === 'steer').length };
  }
  // what can be steered: the busy paper's own turn on the tab of its kind, and a job of that paper and kind; never a
  // compaction, nor the other tab, nor a turn over
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const idle = h.runner.steerable(pane);
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    const job = (key, kind) => ({ att: { key }, kind });
    const own = [h.runner.steerable(pane), h.runner.steerable(pane, job('ATT1', 'chat')), h.runner.steerable(pane, job('ATT1')),
                 h.runner.steerable(pane, job('OTHER', 'chat')), h.runner.steerable(pane, job('ATT1', 'annotate'))];
    pane.tabAnnotate.click(); await settle(20);
    const otherTab = h.runner.steerable(pane);
    pane.tabChat.click(); await settle(20);
    const source = h.runner.job.source;
    source.compact = true;
    const compacting = h.runner.steerable(pane);
    source.compact = false;
    facts.steerable = { idle, own, otherTab, compacting };
    h.runner.cancel(); await settle(100);
  }
  // a refused steer (the turn is over on the server) queues the words, and the log has no steer line
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.followUpMode': 'steer' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']],
                                 refuse: { 'turn/steer': 'no active turn to steer' } } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    pane.input.type('晚了'); pane.send.click(); await settle(100);
    facts.steerRefused = { input: pane.input.value, lines: convLines(h).filter(l => l.subtype === 'steer').length, runs: pane.list.children.length,
                           queued: h.runner.queue.filter(j => j.qid).map(j => j.say) };
    for (const j of h.runner.queue.filter(j => j.qid)) h.runner.removeQueued(pane, j.qid);
    h.runner.cancel(); await settle(100);
  }
  // Claude Code cannot be steered: its follow-ups are never steered, with Steer chosen as well
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.followUpMode': 'steer' }, script: SCRIPT.concat(['HOLD', LAST, RESULT]) });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    pane.input.type('追问'); const tip = pane.send.title; pane.send.click(); await settle(50);
    // its queued row: Steer greyed, with the reason
    const queued = pane.queueBox.children.find(c => c.className.startsWith('scholium-queued'));
    const steer = queued ? [queued.children[2].textContent, !!queued.children[2].disabled, queued.children[2].title] : null;
    facts.steerClaude = { can: h.runner.canSteer('claude'), steerable: h.runner.steerable(pane), follow: h.runner.followUpFor(pane), tip,
                          steers: h.log.steers.length, writes: h.log.stdin.length, steer };
    for (const j of h.runner.queue.filter(j => j.qid)) h.runner.removeQueued(pane, j.qid);
    h.log.release(); await settle(300);
  }
  // an annotation steered from its tab: its words open a new segment that goes on with the annotation, whose one card
  // stays on the last segment
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); pane.input.type('只批注第 3 页'); pane.annotGo.click(); await settle(400);
    pane.input.type('也看第 5 页'); h.runner.sendFromPane(pane, true); await settle(100);
    const cards = () => pane.annot.list.children.flatMap((r, i) => r.children.filter(c => /^scholium-card/.test(c.className)).map(c => [i, c.className]));
    const during = { runs: pane.annot.list.children.length, cards: cards(), steers: h.log.steers.map(s => s.input[0].text) };
    const proc = h.log.codexProcs.at(-1);
    proc.emit([note('item/completed', { threadId: 'T1', turnId: 'U1', item: { type: 'agentMessage', id: 'm1', text: '批注好了' } }),
               turnDone({ id: 'U1', status: 'completed' })]);
    await settle(500);
    const prompts = run => run.children.filter(c => c.className === 'scholium-entry prompt').map(c => c.textContent);
    facts.steerAnnotation = { during, runs: pane.annot.list.children.map(r => prompts(r)), cards: cards(), runCount: pane.annot.list.children.length,
                              retries: pane.annot.list.children.flatMap(r => r.children).filter(c => c.className.includes('retry')).length };
  }
  // the chat's retry: a steered turn that failed offers Retry once, on its last segment
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    pane.input.type('只看第 3 节'); h.runner.sendFromPane(pane, true); await settle(100);
    h.log.codexProcs.at(-1).emit([turnDone({ id: 'U1', status: 'failed', error: { message: '失败了' } })]);
    await settle(500);
    const retries = run => run.children.flatMap(c => [c, ...c.children]).filter(c => c.className.includes('retry')).length;
    facts.steerFailedChat = pane.list.children.map(r => retries(r));
  }
  // ---- queued messages, as Codex queues a follow-up ----
  const qInit = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
  const qDone = n => ev({ type: 'result', subtype: 'success', is_error: false, result: '答' + n, session_id: 'S1' });
  const qReply = n => [qInit, said('答' + n), qDone(n)];
  const qHeld = n => [qInit, 'HOLD', said('答' + n), qDone(n)];   // held before its answer until log.release()
  // the outcome of each run, as drain() reads it
  const outcomes = h => {
    const out = [], run = h.runner.run;
    h.runner.run = async function (job) {
      const o = await run.call(this, job);
      out.push(o ? { ok: o.ok, delivered: o.delivered, cancelled: o.cancelled } : null);
      return o;
    };
    return out;
  };
  const qrows = pane => pane.queueBox.children.filter(c => c.className.startsWith('scholium-queued'));
  const untilRelease = async h => { for (let i = 0; i < 3000 && !h.log.release; i++) await tick(); };
  const nextRelease = async (h, was) => { for (let i = 0; i < 3000 && h.log.release === was; i++) await tick(); await settle(10); };
  const running = async h => { for (let i = 0; i < 3000 && !(h.runner.current && h.log.stdin.length >= 1); i++) await tick(); };
  // follow-ups while the paper runs: rows in the box above the text, in order; dragged, removed and brought back,
  // taken back to the box to edit; each goes when the answer before it ends
  {
    const reply = n => [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), said('答' + n),
                        ev({ type: 'result', subtype: 'success', is_error: false, result: '答' + n, session_id: 'S1' })];
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), 'HOLD',
                                   said('答1'), ev({ type: 'result', subtype: 'success', is_error: false, result: '答1', session_id: 'S1' })],
                                  reply(2), reply(3)] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const rows = () => pane.queueBox.children.filter(c => c.className.startsWith('scholium-queued')).map(r => r.children[1].textContent);
    const row = text => pane.queueBox.children.find(c => c.className.startsWith('scholium-queued') && c.children[1].textContent === text);
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    // a compaction or a retry is no message to queue: refused while the paper runs
    const refused = [await h.runner.send(h.item1, '', { compact: true, conv: pane.shownConv, kind: 'chat' }),
                     await h.runner.send(h.item1, '问题一', { retry: true, conv: pane.shownConv, kind: 'chat', agent: 'claude' }), h.runner.queue.length];
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.input.type('追问三'); pane.send.click(); await settle(20);
    const first = { rows: rows(), input: pane.input.value, buttons: row('追问二').children.slice(2).map(b => b.textContent) };
    const qids = h.runner.queue.map(j => j.qid);
    row('追问三').children[0].fire('dragstart'); const over = row('追问二').fire('dragover'); const drop = row('追问二').fire('drop'); await settle(10);
    const dragged = rows();
    row('追问二').children[3].click(); await settle(10);                       // ✕
    const removed = { rows: rows(), undo: pane.queueBox.children.find(c => c.className.includes('removed')).textContent };
    pane.queueBox.children.find(c => c.className.includes('removed')).children[1].click(); await settle(10);   // 撤销
    const back = rows();
    // a click on its text shows the whole message, a second one its line again
    row('追问二').children[1].click(); await settle(5);
    const expanded = [row('追问二').className, row('追问三').className];
    row('追问二').children[1].click(); await settle(5);
    expanded.push(row('追问二').className);
    row('追问三').children[4].click(); await settle(10);                       // ⋯
    const menu = pane.popover.node.children.map(c => [c.textContent, !!c.disabled]);
    pane.input.focused = false;
    pane.popover.node.children[0].click(); await settle(10);                    // 编辑消息
    const edited = { rows: rows(), input: pane.input.value };
    const box = { focused: !!pane.input.focused, kept: [...h.runner.unsent.values()].includes('追问三') };
    pane.send.click(); await settle(20);
    h.log.release(); await settle(1200);
    // each goes on with the session of the answer before it
    const resumed = h.log.calls.slice(1).map(c => c.opts.arguments[c.opts.arguments.indexOf('--resume') + 1]);
    facts.queue = { refused, first, qids, dragged, over: !!over.prevented, prevented: !!drop.prevented, removed, back, expanded, menu, edited, box, resumed,
                    stdin: h.log.stdin.map(s => ['追问三', '追问二', '问题一'].find(w => s.includes(w))), after: rows() };
  }
  // a stop holds the queue: a line with Go on, Send on each row; a new message first asks whether to clear the queue
  {
    const hold = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), 'WAIT'];   // a stop ends it
    const ok = n => [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), said('答' + n),
                     ev({ type: 'result', subtype: 'success', is_error: false, result: '答' + n, session_id: 'S1' })];
    const h = harness({ scripts: [hold, ok(2), ok(3)] });
    const outs = outcomes(h);
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !(h.runner.current && h.log.stdin.length >= 1); i++) await tick();
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                      // ■
    const held = { line: pane.queueBox.children[0].textContent, row: pane.queueBox.children[1].children[2].textContent,
                   calls: h.log.calls.length, round: pane.send.textContent };
    // the paper is idle meanwhile
    const idle = { state: p.view().state, busy: h.runner.busy('ATT1', 'chat'), any: h.runner.busy('ATT1'), newChat: pane.newChat.disabled };
    pane.input.type('新消息'); pane.send.click(); await settle(20);
    const ask = pane.confirmRow.children.map(c => c.textContent);
    pane.confirmRow.children[2].click(); await settle(800);                    // 发送消息: it goes, and the queue goes on after it, as in Codex
    const sent = { first: h.log.stdin[1].includes('新消息') && !h.log.stdin[1].includes('追问二'), then: !!h.log.stdin[2] && h.log.stdin[2].includes('追问二') };
    facts.held = { held, idle, ask, sent, rows: pane.queueBox.children.length, released: h.runner.heldQueues.size, outcome: outs[0] };
  }
  // a queued message that could not be sent: ⚠ and Retry; the messages after it wait
  {
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), 'HOLD',
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: '答1', session_id: 'S1' })],
                                  [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), said('答2'),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: '答2', session_id: 'S1' })]] });
    const outs = outcomes(h);
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.input.type('追问三'); pane.send.click(); await settle(20);
    const find = h.runner.findClaude;
    h.runner.findClaude = async () => null;
    h.log.release(); await settle(600);
    const row = pane.queueBox.children.find(c => c.className.startsWith('scholium-queued'));
    const failed = { cls: row.className, text: row.children[1].textContent, tip: row.children[1].title, button: row.children[2].textContent,
                     waiting: h.runner.queue.filter(j => j.qid).map(j => j.say), input: pane.input.value,
                     // its Retry is on its row only
                     retries: pane.list.children.flatMap(r => r.children.flatMap(c => [c, ...c.children])).filter(c => c.className.includes('retry')).length };
    h.runner.findClaude = find;
    row.children[2].click(); await settle(600);
    facts.queueFailed = { failed, sent: h.log.stdin[1].includes('追问二') && !h.log.stdin[1].includes('追问三'), outcomes: outs.slice(0, 2) };
  }
  // a failed message deleted, or taken back to the box, lets the queue go on
  for (const how of ['delete', 'edit']) {
    const h = harness({ scripts: [qHeld(1), qReply(3)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.input.type('追问三'); pane.send.click(); await settle(20);
    const find = h.runner.findClaude;
    h.runner.findClaude = async () => null;
    h.log.release(); await settle(600);
    h.runner.findClaude = find;
    const row = qrows(pane)[0];
    if (how === 'delete') row.children[3].click();
    else { pane.input.type('另外'); row.children[4].click(); await settle(5); pane.popover.node.children[0].click(); }   // before what is typed
    await settle(600);
    (facts.queueFailedGone = facts.queueFailedGone || {})[how] = {
      sent: h.log.stdin.length === 2 && h.log.stdin[1].includes('追问三') && !h.log.stdin[1].includes('追问二'), input: pane.input.value, rows: qrows(pane).length };
  }
  // with Codex, Steer on a row puts its words into the turn under way and takes the row out; ⋯ offers Turn off queueing
  // until Steer is the follow-up behaviour
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.followUpMode': 'queue' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    const row = () => qrows(pane)[0];
    const b = row().children[2];
    const steer = [b.textContent, !!b.disabled, b.title];
    row().children[4].click(); await settle(5);
    const menu = pane.popover.node.children.map(c => [c.textContent, !!c.disabled]);
    pane.popover.node.children[1].click(); await settle(5);                    // 关闭排队
    const mode = h.store.get('extensions.scholium-bridge.followUpMode');
    row().children[4].click(); await settle(5);
    const menuSteer = pane.popover.node.children.map(c => !!c.disabled);
    h.runner.closePopover(pane);
    row().children[2].click(); await settle(100);                              // 引导
    facts.queueCodex = { steer, menu, mode, menuSteer, steers: h.log.steers.map(s => s.input[0].text), rows: pane.queueBox.children.length,
                         queue: h.runner.queue.length, lines: convLines(h).filter(l => l.subtype === 'steer').map(l => l.text) };
    h.runner.cancel(); await settle(100);
    // Codex refuses: the row stays
    const g = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']], refuse: { 'turn/steer': 'no active turn to steer' } } });
    g.runner.start('x');
    const q = await g.pane(g.item1); await settle(40);
    const gp = q.pane();
    gp.input.type('问题一'); gp.send.click(); await settle(400);
    gp.input.type('追问二'); gp.send.click(); await settle(20);
    qrows(gp)[0].children[2].click(); await settle(100);                     // 引导
    facts.queueCodex.refused = { rows: qrows(gp).map(r => r.children[1].textContent), queue: g.runner.queue.filter(j => j.qid).length };
    g.runner.dequeue(['ATT1']); g.runner.cancel(); await settle(100);
  }
  // a queued message being sent says so on its row, until its agent has it; one stopped before then comes back as no row
  {
    const h = harness({ scripts: [qHeld(1), [qInit, 'HOLD', said('答2'), 'HOLD', qDone(2)]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    const r1 = h.log.release; r1(); await nextRelease(h, r1);                // the second run, before its answer
    const r = qrows(pane)[0];
    const sending = r ? [r.className, r.children[1].textContent, r.children[2].textContent, r.children.length] : null;
    const r2 = h.log.release; r2(); await nextRelease(h, r2);                // its answer has come
    const delivered = pane.queueBox.children.length;
    h.log.release(); await settle(300);
    const g = harness({ scripts: [qHeld(1), [qInit, 'WAIT']] });
    const outs = outcomes(g);
    g.runner.start('x');
    const q = await g.pane(g.item1); await settle(40);
    const gp = q.pane();
    gp.input.type('问题一'); gp.send.click(); await untilRelease(g);
    gp.input.type('追问二'); gp.send.click(); await settle(20);
    g.log.release();
    for (let i = 0; i < 3000 && g.log.stdin.length < 2; i++) await tick();
    await settle(20);
    gp.send.click(); await settle(300);                                       // ■
    facts.queueSending = { sending, delivered, stopped: { rows: gp.queueBox.children.length, queue: g.runner.queue.length, outcome: outs[1] } };
  }
  // a follow-up to a new conversation's first question goes to that conversation, queued before the conversation had its
  // log or after, also when New chat was chosen while the queue was held; that conversation is the current one then
  facts.queuePointed = {};
  for (const when of ['before', 'after']) {
    const h = harness({ holdDirs: true, scripts: [[qInit, said('答1'), 'WAIT'], qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const pump = async n => { for (let i = 0; i < n; i++) { if (h.log.releaseDir) { const r = h.log.releaseDir; h.log.releaseDir = null; r(); } await tick(); } };
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.releaseDir; i++) await tick();
    if (when === 'before') { pane.input.type('追问二'); pane.send.click(); await settle(20); }
    const conv = h.runner.queue.map(j => j.conv);
    await pump(1);
    await running(h); await settle(20);
    if (when === 'after') { pane.input.type('追问二'); pane.send.click(); await settle(20); }
    const first = pane.shownConv;
    pane.send.click(); await settle(300);                                     // ■
    await h.runner.newChat(pane); await settle(20);
    // the new chat shows none of the old conversation's rows, nor its held line
    const fresh = { shown: pane.shownConv, current: (await h.runner.index('ATT1')).current.claude, rows: pane.queueBox.children.length, hidden: pane.queueBox.hidden };
    await h.runner.openConv(pane, { key: 'ATT1', agent: 'claude', id: first }); await settle(20);   // back from History
    const back = pane.queueBox.children.map(c => c.className);
    pane.queueBox.children[0].children[1].click();                            // 继续
    await pump(3000); await settle(300);
    facts.queuePointed[when] = { conv, first: !!first, fresh, back, logs: convs(h).length,
                                 prompts: convLines(h).filter(l => l.subtype === 'prompt').map(l => l.text), shown: pane.shownConv === first };
  }
  // a held row resumed while another conversation is the current one goes to its own
  {
    const h = harness({ scripts: [[qInit, said('答1'), 'WAIT'], qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    const convA = pane.shownConv;
    pane.input.type('追问A'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■
    await h.runner.newChat(pane); await settle(20);                           // the current conversation: none
    h.runner.releaseQueue(h.runner.queue.find(j => j.qid)); await settle(400);
    const lines = (h.log.writes['/data/tmp/scholium/ATT1/conversations/' + convA + '.jsonl'] || '').trim().split('\n').filter(Boolean).map(l => JSON.parse(l));
    facts.queueOwnConv = { logs: convs(h).length, a: lines.filter(l => l.subtype === 'prompt').map(l => l.text) };
  }
  // queued rows are per conversation: another conversation's run, its rows and its hold go on their own; the clear-queue
  // question counts the shown conversation's rows only
  {
    const bInit = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S2' });
    const h = harness({ scripts: [[qInit, said('答1'), 'WAIT'], [bInit, said('B答'), 'WAIT'],
                                  [bInit, said('B答2'), ev({ type: 'result', subtype: 'success', is_error: false, result: 'B答2', session_id: 'S2' })], qReply(4)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const texts = () => qrows(pane).map(r => r.children[1].textContent);
    pane.input.type('问题一'); pane.send.click(); await running(h);
    const convA = pane.shownConv;
    pane.input.type('追问A'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■: A's row held
    await h.runner.newChat(pane); await settle(20);
    pane.input.type('B问'); pane.send.click(); await settle(20);             // no question: the new chat has no rows
    const asked = !pane.confirmRow.hidden;
    for (let i = 0; i < 3000 && h.log.stdin.length < 2; i++) await tick();
    await settle(20);
    const convB = pane.shownConv;
    pane.input.type('B追问'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■: B's row held
    const line = () => (pane.queueBox.children[0] || {}).className || null;
    const resume = () => { const l = pane.queueBox.children[0]; if (l && l.children[1]) l.children[1].click(); };
    const inB = { rows: texts(), line: line() };
    // a row does not move into another conversation's queue
    h.runner.moveQueued(h.runner.queue.find(j => j.say === 'B追问').qid, h.runner.queue.find(j => j.say === '追问A').qid); await settle(5);
    inB.cross = h.runner.queue.filter(j => j.qid).map(j => j.say);
    resume(); await settle(500);                                             // 继续, in B: B's row only
    const afterB = { held: h.runner.heldQueues.size, calls: h.log.stdin.length, last: (h.log.stdin.at(-1) || '').includes('B追问') };
    await h.runner.openConv(pane, { key: 'ATT1', agent: 'claude', id: convA }); await settle(20);
    const inA = { rows: texts(), line: line() };
    resume(); await settle(500);                                             // 继续, in A
    const prompts = path => (h.log.writes[path] || '').trim().split('\n').filter(Boolean).map(l => JSON.parse(l))
      .filter(l => l.subtype === 'prompt').map(l => l.text);
    const dir = '/data/tmp/scholium/ATT1/conversations/';
    facts.queuePerConv = { asked, two: !!convA && !!convB && convA !== convB, inB, afterB, inA, held: h.runner.heldQueues.size,
                           a: prompts(dir + convA + '.jsonl'), b: prompts(dir + convB + '.jsonl') };
  }
  // an update hands the queued messages over with their numbers, a failed one as failed, and a held queue held; a queued
  // message its agent has goes on as a continuation, without a row
  {
    const h = harness({ scripts: [[qInit, 'WAIT'], [qInit, said('答'), 'HOLD', qDone(2)]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.input.type('追问三'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■: held
    h.runner.queue[1].failed = true;
    h.runner.send(h.item1, '新消息', { kind: 'chat' }); await untilRelease(h);   // a message past the question, as a Retry goes: the queue stays held
    pane.input.type('再一条'); pane.send.click(); await settle(20);         // while it runs: queued, held, without the question
    const busyAsk = !pane.confirmRow.hidden;
    h.runner.stop(true); await settle(40);
    const carried = JSON.parse(h.store.get('extensions.scholium-bridge.carryOver'));
    const h2 = harness({ prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify(carried) }, logs: ours(h), scripts: [[qInit, said('续'), qDone(3)]] });
    h2.runner.start('x', true); await settle(300);
    const q = await h2.pane(h2.item1); await settle(40);
    facts.queueHandover = { busyAsk, carried: carried.jobs.map(j => [j.say, j.qid, !!j.failed]), held: carried.held,
                            restored: h2.runner.queue.filter(j => j.qid).map(j => [j.say, j.qid, !!j.failed]), heldAfter: [...h2.runner.heldQueues],
                            qseq: h2.runner.qseq, rows: q.pane().queueBox.children.map(c => c.className), calls: h2.log.calls.length };
    const g = harness({ scripts: [qHeld(1), [qInit, said('答2'), 'HOLD', qDone(2)]] });
    g.runner.start('x');
    const r = await g.pane(g.item1); await settle(40);
    const gp = r.pane();
    gp.input.type('问题一'); gp.send.click(); await untilRelease(g);
    gp.input.type('追问二'); gp.send.click(); await settle(20);
    const r1 = g.log.release; r1(); await nextRelease(g, r1);                 // 追问二's agent has it
    g.runner.stop(true); await settle(40);
    facts.queueHandover.running = JSON.parse(g.store.get('extensions.scholium-bridge.carryOver')).jobs.map(j => [j.say, j.qid, j.resume]);
  }
  // Send on a row of a held queue: that message first, then the rest
  {
    const h = harness({ scripts: [[qInit, 'WAIT'], qReply(2), qReply(3)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.input.type('追问三'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■
    qrows(pane).find(r => r.children[1].textContent === '追问三').children[2].click(); await settle(800);   // 发送
    facts.queueSendNow = { order: h.log.stdin.slice(1).map(s => ['追问二', '追问三'].find(w => s.includes(w))), held: h.runner.heldQueues.size,
                           rows: pane.queueBox.children.length };
  }
  // a held queue whose last row is deleted lets go once the row can no longer be brought back
  {
    const h = harness({ scripts: [[qInit, 'WAIT'], qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■
    qrows(pane)[0].children[3].click(); await settle(10);                    // ✕
    const during = { held: h.runner.heldQueues.size, rows: pane.queueBox.children.map(c => c.className) };
    h.fire(); await settle(10);                                               // the time to undo is over
    const after = { held: h.runner.heldQueues.size, rows: pane.queueBox.children.length, removed: h.runner.removedQueued.size, hidden: pane.queueBox.hidden };
    pane.input.type('新消息'); pane.send.click(); await settle(300);
    facts.queueEmptied = { during, after, asked: !pane.confirmRow.hidden, sent: h.log.stdin.length };
  }
  // Clear queue: the held messages go, the new one is sent, and the queue is no longer held
  {
    const h = harness({ scripts: [[qInit, 'WAIT'], qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■
    pane.input.type('新消息'); pane.send.click(); await settle(20);
    pane.confirmRow.children[1].click(); await settle(400);                  // 清空队列
    facts.queueCleared = { queue: h.runner.queue.length, held: h.runner.heldQueues.size, rows: pane.queueBox.children.length,
                           sent: h.log.stdin.length === 2 && h.log.stdin[1].includes('新消息'), input: pane.input.value };
  }
  // a message deleted while the paper ran and brought back after its run ended is sent
  {
    const h = harness({ scripts: [qHeld(1), qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    qrows(pane)[0].children[3].click(); await settle(10);                    // ✕
    h.log.release(); await settle(300);
    const idle = h.log.stdin.length;
    pane.queueBox.children.find(c => c.className.includes('removed')).children[1].click(); await settle(300);   // 撤销
    facts.queueUndone = { idle, sent: h.log.stdin.length === 2 && h.log.stdin[1].includes('追问二'), rows: pane.queueBox.children.length };
  }
  // a queued message the agent had is no row any more: waiting for its second try, for the limit, or sent again in a
  // new session; one whose run failed with the agent's answer is no failed row
  {
    const conn = [qInit, ev({ type: 'result', subtype: 'success', is_error: true, result: 'API Error: Connection error.', session_id: 'S1' })];
    const boom = [qInit, said('部分'), ev({ type: 'result', subtype: 'error_during_execution', is_error: true, errors: ['boom'], session_id: 'S1' }), 'EXIT:1'];
    facts.queueAgain = {};
    for (const [name, second] of Object.entries({ retry: conn, limit: LIMIT_HIT, gone: CLAUDE_GONE, answered: boom })) {
      const h = harness({ scripts: [qHeld(1), second, qReply(3)] });
      if (name === 'retry') h.runner.NET_RETRY_MS = 60000;
      const starts = [], run = h.runner.run;
      h.runner.run = async function (job) { starts.push(job.qid || null); return run.call(this, job); };
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
      pane.input.type('追问二'); pane.send.click(); await settle(20);
      h.log.release(); await settle(500);
      facts.queueAgain[name] = { starts: starts.slice(), queue: h.runner.queue.map(j => j.qid || null), rows: pane.queueBox.children.length };
      if (name === 'retry') { h.runner.queue[0].retryAt = 0; await settle(400); }
      h.runner.dequeue(['ATT1']); await settle(20);
    }
  }
  // a queued message whose run broke before its log had it waits, failed
  {
    const h = harness({ scripts: [qHeld(1), qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    const find = h.runner.findClaude;
    h.runner.findClaude = async () => { throw Error('disk full'); };
    h.log.release(); await settle(500);
    const row = qrows(pane)[0];
    const failed = row ? [row.className, row.children[1].textContent,
                          pane.list.children.flatMap(r => r.children.flatMap(c => [c, ...c.children])).filter(c => c.className.includes('retry')).length] : null;
    h.runner.findClaude = find;
    if (row) { row.children[2].click(); await settle(500); }
    facts.queueThrown = { failed, input: pane.input.value, sent: h.log.stdin.length === 2 && h.log.stdin[1].includes('追问二') };
  }
  // a queued message that failed after its log had it (Codex did not start): the row waits failed, the transcript offers
  // no second Retry, and Retry on the row goes on with its own turn
  {
    const refuse = {};
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { refuse, scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT'],
                                                   [note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    refuse.initialize = 'refused by the server';
    h.log.codexProcs.at(-1).emit([note('item/completed', { threadId: 'T1', turnId: 'U1', item: { type: 'agentMessage', id: 'm1', text: '答1' } }),
                                  turnDone({ id: 'U1', status: 'completed' })]);
    await settle(600);
    const row = qrows(pane)[0];
    const retries = () => pane.list.children.flatMap(r => r.children.flatMap(c => [c, ...c.children])).filter(c => c.className.includes('retry')).length;
    const failed = { cls: row ? row.className : null, retries: retries() };
    delete refuse.initialize;
    if (row) { row.children[2].click(); await settle(600); }
    const during = qrows(pane).length;                                        // its turn has it: no row says it is being sent
    h.log.codexProcs.at(-1).emit([note('item/completed', { threadId: 'T1', turnId: 'U2', item: { type: 'agentMessage', id: 'm2', text: '答2' } }),
                                  turnDone({ id: 'U2', status: 'completed' })]);
    await settle(400);
    const lines = convLines(h);
    facts.queueCodexFailed = { failed, during, runs: lines.filter(l => l.subtype === 'run').map(l => l.user),
                               prompts: lines.filter(l => l.subtype === 'prompt').map(l => l.text), rows: qrows(pane).length };
  }
  // a follow-up joins the queue after what waits for its paper, else before the papers waiting for their first run
  {
    const h = harness({ scripts: [qHeld(1)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    await h.runner.annotate([h.item2]); await settle(20);                     // another paper waits for its first run
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.input.type('追问三'); pane.send.click(); await settle(20);
    facts.queueOrder = h.runner.queue.map(j => (j.qid ? j.say : j.att.key));
    h.runner.dequeue(['ATT1', 'ATT2']); h.log.release(); await settle(300);
  }
  // words to the annotation tab while its annotation waits behind another paper: after that annotation, Steer greyed
  // with nothing to steer yet; ■ takes the annotation out of the queue and holds the words
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    await h.runner.annotate([h.item2]); await settle(400);                    // another paper's annotation runs
    await h.runner.annotate([h.item1]); await settle(20);                     // this paper's waits
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(5);
    pane.input.type('只看第 3 页'); pane.send.click(); await settle(20);
    const order = h.runner.queue.map(j => (j.qid ? 'Q:' : '') + j.att.key + '/' + j.kind);
    const row = qrows(pane)[0];
    const tip = row ? [!!row.children[2].disabled, row.children[2].title] : null;
    pane.send.click(); await settle(50);                                      // ■
    facts.queueWaiting = { order, tip, after: h.runner.queue.map(j => (j.qid ? 'Q:' : '') + j.att.key), held: [...h.runner.heldQueues],
                           line: pane.queueBox.children.length ? pane.queueBox.children[0].className : null, round: pane.send.textContent };
    h.runner.dequeue(['ATT1']); h.runner.cancel(); await settle(200);
  }
  // ---- review fix round 1 ----
  const yInit = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S2' });
  const names = h => h.runner.queue.map(j => (j.qid ? 'Q:' + j.say : (j.say || j.att.key) + (j.retried ? '(retry)' : '')));
  const undoRow = pane => pane.queueBox.children.find(c => c.className.includes('removed')).children[1].click();
  // Send message while another paper's run goes: the new message goes ahead of the held queue, which goes on after it
  {
    const last = s => ['新消息', '追问二', '问题一'].map(w => [w, String(s).lastIndexOf(w)]).filter(x => x[1] >= 0).sort((a, b) => b[1] - a[1]).map(x => x[0])[0] || 'other';
    const h = harness({ scripts: [[qInit, 'WAIT'], SCRIPT.concat(['HOLD', LAST, RESULT]), qReply(2), qReply(3)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    await h.runner.annotate([h.item2]); await settle(20);
    pane.send.click(); await settle(300);                                     // ■: A's row held; B's annotation runs
    await untilRelease(h);
    pane.input.type('新消息'); pane.send.click(); await settle(20);
    pane.confirmRow.children[2].click(); await settle(200);                  // 发送消息
    const queued = { queue: names(h), held: h.runner.heldQueues.size };
    h.log.release(); await settle(2000);
    facts.queueSendPastRun = { queued, stdin: h.log.stdin.map(last) };
  }
  // Undo puts a row back into its own queue: before the row that followed it, else after the last row of its queue, else
  // behind what waits for its paper, never ahead of its paper's second try
  {
    const conn = [qInit, 'HOLD', ev({ type: 'result', subtype: 'success', is_error: true, result: 'API Error: Connection error.', session_id: 'S1' })];
    const h = harness({ scripts: [conn, qReply(2)] });
    h.runner.NET_RETRY_MS = 60000;
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    qrows(pane)[0].children[3].click(); await settle(10);                    // ✕
    h.log.release(); await settle(300);                                       // the connection fails: the second try waits
    undoRow(pane); await settle(50);
    const retry = { queue: names(h), runs: h.log.calls.length };
    h.runner.dequeue(['ATT1']); await settle(50);
    const g = harness({ scripts: [qHeld(1), qHeld(2), qReply(3), qReply(4)] });
    g.runner.start('x');
    const q = await g.pane(g.item1); await settle(40);
    const gp = q.pane();
    const rowOf = w => qrows(gp).find(r => r.children[1].textContent === w);
    gp.input.type('问题一'); gp.send.click(); await untilRelease(g);
    for (const w of ['追问一', '追问二', '追问三']) { gp.input.type(w); gp.send.click(); await settle(20); }
    rowOf('追问二').children[3].click(); await settle(10);                   // ✕
    const r1 = g.log.release; r1(); await nextRelease(g, r1);                // 追问一 runs, 追问三 waits
    undoRow(gp); await settle(20);
    const swapped = names(g);
    rowOf('追问三').children[3].click(); await settle(10);                   // ✕ the last row
    gp.input.type('追问四'); gp.send.click(); await settle(20);
    await g.runner.annotate([g.item1]); await settle(20);                     // the paper's annotation waits behind them
    undoRow(gp); await settle(20);
    const lastRow = names(g);
    g.runner.dequeue(['ATT1']); g.log.release(); await settle(300);
    facts.queueUndoOrder = { retry, swapped, lastRow };
  }
  // a failed message goes back before the first row left of its own queue, whatever left the queue meanwhile
  {
    const h = harness({ scripts: [[qInit, said('答1'), 'WAIT'], [yInit, 'HOLD', said('答Y'), ev({ type: 'result', subtype: 'success', is_error: false, result: '答Y', session_id: 'S2' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('X追问'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■: X's row held
    const hx = h.runner.queue.find(j => j.qid).qid;
    await h.runner.newChat(pane); await settle(20);
    pane.input.type('Y问'); pane.send.click(); await untilRelease(h);
    for (const w of ['R一', 'R二']) { pane.input.type(w); pane.send.click(); await settle(20); }
    let found = null;
    const find = h.runner.findClaude;
    h.runner.findClaude = () => new Promise(r => { if (!found) found = r; else r(null); });
    h.log.release();
    for (let i = 0; i < 3000 && !found; i++) await tick();                    // R一's run looks for Claude Code
    h.runner.removeQueued(pane, hx); await settle(10);                         // X's row goes meanwhile
    if (found) found(null);
    await settle(300);
    facts.queueFailedPlace = names(h);
    h.runner.findClaude = find;
    h.runner.dequeue(['ATT1']); await settle(20);
  }
  // a failed row of one conversation leaves the Retry of another conversation's failed run
  {
    const h = harness({ scripts: [qHeld(1), [yInit, ev({ type: 'result', subtype: 'error_during_execution', is_error: true, errors: ['boom'], session_id: 'S2' }), 'EXIT:1']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    const find = h.runner.findClaude;
    h.runner.findClaude = async () => null;
    h.log.release(); await settle(500);                                       // 追问二 fails: a failed row in A
    h.runner.findClaude = find;
    await h.runner.newChat(pane); await settle(20);
    pane.input.type('B问'); pane.send.click(); await settle(600);            // B's run fails without an answer
    const retries = pane.list.children.flatMap(r => r.children.flatMap(c => [c, ...c.children])).filter(c => c.className.includes('retry')).length;
    facts.queueRetryPerConv = { failedA: h.runner.queue.filter(j => j.failed).length, rows: qrows(pane).length, retries };
  }
  // stop() lets go of the queue's state: held queues, rows to bring back and their timers, the numbering
  {
    const h = harness({ scripts: [[qInit, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    for (const w of ['追问二', '追问三']) { pane.input.type(w); pane.send.click(); await settle(20); }
    pane.send.click(); await settle(300);                                     // ■
    qrows(pane)[1].children[3].click(); await settle(10);                    // ✕
    const state = () => ({ held: h.runner.heldQueues.size, removed: h.runner.removedQueued.size, qseq: h.runner.qseq, timer: h.live().includes(5000) });
    const before = state();
    h.runner.stop(); await settle(20);
    facts.queueStop = { before, after: state() };
  }
  // dragging: the row being sent takes no drop; a row moves within its own queue only, never to the end of the queue;
  // the drag ends with dragend
  {
    const h = harness({ scripts: [qHeld(1), [qInit, 'HOLD', said('答2'), qDone(2)]] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const rowOf = w => qrows(pane).find(r => r.children[1].textContent === w);
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    for (const w of ['追问二', '追问三', '追问四']) { pane.input.type(w); pane.send.click(); await settle(20); }
    await h.runner.annotate([h.item2]); await settle(20);                     // another paper waits behind them
    const r1 = h.log.release; r1(); await nextRelease(h, r1);                // 追问二 is being sent
    const sending = qrows(pane).find(r => r.className.includes('sending'));
    const target = { draggable: sending.children[0].getAttribute('draggable'), drops: (sending.listeners.drop || []).length };
    rowOf('追问四').children[0].fire('dragstart'); sending.fire('drop'); await settle(5);
    const ontoSending = names(h);
    h.runner.moveQueued(h.runner.queue.find(j => j.say === '追问四').qid, 'nothing'); await settle(5);
    const nowhere = names(h);
    rowOf('追问四').children[0].fire('dragstart'); rowOf('追问四').children[0].fire('dragend'); rowOf('追问三').fire('drop'); await settle(5);
    const ended = { dragQid: pane.dragQid || null, queue: names(h) };
    h.runner.dequeue(['ATT1', 'ATT2']); h.log.release(); await settle(300);
    facts.queueDrag = { target, ontoSending, nowhere, ended };
  }
  // a deleted conversation's queued rows go with it once it can no longer be brought back, and an update does not hand
  // them over
  {
    const conv = h => ({ key: 'ATT1', id: h.pane0.shownConv, agent: 'claude', title: '问题一', at: 0,
                         path: '/data/tmp/scholium/ATT1/conversations/' + h.pane0.shownConv + '.jsonl' });
    const setUp = async () => {
      const h = harness({ scripts: [[qInit, said('答1'), 'WAIT']] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = h.pane0 = p.pane();
      pane.input.type('问题一'); pane.send.click(); await running(h);
      pane.input.type('追问二'); pane.send.click(); await settle(20);
      pane.send.click(); await settle(300);                                   // ■: held
      await h.runner.deleteConv(pane, conv(h)); await settle(20);
      return h;
    };
    const h = await setUp();
    const during = h.runner.queue.filter(j => j.qid).length;                  // Undo can still bring it back
    h.fire(); await settle(50);
    const after = { rows: h.runner.queue.filter(j => j.qid).length, held: h.runner.heldQueues.size };
    const g = await setUp();
    g.runner.stop(true); await settle(20);
    const carried = g.store.get('extensions.scholium-bridge.carryOver');
    facts.queueConvDeleted = { during, after, carried: carried ? JSON.parse(carried).jobs.length : 0 };
  }
  // a held row queued before its conversation had its log keeps its hold when a run gives it that conversation
  {
    const h = harness({ holdDirs: true, scripts: [qReply(1), qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const release = async () => {
      for (let i = 0; i < 1500; i++) { if (h.log.releaseDir) { const r = h.log.releaseDir; h.log.releaseDir = null; r(); } await tick(); }
      await settle(100);
    };
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.releaseDir; i++) await tick();
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(20);                                      // ■ before the run has its process: it ends there
    await release();
    const stopped = { calls: h.log.calls.length, held: [...h.runner.heldQueues] };
    await h.runner.send(h.item1, '另一个问题'); await release();              // a run that makes the paper's conversation
    facts.queueHeldPointed = { stopped, calls: h.log.calls.length, held: [...h.runner.heldQueues], rows: pane.queueBox.children.map(c => c.className) };
  }
  // the queue takes at most three tenths of the pane's height
  {
    const h = harness();
    h.runner.start('x');
    const scroller = new h.El('div'); scroller.clientHeight = 900;
    const p = await h.pane(h.item1, { closest: sel => (sel === 'item-details' ? { _paneParent: scroller } : null) });
    await settle(40);
    facts.queueHeight = { max: p.pane().queueBox.style.maxHeight, first: p.pane().composer.children[0] === p.pane().queueBox };
  }
  // a message queued to an annotation session counts the paper's annotations when it goes, not when it was queued, and
  // leaves the chat's current conversation as it was
  {
    const h = harness({ scripts: [SCRIPT.concat(['HOLD', LAST, RESULT]), qReply(2)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    p.annotate(); await untilRelease(h);
    pane.input.type('第 5 页那条改短'); pane.send.click(); await settle(20);
    const own = h.runner.queue.filter(j => j.qid).map(j => [j.kind, j.own]);
    h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666'), h.ann('A2', 'highlight', '#ffd400')];
    h.log.release(); await settle(600);
    facts.queueOwn = { own, told: /编辑写入它们的那份配置/.test(h.log.stdin[1] || ''), chat: (await h.runner.index('ATT1')).current.claude || null };
  }
  // ---- final fixes ----
  // the agent's process being created, with a stop pressed meanwhile (pressed: what the run's process is created with)
  const stopWhileMade = (h, pane, made) => {
    const sub = h.runner.subprocess;
    h.runner.subprocess = function () {
      const s = sub.call(this);
      return Object.assign({}, s, { call: async opts => { const proc = await s.call(opts); if (made(opts)) h.runner.stopFromPane(pane); return proc; } });
    };
  };
  // ■ while a run starts, before its agent's process (its folder being made): the run ends as cancelled, no process
  // starts, the words go back to the box, and the queue is held
  {
    const h = harness({ holdDirs: true, script: SCRIPT.concat(['WAIT']) });
    const outs = outcomes(h);
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.releaseDir; i++) await tick();
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    const round = pane.send.textContent;
    pane.send.click(); await settle(20);                                      // ■
    h.log.releaseDir(); await settle(300);
    facts.stopStarting = { round, calls: h.log.calls.length, job: !!h.runner.job, box: pane.input.value, outcome: outs[0] || null, convs: convs(h).length,
                           queue: h.runner.queue.map(j => j.say), held: h.runner.heldQueues.size, state: p.view().state,
                           line: pane.queueBox.children.length ? pane.queueBox.children[0].className : null };
    h.runner.cancel(); await settle(100);
  }
  // the same for a queued message the queue starts: it goes back to the head of its queue, held
  {
    const h = harness({ holdDirs: true, scripts: [qHeld(1), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.releaseDir; i++) await tick();
    h.log.releaseDir(); h.log.releaseDir = null; await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    h.log.release();
    for (let i = 0; i < 3000 && !h.log.releaseDir; i++) await tick();        // 追问二 starts
    const starting = h.runner.job && h.runner.job.source.say;
    pane.send.click(); await settle(20);                                      // ■
    h.log.releaseDir(); await settle(300);
    facts.stopStartingRow = { starting, calls: h.log.calls.length, job: !!h.runner.job, box: pane.input.value,
                              queue: h.runner.queue.map(j => (j.qid ? 'Q:' : '') + j.say), held: h.runner.heldQueues.size };
    h.runner.dequeue(['ATT1']); h.runner.cancel(); await settle(100);
  }
  // ■ once the words are in the log, before the agent's process: the run ends as cancelled in its log, without a process
  {
    const h = harness({ script: SCRIPT.concat(['WAIT']) });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const append = h.runner.appendEntries;
    h.runner.appendEntries = function (entries) {
      append.call(this, entries);
      if (entries.some(e => e.kind === 'prompt')) { this.appendEntries = append; this.stopFromPane(pane); }
    };
    pane.input.type('问题一'); pane.send.click(); await settle(300);
    facts.stopLogged = { calls: h.log.calls.length, job: !!h.runner.job, box: pane.input.value,
                         ends: convLines(h).filter(l => l.subtype === 'end').map(l => l.outcome), prompts: convLines(h).filter(l => l.subtype === 'prompt').map(l => l.text) };
    h.runner.cancel(); await settle(100);
  }
  // ■ while Claude Code's process is being created: it is killed before it has the prompt
  {
    const h = harness({ script: SCRIPT.concat(['WAIT']) });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    stopWhileMade(h, pane, opts => opts.arguments.includes('--include-partial-messages'));
    pane.input.type('问题一'); pane.send.click(); await settle(300);
    facts.stopClaudeMade = { calls: h.log.calls.length, kills: h.log.kills, stdin: h.log.stdin.length, job: !!h.runner.job,
                             ends: convLines(h).filter(l => l.subtype === 'end').map(l => l.outcome) };
    h.runner.cancel(); await settle(100);
  }
  // ■ while Codex's server starts: the server is closed and no turn starts
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    stopWhileMade(h, pane, opts => opts.arguments[0] === 'app-server' && !!h.runner.job);
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    const sent = h.log.codexProcs.flatMap(pr => pr.sent).map(m => m.method).filter(Boolean);
    facts.stopServerMade = { turns: sent.filter(m => m === 'turn/start').length, job: !!h.runner.job,
                             ends: convLines(h).filter(l => l.subtype === 'end').map(l => l.outcome) };
    h.runner.cancel(); await settle(100);
  }
  // Esc pressed once is for the run it was pressed on: when the queue starts the next one, the hint is back and one press
  // stops nothing; two do
  {
    const h = harness({ scripts: [qHeld(1), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    key(pane.box, { key: 'Escape' });
    const armed = pane.hint.textContent;
    h.log.release(); await settle(300);                                       // the first run ends; the queue sends 追问二
    const next = h.runner.job && h.runner.job.source.say;
    const hint = pane.hint.textContent;
    key(pane.box, { key: 'Escape' }); await settle(20);
    const once = !!h.runner.current && !h.runner.current.cancelled;
    key(pane.box, { key: 'Escape' }); await settle(200);
    facts.escPerRun = { armed, next, hint, once, twice: !h.runner.job };
  }
  // ■ in Steer mode: the turn being interrupted takes no more words; a message sent meanwhile queues
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.followUpMode': 'steer' },
                        codex: { scripts: [[note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    const before = h.runner.steerable(pane);
    pane.send.click();                                                        // ■
    const stopping = h.runner.steerable(pane);
    pane.input.type('改问这个'); pane.send.click(); await settle(600);
    const turns = h.log.codexProcs.flatMap(pr => pr.sent).filter(m => m.method === 'turn/start');
    facts.steerStopping = { before, stopping, steers: h.log.steers.length, turns: turns.map(m => m.params.input[0].text.includes('改问这个')) };
    h.runner.cancel(); await settle(100);
  }
  // a Codex compaction in Steer mode: the round button says the words queue
  {
    const first = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
                   coItem('completed', { type: 'agentMessage', id: 'a1', text: '回答一' }),
                   usage(tok(849000, 800000, 1000), tok(849000, 800000, 1000)),
                   turnDone({ status: 'completed', durationMs: 1000 })];
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.followUpMode': 'steer' },
                        codex: { scripts: [first], compactScript: ['WAIT'] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(500);
    await h.runner.compactFromPane(pane, '');
    for (let i = 0; i < 3000 && !(h.runner.job && h.runner.job.delivered); i++) await tick();
    pane.input.type('追问');
    facts.compactSteerTip = { follow: h.runner.followUpFor(pane), tip: pane.send.title };
    h.runner.cancel(); await settle(200);
  }
  // ■ on a paper the usage limit paused, behind which its queue waits: only held messages are left, and the pause ends
  {
    const h = harness({ scripts: [[qInit, 'HOLD'].concat(LIMIT_HIT)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await untilRelease(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    h.log.release(); await settle(300);                                       // the limit: the paper waits
    const paused = !!h.runner.paused;
    pane.send.click(); await settle(50);                                      // ■
    facts.pauseHeldOnly = { paused, after: !!h.runner.paused, queue: h.runner.queue.map(j => (j.qid ? 'Q:' : '') + (j.say || j.att.key)),
                            held: h.runner.heldQueues.size };
    h.runner.dequeue(['ATT1']);
  }
  // a held queue does not keep the paper's Scholium annotations from being deleted
  {
    const h = harness({ existing: [['zotero-scholium']], scripts: [[qInit, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    pane.send.click(); await settle(300);                                     // ■: the run stops, 追问二 is held
    const held = h.runner.heldQueues.size;
    const removed = await h.runner.removeAnnotations([h.item1]);
    facts.deleteHeld = { held, removed, erased: h.log.erased, alerts: h.log.alerts.length };
    h.runner.dequeue(['ATT1']);
  }
  // a follow-up goes after the queued jobs of its own conversation, not behind a queued annotation of its paper
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    await h.runner.annotate([h.item2]); await settle(100);                    // another paper runs
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(20);           // waits for its turn
    await h.runner.annotate([h.item1]); await settle(20);                     // the paper's annotation waits too
    pane.input.type('追问二'); pane.send.click(); await settle(20);
    facts.followUpOwnQueue = h.runner.queue.map(j => (j.qid ? 'Q:' + j.say : j.say || j.att.key + '/' + j.kind));
    h.runner.dequeue(['ATT1', 'ATT2']); h.runner.cancel(); await settle(100);
  }
  // /compact while the paper cannot compact (no conversation shown, a run going on): the words stay in the box, and the
  // round button does not say that it queues them
  {
    const h = harness({ scripts: [[qInit, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('/compact');
    const bare = { tip: pane.send.title };
    pane.send.click(); await settle(50);
    Object.assign(bare, { box: pane.input.value, calls: h.log.calls.length });
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('/compact 侧重');
    const busy = { tip: pane.send.title };
    pane.send.click(); await settle(50);
    Object.assign(busy, { box: pane.input.value, queue: h.runner.queue.length, calls: h.log.calls.length });
    facts.compactNotNow = { bare, busy };
    h.runner.cancel(); await settle(100);
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_compact_button(facts):
    b = facts["compactButton"]
    assert b["idle"] == {"label": "压缩此对话的上下文", "disabled": False, "note": "早先的内容换成摘要，对话接着进行"}
    assert b["closed"] is None and b["busy"] is True and b["stdin"] == "/compact"


def test_the_compact_button_is_greyed_without_a_conversation_or_a_size(facts):
    assert facts["compactButtonGreyed"] == {"noSize": True, "sized": False, "noConv": True}


def test_the_compact_button_is_greyed_by_a_run_of_the_other_tab(facts):
    assert facts["compactButtonOtherTab"] == {"tab": "chat", "busyHere": False, "disabled": True}


def test_claude_compaction(facts):
    c = facts["compactClaude"]
    assert c["during"]["stdin"] == "/compact 侧重方法部分" and c["during"]["resumed"] == "S1"
    assert c["during"]["marker"] == "◌ 正在压缩上下文……"
    assert re.fullmatch(r"正在压缩 · \d+s", c["during"]["state"]) and c["during"]["round"] == "■"
    assert c["after"] == "上下文已压缩 · 850k → 120k" and c["runs"] == 2
    assert c["hidden"] is True
    assert "120k / 1,000k tokens" in c["ring"]
    assert c["runLine"]["compact"] is True and c["runLine"]["user"] is None
    assert [m["subtype"] for m in c["marks"]] == ["compact"] and c["marks"][0]["text"] == "侧重方法部分"
    assert c["turns"] == [["问题一", "回答一"]] and c["session"] == "S1"


def test_codex_compaction(facts):
    c = facts["compactCodex"]
    assert c["ok"] is True
    assert "thread/resume" in c["sent"] and "thread/compact/start" in c["sent"] and "turn/start" not in c["sent"]
    assert c["words"] is False and c["exclude"] is True
    assert c["before"] == 850000
    assert c["after"] == "上下文已压缩 · 850k → 120k" and c["runs"] == 2
    assert c["compacted"] == [[850000, 120000]]
    assert c["runLine"]["compact"] is True and c["runLine"]["user"] is None
    assert c["turns"] == [["问题一", "回答一"]]
    assert "120k / 1,000k tokens" in c["ring"]
    assert c["titles"] == ["上下文已压缩：Paper ITEM1"] and c["bodies"] == ["850k → 120k"]
    assert facts["compactCodexAuto"] == ["上下文已自动压缩"]
    assert facts["compactCodexFailed"]["marks"] == 0 and facts["compactCodexFailed"]["after"].startswith("压缩已中断")
    assert facts["compactCodexDelivered"] == [["ATT1", True, "T1"]]


def test_compaction_on_its_own(facts):
    assert facts["compactAuto"] == ["上下文已自动压缩 · 990k → 150k"]
    assert facts["compactAutoParts"] == ["scholium-entry prompt", "scholium-fold", "scholium-entry text", "scholium-compact", "scholium-meta"], \
        "the start of the compaction has no line"
    assert facts["compactAutoEarly"] == ["上下文已自动压缩 · 990k → 150k"]
    assert facts["compactedLine"] == 90


def test_a_compaction_stopped(facts):
    assert facts["compactStopped"].startswith("压缩已中断")
    assert facts["compactStoppedLog"] == {"turns": [["问", "好", ""]], "result": "好"}, "the stopped compaction is no turn's end"


def test_the_run_after_a_compaction_is_a_turn_of_its_own(facts):
    f = facts["afterCompaction"]
    assert f["runs"] == [[False, "问题一", False], [True, None, False], [False, "问题二", False]]
    assert f["turns"] == [["问题一", "回答一"], ["问题二", "回答二"]]


def test_the_state_line_is_painted_on_the_tab_of_the_run(facts):
    a = facts["tickAnnotation"]
    assert re.search(r"已用 \d+s", a["running"]) and re.search(r"已用 \d+s", a["back"])
    assert a["chat"] == "", "the chat tab has nothing to say while the annotation runs"
    c = facts["tickChat"]
    assert re.search(r"已用 \d+s", c["chatRunning"]) and c["annot"] == ""


def test_the_run_after_a_compaction_goes_on_with_the_turn_before(facts):
    assert facts["goesOnAfterCompaction"] == [[False, "问", True], [True, None, False], [False, "问", False]]


def test_a_compaction_goes_to_the_conversation_named(facts):
    f = facts["compactTarget"]
    assert f["bare"] is False and f["callsBefore"] == 0, "no session to compact"
    assert f["old"] is True and f["resumed"] == "OLD" and f["stdin"] == "/compact 侧重" and f["wrote"] == 1
    assert f["titles"] == ["上下文已压缩：Paper ITEM1"] and f["bodies"] == ["800 → 90"], "a compaction is no annotation"


def test_an_update_hands_a_compaction_over_as_one(facts):
    f = facts["compactHandover"]
    assert f["waiting"] == [False], "a compaction waiting has not started a conversation's run"
    assert ["ATT1", True] in f["carried"] and ["ATT1", True] in f["restored"]


def test_a_compaction_leaves_the_result_and_time_of_the_conversation(facts):
    assert facts["afterCompactionLog"] == {"result": "答", "lastAtIsTurns": True, "runs": 2}


def test_a_compaction_is_never_an_annotation(facts):
    f = facts["annotationCompaction"]
    assert f["sent"] is True and f["stdin"] == ["/compact 侧重"] and f["sessions"] == 1
    w = facts["compactWords"]
    assert w["noSession"] == {"calls": 0, "box": "/compact 侧重"}, "the words stay in the box"


def test_a_compaction_under_way_is_handed_over_as_one_at_an_update(facts):
    f = facts["compactDelivered"]
    assert f["carried"] == [["ATT1", True, "S1", "侧重方法"]]
    assert f["stdin"] == ["/compact 侧重方法"] and f["continued"] == 0, "the new copy compacts again, with the focus"


def test_the_words_of_a_compaction_go_back_as_typed(facts):
    assert facts["givenBackCompaction"] == ["/compact 侧重方法部分", "/compact"]


def test_compact_alone_compacts_and_compactify_is_words(facts):
    w = facts["compactWords"]
    assert w["bare"] == "/compact" and w["words"] is True and w["plain"] is True


def test_codex_steer(facts):
    s = facts["steerCodex"]
    assert s["tip"] == "排队"
    assert s["queued"] == 0, "Queue chosen: a send while busy steers nothing"
    assert s["queuedWords"] == {"words": ["只看第 3 节"], "box": "", "after": 0}, "it queues the words instead"
    assert s["steers"] == [["T1", "U1", [{"type": "text", "text": "只看第 3 节", "text_elements": []}]]] and s["input"] == ""
    assert s["during"]["stopped"] == 0 and s["during"]["busy"], "the turn goes on"
    assert s["lines"] == ["只看第 3 节"]
    assert s["turns"] == [["问题一\n\n只看第 3 节", "好的"]]
    assert s["steerFn"] == ["function", "undefined"], "the turn that ended takes no more words"
    assert s["reread"] == [["问题一", False], ["只看第 3 节", True]]


def test_steered_words_open_a_segment_that_goes_on_with_the_turn(facts):
    s = facts["steerCodex"]
    # a user message at the start of the new segment; the meta line on the last segment only
    assert s["runs"] == [[["问题一"], False], [["只看第 3 节"], True]]


def test_a_steer_after_the_turn_ended_or_refused_queues_the_words(facts):
    assert facts["steerLate"]["steers"] == 0 and facts["steerLate"]["lines"] == 0
    r = facts["steerRefused"]
    assert r["input"] == "" and r["queued"] == ["晚了"] and r["lines"] == 0 and r["runs"] == 1


def test_claude_steer_branch(facts):
    # Claude Code cannot be steered: a second message written during an answer only runs as a turn of its own
    s = facts["steerClaude"]
    assert s["can"] is False and s["steerable"] is False and s["follow"] == "queue" and s["tip"] == "排队"
    assert s["steers"] == 0 and s["writes"] == 1


def test_claude_rows_cannot_steer(facts):
    s = facts["steerClaude"]["steer"]
    assert s == ["引导", True, "Claude Code 不支持引导"]   # branch B


def test_an_annotation_steered_keeps_one_card_on_its_last_segment(facts):
    s = facts["steerAnnotation"]
    assert s["during"]["steers"] == ["也看第 5 页"] and s["during"]["cards"] == []
    assert s["runCount"] == 2 and s["runs"][1] == ["也看第 5 页"]
    assert len(s["cards"]) == 1 and s["cards"][0][0] == 1
    assert s["retries"] <= 1


def test_a_steered_chat_that_failed_offers_retry_on_its_last_segment_only(facts):
    assert facts["steerFailedChat"] == [0, 1]


def test_the_settings_page_says_that_claude_code_does_not_steer():
    from bridge_harness import PLUGIN
    key = "scholium-followup-claude-note"
    assert f'data-l10n-id="{key}"' in (PLUGIN / "settings.xhtml").read_text(encoding="utf-8")
    zh = (PLUGIN / "locale/zh-CN/scholium-bridge.ftl").read_text(encoding="utf-8")
    en = (PLUGIN / "locale/en-US/scholium-bridge.ftl").read_text(encoding="utf-8")
    assert f"{key} = Claude Code 不支持引导，它的跟进消息总是排队。" in zh
    assert f"{key} = Claude Code does not support steering; its follow-ups always queue." in en


def test_the_queue(facts):
    q = facts["queue"]
    assert q["refused"] == [False, False, 0], "a compaction or a retry while the paper runs is refused, not queued"
    assert q["first"] == {"rows": ["追问二", "追问三"], "input": "", "buttons": ["引导", "✕", "⋯"]}
    assert q["qids"] == ["1", "2"]
    assert q["dragged"] == ["追问三", "追问二"] and q["prevented"] is True and q["over"] is True
    assert q["removed"]["rows"] == ["追问三"] and q["removed"]["undo"] == "已删除撤销"
    assert q["back"] == ["追问三", "追问二"]
    assert q["expanded"] == ["scholium-queued full", "scholium-queued", "scholium-queued"]
    assert q["menu"] == [["编辑消息", False], ["关闭排队", True]], "Claude Code cannot be steered (branch B)"
    assert q["edited"] == {"rows": ["追问二"], "input": "追问三"}
    assert q["box"] == {"focused": True, "kept": True}, "the words edited are the box's, kept for it"
    assert q["stdin"] == ["问题一", "追问二", "追问三"] and q["after"] == []
    assert q["resumed"] == ["S1", "S1"]


def test_a_stop_holds_the_queue(facts):
    h = facts["held"]
    assert h["held"]["line"] == "由于你中断了当前响应，队列已暂停继续"
    assert h["held"]["row"] == "发送" and h["held"]["calls"] == 1 and h["held"]["round"] == "↑"
    assert h["ask"] == ["发送消息？你即将发送一条消息。要清除之前已排队的 1 条消息吗？", "清空队列", "发送消息"]
    # Send message sends the new message and resumes the queue after it (Codex: resumeInterruptedSteers)
    assert h["sent"] == {"first": True, "then": True}
    assert h["rows"] == 0 and h["released"] == 0
    assert h["outcome"] == {"ok": False, "delivered": False, "cancelled": True}


def test_a_held_queue_leaves_the_paper_idle(facts):
    i = facts["held"]["idle"]
    assert "排队中" not in (i["state"] or "") and i["busy"] is False and i["any"] is False and i["newChat"] is False


def test_a_queued_message_that_failed(facts):
    f = facts["queueFailed"]["failed"]
    assert f["cls"] == "scholium-queued failed" and f["text"] == "⚠ 追问二"
    assert f["tip"] == "这条排队中的消息未能发送 · 重试、编辑或删除该消息以继续发送排队的消息"
    assert f["button"] == "重试" and f["waiting"] == ["追问二", "追问三"] and f["input"] == ""
    assert f["retries"] == 0, "no Retry in the transcript, which would retry the turn before"
    assert facts["queueFailed"]["sent"] is True
    assert facts["queueFailed"]["outcomes"] == [{"ok": True, "delivered": True, "cancelled": False}, {"ok": False, "delivered": False}]


def test_a_failed_message_deleted_or_edited_lets_the_queue_go_on(facts):
    g = facts["queueFailedGone"]
    assert g["delete"] == {"sent": True, "input": "", "rows": 0}
    assert g["edit"] == {"sent": True, "input": "追问二\n\n另外", "rows": 0}


def test_codex_rows_steer_and_turn_off_queueing(facts):
    c = facts["queueCodex"]
    assert c["steer"] == ["引导", False, "提交，但不中断模型运行"]
    assert c["menu"] == [["编辑消息", False], ["关闭排队", False]]
    assert c["mode"] == "steer" and c["menuSteer"] == [False, True]
    assert c["steers"] == ["追问二"] and c["lines"] == ["追问二"] and c["rows"] == 0 and c["queue"] == 0
    assert c["refused"] == {"rows": ["追问二"], "queue": 1}, "a refused steer leaves the row"


def test_a_queued_message_being_sent(facts):
    s = facts["queueSending"]
    assert s["sending"] == ["scholium-queued sending", "追问二", "正在发送", 3]
    assert s["delivered"] == 0, "the row goes once its agent has the message"
    assert s["stopped"] == {"rows": 0, "queue": 0, "outcome": {"ok": False, "delivered": False, "cancelled": True}}


def test_follow_ups_go_to_the_new_conversation_of_their_question(facts):
    for when, conv in [("before", [None]), ("after", [])]:
        f = facts["queuePointed"][when]
        assert f["conv"] == conv and f["first"] is True, when
        assert f["fresh"] == {"shown": None, "current": None, "rows": 0, "hidden": True}, when
        assert f["back"] == ["scholium-queue-held", "scholium-queued"], when
        assert f["logs"] == 1 and f["prompts"] == ["问题一", "追问二"] and f["shown"] is True, when


def test_a_held_row_goes_to_its_own_conversation(facts):
    assert facts["queueOwnConv"] == {"logs": 1, "a": ["问题一", "追问A"]}


def test_queued_rows_are_per_conversation(facts):
    f = facts["queuePerConv"]
    assert f["asked"] is False and f["two"] is True
    assert f["inB"] == {"rows": ["B追问"], "line": "scholium-queue-held", "cross": ["追问A", "B追问"]}
    assert f["afterB"] == {"held": 1, "calls": 3, "last": True}, "Resume in B leaves A's queue held"
    assert f["inA"] == {"rows": ["追问A"], "line": "scholium-queue-held"}
    assert f["held"] == 0
    assert f["a"] == ["问题一", "追问A"] and f["b"] == ["B问", "B追问"]


def test_an_update_hands_the_queue_over(facts):
    f = facts["queueHandover"]
    assert f["busyAsk"] is False, "a message while the paper runs joins the held queue"
    assert f["carried"] == [["", None, False], ["追问二", "1", False], ["追问三", "2", True], ["再一条", "3", False]]
    assert len(f["held"]) == 1 and re.fullmatch(r"ATT1/chat/claude-\d{8}-\d{6}", f["held"][0]), "a conversation's queue"
    assert f["restored"] == [["追问二", "1", False], ["追问三", "2", True], ["再一条", "3", False]]
    assert f["heldAfter"] == f["held"] and f["qseq"] == 3
    assert f["rows"] == ["scholium-queue-held", "scholium-queued", "scholium-queued failed", "scholium-queued"] and f["calls"] == 1
    assert f["running"] == [["", None, "S1"]], "a queued message its agent has continues without a row"


def test_send_on_a_held_row(facts):
    assert facts["queueSendNow"] == {"order": ["追问三", "追问二"], "held": 0, "rows": 0}


def test_a_held_queue_emptied_lets_go(facts):
    e = facts["queueEmptied"]
    assert e["during"] == {"held": 1, "rows": ["scholium-queue-removed"]}
    assert e["after"] == {"held": 0, "rows": 0, "removed": 0, "hidden": True}
    assert e["asked"] is False and e["sent"] == 2


def test_clear_queue(facts):
    assert facts["queueCleared"] == {"queue": 0, "held": 0, "rows": 0, "sent": True, "input": ""}


def test_a_message_brought_back_after_the_run_is_sent(facts):
    assert facts["queueUndone"] == {"idle": 1, "sent": True, "rows": 0}


def test_a_message_the_agent_had_is_no_row(facts):
    a = facts["queueAgain"]
    assert a["retry"] == {"starts": [None, "1"], "queue": [None], "rows": 0}
    assert a["limit"] == {"starts": [None, "1"], "queue": [None], "rows": 0}
    assert a["gone"] == {"starts": [None, "1", None], "queue": [], "rows": 0}
    assert a["answered"] == {"starts": [None, "1"], "queue": [], "rows": 0}


def test_a_queued_run_that_broke_waits_failed(facts):
    t = facts["queueThrown"]
    # its Retry is on its row only: one in the transcript would retry the turn before
    assert t["failed"] == ["scholium-queued failed", "⚠ 追问二", 0] and t["input"] == "" and t["sent"] is True


def test_a_queued_message_failed_after_its_log(facts):
    c = facts["queueCodexFailed"]
    assert c["failed"] == {"cls": "scholium-queued failed", "retries": 0}, "Retry once, on the row"
    assert c["during"] == 0
    assert c["runs"] == ["问题一", "追问二", None] and c["prompts"] == ["问题一", "追问二"] and c["rows"] == 0


def test_where_a_follow_up_joins_the_queue(facts):
    assert facts["queueOrder"] == ["追问二", "追问三", "ATT2"]
    w = facts["queueWaiting"]
    assert w["order"] == ["ATT1/annotate", "Q:ATT1/annotate"]
    assert w["tip"] == [True, "现在没有可引导的回答"]
    assert w["after"] == ["Q:ATT1"] and w["held"] == ["ATT1/annotate/"], "no session yet"
    assert w["line"] == "scholium-queue-held" and w["round"] == "↑"


def test_send_message_goes_ahead_of_the_held_queue_while_another_run_goes(facts):
    f = facts["queueSendPastRun"]
    assert f["queued"] == {"queue": ["新消息", "Q:追问二"], "held": 0}
    assert f["stdin"] == ["问题一", "other", "新消息", "追问二"]


def test_undo_puts_a_row_back_into_its_own_queue(facts):
    f = facts["queueUndoOrder"]
    assert f["retry"] == {"queue": ["问题一(retry)", "Q:追问二"], "runs": 1}, "never ahead of its paper's second try"
    assert f["swapped"] == ["Q:追问二", "Q:追问三"], "before the row that followed it"
    assert f["lastRow"] == ["Q:追问二", "Q:追问四", "Q:追问三", "ATT1"], "else after the last row of its queue"


def test_a_failed_message_goes_back_before_the_rest_of_its_queue(facts):
    assert facts["queueFailedPlace"] == ["Q:R一", "Q:R二"]


def test_a_failed_row_hides_only_its_own_conversations_retry(facts):
    assert facts["queueRetryPerConv"] == {"failedA": 1, "rows": 0, "retries": 1}


def test_stop_lets_go_of_the_queue_state(facts):
    f = facts["queueStop"]
    assert f["before"] == {"held": 1, "removed": 1, "qseq": 2, "timer": True}
    assert f["after"] == {"held": 0, "removed": 0, "qseq": 0, "timer": False}


def test_dragging_rows(facts):
    d = facts["queueDrag"]
    assert d["target"] == {"draggable": None, "drops": 0}, "the row being sent is no drop target"
    assert d["ontoSending"] == ["Q:追问三", "Q:追问四", "ATT2"]
    assert d["nowhere"] == ["Q:追问三", "Q:追问四", "ATT2"], "never to the end of the whole queue"
    assert d["ended"] == {"dragQid": None, "queue": ["Q:追问三", "Q:追问四", "ATT2"]}


def test_a_deleted_conversation_takes_its_rows(facts):
    assert facts["queueConvDeleted"] == {"during": 1, "after": {"rows": 0, "held": 0}, "carried": 0}


def test_a_held_row_keeps_its_hold_when_its_conversation_is_made(facts):
    f = facts["queueHeldPointed"]
    assert f["stopped"] == {"calls": 0, "held": ["ATT1/chat/"]}, "the stop ends the run before its process and its conversation"
    assert f["calls"] == 1 and len(f["held"]) == 1 and re.fullmatch(r"ATT1/chat/claude-\d{8}-\d{6}", f["held"][0])
    assert f["rows"] == ["scholium-queue-held", "scholium-queued"]


def test_the_queue_height(facts):
    assert facts["queueHeight"] == {"max": "270px", "first": True}


def test_a_queued_annotation_message_counts_the_annotations_when_it_goes(facts):
    assert facts["queueOwn"] == {"own": [["annotate", 0]], "told": True, "chat": None}


def test_the_queue_strings_follow_codex():
    from bridge_harness import BRIDGE
    src = BRIDGE.read_text(encoding="utf-8")
    for en in ["Queue paused because you interrupted", "Submit without interrupting the model", "Edit message", "Turn off queueing",
               "This queued message could not be sent · Retry, edit, or delete it to continue the queue", "Clear queue", "Send message",
               "Delete queued message", "Sending"]:
        assert en in src


def test_what_can_be_steered(facts):
    s = facts["steerable"]
    assert s["idle"] is False and s["own"] == [True, True, True, False, False]
    assert s["otherTab"] is False and s["compacting"] is False


def test_a_stop_while_a_run_starts_cancels_it(facts):
    f = facts["stopStarting"]
    assert f["round"] == "■"
    assert f["calls"] == 0 and f["job"] is False and f["convs"] == 0, "no process starts, no conversation is left"
    assert f["box"] == "问题一", "the words go back to the box"
    assert f["outcome"] == {"ok": False, "delivered": False, "cancelled": True}
    assert f["queue"] == ["追问二"] and f["held"] == 1 and f["line"] == "scholium-queue-held"
    assert f["state"].startswith("已取消")
    r = facts["stopStartingRow"]
    assert r["starting"] == "追问二"
    assert r == {"starting": "追问二", "calls": 1, "job": False, "box": "", "queue": ["Q:追问二"], "held": 1}, "the row goes back, held"


def test_a_stop_after_the_words_are_logged_ends_the_run_as_cancelled(facts):
    assert facts["stopLogged"] == {"calls": 0, "job": False, "box": "", "ends": ["cancelled"], "prompts": ["问题一"]}


def test_a_stop_while_the_agent_starts_ends_its_process(facts):
    assert facts["stopClaudeMade"] == {"calls": 1, "kills": 1, "stdin": 0, "job": False, "ends": ["cancelled"]}
    assert facts["stopServerMade"] == {"turns": 0, "job": False, "ends": ["cancelled"]}


def test_an_esc_pressed_once_is_for_its_own_run(facts):
    e = facts["escPerRun"]
    assert e["armed"] == "再按一次 Esc 停止" and e["next"] == "追问二"
    assert e["hint"] == "Ctrl+Enter 发送", "the next run starts without the first press"
    assert e["once"] is True and e["twice"] is True


def test_a_turn_being_stopped_takes_no_steer(facts):
    s = facts["steerStopping"]
    assert s["before"] is True and s["stopping"] is False
    assert s["steers"] == 0 and s["turns"] == [False, True], "the words queue and go as a turn of their own"


def test_the_round_button_says_queue_during_a_codex_compaction(facts):
    assert facts["compactSteerTip"] == {"follow": "queue", "tip": "排队"}


def test_a_pause_ends_when_only_held_messages_are_left(facts):
    assert facts["pauseHeldOnly"] == {"paused": True, "after": False, "queue": ["Q:追问二"], "held": 1}


def test_a_held_queue_does_not_keep_annotations_from_being_deleted(facts):
    assert facts["deleteHeld"] == {"held": 1, "removed": 1, "erased": ["E0"], "alerts": 0}


def test_a_follow_up_goes_after_its_own_conversations_queue(facts):
    assert facts["followUpOwnQueue"] == ["问题一", "Q:追问二", "ATT1/annotate"]


def test_a_compact_the_paper_cannot_take_stays_in_the_box(facts):
    c = facts["compactNotNow"]
    assert c["bare"] == {"tip": "现在不能压缩", "box": "/compact", "calls": 0}
    assert c["busy"] == {"tip": "现在不能压缩", "box": "/compact 侧重", "queue": 0, "calls": 1}
