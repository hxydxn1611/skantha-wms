/**
 * PALLET VISION COUNTING UI CONTROLLER
 * Skantha WMS & W.A.R.L.O.G. Warehouse OS
 * 
 * Provides interactive controls for:
 * Option 1: Individual Piece Counting (Countable pipes, tubes, bars, rods, billets, box sections)
 * Option 2: Bundle Counting & Multi-View Stack Deconstruction (Tiers, layers, 3D isometric layout)
 */

(function() {
    let currentMode = 'pieces'; // 'pieces' or 'bundles'
    let latestPiecesResult = null;
    let latestBundlesResult = null;
    let mappedVisionSkus = [];
    let selectedPiecesSkuId = '';
    let selectedBundlesSkuId = '';

    window.toggleDemoPresets = function(drawerId) {
        const el = document.getElementById(drawerId);
        if (el) {
            el.style.display = (el.style.display === 'none' || !el.style.display) ? 'block' : 'none';
        }
    };

    window.loadVisionSkus = async function(forceRefresh = false) {
        try {
            const res = await fetch('/api/pallets/vision-skus');
            const data = await res.json();
            if (!data.success) return;

            mappedVisionSkus = data.skus || [];

            const pSelect = document.getElementById('piecesSkuSelect');
            const bSelect = document.getElementById('bundlesSkuSelect');

            const buildOptions = () => {
                let html = '<option value="">-- Auto-Detect (Stock Found, Racks/Crates Ignored) --</option>';
                html += '<option value="MULTI_ALL">✨ Multi-Product Mode: Count All Products Individually</option>';
                mappedVisionSkus.forEach(s => {
                    html += `<option value="${s.sku_id}">🎯 Target Only: ${s.sku_id} &mdash; ${s.name} (${s.category})</option>`;
                });
                return html;
            };

            if (pSelect) {
                const prev = pSelect.value;
                pSelect.innerHTML = buildOptions();
                if (prev) {
                    pSelect.value = prev;
                } else {
                    pSelect.value = "";
                }
                window.onVisionSkuSelected('pieces', pSelect.value);
            }

            if (bSelect) {
                const prev = bSelect.value;
                bSelect.innerHTML = buildOptions();
                if (prev) {
                    bSelect.value = prev;
                } else {
                    bSelect.value = "";
                }
                window.onVisionSkuSelected('bundles', bSelect.value);
            }

            // Also populate the inline Pallet Counting Workbench SKU selector (#wbTargetSkuSelect)
            const wbSelect = document.getElementById('wbTargetSkuSelect');
            if (wbSelect) {
                const prevWb = wbSelect.value;
                let wbHtml = '<option value="">✨ Auto-Recognize Product from Warehouse SKUs (100% AI Match)</option>';
                mappedVisionSkus.forEach(s => {
                    const upb = Math.max(1, parseInt(s.units_per_bundle || 1, 10));
                    const uom = (s.uom || 'EA').toUpperCase();
                    const bname = s.bundle_name || 'Bundle';
                    wbHtml += `<option value="${s.sku_id}">🎯 ${s.sku_id} — ${s.name} [1 ${bname} = ${upb} ${uom}]</option>`;
                });
                wbSelect.innerHTML = wbHtml;
                if (prevWb && mappedVisionSkus.some(s => s.sku_id === prevWb)) {
                    wbSelect.value = prevWb;
                }
            }
        } catch (e) {
            console.error('Failed to load vision SKUs:', e);
        }
    };

    window.loadWorkbenchVisionSkus = window.loadVisionSkus;

    window.onWorkbenchSkuSelectChange = function(skuId) {
        const matched = mappedVisionSkus.find(s => s.sku_id === skuId);
        const upbInput = document.getElementById('wbUnitsPerBundleInput');
        const uomSelect = document.getElementById('wbUomSelect');
        const bnameInput = document.getElementById('wbBundleNameInput');
        const recText = document.getElementById('wbRecognizedSkuText');

        if (matched) {
            const upb = Math.max(1, parseInt(matched.units_per_bundle || 1, 10));
            const uom = (matched.uom || 'EA').toUpperCase();
            const bname = matched.bundle_name || 'Bundle';
            if (upbInput) upbInput.value = upb;
            if (uomSelect) {
                if (!Array.from(uomSelect.options).some(o => o.value === uom)) {
                    const opt = document.createElement('option');
                    opt.value = uom;
                    opt.textContent = uom;
                    uomSelect.appendChild(opt);
                }
                uomSelect.value = uom;
            }
            if (bnameInput) bnameInput.value = bname;
            if (recText) {
                recText.innerHTML = `Locked SKU: <b style="color:#38bdf8; font-family:monospace;">${matched.sku_id}</b> &mdash; ${matched.name} <span style="color:#94a3b8;">(${matched.category || 'General'})</span>`;
            }
            const bMatSelect = document.getElementById('wbBundleMaterialSelect');
            if (bMatSelect) {
                const textBlob = `${matched.sku_id} ${matched.name || ''} ${matched.category || ''}`.toLowerCase();
                if (textBlob.includes('box') || textBlob.includes('carton')) {
                    bMatSelect.value = 'carton_boxes';
                } else if (textBlob.includes('pipe') || textBlob.includes('tube') || textBlob.includes('steel') || textBlob.includes('metal') || textBlob.includes('rod') || textBlob.includes('profile') || textBlob.includes('bar')) {
                    bMatSelect.value = 'metal_bundles';
                } else if (textBlob.includes('timber') || textBlob.includes('wood') || textBlob.includes('plank')) {
                    bMatSelect.value = 'timber_bundles';
                }
            }
        } else {
            if (recText) {
                recText.textContent = 'Auto-Recognition Active — AI Vision will identify the exact SKU from your active warehouse catalog and calculate total individual units.';
            }
        }
        window.onWorkbenchBundleMultiplierChange();
    };

    window.onWorkbenchBundleMultiplierChange = function() {
        const upb = Math.max(1, parseInt(document.getElementById('wbUnitsPerBundleInput')?.value || '1', 10));
        const uom = (document.getElementById('wbUomSelect')?.value || 'EA').toUpperCase();
        const bname = (document.getElementById('wbBundleNameInput')?.value || 'Bundle').trim() || 'Bundle';
        const pill = document.getElementById('wbRealizedUnitsPill');
        const totalBadge = document.getElementById('wbTotalBadge');

        let baseCount = 0;
        if (wbLatestResult) {
            const qb = wbLatestResult.quantity_breakdown || {};
            baseCount = qb.total_units !== undefined ? qb.total_units : (wbLatestResult.total_pieces !== undefined ? wbLatestResult.total_pieces : (wbLatestResult.total_bundles || 0));
        }
        const totalIndividual = baseCount * upb;
        if (pill) {
            pill.innerHTML = `${baseCount} ${bname}${baseCount === 1 ? '' : 's'} &times; ${upb} ${uom} = <span style="color:#fff; text-decoration:underline;">${totalIndividual} ${uom}</span>`;
        }
        if (totalBadge && wbLatestResult) {
            totalBadge.textContent = upb > 1 ? `${baseCount} ${bname.toUpperCase()}S (${totalIndividual} ${uom})` : `${totalIndividual} ${uom}`;
        }
    };

    window.saveWorkbenchBundleConfigToSku = async function() {
        const selSku = document.getElementById('wbTargetSkuSelect')?.value || (wbLatestResult && wbLatestResult.sku_id) || '';
        if (!selSku) {
            if (typeof showToast === 'function') {
                showToast('Select a target SKU or run Count Now first so AI recognizes the SKU to save to.', 'warning');
            }
            return;
        }
        const upb = Math.max(1, parseInt(document.getElementById('wbUnitsPerBundleInput')?.value || '1', 10));
        const uom = (document.getElementById('wbUomSelect')?.value || 'EA').toUpperCase();
        const bname = (document.getElementById('wbBundleNameInput')?.value || 'Bundle').trim() || 'Bundle';
        if (typeof window.quickSaveBundleDeclaration === 'function') {
            await window.quickSaveBundleDeclaration(selSku, upb, uom, bname);
        }
    };

    window.onVisionSkuSelected = function(mode, skuId) {
        const isPieces = mode === 'pieces';
        if (isPieces) selectedPiecesSkuId = skuId;
        else selectedBundlesSkuId = skuId;

        const thumb = document.getElementById(isPieces ? 'piecesSkuThumb' : 'bundlesSkuThumb');
        const icon = document.getElementById(isPieces ? 'piecesSkuNoThumbIcon' : 'bundlesSkuNoThumbIcon');
        const badge = document.getElementById(isPieces ? 'piecesSkuStatusBadge' : 'bundlesSkuStatusBadge');

        if (skuId === 'MULTI_ALL') {
            if (thumb) {
                thumb.src = '';
                thumb.style.display = 'none';
            }
            if (icon) {
                icon.className = 'fas fa-layer-group';
                icon.style.display = 'block';
                icon.style.color = '#38bdf8';
            }
            if (badge) {
                badge.innerHTML = `<i class="fas fa-layer-group"></i> Multi-Product Simultaneous Mode (Individual Counts)`;
                badge.style.background = 'rgba(56,189,248,0.15)';
                badge.style.color = '#38bdf8';
                badge.style.borderColor = 'rgba(56,189,248,0.3)';
            }
            return;
        }

        const matched = mappedVisionSkus.find(s => s.sku_id === skuId);

        if (matched && matched.image_url) {
            if (thumb) {
                thumb.src = matched.image_url;
                thumb.style.display = 'block';
            }
            if (icon) icon.style.display = 'none';
            if (badge) {
                badge.innerHTML = `<i class="fas fa-crosshairs"></i> Target Match: Count ONLY ${matched.sku_id} (Ignore Others & Racks)`;
                badge.style.background = 'rgba(16,185,129,0.15)';
                badge.style.color = '#10b981';
                badge.style.borderColor = 'rgba(16,185,129,0.3)';
            }
        } else {
            if (thumb) {
                thumb.src = '';
                thumb.style.display = 'none';
            }
            if (icon) {
                icon.className = 'fas fa-boxes-stacked';
                icon.style.display = 'block';
                icon.style.color = '#64748b';
            }
            if (badge) {
                badge.innerHTML = `<i class="fas fa-robot"></i> Auto-Detect (All Stock, Racks Filtered)`;
                badge.style.background = 'rgba(148,163,184,0.12)';
                badge.style.color = '#94a3b8';
                badge.style.borderColor = 'rgba(148,163,184,0.2)';
            }
        }
    };

    // -------------------------------------------------------------------------
    // MODAL OPEN / CLOSE & MODE SWITCHING
    // -------------------------------------------------------------------------

    window.openVisionCountingModal = function(initialMode = 'pieces') {
        const modal = document.getElementById('modalVisionCounting');
        if (modal) {
            modal.style.display = 'flex';
            switchVisionCountingMode(initialMode);
            if (mappedVisionSkus.length === 0) {
                window.loadVisionSkus();
            }
        }
    };

    window.closeVisionCountingModal = function() {
        const modal = document.getElementById('modalVisionCounting');
        if (modal) {
            modal.style.display = 'none';
        }
    };

    // Backward-compatibility alias
    window.openMultiAngleAuditModal = function() {
        window.openVisionCountingModal('bundles');
    };
    window.closeMultiAngleAuditModal = function() {
        window.closeVisionCountingModal();
    };

    window.switchVisionCountingMode = function(mode) {
        currentMode = mode;
        const btnPieces = document.getElementById('tabModePieces');
        const btnBundles = document.getElementById('tabModeBundles');
        const panelPieces = document.getElementById('panelModePieces');
        const panelBundles = document.getElementById('panelModeBundles');

        if (mode === 'pieces') {
            if (btnPieces) {
                btnPieces.style.background = '#8b5cf6';
                btnPieces.style.color = '#ffffff';
                btnPieces.style.borderColor = '#8b5cf6';
            }
            if (btnBundles) {
                btnBundles.style.background = 'transparent';
                btnBundles.style.color = '#94a3b8';
                btnBundles.style.borderColor = 'rgba(255,255,255,0.15)';
            }
            if (panelPieces) panelPieces.style.display = 'block';
            if (panelBundles) panelBundles.style.display = 'none';
        } else {
            if (btnBundles) {
                btnBundles.style.background = '#0284c7';
                btnBundles.style.color = '#ffffff';
                btnBundles.style.borderColor = '#0284c7';
            }
            if (btnPieces) {
                btnPieces.style.background = 'transparent';
                btnPieces.style.color = '#94a3b8';
                btnPieces.style.borderColor = 'rgba(255,255,255,0.15)';
            }
            if (panelBundles) panelBundles.style.display = 'block';
            if (panelPieces) panelPieces.style.display = 'none';
        }
    };


    // -------------------------------------------------------------------------
    // OPTION 1: INDIVIDUAL PIECE COUNTING
    // -------------------------------------------------------------------------

    window.previewPiecesImage = function(input) {
        if (!input.files || !input.files[0]) return;
        const file = input.files[0];
        const reader = new FileReader();
        reader.onload = function(e) {
            const previewImg = document.getElementById('piecesPreviewImg');
            const placeholder = document.getElementById('piecesPlaceholder');
            if (previewImg) {
                previewImg.src = e.target.result;
                previewImg.style.display = 'block';
            }
            if (placeholder) {
                placeholder.style.display = 'none';
            }
            // Auto-trigger instant 1-click count!
            setTimeout(() => {
                window.executePieceCount(false);
            }, 50);
        };
        reader.readAsDataURL(file);
    };

    let currentPiecesList = [];
    let manualPinsList = [];
    let isCustomMatrixManuallyTuned = false;
    let currentRawImageUrl = '';

    window.loadSamplePiecesImage = function(sampleFileName = 'sample_individual_pipes_229.jpg', mode = 'auto') {
        const previewImg = document.getElementById('piecesPreviewImg');
        const placeholder = document.getElementById('piecesPlaceholder');
        if (previewImg) {
            previewImg.src = `/static/test_scenes/${sampleFileName}`;
            previewImg.style.display = 'block';
        }
        if (placeholder) placeholder.style.display = 'none';

        const modeSelect = document.getElementById('piecesCountingModeSelect');
        if (modeSelect) modeSelect.value = mode;

        currentMatrixParams = null;
        isCustomMatrixManuallyTuned = false;
        manualPinsList = [];
        const overlay = document.getElementById('piecesBadgesOverlay');
        if (overlay) overlay.innerHTML = '';

        window.executePieceCount(true, sampleFileName, mode);
    };

    window.executePieceCount = async function(useSample = false, sampleNameOverride = null, modeOverride = null) {
        const btn = document.getElementById('btnRunPieceCount');
        const spinner = document.getElementById('piecesProcessingStatus');
        const resultContainer = document.getElementById('piecesResultContainer');

        if (btn) btn.disabled = true;
        if (spinner) spinner.style.display = 'block';
        if (resultContainer) resultContainer.style.display = 'none';

        const overlay = document.getElementById('piecesBadgesOverlay');
        if (overlay) overlay.innerHTML = '';
        manualPinsList = [];

        if (useSample || !isCustomMatrixManuallyTuned) {
            currentMatrixParams = null;
        }

        try {
            const formData = new FormData();
            const sens = document.getElementById('piecesSensitivitySlider')?.value || '0.5';
            const clust = document.getElementById('piecesClusterSelect')?.value || '1';
            const mode = modeOverride || document.getElementById('piecesCountingModeSelect')?.value || 'auto';

            formData.append('sensitivity', sens);
            formData.append('clusters', clust);
            formData.append('counting_mode', mode);

            const selectedSku = document.getElementById('piecesSkuSelect')?.value || selectedPiecesSkuId || '';
            if (selectedSku) {
                formData.append('sku_id', selectedSku);
            }

            // Custom 3D Matrix Parameters (if fine-tuned by user)
            if (currentMatrixParams) {
                if (currentMatrixParams.layers) formData.append('matrix_layers', currentMatrixParams.layers);
                if (currentMatrixParams.columns) formData.append('matrix_columns', currentMatrixParams.columns);
                if (currentMatrixParams.depth) formData.append('matrix_depth', currentMatrixParams.depth);
            }

            const sampleFile = sampleNameOverride || 'sample_individual_pipes_229.jpg';

            if (useSample) {
                formData.append('use_sample', 'true');
                formData.append('sample_name', sampleFile);
            } else {
                const f = document.getElementById('filePiecesImage')?.files[0];
                if (f) {
                    formData.append('image', f);
                } else {
                    formData.append('use_sample', 'true');
                    formData.append('sample_name', sampleFile);
                }
            }

            const res = await fetch('/api/pallets/count-pieces', {
                method: 'POST',
                body: formData
            });

            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Failed to detect pieces');
            }

            latestPiecesResult = data;
            currentPiecesList = data.pieces || [];
            currentRawImageUrl = data.raw_image_url || data.annotated_image_url || '';

            renderPiecesResults(data);

        } catch (err) {
            console.error('Piece count error:', err);
            alert(`Counting Error: ${err.message}`);
        } finally {
            if (btn) btn.disabled = false;
            if (spinner) spinner.style.display = 'none';
        }
    };

    function renderPiecesResults(data) {
        const resultContainer = document.getElementById('piecesResultContainer');
        if (!resultContainer) return;

        resultContainer.style.display = 'flex';

        // Total badge with smart units
        const badge = document.getElementById('piecesTotalBadge');
        if (badge) {
            let countLabel = `${data.total_pieces} PCS`;
            if (data.mode === 'MULTI_PRODUCT') {
                const prodCount = (data.clusters || []).filter(c => c.sku_id).length;
                countLabel = `${data.total_pieces} ITEMS (${prodCount} Products)`;
            } else if (data.mode === 'TARGET_SKU') {
                countLabel = `${data.total_pieces} ${data.sku_name ? data.sku_name.toUpperCase() : 'ITEMS'} (TARGET)`;
            } else if (data.mode === 'BUNDLE_STACK' || data.items_label === 'Bundles') {
                countLabel = `${data.total_pieces} BUNDLES`;
            } else if (data.mode === 'BOX_GRID') {
                const qb = data.quantity_breakdown || {};
                const directCount = qb.directly_detected_count !== undefined ? qb.directly_detected_count : (data.visible_pieces || data.total_pieces);
                const hiddenCount = qb.inferred_count !== undefined ? qb.inferred_count : (data.hidden_count || 0);
                if (qb.is_estimate && hiddenCount > 0) {
                    countLabel = `${data.total_pieces} BOXES (Proposed Estimate: ${directCount} Visible + ${hiddenCount} Inferred)`;
                } else if (hiddenCount === 0) {
                    countLabel = `${directCount} BOXES (Direct Visible Detections)`;
                } else {
                    countLabel = `${directCount} BOXES (${data.total_pieces} Total)`;
                }
            }
            badge.textContent = countLabel;
        }

        // SKU match status tag
        const skuTag = document.getElementById('piecesSkuMatchResultTag');
        if (skuTag) {
            if (data.mode === 'MULTI_PRODUCT') {
                skuTag.style.display = 'inline-flex';
                let ignoredText = data.ignored_count ? ` &bull; <span style="color:#94a3b8;"><i class="fas fa-filter"></i> ${data.ignored_count} Non-product / Racks Ignored</span>` : '';
                skuTag.innerHTML = `<i class="fas fa-layer-group" style="color:#38bdf8;"></i> <b>Multi-Product Breakdown</b>: Individual counts active${ignoredText}`;
            } else if (data.mode === 'TARGET_SKU') {
                skuTag.style.display = 'inline-flex';
                let ignoredText = data.ignored_count ? ` &bull; <span style="color:#94a3b8;"><i class="fas fa-shield-alt"></i> ${data.ignored_count} other stock & racks ignored</span>` : '';
                skuTag.innerHTML = `<i class="fas fa-crosshairs" style="color:#10b981;"></i> <b>Strict Target Match</b>: Only '${data.sku_name || data.sku_id}' counted${ignoredText}`;
            } else if (data.matrix_3d) {
                skuTag.style.display = 'inline-flex';
                const qb = data.quantity_breakdown || {};
                const isEst = qb.is_estimate;
                const directCount = qb.directly_detected_count !== undefined ? qb.directly_detected_count : (data.visible_pieces || data.total_pieces);
                const hiddenCount = qb.inferred_count !== undefined ? qb.inferred_count : (data.hidden_count || 0);
                if (isEst && hiddenCount > 0) {
                    skuTag.innerHTML = `<i class="fas fa-cubes" style="color:#38bdf8;"></i> <b>Proposed 3D Estimate</b>: ${data.matrix_3d.formula} (${directCount} visible direct detections, ${hiddenCount} inferred rear/interior)`;
                } else if (data.matrix_3d.is_depth_unknown) {
                    skuTag.innerHTML = `<i class="fas fa-bullseye" style="color:#10b981;"></i> <b>Direct Object Recognition</b>: ${directCount} distinct physical cartons localized (Interior depth unknown)`;
                } else {
                    skuTag.innerHTML = `<i class="fas fa-bullseye" style="color:#10b981;"></i> <b>Direct Object Recognition</b>: ${directCount} distinct physical cartons localized (0 inferred hidden)`;
                }
            } else if (data.sku_id) {
                skuTag.style.display = 'inline-flex';
                skuTag.innerHTML = `<i class="fas fa-certificate" style="color:#10b981;"></i> Reference SKU: <b>${data.sku_id}</b> &bull; ${data.confidence_note || 'AI Trained Signature Verified'}`;
            } else {
                skuTag.style.display = 'none';
            }
        }

        // Annotated Image URL
        const imgElem = document.getElementById('piecesResultImg');
        if (imgElem && data.annotated_image_url) {
            imgElem.src = `${data.annotated_image_url}?t=${Date.now()}`;
            imgElem.onload = () => {
                renderInteractiveBadgesOverlay();
            };
        }

        // Cluster breakdown pills
        updatePiecesClustersPills(data.clusters);

        // 3D Pallet Matrix Digital Twin (Renders all visible + hidden boxes in 3D WebGL)
        const box3DSection = document.getElementById('boxMatrix3DSection');
        if (box3DSection) {
            if (data.matrix_3d) {
                box3DSection.style.display = 'block';
                const formulaBadge = document.getElementById('matrix3DFormulaBadge');
                if (formulaBadge) {
                    const qb = data.quantity_breakdown || {};
                    const directCount = qb.directly_detected_count !== undefined ? qb.directly_detected_count : (data.visible_pieces || data.total_pieces);
                    const hiddenCount = qb.inferred_count !== undefined ? qb.inferred_count : (data.hidden_count || 0);
                    if (hiddenCount > 0) {
                        formulaBadge.textContent = `${data.matrix_3d.formula} (${directCount} Visible + ${hiddenCount} Inferred Core)`;
                    } else if (data.matrix_3d.is_depth_unknown) {
                        formulaBadge.textContent = `Direct Front Elevation Twin (${directCount} Localized Objects; Interior Depth Unknown)`;
                    } else {
                        formulaBadge.textContent = `${data.matrix_3d.formula} (All ${directCount} Direct Visible Detections)`;
                    }
                }
                const lElem = document.getElementById('matrixValLayers');
                const cElem = document.getElementById('matrixValColumns');
                const dElem = document.getElementById('matrixValDepth');
                if (lElem) lElem.textContent = data.matrix_3d.layers;
                if (cElem) cElem.textContent = data.matrix_3d.columns;
                if (dElem) {
                    if (data.matrix_3d.is_depth_unknown) {
                        dElem.textContent = '1 (Front; Interior Unknown)';
                    } else {
                        dElem.textContent = data.matrix_3d.depth;
                    }
                }

                if (data.matrix_3d.reconstruction_mode === 'OPERATOR_CONFIRMED') {
                    currentMatrixParams = {
                        layers: data.matrix_3d.layers,
                        columns: data.matrix_3d.columns,
                        depth: data.matrix_3d.depth
                    };
                } else {
                    currentMatrixParams = null;
                    isCustomMatrixManuallyTuned = false;
                }

                setTimeout(() => {
                    init3DPalletViewer(data.matrix_3d);
                }, 100);
            } else {
                box3DSection.style.display = 'none';
            }
        }

        resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function updatePiecesClustersPills(clusters) {
        const pillsContainer = document.getElementById('piecesClustersPills');
        if (!pillsContainer) return;

        if (clusters && clusters.length > 0) {
            pillsContainer.innerHTML = clusters.map(cl => {
                const isIgnored = cl.name && cl.name.toLowerCase().includes('ignored');
                const borderCol = isIgnored ? 'rgba(148,163,184,0.3)' : (cl.color_hex || '#0284c7');
                const bgCol = isIgnored ? 'rgba(148,163,184,0.08)' : 'rgba(255,255,255,0.06)';
                const dotCol = isIgnored ? '#64748b' : (cl.color_hex || '#0284c7');
                const icon = isIgnored ? '<i class="fas fa-filter" style="color:#64748b; font-size:0.75rem;"></i>' : `<span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:${dotCol};"></span>`;
                return `
                    <div style="background:${bgCol}; border:1px solid ${borderCol}; border-radius:6px; padding:6px 12px; display:inline-flex; align-items:center; gap:8px;">
                        ${icon}
                        <span style="font-size:0.75rem; color:${isIgnored ? '#94a3b8' : '#f1f5f9'}; font-weight:600;">${cl.name}:</span>
                        <b style="font-size:0.85rem; color:#fff; font-family:'JetBrains Mono',monospace;">${cl.count}</b>
                    </div>
                `;
            }).join('');
        } else {
            pillsContainer.innerHTML = '';
        }
    }

    function renderInteractiveBadgesOverlay() {
        const overlay = document.getElementById('piecesBadgesOverlay');
        const imgElem = document.getElementById('piecesResultImg');
        if (!overlay || !imgElem) return;

        overlay.innerHTML = '';
        const imgW = imgElem.naturalWidth || imgElem.clientWidth || 1;
        const imgH = imgElem.naturalHeight || imgElem.clientHeight || 1;

        // The backend annotated image already contains the authoritative numbered markers and bounding boxes.
        // Do NOT render a duplicate visible layer of automated frontend numbered markers!
        // Render transparent interactive hit-zones for existing detections (lighting up only on hover to delete),
        // and visible badges only for un-rendered manual operator additions.
        currentPiecesList.forEach((p, idx) => {
            const leftPct = (p.x / imgW) * 100;
            const topPct = (p.y / imgH) * 100;
            const isUnrenderedManual = Boolean(p.is_unrendered_pin);

            const badge = document.createElement('div');
            badge.className = 'interactive-piece-badge';
            badge.style.cssText = `
                position: absolute;
                left: ${leftPct}%;
                top: ${topPct}%;
                transform: translate(-50%, -50%);
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background: ${isUnrenderedManual ? '#10b981' : 'transparent'};
                border: 2px solid ${isUnrenderedManual ? '#ffffff' : 'transparent'};
                color: ${isUnrenderedManual ? '#ffffff' : 'transparent'};
                font-size: 10px;
                font-weight: 800;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                pointer-events: auto;
                user-select: none;
                transition: transform 0.15s, background 0.15s, border-color 0.15s;
            `;
            const confStr = p.confidence !== undefined ? ` (Conf ${Number(p.confidence).toFixed(2)})` : '';
            badge.title = `Detection #${p.id || (idx + 1)}${confStr}\nClick to Remove`;
            badge.textContent = isUnrenderedManual ? (p.id || (idx + 1)) : '';

            badge.onmouseenter = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1.35)';
                badge.style.background = 'rgba(239, 68, 68, 0.85)';
                badge.style.borderColor = '#ffffff';
                badge.style.color = '#ffffff';
                badge.textContent = '×';
            };
            badge.onmouseleave = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1)';
                badge.style.background = isUnrenderedManual ? '#10b981' : 'transparent';
                badge.style.borderColor = isUnrenderedManual ? '#ffffff' : 'transparent';
                badge.style.color = isUnrenderedManual ? '#ffffff' : 'transparent';
                badge.textContent = isUnrenderedManual ? (p.id || (idx + 1)) : '';
            };
            badge.onclick = (e) => {
                e.stopPropagation();
                window.removePieceBadge(idx);
            };

            overlay.appendChild(badge);
        });
    }

    window.handleImageCanvasClick = function(event) {
        const imgElem = document.getElementById('piecesResultImg');
        if (!imgElem) return;

        const rect = imgElem.getBoundingClientRect();
        const clickX = event.clientX - rect.left;
        const clickY = event.clientY - rect.top;

        const imgW = imgElem.naturalWidth || imgElem.clientWidth || 1;
        const imgH = imgElem.naturalHeight || imgElem.clientHeight || 1;

        const naturalX = Math.round((clickX / rect.width) * imgW);
        const naturalY = Math.round((clickY / rect.height) * imgH);

        // Check if click hits an existing detection centroid (within 18px in image space)
        const hitIdx = currentPiecesList.findIndex(p => Math.hypot((p.x || 0) - naturalX, (p.y || 0) - naturalY) <= 18);
        if (hitIdx !== -1) {
            window.removePieceBadge(hitIdx);
            return;
        }

        const newIdx = currentPiecesList.length + 1;
        currentPiecesList.push({
            id: newIdx,
            index: newIdx,
            detection_id: `MAN-${String(newIdx).padStart(3, '0')}`,
            x: naturalX,
            y: naturalY,
            w: 36,
            h: 36,
            confidence: 1.0,
            cluster: 'Operator Verified',
            color_hex: '#10b981',
            is_unrendered_pin: true
        });

        updateLocalPiecesState();
        renderInteractiveBadgesOverlay();
    };

    window.removeManualPin = function(index) {
        if (index >= 0 && index < manualPinsList.length) {
            manualPinsList.splice(index, 1);
            updateLocalManualPinsState();
            renderInteractiveBadgesOverlay();
        }
    };

    function updateLocalManualPinsState() {
        const manualCount = manualPinsList.length;
        if (!latestPiecesResult) return;
        const directCount = latestPiecesResult.directly_detected_count !== undefined 
            ? latestPiecesResult.directly_detected_count 
            : (latestPiecesResult.visible_pieces || latestPiecesResult.total_pieces || 0);
        const total = directCount + manualCount;

        const badge = document.getElementById('piecesTotalBadge');
        if (badge) {
            if (manualCount > 0) {
                badge.textContent = `${total} BOXES (${directCount} Direct + ${manualCount} Manual)`;
            } else {
                badge.textContent = `${directCount} BOXES (Direct Visible Detections)`;
            }
        }
    }

    window.removePieceBadge = function(index) {
        if (index >= 0 && index < currentPiecesList.length) {
            currentPiecesList.splice(index, 1);
            // Renumber remaining pieces sequentially
            currentPiecesList.forEach((p, i) => { p.id = i + 1; });
            updateLocalPiecesState();
            renderInteractiveBadgesOverlay();
        }
    };

    function updateLocalPiecesState() {
        const total = currentPiecesList.length;
        const badge = document.getElementById('piecesTotalBadge');
        if (badge) badge.textContent = `${total} PCS`;

        // Recalculate clusters
        const clusterMap = {};
        currentPiecesList.forEach(p => {
            const cname = p.cluster || 'Verified piece';
            if (!clusterMap[cname]) {
                clusterMap[cname] = { name: cname, count: 0, color_hex: p.color_hex || '#0284c7' };
            }
            clusterMap[cname].count++;
        });

        updatePiecesClustersPills(Object.values(clusterMap));

        if (latestPiecesResult) {
            latestPiecesResult.total_pieces = total;
            latestPiecesResult.visible_pieces = total;
            latestPiecesResult.directly_detected_count = total;
            if (latestPiecesResult.quantity_breakdown) {
                latestPiecesResult.quantity_breakdown.visible_count = total;
                latestPiecesResult.quantity_breakdown.directly_detected_count = total;
                const hidden = latestPiecesResult.quantity_breakdown.inferred_count || 0;
                latestPiecesResult.quantity_breakdown.total_units = total + hidden;
            }
        }
    }

    window.recertifyAndSavePieces = async function() {
        if (!currentRawImageUrl || currentPiecesList.length === 0) {
            alert('No pieces loaded to certify.');
            return;
        }

        try {
            const res = await fetch('/api/pallets/re-render-pieces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    raw_image_url: currentRawImageUrl,
                    pieces: currentPiecesList
                })
            });

            const data = await res.json();
            if (res.ok && data.success) {
                const imgElem = document.getElementById('piecesResultImg');
                if (imgElem && data.annotated_image_url) {
                    imgElem.src = `${data.annotated_image_url}?t=${Date.now()}`;
                }
                alert(`Certified 100% Verified! Total Count: ${data.total_pieces} Pieces.`);
            } else {
                alert(`Re-render error: ${data.error || 'Failed to re-render'}`);
            }
        } catch (err) {
            console.error('Recertify error:', err);
            alert(`Error: ${err.message}`);
        }
    };

    window.syncPiecesCountToPallet = async function() {
        if (!latestPiecesResult && currentPiecesList.length === 0) {
            alert('Please run piece count first.');
            return;
        }

        const count = currentPiecesList.length || (latestPiecesResult ? latestPiecesResult.total_pieces : 0);
        const confirmSync = confirm(`Reconcile Active Pallet with Verified Piece Count?\n\nVerified Total: ${count} Units\nThis will record certified inventory in WMS.`);
        if (!confirmSync) return;

        try {
            const res = await fetch('/api/vision/sync-audit-count', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    total_bundles: Math.max(1, Math.round(count / 10)),
                    units_per_bundle: 10
                })
            });

            const data = await res.json();
            if (res.ok && data.success) {
                alert(`Success! Reconciled with ${count} verified pieces.`);
                closeVisionCountingModal();
                if (typeof window.palletModule !== 'undefined' && window.palletModule.loadPallets) {
                    window.palletModule.loadPallets();
                }
            } else {
                alert(`Sync Error: ${data.error || 'Failed to reconcile count'}`);
            }
        } catch (e) {
            console.error('Sync piece count error:', e);
            alert(`Error: ${e.message}`);
        }
    };


    // -------------------------------------------------------------------------
    // OPTION 2: BUNDLE COUNTING & MULTI-VIEW STACK DECONSTRUCTION
    // -------------------------------------------------------------------------

    window.previewBundleAngle = function(slotIndex, input) {
        if (!input.files || !input.files[0]) return;
        const file = input.files[0];
        const reader = new FileReader();
        reader.onload = function(e) {
            const previewImg = document.getElementById(`bundleAnglePreview${slotIndex}`);
            const placeholder = document.getElementById(`bundleAnglePlaceholder${slotIndex}`);
            if (previewImg) {
                previewImg.src = e.target.result;
                previewImg.style.display = 'block';
            }
            if (placeholder) {
                placeholder.style.display = 'none';
            }
        };
        reader.readAsDataURL(file);
    };

    window.loadBundleSampleDemo = function(presetKey) {
        const a1 = document.getElementById('bundleAnglePreview1');
        const a2 = document.getElementById('bundleAnglePreview2');

        if (presetKey === 'timber_48') {
            if (a1) { a1.src = '/static/test_scenes/sample_timber_angle1_front.jpg'; a1.style.display = 'block'; }
            if (a2) { a2.src = '/static/test_scenes/sample_timber_angle2_side.jpg'; a2.style.display = 'block'; }
        } else if (presetKey === 'multistack_84') {
            if (a1) { a1.src = '/static/test_scenes/sample_multistack_angle1_front.jpg'; a1.style.display = 'block'; }
            if (a2) { a2.src = '/static/test_scenes/sample_multistack_angle2_side.jpg'; a2.style.display = 'block'; }
        }

        ['1', '2'].forEach(id => {
            const pl = document.getElementById(`bundleAnglePlaceholder${id}`);
            if (pl) pl.style.display = 'none';
        });

        window.executeBundleCount(presetKey);
    };

    window.executeBundleCount = async function(presetKey = null) {
        const btn = document.getElementById('btnRunBundleCount');
        const spinner = document.getElementById('bundleProcessingStatus');
        const resultContainer = document.getElementById('bundleResultContainer');

        if (btn) btn.disabled = true;
        if (spinner) spinner.style.display = 'block';
        if (resultContainer) resultContainer.style.display = 'none';

        try {
            const formData = new FormData();
            const mult = document.getElementById('bundleDepthMultiplier')?.value || '1';
            formData.append('depth_multiplier', mult);

            const selectedSku = document.getElementById('bundlesSkuSelect')?.value || selectedBundlesSkuId || '';
            if (selectedSku) {
                formData.append('sku_id', selectedSku);
            }

            if (presetKey) {
                formData.append('preset_name', presetKey);
            } else {
                const f1 = document.getElementById('fileBundleAngle1')?.files[0];
                const f2 = document.getElementById('fileBundleAngle2')?.files[0];
                if (f1) formData.append('angle1', f1);
                if (f2) formData.append('angle2', f2);
            }

            const res = await fetch('/api/pallets/count-bundles', {
                method: 'POST',
                body: formData
            });

            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Failed to compute bundle count');
            }

            latestBundlesResult = data;
            renderBundleResults(data);

        } catch (err) {
            console.error('Bundle audit error:', err);
            alert(`Audit Error: ${err.message}`);
        } finally {
            if (btn) btn.disabled = false;
            if (spinner) spinner.style.display = 'none';
        }
    };

    function renderBundleResults(data) {
        const resultContainer = document.getElementById('bundleResultContainer');
        if (!resultContainer) return;

        resultContainer.style.display = 'flex';

        // Audit Sheet Board Image
        const imgElem = document.getElementById('bundleAuditBoardImg');
        if (imgElem && data.audit_image_url) {
            imgElem.src = `${data.audit_image_url}?t=${Date.now()}`;
        }

        // Total badge
        const totalElem = document.getElementById('bundleTotalBundlesBadge');
        if (totalElem) {
            let label = `${data.total_bundles} BUNDLES`;
            if (data.sku_id) {
                label += ` &bull; ${data.sku_id}`;
            }
            totalElem.innerHTML = label;
        }

        // Difference indicator
        const diffElem = document.getElementById('bundleDifferenceBadge');
        if (diffElem && data.comparison) {
            diffElem.textContent = `DIFFERENCE ${data.comparison.difference || 0}`;
        }

        // Populate Table Rows
        const tbody = document.getElementById('bundleStacksTableBody');
        if (tbody && data.stacks) {
            tbody.innerHTML = data.stacks.map(s => {
                const hexColor = s.color_hex || '#0ea5e9';
                return `
                    <tr>
                        <td style="display:flex; align-items:center; gap:8px; padding:6px 4px;">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:2px; background:${hexColor};"></span>
                            <b>${s.name}</b>
                        </td>
                        <td style="text-align:center; font-weight:700; padding:6px 4px;">${s.layers}</td>
                        <td style="text-align:center; font-family:'JetBrains Mono',monospace; color:#38bdf8; padding:6px 4px;">${s.formula}</td>
                        <td style="text-align:right; font-weight:800; font-size:0.95rem; color:#10b981; padding:6px 4px;">${s.bundles}</td>
                    </tr>
                `;
            }).join('');
        }

        // Rule and cross checks
        const ruleElem = document.getElementById('bundleRuleSummaryText');
        if (ruleElem && data.rule_used) {
            ruleElem.textContent = data.rule_used;
        }

        resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    window.syncBundlesCountToPallet = async function() {
        if (!latestBundlesResult) {
            alert('Please run bundle count first.');
            return;
        }

        const count = latestBundlesResult.total_bundles;
        const confirmSync = confirm(`Reconcile Pallet with Certified Bundle Count?\n\nVerified Count: ${count} Bundles\nThis will synchronize active inventory records.`);
        if (!confirmSync) return;

        try {
            const res = await fetch('/api/vision/sync-audit-count', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    total_bundles: count,
                    units_per_bundle: 10
                })
            });

            const data = await res.json();
            if (res.ok && data.success) {
                alert(`Success! Reconciled with ${count} bundles (${count * 10} pieces).`);
                closeVisionCountingModal();
                if (typeof window.palletModule !== 'undefined' && window.palletModule.loadPallets) {
                    window.palletModule.loadPallets();
                }
            } else {
                alert(`Sync Error: ${data.error || 'Failed to reconcile count'}`);
            }
        } catch (e) {
            console.error('Sync bundle count error:', e);
            alert(`Error: ${e.message}`);
        }
    };

    window.openPiecesImageFullscreen = function() {
        const imgElem = document.getElementById('piecesResultImg');
        if (!imgElem || !imgElem.src) return;
        window.open(imgElem.src, '_blank');
    };

    window.openBundleImageFullscreen = function() {
        const imgElem = document.getElementById('bundleAuditBoardImg');
        if (!imgElem || !imgElem.src) return;
        window.open(imgElem.src, '_blank');
    };

    // =========================================================================
    // 3D PALLET MATRIX DIGITAL TWIN & OCCLUDED REAR BOXES VIEWER (Three.js)
    // =========================================================================

    let threeScene = null;
    let threeCamera = null;
    let threeRenderer = null;
    let threeControls = null;
    let threeBoxMeshes = [];
    let isExploded = false;
    let isXRay = false;
    let currentMatrixParams = null;
    let activeMatrixData = null;
    let threeAnimationId = null;

    window.adjust3DMatrixParam = function(param, delta) {
        if (!currentMatrixParams) {
            currentMatrixParams = { layers: 4, columns: 3, depth: 2 };
        }
        isCustomMatrixManuallyTuned = true;
        currentMatrixParams[param] = Math.max(1, Math.min(12, (currentMatrixParams[param] || 1) + delta));
        
        const elemMap = { layers: 'matrixValLayers', columns: 'matrixValColumns', depth: 'matrixValDepth' };
        if (elemMap[param]) {
            const el = document.getElementById(elemMap[param]);
            if (el) el.textContent = currentMatrixParams[param];
        }
        
        // Re-execute piece count with custom matrix
        window.executePieceCount(false);
    };

    window.toggleExplode3D = function() {
        isExploded = !isExploded;
        const btn = document.getElementById('btnToggleExplode3D');
        if (btn) {
            btn.innerHTML = isExploded ? 
                '<i class="fas fa-compress-arrows-alt"></i> <span>Compact Stack</span>' :
                '<i class="fas fa-arrows-split-up-and-left"></i> <span>Explode 3D Stack</span>';
            btn.style.background = isExploded ? '#0284c7' : '#334155';
        }
        animateExplode(isExploded);
    };

    window.toggleXRay3D = function() {
        isXRay = !isXRay;
        const btn = document.getElementById('btnToggleXRay3D');
        if (btn) {
            btn.innerHTML = isXRay ? 
                '<i class="fas fa-eye-slash"></i> <span>Solid View</span>' : 
                '<i class="fas fa-eye"></i> <span>X-Ray Glass</span>';
            btn.style.background = isXRay ? '#0284c7' : '#334155';
        }
        threeBoxMeshes.forEach(mesh => {
            if (!mesh.userData.isHidden) {
                if (isXRay) {
                    mesh.material.transparent = true;
                    mesh.material.opacity = 0.28;
                } else {
                    mesh.material.transparent = false;
                    mesh.material.opacity = 1.0;
                }
            }
        });
    };

    window.reset3DCamera = function() {
        if (!threeCamera || !threeControls) return;
        threeCamera.position.set(4.8, 4.4, 6.0);
        threeControls.target.set(0, 1.3, 0);
        threeControls.update();
    };

    function animateExplode(explodeState) {
        const factor = explodeState ? 1.55 : 1.0;
        threeBoxMeshes.forEach(mesh => {
            const orig = mesh.userData.origPos;
            if (orig) {
                mesh.position.x = orig.x * (explodeState ? factor : 1.0);
                mesh.position.y = orig.y + (explodeState ? (mesh.userData.layer * 0.3) : 0);
                mesh.position.z = orig.z * (explodeState ? factor : 1.0);
                if (mesh.userData.edgesMesh) {
                    mesh.userData.edgesMesh.position.copy(mesh.position);
                }
            }
        });
    }

    function init3DPalletViewer(matrix3D) {
        if (typeof THREE === 'undefined') {
            console.warn('Three.js library not loaded yet');
            return;
        }

        const container = document.getElementById('threeJsCanvasContainer');
        if (!container) return;

        const loadingNotice = document.getElementById('threeJsLoadingNotice');
        if (loadingNotice) loadingNotice.style.display = 'none';

        // Clear previous renderer canvas if existing
        while (container.firstChild) {
            if (container.firstChild.id === 'threeJsLoadingNotice' || 
                container.firstChild.id === 'threeJsHoverInfo' || 
                container.firstChild.tagName === 'DIV') {
                break;
            }
            container.removeChild(container.firstChild);
        }

        activeMatrixData = matrix3D;
        threeBoxMeshes = [];
        isExploded = false;
        isXRay = false;

        const w = container.clientWidth || 700;
        const h = container.clientHeight || 380;

        // 1. Scene
        threeScene = new THREE.Scene();
        threeScene.background = new THREE.Color(0x020617); // Slate 950

        // 2. Camera
        threeCamera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
        threeCamera.position.set(4.8, 4.4, 6.0);

        // 3. Renderer
        threeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        threeRenderer.setSize(w, h);
        threeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        threeRenderer.shadowMap.enabled = true;
        threeRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
        container.insertBefore(threeRenderer.domElement, container.firstChild);

        // 4. Orbit Controls
        const cols = Math.max(1, matrix3D.columns || 3);
        const depth = Math.max(1, matrix3D.rows || matrix3D.depth || 1);
        const layers = Math.max(1, matrix3D.layers || 4);
        const isRegularGrid = (
            matrix3D.reconstruction_mode === 'OPERATOR_CONFIRMED' ||
            matrix3D.reconstruction_mode === 'STRUCTURED_PALLET_RECONSTRUCTION'
        );
        const SCENE_SPAN_X = Math.max(2.4, Math.min(5.6, cols * 0.96));
        const SCENE_SPAN_Y = Math.max(1.8, Math.min(4.5, layers * 0.78));

        const hasPallet = matrix3D.has_pallet === true;
        const palletW = isRegularGrid ? (cols * 0.94 + 0.36) : (SCENE_SPAN_X + 0.45);
        const palletD = isRegularGrid ? Math.max(depth * 0.94 + 0.36, 1.5) : 1.6;
        const palletH = hasPallet ? 0.16 : 0.0;

        if (typeof THREE.OrbitControls !== 'undefined') {
            threeControls = new THREE.OrbitControls(threeCamera, threeRenderer.domElement);
            threeControls.enableDamping = true;
            threeControls.dampingFactor = 0.08;
            threeControls.maxPolarAngle = Math.PI / 2 - 0.02; // Don't go below ground
            threeControls.minDistance = 2.0;
            threeControls.maxDistance = 20.0;
            const targetY = isRegularGrid ? (layers * 0.74 / 2) + palletH : (SCENE_SPAN_Y / 2) + palletH;
            threeControls.target.set(0, targetY, 0);
            threeControls.update();
        }

        // 5. Lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.75);
        threeScene.add(ambientLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.85);
        dirLight.position.set(8, 14, 10);
        dirLight.castShadow = true;
        dirLight.shadow.mapSize.width = 1024;
        dirLight.shadow.mapSize.height = 1024;
        threeScene.add(dirLight);

        const blueRimLight = new THREE.DirectionalLight(0x38bdf8, 0.45);
        blueRimLight.position.set(-8, 6, -8);
        threeScene.add(blueRimLight);

        // 6. Floor Grid with dark sleek style
        const gridHelper = new THREE.GridHelper(16, 16, 0x1e293b, 0x0f172a);
        gridHelper.position.y = 0;
        threeScene.add(gridHelper);

        // 7. Wooden Pallet Base (only render if image evidence supports a pallet base)
        if (hasPallet) {
            const woodMat = new THREE.MeshStandardMaterial({
                color: 0x92663b,
                roughness: 0.85,
                metalness: 0.05
            });

            const slatCount = Math.max(5, cols * 2 + 1);
            const slatW = palletW / slatCount * 0.75;
            for (let i = 0; i < slatCount; i++) {
                const slatGeo = new THREE.BoxGeometry(slatW, 0.04, palletD);
                const slatMesh = new THREE.Mesh(slatGeo, woodMat);
                const xPos = -palletW / 2 + (i + 0.5) * (palletW / slatCount);
                slatMesh.position.set(xPos, palletH - 0.02, 0);
                slatMesh.receiveShadow = true;
                threeScene.add(slatMesh);
            }

            for (let s = -1; s <= 1; s++) {
                const runnerGeo = new THREE.BoxGeometry(0.12, palletH - 0.04, palletD);
                const runnerMesh = new THREE.Mesh(runnerGeo, woodMat);
                runnerMesh.position.set(s * (palletW * 0.42), (palletH - 0.04) / 2, 0);
                runnerMesh.receiveShadow = true;
                threeScene.add(runnerMesh);
            }
        }

        // Precompute cumulative layer heights for irregular 3D stacks so boxes rest solidly on lower layers
        const layerMaxH = {};
        (matrix3D.boxes || []).forEach(b => {
            const lyr = b.layer || 0;
            const bh = isRegularGrid ? 0.68 : Math.max(0.48, Math.min(1.35, (b.rel_h_ratio || 1.0) * 0.70));
            if (!layerMaxH[lyr] || bh > layerMaxH[lyr]) layerMaxH[lyr] = bh;
        });
        const layerBaseY = {};
        let cumY = palletH;
        for (let lyr = 0; lyr < layers + 2; lyr++) {
            layerBaseY[lyr] = cumY;
            cumY += (layerMaxH[lyr] || 0.68) + 0.02;
        }

        // 8. Construct 3D Cuboids (Visible front/side solid, Shared Corner accented, Hidden interior translucent)
        (matrix3D.boxes || []).forEach(b => {
            let boxW = 0.86;
            let boxH = 0.68;
            let boxD = 0.86;
            let posX = 0;
            let posY = 0;
            let posZ = 0;

            if (isRegularGrid) {
                posX = (b.col - (cols - 1) / 2) * 0.92;
                posY = (b.layer || 0) * 0.72 + (boxH / 2) + palletH;
                posZ = (b.depth - (depth - 1) / 2) * 0.92;
            } else {
                boxW = Math.max(0.68, Math.min(2.20, (b.rel_w_ratio || 1.0) * 1.15));
                boxH = Math.max(0.48, Math.min(1.35, (b.rel_h_ratio || 1.0) * 0.70));
                boxD = Math.max(0.76, Math.min(1.55, boxW * 0.88));
                const lyr = b.layer || 0;
                posX = (cols === 1 && b.rel_x_offset !== undefined)
                    ? (b.rel_x_offset * 1.25)
                    : (((b.norm_x !== undefined ? b.norm_x : 0.5) - 0.5) * SCENE_SPAN_X);
                posY = (layerBaseY[lyr] !== undefined ? layerBaseY[lyr] : palletH) + (boxH / 2);
                posZ = 0;
            }

            const boxGeo = new THREE.BoxGeometry(boxW, boxH, boxD);
            const edgesGeo = new THREE.EdgesGeometry(boxGeo);

            let boxMat = null;
            let edgeMat = null;

            if (b.is_hidden) {
                boxMat = new THREE.MeshPhysicalMaterial({
                    color: 0x0284c7,
                    roughness: 0.15,
                    transmission: 0.75,
                    opacity: 0.38,
                    transparent: true,
                    depthWrite: false
                });
                edgeMat = new THREE.LineBasicMaterial({
                    color: 0x38bdf8,
                    linewidth: 2,
                    transparent: true,
                    opacity: 0.85
                });
            } else if (b.face_role === 'shared_corner') {
                boxMat = new THREE.MeshStandardMaterial({
                    color: 0xd4a373,
                    roughness: 0.70,
                    metalness: 0.06
                });
                edgeMat = new THREE.LineBasicMaterial({
                    color: 0x8b5cf6,
                    linewidth: 2
                });
            } else {
                boxMat = new THREE.MeshStandardMaterial({
                    color: 0xcba06c,
                    roughness: 0.75,
                    metalness: 0.05
                });
                edgeMat = new THREE.LineBasicMaterial({
                    color: 0x6e471d,
                    linewidth: 1
                });
            }

            const mesh = new THREE.Mesh(boxGeo, boxMat);
            mesh.position.set(posX, posY, posZ);
            mesh.castShadow = !b.is_hidden;
            mesh.receiveShadow = true;

            // Edge highlight wireframe
            const edgeLine = new THREE.LineSegments(edgesGeo, edgeMat);
            edgeLine.position.copy(mesh.position);
            threeScene.add(edgeLine);

            mesh.userData = {
                id: b.id,
                layer: b.layer,
                col: b.col,
                depth: b.depth,
                status: b.status,
                label: b.label || `Box #${b.id}`,
                isHidden: b.is_hidden,
                origPos: { x: posX, y: posY, z: posZ },
                edgesMesh: edgeLine
            };

            threeBoxMeshes.push(mesh);
            threeScene.add(mesh);
        });

        // 9. Interactive Raycasting Tooltip on Mouse Hover
        const raycaster = new THREE.Raycaster();
        const mouse = new THREE.Vector2();
        const tooltip = document.getElementById('threeJsHoverInfo');

        container.onmousemove = function(event) {
            const rect = container.getBoundingClientRect();
            mouse.x = ((event.clientX - rect.left) / container.clientWidth) * 2 - 1;
            mouse.y = -((event.clientY - rect.top) / container.clientHeight) * 2 + 1;

            raycaster.setFromCamera(mouse, threeCamera);
            const intersects = raycaster.intersectObjects(threeBoxMeshes);

            if (intersects.length > 0) {
                const hit = intersects[0].object;
                const d = hit.userData;
                if (tooltip) {
                    const tagCol = d.isHidden ? '#38bdf8' : '#10b981';
                    const tagText = d.isHidden ? 'OCCLUDED REAR BOX' : 'VISIBLE BOX';
                    tooltip.innerHTML = `
                        <div style="font-weight:800; color:#fff; display:flex; align-items:center; gap:6px;">
                            <span style="color:${tagCol};">[${tagText}]</span> ${d.label}
                        </div>
                        <div style="font-size:0.7rem; color:#94a3b8; font-family:'JetBrains Mono',monospace;">
                            Position: Layer ${d.layer + 1} &bull; Col ${d.col + 1} &bull; Depth ${d.depth + 1}
                        </div>
                    `;
                    tooltip.style.display = 'block';
                }
            } else {
                if (tooltip) tooltip.style.display = 'none';
            }
        };

        container.onmouseleave = function() {
            if (tooltip) tooltip.style.display = 'none';
        };

        // Resize handler
        window.onresize = function() {
            if (!container || !threeCamera || !threeRenderer) return;
            const newW = container.clientWidth;
            const newH = container.clientHeight;
            if (newW && newH) {
                threeCamera.aspect = newW / newH;
                threeCamera.updateProjectionMatrix();
                threeRenderer.setSize(newW, newH);
            }
        };

        // Animation Loop
        if (threeAnimationId) cancelAnimationFrame(threeAnimationId);
        function animate() {
            threeAnimationId = requestAnimationFrame(animate);
            if (threeControls) threeControls.update();
            threeRenderer.render(threeScene, threeCamera);
        }
        animate();
    }

    // Initialize Drag & Drop on the unified dropzone
    function initUnifiedDropZone() {
        const dropZone = document.getElementById('unifiedDropZone');
        const fileInput = document.getElementById('filePiecesImage');
        if (!dropZone || !fileInput) return;

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.borderColor = '#38bdf8';
                dropZone.style.background = 'rgba(2, 132, 199, 0.15)';
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.borderColor = '#0284c7';
                dropZone.style.background = '#1e293b';
            }, false);
        });

        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files && files.length > 0) {
                fileInput.files = files;
                window.previewPiecesImage(fileInput);
            }
        }, false);
    }

    // =========================================================================
    // INLINE PALLET VISION COUNTING WORKBENCH CONTROLLER
    // =========================================================================
    let wbMode = 'pieces'; // 'pieces' or 'bundles'
    let wbSource = 'upload'; // 'upload' or 'camera'
    let wbCurrentPieces = [];
    let wbRawImageUrl = '';
    let wbLatestResult = null;
    let wbCurrentMatrix = { rows: 5, columns: 5, layers: 5 };
    let wbThreeScene, wbThreeCamera, wbThreeRenderer, wbThreeControls;
    let wbThreeBoxMeshes = [];
    let wbIsExploded = false;
    let wbIsXRay = false;
    let wbThreeAnimId = null;

    let wbSelectedFile = null;
    let wbCountRequestId = 0;
    let wbRegions = [];
    let wbCurrentTool = 'none';
    let wbDrawingPolyPoints = [];
    let wbIsDraggingRect = false;
    let wbDragStart = null;

    window.openPalletCountingWorkbench = function(initialMode = 'pieces', triggerUpload = false) {
        const wb = document.getElementById('palletCountingWorkbench');
        if (wb) {
            wb.scrollIntoView({ behavior: 'smooth', block: 'start' });
            window.setWorkbenchMode(initialMode);
            
            // Synchronize cameras from palletCameraSelect
            const mainCamSelect = document.getElementById('palletCameraSelect');
            const wbCamSelect = document.getElementById('wbCameraSelect');
            if (mainCamSelect && wbCamSelect) {
                wbCamSelect.innerHTML = mainCamSelect.innerHTML;
                wbCamSelect.value = mainCamSelect.value;
            }

            if (triggerUpload) {
                setTimeout(() => {
                    window.triggerWorkbenchUpload();
                }, 200);
            }
        }
    };

    // Override openVisionCountingModal to use the inline workbench directly
    window.openVisionCountingModal = function(initialMode = 'pieces') {
        window.openPalletCountingWorkbench(initialMode);
    };

    window.setWorkbenchMode = function(mode) {
        wbMode = mode;
        const btnP = document.getElementById('wbModePiecesBtn');
        const btnB = document.getElementById('wbModeBundlesBtn');
        const regBar = document.getElementById('wbRegionControlsBar');
        const matWrap = document.getElementById('wbBundleMaterialSelectWrap');
        const glassBar = document.getElementById('wbGlassProfileBar');
        const matSelect = document.getElementById('wbBundleMaterialSelect');
        const currentMat = matSelect ? matSelect.value : '';

        if (mode === 'pieces') {
            if (btnP) { btnP.style.background = '#0284c7'; btnP.style.color = '#fff'; }
            if (btnB) { btnB.style.background = 'transparent'; btnB.style.color = '#94a3b8'; }
            if (regBar) regBar.style.display = 'flex';
            if (matWrap) matWrap.style.display = 'none';
            if (glassBar) glassBar.style.display = 'none';
            // Clear target SKU selector if it was locked to a bundle/glass SKU
            const wbSkuSel = document.getElementById('wbTargetSkuSelect');
            if (wbSkuSel && wbSkuSel.value && wbSkuSel.value.startsWith('GLS-')) {
                wbSkuSel.value = '';
            }
        } else {
            if (btnB) { btnB.style.background = '#0284c7'; btnB.style.color = '#fff'; }
            if (btnP) { btnP.style.background = 'transparent'; btnP.style.color = '#94a3b8'; }
            if (regBar) regBar.style.display = 'none';
            if (matWrap) matWrap.style.display = 'inline-flex';
            if (glassBar) {
                glassBar.style.display = (currentMat === 'glass_bundles') ? 'flex' : 'none';
            }
            if (currentMat === 'glass_bundles') {
                window.loadWorkbenchGlassProfiles();
            }
            if (typeof window.setWorkbenchRegionTool === 'function') {
                window.setWorkbenchRegionTool('none');
            }
        }
    };

    window.onWorkbenchBundleMaterialChange = function(mat) {
        const glassBar = document.getElementById('wbGlassProfileBar');
        if (glassBar) {
            glassBar.style.display = (mat === 'glass_bundles') ? 'flex' : 'none';
        }
        if (mat === 'glass_bundles') {
            window.loadWorkbenchGlassProfiles();
        }
        if (wbRawImageUrl && wbMode === 'bundles') {
            window.executeWorkbenchCount();
        }
    };

    let wbGlassProfilesCache = [];
    window.loadWorkbenchGlassProfiles = async function() {
        try {
            const res = await fetch('/api/pallets/glass-profiles');
            const data = await res.json();
            if (res.ok && data.success && Array.isArray(data.profiles)) {
                wbGlassProfilesCache = data.profiles;
                const sel = document.getElementById('wbGlassProfileSelect');
                if (sel) {
                    const currVal = sel.value;
                    sel.innerHTML = '<option value="">-- Custom / Manual Dimensions --</option>';
                    data.profiles.forEach(p => {
                        const opt = document.createElement('option');
                        opt.value = p.id;
                        opt.textContent = `${p.name} (${p.length}×${p.width}×${p.thickness} ${p.unit})`;
                        sel.appendChild(opt);
                    });
                    if (currVal && data.profiles.some(p => p.id === currVal)) {
                        sel.value = currVal;
                    } else if (data.profiles.length > 0) {
                        sel.value = data.profiles[0].id;
                        window.onWorkbenchGlassProfileChange(data.profiles[0].id);
                    }
                }
            }
        } catch (e) {
            console.warn('Failed to load glass profiles:', e);
        }
    };

    window.onWorkbenchGlassProfileChange = function(profileId) {
        const p = wbGlassProfilesCache.find(x => x.id === profileId);
        if (p) {
            const lIn = document.getElementById('wbGlassLengthInput');
            const wIn = document.getElementById('wbGlassWidthInput');
            const tIn = document.getElementById('wbGlassThicknessInput');
            const uSel = document.getElementById('wbGlassUnitSelect');
            const pkgSel = document.getElementById('wbGlassPackagingSelect');
            const ppbIn = document.getElementById('wbGlassSheetsPerBundleInput');
            if (lIn) lIn.value = p.length;
            if (wIn) wIn.value = p.width;
            if (tIn) tIn.value = p.thickness;
            if (uSel && p.unit) uSel.value = p.unit;
            if (pkgSel && p.packaging_type) pkgSel.value = p.packaging_type;
            if (ppbIn) ppbIn.value = p.pieces_per_bundle || '';

            if (p.pieces_per_bundle) {
                const upbIn = document.getElementById('wbUnitsPerBundleInput');
                if (upbIn) upbIn.value = p.pieces_per_bundle;
            }
            const uomSel = document.getElementById('wbUomSelect');
            if (uomSel) uomSel.value = 'SHEETS';

            if (wbRawImageUrl && wbMode === 'bundles') {
                window.executeWorkbenchCount();
            }
        }
    };

    window.onWorkbenchGlassDimInput = function() {
        if (wbRawImageUrl && wbMode === 'bundles') {
            clearTimeout(window._glassDimTimeout);
            window._glassDimTimeout = setTimeout(() => {
                window.executeWorkbenchCount();
            }, 400);
        }
    };

    window.saveCurrentGlassProfilePrompt = async function() {
        const l = parseFloat(document.getElementById('wbGlassLengthInput')?.value || '2440');
        const w = parseFloat(document.getElementById('wbGlassWidthInput')?.value || '1830');
        const t = parseFloat(document.getElementById('wbGlassThicknessInput')?.value || '6');
        const u = document.getElementById('wbGlassUnitSelect')?.value || 'mm';
        const pkg = document.getElementById('wbGlassPackagingSelect')?.value || 'A_FRAME_STILLAGE';
        const ppb = document.getElementById('wbGlassSheetsPerBundleInput')?.value;

        const defaultName = `Glass Pack (${l}×${w}×${t} ${u})`;
        const name = prompt('Enter a name for this Glass Measurement Profile:', defaultName);
        if (!name) return;

        try {
            const res = await fetch('/api/pallets/glass-profiles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name.trim(),
                    length: l,
                    width: w,
                    thickness: t,
                    unit: u,
                    packaging_type: pkg,
                    pieces_per_bundle: ppb ? parseInt(ppb, 10) : null
                })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                if (typeof showToast === 'function') {
                    showToast(`Glass profile '${name}' saved successfully!`, 'success');
                }
                await window.loadWorkbenchGlassProfiles();
                const sel = document.getElementById('wbGlassProfileSelect');
                if (sel && data.profile?.id) {
                    sel.value = data.profile.id;
                }
            } else {
                alert(`Error saving profile: ${data.error || 'Unknown error'}`);
            }
        } catch (e) {
            console.error('Error saving glass profile:', e);
            alert(`Network error: ${e.message}`);
        }
    };

    window.triggerWorkbenchUpload = function() {
        window.setWorkbenchSource('upload');
        const fi = document.getElementById('wbFileInput');
        if (fi) {
            fi.click();
        }
    };

    window.setWorkbenchSource = function(source) {
        wbSource = source;
        const btnU = document.getElementById('wbSourceUploadBtn');
        const btnC = document.getElementById('wbSourceCameraBtn');
        const camWrap = document.getElementById('wbCameraSelectWrap');
        const dropZone = document.getElementById('wbDropZone');
        const cameraViewWrap = document.getElementById('wbCameraViewWrap');
        const camSelect = document.getElementById('wbCameraSelect') || document.getElementById('palletCameraSelect');
        const camId = camSelect ? camSelect.value : 'cam_inbound_01';

        if (source === 'upload') {
            if (btnU) { btnU.style.background = '#10b981'; btnU.style.color = '#fff'; }
            if (btnC) { btnC.style.background = 'transparent'; btnC.style.color = '#94a3b8'; }
            if (camWrap) camWrap.style.display = 'none';
            if (dropZone) dropZone.style.display = 'flex';
            if (cameraViewWrap) cameraViewWrap.style.display = 'none';
        } else {
            if (btnC) { btnC.style.background = '#10b981'; btnC.style.color = '#fff'; }
            if (btnU) { btnU.style.background = 'transparent'; btnU.style.color = '#94a3b8'; }
            if (camWrap) camWrap.style.display = 'inline-flex';
            if (dropZone) dropZone.style.display = 'none';
            if (cameraViewWrap) cameraViewWrap.style.display = 'block';

            const feedImg = document.getElementById('palletLiveFeedImg');
            const feedLabel = document.getElementById('wbCamFeedLabel');
            if (feedImg) feedImg.src = `/video_feed/${camId}?t=${Date.now()}`;
            if (feedLabel) feedLabel.textContent = `CAM: ${camId}`;
        }
    };

    window.onWorkbenchCameraChange = function() {
        const camSelect = document.getElementById('wbCameraSelect');
        const camId = camSelect ? camSelect.value : 'cam_inbound_01';
        const feedImg = document.getElementById('palletLiveFeedImg');
        const feedLabel = document.getElementById('wbCamFeedLabel');
        if (feedImg) feedImg.src = `/video_feed/${camId}?t=${Date.now()}`;
        if (feedLabel) feedLabel.textContent = `CAM: ${camId}`;
    };

    window.replaceWorkbenchImage = function() {
        window.setWorkbenchSource('upload');
        lastWbUploadFile = null;
        lastWbUploadTime = 0;
        if (typeof window.clearWorkbenchRegions === 'function') {
            window.clearWorkbenchRegions(true);
        }
        const fi = document.getElementById('wbFileInput');
        if (fi) {
            fi.value = ''; // Reset so selecting the same image file again triggers preview
            fi.click();
        }
    };

    window.removeWorkbenchImage = function() {
        wbCountRequestId++; // Invalidate any pending in-flight requests
        wbSelectedFile = null;
        lastWbUploadFile = null;
        lastWbUploadTime = 0;
        wbLatestResult = null;
        wbCurrentPieces = [];
        wbRawImageUrl = '';
        if (typeof window.clearWorkbenchRegions === 'function') {
            window.clearWorkbenchRegions(true);
        }

        const fi = document.getElementById('wbFileInput');
        if (fi) fi.value = '';

        const previewImg = document.getElementById('wbPreviewImg');
        const placeholder = document.getElementById('wbPlaceholder');
        const fiWrap = document.getElementById('wbSelectedFileInfo');
        const fnSpan = document.getElementById('wbSelectedFileName');
        if (previewImg) {
            previewImg.src = '';
            previewImg.style.display = 'none';
        }
        if (placeholder) placeholder.style.display = 'block';
        if (fiWrap) fiWrap.style.display = 'none';
        if (fnSpan) fnSpan.textContent = '';

        // Hide interactive stage & clear canvas
        const stageCard = document.getElementById('wbInteractiveStageCard');
        if (stageCard) stageCard.style.display = 'none';
        const img = document.getElementById('wbResultImg');
        if (img) img.src = '';
        const overlay = document.getElementById('wbBadgesOverlay');
        if (overlay) overlay.innerHTML = '';
        const pills = document.getElementById('wbClustersPills');
        if (pills) pills.innerHTML = '';

        // Reset Results Hero Card
        const totalBadge = document.getElementById('wbTotalBadge');
        if (totalBadge) totalBadge.textContent = '0 PIECES';
        const statusBadge = document.getElementById('wbVerificationStatusBadge');
        if (statusBadge) {
            statusBadge.textContent = 'PROPOSED (Idle)';
            statusBadge.style.color = '#94a3b8';
            statusBadge.style.borderColor = 'rgba(148,163,184,0.2)';
            statusBadge.style.background = 'rgba(148,163,184,0.12)';
        }
        const formulaElem = document.getElementById('wbAutoGeometryFormula');
        if (formulaElem) {
            formulaElem.textContent = 'Awaiting Pallet Detection...';
            formulaElem.style.color = '#38bdf8';
        }
        const methodBadge = document.getElementById('wbCountingMethodBadge');
        if (methodBadge) methodBadge.textContent = 'AUTOMATED_CV';

        const statVis = document.getElementById('wbStatVisible');
        const statInf = document.getElementById('wbStatInferred');
        const statForm = document.getElementById('wbStatFormula');
        const statTare = document.getElementById('wbStatTare');
        if (statVis) statVis.textContent = '0';
        if (statInf) statInf.textContent = '0';
        if (statForm) statForm.textContent = '--';
        if (statTare) statTare.textContent = '0 Pallet Base Detected';

        // Clear 3D model canvas immediately
        initWb3DPalletViewer(null);

        if (typeof showToast === 'function') {
            showToast('Pallet image and count state removed.', 'info');
        }
    };

    window.clearWorkbenchCount = function(silent = false) {
        wbCountRequestId++; // Invalidate any pending in-flight requests
        // Purge detections, markers, geometry, results, and 3D visualization, preserving the loaded image
        wbLatestResult = null;
        wbCurrentPieces = [];

        const stageCard = document.getElementById('wbInteractiveStageCard');
        if (stageCard) stageCard.style.display = 'none';
        const overlay = document.getElementById('wbBadgesOverlay');
        if (overlay) overlay.innerHTML = '';
        const pills = document.getElementById('wbClustersPills');
        if (pills) pills.innerHTML = '';

        const totalBadge = document.getElementById('wbTotalBadge');
        if (totalBadge) totalBadge.textContent = '0 PIECES';
        const statusBadge = document.getElementById('wbVerificationStatusBadge');
        if (statusBadge) {
            statusBadge.textContent = 'PROPOSED (Idle)';
            statusBadge.style.color = '#94a3b8';
            statusBadge.style.borderColor = 'rgba(148,163,184,0.2)';
            statusBadge.style.background = 'rgba(148,163,184,0.12)';
        }
        const formulaElem = document.getElementById('wbAutoGeometryFormula');
        if (formulaElem) {
            formulaElem.textContent = 'Awaiting Pallet Detection...';
            formulaElem.style.color = '#38bdf8';
        }
        const statVis = document.getElementById('wbStatVisible');
        const statInf = document.getElementById('wbStatInferred');
        const statForm = document.getElementById('wbStatFormula');
        const statTare = document.getElementById('wbStatTare');
        if (statVis) statVis.textContent = '0';
        if (statInf) statInf.textContent = '0';
        if (statForm) statForm.textContent = '--';
        if (statTare) statTare.textContent = '0 Pallet Base Detected';

        // Clear 3D model canvas
        initWb3DPalletViewer(null);

        if (!silent && typeof showToast === 'function') {
            showToast('Pallet count cleared. Ready to count again.', 'info');
        }
    };

    window.onWorkbenchDropZoneClick = function() {
        if (wbSource === 'upload') {
            const fi = document.getElementById('wbFileInput');
            if (fi) fi.click();
        } else {
            window.executeWorkbenchCount();
        }
    };

    let lastWbUploadFile = null;
    let lastWbUploadTime = 0;

        // =========================================================================
    // STAGE 5: MULTI-VIEW SESSION STATE & WORKBENCH TRAY HELPERS
    // =========================================================================
    let wbMultiViews = []; // Array of { id, label, isRef, file, dataUrl, regions }

    window.getWorkbenchMultiViews = function() {
        return wbMultiViews;
    };

    window.renderWorkbenchMultiViewStrip = function() {
        const strip = document.getElementById('wbMultiViewStrip');
        const pill = document.getElementById('wbMultiViewCountPill');
        if (pill) {
            pill.textContent = `${wbMultiViews.length} View${wbMultiViews.length === 1 ? '' : 's'} Staged`;
        }
        if (!strip) return;
        strip.innerHTML = '';

        if (wbMultiViews.length === 0) {
            strip.innerHTML = `
                <div id="wbMultiViewEmptyPrompt" style="color:#64748b; font-size:0.74rem; font-style:italic; padding:6px 0;">
                    Drop a primary photo below, or click "+ Add View Photo" to stage multiple camera angles (Front, Rear, Left, Right, Top).
                </div>
            `;
            return;
        }

        wbMultiViews.forEach((v, idx) => {
            const card = document.createElement('div');
            card.style.cssText = `
                display:inline-flex; align-items:center; gap:8px; background:#0f172a;
                border:1px solid ${v.isRef ? '#0284c7' : '#334155'}; border-radius:6px;
                padding:4px 8px; flex-shrink:0; font-size:0.72rem; position:relative;
            `;

            const imgThumb = document.createElement('img');
            imgThumb.src = v.dataUrl || (v.file ? URL.createObjectURL(v.file) : '');
            imgThumb.style.cssText = 'width:38px; height:38px; object-fit:cover; border-radius:4px; border:1px solid #475569;';

            const infoDiv = document.createElement('div');
            infoDiv.style.cssText = 'display:flex; flex-direction:column; gap:2px;';

            const labelSel = document.createElement('select');
            labelSel.style.cssText = 'background:#1e293b; color:#38bdf8; border:1px solid #475569; border-radius:3px; font-size:0.68rem; padding:1px 4px; font-weight:700;';
            const labels = ['front', 'rear', 'left', 'right', 'top', 'side', 'perspective'];
            labels.forEach(lbl => {
                const opt = document.createElement('option');
                opt.value = lbl;
                opt.textContent = lbl.toUpperCase();
                if (v.label === lbl) opt.selected = true;
                labelSel.appendChild(opt);
            });
            labelSel.onchange = function() {
                v.label = this.value;
            };

            const actRow = document.createElement('div');
            actRow.style.cssText = 'display:flex; align-items:center; gap:4px;';

            const refBtn = document.createElement('button');
            refBtn.type = 'button';
            refBtn.style.cssText = `
                background:${v.isRef ? '#0284c7' : 'transparent'}; color:${v.isRef ? '#fff' : '#94a3b8'};
                border:1px solid #475569; border-radius:3px; font-size:0.62rem; padding:1px 5px; cursor:pointer; font-weight:700;
            `;
            refBtn.textContent = v.isRef ? '★ REF' : 'Set Ref';
            refBtn.onclick = function() {
                wbMultiViews.forEach(x => x.isRef = false);
                v.isRef = true;
                window.renderWorkbenchMultiViewStrip();
            };

            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.style.cssText = 'background:transparent; color:#ef4444; border:none; font-size:0.75rem; cursor:pointer; padding:0 3px;';
            delBtn.innerHTML = '<i class="fas fa-xmark"></i>';
            delBtn.title = 'Remove this view';
            delBtn.onclick = function() {
                window.removeWorkbenchView(v.id);
            };

            actRow.appendChild(refBtn);
            actRow.appendChild(delBtn);

            infoDiv.appendChild(labelSel);
            infoDiv.appendChild(actRow);

            card.appendChild(imgThumb);
            card.appendChild(infoDiv);
            strip.appendChild(card);
        });
    };

    window.addWorkbenchView = function(fileOrBlob, label = null, isRef = false) {
        if (!fileOrBlob) return;
        const reader = new FileReader();
        reader.onload = function(e) {
            const dataUrl = e.target.result;
            const viewId = 'view_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4);
            const defaultLabels = ['front', 'rear', 'left', 'right', 'top', 'side'];
            const assignedLabel = label || defaultLabels[wbMultiViews.length % defaultLabels.length];
            const shouldBeRef = isRef || (wbMultiViews.length === 0);

            if (shouldBeRef) {
                wbMultiViews.forEach(x => x.isRef = false);
            }

            wbMultiViews.push({
                id: viewId,
                label: assignedLabel,
                isRef: shouldBeRef,
                file: fileOrBlob,
                dataUrl: dataUrl,
                regions: []
            });

            window.renderWorkbenchMultiViewStrip();

            // Set main preview to reference view
            const previewImg = document.getElementById('wbPreviewImg');
            const placeholder = document.getElementById('wbPlaceholder');
            if (previewImg) {
                previewImg.src = dataUrl;
                previewImg.style.display = 'block';
            }
            if (placeholder) placeholder.style.display = 'none';

            window.executeWorkbenchCount();
        };
        reader.readAsDataURL(fileOrBlob);
    };

    window.removeWorkbenchView = function(viewId) {
        const wasRef = wbMultiViews.find(v => v.id === viewId)?.isRef;
        wbMultiViews = wbMultiViews.filter(v => v.id !== viewId);
        if (wasRef && wbMultiViews.length > 0) {
            wbMultiViews[0].isRef = true;
        }
        window.renderWorkbenchMultiViewStrip();
        if (wbMultiViews.length > 0) {
            window.executeWorkbenchCount();
        } else {
            window.clearWorkbenchCount();
        }
    };

    window.clearAllWorkbenchViews = function() {
        wbMultiViews = [];
        window.renderWorkbenchMultiViewStrip();
        window.clearWorkbenchCount();
    };

    window.handleWorkbenchAddViewUpload = function(fileInput) {
        if (fileInput && fileInput.files && fileInput.files[0]) {
            const file = fileInput.files[0];
            fileInput.value = '';
            window.addWorkbenchView(file);
        }
    };

    window.captureWorkbenchCameraAsView = function() {
        const camSel = document.getElementById('wbCameraSelect') || document.getElementById('palletCameraSelect');
        const camId = camSel ? camSel.value : 'cam_inbound_01';

        fetch(`/snapshot/${camId}`)
            .then(res => {
                if (!res.ok) throw new Error('Camera snapshot failed');
                return res.blob();
            })
            .then(blob => {
                const f = new File([blob], `cam_${camId}_${Date.now()}.jpg`, { type: 'image/jpeg' });
                window.addWorkbenchView(f);
                if (typeof showToast === 'function') {
                    showToast(`Captured snapshot from ${camId} into Multi-View session.`, 'success');
                }
            })
            .catch(err => {
                console.warn('[Workbench] Camera snapshot fetch fallback:', err);
                // Fallback: draw live feed element to canvas blob
                const liveImg = document.getElementById('palletLiveFeedImg');
                if (liveImg && liveImg.naturalWidth) {
                    const c = document.createElement('canvas');
                    c.width = liveImg.naturalWidth;
                    c.height = liveImg.naturalHeight;
                    const ctx = c.getContext('2d');
                    ctx.drawImage(liveImg, 0, 0);
                    c.toBlob(b => {
                        if (b) {
                            const f = new File([b], `cam_frame_${Date.now()}.jpg`, { type: 'image/jpeg' });
                            window.addWorkbenchView(f);
                        }
                    }, 'image/jpeg', 0.95);
                } else {
                    if (typeof showToast === 'function') {
                        showToast('Camera capture unavailable. Upload an image view instead.', 'warning');
                    }
                }
            });
    };

    
    window.previewWorkbenchUpload = function(inputOrFile) {
        let file = null;
        if (inputOrFile instanceof File || inputOrFile instanceof Blob) {
            file = inputOrFile;
        } else if (inputOrFile && inputOrFile.files && inputOrFile.files[0]) {
            file = inputOrFile.files[0];
        }
        if (!file) return;

        // Prevent duplicate trigger within 250ms on identical file
        const now = Date.now();
        if (file === lastWbUploadFile && (now - lastWbUploadTime) < 250) {
            return;
        }
        lastWbUploadFile = file;
        lastWbUploadTime = now;

        // Validate image file: allow common formats (AVIF, WebP, PNG, JPEG, BMP, TIFF, GIF, etc.)
        const validExtensions = ['.jpg', '.jpeg', '.png', '.webp', '.avif', '.bmp', '.dib', '.tiff', '.tif', '.gif', '.pbm', '.pgm', '.ppm', '.sr', '.ras', '.jp2'];
        const nonImageExtensions = ['.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.zip', '.tar', '.gz', '.7z', '.exe', '.dll', '.mp4', '.avi', '.mov', '.mp3', '.json', '.xml', '.html'];
        const nameLower = (file.name || '').toLowerCase();
        const hasValidExt = validExtensions.some(ext => nameLower.endsWith(ext));
        const hasNonImageExt = nonImageExtensions.some(ext => nameLower.endsWith(ext));
        const isImageMime = file.type && file.type.startsWith('image/');

        // Explicitly reject known non-image document formats
        if (hasNonImageExt) {
            const err = `Unsupported document format (${file.name || 'file'}). Please upload an image file (JPEG, PNG, WebP, AVIF, TIFF, BMP, GIF).`;
            if (typeof showToast === 'function') showToast(err, 'error'); else alert(err);
            const fi = document.getElementById('wbFileInput');
            if (fi) fi.value = '';
            return;
        }

        // Allow if valid image MIME, recognized image extension, or generic/empty type without forbidden extension
        const isAcceptableImage = isImageMime || hasValidExt || (!file.type || file.type === 'application/octet-stream');
        if (!isAcceptableImage) {
            const err = 'Unsupported file type. Please upload a valid warehouse photo (JPEG, PNG, WebP, AVIF, TIFF, BMP, GIF).';
            if (typeof showToast === 'function') showToast(err, 'error'); else alert(err);
            const fi = document.getElementById('wbFileInput');
            if (fi) fi.value = '';
            return;
        }

        // Purge any previous results/3D state silently (wbCountRequestId is incremented here)
        window.clearWorkbenchCount(true);

        // Store active File object as single source of truth for counting
        wbSelectedFile = file;

        // Reset target SKU selector if switching/uploading in pieces mode to prevent stale glass SKU lock
        if (wbCountingMode === 'pieces') {
            const wbSkuSel = document.getElementById('wbTargetSkuSelect');
            if (wbSkuSel && wbSkuSel.value && wbSkuSel.value.startsWith('GLS-')) {
                wbSkuSel.value = '';
            }
        }

        // Switch source to upload automatically
        wbSource = 'upload';
        const btnU = document.getElementById('wbSourceUploadBtn');
        const btnC = document.getElementById('wbSourceCameraBtn');
        const camWrap = document.getElementById('wbCameraSelectWrap');
        const dropZone = document.getElementById('wbDropZone');
        const cameraViewWrap = document.getElementById('wbCameraViewWrap');

        if (btnU) { btnU.style.background = '#10b981'; btnU.style.color = '#fff'; }
        if (btnC) { btnC.style.background = 'transparent'; btnC.style.color = '#94a3b8'; }
        if (camWrap) camWrap.style.display = 'none';
        if (dropZone) dropZone.style.display = 'flex';
        if (cameraViewWrap) cameraViewWrap.style.display = 'none';

        // Update selected file badge
        const fnSpan = document.getElementById('wbSelectedFileName');
        const fiWrap = document.getElementById('wbSelectedFileInfo');
        const fileName = file.name || 'pallet_image.jpg';
        const fileSizeKb = file.size ? (file.size / 1024).toFixed(1) : '0';
        if (fnSpan) fnSpan.textContent = `${fileName} (${fileSizeKb} KB)`;
        if (fiWrap) fiWrap.style.display = 'block';

        const capturedReqId = wbCountRequestId;
        const reader = new FileReader();
        reader.onload = function(e) {
            if (capturedReqId !== wbCountRequestId) return; // Discard if superseded
            const previewImg = document.getElementById('wbPreviewImg');
            const placeholder = document.getElementById('wbPlaceholder');
            if (previewImg) {
                // Graceful fallback if browser cannot render format natively (e.g. TIFF)
                previewImg.onerror = function() {
                    console.info('[Workbench] Browser cannot natively preview raw image format; server will process and provide visual verification.');
                    previewImg.style.display = 'none';
                    if (placeholder) {
                        placeholder.style.display = 'block';
                        const sub = document.getElementById('wbPlaceholderSubtitle');
                        if (sub) sub.textContent = `${fileName} loaded. High-precision server decoding in progress...`;
                    }
                };
                previewImg.onload = function() {
                    previewImg.style.display = 'block';
                    if (placeholder) placeholder.style.display = 'none';
                };
                previewImg.src = e.target.result;
            }
            // Sync into wbMultiViews as reference view
            if (!wbMultiViews || wbMultiViews.length === 0) {
                wbMultiViews = [{
                    id: 'view_ref',
                    label: 'front',
                    isRef: true,
                    file: file,
                    dataUrl: e.target.result,
                    regions: wbRegions || []
                }];
            } else {
                wbMultiViews[0].file = file;
                wbMultiViews[0].dataUrl = e.target.result;
            }
            if (typeof window.renderWorkbenchMultiViewStrip === 'function') {
                window.renderWorkbenchMultiViewStrip();
            }

            // Trigger automated counting execution immediately for the current file
            window.executeWorkbenchCount();
        };
        reader.readAsDataURL(file);
    };

    window.executeWorkbenchCount = async function() {
        const btn = document.getElementById('btnRunWorkbenchCount');
        const spinner = document.getElementById('wbProcessingStatus');

        if (btn) btn.disabled = true;
        if (spinner) spinner.style.display = 'block';

        // Purge stale detections and cached 3D geometry before starting a recount
        wbLatestResult = null;
        wbCurrentPieces = [];
        const prevOverlay = document.getElementById('wbBadgesOverlay');
        if (prevOverlay) prevOverlay.innerHTML = '';
        initWb3DPalletViewer(null);

        const thisRequestId = ++wbCountRequestId;

        try {
            const formData = new FormData();
            formData.append('source_type', wbSource);
            if (wbMode === 'bundles') {
                const matSelect = document.getElementById('wbBundleMaterialSelect');
                const matVal = matSelect ? matSelect.value : 'metal_bundles';
                formData.append('counting_mode', 'bundles');
                formData.append('material_type', matVal);
                if (wbRegions && wbRegions.length > 0) {
                    formData.append('regions', JSON.stringify(wbRegions));
                }
                if (matVal === 'glass_bundles') {
                    const lIn = document.getElementById('wbGlassLengthInput');
                    const wIn = document.getElementById('wbGlassWidthInput');
                    const tIn = document.getElementById('wbGlassThicknessInput');
                    const uSel = document.getElementById('wbGlassUnitSelect');
                    const pkgSel = document.getElementById('wbGlassPackagingSelect');
                    const ppbIn = document.getElementById('wbGlassSheetsPerBundleInput');
                    const pSel = document.getElementById('wbGlassProfileSelect');
                    const glassProf = {
                        length: parseFloat(lIn?.value || '2440'),
                        width: parseFloat(wIn?.value || '1830'),
                        thickness: parseFloat(tIn?.value || '6'),
                        unit: uSel?.value || 'mm',
                        packaging_type: pkgSel?.value || 'A_FRAME_STILLAGE',
                        pieces_per_bundle: ppbIn?.value ? parseInt(ppbIn.value, 10) : undefined,
                        id: pSel?.value || undefined
                    };
                    formData.append('glass_profile', JSON.stringify(glassProf));
                }
            } else {
                formData.append('counting_mode', 'pieces');
                formData.append('material_type', 'individual_pieces');
                if (wbRegions && wbRegions.length > 0) {
                    formData.append('regions', JSON.stringify(wbRegions));
                }
            }

            const camSelect = document.getElementById('wbCameraSelect') || document.getElementById('palletCameraSelect');
            const camId = camSelect ? camSelect.value : 'cam_inbound_01';
            formData.append('camera_id', camId);

            // Attach target SKU and manual Individuals-per-Bundle / UOM declaration
            const wbSkuId = document.getElementById('wbTargetSkuSelect')?.value || '';
            const wbUpb = Math.max(1, parseInt(document.getElementById('wbUnitsPerBundleInput')?.value || '1', 10));
            const wbUom = (document.getElementById('wbUomSelect')?.value || 'EA').toUpperCase();
            const wbBname = (document.getElementById('wbBundleNameInput')?.value || 'Bundle').trim() || 'Bundle';
            if (wbSkuId) formData.append('sku_id', wbSkuId);
            formData.append('units_per_bundle', String(wbUpb));
            formData.append('uom', wbUom);
            formData.append('bundle_name', wbBname);

            if (wbSource === 'upload') {
                let targetFile = wbSelectedFile;
                if (!targetFile) {
                    const fi = document.getElementById('wbFileInput');
                    if (fi && fi.files && fi.files[0]) {
                        targetFile = fi.files[0];
                        wbSelectedFile = targetFile;
                    }
                }

                // If wbSelectedFile is detached but preview image has an active data URL
                if (!targetFile) {
                    const previewImg = document.getElementById('wbPreviewImg');
                    if (previewImg && previewImg.src && previewImg.src.startsWith('data:image/')) {
                        try {
                            const byteString = atob(previewImg.src.split(',')[1]);
                            const mimeString = previewImg.src.split(',')[0].split(':')[1].split(';')[0];
                            const ab = new ArrayBuffer(byteString.length);
                            const ia = new Uint8Array(ab);
                            for (let i = 0; i < byteString.length; i++) {
                                ia[i] = byteString.charCodeAt(i);
                            }
                            targetFile = new Blob([ab], { type: mimeString });
                            wbSelectedFile = targetFile;
                        } catch (convErr) {
                            console.warn('[Workbench] Fallback Blob reconstruction from preview failed:', convErr);
                        }
                    }
                }

                if (targetFile) {
                    const filename = (targetFile && targetFile.name) ? targetFile.name : 'pallet_upload.jpg';
                    formData.append('image', targetFile, filename);
                    formData.append('angle1', targetFile, filename);

                    // Also attach image_data as fallback base64 payload if preview is available
                    const previewImg = document.getElementById('wbPreviewImg');
                    if (previewImg && previewImg.src && previewImg.src.startsWith('data:image/')) {
                        formData.append('image_data', previewImg.src);
                    }
                } else {
                    if (typeof showToast === 'function') {
                        showToast('No image file selected. Please click or drop a pallet photo to count.', 'warning');
                    } else {
                        alert('No image file selected. Please select an image file to count.');
                    }
                    if (btn) btn.disabled = false;
                    if (spinner) spinner.style.display = 'none';
                    return;
                }
            }

            let endpoint = wbMode === 'bundles' ? '/api/pallets/count-bundles' : '/api/pallets/count-pieces';

            // STAGE 5: If 2 or more views are staged, route to dedicated multi-view fusion endpoint
            if (wbMultiViews && wbMultiViews.length >= 2) {
                endpoint = '/api/pallets/count-multiview';
                wbMultiViews.forEach((v, vIdx) => {
                    if (v.file) {
                        formData.append(`view_image_${vIdx}`, v.file, v.file.name || `${v.label}.jpg`);
                    } else if (v.dataUrl) {
                        formData.append(`view_image_${vIdx}`, v.dataUrl);
                    }
                    formData.append(`view_label_${vIdx}`, v.label);
                    formData.append(`is_ref_${vIdx}`, String(v.isRef));
                    if (v.regions && v.regions.length > 0) {
                        formData.append(`regions_${vIdx}`, JSON.stringify(v.regions));
                    }
                });
            }
            const res = await fetch(endpoint, {
                method: 'POST',
                body: formData
            });

            // Discard stale response if a newer request or reset occurred
            if (thisRequestId !== wbCountRequestId) {
                console.log(`[Workbench] Discarded stale response for request #${thisRequestId}`);
                return;
            }

            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Vision counting failed');
            }

            // Check again after JSON decode
            if (thisRequestId !== wbCountRequestId) return;

            wbLatestResult = data;
            wbCurrentPieces = (data.pieces || []).map((p, idx) => ({ ...p, id: idx + 1 }));
            wbRawImageUrl = data.raw_image_url || data.annotated_image_url || '';

            // If client browser could not render format natively (e.g. TIFF), synchronize preview with server-decoded representation
            const previewImg = document.getElementById('wbPreviewImg');
            const placeholder = document.getElementById('wbPlaceholder');
            if (previewImg && wbRawImageUrl && previewImg.style.display === 'none') {
                previewImg.onerror = null;
                previewImg.src = wbRawImageUrl;
                previewImg.style.display = 'block';
                if (placeholder) placeholder.style.display = 'none';
            }

            renderWorkbenchResults(data);

            const qb = data.quantity_breakdown || {};
            const total = qb.total_units !== undefined ? qb.total_units : (data.total_pieces !== undefined ? data.total_pieces : (data.total_bundles || 0));
            if (typeof showToast === 'function') {
                if (total === 0) {
                    showToast(data.message || 'Analysis complete: No countable objects localized from visual evidence.', 'info');
                } else {
                    showToast(`Pallet analyzed: ${total} ${data.mode === 'BUNDLE_STACK' ? 'bundles' : 'pieces'} counted.`, 'success');
                }
            }

        } catch(err) {
            if (thisRequestId !== wbCountRequestId) return;
            console.error('[Workbench Count Error]:', err);
            if (typeof showToast === 'function') {
                showToast(`Counting Error: ${err.message}`, 'error');
            } else {
                alert(`Counting Error: ${err.message}`);
            }
        } finally {
            if (thisRequestId === wbCountRequestId) {
                if (btn) btn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }
        }
    };

    function renderWorkbenchResults(data) {
        // STAGE 5: Render Multi-View Cross-View Fusion Traceability if present
        const traceCard = document.getElementById('wbMultiViewTraceabilityCard');
        const switcherBar = document.getElementById('wbViewSwitcherBar');
        const switcherTabs = document.getElementById('wbViewSwitcherTabs');

        if (data.fusion_status) {
            if (traceCard) {
                traceCard.style.display = 'block';

                const statusBadge = document.getElementById('wbFusionStatusBadge');
                if (statusBadge) {
                    const st = String(data.fusion_status).toUpperCase();
                    statusBadge.textContent = st;
                    if (st === 'COMPLETE') {
                        statusBadge.style.background = 'rgba(16,185,129,0.15)';
                        statusBadge.style.color = '#34d399';
                        statusBadge.style.borderColor = 'rgba(16,185,129,0.3)';
                    } else if (st === 'PARTIAL') {
                        statusBadge.style.background = 'rgba(245,158,11,0.15)';
                        statusBadge.style.color = '#fbbf24';
                        statusBadge.style.borderColor = 'rgba(245,158,11,0.3)';
                    } else {
                        statusBadge.style.background = 'rgba(239,68,68,0.15)';
                        statusBadge.style.color = '#f87171';
                        statusBadge.style.borderColor = 'rgba(239,68,68,0.3)';
                    }
                }

                const dupsElem = document.getElementById('wbFusionDupsRemoved');
                if (dupsElem) {
                    dupsElem.textContent = `${data.duplicate_observations_removed || 0} Merged`;
                }

                const confElem = document.getElementById('wbFusionConfidenceVal');
                if (confElem) {
                    const score = data.heuristic_association_score !== undefined ? data.heuristic_association_score : (data.fusion_confidence || 0.95);
                    confElem.textContent = `${Math.round(score * 100)}%`;
                }

                // Stage 6: Honest Confidence Semantics
                const confNatureEl = document.getElementById('wbConfNatureVal');
                if (confNatureEl) confNatureEl.textContent = data.confidence_nature || 'HEURISTIC_ASSOCIATION_SCORE';

                const calibStatusEl = document.getElementById('wbCalibStatusVal');
                if (calibStatusEl) calibStatusEl.textContent = (data.calibration_status || 'UNCALIBRATED').replace('_', ' ');

                const detConfEl = document.getElementById('wbDetectorConfMeanVal');
                if (detConfEl) {
                    detConfEl.textContent = data.detector_confidence_mean ? `${Math.round(data.detector_confidence_mean * 100)}%` : 'N/A';
                }

                const conflictsEl = document.getElementById('wbConflictsCountVal');
                if (conflictsEl) conflictsEl.textContent = data.conflicting_observations_count || 0;

                const assocQualEl = document.getElementById('wbAssocQualityPill');
                if (assocQualEl) {
                    const q = (data.association_quality || 'HIGH').toUpperCase();
                    assocQualEl.textContent = `${q} QUALITY`;
                    if (q === 'HIGH') {
                        assocQualEl.style.background = 'rgba(16,185,129,0.15)';
                        assocQualEl.style.color = '#34d399';
                        assocQualEl.style.borderColor = 'rgba(16,185,129,0.3)';
                    } else if (q === 'MODERATE') {
                        assocQualEl.style.background = 'rgba(245,158,11,0.15)';
                        assocQualEl.style.color = '#fbbf24';
                        assocQualEl.style.borderColor = 'rgba(245,158,11,0.3)';
                    } else {
                        assocQualEl.style.background = 'rgba(239,68,68,0.15)';
                        assocQualEl.style.color = '#f87171';
                        assocQualEl.style.borderColor = 'rgba(239,68,68,0.3)';
                    }
                }

                const reviewBadge = document.getElementById('wbReviewStatusBadge');
                if (reviewBadge) {
                    const rSt = (data.review_status || 'AUTOMATED_PROPOSAL').toUpperCase();
                    reviewBadge.textContent = rSt.replace('_', ' ');
                    if (rSt === 'OPERATOR_REVIEWED') {
                        reviewBadge.style.background = 'rgba(16,185,129,0.15)';
                        reviewBadge.style.color = '#34d399';
                        reviewBadge.style.borderColor = 'rgba(16,185,129,0.3)';
                    } else {
                        reviewBadge.style.background = 'rgba(56,189,248,0.15)';
                        reviewBadge.style.color = '#38bdf8';
                        reviewBadge.style.borderColor = 'rgba(56,189,248,0.3)';
                    }
                }

                const geoLimitsEl = document.getElementById('wbGeoLimitsNote');
                if (geoLimitsEl && data.geometric_limitations) {
                    geoLimitsEl.textContent = data.geometric_limitations;
                }

                const pillsWrap = document.getElementById('wbFusionPerViewPills');
                if (pillsWrap && data.per_view_counts) {
                    pillsWrap.innerHTML = Object.entries(data.per_view_counts)
                        .map(([lbl, cnt]) => `<span style="background:#0f172a; border:1px solid #334155; padding:3px 8px; border-radius:4px; font-size:0.72rem; color:#38bdf8;"><b>${lbl.toUpperCase()}:</b> ${cnt}</span>`)
                        .join('');
                }

                const assocsWrap = document.getElementById('wbFusionAssocsList');
                if (assocsWrap && data.object_view_associations) {
                    assocsWrap.innerHTML = Object.entries(data.object_view_associations)
                        .slice(0, 15)
                        .map(([objId, vList]) => `<span style="background:rgba(2,132,199,0.15); border:1px solid rgba(2,132,199,0.3); padding:2px 6px; border-radius:4px; font-size:0.68rem; color:#f8fafc;">${objId} (${vList.join('+')})</span>`)
                        .join('') + (Object.keys(data.object_view_associations).length > 15 ? `<span style="font-size:0.68rem; color:#94a3b8; align-self:center;">+${Object.keys(data.object_view_associations).length - 15} more</span>` : '');
                }

                const warnElem = document.getElementById('wbFusionAmbiguityWarning');
                if (warnElem) {
                    warnElem.style.display = (data.fusion_status === 'ambiguous' || (data.uncertain_count && data.uncertain_count > 0)) ? 'block' : 'none';
                }

                // Render Stage 6 Operator Review Drawer Items
                window.currentMultiViewSession = data;
                renderOperatorReviewDrawer(data);
            }

            // Populate View Switcher Tabs
            if (switcherBar && switcherTabs && data.annotated_views) {
                switcherBar.style.display = 'flex';
                switcherTabs.innerHTML = '';

                // 1. Unified Audit Board Tab
                const boardTab = document.createElement('button');
                boardTab.type = 'button';
                boardTab.style.cssText = 'background:#0284c7; color:#fff; border:none; border-radius:4px; padding:3px 8px; font-size:0.7rem; font-weight:700; cursor:pointer; white-space:nowrap;';
                boardTab.textContent = '★ Fused Audit Board';
                boardTab.onclick = function() {
                    Array.from(switcherTabs.children).forEach(t => t.style.background = '#1e293b');
                    boardTab.style.background = '#0284c7';
                    const resImg = document.getElementById('wbResultImg');
                    if (resImg) resImg.src = data.annotated_image_url || data.audit_image_url;
                };
                switcherTabs.appendChild(boardTab);

                // 2. Individual View Tabs
                Object.entries(data.annotated_views).forEach(([vLabel, vUrl]) => {
                    if (!vUrl) return;
                    const vTab = document.createElement('button');
                    vTab.type = 'button';
                    vTab.style.cssText = 'background:#1e293b; color:#cbd5e1; border:1px solid #334155; border-radius:4px; padding:3px 8px; font-size:0.7rem; font-weight:600; cursor:pointer; white-space:nowrap;';
                    vTab.textContent = `View: ${vLabel.toUpperCase()}`;
                    vTab.onclick = function() {
                        Array.from(switcherTabs.children).forEach(t => t.style.background = '#1e293b');
                        vTab.style.background = '#0284c7';
                        const resImg = document.getElementById('wbResultImg');
                        if (resImg) resImg.src = vUrl;
                    };
                    switcherTabs.appendChild(vTab);
                });
            }
        } else {
            if (traceCard) traceCard.style.display = 'none';
            if (switcherBar) switcherBar.style.display = 'none';
        }

        const stageCard = document.getElementById('wbInteractiveStageCard');
        if (stageCard) {
            stageCard.style.display = 'block';
            setTimeout(() => {
                stageCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 100);
        }

        const qb = data.quantity_breakdown || {};
        const total = qb.total_units !== undefined ? qb.total_units : (data.total_pieces !== undefined ? data.total_pieces : (data.total_bundles || 0));
        const visible = qb.directly_detected_count !== undefined ? qb.directly_detected_count : (qb.visible_count !== undefined ? qb.visible_count : (data.visible_pieces !== undefined ? data.visible_pieces : (qb.visible_bundles !== undefined ? qb.visible_bundles : total)));
        const inferred = qb.inferred_count !== undefined ? qb.inferred_count : (data.hidden_count || 0);
        const autoGeom = qb.automated_geometry || data.automated_geometry || {};

        // Update Proposed Count badge & Recognized SKU + Practical UOM Banner
        const recSku = data.recognized_sku || {};
        const hasExplicitSelect = Boolean(document.getElementById('wbTargetSkuSelect')?.value);
        const upbInputEl = document.getElementById('wbUnitsPerBundleInput');
        const uomSelectEl = document.getElementById('wbUomSelect');
        const bnameInputEl = document.getElementById('wbBundleNameInput');

        if (!hasExplicitSelect && recSku.sku_id) {
            // Sync recognized SKU's declared bundle multiplier if user left input at default 1
            if (upbInputEl && parseInt(upbInputEl.value || '1', 10) === 1 && recSku.units_per_bundle > 1) {
                upbInputEl.value = recSku.units_per_bundle;
            }
            if (uomSelectEl && recSku.uom) {
                const rUom = String(recSku.uom).toUpperCase();
                if (!Array.from(uomSelectEl.options).some(o => o.value === rUom)) {
                    const opt = document.createElement('option');
                    opt.value = rUom;
                    opt.textContent = rUom;
                    uomSelectEl.appendChild(opt);
                }
                uomSelectEl.value = rUom;
            }
            if (bnameInputEl && recSku.bundle_name) {
                bnameInputEl.value = recSku.bundle_name;
            }
        }

        const activeUpb = Math.max(1, parseInt(upbInputEl?.value || data.units_per_bundle || recSku.units_per_bundle || '1', 10));
        const activeUom = (uomSelectEl?.value || data.uom || recSku.uom || 'EA').toUpperCase();
        const activeBname = (bnameInputEl?.value || data.bundle_name || recSku.bundle_name || 'Bundle').trim() || 'Bundle';
        const realizedTotal = total * activeUpb;

        const recTextEl = document.getElementById('wbRecognizedSkuText');
        if (recTextEl && (recSku.sku_id || data.sku_id)) {
            const sid = recSku.sku_id || data.sku_id;
            const sname = recSku.name || data.sku_name || sid;
            const scat = recSku.category || data.sku_category || 'General';
            const confPct = Math.round((recSku.confidence || 0.98) * 100);
            const recMethod = recSku.recognition_method || '';
            const mismatchWarn = recSku.mismatch_warning || data.mismatch_warning;
            let matchTag = `<span style="color:#a7f3d0; font-size:0.74rem;">[${scat} &bull; ${confPct}% Precision Match]</span>`;
            if (mismatchWarn) {
                matchTag = `<span style="color:#ef4444; font-size:0.75rem; font-weight:600;"><i class="fas fa-exclamation-triangle"></i> [Warning: ${mismatchWarn}]</span>`;
                // Reset mismatched SKU selection in dropdown so subsequent counts don't re-lock onto wrong material
                const wbSkuSel = document.getElementById('wbTargetSkuSelect');
                if (wbSkuSel && wbSkuSel.value && wbSkuSel.value !== sid) {
                    wbSkuSel.value = '';
                }
            } else if (recMethod === 'MATERIAL_FAMILY_INFERRED') {
                matchTag = `<span style="color:#f59e0b; font-size:0.74rem;">[Material Inferred &bull; Catalog SKU Not Mapped]</span>`;
            }
            recTextEl.innerHTML = `Recognized Product: <b style="color:#38bdf8; font-family:monospace;">${sid}</b> &mdash; <span style="color:#fff;">${sname}</span> ${matchTag}`;
        }
        const pillEl = document.getElementById('wbRealizedUnitsPill');
        if (pillEl) {
            pillEl.innerHTML = `${total} ${activeBname}${total === 1 ? '' : 's'} &times; ${activeUpb} ${activeUom} = <span style="color:#fff; text-decoration:underline;">${realizedTotal} ${activeUom}</span>`;
        }

        const totalBadge = document.getElementById('wbTotalBadge');
        if (totalBadge) {
            if (data.mode === 'METAL_BUNDLES' || data.counting_strategy === 'DEDICATED_METAL_BUNDLE_COUNTING') {
                const bCount = data.physical_bundles_count !== undefined ? data.physical_bundles_count : total;
                totalBadge.textContent = activeUpb > 1
                    ? `${bCount} METAL BUNDLE${bCount === 1 ? '' : 'S'} (${realizedTotal} ${activeUom})`
                    : `${bCount} METAL BUNDLE${bCount === 1 ? '' : 'S'}`;
            } else if (data.mode === 'GLASS_BUNDLES' || data.counting_strategy === 'MEASUREMENT_AWARE_GLASS_BUNDLE_COUNTING') {
                const bCount = data.physical_bundles_count !== undefined ? data.physical_bundles_count : total;
                const prof = data.glass_profile || {};
                const dimStr = prof.length && prof.width ? ` [${prof.length}×${prof.width} ${prof.unit || 'mm'}]` : '';
                totalBadge.textContent = activeUpb > 1
                    ? `${bCount} GLASS BUNDLE${bCount === 1 ? '' : 'S'}${dimStr} (${realizedTotal} ${activeUom})`
                    : `${bCount} GLASS BUNDLE${bCount === 1 ? '' : 'S'}${dimStr}`;
            } else if (wbMode === 'bundles' || data.mode === 'BUNDLE_STACK') {
                totalBadge.textContent = activeUpb > 1
                    ? `${total} ${activeBname.toUpperCase()}S (${realizedTotal} ${activeUom})`
                    : `${total} ${activeBname.toUpperCase()}S`;
            } else {
                totalBadge.textContent = activeUpb > 1
                    ? `${total} ${activeBname.toUpperCase()}S (${realizedTotal} ${activeUom})`
                    : `${realizedTotal} ${activeUom}`;
            }
        }

        // Update Inferred Geometry Formula (Read-Only)
        const formulaElem = document.getElementById('wbAutoGeometryFormula');
        const methodBadge = document.getElementById('wbCountingMethodBadge');
        if (methodBadge) {
            methodBadge.textContent = qb.counting_method || data.method || 'DIRECT_INSTANCE_LOCALIZATION';
        }
        if (formulaElem) {
            if (total === 0) {
                formulaElem.textContent = data.confidence_note || data.message || '0 Countable Units Localized (Insufficient Visual Evidence)';
                formulaElem.style.color = '#f59e0b';
            } else if (qb.formula) {
                formulaElem.textContent = qb.formula;
                formulaElem.style.color = '#10b981';
            } else if ((autoGeom.stack_detected || autoGeom.is_regular_matrix) && autoGeom.layers && autoGeom.columns) {
                const confText = qb.is_estimate ? 'Estimated Stack' : 'Direct Instance Localization';
                const depthStr = autoGeom.is_depth_unknown ? 'Unknown Interior Depth' : `${autoGeom.rows || autoGeom.depth || 1} Depth`;
                formulaElem.textContent = `${visible} Directly Localized (${autoGeom.layers} Layers × ${autoGeom.columns} Cols • ${depthStr} • ${confText})`;
                formulaElem.style.color = '#10b981';
            } else if (data.mode === 'BUNDLE_STACK') {
                formulaElem.textContent = `${total} Bundles Directly Localized (${data.stacks?.length || 1} Stack Groups)`;
                formulaElem.style.color = '#38bdf8';
            } else {
                formulaElem.textContent = `${visible} Physical Instances Directly Localized`;
                formulaElem.style.color = '#38bdf8';
            }
        }

        // Update 4-Stat breakdown (including dynamic Tare Packaging readout)
        const statVis = document.getElementById('wbStatVisible');
        const statInf = document.getElementById('wbStatInferred');
        const statForm = document.getElementById('wbStatFormula');
        const statTare = document.getElementById('wbStatTare');
        if (statVis) statVis.textContent = visible;
        if (statInf) statInf.textContent = inferred;
        if (statForm) {
            statForm.textContent = qb.formula || data.grid_formula || `${visible} Visible Units`;
            statForm.title = statForm.textContent;
        }
        if (statTare) {
            const palletBaseCount = qb.tare_packaging?.pallet_base_count !== undefined
                ? qb.tare_packaging.pallet_base_count
                : (data.tare_pallet_base_detected ? 1 : 0);
            statTare.textContent = palletBaseCount > 0 ? `${palletBaseCount} Pallet Base (Excluded)` : '0 Pallet Base Detected';
        }

        // Status badge: clear indication of Direct Instance Detection vs Estimated vs Insufficient
        const statusBadge = document.getElementById('wbVerificationStatusBadge');
        if (statusBadge && (data.mode === 'METAL_BUNDLES' || data.counting_strategy === 'DEDICATED_METAL_BUNDLE_COUNTING')) {
            const hasUncertain = Boolean(data.uncertain_count && data.uncertain_count > 0);
            statusBadge.textContent = hasUncertain ? 'DIRECT METAL BUNDLES (With Uncertainty)' : 'DIRECT METAL BUNDLES (Confirmed)';
            statusBadge.style.color = hasUncertain ? '#f59e0b' : '#10b981';
            statusBadge.style.borderColor = hasUncertain ? 'rgba(245,158,11,0.3)' : 'rgba(16,185,129,0.3)';
            statusBadge.style.background = hasUncertain ? 'rgba(245,158,11,0.15)' : 'rgba(16,185,129,0.15)';
        } else if (statusBadge && (data.mode === 'GLASS_BUNDLES' || data.counting_strategy === 'MEASUREMENT_AWARE_GLASS_BUNDLE_COUNTING')) {
            const hasUncertain = Boolean(data.uncertain_count && data.uncertain_count > 0);
            statusBadge.textContent = hasUncertain ? 'GLASS BUNDLES (With Uncertainty)' : 'MEASUREMENT-AWARE GLASS (Confirmed)';
            statusBadge.style.color = hasUncertain ? '#f59e0b' : '#06b6d4';
            statusBadge.style.borderColor = hasUncertain ? 'rgba(245,158,11,0.3)' : 'rgba(6,182,212,0.3)';
            statusBadge.style.background = hasUncertain ? 'rgba(245,158,11,0.15)' : 'rgba(6,182,212,0.15)';
        } else 
        if (statusBadge) {
            let stText = 'DIRECT INSTANCE DETECTION';
            let stColor = '#10b981';
            let stBorder = 'rgba(16,185,129,0.3)';
            let stBg = 'rgba(16,185,129,0.15)';

            if (total === 0 || qb.verification_status === 'INSUFFICIENT_VISUAL_EVIDENCE') {
                stText = 'INSUFFICIENT VISUAL EVIDENCE';
                stColor = '#f59e0b';
                stBorder = 'rgba(245,158,11,0.3)';
                stBg = 'rgba(245,158,11,0.15)';
            } else if (qb.verification_status === 'DIRECT_VISUAL_DETECTION (Total Unknown)' || autoGeom.is_depth_unknown) {
                stText = 'DIRECT VISUAL (Interior Depth Unknown)';
                stColor = '#10b981';
                stBorder = 'rgba(16,185,129,0.3)';
                stBg = 'rgba(16,185,129,0.15)';
            } else if (qb.verification_status === 'DIRECT_VISUAL_DETECTION' || qb.verification_status === 'DIRECT_VISUAL' || qb.verification_status === 'AUTOMATED_DETECTION' || (inferred === 0 && !qb.is_estimate)) {
                stText = 'DIRECT VISUAL (Confirmed)';
                stColor = '#10b981';
                stBorder = 'rgba(16,185,129,0.3)';
                stBg = 'rgba(16,185,129,0.15)';
            } else if (qb.verification_status === 'ESTIMATED_STACK' || qb.is_estimate) {
                stText = qb.counting_strategy === 'STRUCTURED_PALLET_RECONSTRUCTION'
                    ? 'PROPOSED (Structured 3D Stack)'
                    : 'PROPOSED (Estimated Stack)';
                stColor = '#f59e0b';
                stBorder = 'rgba(245,158,11,0.3)';
                stBg = 'rgba(245,158,11,0.15)';
            } else if (qb.verification_status === 'UNCERTAIN') {
                stText = 'UNCERTAIN (Verify Stack)';
                stColor = '#ef4444';
                stBorder = 'rgba(239,68,68,0.3)';
                stBg = 'rgba(239,68,68,0.15)';
            }
            statusBadge.textContent = stText;
            statusBadge.style.color = stColor;
            statusBadge.style.borderColor = stBorder;
            statusBadge.style.background = stBg;
        }

        // Result image
        const img = document.getElementById('wbResultImg');
        if (img && data.annotated_image_url) {
            img.src = `${data.annotated_image_url}?t=${Date.now()}`;
            img.onload = () => {
                renderWbBadgesOverlay();
            };
        }

        // Update 4-stat labels for pieces mode or dedicated metal bundles
        const isMetalBundle = (data.mode === 'METAL_BUNDLES' || data.counting_strategy === 'DEDICATED_METAL_BUNDLE_COUNTING');
        const isGlassBundle = (data.mode === 'GLASS_BUNDLES' || data.counting_strategy === 'MEASUREMENT_AWARE_GLASS_BUNDLE_COUNTING');
        const isPiecesMode = !isMetalBundle && !isGlassBundle && (data.mode === 'INDIVIDUAL_PIECES' || data.counting_mode === 'individual_pieces' || wbMode === 'pieces');
        const lblStatVis = document.getElementById('wbLabelStatVisible');
        const lblStatInf = document.getElementById('wbLabelStatInferred');
        if (lblStatVis) {
            lblStatVis.textContent = isMetalBundle ? 'Confirmed Bundles:' : (isGlassBundle ? 'Confirmed Glass Bundles:' : (isPiecesMode ? 'Confirmed Pieces:' : 'Visible Detected:'));
        }
        if (lblStatInf) {
            lblStatInf.textContent = (isMetalBundle || isGlassBundle) ? 'Uncertain Bundles:' : ((isPiecesMode && data.regions && data.regions.length > 0)
                ? 'Excluded / Review:'
                : 'Inferred (Hidden):');
        }
        if (statInf && (isMetalBundle || isGlassBundle)) {
            statInf.textContent = data.uncertain_count || 0;
            statInf.title = `${data.uncertain_count || 0} Uncertain bundle candidates`;
        }
        if (statVis && (isMetalBundle || isGlassBundle)) {
            statVis.textContent = data.confirmed_count !== undefined ? data.confirmed_count : (data.physical_bundles_count || total);
        }
        if (statInf && isPiecesMode && data.regions && data.regions.length > 0) {
            statInf.textContent = `${data.excluded_count || 0} Exc / ${data.uncertain_count || 0} Review`;
            statInf.title = `Excluded: ${data.excluded_count || 0} | Boundary Review: ${data.uncertain_count || 0}`;
        }

        renderWorkbenchRegionsOverlay();

        // Cluster pills
        renderWbClusterPills(data.clusters);

        // 3D Digital Twin: render localized physical objects accurately
        if (data.matrix_3d && data.matrix_3d.boxes && data.matrix_3d.boxes.length > 0) {
            setTimeout(() => {
                initWb3DPalletViewer(data.matrix_3d);
            }, 80);
        } else {
            initWb3DPalletViewer(null);
        }
    }

    function renderWbClusterPills(clusters) {
        const pills = document.getElementById('wbClustersPills');
        if (!pills) return;
        if (clusters && clusters.length > 0) {
            pills.innerHTML = clusters.map(cl => {
                return `
                    <div style="background:rgba(255,255,255,0.06); border:1px solid ${cl.color_hex || '#0284c7'}; border-radius:6px; padding:4px 10px; display:inline-flex; align-items:center; gap:6px; font-size:0.75rem;">
                        <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${cl.color_hex || '#0284c7'};"></span>
                        <span style="color:#f1f5f9; font-weight:600;">${cl.name}:</span>
                        <b style="color:#fff; font-family:'JetBrains Mono',monospace;">${cl.count}</b>
                    </div>
                `;
            }).join('');
        } else {
            pills.innerHTML = '';
        }
    }

    function renderWbBadgesOverlay() {
        const overlay = document.getElementById('wbBadgesOverlay');
        const imgElem = document.getElementById('wbResultImg');
        if (!overlay || !imgElem) return;

        overlay.innerHTML = '';
        const imgW = imgElem.naturalWidth || imgElem.clientWidth || 1;
        const imgH = imgElem.naturalHeight || imgElem.clientHeight || 1;

        // Do NOT render a duplicate set of visible numbered DOM markers over backend-rendered markers.
        // Instead, render transparent interactive hit-zones over each accepted detection (revealing a delete
        // highlight on hover), and only render visible badges for un-rendered manual pins prior to re-render.
        wbCurrentPieces.forEach((p, idx) => {
            const seqId = idx + 1;
            p.id = seqId;

            const leftPct = (p.x / imgW) * 100;
            const topPct = (p.y / imgH) * 100;
            const isUnrenderedPin = Boolean(p.is_unrendered_pin);

            const badge = document.createElement('div');
            badge.className = 'interactive-piece-badge';
            badge.style.cssText = `
                position: absolute;
                left: ${leftPct}%;
                top: ${topPct}%;
                transform: translate(-50%, -50%);
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background: ${isUnrenderedPin ? (p.color_hex || '#10b981') : 'transparent'};
                border: ${isUnrenderedPin ? '2px solid #ffffff' : '2px solid transparent'};
                color: ${isUnrenderedPin ? '#ffffff' : 'transparent'};
                font-size: 10px;
                font-weight: 800;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                pointer-events: auto;
                box-shadow: ${isUnrenderedPin ? '0 2px 6px rgba(0,0,0,0.5)' : 'none'};
                user-select: none;
                transition: transform 0.15s, background 0.15s, border-color 0.15s, color 0.15s;
            `;
            const confPct = p.confidence ? ` • ${Math.round(p.confidence * 100)}% conf` : '';
            badge.title = `Object #${seqId} (${p.cluster || 'Detected Object'}${confPct})\nClick to Delete`;
            badge.textContent = isUnrenderedPin ? seqId : '×';

            badge.onmouseenter = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1.25)';
                badge.style.background = 'rgba(239, 68, 68, 0.9)';
                badge.style.borderColor = '#ffffff';
                badge.style.color = '#ffffff';
                badge.textContent = '×';
            };
            badge.onmouseleave = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1)';
                badge.style.background = isUnrenderedPin ? (p.color_hex || '#10b981') : 'transparent';
                badge.style.borderColor = isUnrenderedPin ? '#ffffff' : 'transparent';
                badge.style.color = isUnrenderedPin ? '#ffffff' : 'transparent';
                badge.textContent = isUnrenderedPin ? seqId : '×';
            };
            badge.onclick = (e) => {
                e.stopPropagation();
                window.removeWorkbenchBadge(idx);
            };

            overlay.appendChild(badge);
        });
    }

    window.handleWorkbenchCanvasClick = function(event) {
        if (wbCurrentTool !== 'none') return;
        const imgElem = document.getElementById('wbResultImg');
        if (!imgElem) return;

        const rect = imgElem.getBoundingClientRect();
        const clickX = event.clientX - rect.left;
        const clickY = event.clientY - rect.top;

        const imgW = imgElem.naturalWidth || imgElem.clientWidth || 1;
        const imgH = imgElem.naturalHeight || imgElem.clientHeight || 1;

        const naturalX = Math.round((clickX / rect.width) * imgW);
        const naturalY = Math.round((clickY / rect.height) * imgH);

        // Check if click is near an existing detection first
        const hitRadiusNat = Math.max(14, Math.round((18 / Math.max(rect.width, 1)) * imgW));
        const hitIdx = wbCurrentPieces.findIndex(p => Math.hypot((p.x || 0) - naturalX, (p.y || 0) - naturalY) <= hitRadiusNat);
        if (hitIdx !== -1) {
            window.removeWorkbenchBadge(hitIdx);
            return;
        }

        const newId = wbCurrentPieces.length + 1;
        wbCurrentPieces.push({
            id: newId,
            index: newId,
            detection_id: `op_pin_${newId}`,
            x: naturalX,
            y: naturalY,
            centroid: [naturalX, naturalY],
            norm_x: Number((naturalX / imgW).toFixed(4)),
            norm_y: Number((naturalY / imgH).toFixed(4)),
            norm_w: 0.08,
            norm_h: 0.08,
            confidence: 1.0,
            detection_status: 'OPERATOR_ADDED',
            uncertainty_indicators: [],
            cluster: 'Operator Added',
            color_hex: '#10b981',
            is_unrendered_pin: true
        });

        updateLocalWorkbenchState();
        renderWbBadgesOverlay();
        window.recertifyWorkbenchMarkers(true);
    };

    window.removeWorkbenchBadge = function(index) {
        if (index >= 0 && index < wbCurrentPieces.length) {
            wbCurrentPieces.splice(index, 1);
            wbCurrentPieces.forEach((p, i) => {
                p.id = i + 1;
                p.index = i + 1;
            });
            updateLocalWorkbenchState();
            renderWbBadgesOverlay();
            window.recertifyWorkbenchMarkers(true);
        }
    };

    function updateLocalWorkbenchState() {
        const visible = wbCurrentPieces.length;
        const qb = wbLatestResult?.quantity_breakdown || {};
        const inferred = qb.inferred_count !== undefined ? qb.inferred_count : (wbLatestResult?.hidden_count || 0);
        const total = visible + inferred;

        const statVis = document.getElementById('wbStatVisible');
        const statInf = document.getElementById('wbStatInferred');
        const statForm = document.getElementById('wbStatFormula');
        const totalBadge = document.getElementById('wbTotalBadge');
        const statusBadge = document.getElementById('wbVerificationStatusBadge');

        if (statVis) statVis.textContent = visible;
        if (statInf) statInf.textContent = inferred;
        if (statForm) {
            statForm.textContent = `${visible} Visible + ${inferred} Inferred = ${total} Total`;
            statForm.title = statForm.textContent;
        }
        if (totalBadge) totalBadge.textContent = `${total} ${wbMode === 'bundles' ? 'BUNDLES' : 'PIECES'}`;
        if (statusBadge) {
            statusBadge.textContent = 'DIRECT VISUAL (Operator Verified)';
            statusBadge.style.color = '#38bdf8';
            statusBadge.style.borderColor = 'rgba(56,189,248,0.3)';
            statusBadge.style.background = 'rgba(56,189,248,0.15)';
        }
    }

    window.recertifyWorkbenchMarkers = async function(silent = false) {
        if (!wbRawImageUrl) {
            if (!silent) alert('No image loaded to re-render.');
            return;
        }

        try {
            const res = await fetch('/api/pallets/re-render-pieces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    raw_image_url: wbRawImageUrl,
                    pieces: wbCurrentPieces,
                    matrix_dimensions: null,
                    counting_mode: wbMode === 'bundles' ? 'bundles' : 'pieces',
                    regions: (wbMode !== 'bundles' && wbRegions.length > 0) ? wbRegions : null
                })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                wbLatestResult = data;
                wbCurrentPieces = (data.pieces || []).map((p, idx) => ({ ...p, id: idx + 1, is_unrendered_pin: false }));
                renderWorkbenchResults(data);
                if (!silent && typeof showToast === 'function') {
                    showToast(`Re-rendered: ${data.total_pieces} pieces verified.`, 'success');
                }
            } else if (!silent) {
                alert(`Re-render error: ${data.error || 'Failed to re-render'}`);
            }
        } catch(e) {
            console.error('Re-render error:', e);
            if (!silent) alert(`Error: ${e.message}`);
        }
    };

    function initWb3DPalletViewer(matrixData) {
        const container = document.getElementById('wbThreeJsContainer');
        if (!container) return;

        const loading = document.getElementById('wbThreeJsLoading');
        const placeholder = document.getElementById('wbThreeJsPlaceholder');
        const depthBanner = document.getElementById('wbThreeJsDepthBanner');
        if (loading) loading.style.display = 'none';

        // If no 3D stack boxes exist, display the clean 2D planar status
        if (!matrixData || !matrixData.boxes || matrixData.boxes.length === 0) {
            if (depthBanner) depthBanner.style.display = 'none';
            if (placeholder) {
                placeholder.style.display = 'block';
                placeholder.innerHTML = `
                    <i class="fas fa-layer-group" style="font-size:1.8rem; margin-bottom:6px; opacity:0.5; color:#38bdf8; display:block;"></i>
                    <div style="font-weight:700; color:#cbd5e1; font-size:0.78rem;">Direct Visual Count Active (2D Surface)</div>
                    <div style="font-size:0.7rem; color:#64748b; margin-top:2px;">3D Digital Twin renders localized physical objects when detected.</div>
                `;
            }
            const existingCanvas = container.querySelector('canvas');
            if (existingCanvas) existingCanvas.remove();
            return;
        }

        if (placeholder) placeholder.style.display = 'none';

        if (depthBanner) {
            if (matrixData.is_depth_unknown) {
                depthBanner.style.display = 'block';
                depthBanner.style.color = '#f59e0b';
                const visCount = matrixData.visible_count !== undefined ? matrixData.visible_count : matrixData.boxes.length;
                depthBanner.textContent = `Single-View Localization: ${visCount} Directly Detected • Interior Depth Unknown (0 Fabricated)`;
            } else if (matrixData.reconstruction_mode === 'STRUCTURED_PALLET_RECONSTRUCTION') {
                depthBanner.style.display = 'block';
                depthBanner.style.color = '#38bdf8';
                const rVal = matrixData.rows || matrixData.depth || 1;
                const cVal = matrixData.columns || 1;
                const lVal = matrixData.layers || 1;
                const totVal = matrixData.total_3d_capacity || matrixData.boxes.length;
                const visVal = matrixData.visible_count || 0;
                const hidVal = matrixData.hidden_count || 0;
                const shVal = matrixData.shared_corner_count || lVal;
                depthBanner.textContent = `Structured 3D Stack: ${rVal}R × ${cVal}C × ${lVal}L = ${totVal} Units (${visVal} Direct + ${hidVal} Core • ${shVal} Shared Corner)`;
            } else {
                depthBanner.style.display = 'none';
            }
        }

        if (typeof THREE === 'undefined') {
            console.warn('[3D Viewer] Three.js not loaded');
            if (placeholder) {
                placeholder.style.display = 'block';
                placeholder.textContent = 'Three.js library is loading...';
            }
            return;
        }

        // Clean up previous canvas
        const existingCanvas = container.querySelector('canvas');
        if (existingCanvas) existingCanvas.remove();

        wbThreeBoxMeshes = [];
        wbIsExploded = false;
        wbIsXRay = false;

        const w = container.clientWidth || 360;
        const h = container.clientHeight || 250;

        wbThreeScene = new THREE.Scene();
        wbThreeScene.background = new THREE.Color(0x020617);

        wbThreeCamera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
        wbThreeCamera.position.set(5.5, 4.8, 6.5);

        wbThreeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        wbThreeRenderer.setSize(w, h);
        wbThreeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        wbThreeRenderer.shadowMap.enabled = true;
        container.insertBefore(wbThreeRenderer.domElement, container.firstChild);

        const cols = Math.max(1, matrixData.columns || 1);
        const rows = Math.max(1, matrixData.rows || matrixData.depth || 1);
        const layers = Math.max(1, matrixData.layers || 1);
        const hasPallet = matrixData.has_pallet === true;
        const isStructuredGrid = (
            matrixData.reconstruction_mode === 'OPERATOR_CONFIRMED' ||
            matrixData.reconstruction_mode === 'STRUCTURED_PALLET_RECONSTRUCTION'
        );

        const spanW = Math.max(2.6, Math.min(6.4, cols * 0.92));
        const spanD = Math.max(1.8, Math.min(5.6, rows * 0.92));
        const palletH = hasPallet ? 0.16 : 0.0;

        const ControlsClass = THREE.OrbitControls || window.OrbitControls;
        if (typeof ControlsClass !== 'undefined') {
            wbThreeControls = new ControlsClass(wbThreeCamera, wbThreeRenderer.domElement);
            wbThreeControls.enableDamping = true;
            wbThreeControls.dampingFactor = 0.08;
            wbThreeControls.maxPolarAngle = Math.PI / 2 - 0.02;
            const targetY = isStructuredGrid ? (layers * 0.72 / 2) + palletH : (layers * 0.65 / 2) + palletH;
            wbThreeControls.target.set(0, targetY, 0);
            wbThreeControls.update();
        }

        const ambLight = new THREE.AmbientLight(0xffffff, 0.85);
        wbThreeScene.add(ambLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
        dirLight.position.set(8, 14, 10);
        wbThreeScene.add(dirLight);

        const rimLight = new THREE.DirectionalLight(0x38bdf8, 0.40);
        rimLight.position.set(-7, 6, -7);
        wbThreeScene.add(rimLight);

        const gridHelper = new THREE.GridHelper(14, 14, 0x1e293b, 0x0f172a);
        wbThreeScene.add(gridHelper);

        // Render wooden pallet base with top deck slats and bottom stringer runners if tare pallet was detected
        if (hasPallet) {
            const palletW = isStructuredGrid ? (cols * 0.90 + 0.36) : (spanW + 0.4);
            const palletD = isStructuredGrid ? Math.max(rows * 0.90 + 0.36, 1.5) : (Math.max(spanD, 1.6) + 0.4);
            const woodMat = new THREE.MeshStandardMaterial({ color: 0x8a5d3b, roughness: 0.85, metalness: 0.05 });
            const slatCount = Math.max(5, cols * 2 + 1);
            const slatW = (palletW / slatCount) * 0.74;
            for (let i = 0; i < slatCount; i++) {
                const slatGeo = new THREE.BoxGeometry(slatW, 0.04, palletD);
                const slat = new THREE.Mesh(slatGeo, woodMat);
                const xPos = -palletW / 2 + (i + 0.5) * (palletW / slatCount);
                slat.position.set(xPos, palletH - 0.02, 0);
                wbThreeScene.add(slat);
            }
            for (let s = -1; s <= 1; s++) {
                const runnerGeo = new THREE.BoxGeometry(0.12, palletH - 0.04, palletD);
                const runner = new THREE.Mesh(runnerGeo, woodMat);
                runner.position.set(s * (palletW * 0.42), (palletH - 0.04) / 2, 0);
                wbThreeScene.add(runner);
            }
        }

        // Precompute cumulative layer heights for irregular 3D stacks so boxes rest solidly on lower layers
        const layerMaxH = {};
        (matrixData.boxes || []).forEach(b => {
            const lyr = b.layer || 0;
            const bh = isStructuredGrid ? 0.66 : Math.max(0.48, Math.min(1.35, (b.rel_h_ratio || 1.0) * 0.70));
            if (!layerMaxH[lyr] || bh > layerMaxH[lyr]) layerMaxH[lyr] = bh;
        });
        const layerBaseY = {};
        let cumY = palletH;
        for (let lyr = 0; lyr < layers + 2; lyr++) {
            layerBaseY[lyr] = cumY;
            cumY += (layerMaxH[lyr] || 0.66) + 0.02;
        }

        (matrixData.boxes || []).forEach(b => {
            let boxW = 0.84;
            let boxH = 0.66;
            let boxD = 0.84;
            let posX, posY, posZ;

            if (isStructuredGrid) {
                posX = (b.col - (cols - 1) / 2) * 0.90;
                posY = (b.layer || 0) * 0.70 + (boxH / 2) + palletH;
                posZ = (b.depth - (rows - 1) / 2) * 0.90;
            } else {
                boxW = Math.max(0.68, Math.min(2.20, (b.rel_w_ratio || 1.0) * 1.15));
                boxH = Math.max(0.48, Math.min(1.35, (b.rel_h_ratio || 1.0) * 0.70));
                boxD = Math.max(0.76, Math.min(1.55, boxW * 0.88));
                const lyr = b.layer || 0;
                posX = (cols === 1 && b.rel_x_offset !== undefined)
                    ? (b.rel_x_offset * 1.25)
                    : (((b.norm_x !== undefined ? b.norm_x : 0.5) - 0.5) * spanW);
                posY = (layerBaseY[lyr] !== undefined ? layerBaseY[lyr] : palletH) + (boxH / 2);
                posZ = rows > 1 ? ((b.depth || 0) - (rows - 1) / 2) * 0.88 : 0.0;
            }

            const itemGeo = new THREE.BoxGeometry(boxW, boxH, boxD);
            const itemEdgesGeo = new THREE.EdgesGeometry(itemGeo);

            let mat, edgeMat;
            if (b.is_hidden) {
                mat = new THREE.MeshPhysicalMaterial({
                    color: 0x0284c7,
                    roughness: 0.15,
                    transmission: 0.78,
                    opacity: 0.36,
                    transparent: true,
                    depthWrite: false
                });
                edgeMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.85 });
            } else if (b.is_glass || matrixData.is_glass) {
                mat = new THREE.MeshPhysicalMaterial({
                    color: 0x06b6d4,
                    roughness: 0.12,
                    transmission: 0.82,
                    opacity: 0.58,
                    transparent: true,
                    depthWrite: false,
                    metalness: 0.08
                });
                edgeMat = new THREE.LineBasicMaterial({ color: 0x22d3ee, linewidth: 2 });
            } else if (b.face_role === 'shared_corner') {
                mat = new THREE.MeshStandardMaterial({ color: 0xd4a373, roughness: 0.70, metalness: 0.06 });
                edgeMat = new THREE.LineBasicMaterial({ color: 0x8b5cf6, linewidth: 2 });
            } else {
                mat = new THREE.MeshStandardMaterial({ color: 0xcba06c, roughness: 0.75, metalness: 0.05 });
                edgeMat = new THREE.LineBasicMaterial({ color: 0x6e471d });
            }

            const mesh = new THREE.Mesh(itemGeo, mat);
            mesh.position.set(posX, posY, posZ);
            const edge = new THREE.LineSegments(itemEdgesGeo, edgeMat);
            edge.position.copy(mesh.position);
            wbThreeScene.add(edge);

            mesh.userData = {
                id: b.id,
                layer: b.layer,
                col: b.col,
                depth: b.depth,
                label: b.label || `Object #${b.id} (Layer ${(b.layer || 0) + 1}, Col ${(b.col || 0) + 1})`,
                isHidden: Boolean(b.is_hidden),
                origPos: { x: posX, y: posY, z: posZ },
                edgesMesh: edge
            };

            wbThreeBoxMeshes.push(mesh);
            wbThreeScene.add(mesh);
        });

        // Hover Tooltip using Raycaster
        const raycaster = new THREE.Raycaster();
        const mouse = new THREE.Vector2();
        const hoverDiv = document.getElementById('wbThreeJsHover');

        wbThreeRenderer.domElement.addEventListener('mousemove', (e) => {
            const rect = wbThreeRenderer.domElement.getBoundingClientRect();
            mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
            mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

            raycaster.setFromCamera(mouse, wbThreeCamera);
            const intersects = raycaster.intersectObjects(wbThreeBoxMeshes);

            if (intersects.length > 0 && hoverDiv) {
                const item = intersects[0].object.userData;
                hoverDiv.style.display = 'block';
                hoverDiv.innerHTML = `
                    <div style="font-weight:700; color:#38bdf8;">${item.label}</div>
                    <div style="font-size:0.65rem; color:${item.isHidden ? '#f59e0b' : '#10b981'};">
                        ${item.isHidden ? 'Inferred Hidden Unit' : 'Directly Localized Physical Object'}
                    </div>
                `;
            } else if (hoverDiv) {
                hoverDiv.style.display = 'none';
            }
        });

        if (wbThreeAnimId) cancelAnimationFrame(wbThreeAnimId);
        function anim() {
            wbThreeAnimId = requestAnimationFrame(anim);
            if (wbThreeControls) wbThreeControls.update();
            wbThreeRenderer.render(wbThreeScene, wbThreeCamera);
        }
        anim();
    }

    window.toggleWbExplode3D = function() {
        wbIsExploded = !wbIsExploded;
        const factor = wbIsExploded ? 1.6 : 1.0;
        wbThreeBoxMeshes.forEach(mesh => {
            const op = mesh.userData.origPos;
            if (!op) return;
            mesh.position.set(op.x * factor, op.y * factor, op.z * factor);
            if (mesh.userData.edgesMesh) {
                mesh.userData.edgesMesh.position.copy(mesh.position);
            }
        });
    };

    window.toggleWbXRay3D = function() {
        wbIsXRay = !wbIsXRay;
        wbThreeBoxMeshes.forEach(mesh => {
            if (!mesh.userData.isHidden) {
                mesh.material.transparent = wbIsXRay;
                mesh.material.opacity = wbIsXRay ? 0.35 : 1.0;
            }
        });
    };

    window.resetWb3DCamera = function() {
        if (wbThreeCamera && wbThreeControls) {
            wbThreeCamera.position.set(5.5, 4.8, 6.5);
            wbThreeControls.target.set(0, 1.0, 0);
            wbThreeControls.update();
        }
    };

    window.applyVerifiedCountToActivePallet = function() {
        const qb = (wbLatestResult && wbLatestResult.quantity_breakdown) || {};
        const baseCount = qb.total_units !== undefined ? qb.total_units : (wbLatestResult ? (wbLatestResult.total_pieces !== undefined ? wbLatestResult.total_pieces : (wbLatestResult.total_bundles || 0)) : 0);
        const uPerB = Math.max(1, parseInt(document.getElementById('wbUnitsPerBundleInput')?.value || document.getElementById('palletUnitsPerBundle')?.textContent || '1', 10));
        const uom = (document.getElementById('wbUomSelect')?.value || 'EA').toUpperCase();
        const bname = (document.getElementById('wbBundleNameInput')?.value || 'Bundle').trim() || 'Bundle';
        const totalIndividualUnits = baseCount * uPerB;

        const palletPcsElem = document.getElementById('palletTotalPieces');
        const palletBundlesElem = document.getElementById('palletCountBundles');
        const unitsPerBundleElem = document.getElementById('palletUnitsPerBundle');
        if (unitsPerBundleElem) unitsPerBundleElem.textContent = uPerB;

        if (wbMode === 'bundles' || uPerB > 1) {
            if (palletBundlesElem) palletBundlesElem.textContent = baseCount;
            if (palletPcsElem) palletPcsElem.textContent = totalIndividualUnits;
        } else {
            if (palletPcsElem) palletPcsElem.textContent = totalIndividualUnits;
            if (palletBundlesElem) palletBundlesElem.textContent = Math.max(1, Math.round(totalIndividualUnits / uPerB));
        }

        if (typeof showToast === 'function') {
            showToast(`Verified count (${baseCount} ${bname}s × ${uPerB} ${uom} = ${totalIndividualUnits} ${uom}) applied to active pallet build session.`, 'success');
        } else {
            alert(`Verified count applied to active pallet session: ${totalIndividualUnits} ${uom}`);
        }
    };

    function initWbDropZone() {
        const dropZone = document.getElementById('wbDropZone');
        const fileInput = document.getElementById('wbFileInput');
        if (!dropZone || !fileInput) return;

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.borderColor = '#38bdf8';
                dropZone.style.background = 'rgba(2, 132, 199, 0.15)';
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.borderColor = '#0284c7';
                dropZone.style.background = '#1e293b';
            }, false);
        });

        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt && dt.files;
            if (files && files.length > 0) {
                try { fileInput.files = files; } catch(ex) {}
                window.previewWorkbenchUpload(files[0]);
            }
        }, false);
    }

    // =========================================================================
    // INTERACTIVE INCLUDE / EXCLUDE COUNTING REGIONS CONTROLLER
    // =========================================================================

    window.setWorkbenchRegionTool = function(toolName) {
        wbCurrentTool = toolName || 'none';
        cancelWorkbenchRegionDraft();

        const canvas = document.getElementById('wbRegionDrawCanvas');
        if (canvas) {
            canvas.style.display = (wbCurrentTool === 'none') ? 'none' : 'block';
            if (wbCurrentTool !== 'none') {
                syncRegionDrawCanvasSize();
            }
        }

        const tools = ['Pointer', 'IncludeRect', 'ExcludeRect', 'IncludePoly', 'ExcludePoly'];
        tools.forEach(t => {
            const btn = document.getElementById(`wbBtnTool${t}`);
            if (btn) {
                btn.style.borderColor = 'rgba(255,255,255,0.15)';
                btn.style.boxShadow = 'none';
            }
        });

        let activeId = 'wbBtnToolPointer';
        if (wbCurrentTool === 'include_rect') activeId = 'wbBtnToolIncludeRect';
        else if (wbCurrentTool === 'exclude_rect') activeId = 'wbBtnToolExcludeRect';
        else if (wbCurrentTool === 'include_poly') activeId = 'wbBtnToolIncludePoly';
        else if (wbCurrentTool === 'exclude_poly') activeId = 'wbBtnToolExcludePoly';

        const activeBtn = document.getElementById(activeId);
        if (activeBtn) {
            activeBtn.style.borderColor = (wbCurrentTool.startsWith('exclude')) ? '#ef4444' : '#10b981';
            activeBtn.style.boxShadow = '0 0 0 2px rgba(255,255,255,0.2)';
        }
    };

    window.clearWorkbenchRegions = function(silent = false) {
        wbRegions = [];
        cancelWorkbenchRegionDraft();
        renderWorkbenchRegionsOverlay();
        updateRegionStatusBadge();
        if (!silent && wbRawImageUrl) {
            window.recertifyWorkbenchMarkers(true);
        }
    };

    function updateRegionStatusBadge() {
        const statusEl = document.getElementById('wbActiveRegionStatusText');
        if (!statusEl) return;
        if (!wbRegions || wbRegions.length === 0) {
            statusEl.textContent = 'No regions drawn';
            statusEl.style.color = '#64748b';
        } else {
            const inc = wbRegions.filter(r => r.region_type === 'include').length;
            const exc = wbRegions.filter(r => r.region_type === 'exclude').length;
            statusEl.textContent = `${wbRegions.length} Active (${inc} Inc, ${exc} Exc)`;
            statusEl.style.color = '#10b981';
        }
    }

    function syncRegionDrawCanvasSize() {
        const imgElem = document.getElementById('wbResultImg');
        const canvas = document.getElementById('wbRegionDrawCanvas');
        if (!imgElem || !canvas) return;
        const natW = imgElem.naturalWidth || imgElem.clientWidth || 800;
        const natH = imgElem.naturalHeight || imgElem.clientHeight || 600;
        canvas.width = natW;
        canvas.height = natH;
    }

    function cancelWorkbenchRegionDraft() {
        wbDrawingPolyPoints = [];
        wbIsDraggingRect = false;
        wbDragStart = null;
        const canvas = document.getElementById('wbRegionDrawCanvas');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }

    function renderWorkbenchRegionsOverlay() {
        const svg = document.getElementById('wbRegionsSvgOverlay');
        const imgElem = document.getElementById('wbResultImg');
        if (!svg) return;
        svg.innerHTML = '';
        if (!imgElem || !wbRegions || wbRegions.length === 0) return;

        const natW = imgElem.naturalWidth || imgElem.clientWidth || 800;
        const natH = imgElem.naturalHeight || imgElem.clientHeight || 600;
        svg.setAttribute('viewBox', `0 0 ${natW} ${natH}`);

        wbRegions.forEach((r, idx) => {
            const isInc = (r.region_type === 'include');
            const strokeColor = isInc ? '#10b981' : '#ef4444';
            const fillColor = isInc ? 'rgba(16, 185, 129, 0.16)' : 'rgba(239, 68, 68, 0.20)';
            const strokeWidth = Math.max(2, Math.round(natW / 500));
            const dashArray = isInc ? 'none' : '8,4';

            if (r.type === 'rect') {
                const rectEl = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                rectEl.setAttribute('x', r.x);
                rectEl.setAttribute('y', r.y);
                rectEl.setAttribute('width', r.w);
                rectEl.setAttribute('height', r.h);
                rectEl.setAttribute('rx', '4');
                rectEl.setAttribute('fill', fillColor);
                rectEl.setAttribute('stroke', strokeColor);
                rectEl.setAttribute('stroke-width', strokeWidth);
                rectEl.setAttribute('stroke-dasharray', dashArray);
                svg.appendChild(rectEl);

                const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                txt.setAttribute('x', r.x + 8);
                txt.setAttribute('y', Math.max(22, r.y + 20));
                txt.setAttribute('fill', strokeColor);
                txt.setAttribute('font-size', String(Math.max(12, Math.round(natW / 65))));
                txt.setAttribute('font-weight', '700');
                txt.setAttribute('font-family', 'system-ui, sans-serif');
                txt.textContent = isInc ? `+ INCLUDE REGION #${idx + 1}` : `- EXCLUDE REGION #${idx + 1}`;
                svg.appendChild(txt);
            } else if (r.type === 'polygon' && r.points && r.points.length > 0) {
                const polyEl = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                const ptsStr = r.points.map(pt => `${pt[0]},${pt[1]}`).join(' ');
                polyEl.setAttribute('points', ptsStr);
                polyEl.setAttribute('fill', fillColor);
                polyEl.setAttribute('stroke', strokeColor);
                polyEl.setAttribute('stroke-width', strokeWidth);
                polyEl.setAttribute('stroke-dasharray', dashArray);
                svg.appendChild(polyEl);

                const p0 = r.points[0];
                const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                txt.setAttribute('x', p0[0] + 8);
                txt.setAttribute('y', Math.max(22, p0[1] + 20));
                txt.setAttribute('fill', strokeColor);
                txt.setAttribute('font-size', String(Math.max(12, Math.round(natW / 65))));
                txt.setAttribute('font-weight', '700');
                txt.setAttribute('font-family', 'system-ui, sans-serif');
                txt.textContent = isInc ? `+ INCLUDE REGION #${idx + 1}` : `- EXCLUDE REGION #${idx + 1}`;
                svg.appendChild(txt);
            }
        });
    }

    function initRegionDrawingEvents() {
        const canvas = document.getElementById('wbRegionDrawCanvas');
        if (!canvas) return;

        function getCanvasNaturalPos(e) {
            const rect = canvas.getBoundingClientRect();
            const clientX = e.clientX - rect.left;
            const clientY = e.clientY - rect.top;
            const scaleX = canvas.width / Math.max(1, rect.width);
            const scaleY = canvas.height / Math.max(1, rect.height);
            return {
                x: Math.round(clientX * scaleX),
                y: Math.round(clientY * scaleY),
                clientX,
                clientY
            };
        }

        canvas.addEventListener('mousedown', (e) => {
            if (wbCurrentTool === 'none') return;
            const pos = getCanvasNaturalPos(e);

            if (wbCurrentTool === 'include_rect' || wbCurrentTool === 'exclude_rect') {
                wbIsDraggingRect = true;
                wbDragStart = pos;
            } else if (wbCurrentTool === 'include_poly' || wbCurrentTool === 'exclude_poly') {
                if (wbDrawingPolyPoints.length >= 3) {
                    const firstPt = wbDrawingPolyPoints[0];
                    const dist = Math.hypot(firstPt[0] - pos.x, firstPt[1] - pos.y);
                    const thresholdNat = (canvas.width / Math.max(1, canvas.clientWidth)) * 18;
                    if (dist <= thresholdNat) {
                        completePolygonRegion();
                        return;
                    }
                }
                wbDrawingPolyPoints.push([pos.x, pos.y]);
                drawCurrentDraft();
            }
        });

        canvas.addEventListener('mousemove', (e) => {
            if (wbCurrentTool === 'none') return;
            const pos = getCanvasNaturalPos(e);

            if (wbIsDraggingRect && wbDragStart) {
                drawRectDraft(wbDragStart, pos);
            } else if ((wbCurrentTool === 'include_poly' || wbCurrentTool === 'exclude_poly') && wbDrawingPolyPoints.length > 0) {
                drawPolyDraft(pos);
            }
        });

        canvas.addEventListener('mouseup', (e) => {
            if (wbCurrentTool === 'none') return;
            if (wbIsDraggingRect && wbDragStart) {
                const pos = getCanvasNaturalPos(e);
                const rx = Math.min(wbDragStart.x, pos.x);
                const ry = Math.min(wbDragStart.y, pos.y);
                const rw = Math.abs(pos.x - wbDragStart.x);
                const rh = Math.abs(pos.y - wbDragStart.y);

                wbIsDraggingRect = false;
                wbDragStart = null;

                if (rw > 10 && rh > 10) {
                    const rtype = wbCurrentTool.startsWith('exclude') ? 'exclude' : 'include';
                    wbRegions.push({
                        id: `reg_${Date.now()}_${wbRegions.length + 1}`,
                        type: 'rect',
                        region_type: rtype,
                        x: rx,
                        y: ry,
                        w: rw,
                        h: rh
                    });
                    setWorkbenchRegionTool('none');
                    renderWorkbenchRegionsOverlay();
                    updateRegionStatusBadge();
                    if (wbRawImageUrl) {
                        window.recertifyWorkbenchMarkers(true);
                    }
                } else {
                    cancelWorkbenchRegionDraft();
                }
            }
        });

        canvas.addEventListener('dblclick', (e) => {
            if (wbCurrentTool === 'include_poly' || wbCurrentTool === 'exclude_poly') {
                e.preventDefault();
                e.stopPropagation();
                if (wbDrawingPolyPoints.length >= 3) {
                    completePolygonRegion();
                }
            }
        });

        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' || e.code === 'Escape') {
                if (wbCurrentTool !== 'none' || wbDrawingPolyPoints.length > 0 || wbIsDraggingRect) {
                    setWorkbenchRegionTool('none');
                }
            }
        });

        function completePolygonRegion() {
            if (wbDrawingPolyPoints.length < 3) return;
            const rtype = wbCurrentTool.startsWith('exclude') ? 'exclude' : 'include';
            wbRegions.push({
                id: `reg_${Date.now()}_${wbRegions.length + 1}`,
                type: 'polygon',
                region_type: rtype,
                points: [...wbDrawingPolyPoints]
            });
            setWorkbenchRegionTool('none');
            renderWorkbenchRegionsOverlay();
            updateRegionStatusBadge();
            if (wbRawImageUrl) {
                window.recertifyWorkbenchMarkers(true);
            }
        }

        function drawRectDraft(start, current) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const isInc = wbCurrentTool.startsWith('include');
            const rx = Math.min(start.x, current.x);
            const ry = Math.min(start.y, current.y);
            const rw = Math.abs(current.x - start.x);
            const rh = Math.abs(current.y - start.y);

            ctx.fillStyle = isInc ? 'rgba(16, 185, 129, 0.20)' : 'rgba(239, 68, 68, 0.25)';
            ctx.fillRect(rx, ry, rw, rh);
            ctx.strokeStyle = isInc ? '#10b981' : '#ef4444';
            ctx.lineWidth = Math.max(2, Math.round(canvas.width / 500));
            if (!isInc) ctx.setLineDash([8, 4]);
            else ctx.setLineDash([]);
            ctx.strokeRect(rx, ry, rw, rh);
        }

        function drawPolyDraft(currPos) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (wbDrawingPolyPoints.length === 0) return;

            const isInc = wbCurrentTool.startsWith('include');
            ctx.strokeStyle = isInc ? '#10b981' : '#ef4444';
            ctx.lineWidth = Math.max(2, Math.round(canvas.width / 500));
            if (!isInc) ctx.setLineDash([8, 4]);
            else ctx.setLineDash([]);

            ctx.beginPath();
            ctx.moveTo(wbDrawingPolyPoints[0][0], wbDrawingPolyPoints[0][1]);
            for (let i = 1; i < wbDrawingPolyPoints.length; i++) {
                ctx.lineTo(wbDrawingPolyPoints[i][0], wbDrawingPolyPoints[i][1]);
            }
            if (currPos) {
                ctx.lineTo(currPos.x, currPos.y);
            }
            ctx.stroke();

            ctx.setLineDash([]);
            wbDrawingPolyPoints.forEach((pt, idx) => {
                ctx.fillStyle = (idx === 0) ? '#ffffff' : (isInc ? '#10b981' : '#ef4444');
                ctx.beginPath();
                ctx.arc(pt[0], pt[1], Math.max(5, Math.round(canvas.width / 200)), 0, 2 * Math.PI);
                ctx.fill();
                ctx.strokeStyle = '#000000';
                ctx.lineWidth = 1.5;
                ctx.stroke();
            });
        }

        function drawCurrentDraft() {
            drawPolyDraft(null);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initUnifiedDropZone();
            initWbDropZone();
            initRegionDrawingEvents();
            window.loadVisionSkus();
        });
    } else {
        initUnifiedDropZone();
        initWbDropZone();
        initRegionDrawingEvents();
        window.loadVisionSkus();
    }

})();

    // =========================================================================
    // STAGE 6: Multi-View Operator Review & Association Auditing Workflow
    // =========================================================================
    window.currentMultiViewSession = null;

    function renderOperatorReviewDrawer(session) {
        const listEl = document.getElementById('wbOperatorReviewObjectsList');
        if (!listEl) return;
        listEl.innerHTML = '';

        const objects = session.fused_objects || session.pieces || [];
        const ambiguous = session.ambiguous_candidates || [];

        if (objects.length === 0 && ambiguous.length === 0) {
            listEl.innerHTML = '<div style="color:#64748b; font-size:0.7rem; font-style:italic; padding:4px 0;">No grouped objects available for review.</div>';
            return;
        }

        // Render Fused Object Cards
        objects.forEach(obj => {
            const card = document.createElement('div');
            card.style.cssText = 'background:#1e293b; border:1px solid #334155; border-radius:5px; padding:6px 8px; display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:0.68rem;';

            const left = document.createElement('div');
            left.style.cssText = 'display:flex; align-items:center; gap:8px;';

            if (obj.crop_url) {
                const img = document.createElement('img');
                img.src = obj.crop_url;
                img.style.cssText = 'width:36px; height:36px; object-fit:cover; border-radius:4px; border:1px solid #475569;';
                left.appendChild(img);
            } else {
                const iconBox = document.createElement('div');
                iconBox.style.cssText = 'width:36px; height:36px; background:#0f172a; border-radius:4px; display:flex; align-items:center; justify-content:center; color:#64748b; font-size:0.9rem;';
                iconBox.innerHTML = '<i class="fas fa-cube"></i>';
                left.appendChild(iconBox);
            }

            const info = document.createElement('div');
            const contributing = (obj.contributing_views || [obj.primary_view || 'front']).join(' + ').toUpperCase();
            const statusColor = (obj.status === 'CONFIRMED' && !obj.is_uncertain) ? '#34d399' : '#fbbf24';
            info.innerHTML = `
                <div style="font-weight:700; color:#f8fafc; display:flex; align-items:center; gap:5px;">
                    <span>${obj.object_id || obj.detection_id}</span>
                    <span style="font-size:0.6rem; color:${statusColor}; background:rgba(255,255,255,0.06); padding:1px 4px; border-radius:3px;">${obj.status || 'CONFIRMED'}</span>
                </div>
                <div style="color:#94a3b8; font-size:0.62rem;">Views: <span style="color:#38bdf8;">${contributing}</span> | Tier: ${obj.tier_index !== undefined ? obj.tier_index : 0}</div>
            `;
            left.appendChild(info);

            const actions = document.createElement('div');
            actions.style.cssText = 'display:flex; gap:4px;';

            // Confirm Button
            if (obj.status !== 'CONFIRMED' || obj.is_uncertain) {
                const confirmBtn = document.createElement('button');
                confirmBtn.type = 'button';
                confirmBtn.style.cssText = 'background:#059669; color:#fff; border:none; border-radius:3px; padding:2px 6px; font-size:0.62rem; cursor:pointer; font-weight:600;';
                confirmBtn.textContent = 'Confirm';
                confirmBtn.onclick = () => window.reviewWorkbenchSession('confirm_object', obj.object_id || obj.detection_id);
                actions.appendChild(confirmBtn);
            }

            // Separate Observations Button (enabled when > 1 contributing view)
            if ((obj.contributing_views && obj.contributing_views.length > 1) || (obj.observations && Object.keys(obj.observations).length > 1)) {
                const sepBtn = document.createElement('button');
                sepBtn.type = 'button';
                sepBtn.style.cssText = 'background:#d97706; color:#fff; border:none; border-radius:3px; padding:2px 6px; font-size:0.62rem; cursor:pointer; font-weight:600;';
                sepBtn.textContent = 'Separate';
                sepBtn.title = 'Separate cross-view observations into distinct objects';
                sepBtn.onclick = () => window.reviewWorkbenchSession('separate_object', obj.object_id || obj.detection_id);
                actions.appendChild(sepBtn);
            }

            // Mark Uncertain Button
            if (obj.status !== 'UNCERTAIN' && !obj.is_uncertain) {
                const uncertBtn = document.createElement('button');
                uncertBtn.type = 'button';
                uncertBtn.style.cssText = 'background:#475569; color:#fca5a5; border:none; border-radius:3px; padding:2px 6px; font-size:0.62rem; cursor:pointer; font-weight:600;';
                uncertBtn.textContent = 'Flag';
                uncertBtn.title = 'Mark as uncertain candidate without counting';
                uncertBtn.onclick = () => window.reviewWorkbenchSession('mark_uncertain', obj.object_id || obj.detection_id);
                actions.appendChild(uncertBtn);
            }

            card.appendChild(left);
            card.appendChild(actions);
            listEl.appendChild(card);
        });

        // Render Ambiguous Candidates
        ambiguous.forEach((amb, idx) => {
            const card = document.createElement('div');
            card.style.cssText = 'background:#1e293b; border:1px dashed #ef4444; border-radius:5px; padding:6px 8px; display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:0.68rem;';

            const left = document.createElement('div');
            left.style.cssText = 'display:flex; align-items:center; gap:8px;';

            const iconBox = document.createElement('div');
            iconBox.style.cssText = 'width:36px; height:36px; background:#450a0a; border-radius:4px; display:flex; align-items:center; justify-content:center; color:#f87171; font-size:0.9rem;';
            iconBox.innerHTML = '<i class="fas fa-question-circle"></i>';
            left.appendChild(iconBox);

            const info = document.createElement('div');
            info.innerHTML = `
                <div style="font-weight:700; color:#fca5a5;">Ambiguous Candidate #${idx+1}</div>
                <div style="color:#94a3b8; font-size:0.62rem;">View: ${amb.view_label || 'secondary'} | Score: ${amb.best_score ? Math.round(amb.best_score*100)+'%' : 'N/A'}</div>
            `;
            left.appendChild(info);

            const actions = document.createElement('div');
            actions.style.cssText = 'display:flex; gap:4px;';

            const confBtn = document.createElement('button');
            confBtn.type = 'button';
            confBtn.style.cssText = 'background:#059669; color:#fff; border:none; border-radius:3px; padding:2px 6px; font-size:0.62rem; cursor:pointer; font-weight:600;';
            confBtn.textContent = 'Accept';
            confBtn.title = 'Accept and confirm as distinct object';
            confBtn.onclick = () => window.reviewWorkbenchSession('confirm_object', amb.candidate_obj_id);
            actions.appendChild(confBtn);

            card.appendChild(left);
            card.appendChild(actions);
            listEl.appendChild(card);
        });
    }

    window.reviewWorkbenchSession = async function(action, objectId = null, secondaryView = null, notes = null) {
        if (!window.currentMultiViewSession || !window.currentMultiViewSession.session_id) {
            console.warn('[ReviewWorkbench] No active multi-view session available for review.');
            return;
        }

        const sessId = window.currentMultiViewSession.session_id;
        try {
            const resp = await fetch('/api/pallets/multiview-review', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessId,
                    action: action,
                    object_id: objectId,
                    secondary_view: secondaryView,
                    notes: notes
                })
            });

            const data = await resp.json();
            if (data.success) {
                window.currentMultiViewSession = data;
                // Re-render UI with updated session state
                renderWorkbenchResults(data);
                if (typeof showToast === 'function') {
                    showToast(`Review action '${action}' applied: primary count is now ${data.primary_count}.`, 'success');
                }
            } else {
                console.error('[ReviewWorkbench] Error:', data.error);
                if (typeof showToast === 'function') {
                    showToast(`Review action failed: ${data.error}`, 'error');
                }
            }
        } catch (err) {
            console.error('[ReviewWorkbench] Network error:', err);
            if (typeof showToast === 'function') {
                showToast(`Review action network error: ${err.message}`, 'error');
            }
        }
    };

    window.recalculateWorkbenchMultiView = function() {
        window.reviewWorkbenchSession('recalculate');
    };
