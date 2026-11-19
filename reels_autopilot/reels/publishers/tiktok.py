"""TikTok via the Content Posting API (free).

TIKTOK_MODE=inbox  -> video lands in your TikTok inbox/drafts; you tap "Post"
                      (needs the video.upload scope – easiest to get approved).
TIKTOK_MODE=direct -> posted directly (video.publish scope). Until TikTok audits
                      your app, direct posts can only be SELF_ONLY (private).
"""

import requests

from reels.publishers.base import (
    Post,
    Publisher,
    PublishError,
    PublishResult,
    check,
    env,
    poll,
)

API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024


def _tiktok_check(resp: requests.Response, what: str) -> dict:
    data = check(resp, what) if resp.status_code >= 400 else resp.json()
    err = data.get("error") or {}
    if err.get("code") not in (None, "", "ok"):
        raise PublishError(f"{what} failed: {err.get('code')} {err.get('message')}")
    return data.get("data", {})


class TikTokPublisher(Publisher):
    name = "tiktok"

    def missing(self) -> list[str]:
        if env("TIKTOK_ACCESS_TOKEN"):
            return []
        keys = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")
        return [k for k in keys if not env(k)]

    def _token(self) -> str:
        if env("TIKTOK_REFRESH_TOKEN") and env("TIKTOK_CLIENT_KEY"):
            resp = requests.post(
                f"{API}/oauth/token/",
                data={
                    "client_key": env("TIKTOK_CLIENT_KEY"),
                    "client_secret": env("TIKTOK_CLIENT_SECRET"),
                    "grant_type": "refresh_token",
                    "refresh_token": env("TIKTOK_REFRESH_TOKEN"),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            data = check(resp, "refresh TikTok token")
            if "access_token" in data:
                return data["access_token"]
        token = env("TIKTOK_ACCESS_TOKEN")
        if not token:
            raise PublishError("no TikTok access token")
        return token

    def publish(self, post: Post) -> PublishResult:
        token = self._token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        size = post.video.stat().st_size
        chunk = size if size <= 64 * 1024 * 1024 else CHUNK
        count = max(1, size // chunk) if chunk != size else 1
        source = {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk,
            "total_chunk_count": count,
        }
        mode = env("TIKTOK_MODE", "inbox")
        if mode == "direct":
            body = {
                "post_info": {
                    "title": post.for_platform("tiktok")["caption"],
                    "privacy_level": env("TIKTOK_PRIVACY", "SELF_ONLY"),
                    "disable_comment": False,
                    "disable_duet": False,
                    "disable_stitch": False,
                },
                "source_info": source,
            }
            url = f"{API}/post/publish/video/init/"
        else:
            body = {"source_info": source}
            url = f"{API}/post/publish/inbox/video/init/"
        init = _tiktok_check(
            requests.post(url, json=body, headers=headers, timeout=60), "TikTok init"
        )
        publish_id, upload_url = init["publish_id"], init["upload_url"]
        with post.video.open("rb") as fh:
            for i in range(count):
                first = i * chunk
                # the last chunk absorbs the remainder (TikTok's rule)
                length = size - first if i == count - 1 else chunk
                part = fh.read(length)
                last = first + len(part) - 1
                r = requests.put(
                    upload_url,
                    data=part,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(part)),
                        "Content-Range": f"bytes {first}-{last}/{size}",
                    },
                    timeout=600,
                )
                if r.status_code not in (200, 201, 206):
                    raise PublishError(f"TikTok upload chunk {i}: {r.status_code}")

        def status():
            return _tiktok_check(
                requests.post(
                    f"{API}/post/publish/status/fetch/",
                    json={"publish_id": publish_id},
                    headers=headers,
                    timeout=30,
                ),
                "TikTok status",
            )

        def done(s):
            st = s.get("status", "")
            if st == "FAILED":
                raise PublishError(f"TikTok failed: {s.get('fail_reason')}")
            return st in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE")

        final = poll(status, done, timeout=600, every=6)
        note = (
            "sent to your TikTok inbox – open the app and tap Post"
            if final.get("status") == "SEND_TO_USER_INBOX"
            else f"privacy={env('TIKTOK_PRIVACY', 'SELF_ONLY')}"
        )
        return PublishResult(self.name, True, publish_id, "", note=note)
