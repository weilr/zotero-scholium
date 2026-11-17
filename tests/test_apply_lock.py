"""One --apply at a time per output folder: runs of a paper at once read the attachment, write it and record what they
wrote in turn, so that neither record loses the other's."""
import json
import os
import time

import pymupdf
import pytest

from zotero_scholium import cli


def _pdf(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "We propose a simple method for testing annotation tools.", fontsize=11)
    path = tmp_path / "paper.pdf"
    doc.save(path)
    return str(path)


def test_the_lock_is_taken_and_given_back(tmp_path):
    lock = cli.ApplyLock()
    assert lock.take(str(tmp_path)) is True
    path = tmp_path / ".apply.lock"
    assert path.exists()
    lock.release()
    assert not path.exists() and lock.path is None
    lock.release()   # a second release is harmless


def test_a_second_write_waits_for_the_first_and_gives_up_with_a_word(tmp_path):
    first = cli.ApplyLock()
    first.take(str(tmp_path))
    started = time.monotonic()
    with pytest.raises(SystemExit) as e:
        cli.ApplyLock().take(str(tmp_path), wait=0.5)
    assert time.monotonic() - started >= 0.4, "it waited"
    assert "another write to this paper is still going on" in str(e.value)
    first.release()


def test_a_lock_left_by_a_write_that_died_is_taken_over(tmp_path):
    path = tmp_path / ".apply.lock"
    path.write_text("4242")
    old = time.time() - cli.ApplyLock.STALE - 5
    os.utime(path, (old, old))
    lock = cli.ApplyLock()
    assert lock.take(str(tmp_path), wait=0.5) is True
    lock.release()


def test_apply_gives_the_lock_back_however_it_ends(tmp_path, capsys):
    cp = tmp_path / "config.json"
    json.dump({"pdf": _pdf(tmp_path), "item_key": "I", "attachment_key": "A", "out_dir": str(tmp_path),
               "highlights": [{"page": 1, "text": "We propose a simple method for testing annotation tools.", "core": True,
                               "comment": "我们提出一种测试批注工具的简单方法。"}]}, open(cp, "w", encoding="utf8"))
    taken = []
    real = cli.ApplyLock.take

    def spy(self, out_dir, wait=None):
        taken.append(out_dir)
        return real(self, out_dir, wait)

    cli.ApplyLock.take = spy
    try:
        with pytest.raises(SystemExit):
            cli.main(["--config", str(cp), "--apply", "--backend", "js", "--ignore-existing"])
        capsys.readouterr()
        cli.main(["--config", str(cp)])   # a dry run takes no lock
        capsys.readouterr()
    finally:
        cli.ApplyLock.take = real
    assert taken == [str(tmp_path)], "only --apply takes it"
    assert not (tmp_path / ".apply.lock").exists()
