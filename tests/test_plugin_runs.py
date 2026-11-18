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
    const TXT = '/data/scholium/papers/ATT1/sentences.txt';
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
    g.zotero.Prefs.set('extensions.scholium.maxRuns', 2, true); await settle(200);   // the settings allow two
    facts.maxRuns.raised = { calls: g.log.calls.length, queue: g.runner.queue.length };
    g.runner.stop(); await settle(50);
  }
  // a message to another conversation of a paper that runs starts at once; an update hands both runs over
  const OTHER = 'chat-20261001-120000', OTHER_PATH = '/data/scholium/papers/ATT1/conversations/' + OTHER + '.jsonl';
  const OLD = [{ type: 'scholium', subtype: 'run', agent: 'claude', user: 'old', at: 1 },
               { type: 'system', subtype: 'init', session_id: 'S0', cwd: '/data/scholium/papers/ATT1/conversations/' + OTHER },
               { type: 'assistant', session_id: 'S0', message: { content: [{ type: 'text', text: 'old answer' }] } },
               { type: 'result', subtype: 'success', is_error: false, result: 'old answer', session_id: 'S0' }].map(e => JSON.stringify(e)).join('\n') + '\n';
  {
    const h = harness({ prefs: { 'extensions.scholium.maxRuns': 3 }, scripts: [SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT'])],
                        logs: { [OTHER_PATH]: OLD } });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', null);
    await h.runner.send(h.item1, 'first'); await settle(200);
    await h.runner.send(h.item1, 'second', { conv: OTHER }); await settle(300);
    const both = { calls: h.log.calls.length, convs: [...h.runner.runs.values()].map(r => r.conv).sort() };
    h.runner.stop(true); await settle(50);
    const raw = h.store.get('extensions.scholium.carryOver');
    const logs = Object.fromEntries(Object.entries(h.log.writes).filter(([p]) => p.startsWith('/data/scholium/papers/')));
    const g = harness({ prefs: { 'extensions.scholium.maxRuns': 3, 'extensions.scholium.carryOver': raw },
                        scripts: [SCRIPT.concat(['WAIT']), SCRIPT.concat(['WAIT'])], logs });
    g.runner.start('x', true); await settle(400);
    facts.twoConvs = { both, carried: JSON.parse(raw || '{"jobs":[]}').jobs.map(j => j.conv).sort(),
                       restored: [...g.runner.runs.values()].map(r => r.conv).concat(g.runner.queue.map(j => j.conv)).sort() };
    g.runner.stop(); await settle(50);
  }
  // a message queued without its conversation while the paper's conversation runs is placed there and waits for that run
  {
    const h = harness({ prefs: { 'extensions.scholium.maxRuns': 3 }, scripts: [SCRIPT.concat(['HOLD', LAST, RESULT]), SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    await h.runner.send(h.item1, 'first'); await settle(300);
    const convA = [...h.runner.runs.values()][0].conv;
    await h.runner.send(h.item1, 'follow-up', { conv: null }); await settle(50);
    h.runner.pump(); await settle(300);
    const during = { calls: h.log.calls.length, runs: [...h.runner.runs.values()].map(r => r.conv), queued: h.runner.queue.map(j => j.conv) };
    h.log.release(); await settle(600);
    facts.oneRunPerConv = { convA, during, after: h.log.calls.length };
    h.runner.stop(); await settle(50);
  }
  // an update while a job has left the queue but its run has not begun (it waits for the folders to be moved): the job
  // is handed over as it was queued, and nothing of it runs in the copy that stops
  {
    const h = harness({ logs: { '/data/tmp/scholium/WXYZ9999/config.json': '{}' }, failMoves: ['/data/tmp/scholium/WXYZ9999'] });
    h.runner.start('x');
    await h.runner.migrating;
    // a job queued as send() queues one (send itself reads the conversations, which wait for the folders too)
    const job = Object.assign(await h.runner.resolve(h.item1), { agent: 'claude', say: 'waits for the folders', kind: 'chat', conv: null });
    h.runner.queue.push(job); h.runner.pump(); await settle(100);
    const between = { queue: h.runner.queue.length, active: h.runner.active.size, runs: h.runner.runs.size };
    h.runner.stop(true); await settle(200);
    const raw = h.store.get('extensions.scholium.carryOver');
    const g = harness({ prefs: { 'extensions.scholium.carryOver': raw }, scripts: [SCRIPT.concat(['WAIT'])] });
    g.runner.start('x', true); await settle(400);
    facts.betweenStop = { between, calls: h.log.calls.length, carried: JSON.parse(raw || '{"jobs":[]}').jobs.map(j => j.say),
                          restored: g.log.calls.length + g.runner.queue.length };
    g.runner.stop(); await settle(50);
  }
  // words queued without their conversation, placed in one whose second try waits before them, wait for that try
  {
    const h = harness({ prefs: { 'extensions.scholium.maxRuns': 3 }, logs: { [OTHER_PATH]: OLD } });
    h.runner.start('x');
    await h.runner.chooseConv('ATT1', OTHER);
    const retry = Object.assign(await h.runner.resolve(h.item1), { agent: 'claude', say: 'again', kind: 'chat', conv: OTHER, retried: true,
                                                                    retryAt: Date.now() + 60000 });
    h.runner.queue.push(retry);
    await h.runner.send(h.item1, 'follow-up', { conv: null }); await settle(300);
    facts.afterRetry = { calls: h.log.calls.length, queue: h.runner.queue.map(j => [j.say, j.conv]) };
    // ■ in the section of a new conversation: of the tab only the second try waits (no run), so ■ stops it; the queued
    // row of the other conversation stays, not held
    const p = await h.pane(h.item1); await settle(40);
    await h.runner.chooseConv('ATT1', null); await settle(20);
    h.runner.viewOf(p.pane(), 'chat').shownConv = null;
    h.runner.stopFromPane(p.pane()); await settle(100);
    facts.stopOther = { queue: h.runner.queue.map(j => j.say), held: [...h.runner.heldQueues] };
    h.runner.stop(); await settle(50);
  }
  // a stop: a job already handled is not handed over again; a copy stopped while it waited for the folders leaves what
  // was handed over to it for the next copy
  {
    const h = harness();
    h.runner.start('x');
    const done = Object.assign(await h.runner.resolve(h.item1), { agent: 'claude', say: 'handled', kind: 'chat', ended: true });
    h.runner.active.add(done);
    h.runner.stop(true); await settle(50);
    facts.endedNotCarried = h.store.get('extensions.scholium.carryOver') || null;
    const raw = JSON.stringify({ jobs: [{ key: 'ATT1', libraryID: 1, agent: 'claude', say: 'kept', kind: 'chat' }] });
    const g = harness({ prefs: { 'extensions.scholium.carryOver': raw }, logs: { '/data/tmp/scholium/WXYZ9999/config.json': '{}' },
                        failMoves: ['/data/tmp/scholium/WXYZ9999'] });
    g.runner.start('x', true);
    await g.runner.migrating;
    g.runner.stop(); await settle(100);
    facts.stoppedKeeps = g.store.get('extensions.scholium.carryOver') === raw;
  }
  // ■ in a section showing one conversation holds that conversation's queued words only
  {
    const h = harness({ prefs: { 'extensions.scholium.maxRuns': 3 }, logs: { [OTHER_PATH]: OLD },
                        scripts: [SCRIPT.concat(['HOLD', LAST, RESULT]), SCRIPT.concat(['WAIT']), SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    await h.runner.chooseConv('ATT1', null);
    await h.runner.send(h.item1, 'first'); await settle(200);
    const convA = [...h.runner.runs.values()][0].conv;
    await h.runner.send(h.item1, 'second', { conv: OTHER }); await settle(300);
    await h.runner.send(h.item1, 'follow-up A', { conv: convA }); await settle(50);
    h.runner.viewOf(pane, 'chat').shownConv = OTHER;   // the section shows the other conversation
    h.runner.stopFromPane(pane); await settle(300);
    const held = [...h.runner.heldQueues];
    h.log.release(); await settle(600);   // the first conversation's run ends: its follow-up goes on
    facts.stopOne = { convA, held, calls: h.log.calls.length, queue: h.runner.queue.map(j => j.say) };
    h.runner.stop(); await settle(50);
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
    assert m["raised"] == {"calls": 2, "queue": 0}, "more allowed in the settings: it starts"


def test_another_conversation_of_a_busy_paper_starts_and_an_update_hands_both_over(facts):
    t = facts["twoConvs"]
    assert t["both"]["calls"] == 2 and len(t["both"]["convs"]) == 2 and None not in t["both"]["convs"]
    assert t["carried"] == t["both"]["convs"]
    assert t["restored"] == t["both"]["convs"], "each conversation's run comes back"


def test_a_queued_message_never_runs_beside_its_conversations_run(facts):
    o = facts["oneRunPerConv"]
    assert o["during"] == {"calls": 1, "runs": [o["convA"]], "queued": [o["convA"]]}, "placed there, it waits"
    assert o["after"] == 2


def test_an_update_hands_over_a_job_between_the_queue_and_its_run(facts):
    b = facts["betweenStop"]
    assert b["between"] == {"queue": 0, "active": 1, "runs": 0}, "the job left the queue, its run has not begun"
    assert b["carried"] == ["waits for the folders"] and b["calls"] == 0, "handed over; no agent started in the old copy"
    assert b["restored"] == 1


def test_words_placed_in_a_conversation_wait_for_its_second_try(facts):
    assert facts["afterRetry"] == {"calls": 0, "queue": [["again", "chat-20261001-120000"], ["follow-up", "chat-20261001-120000"]]}


def test_stop_in_a_conversation_with_nothing_waiting_stops_what_waits_of_the_tab(facts):
    assert facts["stopOther"] == {"queue": ["follow-up"], "held": []}


def test_a_handled_job_is_not_handed_over_and_a_stopped_copy_keeps_the_hand_over(facts):
    assert facts["endedNotCarried"] is None
    assert facts["stoppedKeeps"] is True


def test_stop_holds_its_own_conversations_queue_only(facts):
    s = facts["stopOne"]
    assert f"ATT1/chat/{s['convA']}" not in s["held"]
    assert s["calls"] == 3 and s["queue"] == [], "the other conversation's follow-up went on"


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
