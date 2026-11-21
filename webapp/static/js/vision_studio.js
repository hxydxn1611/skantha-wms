/*
 * AI Vision tools (vision_studio_routes.py):
 *   - tabs on the AI Vision screen: Products | Counting Studio | Weight Check
 *   - Counting Studio: draw 1-3 example boxes (or type words), YOLOE counts the rest;
 *     tap a marker to remove it, tap empty space to add one; save an example per product
 *   - Weight Check: pieces = (loaded - empty) / weight of one piece, compared with the camera
 *   - Photo finder: product photos from Pixabay (/ Pexels) and Openverse, pick several,
 *     "Show 5 more" never repeats; used by the product dialog and the product photo window
 */
(function () {
    'use strict';

    const h = (v) => (window.__h ? window.__h(v) : String(v == null ? '' : v).replace(/[&<>"'`]/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' }[c])));
    const $ = (id) => document.getElementById(id);
    const can = (k) => (typeof window.hasPerm === 'function' ? window.hasPerm(k) : true);
    const toast = (m, k) => (window.warlogToast ? window.warlogToast(m, k) : alert(m));
    const MAX_SIDE = 1600;

    // ================================================================== tabs
    let avTab = 'products';
    // one-line "what is this for" under the tabs
    const ABOUT = {
        products: {
            icon: 'fa-boxes-packing', color: 't-violet', title: 'Your product list',
            text: 'Every product the warehouse handles: name, unit, pieces per bundle and photos. Palletization, Inventory and AI counting all read from here.',
            tips: [['fa-plus', 'Add SKU', 'one product at a time'], ['fa-file-excel', 'Upload Excel', 'many at once (download the Template first)'],
                   ['fa-images', 'Bulk Image Mapping', 'photos named by SKU code'], ['fa-globe', 'Images / Find photos online', 'pick product photos from the internet']],
        },
        studio: {
            icon: 'fa-bullseye', color: 't-blue', title: 'Count items in a photo, no training needed',
            text: 'Draw a box around one item (or type what it is) and the AI finds all the others. Tap to correct, then save the example so the next count is one click.',
            tips: [['fa-image', 'Photo', 'upload or take a picture'], ['fa-vector-square', 'Draw example', 'box 1–3 items'],
                   ['fa-bolt', 'Count', 'see every item numbered'], ['fa-bookmark', 'Save as example', 'reuse it for this product']],
        },
        weight: {
            icon: 'fa-scale-balanced', color: 't-teal', title: 'Count without a camera',
            text: 'Weigh the loaded pallet, take away the empty pallet, divide by one piece’s weight. Use it to double-check a camera count or when no photo is possible.',
            tips: [['fa-box', 'Product', 'fills in one piece’s weight'], ['fa-weight-hanging', 'Weights', 'scale reading and empty pallet'],
                   ['fa-scale-balanced', 'Compare', 'with the camera count']],
        },
    };
    function renderAbout(name) {
        const el = $('avAbout');
        const a = ABOUT[name];
        if (!el || !a) return;
        el.innerHTML = `<span class="uac-tab-icon ${a.color} av-about-icon"><i class="fas ${a.icon}"></i></span>
            <div class="av-about-body"><div class="av-about-title">${h(a.title)}</div><div class="av-about-text">${h(a.text)}</div>
            <div class="av-about-tips">${a.tips.map(t => `<span><i class="fas ${t[0]}"></i><b>${h(t[1])}</b> ${h(t[2])}</span>`).join('')}</div></div>`;
    }

    function avShowTab(name) {
        avTab = name;
        renderAbout(name);
        document.querySelectorAll('#avTabs .uac-tab').forEach(b => b.classList.toggle('is-active', b.dataset.av === name));
        document.querySelectorAll('#ai-vision-view .av-products').forEach(el => { el.style.display = name === 'products' ? '' : 'none'; });
        document.querySelectorAll('#ai-vision-view .av-pane').forEach(el => { el.style.display = el.dataset.avpane === name ? '' : 'none'; });
        if (name === 'studio') studioOpen();
        if (name === 'weight') weightOpen();
        try { sessionStorage.setItem('warlog_av_tab', name); } catch (e) {}
    }
    window.avShowTab = avShowTab;
    window.__csItems = () => S.items.filter(i => !i.removed).concat(S.added);   // used by the UI check script

    // ================================================================== products (shared by studio + weight)
    let skus = null;
    async function loadSkus(force) {
        if (skus && !force) return skus;
        const all = [];
        try {
            for (let page = 1; page <= 10; page++) {
                const r = await fetch(`/api/sku_master?limit=100&page=${page}&status=Active`);
                const b = await r.json();
                const items = (b.data && b.data.items) || [];
                all.push(...items);
                if (items.length < 100) break;
            }
        } catch (e) { /* keep what we have */ }
        skus = all;
        return skus;
    }
    function fillSkuSelect(sel, first) {
        if (!sel || !skus) return;
        const keep = sel.value;
        sel.innerHTML = `<option value="">${h(first)}</option>` + skus.map(s =>
            `<option value="${h(s.sku_id)}">${h(s.name || s.sku_id)} · ${h(s.sku_id)}</option>`).join('');
        if (keep && skus.some(s => s.sku_id === keep)) sel.value = keep;
    }
    const skuById = (id) => (skus || []).find(s => s.sku_id === id);

    // ================================================================== Counting Studio
    const S = {
        img: null,           // working canvas (≤1600 px) of the photo
        w: 0, h: 0,
        boxes: [],           // example boxes [x1,y1,x2,y2] in working pixels
        autoBoxes: [],       // examples the word search picked by itself
        items: [],           // AI markers {cx,cy,x1..y2,conf,removed}
        added: [],           // manual markers {cx,cy}
        mode: 'example',
        drawing: false, drag: null,
        exampleId: null,     // saved example in use
        result: null,
        ready: false,
    };
    let studioWired = false, status = null;

    async function studioOpen() {
        if (!studioWired) wireStudio();
        await loadSkus();
        fillSkuSelect($('csSku'), 'Any item (no product)');
        if (!status) {
            try {
                const r = await fetch('/api/vision/studio/status');
                status = await r.json();
            } catch (e) { status = null; }
            renderEngine();
        }
        draw();
    }

    function renderEngine() {
        const el = $('csEngine');
        if (!el) return;
        if (!status || !status.success) { el.innerHTML = ''; return; }
        el.innerHTML = `<i class="fas fa-microchip"></i> YOLOE · runs on this ${h(status.device)}${status.gpu_name ? ' (' + h(status.gpu_name) + ')' : ''} · no training`
            + (status.model_ready ? '' : ' · <b class="c-danger">model missing</b>');
        const note = $('csTextNote');
        if (note) {
            note.hidden = !!status.text_ready;
            note.innerHTML = '<i class="fas fa-hourglass-half"></i> Word search is still being set up on this PC. Use <b>Show an example</b> meanwhile.';
        }
    }

    function hint(html) { const el = $('csHint'); if (el) el.querySelector('span').innerHTML = html; }

    function setMode(m) {
        S.mode = m;
        document.querySelectorAll('.cs-seg button').forEach(b => b.classList.toggle('is-on', b.dataset.mode === m));
        document.querySelectorAll('.cs-mode').forEach(el => { el.hidden = el.dataset.csmode !== m; });
        setDrawing(m === 'example' && !!S.img && !S.result && !S.exampleId);
        draw();
        refreshUi();
    }

    function setDrawing(on) {
        S.drawing = !!on;
        $('csDrawBtn')?.classList.toggle('is-on', S.drawing);
        const c = $('csCanvas');
        if (c) c.style.cursor = S.drawing ? 'crosshair' : 'pointer';
        refreshUi();
    }

    function refreshUi() {
        const n = S.boxes.length;
        if ($('csBoxCount')) $('csBoxCount').textContent = S.exampleId ? 'Using the saved example' : `${n} example${n === 1 ? '' : 's'} drawn`;
        const ready = !!S.img && (S.mode === 'text' ? !!($('csPrompt')?.value.trim()) : (n > 0 || !!S.exampleId));
        if ($('csCountBtn')) $('csCountBtn').disabled = !ready;
        if ($('csUndoBtn')) $('csUndoBtn').disabled = !n;
        if ($('csClearBtn')) $('csClearBtn').disabled = !S.img;
        if ($('csDrawBtn')) $('csDrawBtn').disabled = !S.img || S.mode !== 'example';
        if ($('csDownloadBtn')) $('csDownloadBtn').disabled = !S.result;
        const save = $('csSaveExample');
        if (save) save.disabled = !($('csSku')?.value) || !n;
        if (!S.img) hint('Add a photo to begin.');
        else if (S.result) hint('<b>Check the markers.</b> Tap a marker to remove it, tap an empty spot to add one.');
        else if (S.mode === 'text') hint('Type what to look for (e.g. <b>steel pipe end</b>), then press <b>Count</b>.');
        else if (S.exampleId) hint('Using the saved example for this product. Press <b>Count</b>.');
        else if (!n) hint('<b>Draw a box</b> around one item: press and drag on the photo.');
        else hint(`Good. Add ${n < 3 ? '1–' + (3 - n) + ' more for better results, or ' : ''}press <b>Count</b>.`);
    }

    function total() {
        return S.items.filter(i => !i.removed).length + S.added.length;
    }

    function showResult() {
        const box = $('csResult');
        if (!box) return;
        box.hidden = !S.result;
        if (!S.result) return;
        const removed = S.items.filter(i => i.removed).length;
        $('csTotal').textContent = total().toLocaleString();
        const meta = [];
        meta.push(`AI found ${S.items.length}`);
        if (S.autoBoxes.length) meta.push(`from ${S.autoBoxes.length} sure match${S.autoBoxes.length === 1 ? '' : 'es'} of the words`);
        if (removed) meta.push(`you removed ${removed}`);
        if (S.added.length) meta.push(`you added ${S.added.length}`);
        meta.push(`${(S.result.ms / 1000).toFixed(1)} s`);
        $('csMeta').innerHTML = meta.map(m => `<span>${h(m)}</span>`).join('');
        refreshUi();
    }

    // ------------------------------------------------------------------ photo in
    function loadImageFile(file) {
        if (!file || !/^image\//.test(file.type || 'image/')) return toast('That file is not a photo.', 'error');
        const url = URL.createObjectURL(file);
        loadImageUrl(url, () => URL.revokeObjectURL(url));
    }
    function loadImageUrl(url, done) {
        const im = new Image();
        im.onload = () => {
            const s = Math.min(1, MAX_SIDE / Math.max(im.naturalWidth, im.naturalHeight));
            const c = document.createElement('canvas');
            c.width = Math.round(im.naturalWidth * s);
            c.height = Math.round(im.naturalHeight * s);
            c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
            S.img = c; S.w = c.width; S.h = c.height;
            S.boxes = []; S.autoBoxes = []; S.items = []; S.added = []; S.result = null;
            $('csCanvas').hidden = false;
            $('csDrop').hidden = true;
            showResult();
            setMode(S.mode);
            draw();
            if (done) done();
        };
        im.onerror = () => { toast('That photo could not be opened.', 'error'); if (done) done(); };
        im.src = url;
    }

    // ------------------------------------------------------------------ canvas
    function markerRadius() {
        const src = S.items.length ? S.items : S.boxes.map(b => ({ x1: b[0], y1: b[1], x2: b[2], y2: b[3] }));
        if (!src.length) return Math.max(8, S.w / 90);
        const sizes = src.map(i => Math.min(i.x2 - i.x1, i.y2 - i.y1)).sort((a, b) => a - b);
        const med = sizes[Math.floor(sizes.length / 2)];
        return Math.max(6, Math.min(22, med * 0.32));
    }

    function draw() {
        const c = $('csCanvas');
        if (!c || !S.img) return;
        c.width = S.w; c.height = S.h;
        const g = c.getContext('2d');
        g.drawImage(S.img, 0, 0);
        const scale = S.w / Math.max(1, c.clientWidth || S.w);
        // examples
        g.lineWidth = Math.max(2, 2.5 * scale);
        g.setLineDash([8 * scale, 5 * scale]);
        g.strokeStyle = '#d946ef';
        g.fillStyle = 'rgba(217,70,239,0.12)';
        if (S.mode === 'example') S.boxes.forEach(b => { g.fillRect(b[0], b[1], b[2] - b[0], b[3] - b[1]); g.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]); });
        g.strokeStyle = '#6366f1';
        S.autoBoxes.forEach(b => g.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]));
        g.strokeStyle = '#d946ef';
        if (S.drag) {
            const d = S.drag;
            g.strokeRect(Math.min(d.x0, d.x1), Math.min(d.y0, d.y1), Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0));
        }
        g.setLineDash([]);
        // markers
        const r = markerRadius();
        const font = Math.round(r * 0.95);
        let n = 0;
        const drawMarker = (x, y, color, label) => {
            g.beginPath();
            g.arc(x, y, r, 0, Math.PI * 2);
            g.fillStyle = color; g.fill();
            g.lineWidth = Math.max(1.5, r * 0.18); g.strokeStyle = '#fff'; g.stroke();
            if (r >= 9) {
                g.fillStyle = '#fff'; g.font = `700 ${font}px Inter, system-ui, sans-serif`;
                g.textAlign = 'center'; g.textBaseline = 'middle';
                g.fillText(label, x, y + 0.5);
            }
        };
        S.items.forEach(i => { if (!i.removed) drawMarker(i.cx, i.cy, 'rgba(13,148,136,0.92)', String(++n)); });
        S.added.forEach(a => drawMarker(a.cx, a.cy, 'rgba(245,158,11,0.95)', String(++n)));
        S.items.forEach(i => {
            if (!i.removed) return;
            g.strokeStyle = 'rgba(239,68,68,0.9)'; g.lineWidth = Math.max(2, r * 0.2);
            g.beginPath(); g.moveTo(i.cx - r * 0.6, i.cy - r * 0.6); g.lineTo(i.cx + r * 0.6, i.cy + r * 0.6);
            g.moveTo(i.cx + r * 0.6, i.cy - r * 0.6); g.lineTo(i.cx - r * 0.6, i.cy + r * 0.6); g.stroke();
        });
    }

    function pt(e) {
        const c = $('csCanvas');
        const rect = c.getBoundingClientRect();
        const p = e.touches ? e.touches[0] : e;
        return { x: (p.clientX - rect.left) * (S.w / rect.width), y: (p.clientY - rect.top) * (S.h / rect.height) };
    }

    function onDown(e) {
        if (!S.img) return;
        const p = pt(e);
        if (S.drawing) {
            S.drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
            e.preventDefault();
            return;
        }
        if (!S.result) return;
        // edit markers: remove the nearest one under the finger, or add one
        const r = markerRadius() * 1.25;
        let best = null, bd = Infinity;
        S.added.forEach((a, idx) => { const d = Math.hypot(a.cx - p.x, a.cy - p.y); if (d < bd) { bd = d; best = { kind: 'added', idx }; } });
        S.items.forEach((i, idx) => { const d = Math.hypot(i.cx - p.x, i.cy - p.y); if (d < bd) { bd = d; best = { kind: 'item', idx }; } });
        if (best && bd <= r) {
            if (best.kind === 'added') S.added.splice(best.idx, 1);
            else S.items[best.idx].removed = !S.items[best.idx].removed;
        } else {
            S.added.push({ cx: p.x, cy: p.y });
        }
        draw(); showResult();
    }
    function onMove(e) {
        if (!S.drag) return;
        const p = pt(e);
        S.drag.x1 = p.x; S.drag.y1 = p.y;
        draw();
        e.preventDefault();
    }
    function onUp() {
        if (!S.drag) return;
        const d = S.drag;
        S.drag = null;
        const b = [Math.min(d.x0, d.x1), Math.min(d.y0, d.y1), Math.max(d.x0, d.x1), Math.max(d.y0, d.y1)];
        if (b[2] - b[0] >= 6 && b[3] - b[1] >= 6) {
            if (S.boxes.length >= 10) S.boxes.shift();
            S.boxes.push(b.map(v => Math.round(v)));
            S.exampleId = null;
            document.querySelectorAll('.cs-ex').forEach(x => x.classList.remove('is-on'));
        }
        draw(); refreshUi();
    }

    // ------------------------------------------------------------------ count
    function sensLabel(v) {
        return v < 25 ? 'Strict' : v < 45 ? 'Careful' : v < 60 ? 'Balanced' : v < 80 ? 'Generous' : 'Find everything';
    }

    async function doCount() {
        if (!S.img) return;
        const btn = $('csCountBtn');
        btn.disabled = true;
        $('csBusy').hidden = false;
        $('csBusyText').textContent = S.mode === 'text' ? 'Looking for “' + ($('csPrompt').value.trim()) + '”…' : 'Finding items like your example…';
        try {
            const blob = await new Promise(res => S.img.toBlob(res, 'image/jpeg', 0.9));
            const fd = new FormData();
            fd.append('image', blob, 'photo.jpg');
            fd.append('mode', S.mode);
            fd.append('sensitivity', String(($('csSens').value | 0) / 100));
            fd.append('detail', $('csDetail').value);
            if (S.mode === 'text') fd.append('prompts', $('csPrompt').value);
            else {
                fd.append('boxes', JSON.stringify(S.boxes));
                fd.append('similar_size', $('csSimilar').checked ? '1' : '0');
                if (S.exampleId && !S.boxes.length) fd.append('example_id', String(S.exampleId));
            }
            const r = await fetch('/api/vision/studio/count', { method: 'POST', body: fd });
            const b = await r.json().catch(() => ({}));
            if (!r.ok || !b.success) throw new Error(b.error || 'Counting failed.');
            S.result = b;
            S.items = (b.items || []).map(i => Object.assign({}, i, { removed: false }));
            S.autoBoxes = (b.auto_examples || []).map(x => x.map(Number));
            S.added = [];
            setDrawing(false);
            draw(); showResult();
            if (!S.items.length) toast('Nothing found. Try “Find more” sensitivity, or draw a tighter example box.', 'warning');
        } catch (e) {
            toast(e.message || 'Counting failed.', 'error');
        } finally {
            $('csBusy').hidden = true;
            refreshUi();
        }
    }

    // ------------------------------------------------------------------ saved examples
    async function loadExamples() {
        const box = $('csExamples');
        const sku = $('csSku').value;
        S.exampleId = null;
        if (!box) return;
        if (!sku) { box.innerHTML = ''; refreshUi(); return; }
        box.innerHTML = '<div class="uac-muted">Looking for saved examples…</div>';
        try {
            const r = await fetch('/api/vision/studio/examples?sku_id=' + encodeURIComponent(sku));
            const b = await r.json();
            const ex = (b.examples || []);
            const s = skuById(sku);
            if (!ex.length) {
                box.innerHTML = `<div class="cs-note"><i class="fas fa-bookmark"></i> No saved example for ${h(s ? s.name : sku)} yet. Draw one, count, then <b>Save as example</b>, and next time you won't need to draw.</div>`;
            } else {
                box.innerHTML = `<div class="cs-ex-head">Saved examples, tap one to use it</div><div class="cs-ex-list">` + ex.map(e => `
                    <button type="button" class="cs-ex" data-id="${Number(e.id)}" title="${h(e.name || 'Example')} · by ${h(e.created_by || '')}">
                        <img src="${h(e.image_path)}" alt=""><span>${h(e.name || ('Example #' + e.id))}</span>
                        ${can('sku.edit') ? `<i class="fas fa-xmark cs-ex-del" data-del="${Number(e.id)}" title="Remove"></i>` : ''}
                    </button>`).join('') + '</div>';
                box.querySelectorAll('.cs-ex').forEach(el => el.addEventListener('click', (ev) => {
                    const del = ev.target.closest('[data-del]');
                    if (del) { ev.stopPropagation(); return removeExample(Number(del.dataset.del)); }
                    const id = Number(el.dataset.id);
                    const on = S.exampleId !== id;
                    box.querySelectorAll('.cs-ex').forEach(x => x.classList.remove('is-on'));
                    S.exampleId = on ? id : null;
                    if (on) { el.classList.add('is-on'); S.boxes = []; setMode('example'); setDrawing(false); }
                    draw(); refreshUi();
                }));
            }
        } catch (e) { box.innerHTML = ''; }
        refreshUi();
        // suggestions for word search from the product
        const chips = $('csPromptChips');
        if (chips) {
            const s = skuById(sku);
            const base = s ? String(s.name || '').replace(/\(.*?\)/g, '').trim() : '';
            const list = [base && base + ' end', base].filter(Boolean).concat(['steel pipe end', 'wooden plank end', 'glass sheet edge', 'carton box']);
            chips.innerHTML = [...new Set(list)].slice(0, 5).map(t => `<button type="button" class="cs-chip cs-chip-btn">${h(t)}</button>`).join('');
            chips.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { $('csPrompt').value = b.textContent; refreshUi(); }));
        }
    }

    async function saveExample() {
        const sku = $('csSku').value;
        if (!sku) return toast('Choose the product first (step 1).', 'warning');
        if (!S.boxes.length) return toast('Draw at least one example box first.', 'warning');
        const s = skuById(sku);
        const name = prompt('Name this example (optional):', s ? (s.name + ' – front view') : '');
        if (name === null) return;
        const blob = await new Promise(res => S.img.toBlob(res, 'image/jpeg', 0.9));
        const fd = new FormData();
        fd.append('image', blob, 'example.jpg');
        fd.append('sku_id', sku);
        fd.append('boxes', JSON.stringify(S.boxes));
        fd.append('name', name || '');
        const r = await fetch('/api/vision/studio/examples', { method: 'POST', body: fd });
        const b = await r.json().catch(() => ({}));
        if (!r.ok || !b.success) return toast(b.error || 'Could not save the example.', 'error');
        toast(b.message || 'Example saved.', 'success');
        loadExamples();
    }

    async function removeExample(id) {
        if (!confirm('Remove this saved example?')) return;
        const r = await fetch('/api/vision/studio/examples/' + id, { method: 'DELETE' });
        const b = await r.json().catch(() => ({}));
        if (!r.ok || !b.success) return toast(b.error || 'Could not remove it.', 'error');
        toast('Example removed.', 'success');
        loadExamples();
    }

    function wireStudio() {
        studioWired = true;
        const c = $('csCanvas');
        c.addEventListener('mousedown', onDown);
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
        c.addEventListener('touchstart', onDown, { passive: false });
        c.addEventListener('touchmove', onMove, { passive: false });
        c.addEventListener('touchend', onUp);
        window.addEventListener('resize', () => { if (avTab === 'studio') draw(); });
        $('csFile').addEventListener('change', e => { loadImageFile(e.target.files[0]); e.target.value = ''; });
        $('csCamera').addEventListener('change', e => { loadImageFile(e.target.files[0]); e.target.value = ''; });
        const stage = $('csStage');
        stage.addEventListener('dragover', e => { e.preventDefault(); stage.classList.add('is-drag'); });
        stage.addEventListener('dragleave', () => stage.classList.remove('is-drag'));
        stage.addEventListener('drop', e => { e.preventDefault(); stage.classList.remove('is-drag'); loadImageFile(e.dataTransfer.files[0]); });
        $('csSampleBtn').addEventListener('click', () => loadImageUrl('/static/samples/sample_planks_cc0.jpg'));
        $('csDrawBtn').addEventListener('click', () => setDrawing(!S.drawing));
        $('csUndoBtn').addEventListener('click', () => { S.boxes.pop(); draw(); refreshUi(); });
        $('csClearBtn').addEventListener('click', () => {
            S.boxes = []; S.autoBoxes = []; S.items = []; S.added = []; S.result = null; S.exampleId = null;
            document.querySelectorAll('.cs-ex').forEach(x => x.classList.remove('is-on'));
            showResult(); setMode(S.mode); draw();
        });
        $('csDownloadBtn').addEventListener('click', () => {
            const a = document.createElement('a');
            a.href = $('csCanvas').toDataURL('image/jpeg', 0.9);
            a.download = `warlog_count_${total()}_${new Date().toISOString().slice(0, 10)}.jpg`;
            a.click();
        });
        document.querySelectorAll('.cs-seg button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
        $('csPrompt').addEventListener('input', refreshUi);
        $('csPrompt').addEventListener('keydown', e => { if (e.key === 'Enter' && !$('csCountBtn').disabled) doCount(); });
        $('csSens').addEventListener('input', () => { $('csSensLabel').textContent = sensLabel($('csSens').value | 0); });
        $('csSku').addEventListener('change', loadExamples);
        $('csCountBtn').addEventListener('click', doCount);
        $('csSaveExample').addEventListener('click', saveExample);
        $('csToWeight').addEventListener('click', () => {
            avShowTab('weight');
            $('wcCam').value = total();
            if ($('csSku').value) { $('wcSku').value = $('csSku').value; wcProduct(); }
            wcCalc();
        });
        refreshUi();
    }

    // ================================================================== Weight Check
    let weightWired = false;
    async function weightOpen() {
        await loadSkus();
        fillSkuSelect($('wcSku'), 'Choose a product…');
        if (weightWired) return;
        weightWired = true;
        $('wcSku').addEventListener('change', () => { wcProduct(); wcCalc(); });
        ['wcUnit', 'wcGross', 'wcTare', 'wcCam'].forEach(id => $(id).addEventListener('input', wcCalc));
    }
    function wcProduct() {
        const s = skuById($('wcSku').value);
        const w = s ? Number(s.unit_weight) || 0 : 0;
        $('wcUnit').value = w ? w : '';
        $('wcUnitHint').textContent = s ? (w ? `From the product: ${w} kg per ${String(s.uom || 'piece').toLowerCase()}.`
            : 'This product has no weight per piece yet. Type it here (and add it to the product).') : 'Taken from the product; you can change it here.';
    }
    function wcCalc() {
        const out = $('wcOut');
        const unit = parseFloat($('wcUnit').value), gross = parseFloat($('wcGross').value);
        const tare = parseFloat($('wcTare').value) || 0, cam = $('wcCam').value === '' ? null : parseInt($('wcCam').value, 10);
        const s = skuById($('wcSku').value);
        const uom = s ? String(s.uom || 'pcs').toLowerCase() : 'pcs';
        if (!(unit > 0) || !(gross > 0)) {
            out.innerHTML = `<div class="wc-empty"><span class="inv-empty-icon"><i class="fas fa-scale-balanced"></i></span>
                <div class="inv-empty-title">Enter the weights</div><div class="uac-muted">${!(unit > 0) ? 'Weight of one piece is needed.' : 'Loaded pallet weight is needed.'}</div></div>`;
            return;
        }
        if (tare >= gross) { out.innerHTML = '<div class="wc-empty"><div class="inv-empty-title c-danger">The empty weight is more than the loaded weight.</div></div>'; return; }
        const exact = (gross - tare) / unit;
        const pieces = Math.round(exact);
        const off = Math.abs(exact - pieces);
        let verdict = '';
        if (cam !== null && !isNaN(cam)) {
            const diff = cam - pieces;
            const ok = Math.abs(diff) <= Math.max(1, Math.round(pieces * 0.01));
            verdict = ok
                ? `<div class="wc-verdict ok"><i class="fas fa-circle-check"></i><div><b>Camera and weight agree.</b><br>Camera ${cam} · weight ${pieces}</div></div>`
                : `<div class="wc-verdict warn"><i class="fas fa-triangle-exclamation"></i><div><b>${Math.abs(diff)} ${diff > 0 ? 'more' : 'fewer'} by camera than by weight.</b><br>Camera ${cam} · weight ${pieces}. Recount, or check the weight per piece and the empty weight.</div></div>`;
        }
        out.innerHTML = `<div class="uac-stat-label">Expected by weight</div>
            <div class="wc-big">${pieces.toLocaleString()} <span>${h(uom)}</span></div>
            <div class="wc-math">(${gross.toLocaleString()} − ${tare.toLocaleString()}) ÷ ${unit} = ${exact.toFixed(2)}</div>
            ${off > 0.25 ? '<div class="cs-note"><i class="fas fa-circle-info"></i> The weights don\'t divide evenly. The scale reading or the weight per piece may be a little off.</div>' : ''}
            ${verdict}`;
    }

    // ================================================================== Photo finder
    const PF = { query: '', seen: [], page: 1, items: [], picked: new Map(), onDone: null, busy: false };

    function openPhotoFinder(opts) {
        PF.query = (opts && opts.query || '').trim();
        PF.seen = []; PF.page = 1; PF.items = []; PF.picked = new Map(); PF.onDone = opts && opts.onDone;
        let wrap = $('pfModal');
        if (wrap) wrap.remove();
        wrap = document.createElement('div');
        wrap.id = 'pfModal';
        wrap.className = 'uac-modal-backdrop pf-backdrop';
        wrap.innerHTML = `<div class="uac-modal pf-modal" role="dialog" aria-modal="true" aria-label="Find product photos">
            <div class="uac-modal-head"><div><h3><i class="fas fa-globe c-blue"></i> Find product photos</h3>
                <div class="uac-modal-sub">${h(opts && opts.subtitle || 'Pick the photos that look like your product. You can pick more than one.')}</div></div>
                <button class="uac-x" type="button" aria-label="Close">&times;</button></div>
            <div class="pf-search"><div class="uac-search"><i class="fas fa-magnifying-glass"></i>
                <input id="pfQ" class="uac-input" maxlength="100" value="${h(PF.query)}" placeholder="e.g. wooden plank"></div>
                <button type="button" class="uac-btn uac-btn-primary" id="pfGo"><i class="fas fa-magnifying-glass"></i> Search</button></div>
            <div class="pf-sources" id="pfSources"></div>
            <div class="pf-grid" id="pfGrid"></div>
            <div class="uac-modal-actions pf-foot">
                <div class="uac-foot-left"><span class="pf-picked" id="pfPicked">None picked</span></div>
                <button type="button" class="uac-btn" id="pfMore"><i class="fas fa-rotate"></i> Show 5 more</button>
                <button type="button" class="uac-btn uac-btn-primary" id="pfUse" disabled><i class="fas fa-check"></i> Use photos</button>
            </div></div>`;
        document.body.appendChild(wrap);
        const close = () => wrap.remove();
        wrap.addEventListener('click', e => { if (e.target === wrap) close(); });
        wrap.querySelector('.uac-x').onclick = close;
        $('pfGo').onclick = () => { PF.query = $('pfQ').value.trim(); PF.seen = []; PF.page = 1; PF.items = []; pfFetch(10, true); };
        $('pfQ').addEventListener('keydown', e => { if (e.key === 'Enter') $('pfGo').click(); });
        $('pfMore').onclick = () => pfFetch(5, false);
        $('pfUse').onclick = async () => {
            const chosen = [...PF.picked.values()];
            if (!chosen.length) return;
            $('pfUse').disabled = true;
            try { if (PF.onDone) await PF.onDone(chosen); close(); }
            finally { const b = $('pfUse'); if (b) b.disabled = false; }
        };
        if (PF.query.length >= 2) pfFetch(10, true);
        else { pfSkeleton(0); $('pfGrid').innerHTML = '<div class="pf-empty">Type what the product is, then press Search.</div>'; $('pfQ').focus(); }
    }
    window.openPhotoFinder = openPhotoFinder;

    function pfSkeleton(n) {
        const grid = $('pfGrid');
        for (let i = 0; i < n; i++) {
            const d = document.createElement('div');
            d.className = 'pf-tile pf-skel';
            grid.appendChild(d);
        }
    }

    async function pfFetch(count, fresh) {
        if (PF.busy || PF.query.length < 2) return;
        PF.busy = true;
        const grid = $('pfGrid');
        if (fresh) grid.innerHTML = '';
        grid.querySelectorAll('.pf-empty').forEach(x => x.remove());
        pfSkeleton(count);
        $('pfMore').disabled = true;
        try {
            const q = new URLSearchParams({ q: PF.query, count: String(count), page: String(PF.page), seen: PF.seen.join(',') });
            const r = await fetch('/api/vision/photos/search?' + q.toString());
            const b = await r.json().catch(() => ({}));
            grid.querySelectorAll('.pf-skel').forEach(x => x.remove());
            if (!r.ok || !b.success) throw new Error(b.error || 'Search failed.');
            PF.page = b.next_page || PF.page + 1;
            const src = b.sources || {};
            const names = [src.pixabay && 'Pixabay', src.pexels && 'Pexels', src.openverse && 'Openverse'].filter(Boolean);
            $('pfSources').innerHTML = 'Photos from ' + names.map(x => `<b>${h(x)}</b>`).join(' · ')
                + ' · free to use, even commercially · hover a photo for its licence'
                + (!src.pixabay ? ' <span class="pf-tip">Add the free Pixabay key for more product photos.</span>' : '');
            (b.photos || []).forEach(p => {
                PF.seen.push(p.id);
                PF.items.push(p);
                const t = document.createElement('button');
                t.type = 'button';
                t.className = 'pf-tile';
                t.dataset.id = p.id;
                t.title = [p.title, p.author && ('by ' + p.author), p.license].filter(Boolean).join(' · ');
                t.innerHTML = `<img loading="lazy" src="${h(p.thumb)}" alt="">
                    <span class="pf-check"><i class="fas fa-check"></i></span>
                    <span class="pf-credit">${h(p.provider)}${p.author ? ' · ' + h(p.author) : ''}</span>`;
                const img = t.querySelector('img');
                img.onload = () => t.classList.add('is-loaded');
                img.onerror = () => t.remove();
                t.addEventListener('click', () => {
                    if (PF.picked.has(p.id)) PF.picked.delete(p.id); else PF.picked.set(p.id, p);
                    t.classList.toggle('is-picked', PF.picked.has(p.id));
                    pfCount();
                });
                grid.appendChild(t);
            });
            if (!grid.children.length) grid.innerHTML = '<div class="pf-empty">No photos found. Try simpler words, e.g. “plank” instead of the product code.</div>';
            else if (!(b.photos || []).length) toast('No more new photos for these words. Try different words.', 'warning');
        } catch (e) {
            grid.querySelectorAll('.pf-skel').forEach(x => x.remove());
            if (!grid.children.length) grid.innerHTML = `<div class="pf-empty c-danger">${h(e.message)}</div>`;
            else toast(e.message, 'error');
        } finally {
            PF.busy = false;
            const m = $('pfMore'); if (m) m.disabled = false;
        }
    }

    function pfCount() {
        const n = PF.picked.size;
        $('pfPicked').innerHTML = n ? `<i class="fas fa-circle-check"></i> ${n} picked` : 'None picked';
        $('pfUse').disabled = !n;
        $('pfUse').innerHTML = `<i class="fas fa-check"></i> Use ${n || ''} photo${n === 1 ? '' : 's'}`;
    }

    async function importPhotos(skuId, chosen) {
        const r = await fetch('/api/vision/photos/import', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sku_id: skuId, items: chosen.map(p => ({ url: p.url, provider: p.provider, author: p.author, page_url: p.page_url, license: p.license })) }),
        });
        const b = await r.json().catch(() => ({}));
        if (!r.ok || !b.success) throw new Error(b.error || 'Could not save the photos.');
        if (b.errors && b.errors.length) toast(`${b.saved} saved, ${b.errors.length} could not be downloaded.`, 'warning');
        else toast(b.message || 'Photos added.', 'success');
        return b;
    }

    // ---- product dialog: pick now, saved after "Save Record"
    let pending = [];
    function renderPending() {
        const box = $('skuModalPhotoList');
        if (!box) return;
        box.innerHTML = pending.length ? pending.map((p, i) => `<div class="pf-thumb"><img src="${h(p.thumb)}" alt="">
            <button type="button" title="Remove" data-i="${i}">&times;</button></div>`).join('')
            + `<div class="pf-pending-note"><i class="fas fa-circle-info"></i> ${pending.length} photo${pending.length === 1 ? '' : 's'} will be added when you save.</div>` : '';
        box.querySelectorAll('button[data-i]').forEach(b => b.addEventListener('click', () => { pending.splice(Number(b.dataset.i), 1); renderPending(); }));
    }
    window.skuModalFindPhotos = function () {
        const name = ($('skuModalName')?.value || '').trim();
        const cat = ($('skuModalCategory')?.value || '').trim();
        openPhotoFinder({
            query: name || cat,
            subtitle: 'Pick the photos that look like this product. They are added when you save the product.',
            onDone: (chosen) => {
                const ids = new Set(pending.map(p => p.id));
                chosen.forEach(p => { if (!ids.has(p.id)) pending.push(p); });
                renderPending();
            },
        });
    };
    function wrapProductDialog() {
        ['openAddSkuModal', 'openEditSkuModal'].forEach(fn => {
            const orig = window[fn];
            if (typeof orig !== 'function' || orig.__pfWrapped) return;
            const w = function () { pending = []; renderPending(); return orig.apply(this, arguments); };
            w.__pfWrapped = true;
            window[fn] = w;
        });
        const submit = window.submitSkuForm;
        if (typeof submit === 'function' && !submit.__pfWrapped) {
            const w = async function () {
                const sku = ($('skuModalCode')?.value || '').trim();
                const out = await submit.apply(this, arguments);
                const closed = !$('modalAddSku')?.classList.contains('active');
                if (closed && sku && pending.length) {
                    const chosen = pending.slice();
                    pending = []; renderPending();
                    try { await importPhotos(sku, chosen); } catch (e) { toast(e.message, 'error'); }
                    if (typeof window.fetchSkuMaster === 'function') window.fetchSkuMaster();
                }
                return out;
            };
            w.__pfWrapped = true;
            window.submitSkuForm = w;
            // the form's submit handler calls submitSkuForm by name; nothing else to rewire
        }
        const openImgs = window.openSkuImagesModal;
        if (typeof openImgs === 'function' && !openImgs.__pfWrapped) {
            const w = function (skuId) { window.__pfImagesSku = skuId || null; return openImgs.apply(this, arguments); };
            w.__pfWrapped = true;
            window.openSkuImagesModal = w;
        }
    }

    // ---- product photo window: import straight away
    window.skuImagesFindPhotos = async function () {
        const sku = window.__pfImagesSku;
        if (!sku) return toast('Open the photos of one product first.', 'warning');
        let name = sku;
        try {
            const r = await fetch('/api/sku_master/' + encodeURIComponent(sku));
            const b = await r.json();
            if (b.success && b.data && b.data.name) name = b.data.name.replace(/\(.*?\)/g, '').trim();
        } catch (e) {}
        openPhotoFinder({
            query: name,
            subtitle: `Pick photos for ${sku}. They are saved to the product straight away.`,
            onDone: async (chosen) => {
                try { await importPhotos(sku, chosen); } catch (e) { toast(e.message, 'error'); return; }
                if (typeof window.openSkuImagesModal === 'function') window.openSkuImagesModal(sku);
                if (typeof window.fetchSkuMaster === 'function') window.fetchSkuMaster();
            },
        });
    };

    // ================================================================== start
    // hover descriptions for the product toolbar buttons
    function describeProductButtons() {
        const map = [
            ['openAddSkuModal()', 'Add one product by hand (you can also find photos online in the form)'],
            ['openExcelUploadModal()', 'Add or update many products at once from an Excel file'],
            ['openSkuImagesModal()', 'Upload many photos at once; each file name must contain the SKU code'],
        ];
        document.querySelectorAll('#ai-vision-view .av-products button[onclick]').forEach(b => {
            const hit = map.find(m => (b.getAttribute('onclick') || '').trim() === m[0]);
            if (hit && !b.title) b.title = hit[1];
        });
        document.querySelectorAll('#ai-vision-view .av-products a[href*="template"], #ai-vision-view .av-products button[onclick*="emplate"]')
            .forEach(b => { if (!b.title) b.title = 'Download an empty Excel file with the right columns'; });
    }

    function start() {
        wrapProductDialog();
        renderAbout('products');
        describeProductButtons();
        try {
            const t = sessionStorage.getItem('warlog_av_tab');
            if (t && t !== 'products' && document.querySelector(`#avTabs [data-av="${t}"]`)) {
                const view = $('ai-vision-view');
                // only once the AI Vision screen is shown
                const apply = () => { if (view && view.classList.contains('active')) avShowTab(t); };
                apply();
            }
        } catch (e) {}
        // (the product form's onsubmit calls window.submitSkuForm by name, so the wrapper above is used)
    }
    if (document.readyState === 'complete') start();
    else window.addEventListener('load', start);
})();
