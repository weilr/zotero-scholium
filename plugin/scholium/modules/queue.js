// ScholiumRunner, continued: Annotate, sending, the runs of a paper and a conversation, and the queue

Object.assign(ScholiumRunner, {
  async annotate(items, { extra = "", confirmed = false, replace = false, agent = this.agent(), queueConsent = null } = {}) {
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
    const queues = jobs.map(j => (queueConsent && queueConsent[this.keyOf(j.att)]) || this.annotationQueueSnapshot(this.keyOf(j.att), agent));
    const queued = queues.reduce((n, rows) => n + rows.length, 0);
    if ((total && !confirmed) || (queued && !queueConsent)) {
      const shared = replaced.some(a => this.groupOf(a.libraryID));
      const question = [queued ? this.text("redoQueued", queued) : "", total ? this.text("redo", total, this.clearedNotes(replaced).length, shared) : ""].filter(Boolean).join(" ");
      if (!Services.prompt.confirm(win, this.text("redoTitle"), question)) return 0;
      replace = true;
    }
    for (const [i, j] of jobs.entries()) {
      Object.assign(j, { own: own[i], extra, agent, annotate: true, asking: false, kind: "annotate", annotationQueue: { rows: queues[i] } });
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
    const kind = opts.kind === "annotate" ? "annotate" : "chat", confirmation = opts.confirmation || null;
    const validConfirmation = () => !confirmation || (this.heldConfirmationCurrent(confirmation)
      && confirmation.held.confirmation === confirmation && !confirmation.job && confirmation.key === this.keyOf(job.att)
      && confirmation.conv === opts.conv && confirmation.kind === kind);
    if (!validConfirmation()) return false;
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
                         edited: !!opts.edited, confirmation,
                         // Only a pane action carries confirmation; its sequence must be after the report.
                         sentSeq: opts.retry || opts.edited || opts.compact ? 0 : ++this.sendSeq },
                  // the other papers of a chat's message; without them, a run takes those its conversation's log names
                  kind === "chat" && Array.isArray(opts.papers) ? { papers: opts.papers } : {});
    // the paper is busy: the words wait in the queue of the conversation, as Codex queues a follow-up
    if (busy) {
      Object.assign(job, { qid: String(++this.qseq), conv: opts.conv || null });
      if (kind === "annotate" && job.conv) job.agent = this.convAgent(job.conv);   // an annotation session's, from now on
      if (confirmation) confirmation.job = job;
      else if (job.conv) this.heldBack.delete(`${this.keyOf(job.att)}/${job.conv}`);
      this.queue.splice(this.followUpAt(job), 0, job);
      this.refresh();
      this.pump();   // another conversation of the paper may start now; its own waits for the run that goes on
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
    if (!validConfirmation() || (confirmation && job.conv !== confirmation.conv)) return false;
    if (job.compact && !job.resume) return false;
    if (this.busy(this.keyOf(job.att), kind)) return false;
    // ahead of a held queue it is sent past (Send message), else where a conversation's message goes
    const ahead = opts.before ? this.queue.indexOf(opts.before) : -1;
    if (confirmation) confirmation.job = job;   // accepted: later view changes do not revoke this job's exact report
    else if (!opts.retry && !opts.compact && job.conv) this.heldBack.delete(`${this.keyOf(job.att)}/${job.conv}`);
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
    return [...this.active].some(j => this.keyOf(j.att) === key && of(j)) || this.paperRuns(key).some(r => !kind || r.kind === kind)
      || this.queue.some(j => this.keyOf(j.att) === key && of(j) && !this.isHeld(j));
  },

  // the run of a job going on, and the paper and tab a job is of
  runOfJob(job) { for (const r of this.runs.values()) if (r.source === job) return r; return null; },
  tabOf(job) { return { key: this.keyOf(job.att), kind: job.kind || "chat" }; },

  // whether a run still goes on: not ended, not dropped by a stop
  alive(run) { return !!run && !run.gone && this.runs.get(run.id) === run; },

  // the run going on of a conversation: a paper's key, its tab's kind and the conversation's id; null as the id is the tab's
  // new conversation, whose run has no id for it yet
  runOfConv(key, kind = "chat", conv = null) {
    for (const r of this.runs.values()) if (!r.gone && r.key === key && r.kind === kind && (r.conv || null) === (conv || null)) return r;
    return null;
  },

  // the run of the conversation a view shows
  runOfView(view) {
    return view && view.shownKey ? this.runOfConv(view.shownKey, view.kind || "chat", view.shownConv || null) : null;
  },

  // the runs of a paper going on
  paperRuns(key) { return [...this.runs.values()].filter(r => !r.gone && r.key === key); },

  // a run ends: it no longer goes on, its draft goes with it
  endRun(run) {
    if (!run) return;
    if (!run.gone && run.path) {
      this.lastEntries.delete(run.path);
      this.lastEntries.set(run.path, run.entries);
      if (this.lastEntries.size > 20) this.lastEntries.delete(this.lastEntries.keys().next().value);
    }
    if (!run.gone) this.lastRun = run;
    run.gone = true;
    clearTimeout(run.draftTimer);
    run.draftTimer = null;
    if (this.runs.get(run.id) === run) this.runs.delete(run.id);
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

  // An agent's earlier annotation sessions have no history entry; count even rows whose removal can still be undone.
  annotationQueued(key, agent) {
    return this.queue.concat([...this.removedQueued.values()].map(r => r.job)).filter(j => j.qid && j.kind === "annotate"
      && j.conv && this.keyOf(j.att) === key && this.convAgent(j.conv) === agent);
  },

  annotationQueueSnapshot(key, agent) {
    return this.annotationQueued(key, agent).map(j => ({ qid: j.qid, conv: j.conv, say: j.say, removed: this.removedQueued.has(j.qid) }));
  },

  // Only the messages shown in the confirmation can be discarded; expired removal Undo rows may disappear meanwhile.
  checkedAnnotationQueue(job, key) {
    const old = this.annotationQueued(key, job.agent).filter(j => j.conv !== job.conv);
    const rows = job.annotationQueue && job.annotationQueue.rows;
    if (old.some(j => !Array.isArray(rows) || !rows.some(r => r && r.qid === j.qid && r.conv === j.conv && r.say === j.say
      && r.removed === this.removedQueued.has(j.qid)))) {
      const message = this.text("annotationQueueChanged");
      for (const pane of this.panes.values()) if (pane.keys.includes(key)) this.sayUnderBox(pane, message);
      throw new Error(message);
    }
    return old;
  },

  // Once the new session's first line is saved, the confirmed old queues can no longer be resumed.
  discardAnnotationQueued(job, key) {
    const old = new Set(this.checkedAnnotationQueue(job, key));
    this.queue = this.queue.filter(j => !old.has(j));
    for (const [qid, r] of this.removedQueued) {
      if (!old.has(r.job)) continue;
      clearTimeout(r.timer);
      this.removedQueued.delete(qid);
    }
    this.tidyHeld();
    delete job.annotationQueue;
  },

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
    this.pump();
  },

  undoRemoveQueued(qid) {
    const r = this.removedQueued.get(qid);
    if (!r) return;
    clearTimeout(r.timer);
    this.removedQueued.delete(qid);
    this.queue.splice(this.backAt(r.job, r.next), 0, r.job);
    this.refresh();
    this.pump();
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
    this.pump();
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
    this.pump();
  },

  // Resume: the held queue goes on
  releaseQueue(job) {
    this.heldQueues.delete(this.queueKey(job));
    this.refresh();
    this.pump();
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
    this.pump();
  },

  // take papers out of the queue, their runs of one kind only when given, and their queued messages unless `rows` is
  // false; an agent's pause ends once nothing but held messages is left of its runs. A message that had not started
  // goes back to its box, an annotation's wishes too, with the messages queued for its session to come (which leave the
  // queue with it); an edited question that had not started is undone
  dequeue(keys, kind = null, { rows = true, conv } = {}) {
    // conv: of that conversation only, and what has none yet
    const ours = j => keys.includes(this.keyOf(j.att)) && (!kind || (j.kind || "chat") === kind) && (rows || !j.qid)
      && (conv === undefined || !j.conv || j.conv === conv);
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
});
