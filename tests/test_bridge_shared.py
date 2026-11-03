"""One conversation of a paper shared by Claude Code and Codex: each agent's own session of it as the log has it, the
list and the current conversation of the paper, the agent chosen answering the next message given what it has not
seen, and the line under each answer."""
import pytest

from bridge_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const DIR = '/data/tmp/scholium/ATT1/conversations/';
// a turn of Claude Code as the plugin logs it: its run line, its words, the answer (its uuid and usage given), the result
// and the end time
const claudeTurn = (n, uuid, session = 'S1', at = 1000 + n) => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session })
  + L({ type: 'assistant', uuid, session_id: session, message: { usage: { input_tokens: 10 * n, cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0, output_tokens: 1 }, content: [{ type: 'text', text: '回答' + n }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: session,
        modelUsage: { 'claude-opus-5-5': { contextWindow: 200000 } } })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
// a turn of Codex as the plugin logs it, in thread `thread`, its turn `id`
const codexTurn = (n, id, thread = 'T1', at = 1000 + n) => L({ type: 'scholium', subtype: 'run', agent: 'codex', user: '问题' + n, at })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: thread })
  + L({ method: 'turn/started', params: { threadId: thread, turn: { id, status: 'inProgress' } } })
  + L({ method: 'item/completed', params: { threadId: thread, turnId: id, item: { type: 'agentMessage', id: 'a' + n, text: '回答' + n } } })
  + L({ method: 'thread/tokenUsage/updated', params: { threadId: thread, turnId: id, tokenUsage: {
        last: { totalTokens: 500 * n, inputTokens: 500 * n, cachedInputTokens: 0, outputTokens: 0 }, modelContextWindow: 1000000 } } })
  + L({ method: 'turn/completed', params: { threadId: thread, turn: { id, status: 'completed', items: [] } } })
  + L({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: '回答' + n, session_id: thread })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
// what a Claude Code run answers: its session and its words
const answered = (session, text) => [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session }),
  ev({ type: 'assistant', uuid: 'v-' + text, session_id: session, message: { content: [{ type: 'text', text }] } }),
  ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: session })];
// what a Codex turn answers
const codexSays = text => [note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
  coItem('completed', { type: 'agentMessage', id: 'a-' + text, text }), turnDone({ status: 'completed' })];
(async () => {
  const facts = {};
  // each agent's own session of a conversation: its session, the last turn it saw, its point, its context and its
  // latest run; who answered each turn and the points before it
  {
    const MIX = claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1') + claudeTurn(3, 'u3', 'S1');
    const gone = L({ type: 'scholium', subtype: 'gone', agent: 'codex', resent: false });
    const retry = L({ type: 'scholium', subtype: 'run', agent: 'codex', user: null, at: 1500 })
      + L({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T2' })
      + L({ method: 'turn/started', params: { threadId: 'T2', turn: { id: 'K9', status: 'inProgress' } } })
      + L({ method: 'turn/completed', params: { threadId: 'T2', turn: { id: 'K9', status: 'completed', items: [] } } })
      + L({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: '再答3', session_id: 'T2' });
    const compact = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: null, at: 1600, compact: true })
      + L({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'manual', pre_tokens: 9000, post_tokens: 900 } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'S1' });
    // a cut: Claude Code goes back to u1, Codex to a new session; a later Claude Code run that never reached it keeps the
    // point, one that reached it in a session of its own drops it
    const marker = L({ type: 'scholium', subtype: 'rewind', points: { claude: { uuid: 'u1' }, codex: null } });
    const unreached = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题3', at: 1700, rewind: { uuid: 'u1' } })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题3' }) + L({ type: 'scholium', subtype: 'end', outcome: 'failed', text: 'boom' });
    const forked = claudeTurn(4, 'u4', 'S9', 1800);
    const h = harness({ logs: {
      [DIR + 'chat-20261101-120000.jsonl']: MIX,
      [DIR + 'chat-20261101-120001.jsonl']: MIX + gone + retry + compact,
      [DIR + 'chat-20261101-120002.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1') + marker,
      [DIR + 'chat-20261101-120003.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1') + marker + unreached,
      [DIR + 'chat-20261101-120004.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1') + marker + unreached + forked,
      // a retry by another agent that never reached it leaves the turn with the agent that answered
      [DIR + 'chat-20261101-120005.jsonl']: claudeTurn(1, 'u1') + L({ type: 'scholium', subtype: 'run', agent: 'codex', user: null, at: 1900 })
        + L({ type: 'scholium', subtype: 'end', outcome: 'failed', text: 'boom' }),
      // an earlier version's marker names the log's own agent's point
      [DIR + 'codex-20261001-120000.jsonl']: codexTurn(1, 'K1') + codexTurn(2, 'K2') + L({ type: 'scholium', subtype: 'rewind', point: { turnId: 'K1' } }),
      [DIR + 'claude-20261001-120000.jsonl']: claudeTurn(1, 'u1') + claudeTurn(2, 'u2') + L({ type: 'scholium', subtype: 'rewind', point: null }),
      // a log of an earlier version without run lines is its agent's
      '/data/tmp/scholium/ATT1/codex-run.jsonl': L({ type: 'scholium', subtype: 'prompt', text: '旧问题', question: true })
        + L({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T0' })
        + L({ method: 'turn/started', params: { threadId: 'T0', turn: { id: 'K0', status: 'inProgress' } } })
        + L({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: '旧回答', session_id: 'T0' }) } });
    h.runner.start('x');
    const read = id => h.runner.readLog('ATT1', id);
    const state = a => ({ session: a.session, through: a.through, point: a.point, rewind: a.rewind, used: a.context ? a.context.used : null,
                          lastAt: a.lastAt });
    const mix = await read('chat-20261101-120000');
    const after = await read('chat-20261101-120001');
    const cut = await read('chat-20261101-120002');
    const cutUnreached = await read('chat-20261101-120003');
    const cutForked = await read('chat-20261101-120004');
    const retryUnreached = await read('chat-20261101-120005');
    const oldCodex = await read('codex-20261001-120000'), oldClaude = await read('claude-20261001-120000'), oldRun = await read('codex-run');
    facts.agents = {
      keys: Object.keys(mix).sort(),
      mix: { claude: state(mix.agents.claude), codex: state(mix.agents.codex),
             turns: mix.turns.map(t => [t.user, t.agent, t.points, t.reply]) },
      after: { claude: state(after.agents.claude), codex: state(after.agents.codex), turns: after.turns.map(t => [t.agent, t.reply]),
               stale: [after.agents.claude.stale, after.agents.codex.stale], staleMix: [mix.agents.claude.stale, mix.agents.codex.stale] },
      cut: { claude: state(cut.agents.claude), codex: state(cut.agents.codex) },
      cutUnreached: state(cutUnreached.agents.claude),
      cutForked: state(cutForked.agents.claude),
      unreachedRetry: { claude: state(retryUnreached.agents.claude), codex: state(retryUnreached.agents.codex), turns: retryUnreached.turns.map(t => t.agent) },
      old: { codex: state(oldCodex.agents.codex), claude: state(oldClaude.agents.claude), run: [state(oldRun.agents.codex), oldRun.turns[0].agent] },
    };
  }
  // the paper's one list: the conversations of earlier versions and the shared ones, newest first; the current one from an
  // index of an earlier version, kept at once; a switch of the agent keeps the conversation shown
  {
    const h = harness({ logs: {
      [DIR + 'claude-20261001-120000.jsonl']: claudeTurn(1, 'u1'),
      [DIR + 'codex-20261002-120000.jsonl']: codexTurn(1, 'K1'),
      [DIR + 'annotate-claude-20261003-120000.jsonl']: claudeTurn(1, 'u9'),
      '/data/tmp/scholium/ATT1/claude-run.jsonl': claudeTurn(1, 'u0'),
      [DIR + 'index.json']: JSON.stringify({ current: { codex: 'codex-20261002-120000', claude: null }, titles: {}, annotation: {} }) },
      logTimes: { [DIR + 'claude-20261001-120000.jsonl']: 3000, [DIR + 'codex-20261002-120000.jsonl']: 2000,
                  '/data/tmp/scholium/ATT1/claude-run.jsonl': 1000 } });
    h.runner.start('x');
    const list = (await h.runner.conversations('ATT1')).map(c => c.id);
    h.runner.choose('agent', 'codex');
    const migrated = await h.runner.currentConv('ATT1');
    const saved = JSON.parse(h.log.writes[DIR + 'index.json']).chat;
    h.runner.choose('agent', 'claude');
    const afterSwitch = await h.runner.currentConv('ATT1');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const shown = pane.shownConv;
    pane.agent.change('codex'); await settle(100);
    await h.runner.toggleHistory(pane); await settle(40);
    const rows = pane.popover.node.children.filter(c => /scholium-history-row/.test(c.className)).length;
    facts.oneList = { list, migrated, saved, afterSwitch, shown, switched: pane.shownConv, rows };
  }
  // no index of an earlier version: the newest; null there (a switch of an earlier version) is none chosen, also the newest
  {
    const h = harness({ logs: { [DIR + 'claude-20261001-120000.jsonl']: claudeTurn(1, 'u1'), [DIR + 'codex-20261002-120000.jsonl']: codexTurn(1, 'K1'),
                                [DIR + 'index.json']: JSON.stringify({ current: { claude: null }, titles: {}, annotation: {} }) },
                        logTimes: { [DIR + 'claude-20261001-120000.jsonl']: 1000, [DIR + 'codex-20261002-120000.jsonl']: 2000 } });
    h.runner.start('x');
    facts.migrateNull = await h.runner.currentConv('ATT1');
  }
  // a question starts a shared conversation, chat-<time>; Codex chosen answers the next message in it; New chat empties
  // the tab; History opens the first again; words typed stay across a switch
  {
    const h = harness({ scripts: [answered('S1', 'Claude 答一')], codex: { scripts: [codexSays('Codex 答二')] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    const conv = pane.shownConv;
    pane.agent.change('codex'); await settle(100);
    pane.input.type('问题二'); pane.send.click(); await settle(600);
    const files = convs(h).filter(c => !c.includes('/annotate-')).map(c => c.split('/').pop());
    const agents = convLines(h).filter(l => l.subtype === 'run').map(l => l.agent);
    pane.input.type('还没发的字');
    pane.agent.change('claude'); await settle(100);
    const kept = pane.input.value;
    await h.runner.newChat(pane); await settle(40);
    const afterNew = [pane.shownConv, JSON.parse(h.log.writes[DIR + 'index.json']).chat];
    await h.runner.toggleHistory(pane); await settle(40);
    const open = pane.popover.node.children.find(c => /scholium-history-row/.test(c.className)).children[0];
    open.click(); await settle(100);
    facts.shared = { conv, sameConv: pane.shownConv === conv, files, agents, kept, afterNew };
  }
  // ↻ and an edited question go to the agent chosen now; a compaction is the chosen agent's session's
  {
    const conv = 'chat-20261101-120000';
    const two = claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1');
    const failed = two + L({ type: 'scholium', subtype: 'run', agent: 'codex', user: '问题3', at: 1003 })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题3' }) + L({ type: 'scholium', subtype: 'end', outcome: 'failed', text: 'boom' });
    const h = harness({ logs: { [DIR + conv + '.jsonl']: failed, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [answered('S1', '重答3')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.runner.choose('agent', 'claude');
    await h.runner.retryFromView(pane); await settle(400);
    const retry = { args: h.log.calls[0].opts.arguments.slice(h.log.calls[0].opts.arguments.indexOf('--resume'), h.log.calls[0].opts.arguments.indexOf('--resume') + 2),
                    run: convLines(h).filter(l => l.subtype === 'run').at(-1), stdin: h.log.stdin[0] };
    // the edit of the second question (Codex's): Claude Code goes back to its point before it; Codex, without a session
    // before it, has none in the conversation kept
    const h2 = harness({ logs: { [DIR + conv + '.jsonl']: two + claudeTurn(3, 'u3', 'S1'), [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                         scripts: [answered('S5', '新答2')] });
    h2.runner.start('x');
    const p2 = await h2.pane(h2.item1); await settle(40);
    const pane2 = p2.pane();
    const prompt = (await h2.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
    await h2.runner.editTurn(pane2, prompt, '新问题二'); await settle(400);
    const lines = convLines(h2);
    const args2 = h2.log.calls[0].opts.arguments;
    facts.byChosen = { retry,
      edit: { marker: lines.find(l => l.subtype === 'rewind'), args: args2.slice(args2.indexOf('--resume'), args2.indexOf('--resume') + 5),
              run: lines.filter(l => l.subtype === 'run').at(-1), codex: (await h2.runner.readLog('ATT1', conv)).agents.codex.session,
              stdin: h2.log.stdin[0] } };
    // a compaction: Codex chosen compacts its own thread of the conversation
    const h3 = harness({ logs: { [DIR + conv + '.jsonl']: two, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h3.runner.start('x');
    const p3 = await h3.pane(h3.item1); await settle(40);
    h3.runner.choose('agent', 'codex');
    await h3.runner.compactFromPane(p3.pane()); await settle(400);
    const sent = h3.log.codexProcs.at(-1) ? h3.log.codexProcs.at(-1).sent.map(m => m.method).filter(Boolean) : [];
    facts.byChosen.compact = { resumed: sent.includes('thread/resume'), compacted: sent.includes('thread/compact/start'), claude: h3.log.calls.length };
  }
  // the same question edited twice: the second cut is seen by Claude Code alone, and the one marker left still takes Codex
  // back as the first one did: to its point, or (its turn before having never completed) to a new session
  {
    const conv = 'chat-20261101-120000';
    const unfinished = codexTurn(2, 'K2', 'T1').split('\n').filter(l => !l.includes('turn/completed')).join('\n');
    const logs = { point: { log: claudeTurn(1, 'u1') + codexTurn(2, 'K2', 'T1') + codexTurn(3, 'K3', 'T1') + claudeTurn(4, 'u4'), turn: 2 },
                   none: { log: claudeTurn(1, 'u1') + unfinished + codexTurn(3, 'K3', 'T1'), turn: 2 } };
    facts.editTwice = {};
    for (const [name, { log, turn }] of Object.entries(logs)) {
      const h = harness({ logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                          scripts: [answered('S5', '新答'), answered('S6', '再答')] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      const promptOf = async () => (await h.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === turn);
      await h.runner.editTurn(pane, await promptOf(), '新问题'); await settle(400);
      const first = convLines(h).filter(l => l.subtype === 'rewind');
      await h.runner.editTurn(pane, await promptOf(), '再改问题'); await settle(400);
      const markers = convLines(h).filter(l => l.subtype === 'rewind');
      const after = await h.runner.readLog('ATT1', conv);
      facts.editTwice[name] = { first, markers, codex: { session: after.agents.codex.session, rewind: after.agents.codex.rewind },
                                calls: h.log.calls.length, prompts: convLines(h).filter(l => l.subtype === 'prompt').map(l => l.text),
                                stdin: h.log.stdin.slice(0, 2) };
    }
  }
  // the agent answering an edit goes back to its point before the question though it never saw the question: a session of
  // its own, so that Undo leaves the old one as it was (Claude Code goes on with it; Codex's fork is archived)
  {
    const conv = 'chat-20261101-120000';
    const IDX = JSON.stringify({ chat: conv, titles: {}, annotation: {} });
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + claudeTurn(2, 'u2', 'S1') + codexTurn(3, 'K3', 'T1'), [DIR + 'index.json']: IDX },
                        scripts: [answered('S5', '新答三'), answered('S1', '下一答')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const prompt = (await h.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 2);
    await h.runner.editTurn(pane, prompt, '新问题三'); await settle(400);
    const args = h.log.calls[0].opts.arguments;
    const marker = convLines(h).filter(l => l.subtype === 'rewind');
    await h.runner.undoReplace('ATT1/' + conv); await settle(100);
    const back = (await h.runner.readLog('ATT1', conv)).agents.claude;
    pane.input.type('下一问'); pane.send.click(); await settle(400);
    const next = h.log.calls[1].opts.arguments;
    facts.unseenEdit = { claude: { args: args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 5), marker, back: [back.session, back.through],
                                   next: [next.slice(next.indexOf('--resume'), next.indexOf('--resume') + 2), next.includes('--resume-session-at')],
                                   archived: h.store.get('extensions.scholium-bridge.codexArchive') || null } };
    // Codex chosen edits a question Claude Code answered after Codex's last turn
    const g = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        logs: { [DIR + conv + '.jsonl']: codexTurn(1, 'K1', 'T1') + claudeTurn(2, 'u2', 'S1'), [DIR + 'index.json']: IDX },
                        codex: { scripts: [codexSays('新答二')] } });
    g.runner.start('x');
    const gp = await g.pane(g.item1); await settle(40);
    const gprompt = (await g.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
    await g.runner.editTurn(gp.pane(), gprompt, '新问题二'); await settle(600);
    const sent = g.log.codexProcs.flatMap(c => c.sent).filter(m => typeof m.method === 'string' && /^thread\//.test(m.method))
      .map(m => [m.method, m.params.threadId || null, m.params.lastTurnId || null]);
    const gmarker = convLines(g).filter(l => l.subtype === 'rewind');
    await g.runner.undoReplace('ATT1/' + conv); await settle(100);
    facts.unseenEdit.codex = { sent, marker: gmarker, archived: JSON.parse(g.store.get('extensions.scholium-bridge.codexArchive') || '[]'),
                               back: (await g.runner.readLog('ATT1', conv)).agents.codex.session };
  }
  // an edit of the last question, then of an earlier one, Codex not having run since: the first marker goes with the cut
  // text, and the one left still takes Codex back to its point before the earlier question, or (without one) to a new
  // session; the next Codex message forks the thread there, or starts one
  {
    const conv = 'chat-20261101-120000';
    const IDX = JSON.stringify({ chat: conv, titles: {}, annotation: {} });
    const unfinished = n => codexTurn(n, 'K' + n, 'T1').split('\n').filter(l => !l.includes('turn/completed')).join('\n');
    const cases = { point: { log: codexTurn(1, 'K1', 'T1') + claudeTurn(2, 'u2', 'S1') + claudeTurn(3, 'u3', 'S1') + codexTurn(4, 'K4', 'T1'), turns: [3, 2] },
                    none: { log: unfinished(1) + claudeTurn(2, 'u2', 'S1') + unfinished(3) + claudeTurn(4, 'u4', 'S1'), turns: [2, 1] } };
    facts.cutMarker = {};
    for (const [name, { log, turns }] of Object.entries(cases)) {
      const h = harness({ logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: IDX },
                          scripts: [answered('S5', '新答'), answered('S6', '再答')], codex: { scripts: [codexSays('Codex 答')] } });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      const promptOf = async t => (await h.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === t);
      await h.runner.editTurn(pane, await promptOf(turns[0]), '新问题'); await settle(400);
      const first = convLines(h).filter(l => l.subtype === 'rewind');
      await h.runner.editTurn(pane, await promptOf(turns[1]), '再改问题'); await settle(400);
      const markers = convLines(h).filter(l => l.subtype === 'rewind');
      const codex = (await h.runner.readLog('ATT1', conv)).agents.codex;
      pane.agent.change('codex'); await settle(100);
      pane.input.type('问 Codex'); pane.send.click(); await settle(800);
      const sent = h.log.codexProcs.flatMap(c => c.sent).filter(m => typeof m.method === 'string' && /^thread\/(start|resume|fork)$/.test(m.method))
        .map(m => [m.method, m.params.threadId || null, m.params.lastTurnId || null]);
      facts.cutMarker[name] = { first, markers, codex: { session: codex.session, rewind: codex.rewind }, sent };
    }
  }
  // a deleted shared conversation's Codex thread is archived at the next Codex run
  {
    const conv = 'chat-20261101-120000';
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1') + codexTurn(2, 'K2', 'T7'), [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    await h.runner.deleteConv(pane, (await h.runner.conversations('ATT1'))[0]);
    await h.runner.finishDelete(DIR + conv + '.jsonl');
    facts.deleted = { archive: JSON.parse(h.store.get('extensions.scholium-bridge.codexArchive') || '[]'),
                      index: JSON.parse(h.log.writes[DIR + 'index.json']).chat };
  }
  // every Codex thread of a deleted conversation is archived, not only the current one
  {
    const conv = 'chat-20261101-120000';
    const h = harness({ logs: { [DIR + conv + '.jsonl']: codexTurn(1, 'K1', 'T7') + claudeTurn(2, 'u2') + codexTurn(3, 'K3', 'T8'),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    await h.runner.deleteConv(p.pane(), (await h.runner.conversations('ATT1'))[0]);
    await h.runner.finishDelete(DIR + conv + '.jsonl');
    facts.deletedAll = JSON.parse(h.store.get('extensions.scholium-bridge.codexArchive') || '[]');
  }
  // a log that cannot be removed keeps its threads: nothing is archived
  {
    const conv = 'chat-20261101-120000';
    const path = DIR + conv + '.jsonl';
    const h = harness({ logs: { [path]: codexTurn(1, 'K1', 'T7'), [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        unremovable: [path] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    await h.runner.deleteConv(p.pane(), (await h.runner.conversations('ATT1'))[0]);
    await h.runner.finishDelete(path);
    facts.deleteFails = { kept: path in h.log.writes, archive: h.store.get('extensions.scholium-bridge.codexArchive') || null };
  }
  // Undo of an edit archives the threads only the edit's new run used, never one the old log still uses; the end of the
  // Undo window, and the plugin stopping within it, archive the threads only the replaced part used (the second question
  // of a log that used T1 then T2)
  {
    const conv = 'chat-20261101-120000';
    const IDX = JSON.stringify({ chat: conv, titles: {}, annotation: {} });
    const log = codexTurn(1, 'K1', 'T1') + codexTurn(2, 'K2', 'T2');
    facts.archiving = {};
    for (const [name, agent] of [['claude', 'claude'], ['codex', 'codex']]) {
      for (const how of ['undo', 'end', 'stop']) {
        const h = harness({ prefs: { 'extensions.scholium-bridge.agent': agent }, logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: IDX },
                            scripts: [answered('S5', '新答')], codex: { scripts: [codexSays('新答')] } });
        h.runner.start('x');
        const p = await h.pane(h.item1); await settle(40);
        const prompt = (await h.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
        await h.runner.editTurn(p.pane(), prompt, '新问题'); await settle(600);   // the second question
        const used = h.runner.codexThreads(h.log.writes[DIR + conv + '.jsonl']);
        if (how === 'undo') await h.runner.undoReplace('ATT1/' + conv);
        else if (how === 'end') h.runner.endReplaced('ATT1/' + conv);
        else h.runner.stop();
        await settle(200);
        facts.archiving[name + '-' + how] = { used: [...used].sort(), archived: JSON.parse(h.store.get('extensions.scholium-bridge.codexArchive') || '[]') };
      }
    }
    // an end without a readable log does nothing
    const g = harness({ logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: IDX }, scripts: [answered('S5', '新答')] });
    g.runner.start('x');
    const gp = await g.pane(g.item1); await settle(40);
    const gprompt = (await g.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
    await g.runner.editTurn(gp.pane(), gprompt, '新问题'); await settle(400);
    delete g.log.writes[DIR + conv + '.jsonl'];
    g.runner.endReplaced('ATT1/' + conv); await settle(100);
    facts.archiving.unreadable = g.store.get('extensions.scholium-bridge.codexArchive') || null;
    // an Undo whose log cannot be written back archives nothing: the log keeps the edit's fork
    const f = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: IDX },
                        codex: { scripts: [codexSays('新答')] }, failLogWrites: (p, t) => t === log });
    f.runner.start('x');
    const fp = await f.pane(f.item1); await settle(40);
    const fprompt = (await f.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
    await f.runner.editTurn(fp.pane(), fprompt, '新问题'); await settle(600);
    await f.runner.undoReplace('ATT1/' + conv); await settle(200);
    facts.archiving.undoFails = { restored: f.log.writes[DIR + conv + '.jsonl'] === log, refused: !!f.log.lockedOnce,
                                  archived: f.store.get('extensions.scholium-bridge.codexArchive') || null };
  }
  // an agent whose session an edit took back before its own rewrite of the annotations is told of it; one whose latest run
  // made it is not
  {
    const conv = 'chat-20261101-120000';
    const IDX = JSON.stringify({ chat: conv, titles: {}, annotation: {} });
    // Claude Code's third run rewrote the annotations at 3050, in the run of 3000 to 3100
    const third = claudeTurn(3, 'u3', 'S1', 3000).replace('"at":2003', '"at":3100');
    const log = claudeTurn(1, 'u1', 'S1') + claudeTurn(2, 'u2', 'S1') + third;
    const applied = { config: 'D:/out/config.json', agent: 'claude', conv, at: 3050 };
    facts.ownRewrite = {};
    for (const edited of [false, true]) {
      const h = harness({ prefs: { 'extensions.scholium-bridge.agent': edited ? 'codex' : 'claude' },
                          logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: IDX, '/data/tmp/scholium/ATT1/applied.json': JSON.stringify(applied) },
                          scripts: [answered('S1', '答四')], codex: { scripts: [codexSays('Codex 答')] } });
      h.runner.start('x');
      h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666')];
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      if (edited) {
        const prompt = (await h.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
        await h.runner.editTurn(pane, prompt, '新问题二'); await settle(600);
        pane.agent.change('claude'); await settle(100);
      }
      pane.input.type('问题'); pane.send.click(); await settle(500);
      facts.ownRewrite[edited ? 'afterEdit' : 'latest'] = h.log.stdin.at(-1);
    }
  }
  // a run of Claude Code's that rewrote the annotations and was cut short without its end time (Zotero closed during it)
  // made it in its session: its end is the length on its end line, else the start of the run after it, else (the log
  // ends with it) none to go by
  {
    const conv = 'chat-20261101-120000';
    const IDX = JSON.stringify({ chat: conv, titles: {}, annotation: {} });
    const applied = { config: 'D:/out/config.json', agent: 'claude', conv, at: 3050 };
    const cut3 = end => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题3', at: 3000 })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题3' })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', uuid: 'u3', session_id: 'S1', message: { content: [{ type: 'text', text: '回答一半' }] } })
      + (end ? L({ type: 'scholium', subtype: 'end', outcome: 'interrupted', text: '中断', duration_ms: 100 }) : '');
    const base = claudeTurn(1, 'u1', 'S1') + claudeTurn(2, 'u2', 'S1');
    facts.cutShort = {};
    for (const [name, log] of [['ends', base + cut3(false)], ['followed', base + cut3(false) + codexTurn(4, 'K4', 'T1', 4000)],
                               ['endLine', base + cut3(true)]]) {
      const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'claude' },
                          logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: IDX, '/data/tmp/scholium/ATT1/applied.json': JSON.stringify(applied) },
                          scripts: [answered('S1', '答')] });
      h.runner.start('x');
      h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666')];
      const p = await h.pane(h.item1); await settle(40);
      const lastEnd = (await h.runner.readLog('ATT1', conv)).agents.claude.lastEnd;
      const pane = p.pane();
      pane.input.type('问题'); pane.send.click(); await settle(500);
      facts.cutShort[name] = { lastEnd: lastEnd === Infinity ? 'Infinity' : lastEnd, told: (h.log.stdin.at(-1) || '').includes('重写了批注') };
    }
  }
  // a new conversation's index has no empty `current`
  {
    const h = harness({ scripts: [answered('S1', '答')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题'); pane.send.click(); await settle(400);
    const saved = JSON.parse(h.log.writes[DIR + 'index.json']);
    facts.indexFile = Object.keys(saved).sort();
    const again = await h.runner.index('ATT1');
    facts.indexRead = typeof again.current;
  }
  // Claude Code asks, Codex goes on (a new thread given the conversation as text, Claude Code's answer named), Claude Code
  // again (its own session, given the turn of Codex's); then a turn it saw is not given again
  {
    const h = harness({ scripts: [answered('S1', 'Claude 答一'), answered('S1', 'Claude 答三'), answered('S1', 'Claude 答四')],
                        codex: { scripts: [codexSays('Codex 答二')] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    pane.agent.change('codex'); await settle(100);
    pane.input.type('问题二'); pane.send.click(); await settle(600);
    pane.agent.change('claude'); await settle(100);
    pane.input.type('问题三'); pane.send.click(); await settle(400);
    pane.input.type('问题四'); pane.send.click(); await settle(400);
    const proc = h.log.codexProcs.at(-1);
    const injected = proc.sent.filter(m => m.method === 'thread/inject_items').length;
    const opened = proc.sent.filter(m => /^thread\/(start|resume|fork)$/.test(m.method || '')).map(m => m.method);
    const input = proc.sent.find(m => m.method === 'turn/start').params.input[0].text;
    const args = h.log.calls[1].opts.arguments;
    facts.handOver = { injected, opened, input,
                       resume: args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 2),
                       third: h.log.stdin[1], fourth: h.log.stdin[2] };
  }
  // a new Codex thread of a conversation whose answers are all Codex's own is given it as items of the thread
  {
    const conv = 'chat-20261101-120000';
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' },
                        logs: { [DIR + conv + '.jsonl']: codexTurn(1, 'K1', 'T1') + codexTurn(2, 'K2', 'T1')
                                  + L({ type: 'scholium', subtype: 'gone', agent: 'codex', resent: false }),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        codex: { scripts: [codexSays('Codex 答3')] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题3'); pane.send.click(); await settle(600);
    const sent = h.log.codexProcs.at(-1).sent;
    facts.codexOwn = { opened: sent.filter(m => /^thread\/(start|resume|fork|inject_items)$/.test(m.method || '')).map(m => m.method),
                       items: sent.filter(m => m.method === 'thread/inject_items').map(m => m.params.items.map(i => [i.role, i.content[0].text])),
                       input: sent.find(m => m.method === 'turn/start').params.input[0].text };
  }
  // a retry by the other agent: the agent whose session saw the turn is given the answer that replaced its own, the turn
  // of its own message not; Codex's run reached it and failed, Claude Code answers again, then Codex asks (and the other way)
  {
    const conv = 'chat-20261101-120000';
    const IDX = JSON.stringify({ chat: conv, titles: {}, annotation: {} });
    const codexFailed = L({ type: 'scholium', subtype: 'run', agent: 'codex', user: '问题2', at: 1002 })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题2' })
      + L({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T1' })
      + L({ method: 'turn/started', params: { threadId: 'T1', turn: { id: 'K2', status: 'inProgress' } } })
      + L({ type: 'scholium', subtype: 'end', outcome: 'failed', text: 'stream disconnected' })
      + L({ type: 'scholium', subtype: 'time', at: 2002 });
    const claudeFailed = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题2', at: 1002 })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题2' })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', uuid: 'u2', session_id: 'S1', message: { content: [{ type: 'tool_use', id: 'tu1', name: 'Bash', input: {} }] } })
      + L({ type: 'scholium', subtype: 'end', outcome: 'failed', text: 'boom' })
      + L({ type: 'scholium', subtype: 'time', at: 2002 });
    const stale = l => [l.agents.claude.stale, l.agents.codex.stale];
    facts.retryOther = {};
    for (const [name, log, first, then] of [['toClaude', claudeTurn(1, 'u1', 'S1') + codexFailed, 'claude', 'codex'],
                                            ['toCodex', codexTurn(1, 'K1', 'T1') + claudeFailed, 'codex', 'claude']]) {
      const h = harness({ logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: IDX },
                          scripts: [answered('S1', 'Claude 重答2'), answered('S1', 'Claude 答3')],
                          codex: { scripts: [codexSays('Codex 重答2'), codexSays('Codex 答3')] } });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      pane.agent.change(first); await settle(100);
      await h.runner.retryFromView(pane); await settle(600);
      const mid = await h.runner.readLog('ATT1', conv);
      pane.agent.change(then); await settle(100);
      pane.input.type('问题3'); pane.send.click(); await settle(800);
      const end = await h.runner.readLog('ATT1', conv);
      let given = null, opened = null;
      if (then === 'codex') {
        const proc = h.log.codexProcs.at(-1);
        opened = proc.sent.filter(m => /^thread\/(start|resume|fork)$/.test(m.method || '')).map(m => m.method);
        given = proc.sent.find(m => m.method === 'turn/start').params.input[0].text;
      } else {
        const args = h.log.calls.at(-1).opts.arguments;
        opened = args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 2);
        given = h.log.stdin.at(-1);
      }
      facts.retryOther[name] = { mid: { stale: stale(mid), through: [mid.agents.claude.through, mid.agents.codex.through], turns: mid.turns.map(t => [t.agent, t.reply]) },
                                 opened, given, end: stale(end) };
    }
  }
  // a message queued while the paper runs is answered by the agent chosen when it was sent, in its own session, given
  // the turns it has not seen: a stop holds the queue, Codex is chosen, the queue goes on with Claude Code
  {
    const conv = 'chat-20261101-120000';
    const hold = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' }), 'WAIT'];   // a stop ends it
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1'),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [hold, answered('S1', 'Claude 答4')], codex: { scripts: [codexSays('Codex 答')] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题3'); pane.send.click();
    for (let i = 0; i < 3000 && !(h.runner.current && h.log.stdin.length >= 1); i++) await tick();
    const busy = pane.agent.disabled;
    pane.input.type('问题4'); pane.send.click(); await settle(20);
    const queued = h.runner.queue.map(j => [j.say, j.agent]);
    pane.send.click(); await settle(300);                                      // ■
    pane.agent.change('codex'); await settle(100);
    const chosen = [h.runner.agent(), pane.agent.disabled];
    pane.queueBox.children[0].children[1].click(); await settle(800);        // go on
    const args = h.log.calls.at(-1).opts.arguments;
    facts.queuedSwitch = { busy, queued, chosen, calls: h.log.calls.length,
                           codex: h.log.codexProcs.flatMap(c => c.sent).filter(m => m.method === 'turn/start').length,
                           resume: args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 2), given: h.log.stdin.at(-1),
                           runs: convLines(h).filter(l => l.subtype === 'run').map(l => [l.agent, l.user]) };
  }
  // a run of Claude Code's that never reached it: the next one is given the turns again, its own failed one too
  {
    const conv = 'chat-20261101-120000';
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1'),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [['STDERR:Error: boom\n', 'EXIT:1'], answered('S1', '答四')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题三'); pane.send.click(); await settle(400);
    pane.input.type('问题四'); pane.send.click(); await settle(400);
    facts.unreached = { first: h.log.stdin[0], second: h.log.stdin[1] };
  }
  // a new session of a conversation that both answered: each answer with its agent; the turn numbers of a long one go on
  {
    const conv = 'chat-20261101-120000';
    let log = '';
    for (let n = 1; n <= 12; n++) log += codexTurn(n, 'K' + n, 'T1');
    const mixed = claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1');
    const h = harness({ logs: { [DIR + conv + '.jsonl']: mixed, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }),
                                '/data/tmp/scholium/ATT2/conversations/chat-20261101-120000.jsonl': log } });
    h.runner.start('x');
    const r = h.runner;
    const turns = (await r.readLog('ATT1', conv)).turns;
    const long = (await r.readLog('ATT2', conv)).turns;
    facts.texts = { history: r.historyText(turns), missedLong: r.missedText(long.slice(0, 12), 0), missed: r.missedText(turns.slice(1), 1),
                    none: [r.missedText([], 3), r.historyText([])] };
    // the same in English
    const he = harness({ locale: 'en-US', logs: { [DIR + conv + '.jsonl']: mixed } });
    he.runner.start('x');
    const et = (await he.runner.readLog('ATT1', conv)).turns;
    facts.texts.english = { history: he.runner.historyText(et), missed: he.runner.missedText(et.slice(1), 1), missedTwo: he.runner.missedText(et, 0) };
  }
  // annotations Codex rewrote in this conversation since Claude Code's last turn: Claude Code is told, in this
  // conversation's words; ones it wrote itself here, not
  {
    const conv = 'chat-20261101-120000';
    const told = {};
    for (const [name, agent, where] of [['codexHere', 'codex', conv], ['claudeHere', 'claude', conv], ['codexElsewhere', 'codex', 'chat-20261001-090000']]) {
      const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1'),
                                  [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }),
                                  '/data/tmp/scholium/ATT1/applied.json': JSON.stringify({ config: 'D:/out/config.json', agent, conv: where, at: 1500 }) },
                          scripts: [answered('S1', '答三')] });
      h.runner.start('x');
      h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666')];
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      pane.input.type('问题三'); pane.send.click(); await settle(400);
      told[name] = h.log.stdin[0];
    }
    facts.changed = told;
  }
  // under each answer, who gave it: the agent, the model and the time; the ring shows the chosen agent's session of the
  // conversation, none for an agent without one
  {
    const conv = 'chat-20261101-120000';
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1'),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    h.runner.models.codex = [{ value: 'gpt-6-luna', label: 'GPT-6-Luna' }];
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const metas = () => flatNodes(h.runner, pane).filter(n => n.className === 'scholium-meta').map(n => n.children[0].textContent.replace(/(\d{1,2}月\d{1,2}日 )?\d{1,2}:\d{2}/, 'HH:MM'));
    const ring = () => [!pane.ring.hidden, pane.ring.title.split('\n')[2] || ''];
    const metaLines = metas();   // before a switch, which may ask Codex for its models again
    const answeredBy = [h.runner.answeredBy('Claude Code · claude-opus-5-5'), h.runner.answeredBy('Codex · gpt-6-luna'), h.runner.answeredBy('gpt-x')];
    const claudeRing = ring();
    pane.agent.change('codex'); await settle(100);
    const codexRing = ring();
    const h2 = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1'), [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h2.runner.start('x');
    const p2 = await h2.pane(h2.item1); await settle(40);
    p2.pane().agent.change('codex'); await settle(100);
    facts.labels = { metas: metaLines, claudeRing, codexRing, noSession: !p2.pane().ring.hidden, answeredBy };
  }
  // a queued message of Claude Code's that never reached it, a message to Codex going first, then the queued one's Retry:
  // its words are asked again as a new turn at the end
  {
    const conv = 'chat-20261101-120000';
    const log = claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1');
    const h = harness({ logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [answered('S1', 'Claude 答三'), ['STDERR:Error: boom\n', 'EXIT:1'], answered('S1', 'Claude 答四')],
                        codex: { scripts: [codexSays('Codex 答五')] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.runner.choose('agent', 'claude');
    await h.runner.send(h.att1, '问题三');
    await h.runner.send(h.att1, '问题四');
    await settle(800);
    const q = h.runner.queue.map(j => ({ failed: !!j.failed, logged: !!j.logged, turnAt: j.turnAt }));
    h.runner.choose('agent', 'codex');
    await h.runner.send(h.att1, '问题五');
    await settle(800);
    const qid = h.runner.queue[0] && h.runner.queue[0].qid;
    if (qid) { h.runner.retryQueued(qid); await settle(800); }
    const turns = (await h.runner.readLog('ATT1', conv)).turns.map(t => [t.user, t.agent, t.reply, t.ended]);
    facts.retryAfter = { q, qid: !!qid, turns, stdin: h.log.stdin,
                         runs: convLines(h).filter(l => l.subtype === 'run').map(l => [l.agent, l.user]) };
  }
  // the same where the agent has no session of the conversation (a new session is given the history), and where the index
  // no longer points at the words (an edit cut the log): nothing is left out; and the indices through an update
  for (const mode of ['newSession', 'cut', 'carry']) {
    const conv = 'chat-20261101-120000';
    const log = mode === 'newSession' ? codexTurn(1, 'K1', 'T1') + codexTurn(2, 'K2', 'T1') : claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1');
    const fail = ['STDERR:Error: boom\n', 'EXIT:1'];
    const h = harness({ logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: mode === 'newSession' ? [fail, fail, answered('S1', 'Claude 答四')] : [answered('S1', 'Claude 答三'), fail, answered('S1', 'Claude 答四')],
                        codex: { scripts: [codexSays('Codex 答五')] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.runner.choose('agent', 'claude');
    await h.runner.send(h.att1, '问题三');
    await h.runner.send(h.att1, '问题四');
    await settle(800);
    h.runner.choose('agent', 'codex');
    await h.runner.send(h.att1, '问题五');
    await settle(800);
    const qid = h.runner.queue[0] && h.runner.queue[0].qid;
    const out = {};
    if (mode === 'cut') h.runner.queue[0].turnAt = 1;   // an index that points at another turn
    if (mode === 'carry') {
      h.runner.queue[0].leftAt = [3];
      h.runner.carryOver(null);
      const carried = JSON.parse(h.store.get('extensions.scholium-bridge.carryOver'));
      // the list read back, and the one index an earlier copy handed over
      const restore = async saved => {
        const h2 = harness({ gateFirst: true, prefs: { 'extensions.scholium-bridge.carryOver': JSON.stringify(saved) }, logs: { [DIR + conv + '.jsonl']: log } });
        h2.runner.start('x', true); await settle(200);
        const j = [h2.runner.job && h2.runner.job.source].concat(h2.runner.queue).filter(Boolean)[0];
        return j ? [j.turnAt, j.leftAt] : null;
      };
      const restored = await restore(carried);
      const old = await restore(Object.assign({}, carried, { jobs: carried.jobs.map(s => Object.assign({}, s, { leftAt: 3 })) }));
      out.carry = { saved: carried.jobs.map(s => [s.turnAt, s.leftAt]), restored, old };
    } else if (qid) { h.runner.retryQueued(qid); await settle(800); }
    const sent = h.log.stdin[h.log.stdin.length - 1] || '';
    out.turns = (await h.runner.readLog('ATT1', conv)).turns.map(t => [t.user, t.agent, t.reply, t.ended]);
    out.count4 = sent.split('问题四').length - 1;
    out.resumed = h.log.calls.length ? h.log.calls[h.log.calls.length - 1].opts.arguments.includes('--resume') : null;
    out.sent = sent;
    (facts.retryModes = facts.retryModes || {})[mode] = out;
  }
  // a failed queued message whose turn an edit cut away: the turn at its index is now another message's, the last one,
  // and its Retry asks the words again as a new turn at the end instead of answering that turn again
  {
    const conv = 'chat-20261101-120000';
    const fail = ['STDERR:Error: boom\n', 'EXIT:1'];
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1'),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [answered('S1', 'Claude 答三'), fail, answered('S2', '改后答'), answered('S2', 'Claude 答四')],
                        codex: { scripts: [codexSays('Codex 答六')] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.runner.choose('agent', 'claude');
    await h.runner.send(h.att1, '问题三');
    await h.runner.send(h.att1, '问题四');
    await settle(800);
    const prompt = (await h.runner.readLog('ATT1', conv)).entries.find(e => e.kind === 'prompt' && e.turn === 2);
    await h.runner.editTurn(p.pane(), prompt, '问题三改'); await settle(800);
    h.runner.choose('agent', 'codex');
    await h.runner.send(h.att1, '问题六'); await settle(800);
    h.runner.choose('agent', 'claude');
    const q = h.runner.queue.map(j => [j.turnAt, j.say]);
    if (h.runner.queue[0]) { h.runner.retryQueued(h.runner.queue[0].qid); await settle(800); }
    const sent = h.log.stdin[h.log.stdin.length - 1] || '';
    facts.retryCut = { q, turns: (await h.runner.readLog('ATT1', conv)).turns.map(t => [t.user, t.agent, t.reply]), sent,
                       runs: convLines(h).filter(l => l.subtype === 'run').map(l => [l.agent, l.user]) };
  }
  // words that fail twice, each time after a newer message went first: both of their old turns are left out
  {
    const conv = 'chat-20261101-120000';
    const fail = ['STDERR:Error: boom\n', 'EXIT:1'];
    const h = harness({ logs: { [DIR + conv + '.jsonl']: claudeTurn(1, 'u1', 'S1') + codexTurn(2, 'K2', 'T1'),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) },
                        scripts: [answered('S1', 'Claude 答三'), fail, fail, answered('S1', 'Claude 答四')],
                        codex: { scripts: [codexSays('Codex 答五'), codexSays('Codex 答六')] } });
    h.runner.start('x');
    await h.pane(h.item1); await settle(40);
    h.runner.choose('agent', 'claude');
    await h.runner.send(h.att1, '问题三');
    await h.runner.send(h.att1, '问题四');
    await settle(800);
    h.runner.choose('agent', 'codex');
    await h.runner.send(h.att1, '问题五'); await settle(800);
    h.runner.choose('agent', 'claude');
    if (h.runner.queue[0]) { h.runner.retryQueued(h.runner.queue[0].qid); await settle(800); }
    const between = h.runner.queue.map(j => [j.turnAt, j.leftAt]);
    h.runner.choose('agent', 'codex');
    await h.runner.send(h.att1, '问题六'); await settle(800);
    h.runner.choose('agent', 'claude');
    if (h.runner.queue[0]) { h.runner.retryQueued(h.runner.queue[0].qid); await settle(800); }
    const sent = h.log.stdin[h.log.stdin.length - 1] || '';
    facts.retryTwice = { between, sent, turns: (await h.runner.readLog('ATT1', conv)).turns.map(t => [t.user, t.agent, t.reply]) };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_each_agent_has_its_own_session_of_a_conversation(facts):
    a = facts["agents"]
    assert a["keys"] == ["agents", "entries", "id", "path", "question", "result", "turns"]
    m = a["mix"]
    assert m["claude"] == {"session": "S1", "through": 2, "point": {"uuid": "u3"}, "rewind": None, "used": 31, "lastAt": 1003}
    assert m["codex"] == {"session": "T1", "through": 1, "point": {"turnId": "K2"}, "rewind": None, "used": 1000, "lastAt": 1002}
    assert m["turns"] == [
        ["问题1", "claude", {"claude": None, "codex": None}, "回答1"],
        ["问题2", "codex", {"claude": {"uuid": "u1"}, "codex": None}, "回答2"],
        ["问题3", "claude", {"claude": {"uuid": "u1"}, "codex": {"turnId": "K2"}}, "回答3"],
    ]


def test_a_gone_session_a_retry_and_a_compaction_are_their_agents_own(facts):
    a = facts["agents"]["after"]
    # Codex's session went, then its retry of the third turn answered it in a new thread; Claude Code's compaction keeps its
    # turns, takes its point away and leaves the size it made
    assert a["codex"] == {"session": "T2", "through": 2, "point": {"turnId": "K9"}, "rewind": None, "used": 0, "lastAt": 1500}
    assert a["claude"] == {"session": "S1", "through": 2, "point": None, "rewind": None, "used": 900, "lastAt": 1003}
    assert a["turns"] == [["claude", "回答1"], ["codex", "回答2"], ["codex", "再答3"]]
    assert a["stale"] == [2, None], "Claude Code's session saw the third turn, not Codex's answer that replaced its own"
    assert a["staleMix"] == [None, None], "turns answered one after another leave nothing to give again"


def test_a_cut_takes_each_agent_it_names_back(facts):
    c = facts["agents"]["cut"]
    assert c["claude"] == {"session": "S1", "through": 0, "point": {"uuid": "u1"}, "rewind": {"uuid": "u1"}, "used": 11, "lastAt": 1001}
    assert c["codex"] == {"session": None, "through": -1, "point": None, "rewind": None, "used": 0, "lastAt": 1002}
    u = facts["agents"]["cutUnreached"]
    assert u["rewind"] == {"uuid": "u1"}, "a run that never reached the agent keeps its point"
    assert u["lastAt"] == 1001 and u["through"] == 0, "a run that never reached the agent is not the latest that did its work"
    f = facts["agents"]["cutForked"]
    assert f["session"] == "S9" and f["rewind"] is None and f["through"] == 3


def test_logs_of_earlier_versions_are_their_agents(facts):
    o = facts["agents"]["old"]
    assert o["codex"]["rewind"] == {"turnId": "K1"} and o["codex"]["session"] == "T1"
    assert o["claude"]["session"] is None and o["claude"]["through"] == -1
    assert o["run"] == [{"session": "T0", "through": 0, "point": None, "rewind": None, "used": None, "lastAt": 0}, "codex"]


def test_a_retry_that_never_reached_its_agent_does_not_take_the_turn(facts):
    r = facts["agents"]["unreachedRetry"]
    assert r["turns"] == ["claude"]
    assert r["codex"] == {"session": None, "through": -1, "point": None, "rewind": None, "used": None, "lastAt": 0}
    assert r["claude"]["session"] == "S1" and r["claude"]["through"] == 0


def test_one_list_of_the_papers_conversations(facts):
    o = facts["oneList"]
    assert o["list"] == ["claude-20261001-120000", "codex-20261002-120000", "claude-run"], "annotation sessions are not in it"
    assert o["migrated"] == "codex-20261002-120000" and o["saved"] == "codex-20261002-120000", \
        "the chosen agent's current conversation of an earlier version, kept at once"
    assert o["afterSwitch"] == "codex-20261002-120000"
    assert o["shown"] == o["switched"] == "codex-20261002-120000", "a switch keeps the conversation shown"
    assert o["rows"] == 3, "History lists them all, whichever agent is chosen"
    assert facts["migrateNull"] == "codex-20261002-120000"


def test_a_shared_conversation_goes_on_with_the_agent_chosen(facts):
    s = facts["shared"]
    assert s["conv"].startswith("chat-") and s["files"] == [s["conv"] + ".jsonl"]
    assert s["agents"] == ["claude", "codex"], "one log, each run with its agent"
    assert s["kept"] == "还没发的字", "words typed stay across a switch"
    assert s["afterNew"] == [None, None]
    assert s["sameConv"] is True, "History opens it again"


def test_retry_edit_and_compaction_go_to_the_agent_chosen(facts):
    b = facts["byChosen"]
    assert b["retry"]["args"] == ["--resume", "S1"] and b["retry"]["run"]["agent"] == "claude" and b["retry"]["run"]["user"] is None
    given = b["retry"]["stdin"]
    assert "[第 2 轮]\n用户：问题2\n回答（Codex）：回答2" in given and given.index("回答（Codex）") < given.index("问题3"), \
        "the retry is given Codex's turn it has not seen, before the question"
    assert given.count("问题3") == 1 and "[第 3 轮]" not in given, "the retried question once, as the message"
    e = b["edit"]
    assert e["marker"] == {"type": "scholium", "subtype": "rewind", "points": {"claude": {"uuid": "u1"}}}
    assert e["codex"] is None, "Codex had no session before the question: none in the conversation kept"
    assert e["args"] == ["--resume", "S1", "--resume-session-at", "u1", "--fork-session"]
    assert e["run"]["agent"] == "claude" and e["run"]["rewind"] == {"uuid": "u1"}
    # its point is its answer to the turn right before the edited question: no turn between them to give
    assert "[第" not in e["stdin"] and "新问题二" in e["stdin"]
    assert b["compact"] == {"resumed": True, "compacted": True, "claude": 0}


def test_an_edit_again_keeps_the_other_agents_way_back(facts):
    t = facts["editTwice"]
    p = t["point"]
    first = {"type": "scholium", "subtype": "rewind", "points": {"claude": {"uuid": "u1"}, "codex": {"turnId": "K2"}}}
    assert p["first"] == [first] and p["markers"] == [first], "one marker, Codex still going back to its point"
    assert p["codex"] == {"session": "T1", "rewind": {"turnId": "K2"}}
    assert p["calls"] == 2 and p["prompts"][-1] == "再改问题"
    # Claude Code goes back to its answer to the first turn: Codex's second turn lies between it and the edited question
    for given, words in zip(p["stdin"], ["新问题", "再改问题"]):
        assert "[第 2 轮]\n用户：问题2\n回答（Codex）：回答2" in given and given.index("回答（Codex）") < given.index(words)
        assert "[第 1 轮]" not in given and "[第 3 轮]" not in given and "问题3" not in given, "not its own turn, nor the cut one"
    n = t["none"]
    first = {"type": "scholium", "subtype": "rewind", "points": {"claude": {"uuid": "u1"}, "codex": None}}
    assert n["first"] == [first], "Claude Code, answering, goes back to its point too"
    assert n["markers"] == [first], "one marker, Codex still sent to a new session"
    assert n["codex"] == {"session": None, "rewind": None}, "not the thread that saw the cut turns"
    assert n["calls"] == 2 and n["prompts"][-1] == "再改问题"


def test_the_agent_answering_an_edit_goes_back_though_it_never_saw_the_question(facts):
    c = facts["unseenEdit"]["claude"]
    assert c["args"] == ["--resume", "S1", "--resume-session-at", "u2", "--fork-session"], "a session of its own from its latest point"
    assert c["marker"] == [{"type": "scholium", "subtype": "rewind", "points": {"claude": {"uuid": "u2"}}}]
    assert c["back"] == ["S1", 1] and c["next"] == [["--resume", "S1"], False], "after Undo the old session goes on as it was"
    assert c["archived"] is None
    x = facts["unseenEdit"]["codex"]
    assert x["sent"] == [["thread/fork", "T1", "K1"]]
    assert x["marker"] == [{"type": "scholium", "subtype": "rewind", "points": {"codex": {"turnId": "K1"}}}]
    assert x["archived"] == ["F1"] and x["back"] == "T1", "Undo archives the fork and gives the thread back"


def test_an_earlier_edit_after_a_later_one_takes_codex_back(facts):
    p = facts["cutMarker"]["point"]
    assert p["first"] == [{"type": "scholium", "subtype": "rewind", "points": {"claude": {"uuid": "u3"}, "codex": {"turnId": "K1"}}}]
    assert p["markers"] == [{"type": "scholium", "subtype": "rewind", "points": {"claude": {"uuid": "u2"}, "codex": {"turnId": "K1"}}}], \
        "one marker: Codex goes back to its point before the earlier question"
    assert p["codex"] == {"session": "T1", "rewind": {"turnId": "K1"}}
    assert p["sent"] == [["thread/fork", "T1", "K1"]], "the next Codex message forks the thread, never resumes it as it was"
    n = facts["cutMarker"]["none"]
    assert n["first"] == [{"type": "scholium", "subtype": "rewind", "points": {"claude": {"uuid": "u2"}, "codex": None}}]
    assert n["markers"] == [{"type": "scholium", "subtype": "rewind", "points": {"codex": None}}], \
        "Codex had no point before the question: a new session"
    assert n["codex"] == {"session": None, "rewind": None} and n["sent"] == [["thread/start", None, None]]


def test_a_deleted_shared_conversations_codex_thread_is_archived(facts):
    d = facts["deleted"]
    assert d["archive"] == ["T7"] and d["index"] is None


def test_every_codex_thread_of_a_deleted_conversation_is_archived(facts):
    assert facts["deletedAll"] == ["T7", "T8"]


def test_undo_and_its_end_archive_only_the_threads_the_other_text_used(facts):
    a = facts["archiving"]
    assert a["claude-undo"]["archived"] == [], "the thread the old log still uses is not archived"
    assert a["claude-end"]["archived"] == ["T2"], "the replaced part's thread, once the Undo goes"
    assert a["codex-undo"]["archived"] == ["F1"] and a["codex-undo"]["used"] == ["F1", "T1"], "the fork of the edit"
    assert a["codex-end"]["archived"] == ["T2"], "the fork and the thread before the edit stay"
    assert a["unreadable"] is None, "without a log to read nothing is archived"


def test_the_plugin_stopping_within_the_undo_window_archives_the_replaced_part(facts):
    a = facts["archiving"]
    assert a["claude-stop"]["archived"] == ["T2"] and a["codex-stop"]["archived"] == ["T2"]


def test_threads_are_archived_only_once_their_log_is_written_back_or_removed(facts):
    u = facts["archiving"]["undoFails"]
    assert u["refused"] is True and u["restored"] is False
    assert u["archived"] is None, "the log still holds the edit's fork"
    d = facts["deleteFails"]
    assert d["kept"] is True and d["archive"] is None, "the log still holds its thread"


def test_a_run_cut_short_made_its_rewrite_in_its_session(facts):
    c = facts["cutShort"]
    assert c["endLine"] == {"lastEnd": 3100, "told": False}, "its end: the start and the length on its end line"
    assert c["followed"] == {"lastEnd": 4000, "told": False}, "its end: before the next run started"
    assert c["ends"] == {"lastEnd": "Infinity", "told": False}, "the log ends with it: every rewrite of its own is in it"


def test_an_agent_is_told_of_its_own_rewrite_an_edit_took_its_session_back_before(facts):
    r = facts["ownRewrite"]
    assert "重写了批注" not in r["latest"], "its latest run made it: in its session"
    assert "上次之后，Claude Code 在这段对话里用配置 D:/out/config.json 重写了批注" in r["afterEdit"]


def test_a_new_conversations_index_has_no_empty_current(facts):
    assert facts["indexFile"] == ["annotation", "chat", "titles"] and facts["indexRead"] == "object"


def test_the_agent_chosen_is_given_what_it_has_not_seen(facts):
    h = facts["handOver"]
    assert h["opened"] == ["thread/start"] and h["injected"] == 0, "Claude Code answered in it: not as items of the thread"
    given = h["input"]
    assert given.startswith("下面是这段对话之前的内容（Zotero 里保存的记录），每轮注明是谁回答的：\n\n"
                            "[第 1 轮]\n用户：问题一\n回答（Claude Code）：Claude 答一\n\n——以上是之前的对话，新消息如下——"), \
        "a new Codex thread is given the conversation as text, each answer named"
    assert given.count("问题二") == 1 and given.index("回答（Claude Code）") < given.index("问题二")
    assert h["resume"] == ["--resume", "S1"], "Claude Code goes on with its own session"
    third = h["third"]
    assert "[第 2 轮]\n用户：问题二\n回答（Codex）：Codex 答二" in third
    assert "[第 1 轮]" not in third, "the turn it answered itself is in its session"
    assert third.index("回答（Codex）") < third.index("问题三"), "the turns it did not see come before the message"
    assert "[第" not in h["fourth"], "a turn it saw is not given again"


def test_a_run_that_never_reached_the_agent_gives_the_turns_again(facts):
    u = facts["unreached"]
    assert "[第 2 轮]" in u["first"] and "[第 2 轮]" in u["second"]
    assert "[第 3 轮]\n用户：问题三\n回答（Claude Code）：（没有完成" in u["second"]


def test_the_conversation_given_names_who_answered(facts):
    t = facts["texts"]
    assert t["history"].startswith("下面是这段对话之前的内容（Zotero 里保存的记录），每轮注明是谁回答的：")
    assert "[第 1 轮]\n用户：问题1\n回答（Claude Code）：回答1" in t["history"] and "[第 2 轮]\n用户：问题2\n回答（Codex）：回答2" in t["history"]
    assert "接不上" not in t["history"]
    zhOpen = "下面是这段对话里，你上次回答之后的 1 轮。这期间用户在 Zotero 里接着问，有的由别的智能体回答，每轮注明了回答者。它们属于这段对话，请接着它们回答："
    assert t["missed"].startswith(zhOpen)
    assert "[第 2 轮]" in t["missed"] and t["missed"].endswith("——以上是这段对话最近的几轮，下面是用户的新消息——")
    assert "你的会话里没有" not in t["missed"] and "你没看到的" not in t["missed"]
    m = t["missedLong"]
    assert "之前的 7 轮对话（摘录）" in m and "[第 8 轮]" in m and "[第 12 轮]" in m and "[第 7 轮]" not in m
    assert t["none"] == ["", ""]
    e = t["english"]
    assert e["history"].startswith("Below is this conversation so far (the record kept in Zotero), each answer with the agent that gave it:")
    assert "[Turn 2]\nUser: 问题2\nAnswer (Codex): 回答2" in e["history"]
    enRest = " Meanwhile the user went on asking in Zotero, some answered by another agent; each answer names the agent that gave it. They are part of this conversation; answer as its continuation:"
    enEnd = "--- the latest exchanges of this conversation end; the user's new message follows ---"
    assert e["missed"].startswith("Below is the exchange of this conversation after your last answer." + enRest)
    assert e["missedTwo"].startswith("Below are the 2 exchanges of this conversation after your last answer." + enRest)
    assert e["missed"].endswith(enEnd) and e["missedTwo"].endswith(enEnd)
    assert "your session does not have" not in e["missed"] + e["missedTwo"]


def test_annotations_rewritten_since_are_told(facts):
    c = facts["changed"]
    assert "上次之后，Codex 在这段对话里用配置 D:/out/config.json 重写了批注" in c["codexHere"]
    assert "重写了批注" not in c["claudeHere"], "its own rewrite in this conversation is in its session"
    assert "上次之后，Codex 在这篇论文的另一段对话里用配置 D:/out/config.json 重写了批注" in c["codexElsewhere"]


def test_each_answer_names_who_gave_it(facts):
    l = facts["labels"]
    assert l["metas"] == ["Claude Code · Opus 5.5 · HH:MM", "Codex · GPT-6-Luna · HH:MM"]
    assert l["answeredBy"] == ["Claude Code · Opus 5.5", "Codex · GPT-6-Luna", "gpt-x"]


def test_the_ring_is_the_chosen_agents_session(facts):
    l = facts["labels"]
    # each agent's own context: Claude Code 11 of 200,000 tokens, Codex 1,000 of 1,000,000 (kTokens, contextTokens)
    assert l["claudeRing"] == [True, "11 / 200k tokens"]
    assert l["codexRing"] == [True, "1k / 1,000k tokens"]
    assert l["noSession"] is False, "an agent without a session of the conversation has no ring"


def test_a_new_codex_thread_of_codexs_own_answers_is_given_them_as_items(facts):
    c = facts["codexOwn"]
    assert c["opened"] == ["thread/start", "thread/inject_items"]
    assert c["items"] == [[["user", "问题1"], ["assistant", "回答1"], ["user", "问题2"], ["assistant", "回答2"]]]
    assert "[第" not in c["input"] and "下面是这段对话之前的内容" not in c["input"], "not again as text"


def test_the_agent_whose_answer_a_retry_replaced_is_given_the_new_one(facts):
    r = facts["retryOther"]
    a = r["toClaude"]
    assert a["mid"]["turns"] == [["claude", "回答1"], ["claude", "Claude 重答2"]]
    assert a["mid"]["through"] == [1, 1] and a["mid"]["stale"] == [None, 1], "Codex's session saw the turn, not Claude Code's answer"
    assert a["opened"] == ["thread/resume"], "Codex goes on with its own thread"
    assert "[第 2 轮]\n用户：问题2\n回答（Claude Code）：Claude 重答2" in a["given"]
    assert a["given"].index("回答（Claude Code）") < a["given"].index("问题3")
    assert "[第 1 轮]" not in a["given"] and "[第 3 轮]" not in a["given"], "not the turns it saw, nor its message's own"
    assert a["end"] == [None, None], "once given, nothing left to give"
    b = r["toCodex"]
    assert b["mid"]["turns"] == [["codex", "回答1"], ["codex", "Codex 重答2"]]
    assert b["mid"]["through"] == [1, 1] and b["mid"]["stale"] == [1, None]
    assert b["opened"] == ["--resume", "S1"]
    assert "[第 2 轮]\n用户：问题2\n回答（Codex）：Codex 重答2" in b["given"]
    assert b["given"].index("回答（Codex）") < b["given"].index("问题3")
    assert "[第 1 轮]" not in b["given"] and "[第 3 轮]" not in b["given"]
    assert b["end"] == [None, None]


def test_a_failed_queued_message_is_asked_again_at_the_end_when_a_newer_one_went_first(facts):
    r = facts["retryAfter"]
    assert r["qid"] and r["q"][0] == {"failed": True, "logged": True, "turnAt": 3}, r["q"]
    users = [t[0] for t in r["turns"]]
    assert users[-4:] == ["问题三", "问题四", "问题五", "问题四"], users
    assert r["turns"][-2][1] == "codex" and r["turns"][-2][2] == "Codex 答五", "the newer turn keeps its agent and answer"
    assert r["turns"][-1][1] == "claude" and r["turns"][-1][2] == "Claude 答四"
    sent = r["stdin"][-1]
    assert "问题五" in sent and "Codex 答五" in sent, "the agent is given the newer turn"
    assert sent.count("问题四") == 1, "its words only in the message"
    assert sent.index("问题五") < sent.index("问题四")
    assert "[第 5 轮]\n用户：问题五" in sent and "[第 4 轮]" not in sent, "the turn left behind is not given, the others keep their numbers"
    assert r["runs"][-1] == ["claude", "问题四"]
    old = r["turns"][-3]
    assert old[0] == "问题四" and old[3], "the old turn stays in the log with its failure"


def test_the_retry_of_a_new_session_is_not_given_the_left_behind_turn_either(facts):
    m = facts["retryModes"]["newSession"]
    assert m["resumed"] is False, "no session of the conversation: a new one"
    assert m["count4"] == 1, "its words only in the message"
    assert "[第 5 轮]" in m["sent"] and "[第 1 轮]" in m["sent"] and "[第 4 轮]" not in m["sent"]
    assert [t[0] for t in m["turns"]][-2:] == ["问题五", "问题四"] and m["turns"][-3][3]


def test_an_index_that_no_longer_points_at_the_words_leaves_nothing_out(facts):
    m = facts["retryModes"]["cut"]
    assert [t[0] for t in m["turns"]][-2:] == ["问题五", "问题四"], "asked again at the end"
    assert m["count4"] == 2 and "[第 4 轮]" in m["sent"], "the old turn is given, as nothing says it is the same words"


def test_the_indices_go_through_an_update(facts):
    c = facts["retryModes"]["carry"]["carry"]
    assert c["saved"] == [[3, [3]]] and c["restored"] == [3, [3]]
    assert c["old"] == [3, [3]], "the one index an earlier copy handed over is read as a list"


def test_a_failed_queued_message_whose_turn_an_edit_cut_away_is_asked_again_at_the_end(facts):
    r = facts["retryCut"]
    assert r["q"] == [[3, "问题四"]], "its index is now the last turn, another message's"
    assert r["turns"] == [["问题1", "claude", "回答1"], ["问题2", "codex", "回答2"], ["问题三改", "claude", "改后答"],
                          ["问题六", "codex", "Codex 答六"], ["问题四", "claude", "Claude 答四"]], \
        "the turn at its index keeps its agent and answer; the words are a new turn at the end"
    assert r["runs"][-1] == ["claude", "问题四"]
    assert "问题六" in r["sent"] and "Codex 答六" in r["sent"] and r["sent"].count("问题四") == 1


def test_words_that_fail_twice_leave_both_old_turns_out(facts):
    r = facts["retryTwice"]
    assert r["between"] == [[5, [3]]], "failed again at the end: its new turn, the first one left out"
    assert [t[0] for t in r["turns"]] == ["问题1", "问题2", "问题三", "问题四", "问题五", "问题四", "问题六", "问题四"]
    assert r["turns"][-1][1:] == ["claude", "Claude 答四"]
    sent = r["sent"]
    assert sent.count("问题四") == 1, "its words only in the message"
    assert "[第 5 轮]\n用户：问题五" in sent and "[第 7 轮]\n用户：问题六" in sent
    assert "[第 4 轮]" not in sent and "[第 6 轮]" not in sent, "neither old turn is given"


def test_a_queued_message_goes_to_the_agent_chosen_when_it_was_sent(facts):
    q = facts["queuedSwitch"]
    assert q["busy"] is True, "Agent is off while the paper runs"
    assert q["queued"] == [["问题4", "claude"]]
    assert q["chosen"] == ["codex", False], "Codex chosen while the queue is held"
    assert q["calls"] == 2 and q["codex"] == 0, "Claude Code answers it, Codex nothing"
    assert q["resume"] == ["--resume", "S1"], "in its own session"
    assert q["runs"][-1] == ["claude", "问题4"]
    given = q["given"]
    assert "[第 2 轮]\n用户：问题2\n回答（Codex）：回答2" in given and "[第 3 轮]\n用户：问题3\n回答（Claude Code）：（没有完成" in given, \
        "the turns it has not seen: Codex's, and its own stopped one"
    assert given.index("[第 3 轮]") < given.index("问题4") and "[第 1 轮]" not in given
