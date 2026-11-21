/*
 * WARLOG frontend gating (RBAC Phase 6).
 *
 * Hides menus, screens and buttons the signed-in person may not use, so nobody clicks
 * something only to be refused. This is a convenience only: every API still checks the
 * permission itself.
 *
 *   window.hasPerm('gate.pass.view')            one permission
 *   window.hasPerm('gate.pass.view|dock.view')  any of several
 *   <button data-perm="sku.create">             hidden unless allowed (works for content added later)
 *
 * People who hold every company permission (Company Admin, Platform Admin) skip all of this:
 * nothing is hidden for them, so the existing screens stay exactly as they were.
 *
 * Also here: the read-only "All locations" view, a small toast for refused actions, and
 * clearing the previous person's browser data on a shared PC (H21).
 */
(function () {
    'use strict';

    const ACCESS = Object.assign({ permissions: [], all: false, is_platform_admin: false, scope: null, company_wide: false },
                                 window.WARLOG_ACCESS || {});
    let perms = new Set(ACCESS.permissions || []);

    function hasPerm(expr) {
        if (!expr) return true;
        return String(expr).split('|').some(k => {
            k = k.trim();
            if (!k) return false;
            if (k.startsWith('platform.')) return !!ACCESS.is_platform_admin;
            return ACCESS.all || perms.has(k);
        });
    }
    window.hasPerm = hasPerm;
    window.warlogAccess = () => ACCESS;

    // ------------------------------------------------------------------ toast
    function toast(text, kind) {
        let box = document.getElementById('warlogToastStack');
        if (!box) {
            box = document.createElement('div');
            box.id = 'warlogToastStack';
            box.className = 'wl-toast-stack';
            box.setAttribute('role', 'status');
            box.setAttribute('aria-live', 'polite');
            document.body.appendChild(box);
        }
        const t = document.createElement('div');
        t.className = 'wl-toast wl-toast-' + (kind || 'info');
        const icon = { success: 'fa-circle-check', error: 'fa-circle-xmark', warning: 'fa-triangle-exclamation' }[kind] || 'fa-circle-info';
        t.innerHTML = `<i class="fas ${icon}"></i><span></span>`;
        t.querySelector('span').textContent = String(text || '');
        box.appendChild(t);
        setTimeout(() => { t.classList.add('wl-toast-out'); setTimeout(() => t.remove(), 300); }, 4200);
    }
    window.warlogToast = toast;

    // ------------------------------------------------------------------ what needs which permission
    // Left menu / mobile dock modules and their screens
    const MODULE_RULES = {
        'dashboard': 'dashboard.view',
        'deliveries': 'deliveries.view',
        'gate-passes': 'gate.dashboard.view|gate.pass.view',
        'docks': 'dock.view',
        'ai-vision': 'vision.view',
        'ai-vision-master': 'vision.view',
        'cameras': 'cameras.view',
        'inbound-flow': 'inbound.view',
        'outbound': 'outbound.view',
        'palletization': 'pallet.view',
        'inventory': 'inventory.view',
        'warehouses': 'warehouses.view',
        'master-hub': 'sku.view|bins.view|inventory.view|deliveries.view|gate.pass.view|cyclecount.view|vision.view',
        'copilot': 'copilot.use',
        'users-access': 'users.view',
        'platform-companies': 'platform.companies.manage',
    };

    // Buttons, by the function their onclick calls
    const ACTION_RULES = {
        // warehouses & templates
        openAddFacilityModal: 'warehouses.manage',
        openIndustryBlueprintModal: 'masterdata.blueprint.apply',
        applyCustomIndustryBlueprint: 'masterdata.blueprint.apply',
        // people & roles
        openInviteModal: 'users.invite',
        openCreateCompanyModal: 'platform.companies.manage',
        // master data
        openAddSkuModal: 'sku.create', submitAddSku: 'sku.create', 'window.submitAddSku': 'sku.create',
        openExcelUploadModal: 'sku.import', submitExcelPreview: 'sku.import', executeExcelImport: 'sku.import',
        commitBulkImageUpload: 'sku.edit', saveWorkbenchBundleConfigToSku: 'sku.edit',
        'window.quickSaveBundleDeclaration': 'sku.edit',
        openAddBinModal: 'bins.create', openEditBinModal: 'bins.edit', 'window.openEditBinModal': 'bins.edit',
        quickExpandBinSize: 'bins.edit',
        openTransferInventoryModal: 'inventory.transfer',
        commitSelectedCycleCount: 'cyclecount.execute',
        // deliveries
        openEditDelivery: 'deliveries.edit', deleteDelivery: 'deliveries.delete', exportDeliveriesCSV: 'reports.export',
        // gate
        registerNewWalkInVehiclePrompt: 'gate.vehicle.register', createManualPass: 'gate.vehicle.register',
        autoRegisterWalkInCard: 'gate.vehicle.register',
        updatePass: 'gate.vehicle.edit', saveEditedPlateAndSnapshot: 'gate.vehicle.edit',
        promptEditPlateAndSnapshot: 'gate.vehicle.edit',
        snapTruckPhotoManual: 'gate.anpr.execute', retakePhoto: 'gate.anpr.execute',
        captureDriverPhoto: 'gate.anpr.execute', manualSnapshot: 'gate.anpr.execute',
        verifyOtp: 'gate.otp.verify',
        quickAdmitExpectedPO: 'gate.entry.approve', 'window.admitExpectedDelivery': 'gate.entry.approve',
        approveAllMatchedPasses: 'gate.entry.bulk_approve',
        deletePass: 'gate.override.manual',
        checkout: 'gate.checkout.complete',
        sendInvoice: 'gate.documents.export', downloadGateManifest: 'gate.documents.export',
        simulateGateArrivalPrompt: 'gate.devices.configure', simulateInboundArrival: 'gate.devices.configure',
        // dock & inbound
        updateDockStatus: 'dock.unload.execute', completeUnload: 'dock.unload.execute',
        scanPackages: 'dock.unload.execute', manualAddPackages: 'dock.unload.execute',
        completeInboundReceipt: 'inbound.receipt.complete',
        configureStagingQuota: 'inbound.staging.configure', resetStagingZone: 'inbound.staging.reset',
        // outbound & pallets
        pickOutboundOrder: 'outbound.dispatch',
        assignOutboundTruck: 'outbound.dispatch',
        openNewPalletModal: 'pallet.create',
        // vision
        executeWorkbenchCount: 'vision.counting.execute', executePieceCount: 'vision.counting.execute',
        executeBundleCount: 'vision.counting.execute', approveWorkbenchSession: 'vision.counting.review',
        openAddZoneModal: 'vision.zones.manage', saveCurrentRoi: 'vision.zones.manage',
        openAddObjectClassModal: 'vision.classes.manage',
        saveVisionConfig: 'vision.runtime.configure', resetVisionConfig: 'vision.runtime.configure',
        startAllRuntimeCameras: 'vision.runtime.configure', stopAllRuntimeCameras: 'vision.runtime.configure',
        handleDashboardStartAll: 'vision.runtime.configure', handleDashboardStopAll: 'vision.runtime.configure',
        handleDashboardRestartCurrentCamera: 'vision.runtime.configure',
        // cameras
        deleteCamera: 'cameras.delete', transitionViewToConfigure: 'cameras.configure',
        promptAssignCameraBin: 'cameras.configure', syncCameraToBin: 'cameras.configure',
        ptzMove: 'cameras.ptz.control', ptzSetZoom: 'cameras.ptz.control', ptzZoomDelta: 'cameras.ptz.control',
        ptzReset: 'cameras.ptz.control', togglePtzPanel: 'cameras.ptz.control',
        // workers & violations
        openTrainWorkerModal: 'workers.enroll', submitTrainWorkerLive: 'workers.enroll',
        deleteTrainedWorker: 'workers.delete',
        'window.resolveAllViolations': 'violations.manage',
        // AI Copilot (launcher, dock button; the keyboard shortcut is guarded below)
        toggleCopilot: 'copilot.use',
    };

    // Buttons whose onclick contains these exact calls (sub-tabs)
    const CALL_RULES = [
        ["switchCameraSubTab('settings')", 'cameras.create'],
        ["switchSubTab('po-master'", 'deliveries.view'],
        ["switchSubTab('gate-pass-master'", 'gate.pass.view'],
        ["switchSubTab('vehicle-master'", 'gate.vehicle_log.view'],
        ["switchSubTab('invoice-master'", 'gate.documents.export'],
        ["switchSubTab('bin-master'", 'bins.view'],
        ["switchSubTab('sku-master'", 'sku.view'],
        ["switchSubTab('cycle-count'", 'cyclecount.view'],
        ["switchSubTab('inventory-master'", 'inventory.view'],
        ["switchSubTab('vision-objects'", 'vision.view'],
        ["switchSubTab('vision-zones'", 'vision.view'],
    ];

    const SKIP_CALLS = new Set(['if', 'event.stopPropagation', 'this.parentElement.remove', 'document.getElementById',
                                'navigator.clipboard.writeText', 'return']);

    function ruleForOnclick(code) {
        for (const [needle, perm] of CALL_RULES) if (code.includes(needle)) return perm;
        const calls = code.matchAll(/([A-Za-z_$][\w.$]*)\s*\(/g);
        for (const m of calls) {
            const name = m[1];
            if (SKIP_CALLS.has(name)) continue;
            if (ACTION_RULES[name]) return ACTION_RULES[name];
            const short = name.replace(/^window\./, '');
            if (ACTION_RULES[short]) return ACTION_RULES[short];
            if (name.startsWith('switchTab') || name === 'mobileDockSwitchTab') {
                const arg = code.match(/(?:switchTab|mobileDockSwitchTab)\(\s*['"]([\w-]+)['"]/);
                if (arg && MODULE_RULES[arg[1]]) return MODULE_RULES[arg[1]];
            }
            return null;   // only the first real call decides
        }
        return null;
    }

    function setVisible(el, ok) {
        if (ok) {
            if (el.classList.contains('perm-hidden')) el.classList.remove('perm-hidden');
        } else if (!el.classList.contains('perm-hidden')) {
            el.classList.add('perm-hidden');
        }
    }

    function gateElement(el) {
        let rule = el.getAttribute('data-perm');
        if (!rule && el.hasAttribute('onclick')) rule = ruleForOnclick(el.getAttribute('onclick') || '');
        if (rule) setVisible(el, hasPerm(rule));
    }

    function applyGating(root) {
        root = root || document;
        // menu modules + mobile dock + screens
        root.querySelectorAll('.macos-dock-item[data-module]').forEach(el => {
            const rule = MODULE_RULES[el.getAttribute('data-module')];
            if (rule) setVisible(el, hasPerm(rule));
        });
        root.querySelectorAll('.mobile-nav-item[data-tab]').forEach(el => {
            const rule = MODULE_RULES[el.getAttribute('data-tab')];
            if (rule) setVisible(el, hasPerm(rule));
        });
        Object.keys(MODULE_RULES).forEach(m => {
            const view = document.getElementById(m + '-view');
            if (view && (root === document || root.contains(view))) setVisible(view, hasPerm(MODULE_RULES[m]));
        });
        root.querySelectorAll('[data-perm], [onclick]').forEach(gateElement);
        if (root.nodeType === 1 && (root.hasAttribute('data-perm') || root.hasAttribute('onclick'))) gateElement(root);
        if (root === document) tidySeparators();
    }

    // no divider lines left over where whole groups of the menu are hidden
    function tidySeparators() {
        const list = document.querySelector('.macos-dock-list');
        if (!list) return;
        let seenItem = false, lastSep = null;
        Array.from(list.children).forEach(el => {
            if (el.classList.contains('dock-separator')) {
                setVisible(el, seenItem);
                if (seenItem) lastSep = el;
                seenItem = false;
            } else if (!el.classList.contains('perm-hidden') && el.offsetParent !== null) {
                seenItem = true;
                lastSep = null;
            }
        });
        if (lastSep) setVisible(lastSep, false);
    }

    function firstAllowedModule() {
        const order = ['dashboard', 'gate-passes', 'docks', 'deliveries', 'inbound-flow', 'outbound', 'palletization',
                       'inventory', 'ai-vision', 'cameras', 'master-hub', 'warehouses', 'users-access'];
        return order.find(m => hasPerm(MODULE_RULES[m]) && document.getElementById(m + '-view')) || null;
    }

    function guardNavigation() {
        const original = window.switchTab;
        if (typeof original !== 'function' || original.__warlogGuarded) return;
        const guarded = function (tabId) {
            const rule = MODULE_RULES[tabId];
            if (rule && !hasPerm(rule)) {
                toast("You don't have access to that screen.", 'warning');
                return;
            }
            return original.apply(this, arguments);
        };
        guarded.__warlogGuarded = true;
        window.switchTab = guarded;
    }

    function guardCopilot() {
        const original = window.toggleCopilot;
        if (typeof original !== 'function' || original.__warlogGuarded || hasPerm('copilot.use')) return;
        const guarded = function () { toast("You don't have access to the AI Copilot.", 'warning'); };
        guarded.__warlogGuarded = true;
        window.toggleCopilot = guarded;
    }

    function ensureAllowedScreen() {
        const active = document.querySelector('.view-section.active');
        const id = active ? active.id.replace(/-view$/, '') : 'dashboard';
        const rule = MODULE_RULES[id];
        if (rule && !hasPerm(rule)) {
            const next = firstAllowedModule();
            if (next && typeof window.switchTab === 'function') window.switchTab(next);
            else if (!next) showNoAccess();
        }
    }

    function showNoAccess() {
        if (document.getElementById('wlNoAccess')) return;
        const box = document.createElement('div');
        box.id = 'wlNoAccess';
        box.className = 'wl-noaccess';
        box.innerHTML = `<div class="wl-noaccess-card"><i class="fas fa-user-lock"></i>
            <h2>No screens assigned yet</h2>
            <p>Your account is active, but your role doesn't open any screen at this location. Ask your company admin to give you a role.</p>
            <button type="button" class="wl-noaccess-btn" onclick="doLogout()">Sign out</button></div>`;
        document.body.appendChild(box);
    }

    // ------------------------------------------------------------------ dynamic content
    let pending = [];
    let scheduled = false;
    function watch() {
        const mo = new MutationObserver(records => {
            for (const r of records) r.addedNodes.forEach(n => { if (n.nodeType === 1) pending.push(n); });
            if (pending.length && !scheduled) {
                scheduled = true;
                requestAnimationFrame(() => {
                    const nodes = pending; pending = []; scheduled = false;
                    nodes.forEach(n => { if (n.isConnected) applyGating(n); });
                });
            }
        });
        mo.observe(document.body, { childList: true, subtree: true });
    }

    // ------------------------------------------------------------------ warehouse picker: "All locations (view only)"
    const ALL = '__ALL__';
    function decoratePicker() {
        const sel = document.getElementById('topbarFacilitySelect');
        if (!sel || ACCESS.is_platform_admin || !ACCESS.company_wide) return;
        const sync = () => {
            if (sel.options.length < 2 || sel.querySelector(`option[value="${ALL}"]`)) return;
            const opt = document.createElement('option');
            opt.value = ALL;
            opt.textContent = 'All locations (view only)';
            sel.insertBefore(opt, sel.firstChild);
            if (ACCESS.scope === 'company_all') opt.selected = true;
        };
        new MutationObserver(sync).observe(sel, { childList: true });
        sync();
    }

    // Changing the location in the top bar reloads the page, so every screen (dashboard,
    // cameras, inventory, gate, ...) shows the new location's data; the open screen is kept.
    const RETURN_KEY = 'warlog_return_view';
    function reloadForLocation(label) {
        try {
            const active = document.querySelector('.view-section.active');
            sessionStorage.setItem(RETURN_KEY, JSON.stringify({
                tab: active && active.id ? active.id.replace(/-view$/, '') : '',
                label: label || '',
            }));
        } catch (e) {}
        window.location.reload();
    }
    function pickerLabel(code) {
        const sel = document.getElementById('topbarFacilitySelect');
        const opt = sel ? Array.from(sel.options).find(o => o.value === code) : null;
        return opt ? opt.textContent.trim() : '';
    }
    function restoreAfterLocationChange() {
        let saved = null;
        try {
            saved = JSON.parse(sessionStorage.getItem(RETURN_KEY) || 'null');
            sessionStorage.removeItem(RETURN_KEY);
        } catch (e) {}
        if (!saved) return;
        setTimeout(() => {
            if (saved.tab && saved.tab !== 'dashboard' && document.getElementById(saved.tab + '-view')
                && hasPerm(MODULE_RULES[saved.tab]) && typeof window.switchTab === 'function') {
                window.switchTab(saved.tab);
            }
            if (saved.label) toast('Now working in ' + saved.label, 'success');
        }, 600);
    }

    function wrapFacilitySwitch() {
        const original = window.switchActiveFacility;
        if (typeof original !== 'function' || original.__warlogWrapped) return;
        const wrapped = async function (code, silent) {
            if (code === ALL) {
                window.warlogSetTabWarehouse && window.warlogSetTabWarehouse('all');
                reloadForLocation('all locations (view only)');
                return;
            }
            const leavingAll = ACCESS.scope === 'company_all';
            const before = window.warlogTabWarehouse ? window.warlogTabWarehouse() : '';
            const out = await original.apply(this, arguments);
            const after = window.warlogTabWarehouse ? window.warlogTabWarehouse() : '';
            // a person picked a different location (automatic switches pass silent = true)
            if (leavingAll || (!silent && after && after !== before)) {
                reloadForLocation(pickerLabel(code));
                return out;
            }
            refreshAccess();
            return out;
        };
        wrapped.__warlogWrapped = true;
        window.switchActiveFacility = wrapped;
    }

    function readOnlyBanner() {
        if (ACCESS.scope !== 'company_all' || document.getElementById('wlReadOnlyBanner')) return;
        const b = document.createElement('div');
        b.id = 'wlReadOnlyBanner';
        b.className = 'wl-readonly-banner';
        b.innerHTML = '<i class="fas fa-eye"></i><span>You are viewing <b>all locations</b>. This view is read-only &mdash; pick one location in the top bar to make changes.</span>';
        document.body.appendChild(b);
        document.body.classList.add('wl-readonly');
    }

    // permissions depend on the location (a role can be given per location)
    async function refreshAccess() {
        try {
            const res = await fetch('/api/auth/me');
            if (!res.ok) return;
            const d = await res.json();
            if (!d.access) return;
            Object.assign(ACCESS, d.access);
            perms = new Set(ACCESS.permissions || []);
            applyGating(document);
            ensureAllowedScreen();
        } catch (e) { /* keep the current view */ }
    }
    window.warlogRefreshAccess = refreshAccess;

    // ------------------------------------------------------------------ shared-PC hygiene (H21)
    // Device preferences survive; anything about the previous person does not.
    const KEEP_KEYS = new Set(['warlog_theme', 'skantha_theme', 'warlog_dock_collapsed', 'warlog_copilot_voice_muted',
                               'skandha_vision_config', 'warlog_last_user',
                               'warlog_remember_username']);   // login page "Remember me" (username only)
    function clearUserStorage() {
        try {
            Object.keys(localStorage).forEach(k => { if (!KEEP_KEYS.has(k)) localStorage.removeItem(k); });
        } catch (e) {}
        try { sessionStorage.clear(); } catch (e) {}
    }
    window.warlogClearUserStorage = clearUserStorage;

    function checkUserChange() {
        const me = (window.currentUser && window.currentUser.username) || '';
        let last = '';
        try { last = localStorage.getItem('warlog_last_user') || ''; } catch (e) {}
        if (me && last && last !== me) {
            const wh = (() => { try { return sessionStorage.getItem('warlog_warehouse_id'); } catch (e) { return null; } })();
            clearUserStorage();
            // the page was rendered for this person: keep their tab location
            if (wh && window.warlogSetTabWarehouse) window.warlogSetTabWarehouse(wh);
        }
        try { if (me) localStorage.setItem('warlog_last_user', me); } catch (e) {}
    }

    function wrapLogout() {
        const original = window.doLogout;
        if (typeof original !== 'function' || original.__warlogWrapped) return;
        const wrapped = function () {
            clearUserStorage();
            try { localStorage.removeItem('warlog_last_user'); } catch (e) {}
            return original.apply(this, arguments);
        };
        wrapped.__warlogWrapped = true;
        window.doLogout = wrapped;
    }

    // ------------------------------------------------------------------ start
    checkUserChange();
    function start() {
        wrapLogout();
        readOnlyBanner();
        decoratePicker();
        wrapFacilitySwitch();
        restoreAfterLocationChange();
        const bp = document.getElementById('topbarBlueprintBtn');
        if (bp) bp.style.display = hasPerm('masterdata.blueprint.apply') ? 'inline-flex' : 'none';
        if (ACCESS.all && ACCESS.scope !== 'company_all') return;   // nothing to hide
        applyGating(document);
        guardNavigation();
        guardCopilot();
        ensureAllowedScreen();
        watch();
    }
    if (document.readyState === 'complete') start();
    else window.addEventListener('load', start);
})();
