# Changelog

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
