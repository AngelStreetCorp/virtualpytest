# BUG-0749 — One misspelled `DEVICE{n}_MODEL` gave a device with no controllers at all

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0749 |
| Reported  | 2026-10-21 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium — one character in a `.env` and the device is registered but cannot be driven, with no usable hint in the log |
| Area      | `shared/src/lib/config/device_capabilities.py`, `backend_host/src/controllers/controller_config_factory.py`, `backend_host/src/controllers/controller_manager.py`, `backend_server/src/routes/server_devicemodel_routes.py`, `backend_host/scripts/run_ffmpeg.sh` |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Symptom

`DEVICE4_MODEL` in a host `.env` was written `androidtv` instead of `android_tv`. The host
started cleanly, the device appeared on the dashboard, it streamed, it had a name — and
Take Control answered *"Unsupported device: androidtv"*. No remote, no keys, no
verification. The same thing happened with `appletv`, `firetv_vega`, `firetv`, and with
`andoridtv` — the transposition of the `r` and the `o` that everyone makes when typing
that name from memory.

The factory logged `ERROR: Unknown device model: androidtv` and listed the real names,
which is accurate and useless: the operator had no way to know which of the names they
had half-remembered was the right one, and the obvious guesses all failed identically.

## Root cause

A model name was used as a bare string key, in four places, with no normalization
anywhere:

| Where | What it did with the raw value |
|---|---|
| `controller_manager._get_devices_config_from_environment` | `raw_model.partition('-')` — split the platform tag, kept the spelling verbatim |
| `controller_config_factory.create_controller_configs_from_device_info` | `DEVICE_CONTROLLER_MAP[device_model]` — a miss returned `{}` |
| `controller_config_factory.get_controller_type_for_device` | same lookup, with a default-routing fallback for a miss |
| `server_devicemodel_routes._unsupported_model_error` | `name in DEVICE_CONTROLLER_MAP` → 400 with the list of real names |

`DEVICE_CONTROLLER_MAP` has 24 keys, several of which differ only by an underscore
(`android_tv` / `androidtv`), by a suffix (`fire_tv_fireos` / `fire_tv_vega`) or by case.
The cost of a miss was not cosmetic. `create_controller_configs_from_device_info`
returning `{}` means the device registers with **no controllers at all** — so it is not
"the remote is missing", it is "this device cannot be driven, and no panel can say which
controller it wanted".

There was a second, quieter asymmetry. `run_ffmpeg.sh` also reads `DEVICE{i}_MODEL`
(`override_kind_for_model`) to decide whether the device takes a runtime URL / file
source override. That was a literal `case`, so `DEVICE2_MODEL=rtspvideo` would have built
a perfectly good device in Python and then silently ignored its runtime source switch.

## Fix

One resolver, in `shared/src/lib/config/device_capabilities.py` next to the map it
resolves against, applied at every entry point that reads a model. Three passes, cheapest
first, all **derived from the map keys** so a model added later needs no entry:

1. **exact** — `android_tv`
2. **separator-free** — `androidtv`, `ANDROID_TV`, `Android TV`, `android-mobile`,
   `firetv_vega`, `appletv`
3. **near miss** — `andoridtv` → `android_tv` (0.889), `firetv_ios` → `fire_tv_fireos`
   (0.857), `stbb` → `stb`

Pass 3 fires only when the winner also beats the runner-up by a margin, so two names that
are genuinely different models are never collapsed into one.

`parse_device_model()` does the existing platform-tag split (`stb-example-v2` →
`stb` + `example-v2`) and the spelling resolution in one place. It tries the **whole**
value as a model first, without pass 3, so a separator spelling (`android-mobile`) is
read as the model `android_mobile` rather than as the unknown model `android` carrying
the tag `mobile`, while `android_tv-v2` keeps its tag.

### What is deliberately NOT guessed

Tolerance is not a licence to invent a device:

| Written | Resolves to | Why |
|---|---|---|
| `android` | unknown | the android family has four completions — mobile, tv, tablet, cloud — and the factory lists them |
| `runner` | unknown | same, for `runner_host` / `runner_android_*` |
| `ios` | unknown | `ios_mobile` or `cloud_ios_mobile` |
| `rtsp-video-2` | unknown | a numbered variant is a different naming convention, not a spelling |
| `samsung_tv` | unknown | a real device type this project has no controllers for — not a typo |

An unknown value still comes back "unknown in, unknown out", so the factory keeps
reporting `ERROR: Unknown device model` and listing the real names. A device built out
of the wrong model is worse than no device, because it looks alive and answers to
controls that cannot work.

### One family name, chosen and logged

A bare `fire_tv` / `firetv` names a family, not a model, and no amount of string
similarity resolves it (`fire_tv` → `fire_tv_vega` scores only 0.75, below the cutoff).
It is the one explicit entry in `MODEL_ALIASES`, and it resolves to `fire_tv_fireos`
(Fire OS): the common case, since Vega has its own model name. The correction is **logged
at every entry point** — `DEVICE4_MODEL: 'fire_tv' read as 'fire_tv_fireos'` — so the
choice is visible rather than silent, and a Vega-only fleet changes that one line rather
than its `.env` files.

### Server side

`_unsupported_model_error` resolves the name the same way a host does, so Add Model
accepts `appletv` instead of refusing it by a rule the host does not have. Create and
update **store the canonical spelling**: rows are matched by name against userinterface
`models[]` and resolved to a family (BUG-0144), both of which compare against the
canonical names, so a row stored as `appletv` is invisible to both — and `androidtv` can
no longer be added as a second row for a model already stored as `android_tv`.

## Tests

`tests/backend_host/test_device_model_normalization.py` — 99 tests:

- every canonical model is a fixed point of its own resolver (the guard that keeps the
  fuzzy pass safe as models are added)
- the alternative spellings, the near misses, and the ambiguous values that must stay
  unknown
- the platform tag surviving a corrected model, and `android-mobile` reading as a model
  rather than a tag
- the factory building an **identical** config dict for `androidtv`, `andoridtv`,
  `appletv`, `firetv_vega`, `firetv_ios`, `stbb`, `rtspvideo` and `hostvnc` as for their
  canonical names, and still returning `{}` for a genuinely unknown model
- `override_kind_for_model` sliced out of the **real** `run_ffmpeg.sh`, so editing the
  shell logic breaks the test

## Notes

- `backend_host/src/.env` (untracked, local) makes one pre-existing
  `test_tv_lite_profile.py` parametrization disagree between the bash and python
  resolvers; it is unrelated to this fix and fails the same way without these changes.
- 12 pre-existing ruff findings in the two controller modules are untouched.