#!/bin/bash
# frame_source.sh — helpers for the `imagefile` capture source (sourced by
# run_ffmpeg.sh and emulator_screencap.sh).
#
# An imagefile source is a frame FILE that another process keeps rewriting:
# emulator_screencap.sh publishes a phone/emulator screenshot every 0.2 s and
# run_ffmpeg.sh's `imagefile` branch reads that file as a live frame.
#
# The file can end up in a state no decoder accepts. The writer's transfer died
# half way (the phone dropped off USB in the middle of a screencap) and the
# partial file was published over the last good frame. The capture agent then has
# no source at all: ffmpeg cannot decode it, so the device writes no thumbnail
# and no playlist, and the platform reports a 404 for a device it still lists —
# with nothing on the host saying why.
#
# These helpers tell the three states apart, so the writer never publishes a
# broken frame and the reader can name the fault instead of guessing:
#   frame_is_complete <file>    0 when the file is a whole, decodable frame
#   frame_source_state <file>   missing | corrupt | ok
#
# Source this file with: source frame_source.sh  (or . frame_source.sh)
# Pure shell + coreutils: no ImageMagick and no python (a capture host does not
# necessarily have PIL — see is_black() in emulator_screencap.sh).

# A whole PNG ends with the IEND chunk: length 0, "IEND", CRC ae426082.
# A whole JPEG ends with the EOI marker: ffd9.
# A file that was cut short has neither: its tail is still compressed data.
frame_is_complete() {
  local file="$1" head_hex tail_hex
  [ -n "$file" ] && [ -s "$file" ] || return 1
  head_hex=$(head -c 8 "$file" 2>/dev/null | od -An -tx1 2>/dev/null | tr -d ' \n')
  case "$head_hex" in
    89504e470d0a1a0a)   # PNG signature
      tail_hex=$(tail -c 12 "$file" 2>/dev/null | od -An -tx1 2>/dev/null | tr -d ' \n')
      [ "$tail_hex" = "0000000049454e44ae426082" ]
      ;;
    ffd8*)             # JPEG SOI
      tail_hex=$(tail -c 2 "$file" 2>/dev/null | od -An -tx1 2>/dev/null | tr -d ' \n')
      [ "$tail_hex" = "ffd9" ]
      ;;
    *)
      return 1
      ;;
  esac
}

# missing — the writer has not published a frame yet (the boot race: the grabber
#           may start before the frame loop's first write)
# corrupt — a frame file is there, but no decoder can read it
# ok      — a whole frame
frame_source_state() {
  local file="$1"
  if [ ! -e "$file" ]; then
    echo "missing"
  elif frame_is_complete "$file"; then
    echo "ok"
  else
    echo "corrupt"
  fi
  return 0
}
