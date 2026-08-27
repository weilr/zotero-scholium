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
          scholium profile --from-library
"""
import argparse, json, os, sys, re, datetime, collections
import urllib.request, urllib.error
import pymupdf

__version__ = "0.1.0"

TAG = "zotero-scholium"     # tag applied to every annotation and note created by this tool
LEGACY_TAGS = {"zotero-marginalia", "zotero-paper-annotate"}   # tags written by earlier versions; still recognised as belonging to this tool
OWN_TAGS = {TAG} | LEGACY_TAGS
APP_NAME = "zotero-scholium"
BASE = "http://127.0.0.1:23119"

DEFAULTS = {
    "author": "",               # annotationAuthorName shown in the reader; empty: annotations appear as the user's own
    "levels": {},               # named colour levels, e.g. {"claim": "#ff6666", "method": "#ffd400"}; referenced by "level" in highlights
    "core_color": "#ff6666",    # legacy two-level scheme: highlights carrying "core": true/false
    "other_color": "#ffd400",
    "text_color": "#1a73e8",
    "font_size": 8,
    "preview_pages": [1],
    "note_title": None,
    "note_title_prefix": None,
    "note_html": None,
    "note_replace": False,      # Destructive: deletes existing child notes whose title starts with note_title_prefix.
                                # By default existing notes are preserved and a new note receives a versioned title.
    "cleanup": True,            # False: keep every existing annotation on the attachment (the tool's own included); only add
    "cleanup_external": False,  # bridge backend only: additionally delete annotations Zotero imported from the PDF file
}

# ---------------------------------------------------------------------------
# Text matching and layout (the PDF is only read)
# ---------------------------------------------------------------------------
LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "’": "'", "‘": "'", "“": '"', "”": '"'}


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

    def match(self, phrase):
        key = norm_str(phrase)
        pos = self.text.find(key)
        if pos < 0:
            return None
        idxs = sorted(set(self.wmap[pos:pos + len(key)]))
        return [self.words[i] for i in idxs]

    @staticmethod
    def line_rects(ws):
        lines = {}
        for w in ws:
            k = (w[5], w[6]); r = pymupdf.Rect(w[0], w[1], w[2], w[3])
            lines[k] = lines[k] | r if k in lines else r
        return [lines[k] for k in sorted(lines)]

    def margin_box(self, para_rect):
        """(x0, x1) of the margin box beside a paragraph: its own side in two-column layouts, the wider margin otherwise."""
        left_w = self.body_x0 - 8
        right_w = self.W - self.body_x1 - 8
        use_left = (para_rect.x0 < self.W / 2) if self.two_col else (left_w >= right_w)
        if use_left:
            return 4.0, max(4.0 + 30, self.body_x0 - 4)
        return min(self.W - 4 - 30, self.body_x1 + 4), self.W - 4


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

    fs = float(cfg["font_size"]); line_h = fs * 1.5
    out, missed = [], []
    for h in cfg.get("highlights", []):
        p = int(h["page"]) - 1
        pi = page_index(p)
        ws = pi.match(h["text"])
        if not ws:
            missed.append({"kind": "highlight", "page": p + 1, "text": h["text"][:60]}); continue
        rects = [[round(r.x0, 2), round(pi.H - r.y1, 2), round(r.x1, 2), round(pi.H - r.y0, 2)] for r in pi.line_rects(ws)]
        top = int(round(pi.H - rects[0][3]))
        # colour precedence: explicit "color", then named "level" (resolved through cfg["levels"]), then legacy core/other
        color = h.get("color") or cfg.get("levels", {}).get(h.get("level", ""), None) or \
                (cfg["core_color"] if h.get("core") else cfg["other_color"])
        out.append({"type": h.get("type", "highlight") if h.get("type") in ("highlight", "underline") else "highlight",
                    "color": color, "text": " ".join(w[4] for w in ws), "comment": h.get("comment", ""), "pageLabel": str(p + 1),
                    "sortIndex": f"{p:05d}|{0:06d}|{top:05d}", "position": {"pageIndex": p, "rects": rects}})
    groups = {}
    for s in cfg.get("summaries", []):
        p = int(s["page"]) - 1
        pi = page_index(p)
        ws = pi.match(s["anchor"])
        if not ws:
            missed.append({"kind": "summary", "page": p + 1, "anchor": s["anchor"]}); continue
        r = pi.line_rects(ws)[0]
        bx0, bx1 = pi.margin_box(r)
        lines = wrap(s["text"], (bx1 - bx0) - 3, fs)
        groups.setdefault((p, bx0, bx1), []).append({"y_top": pi.H - r.y0 + 1, "h": len(lines) * line_h + 6, "text": s["text"]})
    for (p, bx0, bx1), blocks in groups.items():
        pi = page_index(p)
        # existing annotations and figures that intrude into this margin become occupied intervals
        page_obstacles = list((obstacles or {}).get(p, [])) + page_figure_rects(doc[p])
        occupied = [(r[1], r[3]) for r in page_obstacles if r[0] < bx1 and r[2] > bx0]
        place_blocks(blocks, occupied, floor=28.0, ceiling=pi.H - 20.0)
        for b in blocks:
            rect = [round(bx0, 2), round(b["y_top"] - b["h"], 2), round(bx1, 2), round(b["y_top"], 2)]
            top = int(round(pi.H - b["y_top"]))
            ann = {"type": "text", "color": cfg["text_color"], "comment": b["text"], "pageLabel": str(p + 1),
                   "sortIndex": f"{p:05d}|{0:06d}|{top:05d}",
                   "position": {"pageIndex": p, "rects": [rect], "fontSize": fs, "rotation": 0}}
            if b.get("layout_warning"):
                ann["layout_warning"] = b["layout_warning"]
            out.append(ann)
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
            else:
                x0, y0, x1, y1 = a["position"]["rects"][0]
                fr = pymupdf.Rect(x0, H - y1, x1, H - y0)
                shape.draw_rect(fr); shape.finish(color=(0.8, 0.8, 0.9), width=0.3)
                for i, ln in enumerate(wrap(a["comment"], (x1 - x0) - 3, fs)):
                    shape.insert_text(pymupdf.Point(fr.x0 + 1.5, fr.y0 + (i + 1) * line_h), ln,
                                      fontsize=fs, fontname="china-s", color=rgb)
        shape.commit()
        page.get_pixmap(dpi=90).save(os.path.join(cfg["out_dir"], f"preview_p{p + 1}.png"))
    doc.close()  # the document is never saved; the PDF file remains unchanged
    return out, missed


CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def _tokens(s):
    """Latin words (3+ characters) and numbers, lower-cased; hyphenation across lines is joined first."""
    s = "".join(LIG.get(c, c) for c in s)  # expand ligatures so that "preﬁx" and "prefix" are the same term
    s = re.sub(r"(\w)-\s+(\w)", r"\1\2", s).lower()
    toks = set()
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
        text_tokens = _tokens(text)
        extra = sorted(t for t in _tokens(comment) if not _covered(t, text_tokens))
        words = len(re.findall(r"[A-Za-z]+", text))
        cjk = len(CJK_RE.findall(comment))
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
    author = cfg["author"]
    mine_content = set(a["comment"] for a in out) | set(a["text"] for a in out if a.get("text"))
    # (0) cleanup: only annotations carrying the tool's tag, the configured author name, or identical content;
    #     skipped entirely with "cleanup": false
    rows = api.children(cfg["attachment_key"], "annotation") if cfg.get("cleanup", True) else []
    to_delete, kept = [], 0
    for r in rows:
        d = r["data"]
        tags = {t["tag"] for t in d.get("tags", [])}
        mine = bool(tags & OWN_TAGS) or (author and d.get("annotationAuthorName") == author) or \
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
        if author:
            it["annotationAuthorName"] = author
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
def _data_dir_candidates(cfg):
    c = []
    if cfg and cfg.get("data_dir"):
        c.append(cfg["data_dir"])
    if cfg and cfg.get("pdf"):
        p = os.path.abspath(cfg["pdf"]).replace("\\", "/")
        if "/storage/" in p:
            c.append(p.split("/storage/")[0])
    c.append(os.path.join(os.path.expanduser("~"), "Zotero"))
    return c


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
    payload = {"itemKey": cfg["item_key"], "attachmentKey": cfg["attachment_key"], "author": cfg["author"],
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
//   (0) {'delete annotations previously created by this tool on the attachment (tag "' + TAG + '", author "' + cfg['author'] + '", or identical content);' if cfg.get('cleanup', True) else 'keep every existing annotation (cleanup disabled);'}
//   (1) {"create a child note (if a note with the same title exists, the new note receives a versioned title; no note is deleted);" if html else "(no child note in this run)"}
//   (2) create {n_h} highlight/underline annotations and {n_t} margin text annotations.
var ITEM_KEY = {json.dumps(cfg['item_key'])}, ATT_KEY = {json.dumps(cfg['attachment_key'])}, AUTHOR = {json.dumps(cfg['author'])}, TAG = {json.dumps(TAG)};
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
  let mine = tags.some(t => OWN_TAGS.includes(t)) || (AUTHOR && a.annotationAuthorName === AUTHOR) ||
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
    if (AUTHOR) ann.annotationAuthorName = AUTHOR;
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
    L.append("\n## Interpretation (to be completed by the assistant from the statistics and confirmed by the user)\n")
    L.append("- colour meanings: " + ", ".join(f"`{c['color']}` = ___" for c in p["colors"]))
    L.append("- highlight comments contain: ___ (translation / why it matters / a question / nothing)")
    L.append("- colour levels to use for new annotations: " + ", ".join(f"{k} = `{v}` = ___" for k, v in p["levels"].items()))
    L.append(f"- margin text: {'yes' if p['uses_margin_text'] else 'no'}; voice: ___")
    L.append(f"- reading note: {'yes' if cn['long_notes'] >= 3 else 'no'}; structure: ___")
    L.append("- tone: ___ (first person or impersonal; whether doubts are recorded; terse labels or full sentences)")
    return "\n".join(L) + "\n"


USER_RULES_MARK = "## User's rules (always win)"
USER_RULES_TEMPLATE = f"""{USER_RULES_MARK}

Rules recorded in this section take precedence over the learned statistics above. Re-running
`profile --from-library` regenerates the sections above and leaves this section unchanged.

- (none yet; add rules here, e.g. "comments are translations", "two colours only: red = core, yellow = other")
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
    ap.add_argument("--out", default=None, help="directory for profile.json and profile.md (default: the user configuration directory)")
    a = ap.parse_args(argv)
    if not a.from_library:
        ap.error("only --from-library is implemented")
    prof = profile_from_library(a.exclude_author)
    out = a.out or os.path.join(os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config"), "zotero-scholium")
    os.makedirs(out, exist_ok=True)
    json.dump(prof, open(os.path.join(out, "profile.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    md_path = os.path.join(out, "profile.md")
    existing = open(md_path, encoding="utf8").read() if os.path.exists(md_path) else ""
    open(md_path, "w", encoding="utf8").write(merge_profile_md(profile_markdown(prof), existing))
    print(json.dumps({"written": [os.path.join(out, "profile.json"), os.path.join(out, "profile.md")], "summary": {
        k: prof[k] for k in ("annotations_analysed", "language", "types", "comment_rate", "comment_len_median", "comment_style", "levels", "child_notes")}},
        ensure_ascii=False, indent=1))


# ---------------------------------------------------------------------------
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
    ap = argparse.ArgumentParser(prog="scholium", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="path of the JSON configuration file (see README)")
    ap.add_argument("--apply", action="store_true", help="write the annotations into Zotero using the backend selected by --backend")
    ap.add_argument("--list", action="store_true", help="list the attachment's current annotations and notes without writing")
    ap.add_argument("--backend", default="auto", choices=["auto", "api", "bridge", "js"])
    ap.add_argument("--allow-missed", action="store_true", help="apply even if some phrases could not be located in the PDF")
    ap.add_argument("--ignore-existing", action="store_true",
                    help="do not read the attachment's existing annotations before laying out margin notes (they may then be overlapped)")
    ap.add_argument("--version", action="version", version=f"scholium {__version__}")
    args = ap.parse_args(argv)
    cfg = dict(DEFAULTS); cfg.update(json.load(open(args.config, encoding="utf8")))
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
        print(json.dumps(res if res else {"error": err}, ensure_ascii=False, indent=1))
        sys.exit(0 if res else 1)

    obstacles, existing_info = {}, "not consulted (--ignore-existing)"
    if not args.ignore_existing:
        name, handle, why = pick_backend(args.backend if args.backend != "js" else "auto", cfg)
        listing = api_list(cfg, handle) if name == "api" else (bridge_list(cfg)[0] if name == "bridge" else None)
        if listing:
            obstacles = existing_obstacles(listing, keep_own=not cfg.get("cleanup", True))
            existing_info = {"annotations_in_zotero": len(listing["annotations"]),
                             "avoided_rects": sum(len(v) for v in obstacles.values())}
        else:
            existing_info = f"unavailable ({why}); existing annotations were not taken into account"
    out, missed = build(cfg, obstacles)
    json.dump(out, open(os.path.join(cfg["out_dir"], "annotations.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    js_path = os.path.join(cfg["out_dir"], "create_annotations.js")
    open(js_path, "w", encoding="utf8").write(render_js(cfg, out))
    by_type = collections.Counter(a["type"] for a in out)
    report = {"highlights": by_type.get("highlight", 0), "underlines": by_type.get("underline", 0),
              "margin_texts": by_type.get("text", 0), "missed": missed, "translation_warnings": check_translations(out),
              "layout_warnings": [{"page": a["pageLabel"], "text": a["comment"][:60], "reason": a["layout_warning"]} for a in out if a.get("layout_warning")],
              "existing_annotations": existing_info, "js": js_path,
              "previews": [os.path.join(cfg["out_dir"], f"preview_p{p}.png") for p in cfg["preview_pages"]]}

    if args.apply:
        if missed and not args.allow_missed:
            report["applied"] = False
            report["apply_error"] = "some phrases could not be located; correct them or pass --allow-missed"
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
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if missed or (args.apply and not report.get("applied")):
        sys.exit(2)


if __name__ == "__main__":
    main()
