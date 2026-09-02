---
name: zotero-scholium
description: "Annotate a paper in the user's Zotero library with native Zotero annotations — highlights on key sentences whose comment is a translation (default colours: red = core, yellow = other), short summaries rendered as editable text in the page margins, and a reading note under the item. Everything is written into Zotero's database; the PDF file is never modified. Use this skill whenever the user asks to annotate, highlight, mark up, take notes on, translate key sentences of, or write margin notes or a reading note for a paper in Zotero, in any language, even if the word \"Zotero\" is not mentioned but the paper evidently comes from their Zotero library. Do not use it for a plain \"summarize this paper\" request whose result is not written back into Zotero."
---

# Zotero paper annotation (native annotations and reading note)

## Outputs

| Output | Form | Rules |
|---|---|---|
| Key-sentence highlights | native `highlight` annotations | The comment is a translation of the sentence into the user's language, not an interpretation. Default colours: `#ff6666` (red) for *core* statements — the enumerated contributions, headline results, the central claim (about 10–15 per paper); `#ffd400` (yellow) for *other* points — method details, setup, limitations, useful observations (about 20–30). Colours are not assigned by topic. |
| Margin notes | native `text` annotations in the page margin beside the paragraph | Blue `#1a73e8`, 8 pt, no hard line breaks. At most one per paragraph, one or two sentences, a reader's own remark. |
| Page summary | `text` annotation across the top of page 1 (`place: "top"`) | Only when the profile or the user asks for it: three or four sentences, `font_size` 9. |
| Reading note | child note (HTML) under the item | What a researcher records after reading: assessments, open questions, specific figures. |
| The PDF file | unchanged | |

Sticky notes (`kind: "note"`) only when the profile shows that habit or the user asks. Everything created carries the tag `zotero-scholium`. Write in the language the user uses in the conversation; for Chinese follow `references/style-zh.md`.

## Requirements

`scripts/scholium.py` needs Python 3.9 or later and PyMuPDF (`import pymupdf`; if missing, ask the user to run `pip install pymupdf`). Zotero must be running. The write channel (local API on Zotero 10, the bridge plugin on 7–9, a JavaScript file as fallback) is selected automatically: `references/backends.md`.

## Workflow

Run `python <skill dir>/scripts/scholium.py …` from any directory. One paper takes about five tool calls: locate, extract, write the configuration, apply, report.

### 0. Profile

Read `<Zotero data dir>/zotero-scholium/profile.md` (`scholium.py profile --path` prints the location). Its `## User's rules (always win)` section overrides the learned statistics, and both override the defaults above. If the file does not exist, run `scholium.py profile --from-library`, complete the draft with the user, and record their corrections in that section. Details: `references/profile.md`.

### 1. Locate the item and the PDF (read-only)

```
GET http://localhost:23119/api/users/0/items?q=<title words>        -> item key
GET http://localhost:23119/api/users/0/items/<ITEM_KEY>/children   -> PDF attachment key and filename
```
The file is `<Zotero data dir>/storage/<ATTACHMENT_KEY>/<filename>`. Prefer the published version over a preprint. No response: Zotero is not running; ask the user to start it.

### 2. Read the paper once, then write the configuration

```bash
python <skill dir>/scripts/scholium.py extract --pdf <pdf> --sentences <out_dir>/sentences.json --out <out_dir>/sentences.txt
```
Read `sentences.txt` in full, appendices included: page markers, `## heading` lines, one numbered sentence per line, a blank line between paragraphs; running headers, footers and the bibliography are already removed. If the tool output is truncated, read it in parts with `--pages N-M`. Do not read the PDF or the full-text cache as well.

Then write the whole configuration at once (template: `examples/config.template.json`):

- `highlights[]`: `id` (one sentence) or `ids: [first, last]` (consecutive sentences on one page), `core`, and `comment` (the translation). Core: the contributions enumerated in the introduction, the main claim of the abstract, the first quantitative sentence of each results subsection, the summary sentence of the conclusion. Each sentence at most once.
- `summaries[]`: `id` (a sentence of the paragraph) and `text`. At most one per paragraph; omit paragraphs with nothing substantive to say. Optional `place: "top"` or `"bottom"` (a band across the page, no id), `side`, `color`, `font_size`, `kind`.
- `note_html`: the reading note (template: `examples/reading_note.template.html`).
- `core_range` and `banned_phrases` from the profile; `sentences` is the JSON written above (default `<out_dir>/sentences.json`).

### 3. Apply and check the report

```bash
python <skill dir>/scripts/scholium.py --config <config.json> --apply
```
One run resolves the ids, lays out the margin boxes clear of figures, existing annotations, the header and the footer, checks, writes, and reads back. Nothing is written while `missed` or `style_warnings` is non-empty: correct the configuration in place and run again (a paper normally needs one or two runs).

- `missed`: unknown ids, or phrases not found (each with the closest passage, `closest`).
- `style_warnings`: raw LaTeX or `^`/`_{` in a comment, a tag the reader does not render, a label-colon margin note, arrows or circled numbers, a hard line break, a phrase from `banned_phrases`, duplicate or intersecting highlights, a highlight over an existing annotation, a core count outside `core_range`, a note math node with a double backslash or LaTeX outside a node.
- `translation_warnings`: a comment with terms or numbers absent from the sentence, or much longer or shorter than it. Correct it or extend the highlight; a unit conversion is the only acceptable residue.
- `layout_warnings`: a margin box without free space; move the note to a neighbouring paragraph or drop it. Open a preview PNG only for this, and only that page.
- `colors`, `ambiguous_matches`, `existing_annotations`, `pdf_sha256`, `now_in_zotero`: `references/configuration.md`.

Ask the user to close and reopen the PDF. `applied: false` names the cause in `apply_error` (`references/backends.md`). Do not re-read `annotations.json` or the configuration: the comments are already in your context.

Repeated runs replace only the tool's own annotations; the user's annotations stay; notes are never deleted (a new note receives a versioned title). Iterate by editing the configuration and re-applying; never edit the generated JavaScript.

## Batch runs

Annotate one paper per agent context. First determine whether the request covers one paper or several. One paper is annotated directly. Only when it covers several, ask the user before starting whether to annotate them one after another or with several sub-agents in parallel, and wait for the answer. Sub-agent calls issued in one response run in parallel; one call per response runs them in sequence.

The coordinating context only dispatches and collects. It starts the batch with a short context (a fresh session, or after compacting), passes each sub-agent only the item key, the attachment key, and the profile location, waits for each sub-agent once instead of polling, and does not run `scholium.py`, read a paper, or open a report itself. Each sub-agent performs steps 1–3 in full and reports one line: counts, note title, remaining warnings. Do not start a second paper in a context that has already read one: the whole context is re-sent on every model call, so the cost grows with the square of the number of papers.

A content review, when the user asks for one, runs in a fresh sub-agent that receives only the configuration file, the report, and `sentences.txt`, and returns its findings as a list. Corrections are made by a fresh sub-agent that receives the configuration file and that list, not by resuming the sub-agent that wrote the paper.

## Writing rules

- **Translations**: the comment translates exactly the highlighted sentence, nothing more and nothing less; a fragment too short to stand alone is highlighted as its full sentence instead. Produce each comment as the output of the following instruction, with `${sourceText}` replaced by the sentence (for a target language other than Chinese, substitute that language):

  ```
  As an AI academic expert, translate the following English text to Chinese with native fluency and technical precision. Keep core ML terms (attention, transformer, loss, etc.) and model/dataset names in English. Use standard Chinese translations for established concepts. Make it read naturally for Chinese researchers.

  Text: ${sourceText}

  Output only the translation.
  ```

  The comment contains the translation only. Numbers and model names stay unchanged.
- **Margin notes**: complete sentences; no `label: content` form, arrows, circled numbers or bracketed tags. Reactions, questions and cross-references are appropriate; no filler; usually 15–40 words.
- **Mathematics**: in comments and margin notes use Unicode and `<sub>`/`<sup>` (`d<sub>k</sub>`, `x<sup>2</sup>`, √, ×, ≤, α); the reader renders only `<b> <i> <sub> <sup>`. In the reading note use the editor's math nodes, rendered with KaTeX: `<span class="math">$d_k$</span>` inline, `<pre class="math">$$…$$</pre>` for a display equation.
- **Reading note**: paragraphs rather than labelled bullet lists; concrete figures; first-person assessments and open questions; limitations in the authors' words and the reader's own; the citation and code link at the end, no sign-off. No stock phrases, em-dash asides, emoji, or aphoristic closing sentences.
- Before applying, read every comment you wrote once more: the absence of any judgement of the reader's own is a defect only reading finds.

## Configuration keys

Required: `pdf`, `item_key`, `attachment_key`, `out_dir`. Content: `highlights[]`, `summaries[]`, `note_html`, `note_title_prefix`, `sentences`. Optional: `levels`, `core_color`, `other_color`, `text_color`, `font_size`, `margin_side`, `summary_kind`, `preview_pages` (keep `[1]`), `snap`, `core_range`, `banned_phrases`, `cleanup`, `cleanup_external`, `note_replace` (keep `false`), `data_dir`. Fields, defaults, per-item options, the customisation table and the report fields: `references/configuration.md`. Data formats: `references/zotero-annotations.md`.
