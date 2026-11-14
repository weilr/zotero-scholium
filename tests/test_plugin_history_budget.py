"""Bound the local history sent to a new or returning agent; no real agents or Zotero."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
const facts = {};
const brokenUnicode = s => /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(s);
for (const locale of ['zh-CN', 'en-US']) {
  const h = harness({ locale }), r = h.runner;
  const inspect = turns => {
    const before = JSON.stringify(turns), text = r.historyText(turns), missed = r.missedText(turns, 5000), items = r.historyItems(turns);
    const parts = r.historyParts(turns), itemTexts = items.map(i => i.content[0].text);
    return { textLength: text.length, missedLength: missed.length, itemsLength: JSON.stringify(items).length,
      summary: parts.summary, whole: parts.whole.map(t => t.n),
      latestWhole: parts.whole.slice(-5).every(t => turns.some(old => t.user === old.user && t.answer === old.reply)),
      coherent: parts.whole.every(t => text.includes(t.user) && text.includes(t.answer) && itemTexts.includes(t.user) && itemTexts.includes(t.answer)),
      roles: items.map(i => i.role), unchanged: before === JSON.stringify(turns),
      brokenUnicode: [text, missed, ...itemTexts].some(brokenUnicode),
      textEnd: text.split('\n\n').at(-1), missedEnd: missed.split('\n\n').at(-1),
      missedNumber: missed.includes('[Turn 6000]') || missed.includes('[第 6000 轮]') };
  };
  for (const n of [100, 1000]) {
    const turns = Array.from({ length: n }, (_, i) => ({ user: 'Question ' + (i + 1) + ': ' + 'q'.repeat(1000),
      reply: 'Answer ' + (i + 1) + ': ' + 'a'.repeat(2000), agent: i % 2 ? 'codex' : 'claude', done: true }));
    facts[locale + n] = inspect(turns);
    if (n === 1000) {
      const say = 'CURRENT QUESTION: ' + '新😀'.repeat(20000) + ' KEEP THE END';
      const job = { att: h.item1, say, resume: 'S1', history: turns };
      const prompt = r.prompt(job, 0), missedPrompt = r.prompt({ ...job, history: [], missed: turns }, 0);
      facts[locale + 'current'] = { kept: prompt.includes(say) && missedPrompt.includes(say),
        afterHistory: prompt.indexOf(say) > prompt.indexOf(facts[locale + n].textEnd),
        compact: r.prompt({ ...job, compact: true, say: 'keep methods' }, 0) };
    }
  }
  const huge = [{ n: 42, user: 'QUESTION-BEGIN ' + '😀\\"\n'.repeat(20000) + ' QUESTION-END',
    quote: { page: 12, text: 'QUOTE-BEGIN ' + '😀'.repeat(40000) + ' QUOTE-END' },
    reply: 'ANSWER-BEGIN ' + '😀\\"\n'.repeat(20000) + ' ANSWER-END', agent: 'codex', done: true }];
  const hugeParts = r.historyParts(huge);
  facts[locale + 'huge'] = { ...inspect(huge),
    questionStart: hugeParts.whole[0].user.includes('QUESTION-BEGIN'), questionEnd: hugeParts.whole[0].user.includes('QUESTION-END'),
    quoteClosed: /^\[p\.12\] "[^]*"\nQUESTION-BEGIN/.test(hugeParts.whole[0].user),
    quotePresent: hugeParts.whole[0].user.includes('QUOTE-BEGIN'), answerPresent: hugeParts.whole[0].answer.includes('ANSWER-BEGIN') };
  try {
    const longPage = [{ user: 'Question?', quote: { page: 'P'.repeat(50000), text: 'Passage.' }, reply: 'Answer.', done: true }];
    require('node:vm').runInNewContext('r.historyParts(turns)', { r, turns: longPage }, { timeout: 250 });
    facts[locale + 'longPage'] = { timedOut: false, ...inspect(longPage) };
  } catch (error) {
    facts[locale + 'longPage'] = { timedOut: /timed out/.test(error.message) };
  }
  const short = [{ user: 'What?', quote: { page: 2, text: 'A 😀 passage' }, reply: 'First.', agent: 'claude', done: true },
                 { user: 'Next?', reply: 'Second.', agent: 'codex', done: true }];
  facts[locale + 'short'] = { parts: r.historyParts(short), items: r.historyItems(short).map(i => [i.role, i.content[0].text]),
    none: [r.historyText([]), r.missedText([], 7), r.historyItems([])],
    excerptQuote: r.historyParts(Array.from({ length: 11 }, () => ({ user: 'What?',
      quote: { page: 2, text: 'q'.repeat(150) }, reply: 'A.', done: true }))).summary.includes('[p.2] "' + 'q'.repeat(150) + '"\nWhat?') };
}
const L = o => JSON.stringify(o) + '\n';
const historyTurn = (n, agent) => {
  const session = agent === 'codex' ? 'T1' : 'S1', user = 'Question ' + n + ': ' + 'q'.repeat(1000);
  return L({ type: 'scholium', subtype: 'run', agent, user, at: 1000 + n })
    + L({ type: 'scholium', subtype: 'prompt', text: user, question: true })
    + L({ type: 'system', subtype: 'init', agent, session_id: session })
    + L({ type: 'result', agent, subtype: 'success', is_error: false, result: 'Answer ' + n + ': ' + 'a'.repeat(2000), session_id: session })
    + L({ type: 'scholium', subtype: 'time', at: 2000 + n });
};
(async () => {
  for (const mode of ['switch', 'missed', 'goneClaude', 'goneCodex']) {
    const agent = mode === 'switch' || mode === 'goneCodex' ? 'codex' : 'claude';
    const id = 'chat-20261101-120000', dir = '/data/tmp/scholium/ATT1/conversations/', path = dir + id + '.jsonl';
    const saved = Array.from({ length: 1000 }, (_, i) => historyTurn(i + 1,
      mode === 'goneCodex' || (mode === 'missed' && i > 0) ? 'codex' : 'claude')).join('');
    const answered = [ev({ type: 'system', subtype: 'init', session_id: 'S2' }), said('New answer'),
      ev({ type: 'result', subtype: 'success', is_error: false, result: 'New answer', session_id: 'S2' })];
    const h = harness({ prefs: { 'extensions.scholium.agent': agent },
      logs: { [path]: saved, [dir + 'index.json']: JSON.stringify({ chat: id, titles: {}, annotation: {} }) },
      scripts: mode === 'goneClaude' ? [CLAUDE_GONE, answered] : [answered],
      codex: { scripts: [CODEX_FOLLOW], newThreads: true,
        refuse: mode === 'goneCodex' ? { 'thread/resume': 'thread T1 is archived' } : {} } });
    h.runner.start('x');
    await h.runner.send(h.att1, 'CURRENT QUESTION KEEP ME'); await settle(1200);
    const sent = h.log.codexProcs.flatMap(p => p.sent), start = sent.filter(m => m.method === 'turn/start').at(-1);
    const injected = sent.find(m => m.method === 'thread/inject_items');
    const prompt = agent === 'codex' ? start.params.input[0].text : h.log.stdin.at(-1);
    const end = mode === 'missed' ? '——以上是这段对话最近的几轮，下面是用户的新消息——' : '——以上是之前的对话，新消息如下——';
    const historyLength = injected ? JSON.stringify(injected.params.items).length : prompt.indexOf(end) + end.length;
    facts[mode] = { historyLength, historyPresent: injected ? injected.params.items.length > 0 : prompt.includes(end),
      omitted: (injected ? JSON.stringify(injected.params.items) : prompt).includes('省略'),
      latest: (injected ? JSON.stringify(injected.params.items) : prompt).includes('Question 1000:'),
      current: prompt.includes('CURRENT QUESTION KEEP ME'), saved: h.log.writes[path].startsWith(saved),
      turns: (await h.runner.readLog('ATT1', id)).turns.length,
      resumes: agent === 'claude' ? h.log.calls.map(c => c.opts.arguments.includes('--resume')) :
        sent.filter(m => ['thread/resume', 'thread/start'].includes(m.method)).map(m => m.method) };
    h.runner.stop();
  }
  console.log(JSON.stringify(facts));
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
@pytest.mark.parametrize("count", [100, 1000])
def test_handoff_is_bounded_and_keeps_recent_complete_turns(facts, locale, count):
    value = facts[f"{locale}{count}"]
    assert max(value["textLength"], value["missedLength"], value["itemsLength"]) <= 40000
    assert value["whole"] == list(range(count - 4, count + 1))
    assert value["latestWhole"] and value["coherent"] and value["unchanged"]
    assert value["roles"] == ["user", "assistant"] * 6
    assert not value["brokenUnicode"]
    assert ("省略" if locale == "zh-CN" else "omitted") in value["summary"]
    assert ("本地完整记录" if locale == "zh-CN" else "full local history") in value["summary"]
    if count == 1000:
        assert value["missedNumber"], "missed exchanges keep their original turn offset"


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_oversized_single_exchange_keeps_quote_question_and_unicode(facts, locale):
    value = facts[locale + "huge"]
    assert max(value["textLength"], value["missedLength"], value["itemsLength"]) <= 40000
    assert value["whole"] == [42] and value["coherent"] and value["unchanged"]
    assert value["questionStart"] and value["questionEnd"] and value["quotePresent"] and value["quoteClosed"]
    assert value["answerPresent"] and not value["brokenUnicode"]
    assert ("省略" if locale == "zh-CN" else "omitted") in value["summary"]


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_current_question_and_manual_compaction_are_not_history_truncations(facts, locale):
    assert facts[locale + "current"] == {"kept": True, "afterHistory": True, "compact": "/compact keep methods"}


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_short_history_and_handoff_end_markers_are_unchanged(facts, locale):
    short = facts[locale + "short"]
    assert short["parts"]["summary"] == ""
    assert short["items"] == [["user", '[p.2] "A 😀 passage"\nWhat?'], ["assistant", "First."],
                              ["user", "Next?"], ["assistant", "Second."]]
    assert short["none"] == ["", "", []]
    assert short["excerptQuote"], "an earlier quote that fits the excerpt allowance remains complete"
    long = facts[locale + "1000"]
    assert long["textEnd"] == ("——以上是之前的对话，新消息如下——" if locale == "zh-CN" else
                               "--- the earlier conversation ends; the new message follows ---")
    assert long["missedEnd"] == ("——以上是这段对话最近的几轮，下面是用户的新消息——" if locale == "zh-CN" else
                                 "--- the latest exchanges of this conversation end; the user's new message follows ---")


@pytest.mark.parametrize("mode", ["switch", "missed", "goneClaude", "goneCodex"])
def test_real_handoff_paths_bound_history_without_rewriting_the_saved_log(facts, mode):
    value = facts[mode]
    assert value["historyPresent"] and 0 < value["historyLength"] <= 40000
    assert value["omitted"] and value["latest"] and value["current"]
    assert value["saved"] and value["turns"] == 1001
    expected = {"switch": ["thread/start"], "missed": [True], "goneClaude": [True, False],
                "goneCodex": ["thread/resume", "thread/start"]}
    assert value["resumes"] == expected[mode]


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_oversized_quote_page_label_cannot_stall_history_clipping(facts, locale):
    value = facts[locale + "longPage"]
    assert not value["timedOut"]
    assert max(value["textLength"], value["missedLength"], value["itemsLength"]) <= 40000
    assert value["coherent"] and value["unchanged"]
