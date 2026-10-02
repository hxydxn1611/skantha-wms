import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Check if addSkuModal exists, if not, we must add it.
sku_modal_html = """
    <!-- Add SKU Modal -->
    <div id="addSkuModal" class="modal-overlay" onclick="if(event.target===this) this.style.display='none'">
        <div class="modal-dialog">
            <div class="modal-header">
                <h3>Add New SKU</h3>
                <button type="button" class="modal-close-btn" onclick="document.getElementById('addSkuModal').style.display='none'">&times;</button>
            </div>
            <div class="modal-body">
                <form id="addSkuForm">
                    <label>SKU ID (Leave blank to auto-generate)</label>
                    <input type="text" id="newSkuId" placeholder="e.g. ELEC-S23-01">
                    <label>Product Name</label>
                    <input type="text" id="newSkuName" placeholder="e.g. Galaxy S23" required>
                    <label>Category</label>
                    <input type="text" id="newSkuCategory" placeholder="e.g. Electronics" required>
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                        <div>
                            <label>Unit Volume (mA3)</label>
                            <input type="number" id="newSkuVol" step="0.1" placeholder="0.5" required>
                        </div>
                        <div>
                            <label>Unit Weight (kg)</label>
                            <input type="number" id="newSkuWt" step="0.1" placeholder="1.2" required>
                        </div>
                    </div>
                </form>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn-secondary" onclick="document.getElementById('addSkuModal').style.display='none'">Cancel</button>
                <button type="button" class="btn-primary" onclick="window.submitAddSku()">Save SKU</button>
            </div>
        </div>
    </div>
"""

if "id=\"addSkuModal\"" not in html:
    html = html.replace("</body>", sku_modal_html + "\n</body>")

submit_sku_js = """
window.submitAddSku = async function() {
    let skuId = document.getElementById('newSkuId').value.trim();
    const name = document.getElementById('newSkuName').value.trim();
    const cat = document.getElementById('newSkuCategory').value.trim();
    
    // Auto-generate if blank
    if (!skuId) {
        const catPrefix = cat ? cat.substring(0,3).toUpperCase() : 'SKU';
        const randomNum = Math.floor(1000 + Math.random() * 9000);
        skuId = `${catPrefix}-${randomNum}`;
    }

    const data = {
        sku_id: skuId,
        name: name,
        category: cat,
        unit_volume: parseFloat(document.getElementById('newSkuVol').value),
        unit_weight: parseFloat(document.getElementById('newSkuWt').value)
    };
    try {
        const res = await fetch('/api/skus', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        document.getElementById('addSkuModal').style.display='none';
        document.getElementById('addSkuForm').reset();
        
        // Refresh master tables
        if(window.fetchSkus) window.fetchSkus();
        
        // If we were adding it for the manifest, we need to refresh the dropdowns!
        // We will just alert that it was created and let them select it.
        try {
            const smRes = await fetch('/api/skus');
            const skus = await smRes.json();
            window.globalSkus = skus;
            // Update all manifest sku dropdowns
            const selects = document.querySelectorAll('select[id^="manifestSku_"]');
            selects.forEach(sel => {
                const currentVal = sel.value;
                let skuOptions = '<option value="">Select SKU...</option>';
                skus.forEach(s => {
                    skuOptions += `<option value="${s.sku_id}">${s.sku_id} - ${s.name}</option>`;
                });
                sel.innerHTML = skuOptions;
                sel.value = currentVal;
            });
            
            alert(`SKU created successfully: ${skuId}`);
        } catch(e) {}
        
    } catch(e) { console.error(e); }
}
"""

if "window.submitAddSku" not in html:
    html = html.replace("</script>\n</body>", submit_sku_js + "\n</script>\n</body>")
else:
    # We replace the old submitAddSku if it exists
    old_submit = re.search(r'window\.submitAddSku = async function\(\) \{.*?\n\}', html, re.DOTALL)
    if old_submit:
        html = html.replace(old_submit.group(0), submit_sku_js)

# Update manifest line generation to add a "+ New SKU" button
old_manifest_line = r"lineDiv\.innerHTML = `.*?<select id=\"manifestSku_\$\{id\}\".*?</select>"
new_manifest_line = """lineDiv.innerHTML = `
                <div style="display:flex; align-items:center; gap:4px;">
                    <select id="manifestSku_${id}" required style="margin:0; padding:6px; font-size:0.8rem; flex-grow:1;" title="SKU">${skuOptions}</select>
                    <button type="button" onclick="document.getElementById('addSkuModal').style.display='flex'" style="background:var(--primary-teal); color:white; border:none; padding:6px; border-radius:4px; cursor:pointer; font-size:0.75rem;" title="Quick Add SKU">+</button>
                </div>"""
html = re.sub(old_manifest_line, new_manifest_line, html, flags=re.DOTALL)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Patched Quick-Add SKU")
