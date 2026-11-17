/* Scholium: the plugin's folder in the data directory, <data dir>/scholium: the profile, each paper's records
 * (papers/<key>), each conversation's working directory (papers/<key>/conversations/<conversation>) and uv's cache
 * (cache/uv).
 */
Object.assign(ScholiumRunner, {
  root() { return PathUtils.join(Zotero.DataDirectory.dir, "scholium"); },
  outDir(key) { return PathUtils.join(this.root(), "papers", key); },
  uvDir() { return PathUtils.join(this.root(), "cache", "uv"); },

  // where a conversation's agent runs, so that its sessions are the plugin's own project, as llm-for-zotero runs each
  // conversation in a folder of its own
  workDir(key, conv) { return PathUtils.join(this.outDir(key), "conversations", conv); },

  // whether a path is the folder or inside it, whatever its slashes (and, on Windows, its case)
  inside(folder, path) {
    const win = Services.appinfo.OS === "WINNT";
    const norm = p => { const s = String(p || "").replace(/\\/g, "/").replace(/\/+$/, ""); return win ? s.toLowerCase() : s; };
    const f = norm(folder), p = norm(path);
    return !!f && (p === f || p.startsWith(f + "/"));
  },

  // the folders of an earlier version and where their contents go: the papers' records and uv's cache of
  // <data dir>/tmp/scholium, the profile of <data dir>/zotero-scholium
  oldFolders() {
    const data = Zotero.DataDirectory.dir;
    return [[PathUtils.join(data, "tmp", "scholium", "uv"), this.uvDir()],
            [PathUtils.join(data, "tmp", "scholium"), PathUtils.join(this.root(), "papers")],
            [PathUtils.join(data, "zotero-scholium"), this.root()]];
  },

  // where a path of an earlier version's folders is now; any other path as it is
  movedPath(path) {
    for (const [from, to] of this.oldFolders()) if (this.inside(from, path)) return to + String(path).slice(from.length);
    return path;
  },

  async children(dir) {
    try { return await IOUtils.getChildren(dir); } catch (e) { return []; }
  },

  async isFolder(path) {
    try { return (await IOUtils.stat(path)).type === "directory"; } catch (e) { return false; }
  },

  async removeIfEmpty(dir) {
    if (!(await this.isFolder(dir)) || (await this.children(dir)).length) return;
    try { await IOUtils.remove(dir, { ignoreAbsent: true }); } catch (e) { this.log("folder not removed: " + dir + ": " + e); }
  },

  // a file or folder moved where nothing has its name, else a folder merged into the one there: what the new place
  // already has stays, and so does the old copy of it; what cannot be moved (held open) goes on the list left
  async mergeMove(from, to, left) {
    if (!(await this.exists(to))) {
      try {
        await IOUtils.makeDirectory(PathUtils.parent(to), { createAncestors: true, ignoreExisting: true });
        await IOUtils.move(from, to);
      } catch (e) {
        left.push(from);
        this.log("not moved: " + from + ": " + e);
      }
      return;
    }
    if (!(await this.isFolder(from)) || !(await this.isFolder(to))) return;
    for (const kid of await this.children(from)) await this.mergeMove(kid, PathUtils.join(to, PathUtils.filename(kid)), left);
    await this.removeIfEmpty(from);
  },

  // an earlier version's folders moved into <data dir>/scholium: the profile's folder whole, of <data dir>/tmp/scholium
  // uv's cache and each paper's folder; the folders left empty go. The paths not moved, which a later start tries again
  async migrateFolders() {
    const data = Zotero.DataDirectory.dir, left = [];
    try { await IOUtils.makeDirectory(PathUtils.join(this.root(), "papers"), { createAncestors: true, ignoreExisting: true }); }
    catch (e) { this.log("plugin folder not made: " + e); }
    const profile = PathUtils.join(data, "zotero-scholium");
    for (const kid of await this.children(profile)) await this.mergeMove(kid, PathUtils.join(this.root(), PathUtils.filename(kid)), left);
    await this.removeIfEmpty(profile);
    const tmp = PathUtils.join(data, "tmp", "scholium");
    for (const kid of await this.children(tmp)) {
      const name = PathUtils.filename(kid);
      if (name === "uv") await this.mergeMove(kid, this.uvDir(), left);
      else if (/^[A-Z0-9]+(?:_g\d+)?$/.test(name) && (await this.isFolder(kid))) await this.mergeMove(kid, this.outDir(name), left);
    }
    await this.removeIfEmpty(tmp);
    this.migrateLeft = left;
    return left;
  },

  // the logs still to be written (ScholiumPendingLogs) and the notes that name them, at their paths in the new folder
  remapPendingLogs() {
    for (const [path, pending] of [...this.pendingLogs]) {
      const moved = this.movedPath(path);
      if (moved === path) continue;
      this.pendingLogs.delete(path);
      this.pendingLogs.set(moved, pending);
    }
    for (const note of this.notes.values()) if (note && note.pendingLog) note.pendingLog = this.movedPath(note.pendingLog);
    if (this.parsedLogs) this.parsedLogs.clear();
  },

  // the folders moved when the plugin starts, before any log is read or run started; what could not be moved is tried
  // once more ten seconds later (a copy of the plugin an update replaces may still hold it)
  startFolders() {
    this.migrateLeft = [];
    const once = () => this.migrateFolders().then(left => { this.remapPendingLogs(); return left; });
    this.migrating = once().then(left => {
      if (!left.length || this.stopped) return;
      this.migrateRetry = setTimeout(() => {
        this.migrateRetry = null;
        this.migrating = once().then(() => {
          for (const pane of this.panes.values()) this.showConversation(pane).catch(e => this.log("section not shown: " + e));
        }).catch(e => this.log("folders not moved: " + e));
      }, 10000);
    }).catch(e => this.log("folders not moved: " + e));
    return this.migrating;
  },

  // waits for the folders to be moved, when they are being moved
  async settled() {
    if (this.migrating) await this.migrating;
  },
});
