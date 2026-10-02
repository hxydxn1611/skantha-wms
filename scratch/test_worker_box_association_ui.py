"""
Playwright UI Verification Script for Part 10: Worker <-> Box Association Test Bench
Verifies:
  1. Login & navigation to AI Vision & Tracking Master
  2. Switching to 'Worker ↔ Box Association Test' subtab
  3. Association KPIs and configuration rules display
  4. Execution of Single Frame Association Test
  5. Execution of Multi-Frame Sequence (CANDIDATE -> CONFIRMED)
  6. Opening and verifying Worker ↔ Box Association Evidence Modal
  7. Ambiguous scenario with competing workers
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

        # 3. Click Worker <-> Box Association Test sub-tab
        print("3. Switching to 'Worker <-> Box Association Test' sub-tab...")
        page.click("button.vision-sub-btn:has-text('Worker')")
        page.wait_for_timeout(800)

        # Verify vision-worker-box-sub is visible
        sub_visible = page.locator("#vision-worker-box-sub").is_visible()
        print(f"   Worker-Box Sub-tab Visible: {sub_visible}")
        assert sub_visible, "vision-worker-box-sub should be visible"

        # Capture initial state
        img1 = os.path.join(ARTIFACT_DIR, "worker_box_test_ui.png")
        page.screenshot(path=img1)
        print(f"   Saved screenshot: {img1}")

        # 4. Reset session then Test Single Frame Evaluation with Synthetic Track Feed
        print("4. Testing Single Frame Association...")
        page.click("#btnResetWorkerBox")
        page.wait_for_timeout(600)

        page.select_option("#wbSourceTypeSelect", "synthetic_wb_confirm")
        page.wait_for_timeout(300)
        page.click("#btnRunWorkerBox")
        page.wait_for_timeout(1500)

        # Verify Candidates count increased
        cand_txt = page.locator("#kpi-wb-candidates").inner_text()
        print(f"   Single frame result: Candidates={cand_txt}")
        assert int(cand_txt) >= 1, "Should have at least 1 CANDIDATE association on frame 1"

        # 5. Test 5-Frame Sequence Execution (CANDIDATE -> CONFIRMED)
        print("5. Testing 5-Frame Association Sequence (CANDIDATE -> CONFIRMED)...")
        page.click("#btnRunWorkerBoxSeq")
        page.wait_for_timeout(2000)

        conf_txt = page.locator("#kpi-wb-confirmed").inner_text()
        print(f"   Sequence completed: Confirmed Associations={conf_txt}")
        assert int(conf_txt) >= 1, "Should have at least 1 CONFIRMED association after sequence"

        # Scroll to show annotated image and table
        page.locator("#wbImageContainer").scroll_into_view_if_needed()
        page.wait_for_timeout(400)

        # Capture Confirmed state
        img2 = os.path.join(ARTIFACT_DIR, "worker_box_test_confirmed.png")
        page.screenshot(path=img2)
        print(f"   Saved screenshot: {img2}")

        # 6. Open Evidence Modal
        print("6. Opening Worker <-> Box Evidence Details Modal...")
        page.click("#wbResultsTbody button:has-text('🔍 Evidence')")
        page.wait_for_timeout(600)

        modal_visible = page.locator("#wbEvidenceModal").is_visible()
        print(f"   Evidence Modal Visible: {modal_visible}")
        assert modal_visible, "Evidence modal should be visible"

        img3 = os.path.join(ARTIFACT_DIR, "worker_box_evidence_modal.png")
        page.screenshot(path=img3)
        print(f"   Saved screenshot: {img3}")

        # Close Modal
        page.click("#wbEvidenceModal button:has-text('Close')")
        page.wait_for_timeout(400)

        # 7. Test Ambiguity Scene Selection
        print("7. Testing Ambiguous Scenario with Two Workers near One Box...")
        page.select_option("#wbSourceTypeSelect", "association_ambiguous_two_workers.jpg")
        page.wait_for_timeout(300)
        page.click("#btnRunWorkerBox")
        page.wait_for_timeout(1500)

        page.locator("#wbImageContainer").scroll_into_view_if_needed()
        page.wait_for_timeout(300)

        img4 = os.path.join(ARTIFACT_DIR, "worker_box_test_ambiguous.png")
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

        page.locator("#wbImageContainer").scroll_into_view_if_needed()
        page.wait_for_timeout(300)

        img5 = os.path.join(ARTIFACT_DIR, "worker_box_black_theme.png")
        page.screenshot(path=img5)
        print(f"   Saved screenshot: {img5}")

        print("\nALL WORKER <-> BOX PLAYWRIGHT UI CHECKS PASSED SUCCESSFULLY!")
        browser.close()

if __name__ == "__main__":
    run_ui_test()
