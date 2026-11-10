"""A question's first step run by the plugin before the agent starts: `extract` of each of its papers whose output folder
has no sentences.txt yet, the paper shown first, one after the other within one time, with the command the prompt names,
the agent's environment and the skill's script the agent finds; `status` is left to the agent. On success the prompt says
sentences.txt is written; a scanned PDF ends the run before any agent with a message; a failure or a timeout leaves extract
to the agent; ■ stops it; the live line says the PDF is being read."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const SKILL = '/home/u/.claude/skills/zotero-scholium';
const SCRIPT_PY = SKILL + '/scripts/scholium.py';
const OUT = '/data/tmp/scholium/ATT1';
const init = ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: 'S1', skills: ['zotero-scholium'] });
const ending = text => [said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1', num_turns: 3 })];
const has = (n, cls) => typeof n.className === 'string' && n.className.split(' ').includes(cls);
const find = (n, cls) => has(n, cls) ? n : (n.children || []).map(c => find(c, cls)).find(Boolean) || null;
const base = (extra = {}) => Object.assign({ env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe', SKILL + '/SKILL.md', SCRIPT_PY],
                                             scripts: [[init, ...ending('答。')]] }, extra);
const calls = h => h.log.scriptCalls.map(o => ({ command: o.command, args: o.arguments, workdir: o.workdir,
                                                  port: (o.environment || {}).SCHOLIUM_ZOTERO_PORT || null }));
const ask = async (h, words = '这篇讲什么？') => {
  const p = await h.pane(h.item1); await settle(40);
  p.pane().input.type(words); p.pane().send.click();
  return p;
};
// the items list's context menu, there before the plugin starts, for a question about two papers (Ask Scholium)
const withMenu = h => {
  const win = h.zotero.getMainWindow();
  const popup = new El('menupopup');
  popup.id = 'zotero-itemmenu';
  win.document.documentElement.append(popup);
  win.ZoteroPane.getSelectedItems = () => [h.item1, h.item2];
  return popup;
};
const askBoth = async (h, popup) => {
  popup.fire('popupshowing', { target: popup });
  popup.children.find(c => c.id === 'scholium-ask-papers').fire('command'); await settle(40);
  return ask(h, '这两篇方法有什么不同？');
};
(async () => {
  const facts = {};
  for (const [name, runs, locale, logs] of [['ok', { extract: ['412 sentences\n', 0] }, 'zh-CN', {}],
                                            ['okEnglish', { extract: ['412 sentences\n', 0] }, 'en-US', {}],
                                            ['there', { extract: ['412 sentences\n', 0] }, 'zh-CN', { [OUT + '/sentences.txt']: 'a\n' }],
                                            ['fails', { extract: ['', 1] }, 'zh-CN', {}]]) {
    const h = harness(base({ locale, logs, scriptRuns: runs }));
    h.runner.start('x');
    await ask(h); await settle(600);
    facts[name] = { calls: calls(h), agent: h.log.calls.length, prompt: h.log.stdin[0] || null };
    h.runner.stop();
  }
  // a scanned PDF: no agent, the chat says why, as does the notice, as an error
  for (const locale of ['zh-CN', 'en-US']) {
    const h = harness(base({ locale, scriptRuns: { extract: ['{"error": "the PDF has no text layer"}', 3] } }));
    h.runner.start('x');
    const p = await ask(h); await settle(600);
    const n = h.log.notices.at(-1);
    facts['scanned_' + locale] = { agent: h.log.calls.length, job: !!h.runner.job, text: h.runner.text('noTextLayerAsk'),
                                   entries: p.view().entries.map(e => e[1]), notice: n && n.descriptions, errors: n && n.errors,
                                   ends: convLines(h).filter(l => l.subtype === 'end').map(l => [l.outcome, l.text]) };
    h.runner.stop();
  }
  // an extract that never ends: after its 180 s the agent does it; the live line says the PDF is being read meanwhile
  {
    const h = harness(base({ scriptRuns: { extract: 'OPEN' } }));
    h.runner.start('x');
    const p = await ask(h); await settle(100);
    const last = p.pane().list.children.at(-1);
    const head = last && find(last, 'scholium-fold-head');
    const during = { agent: h.log.calls.length, timers: h.live(), live: head ? head.textContent : null, title: p.view().stateTitle,
                     reading: h.runner.text('preRun') };
    h.fire(); await settle(600);
    facts.timeout = { during, agent: h.log.calls.length, prompt: h.log.stdin[0] || null };
    h.runner.stop();
  }
  // ■ while extract runs: it is killed and no agent starts
  {
    const h = harness(base({ scriptRuns: { extract: 'HOLD' } }));
    h.runner.start('x');
    await ask(h); await settle(100);
    const stopped = h.runner.cancel(); await settle(300);
    facts.stopped = { stopped, kills: h.log.scriptKills, agent: h.log.calls.length, job: !!h.runner.job, calls: h.log.scriptCalls.length };
    h.runner.stop();
  }
  // a follow-up in the session, and a question without the skill's script, run nothing before the agent
  {
    const h = harness(base({ scriptRuns: { extract: ['x', 0] }, scripts: [[init, ...ending('答。')], [init, ...ending('再答。')]] }));
    h.runner.start('x');
    await ask(h); await settle(600);
    const first = h.log.scriptCalls.length;
    delete h.log.writes[OUT + '/sentences.txt'];
    await ask(h, '还有呢？'); await settle(600);
    facts.followUp = { first, calls: h.log.scriptCalls.length, agent: h.log.calls.length };
    h.runner.stop();
  }
  {
    const h = harness(base({ present: ['/w/bin/uv.exe'], scriptRuns: { extract: ['x', 0] } }));
    h.runner.start('x');
    await ask(h); await settle(600);
    facts.noSkill = { calls: h.log.scriptCalls.length, agent: h.log.calls.length };
    h.runner.stop();
  }
  // two papers: each one's extract, the paper shown first; the other's line says its sentences.txt is there
  {
    const h = harness(base({ scriptRuns: { extract: ['x', 0] } }));
    const menu = withMenu(h);
    h.runner.start('x');
    await askBoth(h, menu); await settle(800);
    facts.both = { calls: calls(h), agent: h.log.calls.length, prompt: h.log.stdin[0] || null };
    h.runner.stop();
  }
  // the other paper's sentences.txt is there already: only the paper shown is extracted
  {
    const h = harness(base({ scriptRuns: { extract: ['x', 0] }, logs: { '/data/tmp/scholium/ATT2/sentences.txt': 'a\n' } }));
    const menu = withMenu(h);
    h.runner.start('x');
    await askBoth(h, menu); await settle(800);
    facts.otherThere = { calls: calls(h).map(c => c.workdir), prompt: h.log.stdin[0] || null };
    h.runner.stop();
  }
  // the two extracts share one time: the second one gets what the first left
  {
    const h = harness(base({ scriptRuns: { extract: 'HOLD' } }));
    const menu = withMenu(h);
    h.runner.start('x');
    const CtxDate = h.runner.paintPane.constructor('return Date')();   // the plugin's own clock
    let now = 1e12;
    const real = CtxDate.now;
    CtxDate.now = () => now;
    await askBoth(h, menu); await settle(100);
    const first = h.live();
    now += 100000;   // the first extract took 100 s
    const proc = h.runner.current.proc;
    proc.out = ['x']; proc.exit = 0; h.log.writes['/data/tmp/scholium/ATT1/sentences.txt'] = 'a\nb\n'; proc.gate(); await settle(100);
    const second = h.live();
    CtxDate.now = real;
    h.runner.cancel(); await settle(200);
    facts.budget = { first, second, calls: h.log.scriptCalls.length };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""

OUT = "/data/tmp/scholium/ATT1"
SCRIPT_PY = "/home/u/.claude/skills/zotero-scholium/scripts/scholium.py"
EXTRACT_ARGS = ["run", SCRIPT_PY, "extract", "--config", OUT + "/paper.json", "--sentences", OUT + "/sentences.json", "--out", OUT + "/sentences.txt"]
ZH_LINE = (f"\n插件已经运行了 extract，写好了 {OUT}/sentences.txt（2 行，开头几行是索引）和同一目录的 sentences.json：直接读 sentences.txt，"
           "不要再运行 extract；问题要用题录（作者、出处、笔记）时再运行 status。\n")
EN_LINE = (f"\nThe plugin has already run extract: it wrote {OUT}/sentences.txt (2 lines; its first lines are the index) and sentences.json "
           "beside it. Read sentences.txt and do not run extract again; run status only when the question needs the paper's record "
           "(authors, venue, notes).\n")


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_a_first_question_runs_extract_before_the_agent_and_says_so(facts):
    f = facts["ok"]
    assert [(c["command"], c["args"], c["workdir"], c["port"]) for c in f["calls"]] == [("/w/bin/uv.exe", EXTRACT_ARGS, OUT, "23119")]
    assert f["agent"] == 1 and f["prompt"].count(ZH_LINE) == 1
    assert EN_LINE in facts["okEnglish"]["prompt"]


def test_status_is_left_to_the_agent(facts):
    assert not any("status" in c["args"] for c in facts["ok"]["calls"])
    assert "status 的输出" not in facts["ok"]["prompt"]


@pytest.mark.parametrize("name, ran", [("there", 0), ("fails", 1)])
def test_a_paper_with_sentences_or_a_failed_extract_leaves_it_as_before(facts, name, ran):
    f = facts[name]
    assert len(f["calls"]) == ran and f["agent"] == 1 and "插件已经运行了 extract" not in f["prompt"]
    assert "（已有就直接读 sentences.txt）" in f["prompt"]


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_a_scanned_pdf_ends_the_question_before_any_agent_with_a_message(facts, locale):
    s = facts["scanned_" + locale]
    assert s["agent"] == 0 and s["job"] is False
    assert s["ends"] == [["failed", s["text"]]] and any(s["text"] in e for e in s["entries"])
    assert s["errors"] == 1 and any(s["text"] in d for d in s["notice"])


def test_an_extract_that_never_ends_is_given_up_and_left_to_the_agent(facts):
    t = facts["timeout"]
    assert t["during"]["agent"] == 0 and 180000 in t["during"]["timers"]
    assert t["during"]["live"] and t["during"]["reading"] in t["during"]["live"], "the live line says the PDF is being read"
    assert t["during"]["title"].startswith(t["during"]["reading"] + " · "), "and so does the state line's tooltip"
    assert t["agent"] == 1 and "插件已经运行了 extract" not in t["prompt"]


def test_stop_during_the_questions_extract_starts_no_agent(facts):
    assert facts["stopped"] == {"stopped": True, "kills": 1, "agent": 0, "job": False, "calls": 1}


def test_a_follow_up_and_a_missing_skill_run_nothing_before_the_agent(facts):
    assert facts["followUp"] == {"first": 1, "calls": 1, "agent": 2}
    assert facts["noSkill"] == {"calls": 0, "agent": 1}


def test_a_question_about_two_papers_extracts_each_the_paper_shown_first(facts):
    b = facts["both"]
    assert [c["workdir"] for c in b["calls"]] == [OUT, "/data/tmp/scholium/ATT2"] and b["agent"] == 1
    assert b["calls"][1]["args"][3:5] == ["--config", "/data/tmp/scholium/ATT2/paper.json"]
    assert ZH_LINE in b["prompt"] and "- /data/tmp/scholium/ATT2/paper.json（Paper ITEM2；sentences.txt 已写好）\n" in b["prompt"]
    o = facts["otherThere"]
    assert o["calls"] == [OUT] and "- /data/tmp/scholium/ATT2/paper.json（Paper ITEM2；sentences.txt 已写好）\n" in o["prompt"]


def test_the_extracts_of_several_papers_share_one_time(facts):
    b = facts["budget"]
    assert 180000 in b["first"] and 80000 in b["second"] and b["calls"] == 2
