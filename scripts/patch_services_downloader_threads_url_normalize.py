#!/usr/bin/env python3
"""Patch services/downloader.py to normalize Threads URLs before yt-dlp."""
from __future__ import annotations

from pathlib import Path

TARGET = Path("services/downloader.py")
BACKUP = Path("services/downloader.py.bak_threads_url_normalize")
HELPER_MARK = "def _normalize_threads_url_for_ytdlp("
HELPER = r'''

def _normalize_threads_url_for_ytdlp(url: str) -> str:
    """Canonicalize Threads URLs for yt-dlp.

    Converts Slack-style <url>, threads.com, and tracking params into:
      https://www.threads.net/@user/post/POST_ID
    """
    try:
        import re as _re
        u = str(url or "").strip().strip("<>").strip()
        if u.startswith("http") and "|" in u:
            u = u.split("|", 1)[0].strip("<>")
        m = _re.search(r"https?://(?:www\.)?threads\.(?:com|net)/(@[^/]+)/(post|media)/([^/?#>]+)", u, _re.I)
        if m:
            return f"https://www.threads.net/{m.group(1)}/{m.group(2)}/{m.group(3)}"
        return u
    except Exception:
        return url
'''


def inject_helper(src: str) -> str:
    if HELPER_MARK in src:
        return src
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


def inject_before_ytdlp(src: str) -> tuple[str, int]:
    lines = src.splitlines(True)
    out = []
    count = 0
    for line in lines:
        if "yt_dlp.YoutubeDL(" in line:
            prev = "".join(out[-6:])
            if "_normalize_threads_url_for_ytdlp" not in prev:
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f'{indent}if "url" in locals():\n')
                out.append(f'{indent}    url = _normalize_threads_url_for_ytdlp(url)\n')
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
    src3, count = inject_before_ytdlp(src2)
    if src3 == src:
        print("No changes needed.")
    else:
        TARGET.write_text(src3, encoding="utf-8")
        print(f"Patched {TARGET}; normalized url before {count} YoutubeDL calls.")
    print("Now run: python3 -m compileall -q services/downloader.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
