# GOAL-01 — Autonomous ops VM

**Status:** active
**Arbitrator:** the owner

An agent running on a dedicated VM that handles operations: system health watching,
code maintenance, and feature requests — triggered by pull requests or by prompts the
arbitrator gives it.

## End state (success criteria)

- A dedicated VM runs an agent loop (cron or persistent session) that:
  - Watches system health signals (service status, disk, CPU, incident queues) and
    proposes remediation tasks when something degrades.
  - Picks up open PRs: reviews them, runs checks, reports findings as PR comments.
  - Accepts feature requests as prompts or issues, turns them into `proposed` tasks,
    and implements approved ones on a branch + PR.
- Every code change reaches `main` only through a PR the arbitrator merges.
- The agent's activity is auditable: one Log line per action, evidence linked.

## Exists today / Gap

- **Exists:** proxmox VM fleet + `update_core.sh` deploy pipeline; monitoring signals
  (vpt-host services, incident queues); gh CLI + CI secrets configured.
- **Gap:** no dedicated ops VM; no agent loop wired to PR events or health signals; no
  triage convention for "prompt → task".

## Guardrails

- **Never modify or delete `.env` on any VM** — config changes go through storage +
  `update_core.sh`.
- **Deploy only via `ssh proxmox "bash update_core.sh <branch>"`** — never scp files to
  /tmp or hand-patch a host; test against the deployed copy.
- **Never push to `main`** — branch + PR always; merges are the arbitrator's.
- **No destructive ops without an approved task naming the exact target** (rm, DB
  deletes, service disables).
- **DB DDL only via the verified migration recipe** (psql as supabase_admin, absolute
  SQL paths), and only from an approved task.

## Arbitration gates (always require human approval)

- Merging any PR.
- Any deploy to hosts/servers.
- Any change to systemd units, sudoers, cron on shared infrastructure.
- Restarting services on hosts running someone's active test session.

## Active tasks

- [TASK-01-repo-strategy-open-core-overlay](../tasks/TASK-01-repo-strategy-open-core-overlay.md) — one public code repo + thin private overlay per customer; replaces hand-patched `prod` fork (proposed 2026-09-02)

## Log

- 2026-09-02 — TASK-01 repo strategy proposed (review of main/prod/demo divergence).
- 2026-07-15 — Goal created.
