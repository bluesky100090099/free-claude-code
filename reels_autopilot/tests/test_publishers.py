"""Publisher flows against a fake HTTP layer (no network, no real accounts)."""

import json

import pytest

from reels.publishers import base, facebook, instagram, tiktok
from reels.publishers.base import Post


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00" * 1234)
    return p


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)


def test_instagram_flow(monkeypatch, video):
    monkeypatch.setenv("IG_USER_ID", "17")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    calls = []
    statuses = iter(["IN_PROGRESS", "FINISHED"])

    def post(url, **kw):
        calls.append(("POST", url, kw))
        if url.endswith("/17/media"):
            assert kw["data"]["media_type"] == "REELS"
            return FakeResp({"id": "C1", "uri": "https://rupload.example/C1"})
        if url == "https://rupload.example/C1":
            assert kw["headers"]["file_size"] == "1234"
            return FakeResp({"success": True})
        if url.endswith("/media_publish"):
            return FakeResp({"id": "M1"})
        raise AssertionError(url)

    def get(url, params=None, **kw):
        if url.endswith("/C1"):
            return FakeResp({"status_code": next(statuses)})
        return FakeResp({"permalink": "https://instagram.com/reel/x"})

    monkeypatch.setattr(instagram.requests, "post", post)
    monkeypatch.setattr(instagram.requests, "get", get)
    res = instagram.InstagramPublisher().publish(Post(video, "t", "cap", ["#a"]))
    assert res.ok and res.id == "M1" and res.url.endswith("/reel/x")
    assert calls[0][2]["data"]["caption"] == "cap\n\n#a"


def test_instagram_error_surfaces(monkeypatch, video):
    monkeypatch.setenv("IG_USER_ID", "17")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        instagram.requests,
        "post",
        lambda *a, **k: FakeResp({"error": {"message": "bad token"}}, 400),
    )
    with pytest.raises(base.PublishError, match="bad token"):
        instagram.InstagramPublisher().publish(Post(video, "t", "c"))


def test_facebook_flow(monkeypatch, video):
    monkeypatch.setenv("FB_PAGE_ID", "99")
    monkeypatch.setenv("FB_PAGE_TOKEN", "tok")
    phases = []

    def post(url, data=None, headers=None, **kw):
        if url.endswith("/video_reels"):
            phases.append(data["upload_phase"])
            if data["upload_phase"] == "start":
                return FakeResp({"video_id": "V1", "upload_url": "https://up/V1"})
            assert data["video_state"] == "PUBLISHED"
            return FakeResp({"success": True})
        assert headers["Authorization"] == "OAuth tok"
        return FakeResp({"success": True})

    monkeypatch.setattr(facebook.requests, "post", post)
    res = facebook.FacebookPublisher().publish(Post(video, "Title", "cap"))
    assert phases == ["start", "finish"]
    assert res.url == "https://www.facebook.com/reel/V1"


@pytest.mark.parametrize("mode", ["inbox", "direct"])
def test_tiktok_flow(monkeypatch, video, mode):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "tok")
    monkeypatch.delenv("TIKTOK_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("TIKTOK_MODE", mode)
    seen = {}

    def post(url, json=None, **kw):
        if url.endswith("/video/init/"):
            seen["init"] = (url, json)
            return FakeResp(
                {
                    "data": {"publish_id": "P1", "upload_url": "https://up"},
                    "error": {"code": "ok"},
                }
            )
        status = "SEND_TO_USER_INBOX" if mode == "inbox" else "PUBLISH_COMPLETE"
        return FakeResp({"data": {"status": status}, "error": {"code": "ok"}})

    def put(url, data=None, headers=None, **kw):
        seen["range"] = headers["Content-Range"]
        return FakeResp({}, 201)

    monkeypatch.setattr(tiktok.requests, "post", post)
    monkeypatch.setattr(tiktok.requests, "put", put)
    res = tiktok.TikTokPublisher().publish(Post(video, "t", "c"))
    assert res.ok and res.id == "P1"
    assert seen["range"] == "bytes 0-1233/1234"
    url, body = seen["init"]
    assert ("/inbox/" in url) == (mode == "inbox")
    if mode == "direct":
        assert body["post_info"]["privacy_level"] == "SELF_ONLY"


def test_publish_batch_skips_done_and_respects_next(monkeypatch, tmp_path):
    from reels import publish as pub_mod
    from reels.pipeline import load_manifest, save_manifest
    from reels.publishers.base import Publisher, PublishResult

    class Fake(Publisher):
        name = "youtube"
        posted: list = []

        def publish(self, post):
            Fake.posted.append(post.video.name)
            return PublishResult("youtube", True, "id", "url")

    monkeypatch.setitem(pub_mod.PUBLISHERS, "youtube", Fake)
    clips = [
        {
            "file": f"clip_0{i}.mp4",
            "title": "t",
            "caption": "c",
            "hashtags": [],
            "published": {},
        }
        for i in (1, 2, 3)
    ]
    clips[0]["published"]["youtube"] = {"ok": True}
    save_manifest(tmp_path, {"clips": clips})
    pub_mod.publish_batch(tmp_path, ["youtube"], next_n=1, log=lambda *_: None)
    assert Fake.posted == ["clip_02.mp4"]
    _, m = load_manifest(tmp_path)
    assert m["clips"][1]["published"]["youtube"]["ok"] is True
    assert m["clips"][2]["published"] == {}
