"""Write outcomes and annotation ownership, with an in-memory Zotero API."""
import json

import pymupdf
import pytest

from zotero_scholium import cli


HIGHLIGHT = {
    "type": "highlight", "color": "#ffd400", "comment": "", "text": "New result.",
    "pageLabel": "1", "sortIndex": "00000|000000|00001",
    "position": {"pageIndex": 0, "rects": [[10, 10, 100, 20]]},
}


def annotation(key, tags=(), text="User result.", comment=""):
    return {"key": key, "data": {
        "itemType": "annotation", "parentItem": "ATT", "annotationType": "highlight",
        "annotationText": text, "annotationComment": comment,
        "annotationColor": "#ffd400", "annotationPageLabel": "1",
        "annotationPosition": '{"pageIndex":0,"rects":[[10,10,100,20]]}',
        "tags": [{"tag": tag} for tag in tags],
    }}


class MemoryApi:
    def __init__(self, rows=(), fail_type=None, hide_created=False, readback_error=False):
        self.rows = {row["key"]: row for row in rows}
        self.fail_type = fail_type
        self.hide_created = hide_created
        self.readback_error = readback_error
        self.created_keys = []

    def children(self, key, item_type=None):
        if self.created_keys and self.readback_error:
            raise RuntimeError("read-back unavailable")
        return [row for k, row in self.rows.items()
                if row["data"]["parentItem"] == key
                and (not item_type or row["data"]["itemType"] == item_type)
                and not (self.hide_created and k in self.created_keys)]

    def create(self, items):
        keys, failed = [], []
        for item in items:
            if item["itemType"] == self.fail_type:
                failed.append({"code": 400, "message": "invalid item"})
                continue
            key = "NEW" + str(len(self.created_keys) + 1)
            self.rows[key] = {"key": key, "data": item.copy()}
            self.created_keys.append(key)
            keys.append(key)
        return keys, failed

    def delete(self, keys):
        for key in keys:
            del self.rows[key]
        return len(keys)


def config(**options):
    return dict(cli.DEFAULTS, item_key="ITEM", attachment_key="ATT", **options)


@pytest.mark.parametrize("comment", ["", "same comment"])
def test_cleanup_preserves_untagged_annotations_even_when_content_matches(comment):
    api = MemoryApi([
        annotation("USER_EMPTY"),
        annotation("USER_SAME", text="New result.", comment=comment),
        annotation("OWN", ["zotero-scholium"]),
        annotation("LEGACY", [next(iter(cli.LEGACY_TAGS))]),
    ])
    result = cli.api_apply(config(), [dict(HIGHLIGHT, comment=comment)], api)
    assert set(api.rows) == {"USER_EMPTY", "USER_SAME", "NEW1"}
    assert result["removed"] == 2 and result["ok"]


def test_note_only_addition_with_cleanup_disabled_preserves_highlights(tmp_path):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
    api = MemoryApi([annotation("OWN", ["zotero-scholium"])])
    result = cli.api_apply(config(cleanup=False, note_html=str(note)), [], api)
    assert "OWN" in api.rows
    assert result["noteCreated"] and result["removed"] == 0


@pytest.mark.parametrize("fail_type", ["note", "annotation"])
def test_failed_creation_reports_failure_and_preserves_previous_annotations(tmp_path, fail_type):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
    api = MemoryApi([annotation("OWN", ["zotero-scholium"])], fail_type=fail_type)
    result = cli.api_apply(config(note_html=str(note)), [HIGHLIGHT], api)
    assert result["ok"] is False
    assert "OWN" in api.rows and result["removed"] == 0
    assert result["failed"]
    assert result["noteCreated"] is (fail_type != "note")


def run_main(tmp_path, monkeypatch, capsys, api, with_note=False):
    pdf = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 120), "The method improves the result.")
        doc.save(pdf)
    cfg = {"pdf": str(pdf), "item_key": "ITEM", "attachment_key": "ATT",
           "out_dir": str(tmp_path), "preview_pages": [], "cleanup": False,
           "highlights": [{"page": 1, "text": "The method improves the result.", "comment": ""}]}
    if with_note:
        note = tmp_path / "note.html"
        note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
        cfg["note_html"] = str(note)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf8")
    monkeypatch.setattr(cli, "pick_backend", lambda *args: ("api", api, "test API"))
    code = 0
    try:
        cli.main(["--config", str(path), "--apply", "--ignore-existing"])
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(capsys.readouterr().out)


def test_main_does_not_report_failed_items_as_applied(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(fail_type="annotation"))
    assert code == 2 and report["applied"] is False
    assert report["apply_error"] and report["result"]["failed"]
    assert "fallback" not in report, "retrying the entire script can duplicate a partial write"


def test_main_verifies_created_keys_instead_of_total_count(tmp_path, monkeypatch, capsys):
    api = MemoryApi([annotation("UNRELATED")], hide_created=True)
    code, report = run_main(tmp_path, monkeypatch, capsys, api, with_note=True)
    assert code == 2 and report["applied"] is False
    assert report["verification"]["missing_annotations"] == ["NEW2"]
    assert report["verification"]["missing_notes"] == ["NEW1"]


def test_main_reports_readback_error_after_writing(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(readback_error=True))
    assert code == 2 and report["applied"] is False
    assert "read-back unavailable" in report["apply_error"]
    assert report["result"]["createdKeys"] == ["NEW1"]


def test_main_reports_verified_annotation_and_note(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(), with_note=True)
    assert code == 0 and report["applied"] is True
    assert report["verification"] == {"missing_annotations": [], "missing_notes": []}
    assert report["now_in_zotero"]["annotations"] == 1
    assert report["result"]["noteCreated"] is True
