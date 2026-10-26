# BUG-0702 — Agent-built navigation trees showed every node stacked at (0, 0), and an edited node lost its screenshot

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0702                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server MCP tree tools, build-tree skills             |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The tree TASK-135 phase 2 built with Forge (`vpttv-ch-full`, 21 nodes, 20 edges) opened in the Navigation Editor as one spot:
every node at (0, 0), so it looked empty and `tv_guide` was hidden under `home`. `vod_player` had no screenshot.

## Root cause

- `create_node` stores no position unless the model passes one, so every tool-made node starts at (0, 0). Nothing laid the tree
  out afterwards (the editor's auto layout runs only after a Build Map run).
- `update_node` (MCP) rebuilt the node from what the model sent: a node given without `position_x`/`position_y` was saved at
  (0, 0), and a node given with a partial `data` dict lost `data.screenshot` and `data.fingerprint`.

## Fix

- `backend_server/src/mcp/tools/tree_tools.py`: `update_node` reads the stored node when position or screenshot data is missing
  and keeps them (the model's values win when given).
- New MCP tool `auto_layout_tree(userinterface_name | tree_id)`: top-down layout (entry, home, then each level under its first
  parent, a parent centred over its children, 300 x 220 px grid), saves only the positions of nodes that move.
- `build-tree-web` / `-mobile` / `-stb` skills: call `auto_layout_tree` as the last step; the web skill also checks that every
  node except entry has a screenshot. `scripts/bench_tree_build.py` calls it after every round.
- Tests: `tests/backend_server/test_mcp_tree_tools.py` (stored position and screenshot kept, layout rows and centring, cycles,
  only stacked nodes moved).

`vpttv-ch-full` was laid out with the same algorithm on 2026-10-19 (21 nodes, data and verifications unchanged).
