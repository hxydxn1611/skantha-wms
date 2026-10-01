from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.goto('http://127.0.0.1:5000/')
    page.click('.btn-login-main')
    page.wait_for_timeout(1000)
    page.click('button.tab-btn:nth-child(7)')
    page.wait_for_timeout(500)
    page.click('button.vision-sub-btn:nth-child(7)')
    page.wait_for_timeout(500)
    page.select_option('#idSourceTypeSelect', 'identity_qr_b104.jpg')
    page.click('#btnRunIdentity')
    page.wait_for_timeout(2000)
    
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark');")
    page.wait_for_timeout(500)
    page.screenshot(path=r'C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20\identity_black_theme.png')
    print('Saved identity_black_theme.png successfully!')
    browser.close()
