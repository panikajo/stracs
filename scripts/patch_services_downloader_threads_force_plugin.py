#!/usr/bin/env python3
"""Force-enable local yt-dlp Threads plugin in services/downloader.py.

Use when scripts/check_threads_runtime.py works with [threads], but the bot still says:
  ERROR: Unsupported URL: https://www.threads.com/...

This patch is intentionally broader than patch_services_downloader_threads_plugin.py:
- injects plugin loading right after imports, at module import time
- works whether downloader uses yt_dlp.YoutubeDL or `from yt_dlp import YoutubeDL`
- also normalizes Threads URLs before YoutubeDL usage when possible
"""
from __future__ import annotations

from pathlib import Path

TARGET = Path("services/downloader.py")
BACKUP = Path("services/downloader.py.bak_threads_force_plugin")
HELPER_MARK = "def _force_enable_threads_ytdlp_plugin("
CALL_MARK = "_force_enable_threads_ytdlp_plugin()"

HELPER = r'''

def _force_enable_threads_ytdlp_plugin() -> None:
    """Load local ./plugins yt-dlp extractors, especially ThreadsIE."""
    try:
        from pathlib import Path as _Path
        from yt_dlp.globals import plugin_dirs as _plugin_dirs
        import yt_dlp.plugins as _plugins
        _root = _Path("plugins")
        if not _root.exists():
            return
        _current = list(_plugin_dirs.value or [])
        if str(_root) not in _current:
            _plugin_dirs.value = [str(_root)] + _current
        _plugins.load_all_plugins()
    except Exception:
        pass


def _normalize_threads_url_for_ytdlp(url: str) -> str:
    """Canonicalize Threads URLs before passing to yt-dlp."""
    try:
        import re as _re
        u = str(url or "").replace("&lt;", "<").replace("&gt;", ">").strip().strip("'\"").strip().strip("<>").strip()
        if u.startswith("http") and "|" in u:
            u = u.split("|", 1)[0].strip("<>").strip()
        m = _re.search(r"https?://(?:www\.)?threads\.(?:com|net)/(?:@(?P<username>[^/?#>]+)/(?:post|media)/|t/)(?P<id>[A-Za-z0-9_-]+)", u, _re.I)
        if m:
            username = m.group("username")
            shortcode = m.group("id")
            if username:
                return f"https://www.threads.net/@{username}/post/{shortcode}"
            return f"https://www.threads.net/t/{shortcode}"
        return u
    except Exception:
        return url
'''


def find_import_insert_at(lines: list[str]) -> int:
    insert_at = 0
    in_docstring = False
    doc_quote = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and (stripped.startswith('"""') or stripped.startswith("'''") ):
            q = stripped[:3]
            if stripped.count(q) == 1:
                in_docstring = True
                doc_quote = q
            insert_at = i + 1
            continue
        if in_docstring:
            insert_at = i + 1
            if doc_quote and doc_quote in stripped:
                in_docstring = False
            continue
        if stripped.startswith("import ") or stripped.startswith("from ") or stripped == "" or stripped.startswith("#"):
            insert_at = i + 1
            continue
        break
    return insert_at


def patch(src: str) -> str:
    lines = src.splitlines(True)
    insert_at = find_import_insert_at(lines)
    changed = False

    if HELPER_MARK not in src:
        lines.insert(insert_at, HELPER + "\n")
        changed = True
        insert_at += 1

    src2 = "".join(lines)
    lines = src2.splitlines(True)
    insert_at = find_import_insert_at(lines)
    # Call at module import time, immediately after helper block if present.
    if CALL_MARK not in src2:
        # insert after helper function block by finding the next real top-level def/class after helper
        text = "".join(lines)
        idx = text.find(HELPER)
        if idx >= 0:
            end = idx + len(HELPER)
            text = text[:end] + f"\n{CALL_MARK}\n" + text[end:]
            lines = text.splitlines(True)
        else:
            lines.insert(insert_at, f"{CALL_MARK}\n")
        changed = True

    # Also add local normalization immediately before any YoutubeDL construction.
    out = []
    for line in lines:
        if "YoutubeDL(" in line and "def " not in line:
            prev = "".join(out[-8:])
            if "_normalize_threads_url_for_ytdlp" not in prev:
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f'{indent}if "url" in locals():\n')
                out.append(f'{indent}    url = _normalize_threads_url_for_ytdlp(url)\n')
                out.append(f'{indent}_force_enable_threads_ytdlp_plugin()\n')
                changed = True
        out.append(line)
    return "".join(out) if changed else src


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found. Run from project root.")
        return 2
    plugin = Path("plugins/threads/yt_dlp_plugins/extractor/threads.py")
    if not plugin.exists():
        print(f"ERROR: {plugin} not found. Copy plugins/ from the hotfix archive first.")
        return 2
    src = TARGET.read_text(encoding="utf-8")
    if not BACKUP.exists():
        BACKUP.write_text(src, encoding="utf-8")
        print("Backup created:", BACKUP)
    dst = patch(src)
    if dst == src:
        print("No changes needed.")
    else:
        TARGET.write_text(dst, encoding="utf-8")
        print("Patched", TARGET)
    print("Now run:")
    print("  python3 -m compileall -q services/downloader.py")
    print("  python3 bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
