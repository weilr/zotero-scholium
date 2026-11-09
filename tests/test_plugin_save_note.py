"""Save as note: the conversation the Chat tab shows (or the session the Annotations tab shows) becomes a child note of
the paper, with a heading of the paper's title after a prefix (not the title alone, which the skill's reading notes
start with) and the date, each question with its quoted passage and each answer set
from its Markdown with the agent that gave it, tagged scholium-chat so that Annotate again and Delete leave it."""
import pytest

from plugin_harness import NODE, plugin_source, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const DIR = '/data/tmp/scholium/ATT1/conversations/';
const AT = new Date(2026, 10, 1, 12, 0).getTime();
const ANSWER = '## 要点\n\n- **方法**：见 [#12]，复杂度 $O(n^2)$\n- 链接 https://example.org/a\n\n$$\\int_0^1 x\\,dx < 1$$\n\n`code` & <b>';
// a turn of a chat log: the question with a quoted passage, then the answer
const turn = (n, agent, model, answer, quote = null, at = AT) => L({ type: 'scholium', subtype: 'run', agent, user: '问题' + n, at })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n + '\n第二行', question: true }, quote ? { quote } : {}))
  + L(Object.assign({ type: 'system', subtype: 'init', apiKeySource: 'none', model, session_id: 'S' + n }, agent === 'codex' ? { agent } : {}))
  + L({ type: 'assistant', session_id: 'S' + n, message: { content: [{ type: 'text', text: answer }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: answer, session_id: 'S' + n })
  + L({ type: 'scholium', subtype: 'time', at: at + 1000 });
// notes as Zotero makes them: saved ones in `saved`
const notes = (h, fails = false) => {
  const saved = [];
  h.zotero.Item = class {
    constructor(type) { this.itemType = type; this.tags = []; this.html = null; }
    setNote(html) { this.html = html; }
    setTags(tags) { this.tags = tags; }
    async saveTx() { if (fails) throw Error('database is locked'); this.id = 'NOTE' + (saved.length + 1); saved.push(this); return this.id; }
  };
  return saved;
};
const brief = n => ({ type: n.itemType, library: n.libraryID, parent: n.parentID === undefined ? null : n.parentID, tags: n.tags, html: n.html });
const menu = pane => { pane.more.click(); const items = pane.popover.node.children.map(c => [c.textContent, !!c.disabled]); return items; };
const choose = (pane, label) => { pane.popover.node.children.find(c => c.textContent === label).click(); };
(async () => {
  const facts = {};
  const conv = 'chat-20261101-120000';
  const logs = { [DIR + conv + '.jsonl']: turn(1, 'claude', 'claude-opus-5-5', ANSWER, { text: 'A <quoted> passage.', page: '3' })
                                          + turn(2, 'codex', 'gpt-6-astra', '第二个回答。', null, AT + 5000),
                 [DIR + 'index.json']: JSON.stringify({ chat: conv, titles: {}, annotation: {} }),
                 '/data/tmp/scholium/ATT1/sentences.json': JSON.stringify({ sentences: [{ id: 12, page: 4, para: 3, text: 'S.' }] }) };
  // the chat's conversation
  for (const locale of ['zh-CN', 'en-US']) {
    const h = harness({ locale, logs });
    const saved = notes(h);
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    const items = menu(pane);
    choose(pane, locale === 'zh-CN' ? '存为笔记' : 'Save as note'); await settle(60);
    facts['chat_' + locale] = { items, saved: saved.map(brief), selected: h.log.selected.slice(), notices: h.log.notices.map(n => n.lines),
                                popover: !!pane.popover };
    h.runner.stop();
  }
  // no conversation yet: the item is there, off
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    facts.empty = menu(p.pane());
    h.runner.stop();
  }
  // the Annotations tab: only while it shows a session; the session's note
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    const before = menu(pane);
    h.runner.closePopover(pane);
    p.annotate(); await settle(300);
    const saved = notes(h);
    const after = menu(pane);
    choose(pane, '存为笔记'); await settle(60);
    facts.annot = { before, after, saved: saved.map(brief) };
    h.runner.stop();
  }
  // a save that fails: nothing selected, the reason under the box
  {
    const h = harness({ logs });
    notes(h, true);
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    menu(pane); choose(pane, '存为笔记'); await settle(60);
    facts.failed = { hint: pane.hint.textContent, selected: h.log.selected.slice(), notices: h.log.notices.length };
    h.runner.stop();
  }
  // a group library the user cannot edit: no note
  {
    const gkey = 'ATT1_g777';
    const glogs = { [`/data/tmp/scholium/${gkey}/conversations/${conv}.jsonl`]: turn(1, 'claude', 'claude-opus-5-5', '回答'),
                    [`/data/tmp/scholium/${gkey}/conversations/index.json`]: JSON.stringify({ chat: conv, titles: {}, annotation: {} }) };
    const h = harness({ logs: glogs, groups: { 2: { groupID: 777, editable: false } } });
    const saved = notes(h);
    h.runner.start('x');
    const g = h.groupPaper(2);
    const p = await h.pane(g.item); await settle(60);
    const pane = p.pane();
    menu(pane); choose(pane, '存为笔记'); await settle(60);
    facts.readOnly = { saved: saved.length, hint: pane.hint.textContent, shown: pane.shownKey };
    h.runner.stop();
  }
  // a saved conversation is no note of the tool's: Annotate again keeps it
  {
    const h = harness({ notes: [['scholium-chat'], ['zotero-scholium']] });
    h.runner.start('x');
    facts.own = h.runner.ownNotes(h.item1).map(n => n.key);
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_chat_menu_saves_the_conversation_as_a_child_note(facts):
    f = facts["chat_zh-CN"]
    assert ["存为笔记", False] in f["items"] and f["popover"] is False
    [note] = f["saved"]
    assert {k: note[k] for k in ("type", "library", "parent", "tags")} == \
        {"type": "note", "library": 1, "parent": "ITEM1", "tags": [{"tag": "scholium-chat"}]}
    assert f["selected"] == ["NOTE1"], "the note is selected in the library, where it opens"
    assert f["notices"] == [["已存为这篇论文的笔记"]]


def test_the_notes_html(facts):
    html = facts["chat_zh-CN"]["saved"][0]["html"]
    assert html.startswith("<h1>Scholium 对话：Paper ITEM1</h1>\n<p>2026-11-01</p>")
    # the question with its quoted passage, escaped, and its line breaks
    assert "<blockquote><p>p.3 · A &lt;quoted&gt; passage.</p></blockquote>\n<p><strong>问：</strong> 问题1<br>第二行</p>" in html
    # the answer: who gave it, then its Markdown as the transcript sets it
    assert "<p><strong>答（Claude Code · Opus 5.5）：</strong></p>" in html
    assert "<h2>要点</h2>" in html and "<ul><li><strong>方法</strong>：见 [p.4]，复杂度 <span class=\"math\">$O(n^2)$</span></li>" in html
    assert '<li>链接 <a href="https://example.org/a">https://example.org/a</a></li></ul>' in html
    assert '<pre class="math">$$\\int_0^1 x\\,dx &lt; 1$$</pre>' in html
    assert "<p><code>code</code> &amp; &lt;b&gt;</p>" in html, "the answer's own tags stay text"
    assert "<p><strong>答（Codex · gpt-6-astra）：</strong></p>\n<p>第二个回答。</p>" in html
    assert "scholium-" not in html and "data-" not in html, "none of the transcript's own classes"


def test_english_labels(facts):
    f = facts["chat_en-US"]
    assert ["Save as note", False] in f["items"] and f["notices"] == [["Saved as a note of the paper"]]
    html = f["saved"][0]["html"]
    assert html.startswith("<h1>Scholium conversation: Paper ITEM1</h1>\n")
    assert "<p><strong>Question:</strong> 问题1<br>第二行</p>" in html and "<p><strong>Answer (Claude Code · Opus 5.5):</strong></p>" in html


def test_without_a_conversation_the_item_is_off(facts):
    assert ["存为笔记", True] in facts["empty"]


def test_the_annotations_tab_offers_it_for_a_session(facts):
    a = facts["annot"]
    assert all(text != "存为笔记" for text, _ in a["before"]), "no session shown: no item"
    assert ["存为笔记", False] in a["after"]
    [note] = a["saved"]
    assert note["parent"] == "ITEM1" and note["tags"] == [{"tag": "scholium-chat"}]
    assert "<p><strong>答（Claude Code · Opus 5.5）：</strong></p>" in note["html"]


def test_a_failed_save_says_why(facts):
    f = facts["failed"]
    assert f["hint"] == "没有存为笔记：database is locked" and f["selected"] == [] and f["notices"] == 0


def test_a_read_only_group_gets_no_note(facts):
    r = facts["readOnly"]
    assert r["shown"] == "ATT1_g777" and r["saved"] == 0 and r["hint"] == "你在这个群组里没有编辑权限，无法存为笔记。"


def test_a_saved_conversation_is_not_the_tools_note(facts):
    assert facts["own"] == ["N1"]
    source = plugin_source()
    assert 'NOTE_TAG: "scholium-chat"' in source and '"scholium-chat"' not in source.split("OWN_TAGS:")[1].split("\n")[0]
