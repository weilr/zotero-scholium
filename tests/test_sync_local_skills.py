"""scripts/sync_local_skills.py against a throwaway repository with three releases."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sync_local_skills.py"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
                    "-C", str(repo), *args], check=True, capture_output=True)


def write(root, files):
    for rel, text in files.items():
        p = root / "skills/zotero-scholium" / rel
        if text is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf8")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    releases = [
        ("v0.0.1", {"SKILL.md": "english 1\n", "scripts/scholium.py": "print(1)\n", "references/a.md": "a\n"}),
        ("v0.0.2", {"SKILL.md": "english 2\n", "scripts/scholium.py": "print(2)\n", "references/a.md": None,
                    "references/b.md": "b\n"}),
        ("v0.0.3", {"scripts/scholium.py": "print(3)\n"}),
    ]
    for tag, files in releases:
        write(root, files)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", tag)
        git(root, "tag", tag)
    write(root, {"scripts/scholium.py": "print('work in progress')\n"})
    return root


def run(repo, *args):
    p = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *map(str, args)],
                       capture_output=True, encoding="utf8")
    return p.returncode, p.stdout + p.stderr


def read(d, rel):
    return (d / rel).read_text(encoding="utf8")


def test_mirror_follows_releases_and_never_the_working_tree(repo, tmp_path):
    d = tmp_path / "codex/zotero-scholium"
    d.mkdir(parents=True)
    assert run(repo, "--ref", "v0.0.1", d)[0] == 0
    (d / "examples").mkdir()
    (d / "examples/mine.json").write_text("{}", encoding="utf8")
    code, out = run(repo, "--ref", "v0.0.2", d)
    assert code == 0, out
    assert read(d, "SKILL.md") == "english 2\n"
    assert read(d, "scripts/scholium.py") == "print(2)\n"
    assert not (d / "references/a.md").exists() and read(d, "references/b.md") == "b\n"
    assert read(d, "examples/mine.json") == "{}"
    code, out = run(repo, d)
    assert code == 0, out
    assert read(d, "scripts/scholium.py") == "print(3)\n"
    assert json.loads(read(d, ".scholium-sync.json"))["skill_md"] == "mirror"


def test_own_skill_md_is_kept_and_flagged_until_acknowledged(repo, tmp_path):
    d = tmp_path / "claude/zotero-scholium"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("中文版\n", encoding="utf8")
    code, out = run(repo, "--ref", "v0.0.1", d)
    assert code == 1 and "--ack" in out
    assert read(d, "SKILL.md") == "中文版\n" and read(d, "scripts/scholium.py") == "print(1)\n"
    assert run(repo, "--ref", "v0.0.1", "--ack", d)[0] == 0
    assert run(repo, "--ref", "v0.0.1", d)[0] == 0

    code, out = run(repo, "--ref", "v0.0.2", d)
    assert code == 1 and "git diff v0.0.1 v0.0.2 -- skills/zotero-scholium/SKILL.md" in out
    assert read(d, "SKILL.md") == "中文版\n" and read(d, "scripts/scholium.py") == "print(2)\n"
    assert run(repo, "--ref", "v0.0.2", d)[0] == 1
    assert run(repo, "--ref", "v0.0.2", "--ack", d)[0] == 0

    code, out = run(repo, d)
    assert code == 0 and "aligned with v0.0.2" in out
    assert read(d, "scripts/scholium.py") == "print(3)\n" and read(d, "SKILL.md") == "中文版\n"


def test_local_edits_are_kept_unless_forced(repo, tmp_path):
    d = tmp_path / "mirror"
    d.mkdir()
    assert run(repo, "--ref", "v0.0.1", d)[0] == 0
    (d / "scripts/scholium.py").write_text("print('patched by hand')\n", encoding="utf8")
    code, out = run(repo, "--ref", "v0.0.2", d)
    assert code == 1 and "edited locally, kept: scripts/scholium.py" in out
    assert read(d, "scripts/scholium.py") == "print('patched by hand')\n"
    assert read(d, "SKILL.md") == "english 2\n"
    assert run(repo, "--ref", "v0.0.2", d)[0] == 1
    assert run(repo, "--ref", "v0.0.2", "--force", d)[0] == 0
    assert read(d, "scripts/scholium.py") == "print(2)\n"


def test_first_sync_replaces_files_matching_an_older_release(repo, tmp_path):
    d = tmp_path / "old-install"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts/scholium.py").write_text("print(1)\n", encoding="utf8")
    (d / "SKILL.md").write_text("english 1\n", encoding="utf8")
    code, out = run(repo, d)
    assert code == 0, out
    assert read(d, "scripts/scholium.py") == "print(3)\n" and read(d, "SKILL.md") == "english 2\n"


def test_errors_exit_2_without_writing(repo, tmp_path):
    missing = tmp_path / "typo/zotero-scholium"
    code, out = run(repo, missing)
    assert code == 2 and "not a directory" in out and not missing.exists()
    d = tmp_path / "install"
    d.mkdir()
    code, out = run(repo, "--ref", "v9.9.9", d)
    assert code == 2 and out.startswith("error: git") and not any(d.iterdir())
    code, out = run(tmp_path, d)
    assert code == 2 and out.startswith("error: git")
    (d / ".scholium-sync.json").write_text("{not json", encoding="utf8")
    code, out = run(repo, d)
    assert code == 2 and "unreadable" in out and not (d / "SKILL.md").exists()


def test_own_mode_without_skill_md_receives_the_released_one(repo, tmp_path):
    d = tmp_path / "own"
    d.mkdir()
    (d / "SKILL.md").write_text("中文版\n", encoding="utf8")
    assert run(repo, "--ack", d)[0] == 0
    (d / "SKILL.md").unlink()
    code, out = run(repo, d)
    assert code == 0, out
    assert read(d, "SKILL.md") == "english 2\n"
    assert json.loads(read(d, ".scholium-sync.json"))["skill_md"] == "mirror"
