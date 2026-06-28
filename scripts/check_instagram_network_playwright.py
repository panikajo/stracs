#!/usr/bin/env python3
"""Diagnose Instagram access from server + Playwright browsers."""
from __future__ import annotations

import asyncio
import socket
import ssl
import sys
import urllib.request

URLS = [
    "https://www.instagram.com/",
    "https://www.instagram.com/accounts/login/",
    "https://www.instagram.com/reel/DZZI166gJVp/",
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0"


def test_dns():
    print("== DNS ==")
    for host in ["www.instagram.com", "instagram.com"]:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            addrs = sorted({i[4][0] for i in infos})
            print(host, "->", ", ".join(addrs[:8]))
        except Exception as e:
            print(host, "ERROR", type(e).__name__, e)


def test_urllib():
    print("\n== HTTPS urllib ==")
    ctx = ssl.create_default_context()
    for url in URLS:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                body = r.read(200)
                print(url, "->", r.status, r.geturl(), "bytes", len(body))
        except Exception as e:
            print(url, "ERROR", type(e).__name__, e)


async def test_playwright():
    print("\n== Playwright ==")
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        print("playwright import ERROR:", type(e).__name__, e)
        return

    async with async_playwright() as p:
        for browser_name in ["firefox", "chromium"]:
            browser_type = getattr(p, browser_name)
            print(f"\n-- {browser_name} --")
            try:
                browser = await browser_type.launch(headless=True)
            except Exception as e:
                print("launch ERROR:", type(e).__name__, e)
                continue
            try:
                page = await browser.new_page(user_agent=UA, locale="en-US")
                page.set_default_timeout(30000)
                for url in URLS:
                    try:
                        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        print(url, "->", resp.status if resp else "no response", page.url)
                    except Exception as e:
                        print(url, "ERROR", type(e).__name__, str(e).split("\n")[0])
            finally:
                await browser.close()


def main():
    # Strip Slack angle brackets if copied as <https://...>
    for i, arg in enumerate(sys.argv):
        sys.argv[i] = arg.strip("<>")
    test_dns()
    test_urllib()
    asyncio.run(test_playwright())


if __name__ == "__main__":
    main()
