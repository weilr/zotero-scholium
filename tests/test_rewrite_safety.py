"""What a rewrite in place never does: overwrite what the user changed, lose its record of what the tool wrote, or act on
a plan that no longer fits what is in Zotero. The in-memory local API and the in-memory Zotero of the plugin tests stand in
for Zotero; nothing reaches a socket."""
import json

import pytest

from plugin_harness import NODE
from test_plugin_rewrite import zotero, EXISTING, NEW, by_key, request
from test_rewrite_in_place import UpdatingApi, paper, run, hl, annotations, notes, record, FIRST, S1, S2, S3  # noqa: F401
from zotero_scholium import cli

node = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")


def kinds(report):
    return [w["kind"] for w in report.get("style_warnings", [])]


NOTE_A = "<h1>Paper</h1><p>First reading of the method.</p>"
NOTE_B = "<h1>Paper</h1><p>Second reading, corrected.</p>"


def note_run(paper, monkeypatch, capsys, html, api, *args):
    tmp = paper[0]
    (tmp / "note.html").write_text(html, encoding="utf8")
    conf = {"highlights": FIRST, "note_html": str(tmp / "note.html"), "note_replace": True, "note_title_prefix": "Paper", "cleanup": True}
    return run(paper, monkeypatch, capsys, conf, "--apply", *args, api=api)


# --- the reading note ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("edit", [
    # a figure and a bold phrase: the text is the same
    lambda html: ('<div data-schema-version="9"><h1>Paper</h1><p>First <strong>reading</strong> of the method.</p>'
                  '<p><img data-attachment-key="IMGKEY01" width="300" height="200"></p></div>'),
    # a new title
    lambda html: html.replace("<h1>Paper</h1>", "<h1>Paper - my summary for the seminar</h1>"),
], ids=["markup", "title"])
def test_a_note_whose_markup_or_title_the_user_changed_goes_to_the_trash_not_overwritten(paper, monkeypatch, capsys, edit):
    api = UpdatingApi()
    note_run(paper, monkeypatch, capsys, NOTE_A, api)
    [key] = notes(api)
    users = edit(NOTE_A)
    api.rows[key]["data"].update(note=users, dateModified="2026-11-10T14:00:00Z", version=5)
    code, report = note_run(paper, monkeypatch, capsys, NOTE_B, api)
    assert report["applied"] is True and "user_edit" not in kinds(report), "its text is the tool's: no warning"
    assert notes(api)[key]["note"] == users and api.trashed == [key], "the user's version is in the trash, as it was"
    assert [n["note"] for k, n in notes(api).items() if k != key] == [NOTE_B]


def test_a_note_rewritten_in_place_is_one_the_tool_left_as_it_is(paper, monkeypatch, capsys):
    api = UpdatingApi()
    note_run(paper, monkeypatch, capsys, NOTE_A, api)
    [key] = notes(api)
    code, report = note_run(paper, monkeypatch, capsys, NOTE_B, api)
    assert report["applied"] is True and list(notes(api)) == [key] and notes(api)[key]["note"] == NOTE_B and api.trashed == []
    assert set(record(paper)["notes"][key]) == {"html", "text"}


def test_a_note_changed_between_the_read_and_the_write_is_not_overwritten(paper, monkeypatch, capsys):
    api = UpdatingApi()
    note_run(paper, monkeypatch, capsys, NOTE_A, api)
    [key] = notes(api)
    real = api.children

    def children(k, item_type=None):   # the user types into the note while the run lays out the annotations
        rows = real(k, item_type)
        if k == "ITEM" and api.listed:
            api.rows[key]["data"].update(note=NOTE_A.replace("</p>", " And my own sentence.</p>"), version=9)
        api.listed = api.listed or k == "ITEM"   # the listing read the notes; the write reads them again
        return rows
    api.listed = False
    monkeypatch.setattr(api, "children", children)
    code, report = note_run(paper, monkeypatch, capsys, NOTE_B, api)
    assert "my own sentence" in notes(api)[key]["note"] and api.trashed == [key]


@node
def test_the_plugin_does_not_overwrite_a_note_changed_after_the_listing():
    existing = [dict(e, html="<h1>Paper</h1><p>Old, and the user's paragraph typed a moment ago.</p>") if e["key"] == "N1" else e
                for e in EXISTING]
    note = {"html": "<h1>Paper</h1><p>New.</p>", "titlePrefix": "Paper", "trashOwn": True, "trashTitlePrefix": "Paper", "updateKey": "N1",
            "expectHtml": "<h1>Paper</h1><p>Old.</p>"}
    out = zotero(request(keep=["A1", "A2"], note=note), existing)
    assert not out["result"].get("noteUpdated") and out["trashed"] == ["N1"] and out["result"]["noteCreated"] is True
    assert "user's paragraph" in by_key(out)["N1"]["note"]


@node
def test_the_plugin_lists_the_notes_text_only_when_asked():
    plain = zotero({"attachmentKey": "ATTACH01"}, EXISTING, listing=True)["result"]
    asked = zotero({"attachmentKey": "ATTACH01", "noteHtml": True}, EXISTING, listing=True)["result"]
    assert all("html" not in n for n in plain["notes"])
    assert {n["key"]: "html" in n for n in asked["notes"]} == {"N1": True, "N2": False}


@node
def test_the_javascript_file_saves_the_note_with_the_annotations_or_not_at_all(tmp_path):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>New.</p>", encoding="utf8")
    cfg = dict(cli.DEFAULTS, item_key="PARENT01", attachment_key="ATTACH01", cleanup=True, note_html=str(note), note_replace=True,
               note_title_prefix="Paper")
    # a change the transaction cannot save (stands in for any failure inside it)
    plan = {"create": [], "update": [{"key": "A1", "index": 0, "fields": {"position": {"pageIndex": 0, "rects": []}}}],
            "keep": [{"key": "A2", "index": 1}], "remove": [], "note": {"update": "N1", "expect": "<h1>Paper</h1><p>Old.</p>"}}
    existing = [dict(e, type="note") if e["key"] == "A1" else e for e in EXISTING]
    out = zotero(script=cli.render_js(cfg, [NEW, NEW], plan), existing=existing)
    assert out.get("error") and "N1" not in out["saves"]
    # the note the file was written for changed since: it goes to the trash and a new one is written
    changed = [dict(e, html="<h1>Paper</h1><p>Old, and mine.</p>") if e["key"] == "N1" else e for e in EXISTING]
    plan = dict(plan, update=[], keep=[{"key": "A1", "index": 0}, {"key": "A2", "index": 1}])
    out = zotero(script=cli.render_js(cfg, [NEW, NEW], plan), existing=changed)
    assert "error" not in out, out.get("error")
    assert by_key(out)["N1"]["note"] == "<h1>Paper</h1><p>Old, and mine.</p>" and out["trashed"] == ["N1"]
