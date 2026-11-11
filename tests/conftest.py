"""The tests never reach the user's Zotero on port 23119. SCHOLIUM_ZOTERO_PORT is set to the discard port 9 before any test
module imports the CLI, so the CLI in this process (cli.BASE) and in every child process a test starts without an
environment of its own talks to port 9. A connection to port 23119 from this process, through a socket or asyncio's
Proactor event loop on Windows, fails the test that made it: it raises ZoteroPortReached before any socket is opened, and
the test is failed at its end even if the code under test caught the error. Every Python process a test starts, also
with an environment of its own (subprocess.Popen's env, given port 9 unless it names one), has the same guard from
child_guard/sitecustomize.py first on its PYTHONPATH, and its attempts fail the test too; a sitecustomize of the test's own
further on that PYTHONPATH runs after it. A child started with python -I, or a program that is not Python, has none."""
import os
import socket
import subprocess
import sys

import pytest

ZOTERO_PORT = 23119
os.environ["SCHOLIUM_ZOTERO_PORT"] = "9"
# a test that stands in for a run of the plugin's agent sets these itself (pytest started by such an agent has them)
for name in ("SCHOLIUM_PLUGIN_RUN", "SCHOLIUM_CONFIRMED", "SCHOLIUM_HELD_BACK"):
    os.environ.pop(name, None)
CHILD_GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "child_guard")


def _with_guard(env):
    """An environment for a child process: the child guard's folder first on PYTHONPATH (a sitecustomize of the test's own
    further on runs after it, child_guard/sitecustomize.py hands over to it), SCHOLIUM_ZOTERO_PORT 9 unless the test names
    one, and the file the guard's attempts are noted in."""
    paths = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != CHILD_GUARD]
    env["PYTHONPATH"] = os.pathsep.join([CHILD_GUARD] + paths)
    env.setdefault("SCHOLIUM_ZOTERO_PORT", "9")
    if os.environ.get("SCHOLIUM_PORT_GUARD_LOG"):
        env.setdefault("SCHOLIUM_PORT_GUARD_LOG", os.environ["SCHOLIUM_PORT_GUARD_LOG"])
    return env


_with_guard(os.environ)
_POPEN_INIT = subprocess.Popen.__init__


def _popen_init(self, *args, env=None, **kwargs):
    _POPEN_INIT(self, *args, env=None if env is None else _with_guard(dict(env)), **kwargs)


subprocess.Popen.__init__ = _popen_init

# the socket methods the guard stands in front of; a test of the guard may replace them
ORIGINAL = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex}
REACHED = []   # the test and the address of each connection to port 23119 that the guard stopped


class ZoteroPortReached(BaseException):
    """A test tried to connect to port 23119. A BaseException, so that no `except Exception` in the code under test hides it."""


def _stop(address):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] == ZOTERO_PORT:
        test = os.environ.get("PYTEST_CURRENT_TEST", "(outside a test)")
        REACHED.append((test, address[0]))
        raise ZoteroPortReached(f"{test} tried to connect to {address[0]}:{ZOTERO_PORT}, the user's Zotero; tests must not "
                                "reach it (SCHOLIUM_ZOTERO_PORT is 9 in tests)")


def _guarded(name):
    def connect(self, address, *args, **kwargs):
        _stop(address)
        return ORIGINAL[name](self, address, *args, **kwargs)
    connect.__name__ = name
    return connect


socket.socket.connect = _guarded("connect")
socket.socket.connect_ex = _guarded("connect_ex")

if sys.platform == "win32":   # asyncio's Proactor event loop connects with ConnectEx, past socket.connect
    from asyncio import windows_events
    ORIGINAL["proactor_connect"] = windows_events.IocpProactor.connect

    def _proactor_connect(self, conn, address):
        _stop(address)
        return ORIGINAL["proactor_connect"](self, conn, address)
    windows_events.IocpProactor.connect = _proactor_connect


@pytest.fixture(scope="session", autouse=True)
def child_guard_log(tmp_path_factory):
    """The file the child processes' guard notes their attempts in, for the session."""
    path = tmp_path_factory.getbasetemp() / "port-guard.log"
    path.touch()
    os.environ["SCHOLIUM_PORT_GUARD_LOG"] = str(path)
    yield path


@pytest.fixture(autouse=True)
def no_zotero_port(child_guard_log):
    """Fails a test that tried to connect to port 23119, also when the code under test caught the guard's error, or a
    child process it started did."""
    start, size = len(REACHED), child_guard_log.stat().st_size
    yield
    reached = REACHED[start:]
    children = child_guard_log.read_bytes()[size:].decode("utf8", "replace").split()
    if reached or children:
        attempts = [f"{test} -> {host}" for test, host in reached] + [f"a child process -> {host}" for host in children[1::2]]
        pytest.fail(f"connected to port {ZOTERO_PORT}: " + "; ".join(attempts), pytrace=False)
