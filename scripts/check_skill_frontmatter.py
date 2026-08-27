"""CI guard: the front matter of every bundled SKILL.md must parse with a strict YAML parser.

Installers such as the skills CLI reject a skill whose front matter is not valid YAML, silently
reporting "no skills found". An unquoted description containing ": " is the typical cause.
"""
import pathlib
import sys

import yaml

root = pathlib.Path(__file__).resolve().parents[1]
paths = sorted(root.glob("skills/*/SKILL.md"))
if not paths:
    sys.exit("no skills/*/SKILL.md found")
for p in paths:
    text = p.read_text(encoding="utf8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        sys.exit(f"{p}: front matter block missing")
    meta = yaml.safe_load(text[4:text.index("\n---\n", 4)])
    for key in ("name", "description"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            sys.exit(f"{p}: front matter field {key!r} missing or empty")
    if meta["name"] != p.parent.name:
        sys.exit(f"{p}: front matter name {meta['name']!r} differs from directory name {p.parent.name!r}")
    print(f"{p.relative_to(root)}: front matter ok ({meta['name']})")
