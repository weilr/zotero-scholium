# The guard of a live run (scripts/smoke/live.py): every Python that the throwaway Zotero's agents start loads it through
# PYTHONPATH. Port 23119 on this machine is the user's own Zotero, so a connection there goes to the throwaway's port
# instead, which live.py writes to port.txt beside this file (a copy in the run folder); each such redirect is noted in
# redirects.txt beside it. Without a valid port.txt a connection to 23119 is refused. A Python started with -I or -E
# does not load this file: the skill's script must then honour SCHOLIUM_ZOTERO_PORT itself (live.py's chain test).
import os
import socket
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_USER = 23119
_LOCAL = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "::"}


def _read_port():
    try:
        with open(os.path.join(_HERE, "port.txt"), encoding="utf-8") as f:
            port = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return port if 1024 <= port <= 65535 and port != _USER else None


_OURS = _read_port()
_connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex


def _note(addr, what):
    try:
        with open(os.path.join(_HERE, "redirects.txt"), "a", encoding="utf-8") as f:
            f.write("%s pid %d %s:%d %s\n" % (time.strftime("%H:%M:%S"), os.getpid(), addr[0], _USER, what))
    except OSError:
        pass


def _is_user(addr):
    return isinstance(addr, tuple) and len(addr) >= 2 and addr[1] == _USER and str(addr[0]) in _LOCAL


def _move(addr):
    """The address a connection goes to: the throwaway's port for the user's Zotero."""
    if not _is_user(addr):
        return addr
    if _OURS is None:
        _note(addr, "refused (no port.txt)")
        raise ConnectionRefusedError("the live-run guard refuses 127.0.0.1:%d, the user's Zotero" % _USER)
    _note(addr, "-> %d" % _OURS)
    return (addr[0], _OURS) + tuple(addr[2:])


def connect(self, addr):
    return _connect(self, _move(addr))


def connect_ex(self, addr):
    return _connect_ex(self, _move(addr))


socket.socket.connect = connect
socket.socket.connect_ex = connect_ex

# an HTTP request names its server in its Host header, which Zotero checks: http.client is given the throwaway's port
try:
    import http.client as _hc

    _init = _hc.HTTPConnection.__init__

    def _http_init(self, host, port=None, *args, **kwargs):
        _init(self, host, port, *args, **kwargs)
        if self.port == _USER and str(self.host) in _LOCAL and _OURS is not None:
            _note((self.host, self.port), "-> %d" % _OURS)
            self.port = _OURS

    _hc.HTTPConnection.__init__ = _http_init
except Exception:
    pass

# urllib writes the Host header from the URL itself: the URL is given the throwaway's port
try:
    import re as _re
    import urllib.request as _ur

    _URL = _re.compile(r"^(https?://(?:127\.0\.0\.1|localhost|\[::1\])):%d(?=/|$)" % _USER)
    _req_init = _ur.Request.__init__

    def _request_init(self, url, *args, **kwargs):
        if isinstance(url, str) and _URL.match(url) and _OURS is not None:
            _note(("127.0.0.1", _USER), "-> %d" % _OURS)
            url = _URL.sub(r"\g<1>:%d" % _OURS, url)
        _req_init(self, url, *args, **kwargs)

    _ur.Request.__init__ = _request_init
except Exception:
    pass
