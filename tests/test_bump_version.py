"""The release's version bump (scripts/bump_version.py), run on a copy of the files in a Git repository of its own, never on
the real tree: the version goes into every file check_versions.py compares and into the skill's copy of cli.py, and the
CHANGELOG's Unreleased section is named after it; a version not above the current one, a CHANGELOG without an Unreleased
section and uncommitted changes in those files are refused."""
import datetime
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = ["pyproject.toml", "src/zotero_scholium/cli.py", "skills/zotero-scholium/scripts/scholium.py", ".claude-plugin/plugin.json",
         ".claude-plugin/marketplace.json", "plugin/scholium/manifest.json", "CHANGELOG.md", "scripts/check_versions.py",
         "scripts/sync_skill_script.py"]
GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git is required")


def put(path, text):
    path.write_bytes(text.encode("utf8"))   # LF, on every Python


def git(root, *args):
    return subprocess.run([GIT, "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          capture_output=True, text=True, check=True)


@pytest.fixture
def copy(tmp_path):
    root = tmp_path / "repo"
    for f in FILES:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / f, root / f)
    changelog = root / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf8")
    if "## Unreleased" not in text:   # the real CHANGELOG between a release and its next change
        put(changelog, text.replace("# Changelog\n", "# Changelog\n\n## Unreleased\n\n- A change.\n", 1))
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "copy")
    return root


def current(root):
    return re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf8"), re.M).group(1)


def bump(root, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "bump_version.py"), *args, "--root", str(root)],
                          capture_output=True, text=True, timeout=60)


def above(version):
    major, minor, patch = map(int, version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def test_the_version_goes_everywhere_and_the_changelog_names_it(copy):
    before = {f: (copy / f).read_text(encoding="utf8") for f in FILES}
    old, new = current(copy), above(current(copy))
    r = bump(copy, new, "--date", "2026-12-01")
    assert r.returncode == 0, r.stderr
    assert f"version {new} everywhere" in r.stdout
    for f in ("pyproject.toml", "src/zotero_scholium/cli.py", ".claude-plugin/plugin.json", "plugin/scholium/manifest.json"):
        text = (copy / f).read_text(encoding="utf8")
        assert new in text and text.replace(new, old) == before[f], f   # only the version changed
    market = (copy / ".claude-plugin/marketplace.json").read_text(encoding="utf8")
    assert market.count(f'"version": "{new}"') == 2 and market.replace(new, old) == before[".claude-plugin/marketplace.json"]
    assert (copy / "skills/zotero-scholium/scripts/scholium.py").read_bytes() == (copy / "src/zotero_scholium/cli.py").read_bytes()
    changelog = (copy / "CHANGELOG.md").read_text(encoding="utf8")
    assert "## Unreleased" not in changelog and f"\n## {new} (2026-12-01)\n" in changelog
    assert changelog.index(f"## {new} (2026-12-01)") < changelog.index(f"## {old} (")


def test_the_date_is_today_unless_given(copy):
    new = above(current(copy))
    assert bump(copy, new).returncode == 0
    assert f"## {new} ({datetime.date.today().isoformat()})" in (copy / "CHANGELOG.md").read_text(encoding="utf8")


@pytest.mark.parametrize("which", ["same", "lower", "malformed"])
def test_a_version_not_above_the_current_one_is_refused(copy, which):
    old = current(copy)
    major, minor, patch = map(int, old.split("."))
    version = {"same": old, "lower": f"{major}.{minor}.{max(patch - 1, 0)}" if patch else f"{major}.{max(minor - 1, 0)}.9",
               "malformed": "0.3"}[which]
    r = bump(copy, version)
    assert r.returncode != 0 and r.stderr.strip()
    assert current(copy) == old and "## Unreleased" in (copy / "CHANGELOG.md").read_text(encoding="utf8"), "nothing written"


def test_a_changelog_without_an_unreleased_section_is_refused(copy):
    changelog = copy / "CHANGELOG.md"
    put(changelog, changelog.read_text(encoding="utf8").replace("## Unreleased", "## Next"))
    git(copy, "commit", "-q", "-am", "no unreleased section")
    old = current(copy)
    r = bump(copy, above(old))
    assert r.returncode != 0 and "Unreleased" in r.stderr and current(copy) == old


def test_uncommitted_changes_in_those_files_are_refused(copy):
    manifest = copy / "plugin/scholium/manifest.json"
    put(manifest, manifest.read_text(encoding="utf8") + "\n")
    old = current(copy)
    r = bump(copy, above(old))
    assert r.returncode != 0 and "plugin/scholium/manifest.json" in r.stderr and current(copy) == old
