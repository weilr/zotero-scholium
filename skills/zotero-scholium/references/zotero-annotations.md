# Zotero annotation data and write channels (reference)

## Annotation object

| Field | Meaning |
|---|---|
| `annotationType` | `highlight`, `underline`, `note`, `text`, `image`, or `ink`. The `text` type (a visible text box) exists since Zotero 7; older versions reject it, and the JavaScript fallback then degrades to `note`. |
| `annotationText` | highlight and underline only: the highlighted source text. |
| `annotationComment` | the comment; for `text` annotations, the displayed text itself. Must not contain hard line breaks; Zotero wraps the text to the box width. |
| `annotationColor` | `#rrggbb`. Zotero palette: yellow `#ffd400`, red `#ff6666`, green `#5fb236`, blue `#2ea8e5`, purple `#a28ae5`. |
| `annotationPageLabel` | page label string, usually the page number. |
| `annotationSortIndex` | `"ppppp|oooooo|ttttt"`: page index (5 digits), character offset (6 digits, may be 0), distance from the page top in PDF points (5 digits). Affects sidebar ordering only. |
| `annotationPosition` | JSON string. Highlight: `{"pageIndex":0,"rects":[[x0,y0,x1,y1],…]}`, one rectangle per line. Text: `{"pageIndex":0,"rects":[[x0,y0,x1,y1]],"fontSize":8,"rotation":0}`. Note: one 22×22 rectangle. Coordinates are in PDF user space (origin at the bottom left, y axis upward). PyMuPDF uses a top-left origin: `y_pdf = page.height − y_fitz` when the media box starts at 0. |
| `annotationAuthorName` | author name shown in the reader. Not set by the tool; the configuration key `author` is not accepted. Ownership is marked by the tag. |
| `annotationIsExternal` | `true` for annotations Zotero imported from the PDF file (displayed as locked). Not exposed by the local API. |
| `tags` | `[{"tag": "…"}]`. The tool tags everything it creates with `zotero-scholium`. |

## Official local API write support (Zotero 10 and later; preferred)

Zotero 10.0 (2026-08-17) added write requests to the local API; Zotero 7 to 9 remain read-only.

1. Read `Zotero-Server-ID` from the header of any `/api/` response. Keys are bound to that ID.
2. Send `POST /api/local/authorize` with the header `Zotero-Server-ID` and the body `{"appName": "zotero-scholium"}`. Zotero shows an *Allow / Always Allow / Deny* dialog and returns `{"key": <32 characters>, "remember": <bool>}`. Keys with `remember: true` are reusable; the tool stores them under `%APPDATA%/zotero-scholium/local-api-keys.json` (or `~/.config/zotero-scholium/`). Otherwise the key is single-use, and a 401 response on the next write indicates that authorisation must be repeated. At most 5 dialogs per minute are permitted (429 beyond that).
3. Every write request carries `Zotero-Server-ID` and `Zotero-API-Key`. `POST /api/users/0/items` accepts an array of at most 50 items and returns `{successful, failed}`. `DELETE /api/users/0/items?itemKey=A,B` requires `If-Unmodified-Since-Version` (taken from the `Last-Modified-Version` header of any GET) and returns 204.
4. Verified item shapes: `{"itemType":"annotation","parentItem":<attachment key>, …fields above…, "tags":[…]}`; `text` annotations retain `fontSize` and `rotation`. Child note: `{"itemType":"note","parentItem":<item key>,"note":<html>}`. Read back with `GET /api/users/0/items/<attachment key>/children?itemType=annotation`.

## scholium-bridge plugin (Zotero 7 to 9)

Endpoints on Zotero's own local server (`http://127.0.0.1:23119`, localhost only): `GET /scholium-bridge/ping`, `POST /scholium-bridge/list {attachmentKey}`, and `POST /scholium-bridge/apply {itemKey, attachmentKey, tag, cleanup, cleanupExternal, annotations[], note{html,titlePrefix,replace}}`. The header `X-Annotate-Token` must equal the content of `<Zotero data dir>/scholium-bridge.token`, created on first start. The endpoints accept data only; no code is executed. Installation: Tools → Plugins → gear icon → Install Plugin From File. Note for plugin authors: an endpoint's `init` must take exactly one parameter; otherwise Zotero's server treats it as the legacy callback style and never responds.

Rich text and mathematics: `annotationComment` and `annotationText` render only `<b> <i> <sub> <sup>`; write mathematics in comments with Unicode symbols and these tags. Note HTML renders mathematics through the note editor's KaTeX nodes: `<span class="math">$…$</span>` inline, `<pre class="math">$$…$$</pre>` for display equations.

## Routes not used

- Writing annotations into the PDF: they become external, locked annotations in Zotero, are stored in the database with an empty author, and the file is re-uploaded on synchronisation. Restoring the file leaves the locked copies in place, producing duplicates.
- `zotero.sqlite`: exclusively locked while Zotero is running.
- Web API: requires a zotero.org account, passes through the cloud, and arrives through synchronisation.
- MCP endpoints of other plugins: authenticated for their own runtime and not intended as a public interface.

## Margin layout used by the tool

Body column edges are the 2nd and 98th percentiles of word x-coordinates on the page (header and footer excluded), widened to the document-level extents (10th and 90th percentiles of the per-page estimates), so that a page with few full-width lines does not place boxes inside the text column. Two-column pages are detected by a small number of words crossing the page centre. A summary box is placed beside the first line of its anchor phrase, on the paragraph's side (two-column layouts) or in the wider margin, clamped between the footer line (28 pt) and the header line (page height minus 20 pt); boxes on one side are shifted downward to avoid overlap and moved upward if they would extend into the footer. Occupied space comprises the existing text, note, image and ink annotations read from Zotero before layout (the tool's own included when `cleanup` is false) and the page's images and vector drawings detected with PyMuPDF; boxes that cannot be placed without overlap are reported in `layout_warnings`. Previews are drawn on in-memory pages; the document is never saved.

Placement modes of `summaries[]`: `place: "top"` and `"bottom"` lay a box across the text column (`body_x0` to `body_x1`) at the page top (6 pt from the edge, descending past header lines to the first gap, staying within the top 30 % of the page) or bottom (between the last text line and the footer, or beneath the footer when that gap is too small, staying within the bottom 30 % of the page); the page's text lines, figures, existing annotations and boxes already placed are obstacles. `side: "left"` or `"right"` forces the margin. `kind: "note"` writes a 22 × 22 pt sticky note beside the anchor's first line, hugging the text column; two notes on adjacent lines are stacked. `rect: [x0, y0, x1, y1]` (points, origin at the top-left corner; on a 90 dpi preview, pixels ÷ 1.25) pins a box that is never moved; an overlap with text, a figure or an annotation is reported as a `layout_warning` and the box is still written. Per item `color` and `font_size` override `text_color` and `font_size`. Layout order on a page: explicit rectangles, then bands, then margin boxes and sticky notes.
