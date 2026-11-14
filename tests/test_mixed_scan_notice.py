"""Successful partial extraction must disclose scanned content without changing sentence IDs."""
import json
import re

import pytest

from zotero_scholium import cli
from test_sentences_and_measure import _index, _scan


@pytest.mark.parametrize("numbered", [False, True])
@pytest.mark.parametrize("to_file", [False, True])
def test_partial_extraction_reports_scanned_content(tmp_path, capsys, numbered, to_file):
    pdf, cache, out = (tmp_path / name for name in ("mixed.pdf", "sentences.json", "text.txt"))
    _scan(str(pdf), 4, text_pages=(0, 2))
    args = ["--pdf", str(pdf)]
    if numbered:
        args += ["--sentences", str(cache)]
    if to_file:
        args += ["--out", str(out)]
    assert cli.extract_main(args) == 0
    console = capsys.readouterr().out
    text = out.read_text(encoding="utf8") if to_file else console
    assert "2 of 4" in text and "not extracted" in text and "OCR" in text
    assert "2 of 4" in console and "OCR" in console
    assert "We study permutation invariance" in text
    if numbered:
        expected = cli.sentence_rects(str(pdf), cli.extract_sentences(str(pdf)))
        assert json.loads(cache.read_text(encoding="utf8"))["sentences"] == [s for s in expected if "id" in s]
        if to_file:
            index, lines = _index(text)
            for page, line in re.findall(r"p\.(\d+) (\d+)", index["pages"]):
                assert lines[int(line) - 1] == f"--- p.{page} ---"


@pytest.mark.parametrize("numbered", [False, True])
def test_text_only_selection_does_not_warn_about_scans_outside_it(tmp_path, capsys, numbered):
    pdf, out = tmp_path / "mixed.pdf", tmp_path / "text.txt"
    _scan(str(pdf), 4, text_pages=(0, 2))
    args = ["--pdf", str(pdf), "--pages", "1", "--out", str(out)]
    if numbered:
        args += ["--sentences", str(tmp_path / "sentences.json")]
    assert cli.extract_main(args) == 0
    assert "OCR" not in out.read_text(encoding="utf8") + capsys.readouterr().out
