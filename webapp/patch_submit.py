with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

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
                    driver_phone: document.getElementById('expDriverPhone').value,
                    load: document.getElementById('expLoad').value,
                    vendor: document.getElementById('expVendor').value,
                    vendor_email: document.getElementById('expVendorEmail').value,
                    activity: document.getElementById('expActivity').value,
                    unloading_sheet: [{
                        sku: "BOX-GENERIC",
                        description: document.getElementById('expLoad').value,
                        uom: "Boxes",
                        expected: parseInt(document.getElementById('expQty').value) || 0
                    }]
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
                    driver_phone: document.getElementById('expDriverPhone').value,
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

if old_submit in html:
    html = html.replace(old_submit, new_submit)
    with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("Successfully patched submit listener")
else:
    print("old_submit string not found in index.html!")
