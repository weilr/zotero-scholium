"""A cleanup re-apply updates only what changed. Each new annotation that holds one of the tool's annotations again (the
same type and page, the same text or comment or the same place) is that annotation: kept untouched when nothing differs,
else updated in its changed fields; only the others are created, and only the tool's annotations no longer in the set
are deleted. The reading note with note_replace is updated in place when this output folder wrote it and the user did
not change it since. Every run here uses the in-memory local API; nothing reaches a socket."""
import copy
import json

import pymupdf
import pytest

from zotero_scholium import cli
from test_run_safeguards import Api, ann_row, note_row

S1 = "The method improves the result on every benchmark."
S2 = "Another sentence written in an earlier session."
S3 = "A third sentence that a later run adds to the set."


class UpdatingApi(Api):
    """The in-memory local API with versions and the update of a POST that names a key and its version."""

    def __init__(self, rows=(), drop_updates=False):
        super().__init__(rows)
        for r in self.rows.values():
            r["data"].setdefault("version", 1)
        self.updated, self.drop_updates, self.clock = [], drop_updates, 100

    def create(self, items):
        keys, failed = super().create(items)
        for k in keys:
            self.clock += 1
            self.rows[k]["data"].update(version=1, dateAdded=f"2026-11-10T10:00:{self.clock % 60:02d}Z",
                                        dateModified=f"2026-11-10T10:00:{self.clock % 60:02d}Z")
        return keys, failed

    def update(self, changes):
        self.updated += copy.deepcopy(changes)
        failed = []
        for c in changes:
            row = self.rows.get(c["key"])
            if not row or row["data"]["version"] != c["version"] or c["key"] in getattr(self, "conflicts", ()):
                failed.append({"key": c["key"], "message": "version conflict"})
                continue
            if not self.drop_updates:
                row["data"].update({k: v for k, v in c.items() if k not in ("key", "version")})
            row["data"]["version"] += 1
            row["data"]["dateModified"] = "2026-11-10T12:00:00Z"   # Zotero moves the date on every change
        return failed


@pytest.fixture
def paper(tmp_path):
    pdf = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 120), S1)
        page.insert_text((72, 400), S2)
        page.insert_text((72, 600), S3)
        doc.save(pdf)
    return tmp_path, str(pdf)


def run(paper, monkeypatch, capsys, config, *args, api):
    tmp, pdf = paper
    path = tmp / "config.json"
    data = dict({"pdf": pdf, "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(tmp / "out"), "preview_pages": []}, **config)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
    monkeypatch.setattr(cli, "pick_backend", lambda *a: ("api", api, "test API"))
    code = 0
    try:
        cli.main(["--config", str(path), *args])
    except SystemExit as e:
        code = e.code
    return code, json.loads(capsys.readouterr().out)


def hl(*pairs):
    return [{"page": 1, "text": text, "comment": comment} for text, comment in pairs]


def annotations(api):
    return {k: r["data"] for k, r in api.rows.items() if r["data"]["itemType"] == "annotation"}


def record(paper):
    return json.loads((paper[0] / "out" / "applied_keys.json").read_text(encoding="utf8"))


FIRST = hl((S1, "该方法提升了每个基准上的结果。"), (S2, "另一句话。"))


def test_a_cleanup_without_earlier_annotations_creates_them_all(paper, monkeypatch, capsys):
    api = UpdatingApi()
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIRST, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and report["rewrite"] == {"created": 2, "updated": 0, "kept": 0, "removed": 0}
    assert api.updated == [] and api.deleted == []


def test_a_corrected_comment_updates_that_annotation_only(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    before = copy.deepcopy(annotations(api))
    fixed = hl((S1, "该方法在每个基准上都提升了结果。"), (S2, "另一句话。"))
    code, report = run(paper, monkeypatch, capsys, {"highlights": fixed, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and report["rewrite"] == {"created": 0, "updated": 1, "kept": 1, "removed": 0}
    assert [{k: v for k, v in u.items()} for u in api.updated] == [{"key": "NEW1", "version": 1, "annotationComment": "该方法在每个基准上都提升了结果。"}]
    assert api.deleted == [] and api.n == 2, "nothing deleted, nothing created"
    assert annotations(api)["NEW2"] == before["NEW2"], "the unchanged one is left untouched"
    r = record(paper)
    assert r["createdKeys"] == [] and r["updatedKeys"] == ["NEW1"] and r["keptKeys"] == ["NEW2"]
    # and once more: the updated annotation is the tool's, not one the user changed (its date moved with the update)
    code, again = run(paper, monkeypatch, capsys, {"highlights": FIRST, "cleanup": True}, "--apply", api=api)
    assert again["applied"] is True and "user_edit" not in [w["kind"] for w in again.get("style_warnings", [])]
    assert again["rewrite"] == {"created": 0, "updated": 1, "kept": 1, "removed": 0}


def test_an_annotation_left_out_is_the_only_one_deleted(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIRST[:1], "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and report["rewrite"] == {"created": 0, "updated": 0, "kept": 1, "removed": 1}
    assert api.deleted == ["NEW2"] and api.updated == [] and set(annotations(api)) == {"NEW1"}


def test_mixed_changes(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    mixed = hl((S1, "该方法提升了结果。"), (S3, "第三句。"))   # one changed, one left out, one added
    mixed[0]["core"] = True                                     # and a new colour
    code, report = run(paper, monkeypatch, capsys, {"highlights": mixed, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and report["rewrite"] == {"created": 1, "updated": 1, "kept": 0, "removed": 1}
    assert api.updated == [{"key": "NEW1", "version": 1, "annotationComment": "该方法提升了结果。", "annotationColor": "#ff6666"}]
    assert api.deleted == ["NEW2"] and set(annotations(api)) == {"NEW1", "NEW3"}
    assert report["verification"]["not_updated"] == [] if "verification" in report else True


def test_a_user_changed_annotation_still_blocks_the_rewrite(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    api.rows["NEW1"]["data"].update(annotationComment="用户改过的译文。", dateModified="2026-11-10T13:00:00Z", version=2)
    fixed = hl((S1, "该方法在每个基准上都提升了结果。"), (S2, "另一句话。"))
    code, report = run(paper, monkeypatch, capsys, {"highlights": fixed, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and "user_edit" in report["apply_error"] and api.updated == [] and api.deleted == []


def test_the_read_back_checks_the_updates(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    api.drop_updates = True   # a channel that answers success and changes nothing
    fixed = hl((S1, "该方法在每个基准上都提升了结果。"), (S2, "另一句话。"))
    code, report = run(paper, monkeypatch, capsys, {"highlights": fixed, "cleanup": True}, "--apply", "--verbose", api=api)
    assert report["applied"] is False and report["verification"]["not_updated"] == ["NEW1"]
    assert "verification failed" in report["apply_error"]


def test_a_dry_run_reports_the_plan(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIRST[:1], "cleanup": True}, api=api)
    assert report["rewrite"] == {"created": 0, "updated": 0, "kept": 1, "removed": 1} and report["cleanup_removes"] == 1


NOTE_A = "<h1>Paper</h1><p>First reading.</p>"
NOTE_B = "<h1>Paper</h1><p>Second reading, corrected.</p>"


def notes(api):
    return {k: r["data"] for k, r in api.rows.items() if r["data"]["itemType"] == "note"}


def test_the_reading_note_is_rewritten_in_place(paper, monkeypatch, capsys):
    tmp = paper[0]
    (tmp / "note.html").write_text(NOTE_A, encoding="utf8")
    api = UpdatingApi()
    conf = {"highlights": FIRST, "note_html": str(tmp / "note.html"), "note_replace": True, "note_title_prefix": "Paper"}
    run(paper, monkeypatch, capsys, conf, "--apply", api=api)
    [key] = notes(api)
    (tmp / "note.html").write_text(NOTE_B, encoding="utf8")
    code, report = run(paper, monkeypatch, capsys, dict(conf, cleanup=True), "--apply", api=api)
    assert report["applied"] is True and list(notes(api)) == [key] and notes(api)[key]["note"] == NOTE_B
    assert api.trashed == [] and record(paper)["noteKeys"] == [key]
    # the user changes the note in Zotero: a rewrite that would undo that is held back
    api.rows[key]["data"].update(note=NOTE_B.replace("corrected", "corrected by me"), dateModified="2026-11-10T14:00:00Z")
    (tmp / "note.html").write_text(NOTE_A, encoding="utf8")
    code, report = run(paper, monkeypatch, capsys, dict(conf, cleanup=True), "--apply", api=api)
    assert report["applied"] is False and "user_edit" in report["apply_error"]
    assert any(w["kind"] == "user_edit" and w["text"] == "reading note" for w in report["style_warnings"])
    # let through, the user's version goes to the trash and a new note is written, as before
    code, report = run(paper, monkeypatch, capsys, dict(conf, cleanup=True), "--apply", "--accept", "user_edit", api=api)
    assert report["applied"] is True and api.trashed == [key] and len(notes(api)) == 2


def test_a_note_the_folder_did_not_write_goes_to_the_trash_as_before(paper, monkeypatch, capsys):
    tmp = paper[0]
    (tmp / "note.html").write_text(NOTE_B, encoding="utf8")
    api = UpdatingApi([note_row("OLD", NOTE_A, ["zotero-scholium"])])
    conf = {"highlights": FIRST, "note_html": str(tmp / "note.html"), "note_replace": True, "note_title_prefix": "Paper", "cleanup": True}
    code, report = run(paper, monkeypatch, capsys, conf, "--apply", api=api)
    assert report["applied"] is True and api.trashed == ["OLD"] and len(notes(api)) == 2


def test_a_change_that_fails_leaves_a_partial_write_and_the_rest(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    api.conflicts = {"NEW1"}   # changed in Zotero between the read and the write
    mixed = hl((S1, "该方法提升了结果。"), (S3, "第三句。"))
    code, report = run(paper, monkeypatch, capsys, {"highlights": mixed, "cleanup": True}, "--apply", api=api)
    assert code == 2 and report["applied"] == "partial" and "changing the earlier ones failed: version conflict" in report["apply_error"]
    assert api.deleted == [] and "NEW3" in annotations(api), "the new one is written, the one left out stays until a run again"
    assert record(paper)["updatedKeys"] == []
