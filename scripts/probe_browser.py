import sys

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:  # pragma: no cover
    print("NO_PLAYWRIGHT", type(exc).__name__, exc)
    sys.exit(1)

with sync_playwright() as p:
    try:
        browser = p.chromium.launch()
    except Exception as exc:
        print("NO_BROWSER", type(exc).__name__, str(exc)[:300])
        sys.exit(2)
    page = browser.new_page()
    page.set_content("<h1 id=t>ok</h1>")
    print("BROWSER_OK", page.inner_text("#t"), browser.version)
    browser.close()
