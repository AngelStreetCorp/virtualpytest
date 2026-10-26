# BUG-0917 — The egg line analysed three frames a second of the five it was given

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0917                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `ba4bfb9b0`, and the worker wait in the commit after it      |

---

## Symptom

The owner asked for 5 analyses a second on the egg line; the captures arrive at 5 fps. `egg_count_yolo_belt_fast` ran
**1.57 analyses/s** on `vpt-lenovo1`, its `sample_hz: 2.0` capped it at 2 anyway, and raising the cap alone gave 2.28.

## Root causes (each measured on the live host with `py-spy`)

1. **A square input for a 16:9 frame.** A 1280x720 frame letterboxed into 640x640 is 44 % grey padding the model still
   runs through.
2. **`cv2.dnn`** runs the same graph slower than onnxruntime on that CPU.
3. **The 10-minute chunk was re-encoded every 2 s.** At 5 fps x ~180 boxes a frame a chunk reaches ~40 MB, and its
   `json.dump` took a fifth of the process under the GIL the detector thread needs.
4. **Pure-Python loops over thousands of anchors** in the decode (at `min_conf: 0.02`) and over every pair of boxes
   in the duplicate merge.
5. **The box was shared** with six capture ffmpegs at nice 0 (the monitor runs at nice 15): load 10-12 on 4 cores.
6. **The worker waited a whole period after a frame that came early.** `_worker` slept `1/sample_hz` whatever was
   pending, so a frame arriving a few ms before its slot waited one more period: the egg line analysed **3.2 frames a
   second on an idle box**, its thread idle 68 % of the time.

## Fix

1. `yolo_seg_detect` takes `input_size: [width, height]`; the profile uses a 640x352 export of the same weights
   (sha256 `00d939ea…d130d6`, `MONITOR_YOLO_BELT_FAST_MODEL` on the host; the 640x640 file stays for a rollback).
2. `backend: onnxruntime` (`threads: 2`).
3. A chunk waits at least 20x its own last encode time between flushes (still 2 s for a small chunk); shutdown forces
   the flush.
4. Both loops vectorised with numpy (same decisions).
5. counting_cars moved to `vpt-lenovo4`, the four internet TV streams to `vpt-lenovo5` / `vpt-lenovo6` (host `.env`
   changes, backups `/root/.env.bak-egg5fps*`); `vpt-lenovo1` keeps the eggs and its FireTv capture card.
6. The worker waits until the earliest pending frame is due (`_next_due_in`).

## Verification

Fixed frame on the host under its old load, matched one-to-one on the 147-egg set: 640x640 cv2.dnn 390 ms 138/147 →
640x352 onnxruntime 118 ms 137/147. Live on `vpt-lenovo1`, 60 s of frame metadata: **4.82 analyses/s, 285 of 288
consecutive captures analysed**, load average 1.35 (was 1.57 analyses/s at load 10). Tests:
`tests/backend_host/test_yolo_seg_detect.py` (rectangular letterbox), `test_monitor_replay.py` (forced flush),
`test_counting_cars.py` (the worker wait).
