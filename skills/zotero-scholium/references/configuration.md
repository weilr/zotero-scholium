# Configuration and report reference

## Keys

| Key | Required | Meaning |
|---|---|---|
| `pdf` | yes | path of the PDF attachment |
| `item_key`, `attachment_key` | yes | Zotero keys of the parent item and the attachment |
| `out_dir` | yes | directory for generated files (`annotations.json`, `create_annotations.js`, previews); use `out/<ATTACHMENT_KEY>` to isolate papers |
| `sentences` | | the JSON written by `extract --sentences` (default `<out_dir>/sentences.json`); needed by entries that use `id` or `ids` |
| `highlights[]` | | see below |
| `summaries[]` | | see below |
| `levels` | | named colours, e.g. `{"claim": "#ff6666", "term": "#ffd400"}`, referenced by `level` in highlights |
| `note_html`, `note_title_prefix` | | HTML file of the child note; the prefix identifies an existing note with the same title, which then gets a versioned title |
| `core_color`, `other_color`, `text_color` | | defaults `#ff6666`, `#ffd400`, `#1a73e8` |
| `font_size` | | margin text size in points (default 8) |
| `margin_side` | | `auto` (default: the paragraph's side, or the wider margin), `left`, `right` |
| `summary_kind` | | `text` (default: visible margin text) or `note` (sticky notes) |
| `preview_pages` | | pages rendered as PNG previews (default `[1]`) |
| `snap` | | accept phrases matching at similarity ≥ 0.95 and report them under `snapped` (default false) |
| `core_range` | | `[low, high]`: expected number of highlights in `core_color`; a count outside it is a style warning |
| `banned_phrases` | | strings that must not occur in comments, margin texts or the note; each occurrence is a style warning |
| `data_dir` | | Zotero data directory (inferred from the PDF path or Zotero's preferences by default); holds the profile and the bridge token |
| `cleanup` | | `true` (default): replace the tool's tagged earlier annotations on the attachment; use only for a complete redo. Set `false` for added notes, margin remarks or selected-scope annotations: keep existing annotations and only add |
| `cleanup_external` | | bridge backend only: also remove annotations imported from the PDF file (default `false`) |
| `note_replace` | | replace existing child notes with the same title prefix (default `false`; keep it) |

### `highlights[]`

One of `id` (a sentence number from `sentences.txt`), `ids` (`[first, last]`, consecutive sentences on one page), or `page` + `text` (a verbatim phrase; a long span may give its first and last words separated by `…`, and `occurrence: N` selects the N-th appearance on the page). Colour: `core: true/false`, or `level` (a name in `levels`), or `color`. `comment` is the translation. Optional `type: "underline"`.

Include only requested output types. For limited-scope work, adjust or omit `core_range` rather than adding highlights to meet a whole-paper target. With `cleanup: false`, avoid sentences that are already highlighted.

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

A top band sits 6 pt below the page edge and moves down past a header line into the gap above the title, within the top 30 % of the page. A bottom band goes between the last line of text and the footer, or beneath the footer when that gap is too small, within the bottom 30 % of the page. Both avoid figures and existing annotations; a `layout_warning` means the page has no free space at that end.

## Commands

```bash
scholium.py extract --pdf <pdf> [--pages N-M] [--keep-references] [--sentences sentences.json] [--out file]
scholium.py --config <config.json>                 # build and report only
scholium.py --config <config.json> --apply         # build, report, write, read back
scholium.py --config <config.json> --list [--full] # what is currently stored on the attachment
```

Run without `--apply` first and review `missed`, `style_warnings`, `translation_warnings` and `layout_warnings`; correct the configuration before applying. `--apply` refuses to write while `missed` or `style_warnings` is non-empty (`--allow-missed`, `--allow-warnings` override). `--backend auto|api|bridge|js` selects the write channel; `--ignore-existing` skips reading the attachment's annotations before layout. `--list` prints the counts by type and colour, the annotations that are not the tool's own, and the note titles; `--list --full` prints every annotation with text, comment and position.

## Report fields

| Field | Content |
|---|---|
| `highlights`, `underlines`, `margin_texts`, `sticky_notes` | counts |
| `colors` | highlights per colour |
| `missed` | entries that could not be placed: an unknown `id`, a phrase not found (with `closest`, `similarity`, and a page `hint` when the closest passage is on a neighbouring page), or an invalid summary (`reason`) |
| `style_warnings` | `{kind, page, text, reason}`; kinds `latex`, `math_format`, `tag`, `label`, `symbol`, `line_break`, `banned_phrase`, `duplicate`, `overlap`, `user_overlap`, `core_count`, `note_math` |
| `translation_warnings` | comments with terms or numbers absent from the highlighted text, or a CJK-per-word ratio far outside the usual range |
| `snapped` | phrases accepted at similarity ≥ 0.95 (`snap: true`) |
| `ambiguous_matches` | phrases and anchors that occur more than once on their page; the first occurrence is used unless `occurrence` is set |
| `layout_warnings` | margin boxes for which no free space was found |
| `existing_annotations` | how many annotations were read from Zotero and how many rectangles were avoided, or why they were unavailable |
| `pdf_sha256` | the file's hash before and after the run and `unchanged` |
| `js`, `previews` | paths of the generated JavaScript file and preview PNGs |
| `applied`, `backend`, `result`, `now_in_zotero`, `apply_error`, `fallback` | with `--apply`: the channel used, the numbers removed and created, a read-back, or the cause of failure and the manual fallback |
| `verification` | API read-back: `missing_annotations` and `missing_notes` list newly returned keys that were not found |

The API's `result.createdKeys` and `result.noteKeys` identify newly written annotations and notes; `result.failed` records reported creation failures. API cleanup runs only after all new items are created successfully. The apply flow checks returned keys against a fresh read-back; missing keys or failed read-back leave `applied: false`. An HTTP exception may leave no `result`. A failure may follow partial writes: inspect any available result and run `--list` before retrying.
