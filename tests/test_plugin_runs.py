"""Runs of several conversations at once: each run keeps its own record (runs), what the runs of one paper share is
taken one at a time (the pre-run's extract), and the queue starts what it may up to the number of runs the settings
allow."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  // two runs of a paper extract it at once: the second waits for the first's extract and takes what it wrote
  {
    const h = harness();
    h.runner.start('x');
    const TXT = '/data/tmp/scholium/ATT1/sentences.txt';
    let calls = 0, release;
    const gate = new Promise(r => { release = r; });
    const run = async () => { calls++; await gate; h.log.writes[TXT] = 'a\nb\nc\n'; return { exitCode: 0, out: '' }; };
    const ctx = { current: null };
    const first = h.runner.preExtract(run, ctx, 'ATT1', 1000);
    const second = h.runner.preExtract(run, { current: null }, 'ATT1', 1000);
    await settle(20);
    const during = calls;
    release();
    facts.extractOnce = { during, results: await Promise.all([first, second]), calls, left: h.runner.extracting.size };
  }
  // writes to one attachment go one after another; another attachment's do not wait for them
  {
    const h = harness();
    const ep = h.endpoints, order = [];
    let open = 0, most = 0;
    ep.apply = async data => {
      open++; most = Math.max(most, open); order.push('start ' + data.attachmentKey + data.n);
      await new Promise(r => setTimeout(r, 30));
      order.push('end ' + data.attachmentKey + data.n); open--;
      if (data.n === 2) throw new Error('refused');
      return { ok: true, n: data.n };
    };
    const results = await Promise.all([ep.applyInTurn({ attachmentKey: 'ATT1', n: 1 }), ep.applyInTurn({ attachmentKey: 'ATT1', n: 2 }).catch(e => String(e.message)),
                                       ep.applyInTurn({ attachmentKey: 'ATT1', n: 3 })]);
    const sameOnly = { order: order.slice(), results, left: ep.applyQueues.size };
    order.length = 0; open = 0; most = 0;
    await Promise.all([ep.applyInTurn({ attachmentKey: 'ATT1', n: 4 }), ep.applyInTurn({ attachmentKey: 'ATT2', n: 5 })]);
    facts.applyInTurn = { sameOnly, others: most };
  }
  // two papers asked at once run at once, each section showing its own run; ■ in one stops that one only
  {
    const h = harness({ prefs: { 'extensions.scholium.maxRuns': 3 }, scripts: [SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await settle(40);
    const a = p1.pane(), b = p2.pane();
    a.input.type('问甲'); a.send.click(); await settle(200);
    b.input.type('问乙'); b.send.click(); await settle(200);
    const both = { calls: h.log.calls.length, runs: [...h.runner.runs.values()].map(r => r.key).sort(), queue: h.runner.queue.length,
                   live: [a.live, b.live], shown: [a.shownKey, b.shownKey], stops: [a.send.className, b.send.className],
                   prompts: [a.list.children.at(-1).children[0].textContent, b.list.children.at(-1).children[0].textContent] };
    a.send.click(); await settle(300);   // ■ in the first section
    const stopped = { kills: h.log.kills, runs: [...h.runner.runs.values()].map(r => r.key), stops: [a.send.className, b.send.className] };
    facts.twoPapers = { both, stopped };
    h.runner.stop(); await settle(50);
  }
  // a message to a conversation that runs waits for it; a paper's chat and its annotation run at once; a second
  // annotation of the paper waits for the first
  {
    const h = harness({ prefs: { 'extensions.scholium.maxRuns': 3 },
                        scripts: [SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问一'); pane.send.click(); await settle(200);
    pane.input.type('追问'); pane.send.click(); await settle(100);
    const sameConv = { calls: h.log.calls.length, queued: h.runner.queue.map(j => j.say) };
    await h.runner.annotate([h.item1], { confirmed: true }); await settle(300);
    const withAnnotation = { calls: h.log.calls.length, kinds: [...h.runner.runs.values()].map(r => r.kind).sort(), chatDot: pane.tabChatDot.hidden === false,
                             annotDot: pane.tabAnnotateDot.hidden === false };
    await h.runner.annotate([h.item1], { confirmed: true, queueConsent: true }); await settle(200);
    facts.onePaper = { sameConv, withAnnotation, secondAnnotation: { calls: h.log.calls.length, queued: h.runner.queue.filter(j => j.annotate).length } };
    h.runner.stop(); await settle(50);
  }
  // the number of runs at once: the settings' 1 to 6; anything else is the default. With 1, the second paper waits
  {
    const h = harness();
    const n = v => { h.store.set('extensions.scholium.maxRuns', v); return h.runner.maxRuns(); };
    facts.maxRuns = { values: [n(1), n(4), n(6), n(0), n(7), n('x'), n(2.5)], fallback: h.runner.MAX_RUNS_DEFAULT };
    const g = harness({ prefs: { 'extensions.scholium.maxRuns': 1 }, scripts: [SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT'])] });
    g.runner.start('x');
    await g.runner.send(g.item1, '问甲'); await settle(200);
    await g.runner.send(g.item2, '问乙'); await settle(200);
    facts.maxRuns.one = { calls: g.log.calls.length, queue: g.runner.queue.length };
    g.runner.stop(); await settle(50);
  }
  // an update while two runs go on hands both over, each as the conversation it was
  {
    const h = harness({ prefs: { 'extensions.scholium.maxRuns': 3 }, scripts: [SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT'])] });
    h.runner.start('x');
    await h.runner.send(h.item1, '问甲'); await settle(200);
    await h.runner.send(h.item2, '问乙'); await settle(200);
    const going = h.runner.runs.size;
    h.runner.stop(true); await settle(50);
    const carried = JSON.parse(h.store.get('extensions.scholium.carryOver') || '{"jobs":[]}').jobs;
    facts.handOver = { going, carried: carried.map(j => [j.key, j.say, !!j.conv]).sort() };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_two_runs_of_a_paper_extract_it_once(facts):
    e = facts["extractOnce"]
    assert e["during"] == 1 and e["calls"] == 1, "the second run waits for the first one's extract"
    assert e["results"] == [{"lines": 3}, {"lines": 3}]
    assert e["left"] == 0


def test_two_papers_asked_at_once_run_at_once_and_stop_apart(facts):
    both = facts["twoPapers"]["both"]
    assert both["calls"] == 2 and both["runs"] == ["ATT1", "ATT2"] and both["queue"] == 0
    assert both["live"] == [True, True] and both["shown"] == ["ATT1", "ATT2"], "each section shows its own run"
    assert both["stops"] == ["scholium-round stop", "scholium-round stop"]
    assert both["prompts"][0].startswith("问甲") and both["prompts"][1].startswith("问乙")
    stopped = facts["twoPapers"]["stopped"]
    assert stopped["kills"] == 1 and stopped["runs"] == ["ATT2"], "■ stops the run of its own section"
    assert stopped["stops"] == ["scholium-round send", "scholium-round stop"]


def test_a_conversation_runs_its_messages_in_turn_beside_the_papers_annotation(facts):
    o = facts["onePaper"]
    assert o["sameConv"] == {"calls": 1, "queued": ["追问"]}, "a message to a conversation that runs waits"
    assert o["withAnnotation"]["calls"] == 2 and o["withAnnotation"]["kinds"] == ["annotate", "chat"]
    assert o["secondAnnotation"] == {"calls": 2, "queued": 0}, "a paper being annotated is left out of another Annotate"


def test_the_number_of_runs_at_once(facts):
    m = facts["maxRuns"]
    d = m["fallback"]
    assert m["values"] == [1, 4, 6, d, d, d, d]
    assert m["one"] == {"calls": 1, "queue": 1}, "with 1, the second paper waits"


def test_three_runs_at_once_by_default():
    from plugin_harness import BOOTSTRAP
    runner = (BOOTSTRAP.parent / "modules" / "runner.js").read_text(encoding="utf-8")
    assert "MAX_RUNS_DEFAULT: 3," in runner


def test_writes_to_one_attachment_go_one_after_another(facts):
    a = facts["applyInTurn"]
    assert a["sameOnly"]["order"] == ["start ATT11", "end ATT11", "start ATT12", "end ATT12", "start ATT13", "end ATT13"]
    assert a["sameOnly"]["results"] == [{"ok": True, "n": 1}, "refused", {"ok": True, "n": 3}], "a refused write does not stop the next"
    assert a["sameOnly"]["left"] == 0
    assert a["others"] == 2, "another attachment's write does not wait"


def test_the_settings_page_chooses_the_number_of_runs_at_once():
    from plugin_harness import BOOTSTRAP
    root = BOOTSTRAP.parent
    page = (root / "settings.xhtml").read_text(encoding="utf-8")
    assert '<menulist preference="extensions.scholium.maxRuns" native="true">' in page
    assert all(f'<menuitem value="{n}" label="{n}"/>' in page for n in range(1, 7))
    assert 'pref("extensions.scholium.maxRuns", "3");' in (root / "prefs.js").read_text(encoding="utf-8")
    for ftl in sorted((root / "locale").glob("*/scholium.ftl")):
        text = ftl.read_text(encoding="utf-8")
        assert "\nscholium-settings-runs = " in text and "\nscholium-settings-runs-desc = " in text, ftl.parent.name


def test_an_update_hands_every_run_over(facts):
    h = facts["handOver"]
    assert h["going"] == 2
    assert [k for k, _, _ in h["carried"]] == ["ATT1", "ATT2"], "both runs go on in the new copy"
