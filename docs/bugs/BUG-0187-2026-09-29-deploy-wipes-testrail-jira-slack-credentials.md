# BUG-0187 — Every deploy disconnected TestRail, JIRA and Slack

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0187                                                     |
| Reported  | 2026-09-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / deploy                                             |
| Fixed in  | build 90145 |
| Commit    | `bf56ea42d`                                                  |

---

## Symptom

After a code deploy, the TestRail page shows TestRail as not connected, JIRA instances are gone
and Slack sync stops, with no error anywhere. Reconnecting works until the next deploy.

## Root cause

The server saved the credentials it collects in the UI inside the project tree, in
`backend_server/config/integrations/` (`testrail.json`, `jira_instances.json`,
`slack_config.json`, `slack_threads.json`). The deploy pushes the project with
`rsync -az --delete`, and its exclude list has no entry for that folder. The files are
gitignored, so they are not in the pushed tree, and `--delete` removes them from the server on
every deploy. On Docker the same files lived in the container's own filesystem and went away
whenever the container was recreated.

## Fix

Runtime-written integration state now lives outside the project tree, in
`~/.config/virtualpytest/` of the user the server runs as (`vpt_user`, home `/var/lib/vpt_user`
on installer-built servers). `VPT_CONFIG_DIR` overrides the directory. The path comes from one
helper, `backend_server/src/lib/utils/integration_state.py`, used by `testrail_service.py`,
`slack_sync.py` and `server_integrations_routes.py`. The Docker server mounts a named volume
`server-config` at that directory. Tracked config (`grafana_config.json`, the `*.example`
templates) stays in `backend_server/config/integrations/`.

Existing files are not moved automatically. Copy them once before deploying (release notes,
Unreleased → Upgrade).

## Verification

Connect TestRail, run a code deploy, reload the TestRail page: still connected, and
`~vpt_user/.config/virtualpytest/testrail.json` exists with mode `0600`.
