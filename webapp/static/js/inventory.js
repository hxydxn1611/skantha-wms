/*
 * Inventory section (menu: Inventory) + Master Data Hub > Inventory Master.
 *
 * One data source for both: GET /api/stock/overview. Changes go through
 * /api/stock/adjust | transfer | min-level, so both screens always show the same numbers
 * and every change lands in the stock history (GET /api/stock/movements).
 * Buttons are shown only to people who may use them; the server checks again.
 */
(function () {
    'use strict';

    const h = (v) => (window.__h ? window.__h(v) : String(v == null ? '' : v).replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
    const can = (k) => (typeof window.hasPerm === 'function' ? window.hasPerm(k) : true);
    const toast = (msg, kind) => (window.warlogToast ? window.warlogToast(msg, kind) : alert(msg));
    const $ = (id) => document.getElementById(id);
    const num = (n) => (Number(n) || 0).toLocaleString();

    let data = null;            // last /api/stock/overview answer
    let tab = 'stock';
    let histFilter = null;      // {inventory_id|sku_id|bin_id, label}
    let expanded = new Set();   // product rows opened in "By Product"
    let loading = null;

    const TYPE_STYLE = {
        adjust: 'warn', transfer_out: 'violet', transfer_in: 'violet', receive: 'ok', pick: 'blue',
        cycle_count: 'teal', count_sync: 'teal', vision_transfer: 'teal', removed: 'off', created: 'ok',
    };

    function readOnly() { return !!(data && data.read_only); }
    function canAdjust() { return !readOnly() && can('inventory.adjust'); }
    function canMove() { return !readOnly() && can('inventory.transfer'); }
    function canLevels() { return !readOnly() && can('inventory.levels.manage'); }

    function when(ts) {
        if (!ts) return '–';
        const s = String(ts);
        const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s.replace(' ', 'T') + 'Z');
        return isNaN(d) ? s : d.toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    }
    function dateOnly(ts) {
        if (!ts) return '–';
        const s = String(ts);
        return s.length >= 10 ? s.slice(0, 10) : s;
    }

    function expiryChip(line) {
        const d = line.days_to_expiry;
        if (d === null || d === undefined) return '<span class="uac-muted">–</span>';
        if (d < 0) return `<span class="uac-pill off">Expired ${h(dateOnly(line.expiry_date))}</span>`;
        if (d <= (data.thresholds || {}).expiry_days) return `<span class="uac-pill warn">${d} day${d === 1 ? '' : 's'} left</span>`;
        return `<span class="uac-muted">${h(dateOnly(line.expiry_date))}</span>`;
    }

    function lineIssues(line) {
        const p = (data.products || []).find(x => x.sku_id === line.sku_id);
        const exp = line.days_to_expiry !== null && line.days_to_expiry !== undefined
            && line.days_to_expiry <= (data.thresholds || {}).expiry_days;
        return !!(p && p.low) || exp;
    }

    // ------------------------------------------------------------------ load
    async function loadInventory() {
        if (loading) return loading;
        loading = (async () => {
            try {
                const res = await fetch('/api/stock/overview');
                const body = await res.json().catch(() => ({}));
                if (!res.ok || !body.success) throw new Error(body.error || 'Could not load stock.');
                data = body;
                renderAll();
                if (tab === 'history') loadHistory();
            } catch (e) {
                ['invStock', 'invProducts', 'invHistory'].forEach(id => { const el = $(id); if (el) el.innerHTML = `<div class="uac-empty uac-error">${h(e.message)}</div>`; });
            } finally {
                loading = null;
            }
        })();
        return loading;
    }

    function renderAll() {
        const s = data.summary || {};
        if ($('invStatQty')) $('invStatQty').textContent = num(s.total_qty);
        if ($('invStatProducts')) $('invStatProducts').textContent = num(s.products);
        if ($('invStatBins')) $('invStatBins').innerHTML = `${num(s.bins_used)}<span class="inv-of"> / ${num(s.bins_total)}</span>`;
        if ($('invStatAlerts')) $('invStatAlerts').textContent = num(s.alerts);
        setBadges(s.alerts || 0);
        if ($('invReadOnlyNote')) $('invReadOnlyNote').style.display = data.read_only ? 'flex' : 'none';
        fillSelect('invStockZone', uniq(data.lines.map(l => l.zone)), 'All zones');
        fillSelect('invStockCat', uniq(data.lines.map(l => l.category)), 'All categories');
        fillSelect('invBinZone', uniq(data.bins.map(b => b.zone)), 'All zones');
        renderStock();
        renderProducts();
        renderBins();
        renderAlerts();
    }

    function setBadges(n) {
        [['invAlertBadge'], ['nav-inventory-alerts']].forEach(([id]) => {
            const el = $(id);
            if (!el) return;
            el.textContent = n > 99 ? '99+' : String(n);
            el.style.display = n > 0 ? '' : 'none';
            el.classList.toggle('inv-badge-off', !(n > 0));
        });
    }

    function uniq(list) { return [...new Set(list.filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b))); }

    function fillSelect(id, values, first) {
        const sel = $(id);
        if (!sel) return;
        const keep = sel.value;
        sel.innerHTML = `<option value="">${h(first)}</option>` + values.map(v => `<option value="${h(v)}">${h(v)}</option>`).join('');
        if (values.includes(keep)) sel.value = keep;
    }

    function emptyBox(icon, title, text) {
        return `<div class="inv-empty"><span class="inv-empty-icon"><i class="fas ${icon}"></i></span>
            <div class="inv-empty-title">${h(title)}</div><div class="uac-muted">${h(text)}</div></div>`;
    }

    // ------------------------------------------------------------------ Stock
    function fillText(pct) {
        return pct > 100 ? `Over limit · ${pct}%` : `${pct}%`;
    }

    function lineActions(l, compact) {
        const out = [];
        if (canAdjust()) out.push(`<button class="uac-btn-sm" title="Adjust quantity" onclick="invAdjust(${Number(l.id)})"><i class="fas fa-pen"></i>${compact ? '' : ' Adjust'}</button>`);
        if (canMove() && (l.quantity || 0) > 0) out.push(`<button class="uac-btn-sm" title="Move to another bin" onclick="invMove(${Number(l.id)})"><i class="fas fa-right-left"></i>${compact ? '' : ' Move'}</button>`);
        out.push(`<button class="uac-btn-sm inv-btn-ghost" title="History of this line" onclick="invHistoryFor({inventory_id:${Number(l.id)}})"><i class="fas fa-clock-rotate-left"></i></button>`);
        return out.join('');
    }

    function renderStock() {
        const box = $('invStock');
        if (!box || !data) return;
        const q = ($('invStockQ')?.value || '').trim().toLowerCase();
        const zone = $('invStockZone')?.value || '';
        const cat = $('invStockCat')?.value || '';
        const issues = $('invStockIssues')?.checked;
        const rows = data.lines.filter(l =>
            (!q || [l.sku_name, l.sku_id, l.bin_id, l.batch_number, l.vendor].some(v => String(v || '').toLowerCase().includes(q)))
            && (!zone || l.zone === zone) && (!cat || l.category === cat) && (!issues || lineIssues(l)));
        if (!data.lines.length) {
            box.innerHTML = emptyBox('fa-box-open', 'No stock here yet',
                'Stock appears when goods are received at the dock (Inbound), counted into a bin, or posted from an AI count.');
            return;
        }
        if (!rows.length) { box.innerHTML = '<div class="uac-empty">Nothing matches these filters.</div>'; return; }
        const loc = data.all_locations;
        box.innerHTML = `<table class="uac-table inv-table"><thead><tr>
            <th>Product</th>${loc ? '<th>Location</th>' : ''}<th>Bin</th><th>Zone</th><th>Batch</th>
            <th class="inv-num">Quantity</th><th>Expiry</th><th>Received</th><th></th></tr></thead><tbody>
            ${rows.map(l => {
                const p = data.products.find(x => x.sku_id === l.sku_id);
                const low = p && p.low ? '<span class="uac-pill off" title="Product is below its minimum level">Low</span>' : '';
                return `<tr>
                <td><div class="uac-name">${h(l.sku_name || l.sku_id)} ${low}${l.is_demo ? ' <span class="uac-pill starter">demo</span>' : ''}</div>
                    <div class="uac-muted">${h(l.sku_id)}${l.category ? ' · ' + h(l.category) : ''}</div></td>
                ${loc ? `<td>${h(l.warehouse_name || '–')}</td>` : ''}
                <td><span class="inv-bin-tag">${h(l.bin_id || '–')}</span></td>
                <td>${h(l.zone || '–')}</td>
                <td>${h(l.batch_number || '–')}</td>
                <td class="inv-num"><span class="inv-qty">${num(l.quantity)}</span> <span class="uac-muted">${h(l.uom || '')}</span></td>
                <td>${expiryChip(l)}</td>
                <td class="uac-muted">${h(dateOnly(l.received_date))}</td>
                <td class="uac-actions">${lineActions(l)}</td></tr>`;
            }).join('')}</tbody></table>
            <div class="inv-foot uac-muted">${rows.length} of ${data.lines.length} stock line${data.lines.length === 1 ? '' : 's'}</div>`;
    }

    // ------------------------------------------------------------------ By Product
    function renderProducts() {
        const box = $('invProducts');
        if (!box || !data) return;
        const q = ($('invProdQ')?.value || '').trim().toLowerCase();
        const lowOnly = $('invProdLow')?.checked;
        const rows = data.products.filter(p =>
            (!q || [p.sku_name, p.sku_id, p.category].some(v => String(v || '').toLowerCase().includes(q))) && (!lowOnly || p.low));
        if (!data.products.length) { box.innerHTML = emptyBox('fa-tags', 'No products in stock', 'Products show up here once they have stock in a bin.'); return; }
        if (!rows.length) { box.innerHTML = '<div class="uac-empty">Nothing matches these filters.</div>'; return; }
        box.innerHTML = `<table class="uac-table inv-table"><thead><tr><th></th><th>Product</th><th class="inv-num">In stock</th>
            <th>Minimum</th><th>Status</th><th>Bins</th><th></th></tr></thead><tbody>
            ${rows.map(p => {
                const open = expanded.has(p.sku_id);
                const min = p.min_qty === null || p.min_qty === undefined ? '<span class="uac-muted">not set</span>' : num(p.min_qty);
                const pct = p.min_qty ? Math.min(100, Math.round(100 * p.quantity / p.min_qty)) : null;
                const status = p.low ? '<span class="uac-pill off">Below minimum</span>'
                    : (p.quantity <= 0 ? '<span class="uac-pill warn">Out of stock</span>' : '<span class="uac-pill ok">OK</span>');
                const sid = window.__js ? window.__js(p.sku_id) : h(JSON.stringify(String(p.sku_id)));
                const lines = open ? data.lines.filter(l => l.sku_id === p.sku_id) : [];
                return `<tr class="inv-prod-row${open ? ' is-open' : ''}" onclick="invToggleProduct(${sid})">
                    <td class="inv-caret"><i class="fas fa-chevron-${open ? 'down' : 'right'}"></i></td>
                    <td><div class="uac-name">${h(p.sku_name)}</div><div class="uac-muted">${h(p.sku_id)}${p.category ? ' · ' + h(p.category) : ''}</div></td>
                    <td class="inv-num"><span class="inv-qty">${num(p.quantity)}</span> <span class="uac-muted">${h(p.uom || '')}</span>
                        ${pct !== null ? `<div class="inv-mini-bar"><span class="${p.low ? 'is-low' : ''}" style="width:${pct}%"></span></div>` : ''}</td>
                    <td>${min}</td><td>${status}</td>
                    <td>${p.bins.length ? p.bins.map(b => `<span class="inv-bin-tag">${h(b)}</span>`).join(' ') : '<span class="uac-muted">–</span>'}</td>
                    <td class="uac-actions" onclick="event.stopPropagation()">
                        ${canLevels() ? `<button class="uac-btn-sm" onclick="invSetMin(${sid})"><i class="fas fa-sliders"></i> Minimum</button>` : ''}
                        <button class="uac-btn-sm inv-btn-ghost" title="History of this product" onclick="invHistoryFor({sku_id:${sid}})"><i class="fas fa-clock-rotate-left"></i></button></td>
                    </tr>${open ? `<tr class="inv-sub-row"><td></td><td colspan="6">${lines.length ? `<div class="inv-sub-list">${lines.map(l => `
                        <div class="inv-sub-item"><span class="inv-bin-tag">${h(l.bin_id)}</span>
                            <span class="uac-muted">${h(l.zone || '')}${l.batch_number ? ' · batch ' + h(l.batch_number) : ''}${data.all_locations && l.warehouse_name ? ' · ' + h(l.warehouse_name) : ''}</span>
                            <b class="inv-sub-qty">${num(l.quantity)}</b>
                            <span class="inv-sub-actions">${lineActions(l)}</span></div>`).join('')}</div>`
                        : '<span class="uac-muted">No stock in any bin.</span>'}</td></tr>` : ''}`;
            }).join('')}</tbody></table>`;
    }

    window.invToggleProduct = function (sku) {
        if (expanded.has(sku)) expanded.delete(sku); else expanded.add(sku);
        renderProducts();
    };

    // ------------------------------------------------------------------ By Bin
    function renderBins() {
        const box = $('invBins');
        if (!box || !data) return;
        const q = ($('invBinQ')?.value || '').trim().toLowerCase();
        const zone = $('invBinZone')?.value || '';
        const used = $('invBinUsed')?.checked;
        const rows = data.bins.filter(b => (!q || String(b.bin_id).toLowerCase().includes(q)) && (!zone || b.zone === zone) && (!used || b.quantity > 0));
        if (!data.bins.length) { box.innerHTML = emptyBox('fa-table-cells-large', 'No bins yet', 'Bins are set up in Master Data Hub > Bin Master.'); return; }
        if (!rows.length) { box.innerHTML = '<div class="uac-empty">Nothing matches these filters.</div>'; return; }
        const full = (data.thresholds || {}).bin_full_pct || 90;
        box.innerHTML = rows.map(b => {
            const lines = data.lines.filter(l => l.bin_id === b.bin_id && (l.quantity || 0) > 0);
            const lvl = b.fill_pct >= full ? 'is-full' : (b.fill_pct >= 70 ? 'is-high' : '');
            const bid = window.__js ? window.__js(b.bin_id) : h(JSON.stringify(String(b.bin_id)));
            return `<div class="inv-bin-card">
                <div class="inv-bin-head"><div><div class="inv-bin-name"><i class="fas fa-cube"></i> ${h(b.bin_id)}</div>
                    <div class="uac-muted">Zone ${h(b.zone || '–')}${data.all_locations && b.warehouse_name ? ' · ' + h(b.warehouse_name) : ''}${b.status && b.status !== 'Active' ? ' · ' + h(b.status) : ''}</div></div>
                    <span class="inv-fill-num ${lvl}">${fillText(b.fill_pct)}</span></div>
                <div class="inv-fill"><span class="${lvl}" style="width:${Math.min(100, b.fill_pct)}%"></span></div>
                <div class="inv-bin-lines">${lines.length ? lines.slice(0, 4).map(l => `<div class="inv-bin-line">
                    <span>${h(l.sku_name || l.sku_id)}</span><b>${num(l.quantity)}</b></div>`).join('')
                    + (lines.length > 4 ? `<div class="uac-muted">+ ${lines.length - 4} more</div>` : '')
                    : '<div class="uac-muted">Empty</div>'}</div>
                <div class="inv-bin-foot">
                    <button class="uac-btn-sm" onclick="invStockForBin(${bid})"><i class="fas fa-list"></i> Stock</button>
                    <button class="uac-btn-sm inv-btn-ghost" onclick="invHistoryFor({bin_id:${bid}})"><i class="fas fa-clock-rotate-left"></i> History</button>
                </div></div>`;
        }).join('');
    }

    window.invStockForBin = function (bin) {
        if ($('invStockQ')) $('invStockQ').value = bin;
        if ($('invStockZone')) $('invStockZone').value = '';
        if ($('invStockCat')) $('invStockCat').value = '';
        if ($('invStockIssues')) $('invStockIssues').checked = false;
        invShowTab('stock');
    };

    // ------------------------------------------------------------------ Alerts
    function renderAlerts() {
        const box = $('invAlerts');
        if (!box || !data) return;
        const a = data.alerts || { low: [], expiring: [], bins_full: [] };
        const group = (icon, cls, title, sub, items, render) => `<div class="glass-panel inv-alert-group">
            <div class="uac-pane-head"><div><div class="uac-pane-title"><span class="uac-tab-icon ${cls}"><i class="fas ${icon}"></i></span> ${h(title)}
                <span class="inv-count">${items.length}</span></div><div class="uac-muted">${h(sub)}</div></div></div>
            ${items.length ? `<div class="inv-alert-list">${items.map(render).join('')}</div>` : '<div class="inv-all-good"><i class="fas fa-circle-check"></i> All good</div>'}</div>`;
        const t = data.thresholds || {};
        box.innerHTML =
            group('fa-arrow-trend-down', 't-amber', 'Below minimum level', 'Products with less stock than their minimum. Set minimums in By Product.', a.low, p => `
                <div class="inv-alert-item"><div><div class="uac-name">${h(p.sku_name)}</div><div class="uac-muted">${h(p.sku_id)}</div></div>
                <div class="inv-alert-figure"><b class="c-danger">${num(p.quantity)}</b> <span class="uac-muted">of min ${num(p.min_qty)} ${h(p.uom || '')}</span></div></div>`)
            + group('fa-hourglass-half', 't-violet', `Expiring within ${t.expiry_days || 30} days`, 'Use or move these first.', a.expiring, l => `
                <div class="inv-alert-item"><div><div class="uac-name">${h(l.sku_name || l.sku_id)}</div><div class="uac-muted">Bin ${h(l.bin_id)}${l.batch_number ? ' · batch ' + h(l.batch_number) : ''}</div></div>
                <div class="inv-alert-figure">${expiryChip(l)} <b>${num(l.quantity)}</b></div></div>`)
            + group('fa-box-archive', 't-teal', `Bins full or over limit`, `${t.bin_full_pct || 90}% full or more (by volume or weight). Check the bin limits in Bin Master.`, a.bins_full, b => `
                <div class="inv-alert-item"><div><div class="uac-name">${h(b.bin_id)}</div><div class="uac-muted">Zone ${h(b.zone || '–')}</div></div>
                <div class="inv-alert-figure"><b class="c-danger">${fillText(b.fill_pct)}</b></div></div>`);
    }

    // ------------------------------------------------------------------ History
    async function loadHistory() {
        const box = $('invHistory');
        if (!box) return;
        const params = new URLSearchParams({ limit: '300' });
        const type = $('invHistType')?.value || '';
        const q = ($('invHistQ')?.value || '').trim();
        if (type) params.set('type', type);
        if (q) params.set('q', q);
        if (histFilter) ['inventory_id', 'sku_id', 'bin_id'].forEach(k => { if (histFilter[k] !== undefined) params.set(k, histFilter[k]); });
        if ($('invHistClear')) $('invHistClear').style.display = histFilter ? '' : 'none';
        if ($('invHistSub')) $('invHistSub').innerHTML = histFilter
            ? `Showing <b>${h(histFilter.label || '')}</b> only. Newest first.`
            : 'Every stock change: who, when, how much and why. Newest first.';
        try {
            const res = await fetch('/api/stock/movements?' + params.toString());
            const body = await res.json().catch(() => ({}));
            if (!res.ok || !body.success) throw new Error(body.error || 'Could not load the history.');
            const rows = body.movements || [];
            if (!rows.length) {
                box.innerHTML = emptyBox('fa-clock-rotate-left', 'No changes recorded yet',
                    'Every stock change from now on is listed here, with the person and the reason.');
                return;
            }
            box.innerHTML = `<table class="uac-table inv-table"><thead><tr><th>When</th><th>Change</th><th>Product</th><th>Bin</th>
                <th class="inv-num">Before → After</th><th class="inv-num">Change</th><th>By</th><th>Reason / note</th></tr></thead><tbody>
                ${rows.map(m => {
                    const d = Number(m.delta) || 0;
                    return `<tr><td class="uac-muted" style="white-space:nowrap">${h(when(m.ts))}</td>
                    <td><span class="inv-type ${TYPE_STYLE[m.movement_type] || ''}">${h(m.type_label)}</span></td>
                    <td><div class="uac-name">${h(m.sku_name || m.sku_id || '–')}</div><div class="uac-muted">${h(m.sku_id || '')}${data && data.all_locations && m.warehouse_name ? ' · ' + h(m.warehouse_name) : ''}</div></td>
                    <td><span class="inv-bin-tag">${h(m.bin_id || '–')}</span></td>
                    <td class="inv-num uac-muted">${num(m.qty_before)} → <b class="inv-after">${num(m.qty_after)}</b></td>
                    <td class="inv-num"><b class="${d > 0 ? 'c-up' : (d < 0 ? 'c-danger' : '')}">${d > 0 ? '+' : ''}${num(d)}</b></td>
                    <td>${m.actor ? `<i class="fas fa-user c-slate"></i> ${h(m.actor)}` : '<span class="uac-muted"><i class="fas fa-robot"></i> System</span>'}</td>
                    <td>${m.reason ? h(m.reason) : '<span class="uac-muted">–</span>'}${m.ref ? ` <span class="uac-muted">(${h(m.ref)})</span>` : ''}</td></tr>`;
                }).join('')}</tbody></table>`;
        } catch (e) {
            box.innerHTML = `<div class="uac-empty uac-error">${h(e.message)}</div>`;
        }
    }

    window.invHistoryFor = function (filter) {
        if (filter) {
            const l = filter.inventory_id && data ? data.lines.find(x => x.id === filter.inventory_id) : null;
            const p = filter.sku_id && data ? data.products.find(x => x.sku_id === filter.sku_id) : null;
            // plain text: shown through h() in loadHistory()
            filter.label = l ? String(l.sku_name || l.sku_id) + ' in ' + String(l.bin_id)
                : (p ? String(p.sku_name) : (filter.bin_id ? 'bin ' + String(filter.bin_id) : ''));
        }
        histFilter = filter;
        if (tab !== 'history') invShowTab('history'); else loadHistory();
    };

    // ------------------------------------------------------------------ tabs
    function invShowTab(name) {
        tab = name;
        document.querySelectorAll('#inventory-view .uac-tab').forEach(b => {
            const on = b.dataset.tab === name;
            b.classList.toggle('is-active', on);
            b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        document.querySelectorAll('#inventory-view .uac-pane').forEach(p => p.classList.toggle('is-active', p.dataset.pane === name));
        if (name === 'history') loadHistory();
        try { sessionStorage.setItem('warlog_inv_tab', name); } catch (e) {}
    }
    window.invShowTab = invShowTab;

    // ------------------------------------------------------------------ dialogs
    function modal(title, sub, bodyHtml, okLabel, onOk, okClass) {
        const wrap = document.createElement('div');
        wrap.className = 'uac-modal-backdrop';
        wrap.innerHTML = `<div class="uac-modal inv-modal" role="dialog" aria-modal="true">
            <div class="uac-modal-head"><div><h3>${h(title)}</h3><div class="uac-modal-sub">${sub}</div></div>
                <button class="uac-x" type="button" aria-label="Close">&times;</button></div>
            <div class="uac-modal-body">${bodyHtml}</div>
            <div class="uac-modal-msg"></div>
            <div class="uac-modal-actions"><button class="uac-btn" type="button" data-x>Cancel</button>
                <button class="uac-btn ${okClass || 'uac-btn-primary'}" type="button" data-ok>${okLabel}</button></div></div>`;
        const close = () => wrap.remove();
        wrap.addEventListener('click', e => { if (e.target === wrap) close(); });
        wrap.querySelector('.uac-x').onclick = close;
        wrap.querySelector('[data-x]').onclick = close;
        const msg = wrap.querySelector('.uac-modal-msg');
        const ok = wrap.querySelector('[data-ok]');
        ok.onclick = async () => {
            msg.className = 'uac-modal-msg';
            ok.disabled = true;
            try {
                const err = await onOk(wrap);
                if (err) { msg.textContent = err; msg.className = 'uac-modal-msg error'; }
                else close();
            } catch (e) {
                msg.textContent = e.message || String(e); msg.className = 'uac-modal-msg error';
            } finally { ok.disabled = false; }
        };
        document.body.appendChild(wrap);
        const first = wrap.querySelector('input, select, textarea');
        if (first) setTimeout(() => first.focus(), 30);
        return wrap;
    }

    async function send(url, method, payload) {
        const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const body = await res.json().catch(() => ({}));
        if (!res.ok || body.success === false) return { error: body.error || body.message || 'That did not work.' };
        return body;
    }

    async function afterChange(message) {
        toast(message, 'success');
        await loadInventory();
        if (window.__invMasterOpen) renderMaster();
        if (tab === 'history') loadHistory();
    }

    function findLine(id) { return data ? data.lines.find(l => l.id === id) : null; }

    window.invAdjust = async function (id) {
        if (!data) await loadInventory();
        const l = findLine(id);
        if (!l) return toast('That stock line is no longer here. Refresh and try again.', 'error');
        const reasons = data.reasons || {};
        modal('Adjust stock', `${h(l.sku_name || l.sku_id)} · bin <b>${h(l.bin_id)}</b>${l.batch_number ? ' · batch ' + h(l.batch_number) : ''}`, `
            <div class="inv-adj-now"><span class="uac-muted">Now in this bin</span><b>${num(l.quantity)} ${h(l.uom || '')}</b></div>
            <label class="uac-label" for="invAdjQty">New quantity (what is physically there)</label>
            <input id="invAdjQty" class="uac-input" type="number" min="0" step="1" value="${Number(l.quantity) || 0}">
            <div class="uac-hint" id="invAdjDiff">No change yet.</div>
            <label class="uac-label" for="invAdjReason">Reason</label>
            <select id="invAdjReason" class="uac-input"><option value="">Choose a reason…</option>
                ${Object.entries(reasons).map(([k, v]) => `<option value="${h(k)}">${h(v)}</option>`).join('')}</select>
            <label class="uac-label" for="invAdjNote">Note <span class="uac-muted">(required for "Other")</span></label>
            <textarea id="invAdjNote" class="uac-input" rows="2" maxlength="250" placeholder="e.g. 3 sheets cracked while unloading"></textarea>
            <div class="uac-hint"><i class="fas fa-shield-halved"></i> Recorded in the stock history with your name.</div>`,
            '<i class="fas fa-check"></i> Save adjustment', async (w) => {
                const qty = w.querySelector('#invAdjQty').value.trim();
                const code = w.querySelector('#invAdjReason').value;
                const note = w.querySelector('#invAdjNote').value.trim();
                if (qty === '' || !/^\d+$/.test(qty)) return 'Enter the new quantity as a whole number (0 or more).';
                if (Number(qty) === Number(l.quantity)) return 'The quantity is the same as now.';
                if (!code) return 'Choose a reason.';
                if (code === 'other' && !note) return 'Write a short note for "Other".';
                const reason = reasons[code] + (note ? ': ' + note : '');
                const r = await send('/api/stock/adjust', 'POST', { inventory_id: l.id, quantity: Number(qty), reason_code: code, reason });
                if (r.error) return r.error;
                await afterChange(r.message || 'Stock updated.');
            });
        const q = document.getElementById('invAdjQty');
        const diff = document.getElementById('invAdjDiff');
        q.addEventListener('input', () => {
            const v = Number(q.value);
            if (q.value === '' || isNaN(v)) { diff.textContent = ''; return; }
            const d = v - (Number(l.quantity) || 0);
            diff.innerHTML = d === 0 ? 'No change yet.' : `Change: <b class="${d > 0 ? 'c-up' : 'c-danger'}">${d > 0 ? '+' : ''}${num(d)}</b>`;
        });
    };

    window.invMove = async function (id) {
        if (!data) await loadInventory();
        const l = findLine(id);
        if (!l) return toast('That stock line is no longer here. Refresh and try again.', 'error');
        const targets = data.bins.filter(b => b.bin_id !== l.bin_id && (l.warehouse_id == null || b.warehouse_id === l.warehouse_id));
        if (!targets.length) return toast('There is no other bin in this location to move to. Add one in Master Data Hub > Bin Master.', 'warning');
        modal('Move stock to another bin', `${h(l.sku_name || l.sku_id)} · from bin <b>${h(l.bin_id)}</b>`, `
            <div class="inv-adj-now"><span class="uac-muted">Available in ${h(l.bin_id)}</span><b>${num(l.quantity)} ${h(l.uom || '')}</b></div>
            <label class="uac-label" for="invMvQty">How many to move</label>
            <div class="inv-qty-row"><input id="invMvQty" class="uac-input" type="number" min="1" max="${Number(l.quantity) || 0}" step="1" value="${Number(l.quantity) || 0}">
                <button type="button" class="uac-btn" id="invMvAll">All</button></div>
            <label class="uac-label" for="invMvTo">To bin</label>
            <select id="invMvTo" class="uac-input"><option value="">Choose a bin…</option>
                ${targets.map(b => `<option value="${h(b.bin_id)}">${h(b.bin_id)} · zone ${h(b.zone || '–')} · ${b.fill_pct}% full</option>`).join('')}</select>
            <label class="uac-label" for="invMvNote">Note <span class="uac-muted">(optional)</span></label>
            <input id="invMvNote" class="uac-input" maxlength="250" placeholder="e.g. moved closer to dispatch">`,
            '<i class="fas fa-right-left"></i> Move stock', async (w) => {
                const qty = w.querySelector('#invMvQty').value.trim();
                const to = w.querySelector('#invMvTo').value;
                if (!/^\d+$/.test(qty) || Number(qty) < 1) return 'Enter how many to move (1 or more).';
                if (Number(qty) > Number(l.quantity)) return `Only ${num(l.quantity)} available.`;
                if (!to) return 'Choose the bin to move to.';
                const r = await send('/api/stock/transfer', 'POST', { inventory_id: l.id, quantity: Number(qty), to_bin: to,
                    reason: w.querySelector('#invMvNote').value.trim() });
                if (r.error) return r.error;
                await afterChange(r.message || 'Stock moved.');
            });
        document.getElementById('invMvAll').onclick = () => { document.getElementById('invMvQty').value = Number(l.quantity) || 0; };
    };

    window.invSetMin = async function (sku) {
        if (!data) await loadInventory();
        const p = data.products.find(x => x.sku_id === sku);
        if (!p) return;
        modal('Minimum stock level', `${h(p.sku_name)} · ${h(p.sku_id)}`, `
            <div class="inv-adj-now"><span class="uac-muted">In stock now (this location)</span><b>${num(p.quantity)} ${h(p.uom || '')}</b></div>
            <label class="uac-label" for="invMinQty">Warn me when stock falls below</label>
            <input id="invMinQty" class="uac-input" type="number" min="0" step="1" value="${p.min_qty == null ? '' : Number(p.min_qty)}" placeholder="Leave empty for no minimum">
            <div class="uac-hint">Applies to this location only. Products below it show in Alerts and on the menu badge.</div>`,
            '<i class="fas fa-check"></i> Save', async (w) => {
                const v = w.querySelector('#invMinQty').value.trim();
                if (v !== '' && !/^\d+$/.test(v)) return 'Enter a whole number, or leave it empty.';
                const r = await send('/api/stock/min-level', 'PUT', { sku_id: p.sku_id, min_qty: v === '' ? null : Number(v) });
                if (r.error) return r.error;
                await afterChange(r.message || 'Saved.');
            });
    };

    window.invExportCsv = async function () {
        try {
            const res = await fetch('/api/stock/export.csv');
            if (!res.ok) {
                const b = await res.json().catch(() => ({}));
                return toast(b.error || 'Export failed.', 'error');
            }
            const blob = await res.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `warlog_stock_${new Date().toISOString().slice(0, 10)}.csv`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
        } catch (e) { toast('Export failed.', 'error'); }
    };

    window.openInventoryForBin = function (bin) {
        if (typeof window.switchTab === 'function') window.switchTab('inventory');
        const go = () => window.invStockForBin(bin);
        if (data) go(); else (loading || loadInventory()).then(go);
    };

    // ------------------------------------------------------------------ Master Data Hub > Inventory Master
    function renderMaster() {
        const body = $('inventoryMasterBody');
        if (!body || !data) return;
        if (!data.lines.length) {
            body.innerHTML = '<tr><td colspan="10" style="text-align:center; color:var(--text-muted); padding:18px;">No stock yet. It appears when goods are received or counted into a bin.</td></tr>';
            return;
        }
        body.innerHTML = data.lines.map(l => `<tr>
            <td>#${Number(l.id)}</td>
            <td><span class="inv-bin-tag">${h(l.bin_id || '–')}</span></td>
            <td>${h(l.zone || '–')}</td>
            <td><strong>${h(l.sku_id)}</strong></td>
            <td>${h(l.sku_name || '–')}</td>
            <td>${h(l.category || '–')}</td>
            <td>${h(l.vendor || '–')}</td>
            <td>${h(dateOnly(l.received_date))}</td>
            <td><strong>${num(l.quantity)}</strong> <span style="color:var(--text-muted); font-size:0.78rem;">${h(l.uom || '')}</span></td>
            <td class="uac-actions">${lineActions(l, true)}</td></tr>`).join('');
    }

    window.loadInventoryMaster = async function () {
        window.__invMasterOpen = true;
        const body = $('inventoryMasterBody');
        if (body && !data) body.innerHTML = '<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">Loading...</td></tr>';
        await loadInventory();
        renderMaster();
    };

    // ------------------------------------------------------------------ wiring
    window.loadInventory = loadInventory;

    function wire() {
        const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };
        let t;
        const debounce = (fn) => () => { clearTimeout(t); t = setTimeout(fn, 200); };
        on('invStockQ', 'input', debounce(renderStock));
        ['invStockZone', 'invStockCat', 'invStockIssues'].forEach(id => on(id, 'change', renderStock));
        on('invProdQ', 'input', debounce(renderProducts));
        on('invProdLow', 'change', renderProducts);
        on('invBinQ', 'input', debounce(renderBins));
        ['invBinZone', 'invBinUsed'].forEach(id => on(id, 'change', renderBins));
        on('invHistQ', 'input', debounce(loadHistory));
        on('invHistType', 'change', loadHistory);
        try {
            const saved = sessionStorage.getItem('warlog_inv_tab');
            if (saved && saved !== 'history' && document.querySelector(`#inventory-view .uac-tab[data-tab="${saved}"]`)) invShowTab(saved);
        } catch (e) {}
        // menu badge: alert count, once at start (only for people who can see stock)
        if ($('inventory-view') && can('inventory.view')) setTimeout(() => { if (!data) loadInventory(); }, 2500);
    }

    if (document.readyState === 'complete') wire();
    else window.addEventListener('load', wire);
})();
