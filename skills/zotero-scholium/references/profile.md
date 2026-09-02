# The annotation profile

The profile lives in the Zotero data directory at `<Zotero data dir>/zotero-scholium/profile.md`; `python <skill dir>/scripts/scholium.py profile --path` prints the resolved location (it also reports a profile left at the pre-0.1.0 location in the user configuration directory, which the next `profile --from-library` migrates).

## Precedence, lowest to highest

1. **Defaults** (the Outputs table in SKILL.md), used only when nothing else applies.
2. **Learned profile**: the statistics that `profile --from-library` derives from the user's own annotations, together with the interpretation of those statistics. A starting point, not the final decision.
3. **The user's explicit instructions**, recorded in the `## User's rules (always win)` section of `profile.md` and given in the current conversation. An explicit instruction overrides the learned profile even where the library shows a different habit; the difference may be mentioned once, then the instruction is followed. Where the user has given no instruction, the learned profile applies.

## Procedure

- If `profile.md` exists, read it in full: the learned sections first, then the user's rules, resolving conflicts in favour of the rules.
- If it does not exist, derive one before writing anything:
  ```bash
  python <skill dir>/scripts/scholium.py profile --from-library
  ```
  Complete the `___` placeholders with an interpretation of the statistics (for example, "yellow = terms; comments are one-line glossary entries"), present the completed draft to the user in a few lines, and ask them to confirm or correct it. Record their corrections, in their own words, in the `## User's rules (always win)` section; re-running the profile command preserves that section.
- Every later correction by the user (for example, "do not use blue" or "comments should be translations") is added to the same section, so that the next paper starts from it.
- A library with very few annotations provides no usable signal: apply the defaults and say so.

## From profile to configuration

`levels` (colour names to hex values), `type: "underline"` where the user underlines, `summaries` only if the user writes margin text, `note_html` only if the user keeps reading notes, comment density and length as observed, `core_range` from the expected number of core highlights, `banned_phrases` from the style reference and the user's rules, and, from the interpretation and the rules, `margin_side`, `summary_kind`, `font_size`, and a `place: "top"` summary on page 1 (see `references/configuration.md`).
