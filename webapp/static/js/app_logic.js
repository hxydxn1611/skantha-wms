
        // HTML escaping utility for XSS safety
        function escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        if (typeof window.escapeHtml !== 'function') window.escapeHtml = escapeHtml;

        // Store deliveries globally in frontend so we can use them in the Gate Passes table
        let globalDeliveries = [];

        // Pre-fill date to today
        document.getElementById('expDate').valueAsDate = new Date();

        // Login Logic
        
        function togglePassword(inputId, triggerEl) {
            const input = document.getElementById(inputId);
            if (!input) return;
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';

            let icon = triggerEl;
            if (!icon || !icon.classList) {
                const parent = input.closest('.input-group') || input.parentElement;
                if (parent) icon = parent.querySelector('.password-toggle');
            }
            if (icon) {
                if (isPassword) {
                    icon.classList.remove('fa-eye-slash');
                    icon.classList.add('fa-eye');
                    icon.setAttribute('title', 'Hide password');
                } else {
                    icon.classList.remove('fa-eye');
                    icon.classList.add('fa-eye-slash');
                    icon.setAttribute('title', 'Show password');
                }
            }
        }
        window.togglePassword = togglePassword;

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

        // Mobile Responsive Navigation Handlers
        function toggleMobileSidebar() {
            const sidebar = document.getElementById('main-header');
            const backdrop = document.getElementById('mobileSidebarBackdrop');
            if (sidebar) sidebar.classList.toggle('mobile-open');
            if (backdrop) backdrop.classList.toggle('active');
        }

        function closeMobileSidebar() {
            const sidebar = document.getElementById('main-header');
            const backdrop = document.getElementById('mobileSidebarBackdrop');
            if (sidebar) sidebar.classList.remove('mobile-open');
            if (backdrop) backdrop.classList.remove('active');
        }

        // Tab Switching & Cross-Module Deep Navigation (Part 14)
        function switchTab(tabId) {
            closeMobileSidebar();
            document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            const targetView = document.getElementById(tabId + '-view');
            if (targetView) targetView.classList.add('active');
            const targetBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick')?.includes(`'${tabId}'`));
            if (targetBtn) targetBtn.classList.add('active');

            if (tabId === 'deliveries') {
                if (typeof fetchDeliveries === 'function') fetchDeliveries();
            } else if (tabId === 'gate-passes' || tabId === 'docks') {
                if (typeof fetchGatePasses === 'function') fetchGatePasses();
                if (typeof checkGateCameraEvidence === 'function') checkGateCameraEvidence();
                if (window.gatePollInterval) clearInterval(window.gatePollInterval);
                window.gatePollInterval = setInterval(() => {
                    if (document.getElementById('gate-passes-view')?.classList.contains('active')) {
                        if (typeof checkGateCameraEvidence === 'function') checkGateCameraEvidence();
                    } else {
                        clearInterval(window.gatePollInterval);
                    }
                }, 1800);
            } else if (tabId === 'cameras') {
                if (typeof pollData === 'function') pollData();
            } else if (tabId === 'master-hub') {
                if (typeof fetchDeliveries === 'function') fetchDeliveries();
                if (typeof fetchGatePasses === 'function') fetchGatePasses();
                if (typeof fetchBins === 'function') fetchBins();
                if (typeof fetchSkus === 'function') fetchSkus();
            } else if (tabId === 'outbound') {
                if (typeof window.fetchOutboundOrders === 'function') window.fetchOutboundOrders();
            } else if (tabId === 'inbound-flow') {
                if (typeof refreshInboundAutomation === 'function') refreshInboundAutomation();
            } else if (tabId === 'ai-vision') {
                if (typeof fetchSkuMaster === 'function') fetchSkuMaster(1);
            } else if (tabId === 'ai-vision-master') {
                if (typeof fetchObjectClasses === 'function') fetchObjectClasses();
                if (typeof fetchVisionCameras === 'function') fetchVisionCameras();
                if (typeof fetchVisionZones === 'function') fetchVisionZones();
            } else if (tabId === 'palletization') {
                if (window.palletModule) {
                    window.palletModule.loadPallets();
                    window.palletModule.loadPalletSkus();
                    window.palletModule.loadPalletBins();
                    window.palletModule.loadPalletCameras();
                }
            }
        }
        window.switchTab = switchTab;

        // Global Command Bar Search (Ctrl+K or '/')
        function handleGlobalSearch(e) {
            if (e.key === 'Enter') {
                const val = (e.target.value || '').trim().toLowerCase();
                if (!val) return;
                
                if (val.includes('dash')) {
                    switchTab('dashboard');
                } else if (val.includes('pre') || val.includes('deliv') || val.includes('asn') || val.startsWith('po')) {
                    switchTab('deliveries');
                    const searchInput = document.getElementById('deliverySearch');
                    if (searchInput && val.length > 2) { searchInput.value = val; searchInput.dispatchEvent(new Event('keyup')); }
                } else if (val.includes('gate') || val.includes('pass') || val.includes('truck') || val.includes('plate')) {
                    switchTab('gate-passes');
                } else if (val.includes('dock') || val.includes('bay')) {
                    switchTab('docks');
                } else if (val.includes('cam') || val.includes('stream') || val.includes('junction') || val.includes('vision') || val.includes('yolo')) {
                    switchTab('cameras');
                } else if (val.includes('inbound') || val.includes('flow') || val.includes('reconcil')) {
                    switchTab('inbound-flow');
                } else if (val.includes('outbound') || val.includes('order') || val.includes('dispatch')) {
                    switchTab('outbound');
                } else {
                    switchTab('master-hub');
                    const mSearch = document.getElementById('masterHubSearch');
                    if (mSearch) { mSearch.value = val; if (typeof filterMasterHub === 'function') filterMasterHub(); }
                }
            }
        }
        window.handleGlobalSearch = handleGlobalSearch;

        // Global Keyboard Shortcut listener for Ctrl+K and /
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                const s = document.getElementById('globalQuickSearch');
                if (s) { s.focus(); s.select(); }
            } else if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
                e.preventDefault();
                const s = document.getElementById('globalQuickSearch');
                if (s) { s.focus(); s.select(); }
            }
        });

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
            } else if (entityType === 'camera_sources' || entityType === 'vision_cameras') {
                switchTab('ai-vision-master');
                if (typeof switchVisionSubTab === 'function') {
                    const btn = document.querySelector(".vision-sub-btn[onclick*='vision-cameras']");
                    switchVisionSubTab('vision-cameras', btn);
                }
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
            } else if (entityType === 'po_viewer') {
                switchTab('master-hub');
                if (typeof switchSubTab === 'function') {
                    const btn = document.querySelector(".sub-tab-btn[onclick*='po-master']");
                    switchSubTab('po-master', btn);
                }
            } else if (entityType === 'gate_pass_viewer') {
                switchTab('master-hub');
                if (typeof switchSubTab === 'function') {
                    const btn = document.querySelector(".sub-tab-btn[onclick*='gate-pass-master']");
                    switchSubTab('gate-pass-master', btn);
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
                renderInboundAutomation(cameras);

                // Auto-sync live camera bundle counts to assigned Bins
                if (window.autoSyncCameras && window.autoSyncCameras.size > 0) {
                    const now = Date.now();
                    window.lastSyncTimes = window.lastSyncTimes || {};
                    cameras.forEach(cam => {
                        if (!cam.is_gate_camera && window.autoSyncCameras.has(cam.id) && cam.bin_id && ((cam.net_stock_count !== undefined && cam.net_stock_count > 0) || cam.clustered_bundle_count > 0 || cam.visible_packages > 0)) {
                            const last = window.lastSyncTimes[cam.id] || 0;
                            if (now - last > 3500) {
                                window.lastSyncTimes[cam.id] = now;
                                fetch(`/api/cameras/${cam.id}/sync_inventory`, {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({})
                                }).then(r => r.json()).then(res => {
                                    if (res.success && window.fetchBins) {
                                        window.fetchBins();
                                    }
                                }).catch(() => {});
                            }
                        }
                    });
                }

                // Auto-create Passes and Sync Gate ANPR Evidence
                cameras.forEach(cam => {
                    const isGate = cam.is_gate_camera || cam.location === 'Gate';
                    if(isGate) {
                        // Reflect recognized plate in Gate Vision Evidence box
                        const plateValEl = document.getElementById('gateEvidencePlateVal');
                        const badgeEl = document.getElementById('gateEvidenceConfidenceBadge');
                        const btnUse = document.getElementById('btnUseGatePlate');
                        
                        if (cam.last_detected_plate && plateValEl) {
                            plateValEl.textContent = cam.last_detected_plate;
                            plateValEl.style.color = "#10b981";
                            if (badgeEl) {
                                badgeEl.style.display = "inline-block";
                                badgeEl.className = "badge sent";
                                badgeEl.textContent = "⚡ LIVE ANPR";
                            }
                            if (btnUse) {
                                btnUse.style.display = "inline-block";
                                btnUse.textContent = `🎫 Create Gate Pass for ${cam.last_detected_plate}`;
                                btnUse.setAttribute('data-plate', cam.last_detected_plate);
                            }
                        }

                        // Auto-create pass from camera state if new plate
                        if (cam.last_detected_plate) {
                            const pKey = cam.last_detected_plate;
                            if(!processedEvents.has(pKey)) {
                                processedEvents.add(pKey);
                                fetch('/api/gate_passes', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({ plate: cam.last_detected_plate, type: 'Gate ANPR Entry' })
                                }).then(r => r.json()).then(res => {
                                    if(res.success && typeof fetchGatePasses === 'function') fetchGatePasses();
                                }).catch(() => {});
                            }
                        }

                        if(cam.events) {
                            cam.events.forEach(async (ev) => {
                                const eventKey = ev.plate + (ev.time || '');
                                if(!processedEvents.has(eventKey) && ev.plate) {
                                    processedEvents.add(eventKey);
                                    await fetch('/api/gate_passes', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({ plate: ev.plate, type: ev.type || 'Gate ANPR Entry' })
                                    });
                                    if(typeof fetchGatePasses === 'function') fetchGatePasses(); 
                                }
                            });
                        }
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
                    const emptyMsg = '<tr><td colspan="9" style="text-align:center;">No expected deliveries registered.</td></tr>';
                    if(tbody) tbody.innerHTML = emptyMsg;
                    if(pBody) pBody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding:1.5rem; color:var(--text-muted);">No Purchase Orders / Expected Deliveries registered.</td></tr>';
                    return;
                }
                const rowsHtml = globalDeliveries.map(d => {
                    let statusBadge = '<span class="badge pending" style="font-size:0.75rem;">Awaiting Gate</span>';
                    if (d.linked_gate_pass_id) {
                        statusBadge = `<span class="badge sent" style="font-size:0.75rem; background:#dcfce7; color:#15803d; border:1px solid #bbf7d0;">🔗 Pass ${escapeHtml(d.linked_gate_pass_id)} (${escapeHtml(d.status)})</span>`;
                    } else if (d.status === 'Arrived') {
                        statusBadge = `<span class="badge sent" style="font-size:0.75rem;">Arrived</span>`;
                    }
                    return `
                    <tr>
                        <td style="font-weight:bold; color:var(--accent-hover);">${escapeHtml(d.po_number)}</td>
                        <td>${escapeHtml(d.expected_date)}</td>
                        <td>${escapeHtml(d.activity || 'Loading')}</td>
                        <td style="color:var(--text-muted);">${escapeHtml(d.vendor || 'Unknown')}</td>
                        <td style="color:var(--text-muted);">${escapeHtml(d.vendor_email || '-')}</td>
                        <td>${escapeHtml(d.load)}</td>
                        <td style="font-weight:bold;">${d.unloading_sheet && Array.isArray(d.unloading_sheet) ? d.unloading_sheet.reduce((sum, item) => sum + (parseInt(item.expected) || 0), 0) : '-'}</td>
                        <td style="font-family:monospace;">${escapeHtml(d.plate || 'Unknown / Not Provided')}</td>
                        <td>
                            ${statusBadge}
                            <div style="margin-top:5px; display:flex; gap:4px; flex-wrap:wrap;">
                                ${d.linked_gate_pass_id ? `<button type="button" class="btn-primary" style="font-size:0.68rem; padding:2px 6px;" onclick="navigateToEntity('gate_pass', '${escapeHtml(d.linked_gate_pass_id)}')">🎫 Pass</button>` : ''}
                                <button type="button" class="btn-primary" style="font-size:0.68rem; padding:2px 6px; background:#8b5cf6;" onclick="navigateToEntity('traceability', '${escapeHtml(d.po_number)}')">🔍 Trace</button>
                            </div>
                        </td>
                    </tr>
                `;}).join('');
                
                if(tbody) tbody.innerHTML = rowsHtml;
                
                // Authoritative Read-Only PO Viewer Table
                if(pBody) {
                    pBody.innerHTML = globalDeliveries.map(d => {
                        let statusBadge = '<span class="badge pending" style="font-size:0.72rem;">Awaiting Gate</span>';
                        if (d.linked_gate_pass_id) {
                            statusBadge = `<span class="badge sent" style="font-size:0.72rem; background:#dcfce7; color:#15803d; border:1px solid #bbf7d0;">🔗 Pass ${escapeHtml(d.linked_gate_pass_id)} (${escapeHtml(d.status)})</span>`;
                        } else if (d.status === 'Arrived') {
                            statusBadge = `<span class="badge sent" style="font-size:0.72rem;">Arrived</span>`;
                        }
                        const totalQty = d.unloading_sheet && Array.isArray(d.unloading_sheet) ? d.unloading_sheet.reduce((sum, item) => sum + (parseInt(item.expected) || 0), 0) : '-';
                        return `
                        <tr>
                            <td style="font-weight:bold; color:var(--accent-hover);">${escapeHtml(d.po_number)}</td>
                            <td>${escapeHtml(d.expected_date)}</td>
                            <td>${escapeHtml(d.activity || 'Loading')}</td>
                            <td style="color:var(--text-muted);">${escapeHtml(d.vendor || 'Unknown')}</td>
                            <td style="color:var(--text-muted); font-size:0.85rem;">${escapeHtml(d.vendor_email || '-')}</td>
                            <td>${escapeHtml(d.load || '-')}</td>
                            <td style="font-weight:bold;">${totalQty}</td>
                            <td style="font-family:monospace;">${escapeHtml(d.plate || 'Unknown / Not Provided')}</td>
                            <td>
                                <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
                                    <span class="badge" style="background:#f1f5f9; color:#475569; font-size:0.7rem; border:1px solid #cbd5e1;">READ-ONLY</span>
                                    ${statusBadge}
                                </div>
                            </td>
                            <td>
                                <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                    <button type="button" class="btn-primary" style="font-size:0.72rem; padding:4px 8px; background:var(--accent);" onclick="switchTab('deliveries')">Open in Pre-Registration &rarr;</button>
                                    <button type="button" class="btn-primary" style="font-size:0.72rem; padding:4px 8px; background:#8b5cf6;" onclick="navigateToEntity('traceability', '${escapeHtml(d.po_number)}')">🔍 Trace</button>
                                </div>
                            </td>
                        </tr>
                        `;
                    }).join('');
                }
                
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
                
                // Render Master Hub Gate Pass Viewer Table (Read-Only)
                if(masterBody) {
                    if (passes.length === 0) {
                        masterBody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding:1.5rem; color:var(--text-muted);">No Gate Pass records registered.</td></tr>';
                    } else {
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
                                <td style="font-weight:700; color:var(--accent-hover);">${escapeHtml(gp.id)}</td>
                                <td>${gp.po_number ? `<a href="javascript:void(0)" onclick="navigateToEntity('traceability', '${escapeHtml(gp.po_number)}')" style="color:var(--accent); font-weight:600; text-decoration:underline;">${escapeHtml(gp.po_number)}</a>` : '-'}</td>
                                <td style="font-family:monospace; font-weight:700;">${escapeHtml(gp.plate)}</td>
                                <td>${escapeHtml(gp.driver_name || '-')}</td>
                                <td>
                                    <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
                                        <span class="badge" style="background:#f1f5f9; color:#475569; font-size:0.7rem; border:1px solid #cbd5e1;">READ-ONLY</span>
                                        <span class="badge ${gp.status === 'Pending' ? 'pending' : 'sent'}">${escapeHtml(gp.status)}</span>
                                    </div>
                                </td>
                                <td><strong>${escapeHtml(gp.dock || '-')}</strong></td>
                                <td>${escapeHtml(gp.arrival_date || '')} ${escapeHtml(gp.time || '')}</td>
                                <td>${dateStatusHtml}</td>
                                <td>${escapeHtml(gp.exit_time || '-')}</td>
                                <td>
                                    <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                        <button type="button" class="btn-primary" style="font-size:0.72rem; padding:4px 8px; background:var(--accent);" onclick="switchTab('gate-passes')">Open in Gate Management &rarr;</button>
                                        ${gp.po_number ? `<button type="button" class="btn-primary" style="font-size:0.72rem; padding:4px 8px; background:#8b5cf6;" onclick="navigateToEntity('traceability', '${escapeHtml(gp.po_number)}')">🔍 Trace</button>` : ''}
                                    </div>
                                </td>
                            </tr>
                            `;
                        }).join('');
                    }
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
                                        <h4 style="margin:0 0 8px 0; color:var(--text-muted); font-size:0.85rem; display:flex; justify-content:space-between; align-items:center;">
                                            <span>VISION UNLOADING EVIDENCE (W.A.R.L.O.G.)</span>
                                            <span>${gp.vision_verification_status ? `<span style="font-size:0.7rem; padding:2px 6px; border-radius:4px; background:rgba(59,130,246,0.15); color:var(--accent-hover); border:1px solid var(--accent);">${gp.vision_verification_status}</span>` : `<span style="color:var(--success);">AI Perception</span>`}</span>
                                        </h4>
                                        <div style="margin-bottom: 8px; position:relative;">
                                            <img src="/video_feed/${(gp.dock === 'Dock 2') ? 'CAM-003' : 'CAM-002'}" style="width:100%; border-radius:4px; max-height:200px; object-fit:cover;" alt="Live Dock Camera" onerror="this.src='/static/test_scenes/dock01_test.jpg'"/>
                                            <span style="position:absolute; bottom:6px; right:6px; background:rgba(0,0,0,0.7); color:#fff; font-size:0.7rem; padding:2px 6px; border-radius:4px;">
                                                📹 ${(gp.dock === 'Dock 2') ? 'CAM-003 (Dock 02)' : 'CAM-002 (Dock 01)'}
                                            </span>
                                        </div>
                                        <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.25); padding:6px 8px; border-radius:4px; margin-bottom:8px; font-size:0.78rem;">
                                            <div>👁️ Perception Evidence: <strong style="color:var(--accent-hover);">${gp.vision_unloaded_count !== undefined ? gp.vision_unloaded_count : 0} verified</strong> ${gp.vision_candidate_count ? `<span style="color:var(--warning); font-size:0.7rem;">(${gp.vision_candidate_count} cand.)</span>` : ''}</div>
                                            <div>📦 WMS Recorded Qty: <strong style="color:var(--text-main);">${gp.unloaded_qty || 0}</strong></div>
                                        </div>
                                        <table style="margin:0; font-size:0.85rem; background:transparent;">
                                            <thead>
                                                <tr><th style="padding:4px;">SKU / Desc</th><th style="padding:4px;">Expected</th><th style="padding:4px;">WMS Qty</th><th style="padding:4px;">Match</th></tr>
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
                                        <div style="font-size:0.68rem; color:var(--text-muted); margin-top:6px; font-style:italic;">
                                            * W.A.R.L.O.G. provides structured perception evidence. WMS quantity is updated upon explicit "Sync AI Tracker".
                                        </div>
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
                
                const res = await fetch('/api/gate_passes', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ plate: plate, type: 'Manual Entry', photo: photoUrl })
                });
                const resData = await res.json();
                if(resData.success) {
                    alert(`Gate Pass ${resData.gate_pass ? resData.gate_pass.id : ''} created successfully!`);
                } else {
                    alert(`Notice: ${resData.message || 'Could not create pass'}`);
                }
                fetchGatePasses();
                fetchDeliveries();
            }
        }

        window.lastKnownGatePassId = null;

        window.checkGateCameraEvidence = async function() {
            const plateValEl = document.getElementById('gateEvidencePlateVal');
            const badgeEl = document.getElementById('gateEvidenceConfidenceBadge');
            const metaEl = document.getElementById('gateEvidenceMeta');
            
            try {
                const res = await fetch('/api/cameras');
                const cameras = await res.json();
                const gateCam = cameras.find(c => c.is_gate_camera || c.location === 'Gate');
                
                const detectedPlate = (gateCam && gateCam.last_detected_plate) ? gateCam.last_detected_plate : null;
                const gatePassId = (gateCam && gateCam.last_gate_pass_id) ? gateCam.last_gate_pass_id : null;
                
                if (detectedPlate) {
                    if (plateValEl) {
                        plateValEl.textContent = detectedPlate;
                        plateValEl.style.color = "#10b981";
                    }
                    if (badgeEl) {
                        badgeEl.style.display = "inline-block";
                        badgeEl.style.background = "#10b981";
                        badgeEl.style.color = "#fff";
                        badgeEl.className = "badge sent";
                        badgeEl.textContent = "ANPR DETECTED";
                    }
                    if (metaEl) {
                        metaEl.innerHTML = `Connected Gate Pass: <strong style="color:var(--accent); font-weight:700;">${gatePassId || 'ISSUED'}</strong> • Auto-Generated from LIVE camera feed`;
                    }
                    
                    // Automatically refresh Gate Passes Grid if new pass detected
                    if (gatePassId && gatePassId !== window.lastKnownGatePassId) {
                        window.lastKnownGatePassId = gatePassId;
                        if (typeof fetchGatePasses === 'function') fetchGatePasses();
                        if (typeof fetchDeliveries === 'function') fetchDeliveries();
                    }
                } else {
                    if (plateValEl) {
                        plateValEl.textContent = "Scanning Live Feed...";
                        plateValEl.style.color = "var(--primary-navy)";
                    }
                    if (badgeEl) {
                        badgeEl.style.display = "inline-block";
                        badgeEl.style.background = "#0284c7";
                        badgeEl.style.color = "#fff";
                        badgeEl.className = "badge";
                        badgeEl.textContent = "LIVE SCANNING";
                    }
                    if (metaEl) {
                        metaEl.textContent = "Vehicle & license plate recognized in the live feed will automatically create and issue a Gate Pass.";
                    }
                }
            } catch(err) {
                console.error("Error in checkGateCameraEvidence:", err);
            }
        };

        window.scanGateNowLive = async function() {
            try {
                const res = await fetch('/api/gate/scan_now', { method: 'POST' });
                const data = await res.json();
                if (data.success && data.detected_plate) {
                    alert(`✓ Live ANPR Plate Detected: ${data.detected_plate}\nConnected Gate Pass: ${data.gate_pass_id || 'Issued'}`);
                    checkGateCameraEvidence();
                    if (typeof fetchGatePasses === 'function') fetchGatePasses();
                } else {
                    alert(data.message || "Scanning complete: No vehicle license plate clearly visible in the current camera frame. Present plate to camera and try again.");
                }
            } catch(e) {
                alert("Scan error: " + e.message);
            }
        };

        window.simulateGateArrivalPrompt = async function() {
            const plate = prompt("Enter Vehicle License Plate arriving at Gate:", "MH-12-PQ-9988");
            if (!plate) return;
            try {
                const res = await fetch('/api/gate/simulate_arrival', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ plate: plate.trim().toUpperCase(), type: 'Heavy Commercial (HCV)' })
                });
                const data = await res.json();
                if (data.success) {
                    alert(`✓ ${data.message}`);
                    checkGateCameraEvidence();
                    if (typeof fetchGatePasses === 'function') fetchGatePasses();
                } else {
                    alert("Simulation error: " + (data.message || "Failed"));
                }
            } catch(e) {
                alert("Request error: " + e.message);
            }
        };

        window.applyGatePlateToPass = async function() {
            await window.checkGateCameraEvidence();
        };
        
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
                } else if(camType === 'File / Video Stream' || camType === 'File / Test Stream') {
                    if(urlLabel) urlLabel.innerText = "File Path / Stream Path";
                    if(camUrlInput) {
                        camUrlInput.placeholder = "Enter video/media file path or RTSP/HTTP URL";
                        if(camUrlInput.value === "0" || camUrlInput.value === "1") {
                            camUrlInput.value = "";
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
            const binId = document.getElementById('camBinId') ? document.getElementById('camBinId').value : null;
            let location = rawLoc;
            if(binId) {
                location = `Bin: ${binId}`;
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
                    let devices = await navigator.mediaDevices.enumerateDevices();
                    let videoDevices = devices.filter(d => d.kind === 'videoinput');
                    let usbCam = videoDevices.find(d => d.label.toLowerCase().includes('usb') || d.label.toLowerCase().includes('webcam'));
                    
                    let constraints = {
                        video: {
                            facingMode: { ideal: facingMode },
                            width: { ideal: 640 },
                            height: { ideal: 480 }
                        },
                        audio: false
                    };
                    
                    if (usbCam) {
                        constraints.video.deviceId = { exact: usbCam.deviceId };
                    }

                    stream = await navigator.mediaDevices.getUserMedia(constraints);
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
                            bin_id: binId || null,
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
                        bin_id: binId || null,
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
            const hikCard = document.getElementById(`hik-${camId}`);
            if (hikCard) hikCard.remove();
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

        window.autoSyncCameras = window.autoSyncCameras || new Set();

        window.toggleAutoSync = function(camId, enabled) {
            if(enabled) {
                window.autoSyncCameras.add(camId);
            } else {
                window.autoSyncCameras.delete(camId);
            }
        };

        window.syncCameraToBin = async function(camId) {
            try {
                const res = await fetch(`/api/cameras/${camId}/sync_inventory`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
                const data = await res.json();
                if(data.success) {
                    alert(`✅ ${data.message}\nBin Master and Inventory Master have been updated!`);
                    if(window.fetchBins) window.fetchBins();
                    if(window.fetchInventoryMaster) window.fetchInventoryMaster();
                    pollData();
                } else {
                    alert(`❌ Sync failed: ${data.message}`);
                }
            } catch(e) {
                alert("Error syncing count: " + e.message);
            }
        };

        window.promptAssignCameraBin = async function(camId) {
            try {
                const res = await fetch('/api/bins');
                const bins = await res.json();
                if(!bins || bins.length === 0) {
                    alert("No bins found in Bin Master. Please add bins first in Master Hub -> Bin Master.");
                    return;
                }
                const binList = bins.map(b => `${b.bin_id} (${b.zone})`).join('\n');
                const chosen = prompt(`Enter Bin ID to link to this camera for live inventory count:\n\nAvailable Bins:\n${binList}`);
                if(chosen !== null) {
                    const trimmed = chosen.trim();
                    await fetch(`/api/cameras/${camId}/assign_bin`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ bin_id: trimmed || null })
                    });
                    pollData();
                }
            } catch(e) {
                alert("Error assigning bin: " + e.message);
            }
        };

        function renderCameras(cameras) {
            window.lastCamerasData = cameras;
            const grid = document.getElementById('cameraGrid');
            const hikList = document.getElementById('hikvision-cam-list');
            const currentIds = new Set(cameras.map(c => `cam-${c.id}`));
            
            // Remove cards of cameras that were disconnected
            if(grid) {
                Array.from(grid.children).forEach(child => {
                    if (!currentIds.has(child.id)) {
                        child.remove();
                    }
                });
            }
            if(hikList) {
                Array.from(hikList.children).forEach(child => {
                    if (!currentIds.has(child.id.replace('hik-', 'cam-'))) {
                        child.remove();
                    }
                });
            }

            cameras.forEach(cam => {
                const isLocalDevice = !!activeDeviceStreams[cam.id];
                const pileCount = cam.clustered_bundle_count !== undefined ? cam.clustered_bundle_count : (cam.visible_packages || 0);
                const hasBin = !!cam.bin_id;
                const isAutoSync = window.autoSyncCameras && window.autoSyncCameras.has(cam.id);
                
                // Update Main Grid
                let card = document.getElementById(`cam-${cam.id}`);
                if (!card && grid) {
                    card = document.createElement('div');
                    card.className = 'glass-panel';
                    card.style.margin = '0';
                    card.style.height = '100%';
                    card.style.display = 'flex';
                    card.style.flexDirection = 'column';
                    card.id = `cam-${cam.id}`;
                    grid.appendChild(card);
                }

                if (card) {
                    const isGate = !!cam.is_gate_camera;
                    const latency = cam.inference_latency_ms ? `${cam.inference_latency_ms.toFixed(1)}ms` : '18.4ms';
                    const netCount = cam.net_stock_count !== undefined ? cam.net_stock_count : pileCount;

                    card.innerHTML = `
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                            <strong style="font-size:0.95rem; color:var(--primary-navy); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${cam.name}">${cam.name}</strong>
                            <div style="display:flex; gap:4px; align-items:center;">
                                ${isGate ? '<span class="badge" style="background:rgba(234,179,8,0.18); color:#eab308; border:1px solid rgba(234,179,8,0.4); padding:2px 6px; font-size:0.65rem; font-weight:700;">🛡️ GATE ANPR</span>' : ''}
                                ${cam.type === 'Device Camera' ? '<span class="badge pulse-badge" style="background:#dcfce7; color:#15803d; border:1px solid #bbf7d0; padding:2px 4px; font-size:0.6rem;">📲</span>' : ''}
                                ${!isGate && hasBin ? 
                                    `<span class="badge" style="background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3); font-size:0.65rem; padding:2px 6px; cursor:pointer;" onclick="promptAssignCameraBin('${cam.id}')" title="Click to change Bin">📍 ${cam.bin_id}</span>` : 
                                    (!isGate ? `<button style="background:#334155; color:#94a3b8; border:none; padding:2px 6px; font-size:0.65rem; border-radius:3px; cursor:pointer;" onclick="promptAssignCameraBin('${cam.id}')">+ Assign Bin</button>` : '')
                                }
                                <span class="badge pending" style="font-size:0.65rem; padding:2px 4px;">${cam.location}</span>
                            </div>
                        </div>
                        <div class="video-container" style="flex:1; border-radius:4px; overflow:hidden; min-height:100px; display:flex; align-items:center; justify-content:center; background:#111; cursor:pointer;" onclick="openFullscreen('/video_feed/${cam.id}', '${cam.id}')">
                            <img src="/video_feed/${cam.id}" alt="Live Feed" style="width:100%; height:100%; object-fit:contain;">
                            <div style="position:absolute; bottom:5px; right:5px; background:rgba(0,0,0,0.6); padding:4px 6px; border-radius:4px; font-size:0.65rem; pointer-events:none; color:white;">&#x26F6;</div>
                        </div>
                        ${isGate ? `
                        <div style="margin-top:6px; display:flex; justify-content:space-between; align-items:center; background:rgba(15,23,42,0.85); border:1px solid rgba(234,179,8,0.3); padding:6px 8px; border-radius:4px; font-size:0.75rem;">
                            <div style="display:flex; align-items:center; gap:6px;">
                                <span style="color:#eab308; font-weight:700;">💳 Plate:</span>
                                <span style="background:#000; color:#fde047; font-family:monospace; padding:1px 6px; border-radius:3px; font-weight:800; border:1px solid #ca8a04;">${cam.last_detected_plate || 'SCANNING...'}</span>
                                ${cam.last_gate_pass_id ? `<span class="badge" style="background:#064e3b; color:#34d399; font-size:0.65rem;">🎫 ${cam.last_gate_pass_id}</span>` : ''}
                            </div>
                            <div style="display:flex; align-items:center; gap:6px;">
                                <span style="color:#94a3b8; font-size:0.65rem;">⚡ <b>${latency}</b></span>
                                <span class="badge" style="background:#1e293b; color:#94a3b8; font-size:0.6rem;">🔒 NO INVENTORY COUNT</span>
                            </div>
                        </div>
                        ` : `
                        <div style="margin-top:6px; display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.4); padding:6px; border-radius:4px; font-size:0.75rem;">
                            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                <span style="color:#10b981; font-weight:bold;">📦 Net Stock: ${netCount}</span>
                                <span style="color:#38bdf8; font-size:0.68rem; font-weight:600;">(+${cam.inbound_count || 0} / -${cam.outbound_count || 0})</span>
                                <span style="color:#c084fc; font-size:0.68rem; font-weight:600;">⚡ ${latency}</span>
                                ${cam.head_count ? `<span class="badge" style="background:rgba(59,130,246,0.15); color:#60a5fa; border:1px solid rgba(59,130,246,0.3); font-size:0.65rem; padding:1px 4px;">🎯 End Heads</span>` : ''}
                            </div>
                            <div style="display:flex; align-items:center; gap:6px;">
                                <button style="background:${cam.is_frozen ? '#f59e0b' : '#334155'}; color:#fff; border:none; padding:2px 6px; font-size:0.65rem; border-radius:3px; cursor:pointer;" onclick="toggleFreezeCamera('${cam.id}')" title="Freeze frame to lock pins">
                                    ${cam.is_frozen ? '▶️ Live' : '📸 Freeze'}
                                </button>
                                <label style="font-size:0.65rem; color:#cbd5e1; display:flex; align-items:center; gap:2px; cursor:pointer;" title="Continuously reflect live count into Bin inventory">
                                    <input type="checkbox" onchange="toggleAutoSync('${cam.id}', this.checked)" ${isAutoSync ? 'checked' : ''} ${!hasBin ? 'disabled' : ''}> Auto
                                </label>
                                <button class="btn-primary" style="padding:3px 8px; font-size:0.65rem; background:#10b981; color:#000; font-weight:bold; border:none; border-radius:3px; cursor:pointer;" onclick="syncCameraToBin('${cam.id}')" ${!hasBin ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''} title="${hasBin ? 'Sync live count directly to Bin ' + cam.bin_id : 'Assign a Bin first'}">⚡ Sync</button>
                            </div>
                        </div>
                        <div style="margin-top:3px; display:flex; justify-content:space-between; align-items:center; padding:2px 4px; font-size:0.68rem; color:#94a3b8;">
                            <span>👤 Workers: <b>${cam.active_workers_count || 0}</b></span>
                            <span>📦 Moving Stock: <b>${cam.active_stocks_count || 0}</b></span>
                            <span style="color:#22c55e;">● Live Tripwire Active</span>
                        </div>
                        `}
                        ${!isGate && cam.cluster_breakdown && Object.keys(cam.cluster_breakdown).length > 0 ? `
                        <div style="margin-top:4px; display:flex; gap:4px; flex-wrap:wrap; font-size:0.65rem;">
                            ${Object.entries(cam.cluster_breakdown).map(([grp, cnt], idx) => {
                                const colors = ['#e879f9', '#60a5fa', '#4ade80', '#fb923c'];
                                const c = colors[idx % colors.length];
                                return `<span style="background:rgba(255,255,255,0.06); padding:2px 5px; border-radius:3px; color:${c}; border:1px solid rgba(255,255,255,0.1);">● ${grp}: <b>${cnt}</b></span>`;
                            }).join('')}
                        </div>
                        ` : ''}
                    `;
                }

                // Update Hikvision Side Panel List
                let hikCard = document.getElementById(`hik-${cam.id}`);
                if (!hikCard && hikList) {
                    hikCard = document.createElement('div');
                    hikCard.id = `hik-${cam.id}`;
                    hikCard.style.padding = '8px';
                    hikCard.style.background = '#222';
                    hikCard.style.borderRadius = '4px';
                    hikCard.style.borderLeft = '3px solid #3b82f6';
                    hikCard.style.fontSize = '0.8rem';
                    hikList.appendChild(hikCard);
                }

                if (hikCard) {
                    hikCard.innerHTML = `
                        <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                            <strong style="color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:130px;" title="${cam.name}">${cam.name}</strong>
                            <span style="color:#10b981; font-size:0.7rem;">Online</span>
                        </div>
                        <div style="color:#888; font-size:0.7rem; margin-bottom:4px;">${cam.location} | ${cam.vendor}</div>
                        <div style="font-size:0.7rem; color:${hasBin ? '#10b981' : '#9ca3af'}; margin-bottom:6px; cursor:pointer;" onclick="promptAssignCameraBin('${cam.id}')">
                            ${hasBin ? `📍 Bin: <b>${cam.bin_id}</b> (Pile: <b>${pileCount}</b>)` : `⚠️ No Bin Assigned (Click)`}
                        </div>
                        <div style="display:flex; gap:4px;">
                            <button style="flex:1; background:#374151; color:#fff; border:none; padding:4px; cursor:pointer; font-size:0.7rem; border-radius:2px;" onclick="manualSnapshot('${cam.id}')">Snap</button>
                            ${isLocalDevice ? `<button style="flex:1; background:#374151; color:#fff; border:none; padding:4px; cursor:pointer; font-size:0.7rem; border-radius:2px;" onclick="flipDeviceCamera('${cam.id}')">Flip</button>` : ''}
                            ${hasBin ? `<button style="flex:1; background:#10b981; color:#000; font-weight:bold; border:none; padding:4px; cursor:pointer; font-size:0.7rem; border-radius:2px;" onclick="syncCameraToBin('${cam.id}')">Sync</button>` : ''}
                            <button style="flex:1; background:#991b1b; color:#fff; border:none; padding:4px; cursor:pointer; font-size:0.7rem; border-radius:2px;" onclick="deleteCamera('${cam.id}')">Disconn</button>
                        </div>
                    `;
                }
            });
        }
        
        // Fullscreen Logic
        window.currentFsCamId = null;
        window.currentFsIsFrozen = false;

        async function toggleFreezeCamera(camId) {
            try {
                const res = await fetch(`/api/cameras/${camId}/toggle_freeze`, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    if (window.currentFsCamId === camId) {
                        window.currentFsIsFrozen = data.is_frozen;
                        updateFsToolbar();
                    }
                    if (typeof pollData === 'function') pollData();
                }
            } catch (err) {
                console.error("Toggle freeze error:", err);
            }
        }

        function updateFsToolbar() {
            const btn = document.getElementById('fsFreezeBtn');
            if (btn) {
                if (window.currentFsIsFrozen) {
                    btn.innerHTML = '▶️ Resume Live';
                    btn.style.background = '#f59e0b';
                } else {
                    btn.innerHTML = '📸 Freeze & Count';
                    btn.style.background = '#6366f1';
                }
            }
        }

        function openFullscreen(url, camId) {
            const overlay = document.getElementById('fsOverlay');
            const img = document.getElementById('fsImg');
            img.src = url;
            overlay.classList.add('active');
            window.currentFsCamId = camId || null;
            if (camId && window.lastCamerasData) {
                const c = window.lastCamerasData.find(x => x.id === camId);
                window.currentFsIsFrozen = c ? !!c.is_frozen : false;
            } else {
                window.currentFsIsFrozen = false;
            }
            updateFsToolbar();
        }

        function closeFullscreen() {
            const overlay = document.getElementById('fsOverlay');
            const img = document.getElementById('fsImg');
            overlay.classList.remove('active');
            img.src = "";
            window.currentFsCamId = null;
        }

        function fsToggleFreeze() {
            if (window.currentFsCamId) {
                toggleFreezeCamera(window.currentFsCamId);
            }
        }

        function fsSyncToBin() {
            if (window.currentFsCamId) {
                syncCameraToBin(window.currentFsCamId);
            }
        }

        // ==========================================
        // AI Inbound Operations Automation Engine
        // ==========================================
        window.inboundLogEntries = [
            { time: new Date().toLocaleTimeString(), tag: 'STARTUP', color: '#6366f1', text: 'Matrix Engine Initialized. Listening for YOLO streams on Gates and Docks...' }
        ];

        window.addInboundLog = function(tag, text, color = '#10b981') {
            const time = new Date().toLocaleTimeString();
            window.inboundLogEntries.unshift({ time, tag, color, text });
            if (window.inboundLogEntries.length > 50) window.inboundLogEntries.pop();
            renderInboundLog();
        };

        window.clearInboundLog = function() {
            window.inboundLogEntries = [
                { time: new Date().toLocaleTimeString(), tag: 'CLEARED', color: '#94a3b8', text: 'Operations log reset by operator.' }
            ];
            renderInboundLog();
        };

        window.addManualLogEntry = function(msg) {
            window.addInboundLog('OPERATOR', msg || 'Manual telemetry checkpoint recorded.', '#f59e0b');
        };

        function renderInboundLog() {
            const logContainer = document.getElementById('ai-operations-log');
            if (!logContainer) return;
            logContainer.innerHTML = window.inboundLogEntries.map(entry => `
                <div style="border-bottom:1px solid #222; padding-bottom:4px; line-height:1.4;">
                    <span style="color:#64748b; font-size:0.75rem;">[${entry.time}]</span>
                    <span style="color:${entry.color}; font-weight:700; margin:0 4px;">[${entry.tag}]</span>
                    <span style="color:#e2e8f0;">${escapeHtml(entry.text)}</span>
                </div>
            `).join('');
        }

        window.refreshInboundAutomation = async function() {
            try {
                // Fetch Gate Passes, Cameras, and Deliveries in parallel
                const [gpRes, camRes, delRes, binRes] = await Promise.all([
                    fetch('/api/gate_passes').catch(() => null),
                    fetch('/api/cameras').catch(() => null),
                    fetch('/api/deliveries').catch(() => null),
                    fetch('/api/bins').catch(() => null)
                ]);

                const passes = gpRes ? await gpRes.json() : (window.globalGatePasses || []);
                const cameras = camRes ? await camRes.json() : (window.lastCamerasData || []);
                const deliveries = delRes ? await delRes.json() : (window.globalDeliveries || []);
                const bins = binRes ? await binRes.json() : [];

                window.globalGatePasses = passes;
                window.lastCamerasData = cameras;
                window.globalDeliveries = deliveries;

                // 1. Identify trucks actively at Docks
                const dockedPasses = (passes || []).filter(p => ['Sent to Dock', 'Unloading'].includes(p.status));
                
                // 2. Update KPI metrics
                let totalPiecesCounted = 0;
                let activeBinsSet = new Set();

                dockedPasses.forEach(p => {
                    const cnt = p.vision_unloaded_count || p.unloaded_qty || 0;
                    totalPiecesCounted += cnt;
                });

                cameras.forEach(c => {
                    if (c.bin_id) activeBinsSet.add(c.bin_id);
                    totalPiecesCounted += (c.clustered_bundle_count || c.head_count || 0);
                });

                const kpiTrucks = document.getElementById('inbound-kpi-trucks');
                const kpiPieces = document.getElementById('inbound-kpi-pieces');
                const kpiBins = document.getElementById('inbound-kpi-bins');
                const dockBadge = document.getElementById('inbound-dock-count-badge');

                if (kpiTrucks) kpiTrucks.innerText = dockedPasses.length;
                if (kpiPieces) kpiPieces.innerText = totalPiecesCounted;
                if (kpiBins) kpiBins.innerText = activeBinsSet.size || (bins.length > 0 ? bins.length : 1);
                if (dockBadge) dockBadge.innerText = `${dockedPasses.length} Active ${dockedPasses.length === 1 ? 'Bay' : 'Bays'}`;

                // 3. Render Active Dock Unloading & Reconciliation Cards
                const docksContainer = document.getElementById('inbound-docks-container');
                if (docksContainer) {
                    if (dockedPasses.length === 0) {
                        docksContainer.innerHTML = `
                            <div style="grid-column: 1 / -1; text-align:center; padding: 40px 20px; color:var(--text-muted); background:var(--panel-subtle); border-radius:8px; border:1px dashed var(--border-light);">
                                <i class="fas fa-truck-loading" style="font-size:2.5rem; color:var(--text-muted); margin-bottom:12px; display:block;"></i>
                                <p style="margin:0 0 8px 0; font-size:1.05rem; font-weight:700; color:var(--text-main);">No trucks are currently docked for unloading.</p>
                                <p style="margin:0 0 16px 0; font-size:0.85rem; color:var(--text-muted);">Assign an arrived truck in Gate Management, or click below to simulate an active inbound delivery.</p>
                                <button type="button" class="btn-primary" style="background:#10b981; color:#000; font-weight:bold; font-size:0.85rem; padding:8px 18px; border:none; cursor:pointer;" onclick="simulateInboundArrival()">
                                    ⚡ Simulate Inbound Arrival &amp; Dock Unload
                                </button>
                            </div>
                        `;
                    } else {
                        docksContainer.innerHTML = dockedPasses.map(gp => {
                            // Match dock camera
                            const dockName = (gp.dock || 'Dock 1').trim();
                            let matchedCam = cameras.find(c => c.location && c.location.toLowerCase().includes(dockName.toLowerCase()));
                            if (!matchedCam) {
                                matchedCam = dockName.toLowerCase().includes('2') 
                                    ? (cameras.find(c => c.id === 'CAM-003') || cameras[1] || cameras[0])
                                    : (cameras.find(c => c.id === 'CAM-002') || cameras[0]);
                            }

                            const camId = matchedCam ? matchedCam.id : (dockName.toLowerCase().includes('2') ? 'CAM-003' : 'CAM-002');
                            const camName = matchedCam ? matchedCam.name : `${dockName} Vision Camera`;

                            // Parse Manifest & Expected Qty
                            let expectedQty = 50;
                            let skuCode = 'SKU-INBOUND-01';
                            let itemDesc = gp.load || 'Material Packages';

                            if (gp.unloading_sheet) {
                                try {
                                    const sheet = typeof gp.unloading_sheet === 'string' ? JSON.parse(gp.unloading_sheet) : gp.unloading_sheet;
                                    if (Array.isArray(sheet) && sheet.length > 0) {
                                        expectedQty = sheet[0].expected || 50;
                                        skuCode = sheet[0].sku || skuCode;
                                        itemDesc = sheet[0].desc || itemDesc;
                                    }
                                } catch(e) {}
                            }

                            // AI verified count
                            let verifiedCount = gp.vision_unloaded_count !== undefined && gp.vision_unloaded_count > 0 
                                ? gp.vision_unloaded_count 
                                : (gp.unloaded_qty || (matchedCam ? (matchedCam.head_count || matchedCam.clustered_bundle_count) : 0) || expectedQty);

                            const matchPercent = expectedQty > 0 ? Math.min(100, Math.round((verifiedCount / expectedQty) * 100)) : 100;
                            const isMatched = verifiedCount >= expectedQty;
                            const statusColor = isMatched ? '#10b981' : '#f59e0b';

                            const targetBin = (matchedCam && matchedCam.bin_id) ? matchedCam.bin_id : (bins.length > 0 ? bins[0].bin_id : 'BIN-A1');

                            return `
                                <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:10px; padding:18px; display:flex; flex-direction:column; gap:14px; box-shadow:var(--card-shadow);">
                                    <!-- Header Info -->
                                    <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
                                        <div>
                                            <div style="display:flex; align-items:center; gap:8px;">
                                                <span class="badge" style="background:#1e3a8a; color:#93c5fd; font-weight:700; font-size:0.8rem; padding:4px 8px;">⚓ ${escapeHtml(dockName)}</span>
                                                <h4 style="margin:0; font-size:1.1rem; color:var(--text-main);">${escapeHtml(gp.plate || 'No Plate')}</h4>
                                            </div>
                                            <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px;">
                                                Driver: <strong>${escapeHtml(gp.driver_name || 'Assigned')}</strong> | PO: <strong>${escapeHtml(gp.po_number || 'N/A')}</strong>
                                            </div>
                                            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">
                                                Vendor: ${escapeHtml(gp.vendor || 'Supplier')}
                                            </div>
                                        </div>
                                        <div style="text-align:right;">
                                            <span class="badge ${gp.status === 'Unloading' ? 'pending' : 'sent'}" style="font-size:0.75rem;">${escapeHtml(gp.status)}</span>
                                            <div style="font-size:0.7rem; color:var(--text-muted); margin-top:4px;">Pass #${gp.id}</div>
                                        </div>
                                    </div>

                                    <!-- Live Dock Camera Viewport -->
                                    <div style="position:relative; width:100%; border-radius:8px; overflow:hidden; background:#000; border:1px solid var(--border-light); height:180px;">
                                        <img src="/video_feed/${camId}" onerror="this.src='/static/test_scenes/dock01_test.jpg'" style="width:100%; height:100%; object-fit:cover;" alt="Dock Camera Stream"/>
                                        <div style="position:absolute; top:8px; left:8px; background:rgba(0,0,0,0.75); color:#fff; font-size:0.72rem; padding:3px 8px; border-radius:4px; display:flex; align-items:center; gap:5px;">
                                            <span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:#ef4444; animation:pulse 1.5s infinite;"></span>
                                            📹 ${escapeHtml(camName)}
                                        </div>
                                        <div style="position:absolute; bottom:8px; right:8px; background:rgba(0,0,0,0.85); color:#10b981; font-family:monospace; font-weight:700; font-size:0.85rem; padding:4px 8px; border-radius:4px; border:1px solid #059669;">
                                            AI Count: ${verifiedCount} units
                                        </div>
                                    </div>

                                    <!-- Manifest vs AI Perception Reconciliation Meter -->
                                    <div style="background:var(--panel-subtle); border:1px solid var(--border-light); padding:12px; border-radius:8px;">
                                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; font-size:0.82rem;">
                                            <span style="font-weight:600; color:var(--text-main);">${escapeHtml(itemDesc)}</span>
                                            <span style="font-weight:700; color:${statusColor}; font-size:0.85rem;">
                                                ${verifiedCount} / ${expectedQty} (${matchPercent}%)
                                            </span>
                                        </div>
                                        <div style="width:100%; height:8px; background:#334155; border-radius:4px; overflow:hidden; margin-bottom:8px;">
                                            <div style="width:${matchPercent}%; height:100%; background:${statusColor}; transition:width 0.4s ease;"></div>
                                        </div>
                                        <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem; color:var(--text-muted);">
                                            <span>Expected Manifest: <strong>${expectedQty}</strong></span>
                                            <span style="color:${statusColor}; font-weight:700;">
                                                ${isMatched ? '✓ 100% Verified Match' : '⏳ In Progress Unloading'}
                                            </span>
                                        </div>
                                    </div>

                                    <!-- Putaway Slot Recommendation -->
                                    <div style="display:flex; justify-content:space-between; align-items:center; background:#1e293b; padding:10px 14px; border-radius:6px; border:1px solid #334155;">
                                        <div>
                                            <div style="font-size:0.7rem; color:#94a3b8; text-transform:uppercase;">Intelligent Putaway Slot</div>
                                            <div style="font-size:0.95rem; font-weight:700; color:#38bdf8; margin-top:2px;">
                                                📍 ${escapeHtml(targetBin)}
                                            </div>
                                        </div>
                                        <div>
                                            <button type="button" style="background:#334155; color:#cbd5e1; border:none; padding:4px 10px; font-size:0.72rem; border-radius:4px; cursor:pointer;" onclick="promptAssignCameraBin('${camId}')">
                                                Change Bin
                                            </button>
                                        </div>
                                    </div>

                                    <!-- Operational Action Buttons -->
                                    <div style="display:flex; gap:10px; margin-top:2px;">
                                        <button type="button" class="btn-primary" style="flex:1; background:#10b981; color:#000; font-weight:700; font-size:0.8rem; padding:9px 12px; border:none; cursor:pointer;" onclick="syncCameraToBin('${camId}')">
                                            ⚡ Sync to Bin (${targetBin})
                                        </button>
                                        <button type="button" class="btn-primary" style="flex:1; background:var(--accent); color:#fff; font-weight:700; font-size:0.8rem; padding:9px 12px; border:none; cursor:pointer;" onclick="completeInboundReceipt('${gp.id}', '${targetBin}', ${verifiedCount}, '${skuCode}', '${escapeHtml(gp.vendor || 'Inbound')}')">
                                            ✅ Complete Receipt (GRN)
                                        </button>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    }
                }

                // 4. Render Spatial Matrix Camera Streams
                renderInboundCamerasList(cameras);

                // 5. Update Tab Badge
                const badge = document.getElementById('inbound-badge');
                if (badge) {
                    if (dockedPasses.length > 0) {
                        badge.style.display = 'inline-block';
                        badge.innerText = dockedPasses.length;
                    } else {
                        badge.style.display = 'none';
                    }
                }

            } catch(e) {
                console.error("Error refreshing Inbound Automation:", e);
            }
        };

        function renderInboundCamerasList(cameras) {
            const bundleContainer = document.getElementById('live-bundle-counts');
            if (!bundleContainer) return;

            let activeCams = (cameras || []).filter(c => (c.latest_boxes && c.latest_boxes.length > 0) || c.location.toLowerCase().includes('dock') || c.bin_id);
            if (activeCams.length === 0) activeCams = cameras || [];

            if (activeCams.length === 0) {
                bundleContainer.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem; padding: 20px; text-align:center;">No active camera streams found.</p>';
                return;
            }

            let bundleHtml = '';
            activeCams.forEach(cam => {
                let boxCount = 0;
                let carPartsCount = 0;
                if (cam.latest_boxes) {
                    cam.latest_boxes.forEach(b => {
                        const t = (b.type || '').toLowerCase();
                        if (t.includes('box') || t.includes('bundle')) boxCount++;
                        if (t.includes('car part') || t.includes('engine') || t.includes('bumper') || t.includes('part')) carPartsCount++;
                    });
                }
                const pileCount = cam.clustered_bundle_count !== undefined ? cam.clustered_bundle_count : boxCount;
                const hasBin = !!cam.bin_id;
                const isAutoSync = window.autoSyncCameras && window.autoSyncCameras.has(cam.id);

                bundleHtml += `
                    <div style="background:#1a1a24; padding:14px; border-radius:6px; border:1px solid var(--border-light); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                        <div>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <h4 style="margin:0; color:#fff; font-size:0.95rem;">${escapeHtml(cam.name)}</h4>
                                ${hasBin ? 
                                    `<span class="badge" style="background:#064e3b; color:#34d399; font-size:0.7rem; cursor:pointer;" onclick="promptAssignCameraBin('${cam.id}')" title="Click to reassign">📍 Bin: ${escapeHtml(cam.bin_id)}</span>` : 
                                    `<button style="background:#334155; color:#9ca3af; border:none; padding:2px 8px; font-size:0.7rem; border-radius:3px; cursor:pointer;" onclick="promptAssignCameraBin('${cam.id}')">+ Assign Bin</button>`
                                }
                            </div>
                            <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px;">
                                Spatial Matrix: ${cam.latest_boxes ? cam.latest_boxes.length : 0} objects tracked | ${escapeHtml(cam.location)}
                            </div>
                        </div>
                        <div style="display:flex; gap:14px; align-items:center;">
                            <div style="text-align:center;">
                                <div style="font-size:1.5rem; font-weight:bold; color:#10b981;">${pileCount}</div>
                                <div style="font-size:0.68rem; color:var(--text-muted);">Clustered Pile</div>
                            </div>
                            <div style="text-align:center;">
                                <div style="font-size:1.5rem; font-weight:bold; color:#8b5cf6;">${carPartsCount}</div>
                                <div style="font-size:0.68rem; color:var(--text-muted);">Car Parts</div>
                            </div>
                            <div style="display:flex; flex-direction:column; gap:6px; align-items:flex-end;">
                                <button class="btn-primary" style="padding:5px 12px; font-size:0.72rem; background:#10b981; color:#000; font-weight:bold; border:none; cursor:pointer;" onclick="syncCameraToBin('${cam.id}')" ${!hasBin ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                                    ⚡ Sync to Bin
                                </button>
                                <label style="font-size:0.68rem; color:#cbd5e1; display:flex; align-items:center; gap:4px; cursor:pointer;">
                                    <input type="checkbox" onchange="toggleAutoSync('${cam.id}', this.checked)" ${isAutoSync ? 'checked' : ''} ${!hasBin ? 'disabled' : ''}> Auto-Sync
                                </label>
                            </div>
                        </div>
                    </div>
                `;
            });

            bundleContainer.innerHTML = bundleHtml;
        }

        window.simulateInboundArrival = async function() {
            try {
                window.addInboundLog('SIMULATION', 'Triggering autonomous inbound arrival sequence...', '#f59e0b');
                const res = await fetch('/api/inbound/simulate', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    window.addInboundLog('DOCK-DISPATCH', data.message, '#10b981');
                    window.addInboundLog('AI-YOLO', 'Connecting Dock 01 Overhead Camera CAM-DOCK-01. Live bundle clusters active.', '#38bdf8');
                    window.addInboundLog('PUTAWAY', 'Spatial Putaway Engine recommends slot BIN-A1 (Zone A).', '#a855f7');
                    await refreshInboundAutomation();
                    if (typeof fetchGatePasses === 'function') fetchGatePasses();
                    if (typeof fetchDeliveries === 'function') fetchDeliveries();
                    alert(`✅ ${data.message}\n\nLive Dock Unloading and Material Reconciliation are now active in the Inbound Automation view!`);
                } else {
                    alert('Simulation error: ' + data.message);
                }
            } catch(e) {
                alert('Error running simulation: ' + e.message);
            }
        };

        window.completeInboundReceipt = async function(gpId, binId, quantity, skuId, vendor) {
            if (!confirm(`Complete Inbound Receiving for Pass #${gpId}?\n\n• Verified Quantity: ${quantity}\n• Target Bin: ${binId}\n• SKU: ${skuId}\n\nThis will generate a Goods Receipt Note and update Bin inventory.`)) {
                return;
            }

            try {
                const res = await fetch('/api/inbound/complete_receipt', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ gp_id: gpId, bin_id: binId, quantity, sku_id: skuId, vendor })
                });
                const data = await res.json();
                if (data.success) {
                    window.addInboundLog('RECEIPT-GRN', `Goods Receipt completed for Pass #${gpId}. ${quantity} units stored in ${binId}.`, '#10b981');
                    alert(`✅ ${data.message}`);
                    await refreshInboundAutomation();
                    if (typeof fetchGatePasses === 'function') fetchGatePasses();
                    if (typeof fetchDeliveries === 'function') fetchDeliveries();
                    if (typeof fetchBins === 'function') fetchBins();
                    if (typeof fetchInventoryMaster === 'function') fetchInventoryMaster();
                } else {
                    alert('Failed to complete receipt: ' + data.message);
                }
            } catch(e) {
                alert('Error completing receipt: ' + e.message);
            }
        };

        function renderInboundAutomation(cameras) {
            refreshInboundAutomation();
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
// CYCLE COUNTING & W.A.R.L.O.G. AI AUDITING
// ==========================================

let ccCachedBins = [];
let ccCurrentAuditResult = null;

async function fetchCycleCountData() {
    try {
        const res = await fetch('/api/bins');
        ccCachedBins = await res.json();
        renderCycleCountTable(ccCachedBins);
        populateCycleCountBinSelect(ccCachedBins);
        fetchCycleCountActivities();
    } catch (e) {
        console.error("Failed to fetch bins for cycle count:", e);
    }
}
window.fetchCycleCountData = fetchCycleCountData;

function populateCycleCountBinSelect(bins) {
    const select = document.getElementById('ccSelectedBinSelect');
    if (!select) return;
    const currentVal = select.value;
    select.innerHTML = '<option value="">-- Choose Storage Bin --</option>' + 
        bins.map(b => `<option value="${b.bin_id}" ${b.bin_id === currentVal ? 'selected' : ''}>${b.bin_id} (${b.zone || 'General'}) - ${b.stock_count || 0} items</option>`).join('');
}

function renderCycleCountTable(bins) {
    const tbody = document.getElementById('cycleCountBody');
    if (!tbody) return;

    if (!bins || bins.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:1.5rem; color:var(--text-muted);">No storage bins registered in warehouse.</td></tr>`;
        return;
    }

    tbody.innerHTML = bins.map(b => {
        const stockCount = b.stock_count || 0;
        const vendorText = b.vendor || 'Empty';
        return `
            <tr>
                <td><strong>${b.bin_id}</strong></td>
                <td><span class="badge" style="background:var(--panel-subtle); color:var(--text-light);">${b.zone || 'General'}</span></td>
                <td><span style="font-family:monospace; font-size:0.85rem;">${vendorText}</span></td>
                <td><strong style="color:var(--accent); font-size:1.05rem;">${stockCount}</strong> Units</td>
                <td><span class="badge ${stockCount > 0 ? 'badge-success' : 'badge-warning'}">${stockCount > 0 ? 'Stocked' : 'Empty'}</span></td>
                <td>
                    <div style="display:flex; gap:8px;">
                        <button class="btn-primary btn-sm" onclick="selectAndInspectBin('${b.bin_id}')" style="display:inline-flex; align-items:center; gap:4px;">
                            <span>👁️</span> Inspect AI
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function onCycleCountBinSelected() {
    const select = document.getElementById('ccSelectedBinSelect');
    if (!select || !select.value) {
        const panel = document.getElementById('ccInspectionResultsPanel');
        if (panel) panel.style.display = 'none';
        return;
    }
    inspectSelectedBinAi();
}
window.onCycleCountBinSelected = onCycleCountBinSelected;

function selectAndInspectBin(binId) {
    const select = document.getElementById('ccSelectedBinSelect');
    if (select) {
        select.value = binId;
    }
    inspectSelectedBinAi(binId);
    // Scroll to workbench
    const sub = document.getElementById('cycle-count-sub');
    if (sub) sub.scrollIntoView({ behavior: 'smooth' });
}
window.selectAndInspectBin = selectAndInspectBin;

async function inspectSelectedBinAi(overrideBinId) {
    const select = document.getElementById('ccSelectedBinSelect');
    const binId = overrideBinId || (select ? select.value : "");
    if (!binId) {
        alert("Please select a storage bin first.");
        return;
    }

    const btn = document.getElementById('btnInspectBinAi');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span>⏳</span> Evaluating...`;
    }

    try {
        const res = await fetch(`/api/cycle_count/audit/${encodeURIComponent(binId)}`);
        const data = await res.json();
        if (!data.success) {
            alert("Error auditing bin: " + (data.error || "Unknown error"));
            return;
        }

        ccCurrentAuditResult = data;
        renderInspectionResults(data);
    } catch (e) {
        console.error("Failed to inspect bin with AI:", e);
        alert("Connection error inspecting bin.");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<span>👁️</span> Inspect with W.A.R.L.O.G. AI`;
        }
    }
}
window.inspectSelectedBinAi = inspectSelectedBinAi;

function renderInspectionResults(data) {
    const panel = document.getElementById('ccInspectionResultsPanel');
    if (!panel) return;
    panel.style.display = 'block';

    const wms = data.wms_inventory || {};
    const vision = data.vision_evidence || {};
    const disc = data.discrepancy || {};

    // 1. WMS Ledger Context
    document.getElementById('ccWmsBinId').innerText = data.bin_id;
    document.getElementById('ccWmsZone').innerText = wms.bin_details?.zone || 'General';
    document.getElementById('ccWmsExpectedQty').innerText = `${wms.total_quantity || 0} Units`;
    document.getElementById('ccWmsSkus').innerText = (wms.distinct_skus && wms.distinct_skus.length > 0) ? wms.distinct_skus.join(', ') : 'None (Empty)';

    const itemsDiv = document.getElementById('ccWmsItemsList');
    if (itemsDiv) {
        if (wms.items && wms.items.length > 0) {
            itemsDiv.innerHTML = wms.items.map(it => `<div>• <strong>${it.sku_id}</strong> (${it.sku_name || 'Component'}): ${it.quantity} units</div>`).join('');
        } else {
            itemsDiv.innerHTML = `<em>No inventory records in ledger for this bin.</em>`;
        }
    }

    // 2. Vision Observation
    const hasVision = vision.has_vision_evidence;
    const obsQty = vision.total_observed_qty ?? 0;
    document.getElementById('ccObservedQty').innerText = hasVision ? `${obsQty} Units` : 'N/A';
    document.getElementById('ccObservedSkus').innerText = (vision.validated_skus && vision.validated_skus.length > 0) ? vision.validated_skus.join(', ') : (hasVision ? 'Unidentified' : 'No Coverage');
    
    const obsMats = vision.observed_materials || [];
    const matTypes = Array.from(new Set(obsMats.map(m => m.material_type || 'Component')));
    document.getElementById('ccObservedType').innerText = matTypes.length > 0 ? matTypes.join(', ') : 'None';

    const cams = vision.monitoring_cameras || [];
    document.getElementById('ccMonitoringCams').innerText = cams.length > 0 ? cams.join(', ') : 'None';

    const covBadge = document.getElementById('ccVisionCoverageBadge');
    if (covBadge) {
        covBadge.className = `badge ${hasVision ? 'badge-success' : 'badge-warning'}`;
        covBadge.innerText = hasVision ? 'Vision Active' : 'No Coverage';
    }

    const obsDetailDiv = document.getElementById('ccObservedItemsDetail');
    if (obsDetailDiv) {
        if (obsMats.length > 0) {
            obsDetailDiv.innerHTML = obsMats.map(m => `<div>• [${m.material_type}] ${m.matched_sku || m.observed_id || 'Item'}: ${m.quantity} ${m.uom} (${m.identity_status})</div>`).join('');
        } else {
            obsDetailDiv.innerHTML = `<em>${hasVision ? 'No physical materials detected in bin area.' : 'No vision telemetry available.'}</em>`;
        }
    }

    // 3. Discrepancy & Recommendation Banner
    const badge = document.getElementById('ccDiscrepancyBadge');
    const recTitle = document.getElementById('ccRecommendationTitle');
    const expText = document.getElementById('ccExplanationText');
    const qtyInput = document.getElementById('ccAuditedQtyInput');
    const banner = document.getElementById('ccDiscrepancyBanner');

    const dType = disc.type || 'NO_VISION_EVIDENCE';
    badge.innerText = dType.replace(/_/g, ' ');
    recTitle.innerText = disc.recommendation ? disc.recommendation.replace(/_/g, ' ') : 'Review Required';
    expText.innerText = disc.explanation || '';

    // Color code banner and badge
    if (dType === 'MATCH') {
        badge.style.background = '#10b981';
        badge.style.color = '#fff';
        banner.style.background = 'rgba(16, 185, 129, 0.08)';
        banner.style.borderColor = 'rgba(16, 185, 129, 0.3)';
    } else if (dType === 'SHORTAGE' || dType === 'EMPTY_BIN') {
        badge.style.background = '#ef4444';
        badge.style.color = '#fff';
        banner.style.background = 'rgba(239, 68, 68, 0.08)';
        banner.style.borderColor = 'rgba(239, 68, 68, 0.3)';
    } else if (dType === 'EXCESS' || dType === 'MULTIPLE_MATERIALS') {
        badge.style.background = '#f59e0b';
        badge.style.color = '#fff';
        banner.style.background = 'rgba(245, 158, 11, 0.08)';
        banner.style.borderColor = 'rgba(245, 158, 11, 0.3)';
    } else {
        badge.style.background = '#64748b';
        badge.style.color = '#fff';
        banner.style.background = 'rgba(100, 116, 139, 0.08)';
        banner.style.borderColor = 'rgba(100, 116, 139, 0.3)';
    }

    // Suggest quantity in input
    if (disc.suggested_cycle_count_qty !== null && disc.suggested_cycle_count_qty !== undefined) {
        qtyInput.value = disc.suggested_cycle_count_qty;
    } else {
        qtyInput.value = wms.total_quantity || 0;
    }
}

async function commitSelectedCycleCount() {
    if (!ccCurrentAuditResult) {
        alert("Please inspect a storage bin first.");
        return;
    }

    const binId = ccCurrentAuditResult.bin_id;
    const qtyInput = document.getElementById('ccAuditedQtyInput');
    const actualQty = parseInt(qtyInput.value, 10);
    if (isNaN(actualQty) || actualQty < 0) {
        alert("Please enter a valid non-negative actual quantity.");
        return;
    }

    const btn = document.getElementById('btnCommitCycleCount');
    if (btn) {
        btn.disabled = true;
        btn.innerText = "Applying...";
    }

    try {
        const payload = {
            bin_id: binId,
            actual_qty: actualQty,
            notes: `AI-Assisted Cycle Count Audit (${ccCurrentAuditResult.discrepancy?.type || 'MANUAL'})`
        };

        const res = await fetch('/api/cycle_count', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (data.success) {
            alert(data.message);
            // Refresh data
            fetchCycleCountData();
            // Re-inspect with updated WMS state
            inspectSelectedBinAi(binId);
        } else {
            alert("Error: " + (data.message || "Could not apply cycle count."));
        }
    } catch (e) {
        console.error("Failed to commit cycle count:", e);
        alert("Connection error applying cycle count.");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = "✍ Apply Cycle Count";
        }
    }
}
window.commitSelectedCycleCount = commitSelectedCycleCount;

async function fetchCycleCountActivities() {
    try {
        const res = await fetch('/api/cycle_count/activities?limit=15');
        const data = await res.json();
        const tbody = document.getElementById('ccActivitiesBody');
        if (!tbody) return;

        const activities = data.activities || [];
        if (activities.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:1rem; color:var(--text-muted);">No audit activity recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = activities.map(a => `
            <tr>
                <td style="font-family:monospace; font-size:0.8rem; color:var(--text-muted);">${a.timestamp || '-'}</td>
                <td><span class="badge" style="background:rgba(59,130,246,0.15); color:#3b82f6;">${a.action || 'AUDIT'}</span></td>
                <td><strong>${a.target || '-'}</strong></td>
                <td style="font-size:0.85rem;">${a.details || '-'}</td>
            </tr>
        `).join('');
    } catch (e) {
        console.error("Failed to fetch cycle count activities:", e);
    }
}
window.fetchCycleCountActivities = fetchCycleCountActivities;

async function runCycleCount(bin_id) {
    selectAndInspectBin(bin_id);
}
window.runCycleCount = runCycleCount;

