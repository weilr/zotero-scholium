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
    items = cli.extract_sentences(str(fp))
    sfile = tmp_path / "sentences.json"
    json.dump({"pdf": str(fp), "sentences": items}, open(sfile, "w", encoding="utf8"), ensure_ascii=False)
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


def test_apply_is_blocked_by_style_warnings_and_reports_pdf_hash(tmp_path, capsys):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    cfg = {"pdf": str(fp), "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path), "preview_pages": [],
           "highlights": [{"page": 1, "text": "Foundation models have transformed language processing.", "comment": "基础模型 $x$"}]}
    cp = tmp_path / "config.json"; json.dump(cfg, open(cp, "w", encoding="utf8"))
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing"])
    rep = json.loads(capsys.readouterr().out)
    assert e.value.code == 2 and rep["applied"] is False and "style warnings" in rep["apply_error"]
    assert rep["pdf_sha256"]["unchanged"] is True and len(rep["pdf_sha256"]["before"]) == 64
    cfg["highlights"][0]["comment"] = "基础模型改变了语言处理。"
    json.dump(cfg, open(cp, "w", encoding="utf8"))
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing"])
    rep = json.loads(capsys.readouterr().out)
    assert rep["style_warnings"] == [] and rep["backend"] == "js" and rep["applied"] is False and "fallback" in rep


def test_extract_main_writes_numbered_listing_and_json(tmp_path, capsys):
    fp = tmp_path / "paper.pdf"; _three_page_pdf(str(fp))
    out = tmp_path / "sentences.txt"; js = tmp_path / "sentences.json"
    cli.extract_main(["--pdf", str(fp), "--out", str(out), "--sentences", str(js)])
    assert "sentences" in capsys.readouterr().out
    listing = out.read_text(encoding="utf8"); data = json.load(open(js, encoding="utf8"))
    assert listing.startswith("--- p.1 ---") and "1 | " in listing
    assert data["pdf"] == str(fp) and data["sentences"][0]["id"] == 1
    cli.extract_main(["--pdf", str(fp), "--out", str(out), "--sentences", str(js), "--pages", "2"])
    part = out.read_text(encoding="utf8"); capsys.readouterr()
    first_id = int(next(ln for ln in part.split("\n") if " | " in ln).split(" | ")[0])
    assert part.startswith("--- p.2 ---") and "--- p.1 ---" not in part and first_id > 1, "ids keep counting over the whole document"
    assert json.load(open(js, encoding="utf8"))["sentences"][0]["id"] == 1, "the JSON covers the whole document"


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
