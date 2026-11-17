// ScholiumRunner, continued: the plugin's own first steps of a run (the skill's extract), and what the skill's
// script held back and the user confirmed

Object.assign(ScholiumRunner, {
  // the skill's script as the agent runs it, for the plugin's own first steps (preRun, preRunQuestion): with the command
  // its prompt names (scriptProgram), the agent's environment, in a paper's output folder, within a time; the process is
  // the run's current one, which ■ kills. null after ■ or a stop, and once one came while the process was being created
  preRunner(job, ctx, script, env) {
    const runner = job.scriptRun || {}, running = ctx.running, key = ctx.key;
    return async (args, ms, workdir) => {
      if (running.stopAsked || !this.alive(running)) return null;
      const proc = await this.subprocess().call(Object.assign({ command: runner.command, arguments: runner.prefix.concat([script], args),
                                                                 workdir }, env));
      if (running.stopAsked || !this.alive(running)) {   // the plugin stopped, or ■, while the process was being created
        try { proc.kill(); } catch (e) {}
        ctx.current = { key, proc, cancelled: true };
        return null;
      }
      running.current = ctx.current = { key, proc, cancelled: false };
      try { return await this.readOutput(proc, ms); }
      finally { running.current = null; }
    };
  },

  // `extract` of a paper (its key of keyOf) into its output folder by a preRunner: { lines (of sentences.txt), main (its
  // index's main text lines [first, last], when the index gives them) }; { scanned } for a PDF without a text layer (exit
  // code 3); { cancelled } after ■; null when it failed or did not end in time
  // Another run of the paper that extracts it now: this one waits for that extract and takes what it wrote.
  async preExtract(run, ctx, k, ms) {
    const out = this.outDir(k), txt = PathUtils.join(out, "sentences.txt");
    const lines = async () => {
      const text = await IOUtils.readUTF8(txt);
      const main = /^main text: lines (\d+)-(\d+)\r?$/m.exec(text.slice(0, 4000));
      return Object.assign({ lines: text.split(/\r?\n/).length - (/\n$/.test(text) ? 1 : 0) },
                           main ? { main: [Number(main[1]), Number(main[2])] } : {});
    };
    const other = this.extracting.get(k);
    if (other) {
      await other.catch(() => null);
      if (await this.exists(txt)) return lines();
    }
    const mine = (async () => {
      const extract = await run(["extract", "--config", this.paperPath(k), "--sentences", PathUtils.join(out, "sentences.json"), "--out", txt],
                                ms, out);
      if (ctx.current && ctx.current.cancelled) return { cancelled: true };
      if (!extract || extract.late) return null;
      if (extract.exitCode === 3) return { scanned: true };
      if (extract.exitCode !== 0) return null;
      return lines();
    })();
    this.extracting.set(k, mine);
    try { return await mine; }
    finally { if (this.extracting.get(k) === mine) this.extracting.delete(k); }
  },

  // an annotation's first steps, run by the plugin before the agent starts, by the skill's script the agent runs
  // (skillScript, preRunner): `status <item key> [--group ID]` within PRE_STATUS_MS, then `extract` within PRE_EXTRACT_MS.
  // { status (its JSON, minified), lines (of sentences.txt), main, script } when both ran; { scanned } for a PDF without a text
  // layer; { cancelled } after ■; null otherwise, and the agent runs them itself. The live line says the PDF is read
  async preRun(job, ctx) {
    const script = job.scriptRun && job.scriptRun.command ? await this.skillScript(job.agent) : null;
    if (!script) return null;
    const key = this.keyOf(job.att), running = ctx.running;
    const run = this.preRunner(job, ctx, script, await this.agentEnv(job.agent === "codex"));
    const group = this.groupOf(job.att.libraryID);
    running.preRun = true;
    this.refresh();
    this.settleRun(running);
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
      return Object.assign({ status: json, lines: extract.lines, script }, extract.main ? { main: extract.main } : {});
    } catch (e) {
      this.log("pre-run failed: " + e);
      return null;
    } finally {
      running.preRun = false;
      this.refresh();
      this.settleRun(running);
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
    if (!script || !this.alive(running)) return null;
    const run = this.preRunner(job, ctx, script, await this.agentEnv(job.agent === "codex"));
    const until = Date.now() + this.PRE_EXTRACT_MS;
    let pre = null;
    running.preRun = true;
    this.refresh();
    this.settleRun(running);
    try {
      for (const f of papers) {
        const left = until - Date.now();
        if (left < 1000 || running.stopAsked || !this.alive(running)) break;   // the rest are the agent's
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
      this.settleRun(running);
    }
  },

  // a scanned PDF found by the pre-run: the run ends as an agent's does that found it, with the card that says so
  scannedEnd(ctx) {
    ctx.current = { key: ctx.key, proc: null, cancelled: false };
    ctx.exitCode = 0;
    ctx.missing = "noTextLayer";
    ctx.result = { type: "result", subtype: "success", is_error: false, result: this.text("noTextLayer"), num_turns: 0 };
  },

  // the skill's script refuses --accept user_edit and cleanup_other unless the user clicked the current report's action
  // for those annotations and notes (heldBack), or by Annotate again, for
  // the tool's annotations that its deletion first left (taskPrompt's one exception). { kind: [keys] }
  confirmedFor(job, key) {
    const kinds = {};
    if (job.annotate && job.own > 0) kinds.cleanup_other = job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).map(a => a.key);
    const held = job.conv ? this.heldBack.get(`${key}/${job.conv}`) : null;
    const confirmation = job.confirmation;
    if (held && confirmation && held.confirmation === confirmation && confirmation.held === held
        && confirmation.keys === JSON.stringify(held.keys) && confirmation.job === job
        && confirmation.key === key && confirmation.conv === job.conv && confirmation.kind === (job.kind || "chat")
        && job.say && !job.compact && !job.annotate
        && (job.sentSeq || 0) > held.seq) {
      for (const [kind, keys] of Object.entries(held.keys)) kinds[kind] = [...new Set((kinds[kind] || []).concat(keys))];
      job.confirmedHeld = held;
    }
    return kinds;
  },

  // what a conversation's runs hold back, one file per conversation: runs of a paper at once do not share it
  heldPath(key, conv = null) { return PathUtils.join(this.outDir(key), conv ? `held_back-${conv}.json` : "held_back.json"); },

  // What the script held back belongs to this report. A button can approve it once, and new ordinary words discard it.
  async keepHeld(ctx) {
    const { job, key } = ctx;
    let held = null;
    const path = this.heldPath(key, job.conv);
    if (await this.exists(path)) {
      try { held = JSON.parse(await IOUtils.readUTF8(path)); } catch (e) {}
      await IOUtils.remove(path, { ignoreAbsent: true }).catch(() => {});
    }
    const keys = {};
    for (const kind of ["user_edit", "cleanup_other"]) {
      const list = held && Array.isArray(held[kind]) ? held[kind].filter(k => typeof k === "string" && k) : [];
      if (list.length) keys[kind] = list;
    }
    const at = `${key}/${job.conv}`;
    if (job.conv && Object.keys(keys).length) this.heldBack.set(at, { keys, seq: this.sendSeq });
    else if (job.confirmedHeld && this.heldBack.get(at) === job.confirmedHeld) this.heldBack.delete(at);
  },
});
