"""Replacing an annotation session explicitly retires its unsent queue, only after the new log starts."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
  const paused = async (options = {}) => {
    const h = harness(Object.assign({ scripts: [[init, 'WAIT'], [init, 'HOLD', LAST, RESULT]] }, options));
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(50);
    const pane = p.pane();
    p.annotate();
    for (let i = 0; i < 3000 && !h.log.stdin.length; i++) await tick();
    for (const text of ['Old queued instruction', 'Old removed instruction']) {
      pane.input.type(text); pane.send.click(); await settle(30);
    }
    pane.send.click(); await settle(500);
    const conv = pane.annot.shownConv;
    h.runner.removeQueued(pane, h.runner.queue[1].qid);
    return { h, p, pane, conv };
  };
  const state = ({ h, pane, conv }) => ({
    same: pane.annot.shownConv === conv,
    queue: h.runner.queue.map(j => j.say), held: h.runner.heldQueues.size,
    removed: [...h.runner.removedQueued.values()].map(r => r.job.say),
    calls: h.log.calls.length,
  });
  const approve = async pane => {
    pane.annotGo.click(); await settle(50);
    const question = pane.confirmRow.hidden ? '' : textOf(pane.confirmRow);
    if (!pane.confirmRow.hidden) pane.confirmRow.children.at(-1).click();
    await settle(500);
    return question;
  };
  {
    const s = await paused(), { h, pane, conv } = s;
    facts.before = state(s);
    facts.question = await approve(pane);
    pane.input.type('New queued instruction'); pane.send.click(); await settle(50);
    facts.during = state(s);
    h.runner.carryOver(h.runner.job);
    facts.carried = JSON.parse(h.runner.getPref('carryOver')).jobs.filter(j => j.qid).map(j => j.say);
    if (h.log.release) h.log.release();
    await settle(900);
    facts.finished = { queue: h.runner.queue.length, held: h.runner.heldQueues.size,
      oldSent: h.log.stdin.some(text => text.includes('Old queued instruction') || text.includes('Old removed instruction')),
      newSent: h.log.stdin.some(text => text.includes('New queued instruction')),
      oldLog: !!(await h.runner.readLog('ATT1', conv)) };
    h.runner.stop();
  }
  {
    const s = await paused(), { h, pane } = s;
    pane.annotGo.click(); await settle(50);
    facts.cancelAsked = !pane.confirmRow.hidden;
    if (!pane.confirmRow.hidden) pane.confirmRow.children[1].click();
    await settle(50);
    facts.cancelled = state(s);
    h.runner.stop();
  }
  {
    let refuse = false;
    const s = await paused({ failLogWrites: (path, text) => refuse && text.includes('"subtype":"run"') });
    refuse = true;
    await approve(s.pane);
    facts.writeFailed = state(s);
    s.h.runner.stop();
  }
  {
    const s = await paused({ confirm: false }), { h } = s;
    const count = await h.runner.annotate([h.item1]); await settle(100);
    facts.batchCancel = { count, question: h.log.confirms.at(-1) || '', ...state(s) };
    h.runner.stop();
  }
  {
    const s = await paused(), { h, pane } = s;
    const foreign = [
      { att: h.att1, kind: 'chat', conv: 'chat-old', agent: 'claude', say: 'Other chat', qid: 'chat' },
      { att: h.att1, kind: 'annotate', conv: 'annotate-codex-old', agent: 'codex', say: 'Other agent', qid: 'agent' },
      { att: (await h.runner.resolve(h.item2)).att, kind: 'annotate', conv: 'annotate-claude-old', agent: 'claude', say: 'Other paper', qid: 'paper' },
    ];
    h.runner.queue.push(...foreign);
    for (const job of foreign) h.runner.heldQueues.add(h.runner.queueKey(job));
    await approve(pane);
    facts.others = { queue: h.runner.queue.map(j => j.say), held: h.runner.heldQueues.size };
    h.runner.stop();
  }
  for (const change of ['added', 'edited', 'restored', 'expired', 'whileWriting']) {
    const s = await paused(), { h, pane, conv } = s;
    let release;
    if (change === 'whileWriting') {
      const io = await h.runner.appendLog.constructor('return IOUtils')(), write = io.writeUTF8;
      io.writeUTF8 = async (path, text, opts) => {
        if (text.includes('"subtype":"run"')) await new Promise(resolve => { release = resolve; });
        return write(path, text, opts);
      };
    } else {
      const read = h.runner.readApplied;
      h.runner.readApplied = async function (key) {
        await new Promise(resolve => { release = resolve; });
        return read.call(this, key);
      };
    }
    await approve(pane);
    if (!release) throw Error('Expected the annotation startup to wait');
    const removed = [...h.runner.removedQueued.keys()][0];
    if (change === 'edited') {
      h.runner.editQueued(pane, h.runner.queue[0].qid);
      pane.input.type('Edited after confirmation'); pane.send.click();
    } else if (change === 'restored') h.runner.undoRemoveQueued(removed);
    else if (change === 'expired') h.fire();
    else if (change === 'whileWriting') await h.runner.send(h.item1, 'Added after confirmation', { kind: 'annotate', conv });
    else { pane.input.type('Added after confirmation'); pane.send.click(); }
    await settle(50);
    release(); await settle(700);
    facts[change] = { ...state(s), hint: pane.said?.text || '', rows: textOf(pane.queueBox) };
    h.runner.stop();
  }
  {
    const s = await paused(), { h, pane } = s;
    pane.tabChat.click(); await settle(30);
    pane.input.type('New chat question'); pane.send.click(); await settle(500);
    facts.newChat = state(s);
    h.runner.stop();
  }
  {
    const s = await paused(), { h, pane, conv } = s;
    const io = await h.runner.appendLog.constructor('return IOUtils')(), write = io.writeUTF8;
    let release;
    io.writeUTF8 = async (path, text, opts) => {
      if (text.includes('"subtype":"run"') && !release) await new Promise(resolve => { release = resolve; });
      return write(path, text, opts);
    };
    await approve(pane);
    if (!release) throw Error('Expected the first run line to wait');
    h.runner.stop(true);
    const saved = h.runner.getPref('carryOver');
    const handed = JSON.parse(saved).jobs.filter(j => j.qid).map(j => j.say);
    release(); await settle(200);
    const next = harness({ logs: h.log.writes, prefs: { 'extensions.scholium.carryOver': saved } });
    next.runner.start('x', true);
    const p = await next.pane(next.item1); await settle(900);
    facts.updated = { handed, same: p.pane().annot.shownConv === conv,
      queue: next.runner.queue.map(j => j.say), held: next.runner.heldQueues.size,
      oldSent: next.log.stdin.some(text => text.includes('Old queued instruction')) };
    next.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { console.error(e.stack || e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_reannotation_confirms_and_retires_the_old_queue(facts):
    assert facts["before"] == {
        "same": True, "queue": ["Old queued instruction"], "held": 1,
        "removed": ["Old removed instruction"], "calls": 1,
    }
    assert "2" in facts["question"] and "消息" in facts["question"]
    assert facts["during"] == {
        "same": False, "queue": ["New queued instruction"], "held": 0,
        "removed": [], "calls": 2,
    }
    assert facts["finished"] == {"queue": 0, "held": 0, "oldSent": False, "newSent": True, "oldLog": True}
    assert facts["carried"] == ["New queued instruction"]


def test_cancelling_reannotation_keeps_the_old_queue_reachable(facts):
    assert facts["cancelAsked"] is True
    assert facts["cancelled"] == facts["before"]


def test_failed_new_log_keeps_the_old_queue_reachable(facts):
    assert facts["writeFailed"] == facts["before"]


def test_batch_reannotation_confirms_unsent_messages_even_without_annotations(facts):
    result = facts["batchCancel"].copy()
    assert "2" in result.pop("question")
    assert result.pop("count") == 0
    assert result == facts["before"]


def test_reannotation_preserves_other_reachable_queues(facts):
    assert facts["others"] == {"queue": ["Other chat", "Other agent", "Other paper"], "held": 3}


@pytest.mark.parametrize("phase", ["added", "whileWriting"])
def test_messages_added_after_confirmation_stay_reachable(facts, phase):
    f = facts[phase]
    assert f["same"] is True and f["calls"] == 1
    assert f["queue"] == ["Old queued instruction", "Added after confirmation"]
    assert f["held"] == 1 and f["removed"] == ["Old removed instruction"]
    assert "Added after confirmation" in f["rows"]
    assert "确认" in f["hint"]


def test_restoring_a_removed_message_requires_new_confirmation(facts):
    f = facts["restored"]
    assert f["same"] is True and f["calls"] == 1
    assert f["queue"] == ["Old queued instruction", "Old removed instruction"]
    assert f["held"] == 1 and f["removed"] == []
    assert "Old removed instruction" in f["rows"] and "确认" in f["hint"]


def test_editing_a_message_after_confirmation_keeps_the_edit_reachable(facts):
    f = facts["edited"]
    assert f["same"] is True and f["calls"] == 1
    assert f["queue"] == ["Edited after confirmation"]
    assert f["held"] == 1 and f["removed"] == ["Old removed instruction"]
    assert "Edited after confirmation" in f["rows"] and "确认" in f["hint"]


def test_expiring_remove_undo_does_not_require_new_confirmation(facts):
    f = facts["expired"]
    assert f["same"] is False and f["calls"] == 2
    assert f["queue"] == [] and f["held"] == 0 and f["removed"] == []


def test_new_chat_never_discards_annotation_messages(facts):
    assert facts["newChat"] == {**facts["before"], "calls": 2}


def test_update_during_first_log_write_preserves_the_confirmed_cleanup(facts):
    assert facts["updated"] == {
        "handed": ["Old queued instruction"], "same": False,
        "queue": [], "held": 0, "oldSent": False,
    }
