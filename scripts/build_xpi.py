"""Build the Zotero plugin package.

    python scripts/build_xpi.py OUT.xpi

The archive holds manifest.json, bootstrap.js, prefs.js, settings.xhtml, settings.js and the content/ and locale/
folders of plugin/scholium, and skills/zotero-scholium at content/skill/zotero-scholium/, which the plugin installs
when an agent has none. __pycache__ folders and .pyc files are left out. The files are read where they are; nothing is
written into the working tree. scripts/check_xpi.py checks the result.
"""

import argparse
from pathlib import Path
import sys
import zipfile

TOP = ["manifest.json", "bootstrap.js", "prefs.js", "settings.xhtml", "settings.js"]
FOLDERS = ["content", "locale"]
SKILL_AT = "content/skill"


def walk(src, at, skip=()):
    """(name in the archive, source path) for a folder and everything under it, folders before their files."""
    out = [(at + "/", src)]
    for p in sorted(src.iterdir(), key=lambda p: p.name):
        name = f"{at}/{p.name}"
        if p.name == "__pycache__" or p.suffix == ".pyc" or name in skip:
            continue
        out += walk(p, name, skip) if p.is_dir() else [(name, p)]
    return out


def entries(repo):
    plugin, skill = repo / "plugin" / "scholium", repo / "skills" / "zotero-scholium"
    missing = [str(p) for p in [*(plugin / n for n in TOP), *(plugin / f for f in FOLDERS), skill / "SKILL.md"]
               if not p.exists()]
    if missing:
        raise FileNotFoundError("missing: " + ", ".join(missing))
    out = [(n, plugin / n) for n in TOP]
    for folder in FOLDERS:
        # a content/skill/ left by an earlier build by hand is replaced by the skill of the working tree
        out += walk(plugin / folder, folder, skip={SKILL_AT})
    out.append((SKILL_AT + "/", skill.parent))
    out += walk(skill, SKILL_AT + "/zotero-scholium")
    return out


def build(repo, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    files = 0
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for name, src in entries(repo):
                z.write(src, name)
                files += not name.endswith("/")
        part.replace(dest)
    finally:
        if part.exists():
            part.unlink()
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", metavar="OUT.xpi", help="path of the package to write")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        files = build(Path(args.repo), args.out)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"{args.out}: {files} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
