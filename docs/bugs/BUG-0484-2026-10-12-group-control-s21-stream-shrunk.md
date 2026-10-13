# BUG-0484 — Group control shows the S21 stream shrunk in its tile

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0484                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend · rec · Group control                               |
| Fixed in  | Unreleased                                                   |
| Commit    | 632f021c9                                                    |

---

## Symptom

In Group control (ADB, two phones) the Galaxy S21 tile showed the phone as a small picture in
the middle of a black tile, while the S7 tile filled its height. Taking control of the S21 alone
showed it at full size.

## Root cause

The S21 streams a 16:9 landscape frame with its portrait screen pillarboxed in the middle; the
S7 streams a portrait frame. The group tile renders `RecHostPreview`, which always uses
`objectFit: 'contain'`, so the S21's whole 16:9 frame — black bars included — was fitted into
the tile. The single-device Take Control panel instead puts a phone in a 9:16 box with
`objectFit: 'cover'`, which crops the bars away.

## Fix

`RecHostPreview` takes a `fillMobileFrame` prop that switches phones to `cover` (live player,
WebRTC player and the snapshot image). `GroupStreamCell` gives a phone member a centred 9:16
box and sets it, matching the Take Control panel.
