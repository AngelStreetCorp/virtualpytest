# BUG-0767 — IRTrans raw keys refused: the LED was written after a comma

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0767                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host                                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On a client with an IRTrans Multistream V3.1 16 Port (LAN L5.12.26) behind an nginx UDP forward,
Apple TVs in raw mode (`IR_IP` set, no `IR_REMOTE`) never reacted. Take Control said
`press_key executed successfully`, the status dot was green, and `last_send_ok` was true.

## Root cause

`IRTransRemoteController.press_key` (`backend_host/src/controllers/remote/irtrans.py`) sent
`sndccf <ccf>,l<led>\r`. A capture on the proxy showed the box answering every one of them with
`**00055 RESULT Error: Illegal / not supported CCF Code`. The same code with no LED, or written
`sndccf <ccf> l<led>` / `sndccf l<led>,<ccf>`, got `RESULT OK`, and an EOS key sent that way
fired on LED 5 only. The controller also ignored the reply, and nginx (`proxy_responses 0`)
dropped it, so the refusal never surfaced.

## Fix

- `press_key` sends `sndccf <ccf> l<led>\r` in raw mode (named `snd <remote>,<cmd>,l<led>` is unchanged).
- It reads the box's `RESULT` line (0.3 s): `Error` → the key fails with the box's message
  (status dot red, error in the toast). No reply (a proxy that drops it) still counts as sent.
- Doc: `docs/agent/devices/INFRARED.md` §2b, including the web interface and the `.rem` timing lesson.

## Client patch

- patch-2 (`patch/patch_host_2_irtrans-any-device.sh`) now carries this `irtrans.py` and the
  BUG-0754 `ir_conf/apple_tv.json` (official Apple codes). Re-running it on a host that already
  has an older patch-2 updates both files.
- Apply on the host: `bash patch_host_2_irtrans-any-device.sh --check` (10 = needed), then
  `sudo bash patch_host_2_irtrans-any-device.sh`.
- Verify: Take Control on the Apple TV, press RIGHT; the journal shows
  `Sending RIGHT -> 'sndccf … l13\\r'` and the Apple TV moves. Set `proxy_responses 1` on the
  nginx UDP block so a refused key shows as an error.
- Undo: `sudo bash patch_host_2_irtrans-any-device.sh --rollback`.

## Verification

- Payload format against a local UDP stub: raw sends `sndccf … l13\r`, a stub `RESULT OK` → True,
  a stub `RESULT Error: …` → False with the message, named sends `snd samsung,RIGHT,l13\r`.
- patch-2 on a scratch tree: `--check` 10, apply (files written and compiled), `--check` 0, `--rollback` restores.
- On the client box: `sndccf <ccf> l5` and `sndccf l5,<ccf>` → `RESULT OK` and only the EOS on LED 5
  reacted; `<ccf>,l5` → `Illegal / not supported CCF Code`.
