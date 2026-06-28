#!/usr/bin/env python3
"""Debug what Threads returns to this server for a post URL."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def normalize_threads_url(raw: str) -> str:
    u = str(raw or "").replace("&lt;", "<").replace("&gt;", ">").strip().strip("'\"").strip().strip("<>").strip()
    if u.startswith("http") and "|" in u:
        u = u.split("|", 1)[0].strip("<>")
    m = re.search(r"https?://(?:www\.)?threads\.(?:com|net)/(@[^/]+)/(post|media)/([^/?#>]+)", u, re.I)
    if m:
        return f"https://www.threads.net/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    m = re.search(r"https?://(?:www\.)?threads\.(?:com|net)/t/([^/?#>]+)", u, re.I)
    if m:
        return f"https://www.threads.net/t/{m.group(1)}"
    return u

URL = normalize_threads_url(sys.argv[1] if len(sys.argv) > 1 else "")
if not URL:
    print("Usage: python3 scripts/debug_threads_page.py 'https://www.threads.net/@user/post/POST_ID'")
    raise SystemExit(2)

COOKIE_CANDIDATES = [Path("cookies/threads.txt"), Path("cookies/instagram.txt"), Path("cookies/meta.txt"), Path("cookies/cookies.txt")]
shortcode = URL.rstrip('/').split('/')[-1]

try:
    import yt_dlp
except Exception as e:
    print("ERROR: cannot import yt_dlp:", e)
    raise SystemExit(2)

base_opts = {
    "quiet": True,
    "skip_download": True,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "http_headers": {"Accept-Language": "en-US,en;q=0.9,ru;q=0.8"},
}

print("URL:", URL)
print("shortcode:", shortcode)

for cookie in [None, *COOKIE_CANDIDATES]:
    if cookie is not None and (not cookie.exists() or cookie.stat().st_size <= 0):
        continue
    label = str(cookie) if cookie else "no cookies"
    opts = dict(base_opts)
    if cookie:
        opts["cookiefile"] = str(cookie)
    print("\n===", label, "===")
    if cookie:
        txt = cookie.read_text(errors="ignore")
        print("cookie bytes:", cookie.stat().st_size)
        print("has session marker:", any(x in txt for x in ("sessionid", "c_user", "xs")))
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            webpage = ydl.urlopen(URL).read().decode("utf-8", "ignore")
    except Exception as e:
        print("download error:", repr(e))
        continue
    print("html bytes:", len(webpage))
    for needle in [shortcode, "video_versions", "image_versions2", "og:video", "og:image", "__bbox", "login", "Please wait"]:
        print(f"contains {needle!r}:", needle in webpage)
    media_urls = re.findall(r"https?:\\?/\\?/[^\"'<>\\\s]+?\.(?:mp4|m3u8)(?:\?[^\"'<>\\\s]+)?", webpage, flags=re.I)
    print("raw mp4/m3u8 urls:", len(set(media_urls)))
