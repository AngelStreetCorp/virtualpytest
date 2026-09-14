# fullzap

Channel-zapping test: presses a channel-change key N times and, after each press,
verifies the zap actually happened **and** the destination channel is really playing.

It does **not** just check that the remote key was sent — it confirms (a) the channel
changed (zapping detection) and (b) the new channel shows real video (motion), and it
also runs AI analysis for subtitles and spoken audio.

## Usage

```bash
python test_scripts/tv/fullzap.py --max-iteration 5
python test_scripts/tv/fullzap.py --action live_chup --goto-live true
python test_scripts/tv/fullzap.py --audio-analysis true --max-iteration 10
# Restrict the post-zap motion check to a content region (exclude a moving overlay):
python test_scripts/tv/fullzap.py --motion-area "0,120,1280,400"
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface (navigation tree) name |
| `--variant` | string | _(base)_ | Optional named variant of the tree |
| `--max-iteration` | int | `3` | Number of zap iterations |
| `--action` | string | `live_chup` | Zap action node (`live_chup` / `live_chdown`) |
| `--goto-live` | bool | `true` | Navigate to the live node before zapping |
| `--audio-analysis` | bool | `false` | Run the audio-menu (language) analysis at the end |
| `--motion-area` | string | _(centre 60%)_ | `x,y,width,height` region for the post-zap motion check. **Defaults to the centre 60% of the frame** (excludes header/footer/side overlays); only set this to tune per UI |

---

## What it does, step by step

1. **Load the navigation tree** for `--userinterface` (and `--variant` if given). This gives
   `tree_id` and the node graph used to navigate.

2. **Go to live** (`--goto-live true`): navigate to the `live` node (`live_fullscreen` on
   mobile). With `--goto-live false` the device position is just set to `live` without moving.

3. **For each iteration** (`--max-iteration`):
   1. **Send the zap key** by navigating to the action node (`live_chup`). This sends the
      real remote/IR/BLE key and records `last_action_timestamp` (used to match the zap).
   2. **Analyze the result** (`analyze_after_zap`), in this order:
      - **Zapping detection** — was it a real channel change? (see below)
      - **Motion detection** — is the destination actually playing video? (see below)
      - **Subtitle AI** — are subtitles present, and what text/language?
      - **Audio speech (Whisper)** — is anyone speaking, and in what language?
   3. **Decide pass/fail for the iteration**: for `chup`/`chdown` an iteration is
      **successful only if `zapping_detected AND motion_detected`**. A channel that zapped but
      landed on a frozen screen (e.g. a parental/age-rating block) **fails**.
   4. **Record** the step (with start/end/duration and the real pass/fail), the DB row, and KPI.

4. **Summaries**: print the per-iteration table (separate **Zap** and **Motion** columns) and
   the fullzap summary. The **script passes only if every iteration passed**
   (`successful_iterations == max_iteration`).

---

## The detection algorithms

The capture pipeline (`run_ffmpeg.sh` → `capture_monitor.py` → `detector.py`) continuously
writes one analysis JSON per frame (`freeze`, `blackscreen`, `audio`, …). fullzap reads those
flags **and** runs fresh measurements where it matters.

### Blackscreen (`detector.py: quick_blackscreen_check`)
- Looks at the region **5%–70% of the image height** (skips the channel header and the bottom
  banner so an info overlay can't fool it).
- Samples every 4th pixel; a pixel is "dark" if its grey intensity is **≤ 10**.
- **Blackscreen if more than 95%** of sampled pixels are dark.

### Freeze (`detector.py: detect_freeze_pixel_diff`)
- Each frame is reduced to a **320×180 grayscale thumbnail**.
- The current thumbnail is compared with the **previous 3** thumbnails via `cv2.absdiff`.
- A pixel "changed" if its intensity differs by **> 10**.
- **Frozen** = *every* compared frame has **< 0.8%** changed pixels (early-exit to "not frozen"
  as soon as any frame exceeds 5%). Has adaptive sampling under load and a long-freeze fast path.
- ⚠️ Because this is a whole-frame pixel diff, a **static screen with a small animated overlay**
  (ticking clock, progress bar, EPG ticker) reads as **not frozen** — which is exactly why
  freeze alone can't tell "playing" from "frozen behind an overlay". That's what the real
  motion check + `--motion-area` are for.

### Zapping detection — "did the channel change?" (`capture_monitor` → `last_zapping.json`)
- After a channel-change key, `capture_monitor` watches for the **blackscreen/freeze transition**
  (the brief black/frozen gap while the box retunes), then the **first content frame** after it.
- It stamps the detection with the **action timestamp** so it can be matched to *this* key press,
  and runs **AI on the channel banner** to read the channel name/number and the current program.
- It writes `last_zapping.json` with `status` (`in_progress` → done / `aborted`), the
  blackscreen duration, total zap duration, channel info, and the transition images (before /
  first-black / last-black / after), uploaded to R2.
- `ZapExecutor` **polls up to 45s** for the entry whose `action_timestamp` matches this iteration.
  `zapping_detected = True` only when a matching, completed detection is found.

### Motion detection — "is the destination really playing?"
fullzap uses **two** things here:
- **JSON freeze/blackscreen flags** of the last 3 frames → used for the **thumbnail strip** in
  the report (the "Motion Analysis – recent captures", oldest on the left) and for `audio_ok`.
- **Real frame-to-frame motion** (`DetectMotion` → `compare_images_for_motion`) → this is the
  **actual pass/fail signal**. It is run **after** the zapping poll so it looks at the *settled
  destination*, not the transition:
  - captures **two fresh frames ~1s apart**, grayscale;
  - **both frames are cropped to a region before the diff. By default this is the centre 60%
    of the frame** (`DEFAULT_MOTION_AREA_FRACTION`), which already excludes the typical edge
    overlays — channel header (top), info/EPG banner (bottom), and left/right menu panels —
    so a frozen channel behind a moving overlay does **not** count as motion. `--motion-area`
    overrides this with an explicit `x,y,width,height` region per UI;
  - a pixel "changed" if its intensity differs by **> 30**;
  - **motion detected if the changed-pixel percentage > threshold (5%)**.

### Subtitle AI (`DetectSubtitlesAI`)
- Sends the **3 most recent sequential frames** to the vision model.
- Returns `subtitles_detected`, the extracted **text**, and the detected **language**.

### Audio speech — Whisper (`DetectAudioSpeech` → `audio_ai_helpers`)
- Pulls the **recent audio segments** from the HLS `.ts` files and extracts the audio.
- Transcribes locally with **faster-whisper** (model **`tiny`**, cached as a singleton; ~4–5×
  faster than openai-whisper).
- `audio_speech_detected = True` only if the combined transcript is non-empty; also returns the
  **detected language**. Audio segments are uploaded to R2 for traceability in the report.

---

## Output

- **Per-iteration table** with separate columns:
  `Iter | Action | Start | End | Duration | Zap | Motion | Subtitles | Audio | Channel Info`
  - **Zap** = channel actually changed (with method ⬛ blackscreen / 🧊 freeze + duration)
  - **Motion** = destination is playing video (real, after zap)
  - `TOTALS` shows `successful (zap+motion)` plus per-signal rates.
- **HTML report**: each iteration is a step. The step badge is **PASS only when zap+motion
  passed**; failed steps show the reason ("Zap not detected" / "Destination frozen — zapped but
  no motion"). Analysis Results show Motion / Subtitle / Audio / Zapping separately, with image
  thumbnails forced onto a white background even in dark theme.

## Related
- `zap_chup.py` — lighter navigation/optimization test that now also runs the same real
  post-zap motion check.
- Detection internals: `backend_host/scripts/detector.py` (freeze/blackscreen),
  `shared/src/lib/executors/zap_executor.py` (orchestration),
  `backend_host/src/controllers/verification/video_analysis_helpers.py` (real motion).
