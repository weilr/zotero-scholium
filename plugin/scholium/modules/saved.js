// ScholiumRunner, continued: saved prompts

Object.assign(ScholiumRunner, {
  // the saved prompts of the row above the chat's box: [{ label, prompt }]; the four built-in ones until the list is
  // changed, then the list as it was saved
  savedPrompts() {
    try {
      const list = JSON.parse(this.getPref("savedPrompts") || "null");
      if (Array.isArray(list)) {
        return list.filter(p => p && typeof p.prompt === "string" && p.prompt.trim())
          .map(p => ({ label: String(p.label || "").trim() || this.promptLabel(p.prompt), prompt: p.prompt.trim() }));
      }
    } catch (e) { this.log("saved prompts not read: " + e); }
    return [1, 2, 3, 4].map(n => ({ label: this.text("starterLabel" + n), prompt: this.text("starter" + n) }));
  },

  saveSavedPrompts(list) {
    try { Zotero.Prefs.set(this.pref + "savedPrompts", JSON.stringify(list.map(p => ({ label: p.label, prompt: p.prompt }))), true); }
    catch (e) { this.log("saved prompts not saved: " + e); }
    this.refresh();
  },

  // a prompt's label when none was given: its first twelve characters
  promptLabel(prompt) { return Array.from(String(prompt).trim().split("\n")[0]).slice(0, 12).join(""); },

  // the row of saved prompts, on the chat tab while its box is there: one button each (✎ and 🗑 on hover), ＋ at the end,
  // and the one deleted a moment ago with Undo; drawn again only when that changes, and not while a prompt is edited there
  paintSaved(pane) {
    const shown = pane.tab === "chat" && !pane.composer.hidden;
    this.show(pane.saved, shown);
    if (!shown || pane.savedEdit) return;
    const list = this.savedPrompts();
    const sig = JSON.stringify([list, !!this.savedRemoved]);
    if (pane.savedSig === sig) return;
    pane.savedSig = sig;
    const doc = pane.doc;
    const nodes = list.map((p, at) => this.savedItem(pane, p, at));
    nodes.push(this.iconButton(doc, "add", this.text("savedAdd"), () => this.editSaved(pane, -1)));
    if (this.savedRemoved) nodes.push(this.undoStrip(doc, this.text("queuedRemoved"), () => this.undoRemoveSaved()));
    pane.saved.replaceChildren(...nodes);
  },

  // a saved prompt: its label sends its words; ✎ and 🗑 beside it; dragged onto another, it takes that one's place
  savedItem(pane, p, at) {
    const doc = pane.doc, node = doc.createElement("span");
    node.className = "scholium-saved-item";
    node.setAttribute("draggable", "true");
    const go = doc.createElement("button");
    go.className = "scholium-saved-go";
    go.textContent = p.label;
    go.title = p.prompt;
    go.addEventListener("click", () => this.sendFromPane(pane, false, p.prompt));
    node.append(go,
                this.iconButton(doc, "edit", this.text("savedEdit"), () => this.editSaved(pane, at)),
                this.iconButton(doc, "trash", this.text("savedDelete"), () => this.removeSaved(at)));
    node.addEventListener("dragstart", e => { pane.dragSaved = at; try { e.dataTransfer.setData("text/plain", String(at)); } catch (err) {} });
    node.addEventListener("dragend", () => { pane.dragSaved = null; });
    node.addEventListener("dragover", e => { if (typeof pane.dragSaved === "number") e.preventDefault(); });
    node.addEventListener("drop", e => {
      e.preventDefault();
      const from = pane.dragSaved;
      pane.dragSaved = null;
      if (typeof from === "number") this.moveSaved(from, at);
    });
    return node;
  },

  // a line that says what was just done, with Undo
  undoStrip(doc, text, onUndo) {
    const strip = doc.createElement("div");
    strip.className = "scholium-undo";
    const t = doc.createElement("span");
    t.textContent = text;
    strip.append(t, this.paneButton(doc, this.text("undo"), onUndo, "quiet small"));
    return strip;
  },

  // the row as a small editor of one saved prompt (at -1: a new one at the end): its label and its words; ✓ or
  // Ctrl/⌘+Enter keeps it, ✕ or Esc leaves the row as it was
  editSaved(pane, at) {
    const doc = pane.doc, was = at >= 0 ? this.savedPrompts()[at] || null : null;
    const editor = doc.createElement("div");
    editor.className = "scholium-saved-editor";
    const label = doc.createElement("input");
    label.className = "scholium-saved-label";
    label.setAttribute("no-native", "true");
    label.setAttribute("no-windows-native", "true");
    label.placeholder = this.text("savedLabel");
    label.value = was ? was.label : "";
    const words = doc.createElement("textarea");
    words.className = "scholium-saved-prompt";
    words.setAttribute("rows", "2");
    words.setAttribute("no-native", "true");
    words.setAttribute("no-windows-native", "true");
    words.placeholder = this.text("savedPrompt");
    words.value = was ? was.prompt : "";
    const close = () => { pane.savedEdit = null; pane.savedSig = null; this.paintSaved(pane); };
    const keep = () => {
      const prompt = String(words.value || "").trim();
      if (!prompt) return;
      const item = { label: String(label.value || "").trim() || this.promptLabel(prompt), prompt };
      const list = this.savedPrompts();
      if (at >= 0 && at < list.length) list[at] = item;
      else list.push(item);
      pane.savedEdit = null;
      pane.savedSig = null;
      this.saveSavedPrompts(list);
    };
    const no = this.iconButton(doc, "close", this.text("savedCancel"), close);
    const ok = this.iconButton(doc, "check", this.text("savedSave"), keep);
    const fit = () => { ok.disabled = !String(words.value || "").trim(); };
    words.addEventListener("input", fit);
    for (const field of [label, words]) {
      field.addEventListener("keydown", e => {
        if (e.isComposing) return;   // the ime's keys
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
        else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); keep(); }
      });
    }
    const tools = doc.createElement("div");
    tools.className = "scholium-saved-tools";
    tools.append(no, ok);
    editor.append(label, words, tools);
    fit();
    pane.savedEdit = { at, editor };
    pane.saved.replaceChildren(editor);
    try { (was ? words : label).focus(); } catch (e) {}
  },

  // a saved prompt goes at once; Undo brings it back to its place for a few seconds
  removeSaved(at) {
    const list = this.savedPrompts();
    if (!list[at]) return;
    const [item] = list.splice(at, 1);
    if (this.savedRemoved) clearTimeout(this.savedRemoved.timer);
    this.savedRemoved = { item, at, timer: setTimeout(() => { this.savedRemoved = null; this.refresh(); }, this.UNDO_MS) };
    this.saveSavedPrompts(list);
  },

  undoRemoveSaved() {
    const r = this.savedRemoved;
    if (!r) return;
    clearTimeout(r.timer);
    this.savedRemoved = null;
    const list = this.savedPrompts();
    list.splice(Math.min(r.at, list.length), 0, r.item);
    this.saveSavedPrompts(list);
  },

  // a saved prompt dragged onto another takes its place
  moveSaved(from, to) {
    const list = this.savedPrompts();
    if (from === to || !list[from] || !list[to]) return;
    const [item] = list.splice(from, 1);
    list.splice(to, 0, item);
    this.saveSavedPrompts(list);
  },
});
