#!/usr/bin/env python3
"""Small text patch for services/cookies.py: make page.goto less fragile.

It backs up services/cookies.py and replaces common Instagram login goto calls
from wait_until='load' to wait_until='domcontentloaded' with timeout=60000.
This helps when Firefox throws NS_ERROR_NET_EMPTY_RESPONSE during full load.
"""
from __future__ import annotations
from pathlib import Path
import re

p = Path("services/cookies.py")
if not p.exists():
    raise SystemExit("ERROR: services/cookies.py not found. Run from project root.")

src = p.read_text(encoding="utf-8")
backup = p.with_suffix(".py.bak_playwright_retry")
if not backup.exists():
    backup.write_text(src, encoding="utf-8")
    print("Backup:", backup)

new = src
# Normalize wait_until load/networkidle to domcontentloaded for Instagram login.
new = re.sub(r"wait_until\s*=\s*['\"](?:load|networkidle)['\"]", "wait_until='domcontentloaded'", new)
# If page.goto has no timeout, add a longer timeout for accounts/login calls.
new = re.sub(
    r"page\.goto\(([^\n]*instagram\.com/accounts/login/[^\n]*?)(\))",
    lambda m: "page.goto(" + (m.group(1) + ", timeout=60000" if "timeout=" not in m.group(1) else m.group(1)) + m.group(2),
    new,
)
# Same for www.instagram.com if login URL is built from variable and timeout missing is hard to detect: leave safe.

if new == src:
    print("No automatic changes made. Open services/cookies.py and change page.goto wait_until='load' to 'domcontentloaded'.")
else:
    p.write_text(new, encoding="utf-8")
    print("Patched:", p)
    print("Run: python3 -m compileall -q services/cookies.py")
