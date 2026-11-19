import json
import shutil
import subprocess

import pytest

from reels.captions import Word, build_ass, group_words, transcript_text
from reels.config import Settings
from reels.highlights import (
    Clip,
    _parse_gemini_json,
    clean_hashtags,
    normalize_clips,
    parse_timestamp,
)


def test_normalize_forces_length_and_removes_overlap():
    clips = [Clip(10, 0, 9), Clip(12, 0, 8), Clip(95, 0, 7), Clip(40, 0, 6)]
    out = normalize_clips(clips, video_duration=100, duration=15, count=5)
    assert [(c.start, c.end) for c in out] == [(10, 25), (40, 55), (85, 100)]


def test_normalize_short_video():
    out = normalize_clips([Clip(3, 0, 1)], video_duration=9, duration=15, count=2)
    assert (out[0].start, out[0].end) == (0, 9)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(83, 83.0), ("83.5", 83.5), ("1:23", 83.0), ("01:01:23.5", 3683.5)],
)
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == expected


def test_clean_hashtags_dedup_and_unicode():
    assert clean_hashtags(["#ريلز", "ريلز", "fun stuff!", "#Tips"]) == [
        "#ريلز",
        "#funstuff",
        "#Tips",
    ]
    assert clean_hashtags("a, #b c") == ["#a", "#b", "#c"]


def test_parse_gemini_json_variants():
    assert _parse_gemini_json('```json\n[{"start": 3}]\n```') == [{"start": 3}]
    assert _parse_gemini_json('{"clips": [{"start": 1}, {"x": 2}]}') == [{"start": 1}]


def test_group_words_breaks_on_size_gap_and_punctuation():
    ws = [Word(i * 0.3, i * 0.3 + 0.25, f"w{i}") for i in range(7)]
    ws[3].text = "end."
    groups = group_words(ws)
    assert [len(g) for g in groups] == [3, 1, 3]


def test_build_ass_has_hook_and_one_event_per_word():
    s = Settings()
    words = [Word(10.0, 10.4, "مرحبا"), Word(10.5, 10.9, "بكم")]
    ass = build_ass(words, 10, 25, s, hook="سر {خطير}")
    events = [line for line in ass.splitlines() if line.startswith("Dialogue")]
    assert len(events) == 3
    assert "سر (خطير)" in events[0]  # braces escaped
    assert events[1].startswith("Dialogue: 0,0:00:00.00,0:00:00.50,Caption")
    assert ",-1\n" in ass  # auto base direction – required for Arabic


def test_transcript_text():
    ws = [Word(65.0, 65.5, "hello"), Word(65.6, 66.0, "world.")]
    assert transcript_text(ws) == "[01:05.0] hello world."


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_end_to_end_make(tmp_path):
    from reels.pipeline import make

    src = tmp_path / "in.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=40",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=40",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(src),
        ],
        check=True,
    )
    s = Settings()
    s.gemini_api_key = ""
    batch = make(
        str(src),
        tmp_path / "out",
        count=2,
        duration=5,
        picker="energy",
        captions=False,
        settings=s,
        log=lambda *_: None,
    )
    manifest = json.loads((batch / "manifest.json").read_text())
    assert len(manifest["clips"]) == 2
    for c in manifest["clips"]:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(batch / c["file"]),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert probe == "1080,1920"
    assert (batch / "POST_KIT.md").exists()
