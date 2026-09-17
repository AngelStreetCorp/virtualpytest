# BUG-0127 — A missing import quietly removed the agent's ten navigation-tree tools

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0127                                                                    |
| Reported  | 2026-09-16 (found while investigating [BUG-0126](BUG-0126-2026-09-16-runtime-route-background-loop-kills-atlas-chat.md)) |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (the agent works, but cannot read or edit navigation trees and never says so) |
| Area      | `backend_server/src/mcp/tools/tree_tools.py`                                |
| Fixed in  | build 9151                                                                  |
| Commit    | `4480b0275d`                                                                |

---

## Symptom

Every agent-manager creation logged, once, to the server journal:

```
[MCP-SERVER] ⚠️ Failed to instantiate tree: name 'get_mcp_logger' is not defined
[MCP] ✅ Initialized with 92 tools
```

The agent then ran happily with 92 tools instead of 102 — missing the whole `tree` category,
i.e. every navigation-tree CRUD primitive. Nothing surfaced to the user: asking Atlas to inspect
or edit a tree simply produced an answer built without those tools.

## Root cause

`VirtualPyTestMCPServer.__init__` instantiates each registered tool class inside a
`try/except Exception`, logs one line and `continue`s. `TreeTools.__init__` calls
`get_mcp_logger()`, but `tree_tools.py` never imported it — `userinterface_tools.py` imports the
same helper from `..utils.mcp_logger` and works. So the class raised `NameError` at construction,
the category was skipped, and the catch-all turned a hard import error into a one-line warning
in a log nobody reads.

## Fix

`4480b0275d` adds the missing `from ..utils.mcp_logger import get_mcp_logger` to
`tree_tools.py`.

## Verification

Restart `vpt-server` and send any chat message; the journal reads `[MCP] ✅ Initialized with 102
tools` with no `Failed to instantiate` line. Verified on `.103` 2026-09-16.
