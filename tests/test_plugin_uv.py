"""uv and the agent's PATH: on macOS and Linux the login shell's PATH, read once a session, goes before Zotero's in the
agent's process and in the search for its programs; uv's folders are added when they are missing. The setup check has a
uv line, with which a missing Python or PyMuPDF is no fault; a run that met no uv says how to install it; the skill's
commands are recognised when uv runs them. The script carries the inline metadata uv reads."""
import re
import sys
from pathlib import Path

import pytest

from plugin_harness import NODE, run_scenarios

ROOT = Path(__file__).resolve().parents[1]

SCENARIOS = r"""
(async () => {
  const facts = {};
  const NVM = '/home/u/.nvm/versions/node/v22/bin';
  const LOGIN = '/opt/homebrew/bin:/usr/bin:' + NVM + ':/usr/bin/';
  // what an interactive login shell prints: its startup files' words around the marked PATH
  const SAID = 'Last login: Mon Nov  9 on ttys001\nwelcome\n@SCHOLIUM_PATH@' + LOGIN + '@SCHOLIUM_PATH@\n';
  const ZOTERO_PATH = '/usr/bin:/bin:/usr/sbin:/sbin';
  const mac = (extra = {}) => Object.assign({ os: 'Darwin', env: { SHELL: '/bin/zsh', PATH: ZOTERO_PATH }, present: ['/bin/zsh'], shell: SAID,
                                              claudeAt: '/opt/homebrew/bin/claude' }, extra);
  const shells = h => h.log.shellCalls.map(o => [o.command, o.arguments]);
  const brief = lines => lines.map(l => [l.id, l.state, l.label, l.text]);
  const check = async h => brief(await h.zotero.Scholium.setupCheck(() => {}));
  const of = (lines, ...ids) => lines.filter(l => ids.includes(l[0]));

  // macOS: two runs, the shell asked once; uv's folder that is there is added, the one that is not is left out
  {
    const h = harness(mac({ present: ['/bin/zsh', '/home/u/.local/bin'] }));
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(300);
    await h.runner.annotate([h.item2]); await settle(300);
    facts.macRuns = { shells: shells(h), envs: h.log.calls.map(c => c.opts.environment), append: h.log.calls.map(c => c.opts.environmentAppend) };
    h.runner.stop();
  }
  // Codex's server gets the same PATH
  {
    const h = harness(mac({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { versions: { '/opt/homebrew/bin/codex': 'codex-cli 0.170.0' } } }));
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(600);
    facts.macCodex = { shells: h.log.shellCalls.length, env: h.log.codexCalls.map(o => o.environment), append: h.log.codexCalls.map(o => o.environmentAppend) };
    h.runner.stop();
  }
  // Codex's process: uv's cache and Pythons inside its sandbox's writable root, unless the user set where they go; Claude
  // Code's keeps uv's defaults
  for (const [name, env] of [['codexUv', { PATH: '/w/bin' }], ['codexUvSet', { PATH: '/w/bin', UV_CACHE_DIR: 'D:/mine/uv' }]]) {
    const h = harness({ env, prefs: { 'extensions.scholium.agent': 'codex' } });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(600);
    facts[name] = { codex: h.log.codexCalls.map(o => o.environment), claude: (await h.runner.agentEnv()).environment, root: h.runner.codexRoots()[0] };
    h.runner.stop();
  }
  // which shell: $SHELL, else /bin/zsh; none there, nothing started
  for (const [name, env, present] of [['noShellVar', { PATH: ZOTERO_PATH }, ['/bin/zsh']],
                                      ['relativeShell', { SHELL: 'zsh', PATH: ZOTERO_PATH }, ['/bin/zsh']],
                                      ['fish', { SHELL: '/usr/local/bin/fish', PATH: ZOTERO_PATH }, ['/bin/zsh', '/usr/local/bin/fish']],
                                      ['noShell', { SHELL: '/nowhere/zsh', PATH: ZOTERO_PATH }, []]]) {
    const h = harness(mac({ env, present }));
    const got = await h.runner.agentEnv();
    facts[name] = { shells: shells(h), env: got.environment };
  }
  // a shell that does not answer is killed after LOGIN_PATH_MS, and Zotero's PATH is kept; it is not asked again
  {
    const h = harness(mac({ shell: 'HOLD' }));
    const pending = h.runner.agentEnv();
    await settle(60);
    const during = { calls: h.log.shellCalls.length, kills: h.log.shellKills, timers: h.live() };
    h.fire();
    const got = await pending;
    const again = await h.runner.agentEnv();
    facts.held = { during, kills: h.log.shellKills, env: got.environment, again: again.environment, calls: h.log.shellCalls.length, ms: h.runner.LOGIN_PATH_MS };
  }
  // a shell whose output never ends, not even when it is killed (a child its startup files started holds it): after
  // LOGIN_PATH_MS it is killed and Zotero's PATH is used; a run started meanwhile goes on then, and ■ meanwhile stops it
  {
    const h = harness(mac({ shell: 'OPEN' }));
    let got = null;
    h.runner.agentEnv().then(e => { got = e; });
    await settle(60);
    const during = { got: !!got, timers: h.live() };
    h.fire(); await settle(60);
    let again = null;
    h.runner.agentEnv().then(e => { again = e; });
    await settle(20);
    facts.open = { during, env: got && got.environment, again: again && again.environment, kills: h.log.shellKills, calls: h.log.shellCalls.length,
                   timers: h.live() };
  }
  {
    const h = harness(mac({ shell: 'OPEN' }));
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(100);
    const before = { calls: h.log.calls.length, job: !!h.runner.job };
    h.fire(); await settle(300);
    facts.openRun = { before, envs: h.log.calls.map(c => c.opts.environment), kills: h.log.shellKills };
    h.runner.stop();
  }
  {
    const h = harness(mac({ shell: 'OPEN' }));
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(100);
    const stopped = h.runner.cancel();
    h.fire(); await settle(300);
    facts.openStop = { stopped, job: !!h.runner.job, calls: h.log.calls.length, killed: h.log.kills, queue: h.runner.queue.length };
    h.runner.stop();
  }
  // its marked PATH came and its output stays open: the PATH is used at once, and the shell is not killed
  {
    const h = harness(mac({ shell: { open: SAID } }));
    let got = null;
    h.runner.agentEnv().then(e => { got = e; });
    await settle(60);
    facts.openSaid = { env: got && got.environment, kills: h.log.shellKills, timers: h.live() };
  }
  // a Codex copy whose --version never ends is left out after 15 s; the others are compared
  {
    const h = harness({ codex: { versions: Object.assign({}, CODEX_VERSIONS, { [CODEX_APP]: 'OPEN' }) } });
    let found;
    h.runner.findCodex().then(p => { found = p; });
    await settle(100);
    const during = { found, timers: h.live() };
    h.fire(); await settle(100);
    facts.codexOpen = { during, found, timers: h.live() };
  }
  // a shell that does not start, or prints no marked PATH, or one of relative folders: ignored, and not asked again
  for (const [name, shell] of [['notStarted', { fails: 'NS_ERROR_FILE_ACCESS_DENIED' }], ['noMarks', 'zsh: no such option: foo\n'],
                               ['relative', '@SCHOLIUM_PATH@bin:.@SCHOLIUM_PATH@'], ['failing', null]]) {
    const h = harness(mac({ shell }));
    const logged = [];
    const realLog = h.runner.log.bind(h.runner);
    h.runner.log = m => { logged.push(String(m)); return realLog(m); };
    const first = await h.runner.agentEnv();
    const second = await h.runner.agentEnv();
    facts[name] = { env: first.environment, same: JSON.stringify(first) === JSON.stringify(second), calls: h.log.shellCalls.length,
                    logged: logged.filter(m => m.includes('login PATH')) };
  }
  // Linux reads it as macOS does; Windows starts no shell
  {
    const h = harness(mac({ os: 'Linux' }));
    facts.linux = { env: (await h.runner.agentEnv()).environment, shells: shells(h) };
  }
  {
    const h = harness({ env: { SHELL: '/bin/zsh', PATH: '/w/bin' }, present: ['/bin/zsh'] });
    facts.windows = { env: (await h.runner.agentEnv()).environment, shells: h.log.shellCalls.length };
  }
  // Windows: %USERPROFILE%\.local\bin added when it is there and missing, under the name the environment gives PATH
  {
    const h = harness({ env: { PATH: '/w/bin' }, present: ['/home/u/.local/bin'] });
    const upper = (await h.runner.agentEnv()).environment;
    h.runner.subprocess().getEnvironment = () => ({ Path: '/w/bin', OTHER: 'x' });
    const mixed = (await h.runner.agentEnv()).environment;
    const h2 = harness({ env: { PATH: '/w/bin;/HOME/u/.LOCAL/bin\\' }, present: ['/home/u/.local/bin'] });
    facts.windowsLocalBin = { upper, mixed, already: (await h2.runner.agentEnv()).environment };
  }

  // programs looked for on the agent's PATH: nvm's claude and codex, Homebrew's python3, uv in ~/.local/bin
  {
    const h = harness(mac({ claudeExists: false, present: ['/bin/zsh', NVM + '/claude', NVM + '/codex', '/opt/homebrew/bin/python3', '/usr/bin/python3'],
                            codex: { versions: { [NVM + '/codex']: 'codex-cli 0.170.0' } } }));
    facts.found = { claude: await h.runner.findClaude(), codex: await h.runner.findCodex(), python: await h.runner.pathPython(),
                    shells: h.log.shellCalls.length };
  }

  // the setup check's uv line on each system, and Python and PyMuPDF with uv
  const UV = '/home/u/.local/bin/uv';
  const UV_SAID = 'uv 0.13.7 (316c827e0 2026-11-03 aarch64-apple-darwin)\n';
  for (const [name, opts] of Object.entries({
    macMissing: mac({ present: ['/bin/zsh', '/opt/homebrew/bin/python3'], python: { '/opt/homebrew/bin/python3': '3.12.1\n1.24.10\n' } }),
    macMissingEnglish: mac({ locale: 'en-US', present: ['/bin/zsh', '/opt/homebrew/bin/python3'], python: { '/opt/homebrew/bin/python3': '3.12.1\n1.24.10\n' } }),
    linuxMissing: mac({ os: 'Linux', present: ['/bin/zsh'] }),
    linuxMissingEnglish: mac({ os: 'Linux', locale: 'en-US', present: ['/bin/zsh'] }),
    macFound: mac({ present: ['/bin/zsh', '/home/u/.local/bin', UV, '/opt/homebrew/bin/python3'], uv: { [UV]: UV_SAID },
                    python: { '/opt/homebrew/bin/python3': '3.12.1\n1.24.10\n' } }),
    uvNoPython: mac({ present: ['/bin/zsh', '/home/u/.local/bin', UV], uv: { [UV]: UV_SAID } }),
    uvNoPythonEnglish: mac({ locale: 'en-US', present: ['/bin/zsh', '/home/u/.local/bin', UV], uv: { [UV]: UV_SAID } }),
    uvOldPython: mac({ present: ['/bin/zsh', '/home/u/.local/bin', UV, '/usr/bin/python3'], uv: { [UV]: UV_SAID }, python: { '/usr/bin/python3': '3.8.10\n' } }),
    uvNoPymupdf: { env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe', '/w/bin/python.exe'],
                   uv: { '/w/bin/uv.exe': 'uv 0.13.7 (316c827e0 2026-11-03 x86_64-pc-windows-msvc)\n' }, python: { '/w/bin/python.exe': '3.12.1\n' } },
    uvNoPymupdfEnglish: { locale: 'en-US', env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe', '/w/bin/python.exe'],
                          uv: { '/w/bin/uv.exe': 'uv 0.13.7 (316c827e0 2026-11-03 x86_64-pc-windows-msvc)\n' }, python: { '/w/bin/python.exe': '3.12.1\n' } },
    uvSilent: { env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe'] },
    windowsLocalBin: { env: { PATH: '/w/bin' }, present: ['/home/u/.local/bin', '/home/u/.local/bin/uv.exe'],
                       uv: { '/home/u/.local/bin/uv.exe': 'uv 0.13.7 (316c827e0 2026-11-03 x86_64-pc-windows-msvc)\n' } },
  })) {
    const h = harness(opts);
    h.runner.start('x');
    const lines = await check(h);
    facts['check_' + name] = { lines: of(lines, 'uv', 'python', 'pymupdf'), ids: lines.map(l => l[0]),
                               uvCalls: h.log.uvCalls.map(o => [o.command, o.arguments, (o.environment || {}).PATH || null]) };
    h.runner.stop();
  }

  // what a run that met no uv says, and the texts with the installer of each system
  {
    const h = harness({});
    const m = (c, o, b = null) => h.runner.missingAfter(c, o, b);
    const UVX = 'uv run C:/skills/scholium.py status ITEM1';
    facts.missingAfter = {
      bash: m(UVX, '/usr/bin/bash: line 1: uv: command not found'), zsh: m(UVX, 'zsh: command not found: uv'), sh: m(UVX, 'sh: 1: uv: not found'),
      fish: m(UVX, 'fish: Unknown command: uv'),
      pwsh: m(UVX, "uv: The term 'uv' is not recognized as a name of a cmdlet, function, script file, or executable program."),
      cmd: m(UVX, "'uv' is not recognized as an internal or external command,\noperable program or batch file."),
      zshPython: m('python3 C:/skills/scholium.py status ITEM1', 'zsh: command not found: python3'),
      both: m('uv run C:/skills/scholium.py status ITEM1 || python C:/skills/scholium.py status ITEM1', 'bash: uv: command not found\nbash: python: command not found'),
      pythonLater: m('python C:/skills/scholium.py status ITEM1', '{"items": []}', 'noUv'),
      uvx: m('uvx ruff', 'bash: uvx: command not found', null),
      uvRuns: m(UVX, 'Installed 1 package in 38ms\n{"items": []}', 'noUv'),
    };
    const texts = () => ({ noUv: h.runner.text('noUv'), noPython: h.runner.text('noPython'), pymupdf: h.runner.text('pymupdfMissing') });
    facts.windowsTexts = texts();
    h.zotero.locale = 'en-US';
    facts.windowsTextsEnglish = texts();
    const hm = harness(mac({ locale: 'en-US' }));
    facts.macTextsEnglish = { noUv: hm.runner.text('noUv'), noPython: hm.runner.text('noPython') };
  }
  const init = ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: 'S1', skills: ['zotero-scholium'] });
  const ending = text => [said(text), ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: 'S1', num_turns: 3 })];
  const card = p => {
    const c = p.pane().annot.list.children.at(-1).children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card'));
    return c ? { cls: c.className, title: c.children[0].textContent } : null;
  };
  const UV_EXTRACT = 'uv run C:/skills/scholium.py extract --pdf x.pdf --sentences s.json';
  const PY_EXTRACT = 'python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json';
  for (const [name, steps] of Object.entries({
    noUv: [tool('Bash', { command: UV_EXTRACT }, 't1'), answer('/usr/bin/bash: line 1: uv: command not found', true, 't1')],
    pythonAfter: [tool('Bash', { command: UV_EXTRACT }, 't1'), answer('/usr/bin/bash: line 1: uv: command not found', true, 't1'),
                  tool('Bash', { command: PY_EXTRACT }, 't2'), answer('412 sentences -> s.json', false, 't2')],
    neither: [tool('Bash', { command: UV_EXTRACT }, 't1'), answer('/usr/bin/bash: line 1: uv: command not found', true, 't1'),
              tool('Bash', { command: PY_EXTRACT }, 't2'), answer('/usr/bin/bash: line 1: python: command not found', true, 't2')],
  })) {
    const h = harness({ script: [init, ...steps, ...ending('停在这里。')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(500);
    facts['card_' + name] = card(p);
    h.runner.stop();
  }

  // how the script runs here: the annotation's and a question's prompts say uv run when uv is on the agent's PATH, else
  // the Python found there (python when there is none); found by files on the PATH, with no process
  const answered = ev({ type: 'result', subtype: 'success', is_error: false, result: 'ok', session_id: 'S2' });
  for (const [name, opts] of Object.entries({
    runUv: { env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe', '/w/bin/python.exe'] },
    runPython: { env: { PATH: '/w/bin' }, present: ['/w/bin/python.exe'] },
    runNone: { env: { PATH: '/w/bin' } },
    runUvEnglish: { locale: 'en-US', env: { PATH: '/w/bin' }, present: ['/w/bin/uv.exe'] },
    runPythonEnglish: { locale: 'en-US', env: { PATH: '/w/bin' }, present: ['/w/bin/python.exe'] },
    runMac: mac({ present: ['/bin/zsh', '/opt/homebrew/bin/python3'] }),
  })) {
    const h = harness(Object.assign({ scripts: [[init, ...ending('完成。')], [init, answered]] }, opts));
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    pane.annotGo.click(); await settle(600);
    pane.tabChat.click(); await settle(10);
    pane.input.type('What is new here?'); pane.send.click(); await settle(400);
    facts[name] = { prompts: h.log.stdin.slice(0, 2), processes: h.log.uvCalls.length + h.log.pyCalls.length };
    h.runner.stop();
  }

  // one turn's output in an annotation's Claude Code runs: capped unless the user's environment sets it; a question's
  // runs and Codex are left as they are
  const cap = o => (o.environment || {}).CLAUDE_CODE_MAX_OUTPUT_TOKENS || null;
  for (const [name, opts] of Object.entries({ capClaude: {}, capUserSet: { env: { CLAUDE_CODE_MAX_OUTPUT_TOKENS: '64000' } } })) {
    const h = harness(Object.assign({ scripts: [[init, ...ending('完成。')], [init, ...ending('改好了。')], [init, answered]] }, opts));
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const pane = p.pane();
    pane.tabAnnotate.click(); await settle(10);
    pane.annotGo.click(); await settle(600);
    pane.input.type('第 5 页那条译文改短'); pane.send.click(); await settle(400);   // words to the annotation's session
    pane.tabChat.click(); await settle(10);
    pane.input.type('What is new here?'); pane.send.click(); await settle(400);
    facts[name] = { caps: h.log.calls.map(c => cap(c.opts)), resumed: h.log.calls.map(c => c.opts.arguments.includes('--resume')) };
    h.runner.stop();
  }
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' } });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(600);
    facts.capCodex = h.log.codexCalls.map(cap);
    h.runner.stop();
  }

  // the skill's commands as uv runs them
  {
    const h = harness({});
    const s = c => h.runner.commandStep(c);
    facts.steps = {
      extract: s('uv run C:/skills/scholium.py extract --pdf x.pdf --sentences s.json'),
      extractQuoted: s('uv run "C:/skills/scholium.py" extract --config paper.json'),
      dryRun: s('uv run C:/skills/scholium.py --config c.json'),
      dryRunEquals: s('uv run /s/scholium.py --config=c.json'),
      apply: s('uv run C:/skills/scholium.py --config c.json --apply'),
      list: s('uv run C:/skills/scholium.py --config c.json --list'),
      status: s('uv run C:/skills/scholium.py status ITEM1'),
      uvConfigFile: s('uv run --config-file uv.toml C:/skills/scholium.py status ITEM1'),
      uvConfigFileDryRun: s('uv run --config-file uv.toml C:/skills/scholium.py --config c.json'),
      statusConfig: s('python C:/skills/scholium.py status K9AVSL6I --config C:/o/paper.json'),
      samplesConfig: s('uv run C:/skills/scholium.py samples --exclude K9AVSL6I --config c.json'),
      profileConfig: s('python "C:/skills/scholium.py" profile --from-library --config c.json'),
      extractConfig: s('python C:/skills/scholium.py extract --config C:/o/paper.json --sentences s.json'),
    };
    facts.applied = {
      quoted: h.runner.appliedConfig('uv run /s/scholium.py --config "/o/my config.json" --apply'),
      afterUvOption: h.runner.appliedConfig('uv run --config-file uv.toml /s/scholium.py --config c.json --apply'),
      dryRun: h.runner.appliedConfig('uv run /s/scholium.py --config c.json'),
    };
    facts.claudeStep = h.runner.step(JSON.parse(tool('Bash', { command: 'uv run /s/scholium.py --config c.json --apply' })));
    facts.codexStep = h.runner.codexStep({ method: 'item/started', params: { item: { type: 'commandExecution',
      command: `"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command 'uv run C:/skills/scholium.py extract --pdf x.pdf'` } } });
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""

UV_WINDOWS = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
UV_UNIX = "curl -LsSf https://astral.sh/uv/install.sh | sh"
NVM = "/home/u/.nvm/versions/node/v22/bin"
MERGED = f"/opt/homebrew/bin:/usr/bin:{NVM}:/bin:/usr/sbin:/sbin"
PLAIN = {"PYTHONIOENCODING": "utf-8", "SCHOLIUM_ZOTERO_PORT": "23119"}
RUN_KEYS = ("SCHOLIUM_PLUGIN_RUN", "SCHOLIUM_HELD_BACK", "SCHOLIUM_CONFIRMED")


def base(env):
    """An agent's environment without what a run adds for the skill's script (test_plugin_confirm.py)."""
    return {k: v for k, v in env.items() if k not in RUN_KEYS}


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node.js is required for plugin tests")
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_login_shells_path_goes_before_zoteros_in_each_run_and_is_read_once(facts):
    r = facts["macRuns"]
    assert r["shells"] == [["/bin/zsh", ["-ilc", "printf '%s' \"@SCHOLIUM_PATH@$PATH@SCHOLIUM_PATH@\""]]], "asked once, as a login shell"
    env = dict(PLAIN, PATH=MERGED + ":/home/u/.local/bin", CLAUDE_CODE_MAX_OUTPUT_TOKENS="32000")
    assert [base(e) for e in r["envs"]] == [env, env], "each folder once; ~/.local/bin there and added, ~/.cargo/bin not there and left out"
    assert r["append"] == [True, True]
    c = facts["macCodex"]
    assert c["shells"] == 1 and [base(e) for e in c["env"]] == [dict(PLAIN, PATH=MERGED, **CODEX_UV)] and c["append"] == [True]


CODEX_UV = {"UV_CACHE_DIR": "/data/tmp/scholium/uv/cache", "UV_PYTHON_INSTALL_DIR": "/data/tmp/scholium/uv/python"}


def test_codex_gets_uvs_folders_inside_its_sandbox_unless_set(facts):
    u = facts["codexUv"]
    assert u["root"] == "/data/tmp/scholium" and all(v.startswith(u["root"] + "/") for v in CODEX_UV.values())
    assert u["codex"] and all(base(e) == dict(PLAIN, **CODEX_UV) for e in u["codex"]), "each Codex process"
    assert u["claude"] == PLAIN, "Claude Code keeps uv's defaults"
    s = facts["codexUvSet"]
    assert s["codex"] and all(base(e) == dict(PLAIN, UV_PYTHON_INSTALL_DIR="/data/tmp/scholium/uv/python") for e in s["codex"]), "the user's own is kept"


def test_the_shell_is_shell_else_zsh(facts):
    assert facts["noShellVar"]["shells"][0][0] == "/bin/zsh"
    assert facts["relativeShell"]["shells"][0][0] == "/bin/zsh"
    assert facts["fish"]["shells"][0][0] == "/usr/local/bin/fish"
    assert facts["noShell"] == {"shells": [], "env": PLAIN}, "no shell there: Zotero's PATH as it is"


def test_a_shell_that_does_not_answer_is_killed_and_zoteros_path_kept(facts):
    h = facts["held"]
    assert h["ms"] == 5000 and h["during"] == {"calls": 1, "kills": 0, "timers": [5000]}
    assert h["kills"] == 1
    assert h["env"] == PLAIN and h["again"] == PLAIN
    assert h["calls"] == 1, "not asked again in the session"


def test_a_shell_whose_output_never_ends_is_given_up_after_its_time(facts):
    o = facts["open"]
    assert o["during"] == {"got": False, "timers": [5000]}
    assert o["env"] == PLAIN and o["again"] == PLAIN, "Zotero's PATH, also afterwards"
    assert o["kills"] == 1 and o["calls"] == 1 and o["timers"] == []
    r = facts["openRun"]
    assert r["before"] == {"calls": 0, "job": True}, "the run waits for the shell"
    assert [base(e) for e in r["envs"]] == [dict(PLAIN, CLAUDE_CODE_MAX_OUTPUT_TOKENS="32000")], "then goes on with Zotero's PATH"
    assert r["kills"] == 1
    s = facts["openStop"]
    assert s["stopped"] is True and s["job"] is False and s["queue"] == 0, "■ while it waits stops the run"
    assert s["calls"] == s["killed"] == 0, "no process is started"


def test_a_shell_that_printed_its_path_is_not_waited_for(facts):
    s = facts["openSaid"]
    assert s["env"] == dict(PLAIN, PATH=MERGED) and s["kills"] == 0 and s["timers"] == []


def test_a_codex_whose_version_never_ends_is_left_out(facts):
    c = facts["codexOpen"]
    assert c["during"] == {"timers": [15000]}
    assert c["found"] == "/home/u/.cargo/bin/codex.exe" and c["timers"] == []


def test_a_shell_that_fails_is_ignored_and_not_asked_again(facts):
    for name in ("notStarted", "noMarks", "relative", "failing"):
        f = facts[name]
        assert f["env"] == PLAIN and f["same"] is True and f["calls"] == 1, name
    assert facts["notStarted"]["logged"] == ["login PATH not read: Error: NS_ERROR_FILE_ACCESS_DENIED"]


def test_linux_reads_it_and_windows_starts_no_shell(facts):
    assert facts["linux"]["env"] == dict(PLAIN, PATH=MERGED) and len(facts["linux"]["shells"]) == 1
    assert facts["windows"] == {"env": PLAIN, "shells": 0}


def test_windows_adds_uvs_folder_under_the_name_path_has(facts):
    w = facts["windowsLocalBin"]
    assert w["upper"] == dict(PLAIN, PATH="/w/bin;/home/u/.local/bin")
    assert w["mixed"] == dict(PLAIN, Path="/w/bin;/home/u/.local/bin"), "the environment's own spelling, not a second variable"
    assert w["already"] == PLAIN, "already on PATH (case and a trailing separator aside): Zotero's PATH as it is"


def test_programs_are_looked_for_on_the_agents_path(facts):
    f = facts["found"]
    assert f == {"claude": f"{NVM}/claude", "codex": f"{NVM}/codex", "python": "/opt/homebrew/bin/python3", "shells": 1}


def test_the_uv_line_comes_before_python_with_the_installer_of_each_system(facts):
    m = facts["check_macMissing"]
    assert m["ids"][-3:] == ["uv", "python", "pymupdf"]
    assert m["lines"][0] == ["uv", "unknown", "uv", f"未找到。推荐安装：uv 会自行提供 Python 和 PyMuPDF。在终端运行 {UV_UNIX} 安装（或 brew install uv）。"]
    assert m["lines"][1:] == [["python", "ok", "Python", "3.12.1：/opt/homebrew/bin/python3（Scholium 找到的 Python，智能体的终端可能用另一个）"],
                              ["pymupdf", "ok", "PyMuPDF", "已安装 1.24.10"]], "without uv, Python and PyMuPDF are checked as before"
    assert facts["check_macMissingEnglish"]["lines"][0][3] == (
        f"Not found. Recommended: uv provides Python and PyMuPDF by itself; install it with {UV_UNIX} in a terminal (or brew install uv).")
    assert facts["check_linuxMissing"]["lines"][0][3] == f"未找到。推荐安装：uv 会自行提供 Python 和 PyMuPDF。在终端运行 {UV_UNIX} 安装。"
    assert facts["check_linuxMissingEnglish"]["lines"][0][3] == (
        f"Not found. Recommended: uv provides Python and PyMuPDF by itself; install it with {UV_UNIX} in a terminal.")
    assert facts["check_linuxMissing"]["lines"][1][:2] == ["python", "bad"], "no uv and no Python: a fault as before"


def test_uv_found_and_its_version(facts):
    f = facts["check_macFound"]
    assert f["lines"][0] == ["uv", "ok", "uv", "0.13.7：/home/u/.local/bin/uv"]
    assert f["uvCalls"] == [["/home/u/.local/bin/uv", ["--version"], MERGED + ":/home/u/.local/bin"]], "run with the agent's PATH"
    assert f["lines"][1:] == [["python", "ok", "Python", "3.12.1：/opt/homebrew/bin/python3（Scholium 找到的 Python，智能体的终端可能用另一个）"],
                              ["pymupdf", "ok", "PyMuPDF", "已安装 1.24.10"]]
    assert facts["check_windowsLocalBin"]["lines"][0] == ["uv", "ok", "uv", "0.13.7：/home/u/.local/bin/uv.exe"], "found in the folder added"


def test_with_uv_a_missing_or_old_python_or_pymupdf_is_no_fault(facts):
    assert facts["check_uvNoPython"]["lines"][1:] == [["python", "unknown", "Python", "Scholium 找不到 Python；uv 会代为提供 Python 和 PyMuPDF。"]]
    assert facts["check_uvNoPythonEnglish"]["lines"][1:] == [["python", "unknown", "Python", "Scholium finds no Python; uv provides Python and PyMuPDF instead."]]
    assert facts["check_uvOldPython"]["lines"][1:] == [["python", "unknown", "Python", "3.8.10 太旧：/usr/bin/python3；uv 会代为提供 Python 和 PyMuPDF。"]]
    n = facts["check_uvNoPymupdf"]["lines"]
    assert n[0] == ["uv", "ok", "uv", "0.13.7：/w/bin/uv.exe"]
    assert n[2] == ["pymupdf", "unknown", "PyMuPDF", "未安装；uv 会代为提供 PyMuPDF。"]
    assert facts["check_uvNoPymupdfEnglish"]["lines"][2] == ["pymupdf", "unknown", "PyMuPDF", "Not installed; uv provides PyMuPDF instead."]
    for name in ("uvNoPython", "uvOldPython", "uvNoPymupdf"):
        assert all(line[1] != "bad" for line in facts["check_" + name]["lines"]), name


def test_uv_that_gives_no_version_leaves_python_checked_as_before(facts):
    s = facts["check_uvSilent"]["lines"]
    assert s[0] == ["uv", "unknown", "uv", "/w/bin/uv.exe 没有报出版本"]
    assert s[1][:2] == ["python", "bad"]


def test_a_missing_uv_is_recognised_in_each_shell(facts):
    m = facts["missingAfter"]
    for name in ("bash", "zsh", "sh", "fish", "pwsh", "cmd"):
        assert m[name] == "noUv", name
    assert m["zshPython"] == "noPython"
    assert m["both"] == "noPython", "neither uv nor Python: the text that names both ways"
    assert m["pythonLater"] is None, "the script run by python afterwards clears it"
    assert m["uvx"] is None and m["uvRuns"] is None


def test_the_failure_texts_recommend_uv_with_the_installer(facts):
    w = facts["windowsTexts"]
    assert w["noUv"] == f"找不到 uv，在终端运行 {UV_WINDOWS} 安装后再试。"
    assert w["noPython"] == f"找不到 Python，安装 uv（在终端运行 {UV_WINDOWS}），或安装 Python 3.9 或更高版本并运行 pip install -U pymupdf 后再试。"
    assert w["pymupdf"] == f"缺少 PyMuPDF，安装 uv（在终端运行 {UV_WINDOWS}）或运行 pip install -U pymupdf 后再试。"
    e = facts["windowsTextsEnglish"]
    assert e["noUv"] == f"uv was not found; install it with {UV_WINDOWS} in a terminal, then try again."
    assert e["noPython"] == (f"Python was not found; install uv (run {UV_WINDOWS} in a terminal), or install Python 3.9 or later "
                             "and run pip install -U pymupdf, then try again.")
    assert e["pymupdf"] == f"PyMuPDF is missing; install uv (run {UV_WINDOWS} in a terminal) or run pip install -U pymupdf, then try again."
    mac = facts["macTextsEnglish"]
    assert mac["noUv"] == f"uv was not found; install it with {UV_UNIX} in a terminal, then try again."
    assert UV_UNIX in mac["noPython"]


@pytest.mark.parametrize("name, line", [
    ("runUv", "这台电脑装了 uv：用 uv run 运行 scholium.py。"),
    ("runPython", "这台电脑没有装 uv：用 python 运行 scholium.py。"),
    ("runNone", "这台电脑没有装 uv：用 python 运行 scholium.py。"),
    ("runUvEnglish", "uv is installed here: run scholium.py with uv run."),
    ("runPythonEnglish", "uv is not installed here: run scholium.py with python."),
    ("runMac", "这台电脑没有装 uv：用 python3 运行 scholium.py。"),
])
def test_the_prompts_say_how_the_script_runs_here(facts, name, line):
    f = facts[name]
    assert len(f["prompts"]) == 2, "an annotation and a question"
    for prompt in f["prompts"]:
        assert prompt.count(line) == 1
        assert ("uv run 运行" in prompt or "with uv run" in prompt) == ("装了 uv" in line or "is installed" in line)
    assert f["processes"] == 0, "no process to find it"


def test_an_annotations_claude_code_turns_are_capped_unless_the_user_set_it(facts):
    c = facts["capClaude"]
    assert c["resumed"] == [False, True, False], "the annotation, words to its session, a question"
    assert c["caps"] == ["32000", "32000", None]
    assert facts["capUserSet"]["caps"] == [None, None, None], "the user's own value is inherited, not replaced"
    assert facts["capCodex"] and all(v is None for v in facts["capCodex"])


def test_a_run_that_met_no_uv_says_so_unless_python_ran_the_script(facts):
    assert facts["card_noUv"] == {"cls": "scholium-card none", "title": f"没有写入批注：找不到 uv，在终端运行 {UV_WINDOWS} 安装后再试。"}
    assert facts["card_pythonAfter"] == {"cls": "scholium-card none", "title": "没有写入批注"}
    assert facts["card_neither"]["title"].startswith("没有写入批注：找不到 Python，安装 uv")


def test_the_skills_commands_run_by_uv_are_recognised(facts):
    assert facts["steps"] == {"extract": "extract", "extractQuoted": "extract", "dryRun": None, "dryRunEquals": None,
                              "apply": "applying", "list": None, "status": None, "uvConfigFile": None, "uvConfigFileDryRun": None,
                              "statusConfig": None, "samplesConfig": None, "profileConfig": None, "extractConfig": "extract"}
    assert facts["applied"] == {"quoted": "/o/my config.json", "afterUvOption": "c.json", "dryRun": None}
    assert facts["claudeStep"] == "applying" and facts["codexStep"] == "extract"


# --- the script's inline metadata (PEP 723), which `uv run` reads -------------------------------------------------------

PEP723 = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")
SCRIPTS = [ROOT / "src" / "zotero_scholium" / "cli.py", ROOT / "skills" / "zotero-scholium" / "scripts" / "scholium.py"]


@pytest.mark.parametrize("path", SCRIPTS, ids=["cli.py", "scholium.py"])
def test_the_script_carries_inline_metadata_with_pymupdf(path):
    text = path.read_text(encoding="utf8")
    blocks = [m for m in PEP723.finditer(text) if m.group("type") == "script"]
    assert len(blocks) == 1
    content = "".join(line[2:] if line.startswith("# ") else line[1:] for line in blocks[0].group("content").splitlines(keepends=True))
    assert re.search(r'^requires-python = ">=3\.9"$', content, re.M)
    assert re.findall(r'"([^"]+)"', re.search(r"^dependencies = \[(.*)\]$", content, re.M).group(1)) == ["pymupdf"]
    if sys.version_info >= (3, 11):
        import tomllib
        assert tomllib.loads(content) == {"requires-python": ">=3.9", "dependencies": ["pymupdf"]}
    assert text.splitlines()[0] == "# -*- coding: utf-8 -*-", "the coding line stays first"
    assert text.index("# /// script") < text.index('"""'), "before the docstring"


def test_the_skill_names_both_ways_to_run_the_script_once():
    skill = ROOT / "skills" / "zotero-scholium"
    text = (skill / "SKILL.md").read_text(encoding="utf8")
    assert text.count("`uv run <skill dir>/scripts/scholium.py …`") == 1
    assert text.count("`python <skill dir>/scripts/scholium.py …`") == 1
    for md in [skill / "SKILL.md"] + sorted((skill / "references").glob("*.md")):
        body = md.read_text(encoding="utf8").replace("`python <skill dir>/scripts/scholium.py …`", "")
        assert "python <skill dir>" not in body, md.name


def test_the_message_for_a_missing_pymupdf_names_uv():
    from zotero_scholium import cli
    assert "uv run" in cli.PYMUPDF_MISSING and "pip install -U pymupdf" in cli.PYMUPDF_MISSING
    assert cli.PYMUPDF_MISSING.startswith("PyMuPDF is not installed"), "as the plugin recognises it"
