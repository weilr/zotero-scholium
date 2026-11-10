# Smoke checks in a throwaway Zotero

`smoke.py` starts a Zotero with a new profile and data folder, installs the plugin and a probe plugin, drives the
Scholium section the way a user would, and prints PASS or FAIL per check. A fake `claude` replays recorded Claude Code
streams, so no model is called. Run it before a release, on each Zotero version the plugin supports.

## Build the fake Claude Code once

The fake is C# source. The .NET Framework compiler that ships with Windows builds it:

```
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /out:%TEMP%\scholium-fake\fakeclaude.exe scripts\smoke\fakeclaude\fakeclaude.cs
```

(From Git Bash, prefix the command with `MSYS_NO_PATHCONV=1`.) Keep the .exe out of the repository. The runner gives
each run its own copy of `fakeclaude/scripts` and `models.json` through `SCHOLIUM_FAKE_DIR`.

## Run

```
python scripts/smoke/smoke.py --zotero "C:\Program Files\Zotero\zotero.exe" --port 23129 --fake %TEMP%\scholium-fake\fakeclaude.exe
```

| Option | Default | Meaning |
|---|---|---|
| `--zotero` | (required) | the `zotero.exe` to test, installed or extracted |
| `--port` | 23129 | the throwaway's local server port; 23119 (the user's Zotero) is refused |
| `--fake` | (required unless only `setup`) | the fake `claude` built above |
| `--git` | (none) | test `plugin/scholium` and `skills/zotero-scholium` as committed at this revision (e.g. `HEAD`), exported byte for byte: no CRLF from `core.autocrlf`, no uncommitted edits |
| `--plugin` | `plugin/scholium` | the plugin source folder, or a built `.xpi` |
| `--skill` | `skills/zotero-scholium` | the skill added in `content/skill` when the plugin has none; `""` for none |
| `--cli` | `<skill>/scripts/scholium.py` | the skill's CLI for the `apply` check |
| `--locale` | `zh-CN` | `zh-CN` or `en-US` |
| `--checks` | `all` | `all`, `fake` (everything but `setup` and `copy`, which need the real programs), or a comma list |
| `--out` | `%TEMP%\scholium-smoke\<time>` | the run folders |
| `--minutes` | 10 | the longest one Zotero start may take |

Exit code 0 means every check passed, no console error named the plugin, and netstat for :23119 was the same before
and after.

Before a release, test what is committed: add `--git HEAD`. To test the package exactly as it will ship, build it
with `python scripts/build_xpi.py %TEMP%\scholium.xpi` and pass `--plugin %TEMP%\scholium.xpi`; a package that
carries the skill keeps its own.

The checks take the sentences they expect (the not-signed-in text, the PyMuPDF card, the menu item, the button
labels) from the running plugin's `text()`, so they follow its wording. On top of that they check what does not
depend on the wording: no "Please run /login", the card names PyMuPDF, the dialog names the local API.

## Checks

| Check | What it does |
|---|---|
| `section` | The Scholium section renders in the item pane, both tabs (Chat / Annotations). |
| `localapi` | With Zotero's local API off, Annotate shows the confirmation. Accepted, the pref turns on, and the run starts and ends with a card. |
| `signedout` | Claude Code's "Not logged in · Please run /login" stream shows the plugin's own sentence in Annotations and in Chat, never "Please run /login". |
| `pymupdf` | A run whose tool result says PyMuPDF is missing ends with the card "No annotations written: PyMuPDF is missing; …". |
| `reselect` | After a fake run, another item is selected (its Scholium section left off-screen), then the paper again. The card of its annotation session is back within 8 seconds. |
| `apply` | The skill's CLI writes two highlights with `core_color` `#FF6666` and a note through `/scholium/apply`. The colours arrive lower-case and there is one note. A second write that Zotero rejects (an invalid sort index) leaves no second note. |
| `reader` | In a reader tab, the context menu of a text selection offers Ask Scholium. Choosing it puts the passage above the Chat box. |
| `groups` | A paper in a local group library. The first Annotate asks once (the plugin's own words), a second does not. The skill's CLI writes into the group with `group_id`, and `list` answers the group's `libraryID`. With the group made not editable, the Annotations tab says so, Annotate is off, and the CLI's write is refused. |
| `skill` | Claude Code's init lists no zotero-scholium skill. The failed card offers "Install the skill and retry". Clicking it installs the package's skill into the run's `CLAUDE_CONFIG_DIR` (byte-identical) and runs again. Without a skill in the package, the hint under the box says so and nothing is written. |
| `port` | The fake records each call's `SCHOLIUM_ZOTERO_PORT`. Every agent run must have the throwaway's port, which the skill's script uses instead of 23119. |
| `adddir` | Every agent run gets `--add-dir <CLAUDE_CONFIG_DIR>/skills/zotero-scholium` exactly when that folder is there as the run starts. It is the run's own folder, empty until the `skill` check installs the skill, so a full run sees both cases. |
| `scanned` | The skill's `extract` on an image-only PDF exits with code 3 and the "no text layer" error. It needs no Zotero. |
| `setup` | The settings page's setup check, in a second Zotero start: the lines, the local API's "Turn on" and the Claude Code skill's "Install". It needs the real `claude` and `codex`: it runs `claude auth status` and `codex app-server`, which make no model calls. They report "not signed in", because the run's `CLAUDE_CONFIG_DIR` and `CODEX_HOME` are empty. |
| `copy` | The setup check's Copy puts "Scholium <version> · Zotero <version> · <OS>" and the lines on the clipboard. That is the system's clipboard: the text that was on it is put back (a clipboard without text is emptied). |

## Safety

- **Port:** the port must not be 23119.
- **netstat:** the runner prints netstat for :23119 before and after each Zotero start.
- **Isolation:** the profile, data folder, APPDATA, TEMP and TMP are inside the run folder. A Zotero that quits empties `<TEMP>\Zotero`, which must not be the one a running Zotero uses.
- **Agent folders:** `CLAUDE_CONFIG_DIR` and `CODEX_HOME` point at empty folders of the run.
- **Environment:** variables starting with `CLAUDE` of the calling shell (a Claude Code session's) are not passed on.
- **Profile prefs:** `user.js` turns off the first-run start page (`extensions.zotero.firstRun2`), the Word and LibreOffice add-in installs, updates and sync.
- **Ending processes:** at the end, only processes whose command line names the run's profile are ended.
- **Screenshots:** they are drawn from Zotero's own windows, never from the screen.

## Other Zotero versions

You do not need to install another version to test it. Download the official installer from
`https://download.zotero.org/client/release/<version>/Zotero-<version>_x64_setup.exe` and check its signature
("Corporation for Digital Scholarship"). Then extract it with 7-Zip (`7z x -o<folder> <setup.exe>`) and pass
`<folder>\core\zotero.exe`. Give each version its own port if they run side by side.

## A run folder

```
<out>/fake/   <out>/setup/
  profile/  data/  appdata/  temp/  claude-config/  codex-home/  fake/   the throwaway's own folders
  shots/facts.json                                                     what the probe saw, step by step
  shots/*.png                                                          screenshots of each check
  zotero-debug.txt  zotero-debug-store.txt                             Zotero's debug output
  cli-run1/ cli-run2/ cli-list/                                        the apply check's configs and CLI output
<out>/summary.json                                                     every check's result and details
```

`tests/test_smoke_tools.py` tests the runner's pure parts without starting Zotero.

# Real runs: what a change costs and writes

`live.py` runs one real one-click Annotate, Claude Code through the plugin, in a throwaway Zotero, and `eval.py` scores
it. Use them to measure a skill or plugin change before and after, the same way each time. They are for Windows: the
watcher reads `netstat -ano` and the process table.

The plugin, the skill and `.claude-plugin` are exported from git at `--git` (default `HEAD`), byte for byte, so commit
the change first. Claude Code runs as the plugin starts it, with `--setting-sources project,local --plugin-dir <export>`
added: the exported skill and none of your settings. It uses your Claude Code login, so your own skill folder
(`~/.claude/skills/zotero-scholium`) is visible to the agent; that is why its script is checked (see below).

## One measurement

```
python scripts/smoke/live.py --zotero "C:\Program Files\Zotero\zotero.exe" --pdf D:\papers\2305.18290.pdf --meta dpo.json --tag dpo-head
python scripts/smoke/eval.py report %TEMP%\scholium-live\dpo-head
```

`--meta` is the item's JSON (`{"itemType": "preprint", "fields": {"title": ..., "archiveID": "arXiv:2305.18290", "DOI": ...},
"creators": [["First", "Last"]]}`); without it the item is a preprint titled after the file. The PDF is only read: Zotero
imports a copy into the throwaway's storage.

| Option | Default | Meaning |
|---|---|---|
| `--zotero` | (required) | the `zotero.exe` to start with a throwaway profile |
| `--pdf`, `--meta` | (required), none | the paper and its item |
| `--git` | `HEAD` | the commit to run |
| `--model`, `--effort`, `--locale` | `haiku`, `low`, `zh-CN` | the plugin's settings for the run |
| `--extra` | `""` | instructions typed above Annotate (none: the one-click run) |
| `--max-msgs` | 60 | the probe cancels the run after this many API messages (the agent never sees it) |
| `--max-usd` | 1.00 | the session ends once its result lines' `total_cost_usd` passes this |
| `--limit`, `--minutes` | 20, 30 | minutes for the agent run, and for the whole Zotero session |
| `--chat` | `""` | a question in the Chat tab after the run |
| `--open-reader` | off | a reader tab before and after the run, the eye button's preference never set |
| `--from-run` | none | start from a copy of a finished run's profile and data |
| `--claude` | npm's under APPDATA, else PATH | the real `claude` |
| `--fake` | none | a rehearsal with the fake Claude Code above: no model is called |
| `--port` | 23129 | the throwaway's port; 23119 is refused |
| `--tag`, `--out` | the time, `%TEMP%\scholium-live` | the run folder `<out>\<tag>` |
| `--config` | none | a JSON file of defaults for these options, e.g. `{"zotero": "...", "papers": "D:\\papers"}` |

`eval.py report RUN...` prints a row per run: cost, tokens by kind (input, cache read, cache write, output, thinking),
turns, wall and agent time, the reads of `sentences.txt` (offset+limit) and of the skill's other files, the reading
note's length, `<h1>` and headings, and the closing line. `--calls` adds each tool call with the tokens it added and how
many later messages re-read them, and the context of each API message. `--compare BASELINE.json` shows each measure
against the baseline's run of the same paper.

Exit code 0: a complete run; 1: safe but incomplete (a timeout, no result); 2: refused before Zotero started; 3: a
safety layer stopped it; 4: unverified (a closed connection with 23119 appeared that the watcher could not attribute;
`live.json` says which). `live.json`'s `verdict` is `safe`, `unverified` or `unsafe`.

## An evaluation

`evalset.json` names four arXiv papers (DPO, DDPM, ResNet, knowledge distillation) with their metadata, the PDF's URL
and its SHA-256, and the run's settings (Haiku, low effort, zh-CN, no extra instructions). The PDFs are not in the
repository: download each into a folder as `<arxiv id>.pdf` (or `<arxiv id>\paper.pdf`).

```
python scripts/smoke/eval.py run --zotero "C:\Program Files\Zotero\zotero.exe" --papers D:\papers --max-usd 0.50
python scripts/smoke/eval.py score %TEMP%\scholium-live\eval-<time>\eval-dpo ... --compare <earlier>\eval.json
```

`run` starts one throwaway Zotero per paper, in turn, and writes `<out>\eval.json` (a baseline) and `eval.md`. To compare
commits, give several: `--git v0.2.2,HEAD --repeat 2` runs them interleaved (v0.2.2, HEAD, v0.2.2, HEAD for each paper),
tagged `eval-<paper>-<rev>-<n>`. `--only dpo,ddpm` takes some papers. No run starts once the set's result lines add up to
`--max-usd`; each run is given what is left as its own `--max-usd`. The set stops when a run is refused or a safety
layer stopped one.

`score` prints the quality table: highlights and core, pages with highlights, highlights from the references on,
empty comments and comments that copy the English, comment length, translation warnings at the first dry run and at
apply, margin and sticky notes, layout warnings and overlaps, phrases not found, the reading note (length, paragraphs,
headings, `<h1>`, the citation), dry runs and their failures, `--apply` runs, tool errors and retries. `--out NAME`
writes NAME.json and NAME.md. A baseline names runs by their folder's name, not by a path.

Committed baselines are in `baselines/`, named `<commit>-<model>-<locale>` (`.json` and `.md`, with a line of notes on
how they were made). Compare a change with the latest: `--compare scripts/smoke/baselines/bac8a66-haiku-zh.json`.

## What it costs

A whole paper with Haiku at low effort costs about $0.02–0.03 (once $0.10, when its output ran long), the evaluation
set about $0.15–0.20. Opus on pages 1–6 costs about $0.60. Rehearse with `--fake` first: it costs nothing.

## Do not pass --max-budget-usd

Claude Code shows the agent its budget on every turn, and an agent that sees it economizes: it reads less and writes
less, so the run measures the budget, not the change. The plugin never passes it, and neither does `live.py`: the probe
refuses a run whose arguments have it. The caps are ones the agent cannot see: `--max-msgs` (the probe counts the API
messages in the run's log and cancels it) and `--max-usd`, from the result lines. A result line comes at the end of an
agent run, so `--max-usd` ends a session after the run that passed it, and in a set it stops the next run from
starting; a single run is bounded by `--max-msgs`.

## Safety of a real run

None of these can be turned off.

- **Port:** 23119 is refused as `--port`, in the profile's prefs and in the guard. The prefs are `smoke.py`'s:
  `extensions.zotero.firstRun2` false (no zotero.org/start in your browser), no Word or LibreOffice add-in installs, no
  updates, no sync.
- **Your skill script:** before a run, `~/.claude/skills/zotero-scholium/scripts/scholium.py`, if it is there, is read
  (only read). Unless it reads `SCHOLIUM_ZOTERO_PORT`, there is no run: the agent can see that folder, and an older script
  would write to your Zotero. The exported script is checked the same way.
- **The agent's environment:** the probe looks at the environment the plugin gives each agent process. Unless
  `SCHOLIUM_ZOTERO_PORT` is the throwaway's port, the run is cancelled; `live.json` records every process's value.
- **Guard:** every Python the agents start loads `guard/sitecustomize.py` (a copy in the run, through `PYTHONPATH`). A
  connection to 23119 goes to the throwaway's port instead and is noted in `guard\redirects.txt`. A redirect during the
  run is a safety stop: some script did not honour the port.
- **Chain test:** before the probe presses Annotate, the runner checks the guard (its own redirects), runs the exported
  script's `status` through the guard and again with `python -I` and only `SCHOLIUM_ZOTERO_PORT`, and an `--apply` on a
  chain-test item, and compares netstat :23119 before and after. If any of it fails, there is no run.
- **Watcher:** from before Zotero starts until after it ended, netstat is read every second. Every connection with 23119
  on either side is logged (`watch23119-all.txt`), the clients in `watch23119.txt`. A connection to 23119 from this run's
  process tree (the runner, its Zotero and their children) that a sample shows ends the run's Zotero: `TRIPPED`, exit
  code 3. Only the processes whose command line names the run's profile are ended, never the connecting process.
  Windows reuses process ids, so a parent created after its child does not count as its parent. A connection shorter
  than a second may be missed while it is open; it then shows only as a closed one (TIME_WAIT, no process), and one that
  appears during the session makes it unverified (exit code 4), since it could have been the run's.
- **netstat:** the LISTENING lines of :23119 (your Zotero) must be the same before and after the session; your own
  connections to it come and go and are only logged.
- **The session's Zotero:** the runner waits while the Zotero it started runs, also when the process list cannot be
  read, and at the end ends that process by the handle it holds if the list missed it.
- **The skill:** the probe gives the plugin the export's skill folder as Claude Code's, so `--add-dir` and the pre-run
  run the commit's skill, not one you installed; `facts.json` records each process the plugin starts.
- **Isolation:** as for the smoke checks: profile, data, APPDATA, TEMP and CODEX_HOME are the run's; the calling
  shell's `CLAUDE*` variables are not passed on. A rehearsal also gets an empty `CLAUDE_CONFIG_DIR`. Only processes
  whose command line names the run's profile are ended, and only a folder this runner made is emptied for a new run.

## Codex, with a fake app-server

`fakecodex/` is a stand-in for `codex app-server`, so that the plugin's Codex path (the pre-run, the prompt, the steps
of the live line, the card, the eye button, ■) can be checked in a throwaway Zotero without a model or an account. Build
its launcher once, as the fake Claude Code:

```
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /out:%TEMP%\scholium-fake\fakecodex.exe scripts\smoke\fakecodex\launcher.cs
python scripts/smoke/live.py --zotero "C:\Program Files\Zotero\zotero.exe" --pdf D:\papers\2305.18290.pdf --port 23149 ^
    --fake %TEMP%\scholium-fake\fakeclaude.exe --fake-codex %TEMP%\scholium-fake\fakecodex.exe --stop-prerun --open-reader --chat "这篇论文讲什么？"
```

`--fake-codex` sets the plugin to Codex with the fake on `codexPath` (copied into `<run>\fakecodex\` with
`fake_codex.py` and the Python that runs it, so its logs are the run's: `<run>\fakecodex\calls\`), and installs the
export's skill into the run's `CODEX_HOME`. It needs `--fake` too, so that no real agent is ever started. The fake
answers the plugin's JSON-RPC requests (initialize, account/read, model/list, skills/list, thread/start, turn/start,
turn/interrupt, …) and plays the one-click annotation: it reads `sentences.txt`, writes `config.json` and the note with
placeholder comments, and runs the skill's own `scholium.py --apply` against the throwaway's port (refused when the
port is missing or 23119); any other turn gets one sentence. `--stop-prerun` first presses ■ during an Annotate's
pre-run (the skill copy's `status` waits while `<run>\codex-home\SLOW_PRERUN` is there). `shots\facts.json` records each
process the plugin starts, with its port and `UV_CACHE_DIR`, and the live line's words and step.

## A live run folder

```
<out>/<tag>/
  live.json                                 the runner's summary: ended, cost, chain test, agent env, watcher, netstat
  export/                                   the commit's plugin, skill and .claude-plugin (Claude Code's --plugin-dir)
  guard/  chain/                            the guard (port.txt, redirects.txt), the chain test's files
  watch23119-all.txt  watch23119.txt        the watcher's logs
  probe-config.json  chain-request.json  chain-done.json
  shots/facts.json  shots/db.json           what the probe saw (with the click, and the live line's words and step each
                                            time they change); the annotations and notes in the database
  shots/prompt-1.txt  shots/conv-*.jsonl    the prompt and the conversation logs
  data/tmp/scholium/<key>/                  the run's own folder: config.json, sentences.txt, conversations/
  profile/  data/  appdata/  temp/  zotero-debug.txt
```

`tests/test_live_tools.py` tests the pure parts of `live.py`, `eval.py`, the guard and the live probe.
