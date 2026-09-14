# zap_digit

Channel-zapping test that enters channel **numbers** directly on the remote keypad —
instead of pressing a `live_chup` action node like `zap_chup`/`fullzap`, it types the
digits of each channel. You give it channel pairs (e.g. `123>300`) and it ping-pongs
**source ↔ destination** for the requested number of iterations, verifying after every
entry that the destination is actually playing (real frame-to-frame motion), not frozen.

## Device scope — TV / STB only

Digit zapping needs a numeric keypad on the remote, so this targets **TV/STB** devices:
Android TV (ADB), IR STBs (`ir_conf/*.json`), and BLE STBs (`ble_conf/arris.json`).
Android **phones** have no digit keypad remote — this script does not apply to
`android_mobile`. Default UI is `example_tv`.

## "No mistakes" by construction

The user only ever types channel **numbers** (0-9). Each digit char is mapped to the
device's real remote key via `DIGIT_KEYMAP` — the universal convention `KEY_0`..`KEY_9`,
present in every IR config, the BLE config, and the Android TV ADB keymap
(`adb_utils.ADB_KEYS`, where `KEY_0..KEY_9` were added so `press_key` accepts digits). A
non-digit in `--zaps` is **rejected up front**, so an invalid remote key can never be sent.

## Usage

```bash
python test_scripts/tv/zap_digit.py --zaps "123>300" --iterations 5
python test_scripts/tv/zap_digit.py example_tv --zaps "123>300, 11>42"
# Re-run repeatedly without re-navigating (you're already on live):
python test_scripts/tv/zap_digit.py --zaps "123>300" --goto-live false
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_tv` | UI interface (navigation tree) name. TV/STB only |
| `--variant` | string | _(base)_ | Optional named variant of the tree |
| `--zaps` | string | `123>300` | Channel pairs to ping-pong, `src>dst` separated by `>`, multiple comma-separated (e.g. `123>300, 11>42`). Each side must be digits only |
| `--digit-wait-ms` | int | `400` | Milliseconds to wait after each digit key press |
| `--final-wait-time` | int | `3000` | Milliseconds to wait after the full channel is entered, before checking motion (same `final_wait_time` convention as action sets, in ms) |
| `--iterations` | int | `1` | Number of source↔destination round trips per pair |
| `--goto-live` | bool | `true` | Navigate to the live node first; set **false** to re-run repeatedly from live |
| `--live-node` | string | `live` | Node label to navigate to when `--goto-live` is true |

## What it does, step by step

1. **Validate `--zaps`** into `(source, destination)` pairs. Anything that isn't
   `digits>digits` is rejected **before any key is sent**.
2. **Load the navigation tree** for `--userinterface` (and `--variant` if given).
3. **Go to live** (`--goto-live true`): navigate to `--live-node` so playback is active.
   With `--goto-live false` it skips straight to zapping (useful when already on live).
4. **For each pair, for each iteration** — enter the **source** channel, then the
   **destination** channel. Each entry:
   1. Press each digit key (`KEY_<d>`), waiting `--digit-wait-ms` between presses.
   2. Wait `--final-wait-time` for the channel to settle.
   3. Run the **real motion check** (`ZapExecutor.detect_real_motion`) — captures two
      fresh frames ~1s apart and diffs the centre region; any frozen/blackscreen frame
      ⇒ no motion. (Same strict signal `zap_chup`/`fullzap` use.)
5. After the last digit, `last_action.json` is stamped (the same IPC the action executor
   uses) so **vpt-monitor** can attribute its zap detection to this entry. After motion,
   the script does a **best-effort read of the local zap measurement** the monitor wrote
   to `last_zapping.json` (channel name/number + blackscreen/total-zap durations) —
   matched by that timestamp, never blocking the verdict.
6. Each channel entry is **recorded as its own report step** (category `zap_action`,
   labelled `<from> → ch <n>`), carrying **4 images**, the change-% in the message, and
   the zap measurement under *Analysis Results → Zap Detection* (when detected). A frozen
   entry shows the reason ("Destination frozen…"); a dropped key shows "Key press failed…".
7. **Summary**: per-entry table + statistics. The script **passes only if every channel
   entry played** — a frozen destination (keys sent, no motion) or a dropped key fails the run.

## Zap measurement (local, before DB)

vpt-monitor (`capture_monitor.py`) detects the channel change and writes
`last_zapping.json` **locally, the moment it detects it — before the DB write**. The
script reads it back via `ZapExecutor.fetch_zap_measurement(context, action_ts)` (a thin
wrapper over the same reader `fullzap` uses, capped at 60s but exiting as soon as the
result lands). It's **best-effort**: if the monitor hasn't written it in time, the
measurement is simply `null` for that entry — it never changes pass/fail.

## Report

The goto-live navigation appears as its usual steps (`ENTRY → home`, `home → live`),
then **one step per channel entry**:

```
3  PASS  live → ch 123    Enter channel 123 — motion 7.4%
4  PASS  ch 123 → ch 300  Enter channel 300 — motion 6.1%
```

Each zap step holds **4 images**, in the order the report renders them:

1. **step start** — original full frame before zapping (where we came from)
2. **motion 1** — first cropped frame the motion check compared
3. **motion 2** — second cropped frame
4. **step end** — original full frame on the settled destination (where we landed)

The two original full frames are captured with `capture_screenshot_for_script` (start
and end of the step); the two motion crops come from `ZapExecutor.detect_real_motion`.

## Output (console)

- Per-entry lines: `✅/❌ [keys✅ motion✅] 123→300 #1 source (ch 123)`
- Statistics: total entries, successful, failed, **frozen destinations** (zapped but no
  motion), and **key-press failures**.
- `context.execution_summary`: `Zap digit [ui/variant]: N/M entries played, F frozen, K key-press failures`.

## Related

- `zap_chup.py` — executes a `live_chup` action node N times (navigation-optimization test).
- `fullzap.py` — presses a channel-change key and adds zapping + subtitle + audio analysis.
- Motion internals: `shared/src/lib/executors/zap_executor.py` (`detect_real_motion`).
- Digit key names: `backend_host/src/lib/utils/adb_utils.py` (`ADB_KEYS`),
  `backend_host/src/controllers/remote/ir_conf/*.json`, `…/bluetooth/ble_conf/arris.json`.
