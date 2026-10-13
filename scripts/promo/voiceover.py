"""Add a spoken voice-over to a built video: each scene's voice text (its "voice" option when it has one, else its
caption; cards: title + subtitle) is read by a TTS voice, placed at the scene's start and mixed into an audio track. Run after `python3 build2.py <key>` (it reads the scene
segments that build left in WORK, so the timing is the video's own).

Usage: python3 voiceover.py <video-key> [--voice English_expressive_narrator] [--model speech-02-hd]
       -> out/<name>_voice-<voice>.mp4 (the silent build is kept)
TTS is MiniMax T2A v2 (MINIMAX_API_KEY in ~/virtualpytest/.env, never printed; the OpenAI key there is empty).
TTS clips are cached in WORK/tts/ by text+voice.
A line longer than its scene is sped up (atempo, up to 1.25x); beyond that it is reported, not cut.
"""
import argparse
import hashlib
import json
import sys
import ssl
import subprocess
import urllib.request
from pathlib import Path

import certifi

import build2
from build import WORK, OUT, FFMPEG

ENV = Path(__file__).resolve().parents[2] / ".env"


def env(name):
    for line in ENV.read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} missing in {ENV}")


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def tts(text, voice, model, key, speed=1.0):
    d = WORK / "tts"; d.mkdir(exist_ok=True)
    out = d / (hashlib.sha1(f"{model}|{voice}|{text}".encode() if speed == 1.0 else f"{model}|{voice}|{speed}|{text}".encode()).hexdigest()[:16] + ".mp3")
    if out.exists():
        return out
    body = json.dumps({"model": model, "text": text, "stream": False,
                       "voice_setting": {"voice_id": voice, "speed": speed, "vol": 1.0, "pitch": 0},
                       "audio_setting": {"sample_rate": 44100, "bitrate": 128000, "format": "mp3", "channel": 1}}).encode()
    req = urllib.request.Request("https://api.minimax.io/v1/t2a_v2", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120, context=ssl.create_default_context(cafile=certifi.where())) as r:
        d = json.load(r)
    if d.get("base_resp", {}).get("status_code") != 0 or not (d.get("data") or {}).get("audio"):
        raise SystemExit(f"TTS failed: {d.get('base_resp')}")
    out.write_bytes(bytes.fromhex(d["data"]["audio"]))
    return out


def lines(key):
    """(start, scene length, text) per scene, from the scene list and the built segments."""
    fn, name = build2.VIDEOS[key]
    t, res = 0.0, []
    for i, sc in enumerate(fn(), 1):
        seg = WORK / f"{key}_s{i:02d}.mp4"
        d = duration(seg)
        if build2._opts(sc).get("voice"):
            text = build2._opts(sc)["voice"]
        elif sc[0] == "card":
            big, small = sc[1], sc[2]
            text = f"{big}." if i == 1 else small      # opening card: the title only (owner: a long still opening loses viewers)
        else:
            text = sc[3]
        res.append((t, d, text)); t += d
    return name, res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("key"); ap.add_argument("--voice", default="English_Insightful_Speaker")   # owner pick, 2026-10-06
    ap.add_argument("--model", default="speech-02-hd")
    ap.add_argument("--fade", type=float, default=0.2, help="fade in/out on every line, seconds (owner: 0.2)"); a = ap.parse_args()
    key = env("MINIMAX_API_KEY")
    name, ls = lines(a.key)
    video = OUT / name
    inputs, filters, labels = ["-i", str(video)], [], []
    prev_end, placed = 0.0, []
    for n, (start, d, text) in enumerate(ls, 1):
        wav = tts(text, a.voice, a.model, key); spoken = duration(wav)
        at = max(start + 0.35, prev_end + 0.2)           # never overlap the previous line
        room = start + d - 0.25 - at
        tempo = min(max(spoken / room, 1.0), 1.12) if room > 0 else 1.12   # a light speed-up only; else it spills over
        if tempo > 1.0:   # ask the TTS to speak faster (clean) instead of time-stretching the audio (warbles)
            wav = tts(text, a.voice, a.model, key, speed=round(tempo + 0.01, 2)); spoken = duration(wav)
        if spoken > room + 0.05:
            print(f"  ~ scene {n}: spills {spoken - room:.1f}s into the next scene")
        inputs += ["-i", str(wav)]
        # short fades on both ends of every line, so no line starts or stops with a click
        filters.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=mono,highpass=f=80,afftdn=nr=12:nf=-50:tn=1,afade=t=in:d={a.fade},"
                       f"areverse,afade=t=in:d={a.fade},areverse,adelay={int(at * 1000)}:all=1[a{n}]")
        labels.append(f"[a{n}]"); prev_end = at + spoken; placed.append({"at": round(at, 3), "dur": round(spoken, 3), "text": text})
        print(f"  {at:6.2f}s  speed {max(tempo, 1.0):.2f}  {text}")
    vlen = duration(video); hold = max(0.0, prev_end + 0.6 - vlen)   # the voice may outlast the picture: hold the last frame
    total = vlen + hold   # pad the voice track to exactly the picture's length (an open-ended apad never ends)
    mix = f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,acompressor=threshold=-24dB:ratio=3:attack=15:release=250:makeup=2,apad=whole_dur={total:.3f},atrim=0:{total:.3f}"
    # loudness in two passes: measure the whole voice track once, then apply ONE fixed gain (linear). The one-pass
    # (dynamic) loudnorm rides the gain up in every pause, so lines jump in and drop out ("goes loud and stops").
    r = subprocess.run([FFMPEG, "-v", "info", *inputs, "-filter_complex", f"{';'.join(filters)};{mix},"
                        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json[m]", "-map", "[m]", "-f", "null", "-"],
                       capture_output=True, text=True)
    meas = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    filters.append(f"{mix},loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:measured_I={meas['input_i']}:"
                   f"measured_TP={meas['input_tp']}:measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
                   f"offset={meas['target_offset']},aresample=48000,aformat=channel_layouts=stereo[aout]")
    # The voice track is rendered on its own first, then muxed with the picture. Mixing it in the same graph as the
    # video (tpad + x264) made amix drop whole lines at random (25b: "Two Android phones, live" went silent).
    mixwav = WORK / f"{video.stem}_voice.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[aout]", str(mixwav)], check=True)
    vf, vcodec = [], ["-c:v", "copy"]
    if hold > 0:
        vf, vcodec = ["-vf", f"tpad=stop_mode=clone:stop_duration={hold:.2f}"], ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"]
    out = video.with_name(f"{video.stem}_voice-{a.voice}.mp4")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-i", str(mixwav), *vf, "-map", "0:v", "-map", "1:a",
                    *vcodec, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True)
    # The voice map lets promo_check hear every line; check it here too, so a dropped line fails at the source.
    Path(str(out) + ".voice.json").write_text(json.dumps(placed, indent=1))
    from promo_check import audio_pcm, silent_lines
    silent = silent_lines(audio_pcm(out), placed)
    for at, text, db in silent:
        print(f"  ! SILENT at {at:.2f}s ({db:.0f} dBFS): {text}")
    print(f"DONE {out} {duration(out):.1f}s")
    if silent:
        sys.exit(f"{len(silent)} voice line(s) silent in {out}")


if __name__ == "__main__":
    main()
