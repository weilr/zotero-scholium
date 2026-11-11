# Configuration and report reference

## Keys

| Key | Required | Meaning |
|---|---|---|
| `pdf` | yes | path of the PDF attachment |
| `item_key`, `attachment_key` | yes | Zotero keys of the parent item and the attachment |
| `out_dir` | yes | directory for generated files (`annotations.json`, `create_annotations.js`, previews); use `out/<ATTACHMENT_KEY>` to isolate papers |
| `group_id`, `library_id` | | the item's group library (its group id) and Zotero's id of that library, as the plugin's `paper.json` gives them; without them, My Library, unless `paper.json` in `out_dir` names the same attachment's library |
| `sentences` | | the JSON written by `extract --sentences` (default `<out_dir>/sentences.json`); needed by `id` or `ids`. Its PDF fingerprint must match the current file; re-extract legacy caches without a fingerprint or after changing the PDF |
| `highlights[]` | | see below |
| `summaries[]` | | see below |
| `levels` | | named colours, e.g. `{"claim": "#ff6666", "term": "#ffd400"}`, referenced by `level` in highlights |
| `note_html`, `note_title_prefix` | | HTML file of the child note; the prefix identifies an existing note with the same title, which then gets a versioned title. A note of the tool with the same text is not written again |
| `core_color`, `other_color`, `text_color` | | defaults `#ff6666`, `#ffd400`, `#1a73e8` |
| `font_size` | | margin text size in points (default 8) |
| `margin_side` | | `auto` (default: the paragraph's side, or the wider margin; in one column the other margin when text such as a vertical preprint stamp sits beside the paragraph), `left`, `right`. Margin boxes keep clear of text in the margins |
| `summary_kind` | | `text` (default: visible margin text) or `note` (sticky notes) |
| `preview_pages` | | pages rendered as PNG previews (default `[]`: none) |
| `snap` | | accept phrases matching at similarity ≥ 0.95 and report them under `snapped` (default false) |
| `core_range` | | `[low, high]`: expected number of highlights in `core_color`; a count outside it is reported (`core_count`) without blocking `--apply` |
| `banned_phrases` | | strings that must not occur in comments, margin texts or the note; each occurrence is a style warning |
| `data_dir` | | Zotero data directory (inferred from the PDF path or Zotero's preferences by default); holds the profile and the plugin's token |
| `cleanup` | | `false` (default): keep existing annotations and only add; text the tool already wrote on the same page is reported as `duplicate_existing`. `true`, only for a complete redo: the tool's tagged earlier annotations on the attachment are replaced. One that a new annotation holds again (the same type and page, the same text or comment, or the same place) is kept as it is, or changed in place in the fields that differ (never the user's tags or a page label they set); the others are deleted once the new ones are written (`cleanup_removes` counts them, `rewrite` gives created, updated, kept and removed); those this configuration did not write are held back as `cleanup_other` |
| `cleanup_external` | | plugin backend only: also remove annotations imported from the PDF file (default `false`) |
| `note_replace` | | `true` for a redo: once the new note is written, the tool's earlier notes under the item go to Zotero's trash (only those whose title starts with `note_title_prefix`, when it is set); notes without the tool's tags are never touched. The note this output folder wrote last is rewritten in place instead, keeping its key, while it is as the tool stored it; one whose text the user changed is held back as `user_edit`, and one with the user's markup, images or title goes to the trash as the others do. Default `false` |
| `band_min_font_size` | | smallest size a top or bottom band is set to when it has no room at its own (default 8; 4 to 36); without room even then the band becomes a sticky note |

### `highlights[]`

One of `id` (a sentence number from `sentences.txt`), `ids` (`[first, last]`, consecutive sentences on one page), or `page` + `text` (a verbatim phrase; a long span may give its first and last words separated by `…`, and `occurrence: N` selects the N-th appearance on the page). Colour: `core: true/false`, or `level` (a name in `levels`), or `color`. `comment` is the translation. Optional `type: "underline"`.

Keys outside this table, misspelt ones included, end the run with a config error naming the nearest valid key. Include only requested output types. For limited-scope work, adjust or omit `core_range` rather than adding highlights to meet a whole-paper target. With `cleanup: false`, avoid sentences that are already highlighted.

Ids require an exact text match. If a sentence also appears inside another sentence, or a range matches multiple passages, the entry is reported as ambiguous instead of selecting the first match. After checking the page, set `occurrence` to the intended passage; repeated complete sentences retain their existing id-based ordering.

### `summaries[]`

`text` and one of `id` (a sentence of the paragraph), `page` + `anchor` (a unique phrase locating the paragraph; `occurrence` when it repeats), or `page` + `place: "top"` / `"bottom"` (a band across the text column at that end of the page). Optional `side` (`left`, `right`), `color`, `font_size`, `kind: "note"` (sticky note), `rect` (`[x0, y0, x1, y1]` in points from the top-left corner, for a fixed position).

## Customisation

| Request or rule | Configuration |
|---|---|
| a summary at the top of page 1 | `{"page": 1, "place": "top", "font_size": 9, "text": "…"}` in `summaries` |
| a remark at the bottom of page N | `{"page": N, "place": "bottom", "text": "…"}` |
| a short summary at the start of each section | `id` of the section's first sentence, default placement |
| notes on the left or right margin | `"margin_side": "left"` or `"right"` (per item: `side`) |
| a larger or smaller font, another colour | `font_size`, `color` (global, or per item) |
| sticky notes instead of margin text | `"summary_kind": "note"` (per item: `kind`) |
| the summary in the reading note rather than on the page | `note_html` |

A top band sits 6 pt below the page edge and moves down past a header line into the gap above the title, within the top 30 % of the page. When that gap is too small, it goes into the strip between the page edge (2 pt) and the first line, beside a logo or another figure there. A bottom band goes between the last line of text and the footer, or beneath the footer when that gap is too small, within the bottom 30 % of the page. Both avoid figures and existing annotations. A band without room at its font size is set smaller in steps of 0.5 pt, down to `band_min_font_size`, and listed under `fitted`. When even that size has no room, it is written as a sticky note with the whole text as its comment, in the margin beside the column's first text line (top) or its last above the footer (bottom), and listed under `as_notes`.

## Commands

```bash
scholium.py status <ITEM_OR_PDF_KEY>               # the paper's PDFs, annotations and notes, before a configuration exists
scholium.py status --query "<title words>"         # matching items
scholium.py samples [KEY …] [--query W] [--exclude KEY] [--papers 2] [--per-kind 4]   # style examples of earlier runs
                                                   # status and samples: --group <id> reads a group library
scholium.py extract --pdf <pdf> [--pages N-M] [--keep-references] [--sentences sentences.json] [--out file]   # prints lines and characters
scholium.py --config <config.json> [--verbose]     # build and report only (--verbose: every report field)
scholium.py --config <config.json> --apply         # build, report, write, read back
scholium.py --config <config.json> --list [--full] # what is currently stored on the attachment
```

`extract` removes the bibliography (unless `--keep-references`) and a paper checklist (from its heading to the next appendix heading or the end); the page marker of a rotated page reads `--- p.N (rotated: not annotatable) ---`. With `--sentences`, the file `--out` writes starts with an index of its line numbers: each page's start and, when found, the main text's lines, the references' line, where the text after them starts (`after the references`, when it does not start with an appendix heading) and where an appendix after them starts (a heading starting with Appendix, Appendices or Supplementary).

`--apply` checks first and reports `missed`, `style_warnings`, `translation_warnings` and `layout_warnings` as a run without `--apply` does, which only checks; `--apply` refuses to write while `missed`, `style_warnings` (other than `core_count`) or `layout_warnings` is non-empty, or when the annotations already on the attachment could not be read; `--accept KIND[,KIND]` lets those style kinds through (`layout` for layout warnings), `--allow-missed` and `--allow-warnings` override them; when the annotations already on the attachment could not be read, only `--ignore-existing` writes anyway, and not with `cleanup: true`. `--backend auto|api|plugin|js` selects the write channel; `--ignore-existing` skips reading the attachment's annotations before layout, and `--apply` refuses it with `cleanup: true`. `--list` prints the counts by type and colour, the annotations that are not the tool's own, and the note titles; `--list --full` prints every annotation with text, comment and position.

## Report fields

Without `--verbose` the report leaves out empty lists and zero counts, `js`, `pdf_sha256` while the PDF is unchanged, `existing_annotations` when they were read, and after a successful write `backend_reason`, `verification` and the empty fields and `keys` of `result`.

| Field | Content |
|---|---|
| `highlights`, `underlines`, `margin_texts`, `sticky_notes` | counts |
| `colors` | highlights per colour |
| `missed` | entries that could not be placed: an unknown `id`, a phrase not found (with `closest`, `similarity`, and a page `hint` when the closest passage is on a neighbouring page), an invalid summary, or an item on a rotated page, where nothing is written (`reason`) |
| `style_warnings` | `{kind, page, text, reason}`; kinds `latex`, `math_format`, `tag`, `label`, `symbol`, `line_break`, `banned_phrase`, `duplicate`, `overlap`, `user_overlap`, `duplicate_existing`, `user_edit` (with `cleanup`: a tool's annotation the user changed in Zotero after it was written, which the rewrite would delete, or change in what the user changed: its comment, colour, text or place; the reason names the change; with `note_replace`: the reading note this folder wrote, changed by the user since), `cleanup_other` (with `cleanup`: the tool's annotations the cleanup would delete that neither this configuration file's last write created nor the new set holds again on their page, by text, comment or place; `--accept cleanup_other` for a complete redo the user asked for), `core_count` (advisory), `note_title` (a reading note that does not start with its `<h1>` title, or an empty one), `note_math` |
| `cleanup_removes` | how many of the tool's earlier annotations a run with `cleanup: true` deletes (`null` when they could not be read) |
| `translation_warnings` | comments with terms or numbers absent from the highlighted text (a comment in a Latin-script language: its numbers and its acronyms, CamelCase names and words with digits or Greek letters only), or a CJK-per-word ratio far outside the usual range |
| `snapped` | phrases accepted at similarity ≥ 0.95 (`snap: true`) |
| `ambiguous_matches` | phrases and anchors that occur more than once on their page; the first occurrence is used unless `occurrence` is set |
| `layout_warnings` | sticky notes with no room in their margin, or in a margin narrower than the icon; explicit rectangles over text, a figure or an annotation |
| `fitted` | bands set smaller to fit, with the font sizes before and after |
| `as_notes` | sticky notes written for boxes without room: a margin box with no gap tall enough in its margin (and, on a one-column page with `side: auto`, in the other one), taller than the page allows, or in a margin narrower than a box (30 pt), beside the first line of its paragraph; a band without room even at `band_min_font_size`, beside the first or last line of text |
| `existing_annotations` | how many annotations were read from Zotero and how many rectangles were avoided, or why they were unavailable |
| `pdf_sha256` | the file's hash before and after the run and `unchanged` |
| `js`, `previews` | paths of the generated JavaScript file and of the preview PNGs (`previews` only when pages were rendered) |
| `applied`, `backend`, `result`, `now_in_zotero`, `apply_error`, `fallback` | with `--apply`: the channel used, the numbers removed, created and moved to the trash (`result.notesTrashed`; `result.noteReplace` when a plugin before 0.1.9 left the notes), a read-back, or the cause of failure and the manual fallback; `applied` is `"partial"` when the new items were written but removing the earlier ones failed (`result.removeError`); `applied`, `apply_error` and `fallback` come last |
| `verification` | read-back: `missing_annotations` and `missing_notes` list newly returned keys that were not found (local API, and the plugin from 0.1.9) |

The keys of newly written annotations and notes (`createdKeys`, `noteKeys`) go to `applied_keys.json` in `out_dir` (`result.keys`), with the configuration's path, those changed and kept in place (`updatedKeys`, `keptKeys`), with `cleanup` the keys it replaced (`replacedKeys`), and fingerprints of what it left (`written`, `notes`, from the read-back), which later runs compare to tell the user's changes from the tool's; a write that wrote nothing leaves the file as it was; `result.failed` records reported creation failures. Items go in batches of 50; a batch that fails ends the write, `createdKeys` keeps the keys of the batches before it, and the failure's `items` names the items from that batch on, which may or may not exist. Every channel removes the old annotations only after all new items are created; the plugin and the generated JavaScript do both in one transaction, so a failure leaves the old ones. Through the local API, a removal that fails after the new items are written leaves `applied: "partial"`, as does, through the local API or the plugin, a move of the earlier notes to the trash that fails: run `--list` before running again. The apply flow checks returned keys against a fresh read-back, and the changed annotations' comment, colour and text (`verification.not_updated`); missing keys, changes not read back or a failed read-back leave `applied: false`. A change in place that fails (through the local API each item's version guards it) leaves `applied: "partial"`; a write whose annotations to change or delete changed since the run listed them (their version, or their date for the plugin and the JavaScript file) writes nothing and asks to run again. An older plugin, whose listing has no `canUpdate`, makes no changes in place: it deletes and creates them. An HTTP exception may leave no `result`. A failure may follow partial writes: inspect any available result and run `--list` before retrying.
