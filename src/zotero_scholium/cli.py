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

Backends (--backend auto selects the first available one):
  api     official local API of Zotero 10 and later (no plugin; one confirmation dialog on first use)
  bridge  the bundled scholium-bridge plugin (Zotero 7 to 9)
  js      a "Run JavaScript" file for manual execution in Zotero (last resort)

Requires: pip install pymupdf
Usage:    scholium --config config.json [--apply] [--list] [--backend auto|api|bridge|js]
          scholium extract --pdf paper.pdf
          scholium profile --from-library
"""
import argparse
import difflib, glob, hashlib, json, os, sys, re, datetime, collections
import urllib.request, urllib.error
import pymupdf

__version__ = "0.1.0"

TAG = "zotero-scholium"     # tag applied to every annotation and note created by this tool
LEGACY_TAGS = {"zotero-marginalia", "zotero-paper-annotate"}   # tags written by earlier versions; still recognised as belonging to this tool
OWN_TAGS = {TAG} | LEGACY_TAGS
APP_NAME = "zotero-scholium"
BASE = "http://127.0.0.1:23119"

DEFAULTS = {
    "levels": {},               # named colour levels, e.g. {"claim": "#ff6666", "method": "#ffd400"}; referenced by "level" in highlights
    "core_color": "#ff6666",    # legacy two-level scheme: highlights carrying "core": true/false
    "other_color": "#ffd400",
    "text_color": "#1a73e8",
    "font_size": 8,
    "margin_side": "auto",      # margin used for summaries: "auto" (paragraph's side / wider margin), "left", "right"
    "summary_kind": "text",     # "text": visible margin text; "note": sticky notes (only when the user has that habit)
    "preview_pages": [1],
    "note_title": None,
    "note_title_prefix": None,
    "note_html": None,
    "note_replace": False,      # Destructive: deletes existing child notes whose title starts with note_title_prefix.
                                # By default existing notes are preserved and a new note receives a versioned title.
    "cleanup": True,            # False: keep every existing annotation on the attachment (the tool's own included); only add
    "cleanup_external": False,  # bridge backend only: additionally delete annotations Zotero imported from the PDF file
    "core_range": None,         # [low, high]: expected number of highlights in core_color; outside it a style warning is reported
    "banned_phrases": [],       # strings that must not occur in comments, margin texts or the note (reported as style warnings)
    "sentences": None,          # sentences.json written by `extract --sentences` (default: <out_dir>/sentences.json)
}

# ---------------------------------------------------------------------------
# Text matching and layout (the PDF is only read)
# ---------------------------------------------------------------------------
LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "’": "'", "‘": "'", "“": '"', "”": '"'}
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")     # the reader accepts <b> <i> <sub> <sup> in comments
MATH_RE = re.compile(r"\$\$[^$]*\$\$|\$[^$\n]+\$|\\\([^()]*\\\)|\\[a-zA-Z]+")
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


class PageIndex:
    """Word-level index of one page together with an approximate model of its column geometry."""

    def __init__(self, page, doc_bounds=None):
        self.page = page
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

    def text_line_rects(self):
        """Rectangles (PDF space, y upward) of the page's horizontal text lines. Lines written in another
        direction (vertical preprint stamps in the margin) are dropped."""
        rects = []
        for block in self.page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                dx, dy = line.get("dir", (1, 0))
                if abs(dx - 1) > 0.01 or abs(dy) > 0.01:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                if x1 - x0 <= 0 or y1 - y0 <= 0 or not "".join(s.get("text", "") for s in line.get("spans", [])).strip():
                    continue
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
    return {"page": page, "text": text, "place": place, "side": side, "kind": kind, "color": color,
            "font_size": font_size, "rect": rect, "anchor": anchor,
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
    room the block keeps its requested position and is marked with `layout_warning`.
    """
    occ = sorted(occupied)

    def hits(y_top, h):
        return [iv for iv in occ if y_top - h < iv[1] + gap and y_top > iv[0] - gap]

    for b in sorted(blocks, key=lambda b: -b["y_top"]):
        h = b["h"]
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
            b["layout_warning"] = "no free space in the margin beside this paragraph; the box may overlap an existing annotation or a figure"
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
    return ann


def layout_page_summaries(pi, specs, page_obstacles, missed):
    """Lay out one page's summaries and return their annotations.

    Order: explicit rectangles (never moved; an overlap is only reported), then top/bottom bands across the text
    column, then margin boxes and sticky notes beside their anchors. Every placed box joins the obstacle set of the
    following groups. Bands avoid the page's text lines; margin boxes lie outside the text column by construction.
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
    for sp in [s for s in specs if not s["rect"] and s["kind"] == "text" and s["place"] in ("top", "bottom")]:
        h = _box_height(sp, bx1 - bx0)
        occ = [(r[1], r[3]) for r in occupied + text_lines if r[0] < bx1 and r[2] > bx0]
        if sp["place"] == "top":
            blk = {"y_top": pi.H - BAND_MARGIN, "h": h}
            place_blocks([blk], occ, floor=0.7 * pi.H, ceiling=pi.H - BAND_MARGIN)
            warn = "no free space at the top of the page; shorten the text or use place: bottom"
        else:
            # the footer (page number, running line) is any text line inside the column within 8 % of the page bottom;
            # the band goes between the text and the footer, or, when that gap is too small, beneath the footer
            footer = [r for r in text_lines if r[0] < bx1 and r[2] > bx0 and r[3] < 0.08 * pi.H]
            footer_top = max((r[3] for r in footer), default=0.0)
            blk = {"y_top": max(BAND_MARGIN, footer_top + 3.0) + h, "h": h}
            place_blocks([blk], occ + ([(0.0, footer_top)] if footer else []), floor=BAND_MARGIN, ceiling=0.3 * pi.H)
            if blk.get("layout_warning") and footer:
                below = {"y_top": BAND_MARGIN + h, "h": h}
                place_blocks([below], occ, floor=BAND_MARGIN, ceiling=min(r[1] for r in footer) - 3.0)
                if not below.get("layout_warning"):
                    blk = below
            warn = "no free space at the bottom of the page; shorten the text or use place: top"
        rect = [bx0, blk["y_top"] - h, bx1, blk["y_top"]]
        anns.append(_summary_annotation(pi, sp, rect, warn if blk.get("layout_warning") else None)); occupied.append(rect)
    # 3. margin boxes and sticky notes beside their anchors (a sticky note ignores `place`)
    groups = {}
    for sp in [s for s in specs if not s["rect"] and (s["kind"] == "note" or s["place"] == "margin")]:
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
        mx0, mx1 = pi.margin_box(r, sp["side"])
        if sp["kind"] == "note":  # the icon hugs the text column
            mx0, mx1 = (mx1 - NOTE_ICON, mx1) if mx1 <= pi.body_x0 else (mx0, mx0 + NOTE_ICON)
        groups.setdefault((mx0, mx1), []).append(({"y_top": pi.H - r.y0 + 1, "h": _box_height(sp, mx1 - mx0)}, sp))
    for (mx0, mx1), items in groups.items():
        occ = [(r[1], r[3]) for r in occupied if r[0] < mx1 and r[2] > mx0]
        place_blocks([b for b, _ in items], occ, floor=28.0, ceiling=pi.H - 20.0)
        for b, sp in items:
            rect = [mx0, b["y_top"] - b["h"], mx1, b["y_top"]]
            anns.append(_summary_annotation(pi, sp, rect, b.get("layout_warning"))); occupied.append(rect)
    return anns


def build(cfg, obstacles=None):
    """Convert the configuration into annotation objects with PDF-space coordinates and render preview PNGs.

    `obstacles` maps a page index to rectangles already occupied by other annotations (see
    existing_obstacles); margin boxes are laid out around them and around the page's figures.
    """
    doc = pymupdf.open(cfg["pdf"])
    bounds = column_bounds(doc)
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
        except (KeyError, ValueError, TypeError, FileNotFoundError) as e:
            missed.append({"kind": kind, "id": item.get("id", item.get("ids")), "reason": str(e).strip("'")})
            return None
        text = " ".join(r["text"] for r in recs)
        fields = {"page": recs[0]["page"], "text" if kind == "highlight" else "anchor": text, "_from_id": True}
        if len(recs) == 1 and not item.get("occurrence"):
            fields["occurrence"] = recs[0]["occurrence"]
        return dict(item, **fields)

    for h in cfg.get("highlights", []):
        h = resolve(h, "highlight")
        if h is None:
            continue
        p = int(h["page"]) - 1
        pi = page_index(p)
        occ = int(h.get("occurrence") or 0) or None   # 1-based; None: the first occurrence, ambiguity is reported
        ws, reason, snapped = pi.match(h["text"], occ or 1), None, None
        if not ws and h.get("_from_id") and len(h["text"].split()) > 10:
            words = h["text"].split()                # a sentence from the extraction: anchor on its ends
            ws, reason = pi.match_range(" ".join(words[:5]), " ".join(words[-5:]), occurrence=occ)
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
        rects = [[round(r.x0, 2), round(pi.H - r.y1, 2), round(r.x1, 2), round(pi.H - r.y0, 2)] for r in pi.line_rects(ws)]
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
    page_sizes = [(pg.rect.width, pg.rect.height) for pg in doc]
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
        pi = page_index(p)
        # existing annotations and figures are occupied space for every summary on the page
        page_obstacles = list((obstacles or {}).get(p, [])) + page_figure_rects(doc[p])
        out.extend(layout_page_summaries(pi, page_specs, page_obstacles, missed))
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
    doc.close()  # the document is never saved; the PDF file remains unchanged
    return out, missed


CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def _tokens(s):
    """Latin words (3+ characters) and numbers, lower-cased; hyphenation across lines is joined first,
    and both the joined form and its two halves count as terms."""
    s = "".join(LIG.get(c, c) for c in s)  # expand ligatures so that "preﬁx" and "prefix" are the same term
    toks = set()
    for m in re.finditer(r"([A-Za-z]{2,})-\s+([A-Za-z]{2,})", s):
        toks.update(part.lower() for part in m.groups() if len(part) >= 3)
    s = re.sub(r"(\w)-\s+(\w)", r"\1\2", s).lower()
    for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s):
        if len(t) >= 3 or any(c.isdigit() for c in t):
            toks.add(t)
    return toks


def _covered(tok, text_tokens):
    """A comment token is covered if it, a prefix/extension of it, or its digit skeleton appears in the source text."""
    if tok in text_tokens or tok + "s" in text_tokens or tok + "es" in text_tokens or tok.rstrip("s") in text_tokens:
        return True
    if any(c.isdigit() for c in tok):
        d = re.sub(r"[^0-9]", "", tok)
        for u in text_tokens:
            du = re.sub(r"[^0-9]", "", u)
            if d and du and (d == du or d.startswith(du) or du.startswith(d)):
                return True
        return False
    return any(len(tok) >= 4 and (u.startswith(tok) or tok.startswith(u)) and min(len(u), len(tok)) >= 4 for u in text_tokens)


def check_translations(annotations):
    """Heuristic fidelity check: a highlight comment must translate the highlighted span only.

    Two signals are reported as warnings (never as errors): numbers or Latin terms that occur in the
    comment but not in the highlighted text (content added from outside the span), and a CJK-characters-
    per-English-word ratio far outside the usual range (a comment much longer or shorter than the span
    it translates). The caller decides how to act on them.
    """
    warnings = []
    for a in annotations:
        if a.get("type") not in ("highlight", "underline") or not a.get("comment"):
            continue
        text, comment = a["text"], a["comment"]
        plain = TAG_RE.sub(" ", MATH_RE.sub(" ", comment))  # rich-text tags and mathematics are display, not content
        text_tokens = _tokens(text)
        extra = sorted(t for t in _tokens(plain) if not _covered(t, text_tokens))
        words = len(re.findall(r"[A-Za-z]+", text))
        cjk = len(CJK_RE.findall(plain))
        reasons = []
        if extra:
            reasons.append("terms or numbers not present in the highlighted text: " + ", ".join(extra))
        if cjk and words >= 6:
            ratio = cjk / words
            if ratio > 2.8:
                reasons.append(f"comment is long for the span ({ratio:.1f} characters per word); it may translate more than what is highlighted")
            elif ratio < 0.8:
                reasons.append(f"comment is short for the span ({ratio:.1f} characters per word); it may omit part of the sentence")
        if reasons:
            warnings.append({"page": a["pageLabel"], "text": text[:80], "comment": comment[:80], "reasons": reasons})
    return warnings


STYLE_SYMBOL_RE = re.compile(r"[→←↑↓⇒①-⑳【】]")            # arrows, circled numbers, bracket tags
LABEL_RE = re.compile(r"^[^：:，,。.]{1,12}[：:]\s*\S")         # "label: content" at the start of a margin note
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


def _text_defects(s):
    """(kind, reason) pairs for display defects in a comment or margin text."""
    found = []
    if MATH_RE.search(s):
        found.append(("latex", "raw LaTeX; write mathematics with Unicode symbols and <sub>/<sup>"))
    if MATH_FORMAT_RE.search(s):
        found.append(("math_format", "exponent or subscript written with ^, _{ or a bare minus; use <sup>/<sub>"))
    tags = [m.group(1).lower() for m in re.finditer(r"</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>", s)]
    bad = sorted(set(tags) - READER_TAGS)
    if bad:
        found.append(("tag", "tags the reader does not render: " + ", ".join(bad)))
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
    own earlier ones excepted unless `cleanup` is false), the number of core-coloured highlights against
    `core_range`, and mathematics in the note (a double backslash inside a math node, LaTeX outside one).
    """
    warnings = []
    existing = _existing_rects(listing, keep_own=not cfg.get("cleanup", True))
    banned = [b for b in (cfg.get("banned_phrases") or []) if b]
    marks = [a for a in annotations if a["type"] in ("highlight", "underline")]

    def warn(kind, a, reason):
        label = a.get("text") if a["type"] in ("highlight", "underline") else a.get("comment", "")
        warnings.append({"kind": kind, "page": a["pageLabel"], "text": (label or "")[:60], "reason": reason})

    for a in annotations:
        is_mark = a["type"] in ("highlight", "underline")
        comment = a.get("comment", "")
        for kind, reason in _text_defects(comment):
            warn(kind, a, reason)
        if not is_mark and LABEL_RE.match(comment):
            warn("label", a, "label-colon form; write a sentence")
        if not is_mark and STYLE_SYMBOL_RE.search(comment):
            warn("symbol", a, "arrows, circled numbers or bracket tags; write a sentence")
        hits = [b for b in banned if b in TAG_RE.sub("", comment)]
        if hits:
            warn("banned_phrase", a, "contains: " + ", ".join(hits))
        if is_mark:
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


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
PAGE_NUM_RE = re.compile(r"^(?:\d{1,4}|[ivxlcdm]{1,7})$", re.I)


def extract_paragraphs(pdf_path, pages=None, keep_references=False):
    """[(page number, [(kind, text), ...]), ...] with kind "heading", "para" or "marker".

    Lines are de-hyphenated and ligatures expanded with the same rules the matcher uses, so a phrase
    copied from this output matches. Running headers and footers (lines recurring on most pages) and
    standalone page numbers are dropped; the bibliography between the References heading and the next
    heading (judged by font size and weight) is replaced by a marker line unless keep_references is set."""
    doc = pymupdf.open(pdf_path)
    sel = list(range(len(doc))) if not pages else [p - 1 for p in pages if 1 <= p <= len(doc)]
    page_rows, weighted = [], []
    for p in sel:
        rows = []
        for bi, block in enumerate(doc[p].get_text("dict").get("blocks", [])):
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
    out, in_refs = [], False
    for p, rows in zip(sel, page_rows):
        paras = []
        for i, (blk, t, size, bold) in enumerate(rows):
            n = norm_str(t)
            if PAGE_NUM_RE.match(t) or ((i < 3 or i >= len(rows) - 3) and n in recurring):
                continue
            if not keep_references:
                if not in_refs and n in ("references", "bibliography"):
                    in_refs = True
                    paras.append([None, "[references removed]", "marker"])
                    continue
                if in_refs:
                    if n.startswith(("appendix", "supplementary")) or heading(t, size, bold):
                        in_refs = False           # the bibliography ends at the next heading
                    else:
                        continue
            t = "".join(LIG.get(c, c) for c in t)
            kind = "heading" if heading(t, size, bold) else "para"
            if paras and paras[-1][0] == blk and kind == "para" and paras[-1][2] == "para":
                prev = paras[-1][1]
                paras[-1][1] = prev[:-1] + t if prev.endswith("-") and t[:1].islower() else prev + " " + t
            else:
                paras.append([blk, t, kind])
        out.append((p + 1, [(kind, re.sub(r"([A-Za-z])-\s+([a-z])", r"\1\2", t)) for _, t, kind in paras]))
    return out


def extract_text(pdf_path, pages=None, keep_references=False):
    """The paper's text with page markers, one paragraph per line (see extract_paragraphs)."""
    return "\n\n".join(f"--- p.{p} ---\n" + "\n".join(t for _, t in paras)
                       for p, paras in extract_paragraphs(pdf_path, pages, keep_references)) + "\n"


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
    {"page", "para", "heading"}; a marker is {"page", "para", "marker"}."""
    items, sid, para = [], 0, 0
    for p, paras in extract_paragraphs(pdf_path, pages, keep_references):
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
    return items


def render_sentences(items):
    """The listing an agent reads: page markers, `## heading` lines, `id | sentence` lines, blank lines between paragraphs."""
    out, page, para = [], None, None
    for it in items:
        if it["page"] != page:
            if out:
                out.append("")
            out.append(f"--- p.{it['page']} ---"); page, para = it["page"], None
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
    """{id: sentence} from the sentences file, each with its occurrence among identical sentences on its page."""
    path = cfg.get("sentences") or os.path.join(cfg["out_dir"], "sentences.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"sentences file not found: {path} (run `scholium extract --sentences`)")
    data = json.load(open(path, encoding="utf8"))
    seen, table = collections.Counter(), {}
    for it in data.get("sentences", []):
        if "id" not in it:
            continue
        key = (it["page"], norm_str(it["text"]))
        seen[key] += 1
        table[int(it["id"])] = dict(it, occurrence=seen[key])
    return table


def extract_main(argv):
    ap = argparse.ArgumentParser(prog="scholium extract",
                                 description="Print the PDF's text with page markers, de-hyphenated, without running headers, footers, page numbers and the bibliography.")
    ap.add_argument("--pdf", help="path of the PDF (default: the \"pdf\" key of --config)")
    ap.add_argument("--config", help="JSON configuration file to take the pdf path from")
    ap.add_argument("--out", help="write to this file instead of standard output")
    ap.add_argument("--pages", help="page or page range, e.g. 3 or 1-8 (default: all pages)")
    ap.add_argument("--keep-references", action="store_true", help="keep the bibliography")
    ap.add_argument("--sentences", metavar="JSON", help="write numbered sentences to this JSON file and print the numbered listing instead of plain text")
    args = ap.parse_args(argv)
    pdf = args.pdf or (json.load(open(args.config, encoding="utf8")).get("pdf") if args.config else None)
    if not pdf:
        sys.exit("extract: give --pdf or --config")
    pages = None
    if args.pages:
        m = re.match(r"^(\d+)(?:-(\d+))?$", args.pages)
        if not m:
            sys.exit("extract: --pages takes N or N-M")
        pages = list(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
    if args.sentences:
        items = extract_sentences(pdf, keep_references=args.keep_references)   # ids count over the whole document
        n = sum(1 for it in items if "id" in it)
        json.dump({"pdf": pdf, "sentences": [it for it in items if "id" in it],
                   "headings": [it for it in items if "id" not in it]}, open(args.sentences, "w", encoding="utf8"), ensure_ascii=False, indent=0)
        text = render_sentences([it for it in items if not pages or it["page"] in pages])
        summary = f"{n} sentences -> {args.sentences}"
    else:
        text = extract_text(pdf, pages=pages, keep_references=args.keep_references)
        summary = f"{len(text)} characters"
    if args.out:
        open(args.out, "w", encoding="utf8").write(text)
        print(f"{args.out}: {summary}")
    else:
        print(text)
    return 0


def http(method, path, body=None, headers=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode("utf8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf8", "ignore")
    except Exception as e:
        return 0, {}, str(e)


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

    def write(self, method, path, body=None, extra=None):
        """Write request with automatic (re)authorization on 401."""
        s = h = t = None
        for attempt in range(2):
            if not self.key:
                self.authorize()
            hdr = {"Zotero-Server-ID": self.server_id, "Zotero-API-Key": self.key}
            hdr.update(extra or {})
            s, h, t = http(method, path, body, hdr, timeout=120)
            if s == 401 and attempt == 0:
                self.key = None
                self.keys.pop(self.server_id, None)
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
            raise RuntimeError(f"failed to read children (HTTP {s}): {t[:200]}")
        return json.loads(t)

    def create(self, items):
        created, failed = [], []
        for i in range(0, len(items), 50):
            s, h, t = self.write("POST", "/api/users/0/items", items[i:i + 50])
            if s != 200:
                raise RuntimeError(f"create failed (HTTP {s}): {t[:300]}")
            d = json.loads(t)
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


def parse_position(value):
    """annotationPosition arrives as a JSON string from the local API and as an object from the bridge plugin."""
    try:
        return json.loads(value) if isinstance(value, str) else (value or {})
    except ValueError:
        return {}


def api_list(cfg, api):
    rows = api.children(cfg["attachment_key"], "annotation")
    anns = [{"key": r["key"], "type": r["data"]["annotationType"], "color": r["data"].get("annotationColor"),
             "author": r["data"].get("annotationAuthorName", ""), "tags": [t["tag"] for t in r["data"].get("tags", [])],
             "pageLabel": r["data"].get("annotationPageLabel"), "text": (r["data"].get("annotationText") or "")[:80],
             "comment": (r["data"].get("annotationComment") or "")[:80],
             "position": parse_position(r["data"].get("annotationPosition"))} for r in rows]
    notes = []
    if cfg.get("item_key"):
        for c in api.children(cfg["item_key"]):
            if c["data"]["itemType"] == "note":
                notes.append({"key": c["key"], "title": note_title_from_html(c["data"].get("note", ""))})
    return {"ok": True, "backend": "api", "attachmentKey": cfg["attachment_key"], "annotations": anns, "notes": notes}


def api_apply(cfg, out, api):
    mine_content = set(a["comment"] for a in out) | set(a["text"] for a in out if a.get("text"))
    # (0) cleanup: only annotations carrying the tool's tag or identical content;
    #     skipped entirely with "cleanup": false
    rows = api.children(cfg["attachment_key"], "annotation") if cfg.get("cleanup", True) else []
    to_delete, kept = [], 0
    for r in rows:
        d = r["data"]
        tags = {t["tag"] for t in d.get("tags", [])}
        mine = bool(tags & OWN_TAGS) or \
               (d.get("annotationComment") or "") in mine_content or (d.get("annotationText") or "") in mine_content
        if mine:
            to_delete.append(r["key"])
        else:
            kept += 1
    removed = api.delete(to_delete) if to_delete else 0
    # (1) child note: existing notes are preserved; the title is versioned if a note with the same prefix exists
    note_created, notes_removed = False, 0
    if cfg.get("note_html") and cfg.get("item_key"):
        html = open(cfg["note_html"], encoding="utf8").read()
        prefix = cfg.get("note_title_prefix") or cfg.get("note_title") or ""
        existing = [c for c in api.children(cfg["item_key"]) if c["data"]["itemType"] == "note"]
        titles = [note_title_from_html(c["data"].get("note", "")) for c in existing]
        if cfg.get("note_replace") and prefix:
            victims = [c["key"] for c, t in zip(existing, titles) if t.startswith(prefix)]
            notes_removed = api.delete(victims) if victims else 0
            titles = []
        html, _ = version_note(html, prefix, titles)
        api.create([{"itemType": "note", "parentItem": cfg["item_key"], "note": html, "tags": [{"tag": TAG}]}])
        note_created = True
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
    counts = {}
    for a in out:
        counts[a["type"]] = counts.get(a["type"], 0) + 1
    return {"ok": True, "backend": "api", "removed": removed, "kept": kept, "noteCreated": note_created,
            "notesRemoved": notes_removed,
            "created": counts if not failed else {"created_keys": len(created_keys), "failed": failed}}


# ---------------------------------------------------------------------------
# Backend 2: scholium-bridge plugin (Zotero 7 to 9)
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
    return token, json.loads(t) if t.startswith("{") else {}


def bridge_list(cfg):
    token, info = bridge_connect(cfg)
    if not token:
        return None, info
    s, h, t = http("POST", "/scholium-bridge/list", {"attachmentKey": cfg["attachment_key"]}, {"X-Annotate-Token": token})
    res = json.loads(t) if s == 200 else {}
    if not res.get("ok"):
        return None, "list failed (HTTP %s): %s" % (s, t[:200])
    res["backend"] = "bridge"
    return res, None


def bridge_apply(cfg, out):
    token, info = bridge_connect(cfg)
    if not token:
        return None, info
    html = open(cfg["note_html"], encoding="utf8").read() if cfg.get("note_html") else None
    prefix = cfg.get("note_title_prefix") or cfg.get("note_title") or ""
    if html and not cfg.get("note_replace"):
        lst, _ = bridge_list(cfg)
        if lst:
            html, prefix = version_note(html, prefix, [n["title"] for n in lst.get("notes", [])])
    payload = {"itemKey": cfg["item_key"], "attachmentKey": cfg["attachment_key"],
               "cleanup": bool(cfg.get("cleanup", True)), "cleanupExternal": bool(cfg.get("cleanup_external")), "tag": TAG, "legacyTags": sorted(LEGACY_TAGS), "annotations": out,
               "note": {"html": html, "titlePrefix": prefix, "replace": bool(cfg.get("note_replace", False))} if html else None}
    s, h, t = http("POST", "/scholium-bridge/apply", payload, {"X-Annotate-Token": token}, timeout=180)
    res = json.loads(t) if s == 200 else {}
    if not res.get("ok"):
        return None, "apply failed (HTTP %s): %s" % (s, t[:200])
    res["backend"] = "bridge"
    return res, None


# ---------------------------------------------------------------------------
# Backend 3: "Run JavaScript" file (manual execution)
# ---------------------------------------------------------------------------
def render_js(cfg, out):
    html = open(cfg["note_html"], encoding="utf8").read() if cfg.get("note_html") else None
    title_prefix = cfg.get("note_title_prefix") or cfg.get("note_title") or ""
    n_h = sum(1 for a in out if a["type"] in ("highlight", "underline")); n_t = len(out) - n_h
    return f"""// Usage: in Zotero, open Tools -> Developer -> Run JavaScript, enable "Run as async function",
// paste the entire content of this file, and click Run.
// Effect (all changes are made in the Zotero database; the PDF file is not modified):
//   (0) {'delete annotations previously created by this tool on the attachment (tag "' + TAG + '" or identical content);' if cfg.get('cleanup', True) else 'keep every existing annotation (cleanup disabled);'}
//   (1) {"create a child note (if a note with the same title exists, the new note receives a versioned title; no note is deleted);" if html else "(no child note in this run)"}
//   (2) create {n_h} highlight/underline annotations and {n_t} margin text annotations.
var ITEM_KEY = {json.dumps(cfg['item_key'])}, ATT_KEY = {json.dumps(cfg['attachment_key'])}, TAG = {json.dumps(TAG)};
var OWN_TAGS = {json.dumps(sorted(OWN_TAGS))};
var CLEANUP = {json.dumps(bool(cfg.get('cleanup', True)))};
var NOTE_HTML = {json.dumps(html, ensure_ascii=False)};
var NOTE_TITLE_PREFIX = {json.dumps(title_prefix, ensure_ascii=False)};
var ANNOTATIONS = {json.dumps(out, ensure_ascii=False)};

var libraryID = Zotero.Libraries.userLibraryID;
var parent = Zotero.Items.getByLibraryAndKey(libraryID, ITEM_KEY);
var att = Zotero.Items.getByLibraryAndKey(libraryID, ATT_KEY);
if (!parent) throw new Error("item not found: " + ITEM_KEY);
if (!att) throw new Error("attachment not found: " + ATT_KEY);

var MINE = new Set(ANNOTATIONS.map(a => a.comment).concat(ANNOTATIONS.filter(a => a.text).map(a => a.text)));
var removed = 0, kept = 0;
for (let a of (CLEANUP ? att.getAnnotations(true) : [])) {{
  let tags = a.getTags().map(t => t.tag);
  let mine = tags.some(t => OWN_TAGS.includes(t)) ||
             MINE.has(a.annotationComment) || (a.annotationText && MINE.has(a.annotationText));
  if (mine) {{ await a.eraseTx(); removed++; }} else {{ kept++; }}
}}

var noteCreated = false;
if (NOTE_HTML) {{
  let existing = Zotero.Items.get(parent.getNotes()).map(n => n.getNoteTitle());
  let same = existing.filter(t => t && NOTE_TITLE_PREFIX && t.startsWith(NOTE_TITLE_PREFIX));
  let html = NOTE_HTML;
  if (same.length) {{
    let d = new Date(), ds = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    html = html.replace(/<h1([^>]*)>([\\s\\S]*?)<\\/h1>/i, (m, attrs, t) => "<h1" + attrs + ">" + t.replace(/\\s*\\(v\\d+, \\d{{4}}-\\d{{2}}-\\d{{2}}\\)\\s*$/, "") + " (v" + (same.length + 1) + ", " + ds + ")</h1>");
  }}
  let note = new Zotero.Item("note");
  note.libraryID = libraryID;
  note.parentID = parent.id;
  note.setNote(html);
  note.setTags([{{tag: TAG}}]);
  await note.saveTx();
  noteCreated = true;
}}

var created = {{highlight: 0, text: 0, note: 0}};
await Zotero.DB.executeTransaction(async function () {{
  for (let a of ANNOTATIONS) {{
    let ann = new Zotero.Item("annotation");
    ann.libraryID = libraryID;
    ann.parentID = att.id;
    let type = a.type;
    try {{ ann.annotationType = type; }}
    catch (e) {{ type = "note"; ann.annotationType = type; }}  // Zotero without text annotations: fall back to a sticky note
    if (type === "highlight") ann.annotationText = a.text;
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
}});
return "removed " + removed + " old annotations (kept " + kept + " of yours); note: " + (NOTE_HTML ? (noteCreated ? "created" : "not created") : "none") +
  "; created " + created.highlight + " highlights, " + created.text + " margin texts" + (created.note ? ", " + created.note + " sticky notes" : "") + ". Close and reopen the PDF to see them.";
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
    ap.add_argument("--path", action="store_true", help="print the resolved profile location and exit (no library access)")
    ap.add_argument("--data-dir", default=None, help="Zotero data directory (default: ZOTERO_DATA_DIR, Zotero's prefs.js, or ~/Zotero)")
    ap.add_argument("--out", default=None, help="directory for profile.json and profile.md (default: <Zotero data dir>/zotero-scholium/)")
    a = ap.parse_args(argv)
    cfg = {"data_dir": a.data_dir} if a.data_dir else None
    out = a.out or profile_dir(cfg)
    md_path = os.path.join(out, "profile.md")
    legacy_md = os.path.join(legacy_profile_dir(), "profile.md")
    if a.path:
        print(json.dumps({"data_dir": zotero_data_dir(cfg), "profile_md": md_path, "exists": os.path.exists(md_path),
                          "legacy_profile_md": legacy_md if os.path.exists(legacy_md) else None}, ensure_ascii=False, indent=1))
        return
    if not a.from_library:
        ap.error("use --from-library to derive the profile, or --path to print its location")
    prof = profile_from_library(a.exclude_author)
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


def pick_backend(requested, cfg):
    """Return (name, handle, reason)."""
    ver, sid = zotero_version()
    if requested in ("auto", "api"):
        if ver and sid:
            try:
                major = int(ver.split(".")[0])
            except ValueError:
                major = 0
            if major >= 10:
                return "api", LocalApi(sid), f"Zotero {ver}: official local API write support"
            if requested == "api":
                return None, None, f"Zotero {ver}: the local API is read-only before Zotero 10"
        elif requested == "api":
            return None, None, "Zotero is not running or its local server is disabled"
    if requested in ("auto", "bridge"):
        token, info = bridge_connect(cfg)
        if token:
            return "bridge", token, "scholium-bridge plugin"
        if requested == "bridge":
            return None, None, info
    if requested in ("auto", "js"):
        return "js", None, "no write channel available; generated a Run-JavaScript file instead" if requested == "auto" else "Run-JavaScript file requested"
    return None, None, "no backend available"


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
    ap = argparse.ArgumentParser(prog="scholium", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="path of the JSON configuration file (see README)")
    ap.add_argument("--apply", action="store_true", help="write the annotations into Zotero using the backend selected by --backend")
    ap.add_argument("--list", action="store_true", help="list the attachment's current annotations and notes without writing")
    ap.add_argument("--full", action="store_true", help="with --list: print every annotation with text, comment and position")
    ap.add_argument("--backend", default="auto", choices=["auto", "api", "bridge", "js"])
    ap.add_argument("--allow-missed", action="store_true", help="apply even if some phrases could not be located in the PDF")
    ap.add_argument("--allow-warnings", action="store_true", help="apply even if style warnings are reported")
    ap.add_argument("--ignore-existing", action="store_true",
                    help="do not read the attachment's existing annotations before laying out margin notes (they may then be overlapped)")
    ap.add_argument("--version", action="version", version=f"scholium {__version__}")
    args = ap.parse_args(argv)
    raw = json.load(open(args.config, encoding="utf8"))
    if "author" in raw:
        sys.exit("config error: the 'author' key is not supported")
    cfg = dict(DEFAULTS); cfg.update(raw)
    for k in ("pdf", "item_key", "attachment_key", "out_dir"):
        if not cfg.get(k):
            sys.exit(f"config missing required key: {k}")

    if args.list:
        name, handle, why = pick_backend(args.backend if args.backend != "js" else "auto", cfg)
        if name == "api":
            res, err = api_list(cfg, handle), None
        elif name == "bridge":
            res, err = bridge_list(cfg)
        else:
            res, err = None, why
        print(json.dumps((res if args.full else compact_listing(res)) if res else {"error": err}, ensure_ascii=False, indent=1))
        sys.exit(0 if res else 1)

    obstacles, existing_info, listing = {}, "not consulted (--ignore-existing)", None
    if not args.ignore_existing:
        name, handle, why = pick_backend(args.backend if args.backend != "js" else "auto", cfg)
        listing = api_list(cfg, handle) if name == "api" else (bridge_list(cfg)[0] if name == "bridge" else None)
        if listing:
            obstacles = existing_obstacles(listing, keep_own=not cfg.get("cleanup", True))
            existing_info = {"annotations_in_zotero": len(listing["annotations"]),
                             "avoided_rects": sum(len(v) for v in obstacles.values())}
        else:
            existing_info = f"unavailable ({why}); existing annotations were not taken into account"
    pdf_before = _sha256(cfg["pdf"])
    out, missed = build(cfg, obstacles)
    json.dump(out, open(os.path.join(cfg["out_dir"], "annotations.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    js_path = os.path.join(cfg["out_dir"], "create_annotations.js")
    open(js_path, "w", encoding="utf8").write(render_js(cfg, out))
    by_type = collections.Counter(a["type"] for a in out)
    note_html = open(cfg["note_html"], encoding="utf8").read() if cfg.get("note_html") else None
    report = {"highlights": by_type.get("highlight", 0), "underlines": by_type.get("underline", 0),
              "margin_texts": by_type.get("text", 0), "sticky_notes": by_type.get("note", 0),
              "colors": dict(collections.Counter(a["color"] for a in out if a["type"] in ("highlight", "underline"))),
              "missed": missed, "translation_warnings": check_translations(out),
              "style_warnings": check_style(out, cfg, listing, note_html),
              "snapped": [{"page": a["pageLabel"], "text": a["text"][:60], "similarity": a["snapped"]} for a in out if a.get("snapped")],
              "ambiguous_matches": [{"page": a["pageLabel"], "text": (a.get("text") or a.get("comment", ""))[:60], "occurrences": a["occurrences"], "used": 1} for a in out if a.get("occurrences")],
              "layout_warnings": [{"page": a["pageLabel"], "text": a["comment"][:60], "reason": a["layout_warning"]} for a in out if a.get("layout_warning")],
              "existing_annotations": existing_info, "js": js_path,
              "previews": [os.path.join(cfg["out_dir"], f"preview_p{p}.png") for p in cfg["preview_pages"]]}

    if args.apply:
        blockers = []
        if missed and not args.allow_missed:
            blockers.append("some phrases could not be located; correct them or pass --allow-missed")
        if report["style_warnings"] and not args.allow_warnings:
            blockers.append("style warnings are reported; correct them or pass --allow-warnings")
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
            if res:
                report["applied"] = True
                report["result"] = res
                lst = api_list(cfg, handle) if name == "api" else bridge_list(cfg)[0]
                if lst:
                    report["now_in_zotero"] = {"annotations": len(lst["annotations"]), "notes": [n["title"][:70] for n in lst["notes"]]}
            else:
                report["applied"] = False
                report["apply_error"] = err
                report["fallback"] = "execute the generated file in Zotero: Tools -> Developer -> Run JavaScript (Run as async function): " + js_path
    pdf_after = _sha256(cfg["pdf"])
    report["pdf_sha256"] = {"before": pdf_before, "after": pdf_after, "unchanged": pdf_before == pdf_after}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if missed or (args.apply and not report.get("applied")):
        sys.exit(2)


if __name__ == "__main__":
    main()
