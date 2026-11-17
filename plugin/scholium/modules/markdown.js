// ScholiumRunner, continued: Markdown and formulas, sentence citations and links

Object.assign(ScholiumRunner, {
  // Markdown as elements: headings, paragraphs, nested lists, quotes, code blocks, rules, and the inline
  // forms; the text only ever becomes text, so nothing in it is run or loaded
  renderMarkdown(doc, text) {
    const out = [];
    // the line and paragraph separators (U+2028, U+2029) end lines too: `.` in the patterns below does not cross them
    const lines = String(text || "").replace(/\r\n?|[\u2028\u2029]/g, "\n").split("\n");
    const listItem = /^\s*([-*+]|\d{1,9}[.)])\s+/;
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const start = i;
      let m, next;
      if (!line.trim()) {
        i++;
      } else if ((m = /^\s{0,3}(```|~~~)/.exec(line))) {
        const body = [];
        for (i++; i < lines.length && !lines[i].trim().startsWith(m[1]); i++) body.push(lines[i]);
        i++;
        const pre = doc.createElement("pre");
        const code = doc.createElement("code");
        code.textContent = body.join("\n");
        pre.append(code);
        out.push(pre);
      } else if ((m = /^\s{0,3}(#{1,6})\s+(.*?)(\s+#+)?\s*$/.exec(line))) {
        const h = doc.createElement("h" + m[1].length);
        this.inlineMarkdown(doc, h, m[2]);
        out.push(h);
        i++;
      } else if (this.markdownRule(line)) {
        out.push(doc.createElement("hr"));
        i++;
      } else if (/^\s{0,3}>/.test(line)) {
        const body = [];
        for (; i < lines.length && /^\s{0,3}>/.test(lines[i]); i++) body.push(lines[i].replace(/^\s{0,3}>\s?/, ""));
        const quote = doc.createElement("blockquote");
        quote.append(...this.renderMarkdown(doc, body.join("\n")));
        out.push(quote);
      } else if (listItem.test(line)) {
        i = this.markdownList(doc, lines, i, out);
      } else if ((next = this.markdownMath(doc, lines, i, out)) > i) {
        i = next;
      } else if (this.markdownTableStart(lines, i)) {
        i = this.markdownTable(doc, lines, i, out);
      } else {
        const body = [line.trim()];
        for (i++; i < lines.length && lines[i].trim() && !this.markdownBlock(lines[i]) && !listItem.test(lines[i])
               && !this.markdownTableStart(lines, i); i++) body.push(lines[i].trim());
        const para = doc.createElement("p");
        this.inlineMarkdown(doc, para, body.join("\n"));
        out.push(para);
      }
      if (i <= start) i = start + 1;   // each block takes at least one line, so that the text always comes to an end
    }
    return out;
  },

  markdownRule(line) { return /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line); },

  markdownBlock(line) { return /^\s{0,3}(#{1,6}\s|>|```|~~~)/.test(line) || this.markdownRule(line); },

  // a table starts with a row of cells over a row of dashes, one for each cell
  markdownTableStart(lines, i) {
    const rule = lines[i + 1];
    return lines[i].includes("|") && rule !== undefined && rule.includes("|")
      && /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/.test(rule.trim())
      && this.markdownCells(lines[i]).length === this.markdownCells(rule).length;
  },

  // the cells of a table row, split at the bars that are not escaped
  markdownCells(line) {
    return line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
  },

  // the table from line i, its rows running to a blank line; returns the line after it
  markdownTable(doc, lines, i, out) {
    const align = this.markdownCells(lines[i + 1]).map(c => (c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : c.startsWith(":") ? "left" : ""));
    const row = (line, tag) => {
      const tr = doc.createElement("tr");
      const cells = this.markdownCells(line);
      align.forEach((a, k) => {
        const cell = doc.createElement(tag);
        if (a) cell.setAttribute("style", "text-align: " + a);
        this.inlineMarkdown(doc, cell, cells[k] || "");
        tr.append(cell);
      });
      return tr;
    };
    const table = doc.createElement("table");
    const head = doc.createElement("thead");
    head.append(row(lines[i], "th"));
    table.append(head);
    const rows = [];
    for (i += 2; i < lines.length && lines[i].trim() && lines[i].includes("|") && !this.markdownBlock(lines[i]); i++) rows.push(row(lines[i], "td"));
    if (rows.length) {
      const body = doc.createElement("tbody");
      body.append(...rows);
      table.append(body);
    }
    out.push(table);
    return i;
  },

  // a list from line i and the lists nested in it by indentation; returns the line after it
  markdownList(doc, lines, i, out) {
    const item = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
    const width = space => space.replace(/\t/g, "    ").length;
    const items = [];
    let blank = false;
    for (; i < lines.length; i++) {
      const line = lines[i];
      const m = item.exec(line);
      if (m) {
        items.push({ indent: width(m[1]), ordered: /\d/.test(m[2]), start: parseInt(m[2], 10), text: [m[3]] });
        blank = false;
      } else if (!line.trim()) {
        blank = true;
      } else if (items.length && (width(/^\s*/.exec(line)[0]) >= 2 || (!blank && !this.markdownBlock(line)))) {
        items[items.length - 1].text.push(line.trim());   // the item's text goes on
        blank = false;
      } else {
        break;
      }
    }
    const open = [];   // { indent, list, li } from the outermost list in
    for (const it of items) {
      while (open.length && open[open.length - 1].indent > it.indent) open.pop();
      let top = open[open.length - 1];
      // a bullet after a number, or the other way round, starts a list of its own
      if (top && top.indent === it.indent && top.ordered !== it.ordered) {
        open.pop();
        top = open[open.length - 1];
      }
      if (!top || it.indent > top.indent) {
        const list = doc.createElement(it.ordered ? "ol" : "ul");
        if (it.ordered && it.start !== 1) list.setAttribute("start", String(it.start));
        if (top && top.li) top.li.append(list);
        else out.push(list);
        top = { indent: it.indent, ordered: it.ordered, list, li: null };
        open.push(top);
      }
      const li = doc.createElement("li");
      this.inlineMarkdown(doc, li, it.text.join("\n"));
      top.list.append(li);
      top.li = li;
    }
    return i;
  },

  // a formula set apart from line i: $$ … $$ or \[ … \], on one line or several; returns the line after
  // it, or i when none starts there
  markdownMath(doc, lines, i, out) {
    const m = /^\s{0,3}(\$\$|\\\[)(.*)$/.exec(lines[i]);
    if (!m) return i;
    const close = m[1] === "$$" ? "$$" : "\\]";
    const body = [];
    for (let j = i; j < lines.length; j++) {
      const text = j === i ? m[2] : lines[j];
      const end = text.indexOf(close);
      if (end < 0) {
        if (j > i && !text.trim()) return i;   // a blank line before its end: no formula
        body.push(text);
        continue;
      }
      if (text.slice(end + close.length).trim()) return i;   // text after it: a paragraph
      body.push(text.slice(0, end));
      const tex = body.join("\n").trim();
      if (!tex) return i;
      const box = doc.createElement("div");
      box.className = "scholium-math";
      const math = this.mathNode(doc, tex, true);
      if (math) box.append(math);
      else {   // the source, when KaTeX cannot read it
        const code = doc.createElement("code");
        code.textContent = lines.slice(i, j + 1).join("\n").trim();
        box.append(code);
      }
      out.push(box);
      return j + 1;
    }
    return i;
  },

  // KaTeX (content/katex/katex.min.js), loaded when the first formula is set; null when it cannot be
  katex() {
    if (this.katexLib === undefined) {
      this.katexLib = null;
      try {
        const scope = { module: { exports: {} } };
        scope.exports = scope.module.exports;
        Services.scriptloader.loadSubScript(this.chrome + "katex/katex.min.js", scope);
        if (typeof scope.module.exports.renderToString === "function") this.katexLib = scope.module.exports;
      } catch (e) { this.log("KaTeX not loaded: " + e); }
    }
    return this.katexLib;
  },

  // a formula in TeX as MathML, which Zotero sets itself; null when KaTeX cannot read it. KaTeX runs
  // untrusted (no links, pictures or classes from the TeX), and of what it writes only MathML elements
  // and attributes are kept.
  mathNode(doc, tex, display) {
    // for a note: the TeX itself, which Zotero's note editor sets (noteMarkup)
    if (this.noteTex) {
      const s = doc.createElement("span");
      s.className = "scholium-tex";
      s.setAttribute("data-tex", tex);
      return s;
    }
    const key = (display ? "D" : "I") + tex;
    let node = this.mathCache.get(key);
    if (node === undefined) {
      node = null;
      const katex = this.katex();
      const win = doc.defaultView;
      if (katex && win && win.DOMParser) {
        try {
          const markup = katex.renderToString(tex, { output: "mathml", displayMode: display, throwOnError: true, trust: false, strict: "ignore" });
          const math = new win.DOMParser().parseFromString(markup, "text/html").querySelector("math");
          if (math) node = this.cleanMath(math);
        } catch (e) {}
      }
      this.mathCache.set(key, node);
      if (this.mathCache.size > 500) this.mathCache.delete(this.mathCache.keys().next().value);   // the oldest
    }
    return node ? doc.importNode(node, true) : null;
  },

  MATH_TAGS: new Set(["math", "semantics", "annotation", "mrow", "mi", "mn", "mo", "ms", "mtext", "mspace", "msub", "msup", "msubsup",
                      "munder", "mover", "munderover", "mfrac", "msqrt", "mroot", "mstyle", "mpadded", "mphantom", "menclose",
                      "mtable", "mtr", "mtd", "mlabeledtr", "merror", "mmultiscripts", "mprescripts", "none"]),
  MATH_ATTRS: new Set(["xmlns", "display", "encoding", "mathvariant", "mathcolor", "mathbackground", "mathsize", "stretchy", "fence",
                       "separator", "lspace", "rspace", "minsize", "maxsize", "symmetric", "largeop", "movablelimits", "accent",
                       "accentunder", "form", "linethickness", "columnalign", "rowalign", "columnspacing", "rowspacing", "columnlines",
                       "rowlines", "frame", "framespacing", "equalrows", "equalcolumns", "displaystyle", "scriptlevel", "width",
                       "height", "depth", "voffset", "notation"]),

  // only MathML elements and attributes: anything else KaTeX might write is left out
  cleanMath(el) {
    for (const name of el.getAttributeNames()) if (!this.MATH_ATTRS.has(name)) el.removeAttribute(name);
    for (const child of [...el.children]) {
      if (this.MATH_TAGS.has(child.localName)) this.cleanMath(child);
      else child.remove();
    }
    return el;
  },

  // `code` (a colour code with a swatch of its colour), formulas (\( \), $ $, and set apart \[ \], $$ $$),
  // backslash escapes, **bold**, *italics*, [links](…), bare web addresses, and <sub>…</sub> and <sup>…</sup> as
  // subscript and superscript (other tags stay text). A link shows its text with the address as tooltip; the transcript and the profile preview open web and zotero: addresses on a click
  // (followLinks). A $ opens a formula before a non-space and closes one after a non-space that no digit
  // follows, so that prices stay text.
  inlineMarkdown(doc, parent, text, inLink = false) {
    const re = new RegExp([
      "`([^`\\n]+)`",                                  // 1 code
      "\\$\\$([^$]+?)\\$\\$",                          // 2 formula set apart
      "\\\\\\[([\\s\\S]+?)\\\\\\]",                    // 3 formula set apart
      "\\\\\\(([\\s\\S]+?)\\\\\\)",                    // 4 formula
      "\\$(?=[^\\s$])([^$\\n]*?[^\\s$\\\\])\\$(?!\\d)", // 5 formula
      "\\\\([!-/:-@[-`{-~])",                          // 6 an escaped punctuation mark
      "\\*\\*([^*\\n]+?)\\*\\*",                       // 7 bold
      "\\*([^*\\s][^*\\n]*?)\\*",                      // 8 italics
      "\\[([^\\]\\n]+)\\]\\(([^)\\s]+)\\)",            // 9, 10 link
      "((?:https?|zotero)://[^\\s<>\"'`()（）\\[\\]{}，。；：！？、]+)",   // 11 a bare address
      "\\[#(\\d{1,6})\\]",                             // 12 a sentence of the paper
      "<(sub|sup)>([^<>\\n]+?)</\\13>",                // 13, 14 subscript, superscript
    ].join("|"), "g");
    let at = 0;
    let m;
    while ((m = re.exec(text))) {
      let before = m.index > at ? text.slice(at, m.index) : "", open = "";
      // an opening bracket right before citations stays with them
      if (m[12] !== undefined && this.cites) {
        const b = /[（(「『“‘【]$/.exec(before);
        if (b) { open = b[0]; before = before.slice(0, -1); }
      }
      if (before) parent.append(doc.createTextNode(before));
      if (m[11] !== undefined) {   // punctuation after an address ends the sentence, not the address
        // nor is Chinese written right after it: "见https://x.org/abs/1234的图"; a path or query value of Chinese
        // words follows / = # ? or & ("https://zh.example/页")
        let n = 0;
        while (n < m[11].length && m[11].charCodeAt(n) < 0x2e80) n++;
        const own = n === m[11].length || "/=#?&".includes(m[11][n - 1]) ? m[11] : m[11].slice(0, n);
        const address = own.replace(/[.,;:!?]+$/, "");
        re.lastIndex = m.index + address.length;
        at = re.lastIndex;
        parent.append(inLink ? doc.createTextNode(address) : this.linkNode(doc, address, address));
        continue;
      }
      at = re.lastIndex;
      if (m[13] !== undefined) {
        const el = doc.createElement(m[13]);
        this.inlineMarkdown(doc, el, m[14], inLink);
        parent.append(el);
        continue;
      }
      if (m[12] !== undefined) {
        if (!this.cites) { parent.append(doc.createTextNode(m[0])); continue; }
        const run = this.citeRun(doc, text, m, open);
        parent.append(run.node);
        at = re.lastIndex = run.end;
        continue;
      }
      if (m[2] !== undefined || m[3] !== undefined || m[4] !== undefined || m[5] !== undefined) {
        const display = m[2] !== undefined || m[3] !== undefined;
        const math = this.mathNode(doc, (m[2] ?? m[3] ?? m[4] ?? m[5]).trim(), display);
        if (!math) parent.append(doc.createTextNode(m[0]));   // the source, when KaTeX cannot read it
        else if (!display) parent.append(math);
        else {
          const box = doc.createElement("span");
          box.className = "scholium-math";
          box.append(math);
          parent.append(box);
        }
        continue;
      }
      if (m[6] !== undefined) {
        parent.append(doc.createTextNode(m[6]));
        continue;
      }
      if (m[1] !== undefined) {
        const code = doc.createElement("code");
        if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(m[1])) {
          const swatch = doc.createElement("span");
          swatch.className = "scholium-swatch";
          swatch.setAttribute("style", "background-color: " + m[1]);
          code.append(swatch);
        }
        code.append(doc.createTextNode(m[1]));
        parent.append(code);
      } else if (m[7] !== undefined) {
        const strong = doc.createElement("strong");
        this.inlineMarkdown(doc, strong, m[7]);
        parent.append(strong);
      } else if (m[8] !== undefined) {
        const em = doc.createElement("em");
        this.inlineMarkdown(doc, em, m[8]);
        parent.append(em);
      } else if (inLink) {
        this.inlineMarkdown(doc, parent, m[9], true);
      } else {
        const link = this.linkNode(doc, m[10]);
        this.inlineMarkdown(doc, link, m[9], true);
        parent.append(link);
      }
    }
    if (at < text.length) parent.append(doc.createTextNode(text.slice(at)));
  },

  // the paper's numbered sentences, for the citations in answers: read again when the file changed; those of the 20
  // papers shown last are kept
  async loadCitations(key) {
    if (!key) return;
    const path = PathUtils.join(this.outDir(key), "sentences.json");
    let stat = null;
    try { stat = await IOUtils.stat(path); } catch (e) { this.citations.delete(key); return; }
    const had = this.citations.get(key);
    if (had && had.at === stat.lastModified && had.size === stat.size) {
      this.citations.delete(key);
      this.citations.set(key, had);   // the latest shown
      return;
    }
    let raw;
    try { raw = await IOUtils.readUTF8(path); } catch (e) { this.log("sentences not read: " + e); return; }   // tried again at the next draw
    const map = new Map();
    try {
      const data = JSON.parse(raw);
      for (const x of (data && data.sentences) || []) {
        if (x && Number.isInteger(x.id) && x.page > 0) map.set(x.id, { page: x.page, text: String(x.text || ""), rects: this.positionRects(x.rects) });
      }
    } catch (e) { map.clear(); this.log("sentences not parsed: " + e); }
    this.citations.delete(key);
    this.citations.set(key, { at: stat.lastModified, size: stat.size, map });
    if (this.citations.size > 20) this.citations.delete(this.citations.keys().next().value);   // the one shown longest ago
  },

  // a sentence's position in sentences.json: its rectangles of four finite numbers, or null when it has none
  positionRects(rects) {
    const kept = Array.isArray(rects)
      ? rects.filter(r => Array.isArray(r) && r.length === 4 && r.every(v => typeof v === "number" && Number.isFinite(v))) : [];
    return kept.length ? kept : null;
  },

  // the citations side by side from the match m on, as one piece that does not wrap, with the opening bracket before them
  // (open) and the punctuation after them: the sentences of one page one after another are one chip; an id
  // sentences.json does not have stays text. end: where the text goes on after the piece
  citeRun(doc, text, m, open) {
    const ids = [Number(m[12])];
    let end = m.index + m[0].length, r;
    const next = /^\s*\[#(\d{1,6})\]/;
    while ((r = next.exec(text.slice(end)))) { ids.push(Number(r[1])); end += r[0].length; }
    const items = [];
    for (const id of ids) {
      const s = this.cites.map.get(id), last = items[items.length - 1];
      if (s && last && last.s && last.s.page === s.page) last.ids.push(id), last.all.push(s);
      else items.push(s ? { ids: [id], s, all: [s] } : { raw: `[#${id}]` });
    }
    if (!items.some(i => i.s)) return { node: doc.createTextNode(open + text.slice(m.index, end)), end };
    const punct = /^[）)」』”’】。，、；：！？.,;:!?]+/.exec(text.slice(end));
    if (punct) end += punct[0].length;
    const node = doc.createElement("span");
    node.className = "scholium-cites";
    if (open) node.append(doc.createTextNode(open));
    for (const i of items) {
      if (!i.s) { node.append(doc.createTextNode(i.raw)); continue; }
      const rects = i.all.flatMap(s => s.rects || []);
      const s = i.all.length === 1 ? i.s : { page: i.s.page, text: i.all.map(x => x.text).join(" "), texts: i.all.map(x => x.text), rects: rects.length ? rects : null };
      node.append(this.citeNode(doc, this.cites.key, i.ids.join(","), s));
    }
    if (punct) node.append(doc.createTextNode(punct[0]));
    return { node, end };
  },

  withCites(key, fn) {
    const before = this.cites;
    const c = key && this.citations.get(key);
    this.cites = c ? { key, map: c.map } : null;
    try { return fn(); } finally { this.cites = before; }
  },

  // a cited sentence as a chip with its page
  citeNode(doc, key, id, s) {
    const chip = doc.createElement("span");
    chip.className = "scholium-cite";
    chip.setAttribute("data-id", String(id));
    chip.textContent = this.text("pageRef", s.page);
    chip.addEventListener("mouseenter", () => this.openCiteCard(chip, key, s));
    chip.addEventListener("mouseleave", () => { const pane = this.paneOf(chip); if (pane) this.citeAway(pane); });
    chip.addEventListener("click", () => { this.locate(key, s).catch(e => this.log("locate failed: " + e)); });
    // from the keyboard: the card while the chip has the focus (not a click's focus, nor the window's coming back to it),
    // Enter or Space locates
    chip.addEventListener("focus", () => {
      let keyboard = false;
      try { keyboard = chip.matches(":focus-visible"); } catch (e) {}
      if (keyboard) this.openCiteCard(chip, key, s);
    });
    chip.addEventListener("blur", () => { const pane = this.paneOf(chip); if (pane) this.citeAway(pane); });
    this.keyButton(chip, () => { this.locate(key, s).catch(e => this.log("locate failed: " + e)); });
    return chip;
  },

  // a cited sentence on hover: its page, Locate at the top right, the sentence. It closes when the pointer is on neither
  // the chip nor the card
  openCiteCard(chip, key, s) {
    const pane = this.paneOf(chip);
    if (!pane || (pane.popover && pane.popover.name !== "cite")) return;
    pane.citeHover = 1;
    const node = this.openPopover(pane, "cite", chip, card => {
      const doc = pane.doc;
      const head = doc.createElement("div");
      head.className = "scholium-cite-head";
      const page = doc.createElement("span");
      page.textContent = this.text("citePage", s.page);
      const go = this.paneButton(doc, this.text("locate"), () => { this.closePopover(pane, "cite"); this.locate(key, s).catch(e => this.log("locate failed: " + e)); }, "quiet small");
      head.append(page, go);
      card.append(head);
      for (const t of s.texts || [s.text]) {
        const text = doc.createElement("div");
        text.className = "scholium-cite-text";
        text.textContent = t;
        card.append(text);
      }
    });
    node.addEventListener("mouseenter", () => { pane.citeHover++; });
    node.addEventListener("mouseleave", () => this.citeAway(pane));
  },

  citeAway(pane) {
    if (!pane.popover || pane.popover.name !== "cite") return;
    pane.citeHover--;
    setTimeout(() => { if (pane.citeHover <= 0) this.closePopover(pane, "cite"); }, 300);
  },

  // the section that shows a node (a card lives in the window's root, so its pane is found from its chip)
  paneOf(node) {
    for (const pane of this.panes.values()) if (pane.body && pane.body.contains(node)) return pane;
    return null;
  },

  // a cited sentence in the paper's reader: the reader opens (or is switched to) at the sentence's position, which it
  // centres and highlights for a moment; a tab there but not loaded is selected with it. A sentence without a position
  // opens its page
  async locate(key, s) {
    if (!s || !s.page) return;
    const pane = [...this.panes.values()].find(p => p.keys.includes(key) && p.item);
    const att = pane && this.attOf(pane.item.libraryID, key);
    if (!att) return;
    const pageIndex = s.page - 1;
    try { await Zotero.Reader.open(att.id, s.rects ? { position: { pageIndex, rects: s.rects } } : { pageIndex }); }
    catch (e) { this.log("sentence not shown in the reader: " + e); }
  },

  LINK_SCHEMES: /^(?:https?|zotero):/i,

  // a link's text with its address as tooltip; an address Zotero can open is kept for a click
  linkNode(doc, address, text = null) {
    const link = doc.createElement("span");
    link.className = "scholium-link";
    link.title = address;
    if (this.LINK_SCHEMES.test(address)) {
      link.setAttribute("data-href", address);
      link.setAttribute("role", "link");
      link.setAttribute("tabindex", "0");
    }
    if (text !== null) link.append(doc.createTextNode(text));
    return link;
  },

  // a link in `node` opens on a click (not when the click ends a selection in it) or with Enter
  followLinks(node, win) {
    node.addEventListener("click", e => {
      const link = e.target && e.target.closest && e.target.closest(".scholium-link[data-href]");
      const sel = win && win.getSelection && win.getSelection();
      if (!link || (sel && !sel.isCollapsed && link.contains(sel.anchorNode))) return;
      e.preventDefault();
      this.openLink(link.getAttribute("data-href"));
    });
    node.addEventListener("keydown", e => {
      const link = e.key === "Enter" && e.target && e.target.closest && e.target.closest(".scholium-link[data-href]");
      if (link) { e.preventDefault(); this.openLink(link.getAttribute("data-href")); }
    });
  },

  // web addresses open in the browser, zotero: addresses in Zotero (zotero://select shows the item)
  openLink(address) {
    if (!this.LINK_SCHEMES.test(String(address || ""))) return;
    try { Zotero.getMainWindow().ZoteroPane.loadURI(address); }
    catch (e) { this.log("link failed: " + e); }
  },
});
