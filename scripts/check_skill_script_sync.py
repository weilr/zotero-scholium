"""CI guard: the copy of the CLI bundled inside the Claude Code skill must be identical to the package source."""
import pathlib, sys

root = pathlib.Path(__file__).resolve().parents[1]
a = (root / "src" / "zotero_scholium" / "cli.py").read_text(encoding="utf8")
b = (root / "skills" / "zotero-scholium" / "scripts" / "scholium.py").read_text(encoding="utf8")
if a != b:
    print("skills/zotero-scholium/scripts/scholium.py is out of sync with src/zotero_scholium/cli.py\n"
          "run: python scripts/sync_skill_script.py")
    sys.exit(1)
print("skill script in sync")
