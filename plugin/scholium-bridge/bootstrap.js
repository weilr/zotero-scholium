/* Scholium Bridge: a minimal plugin for Zotero 7 and later.
 * Reader toggle (all versions): the eye button in the reader toolbar shows or hides annotations tagged
 * by zotero-scholium in every reader view (tab, window, item-pane preview) at once. The choice is kept
 * in the preference extensions.scholium-bridge.showAnnotations; until it is first switched on, the
 * annotations are hidden. Hiding removes them from the view only; stored items are not changed.
 * One-click annotation (the item context menu needs Zotero 8; the reader's page menu works from 7):
 * starts the installed Claude Code in the background for the selected papers (see ScholiumRunner).
 * Endpoints (needed on Zotero 7 to 9 only), on Zotero's built-in local HTTP server (http://127.0.0.1:23119):
 *   GET  /scholium-bridge/ping   -> { ok, version, dataDir }                       (no token)
 *   POST /scholium-bridge/list   -> annotations of one attachment                  (token)
 *   POST /scholium-bridge/apply  -> clean up + create annotations / child note     (token)
 * No code is evaluated: requests carry plain data (highlight, text, and note annotations).
 * The token is stored in <Zotero data directory>/scholium-bridge.token (created on first start).
 */

var ScholiumBridge = {
  version: "0.1.3",
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

/* One-click annotation (Claude Code): the Scholium section in the item pane (library and reader side
 * pane) starts the user's own, unmodified Claude Code CLI in the background (`claude -p`, signed in
 * with the user's own account; no credentials are read). It runs the zotero-scholium skill on one
 * paper at a time with the Zotero data directory as working directory. The section chooses the
 * model, from the list Claude Code reports, and the effort; it starts, cancels and deletes, shows the
 * state of the paper, and shows the transcript live, like Claude Code: Claude's text, each tool call
 * and its result; for an earlier run it shows the saved log. A box below the transcript takes extra
 * instructions for a new run, or continues the paper's latest conversation (`--resume`). The
 * section opens the annotation profile (<data dir>/zotero-scholium/profile.md), which every run
 * follows, as plain text beside a live Markdown preview in an editor sheet over the Zotero window. The state
 * line shows the turns and tokens of a run; when the usage limit is reached, the queue waits and the
 * interrupted paper continues its conversation after the reset. The section's look is
 * content/scholium.css, linked into each main window. Short notices at the start and the end close by
 * themselves, and a system notification reports the end; both are left out while a Scholium section
 * is on screen in the focused window. Every event is logged to
 * <data dir>/tmp/scholium/<attachment key>/claude-run.jsonl.
 */
var ScholiumRunner = {
  pluginID: null,
  queue: [],                // attachments waiting, in order
  current: null,            // { key, proc, cancelled }
  draining: false,
  job: null,                // { title, key, libraryID, started, step } of the running paper
  last: null,               // { ok, title, key, libraryID, summary, log, at } of the latest finished paper
  notes: new Map(),         // attachment key -> { text, error, at, title }: the latest outcome, shown in its section
  sessions: new Map(),      // attachment key -> Claude Code session of its latest run, which a follow-up continues
  paused: null,             // { until, known, timer } while the usage limit holds the queue
  RETRY_MS: 10 * 60000,     // the wait when Claude Code names no reset time
  pref: "extensions.scholium-bridge.",
  STEPS: ["skill", "extract", "reading", "writing", "dryRun", "applying"],
  TICK_MS: 30000,
  KEEP_DONE_MS: 10 * 60000,
  NOTICE_MS: 6000,
  transcript: [],           // display entries of the running or latest paper
  transcriptKey: null,      // attachment whose run the transcript belongs to
  MAX_ENTRIES: 3000,
  paneID: null,
  panes: new Map(),         // item pane section body -> { doc, keys, list, state, buttons, shownKey, seen }
  models: null,             // [{ value, label, title, efforts }] as Claude Code reports them; null until it answered
  modelsAsked: 0,           // when Claude Code was last asked; a failed request is repeated at most once a minute
  modelsLoading: false,
  DEFAULT_MODEL: "opus",    // Claude Code's alias of the latest Opus, until another model is chosen
  EFFORTS: ["low", "medium", "high", "xhigh", "max"],   // when the model's levels are unknown
  DEFAULT_EFFORT: "medium", // until another level is chosen
  LOG_HEIGHT: 320,
  chrome: "chrome://scholium-bridge/content/",   // the content folder; startup() puts the version into it

  log(msg) { Zotero.debug("[scholium-bridge] " + msg); },

  zh() { return String(Zotero.locale || "").toLowerCase().startsWith("zh"); },

  text(key, ...args) {
    const zh = this.zh();
    const t = {
      headline: zh ? "Scholium 批注" : "Scholium annotation",
      noPdf: zh ? "所选条目没有可用的 PDF 附件。" : "The selected items have no usable PDF attachment.",
      noClaude: zh ? "找不到 Claude Code（claude.exe）。请在 about:config 中设置 extensions.scholium-bridge.claudePath。"
                   : "Claude Code (claude) was not found. Set extensions.scholium-bridge.claudePath in about:config.",
      redoTitle: zh ? "重新批注" : "Annotate again",
      redo: (n, m) => zh ? `${m} 篇论文已有 Scholium 批注，共 ${n} 条。重新批注会替换这些批注，你自己的批注不受影响。继续吗？`
                         : `${m} of the papers already carry ${n} Scholium annotations. Annotating again replaces them; your own annotations are not affected. Continue?`,
      typical: zh ? "已在后台开始，通常需要 10–20 分钟。过程和进度见条目侧栏的 Scholium 区块。"
                  : "Started in the background; this usually takes 10–20 minutes. The Scholium section of the item pane shows the process and the progress.",
      paneModel: zh ? "模型" : "Model",
      paneEffort: zh ? "推理强度" : "Effort",
      paneNoEffort: zh ? "不适用" : "n/a",
      paneClaudeDefault: zh ? "Claude Code 默认" : "Claude Code's default",
      paneClaudeDefaultModel: name => zh ? `Claude Code 默认（${name}）` : `Claude Code's default (${name})`,
      annotateThis: zh ? "批注这篇" : "Annotate",
      deleteThis: zh ? "删除批注" : "Delete annotations",
      logButton: zh ? "打开日志" : "Show log",
      transcriptCaption: zh ? "运行过程" : "Transcript",
      profileOpen: zh ? "个人配置 ↗" : "Personal profile ↗",
      profileTitle: zh ? "个人配置" : "Personal profile",
      profileAbout: zh ? "每次批注都遵循这份画像。重新统计文库只改写开头的统计，Interpretation 和 User's rules 两节保持不变。"
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
      profileReadFailed: msg => zh ? `读不到画像文件：${msg}` : `The profile could not be read: ${msg}`,
      profileFailed: msg => zh ? `保存失败：${msg}` : `The profile could not be saved: ${msg}`,
      noHistory: zh ? "这篇还没有运行记录。" : "This paper has not been run yet.",
      queuedThis: n => zh ? `排队中，前面还有 ${n} 篇` : `Queued, ${n} ahead`,
      otherRunning: title => zh ? `正在批注另一篇：${title}` : `Annotating another paper: ${title}`,
      deleteTitle: zh ? "删除 Scholium 批注" : "Delete Scholium annotations",
      deleteConfirm: (n, m) => zh
        ? `将永久删除 ${m} 篇论文上的 ${n} 条 Scholium 批注（带 zotero-scholium 标签的批注）。你自己的批注和阅读笔记都保留。删除会同步，不能撤销。继续吗？`
        : `This permanently deletes ${n} Scholium annotations (tagged zotero-scholium) on ${m} papers. Your own annotations and the reading notes are kept. The deletion syncs and cannot be undone. Continue?`,
      deleteSkipped: n => zh ? `${n} 篇论文正在批注或排队，不会删除。` : `${n} papers being annotated or queued are skipped.`,
      deleteNone: zh ? "所选论文没有 Scholium 批注。" : "The selected papers carry no Scholium annotations.",
      deleteDone: (n, m) => zh ? `已删除 ${m} 篇论文上的 ${n} 条 Scholium 批注。` : `Deleted ${n} Scholium annotations on ${m} papers.`,
      deleteFailed: msg => zh ? `删除失败：${msg}` : `Deletion failed: ${msg}`,
      model: zh ? "模型" : "Model",
      starting: zh ? "启动 Claude Code" : "starting Claude Code",
      skill: zh ? "加载技能" : "loading the skill",
      extract: zh ? "提取句子" : "extracting sentences",
      reading: zh ? "通读论文" : "reading the paper",
      writing: zh ? "撰写批注" : "writing the annotations",
      dryRun: zh ? "预演检查" : "checking (dry run)",
      applying: zh ? "写入 Zotero" : "writing to Zotero",
      done: zh ? "完成" : "done",
      failed: zh ? "失败" : "failed",
      cancelled: zh ? "已取消" : "cancelled",
      minutes: m => zh ? `${m} 分钟` : `${m} min`,
      stepOf: (i, n, label) => zh ? `第 ${i}/${n} 步 ${label}` : `step ${i}/${n} ${label}`,
      running: (step, time) => zh ? `${step} · 已用 ${time}` : `${step} · ${time} so far`,
      queued: n => zh ? `另有 ${n} 篇排队` : `${n} more queued`,
      finished: title => zh ? `批注完成：${title}` : `Finished: ${title}`,
      failedLine: title => zh ? `批注失败：${title}` : `Failed: ${title}`,
      cancelJob: zh ? "取消批注" : "Cancel the annotation",
      send: zh ? "发送" : "Send",
      extraPlaceholder: zh ? "附加要求（可选），随「批注这篇」一起发送" : "Extra instructions (optional), sent with Annotate",
      followPlaceholder: zh ? "接着对话，例如：第 5 页那条译文改短一些" : "Continue the conversation, e.g. shorten the translation on page 5",
      sendHint: key => zh ? `${key}+Enter 发送` : `${key}+Enter to send`,
      extraLabel: zh ? "附加要求：" : "Extra instructions: ",
      continued: zh ? "额度已恢复，接着中断的地方继续" : "The usage limit has reset; continuing where the run stopped",
      continuing: zh ? "接着上次的对话" : "continuing the conversation",
      continuedNotice: zh ? "已在后台接着上次的对话处理。" : "Continuing the conversation in the background.",
      resumeNow: zh ? "现在继续" : "Continue now",
      limitTitle: zh ? "Claude 额度已用完" : "Claude usage limit reached",
      pausedState: time => zh ? `额度已用完，${time} 重置后自动继续` : `Usage limit reached; continues by itself after ${time}`,
      pausedRetry: time => zh ? `额度已用完，${time} 自动重试` : `Usage limit reached; retries by itself at ${time}`,
      queuedAll: n => zh ? `${n} 篇排队` : `${n} queued`,
      lastRun: zh ? "上次：" : "Last run: ",
      turns: n => zh ? `${n} 轮` : `${n} turns`,
      tokens: amount => zh ? `${amount} token` : `${amount} tokens`,
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

  // the chosen model; "" is Claude Code's own default
  modelPref() {
    const value = this.getPref("claudeModel");
    return typeof value === "string" ? value : this.DEFAULT_MODEL;
  },

  // the effort a run gets: the chosen level, remembered across sessions, when the model accepts it;
  // else medium, or the model's lowest level; none for a model without levels
  effort() {
    const levels = this.effortChoices();
    const chosen = this.getPref("claudeEffort");
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

  // claude.exe directly (the npm shim is a .cmd file, which cannot be started without a shell)
  async findClaude() {
    const configured = this.getPref("claudePath");
    if (configured) return (await this.exists(configured)) ? configured : null;
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

  prompt(job, own) {
    const outDir = this.outDir(job.att.key);
    if (job.resume) return this.followUpPrompt(job);
    if (this.zh()) {
      return [
        "使用 zotero-scholium 技能，为下面这篇论文做整篇标注：重点句高亮加译文评论、页边批注、阅读笔记，按画像和默认值。",
        "",
        `- 条目 key：${job.parentKey}`,
        `- 附件 key：${job.att.key}`,
        `- PDF：${job.path}`,
        `- 输出目录：${outDir}`,
        "",
        "这是从 Zotero 里一键启动的无人值守任务：不要向用户提问，不要启动子代理，由你独立完成第 1–3 步并写入 Zotero。",
        own ? `这篇论文已有 ${own} 条本工具的注释，用户已确认整篇重做。` : "这篇论文目前没有本工具的注释。",
        ...(job.extra ? ["", "用户的附加要求：", job.extra] : []),
        "",
        "结束时最后一行只写一句：高亮 N 条（核心 M 条），页边批注 K 条，笔记标题，剩余警告。",
      ].join("\n");
    }
    return [
      "Use the zotero-scholium skill to annotate the whole paper below: key-sentence highlights with translation comments, margin notes, and a reading note, following the profile and the defaults.",
      "",
      `- Item key: ${job.parentKey}`,
      `- Attachment key: ${job.att.key}`,
      `- PDF: ${job.path}`,
      `- Output directory: ${outDir}`,
      "",
      "This is an unattended task started from Zotero with one click: do not ask the user anything and do not start sub-agents; complete steps 1-3 yourself and write to Zotero.",
      own ? `The paper already carries ${own} annotations of this tool; the user confirmed a complete redo.` : "The paper carries no annotations of this tool yet.",
      ...(job.extra ? ["", "The user's extra instructions:", job.extra] : []),
      "",
      "End with one line only: N highlights (M core), K margin notes, the note title, remaining warnings.",
    ].join("\n");
  },

  // the next message of the paper's conversation: the user's words, or a continuation after the limit
  followUpPrompt(job) {
    const zh = this.zh();
    if (!job.say) {
      return zh ? "额度已恢复。请从中断的地方继续完成上面的任务，规则不变。"
                : "The usage limit has reset. Continue the task above from where it stopped; the rules are unchanged.";
    }
    return (zh ? [
      "下面是用户在 Zotero 里针对这篇论文的批注发来的后续要求。仍是无人值守：不要向用户提问，不要启动子代理；要改批注时按技能的流程修改配置，再写入 Zotero。",
      "",
      job.say,
      "",
      "结束时最后一行只写一句：改了什么，剩余警告。",
    ] : [
      "Below is a follow-up request about this paper's annotations, sent from Zotero. It is still unattended: do not ask the user anything and do not start sub-agents; to change annotations, edit the configuration as the skill describes and write it to Zotero again.",
      "",
      job.say,
      "",
      "End with one line only: what changed, remaining warnings.",
    ]).join("\n");
  },

  outDir(key) { return PathUtils.join(Zotero.DataDirectory.dir, "tmp", "scholium", key); },

  args(job) {
    const args = ["-p", "--output-format", "stream-json", "--verbose",
                  "--permission-mode", this.getPref("claudePermissionMode") || "auto"];
    const home = this.home();
    if (home) args.push("--add-dir", PathUtils.join(home, ".claude", "skills", "zotero-scholium"));
    const outRoot = PathUtils.join(Zotero.DataDirectory.dir, "tmp", "scholium").replace(/\\/g, "/");
    args.push("--allowedTools", "Skill", "Read", `Write(${outRoot}/**)`, `Edit(${outRoot}/**)`);
    const model = this.modelPref();
    if (model) args.push("--model", model);
    const effort = this.effort();
    if (effort) args.push("--effort", effort);
    if (job && job.resume) args.push("--resume", job.resume);
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
      else if (/scholium\.py/.test(cmd) && /\bextract\b/.test(cmd)) step = "extract";
      else if (/scholium\.py/.test(cmd) && /--apply/.test(cmd)) step = "applying";
      else if (/scholium\.py/.test(cmd) && /--config/.test(cmd)) step = "dryRun";
      else if (c.name === "Read" && /sentences\.txt$/i.test(file)) step = "reading";
      else if ((c.name === "Write" || c.name === "Edit") && /scholium/i.test(file.replace(/\\/g, "/"))) step = "writing";
    }
    return step;
  },

  elapsed(started) { return this.text("minutes", Math.max(1, Math.round((Date.now() - started) / 60000))); },

  stepText(step) {
    const i = this.STEPS.indexOf(step);
    return i >= 0 ? this.text("stepOf", i + 1, this.STEPS.length, this.text(step)) : this.text(step || "starting");
  },

  // the running paper's state line: its step, the time so far, and the papers waiting
  runningState() {
    let line = this.text("running", this.stepText(this.job.step), this.elapsed(this.job.started));
    if (this.queue.length) line += " · " + this.text("queued", this.queue.length);
    return line;
  },

  windows() {
    try { return Zotero.getMainWindows ? Zotero.getMainWindows() : [Zotero.getMainWindow()].filter(Boolean); }
    catch (e) { return []; }
  },

  refresh() { this.paintPanes(); },

  // the labels of the section's header and sidenav button, and the section's stylesheet, in a main window
  addToWindow(win) {
    try { if (win.MozXULElement) win.MozXULElement.insertFTLIfNeeded("scholium-bridge.ftl"); } catch (e) {}
    try {
      const doc = win.document;
      if (!doc.getElementById("scholium-bridge-style")) {
        const link = doc.createElementNS("http://www.w3.org/1999/xhtml", "link");
        link.id = "scholium-bridge-style";
        link.setAttribute("rel", "stylesheet");
        link.setAttribute("href", this.chrome + "scholium.css");
        doc.documentElement.append(link);
      }
    } catch (e) { this.log("stylesheet failed: " + e); }
  },

  removeFromWindow(win) {
    if (this.editor && this.editor.doc === win.document) this.closeProfile(this.editor, false);
    try { const link = win.document.querySelector('[href="scholium-bridge.ftl"]'); if (link) link.remove(); } catch (e) {}
    try { const style = win.document.getElementById("scholium-bridge-style"); if (style) style.remove(); } catch (e) {}
  },

  // one stream-json event as display entries, in the manner of Claude Code's transcript
  entries(event) {
    const out = [];
    if (!event || typeof event !== "object") return out;
    if (event.type === "system" && event.subtype === "init") {
      out.push({ kind: "info", text: `${this.text("model")}: ${event.model || "?"}` });
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
    if (event.type === "scholium" && event.subtype === "prompt") out.push({ kind: "prompt", text: String(event.text || "") });
    if (event.type === "scholium" && event.subtype === "continue") out.push({ kind: "info", text: this.text("continued") });
    // a successful result repeats Claude's last message; only a failed run's result is shown
    if (event.type === "result" && (event.is_error || (event.subtype && event.subtype !== "success"))) {
      out.push({ kind: "final", text: String(event.result || event.subtype || "").trim(), error: true });
    }
    return out;
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
    return out || "ok";
  },

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

  dropPane(body) {
    const pane = this.panes.get(body);
    if (!pane) return;
    for (const o of [pane.observer, pane.resizer]) { try { if (o) o.disconnect(); } catch (e) {} }
    this.panes.delete(body);
  },

  // the models Claude Code offers, with the effort levels of each: the initialize request of its
  // stream-json protocol answers without calling a model; only the model list is kept
  async loadModels() {
    if (this.models || this.modelsLoading || Date.now() - this.modelsAsked < 60000) return;
    this.modelsAsked = Date.now();
    this.modelsLoading = true;
    try {
      const models = await this.askModels();
      if (models) {
        this.models = models;
        for (const pane of this.panes.values()) this.fillSelects(pane);
      }
    } catch (e) { this.log("model list failed: " + e); }
    finally { this.modelsLoading = false; }
  },

  async askModels() {
    const claude = await this.findClaude();
    if (!claude) return null;
    const proc = await this.subprocess().call({
      command: claude, arguments: ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"],
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

  // the model options: Claude Code's list once it answered, and the chosen model in any case
  modelChoices() {
    const saved = this.modelPref();
    const list = this.models || [{ value: "", label: this.text("paneClaudeDefault"), title: "", efforts: this.EFFORTS }];
    return list.some(m => m.value === saved) ? list : list.concat([{ value: saved, label: saved, title: "", efforts: this.EFFORTS }]);
  },

  // the effort levels the chosen model accepts
  effortChoices() {
    const saved = this.modelPref();
    return this.modelChoices().find(m => m.value === saved).efforts;
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
      pane.model.replaceChildren(...this.modelChoices().map(m => option(m.value, m.label, m.title)));
      pane.model.value = this.modelPref();
      const levels = this.effortChoices();
      pane.effort.replaceChildren(...(levels.length ? levels.map(e => option(e, e)) : [option("", this.text("paneNoEffort"))]));
      pane.effort.value = this.effort();
      pane.effort.disabled = !levels.length;
    } catch (e) { this.log("selects failed: " + e); }
  },

  // a choice is saved and shown by every pane
  choose(prefName, value) {
    try { Zotero.Prefs.set(this.pref + prefName, value, true); } catch (e) { this.log("preference not saved: " + e); }
    for (const pane of this.panes.values()) this.fillSelects(pane);
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

  logHeight() {
    const h = Number(this.getPref("logHeight"));
    return h >= 80 ? Math.round(h) : this.LOG_HEIGHT;
  },

  // the height dragged at the lower edge of a transcript box is kept for every box
  paneResized(pane) {
    const h = parseInt(pane.list.style.height, 10);
    if (!(h >= 80) || h === this.logHeight()) return;
    try { Zotero.Prefs.set(this.pref + "logHeight", h, true); } catch (e) { this.log("preference not saved: " + e); }
    for (const other of this.panes.values()) {
      if (other !== pane) { try { other.list.style.height = h + "px"; } catch (e) {} }
    }
  },

  renderPane(doc, body, item) {
    const old = this.panes.get(body);
    if (old && old.resizer) { try { old.resizer.disconnect(); } catch (e) {} }
    body.replaceChildren();
    const keys = this.paneKeys(item);
    const pane = { doc, body, item, keys, shownKey: null, history: false, past: null,
                   observer: old ? old.observer : null, seen: !!(old && old.seen), resizer: null };
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
    const field = (text, control) => {
      const label = doc.createElement("label");
      label.className = "scholium-field";
      const caption = doc.createElement("span");
      caption.textContent = text;
      label.append(caption, control);
      return label;
    };
    const box = div("scholium-pane");
    const settings = div("scholium-settings");
    pane.model = doc.createElement("select");
    pane.effort = doc.createElement("select");
    pane.model.className = pane.effort.className = "scholium-select";
    pane.model.addEventListener("change", () => { this.choose("claudeModel", pane.model.value); });
    pane.effort.addEventListener("change", () => { this.choose("claudeEffort", pane.effort.value); });
    this.fillSelects(pane);
    settings.append(field(this.text("paneModel"), pane.model), field(this.text("paneEffort"), pane.effort));
    // the main action first, the contextual ones beside it, deletion apart at the end
    const actions = div("scholium-actions");
    pane.annotate = this.paneButton(doc, this.text("annotateThis"), () => {
      const extra = String(pane.input.value || "").trim();
      this.annotate([item], { extra }).then(n => { if (n && extra) { pane.input.value = ""; this.fitInput(pane); } })
        .catch(e => this.log("annotate failed: " + e));
    }, "primary");
    pane.cancel = this.paneButton(doc, this.text("cancelJob"), () => {
      if (this.job && pane.keys.includes(this.job.key)) this.cancel();
      else this.dequeue(pane.keys);
    });
    pane.resume = this.paneButton(doc, this.text("resumeNow"), () => { this.resumeQueue(); });
    pane.remove = this.paneButton(doc, this.text("deleteThis"), () => { this.removeAnnotations([item]).catch(e => this.log("delete failed: " + e)); },
                                  "quiet danger");
    pane.profile = this.paneButton(doc, this.text("profileOpen"), () => { this.openProfile(doc); }, "quiet");
    actions.append(pane.annotate, pane.cancel, pane.resume, div("scholium-spacer"), pane.profile, pane.remove);
    pane.state = div("scholium-state");
    const caption = div("scholium-caption");
    pane.log = this.paneButton(doc, this.text("logButton"), () => { this.revealLog(pane.shownKey); }, "quiet");
    caption.append(doc.createTextNode(this.text("transcriptCaption")), pane.log);
    pane.list = div("scholium-log");
    pane.list.setAttribute("style", `height: ${this.logHeight()}px;`);
    if (win && win.ResizeObserver) {
      try {
        pane.resizer = new win.ResizeObserver(() => this.paneResized(pane));
        pane.resizer.observe(pane.list);
      } catch (e) { this.log("resize observer failed: " + e); }
    }
    // below the transcript, a message box as in a chat: extra instructions for a new run, or a
    // follow-up; it grows with the text
    const talk = div("scholium-composer");
    pane.input = doc.createElement("textarea");
    pane.input.className = "scholium-input";
    pane.input.setAttribute("rows", "1");
    pane.input.addEventListener("input", () => { this.fitInput(pane); });
    pane.input.addEventListener("keydown", e => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !pane.send.hidden) {
        e.preventDefault();
        this.sendFromPane(pane);
      }
    });
    pane.sendRow = div("scholium-send-row");
    const hint = doc.createElement("span");
    hint.className = "scholium-hint";
    hint.textContent = this.text("sendHint", Services.appinfo && Services.appinfo.OS === "Darwin" ? "⌘" : "Ctrl");
    pane.send = this.paneButton(doc, this.text("send"), () => { this.sendFromPane(pane); }, "primary small");
    pane.sendRow.append(hint, pane.send);
    talk.append(pane.input, pane.sendRow);
    box.append(settings, actions, pane.state, caption, pane.list, talk);
    body.append(box);
    if (this.transcriptKey && keys.includes(this.transcriptKey)) {
      pane.shownKey = this.transcriptKey;
      for (const entry of this.transcript) pane.list.append(this.entryNode(doc, entry));
    }
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
    ed.preview = el("div", "scholium-preview");
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
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    const listItem = /^\s*([-*+]|\d{1,9}[.)])\s+/;
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      let m;
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
      } else {
        const body = [];
        for (; i < lines.length && lines[i].trim() && !this.markdownBlock(lines[i]) && !listItem.test(lines[i]); i++) body.push(lines[i].trim());
        const para = doc.createElement("p");
        this.inlineMarkdown(doc, para, body.join("\n"));
        out.push(para);
      }
    }
    return out;
  },

  markdownRule(line) { return /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line); },

  markdownBlock(line) { return /^\s{0,3}(#{1,6}\s|>|```|~~~)/.test(line) || this.markdownRule(line); },

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
      } else if (width(/^\s*/.exec(line)[0]) >= 2 || (!blank && !this.markdownBlock(line))) {
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

  // `code` (a colour code with a swatch of its colour), **bold**, *italics*, and [links](…) as their text with
  // the address as tooltip, so that nothing in the preview leaves the window
  inlineMarkdown(doc, parent, text) {
    const re = /`([^`\n]+)`|\*\*([^*\n]+?)\*\*|\*([^*\s][^*\n]*?)\*|\[([^\]\n]+)\]\(([^)\s]+)\)/g;
    let at = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m.index > at) parent.append(doc.createTextNode(text.slice(at, m.index)));
      at = re.lastIndex;
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
      } else if (m[2] !== undefined) {
        const strong = doc.createElement("strong");
        this.inlineMarkdown(doc, strong, m[2]);
        parent.append(strong);
      } else if (m[3] !== undefined) {
        const em = doc.createElement("em");
        this.inlineMarkdown(doc, em, m[3]);
        parent.append(em);
      } else {
        const link = doc.createElement("span");
        link.className = "scholium-link";
        link.title = m[5];
        this.inlineMarkdown(doc, link, m[4]);
        parent.append(link);
      }
    }
    if (at < text.length) parent.append(doc.createTextNode(text.slice(at)));
  },

  // the words in a pane's box continue the conversation of the paper it shows
  sendFromPane(pane) {
    const say = String(pane.input.value || "").trim();
    const att = pane.shownKey && Zotero.Items.getByLibraryAndKey(pane.item.libraryID, pane.shownKey);
    if (!say || !att) return;
    this.followUp(att, say).then(sent => { if (sent) { pane.input.value = ""; this.fitInput(pane); } })
      .catch(e => this.log("follow-up failed: " + e));
  },

  // the message box grows with its text, up to its maximum height
  fitInput(pane) {
    try {
      pane.input.style.height = "auto";
      pane.input.style.height = pane.input.scrollHeight + "px";
    } catch (e) {}
    this.paintSend(pane);
  },

  // the send button is enabled while there is something to send
  paintSend(pane) {
    pane.send.disabled = pane.busy || !String(pane.input.value || "").trim();
  },

  // a saved log: its entries, the session to continue, and the result of its latest run; null without a log
  async readLog(key) {
    const path = PathUtils.join(this.outDir(key), "claude-run.jsonl");
    if (!(await this.exists(path))) return null;
    let text;
    try { text = await IOUtils.readUTF8(path); } catch (e) { return null; }
    const entries = [];
    let session = null, result = null;
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      let event;
      try { event = JSON.parse(line); } catch (e) { continue; }
      if (typeof event.session_id === "string" && event.session_id) session = event.session_id;
      if (event.type === "system" && event.subtype === "init") result = null;
      if (event.type === "result") result = event;
      this.addEntries(entries, this.entries(event));
    }
    if (session && !this.sessions.has(key)) this.sessions.set(key, session);
    return { entries: entries.slice(-this.MAX_ENTRIES), session, result };
  },

  // the saved log of an earlier run, when the paper has one and nothing newer is shown
  async loadHistory(body) {
    const pane = this.panes.get(body);
    if (!pane || pane.shownKey) return;
    for (const key of pane.keys) {
      const log = await this.readLog(key);
      if (!log) continue;
      if (this.panes.get(body) !== pane || pane.shownKey) return;   // re-rendered or a run started meanwhile
      pane.shownKey = key;
      pane.history = true;
      pane.past = log.result ? { text: this.text("lastRun") + this.outcome(log.result), error: !this.succeeded(log.result),
                                 title: this.tokenDetail(log.result) } : null;
      pane.list.replaceChildren(...log.entries.map(e => this.entryNode(pane.doc, e)));
      pane.list.scrollTop = pane.list.scrollHeight;
      this.paintPane(pane);
      return;
    }
    if (!pane.shownKey) pane.list.replaceChildren(this.entryNode(pane.doc, { kind: "info", text: this.text("noHistory") }));
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

  // one transcript entry: a bullet column beside the content, so that wrapped lines keep their indent;
  // the stylesheet sets Claude's text in the pane's font, tool calls and results in monospace, and the
  // user's words in a bubble on the right
  entryNode(doc, entry) {
    const node = doc.createElement("div");
    node.className = `scholium-entry ${entry.kind}${entry.error ? " error" : ""}`;
    const bullet = { text: "⏺ ", tool: "⏺ ", result: "⎿ " }[entry.kind];
    if (bullet) {
      const span = doc.createElement("span");
      span.className = "scholium-bullet";
      span.textContent = bullet;
      node.append(span);
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

  appendEntries(entries) {
    const added = this.addEntries(this.transcript, entries);
    if (!added.length) return;
    if (this.transcript.length > this.MAX_ENTRIES) this.transcript.splice(0, this.transcript.length - this.MAX_ENTRIES);
    for (const pane of this.panes.values()) {
      if (pane.shownKey !== this.transcriptKey) continue;
      try {
        const list = pane.list;
        const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
        for (const entry of added) list.append(this.entryNode(pane.doc, entry));
        if (atBottom) list.scrollTop = list.scrollHeight;
      } catch (e) {}
    }
  },

  // a run of this paper replaces whatever the panes of the paper show with its transcript
  startPanes(key) {
    for (const pane of this.panes.values()) {
      if (!pane.keys.includes(key)) continue;
      pane.shownKey = key;
      pane.history = false;
      pane.past = null;
      try {
        pane.list.replaceChildren(...this.transcript.map(e => this.entryNode(pane.doc, e)));
        pane.list.scrollTop = pane.list.scrollHeight;
      } catch (e) {}
    }
  },

  succeeded(result) {
    return !!result && !result.is_error && (!result.subtype || result.subtype === "success");
  },

  // 完成 · 6 分钟 · 29 轮 · 257 万 token
  outcome(result, cancelled = false, started = 0) {
    const parts = [this.text(cancelled ? "cancelled" : this.succeeded(result) ? "done" : "failed")];
    const ms = result && result.duration_ms > 0 ? result.duration_ms : started ? Date.now() - started : 0;
    if (ms || started) parts.push(this.text("minutes", Math.max(1, Math.round(ms / 60000))));
    if (result && result.num_turns > 0) parts.push(this.text("turns", result.num_turns));
    const tokens = this.tokenCounts(result).reduce((n, [, count]) => n + count, 0);
    if (tokens) parts.push(this.text("tokens", this.amount(tokens)));
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
    return counts.some(([, n]) => n) ? counts.map(([label, n]) => `${this.text(label)} ${this.amount(n)}`).join(" · ") : "";
  },

  amount(n) {
    if (this.zh()) return n >= 1e4 ? `${+(n / 1e4).toFixed(n >= 1e6 ? 0 : 1)} 万` : String(n);
    return n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${+(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k` : String(n);
  },

  // 21:05 today, otherwise with the date
  clock(ms) {
    const d = new Date(ms);
    const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    if (d.toDateString() === new Date().toDateString()) return hm;
    return this.zh() ? `${d.getMonth() + 1}月${d.getDate()}日 ${hm}` : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
  },

  // the state line: this paper running, queued or paused, its latest outcome, or another paper's run
  paintPane(pane) {
    try {
      const running = this.job && pane.keys.includes(this.job.key);
      const queuedAt = this.queue.findIndex(j => pane.keys.includes(j.att.key));
      const note = pane.keys.map(k => this.notes.get(k)).filter(Boolean).sort((a, b) => b.at - a.at)[0] || pane.past;
      const paused = this.paused ? this.text(this.paused.known ? "pausedState" : "pausedRetry", this.clock(this.paused.until)) : null;
      const lines = [];
      let kind = "info", title = "";
      if (running) {
        lines.push(this.runningState());
        kind = "running";
      } else if (queuedAt >= 0) {
        if (!(paused && queuedAt === 0)) lines.push(this.text("queuedThis", queuedAt + (this.job ? 1 : 0)));
        if (paused) { lines.push(paused); kind = "paused"; }
      } else {
        if (note) { lines.push(note.text); kind = note.error ? "error" : "ok"; title = note.title || ""; }
        if (this.job) lines.push(this.text("otherRunning", this.job.title));
        else if (paused) {
          lines.push(`${paused} · ${this.text("queuedAll", this.queue.length)}`);
          if (!note) kind = "paused";
        } else if (!note && this.last && Date.now() - this.last.at < this.KEEP_DONE_MS) {
          lines.push(this.text(this.last.ok ? "finished" : "failedLine", this.last.title));
          kind = this.last.ok ? "ok" : "error";
        }
      }
      pane.state.className = `scholium-state ${kind}`;
      pane.state.textContent = lines.join("\n");
      pane.state.title = title;
      this.show(pane.state, lines.length > 0);
      const busy = !!running || queuedAt >= 0;
      pane.annotate.disabled = busy;
      pane.remove.disabled = busy;
      this.show(pane.cancel, !!((running && this.current) || queuedAt >= 0));
      this.show(pane.resume, !!this.paused);
      pane.log.disabled = !pane.shownKey;
      const session = pane.shownKey ? this.sessions.get(pane.shownKey) : null;
      pane.busy = busy;
      this.show(pane.send, !!session);
      this.show(pane.sendRow, !!session);
      pane.input.placeholder = this.text(session ? "followPlaceholder" : "extraPlaceholder");
      this.paintSend(pane);
    } catch (e) {}
  },

  paintPanes() {
    for (const [body, pane] of this.panes) {
      if (body.isConnected === false) { this.dropPane(body); continue; }
      this.paintPane(pane);
    }
  },

  // whether a Scholium section is on screen in the focused window; it then shows what a corner notice
  // or the system notification would say
  paneInView() {
    for (const [body, pane] of this.panes) {
      try {
        const win = pane.doc.defaultView;
        if (!pane.seen || body.isConnected === false || !win || !win.document.hasFocus()) continue;
        if (typeof body.checkVisibility === "function" && !body.checkVisibility({ visibilityProperty: true })) continue;
        return true;
      } catch (e) {}
    }
    return false;
  },

  revealLog(key) {
    if (!key) return;
    try { Zotero.File.reveal(PathUtils.join(this.outDir(key), "claude-run.jsonl")); } catch (e) { this.log("reveal failed: " + e); }
  },

  // system notification, visible while Zotero is in the background
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

  // queue the selected papers; returns how many were queued
  async annotate(items, { extra = "" } = {}) {
    const jobs = [];
    let found = 0;
    for (const item of items || []) {
      try {
        const job = await this.resolve(item);
        if (job) found += 1;
        if (job && !jobs.some(j => j.att.key === job.att.key) && !this.busy(job.att.key)) jobs.push(job);
      } catch (e) { this.log("resolve failed: " + e); }
    }
    const win = Zotero.getMainWindow();
    if (!found) { Services.prompt.alert(win, this.text("headline"), this.text("noPdf")); return 0; }
    if (!jobs.length) { this.refresh(); return 0; }   // every paper is already queued or running
    const own = jobs.map(j => j.att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length);
    const total = own.reduce((a, b) => a + b, 0);
    if (total && !Services.prompt.confirm(win, this.text("redoTitle"), this.text("redo", total, own.filter(Boolean).length))) return 0;
    jobs.forEach((j, i) => { j.own = own[i]; j.extra = extra; });
    this.enqueue(jobs);
    return jobs.length;
  },

  // continue the paper's latest conversation with the user's words; false when that is not possible now
  async followUp(att, say) {
    const session = att && this.sessions.get(att.key);
    if (!session || !say || this.busy(att.key)) return false;
    const job = await this.resolve(att);
    if (!job) return false;
    job.resume = session;
    job.say = say;
    this.enqueue([job]);
    return true;
  },

  busy(key) {
    return !!(this.job && this.job.key === key) || this.queue.some(j => j.att.key === key);
  },

  enqueue(jobs) {
    this.queue.push(...jobs);
    this.refresh();
    if (!this.draining) this.drain();
  },

  // take papers out of the queue; when nothing is left, a pause ends
  dequeue(keys) {
    this.queue = this.queue.filter(j => !keys.includes(j.att.key));
    if (!this.queue.length && this.paused) {
      clearTimeout(this.paused.timer);
      this.paused = null;
    }
    this.refresh();
  },

  // one paper at a time; `draining` also covers the moments before a process exists. The usage limit
  // pauses the queue.
  async drain() {
    this.draining = true;
    try {
      while (this.queue.length && !this.paused) {
        const job = this.queue.shift();
        let outcome = null;
        try { outcome = await this.run(job); }
        catch (e) {
          const message = String(e && e.message || e).slice(0, 300);
          this.current = null;
          this.appendEntries([{ kind: "final", text: message, error: true }]);
          this.notice(job, `${this.text("failed")} · ${message}`, true);
          this.finish(job, false, message);
          this.log("run failed: " + e);
        }
        if (outcome && outcome.limited) this.pause(job, outcome);
      }
    } finally {
      this.draining = false;
      this.refresh();
    }
  },

  // the usage limit: the interrupted paper waits at the head of the queue and continues its
  // conversation when the limit resets; nothing else starts meanwhile
  pause(job, { until, session }) {
    if (this.job && this.job.key === job.att.key) this.job = null;
    this.queue.unshift(session ? Object.assign({}, job, { resume: session, say: "", extra: "" }) : job);
    const wait = until ? Math.max(until - Date.now(), 0) + 60000 : this.RETRY_MS;
    if (this.paused) clearTimeout(this.paused.timer);
    this.paused = { until: Date.now() + wait, known: !!until, timer: setTimeout(() => { this.resumeQueue(); }, wait) };
    const line = this.text(until ? "pausedState" : "pausedRetry", this.clock(this.paused.until));
    this.notice(job, line, true);
    if (!this.paneInView()) this.notify(this.text("limitTitle"), line);
    this.refresh();
  },

  resumeQueue() {
    if (!this.paused) return;
    clearTimeout(this.paused.timer);
    this.paused = null;
    this.refresh();
    if (!this.draining && this.queue.length) this.drain();
  },

  // a short notice in the corner of the window that closes by itself; left out while a Scholium
  // section is on screen, whose state line says the same
  notice(job, text, error = false) {
    if (this.paneInView()) return;
    try {
      const pw = new Zotero.ProgressWindow({ closeOnClick: true });
      pw.changeHeadline(this.text("headline"));
      let icon = null;
      try { if (job.att) icon = job.att.getItemTypeIconName(); } catch (e) {}
      const line = new pw.ItemProgress(icon, job.title);
      if (error) line.setError(); else line.setProgress(100);
      pw.addDescription(text);
      pw.show();
      pw.startCloseTimer(error ? 2 * this.NOTICE_MS : this.NOTICE_MS);
    } catch (e) { this.log("notice failed: " + e); }
  },

  // record the end of one paper: its section keeps the outcome in short, the transcript has the rest
  finish(job, ok, summary, outcome, detail) {
    if (this.job && this.job.key === job.att.key) this.job = null;
    const title = this.text(ok ? "finished" : "failedLine", job.title);
    this.last = { ok, title: job.title, key: job.att.key, libraryID: job.att.libraryID, summary,
                  log: PathUtils.join(this.outDir(job.att.key), "claude-run.jsonl"), at: Date.now() };
    this.notes.set(job.att.key, { text: outcome || this.text(ok ? "done" : "failed"), error: !ok, at: Date.now(), title: detail || "" });
    if (!this.paneInView()) this.notify(title, summary || "");
    this.refresh();
  },

  async tick(job) {
    while (this.job === job) {
      await Zotero.Promise.delay(this.TICK_MS);
      if (this.job === job) this.refresh();
    }
  },

  async run(job) {
    const started = Date.now();
    const key = job.att.key;
    this.job = { title: job.title, key, libraryID: job.att.libraryID, started, step: job.resume ? "continuing" : "starting" };
    const running = this.job;
    // a continued conversation keeps its transcript; a new run starts afresh
    this.transcript = job.resume ? ((await this.readLog(key)) || { entries: [] }).entries : [];
    this.transcriptKey = key;
    this.startPanes(key);
    this.notice(job, this.text(job.resume ? "continuedNotice" : "typical"));
    this.refresh();
    this.tick(running).catch(() => {});
    const claude = await this.findClaude();
    if (!claude) {
      this.appendEntries([{ kind: "final", text: this.text("noClaude"), error: true }]);
      this.notice(job, this.text("noClaude"), true);
      this.finish(job, false, this.text("noClaude"));
      return;
    }
    const outDir = this.outDir(key);
    await IOUtils.makeDirectory(outDir, { createAncestors: true, ignoreExisting: true });
    const logPath = PathUtils.join(outDir, "claude-run.jsonl");
    if (!job.resume || !(await this.exists(logPath))) await IOUtils.writeUTF8(logPath, "");
    // the user's words, or an automatic continuation, go into the log as the plugin's own lines
    const mark = job.say || job.extra ? { type: "scholium", subtype: "prompt", text: job.say || this.text("extraLabel") + job.extra }
      : job.resume ? { type: "scholium", subtype: "continue" } : null;
    if (mark) {
      await IOUtils.writeUTF8(logPath, JSON.stringify(mark) + "\n", { mode: "append" });
      this.appendEntries(this.entries(mark));
    }
    let result = null, buffer = "", lastStep = -1, stderr = "", session = job.resume || null, limit = null;
    const Subprocess = this.subprocess();
    const proc = await Subprocess.call({
      command: claude, arguments: this.args(job), workdir: Zotero.DataDirectory.dir, stderr: "pipe",
      environment: { PYTHONIOENCODING: "utf-8" }, environmentAppend: true,
    });
    this.current = { key, proc, cancelled: false };
    const current = this.current;
    this.refresh();
    await proc.stdin.write(this.prompt(job, job.own));
    await proc.stdin.close();
    const drainErr = (async () => {
      for (;;) { const s = await proc.stderr.readString(); if (!s) break; stderr = (stderr + s).slice(-2000); }
    })().catch(() => {});
    for (;;) {
      const chunk = await proc.stdout.readString();
      if (!chunk) break;
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      if (lines.length) await IOUtils.writeUTF8(logPath, lines.join("\n") + "\n", { mode: "append" });
      for (const raw of lines) {
        let event;
        try { event = JSON.parse(raw); } catch (e) { continue; }
        if (typeof event.session_id === "string" && event.session_id) {
          session = event.session_id;
          this.sessions.set(key, session);
        }
        if (event.type === "result") result = event;
        if (event.type === "rate_limit_event" && event.rate_limit_info) {
          const info = event.rate_limit_info;
          if (info.status === "rejected") limit = { until: info.resetsAt > 0 ? info.resetsAt * 1000 : null };
        }
        if (event.type === "assistant" && event.error === "rate_limit" && !limit) limit = { until: null };
        this.appendEntries(this.entries(event));
        const step = this.step(event);
        const i = step ? this.STEPS.indexOf(step) : -1;
        if (i > lastStep) {
          lastStep = i;
          running.step = step;
          this.refresh();
        }
      }
    }
    await drainErr;
    const { exitCode } = await proc.wait();
    this.current = null;
    const summary = result && typeof result.result === "string" ? result.result.trim().split("\n").pop() : "";
    let ok = false, message;
    if (current.cancelled) {
      message = this.text("cancelled");
      this.appendEntries([{ kind: "final", text: message, error: true }]);
      this.notice(job, message, true);
    } else if (exitCode === 0 && result && !result.is_error) {
      ok = true;
      message = summary;
      this.notice(job, `${this.text("done")} · ${this.elapsed(started)}${summary ? "\n" + summary : ""}`);
    } else if (limit) {
      return { exitCode, result, limited: true, until: limit.until, session };
    } else {
      message = (summary || stderr.trim().split("\n").pop() || `exit ${exitCode}`).slice(0, 300);
      if (!(result && this.entries(result).length)) this.appendEntries([{ kind: "final", text: message, error: true }]);
      this.notice(job, `${this.text("failed")} · ${message}`, true);
    }
    this.finish(job, ok, message, this.outcome(result, current.cancelled, started), this.tokenDetail(result));
    return { exitCode, result };
  },

  cancel() {
    const current = this.current;
    if (!current) return false;
    current.cancelled = true;
    try { current.proc.kill(); } catch (e) {}
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

  // delete the annotations tagged zotero-scholium; user annotations and notes stay
  async removeAnnotations(items) {
    const win = Zotero.getMainWindow();
    const busy = new Set(this.queue.map(j => j.att.key).concat(this.job ? [this.job.key] : []));
    const atts = this.pdfAttachments(items);
    const skipped = atts.filter(a => busy.has(a.key)).length;
    const targets = atts.filter(a => !busy.has(a.key))
      .map(att => ({ att, own: att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)) }))
      .filter(t => t.own.length);
    const total = targets.reduce((n, t) => n + t.own.length, 0);
    const skippedText = skipped ? "\n\n" + this.text("deleteSkipped", skipped) : "";
    if (!total) { Services.prompt.alert(win, this.text("deleteTitle"), this.text("deleteNone") + skippedText); return 0; }
    if (!Services.prompt.confirm(win, this.text("deleteTitle"), this.text("deleteConfirm", total, targets.length) + skippedText)) return 0;
    let removed = 0, papers = 0, current = null;
    try {
      for (const t of targets) {
        current = t;
        await Zotero.Items.erase(t.own.map(a => a.id));
        this.notes.set(t.att.key, { text: this.text("deleteDone", t.own.length, 1), error: false, at: Date.now() });
        removed += t.own.length;
        papers += 1;
      }
      this.notice({ att: targets[0].att, title: this.text("deleteTitle") }, this.text("deleteDone", removed, papers));
    } catch (e) {
      const message = this.text("deleteFailed", String(e && e.message || e));
      this.log("delete failed: " + e);
      if (current) this.notes.set(current.att.key, { text: message, error: true, at: Date.now() });
      this.notice({ att: null, title: this.text("deleteTitle") }, message + "\n" + this.text("deleteDone", removed, papers), true);
    }
    this.refresh();
    return removed;
  },

  start(pluginID) {
    this.pluginID = pluginID;
    this.registerPane(pluginID);
    for (const win of this.windows()) this.addToWindow(win);
  },

  stop() {
    if (this.editor) this.closeProfile(this.editor, false);
    if (this.paused) clearTimeout(this.paused.timer);
    this.paused = null;
    this.queue = [];
    this.cancel();
    for (const win of this.windows()) this.removeFromWindow(win);
    try { if (this.paneID) Zotero.ItemPaneManager.unregisterSection(this.paneID); } catch (e) {}
    this.paneID = null;
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

async function startup({ id, version, rootURI }) {
  await Zotero.initializationPromise;
  try {
    const aomStartup = Components.classes["@mozilla.org/addons/addon-manager-startup;1"]
      .getService(Components.interfaces.amIAddonManagerStartup);
    const pkg = chromePackage(version);
    chromeHandle = aomStartup.registerChrome(Services.io.newURI(rootURI + "manifest.json"),
      [["content", pkg, rootURI + "content/"]]);
    ScholiumRunner.chrome = "chrome://" + pkg + "/content/";
  } catch (e) { Zotero.debug("[scholium-bridge] chrome registration failed: " + e); }
  try { ScholiumToggle.start(id); ScholiumToggle.log("reader toggle registered"); }
  catch (e) { ScholiumToggle.log("reader toggle failed: " + e); }
  try { ScholiumRunner.start(id); ScholiumRunner.log("annotation menu registered"); }
  catch (e) { ScholiumRunner.log("annotation menu failed: " + e); }
  ScholiumBridge.token = await ScholiumBridge.loadToken();
  ScholiumBridge.register();
  ScholiumBridge.log("endpoints registered");
}

function shutdown() {
  try { ScholiumRunner.stop(); } catch (e) {}
  try { ScholiumToggle.stop(); } catch (e) {}
  try { ScholiumBridge.unregister(); } catch (e) {}
  try { if (chromeHandle) chromeHandle.destruct(); } catch (e) {}
  chromeHandle = null;
}
