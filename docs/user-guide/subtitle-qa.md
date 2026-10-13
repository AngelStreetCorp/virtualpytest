# Subtitle QA

Checks that subtitles are shown when they should be, say the right words, and appear at the right
time. It works on a film that has an SRT as ground truth. It reads the picture with tesseract OCR
and the sound with faster-whisper, so it needs no AI service and costs nothing per run.

## What it finds

| Issue | Meaning |
|---|---|
| `missing_subtitle` | A cue is active but no subtitle text is on screen |
| `unexpected_subtitle` | Text in the subtitle band where no cue is defined |
| `stuck_subtitle` | A finished cue is still shown, or an old cue shows over a new one |
| `wrong_text` | Text differs from the cue (character error rate above 20%); missing and extra words are listed |
| `truncated_line` | Only the start or end of the expected line is shown |
| `late_cue` / `early_cue` | The cue appears later / earlier than the speech (audio transcript) or, without a transcript match, the SRT |
| `wrong_language` | The shown text is in another language than the track |
| `overlap` | Two cues on screen together |
| `unreadable_contrast` | Text is shown but its contrast against what surrounds it is below 3:1 |

A defect must hold for the whole cue. A bad read in one frame of a cue whose other frames read
correctly is OCR noise and is shown as OK with a note.

## Sampling

Not every frame is analysed. Per film: 4 samples within ±0.5 s of every cue start and end, one in the
middle of each cue, one every 5 s elsewhere, and (local mode, `--scene`) one at each scene change.
For the 12 min Tears of Steel with 76 cues that is about 720 samples, under 1 per second.

## Run it locally (no device)

```bash
python3 scripts/subtitle_qa/package_source.sh <tears_of_steel_720p.mov> out/   # once: builds the .mkv with EN + DE tracks
python3 scripts/subtitle_qa/run.py --mkv out/tears_of_steel_subs.mkv --lang en,de --out report/ --credits-from 600 --scene
```

Needs `ffmpeg`, `tesseract-ocr` with the `eng` and `deu` packs, and `pip install pytesseract langdetect faster-whisper`.
The first run transcribes the audio (about 4 min for 12 min of film on one CPU thread) and caches it in
`--out`; the 718 samples then take about 2.5 min per language. Output: `subtitle_qa_<lang>.html` (self
contained, about 10 MB), `results_<lang>.json`.

`--credits-from 600` stops judging at 10:00: end credits are picture text in the subtitle band and would
be reported as `unexpected_subtitle`.

## Run it on a device

Run the script **subtitle_qa.py** like any other test, on a *local video* device (Test Execution, or the API /
MCP `execute_script` with `script_name=subtitle_qa.py`). Arguments: `video` (a film with embedded subtitle tracks on the
host, default the Tears of Steel 480p .mkv), `lang` (`en`, `de`, `fr`), `credits_from` (stop at this film second,
default 600), `max_issues` (fail the run above this many issues; `-1` = report only).

What happens, on the host:

1. The device plays the film **from second 0** with the chosen subtitle track drawn into the picture.
2. While the film plays (10 min for 0–600 s), the script copies the frame of every planned sample. Progress shows
   "Capturing: film 5:12 / 10:00, 314/633 frames, 4 missed".
3. Then it reads every saved frame and checks it ("Analysing: 368/620 samples, 23 with an issue so far"), and
   re-reads each flagged frame from the original file at the same moment ("Checking flagged samples against the
   source file").
4. It puts the device's previous video back.

On vpt-pi4 a run takes about 11.5 minutes; the analysis part takes 80–95 s.

## Reading the report

The run report shows the three steps (play, capture, check) and, in its links, **Subtitle Report**. Its Test
Mosaic is the error mosaic. The subtitle report opens with a link back to the run report, then:

- **Verdict** and the key numbers.
- **How the subtitles were read**: OCR engine and version, which part of the frame is read and how, the source
  and capture resolutions, and what the source check found.
- **Issues by cue**: one line per cue with a problem; open it to see each bad frame, the subtitle band enlarged,
  what OCR read, the expected text, the audio around it, and what the source file shows at that moment.
- **Error mosaic**: one tile per problem cue.
- **Not counted**: samples where the source file fails the same way (OCR limit) or the text is part of the film
  picture, device and source side by side.
- **Issues per type**, **Timeline**, **Cue timing** (collapsed) and **All samples** (collapsed, "issues only" by
  default, with filters).
- **Glossary** at the bottom; technical words in the report (cue, CER, OCR noise, lag…) link to it.

## Is it the device or our OCR?

Every flagged sample is read again from the source .mkv at the same moment, where the subtitle is clean. If the
file fails the same way, the problem is OCR (or picture text) and the sample is not counted. If the file reads
correctly and the device frame does not, the difference is in what the device shows or in the capture. On vpt-pi4
the 1150x480 film is captured as a 1280x720 MJPEG picture (stretched), which blurs the thin subtitle text: on a clean
film that is where the remaining flags come from.

## Limits

- On a clean film the remaining flags are false positives of the capture or of OCR; the source check removes
  part of them (5–10 per run on vpt-pi4).
- A few planned frames per run have no capture close enough (about 2%): the capture stalls for ~1 s now and then
  while the Pi decodes the film, draws the subtitle and runs the other streams. They are listed in the log.
- Picture text in the subtitle band (title cards, credits) is reported as `unexpected_subtitle` unless the source
  check shows it in the film itself; `credits_from` stops before the end credits.
- Audio timing needs English speech and an English cue to anchor on; for other languages the matching English
  cue's audio time is used.
- Detection of real defects is covered by synthetic-frame tests (`tests/shared/test_subtitle_qa.py`), not by a
  bug-injected film.
- The burnt-in subtitle only shows during the first playback of the file; the script always restarts the film.

Source film: Tears of Steel, (CC) Blender Foundation | mango.blender.org, CC BY 3.0. Subtitles from the
Blender download page. See `scripts/subtitle_qa/assets/ATTRIBUTION.txt`.
