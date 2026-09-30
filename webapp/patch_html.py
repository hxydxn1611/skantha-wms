import re

with open('templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Replace the table layout for Gate Passes with a Grid container
old_table = """<table>
                    <thead>
                        <tr>
                            <th>Pass ID</th><th>Arrival</th><th>Date Status</th><th>Plate (Editable)</th>
                            <th>Driver</th><th>Load (Match to PO)</th><th>Dock</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="gatePassTableBody"></tbody>
                </table>"""

new_grid = """<div id="gatePassGrid" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 1.5rem; margin-top: 1rem;"></div>"""
html = html.replace(old_table, new_grid)

# Also update the js references to gatePassTableBody -> gatePassGrid
html = html.replace("document.getElementById('gatePassTableBody')", "document.getElementById('gatePassGrid')")
html = html.replace("gateBody.innerHTML = '<tr><td colspan=\"8\" style=\"text-align:center;\">No gate passes yet.</td></tr>';", "gateBody.innerHTML = '<div style=\"grid-column: 1 / -1; text-align:center; padding: 2rem;\">No gate passes yet.</div>';")

# Now let's replace the gatePass innerHTML logic
old_js_start = """                    return `
                    <tr>
                        <td style="font-weight:bold; color:var(--accent-hover);">
                            ${gp.id}<br/>
                            <span class="badge ${gp.status === 'Pending' ? 'pending' : 'sent'}" style="margin-top:4px; display:inline-block">${gp.status}</span>
                        </td>"""

old_js_end = """                        </td>
                    </tr>
                `}).join('');"""

new_js = """                    return `
                    <div style="background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border-light); border-radius: 12px; padding: 1.5rem; display: flex; flex-direction: column; gap: 1rem; position: relative;">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <div>
                                <h3 style="margin: 0; color: var(--accent-hover); font-size: 1.2rem;">Pass ${gp.id}</h3>
                                <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;">Arrival: ${gp.arrival_date} ${gp.time}</div>
                            </div>
                            <span class="badge ${gp.status === 'Pending' ? 'pending' : 'sent'}">${gp.status}</span>
                        </div>
                        
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 8px;">
                            <div>
                                <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Vehicle Plate</label>
                                <input type="text" id="plate_${gp.id}" value="${gp.plate || ''}" placeholder="Enter Plate" style="margin: 4px 0 0 0; font-family: monospace;" ${gp.status !== 'Pending' ? 'disabled' : ''}>
                                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">AI: ${gp.vehicle_type}</div>
                            </div>
                            <div>
                                <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Date Status</label>
                                <div style="margin-top: 4px;">${dateStatusHtml}</div>
                                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">Exp: ${gp.expected_date || 'N/A'}</div>
                            </div>
                        </div>

                        <div>
                            <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Driver & Vendor Details</label>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-top: 4px;">
                                <input type="text" id="driver_${gp.id}" value="${gp.driver_name || ''}" placeholder="Driver Name" style="margin: 0;" ${gp.status !== 'Pending' ? 'disabled' : ''}>
                                <input type="text" id="driver_phone_${gp.id}" value="${gp.driver_phone || ''}" placeholder="Driver Phone" style="margin: 0;" ${gp.status !== 'Pending' ? 'disabled' : ''}>
                                <input type="text" id="vendor_${gp.id}" value="${gp.vendor || ''}" placeholder="Vendor Name" style="margin: 0;" ${gp.status !== 'Pending' ? 'disabled' : ''}>
                                <input type="email" id="vendor_email_${gp.id}" value="${gp.vendor_email || ''}" placeholder="Vendor Email" style="margin: 0;" ${gp.status !== 'Pending' ? 'disabled' : ''}>
                            </div>
                        </div>

                        <div>
                            <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Load Information</label>
                            ${expectedDateInput}
                            ${poNumberInput}
                            <div style="margin-top: 4px;">${poDropdown}</div>
                            <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 0.5rem; margin-top: 0.5rem;">
                                <input type="text" id="load_${gp.id}" value="${gp.load || ''}" placeholder="Load Description" style="margin: 0;" ${gp.status !== 'Pending' ? 'disabled' : ''}>
                                <select id="activity_${gp.id}" style="margin: 0;" ${gp.status !== 'Pending' ? 'disabled' : ''}>
                                    <option value="Unloading" ${gp.activity === 'Unloading' ? 'selected' : ''}>Unloading</option>
                                    <option value="Loading" ${gp.activity === 'Loading' ? 'selected' : ''}>Loading</option>
                                </select>
                            </div>
                        </div>

                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                            <div>
                                <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Truck Photo</label>
                                ${gp.photo 
                                    ? `<div style="margin-top: 4px;"><img src="/static/${gp.photo}" style="width: 100%; max-height: 100px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border-light);"/><div style="cursor:pointer; font-size:0.75rem; color:var(--text-muted); text-align:center; margin-top:4px;" onclick="retakePhoto('${gp.id}')">🔄 Retake Photo</div></div>` 
                                    : `<button class="btn-primary" style="margin-top: 4px; width: 100%; padding: 6px; font-size: 0.8rem;" onclick="retakePhoto('${gp.id}')">📸 Snap Photo</button>`
                                }
                            </div>
                            <div>
                                <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Driver Face</label>
                                ${gp.driver_photo 
                                    ? `<div style="margin-top: 4px;"><img src="/static/${gp.driver_photo}" style="width: 100%; max-height: 100px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border-light);"/><div style="cursor:pointer; font-size:0.75rem; color:var(--text-muted); text-align:center; margin-top:4px;" onclick="captureDriverPhoto('${gp.id}')">🔄 Retake Face</div></div>` 
                                    : `<button class="btn-primary" style="margin-top: 4px; width: 100%; padding: 6px; font-size: 0.8rem;" onclick="captureDriverPhoto('${gp.id}')">📸 Scan Face</button>`
                                }
                            </div>
                        </div>

                        ${gp.status === 'Pending' ? `
                        <div style="margin-top: auto; padding-top: 1rem; border-top: 1px solid var(--border-light);">
                            <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Assign Dock</label>
                            <div style="display: flex; gap: 0.5rem; margin-top: 4px;">
                                <select id="dock_${gp.id}" style="margin: 0; flex: 1;">
                                    <option value="Not Assigned" ${gp.dock === 'Not Assigned' ? 'selected' : ''}>Select Dock...</option>
                                    <option value="Dock 1" ${gp.dock === 'Dock 1' ? 'selected' : ''}>Dock 1</option>
                                    <option value="Dock 2" ${gp.dock === 'Dock 2' ? 'selected' : ''}>Dock 2</option>
                                </select>
                            </div>
                        </div>` : ''}

                        <div style="display: flex; gap: 0.5rem; margin-top: 1rem;">
                            ${gp.status === 'Pending' ? `
                                ${(gp.otp_verified === 0 && gp.driver_phone) ? `<button class="btn-primary" style="flex: 1; background: var(--warning);" onclick="verifyOtp('${gp.id}')">Verify OTP</button>` : ''}
                                <button class="btn-primary" style="flex: 1;" onclick="updatePass('${gp.id}')">Approve & Assign</button>
                                <button class="btn-danger" style="flex: 1;" onclick="deletePass('${gp.id}')">Reject</button>
                            ` : gp.status === 'Completed' ? `
                                <button class="btn-primary" style="flex: 1; background: var(--success);" onclick="checkout('${gp.id}', '${gp.plate}')">Check Out Vehicle</button>
                            ` : gp.status === 'Departed' ? `
                                <div style="flex: 1; text-align: center; color: var(--success); font-weight: bold; padding: 0.5rem;">Checked Out</div>
                            ` : ''}
                            ${(gp.status !== 'Pending' && gp.status !== 'Completed') ? `<button class="btn-danger" style="flex: 1;" onclick="deletePass('${gp.id}')">Delete Pass</button>` : ''}
                        </div>
                    </div>
                `}).join('');"""

# We need to extract the block between old_js_start and old_js_end and replace it with new_js.
import re
pattern = re.compile(re.escape(old_js_start) + r'.*?' + re.escape(old_js_end), re.DOTALL)
html = pattern.sub(new_js.replace('\\', '\\\\'), html) # Handle escape chars

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
