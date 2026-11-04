"""A compaction under way is shown as a run is: its line in the transcript reads "Compacting context for 12s", swept by
a light, its time written again each second; a compaction's state line is its dot. While the agent compacts by itself
in a run, the run's live line reads the same, and "Working for" again once the compaction is done."""
import re

import pytest

from bridge_harness import NODE, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
const pause = ms => new Promise(r => setTimeout(r, ms));   // the ticks of the state line are timers
const has = (n, cls) => typeof n.className === 'string' && n.className.split(' ').includes(cls);
const find = (n, cls) => has(n, cls) ? n : (n.children || []).map(c => find(c, cls)).find(Boolean) || null;
const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
(async () => {
  const facts = {};

  // /compact: the dashed line under way has the swept words and the time; the state line its dot, the time in its tooltip
  {
    const first = [init, said('回答一'), ev({ type: 'result', subtype: 'success', is_error: false, result: '回答一', session_id: 'S1' })];
    const compact = [init, ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }), 'HOLD',
      ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'manual', pre_tokens: 850000, post_tokens: 120000 } }),
      ev({ type: 'result', subtype: 'success', is_error: false, result: '', num_turns: 0, session_id: 'S1' })];
    const h = harness({ scripts: [first, compact] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(300);
    pane.input.type('/compact'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await pause(40);
    const line = pane.list.children.at(-1);
    const swept = find(line, 'scholium-working');
    const during = { line: line.textContent, cls: line.className, swept: swept && swept.textContent, key: pane.liveTime && pane.liveTime.key,
                     same: !!swept && pane.liveTime.node === swept, state: pane.state.textContent, title: pane.state.title };
    h.runner.job.started -= 65000;
    await pause(1300);
    const ticked = { text: pane.liveTime.node.textContent, connected: pane.liveTime.node.isConnected, title: pane.state.title };
    h.log.release(); await settle(400);
    const end = pane.list.children.at(-1);
    facts.manual = { during, ticked, after: end.textContent, sweptAfter: !!find(end, 'scholium-working') };
    h.runner.stop();
  }

  // Claude Code compacts by itself in a question: the live line says so while it compacts, then works again
  {
    const script = [init, ev({ type: 'system', subtype: 'status', status: 'compacting', session_id: 'S1' }), 'HOLD',
      ev({ type: 'system', subtype: 'compact_boundary', session_id: 'S1', compact_metadata: { trigger: 'auto', pre_tokens: 900000, post_tokens: 100000 } }),
      'HOLD', said('好'), ev({ type: 'result', subtype: 'success', is_error: false, result: '好', session_id: 'S1' })];
    const h = harness({ script });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问'); pane.send.click();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await pause(40);
    const head = () => { const n = find(pane.list.children.at(-1), 'scholium-fold-head'); return n ? [n.className, n.textContent] : null; };
    const compacting = { head: head(), key: pane.liveTime && pane.liveTime.key, state: pane.state.textContent };
    h.runner.job.started -= 65000;
    await pause(1300);
    const ticked = pane.liveTime.node.textContent;
    const release = h.log.release; h.log.release = null; release();
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    await pause(40);
    const working = { head: head(), key: pane.liveTime && pane.liveTime.key };
    h.log.release(); await settle(400);
    const run = pane.list.children.at(-1);
    facts.claudeAuto = { compacting, ticked, working, done: head(), lines: run.children.map(c => c.textContent).filter(t => /压缩/.test(t)) };
    h.runner.stop();
  }

  // Codex compacts by itself in a turn: the same
  {
    const h = harness({ prefs: { 'extensions.scholium-bridge.agent': 'codex' }, codex: { scripts: [[
      note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
      coItem('started', { type: 'contextCompaction', id: 'cc1' }), 'WAIT']] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问'); pane.send.click(); await settle(400);
    const head = () => { const n = find(pane.list.children.at(-1), 'scholium-fold-head'); return n ? n.textContent : null; };
    const compacting = head();
    const proc = h.log.codexProcs.at(-1);
    proc.emit([coItem('completed', { type: 'contextCompaction', id: 'cc1' }).split('"TURN"').join(JSON.stringify('U1'))]);
    await settle(200);
    const working = head();
    proc.emit([coItem('completed', { type: 'agentMessage', id: 'a1', text: '好' }), turnDone({ status: 'completed' })]
      .map(l => l.split('"TURN"').join(JSON.stringify('U1'))));
    await settle(400);
    facts.codexAuto = { compacting, working, done: head(), busy: !!h.runner.job };
    h.runner.stop();
  }

  // the words in English
  {
    const h = harness({ locale: 'en-US' });
    facts.english = h.runner.text('compactingFor', '12s');
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_a_compaction_under_way_is_swept_and_timed(facts):
    d = facts["manual"]["during"]
    assert re.fullmatch(r"◌ 正在压缩上下文 \d+ 秒", d["line"]) and d["cls"] == "scholium-compact live"
    assert re.fullmatch(r"正在压缩上下文 \d+ 秒", d["swept"]), "the words and the time are the swept part"
    assert d["key"] == "compactingFor" and d["same"] is True


def test_the_tick_writes_the_compactions_time_again(facts):
    t = facts["manual"]["ticked"]
    assert re.fullmatch(r"正在压缩上下文 1 分 \d 秒", t["text"]) and t["connected"] is True


def test_a_compactions_state_line_is_its_dot(facts):
    d = facts["manual"]["during"]
    assert d["state"] == "", "no words on the state line"
    assert re.fullmatch(r"正在压缩 · \d+s", d["title"]), "the tooltip has the time"


def test_a_finished_compaction_is_no_longer_swept(facts):
    m = facts["manual"]
    assert m["after"] == "上下文已压缩 · 850k → 120k" and m["sweptAfter"] is False


def test_claude_compacting_by_itself_shows_on_the_live_line(facts):
    c = facts["claudeAuto"]
    assert c["compacting"]["head"][0] == "scholium-fold-head live" and re.fullmatch(r"正在压缩上下文 \d+ 秒", c["compacting"]["head"][1])
    assert c["compacting"]["key"] == "compactingFor" and c["compacting"]["state"] == ""
    assert re.fullmatch(r"正在压缩上下文 1 分 \d 秒", c["ticked"]), "the run's time goes on"
    assert re.fullmatch(r"正在处理 1 分 \d 秒", c["working"]["head"][1]) and c["working"]["key"] == "workingFor", "working again once compacted"
    assert re.fullmatch(r"已处理 \d+ 秒", c["done"][1]), "a finished run's time is from its log"
    assert c["lines"] == ["上下文已自动压缩 · 900k → 100k"]


def test_codex_compacting_by_itself_shows_on_the_live_line(facts):
    c = facts["codexAuto"]
    assert re.fullmatch(r"正在压缩上下文 \d+ 秒", c["compacting"])
    assert re.fullmatch(r"正在处理 \d+ 秒", c["working"])
    assert re.fullmatch(r"已处理 \d+ 秒", c["done"]) and c["busy"] is False


def test_the_compaction_line_in_english(facts):
    assert facts["english"] == "Compacting context for 12s"


def test_the_compaction_line_is_swept_as_the_run_line_and_stops_for_reduced_motion():
    rules = css_rules()
    both = rules[".scholium-fold-head.live .scholium-working, .scholium-compact.live .scholium-working"]
    assert "animation: scholium-shimmer 2s linear infinite" in both and "background-clip: text" in both
    from bridge_harness import PLUGIN
    text = (PLUGIN / "content" / "scholium.css").read_text(encoding="utf8")
    reduced = re.search(r"@media \(prefers-reduced-motion: reduce\) \{\s*\.scholium-fold-head\.live \.scholium-working,\s*"
                        r"\.scholium-compact\.live \.scholium-working \{([^}]*)\}", text)
    assert reduced and "animation: none" in reduced.group(1)
