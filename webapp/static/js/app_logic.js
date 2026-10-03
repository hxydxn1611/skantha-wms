
        // Store deliveries globally in frontend so we can use them in the Gate Passes table
        let globalDeliveries = [];

        // Pre-fill date to today
        document.getElementById('expDate').valueAsDate = new Date();

        // Login Logic
        
        function toggleAuthMode() {
            const signin = document.getElementById('form-signin');
            const signup = document.getElementById('form-signup');
            const tagline = document.getElementById('login-tagline');
            if(signin.style.display === 'none') {
                signin.style.display = 'block';
                signup.style.display = 'none';
                if(tagline) tagline.innerText = "SEE EVERYTHING. MOVE WITH PRECISION.";
            } else {
                signin.style.display = 'none';
                signup.style.display = 'block';
                if(tagline) tagline.innerText = "CREATE A NEW W.A.R.L.O.G ACCOUNT.";
            }
        }

        async function doLogin() {
            const u = document.getElementById('username').value;
            const p = document.getElementById('password').value;
            
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({username: u, password: p})
                });
                const data = await res.json();
                
                if(data.success) {
                    document.getElementById('login-overlay').style.display = 'none';
                    const topBar = document.getElementById('top-bar');
                    if (topBar) topBar.style.display = 'flex';
                    const appLayout = document.getElementById('app-layout');
                    if (appLayout) appLayout.style.display = 'flex';
                    document.getElementById('main-header').style.display = 'flex';
                    document.getElementById('main-container').style.display = 'flex';
                    pollData();
                    fetchGatePasses();
                    fetchDeliveries();
                    if (typeof fetchObjectClasses === 'function') fetchObjectClasses();
                    if (typeof fetchVisionCameras === 'function') fetchVisionCameras();
                    if (typeof fetchVisionZones === 'function') fetchVisionZones();
                } else {
                    alert(data.message);
                }
            } catch(e) {
                console.error(e);
                alert("Login failed");
            }
        }

        async function doSignup() {
            const u = document.getElementById('reg-username').value;
            const p = document.getElementById('reg-password').value;
            if(!u || !p) {
                alert("Please fill all fields");
                return;
            }
            try {
                const res = await fetch('/api/register', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({username: u, password: p})
                });
                const data = await res.json();
                if(data.success) {
                    alert(data.message + ". You can now login.");
                    toggleAuthMode();
                    document.getElementById('username').value = u;
                    document.getElementById('password').value = p;
                } else {
                    alert(data.message);
                }
            } catch(e) {
                console.error(e);
                alert("Registration failed");
            }
        }

        // Tab Switching & Cross-Module Deep Navigation (Part 14)
        function switchTab(tabId) {
            document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            const targetView = document.getElementById(tabId + '-view');
            if (targetView) targetView.classList.add('active');
            const targetBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick')?.includes(`'${tabId}'`));
            if (targetBtn) targetBtn.classList.add('active');

            if (tabId === 'ai-vision-master') {
                if (typeof fetchObjectClasses === 'function') fetchObjectClasses();
                if (typeof fetchVisionCameras === 'function') fetchVisionCameras();
                if (typeof fetchVisionZones === 'function') fetchVisionZones();
            }
        }

        function navigateToEntity(entityType, entityId) {
            if (!entityType) return;
            if (entityType === 'delivery') {
                switchTab('deliveries');
            } else if (entityType === 'gate_pass') {
                switchTab('gate-passes');
            } else if (entityType === 'dock') {
                switchTab('docks');
            } else if (entityType === 'camera') {
                switchTab('cameras');
            } else if (entityType === 'zone') {
                switchTab('ai-vision-master');
                if (typeof switchVisionSubTab === 'function') {
                    const btn = document.querySelector(".vision-sub-btn[onclick*='vision-zones']");
                    switchVisionSubTab('vision-zones', btn);
                }
            } else if (entityType === 'traceability' || entityType === 'material') {
                switchTab('ai-vision-master');
                if (typeof switchVisionSubTab === 'function') {
                    const btn = document.querySelector(".vision-sub-btn[onclick*='vision-traceability']");
                    switchVisionSubTab('vision-traceability', btn);
                    if (entityId && typeof handleTraceabilityMaterialSelect === 'function') {
                        setTimeout(() => handleTraceabilityMaterialSelect(entityId), 200);
                    }
                }
            } else if (entityType === 'bin') {
                switchTab('master-hub');
                if (typeof switchSubTab === 'function') {
                    const btn = document.querySelector(".sub-tab-btn[onclick*='bin-master']");
                    switchSubTab('bin-master', btn);
                }
            } else if (entityType === 'sku') {
                switchTab('master-hub');
                if (typeof switchSubTab === 'function') {
                    const btn = document.querySelector(".sub-tab-btn[onclick*='sku-master']");
                    switchSubTab('sku-master', btn);
                }
            }
        }
        window.navigateToEntity = navigateToEntity;

        // Part 14 Deterministic Synthetic Integration Scenario
        async function triggerE2EScenario() {
            const modal = document.getElementById('modalE2EScenario');
            const body = document.getElementById('e2eModalBody');
            if (!modal || !body) return;
            modal.style.display = 'flex';
            body.innerHTML = `
                <div style="text-align:center; padding:2.5rem 1rem;">
                    <div style="font-size:2rem; margin-bottom:1rem;">⚙️</div>
                    <h4 style="margin:0 0 6px 0;">Executing Deterministic Inbound Integration Scenario...</h4>
                    <p style="color:var(--text-muted); font-size:0.85rem; margin:0;">Orchestrating Expected Delivery -> Gate Pass -> Truck -> Box -> Identity -> Validation -> Movement Events -> Material Traceability.</p>
                </div>
            `;

            try {
                const res = await fetch('/api/integration/e2e/test_scenario', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ po_number: 'PO-8821' })
                });
                const data = await res.json();
                if (data.success) {
                    let stepsHtml = data.steps.map(s => `
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; padding:8px 10px; background:var(--panel-subtle); border-radius:6px; margin-bottom:6px; border-left:3px solid var(--success); font-size:0.82rem;">
                            <div>
                                <strong style="color:var(--primary-navy);">Step ${s.step}: ${escapeHtml(s.name)}</strong>
                                <div style="color:var(--text-muted); font-size:0.75rem;">${escapeHtml(s.details)}</div>
                            </div>
                            <span class="badge sent" style="font-size:0.7rem;">✓ ${escapeHtml(s.status)}</span>
                        </div>
                    `).join('');

                    const gov = data.inventory_governance || {};

                    body.innerHTML = `
                        <div style="margin-bottom:1rem; padding:10px 14px; background:rgba(16,185,129,0.1); border:1px solid #10b981; border-radius:8px;">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <strong style="color:#059669; font-size:0.95rem;">✓ Inbound Logistics &amp; Vision Orchestration Verified</strong>
                                <span class="badge sent" style="font-size:0.75rem;">${data.execution_time_ms} ms</span>
                            </div>
                            <p style="margin:4px 0 0 0; font-size:0.8rem; color:var(--text-muted);">Unified platform communication successfully verified using shared master identifiers across WMS and W.A.R.L.O.G.</p>
                        </div>

                        <!-- Inventory Governance Compliance Banner -->
                        <div style="margin-bottom:1rem; padding:8px 12px; background:rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.3); border-radius:8px; font-size:0.8rem;">
                            <strong style="color:#2563eb;">🔒 Inventory Governance Boundary:</strong>
                            <span>Ledger Rows Before: <strong>${gov.inventory_count_before}</strong> | Rows After: <strong>${gov.inventory_count_after}</strong> | Mutations: <strong style="color:#10b981;">${gov.inventory_mutations} (Strictly Zero DB Writes)</strong>.</span>
                        </div>

                        <h5 style="margin:0 0 8px 0; font-size:0.85rem; color:var(--text-muted); text-transform:uppercase;">Scenario Step Trace</h5>
                        <div style="margin-bottom:1rem;">${stepsHtml}</div>

                        <h5 style="margin:0 0 8px 0; font-size:0.85rem; color:var(--text-muted); text-transform:uppercase;">Unified Master Reference Bindings</h5>
                        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px; font-size:0.8rem; background:var(--panel-subtle); padding:10px; border-radius:6px;">
                            <div><strong>Expected PO:</strong> ${escapeHtml(data.wms_bindings?.po_number || 'N/A')}</div>
                            <div><strong>Gate Pass:</strong> ${escapeHtml(data.wms_bindings?.gate_pass_id || 'N/A')}</div>
                            <div><strong>Truck Plate:</strong> ${escapeHtml(data.wms_bindings?.truck_plate || 'N/A')}</div>
                            <div><strong>Assigned Dock:</strong> ${escapeHtml(data.wms_bindings?.assigned_dock || 'N/A')}</div>
                            <div><strong>Vision Zone:</strong> ${escapeHtml(data.wms_bindings?.vision_zone || 'N/A')}</div>
                            <div><strong>Observing Camera:</strong> ${escapeHtml(data.wms_bindings?.camera_id || 'N/A')}</div>
                            <div><strong>Box Material ID:</strong> ${escapeHtml(data.wms_bindings?.material_id || 'N/A')}</div>
                            <div><strong>Destination Bin:</strong> ${escapeHtml(data.wms_bindings?.destination_bin || 'N/A')}</div>
                        </div>
                    `;
                    // Refresh main dashboard metrics
                    if (typeof pollData === 'function') pollData();
                } else {
                    body.innerHTML = `<div style="padding:1.5rem; color:var(--danger); text-align:center;">Scenario Error: ${escapeHtml(data.error || 'Failed')}</div>`;
                }
            } catch (e) {
                body.innerHTML = `<div style="padding:1.5rem; color:var(--danger); text-align:center;">Network Error: ${escapeHtml(e.message)}</div>`;
            }
        }
        window.triggerE2EScenario = triggerE2EScenario;

        // Data Polling
        let processedEvents = new Set();
        async function pollData() {
            try {
                // Fetch Stats
                const statRes = await fetch('/api/stats');
                const stats = await statRes.json();
                document.getElementById('stat-expected').innerText = stats.total_expected;
                document.getElementById('stat-arrived').innerText = stats.total_arrived;
                document.getElementById('stat-pending').innerText = stats.pending_dock;
                document.getElementById('stat-dock').innerText = stats.at_dock;

                // Fetch Unified Integration Overview (Part 14)
                try {
                    const intRes = await fetch('/api/integration/overview');
                    if (intRes.ok) {
                        const intData = await intRes.json();
                        const vKpis = intData.data?.vision_kpis || {};
                        const camEl = document.getElementById('stat-vision-cameras');
                        const evtEl = document.getElementById('stat-vision-events');
                        const matEl = document.getElementById('stat-vision-validated-materials');
                        const trcEl = document.getElementById('stat-vision-traceability');
                        if (camEl) camEl.innerText = vKpis.active_cameras ?? 0;
                        if (evtEl) evtEl.innerText = vKpis.active_events ?? 0;
                        if (matEl) matEl.innerText = vKpis.validated_materials ?? 0;
                        if (trcEl) trcEl.innerText = vKpis.traceability_records ?? 0;

                        // Render Unified Inbound Stream
                        const streamBody = document.getElementById('unifiedInboundStreamBody');
                        const stream = intData.data?.inbound_stream || [];
                        if (streamBody) {
                            if (stream.length === 0) {
                                streamBody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:1.5rem; color:var(--text-muted);">No active inbound shipments.</td></tr>';
                            } else {
                                streamBody.innerHTML = stream.map(s => `
                                    <tr>
                                        <td>
                                            <a href="javascript:void(0)" onclick="navigateToEntity('delivery', '${escapeHtml(s.po_number)}')" style="font-weight:700; color:var(--accent-hover); text-decoration:none;">
                                                📦 ${escapeHtml(s.po_number)}
                                            </a>
                                        </td>
                                        <td>
                                            <a href="javascript:void(0)" onclick="navigateToEntity('gate_pass', '${escapeHtml(s.gate_pass_id)}')" style="font-weight:600; text-decoration:none; color:var(--primary-navy);">
                                                🎫 ${escapeHtml(s.gate_pass_id)}
                                            </a>
                                            <div style="font-size:0.75rem; color:var(--text-muted); font-family:monospace;">${escapeHtml(s.plate)} (${escapeHtml(s.vehicle_type)})</div>
                                        </td>
                                        <td>${escapeHtml(s.vendor)}</td>
                                        <td>
                                            <a href="javascript:void(0)" onclick="navigateToEntity('dock', '${escapeHtml(s.dock)}')" style="font-weight:600; color:var(--accent-hover); text-decoration:none;">
                                                ⚓ ${escapeHtml(s.dock)}
                                            </a>
                                        </td>
                                        <td>
                                            <span class="badge" style="background:rgba(59,130,246,0.12); color:#2563eb; font-size:0.75rem; padding:2px 6px;">
                                                ${escapeHtml(s.zone_code || 'None')}
                                            </span>
                                        </td>
                                        <td>
                                            ${(s.monitoring_cameras && s.monitoring_cameras.length > 0) ? s.monitoring_cameras.map(c => `
                                                <a href="javascript:void(0)" onclick="navigateToEntity('camera', '${escapeHtml(c)}')" class="badge" style="background:rgba(16,185,129,0.12); color:#059669; font-size:0.75rem; padding:2px 6px; text-decoration:none; margin-right:3px;">
                                                    📹 ${escapeHtml(c)}
                                                </a>
                                            `).join('') : '<span style="color:var(--text-muted); font-size:0.75rem;">None</span>'}
                                        </td>
                                        <td style="font-weight:bold; color:#8b5cf6;">
                                            ${s.materials_observed_count} observed
                                        </td>
                                        <td>
                                            <span class="badge ${s.status === 'Sent to Dock' || s.status === 'Unloading' ? 'sent' : 'pending'}" style="font-size:0.72rem;">
                                                ${escapeHtml(s.status)}
                                            </span>
                                        </td>
                                        <td>
                                            <button class="btn-primary" style="font-size:0.75rem; padding:4px 8px; background:linear-gradient(135deg, #3b82f6, #8b5cf6);" onclick="navigateToEntity('traceability', '${escapeHtml(s.po_number)}')">
                                                🔍 Inspect Trace
                                            </button>
                                        </td>
                                    </tr>
                                `).join('');
                            }
                        }
                    }
                } catch (e) {
                    console.warn("Could not fetch integration overview:", e);
                }

                // Fetch Cameras
                const camRes = await fetch('/api/cameras');
                const cameras = await camRes.json();
                renderCameras(cameras);

                // Auto-create Passes and Auto-Count Packages
                cameras.forEach(cam => {
                    if(cam.location === 'Gate' && cam.events) {
                        cam.events.forEach(async (ev) => {
                            const eventKey = ev.plate + ev.time;
                            if(!processedEvents.has(eventKey) && ev.type !== 'Package_Auto_Count') {
                                processedEvents.add(eventKey);
                                await fetch('/api/gate_passes', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({ plate: ev.plate, type: ev.type })
                                });
                                fetchGatePasses(); 
                            }
                        });
                    }
                    if(cam.location === 'Dock' && cam.events) {
                        cam.events.forEach(async (ev) => {
                            const eventKey = "auto_" + ev.time + ev.track_id;
                            if(!processedEvents.has(eventKey) && ev.type === 'Package_Tracked') {
                                processedEvents.add(eventKey);
                                
                                const gpRes = await fetch('/api/gate_passes');
                                const gpList = await gpRes.json();
                                const activeDock = gpList.find(p => p.status === 'Sent to Dock' || p.status === 'Unloading');
                                if(activeDock) {
                                    // With the new API, we just trigger an unload step update to sync total_unloaded
                                    await fetch(`/api/dock/unload_step/${activeDock.id}`, {
                                        method: 'POST'
                                    });
                                    fetchGatePasses();
                                }
                            }
                        });
                    }
                });
            } catch(e) {}
        }

        // Deliveries
        document.getElementById('addDeliveryForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const manifestContainer = document.getElementById('manifestLinesContainer');
            const lines = manifestContainer.children;
            const manifest = [];
            for (let i = 0; i < lines.length; i++) {
                const lineId = lines[i].id.split('_')[1];
                const sku = document.getElementById(`manifestSku_${lineId}`).value;
                const vendor = document.getElementById(`manifestVendor_${lineId}`).value;
                const qty = parseInt(document.getElementById(`manifestQty_${lineId}`).value);
                if(sku && vendor && qty > 0) {
                    manifest.push({ sku_id: sku, vendor: vendor, expected: qty });
                }
            }

            if (manifest.length === 0) {
                alert("Please add at least one item to the Inbound Manifest.");
                return;
            }

            await fetch('/api/deliveries', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    po_number: document.getElementById('expPO').value,
                    expected_date: document.getElementById('expDate').value,
                    plate: document.getElementById('expPlate').value,
                    driver_name: document.getElementById('expDriver').value,
                    driver_phone: document.getElementById('expDriverPhone').value,
                    vendor_email: document.getElementById('expVendorEmail').value,
                    activity: document.getElementById('expActivity').value,
                    unloading_sheet: manifest
                })
            });
            e.target.reset();
            document.getElementById('manifestLinesContainer').innerHTML = '';
            window.addManifestLine();
            document.getElementById('expDate').valueAsDate = new Date();
            fetchDeliveries();
            pollData();
        });

        async function fetchDeliveries() {
            try {
                const res = await fetch('/api/deliveries');
                globalDeliveries = await res.json();
                
                const tbody = document.getElementById('expectedTableBody');
                const pBody = document.getElementById('poMasterBody');
                if(globalDeliveries.length === 0) {
                    const emptyMsg = '<tr><td colspan="8" style="text-align:center;">No expected deliveries registered.</td></tr>';
                    tbody.innerHTML = emptyMsg;
                    if(pBody) pBody.innerHTML = emptyMsg;
                    return;
                }
                const rowsHtml = globalDeliveries.map(d => {
                    let statusBadge = '<span class="badge pending" style="font-size:0.75rem;">Awaiting Gate</span>';
                    if (d.linked_gate_pass_id) {
                        statusBadge = `<span class="badge sent" style="font-size:0.75rem; background:#dcfce7; color:#15803d; border:1px solid #bbf7d0;">🔗 Pass ${d.linked_gate_pass_id} (${d.status})</span>`;
                    } else if (d.status === 'Arrived') {
                        statusBadge = `<span class="badge sent" style="font-size:0.75rem;">Arrived</span>`;
                    }
                    return `
                    <tr>
                        <td style="font-weight:bold; color:var(--accent-hover);">${d.po_number}</td>
                        <td>${d.expected_date}</td>
                        <td>${d.activity || 'Loading'}</td>
                        <td style="color:var(--text-muted);">${d.vendor || 'Unknown'}</td>
                        <td style="color:var(--text-muted);">${d.vendor_email || '-'}</td>
                        <td>${d.load}</td>
                        <td style="font-weight:bold;">${d.unloading_sheet && Array.isArray(d.unloading_sheet) ? d.unloading_sheet.reduce((sum, item) => sum + (parseInt(item.expected) || 0), 0) : '-'}</td>
                        <td style="font-family:monospace;">${d.plate || '<span style="color:#64748b; font-family:sans-serif;">Unknown / Not Provided</span>'}</td>
                        <td>
                            ${statusBadge}
                            <div style="margin-top:5px; display:flex; gap:4px; flex-wrap:wrap;">
                                ${d.linked_gate_pass_id ? `<button type="button" class="btn-primary" style="font-size:0.68rem; padding:2px 6px;" onclick="navigateToEntity('gate_pass', '${d.linked_gate_pass_id}')">🎫 Pass</button>` : ''}
                                <button type="button" class="btn-primary" style="font-size:0.68rem; padding:2px 6px; background:#8b5cf6;" onclick="navigateToEntity('traceability', '${d.po_number}')">🔍 Trace</button>
                            </div>
                        </td>
                    </tr>
                `;}).join('');
                
                tbody.innerHTML = rowsHtml;
                if(pBody) pBody.innerHTML = rowsHtml;
                
                fetchGatePasses();
            } catch(e) {}
        }

        // Helper to autofill row when PO is selected
        function handlePOSelect(selectElement, gpId) {
            const selectedOption = selectElement.options[selectElement.selectedIndex];
            if(selectedOption.value) {
                // value holds the load details, data-driver holds the driver, data-date holds expected date, text holds po
                document.getElementById(`load_${gpId}`).value = selectedOption.value;
                document.getElementById(`expectedDate_${gpId}`).value = selectedOption.getAttribute('data-date');
                document.getElementById(`poNumber_${gpId}`).value = selectedOption.getAttribute('data-po');
                const activity = selectedOption.getAttribute('data-activity');
                if(activity && document.getElementById(`activity_${gpId}`)) {
                    document.getElementById(`activity_${gpId}`).value = activity;
                }
                const driver = selectedOption.getAttribute('data-driver');
                if(driver) {
                    document.getElementById(`driver_${gpId}`).value = driver;
                }
                const vendor = selectedOption.getAttribute('data-vendor');
                if(vendor) {
                    document.getElementById(`vendor_${gpId}`).value = vendor;
                }
                const phone = selectedOption.getAttribute('data-phone');
                if(phone && document.getElementById(`driver_phone_${gpId}`)) {
                    document.getElementById(`driver_phone_${gpId}`).value = phone;
                }
                const email = selectedOption.getAttribute('data-email');
                if(email && document.getElementById(`vendor_email_${gpId}`)) {
                    document.getElementById(`vendor_email_${gpId}`).value = email;
                }
                // Silently update PO backend on selection
                fetch(`/api/gate_passes/${gpId}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ po_number: selectedOption.getAttribute('data-po'), vendor_email: email, vendor: vendor })
                });
            }
        }

        // Gate Passes & Docks
        async function fetchGatePasses() {
            try {
                const res = await fetch('/api/gate_passes');
                const passes = await res.json();
                window.globalGatePasses = passes;
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
                    masterBody.innerHTML = passes.map(gp => {
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
                        <tr>
                            <td>${gp.id}</td>
                            <td>${gp.po_number || '-'}</td>
                            <td>${gp.plate}</td>
                            <td>${gp.driver_name || '-'}</td>
                            <td><span class="badge ${gp.status === 'Pending' ? 'pending' : 'sent'}">${gp.status}</span></td>
                            <td>${gp.dock || '-'}</td>
                            <td>${gp.arrival_date} ${gp.time}</td>
                            <td>${dateStatusHtml}</td>
                            <td>${gp.exit_time || '-'}</td>
                        </tr>
                        `;
                    }).join('');
                }

                // Filter Active Passes for the Grid
                const activePasses = passes.filter(p => !['Exited', 'Departed'].includes(p.status));

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
                                    <select onchange="handlePOSelect(this, '${gp.id}')" style="margin-bottom:0.5rem; padding:0.4rem; background:#eff6ff; border:1px solid #bfdbfe; color:#1e40af; font-weight:600;">
                                        <option value="">Match to a Pending PO...</option>
                                        ${globalDeliveries.map(d => `<option value="${d.load}" data-driver="${d.driver_name}" data-date="${d.expected_date}" data-po="${d.po_number}" data-vendor="${d.vendor}" data-activity="${d.activity}" data-phone="${d.driver_phone || ''}" data-email="${d.vendor_email || ''}">${d.po_number}: ${d.load} (${d.vendor} - ${d.vendor_email || 'No Email'})</option>`).join('')}
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
                        <div style="background: var(--panel-bg); border: 1px solid var(--border-blue); border-radius: 12px; padding: 1.5rem; display: flex; flex-direction: column; gap: 1rem; position: relative; box-shadow: var(--card-shadow);">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap:wrap; gap:8px;">
                                <div>
                                    <h3 style="margin: 0; color: var(--accent-hover); font-size: 1.2rem;">Pass ${gp.id}</h3>
                                    <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;">Arrival: ${gp.arrival_date} ${gp.time}</div>
                                </div>
                                <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
                                    <span class="badge ${gp.status === 'Pending' ? 'pending' : 'sent'}">${gp.status}</span>
                                    <div style="display:flex; gap:4px; margin-top:2px;">
                                        ${gp.po_number ? `<button type="button" class="btn-primary" style="font-size:0.68rem; padding:2px 6px; background:#3b82f6;" onclick="navigateToEntity('delivery', '${gp.po_number}')">📦 PO</button>` : ''}
                                        ${(gp.dock && gp.dock !== 'Not Assigned') ? `<button type="button" class="btn-primary" style="font-size:0.68rem; padding:2px 6px; background:#10b981;" onclick="navigateToEntity('dock', '${gp.dock}')">⚓ Dock</button>` : ''}
                                        <button type="button" class="btn-primary" style="font-size:0.68rem; padding:2px 6px; background:#8b5cf6;" onclick="navigateToEntity('traceability', '${gp.id}')">🔍 Trace</button>
                                    </div>
                                </div>
                            </div>
                            
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; background: var(--panel-subtle); border: 1px solid var(--border-light); padding: 1rem; border-radius: 8px;">
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
                                    <div style="background: var(--panel-subtle); border: 1px solid var(--border-light); padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                                        <h4 style="margin:0 0 8px 0; color:var(--text-muted); font-size:0.85rem; display:flex; justify-content:space-between;">
                                            <span>UNLOADING SHEET (AI VERIFICATION)</span>
                                            <span style="color:var(--success);">98% Accuracy Tracker</span>
                                        </h4>
                                        <div style="margin-bottom: 8px; position:relative;">
                                            <img src="/video_feed/${(gp.dock === 'Dock 2') ? 'CAM-003' : 'CAM-002'}" style="width:100%; border-radius:4px; max-height:200px; object-fit:cover;" alt="Live Dock Camera" onerror="this.src='/static/test_scenes/dock01_test.jpg'"/>
                                            <span style="position:absolute; bottom:6px; right:6px; background:rgba(0,0,0,0.7); color:#fff; font-size:0.7rem; padding:2px 6px; border-radius:4px;">
                                                📹 ${(gp.dock === 'Dock 2') ? 'CAM-003 (Dock 02)' : 'CAM-002 (Dock 01)'}
                                            </span>
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
                                    <button class="btn-primary" style="width:100%; margin-bottom:4px; background:linear-gradient(135deg, #3b82f6, #8b5cf6);" onclick="navigateToEntity('traceability', 'B104')">🔍 View Inbound Material Traceability</button>
                                    <div style="display:flex; gap: 4px; margin-bottom:4px;">
                                        <button class="btn-primary" style="flex: 1;" onclick="scanPackages('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>🔄 Sync AI Tracker</button>
                                        <input type="number" id="manual_add_${gp.id}" placeholder="+Qty" style="width: 60px; padding: 4px; margin: 0; background: var(--panel-bg); color: var(--text-main); border: 1px solid var(--border-light); border-radius: 4px;" ${gp.status === 'Completed' ? 'disabled' : ''}>
                                        <button class="btn-primary" style="padding: 4px 8px; background: var(--accent);" onclick="manualAddPackages('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Add</button>
                                    </div>
                                    
                                    ${gp.status !== 'Completed' ? `
                                        <div style="background: var(--panel-bg); border: 1px solid var(--border-light); padding: 8px; border-radius: 4px; margin-bottom: 8px;">
                                            <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Putaway Bin Allocation</label>
                                            <div style="display:flex; gap: 4px; margin-top:4px;">
                                                <input type="text" id="bin_${gp.id}" value="${gp.bin_allocation || ''}" placeholder="Assign Bin ID" style="flex:1; padding: 4px; margin: 0; background: var(--panel-subtle); color: var(--text-main); border: 1px solid var(--border-light); border-radius: 4px;">
                                                <button class="btn-primary" style="padding: 4px 8px; font-size: 0.75rem; background: var(--accent);" onclick="suggestBin('${gp.id}')">🤖 Auto-Suggest</button>
                                            </div>
                                        </div>
                                    ` : `<div style="font-size:0.85rem; margin-bottom:8px;"><strong>Allocated Bin:</strong> ${gp.bin_allocation}</div>`}
                                    <button class="btn-danger" style="width:100%; margin-bottom:4px;" onclick="completeUnload('${gp.id}')" ${gp.status === 'Completed' ? 'disabled' : ''}>Finish Unloading</button>
                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="width:100%; background:var(--accent-hover);" onclick="sendInvoice('${gp.id}')">📧 Send Invoice to Vendor</button>` : ''}
                                    ${gp.status === 'Completed' ? `<button class="btn-primary" style="margin-top:4px; width:100%; background:var(--accent);" onclick="downloadGateManifest('${gp.id}')">📄 PDF Manifest</button>` : ''}
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


        async function updatePass(id) {
            const plate = document.getElementById(`plate_${id}`).value;
            const driver = document.getElementById(`driver_${id}`).value;
            const driverPhone = document.getElementById(`driver_phone_${id}`) ? document.getElementById(`driver_phone_${id}`).value : '';
            const vendor = document.getElementById(`vendor_${id}`).value;
            const vendorEmail = document.getElementById(`vendor_email_${id}`) ? document.getElementById(`vendor_email_${id}`).value : '';
            const load = document.getElementById(`load_${id}`).value;
            const dock = document.getElementById(`dock_${id}`).value;
            const expectedDate = document.getElementById(`expectedDate_${id}`).value;
            const poNumber = document.getElementById(`poNumber_${id}`).value;
            const activity = document.getElementById(`activity_${id}`).value;
            
            if(dock === 'Not Assigned') { alert("Please assign a dock before approving."); return; }
            const res = await fetch(`/api/gate_passes/${id}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ plate: plate, driver_name: driver, driver_phone: driverPhone, vendor: vendor, vendor_email: vendorEmail, load: load, dock: dock, expected_date: expectedDate, po_number: poNumber, activity: activity, status: 'Sent to Dock' })
            });
            const data = await res.json();
            if(data.otp_generated) {
                if(data.sms_response) {
                    if(data.sms_response.success) {
                        alert(`REAL SMS Sent! OTP ${data.otp_generated} sent to Driver Phone ${driverPhone || 'N/A'}`);
                    } else {
                        alert(`SMS Delivery Failed (Quota Reached?): ${data.sms_response.error || 'Unknown error'}\n\nSince this is a free SMS tier, please use this OTP manually for testing: ${data.otp_generated}`);
                    }
                } else {
                    alert(`No valid driver phone. Testing OTP is: ${data.otp_generated}`);
                }
            }
            fetchGatePasses();
            fetchDeliveries();
            pollData();
        }

        async function deletePass(id) {
            if(confirm('Are you sure you want to delete this Gate Pass?')) {
                await fetch(`/api/gate_passes/${id}`, { method: 'DELETE' });
                fetchGatePasses();
                fetchDeliveries();
                pollData();
            }
        }
        
        async function updateDockStatus(id, newStatus) {
            await fetch(`/api/gate_passes/${id}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ status: newStatus })
            });
            fetchGatePasses();
            fetchDeliveries();
            pollData();
        }

        async function createManualPass() {
            const plate = prompt("Enter Vehicle Plate (or leave blank):", "");
            if(plate !== null) {
                let photoUrl = "";
                
                // Try to find a Gate camera to snap a photo from
                try {
                    const camRes = await fetch('/api/cameras');
                    const cameras = await camRes.json();
                    const gateCams = cameras.filter(c => c.location === 'Gate');
                    if(gateCams.length > 0) {
                        if(confirm("Do you want to capture a photo from the Gate Camera?")) {
                            const snapRes = await fetch(`/api/cameras/${gateCams[0].id}/snap`, { method: 'POST' });
                            const snapData = await snapRes.json();
                            if(snapData.success) {
                                photoUrl = snapData.photo;
                                alert("Photo captured successfully!");
                            } else {
                                alert("Failed to capture photo: " + snapData.message);
                            }
                        }
                    } else {
                        alert("No Gate Camera active. Creating pass without photo.");
                    }
                } catch(e) {
                    console.error("Camera snap error", e);
                }
                
                await fetch('/api/gate_passes', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ plate: plate, type: 'Manual Entry', photo: photoUrl })
                });
                fetchGatePasses();
                fetchDeliveries();
            }
        }
        
        async function retakePhoto(gpId) {
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
                            body: JSON.stringify({ photo: snapData.photo })
                        });
                        fetchGatePasses();
                    } else {
                        alert("Failed to snap photo: " + snapData.message);
                    }
                } else {
                    alert("No Gate Camera active to snap from.");
                }
            } catch(e) {
                console.error("Retake photo error", e);
            }
        }
        
        async function scanPackages(id) {
            const res = await fetch(`/api/dock/unload_step/${id}`, { method: 'POST' });
            const data = await res.json();
            if(data.success) {
                // We re-render the whole table to update the Unloading Sheet 'Match' coloring
                fetchGatePasses();
                console.log("Synced total: " + data.total + " packages");
            } else {
                alert(data.message);
            }
        }

        
        async function manualAddPackages(gp_id) {
            const qtyInput = document.getElementById(`manual_add_${gp_id}`);
            const count = parseInt(qtyInput.value) || 0;
            if (count === 0) return;
            
            try {
                const res = await fetch(`/api/dock/auto_add/${gp_id}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({count: count})
                });
                const data = await res.json();
                if(data.success) {
                    alert(`Added ${count} items. Total: ${data.total}`);
                    fetchGatePasses();
                } else {
                    alert('Error: ' + data.message);
                }
            } catch(e) {
                alert('Connection error');
            }
        }

        
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
    
        async function completeUnload(id) {
            const bin = document.getElementById(`bin_${id}`) ? document.getElementById(`bin_${id}`).value : "";
            await fetch(`/api/gate_passes/${id}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ status: 'Completed', bin_allocation: bin })
            });
            fetchGatePasses();
        }

        async function verifyOtp(id) {
            const otp = prompt("Enter the 4-digit OTP sent to the driver:");
            if(otp) {
                const res = await fetch('/api/gate/verify_otp', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ gp_id: id, otp: otp })
                });
                const data = await res.json();
                alert(data.message);
                if(data.success) fetchGatePasses();
            }
        }

        
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

        async function checkout(id, expectedPlate) {
            const plate = prompt(`Scan/Enter Plate for Check-Out (Expected: ${expectedPlate}):`);
            if(plate) {
                if(confirm('Proceed to scan Driver Face for checkout verification?')) {
                    const res = await fetch('/api/gate/checkout', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ gp_id: id, plate: plate, face_check: true })
                    });
                    const data = await res.json();
                    alert(data.message);
                    if(data.success) {
                        fetchGatePasses();
                        if(typeof fetchVehicleLogs === 'function') fetchVehicleLogs();
                    }
                }
            }
        }

        async function sendInvoice(id) {
            let email = document.getElementById(`vendor_email_${id}`) ? document.getElementById(`vendor_email_${id}`).value : '';
            
            if(!email) {
                // Try to find it from the PO automatically first
                const gp = window.globalGatePasses?.find(g => g.id === id);
                if (gp) {
                    let deliv = null;
                    if (gp.po_number) {
                        deliv = globalDeliveries.find(d => d.po_number === gp.po_number);
                    }
                    if (!deliv && gp.vendor) {
                        deliv = globalDeliveries.find(d => d.vendor === gp.vendor);
                    }
                    if (!deliv && gp.plate) {
                        deliv = globalDeliveries.find(d => d.plate === gp.plate);
                    }
                    
                    // Ultimate fallback for demo: just grab the most recently added expected delivery's email
                    if (!deliv && globalDeliveries.length > 0) {
                        deliv = globalDeliveries[globalDeliveries.length - 1]; // get latest
                    }
                    
                    if (deliv && deliv.vendor_email) {
                        email = deliv.vendor_email;
                    }
                }
            }
            
            if(!email) {
                alert("Vendor email could not be found automatically. Please ensure the vendor email was provided during pre-registration.");
                return;
            }
            
            // Update the input field visually if it exists
            if(document.getElementById(`vendor_email_${id}`)) {
                document.getElementById(`vendor_email_${id}`).value = email;
            }
            
            const res = await fetch('/api/gate/invoice', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ gp_id: id, vendor_email: email })
            });
            const data = await res.json();
            alert(data.message);
            if(typeof fetchInvoices === 'function') fetchInvoices();
        }

        // --- NEW FEATURES: DRIVER PHOTO, VEHICLE LOG, INVOICES ---
        async function captureDriverPhoto(gpId) {
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
                        // alert("Face successfully snapshotted!");
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
        }

        async function fetchVehicleLogs() {
            try {
                const res = await fetch('/api/vehicle_log');
                const logs = await res.json();
                const tbody = document.getElementById('vehicleLogBody');
                if(!tbody) return;
                if(logs.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">No vehicle logs found.</td></tr>';
                    return;
                }
                tbody.innerHTML = logs.map(l => `
                    <tr>
                        <td style="font-family:monospace;">${l.id}</td>
                        <td style="color:var(--accent); font-weight:bold;">${l.gp_id}</td>
                        <td style="font-family:monospace; font-size:1.1rem;">${l.plate}</td>
                        <td>${l.driver_name}</td>
                        <td>${l.entry_time}</td>
                        <td>${l.exit_time || '-'}</td>
                        <td><span class="badge ${l.status === 'Departed' ? 'sent' : 'pending'}">${l.status}</span></td>
                    </tr>
                `).join('');
            } catch(e) {}
        }

        async function fetchInvoices() {
            try {
                const res = await fetch('/api/invoices');
                const invs = await res.json();
                const tbody = document.getElementById('invoicesBody');
                if(!tbody) return;
                if(invs.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">No invoices found.</td></tr>';
                    return;
                }
                tbody.innerHTML = invs.map(i => `
                    <tr>
                        <td style="font-family:monospace;">${i.id}</td>
                        <td style="color:var(--accent); font-weight:bold;">${i.gp_id}</td>
                        <td>${i.po_number}</td>
                        <td>${i.vendor}</td>
                        <td>${i.vendor_email}</td>
                        <td>${i.generated_at}</td>
                        <td><a href="/static/invoices/${i.pdf_path}" target="_blank" class="btn-primary" style="text-decoration:none; display:inline-block; padding:4px 12px; font-size:0.85rem;">📄 Download PDF</a></td>
                    </tr>
                `).join('');
            } catch(e) {}
        }

        // Camera Management & Device Streaming State
        const activeDeviceStreams = {}; // camId -> { stream, intervalId, videoEl, canvasEl, facingMode }

        function isMobileDevice() {
            return /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        }

        function handleCamTypeChange() {
            const camType = document.getElementById('camType').value;
            const isDevice = (camType === 'Device Camera');
            
            const facingGroup = document.getElementById('deviceFacingGroup');
            const urlGroup = document.getElementById('camUrlGroup');
            const camUrlInput = document.getElementById('camUrl');
            const camNameInput = document.getElementById('camName');
            const camVendorSelect = document.getElementById('camVendor');

            if (facingGroup) facingGroup.style.display = isDevice ? 'block' : 'none';
            if (urlGroup) urlGroup.style.display = isDevice ? 'none' : 'block';
            if (camUrlInput) camUrlInput.required = !isDevice;

            if (isDevice) {
                if (!camNameInput.value || camNameInput.value === 'Main Gate' || camNameInput.value.includes('Camera')) {
                    camNameInput.value = isMobileDevice() ? 'Mobile Device Camera' : 'Laptop Built-in Camera';
                }
                if (camVendorSelect) camVendorSelect.value = 'Built-in Device';
                if (camUrlInput) camUrlInput.value = 'device://client';
                const facingSelect = document.getElementById('camFacing');
                if (facingSelect) {
                    facingSelect.value = isMobileDevice() ? 'environment' : 'user';
                }
            } else {
                if (camUrlInput && camUrlInput.value === 'device://client') {
                    camUrlInput.value = '';
                }
                if (camVendorSelect && camVendorSelect.value === 'Built-in Device') {
                    camVendorSelect.value = 'Hikvision';
                }
                
                const urlLabel = document.getElementById('camUrlLabel');
                if(camType === 'USB Webcam') {
                    if(urlLabel) urlLabel.innerText = "USB Camera Index (or Path)";
                    if(camUrlInput) {
                        camUrlInput.placeholder = "Enter 0, 1, 2... or /dev/video0";
                        if(!camUrlInput.value || camUrlInput.value.startsWith('http')) {
                            camUrlInput.value = "0";
                        }
                    }
                } else {
                    if(urlLabel) urlLabel.innerText = "Stream URL";
                    if(camUrlInput) {
                        camUrlInput.placeholder = "http://192.168.x.x:8080/video";
                        if(camUrlInput.value === "0" || camUrlInput.value === "1") {
                            camUrlInput.value = "";
                        }
                    }
                }
            }
        }

        document.getElementById('addCameraForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('connectCameraBtn');
            const originalBtnText = btn.innerText;
            const camType = document.getElementById('camType').value;
            const name = document.getElementById('camName').value;
            const rawLoc = document.getElementById('camLocation').value;
            let location = rawLoc;
            if(rawLoc === 'Bin Location') {
                const bin = document.getElementById('camBinId').value;
                if(bin) location = `Bin: ${bin}`;
            }
            const vendor = document.getElementById('camVendor').value;
            const url = document.getElementById('camUrl').value;
            const facingMode = document.getElementById('camFacing') ? document.getElementById('camFacing').value : 'user';

            if (camType === 'Device Camera') {
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
                        alert("Device camera access on mobile over Wi-Fi requires HTTPS or localhost. Please connect via HTTPS or enable 'Insecure origins treated as secure' in chrome://flags for this URL.");
                    } else {
                        alert("Camera access is not supported or was blocked by browser security permissions.");
                    }
                    return;
                }

                btn.innerText = "Requesting Camera Access...";
                btn.disabled = true;

                let stream = null;
                try {
                    stream = await navigator.mediaDevices.getUserMedia({
                        video: {
                            facingMode: { ideal: facingMode },
                            width: { ideal: 640 },
                            height: { ideal: 480 }
                        },
                        audio: false
                    });
                } catch(err) {
                    try {
                        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
                    } catch(fallbackErr) {
                        alert("Unable to open device camera: " + (fallbackErr.message || fallbackErr.name));
                        btn.innerText = originalBtnText;
                        btn.disabled = false;
                        return;
                    }
                }

                btn.innerText = "Starting AI Pipeline...";

                try {
                    const res = await fetch('/api/cameras', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            name: name,
                            location: location,
                            url: 'device://client',
                            type: 'Device Camera',
                            vendor: vendor
                        })
                    });
                    const camData = await res.json();
                    const camId = camData.id;

                    // Create offscreen video element to capture frames
                    const videoEl = document.createElement('video');
                    videoEl.autoplay = true;
                    videoEl.playsInline = true;
                    videoEl.muted = true;
                    videoEl.srcObject = stream;
                    await videoEl.play();

                    const canvasEl = document.createElement('canvas');
                    canvasEl.width = 640;
                    canvasEl.height = 480;
                    const ctx = canvasEl.getContext('2d');

                    let isSending = false;
                    const intervalId = setInterval(() => {
                        if (isSending) return;
                        if (videoEl.readyState < 2) return;
                        ctx.drawImage(videoEl, 0, 0, 640, 480);
                        canvasEl.toBlob((blob) => {
                            if (!blob) return;
                            isSending = true;
                            fetch(`/api/cameras/${camId}/frame`, {
                                method: 'POST',
                                headers: {'Content-Type': 'image/jpeg'},
                                body: blob
                            })
                            .catch(() => {})
                            .finally(() => { isSending = false; });
                        }, 'image/jpeg', 0.65);
                    }, 125); // ~8 FPS streaming rate

                    activeDeviceStreams[camId] = {
                        stream: stream,
                        intervalId: intervalId,
                        videoEl: videoEl,
                        canvasEl: canvasEl,
                        facingMode: facingMode
                    };

                    e.target.reset();
                    handleCamTypeChange();
                    pollData();
                } catch(serverErr) {
                    alert("Failed to initialize camera on server: " + serverErr.message);
                    stream.getTracks().forEach(t => t.stop());
                } finally {
                    btn.innerText = originalBtnText;
                    btn.disabled = false;
                }
            } else {
                await fetch('/api/cameras', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: name,
                        location: location,
                        url: url,
                        type: camType,
                        vendor: vendor
                    })
                });
                e.target.reset();
                handleCamTypeChange();
                pollData();
            }
        });

        async function flipDeviceCamera(camId) {
            const info = activeDeviceStreams[camId];
            if (!info) return;

            info.stream.getTracks().forEach(t => t.stop());
            clearInterval(info.intervalId);

            const nextFacing = (info.facingMode === 'environment') ? 'user' : 'environment';
            info.facingMode = nextFacing;

            try {
                const newStream = await navigator.mediaDevices.getUserMedia({
                    video: {
                        facingMode: { ideal: nextFacing },
                        width: { ideal: 640 },
                        height: { ideal: 480 }
                    },
                    audio: false
                });
                info.stream = newStream;
                info.videoEl.srcObject = newStream;
                await info.videoEl.play();

                let isSending = false;
                info.intervalId = setInterval(() => {
                    if (isSending) return;
                    if (info.videoEl.readyState < 2) return;
                    const ctx = info.canvasEl.getContext('2d');
                    ctx.drawImage(info.videoEl, 0, 0, 640, 480);
                    info.canvasEl.toBlob((blob) => {
                        if (!blob) return;
                        isSending = true;
                        fetch(`/api/cameras/${camId}/frame`, {
                            method: 'POST',
                            headers: {'Content-Type': 'image/jpeg'},
                            body: blob
                        })
                        .catch(() => {})
                        .finally(() => { isSending = false; });
                    }, 'image/jpeg', 0.65);
                }, 125);
            } catch(e) {
                alert("Failed to flip camera lens: " + e.message);
            }
        }

        async function deleteCamera(camId) {
            if (!confirm("Are you sure you want to disconnect this camera?")) return;
            if (activeDeviceStreams[camId]) {
                activeDeviceStreams[camId].stream.getTracks().forEach(t => t.stop());
                clearInterval(activeDeviceStreams[camId].intervalId);
                delete activeDeviceStreams[camId];
            }
            await fetch(`/api/cameras/${camId}`, { method: 'DELETE' });
            const card = document.getElementById(`cam-${camId}`);
            if (card) card.remove();
            pollData();
        }

        async function manualSnapshot(camId) {
            try {
                const snapRes = await fetch(`/api/cameras/${camId}/snap`, { method: 'POST' });
                const snapData = await snapRes.json();
                if(snapData.success) {
                    window.open(`/static/${snapData.photo}`, '_blank');
                } else {
                    alert("Failed to snap: " + snapData.message);
                }
            } catch(e) {
                console.error("Snapshot error", e);
            }
        }

        window.addEventListener('beforeunload', () => {
            Object.values(activeDeviceStreams).forEach(item => {
                if (item.stream) item.stream.getTracks().forEach(t => t.stop());
                if (item.intervalId) clearInterval(item.intervalId);
            });
        });

        function renderCameras(cameras) {
            const grid = document.getElementById('cameraGrid');
            const currentIds = new Set(cameras.map(c => `cam-${c.id}`));
            
            // Remove cards of cameras that were disconnected
            Array.from(grid.children).forEach(child => {
                if (!currentIds.has(child.id)) {
                    child.remove();
                }
            });

            cameras.forEach(cam => {
                let card = document.getElementById(`cam-${cam.id}`);
                const isLocalDevice = !!activeDeviceStreams[cam.id];
                if (!card) {
                    card = document.createElement('div');
                    card.className = 'glass-panel';
                    card.id = `cam-${cam.id}`;
                    card.innerHTML = `
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
                            <strong style="font-size:1.1rem; color:var(--primary-navy);">${cam.name}</strong>
                            <div style="display:flex; gap:6px; align-items:center;">
                                ${cam.type === 'Device Camera' ? '<span class="badge pulse-badge" style="background:#dcfce7; color:#15803d; border:1px solid #bbf7d0;">● Device Stream</span>' : ''}
                                <span class="badge pending">${cam.location}</span>
                            </div>
                        </div>
                        <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:0.75rem; display:flex; gap:10px;">
                            <span>Type: ${cam.type}</span>
                            <span>Vendor: ${cam.vendor}</span>
                        </div>
                        <div class="video-container" onclick="openFullscreen('/video_feed/${cam.id}')">
                            <img src="/video_feed/${cam.id}" alt="Live Feed">
                            <div style="position:absolute; bottom:10px; right:10px; background:rgba(0,0,0,0.6); padding:4px 8px; border-radius:4px; font-size:0.7rem; pointer-events:none; color:white;">&#x26F6; Fullscreen</div>
                        </div>
                        <div style="display:flex; gap:8px; margin-top:0.75rem;">
                            <button class="btn-primary" style="flex:1; font-size:0.8rem; padding:6px; background:var(--success);" onclick="manualSnapshot('${cam.id}')">📸 Snapshot</button>
                            ${isLocalDevice ? `<button class="btn-primary" style="flex:1; font-size:0.8rem; padding:6px;" onclick="flipDeviceCamera('${cam.id}')">🔄 Flip Lens</button>` : ''}
                            <button class="btn-danger" style="flex:1; font-size:0.8rem; padding:6px;" onclick="deleteCamera('${cam.id}')">Disconnect</button>
                        </div>
                    `;
                    grid.appendChild(card);
                }
            });
        }
        
        // Fullscreen Logic
        function openFullscreen(url) {
            const overlay = document.getElementById('fsOverlay');
            const img = document.getElementById('fsImg');
            img.src = url;
            overlay.classList.add('active');
        }
        function closeFullscreen() {
            const overlay = document.getElementById('fsOverlay');
            const img = document.getElementById('fsImg');
            overlay.classList.remove('active');
            img.src = "";
        }

        // Background polling
        setInterval(() => {
            if (document.getElementById('main-container').style.display !== 'none') {
                pollData();
                if(document.getElementById('master-hub-view').classList.contains('active')) {
                    if(document.getElementById('vehicle-master-sub').style.display !== 'none' && typeof fetchVehicleLogs === 'function') fetchVehicleLogs();
                    if(document.getElementById('invoice-master-sub').style.display !== 'none' && typeof fetchInvoices === 'function') fetchInvoices();
                    if(document.getElementById('bin-master-sub').style.display !== 'none' && typeof fetchBins === 'function') fetchBins();
                    if(document.getElementById('gate-pass-master-sub').style.display !== 'none' && typeof fetchGatePasses === 'function') fetchGatePasses();
                    if(document.getElementById('po-master-sub').style.display !== 'none' && typeof fetchDeliveries === 'function') fetchDeliveries();
                }
                if(document.getElementById('ai-vision-master-view')?.classList.contains('active')) {
                    if(document.getElementById('vision-objects-sub')?.style.display !== 'none' && typeof fetchObjectClasses === 'function') {
                        const searchInput = document.getElementById('objClassSearchInput');
                        if (!searchInput || document.activeElement !== searchInput) {
                            fetchObjectClasses();
                        }
                    }
                    if(document.getElementById('vision-cameras-sub')?.style.display !== 'none' && typeof fetchVisionCameras === 'function') {
                        const searchInput = document.getElementById('visionCamSearchInput');
                        if (!searchInput || document.activeElement !== searchInput) {
                            fetchVisionCameras();
                        }
                    }
                    if(document.getElementById('vision-zones-sub')?.style.display !== 'none' && typeof fetchVisionZones === 'function') {
                        const searchInput = document.getElementById('visionZoneSearchInput');
                        if (!searchInput || document.activeElement !== searchInput) {
                            fetchVisionZones();
                        }
                    }
                }
            }
        }, 2000);

        // Global Modal Keyboard Accessibility (Escape to close)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (typeof closeAddObjectClassModal === 'function') closeAddObjectClassModal();
                if (typeof closeEditObjectClassModal === 'function') closeEditObjectClassModal();
                if (typeof closeViewObjectClassModal === 'function') closeViewObjectClassModal();
                if (typeof closeConfigureCameraModal === 'function') closeConfigureCameraModal();
                if (typeof closeViewCameraModal === 'function') closeViewCameraModal();
                if (typeof closeAddZoneModal === 'function') closeAddZoneModal();
                if (typeof closeEditZoneModal === 'function') closeEditZoneModal();
                if (typeof closeViewZoneModal === 'function') closeViewZoneModal();
                if (typeof closeRoiEditorModal === 'function') closeRoiEditorModal();
                if (typeof closeAssociationEvidenceModal === 'function') closeAssociationEvidenceModal();
                if (typeof closeWorkerBoxEvidenceModal === 'function') closeWorkerBoxEvidenceModal();
                if (typeof closeFullscreen === 'function') closeFullscreen();
            }
        });

        // Initialize camera form state on load
        handleCamTypeChange();

        // THEME SWITCHER LOGIC
        function setTheme(theme) {
            if (theme === 'dark') {
                document.documentElement.setAttribute('data-theme', 'dark');
                try { localStorage.setItem('warlog_theme', 'dark'); } catch(e) {}
            } else {
                document.documentElement.removeAttribute('data-theme');
                try { localStorage.setItem('warlog_theme', 'light'); } catch(e) {}
            }
            updateThemeButtons(theme);
        }

        function updateThemeButtons(theme) {
            document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
                if (btn.getAttribute('data-theme-btn') === theme) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });
        }

        // Sync buttons on initial load
        (function() {
            try {
                const currentTheme = localStorage.getItem('warlog_theme') || 'light';
                updateThemeButtons(currentTheme);
            } catch(e) {}
        })();
    
window.fetchBins = async function() {
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
                <td>
                    <strong>${b.bin_id}</strong>
                    <div style="margin-top:4px;"><button type="button" style="font-size:0.7rem; padding:2px 6px; cursor:pointer;" onclick="window.openInspectBinModal('${b.bin_id}')">Inspect</button></div>
                </td>
                <td><span class="badge" style="background:var(--panel-subtle); color:var(--text-light); padding: 4px 8px; border-radius: 4px;">${b.zone}</span></td>
                <td>
                    <div style="font-size:0.8rem; margin-bottom:4px;">${b.current_volume.toFixed(1)} / ${b.max_volume} mA3</div>
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
                <td><span class="badge ${b.status==='Active'?'badge-success':'badge-warning'}" style="padding: 4px 8px; border-radius: 4px;">${b.status}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch(e) { console.error(e); }
}

window.fetchSkus = async function() {
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
                <td><span class="badge" style="background:var(--panel-subtle); color:var(--text-light); padding: 4px 8px; border-radius: 4px;">${s.category}</span></td>
                <td>${s.unit_volume} m³</td>
                <td>${s.unit_weight} kg</td>
            `;
            tbody.appendChild(tr);
        });
    } catch(e) { console.error(e); }
}


window.openInspectBinModal = async function(binId) {
    document.getElementById('inspectBinIdTitle').innerText = binId;
    document.getElementById('inspectBinModal').style.display = 'flex';
    
    // Fetch Bin details from global list or re-fetch
    try {
        const binRes = await fetch('/api/bins');
        if (binRes.ok) {
            const bins = await binRes.json();
            const bin = bins.find(b => b.bin_id === binId);
            if (bin) {
                document.getElementById('inspectBinZone').innerText = bin.zone;
                document.getElementById('inspectBinVol').innerText = `${bin.current_volume.toFixed(1)} / ${bin.max_volume} mA3`;
                document.getElementById('inspectBinWt').innerText = `${bin.current_weight.toFixed(1)} / ${bin.max_weight} kg`;
                document.getElementById('inspectBinCount').innerText = bin.stock_count;
            }
        }
        
        // Fetch specific inventory for this bin
        const invRes = await fetch(`/api/bins/${binId}/inventory`);
        const tbody = document.getElementById('inspectBinTableBody');
        tbody.innerHTML = '';
        
        if (invRes.ok) {
            const inventory = await invRes.json();
            if (inventory.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Bin is currently empty.</td></tr>';
            } else {
                inventory.forEach(i => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><strong>${i.sku_id}</strong></td>
                        <td>
                            <div>${i.sku_name || 'Unknown'}</div>
                            <div style="font-size:0.75rem; color:var(--text-muted);">${i.category || '-'}</div>
                        </td>
                        <td>${i.vendor || '-'}</td>
                        <td><strong>${i.quantity}</strong></td>
                        <td style="font-size:0.85rem; color:var(--text-muted);">${new Date(i.received_date).toLocaleString()}</td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        } else {
             tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:red;">Failed to load contents.</td></tr>';
        }
    } catch (e) {
        console.error(e);
        document.getElementById('inspectBinTableBody').innerHTML = '<tr><td colspan="5" style="text-align:center; color:red;">Error loading contents.</td></tr>';
    }
}

window.submitAddBin = async function() {
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
        window.fetchBins();
    } catch(e) { console.error(e); }
}


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




window.initDashboardAnalytics = async function() {
    try {
        const bRes = await fetch('/api/bins');
        const bins = await bRes.json();
        
        let zones = {};
        bins.forEach(b => {
            if(!zones[b.zone]) zones[b.zone] = {volUsed: 0, volMax: 0};
            zones[b.zone].volUsed += b.current_volume;
            zones[b.zone].volMax += b.max_volume;
        });
        
        const labels = Object.keys(zones);
        const volUsedData = labels.map(z => zones[z].volUsed);
        const volFreeData = labels.map(z => zones[z].volMax - zones[z].volUsed);
        
        const ctxVol = document.getElementById('chartVolume');
        if(ctxVol && typeof Chart !== 'undefined') {
            new Chart(ctxVol, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Used Volume (m³)', data: volUsedData, backgroundColor: '#3b82f6' },
                        { label: 'Free Volume (m³)', data: volFreeData, backgroundColor: '#334155' }
                    ]
                },
                options: { responsive: true, scales: { x: { stacked: true }, y: { stacked: true } } }
            });
        }
        
        const aRes = await fetch('/api/alerts');
        const alerts = await aRes.json();
        const alertBox = document.getElementById('dashboardAlerts');
        if(alertBox) {
            if(alerts.length === 0) {
                alertBox.innerHTML = '<div style="color:var(--primary-teal);">✅ All systems normal. No alerts.</div>';
            } else {
                alertBox.innerHTML = alerts.map(a => `<div style="margin-bottom:8px; padding:10px; border-left:4px solid ${a.type==='error'?'var(--danger)':'var(--warning)'}; background:rgba(0,0,0,0.2); border-radius:4px;">${a.message}</div>`).join('');
            }
        }
    } catch(e) { console.error(e); }
};

// Auto-run if on dashboard
const origSwitchTab = window.switchTab;
if (origSwitchTab) {
    window.switchTab = function(tabId) {
        origSwitchTab(tabId);
        if(tabId === 'dashboard') {
            setTimeout(() => window.initDashboardAnalytics(), 300);
        }
    };
} else {
    setTimeout(() => window.initDashboardAnalytics(), 1000);
}


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
            if (o.status === 'Fulfilled') actionBtn = '<span style="color:var(--primary-teal); font-weight:bold;">Completed</span>';
            actionBtn += `<button class="btn-primary" style="margin-top:4px; font-size:0.75rem; width:100%; background:var(--accent);" onclick="downloadOutboundManifest('${o.id}')">📄 PDF Manifest</button>`;
            
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


// ==========================================
// MASTER HUB SEARCH
// ==========================================
window.filterMasterHub = function() {
    const input = document.getElementById('masterHubSearch');
    if(!input) return;
    const filter = input.value.toLowerCase();
    
    // The active sub-tab has display != none
    const activeSections = document.querySelectorAll('.sub-master-section');
    let activeSection = null;
    activeSections.forEach(s => {
        if(s.style.display !== 'none') activeSection = s;
    });
    
    if (!activeSection) return;
    
    const tbody = activeSection.querySelector('tbody');
    if (!tbody) return;
    
    const trs = tbody.getElementsByTagName('tr');
    for (let i = 0; i < trs.length; i++) {
        let match = false;
        const tds = trs[i].getElementsByTagName('td');
        for (let j = 0; j < tds.length; j++) {
            if (tds[j].innerText.toLowerCase().includes(filter)) {
                match = true;
                break;
            }
        }
        trs[i].style.display = match ? "" : "none";
    }
}


// ==========================================
// CYCLE COUNTING & AUDIT
// ==========================================
async function runCycleCount(bin_id) {
    const input = document.getElementById(`audit_qty_${bin_id}`);
    const actual_qty = parseInt(input.value);
    if(isNaN(actual_qty)) {
        alert("Enter a valid quantity");
        return;
    }
    try {
        const res = await fetch('/api/cycle_count', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({bin_id: bin_id, actual_qty: actual_qty})
        });
        const data = await res.json();
        if(data.success) {
            alert(data.message);
            fetchMasterHubData();
        } else {
            alert("Error: " + data.message);
        }
    } catch (e) {
        alert("Connection Error");
    }
}

// Modify bin table rendering to include cycle count inputs in the cycle count tab
function renderCycleCountTab(bins, inventory) {
    const tbody = document.getElementById('cycleCountBody');
    if(!tbody) return;
    
    tbody.innerHTML = bins.map(b => {
        const inv = inventory.find(i => i.bin_id === b.bin_id);
        const expected_qty = inv ? inv.quantity : 0;
        const sku_id = inv ? inv.sku_id : 'N/A';
        return `
            <tr>
                <td>${b.bin_id}</td>
                <td>${b.zone}</td>
                <td>${sku_id}</td>
                <td>${expected_qty}</td>
                <td>
                    <div style="display:flex; gap:10px;">
                        <input type="number" id="audit_qty_${b.bin_id}" placeholder="Actual Qty" style="width:100px; padding:4px; margin:0;" value="${expected_qty}">
                        <button class="btn-primary" onclick="runCycleCount('${b.bin_id}')">Audit</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}
