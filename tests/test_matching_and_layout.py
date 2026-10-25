"""Tests against a synthetic two-column PDF generated at run time (no third-party content)."""
import json, os, re
import pymupdf
import pytest

from zotero_scholium import cli


LEFT = ("Foundation models have transformed machine learning for language and vision, but achieving "
        "comparable impact in physical simulation remains a challenge. Data heterogeneity and unstable "
        "long-term dynamics inhibit learning from sufficiently diverse dynamics.")
RIGHT = ("Our work contributes to overcoming these barriers through patch jittering, a stabilization "
         "method derived from harmonic analysis, and topology-aware sampling that ties sampling to the "
         "distribution topology in order to increase training throughput.")


@pytest.fixture(scope="module")
def pdf_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("pdf") / "synthetic.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((300, 30), "Synthetic Paper — header", fontsize=9)
    # two narrow columns produce line breaks within phrases
    page.insert_textbox(pymupdf.Rect(55, 72, 297, 700), LEFT, fontsize=10, fontname="helv")
    page.insert_textbox(pymupdf.Rect(315, 72, 543, 700), RIGHT, fontsize=10, fontname="helv")
    page.insert_text((300, 770), "1", fontsize=9)
    doc.save(str(p)); doc.close()
    return str(p)


def test_norm_str_ignores_ligatures_hyphens_and_spaces():
    assert cli.norm_str("suf-\nficiently ﬁne") == "sufficientlyfine"
    assert cli.norm_str("2D-to-3D") == "2dto3d"


def test_match_spans_line_breaks(pdf_path):
    doc = pymupdf.open(pdf_path)
    pi = cli.PageIndex(doc[0])
    ws = pi.match("Data heterogeneity and unstable long-term dynamics inhibit learning")
    assert ws, "phrase crossing a line break should still match"
    rects = pi.line_rects(ws)
    assert len(rects) >= 2, "a phrase over several lines yields one rect per line"
    assert pi.match("this phrase does not exist") is None


def test_two_column_detection_and_margin_side(pdf_path):
    doc = pymupdf.open(pdf_path)
    pi = cli.PageIndex(doc[0])
    assert pi.two_col
    left_para = pi.line_rects(pi.match("Foundation models have transformed"))[0]
    right_para = pi.line_rects(pi.match("Our work contributes"))[0]
    lx0, lx1 = pi.margin_box(left_para)
    rx0, rx1 = pi.margin_box(right_para)
    assert lx1 <= pi.body_x0 and lx0 >= 0, "left-column paragraph -> left margin"
    assert rx0 >= pi.body_x1 and rx1 <= pi.W, "right-column paragraph -> right margin"


def test_text_line_rects_are_in_pdf_space_and_skip_rotated_words(tmp_path):
    p = tmp_path / "stamp.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 90), "A Title Line", fontsize=16)
    page.insert_text((20, 400), "arXiv:1706.03762v7 [cs.CL] 2 Aug 2023", fontsize=9, rotate=90)  # vertical stamp in the left margin
    page.insert_text((300, 770), "7", fontsize=9)  # page number
    doc.save(str(p)); doc.close()
    pi = cli.PageIndex(pymupdf.open(str(p))[0])
    lines = pi.text_line_rects()
    assert any(r[0] >= 100 and 695 <= r[1] < r[3] <= 725 for r in lines), "title line in PDF space (y upward)"
    assert all(r[0] >= 50 for r in lines), "no word of the rotated stamp is a text line"
    assert any(295 <= r[0] <= 305 and 15 <= r[1] < r[3] <= 32 for r in lines), "a single-character page number remains a line"


def test_text_line_rects_keep_short_words_and_two_digit_numbers(tmp_path):
    """Short words and a two-digit page number are ordinary text lines, not rotated stamps."""
    pdf = _page_pdf(tmp_path / "short.pdf", lambda pg: (pg.insert_textbox(pymupdf.Rect(55, 72, 543, 600), LEFT * 4, fontsize=10, fontname="tiro"),
                                                        pg.insert_text((100, 650), "if it of an", fontname="tiro"),
                                                        pg.insert_text((300, 770), "12", fontsize=9, fontname="tiro")))
    lines = cli.PageIndex(pymupdf.open(pdf)[0]).text_line_rects()
    assert any(295 <= r[0] <= 305 and 15 <= r[1] < r[3] <= 32 for r in lines), "a two-digit page number is a text line"
    assert any(95 <= r[0] <= 105 and 130 <= r[1] < r[3] <= 155 for r in lines), "a line of short words is a text line"
    out, missed = cli.build(_band_cfg(pdf, tmp_path, place="bottom"))
    assert missed == [] and len(out) == 1
    a = out[0]
    assert a["position"]["rects"][0][1] >= 792 - 770 + 2, "the band stays above the page number"
    assert "layout_warning" not in a


def test_margin_box_side_can_be_forced(pdf_path):
    pi = cli.PageIndex(pymupdf.open(pdf_path)[0])
    right_para = pi.line_rects(pi.match("Our work contributes"))[0]
    auto = pi.margin_box(right_para)
    assert auto[0] >= pi.body_x1, "two-column page: the paragraph's own (right) side"
    assert pi.margin_box(right_para, "left")[1] <= pi.body_x0
    assert pi.margin_box(right_para, "right") == auto
    left_para = pi.line_rects(pi.match("Foundation models have transformed"))[0]
    assert pi.margin_box(left_para, "right")[0] >= pi.body_x1


def test_wrap_respects_width():
    lines = cli.wrap("这是一段用于测试换行的中文文本，应该被切成若干行。", 48, 8)
    assert all(sum(cli.cw(c) * 8 for c in ln) <= 48 + 8 for ln in lines)
    assert "".join(lines) == "这是一段用于测试换行的中文文本，应该被切成若干行。"


def test_build_produces_pdf_space_coords_and_no_hard_newlines(pdf_path, tmp_path):
    cfg = dict(cli.DEFAULTS)
    cfg.update({
        "pdf": pdf_path, "item_key": "ITEM0000", "attachment_key": "ATTA0000", "out_dir": str(tmp_path),
        "preview_pages": [1],
        "highlights": [{"page": 1, "core": True, "text": "patch jittering, a stabilization method", "comment": "translation"}],
        "summaries": [{"page": 1, "anchor": "Foundation models have transformed", "text": "summary one"},
                      {"page": 1, "anchor": "Data heterogeneity and unstable", "text": "summary two, placed below the first"}],
    })
    out, missed = cli.build(cfg)
    assert missed == []
    hl = [a for a in out if a["type"] == "highlight"][0]
    assert hl["color"] == cfg["core_color"]
    x0, y0, x1, y1 = hl["position"]["rects"][0]
    assert 0 < y0 < y1 < 792 and 315 <= x0 < x1 <= 543, "highlight in PDF space inside the right column"
    texts = [a for a in out if a["type"] == "text"]
    assert len(texts) == 2 and all("\n" not in t["comment"] for t in texts)
    assert texts[0]["position"]["fontSize"] == cfg["font_size"]
    # the two left-margin boxes must not overlap
    (_, ay0, _, ay1), (_, by0, _, by1) = texts[0]["position"]["rects"][0], texts[1]["position"]["rects"][0]
    assert ay0 >= by1 or by0 >= ay1
    assert os.path.exists(os.path.join(tmp_path, "preview_p1.png"))
    # the source PDF is unchanged
    assert pymupdf.open(pdf_path).page_count == 1


def test_version_note_never_overwrites():
    html = "<h1>Paper Title</h1><p>body</p>"
    same, prefix = cli.version_note(html, "Paper Title", [])
    assert same == html and prefix == "Paper Title"
    v2, title2 = cli.version_note(html, "Paper Title", ["Paper Title"])
    assert title2.startswith("Paper Title (v2, ") and title2 in v2
    v3, title3 = cli.version_note(v2, "Paper Title", ["Paper Title", title2])
    assert title3.startswith("Paper Title (v3, ") and "(v2" not in title3


def test_levels_and_underline(pdf_path, tmp_path):
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": pdf_path, "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [1],
                "levels": {"term": "#5fb236"},
                "highlights": [{"page": 1, "level": "term", "type": "underline", "text": "harmonic analysis", "comment": "def"},
                               {"page": 1, "color": "#123456", "text": "Foundation models", "comment": ""}]})
    out, missed = cli.build(cfg)
    assert missed == []
    assert out[0]["type"] == "underline" and out[0]["color"] == "#5fb236"
    assert out[1]["type"] == "highlight" and out[1]["color"] == "#123456"


def test_highlights_alone_leave_the_other_pages_unread(pdf_path, tmp_path, monkeypatch):
    """The document's column extents are for margin notes; a run without them reads only the pages it highlights."""
    monkeypatch.setattr(cli, "column_bounds", lambda doc: pytest.fail("column extents computed without margin notes"))
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": pdf_path, "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
                "highlights": [{"page": 1, "text": "harmonic analysis", "comment": "def"}]})
    out, missed = cli.build(cfg)
    assert missed == [] and len(out) == 1


def test_profile_markdown_renders_without_newlines_in_samples():
    prof = {"annotations_analysed": 10, "annotated_papers": 2, "annotations_per_paper_median": 5, "language": "zh",
            "types": {"highlight": 0.6, "text": 0.4}, "uses_margin_text": True, "uses_underline": False, "uses_sticky_notes": False,
            "comment_rate": 0.5, "comment_len_median": 30,
            "comment_style": {"label_colon_rate": 0.1, "list_rate": 0.0, "multiline_rate": 0.2},
            "colors": [{"color": "#ff6666", "share": 0.8, "count": 8, "types": {"highlight": 8}, "comment_rate": 0.5,
                        "comment_len_median": 30, "sample_comments": ["a / b"], "sample_texts": []}],
            "child_notes": {"count": 3, "long_notes": 3, "len_median": 900}, "levels": {"level1": "#ff6666"}}
    md = cli.profile_markdown(prof)
    assert "#ff6666" in md and "reading notes: yes" in md and "\n\n\n" not in md


def test_merge_profile_keeps_interpretation_and_user_rules():
    learned_v1 = "# Annotation profile\n\n- Language: zh\n\n## Interpretation\n\n- tone: ___\n"
    first = cli.merge_profile_md(learned_v1, "")
    assert cli.USER_RULES_MARK in first and "(none yet" in first
    edited = first.replace("- tone: ___", "- tone: first person").replace("- (none yet", "- comments are translations\n- (none yet")
    learned_v2 = "# Annotation profile\n\n- Language: en\n\n## Interpretation\n\n- tone: ___\n"
    merged = cli.merge_profile_md(learned_v2, edited)
    assert "Language: en" in merged and "Language: zh" not in merged, "statistics are regenerated"
    assert "- tone: first person" in merged and "- tone: ___" not in merged, "filled-in interpretation survives"
    assert "- comments are translations" in merged, "user's rules survive"
    assert merged.count(cli.USER_RULES_MARK) == 1 and merged.count(cli.INTERPRETATION_MARK) == 1


_TEXT_ANN = {"type": "text", "color": "#1a73e8", "comment": "hi", "pageLabel": "1",
             "sortIndex": "00000|000000|00001", "position": {"pageIndex": 0, "rects": [[1, 2, 3, 4]], "fontSize": 8, "rotation": 0}}


def test_render_js_is_self_contained(tmp_path):
    cfg = dict(cli.DEFAULTS); cfg.update({"item_key": "I", "attachment_key": "A"})
    js = cli.render_js(cfg, [_TEXT_ANN])
    assert "Zotero.Items.getByLibraryAndKey" in js and json.dumps(cli.TAG) in js
    assert "annotationAuthorName" not in js, "the JavaScript backend writes no author name"


def test_author_key_is_rejected(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"pdf": "x.pdf", "item_key": "I", "attachment_key": "A", "out_dir": "o", "author": ""}), encoding="utf8")
    with pytest.raises(SystemExit, match="author"):
        cli.main(["--config", str(cfg)])


class _FakeApi:
    def __init__(self):
        self.created = []

    def children(self, key, item_type=None):
        return []

    def delete(self, keys):
        return len(keys)

    def create(self, items):
        self.created.extend(items)
        return [f"K{i}" for i in range(len(items))], []


def test_api_apply_writes_no_author_name():
    cfg = dict(cli.DEFAULTS); cfg.update({"item_key": "I", "attachment_key": "A"})
    api = _FakeApi()
    res = cli.api_apply(cfg, [_TEXT_ANN], api)
    assert res["ok"] and len(api.created) == 1
    assert all("annotationAuthorName" not in it for it in api.created)
    assert "author" not in cli.DEFAULTS


def test_check_translations_flags_added_content_and_accepts_faithful_translation():
    faithful = {"type": "highlight", "pageLabel": "1", "text": "all models are given the same finetuning budget of 500k samples",
                "comment": "所有模型的微调预算都是 50 万个样本。"}
    extended = {"type": "highlight", "pageLabel": "2", "text": "employs a space-time factorized transformer architecture",
                "comment": "采用时空分解的 Transformer 架构，每个块里交替沿空间轴和时间轴做注意力，并用 CSM 处理分辨率。"}
    added_number = {"type": "underline", "pageLabel": "3", "text": "structure that decreases the diversity of possible grids",
                    "comment": "式 (8) 有低秩结构，会减少可能网格的多样性。"}
    margin = {"type": "text", "pageLabel": "1", "comment": "式 (8) 值得注意"}
    w = cli.check_translations([faithful, extended, added_number, margin])
    pages = [x["page"] for x in w]
    assert "1" not in pages, "number-format conversion (500k -> 50 万) must not be flagged"
    assert "2" in pages and any("csm" in r for x in w if x["page"] == "2" for r in x["reasons"])
    assert "3" in pages and any("8" in r for x in w if x["page"] == "3" for r in x["reasons"])
    assert len(w) == 2, "margin text is never checked"


def test_margin_boxes_avoid_existing_annotations(pdf_path, tmp_path):
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": pdf_path, "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
                "summaries": [{"page": 1, "anchor": "Foundation models have transformed", "text": "summary beside an existing note"}]})
    out, _ = cli.build(cfg)
    x0, y0, x1, y1 = out[0]["position"]["rects"][0]
    obstacles = {0: [[0.0, y0 - 5, 60.0, y1 + 5]]}      # a user's text box exactly where the summary wants to go
    out2, _ = cli.build(cfg, obstacles)
    _, b0, _, b1 = out2[0]["position"]["rects"][0]
    assert b1 <= y0 - 5 or b0 >= y1 + 5, "the box must not overlap the existing annotation"
    assert "layout_warning" not in out2[0]
    listing = {"annotations": [
        {"type": "text", "tags": [], "position": {"pageIndex": 0, "rects": [[1, 2, 3, 4]]}},
        {"type": "text", "tags": [cli.TAG], "position": {"pageIndex": 0, "rects": [[5, 6, 7, 8]]}},
        {"type": "ink", "tags": [], "position": {"pageIndex": 1, "paths": [[10, 20, 30, 40, 12, 22]]}},
        {"type": "highlight", "tags": [], "position": '{"pageIndex": 0, "rects": [[9, 9, 9, 9]]}'}]}
    assert cli.existing_obstacles(listing) == {0: [[1.0, 2.0, 3.0, 4.0]], 1: [[10.0, 20.0, 30.0, 40.0]]}


def test_own_annotations_become_obstacles_when_cleanup_is_disabled():
    """With "cleanup": false the tool's earlier margin boxes remain in Zotero and must not be covered either."""
    listing = {"annotations": [
        {"type": "text", "tags": [cli.TAG], "position": {"pageIndex": 0, "rects": [[1, 2, 3, 4]]}},
        {"type": "text", "tags": [], "position": {"pageIndex": 0, "rects": [[5, 6, 7, 8]]}}]}
    assert cli.existing_obstacles(listing) == {0: [[5.0, 6.0, 7.0, 8.0]]}
    assert cli.existing_obstacles(listing, keep_own=True) == {0: [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]]}


def test_tokens_expand_ligatures():
    assert "prefix" in cli._tokens("preﬁx tuning is difﬁcult")
    assert cli.check_translations([{"type": "highlight", "pageLabel": "1", "text": "preﬁx tuning is difﬁcult to optimize",
                                    "comment": "prefix tuning 这种方法很难优化。"}]) == []


def test_column_bounds_come_from_the_whole_document(tmp_path):
    """Page 2 only has short lines; on its own it would place the right margin box inside the text column."""
    p = tmp_path / "two_pages.pdf"
    doc = pymupdf.open()
    page1 = doc.new_page(width=612, height=792)
    page1.insert_textbox(pymupdf.Rect(55, 72, 297, 700), LEFT * 3, fontsize=10, fontname="helv")
    page1.insert_textbox(pymupdf.Rect(315, 72, 543, 700), RIGHT * 3, fontsize=10, fontname="helv")
    page2 = doc.new_page(width=612, height=792)
    page2.insert_textbox(pymupdf.Rect(55, 72, 297, 700), LEFT * 3, fontsize=10, fontname="helv")
    page2.insert_textbox(pymupdf.Rect(315, 72, 430, 700), RIGHT * 3, fontsize=10, fontname="helv")  # narrow column
    doc.save(str(p)); doc.close()
    doc = pymupdf.open(str(p))
    alone = cli.PageIndex(doc[1])
    assert alone.body_x1 < 440, "per-page estimate underestimates the column"
    bounds = cli.column_bounds(doc)
    assert bounds and bounds[1] > 520
    with_doc = cli.PageIndex(doc[1], bounds)
    x0, _ = with_doc.margin_box(with_doc.line_rects(with_doc.match("Our work contributes"))[0])
    assert x0 >= 520, "the right margin box stays outside the document's text column"


def test_margin_boxes_avoid_figures(tmp_path):
    p = tmp_path / "figure.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(55, 72, 297, 700), LEFT * 3, fontsize=10, fontname="helv")
    page.insert_textbox(pymupdf.Rect(315, 72, 543, 700), RIGHT * 3, fontsize=10, fontname="helv")
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False); pix.clear_with(120)
    page.insert_image(pymupdf.Rect(4, 60, 52, 200), pixmap=pix)          # an image in the left margin, beside the first lines
    page.draw_rect(pymupdf.Rect(548, 60, 608, 200), fill=(0.6, 0.6, 0.6))  # a vector figure in the right margin
    doc.save(str(p)); doc.close()
    doc = pymupdf.open(str(p))
    figs = cli.page_figure_rects(doc[0])
    assert any(r[0] < 52 and r[3] > 792 - 200 for r in figs), "the image is an obstacle (PDF space, y upward)"
    assert any(r[0] >= 540 for r in figs), "the drawing is an obstacle"
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": str(p), "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
                "summaries": [{"page": 1, "anchor": "Foundation models have transformed", "text": "left note"},
                              {"page": 1, "anchor": "Our work contributes", "text": "right note"}]})
    out, missed = cli.build(cfg)
    assert missed == []
    for a in out:
        x0, y0, x1, y1 = a["position"]["rects"][0]
        for fx0, fy0, fx1, fy1 in figs:
            if fx0 < x1 and fx1 > x0:
                assert y1 <= fy0 or y0 >= fy1, "margin note must not overlap a figure"
        assert "layout_warning" not in a


@pytest.mark.parametrize("given, shown", [
    ("d<sub>k</sub> and x<sup>2</sup>", "dₖ and x²"),
    ("π<sub>ref</sub> and π<sup>*</sup>", "π_ref and π*"),
    ("π<sup>SFT</sup>, y<sub>w</sub> and y<sub>l</sub>", "π^SFT, y_w and yₗ"),
    ("e<sup>-x</sup>, a<sub>i,j</sub>", "e⁻ˣ, a_(i,j)"),
    ("<b>bold</b> and <i>slanted</i>", "bold and slanted"),
    ("if p<q and q>r, then p<r", "if p<q and q>r, then p<r"),
    ("x<SUP>2</SUP>, H<SUB>2</SUB>O", "x², H₂O"),
    ('x<sup class="exponent">2</sup> and y<sub >k</sub >', "x² and yₖ"),
    ("an unclosed x<sup>2 stays", "an unclosed x<sup>2 stays"),
])
def test_page_text_writes_scripts_without_tags(given, shown):
    assert cli.page_text(given) == shown


def test_an_unconverted_script_tag_in_margin_text_is_reported(tmp_path):
    pdf = _page_pdf(tmp_path / "t.pdf", lambda pg: pg.insert_textbox(pymupdf.Rect(108, 72, 504, 700), LEFT * 3, fontsize=10, fontname="helv"))
    cfg = _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "The loss grows as x<SUP>2 here."}])
    out, missed = cli.build(cfg)
    assert missed == [] and out[0]["comment"] == "The loss grows as x<SUP>2 here."
    assert [w["kind"] for w in cli.check_style(out, cfg)] == ["tag"]


def test_margin_text_on_the_page_carries_no_tags(tmp_path):
    pdf = _page_pdf(tmp_path / "t.pdf", lambda pg: pg.insert_textbox(pymupdf.Rect(108, 72, 504, 700), LEFT * 3, fontsize=10, fontname="helv"))
    cfg = _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "The reward is β log π<sub>θ</sub>/π<sub>ref</sub>, with π<sup>SFT</sup> as reference."},
                          {"page": 1, "place": "top", "text": "A summary with d<sub>k</sub> and x<sup>2</sup>."}])
    out, missed = cli.build(cfg)
    assert missed == [] and [a["comment"] for a in out] == ["A summary with dₖ and x².", "The reward is β log π_θ/π_ref, with π^SFT as reference."]
    assert cli.check_style(out, cfg) == []


def _stamped_page(tmp_path):
    """One column with a vertical preprint stamp in the left margin, beside the first paragraphs."""
    return _page_pdf(tmp_path / "stamp.pdf", lambda pg: (
        pg.insert_textbox(pymupdf.Rect(108, 72, 520, 760), LEFT * 12, fontsize=10, fontname="helv"),
        pg.insert_text((30, 430), "arXiv:2305.18290v3 [cs.LG] 29 Jul 2024", fontsize=20, rotate=90)))


def test_margin_text_rects_find_a_vertical_stamp(tmp_path):
    doc = pymupdf.open(_stamped_page(tmp_path))
    pi = cli.PageIndex(doc[0])
    rects = pi.margin_text_rects()
    assert any(r[2] <= pi.body_x0 and r[3] - r[1] > 200 for r in rects), "the stamp is margin text"
    assert all(r[2] <= pi.body_x0 + 1 or r[0] >= pi.body_x1 - 1 for r in rects), "no body line is margin text"


def test_margin_note_gives_way_to_a_stamp(tmp_path):
    pdf = _stamped_page(tmp_path)
    doc = pymupdf.open(pdf)
    pi = cli.PageIndex(doc[0])
    stamp = [r for r in pi.margin_text_rects() if r[2] <= pi.body_x0]
    anchor = "Foundation models have transformed"
    left = {"page": 1, "anchor": anchor, "text": "a note beside the first paragraph"}
    out, missed = cli.build(_cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
                                 summaries=[dict(left, side="auto")]))
    assert missed == []
    x0, y0, x1, y1 = out[0]["position"]["rects"][0]
    assert x0 >= pi.body_x1, "with the stamp beside the paragraph, the note takes the right margin"
    out, _ = cli.build(_cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
                            summaries=[dict(left, side="left")]))
    rect = out[0]["position"]["rects"][0]
    assert rect[2] <= pi.body_x0 and not cli._intersects(rect, stamp), "a forced left note moves clear of the stamp"


def test_place_blocks_keeps_boxes_out_of_footer_and_header():
    low = [{"y_top": 40.0, "h": 60.0, "text": "paragraph at the page bottom"}]
    cli.place_blocks(low, [], floor=28.0, ceiling=772.0)
    assert low[0]["y_top"] - low[0]["h"] >= 28.0 and "layout_warning" not in low[0]
    high = [{"y_top": 790.0, "h": 30.0, "text": "paragraph at the page top"}]
    cli.place_blocks(high, [], floor=28.0, ceiling=772.0)
    assert high[0]["y_top"] <= 772.0 and "layout_warning" not in high[0]


def test_cleanup_false_is_honoured_by_the_js_backend():
    cfg = dict(cli.DEFAULTS); cfg.update({"item_key": "I", "attachment_key": "A", "cleanup": False})
    js = cli.render_js(cfg, [])
    assert "var CLEANUP = false;" in js and "keep every existing annotation" in js
    cfg["cleanup"] = True
    assert "var CLEANUP = true;" in cli.render_js(cfg, [])


def test_profile_lives_in_the_zotero_data_dir(tmp_path, monkeypatch):
    data = tmp_path / "ZoteroData"; data.mkdir(); (data / "zotero.sqlite").write_bytes(b"")
    profiles = tmp_path / "Profiles" / "abc.default"; profiles.mkdir(parents=True)
    escaped = str(data).replace("\\", "\\\\")
    (profiles / "prefs.js").write_text('user_pref("extensions.zotero.dataDir", "%s");\n' % escaped, encoding="utf8")
    assert cli.zotero_prefs_data_dir([str(tmp_path / "Profiles")]) == str(data)
    monkeypatch.delenv("ZOTERO_DATA_DIR", raising=False)
    monkeypatch.setattr(cli, "zotero_prefs_data_dir", lambda profile_roots=None: str(data))
    assert cli.zotero_data_dir() == str(data)
    assert cli.profile_dir() == os.path.join(str(data), "zotero-scholium")
    # the configuration and the environment take precedence over prefs.js
    other = tmp_path / "Other"; other.mkdir(); (other / "zotero.sqlite").write_bytes(b"")
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(other))
    assert cli.zotero_data_dir() == str(other)
    assert cli.zotero_data_dir({"data_dir": str(data)}) == str(data)
    # a PDF inside storage/ identifies its own library
    pdf = other / "storage" / "KEY" / "p.pdf"
    assert cli.zotero_data_dir({"pdf": str(pdf)}) == str(other)


def _cfg(**over):
    cfg = dict(cli.DEFAULTS); cfg.update(over); return cfg


def test_normalise_summary_resolves_defaults_from_cfg():
    sp = cli.normalise_summary({"page": 1, "anchor": "a phrase", "text": "note"}, _cfg(font_size=9, text_color="#123456"),
                               [(612.0, 792.0)])
    assert sp == {"page": 0, "text": "note", "place": "margin", "side": "auto", "kind": "text", "color": "#123456",
                  "font_size": 9.0, "min_font_size": 8.0, "rect": None, "anchor": "a phrase", "occurrence": None}
    sp = cli.normalise_summary({"page": 1, "place": "top", "text": "band", "color": "#ff0000", "font_size": 10, "side": "left"},
                               _cfg(margin_side="right", summary_kind="text"), [(612.0, 792.0)])
    assert sp["place"] == "top" and sp["anchor"] is None and sp["side"] == "left" and sp["color"] == "#ff0000" and sp["font_size"] == 10.0
    sp = cli.normalise_summary({"page": 1, "anchor": "x", "text": "t"}, _cfg(margin_side="right", summary_kind="note"), [(612.0, 792.0)])
    assert sp["side"] == "right" and sp["kind"] == "note"
    sp = cli.normalise_summary({"page": 1, "rect": [72, 40, 540, 100], "text": "box"}, _cfg(), [(612.0, 792.0)])
    assert sp["rect"] == [72.0, 40.0, 540.0, 100.0] and sp["anchor"] is None


@pytest.mark.parametrize("item, fragment", [
    ({"page": 1, "text": "t"}, "anchor"),                                              # margin without anchor
    ({"page": 1, "anchor": "a", "text": "t", "place": "side"}, "place"),
    ({"page": 1, "anchor": "a", "text": "t", "side": "outer"}, "side"),
    ({"page": 1, "anchor": "a", "text": "t", "kind": "sticky"}, "kind"),
    ({"page": 1, "place": "top", "text": "t", "kind": "note"}, "anchor"),               # a sticky note needs an anchor
    ({"page": 1, "anchor": "a", "text": "t", "color": "red"}, "color"),
    ({"page": 1, "anchor": "a", "text": "t", "font_size": 60}, "font_size"),
    ({"page": 1, "rect": [0, 0, 700, 50], "text": "t"}, "outside the page"),
    ({"page": 1, "rect": [10, 10, 30, 50], "text": "t"}, "narrower"),
    ({"page": 1, "rect": [10, 10, 300, 12], "text": "t"}, "shorter"),
    ({"page": 1, "rect": [10, 10, 300], "text": "t"}, "rect"),
    ({"page": 1, "rect": [10, 780, 300, 790], "text": "t", "kind": "note"}, "icon"),    # no room for the note icon
    ({"page": 3, "anchor": "a", "text": "t"}, "outside the document"),
    ({"page": 1, "anchor": "a", "text": "  "}, "text"),
])
def test_normalise_summary_rejects_invalid_items(item, fragment):
    with pytest.raises(ValueError) as e:
        cli.normalise_summary(item, _cfg(), [(612.0, 792.0)])
    assert fragment in str(e.value)


GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "summaries_legacy.json")


def test_legacy_configuration_output_is_unchanged(pdf_path, tmp_path):
    """A configuration without the new fields must keep producing byte-identical annotations."""
    cfg = _cfg(pdf=pdf_path, item_key="ITEM0000", attachment_key="ATTA0000", out_dir=str(tmp_path), preview_pages=[],
               highlights=[{"page": 1, "core": True, "text": "patch jittering, a stabilization method", "comment": "translation"}],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "summary one"},
                          {"page": 1, "anchor": "Our work contributes", "text": "a note in the right margin"},
                          {"page": 1, "anchor": "Data heterogeneity and unstable", "text": "summary two, placed below the first"}])
    out, missed = cli.build(cfg)
    assert missed == []
    rendered = json.dumps(out, ensure_ascii=False, indent=1)
    if not os.path.exists(GOLDEN):
        if not os.environ.get("SCHOLIUM_WRITE_GOLDEN"):
            pytest.fail("the golden file %s is missing; re-run with SCHOLIUM_WRITE_GOLDEN=1 to create it" % GOLDEN)
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        open(GOLDEN, "w", encoding="utf8", newline="\n").write(rendered)
        pytest.skip("golden file created; re-run to compare")
    assert rendered == open(GOLDEN, encoding="utf8").read()


def _page_pdf(path, draw):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    draw(page)
    doc.save(str(path)); doc.close()
    return str(path)


def _band_cfg(pdf, out_dir, band_min_font_size=8, **item):
    entry = {"page": 1, "text": "A short summary of the paper written by the reader."}
    entry.update(item)
    return _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(out_dir), preview_pages=[], summaries=[entry],
                band_min_font_size=band_min_font_size)


def test_top_band_sits_above_the_title(tmp_path):
    pdf = _page_pdf(tmp_path / "t.pdf", lambda pg: (pg.insert_text((100, 90), "A Title Line", fontsize=16),
                                                   pg.insert_textbox(pymupdf.Rect(55, 120, 543, 700), LEFT * 4, fontsize=10, fontname="helv")))
    out, missed = cli.build(_band_cfg(pdf, tmp_path, place="top"))
    assert missed == [] and len(out) == 1
    a = out[0]
    x0, y0, x1, y1 = a["position"]["rects"][0]
    assert a["type"] == "text" and y1 == 792 - cli.BAND_MARGIN and y0 >= 792 - 90, "band at the page top, above the title baseline"
    assert x1 - x0 > 300, "band spans the text column"
    assert a["sortIndex"] == "00000|000000|00006" and "layout_warning" not in a


def test_top_band_settles_between_header_and_title(tmp_path):
    pdf = _page_pdf(tmp_path / "h.pdf", lambda pg: (pg.insert_text((200, 30), "Published as a conference paper", fontsize=9),
                                                   pg.insert_text((100, 100), "A Title Line", fontsize=16),
                                                   pg.insert_textbox(pymupdf.Rect(55, 130, 543, 700), LEFT * 4, fontsize=10, fontname="helv")))
    out, missed = cli.build(_band_cfg(pdf, tmp_path, place="top"))
    a = out[0]; x0, y0, x1, y1 = a["position"]["rects"][0]
    assert y1 <= 792 - 30 and y0 >= 792 - 100, "below the header line and above the title"
    assert "layout_warning" not in a


def test_a_top_band_without_room_becomes_a_sticky_note_beside_the_first_line(tmp_path):
    pdf = _page_pdf(tmp_path / "full.pdf", lambda pg: pg.insert_textbox(pymupdf.Rect(55, 8, 543, 780), LEFT * 12, fontsize=10, fontname="helv"))
    text = "A short summary of the paper written by the reader."
    out, missed = cli.build(_band_cfg(pdf, tmp_path, place="top", text=text))
    assert missed == [] and len(out) == 1
    a = out[0]; x0, y0, x1, y1 = a["position"]["rects"][0]
    assert a["type"] == "note" and a["comment"] == text and a["as_note"] and "layout_warning" not in a
    pi = cli.PageIndex(pymupdf.open(pdf)[0])
    first = max(pi.text_line_rects(), key=lambda r: r[3])
    assert y0 < first[3] and y1 > first[1], "beside the first text line"
    assert x0 >= pi.body_x1 and x1 - x0 == pytest.approx(cli.NOTE_ICON), "in the margin, hugging the text column"
    assert "fontSize" not in a["position"]


def _one_column(pg, repeat):
    """One column of `repeat` times LEFT from y = 72 (18 times reach down to about y = 736), and a page number."""
    pg.insert_textbox(pymupdf.Rect(55, 72, 543, 730), LEFT * repeat, fontsize=10, fontname="helv")
    pg.insert_text((300, 770), "7", fontsize=9)


def test_a_bottom_band_without_room_becomes_a_sticky_note_beside_the_last_line(tmp_path):
    pdf = _page_pdf(tmp_path / "bottom.pdf", lambda pg: _one_column(pg, 18))
    text = " ".join([BAND_SENTENCE] * 9)
    out, missed = cli.build(_band_cfg(pdf, tmp_path, place="bottom", text=text))
    assert missed == [] and len(out) == 1
    a = out[0]; x0, y0, x1, y1 = a["position"]["rects"][0]
    assert a["type"] == "note" and a["comment"] == text and a["as_note"] and "layout_warning" not in a
    pi = cli.PageIndex(pymupdf.open(pdf)[0])
    last = min((r for r in pi.text_line_rects() if r[1] > 40), key=lambda r: r[1])
    assert y0 < last[3] and y1 > last[1], "beside the last text line above the page number"
    assert x0 >= pi.body_x1 and x1 - x0 == pytest.approx(cli.NOTE_ICON)
    # the same text fits as a band when the body ends higher on the page
    pdf = _page_pdf(tmp_path / "short.pdf", lambda pg: _one_column(pg, 4))
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="bottom", text=text))
    assert out[0]["type"] == "text" and "as_note" not in out[0]


def _gap_pdf(tmp_path):
    """A first page with a gap above the title too small for a long band at 9 pt."""
    return _page_pdf(tmp_path / "gap.pdf", lambda pg: (pg.insert_text((100, 70), "A Title Line", fontsize=16),
                                                      pg.insert_textbox(pymupdf.Rect(55, 100, 543, 700), LEFT * 4, fontsize=10, fontname="helv")))


BAND_SENTENCE = "The method fits a surrogate model to the measured field and reports its error."


def test_a_band_without_room_is_set_smaller_down_to_the_minimum(tmp_path):
    """Too long at 9 pt but not at 8 pt: the band takes the largest size in steps of 0.5 pt that fits, and says so."""
    pdf = _gap_pdf(tmp_path)
    words = " ".join([BAND_SENTENCE] * 9).split()
    for n in range(10, len(words), 3):           # the shortest text that no longer fits at 9 pt
        text = " ".join(words[:n])
        out, _ = cli.build(_band_cfg(pdf, tmp_path, place="top", text=text, font_size=9))
        if out[0].get("fitted"):
            break
    a = out[0]
    assert "layout_warning" not in a and a["fitted"]["from"] == 9 and 8 <= a["fitted"]["to"] < 9
    assert a["position"]["fontSize"] == a["fitted"]["to"]
    bigger = a["fitted"]["to"] + 0.5
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="top", text=text, font_size=bigger, band_min_font_size=bigger))
    assert out[0]["type"] == "note", "the size taken is the largest that fits"
    # a band that fits at its own size keeps it
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="top", text=BAND_SENTENCE, font_size=9))
    assert "fitted" not in out[0] and out[0]["position"]["fontSize"] == 9


def test_a_band_too_long_even_at_the_minimum_becomes_a_sticky_note(tmp_path):
    """The whole text goes into the note, at the band's colour; band_min_font_size sets the smallest size tried."""
    pdf = _gap_pdf(tmp_path)
    text = " ".join([BAND_SENTENCE] * 9)
    out, missed = cli.build(_band_cfg(pdf, tmp_path, place="top", text=text, font_size=9, color="#aa0000"))
    a = out[0]
    assert missed == [] and a["type"] == "note" and a["comment"] == text and a["color"] == "#aa0000"
    assert "layout_warning" not in a and "fitted" not in a
    words = text.split()
    fitted = next(t for t in (" ".join(words[:n]) for n in range(10, len(words), 3))
                  if cli.build(_band_cfg(pdf, tmp_path, place="top", text=t, font_size=9))[0][0].get("fitted"))
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="top", text=fitted, font_size=9, band_min_font_size=9))
    assert out[0]["type"] == "note" and "fitted" not in out[0]


def test_the_report_lists_bands_set_smaller_and_bands_turned_into_notes(tmp_path, capsys):
    pdf = _gap_pdf(tmp_path)
    words = " ".join([BAND_SENTENCE] * 9).split()
    text = next(t for t in (" ".join(words[:n]) for n in range(10, len(words), 3))
                if cli.build(_band_cfg(pdf, tmp_path, place="top", text=t, font_size=9))[0][0].get("fitted"))
    cfg = _band_cfg(pdf, tmp_path, place="top", text=text, font_size=9)
    path = tmp_path / "config.json"

    def report_of(cfg, *args):
        path.write_text(json.dumps({k: v for k, v in cfg.items() if k in cli.CONFIG_KEYS}), encoding="utf8")
        try:
            cli.main(["--config", str(path), "--ignore-existing", *args])
        except SystemExit:
            pass
        return json.loads(capsys.readouterr().out)
    report = report_of(cfg)
    assert report["layout_warnings"] == [] and report["fitted"][0]["font_size"].startswith("9 -> ") and report["as_notes"] == []
    long = " ".join(words)
    cfg["summaries"][0]["text"] = long
    report = report_of(cfg, "--apply", "--backend", "js")
    assert report["as_notes"] == [{"page": "1", "text": long[:60]}] and report["sticky_notes"] == 1 and report["margin_texts"] == 0
    assert report["layout_warnings"] == [] and report["backend"] == "js", "a band turned into a note does not block --apply"


def _crowded_first_page(pg):
    """A journal's first page: a logo at the top right, a header line 28 pt below the edge, the title right under it."""
    pg.draw_rect(pymupdf.Rect(480, 6, 560, 20), color=(0, 0, 0), fill=(0.2, 0.2, 0.6))
    pg.insert_text((55, 38), "JOURNAL OF EXAMPLES | RESEARCH ARTICLE", fontsize=10)
    pg.insert_text((55, 60), "A Title Line", fontsize=16)
    pg.insert_textbox(pymupdf.Rect(55, 70, 543, 700), LEFT * 4, fontsize=10, fontname="helv")


def test_top_band_without_room_goes_into_the_strip_beside_the_logo(tmp_path):
    pdf = _page_pdf(tmp_path / "logo.pdf", _crowded_first_page)
    if not cli.page_figure_rects(pymupdf.open(pdf)[0]):
        pytest.skip("this PyMuPDF does not report drawings as figures")
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="top", text="One line of summary.", font_size=9))
    a = out[0]; x0, y0, x1, y1 = a["position"]["rects"][0]
    assert "layout_warning" not in a
    assert y1 == 792 - cli.EDGE_MARGIN and y0 >= 792 - 28, "between the page edge and the header line"
    assert x1 <= 480 - 3, "beside the logo, not over it"
    # too long for the strip even at the smallest size: a sticky note
    text = "The method fits a surrogate model to the measured field and reports its error. " * 6
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="top", text=text, font_size=9))
    assert out[0]["type"] == "note" and out[0]["comment"] == text.strip() and "layout_warning" not in out[0]


def test_bottom_band_sits_above_the_page_number(tmp_path):
    pdf = _page_pdf(tmp_path / "b.pdf", lambda pg: (pg.insert_textbox(pymupdf.Rect(55, 72, 543, 600), LEFT * 4, fontsize=10, fontname="helv"),
                                                   pg.insert_text((300, 770), "7", fontsize=9)))
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="bottom"))
    a = out[0]; _, y0, _, y1 = a["position"]["rects"][0]
    assert y0 >= 792 - 770 + 2, "above the page number line"
    assert y1 <= 0.3 * 792 and "layout_warning" not in a


def test_bottom_band_sits_above_the_footer_line(tmp_path):
    """A footer line high enough to leave room beneath it must not attract the band into that strip."""
    pdf = _page_pdf(tmp_path / "f.pdf", lambda pg: (pg.insert_textbox(pymupdf.Rect(55, 72, 543, 600), LEFT * 4, fontsize=10, fontname="helv"),
                                                    pg.insert_text((100, 745), "Journal of Examples, 2026", fontsize=9)))
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="bottom"))
    a = out[0]; _, y0, _, y1 = a["position"]["rects"][0]
    assert y0 >= 792 - 745 + 1, "the band stays above the footer line"
    assert y1 <= 0.3 * 792 and "layout_warning" not in a


def _body_lines(pg, last_baseline):
    """Draw explicit body lines from y = 100 down to `last_baseline` (drawing lines directly cannot overflow silently)."""
    for y in range(100, last_baseline + 1, 12):
        pg.insert_text((60, y), "a line of body text that runs across most of the column width", fontsize=10, fontname="helv")


def test_bottom_band_between_body_and_page_number(tmp_path):
    """Body text ending about 30 pt above the page number: the band goes into that gap, not under the number."""
    pdf = _page_pdf(tmp_path / "g.pdf", lambda pg: (_body_lines(pg, 724), pg.insert_text((300, 770), "9", fontsize=9)))
    pi = cli.PageIndex(pymupdf.open(pdf)[0])
    body_bottom = min(r[1] for r in pi.text_line_rects() if r[1] > 40)
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="bottom", text="one line"))
    a = out[0]; _, y0, _, y1 = a["position"]["rects"][0]
    assert y0 >= 792 - 770 + 2 and y1 <= body_bottom, "between the page number and the last body line"
    assert "layout_warning" not in a


def test_bottom_band_falls_back_beneath_a_footer_when_the_gap_is_too_small(tmp_path):
    """Body text running down to the footer line: the band is placed beneath the footer, not over the text."""
    pdf = _page_pdf(tmp_path / "k.pdf", lambda pg: (_body_lines(pg, 736), pg.insert_text((100, 748), "Journal of Examples, 2026", fontsize=9)))
    pi = cli.PageIndex(pymupdf.open(pdf)[0])
    footer_bottom = min(r[1] for r in pi.text_line_rects())
    out, _ = cli.build(_band_cfg(pdf, tmp_path, place="bottom", text="one line"))
    a = out[0]; _, y0, _, y1 = a["position"]["rects"][0]
    assert cli.BAND_MARGIN <= y0 and y1 <= footer_bottom, "beneath the footer line, above the page edge"
    assert "layout_warning" not in a


def test_explicit_rect_is_converted_and_overlap_is_reported(tmp_path):
    pdf = _page_pdf(tmp_path / "r.pdf", lambda pg: pg.insert_text((100, 90), "A Title Line", fontsize=16))
    out, missed = cli.build(_band_cfg(pdf, tmp_path, rect=[72, 20, 540, 60]))
    assert missed == [] and out[0]["position"]["rects"][0] == [72.0, 732.0, 540.0, 772.0] and "layout_warning" not in out[0]
    out, _ = cli.build(_band_cfg(pdf, tmp_path, rect=[72, 60, 540, 120]))  # covers the title
    assert "explicit rectangle overlaps" in out[0]["layout_warning"]
    out, missed = cli.build(_band_cfg(pdf, tmp_path, rect=[72, 700, 540, 900]))
    assert out == [] and missed[0]["kind"] == "summary" and "outside the page" in missed[0]["reason"]


def test_placed_boxes_become_obstacles_for_later_ones(tmp_path):
    pdf = _page_pdf(tmp_path / "o.pdf", lambda pg: pg.insert_text((100, 200), "A Title Line", fontsize=16))
    cfg = _band_cfg(pdf, tmp_path, rect=[72, 6, 540, 40])
    cfg["summaries"].append({"page": 1, "place": "top", "text": "band placed after the explicit rectangle"})
    out, missed = cli.build(cfg)
    assert missed == [] and len(out) == 2
    fixed, band = out[0]["position"]["rects"][0], out[1]["position"]["rects"][0]
    assert band[3] <= fixed[1] and "layout_warning" not in out[1], "the band moved below the fixed box"


def test_per_item_color_and_font_size(pdf_path, tmp_path):
    cfg = _cfg(pdf=pdf_path, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[1],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "the same text for both boxes here"},
                          {"page": 1, "anchor": "Our work contributes", "text": "the same text for both boxes here",
                           "color": "#aa0000", "font_size": 12}])
    out, missed = cli.build(cfg)
    assert missed == []
    small, big = out
    assert small["color"] == cfg["text_color"] and small["position"]["fontSize"] == 8.0
    assert big["color"] == "#aa0000" and big["position"]["fontSize"] == 12.0
    h = lambda a: a["position"]["rects"][0][3] - a["position"]["rects"][0][1]
    assert h(big) > h(small), "wrapping and box height follow the item's font size"
    assert os.path.exists(os.path.join(tmp_path, "preview_p1.png"))


def test_side_override_and_global_margin_side(pdf_path, tmp_path):
    base = dict(pdf=pdf_path, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[])
    pi = cli.PageIndex(pymupdf.open(pdf_path)[0])
    out, _ = cli.build(_cfg(margin_side="left", summaries=[{"page": 1, "anchor": "Our work contributes", "text": "forced left"}], **base))
    assert out[0]["position"]["rects"][0][2] <= pi.body_x0
    out, _ = cli.build(_cfg(margin_side="left", summaries=[{"page": 1, "anchor": "Our work contributes", "text": "item wins", "side": "right"}], **base))
    assert out[0]["position"]["rects"][0][0] >= pi.body_x1


def test_sticky_notes_hug_the_column_and_do_not_overlap(pdf_path, tmp_path):
    cfg = _cfg(pdf=pdf_path, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[1], summary_kind="note",
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "first note"},
                          {"page": 1, "anchor": "comparable impact", "text": "second note on the next line"}])
    out, missed = cli.build(cfg)
    assert missed == [] and [a["type"] for a in out] == ["note", "note"]
    pi = cli.PageIndex(pymupdf.open(pdf_path)[0])
    for a in out:
        x0, y0, x1, y1 = a["position"]["rects"][0]
        assert abs((x1 - x0) - cli.NOTE_ICON) < 0.01 and abs((y1 - y0) - cli.NOTE_ICON) < 0.01
        assert x1 <= pi.body_x0 and x1 >= pi.body_x0 - 4 - 0.01, "icon beside the left text column"
        assert "fontSize" not in a["position"] and "rotation" not in a["position"]
    (_, ay0, _, ay1), (_, by0, _, by1) = out[0]["position"]["rects"][0], out[1]["position"]["rects"][0]
    assert ay0 >= by1 or by0 >= ay1


def test_render_js_embeds_bands_and_sticky_notes(pdf_path, tmp_path):
    import re as _re
    cfg = _cfg(pdf=pdf_path, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               summaries=[{"page": 1, "place": "top", "text": "band"},
                          {"page": 1, "anchor": "Our work contributes", "kind": "note", "text": "sticky"},
                          {"page": 1, "anchor": "Foundation models have transformed", "text": "margin", "font_size": 10}])
    out, missed = cli.build(cfg)
    assert missed == []
    js = cli.render_js(cfg, out)
    embedded = json.loads(_re.search(r"var ANNOTATIONS = (.*?);\n", js).group(1))
    assert [a["type"] for a in embedded] == ["text", "note", "text"]
    assert embedded[1]["position"]["rects"][0][2] - embedded[1]["position"]["rects"][0][0] == pytest.approx(22.0)
    assert "create 0 highlight/underline annotations and 3 margin text annotations" in js


def _ann(kind, rect, font=None, color="#1a73e8"):
    pos = {"pageIndex": 0, "rects": [rect]}
    if font:
        pos["fontSize"] = font
    return {"annotationType": kind, "annotationColor": color, "annotationComment": "c", "annotationPosition": json.dumps(pos),
            "parentItem": "ATT", "tags": []}


def test_layout_habits_from_positions():
    own = [_ann("text", [108, 726, 504, 786], 9), _ann("text", [108, 700, 504, 780], 9),      # page-top bands
           _ann("text", [520, 400, 600, 440], 8), _ann("text", [520, 300, 600, 340], 8),        # right margin
           _ann("note", [530, 200, 552, 222]), _ann("highlight", [100, 100, 300, 112])]
    lay = cli.layout_habits(own)
    assert lay == {"page_top_notes": 0.5, "margin_side": "right", "text_font_size_median": 9.0}
    assert cli.layout_habits([]) == {"page_top_notes": 0.0, "margin_side": "mixed", "text_font_size_median": None}
    own = [_ann("text", [108, 726, 504, 786], 9), _ann("text", [108, 700, 504, 780], 9),      # page-top bands
           _ann("text", [20, 400, 60, 440], 8), _ann("text", [20, 300, 60, 340], 8),          # left margin
           _ann("text", [20, 200, 60, 240], 8)]
    lay = cli.layout_habits(own)
    assert lay["margin_side"] == "left", "page-top bands span the column and do not vote on the margin side"
    assert lay["page_top_notes"] == 0.4


def test_profile_markdown_renders_layout_lines():
    prof = {"annotations_analysed": 10, "annotated_papers": 2, "annotations_per_paper_median": 5, "language": "zh",
            "types": {"highlight": 0.6, "text": 0.4}, "uses_margin_text": True, "uses_underline": False, "uses_sticky_notes": False,
            "comment_rate": 0.5, "comment_len_median": 30,
            "comment_style": {"label_colon_rate": 0.1, "list_rate": 0.0, "multiline_rate": 0.2},
            "colors": [], "child_notes": {"count": 0, "long_notes": 0, "len_median": 0}, "levels": {},
            "layout": {"page_top_notes": 0.5, "margin_side": "right", "text_font_size_median": 9.0}}
    md = cli.profile_markdown(prof)
    assert "page-top notes on 50%" in md and "margin side: right" in md and "9.0 pt" in md
    assert "- page-top summary: ___" in md and "- margin side: ___" in md and "- sticky notes instead of margin text: ___" in md
    assert "top of page 1" in cli.USER_RULES_TEMPLATE


def test_match_range_ellipsis(pdf_path):
    doc = pymupdf.open(pdf_path)
    pi = cli.PageIndex(doc[0])
    ws, reason = pi.match_range("Data heterogeneity and unstable", "diverse dynamics")
    assert reason is None
    text = " ".join(w[4] for w in ws)
    assert text.startswith("Data heterogeneity") and text.endswith("diverse dynamics.")
    assert pi.match_range("Data", "dynamics")[0] is None, "anchors of a word or two are refused"
    assert pi.match_range("diverse dynamics", "Data heterogeneity")[0] is None, "end before start"
    ws, reason = pi.match_range("learning", "dynamics")
    assert ws is None and "spans" in reason, "ambiguous anchors are refused with the span count"
    ws, reason = pi.match_range("learning", "dynamics", occurrence=1)
    assert reason is None and ws, "an explicit occurrence selects among ambiguous spans"
    assert pi.match_range("learning", "dynamics", occurrence=9)[0] is None


def test_ellipsis_span_in_build(pdf_path, tmp_path):
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": pdf_path, "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path),
                "preview_pages": [], "highlights": [
                    {"page": 1, "core": True, "text": "Foundation models have transformed … remains a challenge", "comment": "x"}]})
    out, missed = cli.build(cfg)
    assert not missed and out[0]["text"].startswith("Foundation models") and out[0]["text"].endswith("remains a challenge.")


def test_missed_reports_closest_and_snap(pdf_path, tmp_path):
    base = {"pdf": pdf_path, "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": []}
    typo = "Data heterogenity and unstable long-term dynamics inhibit learning"  # missing an 'e'
    cfg = dict(cli.DEFAULTS); cfg.update(base); cfg["highlights"] = [{"page": 1, "text": typo, "comment": "x"}]
    out, missed = cli.build(cfg)
    assert not out and len(missed) == 1
    assert missed[0]["similarity"] >= 0.9 and "heterogeneity" in missed[0]["closest"]
    cfg = dict(cli.DEFAULTS); cfg.update(base, snap=True); cfg["highlights"] = [{"page": 1, "text": typo, "comment": "x"}]
    out, missed = cli.build(cfg)
    assert not missed and out[0]["snapped"] >= 0.95 and "heterogeneity" in out[0]["text"]


def test_translation_check_ignores_math_tags_and_hyphen_halves():
    anns = [
        {"type": "highlight", "text": "the scatter- add operation", "comment": "scatter-add 操作", "pageLabel": "1"},
        {"type": "highlight", "text": "attention weights", "comment": "注意力权重 $\\frac{1}{\\sqrt{d_k}}$ 与 d<sub>k</sub>", "pageLabel": "1"},
        {"type": "highlight", "text": "the model uses attention", "comment": "该模型用 attention，另外还讨论了 diffusion", "pageLabel": "1"},
    ]
    ws = cli.check_translations(anns)
    assert len(ws) == 1 and "diffusion" in ws[0]["reasons"][0]


def test_extract_text_dehyphenates_pages_and_cuts_references(tmp_path):
    doc = pymupdf.open()
    for pno in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_text((250, 30), "Running Head Journal", fontsize=9)
        if pno == 0:
            page.insert_textbox(pymupdf.Rect(72, 100, 132, 300), "stabili- zation", fontsize=10, fontname="helv")
        elif pno == 1:
            page.insert_text((72, 120), "Second page body text.", fontsize=10)
        else:
            page.insert_text((72, 100), "References", fontsize=12)
            page.insert_text((72, 130), "[1] A. Vaswani, Attention is all you need. NeurIPS, 2017.", fontsize=9)
            page.insert_text((72, 160), "Appendix A Results", fontsize=12)
            page.insert_text((72, 190), "Extra ablation details.", fontsize=10)
        page.insert_text((300, 770), str(pno + 1), fontsize=9)
    fp = tmp_path / "extract.pdf"; doc.save(str(fp)); doc.close()
    text = cli.extract_text(str(fp))
    assert "--- p.1 ---" in text and "--- p.2 ---" in text and "--- p.3 ---" in text
    assert "stabilization" in text, "hyphenation across the line break is joined"
    assert "Running Head" not in text, "the running header is dropped"
    assert "[references removed]" in text and "Vaswani" not in text
    assert "Appendix A Results" in text and "Extra ablation details." in text


@pytest.mark.parametrize("heading", ["7 References", "References:", "VII. REFERENCES", "References and Notes", "Literature Cited",
                                     "参考文献"])
def test_extract_cuts_numbered_and_other_reference_headings(tmp_path, heading):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "The conclusion of the paper is stated here.", fontsize=10)
    page.insert_text((72, 140), heading, fontsize=12, fontname="china-s" if heading == "参考文献" else "helv")
    page.insert_text((72, 170), "[1] A. Vaswani, Attention is all you need. NeurIPS, 2017.", fontsize=9)
    page.insert_text((72, 200), "Appendix A Results", fontsize=12)
    page.insert_text((72, 230), "Extra ablation details.", fontsize=10)
    fp = tmp_path / "refs.pdf"; doc.save(str(fp)); doc.close()
    text = cli.extract_text(str(fp))
    assert "[references removed]" in text and "Vaswani" not in text and heading not in text
    assert "The conclusion of the paper" in text and "Extra ablation details." in text
    assert "Vaswani" in cli.extract_text(str(fp), keep_references=True)


def _checklist_pdf(path, heading, appendix=True):
    """A section about a checklist, a section called like a paper checklist, the bibliography, the paper checklist (its
    answers point to an appendix), and optionally the appendix."""
    doc = pymupdf.open()
    pages = [[("3 A Checklist for Robust Evaluation", 12), ("We list the checks that every benchmark run should pass.", 10),
              ("2 Checklist", 12), ("Our own checklist for the reader, part of the paper.", 10)],
             [("References", 12), ("[1] A. Vaswani, Attention is all you need. NeurIPS, 2017.", 9)],
             [(heading, 12), ("1. Claims", 10), ("Answer: [Yes] The claims are supported by the proofs in", 10),
              ("Appendix B of the paper.", 10)]]
    if appendix:
        pages.append([("Appendix A Proofs", 12), ("The proof of the first theorem follows.", 10)])
    for lines in pages:
        page = doc.new_page(width=612, height=792)
        for i, (text, size) in enumerate(lines):
            page.insert_text((72, 100 + 30 * i), text, fontsize=size)
    doc.save(str(path)); doc.close()
    return str(path)


@pytest.mark.parametrize("heading", ["NeurIPS Paper Checklist", "Reproducibility Checklist", "Checklist"])
def test_extract_cuts_a_paper_checklist_up_to_the_appendix(tmp_path, heading):
    text = cli.extract_text(_checklist_pdf(tmp_path / "c.pdf", heading), keep_references=True)
    assert "3 A Checklist for Robust Evaluation" in text and "We list the checks" in text, "a section about a checklist stays"
    assert "Our own checklist for the reader" in text, "before the bibliography a section called so stays"
    assert "--- p.3 ---\n[checklist removed]\n" in text and "Answer: [Yes]" not in text
    assert "Appendix B of the paper." not in text, "a line of the checklist that starts with Appendix is no appendix heading"
    assert "Appendix A Proofs" in text and "The proof of the first theorem follows." in text
    text = cli.extract_text(_checklist_pdf(tmp_path / "end.pdf", heading, appendix=False))
    assert text.rstrip().endswith("[checklist removed]"), "without an appendix after it, the checklist runs to the end"


def test_extract_marks_a_rotated_page(tmp_path, capsys):
    """Nothing is written on a rotated page: its page marker says so, and its text is still listed."""
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 700), f"Page {i + 1} says that the method improves the result. "
                            "It also runs fast on every benchmark.", fontsize=10, fontname="helv")
    doc[1].set_rotation(90)
    fp = tmp_path / "rotated.pdf"; doc.save(str(fp)); doc.close()
    text = cli.extract_text(str(fp))
    assert "--- p.1 ---\nPage 1 says" in text and "--- p.2 (rotated: not annotatable) ---\nPage 2 says" in text
    cli.extract_main(["--pdf", str(fp), "--sentences", str(tmp_path / "s.json"), "--out", str(tmp_path / "s.txt")])
    listing = (tmp_path / "s.txt").read_text(encoding="utf8")
    assert listing.startswith("--- p.1 ---\n") and "--- p.2 (rotated: not annotatable) ---\n3 | Page 2 says" in listing


def test_duplicate_sentence_reports_occurrences(tmp_path):
    doc = pymupdf.open(); page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "The same sentence appears here.", fontsize=10)
    page.insert_text((72, 140), "Unrelated middle text for the anchor paragraph.", fontsize=10)
    page.insert_text((72, 180), "The same sentence appears here.", fontsize=10)
    fp = tmp_path / "dup.pdf"; doc.save(str(fp)); doc.close()
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": str(fp), "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
                "highlights": [{"page": 1, "text": "The same sentence appears here.", "comment": "x"}],
                "summaries": [{"page": 1, "anchor": "Unrelated middle text", "text": "note"}]})
    out, missed = cli.build(cfg)
    assert not missed
    hl = [a for a in out if a["type"] == "highlight"][0]
    assert hl["occurrences"] == 2, "a duplicated sentence is flagged"
    assert hl["position"]["rects"][0][1] > 650, "the first occurrence (higher on the page) is highlighted"
    tx = [a for a in out if a["type"] == "text"][0]
    assert "occurrences" not in tx, "a unique anchor is not flagged"
    cfg["highlights"] = [{"page": 1, "text": "The same sentence appears here.", "comment": "x", "occurrence": 2}]
    out, missed = cli.build(cfg)
    hl = [a for a in out if a["type"] == "highlight"][0]
    assert not missed and "occurrences" not in hl, "an explicit occurrence is not warned about"
    assert hl["position"]["rects"][0][1] < 650, "occurrence 2 highlights the lower instance"
    cfg["highlights"] = [{"page": 1, "text": "The same sentence appears here.", "comment": "x", "occurrence": 3}]
    out, missed = cli.build(cfg)
    assert missed and "occurs 2 time" in missed[0]["reason"]


def test_style_warnings_flag_mechanical_defects(pdf_path, tmp_path):
    note = tmp_path / "note.html"
    note.write_text('<h1>T</h1><p>inline <span class="math">$\\\\frac{a}{b}$</span>, raw $y^2$ here, 值得注意</p>', encoding="utf8")
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": pdf_path, "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
                "note_html": str(note), "core_range": [2, 3], "banned_phrases": ["值得注意"], "cleanup": True,
                "highlights": [
                    {"page": 1, "core": True, "text": "Foundation models have transformed machine learning", "comment": "基础模型 $x^2$ 改变了机器学习"},
                    {"page": 1, "core": False, "text": "Data heterogeneity and unstable long-term dynamics", "comment": "QK^T 与 10−3 不稳定"},
                    {"page": 1, "core": False, "text": "Data heterogeneity and unstable long-term dynamics", "comment": "重复一次"},
                    {"page": 1, "core": False, "text": "patch jittering, a stabilization method", "comment": "值得注意 <span>补丁</span> 抖动<sub>k"},
                ],
                "summaries": [
                    {"page": 1, "anchor": "Our work contributes", "text": "方法：三招→吞吐 ①"},
                    {"page": 1, "anchor": "topology-aware sampling", "text": "第一行\n第二行"},
                ]})
    out, missed = cli.build(cfg)
    assert not missed
    first = [a for a in out if a["type"] == "highlight"][0]
    listing = {"annotations": [
        {"key": "USER1", "type": "highlight", "tags": [], "position": {"pageIndex": 0, "rects": first["position"]["rects"][:1]}},
        {"key": "OWN1", "type": "highlight", "tags": ["zotero-scholium"], "position": {"pageIndex": 0, "rects": first["position"]["rects"][:1]}},
    ]}
    w = cli.check_style(out, cfg, listing, note.read_text(encoding="utf8"))
    kinds = {x["kind"] for x in w}
    assert {"latex", "math_format", "tag", "symbol", "label", "line_break", "banned_phrase", "duplicate",
            "user_overlap", "core_count", "note_math"} <= kinds, kinds
    assert sum(1 for x in w if x["kind"] == "user_overlap") == 1, "the tool's own earlier annotation is replaced, not an overlap"
    assert any("USER1" in x["reason"] for x in w)
    assert any(x["kind"] == "core_count" and "1 " in x["reason"] for x in w)
    assert sum(1 for x in w if x["kind"] == "note_math") == 2, "double backslash in a math node; LaTeX outside a node"
    assert all(x["kind"] != "user_overlap" for x in cli.check_style(out, cfg, None, None))
    cfg["highlights"] = [{"page": 1, "core": True, "text": "Foundation models have transformed machine learning", "comment": "基础模型改变了机器学习，d<sub>k</sub> 与 x<sup>2</sup> 正常。"},
                         {"page": 1, "core": True, "text": "patch jittering, a stabilization method", "comment": "补丁抖动，一种稳定化方法"}]
    cfg["summaries"] = [{"page": 1, "anchor": "Our work contributes", "text": "这三招里拓扑感知采样贡献最大。"}]
    note.write_text('<h1>T</h1><p><span class="math">$\\frac{a}{b}$</span> <pre class="math">$$x^2$$</pre></p>', encoding="utf8")
    out, missed = cli.build(cfg)
    own_only = {"annotations": listing["annotations"][1:]}
    assert not missed and cli.check_style(out, cfg, own_only, note.read_text(encoding="utf8")) == []


def test_compact_listing_counts_and_details_only_others():
    listing = {"ok": True, "backend": "api", "attachmentKey": "A", "notes": [{"key": "N1", "title": "T"}], "annotations": [
        {"key": "K1", "type": "highlight", "color": "#ff6666", "tags": ["zotero-scholium"], "pageLabel": "1", "text": "a", "comment": "b", "position": {"pageIndex": 0, "rects": [[0, 0, 1, 1]]}},
        {"key": "K2", "type": "text", "color": "#1a73e8", "tags": ["zotero-scholium"], "pageLabel": "2", "text": "", "comment": "c", "position": {"pageIndex": 1, "rects": [[0, 0, 1, 1]]}},
        {"key": "U1", "type": "highlight", "color": "#ffd400", "tags": [], "pageLabel": "3", "text": "user's own", "comment": "", "position": {"pageIndex": 2, "rects": [[0, 0, 1, 1]]}}]}
    c = cli.compact_listing(listing)
    assert (c["annotations"], c["own"], c["others"]) == (3, 2, 1)
    assert c["by_type"] == {"highlight": 2, "text": 1} and c["by_color"] == {"#ff6666": 1, "#1a73e8": 1, "#ffd400": 1}
    assert c["others_detail"] == [{"key": "U1", "type": "highlight", "color": "#ffd400", "page": "3", "text": "user's own"}]
    assert c["notes"] == [{"key": "N1", "title": "T"}] and c["backend"] == "api"


def test_a_box_taller_than_the_room_is_reported():
    b = {"y_top": 750.0, "h": 800.0}
    cli.place_blocks([b], [], floor=28.0, ceiling=772.0)
    assert b["y_top"] == 772.0 and "taller" in b["layout_warning"]


def test_a_margin_too_narrow_even_for_a_sticky_note_is_reported(tmp_path):
    pdf = _page_pdf(tmp_path / "narrow.pdf", lambda pg: pg.insert_textbox(pymupdf.Rect(20, 72, 604, 760), LEFT * 14, fontsize=10, fontname="helv"))
    cfg = _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "A note."}])
    out, missed = cli.build(cfg)
    assert missed == [] and out[0]["type"] == "note" and "covers the text" in out[0]["layout_warning"]


ANCHOR = "Foundation models have transformed"


def _one_column_pdf(tmp_path):
    """One column from x = 100 to 500: the right margin is the wider one."""
    return _page_pdf(tmp_path / "one.pdf", lambda pg: pg.insert_textbox(pymupdf.Rect(100, 72, 500, 700), LEFT * 8, fontsize=10, fontname="helv"))


def _margin_build(pdf, tmp_path, obstacles=None, **item):
    cfg = _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               summaries=[dict({"page": 1, "anchor": ANCHOR, "text": "A remark of the reader beside the paragraph."}, **item)])
    out, missed = cli.build(cfg, obstacles)
    assert missed == [] and len(out) == 1
    return out[0], cli.PageIndex(pymupdf.open(pdf)[0])


def test_a_margin_box_without_room_takes_the_other_margin_of_a_one_column_page(tmp_path):
    pdf = _one_column_pdf(tmp_path)
    a, pi = _margin_build(pdf, tmp_path)
    assert a["type"] == "text" and a["position"]["rects"][0][0] >= pi.body_x1, "the wider margin first"
    a, pi = _margin_build(pdf, tmp_path, {0: [[pi.body_x1 + 1, 0, 612, 792]]})   # something fills the right margin
    x0, y0, x1, y1 = a["position"]["rects"][0]
    assert a["type"] == "text" and x1 <= pi.body_x0 and "layout_warning" not in a and "as_note" not in a


def test_a_margin_box_without_room_in_either_margin_becomes_a_sticky_note(tmp_path):
    text = " ".join([BAND_SENTENCE] * 40)          # taller than the page in either margin
    a, pi = _margin_build(_one_column_pdf(tmp_path), tmp_path, text=text)
    x0, y0, x1, y1 = a["position"]["rects"][0]
    assert a["type"] == "note" and a["comment"] == text and a["as_note"] and "layout_warning" not in a
    assert x0 >= pi.body_x1 and x1 - x0 == pytest.approx(cli.NOTE_ICON), "beside the paragraph in its own margin, hugging the column"
    line = pi.line_rects(pi.match(ANCHOR))[0]
    assert y1 == pytest.approx(pi.H - line.y0 + 1), "at the first line of its paragraph"


def test_a_margin_box_keeps_its_side_on_two_columns_and_when_side_is_set(pdf_path, tmp_path):
    pi = cli.PageIndex(pymupdf.open(pdf_path)[0])
    a, _ = _margin_build(pdf_path, tmp_path, {0: [[0, 0, pi.body_x0 - 1, 792]]})   # the left margin is full; the right one is free
    assert a["type"] == "note" and a["position"]["rects"][0][2] <= pi.body_x0, "no move to the other column's margin"
    pdf = _one_column_pdf(tmp_path)
    one = cli.PageIndex(pymupdf.open(pdf)[0])
    a, _ = _margin_build(pdf, tmp_path, {0: [[one.body_x1 + 1, 0, 612, 792]]}, side="right")
    assert a["type"] == "note" and a["position"]["rects"][0][0] >= one.body_x1, "a side that is set is kept"


def test_a_margin_box_turned_into_a_sticky_note_does_not_block_apply(tmp_path, capsys):
    cp = tmp_path / "config.json"
    json.dump({"pdf": _one_column_pdf(tmp_path), "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path),
               "summaries": [{"page": 1, "anchor": ANCHOR, "text": " ".join([BAND_SENTENCE] * 40)}]}, open(cp, "w", encoding="utf8"))
    with pytest.raises(SystemExit):
        cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing"])
    rep = json.loads(capsys.readouterr().out)
    assert rep["layout_warnings"] == [] and rep["as_notes"] == [{"page": "1", "text": BAND_SENTENCE[:60]}]
    assert rep["sticky_notes"] == 1 and rep["backend"] == "js"


def test_nothing_is_written_on_a_rotated_page(tmp_path):
    def draw(pg):
        pg.insert_textbox(pymupdf.Rect(72, 72, 540, 700), LEFT * 3, fontsize=10, fontname="helv")
        pg.set_rotation(90)
    pdf = _page_pdf(tmp_path / "rotated.pdf", draw)
    cfg = _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               highlights=[{"page": 1, "text": "Foundation models have transformed"}],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "A note."}])
    out, missed = cli.build(cfg)
    assert out == [] and [m["kind"] for m in missed] == ["highlight", "summary"]
    assert all("rotated" in m["reason"] for m in missed)


def test_layout_warnings_block_apply(tmp_path, capsys):
    pdf = _page_pdf(tmp_path / "narrow.pdf", lambda pg: pg.insert_textbox(pymupdf.Rect(20, 72, 604, 760), LEFT * 14, fontsize=10, fontname="helv"))
    cp = tmp_path / "config.json"
    json.dump({"pdf": pdf, "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
               "summaries": [{"page": 1, "anchor": "Foundation models have transformed", "text": "A note."}]}, open(cp, "w", encoding="utf8"))
    with pytest.raises(SystemExit):
        cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing"])
    rep = json.loads(capsys.readouterr().out)
    assert rep["layout_warnings"] and rep["applied"] is False and "layout warnings" in rep["apply_error"] and "backend" not in rep
    with pytest.raises(SystemExit):
        cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing", "--allow-warnings"])
    rep = json.loads(capsys.readouterr().out)
    assert rep["backend"] == "js" and "layout warnings" not in (rep.get("apply_error") or "")


def _cropped_pdf(tmp_path):
    """The two columns on a page whose crop box is [50 50 562 732], as some publishers' PDFs have it."""
    p = tmp_path / "cropped.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(110, 120, 297, 700), LEFT, fontsize=10, fontname="helv")
    page.insert_textbox(pymupdf.Rect(315, 120, 500, 700), RIGHT, fontsize=10, fontname="helv")
    page.set_cropbox(pymupdf.Rect(50, 60, 562, 742))
    doc.save(str(p)); doc.close()
    return str(p)


def test_positions_are_in_pdf_user_space_when_the_crop_box_does_not_start_at_zero(tmp_path):
    """Zotero stores PDF user space; MuPDF measures from the crop box's corner."""
    pdf = _cropped_pdf(tmp_path)
    cfg = _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[1],
               highlights=[{"page": 1, "text": "patch jittering", "comment": "x"}],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "a remark"}])
    out, missed = cli.build(cfg)
    assert not missed
    page = pymupdf.open(pdf)[0]
    word = page.search_for("patch jittering")[0] * ~page.transformation_matrix
    hl = next(a for a in out if a["type"] == "highlight")["position"]["rects"][0]
    assert abs(hl[0] - word.x0) < 1.5 and abs(hl[1] - word.y0) < 1.5 and abs(hl[3] - word.y1) < 1.5
    box = next(a for a in out if a["type"] == "text")["position"]["rects"][0]
    assert 50 <= box[0] < box[2] <= 110, "the margin box sits in the visible left margin, beside the column"
    assert 50 <= box[1] < box[3] <= 732


def test_existing_annotations_count_in_pdf_user_space_on_an_offset_page(tmp_path):
    pdf = _cropped_pdf(tmp_path)
    cfg = _cfg(pdf=pdf, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               summaries=[{"page": 1, "anchor": "Foundation models have transformed", "text": "a remark beside a user's note"}])
    out, _ = cli.build(cfg)
    x0, y0, x1, y1 = out[0]["position"]["rects"][0]
    note = [x0, y0 - 5, x1, y1 + 5]                         # the user's text box where the remark wants to go
    out2, _ = cli.build(cfg, {0: [note]})
    _, b0, _, b1 = out2[0]["position"]["rects"][0]
    assert b1 <= note[1] or b0 >= note[3], "the box must not overlap the existing annotation"


@pytest.mark.parametrize("comment", ["若 x<y，则 f(x)>f(y)。", "当 n<k 且 k>m 时成立。", "比例为 3:1 时效果最好。", "按 3：1 混合。",
                                     "按 3 : 1 混合。"])
def test_comparisons_and_ratios_are_not_markup_or_labels(comment):
    assert cli._text_defects(comment, page=False) == []
    assert not cli.LABEL_RE.match(comment)


@pytest.mark.parametrize("comment, kind", [("用 <em>强调</em>", "tag"), ('<span class="x">a</span>', "tag"), ("x<br/>y", "tag")])
def test_real_tags_are_still_reported(comment, kind):
    assert [k for k, _ in cli._text_defects(comment, page=False)] == [kind]
    assert cli.LABEL_RE.match("方法：三招") and cli.LABEL_RE.match("结论：2 倍加速来自缓存。") and cli.LABEL_RE.match("Step 2: do")


def test_a_rewrite_that_would_undo_the_users_change_is_reported(pdf_path, tmp_path):
    """With cleanup, a tool's annotation the user changed in Zotero after it was written must be kept by the configuration."""
    text = "patch jittering, a stabilization method"
    cfg = _cfg(pdf=pdf_path, item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[], cleanup=True,
               highlights=[{"page": 1, "text": text, "comment": "补丁抖动，一种稳定化方法"}])
    out, _ = cli.build(cfg)

    def listing(comment, added="2026-10-20 05:00:00", modified="2026-10-20 05:00:00"):
        return {"annotations": [{"key": "OWN1", "type": "highlight", "color": cfg["other_color"], "tags": [cli.TAG], "pageLabel": "1",
                                 "text": out[0]["text"], "comment": comment, "added": added, "modified": modified,
                                 "position": {"pageIndex": 0, "rects": out[0]["position"]["rects"]}}]}
    kinds = lambda lst, c=cfg: [w["kind"] for w in cli.check_style(out, c, lst, None)]
    edited = listing("补丁抖动：用户改过的译文", modified="2026-10-21T09:00:00Z")
    w = [x for x in cli.check_style(out, cfg, edited, None) if x["kind"] == "user_edit"]
    assert len(w) == 1 and "OWN1" in w[0]["reason"] and "补丁抖动：用户改过的译文" in w[0]["reason"]
    assert "user_edit" not in kinds(listing("补丁抖动：用户改过的译文")), "written by the tool and never changed: replaced quietly"
    assert "user_edit" not in kinds(listing("补丁抖动，一种稳定化方法", modified="2026-10-21 09:00:00")), "the configuration keeps the change"
    assert "user_edit" not in kinds(edited, dict(cfg, cleanup=False)), "without cleanup nothing is replaced"
