#!/usr/bin/env python3
"""Patch services/downloader.py so yt-dlp uses Instagram cookies when available.

Safe-ish text patch: creates services/downloader.py.bak_instagram_cookies before editing.
It injects _apply_instagram_cookie_opts(opts, url=...) before yt_dlp.YoutubeDL(opts).
"""
from __future__ import annotations

import re
from pathlib import Path

TARGET = Path("services/downloader.py")
BACKUP = Path("services/downloader.py.bak_instagram_cookies")
HELPER_MARK = "def _apply_instagram_cookie_opts("
HELPER = r'''

def _apply_instagram_cookie_opts(opts: dict, url: str = None) -> dict:
    """Apply Instagram cookies/user-agent to yt-dlp opts when downloading Instagram.

    Keeps old downloader API unchanged. If no cookie file exists, opts are returned as-is.
    """
    try:
        is_instagram = ("instagram.com" in (url or ""))
        if not is_instagram:
            # Some project functions pass platform separately but not url; applying
            # cookiefile globally is usually safe, but keep this conservative.
            return opts
        from pathlib import Path as _Path
        for _cookie in (_Path("cookies/instagram.txt"), _Path("cookies/cookies.txt"), _Path("instagram.txt")):
            if _cookie.exists() and _cookie.stat().st_size > 0:
                opts.setdefault("cookiefile", str(_cookie))
                break
        opts.setdefault(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        )
        headers = opts.setdefault("http_headers", {})
        headers.setdefault("Accept-Language", "en-US,en;q=0.9,ru;q=0.8")
    except Exception:
        pass
    return opts
'''


def inject_helper(src: str) -> str:
    if HELPER_MARK in src:
        return src
    # Put helper after import block.
    lines = src.splitlines(True)
    insert_at = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from ") or stripped == "" or stripped.startswith("#"):
            insert_at = i + 1
            continue
        break
    lines.insert(insert_at, HELPER + "\n")
    return "".join(lines)


def inject_calls(src: str) -> tuple[str, int]:
    lines = src.splitlines(True)
    out = []
    count = 0
    for line in lines:
        m = re.search(r"yt_dlp\.YoutubeDL\((\w+)\)", line)
        if m:
            var = m.group(1)
            prev = "".join(out[-3:])
            if f"_apply_instagram_cookie_opts({var}" not in prev:
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f'{indent}_apply_instagram_cookie_opts({var}, url=locals().get("url"))\n')
                count += 1
        out.append(line)
    return "".join(out), count


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found. Run this from project root.")
        return 2
    src = TARGET.read_text(encoding="utf-8")
    if not BACKUP.exists():
        BACKUP.write_text(src, encoding="utf-8")
        print("Backup created:", BACKUP)
    src2 = inject_helper(src)
    src3, count = inject_calls(src2)
    if src3 == src:
        print("No changes needed or no yt_dlp.YoutubeDL(opts) calls found.")
    else:
        TARGET.write_text(src3, encoding="utf-8")
        print(f"Patched {TARGET}; inserted cookie opts before {count} YoutubeDL calls.")
    print("Now run: python3 -m compileall -q services/downloader.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
