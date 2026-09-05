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
    async save() { saved.push(this); }
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
