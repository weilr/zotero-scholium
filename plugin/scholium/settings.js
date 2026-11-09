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
  const COLOURS = { ok: "var(--accent-green)", bad: "var(--accent-red)", unknown: "var(--fill-secondary)" };
  let checking = false, again = false;
  const lineNode = line => {
    const row = document.createXULElement("hbox");
    row.setAttribute("align", "baseline");
    const mark = document.createXULElement("label");
    mark.textContent = MARKS[line.state] || MARKS.unknown;
    mark.setAttribute("style", "color: " + (COLOURS[line.state] || COLOURS.unknown) + "; font-weight: 600; min-width: 1.2em");
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
        if (!said) { check(); return; }
        text.textContent = said;
        button.remove();
      });
      row.append(button);
    }
    return row;
  };
  // the button is disabled while the check runs; an action done meanwhile runs it again once it ends
  const check = async () => {
    if (checking) { again = true; return; }
    const plugin = Zotero.Scholium;
    const run = document.getElementById("scholium-check-run");
    const box = document.getElementById("scholium-check-lines");
    if (!plugin || !plugin.setupCheck || !run || !box) return;
    checking = true;
    run.disabled = true;
    try {
      do {
        again = false;
        box.replaceChildren();
        await plugin.setupCheck(line => { box.append(lineNode(line)); }).catch(() => {});
      } while (again);
    } finally {
      checking = false;
      run.disabled = false;
    }
  };
  const wire = () => {
    document.getElementById("scholium-claude-browse")?.addEventListener("command", () => { browse("claudePath", "scholium-settings-claude"); });
    document.getElementById("scholium-codex-browse")?.addEventListener("command", () => { browse("codexPath", "scholium-settings-codex"); });
    const plugin = typeof Zotero !== "undefined" ? Zotero.Scholium : null;
    if (plugin && plugin.setupCheck) document.getElementById("scholium-check-run")?.addEventListener("command", () => { check(); });
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
