"""Patch services/downloader.py so free video quality really means <=480p.

Run from the project root:
    python3 scripts/patch_services_downloader_480.py

This script is intentionally conservative: if it cannot find the common format
block, it prints the exact replacement snippet instead of guessing.
"""
from pathlib import Path

p = Path("services/downloader.py")
if not p.exists():
    raise SystemExit("services/downloader.py not found. Run this from the bot project root.")

s = p.read_text()
replacement = '''if audio_only:
        opts["format"] = "bestaudio/best"
    elif quality == "480":
        # Free quality: never download above 480p when yt-dlp exposes heights.
        opts["format"] = (
            "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=480][ext=mp4]/best[height<=480]/best"
        )
    elif quality == "720":
        opts["format"] = (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=720][ext=mp4]/best[height<=720]/best"
        )
    elif quality == "1080":
        opts["format"] = (
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=1080][ext=mp4]/best[height<=1080]/best"
        )
    elif quality == "4k":
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"'''

if 'quality == "480"' not in s:
    candidates = [
        '''if audio_only:
        opts["format"] = "bestaudio/best"
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"''',
        '''if audio_only:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"''',
    ]
    for old in candidates:
        if old in s:
            s = s.replace(old, replacement, 1)
            break
    else:
        print("Could not patch automatically. Put this block inside download() after opts = _base_opts(platform):\n")
        print(replacement)
        raise SystemExit(2)

# Important: some older code overwrote every TikTok video with opts["format"] = "best".
# Keep that behavior only for unrestricted best quality, not for 480/720/1080.
s = s.replace(
    'if platform == "tiktok" and not audio_only:\n        if watermark:',
    'if platform == "tiktok" and not audio_only and quality in ("best", None):\n        if watermark:'
)
s = s.replace(
    'if platform == "tiktok":\n        opts["format"] = "best"',
    'if platform == "tiktok" and not audio_only and quality in ("best", None):\n        opts["format"] = "best"'
)

p.write_text(s)
print("OK: services/downloader.py patched for real free 480p quality.")
