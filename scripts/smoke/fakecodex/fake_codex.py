"""A stand-in for `codex app-server` in a THROWAWAY Zotero (scripts/smoke/live.py --fake-codex): no model, no account,
nothing leaves the machine.

    fakecodex.exe --version          codex-cli 0.999.0
    fakecodex.exe app-server         JSON-RPC over stdin and stdout, one message per line

fakecodex.exe (launcher.cs) starts this file beside it with the Python named in python.txt. It answers what the
Scholium plugin asks (initialize, account/read, model/list, mcpServerStatus/list, plugin/installed, skills/list from
CODEX_HOME/skills and <cwd>/.agents/skills only, skills/extraRoots/set, thread/start|resume|fork|archive|inject_items,
turn/start|interrupt|steer) and plays a turn. For the plugin's one-click annotation it reads sentences.txt (or runs
extract when the plugin's pre-run did not), writes config.json and reading_note.html with placeholder comments, and runs
the skill's own scholium.py --apply against Zotero at SCHOLIUM_ZOTERO_PORT, refused when that is missing, below 1024 or
23119 (the user's Zotero). Any other turn gets a one-sentence answer. Every message in and out, and the process's
arguments, folder and port/uv/Codex variables, go to <SCHOLIUM_FAKE_CODEX_LOG or calls beside this file>/<time>-<pid>.jsonl.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
USER_PORT = 23119
SHELL = r"C:\Program Files\PowerShell\7\pwsh.exe"   # the shell Codex names in a command item (shown only)
ANNOTATE = re.compile(r"为下面这篇论文做整篇标注|annotate the whole paper below")   # the plugin's one-click prompt
LOCK = threading.Lock()
STATE = {"threads": 0, "turns": 0, "items": 0, "interrupted": set(), "done": set()}
_log = None


def log(kind, data):
    global _log
    with LOCK:
        if _log is None:
            folder = os.environ.get("SCHOLIUM_FAKE_CODEX_LOG") or os.path.join(HERE, "calls")
            os.makedirs(folder, exist_ok=True)
            _log = open(os.path.join(folder, "%s-%d.jsonl" % (time.strftime("%H%M%S"), os.getpid())), "a", encoding="utf-8")
        _log.write(json.dumps({"t": round(time.time(), 3), "kind": kind, "data": data}, ensure_ascii=False) + "\n")
        _log.flush()


def send(msg):
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n"
    with LOCK:
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
    log("out", msg)


def notify(method, params):
    send({"method": method, "params": params})


def env_facts(env=None):
    env = os.environ if env is None else env
    return {k: env.get(k) for k in ("SCHOLIUM_ZOTERO_PORT", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "CODEX_HOME", "PYTHONPATH", "APPDATA", "TEMP")}


def port_ok(env=None):
    """The port the skill's script will write to: a number from 1024 to 65535 that is not the user's Zotero's."""
    p = str((os.environ if env is None else env).get("SCHOLIUM_ZOTERO_PORT", "")).strip()
    return p.isdigit() and 1024 <= int(p) <= 65535 and int(p) != USER_PORT


def is_annotation(text):
    return bool(ANNOTATE.search(text or ""))


def skills_in(root):
    out = []
    if root and os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            md = os.path.join(root, name, "SKILL.md")
            if os.path.isfile(md):
                out.append({"name": name, "path": md, "enabled": True, "description": "listed by the fake", "scope": "user"})
    return out


def filler(words):
    """A placeholder comment of about 1.6 CJK characters per English word, without digits, Latin words or colons."""
    base = "这是假代理写的测试译文只用来检查写入流程并不是真正的翻译内容请忽略"
    n = max(12, int(words * 1.6))
    return (base * (n // len(base) + 1))[:n] + "。"


def new_id(kind):
    STATE["items"] += 1
    return "%s_%d" % (kind, STATE["items"])


def command(thread, turn, cwd, shown, argv=None, read=None):
    """A commandExecution item: argv is run for real (stdin not the fake's: a child inheriting a pipe that has a read
    pending blocks at its start on Windows), or the head of the file read is its output."""
    cid = new_id("cmd")
    full = '"%s" -Command \'%s\'' % (SHELL, shown.replace("'", "''"))
    base = {"type": "commandExecution", "id": cid, "command": full, "cwd": cwd, "commandActions": []}
    notify("item/started", {"threadId": thread, "turnId": turn, "item": dict(base, status="inProgress", aggregatedOutput=None, exitCode=None)})
    t0 = time.time()
    if argv:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, timeout=600)
        output, code = (p.stdout + p.stderr)[-20000:], p.returncode
    else:
        try:
            with open(read, encoding="utf-8", errors="replace") as f:
                output, code = "".join(f.readlines()[:400]), 0
        except OSError as e:
            output, code = str(e), 1
    notify("item/completed", {"threadId": thread, "turnId": turn, "item": dict(base, status="completed" if code == 0 else "failed",
                                                                             aggregatedOutput=output, exitCode=code, durationMs=int((time.time() - t0) * 1000))})
    return output, code


def usage(thread, turn, n):
    last = {"inputTokens": 9000, "cachedInputTokens": 6000, "cacheWriteInputTokens": 0, "outputTokens": 400, "reasoningOutputTokens": 100, "totalTokens": 9400}
    notify("thread/tokenUsage/updated", {"threadId": thread, "turnId": turn,
                                         "tokenUsage": {"total": {k: v * n for k, v in last.items()}, "last": last, "modelContextWindow": 200000}})


def say(thread, turn, text):
    notify("item/completed", {"threadId": thread, "turnId": turn, "item": {"type": "agentMessage", "id": new_id("msg"), "text": text}})


def finish(thread, turn, t0, status="completed"):
    """turn/completed, once per turn (an interrupt completes it at once, as Codex does)."""
    if turn in STATE["done"]:
        return
    STATE["done"].add(turn)
    notify("turn/completed", {"threadId": thread, "turn": {"id": turn, "status": status, "items": [], "error": None,
                                                           "durationMs": int((time.time() - t0) * 1000)}})


def annotate(thread, turn, text, skill, cwd):
    t0 = time.time()
    m = re.search(r"([A-Za-z]:\\[^\r\n\"]*?paper\.json|/[^\r\n\"]*?paper\.json)", text)
    if not m or not skill:
        say(thread, turn, "没有找到 paper.json 或技能。")
        return finish(thread, turn, t0, "failed")
    paper_json = m.group(1)
    with open(paper_json, encoding="utf-8") as f:
        paper = json.load(f)
    out = paper["out_dir"]
    script = os.path.join(os.path.dirname(skill), "scripts", "scholium.py")
    stopped = lambda: turn in STATE["interrupted"]
    say(thread, turn, "先看技能说明和句子表。")
    time.sleep(1.0)
    command(thread, turn, cwd, 'Get-Content -Raw "%s"' % skill, read=skill)
    sentences, txt = os.path.join(out, "sentences.json"), os.path.join(out, "sentences.txt")
    if not os.path.isfile(sentences):   # no pre-run: the agent extracts
        time.sleep(1.0)
        command(thread, turn, cwd, 'python "%s" extract --config "%s" --sentences "%s" --out "%s"' % (script, paper_json, sentences, txt),
                argv=[sys.executable, script, "extract", "--config", paper_json, "--sentences", sentences, "--out", txt])
    if stopped():
        return finish(thread, turn, t0, "interrupted")
    time.sleep(1.5)
    command(thread, turn, cwd, 'Get-Content "%s" -TotalCount 400' % txt, read=txt)
    usage(thread, turn, 1)
    if stopped():
        return finish(thread, turn, t0, "interrupted")
    with open(sentences, encoding="utf-8") as f:
        data = json.load(f)
    pick = [s for s in data["sentences"] if s["page"] <= 2 and 80 <= len(s["text"]) <= 260 and not re.search(r"[@{}†∗]", s["text"])][:4]
    found = re.search(r'"title":\s*"([^"]+)"', text)
    title = found.group(1) if found else "Fake Codex paper"
    highlights = [{"id": s["id"], "core": i < 2, "comment": filler(len(s["text"].split()))} for i, s in enumerate(pick)]
    summaries = [{"id": pick[0]["id"], "text": "假代理的页边批注，用来检查页边文本能否写进去。"}] if pick else []
    note = os.path.join(out, "reading_note.html")
    with open(note, "w", encoding="utf-8") as f:
        f.write("<h1>%s</h1><h2>问题</h2><p>假代理的阅读笔记，只用来检查笔记写入。</p><h2>方法</h2><p>没有真正的内容。</p>" % title)
    cfg_path = os.path.join(out, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"pdf": paper["pdf"], "item_key": paper["item_key"], "attachment_key": paper["attachment_key"], "out_dir": out,
                   "sentences": sentences, "note_html": note, "note_title_prefix": title, "cleanup": False,
                   "highlights": highlights, "summaries": summaries}, f, ensure_ascii=False, indent=1)
    time.sleep(1.5)
    changes = [{"path": cfg_path, "kind": {"type": "add"}, "diff": ""}, {"path": note, "kind": {"type": "add"}, "diff": ""}]
    item = {"type": "fileChange", "id": new_id("fc"), "changes": changes}
    notify("item/started", {"threadId": thread, "turnId": turn, "item": dict(item, status="inProgress")})
    notify("item/completed", {"threadId": thread, "turnId": turn, "item": dict(item, status="completed")})
    usage(thread, turn, 2)
    if stopped():
        return finish(thread, turn, t0, "interrupted")
    time.sleep(1.5)
    if port_ok():
        output, code = command(thread, turn, cwd, 'python "%s" --config "%s" --apply' % (script, cfg_path),
                               argv=[sys.executable, script, "--config", cfg_path, "--apply"])
    else:
        output = "refused by the fake: SCHOLIUM_ZOTERO_PORT is %r" % os.environ.get("SCHOLIUM_ZOTERO_PORT")
        command(thread, turn, cwd, "echo refused", read=os.devnull)
    usage(thread, turn, 3)
    try:
        rep = json.loads(output[output.index("{"):])
    except ValueError:
        rep = {}
    created = (rep.get("result") or {}).get("created") or {}
    left = len(rep.get("translation_warnings") or []) + len(rep.get("style_warnings") or [])
    if rep.get("applied"):
        closing = "高亮 %d 条（核心 %d 条），页边批注 %d 条，笔记《%s》，剩余警告：%s" % (
            created.get("highlight", 0), sum(1 for h in highlights if h["core"]), created.get("text", 0), title, "%d 条" % left if left else "无")
    else:
        closing = "没有写入：%s" % (rep.get("apply_error") or output[-200:])
    say(thread, turn, closing)
    finish(thread, turn, t0)


def answer(thread, turn):
    t0 = time.time()
    time.sleep(1.0)
    say(thread, turn, "这篇论文的要点在摘要里。（假 Codex 的回答，没有调用模型）")
    usage(thread, turn, 1)
    finish(thread, turn, t0)


def guarded(body, thread, turn):
    """A turn ends with turn/completed whatever happens in it."""
    t0 = time.time()
    try:
        body()
    except Exception as e:  # noqa: BLE001
        log("error", "turn failed: " + repr(e))
        say(thread, turn, "假 Codex 出错：" + repr(e)[:200])
        finish(thread, turn, t0, "failed")


def reply(msg):
    """The answer to a request, or None for one answered elsewhere (turn/start, turn/interrupt) or a notification."""
    method, p = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"result": {"userAgent": "fake-codex/0.999.0", "codexHome": os.environ.get("CODEX_HOME")}}
    if method == "account/read":
        return {"result": {"account": {"type": "apiKey"}, "requiresOpenaiAuth": False}}
    if method == "model/list":
        return {"result": {"data": [{"id": "gpt-fake", "model": "gpt-fake", "displayName": "GPT Fake", "description": "no model is called",
                                     "isDefault": True, "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "medium"}]}],
                           "nextCursor": None}}
    if method == "mcpServerStatus/list":
        return {"result": {"data": [], "nextCursor": None}}
    if method == "plugin/installed":
        return {"result": {"marketplaces": []}}
    if method == "skills/list":
        home = os.environ.get("CODEX_HOME") or ""
        return {"result": {"data": [{"cwd": cwd, "skills": skills_in(os.path.join(home, "skills") if home else "") + skills_in(os.path.join(cwd, ".agents", "skills")),
                                     "errors": []} for cwd in p.get("cwds") or []]}}
    if method in ("skills/extraRoots/set", "thread/archive", "thread/inject_items", "turn/steer", "thread/compact/start"):
        return {"result": {}}
    if method in ("thread/start", "thread/fork"):
        STATE["threads"] += 1
        return {"result": {"thread": {"id": "thr_fake_%d_%d" % (os.getpid(), STATE["threads"])}, "model": "gpt-fake"}}
    if method == "thread/resume":
        return {"result": {"thread": {"id": p.get("threadId")}, "model": "gpt-fake"}}
    return {"error": {"code": -32601, "message": "not handled by the fake: " + str(method)}}


def handle(msg):
    method, mid, p = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return
    if method == "turn/interrupt":   # as Codex: the turn ends now, interrupted
        STATE["interrupted"].add(p.get("turnId"))
        send({"id": mid, "result": {}})
        return finish(p.get("threadId"), p.get("turnId"), time.time(), "interrupted")
    if method == "turn/start":
        STATE["turns"] += 1
        turn, thread, cwd = "turn_fake_%d" % STATE["turns"], p.get("threadId"), os.getcwd()
        send({"id": mid, "result": {"turn": {"id": turn, "status": "inProgress", "items": [], "error": None}}})
        text = "\n".join(i.get("text", "") for i in p.get("input") or [] if i.get("type") == "text")
        skill = next((i.get("path") for i in p.get("input") or [] if i.get("type") == "skill"), None)
        whole = is_annotation(text)
        log("turn", {"turn": turn, "annotate": whole, "skill": skill, "chars": len(text), "cwd": cwd})
        body = (lambda: annotate(thread, turn, text, skill, cwd)) if whole else (lambda: answer(thread, turn))
        threading.Thread(target=guarded, args=(body, thread, turn), daemon=True).start()
        return
    send(dict({"id": mid}, **reply(msg)))


def main(argv):
    log("start", {"argv": argv, "cwd": os.getcwd(), "env": env_facts(), "port_ok": port_ok()})
    if argv[:1] == ["--version"]:
        print("codex-cli 0.999.0")
        return 0
    if argv[:1] != ["app-server"]:
        print("fake codex: only --version and app-server", file=sys.stderr)
        return 2
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        log("in", msg)
        try:
            handle(msg)
        except Exception as e:  # noqa: BLE001 - an answer even when the fake fails
            log("error", repr(e))
            if msg.get("id") is not None:
                send({"id": msg["id"], "error": {"code": -32000, "message": "fake failed: " + repr(e)}})
    log("eof", {})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
