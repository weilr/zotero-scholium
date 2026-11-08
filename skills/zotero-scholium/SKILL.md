---
name: zotero-scholium
description: "Use when the user asks to highlight, translate key sentences, or write annotations, margin notes, page summaries or reading notes back to a paper in their Zotero library, or to redo, extend or correct such annotations. Excludes summaries that are not written back to Zotero."
---

# Zotero paper annotation (native annotations and reading note)

## Outputs

Create only the output types and paper scope the user requests. Current instructions override the saved profile and defaults.

| Output | Form | Rules |
|---|---|---|
| Key-sentence highlights | native `highlight` annotations | The comment is a translation of the sentence into the user's language, not an interpretation; a paper already in the user's language gets no comments. Default colours: `#ff6666` (red) for *core* statements — the enumerated contributions, headline results, the central claim (about 10–15 per paper); `#ffd400` (yellow) for *other* points — method details, setup, limitations, useful observations. Colours are not assigned by topic. |
| Margin notes | native `text` annotations in the page margin beside the paragraph | Blue `#1a73e8`, 8 pt, no hard line breaks. At most one per paragraph, one or two sentences, a reader's own remark. |
| Page summary | `text` annotation across the top of page 1 (`place: "top"`) | Only when the profile or the user asks for it: three or four sentences, `font_size` 9. |
| Reading note | child note (HTML) under the item | What a researcher records after reading: assessments, open questions, specific figures. |
| The PDF file | unchanged | |

Sticky notes (`kind: "note"`) only when the profile shows that habit or the user asks. Everything created carries the tag `zotero-scholium`. Use the requested language, otherwise the conversation's language; for Chinese follow `references/style-zh.md`.

## Requirements

Run `scholium.py …` below as `uv run <skill dir>/scripts/scholium.py …` from any directory when `uv` is on PATH (it brings Python and PyMuPDF), else as `python <skill dir>/scripts/scholium.py …` (if Python or PyMuPDF is missing, ask the user to install uv or run `pip install -U pymupdf`). Zotero must be running. For an item in a group library, `paper.json` carries `group_id`: keep it in your configuration and give `status` and `samples` `--group <id>`. The write channel (the Scholium plugin when installed, else the local API on Zotero 10, a JavaScript file as fallback) is selected automatically; read `references/backends.md` only when `--apply` does not write.

## Workflow

Use a separate `<out_dir>` for each attachment, e.g. `out/<ATTACHMENT_KEY>`, and keep every file you write for the paper there. Write files with your file-writing tool, not a shell here-document.

### 0. Profile

Read the profile: its path is the `profile` field of `status` (step 1), or the one a launching prompt names. Its `## User's rules (always win)` section overrides the learned statistics, and both override the defaults above. If the file does not exist, run `scholium.py profile --from-library`, complete the draft with the user, and record their corrections in that section (details: `references/profile.md`); in a run with no user to answer, use the defaults and create no profile. When the profile or the user asks to follow the style of earlier annotations, `scholium.py samples [KEY …] [--query WORDS] --exclude <this paper's key>` prints a few highlights, margin texts and the start of the reading note of each such paper; do not dump annotations or notes through the API.

### 1. Locate the item and the PDF (read-only)

```bash
scholium.py status --query "<title words>"   # matching items and their keys
scholium.py status <ITEM_KEY>                # the paper's current state
```
`status` gives the item's authors, date, venue, DOI and URL (for the note's citation), its PDF attachments with their file paths and the annotations already on each (the tool's own by type and colour, and the user's), and the notes under the item (title, length, whether the tool wrote them). Prefer the published version over a preprint. An error saying Zotero does not answer: ask the user to start it; "Zotero's local API is turned off": ask the user to turn on Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*.

### 2. Read the paper once, then write the configuration

```bash
scholium.py extract --pdf <pdf> --sentences <out_dir>/sentences.json --out <out_dir>/sentences.txt
```
When a launching prompt names the paper as a JSON file (`paper.json`), pass that file as `--config <file>` in place of `--pdf <pdf>`, and do not edit it: write your configuration to a file of its own.
If `extract` exits with code 3 (a scan without text), stop and give the user its `error` message.
`sentences.txt` holds page markers, headings and numbered sentences by paragraph, without headers, footers, bibliography and paper checklist; its first lines give the line where each page, the main text, the references and the appendix after them start. Read by them: for the whole paper, the main text in full and only the appendix parts it calls essential; for a scope or page limit, those pages with context. Issue a long part's reads together in one response. Do not also read the PDF or full-text cache.

Extraction creates the output directories and binds `sentences.json` to the PDF's SHA-256; re-extract after the PDF is replaced. If an id is reported as ambiguous, check the page's matching passages and set `occurrence` explicitly; do not guess a position.

Write one configuration from `examples/config.template.json`, including only requested outputs; unknown keys are refused. When the task includes the reading note, first read `examples/reading_note.template.html` (and `references/style-zh.md` for Chinese) and follow its title and sections. Without `cleanup` a run only adds, and text the tool already wrote on a page is refused as `duplicate_existing`. Set `cleanup: true` for a complete redo, and to change or add to annotations already written: edit the configuration they were written from, which holds the paper's whole set, and apply it whole (a separate configuration with only new entries would be deleted by the next whole rewrite). The tool's earlier annotations on the PDF are then replaced (the report's `cleanup_removes` counts them). When the reading note is rewritten too, `note_replace: true` moves the tool's earlier notes to the trash once the new one is written; the user's notes are never touched.

- `highlights[]`: `id` (one sentence) or `ids: [first, last]` (consecutive sentences on one page), `core`, and `comment` (the translation; left out when the paper is in the user's language). Core: the contributions enumerated in the introduction, the main claim of the abstract, the first quantitative sentence of each results subsection, the summary sentence of the conclusion. Each sentence at most once.
- `summaries[]`: `id` (a sentence of the paragraph) and `text`; omit paragraphs with nothing substantive to say.
- `note_html`: the reading note.
- Take banned phrases and the expected number of core highlights from the profile's rules (`banned_phrases`, `core_range`); adjust or omit `core_range` for a limited scope. `sentences` is the JSON written above (default `<out_dir>/sentences.json`). Other fields (colour levels, underlines, sticky notes, placement): `references/configuration.md`, only when the task needs one.

### 3. Review the report, then apply

```bash
scholium.py --config <config.json>
scholium.py --config <config.json> --apply
```
First run without `--apply`. Review the report and correct all its findings in one edit of the configuration (or one rewrite); this is a quality check, not another request for write permission. After correcting, run `--apply` directly: it repeats every check and writes nothing while `missed`, `style_warnings` or `layout_warnings` holds a blocking finding, so a second dry run is not needed. Its outcome is the last field of its output.

- `missed`: unknown ids, or phrases not found (each with the closest passage, `closest`).
- `style_warnings`: formatting, banned phrases, duplicate or overlapping highlights, text the tool already wrote on the page (`duplicate_existing`), the user's changes in Zotero that a rewrite would undo (`user_edit`), a note without its `<h1>` title (`note_title`), note math. `core_count` only informs. For a deliberate exception the user asked for, `--accept KIND` lets that kind through.
- `translation_warnings` (advisory): terms or numbers absent from the sentence, or a comment much longer or shorter than it. Correct a translation that adds or omits content, or extend the highlight to its source; never alter a faithful translation only to silence a warning.
- `layout_warnings`: a box that still has no room says what to change. A margin box without room takes the other margin of a one-column page, or else becomes a sticky note beside its paragraph; a top or bottom band is set smaller, down to 8 pt (`fitted`), or else becomes a sticky note beside the first or last line of text (`as_notes` lists the sticky notes).
- Other fields only inform; empty ones are left out. `ambiguous_matches` lists phrases that occur more than once on their page, placed at the first occurrence unless `occurrence` is set.

The report names each problem and what to change; reading `scholium.py`'s source is not needed.

Open readers show the new annotations by themselves; do not ask the user to reopen the PDF. The apply output has already read the result back: do not run `status` or `--list` after a successful write. `applied: false` names the cause in `apply_error` (`references/backends.md`). If a write partially succeeded or read-back failed, run `--list` to reconcile the stored items before retrying. Do not re-read `annotations.json` or the configuration: the comments are already in your context.

Only annotations carrying the tool's current or legacy tags are ever replaced, never untagged ones with identical content. A note with the same title as an existing one gets a versioned title. Iterate by editing the configuration; never edit the generated JavaScript.

## Several papers, reviews

Annotate one paper per agent context; a single paper is annotated directly. Before starting a request that covers several papers, or a content review the user asks for, read `references/batch.md`.

## Writing rules

- **Translations**: comments contain only a faithful translation of the highlighted sentence, without reader judgements or questions. Expand fragments to a full sentence when needed. Preserve numbers and model names. The full Chinese translation prompt is in `references/style-zh.md`; for other languages, translate naturally with technical precision.
- **Margin notes**: complete sentences; no `label: content` form, arrows, circled numbers or bracketed tags. Reactions, questions and cross-references are appropriate; no filler; usually 15–40 words.
- **Mathematics**: in comments use Unicode and `<sub>`/`<sup>` (`d<sub>k</sub>`, `x<sup>2</sup>`, √, ×, ≤, α); the reader renders only `<b> <i> <sub> <sup>`. Margin text on the page shows no tags: the tool writes `<sub>`/`<sup>` there as Unicode (dₖ, x²) or with `_`/`^` (π_ref). In the reading note use the editor's math nodes, rendered with KaTeX: `<span class="math">$d_k$</span>` inline, `<pre class="math">$$…$$</pre>` for a display equation.
- **Reading note**: paragraphs rather than labelled bullet lists; concrete figures; first-person assessments and open questions; limitations in the authors' words and the reader's own; at the end the citation (from `status`) and the code link when the paper gives one, no sign-off. Look nothing up on the web or in Zotero's database. No stock phrases, em-dash asides, emoji, or aphoristic closing sentences.
- Before applying, read every requested output once more: comments must stay faithful to the source; reader judgements and questions belong in margin notes and reading notes.

Read `references/configuration.md` only for an option or report field not described here, and `references/zotero-annotations.md` (annotation data formats) only when investigating a write problem.
