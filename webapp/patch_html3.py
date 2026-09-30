import re

with open('templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

new_views = """
        <!-- VEHICLE MASTER VIEW -->
        <div id="vehicle-log-view" class="view-section">
            <div class="glass-panel">
                <h2>Vehicle Master Log</h2>
                <p style="color:var(--text-muted);">Historical log of all vehicle check-ins and check-outs.</p>
                <div style="overflow-x:auto;">
                    <table style="width:100%;">
                        <thead>
                            <tr>
                                <th>Gate Pass ID</th><th>Plate</th><th>Driver</th><th>Status</th><th>Entry Time</th><th>Exit Time</th>
                            </tr>
                        </thead>
                        <tbody id="vehicleLogBody"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- INVOICE MASTER VIEW -->
        <div id="invoices-view" class="view-section">
            <div class="glass-panel">
                <h2>Invoice Master</h2>
                <p style="color:var(--text-muted);">Generated invoices for completed gate passes.</p>
                <div style="overflow-x:auto;">
                    <table style="width:100%;">
                        <thead>
                            <tr>
                                <th>Gate Pass ID</th><th>PO Number</th><th>Vendor</th><th>Email</th><th>Generated At</th><th>Download</th>
                            </tr>
                        </thead>
                        <tbody id="invoiceMasterBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
"""

new_scripts = """
        async function fetchVehicleLogs() {
            try {
                const res = await fetch('/api/vehicle_log');
                const logs = await res.json();
                const vBody = document.getElementById('vehicleLogBody');
                if(vBody) {
                    vBody.innerHTML = logs.map(l => `
                        <tr>
                            <td>${l.gp_id}</td>
                            <td>${l.plate}</td>
                            <td>${l.driver_name || '-'}</td>
                            <td><span class="badge ${l.status === 'Departed' ? 'pending' : 'sent'}">${l.status}</span></td>
                            <td>${l.entry_time}</td>
                            <td>${l.exit_time || '-'}</td>
                        </tr>
                    `).join('');
                }
            } catch(e) {}
        }

        async function fetchInvoices() {
            try {
                const res = await fetch('/api/invoices');
                const invs = await res.json();
                const iBody = document.getElementById('invoiceMasterBody');
                if(iBody) {
                    iBody.innerHTML = invs.map(i => `
                        <tr>
                            <td>${i.gp_id}</td>
                            <td>${i.po_number || '-'}</td>
                            <td>${i.vendor || '-'}</td>
                            <td>${i.vendor_email || '-'}</td>
                            <td>${i.generated_at}</td>
                            <td><a href="/static/invoices/${i.pdf_path}" target="_blank" class="btn-primary" style="text-decoration:none; display:inline-block;">View PDF</a></td>
                        </tr>
                    `).join('');
                }
            } catch(e) {}
        }
"""

if 'id="vehicle-log-view"' not in html:
    html = html.replace('<!-- GATE PASS MASTER VIEW -->', new_views + '\n        <!-- GATE PASS MASTER VIEW -->')

if 'async function fetchVehicleLogs()' not in html:
    html = html.replace('// --- NEW FEATURES: DRIVER PHOTO, VEHICLE LOG, INVOICES ---', '// --- NEW FEATURES: DRIVER PHOTO, VEHICLE LOG, INVOICES ---\n' + new_scripts)
    # add to poll loop or init
    # finding pollData
    poll_loc = html.find('fetchGatePasses();')
    # wait we can just add it inside pollData
    html = html.replace('        async function pollData() {\n            fetchDeliveries();\n            fetchGatePasses();', '        async function pollData() {\n            fetchDeliveries();\n            fetchGatePasses();\n            fetchVehicleLogs();\n            fetchInvoices();')
    
    # Also add to initial load
    html = html.replace('fetchGatePasses();\n        pollData();', 'fetchGatePasses();\n        fetchVehicleLogs();\n        fetchInvoices();\n        pollData();')

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
