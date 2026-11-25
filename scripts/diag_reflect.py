import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8096
BASE = "http://127.0.0.1:%d" % PORT
DATA = os.path.join(ROOT, "data-diag")


def wait_health():
    for _ in range(80):
        try:
            with urllib.request.urlopen(BASE + "/api/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    shutil.rmtree(DATA, ignore_errors=True)
    proc = subprocess.Popen([sys.executable, "app.py", "--port", str(PORT),
                             "--data-dir", DATA, "--quiet"], cwd=ROOT)
    try:
        assert wait_health(), "server down"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            page = b.new_page()
            msgs = []
            page.on("console", lambda m: msgs.append((m.type, m.text)))
            page.on("pageerror", lambda e: msgs.append(("pageerror", str(e))))
            page.goto(BASE + "/", wait_until="networkidle")
            for text in ("把周报的开头写出来", "散步 15 分钟"):
                page.fill("#goal-input", text)
                page.click("#goal-form button[type=submit]")
                page.wait_for_function(
                    "t => Array.from(document.querySelectorAll('.goal-text'))"
                    ".some(el => el.textContent === t)", arg=text)
            page.click('.tab[data-view="log"]')
            page.fill("#did-input", "写完了周报前三段")
            page.fill("#learned-input", "先骨架后润色")
            page.click("#checkin-form button[type=submit]")
            page.wait_for_selector(".timeline li")
            page.click('.tab[data-view="today"]')
            page.click(".goal-check")
            page.wait_for_selector(".goal.is-done")
            page.click("#reflect-btn")
            page.wait_for_timeout(3000)
            print("toast      :", repr(page.inner_text("#toast")))
            print("toast shown:", page.evaluate("!document.getElementById('toast').hidden"))
            print("card hidden:", page.evaluate("document.getElementById('card-body').hidden"))
            print("card text  :", repr(page.inner_text("#card-body")[:80]))
            print("state cards:", page.evaluate(
                "fetch('/api/state').then(r=>r.json()).then(d=>d.cards.length)"))
            print("console:")
            for t, m in msgs:
                print("   ", t, "|", m[:200])
            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
