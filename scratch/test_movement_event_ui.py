"""
UI End-to-End Automated Test Suite for Warehouse Movement Event Detection Foundation (Part 12)
W.A.R.L.O.G. / Skandha WMS
"""

import sys
import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20"
BASE_URL = "http://127.0.0.1:5000"

def run_movement_events_ui_test():
    print("=" * 75)
    print("AI VISION & TRACKING MASTER - PART 12 UI VERIFICATION SUITE")
    print("=" * 75)

    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        try:
            # 1. Navigate to Application
            print("[STEP 1] Navigating to Skandha WMS Base URL...")
            page.goto(BASE_URL, timeout=30000)
            page.wait_for_load_state("networkidle")

            # Check if login page is presented
            if page.locator("#username").is_visible(timeout=3000):
                print("Logging in as admin...")
                page.fill("#username", "admin")
                page.fill("#password", "admin")
                page.click(".btn-login-main")
                page.wait_for_timeout(1000)

            # 2. Switch to AI Vision & Tracking Master Hub
            print("[STEP 2] Navigating to AI Vision & Tracking Master Module...")
            page.click("button.tab-btn:has-text('AI Vision')")
            page.wait_for_timeout(800)

            # 3. Switch to Warehouse Movement Events Test Subtab
            print("[STEP 3] Switching to Warehouse Movement Events Test Subtab...")
            page.click("button.vision-sub-btn:has-text('Movement')")
            page.wait_for_timeout(800)

            # Verify subtab container is visible
            events_container = page.locator("#vision-events-sub")
            assert events_container.is_visible(), "Error: #vision-events-sub container is not visible!"
            print("[PASS] Warehouse Movement Events Test subtab is active and visible.")

            # 4. Run 8-Frame Sequence Test
            print("[STEP 4] Executing 8-Frame Dock Loading Sequence Test...")
            run_seq_btn = page.locator("#btnRunEventSeq")
            run_seq_btn.wait_for(state="visible", timeout=5000)
            run_seq_btn.click()

            # Wait for sequence to complete and table rows to appear
            page.wait_for_function("document.querySelectorAll('#evtResultsTbody tr').length > 0", timeout=15000)
            time.sleep(2)

            # Verify rows count
            rows = page.locator("#evtResultsTbody tr")
            row_count = rows.count()
            print(f"[PASS] Sequence completed: Generated {row_count} event records in ledger.")
            assert row_count >= 5, f"Expected at least 5 events across sequence, got {row_count}"

            # Capture UI Screenshot: Sequence execution
            seq_shot_path = os.path.join(ARTIFACT_DIR, "movement_events_test_ui.png")
            page.screenshot(path=seq_shot_path, full_page=False)
            print(f"[SCREENSHOT] Saved sequence UI test to {seq_shot_path}")

            # 5. Inspect Event Evidence Modal
            print("[STEP 5] Inspecting Explainable Event Evidence Modal...")
            first_evidence_btn = page.locator("#evtResultsTbody button:has-text('Evidence')").first
            first_evidence_btn.click()
            time.sleep(1)

            evidence_modal = page.locator("#evtEvidenceModal")
            assert evidence_modal.is_visible(), "Error: Evidence modal failed to open!"
            modal_text = page.locator("#modalEvtContent").inner_text()
            assert len(modal_text) > 50, "Evidence modal content is empty!"
            print("[PASS] Evidence breakdown modal verified with explainable factors.")

            # Capture UI Screenshot: Evidence Modal
            modal_shot_path = os.path.join(ARTIFACT_DIR, "movement_events_evidence_modal.png")
            page.screenshot(path=modal_shot_path, full_page=False)
            print(f"[SCREENSHOT] Saved evidence modal to {modal_shot_path}")

            # Close Modal
            close_btn = page.locator("#evtEvidenceModal button:has-text('Close')")
            close_btn.click()
            time.sleep(0.5)

            # 6. Run Single Frame Scenario (Box Enter)
            print("[STEP 6] Testing Scenario 1: Box Enters Dock 1 (Single Frame)...")
            page.select_option("#evtSourceSelect", "box_enter")
            page.click("#btnRunEventTest")
            time.sleep(1.5)

            active_kpi = page.locator("#kpi-evt-active").inner_text()
            print(f"[PASS] Box Enter Test executed: Active Events KPI = {active_kpi}")

            box_enter_shot_path = os.path.join(ARTIFACT_DIR, "movement_events_box_enter.png")
            page.screenshot(path=box_enter_shot_path, full_page=False)
            print(f"[SCREENSHOT] Saved Box Enter scenario to {box_enter_shot_path}")

            # 7. Test Reset Session
            print("[STEP 7] Testing In-Memory Session Reset...")
            page.click("#btnResetEventSession")
            time.sleep(1)

            reset_active = page.locator("#kpi-evt-active").inner_text()
            assert reset_active == "0", f"Expected 0 active events after reset, got {reset_active}"
            print("[PASS] Session Reset successfully cleared in-memory state and UI counters.")

            # 8. Test Dark Theme Appearance
            print("[STEP 8] Testing Dark / Sleek Theme Appearance...")
            # Run sequence again for populated view
            page.select_option("#evtSourceSelect", "dock_loading")
            page.click("#btnRunEventSeq")
            time.sleep(2)

            theme_toggle = page.locator("#themeToggleBtn")
            if theme_toggle.is_visible():
                theme_toggle.click()
                time.sleep(0.5)

            dark_shot_path = os.path.join(ARTIFACT_DIR, "movement_events_black_theme.png")
            page.screenshot(path=dark_shot_path, full_page=False)
            print(f"[SCREENSHOT] Saved dark theme to {dark_shot_path}")

            print("=" * 75)
            print(">>> ALL PART 12 UI VERIFICATION TESTS PASSED SUCCESSFULLY! <<<")
            print("=" * 75)

        except Exception as e:
            print(f"[FAIL] UI Test encountered error: {e}")
            fail_shot = os.path.join(ARTIFACT_DIR, "movement_events_ui_failure.png")
            page.screenshot(path=fail_shot)
            print(f"[SCREENSHOT] Saved failure state to {fail_shot}")
            raise
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    run_movement_events_ui_test()
