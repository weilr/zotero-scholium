# scholium-bridge

The plugin has two functions:

- **Reader toggle** (Zotero 7 and later): hides the tool's annotations in the reader until they are
  asked for.
- **Write endpoints** (needed on Zotero 7 to 9 only): Zotero 10 provides an official local API with
  write support, which `scholium` uses directly; the local API of Zotero 7, 8, and 9 is read-only.

## Reader toggle

Annotations that carry the tool's tag `zotero-scholium` are hidden in every reader view: reader tabs,
reader windows, and the attachment preview in the item pane. The eye button at the right end of the
reader toolbar shows them in that tab or window, and a second click hides them again. Every newly
opened reader starts hidden, and each reader is toggled separately. Annotations that the tool writes
or changes while a reader is open follow that reader's state.

Hiding removes the annotations from the reader's view and sidebar only. The stored annotations, their
synchronisation, searches, and notes created from annotations are not affected. Disabling or removing
the plugin shows them again in open readers.

## Write endpoints

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
annotations and notes, and can delete only annotations that carry the tool's tag, or, when
`cleanupExternal: true` is passed explicitly, annotations that Zotero imported from the PDF file.

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

## Notes for plugin authors

Every annotation reaches a reader view through `ReaderInstance.prototype._getAnnotation`, when the
reader opens and when Zotero reports added or modified items; the toggle wraps that method and
returns `null` for hidden annotations. `ReaderInstance` is not exported, so the prototype is reached
through the first reader instance: an open reader at startup, or a reader caught as Zotero pushes it
to `Zotero.Reader._readers` (before it loads its annotations) or returns it from
`Zotero.Reader.openPreview`. These two hooks are removed once the prototype is reached. The button is
added through `Zotero.Reader.registerEventListener("renderToolbar", …)`.

The `init` method of an endpoint class must declare exactly one parameter. Zotero's server inspects
`init.length` and treats an arity of 0 or 2 as the legacy callback style, in which case the request
never resolves.
