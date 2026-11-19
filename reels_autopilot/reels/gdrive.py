"""Save clips to Google Drive and log every clip as a row in a Google Sheet.

In Google Colab this needs no setup: `google.colab.auth.authenticate_user()`
asks you to approve once, then Application Default Credentials are used.
Elsewhere, any Google credentials with Drive + Sheets scopes work.
"""

from pathlib import Path

from reels.pipeline import load_manifest, save_manifest
from reels.publishers.base import Post

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
HEADER = [
    "Date",
    "Source",
    "Clip",
    "Drive link",
    "Start (s)",
    "Hook",
    "YouTube title",
    "YouTube description",
    "YouTube tags",
    "Instagram caption",
    "TikTok caption",
    "Facebook text",
    "Hashtags",
    "Status",
]


def _services():
    import google.auth
    from googleapiclient.discovery import build

    creds, _ = google.auth.default(scopes=SCOPES)
    return (
        build("drive", "v3", credentials=creds, cache_discovery=False),
        build("sheets", "v4", credentials=creds, cache_discovery=False),
    )


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_or_create(drive, name: str, mime: str, parent: str | None = None) -> str:
    q = f"name = '{_q(name)}' and mimeType = '{mime}' and trashed = false"
    if parent:
        q += f" and '{parent}' in parents"
    found = drive.files().list(q=q, fields="files(id)", pageSize=1).execute()
    if found.get("files"):
        return found["files"][0]["id"]
    meta: dict = {"name": name, "mimeType": mime}
    if parent:
        meta["parents"] = [parent]
    return drive.files().create(body=meta, fields="id").execute()["id"]


def export_to_google(
    batch: str | Path,
    folder: str = "Reels Autopilot",
    sheet_name: str = "Reels Autopilot – Log",
    upload: bool = True,
    sheet: bool = True,
    log=print,
) -> dict:
    from googleapiclient.http import MediaFileUpload

    batch_dir, manifest = load_manifest(batch)
    drive, sheets = _services()
    result: dict = {}

    root = _find_or_create(drive, folder, FOLDER_MIME)
    if upload:
        sub = _find_or_create(drive, batch_dir.name, FOLDER_MIME, root)
        result["folder_url"] = f"https://drive.google.com/drive/folders/{sub}"
        files = [c["file"] for c in manifest["clips"]] + ["POST_KIT.md"]
        for name in files:
            path = batch_dir / name
            if not path.exists():
                continue
            mime = "video/mp4" if name.endswith(".mp4") else "text/markdown"
            log(f"  Drive ← {name}")
            f = (
                drive.files()
                .create(
                    body={"name": name, "parents": [sub]},
                    media_body=MediaFileUpload(
                        str(path), mimetype=mime, resumable=True
                    ),
                    fields="id,webViewLink",
                )
                .execute()
            )
            for c in manifest["clips"]:
                if c["file"] == name:
                    c["drive_url"] = f["webViewLink"]
        save_manifest(batch_dir, manifest)
        log(f"✓ Drive folder: {result['folder_url']}")

    if sheet:
        sid = _find_or_create(drive, sheet_name, SHEET_MIME, root)
        existing = (
            sheets.spreadsheets()
            .values()
            .get(spreadsheetId=sid, range="A1:A1")
            .execute()
        )
        rows = [] if existing.get("values") else [HEADER]
        for c in manifest["clips"]:
            post = Post(
                batch_dir / c["file"],
                c["title"],
                c["caption"],
                c["hashtags"],
                c.get("description", ""),
                c.get("tags", []),
            )
            yt = post.for_platform("youtube")
            done = [p for p, s in c.get("published", {}).items() if s.get("ok")]
            rows.append(
                [
                    manifest["created"],
                    manifest.get("source_url") or manifest["source"],
                    c["file"],
                    c.get("drive_url", ""),
                    c["start"],
                    c["hook"],
                    yt["title"],
                    yt["description"],
                    ", ".join(yt["tags"]),
                    post.for_platform("instagram")["caption"],
                    post.for_platform("tiktok")["caption"],
                    post.for_platform("facebook")["description"],
                    " ".join(c["hashtags"]),
                    ("published: " + ", ".join(done)) if done else "ready to post",
                ]
            )
        sheets.spreadsheets().values().append(
            spreadsheetId=sid,
            range="A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        result["sheet_url"] = f"https://docs.google.com/spreadsheets/d/{sid}"
        log(f"✓ Sheet: {result['sheet_url']}")
    return result
