# BUG-0505 — `supervisorctl status` reported `adb` FATAL on every Docker host, while adb was working

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0505                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / docker                                        |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

On the GCP standalone showcase (`vpt-gcloud-standalone`, host container `vpt-gcloud-host`):

```
adb                              FATAL     Exited too quickly (process log may have details)
transcript_accumulator           STOPPED
```

and in the container log, four spawn/exit cycles in about 7 seconds followed by a give-up:

```
INFO spawned: 'adb' with pid 319
WARN exited: adb (exit status 0; not expected)
INFO spawned: 'adb' with pid 559
WARN exited: adb (exit status 0; not expected)
INFO gave up: adb entered FATAL state, too many start retries too quickly
```

The same log goes on to report `✅ Registered ADB verification`, `/usr/bin/adb` present and
`Android Debug Bridge version 1.0.41` — the alarm and the working feature sit next to each other.

## Root cause

`backend_host/docker/supervisord.conf:62` ran:

```ini
[program:adb]
command=adb start-server
autorestart=true
```

`adb start-server` **daemonizes**. It forks the real server into the background and the parent
exits **0 immediately**; supervisord is supervising a *foreground* process, so a clean exit 0 is
classified as "not expected", retried, and after `startretries` exhausted it declares FATAL.

**adb is functionally fine — only the supervision is wrong.** The server supervisord gave up on was
still running, as an orphan nobody supervised (confirmed below: `adb -L tcp:5037 fork-server server
--reply-fd 4`, `PPID 1`). Every host of a type with no Android device shows the FATAL, because the
retry storm happens whether or not a device exists.

The block dates from the initial open-source snapshot — `git log -S "program:adb" --
backend_host/docker/supervisord.conf` returns only `703263e54` — so this is long-standing and not
caused by any recent change.

`transcript_accumulator` (`supervisord.conf:149`) is `autostart=false`: deliberately not started, so
`STOPPED` is the correct expected state. Left alone.

## Fix

`backend_host/docker/supervisord.conf` now supervises the adb **server** in the foreground, so
supervisord has a real long-running process to watch, stop and restart:

```ini
command=/usr/bin/adb -L tcp:5037 nodaemon server
startsecs=5
startretries=3
```

`nodaemon server` is adb's foreground server mode (the same form Debian/Ubuntu's own `adb.service`
uses). The change of trade-off between the two candidate fixes:

- **`exitcodes=0` / `autorestart=false` / `startretries=0`** on `adb start-server` would silence the
  alarm while leaving the server a daemonized orphan — exactly today's behaviour, with no restart if
  it dies and no `RUNNING` line to read.
- **foreground supervision** makes adb a process supervisord actually manages: `kill -9` on it now
  produces a clean respawn instead of an unsupervised corpse.

`-L tcp:5037` is deliberately explicit: it is the exact listen endpoint the auto-started server had
(`ps` shows `adb -L tcp:5037 fork-server server`), so the client-visible endpoint is unchanged.

## Verification

Run against the published host image `ghcr.io/angelstreetcorp/virtualpytest-host:main-2026.09.26-9374`
(Docker 29.1.3), same image `backend_host/Dockerfile:27` installs `android-tools-adb` from.

**The bug, reproduced** — container run with the image's own config:

```
adb                              FATAL     Exited too quickly (process log may have details)
2026-10-13 11:21:25 INFO spawned: 'adb' with pid 11
2026-10-13 11:21:26 WARN exited: adb (exit status 0; not expected)
... (4 spawn/exit cycles)
2026-10-13 11:21:32 INFO gave up: adb entered FATAL state, too many start retries too quickly
```

while adb itself worked: `adb devices` exited 0 and the server was running as an orphan
(`21  1  adb -L tcp:5037 fork-server server --reply-fd 4`).

**The fix** — same image, repo `supervisord.conf` bind-mounted over the image's copy:

```
adb                              RUNNING   pid 10, uptime 0:00:29
2026-10-13 11:23:22 INFO spawned: 'adb' with pid 10
2026-10-13 11:23:27 INFO success: adb entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
```

One spawn, no retries, no FATAL.

### Android hosts are not regressed

`/usr/bin/adb` on Debian 1.0.41 is an ELF binary, not the old wrapper script, so the mode was
verified on the exact build the image ships:

- `timeout 10 adb nodaemon server` → exit **124**: it stayed in the foreground (not daemonized).
- `adb -L tcp:5037 nodaemon server` runs as a long-lived process, and `supervisorctl` reports the
  **same pid** as `ps` (pid 10) — the supervised process is the real server, not a wrapper.

Every command shape the controllers actually use was run against the supervised server:

| Command | Result |
|---|---|
| `adb version` | `1.0.41 / 34.0.5-debian` |
| `adb devices` | exit 0 |
| `adb -s 127.0.0.1:5555 shell echo hi` | `device '127.0.0.1:5555' not found` — a **server-side** reply, so `ADBUtils.execute_key_command`'s `adb -s <id> shell …` shape is served |
| `adb connect 127.0.0.1:1` | `failed to connect … Connection refused` — the TCP connect path reaches the server |

Two resilience checks, both of which mean a device host cannot lose adb:

1. **supervisord restarts it** — `kill -9 10` → `WARN exited: adb (terminated by SIGKILL; not
   expected)` → respawned as pid 448 → `RUNNING` again.
2. **clients self-heal anyway** — with the program stopped and *no* server listening, one ordinary
   client call restarted it by itself:
   ```
   * daemon not running; starting now at tcp:5037
   * daemon started successfully
   List of devices attached
   ```
   So Android hosts never depend on supervisord's adb being up: `adb -s ip:port` auto-starts a
   server, exactly as before this change.

The container under test is not Android-capable, so this verifies the client↔server path and the
command shapes, **not** a real `emulator-5554` session. Two other programs (`stream`, `xfce4`) are
FATAL in this ad-hoc run because the entrypoint was bypassed (no stream media, no `dbus-launch`);
they are unrelated to this change and were not investigated.

## Not verified here

A real Android device or emulator attached to the container. The Docker host service publishes no
`5037` and mounts no `/dev/bus/usb` (`setup/docker/docker-compose.yml`), so devices are reached over
TCP as `ip:port` / `adb_serial`; that path is exercised above as far as it can be without hardware.