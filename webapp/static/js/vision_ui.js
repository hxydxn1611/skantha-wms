
                    function switchVisionSubTab(tabId, btn) {
                        document.querySelectorAll('.vision-sub-section').forEach(el => el.style.display = 'none');
                        document.querySelectorAll('.vision-sub-btn').forEach(el => el.classList.remove('active'));
                        const target = document.getElementById(tabId + '-sub');
                        if (target) target.style.display = 'block';
                        if (btn) btn.classList.add('active');
                        if (tabId === 'vision-dashboard') {
                            if (typeof initLiveVisionDashboard === 'function') initLiveVisionDashboard();
                        } else {
                            if (typeof stopLiveVisionDashboardPolling === 'function') stopLiveVisionDashboardPolling();
                        }
                        if (tabId === 'vision-objects') fetchObjectClasses();
                        if (tabId === 'vision-cameras') fetchVisionCameras();
                        if (tabId === 'vision-zones') fetchVisionZones();
                        if (tabId === 'vision-detection') initDetectionTestUI();
                        if (tabId === 'vision-tracking') initTrackingTestUI();
                        if (tabId === 'vision-identity') initIdentityTestUI();
                        if (tabId === 'vision-validation') initValidationTestUI();
                        if (tabId === 'vision-association') initAssociationTestUI();
                        if (tabId === 'vision-worker-box') initWorkerBoxTestUI();
                        if (tabId === 'vision-box-bin') initBoxBinTestUI();
                        if (tabId === 'vision-material-association') initMaterialAssociationTestUI();
                        if (tabId === 'vision-events') initMovementEventsTestUI();
                        if (tabId === 'vision-traceability') initMaterialTraceabilityUI();
                        if (tabId === 'vision-runtime') initVisionRuntimeUI();
                    }

                    // Object Classes Manager State
                    let globalObjectClasses = [];
                    let currentViewedObjId = null;

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

                    function showObjectClassAlert(message, type = 'success') {
                        const alertBox = document.getElementById('objClassAlertBox');
                        const msgEl = document.getElementById('objClassAlertMsg');
                        if (!alertBox || !msgEl) return;
                        msgEl.innerText = message;
                        if (type === 'success') {
                            alertBox.style.background = '#dcfce7';
                            alertBox.style.color = '#15803d';
                            alertBox.style.border = '1px solid #bbf7d0';
                        } else {
                            alertBox.style.background = '#fee2e2';
                            alertBox.style.color = '#b91c1c';
                            alertBox.style.border = '1px solid #fecaca';
                        }
                        alertBox.style.display = 'flex';
                        setTimeout(() => {
                            hideObjectClassAlert();
                        }, 5000);
                    }

                    function hideObjectClassAlert() {
                        const alertBox = document.getElementById('objClassAlertBox');
                        if (alertBox) alertBox.style.display = 'none';
                    }

                    async function fetchObjectClasses() {
                        const search = (document.getElementById('objClassSearchInput')?.value || '').trim();
                        const status = document.getElementById('objClassStatusFilter')?.value || 'ALL';

                        let url = '/api/object_classes';
                        const params = [];
                        if (search) params.push('search=' + encodeURIComponent(search));
                        if (status && status !== 'ALL') params.push('status=' + encodeURIComponent(status));
                        if (params.length > 0) url += '?' + params.join('&');

                        try {
                            const res = await fetch(url);
                            if (res.ok) {
                                const data = await res.json();
                                if (Array.isArray(data)) {
                                    globalObjectClasses = data;
                                }
                            }
                        } catch(e) {
                            console.warn("Failed to fetch object classes:", e);
                        }

                        renderObjectClasses(globalObjectClasses);
                        updateActiveClassKPI();
                    }

                    function updateActiveClassKPI() {
                        const kpiEl = document.getElementById('kpi-vision-objects');
                        if (kpiEl && Array.isArray(globalObjectClasses)) {
                            const activeCount = globalObjectClasses.filter(c => c.status === 'Active').length;
                            kpiEl.innerText = activeCount;
                        }
                    }

                    function renderObjectClasses(classes) {
                        const tbody = document.getElementById('objectClassesBody');
                        const counter = document.getElementById('objClassCountBadge');
                        if (!tbody) return;

                        const totalCount = classes ? classes.length : 0;
                        if (counter) {
                            counter.innerText = `Showing ${totalCount} class${totalCount === 1 ? '' : 'es'}`;
                        }

                        if (!classes || classes.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="8" style="text-align:center; color:var(--text-muted); padding:2.5rem 1rem;">
                                        <div style="font-size:1.1rem; font-weight:700; color:var(--text-main); margin-bottom:4px;">No Object Classes Found</div>
                                        <div style="font-size:0.85rem;">Try modifying your search or status filter, or click "+ Add Object Class" above.</div>
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = classes.map(c => {
                            const isActive = c.status === 'Active';
                            const badgeHtml = isActive 
                                ? '<span class="badge active-status">Active</span>' 
                                : '<span class="badge disabled-status">Disabled</span>';
                            const toggleText = isActive ? 'Disable' : 'Enable';
                            const toggleClass = isActive ? 'btn-warning' : 'btn-primary';
                            const safeCode = escapeHtml(c.code);
                            const safeName = escapeHtml(c.name);
                            const safeDesc = escapeHtml(c.description || '-');
                            const safeCreated = escapeHtml(c.created_at || '-');
                            const safeUpdated = escapeHtml(c.updated_at || '-');

                            return `
                                <tr>
                                    <td style="text-align:center; font-family:monospace; font-weight:700; color:var(--text-muted); font-size:0.85rem;">#${c.id}</td>
                                    <td>
                                        <code style="font-size:0.92rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.08); padding:3px 7px; border-radius:4px; letter-spacing:0.5px;">${safeCode}</code>
                                    </td>
                                    <td><strong style="color:var(--text-main); font-size:0.92rem;">${safeName}</strong></td>
                                    <td style="color:var(--text-muted); font-size:0.85rem; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${safeDesc}">${safeDesc}</td>
                                    <td style="text-align:center;">${badgeHtml}</td>
                                    <td style="font-family:monospace; font-size:0.78rem; color:var(--text-muted);">${safeCreated}</td>
                                    <td style="font-family:monospace; font-size:0.78rem; color:var(--text-muted);">${safeUpdated}</td>
                                    <td style="text-align:center; white-space:nowrap;">
                                        <button type="button" class="btn-primary btn-sm" style="background:var(--panel-subtle); color:var(--text-main); border:1px solid var(--border-light);" onclick="openViewObjectClassModal(${c.id})" title="View Details">
                                            👁 View
                                        </button>
                                        <button type="button" class="btn-primary btn-sm" style="margin-left:4px;" onclick="openEditObjectClassModal(${c.id})" title="Edit Class">
                                            ✏ Edit
                                        </button>
                                        <button type="button" class="${toggleClass} btn-sm" style="margin-left:4px;" onclick="toggleObjectClassStatus(${c.id}, '${c.status}')" title="${toggleText} detection">
                                            ${toggleText}
                                        </button>
                                        <button type="button" class="btn-danger btn-sm" style="margin-left:4px;" onclick="deleteObjectClass(${c.id}, '${safeCode}')" title="Delete Class">
                                            🗑 Delete
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    // Search & Filter Handlers
                    let searchDebounceTimeout = null;
                    function handleSearchFilterChange() {
                        const searchVal = document.getElementById('objClassSearchInput')?.value || '';
                        const clearBtn = document.getElementById('objClassClearSearchBtn');
                        if (clearBtn) clearBtn.style.display = searchVal ? 'block' : 'none';

                        clearTimeout(searchDebounceTimeout);
                        searchDebounceTimeout = setTimeout(() => {
                            fetchObjectClasses();
                        }, 180);
                    }

                    function clearSearchInput() {
                        const input = document.getElementById('objClassSearchInput');
                        if (input) input.value = '';
                        handleSearchFilterChange();
                    }

                    function resetSearchFilters() {
                        const searchInput = document.getElementById('objClassSearchInput');
                        const statusSelect = document.getElementById('objClassStatusFilter');
                        if (searchInput) searchInput.value = '';
                        if (statusSelect) statusSelect.value = 'ALL';
                        const clearBtn = document.getElementById('objClassClearSearchBtn');
                        if (clearBtn) clearBtn.style.display = 'none';
                        fetchObjectClasses();
                    }

                    // Add Modal Handlers
                    function openAddObjectClassModal() {
                        const modal = document.getElementById('modalAddObjectClass');
                        const form = document.getElementById('formAddObjectClass');
                        const alertBox = document.getElementById('modalAddAlert');
                        if (form) form.reset();
                        if (alertBox) alertBox.style.display = 'none';
                        if (modal) modal.classList.add('active');
                        setTimeout(() => document.getElementById('newModalObjCode')?.focus(), 100);
                    }

                    function closeAddObjectClassModal() {
                        const modal = document.getElementById('modalAddObjectClass');
                        if (modal) modal.classList.remove('active');
                    }

                    async function submitAddObjectClass() {
                        const code = document.getElementById('newModalObjCode')?.value.trim().toUpperCase();
                        const name = document.getElementById('newModalObjName')?.value.trim();
                        const description = document.getElementById('newModalObjDesc')?.value.trim();
                        const status = document.getElementById('newModalObjStatus')?.value || 'Active';
                        const alertBox = document.getElementById('modalAddAlert');

                        if (!code || !name) {
                            if (alertBox) {
                                alertBox.innerText = "Class Code and Class Name are required.";
                                alertBox.style.background = '#fee2e2';
                                alertBox.style.color = '#b91c1c';
                                alertBox.style.display = 'block';
                            }
                            return;
                        }

                        try {
                            const res = await fetch('/api/object_classes', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ code, name, description, status })
                            });
                            const data = await res.json();
                            if (res.ok && data.success) {
                                closeAddObjectClassModal();
                                showObjectClassAlert(data.message || `Object class '${code}' created successfully.`);
                                fetchObjectClasses();
                            } else {
                                if (alertBox) {
                                    alertBox.innerText = data.message || "Failed to create object class.";
                                    alertBox.style.background = '#fee2e2';
                                    alertBox.style.color = '#b91c1c';
                                    alertBox.style.display = 'block';
                                }
                            }
                        } catch(e) {
                            if (alertBox) {
                                alertBox.innerText = "Error: " + e.message;
                                alertBox.style.display = 'block';
                            }
                        }
                    }

                    // Edit Modal Handlers
                    async function openEditObjectClassModal(id) {
                        const modal = document.getElementById('modalEditObjectClass');
                        const alertBox = document.getElementById('modalEditAlert');
                        if (alertBox) alertBox.style.display = 'none';

                        let obj = globalObjectClasses.find(c => c.id === id);
                        if (!obj) {
                            try {
                                const res = await fetch(`/api/object_classes/${id}`);
                                if (res.ok) {
                                    const data = await res.json();
                                    obj = data.object_class;
                                }
                            } catch(e) {}
                        }

                        if (!obj) {
                            showObjectClassAlert("Object class not found", "error");
                            return;
                        }

                        document.getElementById('editModalObjId').value = obj.id;
                        document.getElementById('editModalObjIdDisplay').value = `#${obj.id}`;
                        document.getElementById('editModalObjCode').value = obj.code;
                        document.getElementById('editModalObjName').value = obj.name;
                        document.getElementById('editModalObjDesc').value = obj.description || '';
                        document.getElementById('editModalObjStatus').value = obj.status || 'Active';

                        if (modal) modal.classList.add('active');
                        setTimeout(() => document.getElementById('editModalObjName')?.focus(), 100);
                    }

                    function closeEditObjectClassModal() {
                        const modal = document.getElementById('modalEditObjectClass');
                        if (modal) modal.classList.remove('active');
                    }

                    async function submitEditObjectClass() {
                        const id = document.getElementById('editModalObjId')?.value;
                        const code = document.getElementById('editModalObjCode')?.value.trim().toUpperCase();
                        const name = document.getElementById('editModalObjName')?.value.trim();
                        const description = document.getElementById('editModalObjDesc')?.value.trim();
                        const status = document.getElementById('editModalObjStatus')?.value || 'Active';
                        const alertBox = document.getElementById('modalEditAlert');

                        if (!code || !name) {
                            if (alertBox) {
                                alertBox.innerText = "Class Code and Class Name are required.";
                                alertBox.style.background = '#fee2e2';
                                alertBox.style.color = '#b91c1c';
                                alertBox.style.display = 'block';
                            }
                            return;
                        }

                        try {
                            const res = await fetch(`/api/object_classes/${id}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ code, name, description, status })
                            });
                            const data = await res.json();
                            if (res.ok && data.success) {
                                closeEditObjectClassModal();
                                showObjectClassAlert(data.message || `Object class '${code}' updated successfully.`);
                                fetchObjectClasses();
                            } else {
                                if (alertBox) {
                                    alertBox.innerText = data.message || "Failed to update object class.";
                                    alertBox.style.background = '#fee2e2';
                                    alertBox.style.color = '#b91c1c';
                                    alertBox.style.display = 'block';
                                }
                            }
                        } catch(e) {
                            if (alertBox) {
                                alertBox.innerText = "Error: " + e.message;
                                alertBox.style.display = 'block';
                            }
                        }
                    }

                    // View Modal Handlers
                    async function openViewObjectClassModal(id) {
                        currentViewedObjId = id;
                        const modal = document.getElementById('modalViewObjectClass');
                        let obj = globalObjectClasses.find(c => c.id === id);

                        if (!obj) {
                            try {
                                const res = await fetch(`/api/object_classes/${id}`);
                                if (res.ok) {
                                    const data = await res.json();
                                    obj = data.object_class;
                                }
                            } catch(e) {}
                        }

                        if (!obj) {
                            showObjectClassAlert("Object class not found", "error");
                            return;
                        }

                        document.getElementById('viewModalObjId').innerText = `#${obj.id}`;
                        document.getElementById('viewModalObjCode').innerText = obj.code;
                        document.getElementById('viewModalObjName').innerText = obj.name;
                        document.getElementById('viewModalObjDesc').innerText = obj.description || 'No description provided';
                        document.getElementById('viewModalObjCreatedAt').innerText = obj.created_at || '-';
                        document.getElementById('viewModalObjUpdatedAt').innerText = obj.updated_at || '-';

                        const statusBadge = document.getElementById('viewModalObjStatus');
                        if (statusBadge) {
                            statusBadge.className = `badge ${obj.status === 'Active' ? 'active-status' : 'disabled-status'}`;
                            statusBadge.innerText = obj.status;
                        }

                        if (modal) modal.classList.add('active');
                    }

                    function closeViewObjectClassModal() {
                        const modal = document.getElementById('modalViewObjectClass');
                        if (modal) modal.classList.remove('active');
                    }

                    function transitionViewToEdit() {
                        const id = currentViewedObjId;
                        closeViewObjectClassModal();
                        if (id) openEditObjectClassModal(id);
                    }

                    // Enable / Disable Status Toggle
                    async function toggleObjectClassStatus(id, currentStatus) {
                        const nextStatus = currentStatus === 'Active' ? 'Disabled' : 'Active';
                        try {
                            const res = await fetch(`/api/object_classes/${id}`, {
                                method: 'PATCH',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ status: nextStatus })
                            });
                            const data = await res.json();
                            if (res.ok && data.success) {
                                showObjectClassAlert(`Status of class '${data.object_class?.code || id}' changed to ${nextStatus}.`);
                                fetchObjectClasses();
                            } else {
                                alert(data.message || "Failed to update status");
                            }
                        } catch(e) {
                            alert("Error toggling status: " + e.message);
                        }
                    }

                    // Safe Delete Handler
                    async function deleteObjectClass(id, code) {
                        if (!confirm(`Are you sure you want to delete object class '${code}' (ID #${id})?\n\nThis will remove the class definition from the system.`)) {
                            return;
                        }

                        try {
                            const res = await fetch(`/api/object_classes/${id}`, {
                                method: 'DELETE'
                            });
                            const data = await res.json();
                            if (res.ok && data.success) {
                                showObjectClassAlert(data.message || `Object class '${code}' removed successfully.`);
                                fetchObjectClasses();
                            } else {
                                alert(data.message || "Failed to delete object class.");
                            }
                        } catch(e) {
                            alert("Error deleting object class: " + e.message);
                        }
                    }

                    // Configuration Shell Handlers
                    function saveVisionConfig() {
                        const cfg = {
                            mode: document.getElementById('cfg-detection-mode')?.value,
                            interval: document.getElementById('cfg-inference-interval')?.value,
                            camera: document.getElementById('cfg-camera-association')?.value,
                            tracker: document.getElementById('cfg-tracker-algorithm')?.value,
                            conf: document.getElementById('cfg-conf-threshold')?.value,
                            iou: document.getElementById('cfg-nms-iou')?.value,
                            buffer: document.getElementById('cfg-track-buffer')?.value
                        };
                        try {
                            localStorage.setItem('skandha_vision_config', JSON.stringify(cfg));
                        } catch(e) {}
                        const statusEl = document.getElementById('visionConfigStatus');
                        if (statusEl) {
                            statusEl.style.display = 'inline-block';
                            setTimeout(() => { statusEl.style.display = 'none'; }, 3000);
                        }
                    }

                    function resetVisionConfig() {
                        if (document.getElementById('cfg-detection-mode')) document.getElementById('cfg-detection-mode').value = 'balanced';
                        if (document.getElementById('cfg-inference-interval')) document.getElementById('cfg-inference-interval').value = '15';
                        if (document.getElementById('cfg-camera-association')) document.getElementById('cfg-camera-association').value = 'all';
                        if (document.getElementById('cfg-tracker-algorithm')) document.getElementById('cfg-tracker-algorithm').value = 'bytetrack';
                        if (document.getElementById('cfg-conf-threshold')) document.getElementById('cfg-conf-threshold').value = '0.50';
                        if (document.getElementById('cfg-nms-iou')) document.getElementById('cfg-nms-iou').value = '0.45';
                        if (document.getElementById('cfg-track-buffer')) document.getElementById('cfg-track-buffer').value = '30';
                        try {
                            localStorage.removeItem('skandha_vision_config');
                        } catch(e) {}
                        const statusEl = document.getElementById('visionConfigStatus');
                        if (statusEl) {
                            statusEl.innerText = "✓ Reset to default parameters";
                            statusEl.style.display = 'inline-block';
                            setTimeout(() => { statusEl.style.display = 'none'; statusEl.innerText = "✓ Configuration profile saved"; }, 3000);
                        }
                    }

                    // ==========================================
                    // CAMERA SOURCES MASTER MODULE CLIENT LOGIC
                    // ==========================================
                    let globalVisionCameras = [];
                    let currentViewedCamId = null;

                    function showVisionCamAlert(message, type = 'success') {
                        const alertBox = document.getElementById('visionCamAlertBox');
                        const msgEl = document.getElementById('visionCamAlertMsg');
                        if (!alertBox || !msgEl) return;
                        msgEl.innerText = message;
                        if (type === 'success') {
                            alertBox.style.background = '#dcfce7';
                            alertBox.style.color = '#15803d';
                            alertBox.style.border = '1px solid #bbf7d0';
                        } else {
                            alertBox.style.background = '#fee2e2';
                            alertBox.style.color = '#b91c1c';
                            alertBox.style.border = '1px solid #fecaca';
                        }
                        alertBox.style.display = 'flex';
                        setTimeout(() => {
                            hideVisionCamAlert();
                        }, 5000);
                    }

                    function hideVisionCamAlert() {
                        const alertBox = document.getElementById('visionCamAlertBox');
                        if (alertBox) alertBox.style.display = 'none';
                    }

                    async function fetchVisionCameras() {
                        const search = (document.getElementById('visionCamSearchInput')?.value || '').trim();
                        const aiStatus = document.getElementById('visionCamAiFilter')?.value || 'ALL';
                        const camStatus = document.getElementById('visionCamStatusFilter')?.value || 'ALL';

                        let url = '/api/vision/cameras';
                        const params = [];
                        if (search) params.push('search=' + encodeURIComponent(search));
                        if (aiStatus && aiStatus !== 'ALL') params.push('ai_status=' + encodeURIComponent(aiStatus));
                        if (camStatus && camStatus !== 'ALL') params.push('cam_status=' + encodeURIComponent(camStatus));
                        if (params.length > 0) url += '?' + params.join('&');

                        try {
                            const res = await fetch(url);
                            if (res.ok) {
                                const data = await res.json();
                                if (Array.isArray(data)) {
                                    globalVisionCameras = data;
                                }
                            }
                        } catch(e) {
                            console.warn("Failed to fetch vision cameras:", e);
                        }

                        // Also ensure dynamic object classes taxonomy is loaded
                        if (!globalObjectClasses || globalObjectClasses.length === 0) {
                            try {
                                const resObj = await fetch('/api/object_classes');
                                if (resObj.ok) {
                                    globalObjectClasses = await resObj.json();
                                }
                            } catch(e) {}
                        }

                        renderVisionCameras(globalVisionCameras);
                        updateVisionCamerasKPI();
                    }

                    function updateVisionCamerasKPI() {
                        const kpiEl = document.getElementById('kpi-vision-cameras');
                        if (kpiEl && Array.isArray(globalVisionCameras)) {
                            const aiEnabledCount = globalVisionCameras.filter(c => c.ai_config && c.ai_config.ai_enabled).length;
                            kpiEl.innerText = `${aiEnabledCount} / ${globalVisionCameras.length}`;
                            kpiEl.title = `${aiEnabledCount} AI-enabled out of ${globalVisionCameras.length} total registered cameras`;
                        }
                    }

                    function renderVisionCameras(cameras) {
                        const tbody = document.getElementById('visionCamerasBody');
                        const counter = document.getElementById('visionCamCountBadge');
                        if (!tbody) return;

                        const totalCount = cameras ? cameras.length : 0;
                        if (counter) {
                            counter.innerText = `Showing ${totalCount} camera${totalCount === 1 ? '' : 's'}`;
                        }

                        if (!cameras || cameras.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="10" style="text-align:center; color:var(--text-muted); padding:2.5rem 1rem;">
                                        <div style="font-size:1.1rem; font-weight:700; color:var(--text-main); margin-bottom:4px;">No Cameras Found</div>
                                        <div style="font-size:0.85rem;">No cameras match the current filters. Cameras are registered in the existing Camera Master.</div>
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = cameras.map(cam => {
                            const isCamOnline = (cam.camera_status || '').toLowerCase() === 'online';
                            const camStatusBadge = isCamOnline
                                ? '<span class="badge active-status">Online</span>'
                                : '<span class="badge disabled-status">Offline</span>';

                            const aiCfg = cam.ai_config || {};
                            const isAiEnabled = !!aiCfg.ai_enabled;
                            const isDetEnabled = !!aiCfg.detection_enabled;
                            const isTrkEnabled = !!aiCfg.tracking_enabled;

                            const aiBadge = isAiEnabled
                                ? '<span class="badge active-status">Enabled</span>'
                                : '<span class="badge disabled-status">Disabled</span>';

                            const detBadge = isDetEnabled
                                ? '<span class="badge" style="background:#e0f2fe; color:#0369a1; border:1px solid #bae6fd;">Enabled</span>'
                                : '<span class="badge disabled-status">Disabled</span>';

                            const trkBadge = isTrkEnabled
                                ? '<span class="badge" style="background:#fef3c7; color:#b45309; border:1px solid #fde68a;">Enabled</span>'
                                : '<span class="badge disabled-status">Disabled</span>';

                            const safeCode = escapeHtml(cam.camera_code || cam.camera_id);
                            const safeName = escapeHtml(cam.camera_name || '-');
                            const safeWarehouse = escapeHtml(cam.warehouse || 'Warehouse A');
                            const safeLocation = escapeHtml(cam.location || '-');
                            const safeType = escapeHtml(cam.camera_type || 'IP Camera');
                            const safeCamId = escapeHtml(cam.camera_id);

                            return `
                                <tr>
                                    <td>
                                        <code style="font-size:0.92rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.08); padding:3px 7px; border-radius:4px; letter-spacing:0.5px;">${safeCode}</code>
                                    </td>
                                    <td><strong style="color:var(--text-main); font-size:0.92rem;">${safeName}</strong></td>
                                    <td style="color:var(--text-muted); font-size:0.85rem;">${safeWarehouse}</td>
                                    <td style="color:var(--text-muted); font-size:0.85rem;"><span class="badge pending">${safeLocation}</span></td>
                                    <td style="color:var(--text-muted); font-size:0.85rem;">${safeType}</td>
                                    <td style="text-align:center;">${camStatusBadge}</td>
                                    <td style="text-align:center;">${aiBadge}</td>
                                    <td style="text-align:center;">${detBadge}</td>
                                    <td style="text-align:center;">${trkBadge}</td>
                                    <td style="text-align:center; white-space:nowrap;">
                                        <button type="button" class="btn-primary btn-sm" style="background:var(--panel-subtle); color:var(--text-main); border:1px solid var(--border-light);" onclick="openViewCameraModal('${safeCamId}')" title="View Camera Master & AI Details">
                                            👁 View
                                        </button>
                                        <button type="button" class="btn-primary btn-sm" style="margin-left:4px;" onclick="openConfigureCameraModal('${safeCamId}')" title="Configure AI Settings">
                                            ⚙ Configure
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    // Search & Filter Handlers
                    let camSearchDebounceTimeout = null;
                    function handleVisionCamSearchChange() {
                        const searchVal = document.getElementById('visionCamSearchInput')?.value || '';
                        const clearBtn = document.getElementById('visionCamClearSearchBtn');
                        if (clearBtn) clearBtn.style.display = searchVal ? 'block' : 'none';

                        clearTimeout(camSearchDebounceTimeout);
                        camSearchDebounceTimeout = setTimeout(() => {
                            fetchVisionCameras();
                        }, 180);
                    }

                    function clearVisionCamSearch() {
                        const input = document.getElementById('visionCamSearchInput');
                        if (input) input.value = '';
                        handleVisionCamSearchChange();
                    }

                    function resetVisionCamFilters() {
                        const searchInput = document.getElementById('visionCamSearchInput');
                        const aiFilter = document.getElementById('visionCamAiFilter');
                        const statusFilter = document.getElementById('visionCamStatusFilter');
                        if (searchInput) searchInput.value = '';
                        if (aiFilter) aiFilter.value = 'ALL';
                        if (statusFilter) statusFilter.value = 'ALL';
                        const clearBtn = document.getElementById('visionCamClearSearchBtn');
                        if (clearBtn) clearBtn.style.display = 'none';
                        fetchVisionCameras();
                    }

                    // Configure Modal Handlers
                    async function openConfigureCameraModal(camId) {
                        currentViewedCamId = camId;
                        const modal = document.getElementById('modalConfigureCameraSource');
                        const alertBox = document.getElementById('modalVisionCamAlert');
                        if (alertBox) alertBox.style.display = 'none';

                        let cam = globalVisionCameras.find(c => c.camera_id === camId || c.camera_code === camId);
                        if (!cam) {
                            try {
                                const res = await fetch(`/api/vision/cameras/${camId}`);
                                if (res.ok) {
                                    const data = await res.json();
                                    cam = data.camera;
                                }
                            } catch(e) {}
                        }

                        if (!cam) {
                            showVisionCamAlert("Camera source not found", "error");
                            return;
                        }

                        // Populate Read-only Camera Master Context
                        document.getElementById('cfgModalCameraId').value = cam.camera_id;
                        document.getElementById('cfgModalCamCode').innerText = cam.camera_code;
                        document.getElementById('cfgModalCamName').innerText = cam.camera_name;
                        document.getElementById('cfgModalCamWarehouse').innerText = cam.warehouse || 'Warehouse A';
                        document.getElementById('cfgModalCamLocation').innerText = cam.location || 'General';
                        document.getElementById('cfgModalCamType').innerText = cam.camera_type || 'IP Camera';
                        document.getElementById('cfgModalCamBinReadOnly').innerText = cam.bin_id || '-';

                        const statusBadge = document.getElementById('cfgModalCamStatusBadge');
                        if (statusBadge) {
                            const isOnline = (cam.camera_status || '').toLowerCase() === 'online';
                            statusBadge.className = `badge ${isOnline ? 'active-status' : 'disabled-status'}`;
                            statusBadge.innerText = cam.camera_status || 'Unknown';
                        }
                        
                        // Populate Bin Dropdown
                        const binSelect = document.getElementById('cfgModalBinId');
                        if (binSelect) {
                            binSelect.innerHTML = '<option value="">-- None (General Area) --</option>';
                            try {
                                const binRes = await fetch('/api/bins');
                                if (binRes.ok) {
                                    const bins = await binRes.json();
                                    bins.forEach(b => {
                                        const opt = document.createElement('option');
                                        opt.value = b.bin_id;
                                        opt.innerText = `${b.bin_id} (${b.zone})`;
                                        binSelect.appendChild(opt);
                                    });
                                }
                            } catch(e) { console.error("Error fetching bins:", e); }
                            binSelect.value = cam.bin_id || '';
                        }

                        // Populate AI Configuration
                        const aiCfg = cam.ai_config || {};
                        document.getElementById('cfgModalAiEnabled').value = aiCfg.ai_enabled ? '1' : '0';
                        document.getElementById('cfgModalDetectionEnabled').value = aiCfg.detection_enabled ? '1' : '0';
                        document.getElementById('cfgModalTrackingEnabled').value = aiCfg.tracking_enabled ? '1' : '0';
                        document.getElementById('cfgModalFps').value = aiCfg.processing_fps || 5;

                        // Ensure dynamic Object Classes taxonomy is loaded from Object Classes Master
                        if (!globalObjectClasses || globalObjectClasses.length === 0) {
                            try {
                                const resClasses = await fetch('/api/object_classes');
                                if (resClasses.ok) {
                                    globalObjectClasses = await resClasses.json();
                                }
                            } catch(e) {}
                        }

                        // Render dynamic Object Classes checkboxes
                        renderCameraClassCheckboxes(aiCfg.object_classes || []);

                        if (modal) modal.classList.add('active');
                    }

                    function closeConfigureCameraModal() {
                        const modal = document.getElementById('modalConfigureCameraSource');
                        if (modal) modal.classList.remove('active');
                    }

                    function renderCameraClassCheckboxes(selectedCodes = []) {
                        const container = document.getElementById('cfgModalObjectClassesContainer');
                        if (!container) return;

                        const selectedSet = new Set((selectedCodes || []).map(c => String(c).toUpperCase()));

                        // Use classes from Object Classes Master
                        const classes = Array.isArray(globalObjectClasses) && globalObjectClasses.length > 0 
                            ? globalObjectClasses 
                            : [
                                { code: 'BOX', name: 'Box / Carton' },
                                { code: 'WORKER', name: 'Worker / Personnel' },
                                { code: 'TRUCK', name: 'Truck / Carrier' },
                                { code: 'PALLET', name: 'Pallet' },
                                { code: 'FORKLIFT', name: 'Forklift' },
                                { code: 'BIN', name: 'Bin' }
                            ];

                        container.innerHTML = classes.map(cls => {
                            const isChecked = selectedSet.has(cls.code.toUpperCase());
                            const isDisabledClass = cls.status === 'Disabled';
                            return `
                                <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:0.85rem; padding:4px 6px; border-radius:4px; background:var(--panel-bg); border:1px solid var(--border-light);" title="${escapeHtml(cls.description || cls.name)}">
                                    <input type="checkbox" class="cam-obj-class-chk" value="${escapeHtml(cls.code)}" ${isChecked ? 'checked' : ''} style="margin:0; width:auto; cursor:pointer;">
                                    <span style="font-weight:700; color:var(--text-main); font-family:monospace;">${escapeHtml(cls.code)}</span>
                                    ${isDisabledClass ? '<small style="color:var(--text-muted); font-size:0.7rem;">(Inactive)</small>' : ''}
                                </label>
                            `;
                        }).join('');
                    }

                    function selectAllCameraClasses(selectAll) {
                        document.querySelectorAll('.cam-obj-class-chk').forEach(chk => {
                            chk.checked = !!selectAll;
                        });
                    }

                    function handleAiEnabledToggle() {
                        // Keep hook for responsive styling if needed
                    }

                    async function submitConfigureCamera() {
                        const camId = document.getElementById('cfgModalCameraId')?.value;
                        const aiEnabled = document.getElementById('cfgModalAiEnabled')?.value === '1';
                        const detectionEnabled = document.getElementById('cfgModalDetectionEnabled')?.value === '1';
                        const trackingEnabled = document.getElementById('cfgModalTrackingEnabled')?.value === '1';
                        const fpsVal = document.getElementById('cfgModalFps')?.value;
                        const alertBox = document.getElementById('modalVisionCamAlert');

                        // Basic Validation: Processing FPS
                        const fps = parseInt(fpsVal, 10);
                        if (isNaN(fps) || fps <= 0 || fps > 60) {
                            if (alertBox) {
                                alertBox.innerText = "Processing FPS must be a numeric integer between 1 and 60.";
                                alertBox.style.background = '#fee2e2';
                                alertBox.style.color = '#b91c1c';
                                alertBox.style.display = 'block';
                            }
                            return;
                        }

                        // Collect selected object classes
                        const selectedClasses = [];
                        document.querySelectorAll('.cam-obj-class-chk:checked').forEach(chk => {
                            selectedClasses.push(chk.value);
                        });

                        // Validation: If AI is enabled, at least one Object Class must be selected
                        if (aiEnabled && selectedClasses.length === 0) {
                            if (alertBox) {
                                alertBox.innerText = "At least one Object Class must be selected when AI Processing is enabled.";
                                alertBox.style.background = '#fee2e2';
                                alertBox.style.color = '#b91c1c';
                                alertBox.style.display = 'block';
                            }
                            return;
                        }

                        const payload = {
                            bin_id: document.getElementById('cfgModalBinId')?.value,
                            ai_enabled: aiEnabled,
                            detection_enabled: detectionEnabled,
                            tracking_enabled: trackingEnabled,
                            processing_fps: fps,
                            object_classes: selectedClasses
                        };

                        try {
                            const res = await fetch(`/api/vision/cameras/${camId}/config`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });
                            const data = await res.json();
                            if (res.ok && data.success) {
                                closeConfigureCameraModal();
                                showVisionCamAlert(data.message || `AI configuration saved successfully.`);
                                fetchVisionCameras();
                            } else {
                                if (alertBox) {
                                    alertBox.innerText = data.message || "Failed to save AI configuration.";
                                    alertBox.style.background = '#fee2e2';
                                    alertBox.style.color = '#b91c1c';
                                    alertBox.style.display = 'block';
                                }
                            }
                        } catch(e) {
                            if (alertBox) {
                                alertBox.innerText = "Error: " + e.message;
                                alertBox.style.display = 'block';
                            }
                        }
                    }

                    // View Modal Handlers
                    async function openViewCameraModal(camId) {
                        currentViewedCamId = camId;
                        const modal = document.getElementById('modalViewCameraSource');
                        let cam = globalVisionCameras.find(c => c.camera_id === camId || c.camera_code === camId);
                        if (!cam) {
                            try {
                                const res = await fetch(`/api/vision/cameras/${camId}`);
                                if (res.ok) {
                                    const data = await res.json();
                                    cam = data.camera;
                                }
                            } catch(e) {}
                        }

                        if (!cam) {
                            showVisionCamAlert("Camera not found", "error");
                            return;
                        }

                        document.getElementById('viewCamCode').innerText = cam.camera_code;
                        document.getElementById('viewCamName').innerText = cam.camera_name;
                        document.getElementById('viewCamWarehouse').innerText = cam.warehouse || 'Warehouse A';
                        document.getElementById('viewCamLocation').innerText = cam.location || 'General';
                        document.getElementById('viewCamType').innerText = cam.camera_type || 'IP Camera';

                        const statusBadge = document.getElementById('viewCamStatus');
                        if (statusBadge) {
                            const isOnline = (cam.camera_status || '').toLowerCase() === 'online';
                            statusBadge.className = `badge ${isOnline ? 'active-status' : 'disabled-status'}`;
                            statusBadge.innerText = cam.camera_status || 'Unknown';
                        }

                        const aiCfg = cam.ai_config || {};
                        document.getElementById('viewCamAiEnabled').innerHTML = aiCfg.ai_enabled 
                            ? '<span class="badge active-status">Enabled</span>' 
                            : '<span class="badge disabled-status">Disabled</span>';

                        document.getElementById('viewCamDetectionEnabled').innerHTML = aiCfg.detection_enabled 
                            ? '<span class="badge" style="background:#e0f2fe; color:#0369a1; border:1px solid #bae6fd;">Enabled</span>' 
                            : '<span class="badge disabled-status">Disabled</span>';

                        document.getElementById('viewCamTrackingEnabled').innerHTML = aiCfg.tracking_enabled 
                            ? '<span class="badge" style="background:#fef3c7; color:#b45309; border:1px solid #fde68a;">Enabled</span>' 
                            : '<span class="badge disabled-status">Disabled</span>';

                        document.getElementById('viewCamFps').innerText = aiCfg.processing_fps || 5;

                        const classesContainer = document.getElementById('viewCamClassesContainer');
                        if (classesContainer) {
                            const classes = aiCfg.object_classes || [];
                            if (classes.length === 0) {
                                classesContainer.innerHTML = '<span style="color:var(--text-muted); font-size:0.85rem;">None configured</span>';
                            } else {
                                classesContainer.innerHTML = classes.map(cls => `
                                    <code style="font-size:0.85rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.08); padding:2px 6px; border-radius:4px;">${escapeHtml(cls)}</code>
                                `).join(' ');
                            }
                        }

                        document.getElementById('viewCamConfigCreated').innerText = aiCfg.created_at || '-';
                        document.getElementById('viewCamConfigUpdated').innerText = aiCfg.updated_at || '-';

                        if (modal) modal.classList.add('active');
                    }

                    function closeViewCameraModal() {
                        const modal = document.getElementById('modalViewCameraSource');
                        if (modal) modal.classList.remove('active');
                    }

                    function transitionViewToConfigure() {
                        const id = currentViewedCamId;
                        closeViewCameraModal();
                        if (id) openConfigureCameraModal(id);
                    }

                    // ==========================================
                    // WAREHOUSE ZONE MASTER MANAGEMENT LOGIC
                    // ==========================================
                    let globalVisionZones = [];
                    let currentViewedZoneId = null;

                    const ZONE_TYPE_LABELS = {
                        'TRUCK_BAY': 'Truck Bay',
                        'DOCK': 'Dock',
                        'UNLOADING': 'Unloading',
                        'SORTING': 'Sorting',
                        'CONVEYOR': 'Conveyor',
                        'STAGING': 'Staging',
                        'STORAGE': 'Storage',
                        'BIN_AREA': 'Bin Area',
                        'DISPATCH': 'Dispatch'
                    };

                    function showVisionZoneAlert(message, type = 'success') {
                        const alertBox = document.getElementById('visionZoneAlertBox');
                        const msgEl = document.getElementById('visionZoneAlertMsg');
                        if (!alertBox || !msgEl) return;
                        msgEl.innerText = message;
                        if (type === 'error') {
                            alertBox.style.background = '#fef2f2';
                            alertBox.style.color = '#dc2626';
                            alertBox.style.border = '1px solid #fecaca';
                        } else {
                            alertBox.style.background = '#ecfdf5';
                            alertBox.style.color = '#059669';
                            alertBox.style.border = '1px solid #a7f3d0';
                        }
                        alertBox.style.display = 'flex';
                        setTimeout(() => {
                            hideVisionZoneAlert();
                        }, 5000);
                    }

                    function hideVisionZoneAlert() {
                        const alertBox = document.getElementById('visionZoneAlertBox');
                        if (alertBox) alertBox.style.display = 'none';
                    }

                    function handleVisionZoneSearchChange() {
                        const searchInput = document.getElementById('visionZoneSearchInput');
                        const clearBtn = document.getElementById('visionZoneClearSearchBtn');
                        if (clearBtn && searchInput) {
                            clearBtn.style.display = searchInput.value.trim().length > 0 ? 'block' : 'none';
                        }
                        fetchVisionZones();
                    }

                    function clearVisionZoneSearch() {
                        const searchInput = document.getElementById('visionZoneSearchInput');
                        if (searchInput) searchInput.value = '';
                        const clearBtn = document.getElementById('visionZoneClearSearchBtn');
                        if (clearBtn) clearBtn.style.display = 'none';
                        fetchVisionZones();
                    }

                    function resetVisionZoneFilters() {
                        const searchInput = document.getElementById('visionZoneSearchInput');
                        if (searchInput) searchInput.value = '';
                        const clearBtn = document.getElementById('visionZoneClearSearchBtn');
                        if (clearBtn) clearBtn.style.display = 'none';

                        const whFilter = document.getElementById('visionZoneWarehouseFilter');
                        if (whFilter) whFilter.value = 'ALL';

                        const typeFilter = document.getElementById('visionZoneTypeFilter');
                        if (typeFilter) typeFilter.value = 'ALL';

                        const statusFilter = document.getElementById('visionZoneStatusFilter');
                        if (statusFilter) statusFilter.value = 'ALL';

                        fetchVisionZones();
                    }

                    async function fetchVisionZones() {
                        const search = (document.getElementById('visionZoneSearchInput')?.value || '').trim();
                        const warehouse = document.getElementById('visionZoneWarehouseFilter')?.value || 'ALL';
                        const zoneType = document.getElementById('visionZoneTypeFilter')?.value || 'ALL';
                        const status = document.getElementById('visionZoneStatusFilter')?.value || 'ALL';

                        let url = '/api/vision/zones';
                        const params = [];
                        if (search) params.push('search=' + encodeURIComponent(search));
                        if (warehouse && warehouse !== 'ALL') params.push('warehouse=' + encodeURIComponent(warehouse));
                        if (zoneType && zoneType !== 'ALL') params.push('zone_type=' + encodeURIComponent(zoneType));
                        if (status && status !== 'ALL') params.push('status=' + encodeURIComponent(status));
                        if (params.length > 0) url += '?' + params.join('&');

                        try {
                            const res = await fetch(url);
                            if (res.ok) {
                                const data = await res.json();
                                if (Array.isArray(data)) {
                                    globalVisionZones = data;
                                }
                            }
                        } catch (e) {
                            console.warn("Failed to fetch warehouse zones:", e);
                        }

                        renderVisionZones(globalVisionZones);
                    }

                    function renderVisionZones(zones) {
                        const tbody = document.getElementById('visionZonesBody');
                        const countBadge = document.getElementById('visionZoneCountBadge');
                        if (countBadge) {
                            countBadge.innerText = `Showing ${zones.length} zone${zones.length === 1 ? '' : 's'}`;
                        }
                        if (!tbody) return;

                        if (zones.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="7" style="text-align:center; padding:2rem; color:var(--text-muted);">
                                        No warehouse zones found matching criteria. Click "+ Add Zone" to create one.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = zones.map(z => {
                            const isActive = z.status === 'Active';
                            const statusBadge = isActive 
                                ? `<span class="badge sent" style="font-size:0.78rem;">Active</span>`
                                : `<span class="badge pending" style="font-size:0.78rem;">Disabled</span>`;

                            const toggleBtnText = isActive ? 'Disable' : 'Enable';
                            const toggleBtnClass = isActive ? 'btn-danger' : 'btn-success';

                            const typeLabel = escapeHtml(z.zone_type_label || ZONE_TYPE_LABELS[z.zone_type] || z.zone_type);
                            const cameraCount = Array.isArray(z.cameras) ? z.cameras.length : (z.camera_count || 0);
                            const roiCount = Array.isArray(z.cameras) ? z.cameras.filter(c => c.roi_configured).length : 0;
                            const cameraBadge = cameraCount > 0
                                ? `<span class="badge" style="background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; font-size:0.8rem; font-weight:700;">${cameraCount} Camera${cameraCount === 1 ? '' : 's'}</span>` +
                                  (roiCount > 0 ? `<div style="font-size:0.72rem; color:#0284c7; font-weight:700; margin-top:2px;">✓ ${roiCount}/${cameraCount} ROI Configured</div>` : `<div style="font-size:0.72rem; color:var(--text-muted); margin-top:2px;">No ROI Set</div>`)
                                : `<span class="badge" style="background:#f8fafc; color:#94a3b8; border:1px solid #e2e8f0; font-size:0.8rem;">0 Cameras</span>`;

                            return `
                                <tr>
                                    <td>
                                        <code style="font-size:0.92rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.08); padding:3px 7px; border-radius:4px;">
                                            ${escapeHtml(z.zone_code)}
                                        </code>
                                    </td>
                                    <td>
                                        <div style="font-weight:700; color:var(--text-main); font-size:0.92rem;">${escapeHtml(z.zone_name)}</div>
                                        ${z.description ? `<div style="font-size:0.78rem; color:var(--text-muted); margin-top:2px;">${escapeHtml(z.description)}</div>` : ''}
                                    </td>
                                    <td>
                                        <span class="badge" style="background:#e0f2fe; color:#0369a1; border:1px solid #bae6fd; font-size:0.8rem; font-weight:700;">
                                            ${typeLabel}
                                        </span>
                                    </td>
                                    <td>${escapeHtml(z.warehouse || 'Warehouse A')}</td>
                                    <td style="text-align:center;">${cameraBadge}</td>
                                    <td style="text-align:center;">${statusBadge}</td>
                                    <td style="text-align:center;">
                                        <div style="display:inline-flex; gap:6px; flex-wrap:wrap; justify-content:center;">
                                            <button class="btn-primary btn-sm" style="padding:4px 8px; font-size:0.78rem;" onclick="openViewZoneModal(${z.id})">View</button>
                                            <button class="btn-secondary btn-sm" style="padding:4px 8px; font-size:0.78rem;" onclick="openEditZoneModal(${z.id})">Edit</button>
                                            <button class="btn-primary btn-sm" style="padding:4px 8px; font-size:0.78rem; background:#0284c7; color:#fff;" onclick="openRoiEditorModal(${z.id})">📐 Configure ROI</button>
                                            <button class="${toggleBtnClass} btn-sm" style="padding:4px 8px; font-size:0.78rem;" onclick="toggleZoneStatus(${z.id}, '${escapeHtml(z.status)}')">${toggleBtnText}</button>
                                            <button class="btn-danger btn-sm" style="padding:4px 8px; font-size:0.78rem;" onclick="deleteVisionZone(${z.id}, '${escapeHtml(z.zone_code)}')">Delete</button>
                                        </div>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    // Helper to populate camera checkboxes for Add / Edit modals from Camera Master
                    async function populateZoneCameraCheckboxes(containerId, selectedCameraIds = []) {
                        const container = document.getElementById(containerId);
                        if (!container) return;
                        container.innerHTML = '<span style="color:var(--text-muted); font-size:0.85rem;">Loading cameras from Camera Master...</span>';

                        try {
                            const res = await fetch('/api/vision/cameras');
                            if (!res.ok) throw new Error('Failed to load cameras');
                            const cameras = await res.json();

                            if (!Array.isArray(cameras) || cameras.length === 0) {
                                container.innerHTML = '<span style="color:var(--text-muted); font-size:0.85rem;">No cameras available in Camera Master.</span>';
                                return;
                            }

                            const selectedSet = new Set(selectedCameraIds.map(String));
                            container.innerHTML = cameras.map(cam => {
                                const isChecked = selectedSet.has(String(cam.camera_id)) || selectedSet.has(String(cam.camera_code));
                                return `
                                    <label style="display:flex; align-items:center; gap:8px; cursor:pointer; background:var(--panel-bg); padding:6px 10px; border-radius:6px; border:1px solid var(--border-light); font-size:0.85rem;">
                                        <input type="checkbox" name="zone_camera_checkbox" value="${escapeHtml(cam.camera_id)}" ${isChecked ? 'checked' : ''} style="width:auto; margin:0;">
                                        <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                                            <strong style="color:var(--accent);">${escapeHtml(cam.camera_code)}</strong>
                                            <span style="color:var(--text-muted); font-size:0.8rem;"> - ${escapeHtml(cam.camera_name)}</span>
                                        </div>
                                    </label>
                                `;
                            }).join('');
                        } catch (e) {
                            console.error("Camera checkbox population error:", e);
                            container.innerHTML = '<span style="color:var(--danger); font-size:0.85rem;">Error loading cameras.</span>';
                        }
                    }

                    function selectAllZoneCameras(containerId, selectAll = true) {
                        const container = document.getElementById(containerId);
                        if (!container) return;
                        const checkboxes = container.querySelectorAll('input[type="checkbox"]');
                        checkboxes.forEach(cb => cb.checked = selectAll);
                    }

                    // ADD MODAL
                    function openAddZoneModal() {
                        const form = document.getElementById('formAddVisionZone');
                        if (form) form.reset();
                        const alertBox = document.getElementById('modalAddZoneAlert');
                        if (alertBox) {
                            alertBox.style.display = 'none';
                            alertBox.innerText = '';
                        }
                        const whInput = document.getElementById('newZoneWarehouse');
                        if (whInput) whInput.value = 'Warehouse A';
                        const statusSelect = document.getElementById('newZoneStatus');
                        if (statusSelect) statusSelect.value = 'Active';

                        populateZoneCameraCheckboxes('newZoneCamContainer', []);

                        const modal = document.getElementById('modalAddVisionZone');
                        if (modal) modal.classList.add('active');
                        setTimeout(() => document.getElementById('newZoneCode')?.focus(), 100);
                    }

                    function closeAddZoneModal() {
                        const modal = document.getElementById('modalAddVisionZone');
                        if (modal) modal.classList.remove('active');
                    }

                    async function submitAddVisionZone() {
                        const code = (document.getElementById('newZoneCode')?.value || '').trim();
                        const name = (document.getElementById('newZoneName')?.value || '').trim();
                        const type = (document.getElementById('newZoneType')?.value || '').trim();
                        const warehouse = (document.getElementById('newZoneWarehouse')?.value || 'Warehouse A').trim();
                        const description = (document.getElementById('newZoneDesc')?.value || '').trim();
                        const status = document.getElementById('newZoneStatus')?.value || 'Active';

                        const alertBox = document.getElementById('modalAddZoneAlert');
                        const submitBtn = document.getElementById('btnSubmitAddZone');

                        if (!code || !name || !type) {
                            if (alertBox) {
                                alertBox.innerText = 'Zone Code, Zone Name, and Zone Type are required.';
                                alertBox.style.display = 'block';
                                alertBox.style.background = '#fef2f2';
                                alertBox.style.color = '#dc2626';
                                alertBox.style.border = '1px solid #fecaca';
                            }
                            return;
                        }

                        // Collect selected camera IDs
                        const camCheckboxes = document.querySelectorAll('#newZoneCamContainer input[type="checkbox"]:checked');
                        const selectedCameras = Array.from(camCheckboxes).map(cb => cb.value);

                        if (submitBtn) {
                            submitBtn.disabled = true;
                            submitBtn.innerText = 'Creating...';
                        }

                        try {
                            const res = await fetch('/api/vision/zones', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    zone_code: code,
                                    zone_name: name,
                                    zone_type: type,
                                    warehouse: warehouse,
                                    description: description,
                                    status: status,
                                    cameras: selectedCameras
                                })
                            });

                            const data = await res.json();
                            if (res.ok && data.success) {
                                closeAddZoneModal();
                                showVisionZoneAlert(`Zone '${data.zone.zone_code}' created successfully.`);
                                fetchVisionZones();
                            } else {
                                if (alertBox) {
                                    alertBox.innerText = data.message || 'Failed to create warehouse zone.';
                                    alertBox.style.display = 'block';
                                    alertBox.style.background = '#fef2f2';
                                    alertBox.style.color = '#dc2626';
                                    alertBox.style.border = '1px solid #fecaca';
                                }
                            }
                        } catch (e) {
                            console.error(e);
                            if (alertBox) {
                                alertBox.innerText = 'Network error while creating zone.';
                                alertBox.style.display = 'block';
                                alertBox.style.background = '#fef2f2';
                                alertBox.style.color = '#dc2626';
                                alertBox.style.border = '1px solid #fecaca';
                            }
                        } finally {
                            if (submitBtn) {
                                submitBtn.disabled = false;
                                submitBtn.innerText = '+ Create Zone';
                            }
                        }
                    }

                    // EDIT MODAL
                    async function openEditZoneModal(identifier) {
                        const alertBox = document.getElementById('modalEditZoneAlert');
                        if (alertBox) {
                            alertBox.style.display = 'none';
                            alertBox.innerText = '';
                        }

                        try {
                            const res = await fetch(`/api/vision/zones/${identifier}`);
                            if (!res.ok) throw new Error('Zone not found');
                            const data = await res.json();
                            const zone = data.zone;

                            document.getElementById('editZoneId').value = zone.id;
                            document.getElementById('editZoneIdDisplay').value = zone.id;
                            document.getElementById('editZoneCode').value = zone.zone_code;
                            document.getElementById('editZoneName').value = zone.zone_name;
                            document.getElementById('editZoneType').value = zone.zone_type;
                            document.getElementById('editZoneWarehouse').value = zone.warehouse || 'Warehouse A';
                            document.getElementById('editZoneDesc').value = zone.description || '';
                            document.getElementById('editZoneStatus').value = zone.status || 'Active';

                            const currentCamIds = Array.isArray(zone.camera_ids) ? zone.camera_ids : [];
                            await populateZoneCameraCheckboxes('editZoneCamContainer', currentCamIds);

                            const modal = document.getElementById('modalEditVisionZone');
                            if (modal) modal.classList.add('active');
                            setTimeout(() => document.getElementById('editZoneName')?.focus(), 100);
                        } catch (e) {
                            console.error(e);
                            showVisionZoneAlert(`Failed to load zone '${identifier}'.`, 'error');
                        }
                    }

                    function closeEditZoneModal() {
                        const modal = document.getElementById('modalEditVisionZone');
                        if (modal) modal.classList.remove('active');
                    }

                    async function submitEditVisionZone() {
                        const id = document.getElementById('editZoneId')?.value;
                        const code = (document.getElementById('editZoneCode')?.value || '').trim();
                        const name = (document.getElementById('editZoneName')?.value || '').trim();
                        const type = (document.getElementById('editZoneType')?.value || '').trim();
                        const warehouse = (document.getElementById('editZoneWarehouse')?.value || 'Warehouse A').trim();
                        const description = (document.getElementById('editZoneDesc')?.value || '').trim();
                        const status = document.getElementById('editZoneStatus')?.value || 'Active';

                        const alertBox = document.getElementById('modalEditZoneAlert');
                        const submitBtn = document.getElementById('btnSubmitEditZone');

                        if (!id || !code || !name || !type) {
                            if (alertBox) {
                                alertBox.innerText = 'Zone Code, Zone Name, and Zone Type are required.';
                                alertBox.style.display = 'block';
                                alertBox.style.background = '#fef2f2';
                                alertBox.style.color = '#dc2626';
                                alertBox.style.border = '1px solid #fecaca';
                            }
                            return;
                        }

                        const camCheckboxes = document.querySelectorAll('#editZoneCamContainer input[type="checkbox"]:checked');
                        const selectedCameras = Array.from(camCheckboxes).map(cb => cb.value);

                        if (submitBtn) {
                            submitBtn.disabled = true;
                            submitBtn.innerText = 'Saving...';
                        }

                        try {
                            const res = await fetch(`/api/vision/zones/${id}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    zone_code: code,
                                    zone_name: name,
                                    zone_type: type,
                                    warehouse: warehouse,
                                    description: description,
                                    status: status,
                                    cameras: selectedCameras
                                })
                            });

                            const data = await res.json();
                            if (res.ok && data.success) {
                                closeEditZoneModal();
                                showVisionZoneAlert(`Zone '${data.zone.zone_code}' updated successfully.`);
                                fetchVisionZones();
                            } else {
                                if (alertBox) {
                                    alertBox.innerText = data.message || 'Failed to update warehouse zone.';
                                    alertBox.style.display = 'block';
                                    alertBox.style.background = '#fef2f2';
                                    alertBox.style.color = '#dc2626';
                                    alertBox.style.border = '1px solid #fecaca';
                                }
                            }
                        } catch (e) {
                            console.error(e);
                            if (alertBox) {
                                alertBox.innerText = 'Network error while updating zone.';
                                alertBox.style.display = 'block';
                                alertBox.style.background = '#fef2f2';
                                alertBox.style.color = '#dc2626';
                                alertBox.style.border = '1px solid #fecaca';
                            }
                        } finally {
                            if (submitBtn) {
                                submitBtn.disabled = false;
                                submitBtn.innerText = 'Save Changes';
                            }
                        }
                    }

                    // VIEW MODAL
                    async function openViewZoneModal(identifier) {
                        try {
                            const res = await fetch(`/api/vision/zones/${identifier}`);
                            if (!res.ok) throw new Error('Zone not found');
                            const data = await res.json();
                            const zone = data.zone;

                            currentViewedZoneId = zone.id;
                            document.getElementById('viewZoneId').innerText = zone.id;
                            document.getElementById('viewZoneCode').innerText = zone.zone_code;
                            document.getElementById('viewZoneName').innerText = zone.zone_name;

                            const typeLabel = zone.zone_type_label || ZONE_TYPE_LABELS[zone.zone_type] || zone.zone_type;
                            document.getElementById('viewZoneType').innerText = typeLabel;
                            document.getElementById('viewZoneWarehouse').innerText = zone.warehouse || 'Warehouse A';

                            const statusContainer = document.getElementById('viewZoneStatusContainer');
                            if (statusContainer) {
                                const isActive = zone.status === 'Active';
                                statusContainer.innerHTML = isActive
                                    ? `<span class="badge sent">Active</span>`
                                    : `<span class="badge pending">Disabled</span>`;
                            }

                            document.getElementById('viewZoneDesc').innerText = zone.description || 'No description provided';
                            document.getElementById('viewZoneCreatedAt').innerText = zone.created_at || '-';
                            document.getElementById('viewZoneUpdatedAt').innerText = zone.updated_at || '-';

                            const cameras = Array.isArray(zone.cameras) ? zone.cameras : [];
                            const camBadge = document.getElementById('viewZoneCamCountBadge');
                            if (camBadge) {
                                camBadge.innerText = `${cameras.length} Camera${cameras.length === 1 ? '' : 's'}`;
                                camBadge.className = cameras.length > 0 ? 'badge sent' : 'badge pending';
                            }

                            const camsContainer = document.getElementById('viewZoneCamerasContainer');
                            if (camsContainer) {
                                if (cameras.length === 0) {
                                    camsContainer.innerHTML = '<span style="color:var(--text-muted); font-size:0.85rem;">No cameras associated with this zone.</span>';
                                } else {
                                    camsContainer.innerHTML = cameras.map(c => {
                                        const roiBadge = c.roi_configured
                                            ? `<span class="badge" style="background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; font-size:0.72rem;">ROI: Configured</span>`
                                            : `<span class="badge" style="background:#f8fafc; color:#94a3b8; border:1px solid #e2e8f0; font-size:0.72rem;">ROI: Not Set</span>`;
                                        return `
                                            <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:6px; padding:6px 10px; display:inline-flex; align-items:center; gap:8px;">
                                                <code style="font-size:0.85rem; font-weight:800; color:var(--accent);">${escapeHtml(c.camera_code)}</code>
                                                <span style="font-size:0.82rem; color:var(--text-main); font-weight:600;">${escapeHtml(c.name)}</span>
                                                <span style="font-size:0.75rem; color:var(--text-muted);">(${escapeHtml(c.location || 'General')})</span>
                                                ${roiBadge}
                                                <button type="button" class="btn-primary btn-sm" style="padding:2px 7px; font-size:0.72rem; background:#0284c7; color:#fff;" onclick="closeViewZoneModal(); openRoiEditorModal(${zone.id}, '${escapeHtml(c.camera_id)}');">📐 ROI</button>
                                            </div>
                                        `;
                                    }).join('');
                                }
                            }

                            const modal = document.getElementById('modalViewVisionZone');
                            if (modal) modal.classList.add('active');
                        } catch (e) {
                            console.error(e);
                            showVisionZoneAlert(`Failed to load details for zone '${identifier}'.`, 'error');
                        }
                    }

                    function closeViewZoneModal() {
                        const modal = document.getElementById('modalViewVisionZone');
                        if (modal) modal.classList.remove('active');
                    }

                    function transitionZoneViewToEdit() {
                        const id = currentViewedZoneId;
                        closeViewZoneModal();
                        if (id) openEditZoneModal(id);
                    }

                    // STATUS TOGGLE & DELETE
                    async function toggleZoneStatus(id, currentStatus) {
                        const newStatus = currentStatus === 'Active' ? 'Disabled' : 'Active';
                        try {
                            const res = await fetch(`/api/vision/zones/${id}`, {
                                method: 'PATCH',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ status: newStatus })
                            });
                            const data = await res.json();
                            if (res.ok && data.success) {
                                showVisionZoneAlert(`Zone '${data.zone.zone_code}' is now ${newStatus}.`);
                                fetchVisionZones();
                            } else {
                                showVisionZoneAlert(data.message || 'Failed to update zone status.', 'error');
                            }
                        } catch (e) {
                            console.error(e);
                            showVisionZoneAlert('Network error while toggling zone status.', 'error');
                        }
                    }

                    async function deleteVisionZone(id, zoneCode) {
                        if (!confirm(`Are you sure you want to delete warehouse zone '${zoneCode}'?\nThis will remove the zone and its camera associations.`)) {
                            return;
                        }

                        try {
                            const res = await fetch(`/api/vision/zones/${id}`, {
                                method: 'DELETE'
                            });
                            const data = await res.json();
                            if (res.ok && data.success) {
                                showVisionZoneAlert(data.message || `Zone '${zoneCode}' deleted successfully.`);
                                fetchVisionZones();
                            } else {
                                showVisionZoneAlert(data.message || 'Failed to delete zone.', 'error');
                            }
                        } catch (e) {
                            console.error(e);
                            showVisionZoneAlert('Network error while deleting zone.', 'error');
                        }
                    }

                    // ==========================================
                    // VISUAL ZONE / ROI EDITOR MANAGEMENT
                    // ==========================================
                    let currentRoiZone = null;
                    let currentRoiCameraId = null;
                    let roiShapeType = 'POLYGON'; // 'POLYGON' or 'RECTANGLE'
                    let roiPoints = [];           // Array of {x, y} normalized [0.0 - 1.0]
                    let roiSavedPoints = [];      // Snapshot of saved points for reset
                    let roiDraggedIndex = -1;     // Index of point currently being dragged
                    let roiHoveredIndex = -1;     // Index of point currently hovered
                    let roiCanvasImg = null;      // Image object for camera preview
                    let roiImgLoaded = false;
                    let roiFeedInfo = { is_live: false, feed_mode: 'PREVIEW / TEST IMAGE' };
                    let roiRectStart = null;      // For drawing rectangle
                    let isDrawingRect = false;

                    function showRoiAlert(msg, type = 'error') {
                        const alertBox = document.getElementById('roiAlertBox');
                        if (!alertBox) return;
                        alertBox.innerText = msg;
                        if (type === 'error') {
                            alertBox.style.background = '#fef2f2';
                            alertBox.style.color = '#dc2626';
                            alertBox.style.border = '1px solid #fecaca';
                        } else {
                            alertBox.style.background = '#ecfdf5';
                            alertBox.style.color = '#059669';
                            alertBox.style.border = '1px solid #a7f3d0';
                        }
                        alertBox.style.display = 'block';
                        setTimeout(() => { if (alertBox) alertBox.style.display = 'none'; }, 6000);
                    }

                    function hideRoiAlert() {
                        const alertBox = document.getElementById('roiAlertBox');
                        if (alertBox) alertBox.style.display = 'none';
                    }

                    async function openRoiEditorModal(zoneIdentifier, preferredCameraId = null) {
                        try {
                            const res = await fetch(`/api/vision/zones/${zoneIdentifier}`);
                            if (!res.ok) throw new Error('Zone not found');
                            const data = await res.json();
                            currentRoiZone = data.zone;

                            // Fill zone info in modal header
                            document.getElementById('roiZoneCodeBadge').innerText = currentRoiZone.zone_code;
                            document.getElementById('roiZoneNameText').innerText = currentRoiZone.zone_name;
                            document.getElementById('roiZoneTypeBadge').innerText = currentRoiZone.zone_type_label || currentRoiZone.zone_type;
                            document.getElementById('roiZoneWarehouseText').innerText = currentRoiZone.warehouse || 'Warehouse A';

                            // Populate camera dropdown
                            const camSelect = document.getElementById('roiCameraSelect');
                            const cameras = currentRoiZone.cameras || [];
                            if (cameras.length === 0) {
                                alert(`Zone '${currentRoiZone.zone_code}' has no associated cameras. Please associate at least one camera in the Camera Master or Edit Zone modal first.`);
                                return;
                            }

                            camSelect.innerHTML = cameras.map(c => {
                                const statusTxt = c.roi_configured ? '[ROI: Configured]' : '[ROI: Not Configured]';
                                return `<option value="${escapeHtml(c.camera_id)}">${escapeHtml(c.camera_code)} - ${escapeHtml(c.name)} (${escapeHtml(c.location || 'General')}) ${statusTxt}</option>`;
                            }).join('');

                            // Select preferred camera or first
                            let targetCamId = cameras[0].camera_id;
                            if (preferredCameraId && cameras.some(c => c.camera_id === preferredCameraId || c.camera_code === preferredCameraId)) {
                                targetCamId = preferredCameraId;
                            }
                            camSelect.value = targetCamId;
                            currentRoiCameraId = targetCamId;

                            // Open modal
                            const modal = document.getElementById('modalConfigureZoneRoi');
                            if (modal) modal.classList.add('active');

                            // Initialize canvas event listeners once
                            initRoiCanvasEvents();

                            // Load ROI for selected camera
                            await loadRoiForSelectedCamera();
                        } catch (e) {
                            console.error("Failed to open ROI editor:", e);
                            alert("Failed to load zone details for ROI configuration.");
                        }
                    }

                    function closeRoiEditorModal() {
                        const modal = document.getElementById('modalConfigureZoneRoi');
                        if (modal) modal.classList.remove('active');
                        currentRoiZone = null;
                        currentRoiCameraId = null;
                        roiPoints = [];
                        roiSavedPoints = [];
                    }

                    async function handleRoiCameraChange() {
                        const camSelect = document.getElementById('roiCameraSelect');
                        currentRoiCameraId = camSelect.value;
                        await loadRoiForSelectedCamera();
                    }

                    async function loadRoiForSelectedCamera() {
                        if (!currentRoiZone || !currentRoiCameraId) return;
                        hideRoiAlert();

                        // 1. Fetch preview info
                        try {
                            const pRes = await fetch(`/api/vision/cameras/${currentRoiCameraId}/preview_info`);
                            if (pRes.ok) {
                                roiFeedInfo = await pRes.json();
                            } else {
                                roiFeedInfo = { is_live: false, feed_mode: 'PREVIEW / TEST IMAGE', preview_url: `/api/vision/cameras/${currentRoiCameraId}/preview.jpg` };
                            }
                        } catch (e) {
                            roiFeedInfo = { is_live: false, feed_mode: 'PREVIEW / TEST IMAGE', preview_url: `/api/vision/cameras/${currentRoiCameraId}/preview.jpg` };
                        }

                        // Update feed status pill
                        const feedBadge = document.getElementById('roiFeedModeBadge');
                        if (feedBadge) {
                            feedBadge.innerText = roiFeedInfo.feed_mode;
                            feedBadge.className = roiFeedInfo.is_live ? 'badge sent' : 'badge pending';
                        }

                        // 2. Fetch existing ROI
                        try {
                            const rRes = await fetch(`/api/vision/zones/${currentRoiZone.id}/cameras/${currentRoiCameraId}/roi`);
                            const rData = await rRes.json();
                            const configBadge = document.getElementById('roiConfigStateBadge');

                            if (rRes.ok && rData.success && rData.data && rData.data.configured) {
                                const roi = rData.data.roi;
                                roiPoints = Array.isArray(roi.coordinates) ? JSON.parse(JSON.stringify(roi.coordinates)) : [];
                                roiShapeType = roi.shape_type || 'POLYGON';
                                if (configBadge) {
                                    configBadge.innerText = 'Configured';
                                    configBadge.className = 'badge sent';
                                }
                            } else {
                                roiPoints = [];
                                roiShapeType = 'POLYGON';
                                if (configBadge) {
                                    configBadge.innerText = 'Not Configured';
                                    configBadge.className = 'badge pending';
                                }
                            }
                        } catch (e) {
                            console.warn("Failed to fetch ROI:", e);
                            roiPoints = [];
                            roiShapeType = 'POLYGON';
                        }

                        roiSavedPoints = JSON.parse(JSON.stringify(roiPoints));
                        updateShapeTypeButtons();

                        // 3. Load preview image and render canvas
                        loadRoiCanvasImage();
                    }

                    function loadRoiCanvasImage() {
                        roiCanvasImg = new Image();
                        roiImgLoaded = false;
                        roiCanvasImg.crossOrigin = "anonymous";
                        roiCanvasImg.onload = function() {
                            roiImgLoaded = true;
                            renderRoiCanvas();
                        };
                        roiCanvasImg.onerror = function() {
                            roiImgLoaded = false;
                            renderRoiCanvas();
                        };
                        // Add cache buster
                        roiCanvasImg.src = `${roiFeedInfo.preview_url}?t=${Date.now()}`;
                    }

                    function setRoiShapeType(type) {
                        roiShapeType = type;
                        updateShapeTypeButtons();

                        if (type === 'RECTANGLE' && roiPoints.length !== 4) {
                            // Default rectangle if none or invalid
                            roiPoints = [
                                { x: 0.18, y: 0.22 },
                                { x: 0.82, y: 0.22 },
                                { x: 0.82, y: 0.78 },
                                { x: 0.18, y: 0.78 }
                            ];
                        } else if (type === 'POLYGON' && roiPoints.length === 0) {
                            // Default initial 4-point polygon
                            roiPoints = [
                                { x: 0.20, y: 0.25 },
                                { x: 0.80, y: 0.25 },
                                { x: 0.85, y: 0.75 },
                                { x: 0.15, y: 0.75 }
                            ];
                        }
                        renderRoiCanvas();
                    }

                    function updateShapeTypeButtons() {
                        const btnPoly = document.getElementById('btnToolPolygon');
                        const btnRect = document.getElementById('btnToolRectangle');
                        if (btnPoly && btnRect) {
                            if (roiShapeType === 'POLYGON') {
                                btnPoly.className = 'btn-primary btn-sm';
                                btnRect.className = 'btn-secondary btn-sm';
                            } else {
                                btnPoly.className = 'btn-secondary btn-sm';
                                btnRect.className = 'btn-primary btn-sm';
                            }
                        }
                    }

                    function resetRoiPoints() {
                        roiPoints = JSON.parse(JSON.stringify(roiSavedPoints));
                        renderRoiCanvas();
                    }

                    function clearRoiPoints() {
                        roiPoints = [];
                        renderRoiCanvas();
                    }

                    // CANVAS DRAWING & COORDINATE CONVERSION
                    let roiCanvasEventsInitialized = false;
                    function initRoiCanvasEvents() {
                        if (roiCanvasEventsInitialized) return;
                        roiCanvasEventsInitialized = true;

                        const canvas = document.getElementById('roiCanvas');
                        if (!canvas) return;

                        canvas.addEventListener('mousedown', onRoiCanvasMouseDown);
                        window.addEventListener('mousemove', onRoiCanvasMouseMove);
                        window.addEventListener('mouseup', onRoiCanvasMouseUp);
                        canvas.addEventListener('contextmenu', onRoiCanvasContextMenu);
                        canvas.addEventListener('dblclick', onRoiCanvasDblClick);
                    }

                    function getCanvasPointerPos(e) {
                        const canvas = document.getElementById('roiCanvas');
                        if (!canvas) return { x: 0, y: 0, nx: 0, ny: 0 };
                        const rect = canvas.getBoundingClientRect();
                        const scaleX = canvas.width / rect.width;
                        const scaleY = canvas.height / rect.height;

                        const px = (e.clientX - rect.left) * scaleX;
                        const py = (e.clientY - rect.top) * scaleY;

                        const nx = Math.max(0, Math.min(1, px / canvas.width));
                        const ny = Math.max(0, Math.min(1, py / canvas.height));

                        return { px, py, nx, ny };
                    }

                    function onRoiCanvasMouseDown(e) {
                        if (!currentRoiZone || e.button !== 0) return;
                        const { px, py, nx, ny } = getCanvasPointerPos(e);
                        const canvas = document.getElementById('roiCanvas');

                        // Check if clicking existing handle (within 12px)
                        let clickedIndex = -1;
                        for (let i = 0; i < roiPoints.length; i++) {
                            const p = roiPoints[i];
                            const hx = p.x * canvas.width;
                            const hy = p.y * canvas.height;
                            const dist = Math.hypot(px - hx, py - hy);
                            if (dist <= 12) {
                                clickedIndex = i;
                                break;
                            }
                        }

                        if (clickedIndex >= 0) {
                            roiDraggedIndex = clickedIndex;
                            return;
                        }

                        // If using RECTANGLE tool and click outside handle, start drag-draw
                        if (roiShapeType === 'RECTANGLE') {
                            isDrawingRect = true;
                            roiRectStart = { nx, ny };
                            roiPoints = [
                                { x: nx, y: ny },
                                { x: nx, y: ny },
                                { x: nx, y: ny },
                                { x: nx, y: ny }
                            ];
                            renderRoiCanvas();
                            return;
                        }

                        // If using POLYGON tool, click adds a new point
                        if (roiShapeType === 'POLYGON') {
                            roiPoints.push({ x: round4(nx), y: round4(ny) });
                            renderRoiCanvas();
                        }
                    }

                    function onRoiCanvasMouseMove(e) {
                        const canvas = document.getElementById('roiCanvas');
                        if (!canvas) return;
                        const { px, py, nx, ny } = getCanvasPointerPos(e);

                        // Update HUD readout
                        const hudPos = document.getElementById('roiCursorReadout');
                        if (hudPos) {
                            hudPos.innerText = `X: ${nx.toFixed(3)}, Y: ${ny.toFixed(3)}`;
                        }

                        // Handle vertex dragging
                        if (roiDraggedIndex >= 0 && roiDraggedIndex < roiPoints.length) {
                            if (roiShapeType === 'RECTANGLE') {
                                adjustRectangleVertex(roiDraggedIndex, nx, ny);
                            } else {
                                roiPoints[roiDraggedIndex] = { x: round4(nx), y: round4(ny) };
                            }
                            renderRoiCanvas();
                            return;
                        }

                        // Handle rectangle drag-draw
                        if (isDrawingRect && roiRectStart) {
                            const x1 = Math.min(roiRectStart.nx, nx);
                            const x2 = Math.max(roiRectStart.nx, nx);
                            const y1 = Math.min(roiRectStart.ny, ny);
                            const y2 = Math.max(roiRectStart.ny, ny);
                            roiPoints = [
                                { x: round4(x1), y: round4(y1) },
                                { x: round4(x2), y: round4(y1) },
                                { x: round4(x2), y: round4(y2) },
                                { x: round4(x1), y: round4(y2) }
                            ];
                            renderRoiCanvas();
                            return;
                        }

                        // Hover detection for cursor styling
                        let hoverIdx = -1;
                        for (let i = 0; i < roiPoints.length; i++) {
                            const p = roiPoints[i];
                            const hx = p.x * canvas.width;
                            const hy = p.y * canvas.height;
                            if (Math.hypot(px - hx, py - hy) <= 12) {
                                hoverIdx = i;
                                break;
                            }
                        }
                        if (hoverIdx !== roiHoveredIndex) {
                            roiHoveredIndex = hoverIdx;
                            canvas.style.cursor = hoverIdx >= 0 ? 'grab' : 'crosshair';
                            renderRoiCanvas();
                        }
                    }

                    function onRoiCanvasMouseUp(e) {
                        roiDraggedIndex = -1;
                        isDrawingRect = false;
                        roiRectStart = null;
                        renderRoiCanvas();
                    }

                    function onRoiCanvasContextMenu(e) {
                        e.preventDefault();
                        deleteHandleAtPointer(e);
                    }

                    function onRoiCanvasDblClick(e) {
                        e.preventDefault();
                        deleteHandleAtPointer(e);
                    }

                    function deleteHandleAtPointer(e) {
                        if (roiShapeType === 'RECTANGLE') return; // Rectangles must maintain 4 vertices
                        const { px, py } = getCanvasPointerPos(e);
                        const canvas = document.getElementById('roiCanvas');
                        for (let i = 0; i < roiPoints.length; i++) {
                            const p = roiPoints[i];
                            const hx = p.x * canvas.width;
                            const hy = p.y * canvas.height;
                            if (Math.hypot(px - hx, py - hy) <= 14) {
                                if (roiPoints.length <= 3) {
                                    showRoiAlert("A polygon requires at least 3 points. Cannot delete further.", "error");
                                    return;
                                }
                                roiPoints.splice(i, 1);
                                renderRoiCanvas();
                                return;
                            }
                        }
                    }

                    function adjustRectangleVertex(idx, nx, ny) {
                        // idx: 0=TL, 1=TR, 2=BR, 3=BL
                        nx = round4(nx);
                        ny = round4(ny);
                        if (idx === 0) { // Top-Left
                            roiPoints[0] = { x: nx, y: ny };
                            roiPoints[1].y = ny;
                            roiPoints[3].x = nx;
                        } else if (idx === 1) { // Top-Right
                            roiPoints[1] = { x: nx, y: ny };
                            roiPoints[0].y = ny;
                            roiPoints[2].x = nx;
                        } else if (idx === 2) { // Bottom-Right
                            roiPoints[2] = { x: nx, y: ny };
                            roiPoints[3].y = ny;
                            roiPoints[1].x = nx;
                        } else if (idx === 3) { // Bottom-Left
                            roiPoints[3] = { x: nx, y: ny };
                            roiPoints[2].y = ny;
                            roiPoints[0].x = nx;
                        }
                    }

                    function round4(v) {
                        return Math.round(v * 10000) / 10000;
                    }

                    // RENDER CANVAS
                    function renderRoiCanvas() {
                        const canvas = document.getElementById('roiCanvas');
                        if (!canvas) return;
                        const ctx = canvas.getContext('2d');
                        const W = canvas.width;
                        const H = canvas.height;

                        ctx.clearRect(0, 0, W, H);

                        // 1. Draw camera image or perspective background
                        if (roiImgLoaded && roiCanvasImg) {
                            ctx.drawImage(roiCanvasImg, 0, 0, W, H);
                        } else {
                            // Dark technical grid
                            ctx.fillStyle = '#0f172a';
                            ctx.fillRect(0, 0, W, H);

                            ctx.strokeStyle = '#1e293b';
                            ctx.lineWidth = 1;
                            const gridSize = 40;
                            for (let x = 0; x < W; x += gridSize) {
                                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
                            }
                            for (let y = 0; y < H; y += gridSize) {
                                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
                            }
                            ctx.fillStyle = '#64748b';
                            ctx.font = 'bold 15px monospace';
                            ctx.fillText("PREVIEW / TEST CAMERA FRAME", 24, 38);
                        }

                        // Update point telemetry readout in drawer
                        renderPointCoordinatesDrawer();

                        if (roiPoints.length === 0) return;

                        // 2. Draw Polygon / Region
                        ctx.beginPath();
                        const p0 = roiPoints[0];
                        ctx.moveTo(p0.x * W, p0.y * H);
                        for (let i = 1; i < roiPoints.length; i++) {
                            ctx.lineTo(roiPoints[i].x * W, roiPoints[i].y * H);
                        }
                        if (roiPoints.length >= 3) {
                            ctx.closePath();
                            // Translucent zone fill
                            ctx.fillStyle = 'rgba(14, 165, 233, 0.28)';
                            ctx.fill();
                        }

                        // Outline stroke
                        ctx.strokeStyle = '#0284c7';
                        ctx.lineWidth = 2.5;
                        ctx.setLineDash([6, 3]);
                        ctx.stroke();
                        ctx.setLineDash([]); // Reset line dash

                        // 3. Draw Zone Label Badge in center of polygon
                        if (roiPoints.length >= 3 && currentRoiZone) {
                            let avgX = 0, avgY = 0;
                            roiPoints.forEach(p => { avgX += p.x; avgY += p.y; });
                            avgX = (avgX / roiPoints.length) * W;
                            avgY = (avgY / roiPoints.length) * H;

                            const label = `${currentRoiZone.zone_code} (${currentRoiZone.zone_name})`;
                            ctx.font = 'bold 12px sans-serif';
                            const textWidth = ctx.measureText(label).width;
                            const pad = 6;

                            ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
                            ctx.beginPath();
                            ctx.roundRect(avgX - textWidth / 2 - pad, avgY - 10 - pad, textWidth + pad * 2, 20 + pad, 4);
                            ctx.fill();
                            ctx.strokeStyle = '#38bdf8';
                            ctx.lineWidth = 1;
                            ctx.stroke();

                            ctx.fillStyle = '#ffffff';
                            ctx.textAlign = 'center';
                            ctx.textBaseline = 'middle';
                            ctx.fillText(label, avgX, avgY);
                            ctx.textAlign = 'left';
                            ctx.textBaseline = 'alphabetic';
                        }

                        // 4. Draw Vertex Handles
                        for (let i = 0; i < roiPoints.length; i++) {
                            const p = roiPoints[i];
                            const hx = p.x * W;
                            const hy = p.y * H;
                            const isHovered = (i === roiHoveredIndex);
                            const isDragged = (i === roiDraggedIndex);

                            ctx.beginPath();
                            ctx.arc(hx, hy, isHovered || isDragged ? 8 : 6, 0, Math.PI * 2);
                            ctx.fillStyle = isDragged ? '#f59e0b' : (isHovered ? '#38bdf8' : '#ffffff');
                            ctx.fill();
                            ctx.lineWidth = 2;
                            ctx.strokeStyle = '#0284c7';
                            ctx.stroke();

                            // Number label next to handle
                            ctx.font = 'bold 10px monospace';
                            ctx.fillStyle = '#ffffff';
                            ctx.shadowColor = '#000000';
                            ctx.shadowBlur = 4;
                            ctx.fillText(`${i + 1}`, hx + 9, hy - 6);
                            ctx.shadowBlur = 0;
                        }
                    }

                    function renderPointCoordinatesDrawer() {
                        const countEl = document.getElementById('roiVertexCountBadge');
                        const coordsListEl = document.getElementById('roiCoordinatesList');
                        if (countEl) {
                            countEl.innerText = `${roiPoints.length} Point${roiPoints.length === 1 ? '' : 's'}`;
                            countEl.className = roiPoints.length >= 3 ? 'badge sent' : 'badge pending';
                        }
                        if (coordsListEl) {
                            if (roiPoints.length === 0) {
                                coordsListEl.innerHTML = '<span style="color:var(--text-muted); font-size:0.82rem;">No boundary points defined yet. Click on the camera frame above to place points.</span>';
                            } else {
                                coordsListEl.innerHTML = roiPoints.map((p, idx) => `
                                    <span style="background:var(--panel-bg); border:1px solid var(--border-light); padding:2px 7px; border-radius:4px; font-size:0.78rem; font-family:monospace;">
                                        <strong>P${idx + 1}:</strong> (${p.x.toFixed(4)}, ${p.y.toFixed(4)})
                                    </span>
                                `).join(' ');
                            }
                        }
                    }

                    // SAVE ROI TO BACKEND
                    async function saveCurrentRoi() {
                        if (!currentRoiZone || !currentRoiCameraId) return;
                        hideRoiAlert();

                        const minPts = (roiShapeType === 'RECTANGLE') ? 4 : 3;
                        if (roiPoints.length < minPts) {
                            showRoiAlert(`Please define at least ${minPts} points for a ${roiShapeType.toLowerCase()} boundary.`);
                            return;
                        }

                        const saveBtn = document.getElementById('btnSaveRoi');
                        if (saveBtn) {
                            saveBtn.disabled = true;
                            saveBtn.innerText = 'Saving ROI...';
                        }

                        try {
                            const res = await fetch(`/api/vision/zones/${currentRoiZone.id}/cameras/${currentRoiCameraId}/roi`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    shape_type: roiShapeType,
                                    coordinates: roiPoints
                                })
                            });
                            const data = await res.json();

                            if (res.ok && data.success) {
                                roiSavedPoints = JSON.parse(JSON.stringify(roiPoints));
                                const configBadge = document.getElementById('roiConfigStateBadge');
                                if (configBadge) {
                                    configBadge.innerText = 'Configured';
                                    configBadge.className = 'badge sent';
                                }
                                showRoiAlert(`✓ ROI saved successfully for ${currentRoiZone.zone_code} on camera ${data.data.camera_code}.`, 'success');
                                fetchVisionZones();
                            } else {
                                showRoiAlert(data.message || 'Failed to save ROI configuration.');
                            }
                        } catch (e) {
                            console.error("Save ROI error:", e);
                            showRoiAlert('Network error while saving ROI.');
                        } finally {
                            if (saveBtn) {
                                saveBtn.disabled = false;
                                saveBtn.innerText = '💾 Save ROI';
                            }
                        }
                    }

                    // ==========================================
                    // OBJECT DETECTION ENGINE CLIENT LOGIC
                    // ==========================================
                    let dtCamerasList = [];
                    let dtSamplesList = [];

                    async function initDetectionTestUI() {
                        try {
                            const resInfo = await fetch('/api/vision/detection/info');
                            if (resInfo.ok) {
                                const data = await resInfo.json();
                                const info = data.data || {};
                                const badge = document.getElementById('dtEngineDeviceBadge');
                                const kpiDevice = document.getElementById('kpi-dt-device');
                                const kpiDeviceSub = document.getElementById('kpi-dt-device-sub');
                                if (badge) {
                                    badge.innerText = `Detector: ${info.model_name || 'YOLO11'} (${(info.device || 'CPU').toUpperCase()})`;
                                }
                                if (kpiDevice) {
                                    kpiDevice.innerText = (info.device || 'CPU').toUpperCase();
                                }
                                if (kpiDeviceSub) {
                                    kpiDeviceSub.innerText = info.device_name || (info.cuda_available ? 'CUDA Accelerated' : 'CPU Host');
                                }
                                if (info.confidence_threshold) {
                                    const slider = document.getElementById('dtConfSlider');
                                    const display = document.getElementById('dtConfDisplay');
                                    if (slider) slider.value = info.confidence_threshold;
                                    if (display) display.innerText = `${parseFloat(info.confidence_threshold).toFixed(2)} (${Math.round(info.confidence_threshold*100)}%)`;
                                }
                            }
                        } catch (e) {
                            console.warn("Could not load detector info:", e);
                        }

                        try {
                            const resCams = await fetch('/api/vision/cameras');
                            if (resCams.ok) {
                                const cams = await resCams.json();
                                dtCamerasList = Array.isArray(cams) ? cams : (cams.data || []);
                                const sel = document.getElementById('dtCameraSelect');
                                if (sel) {
                                    if (dtCamerasList.length === 0) {
                                        sel.innerHTML = '<option value="">No cameras registered in Camera Master</option>';
                                    } else {
                                        sel.innerHTML = dtCamerasList.map(c => `
                                            <option value="${escapeHtml(c.camera_id)}">
                                                ${escapeHtml(c.camera_code)} - ${escapeHtml(c.camera_name)} (${escapeHtml(c.location || 'General')})
                                            </option>
                                        `).join('');
                                    }
                                }
                            }
                        } catch (e) {
                            console.warn("Could not populate detection cameras:", e);
                        }

                        try {
                            const resSamples = await fetch('/api/vision/detection/samples');
                            if (resSamples.ok) {
                                const data = await resSamples.json();
                                dtSamplesList = data.samples || [];
                                const sel = document.getElementById('dtSampleSelect');
                                if (sel && dtSamplesList.length > 0) {
                                    sel.innerHTML = dtSamplesList.map(s => `
                                        <option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>
                                    `).join('');
                                }
                            }
                        } catch (e) {
                            console.warn("Could not populate sample scenes:", e);
                        }
                    }

                    function handleDetectionSourceChange() {
                        const srcType = document.getElementById('dtSourceTypeSelect')?.value || 'camera';
                        const camBox = document.getElementById('dtCameraSelectContainer');
                        const sampleBox = document.getElementById('dtSampleSelectContainer');
                        const uploadBox = document.getElementById('dtUploadContainer');

                        if (camBox) camBox.style.display = (srcType === 'camera') ? 'block' : 'none';
                        if (sampleBox) sampleBox.style.display = (srcType === 'sample') ? 'block' : 'none';
                        if (uploadBox) uploadBox.style.display = (srcType === 'upload') ? 'block' : 'none';
                    }

                    async function runDetectionTest() {
                        const btn = document.getElementById('btnRunDetection');
                        const originalText = btn ? btn.innerHTML : 'Run Object Detection';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Inferencing...';
                        }

                        const srcType = document.getElementById('dtSourceTypeSelect')?.value || 'camera';
                        const confVal = parseFloat(document.getElementById('dtConfSlider')?.value || '0.25');
                        const deviceVal = document.getElementById('dtDeviceSelect')?.value || 'auto';

                        let payload = {
                            conf_threshold: confVal,
                            device: deviceVal
                        };

                        try {
                            if (srcType === 'camera') {
                                const camId = document.getElementById('dtCameraSelect')?.value;
                                if (!camId) {
                                    alert("Please select a camera node.");
                                    return;
                                }
                                payload.camera_id = camId;
                            } else if (srcType === 'sample') {
                                payload.sample_scene = document.getElementById('dtSampleSelect')?.value;
                            } else if (srcType === 'upload') {
                                const fileInput = document.getElementById('dtFileInput');
                                if (!fileInput.files || fileInput.files.length === 0) {
                                    alert("Please select an image file to upload.");
                                    return;
                                }
                                const file = fileInput.files[0];
                                payload.image_base64 = await new Promise((resolve, reject) => {
                                    const reader = new FileReader();
                                    reader.onload = () => resolve(reader.result);
                                    reader.onerror = reject;
                                    reader.readAsDataURL(file);
                                });
                            }

                            const res = await fetch('/api/vision/detection/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            const data = await res.json();
                            if (res.ok && data.success) {
                                renderDetectionResults(data);
                            } else {
                                alert(data.message || data.error || "Inference failed.");
                            }
                        } catch (e) {
                            console.error("Detection error:", e);
                            alert("Detection request failed: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalText;
                            }
                        }
                    }

                    function renderDetectionResults(data) {
                        const perf = data.performance || {};
                        const modelInfo = data.model_info || {};
                        const detections = data.detections || [];

                        const kpiDevice = document.getElementById('kpi-dt-device');
                        const kpiDeviceSub = document.getElementById('kpi-dt-device-sub');
                        const kpiInfer = document.getElementById('kpi-dt-infer-ms');
                        const kpiTotal = document.getElementById('kpi-dt-total-ms');
                        const kpiCount = document.getElementById('kpi-dt-count');
                        const kpiCountSub = document.getElementById('kpi-dt-count-sub');

                        if (kpiDevice) kpiDevice.innerText = (modelInfo.device || 'CPU').toUpperCase();
                        if (kpiDeviceSub) kpiDeviceSub.innerText = `${modelInfo.model_name || 'yolo11s.pt'} (Conf ≥ ${modelInfo.confidence_threshold})`;
                        if (kpiInfer) kpiInfer.innerText = `${perf.inference_ms || 0} ms`;
                        if (kpiTotal) kpiTotal.innerText = `${perf.total_ms || 0} ms`;
                        if (kpiCount) kpiCount.innerText = detections.length;
                        if (kpiCountSub) kpiCountSub.innerText = `${detections.length} spatial object${detections.length === 1 ? '' : 's'}`;

                        const imgEl = document.getElementById('dtAnnotatedImg');
                        const emptyPrompt = document.getElementById('dtEmptyPrompt');
                        const resBadge = document.getElementById('dtFrameResolutionBadge');

                        if (data.annotated_image_url && imgEl) {
                            imgEl.src = data.annotated_image_url;
                            imgEl.style.display = 'block';
                            if (emptyPrompt) emptyPrompt.style.display = 'none';
                        }
                        if (resBadge) {
                            resBadge.className = 'badge sent';
                            resBadge.innerText = `${data.frame_width}×${data.frame_height} px | ${data.camera_id || 'Test Scene'}`;
                        }

                        const tbody = document.getElementById('dtResultsTableBody');
                        const countBadge = document.getElementById('dtTableCountBadge');
                        if (countBadge) countBadge.innerText = `${detections.length} Record${detections.length === 1 ? '' : 's'}`;

                        if (!tbody) return;

                        if (detections.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="5" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                        No objects detected above confidence threshold (${modelInfo.confidence_threshold || 0.25}). Try lowering the threshold or selecting a different frame.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = detections.map(d => {
                            const clsCode = escapeHtml(d.class_code);
                            const clsName = escapeHtml(d.class_name);
                            const rawCls = escapeHtml(d.raw_model_class);
                            const confPct = (d.confidence * 100).toFixed(1) + '%';
                            const normBbox = `[${d.bbox_normalized.x1.toFixed(3)}, ${d.bbox_normalized.y1.toFixed(3)}, ${d.bbox_normalized.x2.toFixed(3)}, ${d.bbox_normalized.y2.toFixed(3)}]`;
                            const normCenter = `(${d.center_normalized.x.toFixed(3)}, ${d.center_normalized.y.toFixed(3)})`;
                            
                            let roiBadge = '<span style="color:var(--text-muted); font-size:0.75rem;">No ROI</span>';
                            if (d.roi && d.roi.configured) {
                                roiBadge = d.roi.inside 
                                    ? `<span class="badge sent" style="font-size:0.75rem;">✓ INSIDE (${escapeHtml(d.roi.zone_code || 'Zone')})</span>`
                                    : `<span class="badge disabled-status" style="font-size:0.75rem;">✗ OUTSIDE</span>`;
                            }

                            return `
                                <tr>
                                    <td>
                                        <div style="display:flex; align-items:center; gap:6px;">
                                            <code style="font-size:0.85rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.08); padding:2px 6px; border-radius:4px;">${clsCode}</code>
                                            <span style="font-size:0.8rem; font-weight:600; color:var(--text-main);">${clsName}</span>
                                        </div>
                                        <div style="font-size:0.72rem; color:var(--text-muted); margin-top:2px;">Model: <code>${rawCls}</code></div>
                                    </td>
                                    <td>
                                        <strong style="color:var(--text-main);">${confPct}</strong>
                                        <div style="font-size:0.72rem; color:var(--text-muted); font-family:monospace;">${d.confidence}</div>
                                    </td>
                                    <td style="font-family:monospace; font-size:0.78rem; color:var(--text-muted);">
                                        <div>${normBbox}</div>
                                        <div style="font-size:0.72rem; color:var(--text-muted);">Px: [${d.bbox.x1}, ${d.bbox.y1}, ${d.bbox.x2}, ${d.bbox.y2}]</div>
                                    </td>
                                    <td style="font-family:monospace; font-size:0.78rem; text-align:center; color:var(--text-muted);">
                                        <div>${normCenter}</div>
                                        <div style="font-size:0.72rem; color:var(--text-muted);">Px: (${d.center.x}, ${d.center.y})</div>
                                    </td>
                                    <td style="text-align:center;">
                                        ${roiBadge}
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    // ==========================================
                    // PART 6: MULTI-OBJECT TRACKING ENGINE JAVASCRIPT
                    // ==========================================
                    let ttCurrentStep = 0;

                    async function initTrackingTestUI() {
                        try {
                            const resCams = await fetch('/api/vision/cameras');
                            if (resCams.ok) {
                                const cams = await resCams.json();
                                const camList = Array.isArray(cams) ? cams : (cams.data || []);
                                const sel = document.getElementById('ttCameraSelect');
                                if (sel) {
                                    sel.innerHTML = camList.map(c => `
                                        <option value="${c.camera_id}">${c.camera_code || c.camera_id} - ${c.name} (${c.location || 'General'})</option>
                                    `).join('');
                                }
                            }
                        } catch (e) {
                            console.warn("Could not load camera list for tracker:", e);
                        }

                        // Fetch tracker status
                        try {
                            const resStatus = await fetch('/api/vision/tracking/status');
                            if (resStatus.ok) {
                                const data = await resStatus.json();
                                const badge = document.getElementById('ttEngineStatusBadge');
                                if (badge) {
                                    badge.innerText = `Tracker: ByteTrack (${data.sessions?.length || 0} active sessions)`;
                                }
                            }
                        } catch (e) {}
                    }

                    function handleTrackingSourceChange() {
                        const src = document.getElementById('ttSourceTypeSelect')?.value;
                        const stepContainer = document.getElementById('ttStepContainer');
                        const sampleContainer = document.getElementById('ttSampleSelectContainer');
                        const uploadContainer = document.getElementById('ttUploadContainer');

                        if (stepContainer) stepContainer.style.display = (src === 'carrier_motion') ? 'block' : 'none';
                        if (sampleContainer) sampleContainer.style.display = (src === 'sample') ? 'block' : 'none';
                        if (uploadContainer) uploadContainer.style.display = (src === 'upload') ? 'block' : 'none';
                    }

                    async function stepTrackingFrame() {
                        const btn = document.getElementById('btnStepTracking');
                        const originalHtml = btn ? btn.innerHTML : 'Next Step';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Tracking...';
                        }

                        try {
                            const cameraId = document.getElementById('ttCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('ttSourceTypeSelect')?.value || 'carrier_motion';
                            const confThreshold = parseFloat(document.getElementById('ttConfSlider')?.value || 0.25);

                            let payload = {
                                camera_id: cameraId,
                                conf_threshold: confThreshold
                            };

                            if (srcType === 'carrier_motion') {
                                const stepInput = document.getElementById('ttStepInput');
                                const stepVal = parseInt(stepInput?.value || ttCurrentStep);
                                payload.sequence_step = stepVal;
                                ttCurrentStep = (stepVal + 1) % 20;
                                if (stepInput) stepInput.value = ttCurrentStep;
                            } else if (srcType === 'sample') {
                                payload.sample_scene = document.getElementById('ttSampleSelect')?.value;
                            }

                            const res = await fetch('/api/vision/tracking/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.error || data.message || "Tracking failed.");
                                return;
                            }

                            renderTrackingResults(data);
                        } catch (e) {
                            alert("Tracking request error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function runTrackingSequence() {
                        const btn = document.getElementById('btnRunSequence');
                        const originalHtml = btn ? btn.innerHTML : 'Run 5 Frames';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⚡</span> Running 5 Steps...';
                        }

                        try {
                            const cameraId = document.getElementById('ttCameraSelect')?.value || 'CAM-001';
                            const confThreshold = parseFloat(document.getElementById('ttConfSlider')?.value || 0.25);

                            const res = await fetch('/api/vision/tracking/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    camera_id: cameraId,
                                    num_frames: 5,
                                    conf_threshold: confThreshold,
                                    reset_session: false
                                })
                            });

                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.error || data.message || "Sequence tracking failed.");
                                return;
                            }

                            // Render final state
                            const stepResults = data.step_results || [];
                            const lastStep = stepResults[stepResults.length - 1] || {};

                            renderTrackingResults({
                                camera_id: data.camera_id,
                                session_id: data.session_id,
                                frame_index: lastStep.frame_index || 5,
                                active_track_count: data.active_tracks?.length || 0,
                                performance: lastStep.performance || { tracking_ms: 1.2, detection_ms: 48.0, total_ms: 55.0 },
                                tracks: data.active_tracks || [],
                                annotated_image_url: data.final_annotated_image_url
                            });

                            const stepInput = document.getElementById('ttStepInput');
                            if (stepInput) stepInput.value = (parseInt(stepInput.value || 0) + 5) % 20;

                        } catch (e) {
                            alert("Sequence error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function resetTrackingSession() {
                        const cameraId = document.getElementById('ttCameraSelect')?.value || 'CAM-001';
                        try {
                            const res = await fetch('/api/vision/tracking/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: cameraId })
                            });
                            const data = await res.json();
                            if (data.success) {
                                ttCurrentStep = 0;
                                const stepInput = document.getElementById('ttStepInput');
                                if (stepInput) stepInput.value = 0;

                                // Reset telemetry KPIs
                                document.getElementById('kpi-tt-tracks').innerText = '0';
                                document.getElementById('kpi-tt-tracks-sub').innerText = 'Session reset';
                                document.getElementById('kpi-tt-track-ms').innerText = '-';
                                document.getElementById('kpi-tt-det-ms').innerText = '-';
                                document.getElementById('kpi-tt-frame').innerText = '#0';
                                document.getElementById('kpi-tt-session-sub').innerText = 'Fresh session: ' + (data.session_id?.slice(-8) || '');

                                // Reset image
                                const img = document.getElementById('ttAnnotatedImage');
                                const placeholder = document.getElementById('ttImagePlaceholder');
                                const badge = document.getElementById('ttImageMetaBadge');
                                if (img) img.style.display = 'none';
                                if (placeholder) placeholder.style.display = 'block';
                                if (badge) badge.innerText = 'Session Reset';

                                // Reset table
                                const tbody = document.getElementById('ttResultsTbody');
                                if (tbody) {
                                    tbody.innerHTML = `
                                        <tr>
                                            <td colspan="7" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                                Tracking session reset. Track IDs will restart at 1 for next frame.
                                            </td>
                                        </tr>
                                    `;
                                }
                                document.getElementById('ttTrackCountBadge').innerText = '0 Tracks';
                            }
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        }
                    }

                    function renderTrackingResults(data) {
                        const tracks = data.tracks || [];
                        const perf = data.performance || {};

                        // Update KPIs
                        const kpiTracks = document.getElementById('kpi-tt-tracks');
                        const kpiTracksSub = document.getElementById('kpi-tt-tracks-sub');
                        const kpiTrackMs = document.getElementById('kpi-tt-track-ms');
                        const kpiDetMs = document.getElementById('kpi-tt-det-ms');
                        const kpiFrame = document.getElementById('kpi-tt-frame');
                        const kpiSessionSub = document.getElementById('kpi-tt-session-sub');
                        const trackBadge = document.getElementById('ttTrackCountBadge');

                        if (kpiTracks) kpiTracks.innerText = tracks.length;
                        if (kpiTracksSub) kpiTracksSub.innerText = `${tracks.length} active persistent ${tracks.length === 1 ? 'track' : 'tracks'}`;
                        if (kpiTrackMs) kpiTrackMs.innerText = (perf.tracking_ms != null ? perf.tracking_ms : 0).toFixed(2) + ' ms';
                        if (kpiDetMs) kpiDetMs.innerText = (perf.detection_ms != null ? perf.detection_ms : 0).toFixed(2) + ' ms';
                        if (kpiFrame) kpiFrame.innerText = `#${data.frame_index || 1}`;
                        if (kpiSessionSub) kpiSessionSub.innerText = `Session: ${(data.session_id || '').slice(-8)}`;
                        if (trackBadge) trackBadge.innerText = `${tracks.length} ${tracks.length === 1 ? 'Track' : 'Tracks'}`;

                        // Update Annotated Frame
                        const img = document.getElementById('ttAnnotatedImage');
                        const placeholder = document.getElementById('ttImagePlaceholder');
                        const metaBadge = document.getElementById('ttImageMetaBadge');

                        if (data.annotated_image_url && img) {
                            img.src = data.annotated_image_url;
                            img.style.display = 'block';
                            if (placeholder) placeholder.style.display = 'none';
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `${data.frame_width || 640}×${data.frame_height || 480} px | ${data.camera_id} | Frame #${data.frame_index}`;
                            }
                        }

                        // Render Structured Tracks Table
                        const tbody = document.getElementById('ttResultsTbody');
                        if (!tbody) return;

                        if (tracks.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="7" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                        No active tracks in frame #${data.frame_index || 1}. Detections below threshold or object lost.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = tracks.map(t => {
                            const tid = t.track_id;
                            const clsCode = escapeHtml(t.class_code);
                            const clsName = escapeHtml(t.class_name);
                            const confPct = (t.confidence * 100).toFixed(1) + '%';
                            const normBbox = `[${t.bbox_normalized.x1.toFixed(3)}, ${t.bbox_normalized.y1.toFixed(3)}, ${t.bbox_normalized.x2.toFixed(3)}, ${t.bbox_normalized.y2.toFixed(3)}]`;

                            let roiBadge = '<span style="color:var(--text-muted); font-size:0.75rem;">No ROI</span>';
                            if (t.roi && t.roi.configured) {
                                roiBadge = t.roi.inside
                                    ? `<span class="badge sent" style="font-size:0.75rem;">✓ INSIDE (${escapeHtml(t.roi.zone_code || 'Zone')})</span>`
                                    : `<span class="badge disabled-status" style="font-size:0.75rem;">✗ OUTSIDE</span>`;
                            }

                            return `
                                <tr>
                                    <td style="text-align:center;">
                                        <span style="font-size:0.9rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.12); padding:3px 8px; border-radius:6px; font-family:monospace;">
                                            #${tid}
                                        </span>
                                    </td>
                                    <td>
                                        <div style="font-weight:700; color:var(--text-main);">${clsCode}</div>
                                        <div style="font-size:0.72rem; color:var(--text-muted);">${clsName}</div>
                                    </td>
                                    <td>
                                        <strong style="color:var(--text-main);">${confPct}</strong>
                                    </td>
                                    <td style="font-family:monospace; font-size:0.78rem; color:var(--text-muted);">
                                        <div>${normBbox}</div>
                                        <div style="font-size:0.72rem; color:var(--text-muted);">Center: (${t.center_normalized.x.toFixed(3)}, ${t.center_normalized.y.toFixed(3)})</div>
                                    </td>
                                    <td style="text-align:center;">
                                        ${roiBadge}
                                    </td>
                                    <td style="text-align:center; font-family:monospace; font-weight:700; color:var(--text-main);">
                                        ${t.hits}
                                    </td>
                                    <td style="text-align:center;">
                                        <span class="badge sent" style="font-size:0.72rem; text-transform:uppercase;">${t.state || 'Active'}</span>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    // ==========================================
                    // PART 7: OBJECT IDENTITY & RECOGNITION JAVASCRIPT
                    // ==========================================
                    let idCurrentStep = 0;

                    async function initIdentityTestUI() {
                        try {
                            const resCams = await fetch('/api/vision/cameras');
                            if (resCams.ok) {
                                const cams = await resCams.json();
                                const camList = Array.isArray(cams) ? cams : (cams.data || []);
                                const sel = document.getElementById('idCameraSelect');
                                if (sel) {
                                    sel.innerHTML = camList.map(c => `
                                        <option value="${c.camera_id}">${c.camera_code || c.camera_id} - ${c.name} (${c.location || 'General'})</option>
                                    `).join('');
                                }
                            }
                        } catch (e) {
                            console.warn("Could not load camera list for identity test:", e);
                        }

                        // Fetch identity engine status
                        try {
                            const resStatus = await fetch('/api/vision/identity/status');
                            if (resStatus.ok) {
                                const data = await resStatus.json();
                                const badge = document.getElementById('idEngineStatusBadge');
                                if (badge) {
                                    const dev = data.decoders?.ocr?.device || 'CPU';
                                    badge.innerText = `Identity: Active (QR, Barcode, OCR on ${dev.toUpperCase()})`;
                                }
                            }
                        } catch (e) {}
                    }

                    function handleIdentitySourceChange() {
                        const src = document.getElementById('idSourceTypeSelect')?.value;
                        const stepContainer = document.getElementById('idStepContainer');
                        const uploadContainer = document.getElementById('idUploadContainer');

                        if (stepContainer) stepContainer.style.display = (src === 'motion') ? 'block' : 'none';
                        if (uploadContainer) uploadContainer.style.display = (src === 'upload') ? 'block' : 'none';
                    }

                    async function runIdentityTest() {
                        const btn = document.getElementById('btnRunIdentity');
                        const originalHtml = btn ? btn.innerHTML : 'Run Identity';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Processing...';
                        }

                        try {
                            const cameraId = document.getElementById('idCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('idSourceTypeSelect')?.value || 'identity_qr_b104.jpg';
                            const enableBarcode = document.getElementById('idCheckBarcode')?.checked ?? true;
                            const enableOcr = document.getElementById('idCheckOcr')?.checked ?? true;

                            let payload = {
                                camera_id: cameraId,
                                enable_barcode_qr: enableBarcode,
                                enable_ocr: enableOcr,
                                crop_padding: 0.05
                            };

                            if (srcType === 'motion') {
                                const stepInput = document.getElementById('idStepInput');
                                const stepVal = parseInt(stepInput?.value || idCurrentStep);
                                payload.sequence_step = stepVal;
                                payload.sample_scene = 'identity_qr_b104.jpg';
                                idCurrentStep = (stepVal + 1) % 20;
                                if (stepInput) stepInput.value = idCurrentStep;
                            } else if (srcType === 'camera') {
                                // Will be acquired server-side from camera_id
                            } else if (srcType === 'upload') {
                                const fileInput = document.getElementById('idFileInput');
                                if (!fileInput || !fileInput.files[0]) {
                                    alert("Please select an image file to upload.");
                                    return;
                                }
                                const formData = new FormData();
                                formData.append('file', fileInput.files[0]);
                                formData.append('camera_id', cameraId);
                                formData.append('enable_barcode_qr', enableBarcode);
                                formData.append('enable_ocr', enableOcr);

                                const res = await fetch('/api/vision/identity/test', {
                                    method: 'POST',
                                    body: formData
                                });
                                const data = await res.json();
                                if (!res.ok || !data.success) {
                                    alert(data.error || data.message || "Identity recognition failed.");
                                    return;
                                }
                                renderIdentityResults(data);
                                return;
                            } else {
                                // Built-in sample scenes
                                payload.sample_scene = srcType;
                            }

                            const res = await fetch('/api/vision/identity/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.error || data.message || "Identity recognition failed.");
                                return;
                            }

                            renderIdentityResults(data);
                        } catch (e) {
                            alert("Identity recognition request error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function runIdentitySequence() {
                        const btn = document.getElementById('btnRunIdentitySeq');
                        const originalHtml = btn ? btn.innerHTML : 'Run 5 Frames';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⚡</span> Running 5 Steps...';
                        }

                        try {
                            const cameraId = document.getElementById('idCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('idSourceTypeSelect')?.value;
                            const sampleScene = (srcType && srcType.endsWith('.jpg')) ? srcType : 'identity_qr_b104.jpg';

                            const res = await fetch('/api/vision/identity/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    camera_id: cameraId,
                                    num_frames: 5,
                                    sample_scene: sampleScene,
                                    reset_session: false
                                })
                            });

                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.error || data.message || "Identity sequence execution failed.");
                                return;
                            }

                            const stepResults = data.step_results || [];
                            const lastStep = stepResults[stepResults.length - 1] || {};

                            renderIdentityResults({
                                camera_id: data.camera_id,
                                session_id: data.session_id,
                                frame_index: lastStep.frame_index || 5,
                                active_track_count: data.active_tracks?.length || 0,
                                identified_count: lastStep.identified_count || 0,
                                performance: lastStep.performance || { identity_ms: 18.2, total_ms: 55.0 },
                                tracks: data.active_tracks || [],
                                annotated_image_url: data.final_annotated_image_url
                            });

                        } catch (e) {
                            alert("Sequence request error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function resetIdentitySession() {
                        const cameraId = document.getElementById('idCameraSelect')?.value || 'CAM-001';
                        try {
                            const res = await fetch('/api/vision/identity/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: cameraId })
                            });
                            const data = await res.json();
                            if (data.success) {
                                idCurrentStep = 0;
                                const stepInput = document.getElementById('idStepInput');
                                if (stepInput) stepInput.value = 0;

                                // Reset telemetry KPIs
                                document.getElementById('kpi-id-tracks').innerText = '0';
                                document.getElementById('kpi-id-tracks-sub').innerText = 'Session reset';
                                document.getElementById('kpi-id-identified').innerText = '0';
                                document.getElementById('kpi-id-identified-sub').innerText = 'Identities cleared';
                                document.getElementById('kpi-id-ident-ms').innerText = '-';
                                document.getElementById('kpi-id-total-ms').innerText = '-';

                                // Reset image
                                const img = document.getElementById('idAnnotatedImage');
                                const placeholder = document.getElementById('idImagePlaceholder');
                                const badge = document.getElementById('idImageMetaBadge');
                                if (img) img.style.display = 'none';
                                if (placeholder) placeholder.style.display = 'block';
                                if (badge) badge.innerText = 'Session Reset';

                                // Reset table
                                const tbody = document.getElementById('idResultsTbody');
                                if (tbody) {
                                    tbody.innerHTML = `
                                        <tr>
                                            <td colspan="7" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                                Identity session reset. In-memory identities cleared for camera.
                                            </td>
                                        </tr>
                                    `;
                                }
                                document.getElementById('idTrackCountBadge').innerText = '0 Tracks';
                            }
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        }
                    }

                    function renderIdentityResults(data) {
                        const tracks = data.tracks || [];
                        const perf = data.performance || {};

                        // Update KPIs
                        const kpiTracks = document.getElementById('kpi-id-tracks');
                        const kpiTracksSub = document.getElementById('kpi-id-tracks-sub');
                        const kpiIdentified = document.getElementById('kpi-id-identified');
                        const kpiIdentifiedSub = document.getElementById('kpi-id-identified-sub');
                        const kpiIdentMs = document.getElementById('kpi-id-ident-ms');
                        const kpiTotalMs = document.getElementById('kpi-id-total-ms');
                        const trackBadge = document.getElementById('idTrackCountBadge');

                        const identifiedCount = tracks.filter(t => t.identity && t.identity.status === 'IDENTIFIED').length;
                        const conflictCount = tracks.filter(t => t.identity && t.identity.status === 'CONFLICT').length;

                        if (kpiTracks) kpiTracks.innerText = tracks.length;
                        if (kpiTracksSub) kpiTracksSub.innerText = `${tracks.length} tracked entities`;
                        if (kpiIdentified) kpiIdentified.innerText = identifiedCount;
                        if (kpiIdentifiedSub) kpiIdentifiedSub.innerText = `${identifiedCount} identified${conflictCount > 0 ? ' (' + conflictCount + ' conflict)' : ''}`;
                        if (kpiIdentMs) kpiIdentMs.innerText = (perf.identity_ms != null ? perf.identity_ms : 0).toFixed(2) + ' ms';
                        if (kpiTotalMs) kpiTotalMs.innerText = (perf.total_ms != null ? perf.total_ms : 0).toFixed(2) + ' ms';
                        if (trackBadge) trackBadge.innerText = `${tracks.length} ${tracks.length === 1 ? 'Track' : 'Tracks'}`;

                        // Update Annotated Frame
                        const img = document.getElementById('idAnnotatedImage');
                        const placeholder = document.getElementById('idImagePlaceholder');
                        const metaBadge = document.getElementById('idImageMetaBadge');

                        if (data.annotated_image_url && img) {
                            img.src = data.annotated_image_url;
                            img.style.display = 'block';
                            if (placeholder) placeholder.style.display = 'none';
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `${data.frame_width || 640}×${data.frame_height || 480} px | ${data.camera_id} | Frame #${data.frame_index}`;
                            }
                        }

                        // Render Structured Tracks & Identities Table
                        const tbody = document.getElementById('idResultsTbody');
                        if (!tbody) return;

                        if (tracks.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="7" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                        No active tracks in frame #${data.frame_index || 1}.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = tracks.map(t => {
                            const tid = t.track_id;
                            const clsCode = escapeHtml(t.class_code);
                            const ident = t.identity || { status: 'UNIDENTIFIED', value: null, source: null, confidence: 0.0 };

                            let statusBadge = '<span class="badge disabled-status" style="font-size:0.75rem;">UNIDENTIFIED</span>';
                            if (ident.status === 'IDENTIFIED') {
                                statusBadge = '<span class="badge sent" style="font-size:0.75rem; background:#10b981; color:#fff;">✓ IDENTIFIED</span>';
                            } else if (ident.status === 'CONFLICT') {
                                statusBadge = '<span class="badge" style="font-size:0.75rem; background:#f59e0b; color:#fff;">⚠ CONFLICT</span>';
                            }

                            const valDisplay = ident.value
                                ? `<strong style="font-size:0.95rem; color:var(--text-main); font-family:monospace; background:rgba(16,185,129,0.12); padding:3px 8px; border-radius:5px;">${escapeHtml(ident.value)}</strong>`
                                : (ident.status === 'CONFLICT'
                                    ? `<span style="font-size:0.75rem; color:#f59e0b; font-weight:700;">Conflicting candidates</span>`
                                    : `<span style="color:var(--text-muted); font-size:0.8rem;">None detected</span>`);

                            let srcDisplay = '-';
                            if (ident.source) {
                                srcDisplay = `<strong style="color:var(--text-main);">${escapeHtml(ident.source)}</strong> <span style="font-size:0.72rem; color:var(--text-muted);">(${escapeHtml(ident.format || '')})</span>`;
                            } else if (ident.candidates && ident.candidates.length > 0) {
                                srcDisplay = ident.candidates.map(c => `
                                    <div style="font-size:0.72rem; color:var(--text-muted);">
                                        • <strong>${escapeHtml(c.value)}</strong> [${escapeHtml(c.source)}] (${Math.round((c.confidence||0)*100)}%)
                                    </div>
                                `).join('');
                            }

                            const confPct = ident.confidence > 0 ? (ident.confidence * 100).toFixed(1) + '%' : '-';
                            const reads = ident.read_count ? `${ident.read_count}×` : '-';

                            return `
                                <tr>
                                    <td style="text-align:center;">
                                        <span style="font-size:0.9rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.12); padding:3px 8px; border-radius:6px; font-family:monospace;">
                                            #${tid}
                                        </span>
                                    </td>
                                    <td>
                                        <div style="font-weight:700; color:var(--text-main);">${clsCode}</div>
                                    </td>
                                    <td style="text-align:center;">
                                        ${statusBadge}
                                    </td>
                                    <td>
                                        ${valDisplay}
                                    </td>
                                    <td>
                                        ${srcDisplay}
                                    </td>
                                    <td style="text-align:center; font-weight:700; color:var(--text-main);">
                                        ${confPct}
                                    </td>
                                    <td style="text-align:center; font-family:monospace; color:var(--text-muted);">
                                        ${reads}
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    // =======================================================
                    // PART 8: IDENTITY VALIDATION & MASTER-DATA BINDING CLIENT
                    // =======================================================

                    let valActiveCameraId = 'CAM-001';

                    async function initValidationTestUI() {
                        populateValidationCameras();
                        fetchMasterDataStatus();
                        handleValidationSourceChange();
                    }

                    async function populateValidationCameras() {
                        const select = document.getElementById('valCameraSelect');
                        if (!select) return;

                        try {
                            const resCams = await fetch('/api/vision/cameras');
                            if (resCams.ok) {
                                const cams = await resCams.json();
                                const camList = Array.isArray(cams) ? cams : (cams.data || []);
                                select.innerHTML = camList.map(c => `
                                    <option value="${c.camera_id}" ${c.camera_id === valActiveCameraId ? 'selected' : ''}>
                                        ${c.camera_code || c.camera_id} - ${c.name} (${c.location || 'General'})
                                    </option>
                                `).join('');
                                return;
                            }
                        } catch (e) {
                            console.warn("Could not load camera list for validation test:", e);
                        }

                        select.innerHTML = `
                            <option value="CAM-001" selected>CAM-001 - Gate Camera 01 (Gate 01)</option>
                            <option value="CAM-002">CAM-002 - Dock Camera 01 (Dock 01)</option>
                        `;
                    }

                    async function fetchMasterDataStatus() {
                        try {
                            const res = await fetch('/api/vision/validation/status');
                            if (res.ok) {
                                const data = await res.json();
                                const badge = document.getElementById('valEngineStatusBadge');
                                if (badge) {
                                    badge.innerText = `WMS DB: READ-ONLY | Masters: Active`;
                                }
                            }
                        } catch (e) {
                            console.warn("Could not fetch validation status:", e);
                        }
                    }

                    function handleValidationSourceChange() {
                        const src = document.getElementById('valSourceTypeSelect')?.value;
                        const uploadContainer = document.getElementById('valUploadContainer');
                        if (uploadContainer) uploadContainer.style.display = (src === 'upload') ? 'block' : 'none';
                    }

                    async function runValidationTest() {
                        const btn = document.getElementById('btnRunValidation');
                        const originalHtml = btn ? btn.innerHTML : 'Run Validation';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Validating...';
                        }

                        try {
                            const cameraId = document.getElementById('valCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('valSourceTypeSelect')?.value || 'validation_truck_gp1000.jpg';
                            const enableBarcode = document.getElementById('valCheckBarcode')?.checked ?? true;
                            const enableOcr = document.getElementById('valCheckOcr')?.checked ?? true;

                            let payload = {
                                camera_id: cameraId,
                                enable_barcode: enableBarcode,
                                enable_ocr: enableOcr
                            };

                            if (srcType === 'camera') {
                                payload.source_type = 'camera';
                            } else if (srcType === 'upload') {
                                const fileInput = document.getElementById('valFileInput');
                                if (!fileInput || !fileInput.files[0]) {
                                    alert("Please select an image file to upload.");
                                    return;
                                }
                                const reader = new FileReader();
                                reader.onload = async function(e) {
                                    payload.source_type = 'upload';
                                    payload.image_data = e.target.result;
                                    await sendValidationRequest(payload, btn, originalHtml);
                                };
                                reader.readAsDataURL(fileInput.files[0]);
                                return;
                            } else {
                                payload.source_type = 'sample';
                                payload.sample_scene = srcType;
                            }

                            await sendValidationRequest(payload, btn, originalHtml);
                        } catch (e) {
                            alert("Validation request error: " + e.message);
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function sendValidationRequest(payload, btn, originalHtml) {
                        try {
                            const res = await fetch('/api/vision/validation/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.error || data.message || "Master-data validation failed.");
                                return;
                            }
                            renderValidationResults(data);
                        } catch (e) {
                            alert("Validation API error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function resetValidationSession() {
                        const cameraId = document.getElementById('valCameraSelect')?.value || 'CAM-001';
                        try {
                            const res = await fetch('/api/vision/validation/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: cameraId })
                            });
                            const data = await res.json();
                            if (data.success) {
                                // Reset KPIs
                                document.getElementById('kpi-val-tracks').innerText = '0';
                                document.getElementById('kpi-val-tracks-sub').innerText = 'Session reset';
                                document.getElementById('kpi-val-validated').innerText = '0';
                                document.getElementById('kpi-val-validated-sub').innerText = 'No active validations';
                                document.getElementById('kpi-val-unregistered').innerText = '0';
                                document.getElementById('kpi-val-unregistered-sub').innerText = 'Cleared';
                                document.getElementById('kpi-val-ms').innerText = '-';
                                document.getElementById('kpi-val-total-ms').innerText = 'Total: -';

                                // Reset image
                                const img = document.getElementById('valAnnotatedImage');
                                const placeholder = document.getElementById('valImagePlaceholder');
                                const badge = document.getElementById('valImageMetaBadge');
                                if (img) img.style.display = 'none';
                                if (placeholder) placeholder.style.display = 'block';
                                if (badge) badge.innerText = 'Session Reset';

                                // Reset table
                                const tbody = document.getElementById('valResultsTbody');
                                if (tbody) {
                                    tbody.innerHTML = `
                                        <tr>
                                            <td colspan="7" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                                Validation session reset. In-memory identities and tracking cleared.
                                            </td>
                                        </tr>
                                    `;
                                }
                                document.getElementById('valTrackCountBadge').innerText = '0 Tracks';
                            }
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        }
                    }

                    function renderValidationResults(data) {
                        const tracks = data.tracks || [];
                        const perf = data.performance || {};

                        // Update KPIs
                        const kpiTracks = document.getElementById('kpi-val-tracks');
                        const kpiTracksSub = document.getElementById('kpi-val-tracks-sub');
                        const kpiValidated = document.getElementById('kpi-val-validated');
                        const kpiValidatedSub = document.getElementById('kpi-val-validated-sub');
                        const kpiUnreg = document.getElementById('kpi-val-unregistered');
                        const kpiUnregSub = document.getElementById('kpi-val-unregistered-sub');
                        const kpiValMs = document.getElementById('kpi-val-ms');
                        const kpiTotalMs = document.getElementById('kpi-val-total-ms');
                        const trackBadge = document.getElementById('valTrackCountBadge');

                        const validatedCount = tracks.filter(t => t.validation && t.validation.status === 'VALIDATED').length;
                        const unregCount = tracks.filter(t => t.validation && t.validation.status === 'UNREGISTERED').length;

                        if (kpiTracks) kpiTracks.innerText = tracks.length;
                        if (kpiTracksSub) kpiTracksSub.innerText = `${tracks.length} tracked entities`;
                        if (kpiValidated) kpiValidated.innerText = validatedCount;
                        if (kpiValidatedSub) kpiValidatedSub.innerText = `${validatedCount} bound to master`;
                        if (kpiUnreg) kpiUnreg.innerText = unregCount;
                        if (kpiUnregSub) kpiUnregSub.innerText = `${unregCount} not in catalog`;
                        if (kpiValMs) kpiValMs.innerText = (perf.validation_ms != null ? perf.validation_ms : 0).toFixed(2) + ' ms';
                        if (kpiTotalMs) kpiTotalMs.innerText = `Total: ${(perf.total_ms != null ? perf.total_ms : 0).toFixed(2)} ms`;
                        if (trackBadge) trackBadge.innerText = `${tracks.length} ${tracks.length === 1 ? 'Track' : 'Tracks'}`;

                        // Update Annotated Frame
                        const img = document.getElementById('valAnnotatedImage');
                        const placeholder = document.getElementById('valImagePlaceholder');
                        const metaBadge = document.getElementById('valImageMetaBadge');

                        if (data.annotated_image_url && img) {
                            img.src = data.annotated_image_url;
                            img.style.display = 'block';
                            if (placeholder) placeholder.style.display = 'none';
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `${data.frame_width || 640}×${data.frame_height || 480} px | ${data.camera_id} | ${validatedCount} Validated`;
                            }
                        }

                        // Render Structured Validation Table
                        const tbody = document.getElementById('valResultsTbody');
                        if (!tbody) return;

                        if (tracks.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="7" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                        No active tracks in frame.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = tracks.map(t => {
                            const tid = t.track_id;
                            const clsCode = escapeHtml(t.class_code);
                            const ident = t.identity || { status: 'UNIDENTIFIED', value: null, source: null, confidence: 0.0 };
                            const val = t.validation || { status: 'NOT_APPLICABLE', master_type: null, master_id: null, matched_field: null, message: '' };

                            let statusBadge = '<span class="badge disabled-status" style="font-size:0.75rem;">NOT APPLICABLE</span>';
                            if (val.status === 'VALIDATED') {
                                statusBadge = '<span class="badge sent" style="font-size:0.75rem; background:#10b981; color:#fff;">✓ VALIDATED</span>';
                            } else if (val.status === 'UNREGISTERED') {
                                statusBadge = '<span class="badge" style="font-size:0.75rem; background:#f59e0b; color:#fff;">⚠ UNREGISTERED</span>';
                            } else if (val.status === 'AMBIGUOUS') {
                                statusBadge = '<span class="badge" style="font-size:0.75rem; background:#ef4444; color:#fff;">⚡ AMBIGUOUS</span>';
                            } else if (val.status === 'MASTER_DATA_UNAVAILABLE') {
                                statusBadge = '<span class="badge" style="font-size:0.75rem; background:#8b5cf6; color:#fff;">NO MASTER</span>';
                            }

                            const visualValDisplay = ident.value
                                ? `<strong style="font-size:0.92rem; color:var(--text-main); font-family:monospace; background:rgba(16,185,129,0.12); padding:2px 6px; border-radius:4px;">${escapeHtml(ident.value)}</strong>`
                                : (ident.status === 'CONFLICT'
                                    ? `<span style="font-size:0.75rem; color:#ef4444; font-weight:700;">CONFLICT</span>`
                                    : `<span style="color:var(--text-muted); font-size:0.78rem;">UNIDENTIFIED</span>`);

                            const srcDisplay = ident.source ? escapeHtml(ident.source) : '-';
                            const masterIdDisplay = val.master_id
                                ? `<strong style="color:var(--text-main); font-family:monospace;">${escapeHtml(val.master_id)}</strong> <span style="font-size:0.7rem; color:var(--text-muted);">(${escapeHtml(val.matched_field || '')})</span>`
                                : `<span style="color:var(--text-muted); font-size:0.78rem;">-</span>`;

                            const msgDisplay = escapeHtml(val.message || '');

                            return `
                                <tr>
                                    <td style="text-align:center;">
                                        <span style="font-size:0.88rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.12); padding:2px 7px; border-radius:5px; font-family:monospace;">
                                            #${tid}
                                        </span>
                                    </td>
                                    <td>
                                        <strong style="color:var(--text-main);">${clsCode}</strong>
                                    </td>
                                    <td>
                                        ${visualValDisplay}
                                    </td>
                                    <td style="text-align:center; font-size:0.78rem; color:var(--text-muted);">
                                        ${srcDisplay}
                                    </td>
                                    <td style="text-align:center;">
                                        ${statusBadge}
                                    </td>
                                    <td>
                                        ${masterIdDisplay}
                                    </td>
                                    <td style="font-size:0.75rem; color:var(--text-muted); line-height:1.35;">
                                        ${msgDisplay}
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    // ============================================================================
                    // PART 9: TRUCK <-> BOX ASSOCIATION CLIENT JAVASCRIPT
                    // ============================================================================
                    let assocActiveCameraId = 'CAM-001';
                    let latestAssociationsList = [];

                    async function initAssociationTestUI() {
                        populateAssociationCameras();
                        fetchAssociationStatus();
                        handleAssociationSourceChange();
                    }

                    async function populateAssociationCameras() {
                        const select = document.getElementById('assocCameraSelect');
                        if (!select) return;

                        try {
                            const resCams = await fetch('/api/vision/cameras');
                            if (resCams.ok) {
                                const cams = await resCams.json();
                                const camList = Array.isArray(cams) ? cams : (cams.data || []);
                                select.innerHTML = camList.map(c => `
                                    <option value="${c.camera_id}" ${c.camera_id === assocActiveCameraId ? 'selected' : ''}>
                                        ${c.camera_code || c.camera_id} - ${c.name} (${c.location || 'General'})
                                    </option>
                                `).join('');
                                return;
                            }
                        } catch (e) {
                            console.warn("Could not load camera list for association test:", e);
                        }

                        select.innerHTML = `
                            <option value="CAM-001" selected>CAM-001 - Gate Camera 01 (Gate 01)</option>
                            <option value="CAM-002">CAM-002 - Dock Camera 01 (Dock 01)</option>
                        `;
                    }

                    async function fetchAssociationStatus() {
                        try {
                            const res = await fetch('/api/vision/association/status');
                            if (res.ok) {
                                const data = await res.json();
                                const badge = document.getElementById('assocEngineStatusBadge');
                                if (badge) {
                                    badge.innerText = `Engine: Active | In-Memory (Zero DB Writes)`;
                                }
                                if (data.config) {
                                    const cfg = data.config;
                                    const minF = document.getElementById('cfgMinFrames');
                                    const maxD = document.getElementById('cfgMaxDist');
                                    const minS = document.getElementById('cfgMinScore');
                                    const reqZ = document.getElementById('cfgRequireZone');
                                    const ambD = document.getElementById('cfgAmbiguityDelta');
                                    if (minF) minF.innerText = `${cfg.min_consecutive_frames} frames`;
                                    if (maxD) maxD.innerText = `${cfg.max_normalized_distance}`;
                                    if (minS) minS.innerText = `${cfg.min_association_score}`;
                                    if (reqZ) reqZ.innerText = cfg.require_same_zone ? 'STRICT (True)' : 'Optional (False)';
                                    if (ambD) ambD.innerText = `Δ ≤ ${cfg.ambiguity_threshold_delta}`;
                                }
                            }
                        } catch (e) {
                            console.warn("Could not fetch association status:", e);
                        }
                    }

                    function handleAssociationSourceChange() {
                        const src = document.getElementById('assocSourceTypeSelect')?.value;
                        const uploadContainer = document.getElementById('assocUploadContainer');
                        if (uploadContainer) uploadContainer.style.display = (src === 'upload') ? 'block' : 'none';
                    }

                    function generateSyntheticSequence(mode) {
                        const seq = [];
                        if (mode === 'synthetic_confirm') {
                            // 5 consecutive frames: Truck #10 and Box #21 close in Dock 1
                            for (let f = 1; f <= 5; f++) {
                                seq.push([
                                    {
                                        track_id: 10,
                                        class_code: "TRUCK",
                                        confidence: 0.95,
                                        bbox: { x1: 200, y1: 150, x2: 450, y2: 380 },
                                        bbox_normalized: { x1: 0.20, y1: 0.25, x2: 0.45, y2: 0.63 },
                                        center_normalized: [0.325, 0.44],
                                        roi: { inside: true, zone_code: "DOCK-01" },
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "GP-1000", source: "QR", confidence: 0.99 },
                                        validation: { status: "VALIDATED", master_id: "GP-1000", display_name: "Gate Pass GP-1000 [Plate: MH-12-AB-1234]" }
                                    },
                                    {
                                        track_id: 21,
                                        class_code: "BOX",
                                        confidence: 0.91,
                                        bbox: { x1: 420, y1: 320, x2: 510, y2: 420 },
                                        bbox_normalized: { x1: 0.42, y1: 0.53, x2: 0.51, y2: 0.70 },
                                        center_normalized: [0.465, 0.615],
                                        roi: { inside: true, zone_code: "DOCK-01" },
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "VLV-900", source: "QR", confidence: 0.98 },
                                        validation: { status: "VALIDATED", master_id: "VLV-900", display_name: "Consignment Box SKU VLV-900" }
                                    }
                                ]);
                            }
                        } else if (mode === 'synthetic_expire') {
                            // Frames 1-3: present and confirmed
                            for (let f = 1; f <= 3; f++) {
                                seq.push([
                                    {
                                        track_id: 10,
                                        class_code: "TRUCK",
                                        confidence: 0.95,
                                        center_normalized: [0.325, 0.44],
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "GP-1000" },
                                        validation: { status: "VALIDATED", master_id: "GP-1000" }
                                    },
                                    {
                                        track_id: 21,
                                        class_code: "BOX",
                                        confidence: 0.91,
                                        center_normalized: [0.465, 0.615],
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "VLV-900" },
                                        validation: { status: "VALIDATED", master_id: "VLV-900" }
                                    }
                                ]);
                            }
                            // Frames 4-8: box departed frame (empty or only truck remains)
                            for (let f = 4; f <= 8; f++) {
                                seq.push([
                                    {
                                        track_id: 10,
                                        class_code: "TRUCK",
                                        confidence: 0.95,
                                        center_normalized: [0.325, 0.44],
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "GP-1000" },
                                        validation: { status: "VALIDATED", master_id: "GP-1000" }
                                    }
                                ]);
                            }
                        }
                        return seq;
                    }

                    async function runAssociationTest() {
                        const btn = document.getElementById('btnRunAssoc');
                        const originalHtml = btn ? btn.innerHTML : 'Run Single Frame';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Processing...';
                        }

                        try {
                            const cameraId = document.getElementById('assocCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('assocSourceTypeSelect')?.value || 'association_truck_box_dock1.jpg';

                            if (srcType.startsWith('synthetic_')) {
                                const seq = generateSyntheticSequence(srcType);
                                const firstFrameTracks = seq[0] || [];
                                const res = await fetch('/api/vision/association/test', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        camera_id: cameraId,
                                        synthetic_tracks: firstFrameTracks
                                    })
                                });
                                const data = await res.json();
                                if (!res.ok || !data.success) {
                                    alert(data.message || "Association evaluation failed.");
                                    return;
                                }
                                renderAssociationResults({
                                    camera_id: cameraId,
                                    active_truck_count: firstFrameTracks.filter(t => t.class_code === 'TRUCK').length,
                                    active_box_count: firstFrameTracks.filter(t => t.class_code === 'BOX').length,
                                    associations: data.associations || [],
                                    performance: { association_ms: data.association_ms, total_ms: data.association_ms }
                                });
                                return;
                            }

                            let payload = { camera_id: cameraId };

                            if (srcType === 'camera') {
                                payload.source_type = 'camera';
                            } else if (srcType === 'upload') {
                                const fileInput = document.getElementById('assocFileInput');
                                if (!fileInput || !fileInput.files[0]) {
                                    alert("Please select an image file to upload.");
                                    return;
                                }
                                const reader = new FileReader();
                                reader.onload = async function(e) {
                                    payload.source_type = 'upload';
                                    payload.image_data = e.target.result;
                                    await sendAssociationRequest(payload, btn, originalHtml);
                                };
                                reader.readAsDataURL(fileInput.files[0]);
                                return;
                            } else {
                                payload.source_type = 'sample';
                                payload.sample_scene = srcType;
                            }

                            await sendAssociationRequest(payload, btn, originalHtml);
                        } catch (e) {
                            alert("Association request error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function sendAssociationRequest(payload, btn, originalHtml) {
                        try {
                            const res = await fetch('/api/vision/association/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.error || data.message || "Association test failed.");
                                return;
                            }
                            renderAssociationResults(data);
                        } catch (e) {
                            alert("Association API error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function runAssociationSequence() {
                        const btn = document.getElementById('btnRunAssocSeq');
                        const originalHtml = btn ? btn.innerHTML : 'Run Sequence';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Running Sequence...';
                        }

                        try {
                            const cameraId = document.getElementById('assocCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('assocSourceTypeSelect')?.value || 'association_truck_box_dock1.jpg';

                            let payload = {
                                camera_id: cameraId,
                                reset_session: true,
                                num_frames: 5
                            };

                            if (srcType.startsWith('synthetic_')) {
                                payload.synthetic_tracks_sequence = generateSyntheticSequence(srcType);
                            } else {
                                payload.sample_scene = srcType;
                            }

                            const res = await fetch('/api/vision/association/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.message || "Sequence execution failed.");
                                return;
                            }

                            const assocs = data.final_associations || data.associations || [];
                            renderAssociationResults({
                                camera_id: cameraId,
                                active_truck_count: data.active_truck_count || 1,
                                active_box_count: data.active_box_count || 1,
                                associations: assocs,
                                annotated_frame: data.annotated_frame,
                                performance: data.performance || { association_ms: 1.5, total_ms: 22.0 }
                            });
                        } catch (e) {
                            alert("Sequence API error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function resetAssociationSession() {
                        const cameraId = document.getElementById('assocCameraSelect')?.value || 'CAM-001';
                        try {
                            const res = await fetch('/api/vision/association/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: cameraId })
                            });
                            const data = await res.json();
                            if (data.success) {
                                document.getElementById('kpi-assoc-trucks').innerText = '0';
                                document.getElementById('kpi-assoc-trucks-sub').innerText = 'Session reset';
                                document.getElementById('kpi-assoc-boxes').innerText = '0';
                                document.getElementById('kpi-assoc-boxes-sub').innerText = 'Session reset';
                                document.getElementById('kpi-assoc-confirmed').innerText = '0';
                                document.getElementById('kpi-assoc-confirmed-sub').innerText = 'Cleared';
                                document.getElementById('kpi-assoc-candidates').innerText = '0';
                                document.getElementById('kpi-assoc-candidates-sub').innerText = 'Cleared';
                                document.getElementById('kpi-assoc-ambiguous').innerText = '0';
                                document.getElementById('kpi-assoc-ambiguous-sub').innerText = 'Cleared';
                                document.getElementById('kpi-assoc-ms').innerText = '-';
                                document.getElementById('kpi-assoc-total-ms').innerText = 'Total: -';

                                const img = document.getElementById('assocAnnotatedImage');
                                const placeholder = document.getElementById('assocImagePlaceholder');
                                const badge = document.getElementById('assocImageMetaBadge');
                                if (img) img.style.display = 'none';
                                if (placeholder) placeholder.style.display = 'block';
                                if (badge) badge.innerText = 'Session Reset';

                                const tbody = document.getElementById('assocResultsTbody');
                                if (tbody) {
                                    tbody.innerHTML = `
                                        <tr>
                                            <td colspan="10" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                                Association session reset. In-memory pairwise candidates cleared.
                                            </td>
                                        </tr>
                                    `;
                                }
                                document.getElementById('assocCountBadge').innerText = '0 Associations';
                                latestAssociationsList = [];
                            }
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        }
                    }

                    function renderAssociationResults(data) {
                        const assocs = data.associations || [];
                        latestAssociationsList = assocs;
                        const perf = data.performance || {};

                        const confirmedCount = assocs.filter(a => a.status === 'CONFIRMED').length;
                        const candidateCount = assocs.filter(a => a.status === 'CANDIDATE').length;
                        const ambiguousCount = assocs.filter(a => a.evidence && a.evidence.is_ambiguous).length;

                        // Update KPIs
                        const kpiTrucks = document.getElementById('kpi-assoc-trucks');
                        const kpiTrucksSub = document.getElementById('kpi-assoc-trucks-sub');
                        const kpiBoxes = document.getElementById('kpi-assoc-boxes');
                        const kpiBoxesSub = document.getElementById('kpi-assoc-boxes-sub');
                        const kpiConf = document.getElementById('kpi-assoc-confirmed');
                        const kpiConfSub = document.getElementById('kpi-assoc-confirmed-sub');
                        const kpiCand = document.getElementById('kpi-assoc-candidates');
                        const kpiCandSub = document.getElementById('kpi-assoc-candidates-sub');
                        const kpiAmb = document.getElementById('kpi-assoc-ambiguous');
                        const kpiAmbSub = document.getElementById('kpi-assoc-ambiguous-sub');
                        const kpiAssocMs = document.getElementById('kpi-assoc-ms');
                        const kpiTotalMs = document.getElementById('kpi-assoc-total-ms');
                        const countBadge = document.getElementById('assocCountBadge');

                        if (kpiTrucks) kpiTrucks.innerText = data.active_truck_count != null ? data.active_truck_count : '-';
                        if (kpiTrucksSub) kpiTrucksSub.innerText = `${data.active_truck_count || 0} active trucks`;
                        if (kpiBoxes) kpiBoxes.innerText = data.active_box_count != null ? data.active_box_count : '-';
                        if (kpiBoxesSub) kpiBoxesSub.innerText = `${data.active_box_count || 0} active boxes`;
                        if (kpiConf) kpiConf.innerText = confirmedCount;
                        if (kpiConfSub) kpiConfSub.innerText = `${confirmedCount} sustained threshold`;
                        if (kpiCand) kpiCand.innerText = candidateCount;
                        if (kpiCandSub) kpiCandSub.innerText = `${candidateCount} pairwise candidates`;
                        if (kpiAmb) kpiAmb.innerText = ambiguousCount;
                        if (kpiAmbSub) kpiAmbSub.innerText = `${ambiguousCount} competing pairs`;
                        if (kpiAssocMs) kpiAssocMs.innerText = (perf.association_ms != null ? perf.association_ms : 0).toFixed(2) + ' ms';
                        if (kpiTotalMs) kpiTotalMs.innerText = `Total: ${(perf.total_ms != null ? perf.total_ms : 0).toFixed(2)} ms`;
                        if (countBadge) countBadge.innerText = `${assocs.length} ${assocs.length === 1 ? 'Pair' : 'Pairs'}`;

                        // Update Annotated Frame
                        const img = document.getElementById('assocAnnotatedImage');
                        const placeholder = document.getElementById('assocImagePlaceholder');
                        const metaBadge = document.getElementById('assocImageMetaBadge');

                        if (data.annotated_frame && img) {
                            img.src = data.annotated_frame;
                            img.style.display = 'block';
                            if (placeholder) placeholder.style.display = 'none';
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `${data.camera_id} | ${confirmedCount} Confirmed | ${candidateCount} Candidate`;
                            }
                        }

                        // Render Structured Table
                        const tbody = document.getElementById('assocResultsTbody');
                        if (!tbody) return;

                        if (assocs.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="10" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                        No truck-box association candidates detected in this frame.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = assocs.map((a, idx) => {
                            const tId = a.truck_track_id;
                            const bId = a.box_track_id;
                            const tIdent = a.truck_identity || {};
                            const bIdent = a.box_identity || {};
                            const ev = a.evidence || {};
                            const score = a.association_score != null ? a.association_score.toFixed(2) : '-';
                            const dist = ev.normalized_distance != null ? ev.normalized_distance.toFixed(3) : '-';
                            const frames = ev.consecutive_frames != null ? ev.consecutive_frames : 1;
                            const zone = ev.truck_zone || ev.box_zone || '-';

                            // Status badge
                            let statusBadge = '<span class="badge" style="font-size:0.75rem; background:#64748b; color:#fff;">CANDIDATE</span>';
                            if (a.status === 'CONFIRMED') {
                                statusBadge = '<span class="badge sent" style="font-size:0.75rem; background:#10b981; color:#fff;">✓ CONFIRMED</span>';
                            } else if (ev.is_ambiguous) {
                                statusBadge = '<span class="badge" style="font-size:0.75rem; background:#ec4899; color:#fff;">⚡ AMBIGUOUS</span>';
                            } else if (a.status === 'CANDIDATE') {
                                statusBadge = '<span class="badge" style="font-size:0.75rem; background:#f59e0b; color:#fff;">⏱ CANDIDATE</span>';
                            } else if (a.status === 'REJECTED') {
                                statusBadge = '<span class="badge" style="font-size:0.75rem; background:#ef4444; color:#fff;">✗ REJECTED</span>';
                            } else if (a.status === 'EXPIRED') {
                                statusBadge = '<span class="badge disabled-status" style="font-size:0.75rem;">⏳ EXPIRED</span>';
                            }

                            // Identity format
                            const tIdentHtml = tIdent.value
                                ? `<strong style="font-family:monospace; color:var(--text-main); font-size:0.82rem;">${escapeHtml(tIdent.value)}</strong> <span style="font-size:0.68rem; color:${tIdent.validation_status === 'VALIDATED' ? '#10b981' : '#f59e0b'}; font-weight:700;">${escapeHtml(tIdent.validation_status)}</span>`
                                : `<span style="color:var(--text-muted); font-size:0.75rem;">UNIDENTIFIED</span>`;

                            const bIdentHtml = bIdent.value
                                ? `<strong style="font-family:monospace; color:var(--text-main); font-size:0.82rem;">${escapeHtml(bIdent.value)}</strong> <span style="font-size:0.68rem; color:${bIdent.validation_status === 'VALIDATED' ? '#10b981' : '#f59e0b'}; font-weight:700;">${escapeHtml(bIdent.validation_status)}</span>`
                                : `<span style="color:var(--text-muted); font-size:0.75rem;">UNIDENTIFIED</span>`;

                            return `
                                <tr>
                                    <td style="text-align:center;">
                                        <span style="font-size:0.85rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.12); padding:2px 6px; border-radius:4px; font-family:monospace;">
                                            #${tId}
                                        </span>
                                    </td>
                                    <td>${tIdentHtml}</td>
                                    <td style="text-align:center;">
                                        <span style="font-size:0.85rem; font-weight:800; color:#0284c7; background:rgba(2,132,199,0.12); padding:2px 6px; border-radius:4px; font-family:monospace;">
                                            #${bId}
                                        </span>
                                    </td>
                                    <td>${bIdentHtml}</td>
                                    <td style="text-align:center;">${statusBadge}</td>
                                    <td style="text-align:center;">
                                        <strong style="font-size:0.88rem; font-family:monospace; color:${a.status === 'CONFIRMED' ? '#10b981' : 'var(--text-main)'};">${score}</strong>
                                    </td>
                                    <td style="font-size:0.78rem;">
                                        <span class="badge" style="background:rgba(139,92,246,0.12); color:#8b5cf6; font-size:0.7rem; font-family:monospace;">${escapeHtml(zone)}</span>
                                    </td>
                                    <td style="text-align:center; font-family:monospace; font-size:0.78rem; color:var(--text-muted);">${dist}</td>
                                    <td style="text-align:center; font-size:0.8rem; font-weight:700; color:var(--text-main);">${frames}</td>
                                    <td style="text-align:center;">
                                        <button type="button" class="btn-secondary" onclick="openAssociationEvidenceModal(${idx})" style="padding:2px 8px; font-size:0.72rem; cursor:pointer;">
                                            🔍 Evidence
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    function openAssociationEvidenceModal(index) {
                        const assoc = latestAssociationsList[index];
                        if (!assoc) return;

                        const modal = document.getElementById('assocEvidenceModal');
                        const title = document.getElementById('modalAssocTitle');
                        const content = document.getElementById('modalAssocContent');

                        if (title) {
                            title.innerText = `Evidence: Truck #${assoc.truck_track_id} ↔ Box #${assoc.box_track_id} [${assoc.status}]`;
                        }

                        const ev = assoc.evidence || {};
                        const rw = assoc.real_world_association;

                        const rwHtml = rw && rw.status === 'VALIDATED'
                            ? `<div style="background:rgba(16,185,129,0.12); border:1px solid #10b981; border-radius:8px; padding:10px; margin-bottom:12px;">
                                <strong style="color:#10b981; font-size:0.85rem;">✓ Validated Real-World Association Bound:</strong>
                                <div style="font-family:monospace; font-size:0.92rem; color:var(--text-main); margin-top:4px;">
                                    Truck <strong>${escapeHtml(rw.truck_id)}</strong> ↔ Box <strong>${escapeHtml(rw.box_id)}</strong>
                                </div>
                                <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">
                                    Both identities validated against authoritative WMS master records.
                                </div>
                               </div>`
                            : `<div style="background:var(--panel-subtle); border:1px solid var(--border-light); border-radius:8px; padding:10px; margin-bottom:12px;">
                                <span style="font-size:0.82rem; color:var(--text-muted);">
                                    Track-level association only. Real-world identity binding requires BOTH underlying entities to be VALIDATED in Part 8.
                                </span>
                               </div>`;

                        const ambHtml = ev.is_ambiguous
                            ? `<div style="background:rgba(236,72,153,0.12); border:1px solid #ec4899; border-radius:8px; padding:10px; margin-bottom:12px;">
                                <strong style="color:#ec4899; font-size:0.85rem;">⚡ Ambiguity Flag Active:</strong>
                                <p style="font-size:0.8rem; margin:4px 0 0 0; color:var(--text-main); line-height:1.4;">
                                    ${escapeHtml(ev.ambiguity_reason || 'Multiple competing trucks within threshold delta.')}
                                </p>
                               </div>`
                            : '';

                        if (content) {
                            content.innerHTML = `
                                ${rwHtml}
                                ${ambHtml}
                                <table style="width:100%; font-size:0.82rem; margin-bottom:12px;">
                                    <tbody>
                                        <tr>
                                            <td style="width:40%; font-weight:700; color:var(--text-muted); padding:6px 0;">Composite Score:</td>
                                            <td style="font-weight:800; font-family:monospace; font-size:0.95rem; color:${assoc.status === 'CONFIRMED' ? '#10b981' : 'var(--text-main)'};">
                                                ${assoc.association_score != null ? assoc.association_score.toFixed(4) : '-'} (Required &ge; 0.70)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Consecutive Frames:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.consecutive_frames} frames (Required &ge; 3)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Normalized Distance:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.normalized_distance} (Max Allowed: ${ev.max_allowed_distance})
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Same Warehouse Zone:</td>
                                            <td style="color:${ev.same_zone ? '#10b981' : '#ef4444'}; font-weight:700;">
                                                ${ev.same_zone ? '✓ True (Matching Zone)' : '✗ False (Different or Unresolved Zones)'}
                                                <span style="font-size:0.75rem; color:var(--text-muted); font-weight:normal; margin-left:6px;">
                                                    [Truck: ${ev.truck_zone || 'None'}, Box: ${ev.box_zone || 'None'}]
                                                </span>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Spatial Proximity Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.spatial_proximity_score} (Weight: 35%)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Zone Match Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.zone_score} (Weight: 35%)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Temporal Persistence Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.temporal_persistence_score} (Weight: 30%)
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                                <details style="background:var(--panel-subtle); padding:8px 12px; border-radius:6px; font-size:0.75rem; cursor:pointer;">
                                    <summary style="font-weight:700; color:var(--text-muted);">Raw Evidence JSON</summary>
                                    <pre style="margin:8px 0 0 0; font-family:monospace; color:var(--text-main); font-size:0.72rem; overflow-x:auto;">${escapeHtml(JSON.stringify(assoc, null, 2))}</pre>
                                </details>
                            `;
                        }

                        if (modal) modal.style.display = 'flex';
                    }

                    function closeAssociationEvidenceModal() {
                        const modal = document.getElementById('assocEvidenceModal');
                        if (modal) modal.style.display = 'none';
                    }

                    // ============================================================================
                    // PART 10: WORKER <-> BOX ASSOCIATION CLIENT JAVASCRIPT
                    // ============================================================================
                    let wbActiveCameraId = 'CAM-001';
                    let latestWorkerBoxAssociationsList = [];

                    async function initWorkerBoxTestUI() {
                        populateWorkerBoxCameras();
                        fetchWorkerBoxStatus();
                        handleWorkerBoxSourceChange();
                    }

                    async function populateWorkerBoxCameras() {
                        const select = document.getElementById('wbCameraSelect');
                        if (!select) return;

                        try {
                            const resCams = await fetch('/api/vision/cameras');
                            if (resCams.ok) {
                                const cams = await resCams.json();
                                const camList = Array.isArray(cams) ? cams : (cams.data || []);
                                select.innerHTML = camList.map(c => `
                                    <option value="${c.camera_id}" ${c.camera_id === wbActiveCameraId ? 'selected' : ''}>
                                        ${c.camera_code || c.camera_id} - ${c.name} (${c.location || 'General'})
                                    </option>
                                `).join('');
                                return;
                            }
                        } catch (e) {
                            console.warn("Could not load camera list for worker-box association test:", e);
                        }

                        select.innerHTML = `
                            <option value="CAM-001" selected>CAM-001 - Gate Camera 01 (Gate 01)</option>
                            <option value="CAM-002">CAM-002 - Dock Camera 01 (Dock 01)</option>
                        `;
                    }

                    async function fetchWorkerBoxStatus() {
                        try {
                            const res = await fetch('/api/vision/worker-box/status');
                            if (res.ok) {
                                const data = await res.json();
                                const badge = document.getElementById('wbEngineStatusBadge');
                                if (badge) {
                                    badge.innerText = `Engine: Active | In-Memory (Zero DB Writes)`;
                                }
                                if (data.config) {
                                    const cfg = data.config;
                                    const minF = document.getElementById('cfgWbMinFrames');
                                    const maxD = document.getElementById('cfgWbMaxDist');
                                    const minS = document.getElementById('cfgWbMinScore');
                                    const reqZ = document.getElementById('cfgWbRequireZone');
                                    const ambD = document.getElementById('cfgWbAmbiguityDelta');
                                    if (minF) minF.innerText = `${cfg.min_consecutive_frames} frames`;
                                    if (maxD) maxD.innerText = `${cfg.max_normalized_distance}`;
                                    if (minS) minS.innerText = `${cfg.min_association_score}`;
                                    if (reqZ) reqZ.innerText = cfg.require_same_zone ? 'STRICT (True)' : 'Optional (False)';
                                    if (ambD) ambD.innerText = `Δ ≤ ${cfg.ambiguity_threshold_delta}`;
                                }
                            }
                        } catch (e) {
                            console.warn("Could not fetch worker-box association status:", e);
                        }
                    }

                    function handleWorkerBoxSourceChange() {
                        const src = document.getElementById('wbSourceTypeSelect')?.value;
                        const uploadContainer = document.getElementById('wbUploadContainer');
                        if (uploadContainer) uploadContainer.style.display = (src === 'upload') ? 'block' : 'none';
                    }

                    function generateSyntheticWorkerBoxSequence(mode) {
                        const seq = [];
                        if (mode === 'synthetic_wb_confirm') {
                            // 5 consecutive frames: Worker #7 and Box #21 close in Dock 1
                            for (let f = 1; f <= 5; f++) {
                                seq.push([
                                    {
                                        track_id: 7,
                                        class_code: "WORKER",
                                        confidence: 0.96,
                                        bbox: { x1: 220, y1: 160, x2: 300, y2: 340 },
                                        bbox_normalized: { x1: 0.30, y1: 0.25, x2: 0.40, y2: 0.55 },
                                        center_normalized: [0.35, 0.40],
                                        roi: { inside: true, zone_code: "DOCK-01" },
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "Maddy", source: "FACE_ID", confidence: 0.98 },
                                        validation: { status: "VALIDATED", master_id: "Maddy", display_name: "Authorized Personnel (Maddy)" }
                                    },
                                    {
                                        track_id: 21,
                                        class_code: "BOX",
                                        confidence: 0.92,
                                        bbox: { x1: 290, y1: 280, x2: 370, y2: 370 },
                                        bbox_normalized: { x1: 0.38, y1: 0.45, x2: 0.48, y2: 0.60 },
                                        center_normalized: [0.43, 0.525],
                                        roi: { inside: true, zone_code: "DOCK-01" },
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "VLV-900", source: "QR", confidence: 0.99 },
                                        validation: { status: "VALIDATED", master_id: "VLV-900", display_name: "Box SKU: VLV-900" }
                                    }
                                ]);
                            }
                        } else if (mode === 'synthetic_wb_expire') {
                            // Frames 1-3: present and confirmed
                            for (let f = 1; f <= 3; f++) {
                                seq.push([
                                    {
                                        track_id: 7,
                                        class_code: "WORKER",
                                        confidence: 0.96,
                                        center_normalized: [0.35, 0.40],
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "Maddy" },
                                        validation: { status: "VALIDATED", master_id: "Maddy", display_name: "Authorized Personnel (Maddy)" }
                                    },
                                    {
                                        track_id: 21,
                                        class_code: "BOX",
                                        confidence: 0.92,
                                        center_normalized: [0.43, 0.525],
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "VLV-900" },
                                        validation: { status: "VALIDATED", master_id: "VLV-900", display_name: "Box SKU: VLV-900" }
                                    }
                                ]);
                            }
                            // Frames 4-8: box departed frame (only worker remains)
                            for (let f = 4; f <= 8; f++) {
                                seq.push([
                                    {
                                        track_id: 7,
                                        class_code: "WORKER",
                                        confidence: 0.96,
                                        center_normalized: [0.35, 0.40],
                                        roi_zone_code: "DOCK-01",
                                        identity: { status: "IDENTIFIED", value: "Maddy" },
                                        validation: { status: "VALIDATED", master_id: "Maddy", display_name: "Authorized Personnel (Maddy)" }
                                    }
                                ]);
                            }
                        }
                        return seq;
                    }

                    async function runWorkerBoxTest() {
                        const btn = document.getElementById('btnRunWorkerBox');
                        const originalHtml = btn ? btn.innerHTML : 'Run Single Frame';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Processing...';
                        }

                        try {
                            const cameraId = document.getElementById('wbCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('wbSourceTypeSelect')?.value || 'association_worker_box_dock1.jpg';

                            if (srcType.startsWith('synthetic_')) {
                                const seq = generateSyntheticWorkerBoxSequence(srcType);
                                const firstFrameTracks = seq[0] || [];
                                const res = await fetch('/api/vision/worker-box/test', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        camera_id: cameraId,
                                        synthetic_tracks: firstFrameTracks
                                    })
                                });
                                const data = await res.json();
                                if (!res.ok || !data.success) {
                                    alert(data.message || "Worker-Box association evaluation failed.");
                                    return;
                                }
                                renderWorkerBoxResults({
                                    camera_id: cameraId,
                                    active_worker_count: firstFrameTracks.filter(t => t.class_code === 'WORKER').length,
                                    active_box_count: firstFrameTracks.filter(t => t.class_code === 'BOX').length,
                                    associations: data.associations || [],
                                    performance: { association_ms: data.association_ms, total_ms: data.association_ms }
                                });
                                return;
                            }

                            let payload = { camera_id: cameraId };

                            if (srcType === 'camera') {
                                payload.source_type = 'camera';
                            } else if (srcType === 'upload') {
                                const fileInput = document.getElementById('wbFileInput');
                                if (!fileInput || !fileInput.files[0]) {
                                    alert("Please select an image file to upload.");
                                    return;
                                }
                                const reader = new FileReader();
                                reader.onload = async function(e) {
                                    payload.source_type = 'upload';
                                    payload.image_data = e.target.result;
                                    await sendWorkerBoxRequest(payload, btn, originalHtml);
                                };
                                reader.readAsDataURL(fileInput.files[0]);
                                return;
                            } else {
                                payload.source_type = 'sample';
                                payload.sample_scene = srcType;
                            }

                            await sendWorkerBoxRequest(payload, btn, originalHtml);
                        } catch (e) {
                            alert("Worker-Box association request error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function sendWorkerBoxRequest(payload, btn, originalHtml) {
                        try {
                            const res = await fetch('/api/vision/worker-box/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });
                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.message || "Worker-Box association evaluation failed.");
                                return;
                            }
                            renderWorkerBoxResults(data);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function runWorkerBoxSequence() {
                        const btn = document.getElementById('btnRunWorkerBoxSeq');
                        const originalHtml = btn ? btn.innerHTML : 'Run Sequence (5 Frames)';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Evaluating Sequence...';
                        }

                        try {
                            const cameraId = document.getElementById('wbCameraSelect')?.value || 'CAM-001';
                            const srcType = document.getElementById('wbSourceTypeSelect')?.value || 'association_worker_box_dock1.jpg';

                            let payload = {
                                camera_id: cameraId,
                                num_frames: 5,
                                reset_session: true
                            };

                            if (srcType.startsWith('synthetic_')) {
                                payload.synthetic_tracks_sequence = generateSyntheticWorkerBoxSequence(srcType);
                            } else if (srcType === 'camera' || srcType === 'upload') {
                                payload.sample_scene = 'association_worker_box_dock1.jpg';
                            } else {
                                payload.sample_scene = srcType;
                            }

                            const res = await fetch('/api/vision/worker-box/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });
                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.message || "Sequence evaluation failed.");
                                return;
                            }
                            const assocs = data.final_associations || data.associations || [];
                            renderWorkerBoxResults({
                                camera_id: cameraId,
                                active_worker_count: data.active_worker_count || 1,
                                active_box_count: data.active_box_count || 1,
                                associations: assocs,
                                annotated_image_url: data.annotated_image_url,
                                mode: data.mode,
                                total_frames: data.total_frames,
                                performance: data.performance || { association_ms: 1.5, total_ms: 22.0 }
                            });
                        } catch (e) {
                            alert("Sequence evaluation error: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function resetWorkerBoxSession() {
                        const cameraId = document.getElementById('wbCameraSelect')?.value || 'CAM-001';
                        try {
                            const res = await fetch('/api/vision/worker-box/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: cameraId })
                            });
                            const data = await res.json();
                            if (data.success) {
                                latestWorkerBoxAssociationsList = [];
                                // Reset KPIs
                                const kpiWorkers = document.getElementById('kpi-wb-workers');
                                const kpiBoxes = document.getElementById('kpi-wb-boxes');
                                const kpiConfirmed = document.getElementById('kpi-wb-confirmed');
                                const kpiCandidates = document.getElementById('kpi-wb-candidates');
                                const kpiRejected = document.getElementById('kpi-wb-rejected');
                                const kpiAmbiguous = document.getElementById('kpi-wb-ambiguous');
                                const kpiMs = document.getElementById('kpi-wb-ms');
                                const kpiTotalMs = document.getElementById('kpi-wb-total-ms');
                                if (kpiWorkers) kpiWorkers.innerText = '0';
                                if (kpiBoxes) kpiBoxes.innerText = '0';
                                if (kpiConfirmed) kpiConfirmed.innerText = '0';
                                if (kpiCandidates) kpiCandidates.innerText = '0';
                                if (kpiRejected) kpiRejected.innerText = '0';
                                if (kpiAmbiguous) kpiAmbiguous.innerText = '0';
                                if (kpiMs) kpiMs.innerText = '-';
                                if (kpiTotalMs) kpiTotalMs.innerText = 'Total: -';

                                // Reset image
                                const img = document.getElementById('wbAnnotatedImage');
                                const placeholder = document.getElementById('wbImagePlaceholder');
                                const badge = document.getElementById('wbImageMetaBadge');
                                if (img) { img.src = ''; img.style.display = 'none'; }
                                if (placeholder) placeholder.style.display = 'block';
                                if (badge) badge.innerText = 'Session Reset';

                                // Reset table
                                const tbody = document.getElementById('wbResultsTbody');
                                if (tbody) {
                                    tbody.innerHTML = `
                                        <tr>
                                            <td colspan="10" style="text-align:center; padding:2.5rem 1rem; color:var(--text-muted);">
                                                Worker-Box association session reset. In-memory associations and tracking cleared.
                                            </td>
                                        </tr>
                                    `;
                                }
                                const countBadge = document.getElementById('wbCountBadge');
                                if (countBadge) countBadge.innerText = '0 Associations';
                            }
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        }
                    }

                    function renderWorkerBoxResults(data) {
                        const assocs = data.associations || data.final_associations || [];
                        latestWorkerBoxAssociationsList = assocs;
                        const perf = data.performance || {};

                        // Update KPIs
                        const confirmedCount = assocs.filter(a => a.status === 'CONFIRMED').length;
                        const candidateCount = assocs.filter(a => a.status === 'CANDIDATE').length;
                        const rejectedCount = assocs.filter(a => a.status === 'REJECTED').length;
                        const ambiguousCount = assocs.filter(a => a.evidence && a.evidence.is_ambiguous).length;

                        const kpiWorkers = document.getElementById('kpi-wb-workers');
                        const kpiBoxes = document.getElementById('kpi-wb-boxes');
                        const kpiConfirmed = document.getElementById('kpi-wb-confirmed');
                        const kpiCandidates = document.getElementById('kpi-wb-candidates');
                        const kpiRejected = document.getElementById('kpi-wb-rejected');
                        const kpiAmbiguous = document.getElementById('kpi-wb-ambiguous');
                        const kpiMs = document.getElementById('kpi-wb-ms');
                        const kpiTotalMs = document.getElementById('kpi-wb-total-ms');
                        const countBadge = document.getElementById('wbCountBadge');

                        if (kpiWorkers) kpiWorkers.innerText = data.active_worker_count != null ? data.active_worker_count : '-';
                        if (kpiBoxes) kpiBoxes.innerText = data.active_box_count != null ? data.active_box_count : '-';
                        if (kpiConfirmed) kpiConfirmed.innerText = confirmedCount;
                        if (kpiCandidates) kpiCandidates.innerText = candidateCount;
                        if (kpiRejected) kpiRejected.innerText = rejectedCount;
                        if (kpiAmbiguous) kpiAmbiguous.innerText = ambiguousCount;

                        const assocMs = perf.association_ms != null ? perf.association_ms : data.association_ms;
                        if (kpiMs) kpiMs.innerText = assocMs != null ? assocMs.toFixed(2) + ' ms' : '-';
                        if (kpiTotalMs) kpiTotalMs.innerText = `Total: ${(perf.total_ms != null ? perf.total_ms : (assocMs || 0)).toFixed(2)} ms`;
                        if (countBadge) countBadge.innerText = `${assocs.length} ${assocs.length === 1 ? 'Pair' : 'Pairs'}`;

                        // Annotated image
                        const img = document.getElementById('wbAnnotatedImage');
                        const placeholder = document.getElementById('wbImagePlaceholder');
                        const metaBadge = document.getElementById('wbImageMetaBadge');

                        if (data.annotated_image_url && img) {
                            img.src = data.annotated_image_url;
                            img.style.display = 'block';
                            if (placeholder) placeholder.style.display = 'none';
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `${data.camera_id} | ${confirmedCount} Confirmed | ${ambiguousCount} Ambiguous`;
                            }
                        } else if (!data.annotated_image_url && img && (data.mode === 'synthetic_tracks' || data.synthetic_tracks_sequence)) {
                            img.style.display = 'none';
                            if (placeholder) {
                                placeholder.style.display = 'block';
                                placeholder.innerHTML = `
                                    <div style="font-size:2.8rem; margin-bottom:0.75rem; color:#10b981;">⚡ 👷 ↔ 📦</div>
                                    <p style="margin:0; font-size:0.9rem; font-weight:700; color:var(--text-main);">Deterministic Synthetic Sequence Evaluated</p>
                                    <p style="margin:4px 0 0 0; font-size:0.78rem; color:var(--text-muted);">${confirmedCount} Confirmed | ${candidateCount} Candidate | ${ambiguousCount} Ambiguous</p>
                                `;
                            }
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `Synthetic Tracks Feed | Frame #${data.frame_index || 5}`;
                            }
                        }

                        // Structured Table
                        const tbody = document.getElementById('wbResultsTbody');
                        if (!tbody) return;

                        if (assocs.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="10" style="text-align:center; padding:2.5rem 1rem; color:var(--text-muted);">
                                        No Worker ↔ Box candidate associations detected in this frame.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = assocs.map((a, idx) => {
                            const wid = a.worker_track_id;
                            const bid = a.box_track_id;
                            const ev = a.evidence || {};
                            const rw = a.real_world_association;

                            // Status badge
                            let statusBadge = '';
                            if (ev.is_ambiguous) {
                                statusBadge = `<span class="badge" style="background:#ec4899; color:#fff; font-weight:800; font-size:0.72rem;">⚡ AMBIGUOUS</span>`;
                            } else if (a.status === 'CONFIRMED') {
                                statusBadge = `<span class="badge sent" style="background:#10b981; color:#fff; font-weight:800; font-size:0.72rem;">✓ CONFIRMED</span>`;
                            } else if (a.status === 'CANDIDATE') {
                                statusBadge = `<span class="badge pending" style="background:#f59e0b; color:#fff; font-weight:800; font-size:0.72rem;">⏳ CANDIDATE</span>`;
                            } else if (a.status === 'REJECTED') {
                                statusBadge = `<span class="badge cancel" style="background:#ef4444; color:#fff; font-weight:800; font-size:0.72rem;">✕ REJECTED</span>`;
                            } else if (a.status === 'EXPIRED') {
                                statusBadge = `<span class="badge" style="background:#6b7280; color:#fff; font-weight:800; font-size:0.72rem;">⏱ EXPIRED</span>`;
                            } else {
                                statusBadge = `<span class="badge">${a.status}</span>`;
                            }

                            // Worker ID & Box ID
                            const wIdent = a.worker_identity || {};
                            const bIdent = a.box_identity || {};

                            const wIdentDisplay = wIdent.value
                                ? `<span class="badge sent" style="font-size:0.68rem; background:rgba(37,99,235,0.12); color:var(--accent); font-family:monospace;">${escapeHtml(wIdent.value)}</span>`
                                : `<span style="color:var(--text-muted); font-size:0.72rem;">-</span>`;

                            const bIdentDisplay = bIdent.value
                                ? `<span class="badge sent" style="font-size:0.68rem; background:rgba(2,132,199,0.12); color:#0284c7; font-family:monospace;">${escapeHtml(bIdent.value)}</span>`
                                : `<span style="color:var(--text-muted); font-size:0.72rem;">-</span>`;

                            const score = a.association_score != null ? a.association_score.toFixed(3) : '-';
                            const dist = ev.normalized_distance != null ? ev.normalized_distance.toFixed(3) : '-';
                            const frames = ev.consecutive_frames != null ? ev.consecutive_frames : 0;
                            const zone = ev.worker_zone && ev.box_zone && ev.worker_zone === ev.box_zone
                                ? ev.worker_zone
                                : (ev.worker_zone ? `${ev.worker_zone}≠${ev.box_zone || 'None'}` : 'Unresolved');

                            return `
                                <tr>
                                    <td style="text-align:center;">
                                        <span style="font-size:0.85rem; font-weight:800; color:var(--accent); background:rgba(37,99,235,0.12); padding:2px 7px; border-radius:5px; font-family:monospace;">
                                            W#${wid}
                                        </span>
                                    </td>
                                    <td>${wIdentDisplay}</td>
                                    <td style="text-align:center;">
                                        <span style="font-size:0.85rem; font-weight:800; color:#0284c7; background:rgba(2,132,199,0.12); padding:2px 7px; border-radius:5px; font-family:monospace;">
                                            B#${bid}
                                        </span>
                                    </td>
                                    <td>${bIdentDisplay}</td>
                                    <td style="text-align:center;">${statusBadge}</td>
                                    <td style="text-align:center;">
                                        <strong style="font-size:0.88rem; font-family:monospace; color:${a.status === 'CONFIRMED' ? '#10b981' : 'var(--text-main)'};">${score}</strong>
                                    </td>
                                    <td style="font-size:0.78rem;">
                                        <span class="badge" style="background:rgba(139,92,246,0.12); color:#8b5cf6; font-size:0.7rem; font-family:monospace;">${escapeHtml(zone)}</span>
                                    </td>
                                    <td style="text-align:center; font-family:monospace; font-size:0.78rem; color:var(--text-muted);">${dist}</td>
                                    <td style="text-align:center; font-size:0.8rem; font-weight:700; color:var(--text-main);">${frames}</td>
                                    <td style="text-align:center;">
                                        <button type="button" class="btn-secondary" onclick="openWorkerBoxEvidenceModal(${idx})" style="padding:2px 8px; font-size:0.72rem; cursor:pointer;">
                                            🔍 Evidence
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    function openWorkerBoxEvidenceModal(index) {
                        const assoc = latestWorkerBoxAssociationsList[index];
                        if (!assoc) return;

                        const modal = document.getElementById('wbEvidenceModal');
                        const title = document.getElementById('modalWbTitle');
                        const content = document.getElementById('modalWbContent');

                        if (title) {
                            title.innerText = `Evidence: Worker #${assoc.worker_track_id} ↔ Box #${assoc.box_track_id} [${assoc.status}]`;
                        }

                        const ev = assoc.evidence || {};
                        const rw = assoc.real_world_association;

                        const rwHtml = rw && rw.status === 'VALIDATED'
                            ? `<div style="background:rgba(16,185,129,0.12); border:1px solid #10b981; border-radius:8px; padding:10px; margin-bottom:12px;">
                                <strong style="color:#10b981; font-size:0.85rem;">✓ Validated Real-World Association Bound:</strong>
                                <div style="font-family:monospace; font-size:0.92rem; color:var(--text-main); margin-top:4px;">
                                    Worker <strong>${escapeHtml(rw.worker_display || rw.worker_id)}</strong> ↔ Box <strong>${escapeHtml(rw.box_display || rw.box_id)}</strong>
                                </div>
                                <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">
                                    Both identities validated against authoritative WMS master records.
                                </div>
                               </div>`
                            : `<div style="background:var(--panel-subtle); border:1px solid var(--border-light); border-radius:8px; padding:10px; margin-bottom:12px;">
                                <span style="font-size:0.82rem; color:var(--text-muted);">
                                    Track-level association only. Real-world identity binding requires BOTH underlying entities to be VALIDATED in Part 8.
                                </span>
                               </div>`;

                        const ambHtml = ev.is_ambiguous
                            ? `<div style="background:rgba(236,72,153,0.12); border:1px solid #ec4899; border-radius:8px; padding:10px; margin-bottom:12px;">
                                <strong style="color:#ec4899; font-size:0.85rem;">⚡ Ambiguity Flag Active:</strong>
                                <p style="font-size:0.8rem; margin:4px 0 0 0; color:var(--text-main); line-height:1.4;">
                                    ${escapeHtml(ev.ambiguity_reason || 'Multiple competing workers within threshold delta.')}
                                </p>
                               </div>`
                            : '';

                        if (content) {
                            content.innerHTML = `
                                ${rwHtml}
                                ${ambHtml}
                                <table style="width:100%; font-size:0.82rem; margin-bottom:12px;">
                                    <tbody>
                                        <tr>
                                            <td style="width:40%; font-weight:700; color:var(--text-muted); padding:6px 0;">Composite Score:</td>
                                            <td style="font-weight:800; font-family:monospace; font-size:0.95rem; color:${assoc.status === 'CONFIRMED' ? '#10b981' : 'var(--text-main)'};">
                                                ${assoc.association_score != null ? assoc.association_score.toFixed(4) : '-'} (Required &ge; 0.70)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Consecutive Frames:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.consecutive_frames} frames (Required &ge; 3)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Normalized Distance:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.normalized_distance} (Max Allowed: ${ev.max_allowed_distance})
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Same Warehouse Zone:</td>
                                            <td style="color:${ev.same_zone ? '#10b981' : '#ef4444'}; font-weight:700;">
                                                ${ev.same_zone ? '✓ True (Matching Zone)' : '✗ False (Different or Unresolved Zones)'}
                                                <span style="font-size:0.75rem; color:var(--text-muted); font-weight:normal; margin-left:6px;">
                                                    [Worker: ${ev.worker_zone || 'None'}, Box: ${ev.box_zone || 'None'}]
                                                </span>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Spatial Proximity Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.spatial_proximity_score} (Weight: 35%)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Zone Match Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.zone_score} (Weight: 35%)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Temporal Persistence Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.temporal_persistence_score} (Weight: 30%)
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                                <details style="background:var(--panel-subtle); padding:8px 12px; border-radius:6px; font-size:0.75rem; cursor:pointer;">
                                    <summary style="font-weight:700; color:var(--text-muted);">Raw Evidence JSON</summary>
                                    <pre style="margin:8px 0 0 0; font-family:monospace; color:var(--text-main); font-size:0.72rem; overflow-x:auto;">${escapeHtml(JSON.stringify(assoc, null, 2))}</pre>
                                </details>
                            `;
                        }

                        if (modal) modal.style.display = 'flex';
                    }

                    function closeWorkerBoxEvidenceModal() {
                        const modal = document.getElementById('wbEvidenceModal');
                        if (modal) modal.style.display = 'none';
                    }

                    // ========================================================================
                    // PART 11: BOX <-> BIN ASSOCIATION JAVASCRIPT CONTROLLER
                    // ========================================================================
                    let bbActiveCameraId = 'CAM-001';
                    let latestBoxBinAssociationsList = [];

                    async function initBoxBinTestUI() {
                        populateBoxBinCameras();
                        fetchBoxBinStatus();
                        handleBoxBinSourceChange();
                    }

                    async function populateBoxBinCameras() {
                        const select = document.getElementById('bbCameraSelect');
                        if (!select) return;

                        try {
                            const resCams = await fetch('/api/vision/cameras');
                            if (resCams.ok) {
                                const cams = await resCams.json();
                                const camList = Array.isArray(cams) ? cams : (cams.data || []);
                                select.innerHTML = camList.map(c => `
                                    <option value="${c.camera_id}" ${c.camera_id === bbActiveCameraId ? 'selected' : ''}>
                                        ${c.camera_code || c.camera_id} - ${c.name} (${c.location || 'General'})
                                    </option>
                                `).join('');
                                return;
                            }
                        } catch (e) {
                            console.warn("Could not load camera list for box-bin association test:", e);
                        }

                        select.innerHTML = `
                            <option value="CAM-001" selected>CAM-001 - Gate Camera 01 (Gate 01)</option>
                            <option value="CAM-002">CAM-002 - Dock Camera 01 (Dock 01)</option>
                        `;
                    }

                    async function fetchBoxBinStatus() {
                        try {
                            const res = await fetch('/api/vision/box-bin/status');
                            if (res.ok) {
                                const data = await res.json();
                                const badge = document.getElementById('bbEngineStatusBadge');
                                if (badge) {
                                    badge.innerText = `Engine: Active | In-Memory (Zero DB Writes)`;
                                }
                                if (data.config) {
                                    const cfg = data.config;
                                    const minF = document.getElementById('cfgBbMinFrames');
                                    const maxD = document.getElementById('cfgBbMaxDist');
                                    const minS = document.getElementById('cfgBbMinScore');
                                    const reqZ = document.getElementById('cfgBbRequireZone');
                                    const ambD = document.getElementById('cfgBbAmbiguityDelta');
                                    if (minF) minF.innerText = `${cfg.min_consecutive_frames} frames`;
                                    if (maxD) maxD.innerText = `${cfg.max_normalized_distance}`;
                                    if (minS) minS.innerText = `${cfg.min_association_score}`;
                                    if (reqZ) reqZ.innerText = cfg.require_same_zone ? 'STRICT (True)' : 'Optional (False)';
                                    if (ambD) ambD.innerText = `Δ ≤ ${cfg.ambiguity_threshold_delta}`;
                                }
                            }
                        } catch (e) {
                            console.warn("Could not fetch box-bin association status:", e);
                        }
                    }

                    function handleBoxBinSourceChange() {
                        const src = document.getElementById('bbSourceTypeSelect')?.value;
                        const uploadContainer = document.getElementById('bbUploadContainer');
                        if (uploadContainer) uploadContainer.style.display = (src === 'upload') ? 'block' : 'none';
                    }

                    function generateSyntheticBoxBinSequence(mode) {
                        const seq = [];
                        if (mode === 'synthetic_bb_confirm') {
                            // 5 consecutive frames: Box #21 and Bin #15 close in BIN-A
                            for (let f = 1; f <= 5; f++) {
                                seq.push([
                                    {
                                        track_id: 21,
                                        class_code: "BOX",
                                        confidence: 0.95,
                                        bbox: { x1: 240, y1: 240, x2: 360, y2: 380 },
                                        bbox_normalized: { x1: 0.375, y1: 0.50, x2: 0.562, y2: 0.792 },
                                        roi_zone_code: "BIN-A",
                                        identity: { value: "VLV-900", status: "IDENTIFIED", source: "QR" }
                                    },
                                    {
                                        track_id: 15,
                                        class_code: "BIN",
                                        confidence: 0.96,
                                        bbox: { x1: 180, y1: 220, x2: 320, y2: 400 },
                                        bbox_normalized: { x1: 0.281, y1: 0.458, x2: 0.50, y2: 0.833 },
                                        roi_zone_code: "BIN-A",
                                        identity: { value: "BIN-A", status: "IDENTIFIED", source: "QR" }
                                    }
                                ]);
                            }
                        } else if (mode === 'synthetic_bb_expire') {
                            // Frame 1-3: Confirmed Box #21 + Bin #15
                            for (let f = 1; f <= 3; f++) {
                                seq.push([
                                    {
                                        track_id: 21,
                                        class_code: "BOX",
                                        bbox: { x1: 240, y1: 240, x2: 360, y2: 380 },
                                        bbox_normalized: { x1: 0.375, y1: 0.50, x2: 0.562, y2: 0.792 },
                                        roi_zone_code: "BIN-A",
                                        identity: { value: "VLV-900", status: "IDENTIFIED", source: "QR" }
                                    },
                                    {
                                        track_id: 15,
                                        class_code: "BIN",
                                        bbox: { x1: 180, y1: 220, x2: 320, y2: 400 },
                                        bbox_normalized: { x1: 0.281, y1: 0.458, x2: 0.50, y2: 0.833 },
                                        roi_zone_code: "BIN-A",
                                        identity: { value: "BIN-A", status: "IDENTIFIED", source: "QR" }
                                    }
                                ]);
                            }
                            // Frame 4-7: Box moved away/departed (missed_frames accumulates to 4 -> EXPIRED)
                            for (let f = 4; f <= 7; f++) {
                                seq.push([
                                    {
                                        track_id: 15,
                                        class_code: "BIN",
                                        bbox: { x1: 180, y1: 220, x2: 320, y2: 400 },
                                        bbox_normalized: { x1: 0.281, y1: 0.458, x2: 0.50, y2: 0.833 },
                                        roi_zone_code: "BIN-A",
                                        identity: { value: "BIN-A", status: "IDENTIFIED", source: "QR" }
                                    }
                                ]);
                            }
                        }
                        return seq;
                    }

                    async function runBoxBinTest() {
                        const btn = document.getElementById('btnRunBoxBin');
                        const originalHtml = btn ? btn.innerHTML : 'Run Association Test';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Processing...';
                        }

                        const srcType = document.getElementById('bbSourceTypeSelect')?.value || 'association_box_bin_dock1.jpg';
                        const camId = document.getElementById('bbCameraSelect')?.value || 'CAM-001';
                        bbActiveCameraId = camId;

                        try {
                            if (srcType === 'synthetic_bb_confirm' || srcType === 'synthetic_bb_expire') {
                                await runBoxBinSequence(srcType);
                                return;
                            }

                            let payload = {
                                camera_id: camId,
                                source_type: 'sample',
                                sample_scene: srcType
                            };

                            if (srcType === 'camera') {
                                payload.source_type = 'camera';
                            } else if (srcType === 'upload') {
                                const fileInput = document.getElementById('bbUploadInput');
                                if (!fileInput || !fileInput.files[0]) {
                                    alert("Please select an image file to upload.");
                                    return;
                                }
                                const file = fileInput.files[0];
                                const base64 = await new Promise((resolve) => {
                                    const reader = new FileReader();
                                    reader.onload = () => resolve(reader.result);
                                    reader.readAsDataURL(file);
                                });
                                payload.source_type = 'upload';
                                payload.image_base64 = base64;
                            }

                            const res = await fetch('/api/vision/box-bin/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            if (!res.ok) {
                                const err = await res.json();
                                alert("Association test failed: " + (err.message || res.statusText));
                                return;
                            }

                            const data = await res.json();
                            renderBoxBinResults(data);
                        } catch (e) {
                            alert("Error running Box <-> Bin test: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function runBoxBinSequence(modeOverride) {
                        const btn = document.getElementById('btnStepBoxBin');
                        const originalHtml = btn ? btn.innerHTML : 'Step Sequence';
                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = '<span>⏳</span> Sequencer Active...';
                        }

                        const srcType = modeOverride || document.getElementById('bbSourceTypeSelect')?.value || 'association_box_bin_dock1.jpg';
                        const camId = document.getElementById('bbCameraSelect')?.value || 'CAM-001';
                        bbActiveCameraId = camId;

                        try {
                            let payload = {
                                camera_id: camId,
                                num_frames: 5,
                                reset_session: true
                            };

                            if (srcType === 'synthetic_bb_confirm' || srcType === 'synthetic_bb_expire') {
                                payload.synthetic_tracks_sequence = generateSyntheticBoxBinSequence(srcType);
                            } else {
                                payload.sample_scene = srcType;
                            }

                            const res = await fetch('/api/vision/box-bin/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });

                            if (!res.ok) {
                                const err = await res.json();
                                alert("Sequence test failed: " + (err.message || res.statusText));
                                return;
                            }

                            const data = await res.json();
                            renderBoxBinResults(data);
                        } catch (e) {
                            alert("Sequence execution failed: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = originalHtml;
                            }
                        }
                    }

                    async function resetBoxBinSession() {
                        const camId = document.getElementById('bbCameraSelect')?.value || 'CAM-001';
                        if (!confirm(`Reset in-memory Box <-> Bin association tracking state for camera '${camId}'?`)) return;

                        try {
                            const res = await fetch('/api/vision/box-bin/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: camId })
                            });

                            if (res.ok) {
                                // Reset KPIs
                                document.getElementById('kpi-bb-boxes').innerText = '-';
                                document.getElementById('kpi-bb-bins').innerText = '-';
                                document.getElementById('kpi-bb-confirmed').innerText = '0';
                                document.getElementById('kpi-bb-candidates').innerText = '0';
                                document.getElementById('kpi-bb-rejected').innerText = '0';
                                document.getElementById('kpi-bb-ambiguous').innerText = '0';
                                document.getElementById('kpi-bb-ms').innerText = '-';
                                document.getElementById('kpi-bb-total-ms').innerText = 'Total: - ms';

                                // Reset image
                                const img = document.getElementById('bbAnnotatedImage');
                                const placeholder = document.getElementById('bbImagePlaceholder');
                                const badge = document.getElementById('bbImageMetaBadge');
                                if (img) { img.src = ''; img.style.display = 'none'; }
                                if (placeholder) placeholder.style.display = 'block';
                                if (badge) badge.innerText = 'Session Reset';

                                // Reset table
                                const tbody = document.getElementById('bbResultsTbody');
                                if (tbody) {
                                    tbody.innerHTML = `
                                        <tr>
                                            <td colspan="11" style="text-align:center; padding:2.5rem 1rem; color:var(--text-muted);">
                                                Box-Bin association session reset. In-memory associations and tracking cleared.
                                            </td>
                                        </tr>
                                    `;
                                }
                                const countBadge = document.getElementById('bbCountBadge');
                                if (countBadge) countBadge.innerText = '0 Pairs';
                            }
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        }
                    }

                    function renderBoxBinResults(data) {
                        const assocs = data.associations || data.final_associations || [];
                        latestBoxBinAssociationsList = assocs;
                        const perf = data.performance || {};

                        // Update KPIs
                        const confirmedCount = assocs.filter(a => a.status === 'CONFIRMED').length;
                        const candidateCount = assocs.filter(a => a.status === 'CANDIDATE').length;
                        const rejectedCount = assocs.filter(a => a.status === 'REJECTED').length;
                        const ambiguousCount = assocs.filter(a => a.evidence && a.evidence.is_ambiguous).length;

                        const kpiBoxes = document.getElementById('kpi-bb-boxes');
                        const kpiBins = document.getElementById('kpi-bb-bins');
                        const kpiConfirmed = document.getElementById('kpi-bb-confirmed');
                        const kpiCandidates = document.getElementById('kpi-bb-candidates');
                        const kpiRejected = document.getElementById('kpi-bb-rejected');
                        const kpiAmbiguous = document.getElementById('kpi-bb-ambiguous');
                        const kpiMs = document.getElementById('kpi-bb-ms');
                        const kpiTotalMs = document.getElementById('kpi-bb-total-ms');
                        const countBadge = document.getElementById('bbCountBadge');

                        if (kpiBoxes) kpiBoxes.innerText = data.active_boxes != null ? data.active_boxes : '-';
                        if (kpiBins) kpiBins.innerText = data.active_bins != null ? data.active_bins : '-';
                        if (kpiConfirmed) kpiConfirmed.innerText = confirmedCount;
                        if (kpiCandidates) kpiCandidates.innerText = candidateCount;
                        if (kpiRejected) kpiRejected.innerText = rejectedCount;
                        if (kpiAmbiguous) kpiAmbiguous.innerText = ambiguousCount;

                        const assocMs = perf.association_ms != null ? perf.association_ms : data.association_ms;
                        if (kpiMs) kpiMs.innerText = assocMs != null ? assocMs.toFixed(2) + ' ms' : '-';
                        if (kpiTotalMs) kpiTotalMs.innerText = `Total: ${(perf.total_ms != null ? perf.total_ms : (assocMs || 0)).toFixed(2)} ms`;
                        if (countBadge) countBadge.innerText = `${assocs.length} ${assocs.length === 1 ? 'Pair' : 'Pairs'}`;

                        // Annotated image
                        const img = document.getElementById('bbAnnotatedImage');
                        const placeholder = document.getElementById('bbImagePlaceholder');
                        const metaBadge = document.getElementById('bbImageMetaBadge');

                        if (data.annotated_frame && img) {
                            img.src = data.annotated_frame;
                            img.style.display = 'block';
                            if (placeholder) placeholder.style.display = 'none';
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `${data.camera_id} | ${confirmedCount} Confirmed | ${ambiguousCount} Ambiguous`;
                            }
                        } else if (!data.annotated_frame && img && (data.mode === 'synthetic_tracks' || data.mode === 'synthetic_sequence')) {
                            img.style.display = 'none';
                            if (placeholder) {
                                placeholder.style.display = 'block';
                                placeholder.innerHTML = `
                                    <div style="font-size:2.8rem; margin-bottom:0.75rem; color:#10b981;">⚡ 📦 ↔ 📥</div>
                                    <p style="margin:0; font-size:0.9rem; font-weight:700; color:var(--text-main);">Deterministic Synthetic Sequence Evaluated</p>
                                    <p style="margin:4px 0 0 0; font-size:0.78rem; color:var(--text-muted);">${confirmedCount} Confirmed | ${candidateCount} Candidate | ${ambiguousCount} Ambiguous</p>
                                `;
                            }
                            if (metaBadge) {
                                metaBadge.className = 'badge sent';
                                metaBadge.innerText = `Synthetic Sequence | ${confirmedCount} Confirmed`;
                            }
                        }

                        // Populate Associations Table
                        const tbody = document.getElementById('bbResultsTbody');
                        if (!tbody) return;

                        if (assocs.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="11" style="text-align:center; padding:2.5rem 1rem; color:var(--text-muted);">
                                        No active Box ↔ Bin candidate pairs found in this frame. Ensure both Box and Bin are detected.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = assocs.map((assoc, idx) => {
                            const ev = assoc.evidence || {};
                            const bId = assoc.box_identity || {};
                            const bnId = assoc.bin_identity || {};
                            const rw = assoc.real_world_association;

                            // Badge style for status
                            let statusBadge = '';
                            if (assoc.status === 'CONFIRMED') {
                                statusBadge = `<span class="badge" style="background:#10b981; color:#fff; font-weight:800;">CONFIRMED</span>`;
                            } else if (assoc.status === 'CANDIDATE') {
                                statusBadge = `<span class="badge" style="background:#f59e0b; color:#fff; font-weight:800;">CANDIDATE</span>`;
                            } else if (assoc.status === 'REJECTED') {
                                statusBadge = `<span class="badge" style="background:#ef4444; color:#fff; font-weight:800;">REJECTED</span>`;
                            } else {
                                statusBadge = `<span class="badge" style="background:#64748b; color:#fff; font-weight:800;">EXPIRED</span>`;
                            }

                            if (ev.is_ambiguous) {
                                statusBadge += `<br><span class="badge" style="background:#ec4899; color:#fff; font-size:0.65rem; margin-top:2px;">AMBIGUOUS</span>`;
                            }

                            // Real-world binding column
                            let rwHtml = '';
                            if (rw && rw.status === 'VALIDATED') {
                                rwHtml = `<div style="color:#10b981; font-weight:700; font-size:0.75rem;">
                                    ✓ ${escapeHtml(rw.box_id)} ↔ ${escapeHtml(rw.bin_id)}
                                    <div style="font-size:0.68rem; color:var(--text-muted); font-weight:400;">Validated Binding</div>
                                </div>`;
                            } else {
                                rwHtml = `<span style="color:var(--text-muted); font-size:0.75rem;">None (Visual Only)</span>`;
                            }

                            // Identity labels
                            const bLabel = bId.value ? `<code>${escapeHtml(bId.value)}</code>` : `<span style="color:var(--text-muted);">Unidentified</span>`;
                            const bnLabel = bnId.value ? `<code>${escapeHtml(bnId.value)}</code>` : `<span style="color:var(--text-muted);">Unidentified</span>`;

                            // Zone label
                            const zoneMatch = ev.same_zone
                                ? `<span style="color:#10b981; font-weight:700;">${escapeHtml(ev.box_zone || '-')}</span>`
                                : `<span style="color:#ef4444;">${escapeHtml(ev.box_zone || 'None')} ≠ ${escapeHtml(ev.bin_zone || 'None')}</span>`;

                            return `
                                <tr>
                                    <td><strong style="color:#d97706;">Box #${assoc.box_track_id}</strong></td>
                                    <td><strong style="color:#2563eb;">Bin #${assoc.bin_track_id}</strong></td>
                                    <td>${bLabel}</td>
                                    <td>${bnLabel}</td>
                                    <td>${zoneMatch}</td>
                                    <td><code>${ev.normalized_distance != null ? ev.normalized_distance.toFixed(3) : '-'}</code></td>
                                    <td><strong style="color:${ev.consecutive_frames >= 3 ? '#10b981' : 'var(--text-muted)'};">${ev.consecutive_frames || 1}</strong></td>
                                    <td><strong style="font-family:monospace; color:${assoc.association_score >= 0.70 ? '#10b981' : 'var(--text-main)'};">${assoc.association_score != null ? assoc.association_score.toFixed(3) : '-'}</strong></td>
                                    <td>${statusBadge}</td>
                                    <td>${rwHtml}</td>
                                    <td>
                                        <button class="btn-primary" onclick="showBoxBinEvidence(${idx})" style="padding:2px 8px; font-size:0.72rem; background:rgba(37,99,235,0.15); color:var(--accent); border:1px solid var(--accent);">
                                            Evidence
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    function showBoxBinEvidence(assocIndex) {
                        const assoc = latestBoxBinAssociationsList[assocIndex];
                        if (!assoc) return;

                        const modal = document.getElementById('bbEvidenceModal');
                        const title = document.getElementById('modalBbTitle');
                        const content = document.getElementById('modalBbContent');

                        if (title) {
                            title.innerText = `Evidence: Box #${assoc.box_track_id} ↔ Bin #${assoc.bin_track_id} [${assoc.status}]`;
                        }

                        const ev = assoc.evidence || {};
                        const rw = assoc.real_world_association;

                        const rwHtml = rw && rw.status === 'VALIDATED'
                            ? `<div style="background:rgba(16,185,129,0.12); border:1px solid #10b981; border-radius:8px; padding:10px; margin-bottom:12px;">
                                <strong style="color:#10b981; font-size:0.85rem;">✓ Validated Real-World Association Bound:</strong>
                                <div style="font-family:monospace; font-size:0.92rem; color:var(--text-main); margin-top:4px;">
                                    Box <strong>${escapeHtml(rw.box_display || rw.box_id)}</strong> ↔ Bin <strong>${escapeHtml(rw.bin_display || rw.bin_id)}</strong>
                                </div>
                                <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">
                                    Both identities validated against authoritative WMS master records.
                                </div>
                               </div>`
                            : `<div style="background:var(--panel-subtle); border:1px solid var(--border-light); border-radius:8px; padding:10px; margin-bottom:12px;">
                                <span style="font-size:0.82rem; color:var(--text-muted);">
                                    Track-level association only. Real-world identity binding requires BOTH underlying entities to be VALIDATED in Part 8.
                                </span>
                               </div>`;

                        const ambHtml = ev.is_ambiguous
                            ? `<div style="background:rgba(236,72,153,0.12); border:1px solid #ec4899; border-radius:8px; padding:10px; margin-bottom:12px;">
                                <strong style="color:#ec4899; font-size:0.85rem;">⚡ Ambiguity Flag Active:</strong>
                                <p style="font-size:0.8rem; margin:4px 0 0 0; color:var(--text-main); line-height:1.4;">
                                    ${escapeHtml(ev.ambiguity_reason || 'Multiple competing bins within threshold delta.')}
                                </p>
                               </div>`
                            : '';

                        if (content) {
                            content.innerHTML = `
                                ${rwHtml}
                                ${ambHtml}
                                <table style="width:100%; font-size:0.82rem; margin-bottom:12px;">
                                    <tbody>
                                        <tr>
                                            <td style="width:40%; font-weight:700; color:var(--text-muted); padding:6px 0;">Composite Score:</td>
                                            <td style="font-weight:800; font-family:monospace; font-size:0.95rem; color:${assoc.status === 'CONFIRMED' ? '#10b981' : 'var(--text-main)'};">
                                                ${assoc.association_score != null ? assoc.association_score.toFixed(4) : '-'} (Required &ge; 0.70)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Consecutive Frames:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.consecutive_frames} frames (Required &ge; 3)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Normalized Distance:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.normalized_distance} (Max Allowed: ${ev.max_allowed_distance})
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Spatial Proximity Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.spatial_proximity_score} (Weight: 35%)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Vision Zone Match Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.zone_score} (Weight: 35%)
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="font-weight:700; color:var(--text-muted); padding:6px 0;">Temporal Persistence Score:</td>
                                            <td style="font-family:monospace; color:var(--text-main);">
                                                ${ev.temporal_persistence_score} (Weight: 30%)
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                                <details style="background:var(--panel-subtle); padding:8px 12px; border-radius:6px; font-size:0.75rem; cursor:pointer;">
                                    <summary style="font-weight:700; color:var(--text-muted);">Raw Evidence JSON</summary>
                                    <pre style="margin:8px 0 0 0; font-family:monospace; color:var(--text-main); font-size:0.72rem; overflow-x:auto;">${escapeHtml(JSON.stringify(assoc, null, 2))}</pre>
                                </details>
                            `;
                        }

                        if (modal) modal.style.display = 'flex';
                    }

                    function closeBoxBinEvidenceModal() {
                        const modal = document.getElementById('bbEvidenceModal');
                        if (modal) modal.style.display = 'none';
                    }

                    // ============================================================================
                    // PART 12: WAREHOUSE MOVEMENT EVENT DETECTION FOUNDATION CONTROLLERS
                    // ============================================================================
                    let globalMovementEventsCache = [];

                    async function initMovementEventsTestUI() {
                        const camSelect = document.getElementById('evtCameraSelect');
                        if (camSelect && camSelect.options.length === 0) {
                            try {
                                const res = await fetch('/api/cameras');
                                const cams = await res.json();
                                camSelect.innerHTML = cams.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name || c.id)} (${escapeHtml(c.id)})</option>`).join('');
                            } catch (e) {
                                camSelect.innerHTML = '<option value="CAM-001">Dock 01 Camera (CAM-001)</option><option value="CAM-002">Bay Gate Camera (CAM-002)</option>';
                            }
                        }

                        // Fetch status & config from backend
                        try {
                            const stRes = await fetch('/api/vision/events/status');
                            const st = await stRes.json();
                            const badge = document.getElementById('evtEngineStatusBadge');
                            if (badge && st.status === 'healthy') {
                                badge.innerHTML = `Event Layer: Active | Zero DB Writes | In-Memory`;
                            }
                            if (st.config) {
                                const cfgTimeout = document.getElementById('cfgEvtTimeoutFrames');
                                if (cfgTimeout) cfgTimeout.innerText = `${st.config.event_timeout_frames} frames`;
                                const cfgDedup = document.getElementById('cfgEvtDeduplication');
                                if (cfgDedup) cfgDedup.innerText = st.config.enable_deduplication ? 'STRICT (True)' : 'Disabled';
                            }
                        } catch (e) {
                            console.warn("Could not fetch event status:", e);
                        }
                    }

                    function handleMovementEventSourceChange() {
                        const src = document.getElementById('evtSourceSelect');
                        const upCont = document.getElementById('evtUploadContainer');
                        if (src && upCont) {
                            upCont.style.display = (src.value === 'upload') ? 'block' : 'none';
                        }
                    }

                    async function runMovementEventsTest() {
                        const btn = document.getElementById('btnRunEventTest');
                        const srcSelect = document.getElementById('evtSourceSelect');
                        const camSelect = document.getElementById('evtCameraSelect');
                        const upInput = document.getElementById('evtUploadInput');

                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = `<span>⏳</span> Evaluating...`;
                        }

                        const scenario = srcSelect ? srcSelect.value : 'dock_loading';
                        const camera_id = camSelect ? camSelect.value : 'CAM-001';

                        const payload = {
                            camera_id: camera_id,
                            scenario: scenario
                        };

                        if (scenario === 'upload' && upInput && upInput.files.length > 0) {
                            const reader = new FileReader();
                            reader.onload = async function(e) {
                                payload.source_type = 'upload';
                                payload.image_base64 = e.target.result;
                                await executeEventTestPost(payload, btn);
                            };
                            reader.readAsDataURL(upInput.files[0]);
                            return;
                        } else if (scenario === 'camera') {
                            payload.source_type = 'camera';
                        } else if (scenario === 'sample_scene') {
                            payload.source_type = 'sample';
                            payload.sample_scene = 'association_box_bin_dock1.jpg';
                        }

                        await executeEventTestPost(payload, btn);
                    }

                    async function executeEventTestPost(payload, btn) {
                        try {
                            const res = await fetch('/api/vision/events/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });
                            const data = await res.json();
                            renderMovementEventsResults(data);
                        } catch (e) {
                            console.error("Event test execution error:", e);
                            alert("Failed to execute movement event test: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = `<span>▶</span> Run Test Frame`;
                            }
                        }
                    }

                    async function runMovementEventsSequence() {
                        const btn = document.getElementById('btnRunEventSeq');
                        const camSelect = document.getElementById('evtCameraSelect');
                        const srcSelect = document.getElementById('evtSourceSelect');
                        const camera_id = camSelect ? camSelect.value : 'CAM-001';
                        const seqName = (srcSelect && srcSelect.value === 'dock_loading') ? 'dock_loading' : 'automotive_warehouse_flow';

                        if (btn) {
                            btn.disabled = true;
                            btn.innerHTML = `<span>⏳</span> Running ${seqName === 'dock_loading' ? '8' : '18'} Frames...`;
                        }

                        try {
                            const res = await fetch('/api/vision/events/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    camera_id: camera_id,
                                    sequence_name: seqName
                                })
                            });
                            const data = await res.json();
                            renderMovementEventsSequenceResults(data);
                        } catch (e) {
                            console.error("Sequence error:", e);
                            alert("Failed to run sequence: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = `<span>⏩</span> Run Sequence`;
                            }
                        }
                    }

                    async function resetMovementEventsSession() {
                        const btn = document.getElementById('btnResetEventSession');
                        const camSelect = document.getElementById('evtCameraSelect');
                        const camera_id = camSelect ? camSelect.value : 'CAM-001';

                        if (btn) btn.disabled = true;
                        try {
                            await fetch('/api/vision/events/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: camera_id })
                            });
                            globalMovementEventsCache = [];
                            // Reset KPI displays
                            document.getElementById('kpi-evt-active').innerText = '0';
                            document.getElementById('kpi-evt-candidate').innerText = '0';
                            document.getElementById('kpi-evt-completed').innerText = '0';
                            document.getElementById('kpi-evt-expired').innerText = '0';
                            document.getElementById('kpi-evt-cancelled').innerText = '0';
                            document.getElementById('kpi-evt-total').innerText = '0';
                            document.getElementById('kpi-evt-ms').innerText = '-';
                            document.getElementById('kpi-evt-total-ms').innerText = 'Total: - ms';

                            const tbody = document.getElementById('evtResultsTbody');
                            if (tbody) {
                                tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:2rem; color:var(--text-muted);">Session reset. No active movement events.</td></tr>`;
                            }
                            const img = document.getElementById('evtAnnotatedImage');
                            const ph = document.getElementById('evtImagePlaceholder');
                            if (img) img.style.display = 'none';
                            if (ph) ph.style.display = 'block';
                            const badge = document.getElementById('evtCountBadge');
                            if (badge) badge.innerText = '0 Events';
                        } catch (e) {
                            console.error("Reset error:", e);
                        } finally {
                            if (btn) btn.disabled = false;
                        }
                    }

                    function renderMovementEventsResults(data) {
                        const events = data.events || data.active_events || (data.result && data.result.active_events) || [];
                        const current = data.current_frame_events || (data.result && data.result.current_events) || [];
                        const allEvents = (data.result && data.result.all_events) || events;

                        globalMovementEventsCache = allEvents.length > 0 ? allEvents : events;

                        // Update KPIs
                        const activeCount = allEvents.filter(e => e.status === 'ACTIVE').length;
                        const candCount = allEvents.filter(e => e.status === 'CANDIDATE').length;
                        const compCount = allEvents.filter(e => e.status === 'COMPLETED').length;
                        const expCount = allEvents.filter(e => e.status === 'EXPIRED').length;
                        const canCount = allEvents.filter(e => e.status === 'CANCELLED').length;
                        const totalCount = (data.result && data.result.total_events_generated) || allEvents.length;

                        document.getElementById('kpi-evt-active').innerText = activeCount;
                        document.getElementById('kpi-evt-candidate').innerText = candCount;
                        document.getElementById('kpi-evt-completed').innerText = compCount;
                        document.getElementById('kpi-evt-expired').innerText = expCount;
                        document.getElementById('kpi-evt-cancelled').innerText = canCount;
                        document.getElementById('kpi-evt-total').innerText = totalCount;

                        const latency = data.latency_ms || (data.performance && data.performance.event_ms) || (data.result && data.result.event_latency_ms) || 1.5;
                        const totalLat = (data.performance && data.performance.total_ms) || latency;
                        document.getElementById('kpi-evt-ms').innerText = latency.toFixed(2) + ' ms';
                        document.getElementById('kpi-evt-total-ms').innerText = `Total: ${totalLat.toFixed(2)} ms`;

                        const badge = document.getElementById('evtCountBadge');
                        if (badge) badge.innerText = `${allEvents.length} Events`;

                        // Render image
                        const img = document.getElementById('evtAnnotatedImage');
                        const ph = document.getElementById('evtImagePlaceholder');
                        const metaBadge = document.getElementById('evtImageMetaBadge');

                        if (data.annotated_frame) {
                            if (img) {
                                img.src = data.annotated_frame;
                                img.style.display = 'block';
                            }
                            if (ph) ph.style.display = 'none';
                            if (metaBadge) metaBadge.innerText = `Camera ${data.camera_id || 'CAM-001'} | Frame #${data.frame_index || 1}`;
                        } else {
                            // If synthetic test without direct image, refresh from camera preview endpoint
                            if (img) {
                                img.src = `/api/vision/events/cameras/${data.camera_id || 'CAM-001'}/annotated.jpg?t=${Date.now()}`;
                                img.style.display = 'block';
                                img.onerror = function() {
                                    img.style.display = 'none';
                                    if (ph) ph.style.display = 'block';
                                };
                            }
                            if (ph) ph.style.display = 'none';
                            if (metaBadge) metaBadge.innerText = `Session: ${data.camera_id || 'CAM-001'}`;
                        }

                        // Populate Table
                        const tbody = document.getElementById('evtResultsTbody');
                        if (!tbody) return;

                        if (allEvents.length === 0) {
                            tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:2rem; color:var(--text-muted);">No movement events active in this frame.</td></tr>`;
                            return;
                        }

                        tbody.innerHTML = allEvents.map(ev => {
                            const statusColor = ev.status === 'ACTIVE' ? '#10b981' :
                                                ev.status === 'CANDIDATE' ? '#f59e0b' :
                                                ev.status === 'COMPLETED' ? '#6366f1' :
                                                ev.status === 'EXPIRED' ? '#94a3b8' : '#ef4444';

                            const levelColor = ev.event_level === 'VALIDATED_REAL_WORLD' ? '#10b981' : '#38bdf8';
                            const levelLabel = ev.event_level === 'VALIDATED_REAL_WORLD' ? 'REAL-WORLD' : 'TRACK-LEVEL';

                            const p = ev.primary_object || {};
                            const s = ev.secondary_object || {};
                            const z = ev.zone || {};

                            const pText = `<strong>${escapeHtml(p.class_code || 'OBJ')} #${p.track_id}</strong>` +
                                          (p.identity_id ? ` <br><span style="font-family:monospace; color:var(--accent); font-size:0.72rem;">[${escapeHtml(p.identity_id)}]</span>` : '');

                            const sText = s.track_id ? `<strong>${escapeHtml(s.class_code || 'OBJ')} #${s.track_id}</strong>` +
                                          (s.identity_id ? ` <br><span style="font-family:monospace; color:var(--accent); font-size:0.72rem;">[${escapeHtml(s.identity_id)}]</span>` : '') : '<span style="color:var(--text-muted);">-</span>';

                            const zText = z.zone_code ? `<span class="badge" style="font-size:0.70rem; background:rgba(37,99,235,0.12); color:var(--accent);">${escapeHtml(z.zone_code)}</span>` : '<span style="color:var(--text-muted);">-</span>';

                            return `
                                <tr>
                                    <td style="font-family:monospace; font-weight:800; color:var(--accent);">${escapeHtml(ev.event_id)}</td>
                                    <td><strong style="font-size:0.76rem;">${escapeHtml(ev.event_type)}</strong></td>
                                    <td>
                                        <span class="badge" style="background:${statusColor}; color:#fff; font-size:0.68rem; padding:2px 6px;">
                                            ${escapeHtml(ev.status)}
                                        </span>
                                    </td>
                                    <td>${pText}</td>
                                    <td>${sText}</td>
                                    <td>${zText}</td>
                                    <td>
                                        <span class="badge" style="background:rgba(255,255,255,0.06); border:1px solid ${levelColor}; color:${levelColor}; font-size:0.65rem; padding:2px 5px;">
                                            ${levelLabel}
                                        </span>
                                    </td>
                                    <td style="font-family:monospace; font-weight:700;">${ev.confidence != null ? ev.confidence.toFixed(2) : '-'}</td>
                                    <td>
                                        <button type="button" class="btn-secondary" onclick="showMovementEventEvidence('${escapeHtml(ev.event_id)}')" style="padding:2px 8px; font-size:0.70rem;" title="View Explainable Evidence">
                                            🔍 Evidence
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    function renderMovementEventsSequenceResults(seqData) {
                        const history = seqData.frame_results || [];
                        const summary = seqData.summary || {};
                        const finalActive = summary.final_active_events || [];

                        // Collect all generated events across all 8 frames
                        const allEvents = [];
                        history.forEach(fr => {
                            (fr.current_events || []).forEach(e => {
                                if (!allEvents.some(x => x.event_id === e.event_id)) {
                                    allEvents.push(e);
                                }
                            });
                        });

                        globalMovementEventsCache = allEvents.length > 0 ? allEvents : finalActive;

                        document.getElementById('kpi-evt-active').innerText = finalActive.length;
                        document.getElementById('kpi-evt-completed').innerText = allEvents.filter(e => e.status === 'COMPLETED').length;
                        document.getElementById('kpi-evt-total').innerText = summary.total_events_generated || allEvents.length;
                        document.getElementById('kpi-evt-ms').innerText = '< 2.0 ms';
                        document.getElementById('kpi-evt-total-ms').innerText = '8 Frames Completed';

                        const badge = document.getElementById('evtCountBadge');
                        if (badge) badge.innerText = `${allEvents.length} Events Across Sequence`;

                        // Render table with sequence events
                        const tbody = document.getElementById('evtResultsTbody');
                        if (tbody && allEvents.length > 0) {
                            tbody.innerHTML = allEvents.map(ev => {
                                const statusColor = ev.status === 'ACTIVE' ? '#10b981' :
                                                    ev.status === 'CANDIDATE' ? '#f59e0b' :
                                                    ev.status === 'COMPLETED' ? '#6366f1' :
                                                    ev.status === 'EXPIRED' ? '#94a3b8' : '#ef4444';

                                const levelColor = ev.event_level === 'VALIDATED_REAL_WORLD' ? '#10b981' : '#38bdf8';
                                const p = ev.primary_object || {};
                                const s = ev.secondary_object || {};
                                const z = ev.zone || {};

                                const pText = `<strong>${escapeHtml(p.class_code || 'OBJ')} #${p.track_id}</strong>` +
                                              (p.identity_id ? ` <br><span style="font-family:monospace; color:var(--accent); font-size:0.72rem;">[${escapeHtml(p.identity_id)}]</span>` : '');

                                const sText = s.track_id ? `<strong>${escapeHtml(s.class_code || 'OBJ')} #${s.track_id}</strong>` +
                                              (s.identity_id ? ` <br><span style="font-family:monospace; color:var(--accent); font-size:0.72rem;">[${escapeHtml(s.identity_id)}]</span>` : '') : '<span style="color:var(--text-muted);">-</span>';

                                const zText = z.zone_code ? `<span class="badge" style="font-size:0.70rem; background:rgba(37,99,235,0.12); color:var(--accent);">${escapeHtml(z.zone_code)}</span>` : '<span style="color:var(--text-muted);">-</span>';

                                return `
                                    <tr>
                                        <td style="font-family:monospace; font-weight:800; color:var(--accent);">${escapeHtml(ev.event_id)}</td>
                                        <td><strong style="font-size:0.76rem;">${escapeHtml(ev.event_type)}</strong></td>
                                        <td><span class="badge" style="background:${statusColor}; color:#fff; font-size:0.68rem; padding:2px 6px;">${escapeHtml(ev.status)}</span></td>
                                        <td>${pText}</td>
                                        <td>${sText}</td>
                                        <td>${zText}</td>
                                        <td><span class="badge" style="background:rgba(255,255,255,0.06); border:1px solid ${levelColor}; color:${levelColor}; font-size:0.65rem; padding:2px 5px;">${ev.event_level === 'VALIDATED_REAL_WORLD' ? 'REAL-WORLD' : 'TRACK-LEVEL'}</span></td>
                                        <td style="font-family:monospace; font-weight:700;">${ev.confidence != null ? ev.confidence.toFixed(2) : '-'}</td>
                                        <td>
                                            <button type="button" class="btn-secondary" onclick="showMovementEventEvidence('${escapeHtml(ev.event_id)}')" style="padding:2px 8px; font-size:0.70rem;">
                                                🔍 Evidence
                                            </button>
                                        </td>
                                    </tr>
                                `;
                            }).join('');
                        }

                        // Update image
                        const img = document.getElementById('evtAnnotatedImage');
                        const ph = document.getElementById('evtImagePlaceholder');
                        const metaBadge = document.getElementById('evtImageMetaBadge');
                        if (img) {
                            img.src = `/api/vision/events/cameras/${seqData.camera_id || 'CAM-001'}/annotated.jpg?t=${Date.now()}`;
                            img.style.display = 'block';
                            img.onerror = function() {
                                img.style.display = 'none';
                                if (ph) ph.style.display = 'block';
                            };
                        }
                        if (ph) ph.style.display = 'none';
                        if (metaBadge) metaBadge.innerText = `8-Frame Sequence Completed | ${allEvents.length} Events`;
                    }

                    function showMovementEventEvidence(eventId) {
                        const ev = globalMovementEventsCache.find(e => e.event_id === eventId);
                        if (!ev) {
                            alert("Event evidence not found in cache.");
                            return;
                        }

                        const modal = document.getElementById('evtEvidenceModal');
                        const title = document.getElementById('modalEvtTitle');
                        const content = document.getElementById('modalEvtContent');

                        if (title) title.innerText = `Evidence Breakdown: ${ev.event_id} (${ev.event_type})`;

                        const evidenceEntries = Object.entries(ev.evidence || {});
                        const evidenceRows = evidenceEntries.map(([k, v]) => `
                            <tr>
                                <td style="font-weight:700; color:var(--text-muted); padding:6px 0; text-transform:capitalize;">${escapeHtml(k.replace(/_/g, ' '))}:</td>
                                <td style="font-family:monospace; color:var(--text-main); font-weight:600;">${escapeHtml(JSON.stringify(v))}</td>
                            </tr>
                        `).join('');

                        if (content) {
                            content.innerHTML = `
                                <div style="display:flex; justify-content:space-between; align-items:center; background:var(--panel-subtle); padding:10px 14px; border-radius:8px; margin-bottom:12px;">
                                    <div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Event Status</div>
                                        <strong style="font-size:1.05rem; color:var(--accent);">${escapeHtml(ev.status)}</strong>
                                    </div>
                                    <div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Event Level</div>
                                        <strong style="font-size:0.95rem; color:${ev.event_level === 'VALIDATED_REAL_WORLD' ? '#10b981' : '#38bdf8'};">${escapeHtml(ev.event_level)}</strong>
                                    </div>
                                    <div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Score / Confidence</div>
                                        <strong style="font-size:1.05rem; font-family:monospace;">${ev.confidence != null ? ev.confidence.toFixed(4) : '-'}</strong>
                                    </div>
                                </div>

                                <h4 style="margin:12px 0 6px 0; font-size:0.88rem; color:var(--primary-navy);">Explainable Evidence Factors</h4>
                                <table style="width:100%; font-size:0.82rem; margin-bottom:14px;">
                                    <tbody>
                                        ${evidenceRows}
                                    </tbody>
                                </table>

                                <details style="background:var(--panel-subtle); padding:8px 12px; border-radius:6px; font-size:0.75rem; cursor:pointer;">
                                    <summary style="font-weight:700; color:var(--text-muted);">Raw Event Object JSON</summary>
                                    <pre style="margin:8px 0 0 0; font-family:monospace; color:var(--text-main); font-size:0.72rem; overflow-x:auto;">${escapeHtml(JSON.stringify(ev, null, 2))}</pre>
                                </details>
                            `;
                        }

                        if (modal) modal.style.display = 'flex';
                    }

                    function closeMovementEventEvidenceModal() {
                        const modal = document.getElementById('evtEvidenceModal');
                        if (modal) modal.style.display = 'none';
                    }

                    async function queryMovementEventTimeline(matId) {
                        const targetId = matId || prompt("Enter physical Material/SKU ID to query cross-camera movement timeline (e.g. ROD-STEEL-4140-A, B104, GLS-WND-88):", "ROD-STEEL-4140-A");
                        if (!targetId) return;

                        try {
                            const res = await fetch(`/api/vision/events/timeline/${encodeURIComponent(targetId)}?include_candidates=true`);
                            const data = await res.json();
                            if (!data.success) {
                                alert("Failed to fetch timeline: " + (data.message || "Unknown error"));
                                return;
                            }

                            const modal = document.getElementById('evtEvidenceModal');
                            const title = document.getElementById('modalEvtTitle');
                            const content = document.getElementById('modalEvtContent');

                            if (title) title.innerText = `Cross-Camera Physical Timeline: ${targetId}`;
                            if (content) {
                                const eventsHtml = (data.timeline || []).map(ev => `
                                    <div style="background:var(--panel-subtle); border-left:3px solid var(--accent); padding:10px 12px; margin-bottom:10px; border-radius:4px;">
                                        <div style="display:flex; justify-content:space-between; align-items:center;">
                                            <strong style="color:var(--primary-navy); font-size:0.85rem;">${escapeHtml(ev.event_type)}</strong>
                                            <span class="badge" style="background:#10b981; color:#fff; font-size:0.68rem;">${escapeHtml(ev.status)}</span>
                                        </div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">
                                            Camera: <strong>${escapeHtml(ev.camera_id)}</strong> | Stage: <strong>${escapeHtml(ev.stage || 'N/A')}</strong> | Zone: <strong>${escapeHtml(ev.zone ? ev.zone.zone_code : 'N/A')}</strong> | Frame: #${ev.metrics ? ev.metrics.created_frame : 1}
                                        </div>
                                        <div style="font-size:0.72rem; color:var(--text-main); margin-top:4px; font-family:monospace;">
                                            Evidence: ${escapeHtml(JSON.stringify(ev.evidence || {}))}
                                        </div>
                                    </div>
                                `).join('');

                                const conflictsHtml = (data.conflicting_events_isolated || []).length > 0 ? `
                                    <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); padding:8px 12px; border-radius:6px; margin-bottom:12px;">
                                        <strong style="color:#ef4444; font-size:0.8rem;">⚠️ Quarantined Conflicting / Ambiguous Observations (${data.conflicting_events_isolated.length})</strong>
                                        <p style="font-size:0.75rem; color:var(--text-muted); margin:4px 0 0 0;">Isolated from physical timeline to prevent false movement history.</p>
                                    </div>
                                ` : '';

                                content.innerHTML = `
                                    <div style="margin-bottom:12px; font-size:0.82rem; color:var(--text-muted);">
                                        Method: <strong>${escapeHtml(data.cross_camera_continuity_method)}</strong> (Zero Visual Re-ID) | Visited Cameras: <strong>${escapeHtml((data.observed_cameras || []).join(', ') || 'None')}</strong>
                                    </div>
                                    ${conflictsHtml}
                                    <div style="max-height:360px; overflow-y:auto;">
                                        ${eventsHtml || '<p style="color:var(--text-muted); text-align:center; padding:1.5rem;">No timeline records found for this physical identity.</p>'}
                                    </div>
                                `;
                            }

                            if (modal) modal.style.display = 'flex';
                        } catch (e) {
                            console.error("Timeline query error:", e);
                            alert("Failed to query material timeline: " + e.message);
                        }
                    }

                    window.queryMovementEventTimeline = queryMovementEventTimeline;
                    window.closeMovementEventEvidenceModal = closeMovementEventEvidenceModal;
                    window.runMovementEventsSequence = runMovementEventsSequence;
                    window.runMovementEventsTest = runMovementEventsTest;
                    window.resetMovementEventsSession = resetMovementEventsSession;
                    window.showMovementEventEvidence = showMovementEventEvidence;

                    // ==========================================
                    // PART 13: MATERIAL TRACEABILITY JAVASCRIPT
                    // ==========================================
                    let globalTraceabilityCache = {
                        materials: {},
                        currentMaterialId: "B104",
                        timeline: []
                    };

                    async function initMaterialTraceabilityUI() {
                        try {
                            const res = await fetch('/api/vision/traceability/status');
                            if (res.ok) {
                                const status = await res.json();
                                updateTraceabilityKPIs(status);
                            }
                            await refreshTraceabilityMaterialsList();
                        } catch (e) {
                            console.warn("Could not load traceability status:", e);
                        }
                    }

                    function updateTraceabilityKPIs(status) {
                        if (!status) return;
                        const kpiTotal = document.getElementById('trcKpiTotalMaterials');
                        const kpiVal = document.getElementById('trcKpiValidated');
                        const kpiTransit = document.getElementById('trcKpiInTransit');
                        const kpiEvents = document.getElementById('trcKpiTotalEvents');

                        if (kpiTotal) kpiTotal.innerText = status.total_materials_tracked || 0;
                        if (kpiVal) kpiVal.innerText = status.validated_materials || 0;
                        if (kpiTransit) kpiTransit.innerText = status.in_transit_materials || 0;
                        if (kpiEvents) kpiEvents.innerText = status.total_timeline_events || 0;
                    }

                    async function refreshTraceabilityMaterialsList() {
                        try {
                            const res = await fetch('/api/vision/traceability/materials');
                            if (res.ok) {
                                const data = await res.json();
                                const materials = data.materials || [];
                                const sel = document.getElementById('trcMaterialSelect');
                                if (sel) {
                                    let html = '<option value="">-- All Materials --</option>';
                                    materials.forEach(m => {
                                        const isSel = (m.material_id === globalTraceabilityCache.currentMaterialId) ? 'selected' : '';
                                        html += `<option value="${escapeHtml(m.material_id)}" ${isSel}>${escapeHtml(m.material_id)} (${escapeHtml(m.material_class || 'BOX')} - ${escapeHtml(m.traceability_status || 'ACTIVE')})</option>`;
                                    });
                                    if (!materials.some(m => m.material_id === "B104")) {
                                        html += `<option value="B104" ${globalTraceabilityCache.currentMaterialId === 'B104' ? 'selected' : ''}>B104 (Default Box SKU VLV-900)</option>`;
                                    }
                                    sel.innerHTML = html;
                                }

                                if (globalTraceabilityCache.currentMaterialId) {
                                    await loadTraceabilityMaterialDossier(globalTraceabilityCache.currentMaterialId);
                                }
                            }
                        } catch (e) {
                            console.warn("Could not refresh traceability materials list:", e);
                        }
                    }

                    async function handleTraceabilityMaterialSelect(materialId) {
                        if (!materialId) {
                            materialId = "B104";
                        }
                        globalTraceabilityCache.currentMaterialId = materialId;
                        await loadTraceabilityMaterialDossier(materialId);
                    }

                    async function loadTraceabilityMaterialDossier(materialId) {
                        try {
                            // Try enriched Part 14 integration endpoint first
                            let res = await fetch(`/api/integration/material/${encodeURIComponent(materialId)}`);
                            let mat = null;
                            if (res.ok) {
                                const intData = await res.json();
                                mat = intData.data;
                            } else {
                                // Fallback to raw traceability endpoint
                                res = await fetch(`/api/vision/traceability/materials/${encodeURIComponent(materialId)}`);
                                if (res.ok) {
                                    const data = await res.json();
                                    mat = data.material;
                                }
                            }
                            if (mat) {
                                globalTraceabilityCache.materials[materialId] = mat;
                                renderMaterialTraceDossier(mat);
                            } else {
                                clearMaterialTraceDossier(materialId);
                            }
                        } catch (e) {
                            console.warn("Error loading material dossier:", e);
                        }
                    }

                    function clearMaterialTraceDossier(materialId) {
                        const title = document.getElementById('trcDossierTitle');
                        if (title) title.innerText = materialId || 'None';
                        const src = document.getElementById('trcDossierSource');
                        if (src) src.innerText = '--';
                        const dest = document.getElementById('trcDossierDestination');
                        if (dest) dest.innerText = '--';
                        const loc = document.getElementById('trcDossierLocation');
                        if (loc) loc.innerText = '--';
                        const workers = document.getElementById('trcDossierWorkers');
                        if (workers) workers.innerText = '--';
                        const zones = document.getElementById('trcDossierZoneHistory');
                        if (zones) zones.innerHTML = '<span style="color:var(--text-muted);">No zone movements recorded.</span>';
                        const cams = document.getElementById('trcDossierCameras');
                        if (cams) cams.innerHTML = '<span style="color:var(--text-muted);">No camera observations logged.</span>';
                        const tbody = document.getElementById('trcTimelineTbody');
                        if (tbody) {
                            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">No traceability events recorded yet.</td></tr>';
                        }
                        const badge = document.getElementById('trcTimelineCountBadge');
                        if (badge) badge.innerText = '0 Events';
                    }

                    function renderMaterialTraceDossier(mat) {
                        if (!mat) return;
                        if (!mat.wms_references && mat.material_id) {
                            loadTraceabilityMaterialDossier(mat.material_id);
                            return;
                        }
                        const title = document.getElementById('trcDossierTitle');
                        const levelBadge = document.getElementById('trcDossierLevelBadge');
                        const statusBadge = document.getElementById('trcDossierStatusBadge');
                        const src = document.getElementById('trcDossierSource');
                        const srcNote = document.getElementById('trcDossierSourceNote');
                        const dest = document.getElementById('trcDossierDestination');
                        const destNote = document.getElementById('trcDossierDestNote');
                        const loc = document.getElementById('trcDossierLocation');
                        const workers = document.getElementById('trcDossierWorkers');
                        const zones = document.getElementById('trcDossierZoneHistory');
                        const cams = document.getElementById('trcDossierCameras');

                        if (title) {
                            let titleHtml = escapeHtml(mat.material_id || 'Unknown');
                            if (mat.sku_id) {
                                titleHtml += ` <span style="font-size:0.8rem; font-weight:normal; color:#10b981;">[SKU: ${escapeHtml(mat.sku_id)}]</span>`;
                            }
                            if (mat.physical_identifier) {
                                titleHtml += ` <span style="font-size:0.75rem; font-weight:normal; color:#8b5cf6;">(${escapeHtml(mat.physical_identity_type || 'ID')}: ${escapeHtml(mat.physical_identifier)})</span>`;
                            }
                            if (mat.container_id) {
                                titleHtml += ` <span style="font-size:0.75rem; font-weight:normal; color:#f59e0b;">📦 Cont: ${escapeHtml(mat.container_id)}</span>`;
                            }
                            if (mat.has_conflicts || (mat.conflicts && mat.conflicts.length > 0)) {
                                titleHtml += ` <span style="font-size:0.75rem; background:rgba(239,68,68,0.2); color:#ef4444; border:1px solid #ef4444; padding:2px 6px; border-radius:4px;">⚠️ CONFLICT</span>`;
                            }
                            title.innerHTML = titleHtml;
                        }
                        if (levelBadge) {
                            levelBadge.innerText = mat.traceability_level || 'TRACK_LEVEL';
                            levelBadge.style.background = mat.traceability_level === 'VALIDATED_REAL_WORLD' ? '#10b981' : (mat.traceability_level === 'IDENTIFIED' ? '#3b82f6' : '#64748b');
                        }
                        if (statusBadge) {
                            statusBadge.innerText = mat.traceability_status || 'ACTIVE';
                        }

                        // Source Origin
                        if (src) {
                            if (mat.source && mat.source.identity_id) {
                                src.innerHTML = `<span style="color:#3b82f6;">🚚 Truck ${escapeHtml(mat.source.identity_id)}</span>`;
                                if (srcNote) srcNote.innerText = `Observed Associated (Score: ${mat.source.score != null ? mat.source.score.toFixed(2) : '1.0'})`;
                            } else if (mat.source && mat.source.track_id) {
                                src.innerHTML = `<span style="color:#64748b;">Truck Track #${mat.source.track_id} (Unidentified)</span>`;
                            } else {
                                src.innerHTML = '<span style="color:var(--text-muted);">Unknown / None</span>';
                            }
                        }

                        // Destination Target
                        if (dest) {
                            if (mat.destination && mat.destination.identity_id) {
                                dest.innerHTML = `<span style="color:#10b981;">🏷️ Bin ${escapeHtml(mat.destination.identity_id)}</span>`;
                                if (destNote) destNote.innerText = `Observed Associated (Score: ${mat.destination.score != null ? mat.destination.score.toFixed(2) : '1.0'})`;
                            } else if (mat.destination && mat.destination.track_id) {
                                dest.innerHTML = `<span style="color:#64748b;">Bin Track #${mat.destination.track_id} (Unidentified)</span>`;
                            } else {
                                dest.innerHTML = '<span style="color:var(--text-muted);">Unknown / In-Transit</span>';
                            }
                        }

                        // Current Location & Last Verified Location
                        if (loc) {
                            let locHtml = '';
                            if (mat.current_location && mat.current_location.zone_code) {
                                locHtml += `📍 <strong>${escapeHtml(mat.current_location.zone_code)}</strong> <span style="font-size:0.75rem; color:var(--text-muted);">(${escapeHtml(mat.current_location.camera_id || 'CAM-001')})</span>`;
                            } else {
                                locHtml += '<span style="color:var(--text-muted);">Outside / Unknown Zone</span>';
                            }
                            if (mat.last_verified_location && mat.last_verified_location.zone_code) {
                                locHtml += `<br><span style="font-size:0.72rem; color:#10b981;">Verified: ${escapeHtml(mat.last_verified_location.zone_code)} (${escapeHtml(mat.last_verified_location.verification_method || 'CONFIRMED')})</span>`;
                            }
                            loc.innerHTML = locHtml;
                        }

                        // Associated Workers
                        if (workers) {
                            if (mat.associated_workers && mat.associated_workers.length > 0) {
                                const wList = mat.associated_workers.map(w => {
                                    const id = w.identity_id ? `Worker ${w.identity_id}` : `Track #${w.track_id}`;
                                    return `<span class="badge" style="background:rgba(245,158,11,0.15); color:#f59e0b; font-size:0.75rem; padding:2px 8px;">👷 ${escapeHtml(id)}</span>`;
                                }).join(' ');
                                workers.innerHTML = wList;
                            } else {
                                workers.innerHTML = '<span style="color:var(--text-muted);">None observed</span>';
                            }
                        }

                        // Zone Traversal History Chips
                        if (zones) {
                            if (mat.zone_history && mat.zone_history.length > 0) {
                                zones.innerHTML = mat.zone_history.map(zh => {
                                    const isEnter = zh.transition === 'ENTER';
                                    const color = isEnter ? '#10b981' : '#f59e0b';
                                    return `<span style="background:rgba(255,255,255,0.06); border:1px solid ${color}; color:${color}; padding:2px 7px; border-radius:4px; font-size:0.72rem; display:inline-flex; align-items:center; gap:4px;">
                                        <strong>${isEnter ? '📥 IN' : '📤 OUT'}:</strong> ${escapeHtml(zh.zone_code)}
                                    </span>`;
                                }).join(' ');
                            } else {
                                zones.innerHTML = '<span style="color:var(--text-muted);">No zone movements recorded.</span>';
                            }
                        }

                        // Camera Sightings Chips
                        if (cams) {
                            if (mat.camera_observations && mat.camera_observations.length > 0) {
                                const camCounts = {};
                                mat.camera_observations.forEach(co => {
                                    camCounts[co.camera_id] = (camCounts[co.camera_id] || 0) + 1;
                                });
                                cams.innerHTML = Object.entries(camCounts).map(([cam, cnt]) => `
                                    <span style="background:rgba(139,92,246,0.15); border:1px solid #8b5cf6; color:#8b5cf6; padding:2px 8px; border-radius:4px; font-size:0.72rem;">
                                        📹 ${escapeHtml(cam)} (${cnt} sightings)
                                    </span>
                                `).join(' ');
                            } else {
                                cams.innerHTML = '<span style="color:var(--text-muted);">No camera observations logged.</span>';
                            }
                        }

                        // WMS Master References (Part 14 Integration)
                        const wmsSection = document.getElementById('trcDossierWmsSection');
                        const wmsDelivery = document.getElementById('trcWmsDelivery');
                        const wmsGatePass = document.getElementById('trcWmsGatePass');
                        const wmsSku = document.getElementById('trcWmsSku');
                        const wmsPutaway = document.getElementById('trcWmsPutaway');
                        const deepLinksContainer = document.getElementById('trcDossierDeepLinks');

                        if (wmsSection) {
                            const refs = mat.wms_references || {};
                            if (wmsDelivery) {
                                if (refs.delivery && refs.delivery.po_number) {
                                    wmsDelivery.innerHTML = `<span style="color:var(--accent-hover); font-weight:700;">PO ${escapeHtml(refs.delivery.po_number)}</span> <span style="font-size:0.7rem; color:var(--text-muted);">(${escapeHtml(refs.delivery.vendor || 'Vendor')})</span>`;
                                } else {
                                    wmsDelivery.innerHTML = '<span style="color:var(--text-muted);">NOT_AVAILABLE</span>';
                                }
                            }
                            if (wmsGatePass) {
                                if (refs.gate_pass && refs.gate_pass.id) {
                                    wmsGatePass.innerHTML = `<span style="color:#2563eb; font-weight:700;">Pass ${escapeHtml(refs.gate_pass.id)}</span> <span style="font-size:0.7rem; color:var(--text-muted);">[${escapeHtml(refs.truck_plate || refs.gate_pass.plate)}]</span>`;
                                } else {
                                    wmsGatePass.innerHTML = '<span style="color:var(--text-muted);">NOT_AVAILABLE</span>';
                                }
                            }
                            if (wmsSku) {
                                if (refs.sku && refs.sku.name) {
                                    wmsSku.innerHTML = `<span style="color:#10b981; font-weight:700;">${escapeHtml(refs.sku.name)}</span>`;
                                } else {
                                    wmsSku.innerHTML = '<span style="color:var(--text-muted);">UNREGISTERED / NOT_AVAILABLE</span>';
                                }
                            }
                            if (wmsPutaway) {
                                const pStatus = refs.putaway_evidence?.status || 'UNVERIFIED';
                                const pColor = (pStatus === 'OBSERVED_AT_BIN') ? '#10b981' : '#f59e0b';
                                const binLabel = refs.bin?.bin_id ? ` (${escapeHtml(refs.bin.bin_id)})` : '';
                                wmsPutaway.innerHTML = `<span class="badge" style="background:${pColor}20; color:${pColor}; font-size:0.7rem; padding:2px 8px;">${pStatus}${binLabel}</span>`;
                            }

                            if (deepLinksContainer) {
                                let buttons = '';
                                if (refs.delivery?.po_number) {
                                    buttons += `<button type="button" class="btn-primary" style="font-size:0.7rem; padding:3px 8px; background:#3b82f6;" onclick="navigateToEntity('delivery', '${escapeHtml(refs.delivery.po_number)}')">📦 Go to PO</button>`;
                                }
                                if (refs.gate_pass?.id) {
                                    buttons += `<button type="button" class="btn-primary" style="font-size:0.7rem; padding:3px 8px; background:#10b981;" onclick="navigateToEntity('gate_pass', '${escapeHtml(refs.gate_pass.id)}')">🎫 Go to Pass</button>`;
                                }
                                if (refs.gate_pass?.dock && refs.gate_pass.dock !== 'Not Assigned') {
                                    buttons += `<button type="button" class="btn-primary" style="font-size:0.7rem; padding:3px 8px; background:#f59e0b;" onclick="navigateToEntity('dock', '${escapeHtml(refs.gate_pass.dock)}')">⚓ Go to Dock</button>`;
                                }
                                if (refs.bin?.bin_id) {
                                    buttons += `<button type="button" class="btn-primary" style="font-size:0.7rem; padding:3px 8px; background:#8b5cf6;" onclick="navigateToEntity('bin', '${escapeHtml(refs.bin.bin_id)}')">🏷️ Go to Bin ${escapeHtml(refs.bin.bin_id)}</button>`;
                                }
                                deepLinksContainer.innerHTML = buttons;
                            }
                        }

                        // Update Observation Flow Graph (Section 36)
                        const gSrc = document.getElementById('graphTextSource');
                        const gMat = document.getElementById('graphTextMaterial');
                        const gWrk = document.getElementById('graphTextWorker');
                        const gDst = document.getElementById('graphTextDest');

                        if (gSrc) gSrc.innerText = (mat.source && mat.source.identity_id) ? `Truck ${mat.source.identity_id}` : 'None';
                        if (gMat) gMat.innerText = mat.material_id || 'B104';
                        if (gWrk) {
                            if (mat.associated_workers && mat.associated_workers.length > 0) {
                                gWrk.innerText = `Worker ${mat.associated_workers[0].identity_id || mat.associated_workers[0].track_id}`;
                            } else if (mat.current_location && mat.current_location.zone_code) {
                                gWrk.innerText = `Zone ${mat.current_location.zone_code}`;
                            } else {
                                gWrk.innerText = 'In-Transit';
                            }
                        }
                        if (gDst) gDst.innerText = (mat.destination && mat.destination.identity_id) ? `Bin ${mat.destination.identity_id}` : 'None';

                        // Render Timeline Ledger
                        renderTraceTimelineTable(mat.timeline || []);
                    }

                    function renderTraceTimelineTable(timeline) {
                        const tbody = document.getElementById('trcTimelineTbody');
                        const countBadge = document.getElementById('trcTimelineCountBadge');
                        if (!tbody) return;

                        globalTraceabilityCache.timeline = timeline || [];
                        if (countBadge) countBadge.innerText = `${(timeline || []).length} Events`;

                        if (!timeline || timeline.length === 0) {
                            tbody.innerHTML = `
                                <tr>
                                    <td colspan="9" style="text-align:center; padding:2rem 1rem; color:var(--text-muted);">
                                        No traceability events recorded for this material.
                                    </td>
                                </tr>
                            `;
                            return;
                        }

                        tbody.innerHTML = timeline.map(entry => {
                            let typeColor = '#8b5cf6';
                            if (entry.event_type.includes('ENTERED')) typeColor = '#10b981';
                            else if (entry.event_type.includes('EXITED')) typeColor = '#f59e0b';
                            else if (entry.event_type.includes('TRUCK')) typeColor = '#3b82f6';
                            else if (entry.event_type.includes('WORKER')) typeColor = '#eab308';
                            else if (entry.event_type.includes('BIN')) typeColor = '#10b981';

                            let relText = '-';
                            if (entry.related_entity) {
                                const relCls = entry.related_entity.class_code || '';
                                const relId = entry.related_entity.identity_id ? ` [${entry.related_entity.identity_id}]` : ` (#${entry.related_entity.track_id})`;
                                relText = `<span style="font-weight:600;">${escapeHtml(relCls)}${escapeHtml(relId)}</span>`;
                            }

                            const zoneText = entry.zone ? `<strong>${escapeHtml(entry.zone.zone_code || '')}</strong>` : '-';
                            const natureBadge = entry.nature === 'VALIDATED'
                                ? '<span class="badge" style="background:#10b981; color:#fff; font-size:0.65rem;">VALIDATED</span>'
                                : '<span class="badge" style="background:rgba(255,255,255,0.08); color:var(--text-main); font-size:0.65rem;">OBSERVED</span>';

                            return `
                                <tr>
                                    <td style="font-family:monospace; font-weight:800; color:#8b5cf6;">${escapeHtml(entry.trace_id)}</td>
                                    <td style="font-size:0.74rem; color:var(--text-muted); font-family:monospace;">${escapeHtml((entry.timestamp || '').slice(11, 19) || entry.timestamp)}</td>
                                    <td style="font-family:monospace; font-weight:700;">${escapeHtml(entry.event_id)}</td>
                                    <td><strong style="color:${typeColor}; font-size:0.76rem;">${escapeHtml(entry.event_type)}</strong></td>
                                    <td>${natureBadge}</td>
                                    <td>${zoneText}</td>
                                    <td>${relText}</td>
                                    <td><span class="badge" style="background:rgba(255,255,255,0.06); font-size:0.65rem;">${escapeHtml(entry.trace_level || 'TRACK_LEVEL')}</span></td>
                                    <td>
                                        <button type="button" class="btn-secondary" onclick="showTraceEvidence('${escapeHtml(entry.trace_id)}')" style="padding:2px 8px; font-size:0.70rem;">
                                            🔍 Evidence
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');
                    }

                    async function runTraceabilityTest() {
                        const btn = document.getElementById('trcRunTestBtn');
                        const scenario = document.getElementById('trcScenarioSelect') ? document.getElementById('trcScenarioSelect').value : 'box_enter_dock';
                        const camera_id = document.getElementById('trcCameraSelect') ? document.getElementById('trcCameraSelect').value : 'CAM-001';

                        if (btn) {
                            btn.disabled = true;
                            btn.innerText = "Processing...";
                        }

                        try {
                            const res = await fetch('/api/vision/traceability/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ scenario: scenario, camera_id: camera_id })
                            });

                            if (res.ok) {
                                const data = await res.json();
                                const kpiLat = document.getElementById('trcKpiLatency');
                                if (kpiLat && data.processing_time_ms != null) {
                                    kpiLat.innerText = `${data.processing_time_ms.toFixed(2)} ms`;
                                }
                                await initMaterialTraceabilityUI();
                                if (data.material_dossier) {
                                    renderMaterialTraceDossier(data.material_dossier);
                                }
                                updateTraceabilityImage(camera_id);
                            }
                        } catch (e) {
                            alert("Traceability test failed: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = "<span>▶ Run Test Frame</span>";
                            }
                        }
                    }

                    async function runTraceabilitySequence() {
                        const btn = document.getElementById('trcRunSeqBtn');
                        if (btn) {
                            btn.disabled = true;
                            btn.innerText = "Executing Sequence...";
                        }

                        try {
                            const res = await fetch('/api/vision/traceability/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ sequence_name: 'complete_trace' })
                            });

                            if (res.ok) {
                                const data = await res.json();
                                const kpiLat = document.getElementById('trcKpiLatency');
                                if (kpiLat && data.processing_time_ms != null) {
                                    kpiLat.innerText = `${data.processing_time_ms.toFixed(2)} ms`;
                                }
                                const kpiDest = document.getElementById('trcKpiDestination');
                                if (kpiDest) kpiDest.innerText = '1';

                                await initMaterialTraceabilityUI();
                                if (data.material_dossier && data.material_dossier.material_id) {
                                    await loadTraceabilityMaterialDossier(data.material_dossier.material_id);
                                } else if (data.material_dossier) {
                                    renderMaterialTraceDossier(data.material_dossier);
                                }
                                updateTraceabilityImage('CAM-001');
                            }
                        } catch (e) {
                            alert("Traceability sequence failed: " + e.message);
                        } finally {
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = "<span>⚡ Run 7-Frame Sequence</span>";
                            }
                        }
                    }

                    async function resetTraceabilitySession() {
                        const btn = document.getElementById('trcResetBtn');
                        if (btn) btn.disabled = true;

                        try {
                            const res = await fetch('/api/vision/traceability/reset', { method: 'POST' });
                            if (res.ok) {
                                globalTraceabilityCache.materials = {};
                                globalTraceabilityCache.timeline = [];
                                clearMaterialTraceDossier(globalTraceabilityCache.currentMaterialId);
                                updateTraceabilityKPIs({
                                    total_materials_tracked: 0,
                                    validated_materials: 0,
                                    in_transit_materials: 0,
                                    total_timeline_events: 0
                                });
                                const kpiDest = document.getElementById('trcKpiDestination');
                                if (kpiDest) kpiDest.innerText = '0';
                                const kpiLat = document.getElementById('trcKpiLatency');
                                if (kpiLat) kpiLat.innerText = '-- ms';

                                const img = document.getElementById('trcAnnotatedImage');
                                const ph = document.getElementById('trcImagePlaceholder');
                                const metaBadge = document.getElementById('trcImageMetaBadge');
                                if (img) img.style.display = 'none';
                                if (ph) ph.style.display = 'block';
                                if (metaBadge) metaBadge.innerText = 'Awaiting Execution';

                                await refreshTraceabilityMaterialsList();
                            }
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        } finally {
                            if (btn) btn.disabled = false;
                        }
                    }

                    function updateTraceabilityImage(cameraId = 'CAM-001') {
                        const img = document.getElementById('trcAnnotatedImage');
                        const ph = document.getElementById('trcImagePlaceholder');
                        const metaBadge = document.getElementById('trcImageMetaBadge');

                        if (img) {
                            img.src = `/api/vision/traceability/cameras/${cameraId}/annotated.jpg?t=${Date.now()}`;
                            img.style.display = 'block';
                            img.onerror = function() {
                                img.style.display = 'none';
                                if (ph) ph.style.display = 'block';
                            };
                        }
                        if (ph) ph.style.display = 'none';
                        if (metaBadge) metaBadge.innerText = `Active Observer | ${cameraId} | In-Memory`;
                    }

                    function showTraceEvidence(traceId) {
                        const entry = globalTraceabilityCache.timeline.find(t => t.trace_id === traceId);
                        if (!entry) {
                            alert("Evidence details not found in active session cache.");
                            return;
                        }

                        const modal = document.getElementById('trcEvidenceModal');
                        const title = document.getElementById('modalTraceTitle');
                        const content = document.getElementById('modalTraceContent');

                        if (title) title.innerText = `Trace Evidence: ${entry.trace_id} (${entry.event_type})`;

                        const evidenceEntries = Object.entries(entry.evidence || {});
                        const evidenceRows = evidenceEntries.map(([k, v]) => `
                            <tr>
                                <td style="font-weight:700; color:var(--text-muted); padding:6px 0; text-transform:capitalize;">${escapeHtml(k.replace(/_/g, ' '))}:</td>
                                <td style="font-family:monospace; color:var(--text-main); font-weight:600;">${escapeHtml(JSON.stringify(v))}</td>
                            </tr>
                        `).join('');

                        if (content) {
                            content.innerHTML = `
                                <div style="display:flex; justify-content:space-between; align-items:center; background:var(--panel-subtle); padding:10px 14px; border-radius:8px; margin-bottom:12px;">
                                    <div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Material ID</div>
                                        <strong style="font-size:1.05rem; color:#8b5cf6;">${escapeHtml(entry.material_id)}</strong>
                                    </div>
                                    <div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Observation Nature</div>
                                        <strong style="font-size:0.95rem; color:${entry.nature === 'VALIDATED' ? '#10b981' : '#38bdf8'};">${escapeHtml(entry.nature || 'OBSERVED')}</strong>
                                    </div>
                                    <div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Origin Event ID</div>
                                        <strong style="font-size:1.05rem; font-family:monospace; color:var(--accent);">${escapeHtml(entry.event_id)}</strong>
                                    </div>
                                </div>

                                <h4 style="margin:12px 0 6px 0; font-size:0.88rem; color:var(--primary-navy);">Supporting Evidence Factors</h4>
                                <table style="width:100%; font-size:0.82rem; margin-bottom:14px;">
                                    <tbody>
                                        ${evidenceRows}
                                    </tbody>
                                </table>

                                <details style="background:var(--panel-subtle); padding:8px 12px; border-radius:6px; font-size:0.75rem; cursor:pointer;">
                                    <summary style="font-weight:700; color:var(--text-muted);">Raw Trace Record JSON</summary>
                                    <pre style="margin:8px 0 0 0; font-family:monospace; color:var(--text-main); font-size:0.72rem; overflow-x:auto;">${escapeHtml(JSON.stringify(entry, null, 2))}</pre>
                                </details>
                            `;
                        }

                        if (modal) modal.style.display = 'flex';
                    }

                    function closeTraceEvidenceModal() {
                        const modal = document.getElementById('trcEvidenceModal');
                        if (modal) modal.style.display = 'none';
                    }

                    // ============================================================================
                    // PART 15 — VISION RUNTIME & PROCESSING ORCHESTRATOR CLIENT LOGIC
                    // ============================================================================

                    let visionRuntimePollingTimer = null;
                    let activePreviewCameraId = null;

                    function initVisionRuntimeUI() {
                        fetchVisionRuntimeTelemetry();
                        if (visionRuntimePollingTimer) {
                            clearInterval(visionRuntimePollingTimer);
                        }
                        // Auto-refresh telemetry every 2 seconds when tab is open
                        visionRuntimePollingTimer = setInterval(() => {
                            const sub = document.getElementById('vision-runtime-sub');
                            if (sub && sub.style.display !== 'none') {
                                fetchVisionRuntimeTelemetry(true);
                            } else {
                                clearInterval(visionRuntimePollingTimer);
                                visionRuntimePollingTimer = null;
                            }
                        }, 2000);
                    }

                    async function fetchVisionRuntimeTelemetry(isBackground = false) {
                        try {
                            const res = await fetch('/api/vision/runtime/status');
                            const json = await res.json();
                            if (json.success && json.data) {
                                renderVisionRuntimeTelemetry(json.data);
                            }
                        } catch (err) {
                            if (!isBackground) {
                                console.error('Error fetching runtime telemetry:', err);
                            }
                        }
                    }

                    function renderVisionRuntimeTelemetry(data) {
                        const summary = data.summary || {};
                        const cameras = data.cameras || [];

                        // 1. Metric Cards
                        const activeCamsEl = document.getElementById('rtTotalActiveCams');
                        const degradedCamsEl = document.getElementById('rtDegradedCams');
                        const avgFpsEl = document.getElementById('rtAvgProcessingFps');
                        const framesProcEl = document.getElementById('rtTotalFramesProc');
                        const framesRecvEl = document.getElementById('rtTotalFramesRecv');
                        const framesDropEl = document.getElementById('rtTotalFramesDrop');

                        if (activeCamsEl) activeCamsEl.innerText = `${summary.running_cameras || 0} / ${summary.total_cameras || 0}`;
                        if (degradedCamsEl) degradedCamsEl.innerText = `${summary.degraded_cameras || 0} Degraded · ${summary.error_cameras || 0} Errors`;
                        if (avgFpsEl) avgFpsEl.innerText = `${(summary.average_processing_fps || 0).toFixed(1)} FPS`;
                        if (framesProcEl) framesProcEl.innerText = (summary.total_frames_processed || 0).toLocaleString();
                        if (framesRecvEl) framesRecvEl.innerText = `${(summary.total_frames_received || 0).toLocaleString()} Received`;
                        if (framesDropEl) framesDropEl.innerText = (summary.total_frames_dropped || 0).toLocaleString();

                        // 2. Camera Table
                        const tbody = document.getElementById('rtCameraTableBody');
                        if (!tbody) return;

                        if (cameras.length === 0) {
                            tbody.innerHTML = `<tr><td colspan="8" style="padding:1.5rem; text-align:center; color:var(--text-muted);">No camera sessions configured.</td></tr>`;
                            return;
                        }

                        tbody.innerHTML = cameras.map(cam => {
                            let badgeColor = '#6b7280';
                            let badgeBg = 'rgba(107, 114, 128, 0.15)';
                            if (cam.runtime_state === 'RUNNING') {
                                badgeColor = '#10b981';
                                badgeBg = 'rgba(16, 185, 129, 0.15)';
                            } else if (cam.runtime_state === 'DEGRADED') {
                                badgeColor = '#f59e0b';
                                badgeBg = 'rgba(245, 158, 11, 0.15)';
                            } else if (cam.runtime_state === 'ERROR') {
                                badgeColor = '#ef4444';
                                badgeBg = 'rgba(239, 68, 68, 0.15)';
                            }

                            const isRunning = cam.runtime_state === 'RUNNING';
                            const lastProcMs = cam.last_inference_ms ? `${cam.last_inference_ms.toFixed(1)} ms` : '--';
                            const lastProcTime = cam.last_processing_timestamp ? cam.last_processing_timestamp.split(' ')[1] : '--';
                            const lastFrameTime = cam.last_frame_timestamp ? cam.last_frame_timestamp.split(' ')[1] : '--';
                            const errText = cam.last_error ? escapeHtml(cam.last_error) : '<span style="color:var(--text-muted);">-</span>';

                            return `
                                <tr style="border-bottom:1px solid var(--border-light);">
                                    <td style="padding:0.6rem;">
                                        <div style="font-weight:600; color:var(--text-main);">${escapeHtml(cam.camera_code)}</div>
                                        <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(cam.camera_name || '')} (${escapeHtml(cam.location || '')})</div>
                                    </td>
                                    <td style="padding:0.6rem;">
                                        <span style="display:inline-block; padding:0.2rem 0.5rem; border-radius:4px; font-weight:700; font-size:0.72rem; color:${badgeColor}; background:${badgeBg};">
                                            ${escapeHtml(cam.runtime_state)}
                                        </span>
                                    </td>
                                    <td style="padding:0.6rem;">
                                        <span style="font-weight:600; color:${isRunning ? '#10b981' : 'var(--text-muted)'};">${(cam.actual_fps || 0).toFixed(1)}</span>
                                        <span style="font-size:0.75rem; color:var(--text-muted);">/ ${cam.configured_fps} FPS</span>
                                    </td>
                                    <td style="padding:0.6rem;">
                                        <span style="font-weight:600;">${cam.queue_depth || 0}</span>
                                        <span style="font-size:0.75rem; color:var(--text-muted);">/ ${cam.queue_max || 5}</span>
                                    </td>
                                    <td style="padding:0.6rem; font-size:0.8rem; color:var(--text-muted);">
                                        ${lastFrameTime}
                                    </td>
                                    <td style="padding:0.6rem; font-size:0.8rem;">
                                        <div>${lastProcTime}</div>
                                        <div style="font-size:0.72rem; color:var(--text-muted);">${lastProcMs}</div>
                                    </td>
                                    <td style="padding:0.6rem; font-size:0.78rem; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#ef4444;">
                                        ${errText}
                                    </td>
                                    <td style="padding:0.6rem; text-align:center;">
                                        <div style="display:inline-flex; gap:6px;">
                                            ${isRunning ? `
                                                <button type="button" class="btn-secondary" onclick="stopRuntimeCamera('${cam.camera_id}')" style="padding:0.25rem 0.55rem; font-size:0.75rem; color:#ef4444; border-color:#fca5a5;">
                                                    ⏹ Stop
                                                </button>
                                                <button type="button" class="btn-secondary" onclick="restartRuntimeCamera('${cam.camera_id}')" style="padding:0.25rem 0.55rem; font-size:0.75rem;">
                                                    🔄
                                                </button>
                                            ` : `
                                                <button type="button" class="btn-primary" onclick="startRuntimeCamera('${cam.camera_id}')" style="padding:0.25rem 0.55rem; font-size:0.75rem; background:#10b981;">
                                                    ▶ Start
                                                </button>
                                            `}
                                            <button type="button" class="btn-secondary" onclick="testStepRuntimeCamera('${cam.camera_id}')" title="Run 1 Test Frame" style="padding:0.25rem 0.55rem; font-size:0.75rem; color:#8b5cf6; border-color:#ddd6fe;">
                                                ⚡ Step
                                            </button>
                                            <button type="button" class="btn-secondary" onclick="openRuntimePreview('${cam.camera_id}')" title="Live Preview" style="padding:0.25rem 0.55rem; font-size:0.75rem;">
                                                👁
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            `;
                        }).join('');

                        // If live preview is open, update its frame
                        if (activePreviewCameraId) {
                            const previewImg = document.getElementById('rtPreviewImg');
                            if (previewImg) {
                                previewImg.src = `/api/vision/runtime/cameras/${activePreviewCameraId}/preview.jpg?t=${Date.now()}`;
                            }
                        }
                    }

                    async function startRuntimeCamera(cameraId) {
                        try {
                            const res = await fetch(`/api/vision/runtime/cameras/${encodeURIComponent(cameraId)}/start`, { method: 'POST' });
                            const json = await res.json();
                            fetchVisionRuntimeTelemetry();
                        } catch (e) {
                            console.error('Failed to start camera:', e);
                        }
                    }

                    async function stopRuntimeCamera(cameraId) {
                        try {
                            const res = await fetch(`/api/vision/runtime/cameras/${encodeURIComponent(cameraId)}/stop`, { method: 'POST' });
                            const json = await res.json();
                            fetchVisionRuntimeTelemetry();
                        } catch (e) {
                            console.error('Failed to stop camera:', e);
                        }
                    }

                    async function restartRuntimeCamera(cameraId) {
                        try {
                            const res = await fetch(`/api/vision/runtime/cameras/${encodeURIComponent(cameraId)}/restart`, { method: 'POST' });
                            const json = await res.json();
                            fetchVisionRuntimeTelemetry();
                        } catch (e) {
                            console.error('Failed to restart camera:', e);
                        }
                    }

                    async function testStepRuntimeCamera(cameraId) {
                        try {
                            const res = await fetch(`/api/vision/runtime/cameras/${encodeURIComponent(cameraId)}/test_step`, { method: 'POST' });
                            const json = await res.json();
                            fetchVisionRuntimeTelemetry();
                        } catch (e) {
                            console.error('Failed to step camera test:', e);
                        }
                    }

                    async function startAllRuntimeCameras() {
                        try {
                            await fetch('/api/vision/runtime/start', { method: 'POST' });
                            fetchVisionRuntimeTelemetry();
                        } catch (e) {
                            console.error('Failed to start all cameras:', e);
                        }
                    }

                    async function stopAllRuntimeCameras() {
                        try {
                            await fetch('/api/vision/runtime/stop', { method: 'POST' });
                            fetchVisionRuntimeTelemetry();
                        } catch (e) {
                            console.error('Failed to stop all cameras:', e);
                        }
                    }

                    function openRuntimePreview(cameraId) {
                        activePreviewCameraId = cameraId;
                        const sec = document.getElementById('rtPreviewSection');
                        const title = document.getElementById('rtPreviewTitle');
                        const img = document.getElementById('rtPreviewImg');
                        if (title) title.innerText = `Live Pipeline View — ${cameraId}`;
                        if (img) img.src = `/api/vision/runtime/cameras/${encodeURIComponent(cameraId)}/preview.jpg?t=${Date.now()}`;
                        if (sec) sec.style.display = 'block';
                    }

                    function closeRuntimePreview() {
                        activePreviewCameraId = null;
                        const sec = document.getElementById('rtPreviewSection');
                        if (sec) sec.style.display = 'none';
                    }

                    // ============================================================================
                    // MATERIAL ASSOCIATION ENGINE UI (PART 9)
                    // ============================================================================
                    let currentMaterialAssociations = [];

                    function initMaterialAssociationTestUI() {
                        fetchMaterialAssociationStatus();
                    }

                    async function fetchMaterialAssociationStatus() {
                        try {
                            const res = await fetch('/api/vision/material-association/status');
                            if (!res.ok) return;
                            const data = await res.json();
                            const cfg = data.config || {};
                            if (document.getElementById('cfgMatMinFrames')) document.getElementById('cfgMatMinFrames').innerText = `${cfg.min_consecutive_frames || 3} frames`;
                            if (document.getElementById('cfgMatMaxDist')) document.getElementById('cfgMatMaxDist').innerText = `${cfg.max_normalized_distance || 0.40}`;
                            if (document.getElementById('cfgMatMinScore')) document.getElementById('cfgMatMinScore').innerText = `${cfg.min_association_score || 0.70}`;
                            if (document.getElementById('cfgMatAmbDelta')) document.getElementById('cfgMatAmbDelta').innerText = `≤ ${cfg.ambiguity_threshold_delta || 0.15}`;
                        } catch (e) {
                            console.error('Failed to fetch material association status:', e);
                        }
                    }

                    function generateMaterialSyntheticScenario(scenarioName, frameIdx = 1) {
                        if (scenarioName === 'scenario_material_truck') {
                            return [
                                {
                                    track_id: 10,
                                    class_code: "TRUCK",
                                    confidence: 0.95,
                                    bbox: { x1: 180, y1: 160, x2: 420, y2: 390 },
                                    center_normalized: [0.30, 0.45],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "GP-1000", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "TRUCK", master_id: "GP-1000", display_name: "Truck GP-1000" }
                                },
                                {
                                    track_id: 21,
                                    class_code: "GLASS",
                                    confidence: 0.93,
                                    bbox: { x1: 390, y1: 310, x2: 480, y2: 410 },
                                    center_normalized: [0.36, 0.50],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "AUTO-GLASS-01", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "MATERIAL", master_id: "AUTO-GLASS-01", display_name: "Front Windshield (Glass)" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_material_worker') {
                            return [
                                {
                                    track_id: 5,
                                    class_code: "WORKER",
                                    confidence: 0.94,
                                    bbox: { x1: 200, y1: 150, x2: 320, y2: 420 },
                                    center_normalized: [0.26, 0.38],
                                    roi: { inside: true, zone_code: "AISLE-01" },
                                    identity: { status: "IDENTIFIED", value: "admin", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "WORKER", master_id: "admin", display_name: "Operator Admin" }
                                },
                                {
                                    track_id: 22,
                                    class_code: "ROD",
                                    confidence: 0.92,
                                    bbox: { x1: 270, y1: 280, x2: 380, y2: 360 },
                                    center_normalized: [0.32, 0.42],
                                    roi: { inside: true, zone_code: "AISLE-01" },
                                    identity: { status: "IDENTIFIED", value: "AUTO-ROD-01", source: "OCR" },
                                    validation: { status: "VALIDATED", master_type: "MATERIAL", master_id: "AUTO-ROD-01", display_name: "Steering Tie Rod" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_material_bin') {
                            return [
                                {
                                    track_id: 23,
                                    class_code: "FASTENER",
                                    confidence: 0.91,
                                    bbox: { x1: 400, y1: 300, x2: 480, y2: 380 },
                                    center_normalized: [0.44, 0.44],
                                    roi: { inside: true, zone_code: "STORAGE-01" },
                                    identity: { status: "IDENTIFIED", value: "AUTO-BOLT-01", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "MATERIAL", master_id: "AUTO-BOLT-01", display_name: "Flange Bolt 10.9" }
                                },
                                {
                                    track_id: 40,
                                    class_code: "BIN",
                                    confidence: 0.96,
                                    bbox: { x1: 380, y1: 260, x2: 520, y2: 430 },
                                    center_normalized: [0.45, 0.45],
                                    roi: { inside: true, zone_code: "STORAGE-01" },
                                    identity: { status: "IDENTIFIED", value: "BIN-01", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "BIN", master_id: "BIN-01", display_name: "Bin BIN-01" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_container_material') {
                            return [
                                {
                                    track_id: 15,
                                    class_code: "CONTAINER",
                                    confidence: 0.93,
                                    bbox: { x1: 300, y1: 250, x2: 500, y2: 450 },
                                    center_normalized: [0.40, 0.45],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "BOX-101", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "CONTAINER", master_id: "BOX-101", display_name: "Container BOX-101" }
                                },
                                {
                                    track_id: 24,
                                    class_code: "GLASS",
                                    confidence: 0.92,
                                    bbox: { x1: 320, y1: 270, x2: 480, y2: 430 },
                                    center_normalized: [0.40, 0.45],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "AUTO-GLASS-01", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "MATERIAL", master_id: "AUTO-GLASS-01", display_name: "Front Windshield (Glass)" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_single_frame') {
                            return [
                                {
                                    track_id: 10,
                                    class_code: "TRUCK",
                                    confidence: 0.95,
                                    center_normalized: [0.30, 0.45],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "GP-1000", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "TRUCK", master_id: "GP-1000" }
                                },
                                {
                                    track_id: 25,
                                    class_code: "PART",
                                    confidence: 0.90,
                                    center_normalized: [0.34, 0.48],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "SKU-001", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "MATERIAL", master_id: "SKU-001" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_diff_zones') {
                            return [
                                {
                                    track_id: 10,
                                    class_code: "TRUCK",
                                    center_normalized: [0.20, 0.30],
                                    roi: { inside: true, zone_code: "STORAGE-01" },
                                    identity: { status: "IDENTIFIED", value: "GP-1000", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "TRUCK", master_id: "GP-1000" }
                                },
                                {
                                    track_id: 26,
                                    class_code: "GLASS",
                                    center_normalized: [0.25, 0.35],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "AUTO-GLASS-01", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "MATERIAL", master_id: "AUTO-GLASS-01" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_ambiguous_trucks') {
                            return [
                                {
                                    track_id: 11,
                                    class_code: "TRUCK",
                                    center_normalized: [0.25, 0.50],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "GP-1000", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "TRUCK", master_id: "GP-1000" }
                                },
                                {
                                    track_id: 12,
                                    class_code: "TRUCK",
                                    center_normalized: [0.35, 0.50],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "GP-2000", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "TRUCK", master_id: "GP-2000" }
                                },
                                {
                                    track_id: 27,
                                    class_code: "COMPONENT",
                                    center_normalized: [0.30, 0.50],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "AUTO-GLASS-01", source: "BARCODE" },
                                    validation: { status: "VALIDATED", master_type: "MATERIAL", master_id: "AUTO-GLASS-01" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_unidentified_mat') {
                            return [
                                {
                                    track_id: 10,
                                    class_code: "TRUCK",
                                    center_normalized: [0.30, 0.45],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "GP-1000", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "TRUCK", master_id: "GP-1000" }
                                },
                                {
                                    track_id: 28,
                                    class_code: "MATERIAL",
                                    center_normalized: [0.35, 0.48],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "UNIDENTIFIED", value: null },
                                    validation: { status: "NOT_APPLICABLE" }
                                }
                            ];
                        }
                        if (scenarioName === 'scenario_conflicted_mat') {
                            return [
                                {
                                    track_id: 10,
                                    class_code: "TRUCK",
                                    center_normalized: [0.30, 0.45],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "IDENTIFIED", value: "GP-1000", source: "QR" },
                                    validation: { status: "VALIDATED", master_type: "TRUCK", master_id: "GP-1000" }
                                },
                                {
                                    track_id: 29,
                                    class_code: "MATERIAL",
                                    center_normalized: [0.35, 0.48],
                                    roi: { inside: true, zone_code: "DOCK-01" },
                                    identity: { status: "CONFLICT", value: "AUTO-GLASS-01" },
                                    validation: { status: "NOT_APPLICABLE" }
                                }
                            ];
                        }
                        return [];
                    }

                    async function runMaterialAssociationTest() {
                        const btn = document.getElementById('btnRunMatAssoc');
                        const origText = btn ? btn.innerHTML : 'Run Single Frame';
                        if (btn) { btn.disabled = true; btn.innerHTML = '<span>⏳</span> Processing...'; }

                        try {
                            const cameraId = document.getElementById('matAssocCameraSelect')?.value || 'CAM-001';
                            const scenarioName = document.getElementById('matAssocScenarioSelect')?.value || 'scenario_material_truck';
                            const tracks = generateMaterialSyntheticScenario(scenarioName, 1);

                            const res = await fetch('/api/vision/material-association/test', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    camera_id: cameraId,
                                    synthetic_tracks: tracks
                                })
                            });
                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.message || "Material association test failed.");
                                return;
                            }
                            renderMaterialAssociationResults(data);
                        } catch (e) {
                            alert("API error: " + e.message);
                        } finally {
                            if (btn) { btn.disabled = false; btn.innerHTML = origText; }
                        }
                    }

                    async function runMaterialAssociationSequence() {
                        const btn = document.getElementById('btnRunMatAssocSeq');
                        const origText = btn ? btn.innerHTML : 'Run Sequence';
                        if (btn) { btn.disabled = true; btn.innerHTML = '<span>⏩</span> Running 3 Frames...'; }

                        try {
                            const cameraId = document.getElementById('matAssocCameraSelect')?.value || 'CAM-001';
                            const scenarioName = document.getElementById('matAssocScenarioSelect')?.value || 'scenario_material_truck';
                            const baseTracks = generateMaterialSyntheticScenario(scenarioName, 1);

                            const frames = [baseTracks, baseTracks, baseTracks];

                            const res = await fetch('/api/vision/material-association/sequence', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    camera_id: cameraId,
                                    frames: frames
                                })
                            });
                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                alert(data.message || "Sequence failed.");
                                return;
                            }
                            const lastFrameAssocs = data.sequence[data.sequence.length - 1]?.associations || [];
                            renderMaterialAssociationResults({
                                camera_id: cameraId,
                                associations: lastFrameAssocs,
                                association_ms: 2.5
                            });
                        } catch (e) {
                            alert("Sequence API error: " + e.message);
                        } finally {
                            if (btn) { btn.disabled = false; btn.innerHTML = origText; }
                        }
                    }

                    async function resetMaterialAssociationSession() {
                        try {
                            const cameraId = document.getElementById('matAssocCameraSelect')?.value || 'CAM-001';
                            const res = await fetch('/api/vision/material-association/reset', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ camera_id: cameraId })
                            });
                            const data = await res.json();
                            alert(data.message || "Material association session reset.");
                            currentMaterialAssociations = [];
                            renderMaterialAssociationResults({ camera_id: cameraId, associations: [] });
                        } catch (e) {
                            alert("Reset failed: " + e.message);
                        }
                    }

                    async function searchMaterialCrossCamera() {
                        const input = document.getElementById('matCrossCamInput');
                        const sku = input ? input.value.trim() : '';
                        if (!sku) { alert("Please enter a SKU or Material ID."); return; }

                        try {
                            const res = await fetch(`/api/vision/material-association/materials/${encodeURIComponent(sku)}`);
                            const data = await res.json();
                            const found = data.total_associations_found || 0;
                            let msg = `Cross-Camera Search for '${sku}':\nFound ${found} associations across active camera sessions.\nMethod: ${data.cross_camera_continuity_method}`;
                            alert(msg);
                            if (found > 0) {
                                renderMaterialAssociationResults({ associations: data.associations });
                            }
                        } catch (e) {
                            alert("Cross-camera search error: " + e.message);
                        }
                    }

                    function renderMaterialAssociationResults(data) {
                        const assocs = data.associations || [];
                        currentMaterialAssociations = assocs;

                        const total = assocs.length;
                        const confirmed = assocs.filter(a => a.status === 'CONFIRMED').length;
                        const candidate = assocs.filter(a => a.status === 'CANDIDATE').length;
                        const ambiguous = assocs.filter(a => a.evidence?.is_ambiguous).length;
                        const rejected = assocs.filter(a => a.status === 'REJECTED' || a.status === 'EXPIRED').length;
                        const ms = data.association_ms || data.performance?.association_ms || 0.0;

                        if (document.getElementById('matKpiTotal')) document.getElementById('matKpiTotal').innerText = total;
                        if (document.getElementById('matKpiConfirmed')) document.getElementById('matKpiConfirmed').innerText = confirmed;
                        if (document.getElementById('matKpiCandidate')) document.getElementById('matKpiCandidate').innerText = candidate;
                        if (document.getElementById('matKpiAmbiguous')) document.getElementById('matKpiAmbiguous').innerText = ambiguous;
                        if (document.getElementById('matKpiRejected')) document.getElementById('matKpiRejected').innerText = rejected;
                        if (document.getElementById('matKpiLatency')) document.getElementById('matKpiLatency').innerText = `${ms} ms`;
                        if (document.getElementById('matAssocCountBadge')) document.getElementById('matAssocCountBadge').innerText = `${total} Pairs`;

                        const tbody = document.getElementById('matAssocTableBody');
                        if (!tbody) return;

                        if (assocs.length === 0) {
                            tbody.innerHTML = `<tr><td colspan="6" style="padding:2rem 1rem; text-align:center; color:var(--text-muted);">No association candidates active in current session.</td></tr>`;
                            return;
                        }

                        let html = '';
                        assocs.forEach((a, idx) => {
                            const type = a.association_type || 'ASSOCIATION';
                            const pId = a.primary_track_id;
                            const sId = a.secondary_track_id;
                            const pCls = a.primary_class;
                            const sCls = a.secondary_class;
                            const status = a.status || 'CANDIDATE';
                            const score = (a.association_score || 0).toFixed(2);
                            const rwa = a.real_world_association;

                            let statusColor = '#f59e0b';
                            if (status === 'CONFIRMED') statusColor = '#10b981';
                            else if (status === 'REJECTED') statusColor = '#ef4444';
                            else if (status === 'EXPIRED') statusColor = '#6b7280';

                            let rwaText = '<span style="color:var(--text-muted); font-style:italic;">None (Track Only)</span>';
                            if (rwa) {
                                if (type === 'TRUCK_MATERIAL') {
                                    rwaText = `<strong style="color:#0284c7;">${escapeHtml(rwa.truck_id)}</strong> ↔ <strong style="color:#10b981;">${escapeHtml(rwa.material_sku)}</strong>`;
                                } else if (type === 'TRUCK_CONTAINER') {
                                    rwaText = `<strong style="color:#0284c7;">${escapeHtml(rwa.truck_id)}</strong> ↔ <strong style="color:#f59e0b;">${escapeHtml(rwa.container_id)}</strong>`;
                                } else if (type === 'WORKER_MATERIAL') {
                                    rwaText = `<strong style="color:#ec4899;">${escapeHtml(rwa.worker_id)}</strong> ↔ <strong style="color:#10b981;">${escapeHtml(rwa.material_sku)}</strong>`;
                                } else if (type === 'MATERIAL_BIN') {
                                    rwaText = `<strong style="color:#10b981;">${escapeHtml(rwa.material_sku)}</strong> ↔ <strong style="color:#8b5cf6;">${escapeHtml(rwa.bin_id)}</strong>`;
                                } else if (type === 'MATERIAL_CONTAINER') {
                                    rwaText = `Container <strong style="color:#f59e0b;">${escapeHtml(rwa.container_id)}</strong> holds Material <strong style="color:#10b981;">${escapeHtml(rwa.material_sku)}</strong>`;
                                }
                            }

                            html += `
                                <tr style="border-bottom:1px solid var(--border-light);">
                                    <td style="padding:6px 8px; font-weight:700; font-size:0.75rem; color:#0284c7;">${escapeHtml(type)}</td>
                                    <td style="padding:6px 8px;">${escapeHtml(pCls)} #${pId} ↔ ${escapeHtml(sCls)} #${sId}</td>
                                    <td style="padding:6px 8px;">${rwaText}</td>
                                    <td style="padding:6px 8px; font-weight:700;">${score}</td>
                                    <td style="padding:6px 8px;"><span class="badge" style="background:${statusColor}; color:#fff; font-size:0.7rem;">${status}</span></td>
                                    <td style="padding:6px 8px; text-align:center;">
                                        <button class="btn-secondary" onclick="openMaterialEvidenceModal(${idx})" style="padding:2px 8px; font-size:0.72rem;">Evidence</button>
                                    </td>
                                </tr>
                            `;
                        });
                        tbody.innerHTML = html;
                    }

                    function openMaterialEvidenceModal(idx) {
                        const assoc = currentMaterialAssociations[idx];
                        if (!assoc) return;
                        const modal = document.getElementById('matEvidenceModal');
                        const content = document.getElementById('modalMatContent');
                        const ev = assoc.evidence || {};

                        let explanation = ev.explanation || 'No detail available.';
                        let ambiguityHtml = '';
                        if (ev.is_ambiguous) {
                            ambiguityHtml = `<div style="background:rgba(236,72,153,0.1); border:1px solid #ec4899; border-radius:6px; padding:8px 10px; margin-bottom:10px; color:#ec4899; font-size:0.8rem;">
                                <strong>⚠️ Ambiguous Competitors Detected:</strong> ${escapeHtml(ev.ambiguity_reason || '')}
                            </div>`;
                        }

                        content.innerHTML = `
                            ${ambiguityHtml}
                            <div style="background:var(--panel-subtle); border-radius:8px; padding:10px; margin-bottom:10px;">
                                <div style="font-weight:700; color:var(--text-main); font-size:0.85rem; margin-bottom:4px;">Rule Decision:</div>
                                <div style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(explanation)}</div>
                            </div>
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px; font-size:0.78rem;">
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Association Type:</strong> ${escapeHtml(assoc.association_type)}
                                </div>
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Status:</strong> ${escapeHtml(assoc.status)}
                                </div>
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Same Camera:</strong> ${ev.same_camera ? '✓ True' : '✗ False'}
                                </div>
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Same Zone:</strong> ${ev.same_zone ? `✓ Match (${escapeHtml(ev.primary_zone || '')})` : `✗ Mismatch (${escapeHtml(ev.primary_zone || 'None')} vs ${escapeHtml(ev.secondary_zone || 'None')})`}
                                </div>
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Distance:</strong> ${ev.normalized_distance} (max: ${ev.max_allowed_distance})
                                </div>
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Consecutive Frames:</strong> ${ev.consecutive_frames} / 3 min
                                </div>
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Movement Score:</strong> ${ev.movement_consistency_score}
                                </div>
                                <div style="background:var(--panel-bg); padding:8px; border:1px solid var(--border-light); border-radius:6px;">
                                    <strong>Physical Master Identity:</strong> ${ev.validated_physical_identity ? '✓ VALIDATED' : '✗ Unvalidated/None'}
                                </div>
                            </div>
                        `;
                        modal.style.display = 'flex';
                    }

                    function closeMaterialEvidenceModal() {
                        const modal = document.getElementById('matEvidenceModal');
                        if (modal) modal.style.display = 'none';
                    }

                    // ============================================================================
                    // PART 12: W.A.R.L.O.G. LIVE VISION DASHBOARD ENHANCEMENT
                    // ============================================================================
                    let dashSelectedCameraId = null;
                    let dashPollTimer = null;
                    let dashIsPolling = false;
                    let dashLatestData = null;
                    let dashMaterialSearchTerm = '';
                    let dashImgFailCount = 0;

                    function initLiveVisionDashboard() {
                        if (dashPollTimer) {
                            clearInterval(dashPollTimer);
                            dashPollTimer = null;
                        }
                        dashIsPolling = true;
                        loadLiveVisionDashboard(false);
                        dashPollTimer = setInterval(() => {
                            const sub = document.getElementById('vision-dashboard-sub');
                            if (sub && sub.style.display !== 'none') {
                                loadLiveVisionDashboard(false);
                            } else {
                                stopLiveVisionDashboardPolling();
                            }
                        }, 2500);
                    }

                    function stopLiveVisionDashboardPolling() {
                        if (dashPollTimer) {
                            clearInterval(dashPollTimer);
                            dashPollTimer = null;
                        }
                        dashIsPolling = false;
                    }

                    async function loadLiveVisionDashboard(isManual = false) {
                        try {
                            const url = `/api/vision/dashboard/live` + (dashSelectedCameraId ? `?camera_id=${encodeURIComponent(dashSelectedCameraId)}` : '');
                            const res = await fetch(url);
                            if (!res.ok) {
                                console.warn('[Dash] Live dashboard fetch failed:', res.status);
                                return;
                            }
                            const data = await res.json();
                            dashLatestData = data;

                            // 1. Telemetry KPIs
                            const totalCams = data.total_cameras || 0;
                            const activeCams = data.active_cameras || 0;
                            const elActiveCams = document.getElementById('kpi-dash-active-cams');
                            if (elActiveCams) elActiveCams.innerText = `${activeCams} / ${totalCams}`;

                            const elFps = document.getElementById('kpi-dash-fps');
                            if (elFps) elFps.innerText = `${(data.aggregate_fps || 0).toFixed(1)} FPS`;

                            const elTracks = document.getElementById('kpi-dash-tracks');
                            if (elTracks) elTracks.innerText = String(data.tracked_objects || 0);

                            const elMaterials = document.getElementById('kpi-dash-materials');
                            if (elMaterials) elMaterials.innerText = String(data.active_materials_count || 0);

                            const elZones = document.getElementById('kpi-dash-zones');
                            if (elZones) elZones.innerText = String(data.occupied_zones || 0);

                            const elAlerts = document.getElementById('kpi-dash-alerts');
                            if (elAlerts) elAlerts.innerText = String(data.operational_alerts ? data.operational_alerts.length : 0);

                            // 2. Master Runtime Status Indicator
                            const rtBadge = document.getElementById('dashRuntimeStatusBadge');
                            const rtDot = document.getElementById('dashRuntimeDot');
                            const rtText = document.getElementById('dashRuntimeText');
                            if (data.runtime_active) {
                                if (rtDot) {
                                    rtDot.style.background = '#10b981';
                                    rtDot.style.boxShadow = '0 0 8px #10b981';
                                }
                                if (rtText) rtText.innerText = 'RUNTIME RUNNING';
                                if (rtBadge) {
                                    rtBadge.style.background = 'rgba(16, 185, 129, 0.15)';
                                    rtBadge.style.color = '#10b981';
                                    rtBadge.style.borderColor = '#10b981';
                                }
                            } else {
                                if (rtDot) {
                                    rtDot.style.background = '#64748b';
                                    rtDot.style.boxShadow = 'none';
                                }
                                if (rtText) rtText.innerText = 'RUNTIME STOPPED';
                                if (rtBadge) {
                                    rtBadge.style.background = 'var(--panel-subtle)';
                                    rtBadge.style.color = 'var(--text-muted)';
                                    rtBadge.style.borderColor = 'var(--border-light)';
                                }
                            }

                            // 3. Camera Selector Pills
                            renderDashboardCameraPills(data.cameras || [], data.selected_camera);

                            // 4. Live Camera Perception Node
                            renderDashboardLiveCamera(data.selected_camera, data.selected_camera_tracks || []);

                            // 5. Active Traced Materials (Part 11)
                            renderDashboardMaterials(data.active_materials || []);

                            // 6. Zone Occupancy Matrix
                            renderDashboardZoneMatrix(data.zone_occupancy || []);

                            // 7. Movement Event Stream (Part 10)
                            renderDashboardEventStream(data.movement_events || []);

                            // 8. Active & Candidate Associations (Part 9)
                            renderDashboardAssociations(data.associations || []);

                            // 9. Operational Alerts & Exceptions
                            renderDashboardAlerts(data.operational_alerts || []);

                            // 10. Part 13: Controlled Actions & WMS Transactions
                            renderControlledActions(data.controlled_action_recommendations || []);

                        } catch (err) {
                            console.error('[Dash] loadLiveVisionDashboard error:', err);
                        }
                    }

                    function renderDashboardCameraPills(cameras, selectedCam) {
                        const container = document.getElementById('dashCamPills');
                        if (!container) return;

                        if (!dashSelectedCameraId && selectedCam) {
                            dashSelectedCameraId = selectedCam.id;
                        }

                        if (cameras.length === 0) {
                            container.innerHTML = `<span style="font-size:0.75rem; color:var(--text-muted);">No camera sources configured</span>`;
                            return;
                        }

                        let html = '';
                        cameras.forEach(cam => {
                            const isSelected = (cam.id === dashSelectedCameraId) || (!dashSelectedCameraId && selectedCam && selectedCam.id === cam.id);
                            const activeColor = cam.is_active ? '#10b981' : '#64748b';
                            const bg = isSelected ? 'var(--primary-navy)' : 'var(--panel-bg)';
                            const color = isSelected ? '#ffffff' : 'var(--text-main)';
                            const border = isSelected ? 'var(--accent)' : 'var(--border-light)';

                            html += `
                                <button type="button" onclick="selectDashboardCamera('${escapeHtml(cam.id)}')"
                                    style="background:${bg}; color:${color}; border:1px solid ${border}; border-radius:6px; padding:4px 10px; font-size:0.75rem; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:6px; white-space:nowrap; transition:all 0.15s ease;">
                                    <span style="width:7px; height:7px; border-radius:50%; background:${activeColor};"></span>
                                    <span>${escapeHtml(cam.name || cam.id)}</span>
                                    ${cam.is_active ? `<span style="font-size:0.68rem; opacity:0.8;">(${cam.fps.toFixed(1)} FPS)</span>` : ''}
                                </button>
                            `;
                        });
                        container.innerHTML = html;
                    }

                    function selectDashboardCamera(camId) {
                        dashSelectedCameraId = camId;
                        loadLiveVisionDashboard(true);
                    }

                    function renderDashboardLiveCamera(cam, tracks) {
                        const titleEl = document.getElementById('dashCamTitle');
                        const badgeEl = document.getElementById('dashCamStateBadge');
                        const srcTypeEl = document.getElementById('dashCamSourceType');
                        const fpsTagEl = document.getElementById('dashCamFpsTag');
                        const imgEl = document.getElementById('dashPreviewImg');
                        const fallbackEl = document.getElementById('dashPreviewFallback');
                        const pulseDot = document.getElementById('dashLivePulseDot');
                        const liveText = document.getElementById('dashLiveOverlayText');
                        const hudZone = document.getElementById('dashHudZone');
                        const hudObjects = document.getElementById('dashHudObjects');
                        const tracksCountBadge = document.getElementById('dashTracksCountBadge');
                        const detectionsTbody = document.getElementById('dashDetectionsTableBody');

                        if (!cam) {
                            if (titleEl) titleEl.innerText = 'No Camera Selected';
                            if (badgeEl) { badgeEl.innerText = 'IDLE'; badgeEl.style.background = '#64748b'; }
                            if (imgEl) imgEl.style.display = 'none';
                            if (fallbackEl) fallbackEl.style.display = 'flex';
                            if (tracksCountBadge) tracksCountBadge.innerText = '0 Entities';
                            if (detectionsTbody) detectionsTbody.innerHTML = `<tr><td colspan="6" style="padding:16px; text-align:center; color:var(--text-muted);">No camera selected.</td></tr>`;
                            return;
                        }

                        if (titleEl) titleEl.innerText = `${cam.name || cam.id} (${cam.zone || 'Global'})`;
                        if (badgeEl) {
                            badgeEl.innerText = cam.status;
                            badgeEl.style.background = cam.status === 'RUNNING' ? '#10b981' : (cam.status === 'ERROR' ? '#ef4444' : '#64748b');
                        }
                        if (srcTypeEl) srcTypeEl.innerText = cam.source_type || 'SHARED BUS';
                        if (fpsTagEl) fpsTagEl.innerText = `${(cam.fps || 0).toFixed(1)} FPS`;
                        if (hudZone) hudZone.innerText = `Zone: ${cam.zone || 'None'}`;
                        if (hudObjects) hudObjects.innerText = `Objects: ${tracks.length}`;

                        // Live Feed Preview Image
                        if (imgEl && fallbackEl) {
                            if (cam.status === 'RUNNING' || cam.status === 'STOPPED' || cam.status === 'STANDBY') {
                                const previewUrl = `/preview.jpg?source=${encodeURIComponent(cam.source || '')}&camera_id=${encodeURIComponent(cam.id)}&t=${Date.now()}`;
                                imgEl.src = previewUrl;
                                imgEl.style.display = 'block';
                                fallbackEl.style.display = 'none';
                            } else {
                                imgEl.style.display = 'none';
                                fallbackEl.style.display = 'flex';
                            }
                        }

                        if (pulseDot) {
                            pulseDot.style.background = cam.status === 'RUNNING' ? '#10b981' : '#64748b';
                            pulseDot.style.boxShadow = cam.status === 'RUNNING' ? '0 0 8px #10b981' : 'none';
                        }
                        if (liveText) {
                            liveText.innerText = cam.status === 'RUNNING' ? 'LIVE FEED' : 'STANDBY';
                        }

                        // Detections & Active Tracks Inspector Table
                        if (tracksCountBadge) tracksCountBadge.innerText = `${tracks.length} Entities`;
                        if (detectionsTbody) {
                            if (tracks.length === 0) {
                                detectionsTbody.innerHTML = `<tr><td colspan="6" style="padding:16px; text-align:center; color:var(--text-muted);">No active objects detected in ${escapeHtml(cam.name || cam.id)}.</td></tr>`;
                            } else {
                                let rowHtml = '';
                                tracks.forEach(tr => {
                                    const trId = tr.track_id;
                                    const cls = tr.class_name || 'UNKNOWN';
                                    const conf = ((tr.confidence || 0) * 100).toFixed(0);
                                    const tag = tr.identity_value || 'UNIDENTIFIED';
                                    const valState = tr.validation_status || 'NOT_APPLICABLE';
                                    const zone = tr.zone || 'None';

                                    let valColor = '#64748b';
                                    if (valState === 'VALIDATED') valColor = '#10b981';
                                    else if (valState === 'UNREGISTERED') valColor = '#0284c7';
                                    else if (valState === 'AMBIGUOUS' || valState === 'CONFLICT') valColor = '#ef4444';

                                    let clsColor = '#0284c7';
                                    if (['BOX', 'PALLET', 'CONTAINER', 'TRAY', 'CRATE'].includes(cls)) clsColor = '#8b5cf6';
                                    else if (['GLASS', 'ROD', 'FASTENER', 'PART', 'COMPONENT', 'MATERIAL', 'SKU'].includes(cls)) clsColor = '#10b981';
                                    else if (['WORKER', 'PERSON'].includes(cls)) clsColor = '#ec4899';
                                    else if (['TRUCK', 'FORKLIFT', 'VEHICLE'].includes(cls)) clsColor = '#f59e0b';

                                    rowHtml += `
                                        <tr style="border-bottom:1px solid var(--border-light);">
                                            <td style="padding:6px 8px; font-weight:700; color:var(--primary-navy);">#${escapeHtml(String(trId))}</td>
                                            <td style="padding:6px 8px;">
                                                <span class="badge" style="background:${clsColor}; color:#fff; font-size:0.68rem; padding:2px 6px;">${escapeHtml(cls)}</span>
                                            </td>
                                            <td style="padding:6px 8px; font-weight:600;">${conf}%</td>
                                            <td style="padding:6px 8px; font-family:monospace; font-size:0.75rem;">${escapeHtml(tag)}</td>
                                            <td style="padding:6px 8px;">
                                                <span class="badge" style="background:${valColor}; color:#fff; font-size:0.68rem; padding:2px 6px;">${escapeHtml(valState)}</span>
                                            </td>
                                            <td style="padding:6px 8px; font-size:0.72rem; color:var(--text-muted);">${escapeHtml(zone)}</td>
                                        </tr>
                                    `;
                                });
                                detectionsTbody.innerHTML = rowHtml;
                            }
                        }
                    }

                    function handleDashPreviewError() {
                        dashImgFailCount++;
                        const imgEl = document.getElementById('dashPreviewImg');
                        const fallbackEl = document.getElementById('dashPreviewFallback');
                        if (dashImgFailCount > 2) {
                            if (imgEl) imgEl.style.display = 'none';
                            if (fallbackEl) fallbackEl.style.display = 'flex';
                        }
                    }

                    function handleDashPreviewSuccess() {
                        dashImgFailCount = 0;
                        const imgEl = document.getElementById('dashPreviewImg');
                        const fallbackEl = document.getElementById('dashPreviewFallback');
                        if (imgEl) imgEl.style.display = 'block';
                        if (fallbackEl) fallbackEl.style.display = 'none';
                    }

                    function renderDashboardMaterials(materials) {
                        const listEl = document.getElementById('dashMaterialsList');
                        const badgeEl = document.getElementById('dashMaterialCountBadge');
                        if (!listEl) return;

                        const filterTerm = (dashMaterialSearchTerm || '').toLowerCase().trim();
                        const filtered = materials.filter(m => {
                            if (!filterTerm) return true;
                            const text = `${m.material_id} ${m.sku_id || ''} ${m.current_container_id || ''} ${m.current_zone || ''} ${m.status || ''}`.toLowerCase();
                            return text.includes(filterTerm);
                        });

                        if (badgeEl) badgeEl.innerText = `${materials.length} Traced`;

                        if (filtered.length === 0) {
                            listEl.innerHTML = `
                                <div style="padding:2rem; text-align:center; color:var(--text-muted); font-size:0.8rem;">
                                    ${filterTerm ? 'No materials match filter.' : 'No materials currently tracked. Start runtime or ingest movement events.'}
                                </div>
                            `;
                            return;
                        }

                        let html = '';
                        filtered.forEach(mat => {
                            let confColor = '#10b981';
                            if (mat.confidence_level === 'INFERRED_PROXIMITY') confColor = '#f59e0b';
                            else if (mat.confidence_level === 'AMBIGUOUS' || mat.confidence_level === 'CONFLICTED') confColor = '#ef4444';

                            const statusColor = mat.status === 'STATIONARY' ? '#10b981' : (mat.status === 'IN_TRANSIT' ? '#0284c7' : '#8b5cf6');

                            html += `
                                <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:8px; padding:10px; display:flex; justify-content:space-between; align-items:center; gap:8px;">
                                    <div style="display:flex; flex-direction:column; gap:3px; min-width:0; flex:1;">
                                        <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                            <strong style="color:var(--primary-navy); font-size:0.85rem;">${escapeHtml(mat.material_id)}</strong>
                                            <span class="badge" style="background:#0284c7; color:#fff; font-size:0.65rem; padding:1px 5px;">${escapeHtml(mat.sku_id || 'UNKNOWN_SKU')}</span>
                                            <span class="badge" style="background:${statusColor}; color:#fff; font-size:0.65rem; padding:1px 5px;">${escapeHtml(mat.status || 'UNKNOWN')}</span>
                                        </div>
                                        <div style="font-size:0.73rem; color:var(--text-muted); display:flex; gap:10px; flex-wrap:wrap;">
                                            <span>📍 ${escapeHtml(mat.current_zone || mat.current_location || 'Unknown')}</span>
                                            <span>📦 ${escapeHtml(mat.current_container_id || 'No Container')}</span>
                                            <span>📹 ${escapeHtml(mat.last_camera_id || 'N/A')}</span>
                                        </div>
                                    </div>
                                    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
                                        <span class="badge" style="background:${confColor}; color:#fff; font-size:0.62rem; padding:2px 6px;">${escapeHtml(mat.confidence_level || 'DETECTED')}</span>
                                        <button type="button" class="btn-secondary" onclick="openDashboardMaterialDossier('${escapeHtml(mat.material_id)}')" style="font-size:0.72rem; padding:2px 8px;">Dossier</button>
                                    </div>
                                </div>
                            `;
                        });
                        listEl.innerHTML = html;
                    }

                    function filterDashboardMaterials() {
                        const input = document.getElementById('dashMaterialSearch');
                        if (input) {
                            dashMaterialSearchTerm = input.value;
                            if (dashLatestData && dashLatestData.active_materials) {
                                renderDashboardMaterials(dashLatestData.active_materials);
                            }
                        }
                    }

                    function renderDashboardZoneMatrix(zones) {
                        const container = document.getElementById('dashZoneMatrix');
                        if (!container) return;

                        if (zones.length === 0) {
                            container.innerHTML = `<div style="padding:1rem; text-align:center; color:var(--text-muted); font-size:0.75rem;">No zones configured. Add zones in Warehouse Zones & ROI.</div>`;
                            return;
                        }

                        let html = '';
                        zones.forEach(z => {
                            const isOccupied = z.is_occupied;
                            const occColor = isOccupied ? '#10b981' : '#64748b';
                            const bg = isOccupied ? 'rgba(16, 185, 129, 0.08)' : 'var(--panel-bg)';
                            const border = isOccupied ? '#10b981' : 'var(--border-light)';

                            html += `
                                <div style="background:${bg}; border:1px solid ${border}; border-radius:8px; padding:8px 10px; display:flex; justify-content:space-between; align-items:center;">
                                    <div>
                                        <div style="display:flex; align-items:center; gap:6px;">
                                            <span style="width:7px; height:7px; border-radius:50%; background:${occColor};"></span>
                                            <strong style="font-size:0.8rem; color:var(--text-main);">${escapeHtml(z.name || z.zone_code)}</strong>
                                            <span style="font-size:0.68rem; color:var(--text-muted); text-transform:uppercase;">(${escapeHtml(z.type || 'ROI')})</span>
                                        </div>
                                        <div style="font-size:0.72rem; color:var(--text-muted); margin-top:2px;">
                                            ${z.track_count || 0} tracked objects &bull; ${z.materials ? z.materials.length : 0} materials
                                        </div>
                                    </div>
                                    <div>
                                        <span class="badge" style="background:${occColor}; color:#fff; font-size:0.65rem; padding:2px 6px;">
                                            ${isOccupied ? `OCCUPIED (${z.track_count})` : 'CLEAR'}
                                        </span>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    }

                    function renderDashboardEventStream(events) {
                        const container = document.getElementById('dashEventStream');
                        if (!container) return;

                        if (events.length === 0) {
                            container.innerHTML = `<div style="padding:1rem; text-align:center; color:var(--text-muted); font-size:0.75rem;">No recent movement events recorded.</div>`;
                            return;
                        }

                        let html = '';
                        events.slice(0, 15).forEach(ev => {
                            let typeColor = '#0284c7';
                            if (ev.event_type === 'ZONE_ENTER') typeColor = '#10b981';
                            else if (ev.event_type === 'ZONE_EXIT') typeColor = '#f59e0b';
                            else if (ev.event_type === 'DWELL_DETECTED') typeColor = '#8b5cf6';
                            else if (ev.event_type === 'CROSS_CAMERA_HANDOFF') typeColor = '#ec4899';
                            else if (ev.event_type === 'ANOMALOUS_SPEED') typeColor = '#ef4444';

                            const tsStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : '';

                            html += `
                                <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:6px; padding:6px 10px; font-size:0.75rem;">
                                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
                                        <span class="badge" style="background:${typeColor}; color:#fff; font-size:0.65rem; padding:1px 5px;">${escapeHtml(ev.event_type)}</span>
                                        <span style="font-size:0.68rem; color:var(--text-muted);">${escapeHtml(tsStr)}</span>
                                    </div>
                                    <div style="color:var(--text-main); font-weight:600;">
                                        ${escapeHtml(ev.primary_class || 'OBJECT')} #${escapeHtml(String(ev.primary_track_id || ''))}
                                        ${ev.zone ? `<span style="font-weight:normal; color:var(--text-muted);"> in <strong>${escapeHtml(ev.zone)}</strong></span>` : ''}
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    }

                    function renderDashboardAssociations(assocs) {
                        const container = document.getElementById('dashAssociationsList');
                        if (!container) return;

                        if (assocs.length === 0) {
                            container.innerHTML = `<div style="padding:1rem; text-align:center; color:var(--text-muted); font-size:0.75rem;">No active associations formed.</div>`;
                            return;
                        }

                        let html = '';
                        assocs.slice(0, 15).forEach(a => {
                            let statusColor = '#10b981';
                            if (a.status === 'CANDIDATE') statusColor = '#0284c7';
                            else if (a.status === 'AMBIGUOUS' || a.status === 'BROKEN') statusColor = '#ef4444';

                            const pCls = a.primary_class || 'PRIMARY';
                            const sCls = a.secondary_class || 'SECONDARY';
                            const pId = a.primary_track_id;
                            const sId = a.secondary_track_id;

                            html += `
                                <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:6px; padding:6px 10px; font-size:0.75rem; display:flex; justify-content:space-between; align-items:center;">
                                    <div>
                                        <div style="display:flex; align-items:center; gap:6px;">
                                            <strong style="color:#0284c7; font-size:0.72rem;">${escapeHtml(a.association_type || 'ASSOC')}</strong>
                                            <span class="badge" style="background:${statusColor}; color:#fff; font-size:0.62rem; padding:1px 4px;">${escapeHtml(a.status)}</span>
                                        </div>
                                        <div style="color:var(--text-main); margin-top:2px;">
                                            ${escapeHtml(pCls)} #${pId} ↔ ${escapeHtml(sCls)} #${sId}
                                        </div>
                                    </div>
                                    <div style="text-align:right; font-size:0.7rem; color:var(--text-muted);">
                                        <div>Conf: ${(a.confidence_score !== undefined ? a.confidence_score : 1.0).toFixed(2)}</div>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    }

                    function renderDashboardAlerts(alerts) {
                        const container = document.getElementById('dashAlertsList');
                        if (!container) return;

                        if (alerts.length === 0) {
                            container.innerHTML = `
                                <div style="padding:1rem; text-align:center; color:var(--text-muted); font-size:0.75rem; display:flex; align-items:center; justify-content:center; gap:6px;">
                                    <span style="color:#10b981;">✓</span> All vision systems operating nominally.
                                </div>
                            `;
                            return;
                        }

                        let html = '';
                        alerts.forEach(al => {
                            let border = '#f59e0b';
                            let bg = 'rgba(245, 158, 11, 0.08)';
                            let tagColor = '#f59e0b';
                            if (al.severity === 'DANGER' || al.severity === 'ERROR') {
                                border = '#ef4444';
                                bg = 'rgba(239, 68, 68, 0.08)';
                                tagColor = '#ef4444';
                            } else if (al.severity === 'INFO') {
                                border = '#0284c7';
                                bg = 'rgba(2, 132, 199, 0.08)';
                                tagColor = '#0284c7';
                            }

                            html += `
                                <div style="background:${bg}; border-left:3px solid ${border}; border-top:1px solid var(--border-light); border-right:1px solid var(--border-light); border-bottom:1px solid var(--border-light); border-radius:4px; padding:6px 10px; font-size:0.75rem;">
                                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
                                        <strong style="color:${tagColor}; font-size:0.72rem;">${escapeHtml(al.code || al.title || 'ALERT')}</strong>
                                        <span style="font-size:0.65rem; color:var(--text-muted);">${escapeHtml(al.camera_id || '')}</span>
                                    </div>
                                    <div style="color:var(--text-main);">${escapeHtml(al.message || '')}</div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    }

                    // Master Runtime Button Action Handlers
                    async function handleDashboardStartAll() {
                        try {
                            const btn = document.getElementById('btnDashStartAll');
                            if (btn) btn.disabled = true;
                            const res = await fetch('/api/vision/runtime/start_all', { method: 'POST' });
                            const json = await res.json();
                            if (json.success) {
                                await loadLiveVisionDashboard(true);
                            } else {
                                alert('Failed to start vision runtime: ' + (json.error || 'Unknown error'));
                            }
                        } catch (e) {
                            console.error(e);
                        } finally {
                            const btn = document.getElementById('btnDashStartAll');
                            if (btn) btn.disabled = false;
                        }
                    }

                    async function handleDashboardStopAll() {
                        try {
                            const btn = document.getElementById('btnDashStopAll');
                            if (btn) btn.disabled = true;
                            const res = await fetch('/api/vision/runtime/stop_all', { method: 'POST' });
                            const json = await res.json();
                            if (json.success) {
                                await loadLiveVisionDashboard(true);
                            } else {
                                alert('Failed to stop vision runtime: ' + (json.error || 'Unknown error'));
                            }
                        } catch (e) {
                            console.error(e);
                        } finally {
                            const btn = document.getElementById('btnDashStopAll');
                            if (btn) btn.disabled = false;
                        }
                    }

                    async function handleDashboardRestartCurrentCamera() {
                        if (!dashSelectedCameraId) {
                            alert('Please select a camera node first.');
                            return;
                        }
                        try {
                            await fetch('/api/vision/runtime/stop', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({ camera_id: dashSelectedCameraId })
                            });
                            await fetch('/api/vision/runtime/start', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({ camera_id: dashSelectedCameraId })
                            });
                            await loadLiveVisionDashboard(true);
                        } catch (e) {
                            console.error(e);
                        }
                    }

                    async function handleDashboardTestStep() {
                        try {
                            const btn = document.getElementById('btnDashTestStep');
                            if (btn) btn.disabled = true;
                            const payload = dashSelectedCameraId ? { camera_id: dashSelectedCameraId } : {};
                            const res = await fetch('/api/vision/runtime/test_step', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify(payload)
                            });
                            const json = await res.json();
                            if (json.success) {
                                await loadLiveVisionDashboard(true);
                            } else {
                                alert('Test step failed: ' + (json.error || 'Unknown error'));
                            }
                        } catch (e) {
                            console.error(e);
                        } finally {
                            const btn = document.getElementById('btnDashTestStep');
                            if (btn) btn.disabled = false;
                        }
                    }

                    // Material Dossier In-Place Modal Handlers
                    async function openDashboardMaterialDossier(materialId) {
                        const modal = document.getElementById('dashMaterialModal');
                        const content = document.getElementById('dashModalContent');
                        const titleEl = document.getElementById('dashModalMatTitle');
                        const badgeEl = document.getElementById('dashModalMatLevelBadge');
                        if (!modal || !content) return;

                        if (titleEl) titleEl.innerText = `Material Dossier: ${materialId}`;
                        content.innerHTML = `<div style="padding:2rem; text-align:center; color:var(--text-muted);">Loading material dossier...</div>`;
                        modal.style.display = 'flex';

                        try {
                            const res = await fetch(`/api/vision/traceability/${encodeURIComponent(materialId)}`);
                            if (!res.ok) {
                                content.innerHTML = `<div style="padding:2rem; text-align:center; color:#ef4444;">Failed to load dossier for material ${escapeHtml(materialId)}.</div>`;
                                return;
                            }
                            const data = await res.json();
                            const mat = data.material || {};
                            const events = data.timeline || [];
                            const custody = data.custody_chain || [];

                            if (badgeEl) {
                                badgeEl.innerText = mat.confidence_level || 'DETECTED';
                                let bColor = '#10b981';
                                if (mat.confidence_level === 'INFERRED_PROXIMITY') bColor = '#f59e0b';
                                else if (mat.confidence_level === 'AMBIGUOUS' || mat.confidence_level === 'CONFLICTED') bColor = '#ef4444';
                                badgeEl.style.background = bColor;
                            }

                            let custodyHtml = '';
                            if (custody.length > 0) {
                                custody.forEach(c => {
                                    custodyHtml += `<span class="badge" style="background:var(--panel-subtle); color:var(--text-main); border:1px solid var(--border-light); font-size:0.75rem; padding:4px 8px;">${escapeHtml(c.holder_type)}: <strong>${escapeHtml(c.holder_id)}</strong></span>`;
                                });
                            } else {
                                custodyHtml = `<span style="color:var(--text-muted); font-size:0.75rem;">Direct custody / standalone</span>`;
                            }

                            let eventsHtml = '';
                            if (events.length > 0) {
                                events.forEach(ev => {
                                    const tsStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : '';
                                    eventsHtml += `
                                        <div style="background:var(--panel-subtle); border-left:3px solid #0284c7; padding:8px 12px; border-radius:4px; font-size:0.78rem;">
                                            <div style="display:flex; justify-content:space-between; margin-bottom:2px;">
                                                <strong style="color:var(--primary-navy);">${escapeHtml(ev.event_type)}</strong>
                                                <span style="color:var(--text-muted);">${escapeHtml(tsStr)}</span>
                                            </div>
                                            <div style="color:var(--text-muted);">
                                                Zone: <strong>${escapeHtml(ev.zone || 'None')}</strong> &bull; Camera: <strong>${escapeHtml(ev.camera_id || 'N/A')}</strong>
                                            </div>
                                            ${ev.notes ? `<div style="margin-top:2px; font-style:italic; color:var(--text-main);">${escapeHtml(ev.notes)}</div>` : ''}
                                        </div>
                                    `;
                                });
                            } else {
                                eventsHtml = `<div style="color:var(--text-muted); font-size:0.75rem;">No lifecycle events recorded.</div>`;
                            }

                            content.innerHTML = `
                                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:1rem; font-size:0.8rem;">
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">SKU Identifier</div>
                                        <div style="font-size:1rem; font-weight:700; color:var(--primary-navy);">${escapeHtml(mat.sku_id || 'UNKNOWN_SKU')}</div>
                                    </div>
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">Operational Status</div>
                                        <div style="font-size:1rem; font-weight:700; color:#10b981;">${escapeHtml(mat.status || 'UNKNOWN')}</div>
                                    </div>
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">Current Zone & Location</div>
                                        <div style="font-size:0.9rem; font-weight:600; color:var(--text-main);">${escapeHtml(mat.current_zone || mat.current_location || 'Unknown')}</div>
                                    </div>
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">Current Container</div>
                                        <div style="font-size:0.9rem; font-weight:600; color:var(--text-main);">${escapeHtml(mat.current_container_id || 'No Container')}</div>
                                    </div>
                                </div>

                                <div style="margin-bottom:1rem;">
                                    <div style="font-weight:700; font-size:0.82rem; color:var(--primary-navy); margin-bottom:6px;">Custody Chain:</div>
                                    <div style="display:flex; gap:6px; flex-wrap:wrap;">${custodyHtml}</div>
                                </div>

                                <div>
                                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                                        <span style="font-weight:700; font-size:0.82rem; color:var(--primary-navy);">Movement Timeline:</span>
                                        <button type="button" class="btn-secondary" onclick="jumpToTraceabilitySubTab('${escapeHtml(materialId)}')" style="font-size:0.72rem; padding:2px 8px;">Open Full Traceability Tab &rarr;</button>
                                    </div>
                                    <div style="display:flex; flex-direction:column; gap:6px; max-height:220px; overflow-y:auto;">${eventsHtml}</div>
                                </div>
                            `;
                        } catch (e) {
                            console.error(e);
                            content.innerHTML = `<div style="padding:2rem; text-align:center; color:#ef4444;">Error loading dossier: ${escapeHtml(e.message)}</div>`;
                        }
                    }

                    function closeDashboardMaterialModal() {
                        const modal = document.getElementById('dashMaterialModal');
                        if (modal) modal.style.display = 'none';
                    }

                    function jumpToTraceabilitySubTab(materialId) {
                        closeDashboardMaterialModal();
                        const btn = document.querySelector(".vision-sub-btn[onclick*='vision-traceability']");
                        switchVisionSubTab('vision-traceability', btn);
                        if (typeof handleTraceabilityMaterialSelect === 'function') {
                            setTimeout(() => handleTraceabilityMaterialSelect(materialId), 200);
                        }
                    }

                    // ========================================================================
                    // PART 13 — CONTROLLED ACTIONS FRONTEND LOGIC
                    // ========================================================================

                    let ctrlCurrentPreview = null;

                    function renderControlledActions(recommendations) {
                        const container = document.getElementById('dashControlledActionsList');
                        const badge = document.getElementById('ctrlActionCountBadge');
                        if (!container) return;

                        if (badge) {
                            badge.innerText = `${recommendations.length} PENDING`;
                            badge.style.background = recommendations.length > 0 ? '#f59e0b' : '#0284c7';
                        }

                        if (!recommendations || recommendations.length === 0) {
                            container.innerHTML = `
                                <div style="padding:1.5rem; text-align:center; color:var(--text-muted); font-size:0.8rem; grid-column:1/-1;">
                                    No pending action recommendations. Physical operations operating nominally.
                                </div>
                            `;
                            return;
                        }

                        let html = '';
                        recommendations.forEach((r, idx) => {
                            let typeColor = '#0284c7';
                            if (r.action_type === 'PUTAWAY') typeColor = '#10b981';
                            else if (r.action_type === 'CYCLE_COUNT') typeColor = '#f59e0b';
                            else if (r.action_type === 'DISPATCH') typeColor = '#8b5cf6';

                            const stateColor = r.state === 'READY_FOR_APPROVAL' ? '#f59e0b' : '#06b6d4';

                            html += `
                                <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:8px; padding:12px; display:flex; flex-direction:column; justify-content:space-between; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
                                    <div>
                                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                                            <span class="badge" style="background:${typeColor}; color:#fff; font-size:0.7rem; font-weight:700;">${escapeHtml(r.action_type)}</span>
                                            <span class="badge" style="background:${stateColor}; color:#fff; font-size:0.68rem;">${escapeHtml(r.state)}</span>
                                        </div>
                                        <div style="font-weight:700; font-size:0.85rem; color:var(--primary-navy); margin-bottom:4px;">
                                            ${escapeHtml(r.title || r.entity_id)}
                                        </div>
                                        <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:6px;">
                                            SKU: <strong style="color:var(--text-main);">${escapeHtml(r.material_sku || 'N/A')}</strong> &bull; Qty: <strong style="color:var(--text-main);">${escapeHtml(String(r.recommended_quantity || 1))}</strong>
                                        </div>
                                        <div style="font-size:0.74rem; color:var(--text-muted); margin-bottom:6px;">
                                            Src: ${escapeHtml(r.source || 'N/A')} &rarr; Dst: ${escapeHtml(r.destination || 'N/A')}
                                        </div>
                                        <div style="background:var(--panel-subtle); border-left:3px solid ${typeColor}; padding:5px 8px; border-radius:4px; font-size:0.72rem; color:var(--text-main); margin-bottom:10px;">
                                            ✓ ${escapeHtml(r.evidence_summary || 'Evidence verified')}
                                        </div>
                                    </div>
                                    <div>
                                        <button type="button" class="btn-primary" style="width:100%; font-size:0.78rem; padding:6px 10px; display:flex; justify-content:center; align-items:center; gap:6px;"
                                            onclick='openControlledActionPreview(${JSON.stringify(r.action_type)}, ${JSON.stringify(r.entity_id)}, ${JSON.stringify(r)})'>
                                            <span>🔍 Inspect &amp; Authorize</span>
                                        </button>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    }

                    async function refreshControlledActions() {
                        try {
                            const res = await fetch('/api/wms/controlled_actions/recommendations');
                            if (!res.ok) return;
                            const data = await res.json();
                            renderControlledActions(data.recommendations || []);
                        } catch (e) {
                            console.error('[ControlledActions] Refresh failed:', e);
                        }
                    }

                    async function openControlledActionPreview(actionType, entityId, initialParams) {
                        const modal = document.getElementById('dashControlledActionModal');
                        const content = document.getElementById('ctrlModalContent');
                        const titleEl = document.getElementById('ctrlModalTitle');
                        const stateBadge = document.getElementById('ctrlModalStateBadge');
                        if (!modal || !content) return;

                        if (titleEl) titleEl.innerText = `Controlled Action Preview: ${actionType} (${entityId})`;
                        if (stateBadge) {
                            stateBadge.innerText = 'EVALUATING';
                            stateBadge.style.background = '#64748b';
                        }

                        content.innerHTML = `<div style="padding:2.5rem; text-align:center; color:var(--text-muted);">Evaluating authoritative WMS validation gates and evidence...</div>`;
                        modal.style.display = 'flex';

                        try {
                            const payload = {
                                action_type: actionType,
                                entity_id: entityId,
                                params: initialParams || {}
                            };
                            const res = await fetch('/api/wms/controlled_actions/preview', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });
                            const data = await res.json();
                            if (!res.ok || !data.success) {
                                content.innerHTML = `<div style="padding:2rem; text-align:center; color:#ef4444;">Preview generation failed: ${escapeHtml(data.error || 'Server error')}</div>`;
                                return;
                            }

                            const preview = data.preview || {};
                            ctrlCurrentPreview = preview;

                            if (stateBadge) {
                                stateBadge.innerText = preview.state || 'READY_FOR_APPROVAL';
                                stateBadge.style.background = preview.state === 'READY_FOR_APPROVAL' ? '#10b981' : (preview.state === 'FAILED' ? '#ef4444' : '#f59e0b');
                            }

                            const gates = preview.validation_gates || {};
                            const canAuth = gates.can_authorize;
                            const errors = gates.errors || [];
                            const warnings = gates.warnings || [];

                            let gateItemsHtml = `
                                <div style="display:flex; flex-direction:column; gap:4px; font-size:0.78rem;">
                                    <div style="display:flex; align-items:center; gap:6px;">
                                        <span style="color:${canAuth ? '#10b981' : '#ef4444'}; font-weight:700;">${canAuth ? '✓' : '✗'}</span>
                                        <span>Master Data Identity Validation: <strong>${canAuth ? 'PASSED' : 'FAILED'}</strong></span>
                                    </div>
                                    <div style="display:flex; align-items:center; gap:6px;">
                                        <span style="color:${errors.length === 0 ? '#10b981' : '#ef4444'}; font-weight:700;">${errors.length === 0 ? '✓' : '✗'}</span>
                                        <span>Capacity &amp; Boundary Constraints: <strong>${errors.length === 0 ? 'CLEAR' : 'ERROR'}</strong></span>
                                    </div>
                                    <div style="display:flex; align-items:center; gap:6px;">
                                        <span style="color:#10b981; font-weight:700;">✓</span>
                                        <span>Authoritative WMS Transaction Bound: <strong>COMPATIBLE</strong></span>
                                    </div>
                                </div>
                            `;

                            let alertsHtml = '';
                            if (errors.length > 0) {
                                alertsHtml += `<div style="background:rgba(239, 68, 68, 0.1); border-left:4px solid #ef4444; padding:8px 12px; border-radius:4px; font-size:0.78rem; color:#ef4444; margin-bottom:10px;"><strong>Validation Errors:</strong> ${escapeHtml(errors.join(', '))}</div>`;
                            }
                            if (warnings.length > 0) {
                                alertsHtml += `<div style="background:rgba(245, 158, 11, 0.1); border-left:4px solid #f59e0b; padding:8px 12px; border-radius:4px; font-size:0.78rem; color:#f59e0b; margin-bottom:10px;"><strong>Operational Warnings:</strong> ${escapeHtml(warnings.join(', '))}</div>`;
                            }

                            content.innerHTML = `
                                ${alertsHtml}
                                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:1rem; font-size:0.8rem;">
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">Material / SKU</div>
                                        <div style="font-size:1.05rem; font-weight:700; color:var(--primary-navy);">${escapeHtml(preview.material_sku || 'N/A')}</div>
                                    </div>
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">Quantity &amp; UoM</div>
                                        <div style="font-size:1.05rem; font-weight:700; color:#10b981;">${escapeHtml(String(preview.quantity))} ${escapeHtml(preview.uom || 'Units')}</div>
                                    </div>
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">Origin / Source</div>
                                        <div style="font-size:0.88rem; font-weight:600; color:var(--text-main);">${escapeHtml(preview.source || 'N/A')}</div>
                                    </div>
                                    <div style="background:var(--panel-subtle); padding:10px; border-radius:8px; border:1px solid var(--border-light);">
                                        <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase;">Target Destination</div>
                                        <div style="font-size:0.88rem; font-weight:600; color:var(--text-main);">${escapeHtml(preview.destination || 'N/A')}</div>
                                    </div>
                                </div>

                                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:1rem;">
                                    <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:8px; padding:10px;">
                                        <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Current Expected WMS State:</div>
                                        <pre style="background:var(--panel-subtle); padding:8px; border-radius:4px; font-size:0.72rem; margin:0; overflow-x:auto;">${escapeHtml(JSON.stringify(preview.expected_wms_state, null, 2))}</pre>
                                    </div>
                                    <div style="background:var(--panel-bg); border:1px solid var(--border-light); border-radius:8px; padding:10px;">
                                        <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#10b981; margin-bottom:6px;">Projected Resulting WMS State:</div>
                                        <pre style="background:var(--panel-subtle); padding:8px; border-radius:4px; font-size:0.72rem; margin:0; overflow-x:auto;">${escapeHtml(JSON.stringify(preview.projected_wms_state, null, 2))}</pre>
                                    </div>
                                </div>

                                <div style="background:var(--panel-subtle); border:1px solid var(--border-light); border-radius:8px; padding:10px; margin-bottom:1rem;">
                                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Validation Gates Evaluation:</div>
                                    ${gateItemsHtml}
                                </div>

                                <div style="background:var(--panel-subtle); border:1px solid var(--border-light); border-radius:8px; padding:10px; margin-bottom:1.2rem;">
                                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px;">Authoritative Core WMS Transaction Call:</div>
                                    <code style="font-family:monospace; font-size:0.8rem; color:#0284c7; font-weight:600;">${escapeHtml(preview.exact_wms_operation || 'None')}</code>
                                </div>

                                <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid var(--border-light); padding-top:1rem; flex-wrap:wrap; gap:10px;">
                                    <div style="display:flex; align-items:center; gap:8px;">
                                        <label style="font-size:0.78rem; font-weight:700; color:var(--text-muted); margin:0;">Operator ID:</label>
                                        <input type="text" id="ctrlOperatorInput" value="operator_admin" style="font-size:0.78rem; padding:4px 8px; width:130px; margin:0;" />
                                    </div>
                                    <div style="display:flex; align-items:center; gap:8px;">
                                        <button type="button" class="btn-secondary" onclick="rejectControlledAction('${escapeHtml(actionType)}', '${escapeHtml(entityId)}')" style="font-size:0.8rem; padding:6px 12px; color:#ef4444;">
                                            ✕ Reject Action
                                        </button>
                                        <button type="button" class="btn-primary" id="btnCommitCtrlAction" onclick="commitControlledAction('${escapeHtml(actionType)}', '${escapeHtml(entityId)}')" ${canAuth ? '' : 'disabled'} style="font-size:0.8rem; padding:6px 16px; background:#10b981; border-color:#10b981;">
                                            ✓ Authorize &amp; Commit WMS Transaction
                                        </button>
                                    </div>
                                </div>
                            `;
                        } catch (e) {
                            console.error('[ControlledActions] Preview error:', e);
                            content.innerHTML = `<div style="padding:2rem; text-align:center; color:#ef4444;">Error generating preview: ${escapeHtml(e.message)}</div>`;
                        }
                    }

                    function closeControlledActionModal() {
                        const modal = document.getElementById('dashControlledActionModal');
                        if (modal) modal.style.display = 'none';
                    }

                    async function commitControlledAction(actionType, entityId) {
                        const btn = document.getElementById('btnCommitCtrlAction');
                        const opInput = document.getElementById('ctrlOperatorInput');
                        const opId = opInput ? (opInput.value.trim() || 'operator_admin') : 'operator_admin';
                        const content = document.getElementById('ctrlModalContent');
                        const stateBadge = document.getElementById('ctrlModalStateBadge');

                        if (btn) btn.disabled = true;

                        try {
                            const idempotencyKey = `ACT-${actionType}-${entityId}-${Date.now()}`;
                            const payload = {
                                action_type: actionType,
                                entity_id: entityId,
                                params: (ctrlCurrentPreview && ctrlCurrentPreview.params) || {},
                                operator_id: opId,
                                idempotency_key: idempotencyKey
                            };

                            const res = await fetch('/api/wms/controlled_actions/execute', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });
                            const data = await res.json();

                            if (stateBadge) {
                                stateBadge.innerText = data.status || 'EXECUTED';
                                stateBadge.style.background = data.success ? '#10b981' : '#ef4444';
                            }

                            if (data.success) {
                                content.innerHTML = `
                                    <div style="padding:1.5rem; text-align:center;">
                                        <div style="font-size:2.5rem; color:#10b981; margin-bottom:8px;">✓</div>
                                        <h3 style="margin:0 0 6px 0; color:var(--primary-navy);">WMS Transaction Committed Successfully</h3>
                                        <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem;">
                                            ${escapeHtml(data.message || 'Inventory updated by authoritative WMS database function.')}
                                        </p>
                                        <div style="background:var(--panel-subtle); border:1px solid var(--border-light); border-radius:8px; padding:12px; text-align:left; font-size:0.75rem; margin-bottom:1.5rem;">
                                            <div><strong>Operation:</strong> ${escapeHtml((data.wms_transaction || {}).operation || 'Completed')}</div>
                                            <div><strong>Authorized By:</strong> ${escapeHtml(data.operator_id || opId)}</div>
                                            <div><strong>Idempotency Key:</strong> ${escapeHtml(data.idempotency_key || idempotencyKey)}</div>
                                            <div><strong>Executed At:</strong> ${escapeHtml(data.executed_at || 'Now')}</div>
                                        </div>
                                        <button type="button" class="btn-primary" onclick="closeControlledActionModal(); refreshControlledActions(); loadLiveVisionDashboard(true);" style="font-size:0.85rem; padding:8px 20px;">
                                            Done
                                        </button>
                                    </div>
                                `;
                            } else {
                                content.innerHTML = `
                                    <div style="padding:1.5rem; text-align:center;">
                                        <div style="font-size:2.5rem; color:#ef4444; margin-bottom:8px;">✕</div>
                                        <h3 style="margin:0 0 6px 0; color:#ef4444;">Transaction Authorization Failed</h3>
                                        <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1.5rem;">
                                            ${escapeHtml(data.message || 'Validation gate failed or unauthorized action.')}
                                        </p>
                                        <button type="button" class="btn-secondary" onclick="closeControlledActionModal();" style="font-size:0.85rem; padding:8px 20px;">
                                            Close
                                        </button>
                                    </div>
                                `;
                            }
                        } catch (e) {
                            console.error('[ControlledActions] Execution error:', e);
                            if (content) content.innerHTML = `<div style="padding:2rem; text-align:center; color:#ef4444;">Execution error: ${escapeHtml(e.message)}</div>`;
                        }
                    }

                    async function rejectControlledAction(actionType, entityId) {
                        const reason = prompt("Please provide a reason for rejecting this AI recommendation:", "Operator visual discrepancy override");
                        if (reason === null) return; // User cancelled prompt

                        const opInput = document.getElementById('ctrlOperatorInput');
                        const opId = opInput ? (opInput.value.trim() || 'operator_admin') : 'operator_admin';
                        const content = document.getElementById('ctrlModalContent');
                        const stateBadge = document.getElementById('ctrlModalStateBadge');

                        try {
                            const res = await fetch('/api/wms/controlled_actions/reject', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    action_type: actionType,
                                    entity_id: entityId,
                                    reason: reason,
                                    operator_id: opId
                                })
                            });
                            const data = await res.json();
                            if (stateBadge) {
                                stateBadge.innerText = 'REJECTED';
                                stateBadge.style.background = '#64748b';
                            }
                            if (content) {
                                content.innerHTML = `
                                    <div style="padding:1.5rem; text-align:center;">
                                        <div style="font-size:2rem; color:#64748b; margin-bottom:8px;">🚫</div>
                                        <h3 style="margin:0 0 6px 0; color:var(--primary-navy);">Action Explicitly Rejected</h3>
                                        <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem;">
                                            Rejection recorded in authoritative audit trail with reason: "${escapeHtml(reason)}"
                                        </p>
                                        <button type="button" class="btn-secondary" onclick="closeControlledActionModal(); refreshControlledActions();" style="font-size:0.85rem; padding:8px 20px;">
                                            Close
                                        </button>
                                    </div>
                                `;
                            }
                        } catch (e) {
                            console.error('[ControlledActions] Rejection error:', e);
                        }
                    }

                    // Auto-initialize dashboard when page loads if dashboard tab is active
                    document.addEventListener('DOMContentLoaded', () => {
                        const dashSub = document.getElementById('vision-dashboard-sub');
                        if (dashSub && dashSub.style.display !== 'none') {
                            initLiveVisionDashboard();
                        }
                    });