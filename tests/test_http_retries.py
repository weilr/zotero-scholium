"""Exercise write retries without contacting Zotero or reading real API keys."""
import json

import pytest

from zotero_scholium import cli


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    client = cli.LocalApi("test-server")
    client.key = "test-key"
    return client


@pytest.mark.parametrize("status", [0, 500, 503])
def test_create_does_not_retry_when_commit_outcome_is_unknown(api, monkeypatch, status):
    stored = []

    def exchange(method, path, body=None, headers=None, timeout=60):
        assert method == "POST" and path == "/api/users/0/items"
        stored.extend(body)
        if len(stored) == 1:
            return status, {}, "response failed after commit"
        return 200, {}, json.dumps({"successful": {"0": {"key": "DUPLICATE"}}, "failed": {}})

    monkeypatch.setattr(cli, "http", exchange)
    item = {"itemType": "note", "note": "<p>Keep just one copy.</p>"}
    keys, failed = api.create([item])
    assert keys == [] and f"HTTP {status}" in failed[0]["message"]
    assert stored == [item], "an uncertain response must not duplicate the committed item"


@pytest.mark.parametrize("second", [(500, "server error"), (401, "expired key")])
def test_a_failed_batch_keeps_the_keys_of_the_batches_before_it(api, monkeypatch, second):
    """A server error, or an expired key whose new authorisation is refused, on the second batch."""
    batches = []

    def exchange(method, path, body=None, headers=None, timeout=60):
        if path == "/api/local/authorize":
            return 403, {}, "denied"
        batches.append(len(body))
        if len(batches) == 2:
            return second[0], {}, second[1]
        return 200, {}, json.dumps({"successful": {str(i): {"key": f"K{i}"} for i in range(len(body))}, "failed": {}})

    monkeypatch.setattr(cli, "http", exchange)
    keys, failed = api.create([{"itemType": "annotation"}] * 51)
    assert batches == [50, 1]
    expected = "HTTP 500" if second[0] == 500 else "authorization failed (HTTP 403)"
    assert len(keys) == 50 and failed[0]["items"] == "51-51 of 51" and expected in failed[0]["message"]


@pytest.mark.parametrize("failure, attempts", [(ConnectionRefusedError(10061, "refused"), 1), (TimeoutError("timed out"), cli.GET_ATTEMPTS)])
def test_a_refused_read_is_not_retried_but_a_timed_out_one_is(monkeypatch, failure, attempts):
    """Nothing listening (Zotero closed) is final at once; a busy Zotero gets more tries."""
    tries, waits = [], []

    def opened(req, timeout=None):
        tries.append(req.full_url)
        raise cli.urllib.error.URLError(failure)

    monkeypatch.setattr(cli, "local_opener", lambda: type("Opener", (), {"open": staticmethod(opened)})())
    monkeypatch.setattr(cli.time, "sleep", waits.append)
    status, _, _ = cli.http("GET", "/api/")
    assert status == 0 and len(tries) == attempts and len(waits) == attempts - 1


def test_the_js_backend_does_not_ask_zotero(monkeypatch):
    """Only the local API needs Zotero's version: a requested Run-JavaScript file waits for nothing."""
    asked = []
    monkeypatch.setattr(cli, "http", lambda method, path, *a, **k: asked.append(path) or (0, {}, "refused"))
    assert cli.pick_backend("js", {})[0] == "js" and asked == []
    cli.pick_backend("auto", {})
    assert asked[:2] == ["/scholium/list", "/api/"]
    asked.clear()
    cli.pick_backend("api", {})
    assert asked == ["/api/"]


@pytest.mark.parametrize("status", [0, 500, 503])
def test_delete_still_retries_transient_errors(api, monkeypatch, status):
    attempts = []

    def exchange(method, path, body=None, headers=None, timeout=60):
        if method == "GET":
            return 200, {"Last-Modified-Version": "7"}, "[]"
        assert method == "DELETE" and path.endswith("itemKey=OLD")
        attempts.append(method)
        return (status, {}, "temporary failure") if len(attempts) == 1 else (204, {}, "")

    monkeypatch.setattr(cli, "http", exchange)
    assert api.delete(["OLD"]) == 1
    assert attempts == ["DELETE", "DELETE"]


def test_post_retries_after_authorization_is_renewed(api, monkeypatch):
    keys = []

    def exchange(method, path, body=None, headers=None, timeout=60):
        assert method == "POST"
        if path == "/api/local/authorize":
            return 200, {}, json.dumps({"key": "renewed-key", "remember": False})
        assert path == "/api/users/0/items"
        keys.append(headers["Zotero-API-Key"])
        if len(keys) == 1:
            return 401, {}, "expired key"
        return 200, {}, json.dumps({"successful": {"0": {"key": "NEW"}}, "failed": {}})

    monkeypatch.setattr(cli, "http", exchange)
    assert api.create([{"itemType": "note", "note": "<p>Note</p>"}]) == (["NEW"], [])
    assert keys == ["test-key", "renewed-key"]


def test_post_retries_rejected_precondition_with_fresh_version(api, monkeypatch):
    versions = []

    def exchange(method, path, body=None, headers=None, timeout=60):
        if method == "GET":
            return 200, {"Last-Modified-Version": "8"}, "[]"
        assert method == "POST"
        versions.append(headers["If-Unmodified-Since-Version"])
        return (412, {}, "stale version") if len(versions) == 1 else (200, {}, "accepted")

    monkeypatch.setattr(cli, "http", exchange)
    result = api.write("POST", "/api/users/0/items", [], {"If-Unmodified-Since-Version": "7"})
    assert result == (200, {}, "accepted")
    assert versions == ["7", "8"]


def test_requests_to_zotero_pass_by_a_proxy_the_environment_names(monkeypatch):
    """http_proxy without no_proxy must not send the calls to the local server elsewhere."""
    import http.server
    import threading

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(cli, "BASE", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("NO_PROXY", raising=False)
        status, _, _ = cli.http("GET", "/api/", timeout=5)
    finally:
        server.shutdown()
    assert status == 200


@pytest.mark.parametrize("value, port", [(None, 23119), ("", 23119), (" ", 23119), ("23129", 23129), (" 23129 ", 23129),
                                         ("1", 1), ("65535", 65535)])
def test_the_port_comes_from_the_environment_when_it_is_set(value, port):
    env = {} if value is None else {"SCHOLIUM_ZOTERO_PORT": value}
    assert cli.zotero_base(env) == f"http://127.0.0.1:{port}"


@pytest.mark.parametrize("value", ["0", "65536", "99999", "abc", "-1", "23129x", ":23129", "2312.9", "²", "123456"])
def test_a_port_that_is_no_port_number_is_an_error(value):
    with pytest.raises(SystemExit) as stop:
        cli.zotero_base({"SCHOLIUM_ZOTERO_PORT": value})
    assert f'SCHOLIUM_ZOTERO_PORT is "{value}"' in str(stop.value.code) and "not a port number" in str(stop.value.code)


def test_the_script_takes_the_port_when_it_is_loaded(tmp_path):
    """Read at import, without a request."""
    import os
    import subprocess
    import sys
    code = "import sys; sys.path.insert(0, sys.argv[1]); import scholium; print(scholium.BASE)"
    skill = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "zotero-scholium", "scripts")
    run = lambda env: subprocess.run([sys.executable, "-c", code, skill], capture_output=True, text=True,
                                     env=env, cwd=str(tmp_path), timeout=60)
    base = {k: v for k, v in os.environ.items() if k != "SCHOLIUM_ZOTERO_PORT"}
    assert run(dict(base, SCHOLIUM_ZOTERO_PORT="23129")).stdout.strip() == "http://127.0.0.1:23129"
    assert run(base).stdout.strip() == run(dict(base, SCHOLIUM_ZOTERO_PORT="")).stdout.strip() == "http://127.0.0.1:23119"
    wrong = run(dict(base, SCHOLIUM_ZOTERO_PORT="99999"))
    assert wrong.returncode != 0 and not wrong.stdout and 'SCHOLIUM_ZOTERO_PORT is "99999"' in wrong.stderr
    assert "Traceback" not in wrong.stderr


def test_requests_name_the_chosen_port_in_their_host_header(monkeypatch):
    """Zotero's server answers only a Host of its own address and port."""
    import http.server
    import threading
    seen = []

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Host"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        monkeypatch.setattr(cli, "BASE", cli.zotero_base({"SCHOLIUM_ZOTERO_PORT": str(port)}))
        status, _, _ = cli.http("GET", "/api/", timeout=5)
    finally:
        server.shutdown()
    assert status == 200 and seen == [f"127.0.0.1:{port}"]
    monkeypatch.setattr(cli, "http", lambda *a, **k: (0, {}, "refused"))
    assert cli.zotero_down() == f"Zotero does not answer on 127.0.0.1:{port}; start Zotero, then run again"
