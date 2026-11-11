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


# --- the record of what the tool wrote --------------------------------------------------------------------------

FIXED = hl((S1, "该方法在每个基准上都提升了结果。"), (S2, "另一句话。"))
AGAIN = hl((S1, "该方法在所有基准上都提升了结果。"), (S2, "另一句话。"))


def test_a_write_that_wrote_nothing_leaves_the_record_as_it_was(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)   # NEW1 changed in place
    before = record(paper)
    real = api.create
    api.create = lambda items: ([], [{"message": "create failed (HTTP 500): busy"}])
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED + hl((S3, "第三句。")), "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and record(paper) == before
    api.create = real
    code, report = run(paper, monkeypatch, capsys, {"highlights": AGAIN, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and "user_edit" not in kinds(report), "the tool's own change is still known as the tool's"


def test_a_change_the_answer_did_not_confirm_is_taken_from_the_read_back(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    real = api.update

    def half(changes):   # the first change is made, then the request fails as a whole (as a later batch of 50 would)
        real(changes[:1])
        return [{"message": "update failed (HTTP 500): busy", "items": "2-2 of 2"}]
    api.update = half
    both = hl((S1, "该方法在每个基准上都提升了结果。"), (S2, "又一句话。"))
    code, report = run(paper, monkeypatch, capsys, {"highlights": both, "cleanup": True}, "--apply", api=api)
    assert report["applied"] == "partial" and record(paper)["updatedKeys"] == ["NEW1"]
    api.update = real
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl((S1, "该方法在所有基准上都提升了结果。"), (S2, "又一句话。")), "cleanup": True},
                       "--apply", api=api)
    assert report["applied"] is True and "user_edit" not in kinds(report)


def test_a_failed_read_back_keeps_the_plans_fingerprints(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    real, calls = cli.api_list, []

    def api_list(cfg, handle):   # the listing answers, the read-back after the write does not
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("read-back unavailable")
        return real(cfg, handle)
    monkeypatch.setattr(cli, "api_list", api_list)
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and "verification failed" in report["apply_error"]
    assert set(record(paper)["written"]) == {"NEW1", "NEW2"}
    monkeypatch.setattr(cli, "api_list", real)
    code, report = run(paper, monkeypatch, capsys, {"highlights": AGAIN, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and "user_edit" not in kinds(report)


def test_an_annotation_the_user_changed_during_a_run_is_theirs_next_time(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    real = api.update

    def meanwhile(changes):   # while the run writes, the user corrects NEW2, which the run keeps as it is
        api.rows["NEW2"]["data"].update(annotationComment="我自己的译文。", dateModified="2026-11-10T16:00:00Z", version=7)
        return real(changes)
    api.update = meanwhile
    run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    api.update = real
    code, report = run(paper, monkeypatch, capsys, {"highlights": AGAIN, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and "user_edit" in kinds(report) and annotations(api)["NEW2"]["annotationComment"] == "我自己的译文。"


def test_the_local_apis_changes_name_the_keys_each_batch_took(monkeypatch):
    answers = [(200, {}, json.dumps({"successful": {"0": {"key": "K1"}}, "unchanged": {"1": "K2"}, "failed": {"2": {"key": "K3", "code": 412}}})),
               (500, {}, "busy")]
    monkeypatch.setattr(cli, "http", lambda *a, **k: answers.pop(0))
    api = cli.LocalApi("SID")
    api.key, api.WRITE_ATTEMPTS = "KEY", 1
    changes = [{"key": f"K{i}", "version": 1} for i in range(1, 54)]
    done, failed = api.update(changes)
    assert done == ["K1", "K2"] and failed[0]["key"] == "K3" and "HTTP 500" in failed[1]["message"] and failed[1]["items"] == "51-53 of 53"
