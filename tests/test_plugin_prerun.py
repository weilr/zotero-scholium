"""An annotation's first steps run by the plugin before the agent starts: status and extract, with the command the prompt
names, the agent's environment and the paper's output folder, the skill's script being the one the agent finds. On success
the prompt gives their results; a scanned PDF ends the run before any agent with its card; a failure or a timeout leaves
them to the agent; ■ stops them; the section's live line says the PDF is being read."""
import json

import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const SKILL = '/home/u/.claude/skills/zotero-scholium';
const SCRIPT_PY = SKILL + '/scripts/scholium.py';
const STATUS = '{\n "item": {\n  "key": "ITEM1",\n  "title": "Paper ITEM1"\n },\n "attachments": []\n}\n';
const STATUS_RAW = STATUS;
const init = ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: 'S1', skills: ['zotero-scholium'] });
const ending = text => [said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1', num_turns: 3 })];
const has = (n, cls) => typeof n.className === 'string' && n.className.split(' ').includes(cls);
const find = (n, cls) => has(n, cls) ? n : (n.children || []).map(c => find(c, cls)).find(Boolean) || null;
const base = (extra = {}) => Object.assign({ env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe', SKILL + '/SKILL.md', SCRIPT_PY],
                                             scripts: [[init, ...ending('完成。')]] }, extra);
const calls = h => h.log.scriptCalls.map(o => ({ command: o.command, args: o.arguments, workdir: o.workdir,
                                                  port: (o.environment || {}).SCHOLIUM_ZOTERO_PORT || null }));
const annotate = async (h, item = h.item1) => {
  const p = await h.pane(item); await settle(40);
  const pane = p.pane();
  pane.tabAnnotate.click(); await settle(10);
  pane.annotGo.click();
  return { p, pane };
};
const card = pane => {
  const c = pane.annot.list.children.at(-1) && pane.annot.list.children.at(-1).children.find(n => typeof n.className === 'string' && n.className.startsWith('scholium-card'));
  return c ? c.children[0].textContent : null;
};
(async () => {
  const facts = {};
  for (const [name, runs, locale] of [['ok', { status: [STATUS, 0], extract: ['412 sentences -> s.json\n', 0] }, 'zh-CN'],
                                      ['okEnglish', { status: [STATUS, 0], extract: ['412 sentences -> s.json\n', 0] }, 'en-US'],
                                      ['statusFails', { status: ['', 1], extract: ['412 sentences -> s.json\n', 0] }, 'zh-CN'],
                                      ['extractFails', { status: [STATUS, 0], extract: ['', 1] }, 'zh-CN'],
                                      ['scanned', { status: [STATUS, 0], extract: ['{"error": "no text layer"}', 3] }, 'zh-CN']]) {
    const h = harness(base({ locale, scriptRuns: runs }));
    h.runner.start('x');
    const { pane } = await annotate(h); await settle(600);
    facts[name] = { calls: calls(h), agent: h.log.calls.length, prompt: h.log.stdin[0] || null, card: card(pane), job: !!h.runner.job,
                    noText: h.runner.text('annotNoneWarn', h.runner.text('noTextLayer')) };
    h.runner.stop();
  }
  // a status that never ends: after its 60 s the agent does it
  {
    const h = harness(base({ scriptRuns: { status: 'OPEN', extract: ['x', 0] } }));
    h.runner.start('x');
    const { pane } = await annotate(h); await settle(100);
    const head = find(pane.annot.list.children.at(-1), 'scholium-fold-head');
    const during = { agent: h.log.calls.length, timers: h.live(), live: head ? head.textContent : null, reading: h.runner.text('preRun') };
    h.fire(); await settle(600);
    facts.timeout = { during, agent: h.log.calls.length, prompt: h.log.stdin[0] || null, calls: h.log.scriptCalls.length };
    h.runner.stop();
  }
  // the tooltip while status runs, then while extract runs, then once the agent goes on from them
  {
    const h = harness(base({ scriptRuns: { status: 'HOLD', extract: 'HOLD' },
                             scripts: [[init, tool('Read', { file_path: '/data/tmp/scholium/ATT1/sentences.txt' }, 'r1'), answer('x', false, 'r1'), 'WAIT']] }));
    h.runner.start('x');
    const { p } = await annotate(h); await settle(100);
    const steps = [p.view().stateTitle];
    h.log.scriptCalls.length;   // status holds: release it as if it answered
    const statusProc = h.runner.current.proc;
    statusProc.out = [STATUS_RAW]; statusProc.exit = 0; if (statusProc.gate) statusProc.gate(); await settle(100);
    steps.push(p.view().stateTitle);
    const extractProc = h.runner.current.proc;
    extractProc.out = ['412 sentences\n']; extractProc.exit = 0; if (extractProc.gate) extractProc.gate();
    h.log.writes['/data/tmp/scholium/ATT1/sentences.txt'] = 'a\nb\n';
    await settle(300);
    steps.push(p.view().stateTitle);
    facts.steps = { steps, agent: h.log.calls.length, reading: h.runner.text('preRun') };
    h.runner.cancel(); await settle(200);
    h.runner.stop();
  }
  // ■ while status runs: it is killed and no agent starts
  {
    const h = harness(base({ scriptRuns: { status: 'HOLD' } }));
    h.runner.start('x');
    await annotate(h); await settle(100);
    const stopped = h.runner.cancel(); await settle(300);
    facts.stopped = { stopped, kills: h.log.scriptKills, agent: h.log.calls.length, job: !!h.runner.job, calls: h.log.scriptCalls.length };
    h.runner.stop();
  }
  // a paper in a group library: status names the group
  {
    const h = harness(base({ groups: { 2: { groupID: 777 } }, scriptRuns: { status: [STATUS, 0], extract: ['x', 0] } }));
    h.runner.start('x');
    const g = h.groupPaper(2);
    await annotate(h, g.item); await settle(600);
    facts.group = { calls: calls(h), agent: h.log.calls.length };
    h.runner.stop();
  }
  // a question, and an annotation without the skill's script, run nothing before the agent
  {
    const h = harness(base({ scriptRuns: { status: [STATUS, 0], extract: ['x', 0] }, scripts: [[init, ...ending('答。')]] }));
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.pane().input.type('这篇讲什么？'); p.pane().send.click(); await settle(400);
    facts.question = { calls: h.log.scriptCalls.length, agent: h.log.calls.length };
    h.runner.stop();
  }
  {
    const h = harness(base({ present: ['/w/bin/uv.exe'], scriptRuns: { status: [STATUS, 0], extract: ['x', 0] } }));
    h.runner.start('x');
    await annotate(h); await settle(600);
    facts.noSkill = { calls: h.log.scriptCalls.length, agent: h.log.calls.length };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""

OUT = "/data/tmp/scholium/ATT1"
SCRIPT_PY = "/home/u/.claude/skills/zotero-scholium/scripts/scholium.py"
STATUS = '{"item":{"key":"ITEM1","title":"Paper ITEM1"},"attachments":[]}'
STATUS_ARGS = ["run", SCRIPT_PY, "status", "ITEM1"]
EXTRACT_ARGS = ["run", SCRIPT_PY, "extract", "--config", OUT + "/paper.json", "--sentences", OUT + "/sentences.json", "--out", OUT + "/sentences.txt"]
ZH_LINES = ("插件已经运行了 status（第 1 步）和 extract（第 2 步），不要再运行它们：\n"
            f"- status 的输出：{STATUS}\n"
            f"- extract 写好了 {OUT}/sentences.txt（2 行，开头几行是索引）和同一目录的 sentences.json\n")
EN_LINES = ("The plugin has already run status (step 1) and extract (step 2); do not run them again:\n"
            f"- status output: {STATUS}\n"
            f"- extract wrote {OUT}/sentences.txt (2 lines; its first lines are the index) and sentences.json beside it\n")


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_status_and_extract_run_before_the_agent_with_its_command_and_environment(facts):
    f = facts["ok"]
    assert [(c["command"], c["args"], c["workdir"], c["port"]) for c in f["calls"]] == [
        ("/w/bin/uv.exe", STATUS_ARGS, OUT, "23119"), ("/w/bin/uv.exe", EXTRACT_ARGS, OUT, "23119")]
    assert f["agent"] == 1 and ZH_LINES in f["prompt"]
    assert ZH_LINES.split("\n")[0] in f["prompt"] and f["prompt"].count("status") >= 2
    assert EN_LINES in facts["okEnglish"]["prompt"]


@pytest.mark.parametrize("name, ran", [("statusFails", 1), ("extractFails", 2)])
def test_a_failure_leaves_them_to_the_agent(facts, name, ran):
    f = facts[name]
    assert len(f["calls"]) == ran and f["agent"] == 1
    assert "插件已经运行了 status" not in f["prompt"]


def test_a_scanned_pdf_ends_the_run_before_any_agent(facts):
    f = facts["scanned"]
    assert len(f["calls"]) == 2 and f["agent"] == 0 and f["prompt"] is None
    assert f["card"] == f["noText"] and f["job"] is False


def test_a_status_that_never_ends_is_given_up_and_left_to_the_agent(facts):
    t = facts["timeout"]
    assert t["during"]["agent"] == 0 and 60000 in t["during"]["timers"]
    assert t["during"]["live"] and t["during"]["reading"] in t["during"]["live"], "the live line says the PDF is being read"
    assert t["agent"] == 1 and t["calls"] == 1 and "插件已经运行了 status" not in t["prompt"]


def test_stop_during_the_pre_run_starts_no_agent(facts):
    s = facts["stopped"]
    assert s == {"stopped": True, "kills": 1, "agent": 0, "job": False, "calls": 1}


def test_a_group_paper_gives_status_its_group(facts):
    g = facts["group"]
    assert g["calls"][0]["args"] == ["run", SCRIPT_PY, "status", "ITEM1", "--group", "777"] and g["agent"] == 1
    assert g["calls"][1]["workdir"] == "/data/tmp/scholium/ATT1_g777"


def test_a_question_and_a_missing_skill_run_nothing_before_the_agent(facts):
    assert facts["question"] == {"calls": 0, "agent": 1}
    assert facts["noSkill"] == {"calls": 0, "agent": 1}


def test_the_live_lines_steps_follow_the_pre_run(facts):
    s = facts["steps"]
    during_status, during_extract, agent = s["steps"]
    assert during_status.startswith(s["reading"] + " · 已用 "), "status: what is happening, not the agent's start"
    assert during_extract.startswith("第 1/4 步 提取句子 · 已用 ")
    assert s["agent"] == 1 and agent.startswith("第 2/4 步 通读论文 · 已用 "), "the agent goes on after status and extract"
