#!/usr/bin/env python3
"""What live runs (live.py) cost and wrote, and the evaluation set's runs.

    python scripts/smoke/eval.py report RUN... [--compare BASELINE.json] [--calls]
        a row per run: cost, tokens by kind, turns, wall time, what the agent read, the reading note's structure, the
        closing line; --calls adds each run's tool calls, the context of each API message and the heaviest tool results
    python scripts/smoke/eval.py score RUN... [--out NAME] [--compare BASELINE.json]
        the quality table: highlights, core, pages, highlights from the references on, comments, margin notes, the
        reading note, warnings, dry runs, ...; --out writes NAME.json (a baseline) and NAME.md
    python scripts/smoke/eval.py run --zotero <zotero.exe> --papers <folder> [--only dpo,ddpm] [--git REV[,REV...]]
        [--repeat N] [--max-usd 1.00] [--out DIR] [--compare BASELINE.json] [--fake <fakeclaude.exe>]
        the evaluation set (evalset.json) through live.py, a throwaway Zotero per paper, then score --out <out>/eval

A run is a folder live.py made (probe-config.json, live.json, data/, shots/). A baseline is the JSON of score --out:
{"papers": [...]}, without paths of the machine; runs are compared with the baseline's run of the same paper (arXiv id).
`run` stops starting runs once the set's result lines add up to --max-usd (each run is given what is left as its own
--max-usd), and stops the set when live.py refuses a run, a safety layer stopped one, or one is unverified (exit code
2, 3 or 4).
"""
import argparse
import collections
import difflib
import glob
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import live  # noqa: E402

EVALSET = os.path.join(HERE, "evalset.json")
STOPS = (live.REFUSED_EXIT, live.SAFETY_EXIT, live.UNVERIFIED_EXIT)   # live.py's exit codes that end a set
CJK = re.compile(r"[一-鿿]")
TAG = "zotero-scholium"
READ_FILES = ("SKILL.md", "reading_note.template.html", "config.template.json", "style-zh.md", "style-en.md")


# ---------------------------------------------------------------------------------------------------------------------
# a run's files
# ---------------------------------------------------------------------------------------------------------------------
def read_json(path, default):
    try:
        with open(path, encoding="utf8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def events_of(paths):
    out = []
    for path in paths:
        with open(path, encoding="utf8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content or "")


def first_json(text):
    """The first JSON object in a tool result (the CLI's report), or None."""
    i = text.find("{")
    while i >= 0:
        try:
            return json.JSONDecoder().raw_decode(text[i:])[0]
        except ValueError:
            i = text.find("{", i + 1)
    return None


def kind(name, inp):
    """A tool call by what it did: the skill's script by its command, a file tool by the file's name, else the tool."""
    if name in ("Bash", "PowerShell"):
        cmd = str(inp.get("command", ""))
        if not re.search(r"scholium(\.py)?\b", cmd):
            return "other"
        if re.search(r"\bstatus\b", cmd): return "status"
        if re.search(r"\bextract\b", cmd): return "extract"
        if "--apply" in cmd: return "apply"
        if "--list" in cmd: return "list"
        if re.search(r"\bprofile\b", cmd): return "profile"
        if re.search(r"\bsamples\b", cmd): return "samples"
        if "--config" in cmd: return "dry run"
        return "other scholium"
    return name


def ref_page(pdf):
    """The first page (1-based) with a References or Bibliography heading line; None without one or without PyMuPDF."""
    try:
        import pymupdf
    except ImportError:
        return None
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc):
            for ln in page.get_text().splitlines():
                if re.fullmatch(r"\s*(\d+\s*)?(references|bibliography)\s*", ln, re.I):
                    return i + 1
    return None


def run_files(run):
    """The run's probe config, facts, database dump, live.json, its paper's folder in the data's tmp and its logs."""
    cfg = read_json(os.path.join(run, "probe-config.json"), {})
    facts = read_json(os.path.join(run, "shots", "facts.json"), [])
    att = next((f.get("att") for f in facts if f.get("what") == "items"), None)
    logs = live.conversation_logs(run, "annotate-*")
    if att:
        mine = [p for p in logs if os.path.basename(os.path.dirname(os.path.dirname(p))) == att]
        logs = mine or logs
    att_dir = os.path.dirname(os.path.dirname(logs[-1])) if logs else None
    if logs:   # the logs of the run's paper only
        logs = [p for p in logs if os.path.dirname(os.path.dirname(p)) == att_dir]
    return {"cfg": cfg, "facts": facts, "db": read_json(os.path.join(run, "shots", "db.json"), {"anns": [], "notes": []}),
            "live": read_json(os.path.join(run, "live.json"), {}), "att_dir": att_dir, "logs": logs}


# ---------------------------------------------------------------------------------------------------------------------
# the scores of a run
# ---------------------------------------------------------------------------------------------------------------------
def usage_totals(results):
    u = lambda r: r.get("usage") or {}
    return {"cost_usd": round(sum(r.get("total_cost_usd") or 0 for r in results), 4),
            "turns": sum(r.get("num_turns") or 0 for r in results), "runs": len(results),
            "duration_s": round(sum(r.get("duration_ms") or 0 for r in results) / 1000),
            "input_tokens": sum(u(r).get("input_tokens") or 0 for r in results),
            "cache_read": sum(u(r).get("cache_read_input_tokens") or 0 for r in results),
            "cache_write": sum(u(r).get("cache_creation_input_tokens") or 0 for r in results),
            "output_tokens": sum(u(r).get("output_tokens") or 0 for r in results),
            "thinking_tokens": sum((u(r).get("output_tokens_details") or {}).get("thinking_tokens") or 0 for r in results),
            "result_error": any(r.get("is_error") for r in results)}


def tool_facts(events):
    """The tool calls by kind, the CLI's dry-run and apply reports, the files the agent read (sentences.txt's offsets)."""
    uses, reports, counts, reads, read_files, tool_errors, note_title = {}, [], collections.Counter(), [], set(), 0, 0
    for e in events:
        content = (e.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if e.get("type") == "assistant" and c.get("type") == "tool_use":
                inp = c.get("input") or {}
                k = kind(c.get("name"), inp)
                uses[c.get("id")] = k
                counts[k] += 1
                path = str(inp.get("file_path", "")).replace("\\", "/")
                if c.get("name") == "Read" and path.endswith("sentences.txt"):
                    reads.append(f"{inp.get('offset') or 1}+{inp.get('limit') or 'all'}")
                if c.get("name") in ("Read", "Bash", "PowerShell", "Grep", "Glob"):
                    blob = path + " " + str(inp.get("command", "")) + " " + str(inp.get("pattern", ""))
                    for name in READ_FILES:
                        if name in blob:
                            read_files.add(name)
            elif e.get("type") == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in uses:
                k, t = uses[c["tool_use_id"]], text_of(c.get("content"))
                tool_errors += bool(c.get("is_error"))
                note_title += bool(re.search(r'"kind":\s*"note_title"', t))
                if k in ("dry run", "apply"):
                    rep = first_json(t)
                    failed = bool(c.get("is_error")) or rep is None or bool(re.search(r"Traceback|config error", t))
                    reports.append({"kind": k, "failed": failed, "report": rep or {},
                                    "error": t.strip().splitlines()[-1][:200] if failed and t.strip() else None})
    return {"reports": reports, "counts": dict(counts), "reads": reads, "read_files": sorted(read_files),
            "tool_errors": tool_errors, "note_title_warnings": note_title}


def note_facts(notes, arxiv, doi):
    if not notes:
        return {"reading_notes": 0, "reading_note_chars": 0, "reading_note_paragraphs": 0, "reading_note_headings": 0,
                "reading_note_h1": False, "reading_note_citation": False}
    h = notes[-1].get("html") or ""
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
    return {"reading_notes": len(notes), "reading_note_chars": len(plain), "reading_note_paragraphs": len(re.findall(r"<p[\s>]", h, re.I)),
            "reading_note_headings": len(re.findall(r"<h[1-6][\s>]", h, re.I)), "reading_note_h1": bool(re.search(r"<h1[\s>]", h, re.I)),
            "reading_note_citation": bool((arxiv and arxiv in plain) or (doi and doi in plain.lower()))}


def highlight_facts(anns, core_color, refs):
    hl = [a for a in anns if a.get("type") in ("highlight", "underline")]

    def page(a):   # 1-based: the position's page index, else a numeric page label
        if a.get("pageIndex") is not None:
            return a["pageIndex"] + 1
        return int(a["page"]) if str(a.get("page", "")).isdigit() else 0

    pages = collections.Counter(page(a) for a in hl)
    after = sum(n for p, n in pages.items() if refs and p >= refs)
    comment = lambda a: str(a.get("comment") or "")
    copies = [a for a in hl if comment(a).strip() and (not CJK.search(comment(a)) or
              difflib.SequenceMatcher(None, comment(a).lower(), str(a.get("text") or "").lower()).ratio() > 0.6)]
    return {"highlights": len(hl), "core": sum(1 for a in hl if str(a.get("color") or "").lower() == core_color),
            "pages_with_highlights": len(pages), "highlights_per_page": {str(p): n for p, n in sorted(pages.items())},
            "references_page": refs, "highlights_after_references": after,
            "share_after_references": round(after / len(hl), 3) if hl and refs else None,
            "comments_empty": sum(1 for a in hl if not comment(a).strip()), "comments_copy_english": len(copies),
            "comment_chars_mean": round(sum(len(comment(a)) for a in hl) / len(hl), 1) if hl else None,
            "margin_notes": sum(1 for a in anns if a.get("type") == "text"), "sticky_notes": sum(1 for a in anns if a.get("type") == "note")}


def evaluate(run, pdf_refs=ref_page):
    """Every measure of one run folder (no paths of the machine in it: the run is named by its folder's name)."""
    run = os.path.abspath(run)
    rf = run_files(run)
    fields = (rf["cfg"].get("paper") or {}).get("fields") or {}
    arxiv = str(fields.get("archiveID") or "").replace("arXiv:", "").strip() or os.path.basename(run)
    out = {"run": os.path.basename(run), "paper": fields.get("title", "?"), "arxiv": arxiv,
           "commit": rf["live"].get("commit"), "fake": rf["live"].get("fake")}
    if not rf["logs"]:
        out["error"] = "no annotation log"
        return out
    events = events_of(rf["logs"])
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    results = [e for e in events if e.get("type") == "result"]
    out["model"] = init.get("model")
    out.update(usage_totals(results))
    out["closing_line"] = (str(results[-1].get("result") or "").strip().splitlines() or [""])[-1][:240] if results else None
    ended = next((f for f in rf["facts"] if f.get("what") == "ended"), {})
    out["wall_s"] = ended.get("seconds")
    out["stopped"] = next((f.get("reason") for f in rf["facts"] if f.get("what") == "stop"), None) or ended.get("stopped") or False
    out["safe"] = rf["live"].get("safe")
    t = tool_facts(events)
    dry = [r for r in t["reports"] if r["kind"] == "dry run"]
    final = next((r["report"] for r in reversed(t["reports"]) if r["report"]), {})
    first_dry = next((r["report"] for r in dry if r["report"]), {})
    style = collections.Counter(w.get("kind", "?") for w in final.get("style_warnings") or [] if isinstance(w, dict))
    layout = [w for w in final.get("layout_warnings") or [] if isinstance(w, dict)]
    out.update(sentences_reads=t["reads"], read_files=t["read_files"], note_title_warnings=t["note_title_warnings"],
               dry_runs=len(dry), dry_runs_failed=sum(r["failed"] for r in dry), dry_run_errors=[r["error"] for r in dry if r["failed"]],
               applies=sum(1 for r in t["reports"] if r["kind"] == "apply"), applied=final.get("applied"), tool_errors=t["tool_errors"],
               tool_calls=t["counts"], translation_warnings_first=len(first_dry.get("translation_warnings") or []),
               translation_warnings_final=len(final.get("translation_warnings") or []), layout_warnings=len(layout),
               style_warnings=dict(style), overlaps=style.get("overlap", 0) + style.get("user_overlap", 0) + sum(1 for w in layout if "overlap" in str(w.get("reason", ""))),
               missed=len(final.get("missed") or []), fitted=len(final.get("fitted") or []), as_notes=len(final.get("as_notes") or []))
    cnt = next((e for e in reversed(events) if e.get("type") == "scholium" and e.get("subtype") == "counts"), {})
    out["card"] = {k: cnt.get(k) for k in ("highlights", "core", "margin", "notes", "readingNotes")}
    anns = [a for a in rf["db"].get("anns") or [] if TAG in (a.get("tags") or [])]
    core_color = str(read_json(os.path.join(rf["att_dir"], "config.json"), {}).get("core_color") or "#ff6666").lower()
    pdfs = glob.glob(os.path.join(run, "data", "storage", os.path.basename(rf["att_dir"]), "*.pdf"))
    out.update(highlight_facts(anns, core_color, pdf_refs(pdfs[0]) if pdfs else None))
    notes = [n for n in rf["db"].get("notes") or [] if TAG in (n.get("tags") or [])]
    out.update(note_facts(notes, arxiv, str(fields.get("DOI") or "").lower()))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------------------------------------------------
SUMMED = {"cost_usd", "wall_s", "duration_s", "turns", "input_tokens", "cache_read", "cache_write", "output_tokens",
          "thinking_tokens", "highlights", "core", "margin_notes", "sticky_notes"}
SCORE_ROWS = [("model", "model"), ("cost_usd", "cost (USD)"), ("wall_s", "wall time (s)"), ("duration_s", "agent time (s)"),
              ("turns", "turns"), ("input_tokens", "input tokens"), ("cache_read", "cache read"), ("cache_write", "cache write"),
              ("output_tokens", "output tokens"), ("thinking_tokens", "  of which thinking"), ("highlights", "highlights"),
              ("core", "  core"), ("pages_with_highlights", "pages with highlights"), ("references_page", "references start (page)"),
              ("highlights_after_references", "highlights from the references on"), ("share_after_references", "  share"),
              ("comments_empty", "comments empty"), ("comments_copy_english", "comments copying the English"),
              ("comment_chars_mean", "comment length (chars, mean)"), ("translation_warnings_first", "translation warnings (first dry run)"),
              ("translation_warnings_final", "translation warnings (at apply)"), ("margin_notes", "margin notes"),
              ("sticky_notes", "sticky notes"), ("layout_warnings", "layout warnings"), ("overlaps", "overlaps"),
              ("fitted", "margin notes set smaller"), ("as_notes", "margin notes made sticky"), ("missed", "phrases not found"),
              ("reading_note_chars", "reading note (chars)"), ("reading_note_paragraphs", "  paragraphs"),
              ("reading_note_headings", "  headings"), ("reading_note_h1", "  has an <h1>"), ("reading_note_citation", "  has the citation"),
              ("note_title_warnings", "note title warnings"), ("dry_runs", "dry runs"), ("dry_runs_failed", "  failed"),
              ("applies", "--apply runs"), ("applied", "applied"), ("tool_errors", "tool errors"), ("runs", "agent runs (retries)"),
              ("result_error", "run ended in error"), ("stopped", "stopped by the probe")]
REPORT_ROWS = [("model", "model"), ("cost_usd", "cost"), ("input_tokens", "input"), ("cache_read", "cache read"),
               ("cache_write", "cache write"), ("output_tokens", "output"), ("thinking_tokens", "thinking"), ("turns", "turns"),
               ("wall_s", "wall s"), ("duration_s", "agent s"), ("sentences_reads", "sentences.txt reads"), ("read_files", "also read"),
               ("reading_note_chars", "note chars"), ("reading_note_h1", "h1"), ("reading_note_headings", "headings"),
               ("closing_line", "closing line")]


def cell(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v)
    return str(v).replace("|", "/").replace("\n", " ")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def score_table(evals):
    lines = ["| metric | " + " | ".join(e["run"] for e in evals) + " | total |", "|" + "---|" * (len(evals) + 2),
             "| paper | " + " | ".join(e["arxiv"] for e in evals) + " | |"]
    for key, label in SCORE_ROWS:
        vals = [e.get(key) for e in evals]
        nums = [v for v in vals if is_num(v)]
        total = round(sum(nums), 4) if nums and key in SUMMED else ""
        lines.append(f"| {label} | " + " | ".join(cell(v) for v in vals) + f" | {total} |")
    lines.append("| per page | " + " | ".join(" ".join(f"{p}:{n}" for p, n in (e.get("highlights_per_page") or {}).items()) for e in evals) + " | |")
    lines.append("| style warnings at apply | " + " | ".join(cell(json.dumps(e.get("style_warnings") or {})) for e in evals) + " | |")
    lines.append("| tool calls | " + " | ".join(", ".join(f"{k} {v}" for k, v in sorted((e.get("tool_calls") or {}).items())) for e in evals) + " | |")
    return "\n".join(lines)


def report_table(evals):
    lines = ["| run | paper | " + " | ".join(label for _, label in REPORT_ROWS) + " |", "|" + "---|" * (len(REPORT_ROWS) + 2)]
    for e in evals:
        if e.get("error"):
            lines.append(f"| {e['run']} | {e['arxiv']} | {e['error']} |" + " |" * (len(REPORT_ROWS) - 1))
            continue
        lines.append(f"| {e['run']} | {e['arxiv']} | " + " | ".join(cell(e.get(k)) for k, _ in REPORT_ROWS) + " |")
    return "\n".join(lines)


def delta(a, b):
    """A baseline value a and a value now b, as one cell."""
    if is_num(a) and is_num(b):
        d = b - a
        if not d:
            return f"{b} (=)"
        pct = f" ({d / a * 100:+.0f}%)" if a else ""
        return f"{a} → {b} ({d:+.4g}){pct}"
    return f"{cell(b)} (=)" if a == b else f"{cell(a)} → {cell(b)}"


def compare_table(now, before, rows):
    """Each run against the baseline's run of the same paper (the first one, by arXiv id)."""
    old = {}
    for e in before:
        old.setdefault(e.get("arxiv"), e)
    lines = ["| metric | " + " | ".join(f"{e['run']} ({e['arxiv']})" for e in now) + " |", "|" + "---|" * (len(now) + 1)]
    lines.append("| baseline run | " + " | ".join(cell((old.get(e["arxiv"]) or {}).get("run") or "(none)") for e in now) + " |")
    for key, label in rows:
        lines.append(f"| {label} | " + " | ".join(delta((old.get(e["arxiv"]) or {}).get(key), e.get(key)) for e in now) + " |")
    return "\n".join(lines)


def calls_report(events):
    """A run's tool calls (result size, the tokens each added, the later messages that re-read it), the context of each
    API message, and the tool results that weigh most in cache reads."""
    msgs, order, uses, seq = {}, [], {}, 0
    for e in events:
        if e.get("type") == "assistant":
            m = e.get("message") or {}
            mid = m.get("id") or "noid-%d" % len(order)
            if mid not in msgs:   # stream-json repeats a message's usage for each content block
                order.append(mid)
                msgs[mid] = {"usage": {}, "tools": []}
            if m.get("usage"):
                msgs[mid]["usage"] = m["usage"]
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    seq += 1
                    uses[c.get("id")] = {"n": seq, "msg": len(order) - 1, "name": c.get("name"), "kind": kind(c.get("name"), c.get("input") or {}),
                                         "input": c.get("input") or {}}
                    msgs[mid]["tools"].append(c.get("id"))
        elif e.get("type") == "user":
            content = (e.get("message") or {}).get("content")
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in uses:
                    uses[c["tool_use_id"]].update(chars=len(text_of(c.get("content"))), error=bool(c.get("is_error")))
    ctx = []
    for i, mid in enumerate(order):
        u = msgs[mid]["usage"]
        ctx.append({"context": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0),
                    "read": u.get("cache_read_input_tokens") or 0, "write": u.get("cache_creation_input_tokens") or 0,
                    "output": u.get("output_tokens") or 0, "tools": [uses[t]["kind"] for t in msgs[mid]["tools"]]})
    n = len(ctx)
    for t in uses.values():   # a message's added tokens, shared among its tool calls by the size of their results
        i = t["msg"]
        same = [u for u in uses.values() if u["msg"] == i]
        chars = sum(u.get("chars") or 0 for u in same)
        share = (t.get("chars") or 0) / chars if chars else 1 / len(same)
        t["added"] = round(max(0, ctx[i + 1]["context"] - ctx[i]["context"] - ctx[i]["output"]) * share) if i + 1 < n else None
        t["reread"] = n - i - 1
    lines = ["tool calls (n, message, tool, kind, result chars, tokens added, re-read by later messages):"]
    for t in sorted(uses.values(), key=lambda t: t["n"]):
        what = ""
        if t["name"] in ("Bash", "PowerShell"):
            what = " | " + str(t["input"].get("command", ""))[:140].replace("\n", " ")
        elif t["name"] == "Read":
            what = " | %s offset=%s limit=%s" % (os.path.basename(str(t["input"].get("file_path", "")).replace("\\", "/")),
                                                 t["input"].get("offset"), t["input"].get("limit"))
        lines.append("  #%-2d m%-2d %-10s %-14s %7s ch %7s tok x%-2d%s%s" % (t["n"], t["msg"], t["name"], t["kind"][:14], t.get("chars"),
                                                                       t["added"], t["reread"], " ERROR" if t.get("error") else "", what))
    lines.append("context per API message (input + cache read + cache write; cache read; cache write; output; tools):")
    for i, c in enumerate(ctx):
        lines.append("  m%-2d ctx %7d  read %7d  write %6d  out %5d  %s" % (i, c["context"], c["read"], c["write"], c["output"], ",".join(c["tools"])))
    lines.append("heaviest tool results (tokens added x later messages):")
    for t in sorted(uses.values(), key=lambda t: -((t["added"] or 0) * t["reread"]))[:6]:
        lines.append("  #%-2d %-10s %-14s +%s tokens x %d = %d" % (t["n"], t["name"], t["kind"][:14], t["added"], t["reread"], (t["added"] or 0) * t["reread"]))
    if ctx:
        lines.append("the first message's context, %d tokens, re-read by %d messages; cache reads in all %d" % (ctx[0]["context"], n - 1, sum(c["read"] for c in ctx)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------------
# the evaluation set
# ---------------------------------------------------------------------------------------------------------------------
def load_set(path=EVALSET):
    with open(path, encoding="utf8") as f:
        data = json.load(f)
    names = [p["name"] for p in data["papers"]]
    if len(set(names)) != len(names) or not all(re.fullmatch(r"[a-z0-9-]+", n) for n in names):
        raise ValueError(f"{path}: paper names must be distinct, lower-case letters, digits and -")
    return data


def safe_name(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-") or "x"


def plan(papers, revs, repeat, only=None, prefix="eval"):
    """The runs in order, [(tag, paper, rev)]: each repeat goes through every rev, each rev through every paper
    (interleaved, so that a slow hour or a cache does not favour one rev)."""
    if only:
        want = {w.strip() for w in only.split(",") if w.strip()}
        unknown = want - {p["name"] for p in papers} - {p["arxiv"] for p in papers}
        if unknown:
            raise ValueError(f"--only: no paper {', '.join(sorted(unknown))} in the set")
        papers = [p for p in papers if p["name"] in want or p["arxiv"] in want]
    out = []
    for n in range(1, repeat + 1):
        for rev in revs:
            for p in papers:
                tag = "-".join([prefix, p["name"]] + ([safe_name(rev)] if len(revs) > 1 else []) + ([str(n)] if repeat > 1 else []))
                out.append((tag, p, rev))
    return out


def find_pdf(folder, arxiv):
    for path in (os.path.join(folder, arxiv + ".pdf"), os.path.join(folder, arxiv, "paper.pdf")):
        if os.path.isfile(path):
            return path
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run_set(a, data):
    revs = [r.strip() for r in a.git.split(",") if r.strip()]
    runs = plan(data["papers"], revs, a.repeat, a.only, a.prefix)
    missing = [p for _, p, _ in runs if not find_pdf(a.papers, p["arxiv"])]
    if missing:
        names = sorted({f"{p['arxiv']}.pdf from {p.get('pdf') or 'https://arxiv.org/pdf/' + p['arxiv']}" for p in missing})
        print("missing in --papers: " + "; ".join(names), file=sys.stderr)
        return live.REFUSED_EXIT
    for rev in revs:
        live.commit_of(rev)
    os.makedirs(a.out, exist_ok=True)
    defaults = data.get("run") or {}
    done, code = [], 0
    for tag, paper, rev in runs:
        spent = sum(live.session_cost(os.path.join(a.out, t)) for t in done)
        left = round(a.max_usd - spent, 4)
        if left < a.min_left:
            print(f"== stop before {tag}: {spent:.4f} of {a.max_usd:.2f} USD spent", flush=True)
            break
        pdf = find_pdf(a.papers, paper["arxiv"])
        if paper.get("sha256") and sha256(pdf) != paper["sha256"]:
            print(f"== note: {pdf} is not the set's {paper.get('pdf')} (SHA-256 differs): its scores may not compare", flush=True)
        meta = os.path.join(a.out, f"meta-{paper['name']}.json")
        with open(meta, "w", encoding="utf8") as f:
            json.dump({k: paper[k] for k in ("itemType", "fields", "creators")}, f, ensure_ascii=False, indent=1)
        cmd = [sys.executable, os.path.join(HERE, "live.py"), "--zotero", a.zotero, "--pdf", pdf, "--meta", meta, "--git", rev,
               "--port", str(a.port), "--tag", tag, "--out", a.out, "--max-usd", str(left),
               "--model", a.model or defaults.get("model", "haiku"), "--effort", a.effort or defaults.get("effort", "low"),
               "--locale", a.locale or defaults.get("locale", "zh-CN"), "--extra", defaults.get("extra", ""),
               "--limit", str(defaults.get("limit", 22)), "--minutes", str(defaults.get("minutes", 30)),
               "--max-msgs", str(a.max_msgs or defaults.get("max_msgs", 60))]
        cmd += ["--fake", a.fake] if a.fake else (["--claude", a.claude] if a.claude else [])
        print(f"== {tag} ({paper['arxiv']}, {rev}): {spent:.4f} USD spent, {left:.4f} left", flush=True)
        with open(os.path.join(a.out, tag + ".out"), "w", encoding="utf8") as log:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf8", errors="replace")
            for line in p.stdout:
                sys.stdout.write(line)
                log.write(line)
            code = p.wait()
        if os.path.isfile(os.path.join(a.out, tag, live.MARKER)):
            done.append(tag)
        print(f"== {tag}: exit {code}, cost {live.session_cost(os.path.join(a.out, tag)):.4f} USD", flush=True)
        if code in STOPS:
            why = {live.REFUSED_EXIT: "refused", live.SAFETY_EXIT: "stopped by a safety layer", live.UNVERIFIED_EXIT: "unverified"}[code]
            print(f"== STOP: {tag} was {why}; the set ends", flush=True)
            break
    total = sum(live.session_cost(os.path.join(a.out, t)) for t in done)
    print(f"== the set spent {total:.4f} of {a.max_usd:.2f} USD", flush=True)
    evals = [evaluate(os.path.join(a.out, t)) for t in done]
    if evals:
        write_baseline(evals, os.path.join(a.out, "eval"))
        print(score_table(evals))
        if a.compare:
            print()
            print(compare_table(evals, read_json(a.compare, {}).get("papers") or [], SCORE_ROWS))
        print(f"\nscores: {os.path.join(a.out, 'eval.json')} and eval.md")
    return code if code in STOPS else 0


def write_baseline(evals, name):
    with open(name + ".json", "w", encoding="utf8") as f:
        json.dump({"papers": evals, "at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=1)
    with open(name + ".md", "w", encoding="utf8") as f:
        f.write(score_table(evals) + "\n")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="a row per run: cost, tokens, turns, time, reads, the note, the closing line")
    rep.add_argument("runs", nargs="+")
    rep.add_argument("--compare", help="a baseline JSON (score --out) to compare against")
    rep.add_argument("--calls", action="store_true", help="each run's tool calls and context per API message")
    sc = sub.add_parser("score", help="the quality table of runs")
    sc.add_argument("runs", nargs="+")
    sc.add_argument("--out", help="write <out>.json (a baseline) and <out>.md")
    sc.add_argument("--compare", help="a baseline JSON to compare against")
    rn = sub.add_parser("run", help="the evaluation set through live.py")
    rn.add_argument("--config", help="a JSON file of defaults (zotero, claude, fake, papers, out, port, ...), as live.py's")
    rn.add_argument("--set", default=EVALSET, help="the evaluation set (default: evalset.json)")
    rn.add_argument("--zotero")
    rn.add_argument("--papers", help="the folder of the set's PDFs: <arxiv>.pdf or <arxiv>/paper.pdf")
    rn.add_argument("--only", help="a comma list of the set's paper names or arXiv ids")
    rn.add_argument("--git", default="HEAD", help="a commit, or a comma list of commits to compare (interleaved)")
    rn.add_argument("--repeat", type=int, default=1)
    rn.add_argument("--max-usd", type=float, default=1.0, help="the whole set's stop, from the result lines' total_cost_usd")
    rn.add_argument("--min-left", type=float, default=0.05, help="no run starts with less than this left of --max-usd")
    rn.add_argument("--max-msgs", type=int, default=None, help="each run's invisible cap (default: the set's)")
    rn.add_argument("--model", default=None)
    rn.add_argument("--effort", default=None)
    rn.add_argument("--locale", default=None)
    rn.add_argument("--port", type=int, default=23129)
    rn.add_argument("--claude", default=None)
    rn.add_argument("--fake", default=None, help="a rehearsal with the fake claude: no model is called")
    rn.add_argument("--prefix", default="eval", help="the runs' tags: <prefix>-<paper>[-<rev>][-<n>]")
    rn.add_argument("--out", default=None, help="the folder of the set's runs (default: <system temp>/scholium-live/eval-<time>)")
    rn.add_argument("--compare", help="a baseline JSON to compare the set against")
    if argv[:1] == ["run"]:
        pre = argparse.ArgumentParser(add_help=False)
        pre.add_argument("--config")
        known, _ = pre.parse_known_args(argv[1:])
        try:
            rn.set_defaults(**live.load_config(known.config))
        except (OSError, ValueError) as e:
            print(f"eval.py: {e}", file=sys.stderr)
            return live.REFUSED_EXIT
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if a.cmd == "run":
        try:
            a.port = live.smoke.check_port(a.port)
            if a.repeat < 1 or a.max_usd <= 0:
                raise ValueError("--repeat and --max-usd must be positive")
            data = load_set(a.set)
        except ValueError as e:
            rn.error(str(e))
        if not a.zotero or not a.papers:
            rn.error("--zotero and --papers are needed (or a --config that names them)")
        a.out = os.path.abspath(a.out or os.path.join(tempfile.gettempdir(), "scholium-live", "eval-" + time.strftime("%Y%m%d-%H%M%S")))
        try:
            return run_set(a, data)
        except (ValueError, RuntimeError) as e:
            print(f"eval.py: {e}", file=sys.stderr)
            return live.REFUSED_EXIT
    evals = [evaluate(r) for r in a.runs]
    base = read_json(a.compare, {}).get("papers") if a.compare else None
    if a.compare and base is None:
        print(f"eval.py: {a.compare} is not a baseline (score --out writes one)", file=sys.stderr)
        return 2
    if a.cmd == "report":
        print(report_table(evals))
        if base is not None:
            print()
            print(compare_table(evals, base, REPORT_ROWS[:-1]))
        if a.calls:
            for r, e in zip(a.runs, evals):
                rf = run_files(os.path.abspath(r))
                print(f"\n== {e['run']}\n" + calls_report(events_of(rf["logs"])))
        return 0
    print(score_table(evals))
    if base is not None:
        print()
        print(compare_table(evals, base, SCORE_ROWS))
    if a.out:
        write_baseline(evals, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
