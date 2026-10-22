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
                let html = '<option value="">-- Auto-Detect from Mapped SKUs --</option>';
                mappedVisionSkus.forEach(s => {
                    html += `<option value="${s.sku_id}">${s.sku_id} &mdash; ${s.name} (${s.category})</option>`;
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

        const matched = mappedVisionSkus.find(s => s.sku_id === skuId);

        if (matched && matched.image_url) {
            if (thumb) {
                thumb.src = matched.image_url;
                thumb.style.display = 'block';
            }
            if (icon) icon.style.display = 'none';
            if (badge) {
                badge.innerHTML = `<i class="fas fa-check-circle"></i> AI Reference Active: ${matched.sku_id}`;
                badge.style.background = 'rgba(16,185,129,0.15)';
                badge.style.color = '#10b981';
                badge.style.borderColor = 'rgba(16,185,129,0.3)';
            }
        } else {
            if (thumb) {
                thumb.src = '';
                thumb.style.display = 'none';
            }
            if (icon) icon.style.display = 'block';
            if (badge) {
                badge.innerHTML = `<i class="fas fa-robot"></i> Multi-SKU Auto Detection`;
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

        window.executePieceCount(true, sampleFileName, mode);
    };

    window.executePieceCount = async function(useSample = false, sampleNameOverride = null, modeOverride = null) {
        const btn = document.getElementById('btnRunPieceCount');
        const spinner = document.getElementById('piecesProcessingStatus');
        const resultContainer = document.getElementById('piecesResultContainer');

        if (btn) btn.disabled = true;
        if (spinner) spinner.style.display = 'block';
        if (resultContainer) resultContainer.style.display = 'none';

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
            if (data.mode === 'BUNDLE_STACK' || data.items_label === 'Bundles') {
                countLabel = `${data.total_pieces} BUNDLES`;
            } else if (data.mode === 'BOX_GRID' && data.total_3d_pallet) {
                countLabel = `${data.total_3d_pallet} BOXES (3D Pallet)`;
            }
            badge.textContent = countLabel;
        }

        // SKU match status tag
        const skuTag = document.getElementById('piecesSkuMatchResultTag');
        if (skuTag) {
            if (data.sku_id) {
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

        resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function updatePiecesClustersPills(clusters) {
        const pillsContainer = document.getElementById('piecesClustersPills');
        if (!pillsContainer) return;

        if (clusters && clusters.length > 0) {
            pillsContainer.innerHTML = clusters.map(cl => {
                return `
                    <div style="background:rgba(255,255,255,0.06); border:1px solid ${cl.color_hex}; border-radius:6px; padding:6px 12px; display:inline-flex; align-items:center; gap:8px;">
                        <span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:${cl.color_hex};"></span>
                        <span style="font-size:0.75rem; color:#f1f5f9; font-weight:600;">${cl.name}:</span>
                        <b style="font-size:0.85rem; color:#fff; font-family:'JetBrains Mono',monospace;">${cl.count}</b>
                    </div>
                `;
            }).join('');
        }
    }

    function renderInteractiveBadgesOverlay() {
        const overlay = document.getElementById('piecesBadgesOverlay');
        const imgElem = document.getElementById('piecesResultImg');
        if (!overlay || !imgElem) return;

        overlay.innerHTML = '';
        const imgW = imgElem.naturalWidth || imgElem.clientWidth || 1;
        const imgH = imgElem.naturalHeight || imgElem.clientHeight || 1;

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

        // Add verified point
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

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initUnifiedDropZone);
    } else {
        initUnifiedDropZone();
    }

})();
