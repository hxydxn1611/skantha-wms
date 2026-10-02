import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update Master Hub Tabs
old_tabs = """                      <button class="btn-primary sub-tab-btn active" onclick="switchSubTab('bin-master-sub', this)">Bin Master</button>"""
new_tabs = """                      <button class="btn-primary sub-tab-btn active" onclick="switchSubTab('bin-master-sub', this)">Bin Master</button>
                      <button class="btn-primary sub-tab-btn" onclick="switchSubTab('sku-master-sub', this)">SKU Master</button>"""

if "<button class=\"btn-primary sub-tab-btn\" onclick=\"switchSubTab('sku-master-sub', this)\">SKU Master</button>" not in html:
    html = html.replace(old_tabs, new_tabs)

# 2. Update Bin Master UI
old_bin_master = """                  <div id="bin-master-sub" class="sub-master-section" style="display:none;">
                      <h3>Bin Master</h3>
                      <div style="overflow-x:auto;">
                          <table style="width:100%;">
                              <thead>
                                  <tr>
                                      <th>Bin ID</th>
                                      <th>Vendor</th>
                                      <th>Stock Count</th>
                                      <th>Status</th>
                                      <th>Last Updated</th>
                                  </tr>
                              </thead>
                              <tbody id="binMasterBody"></tbody>
                          </table>
                      </div>
                  </div>"""

new_bin_master = """                  <div id="bin-master-sub" class="sub-master-section" style="display:none;">
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
                          <h3>Bin Master (Capacity & Slotting)</h3>
                          <button class="btn-primary" onclick="document.getElementById('addBinModal').style.display='flex'">+ Add Bin</button>
                      </div>
                      <div style="overflow-x:auto;">
                          <table style="width:100%;">
                              <thead>
                                  <tr>
                                      <th>Bin ID</th>
                                      <th>Zone</th>
                                      <th>Capacity (Vol)</th>
                                      <th>Capacity (Wt)</th>
                                      <th>Stock Count</th>
                                      <th>Vendors</th>
                                      <th>Status</th>
                                  </tr>
                              </thead>
                              <tbody id="binMasterBody"></tbody>
                          </table>
                      </div>
                  </div>
                  
                  <div id="sku-master-sub" class="sub-master-section" style="display:none;">
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
                          <h3>SKU Master (Product Catalog)</h3>
                          <button class="btn-primary" onclick="document.getElementById('addSkuModal').style.display='flex'">+ Add SKU</button>
                      </div>
                      <div style="overflow-x:auto;">
                          <table style="width:100%;">
                              <thead>
                                  <tr>
                                      <th>SKU ID</th>
                                      <th>Name</th>
                                      <th>Category</th>
                                      <th>Unit Vol</th>
                                      <th>Unit Wt</th>
                                  </tr>
                              </thead>
                              <tbody id="skuMasterBody"></tbody>
                          </table>
                      </div>
                  </div>"""

if "id=\"sku-master-sub\"" not in html:
    html = html.replace(old_bin_master, new_bin_master)

# 3. Add Modals
modals = """
<!-- Add Bin Modal -->
<div id="addBinModal" class="modal" style="display:none;">
    <div class="modal-content">
        <h2>Add Physical Bin</h2>
        <form id="addBinForm" onsubmit="event.preventDefault(); submitAddBin();">
            <label>Bin ID (e.g. A1-01)</label>
            <input type="text" id="newBinId" required>
            <label>Warehouse Zone</label>
            <select id="newBinZone">
                <option value="General">General Storage</option>
                <option value="Cold">Cold Storage</option>
                <option value="Hazardous">Hazardous Materials</option>
                <option value="High-Value">High-Value Secured</option>
            </select>
            <label>Max Volume Capacity (Cubic Meters)</label>
            <input type="number" step="0.1" id="newBinVol" value="100.0" required>
            <label>Max Weight Capacity (KG)</label>
            <input type="number" step="0.1" id="newBinWt" value="1000.0" required>
            <div style="display:flex; gap:10px; margin-top:20px;">
                <button type="submit" class="btn-primary">Create Bin</button>
                <button type="button" class="btn-secondary" onclick="document.getElementById('addBinModal').style.display='none'">Cancel</button>
            </div>
        </form>
    </div>
</div>

<!-- Add SKU Modal -->
<div id="addSkuModal" class="modal" style="display:none;">
    <div class="modal-content">
        <h2>Add SKU to Catalog</h2>
        <form id="addSkuForm" onsubmit="event.preventDefault(); submitAddSku();">
            <label>SKU ID (Barcode/QR)</label>
            <input type="text" id="newSkuId" required>
            <label>Product Name</label>
            <input type="text" id="newSkuName" required>
            <label>Category</label>
            <select id="newSkuCategory">
                <option value="Electronics">Electronics</option>
                <option value="Apparel">Apparel</option>
                <option value="Food">Food & Beverage</option>
                <option value="Machinery">Machinery / Parts</option>
            </select>
            <label>Unit Volume (Cubic Meters)</label>
            <input type="number" step="0.01" id="newSkuVol" value="0.1" required>
            <label>Unit Weight (KG)</label>
            <input type="number" step="0.1" id="newSkuWt" value="2.5" required>
            <div style="display:flex; gap:10px; margin-top:20px;">
                <button type="submit" class="btn-primary">Create SKU</button>
                <button type="button" class="btn-secondary" onclick="document.getElementById('addSkuModal').style.display='none'">Cancel</button>
            </div>
        </form>
    </div>
</div>
"""
if "addBinModal" not in html:
    html = html.replace("<!-- Gate Pass Modal -->", modals + "\n<!-- Gate Pass Modal -->")

# 4. Add JavaScript
js_code = """
async function fetchBins() {
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
                <td><strong>${b.bin_id}</strong></td>
                <td><span class="badge" style="background:var(--panel-subtle); color:var(--text-light);">${b.zone}</span></td>
                <td>
                    <div style="font-size:0.8rem; margin-bottom:4px;">${b.current_volume.toFixed(1)} / ${b.max_volume} m³</div>
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
                <td><span class="badge ${b.status==='Active'?'badge-success':'badge-warning'}">${b.status}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch(e) { console.error(e); }
}

async function fetchSkus() {
    try {
        const res = await fetch('/api/skus');
        const skus = await res.json();
        const tbody = document.getElementById('skuMasterBody');
        if(!tbody) return;
        tbody.innerHTML = '';
        skus.forEach(s => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${s.sku_id}</strong></td>
                <td>${s.name}</td>
                <td><span class="badge" style="background:var(--panel-subtle); color:var(--text-light);">${s.category}</span></td>
                <td>${s.unit_volume} m³</td>
                <td>${s.unit_weight} kg</td>
            `;
            tbody.appendChild(tr);
        });
    } catch(e) { console.error(e); }
}

async function submitAddBin() {
    const data = {
        bin_id: document.getElementById('newBinId').value,
        zone: document.getElementById('newBinZone').value,
        max_volume: parseFloat(document.getElementById('newBinVol').value),
        max_weight: parseFloat(document.getElementById('newBinWt').value)
    };
    try {
        await fetch('/api/bins', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
        document.getElementById('addBinModal').style.display='none';
        document.getElementById('addBinForm').reset();
        fetchBins();
    } catch(e) { console.error(e); }
}

async function submitAddSku() {
    const data = {
        sku_id: document.getElementById('newSkuId').value,
        name: document.getElementById('newSkuName').value,
        category: document.getElementById('newSkuCategory').value,
        unit_volume: parseFloat(document.getElementById('newSkuVol').value),
        unit_weight: parseFloat(document.getElementById('newSkuWt').value)
    };
    try {
        await fetch('/api/skus', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
        document.getElementById('addSkuModal').style.display='none';
        document.getElementById('addSkuForm').reset();
        fetchSkus();
    } catch(e) { console.error(e); }
}
"""

if "submitAddBin()" not in html:
    html = html.replace("async function fetchBins() {", js_code + "\n// old fetchBins replaced\n/*")
    html = html.replace("const tbody = document.getElementById('binMasterBody');", "*/\nconst tbody = document.getElementById('binMasterBody');")

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Updated index.html")
