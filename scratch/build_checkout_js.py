import os

# 1. Update app_logic.js
with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    js = f.read()

old_filter = "const activePasses = passes.filter(p => !['Completed', 'Departed'].includes(p.status));"
new_filter = "const activePasses = passes.filter(p => !['Exited', 'Departed'].includes(p.status));"

js = js.replace(old_filter, new_filter)

old_buttons = """                                </div>
                            </div>
                            
                            ${gp.status === 'Pending' ? `"""

new_buttons = """                                </div>
                            </div>
                            
                            ${gp.status === 'Completed' ? `
                                <div style="display:flex; flex-direction:column; gap:10px;">
                                    <div style="background:#e0f2fe; border:1px solid #bae6fd; padding:10px; border-radius:6px; font-size:0.85rem; color:#0369a1;">
                                        <strong>Ready for Departure:</strong> Verify driver & vehicle before checkout.
                                    </div>
                                    <button class="btn-primary" onclick="checkoutGatePass('${gp.id}', '${gp.plate}')" style="width:100%;">Verify & Check-Out Vehicle</button>
                                </div>
                            ` : ''}

                            ${gp.status === 'Pending' ? `"""

js = js.replace(old_buttons, new_buttons)

new_checkout_func = """
        async function checkoutGatePass(gp_id, plate) {
            if(!confirm(`Verify that vehicle ${plate} is at the gate. Complete Check-Out?`)) return;
            try {
                const res = await fetch(`/api/gate/checkout/${gp_id}`, { method: 'POST' });
                const data = await res.json();
                if(data.success) {
                    fetchGatePasses();
                } else {
                    alert("Checkout Failed: " + data.message);
                }
            } catch(e) {
                console.error(e);
            }
        }
"""
if 'async function checkoutGatePass' not in js:
    js = js.replace("async function checkout(id, expectedPlate) {", new_checkout_func + "\n        async function checkout(id, expectedPlate) {")

with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(js)

print("Checkout logic added.")
