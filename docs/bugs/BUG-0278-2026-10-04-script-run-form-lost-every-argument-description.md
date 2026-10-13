# BUG-0278 — Script run form: one f-string description hid every argument description of the script

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0278                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — the run form showed the arguments without their help text |
| Area      | `shared/src/lib/utils/script_target_rules_utils.py` (`extract_arg_descriptions_from_source` / `_from_path`) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

In the script run form (and the virtual-script editor), `dns_lookuptime`, `zap_digit`, `validation`,
`game_flappy`, `game_tetris` and `game_pokemon` showed their arguments with no description, although each
declares `_arg_descriptions`.

## Root cause

The extractor read the whole `_arg_descriptions` dict with `ast.literal_eval`. A single value written as an
f-string (`f"... '{DNS_SYSTEM_DEFAULT}' ..."`) is not a literal, so the call raised and the extractor
returned nothing for the whole script.

## Fix

The dict is read entry by entry: literal values as before; an f-string is rebuilt from its text, with
names filled from the module's own string constants (an imported name stays as `{NAME}`); any other
entry is skipped instead of dropping the rest. Found while giving Sherlock the run's arguments with their
meaning (TASK-38).

## Verification

- `tests/shared/test_sherlock_args.py::test_one_fstring_description_does_not_drop_the_others`.
- `extract_arg_descriptions_from_path` on the six scripts returns 2, 11, 5, 5, 4 and 8 descriptions (was none).
