"""RPC resume failures must not discard a usable native Codex conversation."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const path = '/data/tmp/scholium/ATT1/conversations/codex-20261001-120000.jsonl';
const conv = 'codex-20261001-120000';
const previous = [
  { type: 'scholium', subtype: 'run', agent: 'codex', user: 'First question', at: 1001 },
  { type: 'scholium', subtype: 'prompt', text: 'First question', question: true },
  { type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T1' },
  { method: 'turn/completed', params: { threadId: 'T1', turn: { id: 'K1', status: 'completed', items: [] } } },
  { type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: 'First answer', session_id: 'T1' },
  { type: 'scholium', subtype: 'time', at: 2001 },
].map(ev).join('');
const failures = {
  permission: { code: -32600, message: 'permission denied reading rollout file' },
  auth: { code: -32000, message: 'authentication required' },
  temporary: { code: -32000, message: 'service temporarily unavailable' },
  schema: { code: -32602, message: 'invalid params: expected threadId string' },
  config: { code: -32600, message: 'configuration file not found' },
  rolloutPermission: { code: -32600, message: 'failed to resolve rollout path `/tmp/rollout-T1.jsonl`: permission denied' },
  rolloutDirectory: { code: -32600, message: 'failed to resolve rollout path `/tmp/rollout-T1.jsonl`: path is a directory' },
  network: { code: -32000, message: 'connection reset by peer' },
  overloaded: { code: -32000, message: 'request failed', data: { codexErrorInfo: 'serverOverloaded' } },
  rollout: { code: -32600, message: 'no rollout found for thread id T1' },
  archived: { code: -32600, message: 'thread T1 is archived' },
  thread: { code: -32600, message: 'thread not found: T1' },
  bareThread: { code: -32600, message: 'thread not found' },
  missingRollout: { code: -32600, message: 'rollout file does not exist: /tmp/rollout-T1.jsonl' },
  missingPath: { code: -32600, message: 'failed to resolve rollout path `/tmp/rollout-T1.jsonl`: file does not exist' },
  archivedSession: { code: -32600, message: 'session T1 is archived. Run codex unarchive T1' },
};
(async () => {
  const facts = {};
  const run = async (error, fork = false, recover = false) => {
    const method = fork ? 'thread/fork' : 'thread/resume';
    let attempts = 0;
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, logs: { [path]: previous },
      codex: { newThreads: true, scripts: [CODEX_FOLLOW], answers: {
        [method]: () => (++attempts === 1 || !recover) ? { error } : undefined,
      } } });
    h.log.threads = 1; // the saved conversation already owns T1
    h.runner.start('x');
    const pane = await h.pane(h.item1);
    await settle(100);
    await h.runner.chooseConv('ATT1', conv);
    await h.runner.send(h.item1, 'Follow-up question', Object.assign({ kind: 'chat', conv, agent: 'codex' },
      fork ? { rewind: { turnId: 'K1' }, edited: true } : {}));
    await settle(500);
    await new Promise(resolve => setTimeout(resolve, 100));
    await settle(500);
    const lines = convLines(h), log = await h.runner.readLog('ATT1', conv);
    const sent = h.log.codexProcs.flatMap(proc => proc.sent);
    const result = { attempts, session: own(log, 'codex').session, rewind: own(log, 'codex').rewind,
      gone: lines.filter(line => line.subtype === 'gone').length,
      retry: lines.filter(line => line.subtype === 'retry').length,
      starts: sent.filter(message => message.method === 'thread/start').length,
      injected: sent.filter(message => message.method === 'thread/inject_items').length,
      turns: h.log.codexTurns, state: noteOf(h),
      errors: lines.filter(line => line.subtype === 'end' && line.outcome === 'failed').map(line => line.text),
      expectedError: error.message,
      resumeIds: sent.filter(message => message.method === method).map(message => message.params.threadId) };
    h.runner.stop();
    return result;
  };
  for (const [name, error] of Object.entries(failures)) {
    facts[name] = await run(error);
    if (['permission', 'auth', 'temporary', 'schema', 'network', 'overloaded'].includes(name)) facts['fork_' + name] = await run(error, true);
  }
  facts.recovered = await run(failures.network, false, true);
  facts.forkMissingTurn = await run({ code: -32600, message: 'turn not found: K1' }, true);
  facts.forkUnsupported = await run({ code: -32601, message: 'Method not found' }, true);
  facts.forkUnknownMethod = await run({ code: -32600, message: 'unknown method thread/fork' }, true);
  facts.forkMissingCanonical = await run({ code: -32600, message: "lastTurnId 'K1' was not found in the source thread" }, true);
  facts.forkUnpersisted = await run({ code: -32600, message: "lastTurnId 'K1' is not a persisted canonical turn in the source thread" }, true);
  facts.forkWrappedMissing = await run({ code: -32600, message: 'thread/fork failed to load thread T1: no rollout found for thread id T1' }, true);
  facts.resumeUnsupported = await run({ code: -32601, message: 'Method not found' });
  // Keep the wire's code and structured details for request-specific classification and retries.
  const h = harness({ codex: { answers: { 'thread/resume': () => ({ error: failures.overloaded }) } } });
  const rpc = await h.runner.codexServer(CODEX_APP, '/data');
  try { await rpc.request('thread/resume', { threadId: 'T1' }); }
  catch (error) { facts.metadata = { code: error.code, data: error.data, refused: error.refused, message: error.message }; }
  finally { rpc.close(); await rpc.done; }
  process.stdout.write(JSON.stringify(facts));
})().catch(error => { process.stderr.write(error.stack); process.exitCode = 1; });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


@pytest.mark.parametrize("name", ["permission", "auth", "temporary", "schema", "config", "rolloutPermission", "rolloutDirectory", "resumeUnsupported"])
def test_nonmissing_resume_errors_keep_session_and_report_failure(facts, name):
    result = facts[name]
    assert result["gone"] == result["starts"] == result["injected"] == result["turns"] == 0
    assert result["session"] == "T1" and result["resumeIds"] == ["T1"]
    assert result["state"].startswith("失败") and result["errors"] == [result["expectedError"]]


@pytest.mark.parametrize("name", ["permission", "auth", "temporary", "schema"])
def test_nonmissing_fork_errors_keep_original_session_and_rewind(facts, name):
    result = facts["fork_" + name]
    assert result["gone"] == result["starts"] == result["injected"] == result["turns"] == 0
    assert result["session"] == "T1" and result["rewind"] == {"turnId": "K1"}
    assert result["state"].startswith("失败") and result["errors"] == [result["expectedError"]]


@pytest.mark.parametrize("name", ["network", "overloaded", "fork_network", "fork_overloaded"])
def test_retryable_rpc_errors_retry_once_in_same_session(facts, name):
    result = facts[name]
    assert result["gone"] == result["starts"] == result["injected"] == result["turns"] == 0
    assert result["session"] == "T1" and result["resumeIds"] == ["T1", "T1"]
    assert result["retry"] == 1 and result["state"].startswith("失败")
    assert result["errors"] == [result["expectedError"], result["expectedError"]]


def test_transient_resume_can_recover_without_replaying_history(facts):
    result = facts["recovered"]
    assert result["gone"] == result["starts"] == result["injected"] == 0
    assert result["session"] == "T1" and result["resumeIds"] == ["T1", "T1"]
    assert result["retry"] == result["turns"] == 1 and result["state"].startswith("完成")


@pytest.mark.parametrize("name", ["rollout", "archived", "thread", "bareThread", "missingRollout", "missingPath", "archivedSession",
                                  "forkMissingTurn", "forkUnsupported", "forkUnknownMethod", "forkMissingCanonical", "forkUnpersisted", "forkWrappedMissing"])
def test_explicit_missing_session_and_unsupported_fork_rebuild_history(facts, name):
    result = facts[name]
    assert result["gone"] == result["starts"] == result["injected"] == result["turns"] == 1
    assert result["session"] == "T2" and result["retry"] == 0 and result["state"].startswith("完成")


def test_rpc_rejection_retains_structured_error_details(facts):
    assert facts["metadata"] == {"code": -32000, "data": {"codexErrorInfo": "serverOverloaded"},
                                 "refused": True, "message": "request failed"}
