"""regions[]: an image annotation framing a figure or table found by its label (find_figures), or a rectangle given on
a page, with its comment, colour and tags; a label not found, or found on several pages, is missed (no write); every
write channel creates it; a re-apply of the same region keeps it. PDFs are made here; the local API is in memory."""
import json

import pymupdf
import pytest

from zotero_scholium import cli
from test_rewrite_in_place import UpdatingApi, annotations, run   # noqa: F401
from test_plugin_rewrite import NEW, request, zotero

H = pymupdf.paper_size("a4")[1]   # PyMuPDF's new pages are A4


def figure_page(doc, label="Figure 1"):
    page = doc.new_page()
    page.insert_text((72, 70), "The method is trained on every benchmark and evaluated on the held out split.", fontsize=10)
    page.draw_rect(pymupdf.Rect(150, 100, 450, 250), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    page.insert_text((150, 270), f"{label}: Results on all benchmarks.", fontsize=9)
    page.insert_text((72, 330), "A paragraph of the main text follows the figure here.", fontsize=10)


@pytest.fixture
def paper(tmp_path):
    pdf = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        figure_page(doc)
        doc.save(pdf)
    return tmp_path, str(pdf)


def build(paper, **extra):
    tmp, pdf = paper
    cfg = dict(cli.DEFAULTS, pdf=pdf, item_key="ITEM", attachment_key="ATT", out_dir=str(tmp / "out"), preview_pages=[], **extra)
    return cli.build(cfg)


def test_a_figure_by_its_label_is_an_image_annotation_with_its_comment_colour_and_tags(paper):
    out, missed = build(paper, regions=[{"figure": "Fig. 1", "comment": "结果对比", "color": "blue", "tags": ["图表"]}])
    assert missed == []
    (a,) = out
    with pymupdf.open(paper[1]) as doc:
        r = cli.find_figures(doc)[0]["rect"]
    assert a["type"] == "image" and a["comment"] == "结果对比" and a["color"] == "#2ea8e5" and a["tags"] == ["图表"]
    assert a["position"]["pageIndex"] == 0 and a["position"]["rects"] == [[r[0], H - r[3], r[2], H - r[1]]]
    assert a["label"] == "Figure 1" and a["pageLabel"] == "1" and "text" not in a
    assert a["sortIndex"].startswith("00000|")


def test_a_rectangle_on_a_page(paper):
    out, missed = build(paper, regions=[{"page": 1, "rect": [72, 100, 300, 200]}])
    assert missed == [] and out[0]["position"]["rects"] == [[72.0, H - 200.0, 300.0, H - 100.0]]
    assert out[0]["color"] == cli.DEFAULTS["other_color"] and out[0]["comment"] == ""


def test_a_label_not_found_or_on_two_pages_is_missed_and_a_page_picks_one(tmp_path):
    pdf = tmp_path / "two.pdf"
    with pymupdf.open() as doc:
        figure_page(doc, "Figure 3")
        figure_page(doc, "Figure 3")
        doc.save(pdf)
    paper = (tmp_path, str(pdf))
    out, missed = build(paper, regions=[{"figure": "Figure 9"}, {"figure": "Figure 3"}, {"table": "Table 1"}])
    assert out == [] and [m["kind"] for m in missed] == ["region"] * 3
    assert "not found" in missed[0]["reason"] and "pages 1, 2" in missed[1]["reason"] and "page" in missed[1]["reason"]
    out, missed = build(paper, regions=[{"figure": "Figure 3", "page": 2}])
    assert missed == [] and out[0]["position"]["pageIndex"] == 1


def test_mistakes_in_a_region_are_configuration_errors():
    for region, words in (({"figure": "Figure 1", "rect": [0, 0, 10, 10]}, "one of"),
                          ({"rect": [0, 0, 10, 10]}, "page"),
                          ({"figure": "Table 2"}, "figure"),
                          ({"table": "Section 3"}, "table"),
                          ({"page": 1, "rect": [10, 10, 5, 50]}, "rect"),
                          ({"figure": "Figure 1", "colour": "red"}, "colour")):
        problems = cli.config_problems({"regions": [region]})
        assert any("regions[0]" in p and words in p for p in problems), (region, problems)


def test_the_local_api_and_the_javascript_create_it(paper, tmp_path):
    out, _ = build(paper, regions=[{"figure": "Figure 1", "comment": "结果对比", "tags": ["图表"]}])
    (item,) = cli.api_items({"attachment_key": "ATT"}, out)
    assert item["annotationType"] == "image" and "annotationText" not in item
    assert item["tags"] == [{"tag": "zotero-scholium"}, {"tag": "图表"}] and "label" not in item
    js = cli.render_js(dict(cli.DEFAULTS, attachment_key="ATT", item_key="ITEM", out_dir=str(tmp_path)), out)
    assert '"type": "image"' in js and "image: 0" in js


def test_the_plugin_endpoint_creates_it_with_its_rectangle():
    image = dict(NEW, type="image", text="", comment="结果对比", position={"pageIndex": 0, "rects": [[148, 520, 452, 694]]})
    out = zotero(request(rewrite=False, cleanup=False, annotations=[image]), [])
    assert out["result"]["ok"], out
    assert out["result"]["created"]["image"] == 1
    (made,) = [i for i in out["items"] if i["key"].startswith("NEW")]
    assert json.loads(made["position"])["rects"] == [[148, 520, 452, 694]] and made["comment"] == "结果对比"


def test_a_re_apply_keeps_the_region_and_updates_its_comment_in_place(paper, monkeypatch, capsys):
    api = UpdatingApi()
    first = {"regions": [{"figure": "Figure 1", "comment": "结果对比"}]}
    code, report = run(paper, monkeypatch, capsys, first, "--apply", api=api)
    assert report["applied"] is True and report["regions"] == 1
    assert [a["annotationType"] for a in annotations(api).values()] == ["image"]
    code, again = run(paper, monkeypatch, capsys, dict(first, cleanup=True), "--apply", api=api)
    assert again["rewrite"] == {"created": 0, "updated": 0, "kept": 1, "removed": 0}
    code, changed = run(paper, monkeypatch, capsys, {"regions": [{"figure": "Figure 1", "comment": "新的说明"}], "cleanup": True},
                        "--apply", api=api)
    assert changed["rewrite"] == {"created": 0, "updated": 1, "kept": 0, "removed": 0}
    assert annotations(api)["NEW1"]["annotationComment"] == "新的说明"
