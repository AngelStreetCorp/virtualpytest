#!/usr/bin/env python3
"""
vpt-windows host_vnc audio capture (WASAPI loopback, Stereo Mix fallback).

Reads raw PCM from the host and writes a constant-rate PCM stream to stdout for
ffmpeg to consume (the matching `run_audio_stereo_mix.ps1` pipes this script's
stdout into `-f s16le ...`). The Linux equivalent is `run_ffmpeg.sh` where
`-f pulse -i default` muxes the audio directly into HLS; on Windows host_vnc the
video goes over noVNC (separate path), so the audio lives on its own dedicated
HLS playlist that the dashboard plays alongside the iframe.

Two capture modes:

* `loopback` (default): WASAPI loopback of the **default speaker** via the
  `soundcard` package. Captures what the machine is actually playing, on any
  output endpoint (Realtek analog/digital, HDMI, USB headset). Must run in the
  interactive session (session 1) -- a session-0 service has no audio endpoint.
* `stereo_mix`: the Realtek `Mixage stéréo` / `Stereo Mix` input via
  sounddevice/WDM-KS. Kept as a fallback; it only loops the Realtek analog mix,
  so it records silence when the default output is digital or USB (measured
  -90 dB on vpt-windows while a sound played).

Why this script and not a pure PowerShell capture? sounddevice is a thin wrapper
over PortAudio and the WASAPI host API, which exposes the Stereo Mix source that
device-manager/PnP hides from `dshow`. It also gives clean process-level control
the Scheduled Task can stop and self-heal just like `run_ffmpeg.ps1` does.

Self-heal:
  - If `Mixage st\u00e9r\u00e9o` (the French local-name of Realtek Stereo Mix) is not
    visible to sounddevice, exit 11 with a clear message so the parent ps1 can
    log "Stereo Mix not exposed" and pause the restart loop instead of crashing
    fast.
  - If the PortAudio stream raises (device unplugged, driver reset), the script
    exits 1 and the parent ps1 restarts in 5 s like the existing `vpt-stream`
    pattern (BUG-0592).

Env contract:
  VPT_AUDIO_DEVICE_HINT    optional; if "Mixage_stereo", "stereo_mix", or
                            "Stereo Mix", prefer the French "Mixage st\u00e9r\u00e9o"
                            first (what most Win10/11 Realtek installs expose).
                            Falls back to scanning all host APIS for a device
                            whose name contains "Stereo Mix", "Mixage", or
                            "What U Hear". Default: scan.
  VPT_AUDIO_SAMPLE_RATE    int, default 44100
  VPT_AUDIO_CHANNELS       int, default 2
  VPT_AUDIO_BLOCKSIZE      int, default 4096

Usage:
  python3 capture_audio_stereo_mix.py          # env-driven
  python3 capture_audio_stereo_mix.py --probe  # print chosen device + exit

The output is unsigned 16-bit little-endian PCM, 2-channel, 44.1 kHz by
default. ffmpeg consumes it as `-f s16le -ar 44100 -ac 2 -i -`.

Ref: BUG-0595 (planned), EMULATOR.md vpt-windows Native Emulator section.
"""

from __future__ import annotations

import os
import sys
import time
import signal
import argparse
import traceback
from typing import Optional

import numpy as np
import sounddevice as sd


# Realtek's French translation of Stereo Mix on Win10/11 -- what the install
# typically exposes to sounddevice but hides from dshow. Listed first so the
# hint "Mixage_stereo" prefers it explicitly. Other localizations of "Stereo
# Mix" are matched by the scan-fallback (German "Stereo-Mix", Spanish "Mezcla
# est\u00e9reo", Italian "Mix stereo", etc.).
DEVICE_NAME_PATTERNS = [
    "Mixage st\u00e9r\u00e9o",          # fr-FR Realtek default
    "Mix st\u00e9r\u00e9o",              # variant
    "Mixage",
    "Stereo Mix",
    "Stereo-Mix",
    "Mezcla est\u00e9reo",
    "Mix stereo",
    "What U Hear",
]


def _log(line: str) -> None:
    """One-line stdlib logger -- no prints at module import.

    sounddevice's PortAudio callback can deadlock if Python's stdout blocks,
    so every write uses an explicit flush.
    """
    print(line, file=sys.stderr, flush=True)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        _log(f"[capture] {name}={raw!r} not an int, falling back to {default}")
        return default


def _soundcard_available() -> bool:
    try:
        import soundcard  # noqa: F401
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"[capture] soundcard not available ({e!r}); using Stereo Mix")
        return False


def find_stereo_mix_device(hint: Optional[str] = None) -> Optional[int]:
    """Return the device index for the host's Stereo Mix source, or None.

    The `hint` shortcuts the common Realtek install -- "Mixage_stereo",
    "stereo_mix", "Mixage" -- so we prefer the localized name without scanning.

    Fallback: scan every sounddevice-visible input device for a name that
    matches `DEVICE_NAME_PATTERNS`. Return the first match.
    """
    if hint:
        # Normalize the hint
        norm = hint.lower().replace("_", " ").replace("-", " ")
        # Direct substring match against device names
        candidates = []
        for i, dev in enumerate(sd.query_devices()):
            if not dev["name"]:
                continue
            name_norm = dev["name"].lower()
            if norm in name_norm:
                candidates.append((i, dev["name"], dev["max_input_channels"]))

        # If the hint is specifically pointing at "stereo_mix"/"Mixage_stereo",
        # prefer devices whose name matches our localized patterns first so the
        # French "Mixage st\u00e9r\u00e9o" wins over a phantom "Mic" alt-name.
        if hint.lower() in ("mixage_stereo", "stereo_mix", "mixage"):
            for i, name, ch in candidates:
                for pattern in DEVICE_NAME_PATTERNS:
                    if pattern.lower() in name.lower() and ch and ch > 0:
                        return i

        # Otherwise first input-capable match
        for i, name, ch in candidates:
            if ch and ch > 0:
                return i

    # Scan fallback: any input device whose name matches Stereo Mix patterns
    for i, dev in enumerate(sd.query_devices()):
        if not dev["name"]:
            continue
        if not dev["max_input_channels"]:
            continue
        name = dev["name"]
        for pattern in DEVICE_NAME_PATTERNS:
            if pattern.lower() in name.lower():
                return i
    return None


def describe_chosen_device(idx: int) -> str:
    dev = sd.query_devices(idx)
    hostapi_name = sd.query_hostapis(dev["hostapi"])["name"]
    return (
        f"[capture] device idx={idx} name={dev['name']!r} "
        f"hostapi={hostapi_name!r} in={dev['max_input_channels']} "
        f"out={dev['max_output_channels']}"
    )


def stream_to_stdout(
    device_idx: int,
    sample_rate: int,
    channels: int,
    blocksize: int,
) -> int:
    """Open the input stream and pump raw PCM to stdout until cancelled.

    Returns the process exit code (0 on graceful shutdown via SIGINT/SIGTERM).
    """
    written_frames = 0
    keep_running = True

    def _stop(signum, frame):  # noqa: ARG001 -- signal handler signature
        nonlocal keep_running
        _log(f"[capture] caught signal {signum}, draining and stopping")
        keep_running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        nonlocal written_frames
        nonlocal keep_running
        if status:
            # PortAudio flags: input overflow, etc. -- log but keep streaming.
            _log(f"[capture] PortAudio status: {status!r}")
        if not keep_running:
            raise sd.CallbackStop  # type: ignore[attr-defined]
        # numpy 2.x removed the .tobytes alias on raw cffi buffers; bytes() works
        # for any memoryview-compatible object.
        try:
            sys.stdout.buffer.write(bytes(indata))
        except OSError as e:
            # BrokenPipeError is an OSError; on Windows a closed pipe can also
            # surface as "[Errno 22] Invalid argument" (seen when ffmpeg exits
            # first). Either way there is no reader left: stop cleanly instead
            # of letting the callback raise on every block.
            _log(f"[capture] stdout write failed ({e!r}), stopping")
            keep_running = False
            raise sd.CallbackStop  # type: ignore[attr-defined]
        written_frames += frames

    _log(
        f"[capture] opening stream device={device_idx} sr={sample_rate} "
        f"ch={channels} blocksize={blocksize}"
    )
    stream = sd.RawInputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        device=device_idx,
        blocksize=blocksize,
        callback=callback,
    )
    stream.start()
    _log("[capture] stream started")
    try:
        # Use a polling sleep so signal handlers can flip keep_running.
        while keep_running:
            time.sleep(0.5)
            # Detect parent died (ffmpeg killed) via a broken pipe on stdout.
            try:
                sys.stdout.buffer.flush()
            except (BrokenPipeError, ValueError, OSError):
                _log("[capture] stdout closed (parent exited), stopping")
                break
    finally:
        try:
            stream.stop()
        except Exception as e:  # noqa: BLE001
            _log(f"[capture] stream.stop ignored: {e!r}")
        try:
            stream.close()
        except Exception as e:  # noqa: BLE001
            _log(f"[capture] stream.close ignored: {e!r}")

    _log(f"[capture] drained frames={written_frames} bytes={written_frames * channels * 2}")
    return 0


def loopback_to_stdout(sample_rate: int, channels: int, blocksize: int) -> int:
    """Capture the default output device's WASAPI loopback and pump PCM to stdout.

    Why loopback and not Stereo Mix: "Mixage stereo" only loops the Realtek
    analog mix. When the default output is Realtek Digital Output, an HDMI
    monitor or a USB headset, Stereo Mix records pure silence (measured:
    -90 dB while a sound played on vpt-windows). WASAPI loopback follows
    whatever the current default speaker is, so the captured stream is what a
    person in front of the machine would hear.

    Requires the process to run in the interactive session (session 1): a
    session-0 service has no audio endpoint to loop back.
    """
    import soundcard as sc

    keep_running = True
    written_frames = 0

    def _stop(signum, frame):  # noqa: ARG001
        nonlocal keep_running
        _log(f"[capture] caught signal {signum}, draining and stopping")
        keep_running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    speaker = sc.default_speaker()
    mic = sc.get_microphone(speaker.name, include_loopback=True)
    _log(
        f"[capture] loopback speaker={speaker.name!r} mic={mic.name!r} "
        f"sr={sample_rate} ch={channels} blocksize={blocksize}"
    )
    with mic.recorder(samplerate=sample_rate, channels=channels, blocksize=blocksize) as rec:
        _log("[capture] loopback stream started")
        while keep_running:
            data = rec.record(numframes=blocksize)
            if data is None or len(data) == 0:
                time.sleep(0.02)
                continue
            pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
            if pcm.ndim == 1:
                pcm = np.repeat(pcm[:, None], channels, axis=1)
            elif pcm.shape[1] < channels:
                pcm = np.repeat(pcm[:, :1], channels, axis=1)
            elif pcm.shape[1] > channels:
                pcm = pcm[:, :channels]
            try:
                sys.stdout.buffer.write(pcm.tobytes())
                sys.stdout.buffer.flush()
            except OSError as e:
                _log(f"[capture] stdout write failed ({e!r}), stopping")
                break
            written_frames += pcm.shape[0]

    _log(f"[capture] drained frames={written_frames} bytes={written_frames * channels * 2}")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Stereo Mix PCM capture for ffmpeg pipe")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="print the chosen device + parameters and exit",
    )
    parser.add_argument(
        "--device-hint",
        default=os.environ.get("VPT_AUDIO_DEVICE_HINT", ""),
        help=(
            "preferred device name fragment for stereo_mix mode: 'Mixage_stereo' / "
            "'stereo_mix' / etc. Defaults to env VPT_AUDIO_DEVICE_HINT."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "loopback", "stereo_mix"),
        default=os.environ.get("VPT_AUDIO_CAPTURE_MODE", "auto"),
        help=(
            "auto (default) uses WASAPI loopback of the default speaker, falling back "
            "to Stereo Mix when soundcard is unavailable; loopback forces WASAPI "
            "loopback; stereo_mix forces the Realtek/Stereo Mix input path."
        ),
    )
    args = parser.parse_args(argv)

    hint = args.device_hint.strip() or None
    sr = _env_int("VPT_AUDIO_SAMPLE_RATE", 44100)
    ch = _env_int("VPT_AUDIO_CHANNELS", 2)
    bs = _env_int("VPT_AUDIO_BLOCKSIZE", 4096)

    mode = args.mode
    if mode == "auto":
        mode = "loopback" if _soundcard_available() else "stereo_mix"
    _log(f"[capture] mode={mode}")

    if mode == "loopback":
        try:
            import soundcard as sc

            speaker = sc.default_speaker()
            mic = sc.get_microphone(speaker.name, include_loopback=True)
            _log(f"[capture] loopback device: speaker={speaker.name!r} mic={mic.name!r}")
        except Exception as e:  # noqa: BLE001
            _log(f"[capture] FATAL: WASAPI loopback unavailable: {e!r}")
            return 11
        if args.probe:
            return 0
        try:
            return loopback_to_stdout(sr, ch, bs)
        except Exception as e:  # noqa: BLE001
            _log(f"[capture] unexpected (loopback): {e!r}\n{traceback.format_exc()}")
            return 1

    idx = find_stereo_mix_device(hint)
    if idx is None:
        _log(
            "[capture] FATAL: no Stereo Mix / Mixage stereo source visible to sounddevice. "
            "Enable the device in Sound Control Panel > Recording > right-click > Show "
            "Disabled Devices, then re-enable 'Stereo Mix' (or 'Mixage st\u00e9r\u00e9o')."
        )
        return 11

    _log(describe_chosen_device(idx))
    _log(f"[capture] sr={sr} ch={ch} blocksize={bs} bytes/sec={sr * ch * 2}")

    if args.probe:
        return 0

    try:
        return stream_to_stdout(idx, sr, ch, bs)
    except sd.PortAudioError as e:
        _log(f"[capture] PortAudioError: {e!r}\n{traceback.format_exc()}")
        return 1
    except Exception as e:  # noqa: BLE001
        _log(f"[capture] unexpected: {e!r}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
