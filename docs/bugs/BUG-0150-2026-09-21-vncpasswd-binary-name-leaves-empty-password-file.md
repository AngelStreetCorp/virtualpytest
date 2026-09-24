# BUG-0150 — `install_host.sh` wrote an empty VNC password file on Raspberry Pi OS and carried on

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|-----------------------------------------------------------------------|
| ID        | BUG-0150                                                              |
| Reported  | 2026-09-21                                                            |
| Status    | Fixed (pending deploy)                                                |
| Severity  | Medium (VNC unusable on a fresh Pi host; failure is silent)           |
| Area      | `setup/local/linux/backend_host/install_host.sh`, `backend_host/docker/scripts/entrypoint.sh` |
| Fixed in  | Unreleased                                                            |
| Commit    | `abbc26a80b`                                                          |

---

## Symptom

On a freshly provisioned Raspberry Pi host, `install_host.sh` completes successfully and prints
`✅ VNC password set to: <password>`. `vpt-vnc.service` starts and listens on 5901. But
`/var/lib/vpt_user/.vnc/passwd` is **0 bytes**, so the VNC server rejects every connection — with
nothing in the install output or the service log pointing at the password file.

## Cause

Two independent faults that combine into a silent failure.

**1. The binary has a different name.** `install_host.sh` installs `tigervnc-tools` (line 143) and
then calls `vncpasswd` (line 558). On Debian bookworm / Raspberry Pi OS, `tigervnc-tools` ships
the binary as **`tigervncpasswd`** — there is no `vncpasswd` on PATH:

```
$ dpkg -L tigervnc-tools | grep bin
/usr/bin
/usr/bin/tigervncpasswd
```

So the call fails with `vncpasswd: command not found`. On distros where a `vncpasswd` alias does
exist the script works, which is why this went unnoticed.

**2. The failure cannot surface.** The call is the middle of a pipeline:

```sh
echo "$HOST_VNC_PASSWORD" | vncpasswd -f | sudo tee "$VNC_HOME/.vnc/passwd" > /dev/null
```

A pipeline's exit status is that of its **last** command, and `tee` succeeds — it just writes
nothing. The surrounding block also runs under `set +e`. So a missing binary produces an empty
file, exit status 0, and the unconditional `✅ VNC password set to: …` on the next line.

`backend_host/docker/scripts/entrypoint.sh:44` has the same `vncpasswd` call (redirect rather than
`tee`, so the file is created empty by the shell before the command fails).

## Fix

Resolve whichever binary exists, and verify the result is non-empty rather than trusting the
pipeline's exit status:

```sh
VNCPASSWD_BIN="$(command -v vncpasswd || command -v tigervncpasswd || true)"
if [ -z "$VNCPASSWD_BIN" ]; then
    echo "❌ neither vncpasswd nor tigervncpasswd found — install tigervnc-tools"
    exit 1
fi
echo "$HOST_VNC_PASSWORD" | "$VNCPASSWD_BIN" -f | sudo tee "$VNC_HOME/.vnc/passwd" > /dev/null
...
if [ ! -s "$VNC_HOME/.vnc/passwd" ]; then
    echo "❌ $VNC_HOME/.vnc/passwd is empty — $VNCPASSWD_BIN produced nothing"
    exit 1
fi
```

Applied to both call sites. `docs/get-started/production-checklist.md` documented the same
`vncpasswd -f` recovery command to operators and now notes the Debian/Raspberry Pi OS binary name
and the non-empty requirement.

## How it was found

Provisioning `vpt-pi4` (Raspberry Pi 5, Raspberry Pi OS bookworm) as a full host. The VNC password
step was run by hand rather than via `install_host.sh`, which is the only reason the empty file was
noticed — `stat -c%s` on the result showed `0` immediately after a step that had reported success.

## Verification

On vpt-pi4, using `tigervncpasswd`, `/var/lib/vpt_user/.vnc/passwd` is 8 bytes and `vpt-vnc.service`
serves display `:1` on 5901 with `vpt-websockify` on 6080.

## Notes

The two faults are worth separating. The binary name is a portability bug and would have surfaced
on the first Pi install either way. The silent-success is the more dangerous one: any future
failure of that command — missing package, read-only path, bad permissions — would produce exactly
the same empty file and the same green checkmark. The `-s` check is what prevents the next
variation of this.
