"""The throwaway-Zotero smoke tools (scripts/smoke): their pure parts, without starting Zotero. The runner must never
point anything at the user's Zotero (port 23119), must isolate the throwaway's folders and environment, and must end
only its own processes."""
import importlib.util
import json
import os
import re
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMOKE = os.path.join(ROOT, "scripts", "smoke")


def load(name):
    spec = importlib.util.spec_from_file_location("smoke_" + name, os.path.join(SMOKE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


smoke = load("smoke")


# ---- the user's Zotero is never the target ----
@pytest.mark.parametrize("port", [23119, "23119"])
def test_the_users_port_is_refused(port):
    with pytest.raises(ValueError, match="23119"):
        smoke.check_port(port)


@pytest.mark.parametrize("port", [80, 70000, "abc", None])
def test_other_bad_ports_are_refused(port):
    with pytest.raises(ValueError):
        smoke.check_port(port)


def test_a_free_port_is_taken():
    assert smoke.check_port(23129) == 23129
    assert smoke.check_port("23149") == 23149


def test_prefs_refuse_the_users_port():
    with pytest.raises(ValueError):
        smoke.make_prefs("d", 23119, "zh-CN", True)


def test_the_command_line_refuses_the_users_port(capsys):
    with pytest.raises(SystemExit) as e:
        smoke.main(["--zotero", "nowhere.exe", "--port", "23119", "--fake", "f.exe"])
    assert e.value.code == 2
    assert "23119" in capsys.readouterr().err


def test_the_cli_child_refuses_the_users_port():
    child = load("cli_child")
    with pytest.raises(SystemExit, match="23119"):
        child.main(["--cli", "scholium.py", "--port", "23119", "--", "--config", "c.json"])


# ---- user.js ----
def prefs_of(text):
    out = {}
    for line in text.splitlines():
        m = re.fullmatch(r'user_pref\("([^"]+)", (.*)\);', line)
        assert m, line
        out[m.group(1)] = json.loads(m.group(2))
    return out


def test_user_js_has_the_throwaway_settings():
    p = prefs_of(smoke.user_js(smoke.make_prefs(r"C:\run\data", 23129, "zh-CN", local_api=False, claude_path=r"C:\fake\fakeclaude.exe")))
    assert p["extensions.zotero.firstRun2"] is False   # else zotero.org/start opens in the user's browser
    assert p["extensions.zoteroWinWordIntegration.skipInstallation"] is True
    assert p["extensions.zoteroOpenOfficeIntegration.skipInstallation"] is True
    assert p["extensions.zotero.httpServer.port"] == 23129
    assert p["extensions.zotero.httpServer.localAPI.enabled"] is False
    assert p["extensions.zotero.dataDir"] == r"C:\run\data" and p["extensions.zotero.useDataDir"] is True
    assert p["extensions.zotero.sync.autoSync"] is False and p["app.update.enabled"] is False and p["extensions.update.enabled"] is False
    assert p["extensions.autoDisableScopes"] == 0
    assert p["intl.locale.requested"] == "zh-CN"
    assert p["extensions.scholium.claudePath"] == r"C:\fake\fakeclaude.exe"


def test_user_js_local_api_on_and_no_fake_for_the_setup_check():
    p = prefs_of(smoke.user_js(smoke.make_prefs("d", 23159, "en-US", local_api=True)))
    assert p["extensions.zotero.httpServer.localAPI.enabled"] is True
    assert "extensions.scholium.claudePath" not in p   # the setup check finds the real programs itself


# ---- the environment ----
def test_environment_is_isolated(tmp_path):
    run = str(tmp_path / "run")
    base = {"PATH": "C:\\bin", "HOME": "C:\\home", "CLAUDECODE": "1", "CLAUDE_EFFORT": "xhigh", "Claude_Pid": "7",
            "CLAUDE_CONFIG_DIR": "C:\\Users\\someone\\.claude", "CODEX_HOME": "C:\\Users\\someone\\.codex",
            "TEMP": "C:\\Temp", "TMP": "C:\\Temp", "APPDATA": "C:\\AppData", "ZOTERO_DATA_DIR": "D:\\Zotero"}
    kept = dict(base)
    env = smoke.make_env(base, run, fake_dir=os.path.join(run, "fake"), extra_path=["C:\\agents"])
    assert base == kept   # the caller's environment is not changed
    for k in ("TEMP", "TMP", "APPDATA", "ZOTERO_DATA_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "SCHOLIUM_FAKE_DIR"):
        assert os.path.commonpath([env[k], run]) == run, k
    assert not [k for k in env if k.upper().startswith("CLAUDE") and k != "CLAUDE_CONFIG_DIR"]
    assert env["HOME"] == "C:\\home"
    assert env["PATH"].split(os.pathsep)[:2] == ["C:\\agents", "C:\\bin"]


def test_environment_without_fake_or_extra_path(tmp_path):
    env = smoke.make_env({"PATH": "p"}, str(tmp_path))
    assert "SCHOLIUM_FAKE_DIR" not in env and env["PATH"] == "p"


# ---- ending only the run's own processes ----
def test_only_processes_naming_the_profile_are_ours():
    profile = r"C:\scratch\runs\a\profile"
    rows = [
        (1, r'"C:\Zotero10\zotero.exe" -no-remote -profile "C:\scratch\runs\a\profile" -ZoteroDebugText'),
        (2, r'C:\Zotero10\zotero.exe -no-remote -profile C:/scratch/runs/a/profile -ZoteroDebugText'),
        (3, r'"C:\Zotero10\zotero.exe" -no-remote -profile "C:\scratch\runs\a\profile2"'),
        (4, r'"D:\Software\Zotero\zotero.exe"'),   # the user's own
        (5, r'"D:\Software\Zotero\zotero.exe" -contentproc -parentBuildID 1 -prefsHandle 1:2 -appDir "D:\Software\Zotero\app" 5 tab'),
        (6, None),
        (7, r'c:\SCRATCH\runs\A\profile'),
        (8, r'"C:\Zotero10\zotero.exe" -profile "C:\scratch\runs\a\profile-old"'),
    ]
    assert smoke.pick_ours(rows, profile) == [1, 2, 7]


def test_a_profile_path_with_a_trailing_separator_still_matches():
    assert smoke.profile_matches(r'zotero.exe -profile "C:\r\profile"', "C:\\r\\profile\\")


# ---- checks ----
def test_checks_are_parsed_in_the_probes_order():
    assert smoke.parse_checks("all") == smoke.ALL_CHECKS
    assert smoke.parse_checks("fake") == smoke.FAKE_CHECKS
    assert smoke.parse_checks("reader, section") == ["section", "reader"]
    with pytest.raises(ValueError, match="nonsense"):
        smoke.parse_checks("section,nonsense")


# ---- packages ----
def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:   # the bytes as given: text mode would write CRLF on Windows
        f.write(text.encode("utf8"))


def make_plugin(tmp_path):
    plugin = tmp_path / "plugin"
    write(str(plugin / "manifest.json"), json.dumps({"version": "1.0", "applications": {"zotero": {"id": "scholium@zotero-scholium"}}}))
    write(str(plugin / "bootstrap.js"), "function startup() {}\n")
    write(str(plugin / "content" / "scholium.css"), ".x {}\n")
    write(str(plugin / "__pycache__" / "junk.pyc"), "x")
    skill = tmp_path / "skill"
    write(str(skill / "SKILL.md"), "---\nname: zotero-scholium\n---\n")
    write(str(skill / "references" / "style-zh.md"), "中文风格\n")
    write(str(skill / "scripts" / "scholium.py"), "print(1)\n")
    write(str(skill / "scripts" / "__pycache__" / "scholium.cpython-311.pyc"), "x")
    return str(plugin), str(skill)


def test_the_package_gets_the_hook_the_version_and_the_skill(tmp_path):
    plugin, skill = make_plugin(tmp_path)
    out = str(tmp_path / "p.xpi")
    pid, carried, files = smoke.build_plugin_xpi(plugin, out, "171630", skill)
    assert pid == "scholium@zotero-scholium" and carried
    assert sorted(files) == ["SKILL.md", "references/style-zh.md", "scripts/scholium.py"]
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert json.loads(z.read("manifest.json"))["version"] == "1.0.9171630"   # newer than the release it is built from
        assert "Zotero.__scholium = ScholiumRunner" in z.read("bootstrap.js").decode()
        assert z.read("content/skill/zotero-scholium/references/style-zh.md") == "中文风格\n".encode("utf8")   # byte for byte
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]


def test_a_package_carrying_a_skill_keeps_its_own(tmp_path):
    plugin, skill = make_plugin(tmp_path)
    first = str(tmp_path / "first.xpi")
    smoke.build_plugin_xpi(plugin, first, "1", skill)
    other = tmp_path / "other"
    write(str(other / "SKILL.md"), "another\n")
    _, carried, files = smoke.build_plugin_xpi(first, str(tmp_path / "second.xpi"), "2", str(other))
    assert carried and files["SKILL.md"].startswith(b"---")


def test_a_package_without_a_skill(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    _, carried, files = smoke.build_plugin_xpi(plugin, str(tmp_path / "p.xpi"), "1", None)
    assert not carried and files == {}


# ---- the paper ----
def test_the_pdf_is_well_formed(tmp_path):
    path = smoke.make_pdf(str(tmp_path / "t.pdf"), [[("A (paren) line", 11)], [("Second page", 11)]])
    data = open(path, "rb").read()
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert data.count(b"/Type /Page ") == 2 and b"\\(paren\\)" in data
    xref = int(data.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    entries = data[xref:].split(b"\n")[3:3 + 6]
    for n, entry in enumerate(entries, 1):
        offset = int(entry[:10])
        assert data[offset:].startswith(b"%d 0 obj" % n)


def test_the_pdf_reads_as_text(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(smoke.make_pdf(str(tmp_path / "t.pdf")))
    assert doc.page_count == 2
    assert "The protocol selects a passage, asks a question about it, and records the answer." in doc[1].get_text()


# ---- the fake and the expectations ----
def test_the_fake_scripts_are_stream_json():
    folder = os.path.join(SMOKE, "fakeclaude", "scripts")
    names = sorted(os.listdir(folder))
    assert names == ["annotate-ok.jsonl", "noskill.jsonl", "pymupdf.jsonl", "signedout.jsonl"]
    events = {}
    for name in names:
        events[name] = []
        for line in open(os.path.join(folder, name), encoding="utf8"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("//"):
                events[name].append(json.loads(line))
    init = lambda n: next(e for e in events[n] if e.get("subtype") == "init")
    assert "zotero-scholium" not in init("noskill.jsonl")["skills"]
    assert "zotero-scholium" in init("pymupdf.jsonl")["skills"]
    assert any(e.get("error") == "authentication_failed" for e in events["signedout.jsonl"])
    assert "#exit 1" in open(os.path.join(folder, "signedout.jsonl"), encoding="utf8").read()
    assert "PyMuPDF is not installed" in open(os.path.join(folder, "pymupdf.jsonl"), encoding="utf8").read()


def test_the_probe_asks_the_plugin_for_texts_it_has():
    """The probe takes the sentences it expects from the running plugin (text(key)), so a check follows the plugin's
    wording; each key it asks for must be one of the plugin's texts."""
    probe = open(os.path.join(SMOKE, "probe", "bootstrap.js"), encoding="utf8").read()
    keys = set(re.findall(r'\bt\("(\w+)"', probe))
    assert {"notSignedIn", "pymupdfMissing", "annotNoneWarn", "askScholium", "installSkill", "skillNotCarried", "checkLabel",
            "localApiOff"} <= keys
    plugin = open(os.path.join(ROOT, "plugin", "scholium", "bootstrap.js"), encoding="utf8").read()
    table = plugin[plugin.index("  text(key, ...args) {"):]
    for key in keys:
        assert re.search(r"\n\s+%s: " % key, table), key
    labels = table[table.index("checkLabel:"):][:400]
    for label in ("localApi", "claudeSkill"):   # the setup check's lines it clicks
        assert re.search(r"\b%s: " % label, labels), label


def test_every_locale_has_a_question():
    assert set(smoke.QUESTION) == {"zh-CN", "en-US"} and all(smoke.QUESTION.values())


def test_no_personal_paths_in_the_tools():
    for root, dirs, files in os.walk(SMOKE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            text = open(os.path.join(root, f), encoding="utf8", errors="replace").read()
            assert not re.search(r"C:\\\\?Users\\\\?lrv|scratchpad|\blrv\b", text, re.I), f


# ---- where the checks run, and the runner's own checks ----
def test_the_runs_are_planned_by_where_they_run():
    assert smoke.plan(smoke.ALL_CHECKS) == {"fake": smoke.PROBE_FAKE, "after": ["port", "adddir"], "setup": ["setup", "copy"], "cli": ["scanned"]}
    assert smoke.plan(["port"]) == {"fake": ["pymupdf"], "after": ["port"], "setup": [], "cli": []}   # a run to record
    assert smoke.plan(["copy"])["setup"] == ["setup", "copy"]   # Copy is the setup check's button
    fake = smoke.plan(smoke.parse_checks("fake"))
    assert fake["setup"] == [] and fake["cli"] == ["scanned"] and "reselect" in fake["fake"]


def test_new_checks_are_known():
    assert smoke.parse_checks("scanned,copy,reselect,adddir,port") == ["reselect", "port", "adddir", "copy", "scanned"]


def test_a_recorded_call_is_parsed():
    c = smoke.parse_call("signedout\nENV SCHOLIUM_ZOTERO_PORT=23129\n-p\n--add-dir\nC:\\h\\.claude\\skills\\zotero-scholium\n---\nthe prompt\n---\nmore")
    assert c["name"] == "signedout" and c["env"] == {"SCHOLIUM_ZOTERO_PORT": "23129"}
    assert c["args"] == ["-p", "--add-dir", "C:\\h\\.claude\\skills\\zotero-scholium"] and c["stdin"] == "the prompt\n---\nmore"
    old = smoke.parse_call("answer\n-p\n---\nx")   # a fake built before it recorded the environment
    assert old["env"] == {} and old["args"] == ["-p"]


def call(name="pymupdf", port="23129", add_dir=None):
    env = "" if port is None else f"ENV SCHOLIUM_ZOTERO_PORT={port}\n"
    args = "-p\n" + (f"--add-dir\n{add_dir}\n" if add_dir else "")
    return smoke.parse_call(f"{name}\n{env}{args}---\nprompt")


def test_the_port_check():
    assert smoke.check_port_env([call("MODELS", port=""), call(), call("signedout")], 23129)[0]
    assert not smoke.check_port_env([call(port="23119")], 23129)[0]
    assert not smoke.check_port_env([call(port=None)], 23129)[0]   # not recorded
    assert not smoke.check_port_env([call("MODELS")], 23129)[0]   # no agent run


def test_the_add_dir_check_both_ways():
    folder = "C:\\run\\claude-config\\skills\\zotero-scholium"
    at = lambda c, t: dict(c, at=t)
    # the folder appears at t=10 (the skill check installs it): runs before get no --add-dir, runs after get it
    calls = [at(call("MODELS"), 1), at(call(), 2), at(call("noskill"), 5), at(call("annotate-ok", add_dir=folder), 12)]
    ok, info = smoke.check_add_dir(calls, folder, installed_at=10)
    assert ok and info["cases seen"] == [False, True]
    assert smoke.check_add_dir([at(call(add_dir="c:/run/claude-config/skills/zotero-scholium"), 12)], folder, 10)[0]   # however written
    assert not smoke.check_add_dir([at(call(), 12)], folder, 10)[0]   # there, not given
    assert not smoke.check_add_dir([at(call(add_dir=folder), 2)], folder, 10)[0]   # given before it was there
    assert smoke.check_add_dir([at(call(), 2)], folder, None)[0]   # never there, never given
    assert not smoke.check_add_dir([at(call(add_dir=folder), 2)], folder, None)[0]


def test_the_fake_records_the_port():
    src = open(os.path.join(SMOKE, "fakeclaude", "fakeclaude.cs"), encoding="utf8").read()
    assert 'GetEnvironmentVariable("SCHOLIUM_ZOTERO_PORT")' in src and "ENV SCHOLIUM_ZOTERO_PORT=" in src


def test_the_scanned_pdf_is_image_only(tmp_path):
    data = open(smoke.make_scanned_pdf(str(tmp_path / "s.pdf")), "rb").read()
    assert data.startswith(b"%PDF-1.4") and data.count(b"/Type /Page ") == 2 and b"/Subtype /Image" in data and b" Tj" not in data


def test_the_scanned_pdf_reads_as_a_scan(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(smoke.make_scanned_pdf(str(tmp_path / "s.pdf")))
    for page in doc:
        assert page.get_text().strip() == ""
        assert any(abs(pymupdf.Rect(i["bbox"]) & page.rect) >= abs(page.rect) / 2 for i in page.get_image_info())

