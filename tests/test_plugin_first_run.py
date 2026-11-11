"""What a first run on a new computer meets: Zotero's local API turned off (one confirmation turns it on), the agent
not signed in, PyMuPDF or Python missing, a scanned PDF without a text layer. Each ends with what to do, in the
section's language."""
import json
from pathlib import Path

import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const init = ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: 'S1', skills: ['zotero-scholium'] });
  const ending = (text, error = false) => [said(text), ev({ type: 'result', subtype: 'success', is_error: error, result: text, session_id: 'S1', num_turns: 3 })];
  const card = p => {
    const c = p.pane().annot.list.children.at(-1).children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card'));
    return c ? { cls: c.className, title: c.children[0].textContent } : null;
  };

  // the local API turned off: asked once; declined, nothing starts; accepted, it is turned on and the run starts
  for (const [name, confirm] of [['apiDeclined', false], ['apiAccepted', true]]) {
    const h = harness({ prefs: { 'httpServer.localAPI.enabled': false }, confirm, script: SCRIPT.concat([LAST, RESULT]) });
    h.runner.start('x');
    const queued = await h.runner.annotate([h.item1]); await settle(300);
    const sent = await h.runner.send(h.item2, '这篇的贡献是什么？'); await settle(300);
    facts[name] = { queued, sent, confirms: h.log.confirms.slice(), runs: h.log.calls.length, on: h.store.get('httpServer.localAPI.enabled') };
    h.runner.stop();
  }
  {
    const h = harness({ script: SCRIPT.concat([LAST, RESULT]) });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(300);
    facts.apiOn = { confirms: h.log.confirms.length, runs: h.log.calls.length };
    h.runner.stop();
  }

  // Claude Code not signed in
  {
    const h = harness({ exitCode: 1, script: [init, ev({ type: 'assistant', error: 'authentication_failed', message: { content: [{ type: 'text', text: 'Not logged in · Please run /login' }] } }),
                                              ev({ type: 'result', subtype: 'success', is_error: true, result: 'Not logged in · Please run /login', session_id: 'S1' })] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(400);
    facts.claudeSignedOut = { shown: p.view('annotate').flat.filter(untimed).slice(-2), notice: h.log.notices.flatMap(n => n.descriptions).join(' | '),
                              retried: h.log.calls.length };
    h.runner.stop();
  }

  // Codex: no account although OpenAI's needs one; an account, or a provider of its own, goes on
  for (const [name, account] of [['codexSignedOut', { account: null, requiresOpenaiAuth: true }],
                                 ['codexOtherProvider', { account: null, requiresOpenaiAuth: false }],
                                 ['codexSignedIn', { account: { type: 'chatgpt', email: 'someone@example.com', planType: 'plus' }, requiresOpenaiAuth: true }]]) {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { answers: { 'account/read': () => ({ result: account }) } } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(600);
    const sent = h.log.codexProcs.flatMap(x => x.sent).map(m => m.method).filter(m => typeof m === 'string');
    facts[name] = { card: card(p), threads: sent.filter(m => m === 'thread/start').length, asked: sent.filter(m => m === 'account/read').length,
                    kept: JSON.stringify(h.runner).includes('someone@example.com') };
    h.runner.stop();
  }

  // PyMuPDF or Python missing: on the card of an annotation that wrote nothing, and as a failed run's message; the skill's
  // script running afterwards clears it
  const extract = 'python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json';
  const cases = {
    noPymupdf: [[tool('Bash', { command: extract }, 't1'), answer('PyMuPDF is not installed; run: pip install -U pymupdf', true, 't1')],
                'PyMuPDF 未安装，无法继续。\n高亮 0 条，剩余警告：缺少 PyMuPDF'],
    noPython: [[tool('Bash', { command: extract }, 't1'), answer('/usr/bin/bash: line 1: python: command not found', true, 't1')], '没有 Python。'],
    windowsAlias: [[tool('PowerShell', { command: extract }, 't1'), answer('Python was not found; run without arguments to install from the Microsoft Store', true, 't1')], 'x'],
    installed: [[tool('Bash', { command: extract }, 't1'), answer('PyMuPDF is not installed; run: pip install -U pymupdf', true, 't1'),
                 tool('Bash', { command: 'pip install -U pymupdf' }, 't2'), answer('Successfully installed pymupdf', false, 't2'),
                 tool('Bash', { command: extract }, 't3'), answer('412 sentences -> s.json', false, 't3')], '停在这里。'],
    pipOnly: [[tool('Bash', { command: extract }, 't1'), answer('PyMuPDF is not installed; run: pip install -U pymupdf', true, 't1'),
               tool('Bash', { command: 'pip install -U pymupdf' }, 't2'), answer('error: externally-managed-environment', true, 't2')], '装不上。'],
  };
  for (const [name, [steps, text]] of Object.entries(cases)) {
    const h = harness({ script: [init, ...steps, ...ending(text)] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(500);
    facts[name] = card(p);
    h.runner.stop();
  }
  {
    const h = harness({ exitCode: 1, script: [init, tool('Bash', { command: extract }, 't1'), answer('PyMuPDF is not installed; run: pip install -U pymupdf', true, 't1'),
                                              ...ending('Stopped: PyMuPDF missing', true)] });
    h.runner.start('x');
    await h.runner.send(h.item1, '这篇的方法是什么？'); await settle(500);
    facts.failedQuestion = h.log.notices.flatMap(n => n.descriptions).join(' | ');
    h.runner.stop();
  }
  {
    const h = harness({ locale: 'en-US', script: [init, tool('Bash', { command: extract }, 't1'), answer('PyMuPDF is not installed', true, 't1'), ...ending('Stopped.')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(500);
    facts.noPymupdfEnglish = card(p);
    h.runner.stop();
  }
  // a scanned PDF: extract's error (SCAN_OUT, the script's own) on the card of an annotation that wrote nothing
  for (const [name, locale] of [['scan', 'zh-CN'], ['scanEnglish', 'en-US']]) {
    const h = harness({ locale, script: [init, tool('Bash', { command: extract }, 't1'), answer('Exit code 3\n' + SCAN_OUT, true, 't1'),
                                         ...ending('Stopped: the PDF is a scan.')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(500);
    facts[name] = card(p);
    h.runner.stop();
  }
  {
    const h = harness({});
    const m = (c, o) => h.runner.missingAfter(c, o, null);
    facts.scanSeen = { codex: m('uv run C:/skills/scholium.py extract --config paper.json', SCAN_OUT),
                       source: m('Get-Content C:/skills/scholium.py', SOURCE), skill: m('cat C:/skills/SKILL.md', SKILL) };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    from zotero_scholium import cli
    out = json.dumps({"error": cli.NO_TEXT_LAYER, "pages": 4, "scanned_pages": 4}, ensure_ascii=False, indent=1)
    texts = {"SCAN_OUT": out, "SOURCE": (ROOT / "skills/zotero-scholium/scripts/scholium.py").read_text(encoding="utf8"),
             "SKILL": (ROOT / "skills/zotero-scholium/SKILL.md").read_text(encoding="utf8")}
    return run_scenarios("".join(f"const {k} = {json.dumps(v)};\n" for k, v in texts.items()) + SCENARIOS, tmp_path_factory)


API_OFF = ("Scholium 通过 Zotero 的本地 API 读取论文，它现在是关闭的（设置 → 高级 → 允许此计算机上的其他应用程序与 Zotero 通讯）。"
           "现在打开吗？")


def test_a_run_with_the_local_api_off_asks_to_turn_it_on(facts):
    d = facts["apiDeclined"]
    assert d["confirms"] == [API_OFF, API_OFF], "asked for the annotation and for the question"
    assert d["queued"] == 0 and d["sent"] is False and d["runs"] == 0 and d["on"] is False
    a = facts["apiAccepted"]
    assert a["confirms"] == [API_OFF], "asked once: the question finds it on"
    assert a["queued"] == 1 and a["sent"] is True and a["runs"] >= 1 and a["on"] is True


def test_a_run_with_the_local_api_on_asks_nothing(facts):
    assert facts["apiOn"] == {"confirms": 0, "runs": 1}


def test_claude_code_not_signed_in_says_how_to_sign_in(facts):
    s = facts["claudeSignedOut"]
    said = "Claude Code 还没有登录：在终端运行 claude，按提示登录后再试。"
    assert said in str(s["shown"][-1]) and "Please run /login" not in str(s["shown"]), "once, in the plugin's words"
    assert said in s["notice"]
    assert s["retried"] == 1, "no second try"


def test_codex_without_an_account_stops_before_its_thread(facts):
    s = facts["codexSignedOut"]
    assert s["asked"] == 1 and s["threads"] == 0
    assert "Codex 还没有登录：在终端运行 codex login，登录后再试。" in s["card"]["title"]
    for name in ("codexOtherProvider", "codexSignedIn"):
        assert facts[name]["threads"] == 1 and "还没有登录" not in (facts[name]["card"] or {}).get("title", ""), name
    assert facts["codexSignedIn"]["kept"] is False, "the account's details are not kept"


UV_WINDOWS = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
NO_PYMUPDF = f"缺少 PyMuPDF，安装 uv（在终端运行 {UV_WINDOWS}）或运行 pip install -U pymupdf 后再试。"


def test_missing_pymupdf_or_python_is_named_on_the_empty_card(facts):
    assert facts["noPymupdf"] == {"cls": "scholium-card none", "title": "没有写入批注：" + NO_PYMUPDF}
    assert facts["noPython"]["title"] == (f"没有写入批注：找不到 Python，安装 uv（在终端运行 {UV_WINDOWS}），"
                                          "或安装 Python 3.9 或更高版本并运行 pip install -U pymupdf 后再试。")
    assert facts["windowsAlias"]["title"] == facts["noPython"]["title"]
    assert facts["pipOnly"]["title"] == facts["noPymupdf"]["title"], "a failed pip install leaves it missing"
    assert facts["noPymupdfEnglish"]["title"] == (f"No annotations written: PyMuPDF is missing; install uv (run {UV_WINDOWS} in a terminal) "
                                                  "or run pip install -U pymupdf, then try again.")


def test_the_skills_script_running_afterwards_clears_it(facts):
    assert facts["installed"] == {"cls": "scholium-card none", "title": "没有写入批注"}


def test_a_failed_run_names_what_is_missing(facts):
    assert NO_PYMUPDF in facts["failedQuestion"]


def test_a_scanned_pdf_says_to_run_ocr_first(facts):
    assert facts["scan"] == {"cls": "scholium-card none", "title": "没有写入批注：这个 PDF 没有文字层（扫描件）：先做 OCR 文字识别"
                                                                  "（例如 ocrmypdf，或 Acrobat 的“识别文本”），再批注。"}
    assert facts["scanEnglish"]["title"] == ("No annotations written. The PDF has no text layer (a scanned document): run OCR on it "
                                             "first (e.g. ocrmypdf, or Acrobat's Recognize Text), then annotate again.")
    assert facts["scanSeen"] == {"codex": "noTextLayer", "source": None, "skill": None}, "only extract's error, not the words in the script or the skill"
