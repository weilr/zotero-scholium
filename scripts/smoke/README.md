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
