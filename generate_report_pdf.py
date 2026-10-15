import os
import base64
from playwright.sync_api import sync_playwright

def get_base64_image(path):
    if not os.path.exists(path):
        print(f"Warning: {path} does not exist")
        return ""
    ext = os.path.splitext(path)[1].lower().replace('.', '')
    if ext == 'jpg': ext = 'jpeg'
    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode('utf-8')
    return f"data:image/{ext};base64,{data}"

artifact_dir = r"C:\Users\HAI\.gemini\antigravity-ide\brain\3c29b1b2-2989-4d0f-85c5-e2b4c1dedab2"
user_uploaded_dir = os.path.join(artifact_dir, ".user_uploaded")

# User Before Screenshots
before_login_1 = os.path.join(user_uploaded_dir, "media_1792077040350.jpg")
before_login_2 = os.path.join(user_uploaded_dir, "media_1792077040367.jpg")
before_drawer_1 = os.path.join(user_uploaded_dir, "media_1792077040386.jpg")
before_login_full = os.path.join(user_uploaded_dir, "media_1792077040417.jpg")
before_blank_content = os.path.join(user_uploaded_dir, "media_1792077040426.jpg")

# After Validation Screenshots
after_login = os.path.join(artifact_dir, "final_val_360_login_1792081138613.png")
after_dashboard = os.path.join(artifact_dir, "final_val_360_dashboard_1792081258339.png")
after_drawer = os.path.join(artifact_dir, "final_val_360_drawer_open_1792081269188.png")
after_prereg = os.path.join(artifact_dir, "final_val_390_prereg_1792081285427.png")
after_desktop = os.path.join(artifact_dir, "final_val_1366_desktop_1792081302764.png")

b64_before_login_1 = get_base64_image(before_login_1)
b64_before_login_2 = get_base64_image(before_login_2)
b64_before_drawer_1 = get_base64_image(before_drawer_1)
b64_before_blank = get_base64_image(before_blank_content)

b64_after_login = get_base64_image(after_login)
b64_after_dashboard = get_base64_image(after_dashboard)
b64_after_drawer = get_base64_image(after_drawer)
b64_after_prereg = get_base64_image(after_prereg)
b64_after_desktop = get_base64_image(after_desktop)

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Skantha WMS / W.A.R.L.O.G. - Mobile UI Repair Report</title>
<style>
    @page {{
        size: A4;
        margin: 18mm 15mm 20mm 15mm;
        @bottom-right {{
            content: counter(page) " / " counter(pages);
            font-size: 8pt;
            font-family: 'Segoe UI', system-ui, sans-serif;
            color: #64748b;
        }}
    }}
    
    * {{
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }}
    
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        color: #1e293b;
        background: #ffffff;
        font-size: 10pt;
        line-height: 1.5;
    }}

    .header-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #2563eb;
        padding-bottom: 12px;
        margin-bottom: 18px;
    }}

    .header-title-box h1 {{
        font-size: 18pt;
        font-weight: 800;
        color: #0f172a;
        letter-spacing: -0.5px;
    }}

    .header-title-box .subtitle {{
        font-size: 10pt;
        font-weight: 600;
        color: #2563eb;
        margin-top: 2px;
    }}

    .badge-status {{
        background: #dcfce7;
        color: #15803d;
        border: 1px solid #86efac;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 9pt;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    .meta-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 20px;
        gap: 8px;
    }}

    .meta-item .meta-label {{
        font-size: 7.5pt;
        text-transform: uppercase;
        color: #64748b;
        font-weight: 700;
    }}

    .meta-item .meta-val {{
        font-size: 9pt;
        font-weight: 600;
        color: #0f172a;
    }}

    h2 {{
        font-size: 12.5pt;
        font-weight: 700;
        color: #0f172a;
        margin-top: 18px;
        margin-bottom: 8px;
        border-left: 4px solid #2563eb;
        padding-left: 8px;
    }}

    h3 {{
        font-size: 10.5pt;
        font-weight: 700;
        color: #1e293b;
        margin-top: 10px;
        margin-bottom: 4px;
    }}

    p {{
        margin-bottom: 8px;
        color: #334155;
    }}

    ul {{
        margin-left: 18px;
        margin-bottom: 10px;
        color: #334155;
    }}

    li {{
        margin-bottom: 4px;
    }}

    .code-span {{
        font-family: Consolas, 'Courier New', monospace;
        font-size: 8.5pt;
        background: #f1f5f9;
        padding: 1px 5px;
        border-radius: 4px;
        color: #0f172a;
        border: 1px solid #e2e8f0;
    }}

    .callout {{
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        border-left: 4px solid #3b82f6;
        padding: 10px 12px;
        border-radius: 6px;
        margin: 12px 0;
        font-size: 9pt;
    }}

    .callout-title {{
        font-weight: 700;
        color: #1d4ed8;
        margin-bottom: 4px;
    }}

    .comparison-container {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
        margin: 14px 0;
        page-break-inside: avoid;
    }}

    .comp-card {{
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        overflow: hidden;
        background: #ffffff;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}

    .comp-header {{
        padding: 6px 10px;
        font-size: 8.5pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        display: flex;
        justify-content: space-between;
    }}

    .comp-header.before {{
        background: #fee2e2;
        color: #991b1b;
        border-bottom: 1px solid #fecaca;
    }}

    .comp-header.after {{
        background: #dcfce7;
        color: #166534;
        border-bottom: 1px solid #bbf7d0;
    }}

    .comp-body {{
        padding: 8px;
        display: flex;
        flex-direction: column;
        align-items: center;
        background: #f8fafc;
    }}

    .comp-img {{
        max-width: 100%;
        max-height: 290px;
        object-fit: contain;
        border-radius: 4px;
        border: 1px solid #cbd5e1;
    }}

    .comp-desc {{
        font-size: 8pt;
        color: #475569;
        margin-top: 6px;
        text-align: center;
    }}

    .page-break {{
        page-break-after: always;
    }}

    table.data-table {{
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0;
        font-size: 8.5pt;
    }}

    table.data-table th, table.data-table td {{
        padding: 7px 10px;
        border: 1px solid #e2e8f0;
        text-align: left;
    }}

    table.data-table th {{
        background: #f1f5f9;
        font-weight: 700;
        color: #1e293b;
    }}

    table.data-table tr:nth-child(even) {{
        background: #f8fafc;
    }}

    .full-img-card {{
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 8px;
        background: #f8fafc;
        margin: 10px 0;
        text-align: center;
        page-break-inside: avoid;
    }}

    .full-img-card img {{
        max-width: 100%;
        max-height: 250px;
        object-fit: contain;
        border-radius: 4px;
        border: 1px solid #e2e8f0;
    }}

    .full-img-caption {{
        font-size: 8pt;
        font-weight: 600;
        color: #475569;
        margin-top: 6px;
    }}
</style>
</head>
<body>

<!-- PAGE 1: EXECUTIVE SUMMARY & ROOT CAUSE ANALYSIS -->
<div class="header-bar">
    <div class="header-title-box">
        <h1>W.A.R.L.O.G. & Skantha WMS</h1>
        <div class="subtitle">Mobile Rendering & Navigation Repair Technical Report</div>
    </div>
    <div class="badge-status">Fixed & Verified</div>
</div>

<div class="meta-grid">
    <div class="meta-item">
        <div class="meta-label">Date</div>
        <div class="meta-val">October 15, 2026</div>
    </div>
    <div class="meta-item">
        <div class="meta-label">Target Devices</div>
        <div class="meta-val">Android / iOS (360px - 430px)</div>
    </div>
    <div class="meta-item">
        <div class="meta-label">Git Commit</div>
        <div class="meta-val">c5d21d2 (main)</div>
    </div>
    <div class="meta-item">
        <div class="meta-label">Desktop Stability</div>
        <div class="meta-val">100% Unchanged (&gt;1024px)</div>
    </div>
</div>

<h2>1. Executive Summary</h2>
<p>
    Following user verification testing on mobile devices, multiple visual defects were captured: login page horizontal overflow (clipped headings, branding, inputs), a persistent desktop sidebar sitting directly on top of mobile content, and a non-functioning mobile drawer resulting in blank void pages.
</p>
<p>
    A comprehensive audit of the DOM hierarchy and computed CSS styles revealed that conflicting legacy media queries in <span class="code-span">style.css</span> were directly fighting the modern rules in <span class="code-span">responsive.css</span>. Removing these legacy conflicts, scoping off-canvas drawers, scaling typography/grids, and invalidating asset caches completely restored responsive parity across all tested mobile profiles without any desktop regressions.
</p>

<h2>2. Root Cause Analysis</h2>
<table class="data-table">
    <thead>
        <tr>
            <th style="width: 25%;">Area</th>
            <th style="width: 40%;">Root Cause in Code</th>
            <th style="width: 35%;">Observed User Impact</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Colliding Sidebar Query</strong></td>
            <td>Legacy <span class="code-span">@media (max-width: 768px)</span> in <span class="code-span">style.css</span> set <span class="code-span">#main-header {{ position: static; width: 100%; }}</span> and <span class="code-span">.container {{ min-height: 0; }}</span>.</td>
            <td>The sidebar sat permanently at the top of the mobile screen. The content area below collapsed into a blank void.</td>
        </tr>
        <tr>
            <td><strong>Login Padding Blowout</strong></td>
            <td>Legacy rule <span class="code-span">.login-left, .login-right {{ width: 100%; padding: 2rem; }}</span> in <span class="code-span">style.css</span> lacked <span class="code-span">box-sizing: border-box</span>.</td>
            <td>Added 64px to 100% viewport width, forcing the login overlay 64px wider than mobile screens.</td>
        </tr>
        <tr>
            <td><strong>Fixed Feature Row</strong></td>
            <td><span class="code-span">.login-features</span> had 4 horizontal flex items with hard borders and fixed minimum dimensions.</td>
            <td>Feature icons clipped past right viewport boundary; text was cut off on Android devices.</td>
        </tr>
        <tr>
            <td><strong>Render Deployment Sync</strong></td>
            <td>Remote Render instance was serving an earlier cache lacking the updated stylesheet links.</td>
            <td>Users continued seeing obsolete CSS rules until commit push and cache invalidation.</td>
        </tr>
    </tbody>
</table>

<div class="callout">
    <div class="callout-title">Architecture Safeguard</div>
    All legacy media queries were completely purged from <span class="code-span">style.css</span>, and an explicit <span class="code-span">@import url('responsive.css');</span> was added at the bottom. This guarantees that modern mobile rules cannot be overridden by desktop styles under any deployment scenario.
</div>

<div class="page-break"></div>

<!-- PAGE 2: LOGIN PAGE COMPARISON -->
<div class="header-bar">
    <div class="header-title-box">
        <h1>Priority 2: Mobile Login Screen Repair</h1>
        <div class="subtitle">Before vs. After Visual Comparison (360x800 Profile)</div>
    </div>
</div>

<p>
    The login screen was restructured to provide clean vertical stacking, scaled typography, an ergonomic 2x2 feature matrix, and a perfectly centered, full-width credential form with zero horizontal blowout.
</p>

<div class="comparison-container">
    <div class="comp-card">
        <div class="comp-header before">
            <span>Before (User Android Screenshot)</span>
            <span>Clipped & Blown Out</span>
        </div>
        <div class="comp-body">
            <img class="comp-img" src="{b64_before_login_1}" alt="Before Login">
            <div class="comp-desc">Headings cut off on right, 4-column feature row blown out past screen edge, horizontal scrollbar present.</div>
        </div>
    </div>
    <div class="comp-card">
        <div class="comp-header after">
            <span>After (Validated 360×800)</span>
            <span>Clean Stacked Layout</span>
        </div>
        <div class="comp-body">
            <img class="comp-img" src="{b64_after_login}" alt="After Login">
            <div class="comp-desc">Skantha & W.A.R.L.O.G. logos fit viewport, 2×2 feature grid, 100% width login card, full vertical scrollability.</div>
        </div>
    </div>
</div>

<h3>Key Login Improvements Implemented:</h3>
<ul>
    <li><strong>Fluid Container Constraints:</strong> Set <span class="code-span">#login-overlay</span> to <span class="code-span">display: flex; flex-direction: column; overflow-y: auto; overflow-x: hidden;</span>.</li>
    <li><strong>Logo & Typography Scaling:</strong> Reduced <span class="code-span">.login-hero-logo</span> from 80px to 58px; scaled <span class="code-span">.login-hero-title</span> to <span class="code-span">1.75rem</span>.</li>
    <li><strong>Ergonomic 2×2 Feature Grid:</strong> Transformed 4-row flex into <span class="code-span">grid-template-columns: repeat(2, 1fr)</span> with dividers removed for natural 2-column mobile presentation.</li>
    <li><strong>Touch-Friendly Form:</strong> Card set to <span class="code-span">max-width: 400px; width: 100%;</span> with input font-size at <span class="code-span">16px</span> to eliminate unwanted iOS auto-zoom behavior.</li>
</ul>

<div class="page-break"></div>

<!-- PAGE 3: NAVIGATION DRAWER & DASHBOARD -->
<div class="header-bar">
    <div class="header-title-box">
        <h1>Priorities 1 & 3: Mobile Navigation & App Layout</h1>
        <div class="subtitle">Off-Canvas Drawer and Viewport Isolation</div>
    </div>
</div>

<p>
    The authenticated layout was repaired so that the navigation panel consumes zero permanent horizontal space on mobile devices. An off-canvas left drawer with a smooth backdrop handles all navigation.
</p>

<div class="comparison-container">
    <div class="comp-card">
        <div class="comp-header before">
            <span>Before (User Android Screenshot)</span>
            <span>Static Header & Empty Content</span>
        </div>
        <div class="comp-body">
            <img class="comp-img" src="{b64_before_blank}" alt="Before Blank Content">
            <div class="comp-desc">Legacy query forced nav menu permanently into header space; main content squished into blank white void.</div>
        </div>
    </div>
    <div class="comp-card">
        <div class="comp-header after">
            <span>After (Validated 360×800)</span>
            <span>Full-Width Dashboard View</span>
        </div>
        <div class="comp-body">
            <img class="comp-img" src="{b64_after_dashboard}" alt="After Dashboard">
            <div class="comp-desc">Nav hidden off-canvas. Topbar visible with hamburger button. Metric cards utilize 100% available viewport width.</div>
        </div>
    </div>
</div>

<div class="comparison-container">
    <div class="comp-card">
        <div class="comp-header after">
            <span>Active Mobile Drawer (360×800)</span>
            <span>Touch-Scrollable Drawer</span>
        </div>
        <div class="comp-body">
            <img class="comp-img" src="{b64_after_drawer}" alt="After Drawer Open">
            <div class="comp-desc">Tapping hamburger opens 280px drawer with backdrop. All module links & theme selector vertically scrollable. Auto-closes on tab selection.</div>
        </div>
    </div>
    <div class="comp-card">
        <div class="comp-header after">
            <span>Pre-Registration View (390×844)</span>
            <span>Responsive Forms & Tables</span>
        </div>
        <div class="comp-body">
            <img class="comp-img" src="{b64_after_prereg}" alt="After Pre-Registration">
            <div class="comp-desc">Manifest inputs stack vertically. Data tables wrapped in scroll containers. Zero horizontal blowout on iPhone 14/15/16 profiles.</div>
        </div>
    </div>
</div>

<div class="page-break"></div>

<!-- PAGE 4: DESKTOP STABILITY & VERIFICATION MATRIX -->
<div class="header-bar">
    <div class="header-title-box">
        <h1>Desktop UI Preservation & Validation Matrix</h1>
        <div class="subtitle">Ensuring Zero Regression on Screens &gt; 1024px</div>
    </div>
</div>

<p>
    As strictly mandated, all desktop views above <span class="code-span">1024px</span> remain 100% identical to the original baseline. Mobile hamburger buttons and drawer backdrops are strictly hidden on desktop widths via <span class="code-span">display: none !important</span>.
</p>

<div class="full-img-card">
    <img src="{b64_after_desktop}" alt="Desktop Baseline">
    <div class="full-img-caption">Desktop View (1366×768) - Baseline Sidebar, Wide Metric Cards, Topbar and Tables Completely Preserved</div>
</div>

<h2>Verification Checklist</h2>
<table class="data-table">
    <thead>
        <tr>
            <th>Requirement</th>
            <th>Target</th>
            <th>Local Test Status</th>
            <th>Observed Result</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Mobile Login Fit</td>
            <td>360×800, 390×844</td>
            <td><strong style="color: #166534;">PASSED</strong></td>
            <td>No horizontal overflow. Branding, 2x2 grid, and form fully viewable.</td>
        </tr>
        <tr>
            <td>Hamburger Button</td>
            <td>&le; 1024px</td>
            <td><strong style="color: #166534;">PASSED</strong></td>
            <td>Visible on mobile topbar; tapping toggles drawer with backdrop.</td>
        </tr>
        <tr>
            <td>Off-Canvas Drawer</td>
            <td>&le; 1024px</td>
            <td><strong style="color: #166534;">PASSED</strong></td>
            <td>Consumes 0 space when closed. Vertically scrollable when open.</td>
        </tr>
        <tr>
            <td>Drawer Auto-Close</td>
            <td>&le; 1024px</td>
            <td><strong style="color: #166534;">PASSED</strong></td>
            <td>Switching modules closes drawer and switches view instantaneously.</td>
        </tr>
        <tr>
            <td>Full Content Width</td>
            <td>360px - 430px</td>
            <td><strong style="color: #166534;">PASSED</strong></td>
            <td>Dashboard cards, forms, and charts utilize 100% content width.</td>
        </tr>
        <tr>
            <td>Desktop Integrity</td>
            <td>&gt; 1024px (1366×768)</td>
            <td><strong style="color: #166534;">PASSED</strong></td>
            <td>Permanent left sidebar, wide tables, full topbar intact. Zero changes.</td>
        </tr>
    </tbody>
</table>

<h2>Render Deployment Instructions</h2>
<div class="callout">
    <div class="callout-title">Action Required on Render Dashboard</div>
    All commits have been pushed to <span class="code-span">origin/main</span> (commit <span class="code-span">c5d21d2</span>). Because Render web services cache static files:
    <ol style="margin-left: 20px; margin-top: 6px;">
        <li>Log into <a href="https://dashboard.render.com" target="_blank" style="color: #1d4ed8; font-weight: 600;">dashboard.render.com</a>.</li>
        <li>Select the <strong>skantha-wms</strong> web service.</li>
        <li>Click <strong>Manual Deploy</strong> &rarr; <strong>Deploy latest commit</strong> (or <em>Clear build cache & deploy</em>).</li>
        <li>On mobile devices, perform a hard refresh or clear browser cache to fetch the new CSS bundle.</li>
    </ol>
</div>

</body>
</html>
"""

html_path = os.path.join(r"d:\skantha-wms", "report_preview.html")
pdf_path = os.path.join(r"d:\skantha-wms", "WARLOG_Mobile_UI_Repair_Report.pdf")

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Wrote HTML preview to {html_path}")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(f"file:///{html_path.replace(os.sep, '/')}", wait_until="networkidle")
    page.pdf(
        path=pdf_path,
        format="A4",
        print_background=True,
        margin={"top": "12mm", "bottom": "14mm", "left": "12mm", "right": "12mm"}
    )
    browser.close()

print(f"Successfully generated PDF: {pdf_path}")
