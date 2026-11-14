"""Incomplete skills are reported and repaired by adding packaged files in an isolated virtual filesystem."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {}, USER = '/home/u/.claude/skills/zotero-scholium', CODEX = '/data/.agents/skills/zotero-scholium';
  const required = ['SKILL.md', 'scripts/scholium.py', 'examples/config.template.json', 'examples/reading_note.template.html',
                    'references/backends.md', 'references/batch.md', 'references/configuration.md', 'references/profile.md',
                    'references/style-zh.md', 'references/zotero-annotations.md'];
  const fill = (h, dir, omit = []) => { for (const rel of required) if (!omit.includes(rel)) h.log.writes[dir + '/' + rel] = 'custom ' + rel; };
  const carried = (h, during = () => {}) => {
    h.zotero.HTTP = { request: async (method, url) => {
      const rel = url.split('/zotero-scholium/')[1];
      (h.log.fetched || (h.log.fetched = [])).push(rel);
      during(rel);
      return { response: new TextEncoder().encode('packaged ' + rel).buffer };
    } };
  };
  const skillLine = async (h, id = 'claudeSkill') => {
    const lines = await h.runner.setupCheck();
    return lines.find(l => l.id === id);
  };
  const fresh = opts => {
    const h = harness(opts);
    h.runner.text = (key, ...args) => [key, ...args].join('|');
    return h;
  };
  {
    const h = fresh(); h.log.writes[USER + '/SKILL.md'] = 'my instructions';
    facts.missing = { line: await skillLine(h), script: await h.runner.skillScript('claude') };
  }
  for (const rel of ['examples/config.template.json', 'examples/reading_note.template.html', 'references/style-zh.md']) {
    const h = fresh(); fill(h, USER, [rel]);
    facts[rel] = await skillLine(h);
  }
  {
    const h = fresh(); fill(h, CODEX, ['scripts/scholium.py']);
    facts.codex = await skillLine(h, 'codexSkill');
  }
  {
    const h = fresh(); h.log.writes[USER + '/SKILL.md'] = 'my instructions';
    h.log.writes[USER + '/references/style-zh.md'] = 'my style';
    h.log.writes[USER + '/custom.txt'] = 'my extra';
    carried(h);
    const result = await h.runner.installSkill('claude');
    facts.repair = { result, files: h.log.writes, fetched: h.log.fetched, line: await skillLine(h) };
  }
  {
    const h = fresh(); fill(h, USER); carried(h);
    facts.complete = { line: await skillLine(h), result: await h.runner.installSkill('claude'), fetched: h.log.fetched || [] };
  }
  {
    const h = fresh(); h.log.writes[USER + '/scripts/scholium.py'] = 'my existing script'; carried(h);
    await h.runner.installSkill('claude');
    facts.noManifest = { script: h.log.writes[USER + '/scripts/scholium.py'], fetched: h.log.fetched };
  }
  {
    const h = fresh(); h.log.writes[USER + '/SKILL.md'] = 'my instructions';
    carried(h, rel => { if (rel === 'scripts/scholium.py') h.log.writes[USER + '/' + rel] = 'created while fetching'; });
    await h.runner.installSkill('claude');
    facts.raced = h.log.writes[USER + '/scripts/scholium.py'];
  }
  {
    const cache = '/home/u/.claude/plugins/cache', plugin = cache + '/market/scholium';
    const old = plugin + '/1.9.2', next = plugin + '/1.10.0';
    const h = fresh({ dirs: { [cache]: [cache + '/market'], [cache + '/market']: [plugin], [plugin]: [old, next] } });
    fill(h, USER, ['scripts/scholium.py']);
    fill(h, old + '/skills/zotero-scholium');
    fill(h, next + '/skills/zotero-scholium', ['references/profile.md']);
    facts.cache = { dir: await h.runner.claudeSkillDir(), script: await h.runner.skillScript('claude'), line: await skillLine(h) };
  }
  {
    const dir = '/data/.claude/skills/zotero-scholium';
    const h = fresh(); fill(h, dir, ['scripts/scholium.py']); carried(h);
    const before = Object.fromEntries(Object.entries(h.log.writes).filter(([path]) => path.startsWith(dir + '/')));
    const line = await skillLine(h);
    const result = await h.runner.setupFix(line.action);
    facts.project = { line, result, before,
      after: Object.fromEntries(Object.entries(h.log.writes).filter(([path]) => path.startsWith(dir + '/'))),
      script: h.log.writes[USER + '/scripts/scholium.py'], checked: await skillLine(h) };
  }
  {
    const cache = '/home/u/.claude/plugins/cache', plugin = cache + '/market/scholium';
    const old = plugin + '/1.9.2', next = plugin + '/1.10.0', project = '/data/.claude/skills/zotero-scholium';
    const dirs = { [cache]: [cache + '/market'], [cache + '/market']: [plugin], [plugin]: [old, next] };
    const files = new Set([old, next].flatMap(dir => required.map(rel => dir + '/skills/zotero-scholium/' + rel)));
    const stats = [], runner = { SKILL_FILES: required };
    const path = require('node:path');
    vm.runInNewContext(fs.readFileSync(path.join(path.dirname(process.argv[2]), 'modules/setup.js'), 'utf8'), {
      ScholiumRunner: runner,
      Zotero: { DataDirectory: { dir: '/data' } },
      PathUtils: { join: (...parts) => parts.join('/'), parent: p => p.slice(0, p.lastIndexOf('/')) },
      IOUtils: {
        exists: async p => files.has(p), getChildren: async p => dirs[p] || [],
        stat: async p => {
          stats.push(p);
          if (!files.has(p)) throw Error('NotFoundError');
          return { type: 'regular', size: 8 };
        },
      },
    });
    runner.skillsDir = () => '/home/u/.claude/skills';
    facts.cacheNewest = { dir: await runner.claudeSkillDir(), stats: stats.slice() };
    for (const dir of [old, next]) files.delete(dir + '/skills/zotero-scholium/scripts/scholium.py');
    facts.cacheIncomplete = await runner.claudeSkillDir();
    files.add(project + '/SKILL.md');
    facts.projectIncomplete = await runner.claudeSkillDir();
    files.add(USER + '/SKILL.md');
    facts.userIncomplete = await runner.claudeSkillDir();
  }
  {
    const h = fresh(); h.log.writes[USER + '/SKILL.md'] = 'my instructions';
    h.zotero.HTTP = { request: async (method, url) => {
      if (url.endsWith('/scripts/scholium.py')) throw Error('missing package file');
      return { response: new TextEncoder().encode('packaged').buffer };
    } };
    const result = await h.runner.installSkill('claude');
    facts.noPackage = { result, files: h.log.writes };
  }
  {
    const h = fresh(); fill(h, USER); h.log.writes[USER + '/scripts/scholium.py'] = ''; carried(h);
    facts.empty = { line: await skillLine(h), result: await h.runner.installSkill('claude'), script: h.log.writes[USER + '/scripts/scholium.py'],
                    runnable: await h.runner.skillScript('claude') };
  }
  {
    const runner = { SKILL_FILES: required };
    const path = require('node:path');
    vm.runInNewContext(fs.readFileSync(path.join(path.dirname(process.argv[2]), 'modules/setup.js'), 'utf8'), {
      ScholiumRunner: runner,
      PathUtils: { join: (...parts) => parts.join('/') },
      IOUtils: { exists: async () => true, stat: async p => ({ type: p.endsWith('/scripts/scholium.py') ? 'directory' : 'regular', size: 8 }) },
    });
    facts.directory = await runner.missingSkillFiles(USER);
    runner.claudeSkillDir = async () => USER;
    facts.directoryScript = await runner.skillScript('claude');
  }
  {
    const h = fresh({ home: 'none' }); fill(h, '/data/.claude/skills/zotero-scholium', ['scripts/scholium.py']);
    facts.noHome = await skillLine(h);
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


USER = "/home/u/.claude/skills/zotero-scholium"


def test_manifest_without_runtime_script_is_incomplete(facts):
    line = facts["missing"]["line"]
    assert line["state"] == "bad"
    assert line["text"].startswith("checkSkillIncomplete|") and "scripts/scholium.py" in line["text"]
    assert line["action"]["repair"] is True and line["action"]["label"] == "checkRepair"
    assert facts["missing"]["script"] is None


@pytest.mark.parametrize("rel", ["examples/config.template.json", "examples/reading_note.template.html", "references/style-zh.md"])
def test_workflow_resources_are_required(facts, rel):
    assert facts[rel]["state"] == "bad" and rel in facts[rel]["text"]


def test_codex_metadata_does_not_hide_a_missing_runtime_script(facts):
    assert facts["codex"]["state"] == "bad" and facts["codex"]["action"]["repair"] is True


def test_repair_adds_missing_files_and_preserves_custom_files(facts):
    repair = facts["repair"]
    assert repair["result"] == "skillInstalled" and repair["line"]["state"] == "ok"
    assert repair["files"][USER + "/SKILL.md"] == "my instructions"
    assert repair["files"][USER + "/references/style-zh.md"] == "my style"
    assert repair["files"][USER + "/custom.txt"] == "my extra"
    assert repair["files"][USER + "/scripts/scholium.py"] == "packaged scripts/scholium.py"
    assert "SKILL.md" not in repair["fetched"] and "references/style-zh.md" not in repair["fetched"]


def test_complete_skill_without_optional_display_metadata_is_unchanged(facts):
    assert facts["complete"]["result"] == "skillThere" and facts["complete"]["fetched"] == []
    assert facts["complete"]["line"]["state"] == "ok" and "action" not in facts["complete"]["line"]


def test_install_without_manifest_preserves_existing_script(facts):
    assert facts["noManifest"]["script"] == "my existing script"
    assert "scripts/scholium.py" not in facts["noManifest"]["fetched"]


def test_repair_preserves_file_created_while_package_is_read(facts):
    assert facts["raced"] == "created while fetching"


def test_incomplete_skills_do_not_shadow_complete_plugin_cache(facts):
    dir = "/home/u/.claude/plugins/cache/market/scholium/1.9.2/skills/zotero-scholium"
    assert facts["cache"]["dir"] == dir and facts["cache"]["script"] == dir + "/scripts/scholium.py"
    assert facts["cache"]["line"]["state"] == "ok" and "action" not in facts["cache"]["line"]


def test_newest_complete_cache_skips_older_resource_checks(facts):
    cache = facts["cacheNewest"]
    assert cache["dir"] == "/home/u/.claude/plugins/cache/market/scholium/1.10.0/skills/zotero-scholium"
    assert not any("/1.9.2/" in path for path in cache["stats"])


def test_all_incomplete_skills_keep_user_project_then_newest_cache_priority(facts):
    assert facts["cacheIncomplete"] == "/home/u/.claude/plugins/cache/market/scholium/1.10.0/skills/zotero-scholium"
    assert facts["projectIncomplete"] == "/data/.claude/skills/zotero-scholium"
    assert facts["userIncomplete"] == USER


def test_repair_uses_user_directory_and_leaves_project_files_untouched(facts):
    project = facts["project"]
    assert project["result"] is None and project["before"] == project["after"]
    assert project["line"]["text"].endswith("|" + USER)
    assert project["script"] == "packaged scripts/scholium.py"
    assert project["checked"]["state"] == "ok" and project["checked"]["text"] == "checkSkillAt|" + USER


def test_missing_package_resource_leaves_incomplete_installation_untouched(facts):
    assert facts["noPackage"]["result"] == "skillNotCarried"
    assert facts["noPackage"]["files"] == {USER + "/SKILL.md": "my instructions"}


def test_empty_custom_script_is_reported_and_never_overwritten(facts):
    assert facts["empty"]["line"]["state"] == "bad"
    assert facts["empty"]["result"] == "skillIncomplete" and facts["empty"]["script"] == ""
    assert facts["empty"]["runnable"] is None


def test_directory_cannot_stand_in_for_runtime_script(facts):
    assert facts["directory"] == ["scripts/scholium.py"]
    assert facts["directoryScript"] is None


def test_incomplete_skill_without_home_has_no_repair_action(facts):
    assert facts["noHome"]["state"] == "bad" and facts["noHome"]["text"] == "skillNoHome"
    assert "action" not in facts["noHome"]
