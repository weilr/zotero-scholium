/* Scholium Bridge: a minimal plugin for Zotero 7 to 9.
 * Registers three endpoints on Zotero's built-in local HTTP server (http://127.0.0.1:23119):
 *   GET  /scholium-bridge/ping   -> { ok, version, dataDir }                       (no token)
 *   POST /scholium-bridge/list   -> annotations of one attachment                  (token)
 *   POST /scholium-bridge/apply  -> clean up + create annotations / child note     (token)
 * No code is evaluated: requests carry plain data (highlight, text, and note annotations).
 * The token is stored in <Zotero data directory>/scholium-bridge.token (created on first start).
 */

var ScholiumBridge = {
  version: "0.1.1",
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

function install() {}
function uninstall() {}

async function startup({ id, version, rootURI }) {
  await Zotero.initializationPromise;
  ScholiumBridge.token = await ScholiumBridge.loadToken();
  ScholiumBridge.register();
  ScholiumBridge.log("endpoints registered");
}

function shutdown() {
  try { ScholiumBridge.unregister(); } catch (e) {}
}
