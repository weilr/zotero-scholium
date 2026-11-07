/* Scholium: a minimal plugin for Zotero 7 and later.
 * Reader toggle (all versions): the eye button in the reader toolbar shows or hides annotations tagged
 * by zotero-scholium in every reader view (tab, window, item-pane preview) at once. The choice is kept
 * in the preference extensions.scholium.showAnnotations; until it is first switched on, the
 * annotations are hidden. Hiding removes them from the view only; stored items are not changed.
 * One-click annotation (the Scholium section of the item pane): starts the installed Claude Code or
 * Codex in the background for the paper shown (see ScholiumRunner).
 * Endpoints, on Zotero's built-in local HTTP server (http://127.0.0.1:23119); the tool writes through them
 * when the plugin is installed, and on Zotero 7 to 9 they are its only write channel:
 *   GET  /scholium/ping   -> { ok, version, dataDir }                       (no token)
 *   POST /scholium/list   -> annotations and notes of one attachment, the plugin's version (token)
 *   POST /scholium/apply  -> clean up + create annotations / child note, the new keys (token)
 * list and apply take the attachment in My Library, or in the library a request names by groupID or libraryID.
 * The same endpoints answer at /scholium-bridge/ping, /list and /apply, which the skill of Scholium Bridge 0.1.9 calls.
 * No code is evaluated: requests carry plain data (highlight, text, and note annotations).
 * The token is stored in <Zotero data directory>/scholium.token (created on first start), and in
 * scholium-bridge.token, which the skill of Scholium Bridge 0.1.9 reads.
 */

// the plugin's objects, in modules/ beside this file: ScholiumEndpoints (endpoints.js), ScholiumToggle (toggle.js) and
// ScholiumRunner (runner.js, and the methods the modules after it add). startup() loads them into this scope once, in
// this order, past the script cache as Zotero loads this file: an update in place keeps the files' addresses
var MODULES = ["endpoints.js", "toggle.js", "runner.js", "setup.js", "prompts.js", "section.js", "conversations.js",
               "queue.js", "agents.js"];
var modulesLoaded = false;   // a start after a disable finds them: Zotero keeps the scope, and the objects in it

function loadModules(rootURI) {
  if (modulesLoaded) return;
  for (const name of MODULES) {
    Services.scriptloader.loadSubScriptWithOptions(rootURI + "modules/" + name,
                                                   { target: globalThis, ignoreCache: true });
  }
  modulesLoaded = true;
}

var chromeHandle = null;   // chrome://scholium-<version>/content/ -> the plugin's content/ folder

// a chrome package per version, e.g. scholium-0-1-3
function chromePackage(version) {
  return "scholium-" + String(version || "0").replace(/[^0-9a-z]+/gi, "-").toLowerCase();
}

// a reader listener of the plugin let go of. Zotero 7–9's unregisterEventListener keeps the one listener it is given
// and drops every other, those of other plugins too; there the listener stays, doing nothing (its handler checks that it
// is still the plugin's), until Zotero removes the listeners registered with the plugin's id as the plugin stops
function unregisterReaderListener(type, handler) {
  let major = NaN;
  try { major = parseInt(String(Zotero.version || ""), 10); } catch (e) {}
  if (!(major >= 10) || !handler) return;
  try { Zotero.Reader.unregisterEventListener(type, handler); } catch (e) {}
}

function install() {}
function uninstall() {}

function onMainWindowLoad({ window }) {
  try { ScholiumRunner.addToWindow(window); } catch (e) {}
}

function onMainWindowUnload({ window }) {
  try { ScholiumRunner.removeFromWindow(window); } catch (e) {}
}

// ADDON_UPGRADE and ADDON_DOWNGRADE: one copy of the plugin replaces another, as the copy that stops is told
function replacing(reason) {
  return [typeof ADDON_UPGRADE === "number" ? ADDON_UPGRADE : 7, typeof ADDON_DOWNGRADE === "number" ? ADDON_DOWNGRADE : 8].includes(reason);
}

// the reasons the new copy of an update may start with: Zotero's handlers forget the old version before they start the
// new one, which then gets ADDON_INSTALL
function takingOver(reason) {
  return replacing(reason) || reason === (typeof ADDON_INSTALL === "number" ? ADDON_INSTALL : 5);
}

// Scholium Bridge 0.1.9 (the add-on scholium-bridge@zotero-scholium) is uninstalled, enabled or not, before this plugin
// registers anything: on Zotero 7–9 its shutdown drops every reader listener of the types it used, other plugins' too,
// and it removes its endpoints. A failure, or no end within 10 seconds, is logged and the start goes on
async function removeScholiumBridge() {
  const log = msg => Zotero.debug("[scholium] " + msg);
  let manager = null;
  try { manager = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs").AddonManager; }
  catch (e) {
    try { manager = ChromeUtils.import("resource://gre/modules/AddonManager.jsm").AddonManager; } catch (e2) {}
  }
  if (!manager) { log("Scholium Bridge not looked for: AddonManager not loaded"); return; }
  const removal = (async () => {
    const addon = await manager.getAddonByID("scholium-bridge@zotero-scholium");
    if (!addon) return "";
    await addon.uninstall();
    return "Scholium Bridge uninstalled";
  })().catch(e => "Scholium Bridge not uninstalled: " + e);
  let timer = null;
  const limit = new Promise(resolve => { timer = setTimeout(() => resolve("Scholium Bridge not uninstalled within 10 seconds"), 10000); });
  const outcome = await Promise.race([removal, limit]);
  clearTimeout(timer);
  if (outcome) log(outcome);
}

// Scholium Bridge 0.1.9's preferences (extensions.scholium-bridge.*) become this plugin's where it has no value of its
// own; the old ones are cleared
function takeOverPreferences() {
  try {
    const prefs = Services.prefs, from = prefs.getBranch("extensions.scholium-bridge."), to = prefs.getBranch("extensions.scholium.");
    for (const name of from.getChildList("")) {
      if (!from.prefHasUserValue(name)) continue;
      try {
        if (!to.prefHasUserValue(name)) {
          const type = from.getPrefType(name);
          if (type === prefs.PREF_STRING) to.setStringPref(name, from.getStringPref(name));
          else if (type === prefs.PREF_INT) to.setIntPref(name, from.getIntPref(name));
          else if (type === prefs.PREF_BOOL) to.setBoolPref(name, from.getBoolPref(name));
          else continue;
        }
        from.clearUserPref(name);
      } catch (e) { Zotero.debug("[scholium] preference not taken over: " + name + ": " + e); }
    }
  } catch (e) { Zotero.debug("[scholium] Scholium Bridge's preferences not taken over: " + e); }
}

async function startup({ id, version, rootURI }, reason) {
  loadModules(rootURI);
  await Zotero.initializationPromise;
  await removeScholiumBridge();
  takeOverPreferences();
  try {
    const aomStartup = Components.classes["@mozilla.org/addons/addon-manager-startup;1"]
      .getService(Components.interfaces.amIAddonManagerStartup);
    const pkg = chromePackage(version);
    chromeHandle = aomStartup.registerChrome(Services.io.newURI(rootURI + "manifest.json"),
      [["content", pkg, rootURI + "content/"]]);
    ScholiumRunner.chrome = "chrome://" + pkg + "/content/";
  } catch (e) { Zotero.debug("[scholium] chrome registration failed: " + e); }
  ScholiumRunner.version = ScholiumEndpoints.version = version;
  try { ScholiumToggle.start(id); ScholiumToggle.log("reader toggle registered"); }
  catch (e) { ScholiumToggle.log("reader toggle failed: " + e); }
  ScholiumRunner.rootURI = rootURI;
  try { ScholiumRunner.start(id, takingOver(reason)); ScholiumRunner.log("annotation menu registered"); }
  catch (e) { ScholiumRunner.log("annotation menu failed: " + e); }
  ScholiumEndpoints.token = await ScholiumEndpoints.loadToken();
  ScholiumEndpoints.register();
  if (takingOver(reason)) ScholiumEndpoints.keep();
  ScholiumEndpoints.log("endpoints registered");
}

function shutdown(data, reason) {
  try { ScholiumRunner.stop(replacing(reason)); } catch (e) {}
  try { ScholiumToggle.stop(); } catch (e) {}
  try { ScholiumEndpoints.unregister(); } catch (e) {}
  try { if (chromeHandle) chromeHandle.destruct(); } catch (e) {}
  chromeHandle = null;
}
