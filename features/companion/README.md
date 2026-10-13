# companion — Live-TV companion

Tells what is on a device's screen with zero setup (screen type, content category, programme),
looks up facts about the programme on the web, and tracks live values: score and scoring events
for soccer / rugby / basketball (drawn with the Labox match card), time left for films and
series. Design and measurements: `docs/tasks/TASK-05-live-tv-ai-companion.md`.

## Turning it on and off

| Switch | Where | Effect |
|---|---|---|
| Feature | `DISABLED_FEATURES=companion` / `VITE_DISABLED_FEATURES=companion` (deploy deny-list) | Off: no files deployed, no `vpt-companion` unit, no routes, no AI usage keys, nothing in the frontend bundle |
| Host (**off by default, experimental**) | `ENABLE_COMPANION=true` through a systemd drop-in on `vpt-companion` (the unit ships `false`, like `ENABLE_TRANSCRIPTION`; see `backend_host/services/companion.service`) | Off: the service only sleeps. The pipeline is never imported and no AI call is made |
| Device | `DEVICE{N}_COMPANION=true` in the host `.env` | Only opted-in devices are analysed; with none, the service idles and makes no AI call |
| Cadence | Per category: `identify_interval_s` in each `lib/profiles/*.json` (sport and news 60 s, films and series 120 s). `COMPANION_INTERVAL_S` (default 60) applies when the programme's profile sets none. Also `COMPANION_SCORE_INTERVAL_S` (default: the profile's, 10) in the host `.env` | Seconds between identify calls / score-bug reads. On a slow local model (the PC's LM Studio) use 60 / 30, otherwise the requests queue up and also delay transcript correction |
| Captions | `captions: {"interval_s": 6}` in a profile (news, debate) | Reads the lower band of the frame for name captions (speaker list) and topic straps (topic timeline), skipped while that band is unchanged. ~400 tokens per read on the vision model |
| Call budget | `COMPANION_CALL_TIMEOUT_S` (host `.env`, default 30) | Seconds one AI call may wait for a slot and for its answer. Past it the model counts as busy: the companion keeps the last result and retries after 30 s, doubling up to 5 min (`backoff` in the result) |
| Facts | Settings → AI: a profile with the **web** capability routed for `text.web` | Without one, facts show "unavailable"; the gateway never answers from model memory |
| Fact check (**off by default**) | `DEVICE{N}_COMPANION_FACTCHECK=true` in the host `.env`; cap `COMPANION_FACTCHECK_PER_HOUR` (default 6) | Debates: each new checkable claim gets one web-searched verdict (`text.web.companion.factcheck`): supported / contradicted / unverified, with a source. No source means unverified. Opinions are never checked; past the cap a claim shows "not checked" |
| Fact check meter (TASK-45) | rides on the same `DEVICE{N}_COMPANION_FACTCHECK=true`; caps `COMPANION_METER_PER_HOUR` (default 900) and `COMPANION_FACTCHECK_MIN_CLAIM` (default 0.7) | Live sentence meter: one `text.decision.companion` (Jev) call per finished sentence scores five rhetoric questions and picks the speaker from a per-programme known-people file (`<capture folder>/companion/known_people.json`, cold storage, not the RAM `hot/` folder). Only sentences with `P(factual_claim) >= COMPANION_FACTCHECK_MIN_CLAIM` go to the web check. `result()["meter"]` carries the panel: per-sentence scores, per-speaker averages with a 0-100 rhetoric index. |
| Jev gates (TASK-45 goal 5) | always on for a companion device; fail open | One usage key `text.decision.companion.gate` (inherits `text.decision`, so the `jev` route; no migration) decides whether to SKIP an LLM / web call before it is made. Three gates: (1) before the web fact check (a vague or repeat claim is skipped, `P(specific) < 0.5` or `P(repeat) >= 0.7`); (2) before the programme-facts web lookup (a strap, slot or channel name is skipped, `P(worth_lookup) < 0.5`); (3) before the 2-min debate digest (skipped when the new lines bring nothing new, `P(new_content) < 0.3`). Only the second+ digest is gated; the first always runs. A failure / no answer runs today's call; a gate only ever skips, never changes the answer. |

The strip shows under the live video when the player is in **Live** mode with **Monitoring** on.

## Parts

- `backend_host/companion_monitor.py`: the `vpt-companion` service (`services/companion.service`).
  It reads only files capture already writes (newest `capture_*.json`, its frame, `last_zapping.json`)
  and writes `<metadata>/companion.json`. It is separate from `capture_monitor`, so it can never slow
  detection down.
- `backend_host/companion.py`: the pipeline (identify → facts → track), one thread per device.
- `backend_host/__init__.py`: `POST /host/companion/latest {device_id}`.
- `backend_server/__init__.py`: `POST /server/companion/latest {host_name, device_id}` (proxy) and
  registration of the AI usage keys.
- `lib/`: category profiles (`profiles/*.json`), identify prompt/parser, scoreboard stabiliser,
  broadcast time window, fact cache, claim fact checks (`factcheck.py`), result store, usage keys.
- `frontend/`: `routes.tsx` registers one video overlay: `CompanionStrip`, `MatchCard` (Labox
  port), `TitleCard`.

Adding a category = a new `lib/profiles/<name>.json`. New code is only needed for a new tracker
type (`scoreboard`, `time_window` today) or card template (`match`, `title`, `label`).

## Core hooks

The exact residue in core when this feature is off. All of these are inert without it:

1. `shared/src/lib/ai/usages.py`: `register()` / `feature_usage()`, which let a feature add AI
   usage keys when the server loads it.
2. `frontend/src/config/features.ts`: the `videoOverlays` slot (`FeatureVideoOverlay`,
   `featureVideoOverlays()`), mounted by `frontend/src/components/video/EnhancedHLSPlayer.tsx`.
3. `backend_host/src/.env.example`: the `DEVICE{N}_COMPANION` / `COMPANION_INTERVAL_S` block.

Used from core, but not owned by this feature: web-grounded AI calls (`text.web`, the `web`
profile capability, migration `20260930a`) and the `content-type` training family (migration
`20260930b`).

## Tests

`tests/backend_server/test_companion.py` (lib + registration on/off) and
`tests/backend_host/test_companion.py` (pipeline, service, host route).
