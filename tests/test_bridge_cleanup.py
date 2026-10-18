"""Run the real bridge apply handler with an in-memory Zotero boundary."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from zotero_scholium import cli


BRIDGE = Path(__file__).resolve().parents[1] / "plugin/scholium-bridge/bootstrap.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for bridge tests")

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
const attachment = { id: 1, key: 'ATTACH01', getAnnotations: () => existing };
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1 },
  Items: { getByLibraryAndKey: (libraryID, key) => {
    if (libraryID === 1 && key === 'PARENT01') return { id: 2 };
    if (libraryID !== 1 || key !== attachment.key) throw Error('unexpected attachment');
    return attachment;
  } },
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
  applied = context.ScholiumBridge.apply(input.data);
}
applied.then(result => {
  process.stdout.write(JSON.stringify({ result, remaining: existing.map(a => a.key), saved }));
}).catch(error => { console.error(error); process.exitCode = 1; });
"""


def run_apply(data, existing, script=None):
    completed = subprocess.run(
        [NODE, "-e", RUN_APPLY, str(BRIDGE)],
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
            {"tag": "", "legacyTags": []},
            ["blank", "same-comment", "same-text", "external", "current", "legacy"],
            0,
            6,
        ),
    ],
    ids=["default", "external-disabled", "external-enabled", "cleanup-disabled", "no-owned-tags"],
)
def test_cleanup_uses_ownership_tags_only(options, remaining, removed, kept):
    data = {
        "attachmentKey": "ATTACH01",
        "tag": "scholium",
        "legacyTags": ["old-scholium"],
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
        {"key": "current", "comment": "old output", "tags": ["scholium"]},
        {"key": "legacy", "comment": "older output", "tags": ["old-scholium"]},
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
const context = vm.createContext({ Zotero: { Libraries: { userLibraryID: 1 }, Items: { getByLibraryAndKey: () => attachment } } });
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.ScholiumBridge.list({ attachmentKey: 'ATTACH01' }).then(r => process.stdout.write(JSON.stringify(r)));
"""
    out = json.loads(subprocess.run([NODE, "-e", script, str(BRIDGE)], text=True, capture_output=True, check=True, timeout=15).stdout)
    assert out["ok"] and out["version"] == cli.__version__ and out["annotations"] == []


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
        [NODE, "-e", harness, str(BRIDGE)],
        input=json.dumps({"data": data, "existing": existing, "script": script}),
        text=True, capture_output=True, check=True, timeout=15,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize("channel", ["bridge", "generated-js"])
def test_a_failed_write_keeps_the_old_annotations(channel):
    annotations = [{"type": "highlight", "comment": "", "text": f"new {i}", "color": "#ffd400", "pageLabel": "1",
                    "sortIndex": "0", "position": {"pageIndex": 0, "rects": [[1, 1, 5, 5]]}} for i in range(2)]
    existing = [{"key": "OLD_OWN", "comment": "old output", "tags": ["zotero-scholium"]}, {"key": "USER", "comment": "mine"}]
    if channel == "bridge":
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
const parent = { id: 2, getNotes: () => notes.map(n => n.id) };
const attachment = { id: 1, key: 'ATTACH01', parentID: 2, getAnnotations: () => [] };
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1 },
  Items: {
    getByLibraryAndKey: (lib, key) => key === 'PARENT01' ? parent : key === 'ATTACH01' ? attachment : null,
    get: ids => Array.isArray(ids) ? ids.map(id => notes.find(n => n.id === id)) : ids === 2 ? parent : notes.find(n => n.id === ids),
    trashTx: async ids => { trashed.push(...ids.map(id => notes.find(n => n.id === id).key)); },
  },
  DB: { executeTransaction: async callback => callback() },
  Item: class {
    constructor(type) { this.type = type; }
    setNote(html) { this.html = html; }
    setTags(tags) { this.tags = tags; }
    async saveTx() { created.push(this.html); this.key = 'NOTE' + created.length; }
    async save() {}
  },
} });
let applied;
if (input.script) {
  applied = vm.runInContext('(async function () {\n' + input.script + '\n})()', context);
} else {
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  applied = context.ScholiumBridge.apply(input.data);
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


def run_notes(channel, notes, html, replace, prefix=""):
    """A note written by the bridge or by the generated JavaScript: (result, notes created, keys moved to the trash)."""
    if channel == "bridge":
        data = {"attachmentKey": "ATTACH01", "itemKey": "PARENT01", "tag": "zotero-scholium", "legacyTags": ["zotero-marginalia"],
                "annotations": [], "note": {"html": html, "titlePrefix": "", "trashOwn": replace, "trashTitlePrefix": prefix}}
        payload = {"data": data, "notes": notes, "script": None}
    else:
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf8") as f:
            f.write(html)
        cfg = {"item_key": "PARENT01", "attachment_key": "ATTACH01", "note_html": f.name, "note_replace": replace,
               "note_title_prefix": prefix or None}
        payload = {"data": {}, "notes": notes, "script": cli.render_js(cfg, [])}
        os.unlink(f.name)
    completed = subprocess.run([NODE, "-e", RUN_NOTES, str(BRIDGE)], input=json.dumps(payload), text=True,
                               capture_output=True, check=True, timeout=15)
    out = json.loads(completed.stdout)
    return out["result"], out["created"], out["trashed"]


@pytest.mark.parametrize("channel", ["bridge", "generated-js"])
def test_note_replace_moves_only_the_tools_notes_to_the_trash(channel):
    result, created, trashed = run_notes(channel, EARLIER_NOTES, NEW_NOTE, True)
    assert len(created) == 1 and "The new reading note." in created[0]
    assert trashed == ["OWN_OLD", "LEGACY", "OWN_OTHER"], "the user's note stays, whatever its title"
    result, created, trashed = run_notes(channel, EARLIER_NOTES, NEW_NOTE, True, prefix="Paper")
    assert trashed == ["OWN_OLD", "LEGACY"], "with a title prefix only the tool's notes under that title"
    result, created, trashed = run_notes(channel, EARLIER_NOTES, NEW_NOTE, False)
    assert len(created) == 1 and trashed == [], "without note_replace nothing goes"
    if channel == "bridge":
        assert result["noteKeys"] == ["NOTE1"]


@pytest.mark.parametrize("channel", ["bridge", "generated-js"])
def test_a_note_with_the_same_text_is_not_written_again(channel):
    notes = EARLIER_NOTES + [{"key": "SAME", "html": "<h1>Paper (v3, 2026-10-16)</h1><p>The new reading note.</p>",
                              "tags": ["zotero-scholium"]}]
    result, created, trashed = run_notes(channel, notes, NEW_NOTE, True)
    assert created == [] and "SAME" not in trashed and trashed == ["OWN_OLD", "LEGACY", "OWN_OTHER"]
    if channel == "bridge":
        assert result["noteKeys"] == []
    # the same text in the user's own note is no reason to skip
    result, created, trashed = run_notes(channel, [{"key": "USER", "html": NEW_NOTE}], NEW_NOTE, False)
    assert len(created) == 1
