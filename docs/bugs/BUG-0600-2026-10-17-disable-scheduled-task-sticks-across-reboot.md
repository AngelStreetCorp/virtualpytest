# BUG-0600 — `Disable-ScheduledTask vpt-*` sticks across reboots; hosts drop from dashboard

## Problem

The vpt-windows install (and every Windows native install going forward)
runs the host_vnc host_api (`vpt-host`), the desktop capture pipeline
(`vpt-stream`) and the desktop audio capture pipeline
(`vpt-windows-audio`) as Scheduled Tasks with a `LogonTrigger`. On a
clean install, `Register-ScheduledTask -Force` and `schtasks /create /f`
both create the task in the `Ready` state — the trigger will fire on the
next logon and the wrapper will start.

A debugging round that runs `Disable-ScheduledTask vpt-host` (or
`schtasks /change /disable`) leaves the task in the `Disabled` state.
`Disabled` is a sticky state — `LogonTrigger` does not fire for
`Disabled` tasks, so after the next reboot the wrapper never restarts,
vpt-host never binds port 6109, and the host never re-registers with
vpt-pi4's `getAllHosts`. The Dashboard then shows the host missing,
with no error visible on the host itself (the wrapper simply never
ran).

This is what happened on 2026-10-17: a manual vpt-host wrapper was
started via `host_wrapper.ps1` from ssh to debug a `termios` import
crash, the operator (me) left the `vpt-host` task `Disabled` while the
manual wrapper ran, the box rebooted at 10:44, came back at 13:20,
the manual wrapper was gone, and `vpt-windows` dropped out of
`getAllHosts` until the task was re-Enabled manually at 19:55.

## Fix

`setup/local/windows/backend_host/install_host_windows.ps1`:

- New `Ensure-TaskEnabled` helper:
  ```powershell
  function Ensure-TaskEnabled {
      param([Parameter(Mandatory = $true)] [string]$TaskName)
      $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
      if ($t.State -ne 'Ready') {
          Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
          Write-Log "Re-enabled scheduled task (was $($t.State)): $TaskName"
      }
  }
  ```
- Called at the end of `Install-StreamScheduledTask`,
  `Install-WindowsAudioTask`, and `Install-HostScheduledTask`. The
  next `.\install_host_windows.ps1` run (or any boot where the
  install is re-run) flips a stuck-`Disabled` task back to `Ready`
  and the wrapper restarts on the next logon.

The fix is small and intentionally idempotent: a clean install never
sees a state change, a debugging-induced `Disabled` gets undone on
the next installer run.

## Verification

`scripts/_test_ensure_task.ps1` exercises the helper against all
three vpt-windows tasks on the live box:

1. Snapshot state (was `Running`).
2. `Stop-ScheduledTask` to flush the state back, then
   `Disable-ScheduledTask` — state becomes `Disabled`.
3. Call `Ensure-TaskEnabled` — state flips to `Ready`.
4. `Start-ScheduledTask` — wrapper restarts.
5. `Get-ScheduledTaskInfo` — `LastTaskResult` 267009 (success).
6. `Get-NetTCPConnection -LocalPort 6109` — listener back.
7. `GET /server/system/getAllHosts` on vpt-pi4 — `vpt-windows` listed
   again with `device_count=2` (`Host_Windows` + `Mobile_Emulator`).

Output (2026-10-17 20:08, vpt-windows):

```
=== vpt-host ===
  Before: State = Running
  After disable: State = Disabled
  Re-enabled (was Disabled) -> Ready
  After fix: State = Ready
  PASS (state = Ready)

=== vpt-stream === ... PASS (state = Ready)
=== vpt-windows-audio === ... PASS (state = Ready)

=== Summary ===
  PASS: vpt-host is Ready
  PASS: vpt-stream is Ready
  PASS: vpt-windows-audio is Ready
```

After the test, `Start-ScheduledTask` on all three, then on vpt-pi4:

```
Total hosts: 4
  - vpt-pi4     device_count=4  status=online
  - vpt-lenovo1 device_count=7  status=degraded
  - vpt-nipogi  device_count=24 status=online
  - vpt-windows device_count=2  status=online
```

## Related (not in this commit)

The `vpt-test` Scheduled Task is also `Disabled` on vpt-windows. The
install script doesn't currently manage `vpt-test` (it predates this
hardening work and is set up by hand). If a future install path adds
`Install-TestScheduledTask`, it should call `Ensure-TaskEnabled
-TaskName vpt-test` too.