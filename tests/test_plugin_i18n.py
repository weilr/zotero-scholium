"""The plugin's languages: the language Zotero's locale chooses, each language's table of texts (content/i18n) against
the English one, the section and the reader button in each, the language line of the prompts, and the settings page's
Fluent files against en-US."""
import json
import re

import pytest

from plugin_harness import NODE, PLUGIN, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

I18N = PLUGIN / "content" / "i18n"
LANGS = sorted(p.stem for p in I18N.glob("*.js"))
LOCALES = sorted(p.name for p in (PLUGIN / "locale").iterdir() if p.is_dir())

# Zotero's locale -> the language of the texts
CHOICES = {
    "en-US": "en-US", "en-GB": "en-US", "": "en-US", "it-IT": "en-US", "uk-UA": "en-US",
    "zh-CN": "zh-CN", "zh": "zh-CN", "zh-SG": "zh-CN", "zh-Hans-HK": "zh-CN",
    "zh-TW": "zh-TW", "zh-HK": "zh-TW", "zh-MO": "zh-TW", "zh-Hant": "zh-TW", "zh-Hant-TW": "zh-TW",
    "ja-JP": "ja-JP", "ja": "ja-JP", "ko-KR": "ko-KR", "ko": "ko-KR",
    "de": "de", "de-DE": "de", "de-AT": "de", "fr-FR": "fr-FR", "fr-CA": "fr-FR", "es-ES": "es-ES", "es-MX": "es-ES",
    "ru-RU": "ru-RU", "ru": "ru-RU", "pt-BR": "pt-BR", "pt-PT": "pt-BR",
}
# the language line of each language's prompts, and whether they are the Chinese ones
LINES = {
    "en-US": (None, False), "zh-CN": (None, True),
    "zh-TW": ("用户使用繁体中文：高亮的译文、页边批注、阅读笔记和回答都用繁体中文写。", True),
    "ja-JP": ("The user's language is Japanese: write the highlight translations, margin notes, the reading note and answers in Japanese.", False),
    "ru-RU": ("The user's language is Russian: write the highlight translations, margin notes, the reading note and answers in Russian.", False),
    "pt-PT": ("The user's language is European Portuguese: write the highlight translations, margin notes, the reading note and answers "
              "in European Portuguese.", False),
    "pt-BR": ("The user's language is Brazilian Portuguese: write the highlight translations, margin notes, the reading note and answers "
              "in Brazilian Portuguese.", False),
}

SCENARIOS = r"""
(async () => {
  const facts = { choices: {}, tables: {}, base: {}, section: {}, prompts: {} };
  {
    const h = harness({ locale: 'en-US' });
    for (const locale of Object.keys(CHOICES)) { h.zotero.locale = locale; facts.choices[locale] = h.runner.lang(); }
  }
  // a table's texts rendered with sample arguments: numbers for the counts (Russian's plural forms among them), the
  // agents' names, words; and with markers, to see which arguments a text shows
  const NUMBERS = [0, 1, 2, 3, 4, 5, 11, 12, 21, 22, 25, 101, 111];
  const WORDS = ['claude', 'codex', 'Ctrl', '12s', 'localApi', 'x'];
  const BAD = /undefined|NaN|null|\[object|\$\{|=>/;
  // each set as long as the function's arguments (with 1s), and one more for a default's
  const samples = k => [...NUMBERS.map(n => Array(k).fill(n)), [0, 2], [2, 0], [1, 0], [0, 1], [3, 1, true], [1, 2, true], [1, 1, true],
                        [2, 3, true], [21, 5, true], ...WORDS.map(w => Array(k).fill(w))]
    .map(a => a.concat(Array(Math.max(0, k - a.length)).fill(1)));
  const marks = k => Array.from({ length: k + 1 }, (_, i) => '‹' + i + '›');
  const check = (table, base) => {
    const out = { missing: Object.keys(base).filter(k => !(k in table)), unknown: Object.keys(table).filter(k => !(k in base)),
                  kinds: [], arity: [], bad: [], dropped: [], count: Object.keys(table).length };
    for (const [key, ref] of Object.entries(base)) {
      if (!(key in table)) continue;
      const t = table[key];
      if (typeof t !== typeof ref) { out.kinds.push(key); continue; }
      if (typeof t === 'string') { if (!t.trim() || BAD.test(t)) out.bad.push([key, [], t]); continue; }
      if (t.length !== ref.length) { out.arity.push([key, t.length, ref.length]); continue; }
      for (const args of samples(Math.max(ref.length, 1))) {
        let s;
        try { s = t(...args); } catch (e) { s = 'threw ' + e; }
        // checkLabel gives back an id it does not know, a number among them
        if (typeof s === 'number') s = String(s);
        if (typeof s !== 'string' || !s.trim() || BAD.test(s) || /^threw /.test(s)) out.bad.push([key, args, String(s)]);
      }
      // with markers for the arguments (one more, a default's): a marker the English shows, the table's text shows too
      const m = marks(Math.max(ref.length, 1));
      let shown, own;
      try { shown = String(ref(...m)); own = String(t(...m)); } catch (e) { out.bad.push([key, m, 'threw ' + e]); continue; }
      m.forEach((x, i) => { if (shown.includes(x) && !own.includes(x)) out.dropped.push([key, i, own]); });
    }
    return out;
  };
  {
    const h = harness({ locale: 'en-US' });
    const en = h.runner.baseTexts(false), zh = h.runner.baseTexts(true);
    facts.base = { en: check(en, en), zh: check(zh, en), zhRendered: check(zh, zh) };
    facts.baseKeys = Object.keys(en);
  }
  for (const lang of LANGS) {
    const h = harness({ locale: lang });
    const table = h.runner.localTexts(lang);
    facts.tables[lang] = table ? check(table, h.runner.baseTexts(false)) : null;
  }
  // the section and the reader's button in each language: its tabs, the annotation tab's words, the box's placeholder,
  // and none of the English words where the language has others
  for (const lang of LANGS) {
    const h = harness({ locale: lang });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const own = h.runner.localTexts(lang), en = h.runner.baseTexts(false);
    if (!own) { facts.section[lang] = null; h.runner.stop(); continue; }
    const shown = [textOf(p.body), pane.input.placeholder];
    pane.tabAnnotate.click(); await settle(10);
    shown.push(textOf(p.body), pane.input.placeholder);
    facts.section[lang] = {
      tabs: [pane.tabChat.textContent, pane.tabAnnotate.textContent], ownTabs: [own.tabChat, own.tabAnnotate],
      annotTitle: shown[2].includes(own.annotEmptyTitle), annotButton: shown[2].includes(own.annotateThis),
      placeholders: [shown[1], shown[3]], ownPlaceholders: [own.askPlaceholder, own.annotExtraHint],
      button: [h.toggle.label(true), h.toggle.label(false)], ownButton: [own.toggleHide, own.toggleShow],
      english: Object.entries(en).filter(([k, v]) => typeof v === 'string' && v !== own[k] && / \w/.test(v) && shown.join('\n').includes(v)).map(([k]) => k),
      loads: h.log.scripts,
    };
    h.runner.stop();
  }
  // the page of a quote and of a cited sentence, and a number of tokens, as each language writes them
  facts.numbers = {};
  for (const lang of ['en-US', 'zh-CN', ...LANGS]) {
    const h = harness({ locale: lang });
    facts.numbers[lang] = { quote: h.runner.quoteLabel({ text: 'T', page: '2', label: '2' }), unlabelled: h.runner.quoteLabel({ text: 'T', page: '3' }),
                            cite: h.runner.citeNode(h.paneDoc, 'ATT1', 12, { page: 4 }).textContent,
                            k: [999, 550123, 1000000, 2567600].map(n => h.runner.kTokens(n)) };
  }
  // the prompts: an annotation, a question, and a follow-up of that question
  const qInit = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' });
  const ok = ev({ type: 'result', subtype: 'success', is_error: false, result: 'ok', session_id: 'S1' });
  for (const locale of Object.keys(LINES)) {
    const h = harness({ locale, scripts: [SCRIPT.concat([LAST, RESULT]), [qInit, ok], [qInit, ok]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    pane.annotGo.click(); await settle(600);
    pane.tabChat.click(); await settle(10);
    pane.input.type('What is new here?'); pane.send.click(); await settle(400);
    pane.input.type('And the data?'); pane.send.click(); await settle(400);
    facts.prompts[locale] = h.log.stdin.slice(0, 3);
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    head = (f"const CHOICES = {json.dumps(CHOICES)};\nconst LANGS = {json.dumps(LANGS)};\n"
            f"const LINES = {json.dumps({k: v[0] for k, v in LINES.items()})};\n")
    return run_scenarios(head + SCENARIOS, tmp_path_factory)


def test_zotero_locale_chooses_the_language(facts):
    assert facts["choices"] == CHOICES


def test_each_language_is_a_locale_folder_and_has_a_table():
    # every language but English and Simplified Chinese (baseTexts) has a table; pt-PT has pt-BR's settings page
    assert set(LOCALES) == set(CHOICES.values()) | {"pt-PT"}
    assert set(LANGS) == set(LOCALES) - {"en-US", "zh-CN", "pt-PT"}
    assert (PLUGIN / "locale/pt-PT/scholium.ftl").read_bytes() == (PLUGIN / "locale/pt-BR/scholium.ftl").read_bytes()


def test_the_english_and_chinese_texts_render(facts):
    for name, out in facts["base"].items():
        assert out["missing"] == out["unknown"] == out["kinds"] == out["arity"] == out["bad"] == [], name
    assert len(facts["baseKeys"]) == len(set(facts["baseKeys"])) > 250


@pytest.mark.parametrize("lang", LANGS)
def test_a_table_has_the_english_keys_and_arguments(facts, lang):
    out = facts["tables"][lang]
    assert out is not None, f"content/i18n/{lang}.js does not load or set texts"
    assert out["missing"] == [], "keys the table lacks"
    assert out["unknown"] == [], "keys the English does not have"
    assert out["kinds"] == [], "a string where the English has a function, or the reverse"
    assert out["arity"] == [], "functions whose arguments differ from the English (key, table's, English)"
    assert out["bad"] == [], "texts that render empty, throw or show undefined/NaN"
    assert out["dropped"] == [], "arguments the English shows and the table's text leaves out (key, argument, text)"


@pytest.mark.parametrize("lang", LANGS)
def test_the_section_and_the_reader_button_are_in_the_language(facts, lang):
    f = facts["section"][lang]
    assert f is not None, f"content/i18n/{lang}.js does not load or set texts"
    assert f["tabs"] == f["ownTabs"]
    assert f["annotTitle"] and f["annotButton"]
    assert f["placeholders"] == f["ownPlaceholders"]
    assert f["button"] == f["ownButton"]
    assert f["english"] == [], "English texts shown where the language has its own"
    assert f["loads"] == 1   # the table is loaded once


# a page as a citation gives it in each language (page 2), and a number of tokens in thousands
PAGES = {"en-US": "p.2", "zh-CN": "p.2", "zh-TW": "第\u00a02\u00a0頁", "ja-JP": "p.2", "ko-KR": "2쪽", "de": "S.\u00a02",
         "fr-FR": "p.\u00a02", "es-ES": "p.\u00a02", "ru-RU": "с.\u00a02", "pt-BR": "p.\u00a02"}
COMMA = ["999", "550k", "1,000k", "2,568k"]
THOUSANDS = {"en-US": COMMA, "zh-CN": COMMA, "zh-TW": COMMA, "ja-JP": COMMA, "ko-KR": COMMA,
             "de": ["999", "550k", "1.000k", "2.568k"], "fr-FR": ["999", "550k", "1\u202f000k", "2\u202f568k"],
             "es-ES": ["999", "550k", "1000k", "2568k"], "ru-RU": ["999", "550k", "1\u00a0000k", "2\u00a0568k"],
             "pt-BR": ["999", "550k", "1.000k", "2.568k"]}


@pytest.mark.parametrize("lang", ["en-US", "zh-CN"] + LANGS)
def test_pages_and_thousands_are_written_as_the_language_writes_them(facts, lang):
    f = facts["numbers"][lang]
    assert f["quote"] == PAGES[lang] + " · T" and f["unlabelled"] == PAGES[lang].replace("2", "3") + " · T"
    assert f["cite"] == PAGES[lang].replace("2", "4")
    assert f["k"] == THOUSANDS[lang]


@pytest.mark.parametrize("locale", list(LINES))
def test_the_prompts_carry_the_language_line(facts, locale):
    line, chinese = LINES[locale]
    prompts = facts["prompts"][locale]
    assert len(prompts) == 3
    for kind, text in zip(["annotation", "question", "follow-up"], prompts):
        assert ("使用 zotero-scholium 技能" in text or "下面是用户" in text) == chinese, kind
        if line:
            assert text.count(line) == 1, kind
        else:
            assert "The user's language is" not in text and "繁体中文" not in text, kind


def ftl_messages(path):
    """A Fluent file's messages as {id: (has a value, its attributes)}."""
    out, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"([a-z][\w-]*)\s*=\s*(.*)$", line)
        if m:
            current = m.group(1)
            assert current not in out, f"{path}: {current} twice"
            out[current] = (bool(m.group(2).strip()), [])
            continue
        a = re.match(r"\s+\.([\w-]+)\s*=\s*(\S.*)$", line)
        assert a and current, f"{path}: cannot read {line!r}"
        out[current][1].append(a.group(1))
    return out


@pytest.mark.parametrize("locale", [d for d in LOCALES if d != "en-US"])
def test_a_fluent_file_has_the_english_messages(locale):
    en = ftl_messages(PLUGIN / "locale/en-US/scholium.ftl")
    assert ftl_messages(PLUGIN / "locale" / locale / "scholium.ftl") == en
