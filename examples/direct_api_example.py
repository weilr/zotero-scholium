"""Minimal example: create one highlight in Zotero 10 or later through the official local API, without a plugin.

Zotero must be running. The authorisation request opens a confirmation dialog in Zotero.
"""
import json, urllib.request

BASE = "http://127.0.0.1:23119"
ATTACHMENT_KEY = "XXXXXXXX"   # key of a PDF attachment in the library


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status, dict(r.headers), r.read().decode()


# 1. Every response carries the server ID; write requests must include it.
_, headers, _ = call("GET", "/api/")
server_id = headers["Zotero-Server-ID"]

# 2. Request an API key; Zotero shows an Allow / Always Allow / Deny dialog.
_, _, body = call("POST", "/api/local/authorize", {"appName": "direct_api_example"}, {"Zotero-Server-ID": server_id})
key = json.loads(body)["key"]

# 3. Create a highlight on page 1.
item = {
    "itemType": "annotation", "parentItem": ATTACHMENT_KEY, "annotationType": "highlight",
    "annotationText": "the highlighted sentence", "annotationComment": "my comment",
    "annotationColor": "#ffd400", "annotationPageLabel": "1", "annotationSortIndex": "00000|000000|00100",
    "annotationPosition": json.dumps({"pageIndex": 0, "rects": [[72, 680, 400, 694]]}),
    "tags": [{"tag": "direct_api_example"}],
}
status, _, body = call("POST", "/api/users/0/items", [item], {"Zotero-Server-ID": server_id, "Zotero-API-Key": key})
print(status, body[:300])
