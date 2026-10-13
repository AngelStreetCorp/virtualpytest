# BUG-0272 — MCP create_node dropped verifications, and edge writes were never validated

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0272                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — a built tree silently lacked its verifications      |
| Area      | `backend_server/src/mcp/tools/tree_tools.py`, `backend_server/src/mcp/utils/api_client.py` |
| Fixed in  | Unreleased                                                   |
| Commit    | `e3d7e6b63`                                                  |

---

## Symptom

- `create_node` with top-level `verifications` saved the node without them, and refused a call
  that gave only `node_id` (`'label' is a required property`).
- `update_node` on a tree passed by `tree_id` failed with
  `Failed to fetch userinterface: Unknown error`.
- `create_edge` / `update_edge` never validated action sets.

## Root cause

- `create_node`'s docstring-generated schema had no `verifications` and required `label`; its
  payload forwarded only label/node_id/node_type/data.
- `get_device_model_from_userinterface` expected `{success, data}`, but
  `GET /server/userinterface/getUserInterface/<id>` returns the bare userinterface dict.
- The edge tools looked the userinterface up at `/server/userinterfaces/<id>` (plural), a route
  that does not exist, and skipped validation when the lookup failed.

## Fix

`create_node` accepts and validates `verifications` (top level or `data.verifications`) and
forwards them; `label` defaults to `node_id`, then `data.label`. The device-model lookup reads the
bare dict. Edge and node validation share one lookup through the real route. Action validation
without a host still only warns (the validator reads commands from a host).

## Verification

`tests/backend_server/test_mcp_tree_tools.py`.
