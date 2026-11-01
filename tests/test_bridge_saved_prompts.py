"""The saved prompts above the chat's box: the built-in ones, a click that sends one as typed words are sent, their
editing in the row, deleting with Undo, and their order."""
import json

import pytest

from bridge_harness import NODE, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const items = pane => pane.saved.children.filter(c => c.className === 'scholium-saved-item');
  // the built-in four, shown on the chat tab only; an empty chat has nothing else
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const shown = { labels: items(pane).map(c => c.children[0].textContent), tips: items(pane).map(c => c.children[0].title),
                    tools: items(pane)[0].children.slice(1).map(labelOf), last: labelOf(pane.saved.children.at(-1)),
                    hidden: pane.saved.hidden, list: pane.list.children.map(c => c.className) };
    pane.tabAnnotate.click(); await settle(5);
    shown.onAnnot = pane.saved.hidden;
    pane.tabChat.click(); await settle(5);
    shown.backOnChat = pane.saved.hidden;
    facts.shown = shown;
  }
  // a click sends the prompt with the quote; the words typed in the box stay
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    h.selection('一段原文。', 3, '4')[0].click(); await settle(20);
    pane.input.type('还没写完的话');
    items(pane)[1].children[0].click(); await settle(300);
    const log = await h.runner.readLog('ATT1', pane.shownConv);
    facts.click = { stdin: h.log.stdin[0], box: pane.input.value, quote: pane.quote, turns: log.turns.map(t => t.user) };
  }
  // while the agent answers, a click queues the prompt as a typed follow-up is queued
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(200);
    items(pane)[2].children[0].click(); await settle(50);
    facts.busyClick = { queued: h.runner.queue.filter(j => j.qid).map(j => j.say), box: pane.input.value, calls: h.log.calls.length };
    h.runner.cancel(); await settle(800);   // the held run ends, so that the process can
  }
  // a list in the preference; one that cannot be read gives the built-in ones; English built-in ones
  {
    const saved = JSON.stringify([{ label: '局限', prompt: '这篇论文有哪些局限？' }, { label: '', prompt: '用一句话概括全文的核心贡献和结论' }]);
    const h = harness({ prefs: { 'extensions.scholium-bridge.savedPrompts': saved } });
    h.runner.start('x');
    const bad = harness({ prefs: { 'extensions.scholium-bridge.savedPrompts': '{not json' } });
    bad.runner.start('x');
    const en = harness({ locale: 'en-US' });
    en.runner.start('x');
    facts.stored = { list: h.runner.savedPrompts(), bad: bad.runner.savedPrompts().map(p => p.label),
                     en: en.runner.savedPrompts().map(p => [p.label, p.prompt]) };
  }
  // ✎ turns the row into a small editor with the label and the words; ✓ keeps them, ✕ and Esc leave the row as it was;
  // ＋ adds one at the end, named by its words when it has no label; Ctrl+Enter keeps it
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const editor = () => pane.saved.children[0];
    const fields = () => editor().children;
    items(pane)[1].children[1].click();                      // ✎ on 贡献
    const opened = { cls: editor().className, label: fields()[0].value, prompt: fields()[1].value,
                     placeholders: [fields()[0].placeholder, fields()[1].placeholder], tools: fields()[2].children.map(labelOf) };
    fields()[0].type('贡献点');
    fields()[1].type('列出主要贡献，每条一句。');
    fields()[2].children[1].click();                          // ✓
    const kept = { labels: items(pane).map(c => c.children[0].textContent), pref: h.store.get('extensions.scholium-bridge.savedPrompts') };
    items(pane)[0].children[1].click();
    fields()[1].type('不要的');
    key(fields()[1], { key: 'Escape' });
    const escaped = { labels: items(pane).map(c => c.children[0].textContent), tips: items(pane)[0].children[0].title };
    pane.saved.children.find(c => /glyph add/.test(c.className)).click();     // ＋
    const empty = { label: fields()[0].value, prompt: fields()[1].value, ok: fields()[2].children[1].disabled };
    fields()[1].type('这篇论文最值得复现的实验是哪一个？为什么？');
    const ready = fields()[2].children[1].disabled;
    const ctrlEnter = key(fields()[1], { key: 'Enter', ctrlKey: true });
    facts.editing = { opened, kept, escaped, empty, ready, ctrlEnter: ctrlEnter.defaultPrevented,
                      added: items(pane).map(c => [c.children[0].textContent, c.children[0].title]).at(-1),
                      count: items(pane).length };
  }
  // 🗑 deletes at once, with Undo for a few seconds; Undo puts it back where it was; a drag moves one onto another's place
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const labels = () => items(pane).map(c => c.children[0].textContent);
    items(pane)[1].children[2].click();                      // 🗑 贡献
    const strip = pane.saved.children.at(-1);
    const removed = { labels: labels(), strip: [strip.className, strip.children[0].textContent, labelOf(strip.children[1])] };
    strip.children[1].click();                                // 撤销
    const undone = labels();
    items(pane)[0].children[2].click();
    h.fire(); await settle(5);
    const expired = { labels: labels(), strip: pane.saved.children.some(c => c.className === 'scholium-undo') };
    items(pane)[0].fire('dragstart');
    items(pane)[2].fire('drop');
    const dragged = labels();
    const all = h.runner.savedPrompts().length;
    for (let i = 0; i < all; i++) items(pane)[0].children[2].click();
    facts.removing = { removed, undone, expired, dragged, none: { items: items(pane).length, last: labelOf(pane.saved.children.find(c => c.tagName === 'button')) } };
  }
  // keys pressed while an IME composes are the IME's: Esc and Ctrl+Enter do nothing then; a plain Esc still cancels and is not passed on
  {
    const h = harness({});
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    const editor = () => pane.saved.children[0];
    items(pane)[1].children[1].click();
    const field = editor().children[1];
    field.type('正在输入的');
    const esc = key(field, { key: 'Escape', isComposing: true });
    const enter = key(field, { key: 'Enter', ctrlKey: true, isComposing: true });
    const during = { open: editor().className, value: field.value, escStopped: esc.stopped, enterPrevented: enter.defaultPrevented,
                     pref: h.store.get('extensions.scholium-bridge.savedPrompts') || null };
    const plain = key(field, { key: 'Escape' });
    facts.composing = { during, plainStopped: plain.stopped, labels: items(pane).map(c => c.children[0].textContent) };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_built_in_prompts_sit_above_the_chat_box(facts):
    s = facts["shown"]
    assert s["labels"] == ["问题", "贡献", "方法", "实验"]
    assert s["tips"] == ["这篇论文要解决什么问题？", "主要贡献有哪几点？", "方法的核心思路是什么？", "实验用了哪些数据和对比方法？"]
    assert s["tools"] == ["编辑", "删除"] and s["last"] == "添加常用语句"
    assert s["hidden"] is False and s["onAnnot"] is True and s["backOnChat"] is False
    assert s["list"] == [], "no starters in an empty chat"


def test_a_click_sends_the_prompt_with_the_quote(facts):
    c = facts["click"]
    assert "主要贡献有哪几点？" in c["stdin"] and "一段原文。" in c["stdin"]
    assert c["box"] == "还没写完的话" and c["quote"] is None
    assert c["turns"] == ["主要贡献有哪几点？"]


def test_a_click_while_the_agent_answers_queues_the_prompt(facts):
    b = facts["busyClick"]
    assert b["queued"] == ["方法的核心思路是什么？"] and b["box"] == "" and b["calls"] == 1


def test_the_list_lives_in_a_preference(facts):
    s = facts["stored"]
    assert s["list"] == [{"label": "局限", "prompt": "这篇论文有哪些局限？"}, {"label": "用一句话概括全文的核心贡", "prompt": "用一句话概括全文的核心贡献和结论"}]
    assert s["bad"] == ["问题", "贡献", "方法", "实验"]
    assert s["en"][0] == ["Problem", "What problem does this paper address?"] and [l for l, _ in s["en"]] == ["Problem", "Contributions", "Method", "Experiments"]


def test_the_row_has_its_styles():
    rules = css_rules()
    assert "flex-wrap: wrap" in rules[".scholium-saved"]
    assert ".scholium-starters" not in rules and ".scholium-starter" not in rules
    assert "display: none" in rules[".scholium-saved-item .scholium-button.glyph"]
    assert any("display: inline-flex" in body for sel, body in rules.items() if ".scholium-saved-item:hover .scholium-button.glyph" in sel)


def test_a_saved_prompt_is_edited_in_the_row(facts):
    e = facts["editing"]
    assert e["opened"] == {"cls": "scholium-saved-editor", "label": "贡献", "prompt": "主要贡献有哪几点？",
                           "placeholders": ["名称", "提示词"], "tools": ["取消", "保存"]}
    assert e["kept"]["labels"] == ["问题", "贡献点", "方法", "实验"]
    assert json.loads(e["kept"]["pref"])[1] == {"label": "贡献点", "prompt": "列出主要贡献，每条一句。"}
    assert e["escaped"] == {"labels": ["问题", "贡献点", "方法", "实验"], "tips": "这篇论文要解决什么问题？"}
    assert e["empty"] == {"label": "", "prompt": "", "ok": True} and e["ready"] is False
    assert e["ctrlEnter"] is True and e["count"] == 5
    assert e["added"] == ["这篇论文最值得复现的实验", "这篇论文最值得复现的实验是哪一个？为什么？"]


def test_a_deleted_prompt_comes_back_with_undo_and_one_moves_by_dragging(facts):
    r = facts["removing"]
    assert r["removed"]["labels"] == ["问题", "方法", "实验"]
    assert r["removed"]["strip"] == ["scholium-undo", "已删除", "撤销"]
    assert r["undone"] == ["问题", "贡献", "方法", "实验"]
    assert r["expired"] == {"labels": ["贡献", "方法", "实验"], "strip": False}
    assert r["dragged"] == ["方法", "实验", "贡献"]
    assert r["none"] == {"items": 0, "last": "添加常用语句"}


def test_the_editor_has_its_styles():
    rules = css_rules()
    assert "flex-basis: 100%" in rules[".scholium-saved-editor"]
    assert "resize: vertical" in rules[".scholium-saved-prompt"]


def test_an_ime_composition_keeps_the_editor_open(facts):
    c = facts["composing"]
    assert c["during"] == {"open": "scholium-saved-editor", "value": "正在输入的", "escStopped": False,
                           "enterPrevented": False, "pref": None}
    assert c["plainStopped"] is True and c["labels"] == ["问题", "贡献", "方法", "实验"]
