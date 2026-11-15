"""Zotero's colour names and the user's tags on the tool's annotations: the configuration, the built annotations and the
three write channels (the local API's item JSON, the generated JavaScript and the plugin endpoint)."""
import json

import pymupdf

from zotero_scholium import cli


def paper(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "We propose a simple method that works well on every benchmark we tried.", fontsize=11)
    page.insert_text((72, 300), "The second paragraph explains the training procedure in detail here.", fontsize=11)
    pdf = tmp_path / "p.pdf"
    doc.save(pdf)
    return str(pdf)


def config(tmp_path, **extra):
    raw = dict({"pdf": paper(tmp_path), "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(tmp_path / "out")}, **extra)
    return cli.normalize_config(dict(cli.DEFAULTS, **raw))


def test_colour_names_resolve_and_unknown_ones_name_the_nearest():
    assert cli.zotero_color("Green") == "#5fb236" and cli.zotero_color("#AABBCC") == "#aabbcc"
    assert set(cli.ZOTERO_COLORS) == {"red", "orange", "yellow", "green", "blue", "purple", "magenta", "gray"}
    problems = cli.config_problems({"highlights": [{"page": 1, "text": "simple method", "color": "gren"}]})
    assert any("color" in p and "green" in p for p in problems), problems
    problems = cli.config_problems({"levels": {"method": "green"}, "core_color": "Red",
                                    "highlights": [{"page": 1, "text": "simple method", "level": "method"}],
                                    "summaries": [{"page": 1, "anchor": "second paragraph", "text": "x", "color": "purple"}]})
    assert not [p for p in problems if "color" in p or "colour" in p], problems


def test_tags_are_cleaned_and_the_tools_own_tag_is_refused():
    assert cli.clean_tags(["方法", " 方法 ", "结果"]) == ["方法", "结果"]
    assert cli.clean_tags(["", "x"]) is None and cli.clean_tags("x") is None
    for raw in ({"tags": ["zotero-scholium"]}, {"highlights": [{"page": 1, "text": "a", "tags": ["zotero-marginalia"]}]},
                {"summaries": [{"page": 1, "anchor": "a", "text": "b", "tags": [""]}]}):
        problems = cli.config_problems(raw)
        assert any("tags" in p for p in problems), (raw, problems)


def test_built_annotations_carry_the_colour_value_and_the_tags(tmp_path):
    cfg = config(tmp_path, tags=["精读"], levels={"method": "green"},
                 highlights=[{"page": 1, "text": "simple method", "level": "method", "tags": ["方法", "精读"]},
                             {"page": 1, "text": "every benchmark", "color": "Blue"}],
                 summaries=[{"page": 1, "anchor": "second paragraph", "text": "训练细节", "color": "purple", "tags": ["训练"]}])
    anns, missed = cli.build(cfg)
    assert not missed
    hl = [a for a in anns if a["type"] == "highlight"]
    assert [(a["color"], a["tags"]) for a in hl] == [("#5fb236", ["精读", "方法"]), ("#2ea8e5", ["精读"])]
    margin = [a for a in anns if a["type"] == "text"][0]
    assert margin["color"] == "#a28ae5" and margin["tags"] == ["精读", "训练"]
    assert cfg["core_color"] == "#ff6666"


def test_without_tags_nothing_changes(tmp_path):
    anns, _ = cli.build(config(tmp_path, highlights=[{"page": 1, "text": "simple method", "core": True}]))
    assert anns[0]["color"] == "#ff6666" and "tags" not in anns[0]   # annotations.json as before


def test_the_local_apis_items_and_the_javascript_carry_the_tags(tmp_path):
    anns = [{"type": "highlight", "color": "#5fb236", "text": "simple method", "comment": "简单的方法", "pageLabel": "1",
             "sortIndex": "00000|000000|00100", "position": {"pageIndex": 0, "rects": [[72, 690, 150, 702]]}, "tags": ["方法"]}]
    items = cli.api_items({"attachment_key": "ATT"}, anns)
    assert items[0]["tags"] == [{"tag": "zotero-scholium"}, {"tag": "方法"}]
    js = cli.render_js(dict(cli.DEFAULTS, attachment_key="ATT", item_key="ITEM", out_dir=str(tmp_path)), anns)
    assert '"tags": ["方法"]' in js
    assert "[{tag: TAG}].concat((a.tags || []).map(t => ({tag: t})))" in js
