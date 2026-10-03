import os

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add button
old_buttons = """                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('sku-master', this)">SKU Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('cycle-count', this)">Cycle Count</button>"""
                        
new_buttons = """                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('sku-master', this)">SKU Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('cycle-count', this)">Cycle Count</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('inventory-master', this)">Inventory Master</button>"""

if 'switchSubTab(\'inventory-master\'' not in html:
    html = html.replace(old_buttons, new_buttons)

# 2. Add section
old_section = """<div id="sku-master-sub" class="sub-master-section" style="display:none;">"""

new_section = """
<div id="inventory-master-sub" class="sub-master-section" style="display:none;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
        <h3>Inventory Master (Stock Details)</h3>
        <span style="font-size:0.85rem; color:var(--text-muted);">Real-time View of Physical Stock</span>
    </div>
    <div style="overflow-x:auto;">
        <table style="width:100%;">
            <thead>
                <tr>
                    <th>Record ID</th>
                    <th>Bin ID</th>
                    <th>Zone</th>
                    <th>SKU ID</th>
                    <th>Material / Part</th>
                    <th>Category</th>
                    <th>Vendor</th>
                    <th>Received Date</th>
                    <th>Quantity (Live)</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="inventoryMasterBody"></tbody>
        </table>
    </div>
</div>

<div id="sku-master-sub" class="sub-master-section" style="display:none;">"""

if 'id="inventory-master-sub"' not in html:
    html = html.replace(old_section, new_section)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
    
print("UI tab for Inventory Master injected.")
