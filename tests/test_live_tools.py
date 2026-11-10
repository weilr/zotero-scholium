"""The real-run tools (scripts/smoke/live.py, eval.py, guard/, probe/live.js): their pure parts, without Zotero, a model
or the network. Every safety layer of a live run is checked here: the port, the profile's prefs, the environment, the
user's own skill script, the guard, the chain test's verdict, the watcher's reading of netstat, the budget's flags and
the cost stop's reading of the result lines."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMOKE = os.path.join(ROOT, "scripts", "smoke")


def load(name):
    spec = importlib.util.spec_from_file_location("live_tools_" + name, os.path.join(SMOKE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


live = load("live")
ev = load("eval")


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as f:
        f.write(text.encode("utf8"))
    return str(path)


# ---- the port ----
def test_the_runner_refuses_the_users_port(capsys, monkeypatch):
    monkeypatch.setattr(live, "session", lambda a: pytest.fail("a session started"))
    with pytest.raises(SystemExit) as e:
        live.main(["--zotero", "nowhere.exe", "--pdf", "p.pdf", "--port", "23119"])
    assert e.value.code == 2 and "23119" in capsys.readouterr().err


def test_a_config_file_cannot_bring_the_users_port(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(live, "session", lambda a: pytest.fail("a session started"))
    cfg = write(tmp_path / "c.json", json.dumps({"zotero": "z.exe", "pdf": "p.pdf", "port": 23119}))
    assert live.main(["--config", cfg]) == 2   # "pdf" is not a config key
    cfg = write(tmp_path / "c2.json", json.dumps({"zotero": "z.exe", "port": 23119}))
    with pytest.raises(SystemExit):
        live.main(["--config", cfg, "--pdf", "p.pdf"])
    assert "23119" in capsys.readouterr().err


def test_the_eval_set_refuses_the_users_port(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        ev.main(["run", "--zotero", "z.exe", "--papers", str(tmp_path), "--port", "23119"])
    assert e.value.code == 2 and "23119" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--max-msgs", "0"], ["--max-usd", "0"]])
def test_both_caps_are_always_on(args, capsys, monkeypatch):
    monkeypatch.setattr(live, "session", lambda a: pytest.fail("a session started"))
    with pytest.raises(SystemExit):
        live.main(["--zotero", "z.exe", "--pdf", "p.pdf"] + args)
    assert "positive" in capsys.readouterr().err


def test_the_guard_is_never_written_for_the_users_port(tmp_path):
    with pytest.raises(ValueError, match="23119"):
        live.write_guard(str(tmp_path / "guard"), 23119)


def test_config_keys(tmp_path):
    cfg = write(tmp_path / "c.json", json.dumps({"zotero": "z.exe", "max-usd": 0.5, "papers": "p"}))
    assert live.load_config(cfg) == {"zotero": "z.exe", "max_usd": 0.5, "papers": "p"}
    with pytest.raises(ValueError, match="budget"):
        live.load_config(write(tmp_path / "bad.json", json.dumps({"budget": 1})))
    assert live.load_config(None) == {}


# ---- the profile ----
def test_the_profile_prefs_are_the_throwaways():
    p = live.live_prefs("C:\\run\\data", 23149, "zh-CN", "C:\\bin\\claude.exe", "haiku", "low")
    assert p["extensions.zotero.firstRun2"] is False
    assert p["extensions.zotero.httpServer.port"] == 23149 and p["extensions.zotero.httpServer.localAPI.enabled"] is True
    assert p["extensions.zoteroWinWordIntegration.skipInstallation"] is True and p["extensions.zotero.sync.autoSync"] is False
    assert p["extensions.scholium.claudePath"] == "C:\\bin\\claude.exe"
    assert p["extensions.scholium.claudeModel"] == "haiku" and p["extensions.scholium.claudeEffort"] == "low"
    assert p["extensions.scholium.showAnnotations"] is True
    assert "extensions.scholium.showAnnotations" not in live.live_prefs("d", 23149, "en-US", "c", "opus", "high", show_pref=False)
    with pytest.raises(ValueError, match="23119"):
        live.live_prefs("d", 23119, "zh-CN", "c", "haiku", "low")


# ---- the environment ----
BASE = {"PATH": "C:\\bin", "USERPROFILE": "C:\\Users\\someone", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "x", "Claude_Pid": "7",
        "CLAUDE_CONFIG_DIR": "C:\\Users\\someone\\.claude", "CODEX_HOME": "C:\\Users\\someone\\.codex", "SCHOLIUM_ZOTERO_PORT": "23119",
        "TEMP": "C:\\Temp", "APPDATA": "C:\\AppData", "PYTHONPATH": "C:\\mine"}


def test_a_real_runs_environment(tmp_path):
    run, guard = str(tmp_path / "run"), str(tmp_path / "run" / "guard")
    kept = dict(BASE)
    env = live.live_env(BASE, run, guard)
    assert BASE == kept
    assert not [k for k in env if k.upper().startswith("CLAUDE")]   # the user's login: no CLAUDE_CONFIG_DIR
    assert "SCHOLIUM_ZOTERO_PORT" not in env   # the plugin gives each agent its Zotero's port
    for k in ("TEMP", "TMP", "APPDATA", "ZOTERO_DATA_DIR", "CODEX_HOME"):
        assert os.path.commonpath([env[k], run]) == run, k
    assert env["PYTHONPATH"].split(os.pathsep) == [guard, "C:\\mine"]
    assert env["USERPROFILE"] == BASE["USERPROFILE"] and env["PATH"] == "C:\\bin"
    assert live.check_env(env, run, guard)


def test_a_rehearsals_environment(tmp_path):
    run, guard = str(tmp_path / "run"), str(tmp_path / "run" / "guard")
    env = live.live_env({"PATH": "p"}, run, guard, fake_dir=os.path.join(run, "fake"))
    assert env["SCHOLIUM_FAKE_DIR"] == os.path.join(run, "fake") and env["CLAUDE_CONFIG_DIR"] == os.path.join(run, "claude-config")
    assert env["PYTHONPATH"] == guard
    assert live.check_env(env, run, guard, fake=True)


@pytest.mark.parametrize("change", [{"SCHOLIUM_ZOTERO_PORT": "23129"}, {"CLAUDECODE": "1"}, {"CLAUDE_CONFIG_DIR": "C:\\Users\\x\\.claude"},
                                    {"TEMP": "C:\\Temp"}, {"CODEX_HOME": "C:\\Users\\x\\.codex"}, {"PYTHONPATH": "C:\\other"}])
def test_a_wrong_environment_is_refused(tmp_path, change):
    run, guard = str(tmp_path / "run"), str(tmp_path / "run" / "guard")
    env = dict(live.live_env({"PATH": "p"}, run, guard), **change)
    with pytest.raises(RuntimeError):
        live.check_env(env, run, guard)


def test_the_fakes_config_dir_must_be_the_runs(tmp_path):
    run, guard = str(tmp_path / "run"), str(tmp_path / "run" / "guard")
    env = dict(live.live_env({}, run, guard, fake_dir=os.path.join(run, "fake")), CLAUDE_CONFIG_DIR=str(tmp_path / "elsewhere"))
    with pytest.raises(RuntimeError, match="CLAUDE_CONFIG_DIR"):
        live.check_env(env, run, guard, fake=True)


def test_the_agent_env_check():
    facts = [{"what": "agentEnv", "SCHOLIUM_ZOTERO_PORT": "23149"}, {"what": "agentEnv", "SCHOLIUM_ZOTERO_PORT": "23149"}]
    assert live.check_agent_env(facts, 23149)[0]
    assert not live.check_agent_env(facts + [{"what": "agentEnv", "SCHOLIUM_ZOTERO_PORT": None}], 23149)[0]
    assert not live.check_agent_env([{"what": "agentEnv", "SCHOLIUM_ZOTERO_PORT": "23119"}], 23149)[0]
    assert not live.check_agent_env([], 23149)[0]   # no agent process seen
    aborted = facts + [{"what": "abort", "reason": "agent environment: SCHOLIUM_ZOTERO_PORT undefined, not 23149"}]
    assert not live.check_agent_env(aborted, 23149)[0]


# ---- the user's own skill script ----
OLD_SCRIPT = 'BASE = "http://127.0.0.1:23119"\n# SCHOLIUM_ZOTERO_PORT is not read here\n'


def test_the_skill_script_honours_the_port():
    with open(os.path.join(ROOT, "skills", "zotero-scholium", "scripts", "scholium.py"), encoding="utf8") as f:
        assert live.honours_port(f.read())
    assert live.honours_port('port = os.environ.get("SCHOLIUM_ZOTERO_PORT", "")')
    assert live.honours_port("port = os.getenv('SCHOLIUM_ZOTERO_PORT')")
    assert live.honours_port('port = os.environ["SCHOLIUM_ZOTERO_PORT"]')
    assert not live.honours_port(OLD_SCRIPT)   # a mention is not a read
    assert not live.honours_port("")


def test_the_personal_script_check(tmp_path):
    home = str(tmp_path / "home")
    path = live.personal_script(home)
    assert path == os.path.join(home, ".claude", "skills", "zotero-scholium", "scripts", "scholium.py")
    assert live.check_script(path)[0]   # none: nothing to run
    write(path, 'x = os.environ.get("SCHOLIUM_ZOTERO_PORT")\n')
    before = open(path, "rb").read()
    assert live.check_script(path)[0]
    assert open(path, "rb").read() == before   # only read
    write(path, OLD_SCRIPT)
    ok, what = live.check_script(path)
    assert not ok and "SCHOLIUM_ZOTERO_PORT" in what and "23119" in what


def test_the_runner_refuses_an_old_personal_script(tmp_path, capsys, monkeypatch):
    old = write(tmp_path / "home" / "scholium.py", OLD_SCRIPT)
    monkeypatch.setattr(live, "WINDOWS", True)
    monkeypatch.setattr(live, "personal_script", lambda home=None: old)
    monkeypatch.setattr(live, "session", lambda a: pytest.fail("a session started"))
    monkeypatch.setattr(live, "commit_of", lambda rev: pytest.fail("git was asked"))
    zotero, pdf, fake = (write(tmp_path / n, "x") for n in ("zotero.exe", "p.pdf", "fake.exe"))
    assert live.main(["--zotero", zotero, "--pdf", pdf, "--fake", fake, "--port", "23149", "--out", str(tmp_path / "out")]) == 2
    assert "does not read SCHOLIUM_ZOTERO_PORT" in capsys.readouterr().err
    assert not os.path.exists(str(tmp_path / "out"))


# ---- the budget: never shown to the agent ----
def test_claude_code_never_gets_a_budget():
    flags = live.agent_flags("C:\\run\\export")
    assert flags == ["--setting-sources", "project,local", "--plugin-dir", "C:/run/export"]
    for bad in (["--max-budget-usd", "0.5"], ["--max-budget-usd=0.5"]):
        with pytest.raises(ValueError, match="max-budget-usd"):
            live.check_flags(["--setting-sources", "project,local"] + bad)
    assert "max-budget" not in " ".join(live.parser({})._option_string_actions)


def test_the_probe_cancels_a_run_given_a_budget_or_another_port():
    probe = open(os.path.join(SMOKE, "probe", "live.js"), encoding="utf8").read()
    assert re.search(r"--max-budget-usd.*\n.*abort\(", probe)
    assert "String(port) !== String(CFG.port)" in probe and "CFG.maxMsgs" in probe and "CFG.stopFile" in probe
    assert "chain-request.json" in probe and "if (!chainOk)" in probe


def test_the_probe_points_claude_code_at_the_export():
    probe = open(os.path.join(SMOKE, "probe", "live.js"), encoding="utf8").read()
    assert 'agent === "claude" ? CFG.claudeSkills' in probe and 'line("spawn"' in probe and "Object.defineProperty(w, \"call\"" in probe
    assert '"claudeSkills": os.path.join(export, "skills")' in open(os.path.join(SMOKE, "live.py"), encoding="utf8").read()


def test_the_probe_records_the_click_and_the_live_line():
    probe = open(os.path.join(SMOKE, "probe", "live.js"), encoding="utf8").read()
    assert probe.index('line("clicked"') < probe.index("await realClick(annotGo(box))")   # the pre-run's time: click to Claude Code's args
    assert 'line("live", { words, title })' in probe and ".scholium-working" in probe and "runningTitle()" in probe
    assert "sampled = true;\n    await sampler;" in probe   # the sampler ends with the run


# ---- the probe ----
def assembled():
    with open(os.path.join(SMOKE, "probe", "bootstrap.js"), encoding="utf8") as f1, open(os.path.join(SMOKE, "probe", "live.js"), encoding="utf8") as f2:
        return live.assemble_probe(f1.read(), f2.read())


def test_the_live_probe_is_the_smoke_probe_with_another_main():
    probe = assembled()
    assert probe.count("\nasync function main() {") == 1 and probe.count("\nasync function finish() {") == 1
    assert "r.agentEnv = async function" in probe and 'for (const name of ["section"' not in probe
    assert probe.index("async function main()") < probe.index("async function finish()")
    defined = set(re.findall(r"^(?:async )?function (\w+)|^(?:const|let|var) (\w+)", probe, re.M))
    defined = {a or b for a, b in defined}
    live_js = open(os.path.join(SMOKE, "probe", "live.js"), encoding="utf8").read()
    used = {"selectItem", "showTab", "annotGo", "realClick", "typeIn", "started", "busy", "cards", "shot", "openReader", "listenErrors",
            "acceptDialogs", "waitFor", "step", "finish", "txt", "q", "qa", "win", "doc", "delay", "line", "save", "R", "watching", "reader"}
    assert used <= defined, used - defined
    assert all(re.search(r"\b%s\b" % n, live_js) for n in ("selectItem", "cards", "openReader"))
    with pytest.raises(ValueError):
        live.assemble_probe("function startup() {}\n", "async function main() {}\n")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_live_probe_parses(tmp_path):
    path = write(tmp_path / "probe.js", assembled())
    p = subprocess.run([shutil.which("node"), "--check", path], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_paper_meta():
    assert live.paper_meta(None, "C:\\papers\\2305.18290.pdf") == {"itemType": "preprint", "fields": {"title": "2305.18290"}, "creators": []}
    m = live.paper_meta({"fields": {"title": "T", "date": "2020"}, "creators": [["A", "B"]], "pdf": "ignored"}, "x.pdf")
    assert m == {"itemType": "preprint", "fields": {"title": "T", "date": "2020"}, "creators": [["A", "B"]]}


# ---- the guard (in a child Python: this one keeps conftest's guard) ----
def child(guard, code):
    env = dict(os.environ, PYTHONPATH=guard)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=guard, timeout=60)


def test_the_guard_moves_the_users_port_to_the_throwaways(tmp_path):
    guard = live.write_guard(str(tmp_path / "guard"), 23149)
    p = child(guard, live.GUARD_SELFTEST)
    assert live.guard_selftest_ok(p.returncode, p.stdout, guard, 23149), p.stdout + p.stderr
    assert live.redirects(guard) == 3   # the self-test's own: noted
    assert not live.guard_selftest_ok(p.returncode, p.stdout, guard, 23129)
    assert not live.guard_selftest_ok(0, p.stdout.replace("23149", "23119"), guard, 23149)
    assert not live.guard_selftest_ok(1, p.stdout, guard, 23149)
    assert not live.guard_selftest_ok(0, p.stdout, str(tmp_path / "other"), 23149)


def test_without_a_port_the_guard_refuses(tmp_path):
    guard = live.write_guard(str(tmp_path / "guard"), 23149)
    os.remove(os.path.join(guard, "port.txt"))
    p = child(guard, "import sitecustomize as s\ntry:\n    s._move(('127.0.0.1', 23119))\nexcept ConnectionRefusedError:\n    print('refused')\n"
                     "print(s._move(('127.0.0.1', 23129)))")
    assert p.stdout.split() == ["refused", "('127.0.0.1',", "23129)"], p.stderr
    write(os.path.join(guard, "port.txt"), "23119")   # never the user's port as the target
    p = child(guard, "import sitecustomize as s\nprint(s._OURS)")
    assert p.stdout.strip() == "None"


def test_the_chain_verdict():
    ns = ["TCP 127.0.0.1:23119 0.0.0.0:0 LISTENING 4242"]
    good = {"guardOk": True, "status": {"rc": 0, "out": '{"title": "Direct Preference Optimization: Your"}'},
            "statusIsolated": {"rc": 0, "out": '{"title": "Direct Preference Optimization: Your"}'}, "apply": {"applied": True},
            "redirects": 0, "netstat23119": [ns, ns + ["TCP 127.0.0.1:50000 127.0.0.1:23119 TIME_WAIT 0"]]}
    title = "Direct Preference Optimization: Your Language Model is Secretly a Reward Model"
    assert live.chain_verdict(good, title) == (True, [])
    cases = {"the guard's self-test": {"guardOk": False}, "status through the guard": {"status": {"rc": 1, "out": ""}},
             "status with python -I and SCHOLIUM_ZOTERO_PORT alone": {"statusIsolated": {"rc": 0, "out": "{}"}},
             "--apply on the chain-test item": {"apply": {"applied": False}}, "a redirect by the guard": {"redirects": 1},
             "netstat :23119 changed": {"netstat23119": [ns, []]}}
    for name, change in cases.items():
        ok, failed = live.chain_verdict(dict(good, **change), title)
        assert not ok and failed == [name], name
    assert not live.chain_verdict({}, title)[0]


# ---- the watcher ----
NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:23119        0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:23129        0.0.0.0:0              LISTENING       5000
  TCP    127.0.0.1:50001        127.0.0.1:23119        ESTABLISHED     7003
  TCP    127.0.0.1:23119        127.0.0.1:50001        ESTABLISHED     4242
  TCP    127.0.0.1:50002        127.0.0.1:23119        ESTABLISHED     9100
  TCP    127.0.0.1:50003        127.0.0.1:23119        TIME_WAIT       0
  TCP    127.0.0.1:50004        127.0.0.1:8080         ESTABLISHED     23119
  TCP    127.0.0.1:50005        127.0.0.1:23129        ESTABLISHED     7003
  TCP    [::1]:50006            [::1]:23119            ESTABLISHED     7004
  UDP    0.0.0.0:23119          *:*                                    4242
"""
PROFILE = "C:\\runs\\a\\profile"
TABLE = {   # pid: (parent pid, name, command line, creation time)
    100: (1, "python.exe", "python scripts/smoke/live.py", 1000),                            # the runner
    5000: (100, "zotero.exe", '"C:\\Z\\zotero.exe" -no-remote -profile "C:\\runs\\a\\profile"', 1100),
    7001: (5000, "claude.exe", "claude.exe -p", 1200),
    7002: (7001, "pwsh.exe", "pwsh -c ...", 1300),
    7003: (7002, "python.exe", "python scholium.py --apply", 1400),                          # the run's agent
    7004: (100, "python.exe", "python scholium.py status", 1150),                             # the chain test
    4242: (1, "zotero.exe", '"C:\\Program Files\\Zotero\\zotero.exe"', 10),                   # the user's own
    9100: (1, "WINWORD.EXE", "WINWORD.EXE", 20),
    9200: (9201, "a.exe", "a", 30), 9201: (9200, "b.exe", "b", 30),                          # a loop of parents
    # Word, started before this run, whose parent is gone; that parent's id now belongs to this run's Zotero, its claude
    9300: (5000, "WINWORD.EXE", "WINWORD.EXE /automation", 500), 9301: (7001, "WINWORD.EXE", "WINWORD.EXE", 900),
}


def test_netstat_rows_with_23119_on_either_side():
    rows = live.netstat_rows(NETSTAT)
    assert [(r["local"], r["foreign"], r["pid"]) for r in rows] == [
        ("127.0.0.1:23119", "0.0.0.0:0", 4242), ("127.0.0.1:50001", "127.0.0.1:23119", 7003), ("127.0.0.1:23119", "127.0.0.1:50001", 4242),
        ("127.0.0.1:50002", "127.0.0.1:23119", 9100), ("127.0.0.1:50003", "127.0.0.1:23119", 0), ("[::1]:50006", "[::1]:23119", 7004),
        ("0.0.0.0:23119", "*:*", 4242)]   # not a pid of 23119, not the throwaway's 23129
    assert [live.is_listen(r) for r in rows] == [True, False, False, False, False, False, True]
    assert live.netstat_rows("") == [] and live.netstat_rows("garbage line\nTCP x") == []


def test_the_run_is_its_runner_its_zotero_and_their_children():
    roots = {100}
    assert live.in_tree(7003, TABLE, PROFILE, roots) and live.in_tree(7004, TABLE, PROFILE, roots)
    assert live.in_tree(5000, TABLE, PROFILE) and live.in_tree(7003, TABLE, PROFILE)
    assert not live.in_tree(4242, TABLE, PROFILE, roots) and not live.in_tree(9100, TABLE, PROFILE, roots)
    assert not live.in_tree(9200, TABLE, PROFILE, roots) and not live.in_tree(12345, TABLE, PROFILE, roots)
    assert live.in_tree(100, {}, PROFILE, roots)


def test_a_reused_parent_id_is_not_the_runs():
    """Windows reuses process ids: a process whose parent is gone keeps its id, which may now be the run's Zotero's.
    A "parent" created after its child is another process, and the chain ends there."""
    roots = {100}
    assert not live.in_tree(9300, TABLE, PROFILE, roots) and not live.in_tree(9301, TABLE, PROFILE, roots)
    old = {k: v[:3] for k, v in TABLE.items()}   # without creation times the chain is followed as before
    assert live.in_tree(9300, old, PROFILE, roots)
    unknown = dict(TABLE)
    unknown[7002] = (7001, "pwsh.exe", "pwsh", None)   # a creation time not known: the chain goes on
    assert live.in_tree(7003, unknown, PROFILE, roots)


def test_a_trip_ends_only_the_runs_zotero(monkeypatch, tmp_path):
    rows = live.netstat_rows("  TCP 127.0.0.1:50009 127.0.0.1:23119 ESTABLISHED 7003\n")
    assert live.watch_step(rows, TABLE, PROFILE, {100}, {})[2]["pid"] == 7003
    word = live.netstat_rows("  TCP 127.0.0.1:50010 127.0.0.1:23119 ESTABLISHED 9300\n")   # Word's Zotero integration
    assert live.watch_step(word, TABLE, PROFILE, {100}, {})[2] is None
    ended, ran = [], []
    monkeypatch.setattr(live, "netstat_text", lambda: "  TCP 127.0.0.1:50009 127.0.0.1:23119 ESTABLISHED 7003\n")
    monkeypatch.setattr(live, "procs", lambda: TABLE)
    monkeypatch.setattr(live.smoke, "end_ours", lambda profile: ended.append(profile) or [5000])
    monkeypatch.setattr(live.subprocess, "run", lambda *a, **k: ran.append(a) or pytest.fail("a process was started: %r" % (a,)))
    w = live.Watcher(str(tmp_path), PROFILE)
    w.roots = {100}
    w.stopping.wait = lambda t: w.stopping.set()   # one sample
    w.run()
    assert w.tripped["pid"] == 7003 and w.tripped["ended"] == [5000] and ended == [PROFILE] and ran == []
    assert "taskkill" not in open(os.path.join(SMOKE, "live.py"), encoding="utf8").read().split("class Watcher")[1].split("def prepare_run")[0]


def test_a_closed_connection_during_the_session_leaves_it_unverified(monkeypatch, tmp_path):
    """A connection shorter than a sample shows only as TIME_WAIT without a process, on either side: one that was not
    there as the run's Zotero started could have been the run's."""
    old = "  TCP 127.0.0.1:50020 127.0.0.1:23119 TIME_WAIT 0\n"
    new = "  TCP 127.0.0.1:50021 127.0.0.1:23119 TIME_WAIT 0\n  TCP 127.0.0.1:23119 127.0.0.1:50022 TIME_WAIT 0\n"
    samples = iter([old, old + new])
    monkeypatch.setattr(live, "netstat_text", lambda: next(samples))
    monkeypatch.setattr(live, "procs", lambda: {})
    w = live.Watcher(str(tmp_path), PROFILE)
    calls = []

    def wait(t):
        calls.append(t)
        w.zotero_started = True   # Zotero starts after the first sample
        if len(calls) == 2:
            w.stopping.set()
    w.stopping.wait = wait
    w.run()
    assert w.closed_before == {("127.0.0.1:50020", "127.0.0.1:23119")}
    assert w.closed_during() == [("127.0.0.1:23119", "127.0.0.1:50022"), ("127.0.0.1:50021", "127.0.0.1:23119")]
    assert w.tripped is None
    listen = "TCP 127.0.0.1:23119 0.0.0.0:0 LISTENING 4242"
    s = {"tripped": None, "netstat": {"before": [listen], "after": [listen]}, "redirects": 0, "chain": {"ok": True}, "agent_env": {"ok": True},
         "aborted": [], "ended": "quit", "annotate_results": 1, "db": True, "watch": {"closed during": ["a -> b", "c -> d"]}}
    assert live.verdict(s) == (True, True) and "2 closed connection(s)" in live.unverified(s)[0]
    assert live.unverified(dict(s, watch={"closed during": []})) == []
    assert live.UNVERIFIED_EXIT not in (0, 1, live.REFUSED_EXIT, live.SAFETY_EXIT) and live.UNVERIFIED_EXIT in ev.STOPS


def test_a_from_run_copy_brings_no_cost_or_results(tmp_path, monkeypatch):
    """--from-run copies the source's data, its conversation logs too: only what they gain in the new session counts."""
    src, run = str(tmp_path / "src"), str(tmp_path / "new")
    old_log = os.path.join("data", "tmp", "scholium", "OLDATT", "conversations", "annotate-1.jsonl")
    write(os.path.join(src, old_log), json.dumps({"type": "result", "total_cost_usd": 0.8}) + "\n")
    os.makedirs(os.path.join(src, "profile"))
    live.prepare_run(run)
    monkeypatch.setattr(live, "ours", lambda profile: [])
    live.copy_from_run(src, run)
    since = live.log_sizes(run)
    assert live.session_cost(run) == pytest.approx(0.8)   # without since: the copy's
    assert live.session_cost(run, since) == 0 and live.annotate_results(run, since) == 0
    with open(os.path.join(run, old_log), "a", encoding="utf8") as f:   # the session writes on in the old log
        f.write(json.dumps({"type": "result", "total_cost_usd": 0.05}) + "\n")
    write(os.path.join(run, "data", "tmp", "scholium", "NEWATT", "conversations", "annotate-2.jsonl"),
          json.dumps({"type": "result", "total_cost_usd": 0.02}) + "\n")
    assert live.session_cost(run, since) == pytest.approx(0.07) and live.annotate_results(run, since) == 2
    write(os.path.join(run, old_log), "{}\n")   # a log rewritten shorter: read whole
    assert live.new_lines(os.path.join(run, old_log), since) == ["{}"]


def test_the_process_table_reads_creation_times():
    t = live.parse_procs("100\t1\t133000000000000000\tpython.exe\tpython live.py\n4\t0\t\tSystem\t\n"
                         "7\t100\t133000000000000100\tcmd.exe\tcmd /c \"a\tb\"\nnot a row\n")
    assert t[100] == (1, "python.exe", "python live.py", 133000000000000000)
    assert t[4] == (0, "System", "", None) and t[7][2] == 'cmd /c "a\tb"'


def test_a_connection_from_the_run_trips_the_watcher():
    seen = {}
    every, clients, trip = live.watch_step(live.netstat_rows(NETSTAT), TABLE, PROFILE, {100}, seen)
    assert trip == {"pid": 7003, "name": "python.exe", "line": "TCP 127.0.0.1:50001 127.0.0.1:23119 ESTABLISHED 7003"}
    assert any(l.startswith("zotero-side pid 4242 zotero.exe") for l in every)   # both sides logged
    assert any(l.startswith("client-side pid 7003 python.exe") for l in every)
    assert "OURS pid 7003 python.exe: TCP 127.0.0.1:50001 127.0.0.1:23119 ESTABLISHED 7003" in clients
    assert "other pid 9100 WINWORD.EXE: TCP 127.0.0.1:50002 127.0.0.1:23119 ESTABLISHED 9100" in clients
    assert "closed TCP 127.0.0.1:50003 127.0.0.1:23119 TIME_WAIT 0" in clients
    assert any(l.startswith("OURS pid 7004") for l in clients)
    assert seen["other"] == {"9100 WINWORD.EXE"}
    again = live.watch_step(live.netstat_rows(NETSTAT), TABLE, PROFILE, {100}, seen)
    assert again[0] == [] and again[1] == [] and again[2]   # logged once; still tripping


def test_other_programs_connections_do_not_trip():
    text = "  TCP 127.0.0.1:50002 127.0.0.1:23119 ESTABLISHED 9100\n  TCP 127.0.0.1:23119 127.0.0.1:50002 ESTABLISHED 4242\n"
    every, clients, trip = live.watch_step(live.netstat_rows(text), TABLE, PROFILE, {100}, {})
    assert trip is None and len(every) == 2 and clients == ["other pid 9100 WINWORD.EXE: TCP 127.0.0.1:50002 127.0.0.1:23119 ESTABLISHED 9100"]


# ---- the cost stop ----
STREAM = [
    '{"type": "system", "subtype": "init", "model": "claude-haiku-5-5", "session_id": "s1"}',
    '{"type": "assistant", "message": {"id": "msg_01", "content": [{"type": "text", "text": "the \\"result\\" of the paper"}], '
    '"usage": {"input_tokens": 3, "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 2000, "output_tokens": 50}}}',
    'not json: "type": "result"',
    '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 0.0268, "num_turns": 16, "duration_ms": 118519, '
    '"result": "35 highlights.\\nDone: 35 highlights, 14 core.", "usage": {"input_tokens": 28, "cache_read_input_tokens": 561287, '
    '"cache_creation_input_tokens": 59786, "output_tokens": 18443, "output_tokens_details": {"thinking_tokens": 9167}}}',
    '{"type": "result", "subtype": "error_during_execution", "is_error": true, "total_cost_usd": 0.0012, "num_turns": 1}',
    '{"type": "result", "subtype": "success"}',
]


def test_the_cost_is_the_sum_of_the_result_lines():
    assert live.result_cost(STREAM) == pytest.approx(0.028)
    assert live.result_cost([]) == 0 and live.result_cost(STREAM[:3]) == 0


def test_the_session_cost_counts_every_log_of_the_run(tmp_path):
    run = str(tmp_path / "run")
    write(os.path.join(run, "data", "tmp", "scholium", "ATT1", "conversations", "annotate-claude-1.jsonl"), "\n".join(STREAM) + "\n")
    write(os.path.join(run, "data", "tmp", "scholium", "ATT1", "conversations", "chat-1.jsonl"), STREAM[3] + "\n")
    write(os.path.join(run, "chain", "x.jsonl"), STREAM[3] + "\n")   # not a conversation
    assert live.session_cost(run) == pytest.approx(0.028 + 0.0268)
    assert len(live.conversation_logs(run, "annotate-*")) == 1


def test_the_verdict():
    listen = "TCP 127.0.0.1:23119 0.0.0.0:0 LISTENING 4242"
    ns = {"before": [listen], "after": [listen]}
    good = {"tripped": None, "netstat": ns, "redirects": 0, "chain": {"ok": True}, "agent_env": {"ok": True}, "aborted": [],
            "ended": "quit", "annotate_results": 1, "db": True}
    assert live.verdict(good) == (True, True)
    # the user's own connections (Word, a browser) come and go: only the LISTENING lines are compared
    assert live.verdict(dict(good, netstat={"before": [listen], "after": [listen, "TCP 127.0.0.1:50002 127.0.0.1:23119 TIME_WAIT 0"]}))[0]
    for change in ({"tripped": {"pid": 1}}, {"netstat": {"before": [listen], "after": [listen.replace("4242", "4243")]}},
                   {"netstat": {"before": [listen], "after": []}}, {"redirects": 2}, {"chain": {}},
                   {"agent_env": {"ok": False}}, {"aborted": ["the chain test failed: no real run"]}):
        assert live.verdict(dict(good, **change))[0] is False, change
    assert live.verdict(dict(good, ended="timeout")) == (True, False)
    assert live.verdict(dict(good, annotate_results=0)) == (True, False)


def test_only_a_live_runs_folder_is_emptied(tmp_path):
    other = tmp_path / "mine"
    write(other / "precious.txt", "x")
    with pytest.raises(RuntimeError, match="not a live run"):
        live.prepare_run(str(other))
    assert (other / "precious.txt").exists()
    run = str(tmp_path / "run")
    live.prepare_run(run)
    write(os.path.join(run, "old.txt"), "x")
    live.prepare_run(run)
    assert os.listdir(run) == [live.MARKER]


# ---- the scores ----
def fixture_run(tmp_path, name="eval-dpo"):
    run = tmp_path / name
    att = "ATTKEY01"
    write(run / "probe-config.json", json.dumps({"paper": {"fields": {"title": "Direct Preference Optimization", "archiveID": "arXiv:2305.18290",
                                                                      "DOI": "10.48550/arXiv.2305.18290"}}}))
    write(run / "live.json", json.dumps({"commit": "abc1234", "fake": False, "safe": True}))
    write(run / "shots" / "facts.json", json.dumps([{"what": "items", "att": att}, {"what": "ended", "seconds": 130, "stopped": False}]))
    tag = ["zotero-scholium"]
    anns = [{"type": "highlight", "color": "#ff6666", "pageIndex": 0, "text": "We propose DPO.", "comment": "我们提出 DPO。", "tags": tag},
            {"type": "highlight", "color": "#ffd400", "pageIndex": 1, "text": "It is stable.", "comment": "它很稳定。", "tags": tag},
            {"type": "highlight", "color": "#FF6666", "page": "3", "text": "A reference.", "comment": "", "tags": tag},
            {"type": "highlight", "color": "#ffd400", "pageIndex": 3, "text": "Copied English text", "comment": "Copied English text", "tags": tag},
            {"type": "text", "color": "#2ea8e5", "pageIndex": 0, "text": "", "comment": "页边", "tags": tag},
            {"type": "highlight", "color": "#ff6666", "pageIndex": 0, "text": "the user's", "comment": "", "tags": []}]
    note = "<h1>DPO</h1><h2>问题</h2><p>一段。</p><h2>方法</h2><p>arXiv:2305.18290</p>"
    write(run / "shots" / "db.json", json.dumps({"anns": anns, "notes": [{"title": "DPO", "tags": tag, "html": note}]}, ensure_ascii=False))
    conv = run / "data" / "tmp" / "scholium" / att
    write(conv / "config.json", json.dumps({"core_color": "#FF6666"}))
    write(run / "data" / "storage" / att / "paper.pdf", "%PDF-1.4\n")
    dry = {"missed": [], "translation_warnings": [{"i": 1}, {"i": 2}], "style_warnings": []}
    final = {"applied": True, "translation_warnings": [{"i": 2}], "style_warnings": [{"kind": "overlap"}], "layout_warnings": [{"reason": "overlap"}],
             "missed": [{"text": "x"}]}
    use = lambda i, name, inp: {"type": "assistant", "message": {"id": "msg_%d" % i, "content": [{"type": "tool_use", "id": "t%d" % i, "name": name, "input": inp}],
                                                                  "usage": {"input_tokens": 1, "cache_read_input_tokens": 1000 * i, "output_tokens": 10}}}
    res = lambda i, text, err=False: {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t%d" % i, "content": text, "is_error": err}]}}
    events = [json.loads(STREAM[0]),
              use(1, "Read", {"file_path": "C:/x/sentences.txt", "limit": 400}), res(1, "s" * 100),
              use(2, "Read", {"file_path": "C:/x/sentences.txt", "offset": 400, "limit": 400}), res(2, "s" * 50),
              use(3, "Read", {"file_path": "C:/skill/references/style-zh.md"}), res(3, "style"),
              use(4, "Bash", {"command": "python scholium.py --config c.json"}), res(4, "report:\n" + json.dumps(dry)),
              use(5, "Bash", {"command": "python scholium.py --config c.json"}), res(5, "Traceback (most recent call last):\nconfig error: bad", True),
              use(6, "PowerShell", {"command": "python scholium.py --config c.json --apply"}), res(6, json.dumps(final)),
              {"type": "scholium", "subtype": "counts", "highlights": 4, "core": 2, "margin": 1, "notes": 0, "readingNotes": 1},
              json.loads(STREAM[3])]
    write(conv / "conversations" / "annotate-claude-1.jsonl", "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n")
    return str(run)


def test_a_run_is_scored(tmp_path):
    e = ev.evaluate(fixture_run(tmp_path), pdf_refs=lambda pdf: 3)
    assert e["run"] == "eval-dpo" and e["arxiv"] == "2305.18290" and e["commit"] == "abc1234" and e["model"] == "claude-haiku-5-5"
    assert (e["cost_usd"], e["turns"], e["runs"], e["cache_read"], e["thinking_tokens"], e["wall_s"]) == (0.0268, 16, 1, 561287, 9167, 130)
    assert e["closing_line"] == "Done: 35 highlights, 14 core."
    assert e["highlights"] == 4 and e["core"] == 2   # colours compared without case; the user's own highlight is not counted
    assert e["highlights_per_page"] == {"1": 1, "2": 1, "3": 1, "4": 1} and e["pages_with_highlights"] == 4
    assert e["references_page"] == 3 and e["highlights_after_references"] == 2 and e["share_after_references"] == 0.5
    assert e["comments_empty"] == 1 and e["comments_copy_english"] == 1 and e["margin_notes"] == 1 and e["sticky_notes"] == 0
    assert e["sentences_reads"] == ["1+400", "400+400"] and e["read_files"] == ["style-zh.md"]
    assert (e["dry_runs"], e["dry_runs_failed"], e["applies"], e["applied"], e["tool_errors"]) == (2, 1, 1, True, 1)
    assert e["dry_run_errors"] == ["config error: bad"]
    assert (e["translation_warnings_first"], e["translation_warnings_final"], e["overlaps"], e["missed"]) == (2, 1, 2, 1)
    assert e["tool_calls"] == {"Read": 3, "dry run": 2, "apply": 1}
    assert e["card"]["highlights"] == 4
    assert (e["reading_notes"], e["reading_note_h1"], e["reading_note_headings"], e["reading_note_paragraphs"], e["reading_note_citation"]) == (1, True, 3, 2, True)
    assert e["stopped"] is False and e["safe"] is True


def test_a_run_without_a_log(tmp_path):
    run = tmp_path / "empty"
    write(run / "probe-config.json", "{}")
    e = ev.evaluate(str(run))
    assert e["error"] == "no annotation log" and e["arxiv"] == "empty"
    assert "no annotation log" in ev.report_table([e])


def test_the_references_page_of_a_pdf(tmp_path):
    pytest.importorskip("pymupdf")
    smoke = live.smoke
    pdf = smoke.make_pdf(str(tmp_path / "p.pdf"), [[("Introduction", 12), ("Text.", 11)], [("References", 12), ("[1] A paper.", 11)]])
    assert ev.ref_page(pdf) == 2
    assert ev.ref_page(smoke.make_pdf(str(tmp_path / "q.pdf"), [[("No list here", 12)]])) is None


def test_tables_and_the_comparison(tmp_path):
    e = ev.evaluate(fixture_run(tmp_path), pdf_refs=lambda pdf: 3)
    table = ev.score_table([e])
    assert table.splitlines()[0] == "| metric | eval-dpo | total |" and "| cost (USD) | 0.0268 | 0.0268 |" in table
    report = ev.report_table([e])
    assert report.splitlines()[0].startswith("| run | paper | model | cost |") and "Done: 35 highlights, 14 core." in report
    base = dict(e, run="eval-dpo-old", cost_usd=0.02, highlights=4, read_files=["SKILL.md"])
    cmp = ev.compare_table([e], [base, dict(base, run="second")], ev.SCORE_ROWS)
    assert "| baseline run | eval-dpo-old |" in cmp
    assert "| cost (USD) | 0.02 → 0.0268 (+0.0068) (+34%) |" in cmp and "| highlights | 4 (=) |" in cmp
    other = dict(e, arxiv="1512.03385")
    assert "| baseline run | (none) |" in ev.compare_table([other], [base], ev.REPORT_ROWS)
    assert ev.delta(None, 3) == " → 3" and ev.delta(True, True) == "True (=)" and ev.delta(0, 2) == "0 → 2 (+2)"


def test_a_baseline_has_no_paths_of_the_machine(tmp_path):
    e = ev.evaluate(fixture_run(tmp_path), pdf_refs=lambda pdf: None)
    ev.write_baseline([e], str(tmp_path / "base"))
    text = open(str(tmp_path / "base.json"), encoding="utf8").read()
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text and json.dumps(str(tmp_path))[1:-1] not in text
    assert json.loads(text)["papers"][0]["run"] == "eval-dpo"
    assert open(str(tmp_path / "base.md"), encoding="utf8").read().startswith("| metric | eval-dpo |")


def test_the_calls_report(tmp_path):
    rf = ev.run_files(fixture_run(tmp_path))
    text = ev.calls_report(ev.events_of(rf["logs"]))
    assert "#1  m0  Read" in text and "sentences.txt offset=None limit=400" in text and "ERROR" in text
    assert "context per API message" in text and "m4  ctx    5001" in text


# ---- the evaluation set ----
def test_the_eval_set():
    data = ev.load_set()
    assert {p["name"] for p in data["papers"]} == {"dpo", "ddpm", "resnet", "distill"}
    for p in data["papers"]:
        assert re.fullmatch(r"\d{4}\.\d{5}", p["arxiv"]) and p["fields"]["archiveID"] == "arXiv:" + p["arxiv"]
        assert re.fullmatch(r"https://arxiv\.org/pdf/%sv\d+" % re.escape(p["arxiv"]), p["pdf"]) and re.fullmatch(r"[0-9a-f]{64}", p["sha256"])
        assert p["fields"]["title"] and p["creators"] and p["itemType"] == "preprint"
    assert data["run"]["model"] == "haiku" and data["run"]["max_msgs"] > 0
    assert not [k for k in data["run"] if "budget" in k]


def test_the_runs_are_interleaved():
    papers = [{"name": "dpo", "arxiv": "2305.18290"}, {"name": "ddpm", "arxiv": "2006.11239"}]
    assert [t for t, _, _ in ev.plan(papers, ["HEAD"], 1)] == ["eval-dpo", "eval-ddpm"]
    runs = ev.plan(papers, ["v0.2.2", "HEAD~1"], 2, only="2305.18290")
    assert [(t, r) for t, _, r in runs] == [("eval-dpo-v0.2.2-1", "v0.2.2"), ("eval-dpo-HEAD-1-1", "HEAD~1"),
                                            ("eval-dpo-v0.2.2-2", "v0.2.2"), ("eval-dpo-HEAD-1-2", "HEAD~1")]
    with pytest.raises(ValueError, match="nope"):
        ev.plan(papers, ["HEAD"], 1, only="dpo,nope")


def test_the_papers_folder(tmp_path):
    assert ev.find_pdf(str(tmp_path), "2305.18290") is None
    flat = write(tmp_path / "2305.18290.pdf", "%PDF")
    nested = write(tmp_path / "2006.11239" / "paper.pdf", "%PDF")
    assert ev.find_pdf(str(tmp_path), "2305.18290") == flat and ev.find_pdf(str(tmp_path), "2006.11239") == nested


def test_the_set_does_not_start_without_its_papers(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ev.subprocess, "Popen", lambda *a, **k: pytest.fail("a run started"))
    assert ev.main(["run", "--zotero", "z.exe", "--papers", str(tmp_path), "--port", "23149", "--out", str(tmp_path / "out")]) == 2
    err = capsys.readouterr().err
    assert "https://arxiv.org/pdf/2305.18290v3" in err and "1503.02531.pdf" in err
