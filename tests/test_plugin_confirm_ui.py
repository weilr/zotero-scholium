"""The confirmation pane action stays attached to the exact report, without consuming the user's draft."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const setup = async (opts = {}) => {
    const h = harness(opts); h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane(); pane.input.type('question'); pane.send.click(); await settle(600);
    const r = h.runner, at = 'ATT1/' + pane.shownConv;
    const held = { keys: { user_edit: ['A1', 'A2'], cleanup_other: ['B1'] }, seq: r.sendSeq };
    r.heldBack.set(at, held); r.paintPane(pane);
    return { h, r, pane, at, held };
  };
  for (const name of ['confirm', 'cancel', 'stale', 'switch', 'tab', 'removed', 'ordinary', 'edit', 'mutated', 'race', 'failed', 'lateSwitch', 'notStarted']) {
    const { h, r, pane, at, held } = await setup();
    if (!pane.heldRow) { facts[name] = { available: false }; r.stop(); continue; }
    const row = pane.heldRow, yes = row.children[2], no = row.children[1];
    const line = textOf(row);
    pane.input.type('unfinished draft'); pane.quote = { text: 'selected passage', page: 2 };
    const quote = pane.quote;
    if (name === 'cancel') { no.click(); yes.click(); }
    else if (name === 'stale') { r.heldBack.set(at, { keys: { user_edit: ['NEW'] }, seq: r.sendSeq }); yes.click(); }
    else if (name === 'switch') { pane.shownConv = 'other'; yes.click(); }
    else if (name === 'tab') { pane.tab = 'annotate'; yes.click(); }
    else if (name === 'removed') { r.panes.clear(); yes.click(); }
    else if (name === 'ordinary') { pane.input.type('只删除第一条，其余保留'); pane.send.click(); yes.click(); }
    else if (name === 'edit') {
      await r.editTurn(pane, pane.entries.find(e => e.kind === 'prompt'), '只删除第一条，其余保留');
      await settle(700); yes.click();
    }
    else if (name === 'mutated') { held.keys.user_edit.push('EXTRA'); yes.click(); }
    else if (name === 'failed') { r.resolve = async () => null; yes.click(); }
    else if (name === 'notStarted') { r.findClaude = async () => null; yes.click(); }
    else if (name === 'lateSwitch') {
      const run = r.run.bind(r); let unblock;
      r.run = async job => { await new Promise(go => { unblock = go; }); return run(job); };
      yes.click();
      for (let i = 0; i < 100 && !unblock; i++) await tick();
      pane.tab = 'annotate'; unblock(); await settle(800);
      pane.tab = 'chat'; r.paintPane(pane);
    }
    else if (name === 'race') {
      const resolve = r.resolve.bind(r); let unblock;
      r.resolve = async item => { await new Promise(go => { unblock = go; }); return resolve(item); };
      yes.click(); pane.shownConv = 'other'; unblock();
    } else { yes.click(); yes.click(); }
    await settle(800);
    facts[name] = { available: true, line, calls: h.log.calls.length,
      envs: h.log.calls.map(c => c.opts.environment.SCHOLIUM_CONFIRMED),
      draft: pane.input.value, quote: pane.quote === quote, left: r.heldBack.has(at), shown: !row.hidden };
    r.stop();
  }
  {
    const { h, r, pane } = await setup({ scripts: [SCRIPT.concat([LAST, RESULT]), CLAUDE_GONE, SCRIPT.concat([LAST, RESULT])] });
    if (!pane.heldRow) facts.retry = { available: false };
    else {
      pane.heldRow.children[2].click(); await settle(1000);
      facts.retry = { available: true, envs: h.log.calls.map(c => c.opts.environment.SCHOLIUM_CONFIRMED) };
    }
    r.stop();
  }
  {
    const { h, r, pane, held } = await setup();
    const row = pane.heldRow, keep = row.children[1], confirm = row.children[2];
    for (let i = 0; i < 20; i++) r.paintPane(pane);
    const stable = row.children[1] === keep && row.children[2] === confirm;
    held.keys.user_edit.push('A3'); r.paintPane(pane);
    const changed = row.children[2] !== confirm;
    confirm.click(); await settle(40);
    const staleCalls = h.log.calls.length;
    const findClaude = r.findClaude, attempted = row.children[2];
    r.findClaude = async () => null;
    attempted.click(); await settle(600);
    const offeredAgain = !row.hidden && row.children[2] !== attempted;
    r.findClaude = findClaude;
    row.children[2].click(); await settle(600);
    facts.controls = { stable, changed, staleCalls, offeredAgain, calls: h.log.calls.length,
      env: h.log.calls.at(-1).opts.environment.SCHOLIUM_CONFIRMED };
    r.stop();
  }
  // The same job may retry, but changing the report, conversation, or sequence never grants a new message permission.
  {
    const { h, r, pane, at, held } = await setup();
    if (!pane.heldRow) facts.scope = { available: false };
    else {
      const captured = { pane, key: 'ATT1', conv: pane.shownConv, kind: 'chat', held, keys: JSON.stringify(held.keys) };
      const base = { conv: pane.shownConv, kind: 'chat', say: 'confirmation', sentSeq: r.sendSeq + 1, confirmation: captured };
      captured.job = base; held.confirmation = captured;
      const probe = (changes, key = 'ATT1') => {
        const job = { ...base, ...changes }; captured.job = job;
        return r.confirmedFor(job, key);
      };
      facts.scope = { available: true, valid: r.confirmedFor(base, 'ATT1'),
        duplicateJob: r.confirmedFor({ ...base }, 'ATT1'),
        earlier: probe({ sentSeq: held.seq }),
        otherConv: probe({ conv: 'other' }),
        otherKey: probe({}, 'ATT2'),
        otherKind: probe({ kind: 'annotate' }),
        textToken: probe({ confirmation: 'yes' }),
        retryText: probe({ confirmation: null, retry: true, sentSeq: 0 }) };
      const retry = { ...base, confirmed: facts.scope.valid };
      r.heldBack.delete(at);
      facts.scope.retryEnv = r.runEnv({ job: retry, key: 'ATT1' }).SCHOLIUM_CONFIRMED;
    }
    r.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_button_confirms_the_reported_group_once_and_preserves_draft(facts):
    f = facts["confirm"]
    assert f["available"], "the confirmation row is missing"
    assert "3" in f["line"]
    assert f["calls"] == 2 and f["envs"] == ["", "user_edit:A1,A2;cleanup_other:B1"]
    assert f["draft"] == "unfinished draft" and f["quote"] and not f["left"]


def test_keep_unchanged_cancels_without_sending_or_consuming_draft(facts):
    f = facts["cancel"]
    assert f["available"]
    assert f["calls"] == 1 and not f["left"]
    assert f["draft"] == "unfinished draft" and f["quote"]


@pytest.mark.parametrize("name", ["stale", "switch", "tab", "removed", "mutated", "race"])
def test_stale_or_moved_buttons_never_send_confirmation(facts, name):
    f = facts[name]
    assert f["available"]
    assert f["calls"] == 1 and f["envs"] == [""]


@pytest.mark.parametrize("name", ["ordinary", "edit"])
def test_ordinary_partial_message_invalidates_the_old_button(facts, name):
    f = facts[name]
    assert f["available"]
    assert f["calls"] == 2 and f["envs"] == ["", ""] and not f["left"]


@pytest.mark.parametrize("name", ["failed", "notStarted"])
def test_failed_send_keeps_draft_and_offers_confirmation_again(facts, name):
    f = facts[name]
    assert f["available"]
    assert f["calls"] == 1 and f["left"] and f["shown"]
    assert f["draft"] == "unfinished draft" and f["quote"]


def test_switch_after_enqueue_keeps_the_accepted_job_authorized(facts):
    f = facts["lateSwitch"]
    assert f["available"]
    assert f["envs"] == ["", "user_edit:A1,A2;cleanup_other:B1"] and not f["left"]


def test_automatic_retry_only_reuses_its_own_actual_confirmation(facts):
    f = facts["retry"]
    assert f["available"]
    assert f["envs"] == ["", "user_edit:A1,A2;cleanup_other:B1", "user_edit:A1,A2;cleanup_other:B1"]


def test_unchanged_report_keeps_its_confirmation_controls(facts):
    assert facts["controls"]["stable"] is True


def test_changed_report_replaces_controls_and_rejects_old_action(facts):
    assert facts["controls"]["changed"] is True
    assert facts["controls"]["staleCalls"] == 1


def test_failed_start_offers_a_fresh_working_confirmation(facts):
    f = facts["controls"]
    assert f["offeredAgain"] is True
    assert f["calls"] == 2
    assert f["env"] == "user_edit:A1,A2,A3;cleanup_other:B1"


def test_confirmation_scope_sequence_and_retry(facts):
    f = facts["scope"]
    assert f["available"]
    assert f["valid"] == {"user_edit": ["A1", "A2"], "cleanup_other": ["B1"]}
    assert all(f[k] == {} for k in ["duplicateJob", "earlier", "otherConv", "otherKey", "otherKind", "textToken", "retryText"])
    assert f["retryEnv"] == "user_edit:A1,A2;cleanup_other:B1"
