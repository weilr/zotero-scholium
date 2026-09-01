---
name: zotero-scholium
description: "Annotate a paper in the user's Zotero library with native Zotero annotations — highlights on key sentences whose comment is a translation (default colours: red = core, yellow = other), short summaries rendered as editable text in the page margins, and a reading note under the item. Everything is written into Zotero's database; the PDF file is never modified. Use this skill whenever the user asks to annotate, highlight, mark up, take notes on, translate key sentences of, or write margin notes or a reading note for a paper in Zotero, in any language, even if the word \"Zotero\" is not mentioned but the paper evidently comes from their Zotero library. Do not use it for a plain \"summarize this paper\" request whose result is not written back into Zotero."
---

# Zotero paper annotation (native annotations and reading note)

## Outputs

| Output | Form | Rules |
|---|---|---|
| Key-sentence highlights | native Zotero `highlight` annotations | The comment is a translation of the sentence into the user's language, not an interpretation. Default colour scheme: `#ff6666` (red) for *core* statements, i.e. the paper's enumerated contributions, headline quantitative results, and central claim (approximately 10–15 per paper); `#ffd400` (yellow) for *other* points, i.e. method details, experimental setup, limitations, and useful observations (approximately 20–30). Colours are not assigned by topic. |
| Margin notes | native Zotero `text` annotations placed in the page margin beside the paragraph | Blue `#1a73e8`, 8 pt, without hard line breaks (Zotero wraps the text; the user must be able to edit it). At most one per paragraph, one or two sentences, written as a reader's own marginal remark. |
| Page summary | native Zotero `text` annotation across the top of the first page (`place: "top"`) | Only when the profile or the user asks for it. Three or four sentences: what the paper does, the decisive number, the reader's own judgement; not a restatement of the abstract. Same colour as the margin notes; `font_size` 9. |
| Reading note | child note (HTML) under the item | What a researcher records for later reference after reading: assessments, open questions, and specific figures, rather than a restatement of the abstract. |
| The PDF file | unchanged | Annotations written into the file are displayed as locked and duplicated in Zotero, and the modified file is synchronised. |

Sticky-note annotations (`note` type) are used only when the profile shows that habit or the user asks for them (`summary_kind: "note"`); otherwise the margin text must be visible on the page. Every annotation and note created by the skill carries the tag `zotero-scholium`, which allows a subsequent run to recognise its own output.

Write comments, margin notes, and the reading note in the language the user uses in the conversation. For Chinese, follow `references/style-zh.md`; it specifies the expected register in detail.

## Write channels

`scripts/scholium.py --apply` selects a backend automatically:

| Backend | Zotero | Notes |
|---|---|---|
| `api`: official local API | 10 and later (preferred) | The first run opens an "Allow / Always Allow" dialog in Zotero; inform the user in advance. The key is stored under `%APPDATA%/zotero-scholium/` (or `~/.config/zotero-scholium/`). No plugin is required. |
| `bridge`: plugin | 7 to 9 | The local API is read-only before Zotero 10. Ask the user once to download `scholium-bridge.xpi` from the project's GitHub releases page (https://github.com/weilr/zotero-scholium/releases) and install it (Tools → Plugins → gear icon → Install Plugin From File). |
| `js`: script file | fallback | `create_annotations.js`, to be executed in Tools → Developer → Run JavaScript. |

Do not write to `zotero.sqlite` directly (the database is locked while Zotero is running), and do not attempt to obtain tokens from other plugins' endpoints.

## Requirements

`scripts/scholium.py` needs Python 3.9 or later and PyMuPDF (`import pymupdf`). If the import fails, ask the user to run `pip install pymupdf`; do not install packages on their behalf. Zotero must be running.

## Workflow

### 0. Determine the annotation profile

The profile lives in the Zotero data directory, at `<Zotero data dir>/zotero-scholium/profile.md`; run `python <skill dir>/scripts/scholium.py profile --path` to print the resolved location (it also reports a profile left at the pre-0.1.0 location in the user configuration directory, which the next `profile --from-library` migrates).

Precedence, from lowest to highest:

1. **Defaults** in the table above, used only when nothing else applies.
2. **Learned profile**: the statistics that `profile --from-library` derives from the user's own annotations, together with the interpretation of those statistics. This is the starting point, not the final decision.
3. **The user's explicit instructions**, recorded in the `## User's rules (always win)` section of `profile.md` and given in the current conversation. An explicit instruction overrides the learned profile even where the library shows a different habit. The difference may be mentioned once; the instruction is then followed without further discussion. Where the user has given no instruction, the learned profile applies.

Procedure:

- If `profile.md` exists, read it in full: the learned sections first, then the user's rules, resolving conflicts in favour of the rules.
- If it does not exist, derive one before writing anything:
  ```bash
  python <skill dir>/scripts/scholium.py profile --from-library
  ```
  Complete the `___` placeholders with an interpretation of the statistics (for example, "yellow = terms; comments are one-line glossary entries"), present the completed draft to the user in a few lines, and ask them to confirm or correct it. Record their corrections, in their own words, in the `## User's rules (always win)` section; re-running the profile command preserves that section.
- Every later correction by the user (for example, "do not use blue" or "comments should be translations") is added to the same section, so that the next paper starts from it.
- A library with very few annotations provides no usable signal. In that case apply the defaults and state that this was done.

Translate the profile into configuration values: `levels` (colour names to hex values), `type: "underline"` where the user underlines, `summaries` only if the user writes margin text, `note_html` only if the user keeps reading notes, comment density and length as observed, and, from the interpretation and the user's rules, `margin_side`, `summary_kind`, `font_size`, and a `place: "top"` summary on page 1 (see Customisation).

### 1. Locate the item, the attachment, and the PDF (read-only)

```
GET http://localhost:23119/api/users/0/items?q=<title words>        -> item key
GET http://localhost:23119/api/users/0/items/<ITEM_KEY>/children   -> PDF attachment key and filename
```
The file is located at `<Zotero data dir>/storage/<ATTACHMENT_KEY>/<filename>`. If several PDFs are attached, prefer the published version ("Full Text", "Official") and leave preprints untouched. If the API does not respond, Zotero is not running; ask the user to start it.

### 2. Read the entire paper, then write the content

Run `python <skill dir>/scripts/scholium.py extract --pdf <pdf> --out <out_dir>/text.txt` and read that file once: it carries page markers (`--- p.N ---`), joins hyphenation, and drops running headers, footers and the bibliography, and a phrase copied from it matches in step 3 (`.zotero-ft-cache` and PyMuPDF remain as fallbacks). Read the appendices as well; ablations, failure cases, and engineering details are frequently reported there.

Write a JSON configuration (template: `examples/config.template.json`):

- **highlights**: `page` (1-based), `text` (verbatim; may span lines, since matching ignores whitespace, hyphenation, and ligatures, so text may be pasted from the extraction; avoid mathematical symbols such as ≥ and ×; a long span may give just its first and last few words separated by an ellipsis, `Our model achieves … the training costs`, and the tool highlights everything between the anchors; `occurrence: N` picks the N-th appearance when the text repeats on the page), `core`, and `comment` (the translation). Mark as core: the contributions enumerated in the introduction, the main claim of the abstract, the first quantitative sentence of each results subsection, and the summary sentence of the conclusion. Each sentence is highlighted once; for a sentence that crosses a page break, use only the part on one page.
- **summaries**: `page`, `anchor` (a unique phrase inside the paragraph, used to locate its first line), and `text`. At most one per paragraph; omit paragraphs for which there is nothing substantive to say. Optional per item: `place` (`"top"` or `"bottom"`: a box across the text column at that end of the page, no anchor needed), `side` (`"left"` or `"right"`), `color`, `font_size`, and `kind: "note"` (a sticky note). See Customisation.
- **note_html**: path of the reading note (template: `examples/reading_note.template.html`).

### 3. Generate and check (no writing yet)

```bash
python <skill dir>/scripts/scholium.py --config <config.json>
```
The tool matches the phrases, measures the text columns, lays out the margin boxes (on the paragraph's own side in two-column papers, clear of figures, existing annotations, neighbouring boxes, the header, and the footer), writes `annotations.json` and the fallback `create_annotations.js`, renders `preview_p<N>.png`, and reports `missed`.

- `missed` must be empty. Each entry reports the closest passage on the page (`closest`, with `similarity` and sometimes a page `hint`); copy `closest` into the configuration instead of re-reading the paper. Typical causes: the phrase spans a page break, contains a symbol, or a small-caps word is joined to its neighbour in the extraction (`MODELNAMEoutperforms`). With `"snap": true` matches at similarity 0.95 or higher are accepted automatically and listed under `snapped`; check that list.
- `ambiguous_matches` lists phrases and anchors that occur more than once on their page; the annotation sits at the first occurrence (`used: 1`). To pick another one, set `"occurrence": N` on the item; an explicit occurrence is not warned about.
- The report is the check; do not open the previews by default. Open a preview PNG only when a `layout_warning` cannot be resolved from the report alone, and open only the affected page (the preview font spaces Latin letters irregularly; Zotero renders the text correctly). Keep `preview_pages` at its default `[1]`; add a page only for such an inspection.
- Review `translation_warnings` in the output. Each entry names a comment that contains terms or numbers absent from the highlighted text, or that is much longer or shorter than the span it translates. Correct the comment or extend the highlight until the list is empty; the only acceptable residue is a unit or format conversion.
- Check `existing_annotations` in the output. When Zotero was reachable it reports how many existing annotations were read and how many rectangles were avoided; margin notes are then guaranteed not to cover the user's own annotations. If it reports `unavailable`, tell the user that existing annotations could not be taken into account. `layout_warnings` lists boxes for which the margin had no free space; move the summary to a neighbouring paragraph or drop it.
- A band (`place: "top"` or `"bottom"`) is laid across the text column, above the title, or between the text and the footer (beneath the footer when that gap is too small). A `layout_warning` for it means the page has no free space at that end: shorten the text or move it to the other end of the page.
- Confirm that the checksum of the PDF has not changed.
- Re-read every comment in `annotations.json` against the style checklist before applying.

### 4. Write into Zotero

```bash
python <skill dir>/scripts/scholium.py --config <config.json> --apply
```
`backend` in the output identifies the channel used; `result` reports the numbers removed and created; `now_in_zotero` is a read-back. Ask the user to close and reopen the PDF. If `applied` is `false`, act on `apply_error` (install the plugin on Zotero 7–9, or fall back to executing the JavaScript file). `--list` reads back annotations and note titles at any time.

Repeated runs are safe: only annotations tagged by the tool (or with identical content) are replaced; the user's own annotations remain; existing notes are never deleted (a new note receives a versioned title). Iterate by editing the configuration and re-applying; do not edit the generated JavaScript by hand.

## Batch runs

Annotate one paper per agent context. For several papers, run one sub-agent (or one fresh session) per paper, pass it only the item key, the attachment key, and the profile location, and have it report a single line back (counts, note title, remaining warnings). Do not start a second paper in a context that has already read one: the whole context is re-sent on every model call, so the cost grows with the square of the number of papers.

## Customisation

The user states preferences in conversation or in the `## User's rules (always win)` section of the profile; the assistant translates them into configuration fields. Everything not listed here is content, not layout, and is handled by the profile and the writing rules.

| Request or rule | Configuration |
|---|---|
| a summary at the top of page 1 | `{"page": 1, "place": "top", "font_size": 9, "text": "…"}` in `summaries` |
| a remark at the bottom of page N | `{"page": N, "place": "bottom", "text": "…"}` |
| a short summary at the start of each section | `anchor` = the section heading, default placement (no new field) |
| notes on the left or right margin | `"margin_side": "left"` or `"right"` (per item: `side`) |
| a larger or smaller font, another colour | `font_size`, `color` (global, or per item) |
| sticky notes instead of margin text | `"summary_kind": "note"` (per item: `kind`) |
| the summary in the reading note rather than on the page | `note_html` (no new field) |

A top band is placed 6 pt below the page edge and moves down past a header line into the gap above the title; it stays within the top 30 % of the page. A bottom band goes between the last line of text and the footer, or beneath the footer when that gap is too small, and stays within the bottom 30 % of the page. Both avoid figures and existing annotations.

## Writing rules (any language)

The objective is output that reads as a researcher's own notes rather than generated text. The difference lies in register, not in terminology.

- **Translations**: the comment translates exactly the highlighted span, no more and no less. It must not add context from the surrounding text, the rest of the sentence, or the reader's own interpretation, and it must not omit part of the span. If the span is too short to stand alone, extend the highlight to the full sentence rather than the translation. Produce each comment as the output of the following instruction, with `${sourceText}` replaced by the highlighted span (for a target language other than Chinese, substitute that language):

  ```
  As an AI academic expert, translate the following English text to Chinese with native fluency and technical precision. Keep core ML terms (attention, transformer, loss, etc.) and model/dataset names in English. Use standard Chinese translations for established concepts. Make it read naturally for Chinese researchers.

  Text: ${sourceText}

  Output only the translation.
  ```

  The comment contains the translation only: no notes, no alternatives, no source text. Numbers and model names stay unchanged (rewriting a number in the target language's own convention, such as 500k as a native numeral, is acceptable).
- **Margin notes**: complete sentences; no `label: content` format; no arrows, circled numbers, or bracketed tags. Reactions ("larger than expected"), questions ("why only axis-aligned rotations?"), and cross-references ("inconsistent with the ablation on p. 8?") are appropriate. Leave a paragraph without a note rather than write filler. Usually 15–40 words.
- **Mathematics**: in highlight comments and margin texts, write mathematics with Unicode symbols and `<sub>`/`<sup>` (`d<sub>k</sub>`, `x<sup>2</sup>`, √, ×, ≤, α); the reader renders only the tags `<b> <i> <sub> <sup>`, and raw LaTeX stays visible as source. In the reading note use the note editor's math nodes, rendered with KaTeX: `<span class="math">$d_k$</span>` inline, `<pre class="math">$$…$$</pre>` for a display equation.

- **Reading note**: paragraphs rather than bullet lists with bold labels; concrete figures; first-person assessments and unresolved questions; limitations in the authors' words together with the reader's own; the full citation and code link at the end, without a sign-off line. Vary sentence length. Avoid stock phrases ("it is worth noting", "not only … but also", "marks a milestone"), em-dash asides, emoji, and aphoristic closing sentences.
- Before applying, review every comment: label-colon notes, symbols, stock phrases, and the absence of any judgement of the reader's own are all defects to be corrected first.

## Configuration keys

Required: `pdf`, `item_key`, `attachment_key`, `out_dir`. Content: `highlights[]`, `summaries[]`, `note_html`, `note_title_prefix`. Optional: `core_color`, `other_color`, `text_color`, `font_size` (8), `margin_side` (`auto`, `left`, `right`), `summary_kind` (`text`, `note`), `preview_pages` (keep the default `[1]`), `snap` (default false: accept phrases matching at similarity ≥ 0.95, reported under `snapped`), `data_dir` (bridge backend), `cleanup` (default true: remove the tool's own earlier annotations on the attachment before writing; set false when the user wants every existing annotation kept, and then do not highlight sentences the user already highlighted), `cleanup_external` (bridge backend, default false), `note_replace` (keep `false`; it deletes every child note whose title starts with the prefix). Per `summaries[]` item: `place`, `side`, `color`, `font_size`, `kind`, `occurrence`; per `highlights[]` item: `occurrence`.

## Known pitfalls

- Locked or duplicated annotations originate from a PDF that once contained annotations; Zotero imports them as external. Do not write into PDFs, and leave external annotations untouched unless the user asks otherwise.
- Hard line breaks in text annotations make them impractical to edit.
- Both multi-colour topic schemes and single-colour schemes are generally rejected by users; use a small number of levels with an explicit rule.
- Never delete a user's notes, including earlier versions generated by the tool.
- Zotero 10 API keys are bound to the instance's `Zotero-Server-ID`; a renewed authorisation dialog after reinstalling Zotero is expected behaviour.

Data formats (annotation JSON, sort index, authorisation flow, plugin endpoints): `references/zotero-annotations.md`.
