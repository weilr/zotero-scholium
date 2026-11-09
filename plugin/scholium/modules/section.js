// ScholiumRunner, continued: the main windows and the items list's menu, log events as display entries, the Scholium
// section (its registration, layers, settings chip, models and frame), the profile editor, Markdown and formulas,
// sentence citations and links

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

  // one stream-json event as display entries, in the manner of Claude Code's transcript
  entries(event) {
    const out = [];
    if (!event || typeof event !== "object") return out;
    if (typeof event.method === "string") return this.codexEntries(event);
    if (event.type === "system" && event.subtype === "init") {
      out.push({ kind: "info", model: true, text: `${this.agentName(event.agent === "codex" ? "codex" : "claude")} · ${event.model || "?"}` });
    }
    const content = event.message && Array.isArray(event.message.content) ? event.message.content : [];
    // Claude Code not signed in says so in a message and in its result: the result's line says what to do
    if (event.type === "assistant" && event.error !== "authentication_failed") {
      for (const c of content) {
        if (!c) continue;
        if (c.type === "text" && String(c.text || "").trim()) out.push({ kind: "text", text: String(c.text).trim(), error: !!event.error });
        else if (c.type === "tool_use") out.push({ kind: "tool", name: String(c.name), text: `${c.name}(${this.toolSummary(c.input || {})})` });
      }
    }
    if (event.type === "user") {
      for (const c of content) {
        if (c && c.type === "tool_result") out.push({ kind: "result", text: this.resultSummary(c.content), error: !!c.is_error });
      }
    }
    // a compaction: the agent's status, the boundary it leaves, and the plugin's own lines
    if (event.type === "system" && event.subtype === "status" && event.status === "compacting") out.push({ kind: "compacting" });
    if (event.type === "system" && event.subtype === "status" && event.compact_result && event.compact_result !== "success") {
      out.push({ kind: "compactFailed", text: String(event.compact_error || event.compact_result) });
    }
    if (event.type === "system" && event.subtype === "compact_boundary") {
      const m = event.compact_metadata || {};
      out.push({ kind: "compacted", trigger: m.trigger === "auto" ? "auto" : "manual", pre: Number(m.pre_tokens) || 0, post: Number(m.post_tokens) || 0 });
    }
    if (event.type === "scholium" && event.subtype === "compact") out.push({ kind: "compacting", text: String(event.text || "") });
    if (event.type === "scholium" && event.subtype === "compacted") {
      out.push({ kind: "compacted", trigger: "manual", pre: Number(event.pre) || 0, post: Number(event.post) || 0 });
    }
    // a run that goes on with the turn before (a second try, a continuation) has no words of its own; a compaction is a
    // run of its own
    if (event.type === "scholium" && event.subtype === "run") {
      out.push(Object.assign({ kind: "run", at: event.at || 0, compact: !!event.compact }, event.user === null && !event.compact ? { continues: true } : {}));
    }
    // an annotation's line carries its extra instructions
    if (event.type === "scholium" && event.subtype === "steer") {
      out.push(Object.assign({ kind: "prompt", text: String(event.text || ""), steer: true },
                             event.quote && event.quote.text ? { quote: this.quoteOf(event.quote) } : {}));
    }
    if (event.type === "scholium" && event.subtype === "prompt") {
      out.push(Object.assign({ kind: "prompt", text: String(event.text || "") }, event.annotate ? { annotate: true, extra: String(event.extra || "") } : {},
                             event.quote && event.quote.text ? { quote: this.quoteOf(event.quote) } : {}));
    }
    if (event.type === "scholium" && event.subtype === "unfinished" && String(event.text || "").trim()) {
      out.push({ kind: "text", text: String(event.text).trim(), unfinished: true });
    }
    if (event.type === "scholium" && event.subtype === "continue") {
      out.push({ kind: "info", text: this.text(event.reason === "update" ? "continuedUpdate" : event.reason === "throttle" ? "continuedThrottle" : "continued") });
    }
    // the end of a run without a result of its own: cancelled, failed before a result, interrupted; with how long it ran
    if (event.type === "scholium" && event.subtype === "end") {
      out.push(Object.assign({ kind: "final", text: String(event.text || "").trim() || this.text(event.outcome || "failed"), error: true },
                             event.outcome === "cancelled" ? { cancelled: true } : {},
                             this.AGENTS.includes(event.skill) ? { skill: event.skill } : {},
                             Number.isFinite(event.duration_ms) && event.duration_ms >= 0 ? { duration: event.duration_ms } : {}));
    }
    if (event.type === "scholium" && event.subtype === "retry") out.push({ kind: "info", text: this.text("retrying") });
    // the numbers an annotation's card shows, as counted when it ended
    if (event.type === "scholium" && event.subtype === "counts") {
      const n = k => Number(event[k]) || 0;
      out.push({ kind: "counts", highlights: n("highlights"), core: n("core"), margin: n("margin"), notes: n("notes"), readingNotes: n("readingNotes"),
                 warnings: typeof event.warnings === "string" ? event.warnings : null, turns: n("turns"), tokens: n("tokens"), at: n("at") });
    }
    // when a run ended, under what it showed; or when its wait (for a limit, a second try) was stopped
    if (event.type === "scholium" && event.subtype === "time" && event.at > 0) out.push(Object.assign({ kind: "time", text: this.clock(event.at), at: event.at }, event.waited ? { waited: true } : {}));
    // a successful result repeats Claude's last message; only a failed run's result is shown, with Claude Code's errors
    // when it has no text, and not when they only say the session is gone (a new one goes on, or the end says why)
    if (event.type === "result" && (event.is_error || (event.subtype && event.subtype !== "success"))) {
      const errors = Array.isArray(event.errors) ? event.errors.map(String).join("\n") : "";
      const text = String(event.result || errors || this.failureText(event.subtype)).trim();
      if (event.result || !this.gone(errors)) out.push({ kind: "final", text: /Please run \/login\b/.test(text) ? this.text("notSignedIn", "claude") : text, error: true });
    }
    return out;
  },

  // what the subtype of a failed run's result says
  failureText(subtype) {
    return (/^error_/.test(String(subtype || "")) && this.text(subtype)) || this.text("failed");
  },

  toolSummary(input) {
    const value = input.command || input.file_path || input.skill || input.pattern || input.path || input.url || input.description || "";
    const first = String(value).trim().split("\n")[0];
    return first.length > 160 ? first.slice(0, 159) + "…" : first;
  },

  resultSummary(content) {
    const text = typeof content === "string" ? content
      : Array.isArray(content) ? content.map(c => (c && c.type === "text" ? c.text : "")).join("\n") : "";
    const lines = text.trim().split("\n");
    let out = lines.slice(0, 4).join("\n");
    if (lines.length > 4) out += `\n… +${lines.length - 4}`;
    if (out.length > 600) out = out.slice(0, 599) + "…";
    return out || this.text("noOutput");
  },

  // one Codex notification as display entries, in the same manner: its messages, each command and
  // its output, file changes, tool calls; its reasoning is left out, as Claude's thinking is
  codexEntries(msg) {
    const item = msg.params && msg.params.item;
    if (!item || typeof item !== "object") return [];
    if (msg.method === "item/started" && item.type === "contextCompaction") return [{ kind: "compacting" }];
    if (msg.method === "item/completed" && item.type === "contextCompaction") return [{ kind: "compacted", trigger: "auto", pre: 0, post: 0 }];
    if (msg.method === "item/started") {
      return item.type === "commandExecution"
        ? [{ kind: "tool", name: "Shell", text: `Shell(${this.toolSummary({ command: this.shellCommand(item.command) })})` }] : [];
    }
    if (msg.method !== "item/completed") return [];
    const failed = item.status === "failed" || item.status === "declined";
    if (item.type === "agentMessage") return String(item.text || "").trim() ? [{ kind: "text", text: String(item.text).trim() }] : [];
    if (item.type === "commandExecution") {
      const output = String(item.aggregatedOutput || "");
      return [{ kind: "result", text: failed && !output.trim() ? this.itemStatus(item) : this.resultSummary(output),
                error: failed || (typeof item.exitCode === "number" && item.exitCode !== 0) }];
    }
    if (item.type === "fileChange") {
      return (item.changes || []).filter(c => c && c.path).map(c => ({ kind: "tool", name: "Edit", text: `Edit(${this.toolSummary({ file_path: c.path })})` }))
        .concat(failed ? [{ kind: "result", text: this.itemStatus(item), error: true }] : []);
    }
    if (item.type === "mcpToolCall") {
      const name = `${item.server}.${item.tool}`;
      return [{ kind: "tool", name, text: `${name}(${this.toolSummary(item.arguments || {})})` },
              { kind: "result", text: item.error ? String(item.error.message || item.status) : this.resultSummary(item.result && item.result.content),
                error: !!item.error || failed }];
    }
    if (item.type === "webSearch") return [{ kind: "tool", name: "WebSearch", text: `WebSearch(${this.toolSummary({ pattern: item.query })})` }];
    return [];
  },

  itemStatus(item) { return this.text(item.status === "declined" ? "itemDeclined" : "itemFailed"); },

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
    const shown = this.revealSection(reader._window, pane);
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

  // the section in view in the reader's side pane: the context pane opened, the section opened, the item pane scrolled to
  // it; each step may be missing. A section not drawn yet is found in the side pane of the reader's tab (Zotero draws it
  // once it is scrolled to)
  async revealSection(win, pane = null, tabID = null) {
    try { if (win && win.ZoteroContextPane && win.ZoteroContextPane.collapsed) win.ZoteroContextPane.collapsed = false; } catch (e) {}
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
      pane.escRun = this.job;
      setTimeout(() => this.paintHint(pane), this.ESC_MS + 50);
    }
    this.paintHint(pane);
    return true;
  },

  // whether a first Esc asks to stop: pressed a moment ago, on the run that still goes on. Once that run ends or another
  // starts, the press is forgotten, and paintPane's hint says so
  escArmed(pane) {
    return !!pane.escAt && Date.now() - pane.escAt < this.ESC_MS && pane.escRun === this.job;
  },

  // the run of the tab shown stops; a paper of it that only waits there leaves the queue, the other tab's wait stays. The
  // tab's queued messages stay, held until Resume, as Codex holds its queue after an interruption
  stopFromPane(pane) {
    const mine = j => pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === pane.tab;
    for (const j of this.queue) if (j.qid && mine(j)) this.heldQueues.add(this.queueKey(j));
    if (this.job && mine(this.job.source)) this.cancel();
    else this.dequeue(pane.keys, pane.tab, { rows: false });
  },

  paintHint(pane) {
    const armed = this.escArmed(pane);
    const said = pane.said && Date.now() - pane.said.at < this.SAID_MS ? pane.said.text : "";
    const mod = Services.appinfo && Services.appinfo.OS === "Darwin" ? "⌘" : "Ctrl";
    const shortcut = this.sendShortcut();
    pane.hint.textContent = armed ? this.text("escAgain") : said
      || (shortcut === "enter" ? this.text("sendHintEnter") : shortcut === "cmdIfMultiline" ? this.text("sendHintMultiline", mod) : this.text("sendHint", mod));
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
    const c = view.live && this.showsRun(view) ? this.job.context : view.context;
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
    const c = (view.live && this.showsRun(view) ? this.job.context : view.context) || {};
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

  // the models the agent offers, with the effort levels of each, asked once per session
  async loadModels(agent = this.agent()) {
    if (this.models[agent] || this.modelsLoading[agent] || Date.now() - (this.modelsAsked[agent] || 0) < 60000) return;
    this.modelsAsked[agent] = Date.now();
    this.modelsLoading[agent] = true;
    try {
      const models = agent === "codex" ? await this.askCodexModels() : await this.askModels();
      if (models) {
        this.models[agent] = models;
        for (const pane of this.panes.values()) this.fillSelects(pane);
      }
    } catch (e) { this.log("model list failed: " + ((e && e.message) || JSON.stringify(e))); }
    finally { this.modelsLoading[agent] = false; }
  },

  // Claude Code's models: the initialize request of its stream-json protocol answers without calling
  // a model; only the model list is kept

  async askModels() {
    const claude = await this.findClaude();
    if (!claude) return null;
    const proc = await this.subprocess().call(Object.assign({
      command: claude, arguments: ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                                   "--strict-mcp-config", "--settings", JSON.stringify({ disableAllHooks: true })],
      workdir: Zotero.DataDirectory.dir, stderr: "stdout",
    }, await this.agentEnv()));
    // after 60 s the process is killed and the wait ends, since a child it started may keep its output open (readOutput)
    let late = false, timer = null;
    const deadline = new Promise(resolve => { timer = setTimeout(() => { late = true; try { proc.kill(); } catch (e) {} resolve(null); }, 60000); });
    const read = (async () => {
      await proc.stdin.write(JSON.stringify({ type: "control_request", request_id: "scholium-models",
                                              request: { subtype: "initialize" } }) + "\n");
      await proc.stdin.close();
      let buffer = "";
      for (;;) {
        const chunk = await proc.stdout.readString();
        if (!chunk || late) return null;
        buffer += chunk;
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const raw of lines) {
          let event;
          try { event = JSON.parse(raw); } catch (e) { continue; }
          const r = event && event.type === "control_response" && event.response;
          if (r && r.request_id === "scholium-models") return this.modelOptions(r.response && r.response.models);
        }
      }
    })();
    try { return await Promise.race([read, deadline]); }
    finally {
      clearTimeout(timer);
      try { proc.kill(); } catch (e) {}
    }
  },

  // Claude Code's model list as options; its "default" entry is the empty value, which passes no --model
  modelOptions(list) {
    if (!Array.isArray(list)) return null;
    const out = [];
    for (const m of list) {
      if (!m || typeof m.value !== "string" || !m.value) continue;
      const value = m.value === "default" ? "" : m.value;
      if (out.some(o => o.value === value)) continue;
      const efforts = Array.isArray(m.supportedEffortLevels) ? m.supportedEffortLevels.map(String)
        : m.supportsEffort ? this.EFFORTS : [];
      let label = String(m.displayName || m.value);
      if (!value) {
        const twin = list.find(o => o && o !== m && o.value !== "default" && o.resolvedModel && o.resolvedModel === m.resolvedModel);
        const name = (twin && twin.displayName) || m.resolvedModel || "";
        label = name ? this.text("paneClaudeDefaultModel", name) : this.text("paneClaudeDefault");
      }
      out.push({ value, label, title: String(m.description || ""), efforts });
    }
    if (!out.length) return null;
    if (!out.some(o => o.value === "")) out.unshift({ value: "", label: this.text("paneClaudeDefault"), title: "", efforts: this.EFFORTS });
    return out;
  },

  // Codex's models and their effort levels (model/list); its configuration is not read, so the model it runs by default
  // is the one a new thread last named (codexDefault), else unnamed; no model is called
  async askCodexModels() {
    const codex = await this.findCodex();
    if (!codex) return null;
    const rpc = await this.codexServer(codex, Zotero.DataDirectory.dir);
    const timer = setTimeout(() => rpc.close(), 60000);
    try {
      await this.codexHello(rpc);
      const list = await rpc.request("model/list", {});
      return this.codexModelOptions(list && list.data, String(this.getPref("codexDefault") || ""));
    } finally {
      clearTimeout(timer);
      rpc.close();
    }
  },

  // the model a new Codex thread ran with none chosen, which is Codex's own default: kept, and named by the default option
  noteCodexDefault(name) {
    if (!name || this.getPref("codexDefault") === name) return;
    try { Zotero.Prefs.set(this.pref + "codexDefault", name, true); } catch (e) { this.log("preference not saved: " + e); }
    const options = this.models.codex, first = options && options[0];
    if (!first || first.value !== "") return;
    const twin = options.find(o => o.value === name);
    Object.assign(first, { label: this.text("paneCodexDefaultModel", twin ? twin.label : name), efforts: twin ? twin.efforts : this.CODEX_EFFORTS });
    for (const pane of this.panes.values()) this.fillSelects(pane);
  },

  // Codex's model list as options; the empty value runs Codex's own default: the model of its config.toml as a new
  // thread named it, named by the option once known, with that model's levels. Hidden models are left out.
  codexModelOptions(list, configured = "") {
    if (!Array.isArray(list)) return null;
    const out = [];
    for (const m of list) {
      if (!m || typeof m.model !== "string" || !m.model || m.hidden || out.some(o => o.value === m.model)) continue;
      const efforts = Array.isArray(m.supportedReasoningEfforts)
        ? m.supportedReasoningEfforts.map(e => String(e && typeof e === "object" ? e.reasoningEffort || "" : e || "")).filter(Boolean)
        : this.CODEX_EFFORTS;
      out.push({ value: m.model, label: String(m.displayName || m.model), title: String(m.description || ""), efforts });
    }
    if (!out.length) return null;
    const name = configured;
    const twin = out.find(o => o.value === name);
    out.unshift({ value: "", label: name ? this.text("paneCodexDefaultModel", twin ? twin.label : name) : this.text("paneCodexDefault"),
                  title: "", efforts: twin ? twin.efforts : this.CODEX_EFFORTS });
    return out;
  },

  // the agent's model options: its list once it answered, and the chosen model in any case
  modelChoices(agent = this.agent()) {
    const saved = this.modelPref(agent), efforts = agent === "codex" ? this.CODEX_EFFORTS : this.EFFORTS;
    const list = this.models[agent]
      || [{ value: "", label: this.text(agent === "codex" ? "paneCodexDefault" : "paneClaudeDefault"), title: "", efforts }];
    return list.some(m => m.value === saved) ? list : list.concat([{ value: saved, label: saved, title: "", efforts }]);
  },

  // the effort levels the agent's chosen model accepts
  effortChoices(agent = this.agent()) {
    const saved = this.modelPref(agent);
    return this.modelChoices(agent).find(m => m.value === saved).efforts;
  },

  // a pane's selects from the model list and the saved choices
  fillSelects(pane) {
    try {
      const option = (value, label, title) => {
        const o = pane.doc.createElement("option");
        o.value = value;
        o.textContent = label;
        if (title) o.title = title;
        return o;
      };
      pane.agent.replaceChildren(...this.AGENTS.map(a => option(a, this.agentName(a))));
      pane.agent.value = this.agent();
      pane.model.replaceChildren(...this.modelChoices().map(m => option(m.value, m.label, m.title)));
      pane.model.value = this.modelPref();
      const levels = this.effortChoices();
      pane.effort.replaceChildren(...(levels.length ? levels.map(e => option(e, e)) : [option("", this.text("paneNoEffort"))]));
      pane.effort.value = this.effort();
      pane.effort.disabled = !levels.length;
      if (pane.chip) this.paintChip(pane);
    } catch (e) { this.log("selects failed: " + e); }
  },

  // a choice is saved and shown by every pane; another agent's models are asked for
  choose(prefName, value) {
    try { Zotero.Prefs.set(this.pref + prefName, value, true); } catch (e) { this.log("preference not saved: " + e); }
    for (const pane of this.panes.values()) this.fillSelects(pane);
    if (prefName === "agent") this.loadModels().catch(() => {});
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
    return !!(this.job && pane.keys.includes(this.job.key) && (this.job.source.kind || "chat") === kind)
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
    talk.append(pane.queueBox, pane.confirmRow, pane.papersBox, pane.quoteBox, pane.input, pane.sendRow);
    box.append(head, line, pane.chatView, pane.annotView, pane.saved, talk);
    body.append(box);
    this.fitPane(pane);
    this.watchFit(pane);
    this.watchOpen(pane);
    // the running paper's transcript at once; another conversation once its log is read (loadHistory)
    if (this.job && keys.includes(this.job.key)) this.showLive(pane, this.job.key, this.job.source.kind || "chat");
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

  // the annotation profile, <data dir>/zotero-scholium/profile.md, which every run follows; a missing
  // one starts as scholium.py's template, so that `scholium profile --from-library` keeps the rules
  PROFILE_TEMPLATE: "# Annotation profile\n\n## User's rules (always win)\n\n"
    + "Rules recorded in this section take precedence over the learned statistics above. Re-running\n"
    + "`profile --from-library` regenerates the sections above and leaves this section unchanged.\n\n"
    + "- (none yet; add rules here, e.g. \"comments are translations\", \"two colours only: red = core, yellow = other\")\n",

  profilePath() { return PathUtils.join(Zotero.DataDirectory.dir, "zotero-scholium", "profile.md"); },

  // the profile's editor: a sheet over the Zotero window of the button, one at a time. It is part of
  // the window's own page, like the section, so it needs no page or window of its own. `opener` gets the focus back when
  // it closes (else the element that had it)
  openProfile(doc, opener = null) {
    try {
      if (this.editor) {
        this.editor.input.focus();
        return this.editor;
      }
      return this.renderProfileEditor(doc, opener);
    } catch (e) {
      this.log("profile editor failed: " + e);
      return null;
    }
  },

  // the editor: profile.md as it is, in a plain text box; the file keeps its line ends
  renderProfileEditor(doc, opener = null) {
    const win = doc.defaultView;
    const el = (tag, cls, text) => {
      const e = doc.createElement(tag);
      e.className = cls;
      if (text) e.textContent = text;
      return e;
    };
    const ed = { doc, win, path: this.profilePath(), disk: null, eol: "\n", dirty: false, readFailed: false, message: null,
                 before: opener || doc.activeElement };
    ed.root = el("div", "scholium-sheet-backdrop");
    ed.root.id = "scholium-profile-sheet";
    const sheet = ed.sheet = el("div", "scholium-sheet");
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-label", this.text("profileTitle"));
    const head = el("div", "scholium-editor-head");
    const path = el("div", "scholium-editor-path", ed.path);
    path.title = ed.path;
    head.append(el("div", "scholium-sheet-title", this.text("profileTitle")), el("div", "scholium-editor-about", this.text("profileAbout")), path);
    // the text on the left, on the right as Markdown shows it, as it is typed
    ed.input = el("textarea", "scholium-editor");
    ed.input.setAttribute("spellcheck", "false");
    ed.input.addEventListener("input", () => {
      ed.dirty = true;
      ed.message = null;
      this.paintEditor(ed);
      this.paintPreview(ed);
    });
    ed.input.addEventListener("scroll", () => { this.syncPreview(ed); });
    ed.preview = el("div", "scholium-preview scholium-markdown");
    this.followLinks(ed.preview, win);
    const panes = el("div", "scholium-editor-panes");
    panes.append(ed.input, ed.preview);
    ed.status = el("span", "scholium-hint");
    ed.save = this.paneButton(doc, this.text("profileSave"), () => {
      this.saveProfile(ed).then(ok => { if (ok) this.closeProfile(ed, false); });
    }, "primary");
    ed.cancel = this.paneButton(doc, this.text("profileCancel"), () => { this.closeProfile(ed); });
    const foot = el("div", "scholium-editor-foot");
    foot.append(ed.status, el("span", "scholium-spacer"), ed.cancel, ed.save);
    sheet.append(head, panes, foot);
    ed.root.append(sheet);
    // the sheet's keys stay in the sheet: Esc closes it, Ctrl+S saves, Tab and Shift+Tab go round its controls. The
    // window hears them first, so they work wherever the focus is while the sheet is open (a click on the backdrop)
    ed.onKey = e => {
      if (e.isComposing) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        this.closeProfile(ed);
      } else if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        e.stopPropagation();
        this.saveProfile(ed);
      } else if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.metaKey) this.sheetTab(ed, e);
    };
    sheet.addEventListener("keydown", ed.onKey);
    win.addEventListener("keydown", ed.onKey, true);
    // back in Zotero from another program: the file as it is now, unless it is being edited here
    ed.onFocus = () => { if (!ed.dirty) this.loadProfile(ed); };
    win.addEventListener("focus", ed.onFocus);
    doc.documentElement.append(ed.root);
    this.editor = ed;
    return this.loadProfile(ed).then(() => { try { ed.input.focus(); } catch (e) {} return ed; });
  },

  async loadProfile(ed) {
    let text = null;
    try {
      if (await this.exists(ed.path)) text = await IOUtils.readUTF8(ed.path);
    } catch (e) {
      Object.assign(ed, { readFailed: true, message: { text: this.text("profileReadFailed", String(e && e.message || e)), error: true } });
      this.paintEditor(ed);
      return;
    }
    if (ed.loaded && text === ed.disk) {
      if (ed.readFailed) { Object.assign(ed, { readFailed: false, message: null }); this.paintEditor(ed); }
      return;
    }
    // a missing profile starts as the template and is written on saving
    Object.assign(ed, { loaded: true, disk: text, eol: text && text.includes("\r\n") ? "\r\n" : "\n", dirty: false, readFailed: false, message: null });
    ed.input.value = (text === null ? this.PROFILE_TEMPLATE : text).replace(/\r\n/g, "\n");
    this.paintEditor(ed);
    this.paintPreview(ed);
  },

  async saveProfile(ed) {
    if (ed.readFailed) return false;
    try {
      const now = (await this.exists(ed.path)) ? await IOUtils.readUTF8(ed.path) : null;
      if (now !== ed.disk && !Services.prompt.confirm(ed.win, this.text("profileTitle"), this.text("profileChanged"))) {
        ed.message = { text: this.text("profileNotSaved"), error: true };
        this.paintEditor(ed);
        return false;
      }
      const text = String(ed.input.value).replace(/\r\n/g, "\n").replace(/\n/g, ed.eol);
      await IOUtils.makeDirectory(PathUtils.join(Zotero.DataDirectory.dir, "zotero-scholium"), { createAncestors: true, ignoreExisting: true });
      await IOUtils.writeUTF8(ed.path, text, { tmpPath: ed.path + ".tmp" });
      Object.assign(ed, { disk: text, dirty: false, message: { text: this.text("profileSaved", this.clock(Date.now())), error: false } });
      this.paintEditor(ed);
      return true;
    } catch (e) {
      this.log("profile not saved: " + e);
      ed.message = { text: this.text("profileFailed", String(e && e.message || e)), error: true };
      this.paintEditor(ed);
      return false;
    }
  },

  mayCloseProfile(ed) {
    return !ed.dirty || Services.prompt.confirm(ed.win, this.text("profileTitle"), this.text("profileDiscard"));
  },

  // Tab from the sheet's last control goes to its first, Shift+Tab from its first to its last; from outside the sheet
  // either goes into it. The links of the preview are on the way
  sheetTab(ed, e) {
    const links = typeof ed.preview.querySelectorAll === "function" ? [...ed.preview.querySelectorAll(".scholium-link[tabindex]")] : [];
    const items = [ed.input, ...links, ed.cancel, ed.save].filter(n => n && !n.disabled);
    if (!items.length) return;
    const a = ed.doc.activeElement;
    const first = items[0], last = items[items.length - 1];
    if (a && items.includes(a) && a !== (e.shiftKey ? first : last)) return;
    e.preventDefault();
    e.stopPropagation();
    try { (e.shiftKey ? last : first).focus(); } catch (err) {}
  },

  // unsaved changes are kept unless the user lets them go; on shutdown and when the window closes, without asking
  closeProfile(ed, ask = true) {
    if (ask && !this.mayCloseProfile(ed)) return false;
    try { ed.win.removeEventListener("focus", ed.onFocus); } catch (e) {}
    try { ed.win.removeEventListener("keydown", ed.onKey, true); } catch (e) {}
    ed.root.remove();
    if (this.editor === ed) this.editor = null;
    try { if (ed.before && ed.before.isConnected) ed.before.focus(); } catch (e) {}
    return true;
  },

  // the line under the text: an error or the last save, else unsaved changes, a new file, or the keys
  paintEditor(ed) {
    const m = ed.message;
    const key = Services.appinfo && Services.appinfo.OS === "Darwin" ? "⌘" : "Ctrl";
    ed.status.textContent = m && (m.error || !ed.dirty) ? m.text
      : ed.dirty ? this.text("profileDirty")
      : ed.disk === null ? this.text("profileNew")
      : this.text("profileKeys", key);
    ed.status.className = "scholium-hint" + (m && m.error ? " error" : "");
    ed.input.disabled = ed.readFailed;
    ed.save.disabled = ed.readFailed || (!ed.dirty && ed.disk !== null);
  },

  // the preview shows the text in the box, with its unsaved changes
  paintPreview(ed) {
    ed.preview.replaceChildren(...this.renderMarkdown(ed.doc, ed.input.value));
    this.syncPreview(ed);
  },

  // the preview follows the text box's scrolling, by proportion
  syncPreview(ed) {
    const room = ed.input.scrollHeight - ed.input.clientHeight;
    ed.preview.scrollTop = room > 0 ? ed.input.scrollTop / room * (ed.preview.scrollHeight - ed.preview.clientHeight) : 0;
  },

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
      if (m.index > at) parent.append(doc.createTextNode(text.slice(at, m.index)));
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
        const found = this.cites && this.cites.map.get(Number(m[12]));
        parent.append(found ? this.citeNode(doc, this.cites.key, Number(m[12]), found) : doc.createTextNode(m[0]));
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
      const text = doc.createElement("div");
      text.className = "scholium-cite-text";
      text.textContent = s.text;
      card.append(head, text);
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
