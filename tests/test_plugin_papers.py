"""A question about several papers: Ask Scholium (N papers) in the items list's context menu for 2 to 8 papers or PDFs,
the first paper's Chat tab with the others as removable chips above its box, every paper's paper.json and a line of
them in the prompt, and the conversation, kept with the first paper, naming the others in its log for later turns."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const DIR = '/data/tmp/scholium/ATT1/conversations/';
// the items list's context menu of the main window, and its selection
const withMenu = h => {
  const win = h.zotero.getMainWindow();
  const popup = new El('menupopup');
  popup.id = 'zotero-itemmenu';
  win.document.documentElement.append(popup);
  let selected = [];
  win.ZoteroPane.getSelectedItems = () => selected;
  return { win, popup, select: items => { selected = items; }, item: () => popup.children.find(c => c.id === 'scholium-ask-papers') || null,
           show: () => { popup.fire('popupshowing', { target: popup }); const i = popup.children.find(c => c.id === 'scholium-ask-papers');
                         return i.hidden ? null : i.getAttribute('label'); } };
};
const chips = pane => (pane.papersBox.hidden ? null : pane.papersBox.children.map(c => textOf(c)));
const promptLines = text => String(text).split('\n').filter(l => /paper\.json|论文。|papers below/.test(l));
(async () => {
  const facts = {};
  // the menu item: shown for 2 to 8 papers or PDFs, with their number
  for (const locale of ['zh-CN', 'en-US']) {
    const h = harness({ locale });
    const m = withMenu(h);
    h.runner.start('x');
    const f = { one: (m.select([h.item1]), m.show()), two: (m.select([h.item1, h.item2]), m.show()),
                pdf: (m.select([h.item1, h.att2]), m.show()), note: (m.select([h.item1, h.note]), m.show()),
                nine: (m.select(Array(9).fill(h.item1)), m.show()), eight: (m.select(Array(8).fill(h.item1)), m.show()),
                listeners: (m.popup.listeners.popupshowing || []).length };
    h.runner.stop();
    f.stopped = { item: !!m.item(), listeners: (m.popup.listeners.popupshowing || []).length };
    facts['menu_' + locale] = f;
  }

  // two papers: the first one's Chat tab on a new conversation, the other as a chip; the question goes with both
  {
    const h = harness();
    const m = withMenu(h);
    h.runner.start('x');
    m.select([h.item1, h.item2]);
    m.show();
    m.item().fire('command'); await settle(40);
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    const f = { selected: h.log.selected.slice(), tab: pane.tab, others: pane.others, chips: chips(pane), focused: !!pane.input.focused };
    // the Annotations tab has no chips
    pane.tabAnnotate.click(); f.annotChips = chips(pane); pane.tabChat.click();
    pane.input.type('这两篇方法有什么不同？');
    pane.send.click(); await settle(400);
    const lines = convLines(h);
    f.first = { prompt: promptLines(h.log.stdin[0]), papersJson: JSON.parse(h.log.writes['/data/tmp/scholium/ATT2/paper.json'] || 'null'),
                own: JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/paper.json'] || 'null'),
                logged: lines.filter(l => l.subtype === 'prompt').map(l => l.papers || null), chips: chips(pane), convs: convs(h).length };
    // a later message of the conversation keeps them
    pane.input.type('哪篇更快？');
    pane.send.click(); await settle(400);
    f.second = { prompt: promptLines(h.log.stdin[1]), resumed: h.log.calls[1].opts.arguments.includes('--resume'),
                 logged: convLines(h).filter(l => l.subtype === 'prompt').map(l => l.papers || null), convs: convs(h).length };
    // the section drawn again shows the conversation's papers from its log
    const again = await h.pane(h.item1); await settle(60);
    f.redrawn = chips(again.pane());
    // ✕ leaves the paper out of the next messages, and the log says so
    const q = again.pane();
    q.papersBox.children[1].children.find(c => c.tagName === 'button').click();
    f.removed = { others: q.others, chips: chips(q) };
    q.input.type('只看第一篇。');
    q.send.click(); await settle(400);
    f.third = { prompt: promptLines(h.log.stdin[2]), logged: convLines(h).filter(l => l.subtype === 'prompt').map(l => l.papers || null) };
    const last = await h.pane(h.item1); await settle(60);
    f.afterRemoval = chips(last.pane());
    facts.ask = f;
    h.runner.stop();
  }

  // English prompt, and a paper whose PDF is gone is left out of it
  {
    const h = harness({ locale: 'en-US' });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    h.runner.takePapers(pane, [{ library: 1, key: 'ATT2', title: 'Paper ITEM2' }, { library: 1, key: 'ATT3', title: 'Second PDF' }], 'ATT1');
    h.att2.getFilePathAsync = async () => null;
    pane.input.type('Compare them.');
    pane.send.click(); await settle(400);
    facts.english = { prompt: promptLines(h.log.stdin[0]), chips: chips(pane) };
    h.runner.stop();
  }

  // the section drawn already in the window: it takes the papers at once; no paper with a PDF: a word says so
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    h.paneWin.ZoteroPane = { getSelectedItems: () => [], selectItem: async id => h.log.selected.push(id) };
    await h.runner.askPapers(h.paneWin, [h.item1, h.item2]);
    const pane = p.pane();
    facts.drawn = { chips: chips(pane), pending: h.runner.pendingPapers.size, tab: pane.tab };
    const none = await h.runner.askPapers(h.paneWin, [h.note]);
    facts.none = { returned: none, alerts: h.log.alerts.slice() };
    h.runner.stop();
  }
  // the citation format: one paper's question, and a question about two, in Chinese and in English
  for (const locale of ['zh-CN', 'en-US']) {
    const prompts = {};
    for (const both of [false, true]) {
      const h = harness({ locale });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      if (both) h.runner.takePapers(pane, [{ library: 1, key: 'ATT2', title: 'Paper ITEM2' }], 'ATT1');
      pane.input.type('Compare them.');
      pane.send.click(); await settle(400);
      prompts[both ? 'two' : 'one'] = String(h.log.stdin[0] || '').split('\n');
      h.runner.stop();
    }
    facts['cite_' + locale] = prompts;
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


@pytest.mark.parametrize("locale, two, eight", [("zh-CN", "问 Scholium（2 篇）", "问 Scholium（8 篇）"),
                                                ("en-US", "Ask Scholium (2 papers)", "Ask Scholium (8 papers)")])
def test_the_items_menu_offers_it_for_two_to_eight_papers(facts, locale, two, eight):
    f = facts["menu_" + locale]
    assert f["one"] is None and f["note"] is None and f["nine"] is None
    assert f["two"] == two and f["pdf"] == two and f["eight"] == eight
    assert f["listeners"] == 1 and f["stopped"] == {"item": False, "listeners": 0}


def test_the_first_papers_chat_opens_with_the_others_as_chips(facts):
    f = facts["ask"]
    assert f["selected"] == ["ITEM1"] and f["tab"] == "chat" and f["focused"] is True
    assert f["others"] == [{"library": 1, "key": "ATT2", "title": "Paper ITEM2"}]
    assert f["chips"] == ["同时问", "Paper ITEM2不问《Paper ITEM2》"] and f["annotChips"] is None


def test_the_question_goes_with_every_papers_paper_json(facts):
    first = facts["ask"]["first"]
    assert first["papersJson"] == {"pdf": "D:/Zotero/storage/ATT2/paper.pdf", "item_key": "ITEM2", "attachment_key": "ATT2",
                                   "out_dir": "/data/tmp/scholium/ATT2"}
    assert first["own"]["attachment_key"] == "ATT1"
    prompt = first["prompt"]
    assert any("同时涉及下面几篇论文" in l and "[#123] 只用于上面这篇" in l for l in prompt)
    assert "- /data/tmp/scholium/ATT2/paper.json（Paper ITEM2）" in prompt
    assert first["logged"] == [[{"library": 1, "key": "ATT2", "title": "Paper ITEM2"}]], "the log names the other papers"
    assert first["chips"] == ["同时问", "Paper ITEM2不问《Paper ITEM2》"] and first["convs"] == 1, "one conversation, the first paper's"


def test_later_messages_keep_the_papers(facts):
    s = facts["ask"]["second"]
    assert s["resumed"] is True and s["convs"] == 1
    assert "- /data/tmp/scholium/ATT2/paper.json（Paper ITEM2）" in s["prompt"]
    assert s["logged"][-1] == [{"library": 1, "key": "ATT2", "title": "Paper ITEM2"}]
    assert facts["ask"]["redrawn"] == ["同时问", "Paper ITEM2不问《Paper ITEM2》"], "the conversation shown again shows its papers"


def test_a_paper_left_out_stays_out(facts):
    f = facts["ask"]
    assert f["removed"] == {"others": [], "chips": None}
    assert f["third"]["prompt"] == [] and f["third"]["logged"][-1] == []
    assert f["afterRemoval"] is None


def test_english_and_a_paper_without_its_pdf(facts):
    e = facts["english"]
    assert any(l.startswith("The question is also about the papers below.") for l in e["prompt"])
    assert "- /data/tmp/scholium/ATT3/paper.json (Second PDF)" in e["prompt"]
    assert not any("ATT2" in l for l in e["prompt"]), "a paper whose PDF is gone is left out"
    assert e["chips"] == ["Also about", "Paper ITEM2Leave out “Paper ITEM2”", "Second PDFLeave out “Second PDF”"]


def test_a_section_drawn_already_takes_the_papers(facts):
    d = facts["drawn"]
    assert d["chips"] == ["同时问", "Paper ITEM2不问《Paper ITEM2》"] and d["pending"] == 0 and d["tab"] == "chat"
    assert facts["none"] == {"returned": False, "alerts": ["选中的论文在这台电脑上都没有 PDF 文件。"]}


OUT = "/data/tmp/scholium/ATT1"
EXTRACT = f"extract --config {OUT}/paper.json --sentences {OUT}/sentences.json --out {OUT}/sentences.txt"
CITE = {
    "zh-CN": {
        "one": f"引用论文原句时，在句末写它的句子编号，格式 [#123]（多句写 [#12][#15]）；编号来自 {EXTRACT}（已有就直接读 sentences.txt）。",
        "two": f"引用上面这篇论文的原句时，每次都在句末写它的句子编号，格式 [#123]（多句写 [#12][#15]），只有这种格式会显示为引用；"
               f"编号来自 {EXTRACT}（已有就直接读 sentences.txt）。",
        "papers": "句子编号 [#123] 只用于上面这篇，引用它的原句时每次都写成 [#123]，不要写成“第 29 句”；引用其他论文时写论文标题和页码"
                  "（可加“第 N 句”），不用 [#…]。",
    },
    "en-US": {
        "one": f"When you quote a sentence of the paper, put its sentence number after it as [#123] (several: [#12][#15]); the numbers come "
               f"from {EXTRACT} (read sentences.txt when it is there).",
        "two": f"When you quote a sentence of the paper above, always put its sentence number after it as [#123] (several: [#12][#15]); only "
               f"that form shows as a citation. The numbers come from {EXTRACT} (read sentences.txt when it is there).",
        "papers": "Sentence numbers [#123] are for the paper above only: quote its sentences with [#123] every time, never as “sentence 29”; "
                  "for the others, name the paper and the page (and, if you like, “sentence N”), without [#…].",
    },
}


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_a_question_about_several_papers_cites_the_first_papers_sentences_as_firmly(facts, locale):
    prompts, want = facts["cite_" + locale], CITE[locale]
    assert want["one"] in prompts["one"] and want["two"] not in prompts["one"], "one paper's question: as before"
    assert want["two"] in prompts["two"] and want["one"] not in prompts["two"]
    papers = [line for line in prompts["two"] if want["papers"] in line]
    assert len(papers) == 1 and papers[0].endswith(want["papers"])
