// ScholiumEndpoints: the plugin's endpoints on Zotero's local HTTP server and their token

var ScholiumEndpoints = {
  version: "",              // the plugin's, from its manifest (startup)
  // the tags that mark the tool's annotations and notes, the current one first: only these are removed or trashed
  OWN_TAGS: ["zotero-scholium", "zotero-marginalia", "zotero-paper-annotate"],
  token: null,
  timer: null,
  // the second three are Scholium Bridge 0.1.9's paths, which its skill calls
  paths: ["/scholium/ping", "/scholium/list", "/scholium/apply", "/scholium-bridge/ping", "/scholium-bridge/list", "/scholium-bridge/apply"],

  log(msg) { Zotero.debug("[scholium] " + msg); },

  // the token of scholium.token; without that file, the one of scholium-bridge.token (Scholium Bridge 0.1.9's), else a
  // new one. Both files hold it: the skill of Scholium Bridge 0.1.9 reads the second
  async loadToken() {
    const files = ["scholium.token", "scholium-bridge.token"].map(name => PathUtils.join(Zotero.DataDirectory.dir, name));
    const held = [];   // each file's text, null without the file
    for (const path of files) {
      try { held.push(await IOUtils.exists(path) ? (await IOUtils.readUTF8(path)).trim() : null); }
      catch (e) { held.push(""); this.log("token read failed: " + e); }
    }
    const valid = t => typeof t === "string" && t.length >= 16;
    const t = valid(held[0]) ? held[0] : held[0] === null && valid(held[1]) ? held[1] : Zotero.Utilities.randomString(40);
    if (held[0] !== t) await IOUtils.writeUTF8(files[0], t);
    if (held[1] !== t) {
      try { await IOUtils.writeUTF8(files[1], t); } catch (e) { this.log("token not written to scholium-bridge.token: " + e); }
    }
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

  // the library a request names: a group by its id (groupID), or a library by its id (libraryID); My Library without either
  library(data) {
    if (data.groupID !== undefined && data.groupID !== null && data.groupID !== "") {
      const id = Zotero.Groups.getLibraryIDFromGroupID(Number(data.groupID));
      if (!id) throw new Error(`group ${data.groupID} not found in this Zotero; check group_id in the configuration`);
      return id;
    }
    if (data.libraryID !== undefined && data.libraryID !== null && data.libraryID !== "") {
      const id = Number(data.libraryID);
      if (!Zotero.Libraries.get(id)) throw new Error(`library ${data.libraryID} not found in this Zotero; check library_id in the configuration`);
      return id;
    }
    return Zotero.Libraries.userLibraryID;
  },

  // the PDF attachment a request names, in its library
  attachment(data, libraryID) {
    const att = Zotero.Items.getByLibraryAndKey(libraryID, data.attachmentKey);
    if (!att) throw new Error("attachment not found: " + data.attachmentKey
                              + (libraryID === Zotero.Libraries.userLibraryID ? " in My Library" : " in library " + libraryID));
    return att;
  },

  // the attachment's annotations and its item's notes, the tool's notes with their HTML when asked (noteHtml: whether the
  // user changed one); canUpdate: apply takes a rewrite in place
  async list(data) {
    const libraryID = this.library(data);
    const att = this.attachment(data, libraryID);
    const anns = att.getAnnotations(true).map(a => this.summarize(a));
    const notes = [];
    const parent = att.parentID ? Zotero.Items.get(att.parentID) : null;
    if (parent) {
      for (const n of Zotero.Items.get(parent.getNotes())) {
        const tags = n.getTags().map(t => t.tag);
        notes.push(Object.assign({ key: n.key, title: n.getNoteTitle(), tags },
                                 data.noteHtml && tags.some(t => this.OWN_TAGS.includes(t)) ? { html: n.getNote() } : {}));
      }
    }
    return { ok: true, version: this.version, canUpdate: true, libraryID, attachmentKey: att.key, parentKey: parent ? parent.key : null,
             annotations: anns, notes };
  },

  async apply(data) {
    const libraryID = this.library(data);
    const att = this.attachment(data, libraryID);
    const lib = libraryID === Zotero.Libraries.userLibraryID ? null : Zotero.Libraries.get(libraryID);
    if (lib && (lib.editable === false || lib.filesEditable === false)) {
      throw new Error("You cannot edit this group's library, so annotations cannot be written.");
    }
    const parent = att.parentID ? Zotero.Items.get(att.parentID) : null;
    if (data.itemKey && data.itemKey !== att.key && !(parent && parent.key === data.itemKey)) {
      throw new Error(`item ${data.itemKey} is not the parent of attachment ${data.attachmentKey}; set item_key to the attachment's parent key from status`);
    }
    if (data.note && data.note.html && !parent) throw new Error(`attachment ${data.attachmentKey} has no parent item to hold the note`);
    const anns = Array.isArray(data.annotations) ? data.annotations : [];

    // (0) cleanup: annotations tagged by this tool, and external (PDF-imported, locked) annotations when
    //     data.cleanupExternal is true. They are removed in (2), after the new annotations are saved.
    //     A rewrite in place (data.rewrite) names them: those to change (updates, with the fields that change), to keep
    //     as they are and to remove; one that is not the tool's on this attachment (an external one may be removed), or
    //     one of the tool's that it does not name, ends the write before anything is saved
    const tag = data.tag || "";
    if (tag && tag !== this.OWN_TAGS[0]) throw new Error(`tag must be ${this.OWN_TAGS[0]}`);
    const ownTags = new Set(this.OWN_TAGS);
    const isOwn = a => a.getTags().some(t => ownTags.has(t.tag));
    let old = [];
    let kept = 0;
    const changes = [], keep = Array.isArray(data.keep) ? data.keep.map(String) : [];
    if (data.rewrite) {
      const byKey = new Map(att.getAnnotations(true).map(a => [a.key, a]));
      const updates = Array.isArray(data.updates) ? data.updates : [], remove = Array.isArray(data.remove) ? data.remove.map(String) : [];
      const stranger = k => new Error(`annotation ${k} is not one of the tool's on this attachment; run the tool again`);
      const all = updates.map(u => String(u.key)).concat(keep, remove);
      if (new Set(all).size !== all.length) throw new Error("an annotation is named twice in the rewrite; run the tool again");
      if (remove.length && data.cleanup === false) throw new Error("a rewrite without cleanup removes nothing; run the tool again");
      for (const k of updates.map(u => String(u.key)).concat(keep)) if (!byKey.has(k) || !isOwn(byKey.get(k))) throw stranger(k);
      for (const k of remove) {
        const a = byKey.get(k);
        if (!a || !(isOwn(a) || (data.cleanupExternal && a.annotationIsExternal))) throw stranger(k);
      }
      // each one it changes or removes as the tool read it (expect: its date then); one changed since is left alone
      const day = s => String(s || "").replace("T", " ").replace(/Z$/, "").replace(/\.\d+$/, "").trim();
      for (const [k, d] of Object.entries(data.expect && typeof data.expect === "object" ? data.expect : {})) {
        if (byKey.has(k) && day(byKey.get(k).dateModified) !== day(d)) {
          throw new Error(`the tool's annotations on the attachment changed since they were read (${k}); run the tool again`);
        }
      }
      const named = new Set(all);
      if (data.cleanup !== false) {
        for (const a of byKey.values()) {
          if (isOwn(a) && !named.has(a.key)) throw new Error("the tool's annotations on the attachment changed since they were read; run the tool again");
        }
      }
      old = remove.map(k => byKey.get(k));
      for (const u of updates) changes.push([byKey.get(String(u.key)), u]);
      for (const a of byKey.values()) if (!isOwn(a) && !remove.includes(a.key)) kept++;   // the user's, as without a rewrite
    } else if (data.cleanup !== false) {
      for (const a of att.getAnnotations(true)) {
        const mine = isOwn(a) || (data.cleanupExternal && a.annotationIsExternal);
        if (mine) old.push(a); else kept++;
      }
    }

    // (1) child note. A note of this tool with the same text is not written again, nor one with the same title.
    //     With note.trashOwn, the tool's other notes (titles starting with trashTitlePrefix, when given) go to the
    //     trash once everything is written; notes without the tool's tags are never touched.
    let noteCreated = false, noteSkipped = false, notesTrashed = 0, newNote = null, rewriteNote = null;
    const trash = [], noteKeys = [], createdKeys = [], updatedKeys = [];
    if (data.note && data.note.html && parent) {
      const prefix = data.note.titlePrefix || "";
      const body = html => String(html || "").replace(/<h1[^>]*>[\s\S]*?<\/h1>/i, " ").replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
      const existingNotes = Zotero.Items.get(parent.getNotes());
      const own = n => n.getTags().some(t => ownTags.has(t.tag));
      const same = existingNotes.find(n => own(n) && body(n.getNote()) === body(data.note.html));
      // the tool's note a rewrite names (updateKey) is written over in place, keeping its key, while it is as the plan read it
      // (expectHtml); else it goes to the trash with the others and a new one is written
      const target = data.note.updateKey ? existingNotes.find(n => n.key === String(data.note.updateKey) && own(n)
                                                              && (data.note.expectHtml === undefined || n.getNote() === data.note.expectHtml)) || null : null;
      if (data.note.trashOwn) {
        const only = data.note.trashTitlePrefix || "";
        for (const n of existingNotes) if (own(n) && n !== same && n !== target && (n.getNoteTitle() || "").startsWith(only)) trash.push(n.id);
      }
      if (data.note.trashOwn && same && target && target !== same) trash.push(target.id);   // replaced by the same text
      if (!same && target) {
        rewriteNote = target;
      } else if (same || (prefix && existingNotes.some(n => !trash.includes(n.id) && (n.getNoteTitle() || "").startsWith(prefix)))) {
        noteSkipped = true;
      } else {
        newNote = new Zotero.Item("note");
        newNote.libraryID = libraryID;
        newNote.parentID = parent.id;
        newNote.setNote(data.note.html);
        if (tag) newNote.setTags([{ tag }]);
      }
    }

    // (2) the note and the annotations, then the old ones go, in one transaction: a failure leaves the paper as it was
    const created = { highlight: 0, underline: 0, text: 0, note: 0 };
    const allowed = new Set(["highlight", "underline", "text", "note"]);
    await Zotero.DB.executeTransaction(async () => {
      if (newNote) await newNote.save();
      if (rewriteNote) {
        rewriteNote.setNote(data.note.html);
        await rewriteNote.save();
      }
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
        ann.annotationColor = String(a.color || "#ffd400").toLowerCase();
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
      // the changes in place: only the fields given, which are those that changed
      for (const [ann, u] of changes) {
        if ("comment" in u) ann.annotationComment = String(u.comment || "");
        if ("color" in u) ann.annotationColor = String(u.color || "#ffd400").toLowerCase();
        if ("text" in u && (ann.annotationType === "highlight" || ann.annotationType === "underline")) ann.annotationText = String(u.text || "");
        if ("pageLabel" in u) ann.annotationPageLabel = String(u.pageLabel);
        if ("sortIndex" in u) ann.annotationSortIndex = String(u.sortIndex);
        if (u.position) {
          const pos = Object.assign({}, u.position);
          if (ann.annotationType === "note") { delete pos.fontSize; delete pos.rotation; const r = pos.rects[0]; pos.rects = [[r[0], r[3] - 22, r[0] + 22, r[3]]]; }
          ann.annotationPosition = JSON.stringify(pos);
        }
        await ann.save();
        updatedKeys.push(ann.key);
      }
      for (const a of old) await a.erase();
    });
    if (newNote) { noteCreated = true; noteKeys.push(newNote.key); }
    if (rewriteNote) noteKeys.push(rewriteNote.key);
    // the reader's eye button turns on with the first write of a user who never used it (ScholiumToggle.showOnce)
    if (createdKeys.length) ScholiumToggle.showOnce().catch(e => this.log("annotations not shown: " + e));
    // (3) the earlier notes go to the trash; the new items are written whatever happens here
    let removeError;
    if (trash.length) {
      try { await Zotero.Items.trashTx(trash); notesTrashed = trash.length; }
      catch (e) { removeError = String((e && e.message) || e); }
    }
    return Object.assign({ ok: true, removed: old.length, kept, noteCreated, noteSkipped, notesTrashed, created, createdKeys, noteKeys, removeError },
                         data.rewrite ? { updatedKeys, keptKeys: keep } : {}, rewriteNote ? { noteUpdated: true } : {});
  },

  register() {
    const self = this;
    class Ping {
      supportedMethods = ["GET", "POST"];
      supportedDataTypes = ["application/json"];
      // init must declare exactly one parameter: Zotero's server treats an init of arity 0 or 2 as the
      // legacy callback style, and the request would never resolve.
      init = async (options) => self.reply(200, { ok: true, name: "scholium", version: self.version, dataDir: Zotero.DataDirectory.dir });
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
    this.endpoints = { "/scholium/ping": Ping, "/scholium/list": List, "/scholium/apply": Apply,
                       "/scholium-bridge/ping": Ping, "/scholium-bridge/list": List, "/scholium-bridge/apply": Apply };
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
