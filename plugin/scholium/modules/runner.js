// ScholiumRunner: its state and constants, the log, the languages and the section's texts in English and
// Simplified Chinese; the modules after this one add its other methods

/* One-click annotation (Claude Code or Codex): the Scholium section in the item pane (library and
 * reader side pane) starts the user's own, unmodified agent CLI in the background, signed in with the
 * user's own account; no credentials are read, nor the agent's configuration (of Codex's setup only its MCP servers'
 * names, as Codex lists them, are kept). It runs the zotero-scholium skill on one paper at a
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
 * continues its conversation there. Papers of group libraries are annotated when the user can edit the group's library,
 * after the user agreed once for each group; their runs and files are kept apart (keyOf). Every event but the
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
  pendingQuotes: new Map(), // attachment key -> { quote: { text, page }, at }: a passage asked about before the section was drawn
  QUOTE_MS: 30000,          // how long such a passage waits for its section
  pendingPapers: new Map(), // attachment key -> { papers, at }: the other papers of a question about several (askPapers), until
                            // the first paper's section takes them, within QUOTE_MS
  MAX_PAPERS: 8,            // the most papers a question asks about together
  itemMenus: new Map(),     // main window -> { item, popup, showing }: Ask Scholium (N papers) in its items list's context menu
  // the skill's files as the plugin carries them in content/skill/zotero-scholium (added when the package is built);
  // SKILL.md is written last, so that a copy cut short is not taken for a skill
  SKILL_FILES: ["agents/openai.yaml", "examples/config.template.json", "examples/reading_note.template.html", "references/backends.md",
                "references/batch.md", "references/configuration.md", "references/profile.md", "references/style-zh.md",
                "references/zotero-annotations.md", "scripts/scholium.py", "SKILL.md"],
  current: null,            // { key, proc, cancelled }
  draining: false,
  job: null,                // { title, key, libraryID, started, step } of the running paper
  last: null,               // { ok, title, key, libraryID, summary, log, at } of the latest finished paper
  notes: new Map(),         // <attachment key>/<kind> -> { text, error, at, title, conv }: the latest outcome of each kind
  indexes: new Map(),       // attachment key -> { chat, current, titles: { id: title }, annotation }: its conversations
  parsedLogs: new Map(),    // log path -> { at, size, log }: a log read before, while it is unchanged; `log` is the reading
                            // (parseLog), done or under way
  deleting: new Map(),      // log path -> { key, id, title, at, wasCurrent, timer }: a conversation deleted a moment ago,
                            // until it can no longer be brought back
  unsent: new Map(),        // "<library>/<item key>/<tab>/<agent>/<conversation>" -> the words in a section's message box, not yet
                            // sent; the agent only for an annotation session
  katexLib: undefined,      // KaTeX once loaded (null when it cannot be), for the formulas in messages
  i18n: {},                 // language -> its texts (content/i18n/<language>.js) once loaded, null when they cannot be
  mathCache: new Map(),     // "D"/"I" + TeX -> its MathML, or null when KaTeX cannot read it
  paused: null,             // { <agent>: { agent, until, known, throttled, timer } } while an agent's usage limit or its
                            // service's limit holds that agent's runs; null while none does
  restoreTimer: null,
  RETRY_MS: 10 * 60000,     // the wait when the agent names no reset time
  NET_RETRY_MS: 30000,      // the wait before the second try of a run whose connection failed
  pref: "extensions.scholium.",
  STEPS: ["extract", "reading", "writing", "applying"],   // loading the skill and a dry run, when an agent does one, are no steps
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
  citations: new Map(),     // attachment key -> { at, size, map } the paper's numbered sentences, as sentences.json has them;
                            // the 20 papers shown last
  codexMcp: null,           // the names of the user's MCP servers to switch off in a Codex thread (codexServerNames)
  codexListed: false,       // whether Codex listed them in this session, or the list after a run was tried
  codexRefresh: null,       // the Codex server listing them after a run
  codexRefused: new Set(),  // the names a thread refused as servers of config.toml, in this session
  CODEX_LIST_MS: 10000,     // the longest a run waits for the servers' list, when Codex never listed them
  CHECK_MS: 10000,          // the longest the setup check waits for a program's answer
  MAX_OUTPUT_TOKENS: 32000, // one turn's output, thinking included, in an annotation's Claude Code runs (runClaude)
  PRE_STATUS_MS: 60000,     // the longest the pre-run's status is waited for (preRun)
  PRE_EXTRACT_MS: 180000,   // and its extract
  LOGIN_PATH_MS: 5000,      // the longest the login shell is waited for when its PATH is read (loginPath)
  loginPathRead: null,      // the promise of the login shell's PATH, read once a session; "" when there is none
  cites: null,              // { key, map } the sentences of the paper whose transcript is being drawn
  settingsApi: null,          // { found(agent), setupCheck(onLine), fix(action), copy(lines) } on Zotero.Scholium, for the settings page
  panes: new Map(),         // item pane section body -> { doc, keys, list, state, buttons, the conversation shown, seen }
  AGENTS: ["claude", "codex"],
  models: {},               // agent -> [{ value, label, title, efforts }] as the agent reports them; none until it answered
  modelsAsked: {},          // agent -> when it was last asked; a failed request is repeated at most once a minute
  modelsLoading: {},
  DEFAULT_MODEL: "opus",    // Claude Code's alias of the latest Opus, until another model is chosen; Codex starts at its own default
  EFFORTS: ["low", "medium", "high", "xhigh", "max"],   // when the model's levels are unknown
  CODEX_EFFORTS: ["low", "medium", "high", "xhigh"],
  DEFAULT_EFFORT: "medium", // until another level is chosen
  PANE_HEAD: 34,            // a section's header and its gap below the body, when they cannot be measured
  MIN_PANE: 360,            // the least height of a section
  chrome: "chrome://scholium/content/",   // the content folder; startup() puts the version into it
  version: "",              // the plugin's, which it gives Codex as its client version

  log(msg) { Zotero.debug("[scholium] " + msg); },

  // the prompts' language: Chinese in both Chinese locales, else English
  zh() { return String(Zotero.locale || "").toLowerCase().startsWith("zh"); },

  // the language of the section's texts, from Zotero's: a locale/ folder's name, en-US for one the plugin does not have.
  // Portuguese: pt-BR for Brazil's and plain pt, pt-PT for the others
  lang() {
    const locale = String(Zotero.locale || "").toLowerCase(), first = locale.split(/[-_]/)[0];
    if (first === "zh") return /^zh[-_](tw|hk|mo|hant)\b/.test(locale) ? "zh-TW" : "zh-CN";
    if (first === "pt") return locale === "pt" || /^pt[-_]br\b/.test(locale) ? "pt-BR" : "pt-PT";
    return { ja: "ja-JP", ko: "ko-KR", de: "de", fr: "fr-FR", es: "es-ES", ru: "ru-RU" }[first] || "en-US";
  },

  // the line that gives an agent the user's language where the prompt's own is not it (Traditional Chinese has the
  // Chinese prompt, the others the English one)
  languageLines() {
    const lang = this.lang();
    if (lang === "zh-TW") return ["用户使用繁体中文：高亮的译文、页边批注、阅读笔记和回答都用繁体中文写。"];
    const name = { "ja-JP": "Japanese", "ko-KR": "Korean", de: "German", "fr-FR": "French", "es-ES": "Spanish", "ru-RU": "Russian",
                   "pt-BR": "Brazilian Portuguese", "pt-PT": "European Portuguese" }[lang];
    return name ? [`The user's language is ${name}: write the highlight translations, margin notes, the reading note and answers in ${name}.`] : [];
  },

  // uv's installer for this system, as uv's documentation gives it
  uvInstall() {
    return Services.appinfo.OS === "WINNT" ? 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
      : "curl -LsSf https://astral.sh/uv/install.sh | sh";
  },

  // a text of the section in Zotero's language: from the language's table (a key it lacks in English), else from the
  // English or Simplified Chinese of baseTexts
  text(key, ...args) {
    const lang = this.lang();
    const own = lang === "en-US" || lang === "zh-CN" ? null : this.localTexts(lang);
    const t = own && key in own ? own[key] : this.baseTexts(lang === "zh-CN")[key];
    return typeof t === "function" ? t(...args) : t;
  },

  // a language's table, content/i18n/<language>.js, loaded once: the file sets `texts`, a function that is given the
  // helpers below and gives the keys of baseTexts, each a string or a function of the same arguments; null when it
  // cannot be loaded
  localTexts(lang) {
    if (!(lang in this.i18n)) {
      this.i18n[lang] = null;
      try {
        const scope = {};
        Services.scriptloader.loadSubScript(`${this.chrome}i18n/${lang}.js`, scope);
        const runner = this;
        if (typeof scope.texts === "function") {
          this.i18n[lang] = scope.texts({
            name: (agent, short = false) => runner.agentName(agent, short),   // Claude Code, Claude or Codex
            text: (key, ...args) => runner.text(key, ...args),               // another text of the table
            get os() { return Services.appinfo.OS; },                         // WINNT, Darwin or Linux
            get uvInstall() { return runner.uvInstall(); },                   // uv's install command for the system
          });
        }
      } catch (e) { this.log(`texts of ${lang} not loaded: ` + e); }
    }
    return this.i18n[lang];
  },

  // the section's texts in English, or in Simplified Chinese (zh); each other language has a table of the same keys in
  // content/i18n (localTexts)
  baseTexts(zh) {
    const word = (k, one, many) => (k === 1 ? one : many);
    const plural = (k, one, many) => `${k} ${word(k, one, many)}`;
    const os = Services.appinfo.OS;
    const uvInstall = this.uvInstall();
    // the sentence a redo's or a deletion's question has for a paper in a group library
    const groupShared = zh ? "这是群组文库：群组的所有成员都受影响。" : "This is a group library: it applies to every member.";
    return {
      headline: zh ? "Scholium 批注" : "Scholium annotation",
      noPdf: zh ? "这篇论文没有 PDF 附件：在 Zotero 里添加论文的 PDF 后再试。" : "This paper has no PDF attachment: add the paper's PDF in Zotero, then try again.",
      noFile: zh ? "这篇论文的 PDF 文件不在这台电脑上（还没下载，或已被移走）：在 Zotero 里打开它以下载，或重新链接文件后再试。"
                 : "The paper's PDF file is not on this computer (not downloaded yet, or moved): open it in Zotero to download it, or relink the file, then try again.",
      groupReadOnly: zh ? "你在这个群组里没有编辑权限，无法写入批注。" : "You cannot edit this group's library, so annotations cannot be written.",
      groupFirstTitle: zh ? "群组文库" : "Group library",
      groupFirst: zh ? "批注会写进群组文库，群组的所有成员都能看到。继续吗？"
                     : "The annotations go into the group's library, where every member sees them. Continue?",
      noClaude: zh ? "找不到 Claude Code（claude.exe）。请在 Zotero 设置 → Scholium 里指定 Claude Code 程序。"
                   : "Claude Code (claude) was not found. Set its program in Zotero Settings → Scholium.",
      noCodex: zh ? "找不到 Codex（codex.exe）。请在 Zotero 设置 → Scholium 里指定 Codex 程序。"
                  : "Codex (codex) was not found. Set its program in Zotero Settings → Scholium.",
      settingsOpen: zh ? "设置…" : "Settings…",
      noSkill: agent => zh
        ? `${this.agentName(agent)} 找不到 zotero-scholium 技能：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装后再试（其他安装方式见 README）。`
        : `${this.agentName(agent)} does not find the zotero-scholium skill: install it with npx skills add weilr/zotero-scholium -g -y in a terminal, then try again (other ways in the README).`,
      installSkill: zh ? "安装技能并重试" : "Install the skill and retry",
      skillNotCarried: zh ? "这份插件没有带技能：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装。"
                          : "This copy of the plugin carries no skill: install it with npx skills add weilr/zotero-scholium -g -y in a terminal.",
      skillNoHome: zh ? "找不到用户目录，技能没有装上：在终端运行 npx skills add weilr/zotero-scholium -g -y 安装。"
                      : "The home folder was not found, so the skill was not installed: install it with npx skills add weilr/zotero-scholium -g -y in a terminal.",
      skillFailed: msg => zh ? `技能没有装上：${msg}。在终端运行 npx skills add weilr/zotero-scholium -g -y 安装。`
                             : `The skill could not be installed: ${msg}. Install it with npx skills add weilr/zotero-scholium -g -y in a terminal.`,
      notSignedIn: agent => agent === "codex"
        ? (zh ? "Codex 还没有登录：在终端运行 codex login，登录后再试。" : "Codex is not signed in: run codex login in a terminal, then try again.")
        : (zh ? "Claude Code 还没有登录：在终端运行 claude，按提示登录后再试。" : "Claude Code is not signed in: run claude in a terminal and sign in, then try again."),
      localApiOff: zh ? "Scholium 通过 Zotero 的本地 API 读取论文，它现在是关闭的（设置 → 高级 → 允许此计算机上的其他应用程序与 Zotero 通讯）。现在打开吗？"
                      : "Scholium reads the paper through Zotero's local API, which is turned off (Settings → Advanced → Allow other applications on this computer to communicate with Zotero). Turn it on now?",
      pymupdfMissing: zh ? `缺少 PyMuPDF，安装 uv（在终端运行 ${uvInstall}）或运行 pip install -U pymupdf 后再试。`
                         : `PyMuPDF is missing; install uv (run ${uvInstall} in a terminal) or run pip install -U pymupdf, then try again.`,
      noPython: zh ? `找不到 Python，安装 uv（在终端运行 ${uvInstall}），或安装 Python 3.9 或更高版本并运行 pip install -U pymupdf 后再试。`
                   : `Python was not found; install uv (run ${uvInstall} in a terminal), or install Python 3.9 or later and run pip install -U pymupdf, then try again.`,
      noUv: zh ? `找不到 uv，在终端运行 ${uvInstall} 安装后再试。` : `uv was not found; install it with ${uvInstall} in a terminal, then try again.`,
      noTextLayer: zh ? "这个 PDF 没有文字层（扫描件）：先做 OCR 文字识别（例如 ocrmypdf，或 Acrobat 的“识别文本”），再批注。"
                      : "The PDF has no text layer (a scanned document): run OCR on it first (e.g. ocrmypdf, or Acrobat's Recognize Text), then annotate again.",
      // the setup check of the settings page: each line's name, its sentence, and its button
      checkLabel: id => ({ localApi: zh ? "本地 API" : "Local API", claude: "Claude Code", claudeSkill: zh ? "Claude Code 的技能" : "Claude Code's skill",
                           codex: "Codex", codexSkill: zh ? "Codex 的技能" : "Codex's skill", uv: "uv", python: "Python", pymupdf: "PyMuPDF" })[id] || id,
      checkApiOn: zh ? "已打开，Scholium 通过它读取论文。" : "On; Scholium reads papers through it.",
      checkApiOff: zh ? "已关闭，Scholium 读不到论文：点“打开”，或在 设置 → 高级 里勾选“允许此计算机上的其他应用程序与 Zotero 通讯”。"
                      : "Off, so Scholium cannot read papers: press Turn on, or tick “Allow other applications on this computer to communicate with Zotero” in Settings → Advanced.",
      checkTurnOn: zh ? "打开" : "Turn on",
      checkInstall: zh ? "安装" : "Install",
      checkNoProgram: agent => zh ? `未找到：安装 ${this.agentName(agent)}，或在上方指定它的程序。` : `Not found: install ${this.agentName(agent)}, or set its program above.`,
      checkProgramGone: zh ? "上方指定的程序不存在：改正路径，或清空以自动查找。" : "The program set above does not exist: correct the path, or clear it to find the program automatically.",
      checkSignedIn: zh ? "已登录。" : "Signed in.",
      checkSignedOut: agent => agent === "codex"
        ? (zh ? "还没有登录：在终端运行 codex login。" : "Not signed in: run codex login in a terminal.")
        : (zh ? "还没有登录：在终端运行 claude，按提示登录。" : "Not signed in: run claude in a terminal and sign in."),
      checkSignInUnknown: why => zh ? `登录状态未知（${why}）。` : `Sign-in unknown (${why}).`,
      checkAuthSilent: zh ? "claude auth status 没有回答" : "claude auth status gave no answer",
      checkCodexFailed: msg => zh ? `出错：${msg}` : `Failed: ${msg}`,
      checkNoAnswer: s => zh ? `${s} 秒内没有回答` : `no answer in ${s} s`,
      checkSkillAt: dir => zh ? `已找到：${dir}` : `Found: ${dir}`,
      checkSkillMissing: zh ? "未找到：点“安装”，或在终端运行 npx skills add weilr/zotero-scholium -g -y。"
                            : "Not found: press Install, or run npx skills add weilr/zotero-scholium -g -y in a terminal.",
      checkUv: (v, path) => zh ? `${v}：${path}` : `${v} at ${path}`,
      checkUvSilent: path => zh ? `${path} 没有报出版本` : `${path} did not give its version`,
      checkNoUv: zh ? `未找到。推荐安装：uv 会自行提供 Python 和 PyMuPDF。在终端运行 ${uvInstall} 安装${os === "Darwin" ? "（或 brew install uv）" : ""}。`
                    : `Not found. Recommended: uv provides Python and PyMuPDF by itself; install it with ${uvInstall} in a terminal`
                      + `${os === "Darwin" ? " (or brew install uv)" : ""}.`,
      checkNoPythonUv: zh ? "Scholium 找不到 Python；uv 会代为提供 Python 和 PyMuPDF。" : "Scholium finds no Python; uv provides Python and PyMuPDF instead.",
      checkPythonOldUv: (v, path) => zh ? `${v} 太旧：${path}；uv 会代为提供 Python 和 PyMuPDF。` : `${v} at ${path} is too old; uv provides Python and PyMuPDF instead.`,
      checkPymupdfUv: zh ? "未安装；uv 会代为提供 PyMuPDF。" : "Not installed; uv provides PyMuPDF instead.",
      checkOnPath: zh ? "Scholium 找到的 Python，智能体的终端可能用另一个" : "the Python Scholium finds; an agent's shell may use another",
      checkPython: (v, path) => zh ? `${v}：${path}（${this.text("checkOnPath")}）` : `${v} at ${path} (${this.text("checkOnPath")})`,
      checkPythonOld: (v, path) => zh ? `${v} 太旧，需要 3.9 或更高版本：${path}（${this.text("checkOnPath")}）`
                                      : `${v} is too old; 3.9 or later is needed: ${path} (${this.text("checkOnPath")})`,
      checkPythonSilent: path => zh ? `${path} 没有报出版本（${this.text("checkOnPath")}）` : `${path} did not give its version (${this.text("checkOnPath")})`,
      checkNoPython: zh ? "Scholium 找不到 Python：安装 Python 3.9 或更高版本，再运行 pip install -U pymupdf（智能体的终端可能有另一个 Python）。"
                        : "Scholium finds no Python: install Python 3.9 or later, then run pip install -U pymupdf (an agent's shell may have another Python).",
      checkPymupdf: v => zh ? `已安装 ${v}` : `Installed: ${v}`,
      checkPymupdfMissing: zh ? "未安装：在终端运行 pip install -U pymupdf。" : "Not installed: run pip install -U pymupdf in a terminal.",
      redoTitle: zh ? "重新批注" : "Annotate again",
      redo: (n, notes, group = false) => zh
        ? `这篇论文已有 ${n} 条 Scholium 批注。重新批注会先删除它们${notes ? `，并把 ${notes} 篇阅读笔记移到回收站` : ""}，你自己的批注和笔记不受影响。`
          + (group ? groupShared : "") + "继续吗？"
        : `This paper already carries ${plural(n, "Scholium annotation", "Scholium annotations")}. Annotating again first deletes ${n === 1 ? "it" : "them"}`
          + (notes ? ` and moves ${plural(notes, "reading note", "reading notes")} to the trash` : "") + "; your own annotations and notes are not affected. "
          + (group ? groupShared + " " : "") + "Continue?",
      typical: zh ? "已在后台开始，通常需要 10–20 分钟。过程和进度见条目侧栏的 Scholium 区块。"
                  : "Started in the background; this usually takes 10–20 minutes. The Scholium section of the item pane shows the process and the progress.",
      paneAgent: zh ? "智能体" : "Agent",
      paneModel: zh ? "模型" : "Model",
      paneEffort: zh ? "推理强度" : "Effort",
      agentSwitchNote: zh ? "对话不变，下一条消息由所选智能体回答；批注会话按智能体分开。"
                          : "The conversation shown stays; the agent chosen answers the next message. Annotation sessions are each agent's own.",
      moreTitle: zh ? "更多" : "More",
      paneNoEffort: zh ? "不适用" : "n/a",
      paneClaudeDefault: zh ? "Claude Code 默认" : "Claude Code's default",
      paneClaudeDefaultModel: name => zh ? `Claude Code 默认（${name}）` : `Claude Code's default (${name})`,
      paneCodexDefault: zh ? "Codex 默认" : "Codex's default",
      paneCodexDefaultModel: name => zh ? `Codex 默认（${name}）` : `Codex's default (${name})`,
      annotateThis: zh ? "批注这篇" : "Annotate",
      deleteThis: zh ? "删除批注" : "Delete annotations",
      logButton: zh ? "打开日志" : "Show log",
      saveNote: zh ? "存为笔记" : "Save as note",
      noteSaved: zh ? "已存为这篇论文的笔记" : "Saved as a note of the paper",
      noteNotSaved: why => zh ? `没有存为笔记：${why}` : `Not saved as a note: ${why}`,
      noteReadOnly: zh ? "你在这个群组里没有编辑权限，无法存为笔记。" : "You cannot edit this group's library, so the note cannot be saved.",
      noteHeading: title => zh ? `Scholium 对话：${title}` : `Scholium conversation: ${title}`,
      noteQuestion: zh ? "问：" : "Question:",
      noteAnswer: who => (who ? (zh ? `答（${who}）：` : `Answer (${who}):`) : (zh ? "答：" : "Answer:")),
      copyMessage: zh ? "复制这条回复（Markdown）" : "Copy this message (Markdown)",
      copiedMessage: zh ? "已复制" : "Copied",
      worked: d => zh ? `已处理 ${d}` : `Worked for ${d}`,
      working: zh ? "正在处理" : "Working",
      workingFor: d => zh ? `正在处理 ${d}` : `Working for ${d}`,
      workedPlain: zh ? "已处理" : "Worked",
      preRun: zh ? "正在读取 PDF…" : "Reading the PDF…",
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
      queuedThis: n => zh ? `排队中，前面还有 ${n} 篇` : `Queued, ${n} ahead`,
      deleteTitle: zh ? "删除 Scholium 批注和笔记" : "Delete Scholium annotations and notes",
      deleteConfirm: (n, notes, group = false) => zh
        ? `将删除带 zotero-scholium 标签的${[n ? `这个 PDF 上的 ${n} 条批注` : "", notes ? `这篇论文的 ${notes} 篇阅读笔记` : ""].filter(Boolean).join("和")}。`
          + [n ? "批注永久删除，不能撤销" : "", notes ? "笔记移到回收站，可以恢复" : ""].filter(Boolean).join("；")
          + "。你自己的批注和笔记都保留。删除会同步。" + (group ? groupShared : "") + "继续吗？"
        : `This deletes ${[n ? plural(n, "annotation", "annotations") + " on this PDF" : "", notes ? plural(notes, "reading note", "reading notes") + " of the paper" : ""]
            .filter(Boolean).join(" and ")}, tagged zotero-scholium. `
          + [n ? "The annotations are deleted for good" : "", notes ? (n ? "the" : "The") + (notes === 1 ? " note goes to the trash, where it can be restored" : " notes go to the trash, where they can be restored") : ""]
            .filter(Boolean).join("; ")
          + ". Your own annotations and notes are kept. The deletion syncs. " + (group ? groupShared + " " : "") + "Continue?",
      deleteSkipped: zh ? "正在批注或排队的 PDF 不会删除。" : "A PDF being annotated or queued is skipped.",
      deleteNone: zh ? "这个 PDF 没有 Scholium 批注，这篇论文也没有 Scholium 阅读笔记。"
                     : "This PDF carries no Scholium annotations, and the paper no Scholium reading notes.",
      deleteElsewhere: n => zh ? `这篇论文的另一个 PDF 上还有 ${n} 条 Scholium 批注：打开那个 PDF 即可删除。`
                               : `Another PDF of this paper carries ${plural(n, "Scholium annotation", "Scholium annotations")}: open that PDF to delete ${n === 1 ? "it" : "them"}.`,
      deleteDone: (n, notes) => zh
        ? [n || !notes ? `已删除 ${n} 条 Scholium 批注` : "", notes ? `${notes} 篇笔记已移到回收站` : ""].filter(Boolean).join("，") + "。"
        : [n || !notes ? `Deleted ${plural(n, "Scholium annotation", "Scholium annotations")}` : "",
           notes ? `${plural(notes, "note", "notes")} moved to the trash` : ""].filter(Boolean).join("; ") + ".",
      deleteFailed: msg => zh ? `删除失败：${msg}` : `Deletion failed: ${msg}`,
      starting: name => zh ? `启动 ${name}` : `starting ${name}`,
      extract: zh ? "提取句子" : "extracting sentences",
      reading: zh ? "通读论文" : "reading the paper",
      writing: zh ? "撰写批注" : "writing the annotations",
      applying: zh ? "写入 Zotero" : "writing to Zotero",
      done: zh ? "完成" : "done",
      failed: zh ? "失败" : "failed",
      cancelled: zh ? "已取消" : "cancelled",
      cancelledTitle: zh ? "已取消" : "Cancelled",   // the stopped card's title
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
      nothingToCompact: zh ? "还没有可压缩的内容" : "Nothing to compact yet",
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
      askPapers: n => zh ? `问 Scholium（${n} 篇）` : `Ask Scholium (${n} papers)`,
      papersLead: zh ? "同时问" : "Also about",
      paperRemove: title => zh ? `不问《${title}》` : `Leave out “${title}”`,
      papersNoPdf: zh ? "选中的论文在这台电脑上都没有 PDF 文件。" : "None of the selected papers has a PDF file on this computer.",
      quoteRemove: zh ? "不引用这段" : "Remove the quote",
      annotEmptyTitle: zh ? "还没有批注这篇" : "Not annotated yet",
      annotOwnTitle: n => zh ? `这篇已有 ${n} 条 Scholium 批注` : `This paper carries ${plural(n, "Scholium annotation", "Scholium annotations")}`,
      annotEmptyBody: zh ? "高亮重点句（外文论文附译文），加页边批注和阅读笔记。"
                         : "Highlights key sentences (translated when the paper is in another language), adds margin notes and a reading note.",
      annotExtraHint: zh ? "附加要求（可不填），例如：只批注第 3–5 页" : "Extra instructions (optional), e.g. only pages 3–5",
      annotFollowUpHint: zh ? "接着这次批注修改，例如：第 5 页那条译文改短" : "Continue this annotation, e.g. shorten the translation on page 5",
      redoInline: (n, notes, group = false) => zh ? `重新批注会先删除这篇的 ${n} 条 Scholium 批注${notes ? `，${notes} 篇阅读笔记移到回收站` : ""}（你自己的不动）。`
          + (group ? groupShared : "")
        : `Annotating again first deletes this paper's ${plural(n, "Scholium annotation", "Scholium annotations")}`
          + (notes ? ` and moves ${plural(notes, "reading note", "reading notes")} to the trash` : "") + " (yours stay)." + (group ? " " + groupShared : ""),
      replace: zh ? "替换" : "Replace",
      cancelButton: zh ? "取消" : "Cancel",
      details: zh ? "详情" : "Details",
      annotDone: zh ? "✓ 批注完成" : "✓ Annotated",
      annotDoneClean: zh ? "✓ 批注完成，没有剩余警告" : "✓ Annotated, no warnings left",
      annotDoneWarn: w => zh ? `✓ 批注完成，剩余警告：${w}` : `✓ Annotated, warnings left: ${w}`,
      // the label of the warnings left in an annotation's closing line, and its word for none (warningsPart, warningsOf)
      warningsLabel: zh ? "剩余警告" : "remaining warnings",
      warningsNone: zh ? "无" : "none",
      annotNone: zh ? "没有写入批注" : "No annotations written",
      annotNoneWarn: w => zh ? `没有写入批注：${w}` : `No annotations written: ${w}`,
      annotNoneScan: w => zh ? `没有写入批注：${w}` : `No annotations written. ${w}`,   // w: a whole sentence (noTextLayer)
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
      // a page as a citation gives it: the quoted passage's and a cited sentence's chip
      pageRef: p => `p.${p}`,
      locate: zh ? "定位 ↗" : "Locate ↗",
      retry: zh ? "重试" : "Retry",
      editPrompt: zh ? "编辑" : "Edit",
      editSend: zh ? "发送" : "Send",
      editCancel: zh ? "取消" : "Cancel",
      replaced: zh ? "已替换" : "Replaced",
      compactingFor: d => zh ? `正在压缩上下文 ${d}` : `Compacting context for ${d}`,
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
      pausedState: (time, name) => zh ? `${name} 额度已用完，${time} 重置后自动继续` : `${name} usage limit reached; continues by itself after ${time}`,
      pausedRetry: (time, name) => zh ? `${name} 额度已用完，${time} 自动重试` : `${name} usage limit reached; retries by itself at ${time}`,
      throttledState: (time, name) => zh ? `${name} 服务暂时限流，${time} 自动继续` : `${name} is limiting requests; continues by itself at ${time}`,
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
      // a date without the year; a length of time in words (6 分 17 秒 / 6m 17s), whole hours with their minutes
      monthDay: (month, day) => zh ? `${month}月${day}日` : `${month}/${day}`,
      durationWords: (h, m, s) => zh ? (h ? `${h} 小时 ${m} 分` : m ? `${m} 分 ${s} 秒` : `${s} 秒`) : h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`,
      // the reader toolbar's eye button
      toggleHide: zh ? "隐藏 Scholium 批注" : "Hide Scholium annotations",
      toggleShow: zh ? "显示 Scholium 批注" : "Show Scholium annotations",
    };
  },
};
