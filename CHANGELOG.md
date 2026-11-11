# Changelog

## Unreleased

### Changed

- The annotation's and a question's prompts say how the skill's script runs on this computer: with `uv run` when uv
  is found, else with the Python found.
- An annotation ends with one short line in the user's language; its card shows the warnings that line names in every
  language of the plugin, also when it gives them as a count (剩余警告 1 条（…）, 1 remaining warning (…)) and with words after
  the count (剩余警告：2 条译文提示（…）, which the card keeps whole).
- Nothing asks to close and reopen the PDF after writing (the skill, its JavaScript file, the READMEs): open readers
  show the new annotations by themselves.
- The skill runs `--apply` without a separate dry run: what it holds back is corrected in one edit of the configuration
  before it runs again.
- A one-click annotation is told not to pass `--accept`, `--allow-warnings` or `--allow-missed` but to correct what
  `--apply` holds back; words to its session may let a finding through only when they ask for that exception.
- A new annotation's `status` and `extract` are run by the plugin before the agent starts, and given to it in the
  prompt; a scanned PDF ends the run there, without an agent.
- A conversation's first question starts with its papers' sentences extracted: the plugin runs `extract` before the
  agent for each paper without `sentences.txt`, and the prompt says so, or that the paper is a scan without a text
  layer.
- The skill reads the reading note's template before it writes the note, and the dry run and `--apply` hold back a
  note without its `<h1>` title (`note_title`; `--accept note_title` lets it through).
- The reader's eye button turns on by itself with the first annotation written, for a user who has never used it;
  from then on only the button changes it.
- In an annotation's Claude Code runs, one turn writes at most 32,000 tokens, thinking included
  (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`), unless the user's environment sets that variable.
- A cleanup re-apply changes in place what it holds again: an annotation of the tool at the same place keeps its key
  and only its changed fields are written, unchanged ones are left alone, only the new ones are created and only those
  left out are deleted, through the plugin, the local API and the JavaScript file; the report's `rewrite` counts them.
  With `note_replace`, the reading note the output folder wrote is rewritten in place while it is as the tool stored it;
  one whose text the user changed is held back as `user_edit`, one with the user's markup, images or title goes to the
  trash as before. A plugin before this one deletes and creates as before. A write whose annotations changed in Zotero
  since the run read them writes nothing and asks to run again.

### Fixed

- The model list gives up after 60 s when Claude Code's output does not end, and is asked for again later.
- The translation check takes a number with a capital magnitude suffix and the same value with 万 or 亿 as one:
  6B and 60 亿, 1.5M and 150 万, 175B and 1750 亿 are no longer reported.
- The state line's step: a `status`, `samples` or `profile` command with `--config` is no longer taken for the dry
  run, the steps are extract, reading, writing and applying (four; loading the skill shows the starting words), and
  the plugin's own `status` and `extract` show as theirs.
- Disabling, updating or removing the plugin also takes its button out of the reader's sidenav, where it stayed hidden
  after the reader tabs were closed.
- The card's remaining warnings: a period inside a warning (Fig. 3, p. 9) no longer cuts it short, a warning that
  starts with the language's word for none (keine Übersetzung für S. 3) is kept, 0 and 无（…） are none, and Traditional
  Chinese counts (剩餘警告 2 條（…）) are read.
- ■ while the pre-run's `status` or `extract` is starting stops it at once; it went on until its time was up.
- The pre-run's results go into a Codex prompt only when Codex uses the skill copy that ran them, and of Claude Code's
  plugin cache the highest version of the skill is taken, not an orphaned one.
- A PDF without a parent item gets the pre-run too (`status` is given the attachment's key).
- A scanned PDF's notice gives the whole message, as an error; it said "Done".
- `--apply` with `cleanup: true` no longer deletes annotations of the tool that its configuration did not write (another
  configuration's, or those an add-only write was added to): it holds them back as `cleanup_other`, and
  `--accept cleanup_other` lets a complete redo through. The skill applies again after correcting a translation only
  when its configuration holds the paper's whole set. `applied_keys.json` names the configuration.
- The translation check quotes a number with a K, M or B suffix as the comment writes it (13B, not 13 billion), and
  takes a model's name and its size with a hyphen or a space as one name (Llama-7B, Llama 7B).
- `user_edit` also holds back a rewrite that would put back an annotation the user moved or relabelled in Zotero, or
  delete one they tagged.
- A question about several papers is told to quote the first paper's sentences as [#123] every time, never as
  "sentence 29", so that they show as citations; the other papers by title and page.
- The translation check of a comment in German, French, Spanish, Portuguese or English no longer lists its ordinary words:
  it checks its numbers, also written with the language's words and comma or period (6 Mrd., 1,5 Mio., 6 milliards,
  6 mil millones, 6 bilhões), and its terms (acronyms, CamelCase names, words with digits or Greek letters); words with
  umlauts or accents are no longer split. A Russian comment's numbers are read the same way.
- `note_title` holds back a reading note that does not start with its `<h1>` (one after an introduction or inside a
  comment no longer counts) and an empty one.

## 0.2.2 (2026-11-10)

### Added

- When Zotero's local API is turned off, Annotate, a question or an edited question asks once whether to turn it on.
- When the agent does not find the zotero-scholium skill, the failure offers **Install the skill and retry**: the plugin
  copies the skill it carries into Claude Code's or Codex's skills folder and runs again. A skill already there is left
  as it is.
- A **Setup check** on the settings page: Zotero's local API, Claude Code and Codex (found, signed in, the skill), Python
  and PyMuPDF, with a button where the plugin can fix it.
- The skill's script carries inline metadata (PEP 723): with uv, `uv run scholium.py …` brings Python and PyMuPDF on
  first use. The skill runs the script that way when uv is on PATH, else with `python` as before.
- The setup check has a uv line with the install command for the system. With uv, a missing Python or PyMuPDF is no
  fault.
- The skill's script reaches Zotero at the port `SCHOLIUM_ZOTERO_PORT` names, when it is set (a value that is not a
  port number stops it with an error); the plugin sets it to its Zotero's port (`httpServer.port`) for every process it
  starts, so a changed port works.
- **Copy** in the setup check puts its lines on the clipboard as plain text, with the versions of Scholium and Zotero
  and the operating system, for a bug report.
- Papers in group libraries: Annotate, questions and Ask Scholium work as in My Library, and the annotations go into
  the group's library, where every member sees them. The first annotation in each group asks once; Annotate again and
  Delete annotations say that the change is the group's. A group the user cannot edit gets no annotations and says so;
  its papers' questions are answered. The skill's script reads and writes the library `group_id` names (the plugin's
  `paper.json` carries it; `status` and `samples` take `--group`).
- `extract` stops on a scanned PDF without a text layer (most pages an image with almost no text) with exit code 3 and
  a JSON `error` that says to run OCR first; the skill stops there and passes the message on, and an annotation that
  wrote nothing says so on its card.
- **Save as note** in the ⋯ menu of the Chat tab (and of the Annotations tab while it shows a session) makes the
  conversation a child note of the paper: "Scholium conversation: <the paper's title>" and the date, each question with
  its quoted passage, each answer with the agent that gave it, formulas as Zotero's note editor sets them. It is tagged
  `scholium-chat`, so Annotate again and Delete annotations leave it.
- **Ask Scholium (N papers)** in the items list's context menu, for 2 to 8 papers or PDFs: the first paper's Chat tab
  opens on a new conversation with the others as removable chips above the box, and each message goes with every
  paper's `paper.json`. The conversation is kept with the first paper; its log names the others, so later messages keep
  them.
- With Zotero in Japanese, Korean, German, French, Spanish, Russian, Portuguese or Traditional Chinese, the plugin's
  prompts give the agent that language, so the translations, margin notes, reading note and answers are written in it.
- The Scholium section, the reader's eye button and the settings page in Traditional Chinese, Japanese, Korean,
  German, French, Spanish, Russian and Portuguese (Brazilian, and European for Portugal), following Zotero's language.

### Changed

- A paper already in the user's language gets highlights without comments.
- When Claude Code or Codex is not signed in, or PyMuPDF or Python is missing, the section says what to run. Codex
  without an account stops at once instead of retrying for a minute.
- A missing PyMuPDF or Python is answered with installing uv, or `pip install -U pymupdf`; a run that found no uv says
  how to install it.
- On macOS and Linux, Claude Code and Codex get the PATH of the user's login shell before Zotero's, read once a session,
  so that programs installed with Homebrew, nvm, conda or uv are found when Zotero was started from the Dock or a
  desktop menu. The plugin looks for Claude Code, Codex, Python and uv on that PATH. uv's install folders
  (`~/.local/bin`, and `~/.cargo/bin` outside Windows) are added when they exist and are missing.
- The quick start recommends uv in place of installing Python and PyMuPDF.
- Codex is not offered the effort level max.
- Claude Code runs get only the tools they use (`--tools`): the skill's for an annotation and its session, and WebSearch
  and WebFetch too for a chat, which makes each message's starting context smaller. PowerShell is among them on Windows
  only.
- The file `extract --sentences --out` writes starts with an index of its line numbers: each page, the main text, the
  references, and after them an appendix heading or, when the text there starts without one, that text. The skill
  reads the main text by it and of the appendix only what the main text points to as essential, and finds the pages of
  a page limit there.
- The report of a dry run and of `--apply` leaves out empty fields, the generated file's path, an unchanged PDF's
  hashes and the details of a write that succeeded; `--verbose` prints them all.
- Ask Scholium is offered only in reader tabs. A reader tab's section is the one of the PDF it shows.
- Highlights carry the PDF's own page labels, and Zotero's sidebar lists them in reading order.
- The setup check's Python lines name the Python Scholium finds, no longer Zotero's PATH.
- More error messages end with what to do next: a paper without a PDF, or whose file is missing; a skill that could
  not be installed; a program set on the settings page that is gone; and the script's
  errors when Zotero does not answer, its local API is off, an item is not found or not the attachment's parent,
  authorisation is declined, the token file is not found, Zotero is older than 10 without the plugin, the `author`
  key is given, or a page is rotated.

### Fixed

- `status` and `samples` count a PDF's annotations on Zotero 7 to 9 too, whose local API lists none under an
  attachment: they ask the Scholium plugin then; without the plugin, `status` says so in place of the counts.
- `--backend api` on Zotero 7 to 9 says that their local API is read-only and to install the Scholium plugin, instead of
  that Zotero is not running.
- The profile editor keeps the keyboard: Tab and Shift+Tab stay in it, Esc closes it wherever the focus is, and the
  focus goes back to ⋯ when it closes.
- The settings layer opened from the keyboard starts at the model, so an arrow key no longer switches the agent.
- A run cut short by a plugin update, by disabling the plugin or by quitting Zotero shows how long it worked.
- After a setup check line's button ran the check again, the focus is on that line's button, or on Check.
- Text that was too faint is readable in the light and the dark theme: the line under an answer, the queue's handle,
  the title of a card without annotations, a failed card, the active tab and links; so are the setup check's ✓ and ✗.
- ⋯, Send, Stop and a queued message's ⋯ have names for screen readers. History is an icon like the buttons beside it.
- The tabs follow ← and →; the menus and the history follow ↑, ↓, Home and End.
- The setup check's buttons sit in the middle of their line, and a failed card's buttons side by side.
- Annotate again on one PDF of a paper no longer moves to the trash the reading note of another PDF of it that is being
  annotated or waits.
- A write that fails no longer leaves a new reading note behind.
- Through Zotero 10's local API, the reading note is written after every annotation was accepted, so annotations that
  are refused leave no new note; a note that is refused takes the new annotations back.
- Colours given in upper case are written in lower case, which Zotero requires.
- An edited question keeps its Undo while a dialog is open.
- A stopped or updated plugin starts no run, and a queued message is handed over to the new copy.
- An annotation that does not start gives its extra instructions back to the box. One stopped after its session was
  made leaves no empty session.
- Edit on a queued message keeps its quoted passage. Retry goes to the conversation shown when it was pressed.
- Words typed while a message is on its way stay in the box, and the same message entered twice is sent once.
- A conversation title being renamed is kept when the history closes.
- A conversation drawn while its tab was hidden opens at its end.
- An automatic compaction during an annotation shows its line.
- The profile editor works again after a failed read.
- The step shown while sentences are extracted is no longer the dry run.
- `"cleanup": "false"` and other values that are not true or false for a boolean key are refused instead of read as
  true. `null` for an optional key stands for its default.
- A `note_html` that holds the HTML itself, or names no file, is refused with a configuration error instead of a
  traceback.
- The local API and the JavaScript file refuse an `item_key` that is not the attachment's parent.
- With Zotero's local API turned off, the tool falls back to the other write channels.
- Annotation positions that are not numbers no longer stop a run or the profile.
- Sticky notes beside a narrow left column sit next to it.
- A paper selected again after another item shows its conversation and its annotation session again, instead of the
  Annotations tab's introduction.
- Claude Code is given the skill's folder with `--add-dir` only when it is there, in `CLAUDE_CONFIG_DIR` when that is
  set.
- In a Codex run, `uv run` keeps its cache and the Pythons it installs in `<data dir>/tmp/scholium/uv/`, where Codex's
  sandbox lets it write, unless `UV_CACHE_DIR` or `UV_PYTHON_INSTALL_DIR` is set.

## 0.2.1 (2026-11-06)

### Changed

- **Ask Scholium** is in the context menu of a PDF reader: a right click on selected text offers it, at the end of the
  menu. The selection popup no longer has it.
- A new icon: a page with a note over its corner, drawn for 16 and 20 px in the style of Zotero's item-pane icons, in a
  lighter violet on a dark theme; it shows in the Scholium section's header, the side navigation and the settings, and
  in colour in Zotero's Plugins list, which showed the default icon before.
- While an annotation runs, the Annotations tab no longer lists the six steps, and the state line shows only its dot,
  as for a question; the step and the time are in its tooltip.
- **Annotate again** deletes the paper's Scholium annotations and moves its Scholium reading notes to the trash as soon
  as it is confirmed, before the run starts; the confirmation says so.

### Fixed

- The settings layer is as wide as its longest option needs, so the model dropdown is no wider than its options;
  layers no longer reach past the pane's edge.
- `<sub>…</sub>` and `<sup>…</sup>` in an agent's answer show as subscript and superscript instead of the tags.
- After **Ask Scholium**, Zotero 10 no longer keeps drawing the cleared selection on the page, and on Zotero 7 the
  cursor goes to the box: opening the Scholium section no longer waits more than a second for it to scroll into view.

## 0.2.0 (2026-11-04)

### Added

- The run line of the transcript reads "Working for 12s" with a light sweeping across it, and "Compacting context for
  12s" while the agent compacts its context; the line of a compaction under way reads the same, swept alike. The
  sweep stops when the system asks for reduced motion. The state line beside the settings chip has the step only for
  an annotation ("step 3/6") and its dot for a question or a compaction; the time is in its tooltip. A finished run
  shows "Worked for 24s" with the run, with › to open its steps only when it has steps; a run that was interrupted,
  or stopped while it waited for a usage limit or a second try, shows no time. The state line of a finished run gives
  no duration.
- Saved prompts above the Chat tab's box (preference `savedPrompts`), sent with a click and edited,
  deleted (with **Undo**) and reordered in the row.
- Editing an earlier question of the Chat tab (✎ on hover) asks it again, with the agent chosen, from the conversation
  before it, replacing what followed, with **Undo** for six seconds (Claude Code `--resume-session-at` with
  `--fork-session`; Codex `thread/fork`; a new session given the conversation where that is refused or there is no
  point to go back to); the Codex threads only the replaced part used are archived at the next Codex run once the six
  seconds end or the plugin stops, on **Undo** those only the new part used.
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
- A context ring beside the send button: the share of the context window the chosen agent's session of the
  conversation took up in its latest request, with a layer of input, cache and output and **Compact this
  conversation's context**; `/compact` in the box does the same, and stays in the box while the paper cannot compact.
  Compactions, also the agents' own, show in the transcript with the sizes before and after. A compaction under way
  when the plugin is updated is handed over and runs again.
- Annotation sessions: each **Annotate** starts a session of its own (`annotate-<agent>-<time>.jsonl`, the
  index's `annotation`), shown on the Annotations tab with the six steps and their times, then a card with the
  highlights (core), margin notes, sticky notes and reading notes counted in Zotero, the warnings left, the turns
  and the tokens; a run that wrote none reads "No annotations written". Words typed there continue the session; **Annotate again** asks in place; a failed annotation
  offers **Retry**.
- **Ask Scholium** in the selection popup of a PDF reader (not of an EPUB or snapshot reader) closes the popup, puts
  the passage and its page label above the box of the Chat tab with the cursor in the box, and the next message
  quotes it to the agent with its page in the PDF and, where it differs, the label.
- Before its first session, the Annotations tab says how many of the tool's annotations the paper carries ("This
  paper carries 12 Scholium annotations", with who wrote them and when, where that is known), and its button reads
  **Annotate again**.
  **Delete annotations** deletes the tool's annotations of the PDF the section shows and trashes the paper's reading
  notes; its texts say "this PDF".
- Keyboard: the context ring and the citation chips take the focus; Enter or Space opens the ring's layer or locates
  the sentence; a focused chip shows its card, which opens on keyboard focus only. A layer opened from the keyboard
  (settings, ⋯, history, context, queued message) takes the focus; Esc or Tab out closes it, and Esc gives the focus
  back to its button. The tabs carry `aria-selected`; focus rings use Zotero's accent colour; the context ring turns
  Zotero's orange near the limit.
- Sentence citations: answers cite the paper's sentences as `[#n]`, shown as chips with the page and, on hover,
  the sentence; **Locate ↗** opens the PDF, goes to the sentence and highlights it briefly; a sentence without a
  position in `sentences.json` opens its page.
- A failed question offers **Retry** with the agent chosen; Esc twice on the same run stops it. A failed queued message
  retried after a newer message went first is asked again as a new question at the end; the failed one stays in the
  conversation with its failure.
- Scholium section: Claude Code and Codex share a paper's conversations. **New chat** starts one, **History** lists
  them by day to open, rename or delete (with **Undo**; every Codex thread the conversation used is archived at the
  next Codex run once the six seconds end or the plugin stops before then). Switching the agent keeps the conversation
  shown, as the settings layer says, and the agent chosen answers the next message: in its own session of the
  conversation, given the turns it
  has not seen (the text says the user went on asking in Zotero, some of it answered by another agent, each answer
  labelled), or in a new one given the conversation as text, each answer labelled with its agent (Codex as items of
  its new thread when all the answers are its own). Under each answer, the agent, the model and the time. Each
  conversation has its log in `<out dir>/conversations/`; the conversations of earlier versions (`claude-run.jsonl`,
  `codex-run.jsonl`) are in the list.
- Scholium section: a new session is told which configuration, agent and time wrote the paper's annotations, and a
  session that goes on is told when they were rewritten since, in this conversation or another, or that they are
  gone; an agent whose own rewrite in this conversation was cut away by an edit is told they were rewritten since its
  last turn. The section shows when each run ended.
- The plugin's apply returns `removeError` when the earlier notes cannot be moved to the trash after the new items
  are written.
- `sentences.json` gives each sentence's position (`rects`).

### Changed

- The plugin Scholium Bridge is now Scholium: add-on ID `scholium@zotero-scholium`, preferences
  `extensions.scholium.*`, endpoints `/scholium/ping`, `/scholium/list` and `/scholium/apply`, token file
  `scholium.token`, release file `scholium.xpi`. The tool's backend `bridge` is now `plugin` (`--backend bridge` still
  works). Installed beside Scholium Bridge (0.1.9 or earlier), Scholium uninstalls it and takes over its preferences
  and token; the conversations stay. A run under way in Scholium Bridge stops then, and its queued messages are not
  kept. Scholium also answers at `/scholium-bridge/…` and writes its token to `scholium-bridge.token` as well, for the
  skill of Scholium Bridge 0.1.9. Scholium Bridge does not update to Scholium by itself: install `scholium.xpi` from
  the release.
- Scholium section: the section fills the side pane's height. The state is one line beside the settings chip.
  Once the answer is there, the steps of a run fold into "Worked for 24s ›", a run without steps shows
  "Worked for 24s".
  The history is a layer of the PDF's conversations by day. ■ stops a run.
- Scholium section: annotating no longer continues the chat; the Chat tab is for questions.
- Scholium section: the conversations and the history are those of one PDF, the item's best PDF in the library
  and the open PDF in the reader.
- Token counts are written in k with thousands separators (`2,568k tokens`), in Chinese too.
- When an agent's program is not found, the message points to Zotero Settings → Scholium.
- Scholium section: when the agent no longer has a conversation's session (deleted in the Codex app, or cleaned up
  by Claude Code), a new session is given the conversation, as text or, for Codex when all the answers are its own, as
  items of its new thread, beyond ten exchanges the earlier ones as excerpts; a continuation after a limit or an
  update ends with that reason. A failed Claude Code run without text shows its errors.
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
- A question being edited keeps its box, words and quote when the conversation is drawn again. The queue's deleted
  row is the same **Undo** strip as elsewhere; the history rows' ✎ and 🗑, the quote strip's ✕ and **New chat** ＋ are
  icons.
- Scholium section: ■ or Esc twice on a paper whose message waits behind another paper's run puts its words back in
  its box, and an annotation's extra instructions back in that tab's box; an edited question that has not started is
  undone, and its **Undo** stays while it waits. If the log refuses the first line of a Chat run, its words go back to
  the box (a queued message's to its row, marked, with **Retry**) and the state line says it failed, with the reason;
  an annotation's extra instructions go back to the Annotations tab's box.
- Scholium section: a usage limit or a service limit pauses only the runs of the agent that hit it (and a message
  queued behind such a run on the same tab of that paper); the other agent's runs go on. Only sections whose next run
  waits for that limit show the pause, naming the agent, and **Continue now**, which continues that agent. "Queued,
  N ahead" counts neither held messages nor runs waiting for another limit. Words queued to an annotation session go
  to that session's agent.
- Scholium section: while **Annotate again** waits, the Annotations tab shows the coming session, and words typed
  there run in it after the annotation. An annotation's card counts the turns and tokens of all its parts, also those
  before a pause for a limit. `/compact` with no session starts none, and with nothing to compact yet says so under
  the box. Codex threads waiting to be archived stay listed until Codex has archived them.
- A paper with the logs of both agents from Scholium Bridge 0.1.9 opens the chosen agent's.
- Each run is given `paper.json` in the paper's output folder (the PDF's path, the item and attachment keys, the
  output folder); prompts name that file instead of the PDF's path, and `extract` and `--list` take it with
  `--config`. The agent writes its own configuration to another file in the output folder; `paper.json` is the
  plugin's and read-only.
- `scholium --apply --allow-missed` exits 0 when the write succeeded. The plugin keeps a write as the paper's
  configuration (`applied.json`) whenever its output says it was applied, also "partial", whatever the exit code; a
  write whose configuration is not found (a path through a shell variable, or one that does not exist) or is
  `paper.json` removes the kept one, and the next conversation is told to list the annotations.
- Codex runs do not read Codex's configuration. The names of the user's MCP servers come from Codex's
  `mcpServerStatus/list` (Codex starts each server to list it), kept in the preference `codexServers`. A Codex run
  while no names are kept (the first one) waits at most 10 s for the list; if none comes, it and the session's next
  Codex runs have the user's MCP servers until a list made in the background after it names them. Later runs use the
  kept names and list them again in the background after the session's first Codex run.
  The model menu shows *Codex's default* without a model name until a run with it shows which model that is.
- Editing a question, its **Undo** and saving the profile replace their files atomically. Numbered sentences for
  citation chips are kept for the 20 papers shown last.

### Fixed

- On Zotero 7 to 9, disabling, updating or uninstalling the plugin leaves the reader listeners of other plugins
  registered; the plugin does not unregister its own at shutdown.
- On Zotero 7, the Scholium section's text boxes no longer take the native Windows look, and drawing the section no
  longer logs a JSON.parse error.

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
