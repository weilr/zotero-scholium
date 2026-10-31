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
  `<data dir>/tmp/scholium/<attachment key>/conversations/claude-<time>.jsonl`; a tool's result is kept without
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
  conversation's log (`codex-<time>.jsonl`), between a start line and a result line in Claude Code's form.

A line that the log file does not take at once (locked a moment by a virus scanner or a backup) is written
with the next ones; the run goes on.

Both receive the item key, the attachment key, the PDF path, the output directory
`<data dir>/tmp/scholium/<attachment key>` and the profile's path (or that there is none, so that the
defaults apply and no profile is created), and are told not to ask questions or start sub-agents. A
question is told to read the paper with the skill's `status` and `extract` and to write to Zotero only
when it asks for that. A session that has not seen the paper's annotations of the tool is told how many
there are and, when the plugin saw them written, the configuration that wrote them, the agent and the time
(kept in `<out dir>/applied.json`); a session that goes on is told when another conversation rewrote them since
its last run, or that they are gone. A follow-up that changes or adds annotations is told to edit the
configuration they were written from, the paper's whole set, and apply it whole with `cleanup: true`. Besides the
agent's events, a conversation's log holds the plugin's own lines: the start of each run with the user's words,
the user's words or **Annotate** as shown (a question's marked as one), a continuation, a session the agent no
longer has, the end of a run that has started and has no result of its own (cancelled, failed, interrupted), and
when each run ended.

As in llm-for-zotero, each agent has its own conversations of a paper, a log each in `<out dir>/conversations/`,
with an index of their titles and of the one each agent goes on with. A message and **Annotate** go to that
conversation, in the agent's session there (`claude -p --resume <session>`, Codex's `thread/resume`). When the
conversation has no session, or the agent no longer has it (deleted in the Codex app, or cleaned up by Claude
Code), a new session goes on with it and is given the conversation first: Codex as items of the new thread
(`thread/inject_items`), Claude Code, and a Codex that does not take items, as text before the message. It gets
each exchange's words and final answer; beyond ten exchanges, the latest five whole and the earlier ones as
excerpts (250 characters of the words, 400 of the answer). A continuation after a limit or an update has nothing
to go on with in a new session, and ends with that reason. The logs of earlier versions, `claude-run.jsonl` and
`codex-run.jsonl`, are each agent's first conversation and go on where they are. The files in the output
directory, such as the configuration the annotations were written from, are the same for every conversation.

The *Scholium* section of the item pane, in the library and in the reader's side pane, fills the pane's height.

- Two tabs: **Chat** for questions about the paper, **Annotations** for annotating it. A dot on a tab marks a
  run of that tab going on or waiting while the other tab is shown.
- Under the tabs, a settings chip names the agent, the model and the effort (`Claude Code · Opus 5.5 · medium ▾`)
  and opens a layer with the three choices; a click outside the layer or Esc closes it:
  - **Agent**: Claude Code or Codex. As in llm-for-zotero, a switch starts a new conversation of the paper
    shown; other papers show the conversation that agent goes on with.
  - **Model**: the models the chosen agent reports, asked once per Zotero session without calling a model:
    Claude Code through the initialize request of its stream-json protocol, Codex through `model/list`
    (hidden models are left out). For Claude Code, the latest Opus (`opus`) is used until another model is
    chosen, and *Claude Code's default* passes no `--model`. For Codex, *Codex's default* is used until
    another model is chosen; it names the model of Codex's `config.toml`.
  - **Effort**: the levels the chosen model accepts. It starts at `medium` and keeps the last choice; a model
    that does not accept that level gets `medium` (or its lowest level), and a model without levels gets no
    effort.

  The choices apply to the runs started afterwards, are saved for each agent, and are shared by all panes.
- Beside the chip, one line of state for the tab shown: the step of six and the elapsed time while an
  annotation runs (for a question, the step's name), the attempt while the agent's connection is tried again,
  the place in the queue, a pause for the usage limit with **Continue now**, the latest outcome of the
  conversation shown with its time, turns and tokens (the tooltip splits the tokens into input, cache and
  output), or the deletion. A narrow pane cuts it with an ellipsis.
- ⋯ on the Chat tab holds **Show log** (the conversation's log file), **Personal profile ↗** and **Settings…**;
  on the Annotations tab **Personal profile ↗**, **Show log**, **Delete annotations** and **Settings…**.
  **Settings…** opens the Scholium page of Zotero's settings.

**Chat tab**

- **＋** starts a new conversation with the chosen agent (its first message starts it); **History** lists the
  agent's conversations of the paper, newest first, by day (today, yesterday, the previous 7 and 30 days, older),
  titled by their first message, to open one, rename it (Enter keeps the new title, Esc the old one) or delete it
  (**Undo** brings it back for six seconds; a deleted Codex conversation's thread is archived at the next Codex
  run). While the paper runs or waits, **＋**, **History** and **Agent** are off.
- The process is shown as Claude Code shows it: the user's words or **Annotate**, the agent and model, the
  agent's text, each tool call with its command or file, and the first lines of each result (errors in red),
  and under each run the time it ended; a failed run ends with its error. A running paper is shown live,
  otherwise the conversation the chosen agent goes on with; when that agent has none of the paper and the
  other one has, the section says so. Web addresses and `zotero://` links in a message open on a click or with
  Enter, in the browser or in Zotero; links to files are shown, not followed.

**Annotations tab**

- Before the first annotation, the tab says what an annotation does; its box takes extra instructions, which may
  stay empty, and **Annotate** starts the run.
- **Annotate** goes on in the conversation shown on the Chat tab, where its run shows, with the box's words as
  extra instructions; a redo there still has the earlier run in its context.

**The box**

- The box at the bottom of each tab takes the user's words. The round button sends them (↑, grey while the box is
  empty); while a run of the tab goes on and the box is empty, it is ■, which stops the run (and takes a waiting
  paper out of the queue). Esc while a run goes on asks once ("Press Esc again to stop") and stops on a second
  press within three seconds; with a layer open, Esc closes the layer first. The line under the box names the send
  shortcut. Words typed and not sent are kept for each tab and conversation; the words of a message whose agent is
  not found go back to the box.
- Context ring: beside the round button, a ring whose arc is the share of the model's context window that the
  conversation's session took up in its latest request (orange from 80%); its tooltip gives the share used and
  left and the tokens in k. A click opens a layer with the numbers and a bar of input, cache and output.
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

When an agent's program is not found, the message points to this page.

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
over as it was queued, the user's words with it. Disabling the
plugin or quitting Zotero ends a run the same way, without handing the papers over: the paper's history
shows the run as interrupted, and **Send** continues it.

Papers that already carry the tool's annotations are annotated again only after a confirmation; the
new run replaces those annotations.

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

## Deleting the tool's annotations

**Delete annotations** in the ⋯ menu of the Scholium section's Annotations tab, after a confirmation that
states the counts, permanently deletes the annotations tagged `zotero-scholium` on every PDF attachment of the
selected paper, and moves the paper's reading notes tagged `zotero-scholium` to the trash, where they can be
restored. Annotations and notes without that tag are kept; a paper with an attachment being annotated
or queued is left alone, notes included.
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
