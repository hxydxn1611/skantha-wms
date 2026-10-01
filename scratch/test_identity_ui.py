"""
Playwright automated UI test for Part 7 — Object Identity & Recognition Foundation.
Tests subtab switching, QR test, Barcode test, Conflict test, Dark Theme, and captures screenshots.
"""

import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        print("1. Navigating to W.A.R.L.O.G. WMS...")
        page.goto("http://127.0.0.1:5000/")
        page.wait_for_load_state("networkidle")

        # Login if on login page
        if page.locator("#username").is_visible():
            print("Logging in as admin...")
            page.fill("#username", "admin")
            page.fill("#password", "admin")
            page.click(".btn-login-main")
            page.wait_for_timeout(1000)

        # Navigate to AI Vision & Tracking Master
        print("2. Navigating to AI Vision & Tracking Master...")
        page.click("button.tab-btn:has-text('AI Vision')")
        page.wait_for_timeout(800)

        # Click Identity Test subtab
        print("3. Clicking Identity Test subtab...")
        identity_btn = page.locator("button.vision-sub-btn:has-text('Identity Test')")
        identity_btn.click()
        page.wait_for_timeout(600)

        # Verify #vision-identity-sub is visible
        sub_page = page.locator("#vision-identity-sub")
        assert sub_page.is_visible(), "Identity sub-page is not visible!"
        print("Identity Test subtab is active and visible.")

        # Test 1: Run Identity on QR Code sample (B104)
        print("4. Running Identity Test on Sample 1: QR Code Placard [B104]...")
        page.select_option("#idSourceTypeSelect", "identity_qr_b104.jpg")
        page.click("#btnRunIdentity")
        page.wait_for_timeout(2000)

        # Verify results in UI
        ident_val = page.locator("#idResultsTbody strong").first.inner_text()
        print(f"Decoded identifier in UI: {ident_val}")
        assert "B104" in ident_val, f"Expected B104, got {ident_val}"

        page.screenshot(path=os.path.join(ARTIFACT_DIR, "identity_test_qr.png"))
        print("Saved identity_test_qr.png")

        # Test 2: Run Identity on Barcode sample (B105)
        print("5. Running Identity Test on Sample 2: Barcode [B105]...")
        page.click("#btnResetIdentity")
        page.wait_for_timeout(400)
        page.select_option("#idSourceTypeSelect", "identity_barcode_b105.jpg")
        page.click("#btnRunIdentity")
        page.wait_for_timeout(2000)

        ident_val_bc = page.locator("#idResultsTbody strong").first.inner_text()
        print(f"Decoded barcode identifier in UI: {ident_val_bc}")
        assert "B105" in ident_val_bc, f"Expected B105, got {ident_val_bc}"

        page.screenshot(path=os.path.join(ARTIFACT_DIR, "identity_test_barcode.png"))
        print("Saved identity_test_barcode.png")

        # Test 3: Run Identity on Conflict sample (B104 vs B109)
        print("6. Running Identity Test on Sample 5: Conflicting Identifiers...")
        page.click("#btnResetIdentity")
        page.wait_for_timeout(400)
        page.select_option("#idSourceTypeSelect", "identity_conflict.jpg")
        page.click("#btnRunIdentity")
        page.wait_for_timeout(2000)

        conflict_badge = page.locator("#idResultsTbody .badge:has-text('CONFLICT')")
        assert conflict_badge.count() > 0, "Conflict badge not found in table!"
        print("Conflict status successfully verified in UI.")

        page.screenshot(path=os.path.join(ARTIFACT_DIR, "identity_test_conflict.png"))
        print("Saved identity_test_conflict.png")

        # Test 4: Run 5-frame sequence on QR scene
        print("7. Running 5-frame identity sequence...")
        page.click("#btnResetIdentity")
        page.wait_for_timeout(400)
        page.select_option("#idSourceTypeSelect", "identity_qr_b104.jpg")
        page.click("#btnRunIdentitySeq")
        page.wait_for_timeout(4000)

        page.screenshot(path=os.path.join(ARTIFACT_DIR, "identity_test_ui.png"))
        print("Saved identity_test_ui.png")

        # Test 5: Check Black Theme Parity
        print("8. Testing Black Theme...")
        theme_toggle = page.locator("button:has-text('THEME')")
        if theme_toggle.count() > 0:
            theme_toggle.first.click()
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "identity_black_theme.png"))
            print("Saved identity_black_theme.png")
            # Switch back to default
            theme_toggle.first.click()
            page.wait_for_timeout(400)

        # Test 6: Reset Session
        print("9. Testing Reset Session...")
        page.click("#btnResetIdentity")
        page.wait_for_timeout(600)
        tracks_kpi = page.locator("#kpi-id-tracks").inner_text()
        print(f"Active tracks after reset: {tracks_kpi}")
        assert tracks_kpi == "0", f"Expected 0 tracks after reset, got {tracks_kpi}"

        browser.close()
        print("Playwright UI test completed successfully!")

if __name__ == "__main__":
    run()
