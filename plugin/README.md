# scholium-bridge

The plugin has four functions:

- **Reader toggle** (Zotero 7 and later): shows or hides the tool's annotations in the reader with
  one button.
- **One-click annotation** (Zotero 7 and later): starts Claude Code or Codex in the background to
  annotate the selected paper.
- **Deleting the tool's annotations** (Zotero 7 and later): removes them and the tool's reading notes
  from the selected paper.
- **Write endpoints**: `scholium` writes through them when the plugin is installed, the annotations of
  a run in one transaction; on Zotero 7, 8 and 9, whose local API is read-only, they are its only write
  channel.

## Reader toggle

The eye button at the right end of the reader toolbar shows or hides the annotations that carry the
tool's tag `zotero-scholium` in every reader view at once: reader tabs, reader windows, and the
attachment preview in the item pane. The choice is kept in the preference
`extensions.scholium-bridge.showAnnotations` and applies to readers opened later and after a restart;
until the button is first used, the annotations are hidden. Annotations that the tool writes or
changes while a reader is open follow the current choice; an item-pane preview that is already
showing follows on its next load.

Hiding removes the annotations from the reader's view and sidebar only. The stored annotations, their
synchronisation, searches, and notes created from annotations are not affected. Disabling or removing
the plugin shows them again in open readers.

## One-click annotation

**Annotate** in the *Scholium* section of the item pane starts the Claude Code CLI or the Codex CLI
in the background for the selected paper; papers started while another runs wait in a queue and run
one at a time, and a paper moved to the trash meanwhile is left out. A regular item is annotated through its
best PDF attachment. Only papers in My Library are annotated: for a paper in a group library the section says
so, **Annotate**, **Agent**, **New chat** and **History** are off, and the message box is hidden.

Requirements: Claude Code or Codex installed and signed in, and the zotero-scholium skill installed for
it (`~/.claude/skills/zotero-scholium` for Claude Code; for Codex, `~/.codex/skills/`,
`~/.agents/skills/`, or `<data dir>/.agents/skills/`); a run whose agent does not find the skill ends at
its start (with Codex, the start of a new thread) and says where to put it (when Codex cannot list its
skills, lists them with errors or has the skill switched off, the run ends with what Codex said). The
plugin starts the installed executable unchanged and does not read its credentials; the usage counts
toward the signed-in account.

Each Claude Code run:

- works in the Zotero data directory with `claude -p --output-format stream-json`, the permission
  mode `auto`, file writes pre-approved only inside `<data dir>/tmp/scholium/`, and the skill
  directory added;
- runs without the user's MCP servers and hooks (`--strict-mcp-config`, `disableAllHooks`); the
  user's skills stay;
- logs its events, without the streaming deltas, to the conversation's log,
  `<data dir>/tmp/scholium/<attachment key>/conversations/chat-<time>.jsonl` (an annotation session's
  `annotate-claude-<time>.jsonl`); a tool's result is kept without
  Claude Code's own copy of it and without the data of images (the pages the agent looked at).

Each Codex run:

- talks to `codex app-server` over JSON-RPC, in a new thread or in the conversation's thread, with `<data dir>/tmp/scholium/` as working directory and the zotero-scholium skill
  attached to the first message of a thread;
- runs without the user's MCP servers and installed plugins, switched off for the thread only;
  Codex's `config.toml` is not changed;
- runs in Codex's `workspace-write` sandbox: commands may write only inside `<data dir>/tmp/scholium/`,
  `<data dir>/zotero-scholium/` and `%APPDATA%/zotero-scholium/` (`~/.config/zotero-scholium/` on
  macOS and Linux), and may use the network, which the skill needs for Zotero's local server;
- has Codex's automatic reviewer (`auto_review`) decide on requests beyond the sandbox; a request or
  question that reaches the plugin is declined;
- logs Codex's notifications, without the streaming deltas, the user's message and the turn's diff, to the
  conversation's log (`chat-<time>.jsonl`, an annotation session's `annotate-codex-<time>.jsonl`), between a
  start line and a result line in Claude Code's form.

A line that the log file does not take at once (locked a moment by a virus scanner or a backup) is written
with the next ones; the run goes on.

Both receive the item key, the attachment key, the PDF path, the output directory `<data
dir>/tmp/scholium/<attachment key>` and the profile's path (or that there is none, so that the defaults apply
and no profile is created), and are told not to ask questions or start sub-agents. A question is told to read
the paper with the skill's `status` and `extract` and to write to Zotero only when it asks for that. A session
that has not seen the paper's annotations of the tool is told how many there are and, when the plugin saw them
written, the configuration that wrote them, the agent and the time (kept in `<out dir>/applied.json`); a
session that goes on is told when they were rewritten since its last run, in this conversation (by the other
agent) or another, or that they are gone; an agent whose own rewrite in this conversation was cut away by an
edit is told they were rewritten since its last turn. A follow-up that changes or adds annotations is told to
edit the configuration they were written from, the paper's whole set, and apply it whole with `cleanup: true`.
Besides the agent's events, a conversation's log holds the plugin's own lines: the start of each run with the
user's words, the user's words or **Annotate** as shown (a question's marked as one), a continuation, a
session the agent no longer has, the end of a run that has started and has no result of its own (cancelled,
failed, interrupted), and when each run ended.

Claude Code and Codex share a paper's conversations, a log each in `<out dir>/conversations/` (`chat-<time>.jsonl`),
with an index of their titles and of the one shown. A message goes to the agent chosen, in its own session of that
conversation (`claude -p --resume <session>`, Codex's `thread/resume`), given before the message the turns after the
last one that session saw, and those it saw that the other agent answered again since, numbered by the whole
conversation; the text says the user went on asking in Zotero, some of it answered by another agent, each answer
labelled, and that these turns are part of this conversation. When the agent has no session of the conversation, or no
longer has it (deleted in the Codex app, or cleaned up by Claude Code), a new session goes on with it and is given the
conversation first. Codex gets it as items of the new thread (`thread/inject_items`) when all the earlier answers are
its own and it takes items; otherwise, and for Claude Code, it is text before the message, each answer labelled with
the agent that gave it. It gets each exchange's words and final answer; beyond ten exchanges, the latest five whole and
the earlier ones as excerpts (250 characters of the words, 400 of the answer). A failed queued message retried after a
newer message went first is asked again as a new question at the end; the failed one stays in the conversation with its
failure and the agent is not given those words twice. A continuation after a limit or an update has nothing to go on
with in a new session, and ends with that reason. The logs of earlier versions, `claude-run.jsonl`, `codex-run.jsonl`,
`claude-<time>.jsonl` and `codex-<time>.jsonl`, are in the list and go on where they are. The files in the output
directory, such as the configuration the annotations were written from, are the same for every conversation.

The *Scholium* section of the item pane, in the library and in the reader's side pane, fills the pane's height.
The library's section works on the item's best PDF, the reader's on the PDF it shows; the conversations, the
history and the annotation sessions are those of that PDF.

- Two tabs: **Chat** for questions about the paper, **Annotations** for annotating it. A dot on a tab marks a
  run of that tab going on or waiting while the other tab is shown.
- Under the tabs, the settings chip names the model and, smaller and grey, the effort (`Opus 5.5 medium ▾`); its tooltip
  and its layer name the agent. It opens a layer with the three choices; a click outside the layer or Esc closes it:
  - **Agent**: Claude Code or Codex. The conversation shown stays; the next message goes to the agent chosen.
  - **Model**: the models the chosen agent reports, asked once per Zotero session without calling a model:
    Claude Code through the initialize request of its stream-json protocol, Codex through `model/list`
    (hidden models are left out). For Claude Code, the latest Opus (`opus`) is used until another model is
    chosen, and *Claude Code's default* passes no `--model`. For Codex, *Codex's default* is used until
    another model is chosen; it names the model of Codex's `config.toml`.
  - **Effort**: the levels the chosen model accepts. It starts at `medium` and keeps the last choice; a model
    that does not accept that level gets `medium` (or its lowest level), and a model without levels gets no
    effort.

  The choices apply to the runs started afterwards, are saved for each agent, and are shared by all panes.
- Beside the chip, one line of state for the tab shown: while a question runs, only its dot; while an annotation runs,
  "step 3/6" (「第 3/6 步」); the tooltip gives the time. A compaction's line keeps its time: "Compacting · 12s"
  (「正在压缩 · 12s」). The line also shows the attempt while the agent's connection is tried again, the place in the
  queue and a pause for the usage limit with **Continue now**. Otherwise, on the Chat tab, the latest outcome of the
  conversation shown with its time, turns and tokens (the tooltip splits the tokens into input, cache and output); on
  the Annotations tab the outcome of **Delete annotations** (a finished annotation's is its card). A narrow pane cuts it
  with an ellipsis.
- ⋯ on the Chat tab holds **Show log** (the conversation's log file), **Personal profile ↗** and **Settings…**;
  on the Annotations tab **Personal profile ↗**, **Show log**, **Delete annotations** and **Settings…**.
  **Settings…** opens the Scholium page of Zotero's settings.

**Chat tab**

- **＋** starts a new conversation (its first message starts it). **🕘** lists the conversations of the PDF by day
  (today, yesterday, the previous 7 and 30 days, older), titled by their first message, the one shown highlighted: a
  click opens one, ✎ renames it (Enter keeps the new title, Esc the old one), 🗑 deletes it (**Undo** brings it back for
  six seconds; every Codex thread the conversation used is archived at the next Codex run once the six seconds end or
  the plugin stops before then). While the paper runs or waits, **＋**, the history and **Agent** are off. ✎, 🗑, the
  quote strip's ✕ and **＋** are icon buttons.
- Saved prompts sit above the Chat tab's box. A click sends one: queued or steered while the agent answers, with the
  quoted passage.
- On hover, ✎ and 🗑 show beside each. ✎ and ＋ edit a label and a prompt in the row.
- A deleted one comes back with **Undo** for six seconds. Dragging one moves it.
- There are four built-in ones until the list is changed (preference `savedPrompts`).
- The user's words are a bubble on the right. While a run goes on, one blue line says "Working for 12s" (「正在处理 12 秒」)
  with a light sweeping across it (the sweep stops when the system asks for reduced motion), and the answer appears as
  it is written; once the answer is there, the steps fold into "Worked for 24s ›" (「已处理 24 秒 ›」), which opens them as
  Claude Code shows them: each tool call with its command or file, and the first lines of each result (errors in red).
  A fold opened or closed by hand stays so. Under an answer, a line gives the agent, the model and the time it ended,
  with a copy button (`Claude Code · Opus 5.5 · 12:01`). A failed question ends with its error and ↻ (**Retry**), which
  sends the same words again to the agent chosen. Web addresses and `zotero://` links in a message open on a click or
  with Enter, in the browser or in Zotero; links to files are shown, not followed.
- On hover, ✎ shows under a question of the Chat tab, except while the paper runs or waits. It turns the question into
  a box in place, with its words and its quote; ✓ or the send shortcut asks again, ✕ or Esc cancels. The box keeps its
  words and quote when the conversation is drawn again, and closes when the question is gone or another conversation is
  shown.
- The question and everything after it are replaced. **Undo** under the new question brings them back for six seconds,
  until another message of the conversation starts, with the conversation's title, and stops the new answer without a
  notice; an edited question that waits for another paper's run leaves the queue. The Codex threads only the replaced
  part used are archived at the next Codex run after the **Undo** window ends or the plugin stops; **Undo** archives
  those only the new part used, at the next Codex run.
- The agent chosen answers. Each agent whose session went past the question goes back to its point before it: Claude
  Code resumes its session at the answer before the question, as a new session (`--resume-session-at`,
  `--fork-session`); Codex forks its thread through the turn before (`thread/fork`).
- Where there is nothing to go back to (a compaction since) or the agent refuses it (an older Claude Code), a new
  session is given the conversation before the question. An edited first question starts a new session, and the
  conversation's title follows it unless it was renamed.
- Words steered into a turn go with it. Annotation sessions cannot be edited.
- Sentence citations: a question asks the agent to cite the paper's sentences by their number in
  `sentences.txt`, as `[#123]`. The section reads `sentences.json` in the paper's output directory and shows a
  cited sentence as a chip with its page (`p.4`); on hover, a card gives the page, **Locate ↗** and the sentence.
  The chip or **Locate ↗** opens the PDF in the reader (or switches to it), goes to the sentence and highlights it
  briefly; a sentence without a position in `sentences.json` opens its page. A number that `sentences.json` does
  not have stays as written.

**Annotations tab**

- Before the first annotation, the tab says what an annotation does (and, for annotations the plugin saw written
  earlier, who wrote them and when); its box takes extra instructions, which may stay empty, and **Annotate**
  starts the run.
- Each **Annotate** starts an annotation session of its own, which the chat does not see and the history does
  not list: a log `annotate-<agent>-<time>.jsonl` in `<out dir>/conversations/`, the latest of each agent in the
  index's `annotation`. **Annotate** in the context menu of several papers starts a session for each.
- While it runs, the tab shows **Annotate** with the extra instructions, the six steps (loading the skill,
  extracting sentences, reading the paper, writing the annotations, checking (dry run), writing to Zotero), each
  done step with its time, and under them "Working for 12s" (「正在处理 12 秒」) with **Details ›** for the steps.
- When it ends, the steps fold and a card gives the outcome: the warnings left, from the agent's closing line;
  the numbers counted on the paper in Zotero (highlights with the core ones, those of the configuration's core
  colour; margin notes; sticky notes; reading notes); the turns, the tokens and the time. A failed annotation
  shows its error with ↻ (**Retry**), which annotates again with the same extra instructions.
- Words typed afterwards continue that annotation session, for example to change some annotations.
  **Annotate again** asks in place, above the box, how many Scholium annotations it replaces (the user's own
  stay); **Replace** starts a new session.

**The box**

- The box at the bottom of each tab takes the user's words. The round button sends them (↑, grey while the box is
  empty); while a run of the tab goes on and the box is empty, it is ■, which stops the run (and takes a waiting
  paper out of the queue); a stopped run ends with ⊘ (**cancelled** on hover); a run stopped while it starts ends before its agent's process, and words its
  conversation does not have yet go back to the box (a queued message to its queue). Esc while a run goes on asks
  once ("Press Esc again to stop") and stops on a second press within three seconds on the same run; with a layer
  open, Esc closes the layer first. The line under the box names the send shortcut. Words typed and not sent are
  kept for each tab and conversation; the words of a message whose agent is not found go back to the box.
- A message sent while the agent answers is queued or steers the answer under way, as the follow-up behavior on
  the settings page says; the opposite shortcut does the other for one message: Ctrl+Enter when Enter sends,
  else Ctrl+Shift+Enter. A steered message joins the answer under way without stopping it (Codex's
  `turn/steer`); Claude Code does not support steering, and its follow-ups always queue.
- Queued messages are listed at the top of the box, one line each, at most three tenths of the pane high: ⠿ drags one
  to another place, a click on its text shows it whole, ↪ (**Steer**) sends it into the answer under way, 🗑
  (**Delete**) deletes it (**Undo** for five seconds), and ⋯ offers **Edit message** (back to the box) and **Turn off
  queueing** (the setting becomes Steer). When an answer ends, the first queued message is sent, marked "Sending".
  After a stop the queue is held: "Queue paused because you interrupted" with ▶ (**Resume**), and each row offers ▶
  (**Send**); a new message sent meanwhile asks whether to **Clear queue** or **Send message** first. A queued message
  that could not be sent is marked ⚠ with ↻ (**Retry**), and the queue waits until it is retried, edited or deleted;
  retried after a newer message went first, it is asked again as a new question at the end. During a compaction, and
  while a stopped answer ends, follow-ups queue. A follow-up joins the queue after the messages and runs waiting for
  its own conversation. The queue is kept in memory for each conversation and is handed over with the running paper
  when the plugin is updated.
- Asking about a passage: in the reader, **Ask Scholium** under the colours of the selection popup shows the Chat tab
  of the reader's section, opening the side pane and the section when they are closed, with the passage and its page
  quoted above the box, and closes the popup as a colour does; the icon ✕ removes the quote. The message tells the
  agent that the user quotes that passage of page N, counted in the PDF as in `sentences.txt` and the citation chips,
  with the page's label where it differs; the box and the transcript show the label, the transcript above the user's
  words. The section drawn for another item has no quote.
- Context ring: beside the round button, a ring whose arc is the share of the model's context window that the
  chosen agent's session of the conversation took up in its latest request (orange from 80%), none while the chosen
  agent has no session of the conversation; its tooltip gives the share used and
  left and the tokens in k. A click opens a layer with the numbers, a bar of input, cache and output, and
  **Compact this conversation's context**; `/compact` in the box, optionally followed by what to keep, does the
  same in the agent chosen's session of the conversation, and stays in the box while the paper runs or the tab shows no
  conversation ("Cannot compact now"). Claude
  Code is sent `/compact` in its session (`claude -p --resume`); Codex compacts its thread with
  `thread/compact/start`. A compaction shows in the transcript as a dashed line, "Compacting context…" and then
  "Context compacted · 850k → 120k"; one the agent made by itself reads "Context compacted automatically".
- **Personal profile ↗** opens the annotation profile `<data dir>/zotero-scholium/profile.md`, which
  every run follows, in an editor over the Zotero window: the Markdown text as it is on the left, and
  on the right a preview that formats it as it is typed and follows its scrolling; colour codes such
  as `#ff6666` get a dot of their colour, and links open as in a message. **Save** closes the
  editor, Ctrl+S keeps it open, **Cancel** or Esc closes it, and asks first when there are unsaved changes;
  closing the window, or an update of the plugin, discards them.
  The file keeps its line ends. A file changed elsewhere since it was opened (for example by
  `scholium profile --from-library`) is overwritten only after a confirmation; an unedited
  text shows the file's current content when Zotero is focused again. A missing profile starts as
  the empty `## User's rules (always win)` section of `scholium profile`'s template, which keeps that
  section when it later writes the statistics, and is written on saving.

**Settings page**

The Scholium page of Zotero's settings holds:

| Setting | Choices | Default |
|---|---|---|
| Send shortcut | Enter / Ctrl + Enter for multiline prompts / Always use Ctrl + Enter | Always use Ctrl + Enter |
| Follow-up behavior | Queue / Steer | Queue |
| Show context window usage | on / off | on |
| Claude Code program | a path, or **Browse…** | empty: found automatically |
| Codex program | a path, or **Browse…** | empty: found automatically |

When a program box is empty, it shows the program found, greyed, or `Not found`. When an agent's program is not found, the message points to this page.

While Zotero is in front, a notice in the corner of the window appears when a paper starts and when it
ends, and closes by itself; while Zotero is in the background, a system notification reports the end
instead. They give the run's last line a part per line (counts, remaining warnings), without the note's
title, or the error. Neither appears while the paper's Scholium section is on screen in the focused
Zotero window, whose state line says the same.

When a run fails on the connection to the agent's service (a timeout, a lost connection, an
overloaded or failing server) before the agent has used any tool, the paper is tried once more after
30 seconds; it waits at the head of the queue meanwhile, and ■ ends the wait. The transcript
and the log keep the failed try.

When the agent reports that the usage limit is reached, the queue waits: the interrupted paper
stays at its head, the state line and a notice give the reset time, and a minute after the reset the
paper continues its conversation where it stopped, followed by the rest of the queue. Without a reset
time the queue tries again after ten minutes. A limit of the service rather than of the account (“not
your usage limit”) is named as such, and the queue waits as long as its message says. **Continue now** in
the section ends the wait at once.

When the plugin is updated while a paper runs, the run ends and its log records the interruption; the
new version continues that paper's conversation, then runs the papers still waiting, and a pause for a
limit or a wait for a second try goes on; a paper whose agent had not yet received its prompt is handed
over as it was queued, the user's words with it; a compaction under way is handed over as a compaction, with what
to keep, and runs again. Disabling the plugin or quitting Zotero ends a run the same way, without handing the papers
over: the paper's history shows the run as interrupted; ↻ (**Retry**) on a run that ended before its answer runs it
again, and a new message continues the conversation.

Papers that already carry the tool's annotations are annotated again only after a confirmation (on the
Annotations tab, in place above the box); the new run replaces those annotations.

| Preference | Default | Meaning |
|---|---|---|
| `extensions.scholium-bridge.agent` | `claude` | `claude` or `codex`; set in the Scholium section |
| `extensions.scholium-bridge.claudePath` | found automatically | path of the `claude` executable; set on the settings page |
| `extensions.scholium-bridge.claudeModel` | `opus` (the latest Opus) | value of `--model`, none when empty; set in the Scholium section |
| `extensions.scholium-bridge.claudeEffort` | `medium` | value of `--effort`; set in the Scholium section |
| `extensions.scholium-bridge.claudePermissionMode` | `auto` | value of `--permission-mode` |
| `extensions.scholium-bridge.codexPath` | the newest copy found | path of the `codex` executable; set on the settings page |
| `extensions.scholium-bridge.codexModel` | empty (Codex's default) | Codex model; set in the Scholium section |
| `extensions.scholium-bridge.codexEffort` | `medium` | Codex reasoning effort; set in the Scholium section |
| `extensions.scholium-bridge.sendShortcut` | `cmdAlways` | `enter`, `cmdIfMultiline` or `cmdAlways`; set on the settings page |
| `extensions.scholium-bridge.followUpMode` | `queue` | `queue` or `steer`; set on the settings page |
| `extensions.scholium-bridge.contextRing` | `true` | whether the context ring shows; set on the settings page |
| `extensions.scholium-bridge.savedPrompts` | empty (the four built-in prompts) | the saved prompts as a JSON array of `{label, prompt}`; set in the Scholium section |

## Deleting the tool's annotations

**Delete annotations** in the ⋯ menu of the Scholium section's Annotations tab, after a confirmation that
states the counts, permanently deletes the annotations tagged `zotero-scholium` on every PDF attachment of the
selected paper, and moves the paper's reading notes tagged `zotero-scholium` to the trash, where they can be
restored. Annotations and notes without that tag are kept; a paper with an attachment being annotated
or queued is left alone, notes included; messages held after a stop do not count. The outcome shows on the
Annotations tab's state line.
The deletion syncs like any deletion in Zotero. The configuration of an earlier run stays in
`<data dir>/tmp/scholium/<attachment key>/config.json`; applying it with the skill's script writes the
annotations again.

## Write endpoints

The plugin registers three endpoints on Zotero's built-in local HTTP server (`http://127.0.0.1:23119`,
which listens on localhost only):

| Endpoint | Purpose |
|---|---|
| `GET /scholium-bridge/ping` | returns `{ok, version, dataDir}`; no token required |
| `POST /scholium-bridge/list` | lists the annotations of one attachment (the tool's own whole, with the dates they were added and changed) and the child notes of its parent item, with their tags, and the plugin's version |
| `POST /scholium-bridge/apply` | writes a child note (unless a note of the tool has the same text), then, in one transaction, creates highlights and text annotations and, with `cleanup`, deletes those the tool created earlier; with `note.trashOwn`, moves the tool's earlier notes to the trash; returns the keys it created |

Requests must carry the header `X-Annotate-Token`, whose value is the content of
`<Zotero data directory>/scholium-bridge.token`, a random string written by the plugin on first
start. The endpoints accept **data only**; no code is evaluated. The `apply` endpoint can create
annotations and notes, can delete only annotations that carry the tool's tag, or, when
`cleanupExternal: true` is passed explicitly, annotations that Zotero imported from the PDF file, and
can move to the trash only notes that carry the tool's tag. The tool's tags (`zotero-scholium` and those
of its earlier versions) are fixed in the plugin, and a request naming another tag is refused; a note
goes only under the attachment's own parent item.

## Installation

In Zotero, open Tools → Plugins, click the gear icon, choose *Install Plugin From File…*, and select
`scholium-bridge.xpi` (available from the GitHub release, or built locally as described below). No
restart is required. One-click runs read the library through Zotero's local API: turn it on in
Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*.

## Build

```bash
cd plugin/scholium-bridge
zip -r ../scholium-bridge.xpi manifest.json bootstrap.js prefs.js settings.xhtml settings.js content locale
```

`manifest.json`, `bootstrap.js`, `prefs.js`, `settings.xhtml`, `settings.js` and the `content/` and `locale/` folders
must be located at the root of the archive. `prefs.js` holds the defaults of the settings page's preferences,
`settings.xhtml` and `settings.js` the page.
`content/` holds the section's icons and its stylesheet `scholium.css`, which uses Zotero's theme variables.

## Notes for plugin authors

Every annotation reaches a reader view through `ReaderInstance.prototype._getAnnotation`, when the
reader opens and when Zotero reports added or modified items; the toggle wraps that method and
returns `null` for hidden annotations. `ReaderInstance` is not exported, so the prototype is reached
through the first reader instance: an open reader at startup, or a reader caught as Zotero pushes it
to `Zotero.Reader._readers` (before it loads its annotations) or returns it from
`Zotero.Reader.openPreview`. These two hooks are removed once the prototype is reached. The button is
added through `Zotero.Reader.registerEventListener("renderToolbar", …)`.

The `content/` folder is registered as `chrome://scholium-bridge-<version>/content/`, with the plugin
version in the package name. Zotero keeps the stylesheets of a chrome address after a plugin is
installed over a running copy, so under a fixed address the section would get the previous version's
stylesheet. The profile editor is built in the main window's page, like the section, rather than in a
window of its own.

Codex is looked for in the Codex app's own folders (`%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe`,
renamed with each update), in the native binary inside npm's `@openai/codex` package (npm's `codex`
is a `.cmd` shim, which cannot be started without a shell), in Cargo's and Homebrew's folders, and
on PATH; of the copies found, the one reporting the newest version is used, since an older Codex may
not read a `config.toml` written by a newer one. A project skill in `<data dir>/.agents/skills/` is
not seen from `<data dir>/tmp/scholium/`, so it is added for the thread with `skills/extraRoots/set`,
which does not change Codex's configuration.

The `init` method of an endpoint class must declare exactly one parameter. Zotero's server inspects
`init.length` and treats an arity of 0 or 2 as the legacy callback style, in which case the request
never resolves.
