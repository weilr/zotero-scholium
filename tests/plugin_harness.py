"""The Node harness of the plugin (plugin_harness.js) and the runner of a test module's scenarios: the
simulated Zotero, Claude Code and Codex, followed by the scenarios, run once; their facts come back as JSON."""
import json
from pathlib import Path
import re
import shutil
import subprocess

PLUGIN = Path(__file__).resolve().parents[1] / "plugin/scholium"
BOOTSTRAP = PLUGIN / "bootstrap.js"
CORE = Path(__file__).with_name("plugin_harness.js")
NODE = shutil.which("node")

# the start of a test's own Node script (`node -e <script> <bootstrap.js> …`): loadPlugin(context, path of bootstrap.js)
# runs bootstrap.js in a vm context and loads its modules as startup() does first, through its loadModules and, for that
# moment, a Services.scriptloader that reads them from their folder; the context keeps the Services it had
LOAD_PLUGIN = r"""
function loadPlugin(context, file) {
  const fs = require('node:fs'), path = require('node:path'), url = require('node:url'), vm = require('node:vm');
  vm.runInContext(fs.readFileSync(file, 'utf8'), context);
  const root = url.pathToFileURL(path.dirname(file)).href + '/', scope = vm.runInContext('globalThis', context);
  const had = Object.prototype.hasOwnProperty.call(context, 'Services'), services = context.Services;
  const scriptloader = { loadSubScriptWithOptions(u, { target, ignoreCache } = {}) {
    if (!u.startsWith(root) || target !== scope || ignoreCache !== true) throw Error('unexpected script load: ' + u);
    vm.runInContext(fs.readFileSync(url.fileURLToPath(u), 'utf8'), context, { filename: url.fileURLToPath(u) });
  } };
  context.Services = Object.assign({}, services, { scriptloader });
  try { context.loadModules(root); } finally { if (had) context.Services = services; else delete context.Services; }
}
"""


def plugin_source():
    """The plugin's code as one text, for a test that reads it: bootstrap.js, then the modules it loads, in order."""
    text = BOOTSTRAP.read_text(encoding="utf8")
    names = re.findall(r'"([^"]+)"', re.search(r"var MODULES = \[(.*?)\];", text, re.S).group(1))
    return "\n".join([text] + [(PLUGIN / "modules" / name).read_text(encoding="utf8") for name in names])


def run_scenarios(scenarios, tmp_path_factory, timeout=180):
    # a file, since the harness is longer than a Windows command line may be
    script = tmp_path_factory.mktemp("plugin") / "harness.js"
    script.write_text(CORE.read_text(encoding="utf-8") + "\n" + scenarios, encoding="utf-8")
    completed = subprocess.run([NODE, str(script), str(BOOTSTRAP)], encoding="utf-8", capture_output=True, timeout=timeout)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def css_rules():
    """The section's stylesheet as {selector: declarations}."""
    text = re.sub(r"/\*.*?\*/", "", (PLUGIN / "content" / "scholium.css").read_text(encoding="utf8"), flags=re.S)
    text = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}", "", text)
    assert text.count("{") == text.count("}")
    return {" ".join(sel.split()): body for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", text)}
