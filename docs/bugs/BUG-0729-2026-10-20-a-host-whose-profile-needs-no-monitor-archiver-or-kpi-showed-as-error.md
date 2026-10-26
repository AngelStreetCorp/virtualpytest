# BUG-0729 — A host whose profile needs no image monitoring, archiver or KPI showed as "error"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0729                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium (every host with such a profile reads as broken on the dashboard) |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | d4c34c6ab                                                    |

---

## Symptom

The Hosts page showed a healthy host as **error**, right after a deploy, with nothing wrong on it:

```
host-clone-2   | error   | current:main-2026.10.20-89444
labox-backend  | error   | current:main-2026.10.20-89444
```

The host answered `GET /health` with `"status":"ok"`, ran its web script runs, and its
critical services (`vpt-host`, `vpt-vnc`, `vpt-websockify`) were active. Only the services the
host's monitoring profile does not want were stopped:

```
vpt-host             active
vpt-monitor-img      inactive
vpt-archiver         inactive
vpt-kpi              inactive
vpt-vnc              active
vpt-websockify       active
```

## Root cause

Two changes that should agree did not.

**TASK-144** stops the profile-driven services that no device on the host needs. The host's
applied profile record says so:

```json
{"profiles": {"host": "pc"}, "services": {"img": [], "audio": [], "subtitle": [], "archiver": [], "kpi": [], "avq": []}}
```

**The host status** counted `vpt-monitor-img`, `vpt-archiver` and `vpt-kpi` as critical on every
non-runner host and turned any of them being stopped into `overall_status: error`
(`backend_host/src/lib/utils/system_info_utils.py`):

```python
critical_services = [s for s in services if s.get('critical', False)]
critical_statuses = {s.get('status', 'unknown') for s in critical_services}
if 'error' in critical_statuses or 'stopped' in critical_statuses:
    overall_status = 'error'
```

The critical flag is static (it depends on the device types on the host), so it did not know
that the profile had deliberately turned the service off. Every host whose devices run a profile
that needs none of them therefore reads as broken.

## Fix

`backend_host/src/lib/utils/monitor_profile.py` gained `units_not_needed()`: the units the
applied profiles say no device needs. The host status uses it — a service that is **stopped** and
in that list is not a failure:

```python
for service in services:
    if service.get('status') != 'stopped':
        continue
    unit = service.get('resolved_name') or service.get('name')
    if unit in not_needed_units:
        service['critical'] = False
        service['not_needed'] = True
```

A service that some device **does** need and that is stopped still makes the host `error`, and a
unit the host knows nothing about is still treated as needed (the safe direction).

## Verification

`tests/backend_host/test_host_status_not_needed_services.py` (5 tests):

- the units no device wants are listed from the applied profile record;
- a service a device wants is not in that list;
- an unknown profile record yields an empty list (nothing is downgraded);
- a stopped service nobody needs is not a failure;
- a stopped service somebody needs still is.
