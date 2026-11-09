// the Scholium page of Zotero's settings: the buttons that choose an agent's program, and the setup check
{
  const browse = async (pref, title) => {
    const { FilePicker } = ChromeUtils.importESModule("chrome://zotero/content/modules/filePicker.mjs");
    const fp = new FilePicker();
    fp.init(window, document.l10n ? await document.l10n.formatValue(title) : "", fp.modeOpen);
    fp.appendFilters(fp.filterAll);   // the claude and codex executables are no app bundles
    if (await fp.show() === fp.returnOK) Zotero.Prefs.set("extensions.scholium." + pref, fp.file, true);
  };
  // the setup check: a line per check as it ends (its mark, its name, a sentence, and its action's button); an action
  // done runs the check again, one not done shows why in place of the sentence
  const MARKS = { ok: "✓", bad: "✗", unknown: "–" };
  // the marks' green and red at least 3:1 on the page's ground, in the light and the dark theme
  const COLOURS = { light: { ok: "#1d8746", bad: "#c42131" }, dark: { ok: "#4cd27f", bad: "#ff7b84" } };
  const dark = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const marks = [];   // [mark, state] of the lines shown
  const paintMark = (mark, state) => {
    const colour = COLOURS[dark && dark.matches ? "dark" : "light"][state] || "var(--fill-secondary)";
    mark.setAttribute("style", "color: " + colour + "; font-weight: 600; min-width: 1.2em");
  };
  if (dark && typeof dark.addEventListener === "function") dark.addEventListener("change", () => { for (const [m, s] of marks) paintMark(m, s); });
  let checking = false, again = false, shown = [];
  // the control that gets the focus back once the check that an action ran has ended: that line's button if it is there
  // again, else Check
  let refocus = null, buttons = new Map();
  const lineNode = line => {
    const row = document.createXULElement("hbox");
    // a line with a button: the button in the middle of the line's height, as its words
    row.setAttribute("align", line.action ? "center" : "baseline");
    const mark = document.createXULElement("label");
    mark.textContent = MARKS[line.state] || MARKS.unknown;
    paintMark(mark, line.state);
    marks.push([mark, line.state]);
    const name = document.createXULElement("label");
    name.textContent = line.label;
    name.setAttribute("style", "font-weight: 600");
    const text = document.createXULElement("description");
    text.textContent = line.text;
    text.setAttribute("style", "flex: 1; overflow-wrap: anywhere");   // a long path wraps within the row
    row.append(mark, name, text);
    if (line.action) {
      const button = document.createXULElement("button");
      button.setAttribute("label", line.action.label);
      button.addEventListener("command", async () => {
        const plugin = Zotero.Scholium;
        if (!plugin || !plugin.fix || button.disabled) return;
        button.disabled = true;
        let said = null;
        try { said = await plugin.fix(line.action); } catch (e) { said = String((e && e.message) || e); }
        if (!said) { refocus = line.id; check(); return; }
        text.textContent = line.text = said;   // Copy gives the line as shown
        button.remove();
        focusCheck();
      });
      buttons.set(line.id, button);
      row.append(button);
    }
    return row;
  };
  const focusCheck = () => { try { document.getElementById("scholium-check-run")?.focus(); } catch (e) {} };
  // the button is disabled while the check runs; an action done meanwhile runs it again once it ends. Copy shows once a
  // check has ended
  const check = async () => {
    if (checking) { again = true; return; }
    const plugin = Zotero.Scholium;
    const run = document.getElementById("scholium-check-run");
    const box = document.getElementById("scholium-check-lines");
    const copy = document.getElementById("scholium-check-copy");
    if (!plugin || !plugin.setupCheck || !run || !box) return;
    checking = true;
    run.disabled = true;
    if (copy) copy.hidden = true;
    try {
      do {
        again = false;
        box.replaceChildren();
        shown = [];
        marks.length = 0;
        buttons = new Map();
        await plugin.setupCheck(line => { shown.push(line); box.append(lineNode(line)); }).catch(() => {});
      } while (again);
    } finally {
      checking = false;
      run.disabled = false;
      if (copy && plugin.copy) copy.hidden = !shown.length;
      if (refocus !== null) {
        const button = buttons.get(refocus);
        refocus = null;
        if (button) { try { button.focus(); } catch (e) {} } else focusCheck();
      }
    }
  };
  // the lines shown, with the versions, as plain text on the clipboard; the button says Copied for a moment
  let copiedTimer = null;
  const copyLines = async () => {
    const plugin = Zotero.Scholium;
    const copy = document.getElementById("scholium-check-copy");
    if (!plugin || !plugin.copy || !copy || !shown.length) return;
    try { await plugin.copy(shown); } catch (e) { return; }
    if (!document.l10n) return;
    document.l10n.setAttributes(copy, "scholium-check-copied");
    clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => { document.l10n.setAttributes(copy, "scholium-check-copy"); }, 1500);
  };
  const wire = () => {
    document.getElementById("scholium-claude-browse")?.addEventListener("command", () => { browse("claudePath", "scholium-settings-claude"); });
    document.getElementById("scholium-codex-browse")?.addEventListener("command", () => { browse("codexPath", "scholium-settings-codex"); });
    const plugin = typeof Zotero !== "undefined" ? Zotero.Scholium : null;
    if (plugin && plugin.setupCheck) document.getElementById("scholium-check-run")?.addEventListener("command", () => { check(); });
    if (plugin && plugin.copy) document.getElementById("scholium-check-copy")?.addEventListener("command", () => { copyLines(); });
    // the boxes' grey text: the program the plugin finds by itself, or that it finds none
    for (const [id, agent] of [["scholium-claude-path", "claude"], ["scholium-codex-path", "codex"]]) {
      const input = document.getElementById(id);
      if (!input || !plugin) continue;
      plugin.found(agent).then(async path => {
        input.placeholder = path || (document.l10n ? await document.l10n.formatValue("scholium-settings-not-found") : "");
      }).catch(() => {});
    }
  };
  // zotero loads this script before it inserts the page's markup, then fires `load` on each top-level node of it
  let wired = false;
  document.addEventListener("load", event => {
    if (wired || !event.target?.classList?.contains("scholium-settings")) return;
    wired = true;
    wire();
  }, true);
}
