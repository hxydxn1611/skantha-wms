import os

with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

outbound_js = """
// ==========================================
// OUTBOUND LOGIC
// ==========================================

window.fetchOutboundOrders = async function() {
    try {
        const res = await fetch('/api/outbound');
        const orders = await res.json();
        const tbody = document.getElementById('outboundTableBody');
        if(!tbody) return;
        tbody.innerHTML = '';
        
        orders.forEach(o => {
            const tr = document.createElement('tr');
            let itemsStr = o.items.map(i => `${i.quantity}x ${i.sku_id} (Picked: ${i.picked_quantity})`).join('<br>');
            
            let actionBtn = `<button class="btn-primary" onclick="pickOutboundOrder('${o.id}')">Pick Items</button>`;
            if (o.status === 'Fulfilled') actionBtn = '<span style="color:var(--primary-teal);">Completed</span>';
            
            tr.innerHTML = `
                <td><strong>${o.id}</strong></td>
                <td>${o.customer_name}</td>
                <td>${o.destination}</td>
                <td style="font-size:0.8rem;">${itemsStr}</td>
                <td><span class="badge ${o.status==='Fulfilled'?'badge-success':(o.status==='Pending'?'badge-warning':'')}">${o.status}</span></td>
                <td>${actionBtn}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch(e) { console.error(e); }
}

window.submitAddOutbound = async function() {
    const data = {
        customer_name: document.getElementById('outboundCustomer').value,
        destination: document.getElementById('outboundDest').value,
        items: [
            { sku_id: document.getElementById('outboundSku').value, quantity: parseInt(document.getElementById('outboundQty').value) }
        ]
    };
    try {
        await fetch('/api/outbound', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        document.getElementById('formAddOutbound').reset();
        window.fetchOutboundOrders();
    } catch(e) { console.error(e); }
}

window.pickOutboundOrder = async function(orderId) {
    try {
        const res = await fetch(`/api/outbound/${orderId}/pick`, {method: 'POST'});
        const data = await res.json();
        if(data.success) {
            alert('Order pick processed! Status: ' + data.status);
            window.fetchOutboundOrders();
        } else {
            alert('Failed to pick order: ' + data.error);
        }
    } catch(e) { console.error(e); }
}

// Hook into tab switching
const origSwitchTabOutbound = window.switchTab;
if (origSwitchTabOutbound) {
    window.switchTab = function(tabId) {
        origSwitchTabOutbound(tabId);
        if(tabId === 'outbound') {
            window.fetchOutboundOrders();
            // Populate SKUs
            fetch('/api/skus').then(r=>r.json()).then(skus => {
                const sel = document.getElementById('outboundSku');
                if(sel) {
                    sel.innerHTML = '<option value="">Select SKU...</option>' + skus.map(s => `<option value="${s.sku_id}">${s.name}</option>`).join('');
                }
            });
        }
    };
}
"""

if 'fetchOutboundOrders' not in app_js:
    app_js += "\n" + outbound_js
    with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
        f.write(app_js)

print("JS Outbound Logic injected successfully.")
