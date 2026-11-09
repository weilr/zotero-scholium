"""Check a built plugin package (scripts/build_xpi.py).

    python scripts/check_xpi.py scholium.xpi

The package must hold manifest.json, bootstrap.js, prefs.js, settings.xhtml, settings.js, content/scholium.css, the
icons, every locale's scholium.ftl, every other top-level entry of plugin/scholium, and no __pycache__; every module
that MODULES in its bootstrap.js lists must be in modules/, which holds no other file; every file that SKILL_FILES in
bootstrap.js and its modules lists must be under content/skill/zotero-scholium/ and identical to
skills/zotero-scholium/, and every file of skills/zotero-scholium/ must be listed there. Prints the manifest's version.

Exit status: 0 the package is complete, 1 problems (listed), 2 error.
"""

import argparse
import json
from pathlib import Path
import re
import sys
import zipfile

REQUIRED = ["manifest.json", "bootstrap.js", "prefs.js", "settings.xhtml", "settings.js", "content/scholium.css"]
SKILL_AT = "content/skill/zotero-scholium/"


def skill_files(skill):
    """Files of the skill in the working tree, as paths relative to it."""
    return {p.relative_to(skill).as_posix() for p in skill.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def modules(files):
    """The modules bootstrap.js loads from modules/, in its order (its MODULES)."""
    m = re.search(rb"var MODULES = \[(.*?)\];", files.get("bootstrap.js", b""), re.S)
    return [s.decode() for s in re.findall(rb'"([^"]+)"', m.group(1))] if m else []


def problems(files, repo):
    """What is missing or wrong in a package, given as {name: bytes}."""
    out = [f"missing {n}" for n in REQUIRED if n not in files]
    tops = {n.split("/")[0] for n in files}
    out += [f"missing {p.name}{'/' if p.is_dir() else ''} of plugin/scholium"
            for p in sorted((repo / "plugin/scholium").iterdir()) if p.name not in tops and p.name not in REQUIRED]
    if not any(re.fullmatch(r"content/[^/]+\.svg", n) for n in files):
        out.append("missing content/*.svg")
    locales = sorted(n for n in files if re.fullmatch(r"locale/[^/]+/scholium\.ftl", n))
    if not locales:
        out.append("missing locale/*/scholium.ftl")
    for d in sorted(p.name for p in (repo / "plugin/scholium/locale").glob("*") if p.is_dir()):
        if f"locale/{d}/scholium.ftl" not in files:
            out.append(f"missing locale/{d}/scholium.ftl")
    out += [f"{n}: compiled Python" for n in sorted(files) if "__pycache__" in n.split("/") or n.endswith(".pyc")]
    try:
        manifest = json.loads(files.get("manifest.json", b"{}"))
        icons = manifest.get("icons") or {}
        out += [f"manifest icon {p} is missing" for p in sorted(set(icons.values())) if p not in files]
    except ValueError as e:
        out.append(f"manifest.json: not JSON ({e})")

    loaded = modules(files)
    if "bootstrap.js" in files and not loaded:
        out.append("bootstrap.js: no MODULES list")
    out += [f"missing modules/{n}" for n in loaded if "modules/" + n not in files]
    out += [f"{n} is not in MODULES, so the plugin does not load it" for n in sorted(files)
            if n.startswith("modules/") and n[len("modules/"):] not in loaded]

    code = b"\n".join(files.get(n, b"") for n in ["bootstrap.js"] + ["modules/" + n for n in loaded])
    m = re.search(rb"SKILL_FILES:\s*\[(.*?)\]", code, re.S)
    listed = [s.decode() for s in re.findall(rb'"([^"]+)"', m.group(1))] if m else []
    if "bootstrap.js" in files and not listed:
        out.append("bootstrap.js and its modules: no SKILL_FILES list")
    skill = repo / "skills" / "zotero-scholium"
    for rel in listed:
        name, src = SKILL_AT + rel, skill / rel
        if name not in files:
            out.append(f"missing {name}")
        elif not src.is_file():
            out.append(f"SKILL_FILES lists {rel}, which skills/zotero-scholium/ does not have")
        elif files[name] != src.read_bytes():
            out.append(f"{name} differs from skills/zotero-scholium/{rel}")
    if listed:
        out += [f"skills/zotero-scholium/{rel} is not in SKILL_FILES, so the plugin does not install it"
                for rel in sorted(skill_files(skill) - set(listed))]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("xpi", help="the package to check")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    try:
        with zipfile.ZipFile(args.xpi) as z:
            files = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    except (OSError, zipfile.BadZipFile) as e:
        print(f"error: {args.xpi}: {e}", file=sys.stderr)
        return 2
    found = problems(files, repo)
    if found:
        print(f"{args.xpi}:\n" + "\n".join(f"  {p}" for p in found))
        return 1
    manifest = json.loads(files["manifest.json"])
    skill = sum(1 for n in files if n.startswith(SKILL_AT))
    locales = ", ".join(sorted(n.split("/")[1] for n in files if re.fullmatch(r"locale/[^/]+/scholium\.ftl", n)))
    loaded = len(modules(files))
    print(f"{args.xpi}: {manifest.get('name')} {manifest.get('version')}, {len(files)} files; modules: {loaded}; "
          f"skill: {skill} files, identical to skills/zotero-scholium; locales: {locales}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
