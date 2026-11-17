// ScholiumRunner, continued: log events as display entries, and their nodes

Object.assign(ScholiumRunner, {
  // one stream-json event as display entries, in the manner of Claude Code's transcript
  entries(event) {
    const out = [];
    if (!event || typeof event !== "object") return out;
    if (typeof event.method === "string") return this.codexEntries(event);
    if (event.type === "system" && event.subtype === "init") {
      out.push({ kind: "info", model: true, text: `${this.agentName(event.agent === "codex" ? "codex" : "claude")} · ${event.model || "?"}` });
    }
    const content = event.message && Array.isArray(event.message.content) ? event.message.content : [];
    // Claude Code not signed in says so in a message and in its result: the result's line says what to do
    if (event.type === "assistant" && event.error !== "authentication_failed") {
      for (const c of content) {
        if (!c) continue;
        if (c.type === "text" && String(c.text || "").trim()) out.push({ kind: "text", text: String(c.text).trim(), error: !!event.error });
        else if (c.type === "tool_use") out.push({ kind: "tool", name: String(c.name), text: `${c.name}(${this.toolSummary(c.input || {})})` });
      }
    }
    if (event.type === "user") {
      for (const c of content) {
        if (c && c.type === "tool_result") out.push({ kind: "result", text: this.resultSummary(c.content), error: !!c.is_error });
      }
    }
    // a compaction: the agent's status, the boundary it leaves, and the plugin's own lines
    if (event.type === "system" && event.subtype === "status" && event.status === "compacting") out.push({ kind: "compacting" });
    if (event.type === "system" && event.subtype === "status" && event.compact_result && event.compact_result !== "success") {
      out.push({ kind: "compactFailed", text: String(event.compact_error || event.compact_result) });
    }
    if (event.type === "system" && event.subtype === "compact_boundary") {
      const m = event.compact_metadata || {};
      out.push({ kind: "compacted", trigger: m.trigger === "auto" ? "auto" : "manual", pre: Number(m.pre_tokens) || 0, post: Number(m.post_tokens) || 0 });
    }
    if (event.type === "scholium" && event.subtype === "compact") out.push({ kind: "compacting", text: String(event.text || "") });
    if (event.type === "scholium" && event.subtype === "compacted") {
      out.push({ kind: "compacted", trigger: "manual", pre: Number(event.pre) || 0, post: Number(event.post) || 0 });
    }
    // a run that goes on with the turn before (a second try, a continuation) has no words of its own; a compaction is a
    // run of its own
    if (event.type === "scholium" && event.subtype === "run") {
      out.push(Object.assign({ kind: "run", at: event.at || 0, compact: !!event.compact }, event.user === null && !event.compact ? { continues: true } : {}));
    }
    // an annotation's line carries its extra instructions
    if (event.type === "scholium" && event.subtype === "steer") {
      out.push(Object.assign({ kind: "prompt", text: String(event.text || ""), steer: true },
                             event.quote && event.quote.text ? { quote: this.quoteOf(event.quote) } : {}));
    }
    if (event.type === "scholium" && event.subtype === "prompt") {
      out.push(Object.assign({ kind: "prompt", text: String(event.text || "") }, event.annotate ? { annotate: true, extra: String(event.extra || "") } : {},
                             event.quote && event.quote.text ? { quote: this.quoteOf(event.quote) } : {}));
    }
    if (event.type === "scholium" && event.subtype === "unfinished" && String(event.text || "").trim()) {
      out.push({ kind: "text", text: String(event.text).trim(), unfinished: true });
    }
    if (event.type === "scholium" && event.subtype === "continue") {
      out.push({ kind: "info", text: this.text(event.reason === "update" ? "continuedUpdate" : event.reason === "throttle" ? "continuedThrottle" : "continued") });
    }
    // the end of a run without a result of its own: cancelled, failed before a result, interrupted; with how long it ran
    if (event.type === "scholium" && event.subtype === "end") {
      out.push(Object.assign({ kind: "final", text: String(event.text || "").trim() || this.text(event.outcome || "failed"), error: true },
                             event.outcome === "cancelled" ? { cancelled: true } : {},
                             this.AGENTS.includes(event.skill) ? { skill: event.skill } : {},
                             Number.isFinite(event.duration_ms) && event.duration_ms >= 0 ? { duration: event.duration_ms } : {}));
    }
    if (event.type === "scholium" && event.subtype === "retry") out.push({ kind: "info", text: this.text("retrying") });
    // the numbers an annotation's card shows, as counted when it ended
    if (event.type === "scholium" && event.subtype === "counts") {
      const n = k => Number(event[k]) || 0;
      out.push({ kind: "counts", highlights: n("highlights"), core: n("core"), margin: n("margin"), notes: n("notes"), readingNotes: n("readingNotes"),
                 areas: n("areas"),
                 warnings: typeof event.warnings === "string" ? event.warnings : null, turns: n("turns"), tokens: n("tokens"), at: n("at"),
                 scanned: event.scanned === true });   // a PDF without a text layer
    }
    // when a run ended, under what it showed; or when its wait (for a limit, a second try) was stopped
    if (event.type === "scholium" && event.subtype === "time" && event.at > 0) out.push(Object.assign({ kind: "time", text: this.clock(event.at), at: event.at }, event.waited ? { waited: true } : {}));
    // a successful result repeats Claude's last message; only a failed run's result is shown, with Claude Code's errors
    // when it has no text, and not when they only say the session is gone (a new one goes on, or the end says why)
    if (event.type === "result" && (event.is_error || (event.subtype && event.subtype !== "success"))) {
      const errors = Array.isArray(event.errors) ? event.errors.map(String).join("\n") : "";
      const text = String(event.result || errors || this.failureText(event.subtype)).trim();
      if (event.result || !this.gone(errors)) out.push({ kind: "final", text: /Please run \/login\b/.test(text) ? this.text("notSignedIn", "claude") : text, error: true });
    }
    return out;
  },

  // what the subtype of a failed run's result says
  failureText(subtype) {
    return (/^error_/.test(String(subtype || "")) && this.text(subtype)) || this.text("failed");
  },

  toolSummary(input) {
    const value = input.command || input.file_path || input.skill || input.pattern || input.path || input.url || input.description || "";
    const first = String(value).trim().split("\n")[0];
    return first.length > 160 ? first.slice(0, 159) + "…" : first;
  },

  resultSummary(content) {
    const text = typeof content === "string" ? content
      : Array.isArray(content) ? content.map(c => (c && c.type === "text" ? c.text : "")).join("\n") : "";
    const lines = text.trim().split("\n");
    let out = lines.slice(0, 4).join("\n");
    if (lines.length > 4) out += `\n… +${lines.length - 4}`;
    if (out.length > 600) out = out.slice(0, 599) + "…";
    return out || this.text("noOutput");
  },

  // one Codex notification as display entries, in the same manner: its messages, each command and
  // its output, file changes, tool calls; its reasoning is left out, as Claude's thinking is
  codexEntries(msg) {
    const item = msg.params && msg.params.item;
    if (!item || typeof item !== "object") return [];
    if (msg.method === "item/started" && item.type === "contextCompaction") return [{ kind: "compacting" }];
    if (msg.method === "item/completed" && item.type === "contextCompaction") return [{ kind: "compacted", trigger: "auto", pre: 0, post: 0 }];
    if (msg.method === "item/started") {
      return item.type === "commandExecution"
        ? [{ kind: "tool", name: "Shell", text: `Shell(${this.toolSummary({ command: this.shellCommand(item.command) })})` }] : [];
    }
    if (msg.method !== "item/completed") return [];
    const failed = item.status === "failed" || item.status === "declined";
    if (item.type === "agentMessage") return String(item.text || "").trim() ? [{ kind: "text", text: String(item.text).trim() }] : [];
    if (item.type === "commandExecution") {
      const output = String(item.aggregatedOutput || "");
      return [{ kind: "result", text: failed && !output.trim() ? this.itemStatus(item) : this.resultSummary(output),
                error: failed || (typeof item.exitCode === "number" && item.exitCode !== 0) }];
    }
    if (item.type === "fileChange") {
      return (item.changes || []).filter(c => c && c.path).map(c => ({ kind: "tool", name: "Edit", text: `Edit(${this.toolSummary({ file_path: c.path })})` }))
        .concat(failed ? [{ kind: "result", text: this.itemStatus(item), error: true }] : []);
    }
    if (item.type === "mcpToolCall") {
      const name = `${item.server}.${item.tool}`;
      return [{ kind: "tool", name, text: `${name}(${this.toolSummary(item.arguments || {})})` },
              { kind: "result", text: item.error ? String(item.error.message || item.status) : this.resultSummary(item.result && item.result.content),
                error: !!item.error || failed }];
    }
    if (item.type === "webSearch") return [{ kind: "tool", name: "WebSearch", text: `WebSearch(${this.toolSummary({ pattern: item.query })})` }];
    return [];
  },

  itemStatus(item) { return this.text(item.status === "declined" ? "itemDeclined" : "itemFailed"); },

  // add entries to a transcript; a failed run's result that repeats Claude Code's last message is
  // shown once. Returns the entries added.
  addEntries(list, entries) {
    const added = [];
    for (const e of entries) {
      const prev = list[list.length - 1];
      if (e.kind === "final" && prev && prev.kind === "text" && prev.text === e.text) continue;
      list.push(e);
      added.push(e);
    }
    return added;
  },

  // one transcript entry: a step has a bullet column beside the content, so that wrapped lines keep their indent;
  // the stylesheet sets the agent's text in the pane's font, tool calls and results in monospace, and the
  // user's words in a bubble on the right
  entryNode(doc, entry) {
    const node = doc.createElement("div");
    node.className = `scholium-entry ${entry.kind}${entry.error ? " error" : ""}${entry.draft ? " draft" : ""}`;
    const bullet = { tool: "⏺ ", result: "⎿ " }[entry.kind];
    if (bullet) {
      const span = doc.createElement("span");
      span.className = "scholium-bullet";
      span.textContent = bullet;
      node.append(span);
    }
    // a stopped run: ⊘ and its word
    if (entry.kind === "final" && entry.cancelled) {
      node.className += " cancelled";
      node.title = entry.text;
      const icon = doc.createElement("span");
      icon.className = "scholium-glyph cancelled";
      icon.setAttribute("aria-hidden", "true");
      const word = doc.createElement("span");
      word.textContent = entry.text;
      node.append(icon, word);
      return node;
    }
    if (entry.kind === "text") {
      // the agent writes Markdown: set as the profile's preview sets it
      const content = doc.createElement("div");
      content.className = "scholium-content scholium-markdown";
      try { content.append(...this.renderMarkdown(doc, entry.text)); }
      catch (e) {
        content.textContent = entry.text;   // the source rather than a section that does not render
        this.log("markdown failed: " + e);
      }
      if (entry.unfinished) {
        const note = doc.createElement("div");
        note.className = "scholium-unfinished";
        note.textContent = this.text("unfinished");
        content.append(note);
      }
      node.append(content);
      return node;
    }
    if (entry.kind === "prompt" && entry.quote) {
      const q = doc.createElement("div");
      q.className = "scholium-prompt-quote";
      q.textContent = this.quoteLabel(entry.quote);
      node.append(q);
    }
    const content = doc.createElement("span");
    content.className = "scholium-content";
    if (entry.kind === "tool" && entry.name && entry.text.startsWith(entry.name)) {
      const name = doc.createElement("b");
      name.textContent = entry.name;
      content.append(name, doc.createTextNode(entry.text.slice(entry.name.length)));
    } else {
      content.append(doc.createTextNode(entry.text));
    }
    node.append(content);
    return node;
  },

  // a button that copies the text, and shows for a moment that it did
  copyButton(doc, text) {
    const button = doc.createElement("button");
    button.className = "scholium-copy";
    button.title = this.text("copyMessage");
    button.addEventListener("click", () => {
      try {
        Zotero.Utilities.Internal.copyTextToClipboard(text);
      } catch (e) {
        this.log("copy failed: " + e);
        return;
      }
      button.className = "scholium-copy done";
      button.title = this.text("copiedMessage");
      clearTimeout(button.reset);
      button.reset = setTimeout(() => {
        button.className = "scholium-copy";
        button.title = this.text("copyMessage");
      }, 1500);
    });
    return button;
  },
});
