"""scripts/build_xpi.py and scripts/check_xpi.py: the package carries the plugin and the skill it installs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = {"manifest.json", "bootstrap.js", "prefs.js", "settings.xhtml", "settings.js", "content", "locale", "modules"}


def run(script, *args):
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                       capture_output=True, encoding="utf8")
    return p.returncode, p.stdout + p.stderr


def entries(xpi):
    with zipfile.ZipFile(xpi) as z:
        return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}


def rewrite(xpi, dest, drop=(), put=None):
    """A copy of a package without the entries in `drop` and with those in `put` added or replaced."""
    files = {n: b for n, b in entries(xpi).items() if n not in drop}
    files.update(put or {})
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return dest


def copy_repo(tmp_path):
    repo = tmp_path / "repo"
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "skill")
    shutil.copytree(ROOT / "plugin/scholium", repo / "plugin/scholium", ignore=skip)
    shutil.copytree(ROOT / "skills/zotero-scholium", repo / "skills/zotero-scholium", ignore=skip)
    return repo


def test_package_of_the_working_tree(tmp_path):
    left = ROOT / "plugin/scholium/content/skill"
    before = left.exists()
    xpi = tmp_path / "out/scholium.xpi"
    code, out = run("build_xpi.py", xpi)
    assert code == 0, out
    assert left.exists() == before, "the build must not write content/skill into the working tree"
    assert not list(xpi.parent.glob("*.part"))
    code, out = run("check_xpi.py", xpi)
    assert code == 0, out
    version = json.loads((ROOT / "plugin/scholium/manifest.json").read_text(encoding="utf8"))["version"]
    assert f"Scholium {version}" in out and "identical to skills/zotero-scholium" in out
    files = entries(xpi)
    assert {n.split("/")[0] for n in files} == TOP == set(os.listdir(ROOT / "plugin/scholium"))
    assert files["content/skill/zotero-scholium/SKILL.md"] == (ROOT / "skills/zotero-scholium/SKILL.md").read_bytes()
    assert files["bootstrap.js"] == (ROOT / "plugin/scholium/bootstrap.js").read_bytes()
    modules = sorted((ROOT / "plugin/scholium/modules").iterdir())
    assert modules and f"modules: {len(modules)};" in out
    for module in modules:
        assert files["modules/" + module.name] == module.read_bytes(), module.name


def test_build_leaves_out_compiled_python_and_an_old_content_skill(tmp_path):
    repo = copy_repo(tmp_path)
    cache = repo / "skills/zotero-scholium/scripts/__pycache__"
    cache.mkdir()
    (cache / "scholium.cpython-312.pyc").write_bytes(b"\0")
    old = repo / "plugin/scholium/content/skill/zotero-scholium/SKILL.md"
    old.parent.mkdir(parents=True)
    old.write_text("an old build\n", encoding="utf8")
    xpi = tmp_path / "scholium.xpi"
    code, out = run("build_xpi.py", "--repo", repo, xpi)
    assert code == 0, out
    files = entries(xpi)
    assert not [n for n in files if "__pycache__" in n or n.endswith(".pyc")]
    assert files["content/skill/zotero-scholium/SKILL.md"] == (repo / "skills/zotero-scholium/SKILL.md").read_bytes()
    assert old.read_text(encoding="utf8") == "an old build\n"
    code, out = run("check_xpi.py", "--repo", repo, xpi)
    assert code == 0, out


def test_check_names_what_is_missing_or_changed(tmp_path):
    repo = copy_repo(tmp_path)
    xpi = tmp_path / "scholium.xpi"
    assert run("build_xpi.py", "--repo", repo, xpi)[0] == 0
    at = "content/skill/zotero-scholium/"
    bad = rewrite(xpi, tmp_path / "bad.xpi",
                  drop={at + "scripts/scholium.py", "content/scholium.css", "locale/zh-CN/scholium.ftl", "modules/agents.js"},
                  put={at + "SKILL.md": b"changed\n", at + "scripts/__pycache__/scholium.cpython-312.pyc": b"\0",
                       "modules/extra.js": b"\n"})
    code, out = run("check_xpi.py", "--repo", repo, bad)
    assert code == 1, out
    for expected in ["missing content/skill/zotero-scholium/scripts/scholium.py", "missing content/scholium.css",
                     "missing locale/zh-CN/scholium.ftl", "missing modules/agents.js",
                     "modules/extra.js is not in MODULES, so the plugin does not load it",
                     "content/skill/zotero-scholium/SKILL.md differs from skills/zotero-scholium/SKILL.md",
                     "scripts/__pycache__/scholium.cpython-312.pyc: compiled Python"]:
        assert expected in out, out

    (repo / "skills/zotero-scholium/references/new.md").write_text("new\n", encoding="utf8")
    (repo / "plugin/scholium/new.js").write_text("\n", encoding="utf8")
    code, out = run("check_xpi.py", "--repo", repo, xpi)
    assert code == 1 and "references/new.md is not in SKILL_FILES" in out, out
    assert "missing new.js of plugin/scholium" in out, out

    code, out = run("check_xpi.py", "--repo", repo, tmp_path / "none.xpi")
    assert code == 2 and out.startswith("error:"), out
