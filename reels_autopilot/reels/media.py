"""Thin wrappers around ffprobe / ffmpeg."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class MediaError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise MediaError(f"{tool} not found – install ffmpeg first")


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    has_audio: bool
    fps: float


def probe(path: str | Path) -> VideoInfo:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed for {path}: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise MediaError(f"No video stream in {path}")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    width, height = int(video["width"]), int(video["height"])
    # Respect rotation metadata from phones (portrait videos stored as landscape).
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = abs(int(sd["rotation"]))
    if rotation in (90, 270):
        width, height = height, width
    num, _, den = video.get("avg_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    duration = float(data["format"].get("duration") or video.get("duration") or 0)
    return VideoInfo(duration, width, height, has_audio, fps or 30.0)


def audio_energy(path: str | Path, window: float = 0.5) -> np.ndarray:
    """RMS loudness per `window` seconds (empty array when there is no audio)."""
    sr = 16000
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sr),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return np.zeros(0)
    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768
    hop = int(sr * window)
    n = len(samples) // hop
    if n == 0:
        return np.zeros(0)
    frames = samples[: n * hop].reshape(n, hop)
    return np.sqrt((frames**2).mean(axis=1))


def scene_changes(path: str | Path, threshold: float = 0.3) -> list[float]:
    """Timestamps (s) of hard cuts – used to give the fallback picker 'motion'."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(path),
            "-an",
            "-vf",
            f"scale=160:-2,select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    times = []
    for line in proc.stderr.splitlines():
        if "showinfo" in line and "pts_time:" in line:
            try:
                times.append(float(line.split("pts_time:")[1].split()[0]))
            except (IndexError, ValueError):
                continue
    return times
