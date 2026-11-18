"""The plugin's own folder, <data dir>/scholium: the profile, each paper's records (papers/<key>), each conversation's
working directory (papers/<key>/conversations/<conversation>) and uv's cache (cache/uv); an earlier version's folders
moved into it when the plugin starts; the agents' sessions kept to the plugin (each conversation in its own folder, Codex's
threads archived after each run); the Codex home folder of the settings."""
import json
import re

import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const L = o => JSON.stringify(o) + '\n';
const DIR = '/data/scholium/papers/ATT1/conversations/';
const CONV = 'chat-20261101-120000';
const IDX = JSON.stringify({ chat: CONV, titles: {}, annotation: {} });
// a turn of Claude Code as the plugin logs it, its session started in cwd (none: a log without it)
const claudeTurn = (n, session, cwd) => L({ type: 'scholium', subtype: 'run', agent: 'claude', user: '问题' + n, at: 1000 + n })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L(Object.assign({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: session }, cwd ? { cwd } : {}))
  + L({ type: 'assistant', uuid: 'u' + n, session_id: session, message: { content: [{ type: 'text', text: '回答' + n }] } })
  + L({ type: 'result', subtype: 'success', is_error: false, result: '回答' + n, session_id: session })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
const answered = (session, text) => [ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: session }),
  ev({ type: 'assistant', uuid: 'v-' + text, session_id: session, message: { content: [{ type: 'text', text }] } }),
  ev({ type: 'result', subtype: 'success', is_error: false, result: text, session_id: session })];
const codexTurn = (n, thread) => L({ type: 'scholium', subtype: 'run', agent: 'codex', user: '问题' + n, at: 1000 + n })
  + L(Object.assign({ type: 'scholium', subtype: 'prompt', text: '问题' + n }, n === 1 ? { question: true } : {}))
  + L({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: thread })
  + L({ method: 'turn/completed', params: { threadId: thread, turn: { id: 'K' + n, status: 'completed', items: [] } } })
  + L({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: '回答' + n, session_id: thread })
  + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
const threadCalls = h => h.log.codexProcs.flatMap(p => p.sent).filter(m => typeof m.method === 'string' && /^thread\//.test(m.method))
  .map(m => [m.method, m.params.threadId || null]);
(async () => {
  const facts = {};
  // where things are
  {
    const h = harness({ env: { PATH: '/w/bin' } });
    h.runner.start('x');
    const env = (await h.runner.agentEnv(true)).environment;
    const args = await h.runner.args({ kind: 'chat' });
    facts.paths = { root: h.runner.root(), out: h.runner.outDir('ATT1'), profile: h.runner.profilePath(), uv: h.runner.uvDir(),
                    uvCache: env.UV_CACHE_DIR, uvPython: env.UV_PYTHON_INSTALL_DIR, codexRoots: h.runner.codexRoots(),
                    allowed: args.filter(a => /^(Write|Edit)\(/.test(a)), work: h.runner.workDir('ATT1', CONV), home: env.CODEX_HOME || null };
    h.runner.stop();
  }
  // an earlier version's folders move into the plugin's folder when it starts: whole where nothing has their names; merged
  // where the new folder has some, what it has staying; what is held open stays and is named by the setup check
  {
    const h = harness({ logs: {
      '/data/tmp/scholium/ABCD1234/conversations/chat-1.jsonl': 'L1\n', '/data/tmp/scholium/ABCD1234/config.json': '{}',
      '/data/tmp/scholium/uv/python/x': 'p', '/data/tmp/scholium/notes.txt': 'n',
      '/data/tmp/scholium/EFGH5678/sentences.txt': 'old', '/data/tmp/scholium/EFGH5678/sentences.json': '{}',
      '/data/scholium/papers/EFGH5678/sentences.txt': 'new',
      '/data/tmp/scholium/WXYZ9999/c.json': 'x',
      '/data/zotero-scholium/profile.md': 'B', '/data/zotero-scholium/profile.json': '{}', '/data/scholium/profile.md': 'A' },
      failMoves: ['/data/tmp/scholium/WXYZ9999'] });
    h.runner.start('x');
    await h.runner.migrating;
    const lines = [];
    await h.zotero.Scholium.setupCheck(l => lines.push(l));
    facts.merged = { files: Object.keys(h.log.writes).filter(p => p.startsWith('/data/') && !p.endsWith('.json.tmp')).sort(),
                     profile: h.log.writes['/data/scholium/profile.md'], sentences: h.log.writes['/data/scholium/papers/EFGH5678/sentences.txt'],
                     left: h.runner.migrateLeft.slice(), removed: h.log.removed.slice(), check: lines.filter(l => l.id === 'folders') };
    h.runner.stop();
  }
  {
    const h = harness({ logs: { '/data/tmp/scholium/ABCD1234/conversations/chat-1.jsonl': 'L1\n', '/data/zotero-scholium/profile.md': 'B' } });
    h.runner.start('x');
    await h.runner.migrating;
    const lines = [];
    await h.zotero.Scholium.setupCheck(l => lines.push(l));
    facts.moved = { files: Object.keys(h.log.writes).filter(p => p.startsWith('/data/')).sort(), removed: h.log.removed.slice(),
                    check: lines.filter(l => l.id === 'folders').length, again: await h.runner.migrateFolders() };
    h.runner.stop();
  }
  // a paper of a group library and one of another library move as their key's folder names them
  {
    const h = harness({ logs: { '/data/tmp/scholium/ABCD1234_g7/config.json': '{}', '/data/tmp/scholium/ABCD1234_l5/config.json': '{}',
                                '/data/tmp/scholium/notes/x.json': '{}' } });
    h.runner.start('x');
    await h.runner.migrating;
    facts.libraries = { files: Object.keys(h.log.writes).filter(p => p.startsWith('/data/scholium/papers/')).sort(),
                        kept: '/data/tmp/scholium/notes/x.json' in h.log.writes };
    h.runner.stop();
  }
  // the logs and runs wait for the second try of what could not be moved; a stop ends that wait
  for (const name of ['secondTry', 'stoppedWait']) {
    const h = harness({ logs: { '/data/tmp/scholium/WXYZ9999/config.json': '{}' }, failMoves: ['/data/tmp/scholium/WXYZ9999'] });
    h.runner.start('x');
    await h.runner.migrating;
    let settled = false;
    h.runner.settled().then(() => { settled = true; });
    await settle(20);
    const during = settled;
    if (name === 'secondTry') h.fire(); else h.runner.stop();
    await settle(60);
    facts[name] = { during, after: settled };
    h.runner.stop();
  }
  // the records' paths into the old folders follow the move when a run of the paper starts; a string that only contains
  // one, a folder that only begins like one, and a file that is no record stay
  {
    const OLD = '/data/tmp/scholium/ATT1/', NEW = '/data/scholium/papers/ATT1/';
    const cfg = JSON.stringify({ out_dir: '/data/tmp/scholium/ATT1', note_html: '/DATA/TMP/scholium/ATT1/reading_note.html',
                                 pdf: '/data/storage/ATT1/paper.pdf', other: '/data/tmp/scholium2/x', words: 'see /data/tmp/scholium/ATT1' }, null, 2);
    const h = harness({ scripts: [answered('S1', '答')],
                        logs: { [OLD + 'config.json']: cfg, [OLD + 'applied_keys.json']: JSON.stringify({ config: OLD + 'config.json' }),
                                [OLD + 'annotations.json']: '["/data/tmp/scholium/ATT1"]' } });
    h.runner.start('x');
    await h.runner.migrating;
    const before = h.log.writes[NEW + 'config.json'];
    const p = await h.pane(h.item1); await settle(40);
    p.pane().input.type('新问题'); p.pane().send.click(); await settle(400);
    facts.repointed = { before: before === cfg, config: h.log.writes[NEW + 'config.json'], keys: h.log.writes[NEW + 'applied_keys.json'],
                        other: h.log.writes[NEW + 'annotations.json'], again: await h.runner.repointPaper('ATT1') };
    // a data directory with letters beyond ASCII, which Python's json writes as \u escapes (applied_keys.json)
    const asciiJSON = o => JSON.stringify(o).replace(/[\u0080-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
    h.runner.oldFolders = () => [['C:\\Users\\张三\\Zotero\\tmp\\scholium', 'C:\\Users\\张三\\Zotero\\scholium\\papers']];
    facts.repointed.wide = JSON.parse(h.runner.repointText(asciiJSON({ config: 'C:\\Users\\张三\\Zotero\\tmp\\scholium\\K\\config.json' }))).config;
    facts.repointed.wideJs = JSON.parse(h.runner.repointText(JSON.stringify({ out_dir: 'C:\\Users\\张三\\Zotero\\tmp\\scholium\\K' }))).out_dir;
    h.runner.oldFolders = () => [['D:\\Zotero\\tmp\\scholium', 'D:\\Zotero\\scholium\\papers']];
    facts.repointed.windows = h.runner.repointText(JSON.stringify({ out_dir: 'D:\\Zotero\\tmp\\scholium\\ABCD1234',
      sentences: 'd:\\zotero\\TMP\\scholium\\ABCD1234\\sentences.json', slash: 'D:/Zotero/tmp/scholium/ABCD1234/x.html',
      longer: 'D:\\Zotero\\tmp\\scholiumX\\y' }, null, 1));
    h.runner.stop();
  }
  // a log still to be written (kept across a plugin update) goes to the new folder; its notice names the new path
  {
    const OLD = '/data/tmp/scholium/ATT1/conversations/' + CONV + '.jsonl';
    const h = harness({ logs: { [OLD]: claudeTurn(1, 'S1') } });
    h.zotero.ScholiumPendingLogs = new Map([[OLD, { unlogged: [L({ type: 'scholium', subtype: 'time', at: 3000 })], completed: { key: 'ATT1', kind: 'chat', conv: CONV } }]]);
    h.runner.start('x');
    await h.runner.migrating;
    const keys = [...h.runner.pendingLogs.keys()];
    const note = h.runner.notes.get('ATT1/chat');
    // a log read at once waits for the move
    const read = await h.runner.readLog('ATT1', CONV);
    facts.pending = { keys, note: note && note.pendingLog, turns: read ? read.turns.length : null };
    h.runner.stop();
  }
  // Claude Code: a new conversation runs in its own folder; a session that started elsewhere goes on there
  {
    const h = harness({ scripts: [answered('S1', '答')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.pane().input.type('新问题'); p.pane().send.click(); await settle(400);
    const conv = p.view().shownConv;
    facts.claudeNew = { workdir: h.log.calls[0].opts.workdir, conv, made: h.log.madeDirs.includes(h.log.calls[0].opts.workdir),
                        cwd: own(await h.runner.readLog('ATT1', conv), 'claude').cwd };
    h.runner.stop();
  }
  for (const [name, cwd] of [['claudeOld', '/data'], ['claudeOwn', DIR + CONV], ['claudeNone', null], ['claudeElsewhere', 'D:/Elsewhere'],
                             ['claudeGone', 'D:/Moved']]) {
    const h = harness({ logs: { [DIR + CONV + '.jsonl']: claudeTurn(1, 'S1', cwd), [DIR + 'index.json']: IDX, 'D:/Elsewhere/kept.txt': 'x' },
                        scripts: [answered('S1', '下一答')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.pane().input.type('下一问'); p.pane().send.click(); await settle(400);
    const args = h.log.calls[0].opts.arguments;
    facts[name] = { workdir: h.log.calls[0].opts.workdir, resume: args[args.indexOf('--resume') + 1] };
    h.runner.stop();
  }
  // each session of a log goes on in the folder it started in, the latest or not
  {
    const h = harness({ logs: { [DIR + CONV + '.jsonl']: claudeTurn(1, 'S1', '/data') + claudeTurn(2, 'S2', DIR + CONV), [DIR + 'index.json']: IDX } });
    h.runner.start('x');
    const at = async resume => h.runner.claudeDir({ job: { resume, conv: CONV }, key: 'ATT1' });
    facts.claudeSessions = { S1: await at('S1'), S2: await at('S2'), unknown: await at('S9') };
    h.runner.stop();
  }
  // an edited question forks the old session where the session is
  {
    const h = harness({ logs: { [DIR + CONV + '.jsonl']: claudeTurn(1, 'S1', '/data') + claudeTurn(2, 'S1', '/data'), [DIR + 'index.json']: IDX },
                        scripts: [answered('S2', '新答')] });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    const prompt = (await h.runner.readLog('ATT1', CONV)).entries.find(e => e.kind === 'prompt' && e.turn === 1);
    await h.runner.editTurn(p.pane(), prompt, '新问题二'); await settle(400);
    const args = h.log.calls[0].opts.arguments;
    facts.claudeFork = { workdir: h.log.calls[0].opts.workdir, fork: args.includes('--fork-session') };
    h.runner.stop();
  }
  // a deleted conversation's folder goes with it
  {
    const h = harness({ logs: { [DIR + CONV + '.jsonl']: claudeTurn(1, 'S1', DIR + CONV), [DIR + 'index.json']: IDX,
                                [DIR + CONV + '/scratch.txt']: 'x' } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    await h.runner.deleteConv(p.pane(), { key: 'ATT1', id: CONV, path: DIR + CONV + '.jsonl' }); await settle(50);
    await h.runner.finishDelete(DIR + CONV + '.jsonl').catch(() => {}); await settle(50);
    facts.deleted = { removed: h.log.removed.slice(), scratch: (DIR + CONV + '/scratch.txt') in h.log.writes };
    h.runner.stop();
  }
  // Codex: the thread is archived as each run ends, and comes back for the next; once, the threads earlier versions' runs
  // left in the Codex app's list are archived
  {
    const old = '/data/scholium/papers/ATT2/conversations/codex-20261001-120000.jsonl';
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, logs: { [old]: codexTurn(1, 'OLD1') + codexTurn(2, 'OLD2') },
                        codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.pane().input.type('问一'); p.pane().send.click(); await settle(600);
    const first = threadCalls(h);
    const work = h.log.codexProcs.at(-1).sent.find(m => m.method === 'thread/start').params.cwd;
    p.pane().input.type('问二'); p.pane().send.click(); await settle(600);
    facts.codexRuns = { first, second: threadCalls(h).slice(first.length), work, conv: p.view().shownConv,
                        done: h.store.get('extensions.scholium.codexArchivedOld') || null, queued: h.store.get('extensions.scholium.codexArchive') || null };
    h.runner.stop();
  }
  // a failed turn's thread is archived too; a server that ended leaves its thread for the next run
  {
    const failed = CODEX_SCRIPT.slice(0, -1).concat([turnDone({ status: 'failed', error: { message: 'boom' } })]);
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex', 'extensions.scholium.codexArchivedOld': '1' }, codex: { scripts: [failed] } });
    h.runner.start('x');
    const p = await h.pane(h.item1); await settle(40);
    p.pane().input.type('问一'); p.pane().send.click(); await settle(600);
    facts.codexFailed = threadCalls(h);
    h.runner.stop();
    const g = harness({ prefs: { 'extensions.scholium.agent': 'codex', 'extensions.scholium.codexArchivedOld': '1' }, codex: { exitOn: 'thread/archive' } });
    g.runner.start('x');
    const q = await g.pane(g.item1); await settle(40);
    q.pane().input.type('问一'); q.pane().send.click(); await settle(600);
    facts.codexEnded = { calls: threadCalls(g), queued: g.store.get('extensions.scholium.codexArchive') || null };
    g.runner.stop();
  }
  // the Codex home folder of the settings: Codex's processes keep their threads and sign-in there; one not there stops the run
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex', 'extensions.scholium.codexHome': 'D:/CodexHome' },
                        logs: { 'D:/CodexHome/config.toml': '' } });
    h.runner.start('x');
    const env = (await h.runner.agentEnv(true)).environment;
    const plain = (await h.runner.agentEnv()).environment;
    facts.home = { codex: env.CODEX_HOME || null, claude: plain.CODEX_HOME || null, skills: h.runner.skillsDir('codex'),
                   login: h.runner.codexLogin(h.runner.text('checkSignedOut', 'codex')) };
    h.runner.stop();
    const g = harness({ prefs: { 'extensions.scholium.agent': 'codex', 'extensions.scholium.codexHome': 'D:/Nowhere' } });
    g.runner.start('x');
    const q = await g.pane(g.item1); await settle(40);
    q.pane().input.type('问一'); q.pane().send.click(); await settle(600);
    facts.homeMissing = { threads: threadCalls(g).length, state: noteOf(g), detail: convLines(g).filter(l => l.subtype === 'end').map(l => l.text).join(' ') };
    g.runner.stop();
    const k = harness({ prefs: { 'extensions.scholium.agent': 'codex', 'extensions.scholium.codexHome': 'D:/CodexHome' },
                        logs: { 'D:/CodexHome/config.toml': '' },
                        codex: { answers: { 'account/read': () => ({ result: { account: null, requiresOpenaiAuth: true } }) } } });
    k.runner.start('x');
    const lines = [];
    await k.zotero.Scholium.setupCheck(l => lines.push(l));
    facts.homeCheck = { line: lines.find(l => l.id === 'codex') || null, env: k.log.codexCalls.map(o => o.environment.CODEX_HOME) };
    k.runner.stop();
  }
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


WORK = r"/data/scholium/papers/ATT1/conversations/chat-[\w-]+"


def test_everything_the_plugin_keeps_is_in_the_scholium_folder(facts):
    p = facts["paths"]
    assert p["root"] == "/data/scholium"
    assert p["out"] == "/data/scholium/papers/ATT1"
    assert p["profile"] == "/data/scholium/profile.md"
    assert p["uv"] == "/data/scholium/cache/uv"
    assert p["uvCache"] == "/data/scholium/cache/uv/cache"
    assert p["uvPython"] == "/data/scholium/cache/uv/python"
    assert p["work"] == "/data/scholium/papers/ATT1/conversations/chat-20261101-120000"
    assert p["home"] is None, "no Codex home folder unless the settings name one"


def test_the_agents_may_write_in_the_scholium_folder(facts):
    p = facts["paths"]
    assert p["allowed"] == ["Write(/data/scholium/**)", "Edit(/data/scholium/**)"]
    assert p["codexRoots"][0] == "/data/scholium"
    assert all("tmp" not in r for r in p["codexRoots"])


def test_an_earlier_versions_folders_are_merged_into_the_new_one(facts):
    m = facts["merged"]
    assert m["files"] == sorted([
        "/data/scholium/papers/ABCD1234/conversations/chat-1.jsonl", "/data/scholium/papers/ABCD1234/config.json",
        "/data/scholium/cache/uv/python/x",
        "/data/tmp/scholium/notes.txt",
        "/data/scholium/papers/EFGH5678/sentences.txt", "/data/scholium/papers/EFGH5678/sentences.json",
        "/data/tmp/scholium/EFGH5678/sentences.txt",
        "/data/tmp/scholium/WXYZ9999/c.json",
        "/data/scholium/profile.md", "/data/scholium/profile.json", "/data/zotero-scholium/profile.md"])
    assert m["profile"] == "A" and m["sentences"] == "new", "what the new folder has stays"
    assert m["left"] == ["/data/tmp/scholium/WXYZ9999"]
    assert "/data/tmp/scholium" not in m["removed"] and "/data/zotero-scholium" not in m["removed"], "a folder that still holds something stays"
    assert len(m["check"]) == 1 and m["check"][0]["state"] == "bad"
    assert "1" in m["check"][0]["text"] and "/data/tmp/scholium/WXYZ9999" in m["check"][0]["text"]


def test_folders_moved_whole_are_removed_and_a_second_start_has_nothing_to_move(facts):
    m = facts["moved"]
    assert m["files"] == ["/data/scholium/papers/ABCD1234/conversations/chat-1.jsonl", "/data/scholium/profile.md"]
    assert "/data/zotero-scholium" in m["removed"] and "/data/tmp/scholium" in m["removed"]
    assert m["check"] == 0, "the setup check names nothing when everything moved"
    assert m["again"] == []


def test_the_papers_of_other_libraries_move_too(facts):
    assert facts["libraries"] == {"files": ["/data/scholium/papers/ABCD1234_g7/config.json", "/data/scholium/papers/ABCD1234_l5/config.json"],
                                  "kept": True}, "a folder no key names stays where it is"


def test_logs_and_runs_wait_for_the_second_try_of_the_move(facts):
    assert facts["secondTry"] == {"during": False, "after": True}
    assert facts["stoppedWait"] == {"during": False, "after": True}, "a stop ends the wait"


def test_the_records_paths_follow_the_move_when_a_run_of_the_paper_starts(facts):
    r = facts["repointed"]
    assert r["before"], "nothing is read or written at the start"
    cfg = json.loads(r["config"])
    assert cfg["out_dir"] == "/data/scholium/papers/ATT1"
    assert cfg["note_html"] == "/data/scholium/papers/ATT1/reading_note.html"
    assert cfg["pdf"] == "/data/storage/ATT1/paper.pdf" and cfg["other"] == "/data/tmp/scholium2/x"
    assert cfg["words"] == "see /data/tmp/scholium/ATT1", "only a string that starts with the folder"
    assert r["config"].startswith('{\n  "out_dir"'), "the file's layout stays"
    assert json.loads(r["keys"])["config"] == "/data/scholium/papers/ATT1/config.json"
    assert r["other"] == '["/data/tmp/scholium/ATT1"]', "only the records that name paths"
    assert r["again"] == 0, "a record already pointing to the new folder stays as it is"
    assert r["wide"] == "C:\\Users\\张三\\Zotero\\scholium\\papers\\K\\config.json", "as Python's json writes it"
    assert r["wideJs"] == "C:\\Users\\张三\\Zotero\\scholium\\papers\\K", "as the plugin writes it"
    assert json.loads(r["windows"]) == {"out_dir": "D:\\Zotero\\scholium\\papers\\ABCD1234",
                                        "sentences": "D:\\Zotero\\scholium\\papers\\ABCD1234\\sentences.json",
                                        "slash": "D:/Zotero/scholium/papers/ABCD1234/x.html",
                                        "longer": "D:\\Zotero\\tmp\\scholiumX\\y"}


def test_a_log_still_to_be_written_follows_the_move(facts):
    p = facts["pending"]
    assert p["keys"] == ["/data/scholium/papers/ATT1/conversations/chat-20261101-120000.jsonl"]
    assert p["note"] == "/data/scholium/papers/ATT1/conversations/chat-20261101-120000.jsonl"
    assert p["turns"] == 1, "the log is read where it was moved to"


def test_claude_code_runs_a_new_conversation_in_its_own_folder(facts):
    c = facts["claudeNew"]
    assert re.fullmatch(WORK, c["workdir"]) and c["workdir"].endswith("/" + c["conv"])
    assert c["made"] is True


def test_claude_code_goes_on_with_a_session_where_it_started(facts):
    assert facts["claudeOld"] == {"workdir": "/data", "resume": "S1"}, "a session of the data directory goes on there"
    assert facts["claudeElsewhere"] == {"workdir": "D:/Elsewhere", "resume": "S1"}
    assert facts["claudeGone"] == {"workdir": "/data/scholium/papers/ATT1/conversations/chat-20261101-120000", "resume": "S1"}, \
        "a folder that is gone (a moved data directory): the conversation's own, where Claude Code finds the session gone"
    assert facts["claudeNone"] == {"workdir": "/data", "resume": "S1"}, "a log without the folder: the data directory, as before"
    assert facts["claudeOwn"] == {"workdir": "/data/scholium/papers/ATT1/conversations/chat-20261101-120000", "resume": "S1"}
    assert facts["claudeFork"] == {"workdir": "/data", "fork": True}, "an edit forks the session where it is"
    assert facts["claudeSessions"] == {"S1": "/data", "S2": "/data/scholium/papers/ATT1/conversations/chat-20261101-120000",
                                       "unknown": "/data"}, "each session where it started, the latest or not"


def test_a_deleted_conversations_folder_goes_with_it(facts):
    d = facts["deleted"]
    assert "/data/scholium/papers/ATT1/conversations/chat-20261101-120000" in d["removed"]
    assert d["scratch"] is False


def test_codex_threads_are_archived_after_each_run_and_come_back_for_the_next(facts):
    c = facts["codexRuns"]
    assert re.fullmatch(WORK, c["work"]) and c["work"].endswith("/" + c["conv"]), "the conversation's own folder"
    assert c["first"] == [["thread/start", None], ["thread/archive", "T1"], ["thread/archive", "OLD1"], ["thread/archive", "OLD2"]], \
        "the run's thread as it ends, then once the threads of earlier runs"
    assert c["second"] == [["thread/unarchive", "T1"], ["thread/resume", "T1"], ["thread/archive", "T1"]]
    assert c["done"] == "1" and c["queued"] is None


def test_a_failed_runs_thread_is_archived_and_one_codex_could_not_take_waits(facts):
    assert facts["codexFailed"] == [["thread/start", None], ["thread/archive", "T1"]]
    e = facts["codexEnded"]
    assert e["calls"] == [["thread/start", None], ["thread/archive", "T1"]]
    assert e["queued"] == '["T1"]', "the server ended: archived at the next run"


def test_the_codex_home_folder_of_the_settings(facts):
    h = facts["home"]
    assert h["codex"] == "D:/CodexHome" and h["claude"] is None, "Codex's processes only"
    assert h["skills"] == "D:/CodexHome/skills"
    assert '$env:CODEX_HOME="D:/CodexHome"; codex login' in h["login"]
    assert facts["homeMissing"]["threads"] == 0, "no thread is opened"
    assert "D:/Nowhere" in facts["homeMissing"]["detail"], "the run names the folder that is not there"
    c = facts["homeCheck"]
    assert c["line"]["state"] == "bad" and '$env:CODEX_HOME="D:/CodexHome"; codex login' in c["line"]["text"]
    assert c["env"] and all(v == "D:/CodexHome" for v in c["env"])
