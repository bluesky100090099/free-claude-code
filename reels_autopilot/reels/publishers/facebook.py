"""Facebook Page Reels via the Graph API (free)."""

import requests

from reels.publishers.base import Post, Publisher, PublishResult, check, env


class FacebookPublisher(Publisher):
    name = "facebook"
    required_env = ("FB_PAGE_ID", "FB_PAGE_TOKEN")

    def publish(self, post: Post) -> PublishResult:
        v = env("META_GRAPH_VERSION", "v23.0")
        page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
        endpoint = f"https://graph.facebook.com/{v}/{page}/video_reels"
        start = check(
            requests.post(
                endpoint,
                data={"upload_phase": "start", "access_token": token},
                timeout=60,
            ),
            "start reel upload",
        )
        video_id = start["video_id"]
        upload_url = start.get("upload_url") or (
            f"https://rupload.facebook.com/video-upload/{v}/{video_id}"
        )
        data = post.video.read_bytes()
        check(
            requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(len(data)),
                },
                data=data,
                timeout=600,
            ),
            "upload reel",
        )
        check(
            requests.post(
                endpoint,
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": post.for_platform("facebook")["description"],
                    "access_token": token,
                },
                timeout=60,
            ),
            "publish reel",
        )
        return PublishResult(
            self.name, True, video_id, f"https://www.facebook.com/reel/{video_id}"
        )
