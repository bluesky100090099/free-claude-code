"""Platform publishers. Each one is optional and only runs when configured."""

from reels.publishers.base import Post, Publisher, PublishResult
from reels.publishers.facebook import FacebookPublisher
from reels.publishers.instagram import InstagramPublisher
from reels.publishers.tiktok import TikTokPublisher
from reels.publishers.youtube import YouTubePublisher

PUBLISHERS: dict[str, type[Publisher]] = {
    "youtube": YouTubePublisher,
    "instagram": InstagramPublisher,
    "facebook": FacebookPublisher,
    "tiktok": TikTokPublisher,
}

__all__ = ["PUBLISHERS", "Post", "PublishResult", "Publisher"]
