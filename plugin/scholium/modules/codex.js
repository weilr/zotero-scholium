// ScholiumRunner, continued: Codex: its app-server, threads and their archiving, the skill, MCP servers, usage
// limits and a run

Object.assign(ScholiumRunner, {
  // `codex app-server`: JSON-RPC over stdin and stdout, one message per line. Answers settle their
  // requests, questions from Codex are answered by codexAnswer, and everything else goes to
  // onMessage([[message, line], …]) a chunk at a time.
  async codexServer(codex, workdir, onMessage = null, more = {}) {
    const env = await this.agentEnv(true);
    Object.assign(env.environment, more);   // a run's (runEnv)
    const proc = await this.subprocess().call(Object.assign({
      command: codex, arguments: ["app-server"], workdir, stderr: "pipe",
    }, env));
    const rpc = { proc, next: 1, pending: new Map(), stderr: "" };
    const send = msg => proc.stdin.write(JSON.stringify(msg) + "\n");
    rpc.request = (method, params) => new Promise((resolve, reject) => {
      // a server that has ended answers nothing more
      if (rpc.ended) { reject(rpc.ended); return; }
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
                if (msg.error) waiting.reject(Object.assign(new Error(String(msg.error.message || JSON.stringify(msg.error))),
                                                           { refused: true, code: msg.error.code, data: msg.error.data }));
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
        rpc.ended = failure || new Error(this.text("codexExited", tail));
        for (const waiting of rpc.pending.values()) waiting.reject(rpc.ended);
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

  // Only an explicitly missing session (or a fork point/API the server cannot use) needs history replay.
  // Permission, configuration and temporary RPC failures leave the original session available for another try.
  codexResumeGone(error, fork) {
    if (!error || !error.refused) return false;
    const message = String(error.message || "");
    if (/no rollout found for thread|\bthread not found(?:\s*:|\s*$)|\b(?:thread|session) \S+ is archived\b|\brollout file (?:does not exist|not found)\b/i.test(message)
        || /failed to resolve rollout path [^\r\n]+: file does not exist\b/i.test(message)) return true;
    return !!fork && (error.code === -32601
      || /\bturn not found:|\blastTurnId '[^']+' (?:was not found|is not a persisted canonical turn) in the source thread\b|\b(?:unknown|unsupported) method ["'`]?thread\/fork\b/i.test(message));
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

  // a thread archived after its last run, back for this one; one that is not archived Codex refuses, and it goes on
  async codexUnarchive(rpc, threadId) {
    try { await rpc.request("thread/unarchive", { threadId }); }
    catch (e) { if (!(e && e.refused)) throw e; }
  },

  // the threads of a run archived as it ends, so that the Codex app does not list them; those Codex did not answer for
  // (it ended, or took too long) wait for the next run (queueArchive); one it refuses (gone, archived) is left
  async codexArchiveNow(rpc, ids) {
    for (const threadId of ids) {
      try { await this.within(rpc.request("thread/archive", { threadId }), this.ARCHIVE_MS); }
      catch (e) {
        if (e && e.refused) this.log("thread not archived: " + e);
        else this.queueArchive(threadId);
      }
    }
  },

  // once: the Codex threads the logs of the plugin's conversations name, which runs before this version left in the Codex
  // app's list, archived but for those of runs going on; when Codex stops answering, the next run goes on with it
  async archiveOldThreads(rpc) {
    if (this.getPref("codexArchivedOld")) return;
    const busy = new Set([...this.runs.values()].filter(r => !r.gone && r.agent === "codex" && r.session).map(r => r.session));
    const ids = new Set();
    for (const paper of await this.children(PathUtils.join(this.root(), "papers"))) {
      const logs = (await this.children(PathUtils.join(paper, "conversations"))).concat(await this.children(paper));
      for (const path of logs) {
        if (!/\.jsonl$/.test(path)) continue;
        try { for (const id of this.codexThreads(await IOUtils.readUTF8(path))) if (!busy.has(id)) ids.add(id); } catch (e) {}
      }
    }
    for (const threadId of ids) {
      try { await this.within(rpc.request("thread/archive", { threadId }), this.ARCHIVE_MS); }
      catch (e) { if (!(e && e.refused)) throw e; }
    }
    try { Zotero.Prefs.set(this.pref + "codexArchivedOld", "1", true); } catch (e) { this.log("preference not saved: " + e); }
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

  // where a Codex turn may write: the plugin's folder (records, profile, working directories), and the folder of the local
  // API key that scholium.py keeps (%APPDATA% or ~/.config); it may reach Zotero's local server
  codexRoots() {
    const roots = [this.root()];
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
  // paper's conversation, in the conversation's own folder (workDir); the turn's end becomes a result
  // in Claude Code's form, so that the log, the state line and a later history read alike
  async runCodex(codex, ctx) {
    const { job, key } = ctx;
    const roots = this.codexRoots();
    for (const root of roots) await IOUtils.makeDirectory(root, { createAncestors: true, ignoreExisting: true });
    const cwd = this.workDir(key, job.conv);
    await IOUtils.makeDirectory(cwd, { createAncestors: true, ignoreExisting: true });
    // the Codex home folder of the settings must be there: Codex would make an empty one, signed in to nothing
    const home = this.codexHome();
    if (home && !(await this.isFolder(home))) {
      ctx.current = { key, proc: null, cancelled: false };
      ctx.exitCode = 1;
      ctx.failure = this.text("codexHomeMissing", home);
      return;
    }
    const state = { thread: null, turn: null, done: null, text: "", base: null, usage: null, calls: 0, limits: null, timer: null,
                    used: new Set() };   // the threads the run opened, archived when it ends
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
        if (msg.method === "item/agentMessage/delta") this.growDraft(ctx.running, String(p.delta || ""), p.itemId);
        if (msg.method === "item/completed" && item.type === "agentMessage") this.dropDraft(ctx.running);
        this.appendEntries(ctx.running, this.entries(msg));
        if (msg.method === "item/started" && !["userMessage", "agentMessage", "reasoning", "plan", "hookPrompt"].includes(item.type)) ctx.acted = true;
        this.advance(ctx, this.codexStep(msg));
      }
    }, this.runEnv(ctx));
    if (!this.alive(ctx.running) || ctx.running.stopAsked) {   // the plugin stopped, or ■, while the server was being started
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
    ctx.running.current = ctx.current = { key, proc: rpc.proc, cancelled: false, stop };
    this.refresh();
    try {
      await this.codexHello(rpc);
      if (await this.codexSignedOut(rpc)) throw new Error(this.codexLogin(this.text("notSignedIn", "codex")));
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
        // a missing thread is rebuilt with the conversation; an edited question forks through the turn before it
        // the turns stay with the server: a long conversation is not sent back whole
        const fork = job.rewind && job.rewind.turnId;
        try {
          // the thread was archived after its last run: it comes back for this one
          await this.codexUnarchive(rpc, job.resume);
          state.used.add(job.resume);
          opened = fork ? await this.codexOpen(rpc, "thread/fork", Object.assign({ threadId: job.resume, lastTurnId: fork, excludeTurns: true }, settings))
                        : await this.codexOpen(rpc, "thread/resume", Object.assign({ threadId: job.resume, excludeTurns: true }, settings));
        }
        catch (e) { ctx.gone = this.codexResumeGone(e, fork); throw e; }
      } else {
        opened = await this.codexOpen(rpc, "thread/start", settings);
        if (!model && opened) this.noteCodexDefault(String(opened.model || ""));
      }
      const thread = opened && opened.thread && opened.thread.id;
      if (!thread) throw new Error(this.text("noThread"));
      state.used.add(thread);
      state.thread = ctx.session = ctx.running.session = thread;
      // the start of a run, as Claude Code's log has it: the model and the conversation
      const init = { type: "system", subtype: "init", agent: "codex", model: (opened && opened.model) || model, session_id: thread };
      await this.appendLog(ctx, [JSON.stringify(init)]);
      this.appendEntries(ctx.running, this.entries(init));
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
      ctx.errorInfo = e && e.data && e.data.codexErrorInfo || null;
      this.log("codex run failed: " + failure);
    } finally {
      clearTimeout(state.timer);
      // the run's threads leave the Codex app's list, and once, those of earlier versions' runs
      if (state.used.size) await this.codexArchiveNow(rpc, [...state.used]);
      await this.archiveOldThreads(rpc).catch(e => this.log("old threads not archived: " + e));
      rpc.close();
      await rpc.done.catch(() => {});
      // the servers named from an earlier session, or not at all: listed again now, off the run's path
      if (state.listAfter && this.alive(ctx.running)) this.refreshCodexServers(codex).catch(e => this.log("MCP servers not listed: " + e));
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
    const unfinished = this.unfinished(ctx.running);   // what the turn showed of a message it did not finish, before its end
    await this.appendLog(ctx, (unfinished ? [JSON.stringify(unfinished)] : []).concat(JSON.stringify(ctx.result)));
    if (unfinished) this.appendEntries(ctx.running, this.entries(unfinished));
    this.appendEntries(ctx.running, this.entries(ctx.result));
    // the sizes before and after the compaction, as the plugin's own line
    if (job.compact && !failed) {
      const after = ctx.running.context && ctx.running.context.used;
      const mark = { type: "scholium", subtype: "compacted", pre: state.before || 0, post: after && after !== state.before ? after : 0 };
      await this.appendLog(ctx, [JSON.stringify(mark)]);
      ctx.compacted = this.entries(mark)[0];
      this.appendEntries(ctx.running, [ctx.compacted]);
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
});
