"""make: long video -> N vertical clips + manifest.json + POST_KIT.md"""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from reels.captions import Word, build_ass, transcribe, transcript_text
from reels.config import Settings
from reels.highlights import pick_highlights, write_copy
from reels.media import MediaError, probe, require_ffmpeg
from reels.render import render_clip

LONG_VIDEO = 35 * 60  # above this, Gemini reads the transcript, not the video


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-").lower()
    return s[:50] or "video"


def fetch_input(source: str, workdir: Path, log=print) -> Path:
    """Local path, or a URL (Drive/Dropbox/direct/YouTube…) via yt-dlp."""
    p = Path(source).expanduser()
    if p.exists():
        return p
    if not re.match(r"^https?://", source):
        raise MediaError(f"Input not found: {source}")
    workdir.mkdir(parents=True, exist_ok=True)
    if shutil.which("yt-dlp") is None:
        raise MediaError("yt-dlp is needed for URLs: pip install yt-dlp")
    log("Downloading input…")
    out_tpl = str(workdir / "%(title).60B [%(id)s].%(ext)s")
    proc = subprocess.run(
        [
            "yt-dlp",
            "-f",
            "bv*[height<=1080]+ba/b[height<=1080]/b",
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "-o",
            out_tpl,
            "--print",
            "after_move:filepath",
            source,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise MediaError(f"Download failed: {proc.stderr.strip()[-500:]}")
    return Path(proc.stdout.strip().splitlines()[-1])


def make(
    source: str,
    out_root: str | Path = "out",
    count: int = 5,
    duration: float = 15.0,
    crop: str = "smart",
    picker: str = "auto",
    captions: bool = True,
    settings: Settings | None = None,
    log=print,
    zoom: float = 0.06,
) -> Path:
    require_ffmpeg()
    settings = settings or Settings()
    out_root = Path(out_root)
    src = fetch_input(source, out_root / "_downloads", log)
    info = probe(src)
    log(
        f"Input: {src.name} – {info.duration / 60:.1f} min, "
        f"{info.width}x{info.height}, audio={'yes' if info.has_audio else 'no'}"
    )
    if info.duration < 3:
        raise MediaError("Video is too short")

    batch = out_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(src.stem)}"
    batch.mkdir(parents=True, exist_ok=True)

    full_words: list[Word] | None = None
    transcript = None
    if (
        captions
        and info.has_audio
        and info.duration > LONG_VIDEO
        and settings.gemini_api_key
    ):
        log("Long video: transcribing everything first (Gemini will read text)…")
        full_words = transcribe(src, settings, log=log)
        transcript = transcript_text(full_words) or None

    log(f"Finding the best {count} moments…")
    clips = pick_highlights(
        src, info.duration, count, duration, settings, picker, transcript, log
    )
    log(f"Selected {len(clips)} clip(s).")

    words_per_clip: list[list[Word]] = []
    for c in clips:
        if not captions or not info.has_audio:
            words_per_clip.append([])
        elif full_words is not None:
            words_per_clip.append(
                [w for w in full_words if w.end > c.start and w.start < c.end]
            )
        else:
            words_per_clip.append(
                transcribe(src, settings, c.start, c.duration, log=log)
            )
    texts = [" ".join(w.text for w in ws) for ws in words_per_clip]
    write_copy(clips, texts, settings, log)

    manifest_clips = []
    for i, (clip, words) in enumerate(zip(clips, words_per_clip, strict=True), 1):
        name = f"clip_{i:02d}.mp4"
        ass_path = None
        if captions and (words or clip.hook):
            ass_path = batch / f"clip_{i:02d}.ass"
            ass_path.write_text(
                build_ass(words, clip.start, clip.end, settings, clip.hook),
                encoding="utf-8",
            )
        log(f"  [{i}/{len(clips)}] {clip.start:.1f}s → {clip.end:.1f}s  {clip.title}")
        meta = render_clip(
            src,
            info,
            clip,
            batch / name,
            crop,
            ass_path,
            settings.fonts_dir,
            log,
            zoom,
        )
        manifest_clips.append(
            {
                "file": name,
                **clip.to_dict(),
                **meta,
                "transcript": texts[i - 1],
                "published": {},
            }
        )

    manifest = {
        "source": str(src),
        "source_url": source if re.match(r"^https?://", source) else "",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "language": settings.language,
        "duration": duration,
        "clips": manifest_clips,
    }
    save_manifest(batch, manifest)
    write_post_kit(batch, manifest)
    log(f"Done → {batch}")
    return batch


def save_manifest(batch: Path, manifest: dict) -> None:
    tmp = batch / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(batch / "manifest.json")


def load_manifest(target: str | Path) -> tuple[Path, dict]:
    p = Path(target)
    file = p if p.is_file() else p / "manifest.json"
    return file.parent, json.loads(file.read_text("utf-8"))


def write_post_kit(batch: Path, manifest: dict) -> None:
    """Ready-to-paste text for manual posting (works with zero API setup)."""
    from reels.publishers.base import Post

    lines = ["# Post kit – copy & paste\n"]
    for c in manifest["clips"]:
        post = Post(
            batch / c["file"],
            c["title"],
            c["caption"],
            c["hashtags"],
            c.get("description", ""),
            c.get("tags", []),
        )
        yt = post.for_platform("youtube")
        lines += [
            f"## {c['file']}  ({c['start']:.0f}s–{c['end']:.0f}s)",
            f"**Hook on screen:** {c['hook']}\n",
            "### YouTube Shorts",
            f"Title:\n```\n{yt['title']}\n```",
            f"Description:\n```\n{yt['description']}\n```",
            f"Tags:\n```\n{', '.join(yt['tags'])}\n```",
            "### Instagram",
            f"```\n{post.for_platform('instagram')['caption']}\n```",
            "### TikTok",
            f"```\n{post.for_platform('tiktok')['caption']}\n```",
            "### Facebook",
            f"```\n{post.for_platform('facebook')['description']}\n```\n",
        ]
    (batch / "POST_KIT.md").write_text("\n".join(lines), "utf-8")
