#!/usr/bin/env bash
# Add a finished batch folder to the "reels-queue" GitHub release.
set -euo pipefail
batch="${1:?usage: queue_add.sh <batch-dir>}"
batch="${batch%/}"
TAG="reels-queue"
id="$(basename "$batch")"
tmp="$(mktemp -d)"
if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --prerelease --title "Reels queue" \
    --notes "Clips waiting to be published by the Reels Autopilot workflow."
fi
tar -czf "$tmp/$id.tar.gz" -C "$batch" --exclude manifest.json .
cp "$batch/manifest.json" "$tmp/$id.manifest.json"
gh release upload "$TAG" "$tmp/$id.tar.gz" "$tmp/$id.manifest.json" --clobber
echo "Queued $id"
