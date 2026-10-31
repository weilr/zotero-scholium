"""The Node harness of the bridge plugin (bridge_harness.js) and the runner of a test module's scenarios: the
simulated Zotero, Claude Code and Codex, followed by the scenarios, run once; their facts come back as JSON."""
import json
from pathlib import Path
import shutil
import subprocess

PLUGIN = Path(__file__).resolve().parents[1] / "plugin/scholium-bridge"
BRIDGE = PLUGIN / "bootstrap.js"
CORE = Path(__file__).with_name("bridge_harness.js")
NODE = shutil.which("node")


def run_scenarios(scenarios, tmp_path_factory, timeout=180):
    # a file, since the harness is longer than a Windows command line may be
    script = tmp_path_factory.mktemp("bridge") / "harness.js"
    script.write_text(CORE.read_text(encoding="utf-8") + "\n" + scenarios, encoding="utf-8")
    completed = subprocess.run([NODE, str(script), str(BRIDGE)], encoding="utf-8", capture_output=True, timeout=timeout)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
