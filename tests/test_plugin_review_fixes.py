"""A past question edited with Zotero's local API off, a stopped plugin starting nothing, an annotation that did not start
giving its wishes back, what a run says this computer lacks, the steps of the skill's commands, Codex's effort levels, Ask
Scholium outside My Library, the trash line of one note, the notes Annotate again moves to the trash, the reading note
written with the annotations, a compaction in an annotation, a queued message's passage, Retry, the profile read again, the
box after a send, a title renamed when its list closes, a hidden list scrolled once shown, and a reader's own section."""
import json
import subprocess

import pytest

from plugin_harness import BOOTSTRAP, NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
const ok = (text, session = 'S1') => [init, said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: session })];
const hold = [init, 'WAIT'];
const ending = text => [said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1', num_turns: 3 })];
// a turn of a Claude Code conversation as the plugin logs it
const claudeTurn = (n, uuid, session = 'S1') => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at: 1000 + n })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session })
  + L({ type: 'assistant', uuid: uuid + '-0', session_id: session, message: { content: [{ type: 'text', text: '想一想' }] } })
  + L({ type: 'assistant', uuid, session_id: session, message: { content: [{ type: 'text', text: '回答' + n }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: session })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
const CLAUDE3 = claudeTurn(1, 'u1') + claudeTurn(2, 'u2') + claudeTurn(3, 'u3');
const CLAUDE_CONV = '/data/tmp/scholium/ATT1/conversations/claude-20261001-120000.jsonl';
const OTHER_CONV = '/data/tmp/scholium/ATT1/conversations/claude-20261002-120000.jsonl';
const INDEX = '/data/tmp/scholium/ATT1/conversations/index.json';
const EXTRACT = 'python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json';
const PASSAGE = 'A passage worth asking about.';
// the card of a paper's last annotation on its tab
const card = p => {
  const c = p.pane().annot.list.children.at(-1).children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card'));
  return c ? { cls: c.className, title: c.children[0].textContent } : null;
};
const texts = list => list.children.map(textOf);
// until the paper's run has its process and its words
const running = async h => { for (let i = 0; i < 3000 && !(h.runner.current && h.log.stdin.length >= 1); i++) await tick(); };
const inReader = tabID => sel => (sel === 'item-details' ? { tabID } : null);
const READERS = { TAB1: { itemID: 'ATT1' }, TAB3: { itemID: 'ATT3' } };
const facts = {};
// each scenario's facts, or where it threw
const scenario = async (name, fn) => {
  try { facts[name] = await fn(); }
  catch (e) { facts[name] = { threw: String(e && e.stack || e).split('\n').slice(0, 3).join(' | ') }; }
};
(async () => {
  // a past question edited while the local API is off: asked before anything else; declined, the log stays as it was
  for (const [name, confirm] of [['editApiDeclined', false], ['editApiAccepted', true]]) {
    await scenario(name, async () => {
      const h = harness({ prefs: { 'httpServer.localAPI.enabled': false }, confirm, logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [ok('新回答', 'S2')] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(60);
      const view = h.runner.viewOf(p.pane(), 'chat');
      const sent = await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
      await settle(300);
      const r = { sent, confirms: h.log.confirms.length, cut: CLAUDE_CONV in h.log.mtimes, same: h.log.writes[CLAUDE_CONV] === CLAUDE3,
                  runs: h.log.calls.length, replaced: h.runner.replaced.size, on: h.store.get('httpServer.localAPI.enabled') };
      h.runner.stop();
      return r;
    });
  }
  // the Undo seconds of an edit start once its message went
  await scenario('editUndoTimer', async () => {
    const h = harness({ logs: { [CLAUDE_CONV]: CLAUDE3 }, scripts: [ok('新回答', 'S2')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(60);
    const view = h.runner.viewOf(p.pane(), 'chat');
    const id = 'ATT1/claude-20261001-120000';
    const send = h.runner.send;
    let during = null;
    h.runner.send = async function (...a) {
      const r = this.replaced.get(id);
      during = { held: !!r, timer: r && r.timer ? r.timer.ms : null };
      return send.apply(this, a);
    };
    const sent = await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    const r = h.runner.replaced.get(id);
    const after = { sent, timer: r && r.timer ? r.timer.ms : null, undoMs: h.runner.UNDO_MS };
    h.runner.send = send;
    await settle(300);
    h.runner.stop();
    return { during, after };
  });

  // a stopped plugin queues and starts nothing
  await scenario('stoppedRunner', async () => {
    const h = harness({ scripts: [ok('答')] });
    h.runner.start('x');
    h.runner.stop();
    await h.runner.send(h.item1, '这篇讲什么？');
    await h.runner.annotate([h.item2]);
    await settle(300);
    return { queue: h.runner.queue.length, runs: h.log.calls.length, running: !!h.runner.job };
  });
  // a queued message stays in the queue while its conversation is looked up: a stop then (an update) hands it over
  // and runs nothing; one taken out of the queue meanwhile does not run, and Undo brings it back
  for (const how of ['stop', 'remove']) {
    await scenario(how === 'stop' ? 'stopDuringPlace' : 'removedDuringPlace', async () => {
      const first = [init, 'HOLD', said('答一'), ev({ type: 'result', subtype: 'success', is_error: false, result: '答一', session_id: 'S1' })];
      const h = harness({ scripts: [first, ok('答二')] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      pane.input.type('问题一'); pane.send.click();
      for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
      pane.input.type('追问二'); pane.send.click(); await settle(20);
      const queued = h.runner.queue.filter(j => j.qid).map(j => j.say);
      const place = h.runner.place;
      let during = null, qid = null;
      h.runner.place = async function (job) {
        if (job.qid && !during) {
          during = { inQueue: this.queue.includes(job) };
          qid = job.qid;
          if (how === 'stop') this.stop(true); else this.removeQueued(pane, job.qid);
        }
        return place.apply(this, arguments);
      };
      h.log.release(); await settle(600);
      const r = { queued, during, runs: h.log.calls.length, queue: h.runner.queue.length };
      if (how === 'stop') {
        const carried = JSON.parse(h.store.get('extensions.scholium.carryOver') || '{"jobs":[]}');
        Object.assign(r, { carried: carried.jobs.map(j => [j.say, !!j.qid]), running: !!h.runner.job });
      } else {
        r.removed = [...h.runner.removedQueued.values()].map(x => x.job.say);
        h.runner.undoRemoveQueued(qid); await settle(600);
        r.afterUndo = { runs: h.log.calls.length, asked: h.log.stdin.some(s => s.includes('追问二')) };
        h.runner.stop();
      }
      return r;
    });
  }

  // an annotation that did not start: its wishes back in the Annotations tab's box, the line that ended it still shown
  await scenario('annotateNoProgram', async () => {
    const h = harness({ claudeExists: false });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click();
    pane.input.type('只标核心句');
    pane.annotGo.click(); await settle(400);
    return { box: pane.input.value, tab: pane.tab, shown: texts(pane.annot.list).join(' | '), missing: h.runner.text('noClaude'), runs: h.log.calls.length };
  });
  await scenario('annotateStoppedBeforeStart', async () => {
    const h = harness({ holdDirs: true });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click();
    pane.input.type('只标核心句');
    pane.annotGo.click();
    for (let i = 0; i < 3000 && !h.log.releaseDir; i++) await tick();
    h.runner.cancel();                                  // ■
    h.log.releaseDir(); await settle(400);
    return { box: pane.input.value, shown: texts(pane.annot.list).join(' | '), cancelled: h.runner.text('cancelled'), runs: h.log.calls.length };
  });
  // ■ once the annotation's new session was made: the session goes again
  await scenario('annotateStoppedAfterSession', async () => {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const newConv = h.runner.newConv;
    let made = null;
    h.runner.newConv = async function (...a) { made = await newConv.apply(this, a); this.cancel(); return made; };
    pane.tabAnnotate.click();
    pane.input.type('只标核心句');
    pane.annotGo.click(); await settle(500);
    const index = JSON.parse(h.log.writes[INDEX] || '{}');
    return { made: !!made, latest: await h.runner.annotationConv('ATT1', 'claude'), annotation: index.annotation || null,
             titled: Object.keys(index.titles || {}).includes(made), logs: convs(h).length, box: pane.input.value, runs: h.log.calls.length,
             showsGone: !!made && pane.annot.shownConv === made, shown: texts(pane.annot.list).join(' | '), cancelled: h.runner.text('cancelled') };
  });

  // what a run says this computer lacks: shell commands only; a later command of the skill's script clears it
  await scenario('missingAfter', async () => {
    const h = harness({});
    const m = (c, o, b = null) => h.runner.missingAfter(c, o, b);
    const source = '    raise SystemExit("PyMuPDF is not installed; run: pip install -U pymupdf")';
    return {
      read: m('', source, null), readKeeps: m('', 'print(1)', 'pymupdfMissing'), noCommand: m(undefined, source, 'noPython'),
      shell: m(EXTRACT, 'PyMuPDF is not installed; run: pip install -U pymupdf', null),
      blocks: m(EXTRACT, [{ type: 'text', text: 'PyMuPDF is not installed' }], null),
      scriptFails: m('python C:/skills/scholium.py --config c.json', 'Exit code 2\nstyle_warnings: 1', 'pymupdfMissing'),
      consoleFails: m('scholium --config c.json --apply', 'Exit code 1\nerror: config not found', 'noPython'),
      pipKeeps: m('pip install -U pymupdf', 'error: externally-managed-environment', 'pymupdfMissing'),
      shellRead: m('Get-Content C:/skills/scripts/scholium.py', 'PYMUPDF_MISSING = "PyMuPDF is not installed; run: pip install -U pymupdf"', null),
    };
  });
  const annotRuns = {
    readSource: [tool('Read', { file_path: 'C:/skills/zotero-scholium/scripts/scholium.py' }, 't1'),
                 answer('    raise SystemExit("PyMuPDF is not installed; run: pip install -U pymupdf")', false, 't1')],
    consoleLater: [tool('Bash', { command: EXTRACT }, 't1'), answer('PyMuPDF is not installed; run: pip install -U pymupdf', true, 't1'),
                   tool('Bash', { command: 'scholium --config c.json' }, 't2'), answer('Exit code 2\nerror: no annotations', true, 't2')],
  };
  for (const [name, steps] of Object.entries(annotRuns)) {
    await scenario('missing_' + name, async () => {
      const h = harness({ script: [init, ...steps, ...ending('停在这里。')] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      p.annotate(); await settle(500);
      const r = card(p);
      h.runner.stop();
      return r;
    });
  }
  for (const later of [false, true]) {
    await scenario(later ? 'missing_codexLater' : 'missing_codex', async () => {
      const failed = { exitCode: 1, status: 'failed', output: 'PyMuPDF is not installed; run: pip install -U pymupdf' };
      const dry = 'python C:/skills/scholium.py --config c.json';
      const turn = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }), shell('c1', EXTRACT), shell('c1', EXTRACT, failed)]
        .concat(later ? [shell('c2', dry), shell('c2', dry, { exitCode: 2, status: 'failed', output: 'style_warnings: 1' })] : [],
                [coItem('completed', { type: 'agentMessage', id: 'a1', text: '停在这里。' }), turnDone({ status: 'completed' })]);
      const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [turn] } });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      p.annotate(); await settle(700);
      const r = card(p);
      h.runner.stop();
      return r;
    });
  }

  // the step a command of the skill's script is
  await scenario('commandStep', async () => {
    const h = harness({});
    const s = c => h.runner.commandStep(c);
    return {
      extractConfig: s('python C:/skills/scholium.py extract --config D:/Zotero/tmp/scholium/ATT1/paper.json'),
      extractQuoted: s('python "C:/skills/scholium.py" extract --config paper.json'),
      extract: s(EXTRACT),
      list: s('python C:/skills/scholium.py --config c.json --list'),
      listFull: s('python C:/skills/scholium.py --config c.json --list --full'),
      apply: s('python C:/skills/scholium.py --config c.json --apply'),
      dryRun: s('python C:/skills/scholium.py --config c.json'),
      console: s('scholium --config c.json'),
      other: s('pip install -U pymupdf'),
    };
  });

  // Codex's effort levels when a model's own are unknown
  await scenario('codexEfforts', async () => {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { fail: 'model/list', failMessage: 'no list' } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(200);
    const options = h.runner.codexModelOptions([{ model: 'gpt-x', displayName: 'X' }], '');
    return { unknown: p.view().efforts, listed: options.map(o => [o.value, o.efforts]), claude: h.runner.modelChoices('claude')[0].efforts };
  });
  // the model a new thread named when none is chosen, which the list does not have
  await scenario('codexNamedDefault', async () => {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' },
                        codex: { scripts: [CODEX_FOLLOW], answers: { 'thread/start': () => ({ result: { thread: { id: 'T1' }, model: 'gpt-custom' } }) } } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(200);
    const before = p.view().efforts;
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(800);
    const r = { before, after: p.view().efforts, label: p.view().modelLabels[0], named: h.store.get('extensions.scholium.codexDefault') };
    h.runner.stop();
    return r;
  });

  // Ask Scholium: a PDF of My Library in a reader tab of the main window only
  await scenario('askMenu', async () => {
    const h = harness({});
    h.runner.start('x');
    const n = () => h.selection(PASSAGE, 0, '1').length;
    const plain = n();
    h.att1.libraryID = 2;
    const group = n();
    h.att1.libraryID = 1;
    h.paneWin.location = { href: 'chrome://zotero/content/reader.xhtml' };
    const window = n();
    h.paneWin.location = { href: 'chrome://zotero/content/reader.xhtml?id=1' };
    const windowQuery = n();
    h.paneWin.location = { href: 'chrome://zotero/content/zoteroPane.xhtml' };
    const main = n();
    return { plain, group, window, windowQuery, main };
  });

  // the deletion's question in English with one reading note
  await scenario('deleteOneNote', async () => {
    const h = harness({ notes: [['zotero-scholium']], locale: 'en-US', confirm: false });
    h.runner.start('x');
    await h.runner.removeAnnotations([h.item1]);
    return { asked: h.log.confirms.slice(), both: h.runner.text('deleteConfirm', 3, 1), two: h.runner.text('deleteConfirm', 0, 2) };
  });

  // Annotate again while another PDF of the paper runs or waits: its reading notes stay, and the question says so
  for (const how of ['running', 'queued']) {
    await scenario('redoOtherPdf_' + how, async () => {
      const h = harness({ existing: [['zotero-scholium']], notes: [['zotero-scholium']], secondPdf: true, gateFirst: true });
      h.runner.start('x');
      if (how === 'queued') { await h.runner.annotate([h.item2]); await settle(100); }
      await h.runner.annotate([h.zotero.Items.get('ATT3')]); await settle(100);
      const before = { running: h.runner.job && h.runner.job.key, queue: h.runner.queue.map(j => j.att.key) };
      const queued = await h.runner.annotate([h.item1]); await settle(50);
      const r = { before, queued, asked: h.log.confirms.slice(), erased: h.log.erased.slice(), trashed: h.log.trashed.slice(), notesLeft: h.item1.getNotes() };
      h.runner.stop();
      return r;
    });
  }
  await scenario('redoInPlaceOtherPdf', async () => {
    const h = harness({ existing: [['zotero-scholium']], notes: [['zotero-scholium']], secondPdf: true, gateFirst: true });
    h.runner.start('x');
    await h.runner.annotate([h.zotero.Items.get('ATT3')]); await settle(100);
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    pane.annotGo.click(); await settle(20);
    const asked = pane.confirmRow.hidden ? null : pane.confirmRow.children[0].textContent;
    if (!pane.confirmRow.hidden) { pane.confirmRow.children[2].click(); await settle(100); }   // 替换
    const r = { keys: pane.keys, asked, erased: h.log.erased.slice(), trashed: h.log.trashed.slice() };
    h.runner.stop();
    return r;
  });
  // the Annotations tab's introduction of a paper whose annotation waits, drawn again once its annotations went
  await scenario('introRedrawn', async () => {
    const h = harness({ existing: [['zotero-scholium']], gateFirst: true });
    h.runner.start('x');
    await h.runner.annotate([h.item2]); await settle(100);
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(20);
    const title = () => { const n = pane.annot.list.children[0]; return n && n.className === 'scholium-annot-intro' ? n.children[0].textContent : null; };
    const before = title();
    const queued = await h.runner.annotate([h.item1]); await settle(100);
    const r = { before, queued, after: title(), erased: h.log.erased.slice(), waiting: h.runner.queue.map(j => j.att.key) };
    h.runner.stop();
    return r;
  });

  // an annotation in which Claude Code compacted by itself: the compaction's line, drawn as it ends and from its log
  await scenario('annotationCompacted', async () => {
    const script = [init, tool('Bash', { command: EXTRACT }, 't1'), answer('412 sentences -> s.json', false, 't1'),
      ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }),
      ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'auto', pre_tokens: 900000, post_tokens: 100000 } }),
      tool('Bash', { command: 'python C:/skills/scholium.py --config c.json --apply' }, 't2'), answer('{"applied": true}', false, 't2'),
      LAST, RESULT];
    const h = harness({ script });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(600);
    const parts = p.pane().annot.list.children.at(-1).children.map(c => [c.className, textOf(c)]);
    const later = harness({ logs: ours(h) });
    later.runner.start('x');
    const lp = await later.pane(later.item1); await settle(60);
    lp.pane().tabAnnotate.click(); await settle(60);
    const again = lp.pane().annot.list.children.at(-1).children.map(c => [c.className, textOf(c)]);
    h.runner.stop();
    return { parts, again };
  });

  // Edit on a queued message: its words and its passage back above the box
  await scenario('editQueuedQuote', async () => {
    const h = harness({ scripts: [hold, ok('答二')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    h.selection(PASSAGE, 3, '4')[0].click(); await settle(20);
    pane.input.type('这段什么意思？'); pane.send.click(); await settle(30);
    const job = h.runner.queue.find(j => j.qid);
    const queued = { say: job.say, quote: !!job.quote, box: pane.input.value, paneQuote: pane.quote };
    h.runner.editQueued(pane, job.qid); await settle(10);
    const r = { queued, box: pane.input.value, quote: pane.quote ? pane.quote.text : null, shown: !pane.quoteBox.hidden,
                left: h.runner.queue.filter(j => j.qid).length };
    h.runner.stop();
    return r;
  });

  // Retry goes to the conversation shown when it was pressed; another one opened meanwhile takes nothing
  for (const switched of [false, true]) {
    await scenario(switched ? 'retrySwitched' : 'retrySame', async () => {
      const A = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题A', at: 1001 })
        + L({ type: 'scholium', subtype: 'prompt', text: '问题A', question: true })
        + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'SA' })
        + L({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'boom', session_id: 'SA' })
        + L({ type: 'scholium', subtype: 'time', at: 2001 });
      const B = claudeTurn(1, 'u1', 'SB');
      const h = harness({ logs: { [CLAUDE_CONV]: A, [OTHER_CONV]: B,
                                  [INDEX]: JSON.stringify({ chat: 'claude-20261001-120000', current: {}, titles: {}, annotation: {} }) },
                          scripts: [ok('好了', 'SA')] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(60);
      const pane = p.pane();
      const view = h.runner.viewOf(pane, 'chat');
      const pressed = view.shownConv;
      const readLog = h.runner.readLog;
      let release = null, gated = false;
      h.runner.readLog = function (...a) {
        const r = readLog.apply(this, a);
        if (gated) return r;
        gated = true;
        return new Promise(res => { release = () => res(r); });
      };
      const retry = h.runner.retryFromView(view);
      if (switched) await h.runner.openConv(pane, { key: 'ATT1', id: 'claude-20261002-120000' });
      await settle(20);
      const shown = view.shownConv;
      release(); await retry; await settle(400);
      h.runner.readLog = readLog;
      return { pressed, shown, runs: h.log.calls.length, grewA: h.log.writes[CLAUDE_CONV] !== A, grewB: h.log.writes[OTHER_CONV] !== B,
               asked: h.log.stdin.map(s => (s.includes('问题A') ? '问题A' : null)) };
    });
  }

  // the profile that could not be read, read again unchanged: the error goes
  await scenario('profileReadAgain', async () => {
    const unreadable = [];
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, unreadable });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const [, , foot] = h.sheet().children[0].children;
    const [status, , , save] = foot.children;
    const view = () => ({ status: status.textContent, error: status.className.includes('error'), readFailed: !!h.runner.editor.readFailed });
    const opened = view();
    unreadable.push(PROFILE_PATH);
    h.paneWin.dispatch('focus'); await settle(20);
    const failed = view();
    unreadable.length = 0;
    h.paneWin.dispatch('focus'); await settle(20);
    const back = view();
    const input = h.sheet().children[0].children[1].children[0];
    input.type(input.value + '- 新规则\n');
    save.click(); await settle(20);
    return { opened, failed, back, saved: (h.log.writes[PROFILE_PATH] || '').endsWith('- 新规则\n') };
  });

  // the box after a send: words typed meanwhile stay; the same words sent twice go once; the clear-queue question sends
  // what the box holds when it is answered
  await scenario('typedMeanwhile', async () => {
    const h = harness({ scripts: [ok('答一')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click();
    pane.input.type('另一个问题'); await settle(300);
    return { box: pane.input.value, asked: h.log.stdin.some(s => s.includes('问题一')) };
  });
  await scenario('tabSwitchedMeanwhile', async () => {
    const h = harness({ scripts: [ok('答一')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); pane.input.type('标注的愿望'); pane.tabChat.click();
    pane.input.type('问题一'); pane.send.click();
    pane.tabAnnotate.click(); await settle(300);
    const annotate = pane.input.value;
    pane.tabChat.click(); await settle(10);
    return { annotate, chat: pane.input.value, asked: h.log.stdin.some(s => s.includes('问题一')) };
  });
  await scenario('sentTwice', async () => {
    const h = harness({ scripts: [hold, ok('答二'), ok('答三')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await running(h);
    pane.input.type('追问二'); pane.send.click(); pane.send.click(); await settle(50);
    const r = { queued: h.runner.queue.filter(j => j.qid).map(j => j.say), box: pane.input.value, sending: pane.sending || null };
    h.runner.stop();
    return r;
  });
  for (const how of ['send', 'clear']) {
    await scenario(how === 'send' ? 'heldSendChanged' : 'heldClearEmptied', async () => {
      const h = harness({ scripts: [hold, ok('答二'), ok('答三')] });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      pane.input.type('问题一'); pane.send.click(); await running(h);
      pane.input.type('追问二'); pane.send.click(); await settle(20);
      pane.send.click(); await settle(300);                                  // ■: the queue is held
      pane.input.type('新消息'); pane.send.click(); await settle(20);
      const ask = pane.confirmRow.children.map(c => c.textContent);
      pane.input.type(how === 'send' ? '改过的新消息' : '');
      pane.confirmRow.children[how === 'send' ? 2 : 1].click(); await settle(800);
      const r = { ask, asked: h.log.stdin.map(s => ['改过的新消息', '新消息', '追问二', '问题一'].find(w => s.includes(w)) || null),
                  box: pane.input.value, queue: h.runner.queue.map(j => j.say) };
      h.runner.stop();
      return r;
    });
  }

  // a title being renamed is kept when its list closes by a click outside
  await scenario('renameOnClose', async () => {
    const h = harness({ logs: { [CLAUDE_CONV]: claudeTurn(1, 'u1') } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    pane.historyButton.click(); await settle(100);
    const row = pane.popover.node.children.find(c => /scholium-history-row/.test(c.className));
    row.children[1].click();                                                  // ✎
    const input = row.children[0];
    input.value = '我的标题';
    h.paneDoc.dispatch('mousedown', { target: new h.El('div') }); await settle(60);
    const index = JSON.parse(h.log.writes[INDEX] || '{}');
    return { closed: !pane.popover, renaming: !!pane.renaming, title: (index.titles || {})['claude-20261001-120000'] || null };
  });

  // a list drawn while its tab is hidden goes to its end once its tab is shown
  await scenario('hiddenListScrolled', async () => {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    p.annotate(); await settle(500);                     // a session on the Annotations tab
    pane.tabChat.click(); await settle(10);
    const list = pane.annot.list;
    // as a hidden element: no height, and no scrolling
    Object.defineProperty(list, 'clientHeight', { get: () => (pane.annotView.hidden ? 0 : 100), configurable: true });
    let top = 0;
    Object.defineProperty(list, 'scrollTop', { get: () => top, set: v => { top = list.clientHeight ? v : 0; }, configurable: true });
    await h.runner.showAnnotation(pane);
    const hidden = { top: list.scrollTop, pending: !!pane.annot.scrollPending, end: list.scrollHeight };
    pane.tabAnnotate.click(); await settle(10);
    return { hidden, shown: { top: list.scrollTop, end: list.scrollHeight, pending: !!pane.annot.scrollPending } };
  });

  // a reader tab's section shows the reader's own PDF; a passage waits half a minute, for its own reader's section
  await scenario('readerOwnPdf', async () => {
    const h = harness({ secondPdf: true });
    h.zotero.Reader.getByTabID = id => READERS[id] || null;
    h.runner.start('x');
    const lib = await h.pane(h.item1); await settle(40);
    const rd = await h.pane(h.item1, { closest: inReader('TAB3') }); await settle(40);
    return { library: lib.pane().keys, reader: rd.pane().keys };
  });
  await scenario('pendingQuoteAge', async () => {
    const out = {};
    for (const [name, age] of [['fresh', 0], ['stale', 31000]]) {
      const h = harness({});
      h.runner.start('x');
      h.selection(PASSAGE, 3, '4')[0].click(); await settle(20);
      const waiting = h.runner.pendingQuotes.get('ATT1');
      if (waiting) waiting.at -= age;
      const p = await h.pane(h.item1); await settle(40);
      out[name] = { quote: p.pane().quote ? p.pane().quote.text : null, left: h.runner.pendingQuotes.size };
    }
    return out;
  });
  await scenario('pendingQuoteReader', async () => {
    const h = harness({ secondPdf: true });
    h.zotero.Reader.getByTabID = id => READERS[id] || null;
    h.runner.start('x');
    h.selection(PASSAGE, 3, '4', 'TAB1')[0].click(); await settle(20);
    const other = await h.pane(h.item1, { closest: inReader('TAB3') }); await settle(40);
    const otherTook = other.pane().quote ? other.pane().quote.text : null;
    const waiting = h.runner.pendingQuotes.has('ATT1');
    const own = await h.pane(h.item1, { closest: inReader('TAB1') }); await settle(40);
    return { otherTook, waiting, ownTook: own.pane().quote ? own.pane().quote.text : null, keys: [other.pane().keys, own.pane().keys] };
  });

  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


# the /scholium/apply endpoint in a Zotero whose transaction keeps what was saved inside it only when it ends without an error
RUN_APPLY = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const committed = [];
let pending = null;
const parent = { id: 2, key: 'PARENT01', getNotes: () => [] };
const attachment = { id: 1, key: 'ATTACH01', parentID: 2, getAnnotations: () => [] };
class Item {
  constructor(type) { this.type = type; }
  setNote(html) { this.html = html; }
  setTags(tags) { this.tags = tags; }
  async save() {
    if (!pending) throw Error('save() outside a transaction');
    if (this.type === 'annotation' && this.annotationText === input.failOn) throw Error('simulated save failure');
    this.key = 'K' + (committed.length + pending.length + 1);
    pending.push(this);
  }
  async saveTx() {
    if (pending) throw Error('saveTx() inside a transaction');
    this.key = 'K' + (committed.length + 1);
    committed.push(this);
  }
}
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1 },
  Items: { getByLibraryAndKey: (lib, key) => (key === 'ATTACH01' ? attachment : key === 'PARENT01' ? parent : null),
           get: ids => (Array.isArray(ids) ? [] : ids === 2 ? parent : null), trashTx: async () => {} },
  DB: { executeTransaction: async callback => { pending = []; try { await callback(); committed.push(...pending); } finally { pending = null; } } },
  Item,
} });
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.ScholiumEndpoints.apply(input.data)
  .then(result => ({ result }), error => ({ error: String(error && error.message || error) }))
  .then(out => process.stdout.write(JSON.stringify(Object.assign(out, {
    committed: committed.map(i => ({ type: i.type, color: i.annotationColor || null, note: i.html || null, key: i.key })) }))));
"""
NOTE_HTML = "<h1>Paper</h1><p>The reading note.</p>"


def highlight(text, color="#ffd400"):
    return {"type": "highlight", "text": text, "comment": "译文", "color": color, "pageLabel": "1", "sortIndex": "00000|000000|00000",
            "position": {"pageIndex": 0, "rects": [[1, 1, 5, 5]]}}


def run_apply(annotations, fail_on=None, bootstrap=BOOTSTRAP):
    data = {"attachmentKey": "ATTACH01", "itemKey": "PARENT01", "tag": "zotero-scholium", "annotations": annotations,
            "note": {"html": NOTE_HTML}}
    completed = subprocess.run([NODE, "-e", RUN_APPLY, str(bootstrap)], input=json.dumps({"data": data, "failOn": fail_on}),
                               text=True, encoding="utf-8", capture_output=True, check=True, timeout=15)
    return json.loads(completed.stdout)


def test_an_edit_with_the_local_api_off_declined_leaves_the_conversation_as_it_was(facts):
    assert facts["editApiDeclined"] == {"sent": False, "confirms": 1, "cut": False, "same": True, "runs": 0, "replaced": 0, "on": False}


def test_an_edit_with_the_local_api_turned_on_is_asked_once_and_goes(facts):
    a = facts["editApiAccepted"]
    assert a["sent"] is True and a["confirms"] == 1 and a["on"] is True
    assert a["cut"] is True and a["runs"] == 1 and a["replaced"] == 1


def test_the_undo_seconds_of_an_edit_start_once_its_message_went(facts):
    t = facts["editUndoTimer"]
    assert t["during"] == {"held": True, "timer": None}, "no timer while the message is on its way"
    assert t["after"] == {"sent": True, "timer": 6000, "undoMs": 6000}


def test_a_stopped_plugin_queues_and_runs_nothing(facts):
    assert facts["stoppedRunner"] == {"queue": 0, "runs": 0, "running": False}


def test_a_stop_while_a_queued_message_takes_its_conversation_hands_it_over_and_runs_nothing(facts):
    s = facts["stopDuringPlace"]
    assert s["queued"] == ["追问二"] and s["during"] == {"inQueue": True}
    assert s["runs"] == 1 and s["running"] is False, "only the first question ran"
    assert s["carried"] == [["追问二", True]], "the update's copy gets the message, as a queued one"


def test_a_queued_message_taken_out_while_it_takes_its_conversation_does_not_run(facts):
    r = facts["removedDuringPlace"]
    assert r["during"] == {"inQueue": True}
    assert r["runs"] == 1 and r["queue"] == 0 and r["removed"] == ["追问二"]
    assert r["afterUndo"] == {"runs": 2, "asked": True}, "Undo brings it back, and it runs"


def test_an_annotation_whose_agent_is_not_found_gives_its_wishes_back_and_keeps_its_line(facts):
    a = facts["annotateNoProgram"]
    assert a["box"] == "只标核心句" and a["tab"] == "annotate" and a["runs"] == 0
    assert a["missing"] in a["shown"]


def test_an_annotation_stopped_before_it_started_gives_its_wishes_back_and_keeps_its_line(facts):
    a = facts["annotateStoppedBeforeStart"]
    assert a["box"] == "只标核心句" and a["runs"] == 0
    assert a["cancelled"] in a["shown"]


def test_an_annotation_stopped_once_its_session_was_made_leaves_no_session(facts):
    a = facts["annotateStoppedAfterSession"]
    assert a["made"] is True and a["runs"] == 0
    assert a["latest"] is None and a["annotation"] == {} and a["titled"] is False and a["logs"] == 0
    assert a["shown"] and a["cancelled"] not in a["shown"], "the tab is drawn again as before the annotation"
    assert a["showsGone"] is False, "the tab does not show the session that went"
    assert a["box"] == "只标核心句"


def test_only_shell_output_says_what_is_missing_and_the_skills_script_clears_it(facts):
    m = facts["missingAfter"]
    assert m["read"] is None and m["readKeeps"] == "pymupdfMissing" and m["noCommand"] == "noPython", "a file read leaves it as it was"
    assert m["shellRead"] is None, "the script's source read through the shell names nothing missing"
    assert m["shell"] == "pymupdfMissing" and m["blocks"] == "pymupdfMissing"
    assert m["scriptFails"] is None and m["consoleFails"] is None, "whatever the script's exit code"
    assert m["pipKeeps"] == "pymupdfMissing"


def test_a_run_that_read_the_scripts_source_names_nothing_missing(facts):
    assert facts["missing_readSource"] == {"cls": "scholium-card none", "title": "没有写入批注"}


def test_the_scholium_command_running_afterwards_clears_it_though_it_failed(facts):
    assert facts["missing_consoleLater"] == {"cls": "scholium-card none", "title": "没有写入批注"}
    assert facts["missing_codex"] == {"cls": "scholium-card none",
                                      "title": "没有写入批注：缺少 PyMuPDF，安装 uv（在终端运行 powershell -ExecutionPolicy ByPass -c "
                                               '"irm https://astral.sh/uv/install.ps1 | iex"）或运行 pip install -U pymupdf 后再试。'}
    assert facts["missing_codexLater"] == {"cls": "scholium-card none", "title": "没有写入批注"}


def test_the_step_of_each_command_of_the_skills_script(facts):
    assert facts["commandStep"] == {"extractConfig": "extract", "extractQuoted": "extract", "extract": "extract", "list": None,
                                    "listFull": None, "apply": "applying", "dryRun": "dryRun", "console": "dryRun", "other": None}


CODEX_EFFORTS = ["low", "medium", "high", "xhigh"]


def test_codex_without_a_model_list_offers_its_own_levels(facts):
    c = facts["codexEfforts"]
    assert c["unknown"] == CODEX_EFFORTS
    assert c["listed"] == [["", CODEX_EFFORTS], ["gpt-x", CODEX_EFFORTS]]
    assert c["claude"] == ["low", "medium", "high", "xhigh", "max"]


def test_codex_default_named_by_a_new_thread_outside_the_list_offers_codex_levels(facts):
    c = facts["codexNamedDefault"]
    assert c["named"] == "gpt-custom" and "gpt-custom" in c["label"]
    assert c["before"] == CODEX_EFFORTS and c["after"] == CODEX_EFFORTS


def test_ask_scholium_only_for_my_library_in_the_main_window(facts):
    assert facts["askMenu"] == {"plain": 1, "group": 0, "window": 0, "windowQuery": 0, "main": 1}


def test_the_deletion_question_names_one_note_in_the_singular(facts):
    d = facts["deleteOneNote"]
    assert d["asked"] == ["This deletes 1 reading note of the paper, tagged zotero-scholium. The note goes to the trash, where it can be "
                          "restored. Your own annotations and notes are kept. The deletion syncs. Continue?"]
    assert "the note goes to the trash, where it can be restored." in d["both"]
    assert "The notes go to the trash, where they can be restored." in d["two"]


REDO_ANNOTATIONS_ONLY = "这篇论文已有 1 条 Scholium 批注。重新批注会先删除它们，你自己的批注和笔记不受影响。继续吗？"


@pytest.mark.parametrize("how", ["running", "queued"])
def test_annotate_again_keeps_the_notes_of_a_paper_whose_other_pdf_runs_or_waits(facts, how):
    r = facts["redoOtherPdf_" + how]
    if how == "running":
        assert r["before"] == {"running": "ATT3", "queue": []}
    else:
        assert r["before"] == {"running": "ATT2", "queue": ["ATT3"]}
    assert r["queued"] == 1 and r["asked"] == [REDO_ANNOTATIONS_ONLY]
    assert r["erased"] == ["E0"] and r["trashed"] == [] and r["notesLeft"] == ["N0"]


def test_annotate_again_in_place_counts_the_notes_it_moves(facts):
    r = facts["redoInPlaceOtherPdf"]
    assert r["keys"] == ["ATT1"]
    assert r["erased"] == ["E0"] and r["trashed"] == []
    assert r["asked"] == "重新批注会先删除这篇的 1 条 Scholium 批注（你自己的不动）。", "no notes named that stay"


def test_the_introduction_of_a_waiting_paper_shows_its_annotations_gone(facts):
    r = facts["introRedrawn"]
    assert r["before"] == "这篇已有 1 条 Scholium 批注"
    assert r["queued"] == 1 and r["erased"] == ["E0"] and r["waiting"] == ["ATT1"]
    assert r["after"] == "还没有批注这篇"


def test_a_failed_annotation_leaves_no_new_reading_note():
    out = run_apply([highlight("first"), highlight("boom")], fail_on="boom")
    assert out == {"error": "simulated save failure", "committed": []}


def test_the_note_and_the_annotations_are_written_together_with_lower_case_colours():
    out = run_apply([highlight("first", "#FF6666"), highlight("second", "#2EA8E5")])
    assert [(c["type"], c["color"]) for c in out["committed"]] == [("note", None), ("annotation", "#ff6666"), ("annotation", "#2ea8e5")]
    assert out["committed"][0]["note"] == NOTE_HTML
    r = out["result"]
    assert r["noteCreated"] is True and r["noteKeys"] == [out["committed"][0]["key"]]
    assert r["created"]["highlight"] == 2 and r["createdKeys"] == [c["key"] for c in out["committed"][1:]]


def test_an_annotation_with_a_compaction_draws_its_line(facts):
    c = facts["annotationCompacted"]
    for parts in (c["parts"], c["again"]):
        assert ["scholium-compact", "上下文已自动压缩 · 900k → 100k"] in parts, parts
        assert not any("undefined" in text for _, text in parts), parts


def test_edit_on_a_queued_message_brings_its_passage_back(facts):
    e = facts["editQueuedQuote"]
    assert e["queued"] == {"say": "这段什么意思？", "quote": True, "box": "", "paneQuote": None}
    assert e["box"] == "这段什么意思？" and e["quote"] == "A passage worth asking about." and e["shown"] is True
    assert e["left"] == 0


def test_retry_goes_to_the_conversation_shown_when_it_was_pressed(facts):
    s = facts["retrySame"]
    assert s["pressed"] == s["shown"] == "claude-20261001-120000"
    assert s["runs"] == 1 and s["grewA"] is True and s["grewB"] is False and s["asked"] == ["问题A"]


def test_retry_does_not_go_to_a_conversation_opened_meanwhile(facts):
    s = facts["retrySwitched"]
    assert s["pressed"] == "claude-20261001-120000" and s["shown"] == "claude-20261002-120000"
    assert s["runs"] == 0 and s["grewA"] is False and s["grewB"] is False


def test_the_profile_read_again_after_a_failed_read_drops_the_error(facts):
    p = facts["profileReadAgain"]
    assert p["opened"]["readFailed"] is False and p["opened"]["error"] is False
    assert p["failed"]["readFailed"] is True and p["failed"]["error"] is True
    assert p["back"] == p["opened"]
    assert p["saved"] is True


def test_words_typed_while_a_message_goes_stay_in_the_box(facts):
    assert facts["typedMeanwhile"] == {"box": "另一个问题", "asked": True}


def test_the_box_of_another_tab_keeps_its_words_when_a_message_goes(facts):
    t = facts["tabSwitchedMeanwhile"]
    assert t["asked"] is True and t["annotate"] == "标注的愿望"


def test_the_same_words_sent_twice_while_they_go_are_queued_once(facts):
    s = facts["sentTwice"]
    assert s["queued"] == ["追问二"] and s["box"] == "" and s["sending"] is None


def test_the_clear_queue_question_sends_what_the_box_holds_when_answered(facts):
    s = facts["heldSendChanged"]
    assert s["ask"][1:] == ["清空队列", "发送消息"]
    assert s["asked"][:3] == ["问题一", "改过的新消息", "追问二"] and s["box"] == ""
    c = facts["heldClearEmptied"]
    assert c["asked"] == ["问题一"] and c["queue"] == [], "an emptied box sends nothing; the queue goes"


def test_a_title_being_renamed_is_kept_when_its_list_closes(facts):
    assert facts["renameOnClose"] == {"closed": True, "renaming": False, "title": "我的标题"}


def test_a_list_drawn_hidden_goes_to_its_end_when_its_tab_is_shown(facts):
    s = facts["hiddenListScrolled"]
    assert s["hidden"]["top"] == 0 and s["hidden"]["pending"] is True and s["hidden"]["end"] > 0
    assert s["shown"] == {"top": s["shown"]["end"], "end": s["hidden"]["end"], "pending": False}


def test_a_reader_tabs_section_shows_the_readers_own_pdf(facts):
    assert facts["readerOwnPdf"] == {"library": ["ATT1"], "reader": ["ATT3"]}


def test_a_waiting_passage_is_taken_within_half_a_minute(facts):
    assert facts["pendingQuoteAge"] == {"fresh": {"quote": "A passage worth asking about.", "left": 0},
                                        "stale": {"quote": None, "left": 0}}


def test_a_waiting_passage_goes_to_its_own_readers_section(facts):
    q = facts["pendingQuoteReader"]
    assert q["otherTook"] is None and q["waiting"] is True
    assert q["ownTook"] == "A passage worth asking about." and q["keys"] == [["ATT3"], ["ATT1"]]
