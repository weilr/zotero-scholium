"""The tests never reach the user's Zotero on port 23119. SCHOLIUM_ZOTERO_PORT is set to the discard port 9 before any test
module imports the CLI, so the CLI in this process (cli.BASE) and in every child process a test starts without an
environment of its own talks to port 9. A connection to port 23119 from this process fails the test that made it: it
raises ZoteroPortReached before any socket is opened, and the test is failed at its end even if the code under test
caught the error."""
import os
import socket

import pytest

ZOTERO_PORT = 23119
os.environ["SCHOLIUM_ZOTERO_PORT"] = "9"

# the socket methods the guard stands in front of; a test of the guard may replace them
ORIGINAL = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex}
REACHED = []   # the test and the address of each connection to port 23119 that the guard stopped


class ZoteroPortReached(BaseException):
    """A test tried to connect to port 23119. A BaseException, so that no `except Exception` in the code under test hides it."""


def _guarded(name):
    def connect(self, address, *args, **kwargs):
        if isinstance(address, tuple) and len(address) >= 2 and address[1] == ZOTERO_PORT:
            test = os.environ.get("PYTEST_CURRENT_TEST", "(outside a test)")
            REACHED.append((test, address[0]))
            raise ZoteroPortReached(f"{test} tried to connect to {address[0]}:{ZOTERO_PORT}, the user's Zotero; tests must not "
                                    "reach it (SCHOLIUM_ZOTERO_PORT is 9 in tests)")
        return ORIGINAL[name](self, address, *args, **kwargs)
    connect.__name__ = name
    return connect


socket.socket.connect = _guarded("connect")
socket.socket.connect_ex = _guarded("connect_ex")


@pytest.fixture(autouse=True)
def no_zotero_port():
    """Fails a test that tried to connect to port 23119, also when the code under test caught the guard's error."""
    start = len(REACHED)
    yield
    reached = REACHED[start:]
    if reached:
        pytest.fail(f"connected to port {ZOTERO_PORT}: " + "; ".join(f"{test} -> {host}" for test, host in reached), pytrace=False)
