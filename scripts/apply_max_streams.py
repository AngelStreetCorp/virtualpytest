#!/usr/bin/env python3
"""apply_max_streams.py — bump vpt-nipogi from the 24-stream baseline to the
35-stream max-real-streams layout (TASK-95 §8.10).

Replaces the 4 broken/slow sources (DEVICE5 LCP Public Senat, DEVICE10 Cine
Action Pluto, DEVICE14 Cine Horreur Pluto, DEVICE19 One Piece Pluto) with
verified 720p HLS variants from the doc at docs/agent/iptv-france-streams/
STREAMS.md, and adds 12 new 720p devices (DEVICE25-36) from the same doc.
Also adds DEVICE<N>_VIDEO_CAPTURE_PATH and DEVICE<N>_VIDEO_STREAM_PATH for
each new device — without them, ffmpeg writes to a bare "/hot/..." path
and is killed at start (BUG: ffmpeg exits 1 with "no such file" in the
rename step).

Sources come from the iptv-org fr.m3u probed on 2026-10-16 07:36 UTC
(STREAMS.md §"TL;DR" — 137/214 verified playable). Per the doc:

  - 12 of the 16 picked channels are jmp2.uk Pluto variants at 720p
    (Pluto TV Histoire, Dating, Toons FR, Snooker 900, Kids Classics FR,
    Teen FR, Voyages & Saveurs, Ridiculousness, Teen Mom, Tortues Ninja,
    Turbo).
  - 3 are regional/local French: Alpe d'Huez TV (infomaniak), ILTV
    (creacast), Littoral FM TV (creacast).
  - 1 is Brionnais TV (mandarine) and 1 is TV3V (live-kd).

Idempotent: re-running detects existing device blocks and rewrites them
in place; new devices that are already appended are skipped.

Usage:
  scripts/apply_max_streams.py vpt-nipogi           # apply
  scripts/apply_max_streams.py --check vpt-nipogi  # dry-run

Backup is at /opt/virtualpytest/backend_host/src/.env.bak.<ts> written by
the operator before running (the script reads but does not write the .env
backup — it does a sed-style rewrite on the live file via sudo tee).

After applying, restart vpt-stream once:

  ssh vpt-nipogi 'sudo systemctl restart vpt-stream'

Per-device decode cost (TASK-95 §8.8, §8.10): 0.32 core/stream at 1080p,
0.20 core/stream at 720p. With 19 1080p + 16 720p, total = 6.08 + 3.20 =
9.28 cores (nipogi has 8 cores × 0.95 = 7.6 usable). The 35 streams
saturate the host; expect 0% idle and per-stream `speed` 0.7-1.0x.

For BFM and other UA-gated streams, set DEVICE<N>_USER_AGENT to the
Mozilla UA the CDN expects — run_ffmpeg.sh reads it (commit
TASK-95 §8.10) and adds `-user_agent` to the ffmpeg input.
"""
import re
import subprocess
import sys
import time

# (idx, NAME, VIDEO) — verified 720p working channels from STREAMS.md.
# 4 replacements (5, 10, 14, 19) keep the same index, change the URL to a
# 720p variant that is actually fast.
REPLACE = {
    5:  ("FR Music 1 — Pluto TV Histoire (720p)",     "https://jmp2.uk/plu-611e771e2f5f180007002224.m3u8"),
    10: ("FR Movie 7 — Pluto TV Dating (720p)",      "https://jmp2.uk/plu-682318568e6c0f2f6c6e0038.m3u8"),
    14: ("FR Movie 8 — Pluto TV Toons FR (720p)",    "https://jmp2.uk/plu-5f8eba14a4ffb8000764e950.m3u8"),
    19: ("FR Anime 4 — Pluto TV Snooker 900 (720p)", "https://jmp2.uk/plu-66fd35e44ca31f0008060b77.m3u8"),
}
# 12 new 720p devices at DEVICE25..36
NEW = {
    25: ("FR Kids 1 — Pluto TV Kids Classics FR (720p)", "https://jmp2.uk/plu-654a58dbf9cc82000868f0fb.m3u8"),
    26: ("FR Kids 2 — Pluto TV Teen FR (720p)",          "https://jmp2.uk/plu-5f8eb99ff17815000784a3b0.m3u8"),
    27: ("FR Travel — Voyages & Saveurs (720p)",         "https://jmp2.uk/plu-680291e38e1ff89c2427aefd.m3u8"),
    28: ("FR Comedy — Ridiculousness DE (720p)",         "https://jmp2.uk/plu-5f8eb8a8b2619a000710605c.m3u8"),
    29: ("FR Reality — Teen Mom DE FR (720p)",           "https://jmp2.uk/plu-62f3f05505e621000783df2f.m3u8"),
    30: ("FR Kids 3 — Tortues Ninja TV DE (720p)",       "https://jmp2.uk/plu-5f8ecc1b37867f00071469e9.m3u8"),
    31: ("FR Series — Turbo (720p)",                    "https://jmp2.uk/plu-66f55c3955567d0008ef9b68.m3u8"),
    32: ("FR Regional 1 — Alpe d'Huez TV (720p)",        "https://edge13.vedge.infomaniak.com/livecast/ik:adhtv/manifest.m3u8"),
    33: ("FR Regional 2 — ILTV (720p)",                 "https://live.creacast.com/iltv/smil:iltv.smil/playlist.m3u8"),
    34: ("FR Regional 3 — Littoral FM TV (720p)",        "https://live.creacast.com/littoralfm-ch1/stream/playlist.m3u8"),
    35: ("FR Regional 4 — Brionnais TV (720p)",          "https://stream2.mandarine.media/brionnaistv/brionnaistv/playlist.m3u8"),
    36: ("FR Regional 5 — TV3V (720p)",                  "https://tv3v.live-kd.com/live/tv3v/livestream/index.m3u8"),
}
ALL = {**REPLACE, **NEW}


def ssh_run(host, *args, check=True, capture=False, text=True):
    cmd = ["ssh", "-o", "BatchMode=yes", host, *args]
    return subprocess.run(cmd, check=check, capture_output=capture, text=text)


def read_env(host):
    return ssh_run(host, "sudo -n cat /opt/virtualpytest/backend_host/src/.env",
                  capture=True).stdout


def write_env(host, content):
    ssh = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", host,
         "sudo -n tee /opt/virtualpytest/backend_host/src/.env > /dev/null"],
        stdin=subprocess.PIPE, text=True,
    )
    ssh.communicate(input=content)
    ssh.wait()


def apply(host, check_only=False):
    env_text = read_env(host)
    changes = []  # (idx, action) — "REPLACE" or "APPEND" or "PATCH_PATHS"
    patched_lines = []
    used_indices = set()
    n_replaced = 0
    n_appended = 0
    n_path_patches = 0

    # Pass 1: REPLACE existing device blocks with new 720p ones
    lines = env_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^DEVICE(\d+)_NAME=", line)
        if m:
            idx = int(m.group(1))
            if idx in REPLACE and idx not in used_indices:
                used_indices.add(idx)
                # Collect block until next live device entry
                block = [line]
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if re.match(r"^DEVICE\d+_", nxt) and not nxt.startswith(f"DEVICE{idx}_"):
                        break
                    if re.match(r"^#DEVICE\d+_", nxt):
                        break
                    block.append(nxt)
                    j += 1
                new_name, new_url = REPLACE[idx]
                new_block = [
                    f"DEVICE{idx}_NAME={new_name}",
                    f"DEVICE{idx}_MODEL=rtsp_video",
                    f"DEVICE{idx}_STREAM_TYPE=hls",
                    f"DEVICE{idx}_STREAM_LOOP=1",
                    f"DEVICE{idx}_VIDEO={new_url}",
                    f"DEVICE{idx}_VIDEO_FPS=5",
                    f"DEVICE{idx}_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture{idx}",
                    f"DEVICE{idx}_VIDEO_STREAM_PATH=/host/stream/capture{idx}",
                ]
                patched_lines.extend(new_block)
                n_replaced += 1
                changes.append((idx, "REPLACE", new_name))
                i = j
                continue
        patched_lines.append(line)
        i += 1

    # Pass 2: PATCH missing capture/stream path lines on already-present devices
    final_lines = []
    for line in patched_lines:
        m = re.match(r"^DEVICE(\d+)_(VIDEO|STREAM_TYPE)=", line)
        if m:
            idx = int(m.group(1))
            if idx in NEW:
                # Ensure capture path + stream path follow; if missing, insert
                pass
        final_lines.append(line)
    # Simpler: re-grep final lines and patch each NEW device with path lines
    final_text = "\n".join(final_lines) + "\n"
    existing_capture = set()
    existing_stream = set()
    existing_devices = set()
    for m in re.finditer(r"^DEVICE(\d+)_VIDEO_CAPTURE_PATH=", final_text, re.MULTILINE):
        existing_capture.add(int(m.group(1)))
    for m in re.finditer(r"^DEVICE(\d+)_VIDEO_STREAM_PATH=", final_text, re.MULTILINE):
        existing_stream.add(int(m.group(1)))
    for m in re.finditer(r"^DEVICE(\d+)_NAME=", final_text, re.MULTILINE):
        existing_devices.add(int(m.group(1)))

    path_lines = []
    for idx in NEW:
        if idx not in existing_devices:
            continue  # will be appended below
        if idx not in existing_capture:
            path_lines.append(f"DEVICE{idx}_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture{idx}")
            n_path_patches += 1
        if idx not in existing_stream:
            path_lines.append(f"DEVICE{idx}_VIDEO_STREAM_PATH=/host/stream/capture{idx}")
            n_path_patches += 1
    # Pass 2.5: PATCH missing MODEL/STREAM_TYPE/STREAM_LOOP for already-present devices
    # (these are required for the host to register the device with `av=rtsp_stream` —
    # without MODEL=rtsp_video the device's audio/video capability is null, and the
    # /device-control page filters it out — see BUG-0583 follow-up.)
    missing_av_block = []
    existing_model = set()
    existing_stream_type = set()
    existing_stream_loop = set()
    for m in re.finditer(r"^DEVICE(\d+)_MODEL=", final_text, re.MULTILINE):
        existing_model.add(int(m.group(1)))
    for m in re.finditer(r"^DEVICE(\d+)_STREAM_TYPE=", final_text, re.MULTILINE):
        existing_stream_type.add(int(m.group(1)))
    for m in re.finditer(r"^DEVICE(\d+)_STREAM_LOOP=", final_text, re.MULTILINE):
        existing_stream_loop.add(int(m.group(1)))
    for idx in NEW:
        if idx not in existing_devices:
            continue  # will be appended below with full block
        if idx not in existing_model:
            missing_av_block.append(f"DEVICE{idx}_MODEL=rtsp_video")
            n_path_patches += 1
        if idx not in existing_stream_type:
            missing_av_block.append(f"DEVICE{idx}_STREAM_TYPE=hls")
            n_path_patches += 1
        if idx not in existing_stream_loop:
            missing_av_block.append(f"DEVICE{idx}_STREAM_LOOP=1")
            n_path_patches += 1
    if missing_av_block:
        path_lines = missing_av_block + path_lines
    if path_lines:
        final_text = final_text.rstrip("\n") + "\n" + "\n".join(path_lines) + "\n"
        changes.append(("ALL_NEW", "PATCH_AV+PATHS", f"{n_path_patches} MODEL/STREAM_TYPE/STREAM_LOOP/capture/stream lines"))

    # Pass 3: APPEND new device blocks for indices not yet in the file
    append_lines = []
    for idx in sorted(NEW):
        if idx in existing_devices:
            continue
        name, url = NEW[idx]
        append_lines += [
            f"DEVICE{idx}_NAME={name}",
            f"DEVICE{idx}_MODEL=rtsp_video",
            f"DEVICE{idx}_STREAM_TYPE=hls",
            f"DEVICE{idx}_STREAM_LOOP=1",
            f"DEVICE{idx}_VIDEO={url}",
            f"DEVICE{idx}_VIDEO_FPS=5",
            f"DEVICE{idx}_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture{idx}",
            f"DEVICE{idx}_VIDEO_STREAM_PATH=/host/stream/capture{idx}",
        ]
        n_appended += 1
        changes.append((idx, "APPEND", name))
    if append_lines:
        final_text = final_text.rstrip("\n") + "\n" + "# TASK-95 max-streams: 12 new verified 720p FR streams\n" + "\n".join(append_lines) + "\n"

    # Pass 4: drop commented-out shadow lines for indices we just added live
    to_drop = {idx for idx in NEW}
    cleaned = []
    for line in final_text.splitlines():
        m = re.match(r"^#DEVICE(\d+)_(NAME|VIDEO|STREAM_TYPE|VIDEO_FPS|USER_AGENT|VIDEO_CAPTURE_PATH|VIDEO_STREAM_PATH)=", line)
        if m and int(m.group(1)) in to_drop:
            continue
        cleaned.append(line)
    final_text = "\n".join(cleaned) + "\n"

    print(f"[max-streams] plan for {host}:")
    for idx, action, label in changes:
        if idx == "ALL_NEW":
            print(f"  PATCH  {label}")
        else:
            print(f"  {action:<7} DEVICE{idx}  {label}")
    print(f"[max-streams] total: replaced={n_replaced} appended={n_appended} path-patches={n_path_patches}")

    if check_only:
        return

    write_env(host, final_text)
    print(f"[max-streams] {host}: .env updated; restart vpt-stream to apply")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    check = False
    if args[0] == "--check":
        check = True
        args = args[1:]
    if not args:
        print("Usage: apply_max_streams.py [--check] <ssh-host>")
        sys.exit(2)
    apply(args[0], check_only=check)