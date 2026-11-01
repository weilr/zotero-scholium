# Changelog

## Unreleased

### Added

- Saved prompts above the Chat tab's box (preference `savedPrompts`), sent with a click and edited,
  deleted (with **Undo**) and reordered in the row.
- Editing an earlier question of the Chat tab (✎ on hover) asks it again from the conversation before it,
  replacing what followed, with **Undo** for six seconds (Claude Code `--resume-session-at` with `--fork-session`;
  Codex `thread/fork`; a new session given the conversation where that is refused or there is no point to go back
  to).
- Scholium section: two tabs, **Chat** and **Annotations**. A settings chip (model and effort) opens a
  layer with the three choices; ⋯ holds **Show log**, **Personal profile ↗**, **Settings…** and, on the
  Annotations tab, **Delete annotations**.
- A Scholium page in Zotero's settings: the send shortcut (Enter, Ctrl + Enter for multiline prompts, or always
  Ctrl + Enter), the follow-up behavior (Queue or Steer), whether the context window usage shows, and the Claude
  Code and Codex programs (preferences `sendShortcut`, `followUpMode`, `contextRing`, `claudePath`, `codexPath`).
- Messages sent while the agent answers are queued in the box, where they can be reordered by dragging, opened,
  steered, deleted (with **Undo**) and edited, or with Codex steer the answer under way (`turn/steer`);
  Ctrl+Enter, or Ctrl+Shift+Enter when Ctrl+Enter sends, does the opposite for one message. A stop holds the queue
  until **Resume**; a queued message that could not be sent is marked and offers **Retry**. A stop also ends a run
  that is still starting; words its conversation does not have yet go back to the box, a queued message to its
  queue.
- A context ring beside the send button: the share of the context window the conversation's session took up in
  its latest request, with a layer of input, cache and output and **Compact this conversation's context**;
  `/compact` in the box does the same, and stays in the box while the paper cannot compact. Compactions, also the
  agents' own, show in the transcript with the sizes before and after. A compaction under way when the plugin is
  updated is handed over and runs again.
- Annotation sessions: each **Annotate** starts a session of its own (`annotate-<agent>-<time>.jsonl`, the
  index's `annotation`), shown on the Annotations tab with the six steps and their times, then a card with the
  highlights (core), margin notes, sticky notes and reading notes counted in Zotero, the warnings left, the turns
  and the tokens. Words typed there continue the session; **Annotate again** asks in place; a failed annotation
  offers **Retry**.
- **Ask Scholium** in the reader's selection popup puts the passage and its page label above the box of the Chat
  tab, and the next message quotes it to the agent with its page in the PDF and, where it differs, the label.
- Sentence citations: answers cite the paper's sentences as `[#n]`, shown as chips with the page and, on hover,
  the sentence; **Locate ↗** opens the PDF at the page and finds the sentence.
- A failed question offers **Retry**; Esc twice on the same run stops it.
- Scholium section: as in llm-for-zotero, each agent has its own conversations of a paper. **New chat** starts
  one, **History** lists them by day to open, rename or delete (with **Undo**; a deleted Codex conversation's thread
  is archived), and switching the agent starts a new one. Messages go on in the conversation shown. Each
  conversation has its log in `<out dir>/conversations/`; `claude-run.jsonl` and `codex-run.jsonl` of earlier
  versions are each agent's first conversation.
- Scholium section: a new session is told which configuration, agent and time wrote the paper's annotations, and a
  session that goes on is told when another conversation rewrote them since, or that they are gone. The section
  shows when each run ended.
- The plugin's apply returns `removeError` when the earlier notes cannot be moved to the trash after the new items
  are written.

### Changed

- Scholium section: the section fills the side pane's height. The state is one line beside the settings chip.
  While a run goes on, one line names what the agent does; once the answer is there, the steps fold into "Worked
  for 24s ›". The history is a layer of the PDF's conversations by day. ■ stops a run.
- Scholium section: annotating no longer continues the chat; the Chat tab is for questions.
- Scholium section: the conversations and the history are those of one PDF, the item's best PDF in the library
  and the open PDF in the reader.
- Token counts are written in k with thousands separators (`2,568k tokens`), in Chinese too.
- When an agent's program is not found, the message points to Zotero Settings → Scholium.
- Scholium section: when the agent no longer has a conversation's session (deleted in the Codex app, or cleaned up
  by Claude Code), a new session is given the conversation, Codex as items of its new thread and Claude Code as text,
  beyond ten exchanges the earlier ones as excerpts; a continuation after a limit or an update ends with that
  reason. A failed Claude Code run without text shows its errors.
- Scholium section: a conversation's log leaves out the image data in a Claude Code tool's result, Claude Code's own
  copy of the result and Codex's turn diff. A line the log file does not take at once is written with the next ones,
  and the run goes on.
- Scholium section: the state line gives the outcome of the conversation shown, on the Annotations tab that of
  **Delete annotations**. ■ on a paper that waits for its second try or for a limit to reset ends it as cancelled in
  its log. A paper moved to the trash while it waits is left out. The words of a message whose agent is not found go
  back to the box. A title being typed in **History** stays when the list is drawn again. For a paper in a group
  library the message box is hidden and **Agent**, **New chat** and **History** are off.
- Scholium section: a Codex thread counts as gone only when Codex refuses to resume it. A relative configuration path
  of a command run in a Windows folder is kept as a Windows path. The model list is asked for without the user's MCP
  servers and hooks. `mailto:` links are not followed. A conversation index that cannot be read is not written over,
  and the index is written through a temporary file. English texts say "1 turn" and "1 sticky note"; Codex's end
  and Claude Code's failure kinds are named in the user's language.
- A margin note without room (no gap tall enough, taller than the page allows, or a margin narrower than a box)
  takes the other margin of a one-column page when its `side` is `auto`, and without room there either is written as
  a sticky note with its whole text beside the first line of its paragraph, listed under `as_notes`; a two-column
  page keeps the note on its column's side. Only a sticky note without room still gets a layout warning.
- A top or bottom band that has no room even at `band_min_font_size` is written as a sticky note with its whole
  text, beside the column's first line of text (top) or its last above the footer (bottom), and listed under
  `as_notes`; it no longer gets a layout warning.
- `--apply` refuses `--ignore-existing` when the configuration has `cleanup: true`; when the annotations already on
  the attachment cannot be read, the message offers `--ignore-existing` only without cleanup.
- No preview image is rendered by default (`preview_pages` is `[]`); the report lists `previews` only when pages
  were rendered.
- `extract` also removes the bibliography under numbered and other reference headings ("7 References",
  "VII. REFERENCES", "Literature Cited", "参考文献") and, after it, a paper checklist ("NeurIPS Paper Checklist",
  "Reproducibility Checklist", "Checklist") up to the next appendix heading or the end. The marker of a rotated page
  reads `--- p.N (rotated: not annotatable) ---`.
- When removing the earlier annotations or notes fails after the new ones are written, the report gives
  `applied: "partial"` with `result.removeError`.
- An item that is not in My Library is reported as not found there; group libraries are not supported.
- Retry, Steer, Delete, Send and Resume, and a stopped run's mark, are icons with their words as tooltips; the send
  and stop button is larger.
- The Annotations tab's introduction is one line.

### Fixed

- The Claude Code and Codex boxes of the settings page showed `undefined`; they show the program found.

### Removed

- Scholium section: the **Agent**, **Model** and **Effort** rows, the row of **Annotate**, **Cancel**,
  **Personal profile** and **Delete annotations**, the status box, the "Transcript" caption, and resizing the
  transcript box (the `logHeight` preference).
- The history of all PDFs of an item.

## 0.1.9 (2026-10-20)

- `cleanup` is off by default: a run only adds unless the configuration sets `cleanup: true` for a
  complete redo, and the dry-run report counts what that would delete (`cleanup_removes`). Without
  cleanup, text the tool already wrote on the same page is a blocking `duplicate_existing` warning, and
  `--apply` does not write when the annotations already on the attachment could not be read. A redo
  started from the Scholium section names `cleanup: true` in its prompt.
- `note_replace: true` moves the tool's earlier notes under the item to Zotero's trash once the new note
  is written (only those whose title starts with `note_title_prefix`, when it is set); notes without the
  tool's tags are never touched. A note of the tool with the same text is not written again. The local
  API, the JavaScript file and the plugin do this; the plugin's request takes `trashOwn` and
  `trashTitlePrefix`.
- `core_count` informs without blocking `--apply`; `--accept KIND[,KIND]` lets chosen style warning
  kinds (and `layout`) through.
- Unknown configuration keys, unknown levels and highlight types other than highlight and underline
  end the run with the nearest valid key. A configuration or note written with a byte-order mark is
  read.
- The report ends with `applied`, `apply_error` and `fallback`; the created keys go to
  `<out_dir>/applied_keys.json` (`result.keys`). `--list` and the dry run report a failed read of the
  attachment instead of a traceback, and `profile --from-library` one of the library.
- `profile --path` prints the path of `profile.md` (`--json` for the earlier details). `status` gives
  the authors, date, venue, DOI and URL. `extract` prints the length of its listing in lines.
- The JavaScript fallback says why each write channel was unavailable. Without PyMuPDF, the commands
  that need it say how to install it; PyMuPDF before 1.24 (`fitz`) is used too.
- SKILL.md: the new defaults and options; files are written with the file tool into `out_dir`; the
  description covers redoing, extending and correcting annotations.
- A top or bottom band without room at its font size is set smaller in steps of 0.5 pt down to
  `band_min_font_size` (default 8, between 4 and 36) and listed under `fitted`. When even that is too
  small, the warning gives how many characters fit, the words they end with, and how many to cut.
- Translation warnings read extracted text as it lost its scripts (10−3 for 10⁻³, L2 for L², "CM 2"),
  mathematical italic letters, a space after a thousands separator, "R-squared", ordinals, factors
  ("2-3x" for 2–3 倍), English and Chinese number words (million, 百万, 亿), plurals and abbreviations of
  words in the sentence. Words a comment keeps in English do not count towards the length a translation
  should have. Numbers written as words ("eight", "below one", "unit variance"), "11.60 thousand" given as
  11.60 with 千 elsewhere, "Figure.2", and "1/8" for "8x fewer" are read too. SKILL.md: a faithful
  translation is not changed to silence a warning.
- `extract` and the dry run read a page's text without decoding its images: a paper of many figures that
  took 15 seconds per pass takes under one. Text inside figures may be grouped into fewer lines; the
  sentences and headings of the paper are unchanged.
- A sentence range that crosses a heading names the heading and the sentence after which to split it.
  A sentence whose text is not found on its page no longer suggests running `extract` again.
- `--apply` writes through the scholium-bridge plugin when it is 0.1.9 or later, without an authorisation
  dialog, the annotations in one transaction (the local API saves each item on its own); otherwise
  through the local API as before. The plugin returns the keys it wrote, which go to `applied_keys.json`
  and are checked on read-back, and names its version in `list`. Through a plugin before 0.1.9,
  `note_replace` is not done and `result.noteReplace` says so.
- Scholium section: web addresses and `zotero://` links in a message and in the profile preview open
  on a click or with Enter.
- Scholium section: a paper's state line shows only that paper's run, place in the queue and outcome,
  and its notices are left out only while that paper's section is on screen. While the agent has lost
  its connection and tries again (Claude Code's `api_retry`, Codex's "Reconnecting… 2/5"), the state
  line says so until the agent answers again.
- Positions are written in PDF user space also on pages whose crop box or media box does not start at
  (0, 0); on such pages every annotation used to be shifted by the box's offset. Annotations written there
  before stay shifted until the paper is annotated again.
- `extract` drops a lone number or roman numeral only among a page's first and last three rows or in a
  block made only of such rows; inside a block of text it stays (a formula's variable set on its own line).
  A PDF without a text layer ends `extract` with a message. Highlight entries are checked before the run (an id, ids in order, or a page from 1 with
  text; `occurrence`, `comment`, and `#rrggbb` colours in `color`, `levels`, `core_color`, `other_color`
  and `text_color`), and a page beyond the document is a `missed` entry. The `tag` warning passes
  comparisons such as "x<y，则 f(x)>f(y)", the `label` warning ratios such as "3:1"; translation warnings
  read "15 percent" as 15% and quote a number as the comment writes it. A margin box without room says
  what to change. With `cleanup`, a tool's annotation that the user changed in Zotero after it was written
  blocks `--apply` (`user_edit`) unless the configuration keeps the change; listings give the tool's own
  annotations whole, with their dates.
- Requests to Zotero's local server do not go through a proxy named in the environment.
- SKILL.md: the profile's path comes from `status`; a run with no user to ask uses the defaults when there
  is no profile; to change or add to annotations already written, the configuration they came from (the
  paper's whole set) is edited and applied whole with `cleanup: true`; after corrections `--apply` follows directly, and no `status` follows a successful
  write; the citation comes from `status`, a code link only from the paper. The references are pointed to
  only for what SKILL.md leaves out, and several papers and reviews moved to `references/batch.md`.
  `--help` names the write channels in the order they are chosen.
- Plugin: the bridge removes and trashes only items with the tool's own tags, which are fixed in the
  plugin; it refuses a request that names another tag, or an item other than the attachment's parent for
  the note. It reports the version of its manifest, lists the tool's own annotations whole with their dates,
  and a copy that stops removes only its own endpoints; after an update the new copy puts back endpoints an
  older copy removed.
- Scholium section: when the plugin is updated while a paper runs, the new version continues that paper's
  conversation and then runs the papers still waiting; a pause for a limit and a wait for a second try go
  on, and words the agent had not received yet are handed over with their paper. A run that has started and ends without a result of its own (cancelled, failed, interrupted by an
  update, by disabling the plugin or by quitting Zotero) leaves its end in the log, and the paper's history
  shows it.
- Scholium section: the prompt names the profile, or says there is none and the defaults apply; a
  follow-up that changes or adds annotations is told to edit the paper's one configuration and apply it
  whole with `cleanup: true`. A run whose agent does not find the skill ends at its start and says where
  to put it; when Codex cannot list its skills, lists them with errors or has the skill switched off, the
  run ends with what Codex said. A limit of the service
  rather than of the account ("not your usage limit") is named as such, and the queue waits as long as its
  message says.
- Scholium section: while Zotero is in front a corner notice tells how a paper ended, while it is in the
  background a system notification; the agent's words in a notice are shown as text. A failed deletion is
  shown in the paper's state line only. Only papers in My Library are annotated; a PDF file that is not on
  the computer is named as such; **Annotate** leaves a follow-up in the box for **Send**. Texts for one
  paper, “个人配置” throughout, the Config Editor in place of about:config, the transcript's remaining
  English words in Chinese, solid focus outlines, and each second only the state line set again.
- Scholium section: **Send** asks about a paper that has no conversation yet, in a new conversation that
  answers without annotating. Until the conversation has an annotation, the box's words go with
  **Annotate** as extra instructions, and an annotation by the same agent continues the question's
  conversation and keeps its transcript.

## 0.1.8 (2026-10-16)

- The Scholium section shows the agent's messages as they are written (Claude Code's partial
  messages, Codex's message deltas); the log keeps only the whole messages. Text selected in a
  message being written stays selected.
- Formulas in the agent's messages (`\( \)`, `$ $`, and set apart `\[ \]`, `$$ $$`) are typeset:
  KaTeX 0.18.11, bundled with the plugin (MIT, `content/katex`), turns their TeX into MathML, which
  Zotero sets. A formula KaTeX cannot read stays as written, and a price such as $5 stays text.
  Backslash escapes (`\*`, `\$`) are read as Markdown has them.
- A message sent in a conversation runs before the papers waiting for their first run, after a paper
  that the usage limit or a failed connection interrupted.
- A question in a conversation is answered without the closing line that a change of annotations
  ends with; its notices say "Answered" and give the answer's first line.
- A message with a code block or a wide table no longer widens Zotero's item pane, which pushed the
  right edge of the Scholium section, the copy buttons included, under the side navigation (0.1.7);
  such blocks scroll inside the transcript. Words in table cells are no longer split.
- A paper selected again during its run shows its transcript at the latest entry and follows it; the
  transcript opened at the top and stayed there.
- A message containing a line or paragraph separator (U+2028, U+2029), which text quoted from a PDF
  can hold, hung Zotero or left the Scholium section empty (0.1.7), each time the paper was shown
  while its log held the message. A message that still cannot be set as Markdown shows its source.
- The progress line counts a command that extracts sentences and then writes to Zotero as a write,
  and recognises the `scholium` command as well as `scholium.py`.
- After a plugin update that left the old copy running, the section keeps the new version's
  stylesheet and labels; it kept the old version's, and lost both when the old copy stopped.
- Times read as Claude Code and Codex give them (45s, 6m 05s, 1h 02m 05s), and a running paper's
  time so far counts up each second; it was given in whole minutes, a run under one as one minute.
- While a paper runs, its delete button is out of the way, so that the section's buttons keep to one
  row.
- What a cancelled or failed run showed of a message it did not finish stays in the transcript and
  the log, marked as unfinished and before the failure.
- Words typed in a section's message box and not sent stay with their item while another is shown.
- `scholium.py` reports a refused connection to Zotero (Zotero closed, or its server off) at once;
  it tried three times over 20 seconds. A request that times out is still tried again.
- `--backend js` no longer asks Zotero for its version first; with Zotero's local server not
  answering, it waited about 20 seconds before writing the Run-JavaScript file.
- The message box no longer takes Zotero's look for text boxes: no line under the text while it has
  the focus, no grey ground under the pointer. The box around it shows the focus.

## 0.1.7 (2026-10-15)

- The Scholium section sets the agent's messages as Markdown (headings, lists, tables, code, quotes)
  instead of showing the source. The transcript can be selected and copied, without its bullets, and
  each message has a button that copies its Markdown source. The profile preview reads tables too.
- After a plugin update the reader toolbar could show two eye buttons until Zotero restarted:
  Zotero's update handlers do not wait for each other, so the running copy could be started again
  or left running beside the new one. The copy that starts last now stops the one before it, and a
  toolbar gets one button even beside a copy of 0.1.6 or earlier.
- A configuration without margin notes reads only the pages it highlights; the column extents of the
  whole document were read for every run.
- A write through the bridge plugin lists the attachment 5 times instead of 7 (9 with a reading
  note): the listing that answers the connection check is used.
- The Scholium section parses a paper's log again only when the file has changed (time or size);
  every selection of the paper read the whole log, which a continued conversation keeps extending.
- When a later batch of a local API write fails (an HTTP error, or a new authorisation that is
  refused), the report keeps the keys created by the batches before it (`result.createdKeys`),
  and `result.failed` names the items from the failed batch on.
- The release workflow runs the CI checks first and stops when the tag differs from the version in
  the package, the tool or the plugins (`scripts/check_versions.py`); CI tests Python 3.9 and 3.12.

## 0.1.6 (2026-10-05)

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
- An empty message box in the Scholium section is as tall as its placeholder, which no longer runs
  into the line below it.
- The bridge plugin (Zotero 7–9) and the generated Run-JavaScript file remove the tool's earlier
  annotations in the same transaction as, and after, the new ones: a failed write leaves them in
  place. The Run-JavaScript file writes the text of underlines.
- A run whose prompt or log cannot be written stops Claude Code; a failure while reading Codex's
  messages ends its server and fails the run instead of leaving it waiting. When the plugin stops
  before a run's process is running, the run does not start, and a process being created at that
  moment is stopped at once.
- The transcript box keeps no more entries than the transcript (3000).
- A margin box taller than the page allows, or in a margin narrower than a box (30 pt), gets a
  `layout_warning`, and `--apply` refuses to write while `layout_warnings` is non-empty, as for
  `style_warnings` (`--allow-warnings`). Highlights and margin notes on rotated pages are reported under
  `missed` and not written.
- A sentence range (`ids`) must start and end where its first and last sentences stand on the page;
  otherwise it is reported under `missed` instead of highlighting the same text elsewhere.
- Margin text on the page carries no tags: `<sub>` and `<sup>` (in any case, with or without attributes)
  become Unicode sub- and superscripts (dₖ, x²), or `_` and `^` where a character has none (π_ref); other
  formatting tags are dropped, and a `<sub>` or `<sup>` without its closing tag is reported under
  `style_warnings`.
- Margin notes keep clear of text in the margins, such as the vertical arXiv stamp; in a one-column
  paper a note takes the other margin when its own has text beside the paragraph.
- The READMEs open with an animation of a one-click run and list the features in a table with an
  example from that run for each, some of them animated. The command-line steps move to
  `docs/cli.md`, which refers to the skill's reference files for configuration keys, write channels
  and the profile; the development notes move to `CONTRIBUTING.md`; the safety and troubleshooting
  sections are left to `docs/design.md` and the skill's references.
  The requirements, the skill and the plugin's installation notes name the Zotero setting that turns
  on the local API.

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
