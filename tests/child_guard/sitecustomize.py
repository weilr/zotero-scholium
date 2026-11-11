"""The port guard of every Python process the tests start: conftest.py puts this folder on PYTHONPATH, also in an
environment a test gives a child of its own. A connection to port 23119, the user's Zotero, raises ZoteroPortReached
before any socket is opened, and is noted in the file SCHOLIUM_PORT_GUARD_LOG names, which fails the test that started
the process even if the code under test caught the error."""
import os
import socket
import sys

ZOTERO_PORT = 23119
_ORIGINAL = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex}


class ZoteroPortReached(BaseException):
    """A child of a test tried to connect to port 23119."""


def _stop(address):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] == ZOTERO_PORT:
        log = os.environ.get("SCHOLIUM_PORT_GUARD_LOG")
        if log:
            try:
                with open(log, "a", encoding="utf8") as f:
                    f.write(f"{os.getpid()} {address[0]}\n")
            except OSError:
                pass
        raise ZoteroPortReached(f"a process started by a test tried to connect to {address[0]}:{ZOTERO_PORT}, the user's Zotero")


def connect(self, address, *args, **kwargs):
    _stop(address)
    return _ORIGINAL["connect"](self, address, *args, **kwargs)


def connect_ex(self, address, *args, **kwargs):
    _stop(address)
    return _ORIGINAL["connect_ex"](self, address, *args, **kwargs)


socket.socket.connect = connect
socket.socket.connect_ex = connect_ex

if sys.platform == "win32":   # asyncio's Proactor connects with ConnectEx, past socket.connect
    try:
        from asyncio import windows_events
    except ImportError:
        windows_events = None
    if windows_events is not None:
        _proactor_connect = windows_events.IocpProactor.connect

        def proactor_connect(self, conn, address):
            _stop(address)
            return _proactor_connect(self, conn, address)
        windows_events.IocpProactor.connect = proactor_connect

# a sitecustomize further on the path (a test's own: a guard of the tool it tests) runs after this one, as the module of
# that name, so that its guard stands in front of this one's
_here = os.path.dirname(os.path.abspath(__file__))
for _dir in sys.path:
    _file = os.path.join(_dir or os.getcwd(), "sitecustomize.py")
    if os.path.abspath(_dir or os.getcwd()) != _here and os.path.isfile(_file):
        import importlib.util
        _spec = importlib.util.spec_from_file_location("sitecustomize", _file)
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["sitecustomize"] = _module
        _spec.loader.exec_module(_module)
        break
