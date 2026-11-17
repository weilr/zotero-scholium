// ScholiumRunner, continued: editing a question, and undoing an edit

Object.assign(ScholiumRunner, {
  // whether the user's words of a run can be edited and asked again: the chat's own question or follow-up of a
  // conversation in the log, not words steered into a turn nor an annotation's
  promptEditable(view, run) {
    const p = run.prompt;
    return view.kind === "chat" && !!view.pane && !!view.shownKey && !!view.shownConv && !!p && !p.steer && !p.annotate
      && run.turn === p && typeof p.turn === "number";
  },

  // the turn of a log that a run's words started; null when the log no longer has it as it was. Its words are the run's,
  // or the run's followed by words steered into it
  turnOf(log, prompt) {
    const turn = log && typeof prompt.turn === "number" ? log.turns[prompt.turn] : null;
    const user = turn ? String(turn.user) : "", text = String(prompt.text);
    return turn && turn.prompted && !turn.annotate && (user === text || user.startsWith(text + "\n\n")) ? turn : null;
  },

  // where a chat view shows Undo of its conversation's edited question: the index of the question's run; until that is
  // drawn, the run going on (the question starting) or, past the runs, the end of the list (the question waits); -1: none
  undoAt(view) {
    const r = view.kind === "chat" ? this.replaced.get(`${view.shownKey}/${view.shownConv}`) : null;
    if (!r) return -1;
    const runs = this.runsOf(view.entries || []);
    const own = runs.findIndex(x => !!x.prompt && !x.prompt.steer && x.prompt.turn === r.turn);
    return own >= 0 ? own : this.showsRun(view) ? runs.length - 1 : runs.length;
  },

  undoNode(view) {
    const id = `${view.shownKey}/${view.shownConv}`;
    return this.undoStrip(view.doc, this.text("replaced"), () => { this.undoReplace(id).catch(e => this.log("undo failed: " + e)); });
  },

  // the user's words in place as a box, with their quote: ✓ or the send shortcut asks again, ✕ or Esc leaves them, as
  // does ✓ on the words and quote as they were. The paper's annotation leaves the chat free
  startEdit(view, run, said) {
    if (view.pane && this.busy(view.shownKey, "chat")) return;
    if (view.editing) this.stopEdit(view);
    const doc = view.doc, prompt = run.prompt;
    let quote = prompt.quote || null;
    const box = doc.createElement("div");
    box.className = "scholium-entry prompt scholium-edit";
    if (quote) {
      const q = doc.createElement("div");
      q.className = "scholium-prompt-quote";
      const t = doc.createElement("span");
      t.textContent = this.quoteLabel(quote);
      q.append(t, this.iconButton(doc, "close", this.text("quoteRemove"), () => { quote = null; q.remove(); try { input.focus(); } catch (e) {} }));
      box.append(q);
    }
    const input = doc.createElement("textarea");
    input.className = "scholium-edit-input";
    input.setAttribute("rows", "2");
    input.setAttribute("no-native", "true");
    input.setAttribute("no-windows-native", "true");
    input.value = prompt.text;
    // while the chat runs, the box and its words stay until it is free
    const busy = () => !!view.pane && this.busy(view.shownKey, "chat");
    const submit = () => {
      const say = String(input.value || "").trim();
      if (!say || busy()) { fit(); return; }
      this.stopEdit(view);
      if (say === String(prompt.text).trim() && quote === (prompt.quote || null)) return;
      this.editTurn(view, prompt, say, quote).catch(e => this.log("edit failed: " + e));
    };
    const tools = doc.createElement("div");
    tools.className = "scholium-edit-tools";
    const send = this.iconButton(doc, "check", this.text("editSend"), submit);
    tools.append(this.iconButton(doc, "close", this.text("editCancel"), () => this.stopEdit(view)), send);
    const fit = () => { send.disabled = !String(input.value || "").trim() || busy(); };
    input.addEventListener("input", fit);
    input.addEventListener("keydown", e => {
      if (e.isComposing) return;   // the keys of an input method's word are its own
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.stopEdit(view); return; }
      if (this.sendKey(e, input.value)) { e.preventDefault(); submit(); }
    });
    box.append(input, tools);
    fit();
    said.replaceWith(box);
    // paintPane fits it again when the paper starts or stops running; the list drawn again puts it in place of its
    // question (its turn of the conversation, its words) drawn anew
    view.editing = { box, said, fit, input, turn: prompt.turn, text: String(prompt.text), key: view.shownKey, conv: view.shownConv, drawn: false };
    try { input.focus(); } catch (e) {}
  },

  // whether the words of a run drawn are the question being edited: its turn of the same conversation, with its words
  isEditing(view, e, prompt) {
    return e.key === view.shownKey && e.conv === view.shownConv && prompt.turn === e.turn && String(prompt.text) === e.text;
  },

  // the list of a view drawn again by draw(), all of it (from: null) or the run node from: a question being edited keeps
  // its box in place of the question drawn anew, with the focus and the cursor when it had them; the box closes when the
  // part drawn had it and no longer has its question
  redraw(view, from, draw) {
    const e = view.editing;
    if (!e) { draw(); return; }
    const had = !from || from.contains(e.box);
    let cursor = null;
    try { if (view.doc.activeElement === e.input) cursor = [e.input.selectionStart, e.input.selectionEnd]; } catch (err) {}
    e.drawn = false;
    draw();
    if (!e.drawn) { if (had) view.editing = null; return; }
    if (cursor) { try { e.input.focus(); e.input.setSelectionRange(cursor[0], cursor[1]); } catch (err) {} }
  },

  stopEdit(view) {
    const e = view.editing;
    view.editing = null;
    if (e) { try { e.box.replaceWith(e.said); } catch (err) {} }
  },

  // an earlier question of the chat asked again with new words, answered by the agent chosen: the turns from it on leave the
  // log, and the agents go on from the conversation before it (Claude Code: that point of the session as a new session;
  // Codex: a fork of the thread through the turn before); Undo brings the old log back for a few seconds
  async editTurn(view, prompt, say, quote = null) {
    const pane = view.pane, key = view.shownKey, conv = view.shownConv;
    say = String(say || "").trim();
    if (!pane || !key || !conv || !say || this.busy(key, "chat") || !this.localApiReady()) return false;
    const path = this.convPath(key, conv), id = `${key}/${conv}`;
    await this.flushLog(path);
    if (this.pendingLogs.has(path)) {
      this.notes.set(`${key}/chat`, { text: this.text("logNotSaved"), error: true, at: Date.now(), conv, pendingLog: path });
      this.refresh();
      return false;
    }
    const log = await this.readLog(key, conv);
    const turn = this.turnOf(log, prompt);
    if (!turn) return false;
    let old;
    try { old = await IOUtils.readUTF8(path); } catch (e) { this.log("conversation not read: " + e); return false; }
    const previous = this.replaced.get(id);
    if (previous && (previous.restoring || previous.failed)) return false;
    if (previous) this.endReplaced(id);   // the edit before: its old text goes now
    const agent = this.agent();   // the agent chosen now answers the edited question
    const index = await this.index(key);
    const at = log.turns.indexOf(turn);
    const r = { key, conv, path, text: old, note: this.notes.get(`${key}/chat`) || null,
                title: index.titles[conv], retitled: false, timer: null, turn: prompt.turn };
    // the first question names the conversation, unless it was renamed
    if (at === 0 && index.titles[conv] === this.cut(String(prompt.text).split("\n")[0], 64)) {
      index.titles[conv] = this.cut(say.split("\n")[0], 64);
      r.retitled = true;
      await this.saveIndex(key);
    }
    // an agent with a session at the question's start goes back to its point before it (one without a point, to a new
    // session given the conversation before it) when it answers the edit or its session moved on since: it saw the question
    // or what followed, waits to go back, or is another one now. An agent without a session there starts one from the
    // conversation kept. The first question leaves an empty log
    const points = {};
    for (const a of this.AGENTS) {
      const was = turn.sessions[a], now = log.agents[a];
      if (was && (a === agent || now.session !== was || now.through >= at || now.rewind)) points[a] = turn.points[a] || null;
    }
    // an edit before left its own marker at the end of the kept text: it goes, so that one marker is left, which still
    // takes back the agents only that one named (an earlier version's marker names the log's own agent)
    const kept = old.slice(0, turn.start).split("\n").reverse();
    while (kept.length > 1 && this.isRewindMarker(kept[1])) {
      const was = JSON.parse(kept.splice(1, 1)[0]);
      const named = was.points && typeof was.points === "object" ? was.points : { [this.convAgent(conv)]: was.point };
      for (const a of this.AGENTS) {
        if (Object.prototype.hasOwnProperty.call(named, a) && !Object.prototype.hasOwnProperty.call(points, a)) points[a] = this.pointOf(named[a]);
      }
    }
    const marker = at === 0 ? "" : JSON.stringify({ type: "scholium", subtype: "rewind", points }) + "\n";
    try { await IOUtils.writeUTF8(path, kept.reverse().join("\n") + marker, { tmpPath: path + ".tmp" }); }
    catch (e) {
      this.log("conversation not cut: " + e);
      if (r.retitled) { index.titles[conv] = r.title; await this.saveIndex(key); }
      return false;
    }
    this.replaced.set(id, r);
    await this.chooseConv(key, conv);
    const att = this.attOf(pane.item.libraryID, key);
    let sent = false;
    try { sent = await this.send(att || pane.item, say, { kind: "chat", conv, agent, quote, rewind: this.pointOf(points[agent]), edited: true }); }
    catch (e) { this.log("edit not sent: " + e); }
    if (!sent) { await this.undoReplace(id); return false; }
    if (this.replaced.get(id) === r) r.timer = setTimeout(() => this.undoTimeUp(id), this.UNDO_MS);
    // an edit that waits behind another run (another paper's, the paper's annotation): the sections show the
    // conversation cut, with Undo
    if (!this.runOfConv(key, "chat", conv)) {
      for (const p of [...this.panes.values()]) if (p.keys.includes(key)) await this.showConversation(p);
    }
    return true;
  },

  // whether a line of a log is the marker of an edited question's cut
  isRewindMarker(line) {
    try { const e = JSON.parse(line); return !!e && e.type === "scholium" && e.subtype === "rewind"; } catch (e) { return false; }
  },

  // Undo of an edited question: its run stops (or leaves the queue before it started) without a word, the messages queued
  // behind it are held, and the log, the title and the state line come back as they were; Codex archives the fork
  async undoReplace(id) {
    const r = this.replaced.get(id);
    if (!r || r.restoring) return;
    clearTimeout(r.timer);
    r.restoring = true;
    r.failed = false;
    let pending = null;
    try {
      const mine = j => this.keyOf(j.att) === r.key && (j.kind || "chat") === "chat" && (j.conv || null) === r.conv;
      for (const j of this.queue) if (j.qid && mine(j)) this.heldQueues.add(this.queueKey(j));
      this.queue = this.queue.filter(j => j.qid || !mine(j));
      const runOf = () => [...this.runs.values()].find(x => !x.gone && x.key === r.key && mine(x.source)) || null;
      const current = () => !!runOf();
      if (current()) {
        const x = runOf();
        r.run = x.source.logRun;
        x.source.undone = true;
        this.cancel(x);
      }
      const running = () => current() || !!(r.run && !r.run.done);
      for (let i = 0; i < 400 && running(); i++) await Zotero.Promise.delay(25);
      if (running()) throw new Error("edited run has not stopped");
      pending = this.pendingLogs.get(r.path) || { unlogged: [], flushing: null };
      pending.held = true;
      pending.restore = r;
      this.pendingLogs.set(r.path, pending);
      if (pending.flushing) await pending.flushing;
      // the Codex threads made after the edit, which the old log does not use, are archived once the old log is back
      let now = "";
      try { now = await IOUtils.readUTF8(r.path); } catch (e) {}
      const kept = this.codexThreads(r.text);
      const gone = [...this.codexThreads(now)].filter(thread => !kept.has(thread));
      await IOUtils.writeUTF8(r.path, r.text, { tmpPath: r.path + ".tmp" });
      pending.unlogged.splice(0);
      this.parsedLogs.delete(r.path);
      this.lastEntries.delete(r.path);   // the conversation as its log has it again
      if (r.retitled) {
        const index = await this.index(r.key);
        if (r.title === undefined) delete index.titles[r.conv];
        else index.titles[r.conv] = r.title;
        await this.saveIndex(r.key);
      }
      this.pendingLogs.delete(r.path);
      this.replaced.delete(id);
      for (const thread of gone) this.queueArchive(thread);
      if (r.note) this.notes.set(`${r.key}/chat`, r.note);
      else this.notes.delete(`${r.key}/chat`);
      this.refresh();
      for (const pane of [...this.panes.values()]) {
        if (!pane.keys.includes(r.key)) continue;
        pane.live = false;   // the run it showed as it went left the conversation: all of it is drawn anew
        await this.showConversation(pane).catch(e => this.log("restored conversation not shown: " + e));
      }
    } catch (e) {
      r.failed = true;
      pending = this.pendingLogs.get(r.path) || { unlogged: [], flushing: null };
      pending.held = true;
      pending.restore = r;
      this.pendingLogs.set(r.path, pending);
      this.log("conversation not restored: " + e);
      this.notes.set(`${r.key}/chat`, { text: this.text("undoNotRestored"), error: true, at: Date.now(), conv: r.conv });
      this.refresh();
    } finally {
      r.restoring = false;
      // A failed restore keeps the edited tail held until Undo is retried.
      if (pending && !r.failed) pending.held = false;
    }
  },

  // the Undo seconds of an edit are up: its old conversation goes, unless the edited question still waits to start (behind
  // another paper's run), until when Undo, or ■, brings it back
  undoTimeUp(id) {
    const r = this.replaced.get(id);
    if (!r) return;
    if (r.restoring || r.failed) return;
    if (this.queue.some(j => j.edited && `${this.keyOf(j.att)}/${j.conv}` === id && !this.started(j))) r.timer = setTimeout(() => this.undoTimeUp(id), this.UNDO_MS);
    else this.endReplaced(id);
  },

  // the old conversation of an edit can no longer come back: its Undo goes
  endReplaced(id) {
    const r = this.replaced.get(id);
    if (!r) return;
    if (r.restoring || r.failed) return;
    clearTimeout(r.timer);
    this.replaced.delete(id);
    this.dropUndo(r.key, r.conv);
    this.archiveReplaced(r);
  },

  // the Codex threads only the replaced text of an edit used are archived
  archiveReplaced(r) {
    IOUtils.readUTF8(r.path).then(now => {
      const kept = this.codexThreads(now);
      for (const thread of this.codexThreads(r.text)) if (!kept.has(thread)) this.queueArchive(thread);
    }).catch(e => this.log("replaced threads not archived: " + e));
  },

  // the Undo of an edit leaves the chat views of its conversation: under a run or after them; the rest stays as it is, a
  // box being edited too. A view's strip is the conversation's it shows: another one is drawn anew
  dropUndo(key, conv) {
    for (const pane of [...this.panes.values()]) {
      if (pane.shownKey !== key || pane.shownConv !== conv) continue;
      for (const n of [...pane.list.children]) {
        if (n.className === "scholium-undo") n.remove();
        else for (const c of [...(n.children || [])]) if (c.className === "scholium-undo") c.remove();
      }
    }
  },
});
