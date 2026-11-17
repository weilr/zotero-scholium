// ScholiumRunner, continued: starting runs, the pauses for usage limits, and the end of a run

Object.assign(ScholiumRunner, {
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
      await this.appendLog({ logPath: path }, [JSON.stringify(marks[1])]);
      const kept = this.lastEntries.get(path);   // the run that waited, as it was shown: with its end
      if (kept) this.addEntries(kept, marks.flatMap(m => this.entries(m)));
    }
    this.refresh();
    for (const pane of [...this.panes.values()]) if (pane.keys.includes(key)) await this.showConversation(pane);
  },

  // the runs going on at once: the settings' number, 1 to 6
  maxRuns() {
    const n = Number(this.getPref("maxRuns"));
    return Number.isInteger(n) && n >= 1 && n <= 6 ? n : this.MAX_RUNS_DEFAULT;
  },

  // whether a queued job may start now: not held (Resume, a failed message before it, a usage limit of its agent), not
  // waiting for its second try, not already starting; nothing of its conversation going on or queued before it, and no
  // other annotation of its paper going on or queued before it
  mayStart(job) {
    if (this.active.has(job) || this.isHeld(job) || this.heldByLimit(job) || (job.retryAt || 0) > Date.now()) return false;
    const key = this.keyOf(job.att), kind = job.kind || "chat", conv = job.conv || null;
    const blocks = j => {
      if (this.keyOf(j.att) !== key) return false;
      const k = j.kind || "chat";
      return (k === kind && (j.conv || null) === conv) || (kind === "annotate" && k === "annotate");
    };
    for (const a of this.active) if (blocks(a)) return false;
    // a held message (Resume, a usage limit) holds its own conversation only
    for (const q of this.queue) { if (q === job) break; if (!this.isHeld(q) && !this.heldByLimit(q) && blocks(q)) return false; }
    return true;
  },

  // every queued job that may start starts, in the queue's order, until as many run as the settings allow; one waiting
  // for its second try starts when its time comes. An agent's usage limit holds that agent's jobs only
  pump() {
    if (this.pumpHeld || this.stopped) return;
    for (const job of [...this.queue]) {
      if (this.active.size >= this.maxRuns()) break;
      if (!this.queue.includes(job)) continue;
      if (this.discarded(job.att)) { this.queue.splice(this.queue.indexOf(job), 1); this.log("left out, in the trash: " + this.keyOf(job.att)); continue; }
      if (!this.mayStart(job)) continue;
      this.startRun(job).catch(e => this.log("run not handled: " + e));
    }
    // a job waiting for its second try: the queue is looked at again within a second
    const next = Math.min(...this.queue.map(j => j.retryAt || Infinity));
    if (next < Infinity && !this.retryWait) {
      this.retryWait = true;
      Zotero.Promise.delay(Math.min(Math.max(next - Date.now(), 0), 1000)).then(() => { this.retryWait = false; this.pump(); });
    }
    this.refresh();
  },

  // one queued job's run and what follows it: a queued message takes its conversation as it is now, staying in the queue
  // meanwhile so that a stop hands it over; the job counts as going on (active) until its outcome is handled
  async startRun(job) {
    this.active.add(job);
    try {
      if (job.qid) {
        job.own = job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
        await this.place(job);
      }
      if (this.stopped) return;
      const at = this.queue.indexOf(job);
      if (at < 0) return;   // taken out of the queue meanwhile
      this.queue.splice(at, 1);
      let outcome = null;
      try { outcome = await this.run(job); }
      catch (e) {
        const message = String(e && e.message || e).slice(0, 300);
        const run = this.runOfJob(job);
        if (run) this.dropDraft(run);
        // nothing of a run that failed before its first line reached the log: its words go back, an annotation's wishes
        // with the words queued for its session to come; the paper's sections show its conversations as their logs have
        // them (no run to retry there), a chat's state line the failure
        const unlogged = !job.logPath;
        if (unlogged) {
          this.handBack(job);
          for (const pane of this.panes.values()) if (pane.keys.includes(this.keyOf(job.att))) this.viewOf(pane, job.kind || "chat").live = false;
        } else if (run) this.appendEntries(run, this.entries(await this.logEnd(job.logPath, "failed", message)));
        this.notice(job, `${this.text("failed")} · ${message}`, true);
        this.finish(job, false, message, unlogged && (job.kind || "chat") === "chat" ? `${this.text("failed")} · ${message}` : undefined);
        if (unlogged && run && run.path) this.lastEntries.delete(run.path);   // its log has nothing of it: its run is not shown
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
        this.settleRun(this.tabOf(job));   // its Retry is on its row
      }
      if (outcome && outcome.limited) this.pause(job, outcome);
      if (outcome && outcome.retry) {
        // the message was sent: what waits for the second try is no queued row
        this.queue.unshift(Object.assign({}, job, { retried: true, retryAt: Date.now() + this.NET_RETRY_MS, qid: null }));
        this.refresh();
        this.settleRun(this.tabOf(job));   // the paper is busy again: no retry button
      }
      if (outcome && outcome.fresh) {
        this.queue.unshift(outcome.fresh);
        this.refresh();
      }
    } finally {
      this.active.delete(job);
      this.pump();
    }
  },

  // the usage limit, or a limit of the service: the interrupted paper waits at the head of the queue and continues
  // its conversation when the limit resets; no other run of its agent starts meanwhile, the other agent's go on
  pause(job, { until, session, throttled }) {
    this.endRun(this.runOfJob(job));
    // a question stays one when its conversation continues; an annotation that continued a question's conversation
    // has its prompt there. A run after the wait may have its second try again. A queued message that was sent is no row.
    // An edited question's new session goes on as it is; until there is one, the run goes back to the point again
    this.queue.unshift(Object.assign({}, job, { retried: false, retryAt: 0, qid: null },
                                     session ? { resume: session, say: "", extra: "", asked: !!(job.say || job.asked),
                                                 annotate: false, question: false, fresh: false, logged: false,
                                                 throttled: !!throttled, updated: false, rewind: session === job.resume ? job.rewind || null : null }
                                             : { interrupted: true, logged: true }));
    this.settleRun(this.tabOf(job));   // the paper waits: no retry
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
    this.pump();
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
    this.endRun(this.runOfJob(job));
    const title = this.text(ok && job.compact ? "compactedTitle" : answered ? "answered" : ok ? "finished" : this.asking(job) ? "failedAsk" : "failedLine", job.title);
    // a chat's outcome is its state line's; an annotation's is its card, and a deletion's note before it goes
    if ((job.kind || "chat") === "chat") {
      this.notes.set(`${this.keyOf(job.att)}/chat`, { text: outcome || this.text(ok ? "done" : "failed"), error: !ok, at: Date.now(),
                                              title: detail || "", conv: job.conv || null });
    } else if (job.logPending) this.notes.set(`${this.keyOf(job.att)}/annotate`, {
      text: outcome, error: true, at: Date.now(), conv: job.conv || null, pendingLog: job.logPath });
    else this.notes.delete(`${this.keyOf(job.att)}/annotate`);
    if (!this.focused() && !job.undone) this.notify(title, ok && !answered ? this.brief(summary) : summary || "");
    this.refresh();
    // the sections of the paper take what its log now says of the conversation; without a log, they draw the run ended
    if (job.logPath && !job.logPending) {
      for (const pane of [...this.panes.values()]) {
        if (pane.keys.includes(this.keyOf(job.att))) this.showConversation(pane).catch(e => this.log("section not shown: " + e));
      }
    } else this.settleRun(this.tabOf(job));
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
  async tick(run) {
    while (this.alive(run)) {
      await Zotero.Promise.delay(this.TICK_MS);
      if (!this.alive(run)) break;
      const words = this.durationWords(this.elapsed(run, true));
      for (const pane of this.panes.values()) {
        if (!pane.keys.includes(run.key)) continue;
        try {
          // the line belongs to the tab that shows the run's conversation; the other tab's outcome stays
          if (this.runOfView(this.viewOf(pane, pane.tab)) === run) {
            pane.state.textContent = this.runningState(run);
            pane.state.title = this.runningTitle(run);
          }
          for (const view of this.paneViews(pane)) {
            if (this.runOfView(view) !== run) continue;
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
    if (!this.alive(running)) return;
    const message = this.text("cancelled");
    if (job.qid) {
      this.queue.splice(this.backAt(job, this.nextRow(job, 0)), 0, job);
      this.heldQueues.add(this.queueKey(job));
    } else if (!job.undone) this.handBack(job, redraw);
    this.appendEntries(running, [{ kind: "final", text: message, error: true, cancelled: true }]);
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
