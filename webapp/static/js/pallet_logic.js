/**
 * PALLETIZATION & HUMAN ERROR VIOLATION INTERCEPTOR LOGIC
 * W.A.R.L.O.G. Warehouse OS - Skantha Solutions
 */

(function() {
    let activePalletId = null;
    let palletPollTimer = null;
    let violationPollTimer = null;
    let knownViolationIds = new Set();
    let resolvedViolationIds = new Set();
    let lastViolationToastTime = 0;
    let audioContext = null;

    // Toast Notification System
    function showToast(msg, type = 'info') {
        let container = document.getElementById('palletToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'palletToastContainer';
            container.style.cssText = 'position:fixed; top:24px; right:24px; z-index:999999; display:flex; flex-direction:column; gap:10px; pointer-events:none;';
            document.body.appendChild(container);
        }
        const toast = document.createElement('div');
        const bg = type === 'error' ? '#ef4444' : (type === 'success' ? '#10b981' : '#6366f1');
        const icon = type === 'error' ? 'fa-triangle-exclamation' : (type === 'success' ? 'fa-circle-check' : 'fa-circle-info');
        toast.style.cssText = `background:${bg}; color:#fff; padding:12px 18px; border-radius:8px; font-weight:600; font-size:0.85rem; box-shadow:0 8px 24px rgba(0,0,0,0.25); display:flex; align-items:center; gap:8px; pointer-events:auto; font-family:inherit; transition:opacity 0.3s ease, transform 0.3s ease;`;
        toast.innerHTML = `<i class="fas ${icon}"></i> <span>${msg}</span>`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            setTimeout(() => toast.remove(), 350);
        }, 3800);
    }
    window.showToast = showToast;

    // Web Audio Synthesized Alert Buzzer (Zero external audio asset dependency)
    function playViolationBuzzer() {
        try {
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioContext.state === 'suspended') {
                audioContext.resume();
            }
            const osc = audioContext.createOscillator();
            const gain = audioContext.createGain();
            osc.type = 'sawtooth';
            // Two rapid dissonant warning tones
            osc.frequency.setValueAtTime(440, audioContext.currentTime);
            osc.frequency.setValueAtTime(280, audioContext.currentTime + 0.12);
            gain.gain.setValueAtTime(0.25, audioContext.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.35);
            osc.connect(gain);
            gain.connect(audioContext.destination);
            osc.start();
            osc.stop(audioContext.currentTime + 0.35);
        } catch(e) {
            console.warn('[Audio] Buzzer play error:', e);
        }
    }

    // --------------------------------------------------------------------------
    // VIOLATIONS INTERCEPTOR & DRAWER
    // --------------------------------------------------------------------------
    async function pollViolations() {
        try {
            const res = await fetch('/api/violations?status=OPEN');
            if (!res.ok) return;
            const raw = await res.json();
            const violations = Array.isArray(raw) ? raw : (raw.violations || []);
            
            // Update Topbar Badge
            const btn = document.getElementById('navViolationsBtn');
            const txt = document.getElementById('navViolationsCount');
            const approveAllBtn = document.getElementById('btnApproveAllViolations');
            const count = violations.length;
            
            if (txt) txt.textContent = count;
            if (btn) {
                if (count > 0) {
                    btn.classList.add('has-violations');
                    btn.style.display = 'inline-flex';
                } else {
                    btn.classList.remove('has-violations');
                    btn.style.display = 'none';
                }
            }

            if (approveAllBtn) {
                approveAllBtn.style.display = count > 0 ? 'inline-flex' : 'none';
            }

            // Check if brand new high-severity violations occurred (filter out resolved/acknowledged)
            let hasNew = false;
            const now = Date.now();
            violations.forEach(v => {
                if (!knownViolationIds.has(v.id) && !resolvedViolationIds.has(v.id)) {
                    knownViolationIds.add(v.id);
                    hasNew = true;
                }
            });

            // Prevent irritating repetitive toast notification (max once every 30s)
            if (hasNew && violations.length > 0 && (now - lastViolationToastTime > 30000)) {
                lastViolationToastTime = now;
                playViolationBuzzer();
                showToast(`🚨 Human Error Intercepted: ${violations[0].violation_type}`, 'error');
            }

            // Render drawer body if open
            renderViolationsList(violations);
        } catch(err) {
            console.error('[Violations] Poll error:', err);
        }
    }

    function renderViolationsList(violations) {
        const body = document.getElementById('violationsDrawerBody');
        if (!body) return;

        if (!violations || violations.length === 0) {
            body.innerHTML = `
                <div style="text-align:center; padding:3rem 1rem; color:var(--text-muted);">
                    <i class="fas fa-circle-check" style="font-size:2.5rem; color:#10b981; margin-bottom:12px; display:block;"></i>
                    <h4 style="margin:0 0 6px 0; color:var(--text-main);">No Open Violations</h4>
                    <p style="font-size:0.82rem; margin:0;">Autonomous vision has detected zero human placement or bin compliance errors.</p>
                </div>
            `;
            return;
        }

        body.innerHTML = violations.map(v => {
            const sevColor = v.severity === 'CRITICAL' ? '#dc2626' : (v.severity === 'HIGH' ? '#ef4444' : '#f59e0b');
            const sevBg = v.severity === 'CRITICAL' ? 'rgba(220,38,38,0.1)' : 'rgba(245,158,11,0.1)';
            const timeStr = new Date(v.created_at || Date.now()).toLocaleTimeString();
            return `
                <div class="violation-card severity-${(v.severity||'medium').toLowerCase()}">
                    <div class="violation-card-top">
                        <span class="violation-type-badge" style="background:${sevBg}; color:${sevColor}; border:1px solid ${sevColor};">
                            ${(v.violation_type || 'VIOLATION').replace(/_/g, ' ')}
                        </span>
                        <span>${timeStr}</span>
                    </div>
                    <div class="violation-card-title">${v.title || (v.violation_type || 'Infraction').replace(/_/g, ' ')}</div>
                    <div class="violation-card-desc">${v.description || v.details || 'Human error caught by Autonomous Vision pipeline.'}</div>
                    <div class="violation-card-meta">
                        ${v.pallet_id ? `<span>PLT: <b>${v.pallet_id}</b></span>` : ''}
                        ${v.bin_id ? `<span>BIN: <b>${v.bin_id}</b></span>` : ''}
                        ${v.sku_id ? `<span>SKU: <b>${v.sku_id}</b></span>` : ''}
                        ${v.camera_id ? `<span>CAM: <b>${v.camera_id}</b></span>` : ''}
                    </div>
                    <div style="margin-top:6px; display:flex; justify-content:flex-end;">
                        <button type="button" class="btn-secondary" style="font-size:0.75rem; padding:4px 10px;" onclick="window.resolveViolationModal(${v.id}, '${v.violation_type}')">
                            <i class="fas fa-check"></i> Acknowledge &amp; Resolve
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }

    window.toggleViolationsDrawer = function(forceOpen) {
        const drawer = document.getElementById('violationsDrawer');
        const backdrop = document.getElementById('violationsDrawerBackdrop');
        if (!drawer || !backdrop) return;

        const isOpen = drawer.classList.contains('open');
        const nextState = forceOpen !== undefined ? forceOpen : !isOpen;

        if (nextState) {
            drawer.classList.add('open');
            backdrop.classList.add('active');
            pollViolations();
        } else {
            drawer.classList.remove('open');
            backdrop.classList.remove('active');
        }
    };

    window.resolveViolationModal = async function(id, type) {
        resolvedViolationIds.add(id);
        try {
            const res = await fetch(`/api/violations/${id}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notes: 'Approved by supervisor', resolved_by: 'Supervisor' })
            });
            const data = await res.json();
            if (res.ok && (data.success || data.status === 'success')) {
                showToast(`Violation #${id} approved & resolved.`, 'success');
                await pollViolations();
            } else {
                alert(`Error: ${data.error || data.message || 'Failed to resolve violation'}`);
            }
        } catch(e) {
            console.error('Resolution error:', e);
            alert(`Network error: ${e.message}`);
        }
    };

    window.resolveAllViolations = async function() {
        try {
            const btn = document.getElementById('btnApproveAllViolations');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Approving...';
            }
            const res = await fetch('/api/violations/resolve_all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notes: 'Bulk approved by supervisor', resolved_by: 'Supervisor' })
            });
            const data = await res.json();
            if (data.success) {
                showToast(`All ${data.resolved_count} violation(s) approved and cleared!`, 'success');
                knownViolationIds.clear();
                resolvedViolationIds.clear();
                await pollViolations();
            } else {
                alert(`Error: ${data.error || 'Failed to bulk resolve violations'}`);
            }
        } catch(e) {
            console.error('Resolve all error', e);
            alert(`Network error: ${e.message}`);
        } finally {
            const btn = document.getElementById('btnApproveAllViolations');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-check-double"></i> Approve All';
            }
        }
    };

    // --------------------------------------------------------------------------
    // PALLETIZATION MANAGEMENT & BUNDLE COUNTER
    // --------------------------------------------------------------------------
    async function loadPallets() {
        try {
            const res = await fetch('/api/pallets');
            if (!res.ok) return;
            const raw = await res.json();
            const pallets = Array.isArray(raw) ? raw : (raw.pallets || []);
            renderPalletTable(pallets);

            if (!pallets || pallets.length === 0) {
                activePalletId = null;
                const idElem = document.getElementById('activePalletId');
                const skuElem = document.getElementById('activePalletSku');
                const bundleCountElem = document.getElementById('palletCountBundles');
                const unitsPerBundleElem = document.getElementById('palletUnitsPerBundle');
                const totalPiecesElem = document.getElementById('palletTotalPieces');
                const targetBundlesElem = document.getElementById('palletTargetBundles');
                const barFill = document.getElementById('palletProgressBarFill');
                const pctElem = document.getElementById('palletFillPct');
                const statusElem = document.getElementById('activePalletStatus');
                if (idElem) idElem.textContent = '—';
                if (skuElem) skuElem.textContent = 'Awaiting Pallet Creation...';
                if (bundleCountElem) bundleCountElem.textContent = '0';
                if (unitsPerBundleElem) unitsPerBundleElem.textContent = '0';
                if (totalPiecesElem) totalPiecesElem.textContent = '0';
                if (targetBundlesElem) targetBundlesElem.textContent = '0';
                if (barFill) barFill.style.width = '0%';
                if (pctElem) pctElem.textContent = '0%';
                if (statusElem) {
                    statusElem.textContent = 'IDLE';
                    statusElem.style.background = 'rgba(148, 163, 184, 0.15)';
                    statusElem.style.color = '#94a3b8';
                    statusElem.style.border = '1px solid #94a3b8';
                }
            } else if (!activePalletId && pallets.length > 0) {
                const openPallet = pallets.find(p => p.status !== 'SEALED') || pallets[0];
                setActivePallet(openPallet.pallet_id);
            } else if (activePalletId) {
                const cur = pallets.find(p => p.pallet_id === activePalletId);
                if (cur) updatePalletMonitorUI(cur);
            }
        } catch(err) {
            console.error('[Pallets] Load error:', err);
        }
    }

    async function loadPalletSkus() {
        try {
            const res = await fetch('/api/skus');
            if (!res.ok) return;
            const raw = await res.json();
            const skus = Array.isArray(raw) ? raw : (raw.skus || []);
            const select = document.getElementById('newPalletSkuSelect');
            if (!select) return;

            select.innerHTML = '<option value="">-- Choose SKU to Palletize --</option>' + skus.map(s => {
                const bundleUnits = s.units_per_bundle || 10;
                const targetBundles = s.target_bundles_per_pallet || 50;
                return `<option value="${s.sku_id}" data-units="${bundleUnits}" data-target="${targetBundles}">${s.sku_id} - ${s.name} (${bundleUnits} pcs/bundle)</option>`;
            }).join('');
        } catch(e) {
            console.error('[Pallet SKUs] Error:', e);
        }
    }

    async function loadPalletBins() {
        try {
            const res = await fetch('/api/bins');
            if (!res.ok) return;
            const raw = await res.json();
            const bins = Array.isArray(raw) ? raw : (raw.bins || []);
            const select = document.getElementById('newPalletBinSelect');
            if (!select) return;

            select.innerHTML = '<option value="">-- None / Assign on Seal --</option>' + bins.map(b => {
                return `<option value="${b.bin_id}">${b.bin_id} (${b.zone || 'Storage'} - ${b.status || 'AVAILABLE'})</option>`;
            }).join('');
        } catch(e) {
            console.error('[Pallet Bins] Error:', e);
        }
    }

    async function loadPalletCameras() {
        try {
            const res = await fetch('/api/cameras');
            if (!res.ok) return;
            const raw = await res.json();
            const cams = Array.isArray(raw) ? raw : (raw.cameras || []);
            const select = document.getElementById('palletCameraSelect');
            if (!select) return;

            if (cams.length === 0) {
                select.innerHTML = '<option value="cam_inbound_01">cam_inbound_01 (Pallet Zone)</option>';
                updateCameraStreamFeed('cam_inbound_01');
                return;
            }

            select.innerHTML = cams.map(c => {
                return `<option value="${c.camera_id}">${c.camera_id} - ${c.name} (${c.location || 'Palletizing Zone'})</option>`;
            }).join('');

            // On change, update stream feed
            select.onchange = function() {
                updateCameraStreamFeed(this.value);
            };

            updateCameraStreamFeed(cams[0].camera_id);
        } catch(e) {
            console.error('[Pallet Cameras] Error:', e);
        }
    }

    function updateCameraStreamFeed(camId) {
        const img = document.getElementById('palletLiveFeedImg');
        const camLabel = document.getElementById('palletFeedCamLabel');
        if (img) img.src = `/video_feed/${camId}`;
        if (camLabel) camLabel.textContent = `CAM: ${camId}`;

        // Also bind this camera to current pallet if active
        if (activePalletId && camId) {
            fetch(`/api/pallets/camera/${camId}/bind`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pallet_id: activePalletId })
            }).catch(e => console.warn('Cam bind error:', e));
        }
    }

    window.setActivePallet = async function(palletId) {
        activePalletId = palletId;
        try {
            const res = await fetch(`/api/pallets/${palletId}`);
            if (!res.ok) return;
            const raw = await res.json();
            const p = raw.pallet || raw;
            updatePalletMonitorUI(p);

            // Bind current camera
            const camSelect = document.getElementById('palletCameraSelect');
            if (camSelect && camSelect.value) {
                fetch(`/api/pallets/camera/${camSelect.value}/bind`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pallet_id: activePalletId })
                }).catch(e => console.warn('Cam bind error:', e));
            }
        } catch(e) {
            console.error('[Active Pallet] Fetch error:', e);
        }
    };

    function updatePalletMonitorUI(p) {
        if (!p) return;
        const idElem = document.getElementById('palletMonitorId');
        const skuElem = document.getElementById('palletMonitorSku');
        const statusElem = document.getElementById('palletMonitorStatus');
        const bundleCountElem = document.getElementById('palletCountBundles');
        const unitsPerBundleElem = document.getElementById('palletUnitsPerBundle');
        const totalPiecesElem = document.getElementById('palletTotalPieces');
        const targetBundlesElem = document.getElementById('palletTargetBundles');
        const barFill = document.getElementById('palletProgressBarFill');
        const pctElem = document.getElementById('palletFillPct');
        const hudBundles = document.getElementById('hudPalletBundles');
        const hudPieces = document.getElementById('hudPalletPieces');
        const sealBtn = document.getElementById('btnSealPallet');

        const bundles = p.counted_bundles !== undefined ? p.counted_bundles : (p.current_bundles || 0);
        const unitsPer = p.units_per_bundle || 1;
        const totalPcs = p.total_units !== undefined ? p.total_units : (p.total_pieces || (bundles * unitsPer));
        const target = p.target_bundles || 0;
        const isDynamic = !target || target <= 1;
        const pct = isDynamic ? 100 : Math.min(100, Math.round((bundles / target) * 100));

        if (idElem) idElem.textContent = p.pallet_id;
        if (skuElem) skuElem.textContent = `${p.sku_id} - ${p.sku_name || ''}`;
        if (bundleCountElem) bundleCountElem.textContent = bundles;
        if (unitsPerBundleElem) unitsPerBundleElem.textContent = unitsPer;
        if (totalPiecesElem) totalPiecesElem.textContent = totalPcs;
        if (targetBundlesElem) targetBundlesElem.textContent = isDynamic ? 'Open Count' : target;
        if (barFill) barFill.style.width = isDynamic ? '100%' : `${pct}%`;
        if (pctElem) pctElem.textContent = isDynamic ? 'DYNAMIC TALLY' : `${pct}%`;
        if (hudBundles) hudBundles.textContent = isDynamic ? `${bundles} Bundles` : `${bundles} / ${target}`;
        if (hudPieces) hudPieces.textContent = `${totalPcs} EA`;

        if (statusElem) {
            statusElem.textContent = p.status;
            if (p.status === 'SEALED') {
                statusElem.style.background = 'rgba(16, 185, 129, 0.15)';
                statusElem.style.color = '#10b981';
                statusElem.style.border = '1px solid #10b981';
                if (sealBtn) sealBtn.disabled = true;
            } else {
                statusElem.style.background = 'rgba(99, 102, 241, 0.15)';
                statusElem.style.color = '#6366f1';
                statusElem.style.border = '1px solid #6366f1';
                if (sealBtn) sealBtn.disabled = false;
            }
        }
    }

    function renderPalletTable(pallets) {
        const tbody = document.getElementById('palletTableBody');
        if (!tbody) return;

        if (!pallets || pallets.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:var(--text-muted);">No pallets registered yet. Click "+ Build New Pallet" to start.</td></tr>`;
            return;
        }

        tbody.innerHTML = pallets.map(p => {
            const isSelected = p.pallet_id === activePalletId;
            const isSealed = p.status === 'SEALED';
            const bundles = p.counted_bundles !== undefined ? p.counted_bundles : (p.current_bundles || 0);
            const target = p.target_bundles || 0;
            const unitsPer = p.units_per_bundle || 1;
            const total = p.total_units !== undefined ? p.total_units : (p.total_pieces || (bundles * unitsPer));
            const isDynamic = !target || target <= 1;
            const bundlesDisplay = isDynamic ? `<b>${bundles}</b> <span style="font-size:0.75rem; color:var(--text-muted);">(Open)</span>` : `<b>${bundles}</b> / ${target}`;

            return `
                <tr style="${isSelected ? 'background:rgba(99,102,241,0.06); font-weight:600;' : ''}">
                    <td style="font-family:'JetBrains Mono',monospace;"><b>${p.pallet_id}</b></td>
                    <td>
                        <div><b>${p.sku_id}</b></div>
                        <div style="font-size:0.75rem; color:var(--text-muted);">${p.sku_name || ''}</div>
                    </td>
                    <td>
                        <span class="badge" style="background:${isSealed ? '#10b981' : '#6366f1'}; color:white; font-size:0.7rem;">
                            ${p.status}
                        </span>
                    </td>
                    <td>
                        ${bundlesDisplay}
                    </td>
                    <td style="color:var(--text-muted); font-size:0.82rem;">
                        ${unitsPer} ea
                    </td>
                    <td>
                        <span style="font-family:'JetBrains Mono',monospace; color:#10b981; font-weight:700;">${total} EA</span>
                    </td>
                    <td>${p.assigned_bin_id || '<span style="color:var(--text-muted);">&mdash;</span>'}</td>
                    <td style="text-align:right;">
                        <button type="button" class="btn-secondary" style="font-size:0.75rem; padding:3px 8px; margin-right:4px;" onclick="window.setActivePallet('${p.pallet_id}')" title="Set Active in Vision Monitor">
                            <i class="fas fa-crosshairs"></i> Track
                        </button>
                        <button type="button" class="btn-secondary" style="font-size:0.75rem; padding:3px 8px; margin-right:4px;" onclick="window.printPalletMasterLabel('${p.pallet_id}')" title="Print Master Pallet QR Label">
                            <i class="fas fa-print"></i> Label
                        </button>
                        ${!isSealed ? `
                        <button type="button" class="btn-primary" style="font-size:0.75rem; padding:3px 8px; background:#10b981; border-color:#10b981;" onclick="window.sealPalletAction('${p.pallet_id}')" title="Seal Pallet & Finalize">
                            <i class="fas fa-box-archive"></i> Seal
                        </button>
                        ` : ''}
                    </td>
                </tr>
            `;
        }).join('');
    }

    window.openNewPalletModal = function() {
        const modal = document.getElementById('newPalletModal');
        if (!modal) return;
        loadPalletSkus();
        loadPalletBins();

        // Autogenerate unique Pallet ID
        const dateStr = new Date().toISOString().slice(2, 10).replace(/-/g, '');
        const rnd = Math.floor(1000 + Math.random() * 9000);
        const palletInput = document.getElementById('newPalletIdInput');
        if (palletInput) palletInput.value = `PLT-${dateStr}-${rnd}`;

        modal.style.display = 'flex';
    };

    window.closeNewPalletModal = function() {
        const modal = document.getElementById('newPalletModal');
        if (modal) modal.style.display = 'none';
    };

    window.onNewPalletSkuChange = function() {
        const select = document.getElementById('newPalletSkuSelect');
        const opt = select.options[select.selectedIndex];
        if (!opt) return;

        const units = opt.getAttribute('data-units') || 10;
        const unitsInput = document.getElementById('newPalletUnitsPerBundle');
        const targetInput = document.getElementById('newPalletTargetBundles');
        if (unitsInput) unitsInput.value = units;
        if (targetInput) targetInput.value = ''; // Left empty for dynamic live count
        window.calculateNewPalletTotalPreview();
    };

    window.calculateNewPalletTotalPreview = function() {
        const units = parseInt(document.getElementById('newPalletUnitsPerBundle')?.value || 0, 10);
        const targetVal = document.getElementById('newPalletTargetBundles')?.value;
        const target = targetVal ? parseInt(targetVal, 10) : 0;
        const preview = document.getElementById('newPalletTotalPiecesPreview');
        if (preview) {
            if (target > 0) {
                preview.textContent = `${target * units} Total Pieces (Target Cap: ${target} bundles)`;
            } else {
                preview.textContent = `Continuous Open Count (${units} individual pieces per detected bundle)`;
            }
        }
    };

    window.handleCreatePalletSubmit = async function(e) {
        if (e && e.preventDefault) e.preventDefault();
        const palletId = (document.getElementById('newPalletIdInput')?.value || '').trim();
        const skuSelect = document.getElementById('newPalletSkuSelect');
        const skuId = (skuSelect?.value || '').trim();
        const unitsPer = parseInt(document.getElementById('newPalletUnitsPerBundle')?.value || '10', 10);
        const targetVal = document.getElementById('newPalletTargetBundles')?.value;
        const target = targetVal ? parseInt(targetVal, 10) : 0;
        const binSelect = document.getElementById('newPalletBinSelect');
        const binId = (binSelect?.value || '').trim() || null;

        if (!skuId) {
            alert('Please select a target SKU to palletize.');
            return;
        }

        try {
            const res = await fetch('/api/pallets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    pallet_id: palletId || null,
                    sku_id: skuId,
                    units_per_bundle: unitsPer,
                    target_bundles: target,
                    assigned_bin_id: binId
                })
            });
            const data = await res.json();
            if (res.ok && (data.success || data.status === 'success')) {
                const createdId = data.pallet?.pallet_id || palletId;
                showToast(`Pallet ${createdId} initiated. Autonomous counting active.`, 'success');
                window.closeNewPalletModal();
                activePalletId = createdId;
                loadPallets();
            } else {
                const errMsg = data.error || data.message || `Server responded with status ${res.status}`;
                alert(`Error: ${errMsg}`);
            }
        } catch(err) {
            console.error('Create pallet error:', err);
            alert(`Network or Server error: ${err.message}`);
        }
    };

    window.sealPalletAction = async function(palletId) {
        const targetId = palletId || activePalletId;
        if (!targetId) return;

        if (!confirm(`Are you sure you want to SEAL pallet ${targetId}?\nThis will finalize the bundle count, close autonomous perception for this pallet, and generate the Master Pallet QR label.`)) {
            return;
        }

        try {
            const res = await fetch(`/api/pallets/${targetId}/seal`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (res.ok && (data.success || data.status === 'success')) {
                showToast(`Pallet ${targetId} SEALED successfully.`, 'success');
                loadPallets();
                // Prompt print label
                if (confirm(`Pallet sealed! Open and print Master Pallet QR label now?`)) {
                    window.printPalletMasterLabel(targetId);
                }
            } else {
                alert(`Error: ${data.error || data.message || 'Failed to seal pallet'}`);
            }
        } catch(e) {
            console.error('Seal error:', e);
            alert(`Network error: ${e.message}`);
        }
    };

    window.printPalletMasterLabel = function(palletId) {
        const targetId = palletId || activePalletId;
        if (!targetId) return;
        const url = `/api/pallets/${targetId}/label`;
        const printWindow = window.open(url, '_blank', 'width=700,height=900');
        if (printWindow) {
            printWindow.focus();
        }
    };

    window.handlePalletImageUpload = async function(event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;

        const inputElem = event.target;
        const targetId = activePalletId;
        const camSelect = document.getElementById('palletCameraSelect');
        const camId = camSelect ? camSelect.value : 'cam_inbound_01';

        const formData = new FormData();
        formData.append('image', file);
        if (targetId) formData.append('pallet_id', targetId);
        if (camId) formData.append('camera_id', camId);

        showToast('Analyzing pallet image for bundles & pieces...', 'info');
        const hudBundles = document.getElementById('hudPalletBundles');
        if (hudBundles) hudBundles.textContent = 'DETECTING...';

        try {
            const endpoint = targetId ? `/api/pallets/${targetId}/count_image` : '/api/pallets/count_image';
            const res = await fetch(endpoint, {
                method: 'POST',
                body: formData
            });

            const data = await res.json();
            if (!res.ok || !data.success) {
                showToast(`Image counting error: ${data.error || 'Failed to analyze image'}`, 'error');
                if (targetId) setActivePallet(targetId);
                return;
            }

            // Immediately display annotated result with bounding boxes in live feed view
            const img = document.getElementById('palletLiveFeedImg');
            if (img && data.annotated_image_url) {
                img.src = `${data.annotated_image_url}?t=${Date.now()}`;
            }

            if (data.pallet) {
                activePalletId = data.pallet.pallet_id;
                updatePalletMonitorUI(data.pallet);
            }
            loadPallets();

            const msg = `Counted ${data.counted_bundles} bundles (${data.total_pieces} pieces total) on pallet ${data.pallet_id}!`;
            showToast(msg, 'success');

            if (data.violations_triggered && data.violations_triggered.length > 0) {
                showToast(`Warning: ${data.violations_triggered.length} safety/SKU discrepancy flag(s) logged!`, 'warning');
                pollViolations();
            }
        } catch (err) {
            console.error('[Pallet Image Upload] Error:', err);
            showToast(`Upload failed: ${err.message}`, 'error');
        } finally {
            inputElem.value = '';
        }
    };

    window.resetPalletLiveFeed = function() {
        const camSelect = document.getElementById('palletCameraSelect');
        const camId = camSelect ? camSelect.value : 'cam_inbound_01';
        updateCameraStreamFeed(camId);
        showToast(`Switched back to live camera feed (${camId})`, 'info');
    };


    // Initialize timers and event listeners on DOM ready
    function init() {
        // Violations Poller (every 4 seconds)
        pollViolations();
        if (violationPollTimer) clearInterval(violationPollTimer);
        violationPollTimer = setInterval(pollViolations, 4000);

        // Pallet Poller (every 3 seconds when pallet view active)
        if (palletPollTimer) clearInterval(palletPollTimer);
        palletPollTimer = setInterval(() => {
            const palletView = document.getElementById('palletization-view');
            if (palletView && palletView.classList.contains('active')) {
                loadPallets();
            }
        }, 3000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose helpers globally for switchTab integration
    window.palletModule = {
        loadPallets,
        loadPalletSkus,
        loadPalletBins,
        loadPalletCameras,
        pollViolations
    };
})();
