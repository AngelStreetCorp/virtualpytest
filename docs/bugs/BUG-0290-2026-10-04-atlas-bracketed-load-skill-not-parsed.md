# BUG-0290 — Atlas: a bracketed LOAD SKILL [name] reply was not parsed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0290                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                       |
| Area      | backend_server/src/agent/core                                                |
| Fixed in  | build 90145 |
| Commit    | ff5f961b2                                                    |

---

## Symptom

Atlas's router prompt tells the model to answer `LOAD SKILL [name]`, but a plain-text reply in exactly that
form was not recognised: the reply was shown to the user as an answer and no skill was loaded. (The tool-use
path already stripped the brackets, so only the text path was affected.)

## Root cause

The parser regex `LOAD\s+SKILL\s+([\w-]+)` cannot match the `[` the prompt asks for.

## Fix

The regex accepts an optional bracket; test added (`tests/backend_server/test_agent_routing_log.py`). Same
commit: every router-mode skill pick is now stored in `ai_decisions` (usage `agent.atlas.route`) so the routing
can be measured (TASK-47), and the `Loaded skill` line reaches the journal (it was a `logger.info` below the
server's WARNING level).
