#!/usr/bin/env python3
"""Patch services/downloader.py to load the local Threads yt-dlp extractor plugin."""
from __future__ import annotations

from pathlib import Path

TARGET = Path("services/downloader.py")
BACKUP = Path("services/downloader.py.bak_threads_plugin")
HELPER_MARK = "def _enable_threads_ytdlp_plugin("
HELPER = '''

def _enable_threads_ytdlp_plugin() -> None:
    """Enable local yt-dlp Threads extractor plugin from ./plugins.

    Required when installed yt-dlp prints:
      [generic] Extracting URL ... ERROR: Unsupported URL
    """
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


def inject_calls(src: str) -> tuple[str, int]:
    lines = src.splitlines(True)
    out = []
    count = 0
    for line in lines:
        if "yt_dlp.YoutubeDL(" in line:
            prev = "".join(out[-8:])
            if "_enable_threads_ytdlp_plugin()" not in prev:
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f"{indent}_enable_threads_ytdlp_plugin()\n")
                count += 1
        out.append(line)
    return "".join(out), count


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found. Run this from project root.")
        return 2
    if not Path("plugins/threads/yt_dlp_plugins/extractor/threads.py").exists():
        print("ERROR: local plugin not found: plugins/threads/yt_dlp_plugins/extractor/threads.py")
        print("Copy the plugins/ folder from the hotfix archive first.")
        return 2
    src = TARGET.read_text(encoding="utf-8")
    if not BACKUP.exists():
        BACKUP.write_text(src, encoding="utf-8")
        print("Backup created:", BACKUP)
    src2 = inject_helper(src)
    src3, count = inject_calls(src2)
    if src3 == src:
        print("No changes needed.")
    else:
        TARGET.write_text(src3, encoding="utf-8")
        print(f"Patched {TARGET}; enabled Threads plugin before {count} YoutubeDL calls.")
    print("Now run: python3 -m compileall -q services/downloader.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
