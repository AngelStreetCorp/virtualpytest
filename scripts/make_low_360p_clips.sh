#!/bin/bash
# 48 distinct 640x360 clips (60s) cut from 4 open movies -> /var/lib/vpt-movies
set -u
SRC=/var/tmp/vpt-src; OUT=/var/lib/vpt-movies; mkdir -p $SRC $OUT
dl(){ [ -s "$SRC/$1" ] || curl -fL --retry 3 -m 900 -o "$SRC/$1" "$2" || rm -f "$SRC/$1"; }
dl bbb.mp4  https://archive.org/download/BigBuckBunny_328/BigBuckBunny_512kb.mp4 &
dl sintel.mp4 https://archive.org/download/Sintel/sintel-2048-surround_512kb.mp4 &
dl ed.mp4   https://archive.org/download/ElephantsDream/ed_1024_512kb.mp4 &
dl tos.mp4  https://archive.org/download/Tears-of-Steel/tears_of_steel_1080p.mp4 &
wait
n=0
for s in bbb:bunny sintel:sintel ed:elephants tos:steel; do
  f=${s%%:*}; name=${s##*:}; src=$SRC/$f.mp4; [ -s $src ] || { echo "MISSING $f"; continue; }
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $src | cut -d. -f1)
  step=$(( (dur-60)/11 ))
  for i in $(seq 0 11); do
    n=$((n+1)); o=$(printf "%s/%02d_%s_%02d.mp4" $OUT $n $name $((i+1)))
    [ -s $o ] && continue
    ffmpeg -nostdin -v error -y -ss $((i*step)) -t 60 -i $src -vf scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:-1:-1 -r 25 -c:v libx264 -preset veryfast -b:v 350k -maxrate 450k -bufsize 900k -pix_fmt yuv420p -g 10 -keyint_min 10 -sc_threshold 0 -bf 0 -profile:v baseline -an -movflags +faststart ${o%.mp4}.new.mp4 && mv ${o%.mp4}.new.mp4 $o && echo "ok $o"
  done
done
echo DONE $(ls $OUT/*.mp4 | wc -l)
