// ScholiumRunner, continued: the Scholium section: its registration, layers and popovers, settings chip and
// settings layer, its fit, its tabs and its frame

Object.assign(ScholiumRunner, {
  // PDF attachment keys of the item shown in an item pane
  paneKeys(item) {
    try {
      if (!item) return [];
      if (item.isRegularItem && item.isRegularItem()) return this.pdfAttachments([item]).map(a => this.keyOf(a));
      if (item.isAttachment && item.isAttachment() && item.attachmentContentType === "application/pdf") return [this.keyOf(item)];
    } catch (e) {}
    return [];
  },

  // the Scholium section of the item pane (library and reader side pane)
  registerPane(pluginID) {
    const manager = Zotero.ItemPaneManager;
    if (!manager || typeof manager.registerSection !== "function") return;
    // l10nArgs: Zotero 7 writes "undefined" as the arguments without them; the icons have a lighter violet on a dark theme
    this.paneID = manager.registerSection({
      paneID: "scholium", pluginID,
      header: { l10nID: "scholium-section", l10nArgs: "{}", icon: this.chrome + "icon16.svg", darkIcon: this.chrome + "icon16-dark.svg" },
      sidenav: { l10nID: "scholium-sidenav", l10nArgs: "{}", icon: this.chrome + "icon20.svg", darkIcon: this.chrome + "icon20-dark.svg" },
      onItemChange: ({ item, setEnabled }) => { setEnabled(this.paneKeys(item).length > 0); },
      onRender: ({ doc, body, item }) => { this.renderPane(doc, body, item); },
      onAsyncRender: ({ body }) => this.loadPane(body),
      onDestroy: ({ body }) => { this.dropPane(body); },
    }) || null;
  },

  // the section of a paper in a window: a reader's is the one of its side pane (the library's stays drawn behind the
  // reader's tab); else the one on screen when there are several
  paneFor(win, key, tabID = null) {
    let found = null;
    for (const pane of this.panes.values()) {
      if (!pane.keys.includes(key) || (win && pane.doc.defaultView !== win)) continue;
      if (tabID) {
        let details = null;
        try { details = pane.body.closest("item-details"); } catch (e) {}
        if (details && details.tabID === tabID) return pane;
        continue;
      }
      found = pane;
      try { if (pane.body.checkVisibility && pane.body.checkVisibility()) return pane; } catch (e) {}
    }
    return found;
  },

  // the section in view: the reader's side pane opened (for a section in a reader's tab only: the library's tab has a
  // context pane of its own, which stays as it is), the section opened, the item pane scrolled to it; each step may be
  // missing. A section not drawn yet is found in the side pane of the reader's tab (Zotero draws it once it is scrolled to)
  async revealSection(win, pane = null, tabID = null, reader = false) {
    let inReader = reader || !!tabID;
    try { inReader = inReader || !!(pane && pane.body && pane.body.closest && pane.body.closest("#zotero-context-pane")); } catch (e) {}
    try { if (inReader && win && win.ZoteroContextPane && win.ZoteroContextPane.collapsed) win.ZoteroContextPane.collapsed = false; } catch (e) {}
    let section = null, details = null;
    try {
      if (pane && pane.body) { section = pane.body.closest("collapsible-section"); details = pane.body.closest("item-details"); }
      else if (tabID && win) {
        details = win.document.getElementById(tabID + "-context");
        const own = details && [...details.querySelectorAll("item-pane-custom-section")].find(c => c.dataset.pane === this.paneID);
        section = own && own.querySelector("collapsible-section");
      }
    } catch (e) {}
    try { if (section) section.open = true; } catch (e) {}
    // Zotero 7's scrollToPane may not settle: a second at most
    try {
      if (details && typeof details.scrollToPane === "function") {
        await Promise.race([details.scrollToPane(this.paneID), Zotero.Promise.delay(1000)]);
      }
    } catch (e) {}
  },

  dropPane(body) {
    const pane = this.panes.get(body);
    if (!pane) return;
    try { if (pane.observer) pane.observer.disconnect(); } catch (e) {}
    this.releaseFit(pane);
    this.releaseLayer(pane);
    this.panes.delete(body);
  },

  // a pane's layer and its document-level listener go with the pane
  releaseLayer(pane) {
    this.closePopover(pane);
    try { pane.doc.removeEventListener("mousedown", pane.outside, true); } catch (e) {}
  },

  // a small layer over the item pane, one at a time: the settings, the history, the context, a menu, a quoted sentence.
  // It is fixed in the window's document, since the pane's scroller would clip it; so it closes when the scroller scrolls
  // or the window resizes, and a click outside it or Esc closes it; so does Tab out of it. Opened from the keyboard it takes
  // the focus (`focus`: its first control, or "layer" for the layer itself), which goes back to its button when it closes
  // with the focus in it; opened with the mouse it leaves the focus where it was
  openPopover(pane, name, anchor, build, { focus = false } = {}) {
    this.closePopover(pane);
    const doc = pane.doc;
    const node = doc.createElement("div");
    node.className = "scholium-popover " + name;
    node.addEventListener("keydown", e => { if (e.key === "Escape" && this.escape(pane)) { e.preventDefault(); e.stopPropagation(); } });
    // the focus on an element outside the layer and its button, once it moved; not nowhere (a control drawn again)
    node.addEventListener("focusout", () => {
      setTimeout(() => {
        const a = doc.activeElement;
        if (!pane.popover || pane.popover.node !== node || !a || a === doc.documentElement || a === doc.body
            || node.contains(a) || (anchor && anchor.contains(a))) return;
        this.closePopover(pane);
      }, 0);
    });
    build(node);
    doc.documentElement.append(node);
    const win = doc.defaultView;
    const close = () => { this.closePopover(pane); };
    const scroller = this.paneScroller(pane);
    try { scroller.addEventListener("scroll", close); } catch (e) {}
    try { win.addEventListener("resize", close); } catch (e) {}
    const off = () => {
      try { scroller.removeEventListener("scroll", close); } catch (e) {}
      try { win.removeEventListener("resize", close); } catch (e) {}
    };
    pane.popover = { name, node, anchor, off, took: false };
    this.placePopover(pane);
    if (focus === "layer") node.setAttribute("tabindex", "-1");
    // `focus` may also name the control that takes it
    this.focusLayer(pane, focus === "layer" ? node : focus && typeof focus === "object" ? focus : focus ? this.firstControl(node) : null);
    return node;
  },

  // ↓ and ↑, Home and End move the focus among a layer's items, as in a menu; `items` gives each item's control and the
  // element it belongs to (its row). The keys of a text box are its own
  arrowKeys(pane, node, items) {
    node.addEventListener("keydown", e => {
      if (e.isComposing || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
      if (e.target && ["input", "textarea", "select"].includes(e.target.localName)) return;
      const list = items().filter(([b]) => b && !b.disabled && !b.hidden);
      if (!list.length) return;
      const a = pane.doc.activeElement;
      const at = list.findIndex(([, own]) => !!a && (own === a || (typeof own.contains === "function" && own.contains(a))));
      const step = e.key === "ArrowDown" ? 1 : -1;
      const to = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1
        : at < 0 ? (step > 0 ? 0 : list.length - 1) : (at + step + list.length) % list.length;
      e.preventDefault();
      e.stopPropagation();
      try { list[to][0].focus(); } catch (err) {}
    });
  },

  // the menu items of a layer, for arrowKeys
  menuItems(node) {
    return () => [...(node.children || [])].filter(c => c && c.className === "scholium-menu-item").map(b => [b, b]);
  },

  // the focus into the open layer, which gives it back to its button when it closes
  focusLayer(pane, target) {
    if (!target || !pane.popover) return;
    try { target.focus({ preventScroll: true }); pane.popover.took = true; } catch (e) {}
  },

  // a click from the keyboard (Enter or Space on a button), not from the mouse
  byKeyboard(e) { return !!e && e.detail === 0; },

  // the first control of a layer that takes the focus
  firstControl(node) {
    for (const c of node.children || []) {
      if (!c || !c.localName || c.hidden || c.disabled) continue;
      if (["button", "select", "input", "textarea"].includes(c.localName) || c.getAttribute("tabindex") === "0") return c;
      const inner = this.firstControl(c);
      if (inner) return inner;
    }
    return null;
  },

  closePopover(pane, name = null) {
    const p = pane.popover;
    if (!p || (name && p.name !== name)) return false;
    // a title being renamed in it is kept, as leaving its box keeps it
    const r = pane.renaming;
    try { if (r && r.finish && p.node.contains(r.input)) r.finish(true, false).catch(() => {}); } catch (e) {}
    let inside = false;
    try { inside = p.node.contains(pane.doc.activeElement); } catch (e) {}
    try { p.off(); } catch (e) {}
    try { p.node.remove(); } catch (e) {}
    pane.popover = null;
    if (inside && p.took && p.anchor) { try { p.anchor.focus({ preventScroll: true }); } catch (e) {} }
    return true;
  },

  // the item pane's scroller, or the section when the pane is not inside one
  paneScroller(pane) {
    let scroller = null;
    try { scroller = pane.body.closest("item-details")?._paneParent; } catch (e) {}
    return scroller || pane.box;
  },

  // below its anchor while that is in the upper half of the visible pane, else above it; within the pane's width
  placePopover(pane) {
    const p = pane.popover;
    try {
      const s = this.paneScroller(pane).getBoundingClientRect(), a = p.anchor.getBoundingClientRect();
      p.node.style.maxWidth = Math.floor(s.right - s.left) + "px";
      p.node.style.left = Math.max(s.left, Math.min(a.left, s.right - p.node.offsetWidth)) + "px";
      if (a.top - s.top < (s.bottom - s.top) / 2) { p.node.style.top = (a.bottom + 4) + "px"; p.node.style.bottom = ""; }
      else {
        const doc = pane.doc;
        p.node.style.bottom = ((doc.documentElement.clientHeight || doc.defaultView.innerHeight || s.bottom) - a.top + 4) + "px";
        p.node.style.top = "";
      }
    } catch (e) {}
  },

  // Esc in a section: closes a layer; else, while its paper runs, asks once and stops on the second press, of the same run
  escape(pane) {
    if (this.closePopover(pane)) return true;
    if (!pane.busy) return false;
    if (this.escArmed(pane)) {
      pane.escAt = 0;
      pane.escRun = null;
      this.stopFromPane(pane);
    } else {
      pane.escAt = Date.now();
      pane.escRun = this.paneRun(pane) || "waiting";
      setTimeout(() => this.paintHint(pane), this.ESC_MS + 50);
    }
    this.paintHint(pane);
    return true;
  },

  // the run of the tab a section shows: of the conversation shown, else one of its paper's of the tab's kind
  paneRun(pane) {
    const view = this.viewOf(pane, pane.tab);
    return this.runOfView(view) || pane.keys.map(k => this.paperRuns(k).find(r => r.kind === pane.tab)).find(Boolean) || null;
  },

  // whether a first Esc asks to stop: pressed a moment ago, on the run that still goes on. Once that run ends or another
  // starts, the press is forgotten, and paintPane's hint says so
  escArmed(pane) {
    return !!pane.escAt && Date.now() - pane.escAt < this.ESC_MS && pane.escRun === (this.paneRun(pane) || "waiting");
  },

  // the run of the tab shown stops; a paper of it that only waits there leaves the queue, the other tab's wait stays. The
  // tab's queued messages stay, held until Resume, as Codex holds its queue after an interruption
  stopFromPane(pane) {
    const run = this.paneRun(pane);
    // the conversation ■ is for: the run's, else the one shown; words queued without one yet are the shown one's
    const conv = run ? run.conv || null : this.viewOf(pane, pane.tab).shownConv || null;
    const mine = j => pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === pane.tab && (!j.conv || j.conv === conv);
    for (const j of this.queue) if (j.qid && mine(j)) this.heldQueues.add(this.queueKey(j));
    if (run) this.cancel(run);
    else {
      // what waits of this conversation; when only another one's waits (■ shows for the paper's tab), that
      const waits = j => !j.qid && pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === pane.tab;
      const own = this.queue.some(j => waits(j) && (!j.conv || j.conv === conv));
      this.dequeue(pane.keys, pane.tab, own ? { rows: false, conv } : { rows: false });
    }
  },

  paintHint(pane) {
    const armed = this.escArmed(pane);
    const said = pane.said && Date.now() - pane.said.at < this.SAID_MS ? pane.said.text : "";
    const mod = Services.appinfo && Services.appinfo.OS === "Darwin" ? "⌘" : "Ctrl";
    const shortcut = this.sendShortcut();
    pane.hint.textContent = armed ? this.text("escAgain") : said
      || (shortcut === "enter" ? this.text("sendHintEnter") : shortcut === "cmdIfMultiline" ? this.text("sendHintMultiline", mod) : this.text("sendHint", mod));
    pane.hint.title = pane.hint.textContent;   // cut with an ellipsis where the pane is narrow
  },

  // a word under the message box in place of the hint, for a moment
  sayUnderBox(pane, text) {
    const said = pane.said = { text, at: Date.now() };
    this.paintHint(pane);
    setTimeout(() => { if (pane.said === said) pane.said = null; this.paintHint(pane); }, this.SAID_MS);
  },

  // the context ring: an arc of the window's share the shown conversation's session takes up; its tooltip in Codex's words
  paintRing(pane) {
    const view = this.viewOf(pane, pane.tab);
    const going = view.live ? this.runOfView(view) : null;
    const c = going ? going.context : view.context;
    const used = c && c.used > 0 ? c.used : 0, win = c && c.window > 0 ? c.window : 0;
    const shown = this.contextRingOn() && used > 0 && win > 0;
    this.show(pane.ring, shown);
    if (!shown) return;
    const share = Math.min(100, Math.round(used / win * 100));
    pane.ring.className = "scholium-ring" + (used / win >= this.CONTEXT_WARN ? " warn" : "");
    pane.ring.style.setProperty("--share", share + "%");
    pane.ring.title = [this.text("contextLabel"), this.text("contextUsed", share, 100 - share),
                       this.text("contextTokens", this.kTokens(used), this.kTokens(win))].join("\n");
  },

  // the context layer: the numbers, a bar of input, cache and output, and the compaction of the conversation
  openContextLayer(pane, focus = false) {
    if (this.closePopover(pane, "context")) return;
    const view = this.viewOf(pane, pane.tab);
    const going = view.live ? this.runOfView(view) : null;
    const c = (going ? going.context : view.context) || {};
    this.openPopover(pane, "context", pane.ring, node => {
      const doc = pane.doc;
      const row = (cls, ...kids) => { const d = doc.createElement("div"); d.className = cls; d.append(...kids); return d; };
      // a label and its number as two boxes of their row (two text nodes would run together as one)
      const span = text => { const s = doc.createElement("span"); s.textContent = text; return s; };
      const share = c.window > 0 ? Math.round(c.used / c.window * 100) : 0;
      node.append(row("scholium-context-head", span(this.text("contextTitle2")),
                      span(this.text("contextShare", this.kTokens(c.used), this.kTokens(c.window), share))));
      const p = c.parts;
      if (p && (p.input || p.cache || p.output) && c.window > 0) {
        const bar = row("scholium-context-bar"), legend = row("scholium-context-legend");
        for (const [k, label] of [["input", "partInput"], ["cache", "partCache"], ["output", "partOutput"]]) {
          const seg = doc.createElement("span");
          seg.className = "seg " + k;
          seg.style.setProperty("--w", (p[k] / c.window * 100).toFixed(2) + "%");
          bar.append(seg);
          legend.append(row("item " + k, span(this.text(label)), span(this.kTokens(p[k]))));
        }
        node.append(bar, legend);
      }
      const box = row("scholium-context-compact");
      const go = doc.createElement("button");
      go.className = "scholium-button small";
      go.textContent = this.text("compactButton");
      go.disabled = !view.shownKey || this.busy(view.shownKey) || !view.shownConv || !(c && c.used > 0);
      go.addEventListener("click", () => {
        this.closePopover(pane, "context");
        this.compactFromPane(pane).catch(e => this.log("compact failed: " + e));
      });
      const note = doc.createElement("div");
      note.textContent = this.text("compactNote");
      box.append(go, note);
      node.append(box);
    }, { focus: focus ? "layer" : false });   // not onto Compact, which compacts at once
  },

  chipLabel() {
    const agent = this.agent();
    const model = this.modelChoices(agent).find(m => m.value === this.modelPref(agent));
    return [this.agentName(agent), model ? model.label : this.modelPref(agent), this.effort(agent)].filter(Boolean).join(" · ");
  },

  // the chip: the model, cut with an ellipsis where the line is narrow, then the effort in small grey and ▾, which stay;
  // the agent is in its tooltip and its layer
  paintChip(pane) {
    const doc = pane.doc, agent = this.agent();
    const model = this.modelChoices(agent).find(m => m.value === this.modelPref(agent));
    const name = doc.createElement("span");
    name.className = "scholium-chip-name";
    // an empty model is the agent's default
    name.textContent = (model && model.label) || this.modelPref(agent)
      || this.text(agent === "codex" ? "paneCodexDefault" : "paneClaudeDefault");
    const tail = doc.createElement("span");
    tail.className = "scholium-chip-tail";
    const effort = this.effort(agent);
    if (effort) {
      const e = doc.createElement("span");
      e.className = "scholium-chip-effort";
      e.textContent = effort;
      tail.append(e);
    }
    tail.append(doc.createTextNode("▾"));
    pane.chip.replaceChildren(name, tail);
    pane.chip.title = this.chipLabel();
  },

  paneField(doc, text, control) {
    const label = doc.createElement("label");
    label.className = "scholium-field";
    const caption = doc.createElement("span");
    caption.textContent = text;
    label.append(caption, control);
    return label;
  },

  // opened from the keyboard, the focus goes to the model, not to the agent, whose select an arrow key would switch at
  // once; Shift+Tab reaches the agent
  openSettingsLayer(pane, focus = false) {
    const doc = pane.doc;
    const target = focus ? [pane.model, pane.effort].find(s => !s.disabled && !s.hidden) || true : false;
    this.openPopover(pane, "settings", pane.chip, node => {
      const note = doc.createElement("div");
      note.className = "scholium-note";
      note.textContent = this.text("agentSwitchNote");
      node.append(this.paneField(doc, this.text("paneAgent"), pane.agent), note, this.paneField(doc, this.text("paneModel"), pane.model),
                  this.paneField(doc, this.text("paneEffort"), pane.effort));
    }, { focus: target });
  },

  // the ⋯ menu; each item closes the layer first
  openMoreMenu(pane, focus = false) {
    const doc = pane.doc;
    this.openPopover(pane, "menu", pane.more, node => {
      node.setAttribute("role", "menu");
      this.arrowKeys(pane, node, this.menuItems(node));
      const item = (label, run, disabled = false) => {
        const b = doc.createElement("button");
        b.className = "scholium-menu-item";
        b.setAttribute("role", "menuitem");
        b.textContent = label;
        b.disabled = disabled;
        b.addEventListener("click", () => { this.closePopover(pane); run(); });
        return b;
      };
      const sep = doc.createElement("div");
      sep.className = "scholium-menu-sep";
      if (pane.tab === "annotate") {
        node.append(item(this.text("profileOpen"), () => { this.openProfile(doc, pane.more); }),
                    item(this.text("logButton"), () => { this.revealLog(pane.annot.shownPath); }, !pane.annot.shownPath),
                    // the PDF the section shows, as its conversations
                    item(this.text("deleteThis"), () => {
                      const att = pane.item && this.attOf(pane.item.libraryID, pane.annot.shownKey || pane.keys[0]);
                      this.removeAnnotations(att ? [att] : []).catch(e => this.log("delete failed: " + e));
                    }, pane.keys.some(k => this.busy(k))));
        // the session shown, as a note
        if (pane.annot.shownPath) node.append(item(this.text("saveNote"), () => { this.saveAsNote(pane).catch(e => this.log("note failed: " + e)); }));
        node.append(sep, item(this.text("settingsOpen"), () => { this.openSettings(); }));
        return;
      }
      node.append(item(this.text("logButton"), () => { this.revealLog(pane.shownPath); }, !pane.shownPath),
                  item(this.text("profileOpen"), () => { this.openProfile(doc, pane.more); }),
                  item(this.text("saveNote"), () => { this.saveAsNote(pane).catch(e => this.log("note failed: " + e)); }, !pane.shownPath), sep,
                  item(this.text("settingsOpen"), () => { this.openSettings(); }));
    }, { focus });
  },

  // the hidden attribute alone leaves an element on screen in Zotero's main window
  show(el, visible) {
    el.hidden = !visible;
    el.style.display = visible ? "" : "none";
  },

  paneButton(doc, label, onClick, look = "") {
    const button = doc.createElement("button");
    button.className = ("scholium-button " + look).trim();
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  },

  // a button that is an icon (content/<icon>16.svg, in the button's text colour); its words are its tooltip and
  // its accessible name
  iconButton(doc, icon, label, onClick, look = "quiet") {
    const button = this.paneButton(doc, "", onClick, `${look} glyph ${icon}`);
    const glyph = doc.createElement("span");
    glyph.className = "scholium-glyph";
    button.append(glyph);
    button.title = label;
    button.setAttribute("aria-label", label);
    return button;
  },

  // an element that is not a button made one for the keyboard: it takes the focus, Enter and Space press it
  keyButton(node, onPress) {
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "button");
    node.addEventListener("keydown", e => {
      if (e.isComposing || (e.key !== "Enter" && e.key !== " ")) return;
      e.preventDefault();
      onPress();
    });
  },

  // the real scroller of the item pane (the library's and the reader's alike), or null
  scrollParent(pane) {
    try { return pane.body.closest("item-details")?._paneParent || null; } catch (e) { return null; }
  },

  // a section as tall as its pane shows, so that its message box stays in view: the scroller's visible height less the
  // gaps between the section and its body, measured now
  fitPane(pane) {
    try {
      const scroller = pane.scroller || (pane.scroller = this.scrollParent(pane));
      if (!scroller) return;
      let gap = this.PANE_HEAD;
      const section = pane.body.closest("collapsible-section");
      if (section) {
        const s = section.getBoundingClientRect(), b = pane.body.getBoundingClientRect();
        if (s && b && isFinite(b.top - s.top + s.bottom - b.bottom)) gap = b.top - s.top + s.bottom - b.bottom;
      }
      pane.box.style.height = Math.max(this.MIN_PANE, Math.round(scroller.clientHeight - gap)) + "px";
      pane.queueBox.style.maxHeight = Math.round(scroller.clientHeight * 0.3) + "px";   // the queue, at most three tenths of it
    } catch (e) {}
  },

  // refit when the scroller's size changes. While the section is at the top of the pane, it stays there when a section
  // above it changes size (an attachment's row once its annotations are written, for one)
  watchFit(pane) {
    const scroller = pane.scroller;
    if (!scroller) return;
    const win = pane.doc.defaultView;
    const refit = () => { this.fitPane(pane); };
    const offset = () => {
      const section = pane.body.closest("collapsible-section");
      return section ? section.getBoundingClientRect().top - scroller.getBoundingClientRect().top : null;
    };
    let atTop = false;
    const seen = () => { const t = offset(); atTop = t !== null && Math.abs(t) <= 2; };
    const keep = () => { const t = offset(); if (atTop && t !== null && Math.abs(t) > 2) scroller.scrollTop += t; };
    if (win && win.ResizeObserver) {
      try {
        const o = new win.ResizeObserver(refit);
        o.observe(scroller);
        const above = new win.ResizeObserver(keep);
        const own = pane.body.closest("item-pane-custom-section");
        for (const c of scroller.children || []) if (c !== own) above.observe(c);
        scroller.addEventListener("scroll", seen);
        seen();
        pane.unfit = () => { o.disconnect(); above.disconnect(); scroller.removeEventListener("scroll", seen); };
        return;
      } catch (e) { this.log("resize observer failed: " + e); }
    }
    try {
      win.addEventListener("resize", refit);
      pane.unfit = () => { win.removeEventListener("resize", refit); };
    } catch (e) {}
  },

  // Zotero gives a section drawn while collapsed no async render when it is opened: its conversation is shown then
  watchOpen(pane) {
    let section = null;
    try { section = pane.body.closest("collapsible-section"); } catch (e) {}
    if (!section || typeof section.addEventListener !== "function") return;
    const opened = () => {
      if (section.open && this.panes.get(pane.body) === pane && !pane.showing) this.loadPane(pane.body);
    };
    section.addEventListener("toggle", opened);
    pane.unopen = () => { section.removeEventListener("toggle", opened); };
  },

  // the section's observers and listeners go with its pane
  releaseFit(pane) {
    try { if (pane.unfit) pane.unfit(); } catch (e) {}
    try { if (pane.unopen) pane.unopen(); } catch (e) {}
  },

  // a section's two views: the chat (the section itself, as before) and the annotation tab's
  viewOf(pane, kind) { return kind === "annotate" ? pane.annot : pane; },

  paneViews(pane) { return [pane, pane.annot]; },

  // whether a section's paper has a run of this kind going on or waiting; a held queued message does not wait for a run
  busyKind(pane, kind) {
    return [...this.active].some(j => pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === kind)
      || pane.keys.some(k => this.paperRuns(k).some(r => r.kind === kind))
      || this.queue.some(j => pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === kind && !this.isHeld(j));
  },

  // each tab keeps the words typed to it
  setTab(pane, kind) {
    const before = this.unsentKey(pane);
    this.keepUnsent(pane);
    pane.tab = kind === "annotate" ? "annotate" : "chat";
    this.closePopover(pane);
    this.show(pane.confirmRow, false);   // a question in place is the tab's it was asked on
    this.swapUnsent(pane, before);
    this.paintPane(pane);
    const view = this.viewOf(pane, pane.tab);
    if (view.scrollPending && view.list.clientHeight) { view.scrollPending = false; view.list.scrollTop = view.list.scrollHeight; }
  },

  renderPane(doc, body, item) {
    const old = this.panes.get(body);
    if (old) { this.releaseFit(old); this.releaseLayer(old); }
    body.replaceChildren();
    const keys = this.paneKeys(item);
    // shownKey, shownConv, shownPath: the conversation shown; live while that is the transcript of the running or latest
    // run; turns, question, context: what its log says of it
    const pane = { doc, body, item, keys, shownKey: null, shownConv: null, shownPath: null, live: false, history: false, past: null,
                   turns: 0, question: false, context: null, preferKey: old ? old.preferKey : null,
                   observer: old ? old.observer : null, seen: !!(old && old.seen), scroller: null, unfit: null };
    this.panes.set(body, pane);
    const win = doc.defaultView;
    if (!pane.observer && win && win.IntersectionObserver) {
      try {
        pane.observer = new win.IntersectionObserver(entries => {
          const current = this.panes.get(body);
          if (current && entries.length) current.seen = entries[entries.length - 1].isIntersecting;
        });
        pane.observer.observe(body);
      } catch (e) { this.log("observer failed: " + e); }
    }
    const div = (cls, text) => {
      const d = doc.createElement("div");
      d.className = cls;
      if (text) d.textContent = text;
      return d;
    };
    const box = pane.box = div("scholium-pane");
    pane.agent = doc.createElement("select");
    pane.model = doc.createElement("select");
    pane.effort = doc.createElement("select");
    pane.agent.className = pane.model.className = pane.effort.className = "scholium-select";
    pane.agent.addEventListener("change", () => { this.switchAgent(pane, pane.agent.value).catch(e => this.log("switch failed: " + e)); });
    pane.model.addEventListener("change", () => { this.choose(this.agent() + "Model", pane.model.value); });
    pane.effort.addEventListener("change", () => { this.choose(this.agent() + "Effort", pane.effort.value); });
    this.fillSelects(pane);
    // the tabs with the conversation tools and the ⋯ menu, then the settings chip with the state line; the selects live in
    // the chip's layer
    const head = div("scholium-tabs");
    head.setAttribute("role", "tablist");
    const tab = (kind, label) => {
      const b = doc.createElement("button");
      b.className = "scholium-tab";
      b.setAttribute("role", "tab");
      const dot = doc.createElement("span");
      dot.className = "scholium-tab-dot";
      b.append(doc.createTextNode(label), dot);
      b.addEventListener("click", () => { this.setTab(pane, kind); });
      // ← and →, Home and End choose the other tab and take the focus to it; Tab reaches the chosen one only (paintPane)
      b.addEventListener("keydown", e => {
        if (e.isComposing || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
        e.preventDefault();
        const to = e.key === "Home" ? "chat" : e.key === "End" ? "annotate" : kind === "chat" ? "annotate" : "chat";
        if (to !== pane.tab) this.setTab(pane, to);
        try { (to === "chat" ? pane.tabChat : pane.tabAnnotate).focus(); } catch (err) {}
      });
      return [b, dot];
    };
    [pane.tabChat, pane.tabChatDot] = tab("chat", this.text("tabChat"));
    [pane.tabAnnotate, pane.tabAnnotateDot] = tab("annotate", this.text("tabAnnotate"));
    pane.newChat = this.iconButton(doc, "add", this.text("newChat"), () => { this.newChat(pane).catch(e => this.log("new chat failed: " + e)); });
    pane.historyButton = this.iconButton(doc, "history", this.text("historyButton"), e => {
      this.toggleHistory(pane, this.byKeyboard(e)).catch(err => this.log("history failed: " + err));
    });
    pane.chip = doc.createElement("button");
    pane.chip.className = "scholium-chip";
    this.paintChip(pane);
    pane.chip.addEventListener("click", e => {
      if (!this.closePopover(pane, "settings")) this.openSettingsLayer(pane, this.byKeyboard(e));
    });
    pane.more = doc.createElement("button");
    pane.more.className = "scholium-icon";
    pane.more.textContent = "⋯";
    pane.more.title = this.text("moreTitle");
    pane.more.setAttribute("aria-label", this.text("moreTitle"));
    pane.more.setAttribute("aria-haspopup", "menu");
    pane.more.addEventListener("click", e => {
      if (!this.closePopover(pane, "menu")) this.openMoreMenu(pane, this.byKeyboard(e));
    });
    head.append(pane.tabChat, pane.tabAnnotate, div("scholium-spacer"), pane.newChat, pane.historyButton, pane.more);
    // a select's dropdown is the window's #ContentSelectDropdown: a choice there is inside the layer
    pane.outside = e => {
      const p = pane.popover;
      const dropdown = !!(e.target && typeof e.target.closest === "function" && e.target.closest("#ContentSelectDropdown"));
      if (p && !dropdown && !p.node.contains(e.target) && !(p.anchor && p.anchor.contains(e.target))) this.closePopover(pane);
    };
    doc.addEventListener("mousedown", pane.outside, true);
    box.addEventListener("keydown", e => { if (e.key === "Escape" && this.escape(pane)) { e.preventDefault(); e.stopPropagation(); } });
    const line = div("scholium-line");
    pane.state = div("scholium-state");          // one line of small text at the right
    // Continue now: the runs of the agent whose limit the tab's next run waits for
    pane.resume = this.paneButton(doc, this.text("resumeNow"), () => {
      const next = this.queue.find(j => pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === pane.tab && !this.isHeld(j));
      const hold = next && this.heldByLimit(next);
      if (hold) this.resumeQueue(hold.agent);
    }, "quiet small");
    line.append(pane.chip, pane.state, pane.resume);
    // the chat view: the earlier conversations and the transcript; the annotation view: its own transcript
    pane.chatView = div("scholium-view chat");
    pane.list = div("scholium-log");
    this.followLinks(pane.list, win);
    pane.chatView.append(pane.list);
    pane.annotView = div("scholium-view annotate");
    pane.annot = { kind: "annotate", doc, list: div("scholium-log"), shownKey: null, shownConv: null, shownPath: null, live: false,
                   history: false, turns: 0, question: false, context: null, draft: null, foldOpen: new Map(), pane };
    this.followLinks(pane.annot.list, win);
    // the introduction is the list's content until a session or a run is drawn there
    pane.annot.own = keys.length === 1 ? this.ownCount(item.libraryID, keys[0]) : 0;
    pane.annotIntro = this.introNode(doc, null, pane.annot.own);
    pane.annot.list.append(pane.annotIntro);
    pane.annotView.append(pane.annot.list);
    pane.kind = "chat";
    pane.pane = pane;               // a view's section: the chat view is the section itself
    pane.foldOpen = new Map();
    pane.tab = old ? old.tab : "chat";
    const pending = this.pendingQuote(pane, keys);
    if (pending) { pane.quote = pending; pane.tab = "chat"; }
    else pane.quote = old && old.item === item ? old.quote || null : null;   // a quote is of the item it was chosen for
    // the other papers of a question about several: those Ask Scholium (N papers) chose, else the ones the section had
    const papers = this.pendingPapersOf(keys);
    if (papers) Object.assign(pane, { others: papers.papers.slice(), othersFor: "pending", preferKey: papers.key, tab: "chat" });
    else Object.assign(pane, old && old.item === item ? { others: old.others || [], othersFor: old.othersFor } : { others: [], othersFor: undefined });
    // below the transcript, a message box as in a chat: a question or extra instructions for a new run, or a
    // follow-up; it grows with the text
    // the saved prompts above the chat's box (paintSaved)
    pane.saved = div("scholium-saved");
    const talk = pane.composer = div("scholium-composer");
    pane.input = doc.createElement("textarea");
    pane.input.className = "scholium-input";
    pane.input.setAttribute("rows", "1");
    // without Zotero's look for text boxes (a line under the text on focus, a grey ground on hover): the
    // box around it shows the focus. no-native on Zotero 8 and later, no-windows-native on Zotero 7
    pane.input.setAttribute("no-native", "true");
    pane.input.setAttribute("no-windows-native", "true");
    pane.input.value = this.unsent.get(this.unsentKey(pane)) || "";   // what was typed here before and not sent
    pane.input.addEventListener("input", () => {
      this.keepUnsent(pane);
      this.fitInput(pane);
    });
    pane.input.addEventListener("keydown", e => {
      const what = this.sendKey(e, pane.input.value);
      if (!what || pane.composer.hidden) return;
      e.preventDefault();
      this.sendFromPane(pane, what === "invert");
    });
    // the messages queued while the paper runs, at the top of the box (paintQueue)
    pane.queueBox = div("scholium-queue");
    // a question in place of a dialog, above the words
    pane.confirmRow = div("scholium-confirm");
    this.show(pane.confirmRow, false);
    pane.heldRow = div("scholium-confirm");
    this.show(pane.heldRow, false);
    // the passage of the reader's selection that goes with the next message, and the other papers of the conversation
    pane.quoteBox = div("scholium-quote");
    pane.papersBox = div("scholium-papers");
    pane.sendRow = div("scholium-send-row");
    pane.hint = doc.createElement("span");
    pane.hint.className = "scholium-hint";
    // the context the conversation's session takes up, once its agent said
    pane.ring = doc.createElement("span");
    pane.ring.className = "scholium-ring";
    pane.ring.addEventListener("click", () => { this.openContextLayer(pane); });
    // a click leaves the focus where it was (the message box keeps its caret); Tab reaches the ring, Enter or Space opens it
    pane.ring.addEventListener("mousedown", e => { e.preventDefault(); });
    this.keyButton(pane.ring, () => { this.openContextLayer(pane, true); });
    pane.send = doc.createElement("button");
    pane.send.className = "scholium-round send";
    pane.send.addEventListener("click", () => {
      if (pane.send.className.includes("stop")) this.stopFromPane(pane);
      else this.sendFromPane(pane);
    });
    // the annotation tab's button: Annotate, or Annotate again once the tab shows a session
    pane.annotGo = this.paneButton(doc, this.text("annotateThis"), () => { this.annotateFromPane(pane); }, "primary small");
    pane.sendRow.append(pane.hint, pane.ring, pane.send, pane.annotGo);
    talk.append(pane.queueBox, pane.confirmRow, pane.heldRow, pane.papersBox, pane.quoteBox, pane.input, pane.sendRow);
    box.append(head, line, pane.chatView, pane.annotView, pane.saved, talk);
    body.append(box);
    this.fitPane(pane);
    this.watchFit(pane);
    this.watchOpen(pane);
    // the running paper's transcript at once; another conversation once its log is read (loadHistory)
    for (const k of keys) for (const r of this.paperRuns(k)) this.showLive(pane, r);
    this.paintPane(pane);
    // a passage or papers asked about before the section was drawn: the words to them go in the box
    if (pending || papers) { try { pane.input.focus(); } catch (e) {} }
    this.loadModels().catch(() => {});
    // the conversation and the annotation session now: Zotero skips the async render of an item it did last when the item
    // comes back after another item's sync render; a collapsed section loads them when it is opened (watchOpen)
    let section = null;
    try { section = body.closest("collapsible-section"); } catch (e) {}
    if (!section || section.open !== false) this.loadPane(body);
  },

  // a drawing's conversation and annotation session, read once: the async render after the sync one waits for the same load
  loadPane(body) {
    const pane = this.panes.get(body);
    if (!pane) return Promise.resolve();
    if (!pane.loading) pane.loading = this.loadHistory(body).catch(e => { this.log("history failed: " + e); });
    return pane.loading;
  },
});
