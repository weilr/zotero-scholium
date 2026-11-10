#!/usr/bin/env python3
"""A REAL annotation run, Claude Code through the plugin's Annotate button, in a THROWAWAY Zotero: what a skill or plugin
change costs and what it writes. eval.py scores the run. With --fake (the fake Claude Code of smoke.py) no model is called.

    python scripts/smoke/live.py --zotero <zotero.exe> --pdf <paper.pdf> [--meta <paper.json>] [--git HEAD]
        [--model haiku] [--effort low] [--locale zh-CN] [--max-msgs 60] [--max-usd 1.00] [--tag NAME] [--out DIR]

The plugin and the skill are exported from git at --git (byte for byte, no uncommitted edits). The given zotero.exe starts
with a new profile and data folder (smoke.py's throwaway setup) and a probe (probe/bootstrap.js's helpers with
probe/live.js's main) adds the paper and presses Annotate the way a user would. Claude Code runs as the plugin starts it,
with `--setting-sources project,local --plugin-dir <the export>` added, so the run uses the exported skill and none of the
user's settings. The run folder <out>/<tag> keeps the conversation logs, the probe's facts and database dump (shots/), and
live.json, this runner's summary.

Safety layers, none of which can be turned off (scripts/smoke/README.md says more):
  port       --port is never 23119, the user's own Zotero; the profile's prefs set the throwaway's port (and firstRun2 false)
  script     the user's own skill script (~/.claude/skills/zotero-scholium/scripts/scholium.py), if there, is read (only
             read) and must honour SCHOLIUM_ZOTERO_PORT, as must the exported one; else no run
  agent env  every agent process must get SCHOLIUM_ZOTERO_PORT = the throwaway's port; the probe cancels the run otherwise
  guard      every Python the agents start loads guard/sitecustomize.py (PYTHONPATH): 23119 is redirected to the
             throwaway's port and each redirect noted; a redirect during the run fails it
  chain      before Annotate: the guard's self-test, the exported script's `status` through the guard and with `python -I`
             and SCHOLIUM_ZOTERO_PORT alone, and an `--apply` on a chain-test item, with netstat :23119 unchanged
  watcher    netstat once a second for the whole session, both sides of 23119 logged; a connection to 23119 from this run's
             process tree (this runner, its Zotero and their children) that a sample shows ends the run's own Zotero
             (TRIPPED); a shorter connection shows only as a closed one (TIME_WAIT, no process), and one that appears
             during the session leaves it unverified
  budget     Claude Code never gets --max-budget-usd (it shows the agent its budget each turn and the agent then
             economizes); the probe cancels the run after --max-msgs API messages, a cap the agent does not see, and the
             runner stops the session once the result lines' total_cost_usd passes --max-usd
  processes  only processes whose command line names this run's profile are ended; CLAUDE* variables of the calling shell
             are not passed on; TEMP, APPDATA and CODEX_HOME are the run's own

Windows only (the watcher reads netstat -ano and Win32_Process). Exit code 0: a complete run; 1: safe but incomplete
(timeout, no result); 2: refused before starting; 3: a safety layer stopped it; 4: unverified, a closed connection with
23119 appeared that the watcher could not attribute (the eval set stops on 2, 3 and 4).
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import smoke  # noqa: E402

USER_PORT = smoke.USER_PORT
EXPORT_PATHS = ("plugin/scholium", "skills/zotero-scholium", ".claude-plugin")
GUARD_SRC = os.path.join(HERE, "guard", "sitecustomize.py")
PROBE_BASE = os.path.join(HERE, "probe", "bootstrap.js")
PROBE_LIVE = os.path.join(HERE, "probe", "live.js")
MARKER = "live-run.txt"            # in each run folder this runner made: only such a folder is ever emptied
FORBIDDEN_FLAGS = ("--max-budget-usd",)
SAFETY_EXIT, REFUSED_EXIT, UNVERIFIED_EXIT = 3, 2, 4
WINDOWS = os.name == "nt"   # the watcher needs netstat -ano and Win32_Process
CHAIN_SENTENCE = smoke.PDF_PAGES[0][2][0]
CONFIG_KEYS = {"zotero", "claude", "fake", "out", "port", "papers", "model", "effort", "locale", "max_msgs", "max_usd",
               "limit", "minutes", "git"}


class RefusedError(Exception):
    """A run that does not start: a safety layer's check before Zotero starts."""


# ---------------------------------------------------------------------------------------------------------------------
# pure parts (tests/test_live_tools.py)
# ---------------------------------------------------------------------------------------------------------------------
def load_config(path, allowed=CONFIG_KEYS):
    """A JSON file of defaults for the command line (the Zotero executable, the papers folder, the output folder...):
    {"zotero": "...", "max-usd": 0.5}; keys with - or _."""
    if not path:
        return {}
    with open(path, encoding="utf8") as f:
        cfg = json.load(f)
    out = {str(k).replace("-", "_"): v for k, v in cfg.items()}
    unknown = sorted(set(out) - set(allowed))
    if unknown:
        raise ValueError(f"{path}: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(allowed))}")
    return out


PORT_READ = re.compile(r"""(?:\.get\s*\(|getenv\s*\(|environ\s*\[)\s*["']SCHOLIUM_ZOTERO_PORT["']""")


def honours_port(text):
    """Whether a skill script reads SCHOLIUM_ZOTERO_PORT from its environment (older ones always used 23119)."""
    return bool(PORT_READ.search(text or ""))


def personal_script(home=None):
    """The user's own skill script that the agent's Claude Code may run: CLAUDE_CONFIG_DIR is not passed to the throwaway,
    so it is the one under ~/.claude."""
    return os.path.join(home or os.path.expanduser("~"), ".claude", "skills", "zotero-scholium", "scripts", "scholium.py")


def check_script(path, whose="the user's own skill script"):
    """(ok, what): a script that is not there is fine; one that is there must honour SCHOLIUM_ZOTERO_PORT. Only read."""
    if not os.path.exists(path):
        return True, f"{whose}: none at {path}"
    try:
        with open(path, encoding="utf8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return False, f"{whose} {path} could not be read ({e})"
    if honours_port(text):
        return True, f"{whose} honours SCHOLIUM_ZOTERO_PORT: {path}"
    return False, (f"{whose} {path} does not read SCHOLIUM_ZOTERO_PORT, so an agent running it would write to the user's "
                   "Zotero on 23119; update it (python scripts/sync_local_skills.py) before a real run")


def check_flags(flags):
    """Claude Code's added arguments, without --max-budget-usd (Claude Code shows the agent its budget each turn)."""
    bad = [f for f in flags if str(f).split("=")[0] in FORBIDDEN_FLAGS]
    if bad:
        raise ValueError("--max-budget-usd is refused: Claude Code shows the agent its budget and the agent economizes; "
                         "use --max-msgs (a cap the agent does not see) and --max-usd")
    return list(flags)


def agent_flags(plugin_dir):
    """The arguments added to the plugin's own: no user settings, the export as Claude Code's plugin (its skill)."""
    return check_flags(["--setting-sources", "project,local", "--plugin-dir", str(plugin_dir).replace("\\", "/")])


def live_prefs(data_dir, port, locale, claude_path, model, effort, show_pref=True):
    """The throwaway profile's prefs: smoke.py's (firstRun2 false, no Word add-in installs, no updates or sync), the local
    API on, the given claude, model and effort."""
    port = smoke.check_port(port)
    prefs = smoke.make_prefs(data_dir, port, locale, local_api=True, claude_path=claude_path)
    prefs.update({"extensions.scholium.claudeModel": model, "extensions.scholium.claudeEffort": effort})
    if not show_pref:
        prefs.pop("extensions.scholium.showAnnotations", None)
    if prefs["extensions.zotero.firstRun2"] is not False or prefs["extensions.zotero.httpServer.port"] != port:
        raise RuntimeError("the throwaway's prefs lost firstRun2 or the port")
    return prefs


def live_env(base, run, guard_dir, fake_dir=None):
    """Zotero's environment: the caller's without CLAUDE* (a Claude Code session's), CODEX_HOME and SCHOLIUM_ZOTERO_PORT
    (the plugin sets it for each agent); TEMP, TMP, APPDATA, ZOTERO_DATA_DIR and CODEX_HOME in the run; the guard first on
    PYTHONPATH. A real run keeps the user's Claude Code login (no CLAUDE_CONFIG_DIR); the fake gets an empty one."""
    env = {k: v for k, v in base.items() if not k.upper().startswith("CLAUDE") and k.upper() not in ("CODEX_HOME", "SCHOLIUM_ZOTERO_PORT")}
    env.update(TEMP=os.path.join(run, "temp"), TMP=os.path.join(run, "temp"), APPDATA=os.path.join(run, "appdata"),
               ZOTERO_DATA_DIR=os.path.join(run, "data"), CODEX_HOME=os.path.join(run, "codex-home"),
               PYTHONPATH=os.pathsep.join([guard_dir] + ([base["PYTHONPATH"]] if base.get("PYTHONPATH") else [])))
    if fake_dir:
        env.update(SCHOLIUM_FAKE_DIR=fake_dir, CLAUDE_CONFIG_DIR=os.path.join(run, "claude-config"))
    return env


def check_env(env, run, guard_dir, fake=False):
    """Raises unless the environment is a live run's: nothing of the caller's Claude Code, no SCHOLIUM_ZOTERO_PORT, the
    run's own folders, the guard first."""
    inside = lambda p: bool(p) and os.path.commonpath([os.path.abspath(p), os.path.abspath(run)]) == os.path.abspath(run)
    claude = [k for k in env if k.upper().startswith("CLAUDE") and not (fake and k == "CLAUDE_CONFIG_DIR")]
    problems = [f"{k} is passed on" for k in claude]
    if fake and not inside(env.get("CLAUDE_CONFIG_DIR")):
        problems.append("the fake's CLAUDE_CONFIG_DIR is not the run's")
    if "SCHOLIUM_ZOTERO_PORT" in env:
        problems.append("SCHOLIUM_ZOTERO_PORT is passed on (the plugin sets it)")
    for k in ("TEMP", "TMP", "APPDATA", "ZOTERO_DATA_DIR", "CODEX_HOME"):
        if not inside(env.get(k)):
            problems.append(f"{k} is not inside the run")
    if (env.get("PYTHONPATH") or "").split(os.pathsep)[0] != guard_dir:
        problems.append("the guard is not first on PYTHONPATH")
    if problems:
        raise RuntimeError("the throwaway's environment: " + "; ".join(problems))
    return True


FAKE_CODEX_PY = os.path.join(HERE, "fakecodex", "fake_codex.py")
SLOW_FLAG = "SLOW_PRERUN"   # in <run>/codex-home: the skill copy's status waits while it is there (--stop-prerun)
SLOW_SHIM = ('import os as _fk_os, sys as _fk_sys, time as _fk_time\n'
             'if _fk_sys.argv[1:2] == ["status"] and _fk_os.path.exists(_fk_os.path.join(_fk_os.path.dirname(_fk_os.path.dirname('
             '_fk_os.path.dirname(_fk_os.path.dirname(_fk_os.path.abspath(__file__))))), "%s")):\n'
             '    _fk_time.sleep(8)   # live.py --stop-prerun only: a pre-run slow enough for its stop button\n' % SLOW_FLAG)


def codex_prefs(prefs, codex_path):
    """The prefs of a run with Codex: the plugin's agent, the (fake) codex executable."""
    return dict(prefs, **{"extensions.scholium.agent": "codex", "extensions.scholium.codexPath": codex_path})


def setup_fake_codex(exe, run):
    """The fake codex in the run's own folder: the launcher, fake_codex.py beside it and the Python to run it with, so that
    its logs (calls/) are the run's."""
    folder = os.path.join(run, "fakecodex")
    os.makedirs(folder, exist_ok=True)
    shutil.copyfile(exe, os.path.join(folder, "fakecodex.exe"))
    shutil.copyfile(FAKE_CODEX_PY, os.path.join(folder, "fake_codex.py"))
    with open(os.path.join(folder, "python.txt"), "w", encoding="utf8") as f:
        f.write(sys.executable)
    return os.path.join(folder, "fakecodex.exe")


def install_codex_skill(export, run, slow=False):
    """The export's skill as a Codex user has it installed: <run>/codex-home/skills/zotero-scholium (CODEX_HOME is the
    run's). With slow, its copy's status waits while <run>/codex-home/SLOW_PRERUN is there, for the stop-button check."""
    home = os.path.join(run, "codex-home")
    dst = os.path.join(home, "skills", "zotero-scholium")
    shutil.copytree(os.path.join(export, "skills", "zotero-scholium"), dst)
    if slow:
        script = os.path.join(dst, "scripts", "scholium.py")
        with open(script, encoding="utf8") as f:
            text = f.read()
        marker = '\nif __name__ == "__main__":'
        if text.count(marker) != 1:
            raise RuntimeError("the skill's script has no single __main__ block for the slow pre-run")
        with open(script, "w", encoding="utf8", newline="\n") as f:
            f.write(text.replace(marker, "\n" + SLOW_SHIM + marker))
        open(os.path.join(home, SLOW_FLAG), "w").close()
    return dst


def assemble_probe(base, live):
    """The live probe: bootstrap.js (the smoke probe's helpers and finish()) with live.js in place of its main()."""
    i, j = base.find("\nasync function main() {"), base.find("\nasync function finish() {")
    if i < 0 or j < i:
        raise ValueError("bootstrap.js has no main() before finish()")
    return base[:i + 1] + live.rstrip("\n") + "\n\n" + base[j + 1:]


def paper_meta(meta, pdf):
    """The paper's item: the --meta JSON (itemType, fields, creators), else a preprint titled after the PDF's name."""
    if meta:
        paper = dict(meta)
    else:
        paper = {"itemType": "preprint", "fields": {"title": os.path.splitext(os.path.basename(pdf))[0]}, "creators": []}
    paper.setdefault("itemType", "preprint")
    paper.setdefault("fields", {})
    paper.setdefault("creators", [])
    if not str(paper["fields"].get("title") or "").strip():
        paper["fields"]["title"] = os.path.splitext(os.path.basename(pdf))[0]
    return {"itemType": paper["itemType"], "fields": paper["fields"], "creators": paper["creators"]}


# ---- the guard and the chain test ----
GUARD_SELFTEST = ("import sitecustomize as s, socket, urllib.request as u, http.client as h; print(s.__file__); "
                  "print(socket.socket.connect.__module__); print(s._move(('127.0.0.1', 23119))); "
                  "print(u.Request('http://127.0.0.1:23119/api/').full_url); print(h.HTTPConnection('127.0.0.1', 23119).port)")


def write_guard(guard_dir, port):
    """The run's copy of the guard, with the throwaway's port in port.txt beside it."""
    port = smoke.check_port(port)
    os.makedirs(guard_dir, exist_ok=True)
    shutil.copyfile(GUARD_SRC, os.path.join(guard_dir, "sitecustomize.py"))
    with open(os.path.join(guard_dir, "port.txt"), "w", encoding="utf8") as f:
        f.write(str(port))
    return guard_dir


def redirects(guard_dir):
    path = os.path.join(guard_dir, "redirects.txt")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf8", errors="replace") as f:
        return sum(1 for line in f if line.strip())


def guard_selftest_ok(rc, stdout, guard_dir, port):
    """The guard's self-test output: loaded from the run's guard, socket patched, 23119 moved to the port in every form."""
    lines = (stdout or "").strip().splitlines()
    return (rc == 0 and len(lines) == 5 and os.path.normcase(os.path.abspath(guard_dir)) in os.path.normcase(lines[0])
            and lines[1] == "sitecustomize" and lines[2] == "('127.0.0.1', %d)" % port
            and lines[3] == "http://127.0.0.1:%d/api/" % port and lines[4] == str(port))


def listening(lines):
    return sorted(line for line in lines if "LISTENING" in line)


def chain_verdict(out, title):
    """(ok, what failed) of a chain test's parts: the guard, `status` through the guard and with python -I, the --apply,
    no redirect, the same netstat :23119 LISTENING lines before and after."""
    title = str(title or "")[:30]
    s, si, ap = out.get("status") or {}, out.get("statusIsolated") or {}, out.get("apply") or {}
    failed = []
    if not out.get("guardOk"):
        failed.append("the guard's self-test")
    if s.get("rc") != 0 or title not in (s.get("out") or ""):
        failed.append("status through the guard")
    if si.get("rc") != 0 or title not in (si.get("out") or ""):
        failed.append("status with python -I and SCHOLIUM_ZOTERO_PORT alone")
    if ap.get("applied") is not True:
        failed.append("--apply on the chain-test item")
    if out.get("redirects") != 0:
        failed.append("a redirect by the guard")
    ns = out.get("netstat23119") or [[], ["(none)"]]
    if listening(ns[0]) != listening(ns[1]):
        failed.append("netstat :23119 changed")
    return not failed, failed


# ---- the watcher ----
def netstat_rows(text, port=USER_PORT):
    """The rows of `netstat -ano` with the port on either side: proto, local, foreign, state, pid, the line."""
    rows, tail = [], ":%d" % port
    for raw in (text or "").splitlines():
        parts = raw.split()
        if len(parts) < 4 or parts[0].upper() not in ("TCP", "UDP"):
            continue
        local, foreign = parts[1], parts[2]
        if not (local.endswith(tail) or foreign.endswith(tail)):
            continue
        if parts[0].upper() == "TCP":
            state, pid = parts[3], (parts[4] if len(parts) >= 5 else "")
        else:
            state, pid = "", parts[3]
        rows.append({"proto": parts[0].upper(), "local": local, "foreign": foreign, "state": state,
                     "pid": int(pid) if pid.isdigit() else None, "line": " ".join(parts)})
    return rows


def is_listen(row):
    return row["state"].upper() == "LISTENING" or row["foreign"] in ("0.0.0.0:0", "[::]:0", "*:*")


def in_tree(pid, table, profile, roots=()):
    """Whether pid is of this run: its parent chain reaches one of roots (this runner) or a process whose command line
    names this run's profile (its Zotero). table: {pid: (parent pid, name, command line[, creation time])}. Windows
    reuses process ids and a process keeps the id of a parent that is gone, so the chain ends at a "parent" created
    after its child: that is another process with the same id. Only used to say whose a connection is: a trip ends
    the run's own Zotero (end_ours), never the process found here."""
    seen = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        entry = table[pid]
        parent, cmd, created = entry[0], entry[2], (entry[3] if len(entry) > 3 else None)
        if pid in roots or smoke.profile_matches(cmd, profile):
            return True
        above = table.get(parent)
        above_created = above[3] if above is not None and len(above) > 3 else None
        if created is not None and above_created is not None and above_created > created:
            return False
        pid = parent
    return pid in roots


def watch_step(rows, table, profile, roots, seen, port=USER_PORT):
    """One netstat sample. Returns (lines for watch23119-all.txt: each connection with the port on either side, once;
    lines for watch23119.txt: the clients and closed connections; the trip: a client of this run's process tree, or None).
    seen is kept between samples."""
    tail = ":%d" % port
    every, clients, trip = [], [], None
    for r in rows:
        if is_listen(r):
            continue
        name = (table.get(r["pid"]) or (0, "?", ""))[1] if r["pid"] else ""
        key = (r["local"], r["foreign"], r["state"])
        if key not in seen.setdefault("all", set()):
            seen["all"].add(key)
            side = "zotero-side" if r["local"].endswith(tail) else "client-side"
            every.append(f"{side} pid {r['pid']} {name}: {r['line']}")
        if not r["pid"]:   # a closed connection (TIME_WAIT), on either side: no process to name
            if (r["local"], r["foreign"]) not in seen.setdefault("closed", set()):
                seen["closed"].add((r["local"], r["foreign"]))
                clients.append(f"closed {r['line']}")
            continue
        if not r["foreign"].endswith(tail):
            continue
        mine = in_tree(r["pid"], table, profile, roots)
        if (r["pid"], r["local"]) not in seen.setdefault("clients", set()):
            seen["clients"].add((r["pid"], r["local"]))
            clients.append(f"{'OURS' if mine else 'other'} pid {r['pid']} {name}: {r['line']}")
        if mine and trip is None:
            trip = {"pid": r["pid"], "name": name, "line": r["line"]}
        elif not mine:
            seen.setdefault("other", set()).add(f"{r['pid']} {name}")
    return every, clients, trip


# ---- the cost ----
def result_cost(lines):
    """The sum of total_cost_usd over the stream-json result lines (one per agent run)."""
    total = 0.0
    for line in lines:
        if '"result"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("type") == "result":
            total += float(e.get("total_cost_usd") or 0)
    return total


def conversation_logs(run, kind="*"):
    return sorted(glob.glob(os.path.join(run, "data", "tmp", "scholium", "*", "conversations", kind + ".jsonl")))


def log_sizes(run):
    """{log: its size in bytes}: what the run's conversation logs held as the session began (a --from-run copy's)."""
    out = {}
    for path in conversation_logs(run):
        try:
            out[path] = os.path.getsize(path)
        except OSError:
            pass
    return out


def new_lines(path, since=None):
    """A log's lines written after since[path] bytes (all of a log that was not there, or got shorter)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    start = (since or {}).get(path, 0)
    if start > len(data):
        start = 0
    return data[start:].decode("utf8", "replace").splitlines()


def session_cost(run, since=None):
    """The session's cost: the result lines written to the run's conversation logs since `since` (log_sizes)."""
    return sum(result_cost(new_lines(path, since)) for path in conversation_logs(run))


def annotate_results(run, since=None):
    return sum(1 for path in conversation_logs(run, "annotate-*") for line in new_lines(path, since)
               if '"type": "result"' in line or '"type":"result"' in line)


def check_agent_env(facts, port):
    """(ok, info): every agent process the probe saw had SCHOLIUM_ZOTERO_PORT = the throwaway's port, and nothing was
    aborted for it."""
    seen = [f.get("SCHOLIUM_ZOTERO_PORT") for f in facts if f.get("what") == "agentEnv"]
    aborted = [f.get("reason") for f in facts if f.get("what") == "abort" and "SCHOLIUM_ZOTERO_PORT" in str(f.get("reason"))]
    got = sorted({str(p) for p in seen})
    return bool(seen) and got == [str(port)] and not aborted, {"agent processes": len(seen), "SCHOLIUM_ZOTERO_PORT": got, "aborted": aborted}


def unverified(s):
    """Why a safe session's safety cannot be confirmed: closed connections with 23119 that appeared during it, whose
    process the watcher could not see (a connection shorter than its one-second samples)."""
    closed = (s.get("watch") or {}).get("closed during") or []
    return [f"{len(closed)} closed connection(s) with 23119 appeared during the session without a process id; one shorter "
            "than the watcher's one-second samples cannot be attributed and could have been this run's (watch23119.txt)"] if closed else []


def verdict(s):
    """(safe, complete) of a session summary."""
    safe = (not s["tripped"] and listening(s["netstat"]["before"]) == listening(s["netstat"]["after"]) and s["redirects"] == 0
            and s["chain"].get("ok") is True and s["agent_env"]["ok"] and not s.get("aborted"))
    complete = s["ended"] == "quit" and s["annotate_results"] > 0 and s["db"]
    return safe, bool(complete)


# ---------------------------------------------------------------------------------------------------------------------
# processes, ports, the session
# ---------------------------------------------------------------------------------------------------------------------
def netstat_text():
    return subprocess.run("netstat -ano", capture_output=True, text=True, shell=True).stdout


def procs():
    """{pid: (parent pid, name, command line, creation time as a FILETIME or None)} of every process."""
    ps = ("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.ParentProcessId)`t"
          "$(if ($_.CreationDate) { $_.CreationDate.ToFileTimeUtc() })`t$($_.Name)`t$($_.CommandLine)\" }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf8", errors="replace").stdout
    return parse_procs(out)


def parse_procs(text):
    table = {}
    for line in (text or "").splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5 and parts[0].strip().isdigit():
            created = parts[2].strip()
            table[int(parts[0])] = (int(parts[1]) if parts[1].strip().isdigit() else 0, parts[3], parts[4], int(created) if created.isdigit() else None)
    return table


def ours(profile):
    return smoke.pick_ours(smoke.zotero_processes(), profile)


class Watcher(threading.Thread):
    """netstat every second from before Zotero starts until after it ended: every connection with 23119 on either side
    in watch23119-all.txt, the clients in watch23119.txt; a client of this run's process tree ends the run's Zotero."""

    def __init__(self, run, profile):
        super().__init__(daemon=True)
        self.run_dir, self.profile, self.roots = run, profile, {os.getpid()}
        self.stopping, self.tripped, self.samples, self.seen = threading.Event(), None, 0, {}
        self.zotero_started, self.closed_before = False, set()   # the closed connections already there as Zotero starts

    def closed_during(self):
        """The closed connections with 23119 (TIME_WAIT, no process) that appeared once the run's Zotero started: a
        connection shorter than a sample shows only so, and could have been this run's."""
        return sorted(set(self.seen.get("closed", ())) - self.closed_before)

    def write(self, name, lines):
        if lines:
            with open(os.path.join(self.run_dir, name), "a", encoding="utf8") as f:
                for line in lines:
                    f.write(f"{time.strftime('%H:%M:%S')} {line}\n")

    def run(self):
        while not self.stopping.is_set():
            try:
                rows = [r for r in netstat_rows(netstat_text()) if not is_listen(r)]
                self.samples += 1
                if rows:
                    table = procs()
                    every, clients, trip = watch_step(rows, table, self.profile, self.roots, self.seen)
                    if not self.zotero_started:
                        self.closed_before |= set(self.seen.get("closed", ()))
                    self.write("watch23119-all.txt", every)
                    self.write("watch23119.txt", clients)
                    if trip and not self.tripped:   # only the run's own Zotero is ended, never the connecting process
                        self.tripped = dict(trip, at=time.strftime("%H:%M:%S"))
                        self.write("watch23119.txt", [f"TRIPPED by pid {trip['pid']}: ending this run's Zotero"])
                        self.tripped["ended"] = smoke.end_ours(self.profile)
            except Exception as e:  # noqa: BLE001 - the watcher keeps watching
                self.write("watch23119.txt", [f"watch error {e!r}"])
            self.stopping.wait(1)


def prepare_run(run):
    """An empty run folder: a folder of an earlier run (it has the marker) is emptied, any other is refused."""
    if os.path.exists(run):
        if not os.path.isfile(os.path.join(run, MARKER)):
            raise RuntimeError(f"{run} exists and is not a live run's folder; choose another --tag or --out")
        shutil.rmtree(run)
    os.makedirs(run)
    with open(os.path.join(run, MARKER), "w", encoding="utf8") as f:
        f.write("a throwaway run folder of scripts/smoke/live.py\n")


def copy_from_run(src, run):
    """Start from a finished run's profile and data (the source is only read)."""
    src = os.path.abspath(src)
    if ours(os.path.join(src, "profile")):
        raise RuntimeError("the source run's Zotero is still running")
    shutil.copytree(os.path.join(src, "profile"), os.path.join(run, "profile"), dirs_exist_ok=True)
    shutil.copytree(os.path.join(src, "data"), os.path.join(run, "data"), dirs_exist_ok=True)
    for f in ("extensions.json", "addonStartup.json.lz4", "compatibility.ini", "sessionstore.jsonlz4", "parent.lock", "user.js"):
        try:
            os.remove(os.path.join(run, "profile", f))
        except FileNotFoundError:
            pass
    for d in ("startupCache", "sessionstore-backups"):
        shutil.rmtree(os.path.join(run, "profile", d), ignore_errors=True)


def find_claude():
    """The real claude: npm's package under the user's APPDATA (the throwaway's own APPDATA hides it from the plugin's
    search), else the one on PATH."""
    for d in smoke.agent_dirs(os.environ.get("APPDATA")):
        exe = os.path.join(d, "claude.exe")
        if os.path.isfile(exe):
            return exe
    return shutil.which("claude")


def commit_of(rev):
    p = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", rev + "^{commit}"], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"--git {rev}: not a commit of this repository")
    return p.stdout.strip()


def run_chain(ctx, req):
    """The chain test, on the probe's request: the guard, then the exported script's status (through the guard, and with
    python -I and SCHOLIUM_ZOTERO_PORT alone) and an --apply on the chain-test item, with netstat :23119 unchanged."""
    def py(args, isolated=False, guard=True, timeout=180):
        e = dict(ctx["env"], SCHOLIUM_ZOTERO_PORT=str(ctx["port"]))
        if not guard:
            e.pop("PYTHONPATH", None)
        p = subprocess.run([sys.executable] + (["-I"] if isolated else []) + args, capture_output=True, text=True,
                           encoding="utf8", errors="replace", env=e, cwd=ctx["chain"], timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    out, r0 = {}, redirects(ctx["guard"])
    rc, so, se = py(["-c", GUARD_SELFTEST])
    out["guardOk"] = guard_selftest_ok(rc, so, ctx["guard"], ctx["port"])
    out["guardSelfTestRedirects"] = redirects(ctx["guard"]) - r0
    if not out["guardOk"]:
        out["guardOut"] = [rc, so[-600:], se[-300:]]
        out["ok"], out["failed"] = False, ["the guard's self-test"]
        return out
    r1, ns0 = redirects(ctx["guard"]), smoke.netstat_user_port()
    rc, so, se = py([ctx["script"], "status", req["itemKey"]])
    out["status"] = {"rc": rc, "out": so[:600], "err": se[-300:]}
    rc, so, se = py([ctx["script"], "status", req["itemKey"]], isolated=True, guard=False)
    out["statusIsolated"] = {"rc": rc, "out": so[:600], "err": se[-300:]}
    cfg = {"pdf": req["chainPdf"], "item_key": req["chainItemKey"], "attachment_key": req["chainAttKey"], "out_dir": ctx["chain"],
           "highlights": [{"page": 1, "text": CHAIN_SENTENCE, "core": True, "comment": ""}]}
    with open(os.path.join(ctx["chain"], "config.json"), "w", encoding="utf8") as f:
        json.dump(cfg, f, indent=1)
    rc, so, se = py([ctx["script"], "--config", os.path.join(ctx["chain"], "config.json"), "--apply"], isolated=True, guard=False)
    try:
        rep = json.loads(so)
    except ValueError:
        rep = {"raw": so[-600:]}
    out["apply"] = {"rc": rc, "applied": rep.get("applied"), "backend": rep.get("backend"), "error": rep.get("apply_error"), "err": se[-300:]}
    out["redirects"] = redirects(ctx["guard"]) - r1
    out["netstat23119"] = [ns0, smoke.netstat_user_port()]
    out["ok"], out["failed"] = chain_verdict(out, ctx["title"])
    return out


def read_json(path, default):
    try:
        with open(path, encoding="utf8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def session(a):
    """One throwaway Zotero session; returns the summary (live.json)."""
    run = os.path.join(a.out, a.tag)
    prepare_run(run)
    d = {k: os.path.join(run, k) for k in ("profile", "data", "appdata", "temp", "shots", "chain", "codex-home", "claude-config", "guard")}
    if a.from_run:
        copy_from_run(a.from_run, run)
    for p in d.values():
        os.makedirs(p, exist_ok=True)
    os.makedirs(os.path.join(d["profile"], "extensions"), exist_ok=True)

    export = smoke.export_git(a.git, os.path.join(run, "export"), EXPORT_PATHS)
    script = os.path.join(export, "skills", "zotero-scholium", "scripts", "scholium.py")
    ok, what = check_script(script, "the exported skill script")
    if not ok or not os.path.isfile(os.path.join(export, ".claude-plugin", "plugin.json")):
        raise RefusedError(what if not ok else f"--git {a.git}: the export has no .claude-plugin/plugin.json")
    write_guard(d["guard"], a.port)
    fake_dir = None
    if a.fake:
        fake_dir = os.path.join(run, "fake")
        shutil.copytree(os.path.join(HERE, "fakeclaude", "scripts"), os.path.join(fake_dir, "scripts"))
        shutil.copy(os.path.join(HERE, "fakeclaude", "models.json"), fake_dir)
        with open(os.path.join(fake_dir, "next.txt"), "w", encoding="utf8") as f:
            f.write("annotate-ok")
    prefs = live_prefs(d["data"], a.port, a.locale, a.fake or a.claude, a.model, a.effort, show_pref=not a.open_reader)
    if a.fake_codex:   # the plugin set to Codex: the fake in the run's folder, the export's skill in the run's CODEX_HOME
        prefs = codex_prefs(prefs, setup_fake_codex(a.fake_codex, run))
        install_codex_skill(export, run, slow=a.stop_prerun)
    with open(os.path.join(d["profile"], "user.js"), "w", encoding="utf8") as f:
        f.write(smoke.user_js(prefs))
    plugin_id, _, _ = smoke.build_plugin_xpi(os.path.join(export, "plugin", "scholium"), os.path.join(d["profile"], "extensions", "P.xpi"),
                                             time.strftime("%H%M%S"), os.path.join(export, "skills", "zotero-scholium"))
    os.replace(os.path.join(d["profile"], "extensions", "P.xpi"), os.path.join(d["profile"], "extensions", plugin_id + ".xpi"))
    with open(PROBE_BASE, encoding="utf8") as f1, open(PROBE_LIVE, encoding="utf8") as f2:
        probe = assemble_probe(f1.read(), f2.read())
    manifest = {"manifest_version": 2, "name": "Scholium live probe", "version": "1.0", "description": "throwaway",
                "applications": {"zotero": {"id": smoke.PROBE_ID, "update_url": "https://example.invalid/u.json",
                                            "strict_min_version": "6.999", "strict_max_version": "9999.*"}}}
    with zipfile.ZipFile(os.path.join(d["profile"], "extensions", smoke.PROBE_ID + ".xpi"), "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("bootstrap.js", probe)
    paper = paper_meta(read_json(a.meta, None) if a.meta else None, a.pdf)
    flags = agent_flags(export)
    stop_file = os.path.join(run, "stop-request.json")
    config = {"shots": d["shots"], "run": run, "pdf": a.pdf, "chainPdf": smoke.make_pdf(os.path.join(d["chain"], "chain.pdf")),
              "extra": a.extra, "port": a.port, "paper": paper, "limitMin": a.limit, "locale": a.locale, "flags": flags,
              "maxMsgs": a.max_msgs, "stopFile": stop_file, "checks": [], "openReader": bool(a.open_reader), "chat": a.chat or "",
              # Claude Code's skill folder as the plugin sees it: the export's, so that --add-dir and the pre-run's script
              # are the commit's, not a skill the user installed
              "claudeSkills": os.path.join(export, "skills"),
              "stopPreRun": bool(a.stop_prerun), "slowFlag": os.path.join(d["codex-home"], SLOW_FLAG)}
    if fake_dir:
        config["fake"] = fake_dir
    with open(os.path.join(run, "probe-config.json"), "w", encoding="utf8") as f:
        json.dump(config, f, ensure_ascii=False, indent=1)

    env = live_env(dict(os.environ), run, d["guard"], fake_dir)
    check_env(env, run, d["guard"], fake=bool(fake_dir))
    ctx = {"env": env, "port": a.port, "chain": d["chain"], "guard": d["guard"], "script": script, "title": paper["fields"]["title"]}
    removed = sorted(k for k in os.environ if k not in env)
    print(f"[{a.tag}] Zotero {a.zotero}, port {a.port}, {'FAKE ' + a.fake if a.fake else 'claude ' + a.claude}, model {a.model}, "
          f"effort {a.effort}, locale {a.locale}, git {a.git} ({a.commit}); run folder {run}", flush=True)
    print(f"[{a.tag}] not passed on: {', '.join(removed) or '(none)'}; {a.personal}", flush=True)
    if ours(d["profile"]):
        raise RefusedError("a Zotero with this run's profile is running")

    before = smoke.netstat_user_port()
    print(f"[{a.tag}] netstat :{USER_PORT} before: {before}", flush=True)
    with open(os.path.join(run, "watch23119-all.txt"), "w", encoding="utf8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} session start; netstat :{USER_PORT}: {before}\n")
    since = log_sizes(run)   # the logs a --from-run copy brought: what they hold is not this session's
    watcher = Watcher(run, d["profile"])
    watcher.start()
    time.sleep(1.5)   # a first sample before Zotero starts
    log = open(os.path.join(run, "zotero-debug.txt"), "a", encoding="utf8")
    watcher.zotero_started = True
    zotero = subprocess.Popen([a.zotero, "-no-remote", "-profile", d["profile"], "-ZoteroDebugText"], env=env, stdout=log, stderr=subprocess.STDOUT)
    started, ended, chain, stop_at = time.time(), "quit", {}, None
    try:
        time.sleep(8)
        while time.time() < started + a.minutes * 60:
            time.sleep(2)
            if watcher.tripped:
                ended = "TRIPPED"
                break
            req = os.path.join(run, "chain-request.json")
            if not chain and os.path.exists(req):
                time.sleep(0.5)
                try:
                    chain = run_chain(ctx, read_json(req, {}))
                except Exception as e:  # noqa: BLE001 - the probe then ends without a run
                    chain = {"ok": False, "failed": [repr(e)]}
                with open(os.path.join(run, "chain-done.json"), "w", encoding="utf8") as f:
                    json.dump(chain, f, ensure_ascii=False, indent=1)
                print(f"[{a.tag}] chain test: {'passed' if chain.get('ok') else 'FAILED: ' + ', '.join(chain.get('failed') or [])}", flush=True)
            cost = session_cost(run, since)
            if stop_at is None and cost > a.max_usd:
                stop_at = time.time()
                with open(stop_file, "w", encoding="utf8") as f:
                    json.dump({"cost_usd": cost, "max_usd": a.max_usd}, f)
                print(f"[{a.tag}] cost {cost:.4f} USD passed --max-usd {a.max_usd}: the probe cancels, Zotero is ended in 90 s", flush=True)
            if stop_at is not None and time.time() > stop_at + 90:
                ended = "COST"
                break
            # the session lasts while the Zotero started here runs, also when the process list cannot be read
            if zotero.poll() is not None and not ours(d["profile"]):
                break
        else:
            ended = "timeout"
    finally:
        killed = smoke.end_ours(d["profile"])
        if zotero.poll() is None:   # the process list missed it: the handle held here names this run's Zotero, and only it
            subprocess.run(["taskkill", "/PID", str(zotero.pid), "/T", "/F"], capture_output=True)
            killed = killed + [zotero.pid]
        time.sleep(2)
        watcher.stopping.set()
        watcher.join(10)
        log.close()
    after = smoke.netstat_user_port()
    seconds = round(time.time() - started)
    facts = read_json(os.path.join(d["shots"], "facts.json"), [])
    env_ok, env_info = check_agent_env(facts, a.port)
    s = {"tag": a.tag, "git": a.git, "commit": a.commit, "fake": bool(a.fake), "fake_codex": bool(a.fake_codex), "model": a.model, "effort": a.effort, "locale": a.locale,
         "port": a.port, "max_msgs": a.max_msgs, "max_usd": a.max_usd, "ended": ended, "killed": killed, "seconds": seconds,
         "netstat": {"before": before, "after": after},
         "redirects": redirects(d["guard"]) - (chain.get("guardSelfTestRedirects") or 0),
         "tripped": watcher.tripped, "watch": {"samples": watcher.samples, "logged": len(watcher.seen.get("all", ())),
                                               "other clients": sorted(watcher.seen.get("other", ())), "closed": len(watcher.seen.get("closed", ())),
                                               "closed during": [f"{local} -> {foreign}" for local, foreign in watcher.closed_during()]},
         "chain": {k: chain.get(k) for k in ("ok", "failed", "redirects", "netstat23119")}, "agent_env": dict(env_info, ok=env_ok),
         "aborted": [f.get("reason") for f in facts if f.get("what") == "abort"], "cost_usd": round(session_cost(run, since), 4),
         "cost_stop": stop_at is not None, "annotate_results": annotate_results(run, since), "db": os.path.exists(os.path.join(d["shots"], "db.json")),
         "personal_script": a.personal, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    s["safe"], s["complete"] = verdict(s)
    s["unverified"] = unverified(s)
    s["verdict"] = "unsafe" if not s["safe"] else "unverified" if s["unverified"] else "safe"
    with open(os.path.join(run, "live.json"), "w", encoding="utf8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    print(f"[{a.tag}] ended: {ended}, ended by the runner: {killed}, {seconds} s, cost {s['cost_usd']} USD", flush=True)
    print(f"[{a.tag}] netstat :{USER_PORT} after: {after}", flush=True)
    print(f"[{a.tag}] guard redirects: {s['redirects']} | watcher: {watcher.samples} samples, {s['watch']['logged']} connections logged, "
          f"tripped: {watcher.tripped} | agent env: {env_info} | aborted: {s['aborted'] or 'no'}", flush=True)
    return s


def parser(config):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--config", help="a JSON file of defaults for these options (zotero, claude, out, port, ...)")
    ap.add_argument("--zotero", help="the zotero.exe to start with a throwaway profile")
    ap.add_argument("--pdf", help="the paper (only read: Zotero imports a copy)")
    ap.add_argument("--meta", help="JSON of the paper's item: itemType, fields (title, date, url, archiveID, DOI), creators [[first, last]]")
    ap.add_argument("--git", default="HEAD", metavar="REV", help="the commit whose plugin/scholium, skills/zotero-scholium and .claude-plugin run")
    ap.add_argument("--claude", help="the real claude executable (default: npm's under APPDATA, else PATH)")
    ap.add_argument("--fake", help="a rehearsal: the fake claude built from fakeclaude/fakeclaude.cs (no model is called)")
    ap.add_argument("--fake-codex", help="with --fake: the plugin set to Codex, with the fake codex built from fakecodex/launcher.cs")
    ap.add_argument("--stop-prerun", action="store_true", help="with --fake-codex: first an Annotate stopped with ■ during its pre-run")
    ap.add_argument("--port", type=int, default=23129, help="the throwaway's local server port (never 23119)")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--locale", default="zh-CN", choices=sorted(smoke.QUESTION))
    ap.add_argument("--extra", default="", help="extra instructions typed above Annotate (default: none, the one-click run)")
    ap.add_argument("--max-msgs", type=int, default=60, help="the probe cancels the run after this many API messages (the agent is not shown it)")
    ap.add_argument("--max-usd", type=float, default=1.0, help="the session ends once its result lines' total_cost_usd passes this")
    ap.add_argument("--limit", type=float, default=20, help="minutes the agent run may take before the probe cancels it")
    ap.add_argument("--minutes", type=float, default=30, help="minutes the whole Zotero session may take")
    ap.add_argument("--chat", default="", help="a question for the Chat tab after the run")
    ap.add_argument("--open-reader", action="store_true", help="a reader tab before and after the run, the eye button's pref never set")
    ap.add_argument("--from-run", help="start from a copy of this finished run's profile and data (only read)")
    ap.add_argument("--tag", default=None, help="the run's name (default: the time)")
    ap.add_argument("--out", default=None, help="the folder of the runs (default: <system temp>/scholium-live)")
    ap.set_defaults(**config)
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    known, _ = pre.parse_known_args(argv)
    try:
        config = load_config(known.config)
    except (OSError, ValueError) as e:
        print(f"live.py: {e}", file=sys.stderr)
        return REFUSED_EXIT
    config.pop("papers", None)
    ap = parser(config)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        a.port = smoke.check_port(a.port)
        if a.max_msgs < 1 or a.max_usd <= 0:
            raise ValueError("--max-msgs and --max-usd must be positive: a run always has both caps")
        if a.fake_codex and not a.fake:
            raise ValueError("--fake-codex is a rehearsal: give the fake claude too (--fake), so that no real agent is started")
        if a.stop_prerun and not a.fake_codex:
            raise ValueError("--stop-prerun slows the Codex skill copy's status: it needs --fake-codex")
    except ValueError as e:
        ap.error(str(e))
    if not WINDOWS:
        ap.error("Windows only: the watcher reads netstat -ano and Win32_Process")
    if not a.zotero or not os.path.isfile(a.zotero):
        ap.error(f"--zotero: no zotero.exe at {a.zotero}")
    if not a.pdf or not os.path.isfile(a.pdf):
        ap.error(f"--pdf: no PDF at {a.pdf}")
    if a.meta and not os.path.isfile(a.meta):
        ap.error(f"--meta: no file at {a.meta}")
    a.zotero, a.pdf = os.path.abspath(a.zotero), os.path.abspath(a.pdf)
    if a.fake_codex:
        a.fake_codex = os.path.abspath(a.fake_codex)
        if not os.path.isfile(a.fake_codex):
            ap.error("--fake-codex: build fakecodex.exe first (scripts/smoke/README.md)")
    if a.fake:
        a.fake = os.path.abspath(a.fake)
        if not os.path.isfile(a.fake):
            ap.error("--fake: build fakeclaude.exe first (scripts/smoke/README.md)")
    else:
        a.claude = os.path.abspath(a.claude) if a.claude else find_claude()
        if not a.claude or not os.path.isfile(a.claude):
            ap.error("--claude: no claude executable found")
    a.tag = a.tag or time.strftime("%Y%m%d-%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", a.tag):
        ap.error("--tag: letters, digits, . _ - only")
    a.out = os.path.abspath(a.out or os.path.join(tempfile.gettempdir(), "scholium-live"))
    ok, a.personal = check_script(personal_script())
    if not ok:
        print(f"refused: {a.personal}", file=sys.stderr)
        return REFUSED_EXIT
    try:
        a.commit = commit_of(a.git)
        os.makedirs(a.out, exist_ok=True)
        s = session(a)
    except (RefusedError, RuntimeError, subprocess.CalledProcessError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED_EXIT
    if not s["safe"]:
        print(f"[{a.tag}] SAFETY STOP: see live.json, watch23119.txt and chain-done.json in {os.path.join(a.out, a.tag)}", flush=True)
        return SAFETY_EXIT
    if s["unverified"]:
        print(f"[{a.tag}] UNVERIFIED: " + "; ".join(s["unverified"]), flush=True)
        return UNVERIFIED_EXIT
    print(f"[{a.tag}] {'complete' if s['complete'] else 'INCOMPLETE'}; score it: python scripts/smoke/eval.py report {os.path.join(a.out, a.tag)}", flush=True)
    return 0 if s["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
