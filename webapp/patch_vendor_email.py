import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Add the vendor email field before the Expected Plate field
old_plate_html = """                        <div>
                            <label>Expected Plate</label>"""
new_email_html = """                        <div style="grid-column: 1 / -1;">
                            <label>Primary Vendor Email (For Invoices)</label>
                            <input type="email" id="expVendorEmail" placeholder="logistics@vendor.com" required style="width: 100%; margin-bottom: 0;">
                        </div>
                        <div>
                            <label>Expected Plate</label>"""
if "id=\"expVendorEmail\"" not in html:
    html = html.replace(old_plate_html, new_email_html)


# Also need to update the submit listener!
# Let's use regex to replace it
old_submit_js = r"driver_phone: document\.getElementById\('expDriverPhone'\)\.value,.*?activity: document\.getElementById\('expActivity'\)\.value,.*?unloading_sheet: manifest"
new_submit_js = """driver_phone: document.getElementById('expDriverPhone').value,
                    vendor_email: document.getElementById('expVendorEmail').value,
                    activity: document.getElementById('expActivity').value,
                    unloading_sheet: manifest"""
html = re.sub(old_submit_js, new_submit_js, html, flags=re.DOTALL)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Patched Vendor Email")
