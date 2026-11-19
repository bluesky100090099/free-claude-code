"""Settings read from environment variables (or a local .env file)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

RTL_LANGUAGES = {"ar", "fa", "ur", "he", "ps", "ku"}


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (no extra dependency). Existing env vars win."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


@dataclass
class Settings:
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(
        default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.5-flash")
    )
    language: str = field(default_factory=lambda: _env("REELS_LANGUAGE", "ar"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))
    font: str = field(default_factory=lambda: _env("REELS_FONT", "DejaVu Sans"))
    fonts_dir: str = field(default_factory=lambda: _env("REELS_FONTS_DIR"))

    @property
    def rtl(self) -> bool:
        return self.language.split("-")[0].lower() in RTL_LANGUAGES
