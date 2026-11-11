"""Details of the section found in a real Zotero in ten languages: Ask Scholium leaves the library's layout alone; the
narrow pane wraps the confirmation and the state line instead of cutting them, and cuts the send hint with its whole
text in the tooltip; the tooltip's time is in the language's words; the stopped card's title is a sentence's; the eye
button's English names Scholium; a scanned PDF's card has no row of zeros and reads as two sentences; once the plugin's
extract is done the agent's start is no longer "extracting"."""
import re

import pytest

from plugin_harness import NODE, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const SKILL = '/home/u/.claude/skills/zotero-scholium';
const SCRIPT_PY = SKILL + '/scripts/scholium.py';
const STATUS = '{"item":{"key":"ITEM1"},"attachments":[]}';
const init = ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: 'S1', skills: ['zotero-scholium'] });
const card = pane => {
  const c = pane.annot.list.children.at(-1) && pane.annot.list.children.at(-1).children.find(n => typeof n.className === 'string' && n.className.startsWith('scholium-card'));
  return c ? c.children.map(n => n.textContent) : null;
};
(async () => {
  const facts = {};
  // U1: Ask Scholium from the items list, the library's context pane collapsed
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.paneWin.ZoteroPane = { getSelectedItems: () => [], selectItem: async id => h.log.selected.push(id) };
    h.paneWin.ZoteroContextPane = { collapsed: true };
    await h.runner.askPapers(h.paneWin, [h.item1, h.item2]); await settle(40);
    facts.contextPane = { collapsed: h.paneWin.ZoteroContextPane.collapsed, others: (p.pane().others || []).length };
    h.runner.stop();
  }
  // U3: the send hint's whole text in its tooltip
  {
    const h = harness({ locale: 'ru-RU' });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    facts.hint = { text: p.pane().hint.textContent, title: p.pane().hint.title };
    h.runner.stop();
  }
  // U5: the tooltip's time in each language's words
  facts.tooltip = {};
  for (const locale of ['zh-CN', 'en-US', 'de', 'ja-JP']) {
    const h = harness({ locale });
    h.runner.job = { started: Date.now() - 65000, step: 'reading', source: {}, asking: false };
    facts.tooltip[locale] = h.runner.runningTitle();
  }
  // U6: a stopped annotation's card; U7: the eye button's English
  for (const locale of ['en-US', 'de', 'zh-CN']) {
    const h = harness({ locale, scripts: [[init, 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(200);
    h.runner.cancel(); await settle(300);
    facts['stopped_' + locale] = card(p.pane());
    facts['toggle_' + locale] = [h.runner.text('toggleShow'), h.runner.text('toggleHide')];
    h.runner.stop();
  }
  // U8: a scanned PDF's card
  for (const locale of ['en-US', 'fr-FR', 'zh-CN']) {
    const h = harness({ locale, env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe', SKILL + '/SKILL.md', SCRIPT_PY], scripts: [],
                        scriptRuns: { status: [STATUS, 0], extract: ['{"error": "the PDF has no text layer"}', 3] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(600);
    facts['scanned_' + locale] = { card: card(p.pane()), text: h.runner.text('noTextLayer'), none: h.runner.text('annotNone') };
    h.runner.stop();
  }
  // U9: the tooltip once the plugin's status and extract are done and the agent starts
  {
    const h = harness({ env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe', SKILL + '/SKILL.md', SCRIPT_PY], scripts: [[init, 'WAIT']],
                        scriptRuns: { status: [STATUS, 0], extract: ['x', 0] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(600);
    facts.afterPreRun = { title: p.view().stateTitle, agent: h.log.calls.length };
    h.runner.cancel(); await settle(200);
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_ask_scholium_leaves_the_librarys_context_pane_closed(facts):
    assert facts["contextPane"] == {"collapsed": True, "others": 1}


def test_the_narrow_pane_wraps_the_confirmation_and_the_state_line():
    rules = css_rules()
    # the confirmation's two buttons go under its text together: first in the order of a row that runs from the right, on
    # its first line, which is the bottom one
    confirm = rules[".scholium-confirm"]
    assert "display: flex;" in confirm and "flex-direction: row-reverse;" in confirm and "flex-wrap: wrap-reverse;" in confirm
    assert "flex: 1 1 180px" in rules[".scholium-confirm-text"]
    assert rules[".scholium-confirm > .scholium-button"].strip() == "order: -1;"
    assert rules[".scholium-confirm > .scholium-button:last-child"].strip() == "order: -2;"
    assert "flex-wrap: wrap" in rules[".scholium-line"]
    state = rules[".scholium-line .scholium-state"]
    assert "flex-shrink: 0" in state and "max-width: 100%" in state and "text-overflow: ellipsis" in state


def test_the_send_hint_is_cut_with_its_whole_text_in_the_tooltip(facts):
    assert facts["hint"]["text"] and facts["hint"]["title"] == facts["hint"]["text"]
    hint = css_rules()[".scholium-hint"]
    assert "white-space: nowrap" in hint and "text-overflow: ellipsis" in hint and "overflow: hidden" in hint


def test_the_tooltips_time_is_in_the_languages_words(facts):
    t = facts["tooltip"]
    assert t["zh-CN"].endswith("· 已用 1 分 5 秒") and t["en-US"].endswith("· 1m 5s so far")
    assert t["de"].endswith("· bisher 1 Min. 5 Sek.") and t["ja-JP"].endswith("· 経過 1分5秒")


@pytest.mark.parametrize("locale, title", [("en-US", "Cancelled"), ("de", "Abgebrochen"), ("zh-CN", "已取消")])
def test_the_stopped_cards_title_is_a_sentences(facts, locale, title):
    assert facts["stopped_" + locale][0] == title


def test_the_eye_buttons_english_names_scholium(facts):
    assert facts["toggle_en-US"] == ["Show Scholium annotations", "Hide Scholium annotations"]


@pytest.mark.parametrize("locale, sep", [("en-US", ". "), ("fr-FR", ". "), ("zh-CN", "：")])
def test_a_scanned_pdfs_card_reads_as_its_message_without_a_row_of_zeros(facts, locale, sep):
    s = facts["scanned_" + locale]
    assert len(s["card"]) == 2, "the card contains only its title and time"
    assert s["card"][0] == s["none"] + sep + s["text"]
    assert re.search(r"\b\d{2}:\d{2}$", s["card"][1])


def test_the_agents_start_after_the_pre_run_is_not_extracting(facts):
    a = facts["afterPreRun"]
    assert a["agent"] == 1 and a["title"].startswith("第 2/4 步 通读论文 · 已用 ")
