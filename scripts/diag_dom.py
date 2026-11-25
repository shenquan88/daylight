import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8094
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


SCRIPT = """
() => {
  const out = [];
  document.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const bg = cs.backgroundColor;
    const isWarm = /rgb\\((2[0-9]{2}), (1[0-9]{2}|[0-9]{1,2}), ([0-9]{1,2})\\)/.test(bg);
    if (r.width > 0 && r.width < 16 && r.height > 8 && r.height < 40 && isWarm) {
      out.push({tag: el.tagName, id: el.id, cls: String(el.className).slice(0, 40),
                x: Math.round(r.left), y: Math.round(r.top),
                w: Math.round(r.width), h: Math.round(r.height), bg: bg});
    }
  });
  return out;
}
"""


def main():
    shutil.rmtree(DATA, ignore_errors=True)
    proc = subprocess.Popen([sys.executable, "app.py", "--port", str(PORT),
                             "--data-dir", DATA, "--quiet"], cwd=ROOT)
    try:
        assert wait_health()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            page = b.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(BASE + "/", wait_until="networkidle")
            found = page.evaluate(SCRIPT)
            print("warm slivers:", json.dumps(found, ensure_ascii=False, indent=2))
            print("heading text bbox:", page.evaluate("""() => {
                const h = document.getElementById('today-heading');
                const range = document.createRange();
                range.selectNodeContents(h);
                const r = range.getBoundingClientRect();
                return {left: Math.round(r.left), right: Math.round(r.right),
                        top: Math.round(r.top), bottom: Math.round(r.bottom)};
            }"""))
            page.screenshot(path=os.path.join(ROOT, "screenshots", "_diag_full.png"),
                            clip={"x": 180, "y": 140, "width": 620, "height": 120})
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
