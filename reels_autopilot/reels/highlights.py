"""Choose the best moments of a long video.

1. Gemini (free tier) watches the video – or reads the transcript for very long
   videos – and returns the most viral moments with a hook, title and hashtags.
2. If Gemini is unavailable (no key, quota, network) a local, free heuristic
   uses loudness peaks + scene cuts so the pipeline never stops.
"""

import contextlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from reels.config import Settings
from reels.media import audio_energy, scene_changes


@dataclass
class Clip:
    start: float
    end: float
    score: float = 0.0
    hook: str = ""
    title: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Normalisation – shared by every picker
# --------------------------------------------------------------------------- #
def normalize_clips(
    clips: list[Clip], video_duration: float, duration: float, count: int
) -> list[Clip]:
    """Force exact length, keep inside the video, drop overlaps, best first."""
    duration = min(duration, video_duration)
    fixed: list[Clip] = []
    for c in sorted(clips, key=lambda c: c.score, reverse=True):
        start = max(0.0, float(c.start))
        if start + duration > video_duration:
            start = max(0.0, video_duration - duration)
        start = round(start, 2)
        c.start, c.end = start, round(start + duration, 2)
        if any(c.start < o.end and o.start < c.end for o in fixed):
            continue
        fixed.append(c)
        if len(fixed) == count:
            break
    return sorted(fixed, key=lambda c: c.start)


def clean_hashtags(tags: list[str] | str) -> list[str]:
    if isinstance(tags, str):
        tags = re.split(r"[\s,]+", tags)
    out: list[str] = []
    for t in tags:
        t = re.sub(r"[^\w]", "", str(t).lstrip("#"), flags=re.UNICODE)
        if t and f"#{t}" not in out:
            out.append(f"#{t}")
    return out[:8]


def parse_timestamp(value: str | float | int) -> float:
    """Accept 83, "83.5", "1:23", "01:01:23.5"."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).strip().split(":")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


# --------------------------------------------------------------------------- #
# Free local fallback
# --------------------------------------------------------------------------- #
def pick_by_energy(
    path: str | Path, video_duration: float, count: int, duration: float
) -> list[Clip]:
    window = 0.5
    energy = audio_energy(path, window)
    n_win = max(1, int(round(duration / window)))
    n_slots = max(1, int(video_duration / window))
    if energy.size == 0:
        energy = np.ones(n_slots)
    energy = (
        energy[:n_slots]
        if energy.size >= n_slots
        else np.pad(energy, (0, n_slots - energy.size))
    )
    # Loudness + how much it changes (laughs, punchlines, music drops)
    e = energy / (energy.max() or 1)
    variation = np.abs(np.diff(e, prepend=e[:1]))
    signal = e + 1.5 * variation
    cuts = np.zeros(n_slots)
    for t in scene_changes(path):
        idx = int(t / window)
        if 0 <= idx < n_slots:
            cuts[idx] += 0.15  # a little motion is good, too much is chaos
    signal = signal + cuts
    if n_slots <= n_win:
        return [Clip(0.0, video_duration, 1.0, reason="video shorter than clip")]
    kernel = np.ones(n_win) / n_win
    scores = np.convolve(signal, kernel, mode="valid")  # one score per start slot
    # Skip the first/last 3% (intros, outros, "subscribe" endings)
    margin = int(len(scores) * 0.03) if len(scores) >= 50 else 0
    picked: list[Clip] = []
    for i in np.argsort(scores)[::-1]:  # greedy non-maximum suppression
        if not margin <= i < len(scores) - margin:
            continue
        start = float(i * window)
        if any(start < c.end and c.start < start + duration for c in picked):
            continue
        picked.append(
            Clip(start, start + duration, float(scores[i]), reason="audio/scene peak")
        )
        if len(picked) == count:
            break
    return normalize_clips(picked, video_duration, duration, count)


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #
PROMPT = """You are a world-class short-form video editor (TikTok, Reels, Shorts).
{source}
Pick the {count} BEST moments that work as standalone {duration:.0f}-second
vertical clips. Prefer: a strong hook in the first 2 seconds, a complete idea or
punchline, emotion, surprise, useful tips, quotable lines. Avoid intros, outros,
sponsor reads and moments that need earlier context. Clips must not overlap.

Write all text in language code "{language}" (natural, native, not translated).
Return ONLY a JSON array, best first, each item:
{{"start": <seconds from video start, number>,
  "score": <1-10 virality>,
  "hook": "<max 6 words shown on screen in the first 3 seconds, no emojis>",
  "title": "<max 70 chars, curiosity driven>",
  "caption": "<1-2 engaging sentences + a call to action>",
  "hashtags": ["5-8 relevant hashtags, mix broad and niche"],
  "reason": "<why this moment works, short>"}}
The video is {total:.0f} seconds long, so start must be <= {max_start:.0f}."""


def _gemini_client(settings: Settings):
    from google import genai  # lazy: optional dependency

    return genai.Client(api_key=settings.gemini_api_key)


def _parse_gemini_json(text: str) -> list[dict]:
    text = text.strip()
    match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    data = json.loads(match.group(0) if match else text)
    if isinstance(data, dict):
        data = data.get("clips") or data.get("moments") or [data]
    return [d for d in data if isinstance(d, dict) and "start" in d]


def pick_with_gemini(
    path: str | Path,
    video_duration: float,
    count: int,
    duration: float,
    settings: Settings,
    transcript: str | None = None,
    log=print,
) -> list[Clip]:
    from google.genai import types

    client = _gemini_client(settings)
    ask = count + 3  # ask for extras so overlaps can be dropped
    fmt = {
        "count": ask,
        "duration": duration,
        "language": settings.language,
        "total": video_duration,
        "max_start": max(0, video_duration - duration),
    }
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.4,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
    )
    # The pipeline passes a transcript only for long videos, where text is far
    # cheaper than video tokens (free tier ≈ 250k tokens/minute).
    use_transcript = bool(transcript)
    uploaded = None
    try:
        if use_transcript:
            log("  Gemini: analysing transcript (long video)…")
            prompt = PROMPT.format(
                source=f"Here is a timestamped transcript:\n{transcript}", **fmt
            )
            contents: list = [prompt]
        else:
            log("  Gemini: uploading video…")
            uploaded = client.files.upload(file=str(path))
            while uploaded.state and uploaded.state.name == "PROCESSING":
                time.sleep(3)
                uploaded = client.files.get(name=uploaded.name)
            if uploaded.state and uploaded.state.name == "FAILED":
                raise RuntimeError("Gemini could not process the video")
            source = "Watch this video (visuals AND audio)."
            contents = [uploaded, PROMPT.format(source=source, **fmt)]
            log("  Gemini: picking the best moments…")
        response = None
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=settings.gemini_model, contents=contents, config=config
                )
                break
            except Exception as exc:  # free tier: 429 / 503 – back off
                msg = str(exc)
                if attempt < 3 and ("429" in msg or "503" in msg or "UNAVAIL" in msg):
                    wait = 20 * (attempt + 1)
                    log(f"  Gemini busy ({msg[:60]}…) – retrying in {wait}s")
                    time.sleep(wait)
                    continue
                raise
        assert response is not None
        items = _parse_gemini_json(response.text or "[]")
    finally:
        if uploaded is not None:
            with contextlib.suppress(Exception):
                client.files.delete(name=uploaded.name)
    clips = [
        Clip(
            start=parse_timestamp(it.get("start", 0)),
            end=0,
            score=float(it.get("score", 5)),
            hook=str(it.get("hook", "")).strip(),
            title=str(it.get("title", "")).strip(),
            caption=str(it.get("caption", "")).strip(),
            hashtags=clean_hashtags(it.get("hashtags", [])),
            reason=str(it.get("reason", "")).strip(),
        )
        for it in items
    ]
    return normalize_clips(clips, video_duration, duration, count)


def pick_highlights(
    path: str | Path,
    video_duration: float,
    count: int,
    duration: float,
    settings: Settings,
    picker: str = "auto",
    transcript: str | None = None,
    log=print,
) -> list[Clip]:
    if picker in ("auto", "gemini") and settings.gemini_api_key:
        try:
            clips = pick_with_gemini(
                path, video_duration, count, duration, settings, transcript, log
            )
            if clips:
                if len(clips) < count:
                    extra = pick_by_energy(path, video_duration, count * 3, duration)
                    for c in extra:  # Gemini picks always rank first
                        c.score -= 100
                    clips = normalize_clips(
                        clips + extra, video_duration, duration, count
                    )
                return clips
            log("  Gemini returned no clips – using local picker")
        except Exception as exc:
            if picker == "gemini":
                raise
            log(f"  Gemini unavailable ({str(exc)[:120]}) – using local picker")
    elif picker == "gemini":
        raise RuntimeError("GEMINI_API_KEY is not set")
    return pick_by_energy(path, video_duration, count, duration)


COPY_PROMPT = """You write viral short-video copy. For each numbered clip transcript
below, write copy in language code "{language}".
Return ONLY a JSON array with one object per clip, same order:
{{"hook": "<max 6 words on-screen, no emojis>", "title": "<max 70 chars>",
  "caption": "<1-2 sentences + call to action>", "hashtags": ["5-8 hashtags"]}}

{clips}"""


def write_copy(clips: list[Clip], texts: list[str], settings: Settings, log=print):
    """Fill hook/title/caption for clips that have none (Gemini or simple text)."""
    todo = [i for i, c in enumerate(clips) if not c.title]
    if not todo:
        return
    if settings.gemini_api_key:
        try:
            from google.genai import types

            listing = "\n\n".join(
                f"{n + 1}. {texts[i] or '(no speech)'}" for n, i in enumerate(todo)
            )
            resp = _gemini_client(settings).models.generate_content(
                model=settings.gemini_model,
                contents=COPY_PROMPT.format(language=settings.language, clips=listing),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.7
                ),
            )
            data = json.loads(resp.text or "[]")
            for i, item in zip(todo, data, strict=False):
                c = clips[i]
                c.hook = str(item.get("hook", "")).strip()
                c.title = str(item.get("title", "")).strip()
                c.caption = str(item.get("caption", "")).strip()
                c.hashtags = clean_hashtags(item.get("hashtags", []))
            todo = [i for i in todo if not clips[i].title]
        except Exception as exc:
            log(f"  Gemini copywriting skipped ({str(exc)[:100]})")
    for i in todo:
        words = texts[i].split()
        clips[i].title = " ".join(words[:10]) or f"Clip {i + 1}"
        clips[i].hashtags = clips[i].hashtags or ["#shorts", "#reels", "#fyp"]
