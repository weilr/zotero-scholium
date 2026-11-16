"""Figures and tables found by their captions (find_figures): the caption with the drawing or image beside it (a figure)
or the rows and rules under it (a table), in its own column; a sentence that mentions a figure is no caption. The
labels a configuration may give (figure_label), and the index line extract writes. PDFs are made here with PyMuPDF."""
import pymupdf
import pytest

from zotero_scholium import cli

BODY = "The method is trained on every benchmark and evaluated on the held out split."


def save(doc, tmp_path, name="f.pdf"):
    path = tmp_path / name
    doc.save(path)
    return str(path)


def contains(outer, inner, tol=0.5):
    return outer[0] <= inner[0] + tol and outer[1] <= inner[1] + tol and outer[2] >= inner[2] - tol and outer[3] >= inner[3] - tol


@pytest.fixture
def figure_pdf(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()   # 612 x 792
    page.insert_text((72, 70), BODY, fontsize=10)
    page.draw_rect(pymupdf.Rect(150, 100, 450, 250), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    page.insert_text((150, 270), "Figure 1: Results on all benchmarks.", fontsize=9)
    page.insert_text((72, 330), "As Figure 1 shows, " + BODY, fontsize=10)
    page.insert_text((72, 350), "Figure 1 shows the pipeline we use in every experiment.", fontsize=10)
    return save(doc, tmp_path)


def test_a_figure_is_its_caption_and_the_drawing_above_it(figure_pdf):
    found = cli.find_figures(pymupdf.open(figure_pdf))
    assert [(f["kind"], f["number"], f["page"]) for f in found] == [("figure", "1", 1)], "a sentence that mentions it is no caption"
    r = found[0]["rect"]
    assert contains(r, [150, 100, 450, 250]) and r[3] >= 270 - 1, r     # the drawing and the caption's line
    assert r[1] > 75 and r[3] < 320, r                                   # not the body text above or below


def test_a_table_is_its_caption_and_the_rows_and_rules_under_it(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((100, 100), "Table 2. Accuracy on the test set.", fontsize=9)
    for y in (110, 125, 185):
        page.draw_line(pymupdf.Point(100, y), pymupdf.Point(500, y), color=(0, 0, 0), width=0.6)
    page.insert_text((110, 121), "Method      Accuracy", fontsize=8)
    for i, y in enumerate((140, 155, 170, 181)):
        page.insert_text((110, y), f"Model {i}      {80 + i}.0", fontsize=8)
    page.insert_text((72, 230), BODY, fontsize=10)
    found = cli.find_figures(pymupdf.open(save(doc, tmp_path)))
    assert [(f["kind"], f["number"]) for f in found] == [("table", "2")]
    r = found[0]["rect"]
    assert r[1] <= 92 and r[3] >= 185 and r[3] < 215, r                  # caption to the bottom rule, not the next paragraph
    assert r[0] <= 100 and r[2] >= 500


def test_a_figure_in_the_right_column_stays_there(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    for y in range(80, 400, 14):
        page.insert_text((50, y), "Left column text that runs down", fontsize=9)
    page.draw_rect(pymupdf.Rect(330, 100, 560, 240), color=(0, 0, 0), fill=(0.7, 0.7, 0.9))
    page.insert_text((330, 258), "Figure 2: The right column's figure.", fontsize=9)
    found = cli.find_figures(pymupdf.open(save(doc, tmp_path)))
    assert [(f["kind"], f["number"]) for f in found] == [("figure", "2")]
    r = found[0]["rect"]
    assert r[0] >= 320 and contains(r, [330, 100, 560, 240]), r


def test_the_same_label_on_two_pages_is_found_twice(tmp_path):
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(150, 100, 450, 250), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
        page.insert_text((150, 270), "Figure 3: Again.", fontsize=9)
    found = cli.find_figures(pymupdf.open(save(doc, tmp_path)))
    assert [(f["number"], f["page"]) for f in found] == [("3", 1), ("3", 2)]


def test_labels():
    for s in ("Figure 3", "Fig. 3", "fig 3", "FIG. 3", "图 3", "图3"):
        assert cli.figure_label(s) == ("figure", "3"), s
    assert cli.figure_label("Table S1") == ("table", "S1") and cli.figure_label("表 2") == ("table", "2")
    assert cli.figure_label("Table A.2") == ("table", "A.2") and cli.figure_label("Figure 3: x") is None
    assert cli.figure_label("Section 3") is None
    for sentence in ("Fig. 6 (middle) shows the behaviors.", "Figure 1 shows the pipeline.", "As Figure 2 shows, it works."):
        assert not cli.CAPTION_RE.match(sentence), sentence
    for caption in ("Figure 1: Results.", "Fig. 3. Overview", "Table 2 | Accuracy", "Table 4 Accuracy of", "图 3：结果"):
        assert cli.CAPTION_RE.match(caption), caption


def test_extract_lists_them_in_its_index(figure_pdf, tmp_path):
    out = tmp_path / "s.txt"
    assert cli.extract_main(["--pdf", figure_pdf, "--sentences", str(tmp_path / "s.json"), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf8")
    assert "\nfigures: p.1 Figure 1\n" in text
    pages = [l for l in text.splitlines() if l.startswith("pages: ")][0]
    first = int(pages.split()[-1])                  # the line the index says page 1 starts at
    assert text.splitlines()[first - 1].startswith("--- p.1")
