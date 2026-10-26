# Subtitle QA

Checks that subtitles appear when they should, say the right words, and show at the right time. It compares the film with its subtitle file (SRT), the reference. It runs on the machine itself, with no AI service and no cost per run.

## What it finds

| Problem | What it means |
|---|---|
| Missing subtitle | A subtitle should be on screen, but no text is shown |
| Unexpected subtitle | Text shows in the subtitle area, but no subtitle is defined there |
| Stuck subtitle | A subtitle stays on screen after it should have gone, or an old one shows over a new one |
| Wrong text | The text differs from the reference by more than 20% of its characters. The missing and extra words are listed |
| Truncated line | Only the start or the end of the line is shown |
| Late or early cue | The subtitle comes later or earlier than the speech. Without a transcript match, it is compared with the SRT |
| Wrong language | The text is in another language than the track |
| Overlap | Two subtitles are on screen at the same time |
| Unreadable contrast | The text is hard to read against what is behind it: contrast below 3:1 |

A problem must show across the whole subtitle. One bad frame in a subtitle that reads correctly is OCR noise, so it is shown as OK, with a note.

<div data-technical>

Report codes: `missing_subtitle`, `unexpected_subtitle`, `stuck_subtitle`, `wrong_text` (character error rate above 20%), `truncated_line`, `late_cue` / `early_cue`, `wrong_language`, `overlap`, `unreadable_contrast` (below 3:1).

</div>

## Sampling

The check does not look at every frame. It checks about 720 frames for a 12-minute film with 76 subtitles, under one frame per second.

<div data-technical>

Per film: 4 samples within ±0.5 s of every cue start and end, one in the middle of each cue, one every 5 s elsewhere, and (local mode, `--scene`) one at each scene change.

</div>

## Run it on your computer (no device)

Run the check on a film file, without a device. Install the tools first.

<div data-technical>

```bash
python3 scripts/subtitle_qa/package_source.sh <tears_of_steel_720p.mov> out/   # once: builds the .mkv with EN + DE tracks
python3 scripts/subtitle_qa/run.py --mkv out/tears_of_steel_subs.mkv --lang en,de --out report/ --credits-from 600 --scene
```

Needs `ffmpeg`, `tesseract-ocr` with the `eng` and `deu` packs, and `pip install pytesseract langdetect faster-whisper`.

The first run listens to the sound and keeps the transcript in `--out`. The 718 samples take about 2.5 min per language. Option `--credits-from 600` stops the check at 10:00, before the end credits, which would otherwise show as unexpected subtitles. Each language writes `subtitle_qa_<lang>.html` (self-contained, about 10 MB), and its numbers go to `results_<lang>.json`.

</div>

The first run takes about 4 minutes for 12 minutes of film, then each language takes about 2.5 minutes. You get one report per language.

The check stops at 10:00, before the end credits.

## Run it on a device

Run the script **subtitle_qa.py** like any other test. Pick a *local video* device in Test Execution.

You can set these options:
- **video**: a film with subtitle tracks built in. It runs on the host. The default is the Tears of Steel 480p .mkv.
- **lang**: `en`, `de` or `fr`.
- **credits_from**: the film second where the check stops. The default is 600 (10:00).
- **max_issues**: the run fails above this many problems. Use `-1` to only report.

<div data-technical>

Arguments: `video`, `lang`, `credits_from` (default 600), `max_issues` (`-1` = report only). Run from Test Execution, or through the API or the MCP `execute_script` call with `script_name=subtitle_qa.py`. The capture step runs for the full credits_from span: 10 min for 0–600 s by default. Progress reads like "Capturing: film 5:12 / 10:00, 314/633 frames, 4 missed".

</div>

What happens on the host:

1. The device plays the film **from the start**, with the chosen subtitle track drawn into the picture.
2. While it plays, the script saves a frame at each planned moment.
3. It checks every saved frame. Each flagged frame is checked again against the original file at the same moment.
4. It puts the device's previous video back.

A run on the vpt-pi4 host takes about 11.5 minutes, and the checking part 80 to 95 seconds.

## Reading the report

The run report links to the **Subtitle Report**. The subtitle report opens with a link back to the run report, then shows:

- **Verdict**: the result and the key numbers.
- **Issues by subtitle**: one line per subtitle with a problem. Open it to see each bad frame next to the expected text and what the source file shows.
- **Error mosaic**: one tile for each problem subtitle.
- **Not counted**: samples where the source file has the same fault.
- **Glossary** at the bottom explains the technical words.

<div data-technical>

Also in the report: **How the subtitles were read** (reading engine and version, which part of the picture is read and how, the source and capture sizes, and what the source check found), **Issues per type**, **Timeline**, **Cue timing** (collapsed) and **All samples** (collapsed, issues only by default, with filters). The Test Mosaic is the error mosaic. Not counted also covers samples where the text is part of the film picture.

</div>

## Device or reader?

Each flagged frame is checked against the clean source file.

- The source fails the same way: the fault is in the reader, or the text is part of the picture. It is not counted.
- The source reads correctly and the device frame does not: the fault is in what the device shows or in the capture.

<div data-technical>

On vpt-pi4 the 1150x480 film is captured as a 1280x720 MJPEG picture (stretched). That blurs the thin subtitle text. On a clean film, this is where the remaining flags come from.

</div>

## Limits

- On a clean film, a few false alarms remain from the capture or the reader. On vpt-pi4, 5 to 10 remain per run.
- About 2% of the planned frames get no close capture, because the Pi is busy. These frames are listed in the log.
- Text in the subtitle area, such as title cards and credits, is reported as an unexpected subtitle, unless the source file shows it in the film itself.
- Real problems are tested with made-up frames, not with a film that has faults put in on purpose.

<div data-technical>

- The source check removes some false alarms. The capture stalls for about 1 second now and then, because the Pi is also decoding the film, drawing the subtitle and running the other streams.
- The audio timing needs English speech and an English subtitle to line up with. For other languages, the matching English subtitle's audio time is used.
- The burnt-in subtitle shows only on the first playback of the file. The script always restarts the film.
- Synthetic-frame tests: `tests/shared/test_subtitle_qa.py`.

</div>

Source film: Tears of Steel, (CC) Blender Foundation, CC BY 3.0.

<div data-technical>

Subtitles come from the Blender download page (mango.blender.org). See `scripts/subtitle_qa/assets/ATTRIBUTION.txt`.

</div>
