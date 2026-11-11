// ScholiumRunner, continued: a run, Claude Code and Codex, cancelling, deleting the tool's annotations, and the
// runner's start, hand-over and stop

Object.assign(ScholiumRunner, {
  async run(job) {
    const started = Date.now();
    const key = this.keyOf(job.att);
    const agent = job.agent === "codex" ? "codex" : "claude";
    this.job = { title: job.title, key, libraryID: job.att.libraryID, started, elapsed: 0, agent, step: job.resume && !job.annotate ? "continuing" : "starting",
                 source: job, session: job.resume || null, log: null, asking: this.asking(job), context: null };
    this.transcriptKind = job.kind || "chat";   // the tab whose run this is, from its start
    const running = this.job;
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
    if (this.job !== running) return;   // the plugin stopped meanwhile
    // the run is one of the transcript's from its start; its line goes into the log once the log is there. One that goes
    // on with the turn before is an annotation's when that turn is: its state line counts the steps its list names
    this.transcript = (log ? log.entries : []).concat(this.entries({ type: "scholium", subtype: "run", at: started, compact: !!job.compact,
                                                                                     user: job.compact || again || continuation ? null : "" }));
    const runs = this.runsOf(this.transcript), turn = runs[runs.length - 1].turn;
    running.annotation = !!job.annotate || !!(turn && turn.annotate);
    this.transcriptKey = key;
    this.transcriptPath = log ? log.path : null;
    running.context = mine ? mine.context : null;
    // another run of a conversation whose question was edited a moment ago: the edit can no longer be undone
    if (!job.edited && job.conv) this.endReplaced(`${key}/${job.conv}`);
    this.startPanes(key, this.transcriptKind);
    this.notice(job, this.text(job.compact ? "compacting" : job.annotate || (!job.say && !job.resume) ? "typical" : job.question ? "askNotice" : "continuedNotice"));
    this.refresh();
    this.tick(running).catch(() => {});
    if (running.stopAsked) return this.halted(job, running);   // ■ while the log was read
    const program = agent === "codex" ? await this.findCodex() : await this.findClaude();
    if (this.job !== running || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, while the program was looked up
    if (!program) {
      const missing = this.text(agent === "codex" ? "noCodex" : "noClaude");
      this.handBack(job, false);
      this.appendEntries([{ kind: "final", text: missing, error: true }]);
      this.notice(job, missing, true);
      this.finish(job, false, missing);
      return { ok: false, delivered: false };
    }
    job.scriptRun = await this.scriptProgram();   // the prompt says how the script runs here
    job.script = job.scriptRun.name;
    await IOUtils.makeDirectory(this.outDir(key), { createAncestors: true, ignoreExisting: true });
    if (this.job !== running || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, while the folder was prepared
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
    if (this.job !== running || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, meanwhile
    let made = null;   // an annotation's new session, and the agent's session before it
    if (!job.conv) {
      if (job.annotate) made = { before: (await this.index(key)).annotation[agent] || null };
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
    if (this.transcriptPath !== logPath) {
      this.transcriptPath = logPath;
      this.livePanes(key, job.conv);
    }
    job.logPath = logPath;
    if (this.job !== running || running.stopAsked) {   // the plugin stopped, or ■, while the log was prepared
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
      await IOUtils.writeUTF8(logPath, JSON.stringify(Object.assign({ type: "scholium", subtype: "run", agent, user, at: started },
        job.compact ? { compact: true } : {}, job.rewind && job.resume ? { rewind: job.rewind } : {})) + "\n", { mode: "appendOrCreate" });
    } catch (e) {
      job.logPath = running.log = null;
      running.logged = false;
      if (made) {
        await this.unmakeConv(key, agent, made).catch(err => this.log("session not undone: " + err));
        job.conv = null;
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
      this.appendEntries(made);
    }
    // what the agent's run leaves: its result (as Claude Code's result event), a usage limit, the
    // conversation, the exit code and the end of stderr
    const ctx = { job, key, logPath, running, lastStep: -1, result: null, limit: null, session: job.resume || null,
                  exitCode: null, stderr: "", current: null, applies: {}, commands: {}, missing: null, gone: false, unlogged: [] };
    if (this.job !== running) return;   // the plugin stopped while the log was written
    // ■ meanwhile: the run ends as a cancel ends it, its words in the log
    // a new annotation's status and extract, run here before the agent starts (preRun); a question's extract of its
    // papers without sentences.txt (preRunQuestion)
    const question = (job.kind || "chat") === "chat" && !!job.say && !job.resume && !job.compact && !job.annotate;
    job.pre = running.stopAsked ? null : job.annotate && !job.say && !job.compact ? await this.preRun(job, ctx)
      : question ? await this.preRunQuestion(job, ctx) : null;
    if (this.job !== running) return;   // the plugin stopped meanwhile
    if (job.pre && job.pre.status && !running.stopAsked) this.advance(ctx, "reading");   // the agent reads the sentences next
    if (running.stopAsked || (job.pre && job.pre.cancelled)) ctx.current = { key, proc: null, cancelled: true };
    else if (job.pre && job.pre.scanned && !question) this.scannedEnd(ctx);   // a question goes on, told the PDF is a scan
    else if (agent === "codex") await this.runCodex(program, ctx);
    else await this.runClaude(program, ctx);
    await this.appendLog(ctx, []);   // what the log could not take during the run
    this.current = null;
    // an annotation that wrote, the first for a user who never used the reader's eye button: the annotations are shown
    if (running.annotation && ctx.wrote) await ScholiumToggle.showOnce().catch(e => this.log("annotations not shown: " + e));
    const unfinished = this.unfinished();   // a cancelled run's, which has no end of its own
    if (this.job !== running) return;   // the plugin stopped during the run: nothing more to report
    if (unfinished) {
      try { await IOUtils.writeUTF8(logPath, JSON.stringify(unfinished) + "\n", { mode: "append" }); }
      catch (e) { this.log("unfinished message not logged: " + e); }
      this.appendEntries(this.entries(unfinished));
    }
    const { result, current, exitCode, limit, session } = ctx;
    const text = result && typeof result.result === "string" ? result.result.trim() : "";
    // a message of the user's that wrote nothing to Zotero was a question: the notices give the answer's
    // opening, the others the run's closing line
    const answered = !!(job.say || job.asked) && exitCode === 0 && !!result && !result.is_error && ctx.lastStep < this.STEPS.indexOf("applying");
    const summary = answered ? this.opening(text) : text.split("\n").pop();
    let ok = false, message;
    if (current.cancelled) {
      message = this.text("cancelled");
      this.appendEntries(this.entries(await this.logEnd(logPath, "cancelled", message, started)));
      if (!job.undone) this.notice(job, message, true);   // Undo of an edit stops it without a word
    } else if (exitCode === 0 && result && !result.is_error) {
      ok = true;
      message = job.compact ? (ctx.compacted ? this.compactSizes(ctx.compacted).replace(/^ · /, "") : "") : summary;
      // a scanned PDF the pre-run found: its whole message, as an error
      const scanned = !!(job.pre && job.pre.scanned);
      this.notice(job, job.compact ? this.text("compactedNotice") : scanned ? this.text("noTextLayer")
        : [`${this.text("done")} · ${this.duration(Date.now() - started)}`, answered ? summary : this.brief(summary)].filter(Boolean).join("\n"), scanned);
      // an annotation's end, also of its second try or of its continuation after a pause: the numbers counted in Zotero,
      // the turns and tokens of all of its runs
      if (running.annotation) {
        const spent = (await this.spentOn(key, job.conv)) || { turns: result.num_turns || 0, tokens: this.tokenCounts(result).reduce((n, [, c]) => n + c, 0) };
        const own = await this.countOwn(job.att);
        const none = !(own.highlights || own.margin || own.notes || own.readingNotes);
        const counts = Object.assign({ type: "scholium", subtype: "counts" }, own,
                                     { warnings: none && ctx.missing ? this.text(ctx.missing) : this.warningsOf(text),
                                       turns: spent.turns, tokens: spent.tokens, at: Date.now() },
                                     none && ctx.missing === "noTextLayer" ? { scanned: true } : {});
        try { await IOUtils.writeUTF8(logPath, JSON.stringify(counts) + "\n", { mode: "append" }); }
        catch (e) { this.log("counts not logged: " + e); }
        this.appendEntries(this.entries(counts));
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
        await IOUtils.writeUTF8(logPath, JSON.stringify(mark) + "\n", { mode: "append" });
        if (again) {
          if (this.job === running) this.job = null;
          this.dropRefused(this.transcript);
          this.settleRun();
          return { exitCode, result, fresh: again };
        }
        message = this.text("goneStopped", agent);
      }
      if (!(result && this.entries(result).length)) {
        this.appendEntries(this.entries(await this.logEnd(logPath, "failed", message, started, ctx.noSkill ? { skill: ctx.noSkill } : {})));
      }
      // the connection failed before the agent used a tool, so nothing was written: one more try
      if (!job.retried && !ctx.acted && this.transient(message, ctx.errorInfo)) {
        const mark = { type: "scholium", subtype: "retry" };
        await IOUtils.writeUTF8(logPath, JSON.stringify(mark) + "\n", { mode: "append" });
        this.appendEntries(this.entries(mark));
        if (this.job === running) this.job = null;
        this.settleRun();
        return { exitCode, result, retry: true };
      }
      this.notice(job, `${this.text("failed")} · ${message}`, true);
    }
    const time = { type: "scholium", subtype: "time", at: Date.now() };
    try { await IOUtils.writeUTF8(logPath, JSON.stringify(time) + "\n", { mode: "append" }); }
    catch (e) { this.log("end time not logged: " + e); }
    this.appendEntries(this.entries(time));
    this.finish(job, ok, message, this.outcome(result, current.cancelled), this.tokenDetail(result), answered);
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
    const all = ctx.unlogged.concat(lines);
    if (!all.length) return;
    try {
      await IOUtils.writeUTF8(ctx.logPath, all.join("\n") + "\n", { mode: "append" });
      ctx.unlogged = [];
    } catch (e) {
      ctx.unlogged = all;
      this.log("log not written, kept for the next lines: " + e);
    }
  },

  // the end of a run that has no result of its own (cancelled, failed before a result) as the plugin's line in the
  // log, so that the paper's history shows how it ended
  async logEnd(logPath, outcome, text, started = 0, extra = {}) {
    const mark = Object.assign({ type: "scholium", subtype: "end", outcome, text }, extra);
    if (started) mark.duration_ms = Date.now() - started;
    try { await IOUtils.writeUTF8(logPath, JSON.stringify(mark) + "\n", { mode: "append" }); }
    catch (e) { this.log("end not logged: " + e); }
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

  // the skill's script as the agent runs it, for the plugin's own first steps (preRun, preRunQuestion): with the command
  // its prompt names (scriptProgram), the agent's environment, in a paper's output folder, within a time; the process is
  // the run's current one, which ■ kills. null after ■ or a stop, and once one came while the process was being created
  preRunner(job, ctx, script, env) {
    const runner = job.scriptRun || {}, running = ctx.running, key = ctx.key;
    return async (args, ms, workdir) => {
      if (running.stopAsked || this.job !== running) return null;
      const proc = await this.subprocess().call(Object.assign({ command: runner.command, arguments: runner.prefix.concat([script], args),
                                                                 workdir }, env));
      if (running.stopAsked || this.job !== running) {   // the plugin stopped, or ■, while the process was being created
        try { proc.kill(); } catch (e) {}
        ctx.current = { key, proc, cancelled: true };
        return null;
      }
      this.current = ctx.current = { key, proc, cancelled: false };
      try { return await this.readOutput(proc, ms); }
      finally { this.current = null; }
    };
  },

  // `extract` of a paper (its key of keyOf) into its output folder by a preRunner: { lines (of sentences.txt) }; { scanned }
  // for a PDF without a text layer (exit code 3); { cancelled } after ■; null when it failed or did not end in time
  async preExtract(run, ctx, k, ms) {
    const out = this.outDir(k), txt = PathUtils.join(out, "sentences.txt");
    const extract = await run(["extract", "--config", this.paperPath(k), "--sentences", PathUtils.join(out, "sentences.json"), "--out", txt],
                              ms, out);
    if (ctx.current && ctx.current.cancelled) return { cancelled: true };
    if (!extract || extract.late) return null;
    if (extract.exitCode === 3) return { scanned: true };
    if (extract.exitCode !== 0) return null;
    const text = await IOUtils.readUTF8(txt);
    return { lines: text.split(/\r?\n/).length - (/\n$/.test(text) ? 1 : 0) };
  },

  // an annotation's first steps, run by the plugin before the agent starts, by the skill's script the agent runs
  // (skillScript, preRunner): `status <item key> [--group ID]` within PRE_STATUS_MS, then `extract` within PRE_EXTRACT_MS.
  // { status (its JSON, minified), lines (of sentences.txt), script } when both ran; { scanned } for a PDF without a text
  // layer; { cancelled } after ■; null otherwise, and the agent runs them itself. The live line says the PDF is read
  async preRun(job, ctx) {
    const script = job.scriptRun && job.scriptRun.command ? await this.skillScript(job.agent) : null;
    if (!script) return null;
    const key = this.keyOf(job.att), running = ctx.running;
    const run = this.preRunner(job, ctx, script, await this.agentEnv(job.agent === "codex"));
    const group = this.groupOf(job.att.libraryID);
    running.preRun = true;
    this.refresh();
    this.settleRun();
    try {
      // a PDF without a parent item is named by its own key, which status takes too
      const status = await run(["status", job.parentKey || job.att.key].concat(group ? ["--group", String(group)] : []), this.PRE_STATUS_MS,
                               this.outDir(key));
      if (ctx.current && ctx.current.cancelled) return { cancelled: true };
      let json = null;
      try { json = status && !status.late && status.exitCode === 0 ? JSON.stringify(JSON.parse(status.out)) : null; } catch (e) {}
      if (!json) return null;
      this.advance(ctx, "extract");   // the agent's steps go on after it
      const extract = await this.preExtract(run, ctx, key, this.PRE_EXTRACT_MS);
      if (!extract || extract.cancelled || extract.scanned) return extract;
      return { status: json, lines: extract.lines, script };
    } catch (e) {
      this.log("pre-run failed: " + e);
      return null;
    } finally {
      running.preRun = false;
      this.refresh();
      this.settleRun();
    }
  },

  // a question's first step, run by the plugin before the agent starts as preRun runs it: `extract` of each of its papers
  // whose output folder has no sentences.txt yet, the paper shown first, one after the other, all within PRE_EXTRACT_MS.
  // `status` is left to the agent: a question needs the paper's record (authors, venue, notes) only now and then. { lines,
  // script } when the paper shown was extracted; { scanned } when it has no text layer (its other papers are extracted all
  // the same, and the agent is told it is a scan); { cancelled } after ■; null
  // otherwise, and the agent runs extract itself. Each other paper's entry of job.paperFiles says whether its
  // sentences.txt is there (sentences) or it has no text layer (scanned)
  async preRunQuestion(job, ctx) {
    const key = this.keyOf(job.att), running = ctx.running;
    const there = k => this.exists(PathUtils.join(this.outDir(k), "sentences.txt"));
    const papers = [];
    if (!(await there(key))) papers.push(null);
    for (const f of job.paperFiles || []) {
      if (await there(f.key)) f.sentences = true;
      else papers.push(f);
    }
    const script = papers.length && job.scriptRun && job.scriptRun.command ? await this.skillScript(job.agent) : null;
    if (!script || this.job !== running) return null;
    const run = this.preRunner(job, ctx, script, await this.agentEnv(job.agent === "codex"));
    const until = Date.now() + this.PRE_EXTRACT_MS;
    let pre = null;
    running.preRun = true;
    this.refresh();
    this.settleRun();
    try {
      for (const f of papers) {
        const left = until - Date.now();
        if (left < 1000 || running.stopAsked || this.job !== running) break;   // the rest are the agent's
        const done = await this.preExtract(run, ctx, f ? f.key : key, left);
        if (done && done.cancelled) return done;
        if (f) Object.assign(f, done && done.lines >= 0 ? { sentences: true } : done && done.scanned ? { scanned: true } : {});
        else if (done && done.scanned) pre = { scanned: true };
        else if (done) pre = { lines: done.lines, script };
      }
      return pre;
    } catch (e) {
      this.log("pre-run failed: " + e);
      return pre;
    } finally {
      running.preRun = false;
      this.refresh();
      this.settleRun();
    }
  },

  // a scanned PDF found by the pre-run: the run ends as an agent's does that found it, with the card that says so
  scannedEnd(ctx) {
    ctx.current = { key: ctx.key, proc: null, cancelled: false };
    ctx.exitCode = 0;
    ctx.missing = "noTextLayer";
    ctx.result = { type: "result", subtype: "success", is_error: false, result: this.text("noTextLayer"), num_turns: 0 };
  },

  // Claude Code: `claude -p` with the prompt on stdin and its stream-json events on stdout
  async runClaude(claude, ctx) {
    const { job, key } = ctx;
    const env = await this.agentEnv();
    // a turn of an annotation or of words to its session writes at most MAX_OUTPUT_TOKENS, its thinking included, unless
    // the user's environment sets the limit
    if ((job.kind === "annotate" || ctx.running.annotation) && !this.env("CLAUDE_CODE_MAX_OUTPUT_TOKENS")) env.environment.CLAUDE_CODE_MAX_OUTPUT_TOKENS = String(this.MAX_OUTPUT_TOKENS);
    const proc = await this.subprocess().call(Object.assign({
      command: claude, arguments: await this.args(job), workdir: Zotero.DataDirectory.dir, stderr: "pipe",
    }, env));
    if (this.job !== ctx.running || ctx.running.stopAsked) {   // the plugin stopped, or ■, while the process was being created
      try { proc.kill(); } catch (e) {}
      ctx.current = { key, proc, cancelled: true };
      return;
    }
    this.current = ctx.current = { key, proc, cancelled: false };
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
            if (!event.parent_tool_use_id && e.type === "message_start") this.dropDraft();   // a message begun again starts afresh
            if (!event.parent_tool_use_id && e.type === "content_block_delta" && e.delta && e.delta.type === "text_delta") {
              this.growDraft(String(e.delta.text || ""), e.index);
            }
            continue;
          }
          if (event.type === "assistant") this.dropDraft();   // the whole message replaces its draft
          if (event.type === "assistant" || event.type === "result") this.deliver(ctx);   // the agent has the prompt
          // a compaction answers with its status and boundary
          if (job.compact && event.type === "system" && (event.subtype === "compact_boundary" || (event.subtype === "status" && event.status === "compacting"))) {
            ctx.running.delivered = true;
          }
          if (event.type === "result") {
            const unfinished = this.unfinished();
            if (unfinished) {
              kept.push(JSON.stringify(unfinished));
              this.appendEntries(this.entries(unfinished));
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
              await this.noteApplied(key, applied, "claude", job.conv, Zotero.DataDirectory.dir);
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
          this.appendEntries(this.entries(event));
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

  // `codex app-server`: JSON-RPC over stdin and stdout, one message per line. Answers settle their
  // requests, questions from Codex are answered by codexAnswer, and everything else goes to
  // onMessage([[message, line], …]) a chunk at a time.
  async codexServer(codex, workdir, onMessage = null) {
    const proc = await this.subprocess().call(Object.assign({
      command: codex, arguments: ["app-server"], workdir, stderr: "pipe",
    }, await this.agentEnv(true)));
    const rpc = { proc, next: 1, pending: new Map(), stderr: "" };
    const send = msg => proc.stdin.write(JSON.stringify(msg) + "\n");
    rpc.request = (method, params) => new Promise((resolve, reject) => {
      const id = rpc.next++;
      rpc.pending.set(id, { resolve, reject });
      send({ method, id, params }).catch(e => { rpc.pending.delete(id); reject(e); });
    });
    rpc.notify = method => { send({ method }).catch(() => {}); };
    rpc.close = () => { try { proc.kill(); } catch (e) {} };
    const errors = (async () => {
      for (;;) { const s = await proc.stderr.readString(); if (!s) break; rpc.stderr = (rpc.stderr + s).slice(-2000); }
    })().catch(() => {});
    // however reading ends, no request is left waiting; a failure here also ends the server
    rpc.done = (async () => {
      let failure = null;
      try {
        let buffer = "";
        for (;;) {
          const chunk = await proc.stdout.readString();
          if (!chunk) break;
          buffer += chunk;
          const lines = buffer.split("\n");
          buffer = lines.pop();
          const messages = [];
          for (const raw of lines) {
            let msg;
            try { msg = JSON.parse(raw); } catch (e) { continue; }
            if (!msg || typeof msg !== "object") continue;
            const id = msg.id;
            if (id !== undefined && id !== null && typeof msg.method !== "string") {
              const waiting = rpc.pending.get(id);
              if (waiting) {
                rpc.pending.delete(id);
                // Codex's answer that the request failed, unlike the end of the server
                if (msg.error) waiting.reject(Object.assign(new Error(String(msg.error.message || JSON.stringify(msg.error))), { refused: true }));
                else waiting.resolve(msg.result);
              }
              continue;
            }
            if (id !== undefined && id !== null) send(Object.assign({ id }, this.codexAnswer(msg))).catch(() => {});
            messages.push([msg, raw]);
          }
          if (onMessage && messages.length) await onMessage(messages);
        }
      } catch (e) {
        failure = e;
        rpc.close();
      } finally {
        await errors;
        const tail = rpc.stderr.trim().split("\n").pop() || "";
        for (const waiting of rpc.pending.values()) waiting.reject(failure || new Error(this.text("codexExited", tail)));
        rpc.pending.clear();
      }
      if (failure) throw failure;
    })();
    return rpc;
  },

  async codexHello(rpc) {
    await rpc.request("initialize", { clientInfo: { name: "scholium", title: "Scholium", version: this.version || "0" } });
    rpc.notify("initialized");
  },

  // a question from Codex during an unattended run: its automatic reviewer has decided on what it
  // could, and nobody is there for the rest, so approvals are declined and questions get no answer
  codexAnswer(msg) {
    switch (msg.method) {
      case "item/commandExecution/requestApproval":
      case "item/fileChange/requestApproval": return { result: { decision: "decline" } };
      case "execCommandApproval":
      case "applyPatchApproval": return { result: { decision: "denied" } };
      case "item/permissions/requestApproval": return { result: { permissions: {}, scope: "turn" } };
      case "item/tool/requestUserInput": return { result: { answers: {} } };
      case "mcpServer/elicitation/request": return { result: { action: "decline", content: null, _meta: null } };
    }
    return { error: { code: -32601, message: "not handled by scholium" } };
  },

  // streaming deltas and start-up chatter stay out of the log, the whole items carry the same text; so does the user's
  // message, which the plugin's own line has, and the turn's diff, which each file change repeats whole
  codexNoise(msg) {
    if (/^item\/(?:started|completed)$/.test(String(msg.method || "")) && msg.params && msg.params.item && msg.params.item.type === "userMessage") return true;
    return /(?:[Dd]elta|summaryPartAdded|startupStatus\/updated|remoteControl\/status\/changed|^turn\/diff\/updated)$/.test(String(msg.method || ""));
  },

  // the Codex threads a log's runs used: the session of each Codex start line
  codexThreads(text) {
    const threads = new Set();
    for (const line of String(text || "").split("\n")) {
      if (!line.includes('"codex"')) continue;
      try {
        const e = JSON.parse(line);
        if (e && e.type === "system" && e.subtype === "init" && e.agent === "codex" && typeof e.session_id === "string" && e.session_id) threads.add(e.session_id);
      } catch (err) {}
    }
    return threads;
  },

  // the Codex threads no conversation uses any more, archived at the next Codex run as llm-for-zotero archives them: a
  // deleted conversation's, those only an edit's new run used (Undo), those only its replaced part used (once Undo is gone)
  queueArchive(thread) {
    let ids = [];
    try { ids = JSON.parse(this.getPref("codexArchive") || "[]"); } catch (e) {}
    if (!Array.isArray(ids)) ids = [];
    if (!ids.includes(thread)) ids.push(thread);
    try { Zotero.Prefs.set(this.pref + "codexArchive", JSON.stringify(ids.slice(-50)), true); } catch (e) { this.log("preference not saved: " + e); }
  },

  // each thread leaves the list once Codex archived it or refused it (one it no longer has); once the server does not
  // answer, the rest stay for the next run
  async archiveThreads(rpc) {
    let ids = [];
    try { ids = JSON.parse(this.getPref("codexArchive") || "[]"); } catch (e) {}
    if (!Array.isArray(ids) || !ids.length) return;
    for (const threadId of ids) {
      try { await rpc.request("thread/archive", { threadId }); }
      catch (e) {
        this.log("thread not archived: " + e);
        if (!e || !e.refused) break;
      }
      let left = [];
      try { left = JSON.parse(this.getPref("codexArchive") || "[]"); } catch (e) {}
      left = Array.isArray(left) ? left.filter(id => id !== threadId) : [];
      try { Zotero.Prefs.set(this.pref + "codexArchive", left.length ? JSON.stringify(left) : "", true); } catch (e) {}
    }
  },

  // the zotero-scholium skill as Codex sees it from the working directory; a project skill of the
  // data directory (<data dir>/.agents/skills) is added for this conversation only
  // null when Codex lists no such skill; a request Codex fails, errors in its listing, or the skill switched off end the run
  // with what Codex said
  async codexSkill(rpc, cwd) {
    let failure = null, off = false;
    const issues = [];
    const find = async cwds => {
      try {
        const answer = await rpc.request("skills/list", { cwds });
        for (const entry of (answer && answer.data) || []) {
          for (const e of (entry && entry.errors) || []) issues.push(String((e && (e.message || e.error)) || JSON.stringify(e)));
          for (const s of (entry && entry.skills) || []) {
            if (!s || s.name !== "zotero-scholium" || !s.path) continue;
            if (s.enabled === false) off = true;
            else return s;
          }
        }
      } catch (e) { failure = e; this.log("skills/list failed: " + e); }
      return null;
    };
    let skill = await find([cwd]);
    if (!skill) {
      skill = await find([Zotero.DataDirectory.dir]);
      if (!skill && off) throw new Error(this.text("codexSkillOff"));
      if (!skill && (failure || issues.length)) {
        throw new Error(this.text("codexSkills", failure ? String(failure.message || failure) : [...new Set(issues)].slice(0, 3).join("; ")));
      }
      if (!skill) return null;
      try { await rpc.request("skills/extraRoots/set", { extraRoots: [PathUtils.parent(PathUtils.parent(skill.path))] }); }
      catch (e) { throw new Error(this.text("codexSkills", String(e.message || e))); }
    }
    return { name: skill.name, path: skill.path };
  },

  // what keeps the user's own Codex setup out of a run: their MCP servers, switched off for the thread,
  // and their installed plugins, disabled for its turns; config.toml is neither read nor changed. The servers'
  // names are those Codex listed last (codexServers); only when it never listed them are they listed in the run,
  // for at most CODEX_LIST_MS, else the run goes on with them
  async codexQuiet(rpc) {
    const quiet = { config: null, plugins: [] };
    let names = this.codexServerNames();
    if (!names) {
      try {
        names = await this.within(this.listCodexServers(rpc), this.CODEX_LIST_MS);
        this.keepCodexServers(names);
        this.codexListed = true;
      }
      catch (e) {
        this.log("mcpServerStatus/list failed: " + e);
        this.codexMcp = [];   // for this session; the list after the run may name them
      }
    }
    quiet.listAfter = !this.codexListed;
    if (names && names.length) quiet.config = { mcp_servers: Object.fromEntries(names.map(name => [name, { enabled: false }])) };
    try {
      const installed = await rpc.request("plugin/installed", {});
      for (const market of (installed && installed.marketplaces) || []) {
        for (const plugin of (market && market.plugins) || []) {
          if (plugin && plugin.id && plugin.installed && plugin.enabled) quiet.plugins.push(plugin.id);
        }
      }
    } catch (e) { this.log("plugin/installed failed: " + e); }
    return quiet;
  },

  // the names of the user's MCP servers to switch off: as Codex listed them last (kept as names only), null when it
  // never did
  codexServerNames() {
    if (!this.codexMcp) {
      try {
        const saved = JSON.parse(this.getPref("codexServers") || "null");
        if (Array.isArray(saved)) this.codexMcp = saved.filter(n => typeof n === "string" && n);
      } catch (e) {}
    }
    return this.codexMcp;
  },

  // the user's MCP servers as mcpServerStatus/list names them (it starts each to list its tools): those of config.toml,
  // without Codex's own apps server, the plugins' servers and those a thread refused, which a thread does not take by name
  async listCodexServers(rpc) {
    const names = [];
    let cursor = null;
    for (let page = 0; page < 20; page++) {
      const listed = await rpc.request("mcpServerStatus/list", Object.assign({ detail: "toolsAndAuthOnly" }, cursor ? { cursor } : {}));
      for (const s of (listed && listed.data) || []) {
        if (s && typeof s.name === "string" && s.name && !s.pluginId && s.name !== "codex_apps" && !this.codexRefused.has(s.name)) names.push(s.name);
      }
      cursor = listed && listed.nextCursor;
      if (!cursor) break;
    }
    return names;
  },

  keepCodexServers(names) {
    this.codexMcp = names;
    try { Zotero.Prefs.set(this.pref + "codexServers", JSON.stringify(names), true); } catch (e) { this.log("preference not saved: " + e); }
  },

  // the servers listed again once a Zotero session, after a Codex run, by a server of its own: no run waits for it
  async refreshCodexServers(codex) {
    if (this.codexListed || this.codexRefresh) return;
    this.codexListed = true;   // once, whatever its end
    let rpc = null, timer = null;
    try {
      rpc = this.codexRefresh = await this.codexServer(codex, this.codexRoots()[0]);
      timer = setTimeout(() => rpc.close(), 60000);
      await this.codexHello(rpc);
      this.keepCodexServers(await this.listCodexServers(rpc));
    } catch (e) { this.log("MCP servers not listed: " + e); }
    finally {
      clearTimeout(timer);
      if (rpc) rpc.close();
      this.codexRefresh = null;
    }
  },

  // a promise given up after ms, with the message given or its own
  within(promise, ms, message = "") {
    let timer = null;
    const late = new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error(message || "no answer in " + ms + " ms")), ms); });
    return Promise.race([promise, late]).finally(() => clearTimeout(timer));
  },

  // a thread opened with the user's MCP servers switched off; a name Codex refuses as a server of config.toml (one of its
  // own, or one gone from the file since it was listed) fails the thread's configuration: that server is left out, here
  // and from then on, and the thread opens with the others switched off (with none when the refusal names no server)
  async codexOpen(rpc, method, params) {
    for (;;) {
      try { return await rpc.request(method, params); }
      catch (e) {
        const servers = params.config && params.config.mcp_servers;
        if (!servers || !(e && e.refused) || !/mcp_servers/.test(String(e.message || ""))) throw e;
        this.log("MCP servers not switched off: " + e);
        const named = /mcp_servers\.([^\s`'"]+)/.exec(String(e.message));
        const rest = Object.assign({}, servers);
        if (named && named[1] in rest) {
          delete rest[named[1]];
          this.codexRefused.add(named[1]);
          const names = this.codexServerNames();
          if (names) this.keepCodexServers(names.filter(n => n !== named[1]));
        }
        params = Object.assign({}, params);
        if (named && named[1] in servers && Object.keys(rest).length) params.config = Object.assign({}, params.config, { mcp_servers: rest });
        else delete params.config;
      }
    }
  },

  // where a Codex turn may write: the output folders, the profile folder, and the folder of the local
  // API key that scholium.py keeps (%APPDATA% or ~/.config); it may reach Zotero's local server
  codexRoots() {
    const data = Zotero.DataDirectory.dir;
    const roots = [PathUtils.join(data, "tmp", "scholium"), PathUtils.join(data, "zotero-scholium")];
    const config = this.env("APPDATA") || (this.home() ? PathUtils.join(this.home(), ".config") : "");
    if (config) roots.push(PathUtils.join(config, "zotero-scholium"));
    return roots;
  },

  // Codex's token counts in Claude Code's terms: input without its cached part, cache writes and reads, output
  codexUsage(t) {
    if (!t) return {};
    return { input_tokens: Math.max(0, t.inputTokens - t.cachedInputTokens - t.cacheWriteInputTokens),
             cache_creation_input_tokens: t.cacheWriteInputTokens, cache_read_input_tokens: t.cachedInputTokens, output_tokens: t.outputTokens };
  },

  // when Codex's usage limit resets: the latest reset of a window that is used up; unknown otherwise
  codexReset(limits) {
    const full = [limits && limits.primary, limits && limits.secondary].filter(w => w && w.usedPercent >= 100 && w.resetsAt > 0);
    return full.length ? Math.max(...full.map(w => w.resetsAt * 1000)) : null;
  },

  // Codex: one turn of a conversation through `codex app-server`, in a new thread or in its thread of the
  // paper's conversation, with <data dir>/tmp/scholium as working directory; the turn's end becomes a result
  // in Claude Code's form, so that the log, the state line and a later history read alike
  async runCodex(codex, ctx) {
    const { job, key } = ctx;
    const roots = this.codexRoots();
    for (const root of roots) await IOUtils.makeDirectory(root, { createAncestors: true, ignoreExisting: true });
    const cwd = roots[0];
    const state = { thread: null, turn: null, done: null, text: "", base: null, usage: null, calls: 0, limits: null, timer: null };
    let ended;
    const over = new Promise(resolve => { ended = resolve; });
    const counts = ["inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens"];
    let failure = "";
    const rpc = await this.codexServer(codex, cwd, async messages => {
      const lines = messages.filter(([msg]) => !this.codexNoise(msg)).map(([, raw]) => raw);
      if (lines.length) await this.appendLog(ctx, lines);
      for (const [msg] of messages) {
        const p = msg.params || {};
        const item = p.item || {};
        if (msg.method === "item/completed" && item.type === "agentMessage" && String(item.text || "").trim()) state.text = String(item.text).trim();
        if (msg.method === "thread/tokenUsage/updated" && p.tokenUsage && p.tokenUsage.total) {
          const { total, last } = p.tokenUsage;
          // the thread's totals before this run: the first update's total less its own call
          if (!state.base) state.base = Object.fromEntries(counts.map(k => [k, (Number(total[k]) || 0) - (Number(last && last[k]) || 0)]));
          state.usage = Object.fromEntries(counts.map(k => [k, Math.max(0, (Number(total[k]) || 0) - state.base[k])]));
          state.calls += 1;
        }
        if (msg.method === "account/rateLimits/updated" && p.rateLimits) state.limits = p.rateLimits;
        ctx.running.context = this.contextAfter(msg, ctx.running.context);
        // a write to Zotero, kept with its configuration once its command wrote, in the folder it ran in
        if (msg.method === "item/completed" && item.type === "commandExecution") {
          ctx.missing = this.missingAfter(this.shellCommand(item.command), item.aggregatedOutput, ctx.missing);
          const config = this.appliedConfig(this.shellCommand(item.command));
          if (config && this.wrote(item.aggregatedOutput, item.exitCode === 0 && item.status !== "failed")) {
            ctx.wrote = true;
            await this.noteApplied(key, config, "codex", job.conv, item.cwd || cwd);
          }
        }
        if (msg.method === "turn/completed" && p.turn && (!state.turn || p.turn.id === state.turn)) { state.done = p.turn; delete ctx.current.steer; ended(); }
        // "Reconnecting... 2/5"
        if (msg.method === "error" && p.willRetry) {
          const n = /(\d+)\s*\/\s*(\d+)/.exec(String((p.error && p.error.message) || ""));
          this.reconnecting(ctx, n && n[1], n && n[2]);
        } else if (/^item\//.test(String(msg.method || ""))) this.reconnected(ctx);
        // the message as it is written, until the whole message replaces it
        if (msg.method === "item/agentMessage/delta") this.growDraft(String(p.delta || ""), p.itemId);
        if (msg.method === "item/completed" && item.type === "agentMessage") this.dropDraft();
        this.appendEntries(this.entries(msg));
        if (msg.method === "item/started" && !["userMessage", "agentMessage", "reasoning", "plan", "hookPrompt"].includes(item.type)) ctx.acted = true;
        this.advance(ctx, this.codexStep(msg));
      }
    });
    if (this.job !== ctx.running || ctx.running.stopAsked) {   // the plugin stopped, or ■, while the server was being started
      rpc.close();
      ctx.current = { key, proc: rpc.proc, cancelled: true };
      return;
    }
    rpc.done.then(ended, e => { failure = failure || String((e && e.message) || e); ended(); });
    // cancelling interrupts the turn, so that the conversation records it; the server goes when the
    // turn has ended, or after a few seconds
    const stop = () => {
      if (state.thread && state.turn) rpc.request("turn/interrupt", { threadId: state.thread, turnId: state.turn }).catch(() => {});
      else rpc.close();
      state.timer = setTimeout(() => rpc.close(), 5000);
    };
    this.current = ctx.current = { key, proc: rpc.proc, cancelled: false, stop };
    this.refresh();
    try {
      await this.codexHello(rpc);
      if (await this.codexSignedOut(rpc)) throw new Error(this.text("notSignedIn", "codex"));
      await this.archiveThreads(rpc);
      const model = this.modelPref("codex");
      const settings = { cwd, approvalPolicy: "on-request", approvalsReviewer: "auto_review", sandbox: "workspace-write",
                         serviceName: "scholium" };
      if (model) settings.model = model;
      const quiet = await this.codexQuiet(rpc);
      state.listAfter = quiet.listAfter;
      if (quiet.config) settings.config = quiet.config;
      const skill = job.resume ? null : await this.codexSkill(rpc, cwd);
      if (!job.resume && !skill) {
        ctx.noSkill = "codex";
        throw new Error(this.text("noSkill", "codex"));
      }
      // the pre-run's results are the agent's only when they came from the skill copy Codex uses; else it runs them itself
      if (skill && job.pre && job.pre.script && !this.sameDir(PathUtils.parent(PathUtils.parent(job.pre.script)), PathUtils.parent(skill.path))) job.pre = null;
      let opened = null;
      if (job.resume) {
        // a thread that Codex refuses to resume is one it no longer has: a new one goes on with the conversation; an
        // edited question forks the thread through the turn before it, and a refused fork does the same
        // the turns stay with the server: a long conversation is not sent back whole
        const fork = job.rewind && job.rewind.turnId;
        try {
          opened = fork ? await this.codexOpen(rpc, "thread/fork", Object.assign({ threadId: job.resume, lastTurnId: fork, excludeTurns: true }, settings))
                        : await this.codexOpen(rpc, "thread/resume", Object.assign({ threadId: job.resume, excludeTurns: true }, settings));
        }
        catch (e) { ctx.gone = !!(e && e.refused); throw e; }
      } else {
        opened = await this.codexOpen(rpc, "thread/start", settings);
        if (!model && opened) this.noteCodexDefault(String(opened.model || ""));
      }
      const thread = opened && opened.thread && opened.thread.id;
      if (!thread) throw new Error(this.text("noThread"));
      state.thread = ctx.session = ctx.running.session = thread;
      // the start of a run, as Claude Code's log has it: the model and the conversation
      const init = { type: "system", subtype: "init", agent: "codex", model: (opened && opened.model) || model, session_id: thread };
      await this.appendLog(ctx, [JSON.stringify(init)]);
      this.appendEntries(this.entries(init));
      // a new thread of a conversation is given its turns as items of the thread when all the answers are Codex's own, or
      // as text before the message, each answer with its agent, when another agent gave one or Codex does not take items
      let asText = true;
      if (!job.resume && job.history && job.history.length && job.history.every(t => t.agent === "codex")) {
        try {
          await rpc.request("thread/inject_items", { threadId: thread, items: this.historyItems(job.history) });
          asText = false;
        } catch (e) { this.log("history not injected: " + e); }
      }
      // a compaction is a request of its own: it runs as a turn, whose end ends the run
      if (job.compact) {
        state.before = (ctx.running.context && ctx.running.context.used) || 0;
        if (!ctx.current.cancelled) {
          await rpc.request("thread/compact/start", { threadId: thread });
          ctx.running.delivered = true;
          if (ctx.current.cancelled) stop();
          await over;
        }
      } else {
        const input = [{ type: "text", text: this.prompt(job, job.own, asText), text_elements: [] }];
        if (skill) input.push({ type: "skill", name: skill.name, path: skill.path });
        const params = { threadId: thread, input, sandboxPolicy: { type: "workspaceWrite", writableRoots: roots, networkAccess: true,
                                                                   excludeTmpdirEnvVar: false, excludeSlashTmp: false } };
        if (model) params.model = model;
        if (quiet.plugins.length) params.disabledPluginIds = quiet.plugins;
        const effort = this.effort("codex");
        if (effort) params.effort = effort;
        if (!ctx.current.cancelled) {
          const begun = await rpc.request("turn/start", params);
          state.turn = (begun && begun.turn && begun.turn.id) || null;
          ctx.current.steer = async text => {
            await rpc.request("turn/steer", { threadId: thread, expectedTurnId: state.turn, input: [{ type: "text", text, text_elements: [] }] });
          };
          this.deliver(ctx);   // the turn has the prompt
          if (ctx.current.cancelled) stop();
          await over;
        }
      }
    } catch (e) {
      failure = String((e && e.message) || e);
      this.log("codex run failed: " + failure);
    } finally {
      clearTimeout(state.timer);
      rpc.close();
      await rpc.done.catch(() => {});
      // the servers named from an earlier session, or not at all: listed again now, off the run's path
      if (state.listAfter && this.job === ctx.running) this.refreshCodexServers(codex).catch(e => this.log("MCP servers not listed: " + e));
    }
    const turn = state.done;
    if (!turn || ctx.current.cancelled) {
      ctx.exitCode = turn ? 0 : (await rpc.proc.wait()).exitCode || 1;
      ctx.stderr = failure || rpc.stderr;
      return;
    }
    const failed = turn.status !== "completed";
    const error = turn.error || {};
    ctx.errorInfo = error.codexErrorInfo || null;
    if (failed && (error.codexErrorInfo === "usageLimitExceeded" || error.codexErrorInfo === "rateLimitExceeded")) {
      ctx.limit = { until: this.codexReset(state.limits) };
    }
    ctx.result = { type: "result", agent: "codex", subtype: failed ? "error_during_execution" : "success", is_error: failed,
                   result: failed ? String(error.message || turn.status) : state.text, session_id: state.thread,
                   duration_ms: turn.durationMs > 0 ? turn.durationMs : Date.now() - ctx.running.started, num_turns: state.calls,
                   usage: this.codexUsage(state.usage) };
    const unfinished = this.unfinished();   // what the turn showed of a message it did not finish, before its end
    await this.appendLog(ctx, (unfinished ? [JSON.stringify(unfinished)] : []).concat(JSON.stringify(ctx.result)));
    if (unfinished) this.appendEntries(this.entries(unfinished));
    this.appendEntries(this.entries(ctx.result));
    // the sizes before and after the compaction, as the plugin's own line
    if (job.compact && !failed) {
      const after = ctx.running.context && ctx.running.context.used;
      const mark = { type: "scholium", subtype: "compacted", pre: state.before || 0, post: after && after !== state.before ? after : 0 };
      await this.appendLog(ctx, [JSON.stringify(mark)]);
      ctx.compacted = this.entries(mark)[0];
      this.appendEntries([ctx.compacted]);
    }
    ctx.exitCode = 0;
  },

  // Codex has no account although its provider needs one; a server that cannot say counts as signed in. Only whether
  // there is an account is looked at
  async codexSignedOut(rpc) {
    try { return this.codexNoAccount(await rpc.request("account/read", {})); } catch (e) { return false; }
  },

  // account/read's answer: no account although the provider needs one
  codexNoAccount(r) {
    return !!r && r.account === null && r.requiresOpenaiAuth === true;
  },

  // stops the run under way; one still starting, before its agent's process, stops at its next step (run)
  cancel() {
    const current = this.current;
    if (!current) {
      if (this.job) this.job.stopAsked = true;
      return !!this.job;
    }
    current.cancelled = true;
    try { if (current.stop) current.stop(); else current.proc.kill(); } catch (e) {}
    return true;
  },

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
    const busy = new Set(this.queue.filter(j => !this.isHeld(j)).map(j => j.att).concat(this.job ? [this.attOf(this.job.libraryID, this.job.key)] : [])
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
             margin: own.filter(a => a.annotationType === "text").length, notes: own.filter(a => a.annotationType === "note").length, readingNotes };
  },

  // the core colour of the configuration the paper was written with last; Zotero's red without one
  async coreColor(key) {
    const applied = await this.readApplied(key);
    try {
      const c = applied && JSON.parse(await IOUtils.readUTF8(applied.config)).core_color;
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
    const busy = new Set(this.queue.filter(j => !this.isHeld(j)).map(j => this.keyOf(j.att)).concat(this.job ? [this.job.key] : []));
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

  // `update`: this copy may replace another (an update or a downgrade), which may hand papers over (carryOver); at
  // Zotero's start a hand-over that no copy took is dropped
  start(pluginID, update = false) {
    this.pluginID = pluginID;
    this.stopped = false;
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
  carryOver(running) {
    const plain = j => ({ key: j.att.key, libraryID: j.att.libraryID, agent: j.agent, extra: j.extra || "", say: j.say || "",
                          resume: j.resume || null, asked: !!j.asked, question: !!j.question, annotate: !!j.annotate, own: j.own || 0,
                          interrupted: !!j.interrupted, updated: !!j.updated, fresh: !!j.fresh, conv: j.conv || null, asking: !!j.asking,
                          logged: !!j.logged, throttled: !!j.throttled, retried: !!j.retried, retryAt: j.retryAt || 0, kind: j.kind || "chat",
                          compact: !!j.compact, qid: j.qid || null, failed: !!j.failed, quote: j.quote || null, rewind: j.rewind || null,
                          turnAt: Number.isInteger(j.turnAt) ? j.turnAt : null, leftAt: this.leftOf(j.leftAt),
                          papers: Array.isArray(j.papers) ? j.papers : null });
    const jobs = [];
    if (running && running.source) {
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
    // each agent's pause: { <agent>: { until, known, throttled } }
    const paused = this.paused ? Object.fromEntries(Object.entries(this.paused).map(([a, p]) => [a, { until: p.until, known: p.known, throttled: !!p.throttled }])) : null;
    try { if (jobs.length) Zotero.Prefs.set(this.pref + "carryOver", JSON.stringify({ jobs, paused, held: [...this.heldQueues] }), true); }
    catch (e) { this.log("queue not kept: " + e); }
  },

  // the papers an update interrupted (carryOver), queued again once
  async restoreQueue() {
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
      if (!job || (!qid && (this.busy(this.keyOf(job.att), kind) || jobs.some(j => !j.qid && this.keyOf(j.att) === this.keyOf(job.att) && j.kind === kind)))) continue;
      const agent = s.agent === "codex" ? "codex" : "claude";
      Object.assign(job, { agent, extra: String(s.extra || ""), say: String(s.say || ""), resume: s.resume || null, asked: !!s.asked,
                           question: !!s.question, annotate: !!s.annotate, own: Number(s.own) || 0, updated: !!s.updated, fresh: !!s.fresh,
                           conv: typeof s.conv === "string" && s.conv ? s.conv : null, asking: !!(s.asking || s.question),
                           logged: !!s.logged, interrupted: !!s.interrupted, throttled: !!s.throttled, retried: !!s.retried,
                           retryAt: Number(s.retryAt) || 0, kind, compact: !!s.compact, qid, failed: !!(qid && s.failed),
                           quote: this.quoteOf(s.quote), rewind: this.pointOf(s.rewind),
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
    const running = this.job;
    if (running && running.log) {
      const mark = { type: "scholium", subtype: "end", outcome: "interrupted", text: this.text("interruptedLine"),
                     duration_ms: Date.now() - running.started };
      IOUtils.writeUTF8(running.log, JSON.stringify(mark) + "\n", { mode: "append" }).catch(() => {});
    }
    // a conversation deleted a moment ago goes now, as it would have, its queued messages first: they are not handed over
    for (const path of [...this.deleting.keys()]) this.finishDelete(path).catch(() => {});
    if (update) this.carryOver(running);
    clearTimeout(this.restoreTimer);
    if (this.editor) this.closeProfile(this.editor, false);
    for (const agent of this.AGENTS) this.endPause(agent);
    this.paused = null;
    this.queue = [];
    for (const r of this.removedQueued.values()) clearTimeout(r.timer);
    this.removedQueued.clear();
    // an edit's old conversation can no longer come back: the threads only it used are archived
    for (const r of this.replaced.values()) {
      clearTimeout(r.timer);
      try { this.archiveReplaced(r); } catch (e) {}
    }
    this.replaced.clear();
    if (this.savedRemoved) clearTimeout(this.savedRemoved.timer);
    this.savedRemoved = null;
    this.heldQueues.clear();
    this.qseq = 0;
    this.cancel();
    try { if (this.current) this.current.proc.kill(); } catch (e) {}   // without waiting for Codex to end its turn
    clearTimeout(this.draftTimer);
    this.draft = this.draftTimer = null;
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
    this.job = null;
  },
});
