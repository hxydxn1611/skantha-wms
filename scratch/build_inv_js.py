import os

with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    js = f.read()

# 1. Add fetchInventory() inside fetchMasterHubData()
old_fetch = """        async function fetchMasterHubData() {
            try {
                // PO Master
                let res = await fetch('/api/purchases');"""
                
new_fetch = """        async function fetchMasterHubData() {
            try {
                // Inventory Master
                let invRes = await fetch('/api/inventory');
                let invs = await invRes.json();
                renderInventoryMaster(invs);

                // PO Master
                let res = await fetch('/api/purchases');"""

if 'let invRes = await fetch' not in js:
    js = js.replace(old_fetch, new_fetch)

# 2. Add renderInventoryMaster function
new_funcs = """
        function renderInventoryMaster(invs) {
            const body = document.getElementById('inventoryMasterBody');
            if(!body) return;
            
            body.innerHTML = invs.map(inv => `
                <tr>
                    <td>INV-${inv.id}</td>
                    <td style="font-weight:bold; color:var(--primary-teal);">${inv.bin_id}</td>
                    <td>${inv.zone || '-'}</td>
                    <td>${inv.sku_id}</td>
                    <td style="color:var(--text-main); font-weight:600;">${inv.sku_name || 'Unknown'}</td>
                    <td><span class="badge" style="background:#f3f4f6; color:#4b5563; border:1px solid #d1d5db;">${inv.category || 'General'}</span></td>
                    <td>${inv.vendor || '-'}</td>
                    <td>${inv.received_date || '-'}</td>
                    <td style="font-weight:bold; font-size:1.1rem; color:var(--primary-navy);">
                        <input type="number" id="inv_qty_${inv.id}" value="${inv.quantity}" style="width:70px; padding:4px; font-weight:bold; color:var(--primary-navy);">
                    </td>
                    <td>
                        <button class="btn-primary" onclick="updateInventory(${inv.id})" style="padding:4px 8px; font-size:0.75rem;">💾 Save</button>
                    </td>
                </tr>
            `).join('');
        }
        
        async function updateInventory(invId) {
            const newQty = document.getElementById(`inv_qty_${invId}`).value;
            if(!newQty || isNaN(newQty) || newQty < 0) {
                alert("Please enter a valid quantity.");
                return;
            }
            try {
                const res = await fetch(`/api/inventory/${invId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ quantity: parseInt(newQty) })
                });
                const data = await res.json();
                if(data.success) {
                    alert("Inventory updated & Bin capacity synchronized.");
                    fetchMasterHubData();
                } else {
                    alert("Update failed: " + data.message);
                }
            } catch(e) {
                console.error(e);
            }
        }
"""

if 'function renderInventoryMaster' not in js:
    js = js.replace("async function fetchMasterHubData() {", new_funcs + "\n        async function fetchMasterHubData() {")

with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(js)

print("Inventory JS logic added.")
