# Changelog

## Unreleased

- A run that fails on the connection to Claude Code's or Codex's service before the agent used any
  tool is tried once more after 30 seconds; **Cancel** ends the wait.
- One-click runs leave out the user's MCP servers and hooks (Claude Code) and the user's MCP servers
  and installed plugins (Codex, for the run's thread only); the user's skills stay.
- `scholium status KEY` shows a paper's PDFs, the annotations on them and its notes before a
  configuration is written (`--query` finds the item); `scholium samples` shows a few highlights,
  margin texts and note openings of earlier runs as a style reference.
- A top band without room across the text column goes into the strip above the first line, beside a
  logo there; a band that still has no room reports how many characters fit and the font size at which
  all of it fits.
- The translation check no longer reports soft hyphens, Unicode hyphens or a hyphen between a number
  and its unit as added content, and comments lose soft hyphens before they are written.

## 0.1.5 (2026-10-04)

- The Scholium section also runs Codex: **Agent** chooses Claude Code or Codex, and the model list and
  effort levels follow the chosen agent (for Codex, the model of its `config.toml` unless another is
  chosen). Codex runs through `codex app-server`, the newest copy found on the machine, in its
  `workspace-write` sandbox with `<data dir>/tmp/scholium/` as working directory; commands may write
  only to the output folder, the profile folder and the folder of the tool's local API key, and may
  use the network. Requests beyond the sandbox go to Codex's automatic reviewer, and questions that
  reach the plugin are declined. The transcript, the state line, follow-ups, the usage-limit pause
  and cancelling work as for Claude Code; each run is logged to `codex-run.jsonl`, and a follow-up
  continues with the agent that held the conversation.
- The notice and the system notification at the end of a run show its last line a part per line,
  without the note's title.
- **Delete annotations** also moves the paper's reading notes tagged `zotero-scholium` to the trash;
  other notes are kept.

## 0.1.4 (2026-10-04)

- The bundled plugin annotates papers with one click: **Annotate** in a Scholium section of the item pane (library
  and reader side pane) starts the installed Claude Code in the background (`claude -p`, permission mode `auto`,
  file writes pre-approved only in `<data dir>/tmp/scholium/`), one paper at a time. The section chooses the model
  from the list Claude Code reports (the latest Opus unless another is chosen) and the effort (`medium` until
  another level is chosen, then the last choice); it cancels runs, shows the paper's state, and shows the process
  as Claude Code does (text, tool calls, results, and the error of a failed run), live or from the saved log, in a
  box resized at its lower edge. Notices at the start and the end close by themselves, and a system notification
  reports the end; neither appears while the section is on screen. A paper that already carries the tool's
  annotations is annotated again only after a confirmation, and every run is logged.
- The Scholium section also takes extra instructions for a run and continues a paper's conversation with follow-up
  requests (`claude -p --resume`). It shows each run's minutes, turns and tokens. When the usage limit is reached,
  the queue waits, and the interrupted paper continues its conversation by itself after the reset.
- **Personal profile ↗** in the Scholium section edits the annotation profile
  (`<data dir>/zotero-scholium/profile.md`) as Markdown in an editor over the Zotero window, beside a live preview.
  Unsaved changes and a file changed elsewhere are confirmed before they are lost or overwritten; a missing profile
  starts as the template.
- **Delete annotations** in the same section permanently deletes the annotations tagged `zotero-scholium` on the
  paper after a confirmation; other annotations and reading notes are kept, and a paper being annotated is left
  alone.

## 0.1.3 (2026-10-01)

- The reader toggle applies to every reader at once and is remembered across tabs and restarts
  (preference `extensions.scholium-bridge.showAnnotations`); the annotations are hidden until it is
  first switched on.
- `scripts/sync_local_skills.py` installs the latest release tag into local skill directories. Files edited there and a
  directory's own SKILL.md are kept; it exits 1 while the released SKILL.md has changed since the own one was aligned
  (`--ack` records the alignment).

## 0.1.2 (2026-10-01)

- The bundled plugin hides the tool's annotations in every reader view (tab, window, item-pane
  preview) until the eye button in the reader toolbar is pressed. Each reader starts hidden and is
  toggled separately; stored annotations are not changed. The plugin supports Zotero 7 and later;
  its endpoints remain needed only on Zotero 7 to 9.
- Sentence ids reject ambiguous substring matches and repeated ranges instead of silently selecting
  another passage. Sentence caches carry the source PDF's SHA-256; changed PDFs and legacy caches
  without a fingerprint require a fresh extraction. Extraction creates missing output directories.
- Translation checks compare numeric values without dropping decimal points, signs or percent
  markers, while accepting equivalent decimal, thousands and Chinese quantity-scale notation.
- Annotation cleanup uses only current and legacy tool tags across the API, bridge and generated
  JavaScript backends; matching text or empty comments no longer identify user annotations as owned.
- The API creates new notes and annotations before cleaning up old items, reports creation failures,
  and verifies newly created keys by reading them back. Failed or incomplete writes are not reported
  as successful, and the skill reconciles stored items before retrying.
- Read requests and safe writes retry transient failures. POST requests are not repeated after
  timeouts or HTTP 500/503 errors, avoiding duplicate creation when a response fails after a commit.
- The skill reviews the dry-run report before applying, preserves existing annotations for partial
  additions, and passes task scope, language and preferences to batch agents with separate output
  directories for each paper.
- Translation comments contain only translations; reader judgements belong in margin notes and
  reading notes. The skill entrypoint removes duplicated instructions and shortens its description.
- Add 24 regression cases covering annotation ownership, write results, read-back and HTTP retries.

## 0.1.1 (2026-09-03)

- The `author` configuration key is removed: no author name is written, and repeated runs identify
  earlier annotations by tag and identical content only.
- The skill annotates one paper per agent context (a batch spawns one sub-agent per paper after
  asking whether to run them in sequence or in parallel) and relies on the dry-run report instead
  of preview images; a preview is opened only for a layout warning the report cannot resolve, and
  `preview_pages` stays at its default `[1]`.
- `scholium extract` prints the paper's text with page markers, de-hyphenated, without running
  headers, footers, page numbers and the bibliography.
- A highlight may give just the start and the end of a long span separated by an ellipsis; an
  unmatched phrase is reported with the closest passage on the page, and `"snap": true` accepts
  matches at similarity 0.95 or higher. A phrase or anchor that occurs more than once on its page
  is annotated at the first occurrence and reported under `ambiguous_matches`; `occurrence: N` on
  the item selects the N-th appearance directly.
- The translation check ignores mathematics and rich-text tags and accepts rejoined hyphenations;
  comments may carry `<sub>`/`<sup>`, and reading notes may carry KaTeX math nodes.
- The dry-run report gains `style_warnings` (raw LaTeX and `^`/`_{` in comments, tags the reader
  does not render, label-colon margin notes and arrows or circled numbers in them, hard line
  breaks, phrases from `banned_phrases`, duplicate or intersecting highlights, highlights over
  annotations already in Zotero, a core-colour count outside `core_range`, note math nodes with a
  double backslash or LaTeX outside a node) and `colors`, the number of highlights per colour.
- `--list` prints the counts by type and colour, the annotations that are not the tool's own, and
  the note titles; `--list --full` prints every annotation.
- Batch procedure of the skill: the coordinating context only dispatches one sub-agent per paper
  and collects one line from each; the sub-agent performs the whole procedure including `--apply`;
  reviews and corrections run in fresh sub-agents.
- `scholium extract --sentences` numbers the paper's sentences; `highlights[]` and `summaries[]` name
  sentences by `id` (or `ids` for a consecutive span) and the tool supplies the text and the
  coordinates. `--apply` refuses to write while `missed` or `style_warnings` is non-empty
  (`--allow-warnings`), and the report carries the PDF's SHA-256 before and after the run.
- SKILL.md is reduced to the workflow; configuration keys, commands and report fields, write channels
  and pitfalls, and the profile procedure move to `references/configuration.md`,
  `references/backends.md` and `references/profile.md`.
- `scripts/measure_context.py` reports the token size of the skill files (CI limits the SKILL.md
  body) and `scripts/session_usage.py` the model calls and tokens of Codex rollouts and Claude Code
  transcripts.
- The release workflow publishes the version's CHANGELOG section as the GitHub release notes.

## 0.1.0 (2026-08-28)

Initial public version.

- `scholium` command-line interface: highlights and underlines with comments and named colour
  levels, margin text annotations with automatic layout, and an optional child note. The PDF file is
  only read.
- `scholium profile --from-library`: derives the user's annotation habits (colours, annotation types,
  comment length and style, density, notes) from the annotations in their own library and writes a
  profile draft to be completed by the agent together with the user.
- Backends: the official local API of Zotero 10 and later (no plugin required), the
  `scholium-bridge` plugin for Zotero 7 to 9, and a Run-JavaScript file as a last resort.
- The `scholium-bridge` plugin carries the project's version number.
- Repeated runs replace only annotations tagged `zotero-scholium` (or with identical content).
  Existing notes are never deleted; a new version receives a versioned title.
- Claude Code skill `skills/zotero-scholium`, including a Chinese writing-style guide.
- Margin layout reads the attachment's existing annotations first and never covers them; a
  translation-fidelity check reports comments that go beyond the highlighted span.
- Margin layout also keeps clear of the page's figures (images and vector drawings), and the text
  column edges are estimated over the whole document, so a page with few full-width lines (an
  indented abstract, a figure beside the text) no longer pushes margin notes into the text column;
  a paragraph at the very bottom or top of a page no longer pushes its note into the footer or header.
- `cleanup: false` keeps every existing annotation on the attachment, the tool's own included, and
  only adds new ones (all three backends); the tool's earlier margin notes then count as obstacles
  for the layout.
- The translation-fidelity check expands ligatures (ﬁ, ﬂ, ...) before comparing terms.
- The annotation profile is stored in the Zotero data directory (`<data dir>/zotero-scholium/`)
  rather than the user configuration directory; `profile --path` prints the location, and a
  profile at the old location is migrated on the next `profile --from-library`. The data
  directory is resolved from the configuration, `ZOTERO_DATA_DIR`, the PDF path, or Zotero's
  prefs.js.
- `scholium-bridge` plugin 0.3.1: data-only local endpoints protected by a token, tag support,
  opt-in cleanup of external annotations; `list` returns positions and tags.
- The skill lives in `skills/zotero-scholium/` and is installable with `npx skills add
  weilr/zotero-scholium` (Claude Code, Codex, and other agents) or as a Claude Code plugin through the
  `.claude-plugin` manifests; the `SKILL.md` front matter is quoted so that strict YAML parsers accept it,
  and CI checks it.
- Placement and style of margin notes can be customised: `place: "top"` or `"bottom"` lays a note across
  the text column at that end of a page without an anchor (a summary at the top of page 1 is the main
  use), `side` or `margin_side` chooses the margin, `kind` or `summary_kind` switches to sticky notes,
  and `color` and `font_size` can be set per note. `profile --from-library` reports page-top notes, the
  preferred side and the font size, and the skill maps such requests to configuration fields.
