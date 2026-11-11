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


# --- what counts as the user's change -----------------------------------------------------------------------------

def written_twice(paper, monkeypatch, capsys):
    """Two writes, the second changing NEW1 in place: its fingerprint is the tool's."""
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    api.updated = []
    return api


def bump(api, key, **data):
    api.rows[key]["data"].update(data, dateModified="2026-11-10T15:00:00Z", version=api.rows[key]["data"]["version"] + 1)


ASK = ("stop and ask the user; pass --accept user_edit only after a later message of theirs confirms deleting or overwriting their "
       "change")
DELETE = ("since the tool wrote this annotation ({key}), the user {done} in Zotero, and the rewrite would delete it: keep it in the "
          "configuration, or " + ASK)
UNDO = ("since the tool wrote this annotation ({key}), the user {done} in Zotero, and the rewrite would undo that: keep {keep} in the "
        "configuration, or " + ASK)


def user_edits(report):
    return [w["reason"] for w in report.get("style_warnings", []) if w["kind"] == "user_edit"]


def test_a_page_label_the_user_set_stays_while_the_comment_is_corrected(paper, monkeypatch, capsys):
    api = written_twice(paper, monkeypatch, capsys)
    bump(api, "NEW1", annotationPageLabel="ii")   # Edit Page Number… in the reader
    code, report = run(paper, monkeypatch, capsys, {"highlights": AGAIN, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and user_edits(report) == [] and report["rewrite"]["updated"] == 1
    assert [sorted(c) for c in api.updated] == [["annotationComment", "key", "version"]], "only the configuration's fields are sent"
    assert annotations(api)["NEW1"]["annotationPageLabel"] == "ii" and annotations(api)["NEW1"]["annotationComment"] == AGAIN[0]["comment"]
    # the label is still the user's: left out of the set, the annotation would be deleted
    code, report = run(paper, monkeypatch, capsys, {"highlights": AGAIN[1:], "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and api.deleted == []
    assert user_edits(report) == [DELETE.format(key="NEW1", done="changed the page label 1 → ii")]


def test_a_tag_the_user_added_stays_and_holds_back_only_a_deletion(paper, monkeypatch, capsys):
    api = written_twice(paper, monkeypatch, capsys)
    api.rows["NEW2"]["data"]["tags"].append({"tag": "important"})
    bump(api, "NEW2")
    # left out of the set, it would be deleted: held back
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED[:1], "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and api.deleted == []
    assert user_edits(report) == [DELETE.format(key="NEW2", done="added the tag “important”")]
    # kept in the set as it is, it stays with the user's tag, and nothing is said
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and user_edits(report) == [] and api.updated == []
    # its comment corrected: changed in place, and the tag stays
    fixed = hl((S1, FIXED[0]["comment"]), (S2, "另一句话，改过。"))
    code, report = run(paper, monkeypatch, capsys, {"highlights": fixed, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and user_edits(report) == [] and report["rewrite"]["updated"] == 1
    assert [sorted(c) for c in api.updated] == [["annotationComment", "key", "version"]]
    assert annotations(api)["NEW2"]["annotationComment"] == "另一句话，改过。" and {"tag": "important"} in annotations(api)["NEW2"]["tags"]


def test_a_comment_the_user_changed_holds_back_a_rewrite_that_changes_it(paper, monkeypatch, capsys):
    api = written_twice(paper, monkeypatch, capsys)
    bump(api, "NEW1", annotationComment="我自己的译文。")
    code, report = run(paper, monkeypatch, capsys, {"highlights": AGAIN, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and api.updated == []
    assert user_edits(report) == [UNDO.format(key="NEW1", done="changed the comment", keep="its comment “我自己的译文。”")]
    # the configuration keeps their comment: the rest goes through
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl((S1, "我自己的译文。"), (S2, "另一句话，改过。")), "cleanup": True},
                       "--apply", api=api)
    assert report["applied"] is True and user_edits(report) == [] and annotations(api)["NEW1"]["annotationComment"] == "我自己的译文。"


def test_an_annotation_the_user_moved_is_their_change(paper, monkeypatch, capsys):
    api = written_twice(paper, monkeypatch, capsys)
    pos = json.loads(api.rows["NEW2"]["data"]["annotationPosition"])
    pos["rects"] = [[r[0] + 30, r[1], r[2] + 30, r[3]] for r in pos["rects"]]
    bump(api, "NEW2", annotationPosition=json.dumps(pos))
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and api.updated == []
    assert user_edits(report) == [UNDO.format(key="NEW2", done="moved or resized it", keep="its place")]


# --- the user's word, in a run of the plugin's agent -------------------------------------------------------------------

REFUSED = ("user_edit is let through only once the user has confirmed it (NEW2): stop and ask the user; a later message of theirs "
           "that confirms deleting or overwriting their change lets --accept user_edit through")


def tagged(paper, monkeypatch, capsys):
    """Two writes, then the user tags NEW2: a set without it would delete it."""
    api = written_twice(paper, monkeypatch, capsys)
    api.rows["NEW2"]["data"]["tags"].append({"tag": "important"})
    bump(api, "NEW2")
    return api


def test_in_the_plugins_run_accept_waits_for_the_users_later_message(paper, monkeypatch, capsys):
    api = tagged(paper, monkeypatch, capsys)
    held = paper[0] / "held_back.json"
    monkeypatch.setenv("SCHOLIUM_PLUGIN_RUN", "1")
    monkeypatch.setenv("SCHOLIUM_HELD_BACK", str(held))
    drop = {"highlights": FIXED[:1], "cleanup": True}
    code, report = run(paper, monkeypatch, capsys, drop, "--apply", api=api)
    assert report["applied"] is False and json.loads(held.read_text(encoding="utf8")) == {"user_edit": ["NEW2"]}
    assert [w["keys"] for w in report["style_warnings"] if w["kind"] == "user_edit"] == [["NEW2"]]
    # the same turn: refused, also with --allow-warnings
    for how in (["--accept", "user_edit"], ["--allow-warnings"]):
        code, report = run(paper, monkeypatch, capsys, drop, "--apply", *how, api=api)
        assert report["applied"] is False and REFUSED in report["apply_error"] and api.deleted == [], how
    # confirmed for another annotation: still refused
    monkeypatch.setenv("SCHOLIUM_CONFIRMED", "user_edit:NEW1;cleanup_other:NEW2")
    code, report = run(paper, monkeypatch, capsys, drop, "--apply", "--accept", "user_edit", api=api)
    assert report["applied"] is False and REFUSED in report["apply_error"] and api.deleted == []
    # the user's next message confirmed it: through, and nothing more is noted as held back
    held.unlink()
    monkeypatch.setenv("SCHOLIUM_CONFIRMED", "user_edit:NEW2")
    code, report = run(paper, monkeypatch, capsys, drop, "--apply", "--accept", "user_edit", api=api)
    assert report["applied"] is True and api.deleted == ["NEW2"] and not held.exists()


def test_outside_the_plugin_accept_lets_it_through_as_before(paper, monkeypatch, capsys):
    api = tagged(paper, monkeypatch, capsys)
    monkeypatch.setenv("SCHOLIUM_HELD_BACK", str(paper[0] / "held_back.json"))   # without the plugin's marker
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED[:1], "cleanup": True}, "--apply", "--accept", "user_edit", api=api)
    assert report["applied"] is True and api.deleted == ["NEW2"]


def test_the_listing_names_the_tools_annotations_the_user_changed(paper, monkeypatch, capsys):
    api = tagged(paper, monkeypatch, capsys)
    bump(api, "NEW1", annotationPageLabel="ii")
    expect = [{"key": "NEW1", "type": "highlight", "page": "1", "text": S1, "changes": "changed the page label 1 → ii"},
              {"key": "NEW2", "type": "highlight", "page": "1", "text": S2, "changes": "added the tag “important”"}]
    for args in ((), ("--full",)):
        code, listing = run(paper, monkeypatch, capsys, {"highlights": FIXED}, "--list", *args, api=api)
        assert sorted(listing["changed_by_user"], key=lambda c: c["key"]) == expect, args


# the plan of a comment correction to A1, which the user relabelled ii and tagged after the tool wrote it on page 1
PLACE = {"pageIndex": 0, "rects": [[10, 10, 20, 20]]}
TOOLS_A1 = {"key": "A1", "type": "highlight", "text": "First.", "comment": "旧译文。", "color": "#ffd400", "pageLabel": "1", "tags": ["zotero-scholium"],
            "position": PLACE, "modified": "2026-11-10 10:00:00"}
USERS_A1 = dict(TOOLS_A1, pageLabel="ii", tags=["zotero-scholium", "important"])


def relabelled():
    out = [dict(NEW, text="First.", comment="新译文。", position=PLACE)]
    last = {"printVersion": cli.PRINT_VERSION, "written": {"A1": cli.written_fields(TOOLS_A1)}}
    return out, cli.rewrite_plan(out, dict(cli.DEFAULTS, cleanup=True), {"annotations": [USERS_A1]}, last)


@node
def test_the_plugin_and_the_javascript_file_keep_the_users_page_label_and_tags(monkeypatch):
    out, plan = relabelled()
    assert [(u["key"], u["fields"]) for u in plan["update"]] == [("A1", {"comment": "新译文。"})], "no page label, no tags"
    cfg = dict(cli.DEFAULTS, item_key="PARENT01", attachment_key="ATTACH01", cleanup=True)
    # the plugin, given the payload plugin_apply sends; nothing reaches a socket
    seen = {}
    monkeypatch.setattr(cli, "plugin_connect", lambda cfg: ("TOKEN", {"ok": True, "canUpdate": True, "notes": []}, "http://plugin.invalid"))

    def http(method, path, body=None, headers=None, timeout=60):
        seen["payload"], seen["zotero"] = body, zotero(body, [USERS_A1])
        return 200, {}, json.dumps(seen["zotero"]["result"])
    monkeypatch.setattr(cli, "http", http)
    res, err = cli.plugin_apply(cfg, out, plan)
    assert err is None and res["updatedKeys"] == ["A1"] and seen["payload"]["updates"] == [{"key": "A1", "comment": "新译文。"}]
    # and the JavaScript file
    js = zotero(script=cli.render_js(cfg, out, plan), existing=[USERS_A1])
    assert "error" not in js, js.get("error")
    for done in (seen["zotero"], js):
        a1 = by_key(done)["A1"]
        assert (a1["comment"], a1["pageLabel"], a1["tags"]) == ("新译文。", "ii", ["zotero-scholium", "important"])


# --- a plan that no longer fits -------------------------------------------------------------------------------------

def changing(api, key, when=2):
    """The attachment's annotations as read the `when`-th time (the write's own read is the second): `key` changed."""
    real, calls = api.children, []

    def children(k, item_type=None):
        if k == "ATT":
            calls.append(1)
            if len(calls) == when:
                bump(api, key, annotationComment="改了一下。")
        return real(k, item_type)
    return children


@pytest.mark.parametrize("key", ["NEW1", "NEW2"], ids=["changed", "removed"])
def test_the_local_api_refuses_a_plan_whose_annotations_changed_since_the_listing(paper, monkeypatch, capsys, key):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    monkeypatch.setattr(api, "children", changing(api, key))
    plan_set = hl((S1, "该方法在每个基准上都提升了结果。"), (S3, "第三句。"))   # NEW1 changed, NEW2 left out, one added
    code, report = run(paper, monkeypatch, capsys, {"highlights": plan_set, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and "changed since they were read" in report["apply_error"]
    assert api.updated == [] and api.deleted == [] and api.n == 2, "nothing written"


@node
def test_the_plugin_refuses_a_plan_whose_annotations_changed_since_the_listing():
    stale = {"A1": "2026-11-10 09:00:00"}   # the date the listing gave; A1 is now 10:00
    out = zotero(request(updates=[{"key": "A1", "comment": "x"}], keep=["A2"], expect=stale), EXISTING)
    assert "changed since they were read" in out["error"] and out["saves"] == [] and out["erased"] == []
    out = zotero(request(keep=["A1"], remove=["A2"], expect={"A2": "2026-11-10T09:00:00Z"}), EXISTING)
    assert "changed since they were read" in out["error"] and out["erased"] == []
    out = zotero(request(updates=[{"key": "A1", "comment": "x"}], keep=["A2"], expect={"A1": "2026-11-10T10:00:00Z"}), EXISTING)
    assert out["result"]["updatedKeys"] == ["A1"], "the listing's date, in the local API's form, is the same date"


@node
@pytest.mark.parametrize("plan, why", [
    ({"keep": ["A1", "A2"], "remove": ["A2"]}, "named twice"),
    ({"keep": ["A1", "A1", "A2"]}, "named twice"),
], ids=["keep-and-remove", "twice"])
def test_the_plugin_refuses_a_key_named_twice(plan, why):
    out = zotero(request(**plan), EXISTING)
    assert why in out["error"] and out["saves"] == [] and out["erased"] == []


@node
def test_the_plugin_removes_nothing_without_cleanup():
    out = zotero(request(cleanup=False, remove=["A2"]), EXISTING)
    assert "without cleanup" in out["error"] and out["erased"] == []


@node
def test_the_javascript_file_refuses_a_stale_plan_and_removes_external_ones_with_cleanup_external(tmp_path):
    cfg = dict(cli.DEFAULTS, item_key="PARENT01", attachment_key="ATTACH01", cleanup=True)
    plan = {"create": [], "update": [{"key": "A1", "index": 0, "fields": {"comment": "x"}}], "keep": [{"key": "A2", "index": 1}],
            "remove": [], "note": None, "seen": {"A1": {"modified": "2026-11-10 09:00:00"}}}
    out = zotero(script=cli.render_js(cfg, [NEW, NEW], plan), existing=EXISTING)
    assert "changed since they were read" in out["error"] and out["saves"] == []
    # cleanup_external: the plan removes the external one, as the plugin does
    existing = EXISTING + [{"key": "X1", "type": "highlight", "text": "Imported.", "external": True}]
    cfg = dict(cfg, cleanup_external=True)
    plan = {"create": [], "update": [], "keep": [{"key": "A1", "index": 0}, {"key": "A2", "index": 1}], "remove": ["X1"], "note": None}
    out = zotero(script=cli.render_js(cfg, [NEW, NEW], plan), existing=existing)
    assert "error" not in out, out.get("error")
    assert out["erased"] == ["X1"] and "U1" in by_key(out)
    out = zotero(script=cli.render_js(dict(cfg, cleanup_external=False), [NEW, NEW], plan), existing=existing)
    assert "is not one of the tool's" in out["error"]


def test_a_dry_run_against_a_plugin_that_cannot_update_shows_what_it_will_do(paper, monkeypatch, capsys):
    listing = {"ok": True, "backend": "plugin", "version": "0.2.2", "notes": [], "annotations": [
        {"key": "OLD1", "type": "highlight", "tags": ["zotero-scholium"], "text": S1, "comment": "旧。", "color": "#ffd400", "pageLabel": "1",
         "position": {"pageIndex": 0, "rects": [[72, 110, 400, 125]]}}]}
    monkeypatch.setattr(cli, "pick_backend", lambda *a: ("plugin", "TOKEN", "test plugin"))
    monkeypatch.setattr(cli, "plugin_list", lambda cfg: (listing, None))
    tmp, pdf = paper
    (tmp / "config.json").write_text(json.dumps({"pdf": pdf, "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(tmp / "out"),
                                                 "preview_pages": [], "highlights": FIRST[:1], "cleanup": True}), encoding="utf8")
    try:
        cli.main(["--config", str(tmp / "config.json")])
    except SystemExit:
        pass
    report = json.loads(capsys.readouterr().out)
    assert "rewrite" not in report and report["cleanup_removes"] == 1, "a plugin without canUpdate deletes and creates"
    listing["canUpdate"] = True
    try:
        cli.main(["--config", str(tmp / "config.json")])
    except SystemExit:
        pass
    assert json.loads(capsys.readouterr().out)["rewrite"]["removed"] == 0
