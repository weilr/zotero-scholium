"""Compaction of a conversation (Claude Code's /compact), its markers in the transcript and on the ring; the state line
of the running paper is painted on the tab of the run's kind only."""
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
