"""`scholium status` and `scholium samples` against a simulated local API: a paper's current state before a
configuration is written, and short style examples from the tool's earlier annotations."""
import json
import os

import pytest

from zotero_scholium import cli


def row(key, item_type, parent=None, tags=(), **data):
    data.update(itemType=item_type, tags=[{"tag": t} for t in tags])
    if parent:
        data["parentItem"] = parent
    return {"key": key, "data": data}


def ann(key, parent, kind, color, sort, tags=("zotero-scholium",), text="", comment="", modified="2026-10-01"):
    return row(key, "annotation", parent, tags, annotationType=kind, annotationColor=color, annotationSortIndex=sort,
               annotationText=text, annotationComment=comment, annotationPageLabel=sort[:1], dateModified=modified)


LIBRARY = [
    row("I1", "journalArticle", title="Paper One", date="2025-03-01"),
    row("A1", "attachment", "I1", contentType="application/pdf", filename="one.pdf", linkMode="imported_file"),
    row("A2", "attachment", "I1", contentType="application/pdf", path="D:/papers/one-preprint.pdf", linkMode="linked_file"),
    row("H1", "attachment", "I1", contentType="text/html", filename="page.html"),
    row("N1", "note", "I1", ("zotero-scholium",), note="<h1>Paper One — reading note</h1><p>" + "Findings. " * 200 + "</p>",
        dateModified="2026-10-02T08:00:00Z"),
    row("N0", "note", "I1", ("zotero-scholium",), note="<h1>Older note</h1><p>old</p>", dateModified="2026-09-01T08:00:00Z"),
    row("N2", "note", "I1", (), note="<p>My own thoughts</p>", dateModified="2026-10-03T08:00:00Z"),
    ann("X1", "A1", "highlight", "#ff6666", "1|1", text="We propose a method.", comment="我们提出一种方法。"),
    ann("X2", "A1", "highlight", "#ff6666", "2|1", text="It is fast.", comment="它很快。"),
    ann("X3", "A1", "highlight", "#ffd400", "3|1", text="Setup details.", comment="实验设置细节。"),
    ann("X4", "A1", "text", "#1a73e8", "1|0", comment="首页总结：本文提出一种方法。"),
    ann("X5", "A1", "highlight", "#5fb236", "4|1", tags=(), text="Mine.", comment=""),
    row("I2", "journalArticle", title="Paper Two", date="2024"),
    row("A3", "attachment", "I2", contentType="application/pdf", filename="two.pdf"),
    ann("Y1", "A3", "highlight", "#ff6666", "1|1", text="Two claims.", comment="两个结论。", modified="2026-10-03"),
    row("N3", "note", "I2", ("zotero-scholium",), note="<h1>Paper Two</h1><p>Second note.</p>", dateModified="2026-10-03T08:00:00Z"),
    row("I3", "journalArticle", title="Paper Three"),
]


@pytest.fixture
def zotero(monkeypatch, tmp_path):
    """The local API over LIBRARY; records every path read."""
    rows = {r["key"]: r for r in LIBRARY}
    asked = []

    def http(method, path, body=None, headers=None, timeout=60):
        assert method == "GET", "status and samples only read"
        asked.append(path)
        path, _, query = path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if p)
        parts = path.split("/")[4:]          # /api/users/0/items/...
        if parts == ["items", "top"]:
            words = cli.urllib.parse.unquote(params["q"]).lower()
            hits = [r for r in LIBRARY if "parentItem" not in r["data"] and r["data"]["itemType"] not in ("note",)
                    and words in r["data"].get("title", "").lower()]
            return 200, {}, json.dumps(hits)
        if parts == ["items"]:               # the tool's annotations, most recently changed first
            hits = sorted((r for r in LIBRARY if r["data"]["itemType"] == params.get("itemType")
                           and params.get("tag") in [t["tag"] for t in r["data"]["tags"]]),
                          key=lambda r: r["data"]["dateModified"], reverse=True)
            start, limit = int(params.get("start", 0)), int(params["limit"])
            return 200, {}, json.dumps(hits[start:start + limit])
        if len(parts) == 2 and parts[0] == "items":
            return (200, {}, json.dumps(rows[parts[1]])) if parts[1] in rows else (404, {}, "Not found")
        if len(parts) == 3 and parts[2] == "children":
            kids = [r for r in LIBRARY if r["data"].get("parentItem") == parts[1]]
            if "itemType" in params:
                kids = [r for r in kids if r["data"]["itemType"] == params["itemType"]]
            return 200, {}, json.dumps(kids)
        return 404, {}, "Not found"

    monkeypatch.setattr(cli, "http", http)
    monkeypatch.setattr(cli, "zotero_data_dir", lambda cfg=None: str(tmp_path))
    (tmp_path / "storage" / "A1").mkdir(parents=True)
    (tmp_path / "storage" / "A1" / "one.pdf").write_bytes(b"%PDF")
    return asked


def run(capsys, *argv):
    with pytest.raises(SystemExit) as end:
        cli.main(list(argv))
    return json.loads(capsys.readouterr().out), end.value.code


def test_status_shows_the_pdfs_annotations_and_notes(zotero, capsys, tmp_path):
    for key in ("I1", "A1"):                 # from the item or from one of its PDFs
        out, code = run(capsys, "status", key)
        assert code == 0
        assert out["item"] == {"key": "I1", "title": "Paper One", "year": "2025"}
        a1, a2 = out["pdfs"]
        assert a1 == {"key": "A1", "file": os.path.join(str(tmp_path), "storage", "A1", "one.pdf"), "exists": True, "own": 4, "others": 1,
                      "own_by_type": {"highlight": 3, "text": 1}, "own_by_color": {"#ff6666": 2, "#ffd400": 1, "#1a73e8": 1}}
        assert a2["key"] == "A2" and a2["file"] == "D:/papers/one-preprint.pdf" and a2["own"] == 0
        assert [(n["key"], n["own"]) for n in out["notes"]] == [("N1", True), ("N0", True), ("N2", False)]
        assert out["notes"][0]["title"] == "Paper One — reading note" and out["notes"][0]["characters"] > 1500
        assert out["profile"] == os.path.join(str(tmp_path), "zotero-scholium", "profile.md")


def test_status_lists_matching_items_and_reports_failures(zotero, capsys, monkeypatch):
    out, code = run(capsys, "status", "--query", "paper t")
    assert code == 0 and [m["key"] for m in out["matches"]] == ["I2", "I3"]
    out, code = run(capsys, "status", "NOPE")
    assert code == 1 and "HTTP 404" in out["error"]
    monkeypatch.setattr(cli, "http", lambda *a, **k: (0, {}, "refused"))
    out, code = run(capsys, "status", "I1")
    assert code == 1 and "is it running" in out["error"]


def test_samples_give_a_few_examples_of_other_papers(zotero, capsys):
    out, code = run(capsys, "samples", "--exclude", "A3", "--per-kind", "2")
    assert code == 0
    (paper,) = out["papers"]                 # Paper Two is left out; Paper Three has nothing of the tool
    assert paper["item"] == "I1" and paper["title"] == "Paper One"
    assert [h["comment"] for h in paper["highlights"]] == ["我们提出一种方法。", "实验设置细节。"], "spread over the paper"
    assert paper["margin_and_page_texts"] == [{"page": "1", "text": "首页总结：本文提出一种方法。"}]
    assert paper["note_start"].startswith("Paper One — reading note Findings.") and len(paper["note_start"]) == 700
    assert all(not path.endswith("/items/N2") for path in zotero), "the user's own note is not read for its text"


def test_samples_by_key_or_title_and_most_recent_first(zotero, capsys):
    out, _ = run(capsys, "samples", "--papers", "5")
    assert [p["item"] for p in out["papers"]] == ["I2", "I1"]
    out, _ = run(capsys, "samples", "A3")
    assert [p["item"] for p in out["papers"]] == ["I2"] and out["papers"][0]["note_start"] == "Paper Two Second note."
    out, _ = run(capsys, "samples", "--query", "paper one")
    assert [p["item"] for p in out["papers"]] == ["I1"]
