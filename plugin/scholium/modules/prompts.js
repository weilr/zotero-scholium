// ScholiumRunner, continued: a paper's PDF, key and library, the prompts, the agents' arguments, paper.json and
// applied.json, and the words of a run's steps and state

Object.assign(ScholiumRunner, {
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

  // the key a PDF's runs and files are kept under: its own in My Library; in another library, where the same key may
  // stand for another item, with that library's group id (ABCD2345_g123), or its library id when it is no group
  keyOf(att) {
    if (!att) return null;
    if (!att.libraryID || att.libraryID === Zotero.Libraries.userLibraryID) return att.key;
    const group = this.groupOf(att.libraryID);
    return `${att.key}_${group ? "g" + group : "l" + att.libraryID}`;
  },

  // the PDF of a library a key of keyOf names
  attOf(libraryID, key) { return key ? Zotero.Items.getByLibraryAndKey(libraryID, String(key).replace(/_[gl]\d+$/, "")) : null; },

  // the group id of a group's library; null for My Library and other libraries
  groupOf(libraryID) {
    if (!libraryID || libraryID === Zotero.Libraries.userLibraryID) return null;
    try { return Zotero.Groups.getGroupIDFromLibraryID(libraryID) || null; } catch (e) { return null; }
  },

  // whether annotations can be written to the PDF's library: a group whose library or files the user cannot edit
  // cannot take them
  writable(att) {
    if (!att || !att.libraryID || att.libraryID === Zotero.Libraries.userLibraryID) return true;
    try {
      const lib = Zotero.Libraries.get(att.libraryID);
      return !lib || (lib.editable !== false && lib.filesEditable !== false);
    } catch (e) { return true; }
  },

  // the message, after the conversation so far for a new session that is not given it otherwise, or after the turns a
  // session that goes on has not seen
  prompt(job, own, history = true) {
    if (job.compact) return "/compact" + (job.say ? " " + job.say : "");
    const message = this.taskPrompt(job, own);
    const before = history ? this.historyText(job.history || []) : "";
    return [before, this.missedText(job.missed || [], job.missedFrom || 0), message].filter(Boolean).join("\n\n");
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
    const paper = this.paperPath(this.keyOf(job.att));
    return [zh ? `这篇论文已有 ${own} 条本工具的批注；问到它们的内容时，用 --config ${paper} --list --full 列出。`
                 + "要改批注或补几条时，编辑输出目录里写入它们的那份配置（它是这篇论文的全部批注），设 cleanup: true 整份重写"
                 + "（阅读笔记也改时再设 note_replace: true）；不要另写只含新条目的配置。"
               : `The paper carries ${own} annotations of this tool; when the question is about their content, list them with --config ${paper} --list --full. `
                 + "To change annotations or add a few, edit the configuration in the output directory they were written from (it holds the paper's "
                 + "whole set) and set cleanup: true (and note_replace: true when the reading note changes); do not write a separate configuration "
                 + "with just new entries."];
  },

  // what a session that goes on is told of the annotations changed since its last run: rewritten by another agent in this
  // conversation, or in another of the paper's conversations, or gone
  changedLines(job) {
    const zh = this.zh();
    if (!job.own && job.asking) return [];
    if (!job.own) return [zh ? "这篇论文现在没有本工具的批注（可能已在 Zotero 里删除）。" : "The paper carries no annotations of this tool now (they may have been deleted in Zotero)."];
    const a = job.applied;
    if (!a) return [];
    // its own rewrite in this conversation is in its session only when its latest run made it
    const own = a.conv === job.conv && a.agent === job.agent && (!job.sinceEnd || a.at <= job.sinceEnd);
    if (!(a.at > (job.since || 0)) || own) return [];
    const name = this.agentName(a.agent), when = this.clock(a.at);
    if (a.conv === job.conv) {
      return [zh ? `上次之后，${name} 在这段对话里用配置 ${a.config} 重写了批注（${when}）；改批注前先读这份配置，不要用你记得的版本。`
                 : `Since your last turn, ${name} rewrote the annotations from the configuration ${a.config} in this conversation (${when}); `
                   + "read that configuration before changing annotations, not the version you remember."];
    }
    return [zh ? `上次之后，${name} 在这篇论文的另一段对话里用配置 ${a.config} 重写了批注（${when}）；改批注前先读这份配置，不要用你记得的版本。`
               : `Since your last turn, ${name} rewrote the annotations from the configuration ${a.config} in another conversation `
                 + `about this paper (${when}); read that configuration before changing annotations, not the version you remember.`];
  },

  // how a session's commands name the paper: through paper.json, which is the plugin's, never with the PDF's path or the
  // paper's metadata; the agent's configuration is a file of its own
  paperRule(key) {
    const paper = this.paperPath(key), own = PathUtils.join(this.outDir(key), "config.json");
    // paper.json of another library than My Library also names it (library_id, and group_id for a group)
    const n = /_g\d+$/.test(key) ? 6 : /_l\d+$/.test(key) ? 5 : 4;
    return this.zh() ? `${paper} 是插件的文件，只读，不要修改：只有 extract（代替 --pdf）和 --list 用 --config ${paper}。`
                       + `你的配置另写一个文件，放在输出目录里（如 ${own}），从 ${paper} 的${"四五六"[n - 4]}个键写起，试运行和 --apply 都用它。`
                       + "不要把 PDF 路径、论文标题或其他题录写进命令行。"
                     : `${paper} is the plugin's and read-only; do not edit it. Only extract (in place of --pdf) and --list take --config ${paper}. `
                       + `Write your configuration to a file of your own in the output directory (e.g. ${own}), starting from the ${["four", "five", "six"][n - 4]} keys of ${paper}, `
                       + "and give that one to the dry run and to --apply. Never put the PDF's path, the paper's title or other metadata on a command line.";
  },

  // the prompt's line of a paper in a group library: the group, which status and samples are given
  groupLines(job) {
    const group = this.groupOf(job.att.libraryID);
    if (!group) return [];
    return [this.zh() ? `- 群组文库：${group}（status 和 samples 加 --group ${group}）` : `- Group library: ${group} (give status and samples --group ${group})`];
  },

  // the prompt's lines of the other papers of a question about several: each one's paper.json, and the sentence numbers
  // kept to the first paper, whose sentences the answer's chips show
  papersLines(job) {
    const files = job.paperFiles || [];
    if (!files.length) return [];
    return this.zh() ? [
      "这个问题同时涉及下面几篇论文。每个 paper.json 给出那篇论文的 PDF 路径、两个 key 和输出目录：按需对每篇用 --config 它的 paper.json 运行 extract，"
        + "读它自己输出目录里的 sentences.txt。句子编号 [#123] 只用于上面这篇；引用其他论文时写论文标题和页码。",
      ...files.map(f => `- ${f.path}（${f.title}）`),
    ] : [
      "The question is also about the papers below. Each paper.json gives that paper's PDF path, its two keys and its output directory: "
        + "run extract with --config and its paper.json as needed, and read the sentences.txt in its own output directory. Sentence numbers [#123] "
        + "are for the paper above only; for the others, name the paper and the page.",
      ...files.map(f => `- ${f.path} (${f.title})`),
    ];
  },

  // the message itself: a follow-up in the agent's own session, a question (or a follow-up in a session the agent
  // starts), or the annotation task
  taskPrompt(job, own) {
    const outDir = this.outDir(this.keyOf(job.att));
    // an annotation that continues a question's conversation gets the whole task
    if (job.resume && !job.annotate) return this.followUpPrompt(job);
    if (job.say) return this.questionPrompt(job, own);
    if (this.zh()) {
      return [
        "使用 zotero-scholium 技能，为下面这篇论文做整篇标注：重点句高亮加译文评论（论文本身是中文时不加评论）、页边批注、阅读笔记，按画像和默认值。",
        "",
        `- 条目 key：${job.parentKey}`,
        `- 附件 key：${job.att.key}`,
        ...this.groupLines(job),
        `- 论文：${this.paperPath(this.keyOf(job.att))}（PDF 的路径、两个 key 和输出目录）`,
        `- 输出目录：${outDir}`,
        job.profile ? `- 画像：${job.profile}` : "- 画像：没有；按默认值标注，不要生成或修改画像",
        "",
        "这是从 Zotero 里一键启动的无人值守任务：不要向用户提问，不要启动子代理，由你独立完成第 1–3 步并写入 Zotero。",
        this.paperRule(this.keyOf(job.att)),
        ...this.languageLines(),
        own ? `这篇论文已有 ${own} 条本工具的注释，用户已确认整篇重做（配置里设 cleanup: true）。` : "这篇论文目前没有本工具的注释。",
        ...(job.extra ? ["", "用户的附加要求：", job.extra] : []),
        "",
        "结束时最后一行只写一句：高亮 N 条（核心 M 条），页边批注 K 条，笔记《标题》，剩余警告。",
      ].join("\n");
    }
    return [
      "Use the zotero-scholium skill to annotate the whole paper below: key-sentence highlights with translation comments (none when the paper is already in the user's language), margin notes, and a reading note, following the profile and the defaults.",
      "",
      `- Item key: ${job.parentKey}`,
      `- Attachment key: ${job.att.key}`,
      ...this.groupLines(job),
      `- Paper: ${this.paperPath(this.keyOf(job.att))} (the PDF's path, the two keys and the output directory)`,
      `- Output directory: ${outDir}`,
      job.profile ? `- Profile: ${job.profile}` : "- Profile: none; annotate with the defaults and do not create or change a profile",
      "",
      "This is an unattended task started from Zotero with one click: do not ask the user anything and do not start sub-agents; complete steps 1-3 yourself and write to Zotero.",
      this.paperRule(this.keyOf(job.att)),
      ...this.languageLines(),
      own ? `The paper already carries ${own} annotations of this tool; the user confirmed a complete redo (cleanup: true in the configuration).` : "The paper carries no annotations of this tool yet.",
      ...(job.extra ? ["", "The user's extra instructions:", job.extra] : []),
      "",
      "End with one line only: N highlights (M core), K margin notes, note “title”, remaining warnings.",
    ].join("\n");
  },

  // the user's words to a new session: the first message of a conversation, which answers without annotating, or the
  // next one of a conversation whose session is gone
  questionPrompt(job, own) {
    const outDir = this.outDir(this.keyOf(job.att));
    const paper = this.paperPath(this.keyOf(job.att));
    const later = !!(job.history && job.history.length);   // a message of a conversation that a new session goes on with
    return (this.zh() ? [
      "使用 zotero-scholium 技能读下面这篇论文（status 给出题录，extract 给出正文），回答用户在 Zotero 里提的问题。",
      "",
      `- 条目 key：${job.parentKey}`,
      `- 附件 key：${job.att.key}`,
      ...this.groupLines(job),
      `- 论文：${paper}（PDF 的路径、两个 key 和输出目录）`,
      `- 输出目录：${outDir}`,
      job.profile ? `- 画像：${job.profile}` : "- 画像：没有；不要生成或修改画像",
      ...this.papersLines(job),
      "",
      "这是从 Zotero 里发来的无人值守任务：不要向用户提问，不要启动子代理。只回答，不写批注和笔记；用户在问题里明确要求时，才按技能的流程写入 Zotero。",
      this.paperRule(this.keyOf(job.att)),
      ...this.languageLines(),
      ...this.annotationLines(job, own),
      `引用论文原句时，在句末写它的句子编号，格式 [#123]（多句写 [#12][#15]）；编号来自 extract --config ${paper} --sentences ${outDir}/sentences.json --out ${outDir}/sentences.txt（已有就直接读 sentences.txt）。`,
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
      ...this.groupLines(job),
      `- Paper: ${paper} (the PDF's path, the two keys and the output directory)`,
      `- Output directory: ${outDir}`,
      job.profile ? `- Profile: ${job.profile}` : "- Profile: none; do not create or change a profile",
      ...this.papersLines(job),
      "",
      "This is an unattended task sent from Zotero: do not ask the user anything and do not start sub-agents. Only answer; write no annotations "
        + "and no note unless the question asks for them, and then write to Zotero as the skill describes.",
      this.paperRule(this.keyOf(job.att)),
      ...this.languageLines(),
      ...this.annotationLines(job, own),
      `When you quote a sentence of the paper, put its sentence number after it as [#123] (several: [#12][#15]); the numbers come from extract --config ${paper} --sentences ${outDir}/sentences.json --out ${outDir}/sentences.txt (read sentences.txt when it is there).`,
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
        ...this.languageLines(),
        ...changed,
        ...this.papersLines(job),
        "",
        this.said(job),
        "",
        "写入了 Zotero 时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。",
      ] : [
        "Below is a follow-up message about this paper, sent from Zotero. It is still unattended: do not ask the user anything and do not start sub-agents. "
          + "Answer a question directly; write annotations or a note only when the user asks for them, and then write to Zotero as the skill describes.",
        ...this.languageLines(),
        ...changed,
        ...this.papersLines(job),
        "",
        this.said(job),
        "",
        "When you wrote to Zotero, end with one line only: what changed, remaining warnings. Leave that line out when only answering.",
      ]).join("\n");
    }
    return (zh ? [
      "下面是用户在 Zotero 里针对这篇论文和它的批注发来的后续消息。仍是无人值守：不要向用户提问，不要启动子代理。"
        + "只是提问就直接回答；要改批注时按技能的流程修改配置，再写入 Zotero。",
      ...this.languageLines(),
      ...(job.own ? ["改已经写入的批注或补几条时，都编辑写入它们的那份配置（它是这篇论文的全部批注），设 cleanup: true 整份重写"
                     + "（阅读笔记也改时再设 note_replace: true）；不要另写只含新条目的配置，否则下次整份重写时会把它们删掉。"] : []),
      ...changed,
      ...this.papersLines(job),
      "",
      this.said(job),
      "",
      "改了批注时，结束时最后一行只写一句：改了什么，剩余警告。只回答问题时不写这一行。",
    ] : [
      "Below is a follow-up message about this paper and its annotations, sent from Zotero. It is still unattended: do not ask the user anything and do not start sub-agents. "
        + "Answer a question directly; to change annotations, edit the configuration as the skill describes and write it to Zotero again.",
      ...this.languageLines(),
      ...(job.own ? ["To change annotations already written or to add a few, edit the configuration they were written from (it holds the paper's whole "
                     + "set) and set cleanup: true, so that the whole set replaces them (and note_replace: true when the reading note changes); do not "
                     + "write a separate configuration with just new entries, which the next whole rewrite would delete."] : []),
      ...changed,
      ...this.papersLines(job),
      "",
      this.said(job),
      "",
      "When annotations changed, end with one line only: what changed, remaining warnings. Leave that line out when only answering.",
    ]).join("\n");
  },

  outDir(key) { return PathUtils.join(Zotero.DataDirectory.dir, "tmp", "scholium", key); },

  async args(job) {
    // the text arrives as it is written (stream events), and each whole message after it
    const args = ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                  "--permission-mode", this.getPref("claudePermissionMode") || "auto"];
    // the skill's folder in Claude Code's own (CLAUDE_CONFIG_DIR, else ~/.claude), when it is there
    const skills = this.skillsDir("claude");
    const skill = skills ? PathUtils.join(skills, "zotero-scholium") : "";
    if (skill && (await this.exists(skill))) args.push("--add-dir", skill);
    const outRoot = PathUtils.join(Zotero.DataDirectory.dir, "tmp", "scholium").replace(/\\/g, "/");
    args.push("--allowedTools", "Skill", "Read", `Write(${outRoot}/**)`, `Edit(${outRoot}/**)`);
    // only the tools a run uses are in its context (PowerShell only on Windows, where Claude Code has it); a chat's
    // message may also look something up on the web
    const tools = ["Skill", "Bash"].concat(Services.appinfo.OS === "WINNT" ? ["PowerShell"] : [], ["Read", "Write", "Edit", "Grep", "Glob"]);
    if (!job || job.kind !== "annotate") tools.push("WebSearch", "WebFetch");
    args.push("--tools", tools.join(","));
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

  // the step of a command of the tool (scholium.py run by python or by uv run, or the scholium command), the furthest when
  // one line holds several: a write to Zotero, a dry run, extracting sentences. --config is the script's option, not uv's
  // --config-file
  commandStep(cmd) {
    if (!/\bscholium(?:\.py)?\b/.test(cmd)) return null;
    if (/--apply\b/.test(cmd)) return "applying";
    if (/\bscholium(?:\.py)?["']?\s+extract\b/.test(cmd)) return "extract";
    if (/--list\b/.test(cmd)) return null;
    if (/--config(?:[\s=]|$)/.test(cmd)) return "dryRun";
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

  // the paper as the agent's commands name it (--config): the PDF's path, the keys and the output folder, so that the
  // path, whose file name a shell would expand ($, a backtick), stays off command lines
  paperPath(key) { return PathUtils.join(this.outDir(key), "paper.json"); },

  // a PDF's paper.json, which names it for the skill's script: the PDF's path, the two keys, the output directory and, in
  // another library than My Library, that library
  async writePaper(att, pdf, parentKey) {
    const key = this.keyOf(att), paper = this.paperPath(key);
    const group = this.groupOf(att.libraryID);
    const library = att.libraryID && att.libraryID !== Zotero.Libraries.userLibraryID
      ? Object.assign({ library_id: att.libraryID }, group ? { group_id: group } : {}) : {};
    await IOUtils.writeUTF8(paper, JSON.stringify(Object.assign({ pdf, item_key: parentKey, attachment_key: att.key, out_dir: this.outDir(key) },
                                                                library), null, 1) + "\n", { tmpPath: paper + ".tmp" });
  },

  // whether a command of the tool wrote to Zotero: its output's outcome ("applied": true, or "partial" when the earlier
  // items stayed), whatever the exit code; without one in sight, whether the command succeeded
  // what a shell command's output says this computer lacks for the skill (a text key), kept until a later command of
  // the skill's script prints neither; other tools (a file read shows the script's own text) leave it as it was
  missingAfter(command, output, before) {
    if (!command) return before;
    const text = typeof output === "string" ? output
      : Array.isArray(output) ? output.map(c => (c && c.type === "text" ? c.text : "")).join("\n") : "";
    if (text.includes("PyMuPDF is not installed") && !text.includes("PYMUPDF_MISSING")) return "pymupdfMissing";
    if (/Python was not found|\bpython3?: (?:command )?not found|command not found: python3?\b|'python3?' is not recognized/i.test(text)) return "noPython";
    // uv missing, as bash or sh, zsh, fish, PowerShell or cmd say it
    if (/\buv: (?:command )?not found|command not found: uv\b|Unknown command: uv\b|'uv' is not recognized/i.test(text)) return "noUv";
    // extract's error for a scan without OCR, as JSON (the script's source holds it in another form)
    if (/"error":\s*"the PDF has no text layer/.test(text)) return "noTextLayer";
    return /scholium\.py\b|(?:^|[\s;&|("'])scholium\s/.test(command) ? null : before;
  },

  wrote(output, succeeded) {
    const text = typeof output === "string" ? output
      : Array.isArray(output) ? output.map(c => (c && c.type === "text" ? c.text : "")).join("\n") : "";
    const outcome = [...text.matchAll(/"applied":\s*(true|false|"partial")/g)].pop();
    return outcome ? outcome[1] !== "false" : !!succeeded;
  },

  // a write to Zotero that succeeded, kept whatever the run's end: a relative configuration is the one of the folders
  // it may have run in (the first given, then the output folder) that has it; a Git Bash path (/d/…) is also tried as
  // the Windows one. A write whose configuration is not found (a path the shell expands, as $o\config.json or
  // %o%\config.json, or one that is not there), or is the plugin's paper.json, leaves no configuration kept: a new
  // session is then told to list the annotations, not to rewrite them from an older configuration
  async noteApplied(key, config, agent, conv, base) {
    const file = this.appliedPath(key);
    let path = null;
    if (!/\$[A-Za-z_{(]|%[^%\\\/]+%/.test(config) && !/(?:^|[\\\/])paper\.json$/i.test(config)) {
      // a Windows path takes no "/", which Gecko refuses
      const win = p => (/^[A-Za-z]:/.test(p) ? p.replace(/\//g, "\\") : p);
      let candidates = [win(config)];
      const bash = /^\/([A-Za-z])\/(.+)$/.exec(config);
      if (bash) candidates.push(bash[1].toUpperCase() + ":\\" + bash[2].replace(/\//g, "\\"));
      if (!/^(?:[A-Za-z]:)?[\\/]/.test(config)) {
        const rel = config.replace(/^\.[\\/]/, "");
        const join = dir => (/^[A-Za-z]:|\\/.test(dir) ? (dir.replace(/[\\/]+$/, "") + "\\" + rel).replace(/\//g, "\\") : dir.replace(/[\\/]+$/, "") + "/" + rel);
        candidates = [base, this.outDir(key)].filter(Boolean).map(join);
      }
      for (const c of candidates) if (await this.exists(c)) { path = c; break; }
    }
    try {
      if (path) await IOUtils.writeUTF8(file, JSON.stringify({ config: path, agent, conv, at: Date.now() }), { tmpPath: file + ".tmp" });
      else await IOUtils.remove(file, { ignoreAbsent: true });
    }
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
    if (i >= 0) return this.text("stepOf", i + 1, this.STEPS.length, this.text(step));
    return step && step !== "starting" ? this.text(step) : this.text("starting", this.agentName(this.job && this.job.agent));
  },

  // the running paper's state line: its dot, with the attempt while the connection is tried again; the step and the
  // time are in the tooltip, the time also on the run's line in the transcript
  runningState() {
    const retry = this.job.retry;
    return retry ? this.text("reconnecting", retry.attempt, retry.max) : "";
  },

  // the same with the time so far, for the line's tooltip
  runningTitle() {
    if (this.job.source && this.job.source.compact) return this.text("compactingState", this.duration(this.elapsed()));
    const retry = this.job.retry;
    const step = (this.job.asking ? this.text("working") : this.stepText(this.job.step)) + (retry ? " · " + this.text("reconnecting", retry.attempt, retry.max) : "");
    return this.text("running", step, this.duration(this.elapsed()));
  },

  // the running paper's time so far in whole seconds, one value for its live line and its state line's tooltip: taken
  // from the run's start when it starts and once a second by tick (fresh)
  elapsed(fresh = false) {
    const job = this.job;
    if (!job) return 0;
    if (fresh || !(job.elapsed >= 0)) job.elapsed = Math.max(0, Math.round((Date.now() - job.started) / 1000)) * 1000;
    return job.elapsed;
  },
});
