#!/usr/bin/env python3
"""Check whether yt-dlp can read a Threads post from this server."""
from __future__ import annotations

import sys
from pathlib import Path
import re


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
    print("Usage: python3 scripts/check_threads_runtime.py https://www.threads.net/@user/post/POST_ID")
    raise SystemExit(2)

COOKIE_CANDIDATES = [
    Path("cookies/threads.txt"),
    Path("cookies/instagram.txt"),
    Path("cookies/meta.txt"),
    Path("cookies/cookies.txt"),
]

print("URL:", URL)
print("Working dir:", Path.cwd())
print("\nCookie files:")
cookie = None
for p in COOKIE_CANDIDATES:
    ok = p.exists() and p.stat().st_size > 0
    print(f" - {p}: {'OK' if ok else 'missing/empty'} ({p.stat().st_size if p.exists() else 0} bytes)")
    if cookie is None and ok:
        cookie = p

if cookie:
    try:
        txt = cookie.read_text(errors="ignore")
        has_session = any(name in txt for name in ("sessionid", "c_user", "xs"))
        if not has_session:
            print("WARNING: cookie file found, but no obvious login session cookie (sessionid/c_user/xs). It may be only public cookies.")
    except Exception:
        pass

try:
    import yt_dlp
    print("\nyt-dlp:", getattr(yt_dlp.version, "__version__", "unknown"))
except Exception as e:
    print("\nERROR: cannot import yt_dlp:", e)
    raise SystemExit(2)

# Load local Threads extractor plugin if present. This fixes yt-dlp
# "Unsupported URL" when the installed yt-dlp has no built-in Threads IE.
try:
    from yt_dlp.globals import plugin_dirs
    import yt_dlp.plugins as _plugins
    plugin_root = Path("plugins")
    if plugin_root.exists():
        current = list(plugin_dirs.value or [])
        if str(plugin_root) not in current:
            plugin_dirs.value = [str(plugin_root)] + current
        _plugins.load_all_plugins()
        print("Threads plugin dirs:", ", ".join(_plugins.directories()) or "not found")
except Exception as e:
    print("WARNING: could not load local yt-dlp plugin:", e)

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
    print("\nTesting without cookies (public Threads only).")

try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(URL, download=False)
    print("\nOK: Threads info returned")
    print("title:", (info or {}).get("title"))
    print("uploader:", (info or {}).get("uploader"))
    print("duration:", (info or {}).get("duration"))
    print("thumbnail:", (info or {}).get("thumbnail"))
    raise SystemExit(0)
except Exception as e:
    print("\nERROR: yt-dlp cannot access Threads:")
    print(type(e).__name__ + ":", e)
    print("\nIf the post is login-required, export cookies to cookies/threads.txt or reuse cookies/instagram.txt.")
    raise SystemExit(4)
