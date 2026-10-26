/**
 * INDUSTRY BLUEPRINT & MULTI-FACILITY TRANSFORMER UI LOGIC
 * Skantha Autonomous WMS
 *
 * Provides:
 * 1. Multi-Warehouse Facility Switching & Context Management
 * 2. Pre-Defined Industry Blueprint Selection (Automotive, Beverage, Electronics, Pharma, Metals, 3PL)
 * 3. Custom AI Prompt Synthesis & Real-Time WMS Dataset Application
 */

(function () {
    let cachedWarehouses = [];
    let activeWarehouse = null;
    let cachedBlueprints = [];

    // =========================================================================
    // 1. FACILITY MANAGEMENT & TOPBAR CONTROLLER
    // =========================================================================

    async function loadWarehousesDropdown() {
        try {
            const res = await fetch('/api/warehouses');
            const data = await res.json();
            if (!data.success) return;

            cachedWarehouses = data.warehouses || [];
            activeWarehouse = data.active_warehouse || cachedWarehouses[0];

            renderFacilityDropdown();
            updateFacilityBadge();
            updateModalFacilityTarget();
        } catch (err) {
            console.error('[Industry Blueprint] Error fetching warehouses:', err);
        }
    }

    function renderFacilityDropdown() {
        const selectEl = document.getElementById('topbarFacilitySelect');
        if (!selectEl) return;

        selectEl.innerHTML = '';
        cachedWarehouses.forEach(wh => {
            const opt = document.createElement('option');
            opt.value = wh.code;
            opt.textContent = `${wh.code} (${wh.name} - ${wh.city})`;
            opt.style.background = '#0f172a';
            opt.style.color = '#f1f5f9';
            if (activeWarehouse && wh.code.toUpperCase() === activeWarehouse.code.toUpperCase()) {
                opt.selected = true;
            }
            selectEl.appendChild(opt);
        });
    }

    function updateFacilityBadge() {
        const badgeEl = document.getElementById('topbarFacilityBadge');
        if (!badgeEl || !activeWarehouse) return;

        const mode = (activeWarehouse.operating_mode || 'DEDICATED').toUpperCase();
        badgeEl.textContent = mode;
        if (mode === '3PL') {
            badgeEl.style.background = 'rgba(168, 85, 247, 0.2)';
            badgeEl.style.color = '#c084fc';
            badgeEl.style.borderColor = 'rgba(168, 85, 247, 0.4)';
            badgeEl.title = 'Commercial 3PL Multi-Tenant Hub (Client Partitioning Active)';
        } else {
            badgeEl.style.background = 'rgba(56, 189, 248, 0.2)';
            badgeEl.style.color = '#38bdf8';
            badgeEl.style.borderColor = 'rgba(56, 189, 248, 0.4)';
            badgeEl.title = 'Dedicated Enterprise Facility (Single Company Operations)';
        }
    }

    function updateModalFacilityTarget() {
        const displayEl = document.getElementById('blueprintTargetFacilityDisplay');
        if (displayEl && activeWarehouse) {
            displayEl.textContent = `${activeWarehouse.name} (${activeWarehouse.code}) - ${activeWarehouse.city}`;
        }
    }

    async function switchActiveFacility(warehouseCode) {
        if (!warehouseCode) return;
        try {
            const res = await fetch('/api/warehouses/switch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: warehouseCode })
            });
            const data = await res.json();
            if (data.success) {
                activeWarehouse = data.warehouse;
                updateFacilityBadge();
                updateModalFacilityTarget();
                showBlueprintToast(`Switched active facility to ${data.warehouse.name} (${data.warehouse.code})`, 'success');
                
                // Refresh core data in views
                if (typeof window.loadSKUs === 'function') window.loadSKUs();
                if (typeof window.loadBins === 'function') window.loadBins();
                if (typeof window.loadGatePasses === 'function') window.loadGatePasses();
                if (typeof window.loadExpectedDeliveries === 'function') window.loadExpectedDeliveries();
            } else {
                showBlueprintToast(`Failed to switch warehouse: ${data.error}`, 'error');
            }
        } catch (err) {
            console.error('[Industry Blueprint] Switch facility error:', err);
            showBlueprintToast('Network error switching facility', 'error');
        }
    }

    // =========================================================================
    // 2. BLUEPRINT MODAL CONTROLLER & PRESET RENDERING
    // =========================================================================

    function openIndustryBlueprintModal() {
        const modal = document.getElementById('industryBlueprintModal');
        if (!modal) return;
        modal.style.display = 'flex';
        updateModalFacilityTarget();
        loadIndustryBlueprints();
    }

    function closeIndustryBlueprintModal() {
        const modal = document.getElementById('industryBlueprintModal');
        if (modal) modal.style.display = 'none';
        const banner = document.getElementById('blueprintFeedbackBanner');
        if (banner) banner.style.display = 'none';
    }

    async function loadIndustryBlueprints() {
        const container = document.getElementById('blueprintCardsGrid');
        if (!container) return;

        if (cachedBlueprints.length > 0) {
            renderBlueprintCards(cachedBlueprints);
            return;
        }

        container.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: #94a3b8;">
                <i class="fas fa-circle-notch fa-spin fa-2x" style="color: #38bdf8; margin-bottom: 8px;"></i>
                <p>Loading AI Industry Blueprints Catalog...</p>
            </div>
        `;

        try {
            const res = await fetch('/api/industry_blueprints');
            const data = await res.json();
            if (data.success && data.blueprints) {
                cachedBlueprints = data.blueprints;
                renderBlueprintCards(cachedBlueprints);
            } else {
                container.innerHTML = `<div style="grid-column: 1 / -1; color:#ef4444;">Failed to load blueprints catalog.</div>`;
            }
        } catch (err) {
            console.error('[Industry Blueprint] Catalog load error:', err);
            container.innerHTML = `<div style="grid-column: 1 / -1; color:#ef4444;">Error connecting to Blueprint Engine.</div>`;
        }
    }

    function renderBlueprintCards(blueprints) {
        const container = document.getElementById('blueprintCardsGrid');
        if (!container) return;

        container.innerHTML = '';
        blueprints.forEach(bp => {
            const card = document.createElement('div');
            card.style.cssText = `
                background: rgba(30, 41, 59, 0.65);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 16px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                transition: all 0.25s ease;
                position: relative;
                overflow: hidden;
            `;

            card.onmouseenter = () => {
                card.style.borderColor = 'rgba(56, 189, 248, 0.5)';
                card.style.transform = 'translateY(-2px)';
                card.style.boxShadow = '0 10px 25px -5px rgba(56, 189, 248, 0.15)';
            };
            card.onmouseleave = () => {
                card.style.borderColor = 'rgba(255, 255, 255, 0.1)';
                card.style.transform = 'none';
                card.style.boxShadow = 'none';
            };

            const sampleSkusList = (bp.sample_skus || []).slice(0, 3).map(s => `<span style="background:rgba(255,255,255,0.06); padding:2px 6px; border-radius:4px; font-size:0.72rem; color:#cbd5e1;">${s}</span>`).join(' ');

            card.innerHTML = `
                <div>
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                        <span style="font-size:1.8rem;">${bp.icon || '📦'}</span>
                        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase; padding:3px 8px; border-radius:4px; background:rgba(56,189,248,0.15); color:#38bdf8; border:1px solid rgba(56,189,248,0.3);">
                            ${bp.mode || 'DEDICATED'}
                        </span>
                    </div>
                    <h4 style="margin:0 0 4px 0; font-size:0.95rem; font-weight:700; color:#f8fafc;">${bp.name}</h4>
                    <p style="margin:0 0 10px 0; font-size:0.78rem; color:#94a3b8; line-height:1.35;">${bp.description}</p>
                    
                    <div style="display:flex; flex-wrap:wrap; gap:4px; margin-bottom:12px;">
                        ${sampleSkusList}
                    </div>

                    <div style="font-size:0.73rem; color:#64748b; margin-bottom:14px; display:flex; align-items:center; gap:8px;">
                        <span><i class="fas fa-barcode" style="color:#38bdf8;"></i> ${bp.sku_count || 4} SKUs</span>
                        <span>&bull;</span>
                        <span><i class="fas fa-camera" style="color:#a855f7;"></i> ${bp.vision_classes_count || 6} Vision Classes</span>
                        <span>&bull;</span>
                        <span><i class="fas fa-layer-group" style="color:#10b981;"></i> ${bp.zones_count || 4} Zones</span>
                    </div>
                </div>

                <button type="button" class="btn-apply-blueprint" style="width:100%; padding:8px 12px; background:linear-gradient(135deg, #0284c7, #2563eb); border:none; border-radius:8px; color:#ffffff; font-weight:700; font-size:0.8rem; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:6px; transition:all 0.2s ease;">
                    <i class="fas fa-check"></i> Apply This Blueprint
                </button>
            `;

            const btn = card.querySelector('.btn-apply-blueprint');
            btn.onclick = () => applyIndustryBlueprint(bp.key);
            container.appendChild(card);
        });
    }

    // =========================================================================
    // 3. APPLY BLUEPRINT ACTION (PRESET OR CUSTOM)
    // =========================================================================

    async function applyIndustryBlueprint(key, customPrompt = '') {
        const banner = document.getElementById('blueprintFeedbackBanner');
        const targetMode = document.getElementById('blueprintApplyTargetSelect')?.value || 'CURRENT';
        
        let targetWhCode = (activeWarehouse && activeWarehouse.code) ? activeWarehouse.code : 'WH-MAIN';
        if (targetMode === 'NEW') {
            targetWhCode = ''; // Service will create a dedicated new facility
        }

        if (banner) {
            banner.style.display = 'block';
            banner.style.background = 'rgba(56, 189, 248, 0.15)';
            banner.style.border = '1px solid rgba(56, 189, 248, 0.3)';
            banner.style.color = '#38bdf8';
            banner.innerHTML = `
                <div style="display:flex; align-items:center; gap:10px;">
                    <i class="fas fa-circle-notch fa-spin"></i>
                    <span>Applying blueprint dataset: generating procedural SKUs, vector thumbnail badges, zero-shot AI vision classes, and zone mapping...</span>
                </div>
            `;
        }

        try {
            const payload = {
                blueprint_key: key || '',
                warehouse_code: targetWhCode,
                custom_prompt: customPrompt || ''
            };

            const res = await fetch('/api/industry_blueprints/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (data.success) {
                if (banner) {
                    banner.style.background = 'rgba(16, 185, 129, 0.15)';
                    banner.style.border = '1px solid rgba(16, 185, 129, 0.4)';
                    banner.style.color = '#34d399';
                    banner.innerHTML = `
                        <div style="display:flex; align-items:center; justify-content:space-between;">
                            <div>
                                <i class="fas fa-circle-check" style="margin-right:6px;"></i>
                                <b>Success!</b> ${data.message}
                                <div style="font-size:0.78rem; color:#a7f3d0; margin-top:4px;">
                                    Facility: <b>${data.warehouse ? data.warehouse.name : targetWhCode}</b> &bull; Added ${data.skus_created || 0} SKUs, ${data.classes_created || 0} Vision Classes, ${data.zones_created || 0} Storage Zones, ${data.deliveries_created || 0} Inbound Shipments.
                                </div>
                            </div>
                            <button type="button" onclick="closeIndustryBlueprintModal()" style="background:#10b981; border:none; color:#ffffff; padding:4px 10px; border-radius:6px; font-weight:700; cursor:pointer; font-size:0.75rem;">
                                Done
                            </button>
                        </div>
                    `;
                }

                showBlueprintToast(`✨ ${data.message}`, 'success');

                // Refresh warehouses list and active warehouse
                await loadWarehousesDropdown();

                // Trigger reload of SKU Master and other views
                if (typeof window.loadSKUs === 'function') window.loadSKUs();
                if (typeof window.loadBins === 'function') window.loadBins();
                if (typeof window.loadGatePasses === 'function') window.loadGatePasses();
                if (typeof window.loadExpectedDeliveries === 'function') window.loadExpectedDeliveries();
                if (typeof window.renderAllVisionCameras === 'function') window.renderAllVisionCameras();
                
                // If user is currently in SKU Master tab, trigger refresh
                const skuTabBtn = document.querySelector('[data-tab="sku-master"]');
                if (skuTabBtn && skuTabBtn.classList.contains('active')) {
                    if (typeof window.loadSkuMasterTable === 'function') window.loadSkuMasterTable();
                }

            } else {
                if (banner) {
                    banner.style.background = 'rgba(239, 68, 68, 0.15)';
                    banner.style.border = '1px solid rgba(239, 68, 68, 0.4)';
                    banner.style.color = '#f87171';
                    banner.innerHTML = `<i class="fas fa-triangle-exclamation"></i> Error: ${data.error || 'Failed to apply blueprint'}`;
                }
                showBlueprintToast(`Error: ${data.error}`, 'error');
            }
        } catch (err) {
            console.error('[Industry Blueprint] Apply error:', err);
            if (banner) {
                banner.style.background = 'rgba(239, 68, 68, 0.15)';
                banner.style.border = '1px solid rgba(239, 68, 68, 0.4)';
                banner.style.color = '#f87171';
                banner.innerHTML = `<i class="fas fa-triangle-exclamation"></i> Network error applying blueprint`;
            }
            showBlueprintToast('Network communication error', 'error');
        }
    }

    function applyCustomIndustryBlueprint() {
        const input = document.getElementById('customIndustryInput');
        if (!input) return;
        const text = input.value.trim();
        if (!text) {
            showBlueprintToast('Please enter an industry or company description.', 'warning');
            input.focus();
            return;
        }
        applyIndustryBlueprint('custom', text);
    }

    // =========================================================================
    // 4. TOAST NOTIFICATION UTILITY
    // =========================================================================

    function showBlueprintToast(msg, type = 'info') {
        let toastContainer = document.getElementById('blueprintToastContainer');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'blueprintToastContainer';
            toastContainer.style.cssText = `
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 100000;
                display: flex;
                flex-direction: column;
                gap: 8px;
                pointer-events: none;
            `;
            document.body.appendChild(toastContainer);
        }

        const toast = document.createElement('div');
        const bg = type === 'success' ? '#065f46' : type === 'error' ? '#991b1b' : '#1e293b';
        const border = type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#38bdf8';
        const icon = type === 'success' ? 'fa-circle-check' : type === 'error' ? 'fa-triangle-exclamation' : 'fa-circle-info';

        toast.style.cssText = `
            background: ${bg};
            border: 1px solid ${border};
            color: #ffffff;
            padding: 10px 16px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            pointer-events: auto;
            opacity: 0;
            transform: translateY(10px);
            transition: all 0.25s ease;
        `;
        toast.innerHTML = `<i class="fas ${icon}"></i> <span>${msg}</span>`;
        toastContainer.appendChild(toast);

        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px)';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // =========================================================================
    // 5. GLOBAL EXPORTS & INITIALIZATION
    // =========================================================================

    window.openIndustryBlueprintModal = openIndustryBlueprintModal;
    window.closeIndustryBlueprintModal = closeIndustryBlueprintModal;
    window.applyIndustryBlueprint = applyIndustryBlueprint;
    window.applyCustomIndustryBlueprint = applyCustomIndustryBlueprint;
    window.switchActiveFacility = switchActiveFacility;
    window.loadWarehousesDropdown = loadWarehousesDropdown;

    document.addEventListener('DOMContentLoaded', () => {
        loadWarehousesDropdown();
    });

})();
