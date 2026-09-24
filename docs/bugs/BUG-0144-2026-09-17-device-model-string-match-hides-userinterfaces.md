# BUG-0144 — A phone reached a different way could not see its own userinterfaces or scripts

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0144                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed (pending deploy)                                                       |
| Severity  | Medium (no data loss, but the platform silently hid the right answer and invited duplicate trees) |
| Area      | `shared/src/lib/config/device_capabilities.py`, `frontend/src/config/deviceModelFamilies.ts`, six matchers |
| Fixed in  | Unreleased                                                                   |
| Commit    | TBD                                                                          |

---

## Symptom

On the UserInterface page, one Android phone had grown three near-identical entries:

| userinterface | models |
|---|---|
| `youtube-android-mobile` | `android_mobile`, `phone_agent` |
| `phone_home` | `phone_agent` |
| `cloud_farm_demo` | `cloud_android_mobile` |

Selecting a paired phone or a cloud farm phone in Run Tests, the Campaign builder or the
TestCase builder offered **only** the userinterface whose `models[]` happened to spell that
exact model — the dozen trees already written for an Android phone were not listed. The same
went for scripts: one declaring `_target_rules.device_model: android_mobile` was filtered out
of Run Tests for a farm phone, which is precisely a device it was written for.

The workaround people had found was to add the second model chip by hand
(`youtube-android-mobile` still carries it) or, failing that, to build a parallel tree —
`cloud_farm_demo`.

## Root cause

Model matching was string equality, `models.includes(device_model)`, duplicated in six
places with no shared table:

- `backend_server/src/routes/server_userinterface_routes.py` (`getCompatibleInterfaces`)
- `backend_server/src/mcp/tools/device_tools.py`
- `backend_host/src/lib/utils/host_utils.py`
- `frontend/src/utils/userinterface/deviceCompatibilityUtils.ts`
- `frontend/src/contexts/HostManagerProvider.tsx`
- `frontend/src/pages/CampaignBuilder.tsx` (an inline copy that did not even use the shared util)

Plus two narrow alias tables that each covered a different half of the problem and neither
covered phones: `host_vnc → web, desktop` in the route, and runner↔physical
`COMPATIBLE_MODEL_GROUPS` in `frontend/src/utils/targetCompatibility.ts`.

`android_mobile`, `phone_agent` and `cloud_android_mobile` are one Android phone reached over
adb, over the paired app, and through a cloud farm. Nothing in the codebase said so, so
nothing could act on it.

## Fix

One family table, `MODEL_FAMILIES`, in `shared/src/lib/config/device_capabilities.py` with a
TypeScript mirror in `frontend/src/config/deviceModelFamilies.ts`. All six matchers and the
script-target filter go through it; `CampaignBuilder`'s inline copy was replaced with the
shared `filterCompatibleInterfaces`. An unlisted model is its own family, so anything not
named degrades to exact matching rather than to matching everything.

The asymmetric `host_vnc` rule stayed asymmetric, in `MODEL_EXTRA_MATCHES`: a VNC host can run
a `web` userinterface, but a `web` device cannot run a `host_vnc` one — that tree is full of
desktop actions Playwright cannot execute. Folding it into a family would have introduced the
opposite bug.

**A family is a promise that the same tree runs on every member**, so the cloud side had to be
brought up to it — three real gaps that would otherwise have turned a hidden userinterface into
a failing run:

| Gap | Fix |
|---|---|
| an `android_mobile` tree's screen checks are `verification_type: 'adb'`; the farm registered only `appium` | `features/device-farm/backend_host/__init__.py` registers the cloud controller under both types, on the one lease (no second billed device) |
| the swipe family was Unknown command on Appium | `appium_remote.py` gains `swipe`/`swipe_up`/`swipe_down`/`swipe_left`/`swipe_right` with android_mobile's defaults, over `appium_utils.swipe` (W3C pointer actions) |
| `waitForElementToChange` / `waitForElementToStopChanging` were adb-only | `verification/appium.py` now shares `element_watch` with the adb and paired-phone controllers, translating Appium's `contentDesc`/`className` spelling |

While comparing the two catalogues, `click_element_by_id` turned out to have the same
empty-dump trap [BUG-0138](BUG-0138-2026-09-17-appium-click-searches-an-empty-cache.md) fixed for
`click_element`: it read `self.last_ui_elements` without dumping, so on a fresh controller the id
resolved against an empty list and the click silently did nothing. It now dumps first, and is
offered in the action catalogue.

## Gate

- `tests/shared/test_device_model_families.py` — 27 tests. Includes `TestFamiliesAreHonest`,
  which fails the build if a family member's remote stops backing `adb`, and
  `TestTypeScriptMirrorMatches`, which parses the `.ts` mirror and compares it with the Python
  table so the two cannot drift.
- `tests/frontend/deviceModelFamilies.test.ts` — 22 tests over the three frontend matchers.
- `tests/backend_host/test_appium_android_parity.py` — 18 tests; the catalogue comparison is a
  set difference, so a command added to `android_mobile` and not to Appium fails here.
- `tests/backend_host/test_device_farm.py` — `adb` is in the built controller set and shares the
  one session; `tests/backend_host/test_appium_click_dumps_first.py` covers `click_element_by_id`.

## Not done

`cloud_farm_demo` and `phone_home` are left in the database. They are now reachable from any
Android phone and vice versa, so they are harmless; whether they are worth keeping as trees is
a content decision, not a code one.

## Found while

Reviewing the UserInterface page after the device-farm feature shipped
([TASK-20](../tasks/TASK-20-device-farm-integration.md)) — `cloud_farm_demo` sitting beside
`youtube-android-mobile` was the tell.
