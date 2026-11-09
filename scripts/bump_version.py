"""The release's version bump: the version into every file scripts/check_versions.py compares (and, through
scripts/sync_skill_script.py, into the skill's copy of cli.py), and CHANGELOG.md's "## Unreleased" section named after it
with the date; then check_versions.py with the version as the tag.

    python scripts/bump_version.py X.Y.Z [--date YYYY-MM-DD]

It refuses a version that is not above the current one, a CHANGELOG.md without an "## Unreleased" section, and
uncommitted changes in these files; it then writes nothing. --root names another copy of the repository (the tests')."""
import argparse
import datetime
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
# each file, the pattern of its version (the version is the second group) and how often it holds it
VERSIONS = [("pyproject.toml", r'^(version = ")([^"]+)(")', 1),
            ("src/zotero_scholium/cli.py", r'^(__version__ = ")([^"]+)(")', 1),
            (".claude-plugin/plugin.json", r'("version":\s*")([^"]+)(")', 1),
            (".claude-plugin/marketplace.json", r'("version":\s*")([^"]+)(")', 2),
            ("plugin/scholium/manifest.json", r'("version":\s*")([^"]+)(")', 1)]
CHANGELOG = "CHANGELOG.md"
SKILL_COPY = "skills/zotero-scholium/scripts/scholium.py"
UNRELEASED = re.compile(r"^## Unreleased[ \t]*$", re.M)


def fail(message):
    sys.exit("bump_version: " + message)


def read(root, name):
    with open(root / name, encoding="utf8", newline="") as f:
        return f.read()


def write(root, name, text):
    with open(root / name, "w", encoding="utf8", newline="") as f:
        f.write(text)


def parse(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"{version!r} is not a version X.Y.Z")
    return tuple(int(n) for n in version.split("."))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bump the release's version and name the CHANGELOG's Unreleased section.")
    ap.add_argument("version", help="the new version, X.Y.Z")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="the release's date, YYYY-MM-DD (default: today)")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)
    new = parse(args.version)
    try:
        datetime.date.fromisoformat(args.date)
    except ValueError:
        fail(f"{args.date!r} is not a date YYYY-MM-DD")

    names = [name for name, _, _ in VERSIONS] + [SKILL_COPY, CHANGELOG]
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", *names], capture_output=True, text=True)
    if status.returncode != 0:
        fail("git status failed: " + status.stderr.strip())
    if status.stdout.strip():
        fail("uncommitted changes in: " + ", ".join(line[3:] for line in status.stdout.splitlines()))

    texts, current = {}, set()
    for name, pattern, count in VERSIONS:
        texts[name] = read(root, name)
        found = [m.group(2) for m in re.finditer(pattern, texts[name], re.M)]
        if len(found) != count:
            fail(f"{name}: {len(found)} version fields where {count} were expected")
        current.update(found)
    if len(current) != 1:
        fail("the files carry different versions (" + ", ".join(sorted(current)) + "); run scripts/check_versions.py")
    old = current.pop()
    if new <= parse(old):
        fail(f"{args.version} is not above the current version {old}")
    changelog = read(root, CHANGELOG)
    if len(UNRELEASED.findall(changelog)) != 1:
        fail(f'{CHANGELOG} has no "## Unreleased" section (or more than one)')

    for name, pattern, _ in VERSIONS:
        write(root, name, re.sub(pattern, lambda m: m.group(1) + args.version + m.group(3), texts[name], flags=re.M))
    write(root, CHANGELOG, UNRELEASED.sub(f"## {args.version} ({args.date})", changelog, count=1))
    subprocess.run([sys.executable, str(root / "scripts" / "sync_skill_script.py")], check=True)
    return subprocess.run([sys.executable, str(root / "scripts" / "check_versions.py"), "v" + args.version]).returncode


if __name__ == "__main__":
    sys.exit(main())
