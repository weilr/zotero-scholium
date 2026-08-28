# Changelog

## 0.1.0 (unreleased)

Initial public version.

- `scholium` command-line interface: highlights and underlines with comments and named colour
  levels, margin text annotations with automatic layout, and an optional child note. The PDF file is
  only read.
- `scholium profile --from-library`: derives the user's annotation habits (colours, annotation types,
  comment length and style, density, notes) from the annotations in their own library and writes a
  profile draft to be completed by the agent together with the user.
- Backends: the official local API of Zotero 10 and later (no plugin required), the
  `scholium-bridge` plugin for Zotero 7 to 9, and a Run-JavaScript file as a last resort.
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
