"""Token size of what an agent loads for one paper: the skill files, optionally a profile and a paper's extraction.

    python scripts/measure_context.py [--skill DIR] [--profile FILE] [--pdf FILE] [--json] [--max-skill-tokens N]

Counts with tiktoken (o200k_base) when it is installed, otherwise with a heuristic (one token per four
Latin characters, 1.3 tokens per CJK character). --max-skill-tokens N exits 1 when the SKILL.md body
exceeds N tokens.
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def tokenizer():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return "tiktoken", lambda s: len(enc.encode(s))
    except Exception:
        return "heuristic", lambda s: int(len(CJK.findall(s)) * 1.3 + (len(s) - len(CJK.findall(s))) / 4)


def measure(text, count):
    return {"chars": len(text), "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0), "tokens": count(text)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", default=os.path.join(ROOT, "skills", "zotero-scholium"), help="skill directory (default: the repository's)")
    ap.add_argument("--profile", help="profile.md to include")
    ap.add_argument("--pdf", help="a PDF: measure `extract` output in both plain and numbered form")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--max-skill-tokens", type=int, help="exit 1 when the SKILL.md body exceeds this many tokens")
    args = ap.parse_args(argv)
    name, count = tokenizer()
    result = {"tokenizer": name, "skill": {}}

    skill_md = open(os.path.join(args.skill, "SKILL.md"), encoding="utf8").read()
    m = re.match(r"---\n.*?\n---\n", skill_md, flags=re.S)
    front, body = (m.group(0), skill_md[m.end():]) if m else ("", skill_md)
    result["skill"]["SKILL.md frontmatter"] = measure(front, count)
    result["skill"]["SKILL.md"] = measure(body, count)
    for sub in ("references", "examples", "agents"):
        d = os.path.join(args.skill, sub)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                p = os.path.join(d, fn)
                if os.path.isfile(p):
                    try:
                        result["skill"][f"{sub}/{fn}"] = measure(open(p, encoding="utf8").read(), count)
                    except UnicodeDecodeError:
                        pass
    if args.profile:
        result["profile"] = measure(open(args.profile, encoding="utf8").read(), count)
    if args.pdf:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from zotero_scholium import cli
        result["extract"] = {"text": measure(cli.extract_text(args.pdf), count),
                             "sentences": measure(cli.render_sentences(cli.extract_sentences(args.pdf)), count)}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"tokenizer: {name}")
        rows = [(k, v) for k, v in result["skill"].items()]
        if "profile" in result:
            rows.append(("profile.md", result["profile"]))
        if "extract" in result:
            rows += [("extract (plain text)", result["extract"]["text"]), ("extract (numbered sentences)", result["extract"]["sentences"])]
        for k, v in rows:
            print(f"{k:34s} {v['chars']:>8,} chars {v['lines']:>6,} lines {v['tokens']:>8,} tokens")
        skill_total = sum(v["tokens"] for v in result["skill"].values())
        print(f"{'skill files total':34s} {'':>14} {'':>13} {skill_total:>8,} tokens")
    if args.max_skill_tokens is not None and result["skill"]["SKILL.md"]["tokens"] > args.max_skill_tokens:
        print(f"SKILL.md body: {result['skill']['SKILL.md']['tokens']} tokens > {args.max_skill_tokens}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
