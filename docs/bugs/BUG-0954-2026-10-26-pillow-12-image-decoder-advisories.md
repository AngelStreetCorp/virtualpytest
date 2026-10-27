# BUG-0954 — The backend decoded images with a Pillow that has critical decoder advisories

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0954                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Critical                                                     |
| Area      | backend / dependencies                                       |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

Publishing release `main-2026.10.26-90145` showed 35 open Dependabot alerts on the public
snapshot. 31 of them were already closed on internal `main` before the release (PyJWT 2.15.0,
certifi 2026.10.19 — BUG-0944, compression 1.8.2, brace-expansion 5.0.12) and only wait for the
public repo to be rescanned. What was really still open was **Pillow**, capped at
`>=12.3.0,<13.0.0` in `backend_server/requirements.txt` and `backend_host/requirements.txt`:
one critical advisory (GHSA-8g5g-8vmr-9782, JPEG decoder buffer overflow from scanlines wider
than tile extents), six high (TIFF/PDF/GIF decoding and encoding, ImageMorph) and two medium,
on each of the two manifests. Every patched version is `13.0.0`.

## Root cause

The `<13.0.0` cap was written when Pillow 12 was current, to stop an untested major from
arriving on its own. Pillow 13.0.0 is the first release with the fixes; there is no 12.x
backport.

## Fix

- `backend_server/requirements.txt`: `Pillow==13.0.0` (exact pin, so `update_core.sh`, which
  installs exact server pins the venv lacks, actually upgrades the running servers).
- `backend_host/requirements.txt`: `Pillow==13.0.0` (exact pin, for the same reason on the host
  side — BUG-0961: a host deploy installed no Python package at all, and a range pin is exactly what
  a deploy cannot act on).

Pillow 13's breaking changes were checked against the code: it drops Python 3.10 (every
server and host venv checked runs 3.11.2), and removes `Image._show`,
`Image.get_child_images()`, `ImageCms` `product_name/product_info`, `ExifTags.IFD.Makernote`,
the data-type-changing `fromarray(mode=…)` and silent clipping when saving `I` images as PNG.
None of these is used in `backend_server`, `backend_host`, `shared` or `scripts`. No installed
package pins `Pillow<13` (checked on the node1 server and host-clone-1 venvs).

Left open on purpose: `datasets <5.0.1` (GHSA-379c-qx7v-6h59) in `training/requirements.txt` —
unsloth 2026.10.9, the newest release, still requires `datasets<5.0.0`, and the platform never
imports `datasets`.

## Verification

1. 74 tests that decode images through PIL (`tests/shared/test_clashofclans_vision.py`,
   `test_leagueoflegends_vision_nav.py`, `test_leagueoflegends_target_hp.py`,
   `tests/backend_host/test_timeline.py`) pass in a venv with `pillow==13.0.0`.
2. After the server deploy, the server venv reports `13.0.0`:
   `/opt/virtualpytest/venv/bin/python -c "import PIL; print(PIL.__version__)"`.
   The server deploy of 2026-10-26 (`35748f94`, server scope) installed it on the node's server and
   on both Pi boxes: all three venvs report `13.0.0` (they were 10.4.0, 10.4.0 and 12.3.0).
3. The host venvs get it from the host deploy, once BUG-0961's host dependency step ships.
