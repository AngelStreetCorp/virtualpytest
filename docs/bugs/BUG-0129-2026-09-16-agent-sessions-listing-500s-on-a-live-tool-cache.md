# BUG-0129 — Listing agent sessions 500s once any session has run a tool

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                   |
|-----------|-------------------------------------------------------------------------|
| ID        | BUG-0129                                                                |
| Reported  | 2026-09-16                                                              |
| Status    | Fixed (pending deploy)                                                  |
| Severity  | Medium (Atlas session list is unreadable until `vpt-server` restarts)    |
| Area      | `backend_server/src/agent/core/session.py`                              |
| Fixed in  | build 9151                                                              |
| Commit    | TBD                                                                     |

---

## Symptom

```
GET /server/agent/sessions?team_id=… -> 500
{"error":"Object of type ToolResultCache is not JSON serializable"}
```

Same for `GET /server/agent/sessions/<session_id>`. It is intermittent in the way that matters
most: it depends on what happens to be in the server's memory, so it passes right after a
restart and fails from the first session that runs a tool until the next one. CI run **705**
was green on this route; run **708** failed on it, in both `api-routes` (the sweep) and
`backend-server-tests` (`TestSessionLifecycle::test_create_list_get_delete_session`).

## Root cause

`Session.context` is a free-form bag any agent may write to, and `to_dict()` handed it
straight to `jsonify`:

```python
"context": self.context,
```

`ToolBridge.__init__` parks a **live object** in there so the cache survives across turns
(`backend_server/src/agent/core/tool_bridge.py`):

```python
session.context['_tool_result_cache'] = self._result_cache
```

So every session that has ever run a tool carries something Flask cannot serialize, and the
whole listing dies on it — not just that one session's entry.

## Fix

`to_dict()` no longer trusts `context`. `Session._serializable_context()` drops
underscore-prefixed keys (internal by convention) and any value that fails `json.dumps`, so one
unserializable object can no longer take the response down with it. The cache itself is left
where it is: it is genuinely session state, it simply has no business crossing the API boundary.

## Verification

`tests/backend_server/test_agent_session_serialization.py` — three unit tests (no server): a
session holding a real `ToolResultCache` serializes, the internal key is absent from the
payload, and an unserializable *public* value is dropped rather than fatal. The pre-fix
behaviour is reproducible in one line:

```python
json.dumps({'_tool_result_cache': ToolResultCache()})   # TypeError: not JSON serializable
```

End-to-end after deploy: `GET /server/agent/sessions` answers 200 with sessions that have run
tools, and `api-routes` shows it green.
