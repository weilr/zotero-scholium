"""Sentence caches must identify the PDF and never guess an ambiguous passage."""
import hashlib
import json

import pymupdf
import pytest

from zotero_scholium import cli


def make_pdf(path, paragraphs):
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        for index, text in enumerate(paragraphs):
            page.insert_textbox(pymupdf.Rect(72, 100 + index * 120, 540, 200 + index * 120),
                                text, fontsize=10)
        doc.save(path)


def extract_cache(pdf, cache):
    cli.extract_main(["--pdf", str(pdf), "--sentences", str(cache)])
    return json.loads(cache.read_text(encoding="utf8"))


def config(pdf, cache, **content):
    return dict(cli.DEFAULTS, pdf=str(pdf), sentences=str(cache), out_dir=str(cache.parent),
                item_key="ITEM", attachment_key="ATT", preview_pages=[], **content)


@pytest.mark.parametrize("kind", ["highlight", "summary"])
def test_sentence_id_rejects_a_short_sentence_also_inside_a_long_one(tmp_path, kind):
    pdf, cache = tmp_path / "paper.pdf", tmp_path / "sentences.json"
    make_pdf(pdf, ["In this case, the model reduces memory usage.",
                   "The model reduces memory usage."])
    data = extract_cache(pdf, cache)
    selected = next(row for row in data["sentences"] if row["text"] == "The model reduces memory usage.")
    content = ({"highlights": [{"id": selected["id"], "comment": "Less memory."}]}
               if kind == "highlight" else {"summaries": [{"id": selected["id"], "text": "Less memory."}]})
    output, missed = cli.build(config(pdf, cache, **content))
    assert output == [], "a sentence id must not silently select a containing sentence"
    assert len(missed) == 1 and "ambiguous" in missed[0]["reason"]


def test_ambiguous_sentence_id_can_be_resolved_with_explicit_occurrence(tmp_path):
    pdf, cache = tmp_path / "paper.pdf", tmp_path / "sentences.json"
    make_pdf(pdf, ["In this case, the model reduces memory usage.",
                   "The model reduces memory usage."])
    data = extract_cache(pdf, cache)
    selected = next(row for row in data["sentences"] if row["text"] == "The model reduces memory usage.")
    output, missed = cli.build(config(pdf, cache, highlights=[{"id": selected["id"], "occurrence": 2}]))
    assert not missed and len(output) == 1
    assert output[0]["position"]["rects"][0][3] < 600, "select the later paragraph"


def test_repeated_sentence_range_requires_explicit_occurrence(tmp_path):
    pdf, cache = tmp_path / "paper.pdf", tmp_path / "sentences.json"
    make_pdf(pdf, ["The model saves memory. The model trains faster."] * 2)
    extract_cache(pdf, cache)
    output, missed = cli.build(config(pdf, cache, highlights=[{"ids": [3, 4]}]))
    assert output == []
    assert "ambiguous" in missed[0]["reason"]


def test_extraction_stores_the_pdf_fingerprint(tmp_path):
    pdf, cache = tmp_path / "paper.pdf", tmp_path / "sentences.json"
    make_pdf(pdf, ["The model improves the result."])
    data = extract_cache(pdf, cache)
    assert data["pdf_sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()


@pytest.mark.parametrize("invalid_cache", ["changed_pdf", "legacy_cache"])
def test_invalid_cache_blocks_ids_before_matching_or_applying(tmp_path, capsys, invalid_cache):
    pdf, cache = tmp_path / "paper.pdf", tmp_path / "sentences.json"
    start, end = "Our evaluation of the model demonstrates ", " on all evaluated benchmark datasets."
    make_pdf(pdf, [start + "a substantial improvement over the baseline" + end])
    data = extract_cache(pdf, cache)
    if invalid_cache == "changed_pdf":
        make_pdf(pdf, [start + "a significantly lower accuracy than the baseline" + end])
    else:
        data.pop("pdf_sha256", None)
        cache.write_text(json.dumps(data), encoding="utf8")
    cfg = config(pdf, cache, highlights=[{"id": 1, "comment": "Improves accuracy."}])
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf8")
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        cli.main(["--config", str(path), "--apply", "--ignore-existing", "--backend", "js"])
    report = json.loads(capsys.readouterr().out)
    assert exc.value.code == 2 and report["applied"] is False
    assert report["highlights"] == 0
    assert "extract --sentences" in report["missed"][0]["reason"]
    assert "fallback" not in report, "invalid caches must block before backend selection"


@pytest.mark.parametrize("numbered", [True, False])
def test_extract_creates_both_output_parent_directories(tmp_path, numbered):
    pdf = tmp_path / "paper.pdf"
    make_pdf(pdf, ["The model improves the result."])
    cache, listing = tmp_path / "cache" / "ATT" / "sentences.json", tmp_path / "reading" / "ATT" / "text.txt"
    args = ["--pdf", str(pdf), "--out", str(listing)]
    if numbered:
        args += ["--sentences", str(cache)]
    cli.extract_main(args)
    assert "The model improves the result." in listing.read_text(encoding="utf8")
    if numbered:
        assert json.loads(cache.read_text(encoding="utf8"))["sentences"][0]["id"] == 1
