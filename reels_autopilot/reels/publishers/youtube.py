"""YouTube Shorts via YouTube Data API v3 (free, ~6 uploads/day default quota).

A vertical video <= 3 minutes is automatically a Short. NOTE: Google locks
uploads from *unverified* API projects to private until the project passes a
(free) compliance audit – see README.
"""

from reels.publishers.base import Post, Publisher, PublishResult, env

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubePublisher(Publisher):
    name = "youtube"
    required_env = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")

    def _service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=env("YT_REFRESH_TOKEN"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=env("YT_CLIENT_ID"),
            client_secret=env("YT_CLIENT_SECRET"),
            scopes=SCOPES,
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def publish(self, post: Post) -> PublishResult:
        from googleapiclient.http import MediaFileUpload

        copy = post.for_platform("youtube")
        body = {
            "snippet": {
                "title": copy["title"],
                "description": copy["description"],
                "tags": copy["tags"],
                "defaultLanguage": env("REELS_LANGUAGE", "ar"),
                "categoryId": env("YT_CATEGORY_ID", "22"),
            },
            "status": {
                "privacyStatus": env("YT_PRIVACY", "public"),
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(
            str(post.video), mimetype="video/mp4", chunksize=-1, resumable=True
        )
        req = (
            self._service()
            .videos()
            .insert(part="snippet,status", body=body, media_body=media)
        )
        response = None
        while response is None:
            _status, response = req.next_chunk()
        vid = response["id"]
        return PublishResult(
            self.name,
            True,
            vid,
            f"https://youtube.com/shorts/{vid}",
            note=f"privacy={body['status']['privacyStatus']}",
        )
