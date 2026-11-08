// ScholiumToggle: the reader toggle, the eye button that shows or hides the tool's annotations

var ScholiumToggle = {
  tag: "zotero-scholium",
  pref: "extensions.scholium.showAnnotations",
  active: false,
  shown: false,             // one state for every reader, loaded from and saved to the preference
  handler: null,
  proto: null,              // ReaderInstance.prototype, once reached through a reader
  original: null,
  wrapper: null,
  hooks: [],                // [object, property, replacement] used until the prototype is reached

  log(msg) { Zotero.debug("[scholium] " + msg); },

  isOwn(item) {
    try { return !!item && item.isAnnotation() && item.getTags().some(t => t.tag === this.tag); }
    catch (e) { return false; }
  },

  hidden() { return this.active && !this.shown; },

  readPref() {
    try { return Zotero.Prefs.get(this.pref, true) === true; }
    catch (e) { return false; }
  },

  ownAnnotations(reader) {
    const att = Zotero.Items.get(reader.itemID);
    return att ? att.getAnnotations().filter(a => this.isOwn(a)) : [];
  },

  // Every annotation reaches a reader view through ReaderInstance.prototype._getAnnotation, both when
  // the reader opens and when Zotero reports added or modified items; returning null keeps it out.
  patch(reader) {
    if (this.proto) return true;
    let p = reader;
    while (p && !Object.prototype.hasOwnProperty.call(p, "_getAnnotation")) p = Object.getPrototypeOf(p);
    if (!p || typeof p._getAnnotation !== "function") return false;
    const self = this, original = p._getAnnotation;
    this.wrapper = function (item) {
      if (self.hidden() && self.isOwn(item)) return null;
      return original.apply(this, arguments);
    };
    p._getAnnotation = this.wrapper;
    this.proto = p;
    this.original = original;
    this.unhook();
    return true;
  },

  // ReaderInstance is not exported. Until a first reader exists, catch new readers as Zotero registers
  // them: a tab or window is pushed to Zotero.Reader._readers before it loads its annotations.
  hook() {
    const self = this, R = Zotero.Reader;
    if (Array.isArray(R._readers)) {
      const push = R._readers.push;
      const replacement = function () {
        for (const r of arguments) self.patch(r);
        return push.apply(this, arguments);
      };
      R._readers.push = replacement;
      this.hooks.push([R._readers, "push", replacement]);
    }
    if (typeof R.openPreview === "function") {
      const openPreview = R.openPreview;
      const replacement = async function () {
        const reader = await openPreview.apply(this, arguments);
        if (reader && self.patch(reader)) self.hideLoaded(reader);
        return reader;
      };
      R.openPreview = replacement;
      this.hooks.push([R, "openPreview", replacement]);
    }
  },

  unhook() {
    for (const [obj, prop, replacement] of this.hooks) {
      if (obj[prop] === replacement) delete obj[prop];
    }
    this.hooks = [];
  },

  // For a reader that may have loaded scholium annotations before the wrapper was in place.
  async hideLoaded(reader) {
    try {
      await reader._initPromise;
      if (!this.hidden()) return;
      const keys = this.ownAnnotations(reader).map(a => a.key);
      if (keys.length) await reader.unsetAnnotations(keys);
    } catch (e) { this.log("hide failed: " + e); }
  },

  async toggle() { await this.setShown(!this.shown); },

  // the end of an annotation that wrote, for a user who has never used the button (the preference was never set, not
  // false): the annotations are shown from now on, as a click shows them. Once the preference is set, the clicks decide
  async showOnce() {
    let set;
    try { set = Zotero.Prefs.get(this.pref, true); } catch (e) { return false; }
    if (set !== undefined) return false;
    await this.setShown(true);
    return true;
  },

  // Switch every open reader and its button, and save the choice for later readers and sessions.
  // An item-pane preview that is already showing follows on its next load.
  async setShown(shown) {
    this.shown = shown;
    try { Zotero.Prefs.set(this.pref, this.shown, true); }
    catch (e) { this.log("preference not saved: " + e); }
    const readers = Array.from(Zotero.Reader._readers || []);
    for (const reader of readers) this.repaint(reader);
    await Promise.all(readers.map(reader => this.refresh(reader).catch(e => this.log("refresh failed: " + e))));
  },

  async refresh(reader) {
    const own = this.ownAnnotations(reader);
    if (!own.length) return;
    if (this.shown) await reader.setAnnotations(own);
    else await reader.unsetAnnotations(own.map(a => a.key));
  },

  repaint(reader) {
    try {
      const doc = reader._iframeWindow && reader._iframeWindow.document;
      if (doc) for (const b of doc.querySelectorAll(".scholium-toggle")) this.paint(b);
    } catch (e) {}
  },

  // the button's words, in Zotero's language (the runner's texts)
  label(shown) { return ScholiumRunner.text(shown ? "toggleHide" : "toggleShow"); },

  // 20 x 20 eye; crossed out while the annotations are hidden
  icon(doc, shown) {
    const NS = "http://www.w3.org/2000/svg";
    const svg = doc.createElementNS(NS, "svg");
    for (const [k, v] of [["width", "20"], ["height", "20"], ["viewBox", "0 0 20 20"], ["fill", "none"]]) svg.setAttribute(k, v);
    const paths = ["M10 4.75c-3.9 0-6.7 2.9-7.9 5.25 1.2 2.35 4 5.25 7.9 5.25s6.7-2.9 7.9-5.25C16.7 7.65 13.9 4.75 10 4.75Z",
                   "M12.25 10a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Z"];
    if (!shown) paths.push("M3.5 3.5l13 13");
    for (const d of paths) {
      const p = doc.createElementNS(NS, "path");
      p.setAttribute("d", d);
      p.setAttribute("stroke", "currentColor");
      p.setAttribute("stroke-width", "1.25");
      p.setAttribute("stroke-linecap", "round");
      svg.append(p);
    }
    return svg;
  },

  paint(button) {
    const shown = this.shown;
    button.classList.toggle("active", shown);
    button.setAttribute("aria-pressed", String(shown));
    button.title = this.label(shown);
    button.replaceChildren(this.icon(button.ownerDocument, shown));
  },

  button(doc) {
    const button = doc.createElement("button");
    button.className = "toolbar-button scholium-toggle";
    button.tabIndex = -1;
    this.paint(button);
    button.addEventListener("click", () => {
      this.toggle().catch(e => this.log("toggle failed: " + e));
    });
    return button;
  },

  onRenderToolbar(event) {
    const { reader, doc, append } = event;
    if (!this.active || !reader || !doc) return;
    if (!this.proto && this.patch(reader)) this.hideLoaded(reader);
    // the section was emptied before this event: a button here comes from a copy of 0.1.6 or earlier
    // that a plugin update left running (see start)
    if (doc.querySelector(".toolbar .scholium-toggle")) return;
    append(this.button(doc));
  },

  // readers opened before the plugin started: their toolbars have already been rendered
  async addButton(reader) {
    try {
      await reader._initPromise;
      const doc = reader._iframeWindow && reader._iframeWindow.document;
      const host = doc && doc.querySelector(".toolbar .end .custom-sections");
      if (!this.active || !host || host.querySelector(".scholium-toggle")) return;
      const section = doc.createElement("div");
      section.className = "section";
      section.append(this.button(doc));
      host.append(section);
    } catch (e) { this.log("toolbar button failed: " + e); }
  },

  start(pluginID) {
    const R = Zotero.Reader;
    if (!R || typeof R.registerEventListener !== "function") return;
    // Zotero's handlers for a plugin update do not wait for each other: the running copy can be started
    // again, or left running beside the new one. The copy that starts last stops the one before it.
    if (R.scholiumToggle && R.scholiumToggle.active) {
      try { R.scholiumToggle.stop(); } catch (e) { this.log("previous toggle not stopped: " + e); }
    }
    R.scholiumToggle = this;
    this.shown = this.readPref();
    this.active = true;
    // a handler left registered (see unregisterReaderListener) does nothing once this copy stopped
    const handler = this.handler = event => {
      if (this.handler !== handler) return;
      try { this.onRenderToolbar(event); } catch (e) { this.log("toolbar: " + e); }
    };
    R.registerEventListener("renderToolbar", this.handler, pluginID);
    const open = Array.from(R._readers || []);
    for (const reader of open) this.patch(reader);
    if (!this.proto) this.hook();
    for (const reader of open) { this.hideLoaded(reader); this.addButton(reader); }
  },

  stop() {
    if (!this.active) return;
    const R = Zotero.Reader;
    const readers = Array.from(R._readers || []);
    const hidden = !this.shown;
    this.active = false;   // the wrapper passes everything through from here on
    unregisterReaderListener("renderToolbar", this.handler);
    this.handler = null;
    this.unhook();
    if (this.proto && this.proto._getAnnotation === this.wrapper) this.proto._getAnnotation = this.original;
    this.proto = this.original = this.wrapper = null;   // a later start patches again
    if (R.scholiumToggle === this) delete R.scholiumToggle;
    for (const reader of readers) {
      try {
        const doc = reader._iframeWindow && reader._iframeWindow.document;
        if (doc) for (const b of doc.querySelectorAll(".scholium-toggle")) (b.closest(".section") || b).remove();
      } catch (e) {}
      if (hidden) {
        const own = this.ownAnnotations(reader);
        if (own.length) reader.setAnnotations(own).catch(e => this.log("restore failed: " + e));
      }
    }
  },
};
