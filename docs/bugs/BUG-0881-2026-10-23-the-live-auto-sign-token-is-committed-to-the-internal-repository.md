# BUG-0881 — The live auto-sign token is committed to the internal repository

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0881                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | In progress                                                  |
| Severity  | High                                                        |
| Area      | security / tooling                                          |
| Fixed in  | —                                                            |
| Commit    | TBD                                                          |

---

## Symptom

The token that signs an agent in as a **team admin** on every VirtualPyTest backend is written in the
repository. The repository is the **internal** one (`AngelStreetCorp/virtualpytest-internal`, `isPrivate:
true`), so the blast radius is **everyone with read access to the internal repository** — not the internet.

The **public** repository (`angelstreet/mycodebox`) was scanned file by file on 2026-10-23 (568 files) and
is **clean**: none of the files below exist there and the token value appears in none of its files.

The value in the files below is the live one: it is the same string
`scripts/agent/auto_sign_token.sh` reads from the main server's `.env` on 2026-10-23.

```bash
T=$(scripts/agent/auto_sign_token.sh)
git grep -l "$T"          # → the files below
```

| File | Occurrences | Committed by |
|---|---|---|
| `scripts/measure_e2e_browser.py` | 1 (line 25, `AUTO_SIGN = "…"`) | the QA sweep work (`36d31d74e` and the measure scripts) |
| `scripts/measure_e2e_via_cors.py` | 1 | same |
| `scripts/measure_endtoend.py` | 1 | same |
| `docs/tasks/qa-evidence/tester/sweep-desktop-dark.json` | 16 | `36d31d74e` |
| `docs/tasks/qa-evidence/tester/sweep-desktop-light.json` | 16 | same |
| `docs/tasks/qa-evidence/tester/sweep-mobile-dark.json` | 16 | same |

Anyone with read access to the internal repository can sign in as a team admin on the customer's
production platform: read the hosts, the devices, the campaigns and the test cases, and run the agent
against them. It is also in the git history, so any copy of the internal repository that leaves the
company carries it.

## Root cause

The QA sweep harness wrote the token into its own script and into its captured evidence, and the
evidence was committed. The rule is that the auto-sign token stays in a shell variable — never in a file,
a log, a doc or a commit — and that rule does not depend on the repository being public: the internal
repository is where the code lives, so a token committed there is committed. Nothing checked the diff
for it before the commit landed.

## Fix

1. **Rotate the token** — **OPEN (owner / infra).** `AUTO_SIGN_TOKEN` lives in the main backend
   server's `.env` (`/opt/virtualpytest/.env`); the Pi server trusts the same value. A new value
   has to be written in both places and the services restarted, then
   `scripts/agent/auto_sign_token.sh` hands out the new one. This is the only thing that closes
   the leak: the value in the history is still live, and no gate can make it harmless.
2. **Take the token out of the files** — **DONE.** The three `scripts/measure_e2e_*.py` /
   `scripts/measure_endtoend.py` scripts now do `from _auto_sign import auto_sign_token,
   redact` and `AUTO_SIGN = auto_sign_token()`, and the three
   `docs/tasks/qa-evidence/tester/sweep-*.json` files carry no token-shaped field. Checked
   against the live value (taken at run time, never printed), the working tree is clean.
3. **Guard the repository** — **DONE.** `scripts/security/auto_sign_token_gate.sh` refuses a
   push whose **added lines**, whose **touched files' content** (a binary diff shows no line)
   or whose **commit messages** carry the live value. It reads the value at run time — never
   stored, never printed, never on a command line — so it survives the rotation, and it says
   exactly what was **not** checked when the value cannot be obtained, or when there is
   nothing to compare: a check that did not run is reported as not performed, never as a pass.
   It runs from `.githooks/pre-push` and from the CI `leak-gate` job. What it catches and what
   it does not catch is written down in `docs/agent/release/AUTO_SIGN_TOKEN_GATE.md`.

   It catches a token added from now on. It cannot and does not clean the history — only the
   rotation does that.

## What is still open

The rotation (fix item 1). It is the owner's call: the value is live in the history of this
repository, and only a rotation makes it useless. Rewriting that history is the owner's
decision too, and is not part of any of this.

The guard is not a substitute for it either: it compares against the value that is live *now*,
so once the token is rotated the old value stops being compared — and stops working, which is
the point.

## Verification

```bash
T=$(scripts/agent/auto_sign_token.sh)
git grep -l "$T" && echo "STILL COMMITTED" || echo "clean"
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Auto-Sign: $T" \
  "https://virtualpytest.angelstreet.io/server/system/getAllHosts"   # 401 once the old token is dead

# the guard refuses a change that carries the value
bash scripts/security/auto_sign_token_gate_selftest.sh
```

Note: this bug was found while running TASK-163 (the Atlas benchmark), not by the work that introduced
it. The files belong to another session's QA work, so they were not edited from here — removing the
value from the working tree does not undo what the history already holds; only the rotation does that.
