"""Drive the real UI in Chrome, capture screenshots, and report console errors.

Playwright uses the locally installed Chrome (channel="chrome"), so nothing has
to be downloaded. Data goes to `data-demo/` so the screenshots show a clean run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8098
BASE = "http://127.0.0.1:%d" % PORT
DATA_DIR = os.path.join(ROOT, "data-demo")
SHOTS = os.path.join(ROOT, "screenshots")

problems = []


def call(path):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.status, resp.read().decode("utf-8")


def start_server():
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(PORT), "--data-dir", DATA_DIR, "--quiet"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8",
    )
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            status, _ = call("/api/health")
            if status == 200:
                return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise SystemExit("server never became healthy")


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    proc = start_server()
    console_problems = []
    shots = []

    def shoot(page, name, full_page=True, settle=500):
        """Let view-transition animations finish before capturing."""
        page.wait_for_timeout(settle)
        path = os.path.join(SHOTS, name)
        page.screenshot(path=path, full_page=full_page)
        shots.append(path)
        dims = page.viewport_size
        print("    shot %s (viewport %sx%s)" % (name, dims["width"], dims["height"]))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000},
                                      device_scale_factor=1, locale="zh-CN")
            page = ctx.new_page()

            def on_console(msg):
                if msg.type in ("error", "warning"):
                    console_problems.append("%s: %s" % (msg.type, msg.text))

            page.on("console", on_console)
            page.on("pageerror", lambda err: console_problems.append("pageerror: %s" % err))
            page.on("requestfailed", lambda req: console_problems.append(
                "requestfailed: %s %s" % (req.url, req.failure)))

            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_selector("#mode-badge")
            mode = page.inner_text("#mode-badge")
            date = page.inner_text("#today-date")
            print("mode badge :", mode)
            print("today      :", date)

            shoot(page, "01-today-empty.png")

            # add two goals through the real form
            for text in ("把周报的开头写出来", "散步 15 分钟"):
                page.fill("#goal-input", text)
                page.click("#goal-form button[type=submit]")
                page.wait_for_function(
                    "t => Array.from(document.querySelectorAll('.goal-text'))"
                    ".some(el => el.textContent === t)", arg=text)
            print("goals added:", page.locator(".goal").count())

            # one check-in through the real form
            page.click('.tab[data-view="log"]')
            page.fill("#did-input", "写完了周报前三段，用的时间比预计短")
            page.fill("#learned-input", "先写骨架比先润色快得多")
            page.click("#checkin-form button[type=submit]")
            page.wait_for_selector(".timeline li")
            print("timeline items:", page.locator(".timeline li").count())

            # complete the first goal
            page.click('.tab[data-view="today"]')
            page.click(".goal-check")
            page.wait_for_selector(".goal.is-done")
            print("progress:", page.inner_text("#progress-percent"),
                  "|", page.inner_text("#progress-line"))

            # generate the daily card
            page.click("#reflect-btn")
            page.wait_for_selector("#card-body:not([hidden])")
            card = page.inner_text("#card-body")
            print("card first line:", card.splitlines()[0] if card else "(empty)")

            shoot(page, "02-today-after-record.png")

            # garden
            page.click('.tab[data-view="garden"]')
            page.wait_for_selector(".plant")
            shoot(page, "03-garden.png")

            page.click(".plant")
            page.wait_for_selector("#plant-modal:not([hidden])")
            shoot(page, "04-plant-detail.png", full_page=False)
            page.click("#plant-close")

            # about / persistence
            page.click('.tab[data-view="about"]')
            page.wait_for_function(
                "() => { const el = document.getElementById('fact-db');"
                " return el && el.textContent.trim().length > 3; }")
            print("db shown   :", page.inner_text("#fact-db"))
            shoot(page, "05-about-persistence.png")
            ctx.close()

            # mobile viewport
            mctx = browser.new_context(viewport={"width": 390, "height": 844},
                                       device_scale_factor=2, locale="zh-CN",
                                       is_mobile=True, has_touch=True)
            mpage = mctx.new_page()
            mpage.on("console", lambda msg: console_problems.append(
                "mobile %s: %s" % (msg.type, msg.text)) if msg.type == "error" else None)
            mpage.on("pageerror", lambda err: console_problems.append("mobile pageerror: %s" % err))
            mpage.goto(BASE + "/", wait_until="networkidle")
            mpage.wait_for_selector("#goal-list")
            shoot(mpage, "06-mobile-today.png")
            mctx.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\nscreenshots:")
    for path in shots:
        print("  %s  (%d bytes)" % (path, os.path.getsize(path)))
    print("\nconsole problems: %d" % len(console_problems))
    for item in console_problems:
        print("  - " + item)
    if console_problems:
        problems.extend(console_problems)
    return 0 if not problems else 3


if __name__ == "__main__":
    sys.exit(main())
