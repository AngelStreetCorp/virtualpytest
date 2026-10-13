# scripts/promo — capture and build the product videos

The videos on the [Videos page](../../docs/videos/index.md) were made with these scripts,
end to end, with no manual screen recording. The process and the rules for a new video are in
[docs/tasks/VIDEO_PRODUCTION_GUIDE.md](../../docs/tasks/VIDEO_PRODUCTION_GUIDE.md); the queue of
videos to make next is [docs/tasks/TASK-28-next-videos.md](../../docs/tasks/TASK-28-next-videos.md).

| File | What it does |
|---|---|
| `capture.js` | Stills of every page + the device-modal and run-tests clips, with a fake cursor overlay. `node capture.js [stills\|clips\|all]` |
| `capture_rpi.js` | Same against a second server (dashboard, filtered Device page, heatmap in OK view, device clip) |
| `capture_videos.js` | Navigation-tree video assets: editor tidy + attach device, live goto over the API, report stills |
| `agent_capture2.js` | AI agent video: device panel open, one prompt per fresh chat, waits for the device lock and for each answer |
| `kpi_capture.js` | KPI video: editor with the edge's KPI section, the goto with the device modal, the edge chip and the KPI report walk, report stills. `node kpi_capture.js [editor\|goto\|kpireport\|testreport <url>\|report <url>\|all]`. No node dragging: the layout is the saved one |
| `cmp_capture.js` | Comparison-report video: the node's image check in the editor, the failing goto with the device modal, the failed step in the test report, the comparison page. `node cmp_capture.js [editor\|goto\|report <url>\|all]`; `PROMO_BASE=http://localhost:5073` when the prod frontend is slow |
| `zap_capture.js` | Zap video: Device page, stb4 on rpitest's vpt-pi3, Take Control, Monitoring, CH+, the zap card and its report, no script. `node zap_capture.js`, `node zap_capture.js key CHANNEL_DOWN …` (move the box off camera), `node zap_capture.js report <url>`; needs a local Vite on :5074 pointed at rpitest |
| `mon_capture.js` | 24 h monitoring video: rpitest Heatmap scrubbed to an incident, the device's Last 24h replay, the incident row with its frames; nothing driven. `node mon_capture.js <HH:MM:SS incident start>` (`MON_FROM=21h`, `MON_TILE=x,y`); needs a local Vite on :5074 pointed at rpitest |
| `game_capture.js` | 2048 video (TASK-33): Device page pre-filtered to the S21x and vpt-pi4, both runs launched over the API, the phone in big (HD), then the phone report's last move and its screenshot. Records the CDP screencast (1280x720 CSS at 1.5x = 1920x1080), not Playwright's recordVideo. `node game_capture.js [grid\|report <url>]`; `PROMO_BASE=https://localhost:5074` |
| `layouts_capture.js` | Video 25a (Device view, 1 to 48 devices): the vpt-pi4 server's HLS test streams in 24 / 12 / 48 per page, side by side, 2×2, one full, open in big; `preflight` checks every beat without recording. `node layouts_capture.js [preflight]` |
| `group_capture.js` | Video 25b (group control): S21x + S7 in one group, Home, Chrome by package name, type virtualpytest.com once, Scr↓ twice, release; fixed waits after each action for the slow S7; `preflight` mode. `node group_capture.js [preflight]` |
| `build.py` | Scene renderers (cards, caption overlays, Ken Burns stills, sped-up clips) and the 60 s promo scene list |
| `build2.py` | Scene lists for the walkthrough videos; `python build2.py navigation\|evidence\|ai\|kpi\|cmp\|zap\|mon\|qt\|game` |
| `thumbnail.py` | YouTube thumbnail in the series style |
| `voiceover.py` | English voice-over from the scene captions (MiniMax TTS, voice `English_Insightful_Speaker`, no music): `python3 voiceover.py <key>` after `build2.py <key>`; renders the voice track alone, writes `<voiced>.voice.json` and fails if a line is silent (BUG-0501). See VIDEO_PRODUCTION_GUIDE.md §5 |
| `frames_to_mp4.py` | Called by the recorder: normalises screencast frame sizes and replaces 1-4-frame zoom flashes |
| `promo_check.py` | Quality gate on a built video: counters (banned text by OCR, black frames, dark tiles, flashes, caption overflow, > 90 s, voice mismatch on the decoded audio, voice_silent: every voice line audible) that must all be 0; run before review, and `youtube_upload.py` runs it before every upload |
| `video_worktree.sh` / `builder_brief.md` / `run_builder.sh` / `video_pipeline.sh` | The builder loop (guide §0): a video worktree, the Haiku brief template, the headless Haiku run with cost, one timed take |
| `youtube_upload.py` | YouTube Data API: upload, update, thumbnail, playlist, delete (`meta/<id>.json`); refuses a video that fails `promo_check.py` unless `--skip-check` (logged in the meta json; an owner dark waiver goes in the meta as `promo_check_allow_dark`); credentials incl. `YOUTUBE_REFRESH_TOKEN` in the main `.env`; see the `youtube-upload` skill |
| `token_log.py` | Token spend per video (Claude Code session or MiniMax Code run) appended to `token_log.jsonl`; `report` prints tokens, new tokens and API-equivalent $ per video. See VIDEO_PRODUCTION_GUIDE.md §6 |
| `fonts/` | Inter Regular + Bold, the only font of the series |

## Where the takes and videos live

The raw takes (`raw*/`: clips, `*.marks.json`, stills) and the built files (`out/`) are gitignored.
The copy everyone can reach is on **codebox** (the coding VM, `ssh codebox`), in
`~/virtualpytest-promo/`, laid out like this folder: `raw*/`, `out/` (MP4, SRT, thumbnails).
After every take or build, from the machine that made it:

```bash
rsync -av raw* out codebox:virtualpytest-promo/
```

From Windows without rsync: `scp -r raw* out codebox:virtualpytest-promo/`. To rebuild somewhere
else, copy `raw*/` from there into this folder first, then run `build*.py`.

## Prerequisites

- Runs the same on Windows, macOS and Linux (codebox included). The font is Inter, committed in
  `fonts/` (SIL OFL, `fonts/OFL.txt`): every video uses it, never a system font, so a build on any OS
  gives the same frames. `ffmpeg` 4.2+ on PATH; `pip install pillow`.
- Playwright + Chromium from `tests/e2e/playwright` (`npm install && npx playwright install chromium`).
- A file `.token` next to the scripts holding `AUTO_SIGN_TOKEN` of the target server (never commit it;
  it is in `/opt/virtualpytest/.env` on the server VM, root-owned).
- The captures run against a frontend on `http://localhost:5073` by default (`PROMO_BASE` overrides):
  a local `vite` dev server pointed at the prod API, or prod itself. Prod is fine since the auto-sign
  fixes of 2026-09-27; the local dev server blocks cross-origin R2 thumbnails, which the scripts
  proxy through Playwright.

## Pipeline

```bash
node capture.js all          # raw/*.png, raw/*.webm + raw/*.marks.json (timestamps of each step)
python build.py              # out/virtualpytest_promo_60s.mp4 + .srt
python build2.py navigation  # out/virtualpytest_02_navigation_tree.mp4
python thumbnail.py raw/devices.png out/thumb.jpg "Any screen." "Tested 24/7." "TV, STB, mobile and web"
```

Each clip records the whole interaction; `*.marks.json` holds the second at which each step
happened, and the scene lists in `build*.py` cut and speed up around those marks. Stills get a
slow zoom or a vertical pan; captions are burned in and also written to an SRT.
