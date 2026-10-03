import os

with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

# Add UI for Bin Suggestion above "Finish Unloading"
old_finish_btn = """                                    <button class="btn-danger" style="width:100%; margin-bottom:4px;" onclick="completeUnload('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Finish Unloading</button>"""

new_finish_btn = """                                    
                                    ${gp.status !== 'Completed' ? `
                                        <div style="background: var(--panel-bg); border: 1px solid var(--border-light); padding: 8px; border-radius: 4px; margin-bottom: 8px;">
                                            <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Putaway Bin Allocation</label>
                                            <div style="display:flex; gap: 4px; margin-top:4px;">
                                                <input type="text" id="bin_${gp.id}" value="${gp.bin_allocation || ''}" placeholder="Assign Bin ID" style="flex:1; padding: 4px; margin: 0; background: var(--panel-subtle); color: var(--text-main); border: 1px solid var(--border-light); border-radius: 4px;">
                                                <button class="btn-primary" style="padding: 4px 8px; font-size: 0.75rem; background: var(--accent);" onclick="suggestBin('${gp.id}')">🤖 Auto-Suggest</button>
                                            </div>
                                        </div>
                                    ` : `<div style="font-size:0.85rem; margin-bottom:8px;"><strong>Allocated Bin:</strong> ${gp.bin_allocation}</div>`}
                                    
                                    <button class="btn-danger" style="width:100%; margin-bottom:4px;" onclick="completeUnload('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Finish Unloading</button>"""

if 'Auto-Suggest' not in app_js:
    app_js = app_js.replace(old_finish_btn, new_finish_btn)
    
    suggest_bin_func = """
        async function suggestBin(gp_id) {
            try {
                const res = await fetch(`/api/dock/suggest_bin/${gp_id}`);
                const data = await res.json();
                if(data.success) {
                    document.getElementById(`bin_${gp_id}`).value = data.suggested_bin;
                } else {
                    alert(data.message);
                }
            } catch(e) { console.error(e); }
        }
    """
    app_js = app_js.replace("async function completeUnload", suggest_bin_func + "\n        async function completeUnload")
    
with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(app_js)

print("UI for bin suggestion injected.")
