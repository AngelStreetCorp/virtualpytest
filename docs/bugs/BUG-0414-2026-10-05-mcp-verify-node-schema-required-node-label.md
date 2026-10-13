# BUG-0414 — MCP verify_node rejected a call that gave node_id without node_label

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0414                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                       |
| Area      | backend_server / MCP |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

A client that called `verify_node` with `node_id` only (as the tool description allows) was refused by schema validation, so the model retried with `node_label`.

## Root cause

The tool schema listed `node_label` as required while the code accepted either `node_label` or `node_id`, and the description said `node_id` overrides `node_label`.

## Fix

The `verify_node` docstring (source of the generated definition) marks neither as required and says to give either one; the definition's `required` list is `userinterface_name` only. The code already accepted either, so there is no fallback.

## Verification

- `python3 -m pytest -m unit tests/backend_server/test_mcp_inline_screenshot.py` checks the schema.
- After deploy: `verify_node` with `node_id` only and with `node_label` only both run.
