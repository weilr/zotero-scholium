"""CI guard: the package, the tool, the Claude Code plugin and the Zotero plugin carry one version, and a release tag
(the optional argument, e.g. v0.1.6) names it."""
import json, pathlib, re, sys

root = pathlib.Path(__file__).resolve().parents[1]


def text(path):
    return (root / path).read_text(encoding="utf8")


market = json.loads(text(".claude-plugin/marketplace.json"))
versions = {
    "pyproject.toml": re.search(r'^version = "([^"]+)"', text("pyproject.toml"), re.M).group(1),
    "src/zotero_scholium/cli.py": re.search(r'^__version__ = "([^"]+)"', text("src/zotero_scholium/cli.py"), re.M).group(1),
    ".claude-plugin/plugin.json": json.loads(text(".claude-plugin/plugin.json"))["version"],
    ".claude-plugin/marketplace.json (metadata)": market["metadata"]["version"],
    ".claude-plugin/marketplace.json (plugin)": market["plugins"][0]["version"],
    "plugin/scholium-bridge/manifest.json": json.loads(text("plugin/scholium-bridge/manifest.json"))["version"],
    "plugin/scholium-bridge/bootstrap.js": re.search(r'^  version: "([^"]+)"', text("plugin/scholium-bridge/bootstrap.js"), re.M).group(1),
}
if len(sys.argv) > 1:
    versions["tag " + sys.argv[1]] = sys.argv[1].lstrip("v")
if len(set(versions.values())) != 1:
    print("versions differ:\n" + "\n".join(f"  {v}  {k}" for k, v in versions.items()))
    sys.exit(1)
print("version", next(iter(versions.values())), "everywhere")
