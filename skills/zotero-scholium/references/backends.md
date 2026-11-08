# Write channels and pitfalls

`scholium.py --apply` selects a backend automatically (`--backend` forces one):

| Backend | Zotero | Notes |
|---|---|---|
| `plugin`: Scholium plugin | 7 and later | Taken first when the plugin is 0.1.9 or later: the annotations are written, and with `cleanup` the old ones removed, in one transaction, and the new keys are checked on read-back. An older plugin leaves `note_replace` undone (`result.noteReplace` says so). On Zotero 7 to 9, whose local API is read-only, it is the only write channel; ask the user once to download `scholium.xpi` from https://github.com/weilr/zotero-scholium/releases and install it (Tools → Plugins → gear icon → Install Plugin From File). |
| `api`: official local API | 10 and later | Taken without the plugin or with an older one. The first run opens an "Allow / Always Allow" dialog in Zotero; tell the user in advance to choose "Always Allow". The key is stored under `%APPDATA%/zotero-scholium/` (or `~/.config/zotero-scholium/`). |
| `js`: script file | fallback | `create_annotations.js`, to be executed in Tools → Developer → Run JavaScript with "Run as async function" enabled. |

Do not write to `zotero.sqlite` directly (the database is locked while Zotero is running), and do not attempt to obtain tokens from other plugins' endpoints.

## When `applied` is `false`

`apply_error` names the cause:

- `missed`, `style_warnings` or `layout_warnings` non-empty: correct the configuration and run again.
- The annotations already on the attachment could not be read: run again once Zotero answers. Writing without them (`--ignore-existing`) can add a second copy of what the tool wrote before; with `cleanup: true`, `--apply` refuses `--ignore-existing`.
- Zotero 7–9 without the plugin: guide the installation, then run again.
- An item in a group library: every channel writes into the library `group_id` names (the local API through `/api/groups/<id>`; a plugin before 0.2.2 writes My Library only and is not used for it). A group the user cannot edit refuses the write: tell the user.
- No write channel: `backend_reason` says why each channel was unavailable (Zotero not running, a Zotero before 10, the plugin missing or its token not matching); fix the cause, or let the user run `create_annotations.js` (path in `fallback`).
- An HTTP error from the local API: report it verbatim; a renewed authorisation dialog after reinstalling Zotero or moving the data directory is expected, since keys are bound to the instance's `Zotero-Server-ID`.
- Partial writes or failed read-back: inspect any available `result` and run `--list` to reconcile actual stored annotations and notes before retrying. HTTP exceptions may leave no result; `applied: false` does not mean nothing was written. `applied: "partial"`: the new items were written, but removing the earlier ones failed (`result.removeError`).

## Pitfalls

- Locked or duplicated annotations originate from a PDF that once contained annotations; Zotero imports them as external. Never write into the PDF, and leave external annotations untouched unless the user asks otherwise (`cleanup_external`, plugin backend only).
- Hard line breaks in text annotations make them impractical to edit.
- Follow the user's colour rules; otherwise use the profile or default core/other levels.
- Never delete a user's notes. `note_replace: true` moves only the tool's own earlier notes to the trash, for a redo; do not move or delete notes through the API yourself.
- The tool does not write `annotationAuthorName`. API, plugin and generated JavaScript recognise ownership only by `zotero-scholium` or the legacy tags `zotero-marginalia`, `zotero-paper-annotate`; identical content alone never establishes ownership. The plugin's explicit `cleanup_external` option is separate.
- Every channel writes through Zotero, so open readers show the new annotations at once; with the Scholium plugin, its eye button in the reader toolbar shows or hides the tool's annotations (hidden until it is first turned on).
