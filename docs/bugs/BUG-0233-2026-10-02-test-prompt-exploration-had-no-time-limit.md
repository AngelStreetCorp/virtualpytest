# BUG-0233 — Test Prompt: an exploration had no time limit and overlapped the next run

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0233                                                     |
| Reported  | 2026-10-02                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — an agent that keeps trying never ends: the device stays busy, and a run started meanwhile shares it |
| Area      | `features/ai-test/backend_server/server_testprompt_routes.py` (`_start_exploration`) |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

On host-clone-1 (web_tv, prompt "Go to live TV and zap to the next channel 3 times"), Explore
started at 06:51 UTC and was still pressing keys and clicking tabs at 07:06. A graph run of
another prompt started at 07:06 then drove the same device at the same time.

## Root cause

The `test-prompt-*` skills declare `timeout_seconds: 300`, but the exploration never applied it.
`asyncio.run(run())` ran the agent until the agent itself stopped.

## Fix

The agent loop runs under `asyncio.wait_for` with the skill's `timeout_seconds` (300 s if the
skill gives none). When it expires, the run ends as an *error*, "Exploration stopped after N s
(the skill's time limit)", with its report, logs and trace up to that point.

### First fix did not work (2026-10-03)

The first fix wrapped the loop in \`asyncio.wait_for\`. After its deploy, explorations still ran
948 s and 985 s on a 300 s limit (web_tv, 2026-10-02 08:14 and 08:30 UTC). The agent
(\`agent/core/manager.py\`) calls the LLM (\`client.messages.create\`) and its tools
synchronously inside the async generator, so the event loop never regains control and the
timeout callback never runs. The loop now checks a deadline on every event the agent yields,
and stops after the first event past it. The overshoot is at most one AI turn or tool call.

## Verification

- `py_compile` passes.
- After a server deploy: an exploration that does not finish stops shortly after 300 s, as an error.
