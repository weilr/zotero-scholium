"""The tools Claude Code gets (--tools): an annotation run and the messages to its session have the ones the skill uses;
a chat's question also has WebSearch and WebFetch; resumed, compacted and rewound runs keep theirs."""
import pytest

from plugin_harness import NODE, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};
  const tools = a => (a.includes('--tools') ? a[a.indexOf('--tools') + 1] : null);
  const after = (a, flag) => (a.includes(flag) ? a[a.indexOf(flag) + 1] : null);
  const h = harness();
  h.runner.start('x');
  await h.runner.annotate([h.item1]); await settle(300);
  // a message to the annotation session, then a question in the chat
  await h.runner.send(h.item1, '第 5 页那条译文改短', { kind: 'annotate' }); await settle(300);
  await h.runner.send(h.item2, '这篇讲什么？', { kind: 'chat' }); await settle(300);
  facts.runs = h.log.calls.map(c => ({ tools: tools(c.opts.arguments), resume: after(c.opts.arguments, '--resume'),
                                       allowed: after(c.opts.arguments, '--allowedTools') }));
  // the arguments of a compaction and of an edited question, as args() builds them
  facts.compact = tools(await h.runner.args({ kind: 'chat', compact: true, resume: 'S1' }));
  const rewound = await h.runner.args({ kind: 'chat', resume: 'S1', rewind: { uuid: 'u1' } });
  facts.rewound = { tools: tools(rewound), at: after(rewound, '--resume-session-at'), fork: rewound.includes('--fork-session'),
                    tail: rewound.slice(rewound.indexOf('--resume')) };
  facts.annotCompact = tools(await h.runner.args({ kind: 'annotate', compact: true, resume: 'S1' }));
  h.runner.stop();
  process.stdout.write(JSON.stringify(facts));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""

BASE = "Skill,Bash,PowerShell,Read,Write,Edit,Grep,Glob"
WEB = BASE + ",WebSearch,WebFetch"


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


def test_an_annotation_and_its_session_get_the_skills_tools(facts):
    annotate, follow, chat = facts["runs"]
    assert annotate == {"tools": BASE, "resume": None, "allowed": "Skill"}
    assert follow == {"tools": BASE, "resume": "S1", "allowed": "Skill"}, "a message to the annotation session"
    assert facts["annotCompact"] == BASE


def test_a_chat_also_gets_the_web_tools(facts):
    assert facts["runs"][2]["tools"] == WEB and facts["runs"][2]["resume"] is None
    assert facts["compact"] == WEB
    r = facts["rewound"]
    assert r["tools"] == WEB and r["at"] == "u1" and r["fork"] is True
    assert r["tail"] == ["--resume", "S1", "--resume-session-at", "u1", "--fork-session"]
