from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    page.on("console", lambda msg: print(f"BROWSER CONSOLE [{msg.type}]: {msg.text}"))
    page.on("pageerror", lambda err: print(f"BROWSER UNCAUGHT ERROR: {err}"))

    page.goto("http://127.0.0.1:5000/")
    page.wait_for_load_state("networkidle")

    if page.locator("#username").is_visible():
        page.fill("#username", "admin")
        page.fill("#password", "admin")
        page.click(".btn-login-main")
        page.wait_for_timeout(1000)

    # Click AI Vision tab
    page.click("button.tab-btn:has-text('AI Vision')")
    page.wait_for_timeout(1000)

    # Click Validation Test button
    page.click("button.vision-sub-btn:has-text('Validation Test')")
    page.wait_for_timeout(1000)

    browser.close()
