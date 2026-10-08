from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto('http://127.0.0.1:5000')
    page.fill('#username', 'admin')
    page.fill('#password', 'admin')
    page.click('.btn-login-main')
    page.wait_for_timeout(1000)
    page.evaluate("switchTab('master-hub')")
    page.wait_for_timeout(500)
    btn = page.locator(".sub-tab-btn[onclick*='bin-master']").first
    print("Bin btn text:", btn.inner_text())
    btn.click()
    page.wait_for_timeout(500)
    bin_sub = page.locator("#bin-master-sub")
    print("Bin sub is_visible:", bin_sub.is_visible())
    print("Bin sub display style:", page.evaluate("document.getElementById('bin-master-sub').style.display"))
    print("Bin sub inner text:", bin_sub.inner_text()[:100])
    b.close()
