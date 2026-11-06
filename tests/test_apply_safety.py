"""Write outcomes and annotation ownership, with an in-memory Zotero API."""
import json
import shutil
import subprocess

import pymupdf
import pytest

from zotero_scholium import cli

NODE = shutil.which("node")


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
    def __init__(self, rows=(), fail_type=None, hide_created=False, readback_error=False, parent="ITEM"):
        self.rows = {row["key"]: row for row in rows}
        self.fail_type = fail_type
        self.hide_created = hide_created
        self.readback_error = readback_error
        self.parent = parent   # the attachment ATT's parent item
        self.created_keys = []

    def item(self, key):
        return {"key": key, "data": {"itemType": "attachment", "parentItem": self.parent}}

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
    result = cli.api_apply(config(cleanup=True), [dict(HIGHLIGHT, comment=comment)], api)
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
    assert result["noteCreated"] is False
    assert set(api.rows) == {"OWN"}, "no new note and no new annotation"


def test_the_note_is_written_after_every_annotation_was_accepted(tmp_path):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
    api = MemoryApi()
    result = cli.api_apply(config(note_html=str(note)), [HIGHLIGHT, dict(HIGHLIGHT, text="Other result.")], api)
    assert result["ok"] and result["createdKeys"] == ["NEW1", "NEW2"] and result["noteKeys"] == ["NEW3"]
    assert [api.rows[k]["data"]["itemType"] for k in api.created_keys] == ["annotation", "annotation", "note"]


def test_refused_annotations_leave_no_new_note(tmp_path):
    """The local API refuses the annotations (HTTP 500 on a second --apply): the note is not written."""
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")

    class Refusing(MemoryApi):
        def create(self, items):
            if items[0]["itemType"] == "annotation":
                return [], [{"message": "create failed (HTTP 500): An error occurred", "items": f"1-{len(items)} of {len(items)}"}]
            return super().create(items)
    api = Refusing([annotation("OWN", ["zotero-scholium"])])
    result = cli.api_apply(config(cleanup=True, note_html=str(note), note_replace=True), [HIGHLIGHT], api)
    assert result["ok"] is False and result["noteCreated"] is False and result["noteKeys"] == []
    assert set(api.rows) == {"OWN"} and api.created_keys == []


def test_a_note_that_is_not_written_takes_the_new_annotations_back(tmp_path):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
    api = MemoryApi([annotation("OWN", ["zotero-scholium"])], fail_type="note")
    result = cli.api_apply(config(cleanup=True, note_html=str(note)), [HIGHLIGHT], api)
    assert result["ok"] is False and result["failed"] and result["removed"] == 0
    assert set(api.rows) == {"OWN"}, "the new annotation removed again, the earlier one kept"
    assert result["createdKeys"] == [] and result["created"] == {} and "removed again" in result["undone"]

    class FailingDelete(MemoryApi):
        def delete(self, keys):
            raise RuntimeError("delete failed (HTTP 500): busy")
    api = FailingDelete([annotation("OWN", ["zotero-scholium"])], fail_type="note")
    result = cli.api_apply(config(cleanup=True, note_html=str(note)), [HIGHLIGHT], api)
    assert result["ok"] is False and result["createdKeys"] == ["NEW1"] and "undone" not in result
    assert result["undoError"] == ("the new annotations stay, since removing them failed: delete failed (HTTP 500): busy; "
                                   "run --list before running again")


def test_an_item_that_is_not_the_attachments_parent_is_refused_before_writing(tmp_path, monkeypatch):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
    api = MemoryApi([annotation("OWN", ["zotero-scholium"])], parent="OTHER")
    options = dict(cleanup=True, note_html=str(note), note_replace=True)
    with pytest.raises(RuntimeError, match="^item ITEM is not the parent of attachment ATT; set item_key to the attachment's parent key from status$"):
        cli.api_apply(config(**options), [HIGHLIGHT], api)
    assert set(api.rows) == {"OWN"} and api.created_keys == []
    assert cli.api_apply(dict(config(**options), item_key="ATT"), [], MemoryApi(parent="OTHER"))["ok"], "the attachment's own key passes"
    # the local API: the attachment's parentItem is read, and nothing is written
    sent = []

    def http(method, path, body=None, headers=None, timeout=60):
        sent.append((method, path))
        return 200, {}, json.dumps({"key": "ATT", "data": {"itemType": "attachment", "parentItem": "OTHER"}})
    monkeypatch.setattr(cli, "http", http)
    with pytest.raises(RuntimeError, match="is not the parent"):
        cli.api_apply(config(**options), [HIGHLIGHT], cli.LocalApi("SID"))
    assert sent == [("GET", "/api/users/0/items/ATT")]


RUN_JS = r"""
const vm = require('node:vm');
const script = require('node:fs').readFileSync(0, 'utf8');
const saved = [];
const items = { PARENT: { id: 2, key: 'PARENT', getNotes: () => [] }, OTHER: { id: 3, key: 'OTHER', getNotes: () => [] },
                ATT: { id: 1, key: 'ATT', parentID: 2, getAnnotations: () => [] } };
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1 },
  Items: { getByLibraryAndKey: (lib, key) => items[key] || null, get: ids => [], trashTx: async () => {} },
  DB: { executeTransaction: async callback => callback() },
  Item: class {
    constructor(type) { this.type = type; }
    setNote(html) {}
    setTags(tags) {}
    async save() { saved.push(this.type); }
    async saveTx() { saved.push(this.type); }
  },
} });
vm.runInContext('(async function () {\n' + script + '\n})()', context)
  .then(result => process.stdout.write(JSON.stringify({ result, saved })),
        error => process.stdout.write(JSON.stringify({ error: error.message, saved })));
"""


@pytest.mark.skipif(NODE is None, reason="Node.js is required to run the generated JavaScript")
@pytest.mark.parametrize("item_key, error", [("PARENT", None), ("OTHER", "item OTHER is not the parent of attachment ATT; set item_key to the attachment's parent key from status")])
def test_the_generated_javascript_refuses_an_item_that_is_not_the_parent(tmp_path, item_key, error):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
    script = cli.render_js(dict(config(cleanup=True, note_html=str(note), note_replace=True), item_key=item_key), [HIGHLIGHT])
    out = json.loads(subprocess.run([NODE, "-e", RUN_JS], input=script, encoding="utf8", capture_output=True, check=True,
                                    timeout=15).stdout)
    assert out.get("error") == error
    assert out["saved"] == ([] if error else ["note", "annotation"])


def run_main(tmp_path, monkeypatch, capsys, api, with_note=False, args=("--ignore-existing",), **options):
    """A run of `scholium --apply`; with `api` None the backend is picked as usual."""
    pdf = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 120), "The method improves the result.")
        doc.save(pdf)
    cfg = {"pdf": str(pdf), "item_key": "ITEM", "attachment_key": "ATT",
           "out_dir": str(tmp_path), "preview_pages": [], "cleanup": False,
           "highlights": [{"page": 1, "text": "The method improves the result.", "comment": ""}], **options}
    if with_note:
        note = tmp_path / "note.html"
        note.write_text("<h1>Paper</h1><p>A reading note.</p>", encoding="utf8")
        cfg["note_html"] = str(note)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(dict(cfg, data_dir=str(tmp_path))), encoding="utf8")
    if api is not None:
        monkeypatch.setattr(cli, "pick_backend", lambda *args: ("api", api, "test API"))
    code = 0
    try:
        cli.main(["--config", str(path), "--apply", *args])
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(capsys.readouterr().out)


def test_main_does_not_report_failed_items_as_applied(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(fail_type="annotation"))
    assert code == 2 and report["applied"] is False
    assert report["apply_error"] and report["result"]["failed"]
    assert "fallback" not in report, "retrying the entire script can duplicate a partial write"


def test_main_leaves_no_new_note_when_the_annotations_are_refused(tmp_path, monkeypatch, capsys):
    api = MemoryApi(fail_type="annotation")
    code, report = run_main(tmp_path, monkeypatch, capsys, api, with_note=True)
    assert code == 2 and report["applied"] is False and report["result"]["noteCreated"] is False
    assert api.created_keys == [] and not any(r["data"]["itemType"] == "note" for r in api.rows.values())


def test_main_verifies_created_keys_instead_of_total_count(tmp_path, monkeypatch, capsys):
    api = MemoryApi([annotation("UNRELATED")], hide_created=True)
    code, report = run_main(tmp_path, monkeypatch, capsys, api, with_note=True)
    assert code == 2 and report["applied"] is False
    assert report["verification"]["missing_annotations"] == ["NEW1"]
    assert report["verification"]["missing_notes"] == ["NEW2"]


def test_main_reports_readback_error_after_writing(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(readback_error=True))
    assert code == 2 and report["applied"] is False
    assert "read-back unavailable" in report["apply_error"]
    assert "createdKeys" not in report["result"], "the keys go to a file, not into the report"
    keys = json.loads(open(report["result"]["keys"], encoding="utf8").read())
    assert keys["createdKeys"] == ["NEW1"]


def test_a_failed_removal_after_writing_is_reported_as_partial(tmp_path, monkeypatch, capsys):
    """The new annotations are in Zotero when removing the old ones fails: the report says so instead of applied: false."""
    class FailingDelete(MemoryApi):
        def delete(self, keys):
            raise RuntimeError("delete failed (HTTP 500): busy")
    api = FailingDelete([annotation("OWN", ["zotero-scholium"], text="Old result.")])
    code, report = run_main(tmp_path, monkeypatch, capsys, api, args=(), cleanup=True)
    assert code == 2 and report["applied"] == "partial" and list(report)[-1] == "apply_error"
    assert report["result"]["created"] == {"highlight": 1} and report["result"]["removeError"] == "delete failed (HTTP 500): busy"
    assert "removing the earlier ones failed: delete failed (HTTP 500): busy" in report["apply_error"]
    assert "run --list" in report["apply_error"] and report["verification"]["missing_annotations"] == []
    assert json.load(open(report["result"]["keys"], encoding="utf8"))["createdKeys"] == ["NEW1"]
    assert set(api.rows) == {"OWN", "NEW1"}


def test_a_run_names_an_item_that_is_not_the_parent(tmp_path, monkeypatch, capsys):
    api = MemoryApi(parent="OTHER")
    code, report = run_main(tmp_path, monkeypatch, capsys, api, with_note=True)
    assert code == 2 and report["applied"] is False and report["apply_error"] == "item ITEM is not the parent of attachment ATT; set item_key to the attachment's parent key from status"
    assert api.created_keys == []


def test_main_reports_verified_annotation_and_note(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(), with_note=True)
    assert code == 0 and report["applied"] is True
    assert report["verification"] == {"missing_annotations": [], "missing_notes": []}
    assert report["now_in_zotero"]["annotations"] == 1
    assert report["result"]["noteCreated"] is True


@pytest.mark.parametrize("with_note", [False, True])
def test_a_plugin_run_reuses_the_listing_of_each_connection_check(tmp_path, monkeypatch, capsys, with_note):
    """Backend check and existing annotations, backend check and write, read-back: five listings, note or not."""
    (tmp_path / "scholium.token").write_text("TOKEN", encoding="utf8")
    calls = []

    def http(method, path, body=None, headers=None, timeout=60):
        if not path.startswith("/scholium/"):   # the local API's version check
            return 0, {}, "refused"
        calls.append(path)
        assert headers["X-Annotate-Token"] == "TOKEN"
        if path == "/scholium/apply":
            assert (body["note"] is not None) is with_note
            return 200, {}, json.dumps({"ok": True})
        return 200, {}, json.dumps({"ok": True, "annotations": [], "notes": [{"key": "N", "title": "Paper"}]})

    monkeypatch.setattr(cli, "http", http)
    code, report = run_main(tmp_path, monkeypatch, capsys, None, with_note, ("--backend", "plugin"))
    assert code == 0 and report["applied"] is True and report["backend"] == "plugin"
    assert calls == ["/scholium/list"] * 4 + ["/scholium/apply", "/scholium/list"]
