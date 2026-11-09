"""The skill's command line (scholium.py) against a THROWAWAY Zotero, for smoke.py's apply check: the module's BASE is
set to the given port before its main() runs, so no request goes to the user's Zotero on 23119.

    python cli_child.py --cli <scholium.py> --port 23129 [--bad] -- --config config.json --apply

--bad: the first highlight of the CLI's own build() output gets a sort index Zotero refuses, so that the plugin's
/scholium/apply endpoint fails inside its transaction (the configuration has no key that produces one).
"""
import importlib.util
import sys

USER_PORT = 23119


def main(argv):
    cut = argv.index("--")
    own, rest = argv[:cut], argv[cut + 1:]
    port = int(own[own.index("--port") + 1])
    if port == USER_PORT:
        sys.exit("refused: port 23119 is the user's own Zotero")
    spec = importlib.util.spec_from_file_location("scholium_smoke_cli", own[own.index("--cli") + 1])
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    cli.BASE = "http://127.0.0.1:%d" % port
    if "--bad" in own:
        build = cli.build

        def bad_build(cfg, obstacles=None):
            out, missed = build(cfg, obstacles)
            for a in out:
                if a.get("type") == "highlight":
                    a["sortIndex"] = "BAD|SORT|INDEX"
                    break
            return out, missed

        cli.build = bad_build
    return cli.main(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
