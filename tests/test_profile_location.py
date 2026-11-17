"""The profile's place: <Zotero data dir>/scholium/profile.md, Scholium's folder; the earlier <data dir>/zotero-scholium/
is read while only it has the profile, and its files move into Scholium's folder when the profile is derived again."""
import json
import os

from zotero_scholium import cli


def data_dir(tmp_path, monkeypatch):
    data = tmp_path / "Zotero"
    data.mkdir()
    (data / "zotero.sqlite").write_bytes(b"")
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(data))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return data


def test_the_profile_is_in_scholiums_folder(tmp_path, monkeypatch):
    data = data_dir(tmp_path, monkeypatch)
    assert cli.profile_dir() == str(data / "scholium")
    assert cli.profile_md_path() == str(data / "scholium" / "profile.md"), "the new place, before there is a profile"


def test_the_earlier_folder_is_read_while_only_it_has_the_profile(tmp_path, monkeypatch, capsys):
    data = data_dir(tmp_path, monkeypatch)
    (data / "zotero-scholium").mkdir()
    (data / "zotero-scholium" / "profile.md").write_text("# old", encoding="utf8")
    assert cli.profile_md_path() == str(data / "zotero-scholium" / "profile.md")
    cli.profile_main(["--path", "--json"])
    got = json.loads(capsys.readouterr().out)
    assert got["profile_md"] == str(data / "zotero-scholium" / "profile.md") and got["exists"] is True
    assert got["old_profile_md"] == str(data / "zotero-scholium" / "profile.md")
    (data / "scholium").mkdir()
    (data / "scholium" / "profile.md").write_text("# new", encoding="utf8")
    assert cli.profile_md_path() == str(data / "scholium" / "profile.md"), "once Scholium's folder has one, that one"


def test_deriving_the_profile_moves_the_earlier_one_in(tmp_path, monkeypatch, capsys):
    data = data_dir(tmp_path, monkeypatch)
    old = data / "zotero-scholium"
    old.mkdir()
    rules = "# Annotation profile\n\n## User's rules (always win)\n\n- comments are translations\n"
    (old / "profile.md").write_text(rules, encoding="utf8")
    (old / "profile.json").write_text("{}", encoding="utf8")
    prof = {"annotations_analysed": 3, "language": "zh", "types": {}, "comment_rate": 0, "comment_len_median": 0,
            "comment_style": "", "levels": [], "child_notes": 0, "layout": {}}
    monkeypatch.setattr(cli, "profile_from_library", lambda exclude="": prof)
    monkeypatch.setattr(cli, "profile_markdown", lambda p: "# Annotation profile\n\n## User's rules (always win)\n\n- (none yet; add rules here)\n")
    cli.profile_main(["--from-library"])
    report = json.loads(capsys.readouterr().out)
    assert report["migrated_from"] == str(old / "profile.md")
    assert "comments are translations" in (data / "scholium" / "profile.md").read_text(encoding="utf8"), "the user's rules stay"
    assert not old.exists(), "the earlier folder goes once it is empty"
    assert json.loads((data / "scholium" / "profile.json").read_text(encoding="utf8"))["annotations_analysed"] == 3


def test_a_profile_in_both_places_leaves_the_earlier_one(tmp_path, monkeypatch):
    data = data_dir(tmp_path, monkeypatch)
    for folder, text in (("zotero-scholium", "# old"), ("scholium", "# new")):
        (data / folder).mkdir()
        (data / folder / "profile.md").write_text(text, encoding="utf8")
    assert cli.move_old_profile() == []
    assert (data / "zotero-scholium" / "profile.md").read_text(encoding="utf8") == "# old"
    assert (data / "scholium" / "profile.md").read_text(encoding="utf8") == "# new"


def test_the_skills_copy_of_the_script_is_the_same():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "src", "zotero_scholium", "cli.py"), encoding="utf8") as a, \
         open(os.path.join(root, "skills", "zotero-scholium", "scripts", "scholium.py"), encoding="utf8") as b:
        assert a.read() == b.read()
