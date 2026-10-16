#!/usr/bin/env bash
set -euo pipefail
# Run from repository root. Only temporary .scratch files are written.
base=.scratch/replay-measurements
mkdir -p "$base"
cp apps/edge/recorder.py "$base/recorder_final_snapshot.py"
sha256sum "$base/recorder_final_snapshot.py" "$base/measure.py"
ffmpeg -version > "$base/ffmpeg-version.txt"
ffprobe -version > "$base/ffprobe-version.txt"
python3 --version
uname -srmo
for d in 10 100 1000 10000; do
  ffmpeg -y -hide_banner -loglevel error -f lavfi -i 'color=c=gray:size=320x180:rate=30' -t "$d" -an -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -g 60 -threads 1 "$base/h264-${d}s.mkv"
  ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,time_base:format=duration,size -of json "$base/h264-${d}s.mkv"
done
for rep in 1 2 3; do
  for d in 10 100 1000 10000; do
    python3 "$base/measure.py" "$base/recorder_final_snapshot.py" "$base/h264-${d}s.mkv"
  done
done > "$base/results-final.jsonl"
