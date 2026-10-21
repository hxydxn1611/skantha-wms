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

    // -------------------------------------------------------------------------
    // MODAL OPEN / CLOSE & MODE SWITCHING
    // -------------------------------------------------------------------------

    window.openVisionCountingModal = function(initialMode = 'pieces') {
        const modal = document.getElementById('modalVisionCounting');
        if (modal) {
            modal.style.display = 'flex';
            switchVisionCountingMode(initialMode);
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
        };
        reader.readAsDataURL(file);
    };

    window.loadSamplePiecesImage = function() {
        // Load the 229 pcs steel tube stack reference (Image 1)
        const previewImg = document.getElementById('piecesPreviewImg');
        const placeholder = document.getElementById('piecesPlaceholder');
        if (previewImg) {
            previewImg.src = '/static/test_scenes/sample_individual_pipes_229.jpg';
            previewImg.style.display = 'block';
        }
        if (placeholder) placeholder.style.display = 'none';

        // Auto execute count
        window.executePieceCount(true);
    };

    window.executePieceCount = async function(useSample = false) {
        const btn = document.getElementById('btnRunPieceCount');
        const spinner = document.getElementById('piecesProcessingStatus');
        const resultContainer = document.getElementById('piecesResultContainer');

        if (btn) btn.disabled = true;
        if (spinner) spinner.style.display = 'block';
        if (resultContainer) resultContainer.style.display = 'none';

        try {
            const formData = new FormData();
            const sens = document.getElementById('piecesSensitivitySlider')?.value || '0.5';
            const clust = document.getElementById('piecesClusterSelect')?.value || '4';
            
            formData.append('sensitivity', sens);
            formData.append('clusters', clust);

            if (useSample) {
                formData.append('use_sample', 'true');
                formData.append('sample_name', 'sample_individual_pipes_229.jpg');
            } else {
                const f = document.getElementById('filePiecesImage')?.files[0];
                if (f) {
                    formData.append('image', f);
                } else {
                    // Fall back to sample if no file uploaded
                    formData.append('use_sample', 'true');
                    formData.append('sample_name', 'sample_individual_pipes_229.jpg');
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

        // Total badge
        const badge = document.getElementById('piecesTotalBadge');
        if (badge) {
            badge.textContent = `${data.total_pieces} PCS`;
        }

        // Annotated Image URL
        const imgElem = document.getElementById('piecesResultImg');
        if (imgElem && data.annotated_image_url) {
            imgElem.src = `${data.annotated_image_url}?t=${Date.now()}`;
        }

        // Cluster breakdown pills
        const pillsContainer = document.getElementById('piecesClustersPills');
        if (pillsContainer && data.clusters) {
            pillsContainer.innerHTML = data.clusters.map(cl => {
                return `
                    <div style="background:rgba(255,255,255,0.06); border:1px solid ${cl.color_hex}; border-radius:6px; padding:6px 12px; display:inline-flex; align-items:center; gap:8px;">
                        <span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:${cl.color_hex};"></span>
                        <span style="font-size:0.75rem; color:#f1f5f9; font-weight:600;">${cl.name}:</span>
                        <b style="font-size:0.85rem; color:#fff; font-family:'JetBrains Mono',monospace;">${cl.count}</b>
                    </div>
                `;
            }).join('');
        }

        resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    window.syncPiecesCountToPallet = async function() {
        if (!latestPiecesResult) {
            alert('Please run piece count first.');
            return;
        }

        const count = latestPiecesResult.total_pieces;
        const confirmSync = confirm(`Reconcile Active Pallet with Verified Piece Count?\n\nDetected Total: ${count} Pieces\nThis will record piece inventory in WMS.`);
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
                alert(`Success! Reconciled with ${count} pieces.`);
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

            if (presetKey) {
                formData.append('preset_name', presetKey);
            } else {
                const f1 = document.getElementById('fileBundleAngle1')?.files[0];
                const f2 = document.getElementById('fileBundleAngle2')?.files[0];
                if (f1) formData.append('angle1', f1);
                if (f2) formData.append('angle2', f2);

                if (!f1 && !f2) {
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
            totalElem.textContent = `${data.total_bundles} BUNDLES`;
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

})();
