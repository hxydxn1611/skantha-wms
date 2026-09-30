import re

with open('templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Insert Gate Pass Master View container
new_master_view = """
        <!-- GATE PASS MASTER VIEW -->
        <div id="gate-pass-master-view" class="view-section">
            <div class="glass-panel">
                <h2>Gate Pass Master</h2>
                <p style="color:var(--text-muted);">Historical log of all generated gate passes.</p>
                <div style="overflow-x:auto;">
                    <table style="width:100%;">
                        <thead>
                            <tr>
                                <th>ID</th><th>Plate</th><th>Driver</th><th>Status</th><th>Dock</th><th>Arrival</th><th>Exit Time</th>
                            </tr>
                        </thead>
                        <tbody id="gatePassMasterBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
"""
# find where vehicle-log-view ends and insert new_master_view after it
# Actually, I can just append it before "</div> <!-- End of main-content -->"
html = html.replace('</div>\n    </div>\n\n    <!-- Login Overlay -->', new_master_view + '\n    </div>\n    </div>\n\n    <!-- Login Overlay -->')

# 2. Modify `fetchGatePasses` to filter active passes for the grid, and populate the Master table
# Let's locate `if(passes.length === 0) {`
# We will just rewrite the `fetchGatePasses` function body

fetch_start = "        async function fetchGatePasses() {"
fetch_end = "        async function updatePass(id) {"

new_fetch = """        async function fetchGatePasses() {
            try {
                const res = await fetch('/api/gate_passes');
                const passes = await res.json();
                const gateBody = document.getElementById('gatePassGrid');
                const dockBody = document.getElementById('dockTableBody');
                const masterBody = document.getElementById('gatePassMasterBody');
                
                // Badges
                const pendingCount = passes.filter(p => p.status === 'Pending').length;
                const activeDockCount = passes.filter(p => p.status === 'Sent to Dock').length;
                document.getElementById('gate-badge').style.display = pendingCount > 0 ? 'inline-block' : 'none';
                document.getElementById('dock-badge').style.display = activeDockCount > 0 ? 'inline-block' : 'none';
                
                // Render Master Table
                if(masterBody) {
                    masterBody.innerHTML = passes.map(gp => `
                        <tr>
                            <td>${gp.id}</td>
                            <td>${gp.plate}</td>
                            <td>${gp.driver_name || '-'}</td>
                            <td><span class="badge ${gp.status === 'Pending' ? 'pending' : 'sent'}">${gp.status}</span></td>
                            <td>${gp.dock || '-'}</td>
                            <td>${gp.arrival_date} ${gp.time}</td>
                            <td>${gp.exit_time || '-'}</td>
                        </tr>
                    `).join('');
                }

                // Filter Active Passes for the Grid
                const activePasses = passes.filter(p => !['Completed', 'Departed'].includes(p.status));

                if(activePasses.length === 0) {
                    gateBody.innerHTML = '<div style="grid-column: 1 / -1; text-align:center; padding: 2rem;">No active gate passes.</div>';
                } else {
                    gateBody.innerHTML = activePasses.map(gp => {
                        let poDropdown = '';
                        let expectedDateInput = `<input type="hidden" id="expectedDate_${gp.id}" value="${gp.expected_date || ''}">`;
                        let poNumberInput = `<input type="hidden" id="poNumber_${gp.id}" value="${gp.po_number || ''}">`;
                        
                        if (gp.status === 'Pending') {
                            if (gp.po_number) {
                                poDropdown = `<div style="color:var(--success); font-weight:bold; margin-bottom:0.5rem; font-size:0.85rem;">✓ Auto-Matched PO:<br/>${gp.po_number}</div>`;
                            } else {
                                poDropdown = `
                                    <select onchange="handlePOSelect(this, '${gp.id}')" style="margin-bottom:0.5rem; padding:0.4rem; background:rgba(212,175,55,0.1);">
                                        <option value="">Match to a Pending PO...</option>
                                        ${globalDeliveries.map(d => `<option value="${d.load}" data-driver="${d.driver_name}" data-date="${d.expected_date}" data-po="${d.po_number}" data-vendor="${d.vendor}" data-activity="${d.activity}">${d.po_number}: ${d.load}</option>`).join('')}
                                    </select><br/>
                                `;
                            }
                        } else if (gp.po_number) {
                            poDropdown = `<div style="color:var(--success); font-weight:bold; margin-bottom:0.5rem; font-size:0.85rem;">✓ PO: ${gp.po_number}</div>`;
                        }
                        
                        let dateStatusHtml = '<span style="color:var(--text-muted)">Unmatched</span>';
                        if (gp.expected_date && gp.arrival_date) {
                            if (gp.arrival_date === gp.expected_date) {
                                dateStatusHtml = '<span class="status-ontime">On Time</span>';
                            } else if (gp.arrival_date > gp.expected_date) {
                                dateStatusHtml = '<span class="status-delayed">Delayed</span>';
                            } else {
                                dateStatusHtml = '<span class="status-early">Early</span>';
                            }
                        }
                        
                        return `
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
                                ` : ''}
                                ${(gp.status !== 'Pending') ? `<button class="btn-danger" style="flex: 1;" onclick="deletePass('${gp.id}')">Delete Pass</button>` : ''}
                            </div>
                        </div>
                    `}).join('');
                }

                // Render Dock Table (Only 'Sent to Dock', 'Unloading' or 'Completed')
                const dockedPasses = passes.filter(p => ['Sent to Dock', 'Unloading', 'Completed'].includes(p.status));
                if(dockedPasses.length > 0) {
                    dockBody.innerHTML = dockedPasses.map(gp => `
                        <tr>
                            <td style="font-size:1.2rem; font-weight:bold; color:var(--accent-hover)">${gp.dock}</td>
                            <td>
                                <div>${gp.plate} (${gp.vehicle_type})</div>
                                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:2px;">Vendor: ${gp.vendor || 'N/A'}</div>
                                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:2px;">PO: ${gp.po_number || 'N/A'}</div>
                                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:2px;">Exp: ${gp.expected_date || 'N/A'}</div>
                            </td>
                            <td>${gp.driver_name}</td>
                            <td>
                                <div>${gp.load}</div>
                                <div style="font-size:0.8rem; color:var(--accent-hover); margin-top:4px; font-weight:bold;">Activity: ${gp.activity || 'Loading'}</div>
                                ${gp.photo ? `<div style="margin-top:4px;"><img src="/static/${gp.photo}" style="max-width:150px; border-radius:4px; display:block;" alt="Truck Photo"/></div>` : '<div style="font-size:0.8rem; color:var(--text-muted);">No Photo</div>'}
                            </td>
                            <td>
                                <span class="badge ${gp.status === 'Completed' ? 'sent' : 'pending'}">${gp.status}</span>
                            </td>
                            <td>
                                ${gp.status === 'Sent to Dock' ? `
                                    <button class="btn-primary" style="width:100%; background:var(--success); margin-bottom:4px;" onclick="updateDockStatus('${gp.id}', 'Unloading')">Allow</button>
                                    <button class="btn-danger" style="width:100%;" onclick="updateDockStatus('${gp.id}', 'Rejected')">Reject</button>
                                    ` : `
                                    <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 8px; margin-bottom: 8px;">
                                        <h4 style="margin:0 0 8px 0; color:var(--text-muted); font-size:0.85rem; display:flex; justify-content:space-between;">
                                            <span>UNLOADING SHEET (AI VERIFICATION)</span>
                                            <span style="color:var(--success);">98% Accuracy Tracker</span>
                                        </h4>
                                        <div style="margin-bottom: 8px;">
                                            <img src="/video_feed/07b3adfb" style="width:100%; border-radius:4px; max-height:200px; object-fit:cover;" alt="Live Dock Camera"/>
                                        </div>
                                        <table style="margin:0; font-size:0.85rem; background:transparent;">
                                            <thead>
                                                <tr><th style="padding:4px;">SKU / Desc</th><th style="padding:4px;">Expected</th><th style="padding:4px;">AI Count</th><th style="padding:4px;">Match</th></tr>
                                            </thead>
                                            <tbody>
                                                ${(gp.unloading_sheet && gp.unloading_sheet.length > 0) ? gp.unloading_sheet.map(item => {
                                                    const matchColor = (gp.unloaded_qty === item.expected) ? 'var(--success)' : 'var(--warning)';
                                                    const matchText = (gp.unloaded_qty === item.expected) ? 'YES' : 'NO';
                                                    return `
                                                    <tr>
                                                        <td style="padding:4px;">
                                                            <div style="font-family:monospace; color:var(--text-main);">${item.sku}</div>
                                                            <div style="font-size:0.75rem; color:var(--text-muted);">${item.description}</div>
                                                        </td>
                                                        <td style="padding:4px; font-weight:bold;">${item.expected} ${item.uom}</td>
                                                        <td style="padding:4px; font-weight:bold; color:var(--accent-hover);" id="unloaded_${gp.id}">${gp.unloaded_qty || 0}</td>
                                                        <td style="padding:4px; font-weight:bold; color:${matchColor};">${matchText}</td>
                                                    </tr>
                                                    `;
                                                }).join('') : `<tr><td colspan="4" style="text-align:center; padding:4px;">No PO Sheet Linked</td></tr>`}
                                            </tbody>
                                        </table>
                                    </div>
                                    <button class="btn-primary" style="width:100%; margin-bottom:4px;" onclick="scanPackages('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>🔄 Sync AI Tracker Count</button>
                                    <button class="btn-danger" style="width:100%; margin-bottom:4px;" onclick="completeUnload('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Finish Unloading</button>
                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="width:100%; background:var(--accent-hover);" onclick="sendInvoice('${gp.id}')">📧 Send Invoice to Vendor</button>` : ''}
                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="margin-top:4px; width:100%; background:var(--success);" onclick="checkout('${gp.id}', '${gp.plate}')">Check Out</button>` : ''}
                                `}
                            </td>
                        </tr>
                    `).join('');
                } else {
                    dockBody.innerHTML = '<tr><td colspan="5" style="text-align:center;">No trucks at docks.</td></tr>';
                }

            } catch(e) {}
        }
"""
pattern = re.compile(re.escape(fetch_start) + r'.*?' + re.escape(fetch_end), re.DOTALL)
html = pattern.sub(new_fetch.replace('\\', '\\\\') + '\n\n' + fetch_end, html)

# 3. Rewrite captureDriverPhoto
old_photo_start = "async function captureDriverPhoto(gp_id) {"
old_photo_end = """        }"""

new_photo_func = """async function captureDriverPhoto(gpId) {
            try {
                const camRes = await fetch('/api/cameras');
                const cameras = await camRes.json();
                const gateCams = cameras.filter(c => c.location === 'Gate');
                if(gateCams.length > 0) {
                    const snapRes = await fetch(`/api/cameras/${gateCams[0].id}/snap`, { method: 'POST' });
                    const snapData = await snapRes.json();
                    if(snapData.success) {
                        await fetch(`/api/gate_passes/${gpId}`, {
                            method: 'PUT',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ driver_photo: snapData.photo })
                        });
                        alert("Face successfully snapshotted!");
                        fetchGatePasses();
                    } else {
                        alert("Failed to snap face: " + snapData.message);
                    }
                } else {
                    alert("No Gate Camera active to snap from. Please connect a device camera.");
                }
            } catch(e) {
                console.error("Retake photo error", e);
            }
        }"""

# Manually replace the old function block
# We can just use string replace here, assuming it's uniquely formatted
# First find the exact function content
pattern_photo = re.compile(r'async function captureDriverPhoto\(gp_id\) \{.*?\n        \}', re.DOTALL)
html = pattern_photo.sub(new_photo_func.replace('\\', '\\\\'), html)


with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
