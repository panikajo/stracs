#!/usr/bin/env python3
"""Check whether Instagram cookies exist and whether yt-dlp can access a reel."""
from __future__ import annotations

import os
import sys
from pathlib import Path

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.instagram.com/reel/DZZI166gJVp/"
COOKIE_CANDIDATES = [
    Path("cookies/instagram.txt"),
    Path("cookies/cookies.txt"),
    Path("instagram.txt"),
]


def find_cookie() -> Path | None:
    for p in COOKIE_CANDIDATES:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def main() -> int:
    print("URL:", URL)
    print("Working dir:", Path.cwd())
    print("\nCookie files:")
    cookie = None
    for p in COOKIE_CANDIDATES:
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        print(f" - {p}: {'OK' if exists and size else 'missing/empty'} ({size} bytes)")
        if cookie is None and exists and size:
            cookie = p

    try:
        import yt_dlp
        print("\nyt-dlp:", getattr(yt_dlp.version, "__version__", "unknown"))
    except Exception as e:
        print("\nERROR: cannot import yt_dlp:", e)
        return 2

    if not cookie:
        print("\nERROR: cookies file not found or empty.")
        print("Run /refreshcookies in bot admin, or export Instagram cookies to cookies/instagram.txt")
        return 3

    opts = {
        "quiet": False,
        "no_warnings": False,
        "skip_download": True,
        "cookiefile": str(cookie),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "http_headers": {"Accept-Language": "en-US,en;q=0.9,ru;q=0.8"},
    }
    print("\nTesting with cookiefile:", cookie)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(URL, download=False)
        print("\nOK: Instagram info returned")
        print("title:", (info or {}).get("title"))
        print("uploader:", (info or {}).get("uploader"))
        print("duration:", (info or {}).get("duration"))
        return 0
    except Exception as e:
        print("\nERROR: yt-dlp still cannot access Instagram:")
        print(type(e).__name__ + ":", e)
        print("\nMost likely cookies are expired/invalid, Instagram requires challenge, or server IP is rate-limited.")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
