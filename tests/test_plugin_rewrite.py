"""A rewrite in place through the plugin's /scholium/apply and through the JavaScript file: the annotations named to change
are changed in their given fields only, those to keep are not saved, only those named are deleted, and the reading note
named is rewritten in place. A key that is not one of the tool's annotations of the attachment, or one of the tool's not
named, ends the write before anything is saved. The plugin's listing says it can update (canUpdate) and gives the tool's
notes their text; the CLI sends a plan only to a plugin that says so, else it deletes and creates as before. An
in-memory Zotero stands in for Zotero; nothing reaches a socket."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from plugin_harness import LOAD_PLUGIN
from zotero_scholium import cli

BOOTSTRAP = Path(__file__).resolve().parents[1] / "plugin/scholium/bootstrap.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

# an in-memory Zotero: the attachment's annotations and the parent's notes as items that record their saves
RUN = LOAD_PLUGIN + r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const saves = [], erased = [], trashed = [];
let n = 0;
class Item {
  constructor(type, fields = {}) {
    this.itemType = type; this.key = fields.key || 'NEW' + (++n); this.id = this.key; this.tags = (fields.tags || []).map(tag => ({ tag }));
    Object.assign(this, { annotationType: fields.type, annotationComment: fields.comment || '', annotationText: fields.text || '',
                          annotationColor: fields.color || '#ffd400', annotationPageLabel: fields.pageLabel || '1',
                          annotationPosition: JSON.stringify(fields.position || { pageIndex: 0, rects: [[0, 0, 1, 1]] }),
                          annotationIsExternal: !!fields.external, note: fields.html || '', dateModified: fields.modified || '2026-11-10 10:00:00' });
  }
  getTags() { return this.tags; }
  setTags(tags) { this.tags = tags; }
  getNote() { return this.note; }
  setNote(html) { this.note = html; }
  getNoteTitle() { const m = /<h1[^>]*>(.*?)<\/h1>/i.exec(this.note); return m ? m[1] : ''; }
  async save() { saves.push(this.key); if (!items.includes(this)) items.push(this); }
  async saveTx() { return this.save(); }
  async erase() { erased.push(this.key); items.splice(items.indexOf(this), 1); }
}
const items = input.existing.map(a => new Item(a.kind || 'annotation', a));
const notes = () => items.filter(i => i.itemType === 'note');
const parent = { id: 'PARENT01', key: 'PARENT01', getNotes: () => notes().map(i => i.id) };
const attachment = { id: 'ATTACH01', key: 'ATTACH01', parentID: 'PARENT01', getAnnotations: () => items.filter(i => i.itemType === 'annotation') };
const context = vm.createContext({ Zotero: {
  debug() {},
  Prefs: { get: () => true, set: () => {} },
  Reader: { _readers: [] },
  Libraries: { userLibraryID: 1, get: () => null },
  Groups: { getLibraryIDFromGroupID: () => null },
  Items: { getByLibraryAndKey: (lib, key) => (key === 'PARENT01' ? parent : key === 'ATTACH01' ? attachment : null),
           get: ids => (Array.isArray(ids) ? ids.map(id => items.find(i => i.id === id)) : ids === 'PARENT01' ? parent : null),
           trashTx: async ids => { trashed.push(...ids); } },
  DB: { executeTransaction: async callback => callback() },
  Item: class extends Item { constructor(type) { super(type); } },
} });
let run;
if (input.script) run = vm.runInContext('(async function () {\n' + input.script + '\n})()', context);
else {
  loadPlugin(context, process.argv[1]);
  run = input.list ? context.ScholiumEndpoints.list(input.data) : context.ScholiumEndpoints.apply(input.data);
}
run.then(result => process.stdout.write(JSON.stringify({ result, saves, erased, trashed,
  items: items.map(i => ({ key: i.key, type: i.itemType, comment: i.annotationComment, color: i.annotationColor, text: i.annotationText,
                           position: i.annotationPosition, note: i.note })) })),
         error => process.stdout.write(JSON.stringify({ error: String(error && error.message || error), saves, erased })));
"""


def zotero(data=None, existing=(), script=None, listing=False):
    done = subprocess.run([NODE, "-e", RUN, str(BOOTSTRAP)], input=json.dumps({"data": data, "existing": list(existing), "script": script,
                                                                                  "list": listing}),
                          text=True, encoding="utf8", capture_output=True, check=True, timeout=30)
    return json.loads(done.stdout)


OWN = ["zotero-scholium"]
EXISTING = [{"key": "A1", "type": "highlight", "text": "First.", "comment": "旧译文。", "tags": OWN},
            {"key": "A2", "type": "highlight", "text": "Second.", "comment": "第二句。", "tags": OWN},
            {"key": "U1", "type": "highlight", "text": "Mine.", "comment": "my note"},
            {"key": "N1", "kind": "note", "html": "<h1>Paper</h1><p>Old.</p>", "tags": OWN},
            {"key": "N2", "kind": "note", "html": "<h1>Mine</h1><p>The user's.</p>"}]
NEW = {"type": "highlight", "text": "Third.", "comment": "第三句。", "color": "#ffd400", "pageLabel": "1", "sortIndex": "00000|000001|00000",
       "position": {"pageIndex": 0, "rects": [[10, 10, 20, 20]]}}


def request(**over):
    return dict({"attachmentKey": "ATTACH01", "itemKey": "PARENT01", "tag": "zotero-scholium", "cleanup": True, "rewrite": True,
                 "annotations": [], "updates": [], "keep": [], "remove": []}, **over)


def by_key(out):
    return {i["key"]: i for i in out["items"]}


def test_the_listing_says_it_updates_and_gives_the_tools_notes_their_text():
    out = zotero({"attachmentKey": "ATTACH01", "noteHtml": True}, EXISTING, listing=True)["result"]
    assert out["canUpdate"] is True
    notes = {n["key"]: n for n in out["notes"]}
    assert notes["N1"]["html"] == "<h1>Paper</h1><p>Old.</p>" and "html" not in notes["N2"], "the user's note keeps its text"


def test_a_changed_comment_is_the_only_save():
    out = zotero(request(updates=[{"key": "A1", "comment": "新译文。"}], keep=["A2"]), EXISTING)
    r = out["result"]
    assert r["ok"] and r["updatedKeys"] == ["A1"] and r["keptKeys"] == ["A2"] and r["createdKeys"] == [] and r["removed"] == 0
    assert out["saves"] == ["A1"] and out["erased"] == []
    assert by_key(out)["A1"]["comment"] == "新译文。" and by_key(out)["A1"]["text"] == "First." and by_key(out)["A2"]["comment"] == "第二句。"


def test_only_the_named_one_is_deleted():
    out = zotero(request(keep=["A1"], remove=["A2"]), EXISTING)
    assert out["result"]["removed"] == 1 and out["erased"] == ["A2"] and out["saves"] == []


def test_mixed():
    out = zotero(request(annotations=[NEW], updates=[{"key": "A1", "color": "#FF6666", "position": {"pageIndex": 0, "rects": [[1, 2, 3, 4]]},
                                                       "sortIndex": "00000|000000|00002"}], remove=["A2"]), EXISTING)
    r = out["result"]
    assert r["createdKeys"] and r["updatedKeys"] == ["A1"] and r["removed"] == 1 and r["kept"] == 1, "the user's annotation stays"
    a1 = by_key(out)["A1"]
    assert a1["color"] == "#ff6666" and json.loads(a1["position"])["rects"] == [[1, 2, 3, 4]] and a1["comment"] == "旧译文。"


@pytest.mark.parametrize("plan, why", [
    ({"updates": [{"key": "U1", "comment": "x"}], "keep": ["A1"], "remove": ["A2"]}, "is not one of the tool's"),
    ({"keep": ["A1"], "remove": ["U1", "A2"]}, "is not one of the tool's"),
    ({"keep": ["A1"]}, "changed since they were read"),
    ({"keep": ["A1", "GONE"], "remove": ["A2"]}, "is not one of the tool's"),
])
def test_a_plan_that_does_not_fit_the_attachment_writes_nothing(plan, why):
    out = zotero(request(annotations=[NEW], **plan), EXISTING)
    assert why in out["error"] and out["saves"] == [] and out["erased"] == []


def test_the_reading_note_is_rewritten_in_place():
    note = {"html": "<h1>Paper</h1><p>New.</p>", "titlePrefix": "Paper", "trashOwn": True, "trashTitlePrefix": "Paper", "updateKey": "N1",
            "expectHtml": "<h1>Paper</h1><p>Old.</p>"}
    out = zotero(request(keep=["A1", "A2"], note=note), EXISTING)
    r = out["result"]
    assert r["noteKeys"] == ["N1"] and r["noteUpdated"] is True and r["noteCreated"] is False and out["trashed"] == []
    assert by_key(out)["N1"]["note"] == "<h1>Paper</h1><p>New.</p>" and out["saves"] == ["N1"]
    # a note key that is not the tool's: the user's note is left alone, the tool's goes to the trash, a new one is written
    out = zotero(request(keep=["A1", "A2"], note=dict(note, updateKey="N2")), EXISTING)
    assert "error" not in out and by_key(out)["N2"]["note"] == "<h1>Mine</h1><p>The user's.</p>" and out["trashed"] == ["N1"]
    assert out["result"]["noteCreated"] is True and not out["result"].get("noteUpdated")


def test_without_a_plan_the_tools_annotations_are_deleted_and_created_as_before():
    out = zotero({"attachmentKey": "ATTACH01", "itemKey": "PARENT01", "tag": "zotero-scholium", "cleanup": True, "annotations": [NEW]}, EXISTING)
    assert sorted(out["erased"]) == ["A1", "A2"] and len(out["result"]["createdKeys"]) == 1 and "updatedKeys" not in out["result"]


# the CLI's side: a plan goes only to a plugin that can update

def payload_sent(monkeypatch, can_update, plan, cfg):
    listing = dict({"ok": True, "annotations": [], "notes": []}, **({"canUpdate": True} if can_update else {}))
    monkeypatch.setattr(cli, "plugin_connect", lambda c: ("TOKEN", listing, "/scholium"))
    sent = []
    monkeypatch.setattr(cli, "http", lambda method, path, body=None, *a, **k: sent.append(body) or (200, {}, json.dumps({"ok": True})))
    cli.plugin_apply(cfg, [dict(NEW, comment="a"), dict(NEW, comment="b")], plan)
    return sent[0]


def test_the_cli_sends_the_plan_to_a_plugin_that_can_update(monkeypatch):
    plan = {"create": [1], "update": [{"key": "A1", "index": 0, "fields": {"comment": "a"}}], "keep": [{"key": "A2", "index": 0}],
            "remove": ["A3"], "note": None}
    cfg = dict(cli.DEFAULTS, item_key="PARENT01", attachment_key="ATTACH01", cleanup=True)
    sent = payload_sent(monkeypatch, True, plan, cfg)
    assert sent["rewrite"] is True and [a["comment"] for a in sent["annotations"]] == ["b"]
    assert sent["updates"] == [{"key": "A1", "comment": "a"}] and sent["keep"] == ["A2"] and sent["remove"] == ["A3"]
    old = payload_sent(monkeypatch, False, plan, cfg)   # an older plugin: delete and create as before
    assert "rewrite" not in old and "updates" not in old and [a["comment"] for a in old["annotations"]] == ["a", "b"]


# the JavaScript file

def test_the_javascript_file_rewrites_in_place(tmp_path):
    cfg = dict(cli.DEFAULTS, item_key="PARENT01", attachment_key="ATTACH01", cleanup=True)
    plan = {"create": [0], "update": [{"key": "A1", "index": 1, "fields": {"comment": "新译文。"}}], "keep": [], "remove": ["A2"], "note": None}
    out = zotero(script=cli.render_js(cfg, [NEW, dict(NEW, text="First.")], plan), existing=EXISTING)
    assert "error" not in out, out.get("error")
    assert out["erased"] == ["A2"] and by_key(out)["A1"]["comment"] == "新译文。" and "U1" in by_key(out)
    assert sorted(out["saves"]) == sorted(["A1", next(k for k in by_key(out) if k.startswith("NEW"))])
    assert "changed 1, left 0 as they were" in out["result"]
    # keys that are no longer there: nothing is written
    stale = dict(plan, remove=["GONE"])
    out = zotero(script=cli.render_js(cfg, [NEW, dict(NEW, text="First.")], stale), existing=EXISTING)
    assert "is not one of the tool's" in out["error"] and out["saves"] == [] and out["erased"] == []


def test_a_rewrite_on_an_attachment_without_the_tools_annotations_creates_them():
    out = zotero(request(annotations=[NEW, dict(NEW, text="Fourth.")]), [e for e in EXISTING if e["key"] in ("U1", "N2")])
    r = out["result"]
    assert len(r["createdKeys"]) == 2 and r["updatedKeys"] == [] and r["removed"] == 0 and out["erased"] == []


def test_the_javascript_file_rewrites_the_reading_note_in_place(tmp_path):
    note = tmp_path / "note.html"
    note.write_text("<h1>Paper</h1><p>New.</p>", encoding="utf8")
    cfg = dict(cli.DEFAULTS, item_key="PARENT01", attachment_key="ATTACH01", cleanup=True, note_html=str(note), note_replace=True,
               note_title_prefix="Paper")
    plan = {"create": [], "update": [], "keep": [{"key": "A1", "index": 0}, {"key": "A2", "index": 1}], "remove": [],
            "note": {"update": "N1", "expect": "<h1>Paper</h1><p>Old.</p>"}}
    out = zotero(script=cli.render_js(cfg, [NEW, NEW], plan), existing=EXISTING)
    assert "error" not in out, out.get("error")
    assert by_key(out)["N1"]["note"] == "<h1>Paper</h1><p>New.</p>" and out["trashed"] == [] and out["saves"] == ["N1"]
    assert "rewritten in place" in out["result"]
