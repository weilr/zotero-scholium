"""Release fixes of the final review (group F5): an annotation whose log refuses its first line, the time a run waited
for a usage limit, the Annotations tab's placeholder while an annotation waits, Ask Scholium's popup close when one
view of the reader throws, the text boxes without Zotero 7's native look on Windows, and the section's l10n arguments."""
import re

import pytest

from bridge_harness import BRIDGE, NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const DIR = '/data/tmp/scholium/ATT1/conversations/';
const OLD = 'annotate-claude-20261001-120000';
const oldLog = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: 'Annotate this paper', at: 1000 })
  + L({ type: 'scholium', subtype: 'prompt', text: 'Annotate this paper', annotate: true, extra: '' })
  + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'OLD' })
  + L({ type: 'assistant', uuid: 'o1', session_id: 'OLD', message: { content: [{ type: 'text', text: 'Annotated.' }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: 'Annotated.', session_id: 'OLD' })
  + L({ type: 'scholium', subtype: 'time', at: 2000 });
const linesOf = (h, path) => (h.log.writes[path] || '').trim().split('\n').filter(Boolean).map(l => JSON.parse(l));
const refused = (p, t) => /"subtype":"run"/.test(t);
(async () => {
  const facts = {};

  // an annotation with extra instructions whose log refuses its first line: the words go back to the Annotations tab's
  // box, the tab shows the paper's session as before, no section is left live, nothing waits
  for (const [name, logs] of [['first', {}],
                              ['again', { [DIR + OLD + '.jsonl']: oldLog,
                                          [DIR + 'index.json']: JSON.stringify({ chat: null, titles: {}, annotation: { claude: OLD } }) }]]) {
    const h = harness({ locale: 'en-US', logs, failLogWrites: refused });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    h.runner.setTab(P, 'annotate'); await settle(40);
    const shownBefore = P.annot.shownConv;
    P.input.value = 'only the methods section';
    P.annotGo.click(); await settle(900);
    const seen = () => {
      const v = pa.view();
      return { box: P.input.value, entries: v.entries.map(e => e[0]), runs: v.entries.filter(e => e[0] === 'scholium-run').map(e => e[1]),
               state: v.state, shown: v.shownConv, placeholder: v.placeholder };
    };
    const after = seen(), live = !!P.live, annotLive = !!P.annot.live;
    await h.runner.showAnnotation(P); await settle(100);
    facts['annotRefused_' + name] = { locked: !!h.log.lockedOnce, calls: h.log.calls.length, shownBefore, after, redrawn: seen(), live, annotLive,
                                      queue: h.runner.queue.length, job: !!h.runner.job, busy: h.runner.busy('ATT1'),
                                      sessions: Object.keys(h.log.writes).filter(p => p.startsWith(DIR + 'annotate-')).map(p => p.slice(DIR.length)),
                                      index: (JSON.parse(h.log.writes[DIR + 'index.json'] || '{}').annotation) || null };
    h.runner.stop();
  }
  // Annotate waits behind another paper's run, with words queued for its session; its log refuses its first line: the
  // wishes and the queued words come back to the box together, and nothing is left in the queue
  {
    const h = harness({ locale: 'en-US', gateFirst: true, failLogWrites: (p, t) => p.includes('/ATT1/') && refused(p, t) });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    const pa = await h.pane(h.item1); await settle(40);
    await h.runner.send(h.att2, 'question on B'); await settle(100);
    const P = pa.pane();
    h.runner.setTab(P, 'annotate'); await settle(40);
    P.input.value = 'only the methods section';
    P.annotGo.click(); await settle(200);
    P.input.value = 'then shorten page 5';
    h.runner.sendFromPane(P); await settle(200);
    const waiting = h.runner.queue.map(j => [j.att.key, j.kind, !!j.qid]);
    P.input.value = 'a draft'; h.runner.keepUnsent(P);
    h.log.calls[0].proc.kill(); await settle(900);
    facts.annotRefusedQueued = { waiting, locked: !!h.log.lockedOnce, calls: h.log.calls.length, queue: h.runner.queue.length,
                                 box: P.input.value, shown: P.annot.shownConv, rows: P.queueBox.children.length, annotLive: !!P.annot.live,
                                 sessions: Object.keys(h.log.writes).filter(p => p.startsWith(DIR + 'annotate-')).length };
    h.runner.stop();
  }
  // the same for a Chat question: its words back in the box, the state line says it failed, with the reason
  {
    const h = harness({ locale: 'en-US', failLogWrites: refused });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    P.input.value = 'my careful question';
    h.runner.sendFromPane(P); await settle(800);
    const v = pa.view();
    facts.chatRefused = { locked: !!h.log.lockedOnce, calls: h.log.calls.length, box: P.input.value, state: v.state,
                          runs: v.entries.filter(e => e[0] === 'scholium-run').length, live: !!P.live, annotLive: !!P.annot.live,
                          queue: h.runner.queue.length, annotBox: (h.runner.setTab(P, 'annotate'), P.input.value) };
    h.runner.stop();
  }

  // a run that hits the usage limit at once and is stopped during the wait, two hours later: the wait is not worked time
  {
    const h = harness({ locale: 'en-US', scripts: [LIMIT_HIT] });
    const CtxDate = h.runner.paintPane.constructor('return Date')();
    const realNow = CtxDate.now.bind(CtxDate);
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    const pa = await h.pane(h.item1); await settle(40);
    await h.runner.send(h.att1, 'question on A'); await settle(600);
    const paused = Object.keys(h.runner.paused || {});
    CtxDate.now = () => realNow() + 2 * 3600 * 1000;
    h.runner.stopFromPane(pa.pane()); await settle(800);
    const v = pa.view();
    const conv = v.shownConv;
    facts.waitedThenStopped = { paused, state: v.state, runs: v.entries.filter(e => e[0] === 'scholium-run').map(e => e[1]),
                                flat: v.flat.map(e => e[0]),
                                times: linesOf(h, DIR + conv + '.jsonl').filter(l => l.subtype === 'time').map(l => !!l.waited) };
    CtxDate.now = realNow;
    h.runner.stop();
  }

  // Annotate waits behind another paper's run: the Annotations tab's placeholder asks for words to the session to come
  {
    const h = harness({ locale: 'en-US', gateFirst: true });
    h.runner.start('x');
    h.runner.choose('agent', 'claude');
    const pa = await h.pane(h.item1); await settle(40);
    await h.runner.send(h.att2, 'question on B'); await settle(100);
    const P = pa.pane();
    h.runner.setTab(P, 'annotate'); await settle(40);
    const idle = P.input.placeholder;
    P.input.value = 'only the methods section';
    P.annotGo.click(); await settle(200);
    facts.placeholderWaiting = { idle, waiting: P.input.placeholder, queue: h.runner.queue.map(j => [j.att.key, j.kind || 'chat']),
                                 shown: P.annot.shownConv };
    h.log.calls[0].proc.kill(); await settle(100);
    h.runner.stop();
  }

  // Ask Scholium on Zotero 7-9 with two views, the first of which throws: the second is cleared still
  {
    const h = harness({ locale: 'en-US' });
    h.runner.start('x');
    const l = h.log.listeners.find(x => x.type === 'renderTextSelectionPopup');
    const doc = { createElement: tag => new El(tag) };
    const seen = { primary: 0, ranges: [], rendered: 0, removed: 0 };
    const primary = { _setSelectionRanges() { seen.primary++; throw new Error('not drawn'); } };
    const secondary = { _setSelectionRanges(r) { seen.ranges.push(r === undefined ? 'none' : r); }, _render() { seen.rendered++; },
                        _iframeWindow: { getSelection: () => ({ removeAllRanges() { seen.removed++; } }) } };
    const appended = [];
    l.handler({ reader: { itemID: 'ATT1', _window: h.paneWin, tabID: 'tab-r', _internalReader: { _primaryView: primary, _secondaryView: secondary } },
                doc, params: { annotation: { text: 'A passage.', pageLabel: '3', position: { pageIndex: 2, rects: [] } } },
                append: (...n) => appended.push(...n) });
    appended[0].click(); await settle(30);
    facts.popupTwoViews = { seen, pending: [...h.runner.pendingQuotes.keys()] };
    h.runner.stop();
  }

  // the section's text boxes opt out of Zotero 8+'s native look (no-native) and of Zotero 7's on Windows
  // (no-windows-native); the section's header and side button are registered with l10n arguments
  {
    const conv = 'chat-20261101-120000';
    const turn = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: 'Q1', at: 1000 }) + L({ type: 'scholium', subtype: 'prompt', text: 'Q1' })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', uuid: 'u1', session_id: 'S1', message: { content: [{ type: 'text', text: 'A1' }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: 'A1', session_id: 'S1' }) + L({ type: 'scholium', subtype: 'time', at: 2000 });
    const h = harness({ locale: 'en-US', logs: { [DIR + conv + '.jsonl']: turn, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const s = h.log.sections[0];
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    const walk = n => [n].concat(...((n && n.children) || []).map(walk));
    const opt = n => n ? [n.getAttribute('no-native'), n.getAttribute('no-windows-native')] : null;
    walk(pa.body).find(n => String(n.className || '').includes('edit-prompt')).click(); await settle(20);
    const edit = walk(pa.body).find(n => n.className === 'scholium-edit-input');
    h.runner.editSaved(P, -1); await settle(20);
    const all = walk(pa.body);
    facts.nativeLook = { input: opt(P.input), edit: opt(edit), label: opt(all.find(n => n.className === 'scholium-saved-label')),
                         words: opt(all.find(n => n.className === 'scholium-saved-prompt')),
                         header: s.header.l10nArgs, sidenav: s.sidenav.l10nArgs };
    h.runner.stop();
  }

  // what a refused run line of an annotation's new session touches (the paper has a chat and two annotation sessions)
  {
    const OLDA = 'annotate-claude-20261001-120000', XC = 'annotate-codex-20261002-120000', CH = 'chat-20261003-120000';
    const annLog = (agent, session) => L({ type: 'scholium', subtype: 'run', agent, user: 'Annotate this paper', at: 1000 })
      + L({ type: 'scholium', subtype: 'prompt', text: 'Annotate this paper', annotate: true, extra: '' })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: session })
      + L({ type: 'assistant', uuid: 'o' + session, session_id: session, message: { content: [{ type: 'text', text: 'Annotated.' }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: 'Annotated.', session_id: session })
      + L({ type: 'scholium', subtype: 'time', at: 2000 });
    const fullLogs = () => ({ [DIR + OLDA + '.jsonl']: annLog('claude', 'SA'), [DIR + XC + '.jsonl']: annLog('codex', 'TX'),
      [DIR + CH + '.jsonl']: annLog('claude', 'SC'),
      [DIR + 'index.json']: JSON.stringify({ chat: CH, titles: { [CH]: 'My chat', [OLDA]: 'Old ann', [XC]: 'Codex ann' }, annotation: { claude: OLDA, codex: XC } }) });
    const sizes = h => Object.fromEntries(Object.keys(h.log.writes).filter(p => p.startsWith(DIR)).map(p => [p.slice(DIR.length), h.log.writes[p]]));
    const snap = (h, pa, P, before, extra = {}) => {
      const after = sizes(h);
      return Object.assign({
        box: P.input.value, shown: pa.view().shownConv, queue: h.runner.queue.length, job: !!h.runner.job, annotLive: !!P.annot.live,
        index: JSON.parse(h.log.writes[DIR + 'index.json']),
        removed: h.log.removed.filter(p => p.includes('/conversations/')).map(p => p.slice(DIR.length)),
        changed: Object.keys(Object.assign({}, before, after)).filter(k => before[k] !== after[k] && k !== 'index.json').map(k => k.replace(/\d{8}-\d{6}/, 'STAMP')),
        newLogs: Object.keys(after).filter(k => k.startsWith('annotate-claude-2026110')).map(k => [k.replace(/\d{8}-\d{6}/, 'STAMP'), after[k]]),
      }, extra);
    };
    const open = async h => {
      h.runner.start('x'); h.runner.choose('agent', 'claude');
      const pa = await h.pane(h.item1); await settle(40);
      const P = pa.pane();
      h.runner.setTab(P, 'annotate'); await settle(40);
      P.input.value = 'only the methods section';
      return [pa, P];
    };
    // A: only the empty new log goes; the chat's and Codex's indexes and all three logs stay as they were
    {
      const h = harness({ locale: 'en-US', logs: fullLogs(), failLogWrites: refused });
      const before = sizes(h);
      const [pa, P] = await open(h);
      P.annotGo.click(); await settle(900);
      facts.undoneIsolated = snap(h, pa, P, before);
      h.runner.stop();
    }
    // B: the new log is not empty (a partial write): it is kept, the index still comes back
    {
      let H = null;
      const h = H = harness({ locale: 'en-US', logs: fullLogs(), failLogWrites: (p, t) => {
        if (refused(p, t) && H && H.log.writes[p] === '') { H.log.writes[p] = '{"partial":'; return true; }
        return false;
      } });
      const before = sizes(h);
      const [pa, P] = await open(h);
      P.annotGo.click(); await settle(900);
      facts.undoneKeptPartial = snap(h, pa, P, before);
      h.runner.stop();
    }
    // C: the empty new log cannot be removed: the index still comes back, the words are back, nothing waits
    {
      const h = harness({ locale: 'en-US', logs: fullLogs(), failLogWrites: refused });
      const before = sizes(h);
      const G = h.runner.paintPane.constructor('return this')();
      const realRemove = G.IOUtils.remove;
      G.IOUtils.remove = async p => { if (/annotate-claude-2026110/.test(p)) throw Error('NotAllowedError'); return realRemove(p); };
      const logged = [];
      const realLog = h.runner.log.bind(h.runner);
      h.runner.log = m => { logged.push(String(m)); return realLog(m); };
      const [pa, P] = await open(h);
      P.annotGo.click(); await settle(900);
      facts.undoneRemoveFails = snap(h, pa, P, before, { logged });
      h.runner.stop();
    }
  }

  // a log written before the wait was marked (its stop line has no `waited`) keeps its "Worked for"
  {
    const conv = 'chat-20261101-120000';
    const log = L({ type: 'scholium', subtype: 'run', agent: 'claude', user: 'Q', at: 1000000 }) + L({ type: 'scholium', subtype: 'prompt', text: 'Q' })
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', uuid: 'u1', session_id: 'S1', message: { content: [{ type: 'text', text: "You've hit your limit" }] } })
      + L({ type: 'scholium', subtype: 'end', outcome: 'cancelled', text: 'cancelled' }) + L({ type: 'scholium', subtype: 'time', at: 1000000 + 7200000 });
    const h = harness({ locale: 'en-US', logs: { [DIR + conv + '.jsonl']: log, [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(60);
    facts.oldLogWorked = { runs: pa.view().entries.filter(e => e[0] === 'scholium-run').map(e => e[1]) };
    h.runner.stop();
  }

  // a question whose connection failed, stopped during the wait for its second try: no "Worked for" line
  {
    const h = harness({ locale: 'en-US', scripts: [[SCRIPT[0], ev({ type: 'result', subtype: 'success', is_error: true, result: 'API Error: Connection error.', session_id: 'S1' })]] });
    h.runner.NET_RETRY_MS = 60000;
    h.runner.start('x');
    const pa = await h.pane(h.item1); await settle(40);
    const P = pa.pane();
    P.input.value = 'question on A';
    h.runner.sendFromPane(P); await settle(500);
    const waiting = h.runner.queue.map(j => [!!j.retried, j.retryAt > 0]);
    h.runner.stopFromPane(P); await settle(600);
    const v = pa.view();
    const times = String(h.log.writes[DIR + v.shownConv + '.jsonl'] || '').trim().split('\n').filter(Boolean).map(l => JSON.parse(l))
      .filter(l => l.subtype === 'time' || l.subtype === 'end').map(l => l.subtype + (l.waited ? ':waited' : '') + (l.outcome ? ':' + l.outcome : ''));
    facts.retryWaitStopped = { waiting, runs: v.entries.filter(e => e[0] === 'scholium-run').map(e => e[1]), state: v.state, times };
    h.runner.stop();
  }

  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_an_annotation_whose_log_refuses_its_first_line_gives_its_instructions_back(facts):
    for name in ("first", "again"):
        f = facts["annotRefused_" + name]
        assert f["locked"] is True and f["calls"] == 0
        for seen in (f["after"], f["redrawn"]):
            assert seen["box"] == "only the methods section", f"{name}: the extra instructions are back in the tab's box"
            assert seen["runs"] == [] or "NotWritableError" not in "".join(seen["runs"]), f"{name}: no bare failed run"
            assert seen["shown"] == f["shownBefore"], f"{name}: the tab shows the paper's session as before"
        assert f["live"] is False and f["annotLive"] is False, "no section is left live"
        assert f["queue"] == 0 and f["job"] is False and f["busy"] is False, "nothing waits"
    first, again = facts["annotRefused_first"], facts["annotRefused_again"]
    assert first["after"]["entries"] == ["scholium-annot-intro"] and first["after"]["shown"] is None
    assert first["after"]["placeholder"] == "Extra instructions (optional), e.g. only pages 3–5", "Enter annotates with them"
    assert first["sessions"] == [] and first["index"] == {}, "no empty session is left"
    assert again["after"]["shown"] == "annotate-claude-20261001-120000"
    assert len(again["after"]["runs"]) == 1 and again["after"]["runs"][0].startswith("Annotate this paper")
    assert again["sessions"] == ["annotate-claude-20261001-120000.jsonl"]
    assert again["index"] == {"claude": "annotate-claude-20261001-120000"}, "the earlier session is the paper's again"


def test_words_queued_to_an_annotation_whose_log_refuses_its_first_line_come_back_with_its_wishes(facts):
    q = facts["annotRefusedQueued"]
    assert q["waiting"] == [["ATT1", "annotate", False], ["ATT1", "annotate", True]]
    assert q["locked"] is True and q["calls"] == 1, "only the other paper's run started"
    assert q["box"] == "only the methods section\n\nthen shorten page 5\n\na draft", "a draft typed while it waited comes back too"
    assert q["queue"] == 0 and q["rows"] == 0 and q["shown"] is None and q["annotLive"] is False
    assert q["sessions"] == 0


def test_a_chat_question_whose_log_refuses_its_first_line_still_goes_back_to_the_box(facts):
    c = facts["chatRefused"]
    assert c["locked"] is True and c["calls"] == 0
    assert c["box"] == "my careful question" and c["state"] == "failed · NotWritableError"
    assert c["runs"] == 0 and c["live"] is False and c["annotLive"] is False and c["queue"] == 0
    assert c["annotBox"] == "", "the words stay with the Chat tab"


def test_the_wait_for_a_usage_limit_is_not_worked_time(facts):
    w = facts["waitedThenStopped"]
    assert w["paused"] == ["claude"] and w["state"] == "cancelled"
    assert w["times"] == [True], "the time line of the stop is marked as the end of a wait"
    assert len(w["runs"]) == 1 and "Worked for" not in w["runs"][0], w["runs"]
    assert "2h" not in w["runs"][0]
    assert re.search(r"\d\d:\d\d", w["runs"][0]), "the clock under the run says when it was stopped"
    assert "scholium-entry time" not in w["flat"], "no stray time line"


def test_the_annotations_tab_placeholder_while_an_annotation_waits(facts):
    p = facts["placeholderWaiting"]
    assert p["idle"] == "Extra instructions (optional), e.g. only pages 3–5"
    assert p["queue"] == [["ATT2", "chat"], ["ATT1", "annotate"]] or p["queue"] == [["ATT1", "annotate"]]
    assert p["shown"] is None
    assert p["waiting"] == "Continue this annotation, e.g. shorten the translation on page 5"


def test_ask_scholium_clears_the_other_view_when_one_throws(facts):
    p = facts["popupTwoViews"]
    assert p["seen"] == {"primary": 1, "ranges": ["none"], "rendered": 1, "removed": 1}
    assert p["pending"] == ["ATT1"]


def test_the_text_boxes_opt_out_of_zotero_7_and_8_native_looks(facts):
    n = facts["nativeLook"]
    for box in ("input", "edit", "label", "words"):
        assert n[box] == ["true", "true"], box
    source = BRIDGE.read_text(encoding="utf-8")
    sites = re.findall(r'(\w+(?:\.\w+)?)\.setAttribute\("no-native", "true"\);\n\s*(\w+(?:\.\w+)?)\.setAttribute\("no-windows-native", "true"\);', source)
    assert len(sites) == source.count('setAttribute("no-native", "true")') == 4 and all(a == b for a, b in sites)


def test_the_section_is_registered_with_l10n_arguments(facts):
    n = facts["nativeLook"]
    assert n["header"] == "{}" and n["sidenav"] == "{}", "Zotero 7 writes data-l10n-args=\"undefined\" without them"


UNDONE = "annotate-claude-20261001-120000"
INDEX_BEFORE = {"chat": "chat-20261003-120000", "annotation": {"claude": UNDONE, "codex": "annotate-codex-20261002-120000"},
                "titles": {"chat-20261003-120000": "My chat", UNDONE: "Old ann", "annotate-codex-20261002-120000": "Codex ann"}}


def test_an_undone_annotation_session_leaves_the_chat_and_the_other_agents_index_and_logs_as_they_were(facts):
    f = facts["undoneIsolated"]
    assert f["index"] == INDEX_BEFORE, "the chat's index and Codex's annotation index stay"
    assert f["changed"] == [], "all other logs are byte-identical"
    assert len(f["removed"]) == 1 and re.fullmatch(r"annotate-claude-\d{8}-\d{6}\.jsonl", f["removed"][0]), "only the empty new log is removed"
    assert f["newLogs"] == []
    assert f["box"] == "only the methods section" and f["shown"] == UNDONE
    assert f["queue"] == 0 and f["job"] is False and f["annotLive"] is False


def test_an_undone_annotation_session_keeps_a_log_that_is_not_empty_and_still_restores_the_index(facts):
    f = facts["undoneKeptPartial"]
    assert f["removed"] == [], "the partly written log is kept"
    assert f["newLogs"] == [["annotate-claude-STAMP.jsonl", '{"partial":']]
    assert f["index"] == INDEX_BEFORE
    assert f["changed"] == ["annotate-claude-STAMP.jsonl"], "only the kept log is new; the others are byte-identical"
    assert f["box"] == "only the methods section" and f["shown"] == UNDONE and f["queue"] == 0 and f["job"] is False


def test_an_undone_annotation_session_whose_log_cannot_be_removed_still_restores_the_index(facts):
    f = facts["undoneRemoveFails"]
    assert f["index"] == INDEX_BEFORE
    assert f["removed"] == [] and f["newLogs"] == [["annotate-claude-STAMP.jsonl", ""]], "the empty log stays"
    assert "session not undone: Error: NotAllowedError" in f["logged"]
    assert f["box"] == "only the methods section" and f["shown"] == UNDONE
    assert f["queue"] == 0 and f["job"] is False and f["annotLive"] is False, "nothing is queued"


def test_an_old_log_whose_stop_line_has_no_waited_keeps_its_worked_for(facts):
    runs = facts["oldLogWorked"]["runs"]
    assert len(runs) == 1 and "Worked for 2h 0m" in runs[0], runs


def test_a_stop_during_the_wait_for_a_second_try_shows_no_worked_for_line(facts):
    f = facts["retryWaitStopped"]
    assert f["waiting"] == [[True, True]] and f["state"] == "cancelled"
    assert len(f["runs"]) == 1 and "Worked for" not in f["runs"][0], f["runs"]
    assert f["times"] == ["end:cancelled", "time:waited"]
