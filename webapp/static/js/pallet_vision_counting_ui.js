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
        } catch (e) {
            console.error('Failed to load vision SKUs:', e);
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

        // In BOX_GRID mode (or when backend image already contains authoritative annotations):
        // The backend has burned primary numbered badges, bounding boxes, and confidence tags directly
        // into the image pixels with 1-to-1 coordinate fidelity.
        // We do NOT draw a duplicate layer of DOM numbered circles over every automated detection!
        // The overlay is reserved strictly for manual operator pins (+M1, +M2...) added by clicking.
        if (latestPiecesResult && (latestPiecesResult.mode === 'BOX_GRID' || latestPiecesResult.matrix_3d)) {
            manualPinsList.forEach((pin, pIdx) => {
                const leftPct = (pin.x / imgW) * 100;
                const topPct = (pin.y / imgH) * 100;

                const badge = document.createElement('div');
                badge.className = 'interactive-piece-badge manual-operator-pin';
                badge.style.cssText = `
                    position: absolute;
                    left: ${leftPct}%;
                    top: ${topPct}%;
                    transform: translate(-50%, -50%);
                    width: 24px;
                    height: 24px;
                    border-radius: 50%;
                    background: #f59e0b;
                    border: 2px solid #ffffff;
                    color: #ffffff;
                    font-size: 10px;
                    font-weight: 800;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                    pointer-events: auto;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.6);
                    user-select: none;
                    transition: transform 0.15s, background 0.15s;
                    z-index: 10;
                `;
                badge.title = `Manual Operator Pin #M${pIdx + 1}\nClick to Remove`;
                badge.textContent = `M${pIdx + 1}`;
                badge.onmouseenter = () => {
                    badge.style.transform = 'translate(-50%, -50%) scale(1.3)';
                    badge.style.background = '#ef4444';
                };
                badge.onmouseleave = () => {
                    badge.style.transform = 'translate(-50%, -50%) scale(1)';
                    badge.style.background = '#f59e0b';
                };
                badge.onclick = (e) => {
                    e.stopPropagation();
                    window.removeManualPin(pIdx);
                };
                overlay.appendChild(badge);
            });
            return;
        }

        // For Individual Pieces pinpoint mode (non-carton):
        currentPiecesList.forEach((p, idx) => {
            const leftPct = (p.x / imgW) * 100;
            const topPct = (p.y / imgH) * 100;

            const badge = document.createElement('div');
            badge.className = 'interactive-piece-badge';
            badge.style.cssText = `
                position: absolute;
                left: ${leftPct}%;
                top: ${topPct}%;
                transform: translate(-50%, -50%);
                width: 22px;
                height: 22px;
                border-radius: 50%;
                background: ${p.color_hex || '#0284c7'};
                border: 2px solid #ffffff;
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                pointer-events: auto;
                box-shadow: 0 2px 6px rgba(0,0,0,0.5);
                user-select: none;
                transition: transform 0.15s, background 0.15s;
            `;
            badge.title = `Piece #${p.id || (idx + 1)} (${p.cluster || 'Item'})\nClick to Delete`;
            badge.textContent = p.id || (idx + 1);

            badge.onmouseenter = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1.4)';
                badge.style.background = '#ef4444'; // Red delete indicator
            };
            badge.onmouseleave = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1)';
                badge.style.background = p.color_hex || '#0284c7';
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

        if (latestPiecesResult && (latestPiecesResult.mode === 'BOX_GRID' || latestPiecesResult.matrix_3d)) {
            // Add manual operator pin in carton mode without altering automated verified count
            const pIdx = manualPinsList.length + 1;
            manualPinsList.push({
                id: `M${pIdx}`,
                x: naturalX,
                y: naturalY,
                is_manual: true
            });
            updateLocalManualPinsState();
            renderInteractiveBadgesOverlay();
            return;
        }

        // Add verified point for individual pieces
        const newIdx = currentPiecesList.length + 1;
        currentPiecesList.push({
            id: newIdx,
            x: naturalX,
            y: naturalY,
            cluster: 'Verified item',
            color_hex: '#10b981'
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

                if (!f1 && !f2 && !selectedSku) {
                    formData.append('preset_name', 'timber_48');
                }
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
        const cols = matrix3D.columns || 3;
        const depth = matrix3D.depth || 1;
        const layers = matrix3D.layers || 4;
        const isRegularGrid = (matrix3D.reconstruction_mode === 'OPERATOR_CONFIRMED');
        const SCENE_SPAN_X = Math.max(2.4, Math.min(5.2, cols * 1.05));
        const SCENE_SPAN_Y = Math.max(1.8, Math.min(4.5, layers * 0.85));

        const hasPallet = matrix3D.has_pallet === true;
        const palletW = isRegularGrid ? (cols * 1.05 + 0.35) : (SCENE_SPAN_X + 0.4);
        const palletD = isRegularGrid ? Math.max(depth * 1.05 + 0.35, 1.4) : 1.4;
        const palletH = hasPallet ? 0.16 : 0.0;

        if (typeof THREE.OrbitControls !== 'undefined') {
            threeControls = new THREE.OrbitControls(threeCamera, threeRenderer.domElement);
            threeControls.enableDamping = true;
            threeControls.dampingFactor = 0.08;
            threeControls.maxPolarAngle = Math.PI / 2 - 0.02; // Don't go below ground
            threeControls.minDistance = 2.0;
            threeControls.maxDistance = 20.0;
            const targetY = isRegularGrid ? (layers * 0.80 / 2) + palletH : (SCENE_SPAN_Y / 2) + palletH;
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
            // Wooden material
            const woodMat = new THREE.MeshStandardMaterial({
                color: 0x92663b,
                roughness: 0.85,
                metalness: 0.05
            });

            // Top deck slats
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

            // Bottom runners (3 stringers)
            for (let s = -1; s <= 1; s++) {
                const runnerGeo = new THREE.BoxGeometry(0.12, palletH - 0.04, palletD);
                const runnerMesh = new THREE.Mesh(runnerGeo, woodMat);
                runnerMesh.position.set(s * (palletW * 0.42), (palletH - 0.04) / 2, 0);
                runnerMesh.receiveShadow = true;
                threeScene.add(runnerMesh);
            }
        }

        // 8. Construct 3D Boxes (Visible front/side solid, Hidden rear/interior translucent)
        (matrix3D.boxes || []).forEach(b => {
            let boxW = 0.96;
            let boxH = 0.76;
            let boxD = 0.96;
            let posX = 0;
            let posY = 0;
            let posZ = 0;

            if (isRegularGrid) {
                // Regular confirmed 3D matrix (rows x cols x layers)
                posX = (b.col - (cols - 1) / 2) * 1.02;
                posY = b.layer * 0.80 + 0.38 + palletH;
                posZ = (b.depth - (depth - 1) / 2) * 1.02;
            } else {
                // Direct Physical Object Localization (irregular stack or elevation facade)
                boxW = Math.max(0.35, (b.norm_w || 0.3) * SCENE_SPAN_X * 0.96);
                boxH = Math.max(0.28, (b.norm_h || 0.25) * SCENE_SPAN_Y * 0.96);
                boxD = Math.min(boxW, 1.2);
                posX = (b.norm_x || 0) * SCENE_SPAN_X;
                posY = (b.norm_y || 0) * SCENE_SPAN_Y + (boxH / 2) + palletH;
                posZ = 0;
            }

            const boxGeo = new THREE.BoxGeometry(boxW, boxH, boxD);
            const edgesGeo = new THREE.EdgesGeometry(boxGeo);

            let boxMat = null;
            let edgeMat = null;

            if (b.is_hidden) {
                // OCCLUDED / REAR / INTERIOR BOXES: Translucent Holographic Glass
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
            } else {
                // VISIBLE FRONT & SIDE BOXES: Realistic Warm Cardboard Box
                boxMat = new THREE.MeshStandardMaterial({
                    color: 0xcba06c, // Cardboard kraft paper
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
        if (mode === 'pieces') {
            if (btnP) { btnP.style.background = '#0284c7'; btnP.style.color = '#fff'; }
            if (btnB) { btnB.style.background = 'transparent'; btnB.style.color = '#94a3b8'; }
        } else {
            if (btnB) { btnB.style.background = '#0284c7'; btnB.style.color = '#fff'; }
            if (btnP) { btnP.style.background = 'transparent'; btnP.style.color = '#94a3b8'; }
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
        if (statVis) statVis.textContent = '0';
        if (statInf) statInf.textContent = '0';
        if (statForm) statForm.textContent = '--';

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
        if (statVis) statVis.textContent = '0';
        if (statInf) statInf.textContent = '0';
        if (statForm) statForm.textContent = '--';

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

        const thisRequestId = ++wbCountRequestId;

        try {
            const formData = new FormData();
            formData.append('source_type', wbSource);
            formData.append('counting_mode', wbMode === 'bundles' ? 'bundles' : 'auto');

            const camSelect = document.getElementById('wbCameraSelect') || document.getElementById('palletCameraSelect');
            const camId = camSelect ? camSelect.value : 'cam_inbound_01';
            formData.append('camera_id', camId);

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

            const endpoint = wbMode === 'bundles' ? '/api/pallets/count-bundles' : '/api/pallets/count-pieces';
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
        const stageCard = document.getElementById('wbInteractiveStageCard');
        if (stageCard) {
            stageCard.style.display = 'block';
            setTimeout(() => {
                stageCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 100);
        }

        const qb = data.quantity_breakdown || {};
        const total = qb.total_units !== undefined ? qb.total_units : (data.total_pieces !== undefined ? data.total_pieces : (data.total_bundles || 0));
        const visible = qb.visible_count !== undefined ? qb.visible_count : (data.visible_pieces !== undefined ? data.visible_pieces : (qb.visible_bundles !== undefined ? qb.visible_bundles : total));
        const inferred = qb.inferred_count !== undefined ? qb.inferred_count : (data.hidden_count || 0);
        const autoGeom = qb.automated_geometry || data.automated_geometry || {};

        // Update Proposed Count badge
        const totalBadge = document.getElementById('wbTotalBadge');
        if (totalBadge) {
            totalBadge.textContent = `${total} ${data.mode === 'BUNDLE_STACK' ? 'BUNDLES' : 'PIECES'}`;
        }

        // Update Inferred Geometry Formula (Read-Only)
        const formulaElem = document.getElementById('wbAutoGeometryFormula');
        const methodBadge = document.getElementById('wbCountingMethodBadge');
        if (methodBadge) {
            methodBadge.textContent = qb.counting_method || data.method || 'AUTOMATED_CV';
        }
        if (formulaElem) {
            if (total === 0) {
                formulaElem.textContent = data.confidence_note || data.message || '0 Countable Units Localized (Insufficient Visual Evidence)';
                formulaElem.style.color = '#f59e0b';
            } else if (qb.formula) {
                formulaElem.textContent = qb.formula;
                formulaElem.style.color = '#10b981';
            } else if ((autoGeom.stack_detected || autoGeom.is_regular_matrix) && autoGeom.layers && autoGeom.columns) {
                const confText = qb.is_estimate ? 'Estimated Stack' : 'Direct Geometry';
                formulaElem.textContent = `${autoGeom.layers} Layers × ${autoGeom.columns} Cols × ${autoGeom.rows || autoGeom.depth || 1} Depth = ${total} Units (${confText})`;
                formulaElem.style.color = '#10b981';
            } else if (data.mode === 'BUNDLE_STACK') {
                formulaElem.textContent = `${total} Bundles Detected (${data.stacks?.length || 1} Stack Groups)`;
                formulaElem.style.color = '#38bdf8';
            } else {
                formulaElem.textContent = `${visible} Exterior Units Localized`;
                formulaElem.style.color = '#38bdf8';
            }
        }

        // Update 4-Stat breakdown
        const statVis = document.getElementById('wbStatVisible');
        const statInf = document.getElementById('wbStatInferred');
        const statForm = document.getElementById('wbStatFormula');
        if (statVis) statVis.textContent = visible;
        if (statInf) statInf.textContent = inferred;
        if (statForm) {
            statForm.textContent = qb.formula || data.grid_formula || `${visible} Visible Units`;
            statForm.title = statForm.textContent;
        }

        // Status badge: clear indication of PROPOSED (Estimated vs Direct vs Insufficient)
        const statusBadge = document.getElementById('wbVerificationStatusBadge');
        if (statusBadge) {
            let stText = 'PROPOSED (AI Estimate)';
            let stColor = '#38bdf8';
            let stBorder = 'rgba(56,189,248,0.3)';
            let stBg = 'rgba(56,189,248,0.15)';

            if (total === 0 || qb.verification_status === 'INSUFFICIENT_VISUAL_EVIDENCE') {
                stText = 'INSUFFICIENT VISUAL EVIDENCE';
                stColor = '#f59e0b';
                stBorder = 'rgba(245,158,11,0.3)';
                stBg = 'rgba(245,158,11,0.15)';
            } else if (qb.verification_status === 'DIRECT_VISUAL' || qb.verification_status === 'AUTOMATED_DETECTION' || (inferred === 0 && !qb.is_estimate)) {
                stText = 'DIRECT VISUAL (Confirmed)';
                stColor = '#10b981';
                stBorder = 'rgba(16,185,129,0.3)';
                stBg = 'rgba(16,185,129,0.15)';
            } else if (qb.verification_status === 'ESTIMATED_STACK' || qb.is_estimate) {
                stText = 'PROPOSED (Estimated Stack)';
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

        // Cluster pills
        renderWbClusterPills(data.clusters);

        // 3D Digital Twin: only render if multi-layer stacked geometry exists
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

        wbCurrentPieces.forEach((p, idx) => {
            const seqId = idx + 1;
            p.id = seqId;

            const leftPct = (p.x / imgW) * 100;
            const topPct = (p.y / imgH) * 100;

            const badge = document.createElement('div');
            badge.className = 'interactive-piece-badge';
            badge.style.cssText = `
                position: absolute;
                left: ${leftPct}%;
                top: ${topPct}%;
                transform: translate(-50%, -50%);
                width: 22px;
                height: 22px;
                border-radius: 50%;
                background: ${p.color_hex || '#0284c7'};
                border: 2px solid #ffffff;
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                pointer-events: auto;
                box-shadow: 0 2px 6px rgba(0,0,0,0.5);
                user-select: none;
                transition: transform 0.15s, background 0.15s;
            `;
            badge.title = `Visible Item #${seqId} (${p.cluster || 'Item'})\nClick to Delete`;
            badge.textContent = seqId;

            badge.onmouseenter = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1.35)';
                badge.style.background = '#ef4444';
            };
            badge.onmouseleave = () => {
                badge.style.transform = 'translate(-50%, -50%) scale(1)';
                badge.style.background = p.color_hex || '#0284c7';
            };
            badge.onclick = (e) => {
                e.stopPropagation();
                window.removeWorkbenchBadge(idx);
            };

            overlay.appendChild(badge);
        });
    }

    window.handleWorkbenchCanvasClick = function(event) {
        const imgElem = document.getElementById('wbResultImg');
        if (!imgElem) return;

        const rect = imgElem.getBoundingClientRect();
        const clickX = event.clientX - rect.left;
        const clickY = event.clientY - rect.top;

        const imgW = imgElem.naturalWidth || imgElem.clientWidth || 1;
        const imgH = imgElem.naturalHeight || imgElem.clientHeight || 1;

        const naturalX = Math.round((clickX / rect.width) * imgW);
        const naturalY = Math.round((clickY / rect.height) * imgH);

        const newId = wbCurrentPieces.length + 1;
        wbCurrentPieces.push({
            id: newId,
            x: naturalX,
            y: naturalY,
            cluster: 'Operator Added',
            color_hex: '#10b981'
        });

        updateLocalWorkbenchState();
        renderWbBadgesOverlay();
    };

    window.removeWorkbenchBadge = function(index) {
        if (index >= 0 && index < wbCurrentPieces.length) {
            wbCurrentPieces.splice(index, 1);
            wbCurrentPieces.forEach((p, i) => { p.id = i + 1; });
            updateLocalWorkbenchState();
            renderWbBadgesOverlay();
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
            statusBadge.textContent = 'PROPOSED (Operator Adjusted)';
            statusBadge.style.color = '#38bdf8';
            statusBadge.style.borderColor = 'rgba(56,189,248,0.3)';
            statusBadge.style.background = 'rgba(56,189,248,0.15)';
        }
    }

    window.recertifyWorkbenchMarkers = async function() {
        if (!wbRawImageUrl || wbCurrentPieces.length === 0) {
            alert('No image loaded to re-render.');
            return;
        }

        try {
            const autoGeom = wbLatestResult?.quantity_breakdown?.automated_geometry || {};
            const res = await fetch('/api/pallets/re-render-pieces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    raw_image_url: wbRawImageUrl,
                    pieces: wbCurrentPieces,
                    matrix_dimensions: autoGeom.stack_detected ? {
                        rows: autoGeom.rows || 1,
                        columns: autoGeom.columns || 1,
                        layers: autoGeom.layers || 1
                    } : null
                })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                const img = document.getElementById('wbResultImg');
                if (img && data.annotated_image_url) {
                    img.src = `${data.annotated_image_url}?t=${Date.now()}`;
                }
                renderWorkbenchResults(data);
                if (typeof showToast === 'function') {
                    showToast(`Re-rendered: ${data.total_pieces} pieces verified.`, 'success');
                }
            } else {
                alert(`Re-render error: ${data.error || 'Failed to re-render'}`);
            }
        } catch(e) {
            console.error('Re-render error:', e);
            alert(`Error: ${e.message}`);
        }
    };

    function initWb3DPalletViewer(matrixData) {
        const container = document.getElementById('wbThreeJsContainer');
        if (!container) return;

        const loading = document.getElementById('wbThreeJsLoading');
        const placeholder = document.getElementById('wbThreeJsPlaceholder');
        if (loading) loading.style.display = 'none';

        // If no multi-layer 3D stack was recognized, display the clean 2D planar status
        if (!matrixData || !matrixData.boxes || matrixData.boxes.length === 0) {
            if (placeholder) {
                placeholder.style.display = 'block';
                placeholder.innerHTML = `
                    <i class="fas fa-layer-group" style="font-size:1.8rem; margin-bottom:6px; opacity:0.5; color:#38bdf8; display:block;"></i>
                    <div style="font-weight:700; color:#cbd5e1; font-size:0.78rem;">Direct Visual Count Active (2D Surface)</div>
                    <div style="font-size:0.7rem; color:#64748b; margin-top:2px;">3D Digital Twin generates automatically when a multi-layer stacked geometry is detected.</div>
                `;
            }
            const existingCanvas = container.querySelector('canvas');
            if (existingCanvas) existingCanvas.remove();
            return;
        }

        if (placeholder) placeholder.style.display = 'none';

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

        const ControlsClass = THREE.OrbitControls || window.OrbitControls;
        if (typeof ControlsClass !== 'undefined') {
            wbThreeControls = new ControlsClass(wbThreeCamera, wbThreeRenderer.domElement);
            wbThreeControls.enableDamping = true;
            wbThreeControls.dampingFactor = 0.08;
            wbThreeControls.maxPolarAngle = Math.PI / 2 - 0.02;
            wbThreeControls.target.set(0, 1.0, 0);
            wbThreeControls.update();
        }

        const ambLight = new THREE.AmbientLight(0xffffff, 0.85);
        wbThreeScene.add(ambLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
        dirLight.position.set(8, 14, 10);
        wbThreeScene.add(dirLight);

        const gridHelper = new THREE.GridHelper(14, 14, 0x1e293b, 0x0f172a);
        wbThreeScene.add(gridHelper);

        // Wooden Pallet Base (Tare packaging, excluded from inventory count)
        const cols = matrixData.columns || 5;
        const rows = matrixData.rows || matrixData.depth || 5;
        const layers = matrixData.layers || 5;

        const palletW = cols * 0.9 + 0.3;
        const palletD = rows * 0.9 + 0.3;
        const palletH = 0.15;

        const woodMat = new THREE.MeshStandardMaterial({ color: 0x8a5d3b, roughness: 0.85 });
        const slatGeo = new THREE.BoxGeometry(palletW, 0.04, 0.12);
        for (let i = 0; i < 7; i++) {
            const slat = new THREE.Mesh(slatGeo, woodMat);
            slat.position.set(0, palletH - 0.02, -palletD/2 + (i + 0.5) * (palletD / 7));
            wbThreeScene.add(slat);
        }

        // Inventory Boxes
        const boxGeo = new THREE.BoxGeometry(0.82, 0.65, 0.82);
        const edgesGeo = new THREE.EdgesGeometry(boxGeo);

        (matrixData.boxes || []).forEach(b => {
            const posX = (b.col - (cols - 1) / 2) * 0.88;
            const posY = b.layer * 0.70 + 0.35 + palletH;
            const posZ = (b.depth - (rows - 1) / 2) * 0.88;

            let mat, edgeMat;
            if (b.is_hidden) {
                mat = new THREE.MeshPhysicalMaterial({
                    color: 0x0284c7,
                    roughness: 0.15,
                    transmission: 0.78,
                    opacity: 0.38,
                    transparent: true,
                    depthWrite: false
                });
                edgeMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.8 });
            } else {
                mat = new THREE.MeshStandardMaterial({ color: 0xcba06c, roughness: 0.75 });
                edgeMat = new THREE.LineBasicMaterial({ color: 0x6e471d });
            }

            const mesh = new THREE.Mesh(boxGeo, mat);
            mesh.position.set(posX, posY, posZ);
            const edge = new THREE.LineSegments(edgesGeo, edgeMat);
            edge.position.copy(mesh.position);
            wbThreeScene.add(edge);

            mesh.userData = {
                id: b.id,
                layer: b.layer,
                col: b.col,
                depth: b.depth,
                label: b.label || `Box #${b.id} (Layer ${b.layer + 1}, Col ${b.col + 1}, Row ${b.depth + 1})`,
                isHidden: b.is_hidden,
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
                        ${item.isHidden ? 'Inferred Hidden Unit' : 'Observed Surface Unit'}
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
        const totalBadge = document.getElementById('wbTotalBadge');
        const totalUnits = parseInt((totalBadge?.textContent || '0').replace(/[^0-9]/g, ''), 10) || 0;
        
        const palletPcsElem = document.getElementById('palletTotalPieces');
        const palletBundlesElem = document.getElementById('palletCountBundles');
        const unitsPerBundleElem = document.getElementById('palletUnitsPerBundle');
        const uPerB = parseInt(unitsPerBundleElem?.textContent || '10', 10) || 10;

        if (wbMode === 'bundles') {
            if (palletBundlesElem) palletBundlesElem.textContent = totalUnits;
            if (palletPcsElem) palletPcsElem.textContent = totalUnits * uPerB;
        } else {
            if (palletPcsElem) palletPcsElem.textContent = totalUnits;
            if (palletBundlesElem) palletBundlesElem.textContent = Math.max(1, Math.round(totalUnits / uPerB));
        }

        if (typeof showToast === 'function') {
            showToast(`Verified count (${totalUnits} ${wbMode === 'bundles' ? 'bundles' : 'pieces'}) applied to active pallet build session. Inventory balance remains protected until sealing.`, 'success');
        } else {
            alert(`Verified count applied to active pallet session.`);
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

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initUnifiedDropZone();
            initWbDropZone();
        });
    } else {
        initUnifiedDropZone();
        initWbDropZone();
    }

})();
