# Hot/Cold Archiver Workflow (Windows + Linux)

## Purpose (Short)
The archiver turns live FFmpeg segments into playable MP4 chunks and keeps storage tidy.
It runs two loops:
- FAST loop (every 15s): builds 1-minute MP4s and appends into 10-minute chunks.
- COLD loop (every 60s): cleanup tasks only.

The FAST loop is a retry mechanism. It does **not** force a new 1-minute video every 15 seconds; it only succeeds when enough segments exist.

## Data Flow (Intended)
1. FFmpeg writes live segments continuously:
   - Linux RAM mode: `.../hot/segments/`
   - Windows/SD mode: `.../segments/`
2. FAST loop reads the live segments folder and builds a 1-minute MP4.
3. That 1-minute MP4 is appended into a growing 10-minute chunk (`chunk_10min_X.mp4`).
4. Audio extraction (if available) is done from the 1-minute MP4.

## Why a 15s FAST Loop?
- Provides quick retries if FFmpeg hiccups.
- Keeps the 10-minute chunk growing with minimal delay.
- In practice, a new 1-minute MP4 is created only when enough segments exist.

## Windows vs Linux
- **Linux (RAM mode)** uses `/hot/` for live data and `/segments/` for cold storage.
- **Windows (no /hot)** uses `/segments/` directly. The FAST loop detects SD mode and reads from cold folders.

## What Creates What
- FFmpeg (`run_ffmpeg.sh` / `run_ffmpeg.ps1`) creates:
  - `segments/`, `captures/`, `thumbnails/`
- Archiver (`hot_cold_archiver.py`) creates:
  - `segments/<hour>/chunk_10min_*.mp4`
  - `audio/<hour>/` (if audio)
  - Transcript/metadata manifests as needed

## Active Capture Registry
- FFmpeg writes `active_captures.conf` at stream base:
  - Linux: `/var/www/html/stream/active_captures.conf`
  - Windows: `C:\virtualpytest\stream\active_captures.conf`
- Format:
  `capture_dir,PID,quality`

## Key Logs to Expect
- FAST loop mode and source folder:
  `FAST LOOP (Cold)` and `Segment source: C:\...\segments`
- Parsed active captures entries on startup.
