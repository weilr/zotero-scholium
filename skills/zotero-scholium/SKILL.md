---
name: zotero-scholium
description: "Use when the user asks to highlight, translate key sentences, or write annotations, margin notes or reading notes back to a paper in their Zotero library. Excludes summaries that are not written back to Zotero."
---

# Zotero paper annotation (native annotations and reading note)

## Outputs

Create only the output types and paper scope the user requests. Current instructions override the saved profile and defaults.

| Output | Form | Rules |
|---|---|---|
| Key-sentence highlights | native `highlight` annotations | The comment is a translation of the sentence into the user's language, not an interpretation. Default colours: `#ff6666` (red) for *core* statements — the enumerated contributions, headline results, the central claim (about 10–15 per paper); `#ffd400` (yellow) for *other* points — method details, setup, limitations, useful observations (about 20–30). Colours are not assigned by topic. |
| Margin notes | native `text` annotations in the page margin beside the paragraph | Blue `#1a73e8`, 8 pt, no hard line breaks. At most one per paragraph, one or two sentences, a reader's own remark. |
| Page summary | `text` annotation across the top of page 1 (`place: "top"`) | Only when the profile or the user asks for it: three or four sentences, `font_size` 9. |
| Reading note | child note (HTML) under the item | What a researcher records after reading: assessments, open questions, specific figures. |
| The PDF file | unchanged | |

Sticky notes (`kind: "note"`) only when the profile shows that habit or the user asks. Everything created carries the tag `zotero-scholium`. Use the requested language, otherwise the conversation's language; for Chinese follow `references/style-zh.md`.

## Requirements

`scripts/scholium.py` needs Python 3.9 or later and PyMuPDF (`import pymupdf`; if missing, ask the user to run `pip install pymupdf`). Zotero must be running. The write channel (local API on Zotero 10, the bridge plugin on 7–9, a JavaScript file as fallback) is selected automatically: `references/backends.md`.

## Workflow

Run `python <skill dir>/scripts/scholium.py …` from any directory. Use a separate `<out_dir>` for each attachment, e.g. `out/<ATTACHMENT_KEY>`.

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
For a whole-paper task, read `sentences.txt` in full, appendices included; for a selected scope, read that scope with enough context. It contains page markers, headings and numbered sentences grouped by paragraph; headers, footers and bibliography are removed. Use `--pages N-M` if output is truncated. Do not also read the PDF or full-text cache.

Write one configuration from `examples/config.template.json`, including only requested outputs. Set `cleanup: true` only for a complete redo; use `cleanup: false` when adding notes, margin remarks or annotations within a selected scope. Keep `note_replace: false`.

- `highlights[]`: `id` (one sentence) or `ids: [first, last]` (consecutive sentences on one page), `core`, and `comment` (the translation). Core: the contributions enumerated in the introduction, the main claim of the abstract, the first quantitative sentence of each results subsection, the summary sentence of the conclusion. Each sentence at most once.
- `summaries[]`: `id` (a sentence of the paragraph) and `text`; omit paragraphs with nothing substantive to say.
- `note_html`: the reading note (template: `examples/reading_note.template.html`).
- Use the profile's `banned_phrases`; use its `core_range` for whole-paper highlighting, adjusting or omitting it for a limited scope. `sentences` is the JSON written above (default `<out_dir>/sentences.json`). Other fields and defaults: `references/configuration.md`.

### 3. Review the report, then apply

```bash
python <skill dir>/scripts/scholium.py --config <config.json>
python <skill dir>/scripts/scholium.py --config <config.json> --apply
```
First run without `--apply`. Review the report and correct the configuration before running with `--apply`; this is a quality check, not another request for write permission. `--apply` resolves ids, lays out annotations, checks, writes and reads back. It refuses to write while `missed` or `style_warnings` is non-empty.

- `missed`: unknown ids, or phrases not found (each with the closest passage, `closest`).
- `style_warnings`: formatting, banned phrases, duplicate or overlapping highlights, core count or note math issues; kinds are listed in `references/configuration.md`.
- `translation_warnings`: a comment with terms or numbers absent from the sentence, or much longer or shorter than it. Correct the translation or extend the highlight to cover its source.
- `layout_warnings`: a margin box without free space; move the note to a neighbouring paragraph or drop it. Open a preview PNG only for this, and only that page.
- `colors`, `ambiguous_matches`, `existing_annotations`, `pdf_sha256`, `now_in_zotero`: `references/configuration.md`.

After successful apply, ask the user to close and reopen the PDF. `applied: false` names the cause in `apply_error` (`references/backends.md`). If a write partially succeeded or read-back failed, run `--list` to reconcile the stored items before retrying. Do not re-read `annotations.json` or the configuration: the comments are already in your context.

With `cleanup: true`, repeated runs replace only annotations carrying the tool's current or legacy tags, never untagged annotations with identical content. Notes receive versioned titles. Iterate by editing the configuration; never edit the generated JavaScript.

## Batch runs

Annotate one paper per agent context. First determine whether the request covers one paper or several. One paper is annotated directly. Only when it covers several, ask the user before starting whether to annotate them one after another or with several sub-agents in parallel, and wait for the answer. Sub-agent calls issued in one response run in parallel; one call per response runs them in sequence.

The coordinating context only dispatches and collects. Start with a short context (a fresh session, or after compacting). Each dispatch includes the item key, attachment key, profile location, current task scope and requested output types, language, temporary preferences, the skill/script path, and a unique `out_dir` named after the attachment key. Preserve the user's instructions when dispatching. Wait for each sub-agent once instead of polling; the coordinator does not run `scholium.py`, read a paper or open a report. Each sub-agent performs steps 1–3 and reports counts, note title and remaining warnings. Do not start a second paper in a context that has already read one.

A content review, when the user asks for one, runs in a fresh sub-agent with the configuration, report and `sentences.txt`, and returns a findings list. A fresh sub-agent makes corrections from the configuration and findings. Both receive the same task scope, language and preferences as the writer.

## Writing rules

- **Translations**: comments contain only a faithful translation of the highlighted sentence, without reader judgements or questions. Expand fragments to a full sentence when needed. Preserve numbers and model names. The full Chinese translation prompt is in `references/style-zh.md`; for other languages, translate naturally with technical precision.
- **Margin notes**: complete sentences; no `label: content` form, arrows, circled numbers or bracketed tags. Reactions, questions and cross-references are appropriate; no filler; usually 15–40 words.
- **Mathematics**: in comments and margin notes use Unicode and `<sub>`/`<sup>` (`d<sub>k</sub>`, `x<sup>2</sup>`, √, ×, ≤, α); the reader renders only `<b> <i> <sub> <sup>`. In the reading note use the editor's math nodes, rendered with KaTeX: `<span class="math">$d_k$</span>` inline, `<pre class="math">$$…$$</pre>` for a display equation.
- **Reading note**: paragraphs rather than labelled bullet lists; concrete figures; first-person assessments and open questions; limitations in the authors' words and the reader's own; the citation and code link at the end, no sign-off. No stock phrases, em-dash asides, emoji, or aphoristic closing sentences.
- Before applying, read every requested output once more: comments must stay faithful to the source; reader judgements and questions belong in margin notes and reading notes.

For configuration fields, defaults and report details, read `references/configuration.md`. For annotation data formats, read `references/zotero-annotations.md`.
