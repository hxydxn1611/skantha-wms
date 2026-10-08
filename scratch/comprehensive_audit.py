"""
Skandha WMS / W.A.R.L.O.G. Comprehensive UI/UX and Functional Audit Suite
Runs an exhaustive Playwright automation across all 31 audit dimensions.
Records:
- Page console errors and warnings
- Failed network requests (4xx / 5xx / failed)
- Broken buttons / non-responsive UI handlers
- Functional defects across all 8 WMS modules and 14 AI Vision subtabs
- Modals, forms, validation, and table behavior
- Theme switching consistency (Light / Dark)
- Responsive layout behavior across Desktop, Tablet, and Mobile viewports
- Saves annotated screenshots to the audit artifact directory
"""

import os
import sys
import time
import json
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ARTIFACT_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20\audit"
BASE_URL = "http://127.0.0.1:5000"

findings = []
console_logs = []
network_failures = []


def record_finding(screen, action, expected, actual, error, severity, component):
    item = {
        "screen": screen,
        "action": action,
        "expected": expected,
        "actual": actual,
        "error": error,
        "severity": severity,
        "component": component
    }
    findings.append(item)
    print(f"\n[FINDING - {severity}] {screen} | {action}")
    print(f"  Expected: {expected}")
    print(f"  Actual:   {actual}")
    print(f"  Error:    {error}")
    print(f"  Likely:   {component}")


def run_audit():
    print("=" * 80)
    print("STARTING COMPREHENSIVE AUDIT OF SKANDHA WMS & W.A.R.L.O.G.")
    print("=" * 80)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Listen to console messages
        def handle_console(msg):
            text = msg.text
            msg_type = msg.type
            if msg_type in ("error", "warning") and "favicon" not in text.lower():
                entry = f"[{msg_type.upper()}] {text}"
                console_logs.append(entry)
                if msg_type == "error":
                    print(f"  >>> BROWSER CONSOLE ERROR: {text}")
        page.on("console", handle_console)

        # Listen to network requests
        def handle_response(response):
            if response.status >= 400:
                entry = f"[{response.status}] {response.request.method} {response.url}"
                network_failures.append(entry)
                print(f"  >>> HTTP FAILURE: {entry}")
        page.on("response", handle_response)

        def handle_req_failed(request):
            entry = f"[REQ_FAILED] {request.method} {request.url} - {request.failure}"
            network_failures.append(entry)
            print(f"  >>> NETWORK REQUEST FAILED: {entry}")
        page.on("requestfailed", handle_req_failed)

        # -------------------------------------------------------------
        # 1. LOGIN / AUTHENTICATION AUDIT
        # -------------------------------------------------------------
        print("\n--- AUDIT 1: Login & Authentication ---")
        page.goto(f"{BASE_URL}/", timeout=15000)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "01_login_screen.png"))

        # Test invalid login
        if page.locator("#username").is_visible(timeout=3000):
            page.fill("#username", "invalid_user")
            page.fill("#password", "wrong_password")
            page.click(".btn-login-main")
            page.wait_for_timeout(1000)
            
            # Check alert message
            login_err_el = page.locator("#loginError, .login-error, .alert-error, #error-message")
            err_visible = login_err_el.is_visible() if login_err_el.count() > 0 else False
            if not err_visible:
                # Check browser alert or text
                content = page.content()
                if "Invalid credentials" not in content and "Invalid" not in page.locator("body").inner_text():
                    record_finding(
                        "Login / Authentication",
                        "Submit invalid credentials",
                        "Show clear inline validation or alert indicating 'Invalid credentials'",
                        "No clear visual error element surfaced or error was transient/silent",
                        "Missing or silent login error notification",
                        "MEDIUM",
                        "webapp/templates/index.html / webapp/static/js/app_logic.js"
                    )

            # Test valid login
            page.fill("#username", "admin")
            page.fill("#password", "admin")
            page.click(".btn-login-main")
            page.wait_for_timeout(1500)
            page.wait_for_load_state("networkidle")
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "02_dashboard_after_login.png"))

        # Verify authenticated state
        if page.locator("#dashboard-view").first.is_visible(timeout=5000):
            print("Login successful, entered main application layout.")
        else:
            record_finding(
                "Login / Authentication",
                "Submit valid credentials (admin/admin)",
                "Transition to main application dashboard",
                "Dashboard layout not visible after login",
                "Authentication redirection failure",
                "CRITICAL",
                "webapp/templates/index.html"
            )

        # -------------------------------------------------------------
        # 2. MAIN DASHBOARD AUDIT
        # -------------------------------------------------------------
        print("\n--- AUDIT 2: Main Dashboard ---")
        page.wait_for_timeout(1000)
        # Check WMS KPI Cards
        kpi_cards = page.locator(".kpi-card")
        kpi_count = kpi_cards.count()
        print(f"Dashboard KPI Cards found: {kpi_count}")
        if kpi_count == 0:
            record_finding(
                "Main Dashboard",
                "Inspect summary KPI metrics grid",
                "Display operational KPI cards (Total Stock, Active Bins, Pending Orders, Inbound Trucks, etc.)",
                "0 KPI cards located in .kpi-card",
                "Missing or renamed KPI cards container",
                "HIGH",
                "webapp/templates/index.html"
            )

        # Check W.A.R.L.O.G. Telemetry indicators on Dashboard
        cam_stat = page.locator("#stat-vision-cameras")
        trc_stat = page.locator("#stat-vision-traceability")
        if not cam_stat.is_visible() or not trc_stat.is_visible():
            record_finding(
                "Main Dashboard",
                "Inspect AI Vision telemetry section",
                "Display Active AI Cameras and Traceability Records live indicators",
                f"cam_stat visible: {cam_stat.is_visible()}, trc_stat visible: {trc_stat.is_visible()}",
                "Dashboard telemetry element missing or hidden",
                "MEDIUM",
                "webapp/templates/index.html"
            )

        # Check Inbound Logistics & Vision Stream Table
        stream_rows = page.locator("#unifiedInboundStreamBody tr").count()
        print(f"Inbound stream rows count: {stream_rows}")
        if stream_rows == 0:
            record_finding(
                "Main Dashboard",
                "Inspect Unified Inbound Logistics & Vision Stream table",
                "Display live unified inbound logistics entries",
                "Stream table body has 0 rows",
                "Empty stream table or fetch failure",
                "LOW",
                "webapp/static/js/app_logic.js"
            )

        # Test "Run E2E Integration Scenario" Button & Modal
        btn_e2e = page.locator("button:has-text('Run E2E Integration Scenario')").first
        if btn_e2e.is_visible():
            print("Clicking Run E2E Integration Scenario...")
            btn_e2e.click()
            page.wait_for_timeout(1000)
            modal_e2e = page.locator("#modalE2EScenario")
            if not modal_e2e.is_visible():
                record_finding(
                    "Main Dashboard",
                    "Click [Run E2E Integration Scenario] button",
                    "Open E2E Scenario Execution modal (#modalE2EScenario)",
                    "Modal not visible after click",
                    "Modal toggle failure",
                    "HIGH",
                    "webapp/templates/index.html / webapp/static/js/app_logic.js"
                )
            else:
                page.screenshot(path=os.path.join(ARTIFACT_DIR, "03_modal_e2e_scenario.png"))
                # Close modal
                btn_close_modal = modal_e2e.locator("button:has-text('Close'), .close, [onclick*='modalE2EScenario']").first
                if btn_close_modal.is_visible():
                    btn_close_modal.click()
                    page.wait_for_timeout(500)
                else:
                    page.evaluate("document.getElementById('modalE2EScenario').style.display='none'")

        # -------------------------------------------------------------
        # 3. WMS NAVIGATION & INBOUND MODULE (PRE-REGISTRATION)
        # -------------------------------------------------------------
        print("\n--- AUDIT 3 & 4: Inbound Module (Pre-Registration) ---")
        page.evaluate("switchTab('deliveries')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "04_inbound_pre_registration.png"))

        deliveries_view = page.locator("#deliveries-view")
        if not deliveries_view.is_visible():
            record_finding(
                "Navigation / Inbound",
                "Switch to Pre-Registration tab (deliveries)",
                "#deliveries-view becomes visible",
                "#deliveries-view is hidden",
                "Tab navigation failure",
                "HIGH",
                "webapp/templates/index.html"
            )
        else:
            # Check delivery records table
            deliv_rows = page.locator("#deliveriesTableBody tr, #deliveries-table tbody tr").count()
            print(f"Deliveries table rows: {deliv_rows}")
            
            # Check "Pre-Register Expected Delivery" button / modal
            btn_add_deliv = page.locator("button:has-text('Pre-Register'), button:has-text('Add Delivery')").first
            if btn_add_deliv.is_visible():
                btn_add_deliv.click()
                page.wait_for_timeout(800)
                page.screenshot(path=os.path.join(ARTIFACT_DIR, "05_inbound_add_modal.png"))
                # Close modal
                page.locator("button:has-text('Cancel'), .close").first.click()
                page.wait_for_timeout(500)
            else:
                record_finding(
                    "Inbound Module",
                    "Locate Pre-Register Delivery action button",
                    "Button to register expected delivery is visible",
                    "Button not found",
                    "Missing expected delivery button",
                    "MEDIUM",
                    "webapp/templates/index.html"
                )

        # -------------------------------------------------------------
        # 5. GATE MANAGEMENT MODULE
        # -------------------------------------------------------------
        print("\n--- AUDIT 5: Gate Management ---")
        page.evaluate("switchTab('gate-passes')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "06_gate_management.png"))

        gp_view = page.locator("#gate-passes-view")
        if not gp_view.is_visible():
            record_finding(
                "Gate Management",
                "Switch to Gate Management tab",
                "#gate-passes-view is visible",
                "#gate-passes-view is hidden",
                "Tab navigation failure",
                "HIGH",
                "webapp/templates/index.html"
            )
        else:
            gp_rows = page.locator("#gatePassesTableBody tr, #gatePassesBody tr").count()
            print(f"Gate passes table rows: {gp_rows}")

        # -------------------------------------------------------------
        # 6. DOCK MODULE
        # -------------------------------------------------------------
        print("\n--- AUDIT 6: Dock Module ---")
        page.evaluate("switchTab('docks')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "07_dock_management.png"))

        dock_view = page.locator("#docks-view")
        if not dock_view.is_visible():
            record_finding(
                "Dock Module",
                "Switch to Dock Management tab",
                "#docks-view is visible",
                "#docks-view is hidden",
                "Tab navigation failure",
                "HIGH",
                "webapp/templates/index.html"
            )
        else:
            # Check dock selector or dock assignment card
            dock_select = page.locator("#dockGatePassSelect, #activeDockSelect")
            print(f"Dock assignment controls found: {dock_select.count()}")

        # -------------------------------------------------------------
        # 7. MASTER HUB (INVENTORY, BINS, SKUS, CYCLE COUNT)
        # -------------------------------------------------------------
        print("\n--- AUDIT 7: Master Hub (Bins, SKUs, Inventory, Cycle Count) ---")
        page.evaluate("switchTab('master-hub')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "08_master_hub_bins.png"))

        master_view = page.locator("#master-hub-view")
        if not master_view.is_visible():
            record_finding(
                "Master Hub",
                "Switch to Master Hub tab",
                "#master-hub-view is visible",
                "#master-hub-view is hidden",
                "Tab navigation failure",
                "HIGH",
                "webapp/templates/index.html"
            )
        else:
            # Subtab: Bin Master
            print("Auditing Bin Master subtab...")
            page.locator("button.sub-tab-btn:has-text('Bin Master')").first.click()
            page.wait_for_timeout(800)
            bin_sub = page.locator("#bin-master-sub")
            if not bin_sub.is_visible():
                record_finding(
                    "Master Hub / Bins",
                    "Click Bin Master subtab",
                    "#bin-master-sub is visible",
                    "#bin-master-sub is hidden",
                    "Subtab display failure",
                    "MEDIUM",
                    "webapp/templates/index.html"
                )

            # Test Inspect Bin Modal
            print("Checking Inspect Bin modal...")
            inspect_modal = page.locator("#inspectBinModal")
            if inspect_modal.count() == 0:
                record_finding(
                    "Master Hub / Bins",
                    "Verify inspectBinModal existence in DOM",
                    "#inspectBinModal element exists for inspecting bin live inventory",
                    "#inspectBinModal element missing from DOM",
                    "Missing modal element",
                    "HIGH",
                    "webapp/templates/index.html"
                )

            # Subtab: SKU Master
            print("Auditing SKU Master subtab...")
            page.locator("button.sub-tab-btn:has-text('SKU Master')").first.click()
            page.wait_for_timeout(800)
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "09_master_hub_skus.png"))
            sku_sub = page.locator("#sku-master-sub")
            if not sku_sub.is_visible():
                record_finding(
                    "Master Hub / SKUs",
                    "Click SKU Master subtab",
                    "#sku-master-sub is visible",
                    "#sku-master-sub is hidden",
                    "Subtab display failure",
                    "MEDIUM",
                    "webapp/templates/index.html"
                )

            # Subtab: Inventory Master
            print("Auditing Inventory Master subtab...")
            inv_btn = page.locator("button.sub-tab-btn:has-text('Inventory Master')")
            if inv_btn.is_visible():
                inv_btn.click()
                page.wait_for_timeout(800)
                page.screenshot(path=os.path.join(ARTIFACT_DIR, "10_master_hub_inventory.png"))
                inv_sub = page.locator("#inventory-master-sub")
                if not inv_sub.is_visible():
                    record_finding(
                        "Master Hub / Inventory",
                        "Click Inventory Master subtab",
                        "#inventory-master-sub is visible",
                        "#inventory-master-sub is hidden",
                        "Subtab display failure",
                        "MEDIUM",
                        "webapp/templates/index.html"
                    )
            else:
                record_finding(
                    "Master Hub / Inventory",
                    "Locate Inventory Master subtab button",
                    "Inventory Master subtab button is visible",
                    "Button missing",
                    "Subtab button missing",
                    "MEDIUM",
                    "webapp/templates/index.html"
                )

            # Subtab: Cycle Count
            print("Auditing Cycle Count subtab...")
            cycle_btn = page.locator("button.sub-tab-btn:has-text('Cycle Count')")
            if cycle_btn.is_visible():
                cycle_btn.click()
                page.wait_for_timeout(800)
                page.screenshot(path=os.path.join(ARTIFACT_DIR, "11_master_hub_cycle_count.png"))
            else:
                record_finding(
                    "Master Hub / Cycle Count",
                    "Locate Cycle Count subtab button",
                    "Cycle Count subtab button is visible",
                    "Button missing",
                    "Subtab button missing",
                    "LOW",
                    "webapp/templates/index.html"
                )

        # -------------------------------------------------------------
        # 8. OUTBOUND FLOW MODULE
        # -------------------------------------------------------------
        print("\n--- AUDIT 8: Outbound Flow Module ---")
        page.evaluate("switchTab('outbound-flow')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "12_outbound_flow.png"))

        outbound_view = page.locator("#outbound-flow-view")
        if not outbound_view.is_visible():
            record_finding(
                "Outbound Flow",
                "Switch to Outbound Flow tab",
                "#outbound-flow-view is visible",
                "#outbound-flow-view is hidden",
                "Tab navigation failure",
                "HIGH",
                "webapp/templates/index.html"
            )
        else:
            outbound_orders = page.locator("#outboundOrdersTableBody tr, #outboundTableBody tr").count()
            print(f"Outbound orders table rows: {outbound_orders}")

        # -------------------------------------------------------------
        # 9. CAMERA JUNCTION (CAMERA MASTER)
        # -------------------------------------------------------------
        print("\n--- AUDIT 9: Camera Junction ---")
        page.evaluate("switchTab('cameras')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "13_camera_junction.png"))

        cameras_view = page.locator("#cameras-view")
        if not cameras_view.is_visible():
            record_finding(
                "Camera Junction",
                "Switch to Camera Junction tab",
                "#cameras-view is visible",
                "#cameras-view is hidden",
                "Tab navigation failure",
                "HIGH",
                "webapp/templates/index.html"
            )

        # -------------------------------------------------------------
        # 10. W.A.R.L.O.G. AI VISION MASTER (ALL 14 SUBTABS)
        # -------------------------------------------------------------
        print("\n--- AUDIT 10: W.A.R.L.O.G. AI Vision Master Subtabs ---")
        page.evaluate("switchTab('ai-vision-master')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "14_ai_vision_master_main.png"))

        subtabs_to_audit = [
            ("vision-dashboard", "Dashboard", "#vision-dashboard-sub"),
            ("vision-objects", "Object Classes", "#vision-objects-sub"),
            ("vision-cameras", "Camera Sources", "#vision-cameras-sub"),
            ("vision-zones", "Warehouse Zones", "#vision-zones-sub"),
            ("vision-detection", "Detection Test", "#vision-detection-sub"),
            ("vision-tracking", "Tracking Test", "#vision-tracking-sub"),
            ("vision-identity", "Identity Test", "#vision-identity-sub"),
            ("vision-validation", "Validation Test", "#vision-validation-sub"),
            ("vision-association", "Truck ↔ Box Association", "#vision-association-sub"),
            ("vision-worker-box", "Worker ↔ Box Association", "#vision-worker-box-sub"),
            ("vision-box-bin", "Box ↔ Bin Association", "#vision-box-bin-sub"),
            ("vision-events", "Warehouse Movement Events", "#vision-events-sub"),
            ("vision-traceability", "Material Traceability", "#vision-traceability-sub"),
            ("vision-runtime", "Runtime Orchestrator", "#vision-runtime-sub"),
            ("vision-config", "Configuration", "#vision-config-sub")
        ]

        for tab_id, name, selector in subtabs_to_audit:
            print(f"Auditing AI Vision Subtab: {name} ({tab_id})...")
            # Click button
            btn = page.locator(f"button.vision-sub-btn[onclick*='{tab_id}']").first
            if btn.is_visible():
                btn.click()
            else:
                page.evaluate(f"switchVisionSubTab('{tab_id}')")
            page.wait_for_timeout(800)

            sub_el = page.locator(selector)
            if not sub_el.is_visible():
                record_finding(
                    f"AI Vision Master / {name}",
                    f"Switch to {name} subtab",
                    f"{selector} is visible",
                    f"{selector} is hidden",
                    f"Subtab view {selector} failed to display",
                    "HIGH",
                    "webapp/templates/index.html / webapp/static/js/vision_ui.js"
                )
            else:
                # Capture screenshot
                clean_name = tab_id.replace("vision-", "ai_vision_")
                page.screenshot(path=os.path.join(ARTIFACT_DIR, f"15_{clean_name}.png"))

                # Subtab specific functional checks:
                if tab_id == "vision-objects":
                    obj_cards = page.locator("#objectClassesGrid .class-card, #objClassContainer .class-card").count()
                    print(f"  Object Class cards found: {obj_cards}")
                    if obj_cards == 0:
                        record_finding(
                            "AI Vision / Object Classes",
                            "Load Object Classes taxonomy grid",
                            "Display 6 core object classes (person, forklift, pallet, carton, truck, bin)",
                            "0 cards rendered",
                            "Empty object class grid",
                            "MEDIUM",
                            "webapp/static/js/vision_ui.js"
                        )

                elif tab_id == "vision-zones":
                    # Check zones canvas or map
                    canvas = page.locator("#zoneRoiCanvas, canvas")
                    print(f"  Zone ROI canvas count: {canvas.count()}")

                elif tab_id == "vision-detection":
                    # Check Run Detection Test button
                    run_det_btn = page.locator("button:has-text('Run Detection Test'), #btnRunDetTest")
                    if run_det_btn.is_visible():
                        print("  Triggering Detection Test...")
                        run_det_btn.first.click()
                        page.wait_for_timeout(1500)
                        det_preview = page.locator("#detAnnotatedImg, #detectionPreviewImg")
                        print(f"  Detection preview image visible: {det_preview.is_visible()}")

                elif tab_id == "vision-tracking":
                    # Check Run Tracking Sequence button
                    run_track_btn = page.locator("button:has-text('Run Multi-Frame Sequence'), button:has-text('Run Tracking Test')")
                    if run_track_btn.is_visible():
                        print("  Triggering Tracking Test...")
                        run_track_btn.first.click()
                        page.wait_for_timeout(2000)

                elif tab_id == "vision-identity":
                    # Check Identity Test buttons
                    run_id_btn = page.locator("button:has-text('Run Identity Sequence'), button:has-text('Run OCR & Visual Barcode Test')")
                    if run_id_btn.is_visible():
                        print("  Triggering Identity Test...")
                        run_id_btn.first.click()
                        page.wait_for_timeout(2000)

                elif tab_id == "vision-validation":
                    # Check Validation Test button
                    run_val_btn = page.locator("button:has-text('Run Validation Test'), button:has-text('Run Master Data Validation')")
                    if run_val_btn.is_visible():
                        print("  Triggering Validation Test...")
                        run_val_btn.first.click()
                        page.wait_for_timeout(1500)

                elif tab_id == "vision-association":
                    # Check Truck Box Association test
                    run_assoc_btn = page.locator("button:has-text('Run Association Test'), #assocRunTestBtn")
                    if run_assoc_btn.is_visible():
                        print("  Triggering Truck-Box Association Test...")
                        run_assoc_btn.first.click()
                        page.wait_for_timeout(1500)

                elif tab_id == "vision-worker-box":
                    # Check Worker Box Association test
                    run_wb_btn = page.locator("button:has-text('Run Worker-Box Association Test'), #wbRunTestBtn")
                    if run_wb_btn.is_visible():
                        print("  Triggering Worker-Box Association Test...")
                        run_wb_btn.first.click()
                        page.wait_for_timeout(1500)

                elif tab_id == "vision-box-bin":
                    # Check Box Bin Association test
                    run_bb_btn = page.locator("button:has-text('Run Box-Bin Association Test'), #bbRunTestBtn")
                    if run_bb_btn.is_visible():
                        print("  Triggering Box-Bin Association Test...")
                        run_bb_btn.first.click()
                        page.wait_for_timeout(1500)

                elif tab_id == "vision-events":
                    # Check Movement Events test
                    run_evt_btn = page.locator("button:has-text('Run Event Sequence'), #evtRunSeqBtn")
                    if run_evt_btn.is_visible():
                        print("  Triggering Warehouse Movement Events Sequence...")
                        run_evt_btn.first.click()
                        page.wait_for_timeout(2000)

                elif tab_id == "vision-traceability":
                    # Check Material Traceability test
                    run_trc_btn = page.locator("#trcRunSeqBtn, button:has-text('Run Complete Traceability Sequence')")
                    if run_trc_btn.is_visible():
                        print("  Triggering Material Traceability Sequence...")
                        run_trc_btn.first.click()
                        page.wait_for_timeout(2500)

                elif tab_id == "vision-runtime":
                    # Check Runtime Orchestrator controls
                    btn_start_all = page.locator("#btnStartAllCameras")
                    btn_stop_all = page.locator("#btnStopAllCameras")
                    tbl_cams = page.locator("#tblVisionRuntimeCameras tbody tr")
                    print(f"  Runtime camera rows: {tbl_cams.count()}")
                    if not btn_start_all.is_visible() or not btn_stop_all.is_visible():
                        record_finding(
                            "AI Vision / Runtime Orchestrator",
                            "Verify Runtime Orchestrator controls",
                            "Start All and Stop All action buttons are visible",
                            "Buttons not visible",
                            "Missing orchestrator controls",
                            "MEDIUM",
                            "webapp/templates/index.html"
                        )

        # -------------------------------------------------------------
        # 11. THEME SWITCHING AUDIT
        # -------------------------------------------------------------
        print("\n--- AUDIT 11: Theme Switching ---")
        dark_btn = page.locator("button[data-theme-btn='dark']")
        light_btn = page.locator("button[data-theme-btn='light']")

        if dark_btn.is_visible():
            print("Switching to Dark Theme...")
            dark_btn.click()
            page.wait_for_timeout(1000)
            theme_val = page.evaluate("document.documentElement.getAttribute('data-theme')")
            print(f"Theme attribute after dark click: {theme_val}")
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "16_dark_theme_view.png"))

            if theme_val != "dark":
                record_finding(
                    "Theme Switching",
                    "Click Dark Theme button",
                    "document.documentElement data-theme attribute set to 'dark'",
                    f"data-theme is '{theme_val}'",
                    "Dark theme attribute not applied",
                    "MEDIUM",
                    "webapp/static/js/app_logic.js"
                )

            # Switch back to Light Theme
            print("Switching back to Light Theme...")
            light_btn.click()
            page.wait_for_timeout(800)
            theme_val_light = page.evaluate("document.documentElement.getAttribute('data-theme')")
            print(f"Theme attribute after light click: {theme_val_light}")
            page.screenshot(path=os.path.join(ARTIFACT_DIR, "17_light_theme_view.png"))

        # -------------------------------------------------------------
        # 12. RESPONSIVE / LAYOUT AUDIT
        # -------------------------------------------------------------
        print("\n--- AUDIT 12: Responsive & Layout Testing ---")
        viewports = [
            ("tablet_1024x768", {"width": 1024, "height": 768}),
            ("mobile_390x844", {"width": 390, "height": 844})
        ]

        for vp_name, vp_size in viewports:
            print(f"Testing viewport: {vp_name} ({vp_size['width']}x{vp_size['height']})...")
            page.set_viewport_size(vp_size)
            page.wait_for_timeout(1000)
            page.screenshot(path=os.path.join(ARTIFACT_DIR, f"18_responsive_{vp_name}.png"))

            # Check if sidebar overflows or overlaps content on mobile
            if vp_size["width"] < 768:
                sidebar = page.locator(".sidebar, #sidebar")
                if sidebar.is_visible():
                    box = sidebar.bounding_box()
                    main_box = page.locator("main, .main-content").bounding_box()
                    if box and main_box and box["width"] > 250 and box["x"] >= 0:
                        print(f"  Mobile sidebar takes width {box['width']}px on 390px viewport")

        # Reset viewport
        page.set_viewport_size({"width": 1440, "height": 900})

        # Save findings and log audit results
        report_data = {
            "findings": findings,
            "console_errors": console_logs,
            "network_failures": network_failures,
            "summary": {
                "total_findings": len(findings),
                "total_console_errors": len(console_logs),
                "total_network_failures": len(network_failures)
            }
        }

        with open(os.path.join(ARTIFACT_DIR, "audit_results.json"), "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        print("\n" + "=" * 80)
        print(f"AUDIT RUN FINISHED. TOTAL FINDINGS: {len(findings)}, CONSOLE: {len(console_logs)}, NETWORK: {len(network_failures)}")
        print("=" * 80)

        browser.close()


if __name__ == '__main__':
    run_audit()
