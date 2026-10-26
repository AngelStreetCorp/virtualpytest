# BUG-0624 — A deployment row left `running` by a host restart blocks its device for up to an hour

## Summary
When `vpt-host` restarts while a deployment run is in flight, the run's `deployment_executions` row stays
`running`. The next start is supposed to mark it `failed` (`DeploymentScheduler._sync_from_db`). That clean-up
never ran: it asked for the running executions of every deployment on the host with one `in_('deployment_id', [...])`
filter. host-clone-1 has about 1000 deployments, so the URL was too long and PostgREST answered HTTP 414
(`Error cleaning up stale executions: ... URI too long`). The orphan row then made every recurring fire of the
same device skip as "host busy", until the one-hour age check in `_execute_deployment` finally cleared it.

## Evidence (host-clone-1, 2026-10-18, UTC)
- `pokemon-long-play-jev` (`41668f61`): row `b9d57a77` started 09:00, the host restarted under it, and it was only
  marked failed at 10:00 ("ran for 1.0 hours"). Row `fd6c883f` started 10:15, the host restarted at 10:15:58, and it
  stayed `running` with no process behind it. The 10:30 and 10:45 fires were skipped as "host busy".
- Every `vpt-host` start logs `Error cleaning up stale executions: {'code': 414 ... URI too long}` at startup.
- The host's busy-device check (`get_devices_with_running_deployments`, `host_utils.py`) used the same list
  and logged `Error checking running deployments: ... 414` about every 30 s.

## Fix
- `backend_host/src/services/deployment_scheduler.py`: the startup stale-row query selects `running` rows with
  `deployments!inner(host_name)` and `.eq('deployments.host_name', host)`, with no id list.
- `backend_host/src/lib/utils/host_utils.py`: `get_devices_with_running_deployments` uses the same join filter and
  reads `device_id` from the embedded deployment.

The one-hour age check in `_execute_deployment` stays as the fallback for a run whose thread died without a restart.

## Not changed / open
- `vpt-host` restarted about every 20 minutes during 2026-10-18 (journal: `systemctl Stopping/Started vpt-host`). The
  cause is not identified here; it is what turns every run into an orphan. Find who restarts it before blaming the scheduler.
