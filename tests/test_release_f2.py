"""Release fixes F2 (data safety): a write to Zotero kept from what its output says, whatever the exit code; configuration
paths that a shell expands or that are not there; the paper handed to the agent as paper.json, so that the PDF's path
stays off command lines; Codex's MCP servers and default model learnt without reading its configuration; whole-file
rewrites of a conversation and of the profile made atomic; the citations cache bounded."""
import json

import pymupdf
import pytest

from zotero_scholium import cli
from plugin_harness import NODE, run_scenarios
from test_apply_safety import MemoryApi, annotation, run_main

SCENARIOS = r"""
const APPLIED = '/data/tmp/scholium/ATT1/applied.json';
const OUT = '/data/tmp/scholium/ATT1';
const A = OUT + '/config-A.json', B = OUT + '/config-B.json';
const keptA = JSON.stringify({ config: A, agent: 'claude', conv: 'annotate-claude-1', at: 1000 });
const report = applied => '{\n "missed": [{"id": 412}],\n "now_in_zotero": {"annotations": 41},\n "applied": ' + applied + '\n}';
const methods = sent => sent.filter(m => typeof m.method === 'string').map(m => m.method);
const parsed = t => (t === undefined ? null : JSON.parse(t));
const L = o => JSON.stringify(o) + '\n';
(async () => {
  const facts = {};
  // Claude Code: what the output of a write says decides whether it is kept, whatever the exit code
  facts.claudeKept = {};
  for (const [name, content, isError] of [
    ['allowMissed', 'Exit code 2\n' + report('true'), true],
    ['partial', 'Exit code 2\n' + report('"partial"'), true],
    ['partialBlocks', [{ type: 'text', text: 'Exit code 2\n' + report('"partial"') }], true],
    ['refused', 'Exit code 2\n' + report('false'), true],
    ['refusedThenNothing', 'Exit code 1\nTraceback', true],
    ['succeeded', 'written', false]]) {
    const h = harness({ logs: { [APPLIED]: keptA, [A]: '{}', [B]: '{}' },
                        scripts: [[SCRIPT[0], tool('PowerShell', { command: 'python C:/s/scholium.py --config ' + B + ' --apply --allow-missed' }, 't1'),
                                   answer(content, isError, 't1'), LAST, RESULT]] });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(400);
    facts.claudeKept[name] = JSON.parse(h.log.writes[APPLIED]).config;
  }
  // Codex: the same, from the command's output
  facts.codexKept = {};
  for (const [name, done] of [['allowMissed', { exitCode: 2, status: 'failed', output: report('true') }],
                              ['partial', { exitCode: 2, status: 'failed', output: report('"partial"') }],
                              ['refused', { exitCode: 2, status: 'failed', output: report('false') }],
                              ['succeeded', { output: 'written' }]]) {
    const cmd = 'python C:/skills/scholium.py --config ' + B + ' --apply --allow-missed';
    const s = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }), shell('c5', cmd), shell('c5', cmd, done),
               coItem('completed', { type: 'agentMessage', id: 'a9', text: '完成。' }), turnDone({ status: 'completed', durationMs: 1000 })];
    const c = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, logs: { [APPLIED]: keptA, [A]: '{}', [B]: '{}' }, codex: { scripts: [s] } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    facts.codexKept[name] = JSON.parse(c.log.writes[APPLIED]).config;
  }
  // a write whose configuration is named through a shell variable, is not there, or is the plugin's paper.json leaves no
  // configuration kept; a Windows path written with "/" or as Git Bash writes it is kept as Windows writes it; a "$" of
  // a hidden share is no variable
  {
    const SHARE = '\\\\fs\\home$\\u\\Zotero\\tmp\\scholium\\ATT1\\config.json';
    const h = harness({ logs: { [A]: '{}', 'D:\\Zotero\\tmp\\scholium\\ATT1\\config-B.json': '{}', [SHARE]: '{}', [OUT + '/paper.json']: '{}' } });
    h.runner.start('x');
    const out = [];
    for (const config of ['$o\\config.json', '%o%\\config.json', '$env:OUT/config.json', '${o}/config.json', OUT + '/missing.json', 'missing.json',
                          OUT + '/paper.json', 'paper.json', '.\\paper.json', 'D:/Zotero/tmp/scholium/ATT1/config-B.json',
                          '/d/Zotero/tmp/scholium/ATT1/config-B.json', SHARE]) {
      h.log.writes[APPLIED] = keptA;
      await h.runner.noteApplied('ATT1', config, 'claude', 'c', '/data');
      out.push(APPLIED in h.log.writes ? JSON.parse(h.log.writes[APPLIED]).config : null);
    }
    facts.paths = out;
  }
  // end to end: --config "$o\config.json" in a PowerShell command that wrote; a new conversation is then told to list
  // the annotations, not to rewrite them from the configuration kept before
  {
    const h = harness({ logs: { [APPLIED]: keptA, [A]: '{}' },
                        scripts: [[SCRIPT[0], tool('PowerShell', { command: '$o="D:\\Zotero\\tmp\\scholium\\ATT1"; python C:/s/scholium.py --config "$o\\config.json" --apply' }, 't1'),
                                   answer('{"applied": true}', false, 't1'), LAST, RESULT],
                                  [SCRIPT[0], said('答。'), ev({ type: 'result', subtype: 'success', is_error: false, result: '答。', session_id: 'S2' })]] });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(400);
    h.att1.getAnnotations = () => [h.ann('E0', 'highlight', '#ffd400')];   // what it wrote
    const applied = parsed(h.log.writes[APPLIED]);
    await h.runner.send(h.item1, '第 3 节的批注对吗？'); await settle(400);
    const asked = h.log.stdin.at(-1);
    facts.variable = { applied, listed: asked.includes(`用 --config ${OUT}/paper.json --list --full 列出`), namesA: asked.includes('config-A.json') };
  }
  // an agent that applied paper.json itself: it is not kept as the paper's configuration
  {
    const h = harness({ logs: { [APPLIED]: keptA, [A]: '{}' },
                        scripts: [[SCRIPT[0], tool('PowerShell', { command: 'python C:/s/scholium.py --config ' + OUT + '/paper.json --apply' }, 't1'),
                                   answer('{"applied": true}', false, 't1'), LAST, RESULT]] });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(400);
    facts.paperApplied = parsed(h.log.writes[APPLIED]);
  }
  // the paper as the agent's commands take it: paper.json in the output folder, written whole before the run
  {
    const h = harness();
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(400);
    facts.paper = { file: parsed(h.log.writes[OUT + '/paper.json']), atomic: h.log.tmpPaths.includes(OUT + '/paper.json.tmp'),
                    prompt: h.log.stdin[0] };
  }
  // a question in English about a paper that carries the tool's annotations, none of which the plugin saw written
  {
    const h = harness({ locale: 'en-US', existing: [['zotero-scholium']],
                        scripts: [[SCRIPT[0], ev({ type: 'result', subtype: 'success', is_error: false, result: 'ok', session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().input.type('Why?'); p.pane().send.click(); await settle(400);
    facts.paperEn = h.log.stdin[0];
    facts.paperQuestion = parsed(h.log.writes[OUT + '/paper.json']);
  }
  // Codex: the user's MCP servers named by mcpServerStatus/list, not from its configuration; Codex's own server and the
  // plugins' are left alone; listed in the first run when never listed before, kept as names, and not listed again
  const CX = { 'extensions.scholium.agent': 'codex' };
  const SERVERS = 'extensions.scholium.codexServers';
  const start = sent => sent.find(m => m.method === 'thread/start').params;
  {
    const c = harness({ prefs: CX, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW] } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    const first = c.log.codexProcs.at(-1).sent;
    await c.runner.annotate([c.item1]); await settle(500);
    const second = c.log.codexProcs.at(-1).sent;
    facts.codexQuiet = { first: methods(first), second: methods(second), config: start(first).config, again: start(second).config,
                         listed: (first.find(m => m.method === 'mcpServerStatus/list') || {}).params || null,
                         kept: (c.store.get(SERVERS) || null), servers: c.log.codexProcs.length };
  }
  // names kept from an earlier session switch the servers off at once; the list after the run renews them, off the run
  {
    const c = harness({ prefs: Object.assign({ [SERVERS]: '["s","old"]' }, CX), codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW] } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    const [run, after] = c.log.codexProcs;
    await c.runner.annotate([c.item1]); await settle(500);
    facts.codexSaved = { run: methods(run.sent), config: start(run.sent).config, after: after ? methods(after.sent) : null,
                         afterKilled: after ? after.killed : null, kept: (c.store.get(SERVERS) || null), next: start(c.log.codexProcs.at(-1).sent).config,
                         servers: c.log.codexProcs.length };
  }
  // the list pages by its cursor; a name Codex refuses as a server of config.toml is left out, here and from then on
  {
    const page = p => (p.cursor === 'p2'
      ? { result: { data: [{ name: 't', pluginId: null, tools: {} }, { name: 'codex_apps', pluginId: null, tools: {} }], nextCursor: null } }
      : { result: { data: [{ name: 's', pluginId: null, tools: {} }, { name: 'cua_repl', pluginId: 'cua@openai-bundled', tools: {} }], nextCursor: 'p2' } });
    const refusedT = { error: { code: -32600, message: 'failed to load configuration: invalid transport\nin `mcp_servers.t`\n' } };
    const c = harness({ prefs: CX, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW],
                                            answers: { 'mcpServerStatus/list': page, 'thread/start': p => (p.config && p.config.mcp_servers.t ? refusedT : null) } } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    const first = c.log.codexProcs.at(-1).sent;
    await c.runner.annotate([c.item1]); await settle(500);
    const second = c.log.codexProcs.at(-1).sent;
    facts.codexPaged = { cursors: first.filter(m => m.method === 'mcpServerStatus/list').map(m => m.params.cursor || null),
                         starts: first.filter(m => m.method === 'thread/start').map(m => (m.params.config || {}).mcp_servers || null),
                         turn: methods(first).includes('turn/start'), kept: (c.store.get(SERVERS) || null), next: start(second).config };
  }
  // a refusal that names no server: this thread opens with them, the next one switches them off again
  {
    const vague = { error: { code: -32600, message: 'failed to load configuration: mcp_servers: bad table' } };
    let refusals = 0;
    const c = harness({ prefs: CX, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW],
                                            answers: { 'thread/start': p => (p.config && !refusals++ ? vague : null) } } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    const first = c.log.codexProcs.at(-1).sent;
    await c.runner.annotate([c.item1]); await settle(500);
    facts.codexVague = { starts: first.filter(m => m.method === 'thread/start').map(m => 'config' in m.params),
                         next: start(c.log.codexProcs.at(-1).sent).config, kept: (c.store.get(SERVERS) || null) };
  }
  // a Codex without mcpServerStatus/list runs with the user's servers; the list is tried once more after the run, and
  // not again in this session
  {
    const c = harness({ prefs: CX, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW], refuse: { 'mcpServerStatus/list': 'unknown variant `mcpServerStatus/list`' } } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    const sent = c.log.codexProcs[0].sent;
    const ended = noteOf(c);
    await c.runner.annotate([c.item1]); await settle(500);
    facts.codexOld = { methods: methods(sent), config: 'config' in start(sent), ended,
                       procs: c.log.codexProcs.map(p => methods(p.sent).filter(m => m === 'mcpServerStatus/list' || m === 'thread/start')),
                       kept: (c.store.get(SERVERS) || null) };
  }
  // a list that does not answer in time: the run goes on with the user's servers; the list after the run keeps them
  {
    let held = 0;
    const c = harness({ prefs: CX, codex: { scripts: [CODEX_SCRIPT], answers: { 'mcpServerStatus/list': () => (held++ ? null : 'HOLD') } } });
    c.runner.start('x');
    c.runner.CODEX_LIST_MS = 30;
    await c.runner.annotate([c.item1]); await settle(200);
    await new Promise(r => setTimeout(r, 80));
    await settle(500);
    const sent = c.log.codexProcs[0].sent;
    facts.codexSlow = { config: 'config' in start(sent), turn: methods(sent).includes('turn/start'), ended: noteOf(c), kept: (c.store.get(SERVERS) || null),
                        procs: c.log.codexProcs.length };
  }
  // a name Codex does not take as a server of config.toml fails the thread's configuration: the thread opens without it,
  // and later threads leave it out
  {
    const refused = { error: { code: -32600, message: 'failed to load configuration: invalid transport\nin `mcp_servers.s`\n' } };
    const c = harness({ prefs: CX, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW], answers: { 'thread/start': p => (p.config ? refused : null) } } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    const first = c.log.codexProcs.at(-1).sent;
    const ended = noteOf(c);
    await c.runner.annotate([c.item1]); await settle(500);
    const second = c.log.codexProcs.at(-1).sent;
    facts.codexRefused = { starts: first.filter(m => m.method === 'thread/start').map(m => 'config' in m.params), turn: methods(first).includes('turn/start'),
                           ended, second: methods(second).filter(m => m === 'mcpServerStatus/list' || m === 'thread/start'),
                           secondConfig: 'config' in start(second), kept: (c.store.get(SERVERS) || null) };
  }
  // the default model the section names: none, with the levels of no model, until a new thread names the one Codex
  // runs, which is kept
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().agent.change('codex');
    await settle(200);
    const asked = methods(h.log.codexProcs[0].sent);
    const before = p.view().modelLabels[0], effortsBefore = p.view().efforts;
    await h.runner.annotate([h.item1]); await settle(500);
    facts.codexDefault = { asked, before, effortsBefore, after: p.view().modelLabels[0], pref: h.store.get('extensions.scholium.codexDefault'),
                           efforts: p.view().efforts };
    const g = harness({ prefs: { 'extensions.scholium.codexDefault': 'gpt-6-astra' } });
    g.runner.start('x');
    const q = await g.pane(g.item1);
    await settle(40);
    q.pane().agent.change('codex');
    await settle(200);
    facts.codexDefault.next = q.view().modelLabels[0];
  }
  // an edited question's cut and its Undo replace the conversation's log whole, through a temporary file
  {
    const turn = (n, uuid) => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at: 1000 + n })
      + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
      + L({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S1' })
      + L({ type: 'assistant', uuid: uuid + '-0', session_id: 'S1', message: { content: [{ type: 'text', text: '想一想' }] } })
      + L({ type: 'assistant', uuid, session_id: 'S1', message: { content: [{ type: 'text', text: '回答' + n }] } })
      + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: 'S1' })
      + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
    const CONV = '/data/tmp/scholium/ATT1/conversations/claude-20261001-120000.jsonl';
    const text = turn(1, 'u1') + turn(2, 'u2') + turn(3, 'u3');
    const answered = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S2' }),
                      ev({ type: 'assistant', uuid: 'v-S2', session_id: 'S2', message: { content: [{ type: 'text', text: '新回答' }] } }),
                      ev({ type: 'result', subtype: 'success', is_error: false, result: '新回答', session_id: 'S2' })];
    const h = harness({ logs: { [CONV]: text }, scripts: [answered] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(60);
    const view = h.runner.viewOf(p.pane(), 'chat');
    await h.runner.editTurn(view, h.runner.runsOf(view.entries)[1].prompt, '新问题二', null);
    await settle(400);
    const tmp = () => h.log.tmpPaths.filter(t => t === CONV + '.tmp').length;
    const cut = tmp();
    await h.runner.undoReplace('ATT1/claude-20261001-120000');
    await settle(100);
    facts.atomicLog = { cut, restored: tmp(), back: h.log.writes[CONV] === text };
  }
  // the profile is saved whole through a temporary file
  {
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const [, panes, foot] = h.sheet().children[0].children;
    const [input] = panes.children;
    const [, , , save] = foot.children;
    input.type(input.value + '- 公式不高亮\n');
    save.click(); await settle(20);
    facts.atomicProfile = { tmp: h.log.tmpPaths.includes(PROFILE_PATH + '.tmp'), saved: h.log.writes[PROFILE_PATH].endsWith('- 公式不高亮\n') };
  }
  // the numbered sentences of the 20 papers shown last are kept; stopping drops them
  {
    const keys = Array.from({ length: 25 }, (_, i) => 'K' + String(i).padStart(3, '0'));
    const logs = {};
    for (const k of keys) logs[`/data/tmp/scholium/${k}/sentences.json`] = JSON.stringify({ sentences: [{ id: 1, page: 1, text: 'x' }] });
    const h = harness({ logs });
    h.runner.start('x');
    for (const k of keys.slice(0, 20)) await h.runner.loadCitations(k);
    await h.runner.loadCitations(keys[0]);   // shown again
    for (const k of keys.slice(20)) await h.runner.loadCitations(k);
    const held = [...h.runner.citations.keys()];
    h.runner.stop();
    facts.citations = { size: held.length, shownAgain: held.includes(keys[0]), oldest: keys.slice(1, 7).map(k => held.includes(k)),
                        newest: held.includes(keys[24]), afterStop: h.runner.citations.size };
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""

OUT = "/data/tmp/scholium/ATT1"
A, B = OUT + "/config-A.json", OUT + "/config-B.json"
PAPER = OUT + "/paper.json"


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node.js is required for plugin tests")
    return run_scenarios(SCENARIOS, tmp_path_factory, timeout=300)


# R3-1: the CLI's exit code after a write whose misses were allowed

MISSED = [{"page": 1, "text": "The method improves the result.", "comment": ""},
          {"page": 1, "text": "A sentence this page does not have at all.", "comment": ""}]


def test_a_write_whose_misses_were_allowed_exits_0(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(), args=("--ignore-existing", "--allow-missed"), highlights=MISSED)
    assert report["missed"] and report["applied"] is True
    assert code == 0


def test_misses_still_fail_a_dry_run_a_refused_write_and_a_partial_one(tmp_path, monkeypatch, capsys):
    code, report = run_main(tmp_path, monkeypatch, capsys, MemoryApi(), highlights=MISSED)
    assert code == 2 and report["applied"] is False, "misses not allowed: nothing written"
    code = 0
    try:
        cli.main(["--config", str(tmp_path / "config.json"), "--ignore-existing", "--allow-missed"])
    except SystemExit as e:
        code = e.code
    assert code == 2 and json.loads(capsys.readouterr().out)["missed"], "a dry run reports its misses"

    class FailingDelete(MemoryApi):
        def delete(self, keys):
            raise RuntimeError("delete failed (HTTP 500): busy")
    api = FailingDelete([annotation("OWN", ["zotero-scholium"], text="Old result.")])
    code, report = run_main(tmp_path, monkeypatch, capsys, api, args=("--allow-missed",), cleanup=True, highlights=MISSED)
    assert code == 2 and report["applied"] == "partial", "the earlier items are still there"


# R3-1: what the plugin keeps in applied.json

@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_a_write_is_kept_when_its_output_says_it_was_made_whatever_the_exit_code(facts):
    assert facts["claudeKept"] == {"allowMissed": B, "partial": B, "partialBlocks": B, "refused": A, "refusedThenNothing": A, "succeeded": B}
    assert facts["codexKept"] == {"allowMissed": B, "partial": B, "refused": A, "succeeded": B}


@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_a_write_from_a_configuration_not_found_keeps_none(facts):
    windows_b = "D:\\Zotero\\tmp\\scholium\\ATT1\\config-B.json"
    assert facts["paths"] == [None] * 9 + [windows_b, windows_b, "\\\\fs\\home$\\u\\Zotero\\tmp\\scholium\\ATT1\\config.json"]
    assert facts["variable"] == {"applied": None, "listed": True, "namesA": False}, "the annotations are listed, not rewritten from A"
    assert facts["paperApplied"] is None, "paper.json is never the paper's configuration"


# R3-2: the paper handed over as paper.json

@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_the_paper_is_handed_over_in_paper_json_not_on_a_command_line(facts):
    p = facts["paper"]
    assert p["file"] == {"pdf": "D:/Zotero/storage/ATT1/paper.pdf", "item_key": "ITEM1", "attachment_key": "ATT1", "out_dir": OUT}
    assert p["atomic"] is True
    assert facts["paperQuestion"] == p["file"], "a question's run writes it too"
    prompt = p["prompt"]
    assert "D:/Zotero/storage/ATT1/paper.pdf" not in prompt, "the PDF's path only in paper.json"
    assert f"- 论文：{PAPER}（PDF 的路径、两个 key 和输出目录）" in prompt
    assert (f"{PAPER} 是插件的文件，只读，不要修改：只有 extract（代替 --pdf）和 --list 用 --config {PAPER}。"
            f"你的配置另写一个文件，放在输出目录里（如 {OUT}/config.json），从 {PAPER} 的四个键写起，--apply 用它。"
            "不要把 PDF 路径、论文标题或其他题录写进命令行。") in prompt
    en = facts["paperEn"]
    assert "D:/Zotero/storage/ATT1/paper.pdf" not in en
    assert f"- Paper: {PAPER} (the PDF's path, the two keys and the output directory)" in en
    assert (f"{PAPER} is the plugin's and read-only; do not edit it. Only extract (in place of --pdf) and --list take --config {PAPER}. "
            f"Write your configuration to a file of your own in the output directory (e.g. {OUT}/config.json), starting from the four keys "
            f"of {PAPER}, and give that one to --apply. Never put the PDF's path, the paper's title or other metadata "
            "on a command line.") in en
    assert f"list them with --config {PAPER} --list --full." in en
    assert f"the numbers come from extract --config {PAPER} --sentences {OUT}/sentences.json --out {OUT}/sentences.txt" in en


def _pdf(path):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 120), "The method improves the result.")
        doc.save(path)


def test_extract_and_list_take_the_paper_from_paper_json(tmp_path, monkeypatch, capsys):
    """A file name a shell would expand ($k$, $(...), a backtick) reaches the tool untouched through paper.json."""
    pdf = tmp_path / "Smith - 2023 - Learning $k$-sparse codes $(echo x) `y`.pdf"
    _pdf(pdf)
    out = tmp_path / "out"
    paper = tmp_path / "paper.json"
    paper.write_text(json.dumps({"pdf": str(pdf), "item_key": "ITEM", "attachment_key": "ATT", "out_dir": str(out)}), encoding="utf8")
    cli.main(["extract", "--config", str(paper), "--sentences", str(out / "sentences.json"), "--out", str(out / "sentences.txt")])
    capsys.readouterr()
    assert json.loads((out / "sentences.json").read_text(encoding="utf8"))["pdf"] == str(pdf)
    assert "The method improves the result." in (out / "sentences.txt").read_text(encoding="utf8")
    monkeypatch.setattr(cli, "pick_backend", lambda *a: ("api", MemoryApi([annotation("OWN", ["zotero-scholium"])]), "test API"))
    with pytest.raises(SystemExit) as end:
        cli.main(["--config", str(paper), "--list"])
    assert end.value.code == 0
    assert "config error" not in capsys.readouterr().out


# R3-3: Codex's configuration is not read

@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_codex_mcp_servers_are_named_without_reading_its_configuration(facts):
    q = facts["codexQuiet"]
    assert "config/read" not in q["first"] + q["second"]
    assert q["first"][:5] == ["initialize", "initialized", "account/read", "mcpServerStatus/list", "plugin/installed"]
    assert q["listed"] == {"detail": "toolsAndAuthOnly"}
    assert q["config"] == q["again"] == {"mcp_servers": {"s": {"enabled": False}}}, "not Codex's own server nor a plugin's"
    assert "mcpServerStatus/list" not in q["second"], "listed once while Zotero runs"
    assert q["kept"] == '["s"]' and q["servers"] == 2, "names only; no list after a run that listed"
    pg = facts["codexPaged"]
    assert pg["cursors"] == [None, "p2"]
    assert pg["starts"] == [{"s": {"enabled": False}, "t": {"enabled": False}}, {"s": {"enabled": False}}], "only the refused name left out"
    assert pg["turn"] is True and pg["kept"] == '["s"]' and pg["next"] == {"mcp_servers": {"s": {"enabled": False}}}
    v = facts["codexVague"]
    assert v["starts"] == [True, False] and v["next"] == {"mcp_servers": {"s": {"enabled": False}}} and v["kept"] == '["s"]'
    r = facts["codexRefused"]
    assert r["starts"] == [True, False] and r["turn"] is True
    assert r["second"] == ["thread/start"] and r["secondConfig"] is False and r["kept"] == "[]", "nothing listed again, s left out"


@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_codex_mcp_server_names_are_kept_and_no_run_waits_long_for_them(facts):
    s = facts["codexSaved"]
    assert "mcpServerStatus/list" not in s["run"], "the names kept from an earlier session, at once"
    assert s["config"] == {"mcp_servers": {"s": {"enabled": False}, "old": {"enabled": False}}}
    assert s["after"] == ["initialize", "initialized", "mcpServerStatus/list"] and s["afterKilled"] is True, "listed after the run"
    assert s["kept"] == '["s"]' and s["next"] == {"mcp_servers": {"s": {"enabled": False}}} and s["servers"] == 3
    o = facts["codexOld"]
    assert "turn/start" in o["methods"] and o["config"] is False, "a Codex without the list runs with the user's servers"
    assert o["procs"] == [["mcpServerStatus/list", "thread/start"], ["mcpServerStatus/list"], ["thread/start"]], "tried once more, then not"
    assert o["kept"] is None
    w = facts["codexSlow"]
    assert w["config"] is False and w["turn"] is True and w["ended"] == o["ended"], "the run did not wait for the list"
    assert w["kept"] == '["s"]' and w["procs"] == 2
    assert facts["codexRefused"]["ended"] == o["ended"]


@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_codex_default_model_is_named_once_a_thread_ran_it(facts):
    d = facts["codexDefault"]
    assert d["asked"] == ["initialize", "initialized", "model/list"]
    assert d["before"] == "Codex 默认" and d["effortsBefore"] == ["low", "medium", "high", "xhigh"], "no model named before; Codex has no max"
    assert d["after"] == "Codex 默认（GPT-6-Astra）" and d["pref"] == "gpt-6-astra", "the one a new thread ran"
    assert d["efforts"] == ["low", "medium", "high", "xhigh", "max", "ultra"], "its levels"
    assert d["next"] == "Codex 默认（GPT-6-Astra）"


# R3-6, R3-7

@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_whole_file_rewrites_go_through_a_temporary_file(facts):
    assert facts["atomicLog"] == {"cut": 1, "restored": 2, "back": True}
    assert facts["atomicProfile"] == {"tmp": True, "saved": True}


@pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")
def test_the_citations_cache_keeps_the_papers_shown_last(facts):
    assert facts["citations"] == {"size": 20, "shownAgain": True, "oldest": [False] * 5 + [True], "newest": True, "afterStop": 0}
