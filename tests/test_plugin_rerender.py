"""A section drawn again shows its paper's conversation and annotation session without an async render. Zotero keeps the
async render of a [tab, item] it did last and skips it when that item comes back after another item had only a sync render
(its section below the fold): the sync render loads them, once, and a load overtaken by a newer drawing writes nothing."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const cardOf = q => {
    const last = q.annot.list.children.at(-1);
    return !!(last && last.children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card')));
  };
  const shown = (h, body) => {
    const q = h.runner.panes.get(body);
    return { tab: q.tab, intro: q.annot.list.children.some(c => c.className === 'scholium-annot-intro'), card: cardOf(q),
             annotConv: !!q.annot.shownConv, chatConv: !!q.shownConv, chatEntries: q.list.children.length };
  };
  const sync = (h, body, item) => {
    const section = h.log.sections[0];
    section.onItemChange({ item, setEnabled() {} });
    section.onRender({ doc: h.paneDoc, body, item });
  };

  // an annotation's card, and a chat's transcript, come back with the paper after another item's sync render only
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(500);
    const first = shown(h, p.body);
    sync(h, p.body, h.item2); await settle(40);
    const other = shown(h, p.body);
    sync(h, p.body, h.item1); await settle(40);
    facts.annotation = { first, other, back: shown(h, p.body) };
    h.runner.stop();
  }
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    await h.runner.send(h.item1, '这篇的贡献是什么？'); await settle(500);
    const first = shown(h, p.body);
    sync(h, p.body, h.item2); await settle(40);
    sync(h, p.body, h.item1); await settle(40);
    facts.chat = { first, back: shown(h, p.body) };
    h.runner.stop();
  }
  // one load a drawing: the async render after the sync one waits for the load the sync one started, and a later async
  // render (the section scrolled into view) starts none
  {
    const h = harness();
    h.runner.start('x');
    let loads = 0;
    const real = h.runner.showConversation;
    h.runner.showConversation = function () { loads++; return real.apply(this, arguments); };
    const p = await h.pane(h.item1); await settle(40);
    const once = loads;
    await h.log.sections[0].onAsyncRender({ body: p.body }); await settle(20);
    const scrolled = loads;
    sync(h, p.body, h.item1); await settle(40);
    facts.loads = { once, scrolled, drawnAgain: loads };
    h.runner.stop();
  }
  // a load overtaken by a newer drawing writes nothing: the paper with a session drawn, then at once another item
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(500);
    sync(h, p.body, h.item2); await settle(40);
    sync(h, p.body, h.item1);
    const overtaken = h.runner.panes.get(p.body);
    sync(h, p.body, h.item2); await settle(60);
    facts.overtaken = { shown: shown(h, p.body), item: h.runner.panes.get(p.body).item === h.item2, replaced: h.runner.panes.get(p.body) !== overtaken };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_annotation_card_comes_back_without_an_async_render(facts):
    a = facts["annotation"]
    assert a["first"]["tab"] == "annotate" and a["first"]["card"] is True and a["first"]["intro"] is False
    assert a["other"]["card"] is False and a["other"]["annotConv"] is False, "the other item has no session"
    assert a["back"]["tab"] == "annotate" and a["back"]["card"] is True and a["back"]["intro"] is False and a["back"]["annotConv"] is True


def test_the_chat_comes_back_without_an_async_render(facts):
    c = facts["chat"]
    assert c["first"]["chatConv"] is True and c["first"]["chatEntries"] > 0
    assert c["back"]["chatConv"] is True and c["back"]["chatEntries"] == c["first"]["chatEntries"]


def test_one_load_a_drawing(facts):
    assert facts["loads"] == {"once": 1, "scrolled": 1, "drawnAgain": 2}


def test_a_load_overtaken_by_a_newer_drawing_writes_nothing(facts):
    o = facts["overtaken"]
    assert o["item"] is True and o["replaced"] is True
    assert o["shown"]["card"] is False and o["shown"]["annotConv"] is False and o["shown"]["chatConv"] is False
