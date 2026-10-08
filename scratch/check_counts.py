from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.goto('http://127.0.0.1:5000/')
    page.wait_for_load_state('networkidle')
    page.fill('#username', 'admin')
    page.fill('#password', 'admin')
    page.click('.btn-login-main')
    page.wait_for_timeout(1500)
    
    e_rows = page.locator('#expectedTableBody tr').count()
    gp_rows = page.locator('#gatePassMasterBody tr').count()
    dock_rows = page.locator('#dockTableBody tr').count()
    
    page.evaluate("switchTab('ai-vision-master')")
    page.wait_for_timeout(1000)
    
    page.locator("button.vision-sub-btn:has-text('Object Classes')").first.click()
    page.wait_for_timeout(500)
    obj_rows = page.locator('#objectClassesBody tr').count()
    
    page.locator("button.vision-sub-btn:has-text('Camera Sources')").first.click()
    page.wait_for_timeout(500)
    cam_rows = page.locator('#visionCamerasBody tr').count()
    
    page.locator("button.vision-sub-btn:has-text('Warehouse Zones')").first.click()
    page.wait_for_timeout(500)
    zone_rows = page.locator('#visionZonesBody tr').count()

    page.locator("button.vision-sub-btn:has-text('Runtime Orchestrator')").first.click()
    page.wait_for_timeout(500)
    rt_rows = page.locator('#rtCameraTableBody tr').count()
    
    print(f"VERIFIED DOM: ExpectedDeliveries={e_rows}, GatePassMaster={gp_rows}, DockTable={dock_rows}, ObjectClasses={obj_rows}, CameraSources={cam_rows}, Zones={zone_rows}, RuntimeOrchestratorCameras={rt_rows}")
    browser.close()
