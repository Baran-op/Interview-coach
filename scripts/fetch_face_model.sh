#!/usr/bin/env bash
# Download the MediaPipe face landmarker model and copy the WASM runtime, so face tracking works offline.
# Run from anywhere after `cd frontend && npm install`. Output is git-ignored.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
models="$root/frontend/public/models"
wasm_src="$root/frontend/node_modules/@mediapipe/tasks-vision/wasm"
wasm_dst="$root/frontend/public/mediapipe"
url="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

[ -d "$wasm_src" ] || { echo "Missing $wasm_src: run 'cd frontend && npm install' first." >&2; exit 1; }
mkdir -p "$models" "$wasm_dst"
cp "$wasm_src"/* "$wasm_dst"/
if [ ! -s "$models/face_landmarker.task" ]; then
  curl -fL --retry 2 -o "$models/face_landmarker.task.part" "$url"
  mv "$models/face_landmarker.task.part" "$models/face_landmarker.task"
fi
echo "Face model ready in $models; WASM in $wasm_dst"
