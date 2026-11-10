# Command-line use

English | [中文](cli.zh-CN.md)

The tool behind the skill can be run directly, for scripts or other agent frameworks.

```bash
pip install pymupdf
pip install .                            # provides the `scholium` command
```

Inside the skill the same file is `skills/zotero-scholium/scripts/scholium.py`. It takes the same arguments and runs in two ways:

```bash
python scholium.py …                     # with Python and PyMuPDF installed
uv run scholium.py …                     # uv reads the script's inline metadata (PEP 723) and fetches Python and PyMuPDF
```

## Steps

1. **Locate the item and its PDF attachment** (Zotero must be running, with its local API turned on):

   ```bash
   scholium status --query "direct preference optimization"   # matching items and their keys
   scholium status ITEM_KEY                 # the paper's PDFs, the annotations on them and its notes
   scholium samples --exclude ITEM_KEY      # a few highlights, margin texts and note openings of earlier runs, as a style reference
   ```

2. **Read the paper as numbered sentences.**

   ```bash
   scholium extract --pdf paper.pdf --sentences out/sentences.json --out out/sentences.txt
   ```

   The file starts with an index of its line numbers: where each page starts and, when they are found, where the main text ends, the references start, the text after them starts and an appendix after them starts.
   A PDF without a text layer (a scan without OCR) stops `extract` with exit code 3 and a JSON `error` that says to run OCR first.

3. **Write a configuration file.** A complete template is provided in [`skills/zotero-scholium/examples/config.template.json`](../skills/zotero-scholium/examples/config.template.json).

   ```json
   {
     "pdf": "/path/to/Zotero/storage/<ATTACHMENT_KEY>/paper.pdf",
     "item_key": "<ITEM_KEY>",
     "attachment_key": "<ATTACHMENT_KEY>",
     "out_dir": "out",
     "note_html": "reading_note.html",
     "note_title_prefix": "Direct Preference Optimization",
     "sentences": "out/sentences.json",
     "highlights": [
       {"id": 34, "core": true, "comment": "translation of the highlighted sentence"},
       {"page": 2, "core": false, "text": "In contrast, DPO directly optimizes for the policy best satisfying the preferences", "comment": "translation of the highlighted sentence"}
     ],
     "summaries": [
       {"id": 21, "text": "The figure shows the difference: no reward model and no sampling loop on the right."},
       {"page": 1, "place": "top", "font_size": 9, "text": "three or four sentences across the top of the first page"}
     ]
   }
   ```

   Include only the requested output types. Use a separate `out_dir` for each paper, such as `out/<ATTACHMENT_KEY>`, and place its sentence and note files there. Set `cleanup: true` only for a complete redo; without it a run only adds (added notes, margin remarks, a selected scope). A cleanup that would delete annotations of the tool that this configuration did not write is held back (`cleanup_other`) unless `--accept cleanup_other` is given. A cleanup changes in place what the new set holds again: an annotation at the same place keeps its key and only its changed fields are written (the report's `rewrite`). For a redo with a reading note, `note_replace: true` moves the tool's earlier notes to the trash.

   For an item in a group library, add `"group_id": <the group's id>` (the plugin's `paper.json` carries it), and give `status` and `samples` `--group <id>`.

   `cleanup`, `note_replace`, `cleanup_external`, `snap` and a highlight's `core` must be `true` or `false`; a string such as `"false"` is refused. `null` for an optional key means its default. `font_size`, like `band_min_font_size`, is a number from 4 to 36. `note_html` must be the path of an existing HTML file, not the HTML itself. Colours are `#rrggbb` in either case and are written in lower case, the form Zotero takes. A highlight's `comment` is the translation of its sentence; leave it out when the paper is already in the reader's language.

4. **Generate, review, and apply.** Run without `--apply` first, review all four warning fields below and correct the configuration before applying. (The skill runs `--apply` directly: it checks the same and writes nothing while a blocking finding remains.)

   ```bash
   scholium --config config.json            # build and report without writing
   scholium --config config.json --apply    # build, check, write into Zotero, read back (through the local API without the plugin: confirm the dialog once)
   scholium --config config.json --list     # counts, the annotations that are not the tool's own, note titles (--full: everything)
   ```

   Every run writes `annotations.json`, a fallback `create_annotations.js`, and `preview_p<N>.png` for the pages in `preview_pages` (none by default), and reports `missed` entries (each with the closest passage found on the page), `style_warnings`, `translation_warnings`, `layout_warnings`, and the PDF's hash before and after; fields with nothing to report (the hashes of a PDF that did not change among them) are left out unless `--verbose` is given. `--apply` refuses to write while `missed`, `style_warnings` (other than `core_count`) or `layout_warnings` is non-empty (`--accept KIND`, `--allow-missed`, `--allow-warnings`). A margin note without room takes the other margin of a one-column page, or else becomes a sticky note; a top or bottom band without room is set smaller, down to 8 pt, and without room even then becomes a sticky note.

   `--backend auto` (the default) writes through the Scholium plugin, else through the local API of Zotero 10, else through an older plugin, else into the JavaScript file. With the local API turned off it moves on to the next channel and the report says why; reads through the local API name the setting that turns it on. The local API and the JavaScript file, like the plugin, refuse an `item_key` that is not the attachment's parent before anything is written. Annotations carry the PDF's own page labels (the page numbers Zotero shows, such as `iv`), and their `sortIndex` follows the reading order, so Zotero lists them in the order of the text; the report still names pages by number, from 1.

   The script reaches Zotero at `127.0.0.1:23119`, or at the port that `SCHOLIUM_ZOTERO_PORT` names (a value that is not
   a port number stops it with an error); the plugin sets it to its Zotero's port for the agents it starts.

[`examples/direct_api_example.py`](../examples/direct_api_example.py) demonstrates the underlying Zotero 10 local API calls in approximately thirty lines for use in other applications.

## Reference

The skill's files are the reference for the command line too.

| File | Content |
|---|---|
| [`SKILL.md`](../skills/zotero-scholium/SKILL.md) | The workflow: locating the item, choosing sentences, writing comments and margin notes, invoking the script, verifying the result |
| [`references/configuration.md`](../skills/zotero-scholium/references/configuration.md) | Configuration keys, commands, and report fields |
| [`references/backends.md`](../skills/zotero-scholium/references/backends.md) | Write channels, failure handling, and pitfalls |
| [`references/batch.md`](../skills/zotero-scholium/references/batch.md) | Several papers in one request, with sub-agents; content reviews |
| [`references/profile.md`](../skills/zotero-scholium/references/profile.md) | The annotation profile: `scholium profile --from-library` derives it from the library's annotations, `scholium profile --path` prints where it is; precedence and procedure |
| [`references/style-zh.md`](../skills/zotero-scholium/references/style-zh.md) | Style guide for Chinese comments, margin notes, and reading notes |
| [`references/zotero-annotations.md`](../skills/zotero-scholium/references/zotero-annotations.md) | The annotation data model of Zotero |
| [`scripts/scholium.py`](../skills/zotero-scholium/scripts/scholium.py) | The tool, identical to `src/zotero_scholium/cli.py` |
| [`examples/`](../skills/zotero-scholium/examples/) | Configuration and reading-note templates |
| [`agents/openai.yaml`](../skills/zotero-scholium/agents/openai.yaml) | Display name and invocation policy for Codex |
