# scholium-bridge (Zotero 7 to 9)

Zotero 10 provides an official local API with write support, so this plugin is **not required on
Zotero 10 or later**; `scholium` communicates with Zotero directly. The plugin exists for Zotero 7, 8,
and 9, whose local API is read-only.

## Function

The plugin registers three endpoints on Zotero's built-in local HTTP server (`http://127.0.0.1:23119`,
which listens on localhost only):

| Endpoint | Purpose |
|---|---|
| `GET /scholium-bridge/ping` | returns `{ok, version, dataDir}`; no token required |
| `POST /scholium-bridge/list` | lists the annotations of one attachment and the child notes of its parent item |
| `POST /scholium-bridge/apply` | deletes annotations previously created by the tool, then creates highlights, text annotations, and optionally a child note |

Requests must carry the header `X-Annotate-Token`, whose value is the content of
`<Zotero data directory>/scholium-bridge.token`, a random string written by the plugin on first
start. The endpoints accept **data only**; no code is evaluated. The `apply` endpoint can create
annotations and notes, and can delete only annotations that carry the tool's tag or identical
content, or, when `cleanupExternal: true` is passed explicitly, annotations that Zotero
imported from the PDF file.

## Installation

In Zotero, open Tools → Plugins, click the gear icon, choose *Install Plugin From File…*, and select
`scholium-bridge.xpi` (available from the GitHub release, or built locally as described below). No
restart is required.

## Build

```bash
cd plugin/scholium-bridge
zip -r ../scholium-bridge.xpi manifest.json bootstrap.js
```

`manifest.json` and `bootstrap.js` must be located at the root of the archive.

## Note for plugin authors

The `init` method of an endpoint class must declare exactly one parameter. Zotero's server inspects
`init.length` and treats an arity of 0 or 2 as the legacy callback style, in which case the request
never resolves.
