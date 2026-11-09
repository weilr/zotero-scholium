/* The live probe's main() (scripts/smoke/live.py). live.py builds the probe from bootstrap.js, its helpers and finish(),
   with this main() in place of the smoke checks' one. It adds the paper of probe-config.json and a chain-test item, asks
   live.py for the chain test (chain-request.json, answered in chain-done.json) and ends without a run unless it passed,
   then presses Annotate the way a user would and waits for the run. The run is cancelled after CFG.limitMin minutes, after
   more than CFG.maxMsgs API messages (a cap the agent is never shown), or when live.py asks for it (CFG.stopFile: the
   session's cost reached its stop). Every agent process must get SCHOLIUM_ZOTERO_PORT = CFG.port in its environment, and
   Claude Code's arguments get CFG.flags and never --max-budget-usd; otherwise the run is cancelled. Afterwards: the card,
   the annotations and notes in the database (db.json), the final replies and the conversation logs. Options:
   CFG.openReader (a reader tab before and after the run, from a never-set eye-button preference) and CFG.chat (a
   question in the Chat tab afterwards). */
let lastEnv = null;
let promptN = 0;
const prompts = [];
function stubPrompts() {
  Services.prompt.confirm = (w, title, message) => { prompts.push({ kind: "confirm", title, message }); line("confirm", { title, message }); return true; };
  Services.prompt.alert = (w, title, message) => { prompts.push({ kind: "alert", title, message }); line("alert", { title, message }); };
}
const allAnns = att => att.getAnnotations().map(a => ({ key: a.key, type: a.annotationType, color: a.annotationColor, page: a.annotationPageLabel,
  pageIndex: (() => { try { return JSON.parse(a.annotationPosition).pageIndex; } catch (e) { return null; } })(),
  text: (a.annotationText || "").slice(0, 1000), comment: a.annotationComment || "", tags: a.getTags().map(t => t.tag) }));
function abort(reason) {
  line("abort", { reason });
  try { R().cancel(); } catch (e) {}
  return save().catch(() => {});
}
async function stopAsked() { return !!CFG.stopFile && IOUtils.exists(CFG.stopFile).catch(() => false); }
function readerCounts() {
  const out = {};
  try { out.sidebarCards = reader._iframeWindow.document.querySelectorAll(".annotation").length; } catch (e) { out.sidebarError = String(e); }
  try { out.manager = reader._internalReader._annotationManager._annotations.length; } catch (e) { out.managerError = String(e).slice(0, 80); }
  try {
    const t = reader._iframeWindow.document.querySelector(".scholium-toggle");
    out.eye = t ? { pressed: t.getAttribute("aria-pressed"), title: t.title } : null;
  } catch (e) {}
  const pv = Zotero.Prefs.get("extensions.scholium.showAnnotations", true);
  out.pref = pv === undefined ? "(unset)" : pv;
  out.toggleShown = Zotero.__scholiumToggle ? Zotero.__scholiumToggle.shown : null;
  return out;
}
async function logLines(att, test) {
  const out = [];
  for (const f of await IOUtils.getChildren(R().convDir(att.key)).catch(() => [])) {
    if (!test(PathUtils.filename(f))) continue;
    for (const l of (await IOUtils.readUTF8(f).catch(() => "")).split("\n")) out.push([PathUtils.filename(f), l]);
  }
  return out;
}
async function finalReply(att) {
  const out = [];
  for (const [file, l] of await logLines(att, f => /\.jsonl$/.test(f))) {
    if (!/"type":\s*"result"/.test(l)) continue;
    try { const e = JSON.parse(l); out.push({ file, result: String(e.result || "").slice(-600), cost: e.total_cost_usd, turns: e.num_turns }); } catch (e) {}
  }
  return out;
}
// the run's API messages so far: the distinct assistant message ids in its annotation logs
async function apiMessages(att) {
  const ids = new Set();
  for (const [, l] of await logLines(att, f => /^annotate-.*\.jsonl$/.test(f))) {
    const m = /"type":\s*"assistant".*?"id":\s*"(msg_[^"]+)"/.exec(l);
    if (m) ids.add(m[1]);
  }
  return ids.size;
}

async function main() {
  await Zotero.initializationPromise;
  listenErrors();
  stubPrompts();
  (async () => { while (watching) { try { acceptDialogs(); } catch (e) {} await delay(300); } })();
  try { Zotero.Server.LocalAPI._promptForAuthorization = async () => ({ allow: true, remember: false }); } catch (e) {}
  const ok = await waitFor(() => Zotero.__scholium && Zotero.__scholium.paneID, 60000);
  const r = R();
  line("start", { zotero: Zotero.version, plugin: r && r.version, locale: Zotero.locale, model: r && r.modelPref("claude"),
                  port: Zotero.Prefs.get("httpServer.port"), claudeSkills: r && r.skillsDir("claude"),
                  showAnnotationsPref: Zotero.Prefs.get("extensions.scholium.showAnnotations", true), lang: r && r.lang() });
  if (!ok) { await abort("the plugin did not start"); return finish(); }
  if (String(Zotero.Prefs.get("httpServer.port")) !== String(CFG.port) || String(CFG.port) === "23119") {
    await abort("this Zotero's port is " + Zotero.Prefs.get("httpServer.port") + ", not the throwaway's " + CFG.port);
    return finish();
  }

  // every agent process: the throwaway's port in its environment, or no run
  const env0 = r.agentEnv;
  r.agentEnv = async function (...x) {
    const e = await env0.apply(this, x);
    lastEnv = e;
    const port = e && e.environment && e.environment.SCHOLIUM_ZOTERO_PORT;
    line("agentEnv", { SCHOLIUM_ZOTERO_PORT: port, keys: Object.keys((e && e.environment) || {}) });
    if (String(port) !== String(CFG.port)) {
      await abort("agent environment: SCHOLIUM_ZOTERO_PORT " + port + ", not " + CFG.port);
      throw new Error("agent environment without the throwaway's port");
    }
    await save();
    return e;
  };
  // Claude Code's arguments: the plugin's own, then CFG.flags; never --max-budget-usd (the agent would be shown it)
  const args0 = r.args;
  r.args = async function (job) {
    const a = (await args0.call(this, job)).concat(CFG.flags);
    line("args", { args: a.slice(-10) });
    if (a.some(x => /^--max-budget-usd\b/.test(String(x)))) {
      await abort("--max-budget-usd in Claude Code's arguments");
      throw new Error("--max-budget-usd must not be passed");
    }
    return a;
  };
  // the prompt as the agent gets it on stdin, with the environment its process was started with
  const prompt0 = r.prompt;
  r.prompt = function (job, ...x) {
    const text = prompt0.call(this, job, ...x);
    promptN++;
    const env = (lastEnv && lastEnv.environment) || {};
    line("prompt", { n: promptN, kind: job && job.kind, annotate: !!(job && job.annotate), chars: String(text).length,
                     env: { SCHOLIUM_ZOTERO_PORT: env.SCHOLIUM_ZOTERO_PORT } });
    IOUtils.writeUTF8(PathUtils.join(OUT, `prompt-${promptN}.txt`), String(text)).catch(() => {});
    save().catch(() => {});
    return text;
  };

  const D = {}, C = {};
  await step("setup", async () => {
    const lib = Zotero.Libraries.userLibraryID;
    for (let i = 0; i < 60 && !Zotero.Libraries.get(lib).getDataLoaded("item"); i++) { try { await Zotero.Items.loadAll(lib); } catch (e) { await delay(500); } }
    const paper = CFG.paper;
    const item = new Zotero.Item(paper.itemType || "preprint");
    for (const [field, value] of Object.entries(paper.fields || {})) { try { item.setField(field, value); } catch (e) { line("fieldError", { field }); } }
    item.setCreators((paper.creators || []).map(([firstName, lastName]) => ({ firstName, lastName, creatorType: "author" })));
    await item.saveTx();
    D.item = item;
    D.att = await Zotero.Attachments.importFromFile({ file: CFG.pdf, parentItemID: item.id });   // a copy in the throwaway's storage
    const chainItem = new Zotero.Item("journalArticle");
    chainItem.setField("title", "Chain test (throwaway)");
    await chainItem.saveTx();
    C.item = chainItem;
    C.att = await Zotero.Attachments.importFromFile({ file: CFG.chainPdf, parentItemID: chainItem.id });
    line("items", { item: D.item.key, att: D.att.key, chainItem: C.item.key, chainAtt: C.att.key });
    const w = win();
    w.resizeTo(1500, 1000);
    for (const id of ["post-upgrade-container", "sync-reminder-container"]) { const bar = doc().getElementById(id); if (bar) bar.style.display = "none"; }
    await delay(1500);
    w.focus();
    await waitFor(() => w.ZoteroPane && w.ZoteroPane.itemsView && w.ZoteroPane.itemsView.initialized, 30000);
    await delay(2000);
  });
  if (!D.att || !C.att) { await abort("the items were not made"); return finish(); }

  // the chain test, run by live.py outside Zotero: no run unless it passed
  let chainOk = false;
  await step("chain", async () => {
    await IOUtils.writeUTF8(PathUtils.join(CFG.run, "chain-request.json"), JSON.stringify({ itemKey: D.item.key, attKey: D.att.key,
      chainItemKey: C.item.key, chainAttKey: C.att.key, chainPdf: await C.att.getFilePathAsync() }));
    let done = false;
    for (let i = 0; i < 300 && !done; i++) { done = await IOUtils.exists(PathUtils.join(CFG.run, "chain-done.json")); if (!done) await delay(1000); }
    const res = done ? JSON.parse(await IOUtils.readUTF8(PathUtils.join(CFG.run, "chain-done.json"))) : { ok: false };
    chainOk = !!res.ok && allAnns(C.att).length === 1;
    line("chain", { ok: !!res.ok, chainOk, annotations: allAnns(C.att).length });
    await C.item.eraseTx();
  });
  if (!chainOk) { await abort("the chain test failed: no real run"); return finish(); }

  // the chain test's --apply turned the eye button on for a user who never used it: back to a never-set preference
  if (CFG.openReader) await step("reset-eye", async () => {
    const T = Zotero.__scholiumToggle;
    const before = Zotero.Prefs.get(T.pref, true);
    try { Services.prefs.clearUserPref(T.pref); } catch (e) { line("clearError", { error: String(e) }); }
    T.shown = false;
    line("eyeReset", { prefBefore: before, prefNow: Zotero.Prefs.get(T.pref, true) === undefined ? "(unset)" : Zotero.Prefs.get(T.pref, true), shown: T.shown });
  });

  if (CFG.openReader) await step("reader-before", async () => {
    await selectItem(D);
    await openReader(D.att);
    try { reader._internalReader.toggleSidebar(true); } catch (e) {}
    await delay(2000);
    line("readerBefore", readerCounts());
    await shot("r1-reader-before");
    try { win().Zotero_Tabs.select("zotero-pane"); } catch (e) {}
    await delay(1500);
  });

  let box = null;
  const t0run = Date.now();
  await step("annotate", async () => {
    box = await selectItem(D);
    await showTab(box, "annot");
    if (CFG.extra) typeIn(q(box, ".scholium-input"), CFG.extra);
    await delay(400);
    await realClick(annotGo(box));
    const s = await started(30000);
    line("started", { started: !!s });
    let stopped = false;
    while (busy()) {
      if (!stopped && Date.now() - t0run > CFG.limitMin * 60000) { line("stop", { reason: "limit" }); try { r.cancel(); } catch (e) {} stopped = "limit"; }
      if (!stopped && CFG.maxMsgs) {
        const n = await apiMessages(D.att);
        if (n > CFG.maxMsgs) { line("stop", { reason: "messages", n }); try { r.cancel(); } catch (e) {} stopped = "messages"; }
      }
      if (!stopped && await stopAsked()) { line("stop", { reason: "usd" }); try { r.cancel(); } catch (e) {} stopped = "usd"; }
      await delay(3000);
    }
    await delay(3000);
    line("ended", { seconds: Math.round((Date.now() - t0run) / 1000), stopped, messages: await apiMessages(D.att) });
    line("card", { cards: cards(box), title: txt(q(box, ".scholium-card-title")), nums: qa(box, ".scholium-card-nums > div").map(txt), usage: txt(q(box, ".scholium-card-usage")) });
    await shot("a1-card", box);
    const anns = allAnns(D.att);
    const notes = Zotero.Items.get(D.item.getNotes()).filter(n => !n.deleted).map(n => ({ key: n.key, title: n.getNoteTitle(), tags: n.getTags().map(t => t.tag), html: n.getNote() }));
    await IOUtils.writeUTF8(PathUtils.join(OUT, "db.json"), JSON.stringify({ anns, notes }, null, 1));
    line("db", { byType: anns.reduce((m, a) => (m[a.type] = (m[a.type] || 0) + 1, m), {}), colors: anns.reduce((m, a) => (m[a.color] = (m[a.color] || 0) + 1, m), {}),
                 notes: notes.map(n => n.title) });
    line("final", { replies: await finalReply(D.att), prefAfter: Zotero.Prefs.get("extensions.scholium.showAnnotations", true) });
  });

  if (CFG.openReader) await step("reader-after", async () => {
    await Zotero.Reader.open(D.att.id);   // the tab that was open: no click on the eye button
    await delay(3500);
    line("readerAfter", readerCounts());
    await shot("r2-reader-after");
    try { win().Zotero_Tabs.select("zotero-pane"); } catch (e) {}
    await delay(1200);
  });

  if (CFG.chat && !(await stopAsked())) await step("chat", async () => {
    box = await selectItem(D);
    await showTab(box, "chat");
    typeIn(q(box, ".scholium-input"), CFG.chat);
    await delay(300);
    await realClick(q(box, ".scholium-round"));
    await started(30000);
    const t1 = Date.now();
    while (busy()) {
      if (Date.now() - t1 > CFG.limitMin * 60000 || await stopAsked()) { line("stop", { reason: "chat" }); try { r.cancel(); } catch (e) {} break; }
      await delay(2000);
    }
    await delay(2500);
    await shot("c1-chat", box);
    line("chatDone", { seconds: Math.round((Date.now() - t1) / 1000), replies: await finalReply(D.att) });
  });

  await step("logs", async () => {
    for (const f of await IOUtils.getChildren(r.convDir(D.att.key)).catch(() => [])) await IOUtils.copy(f, PathUtils.join(OUT, "conv-" + PathUtils.filename(f)));
  });
  return finish();
}
