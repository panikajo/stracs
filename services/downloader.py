import asyncio
import os
import json
import re
import glob
import logging
from dataclasses import dataclass
from typing import Optional
from config import config
import shutil
import sys

# Project root — all relative paths (plugins/, cookies/) resolve from here.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))








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
    """Normalize Threads URLs and add --plugin-dirs to yt-dlp CLI calls."""
    try:
        import os as _os
        from pathlib import Path as _Path
        if isinstance(cmd, (list, tuple)):
            parts = [str(x) for x in cmd]
            if not _threads_is_ytdlp_cmd(parts):
                return cmd
            # Add plugin dir only if local plugin exists and not already specified.
            # Use absolute path so it works regardless of working directory.
            plugin_dir_abs = _os.path.join(_PROJECT_ROOT, "plugins")
            plugin_file = _Path(_os.path.join(plugin_dir_abs, "threads", "yt_dlp_plugins", "extractor", "threads.py"))
            if plugin_file.exists() and "--plugin-dirs" not in parts:
                insert_at = 1
                # For `python -m yt_dlp ...`, insert after module name.
                if len(parts) >= 3 and parts[1] == "-m" and parts[2] in ("yt_dlp", "yt-dlp"):
                    insert_at = 3
                parts[insert_at:insert_at] = ["--plugin-dirs", plugin_dir_abs]
            parts = [_threads_normalize_cli_url(x) if "threads." in str(x).lower() else x for x in parts]
            return tuple(parts) if isinstance(cmd, tuple) else parts
        if isinstance(cmd, str) and ("yt-dlp" in cmd or "yt_dlp" in cmd) and "threads." in cmd:
            # Best effort for shell=True commands.
            import re as _re
            cmd = _re.sub(r"&lt;", "<", cmd)
            cmd = _re.sub(r"&gt;", ">", cmd)
            cmd = _re.sub(r"['\"]?<(?P<url>https?://(?:www\.)?threads\.(?:com|net)/[^>\s'\"]+)>['\"]?", lambda m: _threads_normalize_cli_url(m.group('url')), cmd)
            _abs_plugin_dir = _os.path.join(_PROJECT_ROOT, "plugins")
            if "--plugin-dirs" not in cmd and _Path(_os.path.join(_abs_plugin_dir, "threads", "yt_dlp_plugins", "extractor", "threads.py")).exists():
                cmd = cmd.replace("yt-dlp ", f"yt-dlp --plugin-dirs {_abs_plugin_dir} ", 1)
                cmd = cmd.replace("yt_dlp ", f"yt_dlp --plugin-dirs {_abs_plugin_dir} ", 1)
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

logger = logging.getLogger("smdownbot.downloader")

# Find yt-dlp: prefer venv copy, fallback to system
YTDLP = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
if not os.path.exists(YTDLP):
    YTDLP = shutil.which("yt-dlp") or "yt-dlp"


def _clean_source_url(u) -> str:
    """Strip tracking params and fragments from a media URL, keeping the
    canonical link.

    Instagram / TikTok carry the media id in the PATH, so the whole query
    string is junk and can be dropped:
        https://www.instagram.com/reel/DZaGtH9HY0S/?utm_source=ig_web_copy_link&igsh=...
            -> https://www.instagram.com/reel/DZaGtH9HY0S/
        https://www.tiktok.com/@user/video/12345?is_from_webapp=1
            -> https://www.tiktok.com/@user/video/12345

    YouTube /watch carries the id in the query (?v=...), so we keep only the
    'v' param and drop the rest (si, feature, list, t, etc.):
        https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share -> ...?v=dQw4w9WgXcQ
        https://youtu.be/dQw4w9WgXcQ?si=abcd -> https://youtu.be/dQw4w9WgXcQ
    """
    if not u:
        return u
    if not isinstance(u, str):
        u = str(u)
    u = u.strip()

    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parts = urlsplit(u)
        host = (parts.netloc or "").lower()
        # YouTube /watch keeps its id in ?v=
        if "youtube.com" in host and parts.path.rstrip("/") .endswith("/watch"):
            q = [(k, v) for k, v in parse_qsl(parts.query) if k == "v"]
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))
        # Everything else: id is in the path — drop query + fragment entirely.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        # Fallback: naive trim at '?' / '#'
        for sep in ("?", "#"):
            idx = u.find(sep)
            if idx != -1:
                u = u[:idx]
        return u


def _sanitize_title(title) -> str:
    """Make a yt-dlp title safe for a Telegram HTML caption.
    Removes broken/surrogate code points that render as � and strips
    control chars. HTML-escaping is done at send time in the handler."""
    if not title:
        return "Download"
    if not isinstance(title, str):
        title = str(title)
    # Drop lone surrogates and re-decode to clean UTF-8
    title = title.encode("utf-8", "ignore").decode("utf-8", "ignore")
    # Remove control characters (except normal whitespace)
    title = "".join(ch for ch in title if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    title = title.strip()
    return title or "Download"


@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[int] = None
    file_size: Optional[int] = None
    thumbnail: Optional[str] = None
    platform: Optional[str] = None
    error: Optional[str] = None
    formats: Optional[list] = None
    source_url: Optional[str] = None
    uploader_id: Optional[str] = None
    tags: Optional[list] = None
    description: Optional[str] = None
    audio_url: Optional[str] = None
    audio_title: Optional[str] = None
    audio_artist: Optional[str] = None

def _find_cookie_file(platform: str) -> Optional[str]:
    """Find the best cookie file for a platform, with fallbacks.

    Threads uses Instagram/Meta auth, so cookies/instagram.txt works as a
    fallback when cookies/threads.txt does not exist.
    """
    if platform == "tiktok":
        # TikTok: do NOT attach cookies — yt-dlp's challenge solver sets its own
        # short-lived cookies, and user cookies break them.
        return None
    candidates = [os.path.join(config.COOKIES_DIR, f"{platform}.txt")]
    if platform == "threads":
        # Threads shares auth with Instagram (Meta). Fall back to IG cookies.
        candidates.extend([
            os.path.join(config.COOKIES_DIR, "instagram.txt"),
            os.path.join(config.COOKIES_DIR, "meta.txt"),
            os.path.join(config.COOKIES_DIR, "cookies.txt"),
        ])
    for path in candidates:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
    return None


def _base_opts(platform: str = None) -> dict:
    opts = {
        "quiet": True,
        "no-warnings": True,
        "no-playlist": True,
        "output": os.path.join(config.DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        "socket-timeout": 30,
        "retries": 3,
    }
    cookie_file = _find_cookie_file(platform)
    if cookie_file:
        opts["cookies"] = cookie_file
    return opts

def _is_auth_error(stderr: str) -> bool:
    """Check if error indicates expired/invalid cookies."""
    auth_patterns = [
        "You need to log in",
        "login required",
        "authentication",
        "HTTP Error 401",
        "HTTP Error 403",
        "Private content",
    ]
    lower = stderr.lower()
    return any(p.lower() in lower for p in auth_patterns)


async def get_info(url: str, platform: str = None, _retry: bool = True) -> Optional[dict]:
    """Get video info without downloading."""
    cmd = [YTDLP, "--dump-json", "--no-download", "--no-playlist"]

    # Attach cookies with platform-aware fallback (Threads → Instagram).
    cookie_file = _find_cookie_file(platform)
    if cookie_file:
        cmd.extend(["--cookies", cookie_file])

    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace")
        if _retry and platform == "instagram" and _is_auth_error(err):
            logger.info("Auth error in get_info, auto-refreshing cookies...")
            from services.cookies import handle_auth_failure
            if await handle_auth_failure():
                return await get_info(url, platform, _retry=False)
        return None
    try:
        return json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None

async def download(url: str, platform: str = None, audio_only: bool = False, quality: str = "best") -> DownloadResult:
    """Download video/audio via yt-dlp."""
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
    opts = _base_opts(platform)

    if audio_only:
        opts.update({
            "format": "bestaudio/best",
            "extract-audio": True,
            "audio-format": "mp3",
            "audio-quality": "192",
        })
    else:
        if quality == "720":
            opts["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        elif quality == "480":
            opts["format"] = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
        else:
            opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    # TikTok: prefer no-watermark
    if platform == "tiktok":
        opts["format"] = "best"

    # Build command
    cmd = [YTDLP]
    for k, v in opts.items():
        flag = f"--{k.replace('_', '-')}"
        if isinstance(v, bool):
            if v:
                cmd.append(flag)
        elif isinstance(v, (str, int, float)):
            cmd.extend([flag, str(v)])
        elif isinstance(v, list):
            for item in v:
                cmd.extend([flag, json.dumps(item) if isinstance(item, dict) else str(item)])
        elif isinstance(v, dict):
            for dk, dv in v.items():
                cmd.extend([f"--{dk}", str(dv)])

    # Use a unique output template based on the video id so we can reliably
    # locate the file afterwards even when yt-dlp's after_move print is empty
    # (happens for single-file TikTok downloads that skip the merge/move step).
    cmd.extend([
        "--print", "after_move:filepath",
        "--print", "after_move:%(title)s",
        "--print", "after_move:%(duration)s",
        "--print", "after_move:%(thumbnail)s",
        "--print", "after_move:%(webpage_url)s",
        "--print", "after_move:%(uploader_id)s",
        "--print", "after_move:%(uploader)s",
        "--print", "after_move:%(tags)j",
        "--print", "after_move:%(description)j",
        "--no-simulate",
    ])
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(), timeout=config.YT_DLP_TIMEOUT
    )

    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace").strip().split("\n")[-1]
        # Auto-refresh cookies on auth failure
        if platform == "instagram" and _is_auth_error(err):
            logger.info("Auth error in download, auto-refreshing cookies...")
            from services.cookies import handle_auth_failure
            if await handle_auth_failure():
                # Retry download with fresh cookies
                cookie_file = os.path.join(config.COOKIES_DIR, f"{platform}.txt")
                if os.path.exists(cookie_file):
                    opts["cookies"] = cookie_file
                    cmd = [YTDLP]
                    for k, v in opts.items():
                        flag = f"--{k.replace('_', '-')}"
                        if isinstance(v, bool):
                            if v:
                                cmd.append(flag)
                        elif isinstance(v, (str, int, float)):
                            cmd.extend([flag, str(v)])
                        elif isinstance(v, list):
                            for item in v:
                                cmd.extend([flag, json.dumps(item) if isinstance(item, dict) else str(item)])
                        elif isinstance(v, dict):
                            for dk, dv in v.items():
                                cmd.extend([f"--{dk}", str(dv)])
                    cmd.extend(["--print", "after_move:filepath"])
                    cmd.append(url)

                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=config.YT_DLP_TIMEOUT
                    )
                    if proc.returncode == 0:
                        filepath = stdout.decode("utf-8", "replace").strip().split("\n")[-1]
                        if os.path.exists(filepath):
                            file_size = os.path.getsize(filepath)
                            info = await get_info(url, platform, _retry=False)
                            return DownloadResult(
                                success=True,
                                file_path=filepath,
                                title=_sanitize_title(info.get("title", "Download") if info else "Download")[:100],
                                duration=info.get("duration") if info else None,
                                file_size=file_size,
                                thumbnail=info.get("thumbnail") if info else None,
                                platform=platform,
                                description=info.get("description") if info else None,
                            )
                    err = stderr.decode("utf-8", "replace").strip().split("\n")[-1]
        return DownloadResult(success=False, error=err[:200])

    # Capture full stderr so failures show the real yt-dlp reason instead of
    # a generic "File not found".
    full_stderr = stderr.decode("utf-8", "replace").strip()
    # Keep ALL lines including blanks so positional indices match --print order.
    # Only the filepath resolver and metadata parser rely on specific positions.
    _raw_lines = stdout.decode("utf-8", "replace").strip().split("\n")
    out_lines = _raw_lines  # preserve blank lines for correct index alignment

    # Resolve the downloaded file. The first non-empty stdout line should be the
    # filepath from --print after_move:filepath, but for some extractors (TikTok
    # single-file, no post-processing) after_move can print an empty/old path.
    # Fall back to globbing the download dir for the video id from the URL.
    def _resolve_filepath():
        if out_lines and out_lines[0].strip() and os.path.exists(out_lines[0].strip()):
            return out_lines[0].strip()
        # Fallback: find by video id in the output dir
        m = re.search(r"/video/(\d+)|/(\d{8,})", url) or re.search(r"(\d{8,})", url)
        vid = next((g for g in (m.groups() if m else []) if g), None)
        if vid:
            matches = glob.glob(os.path.join(config.DOWNLOAD_DIR, f"{vid}.*"))
            if matches:
                return max(matches, key=os.path.getmtime)
        # Last resort: newest file in the download dir created just now
        all_files = glob.glob(os.path.join(config.DOWNLOAD_DIR, "*"))
        if all_files:
            newest = max(all_files, key=os.path.getmtime)
            import time as _t
            if _t.time() - os.path.getmtime(newest) < config.YT_DLP_TIMEOUT:
                return newest
        return None

    filepath = _resolve_filepath()
    if not filepath or not os.path.exists(filepath):
        # yt-dlp may have exited 0 but produced no file (e.g. extractor warning).
        reason = full_stderr.split("\n")[-1] if full_stderr else "File not found after download"
        return DownloadResult(success=False, error=reason[:200])

    file_size = os.path.getsize(filepath)

    # Parse metadata printed in the SAME yt-dlp pass.
    # out_lines layout (in --print order):
    #   [0:filepath, 1:title, 2:duration, 3:thumbnail, 4:webpage_url,
    #    5:uploader_id, 6:uploader, 7:tags_json, 8:description_json]
    title = "Download"
    duration = None
    thumbnail = None
    source_url = None
    uploader_id = None
    tags = None
    description = None

    def _na(v):
        v = (v or "").strip()
        return None if v in ("", "NA", "None") else v

    if len(out_lines) >= 8:
        title = _sanitize_title(out_lines[1] or "Download")
        dur_raw = (out_lines[2] or "").strip()
        try:
            duration = int(float(dur_raw)) if dur_raw and dur_raw != "NA" else None
        except ValueError:
            duration = None
        thumbnail = _na(out_lines[3])
        source_url = _clean_source_url(_na(out_lines[4]))
        uploader_id = _na(out_lines[5])
        # tags printed as a JSON array via %(tags)j
        try:
            parsed = json.loads(out_lines[7]) if out_lines[7] else None
            if isinstance(parsed, list):
                tags = [str(t) for t in parsed if t]
        except (json.JSONDecodeError, IndexError):
            tags = None
        # description printed as JSON string via %(description)j — newlines are
        # escaped, so it always occupies a single output line.
        if len(out_lines) >= 9:
            try:
                desc_raw = json.loads(out_lines[8]) if out_lines[8] else None
                if isinstance(desc_raw, str) and desc_raw.strip() and desc_raw.strip() != "NA":
                    description = desc_raw.strip()
            except (json.JSONDecodeError, IndexError):
                description = None
    elif len(out_lines) >= 4:
        # Older/partial print (fallback): [filepath, title, duration, thumbnail]
        title = _sanitize_title(out_lines[-3] or "Download")
        dur_raw = out_lines[-2].strip()
        try:
            duration = int(float(dur_raw)) if dur_raw and dur_raw != "NA" else None
        except ValueError:
            duration = None
        thumbnail = _na(out_lines[-1])

    # Fallback: derive source_url / uploader_id from the original URL for TikTok/IG
    if not source_url:
        source_url = url
    source_url = _clean_source_url(source_url)
    if not uploader_id:
        m = re.search(r"(?:tiktok\.com|instagram\.com|threads\.net)/@?([\w.]+)", url)
        if m:
            uploader_id = m.group(1)

    # If description or audio info is missing, try to fetch via get_info (dump-json).
    audio_url = None
    audio_title = None
    audio_artist = None
    if description is None or platform == "threads":
        try:
            _info = await get_info(url, platform, _retry=False)
            if _info:
                if description is None and _info.get("description"):
                    description = str(_info["description"]).strip()
                # Audio track info (Threads posts with background music)
                if _info.get("audio_url"):
                    audio_url = str(_info["audio_url"])
                    audio_title = str(_info["audio_title"]) if _info.get("audio_title") else None
                    audio_artist = str(_info["audio_artist"]) if _info.get("audio_artist") else None
        except Exception:
            pass

    return DownloadResult(
        success=True,
        file_path=filepath,
        title=_sanitize_title(title)[:100],
        duration=duration,
        file_size=file_size,
        thumbnail=thumbnail,
        platform=platform,
        source_url=source_url,
        uploader_id=uploader_id,
        tags=tags,
        description=description,
        audio_url=audio_url,
        audio_title=audio_title,
        audio_artist=audio_artist,
    )

def cleanup_file(path: str):
    """Delete downloaded file."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

def cleanup_old_files(max_age_hours: int = 1):
    """Clean files older than max_age_hours."""
    import time
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    for f in glob.glob(os.path.join(config.DOWNLOAD_DIR, "*")):
        if os.path.getmtime(f) < cutoff:
            try:
                os.remove(f)
            except OSError:
                pass


# ─── Gallery / carousel support ──────────────────────────────────


@dataclass
class GalleryResult:
    """Result of downloading a multi-photo carousel / slideshow post."""
    success: bool
    photos: list[str] = None       # local file paths to images
    videos: list[str] = None       # local file paths to videos
    audio_path: str = None         # optional background audio
    title: str = "Gallery"
    source_url: str = None
    uploader_id: str = None
    tags: list[str] = None
    description: str = None
    error: str = None
    platform: str = None
    thumbnail: str = None
    audio_url: str = None
    audio_title: str = None
    audio_artist: str = None


def is_photo_post(info: dict) -> bool:
    """Detect if yt-dlp info dict represents a photo carousel / slideshow."""
    if not info:
        return False

    IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}

    def _looks_like_image(entry):
        if not entry:
            return False
        ext = (entry.get("ext") or "").lower()
        if ext in IMAGE_EXTS:
            return True
        # No formats key + direct URL → likely an image
        url = entry.get("url") or ""
        if url and not entry.get("formats"):
            # Check URL extension
            path = url.split("?")[0].split("#")[0]
            if any(path.lower().endswith(f".{e}") for e in IMAGE_EXTS):
                return True
        # Some extractors mark images with vcodec=none and acodec=none
        if entry.get("vcodec") == "none" and entry.get("acodec") == "none":
            return True
        return False

    # Playlist/carousel with entries
    entries = info.get("entries")
    if entries:
        return any(_looks_like_image(e) for e in entries)
    # Playlist type even without explicit entries
    if info.get("_type") == "playlist":
        return True
    # Single image post
    return _looks_like_image(info)


async def download_gallery(url: str, platform: str = None) -> Optional[GalleryResult]:
    """Download all items from a carousel/gallery post.

    Uses yt-dlp WITHOUT --no-playlist so every carousel item is fetched.
    Returns a GalleryResult with lists of photo and video paths.
    """
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)

    # Get metadata (with playlist to see the full structure).
    info = await _get_info_with_playlist(url, platform)
    description = None
    source_url = url
    uploader_id = None
    tags = None
    title = "Gallery"
    audio_url = None
    audio_title = None
    audio_artist = None
    if info:
        description = info.get("description")
        title = info.get("title") or "Gallery"
        uploader_id = info.get("uploader_id") or info.get("uploader")
        source_url = info.get("webpage_url") or url
        raw_tags = info.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags if t]
        # Audio track (Threads posts with background music)
        if info.get("audio_url"):
            audio_url = str(info["audio_url"])
            audio_title = str(info["audio_title"]) if info.get("audio_title") else None
            audio_artist = str(info["audio_artist"]) if info.get("audio_artist") else None

    # Download ALL carousel items in a single yt-dlp pass (no --no-playlist).
    opts = _base_opts(platform)
    opts.pop("no-playlist", None)  # allow playlist/carousel
    gallery_template = os.path.join(
        config.DOWNLOAD_DIR,
        f"gal_{os.getpid()}_%(playlist_index|0)s_%(id)s.%(ext)s",
    )
    opts["output"] = gallery_template

    cmd = [YTDLP]
    for k, v in opts.items():
        flag = f"--{k.replace('_', '-')}"
        if isinstance(v, bool):
            if v:
                cmd.append(flag)
        elif isinstance(v, (str, int, float)):
            cmd.extend([flag, str(v)])

    # Print filepath + ext for each downloaded item (2 lines per item).
    cmd.extend([
        "--print", "after_move:filepath",
        "--print", "after_move:%(ext)s",
        "--no-simulate",
    ])
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=config.YT_DLP_TIMEOUT,
        )
    except Exception as e:
        return GalleryResult(success=False, error=str(e)[:200])

    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace").strip().split("\n")[-1] if stderr else "yt-dlp error"
        return GalleryResult(success=False, error=err[:200])

    raw_lines = stdout.decode("utf-8", "replace").strip().split("\n")

    # Parse output in pairs: (filepath, ext)
    photos = []
    videos = []
    IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff"}

    i = 0
    while i < len(raw_lines) - 1:
        fpath = raw_lines[i].strip()
        ext = raw_lines[i + 1].strip().lower()
        i += 2

        if not fpath or not os.path.exists(fpath):
            continue
        if os.path.getsize(fpath) == 0:
            os.remove(fpath)
            continue

        if ext in IMAGE_EXTS:
            photos.append(fpath)
        else:
            videos.append(fpath)

    # Fallback: if no paired output, look for any gallery files created.
    if not photos and not videos:
        prefix = f"gal_{os.getpid()}_"
        for f in sorted(glob.glob(os.path.join(config.DOWNLOAD_DIR, prefix + "*"))):
            if not os.path.getsize(f):
                continue
            fext = os.path.splitext(f)[1].lstrip(".").lower()
            if fext in IMAGE_EXTS:
                photos.append(f)
            else:
                videos.append(f)

    if not photos and not videos:
        return GalleryResult(success=False, error="No media downloaded from gallery")

    # If description is still missing, try a separate get_info (dump-json) call
    # to pick it up. Carousel children often lack the parent's text field.
    if not description:
        try:
            _info = await get_info(url, platform, _retry=False)
            if _info and _info.get("description"):
                description = str(_info["description"]).strip()
            elif _info and _info.get("title"):
                _t = str(_info["title"]).strip()
                if _t and not _t.startswith("Threads post ") and len(_t) > 5:
                    description = _t
        except Exception:
            pass

    return GalleryResult(
        success=True,
        photos=photos,
        videos=videos,
        title=title,
        source_url=source_url,
        uploader_id=uploader_id,
        tags=tags,
        description=description,
        platform=platform,
        audio_url=audio_url,
        audio_title=audio_title,
        audio_artist=audio_artist,
    )


async def _get_info_with_playlist(url: str, platform: str = None) -> Optional[dict]:
    """Like get_info but WITHOUT --no-playlist (for carousel posts)."""
    cmd = [YTDLP, "--dump-json", "--no-download"]

    cookie_file = _find_cookie_file(platform)
    if cookie_file:
        cmd.extend(["--cookies", cookie_file])

    # Plugin dirs
    plugin_dir = os.path.join(_PROJECT_ROOT, "plugins")
    if os.path.isdir(plugin_dir):
        cmd.extend(["--plugin-dirs", plugin_dir])

    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        return None
    raw = stdout.decode("utf-8", "replace").strip()
    # Multiple JSON objects = playlist entries — wrap them
    lines = raw.split("\n")
    entries = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            entries.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]
    # Multiple entries → synthesize a playlist dict
    first = entries[0]
    # Try to find a description from any entry (carousel children may not carry
    # the parent text, but the first or title-bearing entry sometimes does).
    desc = None
    for e in entries:
        d = e.get("description")
        if d and isinstance(d, str) and d.strip():
            desc = d.strip()
            break
    # Fallback: some plugins put the text as the title when description is empty.
    if not desc:
        for e in entries:
            t = e.get("title") or ""
            if t and not t.startswith("Threads post ") and len(t) > 5:
                desc = t.strip()
                break
    return {
        "_type": "playlist",
        "title": first.get("title", "Gallery"),
        "description": desc,
        "uploader_id": first.get("uploader_id"),
        "uploader": first.get("uploader"),
        "webpage_url": first.get("webpage_url"),
        "tags": first.get("tags"),
        "entries": entries,
    }


async def build_slideshow(*args, **kwargs):
    """Placeholder — slideshow rendering not yet implemented."""
    return None


def cleanup_gallery(gallery: GalleryResult):
    """Clean up downloaded gallery files."""
    if gallery is None:
        return
    for f in (gallery.photos or []) + (gallery.videos or []):
        try:
            if f and os.path.exists(f):
                os.remove(f)
        except OSError:
            pass
    if gallery.audio_path:
        try:
            os.remove(gallery.audio_path)
        except OSError:
            pass


def split_video(file_path: str, max_size_mb: int = 48) -> list[str]:
    """Split a video into parts that fit under max_size_mb.
    Returns list of part file paths."""
    import subprocess
    
    file_size = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024
    
    if file_size <= max_bytes:
        return [file_path]
    
    # Get video duration
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", file_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())
    
    # Calculate number of parts needed
    num_parts = int(file_size / max_bytes) + 1
    segment_duration = duration / num_parts
    
    # Split using ffmpeg
    base, ext = os.path.splitext(file_path)
    pattern = f"{base}_part%d{ext}"
    
    subprocess.run([
        "ffmpeg", "-i", file_path,
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(segment_duration),
        "-reset_timestamps", "1",
        pattern
    ], capture_output=True, check=True)
    
    # Collect part files
    parts = sorted(glob.glob(f"{base}_part*{ext}"))
    return parts if parts else [file_path]
