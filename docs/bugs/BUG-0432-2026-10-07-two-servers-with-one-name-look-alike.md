# BUG-0432 — Two servers with the same name looked like the same row in the picker

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0432                                                     |
| Reported  | 2026-10-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Two configured servers that share a `SERVER_NAME` rendered as two identical rows in the
Server picker. Nothing on either row distinguished them, so there was no way to tell which
server you were about to switch to — or which one you were on. The closed select and the
sign-in dialog title showed the same indistinguishable name.

## Root cause

`frontend/src/components/common/ServerSelector.tsx` — `nameFor()` resolves a server's
display name and nothing else: `server_info.server_name` from `getAllHosts`, else the name
advertised by the unauthenticated `/server/auth/check`, else the bare URL. The name is never
qualified, and the component never compared one row's name against another's.

A shared name is entirely ordinary: a `.env` copied from one box to another keeps its
`SERVER_NAME`, and a rename that reached only one box leaves the two disagreeing the other
way. Nothing rejects it — `/server/auth/check` happily advertises whatever `SERVER_NAME`
holds — so the collision is only ever noticed in the UI.

The picker already treats the URL as the identity of a row (`value`/`key` are the URL, and
`getAllServerUrls()` now de-duplicates by canonical URL — BUG-0431). The label was simply
not derived from it.

## Fix

A new pure helper, `frontend/src/utils/serverLabels.ts` — `buildServerPickerLabels(urls,
nameFor)` — returns one label per configured server. A name that is unique among the
configured servers is returned unchanged, so the common case is byte-for-byte what it was. A
name that collides gets the host appended (`Shared — primary.example.com`); the port is
kept, because two services on one box differ only by port.

`ServerSelector` uses it in all three places that render a server name: the closed select,
each `MenuItem`, and the `ServerAuthDialog` title — so the sign-in prompt says which server
you are signing in to. Labels are recomputed on every render, so a name that arrives late
(a `getAllHosts` round finishing) disambiguates immediately instead of waiting for a
remount.

`nameFor` is injected into the helper rather than imported: the authoritative name comes
from live state, which a util has no business knowing.

## Verification

- `tests/frontend/serverLabels.test.ts` — 10 tests: unique names untouched; colliding names
  disambiguated by host; a collision among three rows leaves the unique row alone; two
  services on one host disambiguated by port; a name that already *is* its host is not given
  a redundant suffix; empty input.
- Full frontend component suite passes; `tsc --noEmit` and `eslint` clean.
- After deploy: point two servers at the same `SERVER_NAME` and confirm the picker shows
  `name — host` on both rows, that a differently-named server keeps its plain name, and
  that the sign-in dialog title matches the row you picked.
