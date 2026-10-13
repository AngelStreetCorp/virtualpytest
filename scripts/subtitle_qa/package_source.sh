#!/usr/bin/env bash
# Package Tears of Steel (CC BY 3.0, Blender Foundation) into .mkv files with EN + DE subtitle tracks.
# usage: package_source.sh <tears_of_steel_720p.mov> <out_dir>
# Writes: tears_of_steel_subs.mkv (720p, video copy) and tears_of_steel_subs_480p.mkv (Pi 4 copy).
set -euo pipefail
SRC=${1:?source .mov}; OUT=${2:?out dir}
HERE=$(cd "$(dirname "$0")" && pwd)/assets
mkdir -p "$OUT"
MAPS=(-map 0:v:0 -map 0:a:0 -map 1:0 -map 2:0 -c:s srt
  -metadata:s:s:0 language=eng -metadata:s:s:0 title=English
  -metadata:s:s:1 language=deu -metadata:s:s:1 title=Deutsch
  -disposition:s:0 default -disposition:s:1 0)
ffmpeg -y -v error -i "$SRC" -i "$HERE/TOS-en.srt" -i "$HERE/TOS-de.srt" "${MAPS[@]}" \
  -c:v copy -c:a aac -b:a 128k "$OUT/tears_of_steel_subs.mkv"
ffmpeg -y -v error -i "$SRC" -i "$HERE/TOS-en.srt" -i "$HERE/TOS-de.srt" "${MAPS[@]}" \
  -vf scale=-2:480 -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 96k \
  "$OUT/tears_of_steel_subs_480p.mkv"
cp "$HERE/TOS-en.srt" "$HERE/TOS-de.srt" "$OUT/"
cat > "$OUT/ATTRIBUTION.txt" <<T
Tears of Steel - (CC) Blender Foundation | mango.blender.org
License: Creative Commons Attribution 3.0 (https://creativecommons.org/licenses/by/3.0/)
Source: https://download.blender.org/demo/movies/ToS/ (tears_of_steel_720p.mov, subtitles/TOS-en.srt, TOS-de.srt)
Changes: remuxed into Matroska with embedded subtitle tracks; the 480p file is re-encoded.
T
(cd "$OUT" && sha256sum *.mkv > SHA256SUMS)
