/**
 * Multi-Angle 3D Volumetric Bundle Audit UI
 * Integrates 3-viewpoint perspective analysis, 3D voxel reconstruction,
 * and certified WMS inventory reconciliation.
 */

(function() {
    let latestAuditResult = null;

    window.openMultiAngleAuditModal = function() {
        const modal = document.getElementById('modalMultiAngleAudit');
        if (modal) {
            modal.style.display = 'flex';
        }
    };

    window.closeMultiAngleAuditModal = function() {
        const modal = document.getElementById('modalMultiAngleAudit');
        if (modal) {
            modal.style.display = 'none';
        }
    };

    window.previewAngleImage = function(slotIndex, input) {
        if (!input.files || !input.files[0]) return;
        const file = input.files[0];
        const reader = new FileReader();
        reader.onload = function(e) {
            const previewImg = document.getElementById(`anglePreview${slotIndex}`);
            const placeholder = document.getElementById(`anglePlaceholder${slotIndex}`);
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

    window.loadMultiAngleReferenceDemo = function() {
        // Sets preview placeholders to the reference test scenes
        const a1 = document.getElementById('anglePreview1');
        const a2 = document.getElementById('anglePreview2');
        const a3 = document.getElementById('anglePreview3');
        if (a1) { a1.src = '/static/test_scenes/sample_angle1_front.jpg'; a1.style.display = 'block'; }
        if (a2) { a2.src = '/static/test_scenes/sample_angle2_right.jpg'; a2.style.display = 'block'; }
        if (a3) { a3.src = '/static/test_scenes/sample_angle3_left.jpg'; a3.style.display = 'block'; }

        ['1', '2', '3'].forEach(id => {
            const pl = document.getElementById(`anglePlaceholder${id}`);
            if (pl) pl.style.display = 'none';
        });

        // Trigger analysis with sample
        window.executeMultiAngleCount(true);
    };

    window.executeMultiAngleCount = async function(useSample = false) {
        const btn = document.getElementById('btnRunMultiAngleCount');
        const statusBox = document.getElementById('auditProcessingStatus');
        const resultContainer = document.getElementById('auditResultContainer');

        if (btn) btn.disabled = true;
        if (statusBox) statusBox.style.display = 'block';
        if (resultContainer) resultContainer.style.display = 'none';

        try {
            const formData = new FormData();
            formData.append('sku_id', document.getElementById('auditSkuInput')?.value || 'AUTO-REBAR-32');
            formData.append('bin_location', document.getElementById('auditBinInput')?.value || 'A3');
            formData.append('request_id', document.getElementById('auditReqInput')?.value || '9504EA');
            formData.append('depth_multiplier', document.getElementById('auditDepthMultiplier')?.value || '3');

            if (useSample) {
                formData.append('use_sample', 'true');
            } else {
                const f1 = document.getElementById('fileAngle1')?.files[0];
                const f2 = document.getElementById('fileAngle2')?.files[0];
                const f3 = document.getElementById('fileAngle3')?.files[0];

                if (f1) formData.append('angle1', f1);
                if (f2) formData.append('angle2', f2);
                if (f3) formData.append('angle3', f3);

                if (!f1 && !f2 && !f3) {
                    // Fall back to sample reference if user clicked run without uploading files
                    formData.append('use_sample', 'true');
                }
            }

            const res = await fetch('/api/vision/multi-angle-count', {
                method: 'POST',
                body: formData
            });

            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Failed to compute multi-angle count');
            }

            latestAuditResult = data;
            renderAuditResults(data);

        } catch(err) {
            console.error('Multi-angle audit error:', err);
            alert(`Audit Error: ${err.message}`);
        } finally {
            if (btn) btn.disabled = false;
            if (statusBox) statusBox.style.display = 'none';
        }
    };

    function renderAuditResults(data) {
        const resultContainer = document.getElementById('auditResultContainer');
        if (!resultContainer) return;

        resultContainer.style.display = 'block';

        // Set Audit Sheet Image
        const imgElem = document.getElementById('auditBoardResultImg');
        if (imgElem) {
            imgElem.src = `${data.audit_image_url}?t=${Date.now()}`;
        }

        // Set Grand Total
        const totalElem = document.getElementById('auditTotalBundlesBadge');
        if (totalElem) {
            totalElem.textContent = `${data.total_bundles} BUNDLES`;
        }

        // Populate Table Rows
        const tbody = document.getElementById('auditStacksTableBody');
        if (tbody && data.stacks) {
            tbody.innerHTML = data.stacks.map(s => {
                const bgr = s.color_bgr || [50, 150, 250];
                const rgbStr = `rgb(${bgr[2]}, ${bgr[1]}, ${bgr[0]})`;
                return `
                    <tr>
                        <td style="display:flex; align-items:center; gap:8px;">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:2px; background:${rgbStr};"></span>
                            <b>Stack ${s.id}</b>
                            <span style="color:var(--text-muted); font-size:0.75rem;">(${s.name})</span>
                        </td>
                        <td style="text-align:center; font-weight:700;">${s.layers}</td>
                        <td style="text-align:center; font-family:'JetBrains Mono',monospace; color:#38bdf8;">${s.formula}</td>
                        <td style="text-align:right; font-weight:800; font-size:0.95rem; color:#10b981;">${s.bundles}</td>
                    </tr>
                `;
            }).join('');
        }

        // Scroll to results
        resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    window.syncAuditCountToPallet = async function() {
        if (!latestAuditResult) {
            alert('Please run a 3D audit first.');
            return;
        }

        const count = latestAuditResult.total_bundles;
        const confirmSync = confirm(`Reconcile Pallet with Certified Multi-Angle Count?\n\nVerified Count: ${count} Bundles\nThis will synchronize active inventory records.`);
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
                alert(`Success! Pallet ${data.pallet_id} reconciled with ${count} bundles (${data.total_pieces} pieces).`);
                closeMultiAngleAuditModal();
                if (typeof window.loadPallets === 'function') {
                    window.loadPallets();
                }
            } else {
                alert(`Sync Error: ${data.error || 'Failed to reconcile count'}`);
            }
        } catch(e) {
            console.error('Sync audit count error:', e);
            alert(`Error: ${e.message}`);
        }
    };

    window.openAuditImageFullscreen = function() {
        const imgElem = document.getElementById('auditBoardResultImg');
        if (!imgElem || !imgElem.src) return;
        window.open(imgElem.src, '_blank');
    };

})();
