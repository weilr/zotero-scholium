"""What the plugin gives an agent's process: the port of its Zotero's local server, for the skill's script
(SCHOLIUM_ZOTERO_PORT), to Claude Code, Codex and the setup check's commands; and Claude Code's --add-dir for the skill's
folder, only when that folder is there, in CLAUDE_CONFIG_DIR when it is set."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const port = h => ({ claude: h.log.calls.map(c => c.opts.environment.SCHOLIUM_ZOTERO_PORT),
                       codex: h.log.codexCalls.map(o => o.environment.SCHOLIUM_ZOTERO_PORT),
                       python: h.log.pyCalls.map(o => o.environment.SCHOLIUM_ZOTERO_PORT),
                       uv: h.log.uvCalls.map(o => o.environment.SCHOLIUM_ZOTERO_PORT) });
  const PY = '/w/bin/python.exe', UV = '/w/bin/uv.exe';
  for (const [name, value] of [['changed', 23129], ['unset', undefined], ['text', 'abc'], ['outside', 70000]]) {
    const prefs = value === undefined ? {} : { 'httpServer.port': value };
    const h = harness({ prefs, env: { PATH: '/w/bin' }, present: [PY, UV], python: { [PY]: '3.12.1\n1.24.10\n' }, uv: { [UV]: 'uv 0.13.7\n' } });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(300);
    await h.zotero.Scholium.setupCheck(() => {});
    h.store.set('extensions.scholium.agent', 'codex');
    await h.runner.annotate([h.item2]); await settle(600);
    facts[name] = port(h);
    h.runner.stop();
  }
  // --add-dir: the skill's folder when it is there, in CLAUDE_CONFIG_DIR when that is set
  const addDir = h => { const a = h.log.calls[0].opts.arguments; return a.includes('--add-dir') ? a[a.indexOf('--add-dir') + 1] : null; };
  for (const [name, opts] of [['skillThere', { present: ['/home/u/.claude/skills/zotero-scholium'] }],
                              ['skillMissing', {}],
                              ['configDir', { env: { CLAUDE_CONFIG_DIR: '/cfg/claude' },
                                              present: ['/cfg/claude/skills/zotero-scholium', '/home/u/.claude/skills/zotero-scholium'] }],
                              ['configDirMissing', { env: { CLAUDE_CONFIG_DIR: '/cfg/claude' }, present: ['/home/u/.claude/skills/zotero-scholium'] }]]) {
    const h = harness(opts);
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(300);
    facts[name] = { runs: h.log.calls.length, addDir: addDir(h) };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_every_process_gets_the_port_of_this_zotero(facts):
    c = facts["changed"]
    assert c["claude"] == ["23129"] and c["codex"] and set(c["codex"]) == {"23129"}
    assert c["python"] == ["23129"] and c["uv"] == ["23129"], "the setup check's commands too"
    for name in ("unset", "text", "outside"):
        f = facts[name]
        assert set(f["claude"] + f["codex"] + f["python"] + f["uv"]) == {"23119"}, name


def test_the_skills_folder_is_added_only_when_it_is_there(facts):
    assert facts["skillThere"] == {"runs": 1, "addDir": "/home/u/.claude/skills/zotero-scholium"}
    assert facts["skillMissing"] == {"runs": 1, "addDir": None}
    assert facts["configDir"] == {"runs": 1, "addDir": "/cfg/claude/skills/zotero-scholium"}, "Claude Code's CLAUDE_CONFIG_DIR"
    assert facts["configDirMissing"] == {"runs": 1, "addDir": None}
