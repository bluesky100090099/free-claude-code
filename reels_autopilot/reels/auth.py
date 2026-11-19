"""One-time helpers that turn app credentials into long-lived tokens."""

import os
import secrets
import urllib.parse

import requests


def _graph(path: str, version: str, **params) -> dict:
    r = requests.get(
        f"https://graph.facebook.com/{version}/{path}", params=params, timeout=30
    )
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(data.get("error", {}).get("message", data))
    return data


def meta(app_id: str, app_secret: str, short_token: str) -> None:
    """Short-lived user token → never-expiring Page token + IG user id."""
    v = os.environ.get("META_GRAPH_VERSION", "v23.0")
    long_user = _graph(
        "oauth/access_token",
        v,
        grant_type="fb_exchange_token",
        client_id=app_id,
        client_secret=app_secret,
        fb_exchange_token=short_token,
    )["access_token"]
    pages = _graph(
        "me/accounts",
        v,
        access_token=long_user,
        fields="id,name,access_token,instagram_business_account",
    )
    if not pages.get("data"):
        print("No Facebook Page found for this user (did you grant page access?)")
        return
    for page in pages["data"]:
        ig = (page.get("instagram_business_account") or {}).get("id", "")
        print(f"\n# Page: {page['name']}")
        print(f"FB_PAGE_ID={page['id']}")
        print(f"FB_PAGE_TOKEN={page['access_token']}")
        if ig:
            print(f"IG_USER_ID={ig}")
            print(f"IG_ACCESS_TOKEN={page['access_token']}")
        else:
            print("# (no Instagram Business/Creator account linked to this Page)")
    print("\nPage tokens made from a long-lived user token do not expire.")


def tiktok(client_key: str, client_secret: str, redirect_uri: str) -> None:
    """Interactive OAuth: open URL, approve, paste the redirected URL back."""
    state = secrets.token_urlsafe(16)
    scopes = os.environ.get(
        "TIKTOK_SCOPES", "user.info.basic,video.upload,video.publish"
    )
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(
        {
            "client_key": client_key,
            "scope": scopes,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    print("1) Open this link, log in and approve:\n\n" + url + "\n")
    back = input("2) Paste the full URL you were redirected to: ").strip()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    if query.get("state", [""])[0] != state:
        raise RuntimeError("state mismatch – start again")
    r = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": query["code"][0],
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    data = r.json()
    if "refresh_token" not in data:
        raise RuntimeError(data)
    print(f"\nTIKTOK_REFRESH_TOKEN={data['refresh_token']}")
    print(f"# valid ~{int(data.get('refresh_expires_in', 0)) // 86400} days")
