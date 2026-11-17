// ScholiumRunner, continued: Save as note, notices and the local API check

Object.assign(ScholiumRunner, {
  NOTE_TAG: "scholium-chat",   // a saved conversation's tag: not the tool's, so Annotate again and Delete annotations leave it
  NOTE_TAGS: new Set(["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code", "strong", "em", "hr",
                      "table", "thead", "tbody", "tr", "th", "td", "sub", "sup", "br"]),

  escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  },

  // the conversation the tab shows as a note of its paper (a note of its own for a PDF without a parent item), tagged
  // scholium-chat; then a notice, and the note selected in the library, where it opens
  async saveAsNote(pane) {
    const view = this.viewOf(pane, pane.tab);
    const key = view.shownKey, id = view.shownConv;
    const att = key && id && view.shownPath && pane.item ? this.attOf(pane.item.libraryID, key) : null;
    if (!att) return null;
    try {
      const library = Zotero.Libraries.get(att.libraryID);
      if (library && library.editable === false) { this.sayUnderBox(pane, this.text("noteReadOnly")); return null; }
      const log = await this.readLog(key, id);
      if (!log) throw new Error(view.shownPath);
      const parent = att.parentID ? Zotero.Items.get(att.parentID) : null;
      await this.loadCitations(key);
      const html = this.withCites(key, () => this.noteHtml(pane.doc, (parent || att).getDisplayTitle(), log.entries));
      const note = new Zotero.Item("note");
      note.libraryID = att.libraryID;
      if (parent) note.parentID = parent.id;
      note.setNote(html);
      note.setTags([{ tag: this.NOTE_TAG }]);
      await note.saveTx();
      this.noteNotice(att);   // the paper stays selected, with its conversation
      return note;
    } catch (e) {
      this.log("note not saved: " + e);
      this.sayUnderBox(pane, this.text("noteNotSaved", String((e && e.message) || e)));
      return null;
    }
  },

  noteNotice(att) {
    try {
      const pw = new Zotero.ProgressWindow({ closeOnClick: true });
      pw.changeHeadline(this.text("headline"));
      const line = new pw.ItemProgress("note", this.text("noteSaved"));
      line.setProgress(100);
      pw.show();
      pw.startCloseTimer(this.NOTICE_MS);
    } catch (e) { this.log("notice failed: " + e); }
  },

  // a conversation as a note's HTML: a heading with the paper's title (noteHeading) and the date it started, then each
  // question with its quoted passage, and each answer with the agent and model that gave it, its Markdown set as the
  // transcript sets it
  noteHtml(doc, title, entries) {
    const esc = s => this.escapeHtml(s);
    const runs = this.runsOf(entries).filter(r => !r.compact);
    const first = runs.find(r => r.start > 0);
    const d = new Date(first ? first.start : Date.now());
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const out = [`<h1>${esc(this.text("noteHeading", title))}</h1>`, `<p>${date}</p>`];
    const was = this.noteTex;
    this.noteTex = true;
    try {
      for (const r of runs) {
        if (r.prompt) {
          if (r.prompt.quote) out.push(`<blockquote><p>${esc(this.quoteLabel(r.prompt.quote))}</p></blockquote>`);
          out.push(`<p><strong>${esc(this.text("noteQuestion"))}</strong> ${esc(r.prompt.text).replace(/\n/g, "<br>")}</p>`);
        }
        if (!r.answer.length) continue;
        out.push(`<p><strong>${esc(this.text("noteAnswer", r.model ? this.answeredBy(r.model) : ""))}</strong></p>`);
        for (const e of r.answer) {
          let nodes;
          try { nodes = this.renderMarkdown(doc, e.text); } catch (err) { nodes = null; }
          out.push(nodes ? nodes.map(n => this.noteMarkup(n)).join("") : `<p>${esc(e.text)}</p>`);
        }
      }
    } finally { this.noteTex = was; }
    return out.join("\n");
  },

  // an element of the transcript's Markdown as a note's HTML: the plain tags with their own attributes, a formula as
  // Zotero's note editor keeps it ($…$ in span.math, $$…$$ in pre.math), a link as a link, a cited sentence as [p.N];
  // anything else as its content
  noteMarkup(n) {
    if (!n) return "";
    if (!n.localName) return this.escapeHtml(n.textContent || "");   // text
    const list = [...(n.childNodes || n.children || [])];
    const inner = () => (list.length ? list.map(c => this.noteMarkup(c)).join("") : this.escapeHtml(n.textContent || ""));
    const cls = String(n.className || ""), tag = n.localName;
    const tex = node => [node, ...[...(node.childNodes || node.children || [])]].map(c => c && c.getAttribute && c.getAttribute("data-tex")).find(t => t != null);
    if (cls === "scholium-tex") return `<span class="math">$${this.escapeHtml(n.getAttribute("data-tex"))}$</span>`;
    if (cls === "scholium-math") {
      const t = tex(n);
      if (t == null) return inner();
      return tag === "div" ? `<pre class="math">$$${this.escapeHtml(t)}$$</pre>` : `<span class="math">$\\displaystyle ${this.escapeHtml(t)}$</span>`;
    }
    if (cls === "scholium-swatch") return "";
    if (cls === "scholium-cite") return this.escapeHtml(`[${n.textContent}]`);
    if (cls === "scholium-link") {
      const href = n.getAttribute("data-href");
      return href ? `<a href="${this.escapeHtml(href)}">${inner()}</a>` : inner();
    }
    if (!this.NOTE_TAGS.has(tag)) return inner();
    if (tag === "hr" || tag === "br") return `<${tag}>`;
    let attrs = "";
    if (tag === "ol" && n.getAttribute("start")) attrs = ` start="${this.escapeHtml(n.getAttribute("start"))}"`;
    const style = (tag === "th" || tag === "td") && /^text-align: (left|right|center)$/.exec(n.getAttribute("style") || "");
    if (style) attrs = ` style="${style[0]}"`;
    return `<${tag}${attrs}>${inner()}</${tag}>`;
  },

  // system notification, for while Zotero is in the background (the corner notice is for when it is in front)
  notify(title, body) {
    try {
      const svc = Components.classes["@mozilla.org/alerts-service;1"].getService(Components.interfaces.nsIAlertsService);
      try { svc.showAlertNotification(null, title, body, false, "", null, "scholium"); return; }
      catch (e) {
        const alert = Components.classes["@mozilla.org/alert-notification;1"].createInstance(Components.interfaces.nsIAlertNotification);
        alert.init("scholium", null, title, body);
        svc.showAlert(alert);
      }
    } catch (e) { this.log("notification failed: " + e); }
  },

  // queue the selected papers, each for a new annotation session of the chosen agent, behind a chat of the paper that
  // runs or waits; returns how many were queued. confirmed: asked already, no dialog; replace: the user agreed to replace
  // the paper's Scholium annotations (also by the dialog), which are deleted before the run
  // the skill reads the paper through Zotero's local API; turned on with the user's consent, it answers the next request
  localApiReady() {
    if (Zotero.Prefs.get("httpServer.localAPI.enabled")) return true;
    if (!Services.prompt.confirm(Zotero.getMainWindow(), this.text("headline"), this.text("localApiOff"))) return false;
    Zotero.Prefs.set("httpServer.localAPI.enabled", true);
    return true;
  },
});
