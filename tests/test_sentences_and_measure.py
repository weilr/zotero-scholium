"""Sentence numbering (extract --sentences), id-based configuration entries, apply blockers, and the measuring scripts."""
import json, os, subprocess, sys
import pymupdf
import pytest

from zotero_scholium import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_split_sentences_keeps_abbreviations_and_decimals():
    text = ("We follow Vaswani et al. (2017) and Fig. 3 shows the results. The model uses 0.5 dropout, i.e. half "
            "of the units. It works! Does it scale? See Sec. 4.2 for details.")
    parts = cli.split_sentences(text)
    assert parts == ["We follow Vaswani et al. (2017) and Fig. 3 shows the results.",
                     "The model uses 0.5 dropout, i.e. half of the units. It works!",
                     "Does it scale?", "See Sec. 4.2 for details."], "a fragment of fewer than three words merges"
    assert cli.split_sentences("Proof. Trivial by induction on n.") == ["Proof. Trivial by induction on n."]
    assert cli.split_sentences("Theorem 2. The bound is tight. See Fig. 4.") == ["Theorem 2. The bound is tight.", "See Fig. 4."]


def _three_page_pdf(path):
    doc = pymupdf.open()
    for p in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_text((250, 30), "Running header", fontsize=8)
        if p == 0:
            page.insert_text((72, 80), "Deep Sets Revisited", fontsize=16)
            page.insert_textbox(pymupdf.Rect(72, 110, 540, 400),
                                "Foundation models have transformed language processing. We study permutation invariance "
                                "of set functions. The stabili- zation method reduces error by 40%. Fig. 2 shows this.",
                                fontsize=10, fontname="helv")
        elif p == 1:
            page.insert_text((72, 80), "3 Method", fontsize=13)
            page.insert_textbox(pymupdf.Rect(72, 110, 540, 300),
                                "Each element is encoded independently. The encodings are pooled with a sum.",
                                fontsize=10, fontname="helv")
            page.insert_textbox(pymupdf.Rect(72, 320, 540, 500),
                                "The encodings are pooled with a sum. A second identical sentence tests numbering.",
                                fontsize=10, fontname="helv")
        else:
            page.insert_text((72, 80), "References", fontsize=13)
            page.insert_textbox(pymupdf.Rect(72, 110, 540, 300), "[1] A. Author. A paper. 2020.", fontsize=10, fontname="helv")
        page.insert_text((300, 770), str(p + 1), fontsize=9)
    doc.save(path); doc.close()


def test_extract_sentences_numbers_paragraphs_and_headings(tmp_path):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    items = cli.extract_sentences(str(fp))
    sents = [i for i in items if "id" in i]
    ids = [i["id"] for i in sents]
    assert ids == list(range(1, len(ids) + 1)), "ids are 1-based and consecutive across pages"
    assert sents[0]["page"] == 1 and any(s["page"] == 2 for s in sents)
    assert not any("Running header" in s["text"] for s in sents) and not any("A. Author" in s["text"] for s in sents)
    assert any(s["text"].startswith("The stabilization method") for s in sents), "hyphenation is joined"
    headings = [i["heading"] for i in items if "heading" in i]
    assert "3 Method" in headings
    pooled = [s for s in sents if s["text"] == "The encodings are pooled with a sum."]
    assert len(pooled) == 2 and pooled[0]["para"] != pooled[1]["para"], "identical sentences keep separate ids"
    listing = cli.render_sentences(items)
    assert "--- p.2 ---" in listing and "## 3 Method" in listing
    assert f"{pooled[0]['id']} | The encodings are pooled with a sum." in listing
    assert "\n\n" in listing.split("--- p.2 ---")[1], "paragraphs are separated by a blank line"


def test_build_resolves_ids_ranges_and_summary_ids(tmp_path):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    sfile = tmp_path / "sentences.json"
    cli.extract_main(["--pdf", str(fp), "--sentences", str(sfile)])
    items = json.loads(sfile.read_text(encoding="utf8"))["sentences"]
    sents = {i["id"]: i for i in items if "id" in i}
    first = next(i for i in sents.values() if i["text"].startswith("Foundation models"))
    study = first["id"] + 1
    pooled = [i for i in sents.values() if i["text"] == "The encodings are pooled with a sum."]
    cfg = dict(cli.DEFAULTS)
    cfg.update({"pdf": str(fp), "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
                "sentences": str(sfile),
                "highlights": [{"id": first["id"], "core": True, "comment": "基础模型改变了语言处理。"},
                               {"ids": [study, study + 1], "core": False, "comment": "两句连起来。"},
                               {"id": pooled[1]["id"], "core": False, "comment": "第二处。"},
                               {"id": 9999, "comment": "x"}],
                "summaries": [{"id": pooled[1]["id"], "text": "这段用求和池化。"}, {"id": 4242, "text": "x"}]})
    out, missed = cli.build(cfg)
    hl = [a for a in out if a["type"] == "highlight"]
    assert [cli.norm_str(a["text"]) for a in hl][:2] == [cli.norm_str(first["text"]),
                                                          cli.norm_str(sents[study]["text"] + " " + sents[study + 1]["text"])]
    assert hl[1]["position"]["rects"] and hl[0]["position"]["pageIndex"] == 0
    assert hl[2]["position"]["pageIndex"] == 1 and "occurrences" not in hl[2], "an id names one occurrence; no ambiguity warning"
    assert hl[2]["position"]["rects"][0][1] < 500, "the second identical sentence (lower on the page) is highlighted"
    tx = [a for a in out if a["type"] == "text"]
    assert tx and tx[0]["position"]["pageIndex"] == 1
    assert sorted(m.get("id") for m in missed) == [4242, 9999] and all("unknown sentence id" in m["reason"] for m in missed)


def test_a_range_across_a_heading_names_the_heading_and_where_to_split(tmp_path):
    fp = tmp_path / "paper.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(72, 110, 540, 200), "The dataset consists of many hulls with different shapes. "
                        "It is the only dataset that is in water.", fontsize=10, fontname="helv")
    page.insert_text((72, 230), "Data Generation.", fontsize=13)
    page.insert_textbox(pymupdf.Rect(72, 250, 540, 400), "Samples are solved as steady RANS on a finite-volume solver.",
                        fontsize=10, fontname="helv")
    doc.save(str(fp)); doc.close()
    sfile = tmp_path / "sentences.json"
    cli.extract_main(["--pdf", str(fp), "--sentences", str(sfile)])
    sents = [i for i in json.loads(sfile.read_text(encoding="utf8"))["sentences"] if "id" in i]
    assert len(sents) == 3
    cfg = dict(cli.DEFAULTS, pdf=str(fp), item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[], sentences=str(sfile),
               highlights=[{"ids": [1, 3], "comment": "x"}, {"ids": [1, 2], "comment": "y"}])
    out, missed = cli.build(cfg)
    assert len(out) == 1 and [m["id"] for m in missed] == [[1, 3]]
    assert missed[0]["reason"] == ("sentences 1–3 are not one passage: the heading “Data Generation.” stands between sentence 2 and "
                                   "sentence 3; split the range there")


def test_apply_is_blocked_by_style_warnings_and_reports_pdf_hash(tmp_path, capsys):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    cfg = {"pdf": str(fp), "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
           "highlights": [{"page": 1, "text": "Foundation models have transformed language processing.", "comment": "基础模型 $x$"}]}
    cp = tmp_path / "config.json"; json.dump(cfg, open(cp, "w", encoding="utf8"))
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing", "--verbose"])
    rep = json.loads(capsys.readouterr().out)
    assert e.value.code == 2 and rep["applied"] is False and "style warnings" in rep["apply_error"]
    assert rep["pdf_sha256"]["unchanged"] is True and len(rep["pdf_sha256"]["before"]) == 64
    cfg["highlights"][0]["comment"] = "基础模型改变了语言处理。"
    json.dump(cfg, open(cp, "w", encoding="utf8"))
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing"])
    rep = json.loads(capsys.readouterr().out)
    assert "style_warnings" not in rep and rep["backend"] == "js" and rep["applied"] is False and "fallback" in rep
    assert "pdf_sha256" not in rep and "js" not in rep and rep["fallback"].endswith("create_annotations.js"), \
        "the hashes of an unchanged PDF and the file's path twice are left out"
    assert rep["backend_reason"], "a write that did not happen says why"


def test_extract_main_writes_numbered_listing_and_json(tmp_path, capsys):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    out = tmp_path / "sentences.txt"; js = tmp_path / "sentences.json"
    cli.extract_main(["--pdf", str(fp), "--out", str(out), "--sentences", str(js)])
    assert "sentences" in capsys.readouterr().out
    listing = out.read_text(encoding="utf8"); data = json.load(open(js, encoding="utf8"))
    assert listing.startswith("Index (line numbers of this file)\n") and "1 | " in listing
    assert listing.split("\n\n", 1)[1].startswith("--- p.1 ---"), "the listing follows the index"
    assert data["pdf"] == str(fp) and data["sentences"][0]["id"] == 1
    cli.extract_main(["--pdf", str(fp), "--out", str(out), "--sentences", str(js), "--pages", "2"])
    part = out.read_text(encoding="utf8"); capsys.readouterr()
    first_id = int(next(ln for ln in part.split("\n") if " | " in ln).split(" | ")[0])
    assert part.split("\n\n", 1)[1].startswith("--- p.2 ---") and "--- p.1 ---" not in part and first_id > 1, \
        "ids keep counting over the whole document"
    assert "pages: p.2 4\n" in part, "the index covers the pages listed"


def _paper_with_appendix(path, before_refs=None, first="Appendix A Proofs", then="B Further results"):
    """Two pages of main text, the references, an appendix of two sections (their headings first and then, none after
    the references when first is None); optionally a main-text section called like an appendix before the references."""
    pages = [[("1 Introduction", 13), ("The method improves the result on every benchmark.", 10)],
             [("2 Method", 13), ("Each element is encoded independently of the others.", 10)]
             + ([(before_refs, 13), ("These runs repeat the main experiment twice.", 10)] if before_refs else []),
             [("References", 13), ("[1] A. Author. A paper. 2020.", 9)]]
    if first:
        pages += [[(first, 13), ("The proof of the first theorem follows here.", 10)],
                  [(then, 13), ("More ablations are shown in this table.", 10)]]
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=612, height=792)
        for i, (text, size) in enumerate(lines):
            page.insert_text((72, 100 + 30 * i), text, fontsize=size)
    doc.save(str(path)); doc.close()
    return str(path)


def _index(text):
    """The index of a listing file as {name: value} and the file's lines."""
    lines = text.split("\n")
    head = lines[:lines.index("")]
    assert head[0] == "Index (line numbers of this file)"
    return dict(line.split(": ", 1) for line in head[1:]), lines


def test_the_listing_file_starts_with_an_index_of_its_lines(tmp_path, capsys):
    fp = _paper_with_appendix(tmp_path / "paper.pdf")
    js, out = tmp_path / "sentences.json", tmp_path / "sentences.txt"
    cli.extract_main(["--pdf", fp, "--sentences", str(js), "--out", str(out)])
    text = out.read_text(encoding="utf8")
    index, lines = _index(text)
    assert index == {"main text": "lines 7-15", "references": "line 16 (p.3)", "appendix": "from line 19 (p.4)",
                     "pages": "p.1 7, p.2 11, p.3 15, p.4 18, p.5 22"}
    for part in index["pages"].split(", "):
        page, line = part[2:].split(" ")
        assert lines[int(line) - 1] == f"--- p.{page} ---", part
    assert lines[15] == "[references removed]" and lines[18] == "## Appendix A Proofs"
    assert lines[6:15][2].startswith("1 | The method improves") and lines[14] == "--- p.3 ---", \
        "the main text ends before the references"
    items = cli.extract_sentences(fp)
    assert text.split("\n\n", 1)[1] == cli.render_sentences(items), "the listing after the index is unchanged"
    # on standard output there is no index
    capsys.readouterr()
    cli.extract_main(["--pdf", fp, "--sentences", str(js)])
    assert capsys.readouterr().out.startswith("--- p.1 ---")


def test_the_index_with_the_references_kept_and_without_them(tmp_path, capsys):
    fp = _paper_with_appendix(tmp_path / "paper.pdf")
    js, out = tmp_path / "sentences.json", tmp_path / "sentences.txt"
    cli.extract_main(["--pdf", fp, "--sentences", str(js), "--out", str(out), "--keep-references"])
    index, lines = _index(out.read_text(encoding="utf8"))
    ref = int(index["references"].split()[1])
    assert lines[ref - 1] == "## References" and index["references"].endswith("(p.3)")
    assert lines[int(index["appendix"].split()[2]) - 1] == "## Appendix A Proofs"
    # a paper without references: the pages only
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page(width=612, height=792).insert_text((72, 100), f"Page {i + 1} says that the method improves the result.", fontsize=10)
    plain = tmp_path / "plain.pdf"; doc.save(str(plain)); doc.close()
    cli.extract_main(["--pdf", str(plain), "--sentences", str(js), "--out", str(out)])
    index, lines = _index(out.read_text(encoding="utf8"))
    assert index == {"pages": "p.1 4, p.2 7"} and lines[3] == "--- p.1 ---" and lines[6] == "--- p.2 ---"


@pytest.mark.parametrize("keep", [False, True])
def test_the_text_after_the_references_without_an_appendix_heading(tmp_path, keep):
    # the appendix's sections are "A Mathematical Derivations", "B …" (DPO): the text after the references is listed
    fp = _paper_with_appendix(tmp_path / "paper.pdf", first="A Mathematical Derivations")
    js, out = tmp_path / "sentences.json", tmp_path / "sentences.txt"
    cli.extract_main(["--pdf", fp, "--sentences", str(js), "--out", str(out)] + (["--keep-references"] if keep else []))
    index, lines = _index(out.read_text(encoding="utf8"))
    assert set(index) == {"main text", "references", "after the references", "pages"}
    start = index["after the references"]
    assert start.startswith("from line ") and start.endswith(" (p.4)")
    assert lines[int(start.split()[2]) - 1] == "## A Mathematical Derivations"
    if not keep:
        assert start == "from line 19 (p.4)" and lines[17] == "--- p.4 ---"


def test_the_text_after_the_references_and_an_appendix_heading_later(tmp_path):
    fp = _paper_with_appendix(tmp_path / "paper.pdf", first="A Mathematical Derivations", then="Appendix B Proofs")
    js, out = tmp_path / "sentences.json", tmp_path / "sentences.txt"
    cli.extract_main(["--pdf", fp, "--sentences", str(js), "--out", str(out)])
    index, lines = _index(out.read_text(encoding="utf8"))
    assert lines[int(index["after the references"].split()[2]) - 1] == "## A Mathematical Derivations"
    assert lines[int(index["appendix"].split()[2]) - 1] == "## Appendix B Proofs"
    assert index["after the references"].endswith("(p.4)") and index["appendix"].endswith("(p.5)")


def test_nothing_after_the_references_lists_no_such_line(tmp_path):
    fp = _paper_with_appendix(tmp_path / "paper.pdf", first=None)
    js, out = tmp_path / "sentences.json", tmp_path / "sentences.txt"
    cli.extract_main(["--pdf", fp, "--sentences", str(js), "--out", str(out)])
    index, _ = _index(out.read_text(encoding="utf8"))
    assert set(index) == {"main text", "references", "pages"}


@pytest.mark.parametrize("heading", ["Supplementary experiments", "Appendix of results"])
def test_a_section_called_like_an_appendix_before_the_references_is_main_text(tmp_path, capsys, heading):
    fp = _paper_with_appendix(tmp_path / "paper.pdf", before_refs=heading)
    js, out = tmp_path / "sentences.json", tmp_path / "sentences.txt"
    cli.extract_main(["--pdf", fp, "--sentences", str(js), "--out", str(out)])
    index, lines = _index(out.read_text(encoding="utf8"))
    assert f"## {heading}" in lines[:int(index["references"].split()[1])]
    assert lines[int(index["appendix"].split()[2]) - 1] == "## Appendix A Proofs", "the appendix is the one after the references"
    assert json.load(open(js, encoding="utf8"))["sentences"][0]["id"] == 1, "the JSON covers the whole document"


def _extracted(tmp_path, fp):
    js = tmp_path / "sentences.json"
    cli.extract_main(["--pdf", str(fp), "--sentences", str(js), "--out", str(tmp_path / "sentences.txt")])
    return [i for i in json.loads(js.read_text(encoding="utf8"))["sentences"] if "id" in i], js


def _highlighted(tmp_path, fp, js, sents):
    """The positions the highlights of these sentence ids get."""
    cfg = dict(cli.DEFAULTS, pdf=str(fp), item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               sentences=str(js), highlights=[{"id": s["id"], "comment": "x"} for s in sents])
    out, missed = cli.build(cfg)
    assert not missed
    return [a["position"] for a in out]


def test_each_sentence_gets_its_position_in_zotero_space(tmp_path):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    sents, _ = _extracted(tmp_path, fp)
    assert sents and all(s.get("rects") for s in sents)
    doc = pymupdf.open(str(fp))
    for s in sents:
        page = doc[s["page"] - 1]
        for r in s["rects"]:
            assert len(r) == 4 and all(isinstance(v, (int, float)) for v in r)
            assert 0 <= r[0] < r[2] <= page.rect.width and 0 <= r[1] < r[3] <= page.rect.height
    first = next(s for s in sents if s["text"].startswith("Foundation models"))
    word = doc[0].search_for("Foundation")[0]
    assert abs(first["rects"][0][3] - (792 - word.y0)) < 1.5, "y counts up from the bottom of the page"
    assert "rects" not in (tmp_path / "sentences.txt").read_text(encoding="utf8")


def test_a_sentence_position_is_that_of_its_highlight(tmp_path):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    sents, js = _extracted(tmp_path, fp)
    assert _highlighted(tmp_path, fp, js, sents) == [{"pageIndex": s["page"] - 1, "rects": s["rects"]} for s in sents]


def test_a_repeated_sentence_takes_its_own_occurrence(tmp_path):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    sents, _ = _extracted(tmp_path, fp)
    a, b = [s for s in sents if s["text"] == "The encodings are pooled with a sum."]
    assert b["rects"][0][3] < a["rects"][0][1], "the second one lies lower on the page"
    pi = cli.PageIndex(pymupdf.open(str(fp))[1])
    assert b["rects"] == [[round(r.x0, 2), round(pi.H - r.y1, 2), round(r.x1, 2), round(pi.H - r.y0, 2)]
                          for r in pi.line_rects(pi.match(b["text"], 2))]
    # three such sentences on a page that has the text twice: none of them gets a position
    bare = [{k: v for k, v in s.items() if k != "rects"} for s in (a, b, dict(b, id=99))]
    got = cli.sentence_rects(str(fp), bare)
    assert [s.get("rects") for s in got] == [None, None, None]


def test_a_sentence_whose_text_stands_elsewhere_on_the_page_gets_no_position(tmp_path):
    """A text the page has more often than the extraction has sentences with it is ambiguous, as for an id highlight."""
    fp = tmp_path / "substr.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(72, 72, 540, 400), "In all of the experiments reported here we use Adam. The kernel is "
                        "invariant to rotations of the input. We use Adam. The bound holds because the kernel is invariant to "
                        "rotations of the input and the sum is finite.", fontsize=11, fontname="helv")
    doc.save(str(fp)); doc.close()
    sents, js = _extracted(tmp_path, fp)
    assert len(sents) == 4
    assert [("rects" in s) for s in sents] == [True, True, False, True], "not the end of the first sentence"
    cfg = dict(cli.DEFAULTS, pdf=str(fp), item_key="I", attachment_key="A", out_dir=str(tmp_path), preview_pages=[],
               sentences=str(js), highlights=[{"id": s["id"], "comment": "x"} for s in sents])
    out, missed = cli.build(cfg)
    assert [m["id"] for m in missed] == [s["id"] for s in sents if "rects" not in s]
    assert all("ambiguous" in m["reason"] for m in missed)
    assert [a["position"]["rects"] for a in out] == [s["rects"] for s in sents if "rects" in s]


def test_a_sentence_not_found_as_extracted_takes_the_closest_passage_or_none(tmp_path):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    first = next(i for i in cli.extract_sentences(str(fp)) if i.get("text", "").startswith("Foundation models"))
    assert "rects" not in first
    exact = cli.sentence_rects(str(fp), [dict(first)])[0]["rects"]
    typo = dict(first, text=first["text"].replace("models", "modelz"))
    far = dict(first, id=first["id"] + 1, text="Completely unrelated words that appear nowhere in this paper at all.")
    got = cli.sentence_rects(str(fp), [typo, far])
    assert got[0]["rects"] == exact and "rects" not in got[1]


def test_sentence_positions_are_in_pdf_user_space_on_a_cropped_page(tmp_path):
    fp = tmp_path / "cropped.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(110, 120, 500, 300), "Foundation models have transformed language processing. "
                        "Patch jittering makes the encoder robust to small shifts.", fontsize=10, fontname="helv")
    page.set_cropbox(pymupdf.Rect(50, 60, 562, 742))
    doc.save(str(fp)); doc.close()
    sents, js = _extracted(tmp_path, fp)
    page = pymupdf.open(str(fp))[0]
    word = page.search_for("Patch jittering")[0] * ~page.transformation_matrix
    r = next(s for s in sents if s["text"].startswith("Patch"))["rects"][0]
    assert abs(r[0] - word.x0) < 1.5 and abs(r[1] - word.y0) < 1.5 and abs(r[3] - word.y1) < 1.5
    assert _highlighted(tmp_path, fp, js, sents) == [{"pageIndex": 0, "rects": s["rects"]} for s in sents]


def test_sentences_on_a_rotated_page_get_no_position(tmp_path):
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 700), f"Page {i + 1} says that the method improves the result. "
                            "It also runs fast on every benchmark.", fontsize=10, fontname="helv")
    doc[1].set_rotation(90)
    fp = tmp_path / "rotated.pdf"; doc.save(str(fp)); doc.close()
    sents, _ = _extracted(tmp_path, fp)
    assert [(s["page"], "rects" in s) for s in sents] == [(1, True), (1, True), (2, False), (2, False)]


def test_measure_context_reports_skill_tokens(tmp_path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "measure_context.py"), "--json"],
                       capture_output=True, text=True, encoding="utf8", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["skill"]["SKILL.md"]["tokens"] > 100 and data["tokenizer"] in ("tiktoken", "heuristic")
    assert any(k.startswith("references/") for k in data["skill"])
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "measure_context.py"), "--max-skill-tokens", "1"],
                       capture_output=True, text=True, encoding="utf8", cwd=ROOT)
    assert r.returncode == 1


def test_session_usage_reads_codex_and_claude_transcripts(tmp_path):
    codex = tmp_path / "rollout-2026-09-01T18-00-00-x.jsonl"
    rows = [{"type": "session_meta", "payload": {"timestamp": "2026-09-01T10:00:00Z"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec", "call_id": "c1",
                                                  "arguments": json.dumps({"cmd": "python scholium.py --config c.json --apply"})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "x" * 500}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 40000, "cached_input_tokens": 30000, "output_tokens": 500}}}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 50000, "cached_input_tokens": 45000, "output_tokens": 700}}}}]
    codex.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf8")
    claude = tmp_path / "agent-abc.jsonl"
    rows = [{"type": "assistant", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 30000, "cache_creation_input_tokens": 2000, "output_tokens": 300},
                                              "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "python scholium.py --config c.json"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "y" * 300}]}},
            {"type": "assistant", "message": {"usage": {"input_tokens": 200, "cache_read_input_tokens": 32000, "cache_creation_input_tokens": 0, "output_tokens": 100}, "content": [{"type": "text", "text": "done"}]}}]
    claude.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf8")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "session_usage.py"), "--json", str(codex), str(claude)],
                       capture_output=True, text=True, encoding="utf8", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    by = {d["file"]: d for d in data["sessions"]}
    c = by[str(codex)]; k = by[str(claude)]
    assert (c["harness"], c["calls"], c["input"], c["cached"], c["output"], c["peak"]) == ("codex", 2, 90000, 75000, 1200, 50000)
    assert (k["harness"], k["calls"], k["input"], k["output"], k["peak"]) == ("claude", 2, 64300, 400, 32200)
    assert c["tools"]["scholium apply"] == 1 and k["tools"]["scholium dry-run"] == 1


def test_a_lone_number_or_letter_inside_the_text_is_kept(tmp_path):
    """Only a page's first and last rows can hold its page number; a formula's variable on its own line is text."""
    fp = str(tmp_path / "formula.pdf")
    body = [f"Body line {w} of the running text continues here" for w in "abcdefghij"]
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(72, 72, 540, 700), "\n".join(
        body + ["and the learned vector field defines an ODE,", "d", "dt x = v(t, x), which is solved numerically.",
                "We train the model for", "12", "epochs on the data."] + body) + ".", fontsize=10)
    page.insert_text((300, 760), "7", fontsize=9)
    page.insert_textbox(pymupdf.Rect(30, 72, 60, 700), "\n".join(f"{n:03d}" for n in range(1, 40)), fontsize=8)   # line numbers
    doc.save(fp); doc.close()
    text = " ".join(it["text"] for it in cli.extract_sentences(fp) if "id" in it)
    assert "an ODE, d dt x = v(t, x)" in text and "for 12 epochs" in text
    assert not text.rstrip(".").endswith(" 7"), "the page number at the foot is still dropped"
    assert "005" not in text and "020" not in text, "a column of line numbers is dropped"


def _stopped(capsys, argv):
    """extract's exit code and its JSON output."""
    with pytest.raises(SystemExit) as stop:
        cli.extract_main(argv)
    return stop.value.code, json.loads(capsys.readouterr().out)


def test_extract_stops_on_a_pdf_without_text(tmp_path, capsys):
    fp = str(tmp_path / "scan.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(pymupdf.Rect(72, 72, 540, 700), fill=(0.9, 0.9, 0.9))
    doc.save(fp); doc.close()
    js = tmp_path / "sentences.json"
    code, out = _stopped(capsys, ["--pdf", fp, "--sentences", str(js), "--out", str(tmp_path / "sentences.txt")])
    assert code == cli.NO_TEXT_EXIT == 3 and out["error"] == cli.NO_TEXT_LAYER and not js.exists()
    assert _stopped(capsys, ["--pdf", fp])[0] == 3


def _scan(path, pages, text_pages=(), footer=None, figure=False):
    """A PDF of page images made here (a grey pixmap over the page), with pages of text where text_pages says, an
    optional footer line on the image pages, or one page with a figure in place of the scans."""
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 160), False)
    pix.clear_with(220)
    body = ("We study permutation invariance in learned set functions and show that a simple pooling layer suffices. "
            "The model is trained for twelve epochs on three datasets and compared with two baselines. ") * 3
    for p in range(pages):
        page = doc.new_page(width=612, height=792)
        if p in text_pages or (figure and p != 1):
            page.insert_textbox(pymupdf.Rect(72, 72, 540, 700), body, fontsize=10)
            continue
        if figure:
            page.insert_image(pymupdf.Rect(72, 72, 540, 600), pixmap=pix)
            page.insert_text((72, 640), "Figure 2: Results.", fontsize=9)
            continue
        page.insert_image(page.rect, pixmap=pix)
        if footer:
            page.insert_text((72, 780), footer, fontsize=7)
    doc.save(path); doc.close()


def test_extract_stops_on_a_scan_without_ocr(tmp_path, capsys):
    fp = str(tmp_path / "scan.pdf")
    _scan(fp, 4)
    js = tmp_path / "sentences.json"
    code, out = _stopped(capsys, ["--pdf", fp, "--sentences", str(js), "--out", str(tmp_path / "sentences.txt")])
    assert code == 3 and out == {"error": cli.NO_TEXT_LAYER, "pages": 4, "scanned_pages": 4} and not js.exists()
    assert "run OCR first (e.g. ocrmypdf, or Acrobat's Recognize Text), then annotate again" in out["error"]
    assert _stopped(capsys, ["--pdf", fp])[0] == 3, "the plain text too"
    assert _stopped(capsys, ["--pdf", fp, "--pages", "1"])[0] == 3, "whatever the pages asked for"


def test_a_scan_with_a_cover_page_or_a_footer_is_a_scan(tmp_path, capsys):
    cover = str(tmp_path / "cover.pdf")
    _scan(cover, 4, text_pages=(0,))
    assert _stopped(capsys, ["--pdf", cover])[1]["scanned_pages"] == 3
    footer = str(tmp_path / "footer.pdf")
    _scan(footer, 3, footer="Downloaded from https://example.org on 12 March 2023")
    assert _stopped(capsys, ["--pdf", footer])[1]["scanned_pages"] == 3


def test_a_paper_with_a_figure_page_is_no_scan(tmp_path, capsys):
    fp = str(tmp_path / "figure.pdf")
    _scan(fp, 3, figure=True)
    js = tmp_path / "sentences.json"
    assert cli.extract_main(["--pdf", fp, "--sentences", str(js), "--out", str(tmp_path / "sentences.txt")]) == 0
    assert js.exists() and cli.scanned_pages(fp) == (3, 0)
    half = str(tmp_path / "half.pdf")
    _scan(half, 2, text_pages=(0,))
    assert cli.scanned_pages(half) == (2, 1)
    assert cli.extract_main(["--pdf", half, "--out", str(tmp_path / "half.txt")]) == 0, "half the pages scanned: not most"
    ocr = str(tmp_path / "ocr.pdf")   # a scan with OCR's invisible text over its page images
    _scan(ocr, 2)
    doc = pymupdf.open(ocr)
    for page in doc:
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 700), "Recognized text of the scanned page, as OCR leaves it. " * 6, fontsize=10, render_mode=3)
    doc.saveIncr(); doc.close()
    assert cli.scanned_pages(ocr) == (2, 0)
