# BUG-0299 — Every host pushed every alert to a Redis queue that nothing read

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0299                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — log noise and a growing dead queue; no alert was lost (alerts are in the DB) |
| Area      | `shared/src/lib/database/alerts_db.py`, `shared/src/lib/utils/redis_queue.py`, `backend_server/src/agent/core/nightwatch_handler.py`, `backend_server/scripts/discard_worker.py`, `vpt-discard-incidents` |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Follow-up of [BUG-0283](BUG-0283-2026-10-04-alert-queue-log-said-added-after-redis-failed.md).
Every alert vpt-monitor created was written to the DB, then pushed with `LPUSH p1_alerts` to the
Redis named by the host's `REDIS_URL`:

- hosts on another network (vpt-pi3 timeout, vpt-pi4 `localhost` with no Redis, vpt-nipogi no
  `REDIS_URL`) logged a Redis error on every alert;
- vpt-pi1 queued into its own local Redis, which nothing reads;
- the shared Redis held 864 unread `p1_alerts` items dating back to 2026-03-19 (the
  per-device cap of 5 did not hold: 120 items per host for several hosts).

Nothing consumed `p1_alerts`: `vpt-discard-incidents` was installed disabled and ran the
same entry point as `vpt-discard-scripts` (Sherlock on `p2_scripts`), so enabling it would only
have added a second script consumer.

## Root cause — how alert triage "worked before"

| Period | What triaged alerts | Commit |
|---|---|---|
| 2025-08 → 2025-12-10 | A separate service, `backend_discard` (`ai_analyzer.py`), popped `p1_alerts`, sent a **text-only** prompt (alert metadata, no image — the vision path was commented out) to the AI layer and wrote `checked`, `check_type='ai'`, `discard`, `discard_comment` on the alert. | removed in `4d7c18851` "rm:virtualpytest_discard" |
| 2025-12-10 → 2026-03-16 | The Nightwatch agent was given `background_queues: ['p1_alerts']` but with `dry_run: true` (log + Socket.IO only, no AI, no DB verdict). | `78aa21420` |
| 2026-03-16 → now | `background_queues` removed from `monitor.yaml` ("automated triage owned by vpt-discard-incidents"), but that service was never given its own code path. | `7e266772b`, `1c03c6370` |

So alert verdicts stopped in December 2025. No past verdict survives in the DB: `alerts` keeps
about 7 days, and every row in it (6 835, 2026-09-27 → 2026-10-04) has `check_type` NULL.

## Fix

- **Producer:** `create_alert` no longer touches Redis at all (`add_alert_to_queue`, the
  per-device eviction and `p1_alerts` removed from `redis_queue.py`). No host needs Redis for
  alerts any more, so the remote-network hosts stop logging errors whatever their `REDIS_URL`.
- **Consumer:** `vpt-discard-incidents` now runs `discard_worker.py --incidents`, which polls the
  `alerts` table (`check_type IS NULL`, last 6 h) every 30 s — the table is the queue, so hosts on
  any network are covered. `NightwatchHandler` (rewritten; the dead dry-run path in `manager.py`
  and `dry_run` in the agent config schema are gone) applies the cost rules, then calls usage
  `vision.alert_triage` (inherits the `vision` route: `qwen/qwen3-vl-8b-instruct` on OpenRouter)
  with the alert's uploaded frame and facts, and writes `checked=true, check_type='ai'`,
  `discard`, `discard_type` (= verdict) and `discard_comment`.
- **On/off switch:** the systemd unit itself (installed disabled; enable = on). With it off, no
  code anywhere queues or reads alerts for triage.
- **Cost rules** (server env, defaults): wait `ALERT_DISCARD_MIN_DURATION_S=30` s and skip an
  alert that resolved sooner; analyse only the first alert per host+device+type per
  `ALERT_DISCARD_REPEAT_WINDOW_H=6` h; at most `ALERT_DISCARD_DAILY_MAX=100` model calls per UTC
  day; never send a freeze/blackscreen on a looping test stream (one frame cannot show a stopped
  timecode). Skipped alerts get `check_type='ai_strategy_skip'` and keep `checked=false`.
- AI Queue page: "Incidents pending" = unhandled alerts of the last 6 h; there is no queue to clear.

## Evaluation (why it stays OFF)

72 real alerts (2026-09-27 → 10-04, 9 hosts, freeze / blackscreen / audio loss) plus 6 synthetic
real incidents built from real frames (a live shopping channel frozen / silent, a frozen HLS test
pattern, a frozen video-loop counter, a black film stream). Ground truth: 21 human + 11 teacher
labels from the `av-fault` training set, own judgement from the frames for 34 more, 6 uncertain
excluded. Final prompt:

| Model (profile) | Accuracy | Real caught | Noise discarded | Cost / alert | Latency p50 / p90 |
|---|---|---|---|---|---|
| `qwen3-vl-8b` (qwen/qwen3-vl-8b-instruct) | 91 % (60/66) | 3/6 | 57/60 | $0.000085 | 0.9 s / 1.5 s |
| `gpt-4.1-mini` (openai/gpt-4.1-mini) | 80 % (53/66) | 4/6 | 49/60 | $0.000301 | 1.2 s / 1.6 s |

Typical mistakes: a TV home screen's poster backdrop (film still + title logo) taken for a
frozen film (both models); a frozen test pattern / counter called "expected" (both — one frame
cannot show the timecode stopped; now never sent to the model); a black film stream called
intentional (Qwen); gpt-4.1-mini also keeps idle phones, desktops and cameras as "real" from
the facts alone. An earlier prompt that told the model long or repeating alerts are "almost
always expected" discarded 60/60 noise — it would also have discarded a stuck device.
Missing half of the real incidents is not good enough to discard alerts automatically, so the
worker is **not enabled** in production.

Volume with the rules (DB, full days 09-28 → 10-03): 932 alerts/day → **34/day to the model
(3.6 %)**, max 42/day; ≈ **$0.003/day** with Qwen (≈ $0.08/day without the rules).

## Verification

- `tests/shared/test_nightwatch_triage.py`: each rule, verdict parsing, image path per alert
  shape, prompt facts, usage registration, and that `create_alert` has no Redis code.
- Read-only dry pass of the new handler on the server against the live DB: 200 pending alerts →
  57 short, 134 repeat, 9 to the model.
- The evaluation ran the same `classify()` with `router.resolve_profile()` pinning each profile (no fallback), on the backend server.
