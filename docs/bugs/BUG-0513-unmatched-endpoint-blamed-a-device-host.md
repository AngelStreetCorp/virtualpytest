# BUG-0513 — A wrong endpoint was answered with "host_name required", blaming a device host

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0513                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server / routing                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Any `/server/...` path that reached the catch-all without a `host_name` answered:

```
400 {"error": "host_name required in request body or query parameters", "success": false}
```

The catch-all in `backend_server/src/routes/auto_proxy.py` is the last-resort route: it answers
for **every** `/server/*` path that matched no blueprint. So this is also what a caller gets when
its **path is simply wrong** — and the message then names a *device host* parameter, sending the
reader after a device that has nothing to do with the request.

## Why it cost more than a bad message

This is what made BUG-0507 expensive. A GitLab route took the project as a path segment; a
namespaced project carries a `/`, Flask matched no route, and the request landed here. The error
named a device host, so the obvious reading was "a device parameter is missing" — pointing at the
host layer, not at the one line that had to change. The page meanwhile showed an empty repository,
which reads like the repository rather than like a routing failure.

The same trap has been hit before in this repo: `tests/backend_server/test_permissions.py`
documented that reading `/server/server-manager/hosts` "is not a route: it falls into the
auto_proxy catch-all and answers 400", which made the helper return `""` and every
host-dependent permission test skip itself on a server with five hosts registered.

## The fix

`lib/utils/unmatched_endpoint.py::explain_unmatched_endpoint()` rewrites that one failure so it
names the real situation:

```
No /server route matched /server/<path>, and it is not a device proxy route either (those need
a host_name). If VirtualPyTest should answer this path, its route did not match; if a device
should answer it, send host_name. (host_name required in request body or query parameters)
```

plus two machine-readable keys, `unmatched_endpoint` and `auto_proxy_fallback`, so a caller can
branch on it without parsing prose.

**Only that failure changes.** A success, a 502 from a host that did not answer, any other 400,
and every real device proxy route are untouched — the helper returns its input unchanged for all
of them.

The catch-all also **logs it as a warning** now. Its own log line said `Proxying …` as if this
were an ordinary device call, so the server log looked healthy while a feature's requests were
being forwarded to a host that had never heard of them. In the seven days before this fix the
server logged **56** `gitlab` paths going to the catch-all, and the only place that showed up
anywhere was a 400 in the browser console.

## Evidence from the server log

Counting what the catch-all actually forwards in a week gives the honest shape of the problem:

| Path prefix | Count |
|---|---|
| `system` | 3031 |
| `translate` | 1568 |
| `desktop` | 896 |
| `remote` | 583 |
| `power` | 452 |
| `av` | 201 |
| `mods` | 113 |
| **`gitlab`** | **56** |
| everything else | single digits |

`gitlab` does not belong in that table at all: it is a VirtualPyTest feature, not a device
namespace. Every one of those 56 was a request that matched no route and was forwarded to a host
anyway. `run_api_tests.py` produced part of them — it probes every GET rule in the server's
`url_map` with synthetic values, and the old `<project>` rules generated paths with a raw slash.

That same split is why the fix is a message and a warning rather than a new blocklist: `system`,
`translate`, `desktop`, `remote` and `power` are legitimate device passthroughs, and
`/server/system/vnc-info` is not distinguishable by shape from a feature route that failed to
match. A hand-maintained allowlist would have broken a real device call the first time a new one
appeared. The log line is what makes the next occurrence diagnosable.

## Not changed

The catch-all still forwards an unmatched path to a device host. Deciding "this path is not a
device route" is a routing question the catch-all cannot answer: from its shape,
`/server/system/vnc-info` (a real device passthrough) is indistinguishable from a feature route
that failed to match, and the server log shows both shapes in live use. A blocklist would have
broken a real device call the first time someone added a new one. The message and the log line
now say what happened instead of guessing.