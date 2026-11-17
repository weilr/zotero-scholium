// ScholiumRunner, continued: the main windows, the items list's menu, and the reader's selection and its menu

Object.assign(ScholiumRunner, {
  windows() {
    try { return Zotero.getMainWindows ? Zotero.getMainWindows() : [Zotero.getMainWindow()].filter(Boolean); }
    catch (e) { return []; }
  },

  refresh() { this.tidyHeld(); this.paintPanes(); },

  // the labels of the section's header and sidenav button, and the section's stylesheet, in a main window
  addToWindow(win) {
    try { if (win.MozXULElement) win.MozXULElement.insertFTLIfNeeded("scholium.ftl"); } catch (e) {}
    try {
      const doc = win.document;
      const href = this.chrome + "scholium.css";
      let link = doc.getElementById("scholium-style");
      // another version's sheet, left by a copy that a plugin update left running (see ScholiumToggle.start)
      if (link && link.getAttribute("href") !== href) { link.remove(); link = null; }
      if (!link) {
        link = doc.createElementNS("http://www.w3.org/1999/xhtml", "link");
        link.id = "scholium-style";
        link.setAttribute("rel", "stylesheet");
        link.setAttribute("href", href);
        doc.documentElement.append(link);
      }
    } catch (e) { this.log("stylesheet failed: " + e); }
    this.addItemMenu(win);
  },

  // Ask Scholium (N papers) at the end of the items list's context menu, shown while 2 to MAX_PAPERS papers or PDFs are
  // selected; one left by another copy of the plugin goes
  addItemMenu(win) {
    try {
      const doc = win.document;
      const popup = doc.getElementById("zotero-itemmenu");
      if (!popup || this.itemMenus.has(win)) return;
      const old = doc.getElementById("scholium-ask-papers");
      if (old) old.remove();
      const item = doc.createXULElement ? doc.createXULElement("menuitem")
        : doc.createElementNS("http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul", "menuitem");
      item.id = "scholium-ask-papers";
      item.hidden = true;
      item.addEventListener("command", () => { this.askPapers(win, this.askable(win)).catch(e => this.log("ask papers failed: " + e)); });
      const showing = e => {
        if (e && e.target && e.target !== popup) return;   // a submenu's
        const n = this.askable(win).length;
        item.hidden = n < 2 || n > this.MAX_PAPERS;
        if (!item.hidden) item.setAttribute("label", this.text("askPapers", n));
      };
      popup.addEventListener("popupshowing", showing);
      popup.append(item);
      this.itemMenus.set(win, { item, popup, showing });
    } catch (e) { this.log("item menu failed: " + e); }
  },

  removeItemMenu(win) {
    const m = this.itemMenus.get(win);
    if (!m) return;
    this.itemMenus.delete(win);
    try { m.popup.removeEventListener("popupshowing", m.showing); } catch (e) {}
    try { m.item.remove(); } catch (e) {}
  },

  // the papers (regular items) and PDFs selected in a window's items list
  askable(win) {
    let items = [];
    try { items = win.ZoteroPane.getSelectedItems() || []; } catch (e) {}
    return items.filter(i => i && ((i.isRegularItem && i.isRegularItem()) || (i.isPDFAttachment && i.isPDFAttachment())));
  },

  // a paper as a question about several keeps it: its PDF's library and key, and its title
  paperRef(att, title) { return { library: att.libraryID || Zotero.Libraries.userLibraryID, key: att.key, title: String(title || "") }; },

  paperAtt(ref) {
    try { return ref && ref.key ? Zotero.Items.getByLibraryAndKey(ref.library || Zotero.Libraries.userLibraryID, String(ref.key)) : null; }
    catch (e) { return null; }
  },

  // a question about several papers: the first one with a PDF is selected alone and its Chat tab opens on a new
  // conversation, the others in a row of chips above its box (pendingPapers until its section takes them)
  async askPapers(win, items) {
    const papers = [];
    for (const item of items.slice(0, this.MAX_PAPERS)) {
      let r = null;
      try { r = await this.resolve(item); } catch (e) {}
      if (r && !papers.some(p => p.att === r.att)) papers.push(Object.assign(r, { item }));
    }
    if (!papers.length) {
      Services.prompt.alert(win, this.text("headline"), this.text("papersNoPdf"));
      return false;
    }
    const [first, ...rest] = papers;
    const key = this.keyOf(first.att);
    // a new conversation of the first paper, unless it answers now: the question then waits in the one under way
    const keys = this.paneKeys(first.item);
    if (!keys.some(k => this.busy(k, "chat"))) for (const k of keys) await this.chooseConv(k, null);
    const others = rest.map(p => this.paperRef(p.att, p.title));
    this.pendingPapers.set(key, { papers: others, at: Date.now() });
    try { await win.ZoteroPane.selectItem(first.item.id); } catch (e) { this.log("paper not selected: " + e); }
    // a section drawn already (the paper was shown before): it takes them now
    const pane = this.paneFor(win, key);
    if (pane && this.pendingPapers.has(key)) {
      this.pendingPapers.delete(key);
      this.takePapers(pane, others, key);
      await this.showConversation(pane);
    }
    const shown = this.paneFor(win, key);
    if (shown) {
      await this.revealSection(win, shown);
      try { shown.input.focus(); } catch (e) {}
    }
    return true;
  },

  // the other papers of the next question go above the section's box, on the Chat tab; the conversation shown next keeps
  // them (showConversation)
  takePapers(pane, papers, key) {
    Object.assign(pane, { others: papers.slice(), othersFor: "pending", preferKey: key, tab: "chat" });
    this.paintPane(pane);
  },

  // the pending papers of a section's PDFs, within QUOTE_MS
  pendingPapersOf(keys) {
    for (const k of keys) {
      const p = this.pendingPapers.get(k);
      if (!p) continue;
      this.pendingPapers.delete(k);
      if (Date.now() - p.at < this.QUOTE_MS) return { papers: p.papers, key: k };
    }
    return null;
  },

  removeFromWindow(win) {
    if (this.editor && this.editor.doc === win.document) this.closeProfile(this.editor, false);
    this.removeItemMenu(win);
    try {
      // a newer copy that replaced this copy's sheet keeps its sheet and its labels
      const style = win.document.getElementById("scholium-style");
      if (style && style.getAttribute("href") !== this.chrome + "scholium.css") return;
      if (style) style.remove();
      const link = win.document.querySelector('[href="scholium.ftl"]');
      if (link) link.remove();
    } catch (e) {}
  },

  // Ask Scholium in the context menu of a PDF reader's page while text is selected there: an EPUB or a snapshot has no
  // Scholium section
  contextMenuItem({ reader, append }) {
    const a = this.readerSelection(reader);
    if (!a) return;
    const att = reader && Zotero.Items.get(reader.itemID);
    if (!att || att.attachmentContentType !== "application/pdf") return;
    // a reader window of its own (reader.xhtml) has no item pane to ask in
    try { if (/\/reader\.xhtml(?:[?#]|$)/.test(String(reader._window && reader._window.location && reader._window.location.href))) return; } catch (e) {}
    append({ label: this.text("askScholium"), onCommand: () => { this.askAboutSelection(reader, a).catch(e => this.log("ask failed: " + e)); } });
  },

  // the text selected in a reader: the menu's event does not give it; the reader keeps it, with its page and position,
  // as the selection popup's annotation of each view, the view used last first
  readerSelection(reader) {
    try {
      const ir = reader && reader._internalReader, s = ir && ir._state;
      if (!s) return null;
      const popups = ir._lastViewPrimary === false ? [s.secondaryViewSelectionPopup, s.primaryViewSelectionPopup]
        : [s.primaryViewSelectionPopup, s.secondaryViewSelectionPopup];
      for (const p of popups) if (p && p.annotation && String(p.annotation.text || "").trim()) return p.annotation;
    } catch (e) {}
    return null;
  },

  // the passage goes above the chat's box of the paper's section, in the window of the reader
  async askAboutSelection(reader, a) {
    const att = Zotero.Items.get(reader.itemID);
    if (!att) return;
    // the selection's popup closes, as after a colour: the views' selection is cleared (Zotero 7–9's PDF view has no clearSelection:
    // what Zotero 10's does there, drawn again as 7–9 do when an annotation is selected)
    try {
      const ir = reader._internalReader;
      for (const view of [ir && ir._primaryView, ir && ir._secondaryView]) {
        if (!view) continue;
        try {   // a view that throws leaves the other to be cleared
          // Zotero 10's PDF view clears its ranges without drawing the page again
          if (typeof view.clearSelection === "function") {
            view.clearSelection();
            if (typeof view._render === "function") view._render();
            continue;
          }
          if (typeof view._setSelectionRanges === "function") {
            view._setSelectionRanges();
            if (typeof view._render === "function") view._render();
          }
          try { view._iframeWindow.getSelection().removeAllRanges(); } catch (e) {}
        } catch (e) {}
      }
    } catch (e) {}
    const quote = this.quoteOf({ text: String(a.text).replace(/\s+/g, " ").trim(), page: this.pageOf(a), label: a.pageLabel });
    const pane = this.paneFor(reader._window, this.keyOf(att), reader.tabID || null);
    if (!pane) { this.pendingQuotes.set(this.keyOf(att), { quote, at: Date.now() }); await this.revealSection(reader._window, null, reader.tabID || null); return; }
    pane.quote = quote;
    this.setTab(pane, "chat");
    // the section is opened at once and the box takes the focus before its scrolling settles
    const shown = this.revealSection(reader._window, pane, null, true);
    try { pane.input.focus(); } catch (e) {}
    await shown;
    try { if (pane.doc.activeElement !== pane.input) pane.input.focus(); } catch (e) {}
  },

  // a passage asked about while its reader's section was not drawn: taken by the section of that reader (a section whose
  // reader is not known takes it by its PDF) within half a minute
  pendingQuote(pane, keys) {
    const own = this.readerKey(pane);
    for (const k of own ? [own] : keys) {
      const p = this.pendingQuotes.get(k);
      if (!p) continue;
      this.pendingQuotes.delete(k);
      if (Date.now() - p.at < this.QUOTE_MS) return p.quote;
    }
    return null;
  },

  // the PDF of the reader whose side pane holds the section; null outside a reader's tab
  readerKey(pane) {
    try {
      const details = pane.body.closest("item-details");
      const reader = details && details.tabID && Zotero.Reader.getByTabID(details.tabID);
      const att = reader && Zotero.Items.get(reader.itemID);
      return att ? this.keyOf(att) : null;
    } catch (e) { return null; }
  },
});
