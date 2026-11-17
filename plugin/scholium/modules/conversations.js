// ScholiumRunner, continued: conversations, their files and logs, the history as text, showing a conversation,
// switching the agent and a new chat

Object.assign(ScholiumRunner, {
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
    await this.settled();
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
    await this.settled();
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
    await this.settled();
    const path = this.convPath(key, id);
    const pending = this.pendingLogs.get(path);
    if (pending && pending.flushing) await pending.flushing;
    const tail = pending && pending.unlogged.length ? pending.unlogged.join("\n") + "\n" : "";
    let stat = null;
    try { stat = await IOUtils.stat(path); } catch (e) { return null; }
    // a conversation that goes on appends to its log, so an unchanged one (same time and size) is not parsed again; the
    // sections that ask for it at once share one reading
    let cached = this.parsedLogs.get(path);
    if (!cached || cached.at !== stat.lastModified || cached.size !== stat.size || cached.tail !== tail) {
      cached = { at: stat.lastModified, size: stat.size, tail, log: this.parseLog(path, this.convAgent(id), tail) };
      this.parsedLogs.delete(path);
      this.parsedLogs.set(path, cached);
      if (this.parsedLogs.size > 20) this.parsedLogs.delete(this.parsedLogs.keys().next().value);   // the oldest
    }
    const log = await cached.log;
    const remaining = this.pendingLogs.get(path);
    const currentTail = remaining && remaining.unlogged.length ? remaining.unlogged.join("\n") + "\n" : "";
    if (currentTail !== tail) {
      this.parsedLogs.delete(path);
      return this.readLog(key, id);
    }
    if (!log) {
      if (this.parsedLogs.get(path) === cached) this.parsedLogs.delete(path);
      return null;
    }
    const copy = a => Object.assign({}, a, { context: a.context && Object.assign({}, a.context) });
    const turns = log.turns.map(t => Object.assign({}, t, { points: Object.assign({}, t.points), sessions: Object.assign({}, t.sessions) }));
    return { entries: log.entries.slice(), turns,
             result: log.result, question: log.question, agents: { claude: copy(log.agents.claude), codex: copy(log.agents.codex) },
             papers: (log.papers || []).map(r => Object.assign({}, r)), cwds: Object.assign({}, log.cwds), path, id };
  },

  // what readLog gives of a log, read once; null when it cannot be read. agent: whose the runs of a log without run
  // lines are (a log of an earlier version)
  async parseLog(path, agent = "claude", tail = "") {
    let text;
    try { text = await IOUtils.readUTF8(path); } catch (e) { return null; }
    text += tail;
    const entries = [], turns = [];
    const own = a => (a === "claude" || a === "codex" ? a : null);
    // each agent's own session of the conversation: the session, the last turn it saw (-1: none), the point an edited
    // question takes it back to (Claude Code's last message, Codex's last turn), the point its next run goes back to until
    // the session moves on, the context the session took up, when its latest run that did its work started and ended
    // (lastEnd Infinity: the log ends with that run, cut short without its end), and the first turn it saw that another
    // agent answered again since (Infinity: none)
    const blank = () => ({ session: null, through: -1, point: null, rewind: null, context: null, lastAt: 0, lastEnd: 0, stale: Infinity });
    const agents = { claude: blank(), codex: blank() };
    const cwds = {};   // the folder each session started in, as its start line names it
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
      if (event.type === "system" && event.subtype === "init" && typeof event.session_id === "string" && typeof event.cwd === "string"
          && event.cwd && !cwds[event.session_id]) cwds[event.session_id] = event.cwd;
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
                        context: a.context, lastAt: a.lastAt, lastEnd: a.lastEnd, stale: a.stale === Infinity ? null : a.stale,
                        cwd: (a.session && cwds[a.session]) || null });
    return { entries: entries.slice(-this.MAX_ENTRIES), turns, result, question, agents: { claude: out(agents.claude), codex: out(agents.codex) },
             papers: papers || [], cwds };
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

  // A bounded handoff, shared by new sessions and missed exchanges. Keep recent whole turns first, then as many
  // earlier excerpts as fit. from is the number of turns before these; the local log is never changed.
  historyParts(turns, from = 0) {
    const zh = this.zh();
    const answer = t => t.reply || (t.done ? (zh ? "（没有文字回答）" : "(no text)")
      : zh ? `（没有完成${t.ended ? "：" + this.cut(t.ended, 300) : ""}）` : `(not finished${t.ended ? ": " + this.cut(t.ended, 300) : ""})`);
    const clip = (s, n, tail = false) => {
      s = String(s || "");
      if (!tail || s.length <= n) return this.cut(s, n);
      const head = this.cut(s, Math.ceil(n / 2));
      let start = s.length - (n - head.length);
      const c = s.charCodeAt(start);
      if (c >= 0xdc00 && c <= 0xdfff) start++;   // keep both ends without splitting a surrogate pair
      return head + s.slice(start);
    };
    const user = (t, n = Infinity, tail = false) => {
      const full = (t.quote ? this.quoteTag(t.quote) : "") + String(t.user || "");
      if (full.length <= n) return full;
      // Quotes have their own allowance and are wrapped after clipping, so they cannot hide the question or lose
      // their closing quote. A very long recent question retains its beginning and end.
      const quote = t.quote ? this.quoteTag(Object.assign({}, t.quote, { page: this.cut(t.quote.page, 80),
        text: clip(t.quote.text, Math.floor(n / 3), tail) })) : "";
      return quote + clip(t.user, Math.max(1, n - quote.length), tail);
    };
    const part = i => ({ n: turns[i].n || from + i + 1, user: user(turns[i]), answer: answer(turns[i]), agent: turns[i].agent });
    const size = t => Math.max(this.turnLines({ whole: [t] })[0].length + 2,
      JSON.stringify([this.historyMessage("user", t.user), this.historyMessage("assistant", t.answer)]).length + 1);
    // Covers the larger missedText header/footer, excerpt heading/omission notice, and the items' acknowledgment.
    let left = this.HISTORY_MAX_CHARS - 1024, i = turns.length - 1, shortened = false;
    const whole = [], early = [], recent = turns.length > this.HISTORY_FROM ? turns.length - this.HISTORY_WHOLE : 0;
    for (; i >= recent; i--) {
      let t = part(i), cost = size(t);
      if (cost > left) {
        if (whole.length) break;
        // Even a single exchange can exceed the budget. Clip its fields together, measuring JSON escaping too.
        let limit = Math.floor(left / 2);
        do {
          t = Object.assign({}, t, { user: user(turns[i], limit, true), answer: clip(answer(turns[i]), limit, true) });
          cost = size(t);
          limit = Math.floor(limit * 0.8);
        } while (cost > left);
        shortened = true;
      }
      whole.push(t);
      left -= cost;
    }
    for (; i >= 0; i--) {
      const t = turns[i], u = user(t, this.EXCERPT_USER), a = this.cut(answer(t), this.EXCERPT_ANSWER);
      const line = zh ? `用户：${u}\n回答（${this.agentName(t.agent)}）：${a}`
                      : `User: ${u}\nAnswer (${this.agentName(t.agent)}): ${a}`;
      const cost = JSON.stringify(line).length + 4;
      if (cost > left) break;
      early.push(line);
      left -= cost;
    }
    const summary = [];
    if (i >= 0 || shortened) {
      summary.push(zh ? `交接长度受限：${i >= 0 ? `已省略 ${i + 1} 轮较早对话` : "超长轮次的部分内容已省略"}${i >= 0 && shortened ? "，并截短了超长轮次" : ""}。需要完整内容时，请回看 Zotero 中这段对话的本地完整记录。`
                      : `Handoff length is limited: ${i >= 0 ? `${i + 1} earlier exchanges were omitted` : "part of an oversized exchange was omitted"}${i >= 0 && shortened ? "; an oversized exchange was also shortened" : ""}. Consult this conversation's full local history in Zotero when needed.`);
    }
    if (early.length) summary.push(zh ? `之前的 ${early.length} 轮对话（摘录）：` : `Earlier conversation (${early.length} exchanges):`, ...early.reverse());
    return { summary: summary.join("\n\n"), whole: whole.reverse() };
  },

  historyMessage(role, text) {
    return { type: "message", role, content: [{ type: role === "user" ? "input_text" : "output_text", text: text || "[Empty message]" }] };
  },

  // Codex: the conversation as items of the new thread
  historyItems(turns) {
    if (!turns.length) return [];
    const zh = this.zh();
    const { summary, whole } = this.historyParts(turns);
    const items = [];
    if (summary) items.push(this.historyMessage("user", summary), this.historyMessage("assistant", zh ? "明白，我已了解之前的对话。" : "Understood. I have the earlier conversation context."));
    for (const t of whole) items.push(this.historyMessage("user", t.user), this.historyMessage("assistant", t.answer));
    return items;
  },

  // Claude Code, and Codex when it does not take items: the conversation as text before the message
  historyText(turns) {
    if (!turns.length) return "";
    const zh = this.zh();
    return [
      zh ? "下面是这段对话之前的内容（Zotero 里保存的记录），每轮注明是谁回答的；轮次编号用户看不到，提到之前的内容时说它讲了什么，不要说第几轮："
         : "Below is this conversation so far (the record kept in Zotero), each answer with the agent that gave it; the user does not see the turn numbers, so refer to earlier messages by what they said:",
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
      zh ? `下面是这段对话里，你上次回答之后的 ${turns.length} 轮。这期间用户在 Zotero 里接着问，有的由别的智能体回答，每轮注明了回答者。它们属于这段对话，请接着它们回答；轮次编号用户看不到，提到它们时说内容，不要说第几轮：`
         : (one ? "Below is the exchange of this conversation after your last answer."
                : `Below are the ${turns.length} exchanges of this conversation after your last answer.`)
           + " Meanwhile the user went on asking in Zotero, some answered by another agent; each answer names the agent that gave it. They are part of this conversation; answer as its continuation; the user does not see the turn numbers, so refer to earlier messages by what they said:",
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
    // a chat run of the paper: the one of the conversation its messages go to, else one whose new conversation has no id yet
    const current = {};
    for (const k of pane.keys) current[k] = await this.currentConv(k);
    const liveRun = () => {
      for (const k of pane.keys) {
        const r = this.paperRuns(k).filter(x => x.kind === "chat");
        const run = r.find(x => (x.conv || null) === (current[k] || null)) || r.find(x => !x.conv) || r[0];
        if (run) return run;
      }
      return null;
    };
    if (this.panes.get(pane.body) !== pane || pane.showing !== seq) return;
    if (liveRun()) { this.showLive(pane, liveRun()); await this.showAnnotation(pane); return; }
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
    if (liveRun()) { this.showLive(pane, liveRun()); await this.showAnnotation(pane); return; }   // a run started meanwhile
    const before = this.unsentKey(pane);
    const path = shown ? this.convPath(shown.key, shown.id) : null;
    // the latest run's own transcript, which has what its log may lack (a failure before the run had one); a section that
    // showed the run as it went has it already
    const finished = path ? this.lastEntries.get(path) : null;
    const memory = !!finished;
    const kept = memory && pane.live && pane.shownPath === path && finished.length > 0;
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
    const entries = memory ? finished : log ? log.entries : [];
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
    const annotating = key ? this.paperRuns(key).find(r => r.kind === "annotate") : null;
    if (annotating) { this.showLive(pane, annotating); return; }
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
});
