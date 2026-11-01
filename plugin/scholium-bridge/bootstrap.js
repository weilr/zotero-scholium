/* Scholium Bridge: a minimal plugin for Zotero 7 and later.
 * Reader toggle (all versions): the eye button in the reader toolbar shows or hides annotations tagged
 * by zotero-scholium in every reader view (tab, window, item-pane preview) at once. The choice is kept
 * in the preference extensions.scholium-bridge.showAnnotations; until it is first switched on, the
 * annotations are hidden. Hiding removes them from the view only; stored items are not changed.
 * One-click annotation (the Scholium section of the item pane): starts the installed Claude Code or
 * Codex in the background for the paper shown (see ScholiumRunner).
 * Endpoints, on Zotero's built-in local HTTP server (http://127.0.0.1:23119); the tool writes through them
 * when the plugin is installed, and on Zotero 7 to 9 they are its only write channel:
 *   GET  /scholium-bridge/ping   -> { ok, version, dataDir }                       (no token)
 *   POST /scholium-bridge/list   -> annotations and notes of one attachment, the plugin's version (token)
 *   POST /scholium-bridge/apply  -> clean up + create annotations / child note, the new keys (token)
 * No code is evaluated: requests carry plain data (highlight, text, and note annotations).
 * The token is stored in <Zotero data directory>/scholium-bridge.token (created on first start).
 */

var ScholiumBridge = {
  version: "",              // the plugin's, from its manifest (startup)
  // the tags that mark the tool's annotations and notes, the current one first: only these are removed or trashed
  OWN_TAGS: ["zotero-scholium", "zotero-marginalia", "zotero-paper-annotate"],
  token: null,
  timer: null,
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

  // an annotation as the tool reads it: the tool's own with their whole comment and with the dates that show whether the
  // user changed them in Zotero after they were written, the others shortened
  summarize(a) {
    const tags = a.getTags().map(t => t.tag);
    const cut = tags.some(t => this.OWN_TAGS.includes(t)) ? 2000 : 80;
    return {
      key: a.key, type: a.annotationType, color: a.annotationColor, author: a.annotationAuthorName || "",
      isExternal: !!a.annotationIsExternal, pageLabel: a.annotationPageLabel,
      text: (a.annotationText || "").slice(0, cut), comment: (a.annotationComment || "").slice(0, cut),
      tags, added: a.dateAdded, modified: a.dateModified,
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
    if (parent) for (const n of Zotero.Items.get(parent.getNotes())) notes.push({ key: n.key, title: n.getNoteTitle(), tags: n.getTags().map(t => t.tag) });
    return { ok: true, version: this.version, attachmentKey: att.key, parentKey: parent ? parent.key : null, annotations: anns, notes };
  },

  async apply(data) {
    const libraryID = Zotero.Libraries.userLibraryID;
    const att = Zotero.Items.getByLibraryAndKey(libraryID, data.attachmentKey);
    if (!att) throw new Error("attachment not found: " + data.attachmentKey);
    const parent = att.parentID ? Zotero.Items.get(att.parentID) : null;
    if (data.itemKey && data.itemKey !== att.key && !(parent && parent.key === data.itemKey)) {
      throw new Error(`item ${data.itemKey} is not the parent of attachment ${data.attachmentKey}`);
    }
    if (data.note && data.note.html && !parent) throw new Error(`attachment ${data.attachmentKey} has no parent item to hold the note`);
    const anns = Array.isArray(data.annotations) ? data.annotations : [];

    // (0) cleanup: annotations tagged by this tool, and external (PDF-imported, locked) annotations when
    //     data.cleanupExternal is true. They are removed in (2), after the new annotations are saved.
    const tag = data.tag || "";
    if (tag && tag !== this.OWN_TAGS[0]) throw new Error(`tag must be ${this.OWN_TAGS[0]}`);
    const ownTags = new Set(this.OWN_TAGS);
    const old = [];
    let kept = 0;
    if (data.cleanup !== false) {
      for (const a of att.getAnnotations(true)) {
        const tags = a.getTags().map(t => t.tag);
        const mine = tags.some(t => ownTags.has(t)) ||
                     (data.cleanupExternal && a.annotationIsExternal);
        if (mine) old.push(a); else kept++;
      }
    }

    // (1) child note. A note of this tool with the same text is not written again, nor one with the same title.
    //     With note.trashOwn, the tool's other notes (titles starting with trashTitlePrefix, when given) go to the
    //     trash once everything is written; notes without the tool's tags are never touched.
    let noteCreated = false, noteSkipped = false, notesTrashed = 0;
    const trash = [], noteKeys = [], createdKeys = [];
    if (data.note && data.note.html && parent) {
      const prefix = data.note.titlePrefix || "";
      const body = html => String(html || "").replace(/<h1[^>]*>[\s\S]*?<\/h1>/i, " ").replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
      const existingNotes = Zotero.Items.get(parent.getNotes());
      const own = n => n.getTags().some(t => ownTags.has(t.tag));
      const same = existingNotes.find(n => own(n) && body(n.getNote()) === body(data.note.html));
      if (data.note.trashOwn) {
        const only = data.note.trashTitlePrefix || "";
        for (const n of existingNotes) if (own(n) && n !== same && (n.getNoteTitle() || "").startsWith(only)) trash.push(n.id);
      }
      if (same || (prefix && existingNotes.some(n => !trash.includes(n.id) && (n.getNoteTitle() || "").startsWith(prefix)))) {
        noteSkipped = true;
      } else {
        const note = new Zotero.Item("note");
        note.libraryID = libraryID;
        note.parentID = parent.id;
        note.setNote(data.note.html);
        if (tag) note.setTags([{ tag }]);
        await note.saveTx();
        noteCreated = true;
        noteKeys.push(note.key);
      }
    }

    // (2) annotations, then the old ones go, in one transaction: a failure leaves the attachment as it was
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
        createdKeys.push(ann.key);
      }
      for (const a of old) await a.erase();
    });
    // (3) the earlier notes go to the trash; the new items are written whatever happens here
    let removeError;
    if (trash.length) {
      try { await Zotero.Items.trashTx(trash); notesTrashed = trash.length; }
      catch (e) { removeError = String((e && e.message) || e); }
    }
    return { ok: true, removed: old.length, kept, noteCreated, noteSkipped, notesTrashed, created, createdKeys, noteKeys, removeError };
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
    this.endpoints = { "/scholium-bridge/ping": Ping, "/scholium-bridge/list": List, "/scholium-bridge/apply": Apply };
    Object.assign(Zotero.Server.Endpoints, this.endpoints);
  },

  // only this copy's endpoints: during an update the new copy may have registered its own before this one stops
  unregister() {
    if (this.timer) clearTimeout(this.timer);
    for (const p of this.paths) if (this.endpoints && Zotero.Server.Endpoints[p] === this.endpoints[p]) delete Zotero.Server.Endpoints[p];
  },

  // after an update: the copy it replaced may stop after this one registered, and a copy before 0.1.9 removes the
  // endpoints whoever registered them; the missing ones are put back a moment later
  keep() {
    this.timer = setTimeout(() => {
      for (const p of this.paths) if (this.endpoints && !Zotero.Server.Endpoints[p]) Zotero.Server.Endpoints[p] = this.endpoints[p];
    }, 5000);
  },
};

var ScholiumToggle = {
  tag: "zotero-scholium",
  pref: "extensions.scholium-bridge.showAnnotations",
  active: false,
  shown: false,             // one state for every reader, loaded from and saved to the preference
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

  // Switch every open reader and its button, and save the choice for later readers and sessions.
  // An item-pane preview that is already showing follows on its next load.
  async toggle() {
    this.shown = !this.shown;
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
    const hidden = !this.shown;
    this.active = false;   // the wrapper passes everything through from here on
    try { R.unregisterEventListener("renderToolbar", this.handler); } catch (e) {}
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

/* One-click annotation (Claude Code or Codex): the Scholium section in the item pane (library and
 * reader side pane) starts the user's own, unmodified agent CLI in the background, signed in with the
 * user's own account; no credentials are read. It runs the zotero-scholium skill on one paper at a
 * time. Claude Code runs as `claude -p` with the Zotero data directory as working directory. Codex
 * runs as `codex app-server`, spoken to in JSON-RPC as llm-for-zotero does; its working directory
 * is <data dir>/tmp/scholium, and its sandbox lets it write there, to the profile folder and to the
 * skill's key folder, and reach Zotero's local server. Codex's automatic reviewer decides on anything
 * beyond that; a question that still reaches the plugin is declined, since no one is there to answer.
 * The section chooses the agent, the model, from the list the agent reports, and the effort; it
 * starts, cancels and deletes, shows the state of the paper, and shows the transcript live: the
 * agent's text set as Markdown as it is written (its formulas as MathML, by KaTeX in content/katex,
 * which Zotero sets), each message with a button that copies its source,
 * each tool call and its result; the text can be selected; for an earlier run it shows the saved log.
 * A box below the transcript takes extra instructions for Annotate, or a message, which goes before the papers still
 * waiting; a message sent while its paper runs waits as a row above the text, as Codex queues a follow-up, and goes when
 * the answer before it ends (a stop holds those rows until Resume). As in llm-for-zotero, each agent has its own conversations of a paper: messages and Annotate go to the
 * one chosen last (New chat, a switch of the agent, or History, which also renames and deletes), and a conversation
 * whose session the agent no longer has goes on in a new session that is given it. The section opens the
 * annotation profile (<data dir>/zotero-scholium/profile.md), which every run follows, as plain
 * text beside a live Markdown preview in an editor sheet over the Zotero window. The state line shows
 * the turns and tokens of a run; when the usage limit is reached, the queue waits and the interrupted
 * paper continues its conversation after the reset. The section's look is content/scholium.css,
 * linked into each main window. Short notices in the corner of the window at the start and the end
 * close by themselves while Zotero is in front; while it is in the background a system notification
 * reports the end; neither shows while the paper's Scholium section is on screen in the focused window.
 * An update of the plugin hands the papers still to do over to the new copy, and the running paper
 * continues its conversation there. Only papers in My Library are annotated. Every event but the
 * pieces of a message being written and the user's message as Codex repeats it, and the plugin's own lines (the start
 * of each run, the user's words or Annotate, an edit's rewind marker, a continuation, a session the agent no longer has, the end of a run
 * without a result of its own, when a run ended), is logged to the conversation's log,
 * <data dir>/tmp/scholium/<attachment key>/conversations/<agent>-<time>.jsonl.
 */
var ScholiumRunner = {
  pluginID: null,
  queue: [],                // attachments waiting, in order
  heldQueues: new Set(),    // "<attachment key>/<kind>/<conversation>" (queueKey): a conversation's queued messages, held after a stop until Resume
  savedRemoved: null,       // { item, at, timer }: the saved prompt deleted a moment ago, until Undo can no longer bring it back
  removedQueued: new Map(), // qid -> { job, next, timer }: a queued message deleted a moment ago, until it can no longer be brought back;
                            // next: the qid of the row of its queue that followed it
  replaced: new Map(),      // "key/conv" -> the conversation before an edited question, until Undo can no longer bring it back
  qseq: 0,                  // the number of the latest queued message
  pendingQuotes: new Map(), // attachment key -> { text, page }: a passage asked about before the section was drawn
  current: null,            // { key, proc, cancelled }
  draining: false,
  job: null,                // { title, key, libraryID, started, step } of the running paper
  last: null,               // { ok, title, key, libraryID, summary, log, at } of the latest finished paper
  notes: new Map(),         // <attachment key>/<kind> -> { text, error, at, title, conv }: the latest outcome of each kind
  indexes: new Map(),       // attachment key -> { current: { claude, codex }, titles: { id: title } }: its conversations
  parsedLogs: new Map(),    // log path -> { at, size, log }: a log read before, while it is unchanged; `log` is the reading
                            // (parseLog), done or under way
  deleting: new Map(),      // log path -> { key, id, agent, title, at, wasCurrent, timer }: a conversation deleted a moment ago,
                            // until it can no longer be brought back
  unsent: new Map(),        // "<library>/<item key>/<agent>/<conversation>" -> the words in a section's message box, not yet sent
  katexLib: undefined,      // KaTeX once loaded (null when it cannot be), for the formulas in messages
  mathCache: new Map(),     // "D"/"I" + TeX -> its MathML, or null when KaTeX cannot read it
  paused: null,             // { until, known, throttled, timer } while the usage limit or the service's limit holds the queue
  restoreTimer: null,
  RETRY_MS: 10 * 60000,     // the wait when the agent names no reset time
  NET_RETRY_MS: 30000,      // the wait before the second try of a run whose connection failed
  pref: "extensions.scholium-bridge.",
  STEPS: ["skill", "extract", "reading", "writing", "dryRun", "applying"],
  // a conversation given to a new session of its agent: beyond HISTORY_FROM exchanges, the latest HISTORY_WHOLE whole and the
  // earlier ones as excerpts of the user's words and of the answer
  HISTORY_FROM: 10,
  HISTORY_WHOLE: 5,
  EXCERPT_USER: 250,
  EXCERPT_ANSWER: 400,
  UNDO_MS: 6000,            // a deleted conversation can be brought back this long
  QUEUE_UNDO_MS: 5000,      // a deleted queued message can be brought back this long
  CONTEXT_WARN: 0.8,        // the share of the context window from which its gauge warns
  TICK_MS: 1000,            // the running paper's state line, with its time so far, is set again this often
  NOTICE_MS: 6000,
  transcript: [],           // display entries of the running or latest paper
  transcriptKey: null,      // attachment whose run the transcript belongs to
  transcriptPath: null,     // the log of the conversation it belongs to; null until a new conversation has one
  draft: null,              // { text, block }: the message the agent is writing, until the whole message arrives
  draftTimer: null,
  DRAFT_MS: 80,             // the draft is set again at most this often
  MAX_ENTRIES: 3000,
  paneID: null,
  citations: new Map(),     // attachment key -> { at, size, map } the paper's numbered sentences, as sentences.json has them
  cites: null,              // { key, map } the sentences of the paper whose transcript is being drawn
  bridgeApi: null,          // { found(agent) } on Zotero.ScholiumBridge, for the settings page
  panes: new Map(),         // item pane section body -> { doc, keys, list, state, buttons, the conversation shown, seen }
  AGENTS: ["claude", "codex"],
  models: {},               // agent -> [{ value, label, title, efforts }] as the agent reports them; none until it answered
  modelsAsked: {},          // agent -> when it was last asked; a failed request is repeated at most once a minute
  modelsLoading: {},
  DEFAULT_MODEL: "opus",    // Claude Code's alias of the latest Opus, until another model is chosen; Codex starts at its own default
  EFFORTS: ["low", "medium", "high", "xhigh", "max"],   // when the model's levels are unknown
  DEFAULT_EFFORT: "medium", // until another level is chosen
  PANE_HEAD: 34,            // a section's header and its gap below the body, when they cannot be measured
  MIN_PANE: 360,            // the least height of a section
  chrome: "chrome://scholium-bridge/content/",   // the content folder; startup() puts the version into it
  version: "",              // the plugin's, which it gives Codex as its client version

  log(msg) { Zotero.debug("[scholium-bridge] " + msg); },

  zh() { return String(Zotero.locale || "").toLowerCase().startsWith("zh"); },

  text(key, ...args) {
    const zh = this.zh();
    const word = (k, one, many) => (k === 1 ? one : many);
    const plural = (k, one, many) => `${k} ${word(k, one, many)}`;
    const t = {
      headline: zh ? "Scholium 批注" : "Scholium annotation",
      noPdf: zh ? "这篇论文没有 PDF 附件。" : "This paper has no PDF attachment.",
      noFile: zh ? "这篇论文的 PDF 文件不在这台电脑上（还没下载，或已被移走）。" : "The paper's PDF file is not on this computer (not downloaded yet, or moved).",
      myLibraryOnly: zh ? "Scholium 只能批注“我的文库”里的论文。" : "Scholium annotates papers in My Library only.",
      noClaude: zh ? "找不到 Claude Code（claude.exe）。请在 Zotero 设置 → Scholium 里指定 Claude Code 程序。"
                   : "Claude Code (claude) was not found. Set its program in Zotero Settings → Scholium.",
      noCodex: zh ? "找不到 Codex（codex.exe）。请在 Zotero 设置 → Scholium 里指定 Codex 程序。"
                  : "Codex (codex) was not found. Set its program in Zotero Settings → Scholium.",
      settingsOpen: zh ? "设置…" : "Settings…",
      noSkill: agent => agent === "codex"
        ? (zh ? "Codex 找不到 zotero-scholium 技能：请把它放进 ~/.codex/skills/（见 README）。"
              : "Codex does not find the zotero-scholium skill: put it in ~/.codex/skills/ (see the README).")
        : (zh ? "Claude Code 找不到 zotero-scholium 技能：请把它放进 ~/.claude/skills/（见 README）。"
              : "Claude Code does not find the zotero-scholium skill: put it in ~/.claude/skills/ (see the README)."),
      redoTitle: zh ? "重新批注" : "Annotate again",
      redo: n => zh ? `这篇论文已有 ${n} 条 Scholium 批注。重新批注会替换它们，你自己的批注不受影响。继续吗？`
                    : `This paper already carries ${plural(n, "Scholium annotation", "Scholium annotations")}. Annotating again replaces them; your own annotations are not affected. Continue?`,
      typical: zh ? "已在后台开始，通常需要 10–20 分钟。过程和进度见条目侧栏的 Scholium 区块。"
                  : "Started in the background; this usually takes 10–20 minutes. The Scholium section of the item pane shows the process and the progress.",
      paneAgent: zh ? "智能体" : "Agent",
      paneModel: zh ? "模型" : "Model",
      paneEffort: zh ? "推理强度" : "Effort",
      agentSwitchNote: zh ? "换智能体会开一段新对话。" : "Switching agent starts a new conversation.",
      moreTitle: zh ? "更多" : "More",
      paneNoEffort: zh ? "不适用" : "n/a",
      paneClaudeDefault: zh ? "Claude Code 默认" : "Claude Code's default",
      paneClaudeDefaultModel: name => zh ? `Claude Code 默认（${name}）` : `Claude Code's default (${name})`,
      paneCodexDefault: zh ? "Codex 默认" : "Codex's default",
      paneCodexDefaultModel: name => zh ? `Codex 默认（${name}）` : `Codex's default (${name})`,
      annotateThis: zh ? "批注这篇" : "Annotate",
      deleteThis: zh ? "删除批注" : "Delete annotations",
      logButton: zh ? "打开日志" : "Show log",
      copyMessage: zh ? "复制这条回复（Markdown）" : "Copy this message (Markdown)",
      copiedMessage: zh ? "已复制" : "Copied",
      worked: d => zh ? `已处理 ${d}` : `Worked for ${d}`,
      working: zh ? "正在处理" : "Working",
      workedPlain: zh ? "已处理" : "Worked",
      profileOpen: zh ? "个人配置 ↗" : "Personal profile ↗",
      profileTitle: zh ? "个人配置" : "Personal profile",
      profileAbout: zh ? "每次批注都遵循这份个人配置。重新统计文库只改写开头的统计，Interpretation 和 User's rules 两节保持不变。"
                       : "Every run follows this profile. Deriving it again from the library rewrites only the statistics at the top; the Interpretation and User's rules sections are kept.",
      profileSave: zh ? "保存" : "Save",
      profileCancel: zh ? "取消" : "Cancel",
      profileKeys: key => zh ? `${key}+S 保存 · Esc 关闭` : `${key}+S to save · Esc to close`,
      profileNew: zh ? "文件还不存在，保存后创建" : "The file does not exist yet; saving creates it",
      profileDirty: zh ? "有未保存的修改" : "Unsaved changes",
      profileSaved: time => zh ? `已保存 ${time}` : `Saved at ${time}`,
      profileDiscard: zh ? "放弃未保存的修改吗？" : "Discard the unsaved changes?",
      profileChanged: zh ? "profile.md 在打开后被别处改动过（例如重新统计了文库）。用这里的内容覆盖它吗？"
                         : "profile.md was changed elsewhere after it was opened (for example by deriving it again from the library). Overwrite it with this text?",
      profileNotSaved: zh ? "未保存：文件已被别处改动" : "Not saved: the file was changed elsewhere",
      profileReadFailed: msg => zh ? `读不到个人配置文件：${msg}` : `The profile could not be read: ${msg}`,
      profileFailed: msg => zh ? `保存失败：${msg}` : `The profile could not be saved: ${msg}`,
      noHistory: zh ? "这篇还没有运行记录。" : "This paper has not been run yet.",
      queuedThis: n => zh ? `排队中，前面还有 ${n} 篇` : `Queued, ${n} ahead`,
      deleteTitle: zh ? "删除 Scholium 批注和笔记" : "Delete Scholium annotations and notes",
      deleteConfirm: (n, notes) => zh
        ? `将删除这篇论文上带 zotero-scholium 标签的${[n ? ` ${n} 条批注` : "", notes ? ` ${notes} 篇阅读笔记` : ""].filter(Boolean).join("和")}。`
          + [n ? "批注永久删除，不能撤销" : "", notes ? "笔记移到回收站，可以恢复" : ""].filter(Boolean).join("；")
          + "。你自己的批注和笔记都保留。删除会同步。继续吗？"
        : `This deletes ${[n ? plural(n, "annotation", "annotations") : "", notes ? plural(notes, "reading note", "reading notes") : ""]
            .filter(Boolean).join(" and ")} tagged zotero-scholium on this paper. `
          + [n ? "The annotations are deleted for good" : "", notes ? (n ? "the" : "The") + " notes go to the trash, where they can be restored" : ""]
            .filter(Boolean).join("; ")
          + ". Your own annotations and notes are kept. The deletion syncs. Continue?",
      deleteSkipped: zh ? "正在批注或排队的 PDF 不会删除。" : "A PDF being annotated or queued is skipped.",
      deleteNone: zh ? "这篇论文没有 Scholium 批注或笔记。" : "This paper carries no Scholium annotations or notes.",
      deleteDone: (n, notes) => zh
        ? [n || !notes ? `已删除 ${n} 条 Scholium 批注` : "", notes ? `${notes} 篇笔记已移到回收站` : ""].filter(Boolean).join("，") + "。"
        : [n || !notes ? `Deleted ${plural(n, "Scholium annotation", "Scholium annotations")}` : "",
           notes ? `${plural(notes, "note", "notes")} moved to the trash` : ""].filter(Boolean).join("; ") + ".",
      deleteFailed: msg => zh ? `删除失败：${msg}` : `Deletion failed: ${msg}`,
      starting: name => zh ? `启动 ${name}` : `starting ${name}`,
      skill: zh ? "加载技能" : "loading the skill",
      extract: zh ? "提取句子" : "extracting sentences",
      reading: zh ? "通读论文" : "reading the paper",
      writing: zh ? "撰写批注" : "writing the annotations",
      dryRun: zh ? "预演检查" : "checking (dry run)",
      applying: zh ? "写入 Zotero" : "writing to Zotero",
      done: zh ? "完成" : "done",
      failed: zh ? "失败" : "failed",
      cancelled: zh ? "已取消" : "cancelled",
      interrupted: zh ? "已中断" : "interrupted",
      interruptedLine: zh ? "运行被中断（插件更新或停用，或 Zotero 退出）" : "The run was interrupted (the plugin was updated or disabled, or Zotero quit)",
      noOutput: zh ? "（无输出）" : "(no output)",
      itemFailed: zh ? "失败" : "failed",
      itemDeclined: zh ? "已拒绝" : "declined",
      exitCode: n => zh ? `退出码 ${n}` : `exit ${n}`,
      noThread: zh ? "Codex 没有打开会话" : "Codex opened no conversation",
      codexSkills: msg => zh ? `Codex 列不出它的技能：${msg}` : `Codex could not list its skills: ${msg}`,
      codexSkillOff: zh ? "Codex 里的 zotero-scholium 技能被停用了：请在 Codex 里重新启用它。"
                        : "The zotero-scholium skill is switched off in Codex: switch it on there.",
      unfinished: zh ? "（这条回复没有写完）" : "(this message was not finished)",
      stepOf: (i, n, label) => zh ? `第 ${i}/${n} 步 ${label}` : `step ${i}/${n} ${label}`,
      stepCount: (i, n) => zh ? `第 ${i}/${n} 步` : `step ${i}/${n}`,
      running: (step, time) => zh ? `${step} · 已用 ${time}` : `${step} · ${time} so far`,
      reconnecting: (n, max) => zh ? `连接中断，正在重试${n && max ? `（${n}/${max}）` : ""}` : `connection lost, retrying${n && max ? ` (${n}/${max})` : ""}`,
      compactedTitle: title => zh ? `上下文已压缩：${title}` : `Context compacted: ${title}`,
      finished: title => zh ? `批注完成：${title}` : `Finished: ${title}`,
      answered: title => zh ? `已回答：${title}` : `Answered: ${title}`,
      failedLine: title => zh ? `批注失败：${title}` : `Failed: ${title}`,
      failedAsk: title => zh ? `回答失败：${title}` : `No answer: ${title}`,
      sendTip: zh ? "发送" : "Send",
      stopTip: zh ? "停止" : "Stop",
      queueTip: zh ? "排队" : "Queue",
      steerTip: zh ? "引导" : "Steer",
      compactNotNow: zh ? "现在不能压缩" : "Cannot compact now",
      escAgain: zh ? "再按一次 Esc 停止" : "Press Esc again to stop",
      // the queued messages above the message box, in Codex's words
      queueHeld: zh ? "由于你中断了当前响应，队列已暂停" : "Queue paused because you interrupted",
      queueGoOn: zh ? "继续" : "Resume",
      steerButton: zh ? "引导" : "Steer",
      steerRowTip: zh ? "提交，但不中断模型运行" : "Submit without interrupting the model",
      steerNotNow: zh ? "现在没有可引导的回答" : "No answer to steer right now",
      noSteer: a => zh ? `${a} 不支持引导` : `${a} does not support steering`,
      queuedSend: zh ? "发送" : "Send",
      queuedSending: zh ? "正在发送" : "Sending",
      queuedRemove: zh ? "删除" : "Delete queued message",
      queuedRemoved: zh ? "已删除" : "Deleted",
      queuedEdit: zh ? "编辑消息" : "Edit message",
      queueOff: zh ? "关闭排队" : "Turn off queueing",
      queuedFailedTip: zh ? "这条排队中的消息未能发送 · 重试、编辑或删除该消息以继续发送排队的消息"
                          : "This queued message could not be sent · Retry, edit, or delete it to continue the queue",
      clearQueueAsk: n => zh ? `发送消息？你即将发送一条消息。要清除之前已排队的 ${n} 条消息吗？`
                             : `Send message? You are about to send a message. Do you want to clear the ${plural(n, "message", "messages")} previously queued?`,
      clearQueue: zh ? "清空队列" : "Clear queue",
      sendMessage: zh ? "发送消息" : "Send message",
      sendHintEnter: zh ? "Enter 发送 · Shift+Enter 换行" : "Enter to send · Shift+Enter for a new line",
      sendHintMultiline: key => zh ? `Enter 发送 · 多行时 ${key}+Enter` : `Enter to send · ${key}+Enter for several lines`,
      askPlaceholder: zh ? "向这篇论文提问" : "Ask about this paper",
      followPlaceholder: zh ? "接着对话，例如：第 5 页那条译文改短一些" : "Continue the conversation, e.g. shorten the translation on page 5",
      sendHint: key => zh ? `${key}+Enter 发送` : `${key}+Enter to send`,
      extraLabel: zh ? "附加要求：" : "Extra instructions: ",
      continued: zh ? "额度已恢复，接着中断的地方继续" : "The usage limit has reset; continuing where the run stopped",
      continuedThrottle: zh ? "限流已解除，接着中断的地方继续" : "The service takes requests again; continuing where the run stopped",
      continuedUpdate: zh ? "插件已更新，接着中断的地方继续" : "The plugin was updated; continuing where the run stopped",
      retrying: zh ? "连接失败，30 秒后自动重试一次" : "The connection failed; trying once more in 30 seconds",
      goneStopped: agent => zh ? `${agent === "codex" ? "Codex 里原来的会话已经不存在了（例如在 Codex 应用里删掉了）" : "Claude Code 里原来的会话已经不存在了（例如已被 Claude Code 清理）"}，刚才的任务没法接着做；再发一条消息，会开一个新会话，带着这段对话接着聊。`
                               : `The session in ${agent === "codex" ? "Codex no longer exists (for example, it was deleted in the Codex app)" : "Claude Code no longer exists (for example, Claude Code cleaned it up)"}, so the task cannot go on; a new message starts a new session that is given this conversation.`,
      tabChat: zh ? "对话" : "Chat",
      tabAnnotate: zh ? "批注" : "Annotations",
      askScholium: zh ? "问 Scholium" : "Ask Scholium",
      quoteRemove: zh ? "不引用这段" : "Remove the quote",
      annotEmptyTitle: zh ? "还没有批注这篇" : "Not annotated yet",
      annotEmptyBody: zh ? "高亮重点句并附译文，加页边批注和阅读笔记。"
                         : "Highlights key sentences with translations, adds margin notes and a reading note.",
      annotExtraHint: zh ? "附加要求（可不填），例如：只批注第 3–5 页" : "Extra instructions (optional), e.g. only pages 3–5",
      annotFollowUpHint: zh ? "接着这次批注修改，例如：第 5 页那条译文改短" : "Continue this annotation, e.g. shorten the translation on page 5",
      redoInline: n => zh ? `重新批注会替换这篇的 ${n} 条 Scholium 批注（你自己的不动）。` : `Annotating again replaces this paper's ${n} Scholium annotations (yours stay).`,
      replace: zh ? "替换" : "Replace",
      cancelButton: zh ? "取消" : "Cancel",
      details: zh ? "详情" : "Details",
      annotDone: zh ? "✓ 批注完成" : "✓ Annotated",
      annotDoneClean: zh ? "✓ 批注完成，没有剩余警告" : "✓ Annotated, no warnings left",
      annotDoneWarn: w => zh ? `✓ 批注完成，剩余警告：${w}` : `✓ Annotated, warnings left: ${w}`,
      // the words beside the card's numbers
      numHighlights: (n, c) => zh ? `高亮（核心\u00a0${c}）` : `${word(n, "highlight", "highlights")} (${c}\u00a0core)`,
      numMargin: n => zh ? "页边批注" : word(n, "margin note", "margin notes"),
      numNotes: n => zh ? "便签" : word(n, "sticky note", "sticky notes"),
      numReading: n => zh ? "阅读笔记" : word(n, "reading note", "reading notes"),
      appliedBy: (a, d) => zh ? `上次由 ${a} 在 ${d} 写入` : `Last written by ${a} on ${d}`,
      newChat: zh ? "新对话" : "New chat",
      historyButton: zh ? "历史" : "History",
      historyEmpty: zh ? "没有别的对话。" : "No other conversations.",
      starter1: zh ? "这篇论文要解决什么问题？" : "What problem does this paper address?",
      starter2: zh ? "主要贡献有哪几点？" : "What are its main contributions?",
      starter3: zh ? "方法的核心思路是什么？" : "What is the core idea of the method?",
      starter4: zh ? "实验用了哪些数据和对比方法？" : "Which data and baselines do the experiments use?",
      starterLabel1: zh ? "问题" : "Problem",
      starterLabel2: zh ? "贡献" : "Contributions",
      starterLabel3: zh ? "方法" : "Method",
      starterLabel4: zh ? "实验" : "Experiments",
      savedAdd: zh ? "添加常用语句" : "Add prompt",
      savedLabel: zh ? "名称" : "Label",
      savedPrompt: zh ? "提示词" : "Prompt",
      savedSave: zh ? "保存" : "Save",
      savedCancel: zh ? "取消" : "Cancel",
      savedEdit: zh ? "编辑" : "Edit",
      savedDelete: zh ? "删除" : "Delete",
      otherAgentHas: name => zh ? `这篇论文在 ${name} 里有对话，把智能体换成 ${name} 就能接着聊。`
                                : `This paper has a conversation in ${name}; choose ${name} as the agent to go on with it.`,
      groupToday: zh ? "今天" : "Today",
      groupYesterday: zh ? "昨天" : "Yesterday",
      groupWeek: zh ? "7 天内" : "Previous 7 days",
      groupMonth: zh ? "30 天内" : "Previous 30 days",
      groupOlder: zh ? "更早" : "Older",
      renameConv: zh ? "重命名" : "Rename",
      deleteConv: zh ? "删除这段对话" : "Delete this conversation",
      convDeleted: title => zh ? `已删除「${title}」` : `Deleted “${title}”`,
      undo: zh ? "撤销" : "Undo",
      citePage: p => zh ? `第 ${p} 页` : `Page ${p}`,
      locate: zh ? "定位 ↗" : "Locate ↗",
      retry: zh ? "重试" : "Retry",
      editPrompt: zh ? "编辑" : "Edit",
      editSend: zh ? "发送" : "Send",
      editCancel: zh ? "取消" : "Cancel",
      replaced: zh ? "已替换" : "Replaced",
      compactingLine: zh ? "◌ 正在压缩上下文……" : "◌ Compacting context…",
      compactedLine: zh ? "上下文已压缩" : "Context compacted",
      compactedAuto: zh ? "上下文已自动压缩" : "Context compacted automatically",
      compactStopped: zh ? "压缩已中断" : "Compaction stopped",
      compactingState: d => zh ? `正在压缩 · ${d}` : `Compacting · ${d}`,
      compactedNotice: zh ? "上下文已压缩" : "Context compacted",
      compacting: zh ? "正在压缩" : "Compacting",
      contextLabel: zh ? "上下文窗口：" : "Context window:",
      contextUsed: (u, r) => zh ? `${u}% 已用（剩余 ${r}%）` : `${u}% used (${r}% left)`,
      contextTokens: (u, w) => zh ? `${u} / ${w} tokens` : `${u} / ${w} tokens used`,
      contextTitle2: zh ? "上下文窗口" : "Context window",
      contextShare: (u, w, s) => zh ? `${u} / ${w}（${s}%）` : `${u} / ${w} (${s}%)`,
      compactButton: zh ? "压缩此对话的上下文" : "Compact this conversation's context",
      compactNote: zh ? "早先的内容换成摘要，对话接着进行" : "Earlier content becomes a summary; the conversation goes on",
      partInput: zh ? "输入" : "Input",
      partCache: zh ? "缓存" : "Cache",
      partOutput: zh ? "输出" : "Output",
      retryWait: zh ? "等待第二次尝试" : "waiting for the second try",
      continuing: zh ? "接着上次的对话" : "continuing the conversation",
      continuedNotice: zh ? "已在后台接着上次的对话处理。" : "Continuing the conversation in the background.",
      askNotice: zh ? "已在后台开始回答。过程见条目侧栏的 Scholium 区块。" : "Answering in the background. The Scholium section of the item pane shows the process.",
      resumeNow: zh ? "现在继续" : "Continue now",
      limitTitle: name => zh ? `${name} 额度已用完` : `${name} usage limit reached`,
      throttleTitle: name => zh ? `${name} 服务暂时限流` : `${name} is limiting requests for now`,
      pausedState: time => zh ? `额度已用完，${time} 重置后自动继续` : `Usage limit reached; continues by itself after ${time}`,
      pausedRetry: time => zh ? `额度已用完，${time} 自动重试` : `Usage limit reached; retries by itself at ${time}`,
      throttledState: time => zh ? `服务暂时限流，${time} 自动继续` : `The service is limiting requests; continues by itself at ${time}`,
      lastRun: zh ? "上次：" : "Last run: ",
      turns: n => zh ? `${n} 轮` : plural(n, "turn", "turns"),
      codexExited: tail => zh ? `Codex app-server 已退出${tail ? "：" + tail : ""}` : `codex app-server exited${tail ? ": " + tail : ""}`,
      // the end of a Claude Code run that failed without a message of its own
      error_max_turns: zh ? "达到轮数上限" : "the turn limit was reached",
      error_max_budget_usd: zh ? "达到费用上限" : "the cost limit was reached",
      error_during_execution: zh ? "运行出错" : "the run failed",
      tokens: amount => `${amount} tokens`,
      tokIn: zh ? "输入" : "input",
      tokCacheWrite: zh ? "缓存写入" : "cache write",
      tokCacheRead: zh ? "缓存读取" : "cache read",
      tokOut: zh ? "输出" : "output",
    }[key];
    return typeof t === "function" ? t(...args) : t;
  },

  getPref(name) {
    try { return Zotero.Prefs.get(this.pref + name, true); } catch (e) { return undefined; }
  },

  // the send shortcut, the follow-up behaviour and the context ring, as the Scholium page of Zotero's settings has them
  sendShortcut() {
    const v = this.getPref("sendShortcut");
    return ["enter", "cmdIfMultiline", "cmdAlways"].includes(v) ? v : "cmdAlways";
  },

  followUpMode() { return this.getPref("followUpMode") === "steer" ? "steer" : "queue"; },

  contextRingOn() { return this.getPref("contextRing") !== false; },

  ESC_MS: 3000,   // the second Esc stops within this time

  // what Enter does in a message box under the send shortcut: "send", "invert" (the other way than the follow-up
  // behaviour, for this message only), or null (a new line). As in Codex: with Enter sending, Ctrl+Enter inverts; else
  // Ctrl+Shift+Enter
  sendKey(e, text) {
    if (e.key !== "Enter" || e.isComposing) return null;
    const mod = !!(e.ctrlKey || e.metaKey), shortcut = this.sendShortcut();
    if (shortcut === "enter") return mod ? "invert" : e.shiftKey ? null : "send";
    if (mod) return e.shiftKey ? "invert" : "send";
    return shortcut === "cmdIfMultiline" && !e.shiftKey && !String(text).includes("\n") ? "send" : null;
  },

  // whether the agent takes words into an answer under way: Codex's turn/steer; Claude Code answers a second message only
  // after the first one's result
  canSteer(agent) { return agent === "codex"; },

  // whether the words of a tab can go into the run under way: the tab's paper runs a turn of the tab's kind (no
  // compaction) that takes them; given a job, it is of that paper and kind
  steerable(pane, job = null) {
    const run = this.job;
    if (!run || !pane.keys.includes(run.key) || (run.source.kind || "chat") !== pane.tab || run.source.compact) return false;
    if (job && (job.att.key !== run.key || (job.kind || "chat") !== (run.source.kind || "chat"))) return false;
    // a turn being stopped takes no more words
    return this.canSteer(run.agent) && !!this.current && !this.current.cancelled && typeof this.current.steer === "function";
  },

  // words into the answer under way, as Codex's Steer: given to the agent without stopping it, and logged as the user's
  async steerFromPane(pane, say, quote = null) {
    if (!this.steerable(pane)) return false;
    const running = this.job;
    try { await this.current.steer(this.said({ say, quote })); }
    catch (e) { this.log("steer refused: " + e); return false; }
    const mark = Object.assign({ type: "scholium", subtype: "steer", text: say }, quote ? { quote } : {});
    try { if (running.log) await IOUtils.writeUTF8(running.log, JSON.stringify(mark) + "\n", { mode: "append" }); }
    catch (e) { this.log("steer not logged: " + e); }
    if (this.job === running) this.appendEntries(this.entries(mark));
    return true;
  },

  // whether words sent to a section's busy paper are queued or steered into its run: steered only into a turn that takes
  // them (no compaction, no turn being stopped)
  followUpFor(pane, invert = false) {
    const want = invert ? (this.followUpMode() === "queue" ? "steer" : "queue") : this.followUpMode();
    return want === "steer" && this.steerable(pane) ? "steer" : "queue";
  },

  kTokens(n) {
    const v = Number(n) || 0;
    return v < 1000 ? String(v) : Math.round(v / 1000).toLocaleString("en-US") + "k";
  },

  openSettings() {
    try { Zotero.Utilities.Internal.openPreferences(this.prefPaneID); } catch (e) { this.log("settings not opened: " + e); }
  },

  // the chosen agent: Claude Code until Codex is chosen
  agent() {
    return this.getPref("agent") === "codex" ? "codex" : "claude";
  },

  // the agent's name; `short` names the account whose usage limit it is
  agentName(agent, short = false) {
    return agent === "codex" ? "Codex" : short ? "Claude" : "Claude Code";
  },

  // the agent's chosen model; "" is the agent's own default
  modelPref(agent = this.agent()) {
    const value = this.getPref(agent + "Model");
    return typeof value === "string" ? value : agent === "claude" ? this.DEFAULT_MODEL : "";
  },

  // the effort a run gets: the chosen level, remembered across sessions, when the model accepts it;
  // else medium, or the model's lowest level; none for a model without levels
  effort(agent = this.agent()) {
    const levels = this.effortChoices(agent);
    const chosen = this.getPref(agent + "Effort");
    return levels.includes(chosen) ? chosen : levels.includes(this.DEFAULT_EFFORT) ? this.DEFAULT_EFFORT : levels[0] || "";
  },

  async exists(path) {
    try { return !!path && await IOUtils.exists(path); } catch (e) { return false; }
  },

  env(name) {
    try { return Services.env.get(name) || ""; } catch (e) { return ""; }
  },

  // the user's home directory ("" when unknown); PathUtils has no homeDir in Zotero
  home() {
    try {
      const path = Services.dirsvc.get("Home", Components.interfaces.nsIFile).path;
      if (path) return path;
    } catch (e) {}
    return this.env("USERPROFILE") || this.env("HOME");
  },

  // claude.exe directly (the npm shim is a .cmd file, which cannot be started without a shell): the one set on the
  // settings page, else the one found
  async findClaude() {
    const configured = this.getPref("claudePath");
    if (configured) return (await this.exists(configured)) ? configured : null;
    return this.autoClaude();
  },

  // claude.exe where it is usually installed, or on PATH
  async autoClaude() {
    const home = this.home();
    const win = Services.appinfo.OS === "WINNT";
    const exe = win ? "claude.exe" : "claude";
    const candidates = [];
    const appData = this.env("APPDATA");
    if (win && appData) candidates.push(PathUtils.join(appData, "npm", "node_modules", "@anthropic-ai", "claude-code", "bin", exe));
    if (home) candidates.push(PathUtils.join(home, ".local", "bin", exe), PathUtils.join(home, ".claude", "local", exe));
    if (!win) candidates.push("/opt/homebrew/bin/claude", "/usr/local/bin/claude", "/usr/bin/claude");
    for (const c of candidates) if (await this.exists(c)) return c;
    try { return await this.subprocess().pathSearch(exe); } catch (e) { return null; }
  },

  // the codex executable: the one set on the settings page, else the one found
  async findCodex() {
    const configured = this.getPref("codexPath");
    if (configured) return (await this.exists(configured)) ? configured : null;
    return this.autoCodex();
  },

  // the newest codex executable among the usual places: the Codex app keeps its own copy in a folder
  // that changes with each update, npm's package carries a native one (its shim is a .cmd file), and
  // Cargo, Homebrew and PATH may hold others. An older Codex may not read a newer one's config.toml.
  async autoCodex() {
    const home = this.home();
    const win = Services.appinfo.OS === "WINNT";
    const exe = win ? "codex.exe" : "codex";
    const candidates = [];
    if (win) {
      const local = this.env("LOCALAPPDATA") || (home ? PathUtils.join(home, "AppData", "Local") : "");
      if (local) {
        const bin = PathUtils.join(local, "OpenAI", "Codex", "bin");
        try { for (const dir of await IOUtils.getChildren(bin)) candidates.push(PathUtils.join(dir, exe)); } catch (e) {}
        candidates.push(PathUtils.join(bin, exe));
      }
      const appData = this.env("APPDATA");
      if (appData) {
        const pkg = PathUtils.join(appData, "npm", "node_modules", "@openai", "codex", "node_modules", "@openai");
        for (const [arch, triple] of [["x64", "x86_64-pc-windows-msvc"], ["arm64", "aarch64-pc-windows-msvc"]]) {
          const vendor = PathUtils.join(pkg, "codex-win32-" + arch, "vendor", triple);
          candidates.push(PathUtils.join(vendor, "bin", exe), PathUtils.join(vendor, "codex", exe));
        }
      }
    } else {
      candidates.push("/Applications/Codex.app/Contents/Resources/codex", "/opt/homebrew/bin/codex", "/usr/local/bin/codex");
    }
    if (home) candidates.push(PathUtils.join(home, ".cargo", "bin", exe), PathUtils.join(home, ".local", "bin", exe));
    try { candidates.push(await this.subprocess().pathSearch(exe)); } catch (e) {}
    let best = null;
    for (const path of new Set(candidates)) {
      if (!(await this.exists(path))) continue;
      const version = await this.codexVersion(path);
      if (version && (!best || this.newer(version, best.version))) best = { path, version };
    }
    return best ? best.path : null;
  },

  // the program of an agent the plugin finds by itself, whatever the settings page names: its grey text there
  foundProgram(agent) { return agent === "codex" ? this.autoCodex() : this.autoClaude(); },

  // "codex-cli 0.160.0" -> [0, 160, 0, ""]; null when it does not start or answer
  async codexVersion(path) {
    try {
      const proc = await this.subprocess().call({ command: path, arguments: ["--version"], stderr: "stdout" });
      const timer = setTimeout(() => { try { proc.kill(); } catch (e) {} }, 15000);
      let out = "";
      try {
        for (;;) { const s = await proc.stdout.readString(); if (!s) break; out += s; }
        await proc.wait();
      } finally { clearTimeout(timer); }
      const m = /(\d+)\.(\d+)\.(\d+)(-[\w.]+)?/.exec(out);
      return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4] || ""] : null;
    } catch (e) { return null; }
  },

  // whether version a is newer than b; a pre-release comes before its release
  newer(a, b) {
    for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
    return !a[3] && !!b[3];
  },

  subprocess() {
    const mod = ChromeUtils.importESModule("resource://gre/modules/Subprocess.sys.mjs");
    return mod.Subprocess || mod;
  },

  // a regular item resolves to its best PDF attachment; a PDF attachment to itself
  async resolve(item) {
    let att = item;
    if (item.isRegularItem && item.isRegularItem()) att = await item.getBestAttachment();
    if (!att || !att.isAttachment() || att.attachmentContentType !== "application/pdf") return null;
    const path = await att.getFilePathAsync();
    if (!path) return null;
    const parent = att.parentID ? Zotero.Items.get(att.parentID) : null;
    return { att, path, parentKey: parent ? parent.key : "", title: (parent || att).getDisplayTitle() };
  },

  // the message, after the conversation so far for a new session of it that is not given it otherwise
  prompt(job, own, history = true) {
    if (job.compact) return "/compact" + (job.say ? " " + job.say : "");
    const message = this.taskPrompt(job, own);
    const before = history ? this.historyText(job.history || []) : "";
    return before ? before + "\n\n" + message : message;
  },

  // what a session that has not seen them is told of the paper's annotations by this tool: how many, and the
  // configuration that wrote them when the plugin saw it written
  annotationLines(job, own) {
    const zh = this.zh();
    if (!own) return [zh ? "这篇论文目前没有本工具的批注。" : "The paper carries no annotations of this tool yet."];
    const a = job.applied;
    if (a) {
      return [zh ? `这篇论文已有 ${own} 条本工具的批注，是 ${this.agentName(a.agent)} 在 ${this.clock(a.at)} 用配置 ${a.config} 写入的，这份配置就是它们的全部；`
                   + "问到批注的内容时读这份配置。要改批注或补几条时，编辑它并设 cleanup: true 整份重写（阅读笔记也改时再设 note_replace: true）；"
                   + "不要另写只含新条目的配置。"
                 : `The paper carries ${own} annotations of this tool, written by ${this.agentName(a.agent)} at ${this.clock(a.at)} from the `
                   + `configuration ${a.config}, which holds the whole set; read it when asked about them. To change annotations or add a few, `
                   + "edit it and set cleanup: true, so that the whole set replaces them (and note_replace: true when the reading note changes); "
                   + "do not write a separate configuration with just new entries."];
    }
    return [zh ? `这篇论文已有 ${own} 条本工具的批注；问到它们的内容时，写一份只含 pdf、item_key、attachment_key、out_dir 的配置，用 --config <配置> --list --full 列出。`
                 + "要改批注或补几条时，编辑输出目录里写入它们的那份配置（它是这篇论文的全部批注），设 cleanup: true 整份重写"
                 + "（阅读笔记也改时再设 note_replace: true）；不要另写只含新条目的配置。"
               : `The paper carries ${own} annotations of this tool; when the question is about their content, list them with --config <a configuration with only pdf, item_key, attachment_key and out_dir> --list --full. `
                 + "To change annotations or add a few, edit the configuration in the output directory they were written from (it holds the paper's "
                 + "whole set) and set cleanup: true (and note_replace: true when the reading note changes); do not write a separate configuration "
                 + "with just new entries."];
  },

  // what a session that goes on is told of the annotations changed since its last run: rewritten in another of the
  // paper's conversations, or gone
  changedLines(job) {
    const zh = this.zh();
    if (!job.own && job.asking) return [];
    if (!job.own) return [zh ? "这篇论文现在没有本工具的批注（可能已在 Zotero 里删除）。" : "The paper carries no annotations of this tool now (they may have been deleted in Zotero)."];
    const a = job.applied;
    if (!a || a.conv === job.conv || !(a.at > (job.since || 0))) return [];
    return [zh ? `上次之后，${this.agentName(a.agent)} 在这篇论文的另一段对话里用配置 ${a.config} 重写了批注（${this.clock(a.at)}）；改批注前先读这份配置，不要用你记得的版本。`
               : `Since your last turn, ${this.agentName(a.agent)} rewrote the annotations from the configuration ${a.config} in another conversation `
                 + `about this paper (${this.clock(a.at)}); read that configuration before changing annotations, not the version you remember.`];
  },

  // the message itself: a follow-up in the agent's own session, a question (or a follow-up in a session the agent
  // starts), or the annotation task
  taskPrompt(job, own) {
    const outDir = this.outDir(job.att.key);
    // an annotation that continues a question's conversation gets the whole task
    if (job.resume && !job.annotate) return this.followUpPrompt(job);
    if (job.say) return this.questionPrompt(job, own);
    if (this.zh()) {
      return [
        "使用 zotero-scholium 技能，为下面这篇论文做整篇标注：重点句高亮加译文评论、页边批注、阅读笔记，按画像和默认值。",
        "",
        `- 条目 key：${job.parentKey}`,
        `- 附件 key：${job.att.key}`,
        `- PDF：${job.path}`,
        `- 输出目录：${outDir}`,
        job.profile ? `- 画像：${job.profile}` : "- 画像：没有；按默认值标注，不要生成或修改画像",
        "",
        "这是从 Zotero 里一键启动的无人值守任务：不要向用户提问，不要启动子代理，由你独立完成第 1–3 步并写入 Zotero。",
        own ? `这篇论文已有 ${own} 条本工具的注释，用户已确认整篇重做（配置里设 cleanup: true）。` : "这篇论文目前没有本工具的注释。",
        ...(job.extra ? ["", "用户的附加要求：", job.extra] : []),
        "",
        "结束时最后一行只写一句：高亮 N 条（核心 M 条），页边批注 K 条，笔记《标题》，剩余警告。",
      ].join("\n");
    }
    return [
      "Use the zotero-scholium skill to annotate the whole paper below: key-sentence highlights with translation comments, margin notes, and a reading note, following the profile and the defaults.",
      "",
      `- Item key: ${job.parentKey}`,
      `- Attachment key: ${job.att.key}`,
      `- PDF: ${job.path}`,
      `- Output directory: ${outDir}`,
      job.profile ? `- Profile: ${job.profile}` : "- Profile: none; annotate with the defaults and do not create or change a profile",
      "",
      "This is an unattended task started from Zotero with one click: do not ask the user anything and do not start sub-agents; complete steps 1-3 yourself and write to Zotero.",
      own ? `The paper already carries ${own} annotations of this tool; the user confirmed a complete redo (cleanup: true in the configuration).` : "The paper carries no annotations of this tool yet.",
      ...(job.extra ? ["", "The user's extra instructions:", job.extra] : []),
      "",
      "End with one line only: N highlights (M core), K margin notes, note “title”, remaining warnings.",
    ].join("\n");
  },

  // the user's words to a new session: the first message of a conversation, which answers without annotating, or the
  // next one of a conversation whose session is gone
  questionPrompt(job, own) {
    const outDir = this.outDir(job.att.key);
    const later = !!(job.history && job.history.length);   // a message of a conversation that a new session goes on with
    return (this.zh() ? [
      "使用 zotero-scholium 技能读下面这篇论文（status 给出题录，extract 给出正文），回答用户在 Zotero 里提的问题。",
      "",
      `- 条目 key：${job.parentKey}`,
      `- 附件 key：${job.att.key}`,
      `- PDF：${job.path}`,
      `- 输出目录：${outDir}`,
      job.profile ? `- 画像：${job.profile}` : "- 画像：没有；不要生成或修改画像",
      "",
      "这是从 Zotero 里发来的无人值守任务：不要向用户提问，不要启动子代理。只回答，不写批注和笔记；用户在问题里明确要求时，才按技能的流程写入 Zotero。",
      ...this.annotationLines(job, own),
      `引用论文原句时，在句末写它的句子编号，格式 [#123]（多句写 [#12][#15]）；编号来自 extract --sentences ${outDir}/sentences.json --out ${outDir}/sentences.txt（已有就直接读 sentences.txt）。`,
      "",
      later ? "用户的新消息：" : "用户的问题：",
      this.said(job),
      "",
      "写入了 Zotero 时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。",
    ] : [
      "Use the zotero-scholium skill to read the paper below (status gives its record, extract its text) and answer the question the user asked in Zotero.",
      "",
      `- Item key: ${job.parentKey}`,
      `- Attachment key: ${job.att.key}`,
      `- PDF: ${job.path}`,
      `- Output directory: ${outDir}`,
      job.profile ? `- Profile: ${job.profile}` : "- Profile: none; do not create or change a profile",
      "",
      "This is an unattended task sent from Zotero: do not ask the user anything and do not start sub-agents. Only answer; write no annotations "
        + "and no note unless the question asks for them, and then write to Zotero as the skill describes.",
      ...this.annotationLines(job, own),
      `When you quote a sentence of the paper, put its sentence number after it as [#123] (several: [#12][#15]); the numbers come from extract --sentences ${outDir}/sentences.json --out ${outDir}/sentences.txt (read sentences.txt when it is there).`,
      "",
      later ? "The user's new message:" : "The user's question:",
      this.said(job),
      "",
      "When you wrote to Zotero, end with one line only: what changed, remaining warnings. Leave that line out when only answering.",
    ]).join("\n");
  },

  // the user's words, after the passage they quote: its page in the PDF, with the page's label where it differs
  said(job) {
    const q = job.quote;
    if (!q || !q.text) return job.say;
    const lines = String(q.text).split("\n").map(l => "> " + l).join("\n");
    const zh = this.zh();
    const page = !q.page ? "" : zh ? `第 ${q.page} 页${q.label ? `（页码 ${q.label}）` : ""}` : `page ${q.page}${q.label ? ` (page label ${q.label})` : ""}`;
    const lead = zh ? (page ? `用户引用了${page}的这段原文：` : "用户引用了这段原文：")
                    : (page ? `The user quotes this passage from ${page}:` : "The user quotes this passage:");
    return lead + "\n" + lines + "\n\n" + job.say;
  },

  // a quoted passage as it is kept: its text, its page in the PDF (as sentences.txt and the citation chips count) and,
  // where it differs, the page's label; null without text
  quoteOf(q) {
    if (!q || !q.text) return null;
    const page = String(q.page || ""), label = String(q.label || "");
    return Object.assign({ text: String(q.text), page }, label && label !== page ? { label } : {});
  },

  // the point an edited question takes the session back to, as it is kept: Claude Code's message or Codex's turn; null
  // when it is neither
  pointOf(p) {
    if (p && typeof p.uuid === "string" && p.uuid) return { uuid: p.uuid };
    if (p && typeof p.turnId === "string" && p.turnId) return { turnId: p.turnId };
    return null;
  },

  // the page of a reader's selection: its number in the PDF, else its label
  pageOf(a) {
    const i = a.position ? a.position.pageIndex : -1;
    return typeof i === "number" && i >= 0 ? String(i + 1) : String(a.pageLabel || "");
  },

  // a quoted passage as the section shows it, with the page's label; the page only when the reader gave one
  quoteLabel(q) {
    return (q.page ? `p.${q.label || q.page} · ` : "") + q.text;
  },

  quoteTag(q) {
    return (q.page ? `[p.${q.page}] ` : "") + `"${q.text}"\n`;
  },

  // the next message of the paper's conversation: the user's words, or a continuation after the usage limit, a
  // limit of the service or an update of the plugin
  followUpPrompt(job) {
    const zh = this.zh();
    if (!job.say) {
      if (job.updated) return zh ? "插件更新打断了上面的任务。请从中断的地方继续完成，规则不变。"
                                  : "A plugin update interrupted the task above. Continue it from where it stopped; the rules are unchanged.";
      if (job.throttled) return zh ? "服务已恢复。请从中断的地方继续完成上面的任务，规则不变。"
                                    : "The service takes requests again. Continue the task above from where it stopped; the rules are unchanged.";
      return zh ? "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。"
                : "The usage limit has reset. Continue the task above from where it stopped; the rules are unchanged.";
    }
    const changed = this.changedLines(job);
    // in a question's conversation no configuration holds the paper's annotations
    if (this.asking(job)) {
      return (zh ? [
        "下面是用户在 Zotero 里针对这篇论文发来的后续消息。仍是无人值守：不要向用户提问，不要启动子代理。"
          + "只是提问就直接回答；用户明确要求写批注或笔记时，才按技能的流程写入 Zotero。",
        ...changed,
        "",
        this.said(job),
        "",
        "写入了 Zotero 时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。",
      ] : [
        "Below is a follow-up message about this paper, sent from Zotero. It is still unattended: do not ask the user anything and do not start sub-agents. "
          + "Answer a question directly; write annotations or a note only when the user asks for them, and then write to Zotero as the skill describes.",
        ...changed,
        "",
        this.said(job),
        "",
        "When you wrote to Zotero, end with one line only: what changed, remaining warnings. Leave that line out when only answering.",
      ]).join("\n");
    }
    return (zh ? [
      "下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。仍是无人值守：不要向用户提问，不要启动子代理。"
        + "只是提问就直接回答；要改批注时按技能的流程修改配置，再写入 Zotero。",
      ...(job.own ? ["改已经写入的批注或补几条时，都编辑写入它们的那份配置（它是这篇论文的全部批注），设 cleanup: true 整份重写"
                     + "（阅读笔记也改时再设 note_replace: true）；不要另写只含新条目的配置，否则下次整份重写时会把它们删掉。"] : []),
      ...changed,
      "",
      this.said(job),
      "",
      "改了批注时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。",
    ] : [
      "Below is a follow-up message about this paper and its annotations, sent from Zotero. It is still unattended: do not ask the user anything and do not start sub-agents. "
        + "Answer a question directly; to change annotations, edit the configuration as the skill describes and write it to Zotero again.",
      ...(job.own ? ["To change annotations already written or to add a few, edit the configuration they were written from (it holds the paper's whole "
                     + "set) and set cleanup: true, so that the whole set replaces them (and note_replace: true when the reading note changes); do not "
                     + "write a separate configuration with just new entries, which the next whole rewrite would delete."] : []),
      ...changed,
      "",
      this.said(job),
      "",
      "When annotations changed, end with one line only: what changed, remaining warnings. Leave that line out when only answering.",
    ]).join("\n");
  },

  outDir(key) { return PathUtils.join(Zotero.DataDirectory.dir, "tmp", "scholium", key); },

  args(job) {
    // the text arrives as it is written (stream events), and each whole message after it
    const args = ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                  "--permission-mode", this.getPref("claudePermissionMode") || "auto"];
    const home = this.home();
    if (home) args.push("--add-dir", PathUtils.join(home, ".claude", "skills", "zotero-scholium"));
    const outRoot = PathUtils.join(Zotero.DataDirectory.dir, "tmp", "scholium").replace(/\\/g, "/");
    args.push("--allowedTools", "Skill", "Read", `Write(${outRoot}/**)`, `Edit(${outRoot}/**)`);
    // the user's MCP servers and hooks stay out of the run; their skills stay
    args.push("--strict-mcp-config", "--settings", JSON.stringify({ disableAllHooks: true }));
    const model = this.modelPref("claude");
    if (model) args.push("--model", model);
    const effort = this.effort("claude");
    if (effort) args.push("--effort", effort);
    if (job && job.resume) {
      args.push("--resume", job.resume);
      // an edited question: the session as it was at that point, as a new session (the old one stays as it was)
      if (job.rewind && job.rewind.uuid) args.push("--resume-session-at", job.rewind.uuid, "--fork-session");
    }
    return args;
  },

  // map one stream-json event to a progress step
  step(event) {
    if (!event || event.type !== "assistant") return null;
    let step = null;
    for (const c of (event.message && event.message.content) || []) {
      if (!c || c.type !== "tool_use") continue;
      const input = c.input || {};
      const cmd = String(input.command || "");
      const file = String(input.file_path || "");
      if (c.name === "Skill") step = "skill";
      else if (this.commandStep(cmd)) step = this.commandStep(cmd);
      else if (c.name === "Read" && /sentences\.txt$/i.test(file)) step = "reading";
      else if ((c.name === "Write" || c.name === "Edit") && /scholium/i.test(file.replace(/\\/g, "/"))) step = "writing";
    }
    return step;
  },

  // the step of a command of the tool (scholium.py, or the scholium command), the furthest when one line
  // holds several: a write to Zotero, a dry run, extracting sentences
  commandStep(cmd) {
    if (!/\bscholium(?:\.py)?\b/.test(cmd)) return null;
    if (/--apply\b/.test(cmd)) return "applying";
    if (/--config\b/.test(cmd)) return "dryRun";
    if (/\bextract\b/.test(cmd)) return "extract";
    return null;
  },

  // the configuration a command of the tool writes to Zotero from, as the command names it; null for other commands
  appliedConfig(cmd) {
    if (this.commandStep(cmd) !== "applying") return null;
    const m = /--config(?:\s+|=)(?:"([^"]+)"|'([^']+)'|([^\s"']+))/.exec(cmd);
    return (m && (m[1] || m[2] || m[3])) || null;
  },

  // what the plugin saw write the paper's annotations last: { config, agent, conv, at }; null when it saw none
  appliedPath(key) { return PathUtils.join(this.outDir(key), "applied.json"); },

  // a write to Zotero that succeeded, kept whatever the run's end: a relative configuration is the one of the folders
  // it may have run in (the first given, then the output folder) that has it
  async noteApplied(key, config, agent, conv, base) {
    let path = config;
    if (!/^(?:[A-Za-z]:)?[\\/]/.test(config)) {
      const rel = config.replace(/^\.[\\/]/, "");
      // a Windows path takes no "/", which Gecko refuses
      const join = dir => (/^[A-Za-z]:|\\/.test(dir) ? (dir.replace(/[\\/]+$/, "") + "\\" + rel).replace(/\//g, "\\") : dir.replace(/[\\/]+$/, "") + "/" + rel);
      const candidates = [base, this.outDir(key)].filter(Boolean).map(join);
      path = candidates[0];
      for (const c of candidates) if (await this.exists(c)) { path = c; break; }
    }
    try { await IOUtils.writeUTF8(this.appliedPath(key), JSON.stringify({ config: path, agent, conv, at: Date.now() })); }
    catch (e) { this.log("applied configuration not kept: " + e); }
  },

  async readApplied(key) {
    try {
      const a = JSON.parse(await IOUtils.readUTF8(this.appliedPath(key)));
      return a && typeof a.config === "string" && a.config ? a : null;
    } catch (e) { return null; }
  },

  // map one Codex notification to a progress step: its shell commands, and its file changes in the
  // output folder
  codexStep(msg) {
    const item = (msg.method === "item/started" || msg.method === "item/completed") && msg.params && msg.params.item;
    if (!item) return null;
    if (item.type === "fileChange") {
      return (item.changes || []).some(c => c && /scholium/i.test(String(c.path || "").replace(/\\/g, "/"))) ? "writing" : null;
    }
    if (item.type !== "commandExecution") return null;
    const cmd = String(item.command || "");
    if (this.commandStep(cmd)) return this.commandStep(cmd);
    if (/sentences\.txt/i.test(cmd)) return "reading";
    if (/SKILL\.md/.test(cmd)) return "skill";
    return null;
  },

  // the command inside the shell Codex starts it in: `"C:\…\pwsh.exe" -Command 'python x.py'` -> python x.py
  shellCommand(command) {
    const s = String(command || "");
    const m = /^\s*(?:"([^"]+)"|(\S+))\s+(?:-\w+\s+)*?(?:-Command|-c|-lc|\/c)\s+([\s\S]+)$/i.exec(s);
    if (!m || !/(?:^|[\\/])(?:pwsh|powershell|bash|zsh|sh|cmd)(?:\.exe)?$/i.test(m[1] || m[2])) return s;
    const inner = m[3].trim();
    if (/^'[\s\S]*'$/.test(inner)) return inner.slice(1, -1).replace(/''/g, "'");
    if (/^"[\s\S]*"$/.test(inner)) return inner.slice(1, -1);
    return inner;
  },

  // a length of time as Claude Code and Codex give it: 45s, 6m 05s, 1h 02m 05s
  duration(ms) {
    const all = Math.max(0, Math.round(ms / 1000));
    const h = Math.floor(all / 3600), m = Math.floor((all % 3600) / 60), s = all % 60;
    const two = n => String(n).padStart(2, "0");
    return h ? `${h}h ${two(m)}m ${two(s)}s` : m ? `${m}m ${two(s)}s` : `${s}s`;
  },

  stepText(step) {
    const i = this.STEPS.indexOf(step);
    // a question's line says it works, without a step; an annotation's list of steps names them, so its line has the
    // count only
    if (i >= 0) {
      return this.job && this.job.asking ? this.text("working") : this.job && this.job.annotation ? this.text("stepCount", i + 1, this.STEPS.length)
        : this.text("stepOf", i + 1, this.STEPS.length, this.text(step));
    }
    return step && step !== "starting" ? this.text(step) : this.text("starting", this.agentName(this.job && this.job.agent));
  },

  // the running paper's state line: its step and the time so far
  runningState() {
    if (this.job.source && this.job.source.compact) return this.text("compactingState", this.duration(Date.now() - this.job.started));
    const retry = this.job.retry;
    const step = this.stepText(this.job.step) + (retry ? " · " + this.text("reconnecting", retry.attempt, retry.max) : "");
    return this.text("running", step, this.duration(Date.now() - this.job.started));
  },

  windows() {
    try { return Zotero.getMainWindows ? Zotero.getMainWindows() : [Zotero.getMainWindow()].filter(Boolean); }
    catch (e) { return []; }
  },

  refresh() { this.tidyHeld(); this.paintPanes(); },

  // the labels of the section's header and sidenav button, and the section's stylesheet, in a main window
  addToWindow(win) {
    try { if (win.MozXULElement) win.MozXULElement.insertFTLIfNeeded("scholium-bridge.ftl"); } catch (e) {}
    try {
      const doc = win.document;
      const href = this.chrome + "scholium.css";
      let link = doc.getElementById("scholium-bridge-style");
      // another version's sheet, left by a copy that a plugin update left running (see ScholiumToggle.start)
      if (link && link.getAttribute("href") !== href) { link.remove(); link = null; }
      if (!link) {
        link = doc.createElementNS("http://www.w3.org/1999/xhtml", "link");
        link.id = "scholium-bridge-style";
        link.setAttribute("rel", "stylesheet");
        link.setAttribute("href", href);
        doc.documentElement.append(link);
      }
    } catch (e) { this.log("stylesheet failed: " + e); }
  },

  removeFromWindow(win) {
    if (this.editor && this.editor.doc === win.document) this.closeProfile(this.editor, false);
    try {
      // a newer copy that replaced this copy's sheet keeps its sheet and its labels
      const style = win.document.getElementById("scholium-bridge-style");
      if (style && style.getAttribute("href") !== this.chrome + "scholium.css") return;
      if (style) style.remove();
      const link = win.document.querySelector('[href="scholium-bridge.ftl"]');
      if (link) link.remove();
    } catch (e) {}
  },

  // one stream-json event as display entries, in the manner of Claude Code's transcript
  entries(event) {
    const out = [];
    if (!event || typeof event !== "object") return out;
    if (typeof event.method === "string") return this.codexEntries(event);
    if (event.type === "system" && event.subtype === "init") {
      out.push({ kind: "info", model: true, text: `${this.agentName(event.agent === "codex" ? "codex" : "claude")} · ${event.model || "?"}` });
    }
    const content = event.message && Array.isArray(event.message.content) ? event.message.content : [];
    if (event.type === "assistant") {
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
    // the end of a run without a result of its own: cancelled, failed before a result, interrupted
    if (event.type === "scholium" && event.subtype === "end") {
      out.push(Object.assign({ kind: "final", text: String(event.text || "").trim() || this.text(event.outcome || "failed"), error: true },
                             event.outcome === "cancelled" ? { cancelled: true } : {}));
    }
    if (event.type === "scholium" && event.subtype === "retry") out.push({ kind: "info", text: this.text("retrying") });
    // the numbers an annotation's card shows, as counted when it ended
    if (event.type === "scholium" && event.subtype === "counts") {
      const n = k => Number(event[k]) || 0;
      out.push({ kind: "counts", highlights: n("highlights"), core: n("core"), margin: n("margin"), notes: n("notes"), readingNotes: n("readingNotes"),
                 warnings: typeof event.warnings === "string" ? event.warnings : null, turns: n("turns"), tokens: n("tokens"), at: n("at") });
    }
    // when a run ended, under what it showed
    if (event.type === "scholium" && event.subtype === "time" && event.at > 0) out.push({ kind: "time", text: this.clock(event.at), at: event.at });
    // a successful result repeats Claude's last message; only a failed run's result is shown, with Claude Code's errors
    // when it has no text, and not when they only say the session is gone (a new one goes on, or the end says why)
    if (event.type === "result" && (event.is_error || (event.subtype && event.subtype !== "success"))) {
      const errors = Array.isArray(event.errors) ? event.errors.map(String).join("\n") : "";
      if (event.result || !this.gone(errors)) out.push({ kind: "final", text: String(event.result || errors || this.failureText(event.subtype)).trim(), error: true });
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

  // PDF attachment keys of the item shown in an item pane
  paneKeys(item) {
    try {
      if (!item) return [];
      if (item.isRegularItem && item.isRegularItem()) return this.pdfAttachments([item]).map(a => a.key);
      if (item.isAttachment && item.isAttachment() && item.attachmentContentType === "application/pdf") return [item.key];
    } catch (e) {}
    return [];
  },

  // the Scholium section of the item pane (library and reader side pane)
  registerPane(pluginID) {
    const manager = Zotero.ItemPaneManager;
    if (!manager || typeof manager.registerSection !== "function") return;
    this.paneID = manager.registerSection({
      paneID: "scholium", pluginID,
      header: { l10nID: "scholium-section", icon: this.chrome + "icon16.svg" },
      sidenav: { l10nID: "scholium-sidenav", icon: this.chrome + "icon20.svg" },
      onItemChange: ({ item, setEnabled }) => { setEnabled(this.paneKeys(item).length > 0); },
      onRender: ({ doc, body, item }) => { this.renderPane(doc, body, item); },
      onAsyncRender: ({ body }) => this.loadHistory(body),
      onDestroy: ({ body }) => { this.dropPane(body); },
    }) || null;
  },

  // Ask Scholium under the colours of the reader's selection popup
  selectionButton({ reader, doc, params, append }) {
    const a = params && params.annotation;
    if (!a || !String(a.text || "").trim()) return;
    const b = doc.createElement("button");
    b.className = "toolbar-button wide-button scholium-ask";
    b.textContent = this.text("askScholium");
    b.addEventListener("click", () => { this.askAboutSelection(reader, a).catch(e => this.log("ask failed: " + e)); });
    append(b);
  },

  // the passage goes above the chat's box of the paper's section, in the window of the reader
  async askAboutSelection(reader, a) {
    const att = Zotero.Items.get(reader.itemID);
    if (!att) return;
    // the popup closes, as after a colour: the views' selection is cleared
    try {
      const ir = reader._internalReader;
      for (const view of [ir && ir._primaryView, ir && ir._secondaryView]) if (view && typeof view.clearSelection === "function") view.clearSelection();
    } catch (e) {}
    const quote = this.quoteOf({ text: String(a.text).replace(/\s+/g, " ").trim(), page: this.pageOf(a), label: a.pageLabel });
    const pane = this.paneFor(reader._window, att.key, reader.tabID || null);
    if (!pane) { this.pendingQuotes.set(att.key, quote); await this.revealSection(reader._window, null, reader.tabID || null); return; }
    pane.quote = quote;
    this.setTab(pane, "chat");
    await this.revealSection(reader._window, pane);
    try { pane.input.focus(); } catch (e) {}
  },

  // the section of a paper in a window: a reader's is the one of its side pane (the library's stays drawn behind the
  // reader's tab); else the one on screen when there are several
  paneFor(win, key, tabID = null) {
    let found = null;
    for (const pane of this.panes.values()) {
      if (!pane.keys.includes(key) || (win && pane.doc.defaultView !== win)) continue;
      if (tabID) {
        let details = null;
        try { details = pane.body.closest("item-details"); } catch (e) {}
        if (details && details.tabID === tabID) return pane;
        continue;
      }
      found = pane;
      try { if (pane.body.checkVisibility && pane.body.checkVisibility()) return pane; } catch (e) {}
    }
    return found;
  },

  // the section in view in the reader's side pane: the context pane opened, the section opened, the item pane scrolled to
  // it; each step may be missing. A section not drawn yet is found in the side pane of the reader's tab (Zotero draws it
  // once it is scrolled to)
  async revealSection(win, pane = null, tabID = null) {
    try { if (win && win.ZoteroContextPane && win.ZoteroContextPane.collapsed) win.ZoteroContextPane.collapsed = false; } catch (e) {}
    let section = null, details = null;
    try {
      if (pane && pane.body) { section = pane.body.closest("collapsible-section"); details = pane.body.closest("item-details"); }
      else if (tabID && win) {
        details = win.document.getElementById(tabID + "-context");
        const own = details && [...details.querySelectorAll("item-pane-custom-section")].find(c => c.dataset.pane === this.paneID);
        section = own && own.querySelector("collapsible-section");
      }
    } catch (e) {}
    try { if (section) section.open = true; } catch (e) {}
    try { if (details && typeof details.scrollToPane === "function") await details.scrollToPane(this.paneID); } catch (e) {}
  },

  dropPane(body) {
    const pane = this.panes.get(body);
    if (!pane) return;
    try { if (pane.observer) pane.observer.disconnect(); } catch (e) {}
    this.releaseFit(pane);
    this.releaseLayer(pane);
    this.panes.delete(body);
  },

  // a pane's layer and its document-level listener go with the pane
  releaseLayer(pane) {
    this.closePopover(pane);
    try { pane.doc.removeEventListener("mousedown", pane.outside, true); } catch (e) {}
  },

  // a small layer over the item pane, one at a time: the settings, the history, the context, a menu, a quoted sentence.
  // It is fixed in the window's document, since the pane's scroller would clip it; so it closes when the scroller scrolls
  // or the window resizes, and a click outside it or Esc closes it
  openPopover(pane, name, anchor, build) {
    this.closePopover(pane);
    const node = pane.doc.createElement("div");
    node.className = "scholium-popover " + name;
    node.addEventListener("keydown", e => { if (e.key === "Escape" && this.escape(pane)) { e.preventDefault(); e.stopPropagation(); } });
    build(node);
    pane.doc.documentElement.append(node);
    const win = pane.doc.defaultView;
    const close = () => { this.closePopover(pane); };
    const scroller = this.paneScroller(pane);
    try { scroller.addEventListener("scroll", close); } catch (e) {}
    try { win.addEventListener("resize", close); } catch (e) {}
    const off = () => {
      try { scroller.removeEventListener("scroll", close); } catch (e) {}
      try { win.removeEventListener("resize", close); } catch (e) {}
    };
    pane.popover = { name, node, anchor, off };
    this.placePopover(pane);
    return node;
  },

  closePopover(pane, name = null) {
    const p = pane.popover;
    if (!p || (name && p.name !== name)) return false;
    try { p.off(); } catch (e) {}
    try { p.node.remove(); } catch (e) {}
    pane.popover = null;
    return true;
  },

  // the item pane's scroller, or the section when the pane is not inside one
  paneScroller(pane) {
    let scroller = null;
    try { scroller = pane.body.closest("item-details")?._paneParent; } catch (e) {}
    return scroller || pane.box;
  },

  // below its anchor while that is in the upper half of the visible pane, else above it; within the pane's width
  placePopover(pane) {
    const p = pane.popover;
    try {
      const s = this.paneScroller(pane).getBoundingClientRect(), a = p.anchor.getBoundingClientRect();
      p.node.style.maxWidth = Math.floor(s.right - s.left) + "px";
      p.node.style.left = Math.max(s.left, Math.min(a.left, s.right - p.node.offsetWidth)) + "px";
      if (a.top - s.top < (s.bottom - s.top) / 2) { p.node.style.top = (a.bottom + 4) + "px"; p.node.style.bottom = ""; }
      else {
        const doc = pane.doc;
        p.node.style.bottom = ((doc.documentElement.clientHeight || doc.defaultView.innerHeight || s.bottom) - a.top + 4) + "px";
        p.node.style.top = "";
      }
    } catch (e) {}
  },

  // Esc in a section: closes a layer; else, while its paper runs, asks once and stops on the second press, of the same run
  escape(pane) {
    if (this.closePopover(pane)) return true;
    if (!pane.busy) return false;
    if (this.escArmed(pane)) {
      pane.escAt = 0;
      pane.escRun = null;
      this.stopFromPane(pane);
    } else {
      pane.escAt = Date.now();
      pane.escRun = this.job;
      setTimeout(() => this.paintHint(pane), this.ESC_MS + 50);
    }
    this.paintHint(pane);
    return true;
  },

  // whether a first Esc asks to stop: pressed a moment ago, on the run that still goes on. Once that run ends or another
  // starts, the press is forgotten, and paintPane's hint says so
  escArmed(pane) {
    return !!pane.escAt && Date.now() - pane.escAt < this.ESC_MS && pane.escRun === this.job;
  },

  // the run of the tab shown stops; a paper of it that only waits there leaves the queue, the other tab's wait stays. The
  // tab's queued messages stay, held until Resume, as Codex holds its queue after an interruption
  stopFromPane(pane) {
    const mine = j => pane.keys.includes(j.att.key) && (j.kind || "chat") === pane.tab;
    for (const j of this.queue) if (j.qid && mine(j)) this.heldQueues.add(this.queueKey(j));
    if (this.job && mine(this.job.source)) this.cancel();
    else this.dequeue(pane.keys, pane.tab, { rows: false });
  },

  paintHint(pane) {
    const armed = this.escArmed(pane);
    const mod = Services.appinfo && Services.appinfo.OS === "Darwin" ? "⌘" : "Ctrl";
    const shortcut = this.sendShortcut();
    pane.hint.textContent = armed ? this.text("escAgain")
      : shortcut === "enter" ? this.text("sendHintEnter") : shortcut === "cmdIfMultiline" ? this.text("sendHintMultiline", mod) : this.text("sendHint", mod);
  },

  // the context ring: an arc of the window's share the shown conversation's session takes up; its tooltip in Codex's words
  paintRing(pane) {
    const view = this.viewOf(pane, pane.tab);
    const c = view.live && this.showsRun(view) ? this.job.context : view.context;
    const used = c && c.used > 0 ? c.used : 0, win = c && c.window > 0 ? c.window : 0;
    const shown = this.contextRingOn() && used > 0 && win > 0;
    this.show(pane.ring, shown);
    if (!shown) return;
    const share = Math.min(100, Math.round(used / win * 100));
    pane.ring.className = "scholium-ring" + (used / win >= this.CONTEXT_WARN ? " warn" : "");
    pane.ring.style.setProperty("--share", share + "%");
    pane.ring.title = [this.text("contextLabel"), this.text("contextUsed", share, 100 - share),
                       this.text("contextTokens", this.kTokens(used), this.kTokens(win))].join("\n");
  },

  // the context layer: the numbers, a bar of input, cache and output, and the compaction of the conversation
  openContextLayer(pane) {
    if (this.closePopover(pane, "context")) return;
    const view = this.viewOf(pane, pane.tab);
    const c = (view.live && this.showsRun(view) ? this.job.context : view.context) || {};
    this.openPopover(pane, "context", pane.ring, node => {
      const doc = pane.doc;
      const row = (cls, ...kids) => { const d = doc.createElement("div"); d.className = cls; d.append(...kids); return d; };
      // a label and its number as two boxes of their row (two text nodes would run together as one)
      const span = text => { const s = doc.createElement("span"); s.textContent = text; return s; };
      const share = c.window > 0 ? Math.round(c.used / c.window * 100) : 0;
      node.append(row("scholium-context-head", span(this.text("contextTitle2")),
                      span(this.text("contextShare", this.kTokens(c.used), this.kTokens(c.window), share))));
      const p = c.parts;
      if (p && (p.input || p.cache || p.output) && c.window > 0) {
        const bar = row("scholium-context-bar"), legend = row("scholium-context-legend");
        for (const [k, label] of [["input", "partInput"], ["cache", "partCache"], ["output", "partOutput"]]) {
          const seg = doc.createElement("span");
          seg.className = "seg " + k;
          seg.style.setProperty("--w", (p[k] / c.window * 100).toFixed(2) + "%");
          bar.append(seg);
          legend.append(row("item " + k, span(this.text(label)), span(this.kTokens(p[k]))));
        }
        node.append(bar, legend);
      }
      const box = row("scholium-context-compact");
      const go = doc.createElement("button");
      go.className = "scholium-button small";
      go.textContent = this.text("compactButton");
      go.disabled = !view.shownKey || this.busy(view.shownKey) || !view.shownConv || !(c && c.used > 0);
      go.addEventListener("click", () => {
        this.closePopover(pane, "context");
        this.compactFromPane(pane).catch(e => this.log("compact failed: " + e));
      });
      const note = doc.createElement("div");
      note.textContent = this.text("compactNote");
      box.append(go, note);
      node.append(box);
    });
  },

  chipLabel() {
    const agent = this.agent();
    const model = this.modelChoices(agent).find(m => m.value === this.modelPref(agent));
    return [this.agentName(agent), model ? model.label : this.modelPref(agent), this.effort(agent)].filter(Boolean).join(" · ");
  },

  // the chip: the model, cut with an ellipsis where the line is narrow, then the effort in small grey and ▾, which stay;
  // the agent is in its tooltip and its layer
  paintChip(pane) {
    const doc = pane.doc, agent = this.agent();
    const model = this.modelChoices(agent).find(m => m.value === this.modelPref(agent));
    const name = doc.createElement("span");
    name.className = "scholium-chip-name";
    // an empty model is the agent's default
    name.textContent = (model && model.label) || this.modelPref(agent)
      || this.text(agent === "codex" ? "paneCodexDefault" : "paneClaudeDefault");
    const tail = doc.createElement("span");
    tail.className = "scholium-chip-tail";
    const effort = this.effort(agent);
    if (effort) {
      const e = doc.createElement("span");
      e.className = "scholium-chip-effort";
      e.textContent = effort;
      tail.append(e);
    }
    tail.append(doc.createTextNode("▾"));
    pane.chip.replaceChildren(name, tail);
    pane.chip.title = this.chipLabel();
  },

  paneField(doc, text, control) {
    const label = doc.createElement("label");
    label.className = "scholium-field";
    const caption = doc.createElement("span");
    caption.textContent = text;
    label.append(caption, control);
    return label;
  },

  openSettingsLayer(pane) {
    const doc = pane.doc;
    this.openPopover(pane, "settings", pane.chip, node => {
      const note = doc.createElement("div");
      note.className = "scholium-note";
      note.textContent = this.text("agentSwitchNote");
      node.append(this.paneField(doc, this.text("paneAgent"), pane.agent), note, this.paneField(doc, this.text("paneModel"), pane.model),
                  this.paneField(doc, this.text("paneEffort"), pane.effort));
    });
  },

  // the ⋯ menu; each item closes the layer first
  openMoreMenu(pane) {
    const doc = pane.doc;
    this.openPopover(pane, "menu", pane.more, node => {
      const item = (label, run, disabled = false) => {
        const b = doc.createElement("button");
        b.className = "scholium-menu-item";
        b.textContent = label;
        b.disabled = disabled;
        b.addEventListener("click", () => { this.closePopover(pane); run(); });
        return b;
      };
      const sep = doc.createElement("div");
      sep.className = "scholium-menu-sep";
      if (pane.tab === "annotate") {
        node.append(item(this.text("profileOpen"), () => { this.openProfile(doc); }),
                    item(this.text("logButton"), () => { this.revealLog(pane.annot.shownPath); }, !pane.annot.shownPath),
                    item(this.text("deleteThis"), () => { this.removeAnnotations([pane.item]).catch(e => this.log("delete failed: " + e)); },
                         pane.keys.some(k => this.busy(k))),
                    sep, item(this.text("settingsOpen"), () => { this.openSettings(); }));
        return;
      }
      node.append(item(this.text("logButton"), () => { this.revealLog(pane.shownPath); }, !pane.shownPath),
                  item(this.text("profileOpen"), () => { this.openProfile(doc); }), sep,
                  item(this.text("settingsOpen"), () => { this.openSettings(); }));
    });
  },

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
    } catch (e) { this.log("model list failed: " + e); }
    finally { this.modelsLoading[agent] = false; }
  },

  // Claude Code's models: the initialize request of its stream-json protocol answers without calling
  // a model; only the model list is kept

  async askModels() {
    const claude = await this.findClaude();
    if (!claude) return null;
    const proc = await this.subprocess().call({
      command: claude, arguments: ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                                   "--strict-mcp-config", "--settings", JSON.stringify({ disableAllHooks: true })],
      workdir: Zotero.DataDirectory.dir, stderr: "stdout",
    });
    const timer = setTimeout(() => { try { proc.kill(); } catch (e) {} }, 60000);
    try {
      await proc.stdin.write(JSON.stringify({ type: "control_request", request_id: "scholium-models",
                                              request: { subtype: "initialize" } }) + "\n");
      await proc.stdin.close();
      let buffer = "";
      for (;;) {
        const chunk = await proc.stdout.readString();
        if (!chunk) return null;
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
    } finally {
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

  // Codex's models and their effort levels (model/list), and the model its config.toml names
  // (config/read; nothing else of the configuration is kept); no model is called
  async askCodexModels() {
    const codex = await this.findCodex();
    if (!codex) return null;
    const rpc = await this.codexServer(codex, Zotero.DataDirectory.dir);
    const timer = setTimeout(() => rpc.close(), 60000);
    try {
      await this.codexHello(rpc);
      const list = await rpc.request("model/list", {});
      let configured = "";
      try {
        const read = await rpc.request("config/read", {});
        configured = String((read && read.config && read.config.model) || "");
      } catch (e) {}
      return this.codexModelOptions(list && list.data, configured);
    } finally {
      clearTimeout(timer);
      rpc.close();
    }
  },

  // Codex's model list as options; the empty value runs Codex's own default: the model of its
  // config.toml, else the one it marks as default. Hidden models are left out.
  codexModelOptions(list, configured = "") {
    if (!Array.isArray(list)) return null;
    const out = [];
    for (const m of list) {
      if (!m || typeof m.model !== "string" || !m.model || m.hidden || out.some(o => o.value === m.model)) continue;
      const efforts = Array.isArray(m.supportedReasoningEfforts)
        ? m.supportedReasoningEfforts.map(e => String(e && typeof e === "object" ? e.reasoningEffort || "" : e || "")).filter(Boolean)
        : this.EFFORTS;
      out.push({ value: m.model, label: String(m.displayName || m.model), title: String(m.description || ""), efforts });
    }
    if (!out.length) return null;
    const name = configured || (list.find(m => m && m.isDefault) || {}).model || "";
    const twin = out.find(o => o.value === name);
    out.unshift({ value: "", label: name ? this.text("paneCodexDefaultModel", twin ? twin.label : name) : this.text("paneCodexDefault"),
                  title: "", efforts: twin ? twin.efforts : this.EFFORTS });
    return out;
  },

  // the agent's model options: its list once it answered, and the chosen model in any case
  modelChoices(agent = this.agent()) {
    const saved = this.modelPref(agent);
    const list = this.models[agent]
      || [{ value: "", label: this.text(agent === "codex" ? "paneCodexDefault" : "paneClaudeDefault"), title: "", efforts: this.EFFORTS }];
    return list.some(m => m.value === saved) ? list : list.concat([{ value: saved, label: saved, title: "", efforts: this.EFFORTS }]);
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

  // the hidden attribute alone leaves an element on screen in Zotero's main window
  show(el, visible) {
    el.hidden = !visible;
    el.style.display = visible ? "" : "none";
  },

  paneButton(doc, label, onClick, look = "") {
    const button = doc.createElement("button");
    button.className = ("scholium-button " + look).trim();
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  },

  // a button that is an icon (content/<icon>16.svg, in the button's text colour); its words are its tooltip and
  // its accessible name
  iconButton(doc, icon, label, onClick, look = "quiet") {
    const button = this.paneButton(doc, "", onClick, `${look} glyph ${icon}`);
    const glyph = doc.createElement("span");
    glyph.className = "scholium-glyph";
    button.append(glyph);
    button.title = label;
    button.setAttribute("aria-label", label);
    return button;
  },

  // the real scroller of the item pane (the library's and the reader's alike), or null
  scrollParent(pane) {
    try { return pane.body.closest("item-details")?._paneParent || null; } catch (e) { return null; }
  },

  // a section as tall as its pane shows, so that its message box stays in view: the scroller's visible height less the
  // gaps between the section and its body, measured now
  fitPane(pane) {
    try {
      const scroller = pane.scroller || (pane.scroller = this.scrollParent(pane));
      if (!scroller) return;
      let gap = this.PANE_HEAD;
      const section = pane.body.closest("collapsible-section");
      if (section) {
        const s = section.getBoundingClientRect(), b = pane.body.getBoundingClientRect();
        if (s && b && isFinite(b.top - s.top + s.bottom - b.bottom)) gap = b.top - s.top + s.bottom - b.bottom;
      }
      pane.box.style.height = Math.max(this.MIN_PANE, Math.round(scroller.clientHeight - gap)) + "px";
      pane.queueBox.style.maxHeight = Math.round(scroller.clientHeight * 0.3) + "px";   // the queue, at most three tenths of it
    } catch (e) {}
  },

  // refit when the scroller's size changes. While the section is at the top of the pane, it stays there when a section
  // above it changes size (an attachment's row once its annotations are written, for one)
  watchFit(pane) {
    const scroller = pane.scroller;
    if (!scroller) return;
    const win = pane.doc.defaultView;
    const refit = () => { this.fitPane(pane); };
    const offset = () => {
      const section = pane.body.closest("collapsible-section");
      return section ? section.getBoundingClientRect().top - scroller.getBoundingClientRect().top : null;
    };
    let atTop = false;
    const seen = () => { const t = offset(); atTop = t !== null && Math.abs(t) <= 2; };
    const keep = () => { const t = offset(); if (atTop && t !== null && Math.abs(t) > 2) scroller.scrollTop += t; };
    if (win && win.ResizeObserver) {
      try {
        const o = new win.ResizeObserver(refit);
        o.observe(scroller);
        const above = new win.ResizeObserver(keep);
        const own = pane.body.closest("item-pane-custom-section");
        for (const c of scroller.children || []) if (c !== own) above.observe(c);
        scroller.addEventListener("scroll", seen);
        seen();
        pane.unfit = () => { o.disconnect(); above.disconnect(); scroller.removeEventListener("scroll", seen); };
        return;
      } catch (e) { this.log("resize observer failed: " + e); }
    }
    try {
      win.addEventListener("resize", refit);
      pane.unfit = () => { win.removeEventListener("resize", refit); };
    } catch (e) {}
  },

  // Zotero gives a section drawn while collapsed no async render when it is opened: its conversation is shown then
  watchOpen(pane) {
    let section = null;
    try { section = pane.body.closest("collapsible-section"); } catch (e) {}
    if (!section || typeof section.addEventListener !== "function") return;
    const opened = () => {
      if (section.open && this.panes.get(pane.body) === pane && !pane.showing) this.loadHistory(pane.body).catch(e => this.log("history failed: " + e));
    };
    section.addEventListener("toggle", opened);
    pane.unopen = () => { section.removeEventListener("toggle", opened); };
  },

  // the section's observers and listeners go with its pane
  releaseFit(pane) {
    try { if (pane.unfit) pane.unfit(); } catch (e) {}
    try { if (pane.unopen) pane.unopen(); } catch (e) {}
  },

  // a section's two views: the chat (the section itself, as before) and the annotation tab's
  viewOf(pane, kind) { return kind === "annotate" ? pane.annot : pane; },

  paneViews(pane) { return [pane, pane.annot]; },

  // whether a section's paper has a run of this kind going on or waiting; a held queued message does not wait for a run
  busyKind(pane, kind) {
    return !!(this.job && pane.keys.includes(this.job.key) && (this.job.source.kind || "chat") === kind)
      || this.queue.some(j => pane.keys.includes(j.att.key) && (j.kind || "chat") === kind && !this.isHeld(j));
  },

  // each tab keeps the words typed to it
  setTab(pane, kind) {
    const before = this.unsentKey(pane);
    this.keepUnsent(pane);
    pane.tab = kind === "annotate" ? "annotate" : "chat";
    this.closePopover(pane);
    this.show(pane.confirmRow, false);   // a question in place is the tab's it was asked on
    this.swapUnsent(pane, before);
    this.paintPane(pane);
  },

  renderPane(doc, body, item) {
    const old = this.panes.get(body);
    if (old) { this.releaseFit(old); this.releaseLayer(old); }
    body.replaceChildren();
    const keys = this.paneKeys(item);
    // shownKey, shownConv, shownPath: the conversation shown; live while that is the transcript of the running or latest
    // run; turns, question, context: what its log says of it
    const pane = { doc, body, item, keys, shownKey: null, shownConv: null, shownPath: null, live: false, history: false, past: null,
                   turns: 0, question: false, context: null, preferKey: old ? old.preferKey : null,
                   observer: old ? old.observer : null, seen: !!(old && old.seen), scroller: null, unfit: null };
    this.panes.set(body, pane);
    const win = doc.defaultView;
    if (!pane.observer && win && win.IntersectionObserver) {
      try {
        pane.observer = new win.IntersectionObserver(entries => {
          const current = this.panes.get(body);
          if (current && entries.length) current.seen = entries[entries.length - 1].isIntersecting;
        });
        pane.observer.observe(body);
      } catch (e) { this.log("observer failed: " + e); }
    }
    const div = (cls, text) => {
      const d = doc.createElement("div");
      d.className = cls;
      if (text) d.textContent = text;
      return d;
    };
    const box = pane.box = div("scholium-pane");
    pane.agent = doc.createElement("select");
    pane.model = doc.createElement("select");
    pane.effort = doc.createElement("select");
    pane.agent.className = pane.model.className = pane.effort.className = "scholium-select";
    pane.agent.addEventListener("change", () => { this.switchAgent(pane, pane.agent.value).catch(e => this.log("switch failed: " + e)); });
    pane.model.addEventListener("change", () => { this.choose(this.agent() + "Model", pane.model.value); });
    pane.effort.addEventListener("change", () => { this.choose(this.agent() + "Effort", pane.effort.value); });
    this.fillSelects(pane);
    // the tabs with the conversation tools and the ⋯ menu, then the settings chip with the state line; the selects live in
    // the chip's layer
    const head = div("scholium-tabs");
    const tab = (kind, label) => {
      const b = doc.createElement("button");
      b.className = "scholium-tab";
      b.setAttribute("role", "tab");
      const dot = doc.createElement("span");
      dot.className = "scholium-tab-dot";
      b.append(doc.createTextNode(label), dot);
      b.addEventListener("click", () => { this.setTab(pane, kind); });
      return [b, dot];
    };
    [pane.tabChat, pane.tabChatDot] = tab("chat", this.text("tabChat"));
    [pane.tabAnnotate, pane.tabAnnotateDot] = tab("annotate", this.text("tabAnnotate"));
    pane.newChat = this.paneButton(doc, "＋", () => { this.newChat(pane).catch(e => this.log("new chat failed: " + e)); }, "quiet icon");
    pane.newChat.title = this.text("newChat");
    pane.historyButton = this.paneButton(doc, "🕘", () => { this.toggleHistory(pane).catch(e => this.log("history failed: " + e)); }, "quiet icon");
    pane.historyButton.title = this.text("historyButton");
    pane.chip = doc.createElement("button");
    pane.chip.className = "scholium-chip";
    this.paintChip(pane);
    pane.chip.addEventListener("click", () => {
      if (!this.closePopover(pane, "settings")) this.openSettingsLayer(pane);
    });
    pane.more = doc.createElement("button");
    pane.more.className = "scholium-icon";
    pane.more.textContent = "⋯";
    pane.more.title = this.text("moreTitle");
    pane.more.addEventListener("click", () => {
      if (!this.closePopover(pane, "menu")) this.openMoreMenu(pane);
    });
    head.append(pane.tabChat, pane.tabAnnotate, div("scholium-spacer"), pane.newChat, pane.historyButton, pane.more);
    // a select's dropdown is the window's #ContentSelectDropdown: a choice there is inside the layer
    pane.outside = e => {
      const p = pane.popover;
      const dropdown = !!(e.target && typeof e.target.closest === "function" && e.target.closest("#ContentSelectDropdown"));
      if (p && !dropdown && !p.node.contains(e.target) && !(p.anchor && p.anchor.contains(e.target))) this.closePopover(pane);
    };
    doc.addEventListener("mousedown", pane.outside, true);
    box.addEventListener("keydown", e => { if (e.key === "Escape" && this.escape(pane)) { e.preventDefault(); e.stopPropagation(); } });
    const line = div("scholium-line");
    pane.state = div("scholium-state");          // one line of small text at the right
    pane.resume = this.paneButton(doc, this.text("resumeNow"), () => { this.resumeQueue(); }, "quiet small");
    line.append(pane.chip, pane.state, pane.resume);
    // the chat view: the earlier conversations and the transcript; the annotation view: its own transcript
    pane.chatView = div("scholium-view chat");
    pane.list = div("scholium-log");
    this.followLinks(pane.list, win);
    pane.chatView.append(pane.list);
    pane.annotView = div("scholium-view annotate");
    pane.annot = { kind: "annotate", doc, list: div("scholium-log"), shownKey: null, shownConv: null, shownPath: null, live: false,
                   history: false, turns: 0, question: false, context: null, draft: null, foldOpen: new Map(), pane };
    this.followLinks(pane.annot.list, win);
    // the introduction is the list's content until a session or a run is drawn there
    pane.annotIntro = this.introNode(doc);
    pane.annot.list.append(pane.annotIntro);
    pane.annotView.append(pane.annot.list);
    pane.kind = "chat";
    pane.pane = pane;               // a view's section: the chat view is the section itself
    pane.foldOpen = new Map();
    pane.tab = old ? old.tab : "chat";
    const pending = keys.map(k => this.pendingQuotes.get(k)).find(Boolean);
    if (pending) { pane.quote = pending; for (const k of keys) this.pendingQuotes.delete(k); pane.tab = "chat"; }
    else pane.quote = old && old.item === item ? old.quote || null : null;   // a quote is of the item it was chosen for
    // below the transcript, a message box as in a chat: a question or extra instructions for a new run, or a
    // follow-up; it grows with the text
    // the saved prompts above the chat's box (paintSaved)
    pane.saved = div("scholium-saved");
    const talk = pane.composer = div("scholium-composer");
    pane.input = doc.createElement("textarea");
    pane.input.className = "scholium-input";
    pane.input.setAttribute("rows", "1");
    // without Zotero's look for text boxes (a line under the text on focus, a grey ground on hover): the
    // box around it shows the focus
    pane.input.setAttribute("no-native", "true");
    pane.input.value = this.unsent.get(this.unsentKey(pane)) || "";   // what was typed here before and not sent
    pane.input.addEventListener("input", () => {
      this.keepUnsent(pane);
      this.fitInput(pane);
    });
    pane.input.addEventListener("keydown", e => {
      const what = this.sendKey(e, pane.input.value);
      if (!what || pane.composer.hidden) return;
      e.preventDefault();
      this.sendFromPane(pane, what === "invert");
    });
    // the messages queued while the paper runs, at the top of the box (paintQueue)
    pane.queueBox = div("scholium-queue");
    // a question in place of a dialog, above the words
    pane.confirmRow = div("scholium-confirm");
    this.show(pane.confirmRow, false);
    // the passage of the reader's selection that goes with the next message
    pane.quoteBox = div("scholium-quote");
    pane.sendRow = div("scholium-send-row");
    pane.hint = doc.createElement("span");
    pane.hint.className = "scholium-hint";
    // the context the conversation's session takes up, once its agent said
    pane.ring = doc.createElement("span");
    pane.ring.className = "scholium-ring";
    pane.ring.addEventListener("click", () => { this.openContextLayer(pane); });
    pane.send = doc.createElement("button");
    pane.send.className = "scholium-round send";
    pane.send.addEventListener("click", () => {
      if (pane.send.className.includes("stop")) this.stopFromPane(pane);
      else this.sendFromPane(pane);
    });
    // the annotation tab's button: Annotate, or Annotate again once the tab shows a session
    pane.annotGo = this.paneButton(doc, this.text("annotateThis"), () => { this.annotateFromPane(pane); }, "primary small");
    pane.sendRow.append(pane.hint, pane.ring, pane.send, pane.annotGo);
    talk.append(pane.queueBox, pane.confirmRow, pane.quoteBox, pane.input, pane.sendRow);
    box.append(head, line, pane.chatView, pane.annotView, pane.saved, talk);
    body.append(box);
    this.fitPane(pane);
    this.watchFit(pane);
    this.watchOpen(pane);
    // the running paper's transcript at once; another conversation once its log is read (loadHistory)
    if (this.job && keys.includes(this.job.key)) this.showLive(pane, this.job.key, this.job.source.kind || "chat");
    this.paintPane(pane);
    this.loadModels().catch(() => {});
  },

  // the annotation profile, <data dir>/zotero-scholium/profile.md, which every run follows; a missing
  // one starts as scholium.py's template, so that `scholium profile --from-library` keeps the rules
  PROFILE_TEMPLATE: "# Annotation profile\n\n## User's rules (always win)\n\n"
    + "Rules recorded in this section take precedence over the learned statistics above. Re-running\n"
    + "`profile --from-library` regenerates the sections above and leaves this section unchanged.\n\n"
    + "- (none yet; add rules here, e.g. \"comments are translations\", \"two colours only: red = core, yellow = other\")\n",

  profilePath() { return PathUtils.join(Zotero.DataDirectory.dir, "zotero-scholium", "profile.md"); },

  // the profile's editor: a sheet over the Zotero window of the button, one at a time. It is part of
  // the window's own page, like the section, so it needs no page or window of its own.
  openProfile(doc) {
    try {
      if (this.editor) {
        this.editor.input.focus();
        return this.editor;
      }
      return this.renderProfileEditor(doc);
    } catch (e) {
      this.log("profile editor failed: " + e);
      return null;
    }
  },

  // the editor: profile.md as it is, in a plain text box; the file keeps its line ends
  renderProfileEditor(doc) {
    const win = doc.defaultView;
    const el = (tag, cls, text) => {
      const e = doc.createElement(tag);
      e.className = cls;
      if (text) e.textContent = text;
      return e;
    };
    const ed = { doc, win, path: this.profilePath(), disk: null, eol: "\n", dirty: false, readFailed: false, message: null,
                 before: doc.activeElement };
    ed.root = el("div", "scholium-sheet-backdrop");
    ed.root.id = "scholium-profile-sheet";
    const sheet = el("div", "scholium-sheet");
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-label", this.text("profileTitle"));
    const head = el("div", "scholium-editor-head");
    const path = el("div", "scholium-editor-path", ed.path);
    path.title = ed.path;
    head.append(el("div", "scholium-sheet-title", this.text("profileTitle")), el("div", "scholium-editor-about", this.text("profileAbout")), path);
    // the text on the left, on the right as Markdown shows it, as it is typed
    ed.input = el("textarea", "scholium-editor");
    ed.input.setAttribute("spellcheck", "false");
    ed.input.addEventListener("input", () => {
      ed.dirty = true;
      ed.message = null;
      this.paintEditor(ed);
      this.paintPreview(ed);
    });
    ed.input.addEventListener("scroll", () => { this.syncPreview(ed); });
    ed.preview = el("div", "scholium-preview scholium-markdown");
    this.followLinks(ed.preview, win);
    const panes = el("div", "scholium-editor-panes");
    panes.append(ed.input, ed.preview);
    ed.status = el("span", "scholium-hint");
    ed.save = this.paneButton(doc, this.text("profileSave"), () => {
      this.saveProfile(ed).then(ok => { if (ok) this.closeProfile(ed, false); });
    }, "primary");
    const foot = el("div", "scholium-editor-foot");
    foot.append(ed.status, el("span", "scholium-spacer"),
                this.paneButton(doc, this.text("profileCancel"), () => { this.closeProfile(ed); }), ed.save);
    sheet.append(head, panes, foot);
    ed.root.append(sheet);
    // the sheet's keys stay in the sheet
    sheet.addEventListener("keydown", e => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        this.closeProfile(ed);
      } else if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        e.stopPropagation();
        this.saveProfile(ed);
      }
    });
    // back in Zotero from another program: the file as it is now, unless it is being edited here
    ed.onFocus = () => { if (!ed.dirty) this.loadProfile(ed); };
    win.addEventListener("focus", ed.onFocus);
    doc.documentElement.append(ed.root);
    this.editor = ed;
    return this.loadProfile(ed).then(() => { try { ed.input.focus(); } catch (e) {} return ed; });
  },

  async loadProfile(ed) {
    let text = null;
    try {
      if (await this.exists(ed.path)) text = await IOUtils.readUTF8(ed.path);
    } catch (e) {
      Object.assign(ed, { readFailed: true, message: { text: this.text("profileReadFailed", String(e && e.message || e)), error: true } });
      this.paintEditor(ed);
      return;
    }
    if (ed.loaded && text === ed.disk) return;
    // a missing profile starts as the template and is written on saving
    Object.assign(ed, { loaded: true, disk: text, eol: text && text.includes("\r\n") ? "\r\n" : "\n", dirty: false, readFailed: false, message: null });
    ed.input.value = (text === null ? this.PROFILE_TEMPLATE : text).replace(/\r\n/g, "\n");
    this.paintEditor(ed);
    this.paintPreview(ed);
  },

  async saveProfile(ed) {
    if (ed.readFailed) return false;
    try {
      const now = (await this.exists(ed.path)) ? await IOUtils.readUTF8(ed.path) : null;
      if (now !== ed.disk && !Services.prompt.confirm(ed.win, this.text("profileTitle"), this.text("profileChanged"))) {
        ed.message = { text: this.text("profileNotSaved"), error: true };
        this.paintEditor(ed);
        return false;
      }
      const text = String(ed.input.value).replace(/\r\n/g, "\n").replace(/\n/g, ed.eol);
      await IOUtils.makeDirectory(PathUtils.join(Zotero.DataDirectory.dir, "zotero-scholium"), { createAncestors: true, ignoreExisting: true });
      await IOUtils.writeUTF8(ed.path, text);
      Object.assign(ed, { disk: text, dirty: false, message: { text: this.text("profileSaved", this.clock(Date.now())), error: false } });
      this.paintEditor(ed);
      return true;
    } catch (e) {
      this.log("profile not saved: " + e);
      ed.message = { text: this.text("profileFailed", String(e && e.message || e)), error: true };
      this.paintEditor(ed);
      return false;
    }
  },

  mayCloseProfile(ed) {
    return !ed.dirty || Services.prompt.confirm(ed.win, this.text("profileTitle"), this.text("profileDiscard"));
  },

  // unsaved changes are kept unless the user lets them go; on shutdown and when the window closes, without asking
  closeProfile(ed, ask = true) {
    if (ask && !this.mayCloseProfile(ed)) return false;
    try { ed.win.removeEventListener("focus", ed.onFocus); } catch (e) {}
    ed.root.remove();
    if (this.editor === ed) this.editor = null;
    try { if (ed.before && ed.before.isConnected) ed.before.focus(); } catch (e) {}
    return true;
  },

  // the line under the text: an error or the last save, else unsaved changes, a new file, or the keys
  paintEditor(ed) {
    const m = ed.message;
    const key = Services.appinfo && Services.appinfo.OS === "Darwin" ? "⌘" : "Ctrl";
    ed.status.textContent = m && (m.error || !ed.dirty) ? m.text
      : ed.dirty ? this.text("profileDirty")
      : ed.disk === null ? this.text("profileNew")
      : this.text("profileKeys", key);
    ed.status.className = "scholium-hint" + (m && m.error ? " error" : "");
    ed.input.disabled = ed.readFailed;
    ed.save.disabled = ed.readFailed || (!ed.dirty && ed.disk !== null);
  },

  // the preview shows the text in the box, with its unsaved changes
  paintPreview(ed) {
    ed.preview.replaceChildren(...this.renderMarkdown(ed.doc, ed.input.value));
    this.syncPreview(ed);
  },

  // the preview follows the text box's scrolling, by proportion
  syncPreview(ed) {
    const room = ed.input.scrollHeight - ed.input.clientHeight;
    ed.preview.scrollTop = room > 0 ? ed.input.scrollTop / room * (ed.preview.scrollHeight - ed.preview.clientHeight) : 0;
  },

  // Markdown as elements: headings, paragraphs, nested lists, quotes, code blocks, rules, and the inline
  // forms; the text only ever becomes text, so nothing in it is run or loaded
  renderMarkdown(doc, text) {
    const out = [];
    // the line and paragraph separators (U+2028, U+2029) end lines too: `.` in the patterns below does not cross them
    const lines = String(text || "").replace(/\r\n?|[\u2028\u2029]/g, "\n").split("\n");
    const listItem = /^\s*([-*+]|\d{1,9}[.)])\s+/;
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const start = i;
      let m, next;
      if (!line.trim()) {
        i++;
      } else if ((m = /^\s{0,3}(```|~~~)/.exec(line))) {
        const body = [];
        for (i++; i < lines.length && !lines[i].trim().startsWith(m[1]); i++) body.push(lines[i]);
        i++;
        const pre = doc.createElement("pre");
        const code = doc.createElement("code");
        code.textContent = body.join("\n");
        pre.append(code);
        out.push(pre);
      } else if ((m = /^\s{0,3}(#{1,6})\s+(.*?)(\s+#+)?\s*$/.exec(line))) {
        const h = doc.createElement("h" + m[1].length);
        this.inlineMarkdown(doc, h, m[2]);
        out.push(h);
        i++;
      } else if (this.markdownRule(line)) {
        out.push(doc.createElement("hr"));
        i++;
      } else if (/^\s{0,3}>/.test(line)) {
        const body = [];
        for (; i < lines.length && /^\s{0,3}>/.test(lines[i]); i++) body.push(lines[i].replace(/^\s{0,3}>\s?/, ""));
        const quote = doc.createElement("blockquote");
        quote.append(...this.renderMarkdown(doc, body.join("\n")));
        out.push(quote);
      } else if (listItem.test(line)) {
        i = this.markdownList(doc, lines, i, out);
      } else if ((next = this.markdownMath(doc, lines, i, out)) > i) {
        i = next;
      } else if (this.markdownTableStart(lines, i)) {
        i = this.markdownTable(doc, lines, i, out);
      } else {
        const body = [line.trim()];
        for (i++; i < lines.length && lines[i].trim() && !this.markdownBlock(lines[i]) && !listItem.test(lines[i])
               && !this.markdownTableStart(lines, i); i++) body.push(lines[i].trim());
        const para = doc.createElement("p");
        this.inlineMarkdown(doc, para, body.join("\n"));
        out.push(para);
      }
      if (i <= start) i = start + 1;   // each block takes at least one line, so that the text always comes to an end
    }
    return out;
  },

  markdownRule(line) { return /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line); },

  markdownBlock(line) { return /^\s{0,3}(#{1,6}\s|>|```|~~~)/.test(line) || this.markdownRule(line); },

  // a table starts with a row of cells over a row of dashes, one for each cell
  markdownTableStart(lines, i) {
    const rule = lines[i + 1];
    return lines[i].includes("|") && rule !== undefined && rule.includes("|")
      && /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/.test(rule.trim())
      && this.markdownCells(lines[i]).length === this.markdownCells(rule).length;
  },

  // the cells of a table row, split at the bars that are not escaped
  markdownCells(line) {
    return line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
  },

  // the table from line i, its rows running to a blank line; returns the line after it
  markdownTable(doc, lines, i, out) {
    const align = this.markdownCells(lines[i + 1]).map(c => (c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : c.startsWith(":") ? "left" : ""));
    const row = (line, tag) => {
      const tr = doc.createElement("tr");
      const cells = this.markdownCells(line);
      align.forEach((a, k) => {
        const cell = doc.createElement(tag);
        if (a) cell.setAttribute("style", "text-align: " + a);
        this.inlineMarkdown(doc, cell, cells[k] || "");
        tr.append(cell);
      });
      return tr;
    };
    const table = doc.createElement("table");
    const head = doc.createElement("thead");
    head.append(row(lines[i], "th"));
    table.append(head);
    const rows = [];
    for (i += 2; i < lines.length && lines[i].trim() && lines[i].includes("|") && !this.markdownBlock(lines[i]); i++) rows.push(row(lines[i], "td"));
    if (rows.length) {
      const body = doc.createElement("tbody");
      body.append(...rows);
      table.append(body);
    }
    out.push(table);
    return i;
  },

  // a list from line i and the lists nested in it by indentation; returns the line after it
  markdownList(doc, lines, i, out) {
    const item = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
    const width = space => space.replace(/\t/g, "    ").length;
    const items = [];
    let blank = false;
    for (; i < lines.length; i++) {
      const line = lines[i];
      const m = item.exec(line);
      if (m) {
        items.push({ indent: width(m[1]), ordered: /\d/.test(m[2]), start: parseInt(m[2], 10), text: [m[3]] });
        blank = false;
      } else if (!line.trim()) {
        blank = true;
      } else if (items.length && (width(/^\s*/.exec(line)[0]) >= 2 || (!blank && !this.markdownBlock(line)))) {
        items[items.length - 1].text.push(line.trim());   // the item's text goes on
        blank = false;
      } else {
        break;
      }
    }
    const open = [];   // { indent, list, li } from the outermost list in
    for (const it of items) {
      while (open.length && open[open.length - 1].indent > it.indent) open.pop();
      let top = open[open.length - 1];
      // a bullet after a number, or the other way round, starts a list of its own
      if (top && top.indent === it.indent && top.ordered !== it.ordered) {
        open.pop();
        top = open[open.length - 1];
      }
      if (!top || it.indent > top.indent) {
        const list = doc.createElement(it.ordered ? "ol" : "ul");
        if (it.ordered && it.start !== 1) list.setAttribute("start", String(it.start));
        if (top && top.li) top.li.append(list);
        else out.push(list);
        top = { indent: it.indent, ordered: it.ordered, list, li: null };
        open.push(top);
      }
      const li = doc.createElement("li");
      this.inlineMarkdown(doc, li, it.text.join("\n"));
      top.list.append(li);
      top.li = li;
    }
    return i;
  },

  // a formula set apart from line i: $$ … $$ or \[ … \], on one line or several; returns the line after
  // it, or i when none starts there
  markdownMath(doc, lines, i, out) {
    const m = /^\s{0,3}(\$\$|\\\[)(.*)$/.exec(lines[i]);
    if (!m) return i;
    const close = m[1] === "$$" ? "$$" : "\\]";
    const body = [];
    for (let j = i; j < lines.length; j++) {
      const text = j === i ? m[2] : lines[j];
      const end = text.indexOf(close);
      if (end < 0) {
        if (j > i && !text.trim()) return i;   // a blank line before its end: no formula
        body.push(text);
        continue;
      }
      if (text.slice(end + close.length).trim()) return i;   // text after it: a paragraph
      body.push(text.slice(0, end));
      const tex = body.join("\n").trim();
      if (!tex) return i;
      const box = doc.createElement("div");
      box.className = "scholium-math";
      const math = this.mathNode(doc, tex, true);
      if (math) box.append(math);
      else {   // the source, when KaTeX cannot read it
        const code = doc.createElement("code");
        code.textContent = lines.slice(i, j + 1).join("\n").trim();
        box.append(code);
      }
      out.push(box);
      return j + 1;
    }
    return i;
  },

  // KaTeX (content/katex/katex.min.js), loaded when the first formula is set; null when it cannot be
  katex() {
    if (this.katexLib === undefined) {
      this.katexLib = null;
      try {
        const scope = { module: { exports: {} } };
        scope.exports = scope.module.exports;
        Services.scriptloader.loadSubScript(this.chrome + "katex/katex.min.js", scope);
        if (typeof scope.module.exports.renderToString === "function") this.katexLib = scope.module.exports;
      } catch (e) { this.log("KaTeX not loaded: " + e); }
    }
    return this.katexLib;
  },

  // a formula in TeX as MathML, which Zotero sets itself; null when KaTeX cannot read it. KaTeX runs
  // untrusted (no links, pictures or classes from the TeX), and of what it writes only MathML elements
  // and attributes are kept.
  mathNode(doc, tex, display) {
    const key = (display ? "D" : "I") + tex;
    let node = this.mathCache.get(key);
    if (node === undefined) {
      node = null;
      const katex = this.katex();
      const win = doc.defaultView;
      if (katex && win && win.DOMParser) {
        try {
          const markup = katex.renderToString(tex, { output: "mathml", displayMode: display, throwOnError: true, trust: false, strict: "ignore" });
          const math = new win.DOMParser().parseFromString(markup, "text/html").querySelector("math");
          if (math) node = this.cleanMath(math);
        } catch (e) {}
      }
      this.mathCache.set(key, node);
      if (this.mathCache.size > 500) this.mathCache.delete(this.mathCache.keys().next().value);   // the oldest
    }
    return node ? doc.importNode(node, true) : null;
  },

  MATH_TAGS: new Set(["math", "semantics", "annotation", "mrow", "mi", "mn", "mo", "ms", "mtext", "mspace", "msub", "msup", "msubsup",
                      "munder", "mover", "munderover", "mfrac", "msqrt", "mroot", "mstyle", "mpadded", "mphantom", "menclose",
                      "mtable", "mtr", "mtd", "mlabeledtr", "merror", "mmultiscripts", "mprescripts", "none"]),
  MATH_ATTRS: new Set(["xmlns", "display", "encoding", "mathvariant", "mathcolor", "mathbackground", "mathsize", "stretchy", "fence",
                       "separator", "lspace", "rspace", "minsize", "maxsize", "symmetric", "largeop", "movablelimits", "accent",
                       "accentunder", "form", "linethickness", "columnalign", "rowalign", "columnspacing", "rowspacing", "columnlines",
                       "rowlines", "frame", "framespacing", "equalrows", "equalcolumns", "displaystyle", "scriptlevel", "width",
                       "height", "depth", "voffset", "notation"]),

  // only MathML elements and attributes: anything else KaTeX might write is left out
  cleanMath(el) {
    for (const name of el.getAttributeNames()) if (!this.MATH_ATTRS.has(name)) el.removeAttribute(name);
    for (const child of [...el.children]) {
      if (this.MATH_TAGS.has(child.localName)) this.cleanMath(child);
      else child.remove();
    }
    return el;
  },

  // `code` (a colour code with a swatch of its colour), formulas (\( \), $ $, and set apart \[ \], $$ $$),
  // backslash escapes, **bold**, *italics*, [links](…) and bare web addresses. A link shows its text with the
  // address as tooltip; the transcript and the profile preview open web and zotero: addresses on a click
  // (followLinks). A $ opens a formula before a non-space and closes one after a non-space that no digit
  // follows, so that prices stay text.
  inlineMarkdown(doc, parent, text, inLink = false) {
    const re = new RegExp([
      "`([^`\\n]+)`",                                  // 1 code
      "\\$\\$([^$]+?)\\$\\$",                          // 2 formula set apart
      "\\\\\\[([\\s\\S]+?)\\\\\\]",                    // 3 formula set apart
      "\\\\\\(([\\s\\S]+?)\\\\\\)",                    // 4 formula
      "\\$(?=[^\\s$])([^$\\n]*?[^\\s$\\\\])\\$(?!\\d)", // 5 formula
      "\\\\([!-/:-@[-`{-~])",                          // 6 an escaped punctuation mark
      "\\*\\*([^*\\n]+?)\\*\\*",                       // 7 bold
      "\\*([^*\\s][^*\\n]*?)\\*",                      // 8 italics
      "\\[([^\\]\\n]+)\\]\\(([^)\\s]+)\\)",            // 9, 10 link
      "((?:https?|zotero)://[^\\s<>\"'`()（）\\[\\]{}，。；：！？、]+)",   // 11 a bare address
      "\\[#(\\d{1,6})\\]",                             // 12 a sentence of the paper
    ].join("|"), "g");
    let at = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m.index > at) parent.append(doc.createTextNode(text.slice(at, m.index)));
      if (m[11] !== undefined) {   // punctuation after an address ends the sentence, not the address
        // nor is Chinese written right after it: "见https://x.org/abs/1234的图"; a path or query value of Chinese
        // words follows / = # ? or & ("https://zh.example/页")
        let n = 0;
        while (n < m[11].length && m[11].charCodeAt(n) < 0x2e80) n++;
        const own = n === m[11].length || "/=#?&".includes(m[11][n - 1]) ? m[11] : m[11].slice(0, n);
        const address = own.replace(/[.,;:!?]+$/, "");
        re.lastIndex = m.index + address.length;
        at = re.lastIndex;
        parent.append(inLink ? doc.createTextNode(address) : this.linkNode(doc, address, address));
        continue;
      }
      at = re.lastIndex;
      if (m[12] !== undefined) {
        const found = this.cites && this.cites.map.get(Number(m[12]));
        parent.append(found ? this.citeNode(doc, this.cites.key, Number(m[12]), found) : doc.createTextNode(m[0]));
        continue;
      }
      if (m[2] !== undefined || m[3] !== undefined || m[4] !== undefined || m[5] !== undefined) {
        const display = m[2] !== undefined || m[3] !== undefined;
        const math = this.mathNode(doc, (m[2] ?? m[3] ?? m[4] ?? m[5]).trim(), display);
        if (!math) parent.append(doc.createTextNode(m[0]));   // the source, when KaTeX cannot read it
        else if (!display) parent.append(math);
        else {
          const box = doc.createElement("span");
          box.className = "scholium-math";
          box.append(math);
          parent.append(box);
        }
        continue;
      }
      if (m[6] !== undefined) {
        parent.append(doc.createTextNode(m[6]));
        continue;
      }
      if (m[1] !== undefined) {
        const code = doc.createElement("code");
        if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(m[1])) {
          const swatch = doc.createElement("span");
          swatch.className = "scholium-swatch";
          swatch.setAttribute("style", "background-color: " + m[1]);
          code.append(swatch);
        }
        code.append(doc.createTextNode(m[1]));
        parent.append(code);
      } else if (m[7] !== undefined) {
        const strong = doc.createElement("strong");
        this.inlineMarkdown(doc, strong, m[7]);
        parent.append(strong);
      } else if (m[8] !== undefined) {
        const em = doc.createElement("em");
        this.inlineMarkdown(doc, em, m[8]);
        parent.append(em);
      } else if (inLink) {
        this.inlineMarkdown(doc, parent, m[9], true);
      } else {
        const link = this.linkNode(doc, m[10]);
        this.inlineMarkdown(doc, link, m[9], true);
        parent.append(link);
      }
    }
    if (at < text.length) parent.append(doc.createTextNode(text.slice(at)));
  },

  // the paper's numbered sentences, for the citations in answers: read again when the file changed
  async loadCitations(key) {
    if (!key) return;
    const path = PathUtils.join(this.outDir(key), "sentences.json");
    let stat = null;
    try { stat = await IOUtils.stat(path); } catch (e) { this.citations.delete(key); return; }
    const had = this.citations.get(key);
    if (had && had.at === stat.lastModified && had.size === stat.size) return;
    let raw;
    try { raw = await IOUtils.readUTF8(path); } catch (e) { this.log("sentences not read: " + e); return; }   // tried again at the next draw
    const map = new Map();
    try {
      const data = JSON.parse(raw);
      for (const x of (data && data.sentences) || []) {
        if (x && Number.isInteger(x.id) && x.page > 0) map.set(x.id, { page: x.page, text: String(x.text || ""), rects: this.positionRects(x.rects) });
      }
    } catch (e) { map.clear(); this.log("sentences not parsed: " + e); }
    this.citations.set(key, { at: stat.lastModified, size: stat.size, map });
  },

  // a sentence's position in sentences.json: its rectangles of four finite numbers, or null when it has none
  positionRects(rects) {
    const kept = Array.isArray(rects)
      ? rects.filter(r => Array.isArray(r) && r.length === 4 && r.every(v => typeof v === "number" && Number.isFinite(v))) : [];
    return kept.length ? kept : null;
  },

  withCites(key, fn) {
    const before = this.cites;
    const c = key && this.citations.get(key);
    this.cites = c ? { key, map: c.map } : null;
    try { return fn(); } finally { this.cites = before; }
  },

  // a cited sentence as a chip with its page
  citeNode(doc, key, id, s) {
    const chip = doc.createElement("span");
    chip.className = "scholium-cite";
    chip.setAttribute("data-id", String(id));
    chip.textContent = `p.${s.page}`;
    chip.addEventListener("mouseenter", () => this.openCiteCard(chip, key, s));
    chip.addEventListener("mouseleave", () => { const pane = this.paneOf(chip); if (pane) this.citeAway(pane); });
    chip.addEventListener("click", () => { this.locate(key, s).catch(e => this.log("locate failed: " + e)); });
    return chip;
  },

  // a cited sentence on hover: its page, Locate at the top right, the sentence. It closes when the pointer is on neither
  // the chip nor the card
  openCiteCard(chip, key, s) {
    const pane = this.paneOf(chip);
    if (!pane || (pane.popover && pane.popover.name !== "cite")) return;
    pane.citeHover = 1;
    const node = this.openPopover(pane, "cite", chip, card => {
      const doc = pane.doc;
      const head = doc.createElement("div");
      head.className = "scholium-cite-head";
      const page = doc.createElement("span");
      page.textContent = this.text("citePage", s.page);
      const go = this.paneButton(doc, this.text("locate"), () => { this.closePopover(pane, "cite"); this.locate(key, s).catch(e => this.log("locate failed: " + e)); }, "quiet small");
      head.append(page, go);
      const text = doc.createElement("div");
      text.className = "scholium-cite-text";
      text.textContent = s.text;
      card.append(head, text);
    });
    node.addEventListener("mouseenter", () => { pane.citeHover++; });
    node.addEventListener("mouseleave", () => this.citeAway(pane));
  },

  citeAway(pane) {
    if (!pane.popover || pane.popover.name !== "cite") return;
    pane.citeHover--;
    setTimeout(() => { if (pane.citeHover <= 0) this.closePopover(pane, "cite"); }, 300);
  },

  // the section that shows a node (a card lives in the window's root, so its pane is found from its chip)
  paneOf(node) {
    for (const pane of this.panes.values()) if (pane.body && pane.body.contains(node)) return pane;
    return null;
  },

  // a cited sentence in the paper's reader: the reader opens (or is switched to) at the sentence's position, which it
  // centres and highlights for a moment; a tab there but not loaded is selected with it. A sentence without a position
  // opens its page
  async locate(key, s) {
    if (!s || !s.page) return;
    const pane = [...this.panes.values()].find(p => p.keys.includes(key) && p.item);
    const att = pane && Zotero.Items.getByLibraryAndKey(pane.item.libraryID, key);
    if (!att) return;
    const pageIndex = s.page - 1;
    try { await Zotero.Reader.open(att.id, s.rects ? { position: { pageIndex, rects: s.rects } } : { pageIndex }); }
    catch (e) { this.log("sentence not shown in the reader: " + e); }
  },

  LINK_SCHEMES: /^(?:https?|zotero):/i,

  // a link's text with its address as tooltip; an address Zotero can open is kept for a click
  linkNode(doc, address, text = null) {
    const link = doc.createElement("span");
    link.className = "scholium-link";
    link.title = address;
    if (this.LINK_SCHEMES.test(address)) {
      link.setAttribute("data-href", address);
      link.setAttribute("role", "link");
      link.setAttribute("tabindex", "0");
    }
    if (text !== null) link.append(doc.createTextNode(text));
    return link;
  },

  // a link in `node` opens on a click (not when the click ends a selection in it) or with Enter
  followLinks(node, win) {
    node.addEventListener("click", e => {
      const link = e.target && e.target.closest && e.target.closest(".scholium-link[data-href]");
      const sel = win && win.getSelection && win.getSelection();
      if (!link || (sel && !sel.isCollapsed && link.contains(sel.anchorNode))) return;
      e.preventDefault();
      this.openLink(link.getAttribute("data-href"));
    });
    node.addEventListener("keydown", e => {
      const link = e.key === "Enter" && e.target && e.target.closest && e.target.closest(".scholium-link[data-href]");
      if (link) { e.preventDefault(); this.openLink(link.getAttribute("data-href")); }
    });
  },

  // web addresses open in the browser, zotero: addresses in Zotero (zotero://select shows the item)
  openLink(address) {
    if (!this.LINK_SCHEMES.test(String(address || ""))) return;
    try { Zotero.getMainWindow().ZoteroPane.loadURI(address); }
    catch (e) { this.log("link failed: " + e); }
  },

  // the words in a pane's box, or a saved prompt's (text), go to the paper it shows, in the conversation the chosen
  // agent's messages about it go to; a saved prompt leaves the box as it is
  sendFromPane(pane, invert = false, text = null) {
    const typed = text === null;
    // /compact compacts the conversation shown, on whichever tab; it is no wish for an annotation
    const compact = typed ? /^\/compact(?:\s+([\s\S]*))?$/.exec(String(pane.input.value || "").trim()) : null;
    if (compact && pane.item) {
      this.compactFromPane(pane, (compact[1] || "").trim()).then(ok => { if (ok) this.clearInput(pane); }).catch(e => this.log("compact failed: " + e));
      return;
    }
    // the annotation tab without a session: the words go with a new annotation
    if (typed && pane.tab === "annotate" && !pane.annot.shownConv && !pane.busy) { this.annotateFromPane(pane); return; }
    const say = String(typed ? pane.input.value || "" : text).trim();
    if (!say || !pane.item) return;
    if (pane.busy && this.followUpFor(pane, invert) === "steer" && this.steerable(pane)) {
      const quote = pane.tab === "chat" ? pane.quote : null;
      this.steerFromPane(pane, say, quote)
        .then(ok => {
          if (!ok) return this.queueFromPane(pane, say, { typed });
          if (typed) this.clearInput(pane);
          if (quote && pane.quote === quote) { pane.quote = null; this.paintQuote(pane); }
        })
        .catch(e => this.log("steer failed: " + e));
      return;
    }
    // a new message while the queue of the conversation shown is held asks first whether that queue goes, as Codex asks:
    // Clear queue drops it; Send message sends the new message and resumes the queue after it
    const waiting = this.queue.filter(j => this.shownQueued(pane, j));
    if (waiting.length && this.heldQueues.has(this.queueKey(waiting[0])) && !pane.busy) {
      this.askInPlace(pane, this.text("clearQueueAsk", waiting.length), [
        [this.text("clearQueue"), "quiet small", () => { this.dropQueued(waiting); this.queueFromPane(pane, say, { typed }).catch(e => this.log("message failed: " + e)); }],
        [this.text("sendMessage"), "small", () => {
          this.queueFromPane(pane, say, { before: waiting[0], typed }).then(() => this.releaseQueue(waiting[0])).catch(e => this.log("message failed: " + e));
        }]]);
      return;
    }
    this.queueFromPane(pane, say, { typed }).catch(e => this.log("message failed: " + e));
  },

  // the words to the paper's conversation of the tab: sent, or queued behind the run under way (send); typed words
  // leave the box once they went
  queueFromPane(pane, say, { before = null, typed = true } = {}) {
    const view = this.viewOf(pane, pane.tab);
    const att = view.shownKey && Zotero.Items.getByLibraryAndKey(pane.item.libraryID, view.shownKey);   // the paper of the tab's conversation
    const quote = pane.tab === "chat" ? pane.quote : null;
    return this.send(att || pane.item, say, { kind: pane.tab, conv: view.shownConv, before, quote })
      .then(sent => {
        if (!sent) return;
        if (typed) this.clearInput(pane);
        if (quote && pane.quote === quote) { pane.quote = null; this.paintQuote(pane); }
      });
  },

  // the conversation a tab shows, compacted by its agent: Claude Code's /compact in its session; false when it has no
  // session yet or its paper is busy
  async compactFromPane(pane, focus = "") {
    if (!this.compactable(pane)) return false;
    const view = this.viewOf(pane, pane.tab);
    const att = Zotero.Items.getByLibraryAndKey(pane.item.libraryID, view.shownKey);
    return !!att && this.send(att, focus, { compact: true, kind: pane.tab, conv: view.shownConv });
  },

  // whether the tab shows a conversation its paper is free to compact (its session is looked up when it is sent)
  compactable(pane) {
    const view = this.viewOf(pane, pane.tab);
    return !!pane.item && !!view.shownKey && !!view.shownConv && !this.busy(view.shownKey);
  },

  // the annotation tab's button: the tab's paper annotated anew, with the words in the box as extra wishes; over its
  // Scholium annotations it first asks in place
  annotateFromPane(pane, { extra = String(pane.input.value || "").trim() } = {}) {
    const key = pane.annot.shownKey || pane.keys[0];
    const att = key && pane.item && Zotero.Items.getByLibraryAndKey(pane.item.libraryID, key);
    if (!att) return;
    const go = () => this.annotate([att], { extra, confirmed: true })
      .then(n => { if (n && String(pane.input.value || "").trim() === extra) this.clearInput(pane); })
      .catch(e => this.log("annotate failed: " + e));
    const own = att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
    if (!own) { go(); return; }
    this.askInPlace(pane, this.text("redoInline", own), [[this.text("cancelButton"), "quiet small", () => {}], [this.text("replace"), "small danger", go]]);
  },

  // a question above the box in place of a dialog: its line and its buttons, each of which closes it first
  askInPlace(pane, line, choices) {
    const doc = pane.doc, row = pane.confirmRow;
    const text = doc.createElement("span");
    text.className = "scholium-confirm-text";
    text.textContent = line;
    row.replaceChildren(text, ...choices.map(([label, cls, fn]) => this.paneButton(doc, label, () => { this.show(row, false); fn(); }, cls)));
    this.show(row, true);
  },

  // the words in a message box are kept for the tab and the conversation they are typed to until they are sent, across
  // the section's renders; of the tab shown unless another view is named
  unsentKey(pane, view = this.viewOf(pane, pane.tab)) {
    if (!pane.item) return "";
    return `${pane.item.libraryID}/${pane.item.key}/${view.kind}/${view.shownAgent || this.agent()}/${view.shownConv || ""}`;
  },

  keepUnsent(pane) {
    const key = this.unsentKey(pane);
    if (!key) return;
    if (String(pane.input.value || "").trim()) this.unsent.set(key, pane.input.value);
    else this.unsent.delete(key);
  },

  clearInput(pane) {
    pane.input.value = "";
    this.keepUnsent(pane);
    this.fitInput(pane);
  },

  // the box shows what was typed to the conversation now shown, when that is another one than before
  swapUnsent(pane, before) {
    const after = this.unsentKey(pane);
    if (after === before) return;
    pane.input.value = this.unsent.get(after) || "";
    this.fitInput(pane);
  },

  // the message box grows with its text, up to its maximum height; an empty box is as tall as its placeholder
  fitInput(pane) {
    try {
      const input = pane.input;
      input.style.height = "auto";
      let height = input.scrollHeight;
      if (!input.value && input.placeholder) {
        input.value = input.placeholder;
        height = input.scrollHeight;
        input.value = "";
      }
      input.style.height = height + "px";
    } catch (e) {}
    this.paintSend(pane);
  },

  // the round button: ↑ sends (while the paper runs it queues or steers, as its tooltip says; a /compact the paper cannot
  // take now stays in the box); ■ stops
  paintSend(pane) {
    const text = String(pane.input.value || "").trim();
    const stop = pane.busy && !text;
    const compactNot = /^\/compact(?:\s|$)/.test(text) && !this.compactable(pane);
    pane.send.className = "scholium-round " + (stop ? "stop" : "send");
    pane.send.textContent = stop ? "■" : "↑";
    pane.send.disabled = !stop && !text;
    pane.send.title = this.text(stop ? "stopTip" : compactNot ? "compactNotNow" : !pane.busy ? "sendTip"
      : this.followUpFor(pane) === "steer" ? "steerTip" : "queueTip");
  },

  // the messages waiting in the conversation the tab shows, in the box above its text, as Codex shows them: a line while
  // the queue is held, the message being sent, each queued one, and one deleted a moment ago with Undo. Another
  // conversation's are not shown; they wait in their own
  paintQueue(pane) {
    const doc = pane.doc;
    const mine = j => this.shownQueued(pane, j);
    const jobs = this.queue.filter(mine);
    const held = jobs.length > 0 && this.heldQueues.has(this.queueKey(jobs[0]));
    const nodes = [];
    if (held) {
      const line = doc.createElement("div");
      line.className = "scholium-queue-held";
      const t = doc.createElement("span");
      t.textContent = this.text("queueHeld");
      line.append(t, this.iconButton(doc, "play", this.text("queueGoOn"), () => this.releaseQueue(jobs[0])));
      nodes.push(line);
    }
    const sending = this.job && mine(this.job.source) && !this.job.delivered ? this.job.source : null;
    if (sending) nodes.push(this.queuedRow(pane, sending, { sending: true }));
    for (const j of jobs) nodes.push(this.queuedRow(pane, j, { held }));
    for (const [qid, r] of this.removedQueued) {
      if (!mine(r.job)) continue;
      const gone = doc.createElement("div");
      gone.className = "scholium-queue-removed";
      const t = doc.createElement("span");
      t.textContent = this.text("queuedRemoved");
      gone.append(t, this.paneButton(doc, this.text("undo"), () => this.undoRemoveQueued(qid), "quiet small"));
      nodes.push(gone);
    }
    pane.queueBox.replaceChildren(...nodes);
    this.show(pane.queueBox, nodes.length > 0);
  },

  // a queued message: ⠿ to drag it, its words on one line (all of them once clicked), and Steer, ✕ and ⋯; Send instead of
  // Steer while its queue is held, Retry once it could not be sent
  queuedRow(pane, job, { held = false, sending = false } = {}) {
    const doc = pane.doc, row = doc.createElement("div");
    row.className = "scholium-queued" + (job.failed ? " failed" : "") + (sending ? " sending" : "") + (pane.openQid === job.qid ? " full" : "");
    const handle = doc.createElement("span");
    handle.className = "scholium-queued-handle";
    handle.textContent = "⠿";
    // the message being sent is out of the queue: neither dragged nor a place to drop
    if (!sending) {
      handle.setAttribute("draggable", "true");
      handle.addEventListener("dragstart", e => { pane.dragQid = job.qid; try { e.dataTransfer.setData("text/plain", job.qid); } catch (err) {} });
      handle.addEventListener("dragend", () => { pane.dragQid = null; });
      row.addEventListener("dragover", e => { if (pane.dragQid) e.preventDefault(); });
      row.addEventListener("drop", e => { e.preventDefault(); if (pane.dragQid) this.moveQueued(pane.dragQid, job.qid); pane.dragQid = null; });
    }
    const text = doc.createElement("span");
    text.className = "scholium-queued-text";
    if (job.failed) {
      const warn = doc.createElement("span");
      warn.className = "scholium-glyph warn";
      warn.setAttribute("role", "img");
      warn.setAttribute("aria-label", this.text("queuedFailedTip"));
      text.append(warn, doc.createTextNode(job.say));
      text.title = this.text("queuedFailedTip");
    } else text.textContent = job.say;
    text.addEventListener("click", () => { pane.openQid = pane.openQid === job.qid ? null : job.qid; this.paintQueue(pane); });
    row.append(handle, text);
    if (sending) {
      const s = doc.createElement("span");
      s.className = "scholium-queued-state";
      s.textContent = this.text("queuedSending");
      row.append(s);
      return row;
    }
    let first;
    if (job.failed) first = this.iconButton(doc, "retry", this.text("retry"), () => this.retryQueued(job.qid));
    else if (held) first = this.iconButton(doc, "play", this.text("queuedSend"), () => this.sendQueuedNow(job.qid));
    else {
      first = this.iconButton(doc, "steer", this.text("steerButton"), () => { this.steerQueued(pane, job.qid).catch(e => this.log("steer failed: " + e)); });
      const can = this.steerable(pane, job);
      first.disabled = !can;
      first.title = can ? this.text("steerRowTip") : !this.canSteer(job.agent) ? this.text("noSteer", this.agentName(job.agent)) : this.text("steerNotNow");
    }
    const remove = this.iconButton(doc, "trash", this.text("queuedRemove"), () => this.removeQueued(pane, job.qid));
    const more = this.paneButton(doc, "⋯", () => this.queuedMenu(pane, job, more), "quiet icon");
    row.append(first, remove, more);
    return row;
  },

  // a queued message's ⋯: back to the box to edit, or no queueing from now on (Steer instead, where the agent takes it)
  queuedMenu(pane, job, anchor) {
    this.openPopover(pane, "queued", anchor, node => {
      const item = (label, run, disabled = false) => {
        const b = pane.doc.createElement("button");
        b.className = "scholium-menu-item";
        b.textContent = label;
        b.disabled = disabled;
        b.addEventListener("click", () => { this.closePopover(pane); run(); });
        node.append(b);
      };
      item(this.text("queuedEdit"), () => this.editQueued(pane, job.qid));
      item(this.text("queueOff"), () => { Zotero.Prefs.set(this.pref + "followUpMode", "steer", true); this.refresh(); },
           !this.canSteer(job.agent) || this.followUpMode() === "steer");
    });
  },

  // a paper's conversations, each agent's own: a log each, <out dir>/conversations/<agent>-<time>.jsonl, with an index of
  // the one each agent goes on with and their titles. The log of an earlier version (<out dir>/claude-run.jsonl,
  // codex-run.jsonl) is that agent's first conversation.
  LEGACY: { claude: "claude-run", codex: "codex-run" },

  convDir(key) { return PathUtils.join(this.outDir(key), "conversations"); },

  convPath(key, id) {
    return Object.values(this.LEGACY).includes(id) ? PathUtils.join(this.outDir(key), id + ".jsonl") : PathUtils.join(this.convDir(key), id + ".jsonl");
  },

  convAgent(id) { return /^(?:annotate-)?codex-/.test(String(id)) ? "codex" : "claude"; },

  // { current: { agent: id, or null for a new one }, titles: { id: title }, annotation: { agent: its latest annotation
  // session } }; an agent without a current one goes on with its newest. An index that is there but cannot be read is not
  // written over: this session's choices stay in memory.
  async index(key) {
    if (this.indexes.has(key)) return this.indexes.get(key);
    const index = { current: {}, titles: {}, annotation: {} };
    try {
      const saved = JSON.parse(await IOUtils.readUTF8(PathUtils.join(this.convDir(key), "index.json")));
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
      await IOUtils.writeUTF8(path, JSON.stringify(index), { tmpPath: path + ".tmp" });
    } catch (e) { this.log("conversation index not saved: " + e); }
  },

  // the agent's conversations of the paper that hold something, newest first: [{ key, id, agent, path, at }]; one
  // deleted a moment ago is left out
  async conversations(key, agent) {
    const conv = async (id, path) => {
      if (this.deleting.has(path)) return null;
      try {
        const stat = await IOUtils.stat(path);
        return stat.size > 0 ? { key, id, agent, path, at: stat.lastModified || 0 } : null;
      } catch (e) { return null; }
    };
    const logs = [[this.LEGACY[agent], this.convPath(key, this.LEGACY[agent])]];
    let children = [];
    try { children = await IOUtils.getChildren(this.convDir(key)); } catch (e) {}
    for (const path of children) {
      const m = /[\\/]((claude|codex)-[\w-]+)\.jsonl$/.exec(path);
      if (m && m[2] === agent && !Object.values(this.LEGACY).includes(m[1])) logs.push([m[1], path]);
    }
    const found = await Promise.all(logs.map(([id, path]) => conv(id, path)));
    return found.filter(Boolean).sort((a, b) => b.at - a.at);
  },

  // the conversation the agent's messages about the paper go to: the one chosen last, none after New chat, else its
  // newest
  async currentConv(key, agent) {
    const chosen = (await this.index(key)).current[agent];
    if (chosen === null) return null;
    if (chosen && (await this.exists(this.convPath(key, chosen)))) return chosen;
    const all = await this.conversations(key, agent);
    return all.length ? all[0].id : null;
  },

  async chooseConv(key, agent, id) {
    const index = await this.index(key);
    index.current[agent] = id;
    await this.saveIndex(key);
  },

  // a new conversation of the agent, titled by its first message, which its messages go to from now on; an annotation
  // session is the one the annotation tab shows from now on
  async newConv(key, agent, title, kind = "chat") {
    const d = new Date();
    const two = n => String(n).padStart(2, "0");
    const base = `${kind === "annotate" ? "annotate-" : ""}${agent}-${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}${two(d.getSeconds())}`;
    let id = base;
    for (let n = 2; await this.exists(this.convPath(key, id)); n++) id = `${base}-${n}`;
    await IOUtils.makeDirectory(this.convDir(key), { createAncestors: true, ignoreExisting: true });
    await IOUtils.writeUTF8(this.convPath(key, id), "");
    const index = await this.index(key);
    if (kind === "annotate") index.annotation[agent] = id;
    else index.current[agent] = id;
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

  // a conversation as its log has it: the entries, its session (null when it has none or the agent no longer has
  // it), the turns (the user's words and the answer), whether a question started it and no annotation followed, the
  // result of its latest run, the context its session took up last, and when its latest run started; null without a log
  async readLog(key, id) {
    if (!id) return null;
    const path = this.convPath(key, id);
    let stat = null;
    try { stat = await IOUtils.stat(path); } catch (e) { return null; }
    // a conversation that goes on appends to its log, so an unchanged one (same time and size) is not parsed again; the
    // sections that ask for it at once share one reading
    let cached = this.parsedLogs.get(path);
    if (!cached || cached.at !== stat.lastModified || cached.size !== stat.size) {
      cached = { at: stat.lastModified, size: stat.size, log: this.parseLog(path) };
      this.parsedLogs.delete(path);
      this.parsedLogs.set(path, cached);
      if (this.parsedLogs.size > 20) this.parsedLogs.delete(this.parsedLogs.keys().next().value);   // the oldest
    }
    const log = await cached.log;
    if (!log) {
      if (this.parsedLogs.get(path) === cached) this.parsedLogs.delete(path);
      return null;
    }
    return { entries: log.entries.slice(), session: log.session, turns: log.turns.map(t => Object.assign({}, t)), result: log.result,
             question: log.question, context: log.context && Object.assign({}, log.context), lastAt: log.lastAt, path, id,
             rewind: log.rewind, agent: this.convAgent(id) };
  },

  // what readLog gives of a log, read once; null when it cannot be read
  async parseLog(path) {
    let text;
    try { text = await IOUtils.readUTF8(path); } catch (e) { return null; }
    const entries = [], turns = [];
    // a log of an earlier version starts with an annotation unless the user's words come first; a run's session,
    // and its turn, count once the message reached the agent
    let session = null, pending = null, result = null, question = false, opened = false, reached = false, context = null, lastAt = 0;
    let compacting = false;   // the run is a compaction: its result is no turn's
    // where each turn starts in the text, and the point an edited question takes the session back to: Claude Code's
    // last message, Codex's last turn; rewind: the point a run went back to, until the session moves on
    let at = 0, point = null, rewind = null, bare = null;   // bare: where a run line without the user's words starts
    for (const line of text.split("\n")) {
      const start = at;
      at += line.length + 1;
      if (!line.trim()) continue;
      let event;
      try { event = JSON.parse(line); } catch (e) { continue; }
      // the start of a run, with the user's words when it starts a turn
      if (event.type === "scholium" && event.subtype === "run") {
        opened = typeof event.user === "string";
        compacting = !!event.compact;
        bare = !opened && !event.compact ? start : null;
        if (opened) turns.push({ user: event.user, reply: "", ended: "", reached: false, start, point });
        if (event.rewind) rewind = { point: event.rewind, from: session };
        reached = false;
        pending = null;
        if (event.at > 0 && !event.compact) lastAt = event.at;   // since the session's last run that did its work
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
      if (event.type === "scholium" && event.subtype === "prompt") {
        question = event.question ? true : event.annotate ? false : question;
        if (!opened) {
          turns.push({ user: String(event.text || ""), reply: "", ended: "", reached: false, start: bare === null ? start : bare, point });
          reached = false;
        }
        bare = null;
        if (turns.length) Object.assign(turns[turns.length - 1], { prompted: true, annotate: !!event.annotate });
        if (event.quote && event.quote.text && turns.length) turns[turns.length - 1].quote = this.quoteOf(event.quote);
        opened = false;
      } else if (event.type !== "scholium") {
        opened = false;
        bare = null;
        if (!turns.length) turns.push({ user: this.text("annotateThis"), reply: "", ended: "", reached: false, start, point: null });
      }
      if (typeof event.session_id === "string" && event.session_id) {
        pending = event.session_id;
        if (reached) session = pending;
      }
      if (!reached && this.reached(event)) {
        reached = true;
        if (pending) session = pending;
        if (turns.length) turns[turns.length - 1].reached = true;
      }
      // the agent no longer has the session: a new one goes on with the conversation
      if (event.type === "scholium" && event.subtype === "gone") {
        session = null; rewind = null;
        // a new session took over the run's words: the refused run's error is not drawn
        if (event.resent === true) {
          this.dropRefused(entries);
          if (turns.length) turns[turns.length - 1].ended = "";
          result = null;
        }
      }
      // the cut of an edited question: the next run goes back to the point before it; without one, a new session goes on
      // with the conversation
      if (event.type === "scholium" && event.subtype === "rewind") {
        const back = this.pointOf(event.point);
        if (back) rewind = { point: back, from: session };
        else { session = null; rewind = null; }
      }
      if (event.type === "assistant" && typeof event.uuid === "string" && !compacting) point = { uuid: event.uuid };
      if (event.type === "system" && event.subtype === "compact_boundary") point = null;   // Claude Code keeps no messages before it
      if (event.method === "turn/completed" && event.params && event.params.turn && event.params.turn.id && !compacting) {
        point = { turnId: String(event.params.turn.id) };
      }
      if (rewind && session && session !== rewind.from) rewind = null;   // the run reached the agent: a session of its own
      context = this.contextAfter(event, context);
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
    return { entries: entries.slice(-this.MAX_ENTRIES), session, turns, result, question, context, lastAt, rewind: rewind ? rewind.point : null };
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
    } else if (event.type === "scholium" && (event.subtype === "gone" || (event.subtype === "rewind" && !this.pointOf(event.point)))) {
      c.used = 0;   // the new session reports its own
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

  // a conversation for a new session of it, as llm-for-zotero gives one: beyond HISTORY_FROM exchanges the latest
  // HISTORY_WHOLE whole and the earlier ones as excerpts; each answer is the run's last message
  historyParts(turns) {
    const zh = this.zh();
    const answer = t => t.reply || (t.done ? (zh ? "（没有文字回答）" : "(no text)")
      : zh ? `（没有完成${t.ended ? "：" + this.cut(t.ended, 300) : ""}）` : `(not finished${t.ended ? ": " + this.cut(t.ended, 300) : ""})`);
    let whole = turns.map((t, i) => ({ n: i + 1, user: (t.quote ? this.quoteTag(t.quote) : "") + String(t.user || ""), answer: answer(t) }));
    let summary = "";
    if (whole.length > this.HISTORY_FROM) {
      const early = whole.slice(0, -this.HISTORY_WHOLE);
      whole = whole.slice(-this.HISTORY_WHOLE);
      summary = [zh ? `之前的 ${early.length} 轮对话（摘录）：` : `Earlier conversation (${early.length} exchanges):`,
                 ...early.map(t => (zh ? `用户：${this.cut(t.user, this.EXCERPT_USER)}\n回答：${this.cut(t.answer, this.EXCERPT_ANSWER)}`
                                       : `User: ${this.cut(t.user, this.EXCERPT_USER)}\nAssistant: ${this.cut(t.answer, this.EXCERPT_ANSWER)}`))].join("\n\n");
    }
    return { summary, whole };
  },

  // Codex: the conversation as items of the new thread
  historyItems(turns) {
    if (!turns.length) return [];
    const zh = this.zh();
    const { summary, whole } = this.historyParts(turns);
    const message = (role, text) => ({ type: "message", role, content: [{ type: role === "user" ? "input_text" : "output_text", text: text || "[Empty message]" }] });
    const items = [];
    if (summary) items.push(message("user", summary), message("assistant", zh ? "明白，我已了解之前的对话。" : "Understood. I have the earlier conversation context."));
    for (const t of whole) items.push(message("user", t.user), message("assistant", t.answer));
    return items;
  },

  // Claude Code, and Codex when it does not take items: the conversation as text before the message
  historyText(turns) {
    if (!turns.length) return "";
    const zh = this.zh();
    const { summary, whole } = this.historyParts(turns);
    return [
      zh ? "下面是这段对话之前的内容。原来的会话已经接不上了，这是 Zotero 里保存的记录："
         : "Below is this conversation so far. Its earlier session cannot be continued; this is the record kept in Zotero:",
      ...(summary ? [summary] : []),
      ...whole.map(t => (zh ? `[第 ${t.n} 轮]\n用户：${t.user}\n回答：${t.answer}` : `[Turn ${t.n}]\nUser: ${t.user}\nAnswer: ${t.answer}`)),
      zh ? "——以上是之前的对话，新消息如下——" : "--- the earlier conversation ends; the new message follows ---",
    ].join("\n\n");
  },

  // what a section shows once it is laid out
  async loadHistory(body) {
    const pane = this.panes.get(body);
    if (!pane) return;
    // one PDF: the best of a regular item (the reader shows its own)
    if (pane.keys.length > 1) {
      const job = await this.resolve(pane.item);
      if (job && this.panes.get(body) === pane) pane.keys = [job.att.key];
    }
    await this.showConversation(pane);
  },

  // what a section shows: the running paper's chat transcript, else the conversation of the paper that the chosen agent's
  // messages go to (none after New chat); and on its annotation tab, the annotation session
  async showConversation(pane) {
    const seq = pane.showing = (pane.showing || 0) + 1;
    const liveHere = () => this.job && pane.keys.includes(this.job.key) && (this.job.source.kind || "chat") === "chat";
    if (liveHere()) { this.showLive(pane, this.job.key, "chat"); await this.showAnnotation(pane); return; }
    const agent = this.agent();
    const keys = pane.preferKey && pane.keys.includes(pane.preferKey) ? [pane.preferKey].concat(pane.keys.filter(k => k !== pane.preferKey)) : pane.keys;
    let shown = null, any = false;
    for (const key of keys) {
      const id = await this.currentConv(key, agent);
      if (id) { shown = { key, id }; break; }
    }
    if (!shown) for (const key of pane.keys) if ((await this.conversations(key, agent)).length) { any = true; break; }
    // the other agent's conversations of the paper, which the chosen one does not see
    let other = null;
    for (const a of this.AGENTS) {
      if (shown || any || other || a === agent) continue;
      for (const key of pane.keys) if ((await this.conversations(key, a)).length) { other = a; break; }
    }
    const log = shown ? await this.readLog(shown.key, shown.id) : null;
    if (shown) await this.loadCitations(shown.key);
    if (this.panes.get(pane.body) !== pane || pane.showing !== seq) return;   // rendered or shown anew meanwhile
    if (liveHere()) { this.showLive(pane, this.job.key, "chat"); await this.showAnnotation(pane); return; }   // a run started meanwhile
    const before = this.unsentKey(pane);
    const path = shown ? this.convPath(shown.key, shown.id) : null;
    // the latest run's own transcript, which has what its log may lack (a failure before the run had one); a section that
    // showed the run as it went has it already
    const memory = !!path && path === this.transcriptPath && this.transcriptKind === "chat";
    const kept = memory && pane.live && pane.shownPath === path && this.transcript.length > 0;
    if (pane.shownPath !== path) pane.foldOpen = new Map();   // the steps a reader opened are of the conversation shown
    Object.assign(pane, { shownKey: shown ? shown.key : null, shownConv: shown ? shown.id : null, shownAgent: agent, shownPath: path, live: memory,
                          history: !!log && !memory, turns: log ? log.turns.length : 0, question: !!(log && log.question),
                          context: log ? log.context : null, draft: null });
    pane.past = log && log.result ? { text: this.text("lastRun") + this.outcome(log.result), error: !this.succeeded(log.result),
                                      title: this.tokenDetail(log.result) } : null;
    const entries = memory ? this.transcript : log ? log.entries : [];
    // the run shown as it went is drawn again as finished; anything else anew, at the latest, so that what follows is followed;
    // a chat without entries shows the note of the other agent's conversation
    if (kept) this.refreshRun(pane, pane.runCount - 1);
    else if (entries.length) this.renderTranscript(pane, entries, false);
    else if (pane.item && pane.item.libraryID !== Zotero.Libraries.userLibraryID) {
      this.renderTranscript(pane, [{ kind: "info", text: this.text("noHistory") }], false);
    } else {
      this.renderTranscript(pane, [], false);
      if (other) pane.list.append(this.entryNode(pane.doc, { kind: "info", text: this.text("otherAgentHas", this.agentName(other)) }));
    }
    this.swapUnsent(pane, before);
    this.paintPane(pane);
    if (pane.popover && pane.popover.name === "history") await this.renderHistory(pane);
    await this.showAnnotation(pane);
  },

  // what the annotation tab shows: the paper's annotation session as it runs, else the chosen agent's latest one, else
  // an introduction
  async showAnnotation(pane) {
    const view = pane.annot, seq = view.showing = (view.showing || 0) + 1;
    const key = pane.keys[0] || null;
    const agent = this.agent();
    const id = key ? await this.annotationConv(key, agent) : null;
    const log = id ? await this.readLog(key, id) : null;
    const intro = log && log.entries.length ? null : await this.annotIntroNode(pane, key);
    if (id) await this.loadCitations(key);
    if (view.showing !== seq) return;   // shown anew meanwhile
    // the paper's annotation runs, or started meanwhile
    if (this.job && key === this.job.key && this.job.source.kind === "annotate") { this.showLive(pane, key, "annotate"); return; }
    const before = this.unsentKey(pane);
    const path = log ? log.path : null;
    if (view.shownPath !== path) view.foldOpen = new Map();   // the steps a reader opened are of the session shown
    Object.assign(view, { shownKey: key, shownConv: log ? id : null, shownAgent: agent, shownPath: path, live: false,
                          history: !!log, turns: log ? log.turns.length : 0, question: false, context: log ? log.context : null,
                          entries: log ? log.entries : [], draft: null });
    if (intro) { view.list.replaceChildren(pane.annotIntro = intro); view.runCount = 0; }
    else this.renderTranscript(view, log.entries, false);
    this.swapUnsent(pane, before);
    this.paintPane(pane);
  },

  // the annotation tab before its first session: what an annotation does; and, when an earlier version wrote the
  // paper's annotations, by which agent and when
  async annotIntroNode(pane, key) {
    return this.introNode(pane.doc, key ? await this.readApplied(key) : null);
  },

  introNode(doc, applied = null) {
    const node = doc.createElement("div");
    node.className = "scholium-annot-intro";
    const title = doc.createElement("div");
    title.className = "scholium-annot-intro-title";
    title.textContent = this.text("annotEmptyTitle");
    const body = doc.createElement("div");
    body.textContent = this.text("annotEmptyBody");
    node.append(title, body);
    if (applied && applied.at > 0) {
      const line = doc.createElement("div");
      line.className = "scholium-annot-applied";
      const d = new Date(applied.at);
      line.textContent = this.text("appliedBy", this.agentName(applied.agent === "codex" ? "codex" : "claude"),
                                   this.zh() ? `${d.getMonth() + 1}月${d.getDate()}日` : `${d.getMonth() + 1}/${d.getDate()}`);
      node.append(line);
    }
    return node;
  },

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
    label.placeholder = this.text("savedLabel");
    label.value = was ? was.label : "";
    const words = doc.createElement("textarea");
    words.className = "scholium-saved-prompt";
    words.setAttribute("rows", "2");
    words.setAttribute("no-native", "true");
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

  // the running paper's transcript, as it goes on
  showLive(pane, key, kind = this.transcriptKind) {
    const view = this.viewOf(pane, kind);
    const before = this.unsentKey(pane);
    const job = this.job && this.job.key === key ? this.job.source : null;
    const ours = this.transcriptKey === key;   // a run that has only just started shows its transcript a moment later
    const conv = (job && job.conv) || null;
    if (view.shownKey !== key || view.shownConv !== conv) view.foldOpen = new Map();   // the steps opened are of the conversation shown
    Object.assign(view, { shownKey: key, shownConv: conv, shownAgent: (job && job.agent) || this.agent(),
                          shownPath: ours ? this.transcriptPath : null, live: true,
                          history: false, past: null, draft: null });
    try {
      this.renderTranscript(view, ours ? this.transcript : [], true);
      if (ours && this.draft) this.paintDraft();
    } catch (e) {}
    // the sentences the answers cite, read now: drawn again with their chips
    const had = this.citations.get(key);
    this.loadCitations(key).then(() => {
      if (this.citations.get(key) === had || !view.live || view.shownKey !== key) return;
      view.draft = null;   // the redraw detaches the draft's node
      this.renderTranscript(view, this.transcriptKey === key ? this.transcript : [], true);
      if (this.draft) this.paintDraft();
    }).catch(e => this.log("citations failed: " + e));
    this.swapUnsent(pane, before);
    if (view !== pane) this.paintPane(pane);
  },

  // the sections that show a run's transcript, once the new conversation it started has its log; the words typed
  // there meanwhile go on with it
  livePanes(key, id) {
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, this.transcriptKind);
      if (!view.live || view.shownKey !== key) continue;
      const before = this.unsentKey(pane, view);
      view.shownConv = id;
      view.shownPath = this.convPath(key, id);
      const text = this.unsent.get(before);
      if (text) { this.unsent.delete(before); this.unsent.set(this.unsentKey(pane, view), text); }
    }
  },

  // another agent: its models, and in every section the conversation its messages about the paper go to, so that
  // switching back goes on where that agent was
  async switchAgent(pane, agent) {
    this.choose("agent", agent);
    pane.preferKey = null;
    for (const p of [...this.panes.values()]) await this.showConversation(p);
  },

  // a new conversation of the paper shown, with the chosen agent: its first message starts it. The paper's chat must be
  // idle; an annotation may run
  async newChat(pane) {
    if (pane.keys.some(k => this.busy(k, "chat"))) return;
    for (const key of pane.keys) await this.chooseConv(key, this.agent(), null);
    pane.preferKey = null;
    for (const p of [...this.panes.values()]) if (p.keys.some(k => pane.keys.includes(k))) await this.showConversation(p);
  },

  async toggleHistory(pane) {
    if (this.closePopover(pane, "history")) return;
    this.openPopover(pane, "history", pane.historyButton, () => {});
    await this.renderHistory(pane);
  },

  // today, yesterday, the previous 7 or 30 days, or older
  dayGroup(ms) {
    const day = t => { const d = new Date(t); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); };
    const days = Math.round((day(Date.now()) - day(ms)) / 86400000);
    return days <= 0 ? "groupToday" : days === 1 ? "groupYesterday" : days < 7 ? "groupWeek" : days < 30 ? "groupMonth" : "groupOlder";
  },

  // the chosen agent's conversations of the paper shown, newest first, by day: each opens, is renamed or deleted; one
  // deleted a moment ago can be brought back
  async renderHistory(pane) {
    const agent = this.agent();
    const all = [];
    for (const key of pane.keys) all.push(...await this.conversations(key, agent));
    for (const [path, d] of this.deleting) {
      if (d.agent === agent && pane.keys.includes(d.key)) all.push({ key: d.key, id: d.id, agent, path, at: d.at, title: d.title, deleted: true });
    }
    all.sort((a, b) => b.at - a.at);
    for (const c of all) if (!c.deleted) c.title = await this.convTitle(c.key, c.id);
    const p = pane.popover;
    if (this.panes.get(pane.body) !== pane || !p || p.name !== "history") return;
    const doc = pane.doc;
    const rows = [], rowOf = new Map();
    let group = null;
    for (const c of all) {
      const g = this.dayGroup(c.at);
      if (g !== group) {
        group = g;
        const head = doc.createElement("div");
        head.className = "scholium-history-group";
        head.textContent = this.text(g);
        rows.push(head);
      }
      rowOf.set(c, this.historyRow(pane, c));
      rows.push(rowOf.get(c));
    }
    if (!rows.length) {
      const empty = doc.createElement("div");
      empty.className = "scholium-history-empty";
      empty.textContent = this.text("historyEmpty");
      rows.push(empty);
    }
    // a title being typed stays in its box
    const renaming = pane.renaming;
    if (renaming) renaming.moved = true;
    p.node.replaceChildren(...rows);
    const again = renaming && all.find(c => !c.deleted && c.key === renaming.c.key && c.id === renaming.c.id);
    if (again) this.renameRow(pane, rowOf.get(again), again, renaming.input.value);
    else if (renaming) pane.renaming = null;
    this.placePopover(pane);   // placed again for the size the rows gave it
  },

  historyRow(pane, c) {
    const doc = pane.doc;
    const row = doc.createElement("div");
    const span = (cls, text) => {
      const s = doc.createElement("span");
      s.className = cls;
      s.textContent = text;
      return s;
    };
    if (c.deleted) {
      row.className = "scholium-history-row deleted";
      const undo = this.paneButton(doc, this.text("undo"), () => { this.undoDelete(c.path).catch(e => this.log("undo failed: " + e)); }, "quiet");
      row.append(span("scholium-history-title", this.text("convDeleted", this.cut(c.title, 42))), undo);
      return row;
    }
    const current = c.key === pane.shownKey && c.id === pane.shownConv;
    row.className = "scholium-history-row" + (current ? " current" : "");
    const open = doc.createElement("button");
    open.className = "scholium-history-open";
    open.title = c.title;
    open.append(span("scholium-history-title", this.cut(c.title, 42)), span("scholium-history-time", this.clock(c.at)));
    open.addEventListener("click", () => { this.openConv(pane, c).catch(e => this.log("open failed: " + e)); });
    const rename = this.paneButton(doc, "✎", () => { this.renameRow(pane, row, c); }, "quiet icon");
    rename.title = this.text("renameConv");
    const remove = this.paneButton(doc, "✕", () => { this.deleteConv(pane, c).catch(e => this.log("delete failed: " + e)); }, "quiet icon");
    remove.title = this.text("deleteConv");
    row.append(open, rename, remove);
    return row;
  },

  // the row becomes a box with its title (or with what was typed there before the list was drawn again): Enter or
  // leaving it keeps the new one, Esc the old one; an empty box gives the conversation its first message again
  renameRow(pane, row, c, typed = null) {
    const input = pane.doc.createElement("input");
    input.className = "scholium-history-rename";
    input.value = typed === null ? c.title : typed;
    const renaming = pane.renaming = { c, input, moved: false };
    let done = false;
    const finish = async keep => {
      if (done || renaming.moved) return;
      done = true;
      if (pane.renaming === renaming) pane.renaming = null;
      if (keep) {
        const index = await this.index(c.key);
        const title = this.cut(String(input.value || "").trim().split("\n")[0], 64);
        if (title) index.titles[c.id] = title;
        else delete index.titles[c.id];
        await this.saveIndex(c.key);
      }
      await this.renderHistory(pane);
    };
    input.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); finish(true).catch(() => {}); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false).catch(() => {}); }
    });
    input.addEventListener("blur", () => { finish(true).catch(() => {}); });
    row.replaceChildren(input);
    try { input.focus(); if (input.select) input.select(); } catch (e) {}
  },

  // an earlier conversation, which the agent's messages about the paper go to from now on
  async openConv(pane, c) {
    if (this.busy(c.key, "chat")) return;
    await this.chooseConv(c.key, c.agent, c.id);
    pane.preferKey = c.key;
    for (const p of [...this.panes.values()]) if (p.keys.includes(c.key)) await this.showConversation(p);
    this.closePopover(pane, "history");
  },

  // a conversation goes after UNDO_MS, until then it can be brought back; the one the agent's messages went to is
  // followed by a new one
  async deleteConv(pane, c) {
    if (this.busy(c.key, "chat") || this.deleting.has(c.path)) return;
    const index = await this.index(c.key);
    const wasCurrent = (await this.currentConv(c.key, c.agent)) === c.id;
    const entry = { key: c.key, id: c.id, agent: c.agent, title: c.title, at: c.at, wasCurrent, timer: null };
    this.deleting.set(c.path, entry);
    if (wasCurrent) index.current[c.agent] = null;
    await this.saveIndex(c.key);
    entry.timer = setTimeout(() => { this.finishDelete(c.path).catch(e => this.log("delete failed: " + e)); }, this.UNDO_MS);
    for (const p of [...this.panes.values()]) if (p.keys.includes(c.key)) await this.showConversation(p);
  },

  async undoDelete(path) {
    const entry = this.deleting.get(path);
    if (!entry || entry.finishing) return;   // too late: its log is going
    clearTimeout(entry.timer);
    this.deleting.delete(path);
    const index = await this.index(entry.key);
    if (entry.wasCurrent && index.current[entry.agent] === null) {
      index.current[entry.agent] = entry.id;
      await this.saveIndex(entry.key);
    }
    for (const p of [...this.panes.values()]) if (p.keys.includes(entry.key)) await this.showConversation(p);
  },

  // the log goes, and with it its title; a Codex conversation's thread is archived at the next Codex run
  async finishDelete(path) {
    const entry = this.deleting.get(path);
    if (!entry || entry.finishing) return;
    entry.finishing = true;
    clearTimeout(entry.timer);
    // its queued messages go with it
    const rows = this.queue.filter(j => j.qid && j.att.key === entry.key && j.conv === entry.id);
    if (rows.length) this.dropQueued(rows);
    if (entry.agent === "codex") {
      const log = await this.readLog(entry.key, entry.id);
      if (log && log.session) this.queueArchive(log.session);
    }
    try { await IOUtils.remove(path); } catch (e) { this.log("conversation not deleted: " + e); }
    this.parsedLogs.delete(path);
    const index = await this.index(entry.key);
    delete index.titles[entry.id];
    if (index.current[entry.agent] === entry.id) index.current[entry.agent] = null;
    await this.saveIndex(entry.key);
    this.deleting.delete(path);
    for (const p of [...this.panes.values()]) if (p.popover && p.popover.name === "history" && p.keys.includes(entry.key)) await this.renderHistory(p);
  },

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
    // a stopped run: ⊘, its word on hover
    if (entry.kind === "final" && entry.cancelled) {
      node.className += " cancelled";
      node.title = entry.text;
      const icon = doc.createElement("span");
      icon.className = "scholium-glyph cancelled";
      icon.setAttribute("role", "img");
      icon.setAttribute("aria-label", entry.text);
      node.append(icon);
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
      if (e.kind === "prompt") run.prompt = run.turn = e;
      else if (e.kind === "tool" || e.kind === "result") { run.steps.push(...run.answer, e); run.answer = []; }
      else if (e.kind === "text") run.answer.push(e);
      else if (e.kind === "info" && e.model) run.model = e.text;
      else if (e.kind === "time") run.end = e.at;
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
      if (this.promptEditable(view, run)) {
        said.className += " editable";
        said.append(this.iconButton(doc, "edit", this.text("editPrompt"), () => this.startEdit(view, run, said), "quiet edit-prompt"));
      }
      node.append(said);
    }
    // the question that replaced the ones after it a moment ago: Undo under it
    if (this.replaced.size && this.undoAt(view) === index) node.append(this.undoNode(view));
    // the last run of a view that failed without an answer carries a retry on its failure line; on the annotation tab, a
    // run of words to the session. A queued message that failed has its Retry on its row
    const failedLast = !live && index === (view.runCount || 0) - 1 && !run.answer.length && !!view.pane && (view.kind === "chat" || !!run.turn)
      && !this.busy(view.shownKey)
      && !this.queue.some(j => j.failed && j.att.key === view.shownKey && (j.kind || "chat") === view.kind && (j.conv || null) === (view.shownConv || null));
    let retryable = failedLast ? [...run.lead, ...run.other].filter(e => e.kind === "final" && e.error).pop() : null;
    const line = e => {
      const n = this.entryNode(doc, e);
      if (e === retryable) n.append(this.iconButton(doc, "retry", this.text("retry"), () => { this.retryFromView(view).catch(err => this.log("retry failed: " + err)); }));
      return n;
    };
    for (const e of run.lead) node.append(line(e));
    if (run.steps.length || live) node.append(this.foldNode(view, run, index, live));
    for (const e of run.answer) node.append(this.entryNode(doc, e));
    for (const e of run.other) {
      // the agent's own compaction in this run: a line with the sizes; its start has none
      if (e.kind === "compacted") {
        const n = doc.createElement("div");
        n.className = "scholium-compact";
        n.textContent = this.text("compactedAuto") + this.compactSizes(e);
        node.append(n);
        continue;
      }
      if (e.kind === "compacting") continue;
      node.append(line(e));
    }
    if (!live && run.answer.length) node.append(this.metaNode(doc, run));
    return node;
  },

  // a compaction: one line, while it runs and then how it ended
  compactNode(view, run, live) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-compact" + (live ? " live" : "");
    const lines = run.lead.concat(run.other);
    const done = lines.filter(e => e.kind === "compacted").pop();
    node.textContent = live ? this.text("compactingLine")
      : done ? this.text("compactedLine") + this.compactSizes(done)
      : this.text("compactStopped");
    const failure = lines.find(e => (e.kind === "final" && e.error) || e.kind === "compactFailed");
    if (!live && !done && failure) node.title = failure.text || "";
    return node;
  },

  compactSizes(e) { return e.pre > 0 && e.post > 0 ? ` · ${this.kTokens(e.pre)} → ${this.kTokens(e.post)}` : ""; },

  // an annotation in the annotation tab: the wishes; while it runs the steps and what it does now (the raw steps on a
  // click); then its steps folded with the closing words among them, and a card of the numbers or of the failure. The
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
      && this.queue.some(j => j.att.key === view.shownKey && j.conv === view.shownConv && this.started(j)));
    const failure = live || goesOn ? null : lines.filter(e => e.kind === "final" && e.error).pop();
    const card = counts || failure;
    const lead = card && run.lead.includes(card) ? run.lead.slice(0, run.lead.indexOf(card)) : run.lead;
    for (const e of lead) node.append(this.entryNode(doc, e));
    if (live) node.append(this.stepsNode(view, this.job));
    const steps = run.steps.concat(run.answer);
    if (steps.length || live) node.append(this.foldNode(view, Object.assign({}, run, { steps, answer: [] }), index, live));
    if (counts) node.append(this.countsNode(doc, counts));
    else if (failure) node.append(this.failedCard(view, run, failure, index));
    for (const e of lines.slice(lead.length)) if (e !== card) node.append(this.entryNode(doc, e));
    return node;
  },

  // an annotation's six steps while it runs: the ones done ticked with their time, the current one marked
  stepsNode(view, running) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-steps";
    const seen = (running && running.steps) || [];
    const now = running ? this.STEPS.indexOf(running.step) : -1;
    this.STEPS.forEach((step, i) => {
      const row = doc.createElement("div");
      row.className = "scholium-step" + (i < now ? " done" : i === now ? " now" : "");
      const label = doc.createElement("span");
      const name = this.text(step);
      label.textContent = this.zh() ? name : name.charAt(0).toUpperCase() + name.slice(1);
      const time = doc.createElement("span");
      time.className = "scholium-step-time";
      const at = seen.find(s => s.step === step), next = seen.find(s => this.STEPS.indexOf(s.step) > i);
      time.textContent = i < now && at && next ? this.durationWords(next.at - at.at) : "";
      row.append(label, time);
      node.append(row);
    });
    return node;
  },

  // the card of a finished annotation: its warnings left, the numbers counted in Zotero, and its turns, tokens and end
  countsNode(doc, e) {
    const node = doc.createElement("div");
    node.className = "scholium-card";
    const title = doc.createElement("div");
    title.className = "scholium-card-title";
    title.textContent = e.warnings === "" ? this.text("annotDoneClean") : e.warnings ? this.text("annotDoneWarn", e.warnings) : this.text("annotDone");
    const nums = doc.createElement("div");
    nums.className = "scholium-card-nums";
    for (const [n, label] of [[e.highlights, "numHighlights"], [e.margin, "numMargin"], [e.notes, "numNotes"], [e.readingNotes, "numReading"]]) {
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
    node.append(title, nums, usage);
    return node;
  },

  // the card of a failed annotation: the reason, and on the view's last run while the paper does not annotate, Retry,
  // which annotates again with the same wishes
  failedCard(view, run, failure, index) {
    const doc = view.doc;
    const node = doc.createElement("div");
    node.className = "scholium-card failed";
    const text = doc.createElement("div");
    text.textContent = failure.text;
    node.append(text);
    const extra = (run.turn && run.turn.extra) || "";
    if (view.pane && index === (view.runCount || 0) - 1 && !this.busy(view.shownKey, "annotate")) {
      node.append(this.iconButton(doc, "retry", this.text("retry"), () => { this.annotateFromPane(view.pane, { extra }); }));
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
      head.append(doc.createTextNode(this.text("working")), more);
    } else {
      head.textContent = (live ? this.text("working") : this.workedText(run)) + (open ? " ⌄" : live ? "" : " ›");
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

  workedText(run) {
    return run.start > 0 && run.end >= run.start ? this.text("worked", this.durationWords(run.end - run.start)) : this.text("workedPlain");
  },

  // 6 分 17 秒 / 6m 17s
  durationWords(ms) {
    const all = Math.max(0, Math.round(ms / 1000));
    const h = Math.floor(all / 3600), m = Math.floor((all % 3600) / 60), s = all % 60;
    if (this.zh()) return h ? `${h} 小时 ${m} 分` : m ? `${m} 分 ${s} 秒` : `${s} 秒`;
    return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
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

  // under a finished run's answer: the model and when it ended, and a button that copies the answer
  metaNode(doc, run) {
    const node = doc.createElement("div");
    node.className = "scholium-meta";
    const left = doc.createElement("span");
    left.textContent = [run.model ? this.modelLabel(run.model) : "", run.end ? this.clock(run.end) : ""].filter(Boolean).join(" · ");
    node.append(left, this.copyButton(doc, run.answer.map(e => e.text).join("\n\n")));
    return node;
  },

  // a view's whole transcript; the last run is live while the paper's run goes on
  renderTranscript(view, entries, live) {
    const runs = this.runsOf(entries);
    view.entries = entries;
    view.runCount = runs.length;   // before the runs are drawn: the last one carries the retry
    view.list.replaceChildren(...runs.map((r, i) => this.renderRun(view, r, i, live && i === runs.length - 1)));
    // an edited question that waits for its run: Undo after the conversation
    if (this.replaced.size && this.undoAt(view) === runs.length) view.list.append(this.undoNode(view));
    view.runCount = runs.length;
    view.head = this.headOf(runs);
    view.list.scrollTop = view.list.scrollHeight;
  },

  // what tells the first run drawn: the last line of the transcript's first run while another run follows it (until
  // then the first run is the one that grows); it changes when the transcript's first run goes
  headOf(runs) { return runs.length > 1 ? runs[0].last : null; },

  // whether a view shows the run going on: of the running paper, the view of the run's kind
  showsRun(view) {
    return !!this.job && this.job.key === view.shownKey && this.viewOf(view.pane, this.transcriptKind) === view;
  },

  // one run drawn again, when its steps are opened or closed or it ended; live while it is the view's running run
  refreshRun(view, index) {
    const runs = this.runsOf(view.entries);
    if (!runs[index]) return;
    const node = this.renderRun(view, runs[index], index, this.showsRun(view) && index === runs.length - 1);
    view.list.children[index].replaceWith(node);
    if (view.draft && index === runs.length - 1) node.append(view.draft.node);   // the message being written stays last
  },

  // the views of the latest run draw its last run again once the agent no longer works on it (a pause, the wait for a
  // second try, an end before the run had its log), or when an annotation reaches a step
  settleRun() {
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, this.transcriptKind);
      if (view.shownKey === this.transcriptKey) this.refreshRun(view, view.runCount - 1);
    }
  },

  // entries of the running paper's transcript: the views that show it draw its last run again, or all of it once
  // another run begins
  appendEntries(entries) {
    const added = this.addEntries(this.transcript, entries);
    if (!added.length) return;
    if (this.transcript.length > this.MAX_ENTRIES) this.transcript.splice(0, this.transcript.length - this.MAX_ENTRIES);
    for (const pane of this.panes.values()) {
      const view = this.viewOf(pane, this.transcriptKind);
      if (!view.live || view.shownKey !== this.transcriptKey) continue;
      try {
        const list = view.list;
        const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
        const runs = this.runsOf(this.transcript), live = this.showsRun(view);
        if (runs.length !== view.runCount || this.headOf(runs) !== view.head) this.renderTranscript(view, this.transcript, live);
        else list.children[runs.length - 1].replaceWith(this.renderRun(view, runs[runs.length - 1], runs.length - 1, live));
        if (view.draft) list.lastChild.append(view.draft.node);   // the draft stays last
        if (atBottom) list.scrollTop = list.scrollHeight;
      } catch (e) {}
    }
  },

  // a piece of the message the agent is writing: block names the message part it belongs to; the
  // panes show it a moment later, together with the pieces that follow
  growDraft(piece, block) {
    if (!piece) return;
    if (!this.draft) this.draft = { text: "", block };
    else if (this.draft.block !== block) this.draft.text += "\n\n";
    this.draft.text += piece;
    this.draft.block = block;
    if (!this.draftTimer) this.draftTimer = setTimeout(() => { this.draftTimer = null; this.paintDraft(); }, this.DRAFT_MS);
  },

  // what a run showed of a message it ended before finishing (cancelled, failed), as the plugin's line for
  // the log; null when no message was being written. The draft goes.
  unfinished() {
    const text = this.draft ? this.draft.text.trim() : "";
    this.dropDraft();
    return text ? { type: "scholium", subtype: "unfinished", text } : null;
  },

  dropDraft() {
    if (!this.draft) return;
    this.draft = null;
    clearTimeout(this.draftTimer);
    this.draftTimer = null;
    this.paintDraft();
  },

  // the draft at the end of each pane that shows the running paper's transcript, set as Markdown
  paintDraft() {
    for (const pane of this.panes.values()) {
      try {
        const view = this.viewOf(pane, this.transcriptKind);
        // the other view's draft goes with the run it belonged to
        for (const v of this.paneViews(pane)) {
          if (v !== view && v.draft) { v.draft.node.remove(); v.draft = null; }
        }
        if (!this.draft || !view.live || view.shownKey !== this.transcriptKey) {
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
        view.draft.content.replaceChildren(...this.renderMarkdown(pane.doc, this.draft.text));
        if (atBottom) list.scrollTop = list.scrollHeight;
      } catch (e) {}
    }
  },

  // a run of this paper replaces whatever the panes of the paper show with its transcript
  startPanes(key, kind = this.transcriptKind) {
    for (const pane of this.panes.values()) if (pane.keys.includes(key)) this.showLive(pane, key, kind);
  },

  succeeded(result) {
    return !!result && !result.is_error && (!result.subtype || result.subtype === "success");
  },

  // 完成 · 6m 17s · 29 轮 · 2,568k tokens
  outcome(result, cancelled = false, started = 0) {
    const ended = result && ["cancelled", "interrupted"].includes(result.subtype) ? result.subtype : null;
    const parts = [this.text(cancelled ? "cancelled" : ended || (this.succeeded(result) ? "done" : "failed"))];
    const timed = !!result && typeof result.duration_ms === "number" && result.duration_ms >= 0;
    const ms = timed ? result.duration_ms : started ? Date.now() - started : 0;
    if (timed || started) parts.push(this.duration(ms));
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
    return this.zh() ? `${d.getMonth() + 1}月${d.getDate()}日 ${hm}` : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
  },

  // the state line: this paper running, queued or paused, or its latest outcome; other papers' runs are
  // not shown here
  paintPane(pane) {
    try {
      const tab = pane.tab;
      const running = this.job && pane.keys.includes(this.job.key) && (this.job.source.kind || "chat") === tab;
      const queuedAt = this.queue.findIndex(j => pane.keys.includes(j.att.key) && (j.kind || "chat") === tab && !this.isHeld(j));
      // a chat's outcome is its conversation's; the annotation tab's line has a deletion's only (an annotation's is its card)
      const latest = notes => notes.filter(Boolean).sort((a, b) => b.at - a.at)[0] || null;
      const note = tab === "annotate" ? latest(pane.keys.map(k => this.notes.get(`${k}/annotate`)))
        : latest(pane.keys.map(k => [k, this.notes.get(`${k}/chat`)]).filter(([k, n]) => n && (!n.conv || (k === pane.shownKey && n.conv === pane.shownConv)))
          .map(([, n]) => n)) || pane.past;
      const paused = this.paused ? this.text(this.paused.throttled ? "throttledState" : this.paused.known ? "pausedState" : "pausedRetry",
                                             this.clock(this.paused.until)) : null;
      const foreign = !!pane.item && pane.item.libraryID !== Zotero.Libraries.userLibraryID;
      const lines = [];
      let kind = "info", title = "";
      if (running) {
        lines.push(this.runningState());
        kind = "running";
      } else if (queuedAt >= 0 && this.queue[queuedAt].retryAt > Date.now()) {
        lines.push(this.text("retryWait"));
        kind = "paused";
      } else if (queuedAt >= 0) {
        if (!(paused && queuedAt === 0)) lines.push(this.text("queuedThis", queuedAt + (this.job ? 1 : 0)));
        if (paused) { lines.push(paused); kind = "paused"; }
      } else if (foreign) {
        lines.push(this.text("myLibraryOnly"));
      } else if (note) {
        lines.push(note.text);
        kind = note.error ? "error" : "ok";
        title = note.title || "";
      }
      pane.state.className = `scholium-state ${kind}`;
      // one line, cut where the pane is narrow: the whole of it in the tooltip, with the tokens' detail of a finished run
      pane.state.textContent = lines.join(" · ");
      pane.state.title = [lines.join(" · "), title].filter(Boolean).join("\n");
      this.show(pane.state, lines.length > 0);
      const busy = !!running || queuedAt >= 0;
      // any run of the paper, of either tab
      const any = pane.keys.some(k => this.busy(k));
      // no ✎ on the questions while a run of the paper goes or waits
      pane.chatView.className = "scholium-view chat" + (any ? " busy" : "");
      if (pane.editing) pane.editing.fit();   // ✓ of a question being edited, off while the paper runs
      // the views of the tabs and the dot on the tab whose run goes on out of sight
      this.show(pane.chatView, tab === "chat");
      this.show(pane.annotView, tab === "annotate");
      pane.tabChat.className = "scholium-tab" + (tab === "chat" ? " on" : "");
      pane.tabAnnotate.className = "scholium-tab" + (tab === "annotate" ? " on" : "");
      this.show(pane.tabChatDot, tab !== "chat" && this.busyKind(pane, "chat"));
      this.show(pane.tabAnnotateDot, tab !== "annotate" && this.busyKind(pane, "annotate"));
      this.show(pane.newChat, tab === "chat");
      this.show(pane.historyButton, tab === "chat");
      // an annotation waits behind the paper's chat; not behind another annotation
      pane.annotGo.disabled = this.busyKind(pane, "annotate") || foreign;
      this.show(pane.resume, !!this.paused && queuedAt >= 0);
      // the conversations of the tab stay as they are while its run goes or waits; the agent while any run of the paper does
      pane.agent.disabled = any || foreign;
      pane.newChat.disabled = busy || foreign || !pane.shownConv;
      pane.historyButton.disabled = busy || foreign;
      if (busy || foreign) this.closePopover(pane, "history");
      const asking = running ? !!this.job.asking : queuedAt >= 0 && this.asking(this.queue[queuedAt]);
      // a question while the conversation is a question's; a follow-up once it has turns of another kind (an earlier
      // version's annotation), and while such a run goes or waits
      pane.busy = this.busyKind(pane, tab);
      this.show(pane.composer, !foreign);
      this.paintSaved(pane);
      // the annotation tab: extra wishes and Annotate until it shows a session; then words to the session, with Annotate
      // again beside the send button; while its run goes or waits, ■
      if (tab === "annotate") {
        const has = !!pane.annot.shownConv;
        pane.input.placeholder = this.text(has ? "annotFollowUpHint" : "annotExtraHint");
        pane.annotGo.textContent = this.text(has ? "redoTitle" : "annotateThis");
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
      this.paintQuote(pane);
      this.fitInput(pane);
    } catch (e) {}
  },

  // the passage that goes with the next message, above the box of the chat tab
  paintQuote(pane) {
    const q = pane.tab === "chat" ? pane.quote : null;
    this.show(pane.quoteBox, !!q);
    if (!q) return;
    const text = pane.doc.createElement("span");
    text.className = "scholium-quote-text";
    text.textContent = this.quoteLabel(q);
    const drop = this.paneButton(pane.doc, "✕", () => { pane.quote = null; this.paintQuote(pane); }, "quiet icon small");
    drop.title = this.text("quoteRemove");
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

  // system notification, for while Zotero is in the background (the corner notice is for when it is in front)
  notify(title, body) {
    try {
      const svc = Components.classes["@mozilla.org/alerts-service;1"].getService(Components.interfaces.nsIAlertsService);
      try { svc.showAlertNotification(null, title, body, false, "", null, "scholium-bridge"); return; }
      catch (e) {
        const alert = Components.classes["@mozilla.org/alert-notification;1"].createInstance(Components.interfaces.nsIAlertNotification);
        alert.init("scholium-bridge", null, title, body);
        svc.showAlert(alert);
      }
    } catch (e) { this.log("notification failed: " + e); }
  },

  // queue the selected papers, each for a new annotation session of the chosen agent, behind a chat of the paper that
  // runs or waits; returns how many were queued. confirmed: the user agreed to replace the paper's Scholium annotations
  async annotate(items, { extra = "", confirmed = false } = {}) {
    const jobs = [];
    let found = 0, foreign = false;
    for (const item of items || []) {
      try {
        const job = await this.resolve(item);
        if (job) found += 1;
        if (job && job.att.libraryID !== Zotero.Libraries.userLibraryID) { foreign = true; continue; }
        if (job && !jobs.some(j => j.att.key === job.att.key) && !this.busy(job.att.key, "annotate")) jobs.push(job);
      } catch (e) { this.log("resolve failed: " + e); }
    }
    const win = Zotero.getMainWindow();
    if (!found) {
      Services.prompt.alert(win, this.text("headline"), this.text(this.pdfAttachments(items).length ? "noFile" : "noPdf"));
      return 0;
    }
    if (!jobs.length && foreign) { Services.prompt.alert(win, this.text("headline"), this.text("myLibraryOnly")); return 0; }
    if (!jobs.length) { this.refresh(); return 0; }   // every paper is already queued or running
    const own = jobs.map(j => j.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length);
    const total = own.reduce((a, b) => a + b, 0);
    if (total && !confirmed && !Services.prompt.confirm(win, this.text("redoTitle"), this.text("redo", total))) return 0;
    for (const [i, j] of jobs.entries()) {
      Object.assign(j, { own: own[i], extra, agent: this.agent(), annotate: true, asking: false, kind: "annotate" });
      await this.place(j);
    }
    // another annotation may have been queued for a paper meanwhile
    const ready = jobs.filter(j => !this.busy(j.att.key, "annotate"));
    if (!ready.length) { this.refresh(); return 0; }
    this.enqueue(ready);
    return ready.length;
  },

  // a job's conversation: the one the agent's messages about the paper go to (on the annotation tab, its latest annotation
  // session), its session there when the agent still holds one, and whether its message is the first one; a new
  // conversation (conv null) starts when the job runs
  async place(job) {
    if ((job.retry || job.compact || job.qid) && job.conv) {
      const log = await this.readLog(job.att.key, job.conv);
      job.resume = (log && log.session) || null;
      job.rewind = job.resume ? (log && log.rewind) || null : null;
      job.question = false;
      if (!job.annotate) job.asking = !!(log && log.question);
      return;
    }
    // an annotation starts a session of its own when it runs
    if (job.annotate) { Object.assign(job, { conv: null, resume: null, question: false, asking: false }); return; }
    const conv = job.kind === "annotate" ? await this.annotationConv(job.att.key, job.agent) : await this.currentConv(job.att.key, job.agent);
    const log = conv ? await this.readLog(job.att.key, conv) : null;
    job.conv = conv;
    job.resume = (log && log.session) || null;
    // an edited question goes back to its point; a message after an edit whose run never reached the agent, to that one's
    job.rewind = job.resume ? job.rewind || (log && log.rewind) || null : null;
    // words to an annotation session are not a question
    job.question = job.kind !== "annotate" && !!job.say && !(log && log.turns.length);
    job.asking = job.question || !!(log && log.question);
  },

  // the last turn of a view's conversation again, in the same conversation; its words are in the log already
  async retryFromView(view) {
    const pane = view.pane, key = view.shownKey;
    if (!pane || !key || !view.shownConv) return;
    const log = await this.readLog(key, view.shownConv);
    const turn = log && log.turns[log.turns.length - 1];
    if (!turn) return;
    const att = Zotero.Items.getByLibraryAndKey(pane.item.libraryID, key);
    if (this.busy(key)) return;
    const agent = this.convAgent(view.shownConv);   // the conversation's own agent, whichever is chosen now
    // the retried conversation is the one the chat's messages go to; the annotation tab's is its latest session already
    if (view.kind === "chat") await this.chooseConv(key, agent, view.shownConv);
    await this.send(att, turn.user, { retry: true, conv: view.shownConv, kind: view.kind, agent, quote: turn.quote || null });
  },

  // whether the user's words of a run can be edited and asked again: the chat's own question or follow-up of a
  // conversation in the log, not words steered into a turn nor an annotation's
  promptEditable(view, run) {
    const p = run.prompt;
    return view.kind === "chat" && !!view.pane && !!view.shownKey && !!view.shownConv && !!p && !p.steer && !p.annotate
      && run.turn === p && typeof p.turn === "number";
  },

  // the turn of a log that a run's words started; null when the log no longer has it as it was. Its words are the run's,
  // or the run's followed by words steered into it
  turnOf(log, prompt) {
    const turn = log && typeof prompt.turn === "number" ? log.turns[prompt.turn] : null;
    const user = turn ? String(turn.user) : "", text = String(prompt.text);
    return turn && turn.prompted && !turn.annotate && (user === text || user.startsWith(text + "\n\n")) ? turn : null;
  },

  // where a chat view shows Undo of its conversation's edited question: the index of the question's run; until that is
  // drawn, the run going on (the question starting) or, past the runs, the end of the list (the question waits); -1: none
  undoAt(view) {
    const r = view.kind === "chat" ? this.replaced.get(`${view.shownKey}/${view.shownConv}`) : null;
    if (!r) return -1;
    const runs = this.runsOf(view.entries || []);
    const own = runs.findIndex(x => !!x.prompt && !x.prompt.steer && x.prompt.turn === r.turn);
    return own >= 0 ? own : this.showsRun(view) ? runs.length - 1 : runs.length;
  },

  undoNode(view) {
    const id = `${view.shownKey}/${view.shownConv}`;
    return this.undoStrip(view.doc, this.text("replaced"), () => { this.undoReplace(id).catch(e => this.log("undo failed: " + e)); });
  },

  // the user's words in place as a box, with their quote: ✓ or the send shortcut asks again, ✕ or Esc leaves them
  startEdit(view, run, said) {
    if (view.pane && this.busy(view.shownKey)) return;
    if (view.editing) this.stopEdit(view);
    const doc = view.doc, prompt = run.prompt;
    let quote = prompt.quote || null;
    const box = doc.createElement("div");
    box.className = "scholium-entry prompt scholium-edit";
    if (quote) {
      const q = doc.createElement("div");
      q.className = "scholium-prompt-quote";
      const t = doc.createElement("span");
      t.textContent = this.quoteLabel(quote);
      q.append(t, this.iconButton(doc, "close", this.text("quoteRemove"), () => { quote = null; q.remove(); }));
      box.append(q);
    }
    const input = doc.createElement("textarea");
    input.className = "scholium-edit-input";
    input.setAttribute("rows", "2");
    input.setAttribute("no-native", "true");
    input.value = prompt.text;
    // while the paper runs, the box and its words stay until it is free
    const busy = () => !!view.pane && this.busy(view.shownKey);
    const submit = () => {
      const say = String(input.value || "").trim();
      if (!say || busy()) { fit(); return; }
      this.stopEdit(view);
      this.editTurn(view, prompt, say, quote).catch(e => this.log("edit failed: " + e));
    };
    const tools = doc.createElement("div");
    tools.className = "scholium-edit-tools";
    const send = this.iconButton(doc, "check", this.text("editSend"), submit);
    tools.append(this.iconButton(doc, "close", this.text("editCancel"), () => this.stopEdit(view)), send);
    const fit = () => { send.disabled = !String(input.value || "").trim() || busy(); };
    input.addEventListener("input", fit);
    input.addEventListener("keydown", e => {
      if (e.isComposing) return;   // the keys of an input method's word are its own
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.stopEdit(view); return; }
      if (this.sendKey(e, input.value)) { e.preventDefault(); submit(); }
    });
    box.append(input, tools);
    fit();
    said.replaceWith(box);
    view.editing = { box, said, fit };   // paintPane fits it again when the paper starts or stops running
    try { input.focus(); } catch (e) {}
  },

  stopEdit(view) {
    const e = view.editing;
    view.editing = null;
    if (e) { try { e.box.replaceWith(e.said); } catch (err) {} }
  },

  // an earlier question of the chat asked again with new words: the turns from it on leave the log, and the agent goes on
  // from the conversation before it (Claude Code: that point of the session as a new session; Codex: a fork of the
  // thread through the turn before); Undo brings the old log back for a few seconds
  async editTurn(view, prompt, say, quote = null) {
    const pane = view.pane, key = view.shownKey, conv = view.shownConv;
    say = String(say || "").trim();
    if (!pane || !key || !conv || !say || this.busy(key)) return false;
    const log = await this.readLog(key, conv);
    const turn = this.turnOf(log, prompt);
    if (!turn) return false;
    const path = this.convPath(key, conv), id = `${key}/${conv}`;
    let old;
    try { old = await IOUtils.readUTF8(path); } catch (e) { this.log("conversation not read: " + e); return false; }
    if (this.replaced.has(id)) this.endReplaced(id);   // the edit before: its old text goes now
    const agent = this.convAgent(conv);
    const index = await this.index(key);
    const r = { key, conv, path, text: old, agent, session: log.session, note: this.notes.get(`${key}/chat`) || null,
                title: index.titles[conv], retitled: false, timer: null, turn: prompt.turn };
    // the first question names the conversation, unless it was renamed
    if (turn === log.turns[0] && index.titles[conv] === this.cut(String(prompt.text).split("\n")[0], 64)) {
      index.titles[conv] = this.cut(say.split("\n")[0], 64);
      r.retitled = true;
      await this.saveIndex(key);
    }
    // the cut keeps the point before the question, which the next run goes back to even when it is sent anew; without a
    // point, a new session is given the conversation. The first question leaves an empty log
    const marker = turn === log.turns[0] ? "" : JSON.stringify({ type: "scholium", subtype: "rewind", point: turn.point || null }) + "\n";
    // an edit before left its own marker at the end of the kept text: it goes, so that one marker is left
    const kept = old.slice(0, turn.start).split("\n").reverse();
    while (kept.length > 1 && this.isRewindMarker(kept[1])) kept.splice(1, 1);
    try { await IOUtils.writeUTF8(path, kept.reverse().join("\n") + marker); }
    catch (e) {
      this.log("conversation not cut: " + e);
      if (r.retitled) { index.titles[conv] = r.title; await this.saveIndex(key); }
      return false;
    }
    r.timer = setTimeout(() => this.endReplaced(id), this.UNDO_MS);
    this.replaced.set(id, r);
    await this.chooseConv(key, agent, conv);
    const att = Zotero.Items.getByLibraryAndKey(pane.item.libraryID, key);
    let sent = false;
    try { sent = await this.send(att || pane.item, say, { kind: "chat", conv, agent, quote, rewind: turn.point || null, edited: true }); }
    catch (e) { this.log("edit not sent: " + e); }
    if (!sent) { await this.undoReplace(id); return false; }
    // an edit that waits behind another paper's run: the sections show the conversation cut, with Undo
    if (!(this.job && this.job.key === key)) for (const p of [...this.panes.values()]) if (p.keys.includes(key)) await this.showConversation(p);
    return true;
  },

  // whether a line of a log is the marker of an edited question's cut
  isRewindMarker(line) {
    try { const e = JSON.parse(line); return !!e && e.type === "scholium" && e.subtype === "rewind"; } catch (e) { return false; }
  },

  // Undo of an edited question: its run stops (or leaves the queue before it started) without a word, the messages queued
  // behind it are held, and the log, the title and the state line come back as they were; Codex archives the fork
  async undoReplace(id) {
    const r = this.replaced.get(id);
    if (!r) return;
    clearTimeout(r.timer);
    this.replaced.delete(id);
    const mine = j => j.att.key === r.key && (j.kind || "chat") === "chat" && (j.conv || null) === r.conv;
    for (const j of this.queue) if (j.qid && mine(j)) this.heldQueues.add(this.queueKey(j));
    this.queue = this.queue.filter(j => j.qid || !mine(j));
    const running = () => !!this.job && this.job.key === r.key && mine(this.job.source);
    if (running()) {
      this.job.source.undone = true;
      this.cancel();
      for (let i = 0; i < 400 && running(); i++) await Zotero.Promise.delay(25);
    }
    const now = await this.readLog(r.key, r.conv);
    if (r.agent === "codex" && now && now.session && now.session !== r.session) this.queueArchive(now.session);
    try { await IOUtils.writeUTF8(r.path, r.text); }
    catch (e) { this.log("conversation not restored: " + e); return; }
    if (r.retitled) {
      const index = await this.index(r.key);
      if (r.title === undefined) delete index.titles[r.conv];
      else index.titles[r.conv] = r.title;
      await this.saveIndex(r.key);
    }
    if (r.note) this.notes.set(`${r.key}/chat`, r.note);
    else this.notes.delete(`${r.key}/chat`);
    if (this.transcriptPath === r.path) {
      const back = await this.readLog(r.key, r.conv);
      this.transcript = back ? back.entries : [];
    }
    this.refresh();
    for (const pane of [...this.panes.values()]) {
      if (!pane.keys.includes(r.key)) continue;
      pane.live = false;   // the run it showed as it went left the conversation: all of it is drawn anew
      await this.showConversation(pane);
    }
  },

  // the old conversation of an edit can no longer come back: its Undo goes
  endReplaced(id) {
    const r = this.replaced.get(id);
    if (!r) return;
    clearTimeout(r.timer);
    this.replaced.delete(id);
    this.dropUndo(r.key, r.conv);
  },

  // the Undo of an edit leaves the chat views of its conversation: under a run or after them; the rest stays as it is, a
  // box being edited too. A view's strip is the conversation's it shows: another one is drawn anew
  dropUndo(key, conv) {
    for (const pane of [...this.panes.values()]) {
      if (pane.shownKey !== key || pane.shownConv !== conv) continue;
      for (const n of [...pane.list.children]) {
        if (n.className === "scholium-undo") n.remove();
        else for (const c of [...(n.children || [])]) if (c.className === "scholium-undo") c.remove();
      }
    }
  },

  // the user's words to the paper, in the conversation the chosen agent's messages about it go to: the first message of
  // a new one, which answers without annotating, or the next one; while the paper's run of the tab goes on or waits, a
  // message queued behind it; false when that is not possible now. opts: retry (the same words again in conv, already
  // logged), compact, kind, conv (the conversation a queued message belongs to), before (a held queued message the words go
  // ahead of), quote, agent, rewind (the point an edited question goes back to), edited
  async send(item, say, opts = {}) {
    if (!item || (!say && !opts.compact)) return false;
    const job = await this.resolve(item);
    if (!job) {
      Services.prompt.alert(Zotero.getMainWindow(), this.text("headline"), this.text(this.pdfAttachments([item]).length ? "noFile" : "noPdf"));
      return false;
    }
    const kind = opts.kind === "annotate" ? "annotate" : "chat";
    if (job.att.libraryID !== Zotero.Libraries.userLibraryID) return false;
    // the paper's run of the other tab leaves it free; a compaction, a retry or an edited question is no message to queue
    const busy = this.busy(job.att.key, kind);
    if (busy && (opts.compact || opts.retry || opts.edited)) return false;
    Object.assign(job, { agent: (opts.retry || opts.edited) && opts.agent ? opts.agent : this.agent(), say, own: job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length,
                         kind, retry: !!opts.retry, compact: !!opts.compact, quote: opts.quote || null, rewind: opts.rewind || null,
                         edited: !!opts.edited });
    // the paper is busy: the words wait in the queue of the conversation, as Codex queues a follow-up
    if (busy) {
      Object.assign(job, { qid: String(++this.qseq), conv: opts.conv || null });
      this.queue.splice(this.followUpAt(job), 0, job);
      this.refresh();   // the queue drains already: the run it waits for goes on, or waits in it
      return true;
    }
    // words to the annotation tab without a session go with a new annotation, as its extra wishes
    if (kind === "annotate" && !opts.retry && !opts.compact && !(await this.annotationConv(job.att.key, this.agent()))) {
      return (await this.annotate([job.att], { extra: say })) > 0;
    }
    if (opts.retry) Object.assign(job, { conv: opts.conv, logged: true });
    // a compaction is the shown conversation's, by its own agent
    if (opts.compact) Object.assign(job, { conv: opts.conv, agent: this.convAgent(opts.conv) });
    await this.place(job);
    if (job.compact && !job.resume) return false;
    if (this.busy(job.att.key, kind)) return false;
    // ahead of a held queue it is sent past (Send message), else where a conversation's message goes
    const ahead = opts.before ? this.queue.indexOf(opts.before) : -1;
    this.enqueue([job], ahead >= 0 ? ahead : this.conversationAt());
    return true;
  },

  // the words of a message that did not reach the agent's log go back to the box they were typed in, unless something
  // else was typed there since; a queued message stays in the queue instead, marked (drain)
  giveBack(job) {
    if (job.qid) return;
    const words = job.compact ? "/compact" + (job.say ? " " + job.say : "") : job.say;
    if (!words || this.started(job) || job.fresh || job.logged) return;
    const att = job.att;
    const keys = [att.parentItemKey, att.key].filter(Boolean).map(item => `${att.libraryID}/${item}/${job.kind || "chat"}/${job.agent}/${job.conv || ""}`);
    for (const k of keys) if (!this.unsent.get(k)) this.unsent.set(k, words);
    for (const pane of this.panes.values()) {
      if (!keys.includes(this.unsentKey(pane)) || String(pane.input.value || "").trim()) continue;
      pane.input.value = words;
      if (job.quote && !pane.quote && !job.compact) { pane.quote = job.quote; this.paintQuote(pane); }
      this.fitInput(pane);
    }
  },

  // a paper moved to the trash, or whose parent was, while it waited
  discarded(att) {
    try { return !!(att.deleted || (att.parentItem && att.parentItem.deleted)); } catch (e) { return false; }
  },

  // where a message of a conversation joins the queue: before the papers still waiting for their first run, after
  // the paper that the usage limit or a failed connection interrupted and after the other conversations
  conversationAt() {
    let at = 0;
    const talk = j => !!j.say || (!!j.resume && !j.annotate) || j.retried || j.interrupted;
    while (at < this.queue.length && talk(this.queue[at])) at++;
    return at;
  },

  // whether a paper's run belongs to a conversation that a question started and no annotation continued
  asking(job) {
    return !!(job && !job.annotate && job.asking);
  },

  // whether a paper has a run going on or waiting; of one kind only, when given. A held queued message waits for Resume,
  // not for a run: it leaves the paper free
  busy(key, kind = null) {
    const of = j => !kind || (j.kind || "chat") === kind;
    return !!(this.job && this.job.key === key && of(this.job.source)) || this.queue.some(j => j.att.key === key && of(j) && !this.isHeld(j));
  },

  // where a follow-up joins the queue: after what is queued for its conversation, else where a conversation's message goes
  followUpAt(job) {
    const k = this.queueKey(job);
    for (let i = this.queue.length - 1; i >= 0; i--) if (this.queueKey(this.queue[i]) === k) return i + 1;
    return this.conversationAt();
  },

  // the queue of a conversation (of a tab of a paper): its queued messages go one after another, held together; one
  // queued before its conversation had its log is in the queue of none until the run before it makes one (run)
  queueKey(job) { return `${job.att.key}/${job.kind || "chat"}/${job.conv || ""}`; },

  // whether a job is a message queued to the conversation a tab shows
  shownQueued(pane, job) {
    const view = this.viewOf(pane, pane.tab);
    return !!job.qid && pane.keys.includes(job.att.key) && (job.kind || "chat") === pane.tab && (job.conv || null) === (view.shownConv || null);
  },

  // a queued message that waits: its queue held after a stop, or behind a message of it that could not be sent
  isHeld(job) {
    if (!job.qid) return false;
    const k = this.queueKey(job);
    return this.heldQueues.has(k) || this.queue.some(q => q.failed && this.queueKey(q) === k);
  },

  // a held queue lets go once none of its messages is left, nor can be brought back
  tidyHeld() {
    for (const k of [...this.heldQueues]) {
      const its = j => !!j.qid && this.queueKey(j) === k;
      if (!this.queue.some(its) && ![...this.removedQueued.values()].some(r => its(r.job))) this.heldQueues.delete(k);
    }
  },

  queuedAt(qid) { return this.queue.findIndex(j => j.qid === qid); },

  // a queued message dragged onto another of its queue goes before it
  moveQueued(from, before) {
    const i = this.queuedAt(from), j = this.queuedAt(before);
    if (i < 0 || j < 0 || i === j || this.queueKey(this.queue[i]) !== this.queueKey(this.queue[j])) return;
    const [job] = this.queue.splice(i, 1);
    this.queue.splice(this.queuedAt(before), 0, job);
    this.refresh();
  },

  // where a queued message goes back into its own queue: before the row that followed it, else after the last row of its
  // queue, else where a follow-up of its conversation goes (never ahead of that conversation's own runs)
  backAt(job, next = null) {
    const n = next ? this.queuedAt(next) : -1;
    if (n >= 0) return n;
    const k = this.queueKey(job);
    for (let i = this.queue.length - 1; i >= 0; i--) if (this.queue[i].qid && this.queueKey(this.queue[i]) === k) return i + 1;
    return this.followUpAt(job);
  },

  // the row of a message's queue after a place in the queue
  nextRow(job, from) {
    const k = this.queueKey(job);
    const next = this.queue.slice(from).find(j => j.qid && this.queueKey(j) === k);
    return next ? next.qid : null;
  },

  // ✕: out of the queue, for a moment with Undo in its place; the messages behind a failed one go on
  removeQueued(pane, qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const [job] = this.queue.splice(i, 1);
    const timer = setTimeout(() => { this.removedQueued.delete(qid); this.refresh(); }, this.QUEUE_UNDO_MS);
    this.removedQueued.set(qid, { job, next: this.nextRow(job, i), timer });
    this.refresh();
    if (!this.draining) this.drain();
  },

  undoRemoveQueued(qid) {
    const r = this.removedQueued.get(qid);
    if (!r) return;
    clearTimeout(r.timer);
    this.removedQueued.delete(qid);
    this.queue.splice(this.backAt(r.job, r.next), 0, r.job);
    this.refresh();
    if (!this.draining) this.drain();
  },

  // a queued message back in the box, before what is typed there; the messages behind a failed one go on
  editQueued(pane, qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const [job] = this.queue.splice(i, 1);
    const typed = String(pane.input.value || "").trim();
    pane.input.value = typed ? job.say + "\n\n" + typed : job.say;
    this.keepUnsent(pane);
    this.fitInput(pane);
    try { pane.input.focus(); } catch (e) {}
    this.refresh();
    if (!this.draining) this.drain();
  },

  // Send on a row of a held queue: that message first, and the queue goes on
  sendQueuedNow(qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const [job] = this.queue.splice(i, 1);
    const k = this.queueKey(job);
    const first = this.queue.findIndex(j => j.qid && this.queueKey(j) === k);
    this.queue.splice(first < 0 ? this.followUpAt(job) : first, 0, job);
    this.releaseQueue(job);
  },

  retryQueued(qid) {
    const job = this.queue[this.queuedAt(qid)];
    if (!job) return;
    job.failed = false;
    this.refresh();
    if (!this.draining) this.drain();
  },

  // Resume: the held queue goes on
  releaseQueue(job) {
    this.heldQueues.delete(this.queueKey(job));
    this.refresh();
    if (!this.draining) this.drain();
  },

  // Clear queue: its messages go, and with them its hold (tidyHeld)
  dropQueued(jobs) {
    this.queue = this.queue.filter(j => !jobs.includes(j));
    this.refresh();
  },

  // Steer on a row (greyed unless steerable): the message into the answer under way, out of the queue
  async steerQueued(pane, qid) {
    const i = this.queuedAt(qid);
    if (i < 0) return;
    const job = this.queue[i];
    if (!(await this.steerFromPane(pane, job.say, job.quote))) return;
    const k = this.queuedAt(qid);
    if (k >= 0) this.queue.splice(k, 1);
    this.refresh();
  },

  enqueue(jobs, at = this.queue.length) {
    this.queue.splice(Math.min(at, this.queue.length), 0, ...jobs);
    this.refresh();
    if (!this.draining) this.drain();
  },

  // take papers out of the queue, their runs of one kind only when given, and their queued messages unless `rows` is
  // false; when nothing but held messages is left, a pause ends
  dequeue(keys, kind = null, { rows = true } = {}) {
    const ours = j => keys.includes(j.att.key) && (!kind || (j.kind || "chat") === kind) && (rows || !j.qid);
    const started = this.queue.filter(j => ours(j) && this.started(j));
    this.queue = this.queue.filter(j => !ours(j));
    if (!this.queue.some(j => !this.isHeld(j)) && this.paused) {
      clearTimeout(this.paused.timer);
      this.paused = null;
    }
    this.refresh();
    for (const job of started) this.endWaiting(job).catch(e => this.log("cancel not logged: " + e));
  },

  // whether a queued paper's conversation has its run already: one waiting for its second try, for a limit to reset,
  // or handed over by an update
  started(job) {
    return !!(job.retried || job.interrupted || (job.resume && !job.say && !job.annotate && !job.compact));
  },

  // a paper whose run waited ends as cancelled, in its log and its sections
  async endWaiting(job) {
    const key = job.att.key;
    if ((job.kind || "chat") === "chat") this.notes.set(`${key}/chat`, { text: this.text("cancelled"), error: true, at: Date.now(), conv: job.conv || null });
    else this.notes.delete(`${key}/annotate`);
    if (job.conv) {
      const path = this.convPath(key, job.conv);
      const marks = [await this.logEnd(path, "cancelled", this.text("cancelled")), { type: "scholium", subtype: "time", at: Date.now() }];
      try { await IOUtils.writeUTF8(path, JSON.stringify(marks[1]) + "\n", { mode: "append" }); }
      catch (e) { this.log("end time not logged: " + e); }
      if (this.transcriptPath === path) this.appendEntries(marks.flatMap(m => this.entries(m)));
    }
    this.refresh();
    for (const pane of [...this.panes.values()]) if (pane.keys.includes(key)) await this.showConversation(pane);
  },

  // one paper at a time; `draining` also covers the moments before a process exists. The usage limit
  // pauses the queue.
  async drain() {
    this.draining = true;
    try {
      while (this.queue.length && !this.paused) {
        // a held queued message waits for Resume, and those behind a failed one for it
        const i = this.queue.findIndex(j => !this.isHeld(j));
        if (i < 0) break;
        // a paper whose connection failed waits for its second try at the head of the queue
        const wait = (this.queue[i].retryAt || 0) - Date.now();
        if (wait > 0) { await Zotero.Promise.delay(Math.min(wait, 1000)); continue; }
        const job = this.queue.splice(i, 1)[0];
        if (this.discarded(job.att)) { this.log("left out, in the trash: " + job.att.key); continue; }
        // a queued message takes its conversation as it is now
        if (job.qid) {
          job.own = job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
          await this.place(job);
        }
        let outcome = null;
        try { outcome = await this.run(job); }
        catch (e) {
          const message = String(e && e.message || e).slice(0, 300);
          this.current = null;
          this.dropDraft();
          if (!job.logPath) this.giveBack(job);
          this.appendEntries(job.logPath ? this.entries(await this.logEnd(job.logPath, "failed", message)) : [{ kind: "final", text: message, error: true }]);
          this.notice(job, `${this.text("failed")} · ${message}`, true);
          this.finish(job, false, message);
          this.log("run failed: " + e);
          if (!job.logPath) outcome = { ok: false, delivered: false };   // its words reached nothing
        }
        // a queued message that did not reach the agent goes back to the head of its queue, marked, and its queue waits for it
        if (job.qid && outcome && !outcome.delivered && !outcome.cancelled && !outcome.limited && !outcome.retry && !outcome.fresh) {
          job.failed = true;
          job.logged = job.logged || !!job.logPath;
          this.queue.splice(this.backAt(job, this.nextRow(job, 0)), 0, job);
          this.refresh();
          this.settleRun();   // its Retry is on its row
        }
        if (outcome && outcome.limited) this.pause(job, outcome);
        if (outcome && outcome.retry) {
          // the message was sent: what waits for the second try is no queued row
          this.queue.unshift(Object.assign({}, job, { retried: true, retryAt: Date.now() + this.NET_RETRY_MS, qid: null }));
          this.refresh();
          this.settleRun();   // the paper is busy again: no retry button
        }
        if (outcome && outcome.fresh) {
          this.queue.unshift(outcome.fresh);
          this.refresh();
        }
      }
    } finally {
      this.draining = false;
      this.refresh();
    }
  },

  // the usage limit, or a limit of the service: the interrupted paper waits at the head of the queue and continues
  // its conversation when the limit resets; nothing else starts meanwhile
  pause(job, { until, session, throttled }) {
    if (this.job && this.job.key === job.att.key) this.job = null;
    // a question stays one when its conversation continues; an annotation that continued a question's conversation
    // has its prompt there. A run after the wait may have its second try again. A queued message that was sent is no row.
    // An edited question's new session goes on as it is; until there is one, the run goes back to the point again
    this.queue.unshift(Object.assign({}, job, { retried: false, retryAt: 0, qid: null },
                                     session ? { resume: session, say: "", extra: "", asked: !!(job.say || job.asked),
                                                 annotate: false, question: false, fresh: false, logged: false,
                                                 throttled: !!throttled, updated: false, rewind: session === job.resume ? job.rewind || null : null }
                                             : { interrupted: true, logged: true }));
    this.settleRun();   // the paper waits: no retry
    const wait = until ? Math.max(until - Date.now(), 0) + 60000 : this.RETRY_MS;
    if (this.paused) clearTimeout(this.paused.timer);
    this.paused = { until: Date.now() + wait, known: !!until, throttled: !!throttled, timer: setTimeout(() => { this.resumeQueue(); }, wait) };
    const line = this.text(throttled ? "throttledState" : until ? "pausedState" : "pausedRetry", this.clock(this.paused.until));
    this.notice(job, line, true);
    if (!this.focused()) this.notify(this.text(throttled ? "throttleTitle" : "limitTitle", this.agentName(job.agent, true)), line);
    this.refresh();
  },

  // the time a limit's message names ("约 24 分钟后重置", "try again in 24 minutes"), as a moment; null without one
  // or beyond six hours
  resetFrom(text) {
    const s = String(text || "");
    const m = /(\d+(?:\.\d+)?)\s*(分钟|小时)\s*后/.exec(s)
      || /\bin\s+(?:about\s+|~\s*)?(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b/i.exec(s);
    if (!m) return null;
    const ms = Number(m[1]) * (/^(小时|hour|hr)/i.test(m[2]) ? 3600000 : 60000);
    return ms > 0 && ms <= 6 * 3600000 ? Date.now() + ms : null;
  },

  resumeQueue() {
    if (!this.paused) return;
    clearTimeout(this.paused.timer);
    this.paused = null;
    this.refresh();
    if (!this.draining && this.queue.length) this.drain();
  },

  // whether a Zotero main window has the focus: a corner notice is for then, the system notification for the rest
  focused() {
    return this.windows().some(win => { try { return win.document.hasFocus(); } catch (e) { return false; } });
  },

  // a short notice in the corner of the window that closes by itself, while Zotero is in front; left out while
  // the paper's Scholium section is on screen, whose state line says the same
  notice(job, text, error = false) {
    if (!this.focused() || this.paneInView(job.att && job.att.key, job.kind || "chat")) return;
    try {
      const pw = new Zotero.ProgressWindow({ closeOnClick: true });
      pw.changeHeadline(this.text("headline"));
      let icon = null;
      try { if (job.att) icon = job.att.getItemTypeIconName(); } catch (e) {}
      const line = new pw.ItemProgress(icon, job.title);
      if (error) line.setError(); else line.setProgress(100);
      // a description per line: a description shows its text without line breaks. Zotero turns <a …>…</a> in it
      // into a link with the attributes it names; the agent's words are text, so a joiner follows each <
      const joiner = String.fromCharCode(0x2060);
      for (const part of String(text).split("\n")) pw.addDescription(part.replace(/</g, "<" + joiner));
      pw.show();
      pw.startCloseTimer(error ? 2 * this.NOTICE_MS : this.NOTICE_MS);
    } catch (e) { this.log("notice failed: " + e); }
  },

  // record the end of one paper: its section keeps the outcome in short, the transcript has the rest
  finish(job, ok, summary, outcome, detail, answered = false) {
    if (this.job && this.job.key === job.att.key) this.job = null;
    const title = this.text(ok && job.compact ? "compactedTitle" : answered ? "answered" : ok ? "finished" : this.asking(job) ? "failedAsk" : "failedLine", job.title);
    // a chat's outcome is its state line's; an annotation's is its card, and a deletion's note before it goes
    if ((job.kind || "chat") === "chat") {
      this.notes.set(`${job.att.key}/chat`, { text: outcome || this.text(ok ? "done" : "failed"), error: !ok, at: Date.now(),
                                              title: detail || "", conv: job.conv || null });
    } else this.notes.delete(`${job.att.key}/annotate`);
    if (!this.focused() && !job.undone) this.notify(title, ok && !answered ? this.brief(summary) : summary || "");
    this.refresh();
    // the sections of the paper take what its log now says of the conversation; without a log, they draw the run ended
    if (job.logPath) {
      for (const pane of [...this.panes.values()]) {
        if (pane.keys.includes(job.att.key)) this.showConversation(pane).catch(e => this.log("section not shown: " + e));
      }
    } else this.settleRun();
  },

  // the run's last line for a notice, a line per part, without the note's title:
  // 高亮 47 条（核心 13 条），页边批注 24 条，笔记《…》，剩余警告：…。 -> 高亮 47 条（核心 13 条）/ 页边批注 24 条 / 剩余警告：…
  // 47 highlights (13 core), 24 margin notes, note “…”, remaining warnings: none -> the same three parts
  brief(summary) {
    return String(summary || "")
      .replace(/(^|[，,；;])\s*[^，,；;。]*笔记[^，,；;。《]*《[^》]*》|(^|[，,；;])\s*(?:the\s+|reading\s+)?note\s*(?:“[^”]*”|"[^"]*"|‘[^’]*’|'[^']*')/gi, "")
      .replace(/[。.]\s*$/, "")
      .split(/\s*[，；;]\s*|,\s+/).map(part => part.trim()).filter(Boolean).slice(0, 4)
      .map(part => (part.length > 40 ? part.slice(0, 39) + "…" : part)).join("\n");
  },

  // the sections of the running paper, each second: their time so far, and the context its session takes up
  async tick(job) {
    while (this.job === job) {
      await Zotero.Promise.delay(this.TICK_MS);
      if (this.job !== job) break;
      for (const pane of this.panes.values()) {
        if (!pane.keys.includes(job.key)) continue;
        try {
          // the line belongs to the tab of the run's kind; the other tab's outcome stays
          if (pane.tab === (job.source.kind || "chat")) pane.state.textContent = pane.state.title = this.runningState();
          this.paintRing(pane);
        } catch (e) {}
      }
    }
  },

  // a run that ■ or Esc stopped before its log had the user's words: it ends as cancelled, the words go back to the box and
  // a queued message to the head of its queue, held as the stop holds it; nothing when the plugin stopped meanwhile
  halted(job, running) {
    if (this.job !== running) return;
    const message = this.text("cancelled");
    if (job.qid) {
      this.queue.splice(this.backAt(job, this.nextRow(job, 0)), 0, job);
      this.heldQueues.add(this.queueKey(job));
    } else if (!job.undone) this.giveBack(job);
    this.appendEntries([{ kind: "final", text: message, error: true, cancelled: true }]);
    if (!job.undone) this.notice(job, message, true);
    this.finish(job, false, message, this.outcome(null, true, running.started));
    return { ok: false, delivered: false, cancelled: true };
  },

  async run(job) {
    const started = Date.now();
    const key = job.att.key;
    const agent = job.agent === "codex" ? "codex" : "claude";
    this.job = { title: job.title, key, libraryID: job.att.libraryID, started, agent, step: job.resume && !job.annotate ? "continuing" : "starting",
                 source: job, session: job.resume || null, log: null, asking: this.asking(job), context: null };
    this.transcriptKind = job.kind || "chat";   // the tab whose run this is, from its start
    const running = this.job;
    // the conversation goes on in its log; a new one starts its own when the run is under way
    const log = job.conv ? await this.readLog(key, job.conv) : null;
    // a new session of the conversation is given its turns. A second try, a new session after a gone one, and a message
    // handed back before it reached the agent have their turn in the log already, which is their message
    const continuation = !!job.resume && !job.say && !job.annotate;
    const again = !!(job.retried || job.fresh || job.logged) && !continuation;
    job.history = log && !job.resume ? (again ? log.turns.slice(0, -1) : log.turns) : [];
    job.since = log ? log.lastAt : 0;
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
    running.context = log ? log.context : null;
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
      this.giveBack(job);
      this.appendEntries([{ kind: "final", text: missing, error: true }]);
      this.notice(job, missing, true);
      this.finish(job, false, missing);
      return { ok: false, delivered: false };
    }
    await IOUtils.makeDirectory(this.outDir(key), { createAncestors: true, ignoreExisting: true });
    if (this.job !== running || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, while the folder was prepared
    if (!job.conv) {
      job.conv = await this.newConv(key, agent, job.say || this.text("annotateThis"), job.kind || "chat");
      // the messages queued meanwhile go on with this conversation, held still when they were
      for (const q of this.queue) {
        if (!q.qid || q.conv || q.att.key !== key || (q.kind || "chat") !== (job.kind || "chat")) continue;
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
    if (this.job !== running || running.stopAsked) return this.halted(job, running);   // the plugin stopped, or ■, while the log was prepared
    running.log = logPath;
    // the run's agent, and the user's words when it starts a turn; once this line is on its way an update hands the
    // paper over as logged, so that the new copy does not log the turn again
    const user = job.compact || again || continuation ? null
      : job.say || this.text("annotateThis") + (job.extra ? "\n" + this.text("extraLabel") + job.extra : "");
    running.logged = true;
    await IOUtils.writeUTF8(logPath, JSON.stringify(Object.assign({ type: "scholium", subtype: "run", agent, user, at: started },
      job.compact ? { compact: true } : {}, job.rewind && job.resume ? { rewind: job.rewind } : {})) + "\n", { mode: "appendOrCreate" });
    if (!job.resume || job.annotate) job.profile = (await this.exists(this.profilePath())) ? this.profilePath() : null;
    // the user's words, an annotation, or an automatic continuation, go into the log as the plugin's own lines; a second
    // try has them already. A question's line marks its conversation as one.
    const prompted = text => ({ type: "scholium", subtype: "prompt", text });
    const quoted = job.quote ? { quote: job.quote } : {};
    const mark = job.retried || job.fresh || job.logged ? null
      : job.compact ? { type: "scholium", subtype: "compact", text: job.say || "" }
      : job.annotate ? Object.assign(prompted(this.text("annotateThis") + (job.extra ? "\n" + this.text("extraLabel") + job.extra : "")),
                                     { annotate: true, extra: job.extra || "" })
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
                  exitCode: null, stderr: "", current: null, applies: {}, gone: false, unlogged: [] };
    if (this.job !== running) return;   // the plugin stopped while the log was written
    // ■ meanwhile: the run ends as a cancel ends it, its words in the log
    if (running.stopAsked) ctx.current = { key, proc: null, cancelled: true };
    else if (agent === "codex") await this.runCodex(program, ctx);
    else await this.runClaude(program, ctx);
    await this.appendLog(ctx, []);   // what the log could not take during the run
    this.current = null;
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
      this.notice(job, job.compact ? this.text("compactedNotice")
        : [`${this.text("done")} · ${this.duration(Date.now() - started)}`, answered ? summary : this.brief(summary)].filter(Boolean).join("\n"));
      // an annotation's end, also of its second try or of its continuation after a pause: the numbers counted in Zotero
      if (running.annotation) {
        const tokens = this.tokenCounts(result).reduce((n, [, c]) => n + c, 0);
        const counts = Object.assign({ type: "scholium", subtype: "counts" }, await this.countOwn(job.att),
                                     { warnings: this.warningsOf(text), turns: result.num_turns || 0, tokens, at: Date.now() });
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
      message = (ctx.failure || summary || errors || ctx.stderr.trim().split("\n").pop() || this.text("exitCode", exitCode)).slice(0, 300);
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
      if (!(result && this.entries(result).length)) this.appendEntries(this.entries(await this.logEnd(logPath, "failed", message, started)));
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
    this.finish(job, ok, message, this.outcome(result, current.cancelled, started), this.tokenDetail(result), answered);
    return { exitCode, result, ok, delivered: !!running.delivered, cancelled: !!current.cancelled };
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
  async logEnd(logPath, outcome, text, started = 0) {
    const mark = { type: "scholium", subtype: "end", outcome, text };
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
  // with the whole conversation; null for a continuation after a limit or an update
  fresh(job) {
    if (!job.say && !job.annotate) return null;
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
    (ctx.running.steps = ctx.running.steps || []).push({ step, at: Date.now() });
    this.refresh();
    // the annotation tab's steps show the step reached at once, not with the agent's next line
    if (this.transcriptKind === "annotate") this.settleRun();
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

  // Claude Code: `claude -p` with the prompt on stdin and its stream-json events on stdout
  async runClaude(claude, ctx) {
    const { job, key } = ctx;
    const proc = await this.subprocess().call({
      command: claude, arguments: this.args(job), workdir: Zotero.DataDirectory.dir, stderr: "pipe",
      environment: { PYTHONIOENCODING: "utf-8" }, environmentAppend: true,
    });
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
          // a write to Zotero, kept with its configuration once its command succeeded
          for (const c of (event.message && event.message.content) || []) {
            const config = event.type === "assistant" && c && c.type === "tool_use" && this.appliedConfig(String((c.input || {}).command || ""));
            if (config && c.id) ctx.applies[c.id] = config;
            const applied = event.type === "user" && c && c.type === "tool_result" && !c.is_error && ctx.applies[c.tool_use_id];
            if (applied) await this.noteApplied(key, applied, "claude", job.conv, Zotero.DataDirectory.dir);
          }
          // the skills Claude Code loaded: without this one the run would only look for it
          if (event.type === "system" && event.subtype === "init" && Array.isArray(event.skills)
              && !event.skills.some(name => /(?:^|:)zotero-scholium$/.test(String(name)))) {
            ctx.failure = this.text("noSkill", "claude");
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
    const proc = await this.subprocess().call({
      command: codex, arguments: ["app-server"], workdir, stderr: "pipe",
      environment: { PYTHONIOENCODING: "utf-8" }, environmentAppend: true,
    });
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
    await rpc.request("initialize", { clientInfo: { name: "scholium-bridge", title: "Scholium", version: this.version || "0" } });
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
    return { error: { code: -32601, message: "not handled by scholium-bridge" } };
  },

  // streaming deltas and start-up chatter stay out of the log, the whole items carry the same text; so does the user's
  // message, which the plugin's own line has, and the turn's diff, which each file change repeats whole
  codexNoise(msg) {
    if (/^item\/(?:started|completed)$/.test(String(msg.method || "")) && msg.params && msg.params.item && msg.params.item.type === "userMessage") return true;
    return /(?:[Dd]elta|summaryPartAdded|startupStatus\/updated|remoteControl\/status\/changed|^turn\/diff\/updated)$/.test(String(msg.method || ""));
  },

  // the threads of deleted conversations, archived at the next Codex run as llm-for-zotero archives them
  queueArchive(thread) {
    let ids = [];
    try { ids = JSON.parse(this.getPref("codexArchive") || "[]"); } catch (e) {}
    if (!Array.isArray(ids)) ids = [];
    if (!ids.includes(thread)) ids.push(thread);
    try { Zotero.Prefs.set(this.pref + "codexArchive", JSON.stringify(ids.slice(-50)), true); } catch (e) { this.log("preference not saved: " + e); }
  },

  async archiveThreads(rpc) {
    let ids = [];
    try { ids = JSON.parse(this.getPref("codexArchive") || "[]"); } catch (e) {}
    if (!Array.isArray(ids) || !ids.length) return;
    try { Zotero.Prefs.set(this.pref + "codexArchive", "", true); } catch (e) {}
    for (const threadId of ids) {
      try { await rpc.request("thread/archive", { threadId }); } catch (e) { this.log("thread not archived: " + e); }
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
  // and their installed plugins, disabled for its turns; config.toml is not changed, and of the
  // configuration only the servers' names are kept
  async codexQuiet(rpc) {
    const quiet = { config: null, plugins: [] };
    try {
      const read = await rpc.request("config/read", {});
      const names = Object.keys((read && read.config && read.config.mcp_servers) || {});
      if (names.length) quiet.config = { mcp_servers: Object.fromEntries(names.map(name => [name, { enabled: false }])) };
    } catch (e) { this.log("config/read failed: " + e); }
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
        // a write to Zotero, kept with its configuration once its command succeeded, in the folder it ran in
        if (msg.method === "item/completed" && item.type === "commandExecution" && item.exitCode === 0 && item.status !== "failed") {
          const config = this.appliedConfig(this.shellCommand(item.command));
          if (config) await this.noteApplied(key, config, "codex", job.conv, item.cwd || cwd);
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
      await this.archiveThreads(rpc);
      const model = this.modelPref("codex");
      const settings = { cwd, approvalPolicy: "on-request", approvalsReviewer: "auto_review", sandbox: "workspace-write",
                         serviceName: "scholium-bridge" };
      if (model) settings.model = model;
      const quiet = await this.codexQuiet(rpc);
      if (quiet.config) settings.config = quiet.config;
      const skill = job.resume ? null : await this.codexSkill(rpc, cwd);
      if (!job.resume && !skill) throw new Error(this.text("noSkill", "codex"));
      let opened = null;
      if (job.resume) {
        // a thread that Codex refuses to resume is one it no longer has: a new one goes on with the conversation; an
        // edited question forks the thread through the turn before it, and a refused fork does the same
        // the turns stay with the server: a long conversation is not sent back whole
        const fork = job.rewind && job.rewind.turnId;
        try {
          opened = fork ? await rpc.request("thread/fork", Object.assign({ threadId: job.resume, lastTurnId: fork, excludeTurns: true }, settings))
                        : await rpc.request("thread/resume", Object.assign({ threadId: job.resume, excludeTurns: true }, settings));
        }
        catch (e) { ctx.gone = !!(e && e.refused); throw e; }
      } else opened = await rpc.request("thread/start", settings);
      const thread = opened && opened.thread && opened.thread.id;
      if (!thread) throw new Error(this.text("noThread"));
      state.thread = ctx.session = ctx.running.session = thread;
      // the start of a run, as Claude Code's log has it: the model and the conversation
      const init = { type: "system", subtype: "init", agent: "codex", model: (opened && opened.model) || model, session_id: thread };
      await this.appendLog(ctx, [JSON.stringify(init)]);
      this.appendEntries(this.entries(init));
      // a new thread of a conversation is given its turns as items of the thread, or as text before the message when
      // Codex does not take them
      let asText = true;
      if (!job.resume && job.history && job.history.length) {
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
          if (skill) this.advance(ctx, "skill");
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

  // the paper's Scholium annotations and reading notes as the annotation card counts them
  async countOwn(att) {
    const own = att.getAnnotations().filter(a => ScholiumToggle.isOwn(a));
    const core = await this.coreColor(att.key);
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
  // skill's summary is the reply's last line; 无 and 没有 are "none" only on their own (无法定位 2 句 is a warning)
  warningsOf(text) {
    const s = String(text || "").trim().split("\n").pop();
    if (/无剩余警告|没有剩余警告|剩余警告[:：]\s*(?:无|没有)(?=$|[\s。．.，,；;!！)）])|no (?:remaining )?warnings|remaining warnings:\s*none\b/i.test(s)) return "";
    const m = /剩余警告[:：]\s*([^。\n]+)|remaining warnings:\s*([^.\n]+)/i.exec(s);
    return m ? (m[1] || m[2]).trim() : null;
  },

  // delete the annotations tagged zotero-scholium, and move the reading notes tagged the same to the
  // trash; the user's annotations and notes stay. A paper with an attachment being annotated or
  // queued is left alone, notes included; messages held after a stop do not count. The outcome is the annotation tab's.
  async removeAnnotations(items) {
    const win = Zotero.getMainWindow();
    const busy = new Set(this.queue.filter(j => !this.isHeld(j)).map(j => j.att.key).concat(this.job ? [this.job.key] : []));
    const atts = this.pdfAttachments(items);
    const skipped = atts.filter(a => busy.has(a.key)).length;
    const busyParents = new Set(atts.filter(a => busy.has(a.key) && a.parentID).map(a => a.parentID));
    const parents = new Set();
    const targets = atts.filter(a => !busy.has(a.key)).map(att => {
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
    if (!total && !notes) { Services.prompt.alert(win, this.text("deleteTitle"), this.text("deleteNone") + skippedText); return 0; }
    if (!Services.prompt.confirm(win, this.text("deleteTitle"), this.text("deleteConfirm", total, notes) + skippedText)) return 0;
    let removed = 0, trashed = 0, current = null;
    try {
      for (const t of targets) {
        current = t;
        if (t.own.length) await Zotero.Items.erase(t.own.map(a => a.id));
        removed += t.own.length;
        if (t.notes.length) await Zotero.Items.trashTx(t.notes.map(n => n.id));
        trashed += t.notes.length;
        this.notes.set(`${t.att.key}/annotate`, { text: this.text("deleteDone", t.own.length, t.notes.length), error: false, at: Date.now() });
      }
      this.notice({ att: targets[0].att, title: this.text("deleteTitle"), kind: "annotate" }, this.text("deleteDone", removed, trashed));
    } catch (e) {
      const message = this.text("deleteFailed", String(e && e.message || e))
        + (removed || trashed ? " " + this.text("deleteDone", removed, trashed) : "");
      this.log("delete failed: " + e);
      const att = (current || targets[0]).att;
      this.notes.set(`${att.key}/annotate`, { text: message, error: true, at: Date.now() });
      this.notice({ att, title: this.text("deleteTitle"), kind: "annotate" }, message, true);
    }
    this.refresh();
    return removed + trashed;
  },

  // `update`: this copy may replace another (an update or a downgrade), which may hand papers over (carryOver); at
  // Zotero's start a hand-over that no copy took is dropped
  start(pluginID, update = false) {
    this.pluginID = pluginID;
    this.registerPane(pluginID);
    try {
      this.selectionHandler = event => this.selectionButton(event);
      Zotero.Reader.registerEventListener("renderTextSelectionPopup", this.selectionHandler, pluginID);
    } catch (e) { this.log("selection popup not registered: " + e); }
    // the Scholium page of Zotero's settings; Zotero removes it when the plugin stops
    if (Zotero.PreferencePanes && this.rootURI) {
      Zotero.PreferencePanes.register({ pluginID, src: this.rootURI + "settings.xhtml", label: "Scholium",
                                        image: this.chrome + "icon20.svg", scripts: [this.rootURI + "settings.js"] })
        .then(id => { this.prefPaneID = id; }, e => this.log("settings page not registered: " + e));
    }
    // the settings page asks what the plugin finds by itself, for the grey text of the program boxes
    this.bridgeApi = { found: agent => this.foundProgram(agent) };
    Zotero.ScholiumBridge = this.bridgeApi;
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
                          compact: !!j.compact, qid: j.qid || null, failed: !!j.failed, quote: j.quote || null, rewind: j.rewind || null });
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
    const paused = this.paused ? { until: this.paused.until, known: this.paused.known, throttled: !!this.paused.throttled } : null;
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
      if (!job || (!qid && (this.busy(job.att.key, kind) || jobs.some(j => !j.qid && j.att.key === job.att.key && j.kind === kind)))) continue;
      const agent = s.agent === "codex" ? "codex" : "claude";
      Object.assign(job, { agent, extra: String(s.extra || ""), say: String(s.say || ""), resume: s.resume || null, asked: !!s.asked,
                           question: !!s.question, annotate: !!s.annotate, own: Number(s.own) || 0, updated: !!s.updated, fresh: !!s.fresh,
                           conv: typeof s.conv === "string" && s.conv ? s.conv : null, asking: !!(s.asking || s.question),
                           logged: !!s.logged, interrupted: !!s.interrupted, throttled: !!s.throttled, retried: !!s.retried,
                           retryAt: Number(s.retryAt) || 0, kind, compact: !!s.compact, qid, failed: !!(qid && s.failed),
                           quote: this.quoteOf(s.quote), rewind: this.pointOf(s.rewind) });
      if (qid) this.qseq = Math.max(this.qseq, Number(qid) || 0);
      // a copy before the paper's conversations hands over its one conversation per agent, which became that agent's
      // first: a paper interrupted there has its turn in that log; an annotation not begun starts a session of its own
      if (!("conv" in s)) {
        if (!job.say && !job.resume) job.annotate = true;
        if (job.resume || job.interrupted || job.retried) job.conv = this.LEGACY[agent];
        else {
          if (job.annotate) job.kind = "annotate";
          await this.place(job);
        }
        if (job.interrupted) job.logged = true;
        // that copy kept neither of these for a follow-up
        job.own = job.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
        const log = await this.readLog(job.att.key, job.conv);
        if (!job.annotate) job.asking = !!(job.question || (log && log.question));
      }
      jobs.push(job);
    }
    if (!jobs.length) return;
    for (const k of (Array.isArray(saved.held) && saved.held) || []) if (typeof k === "string") this.heldQueues.add(k);
    const p = saved.paused;
    if (p && p.until > Date.now() && !this.paused) {   // the limit still holds: the queue waits for it, as before the update
      this.paused = { until: p.until, known: !!p.known, throttled: !!p.throttled,
                      timer: setTimeout(() => { this.resumeQueue(); }, p.until - Date.now()) };
    }
    this.enqueue(jobs);
  },

  // `update`: an update or a downgrade replaces this copy, which hands the papers still to do over to the new one.
  // The running paper's log records that its run was interrupted.
  stop(update = false) {
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
    if (this.paused) clearTimeout(this.paused.timer);
    this.paused = null;
    this.queue = [];
    for (const r of this.removedQueued.values()) clearTimeout(r.timer);
    this.removedQueued.clear();
    for (const r of this.replaced.values()) clearTimeout(r.timer);
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
    this.mathCache.clear();
    this.unsent.clear();
    for (const win of this.windows()) this.removeFromWindow(win);
    try { if (this.paneID) Zotero.ItemPaneManager.unregisterSection(this.paneID); } catch (e) {}
    this.paneID = null;
    try { Zotero.Reader.unregisterEventListener("renderTextSelectionPopup", this.selectionHandler); } catch (e) {}
    this.selectionHandler = null;
    this.pendingQuotes.clear();
    this.prefPaneID = null;
    if (Zotero.ScholiumBridge === this.bridgeApi) delete Zotero.ScholiumBridge;   // a newer copy's stays
    this.bridgeApi = null;
    for (const body of [...this.panes.keys()]) this.dropPane(body);
    this.notes.clear();
    this.job = null;
  },
};

var chromeHandle = null;   // chrome://scholium-bridge-<version>/content/ -> the plugin's content/ folder

// a chrome package per version, e.g. scholium-bridge-0-1-3
function chromePackage(version) {
  return "scholium-bridge-" + String(version || "0").replace(/[^0-9a-z]+/gi, "-").toLowerCase();
}

function install() {}
function uninstall() {}

function onMainWindowLoad({ window }) {
  try { ScholiumRunner.addToWindow(window); } catch (e) {}
}

function onMainWindowUnload({ window }) {
  try { ScholiumRunner.removeFromWindow(window); } catch (e) {}
}

// ADDON_UPGRADE and ADDON_DOWNGRADE: one copy of the plugin replaces another, as the copy that stops is told
function replacing(reason) {
  return [typeof ADDON_UPGRADE === "number" ? ADDON_UPGRADE : 7, typeof ADDON_DOWNGRADE === "number" ? ADDON_DOWNGRADE : 8].includes(reason);
}

// the reasons the new copy of an update may start with: Zotero's handlers forget the old version before they start the
// new one, which then gets ADDON_INSTALL
function takingOver(reason) {
  return replacing(reason) || reason === (typeof ADDON_INSTALL === "number" ? ADDON_INSTALL : 5);
}

async function startup({ id, version, rootURI }, reason) {
  await Zotero.initializationPromise;
  try {
    const aomStartup = Components.classes["@mozilla.org/addons/addon-manager-startup;1"]
      .getService(Components.interfaces.amIAddonManagerStartup);
    const pkg = chromePackage(version);
    chromeHandle = aomStartup.registerChrome(Services.io.newURI(rootURI + "manifest.json"),
      [["content", pkg, rootURI + "content/"]]);
    ScholiumRunner.chrome = "chrome://" + pkg + "/content/";
  } catch (e) { Zotero.debug("[scholium-bridge] chrome registration failed: " + e); }
  ScholiumRunner.version = ScholiumBridge.version = version;
  try { ScholiumToggle.start(id); ScholiumToggle.log("reader toggle registered"); }
  catch (e) { ScholiumToggle.log("reader toggle failed: " + e); }
  ScholiumRunner.rootURI = rootURI;
  try { ScholiumRunner.start(id, takingOver(reason)); ScholiumRunner.log("annotation menu registered"); }
  catch (e) { ScholiumRunner.log("annotation menu failed: " + e); }
  ScholiumBridge.token = await ScholiumBridge.loadToken();
  ScholiumBridge.register();
  if (takingOver(reason)) ScholiumBridge.keep();
  ScholiumBridge.log("endpoints registered");
}

function shutdown(data, reason) {
  try { ScholiumRunner.stop(replacing(reason)); } catch (e) {}
  try { ScholiumToggle.stop(); } catch (e) {}
  try { ScholiumBridge.unregister(); } catch (e) {}
  try { if (chromeHandle) chromeHandle.destruct(); } catch (e) {}
  chromeHandle = null;
}
