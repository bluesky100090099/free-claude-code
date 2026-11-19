import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests


@dataclass
class Post:
    video: Path
    title: str
    caption: str
    hashtags: list[str] = field(default_factory=list)

    def text(self, limit: int = 2200, with_title: bool = False) -> str:
        parts = [self.title] if with_title and self.title else []
        if self.caption:
            parts.append(self.caption)
        if self.hashtags:
            parts.append(" ".join(self.hashtags))
        return "\n\n".join(parts)[:limit]


@dataclass
class PublishResult:
    platform: str
    ok: bool
    id: str = ""
    url: str = ""
    error: str = ""
    note: str = ""


class PublishError(RuntimeError):
    pass


class Publisher:
    name = "base"
    required_env: tuple[str, ...] = ()

    def missing(self) -> list[str]:
        return [k for k in self.required_env if not os.environ.get(k, "").strip()]

    def is_configured(self) -> bool:
        return not self.missing()

    def publish(self, post: Post) -> PublishResult:  # pragma: no cover
        raise NotImplementedError


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def check(resp: requests.Response, what: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        err = data.get("error", data) if isinstance(data, dict) else data
        if isinstance(err, dict):
            err = err.get("message") or err.get("error_user_msg") or err
        raise PublishError(f"{what} failed ({resp.status_code}): {err}")
    return data


def poll(fn, done, timeout: float = 600, every: float = 5):
    """Call fn() until done(result) is True or a PublishError is raised."""
    deadline = time.time() + timeout
    while True:
        result = fn()
        if done(result):
            return result
        if time.time() > deadline:
            raise PublishError(f"timed out waiting for processing: {result}")
        time.sleep(every)
