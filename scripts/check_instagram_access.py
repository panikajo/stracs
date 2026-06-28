"""Check Instagram cookies and yt-dlp access for one URL.

Run from the project root:
    python scripts/check_instagram_access.py https://www.instagram.com/p/DZ0one8IweY/
"""
from pathlib import Path
import subprocess
import sys
import time


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.instagram.com/p/DZ0one8IweY/"
    root = Path.cwd()
    cookie_candidates = [
        root / "cookies" / "instagram.txt",
        root / "cookies" / "cookies.txt",
        root / "instagram.txt",
    ]
    cookie = next((p for p in cookie_candidates if p.exists()), None)

    print("=== Instagram access diagnostic ===")
    print("Project:", root)
    print("URL:", url)
    print("Python:", sys.executable)

    if not cookie:
        print("\nERROR: cookies file not found.")
        print("Expected one of:")
        for p in cookie_candidates:
            print(" -", p)
        print("\nRun /refreshcookies in Telegram after installing Playwright browsers:")
        print("  python -m playwright install firefox")
        raise SystemExit(2)

    stat = cookie.stat()
    age_min = (time.time() - stat.st_mtime) / 60
    print("\nCookie file:", cookie)
    print("Size:", stat.st_size, "bytes")
    print("Modified:", f"{age_min:.1f} minutes ago")

    text = cookie.read_text(errors="ignore")[:5000]
    has_sessionid = "sessionid" in text
    print("Contains sessionid:", "YES" if has_sessionid else "NO")
    if stat.st_size < 100 or not has_sessionid:
        print("\nWARNING: cookie file looks invalid or not logged-in.")
        print("Open Instagram manually, login/pass checkpoint, then run /refreshcookies again.")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--cookies", str(cookie),
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "--add-header", "Accept-Language: en-US,en;q=0.9",
        "--no-warnings",
        "--dump-single-json",
        "--skip-download",
        url,
    ]
    print("\nRunning yt-dlp check...")
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    print("Exit code:", proc.returncode)
    if proc.returncode == 0:
        print("OK: yt-dlp can access this Instagram post with cookies.")
        print("First stdout chars:", proc.stdout[:500])
        raise SystemExit(0)

    print("\nFAILED: yt-dlp cannot access this post with current cookies.")
    print("--- stderr ---")
    print(proc.stderr[-2000:])
    print("--- stdout ---")
    print(proc.stdout[-1000:])
    print("\nIf stderr contains login/checkpoint/challenge/empty media response:")
    print("1) open Instagram manually with that account")
    print("2) make sure this exact post opens there")
    print("3) pass any checkpoint/challenge")
    print("4) run /refreshcookies")
    print("5) run this diagnostic again")
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
