"""The setup check of the settings page: Zotero's local API, Claude Code and Codex (signed in or not, and their skill),
and the Python Scholium finds with its PyMuPDF, a line each as its check ends; a button fixes what the plugin can fix
and checks again."""
import re
from pathlib import Path

import pytest

from plugin_harness import BOOTSTRAP, NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const PY = '/py/new/python.exe';
  const CACHE = '/home/u/.claude/plugins/cache';
  const SIGNED_IN = { 'account/read': () => ({ result: { account: { type: 'chatgpt', email: 'someone@example.com', planType: 'plus' }, requiresOpenaiAuth: true } }) };
  // everything there: the skill in Claude Code's folder, Codex's in the data directory, Python 3.12 with PyMuPDF on PATH
  const good = (extra = {}) => Object.assign({ env: { PATH: '/py/none;/py/new' }, present: [PY, '/home/u/.claude/skills/zotero-scholium/SKILL.md'],
                                               python: { [PY]: '3.12.1\n1.24.10\n' }, codex: { answers: SIGNED_IN } }, extra);
  const brief = lines => lines.map(l => [l.id, l.state, l.label, l.text].concat(l.action ? [l.action] : []));
  const carried = h => {
    h.zotero.HTTP = { request: async (method, url) => ({ response: new TextEncoder().encode('file ' + url.split('/zotero-scholium/')[1]).buffer }) };
  };
  // the check through the settings page's API: its lines as they came; `during` sees them while a check is held
  const check = async (h, during = null) => {
    const seen = [];
    const done = h.zotero.Scholium.setupCheck(l => seen.push(l));
    if (during) { await settle(800); await during(seen, h); }
    const returned = await done;
    return { lines: brief(seen), same: JSON.stringify(returned) === JSON.stringify(seen) };
  };
  const run = async (opts, during = null) => {
    const h = harness(opts);
    h.runner.start('x');
    const r = await check(h, during);
    r.kept = ['someone@example.com', 'org-1', 'subscriptionType'].some(s => JSON.stringify(h.runner).includes(s) || JSON.stringify(r.lines).includes(s));
    h.runner.stop();
    r.h = h;
    return r;
  };
  const of = (r, ...ids) => r.lines.filter(l => ids.includes(l[0]));

  {
    const r = await run(good());
    const sent = r.h.log.codexProcs.flatMap(p => p.sent).map(m => m.method).filter(m => typeof m === 'string');
    facts.allGood = { lines: r.lines, same: r.same, kept: r.kept, auth: r.h.log.authCalls.map(o => [o.command, o.arguments]),
                      py: r.h.log.pyCalls.map(o => [o.command, o.arguments]), sent, closed: r.h.log.codexProcs.map(p => p.killed),
                      live: r.h.live() };
  }
  facts.english = (await run(good({ locale: 'en-US' }))).lines;

  // the local API: off, with its button; the button turns it on
  {
    const h = harness(good({ prefs: { 'httpServer.localAPI.enabled': false } }));
    h.runner.start('x');
    const first = await check(h);
    const said = await h.zotero.Scholium.fix(first.lines[0][4]);
    const again = await check(h);
    facts.apiOff = { first: first.lines[0], said, on: h.store.get('httpServer.localAPI.enabled'), again: again.lines[0] };
    h.runner.stop();
  }

  // Claude Code
  for (const [name, opts] of [['claudeOut', { auth: 'out' }], ['claudeFails', { auth: 'fail' }], ['claudeMissing', { claudeExists: false }],
                              ['claudeGone', { prefs: { 'extensions.scholium.claudePath': '/nowhere/claude.exe' } }]]) {
    const r = await run(good(opts));
    facts[name] = { lines: of(r, 'claude', 'claudeSkill'), auth: r.h.log.authCalls.length, kept: r.kept };
  }
  {
    let during = null;
    const r = await run(good({ auth: 'HOLD' }), async (seen, h) => { during = { ids: seen.map(l => l.id), kills: h.log.checkKills }; h.fire(); });
    facts.claudeHeld = { during, lines: of(r, 'claude'), kills: r.h.log.checkKills, ids: r.lines.map(l => l[0]) };
  }

  // Codex
  const codexCases = {
    codexOut: { codex: { answers: { 'account/read': () => ({ result: { account: null, requiresOpenaiAuth: true } }) } } },
    codexOtherProvider: { codex: { answers: { 'account/read': () => ({ result: { account: null, requiresOpenaiAuth: false } }) } } },
    codexRefused: { codex: {} },
    codexNoSkill: { codex: { answers: SIGNED_IN, skillAt: null } },
    codexSkillOff: { codex: { answers: SIGNED_IN, skillOff: true } },
    codexConfig: { codex: { exitOn: 'initialize', stderr: 'Error: error loading config.toml: unknown field `foo` at line 3\n  |\n3 | foo = 1\n  | ^\n' } },
    codexNoStart: { codex: { startFails: 'Failed to execute program' } },
    codexMissing: { codex: { versions: {} } },
    codexGone: { prefs: { 'extensions.scholium.codexPath': '/nowhere/codex.exe' } },
  };
  for (const [name, opts] of Object.entries(codexCases)) {
    const r = await run(good(opts));
    facts[name] = { lines: of(r, 'codex', 'codexSkill'), servers: r.h.log.codexProcs.length, closed: r.h.log.codexProcs.every(p => p.killed),
                    after: r.lines.map(l => l[0]).slice(-2) };
  }
  {
    let during = null;
    const r = await run(good({ codex: { answers: { 'account/read': () => 'HOLD' } } }), async (seen, h) => { during = seen.map(l => l.id); h.fire(); });
    facts.codexHeld = { during, lines: of(r, 'codex', 'codexSkill'), closed: r.h.log.codexProcs.every(p => p.killed), kills: r.h.log.codexKills };
  }
  {
    const h = harness(good({ codex: { answers: SIGNED_IN, skillAt: null } }));
    carried(h);
    h.runner.start('x');
    const line = (await check(h)).lines.find(l => l[0] === 'codexSkill');
    const said = await h.zotero.Scholium.fix(line[4]);
    const written = Object.keys(h.log.writes).filter(k => k.startsWith('/home/u/.codex/skills/zotero-scholium/'));
    facts.codexInstall = { action: line[4], said, written: written.length, skill: h.log.writes['/home/u/.codex/skills/zotero-scholium/SKILL.md'] };
    h.runner.stop();
  }

  // Claude Code's skill: in its own folder, the data directory's project skills, a plugin of its cache, CLAUDE_CONFIG_DIR
  const skillCases = {
    userSkill: {},
    projectSkill: { present: [PY, '/data/.claude/skills/zotero-scholium/SKILL.md'] },
    pluginSkill: { present: [PY, CACHE + '/m/zotero-scholium/0.2.1/skills/zotero-scholium/SKILL.md'],
                   dirs: { [CACHE]: [CACHE + '/other', CACHE + '/m'], [CACHE + '/m']: [CACHE + '/m/zotero-scholium'],
                           [CACHE + '/m/zotero-scholium']: [CACHE + '/m/zotero-scholium/0.2.1'] } },
    shallowSkill: { present: [PY, CACHE + '/m/skills/zotero-scholium/SKILL.md'], dirs: { [CACHE]: [CACHE + '/m'], [CACHE + '/m']: [CACHE + '/m/skills'] } },
    configDirSkill: { env: { PATH: '/py/new', CLAUDE_CONFIG_DIR: '/cfg' }, present: [PY, '/cfg/skills/zotero-scholium/SKILL.md'] },
    noSkill: { present: [PY] },
  };
  for (const [name, opts] of Object.entries(skillCases)) facts[name] = of(await run(good(opts)), 'claudeSkill');
  {
    const h = harness(good({ present: [PY] }));
    carried(h);
    h.runner.start('x');
    const line = (await check(h)).lines.find(l => l[0] === 'claudeSkill');
    const said = await h.zotero.Scholium.fix(line[4]);
    const again = (await check(h)).lines.find(l => l[0] === 'claudeSkill');
    facts.claudeInstall = { action: line[4], said, skill: h.log.writes['/home/u/.claude/skills/zotero-scholium/SKILL.md'], again };
    h.runner.stop();
  }
  {
    const h = harness(good({ present: [PY] }));
    h.zotero.HTTP = { request: async () => { throw Error('NS_ERROR_FILE_NOT_FOUND'); } };
    h.runner.start('x');
    facts.notCarried = await h.zotero.Scholium.fix({ kind: 'skill', agent: 'claude' });
    h.runner.stop();
  }
  {
    const h = harness(good({ present: [PY], home: 'none' }));
    h.runner.start('x');
    facts.noHome = await h.zotero.Scholium.fix({ kind: 'skill', agent: 'claude' });
    h.runner.stop();
  }

  // Python and PyMuPDF
  const STORE = '/localappdata/Microsoft/WindowsApps';
  const pyCases = {
    noPython: { env: { PATH: '/py/none' } },
    oldPython: { env: { PATH: '/py/old' }, present: ['/py/old/python.exe'], python: { '/py/old/python.exe': '3.8.10\n' } },
    noPymupdf: { python: { [PY]: '3.11.4\n' } },
    bothFine: { python: { [PY]: '3.12.1\r\n1.24.10\r\n' } },
    silent: { python: {} },
    storeAlias: { env: { PATH: STORE + ';/apps/WindowsApps\\;/py/new' }, present: [STORE + '/python.exe', '/apps/WindowsApps\\/python.exe', PY] },
  };
  for (const [name, opts] of Object.entries(pyCases)) {
    const r = await run(good(opts));
    facts[name] = { lines: of(r, 'python', 'pymupdf'), calls: r.h.log.pyCalls.map(o => o.command) };
  }
  {
    let during = null;
    const r = await run(good({ python: { [PY]: 'HOLD' } }), async (seen, h) => { during = { ids: seen.map(l => l.id), kills: h.log.checkKills }; h.fire(); });
    facts.pythonHeld = { during, lines: of(r, 'python', 'pymupdf'), kills: r.h.log.checkKills };
  }

  // the settings page: settings.js on the page's markup, with the plugin's API
  const page = h => {
    const els = { 'scholium-check-run': new El('button'), 'scholium-check-lines': new El('vbox'),
                  'scholium-check-copy': Object.assign(new El('button'), { hidden: true }) };
    let onLoad = null;
    const document = { getElementById: id => els[id] || null, createXULElement: tag => new El(tag),
                       addEventListener: (t, f, capture) => { if (t === 'load' && capture) onLoad = f; } };
    const path = require('node:path');
    vm.runInNewContext(fs.readFileSync(path.join(path.dirname(process.argv[2]), 'settings.js'), 'utf8'),
                       { window: {}, document, Zotero: h.zotero, ChromeUtils: { importESModule: () => ({}) } });
    const run = els['scholium-check-run'], box = els['scholium-check-lines'];
    const wiredBefore = (run.listeners.command || []).length;
    onLoad({ target: { classList: { contains: c => c === 'scholium-settings' } } });
    return { run, wiredBefore, press: () => run.fire('command'), copy: els['scholium-check-copy'],
             rows: () => box.children.map(r => r.children.map(c => (c.tagName === 'button' ? '[' + c.getAttribute('label') + ']' : c.textContent))),
             button: label => box.children.find(r => r.children[1].textContent === label).children.find(c => c.tagName === 'button') };
  };
  {
    const py = { [PY]: 'HOLD' };
    const h = harness(good({ prefs: { 'httpServer.localAPI.enabled': false }, present: [PY], python: py }));
    carried(h);
    h.runner.start('x');
    const p = page(h);
    const out = { wiredBefore: p.wiredBefore, wired: (p.run.listeners.command || []).length };
    p.press(); await settle(800);
    out.running = { disabled: p.run.disabled, rows: p.rows() };
    py[PY] = '3.12.1\n1.24.10\n';
    h.fire(); await settle(300);
    out.ended = { disabled: p.run.disabled, rows: p.rows() };
    const calls = h.log.authCalls.length;
    p.press(); await settle(800);
    out.again = { disabled: p.run.disabled, rows: p.rows(), checks: h.log.authCalls.length - calls };
    p.button('本地 API').fire('command'); await settle(800);
    out.turnedOn = { on: h.store.get('httpServer.localAPI.enabled'), rows: p.rows(), checks: h.log.authCalls.length - calls };
    p.button('Claude Code 的技能').fire('command'); await settle(800);
    out.installed = { rows: p.rows(), checks: h.log.authCalls.length - calls, disabled: p.run.disabled };
    facts.page = out;
    h.runner.stop();
  }
  {
    const h = harness(good({ present: [PY] }));
    h.zotero.HTTP = { request: async () => { throw Error('NS_ERROR_FILE_NOT_FOUND'); } };
    h.runner.start('x');
    const p = page(h);
    p.press(); await settle(800);
    const calls = h.log.authCalls.length;
    p.button('Claude Code 的技能').fire('command'); await settle(300);
    facts.pageNotCarried = { row: p.rows().find(r => r[1] === 'Claude Code 的技能'), checks: h.log.authCalls.length - calls };
    p.copy.fire('command'); await settle(20);
    facts.pageNotCarried.copied = h.log.copied.slice();
    h.runner.stop();
  }
  // Copy: hidden until a check has ended and while one runs; then the lines shown, with the versions and the system
  for (const [name, locale, os] of [['copy', 'zh-CN', 'Windows 11 26200'], ['copyEnglish', 'en-US', null]]) {
    const py = { [PY]: 'HOLD' };
    const h = harness(good({ locale, present: [PY], python: py }));
    h.runner.start('x');
    h.runner.version = '0.2.2';
    h.zotero.version = '10.0.7';
    if (os) h.zotero.getOSVersion = async () => os;
    const p = page(h);
    const before = p.copy.hidden, wired = (p.copy.listeners.command || []).length;
    p.press(); await settle(800);
    const during = p.copy.hidden;
    py[PY] = '3.12.1\n1.24.10\n';
    h.fire(); await settle(300);
    const after = p.copy.hidden;
    p.copy.fire('command'); await settle(20);
    facts[name] = { before, wired, during, after, rows: p.rows(), copied: h.log.copied.slice() };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


CLAUDE = "/appdata/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
CODEX = "/localappdata/OpenAI/Codex/bin/h1/codex.exe"
PY = "/py/new/python.exe"
ON_PATH = "Scholium 找到的 Python，智能体的终端可能用另一个"
API_ON = "已打开，Scholium 通过它读取论文。"
API_OFF = "已关闭，Scholium 读不到论文：点“打开”，或在 设置 → 高级 里勾选“允许此计算机上的其他应用程序与 Zotero 通讯”。"
SKILL_MISSING = "未找到：点“安装”，或在终端运行 npx skills add weilr/zotero-scholium -g -y。"
INSTALL = {"label": "安装", "kind": "skill"}
USER_SKILL = ["claudeSkill", "ok", "Claude Code 的技能", "已找到：/home/u/.claude/skills/zotero-scholium"]
UV_WINDOWS = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
NO_UV = f"未找到。推荐安装：uv 会自行提供 Python 和 PyMuPDF。在终端运行 {UV_WINDOWS} 安装。"
CODEX_SKILL = ["codexSkill", "ok", "Codex 的技能", "已找到：/data/.agents/skills/zotero-scholium"]


def test_everything_there_is_a_tick_each_in_order(facts):
    a = facts["allGood"]
    assert a["lines"] == [
        ["localApi", "ok", "本地 API", API_ON],
        ["claude", "ok", "Claude Code", "已登录。"],
        USER_SKILL,
        ["codex", "ok", "Codex", "已登录。"],
        CODEX_SKILL,
        ["uv", "unknown", "uv", NO_UV],
        ["python", "ok", "Python", f"3.12.1：{PY}（{ON_PATH}）"],
        ["pymupdf", "ok", "PyMuPDF", "已安装 1.24.10"],
    ]
    assert a["same"] is True, "the lines streamed are the lines returned"
    assert a["live"] == [], "no timer left"


def test_the_check_asks_without_calling_a_model(facts):
    a = facts["allGood"]
    assert a["auth"] == [[CLAUDE, ["auth", "status"]]]
    [[program, args]] = a["py"]
    assert program == PY and args[0] == "-c" and "sys.version" in args[1] and "'pymupdf'" in args[1] and "'fitz'" in args[1]
    assert {"initialize", "account/read", "skills/list"} <= set(a["sent"])
    assert not [m for m in a["sent"] if m.startswith(("thread/", "turn/"))], "no thread, no turn"
    assert a["closed"] == [True], "the one Codex server is closed"


def test_only_loggedin_of_claudes_answer_is_read(facts):
    assert facts["allGood"]["kept"] is False and facts["claudeOut"]["kept"] is False


def test_english(facts):
    on_path = "the Python Scholium finds; an agent's shell may use another"
    assert facts["english"] == [
        ["localApi", "ok", "Local API", "On; Scholium reads papers through it."],
        ["claude", "ok", "Claude Code", "Signed in."],
        ["claudeSkill", "ok", "Claude Code's skill", "Found: /home/u/.claude/skills/zotero-scholium"],
        ["codex", "ok", "Codex", "Signed in."],
        ["codexSkill", "ok", "Codex's skill", "Found: /data/.agents/skills/zotero-scholium"],
        ["uv", "unknown", "uv", f"Not found. Recommended: uv provides Python and PyMuPDF by itself; install it with {UV_WINDOWS} in a terminal."],
        ["python", "ok", "Python", f"3.12.1 at {PY} ({on_path})"],
        ["pymupdf", "ok", "PyMuPDF", "Installed: 1.24.10"],
    ]


def test_the_local_api_off_has_a_button_that_turns_it_on(facts):
    a = facts["apiOff"]
    assert a["first"] == ["localApi", "bad", "本地 API", API_OFF, {"label": "打开", "kind": "localApi"}]
    assert a["said"] is None and a["on"] is True
    assert a["again"] == ["localApi", "ok", "本地 API", API_ON]


def test_claude_code_signed_out_or_not_answering(facts):
    assert facts["claudeOut"]["lines"] == [["claude", "bad", "Claude Code", "还没有登录：在终端运行 claude，按提示登录。"], USER_SKILL]
    assert facts["claudeFails"]["lines"] == [["claude", "unknown", "Claude Code", "登录状态未知（claude auth status 没有回答）。"], USER_SKILL]


def test_claude_code_not_found(facts):
    assert facts["claudeMissing"] == {"lines": [["claude", "bad", "Claude Code", "未找到：安装 Claude Code，或在上方指定它的程序。"]], "auth": 0,
                                      "kept": False}
    assert facts["claudeGone"]["lines"] == [["claude", "bad", "Claude Code", "上方指定的程序不存在：改正路径，或清空以自动查找。"]]


def test_claude_codes_answer_is_waited_for_and_killed(facts):
    c = facts["claudeHeld"]
    assert c["during"] == {"ids": ["localApi"], "kills": 0}, "the lines come as each check ends"
    assert c["lines"] == [["claude", "unknown", "Claude Code", "登录状态未知（claude auth status 没有回答）。"]]
    assert c["kills"] == 1
    assert c["ids"] == ["localApi", "claude", "claudeSkill", "codex", "codexSkill", "uv", "python", "pymupdf"], "the rest goes on"


def test_codex_signed_out_or_with_a_provider_of_its_own(facts):
    assert facts["codexOut"]["lines"] == [["codex", "bad", "Codex", "还没有登录：在终端运行 codex login。"], CODEX_SKILL]
    assert facts["codexOtherProvider"]["lines"] == [["codex", "ok", "Codex", "已登录。"], CODEX_SKILL]
    assert facts["codexRefused"]["lines"] == [["codex", "unknown", "Codex", "登录状态未知（unknown method account/read）。"], CODEX_SKILL]
    for name in ("codexOut", "codexOtherProvider", "codexRefused"):
        assert facts[name]["servers"] == 1 and facts[name]["closed"] is True, name


def test_codex_without_the_skill_has_the_install_button(facts):
    assert facts["codexNoSkill"]["lines"] == [["codex", "ok", "Codex", "已登录。"],
                                              ["codexSkill", "bad", "Codex 的技能", SKILL_MISSING, dict(INSTALL, agent="codex")]]
    assert facts["codexSkillOff"]["lines"][1] == ["codexSkill", "bad", "Codex 的技能", "Codex 里的 zotero-scholium 技能被停用了：请在 Codex 里重新启用它。"]
    i = facts["codexInstall"]
    assert i["action"] == dict(INSTALL, agent="codex") and i["said"] is None
    assert i["skill"] == "file SKILL.md" and i["written"] == len(skill_files())


def test_a_codex_server_that_fails_shows_its_first_line(facts):
    c = facts["codexConfig"]
    assert c["lines"] == [["codex", "bad", "Codex",
                           "出错：Codex app-server 已退出：Error: error loading config.toml: unknown field `foo` at line 3"]]
    assert c["servers"] == 1 and c["closed"] is True
    assert c["after"] == ["python", "pymupdf"], "no skill line, the rest goes on"
    assert facts["codexNoStart"]["lines"] == [["codex", "bad", "Codex", "出错：Failed to execute program"]]


def test_codex_not_found(facts):
    assert facts["codexMissing"]["lines"] == [["codex", "bad", "Codex", "未找到：安装 Codex，或在上方指定它的程序。"]]
    assert facts["codexMissing"]["servers"] == 0
    assert facts["codexGone"]["lines"] == [["codex", "bad", "Codex", "上方指定的程序不存在：改正路径，或清空以自动查找。"]]


def test_a_codex_server_that_does_not_answer_is_closed(facts):
    c = facts["codexHeld"]
    assert c["during"] == ["localApi", "claude", "claudeSkill"]
    assert c["lines"] == [["codex", "bad", "Codex", "出错：10 秒内没有回答"]]
    assert c["closed"] is True and c["kills"] >= 1


def test_claude_codes_skill_is_found_where_claude_code_finds_it(facts):
    assert facts["userSkill"] == [USER_SKILL]
    assert facts["projectSkill"] == [["claudeSkill", "ok", "Claude Code 的技能", "已找到：/data/.claude/skills/zotero-scholium"]]
    assert facts["pluginSkill"] == [["claudeSkill", "ok", "Claude Code 的技能",
                                     "已找到：/home/u/.claude/plugins/cache/m/zotero-scholium/0.2.1/skills/zotero-scholium"]]
    assert facts["configDirSkill"] == [["claudeSkill", "ok", "Claude Code 的技能", "已找到：/cfg/skills/zotero-scholium"]]
    missing = [["claudeSkill", "bad", "Claude Code 的技能", SKILL_MISSING, dict(INSTALL, agent="claude")]]
    assert facts["shallowSkill"] == missing, "plugins/cache/<marketplace>/<plugin>/<version> only"
    assert facts["noSkill"] == missing


def test_the_install_button_installs_the_skill_or_says_why_not(facts):
    i = facts["claudeInstall"]
    assert i["action"] == dict(INSTALL, agent="claude") and i["said"] is None and i["skill"] == "file SKILL.md"
    assert i["again"] == USER_SKILL
    assert facts["notCarried"] == "这份插件没有带技能：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装。"
    assert facts["noHome"] == "找不到用户目录，技能没有装上：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装。"


def test_python_and_pymupdf(facts):
    assert facts["noPython"] == {"lines": [["python", "bad", "Python", "Scholium 找不到 Python：安装 Python 3.9 或更高版本，"
                                                                    "再运行 pip install -U pymupdf（智能体的终端可能有另一个 Python）。"]], "calls": []}
    assert facts["oldPython"]["lines"] == [["python", "bad", "Python", f"3.8.10 太旧，需要 3.9 或更高版本：/py/old/python.exe（{ON_PATH}）"]]
    assert facts["noPymupdf"]["lines"] == [["python", "ok", "Python", f"3.11.4：{PY}（{ON_PATH}）"],
                                           ["pymupdf", "bad", "PyMuPDF", "未安装：在终端运行 pip install -U pymupdf。"]]
    assert facts["bothFine"]["lines"] == [["python", "ok", "Python", f"3.12.1：{PY}（{ON_PATH}）"], ["pymupdf", "ok", "PyMuPDF", "已安装 1.24.10"]]
    assert facts["silent"]["lines"] == [["python", "unknown", "Python", f"{PY} 没有报出版本（{ON_PATH}）"]]


def test_the_windows_store_alias_is_passed_over(facts):
    s = facts["storeAlias"]
    assert s["calls"] == [PY]
    assert s["lines"][0] == ["python", "ok", "Python", f"3.12.1：{PY}（{ON_PATH}）"]


def test_python_is_waited_for_and_killed(facts):
    p = facts["pythonHeld"]
    assert p["during"] == {"ids": ["localApi", "claude", "claudeSkill", "codex", "codexSkill", "uv"], "kills": 0}
    assert p["lines"] == [["python", "unknown", "Python", f"{PY} 没有报出版本（{ON_PATH}）"]]
    assert p["kills"] == 1


def test_the_settings_page_shows_the_lines_as_they_come(facts):
    p = facts["page"]
    assert p["wiredBefore"] == 0 and p["wired"] == 1, "wired once the markup is there"
    assert p["running"]["disabled"] is True
    assert p["running"]["rows"] == [
        ["✗", "本地 API", API_OFF, "[打开]"],
        ["✓", "Claude Code", "已登录。"],
        ["✗", "Claude Code 的技能", SKILL_MISSING, "[安装]"],
        ["✓", "Codex", "已登录。"],
        ["✓", "Codex 的技能", "已找到：/data/.agents/skills/zotero-scholium"],
        ["–", "uv", NO_UV],
    ]
    assert p["ended"]["disabled"] is False
    assert p["ended"]["rows"][6:] == [["–", "Python", f"{PY} 没有报出版本（{ON_PATH}）"]]
    a = p["again"]
    assert a["disabled"] is False and a["checks"] == 1 and len(a["rows"]) == 8, "a second press checks again in place of the lines"
    assert a["rows"][6:] == [["✓", "Python", f"3.12.1：{PY}（{ON_PATH}）"], ["✓", "PyMuPDF", "已安装 1.24.10"]]


def test_the_settings_pages_buttons_fix_and_check_again(facts):
    p = facts["page"]
    t = p["turnedOn"]
    assert t["on"] is True and t["checks"] == 2 and t["rows"][0] == ["✓", "本地 API", API_ON]
    i = p["installed"]
    assert i["checks"] == 3 and i["disabled"] is False
    assert i["rows"][2] == ["✓", "Claude Code 的技能", "已找到：/home/u/.claude/skills/zotero-scholium"]
    n = facts["pageNotCarried"]
    assert n["row"] == ["✗", "Claude Code 的技能", "这份插件没有带技能：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装。"], \
        "what kept it in place of the sentence, the button gone"
    assert n["checks"] == 0


def test_copy_gives_the_lines_shown_with_the_versions(facts):
    c = facts["copy"]
    assert c["wired"] == 1 and c["before"] is True and c["during"] is True and c["after"] is False
    lines = [f"{r[0]} {r[1]}: {r[2]}" for r in c["rows"]]
    assert c["copied"] == ["\n".join(["Scholium 0.2.2 · Zotero 10.0.7 · Windows 11 26200"] + lines)]
    assert lines[0] == "✓ 本地 API: " + API_ON and lines[5].startswith("– uv: ")
    e = facts["copyEnglish"]
    assert e["copied"][0].split("\n")[:2] == ["Scholium 0.2.2 · Zotero 10.0.7 · WINNT", "✓ Local API: " + e["rows"][0][2]], \
        "without Zotero.getOSVersion, the system's name"
    n = facts["pageNotCarried"]
    assert "✗ Claude Code 的技能: 这份插件没有带技能：" in n["copied"][0], "a line as it is shown after a button"


def test_the_settings_page_has_the_check():
    from plugin_harness import PLUGIN
    src = (PLUGIN / "settings.xhtml").read_text(encoding="utf8")
    assert '<button id="scholium-check-run" data-l10n-id="scholium-check-run"/>' in src and '<vbox id="scholium-check-lines"/>' in src
    zh = (PLUGIN / "locale/zh-CN/scholium.ftl").read_text(encoding="utf8")
    en = (PLUGIN / "locale/en-US/scholium.ftl").read_text(encoding="utf8")
    assert "scholium-check = 环境检查\n" in zh and "scholium-check-run =\n    .label = 检查\n" in zh
    assert "scholium-check = Setup check\n" in en and "scholium-check-run =\n    .label = Check\n" in en
    assert '<button id="scholium-check-copy" data-l10n-id="scholium-check-copy" hidden="true"/>' in src
    assert "scholium-check-copy =\n    .label = 复制\n" in zh and "scholium-check-copied =\n    .label = 已复制\n" in zh
    assert "scholium-check-copy =\n    .label = Copy\n" in en and "scholium-check-copied =\n    .label = Copied\n" in en


def skill_files():
    named = re.search(r"SKILL_FILES: \[(.*?)\]", Path(BOOTSTRAP).read_text(encoding="utf8"), re.S).group(1)
    return re.findall(r'"([^"]+)"', named)
