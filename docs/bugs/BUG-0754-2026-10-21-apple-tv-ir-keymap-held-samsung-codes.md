# BUG-0754 — The Apple TV IR keymap held the Samsung TV codes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0754                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host                                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A device with `DEVICEn_IR_TYPE=apple_tv` (lirc, IR Toy or raw IRTrans) sent codes the
Apple TV ignored.

## Root cause

`backend_host/src/controllers/remote/ir_conf/apple_tv.json` was a copy of `samsung.json`
since the initial snapshot: every frame decodes to address `0x0707` (Samsung32), not Apple's
NEC address `0x87EE`.

## Fix

The file now holds the official Apple remote codes (NEC, 9000/4500 header, address `0x87EE`,
remote ID `0x01`): POWER `0x18`, UP `0x0A`, DOWN `0x0C`, LEFT `0x09`, RIGHT `0x06`,
MENU `0x03`, OK `0x5C`, PLAY/PAUSE `0x5F`, FORWARD `0x1A` and REWIND `0x1C` (both on the
`0x87E5` address). BACK is MENU and PLAY, PAUSE and PLAY_PAUSE are the one play/pause toggle,
as on the real remote. HOME, volume, channel and mute have no code in the set and are empty
("not mapped"); an Apple TV that should drive a Samsung TV keeps `IR_TYPE=samsung`.

## Verification

Each code was decoded back to its NEC address and command. Not yet tested on a live Apple TV.
