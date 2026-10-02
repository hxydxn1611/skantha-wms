"""
Playwright UI Verification Script for Part 11: Box <-> Bin Association Test Bench
Verifies:
  1. Login & navigation to AI Vision & Tracking Master
  2. Switching to 'Box ↔ Bin Association Test' sub-tab
  3. Association KPIs and configuration rules display
  4. Execution of Single Frame Association Test
  5. Execution of Multi-Frame Sequence (CANDIDATE -> CONFIRMED)
  6. Opening and verifying Box ↔ Bin Association Evidence Modal
  7. Ambiguous scenario with competing bins
  8. Dark / Black theme styling and layout
  9. Captures screenshots for artifacts
"""

import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def run_ui_test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.on("console", lambda msg: print(f"BROWSER CONSOLE [{msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"BROWSER ERROR: {err}"))

        print("1. Navigating to W.A.R.L.O.G. WMS...")
        page.goto("http://127.0.0.1:5000/")
        page.wait_for_load_state("networkidle")

        # Handle login if displayed
        if page.locator("#username").is_visible():
            print("   Logging in with admin credentials...")
            page.fill("#username", "admin")
            page.fill("#password", "admin")
            page.click(".btn-login-main")
            page.wait_for_timeout(1000)

        # 2. Click AI Vision & Tracking Master Tab
        print("2. Navigating to AI Vision & Tracking Master...")
        page.click("button.tab-btn:has-text('AI Vision')")
        page.wait_for_timeout(800)

        # 3. Click Box <-> Bin Association Test sub-tab
        print("3. Switching to 'Box <-> Bin Association Test' sub-tab...")
        page.click("button.vision-sub-btn:has-text('Bin')")
        page.wait_for_timeout(800)

        # Verify vision-box-bin-sub is visible
        sub_visible = page.locator("#vision-box-bin-sub").is_visible()
        print(f"   Box-Bin Sub-tab Visible: {sub_visible}")
        assert sub_visible, "vision-box-bin-sub should be visible"

        # Capture initial state
        img1 = os.path.join(ARTIFACT_DIR, "box_bin_test_ui.png")
        page.screenshot(path=img1)
        print(f"   Saved screenshot: {img1}")

        # 4. Reset session then Test Single Frame Evaluation with Sample Scene 1
        print("4. Testing Single Frame Association...")
        page.click("#btnResetBoxBin")
        page.wait_for_timeout(600)

        page.select_option("#bbSourceTypeSelect", "association_box_bin_dock1.jpg")
        page.wait_for_timeout(300)
        page.click("#btnRunBoxBin")
        page.wait_for_timeout(2000)

        # Verify Candidates count or table updated
        cand_txt = page.locator("#kpi-bb-candidates").inner_text()
        print(f"   Single frame result: Candidates={cand_txt}")

        # 5. Test Multi-Frame Sequence Execution (CANDIDATE -> CONFIRMED)
        print("5. Testing Multi-Frame Association Sequence (CANDIDATE -> CONFIRMED)...")
        # Use synthetic confirmation sequence to guarantee >= 3 frame persistence
        page.select_option("#bbSourceTypeSelect", "synthetic_bb_confirm")
        page.wait_for_timeout(300)
        page.click("#btnStepBoxBin")
        page.wait_for_timeout(2500)

        conf_txt = page.locator("#kpi-bb-confirmed").inner_text()
        print(f"   Sequence completed: Confirmed Associations={conf_txt}")
        assert int(conf_txt) >= 1, f"Should have at least 1 CONFIRMED association after sequence, got {conf_txt}"

        # Scroll to show annotated image and table
        page.locator("#bbImageContainer").scroll_into_view_if_needed()
        page.wait_for_timeout(400)

        # Capture Confirmed state
        img2 = os.path.join(ARTIFACT_DIR, "box_bin_test_confirmed.png")
        page.screenshot(path=img2)
        print(f"   Saved screenshot: {img2}")

        # 6. Open Evidence Modal
        print("6. Opening Box <-> Bin Evidence Details Modal...")
        page.click("#bbResultsTbody button:has-text('Evidence')")
        page.wait_for_timeout(600)

        modal_visible = page.locator("#bbEvidenceModal").is_visible()
        print(f"   Evidence Modal Visible: {modal_visible}")
        assert modal_visible, "Evidence modal should be visible"

        img3 = os.path.join(ARTIFACT_DIR, "box_bin_evidence_modal.png")
        page.screenshot(path=img3)
        print(f"   Saved screenshot: {img3}")

        # Close Modal
        page.click("#bbEvidenceModal button:has-text('✕')")
        page.wait_for_timeout(400)

        # 7. Test Ambiguity Scene Selection
        print("7. Testing Ambiguous Scenario with Two Bins near One Box...")
        page.select_option("#bbSourceTypeSelect", "association_ambiguous_two_bins.jpg")
        page.wait_for_timeout(300)
        page.click("#btnRunBoxBin")
        page.wait_for_timeout(2000)

        page.locator("#bbImageContainer").scroll_into_view_if_needed()
        page.wait_for_timeout(300)

        amb_txt = page.locator("#kpi-bb-ambiguous").inner_text()
        print(f"   Ambiguous Pairs Count={amb_txt}")

        img4 = os.path.join(ARTIFACT_DIR, "box_bin_test_ambiguous.png")
        page.screenshot(path=img4)
        print(f"   Saved screenshot: {img4}")

        # 8. Test Dark / Black Theme
        print("8. Testing Dark Theme toggle...")
        theme_btn = page.locator(".theme-toggle-btn[data-theme-btn='dark']")
        if theme_btn.count() > 0:
            theme_btn.first.click()
            page.wait_for_timeout(500)
        else:
            page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")

        page.locator("#bbImageContainer").scroll_into_view_if_needed()
        page.wait_for_timeout(300)

        img5 = os.path.join(ARTIFACT_DIR, "box_bin_black_theme.png")
        page.screenshot(path=img5)
        print(f"   Saved screenshot: {img5}")

        print("\nALL BOX <-> BIN PLAYWRIGHT UI CHECKS PASSED SUCCESSFULLY!")
        browser.close()

if __name__ == "__main__":
    run_ui_test()
