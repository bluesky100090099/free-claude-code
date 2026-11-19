"""Render one 9:16 1080x1920 clip with ffmpeg."""

import subprocess
from pathlib import Path

from reels.highlights import Clip
from reels.media import MediaError, VideoInfo

W, H = 1080, 1920


def face_center_x(path: str | Path, start: float, duration: float) -> float | None:
    """Median horizontal face position (0..1) across the clip, or None."""
    try:
        return _face_center_x(path, start, duration)
    except Exception:  # face detection is a nice-to-have, never fatal
        return None


def _face_center_x(path: str | Path, start: float, duration: float) -> float | None:
    try:
        import cv2
    except ImportError:
        return None
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 dropped Haar cascades
        return None
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    centers: list[float] = []
    weights: list[float] = []
    try:
        for k in range(12):
            t = start + duration * (k + 0.5) / 12
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            scale = 480 / max(w, 1)
            small = cv2.resize(frame, (480, max(1, int(h * scale))))
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))
            for x, _y, fw, fh in faces:
                centers.append((x + fw / 2) / small.shape[1])
                weights.append(float(fw * fh))
    finally:
        cap.release()
    if len(centers) < 3:  # too few detections = probably false positives
        return None
    order = sorted(range(len(centers)), key=lambda i: centers[i])
    total, acc = sum(weights), 0.0
    for i in order:  # weighted median: biggest (closest) face wins
        acc += weights[i]
        if acc >= total / 2:
            return centers[i]
    return centers[order[-1]]


def _filter_escape(path: Path) -> str:
    s = str(path.resolve())
    for ch in ("\\", ":", "'", ",", "[", "]", ";"):
        s = s.replace(ch, "\\" + ch)
    return s


def build_video_filter(
    info: VideoInfo,
    mode: str,
    center_x: float | None,
    ass_path: Path | None,
    fonts_dir: str = "",
) -> str:
    aspect = info.width / max(info.height, 1)
    if aspect <= 9 / 16 + 0.01:  # already vertical
        chain = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1"
        )
    elif mode == "blur" or (mode == "smart" and center_x is None):
        # Whole frame visible on top of a blurred, zoomed copy of itself.
        chain = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=24:2,eq=brightness=-0.08[bgb];"
            f"[fg]scale={W}:-2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    else:
        cx = 0.5 if center_x is None else center_x
        crop_w = int(info.height * 9 / 16) // 2 * 2
        x = int(min(max(cx * info.width - crop_w / 2, 0), info.width - crop_w))
        chain = (
            f"[0:v]crop={crop_w}:{info.height}:{x}:0,scale={W}:{H}:flags=lanczos,"
            f"setsar=1"
        )
    if ass_path is not None:
        extra = f":fontsdir={_filter_escape(Path(fonts_dir))}" if fonts_dir else ""
        chain += f",ass=filename={_filter_escape(ass_path)}{extra}"
    return chain + ",fps=30,format=yuv420p[v]"


def render_clip(
    src: str | Path,
    info: VideoInfo,
    clip: Clip,
    out_path: str | Path,
    mode: str = "smart",
    ass_path: Path | None = None,
    fonts_dir: str = "",
    log=print,
) -> dict:
    out_path = Path(out_path)
    center_x = None
    if mode == "smart":
        center_x = face_center_x(src, clip.start, clip.duration)
    vf = build_video_filter(info, mode, center_x, ass_path, fonts_dir)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{clip.start:.3f}", "-i", str(src)]
    if info.has_audio:
        af = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    else:  # some platforms reject silent-less files; add a silent track
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        af = "[1:a]anull[a]"
    cmd += [
        "-t",
        f"{clip.duration:.3f}",
        "-filter_complex",
        f"{vf};{af}",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg failed: {proc.stderr.strip()[-800:]}")
    framing = (
        "vertical source"
        if info.width / max(info.height, 1) <= 0.57
        else "face-tracked crop"
        if center_x is not None and mode == "smart"
        else "blurred background"
        if mode in ("smart", "blur")
        else "center crop"
    )
    return {"framing": framing, "face_center_x": center_x}
