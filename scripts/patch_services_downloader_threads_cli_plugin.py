#!/usr/bin/env python3
"""Patch services/downloader.py for yt-dlp CLI/subprocess Threads plugin support.

Use when:
- scripts/check_threads_runtime.py works with [threads]
- services/downloader.py has no YoutubeDL/extract_info usages
- bot still says Unsupported URL for Threads

This monkey-patches subprocess/asyncio process launchers inside services.downloader:
- normalizes Threads URLs in command args
- adds `--plugin-dirs plugins` to yt-dlp CLI calls
"""
from __future__ import annotations

from pathlib import Path

TARGET = Path("services/downloader.py")
BACKUP = Path("services/downloader.py.bak_threads_cli_plugin")
MARK = "def _threads_prepare_yt_dlp_cli_cmd("
INSTALL_MARK = "_threads_install_cli_plugin_patch()"

HELPER = r'''

# --- Threads yt-dlp CLI plugin support: injected by Viktor ---
def _threads_normalize_cli_url(value):
    try:
        import re as _re
        u = str(value or "").replace("&lt;", "<").replace("&gt;", ">").strip().strip("'\"").strip().strip("<>").strip()
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
        return value


def _threads_is_ytdlp_cmd(parts):
    try:
        joined = " ".join(str(x) for x in parts[:4]).lower()
        return (
            "yt-dlp" in joined
            or "yt_dlp" in joined
            or "yt-dlp.exe" in joined
        )
    except Exception:
        return False


def _threads_prepare_yt_dlp_cli_cmd(cmd):
    """Normalize Threads URLs and add --plugin-dirs plugins to yt-dlp CLI calls."""
    try:
        import os as _os
        from pathlib import Path as _Path
        if isinstance(cmd, (list, tuple)):
            parts = [str(x) for x in cmd]
            if not _threads_is_ytdlp_cmd(parts):
                return cmd
            # Add plugin dir only if local plugin exists and not already specified.
            plugin_file = _Path("plugins/threads/yt_dlp_plugins/extractor/threads.py")
            if plugin_file.exists() and "--plugin-dirs" not in parts:
                insert_at = 1
                # For `python -m yt_dlp ...`, insert after module name.
                if len(parts) >= 3 and parts[1] == "-m" and parts[2] in ("yt_dlp", "yt-dlp"):
                    insert_at = 3
                parts[insert_at:insert_at] = ["--plugin-dirs", "plugins"]
            parts = [_threads_normalize_cli_url(x) if "threads." in str(x).lower() else x for x in parts]
            return tuple(parts) if isinstance(cmd, tuple) else parts
        if isinstance(cmd, str) and ("yt-dlp" in cmd or "yt_dlp" in cmd) and "threads." in cmd:
            # Best effort for shell=True commands.
            import re as _re
            cmd = _re.sub(r"&lt;", "<", cmd)
            cmd = _re.sub(r"&gt;", ">", cmd)
            cmd = _re.sub(r"['\"]?<(?P<url>https?://(?:www\.)?threads\.(?:com|net)/[^>\s'\"]+)>['\"]?", lambda m: _threads_normalize_cli_url(m.group('url')), cmd)
            if "--plugin-dirs" not in cmd and _Path("plugins/threads/yt_dlp_plugins/extractor/threads.py").exists():
                cmd = cmd.replace("yt-dlp ", "yt-dlp --plugin-dirs plugins ", 1)
                cmd = cmd.replace("yt_dlp ", "yt_dlp --plugin-dirs plugins ", 1)
            return cmd
    except Exception:
        return cmd
    return cmd


def _threads_install_cli_plugin_patch():
    """Monkey-patch subprocess/asyncio launchers used by CLI-based downloaders."""
    try:
        import subprocess as _subprocess
        if not getattr(_subprocess, "_threads_cli_plugin_patched", False):
            _orig_run = _subprocess.run
            _orig_popen = _subprocess.Popen
            _orig_call = _subprocess.call
            _orig_check_call = _subprocess.check_call
            _orig_check_output = _subprocess.check_output

            def _run(cmd, *args, **kwargs):
                return _orig_run(_threads_prepare_yt_dlp_cli_cmd(cmd), *args, **kwargs)
            def _popen(cmd, *args, **kwargs):
                return _orig_popen(_threads_prepare_yt_dlp_cli_cmd(cmd), *args, **kwargs)
            def _call(cmd, *args, **kwargs):
                return _orig_call(_threads_prepare_yt_dlp_cli_cmd(cmd), *args, **kwargs)
            def _check_call(cmd, *args, **kwargs):
                return _orig_check_call(_threads_prepare_yt_dlp_cli_cmd(cmd), *args, **kwargs)
            def _check_output(cmd, *args, **kwargs):
                return _orig_check_output(_threads_prepare_yt_dlp_cli_cmd(cmd), *args, **kwargs)

            _subprocess.run = _run
            _subprocess.Popen = _popen
            _subprocess.call = _call
            _subprocess.check_call = _check_call
            _subprocess.check_output = _check_output
            _subprocess._threads_cli_plugin_patched = True
    except Exception:
        pass

    try:
        import asyncio as _asyncio
        if not getattr(_asyncio, "_threads_cli_plugin_patched", False):
            _orig_exec = _asyncio.create_subprocess_exec
            _orig_shell = _asyncio.create_subprocess_shell

            async def _exec(*cmd, **kwargs):
                prepared = _threads_prepare_yt_dlp_cli_cmd(list(cmd))
                if isinstance(prepared, (list, tuple)):
                    return await _orig_exec(*prepared, **kwargs)
                return await _orig_exec(*cmd, **kwargs)

            async def _shell(cmd, *args, **kwargs):
                return await _orig_shell(_threads_prepare_yt_dlp_cli_cmd(cmd), *args, **kwargs)

            _asyncio.create_subprocess_exec = _exec
            _asyncio.create_subprocess_shell = _shell
            _asyncio._threads_cli_plugin_patched = True
    except Exception:
        pass


_threads_install_cli_plugin_patch()
# --- /Threads yt-dlp CLI plugin support ---
'''


def find_insert_at(lines: list[str]) -> int:
    insert_at = 0
    in_docstring = False
    quote = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and (stripped.startswith('"""') or stripped.startswith("'''")):
            quote = stripped[:3]
            if stripped.count(quote) == 1:
                in_docstring = True
            insert_at = i + 1
            continue
        if in_docstring:
            insert_at = i + 1
            if quote and quote in stripped:
                in_docstring = False
            continue
        if stripped.startswith("import ") or stripped.startswith("from ") or stripped == "" or stripped.startswith("#"):
            insert_at = i + 1
            continue
        break
    return insert_at


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found. Run from project root.")
        return 2
    plugin = Path("plugins/threads/yt_dlp_plugins/extractor/threads.py")
    if not plugin.exists():
        print(f"ERROR: {plugin} not found. Copy plugins/ from v3 archive first.")
        return 2
    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("No changes needed: CLI plugin patch already installed.")
        return 0
    if not BACKUP.exists():
        BACKUP.write_text(src, encoding="utf-8")
        print("Backup created:", BACKUP)
    lines = src.splitlines(True)
    idx = find_insert_at(lines)
    lines.insert(idx, HELPER + "\n")
    TARGET.write_text("".join(lines), encoding="utf-8")
    print("Patched", TARGET, "for yt-dlp CLI/subprocess Threads plugin support.")
    print("Now run:")
    print("  python3 -m compileall -q services/downloader.py")
    print("  python3 bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
