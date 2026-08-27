"""Copy src/zotero_scholium/cli.py into the Claude Code skill, which is kept self-contained by design."""
import pathlib, shutil

root = pathlib.Path(__file__).resolve().parents[1]
src = root / "src" / "zotero_scholium" / "cli.py"
dst = root / "skills" / "zotero-scholium" / "scripts" / "scholium.py"
shutil.copyfile(src, dst)
print("copied", src.relative_to(root), "->", dst.relative_to(root))
