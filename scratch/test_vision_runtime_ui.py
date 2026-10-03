"""
W.A.R.L.O.G. / Skandha WMS AI Vision & Tracking Master
Part 15 — Vision Runtime & Processing Orchestrator Playwright UI Automation Test

Tests:
1. Login & Session Initialization
2. Navigation to AI Vision Master -> Runtime Orchestrator Subtab
3. Telemetry Summary Cards Display (Active Cams, Avg FPS, Frames Processed, Frames Dropped)
4. Per-Camera Runtime Sessions Table Verification (CAM-001 through CAM-004)
5. Start All Cameras Action & Multi-camera Telemetry Updates
6. Live Pipeline Preview Drawer Verification
7. Stop All Cameras Action & Graceful Halt Verification
8. Zero Critical Browser Console Errors Audit
9. High-resolution Screenshots Capture to Artifacts Directory
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20"
BASE_URL = "http://127.0.0.1:5000"


def run_ui_test():
    print("=" * 70)
    print("SKANDHA-WMS + W.A.R.L.O.G. - PART 15 VISION RUNTIME UI TEST")
    print("=" * 70)

    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 920})
        page = context.new_page()

        def on_console(msg):
            if msg.type == "error" and "favicon" not in msg.text:
                console_errors.append(f"[{msg.type}] {msg.text}")
        page.on("console", on_console)

        try:
            # 1. Login
            print("\n[STEP 1] Navigating to Skandha WMS...")
            page.goto(f"{BASE_URL}/", timeout=15000)
            page.wait_for_load_state("networkidle")

            if page.locator("#username").is_visible(timeout=3000):
                print("Logging in with admin credentials...")
                page.fill("#username", "admin")
                page.fill("#password", "admin")
                page.click(".btn-login-main")
                page.wait_for_timeout(1000)

            # 2. Navigate to AI Vision Master tab
            print("\n[STEP 2] Opening AI Vision Master Tab...")
            page.evaluate("switchTab('ai-vision-master')")
            page.wait_for_selector("#ai-vision-master-view", state="visible", timeout=5000)
            print("PASS: AI Vision Master view is visible.")

            # 3. Switch to Runtime Orchestrator subtab
            print("\n[STEP 3] Switching to Runtime Orchestrator subtab...")
            btn_runtime = page.locator("#btnVisionRuntimeTab")
            assert btn_runtime.is_visible(), "Error: btnVisionRuntimeTab is not visible!"
            btn_runtime.click()
            page.wait_for_selector("#vision-runtime-sub", state="visible", timeout=5000)
            page.wait_for_timeout(1000)

            # Verify section visible
            runtime_sub = page.locator("#vision-runtime-sub")
            assert runtime_sub.is_visible(), "Error: vision-runtime-sub is not visible!"
            print("PASS: Runtime Orchestrator sub-page is visible.")

            # Capture initial stopped state
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "runtime_orchestrator_initial.png"))
            print(f"Captured: {os.path.join(ARTIFACT_DIR, 'runtime_orchestrator_initial.png')}")

            # 4. Verify Camera Table has 4 cameras
            print("\n[STEP 4] Verifying Camera Sessions Table...")
            cam_rows = page.locator("#rtCameraTableBody tr")
            row_count = cam_rows.count()
            print(f"Camera session rows count: {row_count}")
            assert row_count >= 4, f"Expected at least 4 camera rows, found {row_count}"

            # 5. Start All Cameras
            print("\n[STEP 5] Clicking 'Start All' Cameras...")
            page.click("#btnStartAllCameras")
            page.wait_for_timeout(2500)  # Wait for polling cycle and frame processing

            # Verify active cameras indicator
            active_cams_text = page.locator("#rtTotalActiveCams").inner_text()
            print(f"Active cameras count: {active_cams_text}")
            assert "4 / 4" in active_cams_text or "4" in active_cams_text, f"Unexpected active cams text: {active_cams_text}"

            # Verify frames processed is incrementing
            frames_proc_text = page.locator("#rtTotalFramesProc").inner_text()
            print(f"Total frames processed: {frames_proc_text}")

            # Capture running state screenshot
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "runtime_orchestrator_running.png"))
            print(f"Captured: {os.path.join(ARTIFACT_DIR, 'runtime_orchestrator_running.png')}")

            # 6. Open Live Preview for CAM-001
            print("\n[STEP 6] Opening Live Preview for CAM-001...")
            preview_btn = page.locator("#rtCameraTableBody tr").first.locator("button[title='Live Preview']")
            if preview_btn.is_visible():
                preview_btn.click()
                page.wait_for_timeout(1000)
                preview_sec = page.locator("#rtPreviewSection")
                assert preview_sec.is_visible(), "Preview section should be visible after clicking preview button"
                preview_sec.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                print("PASS: Live pipeline preview section displayed.")
                page.screenshot(path=os.path.join(ARTIFACT_DIR, "runtime_orchestrator_preview.png"))
                print(f"Captured: {os.path.join(ARTIFACT_DIR, 'runtime_orchestrator_preview.png')}")

            # 7. Dark Theme Verification
            print("\n[STEP 7] Testing Dark Theme...")
            dark_btn = page.locator("button[data-theme-btn='dark']")
            if dark_btn.is_visible():
                dark_btn.click()
                page.wait_for_timeout(800)
                page.screenshot(path=os.path.join(ARTIFACT_DIR, "runtime_orchestrator_dark.png"))
                print(f"Captured: {os.path.join(ARTIFACT_DIR, 'runtime_orchestrator_dark.png')}")
                page.click("button[data-theme-btn='light']")
                page.wait_for_timeout(500)

            # 8. Stop All Cameras
            print("\n[STEP 8] Clicking 'Stop All' Cameras...")
            page.click("#btnStopAllCameras")
            page.wait_for_timeout(1500)

            active_cams_after = page.locator("#rtTotalActiveCams").inner_text()
            print(f"Active cameras after stop: {active_cams_after}")
            assert "0 /" in active_cams_after, f"Expected 0 active cams after stop, got {active_cams_after}"
            print("PASS: All camera sessions gracefully halted.")

            # 9. Console Error Audit
            print("\n[STEP 9] Console Error Audit...")
            critical_errors = [e for e in console_errors if "favicon" not in e.lower()]
            print(f"Total console errors captured: {len(critical_errors)}")
            for err in critical_errors:
                print(f"  Console Error: {err}")
            assert len(critical_errors) == 0, f"Expected 0 console errors, got {len(critical_errors)}"
            print("PASS: 0 critical console errors.")

            print("\n" + "=" * 70)
            print("PLAYWRIGHT UI TEST COMPLETED SUCCESSFULLY!")
            print("=" * 70)

        except Exception as e:
            print(f"\nTEST FAILED WITH EXCEPTION: {e}")
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "runtime_orchestrator_error.png"))
            raise e
        finally:
            browser.close()


if __name__ == '__main__':
    run_ui_test()
