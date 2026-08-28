"""Tests against a synthetic two-column PDF generated at run time (no third-party content)."""
import json, os
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


def test_render_js_is_self_contained(tmp_path):
    cfg = dict(cli.DEFAULTS); cfg.update({"item_key": "I", "attachment_key": "A", "author": "bot"})
    js = cli.render_js(cfg, [{"type": "text", "color": "#1a73e8", "comment": "hi", "pageLabel": "1",
                              "sortIndex": "00000|000000|00001", "position": {"pageIndex": 0, "rects": [[1, 2, 3, 4]], "fontSize": 8, "rotation": 0}}])
    assert "Zotero.Items.getByLibraryAndKey" in js and json.dumps(cli.TAG) in js


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

