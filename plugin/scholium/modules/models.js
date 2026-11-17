// ScholiumRunner, continued: the models and effort levels Claude Code and Codex offer, and the section's selects

Object.assign(ScholiumRunner, {
  // the models the agent offers, with the effort levels of each, asked once per session
  async loadModels(agent = this.agent()) {
    if (this.models[agent] || this.modelsLoading[agent] || Date.now() - (this.modelsAsked[agent] || 0) < 60000) return;
    this.modelsAsked[agent] = Date.now();
    this.modelsLoading[agent] = true;
    try {
      const models = agent === "codex" ? await this.askCodexModels() : await this.askModels();
      if (models) {
        this.models[agent] = models;
        for (const pane of this.panes.values()) this.fillSelects(pane);
      }
    } catch (e) { this.log("model list failed: " + ((e && e.message) || JSON.stringify(e))); }
    finally { this.modelsLoading[agent] = false; }
  },

  // Claude Code's models: the initialize request of its stream-json protocol answers without calling
  // a model; only the model list is kept

  async askModels() {
    const claude = await this.findClaude();
    if (!claude) return null;
    const proc = await this.subprocess().call(Object.assign({
      command: claude, arguments: ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                                   "--strict-mcp-config", "--settings", JSON.stringify({ disableAllHooks: true })],
      workdir: Zotero.DataDirectory.dir, stderr: "stdout",
    }, await this.agentEnv()));
    // after 60 s the process is killed and the wait ends, since a child it started may keep its output open (readOutput)
    let late = false, timer = null;
    const deadline = new Promise(resolve => { timer = setTimeout(() => { late = true; try { proc.kill(); } catch (e) {} resolve(null); }, 60000); });
    const read = (async () => {
      await proc.stdin.write(JSON.stringify({ type: "control_request", request_id: "scholium-models",
                                              request: { subtype: "initialize" } }) + "\n");
      await proc.stdin.close();
      let buffer = "";
      for (;;) {
        const chunk = await proc.stdout.readString();
        if (!chunk || late) return null;
        buffer += chunk;
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const raw of lines) {
          let event;
          try { event = JSON.parse(raw); } catch (e) { continue; }
          const r = event && event.type === "control_response" && event.response;
          if (r && r.request_id === "scholium-models") return this.modelOptions(r.response && r.response.models);
        }
      }
    })();
    try { return await Promise.race([read, deadline]); }
    finally {
      clearTimeout(timer);
      try { proc.kill(); } catch (e) {}
    }
  },

  // Claude Code's model list as options; its "default" entry is the empty value, which passes no --model
  modelOptions(list) {
    if (!Array.isArray(list)) return null;
    const out = [];
    for (const m of list) {
      if (!m || typeof m.value !== "string" || !m.value) continue;
      const value = m.value === "default" ? "" : m.value;
      if (out.some(o => o.value === value)) continue;
      const efforts = Array.isArray(m.supportedEffortLevels) ? m.supportedEffortLevels.map(String)
        : m.supportsEffort ? this.EFFORTS : [];
      let label = String(m.displayName || m.value);
      if (!value) {
        const twin = list.find(o => o && o !== m && o.value !== "default" && o.resolvedModel && o.resolvedModel === m.resolvedModel);
        const name = (twin && twin.displayName) || m.resolvedModel || "";
        label = name ? this.text("paneClaudeDefaultModel", name) : this.text("paneClaudeDefault");
      }
      out.push({ value, label, title: String(m.description || ""), efforts });
    }
    if (!out.length) return null;
    if (!out.some(o => o.value === "")) out.unshift({ value: "", label: this.text("paneClaudeDefault"), title: "", efforts: this.EFFORTS });
    return out;
  },

  // Codex's models and their effort levels (model/list); its configuration is not read, so the model it runs by default
  // is the one a new thread last named (codexDefault), else unnamed; no model is called
  async askCodexModels() {
    const codex = await this.findCodex();
    if (!codex) return null;
    const rpc = await this.codexServer(codex, Zotero.DataDirectory.dir);
    const timer = setTimeout(() => rpc.close(), 60000);
    try {
      await this.codexHello(rpc);
      const list = await rpc.request("model/list", {});
      return this.codexModelOptions(list && list.data, String(this.getPref("codexDefault") || ""));
    } finally {
      clearTimeout(timer);
      rpc.close();
    }
  },

  // the model a new Codex thread ran with none chosen, which is Codex's own default: kept, and named by the default option
  noteCodexDefault(name) {
    if (!name || this.getPref("codexDefault") === name) return;
    try { Zotero.Prefs.set(this.pref + "codexDefault", name, true); } catch (e) { this.log("preference not saved: " + e); }
    const options = this.models.codex, first = options && options[0];
    if (!first || first.value !== "") return;
    const twin = options.find(o => o.value === name);
    Object.assign(first, { label: this.text("paneCodexDefaultModel", twin ? twin.label : name), efforts: twin ? twin.efforts : this.CODEX_EFFORTS });
    for (const pane of this.panes.values()) this.fillSelects(pane);
  },

  // Codex's model list as options; the empty value runs Codex's own default: the model of its config.toml as a new
  // thread named it, named by the option once known, with that model's levels. Hidden models are left out.
  codexModelOptions(list, configured = "") {
    if (!Array.isArray(list)) return null;
    const out = [];
    for (const m of list) {
      if (!m || typeof m.model !== "string" || !m.model || m.hidden || out.some(o => o.value === m.model)) continue;
      const efforts = Array.isArray(m.supportedReasoningEfforts)
        ? m.supportedReasoningEfforts.map(e => String(e && typeof e === "object" ? e.reasoningEffort || "" : e || "")).filter(Boolean)
        : this.CODEX_EFFORTS;
      out.push({ value: m.model, label: String(m.displayName || m.model), title: String(m.description || ""), efforts });
    }
    if (!out.length) return null;
    const name = configured;
    const twin = out.find(o => o.value === name);
    out.unshift({ value: "", label: name ? this.text("paneCodexDefaultModel", twin ? twin.label : name) : this.text("paneCodexDefault"),
                  title: "", efforts: twin ? twin.efforts : this.CODEX_EFFORTS });
    return out;
  },

  // the agent's model options: its list once it answered, and the chosen model in any case
  modelChoices(agent = this.agent()) {
    const saved = this.modelPref(agent), efforts = agent === "codex" ? this.CODEX_EFFORTS : this.EFFORTS;
    const list = this.models[agent]
      || [{ value: "", label: this.text(agent === "codex" ? "paneCodexDefault" : "paneClaudeDefault"), title: "", efforts }];
    return list.some(m => m.value === saved) ? list : list.concat([{ value: saved, label: saved, title: "", efforts }]);
  },

  // the effort levels the agent's chosen model accepts
  effortChoices(agent = this.agent()) {
    const saved = this.modelPref(agent);
    return this.modelChoices(agent).find(m => m.value === saved).efforts;
  },

  // a pane's selects from the model list and the saved choices
  fillSelects(pane) {
    try {
      const option = (value, label, title) => {
        const o = pane.doc.createElement("option");
        o.value = value;
        o.textContent = label;
        if (title) o.title = title;
        return o;
      };
      pane.agent.replaceChildren(...this.AGENTS.map(a => option(a, this.agentName(a))));
      pane.agent.value = this.agent();
      pane.model.replaceChildren(...this.modelChoices().map(m => option(m.value, m.label, m.title)));
      pane.model.value = this.modelPref();
      const levels = this.effortChoices();
      pane.effort.replaceChildren(...(levels.length ? levels.map(e => option(e, e)) : [option("", this.text("paneNoEffort"))]));
      pane.effort.value = this.effort();
      pane.effort.disabled = !levels.length;
      if (pane.chip) this.paintChip(pane);
    } catch (e) { this.log("selects failed: " + e); }
  },

  // a choice is saved and shown by every pane; another agent's models are asked for
  choose(prefName, value) {
    try { Zotero.Prefs.set(this.pref + prefName, value, true); } catch (e) { this.log("preference not saved: " + e); }
    for (const pane of this.panes.values()) this.fillSelects(pane);
    if (prefName === "agent") this.loadModels().catch(() => {});
  },
});
