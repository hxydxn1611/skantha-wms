import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

inspect_modal_html = """
    <!-- Inspect Bin Modal -->
    <div id="inspectBinModal" class="modal-overlay" onclick="if(event.target===this) this.style.display='none'">
        <div class="modal-dialog" style="max-width: 800px;">
            <div class="modal-header">
                <h3 style="margin:0;">Inspect Bin: <span id="inspectBinIdTitle" style="color:var(--primary-navy);"></span></h3>
                <button type="button" class="modal-close-btn" onclick="document.getElementById('inspectBinModal').style.display='none'" title="Close">&times;</button>
            </div>
            <div class="modal-body">
                <div style="background:var(--panel-subtle); border:1px solid var(--border-light); border-radius:8px; padding:0.85rem 1rem; margin-bottom:1rem;">
                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:10px; font-size:0.85rem;">
                        <div>
                            <span style="color:var(--text-muted); font-size:0.75rem; display:block;">Zone</span>
                            <strong id="inspectBinZone" style="color:var(--text-main);">-</strong>
                        </div>
                        <div>
                            <span style="color:var(--text-muted); font-size:0.75rem; display:block;">Volume Usage</span>
                            <span id="inspectBinVol" style="color:var(--text-main); font-weight:600;">-</span>
                        </div>
                        <div>
                            <span style="color:var(--text-muted); font-size:0.75rem; display:block;">Weight Usage</span>
                            <span id="inspectBinWt" style="color:var(--text-main); font-weight:600;">-</span>
                        </div>
                        <div>
                            <span style="color:var(--text-muted); font-size:0.75rem; display:block;">Total Items</span>
                            <span id="inspectBinCount" style="color:var(--text-main); font-weight:600;">-</span>
                        </div>
                    </div>
                </div>
                
                <h4 style="margin:0 0 0.85rem 0; font-size:0.95rem; color:var(--primary-navy); border-bottom:1px solid var(--border-light); padding-bottom:6px;">
                    Current Contents
                </h4>
                <div class="table-responsive" style="max-height: 350px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>SKU ID</th>
                                <th>Name / Category</th>
                                <th>Vendor</th>
                                <th>Qty</th>
                                <th>Received Date</th>
                            </tr>
                        </thead>
                        <tbody id="inspectBinTableBody">
                            <tr><td colspan="5" style="text-align:center;">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn-primary" onclick="document.getElementById('inspectBinModal').style.display='none'">Close</button>
            </div>
        </div>
    </div>
"""

if "id=\"inspectBinModal\"" not in html:
    html = html.replace("<!-- Add SKU Modal -->", inspect_modal_html + "\n    <!-- Add SKU Modal -->")

inspect_js = """
window.openInspectBinModal = async function(binId) {
    document.getElementById('inspectBinIdTitle').innerText = binId;
    document.getElementById('inspectBinModal').style.display = 'flex';
    
    // Fetch Bin details from global list or re-fetch
    try {
        const binRes = await fetch('/api/bins');
        if (binRes.ok) {
            const bins = await binRes.json();
            const bin = bins.find(b => b.bin_id === binId);
            if (bin) {
                document.getElementById('inspectBinZone').innerText = bin.zone;
                document.getElementById('inspectBinVol').innerText = `${bin.current_volume.toFixed(1)} / ${bin.max_volume} mA3`;
                document.getElementById('inspectBinWt').innerText = `${bin.current_weight.toFixed(1)} / ${bin.max_weight} kg`;
                document.getElementById('inspectBinCount').innerText = bin.stock_count;
            }
        }
        
        // Fetch specific inventory for this bin
        const invRes = await fetch(`/api/bins/${binId}/inventory`);
        const tbody = document.getElementById('inspectBinTableBody');
        tbody.innerHTML = '';
        
        if (invRes.ok) {
            const inventory = await invRes.json();
            if (inventory.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Bin is currently empty.</td></tr>';
            } else {
                inventory.forEach(i => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><strong>${i.sku_id}</strong></td>
                        <td>
                            <div>${i.sku_name || 'Unknown'}</div>
                            <div style="font-size:0.75rem; color:var(--text-muted);">${i.category || '-'}</div>
                        </td>
                        <td>${i.vendor || '-'}</td>
                        <td><strong>${i.quantity}</strong></td>
                        <td style="font-size:0.85rem; color:var(--text-muted);">${new Date(i.received_date).toLocaleString()}</td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        } else {
             tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:red;">Failed to load contents.</td></tr>';
        }
    } catch (e) {
        console.error(e);
        document.getElementById('inspectBinTableBody').innerHTML = '<tr><td colspan="5" style="text-align:center; color:red;">Error loading contents.</td></tr>';
    }
}
"""

if "window.openInspectBinModal" not in html:
    html = html.replace("window.submitAddBin = async function() {", inspect_js + "\nwindow.submitAddBin = async function() {")

# Update fetchBins to include the inspect button
new_fetch_bins = """window.fetchBins = async function() {
    try {
        const res = await fetch('/api/bins');
        const bins = await res.json();
        const tbody = document.getElementById('binMasterBody');
        if(!tbody) return;
        tbody.innerHTML = '';
        bins.forEach(b => {
            const tr = document.createElement('tr');
            const pctVol = b.max_volume > 0 ? ((b.current_volume/b.max_volume)*100).toFixed(1) : 0;
            const pctWt = b.max_weight > 0 ? ((b.current_weight/b.max_weight)*100).toFixed(1) : 0;
            tr.innerHTML = `
                <td>
                    <strong>${b.bin_id}</strong>
                    <div style="margin-top:4px;"><button type="button" style="font-size:0.7rem; padding:2px 6px; cursor:pointer;" onclick="window.openInspectBinModal('${b.bin_id}')">Inspect</button></div>
                </td>
                <td><span class="badge" style="background:var(--panel-subtle); color:var(--text-light); padding: 4px 8px; border-radius: 4px;">${b.zone}</span></td>
                <td>
                    <div style="font-size:0.8rem; margin-bottom:4px;">${b.current_volume.toFixed(1)} / ${b.max_volume} mA3</div>
                    <div style="width:100%; background:#334155; height:6px; border-radius:3px;">
                        <div style="width:${Math.min(pctVol, 100)}%; background:${pctVol>90 ? 'var(--danger)' : 'var(--primary-teal)'}; height:100%; border-radius:3px;"></div>
                    </div>
                </td>
                <td>
                    <div style="font-size:0.8rem; margin-bottom:4px;">${b.current_weight.toFixed(1)} / ${b.max_weight} kg</div>
                    <div style="width:100%; background:#334155; height:6px; border-radius:3px;">
                        <div style="width:${Math.min(pctWt, 100)}%; background:${pctWt>90 ? 'var(--danger)' : 'var(--accent)'}; height:100%; border-radius:3px;"></div>
                    </div>
                </td>
                <td><strong style="color:var(--primary-navy); font-size:1.1rem;">${b.stock_count}</strong> Items</td>
                <td>${b.vendor || 'Empty'}</td>
                <td><span class="badge ${b.status==='Active'?'badge-success':'badge-warning'}" style="padding: 4px 8px; border-radius: 4px;">${b.status}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch(e) { console.error(e); }
}"""

old_fetch_bins = re.search(r'window\.fetchBins = async function\(\) \{.*?\n\}', html, re.DOTALL)
if old_fetch_bins:
    html = html.replace(old_fetch_bins.group(0), new_fetch_bins)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Updated index.html with inspect bin")
