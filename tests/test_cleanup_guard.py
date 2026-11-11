"""A cleanup deletes only the tool's annotations its configuration accounts for: those the configuration file's last
write created (out_dir/applied_keys.json names the file) and those the new set holds again (the same page and kind, the
same text, or comment for a margin note). Any other annotation of the tool, written by another configuration, holds the
write back as `cleanup_other` until --accept cleanup_other, for a complete redo the user asked for. Every run here uses
the in-memory local API; nothing reaches a socket."""
import json

import pymupdf
import pytest

from zotero_scholium import cli
from test_run_safeguards import Api, ann_row

S1 = "The method improves the result on every benchmark."
S2 = "Another sentence written in an earlier session."


@pytest.fixture
def paper(tmp_path):
    pdf = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 120), S1)
        page.insert_text((72, 400), S2)
        doc.save(pdf)
    return tmp_path, str(pdf)


def run(paper, monkeypatch, capsys, config, *args, api, name="config.json"):
    tmp, pdf = paper
    path = tmp / name
    data = dict({"pdf": pdf, "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(tmp / "out"), "preview_pages": []}, **config)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
    monkeypatch.setattr(cli, "pick_backend", lambda *a: ("api", api, "test API"))
    code = 0
    try:
        cli.main(["--config", str(path), *args])
    except SystemExit as e:
        code = e.code
    return code, json.loads(capsys.readouterr().out)


def earlier():
    row = ann_row("EARLIER", tags=["zotero-scholium"], text=S2, comment="上一次会话写的。")
    row["data"]["annotationPosition"] = json.dumps({"pageIndex": 0, "rects": [[72, 380, 400, 400]]})
    user = ann_row("USERS", tags=[], text="x", comment="mine")
    user["data"]["annotationPosition"] = json.dumps({"pageIndex": 0, "rects": [[10, 10, 20, 20]]})
    return [row, user]


def kinds(report):
    return [w["kind"] for w in report.get("style_warnings", [])]


HL = [{"page": 1, "text": S1, "comment": "该方法在 5 个基准上都提升了结果。", "core": True}]
FIXED = [dict(HL[0], comment="该方法在每个基准上都提升了结果。")]


def test_reapplying_an_add_only_write_with_cleanup_keeps_the_earlier_annotations(paper, monkeypatch, capsys):
    api = Api(earlier())
    code, first = run(paper, monkeypatch, capsys, {"highlights": HL}, "--apply", api=api)
    assert first["applied"] is True and first["translation_warnings"], "an add-only write with an advisory warning"
    record = json.loads((paper[0] / "out" / "applied_keys.json").read_text(encoding="utf8"))
    assert record["createdKeys"] == ["NEW1"] and record["config"] == str(paper[0] / "config.json")
    # the skill's step 3: the translation corrected, applied again with cleanup
    code, second = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert code == 2 and second["applied"] is False and api.deleted == []
    assert kinds(second) == ["cleanup_other"] and "cleanup_other" in second["apply_error"]
    reason = second["style_warnings"][0]["reason"]
    assert "1 of the tool's annotations" in reason and "EARLIER" in reason and "--accept cleanup_other" in reason
    # a complete redo the user asked for lets it through
    code, third = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", "--accept", "cleanup_other", api=api)
    assert third["applied"] is True and api.deleted == ["EARLIER"] and "USERS" in api.rows
    assert [u["key"] for u in api.updated] == ["NEW1"], "the corrected one is changed in place"


def test_a_configuration_that_holds_the_earlier_annotations_again_may_replace_them(paper, monkeypatch, capsys):
    api = Api(earlier())
    hl = HL + [{"page": 1, "text": S2, "comment": "另一句。"}]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "cleanup": True}, "--apply", api=api)
    assert "cleanup_other" not in kinds(report) and report["applied"] is True and api.deleted == []
    assert [u["key"] for u in api.updated] == ["EARLIER"], "the one it holds again is changed in place"


def test_reapplying_the_configuration_that_wrote_them_needs_nothing_more(paper, monkeypatch, capsys):
    api = Api()   # a paper without the tool's annotations, as after the plugin's Annotate again deleted them
    code, first = run(paper, monkeypatch, capsys, {"highlights": HL}, "--apply", api=api)
    assert first["applied"] is True
    code, second = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert second["applied"] is True and "cleanup_other" not in kinds(second) and api.deleted == []
    # and once more after that cleanup write: its own annotations are the ones it replaces
    code, third = run(paper, monkeypatch, capsys, {"highlights": HL, "cleanup": True}, "--apply", api=api)
    assert third["applied"] is True and api.deleted == [] and [u["key"] for u in api.updated] == ["NEW1", "NEW1"]


def test_another_configurations_write_is_not_this_ones(paper, monkeypatch, capsys):
    api = Api()
    run(paper, monkeypatch, capsys, {"highlights": HL}, "--apply", api=api)                                   # NEW1 from config.json
    run(paper, monkeypatch, capsys, {"highlights": [{"page": 1, "text": S2, "comment": "另一句。"}]}, "--apply",
        api=api, name="extra.json")                                                                        # NEW2 from extra.json, add-only
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and kinds(report) == ["cleanup_other"] and api.deleted == []
    assert "NEW2" in report["style_warnings"][0]["reason"] and "NEW1" not in report["style_warnings"][0]["reason"]


def test_in_the_plugins_run_cleanup_other_waits_for_the_users_confirmation(paper, monkeypatch, capsys):
    api = Api(earlier())
    run(paper, monkeypatch, capsys, {"highlights": HL}, "--apply", api=api)
    held = paper[0] / "held_back.json"
    monkeypatch.setenv("SCHOLIUM_PLUGIN_RUN", "1")
    monkeypatch.setenv("SCHOLIUM_HELD_BACK", str(held))
    redo = {"highlights": FIXED, "cleanup": True}
    code, report = run(paper, monkeypatch, capsys, redo, api=api)   # a dry run notes them too
    assert json.loads(held.read_text(encoding="utf8")) == {"cleanup_other": ["EARLIER"]}
    assert report["style_warnings"][0]["reason"].endswith(
        "; or stop and ask the user; pass --accept cleanup_other only after a later message of theirs confirms deleting them, or "
        "for a complete redo the user confirmed")
    code, report = run(paper, monkeypatch, capsys, redo, "--apply", "--accept", "cleanup_other", api=api)
    assert report["applied"] is False and api.deleted == [] and (
        "cleanup_other is let through only once the user has confirmed it (EARLIER): stop and ask the user; a later message of "
        "theirs that confirms deleting those annotations lets --accept cleanup_other through") in report["apply_error"]
    monkeypatch.setenv("SCHOLIUM_CONFIRMED", "cleanup_other:EARLIER")
    code, report = run(paper, monkeypatch, capsys, redo, "--apply", "--accept", "cleanup_other", api=api)
    assert report["applied"] is True and api.deleted == ["EARLIER"] and "USERS" in api.rows


def test_a_dry_run_reports_it_too_and_without_cleanup_nothing_is_checked(paper, monkeypatch, capsys):
    api = Api(earlier())
    code, report = run(paper, monkeypatch, capsys, {"highlights": HL, "cleanup": True}, api=api)
    assert kinds(report) == ["cleanup_other"] and api.deleted == []
    code, report = run(paper, monkeypatch, capsys, {"highlights": HL}, api=api)
    assert "cleanup_other" not in kinds(report)


def test_a_margin_note_written_over_an_earlier_one_replaces_it(paper, monkeypatch, capsys):
    old = ann_row("NOTE1", tags=["zotero-scholium"], kind="text", text="", comment="旧的页边批注。")
    old["data"]["annotationPosition"] = json.dumps({"pageIndex": 0, "rects": [[0, 0, 612, 792]]})
    api = Api([old])
    summaries = [{"page": 1, "anchor": S1, "text": "改过的页边批注。"}]
    code, report = run(paper, monkeypatch, capsys, {"summaries": summaries, "cleanup": True}, "--apply", api=api)
    assert "cleanup_other" not in kinds(report) and report["applied"] is True and api.deleted == []
    assert [u["key"] for u in api.updated] == ["NOTE1"] and api.n == 0, "the margin note over it is that one, changed"


# the plugin's Annotate again: it deletes the tool's annotations before the agent starts, so that the agent's first write
# has none to clean up; when that deletion failed, the prompt names the one --accept the redo may need
PLUGIN = r"""
(async () => {
  const facts = {};
  for (const locale of ['zh-CN', 'en-US']) {
    for (const [name, eraseFails] of [['cleared', false], ['notCleared', true]]) {
      const h = harness({ existing: [['zotero-scholium']], eraseFails, locale });
      h.runner.start('x');
      await h.runner.annotate([h.item1]); await settle(600);
      facts[locale + '-' + name] = { prompt: h.log.stdin[0] || null, erased: h.log.erased.length, confirms: h.log.confirms.length,
                                     followUp: h.runner.followUpPrompt({ say: 'delete that highlight', own: 1 }) };
      h.runner.stop();
    }
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def plugin_facts(tmp_path_factory):
    from plugin_harness import NODE, run_scenarios
    if NODE is None:
        pytest.skip("Node.js is required for plugin tests")
    return run_scenarios(PLUGIN, tmp_path_factory)


def test_annotate_again_deletes_first_and_names_the_exception_only_when_that_failed(plugin_facts):
    zh, en = plugin_facts["zh-CN-cleared"], plugin_facts["en-US-cleared"]
    assert zh["erased"] == 1 and zh["confirms"] == 1 and "这篇论文目前没有本工具的注释。" in zh["prompt"]
    assert "--accept cleanup_other（" not in zh["prompt"] and "pass --accept cleanup_other (" not in en["prompt"]
    zh, en = plugin_facts["zh-CN-notCleared"], plugin_facts["en-US-notCleared"]
    assert zh["erased"] == 0 and ("\n这篇论文已有 1 条本工具的注释，用户已确认整篇重做：配置里设 cleanup: true；--apply 报告 cleanup_other 时加 "
                                  "--accept cleanup_other（上面不要用 --accept 的唯一例外）。\n") in zh["prompt"]
    assert ("\nThe paper already carries 1 annotations of this tool; the user confirmed a complete redo: set cleanup: true in the "
            "configuration, and when --apply reports cleanup_other, pass --accept cleanup_other (the one exception to the rule on "
            "--accept above).\n") in en["prompt"]


# the user's own changes in Zotero (user_edit) and annotations a cleanup would delete (cleanup_other) are never the agent's
# to override: kept as they are, or the run stops and asks the user in their terms, who confirms in a message of their own
ANNOTATE_ZH = ("--apply 报告 user_edit 或 cleanup_other 时，在用户确认之前不要尝试 --accept：在配置里保留这些批注和笔记的现状（报告写了怎么做）；"
               "做不到时不要写入，最后的回复不写下面那一行，改为用用户的话说明写入会删掉或覆盖哪些批注或笔记（页码、开头几个字、用户改了什么），"
               "并告诉用户回复“确认删除”（或“确认覆盖”）之类的话即可继续；不要提参数、脚本、命令行、权限或“自动模式”。")
ANNOTATE_EN = ("When --apply reports user_edit or cleanup_other, do not try --accept for them before the user confirms: keep those annotations and "
               "notes as they are in the configuration (the report says how); where you cannot, write nothing and, in place of the closing line "
               "below, your final reply says in the user's terms what writing would delete or overwrite (page, first words, what they changed) and "
               "that they can reply, for example, “Yes, delete it” in their language to go ahead; never mention flags, scripts, shells, permissions "
               "or “auto mode”.")
FOLLOW_ZH = ("user_edit 和 cleanup_other 不适用上面的例外，在用户确认之前不要尝试 --accept：--apply 报告它们时，保留这些批注和笔记的现状仍能完成"
             "用户的要求，就在配置里保留（报告写了怎么做）；否则停下，不要写入，在回复里用用户的话说明写入会删掉或覆盖哪些批注或笔记"
             "（页码、开头几个字、用户改了什么），并告诉用户回复“确认删除”（或“确认覆盖”）之类的话即可继续；不要提参数、脚本、命令行、"
             "权限或“自动模式”。只有用户之后的消息明确确认，才对你说明的那些批注或笔记加 --accept user_edit 或 --accept cleanup_other"
             "（在那之前脚本不放行）。")
FOLLOW_EN = ("That exception does not cover user_edit and cleanup_other: do not try --accept for them before the user confirms. When --apply "
             "reports them, keep those annotations and notes as they are in the configuration (the report says how) where that still does what "
             "the user asked; otherwise stop without writing, and in your reply say in the user's terms what writing would delete or overwrite "
             "(page, first words, what they changed) and that they can reply, for example, “Yes, delete it” in their language to go ahead; never "
             "mention flags, scripts, shells, permissions or “auto mode”. Only a later message of theirs that confirms it allows --accept "
             "user_edit or --accept cleanup_other, for the annotations and notes you named (the script refuses them before then).")


def test_the_agent_never_overrides_the_users_own_changes_without_their_word(plugin_facts):
    for name in ("cleared", "notCleared"):
        zh, en = plugin_facts["zh-CN-" + name], plugin_facts["en-US-" + name]
        # the annotation task: after the rule on --accept, before the redo's one exception
        assert zh["prompt"].count("\n不要用 --accept、--allow-warnings 或 --allow-missed：把报告里的问题改掉。\n" + ANNOTATE_ZH + "\n") == 1, name
        assert en["prompt"].count("\nDo not pass --accept, --allow-warnings or --allow-missed: correct the findings instead.\n"
                                  + ANNOTATE_EN + "\n") == 1, name
        # a follow-up in the annotation's session: the user's words allow the other kinds, never these two
        assert zh["followUp"].count("\n除非用户的话要求这个例外，否则不要用 --accept、--allow-warnings 或 --allow-missed：把报告里的问题改掉。\n"
                                    + FOLLOW_ZH + "\n") == 1, name
        assert en["followUp"].count("\nDo not pass --accept, --allow-warnings or --allow-missed unless the user's message asks for that "
                                    "exception: correct the findings instead.\n" + FOLLOW_EN + "\n") == 1, name
    # the redo's exception still follows them, unchanged
    zh, en = plugin_facts["zh-CN-notCleared"]["prompt"], plugin_facts["en-US-notCleared"]["prompt"]
    assert zh.index(ANNOTATE_ZH) < zh.index("--accept cleanup_other（上面不要用 --accept 的唯一例外）。")
    assert en.index(ANNOTATE_EN) < en.index("pass --accept cleanup_other (the one exception to the rule on --accept above).")
