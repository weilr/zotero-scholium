// ScholiumRunner, continued: Save as note, notices, Annotate, editing a question, sending, the queue and the pauses
// for usage limits, and the end of a run

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
      this.noteNotice(att);
      try { await Zotero.getMainWindow().ZoteroPane.selectItem(note.id); } catch (e) { this.log("note not selected: " + e); }
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

  async annotate(items, { extra = "", confirmed = false, replace = false } = {}) {
    let jobs = [];
    let found = 0, readOnly = false;
    for (const item of items || []) {
      try {
        const job = await this.resolve(item);
        if (job) found += 1;
        if (job && !this.writable(job.att)) { readOnly = true; continue; }
        if (job && !jobs.some(j => this.keyOf(j.att) === this.keyOf(job.att)) && !this.busy(this.keyOf(job.att), "annotate")) jobs.push(job);
      } catch (e) { this.log("resolve failed: " + e); }
    }
    const win = Zotero.getMainWindow();
    if (!found) {
      Services.prompt.alert(win, this.text("headline"), this.text(this.pdfAttachments(items).length ? "noFile" : "noPdf"));
      return 0;
    }
    if (!jobs.length && readOnly) { Services.prompt.alert(win, this.text("headline"), this.text("groupReadOnly")); return 0; }
    if (!jobs.length) { this.refresh(); return 0; }   // every paper is already queued or running
    // the first annotation in a group's library, once for each group: its members see what is written there
    const asked = String(this.getPref("groupsAsked") || "").split(",").filter(Boolean);
    const groups = [...new Set(jobs.map(j => this.groupOf(j.att.libraryID)).filter(g => g && !asked.includes(String(g))))];
    if (groups.length) {
      if (!Services.prompt.confirm(win, this.text("groupFirstTitle"), this.text("groupFirst"))) {
        jobs = jobs.filter(j => !groups.includes(this.groupOf(j.att.libraryID)));
        if (!jobs.length) return 0;
      } else {
        try { Zotero.Prefs.set(this.pref + "groupsAsked", asked.concat(groups.map(String)).join(","), true); }
        catch (e) { this.log("preference not saved: " + e); }
      }
    }
    if (!this.localApiReady()) return 0;
    const own = jobs.map(j => j.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length);
    const total = own.reduce((a, b) => a + b, 0);
    const replaced = jobs.filter((j, i) => own[i] > 0).map(j => j.att);
    if (total && !confirmed) {
      const shared = replaced.some(a => this.groupOf(a.libraryID));
      if (!Services.prompt.confirm(win, this.text("redoTitle"), this.text("redo", total, this.clearedNotes(replaced).length, shared))) return 0;
      replace = true;
    }
    for (const [i, j] of jobs.entries()) {
      Object.assign(j, { own: own[i], extra, agent: this.agent(), annotate: true, asking: false, kind: "annotate" });
      await this.place(j);
    }
    // another annotation may have been queued for a paper meanwhile
    let ready = jobs.filter(j => !this.busy(this.keyOf(j.att), "annotate"));
    if (!ready.length) { this.refresh(); return 0; }
    // the user agreed to replace them: the papers' Scholium annotations are deleted now and their Scholium notes moved
    // to the trash, before the runs start
    const redone = replace ? ready.filter(j => j.own > 0) : [];
    if (redone.length) {
      try { await this.clearOwn(redone.map(j => j.att)); } catch (e) { this.log("delete failed: " + e); }
      for (const j of redone) j.own = j.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
      ready = ready.filter(j => !this.busy(this.keyOf(j.att), "annotate"));
      if (!ready.length) { this.refresh(); return 0; }
    }
    this.enqueue(ready);
    // a paper's tab that shows an earlier session shows the session to come while its annotation waits
    const waiting = ready.filter(j => this.queue.includes(j));
    for (const pane of [...this.panes.values()]) {
      const shows = j => pane.keys.includes(this.keyOf(j.att));
      if ((pane.annot.shownConv || redone.some(shows)) && waiting.some(shows)) this.showAnnotation(pane).catch(e => this.log("section not shown: " + e));
    }
    return ready.length;
  },

  // a job's conversation: the one the paper's messages go to (on the annotation tab, the agent's latest annotation
  // session), the agent's session there when it still holds one, and whether its message is the first one; a new
  // conversation (conv null) starts when the job runs
  async place(job) {
    // the agent's own session of the conversation
    const mine = log => (log && log.agents[job.agent === "codex" ? "codex" : "claude"]) || null;
    if ((job.retry || job.compact || job.qid) && job.conv) {
      if (job.kind === "annotate") job.agent = this.convAgent(job.conv);   // an annotation session is its agent's own
      const log = await this.readLog(this.keyOf(job.att), job.conv), a = mine(log);
      job.resume = (a && a.session) || null;
      job.rewind = job.resume ? (a && a.rewind) || null : null;
      job.question = false;
      if (!job.annotate) job.asking = !!(log && log.question);
      return;
    }
    // an annotation starts a session of its own when it runs
    if (job.annotate) { Object.assign(job, { conv: null, resume: null, question: false, asking: false }); return; }
    const conv = job.kind === "annotate" ? await this.annotationConv(this.keyOf(job.att), job.agent) : await this.currentConv(this.keyOf(job.att));
    const log = conv ? await this.readLog(this.keyOf(job.att), conv) : null, a = mine(log);
    job.conv = conv;
    job.resume = (a && a.session) || null;
    // an edited question goes back to its point; a message after an edit whose run never reached the agent, to that one's
    job.rewind = job.resume ? job.rewind || (a && a.rewind) || null : null;
    // words to an annotation session are not a question
    job.question = job.kind !== "annotate" && !!job.say && !(log && log.turns.length);
    job.asking = job.question || !!(log && log.question);
  },

  // the last turn of a view's conversation again, in the same conversation; its words are in the log already
  async retryFromView(view) {
    const pane = view.pane, key = view.shownKey, conv = view.shownConv;
    if (!pane || !key || !conv) return;
    const log = await this.readLog(key, conv);
    const turn = log && log.turns[log.turns.length - 1];
    if (!turn || view.shownKey !== key || view.shownConv !== conv) return;
    const att = this.attOf(pane.item.libraryID, key);
    if (this.busy(key)) return;
    // the chat's turn goes to the agent chosen now; an annotation session's to its own agent
    const agent = view.kind === "chat" ? this.agent() : this.convAgent(conv);
    // the retried conversation is the one the chat's messages go to; the annotation tab's is its latest session already
    if (view.kind === "chat") await this.chooseConv(key, conv);
    await this.send(att, turn.user, { retry: true, conv, kind: view.kind, agent, quote: turn.quote || null });
  },

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

  // the user's words in place as a box, with their quote: ✓ or the send shortcut asks again, ✕ or Esc leaves them
  startEdit(view, run, said) {
    if (view.pane && this.busy(view.shownKey)) return;
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
    // while the paper runs, the box and its words stay until it is free
    const busy = () => !!view.pane && this.busy(view.shownKey);
    const submit = () => {
      const say = String(input.value || "").trim();
      if (!say || busy()) { fit(); return; }
      this.stopEdit(view);
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
    if (!pane || !key || !conv || !say || this.busy(key) || !this.localApiReady()) return false;
    const log = await this.readLog(key, conv);
    const turn = this.turnOf(log, prompt);
    if (!turn) return false;
    const path = this.convPath(key, conv), id = `${key}/${conv}`;
    let old;
    try { old = await IOUtils.readUTF8(path); } catch (e) { this.log("conversation not read: " + e); return false; }
    if (this.replaced.has(id)) this.endReplaced(id);   // the edit before: its old text goes now
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
    // an edit that waits behind another paper's run: the sections show the conversation cut, with Undo
    if (!(this.job && this.job.key === key)) for (const p of [...this.panes.values()]) if (p.keys.includes(key)) await this.showConversation(p);
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
    if (!r) return;
    clearTimeout(r.timer);
    this.replaced.delete(id);
    const mine = j => this.keyOf(j.att) === r.key && (j.kind || "chat") === "chat" && (j.conv || null) === r.conv;
    for (const j of this.queue) if (j.qid && mine(j)) this.heldQueues.add(this.queueKey(j));
    this.queue = this.queue.filter(j => j.qid || !mine(j));
    const running = () => !!this.job && this.job.key === r.key && mine(this.job.source);
    if (running()) {
      this.job.source.undone = true;
      this.cancel();
      for (let i = 0; i < 400 && running(); i++) await Zotero.Promise.delay(25);
    }
    // the Codex threads made after the edit, which the old log does not use, are archived once the old log is back
    let now = "";
    try { now = await IOUtils.readUTF8(r.path); } catch (e) {}
    const kept = this.codexThreads(r.text);
    const gone = [...this.codexThreads(now)].filter(thread => !kept.has(thread));
    try { await IOUtils.writeUTF8(r.path, r.text, { tmpPath: r.path + ".tmp" }); }
    catch (e) { this.log("conversation not restored: " + e); return; }
    for (const thread of gone) this.queueArchive(thread);
    if (r.retitled) {
      const index = await this.index(r.key);
      if (r.title === undefined) delete index.titles[r.conv];
      else index.titles[r.conv] = r.title;
      await this.saveIndex(r.key);
    }
    if (r.note) this.notes.set(`${r.key}/chat`, r.note);
    else this.notes.delete(`${r.key}/chat`);
    if (this.transcriptPath === r.path) {
      const back = await this.readLog(r.key, r.conv);
      this.transcript = back ? back.entries : [];
    }
    this.refresh();
    for (const pane of [...this.panes.values()]) {
      if (!pane.keys.includes(r.key)) continue;
      pane.live = false;   // the run it showed as it went left the conversation: all of it is drawn anew
      await this.showConversation(pane);
    }
  },

  // the Undo seconds of an edit are up: its old conversation goes, unless the edited question still waits to start (behind
  // another paper's run), until when Undo, or ■, brings it back
  undoTimeUp(id) {
    const r = this.replaced.get(id);
    if (!r) return;
    if (this.queue.some(j => j.edited && `${this.keyOf(j.att)}/${j.conv}` === id && !this.started(j))) r.timer = setTimeout(() => this.undoTimeUp(id), this.UNDO_MS);
    else this.endReplaced(id);
  },

  // the old conversation of an edit can no longer come back: its Undo goes
  endReplaced(id) {
    const r = this.replaced.get(id);
    if (!r) return;
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

  // the user's words to the paper, to the chosen agent in the conversation the paper's messages go to: the first message of
  // a new one, which answers without annotating, or the next one; while the paper's run of the tab goes on or waits, a
  // message queued behind it; false when that is not possible now. opts: retry (the same words again in conv, already
  // logged), compact, kind, conv (the conversation a queued message belongs to), before (a held queued message the words go
  // ahead of), quote, agent, rewind (the point an edited question goes back to), edited
  async send(item, say, opts = {}) {
    if (!item || (!say && !opts.compact)) return false;
    const job = await this.resolve(item);
    if (!job) {
      Services.prompt.alert(Zotero.getMainWindow(), this.text("headline"), this.text(this.pdfAttachments([item]).length ? "noFile" : "noPdf"));
      return false;
    }
    const kind = opts.kind === "annotate" ? "annotate" : "chat";
    // words to the annotation tab write annotations, which a group's library the user cannot edit does not take; a
    // question there is answered
    if (kind === "annotate" && !opts.compact && !this.writable(job.att)) {
      Services.prompt.alert(Zotero.getMainWindow(), this.text("headline"), this.text("groupReadOnly"));
      return false;
    }
    if (!opts.compact && !this.localApiReady()) return false;
    // the paper's run of the other tab leaves it free; a compaction, a retry or an edited question is no message to queue
    const busy = this.busy(this.keyOf(job.att), kind);
    if (busy && (opts.compact || opts.retry || opts.edited)) return false;
    Object.assign(job, { agent: (opts.retry || opts.edited) && opts.agent ? opts.agent : this.agent(), say, own: job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length,
                         kind, retry: !!opts.retry, compact: !!opts.compact, quote: opts.quote || null, rewind: opts.rewind || null,
                         edited: !!opts.edited,
                         // a new message, in the order sent (a retry or an edit is none): it may confirm what a run before it
                         // held back (confirmedFor)
                         sentSeq: opts.retry || opts.edited || opts.compact ? 0 : ++this.sendSeq },
                  // the other papers of a chat's message; without them, a run takes those its conversation's log names
                  kind === "chat" && Array.isArray(opts.papers) ? { papers: opts.papers } : {});
    // the paper is busy: the words wait in the queue of the conversation, as Codex queues a follow-up
    if (busy) {
      Object.assign(job, { qid: String(++this.qseq), conv: opts.conv || null });
      if (kind === "annotate" && job.conv) job.agent = this.convAgent(job.conv);   // an annotation session's, from now on
      this.queue.splice(this.followUpAt(job), 0, job);
      this.refresh();   // the queue drains already: the run it waits for goes on, or waits in it
      return true;
    }
    // words to the annotation tab without a session go with a new annotation, as its extra wishes
    if (kind === "annotate" && !opts.retry && !opts.compact && !(await this.annotationConv(this.keyOf(job.att), this.agent()))) {
      return (await this.annotate([job.att], { extra: say })) > 0;
    }
    if (opts.retry) Object.assign(job, { conv: opts.conv, logged: true });
    // a compaction is the shown conversation's: the chat's by the agent chosen, an annotation session's by its own agent
    if (opts.compact) Object.assign(job, { conv: opts.conv, agent: kind === "annotate" ? this.convAgent(opts.conv) : job.agent });
    await this.place(job);
    if (job.compact && !job.resume) return false;
    if (this.busy(this.keyOf(job.att), kind)) return false;
    // ahead of a held queue it is sent past (Send message), else where a conversation's message goes
    const ahead = opts.before ? this.queue.indexOf(opts.before) : -1;
    this.enqueue([job], ahead >= 0 ? ahead : this.conversationAt());
    return true;
  },

  // the words of a message that did not reach the agent's log go back to the box they were typed in, unless something
  // else was typed there since; a queued message stays in the queue instead, marked (drain)
  giveBack(job) {
    if (job.qid) return;
    const words = job.compact ? "/compact" + (job.say ? " " + job.say : "") : job.say;
    if (!words || this.started(job) || job.fresh || job.logged) return;
    const att = job.att;
    const agent = (job.kind || "chat") === "annotate" ? job.agent : "";
    const keys = [att.parentItemKey, att.key].filter(Boolean).map(item => `${att.libraryID}/${item}/${job.kind || "chat"}/${agent}/${job.conv || ""}`);
    for (const k of keys) if (!this.unsent.get(k)) this.unsent.set(k, words);
    for (const pane of this.panes.values()) {
      if (!keys.includes(this.unsentKey(pane)) || String(pane.input.value || "").trim()) continue;
      pane.input.value = words;
      if (job.quote && !pane.quote && !job.compact) { pane.quote = job.quote; this.paintQuote(pane); }
      this.fitInput(pane);
    }
  },

  // a job that did not start: its words go back to its box; an annotation's wishes, with the words queued for its session
  // to come, to its tab, drawn again unless what ended the job stays on it
  handBack(job, redraw = true) {
    if (!job.annotate) return this.giveBack(job);
    const queued = job.conv ? [] : this.queue.filter(j => j.qid && (j.kind || "chat") === "annotate" && !j.conv && this.keyOf(j.att) === this.keyOf(job.att));
    this.queue = this.queue.filter(j => !queued.includes(j));
    this.annotationBack(job, queued, redraw).catch(err => this.log("annotation not given back: " + err));
  },

  // a paper moved to the trash, or whose parent was, while it waited
  discarded(att) {
    try { return !!(att.deleted || (att.parentItem && att.parentItem.deleted)); } catch (e) { return false; }
  },

  // where a message of a conversation joins the queue: before the papers still waiting for their first run, after
  // the paper that the usage limit or a failed connection interrupted and after the other conversations
  conversationAt() {
    let at = 0;
    const talk = j => !!j.say || (!!j.resume && !j.annotate) || j.retried || j.interrupted;
    while (at < this.queue.length && talk(this.queue[at])) at++;
    return at;
  },

  // whether a paper's run belongs to a conversation that a question started and no annotation continued
  asking(job) {
    return !!(job && !job.annotate && job.asking);
  },

  // whether a paper has a run going on or waiting; of one kind only, when given. A held queued message waits for Resume,
  // not for a run: it leaves the paper free
  busy(key, kind = null) {
    const of = j => !kind || (j.kind || "chat") === kind;
    return !!(this.job && this.job.key === key && of(this.job.source)) || this.queue.some(j => this.keyOf(j.att) === key && of(j) && !this.isHeld(j));
  },

  // where a follow-up joins the queue: after what is queued for its conversation, else where a conversation's message goes
  followUpAt(job) {
    const k = this.queueKey(job);
    for (let i = this.queue.length - 1; i >= 0; i--) if (this.queueKey(this.queue[i]) === k) return i + 1;
    return this.conversationAt();
  },

  // the queue of a conversation (of a tab of a paper): its queued messages go one after another, held together; one
  // queued before its conversation had its log is in the queue of none until the run before it makes one (run)
  queueKey(job) { return `${this.keyOf(job.att)}/${job.kind || "chat"}/${job.conv || ""}`; },

  // whether a job is a message queued to the conversation a tab shows
  shownQueued(pane, job) {
    const view = this.viewOf(pane, pane.tab);
    return !!job.qid && pane.keys.includes(this.keyOf(job.att)) && (job.kind || "chat") === pane.tab && (job.conv || null) === (view.shownConv || null);
  },

  // a queued message that waits: its queue held after a stop, or behind a message of it that could not be sent
  isHeld(job) {
    if (!job.qid) return false;
    const k = this.queueKey(job);
    return this.heldQueues.has(k) || this.queue.some(q => q.failed && this.queueKey(q) === k);
  },

  // a held queue lets go once none of its messages is left, nor can be brought back
  tidyHeld() {
    for (const k of [...this.heldQueues]) {
      const its = j => !!j.qid && this.queueKey(j) === k;
      if (!this.queue.some(its) && ![...this.removedQueued.values()].some(r => its(r.job))) this.heldQueues.delete(k);
    }
  },

  queuedAt(qid) { return this.queue.findIndex(j => j.qid === qid); },

  // a queued message dragged onto another of its queue goes before it
  moveQueued(from, before) {
    const i = this.queuedAt(from), j = this.queuedAt(before);
    if (i < 0 || j < 0 || i === j || this.queueKey(this.queue[i]) !== this.queueKey(this.queue[j])) return;
    const [job] = this.queue.splice(i, 1);
    this.queue.splice(this.queuedAt(before), 0, job);
    this.refresh();
  },

  // where a queued message goes back into its own queue: before the row that followed it, else after the last row of its
  // queue, else where a follow-up of its conversation goes (never ahead of that conversation's own runs)
  backAt(job, next = null) {
    const n = next ? this.queuedAt(next) : -1;
    if (n >= 0) return n;
    const k = this.queueKey(job);
    for (let i = this.queue.length - 1; i >= 0; i--) if (this.queue[i].qid && this.queueKey(this.queue[i]) === k) return i + 1;
    return this.followUpAt(job);
  },

  // the row of a message's queue after a place in the queue
  nextRow(job, from) {
    const k = this.queueKey(job);
    const next = this.queue.slice(from).find(j => j.qid && this.queueKey(j) === k);
    return next ? next.qid : null;
  },

  // ✕: out of the queue, for a moment with Undo in its place; the messages behind a failed one go on
  removeQueued(pane, qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const [job] = this.queue.splice(i, 1);
    const timer = setTimeout(() => { this.removedQueued.delete(qid); this.refresh(); }, this.QUEUE_UNDO_MS);
    this.removedQueued.set(qid, { job, next: this.nextRow(job, i), timer });
    this.refresh();
    if (!this.draining) this.drain();
  },

  undoRemoveQueued(qid) {
    const r = this.removedQueued.get(qid);
    if (!r) return;
    clearTimeout(r.timer);
    this.removedQueued.delete(qid);
    this.queue.splice(this.backAt(r.job, r.next), 0, r.job);
    this.refresh();
    if (!this.draining) this.drain();
  },

  // a queued message back in the box, before what is typed there; the messages behind a failed one go on
  editQueued(pane, qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const [job] = this.queue.splice(i, 1);
    const typed = String(pane.input.value || "").trim();
    pane.input.value = typed ? job.say + "\n\n" + typed : job.say;
    if (job.quote && !pane.quote) { pane.quote = job.quote; this.paintQuote(pane); }
    this.keepUnsent(pane);
    this.fitInput(pane);
    try { pane.input.focus(); } catch (e) {}
    this.refresh();
    if (!this.draining) this.drain();
  },

  // Send on a row of a held queue: that message first, and the queue goes on
  sendQueuedNow(qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const [job] = this.queue.splice(i, 1);
    const k = this.queueKey(job);
    const first = this.queue.findIndex(j => j.qid && this.queueKey(j) === k);
    this.queue.splice(first < 0 ? this.followUpAt(job) : first, 0, job);
    this.releaseQueue(job);
  },

  retryQueued(qid) {
    const job = this.queue[this.queuedAt(qid)];
    if (!job) return;
    job.failed = false;
    this.refresh();
    if (!this.draining) this.drain();
  },

  // Resume: the held queue goes on
  releaseQueue(job) {
    this.heldQueues.delete(this.queueKey(job));
    this.refresh();
    if (!this.draining) this.drain();
  },

  // Clear queue: its messages go, and with them its hold (tidyHeld)
  dropQueued(jobs) {
    this.queue = this.queue.filter(j => !jobs.includes(j));
    this.refresh();
  },

  // Steer on a row (greyed unless steerable): the message into the answer under way, out of the queue
  async steerQueued(pane, qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const job = this.queue[i];
    if (!(await this.steerFromPane(pane, job.say, job.quote))) return;
    const k = this.queuedAt(qid);
    if (k >= 0) this.queue.splice(k, 1);
    this.refresh();
  },

  enqueue(jobs, at = this.queue.length) {
    if (this.stopped) return;
    this.queue.splice(Math.min(at, this.queue.length), 0, ...jobs);
    this.refresh();
    if (!this.draining) this.drain();
  },

  // take papers out of the queue, their runs of one kind only when given, and their queued messages unless `rows` is
  // false; an agent's pause ends once nothing but held messages is left of its runs. A message that had not started
  // goes back to its box, an annotation's wishes too, with the messages queued for its session to come (which leave the
  // queue with it); an edited question that had not started is undone
  dequeue(keys, kind = null, { rows = true } = {}) {
    const ours = j => keys.includes(this.keyOf(j.att)) && (!kind || (j.kind || "chat") === kind) && (rows || !j.qid);
    const removed = this.queue.filter(ours);
    const coming = j => removed.some(a => a.annotate && !a.conv && !this.started(a) && this.keyOf(a.att) === this.keyOf(j.att));
    const toCome = this.queue.filter(j => j.qid && (j.kind || "chat") === "annotate" && !j.conv && coming(j));
    this.queue = this.queue.filter(j => !ours(j) && !toCome.includes(j));
    for (const agent of Object.keys(this.paused || {})) {
      if (!this.queue.some(j => !this.isHeld(j) && this.agentOf(j) === agent)) this.endPause(agent);
    }
    this.refresh();
    for (const job of removed) {
      if (this.started(job)) this.endWaiting(job).catch(e => this.log("cancel not logged: " + e));
      else if (job.edited && job.conv) this.undoReplace(`${this.keyOf(job.att)}/${job.conv}`).catch(e => this.log("edit not undone: " + e));
      else if (job.annotate) {
        const queued = job.conv ? [] : toCome.filter(j => this.keyOf(j.att) === this.keyOf(job.att));
        this.annotationBack(job, queued).catch(e => this.log("annotation not given back: " + e));
      } else this.giveBack(job);
    }
  },

  // an annotation that did not start: its tab shows the paper's session again, its extra wishes, the words queued for
  // its session to come and those typed to it meanwhile back in the tab's box, in one piece
  async annotationBack(job, queued = [], redraw = true) {
    const words = [job.extra].concat(queued.map(j => j.say), job.typed || []).filter(Boolean).join("\n\n");
    if (words) this.giveBack(Object.assign({}, job, { say: words, conv: await this.annotationConv(this.keyOf(job.att), job.agent) }));
    if (redraw) for (const pane of [...this.panes.values()]) if (pane.keys.includes(this.keyOf(job.att))) await this.showAnnotation(pane);
  },

  // an annotation's new session whose log refused its first line: its empty log goes, the agent's session before it is
  // the paper's again, and the messages queued for it wait for a session to come again
  async unmakeConv(key, agent, made) {
    for (const q of this.queue) {
      if (!q.qid || q.conv !== made.conv || this.keyOf(q.att) !== key) continue;
      const was = this.queueKey(q);
      q.conv = null;
      if (this.heldQueues.delete(was)) this.heldQueues.add(this.queueKey(q));
    }
    // words typed to it meanwhile (livePanes moved them to it) come back with the annotation's wishes
    made.typed = [];
    for (const [k, text] of [...this.unsent]) {
      if (!k.endsWith("/" + made.conv)) continue;
      this.unsent.delete(k);
      if (!made.typed.includes(text)) made.typed.push(text);
    }
    const index = await this.index(key);
    if (index.annotation[agent] === made.conv) {
      if (made.before) index.annotation[agent] = made.before;
      else delete index.annotation[agent];
    }
    delete index.titles[made.conv];
    await this.saveIndex(key);
    const path = this.convPath(key, made.conv);
    if ((await IOUtils.stat(path)).size === 0) await IOUtils.remove(path);
  },

  // whether a queued paper's conversation has its run already: one waiting for its second try, for a limit to reset,
  // or handed over by an update
  started(job) {
    return !!(job.retried || job.interrupted || (job.resume && !job.say && !job.annotate && !job.compact));
  },

  // a paper whose run waited ends as cancelled, in its log and its sections
  async endWaiting(job) {
    const key = this.keyOf(job.att);
    if ((job.kind || "chat") === "chat") this.notes.set(`${key}/chat`, { text: this.text("cancelled"), error: true, at: Date.now(), conv: job.conv || null });
    else this.notes.delete(`${key}/annotate`);
    if (job.conv) {
      const path = this.convPath(key, job.conv);
      const marks = [await this.logEnd(path, "cancelled", this.text("cancelled")), { type: "scholium", subtype: "time", at: Date.now(), waited: true }];
      try { await IOUtils.writeUTF8(path, JSON.stringify(marks[1]) + "\n", { mode: "append" }); }
      catch (e) { this.log("end time not logged: " + e); }
      if (this.transcriptPath === path) this.appendEntries(marks.flatMap(m => this.entries(m)));
    }
    this.refresh();
    for (const pane of [...this.panes.values()]) if (pane.keys.includes(key)) await this.showConversation(pane);
  },

  // one paper at a time; `draining` also covers the moments before a process exists. An agent's usage limit
  // pauses that agent's runs.
  async drain() {
    this.draining = true;
    try {
      while (this.queue.length) {
        // a held queued message waits for Resume, and those behind a failed one for it; a run of an agent whose limit
        // holds waits for its reset, and what follows it of its paper's tab with it
        const i = this.queue.findIndex(j => !this.isHeld(j) && !this.heldByLimit(j));
        if (i < 0) break;
        // a paper whose connection failed waits for its second try at the head of the queue
        const wait = (this.queue[i].retryAt || 0) - Date.now();
        if (wait > 0) { await Zotero.Promise.delay(Math.min(wait, 1000)); continue; }
        const job = this.queue[i];
        if (this.discarded(job.att)) { this.queue.splice(i, 1); this.log("left out, in the trash: " + this.keyOf(job.att)); continue; }
        // a queued message takes its conversation as it is now; it stays in the queue meanwhile, so that a stop hands it over
        if (job.qid) {
          job.own = job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
          await this.place(job);
        }
        if (this.stopped) break;
        const at = this.queue.indexOf(job);
        if (at < 0) continue;   // taken out of the queue meanwhile
        this.queue.splice(at, 1);
        let outcome = null;
        try { outcome = await this.run(job); }
        catch (e) {
          const message = String(e && e.message || e).slice(0, 300);
          this.current = null;
          this.dropDraft();
          // nothing of a run that failed before its first line reached the log: its words go back, an annotation's wishes
          // with the words queued for its session to come; the paper's sections show its conversations as their logs have
          // them (no run to retry there), a chat's state line the failure
          const unlogged = !job.logPath;
          if (unlogged) {
            this.handBack(job);
            if (this.transcriptKey === this.keyOf(job.att)) this.transcriptPath = null;
            for (const pane of this.panes.values()) if (pane.keys.includes(this.keyOf(job.att))) { pane.live = false; pane.annot.live = false; }
          } else this.appendEntries(this.entries(await this.logEnd(job.logPath, "failed", message)));
          this.notice(job, `${this.text("failed")} · ${message}`, true);
          this.finish(job, false, message, unlogged && (job.kind || "chat") === "chat" ? `${this.text("failed")} · ${message}` : undefined);
          if (unlogged) for (const pane of [...this.panes.values()]) if (pane.keys.includes(this.keyOf(job.att))) await this.showConversation(pane);
          this.log("run failed: " + e);
          if (!job.logPath) outcome = { ok: false, delivered: false };   // its words reached nothing
        }
        // a queued message that did not reach the agent goes back to the head of its queue, marked, and its queue waits for it
        if (job.qid && outcome && !outcome.delivered && !outcome.cancelled && !outcome.limited && !outcome.retry && !outcome.fresh) {
          job.failed = true;
          job.logged = job.logged || !!job.logPath;
          this.queue.splice(this.backAt(job, this.nextRow(job, 0)), 0, job);
          this.refresh();
          this.settleRun();   // its Retry is on its row
        }
        if (outcome && outcome.limited) this.pause(job, outcome);
        if (outcome && outcome.retry) {
          // the message was sent: what waits for the second try is no queued row
          this.queue.unshift(Object.assign({}, job, { retried: true, retryAt: Date.now() + this.NET_RETRY_MS, qid: null }));
          this.refresh();
          this.settleRun();   // the paper is busy again: no retry button
        }
        if (outcome && outcome.fresh) {
          this.queue.unshift(outcome.fresh);
          this.refresh();
        }
      }
    } finally {
      this.draining = false;
      this.refresh();
    }
  },

  // the usage limit, or a limit of the service: the interrupted paper waits at the head of the queue and continues
  // its conversation when the limit resets; no other run of its agent starts meanwhile, the other agent's go on
  pause(job, { until, session, throttled }) {
    if (this.job && this.job.key === this.keyOf(job.att)) this.job = null;
    // a question stays one when its conversation continues; an annotation that continued a question's conversation
    // has its prompt there. A run after the wait may have its second try again. A queued message that was sent is no row.
    // An edited question's new session goes on as it is; until there is one, the run goes back to the point again
    this.queue.unshift(Object.assign({}, job, { retried: false, retryAt: 0, qid: null },
                                     session ? { resume: session, say: "", extra: "", asked: !!(job.say || job.asked),
                                                 annotate: false, question: false, fresh: false, logged: false,
                                                 throttled: !!throttled, updated: false, rewind: session === job.resume ? job.rewind || null : null }
                                             : { interrupted: true, logged: true }));
    this.settleRun();   // the paper waits: no retry
    const wait = until ? Math.max(until - Date.now(), 0) + 60000 : this.RETRY_MS;
    const agent = this.agentOf(job);
    this.endPause(agent);
    const held = { agent, until: Date.now() + wait, known: !!until, throttled: !!throttled, timer: setTimeout(() => { this.resumeQueue(agent); }, wait) };
    this.paused = Object.assign(this.paused || {}, { [agent]: held });
    const line = this.text(throttled ? "throttledState" : until ? "pausedState" : "pausedRetry", this.clock(held.until), this.agentName(agent));
    this.notice(job, line, true);
    if (!this.focused()) this.notify(this.text(throttled ? "throttleTitle" : "limitTitle", this.agentName(job.agent, true)), line);
    this.refresh();
  },

  // the time a limit's message names ("约 24 分钟后重置", "try again in 24 minutes"), as a moment; null without one
  // or beyond six hours
  resetFrom(text) {
    const s = String(text || "");
    const m = /(\d+(?:\.\d+)?)\s*(分钟|小时)\s*后/.exec(s)
      || /\bin\s+(?:about\s+|~\s*)?(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b/i.exec(s);
    if (!m) return null;
    const ms = Number(m[1]) * (/^(小时|hour|hr)/i.test(m[2]) ? 3600000 : 60000);
    return ms > 0 && ms <= 6 * 3600000 ? Date.now() + ms : null;
  },

  // an agent's runs go on (Continue now, or its reset came); every agent's without one named
  resumeQueue(agent = null) {
    if (!this.paused) return;
    for (const a of agent ? [agent] : Object.keys(this.paused)) this.endPause(a);
    this.refresh();
    if (!this.draining && this.queue.length) this.drain();
  },

  agentOf(job) { return job && job.agent === "codex" ? "codex" : "claude"; },

  // the pause of an agent's runs while its limit holds, or null
  pauseOf(agent) { return (this.paused && this.paused[agent]) || null; },

  endPause(agent) {
    const p = this.pauseOf(agent);
    if (!p) return;
    clearTimeout(p.timer);
    delete this.paused[agent];
    if (!Object.keys(this.paused).length) this.paused = null;
  },

  // the pause a queued run waits for: its agent's, or that of a run of its paper's tab ahead of it, which goes first
  heldByLimit(job) {
    if (!this.paused) return null;
    const own = this.pauseOf(this.agentOf(job));
    if (own) return own;
    const kind = job.kind || "chat";
    for (const j of this.queue) {
      if (j === job) break;
      if (this.keyOf(j.att) === this.keyOf(job.att) && (j.kind || "chat") === kind && !this.isHeld(j) && this.pauseOf(this.agentOf(j))) return this.pauseOf(this.agentOf(j));
    }
    return null;
  },

  // whether a Zotero main window has the focus: a corner notice is for then, the system notification for the rest
  focused() {
    return this.windows().some(win => { try { return win.document.hasFocus(); } catch (e) { return false; } });
  },

  // a short notice in the corner of the window that closes by itself, while Zotero is in front; left out while
  // the paper's Scholium section is on screen, whose state line says the same
  notice(job, text, error = false) {
    if (!this.focused() || this.paneInView(this.keyOf(job.att), job.kind || "chat")) return;
    try {
      const pw = new Zotero.ProgressWindow({ closeOnClick: true });
      pw.changeHeadline(this.text("headline"));
      let icon = null;
      try { if (job.att) icon = job.att.getItemTypeIconName(); } catch (e) {}
      const line = new pw.ItemProgress(icon, job.title);
      if (error) line.setError(); else line.setProgress(100);
      // a description per line: a description shows its text without line breaks. Zotero turns <a …>…</a> in it
      // into a link with the attributes it names; the agent's words are text, so a joiner follows each <
      const joiner = String.fromCharCode(0x2060);
      for (const part of String(text).split("\n")) pw.addDescription(part.replace(/</g, "<" + joiner));
      pw.show();
      pw.startCloseTimer(error ? 2 * this.NOTICE_MS : this.NOTICE_MS);
    } catch (e) { this.log("notice failed: " + e); }
  },

  // record the end of one paper: its section keeps the outcome in short, the transcript has the rest
  finish(job, ok, summary, outcome, detail, answered = false) {
    if (this.job && this.job.key === this.keyOf(job.att)) this.job = null;
    const title = this.text(ok && job.compact ? "compactedTitle" : answered ? "answered" : ok ? "finished" : this.asking(job) ? "failedAsk" : "failedLine", job.title);
    // a chat's outcome is its state line's; an annotation's is its card, and a deletion's note before it goes
    if ((job.kind || "chat") === "chat") {
      this.notes.set(`${this.keyOf(job.att)}/chat`, { text: outcome || this.text(ok ? "done" : "failed"), error: !ok, at: Date.now(),
                                              title: detail || "", conv: job.conv || null });
    } else this.notes.delete(`${this.keyOf(job.att)}/annotate`);
    if (!this.focused() && !job.undone) this.notify(title, ok && !answered ? this.brief(summary) : summary || "");
    this.refresh();
    // the sections of the paper take what its log now says of the conversation; without a log, they draw the run ended
    if (job.logPath) {
      for (const pane of [...this.panes.values()]) {
        if (pane.keys.includes(this.keyOf(job.att))) this.showConversation(pane).catch(e => this.log("section not shown: " + e));
      }
    } else this.settleRun();
  },

  // the run's last line for a notice, a line per part, without the note's title:
  // 高亮 47 条（核心 13 条），页边批注 24 条，笔记《…》，剩余警告：…。 -> 高亮 47 条（核心 13 条）/ 页边批注 24 条 / 剩余警告：…
  // 47 highlights (13 core), 24 margin notes, note “…”, remaining warnings: none -> the same three parts
  brief(summary) {
    return String(summary || "")
      .replace(/(^|[，,；;])\s*[^，,；;。]*笔记[^，,；;。《]*《[^》]*》|(^|[，,；;])\s*(?:the\s+|reading\s+)?note\s*(?:“[^”]*”|"[^"]*"|‘[^’]*’|'[^']*')/gi, "")
      .replace(/[。.]\s*$/, "")
      .split(/\s*[，；;]\s*|,\s+/).map(part => part.trim()).filter(Boolean).slice(0, 4)
      .map(part => (part.length > 40 ? part.slice(0, 39) + "…" : part)).join("\n");
  },

  // the sections of the running paper, each second: their time so far, and the context its session takes up
  async tick(job) {
    while (this.job === job) {
      await Zotero.Promise.delay(this.TICK_MS);
      if (this.job !== job) break;
      const words = this.durationWords(this.elapsed(true));
      for (const pane of this.panes.values()) {
        if (!pane.keys.includes(job.key)) continue;
        try {
          // the line belongs to the tab of the run's kind; the other tab's outcome stays
          if (pane.tab === (job.source.kind || "chat")) {
            pane.state.textContent = this.runningState();
            pane.state.title = this.runningTitle();
          }
          for (const view of this.paneViews(pane)) {
            const t = view.liveTime;
            if (t && t.node.isConnected) t.node.textContent = this.text(t.key || "workingFor", words);
          }
          this.paintRing(pane);
        } catch (e) {}
      }
    }
  },

  // a run that ■ or Esc stopped before its log had the user's words: it ends as cancelled, the words go back to the box and
  // a queued message to the head of its queue, held as the stop holds it; nothing when the plugin stopped meanwhile
  halted(job, running, redraw = false) {
    if (this.job !== running) return;
    const message = this.text("cancelled");
    if (job.qid) {
      this.queue.splice(this.backAt(job, this.nextRow(job, 0)), 0, job);
      this.heldQueues.add(this.queueKey(job));
    } else if (!job.undone) this.handBack(job, redraw);
    this.appendEntries([{ kind: "final", text: message, error: true, cancelled: true }]);
    if (!job.undone) this.notice(job, message, true);
    this.finish(job, false, message, this.outcome(null, true));
    return { ok: false, delivered: false, cancelled: true };
  },

  // the words a job's run line gives its turn: the user's, or the annotation's request with its extra wishes
  turnWords(job) { return job.say || this.annotateWords(job); },

  annotateWords(job) { return this.text("annotateThis") + (job.extra ? "\n" + this.text("extraLabel") + job.extra : ""); },

  // the old turns a job's words left behind (leftAt): a list, or the one index an earlier copy kept
  leftOf(at) { return (Array.isArray(at) ? at : [at]).filter(i => Number.isInteger(i)); },
});
