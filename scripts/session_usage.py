"""Model calls and tokens of agent sessions, from Codex rollouts or Claude Code transcripts.

    python scripts/session_usage.py [--json] FILE...
    python scripts/session_usage.py --codex-today

A Codex rollout (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl) is read through its token_count events:
input is the context sent on each call (cached part included), so the sum is what the model processed.
A Claude Code transcript (assistant lines with message.usage) is read the same way: input = input_tokens
+ cache_read + cache_creation per call. Tool calls are counted by kind (scholium dry-run / apply / --list /
extract, zotero API, read file, write file, other) with the size of their outputs.
Repeated message/tool IDs and cumulative token events are counted once. Records without IDs or cumulative
usage retain per-record accounting; equal token counts alone do not identify a repeated call.
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
    tools, outputs, seen_calls = collections.Counter(), 0, set()
    previous, current, seen_events, seen_outputs, session = {}, {}, set(), set(), None
    fields = ("input_tokens", "cached_input_tokens", "output_tokens")
    with open(path, encoding="utf8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t, p = rec.get("type"), rec.get("payload") or {}
            if t == "session_meta" and p.get("id") and p["id"] != session:
                session, previous, current = p["id"], {}, {}
            if t == "event_msg" and p.get("type") == "token_count":
                info = p.get("info") or {}
                event_id = rec.get("id") or rec.get("uuid")
                if not event_id and rec.get("timestamp"):
                    event_id = (rec["timestamp"], json.dumps(info, sort_keys=True))
                if event_id:
                    event_key = (session, event_id)
                    if event_key in seen_events:
                        continue
                    seen_events.add(event_key)
                last = info.get("last_token_usage") or {}
                total = {k: v for k, v in (info.get("total_token_usage") or {}).items()
                         if k in fields and v is not None}
                common = total.keys() & previous.keys()
                if any(total[k] < previous[k] for k in common):
                    previous, current = {}, {}   # a reset starts a new cumulative segment
                same_call = bool(current) and "input_tokens" in total and total["input_tokens"] == previous.get("input_tokens")
                # At the start (or after a reset), last excludes any history before this file.
                delta = {k: total[k] - previous[k] if k in total and k in previous
                         else last.get(k) if last.get(k) is not None else total.get(k, 0) for k in fields}
                if same_call:
                    for k in fields:
                        if k not in total or k not in previous:
                            value = last.get(k) if last.get(k) is not None else total.get(k)
                            delta[k] = value - current[k] if value is not None else 0
                for k in fields:
                    if k in total:
                        previous[k] = total[k]
                    elif k in previous:
                        previous[k] += delta[k]   # do not count a last-only gap again at the next total
                if any(delta.values()):
                    if same_call:
                        current = {k: current[k] + delta[k] for k in fields}
                    else:
                        calls += 1
                        current = delta
                    inp += delta["input_tokens"]; cached += delta["cached_input_tokens"]
                    out += delta["output_tokens"]; peak = max(peak, current["input_tokens"])
            elif t == "response_item":
                call_id = p.get("call_id")
                call_key = (session, call_id)
                if p.get("type") in ("function_call", "custom_tool_call"):
                    if call_id and call_key in seen_calls:
                        continue
                    args = _text(p.get("arguments") or p.get("input") or "")
                    try:
                        cmd = json.loads(args).get("cmd") or args
                    except Exception:
                        cmd = args
                    kind = classify(cmd) if p.get("name") not in ("spawn_agent", "wait_agent", "list_agents") else "sub-agent control"
                    tools[kind] += 1; seen_calls.add(call_key)
                elif p.get("type") in ("function_call_output", "custom_tool_call_output") and call_key in seen_calls:
                    text = _text(p.get("output") or "")
                    output_id = rec.get("id") or rec.get("uuid")
                    output_key = (call_key, ("id", output_id) if output_id else ("text", text))
                    if not call_id or output_key not in seen_outputs:
                        outputs += len(text)
                        seen_outputs.add(output_key)
    return {"harness": "codex", "calls": calls, "input": inp, "cached": cached, "output": out, "peak": peak,
            "tools": dict(tools), "tool_output_chars": outputs}


def read_claude(path):
    calls, inp, cached, out, peak = 0, 0, 0, 0, 0
    tools, outputs = collections.Counter(), 0
    messages, seen_tools, seen_outputs, seen_records = {}, set(), set(), set()
    with open(path, encoding="utf8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            record_id = rec.get("uuid") or rec.get("id")
            if record_id:
                if record_id in seen_records:
                    continue
                seen_records.add(record_id)
            m = rec.get("message") or {}
            if rec.get("type") == "assistant":
                u = m.get("usage") or {}
                # Each streamed content block repeats usage. Keep the final known fields per message.
                mid = m.get("id") or object()
                messages.setdefault(mid, {}).update({k: v for k, v in u.items() if v is not None})
                for c in m.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        if c.get("id") and c["id"] in seen_tools:
                            continue
                        if c.get("id"):
                            seen_tools.add(c["id"])
                        name, arg = (c.get("name") or "").lower(), c.get("input") or {}
                        kind = {"read": "read file", "write": "write file", "edit": "write file", "multiedit": "write file",
                                "agent": "sub-agent control"}.get(name) or (classify(arg.get("command", "")) if name == "bash" else name)
                        tools[kind] += 1
            elif rec.get("type") == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        text = _text(c.get("content") or "")
                        output_key = (c.get("tool_use_id"), text)
                        if not c.get("tool_use_id") or output_key not in seen_outputs:
                            outputs += len(text)
                            seen_outputs.add(output_key)
    for u in messages.values():
        if any(k in u for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")):
            total = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
            calls += 1; inp += total; cached += u.get("cache_read_input_tokens") or 0
            out += u.get("output_tokens") or 0; peak = max(peak, total)
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
