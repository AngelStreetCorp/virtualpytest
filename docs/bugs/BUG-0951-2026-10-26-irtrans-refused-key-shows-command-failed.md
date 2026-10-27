# BUG-0951 — An IRTrans key the box refuses shows only "Command failed"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0951                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / remote (IRTrans)                              |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

An Apple TV on an IRTrans box (`DEVICE2_IR_REMOTE=AppleTv`, `IR_TYPE=apple_tv`, `IR_LED=14`) did not
react to the Take Control panel, while the same key sent from the IRTrans web UI worked. The browser
console only said `[@hook:useInfraredRemote] Command failed: Command failed`, so nothing told the
operator whether the box did not know the remote, did not know the command, or the keymap was missing.

## Root cause

`IRTransRemoteController.press_key` reads the box's `RESULT` line (BUG-0755) and records it in
`_last_send_error`, but `execute_command` returned only `{'success': False}`. The host route and the
server proxy pass the controller's dict through unchanged, and `useInfraredRemote` shows
`result.error || 'Command failed'`, so the reason was dropped on the host.

## Fix

`backend_host/src/controllers/remote/irtrans.py`: a failed `press_key` returns
`{'success': False, 'error': <reason>}` — the box's refusal (`IRTrans refused LEFT: RESULT Error: …`),
an unmapped key, or the missing keymap when the controller never connected.

## Verification

Press a key on an IRTrans device whose box refuses it: the console line becomes
`Command failed: IRTrans refused <KEY>: <box reply>` instead of `Command failed: Command failed`.
