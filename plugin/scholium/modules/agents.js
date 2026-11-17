// ScholiumRunner, continued: a run and its log, Claude Code, and cancelling

Object.assign(ScholiumRunner, {
  async run(job) {
    const logRun = job.logRun = { done: false };
    try { return await this.runJob(job); }
    finally { logRun.done = true; }
  },

  async runJob(job) {
    await this.settled();
    const started = Date.now();
    const key = this.keyOf(job.att);
    if (job.conv) {
      const replaced = this.replaced.get(`${key}/${job.conv}`);
      if (replaced && (replaced.restoring || replaced.failed)) throw new Error(this.text("undoNotRestored"));
      const path = this.convPath(key, job.conv);
      await this.flushLog(path);
      if (this.pendingLogs.has(path)) throw new Error(this.text("logNotSaved"));
    }
    const agent = job.agent === "codex" ? "codex" : "claude";
    const running = { id: "r" + (++this.runSeq), title: job.title, key, libraryID: job.att.libraryID, started, elapsed: 0, agent,
                      step: job.resume && !job.annotate ? "continuing" : "starting", source: job, session: job.resume || null, log: null,
                      asking: this.asking(job), context: null, kind: job.kind || "chat", conv: job.conv || null, entries: [], path: null,
                      current: null, draft: null, draftTimer: null };
    this.runs.set(running.id, running);
    // the conversation goes on in its log; a new one starts its own when the run is under way
    const log = job.conv ? await this.readLog(key, job.conv) : null;
    const mine = log ? log.agents[agent] : null;   // the agent's own session of the conversation
    // a new session of the conversation is given its turns, a session that goes on the turns after the last one it saw. A
    // second try, a new session after a gone one, and a message handed back before it reached the agent have their turn in
    // the log already, which is their message
    const continuation = !!job.resume && !job.say && !job.annotate;
    // words logged before whose turn is no longer the log's last (a newer message went first), or whose turn now holds
    // other words (an edit cut the log): they are asked again as a new turn at the end, so that the log keeps its order.
    // Each old turn of these words (leftAt) stays in the log but is not given to the agent, in its history or its missed
    // turns, as its words come in the message; every copy of the job keeps them. An index that no longer points at these
    // words leaves nothing out. A turn is theirs when it starts with the words its run line wrote
    const words = this.turnWords(job);
    const own = i => {
      const t = Number.isInteger(i) && log ? log.turns[i] : null;
      const user = t ? String(t.user || "") : null;
      return user !== null && (user === words || user.startsWith(words + "\n\n"));   // words steered into it come after
    };
    if (log && !continuation && (job.logged || job.retried) && Number.isInteger(job.turnAt)
        && (job.turnAt !== log.turns.length - 1 || !own(job.turnAt))) {
      const lefts = this.leftOf(job.leftAt);
      job.leftAt = own(job.turnAt) && !lefts.includes(job.turnAt) ? lefts.concat(job.turnAt) : lefts;
      Object.assign(job, { logged: false, retried: false, fresh: false });
    }
    const again = !!(job.retried || job.fresh || job.logged) && !continuation;
    let before = log ? (again ? log.turns.slice(0, -1) : log.turns) : [];
    const left = this.leftOf(job.leftAt).filter(i => own(i) && i < before.length);
    if (left.length) before = before.map((t, i) => Object.assign({}, t, { n: i + 1 }));   // the others keep their numbers
    // from the turn after the last one its session saw, or from the first one it saw that another agent answered again
    job.missedFrom = mine ? Math.min(mine.through + 1, Number.isInteger(mine.stale) ? mine.stale : Infinity) : 0;
    job.missed = job.resume && !continuation && !job.compact ? before.slice(job.missedFrom) : [];
    job.history = log && !job.resume ? before : [];
    if (left.length) {
      job.missed = job.missed.filter(t => !left.includes(t.n - 1));
      job.history = job.history.filter(t => !left.includes(t.n - 1));
    }
    job.since = mine ? mine.lastAt : 0;
    job.sinceEnd = mine ? mine.lastEnd : 0;
    job.applied = await this.readApplied(key);
    if (!this.alive(running)) return;   // the plugin stopped meanwhile
    // the run is one of the transcript's from its start; its line goes into the log once the log is there. One that goes
    // on with the turn before is an annotation's when that turn is: its state line counts the steps its list names
    running.entries = (log ? log.entries : []).concat(this.entries({ type: "scholium", subtype: "run", at: started, compact: !!job.compact,
                                                                                       user: job.compact || again || continuation ? null : "" }));
    const runs = this.runsOf(running.entries), turn = runs[runs.length - 1].turn;
    running.annotation = !!job.annotate || !!(turn && turn.annotate);
    running.path = log ? log.path : null;
    running.context = mine ? mine.context : null;
    // another run of a conversation whose question was edited a moment ago: the edit can no longer be undone
    if (!job.edited && job.conv) this.endReplaced(`${key}/${job.conv}`);
    this.startPanes(running);
    this.notice(job, this.text(job.compact ? "compacting" : job.annotate || (!job.say && !job.resume) ? "typical" : job.question ? "askNotice" : "continuedNotice"));
    this.refresh();
    this.tick(running).catch(() => {});
    if (running.stopAsked) return this.halted(job, running);   // ■ while the log was read
    const program = agent === "codex" ? await this.findCodex() : await this.findClaude();
    if (!this.alive(running) || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, while the program was looked up
    if (!program) {
      const missing = this.text(agent === "codex" ? "noCodex" : "noClaude");
      this.handBack(job, false);
      this.appendEntries(running, [{ kind: "final", text: missing, error: true }]);
      this.notice(job, missing, true);
      this.finish(job, false, missing);
      return { ok: false, delivered: false };
    }
    job.scriptRun = await this.scriptProgram();   // the prompt says how the script runs here
    job.script = job.scriptRun.name;
    await IOUtils.makeDirectory(this.outDir(key), { createAncestors: true, ignoreExisting: true });
    if (!this.alive(running) || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, while the folder was prepared
    await this.writePaper(job.att, job.path, job.parentKey);
    // the other papers of a question about several: the message's, else those the conversation's log names; each gets its
    // paper.json as one paper does. A paper whose PDF is gone is left out
    const refs = (job.kind || "chat") !== "chat" ? [] : Array.isArray(job.papers) ? job.papers : (log && log.papers) || [];
    job.paperFiles = [];
    for (const ref of refs.slice(0, this.MAX_PAPERS - 1)) {
      const other = this.paperAtt(ref);
      if (!other || other === job.att) continue;
      let pdf = null;
      try { pdf = await other.getFilePathAsync(); } catch (e) {}
      if (!pdf) continue;
      const parent = other.parentID ? Zotero.Items.get(other.parentID) : null;
      const k = this.keyOf(other);
      await IOUtils.makeDirectory(this.outDir(k), { createAncestors: true, ignoreExisting: true });
      await this.writePaper(other, pdf, parent ? parent.key : "");
      job.paperFiles.push({ key: k, path: this.paperPath(k), title: ref.title || (parent || other).getDisplayTitle() });
    }
    if (!this.alive(running) || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, meanwhile
    // The pending queue confirmation also keeps the previous session across an update during the first log write.
    let made = job.annotate && job.annotationQueue && job.annotationQueue.conv === job.conv ? job.annotationQueue : null;
    if (!job.conv) {
      if (job.annotate) {
        made = job.annotationQueue || { rows: null };
        made.before = (await this.index(key)).annotation[agent] || null;
      }
      job.conv = await this.newConv(key, agent, job.say || this.text("annotateThis"), job.kind || "chat");
      if (made) made.conv = job.conv;
      // the messages queued meanwhile go on with this conversation, held still when they were
      for (const q of this.queue) {
        if (!q.qid || q.conv || this.keyOf(q.att) !== key || (q.kind || "chat") !== (job.kind || "chat")) continue;
        const was = this.queueKey(q);
        q.conv = job.conv;
        if (this.heldQueues.delete(was)) this.heldQueues.add(this.queueKey(q));
      }
    }
    const logPath = this.convPath(key, job.conv);
    running.conv = job.conv;
    if (running.path !== logPath) {
      running.path = logPath;
      this.livePanes(running);
    }
    job.logPath = logPath;
    if (!this.alive(running) || running.stopAsked) {   // the plugin stopped, or ■, while the log was prepared
      if (made) {
        job.logPath = null;
        await this.unmakeConv(key, agent, made).catch(err => this.log("session not undone: " + err));
        job.conv = null;
        job.typed = made.typed || [];
      }
      return this.halted(job, running, !!made);
    }
    running.log = logPath;
    // the run's agent, and the user's words when it starts a turn; once this line is on its way an update hands the
    // paper over as logged, so that the new copy does not log the turn again
    const user = job.compact || again || continuation ? null : this.turnWords(job);
    running.logged = true;
    if (user !== null) job.turnAt = log ? log.turns.length : 0;   // the turn these words start
    // a log that refuses this line (locked a moment) has nothing of the run: its words go back, no end is logged (drain)
    try {
      if (job.annotate) this.checkedAnnotationQueue(job, key);
      await IOUtils.writeUTF8(logPath, JSON.stringify(Object.assign({ type: "scholium", subtype: "run", agent, user, at: started },
        job.compact ? { compact: true } : {}, job.rewind && job.resume ? { rewind: job.rewind } : {})) + "\n", { mode: "appendOrCreate" });
      if (job.annotate) this.discardAnnotationQueued(job, key);
    } catch (e) {
      job.logPath = running.log = null;
      running.logged = false;
      if (made) {
        await this.unmakeConv(key, agent, made).catch(err => this.log("session not undone: " + err));
        job.conv = null;
        job.logged = false;
        job.typed = made.typed || [];
      }
      throw e;
    }
    if (!job.resume || job.annotate) job.profile = (await this.exists(this.profilePath())) ? this.profilePath() : null;
    // the user's words, an annotation, or an automatic continuation, go into the log as the plugin's own lines; a second
    // try has them already. A question's line marks its conversation as one.
    const prompted = text => ({ type: "scholium", subtype: "prompt", text });
    const quoted = Object.assign(job.quote ? { quote: job.quote } : {},
                                 // the other papers, once a conversation has any: an empty list says they were all left out
                                 Array.isArray(job.papers) && (job.papers.length || (log && log.papers && log.papers.length)) ? { papers: job.papers } : {});
    const mark = job.retried || job.fresh || job.logged ? null
      : job.compact ? { type: "scholium", subtype: "compact", text: job.say || "" }
      : job.annotate ? Object.assign(prompted(this.annotateWords(job)), { annotate: true, extra: job.extra || "" })
      : job.question ? Object.assign(prompted(job.say), { question: true }, quoted)
      : job.say ? Object.assign(prompted(job.say), quoted)
      : job.resume ? { type: "scholium", subtype: "continue", reason: job.updated ? "update" : job.throttled ? "throttle" : undefined } : null;
    if (mark) {
      await IOUtils.writeUTF8(logPath, JSON.stringify(mark) + "\n", { mode: "append" });
      const made = this.entries(mark);
      // the turn's words know their turn, as the log's do once it is read
      for (const e of made) if (e.kind === "prompt" && !e.steer) e.turn = log ? log.turns.length : 0;
      this.appendEntries(running, made);
    }
    // what the agent's run leaves: its result (as Claude Code's result event), a usage limit, the
    // conversation, the exit code and the end of stderr
    const ctx = { job, key, logPath, running, lastStep: -1, result: null, limit: null, session: job.resume || null,
                  exitCode: null, stderr: "", current: null, applies: {}, commands: {}, missing: null, gone: false };
    if (!this.alive(running)) return;   // the plugin stopped while the log was written
    // ■ meanwhile: the run ends as a cancel ends it, its words in the log
    // a new annotation's status and extract, run here before the agent starts (preRun); a question's extract of its
    // papers without sentences.txt (preRunQuestion)
    const question = (job.kind || "chat") === "chat" && !!job.say && !job.resume && !job.compact && !job.annotate;
    job.pre = running.stopAsked ? null : job.annotate && !job.say && !job.compact ? await this.preRun(job, ctx)
      : question ? await this.preRunQuestion(job, ctx) : null;
    if (!this.alive(running)) return;   // the plugin stopped meanwhile
    if (job.pre && job.pre.status && !running.stopAsked) this.advance(ctx, "reading");   // the agent reads the sentences next
    // what the user confirmed of what a run before held back (confirmedFor), once for the message, also for its second try;
    // the file where this run notes what it holds back starts empty (keepHeld)
    if (job.confirmed === undefined) job.confirmed = this.confirmedFor(job, key);
    if (await this.exists(this.heldPath(key, job.conv))) await IOUtils.remove(this.heldPath(key, job.conv), { ignoreAbsent: true }).catch(() => {});
    if (running.stopAsked || (job.pre && job.pre.cancelled)) ctx.current = { key, proc: null, cancelled: true };
    else if (job.pre && job.pre.scanned && !question) this.scannedEnd(ctx);   // a question goes on, told the PDF is a scan
    else if (agent === "codex") await this.runCodex(program, ctx);
    else await this.runClaude(program, ctx);
    await this.appendLog(ctx, []);   // what the log could not take during the run
    await this.keepHeld(ctx);
    running.current = null;
    // an annotation that wrote, the first for a user who never used the reader's eye button: the annotations are shown
    if (running.annotation && ctx.wrote) await ScholiumToggle.showOnce().catch(e => this.log("annotations not shown: " + e));
    const unfinished = this.unfinished(running);   // a cancelled run's, which has no end of its own
    if (!this.alive(running)) return;   // the plugin stopped during the run: nothing more to report
    if (unfinished) {
      await this.appendLog(ctx, [JSON.stringify(unfinished)]);
      this.appendEntries(running, this.entries(unfinished));
    }
    const { result, current, exitCode, limit, session } = ctx;
    const text = result && typeof result.result === "string" ? result.result.trim() : "";
    // a message of the user's that wrote nothing to Zotero was a question: the notices give the answer's
    // opening, the others the run's closing line
    const answered = !!(job.say || job.asked) && exitCode === 0 && !!result && !result.is_error && ctx.lastStep < this.STEPS.indexOf("applying");
    const summary = answered ? this.opening(text) : text.split("\n").pop();
    let ok = false, message, successNotice = null, scannedNotice = false;
    if (current.cancelled) {
      message = this.text("cancelled");
      this.appendEntries(running, this.entries(await this.logEnd(logPath, "cancelled", message, started)));
      if (!job.undone) this.notice(job, message, true);   // Undo of an edit stops it without a word
    } else if (exitCode === 0 && result && !result.is_error) {
      ok = true;
      message = job.compact ? (ctx.compacted ? this.compactSizes(ctx.compacted).replace(/^ · /, "") : "") : summary;
      // a scanned PDF the pre-run found: its whole message, as an error
      const scanned = !!(job.pre && job.pre.scanned);
      successNotice = job.compact ? this.text("compactedNotice") : scanned ? this.text("noTextLayer")
        : [`${this.text("done")} · ${this.duration(Date.now() - started)}`, answered ? summary : this.brief(summary)].filter(Boolean).join("\n");
      scannedNotice = scanned;
      // an annotation's end, also of its second try or of its continuation after a pause: the numbers counted in Zotero,
      // the turns and tokens of all of its runs
      if (running.annotation) {
        const spent = (await this.spentOn(key, job.conv)) || { turns: result.num_turns || 0, tokens: this.tokenCounts(result).reduce((n, [, c]) => n + c, 0) };
        const own = await this.countOwn(job.att);
        const none = !(own.highlights || own.margin || own.notes || own.readingNotes || own.areas);
        const counts = Object.assign({ type: "scholium", subtype: "counts" }, own,
                                     { warnings: none && ctx.missing ? this.text(ctx.missing) : this.warningsOf(text),
                                       turns: spent.turns, tokens: spent.tokens, at: Date.now() },
                                     none && ctx.missing === "noTextLayer" ? { scanned: true } : {});
        await this.appendLog(ctx, [JSON.stringify(counts)]);
        this.appendEntries(running, this.entries(counts));
      }
    } else if (limit) {
      // a limit of the service ("not your usage limit") names no reset time, its message may name a wait
      const said = text + "\n" + ctx.stderr;
      const throttled = !limit.until && /not your usage limit|temporarily limiting|限流/i.test(said);
      return { exitCode, result, limited: true, until: limit.until || this.resetFrom(said), throttled, session };
    } else {
      const errors = result && Array.isArray(result.errors) ? result.errors.map(String).join("; ") : "";
      message = (ctx.failure || (ctx.missing && this.text(ctx.missing)) || summary || errors || ctx.stderr.trim().split("\n").pop()
                 || this.text("exitCode", exitCode)).slice(0, 300);
      // the agent no longer has the session (deleted in Codex's app, cleaned up by Claude Code): a new one goes on with
      // the conversation, given its turns; a continuation has nothing to go on with, and its end says why
      if (job.resume && (ctx.gone || this.gone(message) || (job.rewind && this.rewindRefused(message)))) {
        const again = this.fresh(job);
        const mark = { type: "scholium", subtype: "gone", agent, resent: !!again };
        await this.appendLog(ctx, [JSON.stringify(mark)]);
        if (again) {
          this.endRun(running);
          this.dropRefused(running.entries);
          this.settleRun(running);
          return { exitCode, result, fresh: again };
        }
        message = this.text("goneStopped", agent);
      }
      if (!(result && this.entries(result).length)) {
        this.appendEntries(running, this.entries(await this.logEnd(logPath, "failed", message, started, ctx.noSkill ? { skill: ctx.noSkill } : {})));
      }
      // the connection failed before the agent used a tool, so nothing was written: one more try
      if (!job.retried && !ctx.acted && this.transient(message, ctx.errorInfo)) {
        const mark = { type: "scholium", subtype: "retry" };
        await this.appendLog(ctx, [JSON.stringify(mark)]);
        this.appendEntries(running, this.entries(mark));
        this.endRun(running);
        this.settleRun(running);
        return { exitCode, result, retry: true };
      }
      this.notice(job, `${this.text("failed")} · ${message}`, true);
    }
    const time = { type: "scholium", subtype: "time", at: Date.now() };
    await this.appendLog(ctx, [JSON.stringify(time)]);
    this.appendEntries(running, this.entries(time));
    const outcome = this.outcome(result, current.cancelled), detail = this.tokenDetail(result);
    const pending = this.pendingLogs.get(logPath);
    job.logPending = !!pending;
    if (pending) {
      pending.completed = { key, conv: job.conv, kind: job.kind || "chat", outcome, detail, ok };
      message = this.text("logNotSaved");
      this.notice(job, message, true);
    } else if (successNotice) this.notice(job, successNotice, scannedNotice);
    this.finish(job, ok && !pending, message, pending ? message : outcome, detail, answered && !pending);
    const note = this.notes.get(`${key}/${job.kind || "chat"}`);
    if (pending && note && note.conv === job.conv) note.pendingLog = logPath;
    return { exitCode, result, ok, delivered: !!running.delivered, cancelled: !!current.cancelled };
  },

  // the turns and tokens of a conversation's last turn over all of its runs (a part before a pause, a second try); null
  // when its log cannot be read
  async spentOn(key, conv) {
    const log = await this.readLog(key, conv);
    const turn = log && log.turns[log.turns.length - 1];
    if (!turn) return null;
    let text;
    try { text = await IOUtils.readUTF8(log.path); } catch (e) { return null; }
    let turns = 0, tokens = 0, compacting = false;
    for (const line of text.slice(turn.start).split("\n")) {
      let event;
      try { event = JSON.parse(line); } catch (e) { continue; }
      if (event.type === "scholium" && event.subtype === "run") compacting = !!event.compact;
      if (event.type !== "result" || compacting) continue;
      turns += Number(event.num_turns) || 0;
      tokens += this.tokenCounts(event).reduce((n, [, c]) => n + c, 0);
    }
    return { turns, tokens };
  },

  // lines of a run for its log; those the file did not take (locked a moment by a virus scanner or a backup) go with
  // the next ones, and the run goes on
  async appendLog(ctx, lines) {
    let pending = this.pendingLogs.get(ctx.logPath);
    if (!pending && !lines.length) return true;
    if (!pending) {
      pending = { unlogged: [], flushing: null, held: false };
      this.pendingLogs.set(ctx.logPath, pending);
    }
    pending.unlogged.push(...lines);
    return this.flushLog(ctx.logPath);
  },

  // Each file has one writer. Failed lines stay in order, including the run's final markers.
  async flushLog(path) {
    const pending = this.pendingLogs.get(path);
    if (!pending) return true;
    if (pending.flushing) return pending.flushing;
    if (pending.held) return false;
    pending.flushing = (async () => {
      while (pending.unlogged.length && !pending.held) {
        const lines = pending.unlogged.slice();
        try { await IOUtils.writeUTF8(path, lines.join("\n") + "\n", { mode: "append" }); }
        catch (e) {
          this.log("log not written, kept for retry: " + e);
          this.scheduleLogRetry();
          return false;
        }
        pending.unlogged.splice(0, lines.length);
      }
      if (pending.unlogged.length || pending.held) return false;
      if (this.pendingLogs.get(path) === pending) this.pendingLogs.delete(path);
      this.parsedLogs.delete(path);
      const done = pending.completed;
      if (done && !this.stopped) {
        const noteKey = `${done.key}/${done.kind}`;
        const note = this.notes.get(noteKey);
        if (note && note.conv === done.conv && (note.pendingLog === path || note.text === this.text("logNotSaved"))) {
          if (done.kind === "annotate") this.notes.delete(noteKey);
          else this.notes.set(noteKey, { text: done.outcome, title: done.detail, error: !done.ok, at: Date.now(), conv: done.conv });
        }
        this.refresh();
        for (const pane of this.panes.values()) if (pane.keys.includes(done.key)) {
          this.showConversation(pane).catch(e => this.log("section not shown: " + e));
        }
      }
      return true;
    })();
    try { return await pending.flushing; }
    finally { pending.flushing = null; }
  },

  scheduleLogRetry() {
    if (this.stopped) {
      const owner = Zotero.ScholiumLogWriter;
      if (owner && owner !== this && !owner.stopped) owner.scheduleLogRetry();
      return;
    }
    if (this.logRetryTimer) return;
    this.logRetryTimer = setTimeout(() => {
      this.logRetryTimer = null;
      this.retryLogs().catch(e => this.log("logs not retried: " + e));
    }, 5000);
  },

  async retryLogs() {
    await this.settled();
    for (const path of [...this.pendingLogs.keys()]) await this.flushLog(path);
    if ([...this.pendingLogs.values()].some(p => !p.held)) this.scheduleLogRetry();
    if (!this.stopped) this.refresh();
  },

  // the end of a run that has no result of its own (cancelled, failed before a result) as the plugin's line in the
  // log, so that the paper's history shows how it ended
  async logEnd(logPath, outcome, text, started = 0, extra = {}) {
    const mark = Object.assign({ type: "scholium", subtype: "end", outcome, text }, extra);
    if (started) mark.duration_ms = Date.now() - started;
    await this.appendLog({ logPath }, [JSON.stringify(mark)]);
    return mark;
  },

  // the first line of an answer that says something, without its Markdown marks, for a notice; code
  // fences and a table's rule are passed over, a table row's cells are joined
  opening(text) {
    for (const raw of String(text || "").split("\n")) {
      const line = raw.trim();
      if (/^(```|~~~)/.test(line) || /^[\s|:-]*$/.test(line)) continue;
      const plain = line.replace(/^(#{1,6}\s+|[-*+]\s+|\d{1,9}[.)]\s+|>\s*)/, "").replace(/^\||\|$/g, "")
        .replace(/\s*\|\s*/g, " · ").replace(/\*\*|`/g, "").trim();
      if (plain) return plain.length > 80 ? plain.slice(0, 79) + "…" : plain;
    }
    return "";
  },

  // whether a failure says the agent no longer has its session: Codex's thread/resume, Claude Code's --resume
  gone(message) {
    return /no rollout found for thread|No conversation found with session ID/i.test(String(message || ""));
  },

  // whether Claude Code could not take the session back to an edited question's point: it no longer has that message
  // (compacted since), or it does not know the options
  rewindRefused(message) {
    return /No message found with message\.uuid|unknown option '--(?:resume-session-at|fork-session)'/i.test(String(message || ""));
  },

  // the job for a new session of the agent when the one it was to continue is gone: the user's words or the annotation,
  // with the whole conversation; null for a continuation after a limit or an update, and for a compaction
  fresh(job) {
    if (job.compact || (!job.say && !job.annotate)) return null;
    return Object.assign({}, job, { resume: null, rewind: null, asked: false, updated: false, throttled: false, retried: false, retryAt: 0,
                                    interrupted: false, fresh: true, qid: null });
  },

  // whether a failure is the connection to the agent's service (a timeout, a lost connection, an
  // overloaded or failing server), which a second try may not meet
  transient(message, info) {
    const kind = info && typeof info === "object" ? Object.keys(info)[0] : info;
    if (["httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected", "responseTooManyFailedAttempts",
         "serverOverloaded", "internalServerError"].includes(kind)) return true;
    return /timed? ?out|timeout|connection|network|socket|ECONN|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|error sending request|overloaded|API Error: 5\d\d/i
      .test(String(message || ""));
  },

  // the running paper reached a step; steps only go forward
  advance(ctx, step) {
    const i = step ? this.STEPS.indexOf(step) : -1;
    if (i <= ctx.lastStep) return;
    ctx.lastStep = i;
    ctx.running.step = step;
    this.refresh();
  },

  // the agent has the prompt: a queued message's row no longer says it is being sent
  deliver(ctx) {
    ctx.running.delivered = true;
    if (ctx.job.qid) this.refresh();
  },

  // the agent lost its connection and tries again: attempt n of max, when it says, on the state line
  reconnecting(ctx, attempt, max) {
    ctx.running.retry = { attempt: Number(attempt) || null, max: Number(max) || null };
    this.refresh();
  },

  // the agent answers again
  reconnected(ctx) {
    if (!ctx.running.retry) return;
    ctx.running.retry = null;
    this.refresh();
  },

  // what the agent's process is told for the skill's script: that it runs for the plugin, where it notes what it holds
  // back, and what the user confirmed (empty otherwise, whatever Zotero's own environment says)
  runEnv(ctx) {
    const confirmed = Object.entries(ctx.job.confirmed || {}).filter(([, keys]) => keys.length).map(([kind, keys]) => `${kind}:${keys.join(",")}`);
    return { SCHOLIUM_PLUGIN_RUN: "1", SCHOLIUM_HELD_BACK: this.heldPath(ctx.key, ctx.job.conv), SCHOLIUM_CONFIRMED: confirmed.join(";") };
  },

  // the folder Claude Code runs in: the conversation's own (workDir); a session that started elsewhere (before the
  // plugin's folder, in the data directory) goes on there, since Claude Code keeps a session with its folder, and so
  // does an edit's fork of it
  async claudeDir(ctx) {
    const { job, key } = ctx;
    if (job.resume) {
      const log = job.conv ? await this.readLog(key, job.conv) : null;
      const at = log && log.cwds ? log.cwds[job.resume] : null;
      if (!at) return Zotero.DataDirectory.dir;
      if (!this.inside(this.root(), at)) return at;
    }
    const dir = this.workDir(key, job.conv);
    await IOUtils.makeDirectory(dir, { createAncestors: true, ignoreExisting: true });
    return dir;
  },

  // Claude Code: `claude -p` with the prompt on stdin and its stream-json events on stdout
  async runClaude(claude, ctx) {
    const { job, key } = ctx;
    const env = await this.agentEnv();
    Object.assign(env.environment, this.runEnv(ctx));
    // a turn of an annotation or of words to its session writes at most MAX_OUTPUT_TOKENS, its thinking included, unless
    // the user's environment sets the limit
    if ((job.kind === "annotate" || ctx.running.annotation) && !this.env("CLAUDE_CODE_MAX_OUTPUT_TOKENS")) env.environment.CLAUDE_CODE_MAX_OUTPUT_TOKENS = String(this.MAX_OUTPUT_TOKENS);
    ctx.cwd = await this.claudeDir(ctx);
    const proc = await this.subprocess().call(Object.assign({
      command: claude, arguments: await this.args(job), workdir: ctx.cwd, stderr: "pipe",
    }, env));
    if (!this.alive(ctx.running) || ctx.running.stopAsked) {   // the plugin stopped, or ■, while the process was being created
      try { proc.kill(); } catch (e) {}
      ctx.current = { key, proc, cancelled: true };
      return;
    }
    ctx.running.current = ctx.current = { key, proc, cancelled: false };
    this.refresh();
    const drainErr = (async () => {
      for (;;) { const s = await proc.stderr.readString(); if (!s) break; ctx.stderr = (ctx.stderr + s).slice(-2000); }
    })().catch(() => {});
    let buffer = "";
    try {
      await proc.stdin.write(this.prompt(job, job.own));
      await proc.stdin.close();
      for (;;) {
        const chunk = await proc.stdout.readString();
        if (!chunk) break;
        buffer += chunk;
        const lines = buffer.split("\n");
        buffer = lines.pop();
        // the lines for the log, in the order they are shown: the text as it is written stays out (the
        // whole messages carry it), and what a failed run showed of an unfinished message goes before its end
        const kept = [];
        for (const raw of lines) {
          let event = null;
          try { event = JSON.parse(raw); } catch (e) {}
          if (!event || typeof event !== "object") {
            kept.push(raw);
            continue;
          }
          if (event.type === "stream_event") {
            this.reconnected(ctx);
            const e = event.event || {};
            if (!event.parent_tool_use_id && e.type === "message_start") this.dropDraft(ctx.running);   // a message begun again starts afresh
            if (!event.parent_tool_use_id && e.type === "content_block_delta" && e.delta && e.delta.type === "text_delta") {
              this.growDraft(ctx.running, String(e.delta.text || ""), e.index);
            }
            continue;
          }
          if (event.type === "assistant") this.dropDraft(ctx.running);   // the whole message replaces its draft
          if (event.type === "assistant" || event.type === "result") this.deliver(ctx);   // the agent has the prompt
          // a compaction answers with its status and boundary
          if (job.compact && event.type === "system" && (event.subtype === "compact_boundary" || (event.subtype === "status" && event.status === "compacting"))) {
            ctx.running.delivered = true;
          }
          if (event.type === "result") {
            const unfinished = this.unfinished(ctx.running);
            if (unfinished) {
              kept.push(JSON.stringify(unfinished));
              this.appendEntries(ctx.running, this.entries(unfinished));
            }
          }
          kept.push(event.type === "user" ? this.slim(event, raw) : raw);
          if (typeof event.session_id === "string" && event.session_id) ctx.session = ctx.running.session = event.session_id;
          ctx.running.context = this.contextAfter(event, ctx.running.context);
          // a write to Zotero, kept with its configuration once its command wrote
          for (const c of (event.message && event.message.content) || []) {
            if (event.type === "assistant" && c && c.type === "tool_use" && c.id) ctx.commands[c.id] = String((c.input || {}).command || "");
            if (event.type === "user" && c && c.type === "tool_result") ctx.missing = this.missingAfter(ctx.commands[c.tool_use_id], c.content, ctx.missing);
            const config = event.type === "assistant" && c && c.type === "tool_use" && this.appliedConfig(String((c.input || {}).command || ""));
            if (config && c.id) ctx.applies[c.id] = config;
            const applied = event.type === "user" && c && c.type === "tool_result" && ctx.applies[c.tool_use_id];
            if (applied && this.wrote(c.content, !c.is_error)) {
              ctx.wrote = true;
              await this.noteApplied(key, applied, "claude", job.conv, ctx.cwd || Zotero.DataDirectory.dir);
            }
          }
          // the skills Claude Code loaded: without this one the run would only look for it
          if (event.type === "system" && event.subtype === "init" && Array.isArray(event.skills)
              && !event.skills.some(name => /(?:^|:)zotero-scholium$/.test(String(name)))) {
            ctx.failure = this.text("noSkill", "claude");
            ctx.noSkill = "claude";
            try { proc.kill(); } catch (e) {}
          }
          if (event.type === "result") ctx.result = event;
          if (event.type === "system" && event.subtype === "compact_boundary") ctx.compacted = this.entries(event)[0];
          if (event.type === "assistant" && ((event.message && event.message.content) || []).some(c => c && c.type === "tool_use")) ctx.acted = true;
          if (event.type === "rate_limit_event" && event.rate_limit_info) {
            const info = event.rate_limit_info;
            if (info.status === "rejected") ctx.limit = { until: info.resetsAt > 0 ? info.resetsAt * 1000 : null };
          }
          if (event.type === "assistant" && event.error === "rate_limit" && !ctx.limit) ctx.limit = { until: null };
          if (event.type === "assistant" && event.error === "authentication_failed") ctx.failure = this.text("notSignedIn", "claude");
          if (event.type === "system" && event.subtype === "api_retry") this.reconnecting(ctx, event.attempt, event.max_retries);
          else if (["assistant", "user", "result"].includes(event.type)) this.reconnected(ctx);
          this.appendEntries(ctx.running, this.entries(event));
          this.advance(ctx, this.step(event));
        }
        if (kept.length) await this.appendLog(ctx, kept);
      }
    } catch (e) {
      // the run is reported as failed: Claude Code must not go on writing to Zotero meanwhile
      try { proc.kill(); } catch (e2) {}
      throw e;
    }
    await drainErr;
    ctx.exitCode = (await proc.wait()).exitCode;
  },

  // a tool's result as the log keeps it: without the copy Claude Code adds for itself and without the data of the images
  // (pages the agent looked at), which the transcript does not show
  slim(event, raw) {
    let changed = false;
    if ("tool_use_result" in event) {
      delete event.tool_use_result;
      changed = true;
    }
    const parts = (event.message && Array.isArray(event.message.content) && event.message.content) || [];
    for (const part of parts.concat(...parts.map(c => (c && Array.isArray(c.content) && c.content) || []))) {
      if (part && part.type === "image" && part.source && typeof part.source.data === "string" && part.source.data) {
        part.source.data = "";
        changed = true;
      }
    }
    return changed ? JSON.stringify(event) : raw;
  },

  // stops the run under way; one still starting, before its agent's process, stops at its next step (run)
  // ■ of a run; without one, of every run going on
  cancel(run = null) {
    const runs = run ? [run] : [...this.runs.values()];
    let any = false;
    for (const r of runs) {
      if (!this.alive(r)) continue;
      any = true;
      const current = r.current;
      if (!current) { r.stopAsked = true; continue; }
      current.cancelled = true;
      try { if (current.stop) current.stop(); else current.proc.kill(); } catch (e) {}
    }
    return any;
  },
});
