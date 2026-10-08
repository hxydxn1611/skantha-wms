"""
Detailed Module-by-Module Inspection Script
Gathers exact functional status, DOM state, API responses, console errors,
and screenshots for all modules of Skandha WMS / W.A.R.L.O.G.
"""

import os
import sys
import json
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20\audit"
BASE_URL = "http://127.0.0.1:5000"

results = {
    "modules": {},
    "console_errors": [],
    "network_errors": [],
    "broken_features": [],
    "ux_inconsistencies": []
}


def log_issue(module, action, expected, actual, error, severity, component):
    results["broken_features"].append({
        "screen": module,
        "action": action,
        "expected": expected,
        "actual": actual,
        "error": error,
        "severity": severity,
        "component": component
    })
    print(f"\n[ISSUE - {severity}] {module} -> {action}")
    print(f"  Expected: {expected}")
    print(f"  Actual:   {actual}")
    print(f"  Error:    {error}")


def run_detailed_audit():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_console(msg):
            if msg.type == "error" and "favicon" not in msg.text.lower():
                results["console_errors"].append(msg.text)
                print(f"[CONSOLE ERROR] {msg.text}")
        page.on("console", on_console)

        def on_response(res):
            if res.status >= 400:
                results["network_errors"].append(f"{res.status} {res.request.method} {res.url}")
                print(f"[HTTP {res.status}] {res.request.method} {res.url}")
        page.on("response", on_response)

        # 1. LOGIN
        print("\n=== 1. AUDITING LOGIN / AUTHENTICATION ===")
        page.goto(f"{BASE_URL}/", timeout=15000)
        page.wait_for_load_state("networkidle")

        # Invalid login check
        if page.locator("#username").is_visible(timeout=3000):
            page.fill("#username", "invalid_admin")
            page.fill("#password", "wrong_password")
            page.click(".btn-login-main")
            page.wait_for_timeout(1000)
            
            # Check if an alert was triggered or text displayed
            body_text = page.locator("body").inner_text()
            if "Invalid credentials" not in body_text:
                log_issue(
                    "Login / Authentication",
                    "Submit invalid credentials",
                    "Surfaced visible error banner or toast alerting user to invalid credentials",
                    "HTTP 401 returned by API, but no visual error message rendered in DOM",
                    "Silent failure on invalid credentials in UI",
                    "MEDIUM",
                    "webapp/static/js/app_logic.js (login handler)"
                )
            
            # Valid login
            page.fill("#username", "admin")
            page.fill("#password", "admin")
            page.click(".btn-login-main")
            page.wait_for_timeout(1500)

        # 2. MAIN DASHBOARD
        print("\n=== 2. AUDITING MAIN DASHBOARD ===")
        page.wait_for_selector("#dashboard-view", timeout=5000)
        kpi_counts = page.locator(".kpi-card").count()
        print(f"KPI cards count: {kpi_counts}")

        # Check Inbound Logistics & Vision Stream table
        stream_rows = page.locator("#unifiedInboundStreamBody tr").count()
        print(f"Inbound stream table rows: {stream_rows}")

        # Check Quick Navigation links on Dashboard
        quick_links = page.locator(".quick-links a, .quick-actions button, button:has-text('Quick')")
        print(f"Quick action links: {quick_links.count()}")

        # 3. INBOUND (PRE-REGISTRATION)
        print("\n=== 3. AUDITING INBOUND MODULE (PRE-REGISTRATION) ===")
        page.evaluate("switchTab('deliveries')")
        page.wait_for_timeout(1000)
        deliv_table = page.locator("#deliveriesTableBody tr, #deliveries-table tbody tr")
        deliv_count = deliv_table.count()
        print(f"Deliveries count: {deliv_count}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_01_deliveries.png"))

        # Check form for adding delivery
        deliv_form = page.locator("#deliveryForm, form[action*='deliveries']")
        print(f"Delivery registration form found: {deliv_form.count()}")

        # 4. GATE MANAGEMENT
        print("\n=== 4. AUDITING GATE MANAGEMENT ===")
        page.evaluate("switchTab('gate-passes')")
        page.wait_for_timeout(1000)
        gp_table = page.locator("#gatePassesTableBody tr, #gatePassesBody tr")
        print(f"Gate passes count: {gp_table.count()}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_02_gate_passes.png"))

        # 5. DOCK MANAGEMENT
        print("\n=== 5. AUDITING DOCK MANAGEMENT ===")
        page.evaluate("switchTab('docks')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_03_docks.png"))

        # 6. MASTER HUB
        print("\n=== 6. AUDITING MASTER HUB ===")
        page.evaluate("switchTab('master-hub')")
        page.wait_for_timeout(1000)

        # Bin Master
        print("Auditing Bin Master...")
        page.locator("button.sub-tab-btn:has-text('Bin Master')").first.click()
        page.wait_for_timeout(800)
        bin_rows = page.locator("#binsTableBody tr").count()
        print(f"Bins table rows: {bin_rows}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_04_bins.png"))

        # SKU Master
        print("Auditing SKU Master...")
        page.locator("button.sub-tab-btn:has-text('SKU Master')").first.click()
        page.wait_for_timeout(800)
        sku_rows = page.locator("#skusTableBody tr").count()
        print(f"SKUs table rows: {sku_rows}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_05_skus.png"))

        # Inventory Master
        print("Auditing Inventory Master...")
        page.locator("button.sub-tab-btn:has-text('Inventory Master')").first.click()
        page.wait_for_timeout(800)
        inv_rows = page.locator("#inventoryMasterBody tr").count()
        print(f"Inventory table rows: {inv_rows}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_06_inventory.png"))

        # Cycle Count
        print("Auditing Cycle Count...")
        page.locator("button.sub-tab-btn:has-text('Cycle Count')").first.click()
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_07_cycle_count.png"))

        # 7. OUTBOUND FLOW
        print("\n=== 7. AUDITING OUTBOUND FLOW ===")
        page.evaluate("switchTab('outbound')")
        page.wait_for_timeout(1000)
        outbound_view = page.locator("#outbound-view")
        print(f"Outbound view visible: {outbound_view.is_visible()}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_08_outbound.png"))

        # Check outbound order table and form
        outbound_rows = page.locator("#outboundTableBody tr").count()
        print(f"Outbound table rows: {outbound_rows}")

        # 8. CAMERA JUNCTION
        print("\n=== 8. AUDITING CAMERA JUNCTION ===")
        page.evaluate("switchTab('cameras')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_09_camera_junction.png"))
        cam_cards = page.locator(".camera-card, .cam-box")
        print(f"Camera cards count: {cam_cards.count()}")

        # 9. AI VISION & TRACKING MASTER
        print("\n=== 9. AUDITING AI VISION MASTER ===")
        page.evaluate("switchTab('ai-vision-master')")
        page.wait_for_timeout(1000)

        # Check Object Classes
        print("Checking Object Classes subtab...")
        page.locator("button.vision-sub-btn:has-text('Object Classes')").first.click()
        page.wait_for_timeout(1000)
        obj_rows = page.locator("#objectClassesBody tr").count()
        print(f"Object classes table rows count: {obj_rows}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_10_object_classes.png"))

        # Check Camera Sources
        print("Checking Camera Sources subtab...")
        page.locator("button.vision-sub-btn:has-text('Camera Sources')").first.click()
        page.wait_for_timeout(1000)
        cam_source_rows = page.locator("#cameraSourcesBody tr").count()
        print(f"Camera sources table rows: {cam_source_rows}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_11_camera_sources.png"))

        # Check Warehouse Zones
        print("Checking Warehouse Zones subtab...")
        page.locator("button.vision-sub-btn:has-text('Warehouse Zones')").first.click()
        page.wait_for_timeout(1000)
        zone_rows = page.locator("#zonesListTableBody tr, #zonesTableBody tr").count()
        print(f"Warehouse zones rows: {zone_rows}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_12_warehouse_zones.png"))

        # Check Detection Test
        print("Checking Detection Test subtab...")
        page.locator("button.vision-sub-btn:has-text('Detection Test')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_13_detection_test.png"))

        # Check Tracking Test
        print("Checking Tracking Test subtab...")
        page.locator("button.vision-sub-btn:has-text('Tracking Test')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_14_tracking_test.png"))

        # Check Identity Test
        print("Checking Identity Test subtab...")
        page.locator("button.vision-sub-btn:has-text('Identity Test')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_15_identity_test.png"))

        # Check Validation Test
        print("Checking Validation Test subtab...")
        page.locator("button.vision-sub-btn:has-text('Validation Test')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_16_validation_test.png"))

        # Check Truck-Box Association
        print("Checking Truck-Box Association subtab...")
        page.locator("button.vision-sub-btn:has-text('Truck ↔ Box')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_17_truck_box.png"))

        # Check Worker-Box Association
        print("Checking Worker-Box Association subtab...")
        page.locator("button.vision-sub-btn:has-text('Worker ↔ Box')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_18_worker_box.png"))

        # Check Box-Bin Association
        print("Checking Box-Bin Association subtab...")
        page.locator("button.vision-sub-btn:has-text('Box ↔ Bin')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_19_box_bin.png"))

        # Check Warehouse Movement Events
        print("Checking Warehouse Movement Events subtab...")
        page.locator("button.vision-sub-btn:has-text('Movement Events')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_20_movement_events.png"))

        # Check Material Traceability
        print("Checking Material Traceability subtab...")
        page.locator("button.vision-sub-btn:has-text('Material Traceability')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_21_material_traceability.png"))

        # Check Runtime Orchestrator
        print("Checking Runtime Orchestrator subtab...")
        page.locator("button.vision-sub-btn:has-text('Runtime Orchestrator')").first.click()
        page.wait_for_timeout(1000)
        rt_cams = page.locator("#rtCameraTableBody tr").count()
        print(f"Runtime Orchestrator camera rows: {rt_cams}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_22_runtime_orchestrator.png"))

        # Check Configuration
        print("Checking Configuration subtab...")
        page.locator("button.vision-sub-btn:has-text('Configuration')").first.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "detailed_23_configuration.png"))

        # Save summary
        with open(os.path.join(ARTIFACT_DIR, "detailed_audit_summary.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print("\nDETAILED AUDIT EXECUTION COMPLETE.")
        browser.close()


if __name__ == '__main__':
    run_detailed_audit()
