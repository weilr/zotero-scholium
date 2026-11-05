"""Scholium Bridge 0.1.9 becomes Scholium. Scholium, once installed, uninstalls Scholium Bridge before it registers
anything, takes over its preferences and its token, and answers at its endpoint paths too; the tool reaches either
plugin, and still takes `--backend bridge`."""
import json

import pytest

from plugin_harness import NODE, run_scenarios
from zotero_scholium import cli

needs_node = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

OLD_ID = "scholium-bridge@zotero-scholium"
ALL_PATHS = sorted(["/scholium/ping", "/scholium/list", "/scholium/apply",
                    "/scholium-bridge/ping", "/scholium-bridge/list", "/scholium-bridge/apply"])

SCENARIOS = r"""
const OLD_ID = 'scholium-bridge@zotero-scholium';
// Scholium Bridge 0.1.9 as AddonManager gives it (`how`: 'installed', 'fails', 'hangs', 'uninstallFails' or
// 'uninstallHangs'): its uninstall runs its shutdown, which on Zotero 7–9 drops every reader listener of its two types
// and removes its own endpoints
const manager = (s, how) => ({
  getAddonByID: async id => {
    s.events.push('look ' + id);
    if (how === 'fails') throw Error('AddonManager is not ready');
    if (how === 'hangs') await new Promise(() => {});
    if (id !== OLD_ID || !s.installed) return null;
    return { id, uninstall: async () => {
      s.events.push('uninstall');
      if (how === 'uninstallFails') throw Error('the add-on is locked');
      if (how === 'uninstallHangs') await new Promise(() => {});
      await settle(5);
      s.h.log.listeners = s.h.log.listeners.filter(l => !['renderToolbar', 'renderTextSelectionPopup'].includes(l.type));
      for (const p of Object.keys(s.old)) if (s.endpoints[p] === s.old[p]) delete s.endpoints[p];
      s.installed = false;
      s.events.push('uninstalled');
    } };
  },
});
// a Zotero that records, in order, the add-on asked for, each preference read, the section, each reader listener and
// each endpoint registered; Scholium Bridge's endpoints are there while it is installed
const begin = ({ how = 'installed', installed = true, prefs = {}, logs = {}, noModule = false } = {}) => {
  const s = { events: [], installed, endpoints: {}, debug: [],
              old: { '/scholium-bridge/ping': class {}, '/scholium-bridge/list': class {}, '/scholium-bridge/apply': class {} } };
  if (installed) Object.assign(s.endpoints, s.old);
  const h = s.h = harness({ prefs, logs, addonManager: noModule ? null : manager(s, how) });
  const z = h.zotero;
  Object.assign(z, { initializationPromise: Promise.resolve(), debug: m => { s.debug.push(String(m)); },
                     Server: { Endpoints: new Proxy(s.endpoints, { set(t, k, v) { s.events.push('endpoint ' + k); t[k] = v; return true; } }) } });
  z.Utilities.randomString = n => 'N'.repeat(n);
  const wrap = (obj, name, label) => { const f = obj[name]; obj[name] = function (...a) { s.events.push(label(...a)); return f.apply(this, a); }; };
  wrap(z.ItemPaneManager, 'registerSection', () => 'section');
  wrap(z.Reader, 'registerEventListener', type => 'listener ' + type);
  wrap(z.Prefs, 'get', name => 'read ' + name);
  s.start = (reason = 1) => h.startup({ id: 'scholium@zotero-scholium', version: '0.2.0', rootURI: 'jar:file:///x.xpi!/' }, reason);
  s.order = () => {
    const first = re => s.events.findIndex(e => re.test(e));
    return { uninstalled: s.events.indexOf('uninstalled'), read: first(/^read /), section: first(/^section$/),
             listener: first(/^listener /), endpoint: first(/^endpoint /) };
  };
  s.registered = () => {
    const mine = h.endpoints.endpoints || {};
    return { sections: h.log.sections.length, listeners: h.log.listeners.map(l => l.type).sort(),
             endpoints: Object.keys(s.endpoints).sort(), own: Object.keys(s.endpoints).filter(p => s.endpoints[p] === mine[p]).length };
  };
  s.prefs = () => Object.fromEntries([...h.store].filter(([k]) => k.startsWith('extensions.')));
  s.files = () => [h.log.writes['/data/scholium.token'], h.log.writes['/data/scholium-bridge.token']];
  s.said = () => s.debug.filter(m => /Scholium Bridge/.test(m));
  return s;
};
(async () => {
  const facts = {};

  // Scholium installed while Scholium Bridge 0.1.9 runs: the old add-on goes first, then its settings and token are taken
  {
    const s = begin({ prefs: { 'extensions.scholium-bridge.showAnnotations': true, 'extensions.scholium-bridge.agent': 'codex',
                               'extensions.scholium-bridge.followUpMode': 'steer', 'extensions.scholium.followUpMode': 'queue',
                               'extensions.scholium-bridge.width': 3, 'extensions.zotero.dataDir': '/data' },
                      logs: { '/data/scholium-bridge.token': 'OLD-TOKEN-0123456789' } });
    await s.start(5);
    facts.takeover = { head: s.events.slice(0, 3), order: s.order(), registered: s.registered(), prefs: s.prefs(),
                       shown: s.h.toggle.shown, agent: s.h.runner.agent(), token: s.h.endpoints.token, files: s.files(), said: s.said() };
    // the next start finds nothing to take over and keeps the token
    const prefs = JSON.stringify(s.prefs());
    const stamps = JSON.stringify([s.h.log.mtimes['/data/scholium.token'], s.h.log.mtimes['/data/scholium-bridge.token']]);
    s.h.shutdown({}, 2);
    facts.takeover.left = Object.keys(s.endpoints);
    s.events.length = 0;
    await s.start(1);
    facts.again = { asked: s.events.filter(e => /^(look|uninstall)/.test(e)), samePrefs: JSON.stringify(s.prefs()) === prefs,
                    token: s.h.endpoints.token,
                    unwritten: JSON.stringify([s.h.log.mtimes['/data/scholium.token'], s.h.log.mtimes['/data/scholium-bridge.token']]) === stamps };
    s.h.shutdown({}, 2);
  }

  // no earlier plugin: a new token, in both files
  {
    const s = begin({ installed: false });
    await s.start(5);
    facts.fresh = { asked: s.events.filter(e => /^(look|uninstall)/.test(e)), token: s.h.endpoints.token, files: s.files(),
                    registered: s.registered() };
    s.h.shutdown({}, 2);
  }

  // both files: this plugin's token stays, and goes into the other file
  {
    const s = begin({ installed: false, logs: { '/data/scholium.token': 'NEW-TOKEN-0123456789', '/data/scholium-bridge.token': 'OLD-TOKEN-0123456789' } });
    await s.start(1);
    facts.both = { token: s.h.endpoints.token, files: s.files() };
    s.h.shutdown({}, 2);
  }

  // AddonManager fails, refuses the uninstall, or cannot be loaded: the start goes on
  for (const how of ['fails', 'uninstallFails', 'noModule']) {
    const s = begin(how === 'noModule' ? { noModule: true } : { how });
    await s.start(5);
    facts[how] = { registered: s.registered(), said: s.said(), timers: s.h.live() };
    s.h.shutdown({}, 2);
  }

  // AddonManager does not answer: the start waits for it 10 seconds, then goes on
  for (const how of ['hangs', 'uninstallHangs']) {
    const s = begin({ how });
    let done = false;
    const started = s.start(5).then(() => { done = true; });
    await settle(50);
    const waiting = { done, sections: s.h.log.sections.length, own: s.registered().own, timers: s.h.live() };
    s.h.fire();
    await started;
    facts[how] = { waiting, registered: s.registered(), said: s.said() };
    s.h.shutdown({}, 2);
  }

  // the endpoints at both paths, one handler for each pair
  {
    const s = begin({ installed: false });
    await s.start(1);
    const e = s.endpoints;
    const ping = e['/scholium-bridge/ping'] ? await new e['/scholium-bridge/ping']().init({}) : [404, 'application/json', '{}'];
    const list = e['/scholium-bridge/list'] ? await new e['/scholium-bridge/list']().init({ headers: {}, data: {} }) : [404];
    facts.aliases = { same: ['ping', 'list', 'apply'].map(n => e['/scholium-bridge/' + n] === e['/scholium/' + n]),
                      ping: [ping[0], JSON.parse(ping[2]).name], list: list[0] };
    s.h.shutdown({}, 2);
    facts.aliases.left = Object.keys(e);
    // after an update, both sets are put back once missing
    s.h.endpoints.register();
    s.h.endpoints.keep();
    for (const p of Object.keys(e)) delete e[p];
    s.h.fire();
    facts.aliases.kept = Object.keys(e).filter(p => e[p] === s.h.endpoints.endpoints[p]).sort();
    s.h.endpoints.unregister();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node.js is required for plugin tests")
    return run_scenarios(SCENARIOS, tmp_path_factory)


# ---------------------------------------------------------------------------
# the plugin's start
# ---------------------------------------------------------------------------
@needs_node
def test_scholium_bridge_is_uninstalled_before_anything_registers(facts):
    t = facts["takeover"]
    assert t["head"] == ["look " + OLD_ID, "uninstall", "uninstalled"]
    o = t["order"]
    assert min(o["read"], o["section"], o["listener"], o["endpoint"]) > o["uninstalled"] >= 0, o
    # its shutdown dropped every reader listener of its types: Scholium's came after
    assert t["registered"] == {"sections": 1, "listeners": ["createViewContextMenu", "renderToolbar"], "endpoints": ALL_PATHS, "own": 6}
    assert t["said"], "the removal is logged"


@needs_node
def test_its_preferences_are_taken_over_and_cleared(facts):
    t = facts["takeover"]
    assert t["prefs"] == {"extensions.scholium.showAnnotations": True, "extensions.scholium.agent": "codex",
                          "extensions.scholium.followUpMode": "queue", "extensions.scholium.width": 3,
                          "extensions.zotero.dataDir": "/data"}
    assert t["shown"] is True and t["agent"] == "codex", "read after they were taken over"


@needs_node
def test_its_token_is_taken_and_kept_in_both_files(facts):
    t = facts["takeover"]
    assert t["token"] == "OLD-TOKEN-0123456789" and t["files"] == ["OLD-TOKEN-0123456789"] * 2
    assert facts["fresh"]["token"] == "N" * 40 and facts["fresh"]["files"] == ["N" * 40] * 2
    assert facts["both"] == {"token": "NEW-TOKEN-0123456789", "files": ["NEW-TOKEN-0123456789"] * 2}


@needs_node
def test_a_later_start_has_nothing_to_take_over(facts):
    assert facts["again"] == {"asked": ["look " + OLD_ID], "samePrefs": True, "token": "OLD-TOKEN-0123456789", "unwritten": True}
    assert facts["fresh"]["asked"] == ["look " + OLD_ID]
    assert facts["fresh"]["registered"]["own"] == 6


@needs_node
@pytest.mark.parametrize("how", ["fails", "uninstallFails", "noModule"])
def test_the_start_goes_on_when_addonmanager_fails(facts, how):
    f = facts[how]
    assert f["registered"]["sections"] == 1 and f["registered"]["own"] == 6
    assert f["registered"]["listeners"] == ["createViewContextMenu", "renderToolbar"]
    assert f["said"], "the failure is logged"
    assert 10000 not in f["timers"], "the wait for AddonManager ended"


@needs_node
@pytest.mark.parametrize("how", ["hangs", "uninstallHangs"])
def test_the_start_waits_for_addonmanager_ten_seconds_at_most(facts, how):
    f = facts[how]
    assert f["waiting"] == {"done": False, "sections": 0, "own": 0, "timers": [10000]}
    assert f["registered"]["sections"] == 1 and f["registered"]["own"] == 6
    assert f["said"]


@needs_node
def test_the_endpoints_answer_at_scholium_bridges_paths_too(facts):
    a = facts["aliases"]
    assert a["same"] == [True, True, True]
    assert a["ping"] == [200, "scholium"] and a["list"] == 401
    assert a["left"] == [], "both sets go at shutdown"
    assert a["kept"] == ALL_PATHS, "both sets are handed over after an update"


# ---------------------------------------------------------------------------
# the tool
# ---------------------------------------------------------------------------
@pytest.fixture
def plugin(tmp_path, monkeypatch):
    """The plugin's endpoints under the prefixes in `served`, the token files in tmp_path; records each request's path and
    token."""
    monkeypatch.setattr(cli, "_data_dir_candidates", lambda cfg: [str(tmp_path)])
    asked, served = [], {"prefixes": ("/scholium", "/scholium-bridge"), "status": 200}

    def http(method, path, body=None, headers=None, timeout=60):
        if not path.startswith("/scholium"):   # the local API's version check
            return 0, {}, "refused"
        asked.append((path, (headers or {}).get("X-Annotate-Token")))
        prefix, _, name = path.rpartition("/")
        if prefix not in served["prefixes"]:
            return 404, {}, "No endpoint found"
        if served["status"] != 200:
            return served["status"], {}, "unauthorized"
        if name == "apply":
            return 200, {}, json.dumps({"ok": True, "removed": 0, "kept": 0, "created": {}})
        return 200, {}, json.dumps({"ok": True, "version": "0.1.9", "attachmentKey": "A1", "annotations": [], "notes": []})

    monkeypatch.setattr(cli, "http", http)
    return asked, served


def config(tmp_path):
    return dict(cli.DEFAULTS, pdf=str(tmp_path / "x.pdf"), item_key="I1", attachment_key="A1", out_dir=str(tmp_path))


def test_the_tool_asks_scholiums_paths_with_its_token(tmp_path, plugin):
    asked, _ = plugin
    (tmp_path / "scholium.token").write_text("NEW-TOKEN", encoding="utf8")
    (tmp_path / "scholium-bridge.token").write_text("OLD-TOKEN", encoding="utf8")
    res, err = cli.plugin_apply(config(tmp_path), [])
    assert err is None and res["backend"] == "plugin"
    assert asked == [("/scholium/list", "NEW-TOKEN"), ("/scholium/apply", "NEW-TOKEN")]


def test_scholium_bridge_0_1_9_is_reached_at_its_paths_with_its_token(tmp_path, plugin):
    asked, served = plugin
    served["prefixes"] = ("/scholium-bridge",)
    (tmp_path / "scholium-bridge.token").write_text("OLD-TOKEN", encoding="utf8")
    res, err = cli.plugin_apply(config(tmp_path), [])
    assert err is None and res["backend"] == "plugin"
    assert asked == [("/scholium/list", "OLD-TOKEN"), ("/scholium-bridge/list", "OLD-TOKEN"), ("/scholium-bridge/apply", "OLD-TOKEN")]
    listing, err = cli.plugin_list(config(tmp_path))
    assert err is None and listing["backend"] == "plugin"


def test_only_a_missing_endpoint_sends_the_tool_to_the_old_paths(tmp_path, plugin):
    asked, served = plugin
    (tmp_path / "scholium.token").write_text("NEW-TOKEN", encoding="utf8")
    served["status"] = 401
    token, reason = cli.plugin_connect(config(tmp_path))[:2]
    assert token is None and "token mismatch" in reason and [p for p, _ in asked] == ["/scholium/list"]
    asked.clear()
    served.update(prefixes=(), status=200)
    token, reason = cli.plugin_connect(config(tmp_path))[:2]
    assert token is None and reason == "Scholium plugin is not installed (HTTP 404)"
    assert [p for p, _ in asked] == ["/scholium/list", "/scholium-bridge/list"]


@pytest.mark.parametrize("backend", ["plugin", "bridge"])
def test_backend_bridge_is_the_plugin(tmp_path, plugin, capsys, backend):
    (tmp_path / "scholium.token").write_text("NEW-TOKEN", encoding="utf8")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({k: v for k, v in config(tmp_path).items() if k in ("pdf", "item_key", "attachment_key", "out_dir")}),
                    encoding="utf8")
    with pytest.raises(SystemExit) as end:
        cli.main(["--config", str(path), "--list", "--backend", backend])
    assert end.value.code == 0 and json.loads(capsys.readouterr().out)["backend"] == "plugin"
    assert cli.pick_backend("plugin", config(tmp_path))[0] == "plugin"


def test_the_plugin_reads_no_backend_name():
    from plugin_harness import BOOTSTRAP
    assert '"bridge"' not in BOOTSTRAP.read_text(encoding="utf8")
