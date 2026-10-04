# scholium-bridge

The plugin has four functions:

- **Reader toggle** (Zotero 7 and later): shows or hides the tool's annotations in the reader with
  one button.
- **One-click annotation** (Zotero 7 and later): starts Claude Code or Codex in the background to
  annotate the selected paper.
- **Deleting the tool's annotations** (Zotero 7 and later): removes them and the tool's reading notes
  from the selected paper.
- **Write endpoints** (needed on Zotero 7 to 9 only): Zotero 10 provides an official local API with
  write support, which `scholium` uses directly; the local API of Zotero 7, 8, and 9 is read-only.

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
one at a time. A regular item is annotated through its best PDF attachment.

Requirements: Claude Code or Codex installed and signed in, and the zotero-scholium skill installed
for it (`~/.claude/skills/zotero-scholium` for Claude Code; for Codex, `~/.codex/skills/`,
`~/.agents/skills/`, or `<data dir>/.agents/skills/`). The plugin starts the installed executable
unchanged and does not read its credentials; the usage counts toward the signed-in account.

Each Claude Code run:

- works in the Zotero data directory with `claude -p --output-format stream-json`, the permission
  mode `auto`, file writes pre-approved only inside `<data dir>/tmp/scholium/`, and the skill
  directory added;
- logs every event to `<data dir>/tmp/scholium/<attachment key>/claude-run.jsonl`.

Each Codex run:

- talks to `codex app-server` over JSON-RPC, in a new thread or, for a follow-up, in the paper's
  thread, with `<data dir>/tmp/scholium/` as working directory and the zotero-scholium skill
  attached to the message;
- runs in Codex's `workspace-write` sandbox: commands may write only inside `<data dir>/tmp/scholium/`,
  `<data dir>/zotero-scholium/` and `%APPDATA%/zotero-scholium/` (`~/.config/zotero-scholium/` on
  macOS and Linux), and may use the network, which the skill needs for Zotero's local server;
- has Codex's automatic reviewer (`auto_review`) decide on requests beyond the sandbox; a request or
  question that reaches the plugin is declined;
- logs Codex's notifications, without the streaming deltas, to
  `<data dir>/tmp/scholium/<attachment key>/codex-run.jsonl`, between a start line and a result line
  in Claude Code's form.

Both receive the item key, the attachment key, the PDF path, and the output directory
`<data dir>/tmp/scholium/<attachment key>`, and are told not to ask questions or start sub-agents. A
follow-up adds to the paper's log.

The *Scholium* section of the item pane, in the library and in the reader's side pane, holds the
controls and the process of the selected paper:

- **Agent** chooses Claude Code or Codex for the papers started afterwards.
- **Model** lists the models the chosen agent reports, asked once per Zotero session without calling
  a model: Claude Code through the initialize request of its stream-json protocol, Codex through
  `model/list` (hidden models are left out). For Claude Code, the latest Opus (`opus`) is used until
  another model is chosen, and *Claude Code's default* passes no `--model`. For Codex, *Codex's
  default* is used until another model is chosen; it names the model of Codex's `config.toml`.
- **Effort** lists the levels the chosen model accepts. It starts at `medium` and keeps the last
  choice; a model that does not accept that level gets `medium` (or its lowest level), and a model
  without levels gets no effort.
- The choices apply to the papers started afterwards, are saved for each agent, and are shared by all
  panes.
- **Annotate**, **Cancel** and **Delete annotations** act on the selected paper; **Cancel** also takes
  a queued paper out of the queue. **Show log** above the transcript shows the log file.
- A state line shows the step of six and the elapsed time while the paper runs, its place in the
  queue, its latest outcome with the minutes, turns and tokens of the run (the tooltip splits the
  tokens into input, cache and output), or the deletion, and the paper being annotated when it is
  another one. For a paper run earlier, the outcome comes from the saved log.
- The process is shown as Claude Code shows it: the agent's text, each tool call with its command or
  file, and the first lines of each result (errors in red); a failed run ends with its error. A
  running paper is shown live; for a paper run earlier the latest saved log, of either agent, is
  shown. The box is resized at its lower edge, and its height is kept.
- **Personal profile ↗** opens the annotation profile `<data dir>/zotero-scholium/profile.md`, which
  every run follows, in an editor over the Zotero window: the Markdown text as it is on the left, and
  on the right a preview that formats it as it is typed and follows its scrolling; colour codes such
  as `#ff6666` get a dot of their colour, and links are shown, not followed. **Save** closes the
  editor, Ctrl+S keeps it open, **Cancel** or Esc closes it. Closing with unsaved changes asks first.
  The file keeps its line ends. A file changed elsewhere since it was opened (for example by
  `scholium profile --from-library`) is overwritten only after a confirmation; an unedited
  text shows the file's current content when Zotero is focused again. A missing profile starts as
  the empty `## User's rules (always win)` section of `scholium profile`'s template, which keeps that
  section when it later writes the statistics, and is written on saving.
- The box below the transcript takes the user's words. With **Annotate** they go to the new run as
  extra instructions. Once the paper has a run, **Send** (or Ctrl+Enter) continues that run's
  conversation with them, with the agent that held it (`claude -p --resume <session>`, or Codex's
  `thread/resume`), for example to change some annotations. The words appear in the transcript.

A notice in the corner of the window appears when a paper starts and when it ends, and closes by itself; when a paper ends, a system
notification reports the run's last line or the error. Both show the last line a part per line
(counts, remaining warnings), without the note's title.
Neither appears while a Scholium section is on screen in the focused Zotero window.

When a run fails on the connection to the agent's service (a timeout, a lost connection, an
overloaded or failing server) before the agent has used any tool, the paper is tried once more after
30 seconds; it waits at the head of the queue meanwhile, and **Cancel** ends the wait. The transcript
and the log keep the failed try.

When the agent reports that the usage limit is reached, the queue waits: the interrupted paper
stays at its head, the state line and a notice give the reset time, and a minute after the reset the
paper continues its conversation where it stopped, followed by the rest of the queue. Without a reset
time the queue tries again after ten minutes. **Continue now** in the section ends the wait at once.

Papers that already carry the tool's annotations are annotated again only after a confirmation; the
new run replaces those annotations.

| Preference | Default | Meaning |
|---|---|---|
| `extensions.scholium-bridge.agent` | `claude` | `claude` or `codex`; set in the Scholium section |
| `extensions.scholium-bridge.claudePath` | found automatically | path of the `claude` executable |
| `extensions.scholium-bridge.claudeModel` | `opus` (the latest Opus) | value of `--model`, none when empty; set in the Scholium section |
| `extensions.scholium-bridge.claudeEffort` | `medium` | value of `--effort`; set in the Scholium section |
| `extensions.scholium-bridge.claudePermissionMode` | `auto` | value of `--permission-mode` |
| `extensions.scholium-bridge.codexPath` | the newest copy found | path of the `codex` executable |
| `extensions.scholium-bridge.codexModel` | empty (Codex's default) | Codex model; set in the Scholium section |
| `extensions.scholium-bridge.codexEffort` | `medium` | Codex reasoning effort; set in the Scholium section |
| `extensions.scholium-bridge.logHeight` | `320` | height of the transcript box in pixels; set by resizing it |

## Deleting the tool's annotations

**Delete annotations** in the Scholium section, after a confirmation that states the counts,
permanently deletes the annotations tagged `zotero-scholium` on every PDF attachment of the selected
paper, and moves the paper's reading notes tagged `zotero-scholium` to the trash, where they can be
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
| `POST /scholium-bridge/list` | lists the annotations of one attachment and the child notes of its parent item |
| `POST /scholium-bridge/apply` | deletes annotations previously created by the tool, then creates highlights, text annotations, and optionally a child note |

Requests must carry the header `X-Annotate-Token`, whose value is the content of
`<Zotero data directory>/scholium-bridge.token`, a random string written by the plugin on first
start. The endpoints accept **data only**; no code is evaluated. The `apply` endpoint can create
annotations and notes, and can delete only annotations that carry the tool's tag, or, when
`cleanupExternal: true` is passed explicitly, annotations that Zotero imported from the PDF file.

## Installation

In Zotero, open Tools → Plugins, click the gear icon, choose *Install Plugin From File…*, and select
`scholium-bridge.xpi` (available from the GitHub release, or built locally as described below). No
restart is required.

## Build

```bash
cd plugin/scholium-bridge
zip -r ../scholium-bridge.xpi manifest.json bootstrap.js content locale
```

`manifest.json`, `bootstrap.js` and the `content/` and `locale/` folders must be located at the root of the archive.
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
