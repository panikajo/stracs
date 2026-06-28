#!/usr/bin/env python3
"""Check whether YouTube cookies exist and whether yt-dlp can access a video."""
from __future__ import annotations

import sys
from pathlib import Path

URL = (sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=pDkGYWpeUPE").strip("<>")
COOKIE_CANDIDATES = [
    Path("cookies/youtube.txt"),
    Path("cookies/google.txt"),
    Path("youtube.txt"),
    Path("cookies/cookies.txt"),
]


def main() -> int:
    print("URL:", URL)
    print("Working dir:", Path.cwd())
    print("\nCookie files:")
    cookie = None
    for p in COOKIE_CANDIDATES:
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        ok = exists and size > 0
        print(f" - {p}: {'OK' if ok else 'missing/empty'} ({size} bytes)")
        if cookie is None and ok:
            cookie = p

    try:
        import yt_dlp
        print("\nyt-dlp:", getattr(yt_dlp.version, "__version__", "unknown"))
    except Exception as e:
        print("\nERROR: cannot import yt_dlp:", e)
        return 2

    opts = {
        "quiet": False,
        "no_warnings": False,
        "skip_download": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "http_headers": {"Accept-Language": "en-US,en;q=0.9,ru;q=0.8"},
    }
    if cookie:
        opts["cookiefile"] = str(cookie)
        print("\nTesting with cookiefile:", cookie)
    else:
        print("\nWARNING: no YouTube cookies found. Testing without cookies.")

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(URL, download=False)
        print("\nOK: YouTube info returned")
        print("title:", (info or {}).get("title"))
        print("uploader:", (info or {}).get("uploader"))
        print("duration:", (info or {}).get("duration"))
        return 0
    except Exception as e:
        print("\nERROR: yt-dlp cannot access YouTube:")
        print(type(e).__name__ + ":", e)
        print("\nIf error says 'Sign in to confirm you’re not a bot', export YouTube cookies to cookies/youtube.txt")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
