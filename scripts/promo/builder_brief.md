<!-- Template of the builder's brief (guide §0). Copy it to ~/virtualpytest-promo/runs/brief-<video>.md, replace
every <ANGLE> field, delete the sections that do not apply, then: scripts/promo/run_builder.sh <worktree> <brief> <minutes>.
Before a run: guide §0 step 4 (devices in HD, start state, leases). Fail fast: the same check failing twice = BLOCKED. A follow-up run starts with "CONTROLLER REVIEW of take N:" + what was verified + the exact defects (with times and
what the frames show) + the facts you measured; the builder continues from the same worktree. -->
You are the builder of product video <VIDEO> for VirtualPyTest (you are the only builder; your cost and time are logged).
The storyboard is VALIDATED by the owner: <STORYBOARD path, e.g. docs/tasks/video-storyboards/25b-group-control.md>.
Follow it exactly: every word (title card, end card, captions, voice lines, YouTube title/description/tags) is copied
verbatim from it; never add, drop or reorder beats. If a beat cannot be done as written, STOP and report BLOCKED with
what you found: a story change goes back to the owner. Read docs/tasks/VIDEO_PRODUCTION_GUIDE.md §1, §3, §5, §7 first.
Hard limit: <MINUTES> minutes. Repository: this worktree (branch <BRANCH>, on the Mac). Use absolute paths.
Never print scripts/promo/.token or .env. No push, no deploy.
Run EVERY command in the FOREGROUND and wait for it (Bash timeout 900000 ms for the pipeline): in headless mode a
backgrounded command dies with your session, and there is no next turn. Never end before the final message. Upload only if this brief says the owner said "upload".

PATTERN TO COPY: scripts/promo/layouts_capture.js + build2.py `video_layouts` (key "layouts"): Device page on the main
site (PROMO_BASE defaults to it), Server pick with a direct click then a verified label, Target filter, a `preflight`
mode, fail-closed checks before every hold (labels, tiles playing — tiles are <img> blob thumbnails or <video>, no
"Loading stream", no AI bar, no open dropdown), CDP screencast recorder (promo_lib startRecorder), fake cursor, glides for
on-camera clicks only, marks, "pair" scenes (menu clip ends AT the option click; hold clip starts after the tile check),
per-scene "voice" text. New video: scripts/promo/<CAPTURE>.js + a `video_<KEY>` entry (key "<KEY>", output
out/virtualpytest_<VIDEO>_<KEY>.mp4) in build2.py.

<DEVICES — only if the video drives devices>
- Devices: <server entry, host/device, model, remote>; NOT <devices to avoid and why>. No set-top box tile on screen.
- Leases: `ssh -o BatchMode=yes proxmox '~/bin/vpt-lease list'` / `claim -h`; claim every host you drive (`--kind host`) before the
  first command that takes control (preflight included), agent "mac:haiku-video<VIDEO>"; if held by someone else,
  wait up to 5 min then BLOCKED. Release at the end, also on failure. Release device control in a finally block.
- Stream quality: the controller set every filmed device to HD before this run; preflight re-reads
  `ssh <host> 'cat /var/www/html/stream/active_captures.conf'` (`<dir>,<pid>,<quality>`, captureN = deviceN) and
  stops BLOCKED if a filmed device is not `hd`.
- Wake phones before checks (screens sleep: black stream); measure the key-to-screen delay and size holds from it.
- App launcher lists apps by PACKAGE NAME (e.g. com.google.android.youtube), not by label.

STEPS
1. Preflight first (`node scripts/promo/<CAPTURE>.js preflight`): every beat's action and check, no recording.
2. Takes: `bash scripts/promo/video_pipeline.sh scripts/promo/<CAPTURE>.js <KEY> <N>` from the repo root (preflight ->
   take -> build -> promo_check -> contact sheet, each step timed in scripts/promo/out/<KEY>_pipeline<N>.log). Run it in
   the foreground (it takes 5-12 min). At most <TAKES> takes. promo_check: every counter 0, no waiver without the owner.
3. Look at one frame per beat (ffmpeg -ss <t> -frames:v 1 -> png, read it) and check it against the storyboard row.
4. Voice-over in scripts/promo: `python3 voiceover.py <KEY>`, then `python3 voice_fit.py <KEY>` until zero spills; then
   promo_check on the voiced mp4 (`--srt out/<name>.srt`, all 0 incl. voice_mismatch), `ffmpeg -v error -i <voiced>
   -f null -` silent, loudness -16 ±1 LUFS (`-af ebur128`), one frame per beat of the VOICED video.
5. scripts/promo/meta/draft_<VIDEO>.json per guide §7 (owner format, no URLs, chapters from the final SRT).
6. Commit the capture script, build2.py, voice_pad.json (if changed) and the meta draft with explicit `git add <file>`.

FINAL MESSAGE (short): preflight answers; promo_check tables (silent, voiced); duration; spills; loudness; per-step times
from the pipeline logs; takes used; leases claimed/released; what each beat's frame shows; the commit; the voiced mp4
path. Or BLOCKED with the reason and what you found.
