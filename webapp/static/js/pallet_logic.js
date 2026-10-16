/**
 * PALLETIZATION & HUMAN ERROR VIOLATION INTERCEPTOR LOGIC
 * W.A.R.L.O.G. Warehouse OS - Skantha Solutions
 */

(function() {
    let activePalletId = null;
    let palletPollTimer = null;
    let violationPollTimer = null;
    let knownViolationIds = new Set();
    let audioContext = null;

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
            const violations = await res.json();
            
            // Update Topbar Badge
            const btn = document.getElementById('navViolationsBtn');
            const txt = document.getElementById('navViolationsCount');
            const count = violations.length;
            
            if (txt) txt.textContent = count;
            if (btn) {
                if (count > 0) {
                    btn.classList.add('has-violations');
                    btn.style.display = 'inline-flex';
                } else {
                    btn.classList.remove('has-violations');
                }
            }

            // Check if brand new high-severity violations occurred
            let hasNew = false;
            violations.forEach(v => {
                if (!knownViolationIds.has(v.id)) {
                    knownViolationIds.add(v.id);
                    hasNew = true;
                }
            });

            if (hasNew && violations.length > 0) {
                playViolationBuzzer();
                // Optionally show toast or notification
                if (typeof showToast === 'function') {
                    showToast(`🚨 Human Error Violation Intercepted: ${violations[0].violation_type}`, 'error');
                }
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
            const timeStr = new Date(v.created_at).toLocaleTimeString();
            return `
                <div class="violation-card severity-${(v.severity||'medium').toLowerCase()}">
                    <div class="violation-card-top">
                        <span class="violation-type-badge" style="background:${sevBg}; color:${sevColor}; border:1px solid ${sevColor};">
                            ${v.violation_type.replace(/_/g, ' ')}
                        </span>
                        <span>${timeStr}</span>
                    </div>
                    <div class="violation-card-title">${v.violation_type.replace(/_/g, ' ')}</div>
                    <div class="violation-card-desc">${v.details || 'Human error caught by Autonomous Vision pipeline.'}</div>
                    <div class="violation-card-meta">
                        ${v.pallet_id ? `<span>PLT: <b>${v.pallet_id}</b></span>` : ''}
                        ${v.bin_id ? `<span>BIN: <b>${v.bin_id}</b></span>` : ''}
                        ${v.sku_id ? `<span>SKU: <b>${v.sku_id}</b></span>` : ''}
                        ${v.camera_id ? `<span>CAM: <b>${v.camera_id}</b></span>` : ''}
                    </div>
                    <div style="margin-top:4px; display:flex; justify-content:flex-end;">
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
        const resolution = prompt(`Resolve Violation #${id} (${type})?\nEnter supervisor action or corrective note:`, 'Corrected physical placement in authorized bin.');
        if (!resolution) return;

        try {
            const res = await fetch(`/api/violations/${id}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ resolution_notes: resolution })
            });
            const data = await res.json();
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(`Violation #${id} resolved successfully.`, 'success');
                pollViolations();
            } else {
                alert(`Error: ${data.message}`);
            }
        } catch(e) {
            console.error('Resolution error:', e);
        }
    };

    // --------------------------------------------------------------------------
    // PALLETIZATION MANAGEMENT & BUNDLE COUNTER
    // --------------------------------------------------------------------------
    async function loadPallets() {
        try {
            const res = await fetch('/api/pallets');
            if (!res.ok) return;
            const pallets = await res.json();
            renderPalletTable(pallets);

            // If no active pallet selected, select the first OPEN/IN_PROGRESS pallet
            if (!activePalletId && pallets.length > 0) {
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
            const skus = await res.json();
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
            const bins = await res.json();
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
            const cams = await res.json();
            const select = document.getElementById('palletCameraSelect');
            if (!select) return;

            select.innerHTML = cams.map(c => {
                return `<option value="${c.camera_id}">${c.camera_id} - ${c.name} (${c.location || 'Palletizing Zone'})</option>`;
            }).join('');

            // On change, update stream feed
            select.onchange = function() {
                updateCameraStreamFeed(this.value);
            };

            if (cams.length > 0) {
                updateCameraStreamFeed(cams[0].camera_id);
            }
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
            const p = await res.json();
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
        const hudBundles = document.getElementById('hudPalletBundles');
        const hudPieces = document.getElementById('hudPalletPieces');
        const sealBtn = document.getElementById('btnSealPallet');

        const bundles = p.current_bundles || 0;
        const unitsPer = p.units_per_bundle || 1;
        const totalPcs = p.total_pieces || (bundles * unitsPer);
        const target = p.target_bundles || 1;
        const pct = Math.min(100, Math.round((bundles / target) * 100));

        if (idElem) idElem.textContent = p.pallet_id;
        if (skuElem) skuElem.textContent = `${p.sku_id} - ${p.sku_name || ''}`;
        if (bundleCountElem) bundleCountElem.textContent = bundles;
        if (unitsPerBundleElem) unitsPerBundleElem.textContent = unitsPer;
        if (totalPiecesElem) totalPiecesElem.textContent = totalPcs;
        if (targetBundlesElem) targetBundlesElem.textContent = target;
        if (barFill) barFill.style.width = `${pct}%`;
        if (hudBundles) hudBundles.textContent = `${bundles} / ${target}`;
        if (hudPieces) hudPieces.textContent = totalPcs;

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
            const bundles = p.current_bundles || 0;
            const target = p.target_bundles || 0;
            const unitsPer = p.units_per_bundle || 1;
            const total = p.total_pieces || (bundles * unitsPer);

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
                        <b>${bundles}</b> / ${target}
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
        const target = opt.getAttribute('data-target') || 50;

        const unitsInput = document.getElementById('newPalletUnitsPerBundle');
        const targetInput = document.getElementById('newPalletTargetBundles');
        if (unitsInput) unitsInput.value = units;
        if (targetInput) targetInput.value = target;
        window.calculateNewPalletTotalPreview();
    };

    window.calculateNewPalletTotalPreview = function() {
        const units = parseInt(document.getElementById('newPalletUnitsPerBundle')?.value || 0, 10);
        const target = parseInt(document.getElementById('newPalletTargetBundles')?.value || 0, 10);
        const preview = document.getElementById('newPalletTotalPiecesPreview');
        if (preview) {
            preview.textContent = `${target * units} Total Pieces (at ${target} bundles)`;
        }
    };

    window.handleCreatePalletSubmit = async function(e) {
        e.preventDefault();
        const palletId = document.getElementById('newPalletIdInput').value.trim();
        const skuId = document.getElementById('newPalletSkuSelect').value;
        const unitsPer = parseInt(document.getElementById('newPalletUnitsPerBundle').value, 10);
        const target = parseInt(document.getElementById('newPalletTargetBundles').value, 10);
        const binId = document.getElementById('newPalletBinSelect').value;

        if (!palletId || !skuId) {
            alert('Please specify a Pallet ID and select a target SKU.');
            return;
        }

        try {
            const res = await fetch('/api/pallets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    pallet_id: palletId,
                    sku_id: skuId,
                    units_per_bundle: unitsPer,
                    target_bundles: target,
                    assigned_bin_id: binId
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(`Pallet ${palletId} initiated. Autonomous counting active.`, 'success');
                window.closeNewPalletModal();
                activePalletId = palletId;
                loadPallets();
            } else {
                alert(`Error: ${data.message}`);
            }
        } catch(err) {
            console.error('Create pallet error:', err);
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
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(`Pallet ${targetId} SEALED successfully.`, 'success');
                loadPallets();
                // Prompt print label
                if (confirm(`Pallet sealed! Open and print Master Pallet QR label now?`)) {
                    window.printPalletMasterLabel(targetId);
                }
            } else {
                alert(`Error: ${data.message}`);
            }
        } catch(e) {
            console.error('Seal error:', e);
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
