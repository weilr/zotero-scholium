"""Install the released skill into local skill directories.

    python scripts/sync_local_skills.py [--ref TAG] [--ack] [--force] DIR [DIR ...]

Files are read from a release tag (default: the latest v* tag), never from the working tree.
Each DIR must exist. Every file under skills/zotero-scholium/ in that tag is written to it.
Files that exist only in DIR are left alone; files written by an earlier sync that the release
no longer contains are removed if they are unchanged. A file edited in DIR since the last sync
is kept and reported (--force overwrites it).

A DIR whose SKILL.md is not a released SKILL.md keeps its own SKILL.md; a DIR without one
receives the released SKILL.md. DIR/.scholium-sync.json records the release an own SKILL.md
was last aligned with; when the released SKILL.md has changed since, the script names the diff
to review and exits 1. After updating the SKILL.md, run again with --ack to record the new
alignment.

Exit status: 0 in sync, 1 something to review, 2 error.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SKILL = "skills/zotero-scholium"
MARKER = ".scholium-sync.json"


class SyncError(Exception):
    pass


def sha(data):
    """Content hash that ignores CRLF versus LF line endings."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


class Release:
    def __init__(self, repo, ref):
        self.repo = Path(repo)
        self.ref = ref or self.latest_tag()
        self.commit = self.git("rev-list", "-n", "1", self.ref).decode().strip()
        names = self.git("ls-tree", "-r", "--name-only", self.ref, "--", SKILL).decode().splitlines()
        if not names:
            raise SyncError(f"{self.ref} contains no {SKILL}/")
        self.files = {n[len(SKILL) + 1:]: self.git("show", f"{self.ref}:{n}") for n in names}
        self._released = {}

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True).stdout

    def latest_tag(self):
        tags = self.git("tag", "--list", "v*", "--sort=-v:refname").decode().split()
        if not tags:
            raise SyncError(f"no v* tag in {self.repo}")
        return tags[0]

    def show(self, ref, rel):
        try:
            return self.git("show", f"{ref}:{SKILL}/{rel}")
        except subprocess.CalledProcessError:
            return None

    def released_hashes(self, rel):
        """Hashes of every released version of one file."""
        if rel not in self._released:
            tags = self.git("tag", "--list", "v*").decode().split()
            self._released[rel] = {sha(d) for d in (self.show(t, rel) for t in tags) if d is not None}
        return self._released[rel]


def sync(release, target, ack=False, force=False):
    target = Path(target).expanduser()
    if not target.is_dir():
        raise SyncError(f"{target}: not a directory (create it first to install there)")
    marker_path = target / MARKER
    try:
        marker = json.loads(marker_path.read_text(encoding="utf8")) if marker_path.exists() else {}
        if not isinstance(marker, dict):
            raise ValueError("not a JSON object")
    except ValueError as e:
        raise SyncError(f"{marker_path}: unreadable ({e}); delete it to start over")
    recorded = marker.get("files") or {}
    skill_md = target / "SKILL.md"
    if not skill_md.exists():
        mode = "mirror"
    elif marker.get("skill_md") in ("own", "mirror"):
        mode = marker["skill_md"]
    elif sha(skill_md.read_bytes()) not in release.released_hashes("SKILL.md"):
        mode = "own"
    else:
        mode = "mirror"

    written, unchanged, removed, kept = 0, 0, 0, []
    files = {}
    for rel, data in sorted(release.files.items()):
        if mode == "own" and rel == "SKILL.md":
            continue
        dest = target / rel
        if dest.exists():
            current = dest.read_bytes()
            if sha(current) == sha(data):
                unchanged += 1
                files[rel] = sha(data)
                continue
            known = recorded.get(rel) == sha(current) or sha(current) in release.released_hashes(rel)
            if not known and not force:
                kept.append(rel)
                if rel in recorded:
                    files[rel] = recorded[rel]
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1
        files[rel] = sha(data)
    for rel, digest in recorded.items():
        dest = target / rel
        if rel not in release.files and dest.exists() and sha(dest.read_bytes()) == digest:
            dest.unlink()
            removed += 1

    ok = not kept
    notes = [f"edited locally, kept: {', '.join(kept)} (--force overwrites)"] if kept else []
    aligned = marker.get("skill_md_ref")
    if mode == "own":
        if ack:
            aligned = release.ref
        if aligned is None:
            ok = False
            notes.append(f"own SKILL.md with no recorded release; compare it with "
                         f"`git show {release.ref}:{SKILL}/SKILL.md`, then run again with --ack")
        elif sha(release.show(aligned, "SKILL.md") or b"") != sha(release.files["SKILL.md"]):
            ok = False
            notes.append(f"own SKILL.md follows {aligned}; the released SKILL.md has changed: "
                         f"`git diff {aligned} {release.ref} -- {SKILL}/SKILL.md`; update it, then run again with --ack")
        else:
            notes.append(f"own SKILL.md, aligned with {aligned}")

    new_marker = {"ref": release.ref, "commit": release.commit, "skill_md": mode, "files": files}
    if mode == "own" and aligned:
        new_marker["skill_md_ref"] = aligned
    marker_path.write_text(json.dumps(new_marker, indent=2) + "\n", encoding="utf8")
    print(f"{target}: {release.ref}, {written} written, {unchanged} unchanged, {removed} removed"
          + "".join(f"; {n}" for n in notes))
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dirs", nargs="+", metavar="DIR", help="installed skill directory")
    ap.add_argument("--ref", help="release tag to install (default: the latest v* tag)")
    ap.add_argument("--ack", action="store_true", help="record that an own SKILL.md now follows this release")
    ap.add_argument("--force", action="store_true", help="overwrite files edited locally since the last sync")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        release = Release(args.repo, args.ref)
    except FileNotFoundError:
        print("error: git is not installed or not on PATH", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(f"error: git {' '.join(e.cmd[3:])}: {e.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        return 2
    except SyncError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    results = []
    for d in args.dirs:
        try:
            results.append(sync(release, d, ack=args.ack, force=args.force))
        except SyncError as e:
            print(f"error: {e}", file=sys.stderr)
            results.append(None)
    if None in results:
        return 2
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
