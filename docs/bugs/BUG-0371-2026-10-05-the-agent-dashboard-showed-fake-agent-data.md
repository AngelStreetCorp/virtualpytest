# BUG-0371 — The Agent Dashboard showed fake agent data: a CI test agent ranked first, benchmarks always 100 %, status always "active"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0371                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / backend / db                                      |
| Fixed in  | build 90145 |
| Commit    | `cfb5119eb`                                                  |

---

## Symptom

On `/agent-dashboard` (TASK-54 review, 2026-10-05):

- **Leaderboard**: `__test_agent_never_real__` (a CI fixture, team `default`) was ranked #1 on prod with 15.0,
  above Atlas.
- **Benchmarks**: "Run Benchmark" always produced a 100 % score, whatever the agent.
- **Agent cards**: every agent showed `active` / `on-demand`; the Enabled switch failed silently (404/405).
- **Import**: said "Agent imported successfully" although nothing was saved.
- Chat execution rows were all stored as version `1.0.0` (Atlas is v2.1.0).
- At 390 px the third tab was cut off with no way to scroll to it.

## Root cause

- `get_leaderboard` / `get_agent_score` / `get_agent_scores` in `shared/src/lib/database/agent_benchmarks_db.py`
  read `agent_scores` without a `team_id` filter, so every team saw every team's rows, CI fixtures included.
- `execute_benchmark_run` was a placeholder: `test_passed = True` for every test, fixed 1.5 s duration, no agent called.
- `AgentDashboard.tsx` mapped `status` from `a.status` and type from `a.goal.type`, which the API never returns;
  the switch called `PUT /server/agents/<id>/enabled`, a route that does not exist; the import route only validates.
- `server_agent_routes.py` passed `version='1.0.0'` to `log_execution_history`.

## Fix

- The three score reads filter `.eq('team_id', team_id)`; `team_id` is required.
- `execute_benchmark_run` marks the run `failed` with "Benchmark runner not implemented" and writes no results;
  `POST /server/benchmarks/run/<id>/execute` answers 501.
- Cards read `config.enabled` and `config.background_queues`; the switch is a read-only label; Import shows the
  server's message and its button says "Validate"; tabs are scrollable.
- Chat execution rows use the registry version (`unknown` if the agent id is not registered).

The page itself is redesigned in [TASK-54](../tasks/TASK-54-agent-dashboard.md).

## Verification

- `tsc --noEmit`, eslint on the page, `py_compile` on the 3 Python files: clean.
- Built by MiniMax, reviewed by a Sonnet gate (ACCEPT, 0 fixes).
- After deploy: the leaderboard of team `7fdeb4bb…` no longer lists `__test_agent_never_real__`; a benchmark run
  returns 501; the third tab is reachable at 390 px.
