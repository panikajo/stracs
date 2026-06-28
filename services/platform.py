"""Platform detection helpers for supported social links."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformInfo:
    name: str
    icon: str
    note: str = ""


PLATFORM_INFO = {
    "youtube": PlatformInfo("YouTube", "🔴", ""),
    "instagram": PlatformInfo("Instagram", "📸", ""),
    "tiktok": PlatformInfo("TikTok", "🎵", ""),
    "threads": PlatformInfo("Threads", "🧵", "Публичные посты/фото/видео Threads"),
    "unknown": PlatformInfo("Unknown", "🌐", ""),
}


def get_platform_info(platform: str) -> PlatformInfo:
    return PLATFORM_INFO.get(platform, PLATFORM_INFO["unknown"])


def detect_platform(url: str):
    """Return (platform, content_id) for supported URLs, else None."""
    if not url:
        return None
    url = str(url).strip().strip("<>").strip()
    if url.startswith("http") and "|" in url:
        url = url.split("|", 1)[0].strip("<>")
    m_threads = re.search(r"https?://(?:www\.)?threads\.(?:com|net)/(@[^/]+)/(post|media)/([^/?#>]+)", url, re.I)
    if m_threads:
        url = f"https://www.threads.net/{m_threads.group(1)}/{m_threads.group(2)}/{m_threads.group(3)}"

    # YouTube: normal, Shorts, youtu.be
    if re.search(r"(?:youtube\.com|youtu\.be)", url, re.I):
        m = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{6,})", url)
        return ("youtube", m.group(1) if m else "youtube")

    # Instagram: reel/post/tv/stories
    if re.search(r"instagram\.com", url, re.I):
        m = re.search(r"instagram\.com/(?:reel|p|tv|stories/[^/]+)/([^/?#]+)", url, re.I)
        return ("instagram", m.group(1) if m else "instagram")

    # TikTok: /@user/video/id, vm.tiktok.com redirects, etc.
    if re.search(r"(?:tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)", url, re.I):
        m = re.search(r"/video/(\d+)", url)
        return ("tiktok", m.group(1) if m else "tiktok")

    # Threads: /@user/post/ABC, /@user/media/ABC, or /t/ABC
    if re.search(r"threads\.(?:net|com)", url, re.I):
        m = re.search(r"threads\.(?:net|com)/(?:@[^/]+/(?:post|media)/|t/)([^/?#]+)", url, re.I)
        return ("threads", m.group(1) if m else "threads")

    return None
