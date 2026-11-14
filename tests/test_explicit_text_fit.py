"""Fixed text rectangles warn on overflow without changing their geometry."""
import pymupdf
import pytest

from zotero_scholium import cli


def layout(item, obstacles=()):
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_text((80, 300), "A synthetic body line.")
        spec = cli.normalise_summary(dict({"page": 1, "font_size": 8}, **item), cli.DEFAULTS, [(612, 792)])
        missed = []
        annotations = cli.layout_page_summaries(cli.PageIndex(page), [spec], obstacles, missed)
        assert missed == []
        return annotations[0]


@pytest.mark.parametrize("text", [
    "A long margin note with several sentences. " * 20,
    "这是一条需要自动换行的中文批注。" * 20,
    "first line\nsecond line",
    "第一行\r\n第二行",
], ids=["english-wrap", "chinese-wrap", "line-feed", "crlf"])
def test_overflow_warns_and_preserves_explicit_rect_and_font(text):
    ann = layout({"rect": [80, 20, 350, 40], "text": text})
    assert "fit" in ann.get("layout_warning", "")
    assert ann["position"]["rects"] == [[80.0, 752.0, 350.0, 772.0]]
    assert ann["position"]["fontSize"] == 8.0
    assert ann["type"] == "text" and "fitted" not in ann


@pytest.mark.parametrize("text,rect", [
    ("short", [80, 20, 350, 38]),
    ("甲乙丙丁戊己", [80, 20, 110, 50]),
    ("甲\n乙", [80, 20, 350, 50]),
    ("甲\n\n乙", [80, 20, 350, 62]),
], ids=["one-line", "chinese-two-lines", "two-lines", "blank-line"])
def test_exactly_fitting_text_has_no_layout_warning(text, rect):
    assert "layout_warning" not in layout({"rect": rect, "text": text})


def test_blank_line_counts_toward_explicit_box_height():
    ann = layout({"rect": [80, 20, 350, 50], "text": "甲\n\n乙"})
    assert "fit" in ann.get("layout_warning", "")


def test_exact_fit_with_fractional_font_size_ignores_roundoff():
    ann = layout({"rect": [80, 20, 350, 50.9], "text": "甲\n乙", "font_size": 8.3})
    assert "layout_warning" not in ann


def test_overflow_keeps_the_existing_collision_warning():
    ann = layout({"rect": [80, 20, 350, 40], "text": "long text " * 100},
                 obstacles=[[100, 750, 200, 770]])
    assert "overlaps" in ann["layout_warning"]
    assert "fit" in ann["layout_warning"]


def test_sticky_note_comments_do_not_need_to_fit_the_icon():
    ann = layout({"rect": [80, 20, 350, 40], "text": "long comment " * 100, "kind": "note"})
    assert "layout_warning" not in ann
    assert ann["type"] == "note"
    assert ann["position"]["rects"] == [[80.0, 750.0, 102.0, 772.0]]
