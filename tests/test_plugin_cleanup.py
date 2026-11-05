"""Run the plugin's real apply handler with an in-memory Zotero boundary."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from zotero_scholium import cli


BOOTSTRAP = Path(__file__).resolve().parents[1] / "plugin/scholium/bootstrap.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

RUN_APPLY = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const saved = [];
let existing = input.existing.map(a => ({
  key: a.key,
  annotationComment: a.comment,
  annotationText: a.text || '',
  annotationIsExternal: !!a.external,
  getTags: () => (a.tags || []).map(tag => ({ tag })),
  async eraseTx() { existing = existing.filter(item => item.key !== this.key); },
  async erase() { existing = existing.filter(item => item.key !== this.key); },
}));
const parent = { id: 2, key: 'PARENT01' };
const attachment = { id: 1, key: 'ATTACH01', parentID: 2, getAnnotations: () => existing };
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1 },
  Items: { getByLibraryAndKey: (libraryID, key) => {
    if (libraryID === 1 && key === 'PARENT01') return parent;
    if (libraryID !== 1 || key !== attachment.key) throw Error('unexpected attachment');
    return attachment;
  }, get: id => (id === 2 ? parent : null) },
  DB: { executeTransaction: async callback => callback() },
  Item: class {
    constructor(type) {
      if (type !== 'annotation') throw Error('unexpected item type');
    }
    setTags(tags) { this.tags = tags; }
    async save() { this.key = 'NEW' + (saved.length + 1); saved.push(this); }
  },
} });
let applied;
if (input.script) {
  applied = vm.runInContext('(async function () {\n' + input.script + '\n})()', context);
} else {
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  applied = context.ScholiumEndpoints.apply(input.data);
}
applied.then(result => {
  process.stdout.write(JSON.stringify({ result, remaining: existing.map(a => a.key), saved }));
}).catch(error => { console.error(error); process.exitCode = 1; });
"""


def run_apply(data, existing, script=None):
    completed = subprocess.run(
        [NODE, "-e", RUN_APPLY, str(BOOTSTRAP)],
        input=json.dumps({"data": data, "existing": existing, "script": script}),
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("options", "remaining", "removed", "kept"),
    [
        ({}, ["blank", "same-comment", "same-text", "external"], 2, 4),
        ({"cleanupExternal": False}, ["blank", "same-comment", "same-text", "external"], 2, 4),
        ({"cleanupExternal": True}, ["blank", "same-comment", "same-text"], 3, 3),
        (
            {"cleanup": False, "cleanupExternal": True},
            ["blank", "same-comment", "same-text", "external", "current", "legacy"],
            0,
            0,
        ),
        (
            {"legacyTags": ["personal"]},
            ["blank", "same-comment", "same-text", "external"],
            2,
            4,
        ),
    ],
    ids=["default", "external-disabled", "external-enabled", "cleanup-disabled", "other-tags-requested"],
)
def test_cleanup_uses_ownership_tags_only(options, remaining, removed, kept):
    data = {
        "attachmentKey": "ATTACH01",
        "tag": "zotero-scholium",
        "legacyTags": ["zotero-marginalia"],
        "annotations": [
            {"type": "highlight", "comment": "", "text": "shared text", "position": {}},
            {"type": "highlight", "comment": "shared comment", "text": "new text", "position": {}},
        ],
        **options,
    }
    existing = [
        {"key": "blank", "comment": ""},
        {"key": "same-comment", "comment": "shared comment", "tags": ["personal"]},
        {"key": "same-text", "comment": "user comment", "text": "shared text"},
        {"key": "external", "comment": "", "external": True},
        {"key": "current", "comment": "old output", "tags": ["zotero-scholium"]},
        {"key": "legacy", "comment": "older output", "tags": ["zotero-marginalia"]},
    ]
    output = run_apply(data, existing)
    assert output["remaining"] == remaining
    assert output["result"]["removed"] == removed
    assert output["result"]["kept"] == kept
    assert output["result"]["created"]["highlight"] == 2
    assert len(output["saved"]) == 2
    assert output["result"]["createdKeys"] == ["NEW1", "NEW2"] and output["result"]["noteKeys"] == []


def test_the_listing_names_the_plugins_version():
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const attachment = { id: 1, key: 'ATTACH01', parentID: null, getAnnotations: () => [] };
const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const context = vm.createContext({
  Zotero: { Libraries: { userLibraryID: 1 }, Items: { getByLibraryAndKey: () => attachment }, initializationPromise: Promise.resolve(),
            debug() {}, DataDirectory: { dir: 'D' }, Utilities: { randomString: () => 'x'.repeat(40) }, Server: { Endpoints: {} } },
  PathUtils: { join: (...p) => p.join('/') }, IOUtils: { exists: async () => false, writeUTF8: async () => {} },
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
// startup gives the endpoints the version of the manifest it was installed with
context.startup({ id: manifest.applications.zotero.id, version: manifest.version, rootURI: '' })
  .then(() => context.ScholiumEndpoints.list({ attachmentKey: 'ATTACH01' }))
  .then(r => process.stdout.write(JSON.stringify(r)));
"""
    manifest = BOOTSTRAP.parent / "manifest.json"
    out = json.loads(subprocess.run([NODE, "-e", script, str(BOOTSTRAP), str(manifest)], text=True, capture_output=True, check=True,
                                    timeout=15).stdout)
    assert out["ok"] and out["version"] == json.loads(manifest.read_text(encoding="utf8"))["version"] == cli.__version__
    assert out["annotations"] == []


@pytest.mark.parametrize("cleanup", [True, False], ids=["cleanup-enabled", "cleanup-disabled"])
def test_generated_js_cleanup_uses_ownership_tags_only(cleanup):
    cfg = {"item_key": "PARENT01", "attachment_key": "ATTACH01", "cleanup": cleanup}
    annotations = [
        {"type": "highlight", "comment": "", "text": "shared text", "position": {}},
        {"type": "highlight", "comment": "shared comment", "text": "new text", "position": {}},
    ]
    existing = [
        {"key": "blank", "comment": ""},
        {"key": "same-comment", "comment": "shared comment", "tags": ["personal"]},
        {"key": "same-text", "comment": "user comment", "text": "shared text"},
        {"key": "external", "comment": "", "external": True},
        {"key": "current", "comment": "old output", "tags": ["zotero-scholium"]},
        {"key": "legacy", "comment": "older output", "tags": ["zotero-marginalia"]},
    ]
    output = run_apply({}, existing, cli.render_js(cfg, annotations))
    remaining = ["blank", "same-comment", "same-text", "external"]
    if not cleanup:
        remaining += ["current", "legacy"]
    assert output["remaining"] == remaining
    assert len(output["saved"]) == 2


def run_failing_apply(data, existing, script=None):
    """Like run_apply, but the second annotation fails to save; returns the error and what is left."""
    harness = RUN_APPLY.replace(
        "async save() { this.key = 'NEW' + (saved.length + 1); saved.push(this); }",
        "async save() { if (saved.length) throw Error('simulated save failure'); saved.push(this); }",
    ).replace(
        ".catch(error => { console.error(error); process.exitCode = 1; });",
        ".catch(error => { process.stdout.write(JSON.stringify({ error: error.message, remaining: existing.map(a => a.key) })); });",
    )
    completed = subprocess.run(
        [NODE, "-e", harness, str(BOOTSTRAP)],
        input=json.dumps({"data": data, "existing": existing, "script": script}),
        text=True, capture_output=True, check=True, timeout=15,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize("channel", ["plugin", "generated-js"])
def test_a_failed_write_keeps_the_old_annotations(channel):
    annotations = [{"type": "highlight", "comment": "", "text": f"new {i}", "color": "#ffd400", "pageLabel": "1",
                    "sortIndex": "0", "position": {"pageIndex": 0, "rects": [[1, 1, 5, 5]]}} for i in range(2)]
    existing = [{"key": "OLD_OWN", "comment": "old output", "tags": ["zotero-scholium"]}, {"key": "USER", "comment": "mine"}]
    if channel == "plugin":
        data = {"attachmentKey": "ATTACH01", "tag": "zotero-scholium", "annotations": annotations}
        output = run_failing_apply(data, existing)
    else:
        cfg = {"item_key": "PARENT01", "attachment_key": "ATTACH01", "cleanup": True}
        output = run_failing_apply({}, existing, cli.render_js(cfg, annotations))
    assert output == {"error": "simulated save failure", "remaining": ["OLD_OWN", "USER"]}


def test_generated_js_writes_the_text_of_underlines():
    cfg = {"item_key": "PARENT01", "attachment_key": "ATTACH01", "cleanup": True}
    underline = {"type": "underline", "comment": "", "text": "The selected sentence.", "color": "#ffd400", "pageLabel": "1",
                 "sortIndex": "0", "position": {"pageIndex": 0, "rects": [[1, 1, 5, 5]]}}
    output = run_apply({}, [], cli.render_js(cfg, [underline]))
    assert output["saved"][0]["annotationType"] == "underline"
    assert output["saved"][0]["annotationText"] == "The selected sentence."
    assert "1 underlines" in output["result"]


RUN_NOTES = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const notes = input.notes.map((n, i) => ({ id: i + 10, key: n.key, html: n.html, tags: n.tags || [],
  getNote() { return this.html; }, getNoteTitle() { return (this.html.match(/<h1[^>]*>(.*?)<\/h1>/) || [null, ''])[1]; },
  getTags() { return this.tags.map(tag => ({ tag })); } }));
const created = [], trashed = [];
const parent = { id: 2, key: 'PARENT01', getNotes: () => notes.map(n => n.id) };
const attachment = { id: 1, key: 'ATTACH01', parentID: 2, getAnnotations: () => [] };
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1 },
  Items: {
    getByLibraryAndKey: (lib, key) => key === 'PARENT01' ? parent : key === 'ATTACH01' ? attachment : null,
    get: ids => Array.isArray(ids) ? ids.map(id => notes.find(n => n.id === id)) : ids === 2 ? parent : notes.find(n => n.id === ids),
    trashTx: async ids => {
      if (input.trashFails) throw new Error('the trash is not available');
      trashed.push(...ids.map(id => notes.find(n => n.id === id).key));
    },
  },
  DB: { executeTransaction: async callback => callback() },
  Item: class {
    constructor(type) { this.type = type; }
    setNote(html) { this.html = html; }
    setTags(tags) { this.tags = tags; }
    async saveTx() { created.push(this.html); this.key = 'NOTE' + created.length; }
    async save() { if (this.type === 'note') { created.push(this.html); this.key = 'NOTE' + created.length; } }
  },
} });
let applied;
if (input.script) {
  applied = vm.runInContext('(async function () {\n' + input.script + '\n})()', context);
} else {
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  applied = context.ScholiumEndpoints.apply(input.data);
}
applied.then(result => { process.stdout.write(JSON.stringify({ result, created, trashed })); })
  .catch(error => { console.error(error); process.exitCode = 1; });
"""

EARLIER_NOTES = [
    {"key": "OWN_OLD", "html": "<h1>Paper</h1><p>An earlier reading note.</p>", "tags": ["zotero-scholium"]},
    {"key": "LEGACY", "html": "<h1>Paper (v2, 2026-09-01)</h1><p>A retry.</p>", "tags": ["zotero-marginalia"]},
    {"key": "OWN_OTHER", "html": "<h1>Questions</h1><p>Answers to the user.</p>", "tags": ["zotero-scholium"]},
    {"key": "USER", "html": "<h1>Paper</h1><p>My own thoughts.</p>"},
]
NEW_NOTE = "<h1>Paper</h1><p>The new reading note.</p>"


def run_notes(channel, notes, html, replace, prefix="", trash_fails=False):
    """A note written by the plugin or by the generated JavaScript: (result, notes created, keys moved to the trash)."""
    if channel == "plugin":
        data = {"attachmentKey": "ATTACH01", "itemKey": "PARENT01", "tag": "zotero-scholium", "legacyTags": ["zotero-marginalia"],
                "annotations": [], "note": {"html": html, "titlePrefix": "", "trashOwn": replace, "trashTitlePrefix": prefix}}
        payload = {"data": data, "notes": notes, "script": None, "trashFails": trash_fails}
    else:
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf8") as f:
            f.write(html)
        cfg = {"item_key": "PARENT01", "attachment_key": "ATTACH01", "note_html": f.name, "note_replace": replace,
               "note_title_prefix": prefix or None}
        payload = {"data": {}, "notes": notes, "script": cli.render_js(cfg, [])}
        os.unlink(f.name)
    completed = subprocess.run([NODE, "-e", RUN_NOTES, str(BOOTSTRAP)], input=json.dumps(payload), text=True,
                               capture_output=True, check=True, timeout=15)
    out = json.loads(completed.stdout)
    return out["result"], out["created"], out["trashed"]


@pytest.mark.parametrize("channel", ["plugin", "generated-js"])
def test_note_replace_moves_only_the_tools_notes_to_the_trash(channel):
    result, created, trashed = run_notes(channel, EARLIER_NOTES, NEW_NOTE, True)
    assert len(created) == 1 and "The new reading note." in created[0]
    assert trashed == ["OWN_OLD", "LEGACY", "OWN_OTHER"], "the user's note stays, whatever its title"
    result, created, trashed = run_notes(channel, EARLIER_NOTES, NEW_NOTE, True, prefix="Paper")
    assert trashed == ["OWN_OLD", "LEGACY"], "with a title prefix only the tool's notes under that title"
    result, created, trashed = run_notes(channel, EARLIER_NOTES, NEW_NOTE, False)
    assert len(created) == 1 and trashed == [], "without note_replace nothing goes"
    if channel == "plugin":
        assert result["noteKeys"] == ["NOTE1"]


def test_the_plugin_says_when_the_earlier_notes_could_not_go():
    result, created, trashed = run_notes("plugin", EARLIER_NOTES, NEW_NOTE, True, trash_fails=True)
    assert result["ok"] is True and len(created) == 1 and trashed == [], "the new note is written"
    assert result["notesTrashed"] == 0 and result["removeError"] == "the trash is not available"
    result, created, trashed = run_notes("plugin", EARLIER_NOTES, NEW_NOTE, True)
    assert "removeError" not in result


@pytest.mark.parametrize("channel", ["plugin", "generated-js"])
def test_a_note_with_the_same_text_is_not_written_again(channel):
    notes = EARLIER_NOTES + [{"key": "SAME", "html": "<h1>Paper (v3, 2026-10-16)</h1><p>The new reading note.</p>",
                              "tags": ["zotero-scholium"]}]
    result, created, trashed = run_notes(channel, notes, NEW_NOTE, True)
    assert created == [] and "SAME" not in trashed and trashed == ["OWN_OLD", "LEGACY", "OWN_OTHER"]
    if channel == "plugin":
        assert result["noteKeys"] == []
    # the same text in the user's own note is no reason to skip
    result, created, trashed = run_notes(channel, [{"key": "USER", "html": NEW_NOTE}], NEW_NOTE, False)
    assert len(created) == 1


def test_the_plugin_refuses_another_tag():
    """Only the tool's own tags mark what a run may remove; a request cannot name others."""
    data = {"attachmentKey": "ATTACH01", "tag": "to-read", "cleanup": True, "annotations": []}
    completed = subprocess.run([NODE, "-e", RUN_APPLY, str(BOOTSTRAP)], input=json.dumps({"data": data, "existing": [
        {"key": "USER", "comment": "", "tags": ["to-read"]}], "script": None}), text=True, capture_output=True, timeout=15)
    assert completed.returncode != 0 and "tag must be zotero-scholium" in completed.stderr


@pytest.mark.parametrize("item_key, fragment", [("OTHER001", "is not the parent of attachment ATTACH01")])
def test_the_plugin_refuses_a_note_for_another_item(item_key, fragment):
    data = {"attachmentKey": "ATTACH01", "itemKey": item_key, "tag": "zotero-scholium", "annotations": [],
            "note": {"html": NEW_NOTE, "titlePrefix": "", "trashOwn": True, "trashTitlePrefix": ""}}
    completed = subprocess.run([NODE, "-e", RUN_NOTES, str(BOOTSTRAP)], input=json.dumps({"data": data, "notes": EARLIER_NOTES, "script": None}),
                               text=True, capture_output=True, timeout=15)
    assert completed.returncode != 0 and fragment in completed.stderr


def test_the_new_copy_of_an_update_is_told_to_take_over():
    """Zotero starts the new copy of an update with ADDON_INSTALL or ADDON_UPGRADE; a start of Zotero hands nothing over."""
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({
  Zotero: { initializationPromise: Promise.resolve(), debug() {}, DataDirectory: { dir: 'D' }, Utilities: { randomString: () => 'x'.repeat(40) },
            Server: { Endpoints: {} } },
  PathUtils: { join: (...p) => p.join('/') }, IOUtils: { exists: async () => false, writeUTF8: async () => {} },
  setTimeout: () => 0, clearTimeout() {},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const started = [];
context.ScholiumRunner.start = (id, update) => { started.push(update); };
(async () => {
  for (const reason of [1, 3, 5, 7, 8]) await context.startup({ id: 'x', version: '0.1.9', rootURI: '' }, reason);
  process.stdout.write(JSON.stringify(started));
})();
"""
    out = json.loads(subprocess.run([NODE, "-e", script, str(BOOTSTRAP)], text=True, capture_output=True, check=True, timeout=15).stdout)
    assert out == [False, False, True, True, True]


def test_a_copy_that_stops_leaves_the_new_copys_endpoints():
    """During an update the new copy may register its endpoints before the old copy stops."""
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const endpoints = {};
const copy = () => {
  const context = vm.createContext({ Zotero: { Server: { Endpoints: endpoints }, debug() {} } });
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  return context.ScholiumEndpoints;
};
const old = copy(), fresh = copy();
old.register();
fresh.register();
old.unregister();
const kept = Object.keys(endpoints).filter(p => endpoints[p] === fresh.endpoints[p]).length;
fresh.unregister();
process.stdout.write(JSON.stringify({ kept, left: Object.keys(endpoints).length }));
"""
    out = json.loads(subprocess.run([NODE, "-e", script, str(BOOTSTRAP)], text=True, capture_output=True, check=True, timeout=15).stdout)
    assert out == {"kept": 6, "left": 0}


def test_after_an_update_the_endpoints_an_older_copy_removed_come_back():
    """A copy before 0.1.9 removes the endpoints whoever registered them; it may stop after the new copy started."""
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const endpoints = {}, later = [];
const context = vm.createContext({ Zotero: { Server: { Endpoints: endpoints }, debug() {} }, setTimeout: f => later.push(f), clearTimeout() {} });
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const plugin = context.ScholiumEndpoints;
plugin.register();
plugin.keep();
for (const p of Object.keys(endpoints)) delete endpoints[p];
later.forEach(f => f());
process.stdout.write(JSON.stringify(Object.keys(endpoints).filter(p => endpoints[p] === plugin.endpoints[p]).length));
"""
    out = json.loads(subprocess.run([NODE, "-e", script, str(BOOTSTRAP)], text=True, capture_output=True, check=True, timeout=15).stdout)
    assert out == 6
