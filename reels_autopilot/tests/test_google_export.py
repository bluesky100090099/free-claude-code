"""Drive/Sheets export and per-platform copy, with fake Google services."""

from reels import gdrive
from reels.pipeline import load_manifest, save_manifest
from reels.publishers.base import Post


class Call:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeFiles:
    def __init__(self):
        self.created = []

    def list(self, **kw):
        return Call({"files": []})

    def create(self, body, fields, media_body=None):
        self.created.append(body["name"])
        n = len(self.created)
        return Call({"id": f"id{n}", "webViewLink": f"https://drive/{n}"})


class FakeDrive:
    def __init__(self):
        self._files = FakeFiles()

    def files(self):
        return self._files


class FakeValues:
    def __init__(self):
        self.appended = []

    def get(self, **kw):
        return Call({})

    def append(self, body, **kw):
        self.appended += body["values"]
        return Call({})


class FakeSheets:
    def __init__(self):
        self.v = FakeValues()

    def spreadsheets(self):
        return self

    def values(self):
        return self.v


def test_export_uploads_and_logs(monkeypatch, tmp_path):
    (tmp_path / "clip_01.mp4").write_bytes(b"x")
    (tmp_path / "POST_KIT.md").write_text("kit")
    clip = {
        "file": "clip_01.mp4",
        "start": 10,
        "hook": "h",
        "title": "T",
        "caption": "c",
        "hashtags": ["#a"],
        "description": "d",
        "tags": ["k"],
        "published": {"youtube": {"ok": True}},
    }
    save_manifest(tmp_path, {"created": "now", "source": "s", "clips": [clip]})
    drive, sheets = FakeDrive(), FakeSheets()
    monkeypatch.setattr(gdrive, "_services", lambda: (drive, sheets))
    monkeypatch.setattr(
        "googleapiclient.http.MediaFileUpload", lambda *a, **k: object()
    )
    res = gdrive.export_to_google(tmp_path, log=lambda *_: None)
    assert "clip_01.mp4" in drive._files.created
    rows = sheets.v.appended
    assert rows[0] == gdrive.HEADER and rows[1][2] == "clip_01.mp4"
    assert rows[1][-1] == "published: youtube"
    assert res["sheet_url"].startswith("https://docs.google.com/")
    _, m = load_manifest(tmp_path)
    assert m["clips"][0]["drive_url"].startswith("https://drive/")


def test_platform_copy_rules(tmp_path):
    tags = [f"#t{i}" for i in range(10)]
    p = Post(tmp_path / "v.mp4", "عنوان", "وصف قصير", tags, "وصف طويل", ["كلمة"])
    yt = p.for_platform("youtube")
    assert yt["title"].endswith("#Shorts") and "وصف طويل" in yt["description"]
    assert yt["tags"][0] == "كلمة"
    ig = p.for_platform("instagram")["caption"]
    assert ig.count("#") == 5  # Instagram hashtag limit
    assert p.for_platform("facebook")["description"].startswith("عنوان")
