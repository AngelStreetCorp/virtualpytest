# BUG-0069 — `backend_server/requirements.txt` could not be installed: `h2==4.4.1` vs `hpack==4.1.0`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0069                                                                    |
| Reported  | 2026-09-09 (customer site, first packaged delivery)                         |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (server dependency install fails; running server unaffected)         |
| Area      | backend_server/requirements.txt                                             |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

On the customer's server VM, the optional dependency step of the first packaged delivery
(`pip install -r backend_server/requirements.txt`, TASK-13 §4) aborted:

```
ERROR: Cannot install -r backend_server/requirements.txt (line 20) and hpack==4.1.0
because these package versions have conflicting dependencies.
The conflict is caused by:
    The user requested hpack==4.1.0
    h2 4.4.1 depends on hpack<5 and >=4.2
ERROR: ResolutionImpossible
```

pip installs nothing when the file is unresolvable, so the security bumps in the same file
(`requests` 2.33.0, `pyjwt` 2.13.0, `idna` 3.15) did not land either.

## Root cause

Dependabot PR #25 (`5dbaecfcc`, 2026-09-07) bumped `h2` 4.3.0 → 4.4.1 but left the sibling
pin `hpack==4.1.0` untouched. `h2 4.4.1` declares `hpack<5,>=4.2` and `hyperframe<7,>=6.1`
(wheel metadata). The file had become self-contradictory; TASK-09 P3.6 had already flagged
"fix the conflicting pins so a resolver can install it" and nothing exercised a clean install
since (CI runs from a pre-built venv). The bundle `release-2026.09.09` carries the broken file.

## Fix

Two pins, found one after the other (pip stops at the first unresolvable pair):

1. `hpack==4.1.0` → `hpack==4.2.0` (the only 4.x release satisfying `>=4.2`; `hyperframe==6.1.0`
   already satisfies h2's other constraint).
2. `packaging==25.0` → `packaging==24.2`: the pinned `langfuse>=2.0.0,<3` (v2 SDK, required by
   `observability.py` and the self-hosted v2 server) declares `packaging<25.0,>=23.2`, so every
   langfuse 2.x was rejected and pip blamed the supabase/googletrans/deprecation lines that
   also depend on `packaging`. This pin predates the langfuse cap (June snapshot).

No code change: `hpack` is a transitive dependency of `h2`/`httpx` HTTP/2 support and
`packaging` is only used by third-party libraries; nothing in the tree imports either.

## Verification

- `h2==4.4.1` wheel metadata: `Requires-Dist: hpack<5,>=4.2`, `hyperframe<7,>=6.1`.
- Clean venv (Python 3.12.8), `pip install --dry-run -r backend_server/requirements.txt`:
  before → `ResolutionImpossible` (hpack), after fix 1 → `ResolutionImpossible` (packaging vs
  every langfuse 2.x), after fix 2 → exit 0, `Would install …` (full file resolves).

## Customer workaround on bundle 8713 (until the next release)

Either skip the optional server pip step (nothing in 8713 imports a new server package), or
edit the two lines in their extracted tree before running it:

```bash
sed -i -e 's/^hpack==4.1.0$/hpack==4.2.0/' -e 's/^packaging==25.0$/packaging==24.2/' \
  /shared/code/virtualpytest/backend_server/requirements.txt
```

The host step (`pip install 'defusedxml>=0.7.1'`) is unaffected — it installs one package,
not the file.

## Log

- 2026-09-09 — reported from the customer server during the delivery; pin fixed on `main`.
