// the Scholium page of Zotero's settings: the buttons that choose an agent's program
{
  const browse = async (pref, title) => {
    const { FilePicker } = ChromeUtils.importESModule("chrome://zotero/content/modules/filePicker.mjs");
    const fp = new FilePicker();
    fp.init(window, document.l10n ? await document.l10n.formatValue(title) : "", fp.modeOpen);
    fp.appendFilters(fp.filterAll);   // the claude and codex executables are no app bundles
    if (await fp.show() === fp.returnOK) Zotero.Prefs.set("extensions.scholium." + pref, fp.file, true);
  };
  const wire = () => {
    document.getElementById("scholium-claude-browse")?.addEventListener("command", () => { browse("claudePath", "scholium-settings-claude"); });
    document.getElementById("scholium-codex-browse")?.addEventListener("command", () => { browse("codexPath", "scholium-settings-codex"); });
    // the boxes' grey text: the program the plugin finds by itself, or that it finds none
    const plugin = typeof Zotero !== "undefined" ? Zotero.Scholium : null;
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
