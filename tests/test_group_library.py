"""The skill's script on a paper of a group library: the local API's group paths, the plugin's requests naming the group,
the group taken from paper.json, an older plugin that writes My Library only, and the generated JavaScript."""
import json
import shutil
import subprocess

import pymupdf
import pytest

from zotero_scholium import cli

NODE = shutil.which("node")


def test_the_local_api_reads_and_writes_the_group_library(monkeypatch):
    sent = []

    def http(method, path, body=None, headers=None, timeout=60):
        sent.append((method, path))
        if method == "POST":
            return 200, {"Last-Modified-Version": "3"}, json.dumps({"successful": {"0": {"key": "NEW1"}}, "failed": {}})
        if method == "DELETE":
            return 204, {}, ""
        return 200, {"Last-Modified-Version": "3"}, json.dumps([] if "children" in path else {"key": "ATT", "data": {}})
    monkeypatch.setattr(cli, "http", http)
    api = cli.LocalApi("SID", cli.library_path(777))
    api.key = "KEY"
    api.children("ATT", "annotation"); api.item("ATT"); api.create([{"itemType": "annotation"}])
    api.delete(["OLD"]); api.trash([{"key": "N", "data": {"version": 2}}])
    assert sent and all(path.startswith("/api/groups/777/items") for _, path in sent), sent
    assert cli.library_path() == cli.library_path(None) == "/api/users/0"


def test_the_local_api_gets_the_configurations_group(monkeypatch):
    monkeypatch.setattr(cli, "plugin_connect", lambda cfg: (None, "Scholium plugin is not installed (HTTP 404)", None))
    monkeypatch.setattr(cli, "zotero_version", lambda: ("10.0.1", "SID"))
    name, api, _ = cli.pick_backend("auto", {"group_id": 777, "library_id": 5})
    assert name == "api" and api.lib == "/api/groups/777"
    assert cli.pick_backend("api", {})[1].lib == "/api/users/0"


def _paper(tmp_path, paper=None, **options):
    pdf = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 120), "The method improves the result.")
        doc.save(pdf)
    out = tmp_path / "out"
    out.mkdir()
    if paper is not None:
        (out / "paper.json").write_text(json.dumps(paper), encoding="utf8")
    cfg = dict({"pdf": str(pdf), "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(out), "data_dir": str(tmp_path),
                "highlights": [{"page": 1, "text": "The method improves the result.", "comment": ""}]}, **options)
    path = out / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf8")
    (tmp_path / "scholium.token").write_text("TOKEN", encoding="utf8")
    return path


def _run(capsys, *argv):
    code = 0
    try:
        cli.main(list(argv))
    except SystemExit as e:
        code = e.code
    return code, json.loads(capsys.readouterr().out)


def _plugin(monkeypatch, listed=True):
    """The plugin's endpoints; listed: the listing names its library, as the plugin from 0.2.2 does."""
    bodies = []

    def http(method, path, body=None, headers=None, timeout=60):
        if not path.startswith("/scholium/"):
            return 0, {}, "refused"
        bodies.append((path, {k: v for k, v in (body or {}).items() if k in ("attachmentKey", "groupID", "libraryID")}))
        if path == "/scholium/apply":
            return 200, {}, json.dumps({"ok": True, "createdKeys": ["NEW1"], "noteKeys": []})
        listing = {"ok": True, "version": "0.2.2", "annotations": [{"key": "NEW1", "tags": ["zotero-scholium"]}] if len(bodies) > 3 else [],
                   "notes": []}
        if listed:
            listing["libraryID"] = 5
        return 200, {}, json.dumps(listing)
    monkeypatch.setattr(cli, "http", http)
    return bodies


@pytest.mark.parametrize("paper, options, named", [
    ({"attachment_key": "ATT", "group_id": 777, "library_id": 5}, {}, {"groupID": 777}),
    (None, {"group_id": 777}, {"groupID": 777}),
    (None, {"library_id": 5}, {"libraryID": 5}),
    ({"attachment_key": "OTHER", "group_id": 777}, {}, {}),
    (None, {}, {}),
], ids=["paper.json", "config", "library-id", "another-papers-paper.json", "my-library"])
def test_the_plugins_requests_name_the_papers_library(tmp_path, monkeypatch, capsys, paper, options, named):
    bodies = _plugin(monkeypatch)
    code, report = _run(capsys, "--config", str(_paper(tmp_path, paper, **options)), "--apply", "--backend", "plugin")
    assert code == 0 and report["applied"] is True
    assert {p for p, _ in bodies} == {"/scholium/list", "/scholium/apply"}
    assert all(body == dict({"attachmentKey": "ATT"}, **named) for _, body in bodies)


def test_an_older_plugin_is_not_asked_to_write_to_a_group(tmp_path, monkeypatch, capsys):
    bodies = _plugin(monkeypatch, listed=False)
    code, report = _run(capsys, "--config", str(_paper(tmp_path, None, group_id=777)), "--apply", "--backend", "plugin",
                        "--ignore-existing")
    assert code == 2 and report["applied"] is False
    assert "reads and writes My Library only; update it" in report["apply_error"]
    assert "/scholium/apply" not in [p for p, _ in bodies]


@pytest.mark.parametrize("value", ["777", 0, True, 1.5])
def test_group_id_and_library_id_are_numbers(value):
    base = {"pdf": "p.pdf", "item_key": "I", "attachment_key": "A", "out_dir": "o"}
    for key in ("group_id", "library_id"):
        assert cli.config_problems(dict(base, **{key: value})) == [f"{key} must be a number from 1 (as paper.json gives it)"]
    assert cli.config_problems(dict(base, group_id=777, library_id=5)) == []


RUN_JS = r"""
const vm = require('node:vm');
const script = require('node:fs').readFileSync(0, 'utf8');
const saved = [];
const asked = [];
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1 },
  Groups: { getLibraryIDFromGroupID: id => (id === 777 ? 5 : false) },
  Items: { getByLibraryAndKey: (lib, key) => { asked.push([lib, key]); return lib === 5 ? { id: key === 'ATT' ? 1 : 2, key, parentID: 2, getNotes: () => [], getAnnotations: () => [] } : null; },
           get: ids => [], trashTx: async () => {} },
  DB: { executeTransaction: async callback => callback() },
  Item: class { constructor(type) { this.type = type; } setNote() {} setTags() {} async save() { saved.push([this.type, this.libraryID]); } },
} });
vm.runInContext('(async function () {\n' + script + '\n})()', context)
  .then(() => process.stdout.write(JSON.stringify({ asked, saved })), error => process.stdout.write(JSON.stringify({ error: error.message, asked })));
"""


@pytest.mark.skipif(NODE is None, reason="Node.js is required to run the generated JavaScript")
@pytest.mark.parametrize("group, error", [(777, None), (555, "group not found in this Zotero: 555")])
def test_the_generated_javascript_writes_in_the_group_library(group, error):
    cfg = dict(cli.DEFAULTS, item_key="ITEM", attachment_key="ATT", group_id=group)
    highlight = {"type": "highlight", "color": "#ffd400", "comment": "", "text": "New result.", "pageLabel": "1",
                 "sortIndex": "00000|000000|00001", "position": {"pageIndex": 0, "rects": [[10, 10, 100, 20]]}}
    out = json.loads(subprocess.run([NODE, "-e", RUN_JS], input=cli.render_js(cfg, [highlight]), encoding="utf8",
                                    capture_output=True, check=True, timeout=15).stdout)
    assert out.get("error") == error
    if not error:
        assert out["asked"] == [[5, "ITEM"], [5, "ATT"]] and out["saved"] == [["annotation", 5]]
