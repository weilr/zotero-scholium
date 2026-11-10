"""What the card takes from the closing line's remaining warnings: the whole remainder after the label (a period inside a
warning, as in "Fig. 3" or "p. 9", does not end it), none for the language's word for none on its own or with an aside in
brackets and for a count of 0, and the warning itself when it only starts with that word."""
import json

import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

CASES = [
    # English: a period inside a warning
    ("en-US", "30 highlights (12 core), 7 margin notes, note “X”, remaining warnings: Fig. 3 caption not translated; p. 9 is long",
     "Fig. 3 caption not translated; p. 9 is long"),
    ("en-US", "30 highlights, remaining warnings: e.g. page 3 is long.", "e.g. page 3 is long"),
    ("en-US", "30 highlights, remaining warnings: Eq. 3 is not in the sentence", "Eq. 3 is not in the sentence"),
    ("en-US", "30 highlights, 2 remaining warnings: p. 9 is long; Fig. 2 untranslated", "p. 9 is long; Fig. 2 untranslated"),
    ("en-US", "30 highlights, remaining warnings: 1 (page 3: no warnings were fixed)", "page 3: no warnings were fixed"),
    ("en-US", "30 highlights, remaining warnings: none.", ""),
    ("en-US", "30 highlights, remaining warnings: none (all fixed).", ""),
    ("en-US", "30 highlights, remaining warnings: 0", ""),
    ("en-US", "30 highlights, no warnings.", ""),
    # Chinese, simplified and traditional
    ("zh-CN", "高亮 3 条，剩余警告：0", ""),
    ("zh-CN", "高亮 3 条，剩余警告：无（全部修正）", ""),
    ("zh-CN", "高亮 3 条，剩余警告：无。", ""),
    ("zh-CN", "高亮 3 条，剩余警告：无法定位 2 句", "无法定位 2 句"),
    ("zh-CN", "高亮 3 条，剩余警告：第 3 页偏长。第 5 页缺术语。", "第 3 页偏长。第 5 页缺术语"),
    ("zh-TW", "高亮 3 條，剩餘警告：0", ""),
    ("zh-TW", "高亮 3 條，剩餘警告：無（全部修正）", ""),
    ("zh-TW", "高亮 3 條，剩餘警告 2 條（第 3 頁偏長）", "第 3 頁偏長"),
    ("zh-TW", "高亮 3 條，剩餘警告：無法定位 2 句", "無法定位 2 句"),
    ("zh-TW", "高亮 3 條，無剩餘警告。", ""),
    # other languages: the word for none alone, with an aside, or followed by the label's own word; a warning that
    # starts with it is a warning
    ("de", "30 Markierungen, verbleibende Warnungen: keine Übersetzung für S. 3", "keine Übersetzung für S. 3"),
    ("de", "30 Markierungen, verbleibende Warnungen: keine (alle behoben)", ""),
    ("de", "30 Markierungen, verbleibende Warnungen: Keine.", ""),
    ("de", "30 Markierungen, verbleibende Warnungen: 0", ""),
    ("ru-RU", "30 выделений, оставшиеся предупреждения: нет перевода на с. 3", "нет перевода на с. 3"),
    ("ru-RU", "30 выделений, оставшиеся предупреждения: нет.", ""),
    ("fr-FR", "30 surlignages, avertissements restants : aucun avertissement", ""),
    ("fr-FR", "30 surlignages, avertissements restants : aucun.", ""),
    ("ja-JP", "ハイライト 30 件、残りの警告：なし。", ""),
]

SCENARIOS = r"""
(async () => {
  const cases = %s;
  const out = [];
  for (const [locale, line] of cases) out.push(harness({ locale }).runner.warningsOf('Done.\n' + line));
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
""" % json.dumps([[locale, line] for locale, line, _ in CASES], ensure_ascii=False)


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


@pytest.mark.parametrize("i", range(len(CASES)), ids=[f"{c[0]}-{n}" for n, c in enumerate(CASES)])
def test_the_cards_warnings_from_the_closing_line(parsed, i):
    locale, line, want = CASES[i]
    assert parsed[i] == want, line
