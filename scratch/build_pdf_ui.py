import os

with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

# 1. Update Outbound UI
old_outbound_btn = """            let actionBtn = `<button class="btn-primary" onclick="pickOutboundOrder('${o.id}')">Pick Items</button>`;
            if (o.status === 'Fulfilled') actionBtn = '<span style="color:var(--primary-teal);">Completed</span>';"""

new_outbound_btn = """            let actionBtn = `<button class="btn-primary" onclick="pickOutboundOrder('${o.id}')">Pick Items</button>`;
            if (o.status === 'Fulfilled') actionBtn = '<span style="color:var(--primary-teal); font-weight:bold;">Completed</span>';
            actionBtn += `<button class="btn-primary" style="margin-top:4px; font-size:0.75rem; width:100%; background:var(--accent);" onclick="downloadOutboundManifest('${o.id}')">📄 PDF Manifest</button>`;"""

app_js = app_js.replace(old_outbound_btn, new_outbound_btn)


# 2. Update Gate Pass UI
old_gp_btns = """                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="width:100%; background:var(--accent-hover);" onclick="sendInvoice('${gp.id}')">📧 Send Invoice to Vendor</button>` : ''}
                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="margin-top:4px; width:100%; background:var(--success);" onclick="checkout('${gp.id}', '${gp.plate}')">Check Out</button>` : ''}"""

new_gp_btns = """                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="width:100%; background:var(--accent-hover);" onclick="sendInvoice('${gp.id}')">📧 Send Invoice to Vendor</button>` : ''}
                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="margin-top:4px; width:100%; background:var(--accent);" onclick="downloadGateManifest('${gp.id}')">📄 PDF Manifest</button>` : ''}
                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="margin-top:4px; width:100%; background:var(--success);" onclick="checkout('${gp.id}', '${gp.plate}')">Check Out</button>` : ''}"""

app_js = app_js.replace(old_gp_btns, new_gp_btns)


# 3. Add JS functions
manifest_funcs = """
// ==========================================
// AUTOMATED PDF MANIFESTS
// ==========================================
window.downloadOutboundManifest = async function(orderId) {
    try {
        const res = await fetch(`/api/outbound/${orderId}/manifest`);
        const data = await res.json();
        if(data.success) {
            window.open(data.url, '_blank');
        } else {
            alert("Failed to generate manifest");
        }
    } catch(e) { console.error(e); }
}

window.downloadGateManifest = async function(gpId) {
    try {
        const res = await fetch(`/api/gate/${gpId}/manifest`);
        const data = await res.json();
        if(data.success) {
            window.open(data.url, '_blank');
        } else {
            alert("Failed to generate manifest");
        }
    } catch(e) { console.error(e); }
}
"""

if 'downloadOutboundManifest' not in app_js:
    app_js += "\n" + manifest_funcs
    
with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(app_js)

print("PDF manifest UI injected.")
