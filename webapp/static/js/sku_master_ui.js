/**
 * Skantha WMS — AI Vision: SKU Master Data & Product Image Mapping UI
 * Phase 3: Interactive master data table, 3-step Excel import wizard,
 * and bulk filename-based product image mapping.
 */

(function () {
    let currentPage = 1;
    let currentLimit = 15;
    let totalPages = 1;
    let selectedSkuForImages = null;
    let validatedExcelRows = [];
    let currentDuplicatePolicy = 'skip';
    let bulkImageFiles = [];
    let bulkImageMatches = [];

    // Initialize once DOM is ready
    window.addEventListener('DOMContentLoaded', () => {
        // Wire search input debouncing
        const searchInput = document.getElementById('skuMasterSearchInput');
        if (searchInput) {
            let debounceTimer;
            searchInput.addEventListener('input', () => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    currentPage = 1;
                    fetchSkuMaster();
                }, 300);
            });
        }
    });

    // -------------------------------------------------------------------------
    // 1. Fetch and Render SKU Master Records
    // -------------------------------------------------------------------------
    async function fetchSkuMaster(page = null) {
        if (page !== null) currentPage = page;
        const tbody = document.getElementById('skuMasterTableBody');
        const emptyState = document.getElementById('skuMasterEmptyState');
        const searchVal = document.getElementById('skuMasterSearchInput')?.value || '';
        const catVal = document.getElementById('skuMasterCategoryFilter')?.value || '';
        const statusVal = document.getElementById('skuMasterStatusFilter')?.value || '';
        const imgVal = document.getElementById('skuMasterImageFilter')?.value || '';

        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:var(--text-muted);"><i class="fas fa-spinner fa-spin" style="margin-right:8px;"></i> Loading SKU master records...</td></tr>`;
        }

        try {
            const params = new URLSearchParams({
                search: searchVal,
                category: catVal,
                status: statusVal,
                image_status: imgVal,
                page: currentPage,
                limit: currentLimit
            });

            const res = await fetch(`/api/sku_master?${params.toString()}`);
            const data = await res.json();

            if (!data.success) {
                if (tbody) tbody.innerHTML = `<tr><td colspan="8" style="color:#ef4444; text-align:center; padding:1.5rem;">Error loading SKU records: ${data.message || 'Unknown error'}</td></tr>`;
                return;
            }

            const pageData = data.data || {};
            const items = pageData.items || [];
            totalPages = pageData.total_pages || 1;
            const totalCount = pageData.total_count || 0;

            // Update pagination UI
            const pageInfo = document.getElementById('skuMasterPaginationInfo');
            if (pageInfo) {
                const start = totalCount === 0 ? 0 : (currentPage - 1) * currentLimit + 1;
                const end = Math.min(currentPage * currentLimit, totalCount);
                pageInfo.textContent = `Showing ${start}–${end} of ${totalCount} SKUs`;
            }

            const btnPrev = document.getElementById('skuMasterBtnPrev');
            const btnNext = document.getElementById('skuMasterBtnNext');
            if (btnPrev) btnPrev.disabled = (currentPage <= 1);
            if (btnNext) btnNext.disabled = (currentPage >= totalPages);

            // Populate category filter options if empty
            populateCategoryFilter(items);

            if (items.length === 0) {
                if (tbody) tbody.innerHTML = '';
                if (emptyState) emptyState.style.display = 'block';
                return;
            }

            if (emptyState) emptyState.style.display = 'none';

            let html = '';
            items.forEach(sku => {
                const safeSkuId = escapeHtml(sku.sku_id);
                const safeName = escapeHtml(sku.name);
                const safeDesc = escapeHtml(sku.description || '—');
                const safeCat = escapeHtml(sku.category || 'General');
                const safeUom = escapeHtml(sku.uom || 'EA');
                const statusBadge = sku.status === 'Active'
                    ? `<span style="background:rgba(16,185,129,0.15); color:#059669; border:1px solid rgba(16,185,129,0.3); padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;">Active</span>`
                    : `<span style="background:rgba(148,163,184,0.15); color:#64748b; border:1px solid rgba(148,163,184,0.3); padding:2px 8px; border-radius:12px; font-size:0.75rem;">Disabled</span>`;

                const imgCount = sku.image_count || 0;
                let imgThumbnail = '';
                if (sku.primary_image_path) {
                    imgThumbnail = `
                        <div style="position:relative; width:44px; height:44px; cursor:pointer;" onclick="openSkuImagesModal('${safeSkuId}')" title="Click to view reference images">
                            <img src="${sku.primary_image_path}" alt="${safeSkuId}" style="width:44px; height:44px; object-fit:cover; border-radius:6px; border:1px solid var(--border-light); box-shadow:0 1px 3px rgba(0,0,0,0.1);">
                            ${imgCount > 1 ? `<span style="position:absolute; bottom:-3px; right:-3px; background:#4f46e5; color:#fff; font-size:0.65rem; font-weight:bold; border-radius:10px; padding:0 4px;">+${imgCount - 1}</span>` : ''}
                        </div>`;
                } else {
                    imgThumbnail = `
                        <div onclick="openSkuImagesModal('${safeSkuId}')" style="width:44px; height:44px; background:var(--panel-subtle); border:1px dashed var(--border-light); border-radius:6px; display:flex; align-items:center; justify-content:center; color:var(--text-muted); cursor:pointer;" title="No reference image mapped — Click to upload">
                            <i class="fas fa-camera" style="font-size:0.9rem;"></i>
                        </div>`;
                }

                const imgStatusBadge = imgCount > 0
                    ? `<span style="color:#059669; font-size:0.75rem; font-weight:600; display:inline-flex; align-items:center; gap:4px;"><i class="fas fa-circle-check"></i> ${imgCount} Mapped</span>`
                    : `<span style="color:#d97706; font-size:0.75rem; font-weight:600; display:inline-flex; align-items:center; gap:4px;"><i class="fas fa-triangle-exclamation"></i> Unmapped</span>`;

                html += `
                    <tr>
                        <td style="width:50px; text-align:center;">${imgThumbnail}</td>
                        <td>
                            <span style="font-family:monospace; font-weight:700; color:var(--primary-navy); background:var(--panel-subtle); padding:2px 6px; border-radius:4px; border:1px solid var(--border-light); font-size:0.85rem;">${safeSkuId}</span>
                        </td>
                        <td>
                            <div style="font-weight:600; color:var(--text-color);">${safeName}</div>
                            <small style="color:var(--text-muted); font-size:0.75rem; display:block; max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${safeDesc}</small>
                        </td>
                        <td><span style="background:rgba(99,102,241,0.08); color:#4f46e5; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600;">${safeCat}</span></td>
                        <td style="font-size:0.8rem; font-weight:600;">${safeUom}</td>
                        <td style="font-size:0.78rem; color:var(--text-muted);">
                            ${sku.unit_weight || 0} kg<br><span style="font-size:0.72rem;">${sku.unit_volume || 0} m³</span>
                        </td>
                        <td>${statusBadge}</td>
                        <td>${imgStatusBadge}</td>
                        <td style="text-align:right; white-space:nowrap;">
                            <div style="display:inline-flex; gap:6px;">
                                <button type="button" class="btn-secondary btn-sm" onclick="openSkuImagesModal('${safeSkuId}')" style="padding:4px 8px; font-size:0.78rem;" title="Upload & Map Images">
                                    <i class="fas fa-images" style="margin-right:3px;"></i> Images
                                </button>
                                <button type="button" class="btn-secondary btn-sm" onclick="openEditSkuModal('${safeSkuId}')" style="padding:4px 8px; font-size:0.78rem;" title="Edit SKU">
                                    <i class="fas fa-pen"></i>
                                </button>
                                <button type="button" class="btn-secondary btn-sm" onclick="confirmDeleteSku('${safeSkuId}')" style="padding:4px 8px; font-size:0.78rem; color:#ef4444;" title="Delete SKU">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            });

            if (tbody) tbody.innerHTML = html;
        } catch (e) {
            console.error('Error fetching SKU master:', e);
            if (tbody) tbody.innerHTML = `<tr><td colspan="8" style="color:#ef4444; text-align:center; padding:1.5rem;">Failed to fetch SKU records: ${e.message}</td></tr>`;
        }
    }

    function populateCategoryFilter(items) {
        const filterSelect = document.getElementById('skuMasterCategoryFilter');
        if (!filterSelect || filterSelect.options.length > 1) return;
        const cats = new Set();
        items.forEach(i => { if (i.category) cats.add(i.category); });
        cats.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c;
            opt.textContent = c;
            filterSelect.appendChild(opt);
        });
    }

    function skuMasterPrevPage() {
        if (currentPage > 1) {
            fetchSkuMaster(currentPage - 1);
        }
    }

    function skuMasterNextPage() {
        if (currentPage < totalPages) {
            fetchSkuMaster(currentPage + 1);
        }
    }

    function resetSkuMasterFilters() {
        if (document.getElementById('skuMasterSearchInput')) document.getElementById('skuMasterSearchInput').value = '';
        if (document.getElementById('skuMasterCategoryFilter')) document.getElementById('skuMasterCategoryFilter').value = '';
        if (document.getElementById('skuMasterStatusFilter')) document.getElementById('skuMasterStatusFilter').value = '';
        if (document.getElementById('skuMasterImageFilter')) document.getElementById('skuMasterImageFilter').value = '';
        fetchSkuMaster(1);
    }

    // -------------------------------------------------------------------------
    // 2. Add / Edit SKU Modal
    // -------------------------------------------------------------------------
    function openAddSkuModal() {
        const modal = document.getElementById('modalAddSku');
        if (!modal) return;
        document.getElementById('formAddSku')?.reset();
        document.getElementById('modalSkuFormTitle').textContent = 'Add SKU Master Record';
        document.getElementById('skuModalCode').readOnly = false;
        document.getElementById('skuModalAlert').style.display = 'none';
        modal.classList.add('active');
    }

    async function openEditSkuModal(skuId) {
        const modal = document.getElementById('modalAddSku');
        if (!modal) return;
        document.getElementById('formAddSku')?.reset();
        document.getElementById('modalSkuFormTitle').textContent = `Edit SKU: ${skuId}`;
        const codeInput = document.getElementById('skuModalCode');
        codeInput.value = skuId;
        codeInput.readOnly = true;
        document.getElementById('skuModalAlert').style.display = 'none';

        try {
            const res = await fetch(`/api/sku_master/${encodeURIComponent(skuId)}`);
            const json = await res.json();
            if (json.success && json.data) {
                const s = json.data;
                document.getElementById('skuModalName').value = s.name || '';
                document.getElementById('skuModalDesc').value = s.description || '';
                document.getElementById('skuModalCategory').value = s.category || 'General';
                document.getElementById('skuModalUom').value = s.uom || 'EA';
                document.getElementById('skuModalWeight').value = s.unit_weight || 0;
                document.getElementById('skuModalVolume').value = s.unit_volume || 0;
                document.getElementById('skuModalStatus').value = s.status || 'Active';
            }
        } catch (e) {
            console.error('Error fetching SKU detail:', e);
        }

        modal.classList.add('active');
    }

    function closeSkuModal() {
        document.getElementById('modalAddSku')?.classList.remove('active');
    }

    async function submitSkuForm() {
        const alertBox = document.getElementById('skuModalAlert');
        const skuId = document.getElementById('skuModalCode')?.value.trim();
        const name = document.getElementById('skuModalName')?.value.trim();
        const desc = document.getElementById('skuModalDesc')?.value.trim();
        const cat = document.getElementById('skuModalCategory')?.value.trim();
        const uom = document.getElementById('skuModalUom')?.value.trim();
        const wt = parseFloat(document.getElementById('skuModalWeight')?.value || 0);
        const vol = parseFloat(document.getElementById('skuModalVolume')?.value || 0);
        const status = document.getElementById('skuModalStatus')?.value;

        if (!skuId || !name) {
            alertBox.style.display = 'block';
            alertBox.style.background = '#fef2f2';
            alertBox.style.color = '#ef4444';
            alertBox.textContent = 'SKU Code and Product Name are mandatory.';
            return;
        }

        try {
            const res = await fetch('/api/sku_master', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sku_id: skuId,
                    name: name,
                    description: desc,
                    category: cat,
                    uom: uom,
                    unit_weight: wt,
                    unit_volume: vol,
                    status: status
                })
            });
            const data = await res.json();
            if (data.success) {
                closeSkuModal();
                fetchSkuMaster();
            } else {
                alertBox.style.display = 'block';
                alertBox.style.background = '#fef2f2';
                alertBox.style.color = '#ef4444';
                alertBox.textContent = data.message || 'Error saving SKU.';
            }
        } catch (e) {
            alertBox.style.display = 'block';
            alertBox.style.background = '#fef2f2';
            alertBox.style.color = '#ef4444';
            alertBox.textContent = 'Server error: ' + e.message;
        }
    }

    async function confirmDeleteSku(skuId) {
        if (!confirm(`Are you sure you want to delete SKU '${skuId}'? All reference image mappings for this SKU will also be deleted.`)) {
            return;
        }

        try {
            const res = await fetch(`/api/sku_master/${encodeURIComponent(skuId)}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.success) {
                fetchSkuMaster();
            } else {
                alert(data.message || 'Error deleting SKU.');
            }
        } catch (e) {
            alert('Failed to delete SKU: ' + e.message);
        }
    }

    // -------------------------------------------------------------------------
    // 3. Excel Master Data Upload (3-Step Wizard)
    // -------------------------------------------------------------------------
    function openExcelUploadModal() {
        const modal = document.getElementById('modalExcelUpload');
        if (!modal) return;
        resetExcelWizard();
        modal.classList.add('active');
    }

    function closeExcelUploadModal() {
        document.getElementById('modalExcelUpload')?.classList.remove('active');
    }

    function resetExcelWizard() {
        validatedExcelRows = [];
        document.getElementById('excelFileInput').value = '';
        document.getElementById('excelFileLabel').textContent = 'Drag and drop .xlsx file here, or browse';
        document.getElementById('excelWizardStep1').style.display = 'block';
        document.getElementById('excelWizardStep2').style.display = 'none';
        document.getElementById('excelWizardStep3').style.display = 'none';
        document.getElementById('excelStep1Indicator').classList.add('active');
        document.getElementById('excelStep2Indicator').classList.remove('active');
        document.getElementById('excelStep3Indicator').classList.remove('active');
        document.getElementById('excelUploadAlert').style.display = 'none';
    }

    function handleExcelFileSelected(event) {
        const file = event.target.files[0];
        if (file) {
            document.getElementById('excelFileLabel').innerHTML = `<strong>Selected file:</strong> ${escapeHtml(file.name)} (${(file.size / 1024).toFixed(1)} KB)`;
        }
    }

    async function submitExcelPreview() {
        const fileInput = document.getElementById('excelFileInput');
        const alertBox = document.getElementById('excelUploadAlert');
        const file = fileInput?.files[0];

        if (!file) {
            alertBox.style.display = 'block';
            alertBox.style.background = '#fef2f2';
            alertBox.style.color = '#ef4444';
            alertBox.textContent = 'Please select a valid .xlsx spreadsheet file.';
            return;
        }

        const duplicatePolicyRadios = document.getElementsByName('excelDuplicatePolicy');
        for (const r of duplicatePolicyRadios) {
            if (r.checked) currentDuplicatePolicy = r.value;
        }

        alertBox.style.display = 'block';
        alertBox.style.background = '#f0f9ff';
        alertBox.style.color = '#0284c7';
        alertBox.innerHTML = `<i class="fas fa-spinner fa-spin" style="margin-right:6px;"></i> Uploading and validating spreadsheet data...`;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('duplicate_policy', currentDuplicatePolicy);

        try {
            const res = await fetch('/api/sku_master/excel/preview', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (!data.success) {
                alertBox.style.background = '#fef2f2';
                alertBox.style.color = '#ef4444';
                alertBox.textContent = data.message || 'Validation failed.';
                return;
            }

            alertBox.style.display = 'none';
            validatedExcelRows = data.rows || [];

            // Move to Step 2
            renderExcelPreviewStep(data);
        } catch (e) {
            alertBox.style.background = '#fef2f2';
            alertBox.style.color = '#ef4444';
            alertBox.textContent = 'Server error during validation: ' + e.message;
        }
    }

    function renderExcelPreviewStep(data) {
        document.getElementById('excelWizardStep1').style.display = 'none';
        document.getElementById('excelWizardStep2').style.display = 'block';
        document.getElementById('excelStep1Indicator').classList.remove('active');
        document.getElementById('excelStep2Indicator').classList.add('active');

        // Counters
        document.getElementById('statExcelTotal').textContent = data.total_rows || 0;
        document.getElementById('statExcelNew').textContent = data.valid_new_count || 0;
        document.getElementById('statExcelUpdate').textContent = data.valid_update_count || 0;
        document.getElementById('statExcelSkip').textContent = data.skipped_count || 0;
        document.getElementById('statExcelInvalid').textContent = data.invalid_count || 0;

        const btnConfirm = document.getElementById('btnConfirmExcelImport');
        btnConfirm.disabled = !data.can_import;

        // Render rows
        const tbody = document.getElementById('excelPreviewTableBody');
        tbody.innerHTML = '';
        (data.rows || []).forEach(r => {
            let actionBadge = '';
            if (r.action === 'INSERT') {
                actionBadge = `<span style="background:rgba(16,185,129,0.15); color:#059669; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;"><i class="fas fa-plus"></i> Will Insert</span>`;
            } else if (r.action === 'UPDATE') {
                actionBadge = `<span style="background:rgba(59,130,246,0.15); color:#2563eb; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;"><i class="fas fa-arrows-rotate"></i> Will Update</span>`;
            } else if (r.action === 'SKIP') {
                actionBadge = `<span style="background:rgba(148,163,184,0.15); color:#64748b; padding:2px 8px; border-radius:12px; font-size:0.75rem;"><i class="fas fa-forward"></i> Skipped</span>`;
            } else {
                actionBadge = `<span style="background:rgba(239,68,68,0.15); color:#dc2626; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;"><i class="fas fa-xmark"></i> Rejected</span>`;
            }

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-size:0.8rem; text-align:center;">${r.row_num}</td>
                <td style="font-family:monospace; font-weight:700;">${escapeHtml(r.sku_id || '—')}</td>
                <td style="font-size:0.85rem;">${escapeHtml(r.name || '—')}</td>
                <td style="font-size:0.8rem;">${escapeHtml(r.category || 'General')}</td>
                <td style="font-size:0.8rem;">${escapeHtml(r.uom || 'EA')}</td>
                <td>${actionBadge}</td>
                <td style="font-size:0.75rem; color:#ef4444;">${r.error ? escapeHtml(r.error) : '—'}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function excelBackToStep1() {
        document.getElementById('excelWizardStep2').style.display = 'none';
        document.getElementById('excelWizardStep1').style.display = 'block';
        document.getElementById('excelStep2Indicator').classList.remove('active');
        document.getElementById('excelStep1Indicator').classList.add('active');
    }

    async function executeExcelImport() {
        const btnConfirm = document.getElementById('btnConfirmExcelImport');
        btnConfirm.disabled = true;
        btnConfirm.innerHTML = `<i class="fas fa-spinner fa-spin" style="margin-right:6px;"></i> Writing Data...`;

        try {
            const validRowsToImport = validatedExcelRows.filter(r => r.action === 'INSERT' || r.action === 'UPDATE');
            const res = await fetch('/api/sku_master/excel/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rows: validRowsToImport,
                    duplicate_policy: currentDuplicatePolicy
                })
            });
            const data = await res.json();

            // Move to Step 3 Summary
            document.getElementById('excelWizardStep2').style.display = 'none';
            document.getElementById('excelWizardStep3').style.display = 'block';
            document.getElementById('excelStep2Indicator').classList.remove('active');
            document.getElementById('excelStep3Indicator').classList.add('active');

            document.getElementById('excelResInserted').textContent = data.inserted || 0;
            document.getElementById('excelResUpdated').textContent = data.updated || 0;
            document.getElementById('excelResSkipped').textContent = data.skipped || 0;
            document.getElementById('excelResFailed').textContent = data.failed || 0;

            const errContainer = document.getElementById('excelImportErrorsContainer');
            if (data.errors && data.errors.length > 0) {
                errContainer.style.display = 'block';
                errContainer.innerHTML = data.errors.map(e => `<div>Row ${e.row} [${e.sku_id}]: ${escapeHtml(e.error)}</div>`).join('');
            } else {
                errContainer.style.display = 'none';
            }

            // Refresh table
            fetchSkuMaster(1);
        } catch (e) {
            alert('Import failed: ' + e.message);
            btnConfirm.disabled = false;
            btnConfirm.textContent = 'Confirm Import';
        }
    }

    // -------------------------------------------------------------------------
    // 4. Product Image Upload & Mapping (Single & Bulk)
    // -------------------------------------------------------------------------
    async function openSkuImagesModal(skuId = null) {
        selectedSkuForImages = skuId;
        const modal = document.getElementById('modalSkuImages');
        if (!modal) return;

        // Switch to single SKU tab if SKU provided, else bulk tab
        if (skuId) {
            switchImageModalTab('single');
            await loadSingleSkuImages(skuId);
        } else {
            switchImageModalTab('bulk');
        }

        modal.classList.add('active');
    }

    function closeSkuImagesModal() {
        document.getElementById('modalSkuImages')?.classList.remove('active');
    }

    function switchImageModalTab(tabName) {
        const btnSingle = document.getElementById('btnImgTabSingle');
        const btnBulk = document.getElementById('btnImgTabBulk');
        const panelSingle = document.getElementById('imgPanelSingle');
        const panelBulk = document.getElementById('imgPanelBulk');

        if (tabName === 'single') {
            btnSingle.classList.add('active');
            btnBulk.classList.remove('active');
            panelSingle.style.display = 'block';
            panelBulk.style.display = 'none';
        } else {
            btnBulk.classList.add('active');
            btnSingle.classList.remove('active');
            panelBulk.style.display = 'block';
            panelSingle.style.display = 'none';
        }
    }

    async function loadSingleSkuImages(skuId) {
        selectedSkuForImages = skuId;
        document.getElementById('singleSkuTitle').textContent = `Reference Images for SKU: ${skuId}`;
        const container = document.getElementById('singleSkuGallery');
        container.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:1.5rem; color:var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Loading images...</div>`;

        try {
            const res = await fetch(`/api/sku_master/${encodeURIComponent(skuId)}`);
            const data = await res.json();
            if (!data.success || !data.data) {
                container.innerHTML = `<div style="grid-column:1/-1; color:#ef4444; padding:1rem;">Failed to load SKU images.</div>`;
                return;
            }

            const images = data.data.images || [];
            if (images.length === 0) {
                container.innerHTML = `
                    <div style="grid-column:1/-1; text-align:center; padding:2rem; background:var(--panel-subtle); border-radius:8px; border:1px dashed var(--border-light); color:var(--text-muted);">
                        <i class="fas fa-images" style="font-size:2rem; margin-bottom:8px; display:block;"></i>
                        No reference images mapped yet for <strong>${escapeHtml(skuId)}</strong>.<br>
                        Use the dropzone below to upload product reference photos.
                    </div>`;
                return;
            }

            container.innerHTML = images.map(img => `
                <div style="border:1px solid var(--border-light); border-radius:8px; overflow:hidden; background:var(--panel-subtle); display:flex; flex-direction:column;">
                    <div style="position:relative; width:100%; height:130px; background:#000;">
                        <img src="${img.file_path}" alt="${escapeHtml(img.original_filename)}" style="width:100%; height:100%; object-fit:contain;">
                        ${img.is_primary ? `<span style="position:absolute; top:6px; left:6px; background:#10b981; color:#fff; font-size:0.65rem; font-weight:700; padding:2px 6px; border-radius:4px; box-shadow:0 1px 3px rgba(0,0,0,0.4);">PRIMARY</span>` : ''}
                    </div>
                    <div style="padding:8px; flex:1; display:flex; flex-direction:column; justify-content:space-between;">
                        <div style="font-size:0.75rem; color:var(--text-color); font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(img.original_filename)}">${escapeHtml(img.original_filename)}</div>
                        <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:8px;">${(img.file_size / 1024).toFixed(1)} KB</div>
                        <div style="display:flex; justify-content:space-between; gap:4px;">
                            ${!img.is_primary ? `<button type="button" class="btn-secondary btn-sm" onclick="setPrimaryImage(${img.id})" style="font-size:0.7rem; padding:3px 6px;">Set Primary</button>` : '<span></span>'}
                            <button type="button" class="btn-secondary btn-sm" onclick="deleteSkuImage(${img.id})" style="color:#ef4444; font-size:0.7rem; padding:3px 6px;" title="Delete image">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            container.innerHTML = `<div style="grid-column:1/-1; color:#ef4444; padding:1rem;">Error: ${e.message}</div>`;
        }
    }

    async function handleSingleSkuUpload(event) {
        const files = event.target.files;
        if (!files || files.length === 0 || !selectedSkuForImages) return;

        const formData = new FormData();
        formData.append('sku_id', selectedSkuForImages);
        for (let i = 0; i < files.length; i++) {
            formData.append('images', files[i]);
        }

        const alertBox = document.getElementById('singleUploadAlert');
        alertBox.style.display = 'block';
        alertBox.style.background = '#f0f9ff';
        alertBox.style.color = '#0284c7';
        alertBox.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Uploading ${files.length} image(s)...`;

        try {
            const res = await fetch('/api/sku_master/images/upload', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (data.success) {
                alertBox.style.display = 'none';
                await loadSingleSkuImages(selectedSkuForImages);
                fetchSkuMaster();
            } else {
                alertBox.style.background = '#fef2f2';
                alertBox.style.color = '#ef4444';
                alertBox.textContent = data.message || 'Upload failed.';
            }
        } catch (e) {
            alertBox.style.background = '#fef2f2';
            alertBox.style.color = '#ef4444';
            alertBox.textContent = 'Upload error: ' + e.message;
        }
    }

    async function setPrimaryImage(imageId) {
        if (!selectedSkuForImages) return;
        try {
            const res = await fetch(`/api/sku_master/images/${imageId}/set_primary`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sku_id: selectedSkuForImages })
            });
            const data = await res.json();
            if (data.success) {
                await loadSingleSkuImages(selectedSkuForImages);
                fetchSkuMaster();
            } else {
                alert(data.message || 'Failed to set primary image.');
            }
        } catch (e) {
            alert('Error: ' + e.message);
        }
    }

    async function deleteSkuImage(imageId) {
        if (!confirm('Remove this product image mapping?')) return;
        try {
            const res = await fetch(`/api/sku_master/images/${imageId}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.success) {
                await loadSingleSkuImages(selectedSkuForImages);
                fetchSkuMaster();
            } else {
                alert(data.message || 'Failed to delete image.');
            }
        } catch (e) {
            alert('Error: ' + e.message);
        }
    }

    // -------------------------------------------------------------------------
    // 5. Bulk Filename-Based Image Mapping
    // -------------------------------------------------------------------------
    async function handleBulkImageSelect(event) {
        const files = Array.from(event.target.files || []);
        if (files.length === 0) return;
        bulkImageFiles = files;

        const filenames = files.map(f => f.name);
        const alertBox = document.getElementById('bulkUploadAlert');
        alertBox.style.display = 'block';
        alertBox.style.background = '#f0f9ff';
        alertBox.style.color = '#0284c7';
        alertBox.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Analyzing ${files.length} filenames against SKU master...`;

        try {
            const res = await fetch('/api/sku_master/images/match_preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filenames: filenames })
            });
            const data = await res.json();
            if (!data.success) {
                alertBox.style.background = '#fef2f2';
                alertBox.style.color = '#ef4444';
                alertBox.textContent = data.message || 'Match analysis failed.';
                return;
            }

            alertBox.style.display = 'none';
            bulkImageMatches = data.matches || [];
            renderBulkMatchTable(bulkImageMatches);
        } catch (e) {
            alertBox.style.background = '#fef2f2';
            alertBox.style.color = '#ef4444';
            alertBox.textContent = 'Analysis error: ' + e.message;
        }
    }

    function renderBulkMatchTable(matches) {
        const container = document.getElementById('bulkMatchPreviewSection');
        const tbody = document.getElementById('bulkMatchTableBody');
        container.style.display = 'block';
        tbody.innerHTML = '';

        let matchedCount = 0;
        matches.forEach((m, idx) => {
            if (m.status === 'MATCHED') matchedCount++;
            const isMatched = (m.status === 'MATCHED');
            const statusBadge = isMatched
                ? `<span style="background:rgba(16,185,129,0.15); color:#059669; font-weight:700; padding:2px 8px; border-radius:12px; font-size:0.75rem;"><i class="fas fa-check"></i> ${m.status_label}</span>`
                : `<span style="background:rgba(239,68,68,0.15); color:#ef4444; font-weight:700; padding:2px 8px; border-radius:12px; font-size:0.75rem;"><i class="fas fa-xmark"></i> ${m.status_label}</span>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-size:0.8rem; font-weight:600;">${escapeHtml(m.filename)}</td>
                <td>
                    <input type="text" id="bulkSkuInput_${idx}" value="${escapeHtml(m.matched_sku_id || '')}" placeholder="Enter SKU code" style="padding:4px 8px; font-size:0.8rem; font-family:monospace; margin-bottom:0; width:150px; text-transform:uppercase;">
                </td>
                <td style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(m.matched_name || '—')}</td>
                <td>${statusBadge}</td>
            `;
            tbody.appendChild(tr);
        });

        document.getElementById('bulkMatchSummary').textContent = `${matchedCount} of ${matches.length} images automatically matched to SKUs. You can manually adjust any SKU code above before committing.`;
        document.getElementById('btnCommitBulkImages').disabled = false;
    }

    async function commitBulkImageUpload() {
        if (bulkImageFiles.length === 0) return;

        const btn = document.getElementById('btnCommitBulkImages');
        btn.disabled = true;
        btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Uploading...`;

        // Gather manual mappings
        const mappings = {};
        bulkImageMatches.forEach((m, idx) => {
            const inputVal = document.getElementById(`bulkSkuInput_${idx}`)?.value.trim().toUpperCase();
            if (inputVal) {
                mappings[m.filename] = inputVal;
            }
        });

        const formData = new FormData();
        formData.append('mappings', JSON.stringify(mappings));
        bulkImageFiles.forEach(f => {
            formData.append('images', f);
        });

        const alertBox = document.getElementById('bulkUploadAlert');
        alertBox.style.display = 'block';
        alertBox.style.background = '#f0f9ff';
        alertBox.style.color = '#0284c7';
        alertBox.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Uploading and mapping ${bulkImageFiles.length} images...`;

        try {
            const res = await fetch('/api/sku_master/images/upload', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (data.success) {
                alertBox.style.background = '#f0fdf4';
                alertBox.style.color = '#16a34a';
                alertBox.innerHTML = `<i class="fas fa-circle-check"></i> Successfully mapped ${data.uploaded_count} images!`;
                setTimeout(() => {
                    closeSkuImagesModal();
                    fetchSkuMaster();
                }, 1500);
            } else {
                alertBox.style.background = '#fef2f2';
                alertBox.style.color = '#ef4444';
                alertBox.textContent = data.message || 'Bulk upload encountered errors.';
                btn.disabled = false;
                btn.textContent = 'Commit Image Mappings';
            }
        } catch (e) {
            alertBox.style.background = '#fef2f2';
            alertBox.style.color = '#ef4444';
            alertBox.textContent = 'Error: ' + e.message;
            btn.disabled = false;
            btn.textContent = 'Commit Image Mappings';
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Expose functions globally to window for onclick handlers
    window.fetchSkuMaster = fetchSkuMaster;
    window.skuMasterPrevPage = skuMasterPrevPage;
    window.skuMasterNextPage = skuMasterNextPage;
    window.resetSkuMasterFilters = resetSkuMasterFilters;
    window.openAddSkuModal = openAddSkuModal;
    window.openEditSkuModal = openEditSkuModal;
    window.closeSkuModal = closeSkuModal;
    window.submitSkuForm = submitSkuForm;
    window.confirmDeleteSku = confirmDeleteSku;
    window.openExcelUploadModal = openExcelUploadModal;
    window.closeExcelUploadModal = closeExcelUploadModal;
    window.handleExcelFileSelected = handleExcelFileSelected;
    window.submitExcelPreview = submitExcelPreview;
    window.excelBackToStep1 = excelBackToStep1;
    window.executeExcelImport = executeExcelImport;
    window.openSkuImagesModal = openSkuImagesModal;
    window.closeSkuImagesModal = closeSkuImagesModal;
    window.switchImageModalTab = switchImageModalTab;
    window.handleSingleSkuUpload = handleSingleSkuUpload;
    window.setPrimaryImage = setPrimaryImage;
    window.deleteSkuImage = deleteSkuImage;
    window.handleBulkImageSelect = handleBulkImageSelect;
    window.commitBulkImageUpload = commitBulkImageUpload;

})();
