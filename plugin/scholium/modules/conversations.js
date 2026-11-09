// ScholiumRunner, continued: the message box and the queued messages, conversations and their logs, the history,
// saved prompts, the transcript and the state line

Object.assign(ScholiumRunner, {
  // the words in a pane's box, or a saved prompt's (text), go to the paper it shows, in the conversation the chosen
  // agent's messages about it go to; a saved prompt leaves the box as it is
  sendFromPane(pane, invert = false, text = null) {
    const typed = text === null, tab = pane.tab;
    // /compact compacts the conversation shown, on whichever tab; it is no wish for an annotation
    const compact = typed ? /^\/compact(?:\s+([\s\S]*))?$/.exec(String(pane.input.value || "").trim()) : null;
    if (compact && pane.item) {
      const view = this.viewOf(pane, pane.tab);
      this.compactFromPane(pane, (compact[1] || "").trim()).then(ok => {
        if (ok) this.clearInput(pane);
        // nothing the agent could compact yet (no session of it there), while the paper is free: a word under the box says
        // so, the words stay
        else if (!(view.shownKey && this.busy(view.shownKey))) this.sayUnderBox(pane, this.text("nothingToCompact"));
      }).catch(e => this.log("compact failed: " + e));
      return;
    }
    // the annotation tab without a session: the words go with a new annotation
    if (typed && pane.tab === "annotate" && !pane.annot.shownConv && !pane.busy) { this.annotateFromPane(pane); return; }
    const say = String(typed ? pane.input.value || "" : text).trim();
    if (!say || !pane.item || pane.sending === say) return;
    if (pane.busy && this.followUpFor(pane, invert) === "steer" && this.steerable(pane)) {
      const quote = pane.tab === "chat" ? pane.quote : null, key = this.unsentKey(pane);
      pane.sending = say;
      this.steerFromPane(pane, say, quote)
        .then(ok => {
          if (!ok) return this.queueFromPane(pane, say, { typed });
          if (typed) this.clearSent(pane, tab, say, key);
          if (quote && pane.quote === quote) { pane.quote = null; this.paintQuote(pane); }
        })
        .catch(e => this.log("steer failed: " + e))
        .finally(() => { if (pane.sending === say) pane.sending = null; });
      return;
    }
    // a new message while the queue of the conversation shown is held asks first whether that queue goes, as Codex asks:
    // Clear queue drops it; Send message sends the new message and resumes the queue after it
    const waiting = this.queue.filter(j => this.shownQueued(pane, j));
    if (waiting.length && this.heldQueues.has(this.queueKey(waiting[0])) && !pane.busy) {
      const words = () => (typed ? String(pane.input.value || "").trim() : say);
      this.askInPlace(pane, this.text("clearQueueAsk", waiting.length), [
        [this.text("clearQueue"), "quiet small", () => {
          this.dropQueued(waiting);
          if (words()) this.queueFromPane(pane, words(), { typed }).catch(e => this.log("message failed: " + e));
        }],
        [this.text("sendMessage"), "small", () => {
          if (!words()) return;
          this.queueFromPane(pane, words(), { before: waiting[0], typed }).then(() => this.releaseQueue(waiting[0])).catch(e => this.log("message failed: " + e));
        }]]);
      return;
    }
    this.queueFromPane(pane, say, { typed }).catch(e => this.log("message failed: " + e));
  },

  // the words to the paper's conversation of the tab: sent, or queued behind the run under way (send); typed words
  // leave the box once they went
  queueFromPane(pane, say, { before = null, typed = true } = {}) {
    const view = this.viewOf(pane, pane.tab);
    const att = view.shownKey && this.attOf(pane.item.libraryID, view.shownKey);   // the paper of the tab's conversation
    const quote = pane.tab === "chat" ? pane.quote : null, tab = pane.tab, key = this.unsentKey(pane);
    if (typed) pane.sending = say;
    // a chat's message goes with the other papers above the box
    const papers = pane.tab === "chat" ? (pane.others || []).slice() : undefined;
    return this.send(att || pane.item, say, { kind: pane.tab, conv: view.shownConv, before, quote, papers })
      .then(sent => {
        if (!sent) return;
        if (typed) this.clearSent(pane, tab, say, key);
        if (quote && pane.quote === quote) { pane.quote = null; this.paintQuote(pane); }
      })
      .finally(() => { if (pane.sending === say) pane.sending = null; });
  },

  // the box emptied of words that went, unless it holds others now (typed meanwhile, or another tab's); kept as the unsent
  // words of the tab they were sent from when another tab is shown now, they go there
  clearSent(pane, tab, say, key = "") {
    if (pane.tab === tab) { if (String(pane.input.value || "").trim() === say) this.clearInput(pane); }
    else if (key && String(this.unsent.get(key) || "").trim() === say) this.unsent.delete(key);
  },

  // the conversation a tab shows, compacted by the agent chosen (an annotation session by its own agent): Claude Code's
  // /compact in its session; false when it has no session yet or its paper is busy
  async compactFromPane(pane, focus = "") {
    if (!this.compactable(pane)) return false;
    const view = this.viewOf(pane, pane.tab);
    const att = this.attOf(pane.item.libraryID, view.shownKey);
    return !!att && this.send(att, focus, { compact: true, kind: pane.tab, conv: view.shownConv });
  },

  // whether the tab shows a conversation its paper is free to compact (its session is looked up when it is sent)
  compactable(pane) {
    const view = this.viewOf(pane, pane.tab);
    return !!pane.item && !!view.shownKey && !!view.shownConv && !this.busy(view.shownKey);
  },

  // the annotation tab's button: the tab's paper annotated anew, with the words in the box as extra wishes; over its
  // Scholium annotations it first asks in place, and Replace deletes them at once
  annotateFromPane(pane, { extra = String(pane.input.value || "").trim() } = {}) {
    const key = pane.annot.shownKey || pane.keys[0];
    const att = key && pane.item && this.attOf(pane.item.libraryID, key);
    if (!att) return;
    const go = (replace = false) => this.annotate([att], { extra, confirmed: true, replace })
      .then(n => { if (n && String(pane.input.value || "").trim() === extra) this.clearInput(pane); })
      .catch(e => this.log("annotate failed: " + e));
    const own = att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
    if (!own) { go(); return; }
    this.askInPlace(pane, this.text("redoInline", own, this.clearedNotes([att]).length, !!this.groupOf(att.libraryID)),
                    [[this.text("cancelButton"), "quiet small", () => {}], [this.text("replace"), "small danger", () => go(true)]]);
  },

  // a question above the box in place of a dialog: its line and its buttons, each of which closes it first
  askInPlace(pane, line, choices) {
    const doc = pane.doc, row = pane.confirmRow;
    const text = doc.createElement("span");
    text.className = "scholium-confirm-text";
    text.textContent = line;
    row.replaceChildren(text, ...choices.map(([label, cls, fn]) => this.paneButton(doc, label, () => { this.show(row, false); fn(); }, cls)));
    this.show(row, true);
  },

  // the words in a message box are kept for the tab and the conversation they are typed to until they are sent, across
  // the section's renders and the agent chosen; an annotation session's for its agent. Of the tab shown unless another view
  // is named
  unsentKey(pane, view = this.viewOf(pane, pane.tab)) {
    if (!pane.item) return "";
    const agent = view.kind === "annotate" ? view.shownAgent || this.agent() : "";
    return `${pane.item.libraryID}/${pane.item.key}/${view.kind}/${agent}/${view.shownConv || ""}`;
  },

  keepUnsent(pane) {
    const key = this.unsentKey(pane);
    if (!key) return;
    if (String(pane.input.value || "").trim()) this.unsent.set(key, pane.input.value);
    else this.unsent.delete(key);
  },

  clearInput(pane) {
    pane.input.value = "";
    this.keepUnsent(pane);
    this.fitInput(pane);
  },

  // the box shows what was typed to the conversation now shown, when that is another one than before
  swapUnsent(pane, before) {
    const after = this.unsentKey(pane);
    if (after === before) return;
    pane.input.value = this.unsent.get(after) || "";
    this.fitInput(pane);
  },

  // the message box grows with its text, up to its maximum height; an empty box is as tall as its placeholder
  fitInput(pane) {
    try {
      const input = pane.input;
      input.style.height = "auto";
      let height = input.scrollHeight;
      if (!input.value && input.placeholder) {
        input.value = input.placeholder;
        height = input.scrollHeight;
        input.value = "";
      }
      input.style.height = height + "px";
    } catch (e) {}
    this.paintSend(pane);
  },

  // the round button: ↑ sends (while the paper runs it queues or steers, as its tooltip says; a /compact the paper cannot
  // take now stays in the box); ■ stops
  paintSend(pane) {
    const text = String(pane.input.value || "").trim();
    const stop = pane.busy && !text;
    const compactNot = /^\/compact(?:\s|$)/.test(text) && !this.compactable(pane);
    pane.send.className = "scholium-round " + (stop ? "stop" : "send");
    pane.send.textContent = stop ? "■" : "↑";
    pane.send.disabled = !stop && !text;
    // its name is what it does; its tooltip says so too, or why /compact cannot go now
    const does = stop ? "stopTip" : !pane.busy ? "sendTip" : this.followUpFor(pane) === "steer" ? "steerTip" : "queueTip";
    pane.send.title = this.text(compactNot ? "compactNotNow" : does);
    pane.send.setAttribute("aria-label", this.text(does));
  },

  // the messages waiting in the conversation the tab shows, in the box above its text, as Codex shows them: a line while
  // the queue is held, the message being sent, each queued one, and one deleted a moment ago with Undo. Another
  // conversation's are not shown; they wait in their own
  paintQueue(pane) {
    const doc = pane.doc;
    const mine = j => this.shownQueued(pane, j);
    const jobs = this.queue.filter(mine);
    const held = jobs.length > 0 && this.heldQueues.has(this.queueKey(jobs[0]));
    const nodes = [], qids = [];
    if (held) {
      const line = doc.createElement("div");
      line.className = "scholium-queue-held";
      const t = doc.createElement("span");
      t.textContent = this.text("queueHeld");
      line.append(t, this.iconButton(doc, "play", this.text("queueGoOn"), () => this.releaseQueue(jobs[0])));
      nodes.push(line);
    }
    const sending = this.job && mine(this.job.source) && !this.job.delivered ? this.job.source : null;
    if (sending) { nodes.push(this.queuedRow(pane, sending, { sending: true })); qids.push("sending " + sending.qid); }
    for (const j of jobs) { nodes.push(this.queuedRow(pane, j, { held })); qids.push(j.qid); }
    for (const [qid, r] of this.removedQueued) {
      if (mine(r.job)) { nodes.push(this.undoStrip(doc, this.text("queuedRemoved"), () => this.undoRemoveQueued(qid))); qids.push("removed " + qid); }
    }
    // drawn again only when what it shows changes (a redraw at each event of the run would take the focus from its buttons)
    const sig = JSON.stringify([qids, nodes.map(n => this.nodeSig(n))]);
    if (pane.queueSig !== sig) {
      pane.queueSig = sig;
      pane.queueBox.replaceChildren(...nodes);
    }
    this.show(pane.queueBox, nodes.length > 0);
  },

  // what a node drawn shows: its tags, classes, words, tooltips and states
  nodeSig(n) {
    if (!n || !n.localName) return n ? String(n.textContent || "") : "";
    return [n.localName, n.className, n.title || "", !!n.disabled, n.getAttribute("aria-label") || "", n.textContent,
            [...(n.children || [])].map(c => this.nodeSig(c))];
  },

  // a queued message: ⠿ to drag it, its words on one line (all of them once clicked), and Steer, ✕ and ⋯; Send instead of
  // Steer while its queue is held, Retry once it could not be sent
  queuedRow(pane, job, { held = false, sending = false } = {}) {
    const doc = pane.doc, row = doc.createElement("div");
    row.className = "scholium-queued" + (job.failed ? " failed" : "") + (sending ? " sending" : "") + (pane.openQid === job.qid ? " full" : "");
    const handle = doc.createElement("span");
    handle.className = "scholium-queued-handle";
    handle.textContent = "⠿";
    // the message being sent is out of the queue: neither dragged nor a place to drop
    if (!sending) {
      handle.setAttribute("draggable", "true");
      handle.addEventListener("dragstart", e => { pane.dragQid = job.qid; try { e.dataTransfer.setData("text/plain", job.qid); } catch (err) {} });
      handle.addEventListener("dragend", () => { pane.dragQid = null; });
      row.addEventListener("dragover", e => { if (pane.dragQid) e.preventDefault(); });
      row.addEventListener("drop", e => { e.preventDefault(); if (pane.dragQid) this.moveQueued(pane.dragQid, job.qid); pane.dragQid = null; });
    }
    const text = doc.createElement("span");
    text.className = "scholium-queued-text";
    if (job.failed) {
      const warn = doc.createElement("span");
      warn.className = "scholium-glyph warn";
      warn.setAttribute("role", "img");
      warn.setAttribute("aria-label", this.text("queuedFailedTip"));
      text.append(warn, doc.createTextNode(job.say));
      text.title = this.text("queuedFailedTip");
    } else text.textContent = job.say;
    text.addEventListener("click", () => { pane.openQid = pane.openQid === job.qid ? null : job.qid; this.paintQueue(pane); });
    row.append(handle, text);
    if (sending) {
      const s = doc.createElement("span");
      s.className = "scholium-queued-state";
      s.textContent = this.text("queuedSending");
      row.append(s);
      return row;
    }
    let first;
    if (job.failed) first = this.iconButton(doc, "retry", this.text("retry"), () => this.retryQueued(job.qid));
    else if (held) first = this.iconButton(doc, "play", this.text("queuedSend"), () => this.sendQueuedNow(job.qid));
    else {
      first = this.iconButton(doc, "steer", this.text("steerButton"), () => { this.steerQueued(pane, job.qid).catch(e => this.log("steer failed: " + e)); });
      const can = this.steerable(pane, job);
      first.disabled = !can;
      first.title = can ? this.text("steerRowTip") : !this.canSteer(job.agent) ? this.text("noSteer", this.agentName(job.agent)) : this.text("steerNotNow");
    }
    const remove = this.iconButton(doc, "trash", this.text("queuedRemove"), () => this.removeQueued(pane, job.qid));
    const more = this.paneButton(doc, "⋯", e => this.queuedMenu(pane, job, more, this.byKeyboard(e)), "quiet");
    more.title = this.text("moreTitle");
    more.setAttribute("aria-label", this.text("moreTitle"));
    more.setAttribute("aria-haspopup", "menu");
    row.append(first, remove, more);
    return row;
  },

  // a queued message's ⋯: back to the box to edit, or no queueing from now on (Steer instead, where the agent takes it)
  queuedMenu(pane, job, anchor, focus = false) {
    this.openPopover(pane, "queued", anchor, node => {
      node.setAttribute("role", "menu");
      this.arrowKeys(pane, node, this.menuItems(node));
      const item = (label, run, disabled = false) => {
        const b = pane.doc.createElement("button");
        b.className = "scholium-menu-item";
        b.setAttribute("role", "menuitem");
        b.textContent = label;
        b.disabled = disabled;
        b.addEventListener("click", () => { this.closePopover(pane); run(); });
        node.append(b);
      };
      item(this.text("queuedEdit"), () => this.editQueued(pane, job.qid));
      item(this.text("queueOff"), () => { Zotero.Prefs.set(this.pref + "followUpMode", "steer", true); this.refresh(); },
           !this.canSteer(job.agent) || this.followUpMode() === "steer");
    }, { focus });
  },

  // a paper's chat conversations: a log each, shared by the agents, <out dir>/conversations/chat-<time>.jsonl, with an
  // index of the one its messages go to and their titles; the logs of earlier versions (<agent>-<time>.jsonl there,
  // claude-run.jsonl and codex-run.jsonl in the out dir) are conversations of the list too. An annotation session is an
  // agent's own: annotate-<agent>-<time>.jsonl
  LEGACY: { claude: "claude-run", codex: "codex-run" },

  convDir(key) { return PathUtils.join(this.outDir(key), "conversations"); },

  convPath(key, id) {
    return Object.values(this.LEGACY).includes(id) ? PathUtils.join(this.outDir(key), id + ".jsonl") : PathUtils.join(this.convDir(key), id + ".jsonl");
  },

  convAgent(id) { return /^(?:annotate-)?codex-/.test(String(id)) ? "codex" : "claude"; },

  // { chat: the conversation the paper's messages go to, or null for a new one; current: each agent's of an earlier
  // version; titles: { id: title }; annotation: { agent: its latest annotation session } }. An index that is there but
  // cannot be read is not written over: this session's choices stay in memory.
  async index(key) {
    if (this.indexes.has(key)) return this.indexes.get(key);
    const index = { current: {}, titles: {}, annotation: {} };
    try {
      const saved = JSON.parse(await IOUtils.readUTF8(PathUtils.join(this.convDir(key), "index.json")));
      if (saved && Object.prototype.hasOwnProperty.call(saved, "chat") && (saved.chat === null || typeof saved.chat === "string")) index.chat = saved.chat;
      if (saved && saved.current && typeof saved.current === "object") index.current = saved.current;
      if (saved && saved.titles && typeof saved.titles === "object") index.titles = saved.titles;
      if (saved && saved.annotation && typeof saved.annotation === "object") index.annotation = saved.annotation;
    } catch (e) {
      if (!["NotFoundError", "SyntaxError"].includes(e && e.name)) {
        this.log("conversation index not read: " + e);
        Object.defineProperty(index, "unread", { value: true });
      }
    }
    if (!this.indexes.has(key)) this.indexes.set(key, index);   // unless another call read it meanwhile
    return this.indexes.get(key);
  },

  async saveIndex(key) {
    const index = this.indexes.get(key);
    if (!index || index.unread) return;
    try {
      await IOUtils.makeDirectory(this.convDir(key), { createAncestors: true, ignoreExisting: true });
      const path = PathUtils.join(this.convDir(key), "index.json");
      const saved = Object.assign({}, index);
      if (!Object.keys(saved.current || {}).length) delete saved.current;   // an empty one is not written
      await IOUtils.writeUTF8(path, JSON.stringify(saved), { tmpPath: path + ".tmp" });
    } catch (e) { this.log("conversation index not saved: " + e); }
  },

  // the paper's conversations that hold something, newest first: [{ key, id, path, at }]; one deleted a moment ago is
  // left out
  async conversations(key) {
    const conv = async (id, path) => {
      if (this.deleting.has(path)) return null;
      try {
        const stat = await IOUtils.stat(path);
        return stat.size > 0 ? { key, id, path, at: stat.lastModified || 0 } : null;
      } catch (e) { return null; }
    };
    const logs = Object.values(this.LEGACY).map(id => [id, this.convPath(key, id)]);
    let children = [];
    try { children = await IOUtils.getChildren(this.convDir(key)); } catch (e) {}
    for (const path of children) {
      const m = /[\\/]((?:chat|claude|codex)-[\w-]+)\.jsonl$/.exec(path);
      if (m && !Object.values(this.LEGACY).includes(m[1])) logs.push([m[1], path]);
    }
    const found = await Promise.all(logs.map(([id, path]) => conv(id, path)));
    return found.filter(Boolean).sort((a, b) => b.at - a.at);
  },

  // the conversation the paper's messages go to: the one chosen last, none after New chat, else the newest. An index of an
  // earlier version names one per agent: the chosen agent's, kept as the paper's at once; a paper without any keeps none.
  // Without an index (v0.1.9), the chosen agent's log of that version, while it holds something
  async currentConv(key) {
    const index = await this.index(key);
    const chosen = () => Object.prototype.hasOwnProperty.call(index, "chat");
    if (!chosen()) {
      const was = index.current[this.agent()];
      const all = was && (await this.exists(this.convPath(key, was))) ? null : await this.conversations(key);
      const id = !all ? was : ((all.find(c => c.id === this.LEGACY[this.agent()]) || all[0]) || {}).id || null;
      if (id && !chosen()) { index.chat = id; await this.saveIndex(key); }   // unless chosen meanwhile
      return chosen() ? index.chat : null;
    }
    if (index.chat === null) return null;
    if (index.chat && (await this.exists(this.convPath(key, index.chat)))) return index.chat;
    const all = await this.conversations(key);
    return all.length ? all[0].id : null;
  },

  async chooseConv(key, id) {
    const index = await this.index(key);
    index.chat = id;
    await this.saveIndex(key);
  },

  // a new conversation of the paper, titled by its first message, which its messages go to from now on; an annotation
  // session, the agent's own, is the one the annotation tab shows from now on
  async newConv(key, agent, title, kind = "chat") {
    const d = new Date();
    const two = n => String(n).padStart(2, "0");
    const stamp = `${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}${two(d.getSeconds())}`;
    const base = kind === "annotate" ? `annotate-${agent}-${stamp}` : `chat-${stamp}`;
    let id = base;
    for (let n = 2; await this.exists(this.convPath(key, id)); n++) id = `${base}-${n}`;
    await IOUtils.makeDirectory(this.convDir(key), { createAncestors: true, ignoreExisting: true });
    await IOUtils.writeUTF8(this.convPath(key, id), "");
    const index = await this.index(key);
    if (kind === "annotate") index.annotation[agent] = id;
    else index.chat = id;
    index.titles[id] = this.cut(String(title || "").split("\n")[0], 64);
    await this.saveIndex(key);
    return id;
  },

  // the agent's latest annotation session of the paper, while its log is there
  async annotationConv(key, agent) {
    const id = (await this.index(key)).annotation[agent];
    return id && (await this.exists(this.convPath(key, id))) ? id : null;
  },

  // its title: the user's own, or its first message
  async convTitle(key, id) {
    const title = (await this.index(key)).titles[id];
    if (title) return title;
    const log = await this.readLog(key, id);
    const first = log && log.turns.length ? String(log.turns[0].user || "").split("\n")[0] : "";
    return this.cut(first || this.text("annotateThis"), 64);
  },

  // a conversation as its log has it: the entries, the turns (the user's words and the answer), the result of its latest
  // run, whether a question started it and no annotation followed, and each agent's own session of it (agents); null
  // without a log
  async readLog(key, id) {
    if (!id) return null;
    const path = this.convPath(key, id);
    let stat = null;
    try { stat = await IOUtils.stat(path); } catch (e) { return null; }
    // a conversation that goes on appends to its log, so an unchanged one (same time and size) is not parsed again; the
    // sections that ask for it at once share one reading
    let cached = this.parsedLogs.get(path);
    if (!cached || cached.at !== stat.lastModified || cached.size !== stat.size) {
      cached = { at: stat.lastModified, size: stat.size, log: this.parseLog(path, this.convAgent(id)) };
      this.parsedLogs.delete(path);
      this.parsedLogs.set(path, cached);
      if (this.parsedLogs.size > 20) this.parsedLogs.delete(this.parsedLogs.keys().next().value);   // the oldest
    }
    const log = await cached.log;
    if (!log) {
      if (this.parsedLogs.get(path) === cached) this.parsedLogs.delete(path);
      return null;
    }
    const copy = a => Object.assign({}, a, { context: a.context && Object.assign({}, a.context) });
    const turns = log.turns.map(t => Object.assign({}, t, { points: Object.assign({}, t.points), sessions: Object.assign({}, t.sessions) }));
    return { entries: log.entries.slice(), turns,
             result: log.result, question: log.question, agents: { claude: copy(log.agents.claude), codex: copy(log.agents.codex) },
             papers: (log.papers || []).map(r => Object.assign({}, r)), path, id };
  },

  // what readLog gives of a log, read once; null when it cannot be read. agent: whose the runs of a log without run
  // lines are (a log of an earlier version)
  async parseLog(path, agent = "claude") {
    let text;
    try { text = await IOUtils.readUTF8(path); } catch (e) { return null; }
    const entries = [], turns = [];
    const own = a => (a === "claude" || a === "codex" ? a : null);
    // each agent's own session of the conversation: the session, the last turn it saw (-1: none), the point an edited
    // question takes it back to (Claude Code's last message, Codex's last turn), the point its next run goes back to until
    // the session moves on, the context the session took up, when its latest run that did its work started and ended
    // (lastEnd Infinity: the log ends with that run, cut short without its end), and the first turn it saw that another
    // agent answered again since (Infinity: none)
    const blank = () => ({ session: null, through: -1, point: null, rewind: null, context: null, lastAt: 0, lastEnd: 0, stale: Infinity });
    const agents = { claude: blank(), codex: blank() };
    let by = own(agent) || "claude";   // the agent of the run read
    // a log of an earlier version starts with an annotation unless the user's words come first; a run's session, and its
    // turn, count once the message reached the agent
    let pending = null, result = null, question = false, opened = false, reached = false, runAt = 0, runMine = false, timed = false;
    let compacting = false;   // the run is a compaction: its result is no turn's
    let papers = null;        // the other papers of a question about several, as its latest message named them
    // where each turn starts in the text; bare: where a run line without the user's words starts
    let at = 0, bare = null;
    // a turn knows each agent's point and session at its start, which a cut before it goes back to
    const turn = (user, start) => ({ user, reply: "", ended: "", reached: false, start, agent: by,
                                     points: { claude: agents.claude.point, codex: agents.codex.point },
                                     sessions: { claude: agents.claude.session, codex: agents.codex.session } });
    // an agent without its session, or without a point to go back to: a new session of it goes on with the conversation,
    // and the point of the old one names a message or turn the new one does not have
    const anew = a => {
      Object.assign(agents[a], { session: null, through: -1, point: null, rewind: null, stale: Infinity });
      if (agents[a].context) agents[a].context = Object.assign({}, agents[a].context, { used: 0, parts: null });
    };
    for (const line of text.split("\n")) {
      const start = at;
      at += line.length + 1;
      if (!line.trim()) continue;
      let event;
      try { event = JSON.parse(line); } catch (e) { continue; }
      // the start of a run, its agent, and the user's words when it starts a turn; a run without them answers the turn
      // before (a second try, a retry, a continuation)
      if (event.type === "scholium" && event.subtype === "run") {
        // a run that did its work and was cut short without its end (Zotero closed during it) ended before this one
        if (runMine && !timed && event.at > 0) agents[by].lastEnd = event.at;
        by = own(event.agent) || own(agent) || "claude";
        opened = typeof event.user === "string";
        compacting = !!event.compact;
        bare = !opened && !event.compact ? start : null;
        if (opened) turns.push(turn(event.user, start));
        if (event.rewind) agents[by].rewind = { point: event.rewind, from: agents[by].session };
        reached = false;
        pending = null;
        runAt = event.at > 0 && !event.compact ? event.at : 0;   // counts once the run reached the agent
        runMine = timed = false;
        this.addEntries(entries, this.entries(event));
        continue;
      }
      // words steered into the turn are the user's, and part of the turn's words
      if (event.type === "scholium" && event.subtype === "steer") {
        const q = event.quote && event.quote.text ? event.quote : null;
        if (turns.length) turns[turns.length - 1].user += "\n\n" + (q ? this.quoteTag(q) : "") + String(event.text || "");
        this.addEntries(entries, this.entries(event));
        continue;
      }
      // the cut of an edited question: each agent it names goes back to its point before the question, or, without one,
      // to a new session given the conversation; an earlier version's marker names the point of the log's own agent
      if (event.type === "scholium" && event.subtype === "rewind") {
        const marked = event.points && typeof event.points === "object" ? event.points : { [own(agent) || "claude"]: event.point };
        for (const a of this.AGENTS) {
          if (!Object.prototype.hasOwnProperty.call(marked, a)) continue;
          const back = this.pointOf(marked[a]);
          if (back) agents[a].rewind = { point: back, from: agents[a].session };
          else anew(a);
        }
        this.addEntries(entries, this.entries(event));
        continue;
      }
      if (event.type === "scholium" && event.subtype === "prompt") {
        question = event.question ? true : event.annotate ? false : question;
        if (!opened) {
          turns.push(turn(String(event.text || ""), bare === null ? start : bare));
          reached = false;
        }
        bare = null;
        if (turns.length) Object.assign(turns[turns.length - 1], { prompted: true, annotate: !!event.annotate });
        if (event.quote && event.quote.text && turns.length) turns[turns.length - 1].quote = this.quoteOf(event.quote);
        if (Array.isArray(event.papers)) papers = event.papers.filter(r => r && typeof r.key === "string" && r.key);
        opened = false;
      } else if (event.type !== "scholium") {
        opened = false;
        bare = null;
        if (!turns.length) turns.push(turn(this.text("annotateThis"), start));
      }
      const me = agents[by];
      // the run's end time counts for the agent once the run reached it and did its work; a run cut short has its length
      // on its end line
      if (event.type === "scholium" && event.subtype === "time") {
        timed = true;
        if (runMine && event.at > 0) me.lastEnd = event.at;
      } else if (event.type === "scholium" && event.subtype === "end" && runMine && !timed && event.duration_ms >= 0) {
        timed = true;
        me.lastEnd = runAt + event.duration_ms;
      }
      if (typeof event.session_id === "string" && event.session_id) {
        pending = event.session_id;
        if (reached) me.session = pending;
      }
      if (!reached && this.reached(event)) {
        reached = true;
        if (pending) me.session = pending;
        if (runAt) { me.lastAt = runAt; runMine = true; }   // since the session's last run that did its work
        if (turns.length) {
          turns[turns.length - 1].reached = true;
          // the agent that took the turn's message answers it (a retry hands it over once it is delivered); another agent
          // whose session saw the turn has not seen this answer
          if (!compacting) {
            const k = turns.length - 1;
            Object.assign(me, { through: k, stale: Infinity });
            turns[k].agent = by;
            for (const a of this.AGENTS) if (a !== by && agents[a].through >= k) agents[a].stale = Math.min(agents[a].stale, k);
          }
        }
      }
      // the agent no longer has the session: a new one goes on with the conversation
      if (event.type === "scholium" && event.subtype === "gone") {
        anew(own(event.agent) || by);
        // a new session took over the run's words: the refused run's error is not drawn
        if (event.resent === true) {
          this.dropRefused(entries);
          if (turns.length) turns[turns.length - 1].ended = "";
          result = null;
        }
      }
      if (event.type === "assistant" && typeof event.uuid === "string" && !compacting) agents.claude.point = { uuid: event.uuid };
      if (event.type === "system" && event.subtype === "compact_boundary") agents.claude.point = null;   // Claude Code keeps no messages before it
      if (event.method === "turn/completed" && event.params && event.params.turn && event.params.turn.id && !compacting) {
        agents.codex.point = { turnId: String(event.params.turn.id) };
      }
      if (me.rewind && me.session && me.session !== me.rewind.from) me.rewind = null;   // the run reached the agent: a session of its own
      me.context = this.contextAfter(event, me.context);
      if (event.type === "system" && event.subtype === "init" && !compacting) result = null;
      if (event.type === "result" && !compacting) {
        result = event;
        const errors = Array.isArray(event.errors) ? event.errors.join("; ") : "";
        if (turns.length && event.is_error) turns[turns.length - 1].ended = String(event.result || errors || this.failureText(event.subtype)).trim();
        else if (turns.length) Object.assign(turns[turns.length - 1], { reply: String(event.result || "").trim(), done: true });
      }
      if (event.type === "scholium" && event.subtype === "end" && !compacting) {
        result = { type: "result", subtype: event.outcome, is_error: true, result: event.text, duration_ms: event.duration_ms };
        if (turns.length) turns[turns.length - 1].ended = String(event.text || event.outcome || "");
      }
      const made = this.entries(event);
      // a turn's own words know their turn
      if (event.type === "scholium" && event.subtype === "prompt") for (const e of made) if (e.kind === "prompt" && !e.steer) e.turn = turns.length - 1;
      this.addEntries(entries, made);
    }
    // the log ends with such a run: no rewrite of the agent's here came after it
    if (runMine && !timed) agents[by].lastEnd = Infinity;
    // stale: null when no turn it saw was answered again by another agent
    const out = a => ({ session: a.session, through: a.through, point: a.point, rewind: a.rewind ? a.rewind.point : null,
                        context: a.context, lastAt: a.lastAt, lastEnd: a.lastEnd, stale: a.stale === Infinity ? null : a.stale });
    return { entries: entries.slice(-this.MAX_ENTRIES), turns, result, question, agents: { claude: out(agents.claude), codex: out(agents.codex) },
             papers: papers || [] };
  },

  // the error lines of the latest run, which a new session took over: they leave the entries
  dropRefused(entries) {
    let from = entries.length;
    while (from > 0 && entries[from - 1].kind !== "run") from--;
    for (let i = entries.length - 1; i >= from; i--) if (entries[i].kind === "final" && entries[i].error && !entries[i].cancelled) entries.splice(i, 1);
  },

  // whether an event of a run shows that its message reached the agent: its answer or tools, a result, Codex's turn
  reached(event) {
    if (typeof event.method === "string") return /^(turn\/started|item\/)/.test(event.method);
    return event.type === "assistant" || event.type === "user" || (event.type === "result" && !event.is_error);
  },

  // the context the session holds after an event: what its latest request took in and wrote, and the model's window;
  // the same object when the event says nothing of it
  contextAfter(event, context) {
    const c = Object.assign({ used: 0, window: 0 }, context);
    if (event.type === "assistant" && !event.parent_tool_use_id && event.message && event.message.usage) {
      const u = event.message.usage;
      const n = k => Number(u[k]) || 0;
      c.used = n("input_tokens") + n("cache_creation_input_tokens") + n("cache_read_input_tokens") + n("output_tokens");
      c.parts = { input: n("input_tokens"), cache: n("cache_creation_input_tokens") + n("cache_read_input_tokens"), output: n("output_tokens") };
    } else if (event.type === "system" && event.subtype === "compact_boundary" && event.compact_metadata) {
      // the size the compaction left
      const post = Number(event.compact_metadata.post_tokens) || 0;
      if (!post) return context;
      c.used = post;
      c.parts = null;
    } else if (event.type === "scholium" && event.subtype === "compacted" && Number(event.post) > 0) {
      c.used = Number(event.post);
      c.parts = null;
    } else if (event.type === "result" && event.modelUsage && typeof event.modelUsage === "object") {
      // the run's model's window, the largest of those it used
      const windows = Object.values(event.modelUsage).map(m => Number(m && m.contextWindow) || 0).filter(n => n > 0);
      if (windows.length) c.window = Math.max(...windows);
    } else if (event.method === "thread/tokenUsage/updated" && event.params && event.params.tokenUsage) {
      const t = event.params.tokenUsage;
      if (t.last) {
        c.used = Number(t.last.totalTokens) || c.used;
        const n = k => Number(t.last[k]) || 0;
        c.parts = { input: n("inputTokens") - n("cachedInputTokens"), cache: n("cachedInputTokens"), output: n("outputTokens") };
      }
      if (Number(t.modelContextWindow) > 0) c.window = Number(t.modelContextWindow);
    } else return context;
    return c;
  },

  // text cut to n characters with an ellipsis, never inside a character that takes two
  cut(text, n) {
    const s = String(text || "");
    if (s.length <= n) return s;
    let end = n - 1;
    const c = s.charCodeAt(end - 1);
    if (c >= 0xd800 && c <= 0xdbff) end -= 1;
    return s.slice(0, end) + "…";
  },

  // a conversation for a new session of it, as llm-for-zotero gives one: beyond HISTORY_FROM exchanges the latest
  // HISTORY_WHOLE whole and the earlier ones as excerpts; each answer is the run's last message, with the agent that gave
  // it. from: the number of turns before the first given
  historyParts(turns, from = 0) {
    const zh = this.zh();
    const answer = t => t.reply || (t.done ? (zh ? "（没有文字回答）" : "(no text)")
      : zh ? `（没有完成${t.ended ? "：" + this.cut(t.ended, 300) : ""}）` : `(not finished${t.ended ? ": " + this.cut(t.ended, 300) : ""})`);
    let whole = turns.map((t, i) => ({ n: t.n || from + i + 1, user: (t.quote ? this.quoteTag(t.quote) : "") + String(t.user || ""), answer: answer(t),
                                       agent: t.agent }));
    let summary = "";
    if (whole.length > this.HISTORY_FROM) {
      const early = whole.slice(0, -this.HISTORY_WHOLE);
      whole = whole.slice(-this.HISTORY_WHOLE);
      const name = t => this.agentName(t.agent);
      summary = [zh ? `之前的 ${early.length} 轮对话（摘录）：` : `Earlier conversation (${early.length} exchanges):`,
                 ...early.map(t => (zh ? `用户：${this.cut(t.user, this.EXCERPT_USER)}\n回答（${name(t)}）：${this.cut(t.answer, this.EXCERPT_ANSWER)}`
                                       : `User: ${this.cut(t.user, this.EXCERPT_USER)}\nAnswer (${name(t)}): ${this.cut(t.answer, this.EXCERPT_ANSWER)}`))].join("\n\n");
    }
    return { summary, whole };
  },

  // Codex: the conversation as items of the new thread
  historyItems(turns) {
    if (!turns.length) return [];
    const zh = this.zh();
    const { summary, whole } = this.historyParts(turns);
    const message = (role, text) => ({ type: "message", role, content: [{ type: role === "user" ? "input_text" : "output_text", text: text || "[Empty message]" }] });
    const items = [];
    if (summary) items.push(message("user", summary), message("assistant", zh ? "明白，我已了解之前的对话。" : "Understood. I have the earlier conversation context."));
    for (const t of whole) items.push(message("user", t.user), message("assistant", t.answer));
    return items;
  },

  // Claude Code, and Codex when it does not take items: the conversation as text before the message
  historyText(turns) {
    if (!turns.length) return "";
    const zh = this.zh();
    return [
      zh ? "下面是这段对话之前的内容（Zotero 里保存的记录），每轮注明是谁回答的："
         : "Below is this conversation so far (the record kept in Zotero), each answer with the agent that gave it:",
      ...this.turnLines(this.historyParts(turns)),
      zh ? "——以上是之前的对话，新消息如下——" : "--- the earlier conversation ends; the new message follows ---",
    ].join("\n\n");
  },

  // the turns as text, each answer with the agent that gave it
  turnLines({ summary, whole }) {
    const zh = this.zh();
    return [...(summary ? [summary] : []),
            ...whole.map(t => (zh ? `[第 ${t.n} 轮]\n用户：${t.user}\n回答（${this.agentName(t.agent)}）：${t.answer}`
                                  : `[Turn ${t.n}]\nUser: ${t.user}\nAnswer (${this.agentName(t.agent)}): ${t.answer}`))];
  },

  // a session that goes on: the turns of the conversation after the last one it saw, before the message. from: the number
  // of turns before them
  missedText(turns, from) {
    if (!turns.length) return "";
    const zh = this.zh(), one = turns.length === 1;
    return [
      zh ? `下面是这段对话里，你上次回答之后的 ${turns.length} 轮。这期间用户在 Zotero 里接着问，有的由别的智能体回答，每轮注明了回答者。它们属于这段对话，请接着它们回答：`
         : (one ? "Below is the exchange of this conversation after your last answer."
                : `Below are the ${turns.length} exchanges of this conversation after your last answer.`)
           + " Meanwhile the user went on asking in Zotero, some answered by another agent; each answer names the agent that gave it. They are part of this conversation; answer as its continuation:",
      ...this.turnLines(this.historyParts(turns, from)),
      zh ? "——以上是这段对话最近的几轮，下面是用户的新消息——"
         : "--- the latest exchanges of this conversation end; the user's new message follows ---",
    ].join("\n\n");
  },

  // what a section shows once it is laid out
  async loadHistory(body) {
    const pane = this.panes.get(body);
    if (!pane) return;
    // one PDF: in a reader's side pane the reader's own, else the best of a regular item
    if (pane.keys.length > 1) {
      const own = this.readerKey(pane);
      if (own && pane.keys.includes(own)) pane.keys = [own];
      else {
        const job = await this.resolve(pane.item);
        if (job && this.panes.get(body) === pane) pane.keys = [this.keyOf(job.att)];
      }
    }
    await this.showConversation(pane);
  },

  // what a section shows: the running paper's chat transcript, else the conversation of the paper that its messages go
  // to (none after New chat); and on its annotation tab, the annotation session
  async showConversation(pane) {
    const seq = pane.showing = (pane.showing || 0) + 1;
    const liveHere = () => this.job && pane.keys.includes(this.job.key) && (this.job.source.kind || "chat") === "chat";
    if (liveHere()) { this.showLive(pane, this.job.key, "chat"); await this.showAnnotation(pane); return; }
    const agent = this.agent();
    const keys = pane.preferKey && pane.keys.includes(pane.preferKey) ? [pane.preferKey].concat(pane.keys.filter(k => k !== pane.preferKey)) : pane.keys;
    let shown = null;
    for (const key of keys) {
      const id = await this.currentConv(key);
      if (id) { shown = { key, id }; break; }
    }
    const log = shown ? await this.readLog(shown.key, shown.id) : null;
    if (shown) await this.loadCitations(shown.key);
    if (this.panes.get(pane.body) !== pane || pane.showing !== seq) return;   // rendered or shown anew meanwhile
    if (liveHere()) { this.showLive(pane, this.job.key, "chat"); await this.showAnnotation(pane); return; }   // a run started meanwhile
    const before = this.unsentKey(pane);
    const path = shown ? this.convPath(shown.key, shown.id) : null;
    // the latest run's own transcript, which has what its log may lack (a failure before the run had one); a section that
    // showed the run as it went has it already
    const memory = !!path && path === this.transcriptPath && this.transcriptKind === "chat";
    const kept = memory && pane.live && pane.shownPath === path && this.transcript.length > 0;
    if (pane.shownPath !== path) pane.foldOpen = new Map();   // the steps a reader opened are of the conversation shown
    // the other papers: those Ask Scholium (N papers) chose stay for the conversation shown first; another conversation
    // has those its log records, a new one none
    if (pane.othersFor === "pending") pane.othersFor = path;
    else if (pane.othersFor !== path) Object.assign(pane, { others: log && Array.isArray(log.papers) ? log.papers.slice() : [], othersFor: path });
    Object.assign(pane, { shownKey: shown ? shown.key : null, shownConv: shown ? shown.id : null, shownAgent: agent, shownPath: path, live: memory,
                          history: !!log && !memory, turns: log ? log.turns.length : 0, question: !!(log && log.question),
                          context: log ? log.agents[agent].context : null, draft: null });
    pane.past = log && log.result ? { text: this.text("lastRun") + this.outcome(log.result), error: !this.succeeded(log.result),
                                      title: this.tokenDetail(log.result) } : null;
    const entries = memory ? this.transcript : log ? log.entries : [];
    // the run shown as it went is drawn again as finished; anything else anew, at the latest, so that what follows is followed
    if (kept) this.refreshRun(pane, pane.runCount - 1);
    else if (entries.length) this.renderTranscript(pane, entries, false);
    else this.renderTranscript(pane, [], false);
    this.swapUnsent(pane, before);
    this.paintPane(pane);
    if (pane.popover && pane.popover.name === "history") await this.renderHistory(pane);
    await this.showAnnotation(pane);
  },

  // what the annotation tab shows: the paper's annotation session as it runs, else the session of an annotation waiting to
  // start (none yet: the words typed go to it), else the chosen agent's latest one, else an introduction
  async showAnnotation(pane) {
    const view = pane.annot, seq = view.showing = (view.showing || 0) + 1;
    const key = pane.keys[0] || null;
    const agent = this.agent();
    const coming = this.queue.some(j => this.keyOf(j.att) === key && j.annotate && !j.conv && !this.started(j));
    const id = key && !coming ? await this.annotationConv(key, agent) : null;
    const log = id ? await this.readLog(key, id) : null;
    const own = key && pane.item ? this.ownCount(pane.item.libraryID, key) : 0;
    const intro = log && log.entries.length ? null : await this.annotIntroNode(pane, key, own);
    if (id) await this.loadCitations(key);
    if (view.showing !== seq) return;   // shown anew meanwhile
    // the paper's annotation runs, or started meanwhile
    if (this.job && key === this.job.key && this.job.source.kind === "annotate") { this.showLive(pane, key, "annotate"); return; }
    const before = this.unsentKey(pane);
    const path = log ? log.path : null;
    if (view.shownPath !== path) view.foldOpen = new Map();   // the steps a reader opened are of the session shown
    Object.assign(view, { shownKey: key, shownConv: log ? id : null, shownAgent: agent, shownPath: path, live: false,
                          history: !!log, turns: log ? log.turns.length : 0, question: false, context: log ? log.agents[agent].context : null,
                          entries: log ? log.entries : [], draft: null, own });
    if (intro) { view.list.replaceChildren(pane.annotIntro = intro); view.runCount = 0; }
    else this.renderTranscript(view, log.entries, false);
    this.swapUnsent(pane, before);
    this.paintPane(pane);
  },

  // the annotation tab before its first session: what an annotation does; and, when an earlier version, the skill on its
  // own or the other agent wrote the paper's annotations, how many it carries, and by which agent and when where known
  async annotIntroNode(pane, key, own = 0) {
    return this.introNode(pane.doc, key ? await this.readApplied(key) : null, own);
  },

  // the Scholium annotations on the PDF with this key, whoever wrote them
  ownCount(libraryID, key) {
    try {
      const att = key ? this.attOf(libraryID, key) : null;
      return att ? att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length : 0;
    } catch (e) { return 0; }
  },

  introNode(doc, applied = null, own = 0) {
    const node = doc.createElement("div");
    node.className = "scholium-annot-intro";
    const title = doc.createElement("div");
    title.className = "scholium-annot-intro-title";
    title.textContent = own > 0 ? this.text("annotOwnTitle", own) : this.text("annotEmptyTitle");
    const body = doc.createElement("div");
    body.textContent = this.text("annotEmptyBody");
    node.append(title, body);
    if (applied && applied.at > 0) {
      const line = doc.createElement("div");
      line.className = "scholium-annot-applied";
      const d = new Date(applied.at);
      line.textContent = this.text("appliedBy", this.agentName(applied.agent === "codex" ? "codex" : "claude"),
                                   this.text("monthDay", d.getMonth() + 1, d.getDate()));
      node.append(line);
    }
    return node;
  },

  // the saved prompts of the row above the chat's box: [{ label, prompt }]; the four built-in ones until the list is
  // changed, then the list as it was saved
  savedPrompts() {
    try {
      const list = JSON.parse(this.getPref("savedPrompts") || "null");
      if (Array.isArray(list)) {
        return list.filter(p => p && typeof p.prompt === "string" && p.prompt.trim())
          .map(p => ({ label: String(p.label || "").trim() || this.promptLabel(p.prompt), prompt: p.prompt.trim() }));
      }
    } catch (e) { this.log("saved prompts not read: " + e); }
    return [1, 2, 3, 4].map(n => ({ label: this.text("starterLabel" + n), prompt: this.text("starter" + n) }));
  },

  saveSavedPrompts(list) {
    try { Zotero.Prefs.set(this.pref + "savedPrompts", JSON.stringify(list.map(p => ({ label: p.label, prompt: p.prompt }))), true); }
    catch (e) { this.log("saved prompts not saved: " + e); }
    this.refresh();
  },

  // a prompt's label when none was given: its first twelve characters
  promptLabel(prompt) { return Array.from(String(prompt).trim().split("\n")[0]).slice(0, 12).join(""); },

  // the row of saved prompts, on the chat tab while its box is there: one button each (✎ and 🗑 on hover), ＋ at the end,
  // and the one deleted a moment ago with Undo; drawn again only when that changes, and not while a prompt is edited there
  paintSaved(pane) {
    const shown = pane.tab === "chat" && !pane.composer.hidden;
    this.show(pane.saved, shown);
    if (!shown || pane.savedEdit) return;
    const list = this.savedPrompts();
    const sig = JSON.stringify([list, !!this.savedRemoved]);
    if (pane.savedSig === sig) return;
    pane.savedSig = sig;
    const doc = pane.doc;
    const nodes = list.map((p, at) => this.savedItem(pane, p, at));
    nodes.push(this.iconButton(doc, "add", this.text("savedAdd"), () => this.editSaved(pane, -1)));
    if (this.savedRemoved) nodes.push(this.undoStrip(doc, this.text("queuedRemoved"), () => this.undoRemoveSaved()));
    pane.saved.replaceChildren(...nodes);
  },

  // a saved prompt: its label sends its words; ✎ and 🗑 beside it; dragged onto another, it takes that one's place
  savedItem(pane, p, at) {
    const doc = pane.doc, node = doc.createElement("span");
    node.className = "scholium-saved-item";
    node.setAttribute("draggable", "true");
    const go = doc.createElement("button");
    go.className = "scholium-saved-go";
    go.textContent = p.label;
    go.title = p.prompt;
    go.addEventListener("click", () => this.sendFromPane(pane, false, p.prompt));
    node.append(go,
                this.iconButton(doc, "edit", this.text("savedEdit"), () => this.editSaved(pane, at)),
                this.iconButton(doc, "trash", this.text("savedDelete"), () => this.removeSaved(at)));
    node.addEventListener("dragstart", e => { pane.dragSaved = at; try { e.dataTransfer.setData("text/plain", String(at)); } catch (err) {} });
    node.addEventListener("dragend", () => { pane.dragSaved = null; });
    node.addEventListener("dragover", e => { if (typeof pane.dragSaved === "number") e.preventDefault(); });
    node.addEventListener("drop", e => {
      e.preventDefault();
      const from = pane.dragSaved;
      pane.dragSaved = null;
      if (typeof from === "number") this.moveSaved(from, at);
    });
    return node;
  },

  // a line that says what was just done, with Undo
  undoStrip(doc, text, onUndo) {
    const strip = doc.createElement("div");
    strip.className = "scholium-undo";
    const t = doc.createElement("span");
    t.textContent = text;
    strip.append(t, this.paneButton(doc, this.text("undo"), onUndo, "quiet small"));
    return strip;
  },

  // the row as a small editor of one saved prompt (at -1: a new one at the end): its label and its words; ✓ or
  // Ctrl/⌘+Enter keeps it, ✕ or Esc leaves the row as it was
  editSaved(pane, at) {
    const doc = pane.doc, was = at >= 0 ? this.savedPrompts()[at] || null : null;
    const editor = doc.createElement("div");
    editor.className = "scholium-saved-editor";
    const label = doc.createElement("input");
    label.className = "scholium-saved-label";
    label.setAttribute("no-native", "true");
    label.setAttribute("no-windows-native", "true");
    label.placeholder = this.text("savedLabel");
    label.value = was ? was.label : "";
    const words = doc.createElement("textarea");
    words.className = "scholium-saved-prompt";
    words.setAttribute("rows", "2");
    words.setAttribute("no-native", "true");
    words.setAttribute("no-windows-native", "true");
    words.placeholder = this.text("savedPrompt");
    words.value = was ? was.prompt : "";
    const close = () => { pane.savedEdit = null; pane.savedSig = null; this.paintSaved(pane); };
    const keep = () => {
      const prompt = String(words.value || "").trim();
      if (!prompt) return;
      const item = { label: String(label.value || "").trim() || this.promptLabel(prompt), prompt };
      const list = this.savedPrompts();
      if (at >= 0 && at < list.length) list[at] = item;
      else list.push(item);
      pane.savedEdit = null;
      pane.savedSig = null;
      this.saveSavedPrompts(list);
    };
    const no = this.iconButton(doc, "close", this.text("savedCancel"), close);
    const ok = this.iconButton(doc, "check", this.text("savedSave"), keep);
    const fit = () => { ok.disabled = !String(words.value || "").trim(); };
    words.addEventListener("input", fit);
    for (const field of [label, words]) {
      field.addEventListener("keydown", e => {
        if (e.isComposing) return;   // the ime's keys
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
        else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); keep(); }
      });
    }
    const tools = doc.createElement("div");
    tools.className = "scholium-saved-tools";
    tools.append(no, ok);
    editor.append(label, words, tools);
    fit();
    pane.savedEdit = { at, editor };
    pane.saved.replaceChildren(editor);
    try { (was ? words : label).focus(); } catch (e) {}
  },

  // a saved prompt goes at once; Undo brings it back to its place for a few seconds
  removeSaved(at) {
    const list = this.savedPrompts();
    if (!list[at]) return;
    const [item] = list.splice(at, 1);
    if (this.savedRemoved) clearTimeout(this.savedRemoved.timer);
    this.savedRemoved = { item, at, timer: setTimeout(() => { this.savedRemoved = null; this.refresh(); }, this.UNDO_MS) };
    this.saveSavedPrompts(list);
  },

  undoRemoveSaved() {
    const r = this.savedRemoved;
    if (!r) return;
    clearTimeout(r.timer);
    this.savedRemoved = null;
    const list = this.savedPrompts();
    list.splice(Math.min(r.at, list.length), 0, r.item);
    this.saveSavedPrompts(list);
  },

  // a saved prompt dragged onto another takes its place
  moveSaved(from, to) {
    const list = this.savedPrompts();
    if (from === to || !list[from] || !list[to]) return;
    const [item] = list.splice(from, 1);
    list.splice(to, 0, item);
    this.saveSavedPrompts(list);
  },

  // the running paper's transcript, as it goes on
  showLive(pane, key, kind = this.transcriptKind) {
    const view = this.viewOf(pane, kind);
    const before = this.unsentKey(pane);
    const job = this.job && this.job.key === key ? this.job.source : null;
    const ours = this.transcriptKey === key;   // a run that has only just started shows its transcript a moment later
    const conv = (job && job.conv) || null;
    if (view.shownKey !== key || view.shownConv !== conv) view.foldOpen = new Map();   // the steps opened are of the conversation shown
    Object.assign(view, { shownKey: key, shownConv: conv, shownAgent: (job && job.agent) || this.agent(),
                          shownPath: ours ? this.transcriptPath : null, live: true,
                          history: false, past: null, draft: null });
    try {
      this.renderTranscript(view, ours ? this.transcript : [], true);
      if (ours && this.draft) this.paintDraft();
    } catch (e) {}
    // the sentences the answers cite, read now: drawn again with their chips
    const had = this.citations.get(key);
    this.loadCitations(key).then(() => {
      if (this.citations.get(key) === had || !view.live || view.shownKey !== key) return;
      view.draft = null;   // the redraw detaches the draft's node
      this.renderTranscript(view, this.transcriptKey === key ? this.transcript : [], true);
      if (this.draft) this.paintDraft();
    }).catch(e => this.log("citations failed: " + e));
    this.swapUnsent(pane, before);
    if (view !== pane) this.paintPane(pane);
  },

  // the sections that show a run's transcript, once the new conversation it started has its log; the words typed
  // there meanwhile go on with it
  livePanes(key, id) {
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, this.transcriptKind);
      if (!view.live || view.shownKey !== key) continue;
      const before = this.unsentKey(pane, view);
      view.shownConv = id;
      view.shownPath = this.convPath(key, id);
      const text = this.unsent.get(before);
      if (text) { this.unsent.delete(before); this.unsent.set(this.unsentKey(pane, view), text); }
    }
  },

  // another agent: its models; every section keeps the conversation it shows, which the next message of the agent goes on
  // with
  async switchAgent(pane, agent) {
    this.choose("agent", agent);
    pane.preferKey = null;
    for (const p of [...this.panes.values()]) await this.showConversation(p);
  },

  // a new conversation of the paper shown: its first message starts it. The paper's chat must be idle; an annotation may
  // run
  async newChat(pane) {
    if (pane.keys.some(k => this.busy(k, "chat"))) return;
    for (const key of pane.keys) await this.chooseConv(key, null);
    pane.preferKey = null;
    for (const p of [...this.panes.values()]) if (p.keys.some(k => pane.keys.includes(k))) await this.showConversation(p);
  },

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
    // its queued messages go with it
    const rows = this.queue.filter(j => j.qid && this.keyOf(j.att) === entry.key && j.conv === entry.id);
    if (rows.length) this.dropQueued(rows);
    // the Codex threads of the conversation are archived at the next Codex run, once its log is gone
    let threads = new Set();
    try { threads = this.codexThreads(await IOUtils.readUTF8(path)); } catch (e) {}
    try {
      await IOUtils.remove(path);
      for (const thread of threads) this.queueArchive(thread);
    } catch (e) { this.log("conversation not deleted: " + e); }
    this.parsedLogs.delete(path);
    const index = await this.index(entry.key);
    delete index.titles[entry.id];
    if (index.chat === entry.id) index.chat = null;
    await this.saveIndex(entry.key);
    this.deleting.delete(path);
    for (const p of [...this.panes.values()]) if (p.popover && p.popover.name === "history" && p.keys.includes(entry.key)) await this.renderHistory(p);
  },

  // add entries to a transcript; a failed run's result that repeats Claude Code's last message is
  // shown once. Returns the entries added.
  addEntries(list, entries) {
    const added = [];
    for (const e of entries) {
      const prev = list[list.length - 1];
      if (e.kind === "final" && prev && prev.kind === "text" && prev.text === e.text) continue;
      list.push(e);
      added.push(e);
    }
    return added;
  },

  // one transcript entry: a step has a bullet column beside the content, so that wrapped lines keep their indent;
  // the stylesheet sets the agent's text in the pane's font, tool calls and results in monospace, and the
  // user's words in a bubble on the right
  entryNode(doc, entry) {
    const node = doc.createElement("div");
    node.className = `scholium-entry ${entry.kind}${entry.error ? " error" : ""}${entry.draft ? " draft" : ""}`;
    const bullet = { tool: "⏺ ", result: "⎿ " }[entry.kind];
    if (bullet) {
      const span = doc.createElement("span");
      span.className = "scholium-bullet";
      span.textContent = bullet;
      node.append(span);
    }
    // a stopped run: ⊘, its word on hover
    if (entry.kind === "final" && entry.cancelled) {
      node.className += " cancelled";
      node.title = entry.text;
      const icon = doc.createElement("span");
      icon.className = "scholium-glyph cancelled";
      icon.setAttribute("role", "img");
      icon.setAttribute("aria-label", entry.text);
      node.append(icon);
      return node;
    }
    if (entry.kind === "text") {
      // the agent writes Markdown: set as the profile's preview sets it
      const content = doc.createElement("div");
      content.className = "scholium-content scholium-markdown";
      try { content.append(...this.renderMarkdown(doc, entry.text)); }
      catch (e) {
        content.textContent = entry.text;   // the source rather than a section that does not render
        this.log("markdown failed: " + e);
      }
      if (entry.unfinished) {
        const note = doc.createElement("div");
        note.className = "scholium-unfinished";
        note.textContent = this.text("unfinished");
        content.append(note);
      }
      node.append(content);
      return node;
    }
    if (entry.kind === "prompt" && entry.quote) {
      const q = doc.createElement("div");
      q.className = "scholium-prompt-quote";
      q.textContent = this.quoteLabel(entry.quote);
      node.append(q);
    }
    const content = doc.createElement("span");
    content.className = "scholium-content";
    if (entry.kind === "tool" && entry.name && entry.text.startsWith(entry.name)) {
      const name = doc.createElement("b");
      name.textContent = entry.name;
      content.append(name, doc.createTextNode(entry.text.slice(entry.name.length)));
    } else {
      content.append(doc.createTextNode(entry.text));
    }
    node.append(content);
    return node;
  },

  // a button that copies the text, and shows for a moment that it did
  copyButton(doc, text) {
    const button = doc.createElement("button");
    button.className = "scholium-copy";
    button.title = this.text("copyMessage");
    button.addEventListener("click", () => {
      try {
        Zotero.Utilities.Internal.copyTextToClipboard(text);
      } catch (e) {
        this.log("copy failed: " + e);
        return;
      }
      button.className = "scholium-copy done";
      button.title = this.text("copiedMessage");
      clearTimeout(button.reset);
      button.reset = setTimeout(() => {
        button.className = "scholium-copy";
        button.title = this.text("copyMessage");
      }, 1500);
    });
    return button;
  },

  // a transcript as runs: what each run of the agent showed, from its start line (or, in an earlier version's log, from
  // the user's words) on. The steps are the tool calls, their results and the agent's words between them; the answer is
  // what it wrote after its last step; the rest are the run's other lines (a failure, a notice): its lead before its
  // first step or answer, the others after. turn: the words the run answers, its own or, for a run that goes on with the
  // turn before (a second try, a continuation), those of the run before, which is then continued
  runsOf(entries) {
    const runs = [];
    let run = null, bare = false;   // bare: the run has nothing yet but its start line
    const open = (at, continues = false) => {
      // a compaction is no turn: the run that goes on goes on with the last turn's run
      const before = continues ? runs.filter(r => !r.compact).pop() : null;
      if (before) before.continued = true;
      run = { start: at, end: 0, prompt: null, turn: before ? before.turn : null, lead: [], steps: [], answer: [], other: [], model: "" };
      runs.push(run);
    };
    for (const e of entries) {
      if (e.kind === "run") { open(e.at, !!e.continues); run.compact = !!e.compact; bare = true; continue; }
      // words steered into the turn under way start a segment that goes on with the turn
      if (e.kind === "prompt" && e.steer && run) { open(0, true); run.prompt = e; run.last = e; bare = false; continue; }
      if (!run || (e.kind === "prompt" && !bare)) open(0);
      bare = false;
      run.last = e;
      if (e.kind === "prompt") run.prompt = run.turn = e;
      else if (e.kind === "tool" || e.kind === "result") { run.steps.push(...run.answer, e); run.answer = []; }
      else if (e.kind === "text") run.answer.push(e);
      else if (e.kind === "info" && e.model) run.model = e.text;
      else if (e.kind === "time") { if (e.waited) run.stopped = e.at; else run.end = e.at; }   // a stopped wait is no work of the run
      else if (e.kind === "compacting" || e.kind === "compacted" || e.kind === "compactFailed") run.other.push(e);
      else (run.steps.length || run.answer.length ? run.other : run.lead).push(e);
    }
    return runs;
  },

  // one run: the user's words; the lines before its steps; a line for its steps (what it does now while it runs, else how
  // long it worked; a click opens the steps); the answer; its other lines; then the model and the time with a copy button
  renderRun(view, run, index, live) {
    return this.withCites(view.shownKey, () => this.drawRun(view, run, index, live));
  },

  drawRun(view, run, index, live) {
    if (run.compact) return this.compactNode(view, run, live);
    if (view.kind === "annotate" && run.turn && run.turn.annotate) return this.renderAnnotationRun(view, run, index, live);
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-run";
    if (run.prompt) {
      const said = this.entryNode(doc, run.prompt);
      // the user's own words can be edited and asked again
      const editable = this.promptEditable(view, run);
      if (editable) {
        said.className += " editable";
        said.append(this.iconButton(doc, "edit", this.text("editPrompt"), () => this.startEdit(view, run, said), "quiet edit-prompt"));
      }
      // the question being edited: its box stays, and stands for the words drawn now
      const e = view.editing;
      if (editable && e && this.isEditing(view, e, run.prompt)) { e.said = said; e.drawn = true; node.append(e.box); }
      else node.append(said);
    }
    // the question that replaced the ones after it a moment ago: Undo under it
    if (this.replaced.size && this.undoAt(view) === index) node.append(this.undoNode(view));
    // the last run of a view that failed without an answer carries a retry on its failure line; on the annotation tab, a
    // run of words to the session. A queued message that failed has its Retry on its row
    const failedLast = !live && index === (view.runCount || 0) - 1 && !run.answer.length && !!view.pane && (view.kind === "chat" || !!run.turn)
      && !this.busy(view.shownKey)
      && !this.queue.some(j => j.failed && this.keyOf(j.att) === view.shownKey && (j.kind || "chat") === view.kind && (j.conv || null) === (view.shownConv || null));
    let retryable = failedLast ? [...run.lead, ...run.other].filter(e => e.kind === "final" && e.error).pop() : null;
    const line = e => {
      const n = this.entryNode(doc, e);
      if (e === retryable) {
        const again = () => this.retryFromView(view).catch(err => this.log("retry failed: " + err));
        if (e.skill) n.append(this.paneButton(doc, this.text("installSkill"), () => { this.installAndRetry(view, e.skill, again).catch(err => this.log("install failed: " + err)); }, "small"));
        n.append(this.iconButton(doc, "retry", this.text("retry"), again));
      }
      return n;
    };
    for (const e of run.lead) node.append(line(e));
    if (run.steps.length || live) node.append(this.foldNode(view, run, index, live));
    else if (run.start > 0 && run.end >= run.start) node.append(this.workedNode(view, run));
    for (const e of run.answer) node.append(this.entryNode(doc, e));
    for (const e of run.other) {
      // the agent's own compaction in this run: a line with the sizes; its start has none
      if (e.kind === "compacted") {
        node.append(this.compactedLine(doc, e));
        continue;
      }
      if (e.kind === "compacting") continue;
      node.append(line(e));
    }
    if (!live && run.answer.length) node.append(this.metaNode(doc, run));
    return node;
  },

  // the agent's own compaction within a run: a line with the sizes
  compactedLine(doc, e) {
    const n = doc.createElement("div");
    n.className = "scholium-compact";
    n.textContent = this.text("compactedAuto") + this.compactSizes(e);
    return n;
  },

  // a compaction: one line, while it runs (its words swept, with the time) and then how it ended
  compactNode(view, run, live) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-compact" + (live ? " live" : "");
    if (live) {
      const now = doc.createElement("span");
      now.append(doc.createTextNode("◌ "), this.workingNode(view, "compactingFor"));
      node.append(now);
      return node;
    }
    const lines = run.lead.concat(run.other);
    const done = lines.filter(e => e.kind === "compacted").pop();
    node.textContent = done ? this.text("compactedLine") + this.compactSizes(done) : this.text("compactStopped");
    const failure = lines.find(e => (e.kind === "final" && e.error) || e.kind === "compactFailed");
    if (!live && !done && failure) node.title = failure.text || "";
    return node;
  },

  compactSizes(e) { return e.pre > 0 && e.post > 0 ? ` · ${this.kTokens(e.pre)} → ${this.kTokens(e.post)}` : ""; },

  // an annotation in the annotation tab: the wishes; while it runs what it does now (its raw steps on a click); then
  // its steps folded with the closing words among them, and a card of the numbers or of the failure. The
  // lines after the card's in the log follow the card. A try that the annotation went on from, or waits to go on from (a
  // second try, a continuation after a pause), shows its failure as a line: the card is the annotation's end
  renderAnnotationRun(view, run, index, live) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-run";
    if (run.prompt) node.append(this.entryNode(doc, run.prompt));
    const lines = run.lead.concat(run.other);
    const counts = lines.find(e => e.kind === "counts");
    const goesOn = run.continued || (index === (view.runCount || 0) - 1
      && this.queue.some(j => this.keyOf(j.att) === view.shownKey && j.conv === view.shownConv && this.started(j)));
    const failure = live || goesOn ? null : lines.filter(e => e.kind === "final" && e.error).pop();
    const card = counts || failure;
    const lead = card && run.lead.includes(card) ? run.lead.slice(0, run.lead.indexOf(card)) : run.lead;
    for (const e of lead) node.append(this.entryNode(doc, e));
    const steps = run.steps.concat(run.answer);
    if (steps.length || live) node.append(this.foldNode(view, Object.assign({}, run, { steps, answer: [] }), index, live));
    if (counts) node.append(this.countsNode(doc, counts));
    else if (failure) node.append(this.failedCard(view, run, failure, index));
    for (const e of lines.slice(lead.length)) {
      if (e === card || e.kind === "compacting") continue;
      node.append(e.kind === "compacted" ? this.compactedLine(doc, e) : this.entryNode(doc, e));
    }
    return node;
  },

  // the card of a finished annotation: its warnings left, the numbers counted in Zotero, and its turns, tokens and end
  countsNode(doc, e) {
    const node = doc.createElement("div");
    node.className = "scholium-card";
    const title = doc.createElement("div");
    title.className = "scholium-card-title";
    // a run that left the paper none of the tool's annotations and notes says so, with what it said was left
    const none = !(e.highlights || e.margin || e.notes || e.readingNotes);
    if (none) node.className += " none";
    title.textContent = none ? (e.warnings ? this.text("annotNoneWarn", e.warnings) : this.text("annotNone"))
      : e.warnings === "" ? this.text("annotDoneClean") : e.warnings ? this.text("annotDoneWarn", e.warnings) : this.text("annotDone");
    const nums = doc.createElement("div");
    nums.className = "scholium-card-nums";
    for (const [n, label] of [[e.highlights, "numHighlights"], [e.margin, "numMargin"], [e.notes, "numNotes"], [e.readingNotes, "numReading"]]) {
      const cell = doc.createElement("div");
      const b = doc.createElement("b");
      b.textContent = String(n || 0);
      const s = doc.createElement("span");
      s.textContent = this.text(label, n || 0, e.core);
      cell.append(b, s);
      nums.append(cell);
    }
    const usage = doc.createElement("div");
    usage.className = "scholium-card-usage";
    usage.textContent = [e.turns > 0 ? this.text("turns", e.turns) : "", e.tokens > 0 ? this.text("tokens", this.kTokens(e.tokens)) : "",
                         e.at ? this.clock(e.at) : ""].filter(Boolean).join(" · ");
    node.append(title, nums, usage);
    return node;
  },

  // the card of a failed annotation: the reason, and on the view's last run while the paper does not annotate, Retry,
  // which annotates again with the same wishes
  failedCard(view, run, failure, index) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-card failed";
    const text = doc.createElement("div");
    text.textContent = failure.text;
    node.append(text);
    const extra = (run.turn && run.turn.extra) || "";
    if (view.pane && index === (view.runCount || 0) - 1 && !this.busy(view.shownKey, "annotate")) {
      const again = () => { this.annotateFromPane(view.pane, { extra }); };
      if (failure.skill) node.append(this.paneButton(doc, this.text("installSkill"), () => { this.installAndRetry(view, failure.skill, again).catch(e => this.log("install failed: " + e)); }, "small"));
      node.append(this.iconButton(doc, "retry", this.text("retry"), again));
    }
    return node;
  },

  // the steps folded into one line, as in Codex; the reader's opening or closing wins. It is kept by the run's start,
  // which stays when the transcript's first lines go (an earlier version's run, without one, by its place). An
  // annotation going on offers its raw steps as details
  foldNode(view, run, index, live) {
    const doc = view.doc;
    const key = run.start || index;
    const open = view.foldOpen.get(key) === true;
    const node = doc.createElement("div");
    node.className = "scholium-fold";
    const head = doc.createElement("button");
    head.className = "scholium-fold-head" + (live ? " live" : "");
    if (live && view.kind === "annotate") {
      const more = doc.createElement("span");
      more.className = "scholium-fold-more";
      more.textContent = " " + this.text("details") + (open ? " ⌄" : " ›");
      head.append(this.workingNode(view, this.compactingNow(run) ? "compactingFor" : "workingFor"), more);
    } else if (live) {
      head.append(this.workingNode(view, this.compactingNow(run) ? "compactingFor" : "workingFor"));
      if (open) head.append(doc.createTextNode(" ⌄"));
    } else {
      head.textContent = this.workedText(run) + (open ? " ⌄" : " ›");
    }
    head.addEventListener("click", () => { view.foldOpen.set(key, !open); this.refreshRun(view, index); });
    node.append(head);
    if (open) {
      const body = doc.createElement("div");
      body.className = "scholium-fold-body";
      for (const e of run.steps) body.append(this.entryNode(doc, e));
      node.append(body);
    }
    return node;
  },

  // a finished run without steps: how long it worked, with nothing to open
  workedNode(view, run) {
    const node = view.doc.createElement("div");
    node.className = "scholium-fold";
    const head = view.doc.createElement("div");
    head.className = "scholium-fold-head plain";
    head.textContent = this.workedText(run);
    node.append(head);
    return node;
  },

  // the live line's words: Working for 12s (or Compacting context for 12s), swept by a light; tick writes the time again
  // without drawing the run
  workingNode(view, key = "workingFor") {
    const span = view.doc.createElement("span");
    span.className = "scholium-working";
    // every redraw of the line starts the sweep at the same phase
    span.style.animationDelay = -(Date.now() % 2000) + "ms";
    span.textContent = this.text(key, this.durationWords(this.elapsed()));
    view.liveTime = { node: span, key };
    return span;
  },

  // whether the agent compacts its context now, in a run under way: its last compaction line is the start of one
  compactingNow(run) {
    const last = (run.other || []).filter(e => e.kind === "compacting" || e.kind === "compacted" || e.kind === "compactFailed").pop();
    return !!last && last.kind === "compacting";
  },

  workedText(run) {
    return run.start > 0 && run.end >= run.start ? this.text("worked", this.durationWords(run.end - run.start)) : this.text("workedPlain");
  },

  // 6 分 17 秒 / 6m 17s
  durationWords(ms) {
    const all = Math.max(0, Math.round(ms / 1000));
    const h = Math.floor(all / 3600), m = Math.floor((all % 3600) / 60), s = all % 60;
    return this.text("durationWords", h, m, s);
  },

  // Opus 5.5 for claude-opus-5-5: the label the agent gave the model, else the name made readable
  modelLabel(id) {
    const name = String(id).replace(/^.* · /, "");
    for (const list of Object.values(this.models)) {
      const m = list.find(o => o.value === name);
      if (m) return m.label;
    }
    const c = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(name);
    return c ? `${c[1][0].toUpperCase()}${c[1].slice(1)} ${c[2]}.${c[3]}` : name;
  },

  // "Claude Code · Opus 5.5" for the start of a run "Claude Code · claude-opus-5-5": the agent and the model's label
  answeredBy(info) {
    const s = String(info), at = s.indexOf(" · ");
    return at > 0 ? `${s.slice(0, at)} · ${this.modelLabel(s)}` : this.modelLabel(s);
  },

  // under a finished run's answer: who gave it (the agent and the model) and when it ended, and a button that copies the
  // answer
  metaNode(doc, run) {
    const node = doc.createElement("div");
    node.className = "scholium-meta";
    const left = doc.createElement("span");
    const at = run.end || run.stopped;
    left.textContent = [run.model ? this.answeredBy(run.model) : "", at ? this.clock(at) : ""].filter(Boolean).join(" · ");
    node.append(left, this.copyButton(doc, run.answer.map(e => e.text).join("\n\n")));
    return node;
  },

  // a view's whole transcript; the last run is live while the paper's run goes on
  renderTranscript(view, entries, live) {
    const runs = this.runsOf(entries);
    view.entries = entries;
    view.runCount = runs.length;   // before the runs are drawn: the last one carries the retry
    this.redraw(view, null, () => view.list.replaceChildren(...runs.map((r, i) => this.renderRun(view, r, i, live && i === runs.length - 1))));
    // an edited question that waits for its run: Undo after the conversation
    if (this.replaced.size && this.undoAt(view) === runs.length) view.list.append(this.undoNode(view));
    view.runCount = runs.length;
    view.head = this.headOf(runs);
    // the list goes to its end, unless a box being edited kept its place in it
    if (!(view.editing && view.editing.drawn)) {
      view.list.scrollTop = view.list.scrollHeight;
      view.scrollPending = !view.list.clientHeight;   // hidden: no height to scroll in yet
    }
  },

  // what tells the first run drawn: the last line of the transcript's first run while another run follows it (until
  // then the first run is the one that grows); it changes when the transcript's first run goes
  headOf(runs) { return runs.length > 1 ? runs[0].last : null; },

  // whether a view shows the run going on: of the running paper, the view of the run's kind
  showsRun(view) {
    return !!this.job && this.job.key === view.shownKey && this.viewOf(view.pane, this.transcriptKind) === view;
  },

  // one run drawn again, when its steps are opened or closed or it ended; live while it is the view's running run
  refreshRun(view, index) {
    const runs = this.runsOf(view.entries);
    if (!runs[index]) return;
    const old = view.list.children[index];
    this.redraw(view, old, () => {
      const node = this.renderRun(view, runs[index], index, this.showsRun(view) && index === runs.length - 1);
      old.replaceWith(node);
      if (view.draft && index === runs.length - 1) node.append(view.draft.node);   // the message being written stays last
    });
  },

  // the views of the latest run draw its last run again once the agent no longer works on it (a pause, the wait for a
  // second try, an end before the run had its log), or when an annotation reaches a step
  settleRun() {
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, this.transcriptKind);
      if (view.shownKey === this.transcriptKey) this.refreshRun(view, view.runCount - 1);
    }
  },

  // entries of the running paper's transcript: the views that show it draw its last run again, or all of it once
  // another run begins
  appendEntries(entries) {
    const added = this.addEntries(this.transcript, entries);
    if (!added.length) return;
    if (this.transcript.length > this.MAX_ENTRIES) this.transcript.splice(0, this.transcript.length - this.MAX_ENTRIES);
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, this.transcriptKind);
      if (!view.live || view.shownKey !== this.transcriptKey) continue;
      try {
        const list = view.list;
        const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
        const runs = this.runsOf(this.transcript), live = this.showsRun(view);
        if (runs.length !== view.runCount || this.headOf(runs) !== view.head) this.renderTranscript(view, this.transcript, live);
        else {
          const old = list.children[runs.length - 1];
          this.redraw(view, old, () => old.replaceWith(this.renderRun(view, runs[runs.length - 1], runs.length - 1, live)));
        }
        if (view.draft) list.lastChild.append(view.draft.node);   // the draft stays last
        if (atBottom) list.scrollTop = list.scrollHeight;
      } catch (e) {}
    }
  },

  // a piece of the message the agent is writing: block names the message part it belongs to; the
  // panes show it a moment later, together with the pieces that follow
  growDraft(piece, block) {
    if (!piece) return;
    if (!this.draft) this.draft = { text: "", block };
    else if (this.draft.block !== block) this.draft.text += "\n\n";
    this.draft.text += piece;
    this.draft.block = block;
    if (!this.draftTimer) this.draftTimer = setTimeout(() => { this.draftTimer = null; this.paintDraft(); }, this.DRAFT_MS);
  },

  // what a run showed of a message it ended before finishing (cancelled, failed), as the plugin's line for
  // the log; null when no message was being written. The draft goes.
  unfinished() {
    const text = this.draft ? this.draft.text.trim() : "";
    this.dropDraft();
    return text ? { type: "scholium", subtype: "unfinished", text } : null;
  },

  dropDraft() {
    if (!this.draft) return;
    this.draft = null;
    clearTimeout(this.draftTimer);
    this.draftTimer = null;
    this.paintDraft();
  },

  // the draft at the end of each pane that shows the running paper's transcript, set as Markdown
  paintDraft() {
    for (const pane of this.panes.values()) {
      try {
        const view = this.viewOf(pane, this.transcriptKind);
        // the other view's draft goes with the run it belonged to
        for (const v of this.paneViews(pane)) {
          if (v !== view && v.draft) { v.draft.node.remove(); v.draft = null; }
        }
        if (!this.draft || !view.live || view.shownKey !== this.transcriptKey) {
          if (view.draft) view.draft.node.remove();
          view.draft = null;
          continue;
        }
        const list = view.list;
        const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
        if (!view.draft) {
          const node = this.entryNode(pane.doc, { kind: "text", text: "", draft: true });
          list.lastChild.append(node);   // in the last run
          view.draft = { node, content: node.children[0] };
        }
        // text selected in the draft stays selected: the draft is set again once the selection is gone
        const win = pane.doc.defaultView;
        const sel = win && typeof win.getSelection === "function" ? win.getSelection() : null;
        if (sel && !sel.isCollapsed && sel.containsNode(view.draft.node, true)) continue;
        view.draft.content.replaceChildren(...this.renderMarkdown(pane.doc, this.draft.text));
        if (atBottom) list.scrollTop = list.scrollHeight;
      } catch (e) {}
    }
  },

  // a run of this paper replaces whatever the panes of the paper show with its transcript
  startPanes(key, kind = this.transcriptKind) {
    for (const pane of this.panes.values()) if (pane.keys.includes(key)) this.showLive(pane, key, kind);
  },

  succeeded(result) {
    return !!result && !result.is_error && (!result.subtype || result.subtype === "success");
  },

  // 完成 · 29 轮 · 2,568k tokens; the run's time is on its folded steps ("Worked for 6m 17s")
  outcome(result, cancelled = false) {
    const ended = result && ["cancelled", "interrupted"].includes(result.subtype) ? result.subtype : null;
    const parts = [this.text(cancelled ? "cancelled" : ended || (this.succeeded(result) ? "done" : "failed"))];
    if (result && result.num_turns > 0) parts.push(this.text("turns", result.num_turns));
    const tokens = this.tokenCounts(result).reduce((n, [, count]) => n + count, 0);
    if (tokens) parts.push(this.text("tokens", this.kTokens(tokens)));
    return parts.join(" · ");
  },

  tokenCounts(result) {
    const u = (result && result.usage) || {};
    return [["tokIn", "input_tokens"], ["tokCacheWrite", "cache_creation_input_tokens"],
            ["tokCacheRead", "cache_read_input_tokens"], ["tokOut", "output_tokens"]]
      .map(([label, k]) => [label, Number(u[k]) || 0]);
  },

  // the token counts behind the total, for the state line's tooltip
  tokenDetail(result) {
    const counts = this.tokenCounts(result);
    return counts.some(([, n]) => n) ? counts.map(([label, n]) => `${this.text(label)} ${this.kTokens(n)}`).join(" · ") : "";
  },

  // 21:05 today, otherwise with the date
  clock(ms) {
    const d = new Date(ms);
    const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    if (d.toDateString() === new Date().toDateString()) return hm;
    return `${this.text("monthDay", d.getMonth() + 1, d.getDate())} ${hm}`;
  },

  // the state line: this paper running, queued or paused, or its latest outcome; other papers' runs are
  // not shown here
  paintPane(pane) {
    try {
      const tab = pane.tab;
      const running = this.job && pane.keys.includes(this.job.key) && (this.job.source.kind || "chat") === tab;
      const queuedAt = this.queue.findIndex(j => pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === tab && !this.isHeld(j));
      // a chat's outcome is its conversation's; the annotation tab's line has a deletion's only (an annotation's is its card)
      const latest = notes => notes.filter(Boolean).sort((a, b) => b.at - a.at)[0] || null;
      const note = tab === "annotate" ? latest(pane.keys.map(k => this.notes.get(`${k}/annotate`)))
        : latest(pane.keys.map(k => [k, this.notes.get(`${k}/chat`)]).filter(([k, n]) => n && (!n.conv || (k === pane.shownKey && n.conv === pane.shownConv)))
          .map(([, n]) => n)) || pane.past;
      // the limit the tab's next run waits for, named by the agent that hit it
      const hold = queuedAt >= 0 ? this.heldByLimit(this.queue[queuedAt]) : null;
      const paused = hold ? this.text(hold.throttled ? "throttledState" : hold.known ? "pausedState" : "pausedRetry", this.clock(hold.until),
                                      this.agentName(hold.agent)) : null;
      // a group's paper the user cannot write annotations to: the annotation tab says so and has no Annotate
      const readOnly = tab === "annotate" && !!pane.item && !this.writable(pane.item);
      const lines = [];
      let kind = "info", title = "";
      if (running) {
        lines.push(this.runningState());
        kind = "running";
      } else if (queuedAt >= 0 && this.queue[queuedAt].retryAt > Date.now()) {
        lines.push(this.text("retryWait"));
        kind = "paused";
      } else if (queuedAt >= 0) {
        // ahead of it, what runs first: not a held message, nor a run that waits for another limit
        const ahead = this.queue.slice(0, queuedAt).filter(j => !this.isHeld(j) && [null, hold].includes(this.heldByLimit(j))).length;
        if (!(paused && ahead === 0)) lines.push(this.text("queuedThis", ahead + (this.job ? 1 : 0)));
        if (paused) { lines.push(paused); kind = "paused"; }
      } else if (readOnly) {
        lines.push(this.text("groupReadOnly"));
      } else if (note) {
        lines.push(note.text);
        kind = note.error ? "error" : "ok";
        title = note.title || "";
      }
      pane.state.className = `scholium-state ${kind}`;
      // one line, cut where the pane is narrow: the whole of it in the tooltip, with the tokens' detail of a finished run
      pane.state.textContent = lines.join(" · ");
      pane.state.title = [running ? this.runningTitle() : lines.join(" · "), title].filter(Boolean).join("\n");
      this.show(pane.state, lines.length > 0);
      const busy = !!running || queuedAt >= 0;
      // any run of the paper, of either tab
      const any = pane.keys.some(k => this.busy(k));
      // no ✎ on the questions while a run of the paper goes or waits
      pane.chatView.className = "scholium-view chat" + (any ? " busy" : "");
      if (pane.editing) pane.editing.fit();   // ✓ of a question being edited, off while the paper runs
      // the views of the tabs and the dot on the tab whose run goes on out of sight
      this.show(pane.chatView, tab === "chat");
      this.show(pane.annotView, tab === "annotate");
      pane.tabChat.className = "scholium-tab" + (tab === "chat" ? " on" : "");
      pane.tabAnnotate.className = "scholium-tab" + (tab === "annotate" ? " on" : "");
      pane.tabChat.setAttribute("aria-selected", String(tab === "chat"));
      pane.tabAnnotate.setAttribute("aria-selected", String(tab === "annotate"));
      pane.tabChat.setAttribute("tabindex", tab === "chat" ? "0" : "-1");
      pane.tabAnnotate.setAttribute("tabindex", tab === "annotate" ? "0" : "-1");
      this.show(pane.tabChatDot, tab !== "chat" && this.busyKind(pane, "chat"));
      this.show(pane.tabAnnotateDot, tab !== "annotate" && this.busyKind(pane, "annotate"));
      this.show(pane.newChat, tab === "chat");
      this.show(pane.historyButton, tab === "chat");
      // an annotation waits behind the paper's chat; not behind another annotation
      pane.annotGo.disabled = this.busyKind(pane, "annotate") || readOnly;
      this.show(pane.resume, !!hold);
      // the conversations of the tab stay as they are while its run goes or waits; the agent while any run of the paper does
      pane.agent.disabled = any;
      pane.newChat.disabled = busy || !pane.shownConv;
      pane.historyButton.disabled = busy;
      if (busy) this.closePopover(pane, "history");
      const asking = running ? !!this.job.asking : queuedAt >= 0 && this.asking(this.queue[queuedAt]);
      // a question while the conversation is a question's; a follow-up once it has turns of another kind (an earlier
      // version's annotation), and while such a run goes or waits
      pane.busy = this.busyKind(pane, tab);
      this.show(pane.composer, !readOnly);
      this.paintSaved(pane);
      // the annotation tab: extra wishes and Annotate until it shows a session; then words to the session, with Annotate
      // again beside the send button; while its run goes or waits, ■
      if (tab === "annotate") {
        const has = !!pane.annot.shownConv;
        pane.input.placeholder = this.text(has || pane.busy ? "annotFollowUpHint" : "annotExtraHint");
        // again over the paper's Scholium annotations, of a session here or not
        pane.annotGo.textContent = this.text(has || pane.annot.own > 0 ? "redoTitle" : "annotateThis");
        this.show(pane.annotGo, !pane.busy);
        this.show(pane.send, has || pane.busy);
      } else {
        pane.input.placeholder = this.text((pane.turns && !pane.question && !running) || (busy && !asking) ? "followPlaceholder" : "askPlaceholder");
        this.show(pane.annotGo, false);
        this.show(pane.send, true);
      }
      this.paintRing(pane);
      this.paintHint(pane);
      this.paintQueue(pane);
      this.paintPapers(pane);
      this.paintQuote(pane);
      this.fitInput(pane);
    } catch (e) {}
  },

  // the other papers of the chat's conversation, as chips above its box; ✕ leaves one out of the next messages and gives
  // the focus to the next chip's ✕, else the previous one's, else the box
  paintPapers(pane) {
    const list = pane.tab === "chat" ? pane.others || [] : [];
    this.show(pane.papersBox, list.length > 0);
    // drawn again only when they change, so that ✕ keeps the focus
    const sig = JSON.stringify(list);
    if (pane.papersSig === sig) return;
    pane.papersSig = sig;
    const doc = pane.doc;
    const lead = doc.createElement("span");
    lead.className = "scholium-papers-lead";
    lead.textContent = this.text("papersLead");
    const drops = [];
    const chips = list.map((ref, i) => {
      const chip = doc.createElement("span");
      chip.className = "scholium-paper";
      const title = doc.createElement("span");
      title.className = "scholium-paper-title";
      title.textContent = ref.title || ref.key;
      chip.title = ref.title || ref.key;
      const drop = this.iconButton(doc, "close", this.text("paperRemove", ref.title || ref.key), () => {
        pane.others = (pane.others || []).filter(r => r !== ref);
        this.paintPapers(pane);
        const left = pane.paperDrops || [];
        try { (left[Math.min(i, left.length - 1)] || pane.input).focus(); } catch (e) {}
      });
      drops.push(drop);
      chip.append(title, drop);
      return chip;
    });
    pane.paperDrops = drops;
    pane.papersBox.replaceChildren(...(list.length ? [lead] : []), ...chips);
  },

  // the passage that goes with the next message, above the box of the chat tab; ✕ takes it away and gives the focus to
  // the box
  paintQuote(pane) {
    const q = pane.tab === "chat" ? pane.quote : null;
    this.show(pane.quoteBox, !!q);
    // drawn again only when the passage changes, so that ✕ keeps the focus
    const sig = q ? this.quoteLabel(q) : null;
    if (!q || pane.quoteSig === sig) { pane.quoteSig = sig; return; }
    pane.quoteSig = sig;
    const text = pane.doc.createElement("span");
    text.className = "scholium-quote-text";
    text.textContent = this.quoteLabel(q);
    const drop = this.iconButton(pane.doc, "close", this.text("quoteRemove"), () => {
      pane.quote = null;
      this.paintQuote(pane);
      try { pane.input.focus(); } catch (e) {}
    });
    pane.quoteBox.replaceChildren(text, drop);
  },

  paintPanes() {
    for (const [body, pane] of this.panes) {
      if (body.isConnected === false) { this.dropPane(body); continue; }
      this.paintPane(pane);
    }
  },

  // whether the Scholium section of the paper with this key is on screen in the focused window, on the tab of a run of
  // this kind; it then shows what a corner notice or the system notification would say
  paneInView(key, kind = "chat") {
    for (const [body, pane] of this.panes) {
      try {
        const win = pane.doc.defaultView;
        if (!pane.seen || !pane.keys.includes(key) || body.isConnected === false || !win || !win.document.hasFocus()) continue;
        if (pane.tab !== kind) continue;   // the other tab shows nothing of it
        if (typeof body.checkVisibility === "function" && !body.checkVisibility({ visibilityProperty: true })) continue;
        return true;
      } catch (e) {}
    }
    return false;
  },

  revealLog(path) {
    if (!path) return;
    try { Zotero.File.reveal(path); } catch (e) { this.log("reveal failed: " + e); }
  },
});
