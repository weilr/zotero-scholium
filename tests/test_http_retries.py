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
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        api.create([item])
    assert stored == [item], "an uncertain response must not duplicate the committed item"


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
