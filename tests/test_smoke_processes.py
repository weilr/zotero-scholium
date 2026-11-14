"""Parse process listings without querying or ending any real process."""
import subprocess

import pytest

from test_smoke_tools import smoke


@pytest.mark.parametrize("platform, listing", [
    ("posix", '  12 /opt/zotero/zotero -profile "/tmp/test profile"\n'
              '  34   /opt/Zotero/zotero -profile /tmp/other\n'),
    ("posix", '12\t/opt/zotero/zotero -profile "/tmp/test profile"\n'
              '34\t/opt/Zotero/zotero -profile /tmp/other\n'),
    ("nt", '12\t/opt/zotero/zotero -profile "/tmp/test profile"\n'
           '34\t/opt/Zotero/zotero -profile /tmp/other\n'),
])
def test_process_list_preserves_commands_and_selects_only_our_profile(monkeypatch, platform, listing):
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        text = " 12 zotero\n 34 zotero-bin\n" if "ucomm=" in args else listing
        return subprocess.CompletedProcess(args, 0, stdout=text)

    with monkeypatch.context() as patch:
        patch.setattr(smoke.os, "name", platform)
        patch.setattr(smoke.subprocess, "run", run)
        rows = smoke.zotero_processes()
        pids = smoke.end_ours("/tmp/test profile")

    assert rows == [(12, '/opt/zotero/zotero -profile "/tmp/test profile"'),
                    (34, '/opt/Zotero/zotero -profile /tmp/other')]
    assert pids == [12]
    assert commands[-1] == (["kill", "-9", "12"] if platform == "posix"
                            else ["taskkill", "/PID", "12", "/T", "/F"])


def test_posix_process_list_ignores_empty_or_malformed_rows(monkeypatch):
    listing = '\n   \n42\nnot-a-pid /opt/zotero/zotero\n55 /usr/bin/python unrelated.py\n'
    with monkeypatch.context() as patch:
        patch.setattr(smoke.os, "name", "posix")
        patch.setattr(smoke.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=listing))
        rows = smoke.zotero_processes()
    assert rows == []


def test_posix_cleanup_uses_executable_names_not_words_in_arguments(monkeypatch):
    names = "12 zotero\n34 python\n56 zotero helper\n78 zotero-bin\n"
    args_list = ('12 /opt/zotero/zotero -profile /tmp/test\n'
                 '34 python /tmp/zotero-test.py -profile /tmp/test\n'
                 '56 /tmp/zotero-helper -profile /tmp/test\n'
                 '78 /opt/zotero/zotero-bin -profile /tmp/other\n')
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=names if "ucomm=" in args else args_list)

    with monkeypatch.context() as patch:
        patch.setattr(smoke.os, "name", "posix")
        patch.setattr(smoke.subprocess, "run", run)
        pids = smoke.end_ours("/tmp/test")
    assert pids == [12]
    assert [c for c in commands if c[0] == "kill"] == [["kill", "-9", "12"]]
    assert [c[c.index("-p") + 1] for c in commands if "-p" in c] == ["12,78"]


@pytest.mark.parametrize("command, expected", [
    ('zotero -profile /tmp/TestProfile', True),
    ('zotero -profile "/tmp/TestProfile" -other', True),
    ("zotero -profile '/tmp/TestProfile'", True),
    ('zotero -profile /tmp/testprofile', False),
    ('zotero -profile /other/tmp/TestProfile', False),
    ('zotero -profile /tmp/TestProfile-old', False),
    ('zotero -profile /tmp/TestProfile/subdir', False),
    ('zotero -profile /tmp/TestProfile extra -ZoteroDebugText', False),
    ('zotero -profile /tmp/TestProfile -ZoteroDebugText', True),
    ('zotero --file /tmp/TestProfile', False),
])
def test_posix_profile_match_is_exact_and_case_sensitive(command, expected):
    assert smoke.profile_matches(command, "/tmp/TestProfile") is expected


def test_posix_profile_preserves_spaces_inside_the_path():
    assert smoke.profile_matches('zotero -profile /tmp/test  profile -ZoteroDebugText', '/tmp/test  profile')
    assert not smoke.profile_matches('zotero -profile /tmp/test profile -ZoteroDebugText', '/tmp/test  profile')


def test_posix_without_zotero_does_not_query_args_or_end_processes(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='34 python\n56 zotero helper\n')

    with monkeypatch.context() as patch:
        patch.setattr(smoke.os, "name", "posix")
        patch.setattr(smoke.subprocess, "run", run)
        assert smoke.end_ours('/tmp/test') == []
    assert calls == [["ps", "-A", "-ww", "-o", "pid=", "-o", "ucomm="]]
