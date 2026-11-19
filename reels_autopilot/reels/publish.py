"""Publish clips from a batch, remembering what was already posted."""

import time
from pathlib import Path

from reels.pipeline import load_manifest, save_manifest
from reels.publishers import PUBLISHERS, Post, PublishResult

MAX_ATTEMPTS = 3  # a clip that keeps failing on a platform must not block the queue


def needs_publish(clip: dict, platform: str) -> bool:
    state = clip["published"].get(platform, {})
    return not state.get("ok") and state.get("attempts", 0) < MAX_ATTEMPTS


def publish_batch(
    target: str | Path,
    platforms: list[str],
    next_n: int = 0,
    dry_run: bool = False,
    log=print,
) -> list[PublishResult]:
    """Publish pending clips. next_n=0 → all pending, else only the next N clips.

    Running this on a schedule (e.g. daily with next_n=1) drip-feeds a batch.
    """
    batch, manifest = load_manifest(target)
    active = []
    for name in platforms:
        pub = PUBLISHERS[name]()
        if pub.is_configured():
            active.append(pub)
        else:
            log(
                f"• {name}: not configured ({', '.join(pub.missing())}) – "
                f"post manually using POST_KIT.md"
            )
    results: list[PublishResult] = []
    if not active:
        return results
    done_clips = 0
    for clip in manifest["clips"]:
        pending = [p for p in active if not clip["published"].get(p.name, {}).get("ok")]
        if not pending:
            continue
        if next_n and done_clips >= next_n:
            break
        done_clips += 1
        post = Post(
            video=batch / clip["file"],
            title=clip["title"],
            caption=clip["caption"],
            hashtags=clip["hashtags"],
            description=clip.get("description", ""),
            tags=clip.get("tags", []),
        )
        for pub in pending:
            if dry_run:
                log(f"[dry-run] {pub.name}: would publish {clip['file']}")
                continue
            log(f"→ {pub.name}: uploading {clip['file']}…")
            try:
                res = pub.publish(post)
            except Exception as exc:
                res = PublishResult(pub.name, False, error=str(exc)[:500])
            results.append(res)
            attempts = clip["published"].get(pub.name, {}).get("attempts", 0) + 1
            clip["published"][pub.name] = {
                "attempts": attempts,
                "ok": res.ok,
                "id": res.id,
                "url": res.url,
                "error": res.error,
                "note": res.note,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            save_manifest(batch, manifest)
            if res.ok:
                log(f"  ✓ {pub.name}: {res.url or res.id} {res.note}".rstrip())
            else:
                log(f"  ✗ {pub.name}: {res.error}")
    if done_clips == 0:
        log("Nothing pending – every clip is already published.")
    return results
