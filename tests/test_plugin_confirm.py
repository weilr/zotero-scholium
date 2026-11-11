"""The user's word on what they changed in Zotero: the plugin tells the skill's script that it runs for the plugin
(SCHOLIUM_PLUGIN_RUN) and where to note the annotations and notes it held back (SCHOLIUM_HELD_BACK). The next message the
user sends in that conversation, and only that one, confirms them for the script (SCHOLIUM_CONFIRMED); a message sent
before the run that held them back ended does not, and neither does the run that held them back. Annotate again, whose
deletion first failed, confirms cleanup_other for the tool's annotations it left. An in-memory Zotero stands in for
Zotero; nothing reaches a socket."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const envOf = e => ({ run: e.SCHOLIUM_PLUGIN_RUN, held: e.SCHOLIUM_HELD_BACK, confirmed: e.SCHOLIUM_CONFIRMED });
  // a chat with Claude Code: the first run holds back NEW2, while it runs the user sends a message; then two more
  {
    const h = harness({ scripts: [SCRIPT.concat(['HOLD', LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    const held = h.runner.heldPath('ATT1');
    h.log.writes[held] = JSON.stringify({ user_edit: ['OLD9'] });   // left by a run that was cut short: not this run's
    pane.input.type('删掉那条带 important 标签的高亮'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    h.log.writes[held] = JSON.stringify({ user_edit: ['NEW2'], cleanup_other: [] });   // the script's note
    pane.input.type('顺便问一句'); pane.send.click(); await settle(20);   // sent before the report: queued
    const queued = h.runner.queue.length;
    h.log.release(); await settle(900);
    const before = h.log.calls.length;
    pane.input.type('确认，删掉它，覆盖我的修改'); pane.send.click(); await settle(600);
    pane.input.type('再问一句'); pane.send.click(); await settle(600);
    facts.chat = { queued, before, envs: h.log.calls.map(c => envOf(c.opts.environment)), held, gone: !(held in h.log.writes),
                   stdin: h.log.stdin.length, left: [...h.runner.heldBack.keys()] };
    h.runner.stop();
  }
  // Codex's server gets the same, held back by a run of its conversation
  {
    const h = harness();
    h.store.set('extensions.scholium.agent', 'codex');
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.input.type('删掉它'); pane.send.click(); await settle(800);
    h.runner.heldBack.set('ATT1/' + pane.shownConv, { keys: { cleanup_other: ['K7', 'K8'] }, seq: h.runner.sendSeq });
    pane.input.type('确认删除'); pane.send.click(); await settle(800);
    facts.codex = h.log.codexCalls.map(o => envOf(o.environment));
    h.runner.stop();
  }
  // Annotate again: confirmed for the tool's annotations only when deleting them first failed
  for (const [name, eraseFails] of [['cleared', false], ['notCleared', true]]) {
    const h = harness({ existing: [['zotero-scholium']], eraseFails });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(600);
    const job = await h.runner.resolve(h.item1);   // its one annotation is the tool's
    facts[name] = { env: h.log.calls.map(c => envOf(c.opts.environment)), own: job.att.getAnnotations().map(a => a.key) };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_only_the_next_message_confirms_what_a_run_held_back(facts):
    c = facts["chat"]
    held = c["held"]
    assert held.endswith("/tmp/scholium/ATT1/held_back.json")
    assert c["queued"] == 1 and c["before"] == 2 and c["stdin"] == 4
    assert c["envs"] == [{"run": "1", "held": held, "confirmed": ""},   # the run that held it back
                         {"run": "1", "held": held, "confirmed": ""},   # the message sent while it ran
                         {"run": "1", "held": held, "confirmed": "user_edit:NEW2"},   # the next one, for NEW2 only
                         {"run": "1", "held": held, "confirmed": ""}], "taken by that run"
    assert c["gone"] and c["left"] == [], "the note is read and removed; nothing is left to confirm"


def test_codexs_server_is_told_the_same(facts):
    held = facts["chat"]["held"]
    runs = [e for e in facts["codex"] if e]
    assert runs == [{"run": "1", "held": held, "confirmed": ""}, {"run": "1", "held": held, "confirmed": "cleanup_other:K7,K8"}]
    assert len(facts["codex"]) == 3, "the plugin's own server (the model list) is not a run's"


def test_annotate_again_confirms_cleanup_other_only_for_what_its_deletion_left(facts):
    assert facts["cleared"]["env"] == [{"run": "1", "held": facts["chat"]["held"], "confirmed": ""}]
    left = facts["notCleared"]
    assert len(left["own"]) == 1 and left["env"] == [{"run": "1", "held": facts["chat"]["held"], "confirmed": "cleanup_other:" + left["own"][0]}]
