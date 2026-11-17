"""Offline prompt contracts at the one-click agent boundary, not model-compliance tests."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

LOCALES = ["zh-CN", "zh-TW", "en-US", "ja-JP"]
PROFILE_PATH = "/data/scholium/profile.md"
EXTRA = "For this run, write only a reading note for pages 1-2; no highlights or margin notes."

SCENARIOS = r"""
(async () => {
  const facts = {};
  const profile = "# Annotation profile\n\n## User's rules (always win)\n\nOnly highlights; no margin notes or reading note.\n";
  const extra = 'For this run, write only a reading note for pages 1-2; no highlights or margin notes.';
  for (const locale of ['zh-CN', 'zh-TW', 'en-US', 'ja-JP']) {
    facts[locale] = {};
    for (const mode of ['defaults', 'profile', 'extra']) {
      const h = harness({ locale, logs: mode === 'defaults' ? {} : { [PROFILE_PATH]: profile },
                          scripts: [[ev({ type: 'system', subtype: 'init', session_id: 'S1' }),
                                     ev({ type: 'result', subtype: 'success', is_error: false, result: 'done', session_id: 'S1' })]] });
      h.runner.start('x');
      await h.runner.annotate([h.item1], { extra: mode === 'extra' ? extra : '' });
      await settle(600);
      facts[locale][mode] = { prompt: h.log.stdin[0], calls: h.log.calls.length,
                              profile: h.log.writes[PROFILE_PATH] || null };
      h.runner.stop();
    }
  }
  facts.noNote = {};
  const closings = {
    'zh-CN': ['高亮 1 条（核心 1 条），页边批注 0 条，剩余警告：无。', '高亮 0 条（核心 0 条），页边批注 1 条，剩余警告：无。'],
    'zh-TW': ['高亮 1 條（核心 1 條），頁邊批註 0 條，剩餘警告：無。', '高亮 0 條（核心 0 條），頁邊批註 1 條，剩餘警告：無。'],
    'en-US': ['1 highlight (1 core), 0 margin notes, remaining warnings: none.', '0 highlights (0 core), 1 margin note, remaining warnings: none.'],
    'ja-JP': ['ハイライト 1 件（核心 1 件）、余白注釈 0 件、残りの警告：なし。', 'ハイライト 0 件（核心 0 件）、余白注釈 1 件、残りの警告：なし。'],
  };
  for (const [locale, lines] of Object.entries(closings)) {
    facts.noNote[locale] = [];
    for (const [index, line] of lines.entries()) {
      const h = harness({ locale, script: SCRIPT.concat([said(line), ev({ type: 'result', subtype: 'success', is_error: false,
                                                                        result: line, session_id: 'S1', num_turns: 3 })]) });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      p.annotate();
      h.att1.getAnnotations = () => [h.ann('A1', index ? 'text' : 'highlight', index ? '#1a73e8' : '#ff6666')];
      await settle(600);
      const card = p.pane().annot.list.children.at(-1).children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card'));
      facts.noNote[locale].push({ warnings: h.runner.warningsOf(line), cls: card && card.className,
                                  counts: card && card.children[1].children.map(c => c.children[0].textContent) });
      h.runner.stop();
    }
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


@pytest.mark.parametrize("locale", LOCALES)
def test_one_click_output_scope_defers_to_current_instructions_then_profile(facts, locale):
    """A blanket output request must not override a narrower saved or current request."""
    zh = locale.startswith("zh")
    for mode, result in facts[locale].items():
        prompt = result["prompt"]
        opening = prompt.splitlines()[0]
        # the defaults are named (without them a one-click run left out the margin notes and the reading note), and a
        # narrower request wins
        if zh:
            assert "默认做重点句高亮（评论只写译文，论文本身是中文时不加评论）、页边批注和阅读笔记" in opening
            assert "本次附加要求优先于画像，画像优先于技能默认值，它们只要其中一部分时只做那部分" in opening
        else:
            assert "by default key-sentence highlights (comments contain only translations; " in opening
            assert "margin notes and a reading note" in opening
            assert ("current extra instructions override the profile, which overrides the skill defaults, "
                    "and when they ask for only some of these, make only those") in opening
        assert result["calls"] == 1
        if mode == "defaults":
            assert result["profile"] is None
            assert ("不要生成或修改画像" if zh else "do not create or change a profile") in prompt
        else:
            assert PROFILE_PATH in prompt
            assert result["profile"].endswith("Only highlights; no margin notes or reading note.\n")
        assert (EXTRA in prompt) == (mode == "extra")


@pytest.mark.parametrize("locale", LOCALES)
def test_one_click_closing_does_not_claim_an_unwritten_reading_note(facts, locale):
    """Zero annotations and no note must be expressible without fabricating a title."""
    for result in facts[locale].values():
        closing = result["prompt"].splitlines()[-1]
        if locale.startswith("zh"):
            assert "计数可为 0" in closing
            assert "仅实际写入阅读笔记时加上“笔记《标题》”" in closing
        else:
            assert "counts may be 0" in closing
            assert "include note “title” only if a reading note was actually written" in closing


@pytest.mark.parametrize("locale", LOCALES)
def test_output_scope_keeps_the_same_language_translation_exception(facts, locale):
    for result in facts[locale].values():
        opening = result["prompt"].splitlines()[0]
        if locale.startswith("zh"):
            assert "论文本身是中文时不加评论" in opening
        else:
            assert "none when the paper is already in the user's language" in opening


@pytest.mark.parametrize("locale", LOCALES)
def test_no_note_closing_and_zero_unused_counts_keep_the_success_card(facts, locale):
    assert facts["noNote"][locale] == [
        {"warnings": "", "cls": "scholium-card", "counts": ["1", "0", "0", "0"]},
        {"warnings": "", "cls": "scholium-card", "counts": ["0", "1", "0", "0"]},
    ]
