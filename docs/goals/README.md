# Goals — autonomous agent loops with human arbitration

`docs/goals/` holds the **why**: durable objectives an AI agent can work toward across
many sessions. `docs/tasks/` holds the **how**: individual work items derived from goals.
The split exists so autonomous loops (cron sessions, `/loop`, headless agents) have a
stable steering file, and the human has two clean arbitration points.

## The loop

1. Agent reads its goal file (end state, guardrails, gates).
2. Agent proposes work → creates `docs/tasks/TASK-<goal>-<slug>.md` with `Status: proposed`.
3. **Human arbitrates**: flips `proposed → approved` (edit or PR review). Nothing executes before this.
4. Agent executes **approved tasks only**, inside the goal's guardrails.
5. Agent reports: task → `Status: in-review` + evidence (links, run IDs, reports, diffs).
6. **Human arbitrates**: `in-review → done` (or `rejected` with a reason the agent must read).
7. Agent appends one line to the goal's Log and repeats.

## Hard rules (all goals, all agents)

- **Never self-approve.** Only the human moves `proposed → approved` and `in-review → done`.
- **Code changes go through branches + PRs**, never direct to `main`.
- **Guardrails live in the goal file** — they apply to any agent regardless of which
  model or session runs the loop. If a guardrail blocks the obvious approach, propose a
  task to change the guardrail; don't work around it.
- **Escalate on ambiguity**: if a task's acceptance criteria can be read two ways, stop
  and ask instead of picking one.
- **Evidence over claims**: a task is not `in-review` without artifacts (report URL, run
  ID, screenshot path, PR link).

## Goal file format

```markdown
# GOAL-NN — <title>
**Status:** active | paused | done
**Arbitrator:** <human>

## End state (success criteria)      ← measurable; when true, goal is done
## Exists today / Gap                ← honest current state, updated as work lands
## Guardrails                        ← hard rules; agent must never cross
## Arbitration gates                 ← actions that ALWAYS need human approval
## Active tasks                      ← links into docs/tasks/
## Log                               ← one line per event, newest first
```

## Task file format

```markdown
# TASK-<goal>-<slug> — <title>
**Goal:** GOAL-NN
**Status:** proposed | approved | in-progress | in-review | done | rejected
**Acceptance criteria:** <how the arbitrator will judge it>
**Evidence:** <required artifacts; filled in before in-review>
```

## Current goals

| Goal | Title |
|------|-------|
| [GOAL-01](GOAL-01-ops-vm.md) | Autonomous ops VM — system health, code maintenance, feature requests |
| [GOAL-02](GOAL-02-userinterface-maintenance.md) | AI creates & maintains userinterfaces |
| [GOAL-03](GOAL-03-test-lifecycle.md) | AI test lifecycle — testcases → campaigns → execution → analysis → report |
| [GOAL-04](GOAL-04-device-health.md) | Per-device health checks (mobile, STB, TV, web) |
