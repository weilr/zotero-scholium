# -*- coding: utf-8 -*-
"""
zotero-scholium: write reading results, produced by a person or by a language model, back into
Zotero as native annotations.

For one PDF attachment the tool creates (the PDF file itself is never modified):
  * highlight annotations on selected sentences, each carrying a comment (for example a translation),
    in configurable colours; the default scheme distinguishes "core" from "other"
  * text annotations placed in the page margins beside the paragraphs they refer to
    (short summaries; wrapped automatically and editable in Zotero)
  * optionally a child note (HTML) under the parent item

Backends (--backend auto takes the plugin from 0.1.9, else the local API on Zotero 10, else an older plugin):
  bridge  the bundled scholium-bridge plugin (Zotero 7 and later): a run's annotations in one transaction
  api     official local API of Zotero 10 and later (no plugin; one confirmation dialog on first use)
  js      a "Run JavaScript" file for manual execution in Zotero (last resort)

Requires: pip install pymupdf
Usage:    scholium --config config.json [--apply] [--list] [--backend auto|api|bridge|js]
          scholium status ITEM_KEY | --query WORDS
          scholium extract --pdf paper.pdf [--sentences sentences.json] [--out sentences.txt]
          scholium samples [KEY ...] [--query WORDS]
          scholium profile [--from-library | --path]
"""
import argparse
import difflib, glob, hashlib, json, os, sys, re, time, datetime, collections, unicodedata
import html as htmllib
import urllib.request, urllib.error, urllib.parse
from decimal import Decimal
try:
    import pymupdf
except ImportError:   # PyMuPDF before 1.24 is imported as fitz
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

PYMUPDF_MISSING = "PyMuPDF is not installed; run: pip install -U pymupdf"

__version__ = "0.1.9"

TAG = "zotero-scholium"     # tag applied to every annotation and note created by this tool
LEGACY_TAGS = {"zotero-marginalia", "zotero-paper-annotate"}   # tags written by earlier versions; still recognised as belonging to this tool
OWN_TAGS = {TAG} | LEGACY_TAGS
APP_NAME = "zotero-scholium"
BASE = "http://127.0.0.1:23119"
NOT_IN_MY_LIBRARY = "the item was not found in My Library; items in group libraries are not supported"

DEFAULTS = {
    "levels": {},               # named colour levels, e.g. {"claim": "#ff6666", "method": "#ffd400"}; referenced by "level" in highlights
    "core_color": "#ff6666",    # legacy two-level scheme: highlights carrying "core": true/false
    "other_color": "#ffd400",
    "text_color": "#1a73e8",
    "font_size": 8,
    "margin_side": "auto",      # margin used for summaries: "auto" (paragraph's side / wider margin), "left", "right"
    "summary_kind": "text",     # "text": visible margin text; "note": sticky notes (only when the user has that habit)
    "preview_pages": [],        # pages rendered as preview PNGs
    "note_title": None,
    "note_title_prefix": None,
    "note_html": None,
    "note_replace": False,      # True: after the new note is written, the tool's earlier notes under the item (restricted to
                                # titles starting with note_title_prefix when one is given) go to the trash; untagged notes stay.
                                # By default existing notes are preserved and a new note receives a versioned title.
    "cleanup": False,           # True: a complete redo; the tool's earlier annotations on the attachment are deleted once the new
                                # ones are written. False: keep every existing annotation (the tool's own included); only add
    "cleanup_external": False,  # bridge backend only: additionally delete annotations Zotero imported from the PDF file
    "band_min_font_size": 8,    # a top or bottom band without room at its font size is set smaller, down to this size;
                                # without room even then it becomes a sticky note
    "core_range": None,         # [low, high]: expected number of highlights in core_color; outside it an advisory style warning
    "banned_phrases": [],       # strings that must not occur in comments, margin texts or the note (reported as style warnings)
    "sentences": None,          # sentences.json written by `extract --sentences` (default: <out_dir>/sentences.json)
}

# ---------------------------------------------------------------------------
# Text matching and layout (the PDF is only read)
# ---------------------------------------------------------------------------
LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "’": "'", "‘": "'", "“": '"', "”": '"'}
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")     # the reader accepts <b> <i> <sub> <sup> in comments
MATH_RE = re.compile(r"\$\$[^$]*\$\$|\$[^$\n]+\$|\\\([^()]*\\\)|\\[a-zA-Z]+")
# text annotations on the page show tags literally: <sub>/<sup> become Unicode scripts where every character has one
SUB_CHARS = dict(zip("0123456789+-−=()aehijklmnoprstuvxβγρφχ", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓᵦᵧᵨᵩᵪ"))
SUP_CHARS = dict(zip("0123456789+-−=()abcdefghijklmnoprstuvwxyzβγδθφχ", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᵝᵞᵟᶿᵠᵡ"))
SCRIPT_RE = re.compile(r"<(sub|sup)\b[^<>]*>(.*?)</\1\s*>", re.S | re.I)
FORMAT_TAG_RE = re.compile(r"</?(?:b|i|u|em|strong|span|br)\b[^<>]*>", re.I)   # not "p<q and q>r"
SCRIPT_TAG_RE = re.compile(r"</?su[bp]\b[^<>]*>", re.I)


def page_text(s):
    """Margin text as the page shows it: <sub>/<sup> in Unicode (d<sub>k</sub> -> dₖ, x<sup>2</sup> -> x²), or
    with _ and ^ when a character has no script form (π<sub>ref</sub> -> π_ref); primes and stars stay as they are;
    other formatting tags are dropped. A <sub> or <sup> without its closing tag stays, and check_style reports it."""
    def script(m):
        kind = m.group(1).lower()
        table, mark = (SUB_CHARS, "_") if kind == "sub" else (SUP_CHARS, "^")
        inner = FORMAT_TAG_RE.sub("", m.group(2))
        if inner and all(c in table for c in inner):
            return "".join(table[c] for c in inner)
        if kind == "sup" and inner and all(c in "*∗′'" for c in inner):
            return inner
        return mark + inner if len(inner) <= 1 or inner.isalnum() else f"{mark}({inner})"
    return FORMAT_TAG_RE.sub("", SCRIPT_RE.sub(script, s))


SPAN_SEP = re.compile(r"\s*(?:…|\.\.\.)\s*")  # separates the start and end anchors of a highlight span


def norm_str(s):
    """Normalise for matching: lower-case, expand ligatures, drop whitespace and hyphen/dash characters."""
    out = []
    for c in s.lower():
        for cc in LIG.get(c, c):
            if cc.isspace() or cc in "-–—­":
                continue
            out.append(cc)
    return "".join(out)


def text_lines(page):
    """The page's text blocks and lines as PyMuPDF's "dict" gives them, without the pixel data of its images
    (decoding every image took seconds on a page of figures; only the lines are read)."""
    flags = getattr(pymupdf, "TEXTFLAGS_DICT", None)
    if flags is None:
        return page.get_text("dict").get("blocks", [])
    return page.get_text("dict", flags=flags & ~pymupdf.TEXT_PRESERVE_IMAGES).get("blocks", [])


class PageIndex:
    """Word-level index of one page together with an approximate model of its column geometry."""

    def __init__(self, page, doc_bounds=None):
        self.page = page
        self._blocks = None
        self.W, self.H = page.rect.width, page.rect.height
        self.words = page.get_text("words")  # x0, y0, x1, y1, word, block, line, wordno
        text, wmap = [], []
        for i, w in enumerate(self.words):
            n = norm_str(w[4]); text.append(n); wmap.extend([i] * len(n))
        self.text, self.wmap = "".join(text), wmap
        body = [w for w in self.words if len(w[4]) > 1 and w[1] > 40 and w[3] < self.H - 30]  # header and footer excluded
        xs0 = sorted(w[0] for w in body) or [50.0]
        xs1 = sorted(w[2] for w in body) or [self.W - 50.0]
        self.body_x0 = xs0[len(xs0) // 50]            # robust minimum (2nd percentile)
        self.body_x1 = xs1[-max(1, len(xs1) // 50)]   # robust maximum (98th percentile)
        if doc_bounds:
            # a page with few full-width lines (indented abstract, figure beside the text) underestimates its own
            # column width; the document-level extents keep margin boxes out of the text column
            self.body_x0 = min(self.body_x0, doc_bounds[0])
            self.body_x1 = max(self.body_x1, doc_bounds[1])
        mid = self.W / 2
        crossing = sum(1 for w in body if w[0] < mid - 6 and w[2] > mid + 6)
        self.two_col = crossing < max(3, len(body) * 0.02)

    def match(self, phrase, occurrence=1):
        """Words of the `occurrence`-th appearance (1-based) of the phrase on the page."""
        key = norm_str(phrase)
        pos, start = -1, 0
        for _ in range(max(1, occurrence)):
            pos = self.text.find(key, start)
            if pos < 0:
                return None
            start = pos + max(1, len(key))
        idxs = sorted(set(self.wmap[pos:pos + len(key)]))
        return [self.words[i] for i in idxs]

    def count(self, phrase):
        """Occurrences of the normalised phrase on the page; more than one means the match is ambiguous."""
        key = norm_str(phrase)
        return self.text.count(key) if key else 0

    def match_range(self, start, end, max_span=1200, occurrence=None):
        """Words from an occurrence of `start` to the following occurrence of `end`, both inclusive.
        Returns (words, reason); on failure words is None and reason says why."""
        a, b = norm_str(start), norm_str(end)
        if len(a) < 8 or len(b) < 8:
            return None, "each side of the ellipsis needs a few words"
        spans, i = [], self.text.find(a)
        while i >= 0:
            j = self.text.find(b, i + len(a))
            if j >= 0 and j + len(b) - i <= max_span:
                spans.append((i, j + len(b)))
            i = self.text.find(a, i + 1)
        distinct = sorted(set(spans))
        if not distinct:
            return None, "start or end phrase not found on the page (or the span is longer than ~200 words)"
        if occurrence:
            if len(distinct) < occurrence:
                return None, f"occurrence {occurrence} requested but only {len(distinct)} span(s) found on the page"
            s0, s1 = distinct[occurrence - 1]
        elif len(distinct) > 1:
            return None, f'{len(distinct)} possible spans on the page; make the anchors more specific or set "occurrence"'
        else:
            s0, s1 = distinct[0]
        idxs = sorted(set(self.wmap[s0:s1]))
        return [self.words[i] for i in idxs], None

    def closest(self, phrase):
        """Best fuzzy window on this page for a phrase that did not match exactly: (words, similarity)."""
        key = norm_str(phrase)
        if not key or not self.text:
            return None, 0.0
        sm = difflib.SequenceMatcher(None, self.text, key, autojunk=False)
        m = sm.find_longest_match(0, len(self.text), 0, len(key))
        if not m.size:
            return None, 0.0
        start = max(0, m.a - m.b)
        ratio = difflib.SequenceMatcher(None, self.text[start:start + len(key)], key, autojunk=False).ratio()
        idxs = sorted(set(self.wmap[start:start + len(key)]))
        if not idxs:
            return None, 0.0
        return [self.words[i] for i in idxs], ratio

    @staticmethod
    def line_rects(ws):
        lines = {}
        for w in ws:
            k = (w[5], w[6]); r = pymupdf.Rect(w[0], w[1], w[2], w[3])
            lines[k] = lines[k] | r if k in lines else r
        return [lines[k] for k in sorted(lines)]

    def position_rects(self, ws):
        """Rectangles (PDF space, y upward) of the lines the words lie on, as a Zotero position has them."""
        return [[round(r.x0, 2), round(self.H - r.y1, 2), round(r.x1, 2), round(self.H - r.y0, 2)] for r in self.line_rects(ws)]

    def blocks(self):
        if self._blocks is None:
            self._blocks = text_lines(self.page)
        return self._blocks

    def text_line_rects(self):
        """Rectangles (PDF space, y upward) of the page's horizontal text lines. Lines written in another
        direction (vertical preprint stamps in the margin) are dropped."""
        rects = []
        for block in self.blocks():
            for line in block.get("lines", []):
                dx, dy = line.get("dir", (1, 0))
                if abs(dx - 1) > 0.01 or abs(dy) > 0.01:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                if x1 - x0 <= 0 or y1 - y0 <= 0 or not "".join(s.get("text", "") for s in line.get("spans", [])).strip():
                    continue
                rects.append([x0, self.H - y1, x1, self.H - y0])
        return rects

    def margin_text_rects(self):
        """Rectangles (PDF space, y upward) of the text lines in any direction that lie in a margin beside the
        text column: a vertical preprint stamp, line numbers, marginal headings."""
        rects = []
        for block in self.blocks():
            for line in block.get("lines", []):
                x0, y0, x1, y1 = line["bbox"]
                if x1 - x0 <= 0 or y1 - y0 <= 0 or not "".join(s.get("text", "") for s in line.get("spans", [])).strip():
                    continue
                if x1 <= self.body_x0 + 1 or x0 >= self.body_x1 - 1:
                    rects.append([x0, self.H - y1, x1, self.H - y0])
        return rects

    def margin_box(self, para_rect, side="auto"):
        """(x0, x1) of the margin box beside a paragraph. `auto`: its own side in two-column layouts, otherwise the
        wider margin; `left` and `right` force the side."""
        left_w = self.body_x0 - 8
        right_w = self.W - self.body_x1 - 8
        if side == "left":
            use_left = True
        elif side == "right":
            use_left = False
        else:
            use_left = (para_rect.x0 < self.W / 2) if self.two_col else (left_w >= right_w)
        if use_left:
            return 4.0, max(4.0 + MIN_BOX_WIDTH, self.body_x0 - 4)
        return min(self.W - 4 - MIN_BOX_WIDTH, self.body_x1 + 4), self.W - 4


def column_bounds(doc, sample=60):
    """Document-level extents (x0, x1) of the text columns: the 10th/90th percentiles, over up to `sample`
    pages, of each page's own robust extents. None when no page has enough text."""
    xs0, xs1 = [], []
    n = len(doc)
    for i in range(0, n, max(1, n // sample)):
        page = doc[i]
        H = page.rect.height
        body = [w for w in page.get_text("words") if len(w[4]) > 1 and w[1] > 40 and w[3] < H - 30]
        if len(body) < 50:
            continue
        a = sorted(w[0] for w in body); b = sorted(w[2] for w in body)
        xs0.append(a[len(a) // 50]); xs1.append(b[-max(1, len(b) // 50)])
    if not xs0:
        return None
    xs0.sort(); xs1.sort()
    return xs0[len(xs0) // 10], xs1[max(0, len(xs1) - 1 - len(xs1) // 10)]


def page_figure_rects(page, min_size=8.0):
    """Rectangles (PDF user space, y upward) of the images and vector drawings on a page. Figures that reach into
    the margins must not be covered by margin notes. Tiny drawings (rules, underlines) and page-sized frames
    are ignored."""
    W, H = page.rect.width, page.rect.height
    rects = []
    try:
        rects.extend(pymupdf.Rect(info["bbox"]) for info in page.get_image_info())
    except Exception:
        pass
    try:
        rects.extend(page.cluster_drawings())
    except Exception:
        try:
            rects.extend(pymupdf.Rect(d["rect"]) for d in page.get_drawings())
        except Exception:
            pass
    out = []
    for r in rects:
        r = pymupdf.Rect(r) & page.rect
        if r.is_empty or r.width < min_size or r.height < min_size or (r.width > 0.95 * W and r.height > 0.95 * H):
            continue
        out.append([float(r.x0), float(H - r.y1), float(r.x1), float(H - r.y0)])
    return out


def user_space_shift(page):
    """(dx, dy) from the tool's page coordinates (x from the left edge of the visible page, y up from its bottom
    edge) to PDF user space, in which Zotero stores positions; not zero when the page's crop box or media box does
    not start at (0, 0). Rotated pages are not annotated and get (0, 0)."""
    if page.rotation % 360:
        return 0.0, 0.0
    m = page.transformation_matrix
    dx, dy = -m.e, m.f - page.rect.height
    return (round(dx, 2) if abs(dx) >= 0.01 else 0.0), (round(dy, 2) if abs(dy) >= 0.01 else 0.0)


def shift_rect(r, dx, dy):
    return [round(r[0] + dx, 2), round(r[1] + dy, 2), round(r[2] + dx, 2), round(r[3] + dy, 2)]


def cw(c):  # estimated glyph width in em
    o = ord(c)
    if o < 128:
        return 0.3 if c.isspace() else 0.55
    return 1.0


def wrap(text, width_pt, fs):
    lines, cur, w = [], "", 0.0
    for c in text:
        cwid = cw(c) * fs
        if w + cwid > width_pt and cur:
            lines.append(cur); cur, w = "", 0.0
        cur += c; w += cwid
    if cur:
        lines.append(cur)
    return lines


PLACES = ("margin", "top", "bottom")
SIDES = ("auto", "left", "right")
KINDS = ("text", "note")
BAND_MARGIN = 6.0        # distance between a top/bottom band and the page edge (pt)
NOTE_ICON = 22.0         # side of a sticky-note icon in the Zotero reader (pt)
MIN_BOX_WIDTH = 30.0     # narrowest usable text box (pt)
ROTATED_PAGE = "the page is rotated; annotations on rotated pages are not supported yet, so nothing is written there"
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalise_summary(item, cfg, page_sizes):
    """Resolve the defaults of one `summaries[]` entry and validate it.

    Returns a dict with page (0-based), text, place, side, kind, color, font_size, rect (top-left origin, or None)
    and anchor (or None). Raises ValueError with a reason suitable for the `missed` report.
    """
    if not isinstance(item, dict):
        raise ValueError("a summary must be an object")
    try:
        page = int(item["page"]) - 1
    except (KeyError, TypeError, ValueError):
        raise ValueError("a summary needs a 1-based page number")
    if page < 0 or page >= len(page_sizes):
        raise ValueError(f"page {page + 1} is outside the document ({len(page_sizes)} pages)")
    text = str(item.get("text") or "").strip()
    if not text:
        raise ValueError("a summary needs text")
    place = item.get("place", "margin")
    if place not in PLACES:
        raise ValueError(f"place must be one of {', '.join(PLACES)}")
    side = item.get("side", cfg.get("margin_side", "auto"))
    if side not in SIDES:
        raise ValueError(f"side must be one of {', '.join(SIDES)}")
    kind = item.get("kind", cfg.get("summary_kind", "text"))
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    color = str(item.get("color") or cfg.get("text_color") or DEFAULTS["text_color"])
    if not HEX_COLOR_RE.match(color):
        raise ValueError("color must be a #rrggbb value")
    try:
        font_size = float(item.get("font_size", cfg.get("font_size", DEFAULTS["font_size"])))
    except (TypeError, ValueError):
        raise ValueError("font_size must be a number")
    if not 4 <= font_size <= 36:
        raise ValueError("font_size must lie between 4 and 36")
    try:
        min_font_size = float(cfg.get("band_min_font_size", DEFAULTS["band_min_font_size"]))
    except (TypeError, ValueError):
        raise ValueError("band_min_font_size must be a number")
    if not 4 <= min_font_size <= 36:
        raise ValueError("band_min_font_size must lie between 4 and 36")
    rect = item.get("rect")
    if rect is not None:
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError("rect must be [x0, y0, x1, y1] in points from the top-left corner")
        try:
            rect = [float(v) for v in rect]
        except (TypeError, ValueError):
            raise ValueError("rect must contain four numbers")
        x0, y0, x1, y1 = rect
        W, H = page_sizes[page]
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H or x0 >= x1 or y0 >= y1:
            raise ValueError("rect lies outside the page or is empty")
        if x1 - x0 < MIN_BOX_WIDTH:
            raise ValueError(f"rect is narrower than {MIN_BOX_WIDTH:.0f} pt")
        if kind == "text" and y1 - y0 < font_size * 1.5 + 6:
            raise ValueError("rect is shorter than one line of text")
        if kind == "note" and (y0 + NOTE_ICON > H or x0 + NOTE_ICON > W):
            raise ValueError("rect leaves no room for the sticky-note icon")
    anchor = str(item.get("anchor") or "").strip() or None
    if rect is None and (place == "margin" or kind == "note") and not anchor:
        raise ValueError("anchor is required for margin placement and for sticky notes")
    if kind == "text":
        text = page_text(text)
    return {"page": page, "text": text, "place": place, "side": side, "kind": kind, "color": color,
            "font_size": font_size, "min_font_size": min_font_size, "rect": rect, "anchor": anchor,
            "occurrence": int(item.get("occurrence") or 0) or None}


OBSTACLE_TYPES = ("text", "note", "image", "ink")


def existing_obstacles(listing, keep_own=False):
    """Rectangles (PDF user space, keyed by page index) occupied by annotations that do not belong to this tool.

    Highlights and underlines lie inside the text columns and are ignored. Text boxes, sticky notes, image
    areas and ink paths may occupy the margins and must not be covered by new margin notes. Annotations
    carrying one of the tool's tags are skipped because a run replaces them, unless `keep_own` is set
    (cleanup disabled): then they stay in Zotero and must be avoided like any other annotation.
    """
    obstacles = {}
    for a in (listing or {}).get("annotations", []):
        if (not keep_own and set(a.get("tags") or []) & OWN_TAGS) or a.get("type") not in OBSTACLE_TYPES:
            continue
        pos = parse_position(a.get("position"))
        page = pos.get("pageIndex")
        rects = [r for r in (pos.get("rects") or []) if len(r) == 4]
        for path in pos.get("paths") or []:
            xs, ys = path[0::2], path[1::2]
            if xs and ys:
                rects.append([min(xs), min(ys), max(xs), max(ys)])
        if page is None or not rects:
            continue
        obstacles.setdefault(int(page), []).extend([[float(v) for v in r] for r in rects])
    return obstacles


def place_blocks(blocks, occupied, floor, ceiling, gap=3.0):
    """Assign a final y_top (PDF space, y upward) to every block so that no block overlaps another block, an
    occupied interval, the footer (below `floor`) or the header (above `ceiling`).

    Blocks are processed from the top of the page downward. A block that collides with something is moved
    below it; if that would push it into the footer it is moved upward instead. When neither direction has
    room the block keeps its requested position and is marked with `layout_warning`; so is a block taller than
    the room between `floor` and `ceiling`, which is placed at the ceiling.
    """
    occ = sorted(occupied)

    def hits(y_top, h):
        return [iv for iv in occ if y_top - h < iv[1] + gap and y_top > iv[0] - gap]

    for b in sorted(blocks, key=lambda b: -b["y_top"]):
        h = b["h"]
        if h > ceiling - floor:
            b["y_top"] = ceiling
            b["layout_warning"] = "the box is taller than the page leaves room for; shorten the text"
            occ.append((ceiling - h, ceiling))
            occ.sort()
            continue
        desired = min(max(b["y_top"], floor + h), ceiling)  # a paragraph near the page bottom must not push the box into the footer
        cand, ok = desired, False
        for _ in range(64):
            hit = hits(cand, h)
            if not hit:
                ok = cand - h >= floor
                break
            cand = min(iv[0] for iv in hit) - gap
            if cand - h < floor:
                break
        if not ok:
            cand = desired
            for _ in range(64):
                hit = hits(cand, h)
                if not hit:
                    ok = cand <= ceiling
                    break
                cand = max(iv[1] for iv in hit) + gap + h
                if cand > ceiling:
                    break
        if not ok:
            cand = desired
            b["layout_warning"] = ("no gap tall enough for this box anywhere in this margin of the page; set side to the other "
                                   "margin, anchor it on another page, or drop it")
        b["y_top"] = cand
        occ.append((cand - h, cand))
        occ.sort()
    return blocks


def _box_height(sp, width):
    if sp["kind"] == "note":
        return NOTE_ICON
    text = TAG_RE.sub("", sp["text"])   # <sub>/<sup> tags take no width in the reader
    return len(wrap(text, width - 3, sp["font_size"])) * sp["font_size"] * 1.5 + 6


def _intersects(rect, rects):
    return any(rect[0] < o[2] and rect[2] > o[0] and rect[1] < o[3] and rect[3] > o[1] for o in rects)


def _summary_annotation(pi, sp, rect, warning=None):
    p = pi.page.number
    top = int(round(pi.H - rect[3]))
    ann = {"type": sp["kind"], "color": sp["color"], "comment": sp["text"], "pageLabel": str(p + 1),
           "sortIndex": f"{p:05d}|{0:06d}|{top:05d}",
           "position": {"pageIndex": p, "rects": [[round(v, 2) for v in rect]]}}
    if sp["kind"] == "text":
        ann["position"]["fontSize"] = sp["font_size"]
        ann["position"]["rotation"] = 0
    if warning:
        ann["layout_warning"] = warning
    if sp.get("occurrences"):
        ann["occurrences"] = sp["occurrences"]
    if sp.get("fitted_from"):
        ann["fitted"] = {"from": sp["fitted_from"], "to": sp["font_size"]}
    if sp.get("as_note"):
        ann["as_note"] = True
    return ann


EDGE_MARGIN = 2.0      # distance between a band in the strip above the first line and the page edge (pt)


def top_strip(pi, occupied, text_lines, x0, x1):
    """The widest free piece of the strip between the page edge and the first text line within x0..x1, beside a logo
    or another figure there: (x0, x1, y_top, y_bottom) in PDF space, or None when nothing useful is free."""
    tops = [r[3] for r in text_lines if r[0] < x1 and r[2] > x0]
    y_top, y_bottom = pi.H - EDGE_MARGIN, (max(tops) if tops else 0.7 * pi.H) + 2.0
    if y_top - y_bottom < 10:
        return None
    blocked = sorted((max(r[0], x0), min(r[2], x1)) for r in occupied
                     if r[1] < y_top and r[3] > y_bottom and r[0] < x1 and r[2] > x0)
    free, at = [], x0
    for a, b in blocked:
        if a - 3 > at:
            free.append((at, a - 3))
        at = max(at, b + 3)
    if x1 > at:
        free.append((at, x1))
    best = max(free, key=lambda f: f[1] - f[0], default=None)
    return (best[0], best[1], y_top, y_bottom) if best and best[1] - best[0] >= 60 else None


def smaller_sizes(sp):
    """Font sizes below the band's own, in steps of 0.5 pt, down to its min_font_size."""
    floor = sp.get("min_font_size", DEFAULTS["band_min_font_size"])
    sizes, f = [], sp["font_size"] - 0.5
    while f > floor:
        sizes.append(f)
        f -= 0.5
    return sizes + ([floor] if floor < sp["font_size"] else [])


def layout_page_summaries(pi, specs, page_obstacles, missed):
    """Lay out one page's summaries and return their annotations.

    Order: explicit rectangles (never moved; an overlap is only reported), then top/bottom bands across the text
    column, then margin boxes and sticky notes beside their anchors. Every placed box joins the obstacle set of the
    following groups. Bands avoid the page's text lines; a band without room even at its smallest font size becomes
    a sticky note beside the column's first text line (top) or its last above the footer (bottom). Margin boxes lie
    outside the text column by construction and avoid the text in the margins; one without room takes the other margin
    of a one-column page, or else becomes a sticky note beside its paragraph.
    """
    p = pi.page.number
    anns, occupied = [], list(page_obstacles)
    text_lines = pi.text_line_rects()
    # 1. explicit rectangles (top-left origin in the configuration, PDF space here)
    for sp in [s for s in specs if s["rect"]]:
        x0, y0, x1, y1 = sp["rect"]
        rect = [x0, pi.H - y1, x1, pi.H - y0]
        if sp["kind"] == "note":
            rect = [x0, pi.H - y0 - NOTE_ICON, x0 + NOTE_ICON, pi.H - y0]
        warn = "explicit rectangle overlaps a text line, figure or annotation" if _intersects(rect, occupied + text_lines) else None
        anns.append(_summary_annotation(pi, sp, rect, warn)); occupied.append(rect)
    # 2. bands across the text column
    bx0, bx1 = pi.body_x0, pi.body_x1
    band_notes = []
    for sp in [s for s in specs if not s["rect"] and s["kind"] == "text" and s["place"] in ("top", "bottom")]:
        occ = [(r[1], r[3]) for r in occupied + text_lines if r[0] < bx1 and r[2] > bx0]
        # the footer (page number, running line) is any text line inside the column within 8 % of the page bottom;
        # a bottom band goes between the text and the footer, or, when that gap is too small, beneath the footer
        footer = [r for r in text_lines if r[0] < bx1 and r[2] > bx0 and r[3] < 0.08 * pi.H]
        footer_top = max((r[3] for r in footer), default=0.0)

        def place(h, top=sp["place"] == "top"):
            if top:
                blk = {"y_top": pi.H - BAND_MARGIN, "h": h}
                place_blocks([blk], occ, floor=0.7 * pi.H, ceiling=pi.H - BAND_MARGIN)
                return blk
            blk = {"y_top": max(BAND_MARGIN, footer_top + 3.0) + h, "h": h}
            place_blocks([blk], occ + ([(0.0, footer_top)] if footer else []), floor=BAND_MARGIN, ceiling=0.3 * pi.H)
            if blk.get("layout_warning") and footer:
                below = {"y_top": BAND_MARGIN + h, "h": h}
                place_blocks([below], occ, floor=BAND_MARGIN, ceiling=min(r[1] for r in footer) - 3.0)
                if not below.get("layout_warning"):
                    blk = below
            return blk

        # a top band without room across the column goes into the strip above the first line, beside a logo there
        strip = top_strip(pi, occupied, text_lines, bx0, bx1) if sp["place"] == "top" else None

        def in_strip(v):
            return bool(strip) and _box_height(v, strip[1] - strip[0]) <= strip[2] - strip[3]

        def fits(v):
            return in_strip(v) or not place(_box_height(v, bx1 - bx0)).get("layout_warning")

        if not fits(sp):   # without room at its own font size the band is set smaller, down to min_font_size
            smaller = next((f for f in smaller_sizes(sp) if fits(dict(sp, font_size=f))), None)
            if smaller is None:   # no room even then: a sticky note beside the column's first line, or its last above the footer
                top = sp["place"] == "top"
                lines = [r for r in text_lines if r[0] < bx1 and r[2] > bx0 and r not in footer]
                edge = [bx0, pi.H if top else 0.0, bx1, pi.H if top else 0.0]   # a column without text: the page edge
                ln = (max(lines, key=lambda r: r[3]) if top else min(lines, key=lambda r: r[1])) if lines else edge
                band_notes.append(dict(sp, kind="note", as_note=True,
                                       line=pymupdf.Rect(ln[0], pi.H - ln[3], ln[2], pi.H - ln[1])))
                continue
            sp = dict(sp, font_size=smaller, fitted_from=sp["font_size"])
        h = _box_height(sp, bx1 - bx0)
        blk = place(h)
        rect = [bx0, blk["y_top"] - h, bx1, blk["y_top"]]
        if blk.get("layout_warning"):   # no room across the column, but in the strip above the first line
            hs = _box_height(sp, strip[1] - strip[0])
            rect = [strip[0], strip[2] - hs, strip[1], strip[2]]
        anns.append(_summary_annotation(pi, sp, rect)); occupied.append(rect)
    # 3. margin boxes and sticky notes beside their anchors (a sticky note ignores `place`), and the bands turned
    # into sticky notes beside their lines; text in the margins is occupied space, and in a one-column layout a box
    # takes the other margin when its own has text beside it. A margin box without room takes the other margin of a
    # one-column page (side auto), and without room there either becomes a sticky note beside its paragraph.
    margin_text = pi.margin_text_rects()
    entries = []                                      # (summary, the first line of its anchor)
    for sp in [s for s in specs if not s["rect"] and (s["kind"] == "note" or s["place"] == "margin")] + band_notes:
        r = sp.get("line")
        if r is None:
            occ = sp.get("occurrence")
            ws = pi.match(sp["anchor"], occ or 1)
            if not ws:
                entry = {"kind": "summary", "page": p + 1, "anchor": sp["anchor"]}
                if occ:
                    n = pi.count(sp["anchor"])
                    if n:
                        entry["reason"] = f"occurrence {occ} requested but the anchor occurs {n} time(s) on the page"
                missed.append(entry); continue
            n = pi.count(" ".join(w[4] for w in ws))
            if n > 1 and not occ:                     # the box sits beside the first occurrence
                sp["occurrences"] = n
            r = pi.line_rects(ws)[0]
        entries.append((sp, r))

    def lay(ways):
        """Each entry laid out as `ways` says ("own" margin, the "other" one, or a "note"): [(entry index, summary,
        rect, warning)] in the order they are placed. Only a box of side auto on a one-column page has another margin."""
        groups = {}
        for i, ((sp, r), way) in enumerate(zip(entries, ways)):
            if way == "note":
                sp = dict(sp, kind="note", as_note=True)
            mx0, mx1 = pi.margin_box(r, sp["side"])
            y_top = pi.H - r.y0 + 1
            if sp["side"] == "auto" and not pi.two_col and sp["kind"] != "note":
                ox0, ox1 = pi.margin_box(r, "right" if mx1 <= pi.body_x0 else "left")
                if (_intersects([mx0, y_top - _box_height(sp, mx1 - mx0), mx1, y_top], margin_text)
                        and not _intersects([ox0, y_top - _box_height(sp, ox1 - ox0), ox1, y_top], margin_text)):
                    mx0, mx1, ox0, ox1 = ox0, ox1, mx0, mx1
                if way == "other":
                    mx0, mx1 = ox0, ox1
            if sp["kind"] == "note":  # the icon hugs the text column
                mx0, mx1 = (mx1 - NOTE_ICON, mx1) if mx1 <= pi.body_x0 else (mx0, mx0 + NOTE_ICON)
            groups.setdefault((mx0, mx1), []).append(({"y_top": y_top, "h": _box_height(sp, mx1 - mx0)}, sp, i))
        placed, taken = [], list(occupied)
        for (mx0, mx1), items in groups.items():
            occ = [(r[1], r[3]) for r in taken + margin_text if r[0] < mx1 and r[2] > mx0]
            place_blocks([b for b, _, _ in items], occ, floor=28.0, ceiling=pi.H - 20.0)
            # a margin narrower than the narrowest box: the box reaches into the text column
            narrow = mx0 < pi.body_x1 - 1 and mx1 > pi.body_x0 + 1
            for b, sp, i in items:
                rect = [mx0, b["y_top"] - b["h"], mx1, b["y_top"]]
                warn = b.get("layout_warning") or (f"the margin beside this paragraph is narrower than {MIN_BOX_WIDTH:.0f} pt and the "
                                                   "box covers the text; use place: top or bottom, or drop the note" if narrow else None)
                placed.append((i, sp, rect, warn)); taken.append(rect)
        return placed

    # the highest margin box without room goes elsewhere, one at a time, until every box has room or is a sticky note
    ways = ["own"] * len(entries)
    while True:
        placed = lay(ways)
        stuck = [(rect[3], i) for i, sp, rect, warn in placed if warn and sp["kind"] == "text"]
        if not stuck:
            break
        i = max(stuck)[1]
        ways[i] = "other" if ways[i] == "own" else "note"
    for _, sp, rect, warn in placed:
        anns.append(_summary_annotation(pi, sp, rect, warn)); occupied.append(rect)
    return anns


def build(cfg, obstacles=None):
    """Convert the configuration into annotation objects with PDF-space coordinates and render preview PNGs.

    `obstacles` maps a page index to rectangles already occupied by other annotations (see
    existing_obstacles); margin boxes are laid out around them and around the page's figures.
    """
    doc = pymupdf.open(cfg["pdf"])
    # the column extents only matter for margin notes; without them only the highlighted pages are read
    bounds = column_bounds(doc) if cfg.get("summaries") else None
    idx = {}
    def page_index(p):
        if p not in idx:
            idx[p] = PageIndex(doc[p], bounds)
        return idx[p]

    fs = float(cfg["font_size"])
    out, missed = [], []
    sentences = None

    def resolve(item, kind):
        """Fill page, text/anchor and occurrence of an entry that names sentence ids; None (and a missed entry) on failure."""
        nonlocal sentences
        if "id" not in item and "ids" not in item:
            return item
        try:
            if sentences is None:
                sentences = _load_sentences(cfg)
            ids = [int(item["id"])] if "id" in item else list(range(int(item["ids"][0]), int(item["ids"][1]) + 1))
            recs = [sentences[i] for i in ids if i in sentences]
            if len(recs) != len(ids) or not ids:
                raise KeyError("unknown sentence id " + ", ".join(str(i) for i in ids if i not in sentences))
            if len({r["page"] for r in recs}) > 1:
                raise KeyError("ids span more than one page")
            text = " ".join(r["text"] for r in recs)
            matches = page_index(recs[0]["page"] - 1).count(text)
            if not matches:
                raise ValueError(_unmatched_ids(page_index(recs[0]["page"] - 1), ids, recs))
            if not item.get("occurrence") and matches > 1 and (len(recs) != 1 or matches != recs[0]["same_text_count"]):
                raise ValueError(f"ambiguous sentence id: {matches} passages match; set occurrence explicitly after checking the page")
            if len(recs) > 1:   # the matched span must start and end where the first and the last sentence stand
                pg = page_index(recs[0]["page"] - 1)

                def own(rec):
                    return pg.match(rec["text"], rec["occurrence"]) if pg.count(rec["text"]) == rec["same_text_count"] else None
                start, end = own(recs[0]), own(recs[-1])
                at = pg.match(text, int(item.get("occurrence") or 1))
                if not start or not end or not at or start[0] != at[0] or end[-1] != at[-1]:
                    raise ValueError(f"sentences {ids[0]}–{ids[-1]} do not run from sentence {ids[0]} to sentence {ids[-1]} at their own "
                                     "places on the page (text between them was left out of the extraction, or the text repeats); "
                                     "highlight them one by one or use page and text")
        except (KeyError, ValueError, TypeError, FileNotFoundError) as e:
            missed.append({"kind": kind, "id": item.get("id", item.get("ids")), "reason": str(e).strip("'")})
            return None
        fields = {"page": recs[0]["page"], "text" if kind == "highlight" else "anchor": text}
        if len(recs) == 1 and not item.get("occurrence"):
            fields["occurrence"] = recs[0]["occurrence"]
        return dict(item, **fields)

    for h in cfg.get("highlights", []):
        h = resolve(h, "highlight")
        if h is None:
            continue
        p = int(h["page"]) - 1
        if not 0 <= p < len(doc):
            missed.append({"kind": "highlight", "page": p + 1, "text": str(h.get("text", ""))[:60],
                           "reason": f"page {p + 1} is outside the document ({len(doc)} pages)"})
            continue
        if doc[p].rotation % 360:
            missed.append({"kind": "highlight", "page": p + 1, "text": h["text"][:60], "reason": ROTATED_PAGE})
            continue
        pi = page_index(p)
        occ = int(h.get("occurrence") or 0) or None   # 1-based; None: the first occurrence, ambiguity is reported
        ws, reason, snapped = pi.match(h["text"], occ or 1), None, None
        if not ws:
            parts = [s for s in SPAN_SEP.split(h["text"]) if s]
            if len(parts) == 2:                      # "first words … last words" selects the span between the anchors
                ws, reason = pi.match_range(parts[0], parts[1], occurrence=occ)
            elif len(parts) > 2:
                reason = "more than one ellipsis in the phrase"
            if not ws and not reason and occ:
                n = pi.count(h["text"])
                if n:
                    reason = f"occurrence {occ} requested but the phrase occurs {n} time(s) on the page"
        if not ws:
            entry = {"kind": "highlight", "page": p + 1, "text": h["text"][:60]}
            if reason:
                entry["reason"] = reason
            best_ws, best_r, best_p = None, 0.0, p
            for q in (p, p - 1, p + 1):
                if 0 <= q < len(doc):
                    cand, r2 = page_index(q).closest(h["text"])
                    if cand and r2 > best_r:
                        best_ws, best_r, best_p = cand, r2, q
            if best_ws:
                entry["similarity"] = round(best_r, 2)
                entry["closest"] = " ".join(w[4] for w in best_ws)[:300]
                if best_p != p:
                    entry["hint"] = f"the closest passage is on page {best_p + 1}"
                elif cfg.get("snap") and not occ and best_r >= 0.95:
                    ws, snapped = best_ws, round(best_r, 2)
            if not ws:
                missed.append(entry); continue
        rects = pi.position_rects(ws)
        top = int(round(pi.H - rects[0][3]))
        # colour precedence: explicit "color", then named "level" (resolved through cfg["levels"]), then legacy core/other
        color = h.get("color") or cfg.get("levels", {}).get(h.get("level", ""), None) or \
                (cfg["core_color"] if h.get("core") else cfg["other_color"])
        ann = {"type": h.get("type", "highlight") if h.get("type") in ("highlight", "underline") else "highlight",
               "color": color, "text": " ".join(w[4] for w in ws), "comment": h.get("comment", ""), "pageLabel": str(p + 1),
               "sortIndex": f"{p:05d}|{0:06d}|{top:05d}", "position": {"pageIndex": p, "rects": rects}}
        if snapped:
            ann["snapped"] = snapped
        n = pi.count(ann["text"])
        if n > 1 and not occ:                     # the first occurrence was highlighted without being asked for
            ann["occurrences"] = n
        out.append(ann)
    page_sizes = [(pg.rect.width, pg.rect.height) for pg in doc] if cfg.get("summaries") else []
    specs = []
    for s in cfg.get("summaries", []):
        s = resolve(s, "summary") if isinstance(s, dict) else s
        if s is None:
            continue
        try:
            specs.append(normalise_summary(s, cfg, page_sizes))
        except ValueError as e:
            item = s if isinstance(s, dict) else {}
            missed.append({"kind": "summary", "page": item.get("page"), "anchor": item.get("anchor"), "reason": str(e)})
    by_page = {}
    for sp in specs:
        by_page.setdefault(sp["page"], []).append(sp)
    for p, page_specs in by_page.items():
        if doc[p].rotation % 360:
            missed.extend({"kind": "summary", "page": p + 1, "anchor": sp["anchor"], "reason": ROTATED_PAGE} for sp in page_specs)
            continue
        pi = page_index(p)
        # existing annotations (in PDF user space) and figures are occupied space for every summary on the page
        dx, dy = user_space_shift(doc[p])
        page_obstacles = [shift_rect(r, -dx, -dy) for r in (obstacles or {}).get(p, [])] + page_figure_rects(doc[p])
        out.extend(layout_page_summaries(pi, page_specs, page_obstacles, missed))
    for a in out:   # soft hyphens and zero-width spaces copied from the PDF into a comment are left out
        if a.get("comment"):
            a["comment"] = INVISIBLE_RE.sub("", a["comment"])
    os.makedirs(cfg["out_dir"], exist_ok=True)
    for pg in cfg["preview_pages"]:
        p = int(pg) - 1
        if p < 0 or p >= len(doc):
            continue
        page = doc[p]; H = page.rect.height
        shape = page.new_shape()
        for a in out:
            if a["position"]["pageIndex"] != p:
                continue
            rgb = tuple(int(a["color"][i:i + 2], 16) / 255 for i in (1, 3, 5))
            if a["type"] == "highlight":
                for x0, y0, x1, y1 in a["position"]["rects"]:
                    shape.draw_rect(pymupdf.Rect(x0, H - y1, x1, H - y0))
                shape.finish(color=None, fill=rgb, fill_opacity=0.45)
            elif a["type"] == "underline":
                for x0, y0, x1, y1 in a["position"]["rects"]:
                    shape.draw_line(pymupdf.Point(x0, H - y0 + 1), pymupdf.Point(x1, H - y0 + 1))
                shape.finish(color=rgb, width=1.2)
            elif a["type"] == "note":
                x0, y0, x1, y1 = a["position"]["rects"][0]
                shape.draw_rect(pymupdf.Rect(x0, H - y1, x1, H - y0)); shape.finish(color=rgb, fill=rgb, fill_opacity=0.6)
            else:
                x0, y0, x1, y1 = a["position"]["rects"][0]
                afs = float(a["position"].get("fontSize", fs)); aline_h = afs * 1.5
                fr = pymupdf.Rect(x0, H - y1, x1, H - y0)
                shape.draw_rect(fr); shape.finish(color=(0.8, 0.8, 0.9), width=0.3)
                for i, ln in enumerate(wrap(a["comment"], (x1 - x0) - 3, afs)):
                    shape.insert_text(pymupdf.Point(fr.x0 + 1.5, fr.y0 + (i + 1) * aline_h), ln,
                                      fontsize=afs, fontname="china-s", color=rgb)
        shape.commit()
        page.get_pixmap(dpi=90).save(os.path.join(cfg["out_dir"], f"preview_p{p + 1}.png"))
    shifts = {}
    for a in out:   # Zotero stores positions in PDF user space
        p = a["position"]["pageIndex"]
        if p not in shifts:
            shifts[p] = user_space_shift(doc[p])
        dx, dy = shifts[p]
        if dx or dy:
            a["position"]["rects"] = [shift_rect(r, dx, dy) for r in a["position"]["rects"]]
    doc.close()  # the document is never saved; the PDF file remains unchanged
    return out, missed


CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
INVISIBLE_RE = re.compile("[\u00ad\u200b]")   # soft hyphen, zero-width space
NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<value>[+−-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    r"(?:[eE][+-]?\d+)?)"
    r"(?:\s*(?P<scale>[kK](?![A-Za-z])|百万|千万|十亿|百亿|千亿|[千万亿]|(?:thousand|million|billion|trillion)(?![A-Za-z])))?"
    r"(?:\s*(?P<percent>[%％]))?"
    r"(?:\s*-?\s*(?P<unit>[kmgt]i?b|[numμ]?s|[kmg]?hz|毫秒|微秒|纳秒|秒)(?![A-Za-z]))?"
    r"(?![A-Za-z0-9_]|\.\d|,\d)"
)


def _tokens(s, origin=None):
    """Latin words (3+ characters) and numbers, lower-cased; hyphenation across lines is joined first,
    and both the joined form and its two halves count as terms. `origin`, when given, receives each number's
    text as written (1.75E+11 -> "1750 亿")."""
    # compatibility forms: mathematical italic letters (𝑜𝑢𝑡) and superscript digits (10⁻⁶) become plain characters
    # (a full-width comma stays a separator: "2.1%，3" is not one number)
    s = unicodedata.normalize("NFKC", "".join(LIG.get(c, c) for c in s).replace("，", "， "))
    # PDF text carries soft hyphens and zero-width spaces ("MP-­1") and Unicode hyphens; the comment has plain ones
    s = re.sub("[‐‑‒]", "-", INVISIBLE_RE.sub("", s))
    s = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", s)                 # 20th -> 20
    s = re.sub(r"(\d)\s?[x×](?![A-Za-z0-9])", r"\1 ", s)            # 2-3x -> 2-3 (a factor, "2–3 倍")
    toks = set()
    for m in re.finditer(r"([A-Za-z]+)-\s+([A-Za-z]{2,})", s):
        toks.update(part.lower() for part in m.groups() if len(part) >= 3)
    s = re.sub(r"(\w)-\s+(\w)", r"\1\2", s).lower()
    # Keep version-bearing names intact even when their numeric parts are decimals.
    toks.update(t for t in re.findall(r"(?<![a-z0-9])[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)+", s)
                if any(c.isdigit() for c in t))
    def number_token(match):
        # Decimal tuple scaling is exact, including values beyond the default precision.
        number = Decimal(match["value"].replace(",", "").replace("−", "-"))
        sign, digits, exponent = number.as_tuple()
        exponent += {None: 0, "k": 3, "千": 3, "万": 4, "亿": 8, "百万": 6, "千万": 7, "十亿": 9, "百亿": 10, "千亿": 11, "thousand": 3, "million": 6, "billion": 9,
                     "trillion": 12}[match["scale"]]
        digits = list(digits)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        value = str(Decimal((sign, digits, exponent))) if digits else "0"
        # Keep units on their quantities; spaces must not hide a unit change.
        unit = {"毫秒": "ms", "微秒": "us", "纳秒": "ns", "秒": "s", "μs": "us"}.get(match["unit"], match["unit"])
        token = value + ("%" if match["percent"] else "") + (" " + unit if unit else "")
        toks.add(token)
        if origin is not None:
            origin.setdefault(token, match[0].strip())
        return " "
    s = NUMBER_RE.sub(number_token, s)
    for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s):
        if len(t) >= 3 or any(c.isdigit() for c in t):
            toks.add(t)
    return toks


def _stem(w):
    """A word without its plural ending: queries -> query, boxes -> box, kernels -> kernel."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "shes", "ches", "xes", "zes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _covered(tok, text_tokens, text_words=(), acronyms=()):
    """Numbers and digit-bearing names require exact matches; words allow inflections, and an abbreviation (one of
    `acronyms`) is covered by the words it abbreviates (FNO: Fourier neural operator)."""
    if any(c.isdigit() for c in tok):
        return tok in text_tokens
    if tok in text_tokens or tok + "s" in text_tokens or tok + "es" in text_tokens or tok.rstrip("s") in text_tokens:
        return True
    if any(_stem(tok) == _stem(u) for u in text_tokens):
        return True
    if any(len(tok) >= 4 and (u.startswith(tok) or tok.startswith(u)) and min(len(u), len(tok)) >= 4 for u in text_tokens):
        return True
    if tok not in acronyms:
        return False
    letters = tok[:-1] if tok.endswith("s") and len(tok) > 3 else tok
    return letters in "".join(w[0] for w in text_words).lower()


NUMBER_WORDS = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                        "seventeen eighteen nineteen twenty".split(), range(21)),
                    thirty=30, forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90)
NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)
FACTOR_RE = re.compile(r"\d\s?[x×](?![A-Za-z0-9])|\b(?:times|fold)\b", re.I)


def _text_variants(text):
    """The highlighted PDF text read another way: as extraction loses it (a space after a thousands separator
    "2, 448", "R-squared" for R², "Figure.2"), and as a translation may give it (numbers written as words,
    "unit variance" as 方差为 1, "11.60 thousand" as 11.60 with 千 elsewhere)."""
    alt = re.sub(r"(\d), (?=\d{3}(?!\d))", r"\1,", text)
    alt = re.sub(r"([A-Za-z0-9])[- ]?squared\b", r"\g<1>2", alt)
    alt = re.sub(r"([A-Za-z0-9])[- ]?cubed\b", r"\g<1>3", alt)
    alt = re.sub(r"([A-Za-z]{2,})\.(?=\d)", r"\1. ", alt)
    alt = NUMBER_WORD_RE.sub(lambda m: str(NUMBER_WORDS[m[1].lower()]), alt)
    alt = re.sub(r"(\d)\s*per\s?cent\b", r"\1%", alt, flags=re.I)
    alt = re.sub(r"\bunit(?=[- ](?:scale|variance|norm|length|vector|sphere|ball|cube|interval|circle|square|magnitude)s?\b)", "1", alt,
                 flags=re.I)
    return re.sub(r"(\d)\s*(?:thousand|million|billion|trillion)\b", r"\1", alt, flags=re.I)


def check_translations(annotations):
    """Heuristic fidelity check: a highlight comment must translate the highlighted span only.

    Two signals are reported as warnings (never as errors): numbers or Latin terms that occur in the
    comment but not in the highlighted text (content added from outside the span), and a CJK-characters-
    per-English-word ratio far outside the usual range (a comment much longer or shorter than the span
    it translates). The caller decides how to act on them.

    PDF text loses superscripts and subscripts (10⁻³ is extracted as 10−3, L² as L2, CM² as "CM 2"), so a
    comment's <sub>/<sup> is read both joined to its base and set apart, and the closer reading counts. Words the
    comment keeps in the original (names, citations, terms) need no translation and do not count towards the
    length a translation should have.
    """
    warnings = []
    for a in annotations:
        if a.get("type") not in ("highlight", "underline") or not a.get("comment"):
            continue
        text, comment = a["text"], a["comment"]
        base = MATH_RE.sub(" ", comment)    # mathematics is display, not content
        plain = TAG_RE.sub(" ", base)
        joined = TAG_RE.sub(" ", SCRIPT_TAG_RE.sub("", base))
        text_tokens = _tokens(text) | _tokens(_text_variants(text))
        text_words = re.findall(r"[A-Za-z]+", unicodedata.normalize("NFKC", text))
        acronyms = {m.lower() for m in re.findall(r"(?<![A-Za-z])[A-Z]{2,6}s?(?![A-Za-z])", plain)}
        readings = [joined, plain]
        if FACTOR_RE.search(text):   # "8x fewer samples": "1/8 的样本"
            readings += [re.sub(r"(?<![\d.])1\s*/\s*(?=\d)", "", p) for p in (joined, plain)]
        found = []
        for p in readings:   # each reported as the comment writes it
            origin = {}
            found.append(sorted({origin.get(t, t) for t in _tokens(p, origin) if not _covered(t, text_tokens, text_words, acronyms)}))
        extra = min(found, key=len)
        words = len(text_words)
        kept = {_stem(w.lower()) for p in (plain, joined) for w in re.findall(r"[A-Za-z]+", unicodedata.normalize("NFKC", p))}
        initials = "".join(w[0] for w in text_words).lower()
        abbreviated = set()   # the words an abbreviation in the comment stands for
        for ac in acronyms:
            letters = ac[:-1] if ac.endswith("s") and len(ac) > 3 else ac
            at = initials.find(letters)
            if at >= 0:
                abbreviated.update(range(at, at + len(letters)))
        translated = sum(1 for i, w in enumerate(text_words) if i not in abbreviated and _stem(w.lower()) not in kept)
        cjk = len(CJK_RE.findall(plain))
        reasons = []
        if extra:
            reasons.append("terms or numbers not present in the highlighted text: " + ", ".join(extra))
        if cjk and words >= 6 and cjk / words > 2.8:
            reasons.append(f"comment is long for the span ({cjk / words:.1f} characters per word); it may translate more than what is highlighted")
        elif cjk and translated >= 6 and cjk / translated < 0.8:
            reasons.append(f"comment is short for the span ({cjk / translated:.1f} characters per translated word); it may omit part of the sentence")
        if reasons:
            warnings.append({"page": a["pageLabel"], "text": text[:80], "comment": comment[:80], "reasons": reasons})
    return warnings


STYLE_SYMBOL_RE = re.compile(r"[→←↑↓⇒①-⑳【】]")            # arrows, circled numbers, bracket tags
LABEL_RE = re.compile(r"^[^：:，,。.]{1,12}(?:(?<!\d)(?<!\d\s)[：:]|[：:](?!\s?\d))\s*\S")   # "label: content" (not 3:1, 3：1, 3 : 1)
# a tag as markup writes it: <em>, </span>, <br/>, <span class="x">; not the comparisons in "x<y，则 f(x)>f(y)"
MARKUP_TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)(?:\s+[a-zA-Z][\w:-]*\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'<>]+))*\s*/?>")
MATH_FORMAT_RE = re.compile(r"\^|_\{|(?:\b10|\de)−\d")        # ^, _{ or a bare minus exponent instead of <sup>/<sub>
MATH_NODE_RE = re.compile(r'<(?:span|pre) class="math">(.*?)</(?:span|pre)>', re.S)
READER_TAGS = {"b", "i", "sub", "sup"}                        # the only tags the reader renders in comments


def _overlaps(rect, rects, tol=2.0):
    """True when `rect` shares more than `tol` points in both directions with one of `rects`."""
    return any(min(rect[2], o[2]) - max(rect[0], o[0]) > tol and min(rect[3], o[3]) - max(rect[1], o[1]) > tol for o in rects)


def _existing_rects(listing, keep_own=False):
    """(key, rects) of the annotations already in Zotero that a run leaves in place, keyed by page index."""
    rects = {}
    for a in (listing or {}).get("annotations", []):
        if not keep_own and set(a.get("tags") or []) & OWN_TAGS:
            continue
        pos = parse_position(a.get("position"))
        rs = [[float(v) for v in r] for r in (pos.get("rects") or []) if len(r) == 4]
        if pos.get("pageIndex") is None or not rs:
            continue
        rects.setdefault(int(pos["pageIndex"]), []).append((a.get("key"), rs))
    return rects


def _brief(s):
    """The first 80 characters with whitespace collapsed: what a listing keeps of a text or comment."""
    return " ".join((s or "").split())[:80].strip()


def _own_texts(listing):
    """{(page index, is a highlight or underline): [(text or comment as listed, key)]} of the tool's annotations."""
    out = {}
    for a in (listing or {}).get("annotations", []):
        if not set(a.get("tags") or []) & OWN_TAGS:
            continue
        page = parse_position(a.get("position")).get("pageIndex")
        mark = a.get("type") in ("highlight", "underline")
        body = _brief(a.get("text") if mark else a.get("comment"))
        if page is not None and body:
            out.setdefault((int(page), mark), []).append((body, a.get("key")))
    return out


def _changed_by_user(a):
    """Whether a listed annotation was changed after it was created: written by the tool, its two dates are equal, and
    opening the PDF in the reader leaves them so; a change in Zotero moves the later one."""
    def when(s):
        try:
            return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T")).replace(tzinfo=None)
        except ValueError:
            return None
    added, modified = when(a.get("added")), when(a.get("modified"))
    return bool(added and modified and (modified - added).total_seconds() > 5)


def _reproduces(new, old):
    """Whether a new annotation repeats a listed one: the same page, type and colour, the same text and comment."""
    same = lambda x, y: " ".join((x or "").split()) == " ".join((y or "").split())
    return (new["position"]["pageIndex"] == parse_position(old.get("position")).get("pageIndex") and new["type"] == old.get("type")
            and (new.get("color") or "").lower() == (old.get("color") or "").lower() and same(new.get("comment"), old.get("comment"))
            and (new["type"] not in ("highlight", "underline") or _listed_as(new.get("text"), _brief(old.get("text")))))


def _listed_as(text, listed):
    """Whether a listing's cut text is `text`: listings keep about 80 characters (the plugin counts UTF-16 units and
    may split a character at the cut), so a long listed text matches when the text begins with it."""
    full = " ".join((text or "").split())
    if full == listed:
        return True
    cut = max(len(listed), len(listed.encode("utf-16-le", "surrogatepass")) // 2) >= 76
    return cut and full.startswith(listed[:-1])


def _text_defects(s, page=False):
    """(kind, reason) pairs for display defects in a comment or margin text; `page`: text shown on the page, where
    page_text has already written scripts without a Unicode form with ^."""
    found = []
    if MATH_RE.search(s):
        found.append(("latex", "raw LaTeX; write mathematics with Unicode symbols and <sub>/<sup>"))
    if MATH_FORMAT_RE.search(s.replace("^", "") if page else s):
        found.append(("math_format", "exponent or subscript written with ^, _{ or a bare minus; use <sup>/<sub>"))
    tags = [m.group(1).lower() for m in MARKUP_TAG_RE.finditer(s)]
    bad = sorted(set(tags) - READER_TAGS)
    if bad:
        found.append(("tag", "tags the reader does not render: " + ", ".join(bad)))
    if page:   # page_text has turned every complete <sub>/<sup> into text
        if SCRIPT_TAG_RE.search(s):
            found.append(("tag", "<sub> or <sup> without its closing tag; close it or write the script in Unicode"))
    else:
        unbalanced = [t for t in READER_TAGS if s.count(f"<{t}>") != s.count(f"</{t}>")]
        if unbalanced:
            found.append(("tag", "unclosed tag: " + ", ".join(sorted(unbalanced))))
    if "\n" in s:
        found.append(("line_break", "hard line break"))
    return found


def check_style(annotations, cfg, listing=None, note_html=None):
    """Mechanical style checks on the generated annotations and the note; each finding is a warning.

    Checked: display defects in comments and margin texts (raw LaTeX, ^/_ exponents, tags the reader does not
    render, hard line breaks), label-colon margin notes and arrows or circled numbers in them, `banned_phrases`, highlights
    that duplicate or intersect each other, highlights that overlap annotations already in Zotero (the tool's
    own earlier ones excepted unless `cleanup` is false), text the tool already wrote on the same page when `cleanup` is
    false (`duplicate_existing`), the tool's annotations that the user changed in Zotero and a rewrite with `cleanup` would
    undo (`user_edit`), the number of core-coloured highlights against `core_range` (advisory: it does not
    block --apply), and mathematics in the note (a double backslash inside a math node, LaTeX outside one).
    """
    warnings = []
    existing = _existing_rects(listing, keep_own=not cfg.get("cleanup", False))
    banned = [b for b in (cfg.get("banned_phrases") or []) if b]
    marks = [a for a in annotations if a["type"] in ("highlight", "underline")]
    # what the tool wrote earlier and a run without cleanup keeps: the same text again on the same page is a duplicate
    earlier = {} if cfg.get("cleanup", False) else _own_texts(listing)

    def warn(kind, a, reason):
        label = a.get("text") if a["type"] in ("highlight", "underline") else a.get("comment", "")
        warnings.append({"kind": kind, "page": a["pageLabel"], "text": (label or "")[:60], "reason": reason})

    for a in annotations:
        is_mark = a["type"] in ("highlight", "underline")
        comment = a.get("comment", "")
        same = next((key for body, key in earlier.get((a["position"]["pageIndex"], is_mark), [])
                     if _listed_as(a.get("text") if is_mark else comment, body)), None)
        if same:
            warn("duplicate_existing", a, f"the tool already wrote this on the page ({same}); drop it, or set cleanup: true for "
                                          "a complete redo")
        for kind, reason in _text_defects(comment, page=a["type"] == "text"):
            warn(kind, a, reason)
        if not is_mark and LABEL_RE.match(comment):
            warn("label", a, "label-colon form; write a sentence")
        if not is_mark and STYLE_SYMBOL_RE.search(comment):
            warn("symbol", a, "arrows, circled numbers or bracket tags; write a sentence")
        hits = [b for b in banned if b in TAG_RE.sub("", comment)]
        if hits:
            warn("banned_phrase", a, "contains: " + ", ".join(hits))
        if is_mark and not same:
            page, rects = a["position"]["pageIndex"], a["position"]["rects"]
            for key, rs in existing.get(page, []):
                if any(_overlaps(r, rs) for r in rects):
                    warn("user_overlap", a, f"overlaps an existing annotation ({key})")
                    break
    for i, a in enumerate(marks):
        for b in marks[i + 1:]:
            if a["position"]["pageIndex"] != b["position"]["pageIndex"]:
                continue
            if a["position"]["rects"] == b["position"]["rects"]:
                warn("duplicate", b, "the same span is highlighted twice")
            elif any(_overlaps(r, b["position"]["rects"]) for r in a["position"]["rects"]):
                warn("overlap", b, "intersects another highlight: " + a["text"][:40])
    if cfg.get("cleanup", False):   # a rewrite would undo what the user changed in the tool's annotations since they were written
        for old in (listing or {}).get("annotations", []):
            if not set(old.get("tags") or []) & OWN_TAGS or not _changed_by_user(old) or any(_reproduces(a, old) for a in annotations):
                continue
            comment = " ".join((old.get("comment") or "").split())
            warnings.append({"kind": "user_edit", "page": old.get("pageLabel"), "text": _brief(old.get("text") or comment)[:60],
                             "reason": f"the user changed this annotation ({old.get('key')}) in Zotero after the tool wrote it, and the "
                                       f"rewrite would undo that: keep its comment “{comment[:300]}” and colour {old.get('color')} in the "
                                       "configuration, or --accept user_edit when the user asked to change it"})
    if cfg.get("core_range"):
        lo, hi = cfg["core_range"]
        n = sum(1 for a in marks if a["color"] == cfg["core_color"])
        if not lo <= n <= hi:
            warnings.append({"kind": "core_count", "page": None, "text": None,
                             "reason": f"{n} highlights in the core colour {cfg['core_color']}; core_range is {lo}-{hi}"})
    if note_html:
        def nwarn(reason):
            warnings.append({"kind": "note_math", "page": None, "text": "reading note", "reason": reason})
        for m in MATH_NODE_RE.findall(note_html):
            if "\\\\" in m:
                nwarn("double backslash inside a math node: " + m.strip()[:40])
            elif "$" not in m:
                nwarn("math node without $ delimiters: " + m.strip()[:40])
        rest = MATH_NODE_RE.sub(" ", note_html)
        if re.search(r"\$\$|\$[^$\n]+\$", rest):
            nwarn("LaTeX outside a math node is displayed as source")
        hits = [b for b in banned if b in TAG_RE.sub(" ", rest)]
        if hits:
            warnings.append({"kind": "banned_phrase", "page": None, "text": "reading note", "reason": "contains: " + ", ".join(hits)})
    return warnings


def compact_listing(listing):
    """Counts and the other annotations of a listing; the tool's own annotations are counted only."""
    anns = listing.get("annotations", [])
    own = [a for a in anns if set(a.get("tags") or []) & OWN_TAGS]
    others = [a for a in anns if not (set(a.get("tags") or []) & OWN_TAGS)]
    return {"ok": True, "backend": listing.get("backend"), "attachmentKey": listing.get("attachmentKey"),
            "annotations": len(anns), "own": len(own), "others": len(others),
            "by_type": dict(collections.Counter(a["type"] for a in anns)),
            "by_color": dict(collections.Counter(a.get("color") or "" for a in anns)),
            "others_detail": [{"key": a["key"], "type": a["type"], "color": a.get("color"), "page": a.get("pageLabel"),
                               "text": (a.get("text") or a.get("comment") or "")[:60]} for a in others],
            "notes": listing.get("notes", [])}


def version_note(html, prefix, existing_titles):
    """Existing notes are never deleted: if a note with this title prefix exists, the new note receives a versioned title."""
    same = [t for t in existing_titles if t and prefix and t.startswith(prefix)]
    if not same:
        return html, prefix
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.S | re.I)
    base = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else prefix
    base = re.sub(r"\s*\(v\d+, \d{4}-\d{2}-\d{2}\)\s*$", "", base)
    new_title = f"{base} (v{len(same) + 1}, {datetime.date.today().isoformat()})"
    html = html[:m.start(1)] + new_title + html[m.end(1):] if m else f"<h1>{new_title}</h1>\n" + html
    return html, new_title


def note_title_from_html(html):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", flags=re.S | re.I)
    src = m.group(1) if m else re.sub(r"<br\s*/?>", "\n", html or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", src)).strip()[:200]


def note_body(html):
    """A note's text without its title (which carries the version) and without markup; Zotero wraps a saved
    note in <div data-schema-version="…">, which changes nothing here."""
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<h1[^>]*>.*?</h1>", " ", html or "", count=1, flags=re.S | re.I))
    return re.sub(r"\s+", " ", htmllib.unescape(text)).strip()


def read_text(path):
    """A text file written by the agent; a byte-order mark (PowerShell 5 writes one) is dropped."""
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
PAGE_NUM_RE = re.compile(r"^(?:\d{1,4}|[ivxlcdm]{1,7})$", re.I)
# headings as norm_str gives them: "7 References", "VII. REFERENCES", "Literature Cited" -> "7references", "vii.references", …
REFERENCES_RE = re.compile(r"(?:\d+|[ivxl]+)?\.?(?:references(?:andnotes)?|bibliography|literaturecited|workscited|参考文献)[.:：]?")
CHECKLIST_RE = re.compile(r"(?:[a-z]|\d+)?\.?(?:neurips|icml|iclr|aaai|ijcai|acl|emnlp|naacl|cvpr|iccv|eccv|ml)?"
                          r"(?:paper|reproducibility|responsiblenlp(?:research)?)?checklist:?")
APPENDIX_RE = re.compile(r"(?:[a-z]|\d+)?\.?(?:technical)?(?:appendix|appendices|supplementa(?:ry|l))")
ROTATED_MARK = " (rotated: not annotatable)"   # in the page marker of a rotated page


def extract_paragraphs(pdf_path, pages=None, keep_references=False):
    """[(page number, [(kind, text), ...], rotated), ...] with kind "heading", "para" or "marker".

    Lines are de-hyphenated and ligatures expanded with the same rules the matcher uses, so a phrase
    copied from this output matches. Running headers and footers (lines recurring on most pages) and
    standalone page numbers are dropped; the bibliography between the References heading and the next
    heading (judged by font size and weight) is replaced by a marker line unless keep_references is set,
    and so is a paper checklist after the bibliography, from its heading to the next appendix heading or the end."""
    doc = pymupdf.open(pdf_path)
    sel = list(range(len(doc))) if not pages else [p - 1 for p in pages if 1 <= p <= len(doc)]
    page_rows, weighted = [], []
    for p in sel:
        rows = []
        for bi, block in enumerate(text_lines(doc[p])):
            for line in block.get("lines", []):
                dx, dy = line.get("dir", (1, 0))
                if abs(dx - 1) > 0.01 or abs(dy) > 0.01:
                    continue                      # vertical text, e.g. an arXiv stamp in the margin
                spans = line.get("spans", [])
                txt = re.sub(r"\s+", " ", "".join(s.get("text", "") for s in spans)).strip()
                if not txt:
                    continue
                size = max((s.get("size", 0.0) for s in spans), default=0.0)
                bold = bool(spans) and all(s.get("flags", 0) & 16 for s in spans)
                rows.append((bi, txt, size, bold))
                weighted.append((size, len(txt)))
        page_rows.append(rows)
    weighted.sort()
    total, acc, body_size = sum(w for _, w in weighted), 0, 10.0
    for size, w in weighted:                      # length-weighted median font size = the body text
        acc += w
        if acc >= total / 2:
            body_size = size; break

    def heading(t, size, bold):
        return len(t) < 70 and (size >= body_size + 0.8 or (bold and size >= body_size - 0.1))

    counts = collections.Counter()
    for rows in page_rows:
        for t in {norm_str(t) for _, t, _, _ in rows[:3] + rows[-3:]}:
            counts[t] += 1
    recurring = {t for t, n in counts.items() if t and len(page_rows) >= 3 and n > len(page_rows) / 2}
    out, in_refs, in_checklist, after_refs = [], False, False, False
    for p, rows in zip(sel, page_rows):
        paras = []
        # blocks of nothing but lone numbers or numerals: line numbers beside the text, axis ticks, a page number
        numeric = {r[0] for r in rows} - {blk for blk, t, _, _ in rows if not PAGE_NUM_RE.match(t)}
        for i, (blk, t, size, bold) in enumerate(rows):
            n = norm_str(t)
            edge = i < 3 or i >= len(rows) - 3
            # page numbers and running lines are among a page's first or last rows; inside a block of text a lone
            # number or letter is part of the text (a variable of a formula set on its own line)
            if (PAGE_NUM_RE.match(t) and (edge or blk in numeric)) or (edge and n in recurring):
                continue
            if in_checklist:
                if not (heading(t, size, bold) and APPENDIX_RE.match(n)):
                    continue
                in_checklist = False              # the checklist ends at the appendix
            is_refs = bool(REFERENCES_RE.fullmatch(n))
            after_refs = after_refs or is_refs
            if not keep_references:
                if not in_refs and is_refs:
                    in_refs = True
                    paras.append([None, "[references removed]", "marker"])
                    continue
                if in_refs:
                    if n.startswith(("appendix", "supplementary")) or heading(t, size, bold):
                        in_refs = False           # the bibliography ends at the next heading
                    else:
                        continue
            # a paper checklist follows the bibliography; before it, a section may be called "Checklist"
            if after_refs and heading(t, size, bold) and CHECKLIST_RE.fullmatch(n):
                in_checklist = True
                paras.append([None, "[checklist removed]", "marker"])
                continue
            t = "".join(LIG.get(c, c) for c in t)
            kind = "heading" if heading(t, size, bold) else "para"
            if paras and paras[-1][0] == blk and kind == "para" and paras[-1][2] == "para":
                prev = paras[-1][1]
                paras[-1][1] = prev[:-1] + t if prev.endswith("-") and t[:1].islower() else prev + " " + t
            else:
                paras.append([blk, t, kind])
        out.append((p + 1, [(kind, re.sub(r"([A-Za-z])-\s+([a-z])", r"\1\2", t)) for _, t, kind in paras],
                    bool(doc[p].rotation % 360)))
    return out


def extract_text(pdf_path, pages=None, keep_references=False):
    """The paper's text with page markers, one paragraph per line (see extract_paragraphs)."""
    return "\n\n".join(f"--- p.{p}{ROTATED_MARK if rotated else ''} ---\n" + "\n".join(t for _, t in paras)
                       for p, paras, rotated in extract_paragraphs(pdf_path, pages, keep_references)) + "\n"


ABBREV_RE = re.compile(r"(?:\b(?:e\.g|i\.e|et al|cf|vs|viz|resp|approx|ca|Fig|Figs|Eq|Eqs|Sec|Secs|Tab|Ref|Refs|No|Nos|Dr|Prof|Mr|Ms|Mrs|St|Vol|pp|Ch|Def|Thm|Lem|Prop|Cor|Alg|App)|\b[A-Z])\.$")
SENT_END_RE = re.compile(r"[.!?][\"'”’)\]]*(?=\s+[A-Z0-9(\[\"“‘])")
MIN_SENTENCE_WORDS = 3   # shorter fragments ("Proof.", "Theorem 2.") merge with their predecessor


def split_sentences(text):
    """The sentences of one paragraph.

    A full stop after an abbreviation, an initial or inside a number does not end a sentence, and a
    fragment of fewer than MIN_SENTENCE_WORDS words is merged with its predecessor."""
    text = " ".join(text.split())
    parts, start = [], 0
    for m in SENT_END_RE.finditer(text):
        head = text[start:m.end()]
        if ABBREV_RE.search(head.rstrip("\"'”’)]")):
            continue
        parts.append(head.strip()); start = m.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    merged = []
    for part in parts:
        if merged and (len(part.split()) < MIN_SENTENCE_WORDS or len(merged[-1].split()) < MIN_SENTENCE_WORDS):
            merged[-1] += " " + part
        else:
            merged.append(part)
    return merged


def extract_sentences(pdf_path, pages=None, keep_references=False):
    """Numbered sentences plus headings and markers, in reading order.

    A sentence is {"id", "page", "para", "text"} with ids counted from 1 across the document; a heading is
    {"page", "para", "heading"}; a marker is {"page", "para", "marker"}. Items of a rotated page carry "rotated"."""
    items, sid, para = [], 0, 0
    for p, paras, rotated in extract_paragraphs(pdf_path, pages, keep_references):
        start = len(items)
        for kind, text in paras:
            para += 1
            if kind == "heading":
                items.append({"page": p, "para": para, "heading": text})
            elif kind == "marker":
                items.append({"page": p, "para": para, "marker": text})
            else:
                for sent in split_sentences(text):
                    sid += 1
                    items.append({"id": sid, "page": p, "para": para, "text": sent})
        if rotated:   # nothing is written on a rotated page; its page marker says so
            for it in items[start:]:
                it["rotated"] = True
    return items


SENTENCE_SIMILARITY = 0.9   # the least similarity of a passage taken for a sentence not found as extracted


def sentence_rects(pdf_path, items):
    """Give each sentence its position as Zotero stores it, "rects" in PDF user space, found as its highlight would be:
    when the page has a sentence's text as often as the extracted sentences of the page have it, the n-th of them is its
    n-th occurrence; when the page has it more or fewer times, it is ambiguous and gets none. A sentence whose text the
    page does not have takes the closest passage when it is alike enough. Sentences on a rotated page get none."""
    doc = pymupdf.open(pdf_path)
    try:
        counts = collections.Counter((it["page"], norm_str(it["text"])) for it in items if "id" in it)
        seen, pages = collections.Counter(), {}
        for it in items:
            if "id" not in it:
                continue
            key = (it["page"], norm_str(it["text"]))
            seen[key] += 1
            if it.get("rotated"):
                continue
            p = it["page"] - 1
            if p not in pages:
                pages[p] = (PageIndex(doc[p]), user_space_shift(doc[p]))
            pi, (dx, dy) = pages[p]
            n = pi.count(it["text"])
            ws = pi.match(it["text"], seen[key]) if n == counts[key] else None
            if not n:
                ws, ratio = pi.closest(it["text"])
                if ratio < SENTENCE_SIMILARITY:
                    ws = None
            if ws:
                rects = pi.position_rects(ws)
                it["rects"] = [shift_rect(r, dx, dy) for r in rects] if dx or dy else rects
    finally:
        doc.close()
    return items


def render_sentences(items):
    """The listing an agent reads: page markers, `## heading` lines, `id | sentence` lines, blank lines between paragraphs."""
    out, page, para = [], None, None
    for it in items:
        if it["page"] != page:
            if out:
                out.append("")
            out.append(f"--- p.{it['page']}{ROTATED_MARK if it.get('rotated') else ''} ---"); page, para = it["page"], None
        elif "id" in it and para is not None and it["para"] != para:
            out.append("")                        # a blank line between two sentence paragraphs
        para = it["para"] if "id" in it else None
        if "heading" in it:
            out.append("## " + it["heading"])
        elif "marker" in it:
            out.append(it["marker"])
        else:
            out.append(f"{it['id']} | {it['text']}")
    return "\n".join(out) + "\n"


def _load_sentences(cfg):
    """Load a cache for this exact PDF, counting complete sentences separately from substring matches."""
    path = cfg.get("sentences") or os.path.join(cfg["out_dir"], "sentences.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"sentences file not found: {path} (run `scholium extract --sentences`)")
    data = json.load(open(path, encoding="utf8"))
    if not data.get("pdf_sha256") or data["pdf_sha256"] != _sha256(cfg["pdf"]):
        raise ValueError("sentence cache has no matching PDF fingerprint; re-run `scholium extract --sentences`")
    counts = collections.Counter((it["page"], norm_str(it["text"])) for it in data.get("sentences", []) if "id" in it)
    heads = [(h.get("para", 0), h.get("heading", "")) for h in data.get("headings", [])]
    seen, table, para = collections.Counter(), {}, 0
    for it in data.get("sentences", []):
        if "id" not in it:
            continue
        key = (it["page"], norm_str(it["text"]))
        seen[key] += 1
        # the heading between this sentence and the one before it, if any
        between = [h for p, h in heads if para < p < it.get("para", 0)]
        para = it.get("para", 0)
        table[int(it["id"])] = dict(it, occurrence=seen[key], same_text_count=counts[key], heading_before=between[-1] if between else None)
    return table


def _unmatched_ids(pg, ids, recs):
    """Why the text of sentence ids is not found on their page, and what to do instead."""
    if len(recs) > 1:
        for a, b in zip(recs, recs[1:]):
            if pg.count(a["text"]) and pg.count(b["text"]) and not pg.count(a["text"] + " " + b["text"]):
                what = f"the heading “{b['heading_before']}”" if b.get("heading_before") else "other text (a heading, caption or footnote)"
                return (f"sentences {ids[0]}–{ids[-1]} are not one passage: {what} stands between sentence {a['id']} and sentence "
                        f"{b['id']}; split the range there")
        return f"the text of sentences {ids[0]}–{ids[-1]} is not found on the page as one passage; highlight them one by one or use page and text"
    return f"the text of sentence {ids[0]} is not found on the page as extracted; use page and text"


def extract_main(argv):
    ap = argparse.ArgumentParser(prog="scholium extract",
                                 description="Print the PDF's text with page markers, de-hyphenated, without running headers, footers, page numbers, "
                                             "the bibliography and a paper checklist.")
    ap.add_argument("--pdf", help="path of the PDF (default: the \"pdf\" key of --config)")
    ap.add_argument("--config", help="JSON configuration file to take the pdf path from")
    ap.add_argument("--out", help="write to this file instead of standard output")
    ap.add_argument("--pages", help="page or page range, e.g. 3 or 1-8 (default: all pages)")
    ap.add_argument("--keep-references", action="store_true", help="keep the bibliography")
    ap.add_argument("--sentences", metavar="JSON", help="write numbered sentences with their positions to this JSON file and print the numbered listing instead of plain text")
    args = ap.parse_args(argv)
    if pymupdf is None:
        sys.exit(PYMUPDF_MISSING)
    pdf = args.pdf or (json.loads(read_text(args.config)).get("pdf") if args.config else None)
    if not pdf:
        sys.exit("extract: give --pdf or --config")
    pages = None
    if args.pages:
        m = re.match(r"^(\d+)(?:-(\d+))?$", args.pages)
        if not m:
            sys.exit("extract: --pages takes N or N-M")
        pages = list(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
    no_text = ("extract: the PDF has no text layer (a scanned document); it cannot be annotated until OCR has added one, "
               "so stop and tell the user")
    if args.sentences:
        pdf_hash = _sha256(pdf)
        # ids count over the whole document
        items = sentence_rects(pdf, extract_sentences(pdf, keep_references=args.keep_references))
        n = sum(1 for it in items if "id" in it)
        if _sha256(pdf) != pdf_hash:
            sys.exit("extract: PDF changed during extraction; run again")
        if not any("id" in it or "heading" in it for it in items):
            sys.exit(no_text)
        os.makedirs(os.path.dirname(os.path.abspath(args.sentences)), exist_ok=True)
        json.dump({"pdf": pdf, "pdf_sha256": pdf_hash, "sentences": [it for it in items if "id" in it],
                   "headings": [it for it in items if "id" not in it]}, open(args.sentences, "w", encoding="utf8"), ensure_ascii=False, indent=0)
        text = render_sentences([it for it in items if not pages or it["page"] in pages])
        summary = f"{n} sentences -> {args.sentences}; {text.count(chr(10))} lines, {len(text)} characters"
    else:
        text = extract_text(pdf, pages=pages, keep_references=args.keep_references)
        if not pages and not re.sub(r"--- p\.\d+.*? ---|\s", "", text):
            sys.exit(no_text)
        summary = f"{text.count(chr(10))} lines, {len(text)} characters"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        open(args.out, "w", encoding="utf8").write(text)
        print(f"{args.out}: {summary}")
    else:
        print(text)
    return 0


GET_ATTEMPTS = 3


def local_opener():
    """An opener that goes straight to Zotero on this computer, also when the environment names a proxy (http_proxy
    without no_proxy)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(method, path, body=None, headers=None, timeout=60):
    """One HTTP call against the local API.

    A busy Zotero can leave a request hanging until the socket times out, which
    surfaces as status 0. GET is safe to repeat, so a read is retried a few times
    before giving up; every other method is returned to the caller as-is, because
    a POST that timed out may still have been committed. A refused connection
    (nothing listens: Zotero is closed or its server is off) is reported at once.
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf8") if body is not None else None
    attempts = GET_ATTEMPTS if method.upper() == "GET" else 1
    for attempt in range(attempts):
        req = urllib.request.Request(BASE + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with local_opener().open(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read().decode("utf8", "ignore")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf8", "ignore")
        except Exception as e:
            if attempt == attempts - 1 or isinstance(getattr(e, "reason", e), ConnectionRefusedError):
                return 0, {}, str(e)
            time.sleep(5 * (attempt + 1))
    return 0, {}, "unreachable"


def zotero_version():
    s, h, _ = http("GET", "/api/", timeout=8)
    if s == 0:
        return None, None
    return h.get("X-Zotero-Version", ""), h.get("Zotero-Server-ID", "")


# ---------------------------------------------------------------------------
# Backend 1: official local API (Zotero 10+)
# ---------------------------------------------------------------------------
class LocalApi:
    def __init__(self, server_id):
        self.server_id = server_id
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
        self.key_file = os.path.join(base, "zotero-scholium", "local-api-keys.json")
        self.keys = {}
        if os.path.exists(self.key_file):
            try:
                self.keys = json.load(open(self.key_file, encoding="utf8"))
            except Exception:
                self.keys = {}
        self.key = self.keys.get(server_id)

    def _save_key(self):
        os.makedirs(os.path.dirname(self.key_file), exist_ok=True)
        self.keys[self.server_id] = self.key
        json.dump(self.keys, open(self.key_file, "w", encoding="utf8"))

    def authorize(self):
        print(f"[zotero] Authorisation required: choose \"Allow\" or \"Always Allow\" in the Zotero dialog for \"{APP_NAME}\".",
              file=sys.stderr, flush=True)
        s, h, t = http("POST", "/api/local/authorize", {"appName": APP_NAME}, {"Zotero-Server-ID": self.server_id}, timeout=300)
        if s != 200:
            raise RuntimeError(f"authorization failed (HTTP {s}): {t[:200]}")
        d = json.loads(t)
        self.key = d["key"]
        if d.get("remember"):
            self._save_key()
        return self.key

    WRITE_TIMEOUT = 600
    WRITE_ATTEMPTS = 4

    def write(self, method, path, body=None, extra=None):
        """Write request with automatic (re)authorization on 401 and retries.

        Zotero serialises every write behind one library-wide version counter, so a
        batch that lands while another write is in flight comes back as 412 with a
        stale If-Unmodified-Since-Version; retrying with a fresh version fixes it.
        A busy Zotero can also take minutes to commit a 50-item batch, hence the long
        timeout. Timeouts (status 0) and server errors (500/503) are only retried
        for idempotent methods: a POST may already have committed, so retrying it
        could duplicate annotations.
        """
        s = h = t = None
        auth_retried = False
        idempotent = method.upper() != "POST"
        for attempt in range(self.WRITE_ATTEMPTS):
            if not self.key:
                self.authorize()
            hdr = {"Zotero-Server-ID": self.server_id, "Zotero-API-Key": self.key}
            hdr.update(extra or {})
            if attempt and "If-Unmodified-Since-Version" in hdr:
                hdr["If-Unmodified-Since-Version"] = self.library_version()
            s, h, t = http(method, path, body, hdr, timeout=self.WRITE_TIMEOUT)
            if s == 401 and not auth_retried:
                auth_retried = True
                self.key = None
                self.keys.pop(self.server_id, None)
                continue
            retryable = s == 412 or (idempotent and s in (0, 500, 503))
            if retryable and attempt < self.WRITE_ATTEMPTS - 1:
                time.sleep(5 * (attempt + 1))
                continue
            return s, h, t
        return s, h, t

    def library_version(self):
        s, h, _ = http("GET", "/api/users/0/items?limit=1")
        return h.get("Last-Modified-Version", "0")

    def children(self, key, item_type=None):
        q = f"?itemType={item_type}" if item_type else ""
        s, h, t = http("GET", f"/api/users/0/items/{key}/children{q}")
        if s != 200:
            raise RuntimeError(f"failed to read children (HTTP {s}): {NOT_IN_MY_LIBRARY if s == 404 else t[:200]}")
        return json.loads(t)

    def create(self, items):
        """Keys created and failures, in batches of 50. A batch that fails ends the run; the keys of the batches
        before it are kept, and its failure names the items from that batch on, which may or may not exist."""
        created, failed = [], []
        for i in range(0, len(items), 50):
            try:   # a 401 whose new authorisation fails raises
                s, h, t = self.write("POST", "/api/users/0/items", items[i:i + 50])
                reason = None if s == 200 else f"create failed (HTTP {s}): {t[:300]}"
                d = json.loads(t) if s == 200 else {}
            except Exception as e:
                reason = f"create failed: {e}"
            if reason:
                failed.append({"message": reason, "items": f"{i + 1}-{len(items)} of {len(items)}"})
                break
            created += [v["key"] for v in d.get("successful", {}).values()]
            failed += list(d.get("failed", {}).values())
        return created, failed

    def delete(self, keys):
        for i in range(0, len(keys), 50):
            s, h, t = self.write("DELETE", "/api/users/0/items?itemKey=" + ",".join(keys[i:i + 50]),
                                 None, {"If-Unmodified-Since-Version": self.library_version()})
            if s not in (204, 200):
                raise RuntimeError(f"delete failed (HTTP {s}): {t[:300]}")
        return len(keys)

    def trash(self, rows):
        """Move items to Zotero's trash (recoverable there); `rows` are their API rows, whose versions guard the write."""
        for i in range(0, len(rows), 50):
            body = [{"key": r["key"], "version": r["data"].get("version", r.get("version", 0)), "deleted": True} for r in rows[i:i + 50]]
            s, h, t = self.write("POST", "/api/users/0/items", body)
            failed = (json.loads(t).get("failed") or {}) if s == 200 else None
            if s != 200 or failed:
                raise RuntimeError(f"moving notes to the trash failed (HTTP {s}): {(json.dumps(failed) if failed else t)[:300]}")
        return len(rows)


def parse_position(value):
    """annotationPosition arrives as a JSON string from the local API and as an object from the bridge plugin."""
    try:
        return json.loads(value) if isinstance(value, str) else (value or {})
    except ValueError:
        return {}


def api_list(cfg, api):
    rows = api.children(cfg["attachment_key"], "annotation")

    def listed(r):
        # the tool's own annotations whole, with the dates that show whether the user changed them after they were written
        d = r["data"]
        tags = [t["tag"] for t in d.get("tags", [])]
        cut = 2000 if set(tags) & OWN_TAGS else 80
        return {"key": r["key"], "type": d["annotationType"], "color": d.get("annotationColor"), "author": d.get("annotationAuthorName", ""),
                "tags": tags, "pageLabel": d.get("annotationPageLabel"), "text": (d.get("annotationText") or "")[:cut],
                "comment": (d.get("annotationComment") or "")[:cut], "added": d.get("dateAdded"), "modified": d.get("dateModified"),
                "position": parse_position(d.get("annotationPosition"))}
    anns = [listed(r) for r in rows]
    notes = []
    if cfg.get("item_key"):
        for c in api.children(cfg["item_key"]):
            if c["data"]["itemType"] == "note":
                notes.append({"key": c["key"], "title": note_title_from_html(c["data"].get("note", ""))})
    return {"ok": True, "backend": "api", "attachmentKey": cfg["attachment_key"], "annotations": anns, "notes": notes}


def api_apply(cfg, out, api):
    # Capture old owned keys before creating anything; matching text is not ownership.
    rows = api.children(cfg["attachment_key"], "annotation") if cfg.get("cleanup", False) else []
    to_delete, kept = [], 0
    for r in rows:
        tags = {t["tag"] for t in r["data"].get("tags", [])}
        if tags & OWN_TAGS:
            to_delete.append(r["key"])
        else:
            kept += 1
    result = {"ok": False, "backend": "api", "removed": 0, "kept": kept,
              "noteCreated": False, "notesTrashed": 0, "created": {},
              "createdKeys": [], "noteKeys": [], "failed": []}
    victims = []
    # (1) Child note: old notes stay until all new content has been created; then, with note_replace, the tool's
    #     earlier notes go to the trash. A tool note with the same text is not written again.
    if cfg.get("note_html") and cfg.get("item_key"):
        html = read_text(cfg["note_html"])
        prefix = cfg.get("note_title_prefix") or cfg.get("note_title") or ""
        existing = [c for c in api.children(cfg["item_key"]) if c["data"]["itemType"] == "note"]
        same = next((c for c in existing if _own(c) and note_body(c["data"].get("note", "")) == note_body(html)), None)
        if cfg.get("note_replace"):
            only = cfg.get("note_title_prefix") or ""
            victims = [c for c in existing if _own(c) and c is not same
                       and note_title_from_html(c["data"].get("note", "")).startswith(only)]
        if same:
            result["noteSkipped"] = f"the tool's note {same['key']} has the same text"
        else:
            titles = [note_title_from_html(c["data"].get("note", "")) for c in existing if c not in victims]
            html, _ = version_note(html, prefix, titles)
            keys, failed = api.create([{"itemType": "note", "parentItem": cfg["item_key"], "note": html, "tags": [{"tag": TAG}]}])
            result["noteKeys"] = keys
            result["noteCreated"] = not failed and len(keys) == 1
            if not result["noteCreated"]:
                result["failed"] = failed or [{"message": "note creation returned no unique item key"}]
                return result
    # (2) annotations
    items = []
    for a in out:
        it = {"itemType": "annotation", "parentItem": cfg["attachment_key"], "annotationType": a["type"],
              "annotationComment": a.get("comment", ""), "annotationColor": a["color"],
              "annotationPageLabel": a["pageLabel"], "annotationSortIndex": a["sortIndex"],
              "annotationPosition": json.dumps(a["position"]), "tags": [{"tag": TAG}]}
        if a["type"] in ("highlight", "underline"):
            it["annotationText"] = a.get("text", "")
        items.append(it)
    created_keys, failed = api.create(items)
    result["createdKeys"] = created_keys
    if failed or len(set(created_keys)) != len(items):
        result["failed"] = failed or [{"message": "annotation creation returned fewer unique keys than requested"}]
        result["created"] = {"created_keys": len(created_keys), "failed": result["failed"]}
        return result
    counts = {}
    for a in out:
        counts[a["type"]] = counts.get(a["type"], 0) + 1
    result["created"] = counts
    # Do not remove earlier work if either creation call failed.
    try:   # the new items are written; a failure here leaves earlier ones in place
        result["removed"] = api.delete(to_delete) if to_delete else 0
        result["notesTrashed"] = api.trash(victims) if victims else 0
    except Exception as e:
        result["removeError"] = str(e)
    result["ok"] = True
    return result


# ---------------------------------------------------------------------------
# Backend 2: scholium-bridge plugin (Zotero 7 and later)
# ---------------------------------------------------------------------------
def zotero_prefs_data_dir(profile_roots=None):
    """Data directory recorded in Zotero's prefs.js (`extensions.zotero.dataDir`), or None."""
    if profile_roots is None:
        profile_roots = []
        if os.environ.get("APPDATA"):
            profile_roots.append(os.path.join(os.environ["APPDATA"], "Zotero", "Zotero", "Profiles"))
        profile_roots.append(os.path.expanduser("~/Library/Application Support/Zotero/Profiles"))
        profile_roots.append(os.path.expanduser("~/.zotero/zotero"))
    for root in profile_roots:
        for prefs in sorted(glob.glob(os.path.join(root, "*", "prefs.js"))):
            try:
                text = open(prefs, encoding="utf8", errors="ignore").read()
            except OSError:
                continue
            m = re.search(r'user_pref\("extensions\.zotero\.dataDir",\s*"((?:[^"\\]|\\.)*)"\)', text)
            if m:
                try:
                    return json.loads('"' + m.group(1) + '"')  # prefs.js uses JavaScript string escapes
                except ValueError:
                    continue
    return None


def _data_dir_candidates(cfg):
    """Possible Zotero data directories, most specific first: the configuration, the ZOTERO_DATA_DIR
    environment variable, the PDF path (…/storage/<KEY>/file.pdf), Zotero's prefs.js, and the default."""
    c = []
    if cfg and cfg.get("data_dir"):
        c.append(cfg["data_dir"])
    if os.environ.get("ZOTERO_DATA_DIR"):
        c.append(os.environ["ZOTERO_DATA_DIR"])
    if cfg and cfg.get("pdf"):
        p = os.path.abspath(cfg["pdf"]).replace("\\", "/")
        if "/storage/" in p:
            c.append(p.split("/storage/")[0])
    prefs = zotero_prefs_data_dir()
    if prefs:
        c.append(prefs)
    c.append(os.path.join(os.path.expanduser("~"), "Zotero"))
    return c


def zotero_data_dir(cfg=None):
    """The Zotero data directory: the first candidate that contains zotero.sqlite, else the first that exists,
    else the default location."""
    cands = _data_dir_candidates(cfg)
    for d in cands:
        if os.path.isfile(os.path.join(d, "zotero.sqlite")):
            return d
    for d in cands:
        if os.path.isdir(d):
            return d
    return cands[-1]


def profile_dir(cfg=None):
    """Directory of profile.json and profile.md: <Zotero data dir>/zotero-scholium/. The profile describes
    the annotation habits of one library, so it is kept next to that library rather than in the user
    configuration directory."""
    return os.path.join(zotero_data_dir(cfg), "zotero-scholium")


def legacy_profile_dir():
    """Location used by versions before 0.1.0: the user configuration directory."""
    return os.path.join(os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config"), "zotero-scholium")


def bridge_connect(cfg):
    """(token, the attachment's listing) once the plugin answers; (None, reason) otherwise. The connection
    check is the list request itself, so the listing comes with it ({"ok": False, "error": ...} when it failed)."""
    token = None
    for d in _data_dir_candidates(cfg):
        tok_path = os.path.join(d, "scholium-bridge.token")
        if os.path.exists(tok_path):
            token = open(tok_path, encoding="utf8").read().strip()
            break
    s, h, t = http("POST", "/scholium-bridge/list", {"attachmentKey": cfg.get("attachment_key", "")},
                   {"X-Annotate-Token": token or ""}, timeout=15)
    if s == 0:
        return None, "Zotero is not running or its local server is disabled (" + t[:80] + ")"
    if s == 404:
        return None, "scholium-bridge plugin is not installed (HTTP 404)"
    if s == 401:
        return None, "token mismatch or token file not found (scholium-bridge.token in the Zotero data directory; set data_dir in the config)"
    if not token:
        return None, "token file not found (looked in: %s)" % ", ".join(_data_dir_candidates(cfg))
    res = json.loads(t) if s == 200 else {}
    if not res.get("ok"):
        return token, {"ok": False, "error": "list failed (HTTP %s): %s" % (s, t[:200])}
    res["backend"] = "bridge"
    return token, res


def bridge_list(cfg):
    token, res = bridge_connect(cfg)
    if not token:
        return None, res
    return (res, None) if res["ok"] else (None, res["error"])


def bridge_apply(cfg, out):
    token, lst = bridge_connect(cfg)
    if not token:
        return None, lst
    html = read_text(cfg["note_html"]) if cfg.get("note_html") else None
    prefix = cfg.get("note_title_prefix") or cfg.get("note_title") or ""
    only = cfg.get("note_title_prefix") or ""
    replace = bool(cfg.get("note_replace", False))
    if html:   # the notes the run leaves in place decide the version in the new note's title
        stay = [n["title"] for n in lst.get("notes", [])
                if not (replace and set(n.get("tags") or []) & OWN_TAGS and (n["title"] or "").startswith(only))]
        html, prefix = version_note(html, prefix, stay)
    # trashOwn and trashTitlePrefix are new keys: an older plugin ignores them and trashes nothing
    payload = {"itemKey": cfg["item_key"], "attachmentKey": cfg["attachment_key"],
               "cleanup": bool(cfg.get("cleanup", False)), "cleanupExternal": bool(cfg.get("cleanup_external")), "tag": TAG, "legacyTags": sorted(LEGACY_TAGS), "annotations": out,
               "note": {"html": html, "titlePrefix": prefix, "trashOwn": replace, "trashTitlePrefix": only} if html else None}
    s, h, t = http("POST", "/scholium-bridge/apply", payload, {"X-Annotate-Token": token}, timeout=LocalApi.WRITE_TIMEOUT)
    res = json.loads(t) if s == 200 else {}
    if not res.get("ok"):
        return None, "apply failed (HTTP %s): %s" % (s, t[:200])
    res["backend"] = "bridge"
    if html and replace and "notesTrashed" not in res:
        res["noteReplace"] = "not done: plugins before 0.1.9 leave earlier notes in place; update the plugin"
    return res, None


# ---------------------------------------------------------------------------
# Backend 3: "Run JavaScript" file (manual execution)
# ---------------------------------------------------------------------------
def render_js(cfg, out):
    html = read_text(cfg["note_html"]) if cfg.get("note_html") else None
    title_prefix = cfg.get("note_title_prefix") or cfg.get("note_title") or ""
    replace = bool(html and cfg.get("note_replace"))
    note_step = ("create a child note unless a note of this tool has the same text; " +
                 ("then move the tool's other notes" + (" whose title starts with the prefix" if cfg.get("note_title_prefix") else "") +
                  " to the trash (step 2)" if replace else "a note with the same title gets a versioned title; no note is deleted")
                 if html else "(no child note in this run)")
    n_h = sum(1 for a in out if a["type"] in ("highlight", "underline")); n_t = len(out) - n_h
    return f"""// Usage: in Zotero, open Tools -> Developer -> Run JavaScript, enable "Run as async function",
// paste the entire content of this file, and click Run.
// Effect (all changes are made in the Zotero database; the PDF file is not modified):
//   (0) {'delete annotations carrying a current or legacy tool tag on the attachment, once the new ones are saved (step 2);' if cfg.get('cleanup', False) else 'keep every existing annotation (cleanup disabled);'}
//   (1) {note_step};
//   (2) create {n_h} highlight/underline annotations and {n_t} margin text annotations; a failure leaves the old ones.
var ITEM_KEY = {json.dumps(cfg['item_key'])}, ATT_KEY = {json.dumps(cfg['attachment_key'])}, TAG = {json.dumps(TAG)};
var OWN_TAGS = {json.dumps(sorted(OWN_TAGS))};
var CLEANUP = {json.dumps(bool(cfg.get('cleanup', False)))};
var NOTE_HTML = {json.dumps(html, ensure_ascii=False)};
var NOTE_TITLE_PREFIX = {json.dumps(title_prefix, ensure_ascii=False)};
var NOTE_REPLACE = {json.dumps(replace)}, TRASH_TITLE_PREFIX = {json.dumps(cfg.get('note_title_prefix') or '', ensure_ascii=False)};
var ANNOTATIONS = {json.dumps(out, ensure_ascii=False)};

var libraryID = Zotero.Libraries.userLibraryID;
var parent = Zotero.Items.getByLibraryAndKey(libraryID, ITEM_KEY);
var att = Zotero.Items.getByLibraryAndKey(libraryID, ATT_KEY);
if (!parent) throw new Error("item not found: " + ITEM_KEY);
if (!att) throw new Error("attachment not found: " + ATT_KEY);

var old = [], kept = 0;
for (let a of (CLEANUP ? att.getAnnotations(true) : [])) {{
  let tags = a.getTags().map(t => t.tag);
  let mine = tags.some(t => OWN_TAGS.includes(t));
  if (mine) {{ old.push(a); }} else {{ kept++; }}
}}

var noteCreated = false, noteSame = null, trash = [];
if (NOTE_HTML) {{
  let body = h => String(h || "").replace(/<h1[^>]*>[\\s\\S]*?<\\/h1>/i, " ").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&").replace(/\\s+/g, " ").trim();
  let notes = Zotero.Items.get(parent.getNotes());
  let own = n => n.getTags().some(t => OWN_TAGS.includes(t.tag));
  noteSame = notes.find(n => own(n) && body(n.getNote()) === body(NOTE_HTML)) || null;
  if (NOTE_REPLACE) trash = notes.filter(n => own(n) && n !== noteSame && (n.getNoteTitle() || "").startsWith(TRASH_TITLE_PREFIX)).map(n => n.id);
  let existing = notes.filter(n => !trash.includes(n.id)).map(n => n.getNoteTitle());
  let same = existing.filter(t => t && NOTE_TITLE_PREFIX && t.startsWith(NOTE_TITLE_PREFIX));
  let html = NOTE_HTML;
  if (same.length) {{
    let d = new Date(), ds = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    html = html.replace(/<h1([^>]*)>([\\s\\S]*?)<\\/h1>/i, (m, attrs, t) => "<h1" + attrs + ">" + t.replace(/\\s*\\(v\\d+, \\d{{4}}-\\d{{2}}-\\d{{2}}\\)\\s*$/, "") + " (v" + (same.length + 1) + ", " + ds + ")</h1>");
  }}
  if (!noteSame) {{
    let note = new Zotero.Item("note");
    note.libraryID = libraryID;
    note.parentID = parent.id;
    note.setNote(html);
    note.setTags([{{tag: TAG}}]);
    await note.saveTx();
    noteCreated = true;
  }}
}}

var created = {{highlight: 0, underline: 0, text: 0, note: 0}};
await Zotero.DB.executeTransaction(async function () {{
  for (let a of ANNOTATIONS) {{
    let ann = new Zotero.Item("annotation");
    ann.libraryID = libraryID;
    ann.parentID = att.id;
    let type = a.type;
    try {{ ann.annotationType = type; }}
    catch (e) {{ type = "note"; ann.annotationType = type; }}  // Zotero without text annotations: fall back to a sticky note
    if (type === "highlight" || type === "underline") ann.annotationText = a.text;
    ann.annotationComment = a.comment;
    ann.annotationColor = a.color;
    ann.annotationPageLabel = a.pageLabel;
    ann.annotationSortIndex = a.sortIndex;
    let pos = Object.assign({{}}, a.position);
    if (type === "note") {{ delete pos.fontSize; delete pos.rotation; let r = pos.rects[0]; pos.rects = [[r[0], r[3] - 22, r[0] + 22, r[3]]]; }}
    ann.annotationPosition = JSON.stringify(pos);
    ann.setTags([{{tag: TAG}}]);
    await ann.save();
    created[type]++;
  }}
  for (let a of old) await a.erase();
}});
if (trash.length) await Zotero.Items.trashTx(trash);
return "removed " + old.length + " old annotations (kept " + kept + " of yours); note: " + (NOTE_HTML ? (noteCreated ? "created" : noteSame ? "the same text exists already" : "not created") : "none") +
  (trash.length ? "; " + trash.length + " earlier notes of the tool moved to the trash" : "") +
  "; created " + created.highlight + " highlights, " + (created.underline ? created.underline + " underlines, " : "") + created.text + " margin texts" + (created.note ? ", " + created.note + " sticky notes" : "") + ". Close and reopen the PDF to see them.";
"""


# ---------------------------------------------------------------------------
# Profile: derive the user's annotation habits from their own library (read-only)
# ---------------------------------------------------------------------------
def _cjk_ratio(s):
    return sum(1 for c in s if "一" <= c <= "鿿") / max(1, len(s))


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def layout_habits(own):
    """Placement habits of the user's text and sticky-note annotations, from their positions.

    The local API reports no page sizes, so the top region is taken as y1 >= 670 pt (the top 15 % of a Letter page
    and the top 20 % of an A4 page) and the page centre as x = 300 pt. A page-top note is a text annotation in that
    region at least 250 pt wide. Annotations at least 250 pt wide are bands spanning the text column rather than
    margin notes, so they do not vote on the preferred margin side.
    """
    texts, sides, sizes, top = 0, [], [], 0
    for d in own:
        kind = d.get("annotationType")
        if kind not in ("text", "note"):
            continue
        pos = parse_position(d.get("annotationPosition"))
        rects = [r for r in (pos.get("rects") or []) if len(r) == 4]
        if not rects:
            continue
        x0, y0, x1, y1 = [float(v) for v in rects[0]]
        if x1 - x0 < 250:
            sides.append("left" if (x0 + x1) / 2 < 300 else "right")
        if kind == "text":
            texts += 1
            if pos.get("fontSize"):
                sizes.append(float(pos["fontSize"]))
            if y1 >= 670 and x1 - x0 >= 250:
                top += 1
    left = sides.count("left") / max(1, len(sides))
    side = "mixed" if len(sides) < 3 or 0.25 < left < 0.75 else ("left" if left >= 0.75 else "right")
    return {"page_top_notes": round(top / max(1, texts), 2), "margin_side": side,
            "text_font_size_median": _median(sizes) if sizes else None}


def profile_from_library(exclude_author=""):
    """Read every annotation and child note made by the user (excluding those created by this tool) and summarise the habits."""
    s, h, t = http("GET", "/api/users/0/items?itemType=annotation&limit=100000", timeout=180)
    if s != 200:
        raise RuntimeError(f"cannot read annotations (HTTP {s}); is Zotero running?")
    rows = json.loads(t)
    own = []
    for r in rows:
        d = r["data"]
        tags = {x["tag"] for x in d.get("tags", [])}
        if (tags & OWN_TAGS) or (exclude_author and d.get("annotationAuthorName") == exclude_author):
            continue
        own.append(d)
    n = len(own)
    by_type = collections.Counter(d["annotationType"] for d in own)
    by_color = collections.Counter(d.get("annotationColor") for d in own)
    comments = [(d.get("annotationComment") or "") for d in own]
    with_c = [c for c in comments if c.strip()]
    label_colon = sum(1 for c in with_c if re.match(r"^[^：:\n]{1,10}[：:]", c))
    listy = sum(1 for c in with_c if re.search(r"(^|\n)\s*(\d+[.、)]|[-•*])\s", c))
    multiline = sum(1 for c in with_c if "\n" in c)
    colors = []
    for col, cnt in by_color.most_common():
        if cnt / max(1, n) < 0.03 and len(colors) >= 2:
            break
        xs = [d for d in own if d.get("annotationColor") == col]
        cs = [(d.get("annotationComment") or "").strip() for d in xs]
        cs = [c for c in cs if c]
        colors.append({"color": col, "share": round(cnt / max(1, n), 3), "count": cnt,
                       "types": dict(collections.Counter(d["annotationType"] for d in xs)),
                       "comment_rate": round(len(cs) / max(1, len(xs)), 2),
                       "comment_len_median": _median([len(c) for c in cs]),
                       "sample_comments": [re.sub(r"\s*\n\s*", " / ", c)[:80] for c in cs[:4]],
                       "sample_texts": [(d.get("annotationText") or "")[:80] for d in xs if d.get("annotationText")][:3]})
    per_att = collections.Counter(d["parentItem"] for d in own)
    # child notes, excluding those created by this tool and the "Comment:" stubs Zotero imports from PDF files
    s2, h2, t2 = http("GET", "/api/users/0/items?itemType=note&limit=100000", timeout=180)
    notes = []
    if s2 == 200:
        for r in json.loads(t2):
            d = r["data"]
            if not d.get("parentItem") or ({x["tag"] for x in d.get("tags", [])} & OWN_TAGS):
                continue
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", d.get("note", ""))).strip()
            if txt.startswith("Comment:") and len(txt) < 120:
                continue
            notes.append(txt)
    long_notes = [x for x in notes if len(x) >= 300]
    lang = "zh" if with_c and _median([_cjk_ratio(c) for c in with_c]) > 0.3 else "en"
    prof = {
        "source": "library",
        "annotations_analysed": n,
        "language": lang,
        "types": {k: round(v / max(1, n), 3) for k, v in by_type.items()},
        "uses_underline": by_type.get("underline", 0) / max(1, n) > 0.05,
        "uses_margin_text": by_type.get("text", 0) / max(1, n) > 0.05,
        "uses_sticky_notes": by_type.get("note", 0) / max(1, n) > 0.05,
        "comment_rate": round(len(with_c) / max(1, n), 2),
        "comment_len_median": _median([len(c) for c in with_c]),
        "comment_style": {"label_colon_rate": round(label_colon / max(1, len(with_c)), 2),
                          "list_rate": round(listy / max(1, len(with_c)), 2),
                          "multiline_rate": round(multiline / max(1, len(with_c)), 2)},
        "colors": colors,
        "annotations_per_paper_median": _median(list(per_att.values())),
        "annotated_papers": len(per_att),
        "child_notes": {"count": len(notes), "long_notes": len(long_notes), "len_median": _median([len(x) for x in notes])},
        "levels": {("level%d" % (i + 1)): c["color"] for i, c in enumerate(colors[:3])},
        "layout": layout_habits(own),
    }
    return prof


def profile_markdown(p):
    """Render the statistics as a Markdown draft for the assistant to interpret and the user to correct."""
    L = []
    L.append("# Annotation profile (draft derived from the Zotero library)")
    L.append(f"\nBased on {p['annotations_analysed']} annotations on {p['annotated_papers']} papers, "
             f"{p['annotations_per_paper_median']} per annotated paper (median). Correct any statement that does not apply.\n")
    L.append(f"- Language of comments: **{p['language']}**")
    kinds = ", ".join(f"{k} {int(v*100)}%" for k, v in sorted(p["types"].items(), key=lambda x: -x[1]))
    L.append(f"- Annotation kinds used: {kinds}")
    L.append(f"- Margin text annotations: {'yes' if p['uses_margin_text'] else 'rarely'}; underline: "
             f"{'yes' if p['uses_underline'] else 'rarely'}; sticky notes: {'yes' if p['uses_sticky_notes'] else 'rarely'}")
    L.append(f"- Comments on {int(p['comment_rate']*100)}% of annotations, median {p['comment_len_median']} characters; "
             f"label-colon style {int(p['comment_style']['label_colon_rate']*100)}%, lists {int(p['comment_style']['list_rate']*100)}%, "
             f"multi-line {int(p['comment_style']['multiline_rate']*100)}%")
    L.append("- Colours:")
    for c in p["colors"]:
        ex = "; ".join(c["sample_comments"][:2]) or "—"
        L.append(f"  - `{c['color']}` {int(c['share']*100)}% ({', '.join(f'{k} {v}' for k, v in c['types'].items())}); "
                 f"comments on {int(c['comment_rate']*100)}%, e.g. {ex}")
    cn = p["child_notes"]
    L.append(f"- Child notes: {cn['count']} ({cn['long_notes']} longer than 300 characters); reading notes: "
             f"{'yes' if cn['long_notes'] >= 3 else 'not a habit'}")
    lay = p.get("layout")
    if lay:
        size = f"{lay['text_font_size_median']} pt" if lay.get("text_font_size_median") else "unknown"
        L.append(f"- Placement: page-top notes on {int(lay['page_top_notes'] * 100)}% of text annotations; margin side: {lay['margin_side']}; "
                 f"text font size (median): {size}")
    L.append("\n## Interpretation (to be completed by the assistant from the statistics and confirmed by the user)\n")
    L.append("- colour meanings: " + ", ".join(f"`{c['color']}` = ___" for c in p["colors"]))
    L.append("- highlight comments contain: ___ (translation / why it matters / a question / nothing)")
    L.append("- colour levels to use for new annotations: " + ", ".join(f"{k} = `{v}` = ___" for k, v in p["levels"].items()))
    L.append(f"- margin text: {'yes' if p['uses_margin_text'] else 'no'}; voice: ___")
    L.append("- page-top summary: ___ (yes / no; a text annotation across the top of page 1)")
    L.append("- margin side: ___ (auto / left / right)")
    L.append("- sticky notes instead of margin text: ___ (yes / no)")
    L.append(f"- reading note: {'yes' if cn['long_notes'] >= 3 else 'no'}; structure: ___")
    L.append("- tone: ___ (first person or impersonal; whether doubts are recorded; terse labels or full sentences)")
    return "\n".join(L) + "\n"


USER_RULES_MARK = "## User's rules (always win)"
USER_RULES_TEMPLATE = f"""{USER_RULES_MARK}

Rules recorded in this section take precedence over the learned statistics above. Re-running
`profile --from-library` regenerates the sections above and leaves this section unchanged.

- (none yet; add rules here, e.g. "comments are translations", "two colours only: red = core, yellow = other",
  "a three-sentence summary at the top of page 1 of every paper", "margin notes on the right, 9 pt")
"""


INTERPRETATION_MARK = "## Interpretation"


def merge_profile_md(learned_md, existing_md):
    """Replace only the statistics section; preserve the edited interpretation and the user's rules."""
    if existing_md and USER_RULES_MARK in existing_md:
        keep_from = existing_md.index(INTERPRETATION_MARK) if INTERPRETATION_MARK in existing_md else existing_md.index(USER_RULES_MARK)
        stats_only = learned_md[:learned_md.index(INTERPRETATION_MARK)] if INTERPRETATION_MARK in learned_md else learned_md
        return stats_only.rstrip() + "\n\n" + existing_md[keep_from:].rstrip() + "\n"
    return learned_md.rstrip() + "\n\n" + USER_RULES_TEMPLATE


def profile_main(argv):
    ap = argparse.ArgumentParser(prog="scholium profile", description="Derive an annotation profile from the user's own Zotero annotations (read-only).")
    ap.add_argument("--from-library", action="store_true", help="analyse the library of the running Zotero instance")
    ap.add_argument("--exclude-author", default="", help="annotationAuthorName whose annotations are excluded from the analysis (e.g. the name of an automated tool)")
    ap.add_argument("--path", action="store_true", help="print the path of profile.md and exit (no library access)")
    ap.add_argument("--json", action="store_true", help="with --path: print the data directory, the path and whether the file exists as JSON")
    ap.add_argument("--data-dir", default=None, help="Zotero data directory (default: ZOTERO_DATA_DIR, Zotero's prefs.js, or ~/Zotero)")
    ap.add_argument("--out", default=None, help="directory for profile.json and profile.md (default: <Zotero data dir>/zotero-scholium/)")
    a = ap.parse_args(argv)
    cfg = {"data_dir": a.data_dir} if a.data_dir else None
    out = a.out or profile_dir(cfg)
    md_path = os.path.join(out, "profile.md")
    legacy_md = os.path.join(legacy_profile_dir(), "profile.md")
    if a.path:
        if a.json:
            print(json.dumps({"data_dir": zotero_data_dir(cfg), "profile_md": md_path, "exists": os.path.exists(md_path),
                              "legacy_profile_md": legacy_md if os.path.exists(legacy_md) else None}, ensure_ascii=False, indent=1))
        else:
            print(md_path)
            if not os.path.exists(md_path):
                print("(the file does not exist yet; run `scholium profile --from-library`)", file=sys.stderr)
        return
    if not a.from_library:
        ap.error("use --from-library to derive the profile, or --path to print its location")
    try:
        prof = profile_from_library(a.exclude_author)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=1))
        return 1
    os.makedirs(out, exist_ok=True)
    json.dump(prof, open(os.path.join(out, "profile.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    migrated = None
    if os.path.exists(md_path):
        existing = open(md_path, encoding="utf8").read()
    elif os.path.exists(legacy_md):
        existing = open(legacy_md, encoding="utf8").read()   # keep the interpretation and the user's rules
        migrated = legacy_md
    else:
        existing = ""
    open(md_path, "w", encoding="utf8").write(merge_profile_md(profile_markdown(prof), existing))
    report = {"written": [os.path.join(out, "profile.json"), md_path], "summary": {
        k: prof[k] for k in ("annotations_analysed", "language", "types", "comment_rate", "comment_len_median", "comment_style", "levels", "child_notes", "layout")}}
    if migrated:
        report["migrated_from"] = migrated
    print(json.dumps(report, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------------------
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


BRIDGE_FIRST = (0, 1, 9)   # from this plugin version on, `auto` writes through the plugin: one transaction, keys returned


def _version(text):
    return tuple(int(x) for x in re.findall(r"\d+", str(text or ""))[:3])


def pick_backend(requested, cfg):
    """Return (name, handle, reason). `auto` takes the scholium-bridge plugin when it is recent enough, else the
    local API on Zotero 10, else an older plugin. When `auto` falls back to the JavaScript file, the reason names
    why each write channel was unavailable."""
    bridge = bridge_connect(cfg) if requested in ("auto", "bridge") else None
    if requested == "auto" and bridge[0] and isinstance(bridge[1], dict) and _version(bridge[1].get("version")) >= BRIDGE_FIRST:
        return "bridge", bridge[0], f"scholium-bridge plugin {bridge[1]['version']}"
    ver, sid = zotero_version() if requested in ("auto", "api") else (None, None)
    why_not = []
    if requested in ("auto", "api"):
        if ver and sid:
            try:
                major = int(ver.split(".")[0])
            except ValueError:
                major = 0
            if major >= 10:
                return "api", LocalApi(sid), f"Zotero {ver}: official local API write support"
            why_not.append(f"Zotero {ver}: the local API is read-only before Zotero 10")
        else:
            why_not.append("Zotero is not running or its local server is disabled")
        if requested == "api":
            return None, None, why_not[-1]
    if requested in ("auto", "bridge"):
        token, info = bridge
        if token:
            return "bridge", token, "scholium-bridge plugin"
        if requested == "bridge":
            return None, None, info
        if not any(str(info).startswith(w) for w in why_not):
            why_not.append(str(info))
    if requested in ("auto", "js"):
        return "js", None, ("no write channel available (" + "; ".join(why_not) + "); generated a Run-JavaScript file instead"
                            if requested == "auto" else "Run-JavaScript file requested")
    return None, None, "no backend available"


def _get(path):
    """A read of the local API (Zotero 7 and later), as JSON."""
    s, _, t = http("GET", "/api/users/0" + path)
    if s == 404:
        raise RuntimeError(f"GET {path}: HTTP 404: {NOT_IN_MY_LIBRARY}")
    if s != 200:
        raise RuntimeError(f"GET {path}: HTTP {s}: {t[:160]}" if s else "Zotero does not answer on 127.0.0.1:23119; is it running?")
    return json.loads(t)


def _own(row):
    return bool({t["tag"] for t in row["data"].get("tags", [])} & OWN_TAGS)


def _plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _paper(key):
    """The regular item and its PDF attachment rows, from an item key or a PDF attachment key."""
    row = _get(f"/items/{urllib.parse.quote(key)}")
    if row["data"]["itemType"] == "attachment":
        parent = row["data"].get("parentItem")
        if not parent:
            return None, [row], []
        item = _get(f"/items/{parent}")
    else:
        item = row
    kids = _get(f"/items/{item['key']}/children")
    pdfs = [k for k in kids if k["data"]["itemType"] == "attachment" and k["data"].get("contentType") == "application/pdf"]
    return item, pdfs, [k for k in kids if k["data"]["itemType"] == "note"]


VENUE_FIELDS = ("publicationTitle", "proceedingsTitle", "conferenceName", "bookTitle", "university", "repository", "publisher")


def citation(item):
    """The item's key, title and what a citation line needs: authors (the first twelve), date, venue, DOI and URL."""
    d = item["data"]
    people = [c.get("name") or " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x)
              for c in d.get("creators", []) if c.get("creatorType", "author") == "author"]
    out = {"key": item["key"], "title": d.get("title", "")[:200], "year": (d.get("date") or "")[:4],
           "authors": people[:12] + ([f"… {len(people) - 12} more"] if len(people) > 12 else []),
           "date": d.get("date", ""), "venue": next((d[f] for f in VENUE_FIELDS if d.get(f)), ""),
           "doi": d.get("DOI", ""), "url": d.get("url", "")}
    return {k: v for k, v in out.items() if v or k in ("key", "title")}


def paper_status(key):
    """What a paper already has: each PDF with its file and the annotations on it (the tool's own counted by type and
    colour, the user's counted), and the notes under the item (title, length, whether the tool wrote them)."""
    item, pdfs, notes = _paper(key)
    data_dir = zotero_data_dir()
    out = []
    for p in pdfs:
        d = p["data"]
        path = os.path.join(data_dir, "storage", p["key"], d["filename"]) if d.get("filename") else (d.get("path") or "")
        anns = _get(f"/items/{p['key']}/children?itemType=annotation")
        own = [a for a in anns if _own(a)]
        out.append({"key": p["key"], "file": path, "exists": bool(path) and os.path.exists(path),
                    "own": len(own), "others": len(anns) - len(own),
                    "own_by_type": dict(collections.Counter(a["data"]["annotationType"] for a in own)),
                    "own_by_color": dict(collections.Counter(a["data"].get("annotationColor") for a in own))})
    return {"item": citation(item) if item else None,
            "pdfs": out,
            "notes": [{"key": n["key"], "title": note_title_from_html(n["data"].get("note", ""))[:100], "own": _own(n),
                       "characters": len(_plain(n["data"].get("note", ""))), "modified": n["data"].get("dateModified", "")[:10]}
                      for n in notes],
            "profile": os.path.join(profile_dir(), "profile.md")}


def status_main(argv):
    """`scholium status KEY` prints what a paper already has, before a configuration is written: its PDF attachments
    with their files, the annotations on each, and the notes under the item. `scholium status --query WORDS` lists
    the matching items."""
    ap = argparse.ArgumentParser(prog="scholium status", description=status_main.__doc__)
    ap.add_argument("key", nargs="?", help="item key or PDF attachment key")
    ap.add_argument("--query", help="title words: list the matching items")
    a = ap.parse_args(argv)
    if not a.key and not a.query:
        ap.error("give a key or --query")
    try:
        if a.query:
            rows = _get(f"/items/top?q={urllib.parse.quote(a.query)}&limit=10")
            out = {"matches": [{"key": r["key"], "title": r["data"].get("title", "")[:150], "year": (r["data"].get("date") or "")[:4],
                                "type": r["data"]["itemType"]} for r in rows]}
        else:
            out = paper_status(a.key)
    except RuntimeError as e:
        out = {"error": str(e)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 1 if "error" in out else 0


def paper_samples(item, pdfs, notes, per_kind):
    """A few of the tool's annotations on one paper and the start of its reading note, evenly spread over the paper."""
    anns = []
    for p in pdfs:
        anns += [a for a in _get(f"/items/{p['key']}/children?itemType=annotation") if _own(a)]
    anns.sort(key=lambda a: a["data"].get("annotationSortIndex", ""))

    def spread(rows):     # first, last and evenly between
        if len(rows) <= per_kind or per_kind < 2:
            return rows[:per_kind]
        return [rows[round(i * (len(rows) - 1) / (per_kind - 1))] for i in range(per_kind)]
    highlights = [a for a in anns if a["data"]["annotationType"] in ("highlight", "underline") and a["data"].get("annotationComment")]
    texts = [a for a in anns if a["data"]["annotationType"] in ("text", "note")]
    note = max((n for n in notes if _own(n)), key=lambda n: n["data"].get("dateModified", ""), default=None)
    return {"item": item["key"] if item else None, "title": (item or {}).get("data", {}).get("title", "")[:120],
            "highlights": [{"page": a["data"].get("annotationPageLabel"), "color": a["data"].get("annotationColor"),
                            "text": (a["data"].get("annotationText") or "")[:160], "comment": a["data"]["annotationComment"][:240]}
                           for a in spread(highlights)],
            "margin_and_page_texts": [{"page": a["data"].get("annotationPageLabel"), "text": (a["data"].get("annotationComment") or "")[:240]}
                                      for a in spread(texts)],
            "note_start": _plain(note["data"].get("note", ""))[:700] if note else None}


def samples_main(argv):
    """`scholium samples` prints short examples of the tool's earlier annotations in this library, as a reference
    for their style: for each paper a few highlights with their comments, margin and page texts, and the start of the
    reading note. Without keys it takes the papers annotated most recently."""
    ap = argparse.ArgumentParser(prog="scholium samples", description=samples_main.__doc__)
    ap.add_argument("keys", nargs="*", help="item or PDF attachment keys")
    ap.add_argument("--query", help="title words of the papers to take")
    ap.add_argument("--exclude", action="append", default=[], help="an item or attachment key to leave out (the paper being annotated)")
    ap.add_argument("--papers", type=int, default=2, help="how many papers (default 2)")
    ap.add_argument("--per-kind", type=int, default=4, help="examples of each kind per paper (default 4)")
    a = ap.parse_args(argv)
    try:
        keys = list(a.keys)
        if a.query:
            keys += [r["key"] for r in _get(f"/items/top?q={urllib.parse.quote(a.query)}&limit=10")]
        if not keys:     # the attachments of the most recently changed annotations of the tool, a page at a time
            for start in range(0, 2000, 100):
                rows = _get(f"/items?itemType=annotation&tag={TAG}&sort=dateModified&direction=desc&limit=100&start={start}")
                keys = list(dict.fromkeys(keys + [r["data"]["parentItem"] for r in rows if r["data"].get("parentItem")]))
                if len(rows) < 100 or len(set(keys) - set(a.exclude)) > a.papers:
                    break
        out, seen = [], set(a.exclude)
        for key in keys:
            if len(out) >= a.papers:
                break
            item, pdfs, notes = _paper(key)
            ident = {item["key"] if item else None} | {p["key"] for p in pdfs}
            if ident & seen:
                continue
            seen |= ident
            sample = paper_samples(item, pdfs, notes, a.per_kind)
            if sample["highlights"] or sample["margin_and_page_texts"] or sample["note_start"]:
                out.append(sample)
        result = {"papers": out}
    except RuntimeError as e:
        result = {"error": str(e)}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 1 if "error" in result else 0


ADVISORY_STYLE = {"core_count"}   # style warnings that inform without blocking --apply
CONFIG_KEYS = set(DEFAULTS) | {"pdf", "item_key", "attachment_key", "out_dir", "highlights", "summaries", "data_dir", "snap"}
HIGHLIGHT_KEYS = {"id", "ids", "page", "text", "occurrence", "core", "level", "color", "comment", "type"}
SUMMARY_KEYS = {"id", "page", "anchor", "text", "place", "side", "kind", "color", "font_size", "rect", "occurrence"}


def config_problems(raw):
    """Mistakes a run would otherwise pass over in silence or end on with a traceback: unknown keys (a misspelt
    "cleanup" keeps its default), an unknown level, a colour that is not #rrggbb, a highlight without a sentence id or
    a page with text, ids out of order, a highlight type other than highlight or underline, and missing required keys."""
    if not isinstance(raw, dict):
        return ["the configuration must be a JSON object"]
    problems = []

    def unknown(keys, allowed, where):
        for k in keys:
            if k not in allowed:
                near = difflib.get_close_matches(k, sorted(allowed), n=1)
                problems.append(f"unknown key {k!r}{where}" + (f" (did you mean {near[0]!r}?)" if near else ""))
    if "author" in raw:
        problems.append("the 'author' key is not supported")
    unknown([k for k in raw if k != "author"], CONFIG_KEYS, "")
    for k in ("pdf", "item_key", "attachment_key", "out_dir"):
        if not raw.get(k):
            problems.append(f"missing required key: {k}")
    if "band_min_font_size" in raw:
        v = raw["band_min_font_size"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 4 <= v <= 36:
            problems.append("band_min_font_size must be a number between 4 and 36")
    def whole(v, low=1):
        return isinstance(v, int) and not isinstance(v, bool) and v >= low

    def colour(v):
        return isinstance(v, str) and HEX_COLOR_RE.match(v)

    levels = raw.get("levels") or {}
    if not isinstance(levels, dict):
        problems.append("levels must map names to #rrggbb colours")
        levels = {}
    for name, v in levels.items():
        if not colour(v):
            problems.append(f"levels: {name!r} must be a #rrggbb colour")
    for k in ("core_color", "other_color", "text_color"):
        if k in raw and not colour(raw[k]):
            problems.append(f"{k} must be a #rrggbb colour")
    for i, h in enumerate(raw.get("highlights") or []):
        if not isinstance(h, dict):
            problems.append(f"highlights[{i}] must be an object")
            continue
        at = f"highlights[{i}]"
        unknown(h, HIGHLIGHT_KEYS, f" in {at}")
        if "id" in h and not whole(h["id"]):
            problems.append(f"{at}: id must be a sentence number")
        elif "ids" in h and not (isinstance(h["ids"], list) and len(h["ids"]) == 2 and all(whole(v) for v in h["ids"])
                                 and h["ids"][0] <= h["ids"][1]):
            problems.append(f"{at}: ids must be [first, last], two sentence numbers in order")
        elif "id" not in h and "ids" not in h:
            if not whole(h.get("page")):
                problems.append(f"{at}: give id, ids, or a 1-based page with text")
            if not (isinstance(h.get("text"), str) and h["text"].strip()):
                problems.append(f"{at}: give id, ids, or text with its page")
        if "occurrence" in h and h["occurrence"] is not None and not whole(h["occurrence"]):
            problems.append(f"{at}: occurrence must be a number from 1")
        if "comment" in h and not isinstance(h["comment"], str):
            problems.append(f"{at}: comment must be text")
        if "color" in h and not colour(h["color"]):
            problems.append(f"{at}: color must be a #rrggbb colour")
        if "level" in h and h["level"] not in levels:
            problems.append(f"{at}: unknown level {h['level']!r} (levels: {', '.join(levels) or 'none defined'})")
        if h.get("type", "highlight") not in ("highlight", "underline"):
            problems.append(f"{at}: type must be highlight or underline")
    for i, s in enumerate(raw.get("summaries") or []):
        if isinstance(s, dict):
            unknown(s, SUMMARY_KEYS, f" in summaries[{i}]")
    return problems


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "profile":
        return profile_main(argv[1:])
    if argv and argv[0] == "extract":
        return extract_main(argv[1:])
    if argv and argv[0] == "status":
        sys.exit(status_main(argv[1:]))
    if argv and argv[0] == "samples":
        sys.exit(samples_main(argv[1:]))
    ap = argparse.ArgumentParser(prog="scholium", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="path of the JSON configuration file (see references/configuration.md in the skill)")
    ap.add_argument("--apply", action="store_true", help="write the annotations into Zotero using the backend selected by --backend")
    ap.add_argument("--list", action="store_true", help="list the attachment's current annotations and notes without writing")
    ap.add_argument("--full", action="store_true", help="with --list: print every annotation with text, comment and position")
    ap.add_argument("--backend", default="auto", choices=["auto", "api", "bridge", "js"])
    ap.add_argument("--allow-missed", action="store_true", help="apply even if some phrases could not be located in the PDF")
    ap.add_argument("--allow-warnings", action="store_true", help="apply even if style or layout warnings are reported")
    ap.add_argument("--accept", default="", metavar="KIND[,KIND]",
                    help="apply despite style warnings of these kinds (e.g. user_overlap) and, with \"layout\", despite layout warnings")
    ap.add_argument("--ignore-existing", action="store_true",
                    help="do not read the attachment's existing annotations before laying out margin notes (they may then be "
                         "overlapped); --apply refuses it with cleanup: true")
    ap.add_argument("--version", action="version", version=f"scholium {__version__}")
    args = ap.parse_args(argv)
    try:
        raw = json.loads(read_text(args.config))
    except (OSError, ValueError) as e:
        sys.exit(f"config error: {e}")
    problems = config_problems(raw)
    if problems:
        sys.exit("config error: " + "; ".join(problems))
    cfg = dict(DEFAULTS); cfg.update(raw)
    if pymupdf is None and not args.list:
        sys.exit(PYMUPDF_MISSING)

    if args.list:
        name, handle, why = pick_backend(args.backend if args.backend != "js" else "auto", cfg)
        try:
            if name == "api":
                res, err = api_list(cfg, handle), None
            elif name == "bridge":
                res, err = bridge_list(cfg)
            else:
                res, err = None, why
        except Exception as e:
            res, err = None, str(e)
        print(json.dumps((res if args.full else compact_listing(res)) if res else {"error": err}, ensure_ascii=False, indent=1))
        sys.exit(0 if res else 1)

    obstacles, existing_info, listing, unread = {}, "not consulted (--ignore-existing)", None, None
    if not args.ignore_existing:
        name, handle, why = pick_backend(args.backend if args.backend != "js" else "auto", cfg)
        try:
            if name == "api":
                listing = api_list(cfg, handle)
            elif name == "bridge":
                listing, err = bridge_list(cfg)
                why = err or why
        except Exception as e:
            listing, why = None, str(e)
        if listing:
            obstacles = existing_obstacles(listing, keep_own=not cfg.get("cleanup", False))
            existing_info = {"annotations_in_zotero": len(listing["annotations"]),
                             "avoided_rects": sum(len(v) for v in obstacles.values())}
        else:
            existing_info = f"unavailable ({why}); existing annotations were not taken into account"
            if name in ("api", "bridge"):   # a write channel that cannot list: --apply could write a second copy
                unread = why
    pdf_before = _sha256(cfg["pdf"])
    out, missed = build(cfg, obstacles)
    json.dump(out, open(os.path.join(cfg["out_dir"], "annotations.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    js_path = os.path.join(cfg["out_dir"], "create_annotations.js")
    open(js_path, "w", encoding="utf8").write(render_js(cfg, out))
    by_type = collections.Counter(a["type"] for a in out)
    note_html = read_text(cfg["note_html"]) if cfg.get("note_html") else None
    own_now = [a for a in (listing or {}).get("annotations", []) if set(a.get("tags") or []) & OWN_TAGS]
    report = {"highlights": by_type.get("highlight", 0), "underlines": by_type.get("underline", 0),
              "margin_texts": by_type.get("text", 0), "sticky_notes": by_type.get("note", 0),
              "colors": dict(collections.Counter(a["color"] for a in out if a["type"] in ("highlight", "underline"))),
              "cleanup_removes": (len(own_now) if listing else None) if cfg.get("cleanup") else 0,
              "missed": missed, "translation_warnings": check_translations(out),
              "style_warnings": check_style(out, cfg, listing, note_html),
              "snapped": [{"page": a["pageLabel"], "text": a["text"][:60], "similarity": a["snapped"]} for a in out if a.get("snapped")],
              "ambiguous_matches": [{"page": a["pageLabel"], "text": (a.get("text") or a.get("comment", ""))[:60], "occurrences": a["occurrences"], "used": 1} for a in out if a.get("occurrences")],
              "layout_warnings": [{"page": a["pageLabel"], "text": a["comment"][:60], "reason": a["layout_warning"]} for a in out if a.get("layout_warning")],
              "fitted": [{"page": a["pageLabel"], "text": a["comment"][:60], "font_size": f"{a['fitted']['from']:g} -> {a['fitted']['to']:g}"}
                         for a in out if a.get("fitted")],
              "as_notes": [{"page": a["pageLabel"], "text": a["comment"][:60]} for a in out if a.get("as_note")],
              "existing_annotations": existing_info, "js": js_path}
    previews = [os.path.join(cfg["out_dir"], f"preview_p{p}.png") for p in cfg["preview_pages"]]
    previews = [path for path in previews if os.path.exists(path)]   # pages outside the document are not rendered
    if previews:
        report["previews"] = previews

    if args.apply:
        accepted = {k.strip() for k in args.accept.split(",") if k.strip()}
        blocking = [w for w in report["style_warnings"] if w["kind"] not in accepted | ADVISORY_STYLE]
        blockers = []
        if missed and not args.allow_missed:
            blockers.append("some phrases could not be located; correct them or pass --allow-missed")
        if blocking and not args.allow_warnings:
            blockers.append("style warnings are reported (" + ", ".join(sorted({w["kind"] for w in blocking})) +
                            "); correct them, or accept a deliberate exception with --accept KIND")
        if report["layout_warnings"] and not args.allow_warnings and "layout" not in accepted:
            blockers.append("layout warnings are reported; move, shorten or drop those notes, or pass --accept layout")
        if args.ignore_existing and cfg.get("cleanup"):
            blockers.append("--ignore-existing cannot be combined with cleanup: true; run without --ignore-existing")
        if unread:
            blockers.append(f"the annotations already on the attachment could not be read ({unread}); run again when Zotero "
                            "answers" + ("" if cfg.get("cleanup") else ", or pass --ignore-existing"))
        if blockers:
            report["applied"] = False
            report["apply_error"] = "; ".join(blockers)
        else:
            name, handle, why = pick_backend(args.backend, cfg)
            report["backend"] = name; report["backend_reason"] = why
            res, err = None, why
            try:
                if name == "api":
                    res = api_apply(cfg, out, handle)
                elif name == "bridge":
                    res, err = bridge_apply(cfg, out)
            except Exception as e:
                res, err = None, str(e)
            report["applied"] = False
            if res is not None:
                report["result"] = res
                if res.get("createdKeys") or res.get("noteKeys"):   # the keys go to a file; the report keeps counts
                    keys_path = os.path.join(cfg["out_dir"], "applied_keys.json")
                    json.dump({"createdKeys": res.get("createdKeys", []), "noteKeys": res.get("noteKeys", [])},
                              open(keys_path, "w", encoding="utf8"), indent=1)
                    report["result"] = dict({k: v for k, v in res.items() if k not in ("createdKeys", "noteKeys")}, keys=keys_path)
            if res and res.get("ok"):
                try:
                    lst = api_list(cfg, handle) if name == "api" else bridge_list(cfg)[0]
                    if not lst:
                        raise RuntimeError("read-back unavailable")
                    report["now_in_zotero"] = {"annotations": len(lst["annotations"]), "notes": [n["title"][:70] for n in lst["notes"]]}
                    if "createdKeys" in res:   # the local API and plugins from 0.1.9 on return the new keys
                        ann_keys = {a["key"] for a in lst["annotations"]}
                        note_keys = {n["key"] for n in lst["notes"]}
                        verification = {"missing_annotations": sorted(set(res["createdKeys"]) - ann_keys),
                                        "missing_notes": sorted(set(res.get("noteKeys", [])) - note_keys)}
                        report["verification"] = verification
                        if any(verification.values()):
                            raise RuntimeError("new items are missing from read-back")
                    report["applied"] = True
                except Exception as e:
                    report["apply_error"] = f"write returned success, but verification failed: {e}; inspect --list before retrying"
                if res.get("removeError"):   # the new items are written; earlier ones are still there
                    report["applied"] = "partial" if report["applied"] else False
                    removal = (f"the new items were written, but removing the earlier ones failed: {res['removeError']}; "
                               "run --list to see what is stored before running again")
                    report["apply_error"] = report["apply_error"] + "; " + removal if "apply_error" in report else removal
            else:
                report["apply_error"] = (res.get("error") or "some items could not be created; inspect result.failed and --list before retrying") if res else err
                if name == "js":
                    report["fallback"] = "execute the generated file in Zotero: Tools -> Developer -> Run JavaScript (Run as async function): " + js_path
    pdf_after = _sha256(cfg["pdf"])
    report["pdf_sha256"] = {"before": pdf_before, "after": pdf_after, "unchanged": pdf_before == pdf_after}
    for key in ("applied", "apply_error", "fallback"):   # the outcome comes last, where the end of the output shows it
        if key in report:
            report[key] = report.pop(key)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if missed or (args.apply and report.get("applied") is not True):
        sys.exit(2)


if __name__ == "__main__":
    sys.exit(main())
