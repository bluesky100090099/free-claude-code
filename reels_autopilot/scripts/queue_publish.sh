#!/usr/bin/env bash
# Drip-feed publishing from the free "reels-queue" GitHub release.
# Each batch is stored as <id>.tar.gz (clips) + <id>.manifest.json (state).
# Every run publishes the next N clips of the oldest unfinished batch.
set -euo pipefail
cd "$(dirname "$0")/.."
NEXT="${PUBLISH_PER_RUN:-1}"
TAG="reels-queue"
work="$(mktemp -d)"

if ! gh release view "$TAG" >/dev/null 2>&1; then
  echo "No queue yet – run the workflow manually with a video first."; exit 0
fi
gh release download "$TAG" -p "*.manifest.json" -D "$work/m" --clobber || {
  echo "Queue is empty."; exit 0; }

for manifest in $(ls "$work"/m/*.manifest.json | sort); do
  id="$(basename "$manifest" .manifest.json)"
  pending="$(python -m reels pending "$manifest")"
  if [ "$pending" = "-1" ]; then
    echo "No platform is configured yet (add secrets) – keeping the queue."; exit 0
  fi
  if [ "$pending" = "0" ]; then
    echo "Batch $id is fully published – removing it from the queue."
    gh release delete-asset "$TAG" "$id.tar.gz" -y || true
    gh release delete-asset "$TAG" "$id.manifest.json" -y || true
    continue
  fi
  echo "Publishing next $NEXT clip(s) of batch $id"
  mkdir -p "$work/b/$id"
  gh release download "$TAG" -p "$id.tar.gz" -D "$work"
  tar -xzf "$work/$id.tar.gz" -C "$work/b/$id"
  cp "$manifest" "$work/b/$id/manifest.json"   # latest state wins
  status=0
  python -m reels publish "$work/b/$id" --next "$NEXT" || status=$?
  cp "$work/b/$id/manifest.json" "$work/$id.manifest.json"
  gh release upload "$TAG" "$work/$id.manifest.json" --clobber
  python -m reels status "$work/b/$id"
  exit "$status"
done
echo "Nothing left to publish – add a new video."
