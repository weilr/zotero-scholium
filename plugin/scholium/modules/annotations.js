// ScholiumRunner, continued: a paper's PDF attachments, the tool's annotations and notes and deleting them, the
// core colour, and the warnings a run's closing words name

Object.assign(ScholiumRunner, {
  // every PDF attachment of a selected regular item, and selected PDF attachments themselves
  pdfAttachments(items) {
    const found = new Map();
    for (const item of items || []) {
      try {
        let atts = [];
        if (item.isRegularItem && item.isRegularItem()) atts = Zotero.Items.get(item.getAttachments());
        else if (item.isAttachment && item.isAttachment()) atts = [item];
        for (const a of atts) if (a && a.attachmentContentType === "application/pdf" && !found.has(a.id)) found.set(a.id, a);
      } catch (e) { this.log("attachments failed: " + e); }
    }
    return [...found.values()];
  },

  // the tool's reading notes under a paper: its child notes tagged zotero-scholium
  ownNotes(parent) {
    try { return Zotero.Items.get(parent.getNotes()).filter(n => n.isNote() && n.getTags().some(t => t.tag === ScholiumToggle.tag)); }
    catch (e) { return []; }
  },

  // the reading notes an annotation that replaces these PDFs' annotations moves to the trash: not those of a paper whose
  // other PDF is being annotated or waits, as a deletion leaves them
  clearedNotes(atts) {
    const keys = new Set(atts.map(a => this.keyOf(a)));
    const busy = new Set(this.queue.filter(j => !this.isHeld(j)).map(j => j.att).concat([...this.runs.values()].map(r => this.attOf(r.libraryID, r.key)))
      .filter(a => a && !keys.has(this.keyOf(a)) && a.parentID).map(a => a.parentID));
    return this.ownNotesOf(atts.filter(a => !busy.has(a.parentID)));
  },

  // the tool's reading notes of the papers of these PDFs, each paper once
  ownNotesOf(atts) {
    const parents = [...new Set(atts.map(a => a.parentID).filter(Boolean))];
    return parents.flatMap(id => { const p = Zotero.Items.get(id); return p ? this.ownNotes(p) : []; });
  },

  // an annotation that replaces the tool's annotations: those of these PDFs deleted, the reading notes of their papers
  // moved to the trash; the user's stay
  async clearOwn(atts) {
    const own = atts.flatMap(att => att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)));
    const notes = this.clearedNotes(atts);
    if (own.length) await Zotero.Items.erase(own.map(a => a.id));
    if (notes.length) await Zotero.Items.trashTx(notes.map(n => n.id));
  },

  // the paper's Scholium annotations and reading notes as the annotation card counts them
  async countOwn(att) {
    const own = att.getAnnotations().filter(a => ScholiumToggle.isOwn(a));
    const core = await this.coreColor(this.keyOf(att));
    const marks = own.filter(a => ["highlight", "underline"].includes(a.annotationType));
    let readingNotes = 0;
    try { if (att.parentID) readingNotes = this.ownNotes(Zotero.Items.get(att.parentID)).length; } catch (e) {}
    return { highlights: marks.length, core: marks.filter(a => String(a.annotationColor || "").toLowerCase() === core).length,
             margin: own.filter(a => a.annotationType === "text").length, notes: own.filter(a => a.annotationType === "note").length, readingNotes,
             areas: own.filter(a => a.annotationType === "image").length };
  },

  // the core colour of the configuration the paper was written with last; Zotero's red without one
  async coreColor(key) {
    const applied = await this.readApplied(key);
    try {
      let c = applied && JSON.parse(await IOUtils.readUTF8(applied.config)).core_color;
      if (typeof c === "string") c = this.ZOTERO_COLORS[c.trim().toLowerCase()] || c.trim();
      if (typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c)) return c.toLowerCase();
    } catch (e) {}
    return "#ff6666";
  },

  // what the agent's closing words say of the warnings left: "" for none, the warnings, or null when they do not say. The
  // skill's summary is the reply's last line, and the warnings are its remainder after the label (a period inside them, as
  // in "Fig. 3", does not end them). Its English and Chinese forms, then the language's label and its word for none
  // (warningsPart)
  warningsOf(text) {
    const s = String(text || "").trim().split("\n").pop();
    const end = x => x.trim().replace(/[\s.。．!！]+$/, "");   // without the sentence's closing mark
    const label = String(this.text("warningsLabel") || ""), none = String(this.text("warningsNone") || "").toLowerCase();
    // none: a word for none on its own (无法定位 2 句 and "keine Übersetzung für S. 3" are warnings), with an aside in
    // brackets or after a comma (无（全部修正）, "none, all fixed"), or followed by the label's own word ("aucun
    // avertissement"); a count of 0
    const stems = label.toLowerCase().split(/\s+/).filter(w => w.length >= 4).map(w => w.slice(0, 4));
    const nothing = rest => {
      const core = end(String(rest).toLowerCase().replace(/\s*[(（][^)）]*[)）]\s*[.。]?$/, ""));
      if (/^0(?:\s*[条條件个個개])?$/.test(core)) return true;
      return ["无", "無", "没有", "沒有", "none", none].filter(Boolean).some(w => {
        if (!core.startsWith(w)) return false;
        const after = core.slice(w.length);
        if (!after || /^\s*[，,；;]/.test(after)) return true;
        const word = /^\s+(\p{L}+)$/u.exec(after);
        return !!word && stems.includes(word[1].slice(0, 4));
      });
    };
    // a count, as agents have written it: 剩余警告 1 条（…）, 剩余警告2条：…, 1 remaining warning (…), remaining warnings: 2 (…)
    // give the words in the brackets or after the colon; words right after the count (剩余警告：2 条译文提示（…）,
    // remaining warnings: 2 translation notes (…)) give the whole remainder; else the count. A count of 0 is none
    let m = /剩[余餘]警告\s*[:：]?\s*(\d+)\s*([条條])\s*(?:[（(](.*)[）)]|[:：]\s*([^\n]+)|([^\s。．.!！，,；;][^\n]*))?/.exec(s);
    if (m) return !Number(m[1]) ? "" : m[5] ? end(`${m[1]} ${m[2]}${m[5]}`) : end(m[3] || m[4] || "") || `${m[1]} ${m[2]}`;
    m = /(\d+)\s+remaining warnings?\b\s*(?:\((.*)\)|[:：]\s*([^\n]+))?/i.exec(s);
    if (m) return !Number(m[1]) ? "" : end(m[2] || m[3] || "") || m[1];
    m = /remaining warnings?\s*[:：]\s*(\d+)(?:\s*\((.*)\)|\s+([A-Za-z][^\n]*))?\s*[.。]?\s*$/i.exec(s);
    if (m) return !Number(m[1]) ? "" : m[3] ? end(`${m[1]} ${m[3]}`) : end(m[2] || "") || m[1];
    m = /剩[余餘]警告\s*[:：]\s*([^\n]+)|remaining warnings\s*[:：]\s*([^\n]+)/i.exec(s);
    if (m) return nothing(m[1] || m[2]) ? "" : end(m[1] || m[2]);
    if (/[无無]剩[余餘]警告|[没沒]有剩[余餘]警告|no (?:remaining )?warnings/i.test(s)) return "";
    const escape = x => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const own = label && new RegExp(escape(label) + "\\s*[:：]\\s*(.+)$", "i").exec(s);
    if (!own) return null;
    return nothing(own[1]) ? "" : end(own[1]) || null;
  },

  // delete the annotations tagged zotero-scholium, and move the reading notes tagged the same to the
  // trash; the user's annotations and notes stay. A paper with an attachment being annotated or
  // queued is left alone, notes included; messages held after a stop do not count. The outcome is the annotation tab's.
  async removeAnnotations(items) {
    const win = Zotero.getMainWindow();
    const busy = new Set(this.queue.filter(j => !this.isHeld(j)).map(j => this.keyOf(j.att)).concat([...this.runs.values()].map(r => r.key)));
    // a group's library the user cannot edit keeps its annotations
    const all = this.pdfAttachments(items), atts = all.filter(a => this.writable(a));
    if (all.length && !atts.length) { Services.prompt.alert(win, this.text("deleteTitle"), this.text("groupReadOnly")); return 0; }
    const skipped = atts.filter(a => busy.has(this.keyOf(a))).length;
    const busyParents = new Set(atts.filter(a => busy.has(this.keyOf(a)) && a.parentID).map(a => a.parentID));
    const parents = new Set();
    const targets = atts.filter(a => !busy.has(this.keyOf(a))).map(att => {
      const own = att.getAnnotations().filter(a => ScholiumToggle.isOwn(a));
      let notes = [];
      if (att.parentID && !parents.has(att.parentID) && !busyParents.has(att.parentID)) {
        parents.add(att.parentID);
        const parent = Zotero.Items.get(att.parentID);
        if (parent) notes = this.ownNotes(parent);
      }
      return { att, own, notes };
    }).filter(t => t.own.length || t.notes.length);
    const total = targets.reduce((n, t) => n + t.own.length, 0);
    const notes = targets.reduce((n, t) => n + t.notes.length, 0);
    const skippedText = skipped ? "\n\n" + this.text("deleteSkipped") : "";
    if (!total && !notes) {
      // the paper's other PDFs, which their own sections delete
      const shown = new Set(atts.map(a => this.keyOf(a)));
      const parents = atts.map(a => a.parentID && Zotero.Items.get(a.parentID)).filter(Boolean);
      const elsewhere = this.pdfAttachments(parents).filter(a => !shown.has(this.keyOf(a)))
        .reduce((n, a) => n + a.getAnnotations().filter(x => ScholiumToggle.isOwn(x)).length, 0);
      Services.prompt.alert(win, this.text("deleteTitle"), this.text("deleteNone")
        + (elsewhere ? "\n\n" + this.text("deleteElsewhere", elsewhere) : "") + skippedText);
      return 0;
    }
    const shared = targets.some(t => this.groupOf(t.att.libraryID));
    if (!Services.prompt.confirm(win, this.text("deleteTitle"), this.text("deleteConfirm", total, notes, shared) + skippedText)) return 0;
    let removed = 0, trashed = 0, current = null;
    try {
      for (const t of targets) {
        current = t;
        if (t.own.length) await Zotero.Items.erase(t.own.map(a => a.id));
        removed += t.own.length;
        if (t.notes.length) await Zotero.Items.trashTx(t.notes.map(n => n.id));
        trashed += t.notes.length;
        this.notes.set(`${this.keyOf(t.att)}/annotate`, { text: this.text("deleteDone", t.own.length, t.notes.length), error: false, at: Date.now() });
      }
      this.notice({ att: targets[0].att, title: this.text("deleteTitle"), kind: "annotate" }, this.text("deleteDone", removed, trashed));
    } catch (e) {
      const message = this.text("deleteFailed", String(e && e.message || e))
        + (removed || trashed ? " " + this.text("deleteDone", removed, trashed) : "");
      this.log("delete failed: " + e);
      const att = (current || targets[0]).att;
      this.notes.set(`${this.keyOf(att)}/annotate`, { text: message, error: true, at: Date.now() });
      this.notice({ att, title: this.text("deleteTitle"), kind: "annotate" }, message, true);
    }
    this.refresh();
    // the annotation tabs of these PDFs count their Scholium annotations again
    const keys = targets.map(t => this.keyOf(t.att));
    for (const pane of [...this.panes.values()]) {
      if (pane.keys.some(k => keys.includes(k))) this.showAnnotation(pane).catch(e => this.log("section not shown: " + e));
    }
    return removed + trashed;
  },
});
