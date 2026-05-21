#!/usr/bin/env bash
# Benchmark encoder params for the all-keyframe pass.
# Compares file size + PSNR for different (preset, CRF) combos against a
# ground-truth slice (= current pipeline output).
#
# Args:
#   $1  source video (will slice ~1000 frames out of it)
#   $2  scratch dir (will be wiped)
set -uo pipefail

SRC="${1:-$HOME/.cache/huggingface/lerobot/Xense/earbud_case_insertion_teleop_0515/videos/observation.images.head/chunk-000/file-000.mp4}"
TMP="${2:-/tmp/bench_encoder}"

rm -rf "$TMP"
mkdir -p "$TMP"

echo "Source: $SRC"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -of default=nokey=1:noprint_wrappers=1 "$SRC"
echo

# Step 1: slice out ~33 sec (1000 frames @ 30fps) at the start.
REF="$TMP/ref.mp4"
ffmpeg -hide_banner -loglevel error -y \
  -i "$SRC" -t 33.34 \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -an "$REF"

REF_FRAMES=$(ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=nb_read_frames -of default=nokey=1:noprint_wrappers=1 "$REF")
WIDTH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=nokey=1:noprint_wrappers=1 "$REF")
HEIGHT=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=nokey=1:noprint_wrappers=1 "$REF")
FPS=30
echo "Reference slice: $REF_FRAMES frames, ${WIDTH}x${HEIGHT}, ${FPS}fps"
echo

# Step 2: decode reference to rawvideo (matches the in-memory frames the
# converter feeds to ffmpeg in __init__.py).
RAW="$TMP/ref.raw"
ffmpeg -hide_banner -loglevel error -y -i "$REF" -f rawvideo -pix_fmt bgr24 "$RAW"

# Step 3: sweep params.
printf "%-10s %-4s %12s %14s %12s %10s\n" "preset" "CRF" "size_bytes" "size_MB" "encode_s" "PSNR_dB"
printf "%-10s %-4s %12s %14s %12s %10s\n" "------" "---" "----------" "-------" "--------" "-------"

for PRESET in ultrafast veryfast fast; do
  for CRF in 23 28 30 32; do
    OUT="$TMP/${PRESET}_crf${CRF}.h264"

    # Encode with -g 1 (every frame keyframe), no B frames, dump_extra so each
    # frame carries its own SPS — mirrors the actual converter behaviour.
    T0=$(date +%s.%N)
    ffmpeg -hide_banner -loglevel error -y \
      -f rawvideo -pix_fmt bgr24 -s "${WIDTH}x${HEIGHT}" -r "$FPS" -i "$RAW" \
      -c:v libx264 -preset "$PRESET" -crf "$CRF" \
      -g 1 -keyint_min 1 -bf 0 \
      -flags +global_header -bsf:v dump_extra \
      -tune zerolatency -pix_fmt yuv420p \
      -f h264 "$OUT"
    T1=$(date +%s.%N)
    ENC_TIME=$(echo "$T1 - $T0" | bc)

    SIZE=$(stat -c %s "$OUT")
    SIZE_MB=$(echo "scale=2; $SIZE / 1024 / 1024" | bc)

    # Decode output and compute PSNR vs reference rawvideo.
    PSNR_RAW=$(ffmpeg -hide_banner \
      -f rawvideo -pix_fmt bgr24 -s "${WIDTH}x${HEIGHT}" -r "$FPS" -i "$RAW" \
      -f h264 -i "$OUT" \
      -lavfi "psnr" -f null - 2>&1 | tail -5)
    PSNR=$(echo "$PSNR_RAW" | grep -oE "average:[0-9.]+" | head -1 | cut -d: -f2)
    [ -z "$PSNR" ] && PSNR="?"

    printf "%-10s %-4s %12d %14s %11.2fs %10s\n" "$PRESET" "$CRF" "$SIZE" "$SIZE_MB MB" "$ENC_TIME" "$PSNR"
  done
done

echo
echo "Baseline (current pipeline, ultrafast + default CRF 23):"
echo "  See first row of the table above."
