# BUG-0411 — MCP navigate_to_node restarted every run from the entry edge and could time out after the page had loaded

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0411                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server (navigation execute route, MCP navigation tools) |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Over MCP, "open the search results page" on host-clone-1 (youtube-web) reached the page after about 10 s, but the tool
call did not return: the client reported a timeout and the turn took 1m37s. "Go to the home page" took about 50 s.

## Root cause

`/server/navigation/execute` always put `current_node_id` (usually null) in the payload sent to the host. The host
decides by the presence of the KEY (`'current_node_id' in data` -> `frontend_sent_position`), and a present key with no
value means "the caller does not know the position": the tracked position is wiped and the run starts from the entry edge
(browser relaunch plus its waits). Measured on the main server, home from search_results: `nav.hop.actions` 25.8 s for
`Entry->home`, 5 s of position probe first, 33.9 s end to end. The MCP poll (`_poll_navigation_completion`) gave up after
60 s and answered "timed out" while the host went on.

## Fix

- `server_navigation_execution_routes.py`: forward `current_node_id` to the host only when the caller sent it. Without
  it the host trusts its tracked position and takes the direct edge.
- `navigation_tools.py`: the MCP poll waits up to 120 s (the host's own limit) instead of 60 s; stale comment about a
  synchronous route corrected.

## Verification

- Before (deployed main-2026.10.05-10032, REST replay of the MCP call, device host): search_results about 20 s,
  home 33.9 s.
- After: see the release note / deploy check below.
