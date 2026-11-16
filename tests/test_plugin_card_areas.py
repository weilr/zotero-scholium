"""The card counts the tool's image annotations (framed figures and tables) in a cell of their own, after the others,
only when there are some; a run that wrote only those is no run without annotations. Underlines count as highlights."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const ending = text => [said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1', num_turns: 3 })];
  for (const [name, locale, anns] of [['withAreas', 'zh-CN', [['A1', 'highlight', '#ff6666'], ['A2', 'underline', '#ffd400'], ['A3', 'image', '#2ea8e5'], ['A4', 'image', '#2ea8e5']]],
                                      ['withAreasEnglish', 'en-US', [['A1', 'highlight', '#ff6666'], ['A3', 'image', '#2ea8e5']]],
                                      ['onlyAreas', 'zh-CN', [['A3', 'image', '#2ea8e5']]],
                                      ['without', 'zh-CN', [['A1', 'highlight', '#ff6666']]]]) {
    const h = harness({ script: SCRIPT.concat(ending('Done.\n高亮 1 条，剩余警告：无')), locale });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate();
    h.att1.getAnnotations = () => anns.map(([k, t, c]) => h.ann(k, t, c));
    await settle(600);
    const card = p.pane().annot.list.children.at(-1).children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card'));
    facts[name] = card ? { cls: card.className, cells: card.children[1].children.map(c => c.textContent) } : null;
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_framed_areas_have_a_cell_of_their_own(facts):
    c = facts["withAreas"]
    assert c["cls"] == "scholium-card" and len(c["cells"]) == 5
    assert c["cells"][0].startswith("2") and c["cells"][-1] == "2框选"
    assert facts["withAreasEnglish"]["cells"][-1] == "1area"


def test_a_run_that_only_framed_areas_wrote_annotations(facts):
    assert facts["onlyAreas"]["cls"] == "scholium-card" and facts["onlyAreas"]["cells"][-1] == "1框选"


def test_without_framed_areas_the_card_is_as_before(facts):
    assert len(facts["without"]["cells"]) == 4
