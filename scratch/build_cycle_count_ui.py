import os
import re

# 1. Update app_logic.js with Manual Editing UI and API call
with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

old_ai_sync_btns = """                                    </div>
                                    <button class="btn-primary" style="width:100%; margin-bottom:4px;" onclick="scanPackages('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>🔄 Sync AI Tracker Count</button>
                                    <button class="btn-danger" style="width:100%; margin-bottom:4px;" onclick="completeUnload('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Finish Unloading</button>"""

new_ai_sync_btns = """                                    </div>
                                    <div style="display:flex; gap: 4px; margin-bottom:4px;">
                                        <button class="btn-primary" style="flex: 1;" onclick="scanPackages('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>🔄 Sync AI Tracker</button>
                                        <input type="number" id="manual_add_${gp.id}" placeholder="+Qty" style="width: 60px; padding: 4px; margin: 0; background: var(--panel-bg); color: var(--text-main); border: 1px solid var(--border-light); border-radius: 4px;" ${gp.status === 'Completed' ? 'disabled' : ''}>
                                        <button class="btn-primary" style="padding: 4px 8px; background: var(--accent);" onclick="manualAddPackages('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Add</button>
                                    </div>
                                    <button class="btn-danger" style="width:100%; margin-bottom:4px;" onclick="completeUnload('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Finish Unloading</button>"""

if 'manualAddPackages' not in app_js:
    app_js = app_js.replace(old_ai_sync_btns, new_ai_sync_btns)
    
    manual_add_func = """
        async function manualAddPackages(gp_id) {
            const qtyInput = document.getElementById(`manual_add_${gp_id}`);
            const count = parseInt(qtyInput.value) || 0;
            if (count === 0) return;
            
            try {
                const res = await fetch(`/api/dock/auto_add/${gp_id}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({count: count})
                });
                const data = await res.json();
                if(data.success) {
                    alert(`Added ${count} items. Total: ${data.total}`);
                    fetchGatePasses();
                } else {
                    alert('Error: ' + data.message);
                }
            } catch(e) {
                alert('Connection error');
            }
        }
"""
    # Insert it before completeUnload
    app_js = app_js.replace("async function completeUnload", manual_add_func + "\n        async function completeUnload")


# --- CYCLE COUNT LOGIC IN app_logic.js ---
cycle_count_js = """
// ==========================================
// CYCLE COUNTING & AUDIT
// ==========================================
async function runCycleCount(bin_id) {
    const input = document.getElementById(`audit_qty_${bin_id}`);
    const actual_qty = parseInt(input.value);
    if(isNaN(actual_qty)) {
        alert("Enter a valid quantity");
        return;
    }
    try {
        const res = await fetch('/api/cycle_count', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({bin_id: bin_id, actual_qty: actual_qty})
        });
        const data = await res.json();
        if(data.success) {
            alert(data.message);
            fetchMasterHubData();
        } else {
            alert("Error: " + data.message);
        }
    } catch (e) {
        alert("Connection Error");
    }
}

// Modify bin table rendering to include cycle count inputs in the cycle count tab
function renderCycleCountTab(bins, inventory) {
    const tbody = document.getElementById('cycleCountBody');
    if(!tbody) return;
    
    tbody.innerHTML = bins.map(b => {
        const inv = inventory.find(i => i.bin_id === b.bin_id);
        const expected_qty = inv ? inv.quantity : 0;
        const sku_id = inv ? inv.sku_id : 'N/A';
        return `
            <tr>
                <td>${b.bin_id}</td>
                <td>${b.zone}</td>
                <td>${sku_id}</td>
                <td>${expected_qty}</td>
                <td>
                    <div style="display:flex; gap:10px;">
                        <input type="number" id="audit_qty_${b.bin_id}" placeholder="Actual Qty" style="width:100px; padding:4px; margin:0;" value="${expected_qty}">
                        <button class="btn-primary" onclick="runCycleCount('${b.bin_id}')">Audit</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}
"""

if 'runCycleCount' not in app_js:
    app_js += "\n" + cycle_count_js
    
    # We need to hook renderCycleCountTab into fetchMasterHubData
    old_fetch_master = """                renderBinMaster(bins, inventory);
                renderSkuMaster(skus);"""
    new_fetch_master = """                renderBinMaster(bins, inventory);
                renderSkuMaster(skus);
                renderCycleCountTab(bins, inventory);"""
    app_js = app_js.replace(old_fetch_master, new_fetch_master)

with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(app_js)


# 2. Update index.html for Cycle Count UI
with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Add button
old_buttons = """<button class="btn-primary sub-tab-btn" onclick="switchSubTab('sku-master', this)">SKU Master</button>"""
new_buttons = """<button class="btn-primary sub-tab-btn" onclick="switchSubTab('sku-master', this)">SKU Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('cycle-count', this)">Cycle Count</button>"""
if "switchSubTab('cycle-count', this)" not in html:
    html = html.replace(old_buttons, new_buttons)

# Add sub-section
old_sku_section_end = """                        </tbody>
                    </table>
                </div>"""
                
cycle_count_section = """
                <!-- CYCLE COUNT -->
                <div id="cycle-count-sub" class="sub-master-section" style="display:none; margin-top:20px;">
                    <h3>Cycle Counting & Audits</h3>
                    <p style="color:var(--text-muted); margin-bottom:10px;">Perform routine physical counts and reconcile discrepancies.</p>
                    <table>
                        <thead>
                            <tr>
                                <th>Bin ID</th>
                                <th>Zone</th>
                                <th>SKU</th>
                                <th>Expected Qty (System)</th>
                                <th>Actual Qty (Audit)</th>
                            </tr>
                        </thead>
                        <tbody id="cycleCountBody">
                            <!-- Populated via JS -->
                        </tbody>
                    </table>
                </div>"""

# Safely inject after sku-master-sub
if "id=\"cycle-count-sub\"" not in html:
    # Find the end of sku-master-sub
    # Let's just append it before the closing div of master-hub-view
    
    parts = html.split('<!-- ANALYTICS VIEW -->')
    if len(parts) == 2:
        master_hub_html = parts[0]
        # remove the last </div> which closes master-hub-view
        master_hub_html = master_hub_html.rsplit('</div>', 1)
        master_hub_html_new = master_hub_html[0] + cycle_count_section + "\n            </div>\n        "
        html = master_hub_html_new + '<!-- ANALYTICS VIEW -->' + parts[1]

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("UI patches applied.")
