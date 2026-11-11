/* Scholium smoke probe: a plugin that drives a THROWAWAY Zotero (started by scripts/smoke/smoke.py) through the checks
   its probe-config.json names, with a fake Claude Code, and writes what it saw to <shots>/facts.json after every step:
   a "result" line per check ({ check, pass, info }) and the details. It quits Zotero when it is done.

   Checks: section (the item pane's Scholium section, both tabs), localapi (Annotate with Zotero's local API off: the
   confirmation, then the run), signedout (a "not signed in" stream: the plugin's sentence, not Claude Code's),
   pymupdf (a run whose tool result says PyMuPDF is missing: the card), reselect (a paper selected again after another
   item shows its annotation session's card again), apply (the skill's CLI through /scholium/apply, run by smoke.py
   outside Zotero), reader (Ask Scholium in the reader's context menu), groups (a paper in a local group library: the
   one-time confirmation, a write with group_id, a group that is not editable), skill (Install the skill and retry), setup (the
   settings page's setup check, with the real claude and codex found by the plugin), copy (the setup check's Copy puts
   its lines on the clipboard, which is restored afterwards).

   Screenshots are drawn from Zotero's own windows (drawSnapshot), never from the screen. */
var CFG, OUT;
const Ci = Components.interfaces;
const Cu = Components.utils;
const Cc = Components.classes;
const HTML = "http://www.w3.org/1999/xhtml";
const delay = ms => Zotero.Promise.delay(ms);
const t0 = Date.now();
const facts = [];

function line(what, data) { facts.push(Object.assign({ t: Date.now() - t0, what }, data || {})); }
function result(check, pass, info) { line("result", { check, pass: !!pass, info: info || {} }); }
async function save() {
  await IOUtils.writeUTF8(PathUtils.join(OUT, "facts.json"), "[\n" + facts.map(l => JSON.stringify(l)).join(",\n") + "\n]\n");
}
function install() {}
function uninstall() {}
function shutdown() {}
function startup() {
  const prof = Services.dirsvc.get("ProfD", Ci.nsIFile).path;
  IOUtils.readUTF8(PathUtils.join(PathUtils.parent(prof), "probe-config.json")).then(t => {
    CFG = JSON.parse(t);
    OUT = CFG.shots;
    return main();
  }).catch(async e => {
    line("fatal", { error: String(e), stack: String(e && e.stack).slice(0, 1500) });
    try { await save(); } catch (e2) {}
    Services.startup.quit(Ci.nsIAppStartup.eForceQuit);
  });
}

const r1 = x => Math.round(x * 10) / 10;
const R = () => Zotero.__scholium;
const win = () => Zotero.getMainWindow();
const doc = () => win().document;
const txt = el => el ? el.textContent.replace(/\s+/g, " ").trim() : null;

async function waitFor(test, ms, every = 200) {
  for (let t = 0; t < ms; t += every) {
    let v = null;
    try { v = test(); } catch (e) {}
    if (v) return v;
    await delay(every);
  }
  try { return test(); } catch (e) { return null; }
}
async function step(name, fn) {
  line("step", { name });
  try { await fn(); }
  catch (e) {
    line("error", { step: name, error: String(e), stack: String(e && e.stack).slice(0, 900) });
    if (CFG.checks.includes(name) && !facts.some(f => f.what === "result" && f.check === name)) result(name, false, { error: String(e) });
  }
  await save();
}

// ---- screenshots: drawSnapshot of Zotero's own windows ----
async function snap(w, rectArg, scale) {
  const bmp = await w.browsingContext.currentWindowGlobal.drawSnapshot(rectArg, scale, "white");
  const canvas = w.document.createElementNS(HTML, "canvas");
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  canvas.getContext("2d").drawImage(bmp, 0, 0);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  return new Uint8Array(await blob.arrayBuffer());
}
function scroller(box) { try { return box.closest("item-details")._paneParent; } catch (e) { return null; } }
async function shot(name, box = null, w = win()) {
  await IOUtils.write(PathUtils.join(OUT, name + ".png"), await snap(w, null, 1));
  const files = [name + ".png"];
  box = fresh(box);
  if (box) {
    const sc = scroller(box);
    const left = Math.max(0, (sc ? sc.getBoundingClientRect().left : box.getBoundingClientRect().left) - 12);
    await IOUtils.write(PathUtils.join(OUT, name + "-pane.png"), await snap(w, new w.DOMRect(left, 0, w.innerWidth - left, w.innerHeight), 2));
    files.push(name + "-pane.png");
  }
  line("shot", { files });
}

// ---- input ----
function mouse(w, type, x, y, buttons = 0, clicks = 1) { w.windowUtils.sendMouseEvent(type, x, y, 0, clicks, 0, false, 0, 1, false, false, buttons); }
async function realClick(el, w = win()) {
  el.scrollIntoView({ block: "nearest" });
  await delay(150);
  const b = el.getBoundingClientRect(), x = b.left + b.width / 2, y = b.top + b.height / 2;
  mouse(w, "mousemove", x, y);
  await delay(60);
  mouse(w, "mousedown", x, y, 1);
  await delay(60);
  mouse(w, "mouseup", x, y, 0);
  await delay(300);
}
function typeIn(input, text) {
  input.focus();
  input.value = text;
  input.dispatchEvent(new (input.ownerGlobal.InputEvent)("input", { bubbles: true, inputType: "insertText", data: text }));
}

// ---- the clipboard (the system's: what was on it is put back) ----
function readClipboard() {
  try {
    const cb = Services.clipboard;
    if (!cb.hasDataMatchingFlavors(["text/plain"], cb.kGlobalClipboard)) return { text: null };
    const trans = Cc["@mozilla.org/widget/transferable;1"].createInstance(Ci.nsITransferable);
    trans.init(null);
    trans.addDataFlavor("text/plain");
    try { cb.getData(trans, cb.kGlobalClipboard); }
    catch (e) { cb.getData(trans, cb.kGlobalClipboard, win().browsingContext.currentWindowContext); }
    const data = {};
    trans.getTransferData("text/plain", data);
    return { text: data.value.QueryInterface(Ci.nsISupportsString).data };
  } catch (e) { return { text: null, error: String(e) }; }
}
function restoreClipboard(saved) {
  try {
    if (saved && saved.text != null) {
      Cc["@mozilla.org/widget/clipboardhelper;1"].getService(Ci.nsIClipboardHelper).copyString(saved.text);
      return "text restored";
    }
    Services.clipboard.emptyClipboard(Services.clipboard.kGlobalClipboard);
    return "emptied (it held no text)";
  } catch (e) { return "not restored: " + e; }
}

// ---- dialogs and console ----
const dialogs = [];
function acceptDialogs() {
  const take = d => {
    const dlg = d && d.querySelector && d.querySelector("dialog");
    if (!dlg || !/commonDialog/.test(String(d.documentURI))) return;
    const text = txt(d.getElementById("infoBody")) || txt(dlg);
    if (!text) return;   // not laid out yet
    dialogs.push({ t: Date.now() - t0, title: d.title, text });
    line("dialog", { title: d.title, text });
    try { dlg.getButton("accept").click(); } catch (e) { try { dlg.acceptDialog(); } catch (e2) { line("dialogError", { error: String(e2) }); } }
  };
  try { for (const w of Services.wm.getEnumerator(null)) take(w.document); } catch (e) {}
  try { for (const f of win().document.querySelectorAll("browser, iframe")) { try { take(f.contentDocument); } catch (e) {} } } catch (e) {}
}
let watching = true;
const errors = [];
function listenErrors() {
  Services.console.registerListener({
    observe(m) {
      try {
        if (!(m instanceof Ci.nsIScriptError) || (m.flags & 1)) return;
        const s = String(m.errorMessage || m.message || m), src = String(m.sourceName || "");
        if (/scholium-smokeprobe/.test(src)) return;
        if (/scholium|settings\.js/i.test(s + " " + src)) errors.push({ t: Date.now() - t0, e: s.slice(0, 400), at: src.slice(-70) + ":" + (m.lineNumber || "") });
      } catch (e) {}
    }
  });
}

// ---- items and the section ----
const items = {};
async function makeItem(tag, title) {
  const item = new Zotero.Item("journalArticle");
  item.setField("title", title);
  item.setField("date", "2026");
  item.setCreators([{ firstName: "Smoke", lastName: "Tester", creatorType: "author" }]);
  await item.saveTx();
  const att = await Zotero.Attachments.importFromFile({ file: CFG.pdf, parentItemID: item.id });
  items[tag] = { item, att };
  return items[tag];
}
function boxes() { return [...doc().querySelectorAll(".scholium-pane")]; }
function paneOf(box) { for (const p of R().panes.values()) if (p.box === box) return p; return null; }
const q = (box, sel) => box.querySelector(sel);
const qa = (box, sel) => [...box.querySelectorAll(sel)];
async function toSection(inReader) {
  const sections = [...doc().querySelectorAll("item-pane-custom-section")].filter(s => s.dataset.pane === R().paneID);
  const s = sections.find(x => !x.closest("#zotero-item-pane") === inReader && x.checkVisibility());
  if (!s) throw new Error("no Scholium section " + (inReader ? "in the reader" : "in the library") + " (" + sections.length + " found)");
  await Promise.race([s.closest("item-details").scrollToPane(R().paneID, "instant"), delay(3000)]);
  return waitFor(() => {
    const b = s.querySelector(".scholium-pane");
    if (!b || !b.isConnected) return null;
    b.__probeInReader = !!inReader;   // where fresh() looks for the section drawn anew
    return b;
  }, 8000);
}
// the section's element as it is now: Zotero 7 draws the section anew (after a redo's Replace deleted the annotations,
// say), and the element a step holds is then out of the document, its rectangle empty, so drawSnapshot of it fails and
// its cards are the old ones. The visible section of the same place, the library's item pane or a reader's, replaces it
function fresh(box) {
  if (!box || (box.isConnected && box.getBoundingClientRect().width > 0)) return box;
  const inReader = !!box.__probeInReader;
  return boxes().find(b => b.isConnected && b.checkVisibility() && !b.closest("#zotero-item-pane") === inReader) || box;
}
async function selectItem(it) {
  const w = win();
  try { await w.ZoteroPane.selectItem(it.att.id); } catch (e) {}
  await delay(500);
  try { await w.ZoteroPane.selectItem(it.item.id); } catch (e) { line("selectError", { error: String(e) }); }
  await delay(800);
  if (!w.ZoteroPane.getSelectedItems().some(i => i.id === it.item.id)) {
    try { await w.ZoteroPane.itemsView.selectItem(it.item.id); } catch (e) { line("selectError2", { error: String(e) }); }   // Zotero 7 right after start
    await delay(800);
  }
  await delay(1200);
  const box = await toSection(false);
  await delay(1000);
  return box;
}
const busy = () => { const r = R(); return !!r.job || r.queue.some(j => !r.isHeld(j)); };
async function started(ms = 30000) { return waitFor(() => R().job, ms, 100); }
async function settle(ms = 90000) { await delay(800); return waitFor(() => !busy(), ms, 300); }
async function script(name) { await IOUtils.writeUTF8(PathUtils.join(CFG.fake, "next.txt"), name); }
async function fakeCalls() {
  const out = [];
  for (const f of (await IOUtils.getChildren(PathUtils.join(CFG.fake, "calls")).catch(() => [])).sort()) {
    out.push(PathUtils.filename(f) + ":" + (await IOUtils.readUTF8(f).catch(() => "")).split("\n")[0]);
  }
  return out;
}
function tabs(box) { const t = qa(box, ".scholium-tab"); return { chat: t[0], annot: t[1], labels: t.map(txt) }; }
async function showTab(box, which) {
  const t = tabs(box);
  await realClick(which === "chat" ? t.chat : t.annot);
  await delay(800);
  return paneOf(box) && paneOf(box).tab;
}
function annotGo(box) { const p = paneOf(box); return (p && p.annotGo) || q(box, ".scholium-send-row .scholium-button.primary"); }
function cards(box) {
  box = fresh(box);
  return qa(box, ".scholium-card").map(c => ({ cls: c.className, title: txt(c.querySelector(".scholium-card-title")) || txt(c.firstElementChild),
                                               text: txt(c).slice(0, 300), buttons: [...c.querySelectorAll("button")].map(b => txt(b) || b.title) }));
}
async function annotateHere(box, scriptName) {
  await script(scriptName);
  const go = annotGo(box);
  await realClick(go);
  const s = await started(20000);
  await settle(90000);
  await delay(2000);
  return !!s;
}
async function listFiles(root) {
  const out = [];
  const walk = async d => { for (const c of await IOUtils.getChildren(d).catch(() => [])) { if ((await IOUtils.stat(c)).type === "directory") await walk(c); else out.push(c.slice(root.length + 1).replace(/\\/g, "/")); } };
  await walk(root);
  return out.sort();
}

// ---- the reader ----
let reader = null;
const pv = () => reader._internalReader._primaryView;
const pw = () => pv()._iframeWindow;
async function openReader(att) {
  reader = await Zotero.Reader.open(att.id);
  await reader._initPromise;
  await waitFor(() => { const app = pw().PDFViewerApplication; return app && app.pdfViewer && app.pdfViewer.pagesCount >= 2 && pw().document.querySelector(".page .textLayer span"); }, 30000);
  await delay(1500);
}
async function dragOver(pageIndex, startText, endText) {
  const d = Cu.unwaiveXrays(pw()).document;
  const spans = [...d.querySelectorAll(`.page[data-page-number="${pageIndex + 1}"] .textLayer span`)];
  const a = spans.find(s => s.textContent.includes(startText)), b = spans.find(s => s.textContent.includes(endText));
  if (!a || !b) throw new Error("passage not found on page " + (pageIndex + 1));
  const charBox = (span, at) => {
    const node = [...span.childNodes].find(n => n.nodeType === 3 && n.textContent.length > at) || span.firstChild;
    const r = d.createRange(); r.setStart(node, at); r.setEnd(node, at + 1); return r.getBoundingClientRect();
  };
  const ra = charBox(a, a.textContent.indexOf(startText)), rb = charBox(b, b.textContent.indexOf(endText) + endText.length - 1);
  const start = [ra.left + ra.width * 0.3, ra.top + ra.height / 2], end = [rb.right + 3, rb.top + rb.height / 2];
  const W = Cu.unwaiveXrays(pw());
  const send = (type, x, y, buttons, clicks = 1) => W.windowUtils.sendMouseEvent(type, x, y, 0, clicks, 0, false, 0, 1, false, false, buttons);
  send("mousemove", start[0], start[1], 0, 0);
  send("mousedown", start[0], start[1], 1);
  for (let i = 1; i <= 10; i++) { send("mousemove", start[0] + (end[0] - start[0]) * i / 10, start[1] + (end[1] - start[1]) * i / 10, 1, 0); await delay(50); }
  send("mouseup", end[0], end[1], 0);
  await delay(1200);
  return { selection: String(W.getSelection()).trim().slice(0, 120), at: [r1(ra.left + 12), r1(ra.top + ra.height / 2)] };
}
function openMenus() {
  const out = [];
  for (const w of Services.wm.getEnumerator(null)) {
    for (const p of w.document.querySelectorAll("menupopup")) {
      if (p.state !== "open" && p.state !== "showing") continue;
      out.push({ popup: p, items: [...p.children].map(c => c.localName === "menuseparator" ? "—" : (c.getAttribute("label") || c.label || "")) });
    }
  }
  return out;
}
async function contextMenuAt(x, y) {
  const W = Cu.unwaiveXrays(pw());
  W.windowUtils.sendMouseEvent("mousedown", x, y, 2, 1, 0, false, 0, 1, false, false, 2);
  W.windowUtils.sendMouseEvent("mouseup", x, y, 2, 1, 0, false, 0, 1, false, false, 0);
  W.windowUtils.sendMouseEvent("contextmenu", x, y, 2, 1, 0, false, 0, 1, false, false, 0);
  let menus = await waitFor(() => { const m = openMenus(); return m.length ? m : null; }, 3000);
  if (!menus) {   // the view's own entry to its menu, as a right click calls it
    const v = pv(), open = v._onOpenViewContextMenu || (v._options && v._options.onOpenViewContextMenu);
    try { open.call(v, { x, y }); } catch (e) { line("menuOpenError", { error: String(e) }); }
    menus = await waitFor(() => { const m = openMenus(); return m.length ? m : null; }, 3000);
  }
  return menus || [];
}

// ---- the checks ----
// what a check expects, in the plugin's own words for the running locale (so that the checks follow its wording); the
// checks add what does not depend on the wording
let EXPECTED = null;
function expected() {
  if (EXPECTED) return EXPECTED;
  const r = R(), t = (key, ...args) => { try { return r.text(key, ...args); } catch (e) { return null; } };
  EXPECTED = { localApiOff: t("localApiOff"), signedOut: t("notSignedIn", "claude"), pymupdfCard: t("annotNoneWarn", t("pymupdfMissing")),
               askLabel: t("askScholium"), installSkill: t("installSkill"), skillNotCarried: t("skillNotCarried"),
               localApiName: t("checkLabel", "localApi"), claudeSkillName: t("checkLabel", "claudeSkill"), question: CFG.question,
               groupFirst: t("groupFirst"), groupReadOnly: t("groupReadOnly") };
  line("expected", EXPECTED);
  return EXPECTED;
}
const E = expected;
const CHECKS = {
  async section() {
    const box = await selectItem(items.A);
    const t = tabs(box);
    await showTab(box, "chat");
    await shot("section-chat", box);
    const tab = await showTab(box, "annot");
    const intro = txt(q(box, ".scholium-annot-intro"));
    await shot("section-annotations", box);
    result("section", t.labels.length === 2 && tab === "annotate" && !!intro, { tabs: t.labels, annotationsIntro: intro, annotateButton: txt(annotGo(box)) });
  },

  async localapi() {
    const box = await selectItem(items.A);
    await showTab(box, "annot");
    const before = Zotero.Prefs.get("httpServer.localAPI.enabled");
    const n = dialogs.length;
    const ran = await annotateHere(box, "annotate-ok");
    const asked = dialogs.slice(n).map(d => d.text);
    const after = Zotero.Prefs.get("httpServer.localAPI.enabled");
    const c = cards(box);
    await shot("localapi-card", box);
    result("localapi", before === false && asked.some(t => t === E().localApiOff && /API/.test(t)) && after === true && ran && c.length > 0,
           { before, after, dialog: asked, started: ran, card: c.map(x => x.title) });
  },

  async signedout() {
    const box = await selectItem(items.B);
    await showTab(box, "annot");
    await annotateHere(box, "signedout");
    const annot = cards(box).map(x => x.title);
    const annotText = txt(box);
    await shot("signedout-annotations", box);
    await showTab(box, "chat");
    await script("signedout");
    typeIn(q(box, ".scholium-input"), E().question);
    await delay(300);
    await realClick(q(box, ".scholium-round"));
    await started(20000);
    await settle(60000);
    await delay(1500);
    const finals = qa(box, ".scholium-entry.final, .scholium-entry.error").map(txt);
    const chatText = txt(box);
    await shot("signedout-chat", box);
    result("signedout", annot.includes(E().signedOut) && finals.includes(E().signedOut) && !/Please run \/login/.test(annotText + chatText),
           { annotationsCard: annot, chatFinal: finals, showsLogin: /Please run \/login/.test(annotText + chatText) });
  },

  async pymupdf() {
    const box = await selectItem(items.C);
    await showTab(box, "annot");
    await annotateHere(box, "pymupdf");
    const c = cards(box).map(x => x.title);
    await shot("pymupdf-card", box);
    result("pymupdf", c.includes(E().pymupdfCard) && c.some(x => /PyMuPDF/.test(x)), { card: c, expected: E().pymupdfCard });
  },

  async reselect() {
    const it = items.R, other = items.O;
    const box = await selectItem(it);
    await showTab(box, "annot");
    await annotateHere(box, "annotate-ok");
    const before = cards(box).map(x => x.title);
    const w = win();
    const libDetails = () => [...doc().querySelectorAll("item-details")].find(d => d.closest("#zotero-item-pane"));
    // another item whose Scholium section stays off-screen (the case in which the card did not come back before)
    await w.ZoteroPane.selectItem(other.item.id);
    await delay(1500);
    try { libDetails()._paneParent.scrollTo(0, 0); } catch (e) {}
    await delay(500);
    await w.ZoteroPane.selectItem(it.item.id);
    await delay(500);
    const start = Date.now();
    let seen = null, scrolled = false, last = null;
    for (let i = 0; i < 40 && !seen; i++) {   // 8 s: the user scrolls to the section, the card must come back
      const s = [...doc().querySelectorAll("item-pane-custom-section")].find(x => x.dataset.pane === R().paneID && x.closest("#zotero-item-pane"));
      if (s && !scrolled) { try { s.closest("item-details").scrollToPane(R().paneID, "instant"); scrolled = true; } catch (e) {} }
      const b = s && s.querySelector(".scholium-pane"), p = b && paneOf(b), c = b && b.querySelector(".scholium-card");
      last = { tab: p && p.tab, item: p && p.item && p.item.key, intro: b && txt(q(b, ".scholium-annot-intro")) };
      if (c && c.checkVisibility() && p && p.item && p.item.id === it.item.id) seen = { ms: Date.now() - start, card: txt(c.querySelector(".scholium-card-title")) || txt(c.firstElementChild), tab: p.tab };
      else await delay(200);
    }
    const b = boxes().find(x => x.closest("#zotero-item-pane"));
    if (b) await shot("reselect-after", b);
    result("reselect", before.length > 0 && !!seen, { cardBefore: before, cardAfter: seen, last });
  },

  async apply() {
    const D = items.D;
    const notes = () => Zotero.Items.get(D.item.getNotes()).filter(n => !n.deleted);
    const anns = () => D.att.getAnnotations().map(a => ({ type: a.annotationType, color: a.annotationColor, text: (a.annotationText || "").slice(0, 50) }));
    await IOUtils.writeUTF8(PathUtils.join(CFG.run, "cli-request.json"),
      JSON.stringify({ pdf: await D.att.getFilePathAsync(), item_key: D.item.key, attachment_key: D.att.key }));
    let done = false;
    for (let i = 0; i < 300 && !done; i++) { done = await IOUtils.exists(PathUtils.join(CFG.run, "cli-done.json")); if (!done) await delay(1000); }
    const cli = done ? JSON.parse(await IOUtils.readUTF8(PathUtils.join(CFG.run, "cli-done.json"))) : { error: "no answer from smoke.py" };
    const a = anns(), n = notes();
    const lower = a.length > 0 && a.every(x => /^#[0-9a-f]{6}$/.test(x.color));
    const run1 = cli.run1 || {}, run2 = cli.run2 || {};
    const pass = run1.applied === true && lower && n.length === 1 && a.length === 2 && run2.applied === false && /500|Invalid sortIndex/.test(String(run2.apply_error || ""));
    result("apply", pass, { run1: { applied: run1.applied, backend: run1.backend, colors: run1.colors }, run2: { applied: run2.applied, error: run2.apply_error },
                            zotero: { annotations: a, notes: n.map(x => x.getNoteTitle()) }, cliError: cli.error || null });
    const box = await selectItem(D);
    await showTab(box, "annot");
    await shot("apply-after", box);
  },

  async reader() {
    const D = items.D;
    const box = await selectItem(D);
    await showTab(box, "chat");
    await openReader(D.att);
    await reader.navigate({ pageIndex: 1 });
    await delay(1500);
    await toSection(true).catch(() => null);
    const drag = await dragOver(1, "The protocol selects a passage", "records the answer");
    const menus = await contextMenuAt(drag.at[0], drag.at[1]);
    const ask = menus.flatMap(m => [...m.popup.children]).find(c => (c.getAttribute("label") || "") === E().askLabel);
    const items2 = menus.map(m => m.items);
    if (!ask) {
      for (const m of menus) try { m.popup.hidePopup(); } catch (e) {}
      result("reader", false, { selection: drag.selection, menus: items2 });
      return;
    }
    const popup = ask.closest("menupopup");
    ask.doCommand();
    try { popup.hidePopup(); } catch (e) {}
    await delay(2000);
    const rb = boxes().find(b => !b.closest("#zotero-item-pane") && b.checkVisibility());
    const p = rb && paneOf(rb);
    const strip = rb && txt(q(rb, ".scholium-quote"));
    if (rb) await shot("reader-asked", rb);
    result("reader", !!p && p.tab === "chat" && !!p.quote && !!strip && strip.includes("The protocol selects a passage"),
           { selection: drag.selection, menuItem: ask.getAttribute("label"), menus: items2, tab: p && p.tab, quote: strip });
  },

  async groups() {
    // a local group library, as Zotero's own tests make one (no sync: the throwaway has no account)
    const g = new Zotero.Group();
    g.id = 9100001;
    g.name = "Smoke group";
    g.description = "";
    g.version = 0;
    g.editable = true;
    g.filesEditable = true;
    await g.saveTx();
    try { await Zotero.Items.loadAll(g.libraryID); } catch (e) {}
    const item = new Zotero.Item("journalArticle");
    item.libraryID = g.libraryID;
    item.setField("title", "Smoke group paper");
    await item.saveTx();
    const att = await Zotero.Attachments.importFromFile({ file: CFG.pdf, parentItemID: item.id, libraryID: g.libraryID });
    const it = { item, att };
    const step = async (name, body) => {   // the runner's CLI step, through cli-request-<name>.json
      await IOUtils.writeUTF8(PathUtils.join(CFG.run, `cli-request-${name}.json`), JSON.stringify(body));
      let done = false;
      for (let i = 0; i < 300 && !done; i++) { done = await IOUtils.exists(PathUtils.join(CFG.run, `cli-done-${name}.json`)); if (!done) await delay(1000); }
      return done ? JSON.parse(await IOUtils.readUTF8(PathUtils.join(CFG.run, `cli-done-${name}.json`))) : { error: "no answer from smoke.py" };
    };
    try { await win().ZoteroPane.collectionsView.selectLibrary(g.libraryID); } catch (e) {}
    await delay(1500);
    let box = await selectItem(it);
    const tabsOk = tabs(box).labels.length === 2;
    await showTab(box, "annot");
    const n0 = dialogs.length;
    const ran1 = await annotateHere(box, "annotate-ok");
    const first = dialogs.slice(n0).map(d => d.text);
    const n1 = dialogs.length;
    const ran2 = await annotateHere(box, "annotate-ok");
    const second = dialogs.slice(n1).map(d => d.text);
    await shot("groups-annotated", box);
    const pdf = await att.getFilePathAsync();
    const written = await step("groups-apply", { kind: "apply", pdf, item_key: item.key, attachment_key: att.key, group_id: g.id });
    const anns = att.getAnnotations().map(a => ({ lib: a.libraryID, color: a.annotationColor }));
    // a group whose library the user cannot edit
    g.editable = false;
    await g.saveTx();
    box = await selectItem(it);
    await showTab(box, "annot");
    await delay(800);
    const state = txt(q(box, ".scholium-state")), go = annotGo(box);
    await shot("groups-readonly", box);
    const refused = await step("groups-readonly", { kind: "readonly", pdf, item_key: item.key, attachment_key: att.key, group_id: g.id });
    const after = att.getAnnotations().length;
    g.editable = true;
    await g.saveTx();
    const w = written.apply || {}, l = written.list || {}, r = refused.apply || {};
    result("groups", tabsOk && ran1 && ran2 && first.length === 1 && first[0] === E().groupFirst && second.length === 0
                     && w.applied === true && anns.length === 2 && anns.every(a => a.lib === g.libraryID && /^#[0-9a-f]{6}$/.test(a.color))
                     && l.status === 200 && l.json && l.json.libraryID === g.libraryID
                     && state === E().groupReadOnly && !!go && go.disabled && r.applied === false && /cannot edit/.test(String(r.apply_error || "")) && after === 2,
           { libraryID: g.libraryID, confirmation: first, again: second, started: [ran1, ran2], write: { applied: w.applied, error: w.apply_error },
             annotations: anns, list: l, readOnly: { state, annotateDisabled: !!go && go.disabled, write: { applied: r.applied, error: r.apply_error }, annotationsAfter: after } });
  },

  async skill() {
    const box = await selectItem(items.S);
    await showTab(box, "annot");
    await annotateHere(box, "noskill");
    const card = q(box, ".scholium-card.failed");
    const button = card && [...card.querySelectorAll("button")].find(b => txt(b) === E().installSkill);
    const before = { card: card && txt(card.firstElementChild), button: !!button, calls: await fakeCalls() };
    await shot("skill-card", box);
    if (!button) { result("skill", false, before); return; }
    await script("annotate-ok");
    const callsBefore = (await fakeCalls()).length;
    await realClick(button);
    const hints = [];
    for (let i = 0; i < 12; i++) { const h = txt(q(box, ".scholium-hint")); if (h && !hints.includes(h)) hints.push(h); await delay(150); }
    const again = await started(15000);
    await settle(60000);
    await delay(1500);
    const calls = (await fakeCalls()).slice(callsBefore);
    const files = (await listFiles(CFG.claudeConfig)).filter(f => f.startsWith("skills/zotero-scholium/"));
    await shot("skill-after", box);
    const info = Object.assign(before, { secondRun: !!again, newCalls: calls, hints, installed: files });
    if (CFG.skillCarried) result("skill", !!again && calls.some(c => /annotate-ok/.test(c)) && files.length === CFG.skillFileCount, info);
    else result("skill", !again && files.length === 0 && hints.includes(E().skillNotCarried), info);
  },

  async setup() {
    const r = R();
    Zotero.Utilities.Internal.openPreferences(r.prefPaneID);
    const PW = await waitFor(() => Services.wm.getMostRecentWindow("zotero:pref"), 20000);
    if (!PW) throw new Error("no settings window");
    try { PW.resizeTo(1000, 1100); } catch (e) {}
    const run = await waitFor(() => PW.document.getElementById("scholium-check-run"), 30000);
    if (!run) throw new Error("no setup check on the settings page");
    await delay(2500);
    const rows = () => [...(PW.document.getElementById("scholium-check-lines") || { children: [] }).children];
    const lineOf = row => { const k = [...row.children]; const b = k.find(x => x.localName === "button");
                            return { mark: k[0] && k[0].textContent, name: k[1] && k[1].textContent, text: k[2] && k[2].textContent, button: b ? b.getAttribute("label") : null }; };
    const lines = () => rows().map(lineOf);
    const ended = async () => {
      await waitFor(() => run.disabled || rows().some(x => !x.hasAttribute("data-old")), 8000, 50);
      return waitFor(() => !run.disabled && rows().length && rows().every(x => !x.hasAttribute("data-old")), 120000, 250);
    };
    const markOld = () => { for (const x of rows()) x.setAttribute("data-old", "1"); };
    const click = async el => { el.scrollIntoView({ block: "center" }); await delay(300); await realClick(el, PW); };
    const byName = name => rows().find(x => (x.children[1] && x.children[1].textContent) === name);
    const pshot = async name => { run.scrollIntoView({ block: "start" }); await delay(400); await IOUtils.write(PathUtils.join(OUT, name + ".png"), await snap(PW, null, 1)); line("shot", { files: [name + ".png"] }); };
    line("setup.found", { claude: PW.document.getElementById("scholium-claude-path") && PW.document.getElementById("scholium-claude-path").placeholder,
                          codex: PW.document.getElementById("scholium-codex-path") && PW.document.getElementById("scholium-codex-path").placeholder });
    await click(run);
    const first = await ended();
    const firstLines = lines();
    await pshot("setup-checked");
    // Copy: the lines with the versions on the clipboard; what was on it is put back
    if (CFG.checks.includes("copy")) {
      const copy = PW.document.getElementById("scholium-check-copy");
      const head = `Scholium ${R().version} · Zotero ${Zotero.version}`;
      const saved = readClipboard();
      let copied = null, error = null, restored = null;
      try {
        if (copy && !copy.hidden) { await click(copy); await delay(800); copied = readClipboard(); }
      } catch (e) { error = String(e); }
      finally { restored = restoreClipboard(saved); }
      const text = copied && copied.text;
      result("copy", !!text && text.startsWith(head) && text.split("\n").length >= firstLines.length + 1,
             { button: copy ? { hidden: copy.hidden, label: copy.label || copy.getAttribute("label") } : null, head,
               copied: text ? text.slice(0, 400) : null, lines: text ? text.split("\n").length : 0, restored, error, readError: copied && copied.error });
    }
    // the local API line's button turns it on, and the check runs again
    let apiOk = false;
    const apiRow = byName(E().localApiName), apiButton = apiRow && [...apiRow.children].find(x => x.localName === "button");
    if (apiButton) {
      markOld();
      await click(apiButton);
      const pref = await waitFor(() => Zotero.Prefs.get("httpServer.localAPI.enabled"), 5000);
      await ended();
      const row = byName(E().localApiName);
      apiOk = !!pref && !!row && lineOf(row).mark === "✓";
    }
    // the Claude Code skill line's button installs the skill the package carries, and the check runs again
    let skillOk = false, skillLine = null;
    const skRow = byName(E().claudeSkillName), skButton = skRow && [...skRow.children].find(x => x.localName === "button");
    if (skButton) {
      markOld();
      await click(skButton);
      await ended();
      const row = byName(E().claudeSkillName);
      skillLine = row && lineOf(row);
      skillOk = CFG.skillCarried ? !!skillLine && skillLine.mark === "✓" : !!skillLine && skillLine.text === E().skillNotCarried;
    }
    const finalLines = lines();
    await pshot("setup-after-fixes");
    try { PW.close(); } catch (e) {}
    result("setup", !!first && firstLines.length >= 5 && apiOk && skillOk, { first: firstLines, after: finalLines, apiOk, skillOk, skillLine });
  },
};

async function main() {
  await Zotero.initializationPromise;
  listenErrors();
  (async () => { while (watching) { try { acceptDialogs(); } catch (e) {} await delay(300); } })();
  const ok = await waitFor(() => Zotero.__scholium && Zotero.__scholium.paneID, 60000);
  line("start", { zotero: Zotero.version, plugin: R() && R().version, locale: Zotero.locale, checks: CFG.checks,
                  localAPI: Zotero.Prefs.get("httpServer.localAPI.enabled"), claudeSkills: R() && R().skillsDir("claude") });
  if (!ok) { for (const c of CFG.checks) result(c, false, { error: "the plugin did not start" }); return finish(); }
  // a skill install may only go to this run's folder
  if (R().skillsDir("claude") !== PathUtils.join(CFG.claudeConfig, "skills")) {
    for (const c of CFG.checks) result(c, false, { error: "CLAUDE_CONFIG_DIR is not the run's: " + R().skillsDir("claude") });
    return finish();
  }
  await step("setup-items", async () => {
    const lib = Zotero.Libraries.userLibraryID;
    for (let i = 0; i < 60 && !Zotero.Libraries.get(lib).getDataLoaded("item"); i++) {
      try { await Zotero.Items.loadAll(lib); } catch (e) { await delay(500); }   // /api/ requests wait for this
    }
    const need = { A: ["section", "localapi"], B: ["signedout"], C: ["pymupdf"], R: ["reselect"], O: ["reselect"], D: ["apply", "reader"], S: ["skill"] };
    for (const [tag, uses] of Object.entries(need)) if (uses.some(c => CFG.checks.includes(c))) await makeItem(tag, "Smoke " + tag + ": " + uses.join(", "));
    const w = win();
    w.resizeTo(1500, 1000);
    for (const id of ["post-upgrade-container", "sync-reminder-container"]) { const bar = doc().getElementById(id); if (bar) bar.style.display = "none"; }
    await delay(1500);
    w.focus();
    await waitFor(() => w.ZoteroPane && w.ZoteroPane.itemsView && w.ZoteroPane.itemsView.initialized, 30000);
    await delay(2500);
  });
  for (const name of ["section", "localapi", "signedout", "pymupdf", "reselect", "apply", "reader", "groups", "skill", "setup"]) {
    if (CFG.checks.includes(name)) await step(name, CHECKS[name]);
  }
  return finish();
}
async function finish() {
  watching = false;
  try {
    const all = Services.console.getMessageArray() || [];
    const hits = all.filter(m => m instanceof Ci.nsIScriptError && !(m.flags & 1) && /scholium|settings\.js/i.test(String(m.errorMessage) + " " + String(m.sourceName))
                             && !/scholium-smokeprobe/.test(String(m.sourceName)))
      .map(m => ({ e: String(m.errorMessage).slice(0, 400), at: String(m.sourceName).slice(-70) + ":" + m.lineNumber }));
    for (const h of hits) if (!errors.some(x => x.e === h.e)) errors.push(h);
  } catch (e) {}
  line("errors", { errors });
  try { await IOUtils.writeUTF8(PathUtils.join(CFG.run, "zotero-debug-store.txt"), await Zotero.Debug.get()); } catch (e) {}
  line("done", {});
  await save();
  await delay(500);
  Services.startup.quit(Ci.nsIAppStartup.eForceQuit);
}
