with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

old_fields = """                        <div>
                            <label>Expected Load *</label> 
                            <input type="text" id="expLoad" placeholder="Electronics" required style="width: 100%; margin-bottom: 0;">
                        </div>
                        <div>
                            <label>Expected Qty (Boxes) *</label> 
                            <input type="number" id="expQty" placeholder="50" value="50" required style="width: 100%; margin-bottom: 0;">
                        </div>

                        <div>
                            <label>Vendor *</label> 
                            <input type="text" id="expVendor" placeholder="Samsung Electronics" required style="width: 100%; margin-bottom: 0;">
                        </div>
                        <div>
                            <label>Vendor Email *</label> 
                            <input type="email" id="expVendorEmail" placeholder="logistics@vendor.com" required style="width: 100%; margin-bottom: 0;">
                        </div>"""

new_fields = """                        <div style="grid-column: 1 / -1; border-top: 1px solid var(--border-light); padding-top: 1rem; margin-top: 0.5rem;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 0.5rem;">
                                <label style="margin:0; font-size:1rem; color:var(--primary-navy);">Inbound Manifest (Expected Items)</label>
                                <button type="button" class="btn-secondary" onclick="addManifestLine()" style="font-size:0.75rem; padding:4px 8px;">+ Add Line</button>
                            </div>
                            <div id="manifestLinesContainer" style="display:flex; flex-direction:column; gap:0.5rem; max-height: 250px; overflow-y:auto; padding-right:5px;">
                            </div>
                        </div>"""

html = html.replace(old_fields, new_fields)


add_manifest_js = """
    <script>
        window.manifestLineCount = 0;
        window.addManifestLine = async function() {
            window.manifestLineCount++;
            const id = window.manifestLineCount;
            const container = document.getElementById('manifestLinesContainer');
            
            const lineDiv = document.createElement('div');
            lineDiv.id = `manifestLine_${id}`;
            lineDiv.style.cssText = "display:grid; grid-template-columns: 2fr 2fr 1fr 30px; gap:8px; align-items:center; background:var(--panel-subtle); padding:8px; border-radius:6px; border:1px solid var(--border-light);";
            
            let skuOptions = '<option value="">Select SKU...</option>';
            if(window.globalSkus && window.globalSkus.length > 0) {
                window.globalSkus.forEach(s => {
                    skuOptions += `<option value="${s.sku_id}">${s.sku_id} - ${s.name}</option>`;
                });
            } else {
                try {
                    const res = await fetch('/api/skus');
                    const skus = await res.json();
                    window.globalSkus = skus;
                    skus.forEach(s => {
                        skuOptions += `<option value="${s.sku_id}">${s.sku_id} - ${s.name}</option>`;
                    });
                } catch(e){}
            }

            lineDiv.innerHTML = `
                <select id="manifestSku_${id}" required style="margin:0; padding:6px; font-size:0.8rem;" title="SKU">${skuOptions}</select>
                <input type="text" id="manifestVendor_${id}" placeholder="Vendor Name" required style="margin:0; padding:6px; font-size:0.8rem;" title="Vendor">
                <input type="number" id="manifestQty_${id}" placeholder="Qty" required min="1" style="margin:0; padding:6px; font-size:0.8rem;" title="Expected Qty">
                <button type="button" onclick="document.getElementById('manifestLine_${id}').remove()" style="background:none; border:none; color:var(--danger); cursor:pointer; font-size:1.2rem; padding:0;" title="Remove Line">&times;</button>
            `;
            container.appendChild(lineDiv);
        };
        
        setTimeout(() => { if(document.getElementById('manifestLinesContainer')) window.addManifestLine(); }, 1000);
    </script>
"""
if "window.addManifestLine" not in html:
    html = html.replace("</body>", add_manifest_js + "\n</body>")


old_submit = """        document.getElementById('addDeliveryForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await fetch('/api/deliveries', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    po_number: document.getElementById('expPO').value,
                    expected_date: document.getElementById('expDate').value,
                    plate: document.getElementById('expPlate').value,
                    driver_name: document.getElementById('expDriver').value,
                    driver_phone: document.getElementById('expPhone').value,
                    vendor: document.getElementById('expVendor').value,
                    vendor_email: document.getElementById('expVendorEmail').value,
                    load: document.getElementById('expLoad').value,
                    qty: document.getElementById('expQty').value,
                    activity: document.getElementById('expActivity').value
                })
            });
            e.target.reset();
            document.getElementById('expDate').valueAsDate = new Date();
            fetchDeliveries();
            pollData();
        });"""

new_submit = """        document.getElementById('addDeliveryForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const manifestContainer = document.getElementById('manifestLinesContainer');
            const lines = manifestContainer.children;
            const manifest = [];
            for (let i = 0; i < lines.length; i++) {
                const lineId = lines[i].id.split('_')[1];
                const sku = document.getElementById(`manifestSku_${lineId}`).value;
                const vendor = document.getElementById(`manifestVendor_${lineId}`).value;
                const qty = parseInt(document.getElementById(`manifestQty_${lineId}`).value);
                if(sku && vendor && qty > 0) {
                    manifest.push({ sku_id: sku, vendor: vendor, expected: qty });
                }
            }

            if (manifest.length === 0) {
                alert("Please add at least one item to the Inbound Manifest.");
                return;
            }

            await fetch('/api/deliveries', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    po_number: document.getElementById('expPO').value,
                    expected_date: document.getElementById('expDate').value,
                    plate: document.getElementById('expPlate').value,
                    driver_name: document.getElementById('expDriver').value,
                    driver_phone: document.getElementById('expPhone').value,
                    activity: document.getElementById('expActivity').value,
                    unloading_sheet: manifest
                })
            });
            e.target.reset();
            document.getElementById('manifestLinesContainer').innerHTML = '';
            window.addManifestLine();
            document.getElementById('expDate').valueAsDate = new Date();
            fetchDeliveries();
            pollData();
        });"""

html = html.replace(old_submit, new_submit)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Safely patched index.html for inbound manifest.")
