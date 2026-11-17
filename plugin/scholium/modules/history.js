// ScholiumRunner, continued: the history list

Object.assign(ScholiumRunner, {
  async toggleHistory(pane, focus = false) {
    if (this.closePopover(pane, "history")) return;
    // ↓ and ↑ go from row to row: to its title, or to Undo of one deleted a moment ago
    const node = this.openPopover(pane, "history", pane.historyButton, n => {
      this.arrowKeys(pane, n, () => [...(n.children || [])].filter(r => r && /^scholium-history-row/.test(r.className))
        .map(r => [[...(r.children || [])].find(c => c && c.localName === "button"), r]));
    });
    await this.renderHistory(pane);
    // opened from the keyboard, the focus goes to the first row once the rows are there, unless it went elsewhere meanwhile
    const doc = pane.doc, a = doc.activeElement;
    const first = focus && pane.popover && pane.popover.node === node ? this.firstControl(node) : null;
    if (first && (!a || a === pane.historyButton || a === doc.documentElement || a === doc.body)) this.focusLayer(pane, first);
  },

  // today, yesterday, the previous 7 or 30 days, or older
  dayGroup(ms) {
    const day = t => { const d = new Date(t); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); };
    const days = Math.round((day(Date.now()) - day(ms)) / 86400000);
    return days <= 0 ? "groupToday" : days === 1 ? "groupYesterday" : days < 7 ? "groupWeek" : days < 30 ? "groupMonth" : "groupOlder";
  },

  // the conversations of the paper shown, newest first, by day: each opens, is renamed or deleted; one deleted a moment
  // ago can be brought back
  async renderHistory(pane) {
    const all = [];
    for (const key of pane.keys) all.push(...await this.conversations(key));
    for (const [path, d] of this.deleting) {
      if (pane.keys.includes(d.key)) all.push({ key: d.key, id: d.id, path, at: d.at, title: d.title, deleted: true });
    }
    all.sort((a, b) => b.at - a.at);
    for (const c of all) if (!c.deleted) c.title = await this.convTitle(c.key, c.id);
    const p = pane.popover;
    if (this.panes.get(pane.body) !== pane || !p || p.name !== "history") return;
    const doc = pane.doc;
    const rows = [], rowOf = new Map();
    let group = null;
    for (const c of all) {
      const g = this.dayGroup(c.at);
      if (g !== group) {
        group = g;
        const head = doc.createElement("div");
        head.className = "scholium-history-group";
        head.textContent = this.text(g);
        rows.push(head);
      }
      rowOf.set(c, this.historyRow(pane, c));
      rows.push(rowOf.get(c));
    }
    if (!rows.length) {
      const empty = doc.createElement("div");
      empty.className = "scholium-history-empty";
      empty.textContent = this.text("historyEmpty");
      rows.push(empty);
    }
    // a title being typed stays in its box
    const renaming = pane.renaming;
    if (renaming) renaming.moved = true;
    p.node.replaceChildren(...rows);
    const again = renaming && all.find(c => !c.deleted && c.key === renaming.c.key && c.id === renaming.c.id);
    if (again) this.renameRow(pane, rowOf.get(again), again, renaming.input.value);
    else if (renaming) pane.renaming = null;
    this.placePopover(pane);   // placed again for the size the rows gave it
  },

  historyRow(pane, c) {
    const doc = pane.doc;
    const row = doc.createElement("div");
    const span = (cls, text) => {
      const s = doc.createElement("span");
      s.className = cls;
      s.textContent = text;
      return s;
    };
    if (c.deleted) {
      row.className = "scholium-history-row deleted";
      const undo = this.paneButton(doc, this.text("undo"), () => { this.undoDelete(c.path).catch(e => this.log("undo failed: " + e)); }, "quiet");
      row.append(span("scholium-history-title", this.text("convDeleted", this.cut(c.title, 42))), undo);
      return row;
    }
    const current = c.key === pane.shownKey && c.id === pane.shownConv;
    row.className = "scholium-history-row" + (current ? " current" : "");
    const open = doc.createElement("button");
    open.className = "scholium-history-open";
    open.title = c.title;
    open.append(span("scholium-history-title", this.cut(c.title, 42)), span("scholium-history-time", this.clock(c.at)));
    open.addEventListener("click", () => { this.openConv(pane, c).catch(e => this.log("open failed: " + e)); });
    const rename = this.iconButton(doc, "edit", this.text("renameConv"), () => { this.renameRow(pane, row, c); });
    const remove = this.iconButton(doc, "trash", this.text("deleteConv"), () => { this.deleteConv(pane, c).catch(e => this.log("delete failed: " + e)); });
    row.append(open, rename, remove);
    return row;
  },

  // the row becomes a box with its title (or with what was typed there before the list was drawn again): Enter or
  // leaving it keeps the new one, Esc the old one; an empty box gives the conversation its first message again
  renameRow(pane, row, c, typed = null) {
    const input = pane.doc.createElement("input");
    input.className = "scholium-history-rename";
    input.value = typed === null ? c.title : typed;
    const renaming = pane.renaming = { c, input, moved: false };
    let done = false;
    const finish = renaming.finish = async (keep, redraw = true) => {
      if (done || renaming.moved) return;
      done = true;
      if (pane.renaming === renaming) pane.renaming = null;
      if (keep) {
        const index = await this.index(c.key);
        const title = this.cut(String(input.value || "").trim().split("\n")[0], 64);
        if (title) index.titles[c.id] = title;
        else delete index.titles[c.id];
        await this.saveIndex(c.key);
      }
      if (redraw) await this.renderHistory(pane);
    };
    input.addEventListener("keydown", e => {
      if (e.isComposing) return;   // the keys of an input method's word are its own
      if (e.key === "Enter") { e.preventDefault(); finish(true).catch(() => {}); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false).catch(() => {}); }
    });
    input.addEventListener("blur", () => { finish(true).catch(() => {}); });
    row.replaceChildren(input);
    try { input.focus(); if (input.select) input.select(); } catch (e) {}
  },

  // an earlier conversation, which the paper's messages go to from now on
  async openConv(pane, c) {
    if (this.busy(c.key, "chat")) return;
    await this.chooseConv(c.key, c.id);
    pane.preferKey = c.key;
    for (const p of [...this.panes.values()]) if (p.keys.includes(c.key)) await this.showConversation(p);
    this.closePopover(pane, "history");
  },

  // a conversation goes after UNDO_MS, until then it can be brought back; the one the paper's messages went to is
  // followed by a new one
  async deleteConv(pane, c) {
    if (this.busy(c.key, "chat") || this.deleting.has(c.path)) return;
    const index = await this.index(c.key);
    const wasCurrent = (await this.currentConv(c.key)) === c.id;
    const entry = { key: c.key, id: c.id, title: c.title, at: c.at, wasCurrent, timer: null };
    this.deleting.set(c.path, entry);
    if (wasCurrent) index.chat = null;
    await this.saveIndex(c.key);
    entry.timer = setTimeout(() => { this.finishDelete(c.path).catch(e => this.log("delete failed: " + e)); }, this.UNDO_MS);
    for (const p of [...this.panes.values()]) if (p.keys.includes(c.key)) await this.showConversation(p);
  },

  async undoDelete(path) {
    const entry = this.deleting.get(path);
    if (!entry || entry.finishing) return;   // too late: its log is going
    clearTimeout(entry.timer);
    this.deleting.delete(path);
    const index = await this.index(entry.key);
    if (entry.wasCurrent && index.chat === null) {
      index.chat = entry.id;
      await this.saveIndex(entry.key);
    }
    for (const p of [...this.panes.values()]) if (p.keys.includes(entry.key)) await this.showConversation(p);
  },

  // the log goes, and with it its title
  async finishDelete(path) {
    const entry = this.deleting.get(path);
    if (!entry || entry.finishing) return;
    entry.finishing = true;
    clearTimeout(entry.timer);
    const pending = this.pendingLogs.get(path);
    const wasHeld = pending && pending.held;
    if (pending) {
      pending.held = true;
      if (pending.flushing) await pending.flushing;
    }
    // its queued messages go with it
    const rows = this.queue.filter(j => j.qid && this.keyOf(j.att) === entry.key && j.conv === entry.id);
    if (rows.length) this.dropQueued(rows);
    // the Codex threads of the conversation are archived at the next Codex run, once its log is gone
    let threads = new Set();
    try { threads = this.codexThreads((await IOUtils.readUTF8(path)) + (pending ? pending.unlogged.join("\n") : "")
      + (pending && pending.restore ? pending.restore.text : "")); } catch (e) {}
    try {
      await IOUtils.remove(path);
      this.pendingLogs.delete(path);
      if (pending && pending.restore) this.replaced.delete(`${pending.restore.key}/${pending.restore.conv}`);
      for (const thread of threads) this.queueArchive(thread);
    } catch (e) {
      this.log("conversation not deleted: " + e);
      if (pending) { pending.held = wasHeld; if (!wasHeld) this.scheduleLogRetry(); }
      this.deleting.delete(path);
      const index = await this.index(entry.key);
      if (entry.wasCurrent && index.chat === null) { index.chat = entry.id; await this.saveIndex(entry.key); }
      this.notes.set(`${entry.key}/chat`, { text: this.text("conversationNotDeleted"), error: true, at: Date.now(), conv: entry.id });
      this.refresh();
      for (const pane of this.panes.values()) if (pane.keys.includes(entry.key)) await this.showConversation(pane);
      return;
    }
    this.parsedLogs.delete(path);
    // the folder the conversation's agent ran in goes with it
    const work = this.workDir(entry.key, entry.id);
    if (await this.isFolder(work)) {
      try { await IOUtils.remove(work, { recursive: true, ignoreAbsent: true }); }
      catch (e) { this.log("conversation folder not deleted: " + e); }
    }
    const index = await this.index(entry.key);
    delete index.titles[entry.id];
    if (index.chat === entry.id) index.chat = null;
    await this.saveIndex(entry.key);
    this.deleting.delete(path);
    for (const p of [...this.panes.values()]) if (p.popover && p.popover.name === "history" && p.keys.includes(entry.key)) await this.renderHistory(p);
  },
});
