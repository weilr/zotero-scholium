/* Scholium Bridge: a minimal plugin for Zotero 7 and later.
 * Reader toggle (all versions): annotations tagged by zotero-scholium are hidden in every reader view
 * (tab, window, item-pane preview) until the eye button in the reader toolbar is pressed. Each newly
 * opened reader starts hidden. Hiding removes the annotations from the view only; stored items are
 * not changed.
 * Endpoints (needed on Zotero 7 to 9 only), on Zotero's built-in local HTTP server (http://127.0.0.1:23119):
 *   GET  /scholium-bridge/ping   -> { ok, version, dataDir }                       (no token)
 *   POST /scholium-bridge/list   -> annotations of one attachment                  (token)
 *   POST /scholium-bridge/apply  -> clean up + create annotations / child note     (token)
 * No code is evaluated: requests carry plain data (highlight, text, and note annotations).
 * The token is stored in <Zotero data directory>/scholium-bridge.token (created on first start).
 */

var ScholiumBridge = {
  version: "0.1.2",
  token: null,
  paths: ["/scholium-bridge/ping", "/scholium-bridge/list", "/scholium-bridge/apply"],

  log(msg) { Zotero.debug("[scholium-bridge] " + msg); },

  async loadToken() {
    const path = PathUtils.join(Zotero.DataDirectory.dir, "scholium-bridge.token");
    try {
      if (await IOUtils.exists(path)) {
        const t = (await IOUtils.readUTF8(path)).trim();
        if (t.length >= 16) return t;
      }
    } catch (e) { this.log("token read failed: " + e); }
    const t = Zotero.Utilities.randomString(40);
    await IOUtils.writeUTF8(path, t);
    return t;
  },

  header(headers, name) {
    if (!headers) return null;
    const want = name.toLowerCase();
    for (const k of Object.keys(headers)) if (k.toLowerCase() === want) return headers[k];
    return null;
  },

  authorized(options) {
    const given = this.header(options.headers, "X-Annotate-Token");
    return !!this.token && given === this.token;
  },

  reply(status, obj) { return [status, "application/json", JSON.stringify(obj)]; },

  parse(options) {
    let d = options.data;
    if (typeof d === "string") { try { d = JSON.parse(d); } catch (e) { d = null; } }
    return d || {};
  },

  summarize(a) {
    return {
      key: a.key, type: a.annotationType, color: a.annotationColor, author: a.annotationAuthorName || "",
      isExternal: !!a.annotationIsExternal, pageLabel: a.annotationPageLabel,
      text: (a.annotationText || "").slice(0, 80), comment: (a.annotationComment || "").slice(0, 80),
      tags: a.getTags().map(t => t.tag),
      position: (() => { try { return JSON.parse(a.annotationPosition || "{}"); } catch (e) { return {}; } })(),
    };
  },

  async list(data) {
    const libraryID = Zotero.Libraries.userLibraryID;
    const att = Zotero.Items.getByLibraryAndKey(libraryID, data.attachmentKey);
    if (!att) throw new Error("attachment not found: " + data.attachmentKey);
    const anns = att.getAnnotations(true).map(a => this.summarize(a));
    const notes = [];
    const parent = att.parentID ? Zotero.Items.get(att.parentID) : null;
    if (parent) for (const n of Zotero.Items.get(parent.getNotes())) notes.push({ key: n.key, title: n.getNoteTitle() });
    return { ok: true, attachmentKey: att.key, parentKey: parent ? parent.key : null, annotations: anns, notes };
  },

  async apply(data) {
    const libraryID = Zotero.Libraries.userLibraryID;
    const att = Zotero.Items.getByLibraryAndKey(libraryID, data.attachmentKey);
    if (!att) throw new Error("attachment not found: " + data.attachmentKey);
    const parent = data.itemKey ? Zotero.Items.getByLibraryAndKey(libraryID, data.itemKey)
                                : (att.parentID ? Zotero.Items.get(att.parentID) : null);
    const anns = Array.isArray(data.annotations) ? data.annotations : [];

    // (0) cleanup: annotations tagged by this tool.
    //     Also remove external (PDF-imported, locked) annotations when data.cleanupExternal is true.
    const tag = data.tag || "";
    const ownTags = new Set([tag].concat(data.legacyTags || []).filter(Boolean));
    let removed = 0, kept = 0;
    if (data.cleanup !== false) {
      for (const a of att.getAnnotations(true)) {
        const tags = a.getTags().map(t => t.tag);
        const mine = tags.some(t => ownTags.has(t)) ||
                     (data.cleanupExternal && a.annotationIsExternal);
        if (mine) { await a.eraseTx(); removed++; } else { kept++; }
      }
    }

    // (1) child note. With note.replace = true, existing child notes whose title starts with titlePrefix are
    //     deleted first (intended only for notes this tool created under that title; the option is opt-in).
    let noteCreated = false, noteSkipped = false, notesRemoved = 0;
    if (data.note && data.note.html && parent) {
      const prefix = data.note.titlePrefix || "";
      let existingNotes = Zotero.Items.get(parent.getNotes());
      if (prefix && data.note.replace) {
        for (const n of existingNotes) {
          if ((n.getNoteTitle() || "").startsWith(prefix)) { await n.eraseTx(); notesRemoved++; }
        }
        existingNotes = Zotero.Items.get(parent.getNotes());
      }
      const existing = existingNotes.map(n => n.getNoteTitle());
      if (prefix && existing.some(t => t && t.startsWith(prefix))) {
        noteSkipped = true;
      } else {
        const note = new Zotero.Item("note");
        note.libraryID = libraryID;
        note.parentID = parent.id;
        note.setNote(data.note.html);
        if (tag) note.setTags([{ tag }]);
        await note.saveTx();
        noteCreated = true;
      }
    }

    // (2) annotations
    const created = { highlight: 0, underline: 0, text: 0, note: 0 };
    const allowed = new Set(["highlight", "underline", "text", "note"]);
    await Zotero.DB.executeTransaction(async () => {
      for (const a of anns) {
        if (!allowed.has(a.type)) continue;
        const ann = new Zotero.Item("annotation");
        ann.libraryID = libraryID;
        ann.parentID = att.id;
        let type = a.type;
        try { ann.annotationType = type; }
        catch (e) { type = "note"; ann.annotationType = type; }   // Zotero versions without text annotations
        if (type === "highlight" || type === "underline") ann.annotationText = a.text || "";
        ann.annotationComment = a.comment || "";
        ann.annotationColor = a.color || "#ffd400";
        ann.annotationPageLabel = a.pageLabel || String((a.position && a.position.pageIndex + 1) || 1);
        ann.annotationSortIndex = a.sortIndex || "00000|000000|00000";
        const pos = Object.assign({}, a.position);
        if (type === "note") { delete pos.fontSize; delete pos.rotation; const r = pos.rects[0]; pos.rects = [[r[0], r[3] - 22, r[0] + 22, r[3]]]; }
        ann.annotationPosition = JSON.stringify(pos);
        if (tag) ann.setTags([{ tag }]);
        await ann.save();
        created[type]++;
      }
    });
    return { ok: true, removed, kept, noteCreated, noteSkipped, notesRemoved, created };
  },

  register() {
    const self = this;
    class Ping {
      supportedMethods = ["GET", "POST"];
      supportedDataTypes = ["application/json"];
      // init must declare exactly one parameter: Zotero's server treats an init of arity 0 or 2 as the
      // legacy callback style, and the request would never resolve.
      init = async (options) => self.reply(200, { ok: true, name: "scholium-bridge", version: self.version, dataDir: Zotero.DataDirectory.dir });
    }
    class List {
      supportedMethods = ["POST"];
      supportedDataTypes = ["application/json"];
      init = async (options) => {
        if (!self.authorized(options)) return self.reply(401, { ok: false, error: "unauthorized" });
        try { return self.reply(200, await self.list(self.parse(options))); }
        catch (e) { return self.reply(500, { ok: false, error: String(e && e.message || e) }); }
      };
    }
    class Apply {
      supportedMethods = ["POST"];
      supportedDataTypes = ["application/json"];
      init = async (options) => {
        if (!self.authorized(options)) return self.reply(401, { ok: false, error: "unauthorized" });
        try { return self.reply(200, await self.apply(self.parse(options))); }
        catch (e) { return self.reply(500, { ok: false, error: String(e && e.message || e) }); }
      };
    }
    Zotero.Server.Endpoints["/scholium-bridge/ping"] = Ping;
    Zotero.Server.Endpoints["/scholium-bridge/list"] = List;
    Zotero.Server.Endpoints["/scholium-bridge/apply"] = Apply;
  },

  unregister() { for (const p of this.paths) delete Zotero.Server.Endpoints[p]; },
};

var ScholiumToggle = {
  tag: "zotero-scholium",
  active: false,
  shown: new WeakSet(),     // readers whose scholium annotations are currently displayed
  handler: null,
  proto: null,              // ReaderInstance.prototype, once reached through a reader
  original: null,
  wrapper: null,
  hooks: [],                // [object, property, replacement] used until the prototype is reached

  log(msg) { Zotero.debug("[scholium-bridge] " + msg); },

  isOwn(item) {
    try { return !!item && item.isAnnotation() && item.getTags().some(t => t.tag === this.tag); }
    catch (e) { return false; }
  },

  hidden(reader) { return this.active && !this.shown.has(reader); },

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
      if (self.hidden(this) && self.isOwn(item)) return null;
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
      if (!this.hidden(reader)) return;
      const keys = this.ownAnnotations(reader).map(a => a.key);
      if (keys.length) await reader.unsetAnnotations(keys);
    } catch (e) { this.log("hide failed: " + e); }
  },

  async toggle(reader, button) {
    const show = !this.shown.has(reader);
    if (show) this.shown.add(reader); else this.shown.delete(reader);
    this.paint(button, reader);
    const own = this.ownAnnotations(reader);
    if (!own.length) return;
    if (show) await reader.setAnnotations(own);
    else await reader.unsetAnnotations(own.map(a => a.key));
  },

  label(shown) {
    const zh = String(Zotero.locale || "").toLowerCase().startsWith("zh");
    if (shown) return zh ? "隐藏 Scholium 批注" : "Hide scholium annotations";
    return zh ? "显示 Scholium 批注" : "Show scholium annotations";
  },

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

  paint(button, reader) {
    const shown = this.shown.has(reader);
    button.classList.toggle("active", shown);
    button.setAttribute("aria-pressed", String(shown));
    button.title = this.label(shown);
    button.replaceChildren(this.icon(button.ownerDocument, shown));
  },

  button(reader, doc) {
    const button = doc.createElement("button");
    button.className = "toolbar-button scholium-toggle";
    button.tabIndex = -1;
    this.paint(button, reader);
    button.addEventListener("click", () => {
      this.toggle(reader, button).catch(e => this.log("toggle failed: " + e));
    });
    return button;
  },

  onRenderToolbar(event) {
    const { reader, doc, append } = event;
    if (!this.active || !reader || !doc) return;
    if (!this.proto && this.patch(reader)) this.hideLoaded(reader);
    append(this.button(reader, doc));
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
      section.append(this.button(reader, doc));
      host.append(section);
    } catch (e) { this.log("toolbar button failed: " + e); }
  },

  start(pluginID) {
    const R = Zotero.Reader;
    if (!R || typeof R.registerEventListener !== "function") return;
    this.active = true;
    this.handler = event => {
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
    const hidden = readers.filter(r => !this.shown.has(r));
    this.active = false;   // the wrapper passes everything through from here on
    try { R.unregisterEventListener("renderToolbar", this.handler); } catch (e) {}
    this.unhook();
    if (this.proto && this.proto._getAnnotation === this.wrapper) this.proto._getAnnotation = this.original;
    for (const reader of readers) {
      try {
        const doc = reader._iframeWindow && reader._iframeWindow.document;
        if (doc) for (const b of doc.querySelectorAll(".scholium-toggle")) (b.closest(".section") || b).remove();
      } catch (e) {}
      if (hidden.includes(reader)) {
        const own = this.ownAnnotations(reader);
        if (own.length) reader.setAnnotations(own).catch(e => this.log("restore failed: " + e));
      }
    }
  },
};

function install() {}
function uninstall() {}

async function startup({ id, version, rootURI }) {
  await Zotero.initializationPromise;
  try { ScholiumToggle.start(id); ScholiumToggle.log("reader toggle registered"); }
  catch (e) { ScholiumToggle.log("reader toggle failed: " + e); }
  ScholiumBridge.token = await ScholiumBridge.loadToken();
  ScholiumBridge.register();
  ScholiumBridge.log("endpoints registered");
}

function shutdown() {
  try { ScholiumToggle.stop(); } catch (e) {}
  try { ScholiumBridge.unregister(); } catch (e) {}
}
