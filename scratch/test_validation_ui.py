import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # 1. Navigate to WMS
    print("1. Navigating to http://127.0.0.1:5000...")
    page.goto("http://127.0.0.1:5000/")
    page.wait_for_load_state("networkidle")

    # 2. Login if on login page
    if page.locator("#username").is_visible():
        print("Logging in as admin...")
        page.fill("#username", "admin")
        page.fill("#password", "admin")
        page.click(".btn-login-main")
        page.wait_for_timeout(1000)

    # 3. Navigate to AI Vision & Tracking Master
    print("2. Navigating to AI Vision & Tracking Master...")
    page.click("button.tab-btn:has-text('AI Vision')")
    page.wait_for_timeout(800)

    # 4. Click Validation Test subtab
    print("3. Clicking Validation Test subtab...")
    val_btn = page.locator("button.vision-sub-btn:has-text('Validation Test')")
    val_btn.click()
    page.wait_for_timeout(800)

    # Verify #vision-validation-sub is visible
    sub_page = page.locator("#vision-validation-sub")
    assert sub_page.is_visible(), "Validation sub-page is not visible!"
    print("Validation Test subtab is active and visible.")

    # 5. Run Validation on Sample 1: Gate Pass GP-1000
    print("4. Testing Sample 1: Gate Pass GP-1000...")
    page.select_option("#valSourceTypeSelect", "validation_truck_gp1000.jpg")
    page.click("#btnRunValidation")
    page.wait_for_timeout(2500)

    # Take screenshot of Validated result
    shot1 = os.path.join(ARTIFACT_DIR, "validation_test_gp1000.png")
    page.screenshot(path=shot1)
    print("Saved:", shot1)

    # 6. Run Validation on Sample 4: Unregistered B999999
    print("5. Testing Sample 4: Unregistered B999999...")
    page.select_option("#valSourceTypeSelect", "validation_unknown_b999.jpg")
    page.click("#btnRunValidation")
    page.wait_for_timeout(2500)

    shot2 = os.path.join(ARTIFACT_DIR, "validation_test_unregistered.png")
    page.screenshot(path=shot2)
    print("Saved:", shot2)

    # 7. Switch to Dark Theme
    print("6. Switching to Dark Theme...")
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark');")
    page.wait_for_timeout(1000)

    # Re-run Sample 1 in dark theme
    page.select_option("#valSourceTypeSelect", "validation_truck_gp1000.jpg")
    page.click("#btnRunValidation")
    page.wait_for_timeout(2500)

    shot3 = os.path.join(ARTIFACT_DIR, "validation_black_theme.png")
    page.screenshot(path=shot3)
    print("Saved:", shot3)

    # Full UI view
    shot4 = os.path.join(ARTIFACT_DIR, "validation_test_ui.png")
    page.screenshot(path=shot4)
    print("Saved:", shot4)

    browser.close()
    print("Playwright UI verification finished successfully!")
