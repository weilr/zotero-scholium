"""Papers in group libraries: the one question before the first annotation in each group, paper.json and the prompt
naming the group, runs and files kept apart from a paper of My Library with the same keys, the confirmations of a redo
and a deletion, a library the user cannot edit, and the endpoints writing in the library a request names."""
import json
from pathlib import Path
import subprocess

import pytest

from plugin_harness import LOAD_PLUGIN, NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const dirs = h => [...new Set(Object.keys(h.log.writes).filter(p => p.startsWith('/data/tmp/scholium/')).map(p => p.split('/')[4]))].sort();
  // the first annotation in a group asks once; the group's next paper does not; another group asks again (declined here)
  {
    const h = harness({ groups: { 2: { groupID: 777 }, 3: { groupID: 888 } }, confirm: [true, false] });
    h.runner.start('x');
    const g = h.groupPaper(2);
    const queued = await h.runner.annotate([g.item]); await settle(300);
    facts.first = { queued, confirms: h.log.confirms.slice(), asked: h.store.get('extensions.scholium.groupsAsked'), calls: h.log.calls.length,
                    paper: JSON.parse(h.log.writes['/data/tmp/scholium/ATT1_g777/paper.json']), prompt: h.log.stdin[0], dirs: dirs(h) };
    await h.runner.annotate([h.groupPaper(2, 'ATT9', 'ITEM9').item]); await settle(300);
    const declined = await h.runner.annotate([h.groupPaper(3, 'ATT5', 'ITEM5').item]); await settle(300);
    facts.again = { confirms: h.log.confirms.slice(1), calls: h.log.calls.length, declined, asked: h.store.get('extensions.scholium.groupsAsked') };
    h.runner.stop();
  }
  // a paper of My Library and one of a group with the same keys: each its own runs, files and sessions; a question about the
  // group's paper names the group too
  {
    const h = harness({ groups: { 2: { groupID: 777 } }, prefs: { 'extensions.scholium.groupsAsked': '777' } });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(300);
    const g = h.groupPaper(2);
    await h.runner.annotate([g.item]); await settle(300);
    await h.runner.send(g.item, '这篇讲什么？'); await settle(300);
    const mine = await h.pane(h.item1), theirs = await h.pane(g.item);
    const chats = key => Object.keys(h.log.writes).filter(p => p.startsWith(`/data/tmp/scholium/${key}/conversations/chat-`));
    facts.apart = { calls: h.log.calls.length, confirms: h.log.confirms.length, dirs: dirs(h), keys: [mine.pane().keys, theirs.pane().keys],
                    sessions: [mine.view('annotate').shownConv, theirs.view('annotate').shownConv],
                    chats: [chats('ATT1').length, chats('ATT1_g777').length], question: h.log.stdin[2],
                    mineChat: mine.view('chat').shownConv, theirsChat: theirs.view('chat').shownConv };
    h.runner.stop();
  }
  // Annotate again and Delete in a group say that every member is affected
  {
    const h = harness({ groups: { 2: { groupID: 777 } }, prefs: { 'extensions.scholium.groupsAsked': '777' }, confirm: false });
    h.runner.start('x');
    const g = h.groupPaper(2, 'ATT1', 'ITEM1', [h.ann('E0', 'highlight', '#ff6666')]);
    const redo = await h.runner.annotate([g.item]);
    await h.runner.removeAnnotations([g.item]);
    const p = await h.pane(g.item);
    p.pane().tabAnnotate.click();
    p.pane().annotGo.click();
    facts.shared = { redo, calls: h.log.calls.length, confirms: h.log.confirms.slice(), inline: p.pane().confirmRow.children[0].textContent,
                     mine: harness().runner.text('redo', 1, 0) };
    const en = harness({ locale: 'en-US' }).runner;
    facts.sharedEn = [en.text('redo', 2, 1, true), en.text('deleteConfirm', 2, 0, true), en.text('redoInline', 1, 0, true)];
    h.runner.stop();
  }
  // a group whose files the user cannot edit: nothing is annotated or deleted
  {
    const h = harness({ groups: { 2: { groupID: 777, filesEditable: false } }, existing: [] });
    h.runner.start('x');
    const g = h.groupPaper(2, 'ATT1', 'ITEM1', [h.ann('E0', 'highlight', '#ff6666')]);
    const queued = await h.runner.annotate([g.item]);
    const removed = await h.runner.removeAnnotations([g.item]);
    facts.locked = { queued, removed, calls: h.log.calls.length, alerts: h.log.alerts.slice(), confirms: h.log.confirms.length, erased: h.log.erased.slice() };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""

GROUP_FIRST = "批注会写进群组文库，群组的所有成员都能看到。继续吗？"
READ_ONLY = "你在这个群组里没有编辑权限，无法写入批注。"
SHARED = "这是群组文库：群组的所有成员都受影响。"


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_the_first_annotation_in_a_group_asks_once(facts):
    f = facts["first"]
    assert f["queued"] == 1 and f["calls"] == 1 and f["confirms"] == [GROUP_FIRST] and f["asked"] == "777"
    a = facts["again"]
    assert a["confirms"] == [GROUP_FIRST], "the group's next paper is not asked about; another group is"
    assert a["calls"] == 2 and a["declined"] == 0 and a["asked"] == "777", "a group declined is asked again next time"


def test_paper_json_and_the_prompt_name_the_group(facts):
    f = facts["first"]
    assert f["paper"] == {"pdf": "D:/Zotero/storage/ATT1/paper.pdf", "item_key": "ITEM1", "attachment_key": "ATT1",
                          "out_dir": "/data/tmp/scholium/ATT1_g777", "library_id": 2, "group_id": 777}
    assert f["dirs"] == ["ATT1_g777"]
    p = f["prompt"]
    assert "- 附件 key：ATT1\n- 群组文库：777（status 和 samples 加 --group 777）\n" in p
    assert "从 /data/tmp/scholium/ATT1_g777/paper.json 的六个键写起" in p
    assert "群组文库：777（status 和 samples 加 --group 777）" in facts["apart"]["question"], "a question's prompt too"


def test_a_group_paper_with_the_keys_of_a_paper_of_my_library_is_kept_apart(facts):
    a = facts["apart"]
    assert a["calls"] == 3 and a["confirms"] == 0
    assert a["dirs"] == ["ATT1", "ATT1_g777"], "My Library's files stay where they were"
    assert a["keys"] == [["ATT1"], ["ATT1_g777"]]
    assert a["sessions"][0] and a["sessions"][1], "each paper shows its own annotation session"
    assert a["chats"] == [0, 1] and a["mineChat"] is None and a["theirsChat"], "the question is the group paper's"


def test_annotate_again_and_delete_in_a_group_say_every_member_is_affected(facts):
    s = facts["shared"]
    assert s["redo"] == 0 and s["calls"] == 0
    assert s["confirms"][0] == "这篇论文已有 1 条 Scholium 批注。重新批注会先删除它们，你自己的批注和笔记不受影响。" + SHARED + "继续吗？"
    assert s["confirms"][1].endswith("删除会同步。" + SHARED + "继续吗？")
    assert s["inline"].endswith("（你自己的不动）。" + SHARED)
    assert SHARED not in s["mine"], "a paper of My Library is not"
    redo, delete, inline = facts["sharedEn"]
    assert redo.endswith("are not affected. This is a group library: it applies to every member. Continue?")
    assert delete.endswith("The deletion syncs. This is a group library: it applies to every member. Continue?")
    assert inline.endswith("(yours stay). This is a group library: it applies to every member.")


def test_a_group_whose_files_cannot_be_edited_is_left_alone(facts):
    f = facts["locked"]
    assert f["queued"] == 0 and f["removed"] == 0 and f["calls"] == 0 and f["confirms"] == 0 and f["erased"] == []
    assert f["alerts"] == [READ_ONLY, READ_ONLY]


ENDPOINTS = LOAD_PLUGIN + r"""
const fs = require('node:fs');
const vm = require('node:vm');
const saved = [];
const libs = { 1: { editable: true, filesEditable: true }, 2: { editable: true, filesEditable: true }, 3: { editable: false, filesEditable: true },
               4: { editable: true, filesEditable: false } };
const groups = { 777: 2, 888: 3, 999: 4 };
const att = lib => ({ id: 'A' + lib, key: 'ATT1', libraryID: lib, parentID: 'P' + lib, getAnnotations: () => [] });
const parent = lib => ({ id: 'P' + lib, key: 'ITEM1', libraryID: lib, getNotes: () => [] });
const context = vm.createContext({ Zotero: {
  Libraries: { userLibraryID: 1, get: id => libs[id] || false },
  Groups: { getLibraryIDFromGroupID: id => groups[id] || false },
  Items: { getByLibraryAndKey: (lib, key) => (libs[lib] && key === 'ATT1' ? att(lib) : null),
           get: id => (Array.isArray(id) ? [] : String(id).startsWith('P') ? parent(Number(String(id).slice(1))) : null) },
  DB: { executeTransaction: async callback => callback() },
  Item: class { constructor(type) { this.type = type; } setTags() {} async save() { this.key = 'NEW' + (saved.length + 1); saved.push(this); } },
} });
loadPlugin(context, process.argv[1]);
const E = context.ScholiumEndpoints;
const outcome = p => p.then(r => ({ ok: r.ok, key: r.attachmentKey || null, created: r.createdKeys || null }), e => ({ error: e.message }));
const ann = { type: 'highlight', text: 'x', comment: '', color: '#ffd400', position: { pageIndex: 0, rects: [[1, 2, 3, 4]] } };
(async () => {
  const out = {
    listMine: await outcome(E.list({ attachmentKey: 'ATT1' })),
    listGroup: await outcome(E.list({ attachmentKey: 'ATT1', groupID: 777 })),
    listLibrary: await outcome(E.list({ attachmentKey: 'ATT1', libraryID: 2 })),
    unknownGroup: await outcome(E.list({ attachmentKey: 'ATT1', groupID: 555 })),
    unknownLibrary: await outcome(E.list({ attachmentKey: 'ATT1', libraryID: 9 })),
    applyGroup: await outcome(E.apply({ attachmentKey: 'ATT1', itemKey: 'ITEM1', groupID: 777, tag: 'zotero-scholium', annotations: [ann] })),
    readOnly: await outcome(E.apply({ attachmentKey: 'ATT1', itemKey: 'ITEM1', groupID: 888, tag: 'zotero-scholium', annotations: [ann] })),
    filesLocked: await outcome(E.apply({ attachmentKey: 'ATT1', itemKey: 'ITEM1', libraryID: 4, tag: 'zotero-scholium', annotations: [ann] })),
    libraries: saved.map(s => s.libraryID),
  };
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e); process.exitCode = 1; });
"""


def test_the_endpoints_read_and_write_in_the_library_a_request_names():
    bootstrap = Path(__file__).resolve().parents[1] / "plugin/scholium/bootstrap.js"
    out = json.loads(subprocess.run([NODE, "-e", ENDPOINTS, str(bootstrap)], capture_output=True, text=True, check=True, timeout=15).stdout)
    assert out["listMine"] == out["listGroup"] == out["listLibrary"] == {"ok": True, "key": "ATT1", "created": None}
    assert out["unknownGroup"] == {"error": "group 555 not found in this Zotero; check group_id in the configuration"}
    assert out["unknownLibrary"] == {"error": "library 9 not found in this Zotero; check library_id in the configuration"}
    assert out["applyGroup"] == {"ok": True, "key": None, "created": ["NEW1"]} and out["libraries"] == [2], "written in the group's library"
    message = "You cannot edit this group's library, so annotations cannot be written."
    assert out["readOnly"] == {"error": message} and out["filesLocked"] == {"error": message}
