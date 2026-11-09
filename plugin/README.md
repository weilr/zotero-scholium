# Scholium

The plugin has five functions:

- **Questions about the paper** (Zotero 7 and later): the Chat tab of the Scholium section answers questions with
  Claude Code or Codex, also about a passage selected in the reader (**Ask Scholium**), and cites the paper's
  sentences.
- **Reader toggle** (Zotero 7 and later): shows or hides the tool's annotations in the reader with
  one button.
- **One-click annotation** (Zotero 7 and later): starts Claude Code or Codex in the background to
  annotate the selected paper.
- **Deleting the tool's annotations** (Zotero 7 and later): removes them from the PDF the Scholium section
  shows, and moves the paper's reading notes of the tool to the trash.
- **Write endpoints**: `scholium` writes through them when the plugin is installed, the annotations of
  a run in one transaction; on Zotero 7, 8 and 9, whose local API is read-only, they are its only write
  channel.

## Reader toggle

The eye button at the right end of the reader toolbar shows or hides the annotations that carry the
tool's tag `zotero-scholium` in every reader view at once: reader tabs, reader windows, and the
attachment preview in the item pane. The choice is kept in the preference
`extensions.scholium.showAnnotations` and applies to readers opened later and after a restart;
until the button is first used, the annotations are hidden, and the first annotation that writes turns the
button on (an annotation run of the plugin, or any write through its endpoint); from then on only the button
changes it. Annotations that the tool writes or changes while a reader is open follow the current choice; an item-pane preview that is already
showing follows on its next load.

Hiding removes the annotations from the reader's view and sidebar only. The stored annotations, their
synchronisation, searches, and notes created from annotations are not affected. Disabling or removing
the plugin shows them again in open readers.

## One-click annotation

**Annotate** in the *Scholium* section of the item pane starts the Claude Code CLI or the Codex CLI
in the background for the selected paper; papers started while another runs wait in a queue and run
one at a time, and a paper moved to the trash meanwhile is left out. A regular item is annotated through its
best PDF attachment. A paper in a group library is annotated as one in My Library, into the group's library, where
every member sees the annotations: the first annotation in each group asks once, and **Annotate again** and **Delete
annotations** say that the change is the group's. When the user cannot edit the group's library or its files, the
annotation tab says so and has no **Annotate** and no message box; questions in the chat are answered. paper.json then
names the library (`library_id`, `group_id`), and the paper's runs and files are kept under `<key>_g<group id>`, since
a key is unique only in its library.

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
  directory (`skills/zotero-scholium` in `CLAUDE_CONFIG_DIR`, else in `~/.claude`) added when it is there;
- runs without the user's MCP servers and hooks (`--strict-mcp-config`, `disableAllHooks`); the
  user's skills stay;
- has only the tools it uses (`--tools`): Skill, Bash, PowerShell, Read, Write, Edit, Grep and Glob, and in a
  chat also WebSearch and WebFetch;
- in an annotation and in words to its session, writes at most 32,000 tokens in one turn, its thinking included
  (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`), unless the user's environment sets that variable;
- logs its events, without the streaming deltas, to the conversation's log,
  `<data dir>/tmp/scholium/<attachment key>/conversations/chat-<time>.jsonl` (an annotation session's
  `annotate-claude-<time>.jsonl`); a tool's result is kept without
  Claude Code's own copy of it and without the data of images (the pages the agent looked at).

Each Codex run:

- talks to `codex app-server` over JSON-RPC, in a new thread or in the conversation's thread, with `<data dir>/tmp/scholium/` as working directory and the zotero-scholium skill
  attached to the first message of a thread;
- runs with the user's MCP servers and installed plugins switched off for the thread only; Codex's `config.toml` is
  neither changed nor read: the servers' names come from Codex's `mcpServerStatus/list`, which starts each server to
  list it. A run while no names are kept (the first Codex run) waits at most 10 s for the list; if none comes, it and
  the session's next Codex runs have the user's MCP servers until a list made in a separate Codex process after it
  names them. Later runs use the names kept in the preference `codexServers` and list them again in a separate Codex
  process after the session's first Codex run;
- runs in Codex's `workspace-write` sandbox: commands may write only inside `<data dir>/tmp/scholium/`,
  `<data dir>/zotero-scholium/` and `%APPDATA%/zotero-scholium/` (`~/.config/zotero-scholium/` on
  macOS and Linux), and may use the network, which the skill needs for Zotero's local server; uv's cache and the
  Pythons it installs go to `<data dir>/tmp/scholium/uv/` (`UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`) unless these
  variables are set;
- has Codex's automatic reviewer (`auto_review`) decide on requests beyond the sandbox; a request or
  question that reaches the plugin is declined;
- logs Codex's notifications, without the streaming deltas, the user's message and the turn's diff, to the
  conversation's log (`chat-<time>.jsonl`, an annotation session's `annotate-codex-<time>.jsonl`), between a
  start line and a result line in Claude Code's form.

A line that the log file does not take at once (locked a moment by a virus scanner or a backup) is written
with the next ones; the run goes on.

Both receive the item key, the attachment key, the output directory `<data
dir>/tmp/scholium/<attachment key>`, the file `paper.json` in it and the profile's path (or that there is none, so that the defaults apply
and no profile is created), and are told not to ask questions or start sub-agents. Before each run the plugin writes
`paper.json` (the PDF's path, the item and attachment keys, the output directory); the prompt names that file, not the
PDF's path. It is the plugin's and read-only: only `extract` (in place of `--pdf`) and `--list` take it with
`--config`, and the agent writes its own configuration to another file in the output directory. The annotation's and a
question's prompts say how the script runs on this computer: with `uv run` when uv is on the agents' PATH, else with
the Python found there. Before a new annotation's agent starts, the plugin runs the skill's `status` and `extract` itself
with that command, the agent's environment and the skill's script the agent finds (the section's live line says "Reading
the PDF…", and ■ stops them); the prompt then gives their results, and a scanned PDF ends the run there with its card.
When either fails or does not end in 60 s (`extract`: 180 s), or no skill is found, the agent runs them.
A question is told to read the paper with the skill's `status` and `extract` and to write to Zotero only when it asks for that. A session
that has not seen the paper's annotations of the tool is told how many there are and, when the plugin saw them
written, the configuration that wrote them, the agent and the time (kept in `<out dir>/applied.json`: a write whose output says it was applied, also "partial", is kept whatever the exit
code; one whose configuration is not found or is `paper.json` removes the kept file); a
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
  - **Agent**: Claude Code or Codex. The conversation shown stays, as the layer's note says; the next message goes to
    the agent chosen, and annotation sessions are per agent.
  - **Model**: the models the chosen agent reports, asked once per Zotero session without calling a model:
    Claude Code through the initialize request of its stream-json protocol, Codex through `model/list`
    (hidden models are left out). For Claude Code, the latest Opus (`opus`) is used until another model is
    chosen, and *Claude Code's default* passes no `--model`. For Codex, *Codex's default* is used until
    another model is chosen; it shows no model name until a run with it shows which model that is.
  - **Effort**: the levels the chosen model accepts. It starts at `medium` and keeps the last choice; a model
    that does not accept that level gets `medium` (or its lowest level), and a model without levels gets no
    effort.

  The choices apply to the runs started afterwards, are saved for each agent, and are shared by all panes.
- Beside the chip, one line of state for the tab shown: while a run goes on, only its dot; the tooltip gives the step
  ("step 3/6 reading the paper", 「第 3/6 步 通读论文」) and the time. The line also shows the attempt while the
  agent's connection is tried again, the place in the queue and a pause for the usage limit with **Continue now**.
  Otherwise, on the Chat tab, the latest outcome of the conversation shown with its turns and tokens (the tooltip
  splits the tokens into input, cache and output); on the Annotations tab the outcome of **Delete annotations** (a
  finished annotation's is its card). A narrow pane cuts it with an ellipsis, before the chip.
- ⋯ on the Chat tab holds **Show log** (the conversation's log file), **Personal profile ↗**, **Save as note** and
  **Settings…**; on the Annotations tab **Personal profile ↗**, **Show log**, **Delete annotations**, **Save as note**
  while it shows a session, and **Settings…**. **Save as note** makes the conversation shown a child note of the paper:
  the heading “Scholium conversation: <paper title>” and the date, each question with its quoted passage, and each
  answer with the agent and model that gave it, formulas as Zotero's note editor sets them. The note is tagged
  `scholium-chat`, which Annotate again and Delete annotations leave alone, and is selected in the library.
  **Settings…** opens the Scholium page of Zotero's settings.

**Chat tab**

- **＋** starts a new conversation (its first message starts it). The clock lists the conversations of the PDF by day
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
  Claude Code shows them; a run without steps shows "Worked for 24s" without ›. Every finished run shows it, an
  interrupted one with the duration its log's end line gives, except one stopped while it waited for a usage limit or a
  second try, which shows "Worked ›"
  (「已处理 ›」) when it has steps and nothing otherwise. The steps are: each tool call with its command or file, and the
  first lines of each result (errors in red).
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
  A chip can be focused with Tab, and its card opens on keyboard focus only; Enter or Space locates the sentence.
  The chip or **Locate ↗** opens the PDF in the reader (or switches to it), goes to the sentence and highlights it
  briefly; a sentence without a position in `sentences.json` opens its page. A number that `sentences.json` does
  not have stays as written.

**Annotations tab**

- A paper that carries annotations of the tool (from the skill run on its own, the other agent or an earlier
  version) shows "This paper carries N Scholium annotations" (「这篇已有 N 条 Scholium 批注」), with who wrote them and when
  where the plugin saw them written, and the button reads **Annotate again**. Before the first annotation, the tab
  says what an annotation does; its box takes extra instructions, which may stay empty, and **Annotate**
  starts the run.
- Each **Annotate** starts an annotation session of its own, which the chat does not see and the history does
  not list: a log `annotate-<agent>-<time>.jsonl` in `<out dir>/conversations/`, the latest of each agent in the
  index's `annotation`.
- While it runs, the tab shows **Annotate** with the extra instructions and under them "Working for 12s"
  (「正在处理 12 秒」) with **Details ›** for the steps.
- When it ends, the steps fold and a card gives the outcome: the warnings left, from the agent's closing line;
  the numbers counted on the paper in Zotero (highlights with the core ones, those of the configuration's core
  colour; margin notes; sticky notes; reading notes); the turns and tokens of all its parts (also those before a
  pause for a limit) and the time. A run that left the paper none of the tool's annotations and notes reads "No
  annotations written" (「没有写入批注」), with the warnings left, in orange. A failed annotation shows its error with ↻
  (**Retry**), which annotates again with the same extra instructions.
- Words typed afterwards continue that annotation session, for example to change some annotations.
  **Annotate again** asks in place, above the box, how many Scholium annotations it deletes and how many reading
  notes it moves to the trash (the user's own stay); **Replace** deletes them at once and starts a new session. While it waits behind another paper, the tab shows the coming session, and
  words typed there run in it after the annotation.

**The box**

- The box at the bottom of each tab takes the user's words. The round button sends them (↑, grey while the box is
  empty); while a run of the tab goes on and the box is empty, it is ■, which stops the run (and takes a waiting
  paper out of the queue; the words of a message that waited behind another paper's run go back to its box, and an
  annotation's extra instructions to that tab's box; an edited question that has not started is undone, its **Undo**
  staying while it waits); a stopped run ends with ⊘ (**cancelled** on hover); a run stopped while it starts ends before its agent's process, and words its
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
- Asking about a passage: in the reader, a right click on selected text offers **Ask Scholium** at the end of the
  context menu. It shows the Chat tab of the reader's section, opening the side pane and the section when they are
  closed, with the passage and its page quoted above the box, and clears the selection, with the cursor in the box; the
  icon ✕ removes the quote. It appears in PDF readers only, not in EPUB or snapshot readers. The message tells the
  agent that the user quotes that passage of page N, counted in the PDF as in `sentences.txt` and the citation chips,
  with the page's label where it differs; the box and the transcript show the label, the transcript above the user's
  words. The section drawn for another item has no quote.
- Asking about several papers: with 2 to 8 papers or PDFs selected in the items list, its context menu offers **Ask
  Scholium (N papers)**. It selects the first paper alone and opens its Chat tab on a new conversation (the one under
  way while the paper answers), with the other papers as chips above the box; ✕ on a chip leaves that paper out of the
  next messages. A message goes with every paper's `paper.json`, written as for one paper, and a line of the prompt
  lists them; sentence numbers stay those of the first paper. The conversation is the first paper's, and its log names
  the other papers with each message, so that later messages, a retry and the section drawn again keep them. Questions
  only: the Annotations tab has no chips.
- Context ring: beside the round button, a ring whose arc is the share of the model's context window that the
  chosen agent's session of the conversation took up in its latest request (orange from 80%), none while the chosen
  agent has no session of the conversation; its tooltip gives the share used and
  left and the tokens in k. A click opens a layer with the numbers, a bar of input, cache and output, and
  **Compact this conversation's context**; `/compact` in the box, optionally followed by what to keep, does the
  same in the agent chosen's session of the conversation, and stays in the box while the paper runs or the tab shows no
  conversation ("Cannot compact now"); with nothing to compact yet, the box says so. `/compact` with no session starts
  none. Claude
  Code is sent `/compact` in its session (`claude -p --resume`); Codex compacts its thread with
  `thread/compact/start`. A compaction shows in the transcript as a dashed line, "Compacting context for 12s"
  (「正在压缩上下文 12 秒」, swept by a light as the run line is) and then "Context compacted · 850k → 120k"; while the
  agent compacts by itself during a run, the run's line reads "Compacting context for 43s" and then "Working for" again,
  and the transcript keeps "Context compacted automatically".
- Keyboard: the context ring can be focused, and Enter or Space opens its layer. The settings, ⋯, history, context and
  queued-message layers take the focus when they are opened from the keyboard; Esc or Tab out closes one, and Esc gives
  the focus back to its button. The tabs carry `aria-selected`, and ← → Home End choose one (only the chosen one is a
  Tab stop); ↑ ↓ Home End move through the ⋯ menus and the history. The settings layer starts at the model. Focus rings
  use Zotero's accent colour; text in the accent colours has theme colours of its own that keep 4.5:1.
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

Every process the plugin starts gets `SCHOLIUM_ZOTERO_PORT`, the port of this Zotero's local server
(`httpServer.port`), which the skill's script uses in place of 23119.

Claude Code, Codex, Python and uv are looked for on the agents' PATH, which their processes also get: on macOS and
Linux the PATH of the user's login shell (`$SHELL`, else `/bin/zsh`, read once a session; not used when the shell has
not printed it after 5 s) before Zotero's, then
`~/.local/bin` and `~/.cargo/bin` when they exist; on Windows Zotero's PATH and `%USERPROFILE%\.local\bin`. Claude
Code and Codex are also looked for in their usual install folders (see the notes for plugin authors for Codex).

**Setup check** lists, a line each: Zotero's local API, Claude Code and Codex (found, signed in, the skill), uv, Python
and PyMuPDF, with a button where the plugin can fix it. The uv line gives uv's version and path, or the command that
installs it on this system; with uv, a missing or old Python or PyMuPDF is no fault, since `uv run` provides them.
Once a check has ended, **Copy** puts its lines on the clipboard as plain text, after a line with the versions of
Scholium and Zotero and the operating system, for a bug report.

While Zotero is in front, a notice in the corner of the window appears when a paper starts and when it
ends, and closes by itself; while Zotero is in the background, a system notification reports the end
instead. They give the run's last line a part per line (counts, remaining warnings), without the note's
title, or the error. Neither appears while the paper's Scholium section is on screen in the focused
Zotero window, whose state line says the same.

When a run fails on the connection to the agent's service (a timeout, a lost connection, an
overloaded or failing server) before the agent has used any tool, the paper is tried once more after
30 seconds; it waits at the head of the queue meanwhile, and ■ ends the wait. The transcript
and the log keep the failed try.

When the agent reports that the usage limit is reached, that agent's runs wait, and with them a message queued
behind the interrupted run on the same tab of that paper; the other agent's runs go on. The interrupted paper stays
at the head of the queue, the state line (naming the agent) and a notice give the reset time, and a minute after the
reset the paper continues its conversation where it stopped, followed by that agent's other waiting runs. Without a
reset time that agent's runs try again after ten minutes. A limit of the service rather than of the account (“not
your usage limit”) is named as such, and that agent's runs wait as long as its message says. **Continue now** in the
section ends that agent's wait at once. Only sections whose next run waits for that limit show the pause; "Queued, N
ahead" counts neither held messages nor runs waiting for another limit.

When the plugin is updated while a paper runs, the run ends and its log records the interruption; the
new version continues that paper's conversation, then runs the papers still waiting, and a pause for a
limit or a wait for a second try goes on; a paper whose agent had not yet received its prompt is handed
over as it was queued, the user's words with it; a compaction under way is handed over as a compaction, with what
to keep, and runs again. Disabling the plugin or quitting Zotero ends a run the same way, without handing the papers
over: the paper's history shows the run as interrupted; ↻ (**Retry**) on a run that ended before its answer runs it
again, and a new message continues the conversation.

Papers that already carry the tool's annotations are annotated again only after a confirmation (on the
Annotations tab, in place above the box). The confirmation deletes those annotations at once and moves the tool's
reading notes of the paper to the trash; then the new run starts. When the run fails or is stopped, the paper has none
of the tool's annotations.

If the log refuses the first line of a Chat run, its words go back to the box (a queued message's to its row, marked,
with **Retry**) and the state line says it failed, with the reason; an annotation's extra instructions go back to the
Annotations tab's box. A paper with the logs of both agents from Scholium Bridge 0.1.9 opens the chosen agent's.

At each start the plugin takes over the preferences of Scholium Bridge (`extensions.scholium-bridge.*`) that it has
no value of its own for. It then clears every preference of Scholium Bridge.

| Preference | Default | Meaning |
|---|---|---|
| `extensions.scholium.agent` | `claude` | `claude` or `codex`; set in the Scholium section |
| `extensions.scholium.claudePath` | found automatically | path of the `claude` executable; set on the settings page |
| `extensions.scholium.claudeModel` | `opus` (the latest Opus) | value of `--model`, none when empty; set in the Scholium section |
| `extensions.scholium.claudeEffort` | `medium` | value of `--effort`; set in the Scholium section |
| `extensions.scholium.claudePermissionMode` | `auto` | value of `--permission-mode` |
| `extensions.scholium.codexPath` | the newest copy found | path of the `codex` executable; set on the settings page |
| `extensions.scholium.codexModel` | empty (Codex's default) | Codex model; set in the Scholium section |
| `extensions.scholium.codexEffort` | `medium` | Codex reasoning effort; set in the Scholium section |
| `extensions.scholium.codexServers` | empty (listed at the first Codex run) | the names of the user's Codex MCP servers, switched off in each Codex thread, as `mcpServerStatus/list` gave them; renewed after the first Codex run of each Zotero session |
| `extensions.scholium.codexDefault` | empty | the model a new Codex thread ran with when none was chosen (*Codex's default*), which the model menu names |
| `extensions.scholium.sendShortcut` | `cmdAlways` | `enter`, `cmdIfMultiline` or `cmdAlways`; set on the settings page |
| `extensions.scholium.followUpMode` | `queue` | `queue` or `steer`; set on the settings page |
| `extensions.scholium.contextRing` | `true` | whether the context ring shows; set on the settings page |
| `extensions.scholium.savedPrompts` | empty (the four built-in prompts) | the saved prompts as a JSON array of `{label, prompt}`; set in the Scholium section |

## Deleting the tool's annotations

**Delete annotations** in the ⋯ menu of the Scholium section's Annotations tab, after a confirmation that
states the counts, permanently deletes the annotations tagged `zotero-scholium` on the PDF the section shows, and moves the paper's reading notes tagged `zotero-scholium` to the trash, where they can be
restored. Annotations and notes without that tag are kept; a paper with an attachment being annotated
or queued is left alone, notes included; messages held after a stop do not count. The outcome shows on the
Annotations tab's state line.
The deletion syncs like any deletion in Zotero. The configuration of an earlier run stays in
`<data dir>/tmp/scholium/<attachment key>/config.json`; applying it with the skill's script writes the
annotations again.

## Write endpoints

The plugin registers three endpoints on Zotero's built-in local HTTP server (`http://127.0.0.1:23119`,
which listens on localhost only), and the same three at the paths of Scholium Bridge 0.1.9, which its skill calls:

| Endpoint | Purpose |
|---|---|
| `GET /scholium/ping` | returns `{ok, version, dataDir}`; no token required |
| `POST /scholium/list` | lists the annotations of one attachment (the tool's own whole, with the dates they were added and changed) and the child notes of its parent item, with their tags, and the plugin's version |
| `POST /scholium/apply` | writes a child note (unless a note of the tool has the same text), then, in one transaction, creates highlights and text annotations and, with `cleanup`, deletes those the tool created earlier; with `note.trashOwn`, moves the tool's earlier notes to the trash; returns the keys it created |
| `/scholium-bridge/ping`, `/scholium-bridge/list`, `/scholium-bridge/apply` | the same three, for the skill of Scholium Bridge 0.1.9 |

`list` and `apply` look the attachment up in My Library, or in the library the request names by `groupID` (a group's id)
or `libraryID`; `list` returns that `libraryID`. `apply` refuses a group's library the user cannot edit.

Requests must carry the header `X-Annotate-Token`, whose value is the content of
`<Zotero data directory>/scholium.token`, a random string written by the plugin on first
start, or taken from Scholium Bridge 0.1.9's `scholium-bridge.token` when only that file is there. The plugin writes
the same value to `scholium-bridge.token`, which the skill of Scholium Bridge 0.1.9 reads. The endpoints accept
**data only**; no code is evaluated. The `apply` endpoint can create
annotations and notes, can delete only annotations that carry the tool's tag, or, when
`cleanupExternal: true` is passed explicitly, annotations that Zotero imported from the PDF file, and
can move to the trash only notes that carry the tool's tag. The tool's tags (`zotero-scholium` and those
of its earlier versions) are fixed in the plugin, and a request naming another tag is refused; a note
goes only under the attachment's own parent item.

## Installation

In Zotero, open Tools → Plugins, click the gear icon, choose *Install Plugin From File…*, and select
`scholium.xpi` (available from the GitHub release, or built locally as described below). No
restart is required. One-click runs read the library through Zotero's local API: turn it on in
Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*.

With Scholium Bridge installed (0.1.9 or earlier), install Scholium the same way: at its start it uninstalls Scholium
Bridge (add-on `scholium-bridge@zotero-scholium`) and takes over its preferences and token, and the conversations
stay. A run under way in Scholium Bridge stops when Scholium uninstalls it; its queued messages are not kept.
Scholium Bridge does not update to Scholium by itself.

## Build

```bash
python scripts/build_xpi.py scholium.xpi
python scripts/check_xpi.py scholium.xpi
```

`manifest.json`, `bootstrap.js`, `prefs.js`, `settings.xhtml`, `settings.js` and the `content/`, `locale/` and `modules/`
folders are at the root of the archive, and the skill under `content/skill/zotero-scholium/`, which the plugin installs
when an agent has none. `bootstrap.js` starts and stops the plugin; at its start it loads the files of `modules/`, in
this order, and those after `runner.js` add their methods to `ScholiumRunner`:

| Module | Holds |
|---|---|
| `endpoints.js` | `ScholiumEndpoints`: the write endpoints and their token |
| `toggle.js` | `ScholiumToggle`: the reader toggle |
| `runner.js` | `ScholiumRunner`: its state and constants, the log, the languages and the section's texts in English and Simplified Chinese |
| `setup.js` | the preferences, the agent, model and effort chosen, finding Claude Code, Codex, uv and Python, installing the skill, the setup check |
| `prompts.js` | a paper's PDF, key and library, the prompts, the agents' arguments, `paper.json` and `applied.json`, the words of the steps |
| `section.js` | the items list's menu, log events as display entries, the Scholium section's frame, layers and settings chip, the profile editor, Markdown and formulas, citations and links |
| `conversations.js` | the message box and the queued messages, conversations and their logs, the history, saved prompts, the transcript and the state line |
| `queue.js` | Save as note, notices, Annotate, editing a question, sending, the queue and the pauses for usage limits, the end of a run |
| `agents.js` | a run, Claude Code and Codex, cancelling, deleting the tool's annotations, the runner's start, hand-over and stop |

`prefs.js` holds the defaults of the settings page's preferences, `settings.xhtml` and `settings.js` the page.
`content/` holds the section's icons and its stylesheet `scholium.css`, which uses Zotero's theme variables.
`content/i18n/` holds the section's texts in each language but English and Simplified Chinese (those are in
`modules/runner.js`), one file per folder of `locale/`, which holds the settings page's Fluent files.

## Notes for plugin authors

Every annotation reaches a reader view through `ReaderInstance.prototype._getAnnotation`, when the
reader opens and when Zotero reports added or modified items; the toggle wraps that method and
returns `null` for hidden annotations. `ReaderInstance` is not exported, so the prototype is reached
through the first reader instance: an open reader at startup, or a reader caught as Zotero pushes it
to `Zotero.Reader._readers` (before it loads its annotations) or returns it from
`Zotero.Reader.openPreview`. These two hooks are removed once the prototype is reached. The button is
added through `Zotero.Reader.registerEventListener("renderToolbar", …)`.

The `content/` folder is registered as `chrome://scholium-<version>/content/`, with the plugin
version in the package name. Zotero keeps the stylesheets of a chrome address after a plugin is
installed over a running copy, so under a fixed address the section would get the previous version's
stylesheet. The profile editor is built in the main window's page, like the section, rather than in a
window of its own.

`startup()` loads the modules into `bootstrap.js`'s own scope, once per scope, with
`Services.scriptloader.loadSubScriptWithOptions(rootURI + "modules/…", { target: globalThis, ignoreCache: true })`, as
Zotero loads `bootstrap.js`: a plugin installed over a running copy keeps the files' addresses, and the script cache
would give the previous version's code. Zotero keeps the scope of a disabled plugin, and a start after enabling it
keeps the objects of the first.

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
