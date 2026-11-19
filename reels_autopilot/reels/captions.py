"""Word-level captions (faster-whisper) rendered as animated ASS subtitles."""

from dataclasses import dataclass
from pathlib import Path

from reels.config import Settings


@dataclass
class Word:
    start: float
    end: float
    text: str


_MODEL_CACHE: dict = {}


def _load_model(settings: Settings):
    from faster_whisper import WhisperModel  # optional dependency

    device = settings.whisper_device
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    key = (settings.whisper_model, device)
    if key not in _MODEL_CACHE:
        compute = "float16" if device == "cuda" else "int8"
        _MODEL_CACHE[key] = WhisperModel(
            settings.whisper_model, device=device, compute_type=compute
        )
    return _MODEL_CACHE[key]


def transcribe(
    path: str | Path,
    settings: Settings,
    offset: float = 0.0,
    duration: float | None = None,
    log=print,
) -> list[Word]:
    """Transcribe `path` (optionally only [offset, offset+duration])."""
    if _MODEL_CACHE.get("failed"):
        return []
    try:
        model = _load_model(settings)
    except ImportError:
        log("  faster-whisper not installed – clips will have no captions")
        _MODEL_CACHE["failed"] = True
        return []
    except Exception as exc:  # e.g. model download blocked
        log(f"  Whisper model unavailable ({str(exc)[:80]}) – no captions")
        _MODEL_CACHE["failed"] = True
        return []
    audio_input: str | object = str(path)
    if offset or duration:
        import subprocess

        import numpy as np

        cmd = ["ffmpeg", "-v", "error", "-ss", f"{offset:.3f}", "-i", str(path)]
        if duration:
            cmd += ["-t", f"{duration:.3f}"]
        cmd += ["-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
        raw = subprocess.run(cmd, capture_output=True, check=False).stdout
        if not raw:
            return []
        audio_input = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    lang = settings.language.split("-")[0] or None
    words: list[Word] = []
    try:
        segments, _info = model.transcribe(
            audio_input, language=lang, word_timestamps=True, vad_filter=True
        )
        for seg in segments:
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    words.append(Word(w.start + offset, w.end + offset, text))
    except Exception as exc:
        log(f"  Transcription failed ({str(exc)[:80]}) – no captions")
    return words


def transcript_text(words: list[Word], every: float = 8.0) -> str:
    """Compact '[mm:ss] text' lines for the LLM."""
    lines, current, t0 = [], [], None
    for w in words:
        if t0 is None:
            t0 = w.start
        current.append(w.text)
        if w.end - t0 >= every or w.text[-1:] in ".?!؟":
            lines.append(f"[{int(t0 // 60):02d}:{t0 % 60:04.1f}] {' '.join(current)}")
            current, t0 = [], None
    if current and t0 is not None:
        lines.append(f"[{int(t0 // 60):02d}:{t0 % 60:04.1f}] {' '.join(current)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# ASS subtitle generation
# --------------------------------------------------------------------------- #
def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text: str) -> str:
    return (
        text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")
    )


def group_words(
    words: list[Word], max_words: int = 3, max_span: float = 1.8, gap: float = 0.6
) -> list[list[Word]]:
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur and (
            len(cur) >= max_words
            or w.end - cur[0].start > max_span
            or w.start - cur[-1].end > gap
            or cur[-1].text[-1:] in ".?!،,؟"
        ):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(
    words: list[Word],
    clip_start: float,
    clip_end: float,
    settings: Settings,
    hook: str = "",
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Return an .ass document with word-by-word highlighted captions + hook."""
    font = settings.font
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,\
100,100,0,0,1,7,3,2,90,90,560,-1
Style: Hook,{font},74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00101010,-1,0,0,0,\
100,100,0,0,3,18,0,8,80,80,300,-1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    duration = clip_end - clip_start
    if hook.strip():
        events.append(
            f"Dialogue: 1,{_ts(0)},{_ts(min(3.0, duration))},Hook,,0,0,0,,"
            f"{{\\fad(120,250)}}{_esc(hook.strip())}"
        )
    local = [
        Word(w.start - clip_start, w.end - clip_start, w.text)
        for w in words
        if w.end > clip_start and w.start < clip_end
    ]
    highlight = "{\\c&H0000E5FF&\\fscx112\\fscy112}"  # yellow, slightly bigger
    reset = "{\\c&H00FFFFFF&\\fscx100\\fscy100}"
    for g in group_words(local):
        for i, w in enumerate(g):
            start = max(0.0, w.start)
            end = g[i + 1].start if i + 1 < len(g) else max(w.end, start + 0.25)
            end = min(end, duration)
            if end <= start:
                continue
            parts = []
            for j, other in enumerate(g):
                t = _esc(other.text)
                parts.append(f"{highlight}{t}{reset}" if j == i else t)
            events.append(
                f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{' '.join(parts)}"
            )
    return header + "\n".join(events) + "\n"
