"""The card of an annotation that left the paper none of the tool's annotations and notes says so ("No annotations
written"), with the warnings its closing words give, in the warning colour; one that wrote some says "✓ Annotated"."""
import pytest

from plugin_harness import NODE, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const ending = text => [said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1', num_turns: 3 })];
  for (const [name, text, locale, own] of [['emptyWarned', 'Stopped.\n高亮 0 条，剩余警告：配置写入失败，尚未应用', 'zh-CN', false],
                                           ['emptySilent', 'Done.', 'zh-CN', false],
                                           ['emptyEnglish', 'Done.', 'en-US', false],
                                           ['written', 'Done.\n高亮 2 条，剩余警告：无', 'zh-CN', true]]) {
    const h = harness({ script: SCRIPT.concat(ending(text)), locale });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate();
    if (own) h.att1.getAnnotations = () => [h.ann('A1', 'highlight', '#ff6666'), h.ann('A2', 'highlight', '#ffd400')];
    await settle(600);
    const card = p.pane().annot.list.children.at(-1).children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card'));
    facts[name] = card ? { cls: card.className, title: card.children[0].textContent, nums: card.children[1].textContent } : null;
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_a_card_without_annotations_says_none_were_written_with_the_warnings(facts):
    c = facts["emptyWarned"]
    assert c["cls"] == "scholium-card none"
    assert c["title"] == "没有写入批注：配置写入失败，尚未应用"


def test_a_card_without_annotations_and_without_warnings(facts):
    assert facts["emptySilent"]["cls"] == "scholium-card none" and facts["emptySilent"]["title"] == "没有写入批注"
    assert facts["emptyEnglish"]["title"] == "No annotations written"


def test_a_card_with_annotations_is_a_success(facts):
    c = facts["written"]
    assert c["cls"] == "scholium-card" and c["title"].startswith("✓ 批注完成") and c["nums"].startswith("2")


def test_the_empty_cards_title_is_in_the_warning_colour():
    assert "color: var(--accent-orange)" in css_rules()[".scholium-card.none .scholium-card-title"]
