"""What a run checks before it writes, what it reports, and how it treats the tool's earlier notes."""
import json

import pymupdf
import pytest

from zotero_scholium import cli

SENTENCE = "The method improves the result on every benchmark."


def note_row(key, html, tags=()):
    return {"key": key, "version": 7, "data": {"itemType": "note", "parentItem": "ITEM", "note": html, "version": 7,
                                               "tags": [{"tag": t} for t in tags]}}


def ann_row(key, tags=(), kind="highlight", text=SENTENCE, comment="", page=0):
    return {"key": key, "data": {"itemType": "annotation", "parentItem": "ATT", "annotationType": kind, "annotationText": text,
                                 "annotationComment": comment, "annotationColor": "#ffd400", "annotationPageLabel": str(page + 1),
                                 "annotationPosition": json.dumps({"pageIndex": page, "rects": [[60, 690, 400, 740]]}),   # over the sentence
                                 "tags": [{"tag": t} for t in tags]}}


class Api:
    """An in-memory local API: rows by key; created items get keys NEW1, NEW2, …"""

    def __init__(self, rows=()):
        self.rows = {r["key"]: r for r in rows}
        self.trashed, self.deleted, self.n = [], [], 0

    def children(self, key, item_type=None):
        return [r for r in self.rows.values() if r["data"]["parentItem"] == key and (not item_type or r["data"]["itemType"] == item_type)]

    def create(self, items):
        keys = []
        for item in items:
            self.n += 1
            keys.append(f"NEW{self.n}")
            self.rows[keys[-1]] = {"key": keys[-1], "data": dict(item, parentItem=item.get("parentItem"))}
        return keys, []

    def delete(self, keys):
        self.deleted += keys
        for k in keys:
            self.rows.pop(k)
        return len(keys)

    def trash(self, rows):
        self.trashed += [r["key"] for r in rows]
        return len(rows)


def cfg(**over):
    return dict(cli.DEFAULTS, item_key="ITEM", attachment_key="ATT", **over)


# --- the tool's earlier notes ----------------------------------------------------------------------------

def test_note_replace_trashes_the_tools_notes_and_leaves_the_users(tmp_path):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>The new note.</p>", encoding="utf8")
    api = Api([note_row("OWN", "<h1>Paper</h1><p>Earlier.</p>", ["zotero-scholium"]),
               note_row("LEGACY", "<h1>Paper (v2, 2026-09-01)</h1><p>Retry.</p>", ["zotero-paper-annotate"]),
               note_row("USER", "<h1>Paper</h1><p>Mine.</p>")])
    result = cli.api_apply(cfg(note_html=str(note), note_replace=True, note_title_prefix="Paper"), [], api)
    assert result["ok"] and result["noteCreated"] and result["notesTrashed"] == 2
    assert api.trashed == ["OWN", "LEGACY"] and api.deleted == [], "to the trash, never erased; the user's note stays"
    new = api.rows[result["noteKeys"][0]]["data"]["note"]
    assert "(v2," in new, "versioned against the user's note, which stays, not against the trashed ones"
    api = Api([note_row("OWN", "<h1>Paper</h1><p>Earlier.</p>", ["zotero-scholium"])])
    result = cli.api_apply(cfg(note_html=str(note)), [], api)
    assert result["notesTrashed"] == 0 and api.trashed == [], "without note_replace nothing goes"


def test_a_note_with_the_same_text_is_not_written_again(tmp_path):
    note = tmp_path / "note.html"
    note.write_text("﻿<h1>Paper</h1><p>The same &amp; note.</p>", encoding="utf8")   # a byte-order mark is dropped
    api = Api([note_row("SAME", '<div data-schema-version="9"><h1>Paper (v2, 2026-10-16)</h1><p>The same &amp; note.</p></div>',
                        ["zotero-scholium"]),
               note_row("OLD", "<h1>Paper</h1><p>Older.</p>", ["zotero-scholium"])])
    result = cli.api_apply(cfg(note_html=str(note), note_replace=True), [], api)
    assert result["ok"] and not result["noteCreated"] and "SAME" in result["noteSkipped"]
    assert api.trashed == ["OLD"] and api.n == 0


def test_local_api_trash_sends_versions_and_reports_failures(monkeypatch):
    sent = []

    def http(method, path, body=None, headers=None, timeout=60):
        sent.append((method, path, body))
        failed = {"0": {"message": "locked"}} if body and body[0]["key"] == "BAD" else {}
        return 200, {}, json.dumps({"successful": {}, "failed": failed})
    monkeypatch.setattr(cli, "http", http)
    api = cli.LocalApi("SID")
    api.key = "K"
    assert api.trash([note_row("N1", "x")]) == 1
    assert sent[-1] == ("POST", "/api/users/0/items", [{"key": "N1", "version": 7, "deleted": True}])
    with pytest.raises(RuntimeError, match="trash"):
        api.trash([note_row("BAD", "x")])


# --- the report and the checks before --apply ---------------------------------------------------------------

@pytest.fixture
def paper(tmp_path):
    pdf = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 120), SENTENCE)
        doc.save(pdf)
    return tmp_path, str(pdf)


def run(paper, monkeypatch, capsys, config, *args, api=None, raw=None):
    tmp, pdf = paper
    path = tmp / "config.json"
    data = dict({"pdf": pdf, "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(tmp / "out"), "preview_pages": []}, **config)
    path.write_text(raw if raw is not None else json.dumps(data, ensure_ascii=False), encoding="utf8")
    if api is not None:
        monkeypatch.setattr(cli, "pick_backend", lambda *a: ("api", api, "test API"))
    code = 0
    try:
        cli.main(["--config", str(path), *args])
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    try:
        return code, json.loads(out.out)
    except ValueError:
        return code, out.out + out.err


def test_the_report_says_how_many_annotations_cleanup_removes(paper, monkeypatch, capsys):
    api = Api([ann_row("OWN1", ["zotero-scholium"], text="Another sentence."), ann_row("OWN2", ["zotero-marginalia"], text="More."),
               ann_row("USER")])
    hl = [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。"}]
    _, report = run(paper, monkeypatch, capsys, {"cleanup": True, "highlights": hl}, api=api)
    assert report["cleanup_removes"] == 2
    _, report = run(paper, monkeypatch, capsys, {"highlights": hl}, api=api)
    assert report["cleanup_removes"] == 0, "cleanup is off by default"


def test_writing_the_same_text_again_is_a_blocking_duplicate(paper, monkeypatch, capsys):
    api = Api([ann_row("OWN1", ["zotero-scholium"])])
    hl = [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。"}]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--apply", api=api)
    kinds = [w["kind"] for w in report["style_warnings"]]
    assert kinds == ["duplicate_existing"] and "OWN1" in report["style_warnings"][0]["reason"]
    assert code == 2 and report["applied"] is False and "duplicate_existing" in report["apply_error"]
    _, report = run(paper, monkeypatch, capsys, {"highlights": hl, "cleanup": True}, api=api)
    assert report["style_warnings"] == [], "a redo replaces the earlier annotation"
    api = Api([ann_row("USER")])
    _, report = run(paper, monkeypatch, capsys, {"highlights": hl}, api=api)
    assert [w["kind"] for w in report["style_warnings"]] == ["user_overlap"], "the user's own highlight is no duplicate"


def test_a_listing_that_cut_the_text_still_names_the_duplicate():
    long = "We minimise 𝔼[ℒ(𝑥)] over 𝒪(n) samples drawn from the training set and report the error on held-out data."
    utf16_cut = long.encode("utf-16-le")[:160].decode("utf-16-le", "ignore")   # the plugin's slice(0, 80)
    listing = {"annotations": [{"key": "OWN1", "type": "highlight", "tags": ["zotero-scholium"], "text": utf16_cut,
                                "position": {"pageIndex": 0, "rects": [[60, 690, 400, 740]]}},
                               {"key": "OWN2", "type": "text", "tags": ["zotero-scholium"], "comment": "Short note.",
                                "position": {"pageIndex": 0, "rects": [[500, 690, 590, 740]]}}]}
    new = [{"type": "highlight", "text": long, "comment": "", "pageLabel": "1", "position": {"pageIndex": 0, "rects": [[60, 690, 400, 740]]}},
           {"type": "text", "comment": "Short note. And more.", "pageLabel": "1", "position": {"pageIndex": 0, "rects": [[500, 600, 590, 650]]}}]
    kinds = [(w["kind"], w["text"][:5]) for w in cli.check_style(new, cfg(), listing)]
    assert ("duplicate_existing", "We mi") in kinds, "the cut text is recognised"
    assert not any(k == "duplicate_existing" and t == "Short" for k, t in kinds), "a short complete text is no cut prefix"


def test_accept_lets_a_deliberate_exception_through_and_core_count_only_informs(paper, monkeypatch, capsys):
    api = Api([ann_row("USER")])
    hl = [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。", "core": True}]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "core_range": [10, 15]}, "--apply", api=api)
    assert {w["kind"] for w in report["style_warnings"]} == {"user_overlap", "core_count"}
    assert report["applied"] is False and "user_overlap" in report["apply_error"] and "core_count" not in report["apply_error"]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "core_range": [10, 15]}, "--apply", "--accept", "user_overlap",
                       api=api)
    assert code == 0 and report["applied"] is True
    assert list(report)[-1] == "applied", "the outcome is the last field"
    keys = json.load(open(report["result"]["keys"], encoding="utf8"))
    assert keys["createdKeys"] == ["NEW1"] and "createdKeys" not in report["result"]


@pytest.mark.parametrize("config, fragment", [
    ({"clean_up": True}, "unknown key 'clean_up' (did you mean 'cleanup'?)"),
    ({"highlights": [{"page": 1, "text": SENTENCE, "comentt": "x"}]}, "unknown key 'comentt' in highlights[0] (did you mean 'comment'?)"),
    ({"highlights": [{"page": 1, "text": SENTENCE, "level": "claim"}]}, "highlights[0]: unknown level 'claim' (levels: none defined)"),
    ({"highlights": [{"page": 1, "text": SENTENCE, "type": "squiggly"}]}, "highlights[0]: type must be highlight or underline"),
    ({"summaries": [{"page": 1, "place": "top", "text": "t", "fontsize": 9}]}, "unknown key 'fontsize' in summaries[0] (did you mean 'font_size'?)"),
    ({"author": "Me"}, "the 'author' key is not supported"),
    ({"band_min_font_size": 0}, "band_min_font_size must be a number between 4 and 36"),
    ({"band_min_font_size": "8"}, "band_min_font_size must be a number between 4 and 36"),
    ({"highlights": [{"page": 0, "text": SENTENCE}]}, "highlights[0]: give id, ids, or a 1-based page with text"),
    ({"highlights": [{"page": 1}]}, "highlights[0]: give id, ids, or text with its page"),
    ({"highlights": [{"text": SENTENCE}]}, "highlights[0]: give id, ids, or a 1-based page with text"),
    ({"highlights": [{"ids": [5]}]}, "highlights[0]: ids must be [first, last], two sentence numbers in order"),
    ({"highlights": [{"ids": [5, 3]}]}, "highlights[0]: ids must be [first, last], two sentence numbers in order"),
    ({"highlights": [{"id": "5"}]}, "highlights[0]: id must be a sentence number"),
    ({"highlights": [{"id": 5, "occurrence": "first"}]}, "highlights[0]: occurrence must be a number from 1"),
    ({"highlights": [{"id": 5, "comment": 5}]}, "highlights[0]: comment must be text"),
    ({"highlights": [{"id": 5, "color": "red"}]}, "highlights[0]: color must be a #rrggbb colour"),
    ({"core_color": "red"}, "core_color must be a #rrggbb colour"),
    ({"levels": {"claim": "#f00"}}, "levels: 'claim' must be a #rrggbb colour"),
])
def test_configuration_mistakes_are_refused(paper, monkeypatch, capsys, config, fragment):
    code, out = run(paper, monkeypatch, capsys, config)
    assert fragment in str(code), "the run ends with the reason"


def test_a_configuration_written_with_a_byte_order_mark_is_read(paper, monkeypatch, capsys):
    tmp, pdf = paper
    raw = "﻿" + json.dumps({"pdf": pdf, "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(tmp / "out"),
                                 "preview_pages": [], "highlights": [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。"}]})
    code, report = run(paper, monkeypatch, capsys, {}, "--ignore-existing", raw=raw)
    assert code == 0 and report["highlights"] == 1


def test_a_failed_read_of_the_attachment_is_reported_not_raised(paper, monkeypatch, capsys):
    class Broken(Api):
        def children(self, key, item_type=None):
            raise RuntimeError("failed to read children (HTTP 403): forbidden")
    hl = [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。"}]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, api=Broken())
    assert code == 0 and "HTTP 403" in report["existing_annotations"]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--list", api=Broken())
    assert code == 1 and "HTTP 403" in report["error"]
    # without the annotations already there, a retry could write everything twice: --apply waits
    broken = Broken()
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--apply", api=broken)
    assert code == 2 and report["applied"] is False and "could not be read (failed to read children (HTTP 403)" in report["apply_error"]
    assert "or pass --ignore-existing" in report["apply_error"]
    assert broken.n == 0, "nothing was written"
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "cleanup": True}, "--apply", api=broken)
    assert code == 2 and "could not be read" in report["apply_error"] and "--ignore-existing" not in report["apply_error"]
    assert broken.n == 0


def test_a_redo_is_not_applied_without_reading_the_attachment(paper, monkeypatch, capsys):
    """--ignore-existing skips the listing the user_edit check reads: with cleanup: true --apply refuses it."""
    api = Api([ann_row("OWN1", ["zotero-scholium"], text="Another sentence.")])
    hl = [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。"}]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "cleanup": True}, "--apply", "--ignore-existing", api=api)
    assert code == 2 and report["applied"] is False and "backend" not in report
    assert "--ignore-existing cannot be combined with cleanup: true" in report["apply_error"]
    assert api.n == 0 and api.deleted == [], "nothing was written or removed"
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "cleanup": True}, "--apply", api=api)
    assert code == 0 and report["applied"] is True and api.deleted == ["OWN1"]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--apply", "--ignore-existing", api=Api())
    assert code == 0 and report["applied"] is True, "without cleanup --ignore-existing still writes"


def test_no_preview_is_rendered_unless_pages_are_named(paper, monkeypatch, capsys):
    tmp, pdf = paper
    hl = [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。"}]
    raw = json.dumps({"pdf": pdf, "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(tmp / "out"), "highlights": hl})
    code, report = run(paper, monkeypatch, capsys, {}, "--ignore-existing", raw=raw)
    assert code == 0 and "previews" not in report and not list((tmp / "out").glob("preview_*.png"))
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "preview_pages": [1, 9]}, "--ignore-existing")
    assert report["previews"] == [str(tmp / "out" / "preview_p1.png")], "a page outside the document is not rendered"


# --- commands --------------------------------------------------------------------------------------------------

def test_profile_path_prints_the_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "zotero_data_dir", lambda cfg=None: str(tmp_path))
    cli.main(["profile", "--path"])
    out = capsys.readouterr()
    assert out.out.strip() == str(tmp_path / "zotero-scholium" / "profile.md") and "does not exist" in out.err
    cli.main(["profile", "--path", "--json"])
    assert json.loads(capsys.readouterr().out)["exists"] is False


def test_the_javascript_fallback_names_why_each_channel_was_unavailable(monkeypatch):
    monkeypatch.setattr(cli, "zotero_version", lambda: ("9.0.1", "SID"))
    monkeypatch.setattr(cli, "plugin_connect", lambda cfg: (None, "Scholium plugin is not installed (HTTP 404)", None))
    name, _, why = cli.pick_backend("auto", {})
    assert name == "js" and "read-only before Zotero 10" in why and "HTTP 404" in why
    monkeypatch.setattr(cli, "zotero_version", lambda: (None, None))
    monkeypatch.setattr(cli, "plugin_connect", lambda cfg: (None, "Zotero is not running or its local server is disabled (refused)", None))
    name, _, why = cli.pick_backend("auto", {})
    assert why.count("Zotero is not running") == 1


def test_auto_writes_through_a_recent_plugin_and_otherwise_through_the_local_api(monkeypatch):
    monkeypatch.setattr(cli, "zotero_version", lambda: ("10.0.6", "SID"))
    for plugin, expected in (("0.1.9", "plugin"), ("0.2.0.10200001", "plugin"), ("0.1.8", "api"), (None, "api")):
        listing = {"ok": True, "annotations": [], "notes": []}
        if plugin:
            listing["version"] = plugin
        monkeypatch.setattr(cli, "plugin_connect", lambda cfg, listing=listing: ("TOKEN", listing, "/scholium"))
        name, handle, why = cli.pick_backend("auto", {})
        assert name == expected, plugin
        assert (handle, why) == ("TOKEN", f"Scholium plugin {plugin}") if expected == "plugin" else why.startswith("Zotero 10.0.6")
    # on Zotero 9 an older plugin is the only write channel
    monkeypatch.setattr(cli, "zotero_version", lambda: ("9.0.1", "SID"))
    assert cli.pick_backend("auto", {})[0] == "plugin"
    monkeypatch.setattr(cli, "plugin_connect", lambda cfg: pytest.fail("the plugin is not asked when the local API is requested"))
    monkeypatch.setattr(cli, "zotero_version", lambda: ("10.0.6", "SID"))
    assert cli.pick_backend("api", {})[0] == "api"


def test_the_plugins_keys_are_kept_and_checked_after_writing(paper, monkeypatch, capsys):
    hl = [{"page": 1, "text": SENTENCE, "comment": "该方法提升了结果。"}]
    monkeypatch.setattr(cli, "pick_backend", lambda *a: ("plugin", "TOKEN", "Scholium plugin 0.1.9"))
    listing = {"ok": True, "version": "0.1.9", "annotations": [], "notes": []}
    monkeypatch.setattr(cli, "plugin_list", lambda cfg: (listing, None))
    result = {"ok": True, "removed": 0, "kept": 0, "noteCreated": False, "created": {"highlight": 1}, "createdKeys": ["NEW1"], "noteKeys": []}
    monkeypatch.setattr(cli, "plugin_apply", lambda cfg, out: (result, None))
    listing["annotations"] = [{"key": "NEW1", "tags": ["zotero-scholium"]}]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--apply", "--ignore-existing")
    assert code == 0 and report["applied"] is True and report["verification"] == {"missing_annotations": [], "missing_notes": []}
    tmp, _ = paper
    assert json.loads((tmp / "out" / "applied_keys.json").read_text(encoding="utf8"))["createdKeys"] == ["NEW1"]
    listing["annotations"] = []
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--apply", "--ignore-existing")
    assert code == 2 and report["verification"]["missing_annotations"] == ["NEW1"] and "verification failed" in report["apply_error"]
    # a plugin before 0.1.9 returns no keys: its write is checked by the listing alone
    del result["createdKeys"], result["noteKeys"]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--apply", "--ignore-existing")
    assert code == 0 and report["applied"] is True and "verification" not in report
    # the earlier notes could not go to the trash: the new items are there
    listing["annotations"] = [{"key": "NEW1", "tags": ["zotero-scholium"]}]
    result.update(createdKeys=["NEW1"], noteKeys=[], removeError="the trash is not available")
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl}, "--apply", "--ignore-existing")
    assert code == 2 and report["applied"] == "partial" and "the trash is not available" in report["apply_error"]


def test_an_older_plugin_says_it_left_the_earlier_notes(tmp_path, monkeypatch):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>New.</p>", encoding="utf8")
    monkeypatch.setattr(cli, "plugin_connect", lambda c: ("TOKEN", {"ok": True, "annotations": [], "notes": []}, "/scholium"))
    answer = {"ok": True, "removed": 0, "kept": 0, "noteCreated": True, "created": {}}   # a plugin before 0.1.9
    monkeypatch.setattr(cli, "http", lambda *a, **k: (200, {}, json.dumps(answer)))
    res, err = cli.plugin_apply(cfg(note_html=str(note), note_replace=True), [])
    assert err is None and "install Scholium" in res["noteReplace"]
    answer["notesTrashed"] = 1
    res, err = cli.plugin_apply(cfg(note_html=str(note), note_replace=True), [])
    assert "noteReplace" not in res


def test_status_gives_what_a_citation_line_needs():
    item = {"key": "I1", "data": {"title": "A Paper", "date": "2025-03-01", "proceedingsTitle": "ICLR 2025", "DOI": "10.1/x",
                                  "url": "https://x.org", "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
                                                                       {"creatorType": "editor", "lastName": "Editor"},
                                                                       {"creatorType": "author", "name": "Team X"}]}}
    assert cli.citation(item) == {"key": "I1", "title": "A Paper", "year": "2025", "authors": ["Ada Lovelace", "Team X"],
                                  "date": "2025-03-01", "venue": "ICLR 2025", "doi": "10.1/x", "url": "https://x.org"}
    many = {"key": "I2", "data": {"title": "T", "creators": [{"creatorType": "author", "lastName": f"A{i}"} for i in range(15)]}}
    assert cli.citation(many)["authors"][-1] == "… 3 more" and len(cli.citation(many)["authors"]) == 13


def test_without_pymupdf_the_commands_that_need_it_say_how_to_install_it(paper, monkeypatch, capsys):
    monkeypatch.setattr(cli, "pymupdf", None)
    tmp, pdf = paper
    with pytest.raises(SystemExit) as e:
        cli.main(["extract", "--pdf", pdf])
    assert "pip install -U pymupdf" in str(e.value.code)
    code, out = run(paper, monkeypatch, capsys, {})
    assert "pip install -U pymupdf" in str(code)


def test_extract_says_how_long_the_listing_is(paper, capsys):
    tmp, pdf = paper
    cli.main(["extract", "--pdf", pdf, "--sentences", str(tmp / "s.json"), "--out", str(tmp / "s.txt")])
    line = capsys.readouterr().out
    text = (tmp / "s.txt").read_text(encoding="utf8")
    assert f"{text.count(chr(10))} lines, {len(text)} characters" in line


def test_text_lines_are_read_without_decoding_the_pages_images(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), SENTENCE)
    page.insert_image(pymupdf.Rect(72, 100, 272, 300), pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 400), 0))
    page.insert_text((72, 330), "Figure 1: a caption under the image.")
    with_images = page.get_text("dict")["blocks"]
    assert any("image" in b for b in with_images)
    blocks = cli.text_lines(page)
    assert not any("image" in b for b in blocks)
    lines = lambda bs: sorted(("".join(s["text"] for s in l["spans"]), tuple(l["bbox"])) for b in bs for l in b.get("lines", []))
    assert lines(blocks) == lines(with_images)
    index = cli.PageIndex(page)
    assert index.blocks() is index.blocks()   # read once per page


def test_a_page_beyond_the_end_is_missed_not_raised(paper, monkeypatch, capsys):
    code, report = run(paper, monkeypatch, capsys, {"highlights": [{"page": 9, "text": SENTENCE, "comment": "x"}]}, "--ignore-existing")
    assert code == 2 and "page 9 is outside the document (1 pages)" in report["missed"][0]["reason"]
