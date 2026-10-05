# Command-line use

English | [中文](cli.zh-CN.md)

The tool behind the skill can be run directly, for scripts or other agent frameworks.

```bash
pip install pymupdf
pip install .                            # provides the `scholium` command
```

Inside the skill the same file is `skills/zotero-scholium/scripts/scholium.py`; `python scholium.py …` takes the same arguments.

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

   Include only the requested output types. Use a separate `out_dir` for each paper, such as `out/<ATTACHMENT_KEY>`, and place its sentence and note files there. Set `cleanup: true` only for a complete redo; for added notes, margin remarks or a selected scope, set `cleanup: false`.

4. **Generate, review, and apply.** Run without `--apply` first, review all four warning fields below and correct the configuration before applying.

   ```bash
   scholium --config config.json            # build and report without writing
   scholium --config config.json --apply    # build, check, write into Zotero, read back (Zotero 10: confirm the dialog once)
   scholium --config config.json --list     # counts, the annotations that are not the tool's own, note titles (--full: everything)
   ```

   Every run writes `annotations.json`, a fallback `create_annotations.js`, and `preview_p<N>.png` for the configured pages, and reports `missed` entries (each with the closest passage found on the page), `style_warnings`, `translation_warnings`, `layout_warnings`, and the PDF's hash before and after. `--apply` refuses to write while `missed`, `style_warnings` or `layout_warnings` is non-empty (`--allow-missed`, `--allow-warnings`).

[`examples/direct_api_example.py`](../examples/direct_api_example.py) demonstrates the underlying Zotero 10 local API calls in approximately thirty lines for use in other applications.

## Reference

The skill's files are the reference for the command line too.

| File | Content |
|---|---|
| [`SKILL.md`](../skills/zotero-scholium/SKILL.md) | The workflow: locating the item, choosing sentences, writing comments and margin notes, invoking the script, verifying the result |
| [`references/configuration.md`](../skills/zotero-scholium/references/configuration.md) | Configuration keys, commands, and report fields |
| [`references/backends.md`](../skills/zotero-scholium/references/backends.md) | Write channels, failure handling, and pitfalls |
| [`references/profile.md`](../skills/zotero-scholium/references/profile.md) | The annotation profile: `scholium profile --from-library` derives it from the library's annotations, `scholium profile --path` prints where it is; precedence and procedure |
| [`references/style-zh.md`](../skills/zotero-scholium/references/style-zh.md) | Style guide for Chinese comments, margin notes, and reading notes |
| [`references/zotero-annotations.md`](../skills/zotero-scholium/references/zotero-annotations.md) | The annotation data model of Zotero |
| [`scripts/scholium.py`](../skills/zotero-scholium/scripts/scholium.py) | The tool, identical to `src/zotero_scholium/cli.py` |
| [`examples/`](../skills/zotero-scholium/examples/) | Configuration and reading-note templates |
| [`agents/openai.yaml`](../skills/zotero-scholium/agents/openai.yaml) | Display name and invocation policy for Codex |
