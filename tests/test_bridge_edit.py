"""An earlier question of the chat edited and asked again: where each turn starts in the log and the point before it,
the agents taken back to that point (Claude Code's --resume-session-at with --fork-session, Codex's thread/fork), a new
session given the conversation when they refuse, and the edit in the section with Undo."""
import pytest

from bridge_harness import NODE, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
// a turn of a Claude Code conversation as the plugin logs it: its run line, its words, two messages of the answer (the
// last one's uuid given), the result and the end time
const claudeTurn = (n, uuid, session = 'S1') => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at: 1000 + n })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session })
  + L({ type: 'assistant', uuid: uuid + '-0', session_id: session, message: { content: [{ type: 'text', text: '想一想' }] } })
  + L({ type: 'assistant', uuid, session_id: session, message: { content: [{ type: 'text', text: '回答' + n }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: session })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
const CLAUDE3 = claudeTurn(1, 'u1') + claudeTurn(2, 'u2') + claudeTurn(3, 'u3');
const codexTurn = (n, id) => L({ type: 'scholium', subtype: 'run', agent: 'codex', user: '问题' + n, at: 1000 + n })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T1' })
  + L({ method: 'turn/started', params: { threadId: 'T1', turn: { id, status: 'inProgress' } } })
  + L({ method: 'item/completed', params: { threadId: 'T1', turnId: id, item: { type: 'agentMessage', id: 'a' + n, text: '回答' + n } } })
  + L({ method: 'turn/completed', params: { threadId: 'T1', turn: { id, status: 'completed', items: [] } } })
  + L({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: '回答' + n, session_id: 'T1' })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
const CODEX3 = codexTurn(1, 'K1') + codexTurn(2, 'K2') + codexTurn(3, 'K3');
const CLAUDE_CONV = '/data/tmp/scholium/ATT1/conversations/claude-20261001-120000.jsonl';
const CODEX_CONV = '/data/tmp/scholium/ATT1/conversations/codex-20261001-120000.jsonl';
const INDEX = '/data/tmp/scholium/ATT1/conversations/index.json';
const answered = (session, text = '新回答') => [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session }),
  ev({ type: 'assistant', uuid: 'v-' + session, session_id: session, message: { content: [{ type: 'text', text }] } }),
  ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: session })];
(async () => {
  const facts = {};
  // where each turn starts, the point before it, and which turns have words of their own; a compaction takes Claude
  // Code's point away
  {
    const compacted = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: null, at: 1500, compact: true })
      + L({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'manual', pre_tokens: 9000, post_tokens: 900 } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'S1' });
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3, [CODEX_CONV]: CODEX3,
                                '/data/tmp/scholium/ATT2/conversations/claude-20261001-120000.jsonl': claudeTurn(1, 'u1') + compacted + claudeTurn(2, 'u2') } });
    h.runner.start('x');
    const c = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    const x = await h.runner.readLog('ATT1', 'codex-20261001-120000');
    const k = await h.runner.readLog('ATT2', 'claude-20261001-120000');
    facts.parse = { claude: c.turns.map(t => [t.start, t.points.claude, !!t.prompted]), codex: x.turns.map(t => [t.start, t.points.codex]),
                    compacted: k.turns.map(t => t.points.claude), promptTurns: c.entries.filter(e => e.kind === 'prompt').map(e => e.turn),
                    lengths: [claudeTurn(1, 'u1').length, claudeTurn(2, 'u2').length, codexTurn(1, 'K1').length, codexTurn(2, 'K2').length],
                    rewind: own(c).rewind };
  }
  // Claude Code: a message with a point resumes the session there as a new session; a refusal starts a new session
  // given the conversation before
  {
    const cut = claudeTurn(1, 'u1');
    for (const [name, refusal] of Object.entries({
      gone: [ev({ type: 'result', subtype: 'error_during_execution', is_error: true, num_turns: 0, session_id: 'F9',
                  errors: ['No message found with message.uuid of: u1'] }), 'STDERR:No message found with message.uuid of: u1\n', 'EXIT:1'],
      unknown: ["STDERR:error: unknown option '--resume-session-at'\n", 'EXIT:1'] })) {
      const h = harness({ logs: { [CLAUDE_CONV]: cut }, scripts: [refusal, answered('S3')] });
      h.runner.start('x');
      await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
      await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude', rewind: { uuid: 'u1' }, edited: true });
      await settle(600);
      const first = h.log.calls[0].opts.arguments, second = h.log.calls[1] ? h.log.calls[1].opts.arguments : [];
      const lines = convLines(h);
      const log = await h.runner.readLog('ATT1', 'claude-20261001-120000');
      (facts.claudeRefused = facts.claudeRefused || {})[name] = {
        first: first.slice(first.indexOf('--resume'), first.indexOf('--resume') + 5), second: second.includes('--resume'),
        history: (h.log.stdin[1] || '').includes('问题1') && (h.log.stdin[1] || '').includes('回答1'),
        runRewind: lines.filter(l => l.subtype === 'run').map(l => l.rewind || null),
        prompts: lines.filter(l => l.subtype === 'prompt').map(l => l.text), gone: lines.some(l => l.subtype === 'gone'),
        turns: log.turns.map(t => [t.user, t.reply]), session: own(log).session, rewind: own(log).rewind };
    }
  }
  // Claude Code: a message without a session has no point to go back to
  {
    const h = harness({ scripts: [answered('S1')] });
    h.runner.start('x');
    await h.runner.send(h.item1, '第一问', { kind: 'chat', agent: 'claude', rewind: { uuid: 'u1' }, edited: true });
    await settle(400);
    const args = h.log.calls[0].opts.arguments;
    facts.claudeNoSession = { resume: args.includes('--resume'), at: args.includes('--resume-session-at'), run: convLines(h).find(l => l.subtype === 'run').rewind || null };
  }
  // an edited question whose run failed before the agent had it: the next run goes back to the same point
  {
    const h = harness({ logs: { [CLAUDE_CONV]: claudeTurn(1, 'u1') }, scripts: [['STDERR:Error: boom\n', 'EXIT:1'], answered('S2')] });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
    await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude', rewind: { uuid: 'u1' }, edited: true });
    await settle(400);
    const failed = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    await h.runner.send(h.item1, '新问题二', { retry: true, conv: 'claude-20261001-120000', kind: 'chat', agent: 'claude' });
    await settle(400);
    const args = h.log.calls[1].opts.arguments;
    const after = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    facts.rewindKept = { failed: own(failed).rewind, retried: args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 5), after: own(after).rewind, session: own(after).session };
  }
  // Codex: a fork of the thread through the turn before, without the skill; a refusal starts a new thread given the
  // conversation before
  {
    const run = async refuse => {
      const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, logs: { [CODEX_CONV]: codexTurn(1, 'K1') },
                          codex: Object.assign({ scripts: [CODEX_FOLLOW, CODEX_FOLLOW] }, refuse ? { refuse: { 'thread/fork': 'turn not found: K1' } } : {}) });
      h.runner.start('x');
      await h.runner.chooseConv('ATT1', 'codex-20261001-120000');
      await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'codex-20261001-120000', agent: 'codex', rewind: { turnId: 'K1' }, edited: true });
      await settle(800);
      const sent = h.log.codexProcs.flatMap(p => p.sent).filter(m => typeof m.method === 'string');
      const fork = sent.find(m => m.method === 'thread/fork');
      const start = sent.filter(m => m.method === 'turn/start').at(-1);
      const log = await h.runner.readLog('ATT1', 'codex-20261001-120000');
      return { fork: fork ? { threadId: fork.params.threadId, lastTurnId: fork.params.lastTurnId, excludeTurns: fork.params.excludeTurns } : null,
               methods: sent.map(m => m.method).filter(m => /^thread\/(start|resume|fork|inject_items)$/.test(m)),
               skill: !!start && start.params.input.some(i => i.type === 'skill'), session: own(log).session, rewind: own(log).rewind };
    };
    facts.codexFork = { ok: await run(false), refused: await run(true) };
  }
  // the usage limit after the agent took the edited question as a new session: that session goes on after the wait,
  // without going back again
  {
    const forked = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S5' })]
      .concat(LIMIT_HIT.map(l => l.split('"S1"').join('"S5"')));
    const h = harness({ logs: { [CLAUDE_CONV]: claudeTurn(1, 'u1') }, scripts: [forked, answered('S5')] });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
    await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude', rewind: { uuid: 'u1' }, edited: true });
    await settle(400);
    const paused = !!h.runner.paused;
    h.fire();
    await settle(600);
    const args = h.log.calls[1] ? h.log.calls[1].opts.arguments : [];
    const log = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    facts.limitAfterFork = { paused, calls: h.log.calls.length, resume: args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 2),
                             at: args.includes('--resume-session-at'), runRewind: convLines(h).filter(l => l.subtype === 'run').map(l => l.rewind || null),
                             session: own(log).session, rewind: own(log).rewind };
  }
  // an update while an edited question runs: before the agent has it, the new copy goes back to the same point; after,
  // it goes on in the session the agent made of it
  {
    const handOver = async (script, next, tamper = c => c) => {
      const h = harness({ logs: { [CLAUDE_CONV]: claudeTurn(1, 'u1') }, scripts: [script] });
      h.runner.start('x');
      await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
      await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude', rewind: { uuid: 'u1' }, edited: true });
      await settle(150);
      h.runner.stop(true);
      const carried = tamper(h.store.get('extensions.scholium-bridge.carryOver'));
      const h2 = harness({ prefs: { 'extensions.scholium-bridge.carryOver': carried }, logs: ours(h), scripts: [answered(next)] });
      h2.runner.start('x', true);
      await settle(400);
      const args = h2.log.calls[0] ? h2.log.calls[0].opts.arguments : [];
      const log = await h2.runner.readLog('ATT1', 'claude-20261001-120000');
      h2.runner.stop();
      const job = JSON.parse(carried).jobs[0];
      const after = flag => (args.includes(flag) ? args[args.indexOf(flag) + 1] : null);
      return { handed: [job.resume, job.say, job.rewind || null], resume: after('--resume'), at: after('--resume-session-at'),
               fork: args.includes('--fork-session'), session: own(log).session, rewind: own(log).rewind };
    };
    facts.handedEdit = {
      before: await handOver(['WAIT'], 'S6'),
      after: await handOver([ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S7' }),
                             ev({ type: 'assistant', uuid: 'w1', session_id: 'S7', message: { content: [{ type: 'text', text: '想一想' }] } }), 'WAIT'], 'S7'),
      // a point that is neither a message nor a turn is not taken
      bad: await handOver(['WAIT'], 'S6', c => { const o = JSON.parse(c); o.jobs[0].rewind = { uuid: 7 }; return JSON.stringify(o); }) };
  }
  // the cut of an edited question leaves its point in the log: the next message goes back there from the log alone; a
  // cut without a point leaves no session, and a new one is given the conversation. The line draws nothing
  {
    const usage = { input_tokens: 10, cache_read_input_tokens: 5000, output_tokens: 20 };
    // a turn whose messages say what the session held
    const used = text => text.split('\n').filter(Boolean).map(l => JSON.parse(l))
      .map(o => (o.type === 'assistant' ? Object.assign({}, o, { message: Object.assign({}, o.message, { usage }) }) : o)).map(L).join('');
    const mark = (point, agent = 'claude') => L({ type: 'scholium', subtype: 'rewind', points: { [agent]: point } });
    const plain = used(claudeTurn(1, 'u1'));
    const UNMARKED = '/data/tmp/scholium/ATT2/conversations/claude-20261001-120000.jsonl';
    facts.marker = {};
    for (const [name, point] of Object.entries({ point: { uuid: 'u1' }, none: null })) {
      const h = harness({ logs: { [CLAUDE_CONV]: plain + mark(point), [UNMARKED]: plain }, scripts: [answered('S2')] });
      h.runner.start('x');
      await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
      const before = await h.runner.readLog('ATT1', 'claude-20261001-120000');
      const unmarked = await h.runner.readLog('ATT2', 'claude-20261001-120000');
      await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude' });
      await settle(400);
      const args = h.log.calls[0].opts.arguments;
      const after = await h.runner.readLog('ATT1', 'claude-20261001-120000');
      facts.marker[name] = { session: own(before).session, rewind: own(before).rewind, used: [own(before).context && own(before).context.used, own(unmarked).context && own(unmarked).context.used],
                             sameEntries: JSON.stringify(before.entries) === JSON.stringify(unmarked.entries),
                             drawn: h.runner.entries({ type: 'scholium', subtype: 'rewind', points: { claude: point } }).length,
                             resume: args.includes('--resume') ? args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 5) : null,
                             history: (h.log.stdin[0] || '').includes('问题1') && (h.log.stdin[0] || '').includes('回答1'),
                             after: [own(after).session, own(after).rewind], turns: after.turns.map(t => [t.user, t.reply]) };
    }
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, logs: { [CODEX_CONV]: codexTurn(1, 'K1') + mark({ turnId: 'K1' }, 'codex') },
                        codex: { scripts: [CODEX_FOLLOW] } });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', 'codex-20261001-120000');
    const before = await h.runner.readLog('ATT1', 'codex-20261001-120000');
    await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'codex-20261001-120000' });
    await settle(800);
    const sent = h.log.codexProcs.flatMap(p => p.sent).filter(m => typeof m.method === 'string');
    const fork = sent.find(m => m.method === 'thread/fork');
    const after = await h.runner.readLog('ATT1', 'codex-20261001-120000');
    facts.marker.codex = { rewind: own(before).rewind, fork: fork ? [fork.params.threadId, fork.params.lastTurnId, fork.params.excludeTurns] : null,
                           methods: sent.map(m => m.method).filter(m => /^thread\/(start|resume|fork)$/.test(m)), after: [own(after).session, own(after).rewind] };
  }
  // an edited question is not queued behind a run of the paper: it is sent when the paper is free
  {
    const h = harness({ logs: { [CLAUDE_CONV]: claudeTurn(1, 'u1') }, scripts: [['WAIT']] });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
    await h.runner.send(h.item1, '问题二', { kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude' });
    await settle(150);
    const busy = h.runner.busy('ATT1', 'chat');
    const sent = await h.runner.send(h.item1, '新问题二', { kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude', rewind: { uuid: 'u1' }, edited: true });
    facts.editBusy = { busy, sent, queued: h.runner.queue.filter(j => j.qid).length, calls: h.log.calls.length };
    h.runner.cancel(); await settle(300);
  }
  // ✎ on each of the user's own questions; a click turns it into a box with its words; ✕ or Esc leaves it
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [answered('S2')] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const said = i => pane.list.children[i].children[0];
    const editOf = i => said(i).children.find(c => /edit-prompt/.test(c.className || ''));
    const before = { runs: pane.list.children.length, edits: [0, 1, 2].map(i => !!editOf(i)), label: labelOf(editOf(1)), view: pane.chatView.className };
    editOf(1).click();
    const box = said(1);
    const input = box.children.find(c => c.tagName === 'textarea');
    const opened = { cls: box.className, value: input.value, tools: box.children.at(-1).children.map(labelOf) };
    // an Escape that ends a word typed through an input method is the method's
    const composing = key(input, { key: 'Escape', isComposing: true });
    const composed = { cls: said(1).className, kept: composing.defaultPrevented };
    key(input, { key: 'Escape' });
    const escaped = { cls: said(1).className, text: said(1).children[0].textContent };
    editOf(1).click();
    said(1).children.find(c => c.tagName === 'textarea').type('新问题二');
    said(1).children.at(-1).children[1].click();          // ✓
    await settle(500);
    const args = h.log.calls[0].opts.arguments;
    const text = h.log.writes[CLAUDE_CONV];
    const log = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    const last = pane.list.children.at(-1);
    const strip = last.children.find(c => c.className === 'scholium-undo');
    facts.editClaude = { before, opened, composed, escaped, args: args.slice(args.indexOf('--resume'), args.indexOf('--resume') + 5), kept: text.startsWith(claudeTurn(1, 'u1')),
                         marked: text.startsWith(claudeTurn(1, 'u1') + L({ type: 'scholium', subtype: 'rewind', points: { claude: { uuid: 'u1' } } })),
                         left: ['问题2', '问题3', '回答3'].filter(w => text.includes('"' + w + '"')),
                         turns: log.turns.map(t => [t.user, t.reply]), session: own(log).session, runs: pane.list.children.length,
                         strip: strip ? [strip.children[0].textContent, labelOf(strip.children[1])] : null };
    // a box opened on the new question keeps its words when Undo goes
    editOf(1).click();
    said(1).children.find(c => c.tagName === 'textarea').type('再改一次');
    h.fire(); await settle(40);
    facts.editClaude.expired = { strip: pane.list.children.at(-1).children.some(c => c.className === 'scholium-undo'), replaced: h.runner.replaced.size };
    facts.editClaude.boxKept = { cls: said(1).className, value: (said(1).children.find(c => c.tagName === 'textarea') || {}).value || null };
  }
  // a run of the conversation after the edited one ends its Undo: a follow-up that starts takes the strip away, and
  // nothing undoes it
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [answered('S2'), [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S2' }), 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(400);
    const before = { job: !!h.runner.job, replaced: h.runner.replaced.size };
    pane.input.type('追问'); pane.send.click();
    await settle(300);
    const strips = pane.list.children.filter(n => n.className === 'scholium-undo' || n.children.some(c => c.className === 'scholium-undo')).length;
    await h.runner.undoReplace('ATT1/claude-20261001-120000');
    await settle(100);
    facts.followUpEnds = { before, running: !!h.runner.job, strips, replaced: h.runner.replaced.size, kills: h.log.kills,
                           logged: ['新问题二', '追问'].map(w => h.log.writes[CLAUDE_CONV].includes('"' + w + '"')) };
    h.runner.cancel(); await settle(300);
  }
  // the Undo of an edit in another conversation of the paper going leaves this conversation's strip
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [answered('S2')] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(400);
    const strips = () => pane.list.children.filter(n => n.className === 'scholium-undo' || n.children.some(c => c.className === 'scholium-undo')).length;
    const before = strips();
    h.runner.replaced.set('ATT1/claude-20261002-120000', { key: 'ATT1', conv: 'claude-20261002-120000', timer: null });
    h.runner.endReplaced('ATT1/claude-20261002-120000');
    facts.otherConvUndo = { before, after: strips(), replaced: [...h.runner.replaced.keys()] };
  }
  // an edit the agent does not take back to its point goes on as a new session: that run is the edit's, its Undo stays
  {
    const refusal = [ev({ type: 'result', subtype: 'error_during_execution', is_error: true, num_turns: 0, session_id: 'F9',
                          errors: ['No message found with message.uuid of: u1'] }), 'STDERR:No message found with message.uuid of: u1\n', 'EXIT:1'];
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [refusal, answered('S3')] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(600);
    const words = r => { const c = r.children[0] && r.children[0].children.find(x => x.className === 'scholium-content'); return c ? c.textContent : null; };
    facts.freshKeepsUndo = { calls: h.log.calls.length, replaced: h.runner.replaced.size, session: own(await h.runner.readLog('ATT1', 'claude-20261001-120000')).session,
                             under: pane.list.children.filter(r => r.children.some(c => c.className === 'scholium-undo')).map(words) };
  }
  // a new session took over after the agent refused (a point it no longer has, a session it no longer has): the refused
  // run's error is drawn neither while it runs nor when the log is read again; a continuation without one keeps its error
  {
    const errored = (result, session) => [ev({ type: 'result', subtype: 'error_during_execution', is_error: true, num_turns: 0, session_id: session, result,
                                              errors: result ? [] : ['No message found with message.uuid of: u1'] }), 'STDERR:' + (result || 'x') + '\n', 'EXIT:1'];
    const errorLines = list => list.filter(e => e.kind === 'final' && e.error).map(e => e.text);
    const cases = {
      rewindErrors: { send: { rewind: { uuid: 'u1' }, edited: true }, refusal: errored('', 'F9') },
      rewindText: { send: { rewind: { uuid: 'u1' }, edited: true }, refusal: errored('No message found with message.uuid of: u1', 'F9') },
      goneText: { send: {}, refusal: errored('No conversation found with session ID: S1', 'S1') },
    };
    for (const [name, c] of Object.entries(cases)) {
      const h = harness({ logs: { [CLAUDE_CONV]: claudeTurn(1, 'u1') }, scripts: [c.refusal, answered('S3')] });
      h.runner.start('x');
      await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
      // what the live transcript holds each time the sections are refreshed
      const live = [];
      const refresh = h.runner.refresh;
      h.runner.refresh = function () { live.push(errorLines(h.runner.transcript)); return refresh.apply(this, arguments); };
      await h.runner.send(h.item1, '新问题二', Object.assign({ kind: 'chat', conv: 'claude-20261001-120000', agent: 'claude' }, c.send));
      await settle(600);
      const log = await h.runner.readLog('ATT1', 'claude-20261001-120000');
      (facts.refusedNoError = facts.refusedNoError || {})[name] = { live: live.flat(), reread: errorLines(log.entries), turnEnded: log.turns.map(t => t.ended),
                                                                   gone: convLines(h).filter(l => l.subtype === 'gone').map(l => l.resent) };
    }
    // a continuation has nothing to go on with (resent: false): its error stays when the log is read again
    const stoppedLog = claudeTurn(1, 'u1') + L({ type: 'scholium', subtype: 'run', agent: 'claude', user: null, at: 3000 })
      + L({ type: 'result', subtype: 'error_during_execution', is_error: true, num_turns: 0, session_id: 'S1', result: 'No conversation found with session ID: S1' })
      + L({ type: 'scholium', subtype: 'gone', agent: 'claude', resent: false });
    const h = harness({ logs: { [CLAUDE_CONV]: stoppedLog } });
    h.runner.start('x');
    const kept = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    facts.refusedNoError.stopped = { reread: errorLines(kept.entries), gone: [false] };
  }
  // a second edit of the same question leaves one marker of the cut, not two
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [answered('S2'), answered('S3')] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(400);
    h.fire(); await settle(40);   // the Undo window of the first edit is over
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '再改问题二', null);
    await settle(400);
    const lines = convLines(h), runAt = lines.map(l => l.subtype).lastIndexOf('run');
    facts.editTwice = { markers: lines.filter(l => l.subtype === 'rewind').length, before: lines.slice(0, runAt).filter(l => l.subtype === 'rewind').length,
                        prompts: lines.filter(l => l.subtype === 'prompt').map(l => l.text), calls: h.log.calls.length };
  }
  // words steered into the edited answer leave Undo under the edited question
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex', 'extensions.scholium-bridge.followUpMode': 'steer' }, logs: { [CODEX_CONV]: CODEX3 },
                        codex: { scripts: [[note('turn/started', { threadId: 'F1', turn: { id: 'TURN', status: 'inProgress' } }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[2].prompt, '新问题三', null);
    await settle(400);
    pane.input.type('补充一句'); pane.send.click();
    await settle(200);
    const words = r => { const c = r.children[0] && r.children[0].children.find(x => x.className === 'scholium-content'); return c ? c.textContent : null; };
    const under = pane.list.children.filter(r => r.children.some(c => c.className === 'scholium-undo')).map(words);
    facts.steeredUndo = { runs: pane.list.children.map(words), under, steers: h.log.steers.length, replaced: h.runner.replaced.size };
    h.runner.cancel(); await settle(300);
  }
  // an edit that waits behind another paper's run: the section shows the conversation cut, the queue and Undo, which
  // takes the edit out of the queue
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [['WAIT'], answered('S2')] });
    h.runner.start('x');
    await h.runner.send(h.item2, '别的论文', { kind: 'chat' });
    await settle(150);
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    const sent = await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(200);
    const runs = () => pane.list.children.filter(n => n.className === 'scholium-run')
      .map(r => r.children[0].children.find(c => c.className === 'scholium-content').textContent);
    const strip = pane.list.children.at(-1);
    const waiting = { other: h.runner.job && h.runner.job.key, sent, queued: h.runner.queue.filter(j => j.att.key === 'ATT1').length, runs: runs(),
                      strip: strip.className === 'scholium-undo' ? [strip.children[0].textContent, labelOf(strip.children[1])] : null,
                      state: pane.state.hidden ? null : pane.state.textContent };
    if (strip.className === 'scholium-undo') strip.children[1].click();
    await settle(300); await new Promise(r => setTimeout(r, 60)); await settle(200);
    facts.editQueued = { waiting, queued: h.runner.queue.filter(j => j.att.key === 'ATT1').length, same: h.log.writes[CLAUDE_CONV] === CLAUDE3,
                         runs: runs(), replaced: h.runner.replaced.size, other: h.runner.job && h.runner.job.key, calls: h.log.calls.length };
    h.runner.cancel(); await settle(300);
  }
  // ✓ once the paper has started a run meanwhile (an annotation): the box stays with its words, ✓ off while the paper runs
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [['WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const said = () => pane.list.children[1].children[0];
    said().children.find(c => /edit-prompt/.test(c.className || '')).click();
    said().children.find(c => c.tagName === 'textarea').type('改过的问题二');
    await h.runner.annotate([h.item1], { confirmed: true });
    await settle(200);
    const ok = said().children.at(-1).children[1];
    const busy = { busy: h.runner.busy('ATT1'), disabled: !!ok.disabled };
    ok.click(); await settle(100);
    facts.busyBox = { busy, cls: said().className, value: (said().children.find(c => c.tagName === 'textarea') || {}).value || null,
                      calls: h.log.calls.length, same: h.log.writes[CLAUDE_CONV] === CLAUDE3 };
    h.runner.cancel(); await settle(300);
  }
  // a turn is the view's when its words are the question's, or the question's with words steered into it
  {
    const STEERED = '/data/tmp/scholium/ATT2/conversations/claude-20261001-120000.jsonl';
    const steered = claudeTurn(1, 'u1') + L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题2', at: 1100 })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题2' }) + L({ type: 'system', subtype: 'init', session_id: 'S1' })
      + L({ type: 'scholium', subtype: 'steer', text: '补充一句' })
      + L({ type: 'assistant', uuid: 'u2', session_id: 'S1', message: { content: [{ type: 'text', text: '回答2' }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '回答2', session_id: 'S1' });
    const longer = CLAUDE3.split('问题2').join('问题22');
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3, [STEERED]: steered } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    const prompt = h.runner.runsOf(view.entries)[1].prompt;
    // the log changed under the view: its second question is now other words that start with the same ones
    h.log.writes[CLAUDE_CONV] = longer; h.log.mtimes[CLAUDE_CONV] = ++h.log.clock;
    const refused = await h.runner.editTurn(view, prompt, '改', null);
    await settle(100);
    facts.turnOf = { steered: !!h.runner.turnOf(await h.runner.readLog('ATT2', 'claude-20261001-120000'), { turn: 1, text: '问题2' }),
                     longer: !!h.runner.turnOf(await h.runner.readLog('ATT1', 'claude-20261001-120000'), prompt),
                     refused, same: h.log.writes[CLAUDE_CONV] === longer, calls: h.log.calls.length };
  }
  // a cut that cannot be written leaves the conversation's title as it was
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3, [INDEX]: JSON.stringify({ current: {}, titles: { 'claude-20261001-120000': '问题1' }, annotation: {} }) },
                        failLogWrites: (path, text, o) => !(o && o.mode) && text === '' });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    const sent = await h.runner.editTurn(view, h.runner.runsOf(view.entries)[0].prompt, '第一问改了', null);
    await settle(100);
    facts.cutFails = { sent, title: (await h.runner.index('ATT1')).titles['claude-20261001-120000'],
                       saved: JSON.parse(h.log.writes[INDEX]).titles['claude-20261001-120000'], same: h.log.writes[CLAUDE_CONV] === CLAUDE3,
                       replaced: h.runner.replaced.size, calls: h.log.calls.length };
  }
  // the first question: a new session; the conversation's title follows it unless it was renamed
  {
    const runFirst = async title => {
      const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3, [INDEX]: JSON.stringify({ current: {}, titles: { 'claude-20261001-120000': title }, annotation: {} }) },
                          scripts: [answered('S5')] });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(60);
      const pane = p.pane();
      const view = h.runner.viewOf(pane, 'chat');
      const prompt = h.runner.runsOf(view.entries)[0].prompt;
      await h.runner.editTurn(view, prompt, '第一问改了', null);
      await settle(400);
      return { resume: h.log.calls[0].opts.arguments.includes('--resume'), title: JSON.parse(h.log.writes[INDEX]).titles['claude-20261001-120000'],
               turns: (await h.runner.readLog('ATT1', 'claude-20261001-120000')).turns.map(t => t.user),
               marker: h.log.writes[CLAUDE_CONV].includes('"subtype":"rewind"') };
    };
    facts.editFirst = { auto: await runFirst('问题1'), renamed: await runFirst('我的名字') };
  }
  // an edit where the session has no point before the question (Claude Code after a compaction): the cut leaves a marker
  // without one, and the question runs as a new session given the conversation before it
  {
    const compacted = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: null, at: 1500, compact: true })
      + L({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'manual', pre_tokens: 9000, post_tokens: 900 } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'S1' });
    const kept = claudeTurn(1, 'u1') + compacted;
    const h = harness({ logs: { [CLAUDE_CONV]: kept + claudeTurn(2, 'u2') + claudeTurn(3, 'u3') }, scripts: [answered('S4')] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    const second = h.runner.runsOf(view.entries).find(r => r.prompt && r.prompt.text === '问题2').prompt;
    const sent = await h.runner.editTurn(view, second, '新问题二', null);
    await settle(500);
    const args = h.log.calls[0].opts.arguments;
    const text = h.log.writes[CLAUDE_CONV];
    const log = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    facts.editCompacted = { sent, resume: args.includes('--resume'), at: args.includes('--resume-session-at'),
                            history: (h.log.stdin[0] || '').includes('问题1') && (h.log.stdin[0] || '').includes('回答1'),
                            marked: text.startsWith(kept + L({ type: 'scholium', subtype: 'rewind', points: { claude: null } })),
                            turns: log.turns.map(t => [t.user, t.reply]), session: own(log).session };
  }
  // Undo while the new answer runs: it stops without 已取消, the log comes back as it was, the words do not go to the box
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S2' }), 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    const stateBefore = pane.state.hidden ? null : pane.state.textContent;
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(200);
    const during = { running: !!h.runner.job, view: pane.chatView.className };
    const strip = pane.list.children.at(-1).children.find(c => c.className === 'scholium-undo');
    strip.children[1].click();
    await settle(600);
    await new Promise(r => setTimeout(r, 60)); await settle(200);   // Undo waits for the run to stop in steps of real time
    const log = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    facts.undo = { during, kills: h.log.kills, same: h.log.writes[CLAUDE_CONV] === CLAUDE3, turns: log.turns.map(t => t.user),
                   runs: pane.list.children.length, box: pane.input.value, cancelledNotice: JSON.stringify(h.log.notices).includes('已取消'),
                   state: (pane.state.hidden ? null : pane.state.textContent) === stateBefore, replaced: h.runner.replaced.size, job: !!h.runner.job };
  }
  // Codex: Undo leaves the forked thread to be archived
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, logs: { [CODEX_CONV]: CODEX3 }, codex: { scripts: [CODEX_FOLLOW] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[2].prompt, '新问题三', null);
    await settle(600);
    await h.runner.undoReplace('ATT1/codex-20261001-120000');
    await settle(100);
    facts.undoCodex = { same: h.log.writes[CODEX_CONV] === CODEX3, archive: h.store.get('extensions.scholium-bridge.codexArchive') };
  }
  // no ✎ while the paper runs, on words steered into a turn, or on the annotation tab; editTurn refuses while it runs
  {
    const steered = claudeTurn(1, 'u1') + L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题2', at: 1100 })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题2' }) + L({ type: 'system', subtype: 'init', session_id: 'S1' })
      + L({ type: 'scholium', subtype: 'steer', text: '补充一句' })
      + L({ type: 'assistant', uuid: 'u2', session_id: 'S1', message: { content: [{ type: 'text', text: '回答2' }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '回答2', session_id: 'S1' });
    const h = harness({ logs: { [CLAUDE_CONV]: steered }, scripts: [[...SCRIPT, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const edits = pane.list.children.map(r => !!r.children[0] && r.children[0].children.some(c => /edit-prompt/.test(c.className || '')));
    const view = h.runner.viewOf(pane, 'chat');
    const second = h.runner.runsOf(view.entries)[1].prompt;
    second && pane.list.children[1].children[0].children.find(c => /edit-prompt/.test(c.className || '')).click();
    const boxValue = pane.list.children[1].children[0].children.find(c => c.tagName === 'textarea').value;
    key(pane.list.children[1].children[0].children.find(c => c.tagName === 'textarea'), { key: 'Escape' });
    pane.input.type('问题3'); pane.send.click(); await settle(200);
    facts.notEditable = { edits, boxValue, view: pane.chatView.className, refused: await h.runner.editTurn(view, second, '改', null) };
    h.runner.cancel(); await settle(300);   // the run that waits ends, so that node can
  }
  // Undo of an edit while Zotero is unfocused: the run it stops sends no system notification
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S2' }), 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    h.focus(false);
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(200);
    const before = h.log.notifications.length;
    await h.runner.undoReplace('ATT1/claude-20261001-120000');
    await settle(600);
    await new Promise(r => setTimeout(r, 60)); await settle(200);
    facts.undoUnfocused = { before, after: h.log.notifications.length, job: !!h.runner.job, same: h.log.writes[CLAUDE_CONV] === CLAUDE3 };
  }
  // a send that throws: the edit is undone, the log comes back as it was
  {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    h.runner.send = async () => { throw new Error('send broke'); };
    let sent = 'threw';
    try { sent = await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null); } catch (e) {}
    await settle(100);
    facts.sendThrows = { sent, same: h.log.writes[CLAUDE_CONV] === CLAUDE3, replaced: h.runner.replaced.size };
  }
  // a log of an earlier version: a run line without the user's words, then the prompt; the cut takes the run line with it
  {
    const old = n => L({ type: 'scholium', subtype: 'run', agent: 'claude', at: 1000 + n })
      + L({ type: 'scholium', subtype: 'prompt', text: '问题' + n })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', uuid: 'o' + n, session_id: 'S1', message: { content: [{ type: 'text', text: '回答' + n }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: 'S1' });
    const OLD2 = old(1) + old(2);
    const h = harness({ logs: { [CLAUDE_CONV]: OLD2 } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const pane = p.pane();
    const view = h.runner.viewOf(pane, 'chat');
    const log = await h.runner.readLog('ATT1', 'claude-20261001-120000');
    const starts = log.turns.map(t => t.start);
    h.runner.send = async () => true;
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(100);
    const written = h.log.writes[CLAUDE_CONV] || '';
    const lines = written.split('\n').filter(Boolean).map(l => JSON.parse(l));
    facts.oldRunLine = { starts, first: old(1).length, runs: lines.filter(l => l.subtype === 'run').length, last: lines.at(-1).subtype,
                         kept: written.startsWith(old(1)) };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_each_turn_knows_where_it_starts_and_the_point_before_it(facts):
    p = facts["parse"]
    c1, c2, x1, x2 = p["lengths"]
    assert p["claude"] == [[0, None, True], [c1, {"uuid": "u1"}, True], [c1 + c2, {"uuid": "u2"}, True]]
    assert p["codex"] == [[0, None], [x1, {"turnId": "K1"}], [x1 + x2, {"turnId": "K2"}]]
    assert p["compacted"] == [None, None], "Claude Code no longer has the messages before a compaction"
    assert p["promptTurns"] == [0, 1, 2] and p["rewind"] is None


def test_claude_code_goes_back_as_a_new_session_or_starts_one(facts):
    for name, r in facts["claudeRefused"].items():
        assert r["first"] == ["--resume", "S1", "--resume-session-at", "u1", "--fork-session"], name
        assert r["second"] is False and r["history"] is True, name
        assert r["runRewind"] == [None, {"uuid": "u1"}, None], name
        assert r["prompts"] == ["问题1", "新问题二"] and r["gone"] is True, name
        assert r["turns"] == [["问题1", "回答1"], ["新问题二", "新回答"]] and r["session"] == "S3" and r["rewind"] is None, name


def test_a_conversation_without_a_session_has_no_point(facts):
    assert facts["claudeNoSession"] == {"resume": False, "at": False, "run": None}


def test_a_failed_edit_goes_back_to_the_same_point_next_time(facts):
    r = facts["rewindKept"]
    assert r["failed"] == {"uuid": "u1"}
    assert r["retried"] == ["--resume", "S1", "--resume-session-at", "u1", "--fork-session"]
    assert r["after"] is None and r["session"] == "S2"


def test_codex_forks_the_thread_or_starts_one(facts):
    ok, refused = facts["codexFork"]["ok"], facts["codexFork"]["refused"]
    assert ok["fork"] == {"threadId": "T1", "lastTurnId": "K1", "excludeTurns": True}
    assert ok["methods"] == ["thread/fork"] and ok["skill"] is False and ok["session"] == "F1" and ok["rewind"] is None
    assert refused["methods"] == ["thread/fork", "thread/start", "thread/inject_items"]
    assert refused["skill"] is True and refused["session"] == "T1" and refused["rewind"] is None


def test_the_usage_limit_after_a_fork_goes_on_in_the_fork(facts):
    r = facts["limitAfterFork"]
    assert r["paused"] is True and r["calls"] == 2
    assert r["resume"] == ["--resume", "S5"] and r["at"] is False, "the new session has the edited question: no second rewind"
    assert r["runRewind"] == [None, {"uuid": "u1"}, None]
    assert r["session"] == "S5" and r["rewind"] is None


def test_an_update_hands_the_point_over_until_the_agent_has_the_question(facts):
    before, after = facts["handedEdit"]["before"], facts["handedEdit"]["after"]
    assert before["handed"] == ["S1", "新问题二", {"uuid": "u1"}]
    assert [before["resume"], before["at"], before["fork"]] == ["S1", "u1", True]
    assert before["session"] == "S6" and before["rewind"] is None
    assert after["handed"] == ["S7", "", None]
    assert [after["resume"], after["at"], after["fork"]] == ["S7", None, False]
    assert after["session"] == "S7" and after["rewind"] is None
    bad = facts["handedEdit"]["bad"]
    assert bad["handed"] == ["S1", "新问题二", {"uuid": 7}]
    assert [bad["resume"], bad["at"], bad["fork"]] == ["S1", None, False], "a point that is neither a message nor a turn is not taken"


def test_the_cut_leaves_the_point_for_the_next_message(facts):
    m = facts["marker"]["point"]
    assert m["session"] == "S1" and m["rewind"] == {"uuid": "u1"} and m["used"] == [5030, 5030]
    assert m["sameEntries"] is True and m["drawn"] == 0
    assert m["resume"] == ["--resume", "S1", "--resume-session-at", "u1", "--fork-session"] and m["history"] is False
    assert m["after"] == ["S2", None] and m["turns"] == [["问题1", "回答1"], ["新问题二", "新回答"]]


def test_a_cut_without_a_point_starts_a_new_session_with_the_conversation(facts):
    m = facts["marker"]["none"]
    assert m["session"] is None and m["rewind"] is None and m["used"] == [0, 5030], "the new session reports its own context"
    assert m["sameEntries"] is True and m["drawn"] == 0
    assert m["resume"] is None and m["history"] is True
    assert m["after"] == ["S2", None] and m["turns"] == [["问题1", "回答1"], ["新问题二", "新回答"]]


def test_codex_forks_at_the_point_the_cut_left(facts):
    c = facts["marker"]["codex"]
    assert c["rewind"] == {"turnId": "K1"} and c["fork"] == ["T1", "K1", True] and c["methods"] == ["thread/fork"]
    assert c["after"] == ["F1", None]


def test_an_edited_question_is_not_queued_behind_a_run(facts):
    assert facts["editBusy"] == {"busy": True, "sent": False, "queued": 0, "calls": 1}


def test_a_question_is_edited_in_place_and_asked_again(facts):
    e = facts["editClaude"]
    assert e["before"] == {"runs": 3, "edits": [True, True, True], "label": "编辑", "view": "scholium-view chat"}
    assert e["opened"] == {"cls": "scholium-entry prompt scholium-edit", "value": "问题2", "tools": ["取消", "发送"]}
    assert e["composed"] == {"cls": "scholium-entry prompt scholium-edit", "kept": False}, "an Escape while composing leaves the box"
    assert e["escaped"]["cls"] == "scholium-entry prompt editable" and e["escaped"]["text"] == "问题2"
    assert e["args"] == ["--resume", "S1", "--resume-session-at", "u1", "--fork-session"]
    assert e["kept"] is True and e["left"] == []
    assert e["marked"] is True, "the cut leaves the point before the question in the log"
    assert e["turns"] == [["问题1", "回答1"], ["新问题二", "新回答"]] and e["session"] == "S2" and e["runs"] == 2
    assert e["strip"] == ["已替换", "撤销"]
    assert e["expired"] == {"strip": False, "replaced": 0}
    assert e["boxKept"] == {"cls": "scholium-entry prompt scholium-edit", "value": "再改一次"}, "Undo going leaves an open box as it is"


def test_a_run_of_the_conversation_after_the_edit_ends_its_undo(facts):
    f = facts["followUpEnds"]
    assert f["before"] == {"job": False, "replaced": 1}
    assert f["running"] is True and f["strips"] == 0 and f["replaced"] == 0, "the follow-up that started has no Undo"
    assert f["kills"] == 0 and f["logged"] == [True, True], "nothing undoes the edit nor the follow-up"


def test_undo_going_in_another_conversation_leaves_this_ones(facts):
    assert facts["otherConvUndo"] == {"before": 1, "after": 1, "replaced": ["ATT1/claude-20261001-120000"]}


def test_the_new_session_of_a_refused_edit_keeps_its_undo(facts):
    assert facts["freshKeepsUndo"] == {"calls": 2, "replaced": 1, "session": "S3", "under": ["新问题二"]}


def test_words_steered_into_the_edited_answer_leave_undo_under_the_question(facts):
    s = facts["steeredUndo"]
    assert s["steers"] == 1 and s["runs"] == ["问题1", "问题2", "新问题三", "补充一句"]
    assert s["under"] == ["新问题三"] and s["replaced"] == 1


def test_an_edit_that_waits_shows_the_cut_conversation_with_undo(facts):
    q = facts["editQueued"]
    assert q["waiting"] == {"other": "ATT2", "sent": True, "queued": 1, "runs": ["问题1"], "strip": ["已替换", "撤销"],
                            "state": "排队中，前面还有 1 篇"}
    assert q["queued"] == 0 and q["same"] is True and q["runs"] == ["问题1", "问题2", "问题3"], "Undo takes the edit out of the queue"
    assert q["replaced"] == 0 and q["other"] == "ATT2" and q["calls"] == 1


def test_the_box_keeps_its_words_while_the_paper_runs(facts):
    b = facts["busyBox"]
    assert b["busy"] == {"busy": True, "disabled": True}, "✓ is off while the paper runs"
    assert b["cls"] == "scholium-entry prompt scholium-edit" and b["value"] == "改过的问题二"
    assert b["calls"] == 1 and b["same"] is True


def test_a_turn_is_the_questions_only_with_its_own_words(facts):
    t = facts["turnOf"]
    assert t["steered"] is True, "words steered into the turn follow the question's"
    assert t["longer"] is False and t["refused"] is False and t["same"] is True and t["calls"] == 0, "问题22 is not 问题2"


def test_a_cut_that_fails_keeps_the_title(facts):
    assert facts["cutFails"] == {"sent": False, "title": "问题1", "saved": "问题1", "same": True, "replaced": 0, "calls": 0}


def test_editing_the_first_question_starts_a_new_session(facts):
    f = facts["editFirst"]
    assert f["auto"] == {"resume": False, "title": "第一问改了", "turns": ["第一问改了"], "marker": False}
    assert f["renamed"] == {"resume": False, "title": "我的名字", "turns": ["第一问改了"], "marker": False}


def test_an_edit_without_a_point_starts_a_new_session_with_the_conversation(facts):
    c = facts["editCompacted"]
    assert c["sent"] is True and c["marked"] is True, "the cut leaves a marker without a point"
    assert c["resume"] is False and c["at"] is False and c["history"] is True
    assert c["turns"] == [["问题1", "回答1"], ["新问题二", "新回答"]] and c["session"] == "S4"


def test_undo_brings_the_conversation_back(facts):
    u = facts["undo"]
    assert u["during"] == {"running": True, "view": "scholium-view chat busy"}
    assert u["kills"] >= 1 and u["same"] is True and u["turns"] == ["问题1", "问题2", "问题3"] and u["runs"] == 3
    assert u["box"] == "" and u["cancelledNotice"] is False and u["state"] is True
    assert u["replaced"] == 0 and u["job"] is False


def test_undo_with_codex_archives_the_fork(facts):
    u = facts["undoCodex"]
    assert u["same"] is True and "F1" in u["archive"]


def test_only_the_users_own_questions_can_be_edited_and_not_while_the_paper_runs(facts):
    n = facts["notEditable"]
    assert n["edits"][:2] == [True, True] and n["edits"][2] is False, "the steered words have no ✎"
    assert n["boxValue"] == "问题2", "the box has the question's own words, not the steered ones"
    assert n["view"] == "scholium-view chat busy" and n["refused"] is False


def test_the_edit_has_its_styles():
    rules = css_rules()
    assert "opacity: 0" in rules[".scholium-entry.prompt .edit-prompt"]
    assert any("opacity: 1" in body for sel, body in rules.items() if ".scholium-run:hover .edit-prompt" in sel)
    assert "display: none" in rules[".scholium-view.busy .edit-prompt"]
    assert "resize: vertical" in rules[".scholium-edit-input"]
    # the box is a bubble too: its width outranks the bubble's fit-content
    assert "width: 88%" in rules[".scholium-entry.prompt.scholium-edit"] and "box-sizing: border-box" in rules[".scholium-edit-input"]
    assert "margin-bottom: 20px" in rules[".scholium-entry.prompt.editable"], "room under the bubble for ✎ (22px, 2px below)"
    assert not any(":has(" in sel for sel in rules)


def test_no_error_line_when_a_new_session_took_over(facts):
    r = facts["refusedNoError"]
    for name in ("rewindErrors", "rewindText", "goneText"):
        assert r[name]["gone"] == [True], name
        assert r[name]["live"] == [] and r[name]["reread"] == [], name
        assert not any(r[name]["turnEnded"]), name
    stopped = r["stopped"]
    assert stopped["gone"] == [False] and len(stopped["reread"]) == 1, "a continuation keeps its error"


def test_a_second_edit_of_a_question_leaves_one_marker(facts):
    e = facts["editTwice"]
    assert e["markers"] == 1 and e["before"] == 1, e
    assert e["prompts"] == ["问题1", "再改问题二"] and e["calls"] == 2


def test_undo_of_an_edit_sends_no_notification_while_zotero_is_unfocused(facts):
    u = facts["undoUnfocused"]
    assert u["same"] is True and u["job"] is False
    assert u["after"] == u["before"]


def test_an_edit_whose_send_throws_is_undone(facts):
    assert facts["sendThrows"] == {"sent": False, "same": True, "replaced": 0}


def test_an_old_run_line_without_words_goes_with_the_cut(facts):
    o = facts["oldRunLine"]
    assert o["starts"] == [0, o["first"]]
    assert o["kept"] is True and o["runs"] == 1 and o["last"] == "rewind"
