# Contributing

Bug reports and pull requests are welcome.

**Bug reports:** state the Zotero version, the operating system and the write channel (local API or plugin), and include the output of the failing command and of `--list` where applicable.

**Pull requests:** add or adjust tests in `tests/` and run the checks below.

## Setup and checks

```bash
pip install -e ".[dev]"
pytest                                      # tests use a synthetic PDF; no third-party content
python scripts/check_skill_script_sync.py   # the skill bundles a copy of cli.py that must stay identical
python scripts/check_skill_frontmatter.py   # SKILL.md front matter must be strict YAML
python scripts/measure_context.py           # token size of the skill files (--pdf: and of a paper's extraction; --max-skill-tokens: the CI limit)
python scripts/session_usage.py FILE...     # model calls and tokens of Codex rollouts or Claude Code transcripts
python scripts/sync_local_skills.py DIR...  # after a release: install it into local skill directories (keeps an own SKILL.md; exit 1: review, --ack)
```

After changing `src/zotero_scholium/cli.py`, run `python scripts/sync_skill_script.py` to update the copy in the skill.

## Building the plugin

The plugin is packaged by the release workflow. To build it locally, archive `manifest.json`, `bootstrap.js` and the `content/` and `locale/` folders from `plugin/scholium-bridge/` at the root of a zip file named `scholium-bridge.xpi`.
