"""The tool's own tags (a configuration's `tags`) against the user's: the record keeps which tags the tool wrote on each
annotation, so that they are never taken for the user's change, a rewrite in place sets them as the configuration now
has them, and a tag the user added stays. Every run here uses the in-memory local API; nothing reaches a socket."""
from test_rewrite_in_place import S1, S2, UpdatingApi, annotations, paper, record, run  # noqa: F401  (paper: a fixture)


def tagged(*pairs):
    return [{"page": 1, "text": text, "comment": comment, "tags": tags} for text, comment, tags in pairs]


FIRST = tagged((S1, "该方法提升了每个基准上的结果。", ["方法"]), (S2, "另一句话。", []))


def tags_of(api, key):
    return [t["tag"] for t in annotations(api)[key]["tags"]]


def test_the_record_keeps_the_tools_tags_and_they_are_no_change_of_the_users(paper, monkeypatch, capsys):
    api = UpdatingApi()
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    assert report["applied"] is True and tags_of(api, "NEW1") == ["zotero-scholium", "方法"]
    assert record(paper)["written"]["NEW1"]["tags"] == ["方法"] and record(paper)["written"]["NEW2"]["tags"] == []
    code, again = run(paper, monkeypatch, capsys, {"highlights": FIRST, "cleanup": True}, "--apply", api=api)
    assert again["applied"] is True and again["rewrite"] == {"created": 0, "updated": 0, "kept": 2, "removed": 0}
    assert "user_edit" not in [w["kind"] for w in again.get("style_warnings", [])]


def changed(paper, monkeypatch, capsys, api, config):
    """What `--list` says the user changed in the tool's annotations: {key: words}."""
    code, listed = run(paper, monkeypatch, capsys, config, "--list", api=api)
    return {c["key"]: c.get("changes", "") for c in listed.get("changed_by_user", [])}


def user_edits(report):
    return [w["reason"] for w in report.get("style_warnings", []) if w["kind"] == "user_edit"]


def test_a_tag_the_user_added_is_theirs_and_the_tools_tags_change_around_it(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    row = api.rows["NEW1"]["data"]
    row.update(tags=row["tags"] + [{"tag": "重要"}], dateModified="2026-11-10T13:00:00Z", version=2)
    said = changed(paper, monkeypatch, capsys, api, {"highlights": FIRST})
    assert set(said) == {"NEW1"} and "重要" in said["NEW1"] and "方法" not in said["NEW1"]
    # the configuration's tags change: only the tool's change, the user's tag stays, and that needs no confirmation
    retagged = tagged((S1, "该方法提升了每个基准上的结果。", ["结果"]), (S2, "另一句话。", []))
    code, report = run(paper, monkeypatch, capsys, {"highlights": retagged, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and report["rewrite"] == {"created": 0, "updated": 1, "kept": 1, "removed": 0}
    assert user_edits(report) == []
    assert sorted(tags_of(api, "NEW1")) == sorted(["zotero-scholium", "结果", "重要"])
    assert record(paper)["written"]["NEW1"]["tags"] == ["结果"]


def test_deleting_an_annotation_with_only_the_tools_tags_is_no_users_change(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIRST[1:], "cleanup": True}, "--apply", api=api)
    assert report["applied"] is True and user_edits(report) == [] and api.deleted == ["NEW1"]


def test_a_tool_tag_the_user_removed_is_their_change(paper, monkeypatch, capsys):
    api = UpdatingApi()
    run(paper, monkeypatch, capsys, {"highlights": FIRST}, "--apply", api=api)
    row = api.rows["NEW1"]["data"]
    row.update(tags=[{"tag": "zotero-scholium"}], dateModified="2026-11-10T13:00:00Z", version=2)
    said = changed(paper, monkeypatch, capsys, api, {"highlights": FIRST})
    assert "removed the tag “方法”" in said.get("NEW1", "")
    # putting it back would undo that: the rewrite asks first
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIRST, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and any("removed the tag “方法”" in r for r in user_edits(report))


def test_a_record_without_tags_takes_every_other_tag_for_the_users(paper, monkeypatch, capsys):
    api = UpdatingApi()
    plain = [{"page": 1, "text": S1, "comment": "该方法提升了每个基准上的结果。"}]
    run(paper, monkeypatch, capsys, {"highlights": plain}, "--apply", api=api)
    r = record(paper)
    for v in r["written"].values():
        v.pop("tags", None)   # an output folder written before the tool recorded its tags
    (paper[0] / "out" / "applied_keys.json").write_text(__import__("json").dumps(r), encoding="utf8")
    row = api.rows["NEW1"]["data"]
    row.update(tags=row["tags"] + [{"tag": "方法"}], dateModified="2026-11-10T13:00:00Z", version=2)
    assert "方法" in changed(paper, monkeypatch, capsys, api, {"highlights": plain}).get("NEW1", "")
