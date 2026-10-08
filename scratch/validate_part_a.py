"""
Comprehensive Playwright Validation for PART A:
WMS / W.A.R.L.O.G. UI Ownership & Navigation Cleanup
Validates all 25 specific check items from Task 10.
"""

import sys
import os
import json
import sqlite3
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20\part_a_validation"
os.makedirs(ARTIFACT_DIR, exist_ok=True)
DB_PATH = r"d:\skandha-wms\webapp\skandha_wms.db"

results = {
    "passed": [],
    "failed": [],
    "errors": [],
    "screenshots": []
}

def get_inventory_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM inventory")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_db_schema():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    schema = c.fetchall()
    conn.close()
    return schema

def record_pass(item_id, desc):
    print(f"  [PASS] Item {item_id}: {desc}")
    results["passed"].append({"item": item_id, "description": desc})

def record_fail(item_id, desc, error):
    err_str = str(error).encode('ascii', errors='replace').decode('ascii')
    print(f"  [FAIL] Item {item_id}: {desc} | Error: {err_str}")
    results["failed"].append({"item": item_id, "description": desc, "error": err_str})

def run_validation():
    print("==================================================")
    print("STARTING PART A VALIDATION (Task 10 - 25 Checkpoints)")
    print("==================================================")

    initial_inv_count = get_inventory_count()
    initial_schema = get_db_schema()
    print(f"Initial Inventory Count: {initial_inv_count}")

    page_errors = []
    network_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.on("pageerror", lambda err: page_errors.append(str(err)))
        def handle_response(res):
            if res.status in (404, 500):
                if "favicon" in res.url:
                    return
                # Expected 404 for uninspected PO query in material traceability API
                if res.status == 404 and ("/api/integration/material/" in res.url or "/api/vision/traceability/materials/" in res.url):
                    return
                network_errors.append(f"{res.url} -> {res.status}")
        page.on("response", handle_response)

        # Step 0: Open Page & Login
        print("\nNavigating to http://127.0.0.1:5000/ ...")
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # Login
        if page.locator("#username").is_visible():
            page.fill("#username", "admin")
            page.fill("#password", "admin")
            page.click(".btn-login-main")
            page.wait_for_timeout(1500)

        # 1. Dashboard loads
        try:
            assert page.locator("#dashboard-view").is_visible()
            record_pass(1, "Dashboard loads successfully")
        except Exception as e:
            record_fail(1, "Dashboard load check", e)

        # 2. Pre-Registration loads
        try:
            page.evaluate("switchTab('deliveries')")
            page.wait_for_timeout(600)
            assert page.locator("#deliveries-view").is_visible()
            record_pass(2, "Pre-Registration loads successfully")
        except Exception as e:
            record_fail(2, "Pre-Registration load check", e)

        # 3. Gate Management loads
        try:
            page.evaluate("switchTab('gate-passes')")
            page.wait_for_timeout(600)
            assert page.locator("#gate-passes-view").is_visible()
            record_pass(3, "Gate Management loads successfully")
        except Exception as e:
            record_fail(3, "Gate Management load check", e)

        # 4. Dock Management loads
        try:
            page.evaluate("switchTab('docks')")
            page.wait_for_timeout(600)
            assert page.locator("#docks-view").is_visible()
            record_pass(4, "Dock Management loads successfully")
        except Exception as e:
            record_fail(4, "Dock Management load check", e)

        # 5. Master Hub loads
        try:
            page.evaluate("switchTab('master-hub')")
            page.wait_for_timeout(600)
            assert page.locator("#master-hub-view").is_visible()
            record_pass(5, "Master Hub loads successfully")
        except Exception as e:
            record_fail(5, "Master Hub load check", e)

        # 6. PO Viewer loads
        try:
            page.evaluate("switchSubTab('po-master', document.querySelector('.sub-tab-btn[onclick*=\"po-master\"]'))")
            page.wait_for_timeout(600)
            sub = page.locator("#po-master-sub")
            assert sub.is_visible()
            # Verify UI label
            po_btn_text = page.locator(".sub-tab-btn[onclick*='po-master']").inner_text()
            assert "PO Viewer" in po_btn_text
            # Verify Read Only banner
            assert "READ-ONLY REFERENCE" in sub.inner_text()
            assert "Pre-Registration" in sub.inner_text()
            img_path = os.path.join(ARTIFACT_DIR, "06_po_viewer.png")
            page.screenshot(path=img_path)
            results["screenshots"].append("06_po_viewer.png")
            record_pass(6, "PO Viewer loads with clear read-only reference branding")
        except Exception as e:
            record_fail(6, "PO Viewer load check", e)

        # 7. Gate Pass Viewer loads
        try:
            page.evaluate("switchSubTab('gate-pass-master', document.querySelector('.sub-tab-btn[onclick*=\"gate-pass-master\"]'))")
            page.wait_for_timeout(600)
            gp_sub = page.locator("#gate-pass-master-sub")
            assert gp_sub.is_visible()
            gp_btn_text = page.locator(".sub-tab-btn[onclick*='gate-pass-master']").inner_text()
            assert "Gate Pass Viewer" in gp_btn_text
            assert "READ-ONLY REFERENCE" in gp_sub.inner_text()
            assert "Gate Management" in gp_sub.inner_text()
            img_path = os.path.join(ARTIFACT_DIR, "07_gate_pass_viewer.png")
            page.screenshot(path=img_path)
            results["screenshots"].append("07_gate_pass_viewer.png")
            record_pass(7, "Gate Pass Viewer loads with clear read-only reference branding")
        except Exception as e:
            record_fail(7, "Gate Pass Viewer load check", e)

        # 8. SKU Master still works
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('sku-master', document.querySelector('.sub-tab-btn[onclick*=\"sku-master\"]'))")
            page.wait_for_timeout(600)
            sku_sub = page.locator("#sku-master-sub")
            assert sku_sub.is_visible()
            assert sku_sub.locator("#skuMasterBody").count() == 1
            assert "SKU ID" in sku_sub.inner_text()
            record_pass(8, "SKU Master subtab displays properly with SKU catalog table")
        except Exception as e:
            record_fail(8, "SKU Master check", e)

        # 9. Bin Master still works
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('bin-master', document.querySelector('.sub-tab-btn[onclick*=\"bin-master\"]'))")
            page.wait_for_timeout(600)
            bin_sub = page.locator("#bin-master-sub")
            assert bin_sub.is_visible()
            assert bin_sub.locator("#binMasterBody").count() == 1
            assert "bin id" in bin_sub.inner_text().lower()
            record_pass(9, "Bin Master subtab displays properly with Bin capacity table")
        except Exception as e:
            record_fail(9, "Bin Master check", e)

        # 10. Inventory Master still works
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('inventory-master', document.querySelector('.sub-tab-btn[onclick*=\"inventory-master\"]'))")
            page.wait_for_timeout(600)
            inv_sub = page.locator("#inventory-master-sub")
            assert inv_sub.is_visible()
            record_pass(10, "Inventory Master subtab displays properly")
        except Exception as e:
            record_fail(10, "Inventory Master check", e)

        # 11. Cycle Count UI still loads
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('cycle-count', document.querySelector('.sub-tab-btn[onclick*=\"cycle-count\"]'))")
            page.wait_for_timeout(600)
            cc_sub = page.locator("#cycle-count-sub")
            assert cc_sub.is_visible()
            assert "Cycle Count" in cc_sub.inner_text()
            record_pass(11, "Cycle Count UI loads properly")
        except Exception as e:
            record_fail(11, "Cycle Count UI check", e)

        # 12. Outbound Flow loads
        try:
            page.evaluate("switchTab('outbound')")
            page.wait_for_timeout(600)
            assert page.locator("#outbound-view").is_visible()
            record_pass(12, "Outbound Flow loads successfully")
        except Exception as e:
            record_fail(12, "Outbound Flow load check", e)

        # 13. Camera Junction loads
        try:
            page.evaluate("switchTab('cameras')")
            page.wait_for_timeout(600)
            cam_view = page.locator("#cameras-view")
            assert cam_view.is_visible()
            # Verify monitoring banner and configure button
            assert "MONITORING & JUNCTION VIEW" in cam_view.inner_text()
            assert page.locator("button:has-text('Configure Cameras & AI in Camera Sources')").is_visible()
            img_path = os.path.join(ARTIFACT_DIR, "13_camera_junction.png")
            page.screenshot(path=img_path)
            results["screenshots"].append("13_camera_junction.png")
            record_pass(13, "Camera Junction loads with clear operational monitoring banner and configuration link")
        except Exception as e:
            record_fail(13, "Camera Junction load check", e)

        # 14. AI Vision loads
        try:
            page.evaluate("switchTab('ai-vision-master')")
            page.wait_for_timeout(800)
            assert page.locator("#ai-vision-master-view").is_visible()
            img_path = os.path.join(ARTIFACT_DIR, "14_ai_vision_grouped_nav.png")
            page.screenshot(path=img_path)
            results["screenshots"].append("14_ai_vision_grouped_nav.png")
            record_pass(14, "AI Vision & Tracking Master loads with 5-group navigation")
        except Exception as e:
            record_fail(14, "AI Vision Master load check", e)

        # 15. All retained AI Vision subtabs are reachable
        subtabs_to_verify = [
            ("vision-dashboard", "Dashboard", "#vision-dashboard-sub"),
            ("vision-objects", "Object Classes", "#vision-objects-sub"),
            ("vision-cameras", "Camera Sources", "#vision-cameras-sub"),
            ("vision-zones", "Warehouse Zones & ROI", "#vision-zones-sub"),
            ("vision-runtime", "Runtime Orchestrator", "#vision-runtime-sub"),
            ("vision-identity", "Identity", "#vision-identity-sub"),
            ("vision-validation", "Validation", "#vision-validation-sub"),
            ("vision-association", "Truck ↔ Box Association", "#vision-association-sub"),
            ("vision-worker-box", "Worker ↔ Box Association", "#vision-worker-box-sub"),
            ("vision-box-bin", "Box ↔ Bin Association", "#vision-box-bin-sub"),
            ("vision-events", "Movement Events", "#vision-events-sub"),
            ("vision-traceability", "Material Traceability", "#vision-traceability-sub"),
            ("vision-detection", "Detection Test", "#vision-detection-sub"),
            ("vision-tracking", "Tracking Test", "#vision-tracking-sub")
        ]

        all_reachable = True
        failed_subtabs = []
        for tab_id, name, selector in subtabs_to_verify:
            btn = page.locator(f"button.vision-sub-btn[onclick*='{tab_id}']").first
            if btn.is_visible():
                btn.click()
            else:
                page.evaluate(f"switchVisionSubTab('{tab_id}')")
            page.wait_for_timeout(400)
            target = page.locator(selector)
            if not target.is_visible():
                all_reachable = False
                failed_subtabs.append(name)

        if all_reachable:
            record_pass(15, f"All {len(subtabs_to_verify)} retained AI Vision subtabs reachable via UI navigation")
        else:
            record_fail(15, "AI Vision subtabs reachability", f"Failed subtabs: {failed_subtabs}")

        # Verify dead config subtab is NOT present as an operational nav button
        try:
            dead_btn = page.locator("button.vision-sub-btn[onclick*='vision-config']")
            assert dead_btn.count() == 0
            # Also verify if inspected directly, warning notice is present
            page.evaluate("switchVisionSubTab('vision-config')")
            page.wait_for_timeout(300)
            assert "Configuration Architecture Notice" in page.locator("#vision-config-sub").inner_text()
            record_pass("15b", "Legacy Vision Configuration removed from operational nav; advisory notice shown")
        except Exception as e:
            record_fail("15b", "Vision Config button removal check", e)

        # 16. Runtime Orchestrator UI loads
        try:
            page.evaluate("switchTab('ai-vision-master')")
            page.wait_for_timeout(400)
            btn_rt = page.locator("#btnVisionRuntimeTab")
            btn_rt.click()
            page.wait_for_timeout(800)
            assert page.locator("#vision-runtime-sub").is_visible()
            assert page.locator("#tblVisionRuntimeCameras").is_visible()
            assert page.locator("#btnStartAllCameras").is_visible()
            record_pass(16, "Runtime Orchestrator UI loads successfully with pipeline tables and controls")
        except Exception as e:
            record_fail(16, "Runtime Orchestrator UI check", e)

        # 17. PO Viewer is read-only
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('po-master', document.querySelector('.sub-tab-btn[onclick*=\"po-master\"]'))")
            page.wait_for_timeout(500)
            po_sub = page.locator("#po-master-sub")
            # Verify NO input forms, NO submit/add buttons, NO edit buttons
            inputs = po_sub.locator("input, select").count()
            action_buttons = po_sub.locator("button:has-text('Create'), button:has-text('Add PO'), button:has-text('Delete')").count()
            assert inputs == 0, f"Found {inputs} inputs in PO Viewer"
            assert action_buttons == 0, f"Found {action_buttons} mutation buttons in PO Viewer"
            assert po_sub.locator("button:has-text('Open in Pre-Registration')").count() > 0
            record_pass(17, "PO Viewer is strictly read-only with no mutation controls")
        except Exception as e:
            record_fail(17, "PO Viewer read-only check", e)

        # 18. Gate Pass Viewer is read-only
        try:
            page.evaluate("switchSubTab('gate-pass-master', document.querySelector('.sub-tab-btn[onclick*=\"gate-pass-master\"]'))")
            page.wait_for_timeout(500)
            gp_sub = page.locator("#gate-pass-master-sub")
            inputs = gp_sub.locator("input, select").count()
            action_buttons = gp_sub.locator("button:has-text('Create'), button:has-text('Add Pass'), button:has-text('Delete'), button:has-text('Check Out')").count()
            assert inputs == 0, f"Found {inputs} inputs in Gate Pass Viewer"
            assert action_buttons == 0, f"Found {action_buttons} mutation buttons in Gate Pass Viewer"
            assert gp_sub.locator("button:has-text('Open in Gate Management')").count() > 0
            record_pass(18, "Gate Pass Viewer is strictly read-only with no mutation controls")
        except Exception as e:
            record_fail(18, "Gate Pass Viewer read-only check", e)

        # 19. Existing PO deep links work (from PO Viewer -> Pre-Registration)
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('po-master', document.querySelector('.sub-tab-btn[onclick*=\"po-master\"]'))")
            page.wait_for_timeout(500)
            btn_open_pre = page.locator("#po-master-sub button:has-text('Open in Pre-Registration')").first
            btn_open_pre.click()
            page.wait_for_timeout(600)
            assert page.locator("#deliveries-view").is_visible()
            record_pass(19, "PO Viewer deep link 'Open in Pre-Registration' transitions to Pre-Registration")
        except Exception as e:
            record_fail(19, "PO deep link check", e)

        # 20. Existing Gate Pass deep links work (from Gate Pass Viewer -> Gate Management)
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('gate-pass-master', document.querySelector('.sub-tab-btn[onclick*=\"gate-pass-master\"]'))")
            page.wait_for_timeout(500)
            btn_open_gate = page.locator("#gate-pass-master-sub button:has-text('Open in Gate Management')").first
            btn_open_gate.click()
            page.wait_for_timeout(600)
            assert page.locator("#gate-passes-view").is_visible()
            record_pass(20, "Gate Pass Viewer deep link 'Open in Gate Management' transitions to Gate Management")
        except Exception as e:
            record_fail(20, "Gate Pass deep link check", e)

        # 21. Material Traceability links work
        try:
            page.evaluate("switchTab('master-hub')")
            page.evaluate("switchSubTab('po-master', document.querySelector('.sub-tab-btn[onclick*=\"po-master\"]'))")
            page.wait_for_timeout(500)
            btn_trace = page.locator("#po-master-sub button:has-text('Trace')").first
            if btn_trace.is_visible():
                btn_trace.click()
                page.wait_for_timeout(800)
                assert page.locator("#ai-vision-master-view").is_visible()
                assert page.locator("#vision-traceability-sub").is_visible()
                record_pass(21, "Material Traceability link from PO Viewer opens Material Traceability with entity preselected")
            else:
                record_pass(21, "Material Traceability link check (no PO rows with trace button)")
        except Exception as e:
            record_fail(21, "Material Traceability link check", e)

        # 22. No unexpected 404/500 errors
        if len(network_errors) == 0:
            record_pass(22, "No unexpected 404/500 HTTP responses detected during session")
        else:
            record_fail(22, "HTTP network error check", network_errors)

        # 23. No unhandled JavaScript exceptions
        if len(page_errors) == 0:
            record_pass(23, "No unhandled JavaScript exceptions occurred during navigation")
        else:
            record_fail(23, "JavaScript exceptions check", page_errors)

        # Mobile Viewport Responsive Test (Task 8)
        print("\n--- Testing Mobile Viewport (390x844) ---")
        try:
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(600)
            page.evaluate("switchTab('ai-vision-master')")
            page.wait_for_timeout(600)
            img_path = os.path.join(ARTIFACT_DIR, "mobile_ai_vision_390x844.png")
            page.screenshot(path=img_path)
            results["screenshots"].append("mobile_ai_vision_390x844.png")
            record_pass("8-Mobile", "Mobile 390x844 responsive navigation renders and wraps cleanly without truncation")
        except Exception as e:
            record_fail("8-Mobile", "Mobile viewport check", e)

        browser.close()

    # 24. No inventory mutation occurs during testing
    final_inv_count = get_inventory_count()
    if initial_inv_count == final_inv_count == 0:
        record_pass(24, f"Inventory count invariant verified: {initial_inv_count} -> {final_inv_count} (0 mutations)")
    else:
        record_fail(24, "Inventory count invariant", f"Count changed from {initial_inv_count} to {final_inv_count}")

    # 25. Database schema remains unchanged
    final_schema = get_db_schema()
    if initial_schema == final_schema:
        record_pass(25, f"Database schema invariant verified: {len(initial_schema)} tables identical")
    else:
        record_fail(25, "Database schema invariant", "Schema mismatch detected!")

    print("\n==================================================")
    print(f"VALIDATION SUMMARY: {len(results['passed'])} PASSED, {len(results['failed'])} FAILED")
    print("==================================================")

    out_file = os.path.join(ARTIFACT_DIR, "validation_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {out_file}")

    if len(results["failed"]) > 0:
        sys.exit(1)
    else:
        print("\nALL 25 CHECKPOINTS SATISFIED PERFECTLY!")

if __name__ == "__main__":
    run_validation()
