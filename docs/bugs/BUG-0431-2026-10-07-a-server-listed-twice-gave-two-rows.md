# BUG-0431 — A server repeated in the configuration produced two rows and two fetches

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0431                                                     |
| Reported  | 2026-10-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

With a server listed twice in the configuration — the most common way being the primary
URL repeated in the slave list — the server picker showed the same server on two identical
rows, and every refresh round sent two identical requests to it.

## Root cause

`frontend/src/utils/buildUrlUtils.ts` — `getAllServerUrls()`.

The function pushes the parsed primary URLs and then the parsed slave URLs into one array
and returns it, with no de-duplication. Three spellings of the same server all reached that
array as separate entries:

- the URL repeated verbatim,
- the URL with a trailing `/` (only a `/server` suffix was normalised, not a bare slash),
- the URL with a `/server` suffix — which `normalizeServerUrl` deliberately collapses to
  the bare URL, so `<primary>/server` in the slave list became a *literal* duplicate of the
  primary and was indistinguishable from it even before de-duplication.

`ServerManagerProvider` builds the picker list and the per-round fetch from
`getAllServerUrls()`, so a duplicate produced both a duplicate row and a duplicate
`/getAllHosts` request on every round — doubling the load on that server for no benefit.

## Fix

`getAllServerUrls()` now filters the list through a canonical key —
`normalizeServerUrl`, then a trailing-slash strip, then lower case — keeping the first
occurrence of each server. Configured order is preserved, because both the picker order and
the fetch order derive from this list. The first spelling wins, so a deployment's own URL
form is what ends up in state, in `localStorage` and in the links built from it.

De-duplication is applied after the default-URL fallback, so a single-server deployment is
untouched.

## Verification

- `tests/frontend/buildUrlUtils.test.ts` — 14 tests. The four `getAllServerUrls`
  de-duplication cases fail against the pre-fix code and pass after it; the rest are
  unaffected.
- Full frontend component suite passes; `tsc --noEmit` and `eslint` clean.
- After deploy: configure the primary URL twice (verbatim, with a trailing slash, or as
  `<primary>/server`) and confirm the picker lists that server once, and the network tab
  shows one `getAllHosts` per configured server.
