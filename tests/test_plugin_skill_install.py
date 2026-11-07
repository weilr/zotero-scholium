"""An agent without the zotero-scholium skill: the run's failure offers Install the skill and retry, which copies the
skill the plugin carries into the agent's skills folder (never over one already there) and runs again."""
import re
import subprocess
from pathlib import Path

import pytest

from plugin_harness import BOOTSTRAP, NODE, plugin_source, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const noSkill = [ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: 'S1', skills: ['other'] }), 'WAIT'];
  const carried = h => {
    h.zotero.HTTP = { request: async (method, url, o) => {
      h.log.fetched = (h.log.fetched || []).concat([[url, o && o.responseType]]);
      return { response: new TextEncoder().encode('file ' + url.split('/zotero-scholium/')[1]).buffer };
    } };
  };
  const card = p => {
    const c = p.pane().annot.list.children.at(-1).children.find(c => typeof c.className === 'string' && c.className.startsWith('scholium-card'));
    return c;
  };
  const button = (node, label) => node && node.children.find(c => c.tagName === 'button' && c.textContent === label);
  const written = h => Object.keys(h.log.writes).filter(k => k.includes('/skills/zotero-scholium/'));

  // Claude Code without the skill, the plugin carrying it: installed into ~/.claude/skills, SKILL.md last, then the run again
  {
    const h = harness({ script: noSkill });
    carried(h);
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(300);
    const c = card(p);
    const b = button(c, '安装技能并重试');
    const runs = h.log.calls.length;
    b.click(); await settle(300);
    facts.claude = { cls: c.className, offered: !!b, written: written(h), types: (h.log.fetched || []).map(f => f[1]),
                     text: h.log.writes['/home/u/.claude/skills/zotero-scholium/SKILL.md'], again: h.log.calls.length - runs };
    h.runner.stop();
  }
  // a skill already there is not touched: the run goes again
  {
    const h = harness({ script: noSkill });
    carried(h);
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(300);
    h.log.writes['/home/u/.claude/skills/zotero-scholium/SKILL.md'] = 'the user\'s own';
    const runs = h.log.calls.length;
    button(card(p), '安装技能并重试').click(); await settle(300);
    facts.there = { written: written(h), own: h.log.writes['/home/u/.claude/skills/zotero-scholium/SKILL.md'], fetched: (h.log.fetched || []).length,
                    again: h.log.calls.length - runs };
    h.runner.stop();
  }
  // a plugin without the skill in its package: nothing written, no run, the reason under the box
  {
    const h = harness({ script: noSkill });
    h.zotero.HTTP = { request: async () => { throw Error('NS_ERROR_FILE_NOT_FOUND'); } };
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(300);
    const runs = h.log.calls.length;
    button(card(p), '安装技能并重试').click(); await settle(300);
    facts.notCarried = { written: written(h), said: (p.pane().said || {}).text, again: h.log.calls.length - runs };
    h.runner.stop();
  }
  // Codex without the skill: into ~/.codex/skills; the button stays with the failure when the section is drawn again
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { skillAt: null } });
    carried(h);
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(600);
    const again = await h.pane(h.item1); await settle(200);
    const c = card(again);
    const b = button(c, '安装技能并重试');
    if (b) { b.click(); await settle(600); }
    facts.codex = { offered: !!b, written: written(h).filter(k => k.startsWith('/home/u/.codex/skills/')).length };
    h.runner.stop();
  }
  // a failure with another cause offers no install
  {
    const h = harness({ claudeExists: false });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.annotate(); await settle(300);
    facts.other = { offered: h.flat(p.pane().annot).map(textOf).join('|').includes('安装技能并重试') };
    h.runner.stop();
  }
  // the chat: a question without the skill, its failure line with the install
  {
    const h = harness({ script: noSkill, locale: 'en-US' });
    carried(h);
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    await h.runner.send(h.item1, 'What is new here?'); await settle(300);
    const flat = h.flat(p.pane()).map(textOf).join('|');
    facts.chat = { offered: flat.includes('Install the skill and retry') };
    h.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


SKILL_DIR = "/home/u/.claude/skills/zotero-scholium/"


def test_the_skill_is_installed_into_claude_codes_skills_folder_and_the_run_goes_again(facts):
    c = facts["claude"]
    assert c["cls"].startswith("scholium-card failed") and c["offered"] is True
    assert c["written"][-1] == SKILL_DIR + "SKILL.md", "SKILL.md last"
    assert sorted(w[len(SKILL_DIR):] for w in c["written"]) == sorted(skill_files())
    assert set(c["types"]) == {"arraybuffer"}, "copied byte for byte"
    assert c["text"] == "file SKILL.md"
    assert c["again"] == 1


def test_a_skill_already_there_is_left_as_it_is(facts):
    t = facts["there"]
    assert t["own"] == "the user's own" and t["written"] == [SKILL_DIR + "SKILL.md"] and t["fetched"] == 0
    assert t["again"] == 1


def test_a_plugin_without_the_skill_says_how_to_install_it(facts):
    n = facts["notCarried"]
    assert n["written"] == [] and n["again"] == 0
    assert n["said"] == "这份插件没有带技能：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装。"


def test_codex_gets_it_in_its_own_folder(facts):
    assert facts["codex"]["offered"] is True and facts["codex"]["written"] == len(skill_files())


def test_only_a_missing_skill_offers_the_install(facts):
    assert facts["other"]["offered"] is False
    assert facts["chat"]["offered"] is True


def skill_files():
    out = subprocess.run(["git", "ls-files", "skills/zotero-scholium"], cwd=Path(BOOTSTRAP).parents[2], capture_output=True, text=True,
                         check=True).stdout.split()
    return [f[len("skills/zotero-scholium/"):] for f in out]


def test_the_plugin_names_every_file_of_the_skill():
    named = re.search(r"SKILL_FILES: \[(.*?)\]", plugin_source(), re.S).group(1)
    assert sorted(re.findall(r'"([^"]+)"', named)) == sorted(skill_files())
