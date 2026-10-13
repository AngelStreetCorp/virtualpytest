# Mobility — opt-in sidewalk-accessibility mission (PR 1: foundation)

## Status

**PR 1 of 4** (foundation only — fake adapter, opt-in, no Gazebo, no hardware).
The remaining PRs (Gazebo adapter, VPT runner integration, physical rover
readiness) are separate, owner-reviewed branches.

## What this ships

- A self-contained backend_host service under `backend_host/src/mobility/`.
- An explicit list of capabilities (`telemetry`, `camera`, `navigate`, `stop`,
  `measure`).
- A **deterministic** `FakeMobilityController` that completes a scripted
  100 m sidewalk mission (3 curbs, 1 ramp, 2 obstacles, destination)
  given a seed.
- A `SafetyGate` that authorises every command; the adapter cannot bypass it.
- A `mobility:run` permission enforced through the existing
  `require_permission` helper.
- An opt-in `VPT_MOBILITY_ENABLED` flag (default `false`).

## What this does NOT ship

- No Gazebo / ROS 2 adapter (PR 2). No physical rover actuation (PR 4).
- No production actuation backend. The only actuator that runs is the fake.
- No customer-facing UI. The PR exposes HTTP endpoints only.
- No DB migration for the `mobility:run` permission (owner-only carve-out).

## Activation

```bash
# opt-in: only the routes and the permission gate activate
VPT_MOBILITY_ENABLED=true
VPT_MOBILITY_MAX_SPEED_MPS=1.5
VPT_MOBILITY_MAX_TURN_RADPS=0.5
VPT_MOBILITY_MAX_DURATION_S=30
VPT_MOBILITY_GEOFENCE_MIN_X=0
VPT_MOBILITY_GEOFENCE_MAX_X=200
VPT_MOBILITY_GEOFENCE_MIN_Y=0
VPT_MOBILITY_GEOFENCE_MAX_Y=50
VPT_MOBILITY_HEARTBEAT_TIMEOUT_MS=2000
VPT_MOBILITY_REQUIRE_AUTH_TOKEN=true
VPT_MOBILITY_AUTH_TOKEN_MAX_AGE_S=5
VPT_MOBILITY_NONCE_WINDOW=100
```

All defaults are fail-safe (small speed, narrow geofence, short duration).

## Architecture

```
            ┌─────────────────────────────────────────────────────┐
            │  /host/mobility/*  Flask blueprint                  │
            │  (api.py — opt-in via VPT_MOBILITY_ENABLED)         │
            └─────────────────────────┬───────────────────────────┘
                                      │ RoverCommand
                                      ▼
            ┌─────────────────────────────────────────────────────┐
            │  SafetyGate  (safety.py — R1..R12)                  │
            │  • feature flag   • finiteness     • speed limit     │
            │  • turn limit    • duration       • geofence        │
            │  • operator auth • connection     • e-stop          │
            │  • capability    • internal error                   │
            └─────────────────────────┬───────────────────────────┘
                                      │ SafetyDecision
                                      ▼ (allow / reduce / deny)
            ┌─────────────────────────────────────────────────────┐
            │  BaseMobilityController  (controller.py)            │
            │  owns SafetyContext; zero-motion pulse on deny      │
            └─────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
            ┌─────────────────────────────────────────────────────┐
            │  FakeMobilityController  (adapters/fake.py)         │
            │  in-process deterministic simulator                 │
            │  PR 2 → Gazebo adapter    PR 4 → physical mock     │
            └─────────────────────────────────────────────────────┘
```

### Why a self-contained service (not a `DEVICE_CONTROLLER_MAP` entry)

The `Device` model only knows `av`/`remote`/`verification`/`power`/`network`/
`switch`/`desktop`/`web` (`shared/src/lib/models/device.py:74-81`). Adding a
`mobility` slot requires editing `shared/src/lib/config/device_capabilities.py`
and `Device._controllers`, which expands the blast radius beyond what PR 1
should touch. Mobility is therefore a *service* — its own blueprint, its own
state, gated by `VPT_MOBILITY_ENABLED` — not a `Device`-attached controller.
Capabilities are surfaced via `/host/mobility/state` only.

## SafetyGate rules (R1..R12)

| Rule | Trigger | Outcome | `reason_code` |
|---|---|---|---|
| **R1** | `VPT_MOBILITY_ENABLED=false` | deny | `FEATURE_DISABLED` |
| **R2** | NaN / ±Inf in any numeric field | deny | `NON_FINITE_*` |
| **R3** | `|linear| > max_speed_mps` | reduce (clip) | `LINEAR_CLIPPED_TO_MAX` |
| **R3** | `max_speed_mps == 0` | deny | `LINEAR_DISABLED` |
| **R4** | `|angular| > max_turn_radps` | reduce (clip) | `TURN_CLIPPED_TO_MAX` |
| **R4** | `max_turn_radps == 0` | deny | `TURN_DISABLED` |
| **R5** | `duration_s <= 0` | deny | `DURATION_NON_POSITIVE` |
| **R5** | `duration_s > max_duration_s` | reduce (clip) | `DURATION_CLIPPED_TO_MAX` |
| **R6** | target outside geofence | deny | `GEOFENCE_TARGET_OUT_OF_BOUNDS` |
| **R6** | rover position outside geofence | deny | `GEOFENCE_ROVER_OUT_OF_BOUNDS` |
| **R6** | geofence unconfigured (all bounds = 0) | deny | `GEOFENCE_UNCONFIGURED` |
| **R7** | unknown `operator_id` | deny | `OPERATOR_UNAUTHORIZED` |
| **R7** | missing/invalid token (when `require_auth_token=true`) | deny | `AUTH_TOKEN_INVALID` |
| **R7** | token age > `auth_token_max_age_s` | deny | `AUTH_TOKEN_STALE` |
| **R7** | nonce replayed within `nonce_window` | deny | `AUTH_TOKEN_REPLAYED` |
| **R8** | `connection_healthy=false` | deny | `CONNECTION_UNHEALTHY` |
| **R8** | `now - last_heartbeat_ms > heartbeat_timeout_ms` | deny + zero-motion | `HEARTBEAT_LOST` |
| **R9** | `estop_engaged=true` (everything except `stop`) | deny + zero-motion | `ESTOP_ENGAGED` |
| **R10** | unknown capability | deny | `CAPABILITY_NOT_SUPPORTED` |
| **R11** | every deny | force a zero-motion pulse | (audit only) |
| **R12** | unexpected exception in any rule | deny | `SAFETY_GATE_INTERNAL_ERROR` |

**Stop is unconditional**: `capability="stop"` short-circuits to allow,
regardless of e-stop, connection health, or heartbeat. Stop is the
recovery path; it must always succeed.

## Permission gate

`mobility:run` is enforced by the existing
`backend_server/src/lib/auth_middleware.py::require_permission` helper.
For PR 1:

- **Admin users** hold every permission (existing behaviour) — admin
  tokens work out of the box.
- **Non-admin users** (tester/viewer) get 403 until the owner runs the
  `mobility:run` DB migration (`setup/db/` is owner-only).

The test suite covers the admin and 403 paths.

## Endpoints

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/host/mobility/health` | none | liveness + config + scenarios |
| `POST` | `/host/mobility/heartbeat` | none | adapter-side liveness |
| `GET` | `/host/mobility/state` | `mobility:run` | rover state (telemetry) |
| `GET` | `/host/mobility/observations` | `mobility:run` | recent observation trace |
| `GET` | `/host/mobility/missions` | `mobility:run` | list built-in scenarios |
| `POST` | `/host/mobility/missions` | `mobility:run` | run a deterministic mission |
| `POST` | `/host/mobility/estop` | `mobility:run` | engage e-stop |
| `POST` | `/host/mobility/estop/clear` | `mobility:run` | release e-stop |

## Reporting contract

PR 1 returns mission results through `MobilityResult` (a JSON-friendly
dataclass with `status` ∈ `{pass, fail, needs_review, error}` and a
full observation trace). The VPT reporting conventions are not yet
wired up — that's PR 3. PR 1 ships a clearly-documented temporary
contract; see `MobilityResult.to_dict()`.

## Known limitations (called out for PR 2+)

- **In-memory operator + nonce store.** Multi-host deployments need a
  shared store (Redis or the platform DB) — the nonce window lives in
  process memory today.
- **HMAC secret** defaults to the platform API key. An operator who
  wants a separate secret can set `VPT_MOBILITY_AUTH_SECRET`.
- **Synchronous mission run** in `POST /host/mobility/missions`. A real
  workload needs a worker; PR 3 will move it.
- **E-stop is per-process.** Multi-host deployments need an out-of-band
  channel.

## Tests

| File | Layer | Coverage |
|---|---|---|
| `test_config.py` | unit | defaults, env parsing, garbage recovery |
| `test_models.py` | unit | validation, NaN/Inf, capability allow-list |
| `test_safety.py` | unit + contract | R1..R12, every edge case, thread safety |
| `test_fake_adapter.py` | unit + fault | scripted mission, determinism, faults |
| `test_missions.py` | unit | mission loader + script validation |
| `test_api_registration.py` | unit + integration | opt-in flag, permission gate |
| `tests/backend_host/test_mobility_smoke.py` | tier-A regression | host import, route registration |

Run with:

```bash
# In-process unit + contract tests
python3 -m pytest backend_host/src/mobility/tests/

# Tier-A regression (host unchanged)
python3 -m pytest tests/backend_host/test_mobility_smoke.py
```

## Follow-up PRs

- **PR 2** — Gazebo / ROS 2 adapter (`adapters/gazebo.py`), world/model
  assets, one-command local smoke.
- **PR 3** — VPT runner integration, reporting, optional UI, MCP tool
  exposure (bounded).
- **PR 4** — Physical-rover contract, mock/loopback adapter, hardware
  safety review checklist.