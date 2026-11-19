"""Command line: python -m reels {make,publish,status,doctor,auth}"""

import argparse
import os
import shutil
import sys
from pathlib import Path

from reels.config import Settings, load_dotenv

PLATFORMS = ["youtube", "instagram", "facebook", "tiktok"]


def _platforms(value: str) -> list[str]:
    items = [p.strip().lower() for p in value.split(",") if p.strip()]
    if items == ["all"]:
        return PLATFORMS
    bad = [p for p in items if p not in PLATFORMS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown platform(s): {', '.join(bad)}")
    return items


def cmd_make(args) -> int:
    from reels.pipeline import make
    from reels.publish import publish_batch

    settings = Settings()
    if args.lang:
        settings.language = args.lang
    batch = make(
        args.input,
        args.out,
        args.count,
        args.duration,
        args.crop,
        args.picker,
        not args.no_captions,
        settings,
    )
    if args.publish:
        publish_batch(batch, args.platforms, args.next)
    print(f"\nBATCH_DIR={batch}")
    return 0


def cmd_publish(args) -> int:
    from reels.publish import publish_batch

    results = publish_batch(args.target, args.platforms, args.next, args.dry_run)
    return 1 if any(not r.ok for r in results) else 0


def cmd_status(args) -> int:
    from reels.pipeline import load_manifest

    _batch, manifest = load_manifest(args.target)
    for c in manifest["clips"]:
        marks = []
        for p in PLATFORMS:
            st = c["published"].get(p)
            marks.append(f"{p}:{'✓' if st and st['ok'] else '✗' if st else '·'}")
        print(f"{c['file']}  {c['start']:7.1f}s  {' '.join(marks)}  {c['title'][:50]}")
    return 0


def cmd_pending(args) -> int:
    """Print how many clips still wait for a *configured* platform (for scripts)."""
    from reels.pipeline import load_manifest
    from reels.publish import needs_publish
    from reels.publishers import PUBLISHERS

    _batch, manifest = load_manifest(args.target)
    active = [p for p in args.platforms if PUBLISHERS[p]().is_configured()]
    if not active:
        print(-1)  # nothing configured: never treat a batch as finished
        return 0
    pending = sum(
        1 for c in manifest["clips"] if any(needs_publish(c, p) for p in active)
    )
    print(pending)
    return 0


def cmd_doctor(_args) -> int:
    from reels.publishers import PUBLISHERS

    s = Settings()
    print(f"ffmpeg:   {'✓' if shutil.which('ffmpeg') else '✗ install ffmpeg'}")
    print(f"Gemini:   {'✓' if s.gemini_api_key else '✗ (local picker will be used)'}")
    for mod, label in [
        ("faster_whisper", "captions"),
        ("cv2", "face crop"),
        ("google.genai", "gemini sdk"),
    ]:
        try:
            __import__(mod)
            print(f"{label + ':':<10}✓")
        except ImportError:
            print(f"{label + ':':<10}✗ pip install -r requirements.txt")
    for name, cls in PUBLISHERS.items():
        miss = cls().missing()
        print(
            f"{name + ':':<10}{'✓ auto-publish' if not miss else '✗ manual'}"
            f"{'' if not miss else '  (missing ' + ', '.join(miss) + ')'}"
        )
    return 0


def cmd_auth(args) -> int:
    from reels import auth

    env = os.environ.get
    if args.platform == "meta":
        missing = [k for k in ("META_APP_ID", "META_APP_SECRET") if not env(k)]
        if missing or not args.token:
            print(
                "Usage: META_APP_ID=.. META_APP_SECRET=.. "
                "python -m reels auth meta --token <short-lived user token>"
            )
            return 1
        auth.meta(env("META_APP_ID", ""), env("META_APP_SECRET", ""), args.token)
        return 0
    if args.platform == "tiktok":
        keys = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI")
        if any(not env(k) for k in keys):
            print(f"Set {', '.join(keys)} first (.env).")
            return 1
        auth.tiktok(*(env(k, "") for k in keys))
        return 0
    from google_auth_oauthlib.flow import InstalledAppFlow

    from reels.publishers.youtube import SCOPES

    cid, secret = os.environ.get("YT_CLIENT_ID"), os.environ.get("YT_CLIENT_SECRET")
    if not cid or not secret:
        print("Set YT_CLIENT_ID and YT_CLIENT_SECRET first (.env).")
        return 1
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": cid,
                "client_secret": secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        SCOPES,
    )
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    print("\nAdd this to your .env / GitHub secrets / Colab secrets:\n")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reels", description="Free Reels/Shorts autopilot")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="cut a long video into vertical clips")
    m.add_argument("input", help="video file or URL")
    m.add_argument("-n", "--count", type=int, default=5)
    m.add_argument("-d", "--duration", type=float, default=15.0)
    m.add_argument("-o", "--out", default="out")
    m.add_argument("--crop", choices=["smart", "center", "blur"], default="smart")
    m.add_argument("--picker", choices=["auto", "gemini", "energy"], default="auto")
    m.add_argument("--lang", help="caption/copy language, e.g. ar, en")
    m.add_argument("--no-captions", action="store_true")
    m.add_argument("--publish", action="store_true", help="publish right after")
    m.add_argument("--platforms", type=_platforms, default=PLATFORMS)
    m.add_argument("--next", type=int, default=0)
    m.set_defaults(func=cmd_make)

    pb = sub.add_parser("publish", help="publish pending clips of a batch")
    pb.add_argument("target", help="batch folder (or its manifest.json)")
    pb.add_argument("--platforms", type=_platforms, default=PLATFORMS)
    pb.add_argument("--next", type=int, default=0, help="only the next N clips")
    pb.add_argument("--dry-run", action="store_true")
    pb.set_defaults(func=cmd_publish)

    st = sub.add_parser("status", help="show what is published")
    st.add_argument("target")
    st.set_defaults(func=cmd_status)

    pe = sub.add_parser("pending", help="count clips not yet published")
    pe.add_argument("target")
    pe.add_argument("--platforms", type=_platforms, default=PLATFORMS)
    pe.set_defaults(func=cmd_pending)

    sub.add_parser("doctor", help="check setup").set_defaults(func=cmd_doctor)

    au = sub.add_parser("auth", help="one-time token helpers")
    au.add_argument("platform", choices=["youtube", "meta", "tiktok"])
    au.add_argument("--token", help="meta: short-lived user token")
    au.set_defaults(func=cmd_auth)
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
