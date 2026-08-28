# Design notes

## Native annotations versus annotations embedded in the PDF file

Writing highlights into the PDF file (for example with PyMuPDF) appears to be the most direct route,
but Zotero treats annotations stored in the file as *external*: they are displayed as locked,
read-only objects, Zotero keeps a copy of them in its database, and the modified attachment is
uploaded on the next synchronisation. If the file is later restored, the database copies remain and
the annotations appear duplicated. Native annotations, stored as rows in Zotero's own database, are
editable, are synchronised as data, and leave the PDF file untouched.

## Write channels

| Route | Availability | Assessment |
|---|---|---|
| **Local API write requests** (`POST /api/users/0/items`) | Zotero 10.0 and later (August 2026). One-time confirmation dialog; the key is bound to the Zotero instance. | **Primary channel.** Official, requires no plugin, supports `annotation` items including the `text` type, child notes, and batch deletion. |
| **scholium-bridge plugin** | Zotero 7 to 9 | Fallback. Data-only endpoints on Zotero's local server, protected by a token. |
| Tools → Developer → Run JavaScript | any version | Last resort; requires the user to paste and execute a generated script. |
| Direct SQLite writes | only while Zotero is closed | Not implemented. Zotero holds an exclusive lock on the database while running, and hand-written rows are error-prone. |
| Zotero **web** API | any version; requires a zotero.org account and synchronisation | Used by some MCP servers. Every write passes through the cloud and is not available offline. |
| MCP endpoints of other plugins | when installed | Authenticated for their own runtime; not a public interface. |

## Zotero annotation JSON (verified on Zotero 10.0.1)

```json
{
  "itemType": "annotation",
  "parentItem": "<attachment key>",
  "annotationType": "highlight" | "underline" | "text" | "note" | "image" | "ink",
  "annotationText": "…",            // highlight and underline only
  "annotationComment": "…",         // for "text", the displayed text
  "annotationColor": "#ffd400",
  "annotationPageLabel": "3",
  "annotationSortIndex": "00002|000000|00120",
  "annotationPosition": "{\"pageIndex\":2,\"rects\":[[x0,y0,x1,y1]],\"fontSize\":8,\"rotation\":0}",
  "tags": [{"tag": "zotero-scholium"}]
}
```

- Coordinates are expressed in PDF user space (origin at the bottom left, y axis upward). PyMuPDF uses
  a top-left origin; the conversion is `y_pdf = page.height - y_fitz`.
- `annotationSortIndex` has the form `page(5)|charOffset(6)|topFromPageTop(5)` and affects only the
  ordering of the sidebar.
- `text` annotations wrap to the width of their rectangle. Hard line breaks must not be inserted into
  the comment; they interfere with editing in the reader.

## Ownership and repeated runs

Every annotation and note created by the tool carries the tag `zotero-scholium`. Earlier versions
used the tags `zotero-marginalia` and `zotero-paper-annotate`; all three are recognised. On a repeated run the tool deletes only
annotations that carry one of these tags, that have the configured author name, or whose text or
comment is identical to something about to be created. Existing child notes are never deleted; if a
note with the same title prefix exists, the new note receives a versioned title
(`… (v2, 2026-08-26)`).

## Margin layout

The edges of the text body are estimated from the words on the page (2nd and 98th percentiles of the
word x-coordinates, excluding the header and footer) and widened to the document-level extents (10th
and 90th percentiles of the per-page estimates over a sample of pages), so that a page with few
full-width lines, such as a first page with an indented abstract or a figure beside the text, does not
place its margin boxes inside the text column. Two-column pages are detected by counting the
words that cross the page centre. A summary is placed beside the first line of its anchor phrase: on
the paragraph's own side in two-column layouts, otherwise in the wider margin. Boxes on the same side
are shifted downward to avoid overlap and moved upward if they would extend into the footer; a box is
first clamped between the footer line (28 pt) and the header line (page height minus 20 pt).

Before layout the tool reads the attachment's existing annotations (through whichever backend is
available) and treats the rectangles of text, note, image and ink annotations that are not its own as
occupied intervals of the margin they intrude into (with `cleanup: false` the tool's own earlier
annotations remain in Zotero and are treated the same way). Images and vector drawings of the page,
obtained from PyMuPDF (`get_image_info`, `cluster_drawings`) and filtered to exclude thin rules and
page-sized frames, are added as obstacles. New boxes are placed below such an interval, or above it
when the footer leaves no room; a box for which neither direction has space keeps its requested
position and is reported in `layout_warnings`. `--ignore-existing` skips reading the existing
annotations; figures are always considered.

A summary may also be placed as a band across the text column at the top or bottom of a page (`place`),
at an explicit rectangle (`rect`), on a forced side (`side`), or as a sticky note (`kind`). Bands treat
the page's text lines as obstacles in addition to figures and existing annotations, so a band at the
top of page 1 settles into the gap between a header line and the title; a top band stays within the top
30 % of the page and a bottom band within the bottom 30 % (between the text and the footer, or beneath the footer when that gap is too small), and a band that does not fit is reported
rather than moved to the other end. Boxes are laid out in the order explicit rectangles, bands, margin
boxes, each joining the obstacle set of the next group. Colour and font size can be set per summary;
the defaults remain `text_color` and `font_size`.
