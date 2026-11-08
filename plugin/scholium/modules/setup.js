// ScholiumRunner, continued: the preferences and what they decide, the agent, model and effort chosen, finding Claude
// Code, Codex, uv and Python, installing the skill, the setup check, and starting a process

Object.assign(ScholiumRunner, {
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
  SAID_MS: 3000,  // a word under the message box shows this long

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
    if (job && (this.keyOf(job.att) !== run.key || (job.kind || "chat") !== (run.source.kind || "chat"))) return false;
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

  // a number of tokens, in thousands from 1000 (62k), grouped as the section's language groups digits (1,000k; 1.000k in
  // German)
  kTokens(n) {
    const v = Number(n) || 0;
    if (v < 1000) return String(v);
    const k = Math.round(v / 1000);
    try { return k.toLocaleString(this.lang()) + "k"; } catch (e) { return k.toLocaleString("en-US") + "k"; }
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

  // the agent's folder of the user's own skills: Claude Code's (CLAUDE_CONFIG_DIR when set), Codex's (CODEX_HOME when set)
  skillsDir(agent) {
    const home = this.home();
    const base = agent === "codex" ? this.env("CODEX_HOME") || (home ? PathUtils.join(home, ".codex") : "")
      : this.env("CLAUDE_CONFIG_DIR") || (home ? PathUtils.join(home, ".claude") : "");
    return base ? PathUtils.join(base, "skills") : "";
  },

  // the skill the plugin carries, copied into the agent's skills folder byte for byte; a zotero-scholium skill already
  // there is left as it is. A text key: skillInstalled, skillThere, or what kept it from being installed
  async installSkill(agent) {
    const dir = this.skillsDir(agent);
    if (!dir) return "skillNoHome";
    const dest = PathUtils.join(dir, "zotero-scholium");
    if (await this.exists(PathUtils.join(dest, "SKILL.md"))) return "skillThere";
    const files = [];
    try {
      for (const rel of this.SKILL_FILES) {
        const xhr = await Zotero.HTTP.request("GET", this.chrome + "skill/zotero-scholium/" + rel, { responseType: "arraybuffer" });
        files.push([rel, new Uint8Array(xhr.response)]);
      }
    } catch (e) {
      this.log("skill not carried: " + e);
      return "skillNotCarried";
    }
    for (const [rel, bytes] of files) {
      const path = PathUtils.join(dest, ...rel.split("/"));
      await IOUtils.makeDirectory(PathUtils.parent(path), { createAncestors: true, ignoreExisting: true });
      await IOUtils.write(path, bytes);
    }
    return "skillInstalled";
  },

  // Install the skill and retry: the run again once the skill is there; else what kept it, under the box
  async installAndRetry(view, agent, retry) {
    let outcome;
    try { outcome = await this.installSkill(agent); }
    catch (e) {
      this.log("skill not installed: " + e);
      if (view.pane) this.sayUnderBox(view.pane, this.text("skillFailed", String((e && e.message) || e)));
      return;
    }
    if (outcome === "skillInstalled" || outcome === "skillThere") return retry();
    if (view.pane) this.sayUnderBox(view.pane, this.text(outcome));
  },

  // claude.exe directly (the npm shim is a .cmd file, which cannot be started without a shell): the one set on the
  // settings page, else the one found
  async findClaude() {
    const configured = this.getPref("claudePath");
    if (configured) return (await this.exists(configured)) ? configured : null;
    return this.autoClaude();
  },

  // claude.exe where it is usually installed, or on the agent's PATH (agentPath)
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
    return this.onPath([exe]);
  },

  // the codex executable: the one set on the settings page, else the one found
  async findCodex() {
    const configured = this.getPref("codexPath");
    if (configured) return (await this.exists(configured)) ? configured : null;
    return this.autoCodex();
  },

  // the newest codex executable among the usual places: the Codex app keeps its own copy in a folder
  // that changes with each update, npm's package carries a native one (its shim is a .cmd file), and
  // Cargo, Homebrew and the agent's PATH (agentPath) may hold others. An older Codex may not read a newer one's config.toml.
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
    const onPath = await this.onPath([exe]);
    if (onPath) candidates.push(onPath);
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

  // the setup check of the settings page: a line to onLine as each check ends, { id, state: "ok" | "bad" | "unknown",
  // label, text, action? }, where an action ({ kind: "localApi" } or { kind: "skill", agent }, with its button's label)
  // goes to setupFix. Returns the lines
  async setupCheck(onLine) {
    const lines = [];
    const say = (id, state, text, action = null) => {
      const line = { id, state, label: this.text("checkLabel", id), text };
      if (action) line.action = Object.assign({ label: this.text(action.kind === "localApi" ? "checkTurnOn" : "checkInstall") }, action);
      lines.push(line);
      try { if (onLine) onLine(line); } catch (e) { this.log("setup check line not shown: " + e); }
    };
    if (Zotero.Prefs.get("httpServer.localAPI.enabled")) say("localApi", "ok", this.text("checkApiOn"));
    else say("localApi", "bad", this.text("checkApiOff"), { kind: "localApi" });
    let uv = false;
    for (const check of [() => this.checkClaude(say), () => this.checkCodex(say), async () => { uv = await this.checkUv(say); },
                         () => this.checkPython(say, uv)]) {
      try { await check(); } catch (e) { this.log("setup check failed: " + e); }
    }
    return lines;
  },

  // a setup check's lines as plain text, for a bug report: Scholium's and Zotero's versions and the system, then a line
  // per check with its mark
  async setupReport(lines) {
    let os = "";
    try { if (typeof Zotero.getOSVersion === "function") os = String(await Zotero.getOSVersion()).trim(); } catch (e) {}
    if (!os) { try { os = Services.appinfo.OS + " " + Services.sysinfo.getProperty("version"); } catch (e) { os = Services.appinfo.OS; } }
    const marks = { ok: "✓", bad: "✗", unknown: "–" };
    return [`Scholium ${this.version} · Zotero ${Zotero.version} · ${os}`]
      .concat((lines || []).map(l => `${marks[l.state] || marks.unknown} ${l.label}: ${l.text}`)).join("\n");
  },

  // the setup check's text (setupReport) copied to the clipboard; the text
  async copySetup(lines) {
    const text = await this.setupReport(lines);
    Zotero.Utilities.Internal.copyTextToClipboard(text);
    return text;
  },

  // a setup check's action: Zotero's local API turned on, or the skill the plugin carries installed (installSkill); the
  // words of what kept it from being done, or null once it is done
  async setupFix(action) {
    if (action && action.kind === "localApi") {
      Zotero.Prefs.set("httpServer.localAPI.enabled", true);
      return null;
    }
    if (action && action.kind === "skill") {
      let outcome;
      try { outcome = await this.installSkill(action.agent === "codex" ? "codex" : "claude"); }
      catch (e) {
        this.log("skill not installed: " + e);
        return this.text("skillFailed", String((e && e.message) || e));
      }
      return outcome === "skillInstalled" || outcome === "skillThere" ? null : this.text(outcome);
    }
    return null;
  },

  // a short command's standard output; null when it did not start, failed, or gave no answer in CHECK_MS, after which it is
  // killed
  async checkOutput(command, args) {
    let proc;
    try { proc = await this.subprocess().call(Object.assign({ command, arguments: args, workdir: Zotero.DataDirectory.dir }, await this.agentEnv())); }
    catch (e) {
      this.log("setup check: not started: " + e);
      return null;
    }
    try {
      const { out, late } = await this.readOutput(proc, this.CHECK_MS);
      return late ? null : out;
    } catch (e) {
      this.log("setup check: no answer: " + e);
      return null;
    }
  },

  // a process's standard output { out, late }, read until it ends and the process exits, until done(out) holds, or until
  // ms pass (late): the process is then killed and the reading ends, since a child it started may keep its output open.
  // After done(out), a process that has not exited by then is still killed at that time
  async readOutput(proc, ms, done = null) {
    let late = false, ended = false, timer = null, out = "";
    const deadline = new Promise(resolve => { timer = setTimeout(() => { late = true; try { proc.kill(); } catch (e) {} resolve(); }, ms); });
    const read = (async () => {
      try { await proc.stdin.close(); } catch (e) {}
      for (;;) {
        const s = await proc.stdout.readString();
        if (late) return;
        if (!s) break;
        out += s;
        if (done && done(out)) return;
      }
      await proc.wait();
      ended = true;
    })();
    try { await Promise.race([read, deadline]); }
    finally {
      if (ended || late) clearTimeout(timer);
      else proc.wait().then(() => clearTimeout(timer), () => {});
    }
    return { out, late };
  },

  // Claude Code: the program a run uses and whether it is signed in (only loggedIn of `claude auth status` is read), then
  // its skill
  async checkClaude(say) {
    const claude = await this.findClaude();
    if (!claude) return say("claude", "bad", this.text(this.getPref("claudePath") ? "checkProgramGone" : "checkNoProgram", "claude"));
    const out = await this.checkOutput(claude, ["auth", "status"]);
    let signedIn = null;
    try {
      const v = JSON.parse(/\{[\s\S]*\}/.exec(String(out || ""))[0]).loggedIn;
      if (typeof v === "boolean") signedIn = v;
    } catch (e) {}
    if (signedIn === null) say("claude", "unknown", this.text("checkSignInUnknown", this.text("checkAuthSilent")));
    else if (signedIn) say("claude", "ok", this.text("checkSignedIn"));
    else say("claude", "bad", this.text("checkSignedOut", "claude"));
    const dir = await this.claudeSkillDir();
    if (dir) say("claudeSkill", "ok", this.text("checkSkillAt", dir));
    else say("claudeSkill", "bad", this.text("checkSkillMissing"), { kind: "skill", agent: "claude" });
  },

  // the folder of the zotero-scholium skill Claude Code finds: in its skills folder, in the data directory's project skills
  // (a run's working directory), or in a plugin of its cache (plugins/cache/<marketplace>/<plugin>/<version>/skills); null
  // when there is none
  async claudeSkillDir() {
    const user = this.skillsDir("claude");
    const dirs = (user ? [PathUtils.join(user, "zotero-scholium")] : [])
      .concat([PathUtils.join(Zotero.DataDirectory.dir, ".claude", "skills", "zotero-scholium")]);
    for (const dir of dirs) if (await this.exists(PathUtils.join(dir, "SKILL.md"))) return dir;
    if (!user) return null;
    let level = [PathUtils.join(PathUtils.parent(user), "plugins", "cache")];
    for (let depth = 0; depth < 3 && level.length; depth++) {
      const next = [];
      for (const dir of level) { try { next.push(...await IOUtils.getChildren(dir)); } catch (e) {} }
      level = next;
    }
    for (const dir of level) {
      const skill = PathUtils.join(dir, "skills", "zotero-scholium");
      if (await this.exists(PathUtils.join(skill, "SKILL.md"))) return skill;
    }
    return null;
  },

  // Codex: the program a run uses, through `codex app-server` started as a run starts it: whether it is signed in
  // (account/read, by codexNoAccount) and whether it finds the skill (codexSkill); each answer is waited for CHECK_MS, and
  // the server is closed
  async checkCodex(say) {
    const codex = await this.findCodex();
    if (!codex) return say("codex", "bad", this.text(this.getPref("codexPath") ? "checkProgramGone" : "checkNoProgram", "codex"));
    const late = this.text("checkNoAnswer", Math.round(this.CHECK_MS / 1000));
    const first = e => String((e && e.message) || e).trim().split("\n")[0];
    const cwd = this.codexRoots()[0];
    let rpc = null, said = false;
    try {
      await IOUtils.makeDirectory(cwd, { createAncestors: true, ignoreExisting: true });
      rpc = await this.codexServer(codex, cwd);
      rpc.done.catch(() => {});
      await this.within(this.codexHello(rpc), this.CHECK_MS, late);
      let account = null, why = "";
      try { account = await this.within(rpc.request("account/read", {}), this.CHECK_MS, late); }
      catch (e) {
        if (!e || !e.refused) throw e;
        why = first(e);
      }
      said = true;
      if (why) say("codex", "unknown", this.text("checkSignInUnknown", why));
      else if (this.codexNoAccount(account)) say("codex", "bad", this.text("checkSignedOut", "codex"));
      else say("codex", "ok", this.text("checkSignedIn"));
      const skill = await this.within(this.codexSkill(rpc, cwd), this.CHECK_MS, late);
      if (skill) say("codexSkill", "ok", this.text("checkSkillAt", PathUtils.parent(skill.path)));
      else say("codexSkill", "bad", this.text("checkSkillMissing"), { kind: "skill", agent: "codex" });
    } catch (e) {
      this.log("setup check of Codex: " + e);
      // a server that ended: the first line it wrote to stderr (a config.toml error, say), else the error's first line
      const wrote = rpc && !(e && e.refused) && first(e) !== late ? rpc.stderr.trim().split("\n")[0].trim() : "";
      if (said) say("codexSkill", "bad", first(e));
      else say("codex", "bad", this.text("checkCodexFailed", wrote ? this.text("codexExited", wrote) : first(e)));
    } finally {
      if (rpc) rpc.close();
    }
  },

  // the PATH of the user's login shell on macOS and Linux, read once a session: Zotero started from the Dock or a desktop
  // menu has a short PATH, without the folders of Homebrew, nvm or uv. "" on Windows, or when the shell fails or does not
  // print it in LOGIN_PATH_MS (it is then killed, and its output, which a child it started may keep open, is left)
  loginPath() {
    if (Services.appinfo.OS === "WINNT") return Promise.resolve("");
    if (!this.loginPathRead) this.loginPathRead = this.readLoginPath().catch(e => { this.log("login PATH not read: " + e); return ""; });
    return this.loginPathRead;
  },

  // $SHELL (else /bin/zsh) started as an interactive login shell that prints its PATH between two marks, so that what its
  // startup files print is left out; a mark starts and ends with @, which no variable name holds
  async readLoginPath() {
    const named = this.env("SHELL");
    const shell = named.startsWith("/") && (await this.exists(named)) ? named : (await this.exists("/bin/zsh")) ? "/bin/zsh" : "";
    if (!shell) return "";
    const mark = "@SCHOLIUM_PATH@";
    const proc = await this.subprocess().call({ command: shell, arguments: ["-ilc", `printf '%s' "${mark}$PATH${mark}"`] });
    const { out } = await this.readOutput(proc, this.LOGIN_PATH_MS, o => o.split(mark).length >= 3);
    const parts = out.split(mark);
    const path = parts.length >= 3 ? parts[1].trim() : "";
    return path.split(":").some(d => d.startsWith("/")) ? path : "";
  },

  // the PATH an agent's process is given, and on which the plugin looks for programs (onPath): on macOS and Linux the
  // login shell's (loginPath) before Zotero's, each folder once; then uv's folders (~/.local/bin, and ~/.cargo/bin outside
  // Windows) when they are there and missing. Zotero's own PATH when nothing is added
  async agentPath() {
    const win = Services.appinfo.OS === "WINNT";
    const sep = win ? ";" : ":";
    const own = this.env("PATH");
    const login = await this.loginPath();
    const key = d => (win ? d.replace(/^"(.*)"$/, "$1").replace(/(.)[\\/]+$/, "$1").toLowerCase() : d.replace(/(.)\/+$/, "$1"));
    const dirs = [], seen = new Set();
    for (const d of (login ? login.split(sep) : []).concat(own.split(sep))) {
      if (d && !seen.has(key(d))) { seen.add(key(d)); dirs.push(d); }
    }
    const home = this.home();
    const uvDirs = !home ? [] : [PathUtils.join(home, ".local", "bin")].concat(win ? [] : [PathUtils.join(home, ".cargo", "bin")]);
    let added = false;
    for (const d of uvDirs) {
      if (!seen.has(key(d)) && (await this.exists(d))) { seen.add(key(d)); dirs.push(d); added = true; }
    }
    return login || added ? dirs.join(sep) : own;
  },

  // the options of Subprocess.call for an agent's process, or a program of the setup check: Zotero's environment with
  // Python's output in UTF-8, the port of this Zotero's local server for the skill's script (zoteroPort), and the agent's
  // PATH (agentPath) when it is not Zotero's own. Codex's: uv's cache and the Pythons uv installs in
  // <data dir>/tmp/scholium/uv, which its sandbox may write, unless the user set where they go
  async agentEnv(codex = false) {
    const environment = { PYTHONIOENCODING: "utf-8", SCHOLIUM_ZOTERO_PORT: String(this.zoteroPort()) };
    const path = await this.agentPath();
    if (path !== this.env("PATH")) environment[this.pathName()] = path;
    if (codex) {
      const uv = PathUtils.join(this.codexRoots()[0], "uv");
      if (!this.env("UV_CACHE_DIR")) environment.UV_CACHE_DIR = PathUtils.join(uv, "cache");
      if (!this.env("UV_PYTHON_INSTALL_DIR")) environment.UV_PYTHON_INSTALL_DIR = PathUtils.join(uv, "python");
    }
    return { environment, environmentAppend: true };
  },

  // the port of this Zotero's local server (httpServer.port), 23119 unless the user changed it
  zoteroPort() {
    let port = 0;
    try { port = Number(Zotero.Prefs.get("httpServer.port")); } catch (e) {}
    return Number.isInteger(port) && port >= 1 && port <= 65535 ? port : 23119;
  },

  // the name of the PATH variable: on Windows the one the environment has (often Path), since a second spelling would be a
  // second variable
  pathName() {
    if (Services.appinfo.OS !== "WINNT") return "PATH";
    try { return Object.keys(this.subprocess().getEnvironment()).find(k => k.toUpperCase() === "PATH") || "PATH"; }
    catch (e) { return "PATH"; }
  },

  // the first of the names in a folder of the agent's PATH (agentPath), each name looked for in every folder before the
  // next; a folder that skip matches is passed over. null when there is none
  async onPath(names, skip = null) {
    const win = Services.appinfo.OS === "WINNT";
    const dirs = (await this.agentPath()).split(win ? ";" : ":").map(d => d.trim().replace(/^"(.*)"$/, "$1"))
      .filter(d => d && !(skip && skip.test(d)));
    for (const name of names) {
      for (const dir of dirs) {
        let path;
        try { path = PathUtils.join(dir, name); } catch (e) { continue; }   // a relative folder
        if (await this.exists(path)) return path;
      }
    }
    return null;
  },

  // Python on the agent's PATH: python.exe on Windows, else python3 or python; a WindowsApps folder (the Microsoft Store's
  // alias) is passed over. null when there is none
  pathPython() {
    return this.onPath(Services.appinfo.OS === "WINNT" ? ["python.exe"] : ["python3", "python"], /[\\/]WindowsApps[\\/]?$/i);
  },

  // how the skill's script runs on this computer, for the prompts: "uv run" when uv is on the agent's PATH, else the
  // Python found there ("python" when there is none); files looked for, no process started
  async scriptCommand() {
    if (await this.onPath([Services.appinfo.OS === "WINNT" ? "uv.exe" : "uv"])) return "uv run";
    const python = await this.pathPython();
    return python ? python.split(/[\\/]/).pop().replace(/\.exe$/i, "") : "python";
  },

  // uv on the agent's PATH and its version: the skill's script then runs as `uv run`, which provides Python and PyMuPDF.
  // Whether it answered
  async checkUv(say) {
    const uv = await this.onPath([Services.appinfo.OS === "WINNT" ? "uv.exe" : "uv"]);
    if (!uv) { say("uv", "unknown", this.text("checkNoUv")); return false; }
    const v = /\d+\.\d+\.\d+\S*/.exec(String((await this.checkOutput(uv, ["--version"])) || ""));
    if (!v) { say("uv", "unknown", this.text("checkUvSilent", uv)); return false; }
    say("uv", "ok", this.text("checkUv", v[0], uv));
    return true;
  },

  // that Python's version, and for 3.9 or later its PyMuPDF (imported as fitz before PyMuPDF 1.24); with uv (checkUv) a
  // missing or old one is no fault
  async checkPython(say, uv = false) {
    const python = await this.pathPython();
    if (!python) return say("python", uv ? "unknown" : "bad", this.text(uv ? "checkNoPythonUv" : "checkNoPython"));
    const out = await this.checkOutput(python, ["-c", "import sys; print(sys.version.split()[0]); import importlib.util as u; "
      + "m = __import__('pymupdf' if u.find_spec('pymupdf') else 'fitz'); print(m.VersionBind)"]);
    const [version, pymupdf] = String(out || "").split(/\r?\n/).map(s => s.trim());
    const v = /^(\d+)\.(\d+)/.exec(version || "");
    if (!v) return say("python", "unknown", this.text("checkPythonSilent", python));
    if (Number(v[1]) < 3 || (Number(v[1]) === 3 && Number(v[2]) < 9)) {
      return say("python", uv ? "unknown" : "bad", this.text(uv ? "checkPythonOldUv" : "checkPythonOld", version, python));
    }
    say("python", "ok", this.text("checkPython", version, python));
    if (/^\d+\.\d+/.test(pymupdf || "")) say("pymupdf", "ok", this.text("checkPymupdf", pymupdf));
    else say("pymupdf", uv ? "unknown" : "bad", this.text(uv ? "checkPymupdfUv" : "checkPymupdfMissing"));
  },

  // "codex-cli 0.160.0" -> [0, 160, 0, ""]; null when it does not start or answer
  async codexVersion(path) {
    try {
      const proc = await this.subprocess().call(Object.assign({ command: path, arguments: ["--version"], stderr: "stdout" }, await this.agentEnv()));
      const { out } = await this.readOutput(proc, 15000);
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
});
