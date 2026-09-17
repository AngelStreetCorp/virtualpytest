# `mobile-app` — optional feature

One Android APK (Capacitor shell around the web frontend) plus **phone-as-device**: a paired
phone streams its screen to a host over Socket.IO and takes taps, swipes, keys, text and app
launches from an AccessibilityService, so it shows up as a normal device of that host
(`device_model: phone_agent`).

The phone and tablet **layout** of the web UI (bottom nav, mobile Run Tests, responsive pages)
is **core**, not this feature: it serves every browser on a small screen and stays when this
feature is disabled. This feature owns only the APK shell and the phone-as-device path.

Packaged per `docs/technical/FEATURES.md`. Disable with `DISABLED_FEATURES=mobile-app`.

## Docs

| Audience | Page |
|---|---|
| Users (what it is, where to find it) | `docs/features/mobile-app.md` |
| Operators (slots, pairing, permissions, troubleshooting) | `docs/technical/MOBILE_APP.md` |
| Building the APK | `app/README.md` |
| Agents (pair from the API, fake phone, what works, isolation check) | `docs/agent/devices/PHONE_AGENT.md` |
| Design, wire protocol, decisions (internal) | `docs/tasks/TASK-17-mobile-app-phone-agent.md` |

## Parts

| Folder | What | Loaded by |
|---|---|---|
| `backend_server/` | `/server/mobile-app/*` — hosts with phone slots, create/delete pairings | `register_feature_blueprints` (core `app.py`) |
| `backend_host/` | `/host/phone/*` + Socket.IO `/phone` namespace (`bridge.py`), the `phone_agent` remote controller, the `adb`-type UI verification over the accessibility tree (`controllers/phone_ui_verification.py`), `phone_sim.py` (fake phone for tests), placeholder frame | `register_feature_blueprints` + `register_feature_controllers` (controller registry) |
| `frontend/` | Settings → *Mobile app & phones* (`/configuration/mobile-app`), *This phone* (`/mobile-app/this-phone`, native only), `native/phoneAgent.ts` plugin typings | `virtual:vpt-features` (vite plugin) via `routes.tsx` |
| `lib/` | `protocol.py` — event/command names, key map, QR payload, TTLs, shared by server + host | relative imports inside the feature |
| `db/` | `001_phone_agent_device_model.sql` — the `phone_agent` row in `device_models`, idempotent, per team | **manual** — see "DB" below |
| `app/` | Capacitor project: Kotlin plugin, foreground service, accessibility service, MediaProjection capture | never deployed; built by `app/scripts/apk.sh` |

## Core hooks this feature relies on (all inert when the feature is off)

This is the complete list; when it grows, add the line here and in the manifest description.

| Where | Hook |
|---|---|
| `backend_host/src/controllers/controller_registry.py` | `register_remote_implementation('phone_agent', …)`; `'phone_agent'` in the known-names list; `register_verification_implementation('phone_agent', 'adb', …)` — the verification registry is keyed by `(device_model, type)` so `'adb'` stays the real thing on `android_mobile` |
| `backend_host/src/controllers/controller_manager.py` | consults the registry before the built-in remote types **and** before the built-in verification types (per device model), passes `device_id` to every verification controller; calls `register_feature_controllers('backend_host')` so a script subprocess (no Flask app) also gets feature controllers (BUG-0108) |
| `backend_host/src/controllers/controller_config_factory.py` | asks the registry for the params builder of a feature-registered implementation |
| `shared/src/lib/utils/features.py` | `register_feature_controllers(part)` — generic, added for BUG-0108 |
| `shared/src/lib/config/device_capabilities.py` | the `phone_agent` model (`av: hdmi_stream`, `remote: phone_agent`); `CONTROLLER_VERIFICATION_MAP['phone_agent'] = ['adb']` (backed by the accessibility tree, see `controllers/phone_ui_verification.py`) |
| `shared/src/lib/models/device.py` | `to_dict` maps the controller class name to `'phone_agent'` |
| `shared/src/lib/utils/app_utils.py` | `https://localhost` / `capacitor://localhost` in the default CORS origins (the APK's fixed origin) |
| `backend_host/src/.env.example` | the commented phone-slot block (`xDEVICE3_MODEL=phone_agent`, `PHONE_AGENT_*`) |
| `frontend/src/config/runtimeConfig.ts`, `constants.ts`, `lib/supabase.ts` | `window.__VPT_CONFIG__` runtime config — shared with the Docker install, the APK serves it from native prefs |
| `frontend/src/hooks/useIsNativeApp.ts` | "am I inside the Capacitor shell" |
| `frontend/src/components/controller/remote/RemotePanel.tsx`, `config/remote/remotePanelLayout.ts` | `case 'phone_agent'` → the Android-mobile remote surface |
| `frontend/src/components/mobile/MobileBottomNav.tsx` | one More-menu entry (*Mobile App* on the web, *This phone* in the APK), gated on `isFeatureEnabled('mobile-app')` |
| `frontend/src/components/common/Footer.tsx` | "Get the app" link, same gate |
| `frontend/src/config/features.ts`, `components/rec/RecHostPreview.tsx` | the generic `previewActions` slot: the card mounts a feature's component for its device model and lets it claim the click — an unpaired phone slot offers its pairing code instead of the offline placeholder (`PhoneSlotPreviewAction.tsx`) |
| `infra/proxy/nginx/config/*.conf` | `location ~ ^/host/([^/]+)/phone/socket\.io/` WebSocket upgrade proxy |

Core fetch/auth/socket changes made during TASK-17 (server identity vs page origin, per-server
sessions) are generic core behaviour, not hooks, and are not gated.

## DB

`db/001_phone_agent_device_model.sql` must be applied by hand to every database the release
reaches (`update_core.sh` / `deploy_customer.sh` do not run migrations). Without it the
UserInterface editor offers no `phone_agent` model, so no navigation tree can target a phone.

## Tests

| Tier | File |
|---|---|
| unit (bridge + fake phone) | `tests/backend_host/test_mobile_app_bridge.py` |
| A — server routes | `tests/backend_server/test_mobile_app.py` |
| A — component render | `tests/frontend/MobileAppPage.test.tsx`, `tests/frontend/ThisPhonePage.test.tsx` (`cd tests/frontend && npx vitest run MobileAppPage ThisPhonePage`) |
| A — page sweep | both routes in `tests/e2e/playwright/specs/ui.pages.spec.js` |

```bash
python3 scripts/feature_delivery_report.py mobile-app     # evidence table for the release note
cd frontend && VITE_DISABLED_FEATURES=mobile-app npx vite build --outDir /tmp/d \
  && grep -rl "ThisPhonePage\|/server/mobile-app" /tmp/d/assets   # must print nothing
```

## Acceptance without a phone

```bash
python3 features/mobile-app/backend_host/phone_sim.py --host-url http://<host>:6109 --token <token>   # or --qr '<payload>'
```

pairs a fake phone that streams a test image and answers every command — enough to see the
slot go live, the HLS stream start and a script drive it.
