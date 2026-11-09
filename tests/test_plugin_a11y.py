"""Accessibility and appearance of the section, the profile sheet and the setup check: the sheet keeps the keyboard, the
settings layer starts at the model, the setup check gives the focus back after an action, every symbol button has a
name, the tabs and the menus answer the arrow keys, History is an icon, and the colours of text and marks are readable
in the light and the dark theme."""
import re

import pytest

from plugin_harness import NODE, PLUGIN, css_rules, plugin_source, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const DIR = '/data/tmp/scholium/ATT1/conversations/';
const turn = (n, at) => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at })
  + L({ type: 'scholium', subtype: 'prompt', text: '问题' + n, question: true })
  + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S' + n })
  + L({ type: 'assistant', session_id: 'S' + n, message: { content: [{ type: 'text', text: '回答' + n }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: 'S' + n })
  + L({ type: 'scholium', subtype: 'time', at: at + 1 });
// the focus as a window gives it: the element focused last is the document's active element
let focusDoc = null;
El.prototype.focus = function () { if (focusDoc) focusDoc.activeElement = this; this.focused = true; };
const keyClick = el => el.fire('click', { detail: 0 });
// a key the window hears first (the profile sheet's listener on the window)
const winKey = (h, opts) => {
  const e = Object.assign({ defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} }, opts);
  for (const f of (h.paneWin.listeners.keydown || []).slice()) f(e);
  return e;
};
(async () => {
  const facts = {};

  // the profile sheet: modal, Tab and Shift+Tab go round it, Esc at the window closes it, the focus goes back to ⋯
  {
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, confirm: [true] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const pane = p.pane();
    const doc = h.paneDoc;
    focusDoc = doc;
    profileFrom(pane); await settle(20);
    const box = h.sheet().children[0];
    const [, panes, foot] = box.children;
    const [input] = panes.children;
    const [, , cancel, save] = foot.children;
    const name = n => (n === input ? 'input' : n === cancel ? 'cancel' : n === save ? 'save' : n === pane.more ? 'more' : 'other');
    const f = { modal: box.getAttribute('aria-modal'), role: box.getAttribute('role'), opened: name(doc.activeElement),
                winKeys: (h.paneWin.listeners.keydown || []).length };
    // Save is off until a change: Cancel is the last control
    doc.activeElement = cancel;
    let k = key(box, { key: 'Tab' });
    f.wrap = { to: name(doc.activeElement), prevented: k.defaultPrevented };
    k = key(box, { key: 'Tab', shiftKey: true });
    f.back = { to: name(doc.activeElement), prevented: k.defaultPrevented };
    doc.activeElement = input;
    k = key(box, { key: 'Tab' });
    f.between = { to: name(doc.activeElement), prevented: k.defaultPrevented };
    input.type(input.value + '- x\n');
    doc.activeElement = save;
    key(box, { key: 'Tab' });
    f.fromSave = name(doc.activeElement);
    // the focus outside the sheet (a click on its backdrop): Tab at the window goes into it, Shift+Tab to its last control
    doc.activeElement = doc.documentElement;
    winKey(h, { key: 'Tab' });
    f.outside = name(doc.activeElement);
    doc.activeElement = doc.documentElement;
    winKey(h, { key: 'Tab', shiftKey: true });
    f.outsideBack = name(doc.activeElement);
    doc.activeElement = doc.documentElement;
    k = winKey(h, { key: 'Escape' });
    f.esc = { open: !!h.sheet(), prevented: k.defaultPrevented, confirms: h.log.confirms.length, focus: name(doc.activeElement),
              winKeys: (h.paneWin.listeners.keydown || []).length };
    facts.sheet = f;
    focusDoc = null;
    h.runner.stop();
  }

  // the settings layer from the keyboard: the model takes the focus; the tabs; the ⋯ menu and the history
  {
    const conv1 = 'chat-20261101-120000', conv2 = 'chat-20261102-120000';
    const h = harness({ logs: { [DIR + conv1 + '.jsonl']: turn(1, 1000), [DIR + conv2 + '.jsonl']: turn(2, 2000),
                                [DIR + 'index.json']: JSON.stringify({ chat: conv2, titles: {}, annotation: {} }) } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(60);
    const pane = p.pane();
    const doc = h.paneDoc;
    focusDoc = doc;
    const f = {};
    pane.chip.focus(); keyClick(pane.chip);
    f.settings = { model: doc.activeElement === pane.model, agent: doc.activeElement === pane.agent };
    key(pane.popover.node, { key: 'Escape' });
    // the tabs: ← → Home End choose a tab and take the focus to it; only the chosen one is reached by Tab
    const t = () => [pane.tab, pane.tabChat.getAttribute('tabindex'), pane.tabAnnotate.getAttribute('tabindex'),
                     doc.activeElement === pane.tabChat ? 'chat' : doc.activeElement === pane.tabAnnotate ? 'annotate' : null];
    f.tabs = { first: t() };
    pane.tabChat.focus();
    let k = key(pane.tabChat, { key: 'ArrowRight' });
    f.tabs.right = t().concat([k.defaultPrevented]);
    key(pane.tabAnnotate, { key: 'ArrowLeft' }); f.tabs.left = t();
    key(pane.tabChat, { key: 'End' }); f.tabs.end = t();
    key(pane.tabAnnotate, { key: 'Home' }); f.tabs.home = t();
    k = key(pane.tabChat, { key: 'ArrowDown' }); f.tabs.down = [pane.tab, k.defaultPrevented];
    // the ⋯ menu: ↓ ↑ Home End go among its items, past the disabled ones, round from the last to the first
    pane.more.focus(); keyClick(pane.more);
    const node = pane.popover.node;
    const at = () => doc.activeElement.textContent;
    f.menu = { role: node.getAttribute('role'), items: node.children.filter(c => c.className === 'scholium-menu-item').map(c => [c.getAttribute('role'), c.textContent, !!c.disabled]),
               first: at() };
    f.menu.downs = [];
    for (let i = 0; i < f.menu.items.filter(i => !i[2]).length; i++) { key(node, { key: 'ArrowDown' }); f.menu.downs.push(at()); }
    key(node, { key: 'ArrowUp' }); f.menu.up = at();
    key(node, { key: 'End' }); f.menu.end = at();
    key(node, { key: 'Home' }); f.menu.home = at();
    key(node, { key: 'Escape' });
    f.menu.back = !pane.popover && doc.activeElement === pane.more;
    // the history: ↓ ↑ from row to row, from a row's buttons too
    pane.historyButton.focus(); keyClick(pane.historyButton); await settle(30);
    const hist = pane.popover.node;
    const rows = hist.children.filter(c => /^scholium-history-row/.test(c.className));
    const which = () => rows.findIndex(r => r.contains(doc.activeElement));
    const part = () => (doc.activeElement.className || '').replace('scholium-', '');
    f.history = { rows: rows.length, first: [which(), part()] };
    key(hist, { key: 'ArrowDown' }); f.history.down = [which(), part()];
    doc.activeElement = rows[1].children.find(c => /glyph trash/.test(c.className));
    key(hist, { key: 'ArrowUp' }); f.history.fromTrash = [which(), part()];
    key(hist, { key: 'End' }); f.history.end = [which(), part()];
    // the rename box keeps its arrow keys
    rows[0].children.find(c => /glyph edit/.test(c.className)).click(); await settle(5);
    const input = rows[0].children[0];
    const kept = key(hist, { key: 'ArrowDown', target: input });
    f.history.renameKeeps = !kept.defaultPrevented;
    focusDoc = null;
    facts.keys = f;
    h.runner.stop();
  }

  // the names of the symbol buttons: ⋯, ↑ and ■, a queued message's ⋯; History is an icon
  {
    for (const locale of ['zh-CN', 'en-US']) {
      const h = harness({ locale });
      h.runner.start('x');
      const p = await h.pane(h.item1); await settle(40);
      const pane = p.pane();
      const f = { more: [pane.more.textContent, pane.more.getAttribute('aria-label'), pane.more.title, pane.more.getAttribute('aria-haspopup')] };
      pane.input.type('问题');
      f.send = [pane.send.textContent, pane.send.getAttribute('aria-label'), pane.send.title];
      pane.input.type('');
      pane.busy = true;
      h.runner.paintSend(pane);
      f.stop = [pane.send.textContent, pane.send.getAttribute('aria-label'), pane.send.title];
      pane.input.type('/compact');
      h.runner.paintSend(pane);
      f.queue = [pane.send.getAttribute('aria-label'), pane.send.title];
      pane.busy = false;
      const row = h.runner.queuedRow(pane, { qid: 'q1', say: '下一个问题', agent: 'claude', att: h.att1, kind: 'chat' });
      const last = row.children.at(-1);
      f.queued = [last.textContent, last.getAttribute('aria-label'), last.title];
      f.history = [pane.historyButton.className, pane.historyButton.textContent, pane.historyButton.getAttribute('aria-label'), pane.historyButton.title];
      facts['names_' + locale] = f;
      h.runner.stop();
    }
  }

  // the setup check: the focus after a line's button, the marks' colours in each theme, the rows with a button centred
  {
    const PY = '/py/new/python.exe';
    const SIGNED_IN = { 'account/read': () => ({ result: { account: { type: 'chatgpt', email: 'someone@example.com', planType: 'plus' }, requiresOpenaiAuth: true } }) };
    const good = (extra = {}) => Object.assign({ env: { PATH: '/py/none;/py/new' }, present: [PY, '/home/u/.claude/skills/zotero-scholium/SKILL.md'],
                                                 python: { [PY]: '3.12.1\n1.24.10\n' }, codex: { answers: SIGNED_IN } }, extra);
    // the settings page, with the window's dark-theme query when `dark` is given ({ matches })
    const page = (h, dark = null) => {
      const els = { 'scholium-check-run': new El('button'), 'scholium-check-lines': new El('vbox'),
                    'scholium-check-copy': Object.assign(new El('button'), { hidden: true }) };
      let onLoad = null;
      const document = { getElementById: id => els[id] || null, createXULElement: tag => new El(tag),
                         addEventListener: (t, f, capture) => { if (t === 'load' && capture) onLoad = f; } };
      const window = dark ? { matchMedia: q => (q === '(prefers-color-scheme: dark)' ? dark : null) } : {};
      const path = require('node:path');
      vm.runInNewContext(fs.readFileSync(path.join(path.dirname(process.argv[2]), 'settings.js'), 'utf8'),
                         { window, document, Zotero: h.zotero, ChromeUtils: { importESModule: () => ({}) } });
      onLoad({ target: { classList: { contains: c => c === 'scholium-settings' } } });
      const run = els['scholium-check-run'], box = els['scholium-check-lines'];
      const row = label => box.children.find(r => r.children[1].textContent === label);
      return { run, box, press: () => run.fire('command'), row,
               button: label => row(label).children.find(c => c.tagName === 'button') };
    };
    const off = { prefs: { 'httpServer.localAPI.enabled': false } };
    const out = {};
    // the action done, the line without its button now: Check takes the focus
    {
      const h = harness(good(off));
      h.runner.start('x');
      const p = page(h);
      p.press(); await settle(800);
      out.align = { api: p.row('本地 API').getAttribute('align'), python: p.row('Python').getAttribute('align') };
      p.button('本地 API').fire('command'); await settle(800);
      out.done = { run: !!p.run.focused, button: !!p.button('本地 API') };
      h.runner.stop();
    }
    // the action done, the line still with its button: that button takes the focus
    {
      const h = harness(good(off));
      h.runner.start('x');
      const p = page(h);
      p.press(); await settle(800);
      h.zotero.Scholium.fix = async () => null;
      const before = p.button('本地 API');
      before.fire('command'); await settle(800);
      const again = p.button('本地 API');
      out.again = { same: again === before, focused: !!(again && again.focused), run: !!p.run.focused };
      h.runner.stop();
    }
    // the action not done: its reason in place of the sentence, the button gone, Check takes the focus
    {
      const h = harness(good(off));
      h.runner.start('x');
      const p = page(h);
      p.press(); await settle(800);
      h.zotero.Scholium.fix = async () => 'not now';
      p.button('本地 API').fire('command'); await settle(100);
      out.refused = { run: !!p.run.focused, button: !!p.button('本地 API'), text: p.row('本地 API').children[2].textContent };
      h.runner.stop();
    }
    // the marks: light by default, dark when the window says so, painted again when the theme changes
    {
      const h = harness(good(off));
      h.runner.start('x');
      let changed = null;
      const dark = { matches: true, addEventListener: (t, f) => { if (t === 'change') changed = f; } };
      const p = page(h, dark);
      p.press(); await settle(800);
      const colour = label => /color: ([^;]+)/.exec(p.row(label).children[0].getAttribute('style'))[1];
      out.dark = { ok: colour('Python'), bad: colour('本地 API') };
      dark.matches = false; changed();
      out.light = { ok: colour('Python'), bad: colour('本地 API') };
      h.runner.stop();
    }
    facts.check = out;
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_profile_sheet_keeps_the_keyboard(facts):
    f = facts["sheet"]
    assert (f["modal"], f["role"], f["opened"], f["winKeys"]) == ("true", "dialog", "input", 1)
    assert f["wrap"] == {"to": "input", "prevented": True}, "Tab from the last control goes to the first"
    assert f["back"] == {"to": "cancel", "prevented": True}, "Shift+Tab from the first goes to the last"
    assert f["between"] == {"to": "input", "prevented": False}, "in between, the window moves the focus"
    assert f["fromSave"] == "input", "Save, on after a change, is the last control"
    assert (f["outside"], f["outsideBack"]) == ("input", "save")
    assert f["esc"] == {"open": False, "prevented": True, "confirms": 1, "focus": "more", "winKeys": 0}, \
        "Esc at the window asks for the change and closes the sheet; ⋯ gets the focus back"


def test_the_keyboard_in_the_layers_and_the_tabs(facts):
    k = facts["keys"]
    assert k["settings"] == {"model": True, "agent": False}
    t = k["tabs"]
    assert t["first"] == ["chat", "0", "-1", None]
    assert t["right"] == ["annotate", "-1", "0", "annotate", True]
    assert t["left"] == ["chat", "0", "-1", "chat"]
    assert t["end"] == ["annotate", "-1", "0", "annotate"] and t["home"] == ["chat", "0", "-1", "chat"]
    assert t["down"] == ["chat", False]
    m = k["menu"]
    assert m["role"] == "menu" and all(r == "menuitem" for r, _, _ in m["items"])
    enabled = [text for _, text, off in m["items"] if not off]
    assert len(enabled) >= 3 and m["first"] == enabled[0]
    assert m["downs"] == enabled[1:] + enabled[:1], "↓ goes through the items and from the last to the first"
    assert m["up"] == enabled[-1] and m["end"] == enabled[-1] and m["home"] == enabled[0]
    assert m["back"] is True
    h = k["history"]
    assert h["rows"] == 2 and h["first"] == [0, "history-open"] and h["down"] == [1, "history-open"]
    assert h["fromTrash"] == [0, "history-open"] and h["end"] == [1, "history-open"]
    assert h["renameKeeps"] is True


@pytest.mark.parametrize("locale, more, send, stop, queue, history", [
    ("zh-CN", "更多", "发送", "停止", "排队", "历史"),
    ("en-US", "More", "Send", "Stop", "Queue", "History")])
def test_every_symbol_button_has_a_name(facts, locale, more, send, stop, queue, history):
    f = facts["names_" + locale]
    assert f["more"] == ["⋯", more, more, "menu"]
    assert f["send"] == ["↑", send, send] and f["stop"] == ["■", stop, stop]
    assert f["queue"][0] == queue, "a message while the paper runs is queued: the button's name says so"
    assert f["queued"] == ["⋯", more, more]
    assert f["history"] == ["scholium-button quiet glyph history", "", history, history]


def test_history_is_a_monochrome_icon():
    svg = (PLUGIN / "content" / "history16.svg").read_text(encoding="utf8")
    assert 'viewBox="0 0 16 16"' in svg and 'stroke="context-stroke"' in svg and "fill=\"none\"" in svg
    assert 'url("history16.svg")' in css_rules()[".glyph.history .scholium-glyph"]
    assert "🕘" not in plugin_source()


def test_the_setup_check_gives_the_focus_back(facts):
    c = facts["check"]
    assert c["align"] == {"api": "center", "python": "baseline"}, "a line with a button is centred on it"
    assert c["done"] == {"run": True, "button": False}
    assert c["again"] == {"same": False, "focused": True, "run": False}
    assert c["refused"] == {"run": True, "button": False, "text": "not now"}


def test_the_setup_checks_marks_follow_the_theme(facts):
    c = facts["check"]
    assert c["dark"] == {"ok": "#4cd27f", "bad": "#ff7b84"} and c["light"] == {"ok": "#1d8746", "bad": "#c42131"}


def _luminance(colour):
    rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


LIGHT = ["#ffffff", "#f2f2f2"]          # the pane's and the settings' grounds in the light theme
DARK = ["#1e1e1e", "#2b2b2b", "#303030"]


def test_text_colours_are_readable_in_both_themes():
    css = re.sub(r"/\*.*?\*/", "", (PLUGIN / "content" / "scholium.css").read_text(encoding="utf8"), flags=re.S)
    light = dict(re.findall(r"(--scholium-[\w-]+): (#[0-9a-f]{6})", re.search(r"^:root \{(.*?)\}", css, re.S | re.M).group(1)))
    dark_block = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root \{(.*?)\}", css, re.S).group(1)
    dark = dict(re.findall(r"(--scholium-[\w-]+): (#[0-9a-f]{6})", dark_block))
    assert set(light) == set(dark) == {"--scholium-blue-text", "--scholium-orange-text", "--scholium-red-text"}
    for name in light:
        assert min(_contrast(light[name], g) for g in LIGHT) >= 4.5, name
        assert min(_contrast(dark[name], g) for g in DARK) >= 4.5, name
    rules = css_rules()
    assert "var(--scholium-blue-text)" in rules[".scholium-tab.on"], "the active tab's words and underline"
    assert "var(--scholium-orange-text)" in rules[".scholium-card.none .scholium-card-title"]
    assert "color: var(--scholium-red-text)" in rules[".scholium-card.failed"]
    assert "var(--fill-secondary)" in rules[".scholium-meta"] and "var(--fill-secondary)" in rules[".scholium-queued-handle"]
    assert "light-dark(" not in css, "Firefox 115 has no light-dark()"


def test_the_setup_check_marks_are_readable_in_both_themes():
    js = (PLUGIN / "settings.js").read_text(encoding="utf8")
    m = re.search(r'light: \{ ok: "(#\w{6})", bad: "(#\w{6})" \}, dark: \{ ok: "(#\w{6})", bad: "(#\w{6})" \}', js)
    for colour in m.group(1, 2):
        assert min(_contrast(colour, g) for g in LIGHT) >= 3, colour
    for colour in m.group(3, 4):
        assert min(_contrast(colour, g) for g in DARK) >= 3, colour


def test_a_failed_card_has_its_buttons_side_by_side():
    rules = css_rules()
    card = rules[".scholium-card.failed"]
    assert "flex-direction: row" in card and "flex-wrap: wrap" in card and "align-items: center" in card
    assert "flex-basis: 100%" in rules[".scholium-card.failed > :not(.scholium-button)"], "the reason has a line of its own"
