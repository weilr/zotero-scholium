// the Scholium page of Zotero's settings: the buttons that choose an agent's program
{
  const browse = async (pref, title) => {
    const { FilePicker } = ChromeUtils.importESModule("chrome://zotero/content/modules/filePicker.mjs");
    const fp = new FilePicker();
    fp.init(window, document.l10n ? await document.l10n.formatValue(title) : "", fp.modeOpen);
    fp.appendFilters(fp.filterAll);   // the claude and codex executables are no app bundles
    if (await fp.show() === fp.returnOK) Zotero.Prefs.set("extensions.scholium-bridge." + pref, fp.file, true);
  };
  document.getElementById("scholium-claude-browse")?.addEventListener("command", () => { browse("claudePath", "scholium-settings-claude"); });
  document.getElementById("scholium-codex-browse")?.addEventListener("command", () => { browse("codexPath", "scholium-settings-codex"); });
}
