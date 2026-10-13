# BUG-0236 — An edge or node saved through the REST API left the hosts on the old navigation graph

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0236                                                     |
| Reported  | 2026-10-02                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — navigation and AI exploration ran on a graph without the saved change until someone cleared the host cache by hand |
| Area      | `backend_server/src/routes/server_navigation_trees_routes.py` (node and edge create / update) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

A new interface's entry edge was given its actions (`close_app` + `launch_app`) with
`PUT /server/navigationTrees/<tree>/edges/<edge>`. AI Generate then still failed with *"No path
found from 'Entry' to 'home'"*: the host logged *"Using cached unified graph: 2 nodes, 0 edges"*.
It worked only after `POST /host/navigation/cache/clear/<tree_id>` by hand.

## Root cause

The node and edge create/update routes cleared only the server's caches. They left the hosts to
the editor, which follows every save with `/server/navigation/cache/update-node|edge`. The
reason given was that clearing the host here would race the host's in-place patch. The host
stopped patching long ago: those routes only invalidate now. So any caller other than the
editor (MCP outside its own workaround, agents, scripts, curl) left every host on the old graph.

## Fix

The four routes clear the hosts' graph like every other tree write (in the background; the
graph rebuilds from the database on next use). The `propagate_to_hosts` switch had no other
use and is gone.

## Verification

- `py_compile` passes; no caller passes `propagate_to_hosts` any more.
- After a server deploy: save an edge with `PUT /server/navigationTrees/<tree>/edges/<edge>`;
  the host logs the cache clear, and the next navigation uses the new edge with no manual clear.
