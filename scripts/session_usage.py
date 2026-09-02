"""Model calls and tokens of agent sessions, from Codex rollouts or Claude Code transcripts.

    python scripts/session_usage.py [--json] FILE...
    python scripts/session_usage.py --codex-today

A Codex rollout (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl) is read through its token_count events:
input is the context sent on each call (cached part included), so the sum is what the model processed.
A Claude Code transcript (assistant lines with message.usage) is read the same way: input = input_tokens
+ cache_read + cache_creation per call. Tool calls are counted by kind (scholium dry-run / apply / --list /
extract, zotero API, read file, write file, other) with the size of their outputs.
"""
import argparse, collections, datetime, glob, json, os, sys


def classify(cmd):
    c = (cmd or "").lower()
    if "scholium" in c:
        if "--apply" in c:
            return "scholium apply"
        if "--list" in c:
            return "scholium --list"
        if " extract" in c:
            return "scholium extract"
        if "--config" in c:
            return "scholium dry-run"
        return "scholium other"
    if "23119" in c or "curl " in c or "invoke-restmethod" in c or "invoke-webrequest" in c:
        return "zotero API"
    if "set-content" in c or "out-file" in c or "apply_patch" in c or "*** begin patch" in c or "add-content" in c:
        return "write file"
    if "get-content" in c or c.startswith("cat ") or "sed -n" in c or c.startswith("type ") or c.startswith("head "):
        return "read file"
    return "other"


def _text(x):
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)


def read_codex(path):
    calls, inp, cached, out, peak = 0, 0, 0, 0, 0
    tools, outputs, pending = collections.Counter(), 0, {}
    with open(path, encoding="utf8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t, p = rec.get("type"), rec.get("payload") or {}
            if t == "event_msg" and p.get("type") == "token_count":
                last = (p.get("info") or {}).get("last_token_usage") or {}
                if last.get("input_tokens"):
                    calls += 1; inp += last["input_tokens"]; cached += last.get("cached_input_tokens", 0) or 0
                    out += last.get("output_tokens", 0) or 0; peak = max(peak, last["input_tokens"])
            elif t == "response_item":
                if p.get("type") in ("function_call", "custom_tool_call"):
                    args = _text(p.get("arguments") or p.get("input") or "")
                    try:
                        cmd = json.loads(args).get("cmd") or args
                    except Exception:
                        cmd = args
                    kind = classify(cmd) if p.get("name") not in ("spawn_agent", "wait_agent", "list_agents") else "sub-agent control"
                    tools[kind] += 1; pending[p.get("call_id")] = kind
                elif p.get("type") in ("function_call_output", "custom_tool_call_output") and p.get("call_id") in pending:
                    outputs += len(_text(p.get("output") or ""))
    return {"harness": "codex", "calls": calls, "input": inp, "cached": cached, "output": out, "peak": peak,
            "tools": dict(tools), "tool_output_chars": outputs}


def read_claude(path):
    calls, inp, cached, out, peak = 0, 0, 0, 0, 0
    tools, outputs = collections.Counter(), 0
    with open(path, encoding="utf8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            m = rec.get("message") or {}
            if rec.get("type") == "assistant":
                u = m.get("usage") or {}
                if u.get("input_tokens") is not None:
                    total = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
                    calls += 1; inp += total; cached += u.get("cache_read_input_tokens") or 0
                    out += u.get("output_tokens") or 0; peak = max(peak, total)
                for c in m.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        name, arg = (c.get("name") or "").lower(), c.get("input") or {}
                        kind = {"read": "read file", "write": "write file", "edit": "write file", "multiedit": "write file",
                                "agent": "sub-agent control"}.get(name) or (classify(arg.get("command", "")) if name == "bash" else name)
                        tools[kind] += 1
            elif rec.get("type") == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        outputs += len(_text(c.get("content") or ""))
    return {"harness": "claude", "calls": calls, "input": inp, "cached": cached, "output": out, "peak": peak,
            "tools": dict(tools), "tool_output_chars": outputs}


def read_session(path):
    with open(path, encoding="utf8", errors="ignore") as f:
        head = f.read(4000)
    row = read_codex(path) if '"payload"' in head or '"session_meta"' in head else read_claude(path)
    row["file"] = path
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="rollout or transcript .jsonl files")
    ap.add_argument("--codex-today", action="store_true", help="add today's Codex rollouts")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    files = list(args.files)
    if args.codex_today:
        d = datetime.date.today()
        files += sorted(glob.glob(os.path.expanduser(f"~/.codex/sessions/{d:%Y/%m/%d}/*.jsonl")), key=os.path.getmtime)
    if not files:
        ap.error("give files or --codex-today")
    rows = [read_session(p) for p in files]
    if args.json:
        print(json.dumps({"sessions": rows}, ensure_ascii=False, indent=1))
        return 0
    for r in rows:
        share = f"{r['cached'] / r['input']:.0%}" if r["input"] else "-"
        print(f"{os.path.basename(r['file'])[:44]:44s} {r['harness']:6s} calls {r['calls']:4d}  input {r['input']:>12,} (cached {share})  output {r['output']:>8,}  peak {r['peak']:>9,}")
        print("    tools: " + ", ".join(f"{k} {v}" for k, v in sorted(r["tools"].items(), key=lambda x: -x[1])) + f"; tool output {r['tool_output_chars']:,} chars")
    if len(rows) > 1:
        print(f"{'total':44s} {'':6s} calls {sum(r['calls'] for r in rows):4d}  input {sum(r['input'] for r in rows):>12,}  output {sum(r['output'] for r in rows):>8,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
