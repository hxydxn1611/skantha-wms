/*
 * Companies & Owners (Platform Admin only).
 * Read-only overview of every company, its owners (Company Admins), users and locations.
 * Data: GET /api/platform/companies (permission platform.companies.manage).
 */
(function () {
    'use strict';

    let pcoData = null;

    function esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function when(ts) {
        if (!ts) return 'Never';
        const d = new Date(String(ts).replace(' ', 'T') + (String(ts).includes('Z') ? '' : 'Z'));
        if (isNaN(d.getTime())) return esc(ts);
        return d.toLocaleString(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    function statusPill(status) {
        const s = String(status || 'Active');
        const cls = s.toLowerCase() === 'active' ? 'ok' : 'off';
        return `<span class="pco-pill pco-pill-${cls}">${esc(s)}</span>`;
    }

    async function loadPlatformCompanies() {
        const list = document.getElementById('pcoList');
        if (!list) return;
        if (!pcoData) list.innerHTML = '<div class="pco-empty">Loading companies...</div>';
        try {
            const res = await fetch('/api/platform/companies');
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
            pcoData = data;
            const badge = document.getElementById('nav-platform-companies-count');
            if (badge) { badge.textContent = data.totals.companies; badge.style.display = ''; }
            renderPlatformCompanies();
        } catch (err) {
            list.innerHTML = `<div class="pco-empty pco-error">Could not load companies: ${esc(err.message)}</div>`;
        }
    }

    function matches(c, q) {
        if (!q) return true;
        const hay = [c.name, c.status,
            ...c.users.map(u => `${u.username} ${u.email}`),
            ...c.locations.map(l => `${l.code} ${l.name} ${l.city} ${l.state} ${l.industry}`)].join(' ').toLowerCase();
        return hay.includes(q);
    }

    function renderTotals(t) {
        const el = document.getElementById('pcoTotals');
        if (!el) return;
        const tile = (icon, label, value, color) => `
            <div class="pco-tile">
                <i class="fas ${icon}" style="color:${color};"></i>
                <div><div class="pco-tile-value">${value}</div><div class="pco-tile-label">${label}</div></div>
            </div>`;
        el.innerHTML = tile('fa-building', 'Companies', t.companies, '#8b5cf6')
            + tile('fa-user-tie', 'Owners', t.owners, '#f59e0b')
            + tile('fa-location-dot', 'Locations', t.locations, '#0ea5e9')
            + tile('fa-users', 'Users', t.users, '#10b981');
    }

    function renderOwner(u) {
        return `
            <div class="pco-person">
                <div class="pco-avatar">${esc((u.username || '?').charAt(0).toUpperCase())}</div>
                <div class="pco-person-main">
                    <div class="pco-person-name">${esc(u.username)} ${u.is_active ? '' : '<span class="pco-pill pco-pill-off">Disabled</span>'}</div>
                    <div class="pco-person-meta">${u.email ? esc(u.email) + ' · ' : ''}Last sign-in: ${when(u.last_login_at)}</div>
                </div>
            </div>`;
    }

    function renderLocation(l) {
        const place = [l.city, l.state].filter(Boolean).join(', ');
        return `
            <tr>
                <td><div class="pco-loc-code">${esc(l.code)}</div><div class="pco-loc-name">${esc(l.name)}</div></td>
                <td>${esc(place) || '<span class="pco-muted">-</span>'}</td>
                <td>${esc(l.industry || '-')}<div class="pco-muted">${esc(l.operating_mode || '')}</div></td>
                <td class="pco-num">${l.cameras}</td>
                <td class="pco-num">${l.bins}</td>
                <td class="pco-num">${l.deliveries}</td>
                <td class="pco-num">${l.gate_passes}</td>
                <td>${statusPill(l.status)}</td>
                <td>${when(l.created_at)}</td>
                <td><button class="pco-btn" onclick="pcoWorkIn('${esc(l.code)}')" title="Make this tab file new records into ${esc(l.code)}">
                    <i class="fas fa-right-to-bracket"></i> Work here</button></td>
            </tr>`;
    }

    function renderCompany(c) {
        const owners = c.owners.length
            ? c.owners.map(renderOwner).join('')
            : '<div class="pco-muted">No owner assigned</div>';
        const others = c.users.filter(u => !u.is_owner);
        const otherHtml = others.length
            ? `<div class="pco-subhead">Other users (${others.length})</div>` + others.map(u =>
                `<div class="pco-chip">${esc(u.username)} · ${u.roles.map(r => esc(r.role) + ' @ ' + esc(r.where)).join(', ')}</div>`).join('')
            : '';
        const locs = c.locations.length
            ? `<div class="pco-table-wrap"><table class="pco-table">
                    <thead><tr><th>Location</th><th>City</th><th>Industry</th><th class="pco-num">Cameras</th>
                    <th class="pco-num">Bins</th><th class="pco-num">POs</th><th class="pco-num">Gate passes</th>
                    <th>Status</th><th>Created</th><th></th></tr></thead>
                    <tbody>${c.locations.map(renderLocation).join('')}</tbody></table></div>`
            : '<div class="pco-muted">No locations yet</div>';
        return `
            <div class="glass-panel pco-card">
                <div class="pco-card-head">
                    <div>
                        <div class="pco-company-name">${esc(c.name)}
                            ${c.is_platform_owner ? '<span class="pco-pill pco-pill-owner">Platform owner</span>' : ''}
                            ${statusPill(c.status)}</div>
                        <div class="pco-muted">${c.locations.length} location(s) · ${c.users.length} user(s) · ${c.skus} SKU(s) · since ${when(c.created_at)}</div>
                    </div>
                </div>
                <div class="pco-grid">
                    <div>
                        <div class="pco-subhead">Owner</div>
                        ${owners}
                        ${otherHtml}
                    </div>
                    <div>
                        <div class="pco-subhead">Locations</div>
                        ${locs}
                    </div>
                </div>
            </div>`;
    }

    function renderPlatformCompanies() {
        const list = document.getElementById('pcoList');
        if (!list || !pcoData) return;
        renderTotals(pcoData.totals);
        const q = (document.getElementById('pcoSearch')?.value || '').trim().toLowerCase();
        const shown = pcoData.companies.filter(c => matches(c, q));
        let html = shown.map(renderCompany).join('');
        if (!shown.length) html = '<div class="pco-empty">No company matches your search.</div>';
        if (pcoData.platform_admins.length && !q) {
            html = `<div class="glass-panel pco-card"><div class="pco-subhead">Platform Admins</div>
                ${pcoData.platform_admins.map(u => renderOwner({ ...u, is_active: !!u.is_active })).join('')}</div>` + html;
        }
        if (pcoData.unlinked_locations.length && !q) {
            html += `<div class="glass-panel pco-card"><div class="pco-subhead">Locations without a company</div>
                ${pcoData.unlinked_locations.map(l => `<div class="pco-chip">${esc(l.code)} · ${esc(l.name)}</div>`).join('')}</div>`;
        }
        list.innerHTML = html;
    }

    async function pcoWorkIn(code) {
        if (typeof window.switchActiveFacility === 'function') {
            await window.switchActiveFacility(code);
        }
    }

    window.loadPlatformCompanies = loadPlatformCompanies;
    window.renderPlatformCompanies = renderPlatformCompanies;
    window.pcoWorkIn = pcoWorkIn;
})();
