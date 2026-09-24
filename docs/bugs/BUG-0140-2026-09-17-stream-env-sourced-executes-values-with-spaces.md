# BUG-0140 — The stream service `source`d the host `.env`, so any value with a space was blanked and run as a command

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0140                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed (pending deploy beyond host-clone-1)                                  |
| Severity  | Medium (every device whose name contains a space had an empty name in the grabber; arbitrary shell from a privileged config file) |
| Area      | `backend_host/scripts/run_ffmpeg.sh`                                        |
+| Fixed in  | build 9151                                                          |

---

## Symptom

`journalctl -u vpt-stream` after adding a device slot:

```
/dev/fd/63: line 15: slot: command not found
/dev/fd/63: line 21: S23: command not found
/dev/fd/63: line 32: Galaxy: command not found
```

Nothing visibly failed — the grabbers started and the streams ran — so it read as noise.

## Root cause

```bash
set -a
source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | grep -v '^x')
set +a
```

`source` is bash, and to bash

```
DEVICE3_NAME=Sauce S23 FE
```

is **an assignment followed by a command**: `DEVICE3_NAME=Sauce` applies only to the
environment of the command `S23 FE`. So the variable is left holding `Sauce`… and in the
subshell that runs, nothing keeps it at all — the exported value is **empty** — while `S23` is
executed and fails.

Measured against the real `.env` on a host, comparing `source` with a literal reader over all
36 keys:

```
DEVICE2_NAME=                 ← source        DEVICE2_NAME=Phone slot 1        ← literal
DEVICE3_FARM_DEVICE=          ← source        DEVICE3_FARM_DEVICE=Samsung Galaxy S23 FE
DEVICE3_NAME=                 ← source        DEVICE3_NAME=Sauce S23 FE
```

The other 33 keys were byte-identical. So this is not a farm-device problem: `DEVICE2_NAME` on
an ordinary phone slot was already empty inside the stream service, and had been for as long as
that slot has had a two-word name.

The second half is the part worth taking seriously: **a value in the `.env` is executed as
shell**. `FOO=a $(command)` in that file runs `command` as the stream service's user. The file
is root/`vpt_user`-owned so this is not remotely reachable, but a config value should never be
code, and this one is — including values that arrive by copy-paste from a vendor console.

## Fix

Read `KEY=VALUE` literally and export it, reproducing the two things `source` legitimately did —
stripping a ` # inline comment` and surrounding quotes — and nothing else. A value is data: never
expanded, never executed.

## Gate

A side-by-side comparison over the real host `.env`: the literal reader is identical to `source`
for all 36 keys except the three with spaces, which it gets **right** where `source` returned
empty. Then, on `host-clone-1`: `systemctl restart vpt-stream` → **zero** `command not found`
lines, all three grabbers (`device2`, `device3`, `host`) started, and frames continued to land
(`capture2` 119 captures / 25 segments, `capture3` 73 / 15).

## Found while

Wiring the first cloud-farm device onto a real host ([TASK-20](../tasks/TASK-20-device-farm-integration.md)).
The farm slot has two space-containing values (`DEVICE3_NAME`, `DEVICE3_FARM_DEVICE`), which made
an old and quiet bug loud enough to notice.
