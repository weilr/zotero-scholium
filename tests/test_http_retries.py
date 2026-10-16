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

    def urlopen(req, timeout=None):
        tries.append(req.full_url)
        raise cli.urllib.error.URLError(failure)

    monkeypatch.setattr(cli.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cli.time, "sleep", waits.append)
    status, _, _ = cli.http("GET", "/api/")
    assert status == 0 and len(tries) == attempts and len(waits) == attempts - 1


def test_the_js_backend_does_not_ask_zotero(monkeypatch):
    """Only the local API needs Zotero's version: a requested Run-JavaScript file waits for nothing."""
    asked = []
    monkeypatch.setattr(cli, "http", lambda method, path, *a, **k: asked.append(path) or (0, {}, "refused"))
    assert cli.pick_backend("js", {})[0] == "js" and asked == []
    cli.pick_backend("auto", {})
    assert asked[0] == "/api/"


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
