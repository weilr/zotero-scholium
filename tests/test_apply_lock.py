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
    path.write_text("4242 0123456789abcdef")
    old = time.time() - cli.ApplyLock.STALE - 5
    os.utime(path, (old, old))
    lock = cli.ApplyLock()
    assert lock.take(str(tmp_path), wait=0.5) is True
    lock.release()


def test_an_earlier_versions_lock_is_taken_over_only_after_its_own_time(tmp_path):
    """An earlier version writes its process id alone and does not touch the lock while it writes: such a lock is left
    for OLD_STALE seconds, so that its write is not joined by another, which its release would then let a third join."""
    path = tmp_path / ".apply.lock"
    path.write_text("4242")
    _age(path, cli.ApplyLock.STALE + 5)
    with pytest.raises(SystemExit):
        cli.ApplyLock().take(str(tmp_path), wait=0.3)
    assert path.read_text() == "4242"
    _age(path, cli.ApplyLock.OLD_STALE + 5)
    lock = cli.ApplyLock()
    assert lock.take(str(tmp_path), wait=0.5) is True
    lock.release()


def _age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_the_write_that_holds_the_lock_keeps_touching_it(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.ApplyLock, "BEAT", 0.05)
    lock = cli.ApplyLock()
    lock.take(str(tmp_path))
    path = tmp_path / ".apply.lock"
    _age(path, cli.ApplyLock.STALE + 5)
    time.sleep(0.3)
    assert time.time() - path.stat().st_mtime < 1, "touched again: a live write's lock never looks left"
    with pytest.raises(SystemExit):
        cli.ApplyLock().take(str(tmp_path), wait=0.3)
    lock.release()
    assert not path.exists() and lock.beating is None


def test_a_lock_another_waiter_takes_over_now_stays(tmp_path):
    path = tmp_path / ".apply.lock"
    path.write_text("4242 0123456789abcdef")
    _age(path, cli.ApplyLock.STALE + 5)
    (tmp_path / ".apply.lock.takeover").write_text("")   # another waiter is taking it over
    with pytest.raises(SystemExit):
        cli.ApplyLock().take(str(tmp_path), wait=0.3)
    assert path.read_text() == "4242 0123456789abcdef"
    _age(tmp_path / ".apply.lock.takeover", cli.ApplyLock.STALE + 5)   # that waiter died meanwhile
    lock = cli.ApplyLock()
    assert lock.take(str(tmp_path), wait=1) is True
    assert not (tmp_path / ".apply.lock.takeover").exists()
    lock.release()


def test_a_write_whose_lock_was_taken_over_leaves_the_new_one(tmp_path, monkeypatch):
    """A write that stalled past STALE (a machine asleep) lost its lock to a waiter: it neither touches nor removes the
    waiter's lock."""
    monkeypatch.setattr(cli.ApplyLock, "BEAT", 0.05)
    stalled = cli.ApplyLock()
    stalled.take(str(tmp_path))
    path = tmp_path / ".apply.lock"
    os.remove(path)   # taken over
    waiter = cli.ApplyLock()
    assert waiter.take(str(tmp_path), wait=0.5) is True
    waiter.beating.set()   # the waiter's own touches stopped, to see the stalled write's
    _age(path, cli.ApplyLock.STALE - 5)
    time.sleep(0.3)
    assert time.time() - path.stat().st_mtime > cli.ApplyLock.STALE - 6, "the stalled write does not touch it"
    stalled.release()
    assert path.read_text() == waiter.token
    waiter.release()
    assert not path.exists()


def test_the_release_tries_again_while_a_waiter_reads_the_lock(tmp_path, monkeypatch):
    """On Windows a waiter reading the lock (stale) holds it open for a moment, and the removal is refused then."""
    lock = cli.ApplyLock()
    lock.take(str(tmp_path))
    real, calls = os.remove, []

    def remove(p):
        calls.append(p)
        if len(calls) < 3:
            raise PermissionError(13, "The process cannot access the file", str(p))
        real(p)
    monkeypatch.setattr(cli.os, "remove", remove)
    lock.release()
    assert len(calls) == 3 and not (tmp_path / ".apply.lock").exists()


def test_a_folder_that_refuses_the_lock_is_said_at_once(tmp_path, monkeypatch):
    real = os.open

    def refuse(p, *a, **k):
        if str(p).endswith(".apply.lock"):
            raise PermissionError(13, "Access is denied", str(p))
        return real(p, *a, **k)
    monkeypatch.setattr(cli.os, "open", refuse)
    started = time.monotonic()
    with pytest.raises(SystemExit) as e:
        cli.ApplyLock().take(str(tmp_path), wait=30)
    assert "cannot write the lock" in str(e.value) and time.monotonic() - started < 10


def test_a_lock_being_written_is_waited_for(tmp_path):
    (tmp_path / ".apply.lock").write_text("")   # created, its process id not written yet
    with pytest.raises(SystemExit):
        cli.ApplyLock().take(str(tmp_path), wait=0.5)


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
