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
    assert third["applied"] is True and api.deleted == ["EARLIER", "NEW1"] and "USERS" in api.rows


def test_a_configuration_that_holds_the_earlier_annotations_again_may_replace_them(paper, monkeypatch, capsys):
    api = Api(earlier())
    hl = HL + [{"page": 1, "text": S2, "comment": "另一句。"}]
    code, report = run(paper, monkeypatch, capsys, {"highlights": hl, "cleanup": True}, "--apply", api=api)
    assert "cleanup_other" not in kinds(report) and report["applied"] is True and api.deleted == ["EARLIER"]


def test_reapplying_the_configuration_that_wrote_them_needs_nothing_more(paper, monkeypatch, capsys):
    api = Api()   # a paper without the tool's annotations, as after the plugin's Annotate again deleted them
    code, first = run(paper, monkeypatch, capsys, {"highlights": HL}, "--apply", api=api)
    assert first["applied"] is True
    code, second = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert second["applied"] is True and "cleanup_other" not in kinds(second) and api.deleted == ["NEW1"]
    # and once more after that cleanup write: its own annotations are the ones it replaces
    code, third = run(paper, monkeypatch, capsys, {"highlights": HL, "cleanup": True}, "--apply", api=api)
    assert third["applied"] is True and api.deleted == ["NEW1", "NEW2"]


def test_another_configurations_write_is_not_this_ones(paper, monkeypatch, capsys):
    api = Api()
    run(paper, monkeypatch, capsys, {"highlights": HL}, "--apply", api=api)                                   # NEW1 from config.json
    run(paper, monkeypatch, capsys, {"highlights": [{"page": 1, "text": S2, "comment": "另一句。"}]}, "--apply",
        api=api, name="extra.json")                                                                        # NEW2 from extra.json, add-only
    code, report = run(paper, monkeypatch, capsys, {"highlights": FIXED, "cleanup": True}, "--apply", api=api)
    assert report["applied"] is False and kinds(report) == ["cleanup_other"] and api.deleted == []
    assert "NEW2" in report["style_warnings"][0]["reason"] and "NEW1" not in report["style_warnings"][0]["reason"]


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
    assert "cleanup_other" not in kinds(report) and report["applied"] is True and api.deleted == ["NOTE1"]


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
      facts[locale + '-' + name] = { prompt: h.log.stdin[0] || null, erased: h.log.erased.length, confirms: h.log.confirms.length };
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
    assert "cleanup_other" not in zh["prompt"] and "cleanup_other" not in en["prompt"]
    zh, en = plugin_facts["zh-CN-notCleared"], plugin_facts["en-US-notCleared"]
    assert zh["erased"] == 0 and ("\n这篇论文已有 1 条本工具的注释，用户已确认整篇重做：配置里设 cleanup: true；--apply 报告 cleanup_other 时加 "
                                  "--accept cleanup_other（上面不要用 --accept 的唯一例外）。\n") in zh["prompt"]
    assert ("\nThe paper already carries 1 annotations of this tool; the user confirmed a complete redo: set cleanup: true in the "
            "configuration, and when --apply reports cleanup_other, pass --accept cleanup_other (the one exception to the rule on "
            "--accept above).\n") in en["prompt"]
