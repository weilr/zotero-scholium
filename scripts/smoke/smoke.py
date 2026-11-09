#!/usr/bin/env python3
"""Smoke checks of the Scholium plugin in a THROWAWAY Zotero, with a fake Claude Code (no model is called).

    python scripts/smoke/smoke.py --zotero "C:/Program Files/Zotero/zotero.exe" --port 23129 --fake <fakeclaude.exe>

It starts the given zotero.exe with a new profile, data directory, APPDATA and TEMP under --out (Zotero empties
<TEMP>/Zotero when it quits, which must not be the TEMP of a Zotero the user runs), installs the plugin (a source folder
such as plugin/scholium, or a built .xpi) and a probe plugin (probe/bootstrap.js), and the probe drives the checks:

  section    the item pane's Scholium section renders, both tabs
  localapi   Annotate with Zotero's local API off: the confirmation (accepted), the pref turns on, the run starts and ends
  signedout  a "not signed in" stream from Claude Code: the plugin's sentence, not "Please run /login"
  pymupdf    a run whose tool result says PyMuPDF is missing: the card says what to install
  reselect   after a run, another item, then the paper again: its annotation session's card is back within seconds
  apply      the skill's CLI writes through /scholium/apply (upper-case colours arrive lower-case, one note); a write
             that Zotero rejects leaves no second note
  reader     Ask Scholium in the reader's context menu puts the passage above the Chat box
  groups     a paper in a local group library: the one-time confirmation before the first Annotate (not again), the
             skill's CLI writes into the group with group_id and list answers its libraryID; with the group not
             editable, the Annotations tab says so, Annotate is off and the write is refused
  skill      Install the skill and retry (from a package that carries the skill in content/skill, or the hint without)
  port       the agent's environment has SCHOLIUM_ZOTERO_PORT = this throwaway's port (from the fake's recorded calls)
  adddir     the agent gets --add-dir <CLAUDE_CONFIG_DIR>/skills/zotero-scholium exactly when that folder is there (the
             run's own, empty until the skill check installs the skill: a full run sees both cases)
  setup      the settings page's setup check, with the real claude and codex found by the plugin (this runs
             `claude auth status` and `codex app-server`, which make no model calls); a second Zotero start
  copy       the setup check's Copy puts "Scholium <version> · Zotero <version> …" and its lines on the clipboard
             (the system's: the text that was on it is put back)
  scanned    the skill's extract stops on an image-only PDF with exit code 3 and the no-text-layer error (no Zotero)

The user's own Zotero is never contacted: the port must not be 23119, netstat for :23119 is printed before and after,
and only processes whose command line names this run's profile are ended. CLAUDE* variables of the calling shell are
not passed on; CLAUDE_CONFIG_DIR and CODEX_HOME point at empty folders of the run, so nothing is installed into the
user's ~/.claude or ~/.codex. Exit code 0 when every check passed.
"""
import argparse
import hashlib
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
USER_PORT = 23119
PROBE_FAKE = ["section", "localapi", "signedout", "pymupdf", "reselect", "apply", "reader", "groups", "skill"]   # the probe's, fake Claude
RUNNER_FAKE = ["port", "adddir"]   # read from the fake's recorded calls once the fake session ends
SETUP_CHECKS = ["setup", "copy"]   # a second Zotero start, with the real programs
CLI_CHECKS = ["scanned"]           # the skill's CLI alone, no Zotero
FAKE_CHECKS = PROBE_FAKE + RUNNER_FAKE + CLI_CHECKS   # all that need no real claude or codex
ALL_CHECKS = PROBE_FAKE + RUNNER_FAKE + SETUP_CHECKS + CLI_CHECKS
PROBE_ID = "scholium-smokeprobe@test"
HOOK = ("\n// smoke probe only: the runner and the toggle where the probe can reach them\nvar __smokeStartup = startup;\n"
        "startup = async function (data, reason) { await __smokeStartup(data, reason); "
        "Zotero.__scholium = ScholiumRunner; Zotero.__scholiumToggle = ScholiumToggle; };\n")

# the question the signedout check sends in the Chat tab; the sentences a check expects are asked of the running plugin
# (its text()), so the checks follow its wording
QUESTION = {"zh-CN": "这篇论文讲什么？", "en-US": "What is this paper about?"}

# the paper of the throwaway items: two pages of plain sentences
PDF_PAGES = [
    [("A Minimal Smoke Test Paper", 16), ("Abstract", 12),
     ("We propose a simple method for testing annotation tools in throwaway libraries.", 11),
     ("The method creates a small document with a few plain sentences of text.", 11),
     ("Each sentence can be highlighted without touching the original file.", 11),
     ("Our experiments show that the approach is fast and reliable in practice.", 11)],
    [("2 Evaluation", 13),
     ("In the second section we describe the evaluation protocol in detail.", 11),
     ("The protocol selects a passage, asks a question about it, and records the answer.", 11),
     ("Results are reported for two versions of the reference manager.", 11)],
]


# ---------------------------------------------------------------------------------------------------------------------
# pure parts (tests/test_smoke_tools.py)
# ---------------------------------------------------------------------------------------------------------------------
def check_port(port):
    """The throwaway's local server port: a number in 1024–65535 that is not the user's Zotero's 23119."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError(f"port must be a number, not {port!r}")
    if port == USER_PORT:
        raise ValueError("port 23119 is the user's own Zotero; choose another (e.g. 23129)")
    if not 1024 <= port <= 65535:
        raise ValueError(f"port {port} is outside 1024–65535")
    return port


def parse_checks(text):
    """'all', 'fake', or a comma list of check names, in the order the probe runs them."""
    text = (text or "all").strip().lower()
    names = ALL_CHECKS if text == "all" else FAKE_CHECKS if text == "fake" else [c.strip() for c in text.split(",") if c.strip()]
    unknown = [c for c in names if c not in ALL_CHECKS]
    if unknown:
        raise ValueError(f"unknown check(s): {', '.join(unknown)}; known: {', '.join(ALL_CHECKS)}")
    return [c for c in ALL_CHECKS if c in names]


def plan(checks):
    """Which checks run where: the probe's in the fake session (with a run to record when only port/adddir are asked
    for), the runner's after it, the setup session's (copy runs inside the setup check), the CLI's."""
    fake = [c for c in PROBE_FAKE if c in checks]
    after = [c for c in RUNNER_FAKE if c in checks]
    if after and not fake:
        fake = ["pymupdf"]   # a fake run whose call is recorded
    setup = [c for c in SETUP_CHECKS if c in checks]
    if setup and "setup" not in setup:
        setup = ["setup"] + setup
    return {"fake": fake, "after": after, "setup": setup, "cli": [c for c in CLI_CHECKS if c in checks]}


def parse_call(text):
    """A call the fake recorded: its script name, its environment lines (ENV NAME=value), its arguments, its input."""
    head, _, stdin = text.partition("\n---\n")
    lines = head.split("\n")
    env = {}
    rest = lines[1:]
    while rest and rest[0].startswith("ENV "):
        k, _, v = rest[0][4:].partition("=")
        env[k] = v
        rest = rest[1:]
    return {"name": lines[0].strip(), "env": env, "args": rest, "stdin": stdin}


def check_port_env(calls, port):
    """Every agent run (not the model-list call) got SCHOLIUM_ZOTERO_PORT = the throwaway's port."""
    runs = [c for c in calls if c["name"] != "MODELS"]
    got = sorted({c["env"].get("SCHOLIUM_ZOTERO_PORT", "(not recorded)") for c in runs})
    return bool(runs) and got == [str(port)], {"runs": len(runs), "SCHOLIUM_ZOTERO_PORT": got, "expected": str(port)}


def check_add_dir(calls, folder, installed_at=None):
    """Every agent run gets --add-dir <folder> (Claude Code's skill folder: <CLAUDE_CONFIG_DIR>/skills/zotero-scholium)
    exactly when the folder was there as the run started: installed_at is when it got there (its SKILL.md, written
    last), None when it never did; a call's "at" is when it started."""
    runs = [c for c in calls if c["name"] != "MODELS"]
    rows = []
    for c in runs:
        a = c["args"]
        given = any(_norm(a[i + 1]) == _norm(folder) for i in range(len(a) - 1) if a[i] == "--add-dir")
        there = installed_at is not None and c.get("at", float("inf")) >= installed_at
        rows.append({"call": c["name"], "folder there": there, "--add-dir": given})
    cases = sorted({r["folder there"] for r in rows})
    return bool(runs) and all(r["folder there"] == r["--add-dir"] for r in rows), {"folder": folder, "runs": rows, "cases seen": cases}


def read_calls(folder):
    """The fake's recorded calls in order, each with "at": when it was written (as the call started)."""
    out = []
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        path = os.path.join(folder, f)
        with open(path, encoding="utf8", errors="replace") as h:
            out.append(dict(parse_call(h.read()), at=os.path.getmtime(path)))
    return out


def make_prefs(data_dir, port, locale, local_api, claude_path=None):
    """The throwaway profile's preferences."""
    prefs = {
        "extensions.zotero.dataDir": data_dir, "extensions.zotero.useDataDir": True,
        "extensions.zotero.firstRun2": False,   # else a new profile opens zotero.org/start in the default browser
        "extensions.zotero.httpServer.port": check_port(port), "extensions.zotero.httpServer.localAPI.enabled": bool(local_api),
        "extensions.autoDisableScopes": 0, "extensions.enabledScopes": 15,
        # a new profile would install the Word and LibreOffice add-ins into the user's applications
        "extensions.zoteroWinWordIntegration.skipInstallation": True, "extensions.zoteroOpenOfficeIntegration.skipInstallation": True,
        "app.update.auto": False, "app.update.enabled": False, "extensions.update.enabled": False,
        "extensions.zotero.sync.autoSync": False,
        "intl.locale.requested": locale, "ui.systemUsesDarkTheme": 0, "layout.spellcheckDefault": 0,
        "widget.windows.window_occlusion_tracking.enabled": False, "dom.min_background_timeout_value": 4,
        "extensions.zotero.debug.store": True, "extensions.zotero.debug.store.limit": 2000000,
        "extensions.scholium.agent": "claude", "extensions.scholium.showAnnotations": True,
    }
    if claude_path:
        prefs["extensions.scholium.claudePath"] = claude_path
    return prefs


def user_js(prefs):
    return "".join(f'user_pref("{k}", {json.dumps(v)});\n' for k, v in prefs.items())


def make_env(base, run, fake_dir=None, extra_path=()):
    """Zotero's environment: the caller's without its CLAUDE* variables (a Claude Code session's) and CODEX_HOME; TEMP,
    TMP, APPDATA and ZOTERO_DATA_DIR inside the run; CLAUDE_CONFIG_DIR and CODEX_HOME empty folders of the run."""
    env = {k: v for k, v in base.items() if not k.upper().startswith("CLAUDE") and k.upper() != "CODEX_HOME"}
    env.update(TEMP=os.path.join(run, "temp"), TMP=os.path.join(run, "temp"), APPDATA=os.path.join(run, "appdata"),
               ZOTERO_DATA_DIR=os.path.join(run, "data"), CLAUDE_CONFIG_DIR=os.path.join(run, "claude-config"),
               CODEX_HOME=os.path.join(run, "codex-home"))
    if fake_dir:
        env["SCHOLIUM_FAKE_DIR"] = fake_dir
    if extra_path:
        env["PATH"] = os.pathsep.join(list(extra_path) + [env.get("PATH", "")])
    return env


def agent_dirs(appdata):
    """The folders of the claude and codex executables of their npm packages under the user's APPDATA (which the
    throwaway's own APPDATA hides from the plugin's search), for the setup check's PATH."""
    if not appdata:
        return []
    npm = os.path.join(appdata, "npm", "node_modules")
    dirs = [os.path.join(npm, "@anthropic-ai", "claude-code", "bin"),
            os.path.join(npm, "@openai", "codex", "node_modules", "@openai", "codex-win32-x64", "vendor", "x86_64-pc-windows-msvc", "bin")]
    return [d for d in dirs if os.path.isdir(d)]


def _norm(path):
    """A Windows path, compared without case and separator differences on any system."""
    return ntpath.normcase(ntpath.normpath(str(path).strip().strip('"')))


def profile_matches(cmdline, profile):
    """Whether a process's command line names this profile folder (and not another whose name starts the same)."""
    if not cmdline:
        return False
    line, prof = str(cmdline).replace("/", "\\").lower(), _norm(profile).lower()
    start = line.find(prof)
    while start >= 0:
        after = line[start + len(prof): start + len(prof) + 1]
        if after in ("", '"', " ", "\\"):
            return True
        start = line.find(prof, start + 1)
    return False


def pick_ours(rows, profile):
    """The process ids among (pid, command line) rows that name this profile."""
    return [pid for pid, cmd in rows if profile_matches(cmd, profile)]


def plugin_entries(src):
    """{path in the package: bytes} of a plugin folder or .xpi (no __pycache__ or .pyc)."""
    out = {}
    if os.path.isfile(src):
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():
                if not n.endswith("/"):
                    out[n] = z.read(n)
        return out
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".pyc"):
                continue
            p = os.path.join(root, f)
            out[os.path.relpath(p, src).replace("\\", "/")] = open(p, "rb").read()
    return out


def skill_entries(skill_dir):
    """{relative path: bytes} of a skill folder (no __pycache__ or .pyc)."""
    return {k: v for k, v in plugin_entries(skill_dir).items()}


def build_plugin_xpi(src, out, build, skill_dir=None):
    """The plugin as a package for the throwaway profile: its manifest's version given a fourth part (9 and the build
    number, so that it is newer than the release and the skill's CLI takes it), the probe hook appended to bootstrap.js,
    and the skill added in content/skill/zotero-scholium when skill_dir is given and the package has none.
    Returns (add-on id, whether it carries the skill, the skill's files)."""
    entries = plugin_entries(src)
    manifest = json.loads(entries["manifest.json"].decode("utf8"))
    manifest["version"] = ".".join(str(manifest["version"]).split(".")[:3]) + ".9" + str(build)
    entries["manifest.json"] = json.dumps(manifest, indent=2).encode("utf8")
    entries["bootstrap.js"] = entries["bootstrap.js"] + HOOK.encode("utf8")
    prefix = "content/skill/zotero-scholium/"
    if skill_dir and not any(n.startswith(prefix) for n in entries):
        for rel, data in skill_entries(skill_dir).items():
            entries[prefix + rel] = data
    skill = {n[len(prefix):]: data for n, data in entries.items() if n.startswith(prefix)}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(entries):
            z.writestr(n, entries[n])
    return manifest["applications"]["zotero"]["id"], bool(skill), skill


def make_pdf(path, pages=PDF_PAGES):
    """A small PDF of plain Helvetica lines (no dependencies), one list of (text, size) per page."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % (4 + 2 * i) for i in range(len(pages))), len(pages))).encode(),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for i, lines in enumerate(pages):
        y, parts = 696, []
        for text, size in lines:
            parts.append("BT /F1 %d Tf 72 %d Td (%s) Tj ET" % (size, y, esc(text)))
            y -= size * 2
        stream = "\n".join(parts).encode("latin-1")
        objects.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                        "/Contents %d 0 R >>" % (5 + 2 * i)).encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for k, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % k + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for o in offsets:
        data += b"%010d 00000 n \n" % o
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    with open(path, "wb") as f:
        f.write(bytes(data))
    return path


def make_scanned_pdf(path, pages=2):
    """A PDF whose pages are an image each and no text, as a scan without OCR (no dependencies)."""
    image = b"\x00\x80\xff\x40"   # 2x2 grey pixels, stretched over the page
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % (4 + 2 * i) for i in range(pages)), pages)).encode(),
               b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 4 >>\nstream\n"
               + image + b"\nendstream"]
    for i in range(pages):
        content = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
        objects.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 3 0 R >> >> "
                        "/Contents %d 0 R >>" % (5 + 2 * i)).encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for k, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % k + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for o in offsets:
        data += b"%010d 00000 n \n" % o
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    with open(path, "wb") as f:
        f.write(bytes(data))
    return path


def scanned_check(a, run):
    """The skill's extract on an image-only PDF: exit code 3 and the no-text-layer error as JSON."""
    os.makedirs(run, exist_ok=True)
    pdf = make_scanned_pdf(os.path.join(run, "scanned.pdf"))
    cmd = [sys.executable, os.path.join(HERE, "cli_child.py"), "--cli", a.cli, "--port", str(a.port), "--",
           "extract", "--pdf", pdf, "--sentences", os.path.join(run, "sentences.json"), "--out", os.path.join(run, "sentences.txt")]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace", env=make_env(os.environ, run), cwd=run, timeout=120)
    try:
        rep = json.loads(p.stdout)
    except ValueError:
        rep = {}
    ok = p.returncode == 3 and "no text layer" in str(rep.get("error", "")) and rep.get("scanned_pages") == rep.get("pages") == 2
    return {"check": "scanned", "pass": ok, "info": {"exit": p.returncode, "report": rep or (p.stdout + p.stderr)[-300:],
                                                      "wrote_sentences": os.path.exists(os.path.join(run, "sentences.json"))}}


def export_git(rev, dest, paths=("plugin/scholium", "skills/zotero-scholium")):
    """These paths (plugin/scholium and skills/zotero-scholium) as committed at rev, byte for byte (no CRLF from
    core.autocrlf), in dest."""
    import io
    import tarfile
    data = subprocess.run(["git", "-C", REPO, "-c", "core.autocrlf=false", "archive", "--format=tar", rev] + list(paths),
                          capture_output=True, check=True).stdout
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            if m.isfile() or m.isdir():
                t.extract(m, dest)
    return dest


def sha256s(files):
    return {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}


# ---------------------------------------------------------------------------------------------------------------------
# processes and ports
# ---------------------------------------------------------------------------------------------------------------------
def netstat_user_port():
    out = subprocess.run("netstat -ano", capture_output=True, text=True, shell=True).stdout
    return [" ".join(l.split()) for l in out.splitlines() if ":%d " % USER_PORT in l + " "]


def zotero_processes():
    """(pid, command line) of every zotero process."""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='zotero.exe'\" | "
              "ForEach-Object { [string]$_.ProcessId + \"`t\" + [string]$_.CommandLine }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    else:
        out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout.replace(" ", "\t", 1)
    rows = []
    for l in out.splitlines():
        pid, _, cmd = l.strip().partition("\t")
        if pid.strip().isdigit() and ("zotero" in cmd.lower() or os.name == "nt"):
            rows.append((int(pid), cmd))
    return rows


def end_ours(profile):
    pids = pick_ours(zotero_processes(), profile)
    for pid in pids:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True)
    return pids


# ---------------------------------------------------------------------------------------------------------------------
# the CLI step of the apply check
# ---------------------------------------------------------------------------------------------------------------------
FIRST_HIGHLIGHTS = [{"page": 1, "text": PDF_PAGES[0][2][0], "core": True, "comment": "我们提出一种在临时文库中测试批注工具的简单方法。"},
                    {"page": 1, "text": PDF_PAGES[0][5][0], "core": False, "comment": "实验表明这种方法在实践中快速而可靠。"}]
SECOND_HIGHLIGHTS = [{"page": 1, "text": PDF_PAGES[0][3][0], "core": True, "comment": "该方法生成一份只含几句普通文字的小文档。"},
                     {"page": 1, "text": PDF_PAGES[0][4][0], "core": False, "comment": "每个句子都可以高亮，而不改动原文件。"}]


def cli_config(req, out_dir, data_dir, note, highlights):
    """The skill's configuration for a CLI step: the paper the probe names (with its group_id or library_id when it is
    in another library than My Library), upper-case colours, a note."""
    cfg = {"pdf": req["pdf"], "item_key": req["item_key"], "attachment_key": req["attachment_key"], "out_dir": out_dir,
           "data_dir": data_dir, "core_color": "#FF6666", "other_color": "#FFD400", "note_html": note, "highlights": highlights}
    for k in ("group_id", "library_id"):
        if req.get(k):
            cfg[k] = int(req[k])
    return cfg


def run_cli(run, port, cli, req, env, name, note, highlights, bad=False, extra=("--apply",)):
    out_dir = os.path.join(run, "cli-" + name)
    os.makedirs(out_dir, exist_ok=True)
    cfg = cli_config(req, out_dir, os.path.join(run, "data"), note, highlights)
    cfg_path = os.path.join(out_dir, "config.json")
    with open(cfg_path, "w", encoding="utf8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    cmd = [sys.executable, os.path.join(HERE, "cli_child.py"), "--cli", cli, "--port", str(port)] + (["--bad"] if bad else []) + \
          ["--", "--config", cfg_path, "--backend", "plugin"] + list(extra)   # the plugin's /scholium/apply, not Zotero 10's local API
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace", env=env, cwd=out_dir, timeout=180)
    for suffix, text in (("stdout", p.stdout), ("stderr", p.stderr)):
        with open(os.path.join(out_dir, suffix + ".txt"), "w", encoding="utf8") as f:
            f.write(text)
    try:
        rep = json.loads(p.stdout)
    except ValueError:
        rep = {"apply_error": (p.stdout + p.stderr)[-400:]}
    keep = {k: rep.get(k) for k in ("applied", "apply_error", "backend", "colors", "result", "missed", "style_warnings", "annotations", "notes", "error")}
    keep["exit"] = p.returncode
    return keep


def write_note(run, name, title, body):
    path = os.path.join(run, name)
    with open(path, "w", encoding="utf8") as f:
        f.write(f"<h1>{title}</h1><p>{body}</p>")
    return path


def endpoint_list(run, port, body):
    """The plugin's /scholium/list, as the CLI asks it (with the token of the run's data folder)."""
    import urllib.request
    port = check_port(port)
    with open(os.path.join(run, "data", "scholium.token"), encoding="utf8") as f:
        token = f.read().strip()
    req = urllib.request.Request("http://127.0.0.1:%d/scholium/list" % port, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Annotate-Token": token})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=60) as r:
            status, text = r.status, r.read().decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf8", "replace")
    try:
        js = json.loads(text)
    except ValueError:
        js = {"raw": text[:300]}
    return {"status": status, "json": {k: (len(v) if isinstance(v, list) else v) for k, v in js.items()}}


def groups_step(run, port, cli, env, req):
    """The groups check's CLI steps: a write with group_id and the plugin's list of the group's PDF; or, with the group
    not editable, a write that must be refused."""
    if req.get("kind") == "readonly":
        return {"apply": run_cli(run, port, cli, req, env, "group-readonly", write_note(run, "group-note2.html", "Group note", "Refused."),
                                 SECOND_HIGHLIGHTS)}
    out = {"apply": run_cli(run, port, cli, req, env, "group-apply", write_note(run, "group-note1.html", "Group note", "In the group."),
                            FIRST_HIGHLIGHTS)}
    out["list"] = endpoint_list(run, port, {"attachmentKey": req["attachment_key"], "groupID": int(req["group_id"])})
    return out


def apply_step(run, port, cli, env, req):
    def note(name, title, body):
        return write_note(run, name, title, body)
    first, second = FIRST_HIGHLIGHTS, SECOND_HIGHLIGHTS
    out = {"run1": run_cli(run, port, cli, req, env, "run1", note("note1.html", "Smoke note", "First write."), first)}
    # a write Zotero rejects (an annotation's sort index it does not accept) with another note: nothing may stay of it
    out["run2"] = run_cli(run, port, cli, req, env, "run2", note("note2.html", "Second smoke note", "A rejected write."), second, bad=True)
    out["list"] = run_cli(run, port, cli, req, env, "list", None, first, extra=("--list",))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# one Zotero start
# ---------------------------------------------------------------------------------------------------------------------
def run_session(a, name, checks, runner_checks=()):
    run = os.path.join(a.out, name)
    if os.path.exists(run):
        shutil.rmtree(run)
    dirs = {k: os.path.join(run, k) for k in ("profile", "data", "appdata", "temp", "shots", "claude-config", "codex-home", "fake")}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(dirs["profile"], "extensions"))
    fake_src = os.path.join(HERE, "fakeclaude")
    shutil.copytree(os.path.join(fake_src, "scripts"), os.path.join(dirs["fake"], "scripts"))
    shutil.copy(os.path.join(fake_src, "models.json"), dirs["fake"])
    with open(os.path.join(dirs["fake"], "next.txt"), "w", encoding="utf8") as f:
        f.write("annotate-ok")
    pdf = make_pdf(os.path.join(run, "smoke.pdf"))

    real_agents = name == "setup"
    prefs = make_prefs(dirs["data"], a.port, a.locale, local_api="localapi" not in checks and not real_agents,
                       claude_path=None if real_agents else a.fake)
    with open(os.path.join(dirs["profile"], "user.js"), "w", encoding="utf8") as f:
        f.write(user_js(prefs))
    plugin_id, carried, skill = build_plugin_xpi(a.plugin, os.path.join(dirs["profile"], "extensions", "PLUGIN.xpi"), time.strftime("%H%M%S"), a.skill)
    os.replace(os.path.join(dirs["profile"], "extensions", "PLUGIN.xpi"), os.path.join(dirs["profile"], "extensions", plugin_id + ".xpi"))
    probe_manifest = {"manifest_version": 2, "name": "Scholium smoke probe", "version": "1.0", "description": "throwaway",
                      "applications": {"zotero": {"id": PROBE_ID, "update_url": "https://example.invalid/u.json",
                                                  "strict_min_version": "6.999", "strict_max_version": "9999.*"}}}
    with zipfile.ZipFile(os.path.join(dirs["profile"], "extensions", PROBE_ID + ".xpi"), "w") as z:
        z.writestr("manifest.json", json.dumps(probe_manifest))
        z.write(os.path.join(HERE, "probe", "bootstrap.js"), "bootstrap.js")
    config = {"shots": dirs["shots"], "run": run, "pdf": pdf, "fake": dirs["fake"], "checks": checks, "locale": a.locale,
              "question": QUESTION[a.locale], "claudeConfig": dirs["claude-config"], "skillCarried": carried, "skillFileCount": len(skill)}
    with open(os.path.join(run, "probe-config.json"), "w", encoding="utf8") as f:
        json.dump(config, f, ensure_ascii=False)

    env = make_env(os.environ, run, fake_dir=dirs["fake"], extra_path=agent_dirs(os.environ.get("APPDATA")) if real_agents else ())
    print(f"[{name}] Zotero {a.zotero}, port {a.port}, locale {a.locale}, checks {','.join(checks)}; plugin {plugin_id} "
          f"({'carries' if carried else 'without'} the skill); run folder {run}", flush=True)
    assert not pick_ours(zotero_processes(), dirs["profile"]), "a Zotero with this run's profile is still running"
    before = netstat_user_port()
    print(f"[{name}] netstat :{USER_PORT} before: {before}", flush=True)
    log = open(os.path.join(run, "zotero-debug.txt"), "a", encoding="utf8")
    subprocess.Popen([a.zotero, "-no-remote", "-profile", dirs["profile"], "-ZoteroDebugText"], env=env, stdout=log, stderr=subprocess.STDOUT)
    started, ended, cli_done, served = time.time(), "quit", False, set()
    try:
        time.sleep(8)
        while time.time() < started + a.minutes * 60:
            time.sleep(2)
            req = os.path.join(run, "cli-request.json")
            if not cli_done and os.path.exists(req):
                time.sleep(0.5)
                try:
                    res = apply_step(run, a.port, a.cli, make_env(os.environ, run), json.load(open(req, encoding="utf8")))
                except Exception as e:   # the probe reports the check as failed
                    res = {"error": repr(e)}
                with open(os.path.join(run, "cli-done.json"), "w", encoding="utf8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=1)
                cli_done = True
            for f in sorted(os.listdir(run)):   # the groups check's steps: cli-request-<step>.json -> cli-done-<step>.json
                if f.startswith("cli-request-") and f not in served:
                    served.add(f)
                    time.sleep(0.3)
                    try:
                        res = groups_step(run, a.port, a.cli, make_env(os.environ, run), json.load(open(os.path.join(run, f), encoding="utf8")))
                    except Exception as e:
                        res = {"error": repr(e)}
                    with open(os.path.join(run, f.replace("cli-request-", "cli-done-")), "w", encoding="utf8") as h:
                        json.dump(res, h, ensure_ascii=False, indent=1)
            if not pick_ours(zotero_processes(), dirs["profile"]):
                break
        else:
            ended = "timeout"
    finally:
        killed = end_ours(dirs["profile"])
        log.close()
    after = netstat_user_port()
    print(f"[{name}] ended: {ended}, ended by the runner: {killed}, {round(time.time() - started)} s", flush=True)
    print(f"[{name}] netstat :{USER_PORT} after: {after}", flush=True)

    facts = []
    try:
        facts = json.load(open(os.path.join(dirs["shots"], "facts.json"), encoding="utf8"))
    except (OSError, ValueError):
        pass
    results = {f["check"]: f for f in facts if f.get("what") == "result"}
    if "skill" in results and carried:   # the files installed are the package's, byte for byte
        installed = os.path.join(dirs["claude-config"], "skills", "zotero-scholium")
        got = sha256s(skill_entries(installed)) if os.path.isdir(installed) else {}
        same = got == sha256s(skill)
        results["skill"]["info"]["identical"] = same
        results["skill"]["pass"] = results["skill"]["pass"] and same
    calls = read_calls(os.path.join(dirs["fake"], "calls"))
    if "port" in runner_checks:
        ok, info = check_port_env(calls, a.port)
        results["port"] = {"check": "port", "pass": ok, "info": info}
    if "adddir" in runner_checks:   # the plugin's rule: <CLAUDE_CONFIG_DIR>/skills/zotero-scholium, the run's own here
        folder = os.path.join(dirs["claude-config"], "skills", "zotero-scholium")
        marker = os.path.join(folder, "SKILL.md")
        ok, info = check_add_dir(calls, folder, os.path.getmtime(marker) if os.path.exists(marker) else None)
        results["adddir"] = {"check": "adddir", "pass": ok, "info": info}
    errors = next((f.get("errors") for f in facts if f.get("what") == "errors"), None)
    zotero = next((f.get("zotero") for f in facts if f.get("what") == "start"), None)
    return {"session": name, "checks": [c for c in ALL_CHECKS if c in a.checks_asked and (c in checks or c in runner_checks)],
            "zotero": zotero, "run": run, "results": results, "errors": errors, "ended": ended, "killed": killed,
            "netstat": {"before": before, "after": after}, "shots": sorted(os.listdir(dirs["shots"]))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--zotero", required=True, help="the zotero.exe to test (an installed or an extracted one)")
    ap.add_argument("--port", type=int, default=23129, help="the throwaway's local server port (never 23119)")
    ap.add_argument("--fake", help="the fake claude executable built from fakeclaude/fakeclaude.cs (all checks but setup)")
    ap.add_argument("--plugin", default=os.path.join(REPO, "plugin", "scholium"), help="the plugin source folder or a built .xpi")
    ap.add_argument("--skill", default=os.path.join(REPO, "skills", "zotero-scholium"),
                    help="the skill to package in content/skill when the plugin has none ('' for none)")
    ap.add_argument("--cli", default=None, help="the skill's scholium.py for the apply check (default: <skill>/scripts/scholium.py)")
    ap.add_argument("--locale", default="zh-CN", choices=sorted(QUESTION))
    ap.add_argument("--git", default=None, metavar="REV",
                    help="test plugin/scholium and skills/zotero-scholium as committed at REV (e.g. HEAD), not the working tree")
    ap.add_argument("--checks", default="all", help="all, fake (all but setup and copy), or a comma list of: " + ", ".join(ALL_CHECKS))
    ap.add_argument("--out", default=None, help="the folder of the runs (default: <TEMP>/scholium-smoke/<time>)")
    ap.add_argument("--minutes", type=float, default=10, help="the longest a Zotero start may take")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # the checks' Chinese text on a console of another code page
    except (AttributeError, ValueError):
        pass
    try:
        a.port = check_port(a.port)
        checks = parse_checks(a.checks)
    except ValueError as e:
        ap.error(str(e))
    a.out = os.path.abspath(a.out or os.path.join(os.environ.get("TEMP") or "/tmp", "scholium-smoke", time.strftime("%Y%m%d-%H%M%S")))
    if a.git:
        src = export_git(a.git, os.path.join(a.out, "source"))
        a.plugin = os.path.join(src, "plugin", "scholium") if a.plugin == ap.get_default("plugin") else a.plugin
        a.skill = os.path.join(src, "skills", "zotero-scholium") if a.skill == ap.get_default("skill") else a.skill
    a.zotero = os.path.abspath(a.zotero)
    a.fake = os.path.abspath(a.fake) if a.fake else None   # the plugin needs a native absolute path
    a.plugin = os.path.abspath(a.plugin)
    a.skill = os.path.abspath(a.skill) if a.skill else None
    a.cli = os.path.abspath(a.cli or os.path.join(a.skill or os.path.join(REPO, "skills", "zotero-scholium"), "scripts", "scholium.py"))
    a.checks_asked = checks
    where = plan(checks)
    if not os.path.isfile(a.zotero):
        ap.error(f"no Zotero at {a.zotero}")
    if where["fake"] and not (a.fake and os.path.isfile(a.fake)):
        ap.error("--fake: build fakeclaude.exe first (see scripts/smoke/README.md)")
    os.makedirs(a.out, exist_ok=True)
    sessions = []
    if where["cli"]:
        before = netstat_user_port()
        r = scanned_check(a, os.path.join(a.out, "cli"))
        sessions.append({"session": "cli", "checks": where["cli"], "zotero": None, "run": os.path.join(a.out, "cli"), "results": {"scanned": r},
                         "errors": None, "netstat": {"before": before, "after": netstat_user_port()}, "shots": []})
    if where["fake"]:
        sessions.append(run_session(a, "fake", where["fake"], where["after"]))
    if where["setup"]:
        sessions.append(run_session(a, "setup", where["setup"]))
    ok = True
    print("\nRESULTS (Zotero %s, %s)" % (", ".join(sorted({str(s["zotero"]) for s in sessions if s["zotero"]})), a.locale))
    for s in sessions:
        for c in s["checks"]:
            r = s["results"].get(c)
            passed = bool(r and r.get("pass"))
            ok &= passed
            info = json.dumps(r.get("info") if r else {"error": "no result (the probe did not get to it)"}, ensure_ascii=False)
            print(f"  {'PASS' if passed else 'FAIL'}  {c:10s} {info[:600]}")
        if s["errors"]:
            ok = False
            print(f"  FAIL  console errors naming the plugin: {json.dumps(s['errors'], ensure_ascii=False)[:800]}")
        if s["netstat"]["before"] != s["netstat"]["after"]:
            ok = False
            print(f"  FAIL  netstat :{USER_PORT} changed: {s['netstat']}")
        if s["session"] != "cli":
            print(f"  screenshots: {os.path.join(s['run'], 'shots')}")
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=1)
    print(("ALL PASSED" if ok else "SOME CHECKS FAILED") + f"; details in {os.path.join(a.out, 'summary.json')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
