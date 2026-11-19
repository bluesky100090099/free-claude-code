"""Instagram Reels via the Instagram Graph API (free).

Requires an Instagram Business/Creator account. Uses the resumable upload
endpoint, so the video does NOT need to be hosted on a public URL.
"""

import contextlib

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


class InstagramPublisher(Publisher):
    name = "instagram"
    required_env = ("IG_USER_ID", "IG_ACCESS_TOKEN")

    def publish(self, post: Post) -> PublishResult:
        v = env("META_GRAPH_VERSION", "v23.0")
        host = env("IG_GRAPH_HOST", "graph.facebook.com")
        token, user = env("IG_ACCESS_TOKEN"), env("IG_USER_ID")
        base = f"https://{host}/{v}"
        container = check(
            requests.post(
                f"{base}/{user}/media",
                data={
                    "media_type": "REELS",
                    "upload_type": "resumable",
                    "caption": post.for_platform("instagram")["caption"],
                    "share_to_feed": "true",
                    "access_token": token,
                },
                timeout=60,
            ),
            "create reel container",
        )
        cid = container["id"]
        upload_uri = container.get("uri") or (
            f"https://rupload.facebook.com/ig-api-upload/{v}/{cid}"
        )
        data = post.video.read_bytes()
        check(
            requests.post(
                upload_uri,
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(len(data)),
                },
                data=data,
                timeout=600,
            ),
            "upload video",
        )

        def status():
            return check(
                requests.get(
                    f"{base}/{cid}",
                    params={"fields": "status_code,status", "access_token": token},
                    timeout=30,
                ),
                "check status",
            )

        def done(s):
            if s.get("status_code") == "ERROR":
                raise PublishError(f"Instagram processing error: {s.get('status')}")
            return s.get("status_code") == "FINISHED"

        poll(status, done, timeout=900, every=8)
        media = check(
            requests.post(
                f"{base}/{user}/media_publish",
                data={"creation_id": cid, "access_token": token},
                timeout=60,
            ),
            "publish reel",
        )
        mid = media["id"]
        url = ""
        with contextlib.suppress(Exception):
            url = (
                requests.get(
                    f"{base}/{mid}",
                    params={"fields": "permalink", "access_token": token},
                    timeout=30,
                )
                .json()
                .get("permalink", "")
            )
        return PublishResult(self.name, True, mid, url)
