// ScholiumRunner, continued: the runner's start, hand-over and stop

Object.assign(ScholiumRunner, {
  // `update`: this copy may replace another (an update or a downgrade), which may hand papers over (carryOver); at
  // Zotero's start a hand-over that no copy took is dropped
  start(pluginID, update = false) {
    this.pluginID = pluginID;
    this.stopped = false;
    // Zotero keeps this recovery queue while a plugin copy is disabled or replaced.
    this.pendingLogs = Zotero.ScholiumPendingLogs || this.pendingLogs;
    Zotero.ScholiumPendingLogs = this.pendingLogs;
    Zotero.ScholiumLogWriter = this;
    for (const [path, pending] of this.pendingLogs) {
      const r = pending.restore;
      if (r) {
        this.replaced.set(`${r.key}/${r.conv}`, r);
        this.notes.set(`${r.key}/chat`, { text: this.text("undoNotRestored"), error: true, at: Date.now(), conv: r.conv });
      } else if (pending.completed) {
        const done = pending.completed;
        this.notes.set(`${done.key}/${done.kind}`, { text: this.text("logNotSaved"), error: true, at: Date.now(), conv: done.conv,
          pendingLog: path });
      }
    }
    this.startFolders();
    if (this.pendingLogs.size) this.scheduleLogRetry();
    // more runs at once allowed in the settings: what waits starts
    try { this.maxRunsObserver = Zotero.Prefs.registerObserver(this.pref + "maxRuns", () => this.pump(), true); }
    catch (e) { this.log("settings not observed: " + e); }
    this.registerPane(pluginID);
    try {
      // a handler left registered (see unregisterReaderListener) does nothing once this copy stopped
      const handler = this.menuHandler = event => { if (this.menuHandler === handler) this.contextMenuItem(event); };
      Zotero.Reader.registerEventListener("createViewContextMenu", this.menuHandler, pluginID);
    } catch (e) { this.log("context menu not registered: " + e); }
    // the Scholium page of Zotero's settings; Zotero removes it when the plugin stops
    if (Zotero.PreferencePanes && this.rootURI) {
      Zotero.PreferencePanes.register({ pluginID, src: this.rootURI + "settings.xhtml", label: "Scholium",
                                        image: this.chrome + "icon20.svg", scripts: [this.rootURI + "settings.js"] })
        .then(id => { this.prefPaneID = id; }, e => this.log("settings page not registered: " + e));
    }
    // the settings page asks what the plugin finds by itself, for the grey text of the program boxes, and runs the setup check
    this.settingsApi = { found: agent => this.foundProgram(agent), setupCheck: onLine => this.setupCheck(onLine), fix: action => this.setupFix(action),
                         copy: lines => this.copySetup(lines) };
    Zotero.Scholium = this.settingsApi;
    for (const win of this.windows()) this.addToWindow(win);
    if (!update) {
      if (this.getPref("carryOver")) { try { Zotero.Prefs.set(this.pref + "carryOver", "", true); } catch (e) {} }
      return;
    }
    // Zotero's handlers for an update do not wait for each other: the copy it replaces may stop after this one
    // started, so its papers are looked for again a moment later
    this.restoreQueue().catch(e => this.log("queue not restored: " + e));
    this.restoreTimer = setTimeout(() => { this.restoreQueue().catch(e => this.log("queue not restored: " + e)); }, 5000);
  },

  // the papers still to do when an update replaces this copy, the running one first, as a preference that the new
  // copy reads when it starts (restoreQueue): the running paper continues its conversation, the others start; a pause
  // for a limit and a wait for a second try go on
  carryOver(runs) {
    const plain = j => ({ key: j.att.key, libraryID: j.att.libraryID, agent: j.agent, extra: j.extra || "", say: j.say || "",
                          resume: j.resume || null, asked: !!j.asked, question: !!j.question, annotate: !!j.annotate, own: j.own || 0,
                          interrupted: !!j.interrupted, updated: !!j.updated, fresh: !!j.fresh, conv: j.conv || null, asking: !!j.asking,
                          logged: !!j.logged, throttled: !!j.throttled, retried: !!j.retried, retryAt: j.retryAt || 0, kind: j.kind || "chat",
                          compact: !!j.compact, qid: j.qid || null, failed: !!j.failed, quote: j.quote || null, rewind: j.rewind || null,
                          turnAt: Number.isInteger(j.turnAt) ? j.turnAt : null, leftAt: this.leftOf(j.leftAt),
                          papers: Array.isArray(j.papers) ? j.papers : null, annotationQueue: j.annotationQueue || null });
    const jobs = [];
    for (const running of [].concat(runs || [])) {
      if (!running || !running.source) continue;
      const j = running.source;
      // once the agent has answered to the prompt the conversation holds it, and the paper continues there (a queued
      // message that was sent, too: no row); before that the paper is handed over as it was queued, the user's words with
      // it. A compaction is handed over as one, with its focus: the new copy compacts again. An edited question goes back
      // to its point until the agent made a new session of it
      jobs.push(running.session && running.delivered && !j.compact
        ? Object.assign(plain(j), { resume: running.session, say: "", extra: "", asked: !!(j.say || j.asked), annotate: false, compact: false,
                                    question: false, fresh: false, logged: false, throttled: false, retried: false, retryAt: 0,
                                    updated: true, qid: null, rewind: running.session === j.resume ? j.rewind || null : null })
        : Object.assign(plain(j), { logged: !!(j.logged || running.logged) }));
    }
    for (const j of this.queue) jobs.push(plain(j));
    // a job between the queue and its run (it waits for the folders or its log to be written): as it was queued
    const going = new Set([].concat(runs || []).map(r => r && r.source));
    for (const j of this.active || []) if (!going.has(j) && !this.queue.includes(j) && !j.ended) jobs.push(plain(j));
    // each agent's pause: { <agent>: { until, known, throttled } }
    const paused = this.paused ? Object.fromEntries(Object.entries(this.paused).map(([a, p]) => [a, { until: p.until, known: p.known, throttled: !!p.throttled }])) : null;
    try { if (jobs.length) Zotero.Prefs.set(this.pref + "carryOver", JSON.stringify({ jobs, paused, held: [...this.heldQueues] }), true); }
    catch (e) { this.log("queue not kept: " + e); }
  },

  // the papers an update interrupted (carryOver), queued again once
  async restoreQueue() {
    await this.settled();
    if (this.stopped) return;   // a copy stopped while it waited: what was handed over stays for the next one
    const raw = this.getPref("carryOver");
    if (!raw) return;
    try { Zotero.Prefs.set(this.pref + "carryOver", "", true); } catch (e) {}
    let saved = null;
    try { saved = JSON.parse(raw); } catch (e) { return; }
    const jobs = [];
    for (const s of (saved && Array.isArray(saved.jobs) && saved.jobs) || []) {
      const att = s && Zotero.Items.getByLibraryAndKey(s.libraryID, s.key);
      const job = att ? await this.resolve(att) : null;
      // a paper's chat and its annotation are handed over each, with the messages queued behind them
      const kind = s && s.kind === "annotate" ? "annotate" : "chat";
      const qid = s && typeof s.qid === "string" && s.qid ? s.qid : null;
      const conv = s && typeof s.conv === "string" && s.conv ? s.conv : null;   // each conversation's run is handed over
      // its conversation busy here already, as busy() tells a paper's: starting, running or queued (a paper's annotation:
      // any of its annotations)
      const key = job && this.keyOf(job.att);
      const mine = (k, c) => (k || "chat") === kind && (kind === "annotate" || (c || null) === conv);
      const going = job && ([...this.active].some(j => this.keyOf(j.att) === key && mine(j.kind, j.conv))
                            || this.paperRuns(key).some(r => mine(r.kind, r.conv))
                            || this.queue.some(j => this.keyOf(j.att) === key && mine(j.kind, j.conv) && !this.isHeld(j)));
      if (!job || (!qid && (going
                            || jobs.some(j => !j.qid && this.keyOf(j.att) === this.keyOf(job.att) && j.kind === kind && (j.conv || null) === conv)))) continue;
      const agent = s.agent === "codex" ? "codex" : "claude";
      Object.assign(job, { agent, extra: String(s.extra || ""), say: String(s.say || ""), resume: s.resume || null, asked: !!s.asked,
                           question: !!s.question, annotate: !!s.annotate, own: Number(s.own) || 0, updated: !!s.updated, fresh: !!s.fresh,
                           conv: typeof s.conv === "string" && s.conv ? s.conv : null, asking: !!(s.asking || s.question),
                           logged: !!s.logged, interrupted: !!s.interrupted, throttled: !!s.throttled, retried: !!s.retried,
                           retryAt: Number(s.retryAt) || 0, kind, compact: !!s.compact, qid, failed: !!(qid && s.failed),
                            quote: this.quoteOf(s.quote), rewind: this.pointOf(s.rewind),
                            annotationQueue: s.annotationQueue && typeof s.annotationQueue === "object" ? s.annotationQueue : null,
                           turnAt: Number.isInteger(s.turnAt) ? s.turnAt : null, leftAt: this.leftOf(s.leftAt) },
                    Array.isArray(s.papers) ? { papers: s.papers.filter(r => r && typeof r.key === "string" && r.key) } : {});
      if (qid) this.qseq = Math.max(this.qseq, Number(qid) || 0);
      // a copy before the paper's conversations hands over its one conversation per agent, which became that agent's
      // first: a paper interrupted there has its turn in that log; an annotation not begun starts a session of its own
      if (!("conv" in s)) {
        if (!job.say && !job.resume) job.annotate = true;
        // a question that goes on is the conversation's already; words whose run had begun are the last turn of its log,
        // asked again there
        if (job.resume) job.question = false;
        const legacy = job.say ? await this.readLog(this.keyOf(job.att), this.LEGACY[agent]) : null;
        const last = legacy && legacy.turns[legacy.turns.length - 1];
        const begun = !!last && !last.done && last.user === job.say;
        if (job.resume || job.interrupted || job.retried || begun) job.conv = this.LEGACY[agent];
        else {
          if (job.annotate) job.kind = "annotate";
          await this.place(job);
        }
        if (job.interrupted || begun) job.logged = true;
        if (begun) job.turnAt = legacy.turns.length - 1;
        // that copy kept neither of these for a follow-up
        job.own = job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
        const log = await this.readLog(this.keyOf(job.att), job.conv);
        if (!job.annotate) job.asking = !!(job.question || (log && log.question));
      }
      jobs.push(job);
    }
    if (!jobs.length) return;
    for (const k of (Array.isArray(saved.held) && saved.held) || []) if (typeof k === "string") this.heldQueues.add(k);
    // a limit that still holds: its agent's runs wait for it, as before the update. An earlier copy's one pause held the
    // queue behind the paper the limit interrupted, at its head: it is that paper's agent's (should another paper's run be
    // at the head, its agent waits for that reset instead, as the whole queue did before)
    const p = saved.paused && typeof saved.paused === "object" ? saved.paused : {};
    const head = (Array.isArray(saved.jobs) && saved.jobs[0]) || {};
    const pauses = "until" in p ? { [this.agentOf(head)]: p } : p;
    for (const agent of this.AGENTS) {
      const q = pauses[agent];
      if (!q || !(q.until > Date.now()) || this.pauseOf(agent)) continue;
      this.paused = Object.assign(this.paused || {}, { [agent]: { agent, until: q.until, known: !!q.known, throttled: !!q.throttled,
                                                                  timer: setTimeout(() => { this.resumeQueue(agent); }, q.until - Date.now()) } });
    }
    this.enqueue(jobs);
  },

  // `update`: an update or a downgrade replaces this copy, which hands the papers still to do over to the new one.
  // The running paper's log records that its run was interrupted.
  stop(update = false) {
    this.stopped = true;
    if (Zotero.ScholiumLogWriter === this) delete Zotero.ScholiumLogWriter;
    const running = [...this.runs.values()].filter(r => !r.gone);
    for (const r of running) {
      if (!r.log) continue;
      const mark = { type: "scholium", subtype: "end", outcome: "interrupted", text: this.text("interruptedLine"),
                     duration_ms: Date.now() - r.started };
      this.appendLog({ logPath: r.log }, [JSON.stringify(mark)]).catch(() => {});
    }
    clearTimeout(this.logRetryTimer);
    this.logRetryTimer = null;
    this.retryLogs().catch(e => this.log("logs not saved while stopping: " + e));
    // a conversation deleted a moment ago goes now, as it would have, its queued messages first: they are not handed over
    for (const path of [...this.deleting.keys()]) this.finishDelete(path).catch(() => {});
    if (update) this.carryOver(running);
    clearTimeout(this.restoreTimer);
    clearTimeout(this.migrateRetry);
    this.migrateRetry = null;
    if (this.maxRunsObserver) {
      try { Zotero.Prefs.unregisterObserver(this.maxRunsObserver); } catch (e) {}
      this.maxRunsObserver = null;
    }
    if (this.migrateDone) this.migrateDone();   // what waits for the second try goes on, to find the plugin stopped
    if (this.editor) this.closeProfile(this.editor, false);
    for (const agent of this.AGENTS) this.endPause(agent);
    this.paused = null;
    this.queue = [];
    for (const r of this.removedQueued.values()) clearTimeout(r.timer);
    this.removedQueued.clear();
    // an edit's old conversation can no longer come back: the threads only it used are archived
    for (const r of this.replaced.values()) {
      clearTimeout(r.timer);
      if (r.failed || r.restoring) continue;
      try { this.archiveReplaced(r); } catch (e) {}
    }
    this.replaced.clear();
    if (this.savedRemoved) clearTimeout(this.savedRemoved.timer);
    this.savedRemoved = null;
    this.heldQueues.clear();
    this.qseq = 0;
    this.heldBack.clear();   // a confirmation is the next message's to this copy
    this.cancel();
    for (const r of running) {
      try { if (r.current) r.current.proc.kill(); } catch (e) {}   // without waiting for Codex to end its turn
      this.endRun(r);
    }
    this.katexLib = undefined;
    this.i18n = {};
    this.mathCache.clear();
    this.citations.clear();
    try { if (this.codexRefresh) this.codexRefresh.close(); } catch (e) {}
    this.unsent.clear();
    for (const win of this.windows()) this.removeFromWindow(win);
    try { if (this.paneID) Zotero.ItemPaneManager.unregisterSection(this.paneID); } catch (e) {}
    // Zotero takes a section's button out of the reader's sidenav only through an open reader's item pane: once the reader
    // tabs are closed it stays there, hidden, and comes back with its old icon. The sidenav's own removePane takes it away
    for (const win of this.windows()) {
      try {
        const nav = this.paneID && win.document.getElementById("zotero-context-pane-sidenav");
        if (nav && typeof nav.removePane === "function") nav.removePane(this.paneID);
      } catch (e) {}
    }
    this.paneID = null;
    unregisterReaderListener("createViewContextMenu", this.menuHandler);
    this.menuHandler = null;
    this.pendingQuotes.clear();
    this.pendingPapers.clear();
    this.prefPaneID = null;
    if (Zotero.Scholium === this.settingsApi) delete Zotero.Scholium;   // a newer copy's stays
    this.settingsApi = null;
    for (const body of [...this.panes.keys()]) this.dropPane(body);
    this.notes.clear();
    this.runs.clear();
    this.active.clear();
  },
});
