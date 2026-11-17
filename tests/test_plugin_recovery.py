"""Failed restores and log writes keep their recovery state (pure plugin harness)."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const PATH = '/data/tmp/scholium/ATT1/conversations/claude-20261001-120000.jsonl';
const ID = 'ATT1/claude-20261001-120000';
const OLD = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: 'Original question', at: 1 })
  + ev({ type: 'scholium', subtype: 'prompt', text: 'Original question', question: true });
const NEW = ev({ type: 'scholium', subtype: 'run', agent: 'claude', user: 'Edited question', at: 2 });
const recoveryAnswer = text => [ev({ type: 'system', subtype: 'init', session_id: 'S1', model: 'claude-opus-5-5' }),
  ev({ type: 'assistant', uuid: text, session_id: 'S1', message: { content: [{ type: 'text', text }] } }),
  ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1' })];
const undoRecord = () => ({ key: 'ATT1', conv: 'claude-20261001-120000', path: PATH, text: OLD, timer: null, turn: 0 });
(async () => {
  const facts = {};
  {
    const h = harness({ logs: { [PATH]: NEW }, failLogWrites: (p, t, o) => p === PATH && t === OLD && !!o.tmpPath });
    h.runner.start('x');
    h.runner.replaced.set(ID, undoRecord());
    await h.runner.undoReplace(ID);
    const failed = { kept: h.runner.replaced.has(ID), same: h.log.writes[PATH] === NEW };
    h.runner.undoTimeUp(ID);
    failed.afterExpiry = h.runner.replaced.has(ID);
    h.runner.stop(true);
    h.runner.start('x', true);
    await h.runner.undoReplace(ID);
    facts.undoWrite = { failed, restored: h.log.writes[PATH] === OLD, kept: h.runner.replaced.has(ID) };
  }
  {
    const h = harness({ logs: { [PATH]: NEW } });
    h.runner.start('x');
    h.runner.replaced.set(ID, undoRecord());
    h.runner.runs.set('rU', { id: 'rU', key: 'ATT1', kind: 'chat', conv: 'claude-20261001-120000',
                              source: { att: h.att1, conv: 'claude-20261001-120000', kind: 'chat' } });
    h.runner.cancel = () => {};
    h.zotero.Promise.delay = async () => {};
    await h.runner.undoReplace(ID);
    const timedOut = { kept: h.runner.replaced.has(ID), same: h.log.writes[PATH] === NEW };
    h.runner.runs.clear();
    await h.runner.undoReplace(ID);
    facts.undoTimeout = { timedOut, restored: h.log.writes[PATH] === OLD, kept: h.runner.replaced.has(ID) };
  }
  for (const boundary of ['timer', 'nextRun', 'reload']) {
    let locked = false, failed = false;
    const h = harness({ scripts: [recoveryAnswer('Tail answer'), recoveryAnswer('Next answer')], locale: 'en-US',
      failLogWrites: (p, t) => {
        if (t.includes('\"session_id\":\"S1\"')) failed = true;
        if (!failed || locked) return false;
        h.log.lockedOnce = false;
        return true;
      } });
    h.runner.start('x');
    await h.runner.send(h.item1, 'Question', { kind: 'chat', agent: 'claude' });
    await settle(500);
    const path = Object.keys(h.log.writes).find(p => /conversations\/(?:chat|claude)-[\w-]+\.jsonl$/.test(p));
    const pending = h.runner.pendingLogs && h.runner.pendingLogs.get(path);
    const before = { pending: !!(pending && pending.unlogged.length), saved: (h.log.writes[path] || '').includes('Tail answer'),
      outcome: h.log.ended.at(-1).text, runs: h.log.calls.length,
      reply: (await h.runner.readLog('ATT1', path.split('/').at(-1).replace('.jsonl', ''))).turns.at(-1).reply }; 
    if (boundary === 'nextRun') {
      await h.runner.send(h.item1, 'Next answer', { kind: 'chat', agent: 'claude' });
      await settle(400);
      before.blockedRuns = h.log.calls.length;
    }
    if (boundary !== 'reload') locked = true;
    if (boundary === 'timer') h.fire();
    if (boundary === 'nextRun') {
      await h.runner.send(h.item1, 'Next answer', { kind: 'chat', agent: 'claude' });
    }
    if (boundary === 'reload') {
      h.runner.stop(true);
      await settle(100);
      h.runner.pendingLogs = new Map();
      h.runner.start('x', true);
      before.reloadedState = (await h.pane(h.item1)).view('chat').state;
      locked = true; h.fire();
    }
    await settle(500);
    const events = (h.log.writes[path] || '').trim().split('\n').filter(Boolean).map(JSON.parse);
    facts[boundary] = { before, saved: events.filter(e => e.type === 'assistant').map(e => e.message.content[0].text),
      results: events.filter(e => e.type === 'result').map(e => e.result),
      pending: !!(h.runner.pendingLogs && h.runner.pendingLogs.has(path)), runs: h.log.calls.length,
      state: h.runner.notes.get('ATT1/chat')?.text || '', args: h.log.calls.at(-1).opts.arguments }; 
  }
  {
    const cannotRemove = [PATH];
    let locked = true;
    const h = harness({ logs: { [PATH]: OLD }, unremovable: cannotRemove,
      failLogWrites: () => { h.log.lockedOnce = false; return locked; } });
    h.runner.start('x');
    const index = await h.runner.index('ATT1');
    index.titles['claude-20261001-120000'] = 'Custom title';
    index.chat = null;
    await h.runner.saveIndex('ATT1');
    await h.runner.appendLog({ logPath: PATH }, [JSON.stringify({ type: 'assistant', message: { content: [{ type: 'text', text: 'Pending answer' }] } })]);
    h.runner.deleting.set(PATH, { key: 'ATT1', id: 'claude-20261001-120000', wasCurrent: true, timer: null });
    await h.runner.finishDelete(PATH);
    const failed = { pending: h.runner.pendingLogs.has(PATH), title: index.titles['claude-20261001-120000'],
      current: index.chat, deleting: h.runner.deleting.has(PATH) };
    locked = false;
    h.fire(); await settle(100);
    const retried = h.log.writes[PATH].includes('Pending answer');
    cannotRemove.splice(0);
    h.runner.deleting.set(PATH, { key: 'ATT1', id: 'claude-20261001-120000', wasCurrent: true, timer: null });
    await h.runner.finishDelete(PATH);
    h.fire(); await settle(100);
    facts.deletePending = { failed, retried, exists: PATH in h.log.writes, pending: h.runner.pendingLogs.has(PATH) };
  }
  {
    let locked = true;
    const h = harness({ logs: { [PATH]: NEW }, failLogWrites: (p, t, o) => {
      h.log.lockedOnce = false; return locked && o.mode === 'append';
    } });
    h.runner.start('x');
    await h.runner.appendLog({ logPath: PATH }, [JSON.stringify({ type: 'result', result: 'Edited answer' })]);
    h.runner.replaced.set(ID, undoRecord());
    await h.runner.undoReplace(ID);
    locked = false; h.fire(); await settle(100);
    facts.undoPending = { restored: h.log.writes[PATH] === OLD, pending: h.runner.pendingLogs.has(PATH) };
  }
  {
    const h = harness({ logs: { [PATH]: NEW } });
    h.runner.start('x');
    // The function belongs to the harness vm; this exposes only its mocked IOUtils.
    const io = await h.runner.appendLog.constructor('return IOUtils')();
    const write = io.writeUTF8;
    let release;
    io.writeUTF8 = async (path, text, opts) => {
      if (opts && opts.mode === 'append') await new Promise(resolve => { release = resolve; });
      return write(path, text, opts);
    };
    const writing = h.runner.appendLog({ logPath: PATH }, [JSON.stringify({ type: 'result', result: 'Edited answer' })]);
    await settle(10);
    h.runner.replaced.set(ID, undoRecord());
    const restoring = h.runner.undoReplace(ID);
    await h.runner.undoReplace(ID);
    await settle(10);
    const before = h.log.writes[PATH] === NEW;
    release(); await writing; await restoring;
    h.fire(); await settle(10);
    facts.undoInFlight = { before, restored: h.log.writes[PATH] === OLD, pending: h.runner.pendingLogs.has(PATH) };
  }
  {
    const h = harness({ logs: { [PATH]: NEW } });
    h.runner.start('x');
    const r = Object.assign(undoRecord(), { retitled: true, title: 'Original title' });
    h.runner.replaced.set(ID, r);
    h.runner.pendingLogs.set(PATH, { unlogged: [JSON.stringify({ type: 'assistant', message: { content: [{ type: 'text', text: 'Edited tail' }] } })], flushing: null });
    const saveIndex = h.runner.saveIndex;
    let refuse = true;
    h.runner.saveIndex = async function (key) {
      if (refuse) throw Error('Index locked');
      return saveIndex.call(this, key);
    };
    await h.runner.undoReplace(ID);
    const kept = h.runner.replaced.has(ID);
    const afterFailure = (await h.runner.readLog('ATT1', 'claude-20261001-120000')).entries.some(e => e.text === 'Edited tail');
    refuse = false;
    await h.runner.undoReplace(ID);
    facts.undoMetadata = { kept, afterFailure, restored: h.log.writes[PATH] === OLD, remaining: h.runner.replaced.has(ID),
      title: (await h.runner.index('ATT1')).titles['claude-20261001-120000'] };
  }
  {
    const h = harness({ logs: { [PATH]: NEW } });
    h.runner.start('x');
    const io = await h.runner.appendLog.constructor('return IOUtils')();
    const write = io.writeUTF8;
    let release;
    io.writeUTF8 = async (path, text, opts) => {
      if (opts && opts.mode === 'append') await new Promise(resolve => { release = resolve; });
      return write(path, text, opts);
    };
    const writing = h.runner.appendLog({ logPath: PATH }, [JSON.stringify({ type: 'result', result: 'Edited answer' })]);
    await settle(10);
    h.runner.replaced.set(ID, undoRecord());
    h.runner.runs.set('rU', { id: 'rU', key: 'ATT1', kind: 'chat', conv: 'claude-20261001-120000',
                              source: { att: h.att1, conv: 'claude-20261001-120000', kind: 'chat' } });
    h.runner.cancel = () => {};
    h.zotero.Promise.delay = async () => {};
    await h.runner.undoReplace(ID);
    release(); await writing;
    const pending = h.runner.pendingLogs.has(PATH);
    h.runner.stop(); h.runner.start('x');
    await h.runner.undoReplace(ID);
    facts.timeoutInFlight = { pending, restored: h.log.writes[PATH] === OLD };
  }
  {
    let locked = true;
    const h = harness({ logs: { [PATH]: OLD }, failLogWrites: () => { h.log.lockedOnce = false; return locked; } });
    h.runner.start('x');
    const io = await h.runner.appendLog.constructor('return IOUtils')();
    await h.runner.appendLog({ logPath: PATH }, [JSON.stringify({ type: 'assistant', message: { content: [{ type: 'text', text: 'ONE' }] } }),
      JSON.stringify({ type: 'result', result: 'ONE', num_turns: 1 })]);
    const stat = io.stat;
    let release, held = false;
    io.stat = async p => {
      if (p === PATH && !held) { held = true; await new Promise(r => { release = r; }); }
      return stat(p);
    };
    const reading = h.runner.readLog('ATT1', 'claude-20261001-120000');
    await settle(10);
    locked = false; await h.runner.flushLog(PATH); release();
    const log = await reading;
    facts.readWhileFlushing = log.entries.filter(e => e.kind === 'text' && e.text === 'ONE').length;
  }
  {
    const h = harness({ logs: { [PATH]: OLD }, scripts: [SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
    let release;
    h.runner.noteApplied = async () => await new Promise(r => { release = r; });
    h.runner.replaced.set(ID, undoRecord());
    await h.runner.send(h.item1, 'Edited', { edited: true, kind: 'chat', agent: 'claude' });
    for (let i = 0; i < 100 && !release; i++) await settle(10);
    if (!release) throw Error('Expected the mock run to reach the held result');
    let ended = false;
    const undo = h.runner.undoReplace(ID).then(() => { ended = true; });
    await settle(10); h.runner.stop(); await new Promise(r => setTimeout(r, 20));
    const before = { ended, restored: h.log.writes[PATH] === OLD };
    release(); await undo; await settle(100);
    facts.undoAfterStop = { before, restored: h.log.writes[PATH] === OLD };
  }
  {
    let locked = true;
    const h = harness({ scripts: [recoveryAnswer('Tail answer')], locale: 'en-US', failLogWrites: (p, t) => {
      h.log.lockedOnce = false; return locked && t.includes('Tail answer');
    } });
    h.runner.start('x');
    const pane = await h.pane(h.item1);
    await h.runner.annotate([h.item1]); await settle(500);
    const before = h.runner.notes.get('ATT1/annotate')?.text || '';
    h.runner.notes.clear();
    const reopened = await h.pane(h.item1);
    const newPane = reopened.view('annotate').state;
    locked = false; h.fire(); await settle(100);
    facts.annotationWarning = { before, newPane, after: h.runner.notes.get('ATT1/annotate')?.text || '' };
  }
  {
    const h = harness({ logs: { [PATH]: OLD }, failLogWrites: (p, text, opts) => {
      h.log.lockedOnce = false; return opts.mode === 'append';
    } });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', 'claude-20261001-120000');
    await h.runner.appendLog({ logPath: PATH }, [JSON.stringify({ type: 'assistant', message: { content: [{ type: 'text', text: 'Unsaved original answer' }] } })]);
    const p = await h.pane(h.item1);
    const view = h.runner.viewOf(p.pane(), 'chat');
    const prompt = h.runner.runsOf(view.entries)[0].prompt;
    const edited = await h.runner.editTurn(view, prompt, 'Edited question');
    await settle(100);
    facts.editUnsaved = { edited, same: h.log.writes[PATH] === OLD, pending: h.runner.pendingLogs.has(PATH), runs: h.log.calls.length };
  }
  {
    const h = harness({ logs: { [PATH]: NEW } });
    h.runner.start('x');
    await h.pane(h.item1);
    h.runner.replaced.set(ID, undoRecord());
    h.runner.showConversation = async () => { throw Error('Pane was closed'); };
    await h.runner.undoReplace(ID);
    facts.undoRedraw = { restored: h.log.writes[PATH] === OLD, pending: h.runner.pendingLogs.has(PATH), kept: h.runner.replaced.has(ID) };
  }
  {
    let locked = true;
    const old = harness({ logs: { [PATH]: OLD }, failLogWrites: () => { old.log.lockedOnce = false; return locked; } });
    old.runner.start('x');
    const next = harness({ logs: { [PATH]: OLD } });
    next.log.writes = old.log.writes;
    next.zotero.ScholiumPendingLogs = old.runner.pendingLogs;
    next.runner.start('x', true);
    // Both vm copies see the same owner in a real Zotero process.
    old.zotero.ScholiumLogWriter = next.runner;
    old.runner.stop();
    await old.runner.appendLog({ logPath: PATH }, [JSON.stringify({ type: 'result', result: 'Late old-copy answer' })]);
    locked = false; next.fire(); await settle(100);
    facts.reloadLateWrite = { saved: next.log.writes[PATH].includes('Late old-copy answer'), pending: next.runner.pendingLogs.has(PATH) };
  }
  {
    let locked = true;
    const h = harness({ logs: { [PATH]: OLD }, failLogWrites: () => { h.log.lockedOnce = false; return locked; } });
    h.runner.start('x');
    await h.runner.endWaiting({ att: h.att1, conv: 'claude-20261001-120000', kind: 'chat' });
    locked = false; h.fire(); await settle(100);
    facts.waitingTail = h.log.writes[PATH].trim().split('\n').map(JSON.parse).filter(e => e.subtype === 'end' || e.subtype === 'time').map(e => e.subtype);
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { console.error(e.stack || e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_failed_undo_keeps_backup_and_can_retry(facts):
    assert facts["undoWrite"] == {
        "failed": {"kept": True, "same": True, "afterExpiry": True},
        "restored": True, "kept": False,
    }


def test_undo_never_overwrites_a_run_that_did_not_stop(facts):
    assert facts["undoTimeout"] == {
        "timedOut": {"kept": True, "same": True}, "restored": True, "kept": False,
    }


@pytest.mark.parametrize("boundary", ["timer", "nextRun", "reload"])
def test_unsaved_tail_survives_and_retries_without_rerunning_answer(facts, boundary):
    f = facts[boundary]
    assert f["before"]["pending"] is True
    assert f["before"]["saved"] is False
    assert f["before"]["reply"] == "Tail answer"
    assert "not saved" in f["before"]["outcome"].lower()
    assert f["saved"].count("Tail answer") == 1
    assert f["results"].count("Tail answer") == 1
    assert f["pending"] is False
    assert "not saved" not in f["state"].lower()
    assert f["runs"] == (2 if boundary == "nextRun" else 1)
    if boundary == "nextRun":
        assert f["before"]["blockedRuns"] == 1


def test_failed_delete_keeps_title_and_releases_pending_writes(facts):
    f = facts["deletePending"]
    assert f["failed"] == {"pending": True, "title": "Custom title", "current": "claude-20261001-120000", "deleting": False}
    assert f["retried"] is True
    assert f["exists"] is False and f["pending"] is False


def test_undo_drops_the_edited_answer_pending_retry(facts):
    assert facts["undoPending"] == {"restored": True, "pending": False}


def test_undo_waits_for_inflight_write_and_coalesces_double_click(facts):
    assert facts["undoInFlight"] == {"before": True, "restored": True, "pending": False}


def test_undo_keeps_backup_until_title_is_restored(facts):
    assert facts["undoMetadata"] == {"kept": True, "afterFailure": False, "restored": True, "remaining": False, "title": "Original title"}


def test_timed_out_undo_backup_survives_inflight_write_finishing(facts):
    assert facts["timeoutInFlight"] == {"pending": True, "restored": True}


def test_reading_during_recovery_does_not_duplicate_the_tail(facts):
    assert facts["readWhileFlushing"] == 1


def test_undo_waits_for_old_run_to_settle_after_plugin_stops(facts):
    assert facts["undoAfterStop"] == {"before": {"ended": False, "restored": False}, "restored": True}


def test_annotation_view_warns_until_its_tail_is_saved(facts):
    assert "not saved" in facts["annotationWarning"]["before"].lower()
    assert "not saved" in facts["annotationWarning"]["newPane"].lower()
    assert facts["annotationWarning"]["after"] == ""


def test_edit_waits_until_original_answer_is_saved(facts):
    assert facts["editUnsaved"] == {"edited": False, "same": True, "pending": True, "runs": 0}


def test_successful_undo_is_not_reversed_by_a_closed_pane(facts):
    assert facts["undoRedraw"] == {"restored": True, "pending": False, "kept": False}


def test_new_plugin_copy_retries_late_old_copy_writes(facts):
    assert facts["reloadLateWrite"] == {"saved": True, "pending": False}


def test_cancelled_queued_run_keeps_all_final_markers(facts):
    assert facts["waitingTail"] == ["end", "time"]
