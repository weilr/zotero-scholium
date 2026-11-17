// ScholiumRunner, continued: the transcript, its runs and the state line

Object.assign(ScholiumRunner, {
  // a run's transcript as it goes on, on the tab of its kind
  showLive(pane, run) {
    const view = this.viewOf(pane, run.kind);
    const before = this.unsentKey(pane);
    const key = run.key, conv = run.conv || null;
    if (view.shownKey !== key || view.shownConv !== conv) view.foldOpen = new Map();   // the steps opened are of the conversation shown
    Object.assign(view, { shownKey: key, shownConv: conv, shownAgent: run.agent || this.agent(), shownPath: run.path, live: true,
                          history: false, past: null, draft: null });
    try {
      this.renderTranscript(view, run.entries, true);
      if (run.draft) this.paintDraft(run);
    } catch (e) {}
    // the sentences the answers cite, read now: drawn again with their chips
    const had = this.citations.get(key);
    this.loadCitations(key).then(() => {
      if (this.citations.get(key) === had || !view.live || this.runOfView(view) !== run) return;
      view.draft = null;   // the redraw detaches the draft's node
      this.renderTranscript(view, run.entries, true);
      if (run.draft) this.paintDraft(run);
    }).catch(e => this.log("citations failed: " + e));
    this.swapUnsent(pane, before);
    if (view !== pane) this.paintPane(pane);
  },

  // the sections that show a run's transcript, once the new conversation it started has its log; the words typed
  // there meanwhile go on with it
  livePanes(run) {
    const key = run.key, id = run.conv;
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, run.kind);
      if (!view.live || view.shownKey !== key || (view.shownConv && view.shownConv !== id)) continue;
      const before = this.unsentKey(pane, view);
      view.shownConv = id;
      view.shownPath = this.convPath(key, id);
      const text = this.unsent.get(before);
      if (text) { this.unsent.delete(before); this.unsent.set(this.unsentKey(pane, view), text); }
    }
  },

  // a transcript as runs: what each run of the agent showed, from its start line (or, in an earlier version's log, from
  // the user's words) on. The steps are the tool calls, their results and the agent's words between them; the answer is
  // what it wrote after its last step; the rest are the run's other lines (a failure, a notice): its lead before its
  // first step or answer, the others after. turn: the words the run answers, its own or, for a run that goes on with the
  // turn before (a second try, a continuation), those of the run before, which is then continued
  runsOf(entries) {
    const runs = [];
    let run = null, bare = false;   // bare: the run has nothing yet but its start line
    const open = (at, continues = false) => {
      // a compaction is no turn: the run that goes on goes on with the last turn's run
      const before = continues ? runs.filter(r => !r.compact).pop() : null;
      if (before) before.continued = true;
      run = { start: at, end: 0, prompt: null, turn: before ? before.turn : null, lead: [], steps: [], answer: [], other: [], model: "" };
      runs.push(run);
    };
    for (const e of entries) {
      if (e.kind === "run") { open(e.at, !!e.continues); run.compact = !!e.compact; bare = true; continue; }
      // words steered into the turn under way start a segment that goes on with the turn
      if (e.kind === "prompt" && e.steer && run) { open(0, true); run.prompt = e; run.last = e; bare = false; continue; }
      if (!run || (e.kind === "prompt" && !bare)) open(0);
      bare = false;
      run.last = e;
      // a run's end line gives how long it ran, for a run whose log has no time line after it (an interrupted one)
      if (e.kind === "final" && e.duration >= 0 && run.start > 0 && !run.end) run.end = run.start + e.duration;
      if (e.kind === "prompt") run.prompt = run.turn = e;
      else if (e.kind === "tool" || e.kind === "result") { run.steps.push(...run.answer, e); run.answer = []; }
      else if (e.kind === "text") run.answer.push(e);
      else if (e.kind === "info" && e.model) run.model = e.text;
      else if (e.kind === "time") { if (e.waited) run.stopped = e.at; else run.end = e.at; }   // a stopped wait is no work of the run
      else if (e.kind === "compacting" || e.kind === "compacted" || e.kind === "compactFailed") run.other.push(e);
      else (run.steps.length || run.answer.length ? run.other : run.lead).push(e);
    }
    return runs;
  },

  // one run: the user's words; the lines before its steps; a line for its steps (what it does now while it runs, else how
  // long it worked; a click opens the steps); the answer; its other lines; then the model and the time with a copy button
  renderRun(view, run, index, live) {
    return this.withCites(view.shownKey, () => this.drawRun(view, run, index, live));
  },

  drawRun(view, run, index, live) {
    if (run.compact) return this.compactNode(view, run, live);
    if (view.kind === "annotate" && run.turn && run.turn.annotate) return this.renderAnnotationRun(view, run, index, live);
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-run";
    if (run.prompt) {
      const said = this.entryNode(doc, run.prompt);
      // the user's own words can be edited and asked again
      const editable = this.promptEditable(view, run);
      if (editable) {
        said.className += " editable";
        said.append(this.iconButton(doc, "edit", this.text("editPrompt"), () => this.startEdit(view, run, said), "quiet edit-prompt"));
      }
      // the question being edited: its box stays, and stands for the words drawn now
      const e = view.editing;
      if (editable && e && this.isEditing(view, e, run.prompt)) { e.said = said; e.drawn = true; node.append(e.box); }
      else node.append(said);
    }
    // the question that replaced the ones after it a moment ago: Undo under it
    if (this.replaced.size && this.undoAt(view) === index) node.append(this.undoNode(view));
    // the last run of a view that failed without an answer carries a retry on its failure line; on the annotation tab, a
    // run of words to the session. A queued message that failed has its Retry on its row
    const failedLast = !live && index === (view.runCount || 0) - 1 && !run.answer.length && !!view.pane && (view.kind === "chat" || !!run.turn)
      && !this.busy(view.shownKey)
      && !this.queue.some(j => j.failed && this.keyOf(j.att) === view.shownKey && (j.kind || "chat") === view.kind && (j.conv || null) === (view.shownConv || null));
    let retryable = failedLast ? [...run.lead, ...run.other].filter(e => e.kind === "final" && e.error).pop() : null;
    const line = e => {
      const n = this.entryNode(doc, e);
      if (e === retryable) {
        const again = () => this.retryFromView(view).catch(err => this.log("retry failed: " + err));
        if (e.skill) n.append(this.paneButton(doc, this.text("installSkill"), () => { this.installAndRetry(view, e.skill, again).catch(err => this.log("install failed: " + err)); }, "small"));
        n.append(this.iconButton(doc, "retry", this.text("retry"), again));
      }
      return n;
    };
    // a run stopped before any step: its stop after how long it worked
    const stopped = e => e.kind === "final" && e.cancelled;
    for (const e of run.lead) if (!stopped(e)) node.append(line(e));
    if (run.steps.length || live) node.append(this.foldNode(view, run, index, live));
    else if (run.start > 0 && run.end >= run.start) node.append(this.workedNode(view, run));
    for (const e of run.lead) if (stopped(e)) node.append(line(e));
    for (const e of run.answer) node.append(this.entryNode(doc, e));
    for (const e of run.other) {
      // the agent's own compaction in this run: a line with the sizes; its start has none
      if (e.kind === "compacted") {
        node.append(this.compactedLine(doc, e));
        continue;
      }
      if (e.kind === "compacting") continue;
      node.append(line(e));
    }
    if (!live && run.answer.length) node.append(this.metaNode(doc, run));
    return node;
  },

  // the agent's own compaction within a run: a line with the sizes
  compactedLine(doc, e) {
    const n = doc.createElement("div");
    n.className = "scholium-compact";
    n.textContent = this.text("compactedAuto") + this.compactSizes(e);
    return n;
  },

  // a compaction: one line, while it runs (its words swept, with the time) and then how it ended
  compactNode(view, run, live) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-compact" + (live ? " live" : "");
    if (live) {
      const now = doc.createElement("span");
      now.append(doc.createTextNode("◌ "), this.workingNode(view, "compactingFor"));
      node.append(now);
      return node;
    }
    const lines = run.lead.concat(run.other);
    const done = lines.filter(e => e.kind === "compacted").pop();
    node.textContent = done ? this.text("compactedLine") + this.compactSizes(done) : this.text("compactStopped");
    const failure = lines.find(e => (e.kind === "final" && e.error) || e.kind === "compactFailed");
    if (!live && !done && failure) node.title = failure.text || "";
    return node;
  },

  compactSizes(e) { return e.pre > 0 && e.post > 0 ? ` · ${this.kTokens(e.pre)} → ${this.kTokens(e.post)}` : ""; },

  // an annotation in the annotation tab: the wishes; while it runs what it does now (its raw steps on a click); then
  // its steps folded with the closing words among them, and a card of the numbers or of the failure. The
  // lines after the card's in the log follow the card. A try that the annotation went on from, or waits to go on from (a
  // second try, a continuation after a pause), shows its failure as a line: the card is the annotation's end
  renderAnnotationRun(view, run, index, live) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-run";
    if (run.prompt) node.append(this.entryNode(doc, run.prompt));
    const lines = run.lead.concat(run.other);
    const counts = lines.find(e => e.kind === "counts");
    const goesOn = run.continued || (index === (view.runCount || 0) - 1
      && this.queue.some(j => this.keyOf(j.att) === view.shownKey && j.conv === view.shownConv && this.started(j)));
    const failure = live || goesOn ? null : lines.filter(e => e.kind === "final" && e.error).pop();
    const card = counts || failure;
    const lead = card && run.lead.includes(card) ? run.lead.slice(0, run.lead.indexOf(card)) : run.lead;
    for (const e of lead) node.append(this.entryNode(doc, e));
    const steps = run.steps.concat(run.answer);
    if (steps.length || live) node.append(this.foldNode(view, Object.assign({}, run, { steps, answer: [] }), index, live));
    if (counts) node.append(this.countsNode(doc, counts));
    else if (failure) node.append(this.failedCard(view, run, failure, index));
    for (const e of lines.slice(lead.length)) {
      if (e === card || e.kind === "compacting") continue;
      node.append(e.kind === "compacted" ? this.compactedLine(doc, e) : this.entryNode(doc, e));
    }
    return node;
  },

  // the card of a finished annotation: its warnings left, the numbers counted in Zotero, and its turns, tokens and end
  countsNode(doc, e) {
    const node = doc.createElement("div");
    node.className = "scholium-card";
    const title = doc.createElement("div");
    title.className = "scholium-card-title";
    // a run that left the paper none of the tool's annotations and notes says so, with what it said was left
    const none = !(e.highlights || e.margin || e.notes || e.readingNotes || e.areas);
    if (none) node.className += " none";
    // a scanned PDF's: its message, without a row of zeros
    title.textContent = none && e.scanned ? this.text("annotNoneScan", e.warnings)
      : none ? (e.warnings ? this.text("annotNoneWarn", e.warnings) : this.text("annotNone"))
      : e.warnings === "" ? this.text("annotDoneClean") : e.warnings ? this.text("annotDoneWarn", e.warnings) : this.text("annotDone");
    const nums = doc.createElement("div");
    nums.className = "scholium-card-nums";
    // framed figures and tables have a cell only when the run left some
    for (const [n, label] of [[e.highlights, "numHighlights"], [e.margin, "numMargin"], [e.notes, "numNotes"], [e.readingNotes, "numReading"]]
                             .concat(e.areas > 0 ? [[e.areas, "numAreas"]] : [])) {
      const cell = doc.createElement("div");
      const b = doc.createElement("b");
      b.textContent = String(n || 0);
      const s = doc.createElement("span");
      s.textContent = this.text(label, n || 0, e.core);
      cell.append(b, s);
      nums.append(cell);
    }
    const usage = doc.createElement("div");
    usage.className = "scholium-card-usage";
    usage.textContent = [e.turns > 0 ? this.text("turns", e.turns) : "", e.tokens > 0 ? this.text("tokens", this.kTokens(e.tokens)) : "",
                         e.at ? this.clock(e.at) : ""].filter(Boolean).join(" · ");
    node.append(...(none && e.scanned ? [title, usage] : [title, nums, usage]));
    return node;
  },

  // the card of a failed annotation: the reason, and on the view's last run while the paper does not annotate, Retry,
  // which annotates again with the same wishes
  failedCard(view, run, failure, index) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-card failed";
    const text = doc.createElement("div");
    text.textContent = failure.cancelled ? this.text("cancelledTitle") : failure.text;
    node.append(text);
    const extra = (run.turn && run.turn.extra) || "";
    if (view.pane && index === (view.runCount || 0) - 1 && !this.busy(view.shownKey, "annotate")) {
      const again = () => { this.annotateFromPane(view.pane, { extra }); };
      if (failure.skill) node.append(this.paneButton(doc, this.text("installSkill"), () => { this.installAndRetry(view, failure.skill, again).catch(e => this.log("install failed: " + e)); }, "small"));
      node.append(this.iconButton(doc, "retry", this.text("retry"), again));
    }
    return node;
  },

  // the steps folded into one line, as in Codex; the reader's opening or closing wins. It is kept by the run's start,
  // which stays when the transcript's first lines go (an earlier version's run, without one, by its place). An
  // annotation going on offers its raw steps as details
  foldNode(view, run, index, live) {
    const doc = view.doc;
    const key = run.start || index;
    const open = view.foldOpen.get(key) === true;
    const node = doc.createElement("div");
    node.className = "scholium-fold";
    const head = doc.createElement("button");
    head.className = "scholium-fold-head" + (live ? " live" : "");
    if (live && view.kind === "annotate") {
      const more = doc.createElement("span");
      more.className = "scholium-fold-more";
      more.textContent = " " + this.text("details") + (open ? " ⌄" : " ›");
      head.append(this.workingNode(view, this.liveKey(run, view)), more);
    } else if (live) {
      head.append(this.workingNode(view, this.liveKey(run, view)));
      if (open) head.append(doc.createTextNode(" ⌄"));
    } else {
      head.textContent = this.workedText(run) + (open ? " ⌄" : " ›");
    }
    head.addEventListener("click", () => { view.foldOpen.set(key, !open); this.refreshRun(view, index); });
    node.append(head);
    if (open) {
      const body = doc.createElement("div");
      body.className = "scholium-fold-body";
      for (const e of run.steps) body.append(this.entryNode(doc, e));
      node.append(body);
    }
    return node;
  },

  // a finished run without steps: how long it worked, with nothing to open
  workedNode(view, run) {
    const node = view.doc.createElement("div");
    node.className = "scholium-fold";
    const head = view.doc.createElement("div");
    head.className = "scholium-fold-head plain";
    head.textContent = this.workedText(run);
    node.append(head);
    return node;
  },

  // the live line's words: Working for 12s (or Compacting context for 12s), swept by a light; tick writes the time again
  // without drawing the run
  workingNode(view, key = "workingFor") {
    const span = view.doc.createElement("span");
    span.className = "scholium-working";
    // every redraw of the line starts the sweep at the same phase
    span.style.animationDelay = -(Date.now() % 2000) + "ms";
    span.textContent = this.text(key, this.durationWords(this.elapsed(this.runOfView(view))));
    view.liveTime = { node: span, key };
    return span;
  },

  // the words of a run under way: the PDF read before the agent starts (preRun), a compaction, or the agent's work
  liveKey(run, view) {
    const going = this.runOfView(view);
    return going && going.preRun ? "preRun" : this.compactingNow(run) ? "compactingFor" : "workingFor";
  },

  // whether the agent compacts its context now, in a run under way: its last compaction line is the start of one
  compactingNow(run) {
    const last = (run.other || []).filter(e => e.kind === "compacting" || e.kind === "compacted" || e.kind === "compactFailed").pop();
    return !!last && last.kind === "compacting";
  },

  workedText(run) {
    return run.start > 0 && run.end >= run.start ? this.text("worked", this.durationWords(run.end - run.start)) : this.text("workedPlain");
  },

  // 6 分 17 秒 / 6m 17s
  durationWords(ms) {
    const all = Math.max(0, Math.round(ms / 1000));
    const h = Math.floor(all / 3600), m = Math.floor((all % 3600) / 60), s = all % 60;
    return this.text("durationWords", h, m, s);
  },

  // Opus 5.5 for claude-opus-5-5: the label the agent gave the model, else the name made readable
  modelLabel(id) {
    const name = String(id).replace(/^.* · /, "");
    for (const list of Object.values(this.models)) {
      const m = list.find(o => o.value === name);
      if (m) return m.label;
    }
    const c = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(name);
    return c ? `${c[1][0].toUpperCase()}${c[1].slice(1)} ${c[2]}.${c[3]}` : name;
  },

  // "Claude Code · Opus 5.5" for the start of a run "Claude Code · claude-opus-5-5": the agent and the model's label
  answeredBy(info) {
    const s = String(info), at = s.indexOf(" · ");
    return at > 0 ? `${s.slice(0, at)} · ${this.modelLabel(s)}` : this.modelLabel(s);
  },

  // under a finished run's answer: who gave it (the agent and the model) and when it ended, and a button that copies the
  // answer
  metaNode(doc, run) {
    const node = doc.createElement("div");
    node.className = "scholium-meta";
    const left = doc.createElement("span");
    const at = run.end || run.stopped;
    left.textContent = [run.model ? this.answeredBy(run.model) : "", at ? this.clock(at) : ""].filter(Boolean).join(" · ");
    node.append(left, this.copyButton(doc, run.answer.map(e => e.text).join("\n\n")));
    return node;
  },

  // a view's whole transcript; the last run is live while the paper's run goes on
  renderTranscript(view, entries, live) {
    const runs = this.runsOf(entries);
    view.entries = entries;
    view.runCount = runs.length;   // before the runs are drawn: the last one carries the retry
    this.redraw(view, null, () => view.list.replaceChildren(...runs.map((r, i) => this.renderRun(view, r, i, live && i === runs.length - 1))));
    // an edited question that waits for its run: Undo after the conversation
    if (this.replaced.size && this.undoAt(view) === runs.length) view.list.append(this.undoNode(view));
    view.runCount = runs.length;
    view.head = this.headOf(runs);
    // the list goes to its end, unless a box being edited kept its place in it
    if (!(view.editing && view.editing.drawn)) {
      view.list.scrollTop = view.list.scrollHeight;
      view.scrollPending = !view.list.clientHeight;   // hidden: no height to scroll in yet
    }
  },

  // what tells the first run drawn: the last line of the transcript's first run while another run follows it (until
  // then the first run is the one that grows); it changes when the transcript's first run goes
  headOf(runs) { return runs.length > 1 ? runs[0].last : null; },

  // whether a view shows a run going on: the run of the conversation it shows
  showsRun(view) { return !!this.runOfView(view); },

  // one run drawn again, when its steps are opened or closed or it ended; live while it is the view's running run
  refreshRun(view, index) {
    const runs = this.runsOf(view.entries);
    if (!runs[index]) return;
    const old = view.list.children[index];
    this.redraw(view, old, () => {
      const node = this.renderRun(view, runs[index], index, this.showsRun(view) && index === runs.length - 1);
      old.replaceWith(node);
      if (view.draft && index === runs.length - 1) node.append(view.draft.node);   // the message being written stays last
    });
  },

  // the views of a paper's tab (a run, or { key, kind } of a job) draw their last run again once the agent no longer
  // works on it (a pause, the wait for a second try, an end before the run had its log), or when an annotation reaches a
  // step
  settleRun(of) {
    if (!of) return;
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, of.kind || "chat");
      if (view.shownKey === of.key) this.refreshRun(view, view.runCount - 1);
    }
  },

  // the views that show a run's conversation, live: whether this view does
  showingRun(view, run) {
    return !!view.live && view.shownKey === run.key && (view.kind || "chat") === run.kind && (view.shownConv || null) === (run.conv || null);
  },

  // entries of a run's transcript: the views that show it draw its last run again, or all of it once another run begins
  appendEntries(run, entries) {
    const added = this.addEntries(run.entries, entries);
    if (!added.length) return;
    if (run.entries.length > this.MAX_ENTRIES) run.entries.splice(0, run.entries.length - this.MAX_ENTRIES);
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, run.kind);
      if (!this.showingRun(view, run)) continue;
      try {
        const list = view.list;
        const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
        const runs = this.runsOf(run.entries), live = this.alive(run);
        if (runs.length !== view.runCount || this.headOf(runs) !== view.head) this.renderTranscript(view, run.entries, live);
        else {
          const old = list.children[runs.length - 1];
          this.redraw(view, old, () => old.replaceWith(this.renderRun(view, runs[runs.length - 1], runs.length - 1, live)));
        }
        if (view.draft) list.lastChild.append(view.draft.node);   // the draft stays last
        if (atBottom) list.scrollTop = list.scrollHeight;
      } catch (e) {}
    }
  },

  // a piece of the message a run's agent is writing: block names the message part it belongs to; the panes show it a
  // moment later, together with the pieces that follow
  growDraft(run, piece, block) {
    if (!piece) return;
    if (!run.draft) run.draft = { text: "", block };
    else if (run.draft.block !== block) run.draft.text += "\n\n";
    run.draft.text += piece;
    run.draft.block = block;
    if (!run.draftTimer) run.draftTimer = setTimeout(() => { run.draftTimer = null; this.paintDraft(run); }, this.DRAFT_MS);
  },

  // what a run showed of a message it ended before finishing (cancelled, failed), as the plugin's line for the log; null
  // when no message was being written. The draft goes.
  unfinished(run) {
    const text = run.draft ? run.draft.text.trim() : "";
    this.dropDraft(run);
    return text ? { type: "scholium", subtype: "unfinished", text } : null;
  },

  dropDraft(run) {
    if (!run.draft) return;
    run.draft = null;
    clearTimeout(run.draftTimer);
    run.draftTimer = null;
    this.paintDraft(run);
  },

  // a run's draft at the end of each view that shows its conversation, set as Markdown
  paintDraft(run) {
    for (const pane of this.panes.values()) {
      try {
        const view = this.viewOf(pane, run.kind);
        if (!this.showingRun(view, run)) continue;
        if (!run.draft) {
          if (view.draft) view.draft.node.remove();
          view.draft = null;
          continue;
        }
        const list = view.list;
        const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
        if (!view.draft) {
          const node = this.entryNode(pane.doc, { kind: "text", text: "", draft: true });
          list.lastChild.append(node);   // in the last run
          view.draft = { node, content: node.children[0] };
        }
        // text selected in the draft stays selected: the draft is set again once the selection is gone
        const win = pane.doc.defaultView;
        const sel = win && typeof win.getSelection === "function" ? win.getSelection() : null;
        if (sel && !sel.isCollapsed && sel.containsNode(view.draft.node, true)) continue;
        view.draft.content.replaceChildren(...this.renderMarkdown(pane.doc, run.draft.text));
        if (atBottom) list.scrollTop = list.scrollHeight;
      } catch (e) {}
    }
  },

  // a run replaces whatever the panes of its paper show on its tab with its transcript
  startPanes(run) {
    for (const pane of this.panes.values()) if (pane.keys.includes(run.key)) this.showLive(pane, run);
  },

  succeeded(result) {
    return !!result && !result.is_error && (!result.subtype || result.subtype === "success");
  },

  // 完成 · 29 轮 · 2,568k tokens; the run's time is on its folded steps ("Worked for 6m 17s")
  outcome(result, cancelled = false) {
    const ended = result && ["cancelled", "interrupted"].includes(result.subtype) ? result.subtype : null;
    const parts = [this.text(cancelled ? "cancelled" : ended || (this.succeeded(result) ? "done" : "failed"))];
    if (result && result.num_turns > 0) parts.push(this.text("turns", result.num_turns));
    const tokens = this.tokenCounts(result).reduce((n, [, count]) => n + count, 0);
    if (tokens) parts.push(this.text("tokens", this.kTokens(tokens)));
    return parts.join(" · ");
  },

  tokenCounts(result) {
    const u = (result && result.usage) || {};
    return [["tokIn", "input_tokens"], ["tokCacheWrite", "cache_creation_input_tokens"],
            ["tokCacheRead", "cache_read_input_tokens"], ["tokOut", "output_tokens"]]
      .map(([label, k]) => [label, Number(u[k]) || 0]);
  },

  // the token counts behind the total, for the state line's tooltip
  tokenDetail(result) {
    const counts = this.tokenCounts(result);
    return counts.some(([, n]) => n) ? counts.map(([label, n]) => `${this.text(label)} ${this.kTokens(n)}`).join(" · ") : "";
  },

  // 21:05 today, otherwise with the date
  clock(ms) {
    const d = new Date(ms);
    const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    if (d.toDateString() === new Date().toDateString()) return hm;
    return `${this.text("monthDay", d.getMonth() + 1, d.getDate())} ${hm}`;
  },

  // the state line: this paper running, queued or paused, or its latest outcome; other papers' runs are
  // not shown here
  paintPane(pane) {
    this.keepAtEnd(pane, () => this.paintSection(pane));
  },

  paintSection(pane) {
    try {
      const tab = pane.tab;
      const view = this.viewOf(pane, tab);
      // the run of the tab: of the conversation shown, else one of the paper's of this kind
      const run = this.runOfView(view) || pane.keys.map(k => this.paperRuns(k).find(r => r.kind === tab)).find(Boolean) || null;
      const running = !!run;
      const pending = view.shownPath && this.pendingLogs.get(view.shownPath);
      const queuedAt = this.queue.findIndex(j => pane.keys.includes(this.keyOf(j.att)) && (j.kind || "chat") === tab && !this.isHeld(j));
      // a chat's outcome is its conversation's; the annotation tab's line has a deletion's only (an annotation's is its card)
      const latest = notes => notes.filter(Boolean).sort((a, b) => b.at - a.at)[0] || null;
      const note = tab === "annotate" ? latest(pane.keys.map(k => this.notes.get(`${k}/annotate`)))
        : latest(pane.keys.map(k => [k, this.notes.get(`${k}/chat`)]).filter(([k, n]) => n && (!n.conv || (k === pane.shownKey && n.conv === pane.shownConv)))
          .map(([, n]) => n)) || pane.past;
      // the limit the tab's next run waits for, named by the agent that hit it
      const hold = queuedAt >= 0 ? this.heldByLimit(this.queue[queuedAt]) : null;
      const paused = hold ? this.text(hold.throttled ? "throttledState" : hold.known ? "pausedState" : "pausedRetry", this.clock(hold.until),
                                      this.agentName(hold.agent)) : null;
      // a group's paper the user cannot write annotations to: the annotation tab says so and has no Annotate
      const readOnly = tab === "annotate" && !!pane.item && !this.writable(pane.item);
      const lines = [];
      let kind = "info", title = "";
      if (running) {
        lines.push(this.runningState(run));
        kind = "running";
      } else if (pending && (pending.unlogged.length || pending.restore)) {
        lines.push(this.text(pending.restore ? "undoNotRestored" : "logNotSaved"));
        kind = "error";
      } else if (queuedAt >= 0 && this.queue[queuedAt].retryAt > Date.now()) {
        lines.push(this.text("retryWait"));
        kind = "paused";
      } else if (queuedAt >= 0) {
        // ahead of it, what runs first: not a held message, nor a run that waits for another limit
        const ahead = this.queue.slice(0, queuedAt).filter(j => !this.isHeld(j) && [null, hold].includes(this.heldByLimit(j))).length;
        if (!(paused && ahead === 0)) lines.push(this.text("queuedThis", ahead + this.runs.size));
        if (paused) { lines.push(paused); kind = "paused"; }
      } else if (readOnly) {
        lines.push(this.text("groupReadOnly"));
      } else if (note) {
        lines.push(note.text);
        kind = note.error ? "error" : "ok";
        title = note.title || "";
      }
      pane.state.className = `scholium-state ${kind}`;
      // one line, cut where the pane is narrow: the whole of it in the tooltip, with the tokens' detail of a finished run
      pane.state.textContent = lines.join(" · ");
      pane.state.title = [running ? this.runningTitle(run) : lines.join(" · "), title].filter(Boolean).join("\n");
      this.show(pane.state, lines.length > 0);
      const busy = !!running || queuedAt >= 0;
      // any run of the paper, of either tab
      const any = pane.keys.some(k => this.busy(k));
      // no ✎ on the questions while a run of the chat goes or waits
      pane.chatView.className = "scholium-view chat" + (this.busyKind(pane, "chat") ? " busy" : "");
      if (pane.editing) pane.editing.fit();   // ✓ of a question being edited, off while the chat runs
      // the views of the tabs and the dot on the tab whose run goes on out of sight
      this.show(pane.chatView, tab === "chat");
      this.show(pane.annotView, tab === "annotate");
      pane.tabChat.className = "scholium-tab" + (tab === "chat" ? " on" : "");
      pane.tabAnnotate.className = "scholium-tab" + (tab === "annotate" ? " on" : "");
      pane.tabChat.setAttribute("aria-selected", String(tab === "chat"));
      pane.tabAnnotate.setAttribute("aria-selected", String(tab === "annotate"));
      pane.tabChat.setAttribute("tabindex", tab === "chat" ? "0" : "-1");
      pane.tabAnnotate.setAttribute("tabindex", tab === "annotate" ? "0" : "-1");
      this.show(pane.tabChatDot, tab !== "chat" && this.busyKind(pane, "chat"));
      this.show(pane.tabAnnotateDot, tab !== "annotate" && this.busyKind(pane, "annotate"));
      this.show(pane.newChat, tab === "chat");
      this.show(pane.historyButton, tab === "chat");
      // an annotation waits behind the paper's chat; not behind another annotation
      pane.annotGo.disabled = this.busyKind(pane, "annotate") || readOnly;
      this.show(pane.resume, !!hold);
      // the conversations of the tab stay as they are while its run goes or waits; the agent while any run of the paper does
      pane.agent.disabled = any;
      pane.newChat.disabled = busy || !pane.shownConv;
      pane.historyButton.disabled = busy;
      if (busy) this.closePopover(pane, "history");
      const asking = running ? !!run.asking : queuedAt >= 0 && this.asking(this.queue[queuedAt]);
      // a question while the conversation is a question's; a follow-up once it has turns of another kind (an earlier
      // version's annotation), and while such a run goes or waits
      pane.busy = this.busyKind(pane, tab);
      this.show(pane.composer, !readOnly);
      this.paintHeld(pane);
      this.paintSaved(pane);
      // the annotation tab: extra wishes and Annotate until it shows a session; then words to the session, with Annotate
      // again beside the send button; while its run goes or waits, ■
      if (tab === "annotate") {
        const has = !!pane.annot.shownConv;
        pane.input.placeholder = this.text(has || pane.busy ? "annotFollowUpHint" : "annotExtraHint");
        // again over the paper's Scholium annotations, of a session here or not
        pane.annotGo.textContent = this.text(has || pane.annot.own > 0 ? "redoTitle" : "annotateThis");
        this.show(pane.annotGo, !pane.busy);
        this.show(pane.send, has || pane.busy);
      } else {
        pane.input.placeholder = this.text((pane.turns && !pane.question && !running) || (busy && !asking) ? "followPlaceholder" : "askPlaceholder");
        this.show(pane.annotGo, false);
        this.show(pane.send, true);
      }
      this.paintRing(pane);
      this.paintHint(pane);
      this.paintQueue(pane);
      this.paintPapers(pane);
      this.paintQuote(pane);
      this.fitInput(pane);
    } catch (e) {}
  },

  // the other papers of the chat's conversation, as chips above its box; ✕ leaves one out of the next messages and gives
  // the focus to the next chip's ✕, else the previous one's, else the box
  paintPapers(pane) {
    const list = pane.tab === "chat" ? pane.others || [] : [];
    this.show(pane.papersBox, list.length > 0);
    // drawn again only when they change, so that ✕ keeps the focus
    const sig = JSON.stringify(list);
    if (pane.papersSig === sig) return;
    pane.papersSig = sig;
    const doc = pane.doc;
    const lead = doc.createElement("span");
    lead.className = "scholium-papers-lead";
    lead.textContent = this.text("papersLead");
    const drops = [];
    const chips = list.map((ref, i) => {
      const chip = doc.createElement("span");
      chip.className = "scholium-paper";
      const title = doc.createElement("span");
      title.className = "scholium-paper-title";
      title.textContent = ref.title || ref.key;
      chip.title = ref.title || ref.key;
      const drop = this.iconButton(doc, "close", this.text("paperRemove", ref.title || ref.key), () => {
        pane.others = (pane.others || []).filter(r => r !== ref);
        this.paintPapers(pane);
        const left = pane.paperDrops || [];
        try { (left[Math.min(i, left.length - 1)] || pane.input).focus(); } catch (e) {}
      });
      drops.push(drop);
      chip.append(title, drop);
      return chip;
    });
    pane.paperDrops = drops;
    pane.papersBox.replaceChildren(...(list.length ? [lead] : []), ...chips);
  },

  // the passage that goes with the next message, above the box of the chat tab; ✕ takes it away and gives the focus to
  // the box
  paintQuote(pane) {
    const q = pane.tab === "chat" ? pane.quote : null;
    this.show(pane.quoteBox, !!q);
    // drawn again only when the passage changes, so that ✕ keeps the focus
    const sig = q ? this.quoteLabel(q) : null;
    if (!q || pane.quoteSig === sig) { pane.quoteSig = sig; return; }
    pane.quoteSig = sig;
    const text = pane.doc.createElement("span");
    text.className = "scholium-quote-text";
    text.textContent = this.quoteLabel(q);
    const drop = this.iconButton(pane.doc, "close", this.text("quoteRemove"), () => {
      pane.quote = null;
      this.paintQuote(pane);
      try { pane.input.focus(); } catch (e) {}
    });
    pane.quoteBox.replaceChildren(text, drop);
  },

  paintPanes() {
    for (const [body, pane] of this.panes) {
      if (body.isConnected === false) { this.dropPane(body); continue; }
      this.paintPane(pane);
    }
  },

  // whether the Scholium section of the paper with this key is on screen in the focused window, on the tab of a run of
  // this kind; it then shows what a corner notice or the system notification would say
  paneInView(key, kind = "chat") {
    for (const [body, pane] of this.panes) {
      try {
        const win = pane.doc.defaultView;
        if (!pane.seen || !pane.keys.includes(key) || body.isConnected === false || !win || !win.document.hasFocus()) continue;
        if (pane.tab !== kind) continue;   // the other tab shows nothing of it
        if (typeof body.checkVisibility === "function" && !body.checkVisibility({ visibilityProperty: true })) continue;
        return true;
      } catch (e) {}
    }
    return false;
  },

  revealLog(path) {
    if (!path) return;
    try { Zotero.File.reveal(path); } catch (e) { this.log("reveal failed: " + e); }
  },
});
