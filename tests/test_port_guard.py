"""The guard of conftest.py: a connection to port 23119 is stopped before a socket opens, and the CLI, in this process and
in a child process started without an environment of its own, talks to port 9."""
import os
import socket
import subprocess
import sys

import pytest

import conftest
from zotero_scholium import cli


def test_a_connection_to_port_23119_is_stopped_before_a_socket_opens(monkeypatch):
    opened = []
    monkeypatch.setitem(conftest.ORIGINAL, "connect", lambda *a, **k: opened.append(a))
    monkeypatch.setitem(conftest.ORIGINAL, "connect_ex", lambda *a, **k: opened.append(a) or 0)
    start = len(conftest.REACHED)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(conftest.ZoteroPortReached, match="test_port_guard.py.*127.0.0.1:23119, the user's Zotero"):
            s.connect(("127.0.0.1", 23119))
        with pytest.raises(conftest.ZoteroPortReached):
            s.connect_ex(("localhost", 23119))
        s.connect(("127.0.0.1", 9))   # another port goes through
    finally:
        s.close()
    assert opened == [(s, ("127.0.0.1", 9))], "the original connect never saw port 23119"
    assert [host for _, host in conftest.REACHED[start:]] == ["127.0.0.1", "localhost"]
    del conftest.REACHED[start:]   # this test's own attempts do not fail it


def test_the_cli_talks_to_port_9():
    assert os.environ["SCHOLIUM_ZOTERO_PORT"] == "9"
    assert cli.BASE == "http://127.0.0.1:9"
    skill = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "zotero-scholium", "scripts")
    code = "import sys; sys.path.insert(0, sys.argv[1]); import scholium; print(scholium.BASE)"
    child = subprocess.run([sys.executable, "-c", code, skill], capture_output=True, text=True, timeout=60)
    assert child.stdout.strip() == "http://127.0.0.1:9", "a child started without an environment of its own"



@pytest.mark.skipif(sys.platform != "win32", reason="the Proactor event loop is Windows'; elsewhere asyncio connects with socket.connect")
def test_asyncio_connections_are_stopped_too():
    """Windows' Proactor event loop connects with ConnectEx, past socket.connect. The proactor and the socket here are
    stand-ins: without the guard the call fails on them, before any connection."""
    import types
    from asyncio import windows_events

    class Socket:
        family, type = socket.AF_INET, socket.SOCK_STREAM

        def fileno(self):
            raise AssertionError("the proactor reached the socket")
    start = len(conftest.REACHED)
    with pytest.raises(conftest.ZoteroPortReached):
        windows_events.IocpProactor.connect(types.SimpleNamespace(), Socket(), ("127.0.0.1", 23119))
    assert [host for _, host in conftest.REACHED[start:]] == ["127.0.0.1"]
    del conftest.REACHED[start:]


def test_a_child_python_with_an_environment_of_its_own_has_the_guard():
    """A child started with an environment that names neither the port nor PYTHONPATH still has the guard: its connection
    to port 23119 is stopped and noted for the test that started it. The child connects only once it sees the guard."""
    from pathlib import Path
    log = Path(os.environ["SCHOLIUM_PORT_GUARD_LOG"])
    before = log.stat().st_size if log.exists() else 0
    env = {k: v for k, v in os.environ.items() if k not in ("SCHOLIUM_ZOTERO_PORT", "PYTHONPATH", "SCHOLIUM_PORT_GUARD_LOG")}
    code = ("import socket, sys\n"
            "if getattr(socket.socket.connect, '__module__', None) != 'sitecustomize': sys.exit('no guard')\n"
            "s = socket.socket(); s.connect(('127.0.0.1', 23119))")
    child = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert "no guard" not in child.stderr
    assert child.returncode != 0 and "ZoteroPortReached" in child.stderr and "127.0.0.1:23119" in child.stderr
    noted = log.read_bytes()[before:].decode("utf8")
    assert "127.0.0.1" in noted
    with open(log, "r+b") as f:   # this test's own attempt does not fail it
        f.truncate(before)
