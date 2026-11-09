"""Run the plugin's one-click annotation runner against a simulated Zotero, a scripted Claude Code and
a scripted Codex.

The simulated Subprocess replays stream-json output (split across chunks) and answers the model list
request; for Codex it plays `codex app-server`, answering its JSON-RPC requests and sending the
notifications of a turn. So the command line, the task prompt, the Scholium section of the item
pane (the models Claude Code reports, the remembered effort and the levels of each model, the
editor sheet of the personal profile, buttons, state line, resizable transcript, saved history, the message box), the self-closing
notices while Zotero is in front and the system notification while it is not (neither while the section is on screen in the
focused window), follow-ups, the usage limit, deletion, failures, cancellation, the queue and a plugin update are checked
without starting an agent. PathUtils behaves like Zotero's: it has no homeDir, and join()
rejects a first component that is not an absolute path.
"""

import json
from pathlib import Path
import re
import subprocess

import pytest

from plugin_harness import BOOTSTRAP, NODE, PLUGIN, css_rules, run_scenarios

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for plugin tests")

SCENARIOS = r"""
(async () => {
  const facts = {};

  // registration, the item pane before, during and after a run, notices, shutdown
  {
    const h = harness({ logs: { '/data/c.json': '{}' } });   // the configuration SCRIPT applies
    const { runner, log, item1, item2, note } = h;
    runner.start('scholium@zotero-scholium');
    const sec = log.sections[0];
    facts.section = { paneID: sec.paneID, header: sec.header, sidenav: sec.sidenav, ftl: log.ftl.slice(), styles: h.styles() };
    facts.contextMenus = { menus: log.menus.length, readerListeners: log.listeners.map(l => l.type) };

    const before = await h.pane(item1);
    const forNote = await h.pane(note);
    await settle(40);                               // Claude Code answers the model list request
    facts.paneBefore = { enabled: before.enabled, noteEnabled: forNote.enabled, view: before.view() };

    const other = await h.pane(item2);             // a second pane: its selects follow the first one
    await settle(20);
    const m = log.modelCalls[0];
    facts.modelRequest = { calls: log.modelCalls.length, command: m.command, args: m.arguments, workdir: m.workdir, stderr: m.stderr,
                           stdin: log.modelStdin.map(s => JSON.parse(s)), closed: log.modelStdinClosed, kills: log.modelKills,
                           accountKept: JSON.stringify(runner.models).includes('someone@example.com') };
    const p1 = before.pane();
    p1.model.change('fable');
    p1.effort.change('high');
    facts.settings = { model: h.store.get('extensions.scholium.claudeModel'), effort: h.store.get('extensions.scholium.claudeEffort'),
                       otherModel: other.pane().model.value, otherEffort: other.pane().effort.value };

    // the transcript box: its own background
    facts.box = { cls: p1.list.className };

    await runner.annotate([item1]);
    await settle(300);
    const call = log.calls[0].opts;
    facts.call = { command: call.command, args: call.arguments, workdir: call.workdir, env: call.environment, append: call.environmentAppend };
    facts.prompt = log.stdin[0];
    facts.notices = log.notices.map(notice);
    facts.logLines = convText(h).trim().split('\n').length;
    facts.firstConversation = { files: convs(h).map(p => p.replace(/\d{8}-\d{6}/, 'TIME')),
                                index: JSON.parse(log.writes['/data/tmp/scholium/ATT1/conversations/index.json'].replace(/\d{8}-\d{6}/g, 'TIME')),
                                applied: JSON.parse(log.writes['/data/tmp/scholium/ATT1/applied.json'] || 'null') };
    facts.confirmsWithoutExisting = log.confirms.length;
    facts.paneAfter = before.view('annotate');
    const fold = p1.annot.list.children.at(-1).children.find(c => c.className === 'scholium-fold');
    facts.annotOutcome = { fold: fold && fold.children[0].textContent, chatState: before.view('chat').state };
    facts.otherAfter = other.view();
    const toolNode = h.flat(p1.annot).find(c => c.className === 'scholium-entry tool');
    facts.look = { state: p1.state.className, tool: toolNode.children.map(c => [c.tagName, c.className]),
                   name: toolNode.children[1].children.map(c => c.tagName || 'text'),
                   buttons: [p1.annotGo, p1.resume, p1.send].map(b => b.className), tabs: [p1.tabChat, p1.tabAnnotate].map(b => b.className),
                   newChat: [p1.newChat.className, labelOf(p1.newChat)], history: p1.historyButton.className,
                   parts: p1.body.children[0].children.map(c => c.className), selects: [p1.agent.className, p1.model.className, p1.effort.className],
                   input: p1.input.className, inputNative: p1.input.attrs['no-native'], sendRow: p1.sendRow.className };
    const after = await h.pane(item1);              // rendered anew after the run: the annotation tab shows its session
    facts.paneRerendered = after.view('annotate');
    facts.finished = { notifications: log.notifications };

    before.pane().tabAnnotate.click();
    logFrom(before.pane());
    facts.revealed = log.revealed;

    runner.stop();
    facts.stopped = { sections: log.unregisteredSections, ftl: log.ftl.at(-1), panes: runner.panes.size, toolbarItems: h.toolbarItems(), styles: h.styles().length,
                      observers: h.observers.intersection.concat(h.observers.resize).filter(o => !o.off).length };
  }

  // the saved log of an earlier run is shown for a paper that has one
  {
    const earlier = SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('');
    const h = harness({ logs: { [CONV1]: earlier } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    facts.history = p.view();
  }
  {
    const h = harness({ logs: { [CONV1]: SCRIPT.slice(0, 4).concat([RESULT]).join('') } });
    h.runner.start('x');
    facts.historyWithoutLastMessage = (await h.pane(h.item1)).view().flat;
  }
  {
    const failed = SCRIPT.slice(0, 3).concat([ev({ type: 'result', subtype: 'error_during_execution', is_error: true,
                                                   result: 'scholium.py: style_warnings remain' })]).join('');
    const h = harness({ logs: { [CONV1]: failed } });
    h.runner.start('x');
    facts.failedHistory = (await h.pane(h.item1)).view().flat.filter(untimed).at(-1);
  }

  // the saved effort is shown and passed; an unknown one gives medium; an empty model preference passes no --model
  {
    const efforts = {};
    for (const saved of ['xhigh', '', 'auto']) {
      const h = harness({ prefs: { 'extensions.scholium.claudeEffort': saved, 'extensions.scholium.claudeModel': '' } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await h.runner.annotate([h.item1]); await settle(300);
      const args = h.log.calls[0].opts.arguments;
      efforts[saved || 'empty'] = { shown: p.view().effort, passed: args[args.indexOf('--effort') + 1], model: args.includes('--model') };
    }
    facts.savedEfforts = efforts;
  }
  {
    const h = harness({ prefs: { 'extensions.scholium.claudeEffort': 'xhigh' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pick = () => { const v = p.view(); return { efforts: v.efforts, effort: v.effort, disabled: v.effortDisabled }; };
    const first = pick();
    p.pane().model.change('claude-opus-4-6');
    const opus46 = pick();
    p.pane().model.change('claude-sonnet-4-6');
    const sonnet46 = pick();
    p.pane().model.change('haiku');
    const haiku = pick();
    await h.runner.annotate([h.item1]); await settle(300);
    const args = h.log.calls[0].opts.arguments;
    p.pane().model.change('opus');
    const backToOpus = p.view().effort;
    p.pane().model.change('');
    await h.runner.annotate([h.item2]); await settle(300);
    const claudeDefault = { model: h.store.get('extensions.scholium.claudeModel'), passed: h.log.calls[1].opts.arguments.includes('--model') };
    facts.modelEfforts = { first, opus46, sonnet46, haiku, haikuArgs: { model: args[args.indexOf('--model') + 1], effort: args.includes('--effort') },
                           saved: h.store.get('extensions.scholium.claudeEffort'), backToOpus, claudeDefault };
  }

  // an older Claude Code without the model list: the default and the chosen model, asked once
  {
    const h = harness({ models: 'silent', prefs: { 'extensions.scholium.claudeModel': 'claude-sonnet-5-5' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.pane(h.item2);
    await settle(40);
    const v = p.view();
    facts.noModelList = { models: v.models, labels: v.modelLabels, efforts: v.efforts, calls: h.log.modelCalls.length, kills: h.log.modelKills };
  }

  // while the section is on screen in the focused window, on the tab of the run, it replaces the notices
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const p2 = await h.pane(h.item2);
    p.pane().tabAnnotate.click();                   // the tab that shows the paper's annotation
    h.see(true);
    await h.runner.annotate([h.item1]); await settle(300);
    facts.inView = { notices: h.log.notices.length, notifications: h.log.notifications.length,
                     card: p.view('annotate').flat.at(-1), shown: p.view('annotate').state, other: p2.view().state, otherKind: p2.view().stateKind };
    h.focus(false);
    await h.runner.annotate([h.item2]); await settle(300);
    facts.unfocused = { notices: h.log.notices.length, notifications: h.log.notifications.slice() };
    h.focus(true);
    p.body.checkVisibility = () => false;
    p2.body.checkVisibility = () => false;
    await h.runner.annotate([h.item1]); await settle(300);
    facts.collapsed = { notices: h.log.notices.length };
    p.body.checkVisibility = () => true;
    p2.body.checkVisibility = () => true;
    h.see(false);
    await h.runner.annotate([h.item2]); await settle(300);
    facts.scrolledAway = { notices: h.log.notices.length };
  }
  // a link in the transcript opens on a click or with Enter, not when the click ends a selection in it
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const list = p.pane().list;
    const [para] = h.runner.renderMarkdown(h.paneDoc, 'https://example.org/x and [file](file:///C:/x.pdf)');
    const [web, , file] = para.children;
    const event = target => ({ target: { closest: sel => (sel === '.scholium-link[data-href]' && target.getAttribute('data-href') !== null
                                                         ? target : null) },
                               defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } });
    const click = target => { const e = event(target); for (const f of list.listeners.click) f(e); return e.defaultPrevented; };
    const clicked = [click(web), click(file)];
    h.paneWin.getSelection = () => ({ isCollapsed: false, anchorNode: web.children[0] || web });
    clicked.push(click(web));
    delete h.paneWin.getSelection;
    const enter = Object.assign(event(web), { key: 'Enter' });
    for (const f of list.listeners.keydown) f(enter);
    facts.linkClicks = { clicked, opened: h.log.opened, enterPrevented: enter.defaultPrevented };
  }
  {
    const h = harness({ existing: [['zotero-scholium'], ['zotero-scholium'], ['mine']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().tabAnnotate.click(); await settle(5);                           // the tab of Delete annotations
    h.see(true);
    const removed = await h.runner.removeAnnotations([h.item1]);
    facts.deleteInView = { removed, notices: h.log.notices.length, state: p.view().state, kind: p.view().stateKind };
  }
  {
    const h = harness();
    h.runner.start('x');
    await h.pane(h.item2);
    h.see(true);
    await h.runner.annotate([h.item1]); await settle(300);
    facts.otherInView = { notices: h.log.notices.length, notifications: h.log.notifications.map(n => n.title) };
  }
  // in the background: a failed paper and a finished one, each told by a system notification only
  {
    const failing = SCRIPT.slice(0, 3).concat([ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'scholium.py: style_warnings remain' })]);
    const h = harness({ scripts: [failing, SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    h.focus(false);
    await h.runner.annotate([h.item1]); await h.runner.annotate([h.item2]); await settle(600);
    facts.background = { notices: h.log.notices.length, notifications: h.log.notifications.slice() };
  }

  // during a run, the transcript box holds no more entries than the transcript keeps
  {
    const h = harness({ gateFirst: true });
    h.runner.MAX_ENTRIES = 4;
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]);
    await settle(300);
    facts.boundedLog = { running: !!h.runner.current, kept: h.runner.transcript.length, nodes: p.view('annotate').flat.length };
    h.log.calls[0].proc.kill();
    await settle(100);
  }

  // the prompt cannot be handed to Claude Code: the run fails and the process is stopped
  {
    const h = harness({ stdinFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]);
    await settle(300);
    facts.stdinFails = { kills: h.log.kills, running: !!h.runner.current, state: p.view('annotate').state, last: p.view('annotate').flat.filter(untimed).at(-1) };
  }

  // the plugin stops while the program is looked up: no process is started afterwards
  {
    const h = harness();
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(40);
    const find = h.runner.findClaude.bind(h.runner);
    let release = null;
    h.runner.findClaude = async () => { await new Promise(r => { release = r; }); return find(); };
    const queued = h.runner.annotate([h.item1]);
    for (let i = 0; i < 200 && !release; i++) await tick();
    const looking = !!(release && h.runner.job && !h.runner.current);
    h.runner.stop();
    if (release) release();
    await queued;
    await settle(200);
    facts.stopWhileLooking = { looking, calls: h.log.calls.length };
  }

  // the plugin stops while the run's folder is prepared: no process is started
  {
    const h = harness({ holdDirs: true });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(40);
    const queued = h.runner.annotate([h.item1]);
    for (let i = 0; i < 200 && !h.log.releaseDir; i++) await tick();
    const preparing = !!h.log.releaseDir;
    h.runner.stop();
    if (h.log.releaseDir) h.log.releaseDir();
    await queued;
    await settle(200);
    facts.stopWhilePreparing = { preparing, calls: h.log.calls.length };
  }

  // the plugin stops while Claude Code's process or Codex's server is created: it is stopped at once
  for (const agent of ['claude', 'codex']) {
    const h = harness({ prefs: { 'extensions.scholium.agent': agent } });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(200);
    const real = h.runner.subprocess();
    const count = () => agent === 'codex' ? [h.log.codexCalls.length, h.log.codexKills] : [h.log.calls.length, h.log.kills];
    const before = count();   // Codex's model list has started and closed a server already
    let release = null;
    h.runner.subprocess = () => ({ call: async opts => {
      if (opts.arguments[0] !== '--version') await new Promise(r => { release = r; });
      return real.call(opts);
    } });
    const queued = h.runner.annotate([h.item1]);
    for (let i = 0; i < 200 && !release; i++) await tick();
    const creating = !!release;
    h.runner.stop();
    const told = h.log.notices.length + h.log.notifications.length;
    if (release) release();
    await queued;
    await settle(300);
    const after = count();
    facts['stopWhileCreating_' + agent] = { creating, started: after[0] - before[0], stopped: after[1] - before[1], turns: h.log.codexTurns,
                                            toldAfterStop: h.log.notices.length + h.log.notifications.length - told };
  }

  // a run log that refuses a write a moment (a virus scanner, a backup): the run goes on, and the lines go with the next
  // ones, in order, as in a run whose log took every write
  for (const agent of ['claude', 'codex']) {
    const lines = h => convLines(h).filter(l => !(l.type === 'scholium' && l.subtype === 'time')).map(l => JSON.stringify(l).replace(/"at":\d+/g, ''));
    const runs = [];
    // Claude Code: the run's last write, which goes when the run ends
    for (const failLogWrites of [null, agent === 'claude' ? '"num_turns":26' : '"thread/started"']) {
      const h = harness({ failLogWrites, prefs: { 'extensions.scholium.agent': agent }, codex: { noticeBefore: 'thread/start' } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(200);
      await h.runner.annotate([h.item1]);
      await settle(500);
      runs.push({ kills: h.log.kills + h.log.codexKills, locked: !!h.log.lockedOnce, outcome: p.view('annotate').flat.at(-1)[0], lines: lines(h) });
    }
    facts['logLocked_' + agent] = { kills: runs[1].kills - runs[0].kills, locked: runs[1].locked, outcome: runs[1].outcome,
                                    same: JSON.stringify(runs[1].lines) === JSON.stringify(runs[0].lines), lines: runs[1].lines.length };
  }

  // an empty message box is as tall as its placeholder (two lines here), a typed line as tall as the text
  {
    const h = harness({ locale: 'en-US' });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const input = p.pane().input;
    Object.defineProperty(input, 'scrollHeight', { get() { return Math.max(1, Math.ceil(String(this.value).length / 10)) * 24; } });
    h.runner.paintPanes();
    const empty = input.style.height;
    input.type('short');
    const typed = input.style.height;
    input.type('');
    facts.inputHeight = { placeholder: input.placeholder, empty, typed, cleared: input.style.height, value: input.value };
  }

  // extra instructions with a new run, then a follow-up that continues its conversation
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const look = () => { const v = p.view(); return { placeholder: v.placeholder, sendHidden: v.sendHidden, sendDisabled: v.sendDisabled,
                                                       sendRowHidden: p.pane().sendRow.hidden }; };
    const before = look();
    p.pane().tabAnnotate.click();
    p.pane().input.value = '只标注方法部分';
    p.annotate();
    await settle(300);
    const logPath = convs(h)[0];
    facts.extra = { before, after: look(), prompt: h.log.stdin[0], cleared: p.pane().input.value,
                    firstLogLine: h.log.writes[logPath].trim().split('\n').map(l => JSON.parse(l)).find(l => l.subtype === 'prompt'), firstEntry: p.view().flat[0] };
    p.pane().input.value = '第 5 页那条译文改短';
    for (const f of p.pane().input.listeners.input) f({});
    facts.extra.typed = look();
    let prevented = false;
    for (const f of p.pane().input.listeners.keydown) f({ key: 'Enter', ctrlKey: true, preventDefault: () => { prevented = true; } });
    await settle(300);
    const args = h.log.calls[1].opts.arguments;
    const entries = p.view().flat;
    const lines = h.log.writes[logPath].trim().split('\n').map(l => JSON.parse(l));
    facts.followUp = { calls: h.log.calls.length, resume: args[args.indexOf('--resume') + 1], prompt: h.log.stdin[1], prevented,
                       cleared: p.pane().input.value, prompts: entries.filter(e => e[0] === 'scholium-entry prompt').map(e => e[1]),
                       entries: entries.length, markers: lines.filter(l => l.type === 'scholium' && !['run', 'time', 'counts'].includes(l.subtype)).map(l => l.text),
                       inits: lines.filter(l => l.type === 'system' && l.subtype === 'init').length, state: p.view().state,
                       conversations: convs(h).length, times: entries.filter(e => e[0] === 'scholium-meta').length,
                       cards: entries.filter(e => e[0].startsWith('scholium-card')).length, counts: lines.filter(l => l.subtype === 'counts').length };
  }
  {
    // the agent's answer in a continued conversation is Markdown: set as such, with a button that copies its source
    const reply = ['## 改动', '', '- 第 5 页译文改为 **更短** 的一句', '', '| 页 | 条数 |', '|:--|--:|', '| 5 | 1 |'].join('\n');
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]),
                                  [SCRIPT[0], said(reply), ev({ type: 'result', subtype: 'success', is_error: false, result: reply, session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]);
    await settle(300);
    await h.runner.send(h.att1, '第 5 页那条译文改短', { kind: 'annotate' });
    await settle(300);
    const last = pane => h.flat(pane.pane().annot).filter(c => c.className === 'scholium-entry text').at(-1);
    const node = last(p);
    const meta = p.pane().annot.list.children.at(-1).children.at(-1);   // the line under the run's answer
    const copy = meta.children[1];
    copy.click();
    const done = [copy.className, copy.title, h.live()];
    h.fire();
    facts.markdownReply = { reply, tree: tree(node), meta: tree(meta), copied: h.log.copied.slice(), done, reset: [copy.className, copy.title],
                            rerendered: JSON.stringify(tree(last(await h.pane(h.item1)))) === JSON.stringify(tree(node)) };
  }
  {
    // a question in a continued conversation: the answer shows as it is written, then as the whole message; the
    // pieces stay out of the log, a sub-agent's are left out, and the notices give the answer's opening
    const piece = (text, index, parent = null) => ev({ type: 'stream_event', session_id: 'S1', parent_tool_use_id: parent,
                                                      event: { type: 'content_block_delta', index, delta: { type: 'text_delta', text } } });
    const answer = '## 结论\n\n用的是 **SMART**，从头训练。\n\n- 32M 参数';
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]),
      [SCRIPT[0], piece('作废的开头', 0),   // a message begun again: what came before its start is dropped
       ev({ type: 'stream_event', session_id: 'S1', parent_tool_use_id: null, event: { type: 'message_start', message: {} } }),
       piece('## 结论\n\n用的是 **SMART**', 0), piece('，从头训练。', 0), piece('SUB', 0, 'toolu_1'), piece('- 32M 参数', 1), 'HOLD',
       said(answer), 'HOLD', ev({ type: 'result', subtype: 'success', is_error: false, result: answer, session_id: 'S1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]);
    await settle(300);
    const notified = h.log.notifications.length;
    await h.runner.send(h.att1, '用的什么模型？', { kind: 'annotate' });
    await settle(100);
    await new Promise(r => setTimeout(r, 150));   // the draft is set a moment after its pieces
    const last = () => h.flat(p.pane().annot).filter(c => c.className !== 'scholium-meta').at(-1);
    const again = (await h.pane(h.item1)).pane();   // a pane rendered meanwhile shows it too, scrolled to it
    const writing = { tree: tree(last()), draft: h.runner.draft && h.runner.draft.text, again: tree(h.flat(again.annot).at(-1)),
                      againAtEnd: again.annot.list.scrollTop === again.annot.list.scrollHeight && again.annot.list.scrollTop > 0 };
    h.log.release();
    await settle(100);
    const drafts = () => h.flat(p.pane().annot).filter(c => c.className.includes('draft')).length;
    const whole = { drafts: drafts(), left: h.runner.draft, running: !!h.runner.job };   // the whole message, before the run ends
    h.log.release();
    await settle(300);
    facts.streamed = { writing, whole, done: tree(last()), drafts: drafts(),
                       left: h.runner.draft, streamLines: convText(h).split('\n').filter(l => l.includes('stream_event')).length,
                       prompt: h.log.stdin[1], args: h.log.calls[1].opts.arguments, notifications: h.log.notifications.slice(notified),
                       notice: h.log.notices.at(-1).descriptions };
  }
  {
    // a cancelled run keeps the part of the message it showed, marked, in the transcript and the log; the
    // delete button is out of the way meanwhile; words typed and not sent stay with their item
    const piece = text => ev({ type: 'stream_event', session_id: 'S1', parent_tool_use_id: null,
                               event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } } });
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), [SCRIPT[0], piece('写到一半的 **回答**'), 'WAIT']] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]);
    await settle(300);
    const typeIn = (pane, text) => { pane.input.value = text; for (const f of pane.input.listeners.input) f({}); };
    typeIn(p.pane(), '还没发出去的话');
    await h.pane(h.item2);                              // another paper, then this one again
    const restored = (await h.pane(h.item1)).pane().input.value;
    const q = await h.pane(h.item1);
    typeIn(q.pane(), '问一个问题');
    q.pane().send.click();
    await settle(200);
    await new Promise(r => setTimeout(r, 150));   // the draft is set a moment after its pieces
    const during = { removeDisabled: q.view().removeDisabled, inputAfterSend: q.pane().input.value,
                     rerenderedInput: (await h.pane(h.item1)).pane().input.value };
    h.runner.cancel();
    await settle(300);
    const list = h.flat(q.pane());
    const logged = convLines(h).filter(e => e.subtype === 'unfinished');
    const fromLog = (await h.runner.readLog('ATT1', await h.runner.currentConv('ATT1'))).entries.filter(e => e.unfinished);
    facts.unfinished = { restored, during, last: [tree(list.at(-3)), [list.at(-2).className, textOf(list.at(-2))]],
                         logged: logged.map(e => e.text), fromLog: fromLog.map(e => e.text), removeDisabledAfter: q.view().removeDisabled,
                         durations: [8000, 59400, 59600, 376500, 3725000].map(ms => h.runner.duration(ms)) };
  }
  {
    // a run that fails inside a message: what it showed of the message comes before the failure, on screen,
    // in the log and when the log is read again; Claude Code and Codex alike
    const piece = text => ev({ type: 'stream_event', session_id: 'S1', parent_tool_use_id: null,
                               event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } } });
    const order = async (h, agent) => {
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await settle(40);
      await h.runner.annotate([h.item1]);
      await settle(400);
      const kinds = e => (e.unfinished ? 'unfinished' : e.kind);
      return { shown: h.flat(p.pane().annot).slice(-3).map(c => c.className.replace('scholium-entry ', '')),
               logged: convLines(h).filter(e => e.subtype === 'unfinished' || e.type === 'result')
                 .map(e => e.subtype === 'unfinished' ? 'unfinished' : 'result'),
               read: (await h.runner.readLog('ATT1', await h.runner.annotationConv('ATT1', agent))).entries.slice(-3).map(kinds) };
    };
    facts.failedInside = {
      claude: await order(harness({ exitCode: 1, script: [SCRIPT[0], piece('写到一半'),
        ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'Invalid API key', session_id: 'S1' })] }), 'claude'),
      codex: await order(harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [[
        note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
        note('item/agentMessage/delta', { threadId: 'T1', turnId: 'TURN', itemId: 'a9', delta: '写到一半' }),
        turnDone({ status: 'failed', error: { message: 'Invalid API key' } })]] } }), 'codex'),
    };
  }
  {
    // text selected in the draft stays selected: the draft is set again once nothing in it is selected
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    h.runner.transcriptKey = 'ATT1';
    p.pane().shownKey = 'ATT1';
    p.pane().live = true;
    p.pane().list.append(p.pane().doc.createElement('div'));   // the run the draft joins
    h.runner.growDraft('第一段', 0);
    h.runner.paintDraft();
    const node = p.pane().draft.node;
    let selected = true;
    h.paneWin.getSelection = () => ({ isCollapsed: !selected, containsNode: (n, partly) => partly && n === node });
    h.runner.growDraft('，第二段', 0);
    h.runner.paintDraft();
    const held = node.textContent;
    selected = false;
    h.runner.growDraft('，第三段', 0);
    h.runner.paintDraft();
    facts.draftSelection = { held, after: node.textContent };
    h.runner.dropDraft();
    delete h.paneWin.getSelection;
  }
  {
    // a message sent in a conversation goes before the papers waiting for their first run
    const h = harness();
    h.runner.start('x');
    h.runner.draining = true;   // the queue is only looked at
    const order = async (queue, paused = null) => {
      h.runner.queue = queue.map(([key, more]) => Object.assign({ att: { key }, title: key }, more));
      h.runner.paused = paused;
      await h.runner.send(h.att1, '再短一点');
      const keys = h.runner.queue.map(j => j.att.key + (j.say ? ':' + j.say : ''));
      h.runner.queue = [];
      h.runner.paused = null;
      return keys;
    };
    const paused = { until: Date.now() + 60000, known: true, timer: null };
    facts.followUpOrder = {
      fresh: await order([['ATT2'], ['ATT3']]),
      afterTalk: await order([['ATT2', { resume: 'S2', say: '早先的问题' }], ['ATT3']]),
      afterQuestion: await order([['ATT2', { question: true, say: '新的问题' }], ['ATT3']]),
      beforeAnnotation: await order([['ATT2', { annotate: true, resume: 'S2' }], ['ATT3']]),
      afterRetry: await order([['ATT2', { retried: true, retryAt: Date.now() + 30000 }], ['ATT3']]),
      afterPause: await order([['ATT2', { interrupted: true }], ['ATT3']], paused),
      pausedHeadCancelled: await order([['ATT2'], ['ATT3']], paused),   // the interrupted paper was taken out
      alone: await order([]),
    };
    // what the usage limit leaves at the head of the queue: a question goes on as a question
    const limited = (job, session) => {
      h.runner.pause(Object.assign({ att: { key: 'ATT2' }, title: 'B' }, job), { until: null, session });
      const head = h.runner.queue[0];
      clearTimeout(h.runner.paused.timer);
      h.runner.queue = [];
      h.runner.paused = null;
      return { say: head.say, asked: !!head.asked, resume: head.resume || null, interrupted: !!head.interrupted };
    };
    facts.pausedJobs = { question: limited({ say: '为什么？' }, 'S2'), run: limited({ extra: '只标方法' }, 'S2'), noSession: limited({}, null) };
  }

  // the usage limit seen from a paper outside the queue: nothing of the pause, nothing to continue
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1]);
    await settle(300);
    facts.limitOther = { paused: !!h.runner.paused, resume1: !p1.view('annotate').resumeHidden, resume2: !p2.view('annotate').resumeHidden,
                         state2: p2.view('annotate').state };
  }

  // the usage limit: the queue waits, and the interrupted paper continues its conversation after the reset
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1, h.item2]);
    await settle(300);
    p1.pane().tabAnnotate.click(); p2.pane().tabAnnotate.click();
    facts.limit = { clock: h.runner.paused && h.runner.clock(h.runner.paused.claude.until), calls: h.log.calls.length,
                    queue: h.runner.queue.map(j => [j.att.key, j.resume || null, j.say === undefined ? null : j.say]), waits: h.live(),
                    state1: p1.view().state, kind1: p1.view().stateKind, state2: p2.view().state, title1: p1.view().stateTitle, title2: p2.view().stateTitle, resumeShown: !p1.view().resumeHidden, stopShown: p1.view().round[0] === '■',
                    notices: h.log.notices.map(notice), notifications: h.log.notifications.slice(),
                    last: p1.view().flat.filter(untimed).at(-1),
                    followUpWhileQueued: await h.runner.send(h.att1, 'x', { kind: 'annotate' }), queued: h.runner.queue.length,
                    queuedWords: h.runner.queue.map(j => (j.qid ? [j.att.key, j.kind, j.say] : j.att.key)) };
    h.runner.removeQueued(null, h.runner.queue.find(j => j.qid).qid);   // taken out again: the rest is the pause's
    h.fire();
    await settle(800);
    const lines = convLines(h);
    const args = h.log.calls[1].opts.arguments;
    facts.limitResumed = { calls: h.log.calls.length, resume: args[args.indexOf('--resume') + 1], prompt: h.log.stdin[1],
                           order: h.log.stdin.map(s => (s.match(/附件 key：(\w+)/) || [null, 'continue'])[1]),
                           entries: p1.view().flat.map(e => e[1]), markers: lines.filter(l => l.type === 'scholium' && l.subtype !== 'run').map(l => l.subtype),
                           runs: lines.filter(l => l.subtype === 'run').map(l => [l.agent, l.user]),
                           inits: lines.filter(l => l.type === 'system' && l.subtype === 'init').length, state1: p1.view().state,
                           cards: p1.view().flat.filter(e => e[0].startsWith('scholium-card')),
                           notifications: h.log.notifications.map(n => n.title), paused: h.runner.paused, waits: h.live() };
  }
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(RATE_LIMITED)] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1, h.item2]);
    await settle(300);
    p1.pane().tabAnnotate.click(); p2.pane().tabAnnotate.click();
    facts.retry = { clock: h.runner.paused && h.runner.clock(h.runner.paused.claude.until), waits: h.live(), state1: p1.view().state };
    p2.pane().send.click();                       // the waiting paper leaves the queue
    facts.retry.queue = h.runner.queue.map(j => j.att.key);
    p1.pane().resume.click();                       // continue now
    await settle(300);
    const args = h.log.calls[1].opts.arguments;
    facts.retry.after = { calls: h.log.calls.length, resume: args[args.indexOf('--resume') + 1], waits: h.live(), paused: h.runner.paused,
                          state1: p1.view().state, cards1: p1.view().flat.filter(e => e[0].startsWith('scholium-card')), state2: p2.view().state };
  }
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(RATE_LIMITED)] });
    h.runner.start('x');
    const p1 = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(300);
    p1.pane().tabAnnotate.click();
    p1.pane().send.click();                       // the interrupted paper leaves the queue, which ends the pause
    facts.pauseCancelled = { queue: h.runner.queue.length, paused: h.runner.paused, waits: h.live(), calls: h.log.calls.length };
  }

  // the content folder's chrome address carries the version, and every address of the plugin follows it
  {
    const h = harness();
    h.runner.chrome = 'chrome://' + h.chromePackage('0.1.3.10022049') + '/content/';
    h.runner.start('x');
    const sec = h.log.sections[0];
    facts.versioned = { pkg: h.chromePackage('0.1.3.10022049'), release: h.chromePackage('0.2.0'), icons: [sec.header.icon, sec.sidenav.icon],
                        style: h.styles()[0][3] };
  }

  // the personal profile: profile.md as it is, in a sheet over the Zotero window
  {
    const CRLF = PROFILE.replace(/\n/g, '\r\n');
    const h = harness({ logs: { [PROFILE_PATH]: CRLF }, confirm: [false, false] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const q = p.pane();
    q.more.click();
    const button = { text: q.popover.node.children[1].textContent, cls: q.popover.node.children[1].className };
    h.runner.closePopover(q);
    profileFrom(q); await settle(20);
    const root = h.sheet();
    const box = root.children[0];
    const [head, panes, foot] = box.children;
    const [input, preview] = panes.children;
    const [status, , cancel, save] = foot.children;
    const [title, about, pathLine] = head.children;
    const view = () => ({ status: status.textContent, error: status.className.includes('error'), saveDisabled: save.disabled,
                          inputDisabled: input.disabled, open: !!h.sheet() });
    const focusListeners = () => (h.paneWin.listeners.focus || []).length;
    const f = { button, root: [root.className, root.id], box: [box.className, box.attrs.role, box.attrs['aria-label']],
                title: [title.className, title.textContent], panes: [panes.className, input.className, preview.className],
                previewed: preview.children.length,
                head: [about, pathLine].map(c => [c.className, c.textContent]), pathTitle: pathLine.title,
                buttons: [cancel.textContent, save.textContent, cancel.className, save.className],
                text: input.value, focused: !!input.focused, opened: view(), unchanged: h.log.writes[PROFILE_PATH] === CRLF,
                focusListeners: focusListeners() };
    input.focused = false;
    profileFrom(q); await settle(20);
    f.again = { sheets: h.paneDoc.documentElement.children.filter(c => c.id === 'scholium-profile-sheet').length, focused: !!input.focused };
    input.type(input.value + '- 页边批注用蓝色\n');
    f.edited = view();
    let k = key(box, { key: 's', ctrlKey: true }); await settle(20);
    f.ctrlS = { prevented: k.defaultPrevented, stopped: k.stopped, saved: h.log.writes[PROFILE_PATH], view: view(), dirs: h.log.madeDirs.slice() };
    input.type(input.value + '- 公式不高亮\n');
    k = key(box, { key: 'Escape' });
    f.escape = { prevented: k.defaultPrevented, stopped: k.stopped, view: view() };
    cancel.click();
    f.cancel = view();
    save.click(); await settle(20);
    f.saved = { text: h.log.writes[PROFILE_PATH], view: view(), confirms: h.log.confirms.slice(), focusListeners: focusListeners(),
                refocused: !!h.lastFocus.focused };
    facts.profile = f;
  }
  {
    // a missing profile: the template, written on saving
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const [, panes, foot] = h.sheet().children[0].children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    const before = { status: status.textContent, saveDisabled: save.disabled, written: PROFILE_PATH in h.log.writes, text: input.value };
    save.click(); await settle(20);
    facts.profileCreated = { before, saved: h.log.writes[PROFILE_PATH], dirs: h.log.madeDirs, open: !!h.sheet(), confirms: h.log.confirms.length };
  }
  {
    // the file changed elsewhere: asked before overwriting; back in Zotero, an unedited text follows the file
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, confirm: [false, true] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const [, panes, foot] = h.sheet().children[0].children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    const f = {};
    h.log.writes[PROFILE_PATH] = PROFILE + '- 新统计\n';
    h.paneWin.dispatch('focus'); await settle(20);
    f.reloaded = input.value;
    input.type(input.value + '- 我的修改\n');
    h.log.writes[PROFILE_PATH] = PROFILE + '- 再次统计\n';
    h.paneWin.dispatch('focus'); await settle(20);
    f.keptEdits = input.value.endsWith('- 我的修改\n');
    save.click(); await settle(20);
    f.refused = { confirms: h.log.confirms.slice(), file: h.log.writes[PROFILE_PATH], status: status.textContent,
                  error: status.className.includes('error'), open: !!h.sheet() };
    save.click(); await settle(20);
    f.overwritten = { file: h.log.writes[PROFILE_PATH], open: !!h.sheet(), confirms: h.log.confirms.length };
    facts.profileElsewhere = f;
  }
  {
    // the preview beside the text: the text as Markdown as it is typed, scrolled with the text
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const [input, preview] = h.sheet().children[0].children[1].children;
    input.type(input.value + '- **新规则**：`#2ea8e5` 用于方法\n');
    const f = { tree: preview.children.map(tree) };
    // the text box scrolled to 3/4 of its room: the preview goes to 3/4 of its own
    Object.defineProperty(input, 'scrollHeight', { value: 1100 });
    Object.defineProperty(preview, 'scrollHeight', { value: 2100 });
    input.scrollTop = 750;
    for (const g of input.listeners.scroll || []) g({});
    f.scrolled = preview.scrollTop;
    // typing moves the text box without a scroll event of its own: the rebuilt preview follows
    input.scrollTop = 500;
    input.type(input.value + '- x\n');
    f.scrolledAfterTyping = preview.scrollTop;
    // a link in the preview opens on a click, as in the transcript
    input.type(input.value + '- 见 https://example.org/rules\n');
    const list = preview.children[preview.children.length - 1];
    const link = list.children[list.children.length - 1].children.find(c => c.getAttribute && c.getAttribute('data-href'));
    const e = { target: { closest: () => link }, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
    for (const g of preview.listeners.click || []) g(e);
    f.linkOpened = [h.log.opened, e.defaultPrevented];
    facts.profilePreview = f;
  }
  {
    // an unedited text, which changes on disk: the preview follows the file
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const [, preview] = h.sheet().children[0].children[1].children;
    h.log.writes[PROFILE_PATH] = PROFILE + '- 新统计\n';
    h.paneWin.dispatch('focus'); await settle(20);
    facts.profilePreviewReload = tree(preview.children[preview.children.length - 1]);
  }
  {
    // Markdown as the preview builds it
    const h = harness();
    const sample = ['# Title **bold** #', '', 'Para line one', 'line two with `code` and *em* and [link](https://x.y/z)', '',
                    '## Rules', '', '1. first', '2. second', '   - nested `#ff6666` red', '     continued', '- other list', '  1. inner ordered', '',
                    '> quote **q**', '', '```', '<script>alert(1)</script> **not bold**', '```', '', '---', '3. starts at three', '<b>raw</b>'].join('\r\n');
    facts.markdown = h.runner.renderMarkdown(h.paneDoc, sample).map(tree);
    // subscripts and superscripts as agents write them; other tags, unclosed or crossed ones stay text
    facts.markdownSubSup = h.runner.renderMarkdown(h.paneDoc,
      'π<sub>ref</sub>(y|x) and e<sup>**2**</sup>, <b>b</b>, <sub>open and <sub>a<sup>b</sub></sup>').map(tree);
    // tables: the colons align, an escaped bar stays, a short row is filled and a long one cut; bars without
    // a rule of as many cells under them stay text
    const table = ['Before', '| a | b \\| c | d |', '| :-: | --- | ---: |', '| `x` | 2 |', '| 1 | 2 | 3 | 4 |', '',
                   'x | y', 'no rule', '', 'p | q', '|---|---|---|'].join('\n');
    facts.markdownTable = h.runner.renderMarkdown(h.paneDoc, table).map(tree);
    // text that once looped for ever or threw: the line and paragraph separators; a rule line after many
    // spaces; a message that cannot be set shows its source
    facts.markdownSeparators = ['## 结论\u2028更多', '- 一项\u2028续行', '1. 一\u2029二'].map(t => h.runner.renderMarkdown(h.paneDoc, t).map(tree));
    const t0 = Date.now();
    h.runner.renderMarkdown(h.paneDoc, '| a | b |\n' + ' '.repeat(30000) + '|x');
    facts.markdownSpacesMs = Date.now() - t0;
    // links: a bare address without the punctuation after it, an address in code stays code, an address Zotero
    // cannot open keeps its tooltip and no target, and an address in a link's text is text
    facts.markdownLinks = h.runner.renderMarkdown(h.paneDoc, 'See https://example.org/a_b. Code `https://x.y`, a ' +
      '[file](file:///C:/x.pdf), [see https://in.link](zotero://select/library/items/ABC) and （https://zh.example/页）。' +
      '见https://arxiv.org/abs/1234的图').map(tree);
    const render = h.runner.renderMarkdown;
    h.runner.renderMarkdown = () => { throw Error('broken'); };
    facts.markdownFallback = tree(h.runner.entryNode(h.paneDoc, { kind: 'text', text: '**原文**' }));
    h.runner.renderMarkdown = render;
    // the step of a command: the furthest of several, scholium.py or the scholium command
    const commands = ['python C:/s/scholium.py extract --pdf a.pdf && python C:/s/scholium.py --config c.json --apply',
                      'scholium --config c.json --apply', 'scholium --config c.json', 'python scholium.py extract --pdf x.pdf',
                      'Get-Content D:/x/zotero-scholium/SKILL.md'];
    facts.steps = {
      claude: commands.map(c => h.runner.step({ type: 'assistant', message: { content: [{ type: 'tool_use', name: 'PowerShell', input: { command: c } }] } })),
      codex: commands.map(c => h.runner.codexStep({ method: 'item/started', params: { item: { type: 'commandExecution', command: c } } })),
    };
    facts.openings = ['```python\nprint(1)\n```', '| 页 | 条数 |\n|---|---|\n| 5 | 1 |', '## 结论\n内容', '\n\n**粗体** 开头', '---\n'].map(t => h.runner.opening(t));
  }
  {
    // formulas: TeX set as MathML by KaTeX (the plugin's copy); prices, escapes and code stay text; what KaTeX
    // cannot read stays as written; only MathML elements and attributes are kept
    const h = harness();
    const texOf = n => (n.tagName === 'annotation' ? n._text : n.children.map(c => (c.tagName ? texOf(c) : '')).join(''));
    const mtree = n => (n && n.tagName === 'math' ? 'math' + (n.attrs.display === 'block' ? '[block]' : '') + ':' + texOf(n)
      : n && n.tagName ? [n.tagName + (n.className ? '.' + n.className : ''), ...(n.children.length ? n.children.map(mtree) : n._text ? [n._text] : [])]
      : n.textContent);
    const r = t => h.runner.renderMarkdown(h.paneDoc, t).map(mtree);
    const names = (n, out = new Set()) => { if (n.tagName) { out.add(n.tagName); n.getAttributeNames().forEach(a => out.add('@' + a)); n.children.forEach(c => names(c, out)); } return out; };
    facts.formulas = {
      inline: r('a $x^2$ b'),
      parens: r('复杂度 \\(O(n \\log n)\\)'),
      block: r('$$\n\\frac{a}{b}\n$$'),
      brackets: r('\\[ \\sum_{i=1}^n i \\]'),
      inParagraph: r('see $$E=mc^2$$ here'),
      text: r('price $5 and $10, \\$3, \\*not em\\*, `$x$`'),
      unreadable: r('bad $\\frac{a}{$ end'),
      unclosed: r('$$\nx\n\ntext'),
      structure: tree(h.runner.renderMarkdown(h.paneDoc, '$x^2$')[0].children[0]),
      href: [...names(h.runner.renderMarkdown(h.paneDoc, '$\\href{javascript:alert(1)}{y}$')[0])].sort(),
      loads: h.log.scripts,
    };
    const katex = h.runner.katex();
    const render = katex.renderToString;
    let renders = 0;
    katex.renderToString = (...a) => { renders++; return render.apply(katex, a); };
    const one = h.runner.mathNode(h.paneDoc, 'z^3', false), again = h.runner.mathNode(h.paneDoc, 'z^3', false);
    facts.formulas.cached = { distinct: one !== again, same: JSON.stringify(tree(one)) === JSON.stringify(tree(again)), loads: h.log.scripts, renders };
    // what KaTeX writes passes through the cleaning
    katex.renderToString = () => '<span class="katex"><math onclick="x()"><mi>x</mi><a href="javascript:x()">y</a></math></span>';
    const dirty = h.runner.mathNode(h.paneDoc, 'dirty', false);
    facts.formulas.dirty = { attrs: dirty.attrs, children: dirty.children.map(c => c.tagName) };
    katex.renderToString = render;
    // what is not MathML is left out
    const math = new El('math');
    math.setAttribute('display', 'block');
    math.setAttribute('onclick', 'x()');
    const mi = new El('mi');
    mi.setAttribute('mathvariant', 'normal');
    mi.setAttribute('style', 'color: red');
    const link = new El('a');
    link.setAttribute('href', 'javascript:x()');
    math.append(mi, link);
    h.runner.cleanMath(math);
    facts.formulas.cleaned = { attrs: math.attrs, children: math.children.map(c => [c.tagName, c.attrs]) };
    // without KaTeX the source stays
    h.runner.katexLib = null;
    h.runner.mathCache.clear();
    facts.formulas.withoutKatex = r('a $y^2$ b');
  }
  {
    // another version's sheet, left by a copy that a plugin update left running, is replaced; a copy that
    // stops leaves the sheet and the labels of a newer one
    const h = harness();
    const doc = h.runner.windows()[0].document;
    const old = doc.createElementNS('', 'link');
    old.id = 'scholium-style';
    old.setAttribute('href', 'chrome://scholium-0-1-6/content/scholium.css');
    doc.documentElement.append(old);
    h.runner.start('x');
    const sheets = () => doc.documentElement.children.filter(c => c.id === 'scholium-style').map(c => c.attrs.href);
    const replaced = sheets();
    doc.documentElement.children.find(c => c.id === 'scholium-style').setAttribute('href', 'chrome://scholium-0-1-9/content/scholium.css');
    const ftl = h.log.ftl.length;
    h.runner.stop();
    facts.sheets = { replaced, oldRemoved: old.removed, afterStop: sheets(), labelsRemoved: h.log.ftl.slice(ftl).includes('removed') };
  }
  {
    // a profile that cannot be read is not overwritten; a failed save keeps the sheet and the text
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, readFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const box = h.sheet().children[0];
    const [, panes, foot] = box.children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    key(box, { key: 's', ctrlKey: true }); await settle(20);
    facts.profileUnreadable = { status: status.textContent, error: status.className.includes('error'), inputDisabled: input.disabled,
                                saveDisabled: save.disabled, file: h.log.writes[PROFILE_PATH] === PROFILE, dirs: h.log.madeDirs.length };
  }
  {
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, writeFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    const box = h.sheet().children[0];
    const [, panes, foot] = box.children;
    const [input] = panes.children;
    const [status, , , save] = foot.children;
    input.type(input.value + '- x\n');
    save.click(); await settle(20);
    facts.profileWriteFailed = { status: status.textContent, error: status.className.includes('error'), open: !!h.sheet(),
                                 saveDisabled: save.disabled, kept: input.value.endsWith('- x\n') };
    // Esc, and yes to discarding: closed after one question
    key(box, { key: 'Escape' });
    facts.profileDiscarded = { open: !!h.sheet(), confirms: h.log.confirms.slice() };
  }
  {
    // the window closes, or the plugin shuts down: the sheet goes without asking
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE }, confirm: false });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    profileFrom(p.pane()); await settle(20);
    h.sheet().children[0].children[1].children[0].type('changed');
    h.runner.removeFromWindow(h.paneWin);
    const unloaded = { open: !!h.sheet(), focusListeners: (h.paneWin.listeners.focus || []).length };
    profileFrom(p.pane()); await settle(20);
    h.sheet().children[0].children[1].children[0].type('changed');
    h.runner.stop();
    facts.profileShutdown = { unloaded, open: !!h.sheet(), confirms: h.log.confirms.length };
  }

  // existing scholium annotations: confirm, and refusal starts nothing
  {
    const { runner, log, item1 } = harness({ existing: [['zotero-scholium'], ['zotero-scholium'], ['mine']], confirm: false });
    await runner.annotate([item1]); await settle(50);
    facts.refused = { confirms: log.confirms, calls: log.calls.length };
  }
  {
    const { runner, log, item1 } = harness({ existing: [['zotero-scholium'], ['mine']], confirm: true, locale: 'en-US' });
    await runner.annotate([item1]); await settle(300);
    facts.redo = { calls: log.calls.length, prompt: log.stdin[0], erased: log.erased.slice(), confirms: log.confirms };
  }

  // failure: is_error result, non-zero exit
  {
    const failing = SCRIPT.slice(0, 3).concat([ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'scholium.py: style_warnings remain' })]);
    const h = harness({ script: failing, exitCode: 1 });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]); await settle(300);
    facts.failure = { notices: h.log.notices.map(notice), notifications: h.log.notifications,
                      last: p.view('annotate').flat.filter(untimed).at(-1), state: p.view('annotate').state };
  }

  // cancel while running, from the item pane
  {
    const h = harness({ script: SCRIPT.slice(0, 3).concat(['WAIT']) });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const done = h.runner.annotate([h.item1]);
    await settle(80);
    p.pane().tabAnnotate.click();
    facts.whileRunning = { view: p.view() };
    p.pane().send.click();
    await done; await settle(80);
    facts.cancel = { kills: h.log.kills, current: h.runner.current, last: p.view().flat.filter(untimed).at(-1), view: p.view(),
                     notices: h.log.notices.map(notice), notifications: h.log.notifications.map(n => n.title) };
  }

  // queue: status while the first paper runs, duplicates ignored, the second follows
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1, h.item2, h.att1]);
    await h.runner.annotate([h.item2]);
    await settle(80);
    p1.pane().tabAnnotate.click(); p2.pane().tabAnnotate.click();
    facts.queueWhileFirstRuns = { calls: h.log.calls.length, queued: h.runner.queue.length, alerts: h.log.alerts.length,
                                  pane1: p1.view(), pane2: p2.view() };
    h.log.calls[0].proc.kill();
    await settle(500);
    facts.queueDone = { calls: h.log.calls.length, prompts: h.log.stdin.map(s => (s.match(/附件 key：(\w+)/) || [])[1]),
                        notifications: h.log.notifications.map(n => n.title), pane2: p2.view() };
  }
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const p2 = await h.pane(h.item2);
    await h.runner.annotate([h.item1]);
    await settle(60);
    p2.pane().tabAnnotate.click();
    facts.otherRunning = { state: p2.view().state, kind: p2.view().stateKind };
    h.log.calls[0].proc.kill();
    await settle(200);
  }
  {
    const { runner, log, item1, item2 } = harness({ gateFirst: true });
    await Promise.all([runner.annotate([item1]), runner.annotate([item2])]);
    await settle(80);
    facts.raceWhileFirstStarts = { calls: log.calls.length, queued: runner.queue.length };
    log.calls[0].proc.kill();
    await settle(500);
    facts.raceDone = log.calls.length;
  }

  // deleting scholium annotations: only the tool's tag, after a confirmation, never a running paper
  {
    const existing = [['zotero-scholium'], ['zotero-scholium', 'personal'], ['mine'], ['zotero-marginalia'], []];
    const h = harness({ existing, notes: [['zotero-scholium'], ['mine'], [], ['zotero-scholium', 'reading']] });
    h.runner.start('x');
    const removed = await h.runner.removeAnnotations([h.item1, h.att1, h.note]);
    facts.deleted = { removed, erased: h.log.erased, remaining: h.att1.getAnnotations().map(a => a.key), confirms: h.log.confirms,
                      notice: notice(h.log.notices.at(-1)), trashed: h.log.trashed, notesLeft: h.item1.getNotes() };
    const again = await h.runner.removeAnnotations([h.item1]);
    facts.deleteNothingLeft = { removed: again, alerts: h.log.alerts };
  }
  {
    // only the tool's note is left: it goes as well
    const h = harness({ notes: [['zotero-scholium']], locale: 'en-US', secondPdf: true });
    h.runner.start('x');
    facts.deleteNoteOnly = { removed: await h.runner.removeAnnotations([h.item2, h.item1]), trashed: h.log.trashed, erased: h.log.erased,
                             confirms: h.log.confirms, notice: notice(h.log.notices.at(-1)).descriptions };
  }
  {
    const h = harness({ existing: [['zotero-scholium']], confirm: false });
    facts.deleteRefused = { removed: await h.runner.removeAnnotations([h.item1]), erased: h.log.erased,
                            remaining: h.att1.getAnnotations().length };
  }
  {
    const h = harness({ existing: [['zotero-scholium']], eraseFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    facts.deleteFails = { removed: await h.runner.removeAnnotations([h.item1]), notice: notice(h.log.notices.at(-1)),
                          state: p.view('annotate').state, kind: p.view('annotate').stateKind };   // the tab of Delete annotations
  }
  {
    // a second PDF of the paper is free, but the paper's notes stay while its first PDF runs
    const h = harness({ existing: [['zotero-scholium']], gateFirst: true, notes: [['zotero-scholium']], secondPdf: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(60);
    h.att1.getAnnotations = () => [h.ann('W0', 'highlight', '#ffd400')];   // written by the run
    const before = [h.log.erased.length, h.log.trashed.length];
    facts.deleteWhileRunning = { removed: await h.runner.removeAnnotations([h.item1]), erased: h.log.erased.slice(before[0]),
                                 trashed: h.log.trashed.slice(before[1]), alerts: h.log.alerts,
                                 paneButtons: { annotate: p.view().annotateDisabled, remove: p.view().removeDisabled } };
    h.log.calls[0].proc.kill();
    await settle(200);
  }

  // no PDF, Claude missing, preferences, home directory sources
  {
    const { runner, log, note } = harness();
    await runner.annotate([note]); await settle(20);
    facts.noPdf = { alerts: log.alerts, calls: log.calls.length };
  }
  {
    const h = harness({ claudeExists: false });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]); await settle(80);
    facts.noClaude = { calls: h.log.calls.length, modelCalls: h.log.modelCalls.length, notices: h.log.notices.map(notice),
                       notifications: h.log.notifications.map(n => n.title), last: p.view('annotate').flat.filter(untimed).at(-1), models: p.view().models,
                       state: p.view('annotate').state };
  }
  {
    const { runner, log, item1 } = harness({ prefs: { 'extensions.scholium.claudeModel': 'claude-sonnet-5-5',
      'extensions.scholium.claudePermissionMode': 'dontAsk' } });
    runner.start('x');
    await runner.annotate([item1]); await settle(300);
    facts.prefArgs = log.calls[0].opts.arguments;
  }
  {
    const h = harness({ prefs: { 'extensions.scholium.claudeModel': 'claude-sonnet-5-5' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    facts.customModelOptions = p.view().models;
  }
  {
    const { runner, log, item1 } = harness({ claudeAt: '/home/u/.local/bin/claude.exe' });
    await runner.annotate([item1]); await settle(300);
    facts.localClaude = log.calls.map(c => c.opts.command);
    facts.defaults = log.calls.map(c => [c.opts.arguments[c.opts.arguments.indexOf('--model') + 1],
                                         c.opts.arguments[c.opts.arguments.indexOf('--effort') + 1]]);
  }
  for (const home of ['env', 'none']) {
    const { runner, log, item1 } = harness({ home });
    await runner.annotate([item1]); await settle(300);
    const args = log.calls.length ? log.calls[0].opts.arguments : null;
    facts['home_' + home] = { calls: log.calls.length, addDir: args && args.includes('--add-dir') ? args[args.indexOf('--add-dir') + 1] : null,
                              notifications: log.notifications.map(n => n.title) };
  }

  // the last line of a run as notices show it
  facts.brief = ['高亮 47 条（核心 13 条），页边批注 24 条，笔记《Cooperative robotic exploration of a planetary skylight surface (v2, 2026-10-04)》，剩余警告：附件未包含补充材料。',
                 '28 highlights (12 core), 9 margin notes, the note title, remaining warnings: none.',
                 '28 highlights (12 core), 9 margin notes, note “Attention, revisited”, remaining warnings: none.',
                 '高亮 30 条（核心 10 条），页边批注 12 条，笔记《A》，剩余警告：第 4 页“label”警告已接受。',
                 '30 highlights (10 core), 12 margin notes, note "A", remaining warnings: "label" accepted.',
                 '高亮 47 条（核心 13 条）；页边批注 24 条；笔记《X》；剩余警告：无。',
                 '高亮 30 条，页边批注 24 条，剩余警告：《指南》未引用。',
                 '28 highlights (12 core), 9 margin notes, reading note “X, Y”, remaining warnings: none.',
                 '第 5 页的译文已缩短；无剩余警告。', 'a'.repeat(60), '']
    .map(s => harness().runner.brief(s));

  // Codex: the newest of its copies; a configured path as it is; versions in order
  {
    const h = harness();
    facts.codexFound = { path: await h.runner.findCodex(), asked: h.log.versionCalls.slice() };
    const later = harness({ codex: { versions: Object.assign({}, CODEX_VERSIONS, { [CODEX_NPM]: 'codex-cli 0.161.0\n' }) } });
    facts.codexFound.npmNewer = await later.runner.findCodex();
    const h2 = harness({ prefs: { 'extensions.scholium.codexPath': '/custom/codex.exe' },
                         codex: { versions: { '/custom/codex.exe': 'codex-cli 0.1.0\n' } } });
    facts.codexConfigured = { path: await h2.runner.findCodex(), asked: h2.log.versionCalls.length };
    const h3 = harness({ prefs: { 'extensions.scholium.codexPath': '/custom/missing.exe' } });
    facts.codexConfiguredMissing = await h3.runner.findCodex();
    facts.codexNewer = [[[0, 160, 0, ''], [0, 160, 0, '-alpha.3']], [[0, 160, 0, '-alpha.3'], [0, 160, 0, '']], [[0, 161, 0, ''], [0, 160, 9, '']],
                        [[0, 9, 0, ''], [0, 10, 0, '']], [[1, 0, 0, ''], [0, 99, 99, '']], [[0, 160, 0, ''], [0, 160, 0, '']]]
      .map(([a, b]) => h.runner.newer(a, b));
    facts.shellCommands = ['"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command \'python a.py\'', "/bin/bash -lc 'ls -la'",
                           'pwsh.exe -NoProfile -Command "Get-Content x"', 'python a.py', '"C:\\x\\other.exe" -c \'x\'', "pwsh -Command 'it''s'"]
      .map(c => h.runner.shellCommand(c));
    facts.codexReset = [null, { primary: { usedPercent: 50, resetsAt: 100 } },
                        { primary: { usedPercent: 100, resetsAt: 100 }, secondary: { usedPercent: 100, resetsAt: 200 } },
                        { primary: { usedPercent: 100, resetsAt: 0 }, secondary: { usedPercent: 99, resetsAt: 300 } }].map(l => h.runner.codexReset(l));
  }

  // Codex chosen in the section: its models, asked from codex app-server; each agent keeps its own choices
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1), other = await h.pane(h.item2);
    await settle(40);
    p.pane().agent.change('codex');
    await settle(200);
    const v = p.view();
    const proc = h.log.codexProcs[0];
    const call = h.log.codexCalls[0];
    facts.codexModels = { agent: h.store.get('extensions.scholium.agent'), shown: p.pane().agent.value, otherShown: other.pane().agent.value,
                          agents: p.pane().agent.children.map(o => [o.value, o.textContent]),
                          models: v.models, labels: v.modelLabels, model: v.model, efforts: v.efforts, effort: v.effort,
                          call: { command: call.command, args: call.arguments, workdir: call.workdir }, sent: proc.sent.map(m => m.method),
                          hello: proc.sent[0].params, killed: proc.killed, secretKept: JSON.stringify(h.runner.models).includes('secret-token'),
                          calls: h.log.codexCalls.length };
    p.pane().model.change('gpt-5.5');
    p.pane().effort.change('max');                 // not a level of GPT-5.5
    facts.codexModels.legacy = { efforts: p.view().efforts, effort: p.view().effort };
    p.pane().model.change('gpt-6-luna');
    p.pane().effort.change('high');
    facts.codexModels.chosen = { model: h.store.get('extensions.scholium.codexModel'), effort: h.store.get('extensions.scholium.codexEffort'),
                                 claudeModel: h.store.get('extensions.scholium.claudeModel') || null,
                                 claudeEffort: h.store.get('extensions.scholium.claudeEffort') || null, otherModel: other.pane().model.value };
    p.pane().agent.change('claude');
    await settle(40);
    facts.codexModels.back = { model: p.view().model, effort: p.view().effort, labels: p.view().modelLabels.slice(0, 2) };
    p.pane().agent.change('codex');
    await settle(40);
    facts.codexModels.again = { model: p.view().model, effort: p.view().effort, calls: h.log.codexCalls.length };
  }

  // a Codex annotation and a follow-up in its thread; then Claude Code chosen, the paper having no conversation, starts
  // one, given nothing of Codex's annotation session; Codex chosen again shows it, and its session goes on in its thread
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex', 'extensions.scholium.codexModel': 'gpt-6-luna',
                                 'extensions.scholium.codexEffort': 'high' }, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW, CODEX_FOLLOW] },
                        logs: { '/data/tmp/scholium/c.json': '{}' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    const before = h.log.codexCalls.length;
    const grown = [];   // the pieces of messages as Codex writes them
    const grow = h.runner.growDraft;
    h.runner.growDraft = function (piece, block) { grown.push([piece, block]); return grow.call(this, piece, block); };
    await h.runner.annotate([h.item1]);
    await settle(500);
    p.pane().tabAnnotate.click();                  // the annotation's tab
    facts.codexDraft = { grown, left: h.runner.draft };
    const call = h.log.codexCalls[before];
    const sent = h.log.codexProcs[before].sent;
    const req = m => sent.find(x => x.method === m);
    const logPath = convs(h)[0];
    const lines = () => h.log.writes[logPath].trim().split('\n').map(l => JSON.parse(l));
    const turn = req('turn/start').params;
    facts.codexRun = {
      call: { command: call.command, args: call.arguments, workdir: call.workdir, env: call.environment, append: call.environmentAppend },
      methods: sent.filter(m => typeof m.method === 'string').map(m => m.method),
      skillLists: sent.filter(m => m.method === 'skills/list').map(m => m.params.cwds),
      roots: req('skills/extraRoots/set').params.extraRoots,
      thread: req('thread/start').params,
      turn: Object.assign({}, turn, { input: turn.input.map(i => (i.type === 'text' ? { type: 'text', elements: i.text_elements } : i)) }),
      prompt: turn.input[0].text,
      answers: sent.filter(m => m.method === undefined),
      dirs: h.log.madeDirs.slice(),
      entries: p.view().flat, state: p.view().state, stateTitle: latestNote(h).title,
      logged: lines().filter(l => l.subtype !== 'run').map(l => l.method || l.type), init: lines().find(l => l.type === 'system'), result: lines().find(l => l.type === 'result'),
      killed: h.log.codexProcs[before].killed, session: own(await h.runner.readLog('ATT1', p.view().shownConv)).session,
      notices: h.log.notices.map(notice), sendShown: !p.view().sendHidden, claudeCalls: h.log.calls.length, ring: p.view().ring, ctxUsed: p.view().ctxUsed,
      userMessages: lines().filter(l => l.params && l.params.item && l.params.item.type === 'userMessage').length,
      applied: JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/applied.json']).config,
    };
    logFrom(p.pane());
    facts.codexRun.revealed = h.log.revealed.slice();
    p.pane().input.value = '第 5 页那条译文改短';
    for (const f of p.pane().input.listeners.input) f({});
    p.pane().send.click();
    await settle(500);
    const sent2 = h.log.codexProcs.at(-1).sent;
    facts.codexFollowUp = { claudeCalls: h.log.calls.length, methods: sent2.filter(m => typeof m.method === 'string').map(m => m.method),
                            resume: sent2.find(m => m.method === 'thread/resume').params, input: sent2.find(m => m.method === 'turn/start').params.input,
                            effort: sent2.find(m => m.method === 'turn/start').params.effort, state: noteOf(h),
                            disabled: sent2.find(m => m.method === 'turn/start').params.disabledPluginIds,
                            entries: p.view().flat.slice(-5), results: lines().filter(l => l.type === 'result').length,
                            markers: lines().filter(l => l.type === 'scholium' && l.subtype === 'prompt').map(l => l.text) };
    // Claude Code chosen: the chat keeps what it showed (none: Codex's run was an annotation session); its question starts
    // the paper's conversation, which knows nothing of the annotation session
    const codexLog = h.log.writes[logPath];
    p.pane().tabChat.click();
    const unswitched = p.view().shownConv;
    p.pane().agent.change('claude');
    await settle(100);
    const switched = { entries: p.view().flat, shownConv: p.view().shownConv, newChatDisabled: p.view().newChatDisabled, ring: p.view().ring,
                       placeholder: p.view().placeholder, chosen: 'chat' in JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/conversations/index.json']), unswitched };
    p.pane().input.type('它和 FNO 比怎么样？');
    p.pane().send.click();
    await settle(500);
    const args = h.log.calls.at(-1).opts.arguments;
    const chatConv = p.view().shownConv;
    facts.switchedToClaude = { switched, calls: h.log.calls.length, resumed: args.includes('--resume'), prompt: h.log.stdin.at(-1),
                               conversations: convs(h).map(c => c.split('/').pop().split('-')[0]), codexKept: h.log.writes[logPath] === codexLog };
    // Codex chosen again: the chat keeps the paper's conversation, Claude Code's answer in it, which History lists; the
    // Annotations tab shows Codex's annotation session, which goes on in its thread
    p.pane().agent.change('codex');
    await settle(200);
    const again = { same: !!chatConv && p.view().shownConv === chatConv, asked: p.view().flat.some(e => /^scholium-entry prompt/.test(e[0]) && e[1].includes('它和 FNO 比怎么样？')),
                    info: p.view().flat.filter(e => e[0] === 'scholium-entry info').length };
    p.pane().historyButton.click();
    await settle(100);
    const rows = p.view().historyRows;
    h.runner.closePopover(p.pane());
    p.pane().tabAnnotate.click();
    await settle(20);
    const opened = { shownConv: p.view().shownConv === logPath.split('/').pop().replace('.jsonl', ''), historyRows: p.view().historyRows,
                     entries: p.view().flat.length, placeholder: p.view().placeholder };
    p.pane().input.type('再短一点');
    p.pane().send.click();
    await settle(500);
    const sent3 = h.log.codexProcs.at(-1).sent;
    const turn3 = sent3.find(m => m.method === 'turn/start');
    facts.switchedBack = { again, rows, opened, methods: sent3.map(m => m.method).filter(m => typeof m === 'string' && m.startsWith('thread/')),
                           threadId: (sent3.find(m => m.method === 'thread/resume') || { params: {} }).params.threadId,
                           text: turn3 && turn3.params.input[0].text, skill: !!(turn3 && turn3.params.input.some(i => i.type === 'skill')),
                           runs: lines().filter(l => l.type === 'scholium' && l.subtype === 'run').map(l => [l.agent, l.user]),
                           conversations: convs(h).length };
  }

  // a Codex step by step: the skill, then the extraction, while the turn runs; cancelling interrupts the turn
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT.slice(0, 7).concat(['WAIT'])] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(300);
    p.pane().tabAnnotate.click();
    const during = [p.view().state, p.view().stateTitle.split(' · ')[0]];
    p.pane().send.click();
    await settle(300);
    const proc = h.log.codexProcs.at(-1);
    const logged = convLines(h);
    facts.codexCancel = { during, interrupt: proc.sent.find(m => m.method === 'turn/interrupt').params, killed: proc.killed,
                          last: p.view().flat.filter(untimed).at(-1), state: p.view().state, results: logged.filter(l => l.type === 'result').length,
                          waits: h.live(), current: h.runner.current };
  }
  {
    // the turn has begun with the skill: its first step; shutting down does not wait for the turn to end
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT.slice(0, 2).concat(['WAIT'])] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(300);
    facts.codexCancel.begun = [p.view('annotate').state, p.view('annotate').stateTitle.split(' · ')[0]];
    h.runner.stop();
    facts.codexCancel.shutdown = h.log.codexProcs.at(-1).killed;
    await settle(100);
  }
  {
    // the agent's connection drops and it tries again: the state line says so until the agent answers again
    const reconnecting = note('error', { error: { message: 'Reconnecting... 2/5', codexErrorInfo: { responseStreamDisconnected: { httpStatusCode: null } },
                                                  additionalDetails: 'request timed out' }, willRetry: true, threadId: 'T1', turnId: 'TURN' });
    const states = {};
    for (const [name, script] of [['codex', CODEX_SCRIPT.slice(0, 2).concat([reconnecting, 'WAIT'])],
                                  ['codexBack', CODEX_SCRIPT.slice(0, 2).concat([reconnecting, CODEX_SCRIPT[3], 'WAIT'])]]) {
      const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [script] } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await h.runner.annotate([h.item1]);
      await settle(300);
      states[name] = { state: p.view('annotate').state, entries: p.view('annotate').flat.map(e => e[1]) };
      h.runner.stop();
      await settle(100);
    }
    const retry = ev({ type: 'system', subtype: 'api_retry', attempt: 1, max_retries: 10, retry_delay_ms: 600, error_status: 529,
                       error: 'overloaded', session_id: 'S1' });
    const h = harness({ script: [SCRIPT[0], retry, 'HOLD', said('接着读全文。'), 'WAIT'] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(300);
    states.claude = { state: p.view('annotate').state };
    h.log.release();
    await settle(200);
    states.claudeBack = { state: p.view('annotate').state };
    h.runner.stop();
    await settle(100);
    facts.reconnecting = states;
  }
  {
    // the skill in Codex's own skills folder: no extra root; no skill at all: the run ends before a conversation opens
    const found = {};
    for (const skillAt of ['/data/tmp/scholium', null]) {
      const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { skillAt } });
      h.runner.start('x');
      await h.runner.annotate([h.item1]);
      await settle(400);
      const sent = h.log.codexProcs.at(-1).sent;
      const turn = sent.find(m => m.method === 'turn/start'), thread = sent.find(m => m.method === 'thread/start');
      found[skillAt || 'none'] = { methods: sent.filter(m => typeof m.method === 'string').map(m => m.method).filter(m => m.startsWith('skills/')),
                                   input: turn ? turn.params.input.slice(1) : null, model: thread ? 'model' in thread.params : null,
                                   outcome: (latestNote(h) || {}).text, log: convText(h) || undefined };
    }
    facts.codexSkillFound = found;
  }

  // the Codex usage limit: the queue waits until the window resets, then the thread continues
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_LIMIT, CODEX_FOLLOW] } });
    h.runner.start('x');
    const p1 = await h.pane(h.item1);
    await h.runner.annotate([h.item1, h.item2]);
    await settle(400);
    facts.codexLimit = { clock: h.runner.paused && h.runner.clock(h.runner.paused.codex.until), expected: h.runner.clock(CODEX_RESET * 1000 + 60000),
                         known: h.runner.paused && h.runner.paused.codex.known,
                         queue: h.runner.queue.map(j => [j.att.key, j.agent, j.resume || null]), notifications: h.log.notifications.map(n => n.title),
                         last: p1.view('annotate').flat.filter(untimed).at(-1), state: p1.view('annotate').state };
    h.fire();
    await settle(900);
    const resumed = h.log.codexProcs.find(c => c.sent.some(m => m.method === 'thread/resume'));
    facts.codexLimit.after = { resume: resumed.sent.find(m => m.method === 'thread/resume').params.threadId,
                               prompt: resumed.sent.find(m => m.method === 'turn/start').params.input[0].text,
                               turns: h.log.codexTurns, state: p1.view('annotate').state, cards: p1.view('annotate').flat.filter(e => e[0].startsWith('scholium-card')), paused: h.runner.paused };
  }

  // Codex failing: a failed turn; a refused request; no Codex at all
  {
    const failing = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }),
                     coItem('completed', { type: 'agentMessage', id: 'a1', text: '先提取句子。' }),
                     shell('c1', 'python C:/skills/scholium.py extract --pdf x.pdf'),
                     shell('c1', 'python C:/skills/scholium.py extract --pdf x.pdf', { output: '412 sentences' }),
                     turnDone({ status: 'failed', error: { message: 'stream disconnected before completion',
                                                           codexErrorInfo: { responseStreamDisconnected: { httpStatusCode: 502 } } } })];
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [failing] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(400);
    facts.codexFailed = { entries: p.view('annotate').flat.filter(untimed).slice(-2), state: p.view('annotate').state, paused: h.runner.paused,
                          notices: h.log.notices.map(notice), turns: h.log.codexTurns, queue: h.runner.queue.length };
  }
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex', 'extensions.scholium.codexModel': 'gpt-9' },
                        codex: { fail: 'thread/start', failMessage: 'model gpt-9 is not available' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(400);
    facts.codexRefused = { last: p.view('annotate').flat.filter(untimed).at(-1), state: p.view('annotate').state, killed: h.log.codexProcs.at(-1).killed, turns: h.log.codexTurns };
  }
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { versions: {} } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]);
    await settle(100);
    facts.noCodex = { codexCalls: h.log.codexCalls.length, last: p.view('annotate').flat.filter(untimed).at(-1), state: p.view('annotate').state, models: p.view().models,
                      labels: p.view().modelLabels };
  }

  // the connection fails before the agent used a tool: one more try after a wait, then success or failure
  {
    const ROUTING = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }),
                     turnDone({ status: 'failed', error: { message: 'workspace routing discovery timed out', codexErrorInfo: 'other' } })];
    const DISCONNECTED = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }),
                          turnDone({ status: 'failed', error: { message: 'stream disconnected before completion',
                                                                codexErrorInfo: { responseStreamDisconnected: { httpStatusCode: 502 } } } })];
    const retry = {};
    for (const [name, first, second] of [['ok', ROUTING, CODEX_SCRIPT], ['again', DISCONNECTED, ROUTING]]) {
      const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [first, second] } });
      h.runner.NET_RETRY_MS = 60000;
      h.runner.start('x');
      const p = await h.pane(h.item1);
      await h.runner.annotate([h.item1], { extra: '只标注方法部分' });
      await settle(400);
      p.pane().tabAnnotate.click();
      const v = p.view();
      const waiting = { state: v.state, kind: v.stateKind, stopShown: v.round[0] === '■', last: v.flat.filter(untimed).slice(-2), queue: h.runner.queue.map(j => [j.att.key, !!j.retried]),
                        job: h.runner.job, notices: h.log.notices.length, notifications: h.log.notifications.length, turns: h.log.codexTurns };
      h.runner.queue[0].retryAt = 0;
      await new Promise(r => setTimeout(r, 60));
      await settle(600);
      const lines = convLines(h);
      retry[name] = { waiting, turns: h.log.codexTurns, state: p.view().state, cards: p.view().flat.filter(e => e[0].startsWith('scholium-card')), queue: h.runner.queue.length,
                      marks: lines.filter(l => l.type === 'scholium' && !['run', 'time'].includes(l.subtype)).map(l => l.subtype), inits: lines.filter(l => l.type === 'system').length,
                      runs: lines.filter(l => l.subtype === 'run').map(l => [l.agent, l.user]),
                      entries: p.view().flat.slice(0, 4), notifications: h.log.notifications.map(n => n.title) };
    }
    // cancelling while the paper waits for its second try
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [ROUTING] } });
    h.runner.NET_RETRY_MS = 60000;
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]);
    await settle(400);
    p.pane().tabAnnotate.click();
    p.pane().send.click();
    await new Promise(r => setTimeout(r, 30));
    await settle(200);
    retry.cancelled = { queue: h.runner.queue.length, turns: h.log.codexTurns, last: p.view().flat.filter(untimed).at(-1), draining: h.runner.draining };
    // a refusal is not the connection: no second try
    const refused = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN' } }),
                     turnDone({ status: 'failed', error: { message: 'unauthorized', codexErrorInfo: 'unauthorized' } })];
    const h2 = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [refused] } });
    h2.runner.start('x');
    await h2.runner.annotate([h2.item1]);
    await new Promise(r => setTimeout(r, 60));
    await settle(400);
    retry.refused = { turns: h2.log.codexTurns, queue: h2.runner.queue.length };
    // Claude Code: an API connection error before any tool, then a run
    const h3 = harness({ scripts: [[SCRIPT[0], ev({ type: 'result', subtype: 'success', is_error: true, result: 'API Error: Connection error.', session_id: 'S1' })],
                                   SCRIPT.concat([LAST, RESULT])] });
    h3.runner.NET_RETRY_MS = 60000;
    h3.runner.start('x');
    const p3 = await h3.pane(h3.item1);
    await h3.runner.annotate([h3.item1]);
    await settle(300);
    const claudeWaiting = { state: p3.view('annotate').state, calls: h3.log.calls.length };
    h3.runner.queue[0].retryAt = 0;
    await new Promise(r => setTimeout(r, 60));
    await settle(500);
    retry.claude = { waiting: claudeWaiting, calls: h3.log.calls.length, cards: p3.view('annotate').flat.filter(e => e[0].startsWith('scholium-card')),
                     resumed: h3.log.calls[1].opts.arguments.includes('--resume'), prompts: h3.log.stdin.length };
    // Claude Code had used a tool: no second try
    const h4 = harness({ scripts: [SCRIPT.slice(0, 4).concat([ev({ type: 'result', subtype: 'success', is_error: true, result: 'API Error: Connection error.' })])] });
    h4.runner.start('x');
    await h4.runner.annotate([h4.item1]);
    await new Promise(r => setTimeout(r, 60));
    await settle(400);
    retry.claudeActed = { calls: h4.log.calls.length, queue: h4.runner.queue.length };
    facts.retry2 = retry;
    facts.transient = [['workspace routing discovery timed out', 'other'], ['x', { httpConnectionFailed: { httpStatusCode: null } }],
                       ['API Error: 529 overloaded', null], ['API Error: 500 Internal server error', null], ['error sending request for url', null],
                       ['unauthorized', 'unauthorized'], ['style_warnings remain', null], ['exit 1', null]]
      .map(([m, i]) => h.runner.transient(m, i));
  }

  // the logs of an earlier version, one per agent, are conversations of the paper: the chosen agent's is shown, also when
  // the other one is newer, and each is its agent's
  {
    const codexLog = [CODEX_INIT].concat(CODEX_SCRIPT.filter(l => l.includes('item/')), [CODEX_RESULT]).join('');
    const claudeLog = SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('');
    const shown = {};
    for (const agent of ['codex', 'claude']) {
      const other = agent === 'codex' ? 'claude' : 'codex';
      const h = harness({ logs: { '/data/tmp/scholium/ATT1/claude-run.jsonl': claudeLog, '/data/tmp/scholium/ATT1/codex-run.jsonl': codexLog },
                          logTimes: { [`/data/tmp/scholium/ATT1/${agent}-run.jsonl`]: 1000, [`/data/tmp/scholium/ATT1/${other}-run.jsonl`]: 2000 },
                          prefs: { 'extensions.scholium.agent': agent } });
      h.runner.start('x');
      const p = await h.pane(h.item1);
      logFrom(p.pane());
      shown[agent] = { first: p.view().flat[0], count: p.view().flat.length, state: p.view().state, shownConv: p.view().shownConv,
                       session: own(await h.runner.readLog('ATT1', p.view().shownConv)).session, revealed: h.log.revealed[0],
                       title: await h.runner.convTitle('ATT1', p.view().shownConv) };
    }
    facts.latestLog = shown;
  }

  // an unchanged log is parsed once; one that grew is parsed again
  {
    const h = harness({ logs: { [CONV1]: SCRIPT.slice(0, 4).concat([LAST, RESULT]).join('') }, logTimes: { [CONV1]: 1 } });
    h.runner.start('x');
    let parsed = 0;
    const entries = h.runner.entries.bind(h.runner);
    h.runner.entries = event => { parsed++; return entries(event); };
    const id = 'claude-20261001-120000';
    // a run that ended well without a word: its answer is none, not an unfinished one
    const quiet = await harness({ logs: { [CONV1]: JSON.stringify({ type: 'scholium', subtype: 'run', agent: 'claude', user: '只写入' }) + '\n' + SCRIPT[0]
                                                   + ev({ type: 'result', subtype: 'success', is_error: false, result: '', session_id: 'S1' }) } }).runner.readLog('ATT1', id);
    facts.quietTurn = quiet.turns;
    const first = (await h.runner.readLog('ATT1', id)).entries.length, once = parsed;
    const again = (await h.runner.readLog('ATT1', id)).entries.length, unchanged = parsed - once;
    h.log.writes[CONV1] += said('one more');   // the same time stamp: the size tells
    const after = (await h.runner.readLog('ATT1', id)).entries.length;
    facts.logCache = { first, again, unchanged, after, reparsed: parsed - once - unchanged };
  }

  // an update during a pause for the usage limit: the new copy waits for the same reset; a paper waiting for its second
  // try keeps waiting; a paper whose agent has not answered to its prompt yet is handed over as it was queued
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
    h.runner.start('x');
    await h.runner.annotate([h.item1, h.item2]);
    await settle(300);
    const until = h.runner.paused && h.runner.paused.claude.until;
    h.runner.stop(true);
    const carried = h.store.get('extensions.scholium.carryOver');
    const h2 = harness({ prefs: { 'extensions.scholium.carryOver': carried } });
    h2.runner.start('x', true);
    await settle(300);
    const r = harness({ prefs: { 'extensions.scholium.carryOver': JSON.stringify({ jobs: [{ key: 'ATT1', libraryID: 1, agent: 'claude',
                                                                                              retried: true, retryAt: Date.now() + 600000 }] }) } });
    r.runner.start('x', true);
    await settle(200);
    const n = harness({ script: [SCRIPT[0], 'WAIT'] });   // the conversation has begun, the agent has not answered yet
    n.runner.start('x');
    await n.runner.annotate([n.item1], { extra: '只标方法部分' }); await settle(100);
    n.runner.stop(true);
    const handed = JSON.parse(n.store.get('extensions.scholium.carryOver')).jobs[0];
    facts.carriedPause = { paused: h2.runner.paused && { until: h2.runner.paused.claude.until, known: h2.runner.paused.claude.known }, until, calls: h2.log.calls.length,
                           queue: h2.runner.queue.map(j => [j.att.key, j.resume || null]), waits: h2.live(),
                           retry: { calls: r.log.calls.length, queued: r.runner.queue.map(j => [j.att.key, !!j.retried, j.retryAt > Date.now()]) },
                           undelivered: [handed.resume, handed.extra, !!handed.updated] };
    for (const x of [h2, r]) x.runner.stop();   // the waits end with them
  }
  // Codex that cannot list its skills, lists them with errors, or has the skill switched off: the run ends with what Codex said
  {
    const said = {};
    for (const [name, codex] of [['failed', { fail: 'skills/list', failMessage: 'invalid type: integer' }],
                                 ['errors', { skillAt: null, skillErrors: [{ path: '/home/u/.codex/skills/x/SKILL.md', message: 'invalid YAML' }] }],
                                 ['off', { skillAt: '/data/tmp/scholium', skillOff: true }]]) {
      const c = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex });
      c.runner.start('x');
      await c.runner.annotate([c.item1]); await settle(400);
      said[name] = [c.runner.transcript.filter(e => e.kind !== 'time').at(-1).text, (latestNote(c) || {}).text.slice(0, 2)];
      c.runner.stop();
    }
    facts.codexSkillIssues = said;
  }

  // the agent's words in a corner notice are text: Zotero would turn <a …>…</a> into a link with its attributes
  {
    const h = harness();
    h.runner.notice({ att: null, title: 't' }, 'done <a onmouseover="x()">here</a>\nnext', false);
    facts.noticeMarkup = h.log.notices.at(-1).descriptions;
  }
  // the prompt names the profile when there is one, and says to use the defaults when there is none
  {
    const h = harness({ logs: { [PROFILE_PATH]: PROFILE } });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(300);
    const en = harness({ locale: 'en-US' });
    en.runner.start('x');
    await en.runner.annotate([en.item1]); await settle(300);
    facts.profilePrompt = { zh: h.log.stdin[0], en: en.log.stdin[0] };
  }
  // Claude Code without the skill: the run ends at its start
  {
    const h = harness({ script: [ev({ type: 'system', subtype: 'init', model: 'claude-opus-5-5', session_id: 'S1', skills: ['other', 'x:y'] }), 'WAIT'] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]); await settle(200);
    const lines = convLines(h);
    facts.noSkill = { kills: h.log.kills, last: p.view('annotate').flat.filter(untimed).at(-1), state: p.view('annotate').state, end: lines.at(-2) };
    const ok = harness({ script: [ev({ type: 'system', subtype: 'init', model: 'm', session_id: 'S1', skills: ['zotero-scholium:zotero-scholium'] }),
                                  LAST, RESULT] });
    ok.runner.start('x');
    await ok.runner.annotate([ok.item1]); await settle(200);
    facts.pluginSkill = { kills: ok.log.kills, state: (latestNote(ok) || {}).text };
  }
  // an update while a paper runs: its log records the interruption, and the new copy continues the paper's
  // conversation, then the paper still waiting; a disabled plugin hands nothing over
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await h.runner.annotate([h.item2]);
    await settle(80);
    h.runner.stop(true);
    await settle(40);
    const logPath = convs(h)[0];
    const carried = h.store.get('extensions.scholium.carryOver');
    const h2 = harness({ prefs: { 'extensions.scholium.carryOver': carried }, logs: ours(h) });
    h2.runner.start('x', true);
    const p2 = await h2.pane(h2.item1);
    await settle(600);
    const h3 = harness({ logs: ours(h) });
    h3.runner.start('x');
    const history = await h3.pane(h3.item1);
    const d = harness({ gateFirst: true });
    d.runner.start('x');
    await d.runner.annotate([d.item1]); await settle(80);
    d.runner.stop(false);
    await settle(40);
    // Zotero starts the new copy of an update with ADDON_INSTALL (it has forgotten the old version by then); a
    // hand-over that no copy took is dropped when Zotero starts
    const stale = harness({ prefs: { 'extensions.scholium.carryOver': carried } });
    stale.runner.start('x');
    await settle(200);
    facts.reasons = { takingOver: [1, 2, 3, 4, 5, 6, 7, 8].filter(r => h.takingOver(r)), replacing: [1, 2, 3, 4, 5, 6, 7, 8].filter(r => h.replacing(r)),
                      staleDropped: stale.store.get('extensions.scholium.carryOver'), staleRuns: stale.log.calls.length };
    facts.update = { kills: h.log.kills, end: JSON.parse(h.log.writes[logPath].trim().split('\n').at(-1)), carried: JSON.parse(carried),
                     prompts: h2.log.stdin, resume: h2.log.calls[0].opts.arguments.includes('--resume'),
                     cleared: h2.store.get('extensions.scholium.carryOver'), entries: p2.view('annotate').flat.map(e => e[1]),
                     history: history.view('annotate').state, historyLast: history.view('annotate').flat.filter(untimed).at(-1), conversations: convs(h2).length,
                     disabled: { carried: d.store.get('extensions.scholium.carryOver') ?? null, end: convLines(d).at(-1).outcome } };
  }
  // a cancelled run's end is in its log, and its history shows it
  {
    const h = harness({ script: SCRIPT.slice(0, 3).concat(['WAIT']) });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const done = h.runner.annotate([h.item1]);
    await settle(80);
    p.pane().tabAnnotate.click();
    p.pane().send.click();
    await done; await settle(80);
    const later = harness({ logs: ours(h) });
    later.runner.start('x');
    facts.cancelLogged = { end: convLines(h).at(-2), time: convLines(h).at(-1).subtype,
                           history: (await later.pane(later.item1)).view('annotate').flat.filter(untimed).at(-1) };
  }
  // the service's limit ("not your usage limit") waits as long as its message says, and says what it is
  {
    const busy = 'API Error: Server is temporarily limiting requests (not your usage limit) · 约 24 分钟后重置';
    const h = harness({ scripts: [[SCRIPT[0], ev({ type: 'rate_limit_event', session_id: 'S1', rate_limit_info: { status: 'rejected', isUsingOverage: false } }),
                                   ev({ type: 'assistant', error: 'rate_limit', session_id: 'S1', message: { content: [{ type: 'text', text: busy }] } }),
                                   ev({ type: 'result', subtype: 'success', is_error: true, result: busy, session_id: 'S1' })],
                                  SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    const started = Date.now();
    await h.runner.annotate([h.item1]); await settle(300);
    const paused = h.runner.paused && h.runner.paused.claude;
    facts.throttle = { throttled: paused && paused.throttled, known: paused && paused.known, wait: paused && paused.until - started,
                       waits: h.live(), state: p.view('annotate').state, clock: paused && h.runner.clock(paused.until), notices: h.log.notices.at(-1).descriptions };
    h.fire(); await settle(400);
    facts.throttle.after = { prompt: h.log.stdin[1], entries: p.view('annotate').flat.map(e => e[1]), paused: h.runner.paused };
    facts.resetFrom = ['约 24 分钟后重置', 'Please try again in 3 minutes.', 'try again in about 2 hours', '5 小时额度已用完', 'in 900 hours', '']
      .map(t => { const at = h.runner.resetFrom(t); return at ? Math.round((at - Date.now()) / 60000) : null; });
  }
  // papers outside My Library, and a paper whose PDF file is missing
  {
    const h = harness();
    h.runner.start('x');
    const group = Object.assign({}, h.att1, { key: 'GATT', id: 'GATT', libraryID: 2 });
    const p = await h.pane(group);
    const queued = await h.runner.annotate([group]);
    const missing = Object.assign({}, h.item2, { getBestAttachment: async () => Object.assign({}, h.att2, { getFilePathAsync: async () => null }) });
    await h.runner.annotate([missing]);
    facts.otherLibrary = { state: p.view().state, annotateDisabled: p.view().annotateDisabled, queued, alerts: h.log.alerts.slice(), calls: h.log.calls.length,
                           composerHidden: p.pane().composer.hidden, controls: [p.view().agentDisabled, p.view().historyDisabled, p.view().newChatDisabled],
                           asked: await h.runner.send(group, '这篇讲什么？') };
    facts.otherLibrary.askedMissing = [await h.runner.send(missing, '这篇讲什么？'), h.log.alerts.slice(facts.otherLibrary.alerts.length), h.log.calls.length];
  }
  // Annotate again opens a session of its own, with the words in the box as extra instructions
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.annotate([h.item1]); await settle(300);
    p.pane().tabAnnotate.click();
    p.pane().input.type('只标方法部分');
    p.annotate(); await settle(300);
    const args = h.log.calls[1].opts.arguments;
    facts.annotateInConversation = { calls: h.log.calls.length, prompt: h.log.stdin[1], resume: args.includes('--resume') ? args[args.indexOf('--resume') + 1] : null,
                                     kept: p.pane().input.value, conversations: convs(h).length,
                                     prompts: p.view().flat.filter(e => e[0] === 'scholium-entry prompt').map(e => e[1]) };
  }
  // a question about a paper without a conversation starts one that answers; Annotate opens a session of its own with
  // the words in the annotation tab's box as extra instructions, and leaves the question's conversation as it was
  {
    const reply = '用变分推断估计后验。';
    const ANSWER = [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' }),
                    tool('Skill', { skill: 'zotero-scholium' }), answer('Launching skill: zotero-scholium'), said(reply), 'HOLD',
                    ev({ type: 'result', subtype: 'success', is_error: false, result: reply, session_id: 'Q1' })];
    const marks = () => convLines(h).filter(l => l.type === 'scholium' && !['run', 'time', 'counts'].includes(l.subtype));
    const h = harness({ scripts: [ANSWER, SCRIPT.concat([LAST, RESULT]), SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const session = async (x = h) => { const id = await x.runner.currentConv('ATT1'); const log = id && await x.runner.readLog('ATT1', id); return log ? own(log, 'claude').session : null; };
    const look = () => ({ placeholder: p.view().placeholder, sendHidden: p.view().sendHidden, stop: p.view().round });
    p.pane().input.type('这篇怎么估计后验？');
    const sent = key(p.pane().input, { key: 'Enter', ctrlKey: true }).defaultPrevented;
    await settle(200);
    const during = Object.assign(look(), { state: p.view().state, cleared: p.pane().input.value });
    h.log.release();
    await settle(300);
    const asked = { sent, during, after: Object.assign(look(), { session: await session() }), state: p.view().state, args: h.log.calls[0].opts.arguments,
                    prompt: h.log.stdin[0], lines: marks(), notices: h.log.notices.map(n => n.descriptions), entries: p.view().flat.map(e => e[1]) };
    const questionLog = ours(h);
    const chatLog = h.log.writes[convs(h)[0]];
    p.pane().tabAnnotate.click();
    p.pane().input.type('重点标方法部分');
    p.annotate();
    await settle(400);
    const args1 = h.log.calls[1].opts.arguments;
    const annotated = { resume: args1.includes('--resume') ? args1[args1.indexOf('--resume') + 1] : null, prompt: h.log.stdin[1],
                        cleared: p.pane().input.value, after: Object.assign(look(), { session: await session() }), lines: marks(),
                        prompts: p.view().flat.filter(e => e[0] === 'scholium-entry prompt').map(e => e[1]),
                        chat: [p.view('chat').flat.filter(e => /^scholium-entry prompt( editable)?$/.test(e[0])).map(e => e[1]), h.log.writes[convs(h)[0]] === chatLog],
                        notices: h.log.notices.slice(asked.notices.length).map(n => n.descriptions) };
    const annotatedLog = ours(h);
    p.pane().input.type('第 5 页那条译文改短');
    p.annotate();
    await settle(400);
    const redo = { calls: h.log.calls.length, resumed: h.log.calls[2].opts.arguments.includes('--resume'), kept: p.pane().input.value,
                   lines: marks(), conversations: convs(h).length };
    // after a restart the log names the question's conversation: Annotate continues it, with the profile; a
    // conversation that went on with an annotation is one of an annotation
    const r = harness({ logs: Object.assign({ [PROFILE_PATH]: PROFILE }, questionLog) });
    r.runner.start('x');
    await r.runner.annotate([r.item1]); await settle(300);
    const shown = harness({ logs: questionLog });
    shown.runner.start('x');
    const sp = await shown.pane(shown.item1);
    await settle(100);
    const later = harness({ logs: annotatedLog });
    later.runner.start('x');
    const lp = await later.pane(later.item1);
    await settle(100);
    facts.ask = { asked, annotated, redo,
                  restarted: { resumed: r.log.calls[0].opts.arguments.includes('Q1'), prompt: r.log.stdin[0].split('\n')[0],
                               profile: r.log.stdin[0].split('\n').find(l => l.startsWith('- 画像')) },
                  shown: { placeholder: sp.view().placeholder, session: await session(shown) },
                  later: { placeholder: lp.view().placeholder, session: await session(later) } };
  }
  // the box while a question and then its annotation start, before the agent names the conversation: a question's
  // words, then a follow-up's
  {
    const reply = '用变分推断估计后验。';
    const h = harness({ holdDirs: true, scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' }),
                                                   said(reply), ev({ type: 'result', subtype: 'success', is_error: false, result: reply, session_id: 'Q1' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '这篇怎么估计后验？'); await settle(50);
    const asking = p.view().placeholder;
    h.log.releaseDir(); await settle(300);
    await h.runner.annotate([h.item1]); await settle(50);
    facts.askBox = { asking, annotating: p.view('annotate').placeholder, state: p.view('annotate').state, queued: h.runner.queue.map(j => [j.conv, !!j.annotate]) };
    h.log.releaseDir(); await settle(300);
  }
  // a follow-up in a question's conversation is not told of a configuration; an annotation there that ends before the
  // agent names the conversation leaves it one of an annotation, as its log says; with annotations of the tool the
  // question says how to list them
  {
    const reply = '用变分推断估计后验。';
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' });
    const answered = [init, said(reply), ev({ type: 'result', subtype: 'success', is_error: false, result: reply, session_id: 'Q1' })];
    const broken = [ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'Invalid API key' })];
    const h = harness({ existing: [['zotero-scholium']], scripts: [answered, answered, broken, SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '这篇怎么估计后验？'); await settle(300);
    await h.runner.send(h.att1, '那它的损失函数呢？'); await settle(300);
    await h.runner.annotate([h.item1]); await settle(300);
    const log = await h.runner.readLog('ATT1', p.view().shownConv);
    const failed = { session: own(log, 'claude').session, question: log.question, placeholder: p.view().placeholder };
    await h.runner.annotate([h.item1]); await settle(300);
    facts.askEdges = { owned: h.log.stdin[0].split('\n').find(l => l.startsWith('这篇论文已有')), followUp: h.log.stdin[1],
                       resumes: h.log.calls.map(c => c.opts.arguments.includes('--resume')), failed };
  }
  // the agent no longer has the conversation's session (deleted in Codex's app, cleaned up by Claude Code): a new one
  // goes on with it, given its turns (Codex as items of the new thread, as text when it does not take them); a
  // continuation after a limit says so and stops
  for (const inject of [true, false]) {
    // any failure to resume the thread; a Codex that does not take items
    const refuse = inject ? { 'thread/resume': 'thread T1 is archived' }
                          : { 'thread/resume': 'no rollout found for thread id T1', 'thread/inject_items': 'unknown method thread/inject_items' };
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW], newThreads: true, refuse } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    await h.runner.annotate([h.item1]); await settle(500);
    p.pane().tabAnnotate.click();                  // words on the annotation tab go to its session
    p.pane().input.type('AdLN的作用是什么');
    p.pane().send.click();
    await settle(800);
    const lines = convLines(h);
    const methods = h.log.codexProcs.slice(-2).map(c => c.sent.map(m => m.method).filter(m => typeof m === 'string' && m.startsWith('thread/')));
    const sent = h.log.codexProcs.at(-1).sent;
    const turn = sent.find(m => m.method === 'turn/start');
    const injected = sent.find(m => m.method === 'thread/inject_items');
    facts[inject ? 'goneCodex' : 'goneCodexText'] = {
      methods, marks: lines.filter(l => l.type === 'scholium' && !['run', 'time', 'counts'].includes(l.subtype)).map(l => Object.assign({}, l, { text: l.text && l.text.slice(0, 40) })),
      runs: lines.filter(l => l.subtype === 'run').map(l => l.user), items: injected && injected.params.items,
      prompt: turn && turn.params.input[0].text, skill: !!(turn && turn.params.input.some(i => i.type === 'skill')),
      entries: p.view().flat.slice(-5).map(e => [e[0], e[1].slice(0, 60)]), state: noteOf(h),
      session: own(await h.runner.readLog('ATT1', p.view().shownConv), 'codex').session, placeholder: p.view().placeholder, conversations: convs(h).length };
  }
  {
    const answer = '它是自适应层归一化。';
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), CLAUDE_GONE,
                                  [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q2' }), said(answer),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: answer, session_id: 'Q2' })]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]); await settle(300);
    await h.runner.send(h.att1, 'AdLN的作用是什么', { kind: 'annotate' }); await settle(500);
    p.pane().tabAnnotate.click();
    facts.goneClaude = { resumes: h.log.calls.map(c => c.opts.arguments.includes('--resume')), prompt: h.log.stdin[2],
                         prompts: p.view().flat.filter(e => e[0] === 'scholium-entry prompt').map(e => e[1]),
                         metas: p.view().flat.filter(e => e[0] === 'scholium-meta').map(e => e[1]),
                         info: p.view().flat.filter(e => e[0] === 'scholium-entry info').map(e => e[1]),
                         session: own(await h.runner.readLog('ATT1', p.view().shownConv), 'claude').session, state: noteOf(h),
                         finals: p.view().flat.filter(e => e[0].includes('final')).map(e => e[1]), conversations: convs(h).length };
    const e = harness({ script: [ev({ type: 'result', subtype: 'error_during_execution', is_error: true, num_turns: 0, session_id: 'S9',
                                      errors: ['Credit balance is too low'] }), 'EXIT:1'] });
    e.runner.start('x');
    const ep = await e.pane(e.item1);
    await e.runner.annotate([e.item1]); await settle(300);
    facts.goneClaude.errorsShown = { last: ep.view('annotate').flat.filter(untimed).at(-1), notice: e.log.notices.at(-1) && e.log.notices.at(-1).descriptions };
  }
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT), CLAUDE_GONE] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]); await settle(300);
    h.fire(); await settle(500);
    const lines = convLines(h);
    const later = harness({ logs: ours(h) });
    later.runner.start('x');
    const lp = await later.pane(later.item1);
    await settle(100);
    p.pane().tabAnnotate.click(); lp.pane().tabAnnotate.click();
    facts.goneStopped = { calls: h.log.calls.length, queued: h.runner.queue.length, gone: lines.find(l => l.subtype === 'gone'),
                          state: p.view().state, last: p.view().flat.filter(untimed).at(-1), session: own(await h.runner.readLog('ATT1', p.view().shownConv), 'claude').session,
                          placeholder: p.view().placeholder,
                          later: { session: own(await later.runner.readLog('ATT1', lp.view().shownConv), 'claude').session, placeholder: lp.view().placeholder } };
  }
  // a question to Codex starts a question's conversation
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_FOLLOW] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(500);
    const log = await h.runner.readLog('ATT1', p.view().shownConv);
    facts.codexQuestion = { session: own(log, 'codex').session, question: log.question, placeholder: p.view().placeholder, title: await h.runner.convTitle('ATT1', p.view().shownConv) };
  }
  // the log of an earlier version is a conversation of the paper: the agent chosen goes on with it in place, Claude Code
  // given the conversation before, Codex in its own thread
  {
    const legacy = '/data/tmp/scholium/ATT1/codex-run.jsonl';
    const codexLog = [CODEX_INIT].concat(CODEX_SCRIPT.filter(l => l.includes('item/')), [CODEX_RESULT]).join('');
    const h = harness({ logs: { [legacy]: codexLog }, codex: { scripts: [CODEX_FOLLOW] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(100);
    const claude = { placeholder: p.view().placeholder, shown: p.view().shownConv, info: p.view().flat.filter(e => e[0] === 'scholium-entry info').length };
    p.pane().input.type('AdLN的作用是什么');
    p.pane().send.click();
    await settle(400);
    claude.resumed = h.log.calls[0].opts.arguments.includes('--resume');
    claude.prompt = h.log.stdin[0].split('\n')[0];
    claude.conversations = convs(h).length;
    h.store.set('extensions.scholium.agent', 'codex');
    await h.runner.send(h.att1, '再短一点'); await settle(500);
    const sent = h.log.codexProcs.at(-1).sent;
    const lines = h.log.writes[legacy].slice(codexLog.length).trim().split('\n').map(l => JSON.parse(l));
    facts.legacyGoesOn = { claude, resume: sent.find(m => m.method === 'thread/resume').params.threadId,
                           agents: lines.filter(l => l.subtype === 'run').map(l => l.agent),
                           text: sent.find(m => m.method === 'turn/start').params.input[0].text,
                           appended: lines.filter(l => l.type === 'scholium').map(l => l.subtype), conversations: convs(h).length };
  }
  // the conversation for a new session: beyond ten exchanges the latest five whole and the earlier ones as excerpts; an
  // unfinished answer and one without text said so; a cut never splits a character
  {
    const h = harness();
    const turns = Array.from({ length: 11 }, (_, i) => ({ user: '问题 ' + (i + 1) + ' ' + 'q'.repeat(300), reply: 'x'.repeat(500), ended: '', done: true }));
    turns.push({ user: '最后', reply: '', ended: 'Invalid API key' });
    turns.push({ user: '只写入', reply: '', ended: '', done: true });
    const text = h.runner.historyText(turns);
    const items = h.runner.historyItems(turns);
    const few = h.runner.historyText(turns.slice(0, 2));
    const excerpted = n => h.runner.historyText(turns.slice(0, n)).includes('轮对话（摘录）');
    facts.historyParts = { head: text.split('\n\n')[0], summary: text.split('\n\n')[1], excerpts: (text.match(/^用户：问题 \d+/gm) || []).length,
                           whole: (text.match(/^\[第 (\d+) 轮\]/gm) || []), excerpt: text.split('\n\n')[2],
                           unfinished: text.includes('[第 12 轮]\n用户：最后\n回答（Claude Code）：（没有完成：Invalid API key）'),
                           noText: text.includes('[第 13 轮]\n用户：只写入\n回答（Claude Code）：（没有文字回答）'), end: text.split('\n\n').at(-1),
                           few: few.split('\n\n').map(b => b.split('\n')[0]), none: h.runner.historyText([]), noItems: h.runner.historyItems([]),
                           boundary: [excerpted(10), excerpted(11)],
                           items: items.map(i => [i.role, i.content[0].type, i.content[0].text.split('\n')[0].slice(0, 20)]),
                           cut: [h.runner.cut('ab\u{1d465}cd', 4), h.runner.cut('abc\u{1d465}d', 4), h.runner.cut('abc', 4)] };
  }
  // Annotate again opens a session of its own, in a new thread
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT, CODEX_SCRIPT] } });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(200);
    await h.runner.annotate([h.item1]); await settle(500);
    await h.runner.annotate([h.item1]); await settle(500);
    const sent = h.log.codexProcs.at(-1).sent;
    facts.annotateAgain = { conversations: convs(h).length, threads: sent.map(m => m.method).filter(m => typeof m === 'string' && m.startsWith('thread/')),
                            text: sent.find(m => m.method === 'turn/start').params.input[0].text.split('\n')[0],
                            runs: convLines(h).filter(l => l.subtype === 'run').map(l => l.user) };
  }
  // an update hands over a follow-up its agent has not received yet: the new copy sends it, without logging it again
  {
    const h = harness({ scripts: [SCRIPT.concat([LAST, RESULT]), [SCRIPT[0], 'WAIT']] });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]); await settle(300);
    await h.runner.send(h.att1, 'AdLN的作用是什么', { kind: 'annotate' }); await settle(150);
    h.runner.stop(true);
    const carried = h.store.get('extensions.scholium.carryOver');
    const h2 = harness({ prefs: { 'extensions.scholium.carryOver': carried }, logs: ours(h) });
    h2.runner.start('x', true);
    await settle(400);
    const job = JSON.parse(carried).jobs[0];
    const lines2 = convLines(h2);
    facts.handedFollowUp = { handed: [job.resume, job.say, !!job.conv, job.logged], resumed: h2.log.calls[0].opts.arguments.includes('--resume'),
                             prompt: h2.log.stdin[0], runs: lines2.filter(l => l.subtype === 'run').map(l => l.user),
                             prompts: lines2.filter(l => l.subtype === 'prompt').length, conversations: convs(h2).length };
    h2.runner.stop();
  }
  // a new conversation knows the paper's annotations of the tool and the configuration that wrote them; one that goes on
  // is told when another conversation rewrote them since, or that they are gone
  {
    const answered = [SCRIPT[0], said('讲的是方法。'), ev({ type: 'result', subtype: 'success', is_error: false, result: '讲的是方法。', session_id: 'S1' })];
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' },
                        codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW, CODEX_FOLLOW, CODEX_FOLLOW, CODEX_FOLLOW] }, scripts: [answered],
                        logs: { '/data/tmp/scholium/c.json': '{}' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    await h.runner.annotate([h.item1]); await settle(500);   // Codex, conversation A
    h.att1.getAnnotations = () => [h.ann('E0', 'highlight', '#ffd400'), h.ann('E1', 'highlight', '#ffd400')];   // what it wrote
    p.pane().agent.change('claude');
    await settle(100);
    await h.runner.send(h.att1, '第 3 页那条讲了什么？'); await settle(400);   // Claude Code, conversation B
    const fresh = h.log.stdin.at(-1).split('\n').find(l => /^这篇论文(已有|目前)/.test(l));
    h.store.set('extensions.scholium.agent', 'codex');
    await h.runner.send(h.att1, '再短一点', { kind: 'annotate' }); await settle(500);   // Codex, conversation A: nothing changed since
    const unchanged = h.log.codexProcs.at(-1).sent.find(m => m.method === 'turn/start').params.input[0].text;
    const applied = JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/applied.json']);
    // rewritten in another conversation before this one's last run: nothing to tell
    h.log.writes['/data/tmp/scholium/ATT1/applied.json'] = JSON.stringify(Object.assign({}, applied, { agent: 'claude', conv: 'claude-x', at: 1 }));
    await h.runner.send(h.att1, '再短一点', { kind: 'annotate' }); await settle(500);
    const older = h.log.codexProcs.at(-1).sent.find(m => m.method === 'turn/start').params.input[0].text;
    h.log.writes['/data/tmp/scholium/ATT1/applied.json'] = JSON.stringify(Object.assign({}, applied, { agent: 'claude', conv: 'claude-x',
                                                                                                         config: '/data/tmp/scholium/ATT1/b.json', at: Date.now() + 1000 }));
    await h.runner.send(h.att1, '还是太长', { kind: 'annotate' }); await settle(500);
    const rewritten = h.log.codexProcs.at(-1).sent.find(m => m.method === 'turn/start').params.input[0].text;
    h.att1.getAnnotations = () => [];
    await h.runner.send(h.att1, '重新写', { kind: 'annotate' }); await settle(500);
    const gone = h.log.codexProcs.at(-1).sent.find(m => m.method === 'turn/start').params.input[0].text;
    facts.appliedConfig = { fresh, applied: [applied.agent, applied.config, applied.conv === p.view('annotate').shownConv],
                            unchanged: unchanged.split('\n').filter(l => /上次之后|现在没有|改已经写入/.test(l)),
                            older: older.split('\n').filter(l => /上次之后|现在没有|改已经写入/.test(l)),
                            rewritten: rewritten.split('\n').filter(l => /上次之后|现在没有|改已经写入/.test(l)),
                            gone: gone.split('\n').filter(l => /上次之后|现在没有|改已经写入/.test(l)),
                            commands: ['python C:/s/scholium.py --config "D:\\x y\\c.json" --apply', "scholium --config='c.json' --apply",
                                       'scholium --config c.json', 'python scholium.py --config /abs/c.json --apply']
                              .map(c => h.runner.appliedConfig(c)) };
  }
  // an earlier version's log of two Codex turns: Codex goes on in its thread without being given its own turns
  {
    const legacy = '/data/tmp/scholium/ATT1/codex-run.jsonl';
    const log = [CODEX_INIT].concat(CODEX_SCRIPT.filter(l => l.includes('item/')), [CODEX_RESULT]).join('')
      + JSON.stringify({ type: 'scholium', subtype: 'prompt', text: '第 5 页那条译文改短' }) + '\n'
      + ev({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T1' }) + CODEX_FOLLOW.join('')
      + ev({ type: 'result', agent: 'codex', subtype: 'success', is_error: false, result: '改好了：第 5 页的译文已缩短。', session_id: 'T1' });
    const h = harness({ logs: { [legacy]: log }, prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_FOLLOW] } });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(200);
    await h.runner.send(h.att1, '再短一点'); await settle(500);
    const turn = h.log.codexProcs.at(-1).sent.find(m => m.method === 'turn/start');
    facts.legacyTwoTurns = turn && turn.params.input[0].text.split('\n')[0];
  }
  // a question that met the limit before its agent named a session is handed over by an update as a turn logged already
  {
    const limited = [ev({ type: 'assistant', error: 'rate_limit', message: { content: [{ type: 'text', text: "You've hit your limit · resets 9pm" }] } }),
                     ev({ type: 'result', subtype: 'success', is_error: true, result: "You've hit your limit · resets 9pm" })];
    const h = harness({ scripts: [limited] });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(300);
    h.runner.stop(true);
    facts.handedInterrupted = JSON.parse(h.store.get('extensions.scholium.carryOver')).jobs.map(j => [j.interrupted, j.logged]);
  }
  // a session Claude Code opened but that never had the message is not the conversation's: the next message starts a new
  // one, given the turn that did not get through
  {
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'S7' }),
                                   ev({ type: 'result', subtype: 'error_during_execution', is_error: true, num_turns: 0, session_id: 'S7', errors: ['Invalid API key'] })],
                                  SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '它和 FNO 比怎么样？'); await settle(400);
    const session = own(await h.runner.readLog('ATT1', p.view().shownConv), 'claude').session;
    await h.runner.send(h.att1, '那它的损失函数呢？'); await settle(400);
    facts.unreachedClaude = { session, resumed: h.log.calls[1].opts.arguments.includes('--resume'), prompt: h.log.stdin[1].split('\n\n').slice(1, 2),
                              conversations: convs(h).length };
  }
  // a turn that never reached its agent is not one it has seen, and a thread opened for it is not its session
  {
    const legacy = '/data/tmp/scholium/ATT1/codex-run.jsonl';
    const log = [CODEX_INIT].concat(CODEX_SCRIPT.filter(l => l.includes('item/')), [CODEX_RESULT]).join('')
      + JSON.stringify({ type: 'scholium', subtype: 'run', agent: 'codex', user: '再短一点' }) + '\n'
      + JSON.stringify({ type: 'scholium', subtype: 'prompt', text: '再短一点' }) + '\n'
      + ev({ type: 'system', subtype: 'init', agent: 'codex', model: 'gpt-6-luna', session_id: 'T9' })
      + JSON.stringify({ type: 'scholium', subtype: 'end', outcome: 'failed', text: 'turn/start refused' }) + '\n';
    const h = harness({ logs: { [legacy]: log }, prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_FOLLOW] } });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(200);
    const before = own(await h.runner.readLog('ATT1', 'codex-run')).session;
    await h.runner.send(h.att1, '还是太长'); await settle(500);
    const sent = h.log.codexProcs.at(-1).sent;
    facts.unreached = { before, thread: (sent.find(m => m.method === 'thread/resume') || { params: {} }).params.threadId,
                        text: sent.find(m => m.method === 'turn/start').params.input[0].text };
  }
  // the second try of a continuation goes on as the continuation
  {
    const h = harness({ scripts: [[SCRIPT[0]].concat(LIMIT_HIT),
                                  [SCRIPT[0], ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 500 Internal server error' })],
                                  SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '它和 FNO 比怎么样？'); await settle(300);
    h.fire(); await settle(400);
    await new Promise(r => setTimeout(r, 120));   // the second try's wait
    await settle(600);
    facts.retriedContinuation = { calls: h.log.calls.length, prompts: h.log.stdin.map(t => t.split('\n')[0]),
                                  resumes: h.log.calls.map(c => c.opts.arguments.includes('--resume')) };
  }
  // a question whose agent named no session before the usage limit is sent again as the same turn
  {
    const limited = [ev({ type: 'assistant', error: 'rate_limit', message: { content: [{ type: 'text', text: "You've hit your limit · resets 9pm" }] } }),
                     ev({ type: 'result', subtype: 'success', is_error: true, result: "You've hit your limit · resets 9pm" })];
    const h = harness({ scripts: [limited, SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(300);
    const queued = h.runner.queue.map(j => [j.interrupted, j.logged, j.resume || null]);
    h.fire(); await settle(500);
    const lines = convLines(h);
    facts.interruptedTurn = { queued, calls: h.log.calls.length, runs: lines.filter(l => l.subtype === 'run').map(l => [l.agent, l.user]),
                              prompts: lines.filter(l => l.subtype === 'prompt').length, second: h.log.stdin[1].split('\n')[0], conversations: convs(h).length };
  }
  // an agent that is missing: its new conversation fails, the other agent's stays as it was
  {
    const h = harness({ claudeExists: false, prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    await h.runner.annotate([h.item1]); await settle(500);
    const codexLog = convText(h);
    p.pane().agent.change('claude');
    await settle(100);
    await h.runner.annotate([h.item1]); await settle(300);
    facts.redoWithoutAgent = { kept: convText(h, 'ATT1', 0) === codexLog, conversations: convs(h).length, state: p.view('annotate').state,
                               chatState: p.view('chat').state, last: p.view('annotate').flat.filter(untimed).at(-1) };
  }
  // Annotate and a question for the same paper at once: one runs, the other waits behind it
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    const both = await Promise.all([h.runner.annotate([h.item1]), h.runner.send(h.item1, '这篇讲什么？')]);
    await settle(80);
    facts.askRace = { both, queued: h.runner.queue.length, calls: h.log.calls.length, prompt: h.log.stdin[0].split('\n')[0] };
    h.runner.stop();
  }
  // a paper handed over by an update and still waiting is handed over again as one an update interrupted
  {
    const carried = JSON.stringify({ jobs: [{ key: 'ATT1', libraryID: 1, agent: 'claude', resume: 'S1', updated: true }],
                                     paused: { until: Date.now() + 600000, known: true } });
    const h = harness({ prefs: { 'extensions.scholium.carryOver': carried } });
    h.runner.start('x', true);
    await settle(100);
    h.runner.stop(true);
    const job = JSON.parse(h.store.get('extensions.scholium.carryOver')).jobs[0];
    facts.handedTwice = { calls: h.log.calls.length, updated: job.updated, conv: job.conv };
  }
  // a question goes before the papers still waiting for their first run, after the questions before it
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(80);
    await h.runner.annotate([h.item2]);
    for (const k of ['ATT3', 'ATT4']) await h.runner.send(Object.assign({}, h.att1, { key: k, id: k }), '这篇讲什么？');
    facts.askOrder = h.runner.queue.map(j => j.att.key);
    h.runner.stop();
  }
  // after a question to Claude Code, Annotate with Codex chosen is a new conversation of Codex's, given nothing of the
  // question
  {
    const reply = '用变分推断估计后验。';
    const h = harness({ scripts: [[ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' }), said(reply),
                                   ev({ type: 'result', subtype: 'success', is_error: false, result: reply, session_id: 'Q1' })]],
                        codex: { scripts: [CODEX_SCRIPT] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    await h.runner.send(h.item1, '这篇怎么估计后验？'); await settle(300);
    p.pane().agent.change('codex');
    await settle(200);
    await h.runner.annotate([h.item1]); await settle(500);
    const sent = h.log.codexProcs.at(-1).sent;
    const turn = sent.find(m => m.method === 'turn/start');
    facts.askThenCodex = { claudeCalls: h.log.calls.length, threads: sent.map(m => m.method).filter(m => typeof m === 'string' && m.startsWith('thread/')),
                           placeholder: p.view('annotate').placeholder, text: turn && turn.params.input[0].text.split('\n')[0], conversations: convs(h).length,
                           entries: p.view('annotate').flat.map(e => e[1].slice(0, 30)) };
  }
  // the usage limit in a question and in an annotation: each goes on in its own session with the plain continuation; a
  // question waiting in the queue is cancelled as a question
  {
    const reply = '用变分推断估计后验。';
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' });
    const h = harness({ scripts: [[init].concat(LIMIT_HIT),
                                  [init, said(reply), ev({ type: 'result', subtype: 'success', is_error: false, result: reply, session_id: 'Q1' })],
                                  [init].concat(SCRIPT.slice(1, 3), LIMIT_HIT), SCRIPT.concat([LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '这篇怎么估计后验？'); await settle(300);
    const paused = { stop: p.view().round, queued: h.runner.queue.map(j => [j.resume || null, !!j.question, j.say]) };
    h.fire(); await settle(400);
    const session = async () => own(await h.runner.readLog('ATT1', p.view().shownConv), 'claude').session;
    const answered = { prompt: h.log.stdin[1], session: await session(), state: p.view().state };
    await h.runner.annotate([h.item1]); await settle(300);
    const annotating = { stop: p.view('annotate').round, queued: h.runner.queue.map(j => [j.resume || null, !!j.annotate]) };
    h.fire(); await settle(400);
    facts.askLimit = { paused, answered, annotating, annotatePrompt: h.log.stdin[2].split('\n')[0], continued: h.log.stdin[3],
                       resumes: h.log.calls.map(c => c.opts.arguments.includes('--resume')), session: await session(),
                       annotSession: own(await h.runner.readLog('ATT1', p.view('annotate').shownConv), 'claude').session };
  }
  // an update hands over a question not yet received with its words, and an annotation after a question as it stands:
  // before the agent answered with its whole task in a new session, after that with the plain continuation
  {
    const reply = '用变分推断估计后验。';
    const init = ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q1' });
    const ANSWERED = [init, said(reply), ev({ type: 'result', subtype: 'success', is_error: false, result: reply, session_id: 'Q1' })];
    const question = h => h.runner.send(h.item1, '这篇怎么估计后验？');
    const annotate = async h => { await question(h); await settle(300); await h.runner.annotate([h.item1]); };
    const hand = async (scripts, act) => {
      const h = harness({ scripts });
      h.runner.start('x');
      await act(h); await settle(150);
      h.runner.stop(true);
      const carried = h.store.get('extensions.scholium.carryOver');
      const job = JSON.parse(carried).jobs[0];
      const n = harness({ prefs: { 'extensions.scholium.carryOver': carried }, logs: ours(h) });
      n.runner.start('x', true);
      await settle(400);
      const out = { handed: [job.question, job.annotate, job.say, job.resume, !!job.updated], prompt: (n.log.stdin[0] || '').split('\n')[0],
                    resume: !!n.log.calls[0] && n.log.calls[0].opts.arguments.includes('--resume') };
      n.runner.stop();
      return out;
    };
    facts.askUpdate = { question: await hand([[init, 'WAIT']], question),
                        annotateSent: await hand([ANSWERED, [init, 'WAIT']], annotate),
                        annotateAnswered: await hand([ANSWERED, [init, said('先读论文。'), 'WAIT']], annotate) };
  }
  // New chat, and History: the paper's conversations by day, each opened, renamed or deleted; a deletion can be undone a
  // moment, then the log goes; the words typed to each conversation stay with it
  {
    const reply = n => [ev({ type: 'system', subtype: 'init', apiKeySource: 'none', model: 'claude-opus-5-5', session_id: 'Q' + n }), said('回答 ' + n),
                        ev({ type: 'result', subtype: 'success', is_error: false, result: '回答 ' + n, session_id: 'Q' + n })];
    const h = harness({ scripts: [reply(1), reply(2), reply(3)] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const typeIn = text => p.pane().input.type(text);
    typeIn('第一个问题'); p.pane().send.click(); await settle(300);
    const first = p.view().shownConv;
    const before = { newChatDisabled: p.view().newChatDisabled, historyDisabled: p.view().historyDisabled };
    typeIn('写给第一段对话的话');
    p.pane().newChat.click(); await settle(100);
    const fresh = { entries: p.view().flat, shownConv: p.view().shownConv, newChatDisabled: p.view().newChatDisabled, input: p.pane().input.value,
                    placeholder: p.view().placeholder, chat: JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/conversations/index.json']).chat };
    typeIn('第二个问题'); p.pane().send.click(); await settle(300);
    const second = p.view().shownConv;
    const resumedSecond = h.log.calls[1].opts.arguments.includes('--resume');
    // two conversations of yesterday and an older one, besides today's
    const old = '/data/tmp/scholium/ATT1/conversations/claude-20260901-090000.jsonl';
    h.log.writes[old] = JSON.stringify({ type: 'scholium', subtype: 'run', agent: 'claude', user: '很早的问题' }) + '\n' + SCRIPT[0];
    h.log.mtimes[old] = Date.now() - 40 * 86400000;
    h.log.mtimes[convs(h)[0]] = Date.now() - 86400000;
    p.pane().historyButton.click(); await settle(100);
    const rows = p.view().historyRows;
    // renamed: Enter keeps the new title, Esc the old one
    const rowOf = id => p.pane().popover.node.children.find(r => r.children[0] && r.children[0].title !== undefined
                                                          && r.children[0].children && r.children[0].children[0] && r.children[0].children[0].textContent.startsWith(id));
    const firstRow = rowOf('第一个问题');
    const rowButtons = firstRow.children.slice(1).map(b => [b.className, labelOf(b)]);
    firstRow.children[1].click();
    const box = firstRow.children[0];
    box.value = '估计方法';
    key(box, { key: 'Enter' }); await settle(100);
    const renamed = p.view().historyRows;
    const again = rowOf('第二个问题');
    again.children[1].click();
    again.children[0].value = '不要这个名字';
    key(again.children[0], { key: 'Escape' }); await settle(100);
    const kept = p.view().historyRows.filter(r => r[0].includes('row')).map(r => r[1]);
    // opened: the first conversation, with the words typed to it, which goes on in its session
    rowOf('估计方法').children[0].click(); await settle(200);
    const opened = { shownConv: p.view().shownConv === first, entries: p.view().flat.map(e => e[1]), input: p.pane().input.value,
                     historyOpen: p.view().historyRows !== null };
    p.pane().input.type('接着第一段');
    p.pane().send.click(); await settle(300);
    const resumedFirst = h.log.calls[2].opts.arguments[h.log.calls[2].opts.arguments.indexOf('--resume') + 1];
    const followPrompt = h.log.stdin[2];
    // deleted: the second one, then brought back; the first (shown) one, which a new conversation follows, for good
    p.pane().historyButton.click(); await settle(100);
    rowOf('第二个问题').children[2].click(); await settle(100);
    const deleting = { rows: p.view().historyRows.map(r => r[1]), files: convs(h).length, timers: h.live() };
    p.pane().popover.node.children.find(r => r.className.includes('deleted')).children[1].click(); await settle(100);
    const undone = { rows: p.view().historyRows.filter(r => r[0].includes('row')).length, timers: h.live() };
    rowOf('估计方法').children[2].click(); await settle(100);
    const deletedShown = { entries: p.view().flat, shownConv: p.view().shownConv };
    // the one shown comes back with its place, then goes for good
    p.pane().popover.node.children.find(r => r.className.includes('deleted')).children[1].click(); await settle(100);
    deletedShown.back = p.view().shownConv === first;
    rowOf('估计方法').children[2].click(); await settle(100);
    h.fire(); await settle(200);
    const afterFire = p.view().historyRows.filter(r => r[0].includes('deleted')).length;
    const index = JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/conversations/index.json']);
    facts.conversations = { afterFire, first: !!first, before, fresh, second: second !== first, resumedSecond, rows, rowButtons, renamed, kept, opened, resumedFirst, followPrompt, deleting, undone,
                            deletedShown, removed: h.log.removed.map(r => r.split('/').pop() === first + '.jsonl'),
                            files: convs(h).length, titles: Object.values(index.titles), chat: index.chat,
                            busy: null };
    // while the paper's chat runs, its conversations stay as they are
    const g = harness({ gateFirst: true });
    g.runner.start('x');
    const gp = await g.pane(g.item1);
    await g.runner.send(g.item1, '一个问题'); await settle(80);
    facts.conversations.busy = { newChat: gp.view().newChatDisabled, history: gp.view().historyDisabled, agent: gp.view().agentDisabled };
    g.log.calls[0].proc.kill(); await settle(200);
  }
  // a deleted Codex conversation's thread is archived at the next Codex run
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT, CODEX_SCRIPT], newThreads: true } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(500);
    p.pane().historyButton.click(); await settle(100);
    p.pane().popover.node.children[1].children[2].click(); await settle(100);
    h.fire(); await settle(200);
    const queued = h.store.get('extensions.scholium.codexArchive');
    await h.runner.annotate([h.item2]); await settle(500);
    const sent = h.log.codexProcs.at(-1).sent;
    facts.archived = { queued, archived: sent.filter(m => m.method === 'thread/archive').map(m => m.params.threadId),
                       order: sent.map(m => m.method).filter(m => /^(initialize|thread\/)/.test(m || '')), left: h.store.get('extensions.scholium.codexArchive') };
  }
  // the context the conversation's session takes up: live while it runs, then from its log; orange near the limit
  {
    const used = (input, read, made, out) => ev({ type: 'assistant', session_id: 'S1', message: { content: [{ type: 'text', text: '读论文。' }],
                                                                                              usage: { input_tokens: input, cache_read_input_tokens: read, cache_creation_input_tokens: made, output_tokens: out } } });
    const done = window => ev({ type: 'result', subtype: 'success', is_error: false, result: '好', session_id: 'S1',
                                modelUsage: { 'claude-opus-5-5': { contextWindow: window }, 'claude-haiku-4-5': { contextWindow: 200000 } } });
    const sub = ev({ type: 'assistant', session_id: 'S1', parent_tool_use_id: 'toolu_1', message: { content: [], usage: { input_tokens: 900000 } } });
    const h = harness({ scripts: [[SCRIPT[0], used(2, 40000, 5000, 100), sub, 'HOLD', done(1000000)], [SCRIPT[0], used(2, 700000, 110000, 900), done(1000000)]] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(200);
    await new Promise(r => setTimeout(r, 20)); await settle(50);   // a tick of the state line
    const running = p.view().ring;
    const runningLog = [!!p.view().shownConv, p.view().logDisabled];   // the new conversation's log, while its first run goes on
    h.log.release(); await settle(300);
    const after = { ring: p.view().ring, cls: p.view().ringClass };
    const later = harness({ logs: ours(h) });
    later.runner.start('x');
    const lp = await later.pane(later.item1);
    await settle(50);
    await h.runner.send(h.att1, '再详细一点'); await settle(300);
    const windowed = CODEX_FOLLOW.map(l => l.replace('"modelContextWindow":null', '"modelContextWindow":828400'));
    const codex = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT, windowed] } });
    codex.runner.start('x');
    const cp = await codex.pane(codex.item1);
    await settle(200);
    await codex.runner.annotate([codex.item1]); await settle(500);
    const codexBare = [cp.view('annotate').ring, cp.view('annotate').ctxUsed];
    await codex.runner.send(codex.att1, '再短一点', { kind: 'annotate' }); await settle(500);
    facts.gauge = { running, runningLog, after, logged: lp.view().ring, near: { ring: p.view().ring, cls: p.view().ringClass },
                    none: await (async () => { const b = harness(); b.runner.start('x'); return (await b.pane(b.item1)).view().ring; })(),
                    codex: [codexBare, cp.view('annotate').ring],
                    en: (() => { const e = harness({ locale: 'en-US' }); return [e.runner.text('contextUsed', 23, 77), e.runner.text('contextTokens', '45k', '200k')]; })() };
  }
  // when each run ended, under what it showed (an annotation's card has its own time)
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(300);
    const time = convLines(h).at(-1);
    facts.runTime = { last: p.view('chat').flat.at(-1), logged: [time.type, time.subtype, time.at > 0], shown: h.runner.clock(time.at), at: time.at,
                      read: (await h.runner.readLog('ATT1', p.view('chat').shownConv)).entries.at(-1) };
  }
  // the plugin stops before a run's line is written: nothing of it is logged, and the paper is handed over as queued
  {
    const h = harness({ holdDirs: true });
    h.runner.start('x');
    await h.pane(h.item1);
    const queued = h.runner.send(h.item1, '这篇讲什么？');
    for (let i = 0; i < 200 && !h.log.releaseDir; i++) await tick();
    h.runner.stop(true);
    h.log.releaseDir(); await queued; await settle(100);
    const job = JSON.parse(h.store.get('extensions.scholium.carryOver')).jobs[0];
    facts.stopBeforeLine = { logs: convs(h).map(c => h.log.writes[c]), handed: [job.say, job.logged, job.conv] };
  }
  // a paper with two PDFs: History lists the conversations of its best PDF only; a conversation without a line is not listed
  {
    const conv3 = '/data/tmp/scholium/ATT3/conversations/claude-20261002-120000.jsonl';
    const empty = '/data/tmp/scholium/ATT1/conversations/claude-20261003-120000.jsonl';
    const h = harness({ secondPdf: true, logs: { [CONV1]: JSON.stringify({ type: 'scholium', subtype: 'run', agent: 'claude', user: '第一份' }) + '\n' + SCRIPT[0],
                                                  [conv3]: JSON.stringify({ type: 'scholium', subtype: 'run', agent: 'claude', user: '第二份' }) + '\n' + SCRIPT[0] + said('第二份的回答'),
                                                  [empty]: '' },
                        logTimes: { [CONV1]: Date.now() - 2000, [conv3]: Date.now() - 1000, [empty]: Date.now() } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(50);
    const before = [p.view().shownKey, p.view().shownConv];
    p.pane().historyButton.click(); await settle(100);
    const rows = p.view().historyRows.map(r => r[1].replace(/\d+月\d+日 \d{2}:\d{2}|\d{2}:\d{2}/, ''));
    const keys = p.pane().keys.slice();
    p.pane().popover.node.children.find(r => r.children[0] && r.children[0].title === '第一份').children[0].click(); await settle(100);
    facts.twoPdfs = { before, keys, rows, after: [p.view().shownKey, p.view().shownConv], first: p.view().flat[0] };
    p.annotate(); await settle(300);
    facts.twoPdfs.annotated = (h.log.stdin[0] || '').match(/附件 key：(\w+)/)[1];
  }
  // the words typed while a run starts a new conversation go on with it
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(20);
    const q = p.pane();
    Object.assign(q, { live: true, shownKey: 'ATT1', shownConv: null });
    const before = h.runner.unsentKey(q);
    h.runner.unsent.set(before, '还没发的话');
    h.runner.livePanes('ATT1', 'claude-x');
    facts.livePanes = { shownConv: q.shownConv, shownPath: q.shownPath, moved: h.runner.unsent.get(h.runner.unsentKey(q)) || null,
                        left: h.runner.unsent.has(before) };
  }
  // a paper an earlier version had paused without a session is handed over as logged, in that version's log
  {
    const carried = JSON.stringify({ jobs: [{ key: 'ATT1', libraryID: 1, agent: 'codex', say: '这篇讲什么？', question: true, interrupted: true },
                                            { key: 'ATT2', libraryID: 1, agent: 'claude', extra: '只标方法' }] });
    const h = harness({ prefs: { 'extensions.scholium.carryOver': carried } });
    h.runner.draining = true;   // the queue is only looked at
    h.runner.start('x', true);
    await settle(100);
    facts.legacyHandOver = h.runner.queue.map(j => [j.att.key, j.conv, !!j.logged, !!j.annotate, !!j.asking, j.kind]);
    h.runner.queue = [];
    h.runner.draining = false;
  }
  // a switch of the agent in one section: every section keeps its paper's conversation; New chat asked for while the
  // paper runs changes nothing; a deletion not yet done when the plugin stops is done then
  {
    const conv2 = '/data/tmp/scholium/ATT2/conversations/claude-20261002-120000.jsonl';
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, gateFirst: true,
                        logs: { [CONV1]: JSON.stringify({ type: 'scholium', subtype: 'run', agent: 'claude', user: '甲' }) + '\n' + SCRIPT[0],
                                [conv2]: JSON.stringify({ type: 'scholium', subtype: 'run', agent: 'claude', user: '乙' }) + '\n' + SCRIPT[0] } });
    h.runner.start('x');
    const p1 = await h.pane(h.item1), p2 = await h.pane(h.item2);
    await settle(100);
    const before = [p1.view().shownConv, p2.view().shownConv];
    p1.pane().agent.change('claude');
    await settle(200);
    const switched = [p1.view().shownConv, p2.view().shownConv];
    // the other paper runs: New chat there does nothing
    p2.pane().input.type('丙');
    p2.pane().send.click(); await settle(100);
    const running = h.runner.job && h.runner.job.key;
    const index2 = h.log.writes['/data/tmp/scholium/ATT2/conversations/index.json'];
    await h.runner.newChat(p2.pane());
    const current = [JSON.parse(h.log.writes['/data/tmp/scholium/ATT2/conversations/index.json']).chat,
                     h.log.writes['/data/tmp/scholium/ATT2/conversations/index.json'] === index2];
    h.log.calls[0].proc.kill(); await settle(200);
    // a deletion the plugin stops in the middle of
    p1.pane().agent.change('claude');
    await settle(100);
    await h.runner.deleteConv(p1.pane(), { key: 'ATT1', id: 'claude-20261001-120000', path: CONV1, at: 0, title: '甲' });
    const pending = [h.runner.deleting.size, CONV1 in h.log.writes];
    h.runner.stop();
    await settle(100);
    facts.otherSections = { before, switched, running, current, pending, removed: !(CONV1 in h.log.writes) };
  }
  // switching the agent away and back: the paper's conversation stays, each agent going on with it; a new chat asked
  // for stays new
  {
    const h = harness({ codex: { scripts: [CODEX_FOLLOW] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    const pane = p.pane();
    pane.input.type('问题一'); pane.send.click(); await settle(400);
    const claudeConv = pane.shownConv;
    pane.agent.change('codex'); await settle(100);
    const onCodex = pane.shownConv;
    pane.input.type('问题二'); pane.send.click(); await settle(600);
    const codexConv = pane.shownConv;
    pane.agent.change('claude'); await settle(100);
    const backClaude = { conv: pane.shownConv, runs: pane.list.children.filter(c => c.className === 'scholium-run').length };
    pane.agent.change('codex'); await settle(100);
    const backCodex = pane.shownConv;
    await h.runner.newChat(pane); await settle(40);
    pane.agent.change('claude'); await settle(100);
    const claudeAfterNew = pane.shownConv;
    pane.agent.change('codex'); await settle(100);
    facts.switchBack = { claude: !!claudeConv, onCodex: onCodex === claudeConv, codex: codexConv === claudeConv,
                         backClaude: [backClaude.conv === claudeConv, backClaude.runs], backCodex: backCodex === claudeConv,
                         claudeAfterNew, newKept: pane.shownConv };
  }
  // the configuration of a write that succeeded is kept whatever the run's end; a write that was refused is not; a
  // relative configuration is the one in the output folder when it is there
  {
    const applyCall = (cmd, id) => tool('PowerShell', { command: cmd }, id);
    const overloaded = ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 529 overloaded', session_id: 'S1' });
    const h = harness({ logs: { '/data/tmp/scholium/ATT1/config.json': '{}' },
                        scripts: [[SCRIPT[0], applyCall('python s/scholium.py --config config.json --apply', 't1'), answer('{"applied": true}', false, 't1'), overloaded],
                                  [SCRIPT[0], applyCall('python s/scholium.py --config other.json --apply', 't2'), answer('Exit code 2\nstyle_warnings: 1', true, 't2'),
                                   LAST, RESULT]] });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(400);
    const kept = JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/applied.json']);
    await h.runner.annotate([h.item1]); await settle(400);
    const after = JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/applied.json']);
    facts.appliedKept = { kept: [kept.config, kept.agent], state: (latestNote(h) || {}).text, refused: after.config, at: after.at === kept.at };
    // Codex: a write whose command failed is not kept
    const failedApply = [note('turn/started', { threadId: 'T1', turn: { id: 'TURN', status: 'inProgress' } }),
                         shell('c5', 'python C:/skills/scholium.py --config c.json --apply'),
                         shell('c5', 'python C:/skills/scholium.py --config c.json --apply', { exitCode: 2, status: 'failed', output: 'style_warnings: 1' }),
                         coItem('completed', { type: 'agentMessage', id: 'a9', text: '没写入。' }), turnDone({ status: 'completed', durationMs: 1000 })];
    const c = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [failedApply] } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    facts.appliedKept.codexFailed = '/data/tmp/scholium/ATT1/applied.json' in c.log.writes;
  }
  // a follow-up an earlier version handed over: its paper's annotations counted again, its conversation a question's
  {
    const legacy = '/data/tmp/scholium/ATT1/claude-run.jsonl';
    const log = JSON.stringify({ type: 'scholium', subtype: 'prompt', text: '这篇讲什么？', question: true }) + '\n' + SCRIPT[0]
      + said('讲的是方法。') + ev({ type: 'result', subtype: 'success', is_error: false, result: '讲的是方法。', session_id: 'S1' });
    const carried = JSON.stringify({ jobs: [{ key: 'ATT1', libraryID: 1, agent: 'claude', say: '再问一句', resume: 'S1', question: false }] });
    const h = harness({ existing: [['zotero-scholium'], ['zotero-scholium']], logs: { [legacy]: log }, prefs: { 'extensions.scholium.carryOver': carried } });
    h.runner.draining = true;   // the queue is only looked at
    h.runner.start('x', true);
    await settle(100);
    facts.legacyFollowUp = h.runner.queue.map(j => [j.conv, j.own, !!j.asking, j.resume]);
    h.runner.queue = [];
    h.runner.draining = false;
  }
  // the words typed to a new conversation stay in the box when the agent changes; Undo after the deletion has begun does
  // nothing; the ring takes the window of the latest run, and a session that is gone starts again
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().input.type('写给 Claude 的话');
    p.pane().agent.change('codex'); await settle(200);
    const codexBox = p.pane().input.value;
    p.pane().agent.change('claude'); await settle(200);
    const claudeBox = p.pane().input.value;
    const g = harness({ logs: { [CONV1]: SCRIPT[0] } });
    g.runner.start('x');
    await g.pane(g.item1);
    await settle(40);
    const gp = [...g.runner.panes.values()][0];
    await g.runner.deleteConv(gp, { key: 'ATT1', id: 'claude-20261001-120000', path: CONV1, at: 0, title: 'x' });
    const finishing = g.runner.finishDelete(CONV1);
    const again = g.runner.finishDelete(CONV1);
    await g.runner.undoDelete(CONV1);
    const pendingAfterUndo = g.runner.deleting.has(CONV1);
    await finishing; await again;
    const context = [g.runner.contextAfter({ type: 'result', modelUsage: { a: { contextWindow: 200000 } } }, { used: 5, window: 1000000 }),
                     g.runner.contextAfter({ type: 'scholium', subtype: 'gone' }, { used: 5, window: 1000000 }),
                     g.runner.contextAfter({ type: 'result', modelUsage: {} }, { used: 5, window: 1000000 })];
    facts.reviewEdges = { codexBox, claudeBox, undoLate: [CONV1 in g.log.writes, g.runner.deleting.size, gp.shownConv, pendingAfterUndo, g.log.removed.length],
                          context };
  }
  // the log keeps a tool's result without Claude Code's own copy and without image data; other lines as they came
  {
    const image = { type: 'image', source: { type: 'base64', media_type: 'image/png', data: 'iVBORw0KGgo' + 'A'.repeat(500) } };
    const read = ev({ type: 'user', message: { content: [{ type: 'tool_result', tool_use_id: 'r1', content: [{ type: 'text', text: 'page 3' }, image] }] },
                      tool_use_result: { type: 'image', file: { base64: 'iVBORw0KGgo' + 'A'.repeat(500) } } });
    const h = harness({ scripts: [SCRIPT.slice(0, 4).concat([tool('Read', { file_path: 'p3.png' }, 'r1'), read, LAST, RESULT])] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]); await settle(300);
    const user = convLines(h).filter(l => l.type === 'user').at(-1);
    const parts = user.message.content[0].content;
    facts.slimLog = { copy: 'tool_use_result' in user, data: parts[1].source.data, media: parts[1].source.media_type, text: parts[0].text,
                      plain: convText(h).includes(SCRIPT[3].trim()), shown: p.view('annotate').flat.filter(e => e[0].includes('result')).at(-1)[1] };
    // Codex: the turn's diff stays out
    const diff = note('turn/diff/updated', { threadId: 'T1', turnId: 'TURN', diff: 'diff --git a/x b/x\n+line' });
    const c = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT.slice(0, -1).concat([diff, diff, CODEX_SCRIPT.at(-1)])] } });
    c.runner.start('x');
    await c.runner.annotate([c.item1]); await settle(500);
    facts.slimLog.diff = [convText(c).includes('turn/diff/updated'), convLines(c).some(l => l.type === 'result' && !l.is_error)];
  }
  // a relative configuration of a command that ran in a Windows folder is a Windows path
  {
    const h = harness({ logs: { 'D:\\Zotero\\tmp\\scholium\\sub\\config.json': '{}', 'D:\\Zotero\\tmp\\scholium\\other.json': '{}' } });
    h.runner.start('x');
    const applied = () => JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/applied.json']).config;
    await h.runner.noteApplied('ATT1', 'sub/config.json', 'codex', 'c', 'D:\\Zotero\\tmp\\scholium');
    const found = applied();
    await h.runner.noteApplied('ATT1', './other.json', 'codex', 'c', 'D:\\Zotero\\tmp\\scholium\\');
    facts.windowsConfig = [found, applied()];
  }
  // the words of a message whose agent is not found go back to the box; no conversation is started
  {
    const h = harness({ claudeExists: false });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().input.type('这篇讲什么？');
    p.pane().send.click(); await settle(300);
    facts.givenBack = { box: p.pane().input.value, conversations: convs(h).length, last: p.view().flat.at(-1)[1].slice(0, 16),
                        sendDisabled: p.view().sendDisabled, unsent: [...h.runner.unsent.values()] };
  }
  // Cancel on a paper the usage limit paused: its log and its section say it was cancelled
  {
    const h = harness({ scripts: [SCRIPT.slice(0, 3).concat(LIMIT_HIT)] });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.annotate([h.item1]); await settle(300);
    const paused = [!!h.runner.paused, h.runner.queue.length];
    p.pane().tabAnnotate.click();
    p.pane().send.click(); await settle(200);
    facts.cancelPaused = { paused, queue: h.runner.queue.length, pausedAfter: !!h.runner.paused, state: p.view().state,
                           ends: convLines(h).filter(l => l.subtype === 'end').map(l => l.outcome),
                           last: p.view().flat.filter(untimed).at(-1)[1], timed: convLines(h).at(-1).subtype };
  }
  // a second try that meets the usage limit: after the wait the run continues as any, with a second try of its own
  {
    const overloaded = ev({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'API Error: 529 overloaded', session_id: 'S1' });
    const h = harness({ scripts: [[SCRIPT[0], overloaded], [SCRIPT[0]].concat(LIMIT_HIT), [SCRIPT[0], said('接着做完了。'), RESULT]] });
    h.runner.start('x');
    await h.runner.annotate([h.item1]); await settle(200);
    await new Promise(r => setTimeout(r, 150)); await settle(400);   // the second try's wait
    const waiting = h.runner.queue[0] && [h.runner.queue[0].retried, h.runner.queue[0].retryAt];
    h.fire(); await settle(400);
    facts.pauseAfterRetry = { waiting, calls: h.log.calls.length, marks: convLines(h).filter(l => l.type === 'scholium').map(l => l.subtype) };
  }
  // the state line gives the outcome of the conversation shown
  {
    const h = harness();
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.item1, '这篇讲什么？'); await settle(300);
    const before = p.view().state;
    p.pane().newChat.click(); await settle(100);
    const fresh = p.view().state;
    p.pane().historyButton.click(); await settle(100);
    p.pane().popover.node.children.find(r => r.className.startsWith('scholium-history-row')).children[0].click(); await settle(200);
    facts.stateOfConversation = { before: before.split(' · ')[0], fresh, back: (p.view().state || '').split(' · ')[0] };
  }
  // a title being typed stays in its box when the list is drawn again
  {
    const CONV2 = '/data/tmp/scholium/ATT1/conversations/claude-20261002-120000.jsonl';
    const h = harness({ logs: { [CONV1]: SCRIPT[0], [CONV2]: SCRIPT[0] } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().historyButton.click(); await settle(100);
    const row = () => p.pane().popover.node.children.filter(r => r.className.startsWith('scholium-history-row'))[1];
    row().children[1].click();
    const box = row().children[0];
    box.value = '半截标题';
    await h.runner.renderHistory(p.pane()); await settle(20);
    const again = row().children[0];
    const kept = [again.tagName, again.value, again !== box, !!again.focused];
    for (const f of box.listeners.blur || []) f({});   // the old box, gone, keeps nothing
    await settle(50);
    key(again, { key: 'Enter' }); await settle(100);
    facts.renameKept = { kept, titles: Object.values(JSON.parse(h.log.writes['/data/tmp/scholium/ATT1/conversations/index.json']).titles),
                         renaming: p.pane().renaming };
  }
  // a paper moved to the trash while it waited is left out
  {
    const h = harness({ gateFirst: true });
    h.runner.start('x');
    await h.runner.annotate([h.item1, h.item2]); await settle(100);
    const queued = h.runner.queue.length;
    h.att2.deleted = true;
    h.runner.cancel(); await settle(300);
    facts.trashed = { queued, calls: h.log.calls.length, queue: h.runner.queue.length };
  }
  // an index that is there and cannot be read is not written over; the choices of the session stay in memory
  {
    const index = '/data/tmp/scholium/ATT1/conversations/index.json';
    const saved = JSON.stringify({ current: { claude: 'claude-20261001-120000' }, titles: { 'claude-20261001-120000': '我的标题' } });
    const unreadable = [index];
    const h = harness({ logs: { [CONV1]: SCRIPT[0], [index]: saved }, unreadable });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    p.pane().newChat.click(); await settle(100);
    const g = harness({ logs: { [CONV1]: SCRIPT[0] } });
    g.runner.start('x');
    await g.pane(g.item1); await settle(40);
    await g.runner.chooseConv('ATT1', null);
    facts.indexUnread = { kept: h.log.writes[index] === saved, shownConv: p.view().shownConv, tmp: h.log.tmpPaths,
                          written: JSON.parse(g.log.writes[index]).chat, tmpWritten: g.log.tmpPaths.includes(index + '.tmp') };
  }
  // Codex's server ending while it resumes the thread: the run fails, and the thread stays the conversation's
  {
    const h = harness({ prefs: { 'extensions.scholium.agent': 'codex' }, codex: { scripts: [CODEX_SCRIPT, CODEX_FOLLOW], newThreads: true, exitOn: 'thread/resume' } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(200);
    await h.runner.annotate([h.item1]); await settle(500);
    p.pane().tabAnnotate.click();
    p.pane().input.type('再问一句');
    p.pane().send.click(); await settle(800);
    facts.codexExit = { gone: convLines(h).filter(l => l.subtype === 'gone').length, threads: h.log.threads,
                        session: own(await h.runner.readLog('ATT1', p.view().shownConv), 'codex').session, state: noteOf(h).split(' · ')[0],
                        last: p.view().flat.filter(untimed).at(-1)[1] };
  }
  // the log of a conversation handed over without it is started again
  {
    const carried = JSON.stringify({ jobs: [{ key: 'ATT1', libraryID: 1, agent: 'claude', say: '再问一句', conv: 'claude-20261001-120000', question: true }] });
    const h = harness({ prefs: { 'extensions.scholium.carryOver': carried } });
    h.runner.start('x', true);
    await settle(400);
    facts.logGone = { calls: h.log.calls.length, logged: (h.log.writes[CONV1] || '').includes('"subtype":"run"') };
  }
  // the sections that ask for a log at once read it once, and each gets its own copy
  {
    const h = harness({ logs: { [CONV1]: SCRIPT[0] + said('你好') } });
    h.runner.start('x');
    const id = 'claude-20261001-120000';
    const [a, b] = await Promise.all([h.runner.readLog('ATT1', id), h.runner.readLog('ATT1', id)]);
    a.turns.push('changed');
    facts.sharedReading = { reads: h.log.reads.filter(r => r === CONV1).length, own: b.turns.length, entries: b.entries.length };
  }
  // a section that showed the run as it went keeps its transcript when the run ends: the earlier runs as they are
  {
    const h = harness({ script: SCRIPT.concat(['HOLD', LAST, RESULT]), logs: { [CONV1]: SCRIPT[0] + said('你好') + RESULT } });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    await settle(40);
    await h.runner.send(h.att1, '再改一处');
    for (let i = 0; i < 3000 && !h.log.release; i++) await tick();
    const first = p.pane().list.children[0];
    h.log.release(); await settle(300);
    facts.keptTranscript = { same: p.pane().list.children[0] === first, runs: p.pane().list.children.length, state: p.view().state.split(' · ')[0],
                             entries: p.view().flat.filter(untimed).length, again: (await h.pane(h.item1)).view().flat.filter(untimed).length };
  }
  // words and texts of the section in each language
  {
    const zh = harness().runner, en = harness({ locale: 'en-US' }).runner;
    facts.texts = { turns: [en.text('turns', 1), en.text('turns', 3), zh.text('turns', 1)],
                    failures: ['error_max_turns', 'error_new_kind', 'running', undefined].map(s => zh.failureText(s)),
                    exited: [zh.text('codexExited', 'boom'), en.text('codexExited', '')],
                    entry: zh.entries({ type: 'result', subtype: 'error_max_turns', is_error: true }).map(e => e.text),
                    links: ['mailto:a@b.c', 'https://x.y', 'zotero://select/items/1_X', 'file:///C:/x.pdf'].map(a => zh.LINK_SCHEMES.test(a)) };
  }
  // a failed deletion while the paper's section is on screen: its state line says so, once
  {
    const h = harness({ existing: [['zotero-scholium']], eraseFails: true });
    h.runner.start('x');
    const p = await h.pane(h.item1);
    p.pane().tabAnnotate.click(); await settle(5);
    h.see(true);
    await h.runner.removeAnnotations([h.item1]);
    facts.deleteFailsInView = { notices: h.log.notices.length, state: p.view().state, kind: p.view().stateKind };
  }
  // words of the transcript in the UI's language
  {
    const h = harness();
    facts.uiWords = { empty: h.runner.entries(JSON.parse(answer(''))).map(e => e.text),
                      declined: h.runner.codexEntries({ method: 'item/completed', params: { item: { type: 'commandExecution', status: 'declined', aggregatedOutput: '' } } })
                        .map(e => e.text),
                      exit: h.runner.text('exitCode', 3) };
  }

  process.stdout.write(JSON.stringify(facts));
})().catch(error => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    return run_scenarios(SCENARIOS, tmp_path_factory)


CLAUDE = "/appdata/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
SUMMARY = "高亮 28 条（核心 12 条），页边批注 9 条，笔记《Deep latent》，无剩余警告。"
BRIEF = "高亮 28 条（核心 12 条）\n页边批注 9 条\n无剩余警告"   # the summary in a notice
ASK = "向这篇论文提问"   # the chat's placeholder while its conversation is a question's
HISTORY_HEAD = "下面是这段对话之前的内容（Zotero 里保存的记录），每轮注明是谁回答的："   # a new session's conversation, as text
HISTORY_END = "——以上是之前的对话，新消息如下——"
CLOSING = "改了批注时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。"   # the end of a follow-up's prompt
DONE_NOTICE = ["完成 · Ns"] + BRIEF.split("\n")   # a harness run's own time, read through run_time
DONE_STATE = "完成 · 26 轮 · 2,568k tokens"   # the time is on the run's folded steps


def run_time(value):
    """A harness run's own time (a fraction of a second, which a slow machine may round up) as Ns, and the clock time
    a run ended at as HH:MM, in a string or in the strings of a list or dict; a time taken from a result, such as
    6m 17s, stays."""
    if isinstance(value, str):
        return re.sub(r"(^|· )\d{2}:\d{2}$", r"\1HH:MM", re.sub(r"(?<!m )(?<![\d.])\d+s\b", "Ns", value))
    if isinstance(value, list):
        return [run_time(v) for v in value]
    if isinstance(value, dict):
        return {k: run_time(v) for k, v in value.items()}
    return value
TOKEN_DETAIL = "输入 52 · 缓存写入 111k · 缓存读取 2,410k · 输出 47k"
STARTED = "已在后台开始，通常需要 10–20 分钟。过程和进度见条目侧栏的 Scholium 区块。"
LEVELS = ["low", "medium", "high", "xhigh", "max"]
TRANSCRIPT = [   # a run with its steps opened; the model is under it, with the time (ENDED)
    ["scholium-entry text", "先加载技能，再提取句子。"],
    ["scholium-entry tool", "⏺ Skill(zotero-scholium)"],
    ["scholium-entry result", "⎿ Launching skill: zotero-scholium"],
    ["scholium-entry tool", "⏺ PowerShell(python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json)"],
    ["scholium-entry result", "⎿ 412 sentences -> s.json\n1\n2\n3\n… +2"],
    ["scholium-entry tool", "⏺ Read(D:\\Zotero\\tmp\\scholium\\ATT1\\sentences.txt)"],
    ["scholium-entry tool", "⏺ Write(D:\\Zotero\\tmp\\scholium\\ATT1\\config.json)"],
    ["scholium-entry tool", "⏺ PowerShell(python C:/skills/scholium.py --config c.json)"],
    ["scholium-entry result error", "⎿ Exit code 2\nstyle_warnings: 1"],
    ["scholium-entry tool", "⏺ PowerShell(python C:/skills/scholium.py --config c.json --apply)"],
    ["scholium-entry result", '⎿ {"applied": true}'],
    ["scholium-entry text", "Done.\n" + SUMMARY],
]
ANNOTATE = ["scholium-entry prompt", "批注这篇"]   # the user's Annotate, as the transcript shows it
ENDED = ["scholium-meta", "Claude Code · Opus 5.5 · HH:MM"]     # the model and when a run ended, under its answer


def card(turns="26 轮 · 2,568k tokens", title="✓ 批注完成，没有剩余警告", nums=(0, 0, 0, 0, 0)):
    """A finished annotation's card on the annotation tab: its title, the numbers counted in Zotero, its turns and
    tokens and when it ended (through run_time); the harness's run leaves the paper without Scholium annotations."""
    h, core, margin, notes, reading = nums
    cls = "scholium-card"
    if not any((h, margin, notes, reading)):
        # a run that left none of the tool's annotations and notes says so
        cls += " none"
        title = "没有写入批注" if title in ("✓ 批注完成，没有剩余警告", "✓ 批注完成") else title.replace("✓ 批注完成，剩余警告：", "没有写入批注：")
    return [cls, f"{title}{h}高亮（核心\u00a0{core}）{margin}页边批注{notes}便签{reading}阅读笔记{turns} · HH:MM"]


CARD = card()
RUN = [ANNOTATE] + TRANSCRIPT + [CARD]   # an annotation on its tab: the closing words among the steps, then its card


def test_section_is_registered_and_removed_without_menus_or_toolbar_status(facts):
    assert facts["section"] == {
        "paneID": "scholium",
        "header": {"l10nID": "scholium-section", "l10nArgs": "{}", "icon": "chrome://scholium/content/icon16.svg",
                   "darkIcon": "chrome://scholium/content/icon16-dark.svg"},
        "sidenav": {"l10nID": "scholium-sidenav", "l10nArgs": "{}", "icon": "chrome://scholium/content/icon20.svg",
                    "darkIcon": "chrome://scholium/content/icon20-dark.svg"},
        "ftl": ["scholium.ftl"],
        "styles": [["link", "scholium-style", "stylesheet", "chrome://scholium/content/scholium.css"]],
    }
    assert facts["contextMenus"] == {"menus": 0, "readerListeners": ["createViewContextMenu"]}
    assert facts["stopped"] == {"sections": ["scholium-pane"], "ftl": "removed", "panes": 0, "toolbarItems": 0, "observers": 0,
                                "styles": 0}


def test_models_come_from_claude_code(facts):
    r = facts["modelRequest"]
    assert r["calls"] == 1 and r["command"] == CLAUDE and r["workdir"] == "/data" and r["stderr"] == "stdout"
    assert r["args"] == ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                         "--strict-mcp-config", "--settings", '{"disableAllHooks":true}'], "without the user's MCP servers and hooks"
    assert r["stdin"] == [{"type": "control_request", "request_id": "scholium-models", "request": {"subtype": "initialize"}}]
    assert r["closed"] is True and r["kills"] == 1 and r["accountKept"] is False
    v = facts["paneBefore"]["view"]
    assert v["models"] == ["", "opus", "fable", "haiku", "claude-opus-4-6", "claude-sonnet-4-6"] and v["model"] == "opus"
    assert v["modelLabels"] == ["Claude Code 默认（Fable 5.1）", "Opus 5.5", "Fable 5.1", "Haiku 4.5", "Opus 4.6", "Sonnet 4.6"]
    assert facts["customModelOptions"] == ["", "opus", "fable", "haiku", "claude-opus-4-6", "claude-sonnet-4-6", "claude-sonnet-5-5"]
    n = facts["noModelList"]
    assert n == {"models": ["", "claude-sonnet-5-5"], "labels": ["Claude Code 默认", "claude-sonnet-5-5"], "efforts": LEVELS,
                 "calls": 1, "kills": 1}
    assert facts["noClaude"]["modelCalls"] == 0 and facts["noClaude"]["models"] == ["", "opus"]


def test_the_latest_opus_runs_at_the_remembered_effort(facts):
    v = facts["paneBefore"]["view"]
    assert v["efforts"] == LEVELS and v["effort"] == "medium" and v["effortDisabled"] is False
    assert facts["defaults"] == [["opus", "medium"]]
    e = facts["modelEfforts"]
    assert e["first"] == {"efforts": LEVELS, "effort": "xhigh", "disabled": False}
    assert e["opus46"] == {"efforts": ["low", "medium", "high", "max"], "effort": "medium", "disabled": False}
    assert e["sonnet46"] == {"efforts": ["low", "high", "max"], "effort": "low", "disabled": False}
    assert e["haiku"] == {"efforts": [""], "effort": "", "disabled": True}
    assert e["haikuArgs"] == {"model": "haiku", "effort": False}
    assert e["saved"] == "xhigh" and e["backToOpus"] == "xhigh"
    assert e["claudeDefault"] == {"model": "", "passed": False}
    assert facts["savedEfforts"] == {
        "xhigh": {"shown": "xhigh", "passed": "xhigh", "model": False},
        "empty": {"shown": "medium", "passed": "medium", "model": False},
        "auto": {"shown": "medium", "passed": "medium", "model": False},
    }


def test_section_offers_model_effort_and_actions(facts):
    b = facts["paneBefore"]
    assert b["enabled"] is True and b["noteEnabled"] is False
    v = b["view"]
    assert (v["annotateDisabled"], v["removeDisabled"], v["logDisabled"]) == (False, False, True)
    assert v["round"][0] != "■", "nothing runs: no stop button"
    assert v["flat"] == [] and v["state"] is None
    assert v["stateDisplay"] == "none"   # hidden by display: the attribute alone is not enough in Zotero
    assert facts["settings"] == {"model": "fable", "effort": "high", "otherModel": "fable", "otherEffort": "high"}
    args = facts["call"]["args"]
    assert args[args.index("--model") + 1] == "fable" and args[args.index("--effort") + 1] == "high"


def test_section_is_styled_by_its_stylesheet(facts):
    look = facts["look"]
    assert look["parts"] == ["scholium-tabs", "scholium-line", "scholium-view chat", "scholium-view annotate", "scholium-saved", "scholium-composer"]
    assert look["buttons"] == ["scholium-button primary small", "scholium-button quiet small", "scholium-round send"]
    assert look["tabs"] == ["scholium-tab on", "scholium-tab"]
    assert look["newChat"] == ["scholium-button quiet glyph add", "新对话"], "New chat is the add icon, its words its tooltip"
    assert look["history"] == "scholium-button quiet icon"
    assert look["selects"] == ["scholium-select"] * 3 and look["input"] == "scholium-input"
    assert look["inputNative"] == "true"   # Zotero's text-box look (a line under the text on focus) stays off
    assert look["tool"] == [["span", "scholium-bullet"], ["span", "scholium-content"]] and look["name"] == ["b", "text"]
    rules = css_rules()
    for cls in ["scholium-pane", "scholium-tabs", "scholium-tab", "scholium-tab-dot", "scholium-line", "scholium-view", "scholium-annot-intro", "scholium-chip", "scholium-icon", "scholium-popover", "scholium-menu-item", "scholium-menu-sep", "scholium-note", "scholium-field", "scholium-select", "scholium-spacer",
                "scholium-button", "scholium-state", "scholium-log", "scholium-entry", "scholium-bullet",
                "scholium-content", "scholium-composer", "scholium-input", "scholium-send-row", "scholium-hint", "scholium-copy",
                "scholium-markdown", "scholium-saved", "scholium-saved-item", "scholium-saved-go", "scholium-undo", "scholium-history-group", "scholium-history-row",
                "scholium-history-open", "scholium-history-title", "scholium-history-time", "scholium-history-rename",
                "scholium-history-empty", "scholium-round", "scholium-ring", "scholium-context-head", "scholium-context-bar", "scholium-context-legend",
                "scholium-run", "scholium-fold-head", "scholium-fold-body", "scholium-meta", "scholium-annot-intro-title",
                "scholium-fold-more", "scholium-card", "scholium-card-title", "scholium-card-nums", "scholium-card-usage",
                "scholium-confirm", "scholium-confirm-text"]:
        assert any(re.search(r"\." + re.escape(cls) + r"(?![\w-])", sel) for sel in rules), cls
    log = rules[".scholium-log"]
    assert "resize" not in log
    for part in ("background: var(--material-background)", "color: var(--fill-primary)", "border: var(--material-border-quarternary)",
                 "flex: 1", "overflow: auto", "min-height: 120px", "user-select: text", "contain: inline-size"):
        assert part in log, part
    # the transcript can be selected, without its bullets and buttons; an answer's copy button shows while the pointer is over its run
    assert "user-select: none" in rules[".scholium-bullet"] and "user-select: none" in rules[".scholium-copy"]
    assert 'url("copy16.svg")' in rules[".scholium-copy"] and 'url("check16.svg")' in rules[".scholium-copy.done"]
    assert all((PLUGIN / "content" / name).exists() for name in ("copy16.svg", "check16.svg"))
    assert "opacity: 0" in rules[".scholium-copy"]
    assert "opacity: 1" in rules[".scholium-run:hover .scholium-copy, .scholium-copy:focus-visible, .scholium-copy.done"]
    assert "font-size: 1.2em" in rules[".scholium-log .scholium-markdown h1"]
    assert "word-break: normal" in rules[".scholium-markdown :is(th, td)"]
    assert "display: none !important" in rules[".scholium-pane [hidden]"]
    assert "var(--accent-green)" in rules[".scholium-entry.tool .scholium-bullet"]
    assert [sel for sel, body in rules.items() if "monospace" in body] == [".scholium-entry.tool, .scholium-entry.result", "#scholium-profile-sheet .scholium-editor",
                                                                               ".scholium-markdown code"]
    assert "var(--accent-blue10)" in rules[".scholium-entry.prompt"] and "auto" in rules[".scholium-entry.prompt"]
    assert "var(--accent-blue)" in rules[".scholium-button.primary"] and "var(--accent-blue)" in rules[".scholium-tab.on"]
    assert "border-color: var(--accent-blue)" in rules[".scholium-composer:focus-within"]
    for kind, colour in (("running", "blue"), ("ok", "green"), ("error", "red"), ("paused", "orange")):
        assert f"var(--accent-{colour})" in rules[f".scholium-state.{kind}::before"], kind
    assert "animation: scholium-pulse" in rules[".scholium-state.running::before"]
    assert "var(--accent-orange)" in rules[".scholium-ring.warn"] and "conic-gradient" in rules[".scholium-ring"] and "inset: 3px" in rules[".scholium-ring::after"] and "var(--fill-primary)" in rules[".scholium-round.stop"] and "var(--accent-blue)" in rules[".scholium-round"]
    # a run: its steps folded into a line, blue with a ring while it runs; the model and the time under the answer
    assert "flex-direction: column" in rules[".scholium-run"] and "var(--accent-blue)" in rules[".scholium-fold-head.live"]
    assert "background: transparent" in rules[".scholium-fold-head"] and "var(--fill-secondary)" in rules[".scholium-fold-head"]
    assert 'content: "◌ "' in rules[".scholium-fold-head.live::before"] and "var(--fill-quinary)" in rules[".scholium-fold-body"]
    assert "space-between" in rules[".scholium-meta"] and "var(--fill-tertiary)" in rules[".scholium-meta"]
    # the annotation tab: the card (red when it failed, four numbers in a row), the question in place on a red tint, its
    # Replace in red
    assert not any("scholium-step" in sel for sel in rules), "no list of steps"
    assert "border-color: var(--accent-red)" in rules[".scholium-card.failed"] and "border: var(--material-border-quarternary)" in rules[".scholium-card"]
    assert "repeat(4, 1fr)" in rules[".scholium-card-nums"] and "font-size: 16px" in rules[".scholium-card-nums b"]
    assert "var(--accent-red)" in rules[".scholium-confirm"] and "flex: 1" in rules[".scholium-confirm-text"]
    assert "background: var(--accent-red)" in rules[".scholium-button.danger"]
    assert "text-align: center" in rules[".scholium-annot-intro"] and "font-weight: 600" in rules[".scholium-annot-intro-title"]
    assert not any("scholium-entry.time" in sel or "draft .scholium-bullet" in sel for sel in rules), "no time line, no bullet on a message"
    assert "visibility: hidden" in rules[".scholium-history-row .scholium-button.glyph"]
    assert "visibility: visible" in rules[".scholium-history-row:hover .scholium-button.glyph, .scholium-history-row:focus-within .scholium-button.glyph"], \
        "rename and delete show with the pointer or the keyboard in their row, so that Tab reaches them"
    assert "height: 22px" in rules[".scholium-tabs .scholium-button.icon"] and "height: 22px" in rules[".scholium-button.glyph"], \
        "🕘 as high as ＋ beside it"
    assert "padding: 0 4px" in rules[".scholium-queue .scholium-undo"] and "padding: 2px 4px" in rules[".scholium-queued"], \
        "the queue's Undo strip starts where its rows do"
    assert "text-overflow: ellipsis" in rules[".scholium-history-title"] and "overflow: auto" in rules[".scholium-popover.history"]
    assert "box-sizing: border-box" in rules[".scholium-popover"], "a layer's max-width (the pane's) includes its padding"
    assert "min-width: 240px" in rules[".scholium-popover.settings"]
    note = rules[".scholium-popover.settings .scholium-note"]
    assert "width: 0" in note and "min-width: 100%" in note, "the note does not widen the settings layer and its selects"


def test_transcript_box_has_its_own_look_and_no_drag(facts):
    assert facts["box"]["cls"] == "scholium-log"



def test_claude_is_started_headless_in_the_data_directory(facts):
    call = facts["call"]
    assert call["command"] == CLAUDE
    assert call["workdir"] == "/data"
    assert call["env"] == {"PYTHONIOENCODING": "utf-8"} and call["append"] is True
    args = call["args"]
    assert args[:7] == ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--permission-mode", "auto"]
    assert args[args.index("--add-dir") + 1] == "/home/u/.claude/skills/zotero-scholium"
    i = args.index("--allowedTools")
    assert args[i + 1:i + 5] == ["Skill", "Read", "Write(/data/tmp/scholium/**)", "Edit(/data/tmp/scholium/**)"]
    # the user's MCP servers and hooks stay out of the run
    assert "--strict-mcp-config" in args and json.loads(args[args.index("--settings") + 1]) == {"disableAllHooks": True}


def test_prompt_names_the_paper_and_the_unattended_rules(facts):
    prompt = facts["prompt"]
    for part in ("zotero-scholium", "条目 key：ITEM1", "附件 key：ATT1", "论文：/data/tmp/scholium/ATT1/paper.json",
                 "输出目录：/data/tmp/scholium/ATT1", "不要向用户提问", "不要启动子代理", "目前没有本工具的注释"):
        assert part in prompt, part
    assert facts["confirmsWithoutExisting"] == 0


def test_section_shows_the_transcript_like_claude_code(facts):
    a = facts["paneAfter"]
    assert run_time(a["flat"]) == RUN
    assert not any(kind.startswith("scholium-entry final") for kind, _ in a["flat"])
    # the annotation tab's state line shows runs going on or waiting; the outcome is the run's card and its folded steps,
    # not the chat's
    assert a["state"] is None and a["stateKind"] == "scholium-state info"
    assert re.fullmatch(r"已处理 \d+ 秒 ›", facts["annotOutcome"]["fold"]) and facts["annotOutcome"]["chatState"] is None
    assert a["stateDisplay"] == "none" and a["round"][0] != "■"
    assert (a["annotateDisabled"], a["logDisabled"], a["shownKey"]) == (False, False, "ATT1")
    assert run_time(facts["paneRerendered"]["flat"]) == RUN
    o = facts["otherAfter"]
    assert o["flat"] == []
    assert o["state"] is None and o["stateKind"] == "scholium-state info", "nothing of another paper's run"
    assert facts["logLines"] == 19, "the run's own line, the Annotate line, Claude Code's events, the numbers counted, when it ended"
    assert re.fullmatch(r"/data/tmp/scholium/ATT1/conversations/annotate-claude-\d{8}-\d{6}\.jsonl", facts["revealed"][0])
    c = facts["firstConversation"]
    assert c["files"] == ["/data/tmp/scholium/ATT1/conversations/annotate-claude-TIME.jsonl"]
    assert c["index"] == {"titles": {"annotate-claude-TIME": "批注这篇"}, "annotation": {"claude": "annotate-claude-TIME"}}
    assert c["applied"]["config"] == "/data/c.json" and c["applied"]["agent"] == "claude" and c["applied"]["conv"] in facts["revealed"][0]
    h = facts["history"]
    assert h["history"] is True and h["shownKey"] == "ATT1" and h["logDisabled"] is False
    assert h["flat"] == TRANSCRIPT[:3] + [TRANSCRIPT[-1], ["scholium-meta", "Claude Code · Opus 5.5"]]
    assert h["state"] == "上次：" + DONE_STATE and h["stateKind"] == "scholium-state ok" and h["sendHidden"] is False
    assert facts["historyWithoutLastMessage"] == TRANSCRIPT[:3]
    assert facts["failedHistory"] == ["scholium-entry final error", "scholium.py: style_warnings remain重试"]


def test_corner_notices_close_by_themselves(facts):
    assert run_time(facts["notices"]) == [
        {"closeOnClick": True, "errors": 0, "descriptions": [STARTED], "closeTimer": 6000, "shown": True},
        {"closeOnClick": True, "errors": 0, "descriptions": DONE_NOTICE, "closeTimer": 6000, "shown": True},
    ]
    assert facts["failure"]["notices"][-1]["errors"] == 1 and facts["failure"]["notices"][-1]["closeTimer"] == 12000
    assert facts["cancel"]["notices"][-1]["closeTimer"] == 12000


def test_a_section_on_screen_replaces_the_notices(facts):
    v = facts["inView"]
    assert (v["notices"], v["notifications"]) == (0, 0)
    # the annotation tab's state line shows runs going on or waiting; the outcome is the run's card
    assert run_time(v["card"]) == CARD and v["shown"] is None
    assert v["other"] is None and v["otherKind"] == "scholium-state info", "another paper's section shows nothing of this run"
    assert facts["unfocused"] == {"notices": 0, "notifications": [{"title": "批注完成：Paper ITEM2", "body": BRIEF}]}, \
        "in the background the system notification tells, not a corner notice"
    assert facts["collapsed"] == {"notices": 2}
    assert facts["scrolledAway"] == {"notices": 4}
    d = facts["deleteInView"]
    assert d == {"removed": 2, "notices": 0, "state": "已删除 2 条 Scholium 批注。", "kind": "scholium-state ok"}
    assert facts["otherInView"] == {"notices": 2, "notifications": []}, "only the section of the paper itself replaces the notices"
    assert facts["background"] == {"notices": 0, "notifications": [
        {"title": "批注失败：Paper ITEM1", "body": "scholium.py: style_warnings remain"}, {"title": "批注完成：Paper ITEM2", "body": BRIEF}]}


def test_section_shows_running_and_finished_state(facts):
    q = facts["queueWhileFirstRuns"]
    assert q["pane1"]["state"] == "", "the papers waiting are shown in their own sections"
    assert q["pane1"]["stateKind"] == "scholium-state running"
    assert q["pane1"]["round"] == ["■", "停止"], "the running paper has the stop button"
    assert q["pane2"]["state"] == "排队中，前面还有 1 篇" and q["pane2"]["annotateDisabled"] is True
    w = facts["whileRunning"]["view"]
    assert w["state"] == "" and w["stateKind"] == "scholium-state running"
    assert (w["annotateDisabled"], w["removeDisabled"]) == (True, True) and w["round"] == ["■", "停止"]
    assert w["flat"] == [ANNOTATE] + TRANSCRIPT[:2], "the wishes, then what it does now; no list of steps"
    assert facts["otherRunning"] == {"state": None, "kind": "scholium-state info"}, "another paper's run is not shown here"
    assert facts["finished"]["notifications"] == [], "Zotero is in front: the corner notice tells"


def test_notices_put_each_part_of_the_last_line_on_its_own_line(facts):
    assert facts["brief"] == [
        "高亮 47 条（核心 13 条）\n页边批注 24 条\n剩余警告：附件未包含补充材料",
        "28 highlights (12 core)\n9 margin notes\nthe note title\nremaining warnings: none",
        "28 highlights (12 core)\n9 margin notes\nremaining warnings: none",
        "高亮 30 条（核心 10 条）\n页边批注 12 条\n剩余警告：第 4 页“label”警告已接受",
        "30 highlights (10 core)\n12 margin notes\nremaining warnings: \"label\" accepted",
        "高亮 47 条（核心 13 条）\n页边批注 24 条\n剩余警告：无",
        "高亮 30 条\n页边批注 24 条\n剩余警告：《指南》未引用",
        "28 highlights (12 core)\n9 margin notes\nremaining warnings: none",
        "第 5 页的译文已缩短\n无剩余警告",
        "a" * 39 + "…",
        "",
    ]


def test_existing_annotations_need_confirmation(facts):
    assert facts["refused"]["calls"] == 0
    assert facts["refused"]["confirms"][0].startswith("这篇论文已有 2 条 Scholium 批注。")
    r = facts["redo"]
    assert r["calls"] == 1
    assert r["confirms"] == ["This paper already carries 1 Scholium annotation. Annotating again first deletes it; your own annotations and "
                             "notes are not affected. Continue?"]
    assert r["erased"] == ["E0"], "the confirmed redo deletes the Scholium annotation before the run, not the user's"
    assert "The paper carries no annotations of this tool yet." in r["prompt"]


def test_failure_and_cancel_are_reported(facts):
    f = facts["failure"]
    # the annotation tab: its card in red with the reason and Retry; its state line is for runs going on or waiting
    assert f["last"] == ["scholium-card failed", "scholium.py: style_warnings remain重试"]
    assert f["notifications"] == [] and f["notices"][-1]["descriptions"] == ["失败 · scholium.py: style_warnings remain"]
    assert f["state"] is None
    c = facts["cancel"]
    assert c["kills"] == 1 and c["current"] is None
    assert c["last"] == ["scholium-card failed", "已取消重试"]
    assert c["view"]["annotateDisabled"] is False and c["view"]["round"][0] != "■" and c["view"]["state"] is None
    assert c["notifications"] == [] and c["notices"][-1]["descriptions"] == ["已取消"]


def test_papers_run_one_after_another_without_duplicates(facts):
    q = facts["queueWhileFirstRuns"]
    assert (q["calls"], q["queued"], q["alerts"]) == (1, 1, 0)
    done = facts["queueDone"]
    assert done["calls"] == 2 and done["prompts"] == ["ATT1", "ATT2"]
    assert done["notifications"] == []
    assert done["pane2"]["shownKey"] == "ATT2" and run_time(done["pane2"]["flat"][-2:]) == [TRANSCRIPT[-1], CARD]
    assert done["pane2"]["state"] is None
    assert facts["raceWhileFirstStarts"] == {"calls": 1, "queued": 1}
    assert facts["raceDone"] == 2


def test_delete_removes_only_the_tools_annotations_and_notes_after_a_confirmation(facts):
    d = facts["deleted"]
    assert d["removed"] == 4 and d["erased"] == ["E0", "E1"]
    assert d["remaining"] == ["E2", "E3", "E4"]
    # the tool's notes go to the trash; the user's stay
    assert d["trashed"] == ["N0", "N3"] and d["notesLeft"] == ["N1", "N2"]
    assert d["confirms"] == ["将删除带 zotero-scholium 标签的这个 PDF 上的 2 条批注和这篇论文的 2 篇阅读笔记。"
                             "批注永久删除，不能撤销；笔记移到回收站，可以恢复。你自己的批注和笔记都保留。删除会同步。继续吗？"]
    assert d["notice"] == {"closeOnClick": True, "errors": 0, "descriptions": ["已删除 2 条 Scholium 批注，2 篇笔记已移到回收站。"],
                           "closeTimer": 6000, "shown": True}
    assert facts["deleteNothingLeft"] == {"removed": 0, "alerts": ["这个 PDF 没有 Scholium 批注，这篇论文也没有 Scholium 阅读笔记。"]}
    n = facts["deleteNoteOnly"]
    assert n["removed"] == 1 and n["trashed"] == ["N0"] and n["erased"] == []
    assert n["confirms"] == ["This deletes 1 reading note of the paper, tagged zotero-scholium. The note goes to the trash, where it "
                             "can be restored. Your own annotations and notes are kept. The deletion syncs. Continue?"]
    assert n["notice"] == ["1 note moved to the trash."]
    assert facts["deleteRefused"] == {"removed": 0, "erased": [], "remaining": 1}
    f = facts["deleteFails"]
    assert f["removed"] == 0 and f["notice"]["errors"] == 1
    assert f["notice"]["descriptions"] == ["删除失败：library is read-only"]
    assert f["state"] == "删除失败：library is read-only" and f["kind"] == "scholium-state error"


def test_delete_skips_a_paper_being_annotated(facts):
    r = facts["deleteWhileRunning"]
    assert r["removed"] == 0 and r["erased"] == [] and r["trashed"] == []
    assert r["alerts"] == ["这个 PDF 没有 Scholium 批注，这篇论文也没有 Scholium 阅读笔记。\n\n正在批注或排队的 PDF 不会删除。"]
    assert r["paneButtons"] == {"annotate": True, "remove": True}


def test_missing_pdf_missing_claude_and_preferences(facts):
    assert facts["noPdf"]["calls"] == 0 and len(facts["noPdf"]["alerts"]) == 1
    nc = facts["noClaude"]
    assert nc["calls"] == 0 and nc["notifications"] == []
    assert nc["last"][0] == "scholium-entry final error" and "Zotero 设置 → Scholium" in nc["last"][1]
    assert nc["notices"][-1]["errors"] == 1 and nc["state"] is None
    args = facts["prefArgs"]
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
    assert args[args.index("--effort") + 1] == "medium"


def test_home_directory_comes_from_the_directory_service_or_the_environment(facts):
    assert facts["localClaude"] == ["/home/u/.local/bin/claude.exe"]
    assert facts["home_env"] == {"calls": 1, "addDir": "/profile/u/.claude/skills/zotero-scholium",
                                 "notifications": []}
    assert facts["home_none"] == {"calls": 1, "addDir": None, "notifications": []}


def test_personal_profile_is_edited_as_markdown_over_the_zotero_window(facts):
    f = facts["profile"]
    assert f["button"] == {"text": "个人配置 ↗", "cls": "scholium-menu-item"}
    assert f["root"] == ["scholium-sheet-backdrop", "scholium-profile-sheet"] and f["box"] == ["scholium-sheet", "dialog", "个人配置"]
    assert f["title"] == ["scholium-sheet-title", "个人配置"]
    assert f["panes"] == ["scholium-editor-panes", "scholium-editor", "scholium-preview scholium-markdown"] and f["previewed"] == 8
    assert f["head"][0][0] == "scholium-editor-about" and "Interpretation 和 User's rules 两节保持不变" in f["head"][0][1]
    assert f["head"][1] == ["scholium-editor-path", "/data/zotero-scholium/profile.md"]
    assert f["pathTitle"] == "/data/zotero-scholium/profile.md"
    assert f["buttons"] == ["取消", "保存", "scholium-button", "scholium-button primary"]
    # the file as it is, with the line ends of the text box; nothing is written by opening it
    assert "\r" not in f["text"] and f["text"].startswith("# Annotation profile (draft")
    assert f["text"].endswith("- 颜色只有两级：红 = 核心，黄 = 其他\n")
    assert f["focused"] is True and f["unchanged"] is True and f["focusListeners"] == 1
    assert f["opened"] == {"status": "Ctrl+S 保存 · Esc 关闭", "error": False, "saveDisabled": True, "inputDisabled": False, "open": True}
    assert f["again"] == {"sheets": 1, "focused": True}
    assert f["edited"] == {"status": "有未保存的修改", "error": False, "saveDisabled": False, "inputDisabled": False, "open": True}
    # Ctrl+S saves and stays; the file keeps its CRLF line ends; the key goes no further than the sheet
    c = f["ctrlS"]
    assert c["prevented"] is True and c["stopped"] is True and c["dirs"] == ["/data/zotero-scholium"]
    assert c["saved"].endswith("\r\n- 页边批注用蓝色\r\n") and "\n" not in c["saved"].replace("\r\n", "")
    assert re.fullmatch(r"已保存 \d\d:\d\d", c["view"]["status"]) and c["view"]["saveDisabled"] is True and c["view"]["open"] is True
    # unsaved changes: Esc and Cancel ask, and a refusal keeps the sheet
    assert f["escape"]["prevented"] is True and f["escape"]["stopped"] is True and f["escape"]["view"]["open"] is True
    assert f["cancel"] == {"status": "有未保存的修改", "error": False, "saveDisabled": False, "inputDisabled": False, "open": True}
    saved = f["saved"]
    assert saved["text"].endswith("\r\n- 页边批注用蓝色\r\n- 公式不高亮\r\n") and saved["view"]["open"] is False
    assert saved["confirms"] == ["放弃未保存的修改吗？", "放弃未保存的修改吗？"]
    assert saved["focusListeners"] == 0 and saved["refocused"] is True


def test_profile_preview_shows_the_text_as_markdown_as_it_is_typed(facts):
    f = facts["profilePreview"]
    t = f["tree"]
    assert t[0] == ["h1", "Annotation profile (draft derived from the Zotero library)"]
    assert t[1] == ["p", "Based on 466 annotations on 50 papers."]
    assert t[2] == ["ul", ["li", "Colours:", ["ul", ["li", ["code", ["span.scholium-swatch[background-color: #ff6666]"], "#ff6666"], " 75%"]]]]
    assert t[3] == ["h2", "Interpretation (to be completed by the assistant from the statistics and confirmed by the user)"]
    assert t[5][0] == "h2" and t[5][1] == "User's rules (always win)"
    # the unsaved rule is in the preview
    assert t[-1] == ["ul", ["li", "高亮评论 = 中文翻译"], ["li", "颜色只有两级：红 = 核心，黄 = 其他"],
                     ["li", ["strong", "新规则"], "：", ["code", ["span.scholium-swatch[background-color: #2ea8e5]"], "#2ea8e5"], " 用于方法"]]
    # 750 of 1000 in the text box: 1500 of 2000 in the preview; 500 after typing: 1000 in the rebuilt preview
    assert f["scrolled"] == 1500 and f["scrolledAfterTyping"] == 1000
    assert f["linkOpened"] == [["https://example.org/rules"], True]
    assert facts["profilePreviewReload"] == ["ul", ["li", "高亮评论 = 中文翻译"], ["li", "颜色只有两级：红 = 核心，黄 = 其他"], ["li", "新统计"]]


def test_links_in_messages(facts):
    assert facts["markdownLinks"] == [[
        "p", "See ", ["span.scholium-link[title=https://example.org/a_b][href=https://example.org/a_b]", "https://example.org/a_b"],
        ". Code ", ["code", "https://x.y"], ", a ", ["span.scholium-link[title=file:///C:/x.pdf]", "file"], ", ",
        ["span.scholium-link[title=zotero://select/library/items/ABC][href=zotero://select/library/items/ABC]", "see ", "https://in.link"],
        " and （", ["span.scholium-link[title=https://zh.example/页][href=https://zh.example/页]", "https://zh.example/页"], "）。见",
        ["span.scholium-link[title=https://arxiv.org/abs/1234][href=https://arxiv.org/abs/1234]", "https://arxiv.org/abs/1234"], "的图"]]
    c = facts["linkClicks"]
    assert c["clicked"] == [True, False, False], "a web address opens; a file does not; nor does a click that ends a selection"
    assert c["opened"] == ["https://example.org/x", "https://example.org/x"] and c["enterPrevented"] is True


def test_markdown_preview_builds_elements_and_never_markup(facts):
    assert facts["markdown"] == [
        ["h1", "Title ", ["strong", "bold"]],
        ["p", "Para line one\nline two with ", ["code", "code"], " and ", ["em", "em"], " and ",
         ["span.scholium-link[title=https://x.y/z][href=https://x.y/z]", "link"]],
        ["h2", "Rules"],
        ["ol", ["li", "first"],
               ["li", "second", ["ul", ["li", "nested ", ["code", ["span.scholium-swatch[background-color: #ff6666]"], "#ff6666"],
                                        " red\ncontinued"]]]],
        ["ul", ["li", "other list", ["ol", ["li", "inner ordered"]]]],
        ["blockquote", ["p", "quote ", ["strong", "q"]]],
        ["pre", ["code", "<script>alert(1)</script> **not bold**"]],
        ["hr"],
        ["ol[start=3]", ["li", "starts at three\n<b>raw</b>"]],
    ]
    assert facts["markdownSubSup"] == [
        ["p", "π", ["sub", "ref"], "(y|x) and e", ["sup", ["strong", "2"]], ", <b>b</b>, <sub>open and <sub>a<sup>b</sub></sup>"],
    ]
    assert facts["markdownTable"] == [
        ["p", "Before"],
        ["table", ["thead", ["tr", ["th[text-align: center]", "a"], ["th", "b | c"], ["th[text-align: right]", "d"]]],
                  ["tbody", ["tr", ["td[text-align: center]", ["code", "x"]], ["td", "2"], ["td[text-align: right]"]],
                            ["tr", ["td[text-align: center]", "1"], ["td", "2"], ["td[text-align: right]", "3"]]]],
        ["p", "x | y\nno rule"],
        ["p", "p | q\n|---|---|---|"],
    ]


def test_markdown_that_once_hung_or_threw_now_renders(facts):
    assert facts["markdownSeparators"] == [
        [["h2", "结论"], ["p", "更多"]],
        [["ul", ["li", "一项\n续行"]]],
        [["ol", ["li", "一\n二"]]],
    ]
    assert facts["markdownSpacesMs"] < 300
    assert facts["markdownFallback"] == ["div.scholium-entry text", ["div.scholium-content scholium-markdown", "**原文**"]]


def test_formulas_are_set_as_mathml_and_the_rest_stays_text(facts):
    f = facts["formulas"]
    assert f["inline"] == [["p", "a ", "math:x^2", " b"]]
    assert f["parens"] == [["p", "复杂度 ", "math:O(n \\log n)"]]
    assert f["block"] == [["div.scholium-math", "math[block]:\\frac{a}{b}"]]
    assert f["brackets"] == [["div.scholium-math", "math[block]:\\sum_{i=1}^n i"]]
    assert f["inParagraph"] == [["p", "see ", ["span.scholium-math", "math[block]:E=mc^2"], " here"]]
    # prices are text; escaped marks are themselves; code is code
    assert f["text"] == [["p", "price $5 and $10, ", "$", "3, ", "*", "not em", "*", ", ", ["code", "$x$"]]]
    assert f["unreadable"] == [["p", "bad ", "$\\frac{a}{$", " end"]]
    assert f["unclosed"] == [["p", "$$\nx"], ["p", "text"]]
    assert f["structure"] == ["math", ["semantics", ["mrow", ["msup", ["mi", "x"], ["mn", "2"]]], ["annotation", "x^2"]]]
    # \href in untrusted TeX: no link, only MathML
    elements = {n for n in f["href"] if not n.startswith("@")}
    assert "math" in elements and elements <= {"p", "math", "semantics", "mrow", "mstyle", "mtext", "annotation", "mi", "mo", "mn"}
    assert "@href" not in f["href"]
    assert f["loads"] == 1 and f["cached"] == {"distinct": True, "same": True, "loads": 1, "renders": 1}
    assert f["dirty"] == {"attrs": {}, "children": ["mi"]}
    assert f["cleaned"] == {"attrs": {"display": "block"}, "children": [["mi", {"mathvariant": "normal"}]]}
    assert f["withoutKatex"] == [["p", "a ", "$y^2$", " b"]]


def test_the_plugin_carries_katex_and_its_license():
    katex = PLUGIN / "content" / "katex"
    assert 'version:"0.18.11"' in (katex / "katex.min.js").read_text(encoding="utf8")
    assert (katex / "LICENSE").read_text(encoding="utf8").startswith("The MIT License (MIT)")


def test_steps_and_notice_openings(facts):
    assert facts["steps"] == {"claude": ["applying", "applying", "dryRun", "extract", None],
                              "codex": ["applying", "applying", "dryRun", "extract", "skill"]}
    assert facts["openings"] == ["print(1)", "页 · 条数", "结论", "粗体 开头", ""]


def test_a_newer_copy_keeps_its_stylesheet_and_labels(facts):
    s = facts["sheets"]
    assert s["replaced"] == ["chrome://scholium/content/scholium.css"] and s["oldRemoved"] is True
    assert s["afterStop"] == ["chrome://scholium-0-1-9/content/scholium.css"] and s["labelsRemoved"] is False


def test_the_agents_markdown_is_set_and_its_source_copied(facts):
    r = facts["markdownReply"]
    assert r["tree"] == [
        "div.scholium-entry text",
        ["div.scholium-content scholium-markdown",
         ["h2", "改动"],
         ["ul", ["li", "第 5 页译文改为 ", ["strong", "更短"], " 的一句"]],
         ["table", ["thead", ["tr", ["th[text-align: left]", "页"], ["th[text-align: right]", "条数"]]],
                   ["tbody", ["tr", ["td[text-align: left]", "5"], ["td[text-align: right]", "1"]]]]],
    ]
    assert run_time(r["meta"]) == ["div.scholium-meta", ["span", "Claude Code · Opus 5.5 · HH:MM"], ["button.scholium-copy[title=复制这条回复（Markdown）]"]]
    assert r["copied"] == [r["reply"]]
    assert r["done"][:2] == ["scholium-copy done", "已复制"] and 1500 in r["done"][2]
    assert r["reset"] == ["scholium-copy", "复制这条回复（Markdown）"]
    assert r["rerendered"] is True


def test_a_reply_shows_as_it_is_written_and_a_question_is_answered(facts):
    s = facts["streamed"]
    md = ["div.scholium-content scholium-markdown", ["h2", "结论"], ["p", "用的是 ", ["strong", "SMART"], "，从头训练。"],
          ["ul", ["li", "32M 参数"]]]
    w = s["writing"]
    # two parts of one message, a blank line between them; a sub-agent's piece is left out
    assert w["draft"] == "## 结论\n\n用的是 **SMART**，从头训练。\n\n- 32M 参数"
    assert w["tree"] == w["again"] == ["div.scholium-entry text draft", md]
    assert w["againAtEnd"] is True
    assert s["whole"] == {"drafts": 0, "left": None, "running": True}   # the whole message replaces the draft at once
    assert s["done"] == ["div.scholium-entry text", md]
    assert s["drafts"] == 0 and s["left"] is None and s["streamLines"] == 0
    assert "--include-partial-messages" in s["args"] and s["args"][s["args"].index("--resume") + 1] == "S1"
    assert s["prompt"].endswith("\n\n用的什么模型？\n\n" + CLOSING)
    # nothing was written to Zotero: the notice gives the answer's opening, not a closing line
    assert s["notifications"] == [] and s["notice"][1:] == ["结论"]
    c = facts["codexDraft"]
    assert c["grown"] == [["先", "a1"]] and c["left"] is None


def test_a_cancelled_message_stays_marked_and_typed_words_stay_with_their_item(facts):
    u = facts["unfinished"]
    assert u["restored"] == "还没发出去的话"
    assert u["during"] == {"removeDisabled": True, "inputAfterSend": "", "rerenderedInput": ""}
    assert u["last"][0] == ["div.scholium-entry text",
                            ["div.scholium-content scholium-markdown", ["p", "写到一半的 ", ["strong", "回答"]],
                             ["div.scholium-unfinished", "（这条回复没有写完）"]]]
    assert u["last"][1] == ["scholium-entry final error cancelled", "已取消"]
    assert u["logged"] == u["fromLog"] == ["写到一半的 **回答**"]
    assert u["removeDisabledAfter"] is False
    assert u["durations"] == ["8s", "59s", "1m 00s", "6m 17s", "1h 02m 05s"]


def test_an_unfinished_message_comes_before_the_failure(facts):
    for agent in ("claude", "codex"):
        f = facts["failedInside"][agent]
        assert f["shown"] == ["prompt", "text", "scholium-card failed"], agent   # the message among the folded steps, then the card
        assert f["logged"] == ["unfinished", "result"], agent
        assert f["read"] == ["unfinished", "final", "time"], agent


def test_a_selection_in_the_draft_holds_it_still(facts):
    assert facts["draftSelection"] == {"held": "第一段", "after": "第一段，第二段，第三段"}


def test_a_message_in_a_conversation_goes_before_waiting_papers(facts):
    assert facts["followUpOrder"] == {
        "fresh": ["ATT1:再短一点", "ATT2", "ATT3"],
        "afterTalk": ["ATT2:早先的问题", "ATT1:再短一点", "ATT3"],
        "afterQuestion": ["ATT2:新的问题", "ATT1:再短一点", "ATT3"],
        "beforeAnnotation": ["ATT1:再短一点", "ATT2", "ATT3"],   # a follow-up for an agent without a session there
        "afterRetry": ["ATT2", "ATT1:再短一点", "ATT3"],
        "afterPause": ["ATT2", "ATT1:再短一点", "ATT3"],
        "pausedHeadCancelled": ["ATT1:再短一点", "ATT2", "ATT3"],
        "alone": ["ATT1:再短一点"],
    }
    assert facts["pausedJobs"] == {
        "question": {"say": "", "asked": True, "resume": "S2", "interrupted": False},
        "run": {"say": "", "asked": False, "resume": "S2", "interrupted": False},
        "noSession": {"asked": False, "resume": None, "interrupted": True},   # the same paper again, from the start
    }


def test_missing_profile_starts_as_the_template_and_is_written_on_saving(facts):
    c = facts["profileCreated"]
    assert c["before"]["status"] == "文件还不存在，保存后创建" and c["before"]["saveDisabled"] is False and c["before"]["written"] is False
    assert c["before"]["text"].startswith("# Annotation profile\n\n## User's rules (always win)\n\nRules recorded in this section take precedence")
    assert c["saved"] == c["before"]["text"] and c["dirs"] == ["/data/zotero-scholium"] and c["open"] is False and c["confirms"] == 0


def test_profile_changed_elsewhere_is_not_overwritten_unasked(facts):
    f = facts["profileElsewhere"]
    assert f["reloaded"].endswith("- 新统计\n") and f["keptEdits"] is True
    r = f["refused"]
    assert r["confirms"] == ["profile.md 在打开后被别处改动过（例如重新统计了文库）。用这里的内容覆盖它吗？"]
    assert r["file"].endswith("- 再次统计\n") and r["status"] == "未保存：文件已被别处改动" and r["error"] is True and r["open"] is True
    o = f["overwritten"]
    assert o["file"].endswith("- 新统计\n- 我的修改\n") and o["open"] is False and o["confirms"] == 2


def test_profile_read_and_write_failures_keep_the_file_and_the_text(facts):
    assert facts["profileUnreadable"] == {"status": "读不到个人配置文件：NotReadableError", "error": True, "inputDisabled": True,
                                          "saveDisabled": True, "file": True, "dirs": 0}
    assert facts["profileWriteFailed"] == {"status": "保存失败：NotAllowedError", "error": True, "open": True,
                                           "saveDisabled": False, "kept": True}
    assert facts["profileDiscarded"] == {"open": False, "confirms": ["放弃未保存的修改吗？"]}
    assert facts["profileShutdown"] == {"unloaded": {"open": False, "focusListeners": 0}, "open": False, "confirms": 0}


def test_profile_sheet_covers_the_window_in_zotero_colours():
    rules = css_rules()
    backdrop = rules[".scholium-sheet-backdrop"]
    for part in ("position: fixed", "inset: 0", "z-index: 10000"):
        assert part in backdrop, part
    preview = rules["#scholium-profile-sheet .scholium-preview"]
    assert "overflow: auto" in preview and "background: var(--material-background)" in preview
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in rules[".scholium-editor-panes"]
    assert "border-radius: 50%" in rules[".scholium-swatch"]
    assert "background: var(--material-sidepane)" in rules[".scholium-sheet"]
    editor = rules["#scholium-profile-sheet .scholium-editor"]
    assert "background: var(--material-background)" in editor and "color: var(--fill-primary)" in editor
    assert "var(--accent-red)" in rules[".scholium-hint.error"]
    assert not (PLUGIN / "content" / "profile.xhtml").exists()


def test_new_profile_keeps_its_rules_through_a_statistics_run(facts):
    from zotero_scholium import cli
    created = facts["profileCreated"]["saved"]
    assert cli.USER_RULES_MARK in created
    edited = created + "- 页边批注用蓝色\n"
    merged = cli.merge_profile_md("# Annotation profile\n\nBased on 999 annotations.\n\n## Interpretation (x)\n\n- colour meanings: ___\n", edited)
    assert "999 annotations" in merged and merged.rstrip().endswith("- 页边批注用蓝色")


def test_plugin_addresses_carry_the_version(facts):
    v = facts["versioned"]
    assert v["pkg"] == "scholium-0-1-3-10022049" and v["release"] == "scholium-0-2-0"
    base = "chrome://scholium-0-1-3-10022049/content/"
    assert v["icons"] == [base + "icon16.svg", base + "icon20.svg"]
    assert v["style"] == base + "scholium.css"


def test_plugin_ships_the_section_icons_and_localization():
    import xml.dom.minidom
    # drawn apart for 16 and 20 px, violet, lighter on a dark theme
    for name, size, colour in (("icon16.svg", "16", "#8b5cf6"), ("icon16-dark.svg", "16", "#a78bfa"),
                               ("icon20.svg", "20", "#8b5cf6"), ("icon20-dark.svg", "20", "#a78bfa")):
        svg = xml.dom.minidom.parse(str(PLUGIN / "content" / name)).documentElement
        assert svg.tagName == "svg" and svg.getAttribute("viewBox") == f"0 0 {size} {size}" and f'fill="{colour}"' in svg.toxml(), name
    # the plugin list's icon, in colour
    icons = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf8"))["icons"]
    assert icons == {"48": "content/icon96.svg", "96": "content/icon96.svg"}
    assert xml.dom.minidom.parse(str(PLUGIN / "content" / "icon96.svg")).documentElement.getAttribute("viewBox") == "0 0 96 96"
    assert (PLUGIN / "content" / "scholium.css").is_file()
    for lang in ("en-US", "zh-CN"):
        ftl = (PLUGIN / "locale" / lang / "scholium.ftl").read_text(encoding="utf8")
        assert "scholium-section =\n    .label = Scholium" in ftl and "scholium-sidenav =\n    .tooltiptext = Scholium" in ftl


def test_the_transcript_box_is_bounded_like_the_transcript(facts):
    assert facts["boundedLog"] == {"running": True, "kept": 4, "nodes": 4}


def test_a_failed_prompt_write_stops_claude_code(facts):
    f = facts["stdinFails"]
    assert f["kills"] == 1 and not f["running"] and f["state"] is None and f["last"][0] == "scholium-card failed" and "EPIPE" in f["last"][1]


def test_no_run_starts_after_the_plugin_stopped(facts):
    assert facts["stopWhileLooking"] == {"looking": True, "calls": 0}
    assert facts["stopWhilePreparing"] == {"preparing": True, "calls": 0}
    assert facts["stopWhileCreating_claude"] == {"creating": True, "started": 1, "stopped": 1, "turns": 0, "toldAfterStop": 0}
    assert facts["stopWhileCreating_codex"] == {"creating": True, "started": 1, "stopped": 1, "turns": 0, "toldAfterStop": 0}


def test_a_log_that_refuses_a_write_a_moment_loses_nothing(facts):
    for agent in ("claude", "codex"):
        f = facts["logLocked_" + agent]
        assert f["locked"] and f["kills"] == 0 and f["outcome"] == "scholium-card none", agent   # the harness's run writes none
        assert f["same"] and f["lines"] > 3, agent + ": every line, in order"



def test_an_empty_message_box_fits_its_placeholder(facts):
    assert facts["inputHeight"] == {"placeholder": "Ask about this paper",
                                    "empty": "48px", "typed": "24px", "cleared": "48px", "value": ""}


def test_extra_instructions_and_follow_ups_continue_the_conversation(facts):
    e = facts["extra"]
    assert e["before"] == {"placeholder": ASK, "sendHidden": False, "sendDisabled": True, "sendRowHidden": False}
    assert "用户的附加要求：\n只标注方法部分\n\n结束时" in e["prompt"] and e["cleared"] == ""
    assert e["firstLogLine"] == {"type": "scholium", "subtype": "prompt", "text": "批注这篇\n附加要求：只标注方法部分", "annotate": True,
                                 "extra": "只标注方法部分"}
    assert e["firstEntry"] == ["scholium-entry prompt", "批注这篇\n附加要求：只标注方法部分"]
    # the section stays on the annotation tab, whose words go to the annotation's session
    follow = "接着这次批注修改，例如：第 5 页那条译文改短"
    assert e["after"] == {"placeholder": follow, "sendHidden": False, "sendDisabled": True, "sendRowHidden": False}
    assert e["typed"] == {"placeholder": follow, "sendHidden": False, "sendDisabled": False, "sendRowHidden": False}
    f = facts["followUp"]
    assert f["calls"] == 2 and f["resume"] == "S1" and f["prevented"] is True and f["cleared"] == ""
    assert f["prompt"].startswith("下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。仍是无人值守：不要向用户提问，不要启动子代理。"
                                  "只是提问就直接回答；要改批注时按技能的流程修改配置，再写入 Zotero。")
    assert f["prompt"].endswith("\n\n第 5 页那条译文改短\n\n" + CLOSING)
    assert f["prompts"] == ["批注这篇\n附加要求：只标注方法部分", "第 5 页那条译文改短"]
    assert f["entries"] == 2 * (2 + len(TRANSCRIPT)), "each run: the user's words, the transcript, the annotation's card or when the follow-up ended"
    assert f["markers"] == f["prompts"] and f["inits"] == 2 and f["cards"] == 1 and f["times"] == 1
    assert f["counts"] == 1, "the numbers are the annotation's, not the follow-up's"
    assert f["state"] is None and f["conversations"] == 1


def test_a_paper_outside_the_queue_shows_nothing_of_a_pause(facts):
    assert facts["limitOther"] == {"paused": True, "resume1": True, "resume2": False, "state2": None}


def test_usage_limit_pauses_the_queue_and_continues_after_the_reset(facts):
    m = facts["limit"]
    waiting = f"Claude Code 额度已用完，{m['clock']} 重置后自动继续"
    assert m["calls"] == 1 and m["queue"] == [["ATT1", "S1", ""], ["ATT2", None, None]]
    assert len(m["waits"]) == 1 and 7_190_000 < m["waits"][0] <= 7_260_000
    assert m["state1"] == waiting and m["kind1"] == "scholium-state paused"
    assert m["state2"] == "排队中，前面还有 1 篇 · " + waiting, "one line"
    assert m["title1"] == waiting and m["title2"] == m["state2"], "a state cut short is whole in its tooltip"
    assert m["resumeShown"] is True and m["stopShown"] is True
    assert m["notices"][-1]["errors"] == 1 and m["notices"][-1]["descriptions"] == [waiting]
    assert m["notifications"] == []
    assert m["last"] == ["scholium-entry text error", "You've hit your limit · resets 9pm"]
    # a follow-up while the paper waits for the reset is queued behind it
    assert m["followUpWhileQueued"] is True and m["queued"] == 3 and m["queuedWords"] == ["ATT1", ["ATT1", "annotate", "x"], "ATT2"]
    r = facts["limitResumed"]
    assert r["calls"] == 3 and r["resume"] == "S1" and r["order"] == ["ATT1", "continue", "ATT2"]
    assert r["prompt"] == "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。"
    assert "额度已恢复，接着中断的地方继续" in r["entries"] and r["markers"] == ["prompt", "continue", "counts", "time"] and r["inits"] == 2
    assert r["runs"] == [["claude", "批注这篇"], ["claude", None]], "the continuation is the same turn"
    assert run_time(r["cards"]) == [CARD], "the annotation's card, once it went on to its end"
    assert r["state1"] is None and r["paused"] is None and r["waits"] == []
    assert r["notifications"] == []
    t = facts["retry"]
    assert t["waits"] == [600000] and t["state1"] == f"Claude Code 额度已用完，{t['clock']} 自动重试"
    assert t["queue"] == ["ATT1"]
    a = t["after"]
    assert a["calls"] == 2 and a["resume"] == "S1" and a["waits"] == [] and a["paused"] is None
    assert run_time(a["cards1"]) == [CARD] and a["state1"] is None and a["state2"] is None
    assert facts["pauseCancelled"] == {"queue": 0, "paused": None, "waits": [], "calls": 1}


CODEX_APP = "/localappdata/OpenAI/Codex/bin/h1/codex.exe"
CODEX_NPM = "/appdata/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
CODEX_TRANSCRIPT = [
    ["scholium-entry text", "先提取句子。"],
    ["scholium-entry tool", "⏺ Shell(python C:/skills/scholium.py extract --pdf x.pdf --sentences s.json)"],
    ["scholium-entry result", "⎿ 412 sentences -> s.json\n1\n2\n3\n… +2"],
    ["scholium-entry tool", "⏺ Shell(Get-Content D:\\Zotero\\tmp\\scholium\\ATT1\\sentences.txt)"],
    ["scholium-entry result", "⎿ [1] First sentence."],
    ["scholium-entry tool", "⏺ Edit(D:\\Zotero\\tmp\\scholium\\ATT1\\config.json)"],
    ["scholium-entry tool", "⏺ Shell(python C:/skills/scholium.py --config c.json)"],
    ["scholium-entry result error", "⎿ style_warnings: 1"],
    ["scholium-entry tool", "⏺ Shell(python C:/skills/scholium.py --config c.json --apply)"],
    ["scholium-entry result", '⎿ {"applied": true}'],
    ["scholium-entry text", "Done.\n" + SUMMARY],
]
CODEX_ENDED = ["scholium-meta", "Codex · GPT-6-Luna · HH:MM"]
CODEX_CARD = card("3 轮 · 2,647k tokens")


def test_codex_is_the_newest_copy_found(facts):
    f = facts["codexFound"]
    assert f["path"] == CODEX_APP and f["npmNewer"] == CODEX_NPM
    assert f["asked"] == [CODEX_APP, "/localappdata/OpenAI/Codex/bin/codex.exe",
                          "/appdata/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe",
                          "/home/u/.cargo/bin/codex.exe", "/home/u/.local/bin/codex.exe"]
    assert facts["codexConfigured"] == {"path": "/custom/codex.exe", "asked": 0} and facts["codexConfiguredMissing"] is None
    assert facts["codexNewer"] == [True, False, True, False, True, False]
    assert facts["shellCommands"] == ["python a.py", "ls -la", "Get-Content x", "python a.py", "\"C:\\x\\other.exe\" -c 'x'", "it's"]
    assert facts["codexReset"] == [None, None, 200000, None]


def test_codex_models_come_from_its_app_server(facts):
    m = facts["codexModels"]
    assert m["agent"] == "codex" and m["shown"] == "codex" and m["otherShown"] == "codex"
    assert m["agents"] == [["claude", "Claude Code"], ["codex", "Codex"]]
    assert m["call"] == {"command": CODEX_APP, "args": ["app-server"], "workdir": "/data"}
    assert m["sent"] == ["initialize", "initialized", "model/list"] and m["killed"] is True
    assert m["hello"]["clientInfo"]["name"] == "scholium" and m["secretKept"] is False and m["calls"] == 1
    assert m["models"] == ["", "gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-5.5"] and m["model"] == ""
    assert m["labels"] == ["Codex 默认", "GPT-6.1-Sol", "GPT-6-Astra", "GPT-6-Luna", "GPT-5.5"], "no model named before a thread ran it"
    assert m["efforts"] == ["low", "medium", "high", "xhigh"] and m["effort"] == "medium", "Codex has no max"
    assert m["legacy"] == {"efforts": ["low", "medium", "high", "xhigh"], "effort": "medium"}
    assert m["chosen"] == {"model": "gpt-6-luna", "effort": "high", "claudeModel": None, "claudeEffort": None, "otherModel": "gpt-6-luna"}
    assert m["back"] == {"model": "opus", "effort": "medium", "labels": ["Claude Code 默认（Fable 5.1）", "Opus 5.5"]}
    assert m["again"] == {"model": "gpt-6-luna", "effort": "high", "calls": 1}


def test_codex_runs_the_skill_in_a_sandbox_through_its_app_server(facts):
    r = facts["codexRun"]
    assert r["call"] == {"command": CODEX_APP, "args": ["app-server"], "workdir": "/data/tmp/scholium",
                         "env": {"PYTHONIOENCODING": "utf-8"}, "append": True}
    assert r["methods"] == ["initialize", "initialized", "account/read", "mcpServerStatus/list", "plugin/installed", "skills/list", "skills/list",
                            "skills/extraRoots/set", "thread/start", "turn/start"]
    assert r["skillLists"] == [["/data/tmp/scholium"], ["/data"]] and r["roots"] == ["/data/.agents/skills"]
    # the user's MCP servers and installed plugins stay out of the thread
    assert r["thread"] == {"cwd": "/data/tmp/scholium", "approvalPolicy": "on-request", "approvalsReviewer": "auto_review",
                           "sandbox": "workspace-write", "serviceName": "scholium", "model": "gpt-6-luna",
                           "config": {"mcp_servers": {"s": {"enabled": False}}}}
    roots = ["/data/tmp/scholium", "/data/zotero-scholium", "/appdata/zotero-scholium"]
    assert r["turn"] == {"threadId": "T1", "model": "gpt-6-luna", "effort": "high", "disabledPluginIds": ["superpowers@m", "zotero@remote"],
                         "input": [{"type": "text", "elements": []},
                                   {"type": "skill", "name": "zotero-scholium", "path": "/data/.agents/skills/zotero-scholium/SKILL.md"}],
                         "sandboxPolicy": {"type": "workspaceWrite", "writableRoots": roots, "networkAccess": True,
                                           "excludeTmpdirEnvVar": False, "excludeSlashTmp": False}}
    assert all(d in r["dirs"] for d in roots)
    assert "附件 key：ATT1" in r["prompt"] and "不要向用户提问" in r["prompt"]
    # questions that reach the plugin are declined: nobody is there to answer
    assert r["answers"] == [{"id": "q1", "result": {"decision": "decline"}}, {"id": "q2", "result": {"answers": {}}},
                            {"id": "q3", "error": {"code": -32601, "message": "not handled by scholium"}}]
    assert r["killed"] is True and r["session"] == "T1" and r["claudeCalls"] == 0
    assert r["applied"] == "/data/tmp/scholium/c.json", "the configuration of its apply, in Codex's folder"


def test_codex_transcript_state_and_log_read_like_claude_codes(facts):
    r = facts["codexRun"]
    assert run_time(r["entries"]) == [ANNOTATE] + CODEX_TRANSCRIPT + [CODEX_CARD]
    assert r["state"] is None and r["ctxUsed"] == 1325778 and r["ring"] is None
    # the token counts behind the total, which no place on the annotation tab shows
    assert r["stateTitle"] == "输入 190k · 缓存写入 0 · 缓存读取 2,410k · 输出 47k"
    # deltas and start-up chatter stay out of the log; the run starts and ends as Claude Code's does
    assert not any(m.endswith("Delta") or m.endswith("delta") or "startupStatus" in m for m in r["logged"])
    assert r["logged"][:2] == ["scholium", "system"] and r["logged"][-3:] == ["result", "scholium", "scholium"]   # the numbers counted, the end
    assert "item/commandExecution/requestApproval" in r["logged"] and r["userMessages"] == 0, "the user's message is the plugin's own line"
    assert r["init"] == {"type": "system", "subtype": "init", "agent": "codex", "model": "gpt-6-luna", "session_id": "T1"}
    assert r["result"] == {"type": "result", "agent": "codex", "subtype": "success", "is_error": False, "result": "Done.\n" + SUMMARY,
                           "session_id": "T1", "duration_ms": 376500, "num_turns": 3,
                           "usage": {"input_tokens": 190000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 2410000,
                                     "output_tokens": 46778}}
    assert run_time(r["notices"][-1]["descriptions"]) == DONE_NOTICE
    # the annotation tab shows its session: its send button is there; its log is the annotation session's
    assert r["sendShown"] is True and re.fullmatch(r"/data/tmp/scholium/ATT1/conversations/annotate-codex-\d{8}-\d{6}\.jsonl", r["revealed"][0])
    latest = facts["latestLog"]
    assert latest["codex"] == {"first": CODEX_TRANSCRIPT[0], "count": len(CODEX_TRANSCRIPT) + 1,
                               "state": "上次：完成 · 3 轮 · 2,647k tokens", "shownConv": "codex-run", "session": "T1",
                               "revealed": "/data/tmp/scholium/ATT1/codex-run.jsonl", "title": "批注这篇"}, "an earlier version's log is its agent's"
    assert latest["claude"]["first"] == TRANSCRIPT[0]
    assert latest["claude"]["session"] == "S1" and latest["claude"]["shownConv"] == "claude-run"
    assert latest["claude"]["revealed"] == "/data/tmp/scholium/ATT1/claude-run.jsonl"


def test_an_unchanged_log_is_parsed_once(facts):
    c = facts["logCache"]
    assert c["first"] == c["again"] and c["unchanged"] == 0
    assert c["after"] == c["first"] + 1 and c["reparsed"] == 7
    assert facts["quietTurn"] == [{"user": "只写入", "reply": "", "ended": "", "reached": True, "start": 0, "agent": "claude", "points": {"claude": None, "codex": None},
                                  "sessions": {"claude": None, "codex": None}, "done": True}], \
        "a run that ended well without a word is not an unfinished one"


def test_the_agents_share_the_papers_conversations(facts):
    f = facts["codexFollowUp"]
    assert f["claudeCalls"] == 0
    assert f["methods"] == ["initialize", "initialized", "account/read", "plugin/installed", "thread/resume", "turn/start"], "the servers listed once"
    assert f["resume"] == {"threadId": "T1", "excludeTurns": True, "cwd": "/data/tmp/scholium", "approvalPolicy": "on-request", "approvalsReviewer": "auto_review",
                           "sandbox": "workspace-write", "serviceName": "scholium", "model": "gpt-6-luna",
                           "config": {"mcp_servers": {"s": {"enabled": False}}}}
    assert f["disabled"] == ["superpowers@m", "zotero@remote"]
    assert len(f["input"]) == 1 and f["input"][0]["text"].endswith("第 5 页那条译文改短\n\n" + CLOSING)
    assert f["effort"] == "high"
    # only this run's calls and tokens: the thread's totals include the earlier turn (kept by the plugin; a follow-up on
    # the annotation tab shows its model and time)
    assert f["state"] == "完成 · 1 轮 · 403k tokens"
    assert run_time(f["entries"]) == [["scholium-entry text", "Done.\n" + SUMMARY], CODEX_CARD, ["scholium-entry prompt", "第 5 页那条译文改短"],
                                      ["scholium-entry text", "改好了：第 5 页的译文已缩短。"], CODEX_ENDED]
    assert f["results"] == 2 and f["markers"] == ["批注这篇", "第 5 页那条译文改短"]
    # Claude Code chosen: the chat keeps what it showed, none (Codex's annotation session is no chat); its question starts
    # the paper's conversation, given nothing of the annotation session; Codex's log stays as it was
    c = facts["switchedToClaude"]
    s = c["switched"]
    assert s["entries"] == []
    assert (s["unswitched"], s["shownConv"], s["newChatDisabled"], s["ring"], s["placeholder"]) == (None, None, True, None, ASK)
    assert s["chosen"] is False, "a switch chooses no conversation: the paper has none yet"
    assert c["calls"] == 1 and c["resumed"] is False
    assert c["prompt"].startswith("使用 zotero-scholium 技能读下面这篇论文") and HISTORY_HEAD not in c["prompt"]
    assert "\n\n用户的问题：\n它和 FNO 比怎么样？\n\n" in c["prompt"]
    assert c["conversations"] == ["annotate", "chat"] and c["codexKept"] is True
    # Codex chosen again: the chat keeps the paper's conversation with Claude Code's turn, no note of another agent's,
    # and History lists it; the annotation tab shows Codex's session, which goes on in its thread
    b = facts["switchedBack"]
    assert b["again"] == {"same": True, "asked": True, "info": 0}
    assert [r[0] for r in b["rows"]] == ["scholium-history-group", "scholium-history-row current"]
    assert b["rows"][1][1].startswith("它和 FNO 比怎么样？")
    assert b["opened"] == {"shownConv": True, "historyRows": None, "entries": 16, "placeholder": "接着这次批注修改，例如：第 5 页那条译文改短"}
    assert b["methods"] == ["thread/resume"] and b["threadId"] == "T1" and b["skill"] is False, "Codex goes on in its own thread"
    assert b["text"].startswith("下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。") and b["text"].endswith("\n\n再短一点\n\n" + CLOSING)
    assert b["runs"] == [["codex", "批注这篇"], ["codex", "第 5 页那条译文改短"], ["codex", "再短一点"]] and b["conversations"] == 2


def test_codex_steps_and_cancel(facts):
    c = facts["codexCancel"]
    assert c["during"] == ["", "第 2/6 步 提取句子"], "the state line is its dot; the step is in its tooltip"
    assert c["interrupt"] == {"threadId": "T1", "turnId": "U1"} and c["killed"] is True
    assert c["last"] == ["scholium-card failed", "已取消重试"] and c["state"] is None
    assert c["results"] == 0 and c["waits"] == [] and c["current"] is None and c["shutdown"] is True
    assert c["begun"] == ["", "第 1/6 步 加载技能"]
    s = facts["codexSkillFound"]
    assert s["/data/tmp/scholium"]["methods"] == ["skills/list"]
    assert s["/data/tmp/scholium"]["input"] == [{"type": "skill", "name": "zotero-scholium", "path": "/home/u/.codex/skills/zotero-scholium/SKILL.md"}]
    none = s["none"]
    assert none["methods"] == ["skills/list", "skills/list"] and none["input"] is None and none["model"] is None, "no conversation opens"
    assert none["outcome"].startswith("失败")
    end = json.loads(none["log"].strip().splitlines()[-2])   # before when the run ended
    assert end["subtype"] == "end" and end["outcome"] == "failed" and "Codex 找不到 zotero-scholium 技能" in end["text"]


def test_a_lost_connection_shows_on_the_state_line_until_the_agent_answers_again(facts):
    r = facts["reconnecting"]
    assert r["codex"]["state"] == "连接中断，正在重试（2/5）"
    assert r["codexBack"]["state"] == ""
    assert not any("连接" in str(e) or "Reconnecting" in str(e) for e in r["codex"]["entries"]), "the transcript gets no line of its own"
    assert "连接中断，正在重试（1/10）" in r["claude"]["state"]
    assert "连接中断" not in r["claudeBack"]["state"]


def test_codex_usage_limit_waits_for_the_reset(facts):
    l = facts["codexLimit"]
    assert l["clock"] == l["expected"] and l["known"] is True
    assert l["queue"] == [["ATT1", "codex", "T1"], ["ATT2", "codex", None]]
    assert l["notifications"] == []
    assert l["last"] == ["scholium-entry final error", "You've hit your usage limit. Try again at 9:00 PM."], "it goes on after the wait: no card"
    a = l["after"]
    assert a["resume"] == "T1" and a["prompt"] == "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。"
    # the continuation ends the annotation: its card, with the continuation's turns and tokens
    assert run_time(a["cards"]) == [card("1 轮 · 403k tokens", title="✓ 批注完成")], "the end's card only"
    assert a["turns"] == 3 and a["paused"] is None and a["state"] is None


def test_codex_failures_are_reported(facts):
    f = facts["codexFailed"]
    assert f["entries"] == [["scholium-entry result", "⎿ 412 sentences"], ["scholium-card failed", "stream disconnected before completion重试"]]
    assert f["state"] is None and f["paused"] is None
    assert f["turns"] == 1 and f["queue"] == 0   # a tool had run: no second try
    assert f["notices"][-1]["descriptions"] == ["失败 · stream disconnected before completion"]
    r = facts["codexRefused"]
    assert r["last"] == ["scholium-card failed", "model gpt-9 is not available重试"] and r["state"] is None
    assert r["killed"] is True and r["turns"] == 0
    n = facts["noCodex"]
    # no program, so no session: the end of a run without its Annotate line, with no Retry
    assert n["codexCalls"] == 0 and n["state"] is None
    assert n["last"] == ["scholium-entry final error", "找不到 Codex（codex.exe）。请在 Zotero 设置 → Scholium 里指定 Codex 程序。"]
    assert n["models"] == [""] and n["labels"] == ["Codex 默认"]


def test_a_failed_connection_gets_one_more_try(facts):
    r = facts["retry2"]
    w = r["ok"]["waiting"]
    assert w["state"] == "等待第二次尝试" and w["kind"] == "scholium-state paused", "the transcript says why"
    assert w["last"] == [["scholium-entry final error", "workspace routing discovery timed out"],
                         ["scholium-entry info", "连接失败，30 秒后自动重试一次"]], "no card: the second try comes by itself"
    assert w["stopShown"] is True and w["queue"] == [["ATT1", True]] and w["job"] is None
    assert w["notices"] == 1 and w["notifications"] == 0 and w["turns"] == 1   # only the start notice so far
    ok = r["ok"]
    assert ok["turns"] == 2 and ok["queue"] == 0 and ok["state"] is None
    assert run_time(ok["cards"]) == [CODEX_CARD], "the second try is the annotation's: its card, and no red card"
    # one log, the first try kept: two starts, the retry line between them
    assert ok["marks"] == ["prompt", "retry", "counts"] and ok["inits"] == 2   # the extra instructions are logged once
    assert ok["runs"] == [["codex", "批注这篇\n附加要求：只标注方法部分"], ["codex", None]], "the second try is the same turn"
    assert ok["entries"][:4] == [["scholium-entry prompt", "批注这篇\n附加要求：只标注方法部分"],
                                 ["scholium-entry final error", "workspace routing discovery timed out"],
                                 ["scholium-entry info", "连接失败，30 秒后自动重试一次"], ["scholium-entry text", "先提取句子。"]]
    assert ok["notifications"] == []
    again = r["again"]
    assert again["turns"] == 2 and again["queue"] == 0 and again["state"] is None
    assert again["cards"] == [["scholium-card failed", "workspace routing discovery timed out重试"]], "the last try's card, with Retry"
    assert again["marks"] == ["prompt", "retry"] and again["notifications"] == []
    assert again["waiting"]["last"][0] == ["scholium-entry final error", "stream disconnected before completion"]
    assert r["cancelled"] == {"queue": 0, "turns": 1, "last": ["scholium-card failed", "已取消重试"], "draining": False}
    assert r["refused"] == {"turns": 1, "queue": 0}
    c = r["claude"]
    assert c["waiting"] == {"state": "等待第二次尝试", "calls": 1}
    assert c["calls"] == 2 and run_time(c["cards"]) == [CARD]
    assert c["resumed"] is False and c["prompts"] == 2
    assert r["claudeActed"] == {"calls": 1, "queue": 0}
    assert facts["transient"] == [True, True, True, True, True, False, False, False]


def test_a_notice_shows_the_agents_words_as_text(facts):
    d = facts["noticeMarkup"]
    assert d == ["done <\u2060a onmouseover=\"x()\">here<\u2060/a>", "next"]


def test_the_prompt_names_the_profile_or_the_defaults(facts):
    p = facts["profilePrompt"]
    assert "- 画像：/data/zotero-scholium/profile.md\n" in p["zh"]
    assert "- Profile: none; annotate with the defaults and do not create or change a profile\n" in p["en"]
    assert p["en"].endswith("End with one line only: N highlights (M core), K margin notes, note “title”, remaining warnings.")
    assert facts["prompt"].count("画像：没有；按默认值标注，不要生成或修改画像") == 1
    assert "笔记《标题》" in facts["prompt"]


def test_a_follow_up_says_how_to_change_written_annotations(facts):
    prompt = facts["appliedConfig"]["unchanged"][0]
    assert "改已经写入的批注或补几条时，都编辑写入它们的那份配置（它是这篇论文的全部批注），设 cleanup: true 整份重写" in prompt
    assert "不要另写只含新条目的配置，否则下次整份重写时会把它们删掉。" in prompt
    # the harness's paper never gets the annotations: as after a deletion, the follow-up says they are gone
    assert "\n这篇论文现在没有本工具的批注（可能已在 Zotero 里删除）。\n" in facts["followUp"]["prompt"]
    assert "整份重写" not in facts["followUp"]["prompt"]


def test_claude_code_without_the_skill_stops_at_once(facts):
    n = facts["noSkill"]
    assert n["kills"] == 1 and n["state"] is None
    assert n["last"] == ["scholium-card failed", "Claude Code 找不到 zotero-scholium 技能：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装后再试（其他安装方式见 README）。重试"]
    assert n["end"]["subtype"] == "end" and n["end"]["outcome"] == "failed"
    assert facts["pluginSkill"]["kills"] == 0 and facts["pluginSkill"]["state"].startswith("完成"), "a plugin's skill counts"


def test_an_update_hands_the_running_paper_and_the_queue_to_the_new_copy(facts):
    u = facts["update"]
    assert u["end"]["subtype"] == "end" and u["end"]["outcome"] == "interrupted"
    assert u["end"]["text"] == "运行被中断（插件更新或停用，或 Zotero 退出）"
    assert [(c["key"], c["resume"], c.get("updated", False)) for c in u["carried"]["jobs"]] == [("ATT1", "S1", True), ("ATT2", None, False)]
    assert u["carried"]["paused"] is None
    assert u["resume"] is True and u["prompts"][0] == "插件更新打断了上面的任务。请从中断的地方继续完成，规则不变。"
    assert "附件 key：ATT2" in u["prompts"][1] and len(u["prompts"]) == 2
    assert u["cleared"] == "", "handed over once"
    assert "运行被中断（插件更新或停用，或 Zotero 退出）" in u["entries"] and "插件已更新，接着中断的地方继续" in u["entries"]
    # the annotation tab of a section drawn later shows the session, its end last; its state line shows runs going on or waiting
    assert u["history"] is None and u["historyLast"] == ["scholium-card failed", "运行被中断（插件更新或停用，或 Zotero 退出）重试"]
    assert u["disabled"] == {"carried": None, "end": "interrupted"}


def test_a_cancelled_run_keeps_its_end_in_the_log(facts):
    c = facts["cancelLogged"]
    assert c["end"]["outcome"] == "cancelled" and c["end"]["text"] == "已取消"
    assert c["history"] == ["scholium-card failed", "已取消重试"]


def test_the_services_limit_waits_as_long_as_it_says(facts):
    t = facts["throttle"]
    assert t["throttled"] is True and t["known"] is True and 1_490_000 < t["wait"] <= 1_510_000
    assert t["state"] == f"Claude Code 服务暂时限流，{t['clock']} 自动继续" and t["notices"] == [t["state"]]
    a = t["after"]
    assert a["prompt"] == "服务已恢复。请从中断的地方继续完成上面的任务，规则不变。" and a["paused"] is None
    assert "限流已解除，接着中断的地方继续" in a["entries"]
    assert facts["resetFrom"] == [24, 3, 120, None, None, None]


def test_papers_outside_my_library_and_missing_files_are_not_run(facts):
    o = facts["otherLibrary"]
    assert o["state"] == "Scholium 只能批注“我的文库”里的论文。" and o["annotateDisabled"] is True
    assert o["queued"] == 0 and o["calls"] == 0
    assert o["alerts"] == ["Scholium 只能批注“我的文库”里的论文。", "这篇论文的 PDF 文件不在这台电脑上（还没下载，或已被移走）。"]
    assert facts["noPdf"]["alerts"] == ["这篇论文没有 PDF 附件。"]
    assert o["composerHidden"] is True and o["controls"] == [True, True, True] and o["asked"] is False, "no message box or conversations"
    assert o["askedMissing"] == [False, ["这篇论文的 PDF 文件不在这台电脑上（还没下载，或已被移走）。"], 0]


def test_annotate_again_opens_a_session_with_the_box_as_extra_instructions(facts):
    a = facts["annotateInConversation"]
    assert a["calls"] == 2 and a["resume"] is None and a["kept"] == "" and a["conversations"] == 2
    assert a["prompt"].startswith("使用 zotero-scholium 技能，为下面这篇论文做整篇标注：") and "用户的附加要求：\n只标方法部分\n\n结束时" in a["prompt"]
    assert a["prompts"] == ["批注这篇\n附加要求：只标方法部分"], "the annotation tab shows the new session"


def test_a_question_starts_a_conversation_that_answers_without_annotating(facts):
    a = facts["ask"]["asked"]
    assert a["sent"] is True and "--resume" not in a["args"]
    assert a["prompt"] == "\n".join([
        "使用 zotero-scholium 技能读下面这篇论文（status 给出题录，extract 给出正文），回答用户在 Zotero 里提的问题。",
        "",
        "- 条目 key：ITEM1",
        "- 附件 key：ATT1",
        "- 论文：/data/tmp/scholium/ATT1/paper.json（PDF 的路径、两个 key 和输出目录）",
        "- 输出目录：/data/tmp/scholium/ATT1",
        "- 画像：没有；不要生成或修改画像",
        "",
        "这是从 Zotero 里发来的无人值守任务：不要向用户提问，不要启动子代理。只回答，不写批注和笔记；用户在问题里明确要求时，才按技能的流程写入 Zotero。",
        "/data/tmp/scholium/ATT1/paper.json 是插件的文件，只读，不要修改：只有 extract（代替 --pdf）和 --list 用 --config "
        "/data/tmp/scholium/ATT1/paper.json。你的配置另写一个文件，放在输出目录里（如 /data/tmp/scholium/ATT1/config.json），"
        "从 /data/tmp/scholium/ATT1/paper.json 的四个键写起，试运行和 --apply 都用它。不要把 PDF 路径、论文标题或其他题录写进命令行。",
        "这篇论文目前没有本工具的批注。",
        "引用论文原句时，在句末写它的句子编号，格式 [#123]（多句写 [#12][#15]）；编号来自 extract --config /data/tmp/scholium/ATT1/paper.json "
        "--sentences /data/tmp/scholium/ATT1/sentences.json --out /data/tmp/scholium/ATT1/sentences.txt（已有就直接读 sentences.txt）。",
        "",
        "用户的问题：",
        "这篇怎么估计后验？",
        "",
        "写入了 Zotero 时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。",
    ])
    assert run_time(a["during"]) == {"placeholder": ASK, "sendHidden": False, "stop": ["■", "停止"], "state": "", "cleared": ""}, \
        "a question's state line is its dot"
    assert a["lines"] == [{"type": "scholium", "subtype": "prompt", "text": "这篇怎么估计后验？", "question": True}]
    assert run_time(a["notices"]) == [["已在后台开始回答。过程见条目侧栏的 Scholium 区块。"], ["完成 · Ns", "用变分推断估计后验。"]]
    assert a["entries"][0] == "这篇怎么估计后验？编辑" and a["entries"][-2:] == ["用变分推断估计后验。", a["entries"][-1]], "the question with its ✎"
    assert a["after"]["placeholder"] == ASK and a["after"]["session"] == "Q1"
    assert facts["ask"]["shown"] == {"placeholder": ASK, "session": "Q1"}, "a restart reads the question's conversation from the log"


def test_annotate_after_a_question_opens_a_session_of_its_own(facts):
    follow = "接着这次批注修改，例如：第 5 页那条译文改短"   # the annotation tab's box while its run goes, then words to its session
    n = facts["ask"]["annotated"]
    assert n["resume"] is None and n["cleared"] == "", "a new annotation session is not given the chat"
    assert n["prompt"].startswith("使用 zotero-scholium 技能，为下面这篇论文做整篇标注：")
    assert "\n- 画像：没有；按默认值标注，不要生成或修改画像\n" in n["prompt"] and "用户的附加要求：\n重点标方法部分\n\n结束时" in n["prompt"]
    assert n["lines"] == [{"type": "scholium", "subtype": "prompt", "text": "批注这篇\n附加要求：重点标方法部分", "annotate": True, "extra": "重点标方法部分"}]
    assert n["prompts"] == ["批注这篇\n附加要求：重点标方法部分"]
    assert n["chat"] == [["这篇怎么估计后验？编辑"], True], "the question's conversation stays as it was (the question with its ✎)"
    assert n["notices"][0] == [STARTED]
    assert n["after"] == {"placeholder": follow, "sendHidden": False, "stop": ["↑", "发送"], "session": "Q1"}
    r = facts["ask"]["redo"]
    assert r["calls"] == 3 and r["resumed"] is False and r["kept"] == "" and r["conversations"] == 3, "Annotate again opens another session"
    assert [line["text"] for line in r["lines"]] == ["批注这篇\n附加要求：第 5 页那条译文改短"]
    assert facts["ask"]["restarted"] == {"resumed": False, "prompt": n["prompt"].split("\n")[0], "profile": "- 画像：/data/zotero-scholium/profile.md"}
    assert facts["ask"]["later"] == {"placeholder": ASK, "session": "Q1"}, "the question's conversation stays a question's"
    assert facts["askOrder"] == ["ATT3", "ATT4", "ATT2"], "questions go before the papers still waiting, in their order"
    assert run_time(facts["askBox"]) == {"asking": ASK, "annotating": follow, "state": "", "queued": []}, \
        "an annotation that starts shows on its own tab, its dot on the state line"
    c = facts["askThenCodex"]
    assert c["claudeCalls"] == 1 and c["threads"] == ["thread/start"] and c["conversations"] == 2, "Codex starts a conversation of its own"
    assert c["text"] == "使用 zotero-scholium 技能，为下面这篇论文做整篇标注：重点句高亮加译文评论（论文本身是中文时不加评论）、页边批注、阅读笔记，按画像和默认值。"
    assert c["entries"][0] == "批注这篇" and c["entries"][-1] == CODEX_CARD[1][:30] and "这篇怎么估计后验？" not in c["entries"]
    assert c["placeholder"] == follow


def test_a_questions_follow_ups_failures_and_races(facts):
    e = facts["askEdges"]
    assert e["owned"] == ("这篇论文已有 1 条本工具的批注；问到它们的内容时，用 --config /data/tmp/scholium/ATT1/paper.json --list --full 列出。"
                          "要改批注或补几条时，编辑输出目录里写入它们的那份配置（它是这篇论文的全部批注），"
                          "设 cleanup: true 整份重写（阅读笔记也改时再设 note_replace: true）；不要另写只含新条目的配置。")
    assert e["followUp"] == ("下面是用户在 Zotero 里针对这篇论文发来的后续消息。仍是无人值守：不要向用户提问，不要启动子代理。"
                             "只是提问就直接回答；用户明确要求写批注或笔记时，才按技能的流程写入 Zotero。\n\n那它的损失函数呢？\n\n"
                             "写入了 Zotero 时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。"), "no configuration to rewrite whole"
    assert e["resumes"] == [False, True, False, False], "each annotation opens a session of its own"
    assert e["failed"] == {"session": "Q1", "question": True, "placeholder": ASK}, "a failed annotation leaves the question's conversation as it was"
    race = facts["askRace"]
    assert [bool(x) for x in race["both"]] == [True, True] and race["queued"] == 1 and race["calls"] == 1, "one runs, the other waits behind it"
    assert facts["handedTwice"] == {"calls": 0, "updated": True, "conv": "claude-run"}, "an earlier version's paper goes on in that version's log"


def test_a_session_the_agent_no_longer_has_is_rebuilt_from_the_conversation(facts):
    question = "使用 zotero-scholium 技能读下面这篇论文（status 给出题录，extract 给出正文），回答用户在 Zotero 里提的问题。"
    turn = "[第 1 轮]\n用户：批注这篇\n回答（Codex）：Done.\n" + SUMMARY
    claude_turn = turn.replace("（Codex）", "（Claude Code）")
    items = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "批注这篇"}]},
             {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done.\n" + SUMMARY}]}]
    for name in ("goneCodex", "goneCodexText"):
        c = facts[name]
        assert c["methods"] == [["thread/resume"], ["thread/start", "thread/inject_items"]], name
        assert c["marks"][1:] == [{"type": "scholium", "subtype": "prompt", "text": "AdLN的作用是什么"},
                                  {"type": "scholium", "subtype": "gone", "agent": "codex", "resent": True}], name
        assert c["runs"] == ["批注这篇", "AdLN的作用是什么", None], "the new session's run is the same turn"
        assert c["items"] == items, name
        assert "\n\n用户的新消息：\nAdLN的作用是什么\n\n" in c["prompt"] and c["skill"] is True, name
        assert run_time(c["entries"][-3:]) == [["scholium-entry prompt", "AdLN的作用是什么"], ["scholium-entry text", "改好了：第 5 页的译文已缩短。"],
                                               ["scholium-meta", "Codex · GPT-6-Astra · HH:MM"]], "nothing shows the session was rebuilt"
        assert c["state"].startswith("完成") and c["session"] == "T2" and c["conversations"] == 1, name
        assert c["placeholder"] == "接着这次批注修改，例如：第 5 页那条译文改短", name
    assert facts["goneCodex"]["prompt"].startswith(question), "the turns are items of the new thread, not text"
    assert facts["goneCodexText"]["prompt"].startswith(HISTORY_HEAD + "\n\n" + turn + "\n\n" + HISTORY_END + "\n\n" + question), \
        "a Codex that does not take items gets them as text"
    k = facts["goneClaude"]
    assert k["resumes"] == [False, True, False]
    assert k["prompt"].startswith(HISTORY_HEAD + "\n\n" + claude_turn + "\n\n" + HISTORY_END + "\n\n" + question)
    assert "\n\n用户的新消息：\nAdLN的作用是什么\n\n" in k["prompt"]
    assert k["prompts"] == ["批注这篇", "AdLN的作用是什么"], "the words are not shown twice"
    # the follow-up's model and time (the annotation has its card)
    assert run_time(k["metas"]) == ["Claude Code · Opus 5.5 · HH:MM"] and k["info"] == [] and k["finals"] == [], "Claude Code's own error for the missing session is not shown"
    assert k["session"] == "Q2" and k["state"].startswith("完成") and k["conversations"] == 1
    assert k["errorsShown"] == {"last": ["scholium-card failed", "Credit balance is too low重试"], "notice": ["失败 · Credit balance is too low"]}
    s = facts["goneStopped"]
    stopped = "Claude Code 里原来的会话已经不存在了（例如已被 Claude Code 清理），刚才的任务没法接着做；再发一条消息，会开一个新会话，带着这段对话接着聊。"
    assert s["calls"] == 2 and s["queued"] == 0, "a continuation is not sent to a new session"
    assert s["gone"] == {"type": "scholium", "subtype": "gone", "agent": "claude", "resent": False}
    # the annotation's continuation failed: its card, with Retry, which annotates anew
    assert s["state"] is None and s["last"] == ["scholium-card failed", stopped + "重试"]
    follow = "接着这次批注修改，例如：第 5 页那条译文改短"   # the annotation tab's box, which shows the session
    assert s["session"] is None and s["placeholder"] == follow, "the session shown stays, without the agent's session"
    assert s["later"] == {"session": None, "placeholder": follow}, "after a restart the log no longer names it"


def test_conversations_of_earlier_versions_and_the_history_given(facts):
    assert facts["codexQuestion"] == {"session": "T1", "question": True, "placeholder": ASK, "title": "这篇讲什么？"}
    g = facts["legacyGoesOn"]
    assert g["claude"] == {"placeholder": "接着对话，例如：第 5 页那条译文改短一些", "shown": "codex-run", "info": 0,
                           "resumed": False, "conversations": 0, "prompt": HISTORY_HEAD}, \
        "Claude Code goes on with the conversation shown, given it as text"
    assert g["resume"] == "T1" and g["text"].startswith("下面是这段对话里，你上次回答之后的 1 轮。这期间用户在 Zotero 里接着问，有的由别的智能体回答，每轮注明了回答者。它们属于这段对话，请接着它们回答：\n\n[第 2 轮]\n用户：AdLN的作用是什么\n回答（Claude Code）："), \
        "Codex is given the turn of Claude Code's that its thread did not see"
    assert "\n\n下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。" in g["text"]
    assert g["agents"] == ["claude", "codex"] and g["conversations"] == 0, "both go on in the earlier log itself"
    assert g["appended"] == ["run", "prompt", "time"] * 2
    h = facts["historyParts"]
    assert h["head"] == HISTORY_HEAD and h["end"] == HISTORY_END
    assert h["summary"] == "之前的 8 轮对话（摘录）：" and h["whole"] == ["[第 %d 轮]" % n for n in range(9, 14)]
    assert h["excerpt"] == "用户：问题 1 " + "q" * 244 + "…\n回答（Claude Code）：" + "x" * 399 + "…", "the user's words cut to 250, the answer to 400"
    assert h["excerpts"] == 11 and h["unfinished"] is True and h["noText"] is True
    assert h["few"] == [HISTORY_HEAD, "[第 1 轮]", "[第 2 轮]", HISTORY_END] and h["none"] == "" and h["noItems"] == []
    assert [i[:2] for i in h["items"]] == [["user", "input_text"], ["assistant", "output_text"]] * 6, "the excerpts, then five exchanges"
    assert h["items"][0][2] == "之前的 8 轮对话（摘录）：" and h["items"][1][2] == "明白，我已了解之前的对话。"
    assert h["cut"] == ["ab…", "abc…", "abc"], "never half of a character that takes two"
    assert h["boundary"] == [False, True], "excerpts from the eleventh exchange on"
    a = facts["annotateAgain"]
    assert a == {"conversations": 2, "threads": ["thread/start"], "runs": ["批注这篇"],
                 "text": "使用 zotero-scholium 技能，为下面这篇论文做整篇标注：重点句高亮加译文评论（论文本身是中文时不加评论）、页边批注、阅读笔记，按画像和默认值。"}
    f = facts["handedFollowUp"]
    assert f["handed"] == ["S1", "AdLN的作用是什么", True, True] and f["resumed"] is True
    assert f["prompt"].startswith("下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。") and "AdLN的作用是什么" in f["prompt"]
    assert f["runs"] == ["批注这篇", "AdLN的作用是什么", None] and f["prompts"] == 2 and f["conversations"] == 1, \
        "the handed message is the same turn, logged once"


def test_new_and_resumed_sessions_know_the_annotations_and_turns(facts):
    a = facts["appliedConfig"]
    assert re.sub(r"\d{2}:\d{2}", "HH:MM", a["fresh"]) == (
        "这篇论文已有 2 条本工具的批注，是 Codex 在 HH:MM 用配置 /data/tmp/scholium/c.json 写入的，这份配置就是它们的全部；问到批注的内容时读这份配置。"
        "要改批注或补几条时，编辑它并设 cleanup: true 整份重写（阅读笔记也改时再设 note_replace: true）；不要另写只含新条目的配置。")
    assert a["applied"] == ["codex", "/data/tmp/scholium/c.json", True], "the configuration of Codex's apply, in its folder"
    edit = ("改已经写入的批注或补几条时，都编辑写入它们的那份配置（它是这篇论文的全部批注），设 cleanup: true 整份重写（阅读笔记也改时再设 "
            "note_replace: true）；不要另写只含新条目的配置，否则下次整份重写时会把它们删掉。")
    assert a["unchanged"] == [edit], "nothing changed since its last run"
    assert a["older"] == [edit], "another conversation's rewrite before this one's last run is nothing new"
    assert [re.sub(r"\d{2}:\d{2}", "HH:MM", t) for t in a["rewritten"]] == [
        edit, "上次之后，Claude Code 在这篇论文的另一段对话里用配置 /data/tmp/scholium/ATT1/b.json 重写了批注（HH:MM）；改批注前先读这份配置，不要用你记得的版本。"]
    assert a["gone"] == ["这篇论文现在没有本工具的批注（可能已在 Zotero 里删除）。"]
    assert a["commands"] == ["D:\\x y\\c.json", "c.json", None, "/abs/c.json"]
    assert facts["unreachedClaude"] == {"session": None, "resumed": False, "conversations": 1,
                                        "prompt": ["[第 1 轮]\n用户：它和 FNO 比怎么样？\n回答（Claude Code）：（没有完成：Invalid API key）"]}, \
        "a session that never had the message is not the conversation's"
    assert facts["legacyTwoTurns"] == "下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。仍是无人值守：不要向用户提问，不要启动子代理。" \
                                      "只是提问就直接回答；要改批注时按技能的流程修改配置，再写入 Zotero。", "both turns of the earlier log reached Codex"
    assert facts["handedInterrupted"] == [[True, True]]
    u = facts["unreached"]
    assert u["before"] == "T1" and u["thread"] == "T1", "a thread that never had the message is not Codex's session"
    assert u["text"].startswith("下面是这段对话里，你上次回答之后的 1 轮。这期间用户在 Zotero 里接着问，有的由别的智能体回答，每轮注明了回答者。它们属于这段对话，请接着它们回答：\n\n[第 2 轮]\n用户：再短一点\n回答（Codex）：（没有完成："), \
        "the turn that never reached the thread is given again"
    assert "\n\n下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。" in u["text"]
    r = facts["retriedContinuation"]
    assert r["calls"] == 3 and r["prompts"][1:] == ["额度已恢复。请从中断的地方继续完成上面的任务，规则不变。"] * 2 and r["resumes"] == [False, True, True]
    i = facts["interruptedTurn"]
    assert i["queued"] == [[True, True, None]] and i["calls"] == 2 and i["conversations"] == 1
    assert i["runs"] == [["claude", "这篇讲什么？"], ["claude", None]] and i["prompts"] == 1, "the same turn, its words logged once"
    assert i["second"].startswith("使用 zotero-scholium 技能读下面这篇论文")
    w = facts["redoWithoutAgent"]
    assert w == {"kept": True, "conversations": 1, "state": None, "chatState": None,
                 "last": ["scholium-entry final error", "找不到 Claude Code（claude.exe）。请在 Zotero 设置 → Scholium 里指定 Claude Code 程序。"]}


def test_new_chat_and_history(facts):
    c = facts["conversations"]
    new = []
    assert c["first"] is True and c["before"] == {"newChatDisabled": False, "historyDisabled": False}
    assert c["fresh"] == {"entries": new, "shownConv": None, "newChatDisabled": True, "input": "", "placeholder": ASK, "chat": None}
    assert c["second"] is True and c["resumedSecond"] is False, "the next message starts a conversation of its own"
    rows = [[cls, re.sub(r"\d{2}:\d{2}", "HH:MM", text)] for cls, text in c["rows"]]
    assert rows[0] == ["scholium-history-group", "今天"] and rows[1] == ["scholium-history-row current", "第二个问题HH:MM重命名删除这段对话"]
    assert rows[2] == ["scholium-history-group", "昨天"] and re.fullmatch(r"第一个问题\d+月\d+日 HH:MM重命名删除这段对话", rows[3][1])
    assert c["rowButtons"] == [["scholium-button quiet glyph edit", "重命名"], ["scholium-button quiet glyph trash", "删除这段对话"]], \
        "rename and delete are icons, their words their tooltips"
    assert rows[4] == ["scholium-history-group", "更早"] and rows[5][1].startswith("很早的问题"), "an earlier version's title is its first words"
    assert c["renamed"][3][1].startswith("估计方法") and [r[1] for r in c["renamed"]][1] == c["rows"][1][1]
    assert [k[:5] for k in c["kept"]] == ["第二个问题", c["kept"][1][:5], "很早的问题"] and c["kept"][1].startswith("估计方法"), "Esc keeps the old title"
    o = c["opened"]
    assert o["shownConv"] is True and o["input"] == "写给第一段对话的话" and o["historyOpen"] is False, "the words typed to it come back with it"
    assert run_time(o["entries"]) == ["第一个问题编辑", "回答 1", "Claude Code · Opus 5.5 · HH:MM"], "the question with its ✎"
    assert c["resumedFirst"] == "Q1", "an earlier conversation goes on in its session"
    assert c["afterFire"] == 0, "a conversation gone for good leaves the layer's rows"
    assert c["followPrompt"] == ("下面是用户在 Zotero 里针对这篇论文发来的后续消息。仍是无人值守：不要向用户提问，不要启动子代理。"
                                 "只是提问就直接回答；用户明确要求写批注或笔记时，才按技能的流程写入 Zotero。\n\n接着第一段\n\n"
                                 "写入了 Zotero 时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。"), \
        "a question's conversation without annotations is not told they are gone"
    d = c["deleting"]
    assert d["rows"][2] == "已删除「第二个问题」撤销" and d["files"] == 3 and d["timers"] == [6000], "for a moment it can be brought back"
    assert c["undone"] == {"rows": 3, "timers": []}
    assert c["deletedShown"] == {"entries": new, "shownConv": None, "back": True}, \
        "the conversation shown is followed by a new one, and comes back with Undo"
    assert c["removed"] == [True] and c["files"] == 2 and c["titles"] == ["第二个问题"] and c["chat"] is None
    assert c["busy"] == {"newChat": True, "history": True, "agent": True}, "the conversations stay as they are while the paper runs"
    a = facts["archived"]
    assert a["queued"] == '["T1"]' and a["archived"] == ["T1"] and a["left"] == ""
    assert a["order"] == ["initialize", "initialized", "thread/archive", "thread/start"], "archived at the next Codex run"


def test_conversations_of_a_paper_with_two_pdfs_and_hand_overs(facts):
    t = facts["twoPdfs"]
    assert t["before"] == ["ATT1", "claude-20261001-120000"]
    assert t["keys"] == ["ATT1"]
    assert t["rows"] == ["今天", "第一份重命名删除这段对话"], "the best PDF's conversations only; one without a line is not listed"
    assert t["after"] == ["ATT1", "claude-20261001-120000"]
    assert t["annotated"] == "ATT1", "Annotate goes to the PDF whose conversation is shown, as Send does"
    assert facts["livePanes"] == {"shownConv": "claude-x", "shownPath": "/data/tmp/scholium/ATT1/conversations/claude-x.jsonl",
                                  "moved": "还没发的话", "left": False}
    assert facts["legacyHandOver"] == [["ATT1", "codex-run", True, False, True, "chat"], ["ATT2", None, False, True, False, "annotate"]], \
        "an earlier version's paused question has its turn in that version's log; its annotation not begun starts a session of its own"


def test_a_switch_of_the_agent_keeps_each_papers_conversation(facts):
    o = facts["otherSections"]
    assert o["before"] == o["switched"] == ["claude-20261001-120000", "claude-20261002-120000"], \
        "every section, the one switched too, keeps its paper's conversation"
    assert o["running"] == "ATT2" and o["current"] == ["claude-20261002-120000", True], "New chat while the paper runs changes nothing"
    assert o["pending"] == [1, True] and o["removed"] is True, "a deletion not done yet is done when the plugin stops"


def test_switching_back_goes_on_with_the_same_conversation(facts):
    s = facts["switchBack"]
    assert s["claude"] is True and s["onCodex"] is True and s["codex"] is True, "Codex goes on with the conversation shown"
    assert s["backClaude"] == [True, 2], "back to Claude Code: the same conversation, with both answers"
    assert s["backCodex"] is True, "back to Codex: the same conversation"
    assert s["claudeAfterNew"] is None and s["newKept"] is None, "a new chat asked for stays new across a switch"


def test_review_cases_of_the_conversations(facts):
    k = facts["appliedKept"]
    assert k["kept"] == ["/data/tmp/scholium/ATT1/config.json", "claude"], "a write that succeeded, though the run then failed"
    assert k["refused"] == k["kept"][0] and k["at"] is True, "a refused write changes nothing"
    assert k["codexFailed"] is False, "nor does a Codex write whose command failed"
    assert facts["legacyFollowUp"] == [["claude-run", 2, True, "S1"]], "an earlier version's follow-up: the annotations counted, a question's conversation"
    e = facts["reviewEdges"]
    assert e["codexBox"] == e["claudeBox"] == "写给 Claude 的话", "words stay with the conversation they were typed to, whichever agent"
    assert e["undoLate"] == [False, 0, None, True, 1], "Undo after the deletion began does nothing; the log goes once"
    assert e["context"] == [{"used": 5, "window": 200000}, {"used": 5, "window": 1000000}, {"used": 5, "window": 1000000}]


def test_the_context_ring_follows_the_session(facts):
    g = facts["gauge"]
    tip = lambda share, used, win: f"上下文窗口：\n{share}% 已用（剩余 {100 - share}%）\n{used} / {win} tokens"
    assert g["running"] is None, "no ring before the model's window is known"
    assert g["runningLog"] == [True, False], "a new conversation's log can be opened while its first run goes on"
    assert g["after"] == {"ring": tip(5, "45k", "1,000k"), "cls": "scholium-ring"} and g["logged"] == g["after"]["ring"]
    assert g["near"] == {"ring": tip(81, "811k", "1,000k"), "cls": "scholium-ring warn"}
    assert g["none"] is None and g["en"] == ["23% used (77% left)", "45k / 200k tokens used"]
    assert g["codex"] == [[None, 1325778], tip(49, "403k", "828k")], "Codex's latest request, in the window it names"


def test_when_a_run_ended_is_shown_under_it(facts):
    t = facts["runTime"]
    assert run_time(t["last"]) == ENDED and t["logged"] == ["scholium", "time", True] and t["last"][1].endswith(" · " + t["shown"])
    assert t["read"] == {"kind": "time", "text": t["shown"], "at": t["at"]}


def test_a_stop_before_the_run_line_logs_nothing(facts):
    assert facts["stopBeforeLine"] == {"logs": [], "handed": ["这篇讲什么？", False, None]}


def test_a_question_and_its_annotation_go_on_after_a_limit_and_an_update(facts):
    lim = facts["askLimit"]
    assert lim["paused"] == {"stop": ["■", "停止"], "queued": [["S1", False, ""]]}
    assert run_time(lim["answered"]) == {"prompt": "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。", "session": "Q1", "state": "完成"}
    assert lim["annotating"] == {"stop": ["■", "停止"], "queued": [["S1", False]]}
    assert lim["annotatePrompt"].startswith("使用 zotero-scholium 技能，为下面这篇论文做整篇标注")
    assert lim["continued"] == "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。", "the task is not sent twice"
    assert lim["resumes"] == [False, True, False, True] and lim["session"] == "Q1" and lim["annotSession"] == "S1"
    u = facts["askUpdate"]
    assert u["question"] == {"handed": [True, False, "这篇怎么估计后验？", None, False],
                             "prompt": "使用 zotero-scholium 技能读下面这篇论文（status 给出题录，extract 给出正文），回答用户在 Zotero 里提的问题。",
                             "resume": False}
    assert u["annotateSent"] == {"handed": [False, True, "", None, False],
                                 "prompt": "使用 zotero-scholium 技能，为下面这篇论文做整篇标注：重点句高亮加译文评论（论文本身是中文时不加评论）、页边批注、阅读笔记，按画像和默认值。",
                                 "resume": False}
    assert u["annotateAnswered"] == {"handed": [False, False, "", "Q1", True], "prompt": "插件更新打断了上面的任务。请从中断的地方继续完成，规则不变。",
                                     "resume": True}
def test_a_failed_deletion_in_view_is_told_once(facts):
    assert facts["deleteFailsInView"] == {"notices": 0, "state": "删除失败：library is read-only", "kind": "scholium-state error"}


def test_transcript_words_follow_the_ui_language(facts):
    w = facts["uiWords"]
    assert w == {"empty": ["（无输出）"], "declined": ["已拒绝"], "exit": "退出码 3"}


def test_the_new_copy_of_an_update_takes_over_and_a_stale_hand_over_is_dropped(facts):
    r = facts["reasons"]
    assert r["takingOver"] == [5, 7, 8] and r["replacing"] == [7, 8]
    assert r["staleDropped"] == "" and r["staleRuns"] == 0


def test_an_update_keeps_a_pause_a_wait_and_words_not_yet_received(facts):
    c = facts["carriedPause"]
    assert c["paused"] == {"until": c["until"], "known": True} and c["calls"] == 0, "the queue waits for the same reset"
    assert any(7_000_000 < w <= 7_260_000 for w in c["waits"])
    assert c["queue"] == [["ATT1", "S1"], ["ATT2", None]]
    assert c["retry"] == {"calls": 0, "queued": [["ATT1", True, True]]}, "a second try keeps its time"
    assert c["undelivered"] == [None, "只标方法部分", False], "the paper starts again with the user's words"


def test_codex_skill_problems_are_named(facts):
    assert facts["codexSkillIssues"] == {
        "failed": ["Codex 列不出它的技能：invalid type: integer", "失败"],
        "errors": ["Codex 列不出它的技能：invalid YAML", "失败"],
        "off": ["Codex 里的 zotero-scholium 技能被停用了：请在 Codex 里重新启用它。", "失败"]}


def test_the_log_keeps_no_image_data_nor_copies(facts):
    s = facts["slimLog"]
    assert s["copy"] is False and s["data"] == "" and s["media"] == "image/png" and s["text"] == "page 3"
    assert s["plain"] is True, "other lines as Claude Code wrote them"
    assert s["shown"] == "⎿ page 3"
    assert s["diff"] == [False, True], "Codex's turn diff stays out"


def test_a_relative_configuration_in_a_windows_folder(facts):
    assert facts["windowsConfig"] == ["D:\\Zotero\\tmp\\scholium\\sub\\config.json", "D:\\Zotero\\tmp\\scholium\\other.json"]


def test_words_go_back_when_the_agent_is_not_found(facts):
    g = facts["givenBack"]
    assert g["box"] == "这篇讲什么？" and g["conversations"] == 0 and g["last"].startswith("找不到 Claude Code")
    assert g["sendDisabled"] is False and "这篇讲什么？" in g["unsent"]


def test_cancel_ends_a_paused_paper_in_its_log_and_section(facts):
    c = facts["cancelPaused"]
    assert c["paused"] == [True, 1] and c["queue"] == 0 and c["pausedAfter"] is False
    assert c["state"] is None and c["ends"] == ["cancelled"] and c["last"] == "已取消重试" and c["timed"] == "time"


def test_a_second_try_paused_by_the_limit_continues_as_any_run(facts):
    p = facts["pauseAfterRetry"]
    assert p["waiting"] == [False, 0] and p["calls"] == 3
    assert p["marks"] == ["run", "prompt", "retry", "run", "run", "continue", "counts", "time"], "the annotation's end, counted"


def test_the_state_line_is_the_conversation_shown(facts):
    assert facts["stateOfConversation"] == {"before": "完成", "fresh": None, "back": "完成"}


def test_a_title_being_typed_survives_the_list_drawn_again(facts):
    r = facts["renameKept"]
    assert r["kept"] == ["input", "半截标题", True, True] and r["titles"] == ["半截标题"] and r["renaming"] is None


def test_a_paper_in_the_trash_is_left_out(facts):
    assert facts["trashed"] == {"queued": 1, "calls": 1, "queue": 0}


def test_an_unreadable_index_is_not_written_over(facts):
    i = facts["indexUnread"]
    assert i["kept"] is True and i["shownConv"] is None and i["tmp"] == []
    assert i["written"] is None and i["tmpWritten"] is True, "a readable one is written through a temporary file"


def test_a_codex_server_that_ends_does_not_lose_the_thread(facts):
    c = facts["codexExit"]
    assert c["gone"] == 0 and c["threads"] == 1 and c["session"] == "T1" and c["state"] == "失败"
    assert c["last"].startswith("Codex app-server 已退出")


def test_a_handed_over_conversation_without_its_log(facts):
    assert facts["logGone"] == {"calls": 1, "logged": True}


def test_sections_share_one_reading_of_a_log(facts):
    assert facts["sharedReading"] == {"reads": 1, "own": 1, "entries": 2}


def test_a_section_keeps_the_transcript_it_showed_live(facts):
    k = facts["keptTranscript"]
    assert k["same"] is True and k["runs"] == 2 and k["state"] == "完成" and k["entries"] == k["again"]


def test_texts_in_each_language(facts):
    t = facts["texts"]
    assert t["turns"] == ["1 turn", "3 turns", "1 轮"]
    assert t["failures"] == ["达到轮数上限", "失败", "失败", "失败"]
    assert t["exited"] == ["Codex app-server 已退出：boom", "codex app-server exited"]
    assert t["entry"] == ["达到轮数上限"]
    assert t["links"] == [False, True, True, False], "mailto: is not followed"
