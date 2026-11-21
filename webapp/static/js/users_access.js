/*
 * Users & Access + Change Password (RBAC Phase 4).
 * APIs: /api/iam/* (users.view / users.invite / users.edit / users.deactivate / assignments.manage),
 *       /api/auth/change_password, and for the Platform Admin /api/platform/companies.
 * The server enforces every rule; buttons here only follow what it reports in `can`.
 */
(function () {
    'use strict';

    let uac = null;          // last /api/iam/overview response
    let companiesLoaded = false;

    function esc(v) {
        return String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    function when(ts) {
        if (!ts) return 'Never';
        const d = new Date(String(ts).replace(' ', 'T') + 'Z');
        if (isNaN(d.getTime())) return esc(ts);
        return d.toLocaleString(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    function toast(text, kind) {
        if (typeof window.warlogToast === 'function') window.warlogToast(text, kind || 'info');
        else if (typeof window.showToast === 'function') window.showToast(text, kind || 'info');
        else alert(text);
    }

    async function api(method, url, body) {
        const sel = document.getElementById('uacCompany');
        const cid = sel && sel.style.display !== 'none' ? sel.value : '';
        const full = cid ? url + (url.includes('?') ? '&' : '?') + 'company_id=' + encodeURIComponent(cid) : url;
        const res = await fetch(full, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: body ? JSON.stringify(body) : undefined
        });
        let data = {};
        try { data = await res.json(); } catch (e) {}
        if (!res.ok || !data.success) throw new Error(data.message || data.error || `Request failed (${res.status})`);
        return data;
    }

    // ------------------------------------------------------------------ modal helper
    function modal(title, bodyHtml, actions, wide, footerLeft, subtitle) {
        closeModal();
        const wrap = document.createElement('div');
        wrap.id = 'uacModal';
        wrap.className = 'uac-modal-backdrop';
        wrap.innerHTML = `
            <div class="uac-modal ${wide ? 'uac-modal-wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="uacModalTitle">
                <div class="uac-modal-head">
                    <div><h3 id="uacModalTitle">${esc(title)}</h3>${subtitle ? `<div class="uac-modal-sub">${esc(subtitle)}</div>` : ''}</div>
                    <button type="button" class="uac-x" aria-label="Close" onclick="window.__uacClose()">&times;</button>
                </div>
                <div class="uac-modal-body">${bodyHtml}</div>
                <div class="uac-modal-msg" id="uacModalMsg" role="alert"></div>
                <div class="uac-modal-actions">
                    <div class="uac-foot-left">${footerLeft || ''}</div>
                    <button type="button" class="uac-btn" onclick="window.__uacClose()">${actions.length ? 'Cancel' : 'Close'}</button>
                    ${actions.map((a, i) => `<button type="button" class="uac-btn ${a.primary ? 'uac-btn-primary' : ''} ${a.danger ? 'uac-btn-danger' : ''}" data-i="${i}">${esc(a.label)}</button>`).join('')}
                </div>
            </div>`;
        document.body.appendChild(wrap);
        wrap.addEventListener('click', e => { if (e.target === wrap) closeModal(); });
        wrap.querySelectorAll('.uac-modal-actions [data-i]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const a = actions[+btn.dataset.i];
                const msg = document.getElementById('uacModalMsg');
                msg.className = 'uac-modal-msg';
                btn.disabled = true;
                try {
                    await a.run();
                } catch (err) {
                    msg.textContent = err.message;
                    msg.className = 'uac-modal-msg error';
                } finally {
                    btn.disabled = false;
                }
            });
        });
        const first = wrap.querySelector('input, select, textarea');
        if (first) first.focus();
        return wrap;
    }

    function closeModal() {
        const m = document.getElementById('uacModal');
        if (m) m.remove();
    }
    window.__uacClose = closeModal;

    function showLinkOnce(title, intro, link) {
        modal(title, `
            <p class="uac-p">${esc(intro)}</p>
            <div class="uac-link-box"><input id="uacLink" class="uac-input" readonly value="${esc(link)}"></div>
            <p class="uac-p uac-muted">Anyone with this link can use it, so share it only with that person.</p>`,
            [{ label: 'Copy link', primary: true, run: async () => {
                const inp = document.getElementById('uacLink');
                inp.select();
                try { await navigator.clipboard.writeText(inp.value); } catch (e) { document.execCommand('copy'); }
                toast('Link copied.', 'success');
            } }]);
    }

    // ------------------------------------------------------------------ load + render
    async function loadCompanies() {
        if (companiesLoaded) return;
        const sel = document.getElementById('uacCompany');
        if (!sel) return;
        try {
            const res = await fetch('/api/platform/companies');
            if (!res.ok) return;  // not the Platform Admin
            const data = await res.json();
            sel.innerHTML = data.companies.map(c =>
                `<option value="${c.id}">${esc(c.name)}${c.status !== 'Active' ? ' (suspended)' : ''}</option>`).join('');
            sel.style.display = '';
            companiesLoaded = true;
        } catch (e) {}
    }

    async function loadUsersAccess() {
        const usersEl = document.getElementById('uacUsers');
        if (!usersEl) return;
        if (window.currentUser && (window.currentUser.is_platform_admin || window.currentUser.role_label === 'Super Admin')) await loadCompanies();
        wireFilters();
        try {
            uac = await api('GET', '/api/iam/overview');
            const sel = document.getElementById('uacCompany');
            if (sel && sel.style.display !== 'none' && !sel.value) sel.value = uac.company_id;
            render();
            loadRoles();
            loadCompanySettings();
            uacLoadAudit(1);
        } catch (err) {
            usersEl.innerHTML = `<div class="uac-empty uac-error">${esc(err.message)}</div>`;
            document.getElementById('uacInvites').innerHTML = '';
        }
    }

    function render() {
        const can = uac.can || {};
        const inviteBtn = document.getElementById('uacInviteBtn');
        if (inviteBtn) inviteBtn.style.display = can['users.invite'] ? '' : 'none';

        fillPeopleFilters();
        const fq = (document.getElementById('uacPeopleQ')?.value || '').trim().toLowerCase();
        const fRole = document.getElementById('uacPeopleRole')?.value || '';
        const fWh = document.getElementById('uacPeopleWh')?.value || '';
        const fStatus = document.getElementById('uacPeopleStatus')?.value || '';
        const people = uac.users.filter(u => {
            const act = u.assignments.filter(a => a.status === 'Active');
            if (fq && !`${u.username} ${u.email || ''}`.toLowerCase().includes(fq)) return false;
            if (fRole && !act.some(a => String(a.role_id) === fRole)) return false;
            if (fWh && !act.some(a => String(a.warehouse_id ?? 'all') === fWh)) return false;
            if (fStatus === 'active' && !u.is_active) return false;
            if (fStatus === 'inactive' && u.is_active) return false;
            return true;
        });
        const rows = people.map(u => {
            const self = u.id === uac.me;
            const active = u.assignments.filter(a => a.status === 'Active');
            const access = active.length
                ? active.map(a => `<span class="uac-chip">${esc(a.role)} &middot; ${esc(a.warehouse_code)}
                    ${can['assignments.manage'] && !self && !u.is_platform_admin ? `<button class="uac-chip-x" title="Remove this access" onclick="uacRevokeAccess(${a.id})">&times;</button>` : ''}</span>`).join('')
                : '<span class="uac-muted">No access</span>';
            const status = u.is_active
                ? '<span class="uac-pill ok">Active</span>' + (u.must_reset_password ? ' <span class="uac-pill warn">Must change password</span>' : '')
                : '<span class="uac-pill off">Deactivated</span>';
            const actions = [];
            if (!self && !u.is_platform_admin) {
                if (can['assignments.manage'] && u.is_active) actions.push(`<button class="uac-btn-sm" onclick="uacAddAccess(${u.id})"><i class="fas fa-plus"></i> Access</button>`);
                if (can['users.edit'] && u.is_active) actions.push(`<button class="uac-btn-sm" onclick="uacResetLink(${u.id})"><i class="fas fa-key"></i> Reset link</button>`);
                if (can['users.edit']) actions.push(`<button class="uac-btn-sm" onclick="uacEditEmail(${u.id})"><i class="fas fa-envelope"></i> Email</button>`);
                if (can['users.deactivate']) actions.push(u.is_active
                    ? `<button class="uac-btn-sm danger" onclick="uacSetActive(${u.id}, false)"><i class="fas fa-user-slash"></i> Deactivate</button>`
                    : `<button class="uac-btn-sm" onclick="uacSetActive(${u.id}, true)"><i class="fas fa-user-check"></i> Activate</button>`);
            }
            return `<tr class="${u.is_active ? '' : 'uac-row-off'}">
                <td><div class="uac-name">${esc(u.username)}${self ? ' <span class="uac-muted">(you)</span>' : ''}</div>
                    <div class="uac-muted">${esc(u.role_label)}</div></td>
                <td>${esc(u.email || '-')}</td>
                <td>${access}</td>
                <td>${status}</td>
                <td>${when(u.last_login_at)}</td>
                <td class="uac-actions">${actions.join('') || '<span class="uac-muted">-</span>'}</td>
            </tr>`;
        }).join('');
        document.getElementById('uacUsers').innerHTML = people.length
            ? `<table class="uac-table"><thead><tr><th>User</th><th>Email</th><th>Access (role &middot; location)</th><th>Status</th><th>Last sign-in</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
            : (uac.users.length ? '<div class="uac-empty"><i class="fas fa-filter"></i> Nobody matches these filters.</div>'
                                : '<div class="uac-empty">No users yet. Invite someone to get started.</div>');

        const fInv = document.getElementById('uacInviteStatus')?.value || '';
        const invites = uac.invitations.filter(i => !fInv || i.status === fInv);
        const pending = uac.invitations.filter(i => i.status === 'Pending').length;
        const badge = document.getElementById('uacInviteBadge');
        if (badge) { badge.textContent = pending; badge.style.display = pending ? '' : 'none'; }
        const inv = invites.map(i => {
            const pill = { Pending: 'warn', Accepted: 'ok', Revoked: 'off', Expired: 'off' }[i.status] || 'off';
            const acts = [];
            if (can['users.invite'] && i.status === 'Pending') acts.push(`<button class="uac-btn-sm danger" onclick="uacRevokeInvite(${i.id})">Revoke</button>`);
            if (can['users.invite'] && (i.status === 'Pending' || i.status === 'Expired' || i.status === 'Revoked')) acts.push(`<button class="uac-btn-sm" onclick="uacResendInvite(${i.id})">Send again</button>`);
            return `<tr><td>${esc(i.email)}</td><td>${esc(i.role_name)} &middot; ${esc(i.warehouse_code)}</td>
                <td><span class="uac-pill ${pill}">${esc(i.status)}</span></td>
                <td>${esc(i.invited_by_name || '-')}</td><td>${when(i.created_at)}</td>
                <td>${i.status === 'Pending' ? when(i.expires_at) : '-'}</td>
                <td class="uac-actions">${acts.join('')}</td></tr>`;
        }).join('');
        document.getElementById('uacInvites').innerHTML = invites.length
            ? `<table class="uac-table"><thead><tr><th>Email</th><th>Role &middot; location</th><th>Status</th><th>Invited by</th><th>Sent</th><th>Expires</th><th></th></tr></thead><tbody>${inv}</tbody></table>`
            : `<div class="uac-empty">${uac.invitations.length ? 'No invitations with this status.' : 'No invitations yet.'}</div>`;
        updateSummary();
        refreshTabs();
    }

    function fillPeopleFilters() {
        const setOpts = (id, first, opts) => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const keep = sel.value;
            sel.innerHTML = `<option value="">${first}</option>` + opts.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('');
            if ([...sel.options].some(o => o.value === keep)) sel.value = keep;
        };
        const roleMap = new Map();
        uac.users.forEach(u => u.assignments.forEach(a => { if (a.status === 'Active') roleMap.set(String(a.role_id), a.role); }));
        setOpts('uacPeopleRole', 'All roles', [...roleMap.entries()].sort((x, y) => x[1].localeCompare(y[1])));
        setOpts('uacPeopleWh', 'All locations', [['all', 'All locations (company-wide)']]
            .concat(uac.warehouses.map(w => [String(w.id), `${w.code} · ${w.name}`])));
    }

    // ------------------------------------------------------------------ tabs, header actions, summary
    const TAB_KEY = 'warlog_uac_tab';
    let currentTab = (() => { try { return localStorage.getItem(TAB_KEY) || 'people'; } catch (e) { return 'people'; } })();

    function tabAvailable(name) {
        const inner = { roles: 'uacRolesPanel', settings: 'uacSettingsPanel', audit: 'uacAuditPanel' }[name];
        if (!inner) return true;
        const el = document.getElementById(inner);
        return !!el && el.style.display !== 'none';
    }

    function refreshTabs() {
        const tabs = [...document.querySelectorAll('#uacTabs .uac-tab')];
        let visible = 0;
        tabs.forEach(t => { const ok = tabAvailable(t.dataset.tab); t.style.display = ok ? '' : 'none'; if (ok) visible++; });
        const bar = document.getElementById('uacTabs');
        if (bar) bar.style.display = visible > 1 ? '' : 'none';
        if (!tabAvailable(currentTab)) currentTab = 'people';
        applyTab();
    }

    function applyTab() {
        document.querySelectorAll('#uacTabs .uac-tab').forEach(t => {
            const on = t.dataset.tab === currentTab;
            t.classList.toggle('is-active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        document.querySelectorAll('#users-access-view .uac-pane').forEach(p => p.classList.toggle('is-active', p.dataset.pane === currentTab));
        document.querySelectorAll('#users-access-view .uac-hdr-btn').forEach(b => {
            b.classList.toggle('tab-off', !(b.dataset.forTab || '').split(' ').includes(currentTab));
        });
    }

    window.uacShowTab = function (name) {
        if (!tabAvailable(name)) return;
        currentTab = name;
        try { localStorage.setItem(TAB_KEY, name); } catch (e) {}
        applyTab();
    };

    let lastChange = null;
    function updateSummary() {
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        if (uac) {
            set('uacStatPeople', uac.users.length);
            set('uacStatActive', uac.users.filter(u => u.is_active).length);
            set('uacStatInvites', uac.invitations.filter(i => i.status === 'Pending').length);
        }
        if (roles) {
            const starters = roles.roles.filter(r => r.template_key).length;
            set('uacStatRoles', `${roles.roles.filter(r => r.is_active).length}` + (starters ? ` (${starters} starter)` : ''));
        } else if (uac) {
            set('uacStatRoles', uac.roles.length);
        }
        set('uacStatLast', lastChange ? shortWhen(lastChange) : '–');
    }

    function shortWhen(ts) {
        const d = new Date(String(ts).replace(' ', 'T') + 'Z');
        if (isNaN(d.getTime())) return String(ts);
        const t = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        const today = new Date();
        const y = new Date(); y.setDate(today.getDate() - 1);
        if (d.toDateString() === today.toDateString()) return `Today ${t}`;
        if (d.toDateString() === y.toDateString()) return `Yesterday ${t}`;
        return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short' }) + ` ${t}`;
    }

    let filtersWired = false;
    function wireFilters() {
        if (filtersWired) return;
        filtersWired = true;
        ['uacPeopleQ', 'uacPeopleRole', 'uacPeopleWh', 'uacPeopleStatus', 'uacInviteStatus'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener(el.tagName === 'INPUT' ? 'input' : 'change', () => uac && render());
        });
        const rq = document.getElementById('uacRolesQ');
        if (rq) rq.addEventListener('input', () => roles && renderRolesTable());
        const aq = document.getElementById('audQ');
        if (aq) aq.addEventListener('keydown', e => { if (e.key === 'Enter') uacLoadAudit(1); });
    }

    function roleOptions() {
        return uac.roles.map(r => `<option value="${r.id}" data-code="${esc(r.builtin_code || '')}">${esc(r.name)}</option>`).join('');
    }

    function warehouseOptions() {
        return '<option value="">All locations</option>' +
            uac.warehouses.map(w => `<option value="${w.id}">${esc(w.code)} &middot; ${esc(w.name)}</option>`).join('');
    }

    function roleWarehouseFields(prefix) {
        return `
            <label class="uac-label" for="${prefix}Role">Role</label>
            <select id="${prefix}Role" class="uac-input" onchange="uacRoleChanged('${prefix}')">${roleOptions()}</select>
            <label class="uac-label" for="${prefix}Wh">Location</label>
            <select id="${prefix}Wh" class="uac-input">${warehouseOptions()}</select>
            <div class="uac-hint" id="${prefix}Hint"></div>`;
    }

    window.uacRoleChanged = function (prefix) {
        const role = document.getElementById(prefix + 'Role');
        const wh = document.getElementById(prefix + 'Wh');
        const hint = document.getElementById(prefix + 'Hint');
        const isAdmin = role.selectedOptions[0]?.dataset.code === 'company_admin';
        if (isAdmin) { wh.value = ''; wh.disabled = true; hint.textContent = 'Company Admin always covers every location and can manage users.'; }
        else { wh.disabled = false; hint.textContent = 'Pick one location, or All locations.'; }
    };

    // ------------------------------------------------------------------ actions
    window.openInviteModal = async function (presetRoleId) {
        if (!uac) { await loadUsersAccess(); if (!uac) return; }
        modal('Invite user by email', `
            <label class="uac-label" for="invEmail">Recipient Email Address</label>
            <input id="invEmail" class="uac-input" type="email" placeholder="teammate@gmail.com" autocomplete="off">
            ${roleWarehouseFields('inv')}
            <p class="uac-p uac-muted">Sends an invitation email directly to this address with a one-click signup link (valid for 72 hours, assigns this role automatically).</p>`,
            [{ label: 'Send invitation email', primary: true, run: async () => {
                const emailVal = document.getElementById('invEmail').value.trim();
                const out = await api('POST', '/api/iam/invitations', {
                    email: emailVal,
                    role_id: document.getElementById('invRole').value,
                    warehouse_id: document.getElementById('invWh').value || null
                });
                await loadUsersAccess();
                if (out.invite_link) showLinkOnce('Invitation created (copy link)', out.message, out.invite_link);
                else { closeModal(); toast(out.message || `Invitation email sent to ${emailVal}!`, 'success'); }
            } }]);
        if (presetRoleId) {
            const rSel = document.getElementById('invRole');
            if (rSel) rSel.value = String(presetRoleId);
        }
        uacRoleChanged('inv');
    };

    window.openAssignRoleModal = async function (roleId) {
        if (!uac) { await loadUsersAccess(); if (!uac) return; }
        const r = (uac.roles || []).find(x => String(x.id) === String(roleId)) || roleById(roleId);
        const rName = r ? r.name : 'Selected role';
        const userOpts = (uac.users || []).filter(u => u.is_active).map(u =>
            `<option value="${u.id}">${esc(u.username)}${u.email ? ' (' + esc(u.email) + ')' : ''}</option>`
        ).join('');
        if (!userOpts) {
            openInviteModal(roleId);
            return;
        }
        const isCompAdmin = r && r.builtin_code === 'company_admin';
        modal(`Assign "${rName}" to user`, `
            <label class="uac-label" for="asrUser">User</label>
            <select id="asrUser" class="uac-input">${userOpts}</select>
            <label class="uac-label" for="asrWh">Location</label>
            <select id="asrWh" class="uac-input" ${isCompAdmin ? 'disabled' : ''}>${warehouseOptions()}</select>
            <div class="uac-hint">${isCompAdmin ? 'Company Admin always covers every location.' : 'Pick one warehouse location, or All locations.'}</div>`,
            [{ label: 'Assign role', primary: true, run: async () => {
                const uid = document.getElementById('asrUser').value;
                const wid = isCompAdmin ? null : (document.getElementById('asrWh').value || null);
                const out = await api('POST', `/api/iam/users/${uid}/assignments`, {
                    role_id: roleId,
                    warehouse_id: wid
                });
                closeModal();
                toast(out.message || `Assigned ${rName} successfully.`, 'success');
                await loadUsersAccess();
            } }]);
    };

    window.uacAddAccess = function (userId) {
        const u = uac.users.find(x => x.id === userId);
        modal(`Give ${u ? u.username : 'user'} access`, roleWarehouseFields('acc'),
            [{ label: 'Give access', primary: true, run: async () => {
                const out = await api('POST', `/api/iam/users/${userId}/assignments`, {
                    role_id: document.getElementById('accRole').value,
                    warehouse_id: document.getElementById('accWh').value || null
                });
                closeModal(); toast(out.message, 'success'); loadUsersAccess();
            } }]);
        uacRoleChanged('acc');
    };

    function findAssignment(id) {
        for (const u of uac.users) for (const a of u.assignments) if (a.id === id) return { u, a };
        return null;
    }
    function userById(id) { return uac.users.find(x => x.id === id) || { username: 'user', email: '' }; }

    window.uacRevokeAccess = function (assignmentId) {
        const f = findAssignment(assignmentId);
        if (!f) return;
        const username = f.u.username, role = f.a.role, where = f.a.warehouse_code;
        modal('Remove access', `<p class="uac-p">Remove <b>${esc(role)}</b> at <b>${esc(where)}</b> from <b>${esc(username)}</b>? It takes effect on their next click.</p>
            <label class="uac-label" for="revReason">Reason (optional)</label><input id="revReason" class="uac-input">`,
            [{ label: 'Remove access', danger: true, run: async () => {
                const out = await api('POST', `/api/iam/assignments/${assignmentId}/revoke`, { reason: document.getElementById('revReason').value });
                closeModal(); toast(out.message, 'success'); loadUsersAccess();
            } }]);
    };

    window.uacSetActive = function (userId, active) {
        const username = userById(userId).username;
        if (active) {
            api('POST', `/api/iam/users/${userId}/activate`, {}).then(o => { toast(o.message, 'success'); loadUsersAccess(); })
                .catch(e => toast(e.message, 'error'));
            return;
        }
        modal(`Deactivate ${username}`, `<p class="uac-p">${esc(username)} will be signed out at once and can't sign in again until reactivated. Their history stays.</p>
            <label class="uac-label" for="deaReason">Reason</label><input id="deaReason" class="uac-input" placeholder="e.g. Left the company">`,
            [{ label: 'Deactivate', danger: true, run: async () => {
                const out = await api('POST', `/api/iam/users/${userId}/deactivate`, { reason: document.getElementById('deaReason').value });
                closeModal(); toast(out.message, 'success'); loadUsersAccess();
            } }]);
    };

    window.uacResetLink = function (userId) {
        const username = userById(userId).username;
        modal(`Reset password for ${username}`, `<p class="uac-p">Send ${esc(username)} a link to choose a new password. It works once, for 30 minutes.</p>`,
            [{ label: 'Send reset link', primary: true, run: async () => {
                const out = await api('POST', `/api/iam/users/${userId}/reset_link`, {});
                if (out.reset_link) showLinkOnce('Reset link', out.message, out.reset_link);
                else { closeModal(); toast(out.message, 'success'); }
            } }]);
    };

    window.uacEditEmail = function (userId) {
        const current = userById(userId).email || '';
        modal('Change email', `<label class="uac-label" for="emlNew">Email</label><input id="emlNew" class="uac-input" type="email" value="${esc(current)}">`,
            [{ label: 'Save', primary: true, run: async () => {
                const out = await api('PATCH', `/api/iam/users/${userId}`, { email: document.getElementById('emlNew').value.trim() });
                closeModal(); toast(out.message, 'success'); loadUsersAccess();
            } }]);
    };

    window.uacRevokeInvite = function (id) {
        api('POST', `/api/iam/invitations/${id}/revoke`, {}).then(o => { toast(o.message, 'success'); loadUsersAccess(); })
            .catch(e => toast(e.message, 'error'));
    };

    window.uacResendInvite = function (id) {
        api('POST', `/api/iam/invitations/${id}/resend`, {}).then(out => {
            loadUsersAccess();
            if (out.invite_link) showLinkOnce('New invitation link', out.message, out.invite_link);
            else toast(out.message, 'success');
        }).catch(e => toast(e.message, 'error'));
    };

    // ------------------------------------------------------------------ change password (everyone)
    window.openChangePasswordModal = function () {
        modal('Change your password', `
            <label class="uac-label" for="cpCurrent">Current password</label>
            <input id="cpCurrent" class="uac-input" type="password" autocomplete="current-password">
            <label class="uac-label" for="cpNew">New password</label>
            <input id="cpNew" class="uac-input" type="password" autocomplete="new-password">
            <div class="uac-hint">At least 10 characters. Not your username or company name.</div>
            <label class="uac-label" for="cpConfirm">Confirm new password</label>
            <input id="cpConfirm" class="uac-input" type="password" autocomplete="new-password">
            <p class="uac-p uac-muted">You stay signed in here; other devices are signed out.</p>`,
            [{ label: 'Change password', primary: true, run: async () => {
                const res = await fetch('/api/auth/change_password', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        current_password: document.getElementById('cpCurrent').value,
                        new_password: document.getElementById('cpNew').value,
                        confirm_password: document.getElementById('cpConfirm').value
                    })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || !data.success) throw new Error(data.message || data.error || 'Could not change the password.');
                closeModal(); toast(data.message, 'success');
            } }]);
    };

    // ------------------------------------------------------------------ companies (Platform Admin)
    window.openCreateCompanyModal = function () {
        modal('New company', `
            <label class="uac-label" for="ncName">Company name</label><input id="ncName" class="uac-input">
            <label class="uac-label" for="ncCity">City of the first location</label><input id="ncCity" class="uac-input" placeholder="e.g. Chennai">
            <label class="uac-label" for="ncEmail">Owner's email (becomes Company Admin)</label><input id="ncEmail" class="uac-input" type="email">
            <p class="uac-p uac-muted">The company starts with one empty location. The owner gets an invitation link to set up their account.</p>`,
            [{ label: 'Create company', primary: true, run: async () => {
                const res = await fetch('/api/platform/companies', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: document.getElementById('ncName').value, city: document.getElementById('ncCity').value,
                                           owner_email: document.getElementById('ncEmail').value.trim() })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || !data.success) throw new Error(data.message || data.error || 'Could not create the company.');
                companiesLoaded = false;
                if (typeof window.loadPlatformCompanies === 'function') window.loadPlatformCompanies();
                const inv = data.invitation || {};
                if (inv.invite_link) showLinkOnce(`${data.name} created`, inv.message, inv.invite_link);
                else { closeModal(); toast(`${data.name} created. ${inv.message || ''}`, 'success'); }
            } }]);
    };

    window.pcoSetCompanyStatus = function (companyId, active) {
        const name = (window.__pcoNames && window.__pcoNames[companyId]) || 'this company';
        const go = async (reason) => {
            const res = await fetch(`/api/platform/companies/${companyId}/${active ? 'activate' : 'suspend'}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) throw new Error(data.message || data.error || 'Failed.');
            closeModal(); toast(data.message, 'success');
            companiesLoaded = false;
            if (typeof window.loadPlatformCompanies === 'function') window.loadPlatformCompanies();
        };
        if (active) { go('').catch(e => toast(e.message, 'error')); return; }
        modal(`Suspend ${name}`, `<p class="uac-p">Everyone in ${esc(name)} is signed out and can't sign in until you reactivate it. No data is deleted.</p>
            <label class="uac-label" for="susReason">Reason</label><input id="susReason" class="uac-input">`,
            [{ label: 'Suspend company', danger: true, run: () => go(document.getElementById('susReason').value) }]);
    };

    // ------------------------------------------------------------------ roles (Phase 5)
    let roles = null;   // /api/iam/roles response

    async function loadRoles() {
        const panel = document.getElementById('uacRolesPanel');
        if (!panel) return;
        try {
            roles = await api('GET', '/api/iam/roles');
        } catch (err) {
            panel.style.display = 'none';   // no roles.view
            refreshTabs();
            return;
        }
        panel.style.display = '';
        document.getElementById('uacNewRoleBtn').style.display = roles.can_manage ? 'inline-flex' : 'none';
        const packBtn = document.getElementById('uacApplyPackBtn');
        const packSel = document.getElementById('uacRolePackSelect');
        if (packBtn) packBtn.style.display = roles.can_manage ? 'inline-flex' : 'none';
        if (packSel) packSel.style.display = roles.can_manage ? '' : 'none';
        try {
            const cov = await api('GET', '/api/iam/roles/coverage');
            const meter = document.getElementById('uacCoverageMeter');
            if (meter && cov && typeof cov.coverage_pct !== 'undefined') {
                meter.textContent = `Coverage: ${cov.covered_permissions}/${cov.total_permissions} (${cov.coverage_pct}%)`;
            }
        } catch (e) {}
        renderRolesTable();
        updateSummary();
        refreshTabs();
    }

    window.uacApplyRolePack = async function () {
        const pack = document.getElementById('uacRolePackSelect')?.value || '3_role';
        try {
            const out = await api('POST', '/api/iam/roles/apply-pack', { pack });
            await loadUsersAccess();
            toast((out.message || `Applied ${pack} role pack.`) + ' Use Assign or Invite on any role below.', 'success');
        } catch (e) {
            toast(e.message || 'Could not apply role pack.', 'error');
        }
    };

    function renderRolesTable() {
        const q = (document.getElementById('uacRolesQ')?.value || '').trim().toLowerCase();
        const visibleRoles = roles.roles.filter(r => r.is_active || (r.users && r.users.length > 0));
        const hiddenCount = roles.roles.length - visibleRoles.length;
        const list = visibleRoles.filter(r => !q || `${r.name} ${r.description}`.toLowerCase().includes(q));
        const rows = list.map(r => {
            const badge = r.is_builtin ? '<span class="uac-pill warn">Built-in</span>'
                : (r.is_active ? (r.template_key ? '<span class="uac-pill starter">Starter</span> ' : '') + '<span class="uac-pill ok">Active</span>'
                               : '<span class="uac-pill off">Deactivated</span>');
            const people = r.users.length
                ? r.users.slice(0, 4).map(u => `<span class="uac-chip">${esc(u.username)} &middot; ${esc(u.warehouse_code)}</span>`).join('')
                  + (r.users.length > 4 ? ` <span class="uac-muted">+${r.users.length - 4} more</span>` : '')
                : '<span class="uac-muted">Nobody yet</span>';
            const acts = [];
            if (r.is_active && r.builtin_code !== 'user') {
                if (uac && uac.can && uac.can['assignments.manage']) {
                    acts.push(`<button class="uac-btn-sm" onclick="openAssignRoleModal(${r.id})" title="Assign this role to an existing user"><i class="fas fa-user-check"></i> Assign</button>`);
                }
                if (uac && uac.can && uac.can['users.invite']) {
                    acts.push(`<button class="uac-btn-sm" onclick="openInviteModal(${r.id})" title="Invite someone by email with this role"><i class="fas fa-envelope"></i> Invite</button>`);
                }
            }
            acts.push(`<button class="uac-btn-sm" onclick="openRoleEditor(${r.id})"><i class="fas ${r.is_builtin || !roles.can_manage ? 'fa-eye' : 'fa-pen'}"></i> ${r.is_builtin || !roles.can_manage ? 'View' : 'Edit'}</button>`);
            if (!r.is_builtin && roles.can_manage) {
                acts.push(r.is_active
                    ? `<button class="uac-btn-sm danger" onclick="uacRoleSetActive(${r.id}, false)"><i class="fas fa-ban"></i> Deactivate</button>`
                    : `<button class="uac-btn-sm" onclick="uacRoleSetActive(${r.id}, true)"><i class="fas fa-rotate-left"></i> Reactivate</button>`);
            }
            const count = r.builtin_code === 'company_admin' ? 'Everything in the company' : `${r.permissions.length} permission(s)`;
            return `<tr class="${r.is_active ? '' : 'uac-row-off'}">
                <td><div class="uac-name">${esc(r.name)}</div><div class="uac-muted">${esc(r.description)}</div></td>
                <td class="uac-nowrap">${badge}</td><td>${count}</td><td>${people}</td>
                <td class="uac-actions">${acts.join('')}</td></tr>`;
        }).join('');
        document.getElementById('uacRoles').innerHTML = (list.length
            ? `<table class="uac-table"><thead><tr><th>Role</th><th>Type</th><th>Grants</th><th>People</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
            : '<div class="uac-empty"><i class="fas fa-filter"></i> No role matches.</div>')
            + (hiddenCount > 0 ? `<div class="uac-muted" style="padding:10px 4px 2px; font-size:0.78rem;">${hiddenCount} unused pack/inactive role(s) hidden. Switch packs anytime via Apply Pack above.</div>` : '');
    }

    function roleById(id) { return (roles && roles.roles.find(r => r.id === id)) || null; }

    const MODULE_ICONS = {
        'Gate': 'fa-torii-gate', 'Dashboard': 'fa-gauge-high', 'Pre-registration': 'fa-clipboard-list',
        'Dock': 'fa-truck-ramp-box', 'Inbound': 'fa-arrow-right-to-bracket', 'Locations': 'fa-location-dot',
        'Master data': 'fa-barcode', 'Inventory': 'fa-boxes-stacked', 'Cycle count': 'fa-list-check',
        'Outbound': 'fa-truck-fast', 'Pallets': 'fa-pallet', 'AI vision': 'fa-eye',
        'Vision configuration': 'fa-sliders', 'Cameras': 'fa-video', 'Workers': 'fa-id-badge',
        'Violations': 'fa-triangle-exclamation', 'Copilot': 'fa-wand-magic-sparkles',
        'Controlled actions': 'fa-shield-halved', 'Integration': 'fa-plug', 'Administration': 'fa-user-gear'
    };

    // Role editor state (one editor open at a time)
    const ed = { role: null, readOnly: false, selected: new Set(), module: null, query: '' };

    function allPerms() {
        const out = [];
        roles.catalog.forEach(g => g.permissions.forEach(p => out.push({ ...p, module: g.module })));
        return out;
    }

    function canToggle(p) {
        return !ed.readOnly && (p.grantable || ed.selected.has(p.key));
    }

    function permRow(p, showModule) {
        const on = ed.selected.has(p.key);
        const locked = !p.grantable;
        const tip = locked ? 'You can only grant permissions you have yourself' : p.key;
        return `<label class="rb-row ${on ? 'is-on' : ''} ${canToggle(p) ? '' : 'is-locked'}" title="${esc(tip)}">
            <span class="rb-row-main">
                <span class="rb-row-label">${esc(p.label)}</span>
                <span class="rb-row-meta">
                    ${showModule ? `<span class="rb-tag rb-tag-module">${esc(p.module)}</span>` : ''}
                    <span class="rb-tag">${esc(p.action)}</span>
                    ${p.sensitive ? '<span class="rb-tag rb-tag-sensitive"><i class="fas fa-shield-halved"></i> Sensitive</span>' : ''}
                    ${locked ? '<span class="rb-tag rb-tag-lock"><i class="fas fa-lock"></i> Not yours to grant</span>' : ''}
                </span>
            </span>
            <span class="rb-switch">
                <input type="checkbox" data-key="${esc(p.key)}" ${on ? 'checked' : ''} ${canToggle(p) ? '' : 'disabled'}>
                <span class="rb-slider" aria-hidden="true"></span>
            </span>
        </label>`;
    }

    function groupStats(g) {
        const total = g.permissions.length;
        const on = g.permissions.filter(p => ed.selected.has(p.key)).length;
        return { on, total };
    }

    function renderNav() {
        const q = ed.query;
        const html = roles.catalog.map(g => {
            const { on, total } = groupStats(g);
            const hits = q ? g.permissions.filter(p => matchQuery(p, g.module)).length : total;
            const icon = MODULE_ICONS[g.module] || 'fa-circle';
            return `<button type="button" class="rb-nav-item ${g.module === ed.module && !q ? 'is-active' : ''} ${q && !hits ? 'is-dim' : ''}"
                        data-module="${esc(g.module)}">
                <i class="fas ${icon} rb-nav-icon"></i>
                <span class="rb-nav-name">${esc(g.module)}</span>
                <span class="rb-nav-count ${on ? 'has-on' : ''}">${on}/${total}</span>
                <span class="rb-nav-bar"><span style="width:${total ? Math.round(on * 100 / total) : 0}%"></span></span>
            </button>`;
        }).join('');
        document.getElementById('rbNav').innerHTML = html;
    }

    function matchQuery(p, module) {
        const q = ed.query;
        return !q || `${p.label} ${p.key} ${p.action} ${module} ${p.section || ''}`.toLowerCase().includes(q);
    }

    function renderPane() {
        const pane = document.getElementById('rbPane');
        if (ed.query) {
            const hits = allPerms().filter(p => matchQuery(p, p.module));
            pane.innerHTML = `
                <div class="rb-pane-head">
                    <div><div class="rb-pane-title">Search results</div>
                    <div class="rb-pane-sub">${hits.length} permission(s) match &ldquo;${esc(ed.query)}&rdquo;</div></div>
                </div>
                <div class="rb-pane-body">${hits.length ? `<div class="rb-section">${hits.map(p => permRow(p, true)).join('')}</div>`
                    : '<div class="rb-empty"><i class="fas fa-magnifying-glass"></i> Nothing matches. Try another word.</div>'}</div>`;
            return;
        }
        const g = roles.catalog.find(x => x.module === ed.module) || roles.catalog[0];
        const { on, total } = groupStats(g);
        const sections = [];
        g.permissions.forEach(p => {
            const name = p.section || '';
            let s = sections.find(x => x.name === name);
            if (!s) { s = { name, perms: [] }; sections.push(s); }
            s.perms.push(p);
        });
        const togglable = g.permissions.filter(canToggle);
        pane.innerHTML = `
            <div class="rb-pane-head">
                <div><div class="rb-pane-title"><i class="fas ${MODULE_ICONS[g.module] || 'fa-circle'}"></i> ${esc(g.module)}</div>
                <div class="rb-pane-sub">${on} of ${total} selected</div></div>
                ${ed.readOnly || !togglable.length ? '' : `<div class="rb-pane-actions">
                    <button type="button" class="rb-link" data-act="all">Select all</button>
                    <button type="button" class="rb-link" data-act="none">Clear</button></div>`}
            </div>
            <div class="rb-pane-body">${sections.map(s => `
                <div class="rb-section">
                    ${s.name ? `<div class="rb-section-title">${esc(s.name)}</div>` : ''}
                    ${s.perms.map(p => permRow(p, false)).join('')}
                </div>`).join('')}</div>`;
    }

    function renderTotals() {
        const t = document.getElementById('rbTotal');
        if (t) t.innerHTML = `<b>${ed.selected.size}</b> permission(s) selected`;
    }

    function refreshEditor() {
        renderNav();
        renderPane();
        renderTotals();
    }

    function invalidatePreview() {
        const box = document.getElementById('rbPreview');
        if (box) { box.innerHTML = ''; delete box.dataset.confirmed; }
        const btn = document.querySelector('#uacModal .uac-btn-primary');
        if (btn && ed.role) btn.textContent = 'Review & save';
    }

    function wireEditor() {
        const root = document.getElementById('rbEditor');
        root.addEventListener('click', e => {
            const nav = e.target.closest('.rb-nav-item');
            if (nav) {
                ed.module = nav.dataset.module;
                ed.query = '';
                document.getElementById('rbSearch').value = '';
                refreshEditor();
                document.querySelector('#rbPane .rb-pane-body')?.scrollTo(0, 0);
                return;
            }
            const act = e.target.closest('.rb-link');
            if (act) {
                const g = roles.catalog.find(x => x.module === ed.module);
                g.permissions.filter(canToggle).forEach(p => {
                    if (act.dataset.act === 'all') ed.selected.add(p.key); else ed.selected.delete(p.key);
                });
                invalidatePreview();
                refreshEditor();
            }
        });
        root.addEventListener('change', e => {
            const key = e.target.dataset && e.target.dataset.key;
            if (!key) return;
            if (e.target.checked) ed.selected.add(key); else ed.selected.delete(key);
            e.target.closest('.rb-row').classList.toggle('is-on', e.target.checked);
            invalidatePreview();
            renderNav();
            renderTotals();
            const sub = document.querySelector('#rbPane .rb-pane-sub');
            if (sub && !ed.query) {
                const g = roles.catalog.find(x => x.module === ed.module);
                const { on, total } = groupStats(g);
                sub.textContent = `${on} of ${total} selected`;
            }
        });
        document.getElementById('rbSearch').addEventListener('input', e => {
            ed.query = e.target.value.trim().toLowerCase();
            renderNav();
            renderPane();
        });
    }

    window.uacRestoreRoleDefaults = function () {
        if (!ed.role || !ed.role.template_permissions) return;
        ed.selected = new Set(ed.role.template_permissions);
        invalidatePreview();
        refreshEditor();
        toast('Default permissions restored. Save to keep them.', 'info');
    };

    window.openRoleEditor = function (roleId) {
        if (!roles) return;
        const r = roleId ? roleById(roleId) : null;
        ed.role = r;
        ed.readOnly = !!(r && (r.is_builtin || !roles.can_manage));
        ed.selected = new Set(r ? r.permissions : []);
        ed.query = '';
        const firstOn = roles.catalog.find(g => g.permissions.some(p => ed.selected.has(p.key)));
        ed.module = (firstOn || roles.catalog[0]).module;

        const title = r ? (ed.readOnly ? r.name : `Edit role`) : 'New role';
        const totalPerms = allPerms().length;
        const note = r && r.builtin_code === 'company_admin'
            ? '<div class="rb-note"><i class="fas fa-circle-info"></i> Built-in role: full access inside the company, including people and roles. It can\'t be changed.</div>'
            : r && r.builtin_code === 'user'
                ? '<div class="rb-note"><i class="fas fa-circle-info"></i> Built-in role: grants nothing by itself. Give people a custom role for what they should do.</div>'
                : r && r.template_key
                    ? '<div class="rb-note"><i class="fas fa-wand-magic-sparkles"></i> Starter role. Change anything you like; <b>Restore defaults</b> brings back the original ticks.</div>'
                    : '';
        const body = `
            ${note}
            <div class="rb-top">
                <div class="rb-field"><label class="uac-label" for="rbName">Role name</label>
                    <input id="rbName" class="uac-input" maxlength="60" value="${esc(r ? r.name : '')}" ${ed.readOnly ? 'disabled' : ''} placeholder="e.g. Gate Operator"></div>
                <div class="rb-field"><label class="uac-label" for="rbDesc">Description</label>
                    <input id="rbDesc" class="uac-input" maxlength="300" value="${esc(r ? r.description : '')}" ${ed.readOnly ? 'disabled' : ''} placeholder="What does this person do?"></div>
            </div>
            <div id="rbEditor" class="rb-editor">
                <aside class="rb-side">
                    <div class="rb-search"><i class="fas fa-magnifying-glass"></i>
                        <input id="rbSearch" class="uac-input" placeholder="Search ${totalPerms} permissions" autocomplete="off"></div>
                    <nav id="rbNav" class="rb-nav" aria-label="Permission groups"></nav>
                    <div class="rb-side-foot">${roles.catalog.length} groups &middot; ${totalPerms} permissions</div>
                </aside>
                <section id="rbPane" class="rb-pane" aria-live="polite"></section>
            </div>
            <div id="rbPreview"></div>`;
        const footerLeft = `<span id="rbTotal" class="rb-total"></span>
            ${r && r.template_permissions && !ed.readOnly ? '<button type="button" class="rb-link" onclick="uacRestoreRoleDefaults()"><i class="fas fa-rotate-left"></i> Restore defaults</button>' : ''}`;
        const actions = ed.readOnly ? [] : [{
            label: r ? 'Review & save' : 'Create role', primary: true, run: async () => {
                const payload = { name: document.getElementById('rbName').value, description: document.getElementById('rbDesc').value,
                                  permissions: [...ed.selected] };
                if (!r) {
                    const out = await api('POST', '/api/iam/roles', payload);
                    closeModal(); toast(out.message, 'success'); loadUsersAccess();
                    return;
                }
                const box = document.getElementById('rbPreview');
                if (!box.dataset.confirmed) {
                    const pv = await api('POST', `/api/iam/roles/${r.id}/preview`, payload);
                    const list = (arr, cls) => arr.length ? arr.map(x => `<span class="rb-chip ${cls}">${esc(x)}</span>`).join('') : '<span class="uac-muted">nothing</span>';
                    box.innerHTML = `<div class="rb-preview">
                        <div class="rb-preview-head"><i class="fas fa-users"></i>
                            <span><b>${pv.users.length}</b> user(s) get this change on their next click${pv.users.length ? ': ' + pv.users.map(u => esc(u.username)).join(', ') : ''}</span></div>
                        <div class="rb-diff"><span class="rb-diff-label">Adds</span><div>${list(pv.added, 'rb-add')}</div></div>
                        <div class="rb-diff"><span class="rb-diff-label">Removes</span><div>${list(pv.removed, 'rb-rem')}</div></div>
                        <div class="rb-preview-foot">Check the changes, then press <b>Confirm &amp; save</b>.</div></div>`;
                    box.dataset.confirmed = '1';
                    const btn = document.querySelector('#uacModal .uac-btn-primary');
                    if (btn) btn.textContent = 'Confirm & save';
                    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    return;
                }
                const out = await api('PUT', `/api/iam/roles/${r.id}`, payload);
                closeModal(); toast(out.message, 'success'); loadUsersAccess();
            } }];
        modal(title, body, actions, true, footerLeft,
              r ? (ed.readOnly ? (r.is_builtin ? 'Built-in role (read-only)' : 'View only') : r.name) : 'Pick what people with this role may do.');
        refreshEditor();
        wireEditor();
        // editing the name/description after a preview needs a fresh preview
        ['rbName', 'rbDesc'].forEach(id => document.getElementById(id).addEventListener('input', invalidatePreview));
    };

    window.uacRoleSetActive = function (roleId, active) {
        const r = roleById(roleId);
        if (!r) return;
        if (active) {
            api('POST', `/api/iam/roles/${roleId}/activate`, {}).then(o => { toast(o.message, 'success'); loadUsersAccess(); })
                .catch(e => toast(e.message, 'error'));
            return;
        }
        modal(`Deactivate role: ${r.name}`, `
            <p class="uac-p">${r.users.length} user(s) lose this role's permissions on their next click:
                ${r.users.map(u => esc(u.username)).join(', ') || 'nobody'}. Their other access stays. You can reactivate it later.</p>
            <label class="uac-label" for="rdReason">Reason</label><input id="rdReason" class="uac-input">`,
            [{ label: 'Deactivate role', danger: true, run: async () => {
                const out = await api('POST', `/api/iam/roles/${roleId}/deactivate`, { reason: document.getElementById('rdReason').value });
                closeModal(); toast(out.message, 'success'); loadUsersAccess();
            } }]);
    };

    // ------------------------------------------------------------------ company settings (Phase 7)
    async function loadCompanySettings() {
        const panel = document.getElementById('uacSettingsPanel');
        if (!panel) return;
        let data;
        try { data = await api('GET', '/api/iam/company_settings'); }
        catch (e) { panel.style.display = 'none'; refreshTabs(); return; }
        const s = data.settings, can = data.can;
        if (!can['copilot.web_search'] && !can['audit.retention_days']) { panel.style.display = 'none'; refreshTabs(); return; }
        panel.style.display = '';
        refreshTabs();
        document.getElementById('uacSettings').innerHTML = `
            <div class="set-row">
                <div><div class="set-title">Copilot web search</div>
                    <div class="uac-muted">Lets Copilot look up general questions on the internet. Number plates, PO numbers, phone numbers, emails and names are removed before anything leaves the server. Off by default.</div></div>
                <label class="set-switch" title="${can['copilot.web_search'] ? '' : 'You need the Copilot settings permission'}">
                    <input type="checkbox" id="setWebSearch" ${s['copilot.web_search'] ? 'checked' : ''} ${can['copilot.web_search'] ? '' : 'disabled'}>
                    <span class="set-slider"></span></label>
            </div>
            <div class="set-row">
                <div><div class="set-title">Keep audit records for</div>
                    <div class="uac-muted">Older records are removed once a day. Between 30 and 3650 days.</div></div>
                <div class="set-inline"><input type="number" id="setRetention" class="uac-input" min="30" max="3650"
                    value="${esc(s['audit.retention_days'])}" ${can['audit.retention_days'] ? '' : 'disabled'}><span class="uac-muted">days</span>
                    ${can['audit.retention_days'] ? '<button class="uac-btn-sm" id="setRetentionSave">Save</button>' : ''}</div>
            </div>`;
        const save = async (key, value) => {
            try { const o = await api('PUT', '/api/iam/company_settings', { key, value }); toast(o.message, 'success'); }
            catch (e) { toast(e.message, 'error'); loadCompanySettings(); }
        };
        const ws = document.getElementById('setWebSearch');
        if (ws && !ws.disabled) ws.addEventListener('change', () => save('copilot.web_search', ws.checked));
        const rb = document.getElementById('setRetentionSave');
        if (rb) rb.addEventListener('click', () => save('audit.retention_days', document.getElementById('setRetention').value));
    }

    // ------------------------------------------------------------------ audit log (Phase 7)
    let auditRows = [];

    function auditQuery(page) {
        const p = new URLSearchParams();
        const v = id => (document.getElementById(id) || {}).value || '';
        if (v('audQ')) p.set('q', v('audQ'));
        if (v('audArea')) p.set('action', v('audArea'));
        if (v('audFrom')) p.set('from', v('audFrom'));
        if (v('audTo')) p.set('to', v('audTo'));
        if (page) p.set('page', page);
        return p.toString();
    }

    function actionLabel(a) {
        // 'iam.invitation.accepted' -> 'invitation accepted', 'gate.entry_approved' -> 'gate entry approved'
        return String(a || '').replace(/^(iam|auth|platform|activity)\./, '').replace(/[._]/g, ' ');
    }

    window.uacLoadAudit = async function (page) {
        const panel = document.getElementById('uacAuditPanel');
        if (!panel) return;
        let data;
        try { data = await api('GET', '/api/iam/audit?' + auditQuery(page || 1)); }
        catch (e) { panel.style.display = 'none'; refreshTabs(); return; }
        panel.style.display = '';
        document.getElementById('uacAuditExport').style.display = data.can_export ? 'inline-flex' : 'none';
        auditRows = data.rows;
        if ((page || 1) === 1 && data.rows.length && !document.getElementById('audQ').value
                && !document.getElementById('audArea').value) {
            lastChange = data.rows[0].ts;
            updateSummary();
        }
        refreshTabs();
        const resultPill = r => r === 'success' ? '' : `<span class="uac-pill ${r === 'denied' ? 'off' : 'warn'}">${esc(r)}</span>`;
        document.getElementById('uacAudit').innerHTML = data.rows.length ? `
            <table class="uac-table aud-table"><thead><tr><th>When</th><th>Who</th><th>What</th><th>Record</th><th>Where</th><th>Reason</th><th></th></tr></thead>
            <tbody>${data.rows.map((r, i) => `<tr>
                <td class="aud-when">${when(r.ts)}</td>
                <td>${esc(r.actor_username || '-')}${String(r.actor_username || '').startsWith('system:') ? ' <span class="uac-pill starter">system</span>' : ''}</td>
                <td><span class="aud-action">${esc(actionLabel(r.action))}</span> ${resultPill(r.result)}</td>
                <td class="uac-muted">${esc([r.resource_type, r.resource_id].filter(Boolean).join(' '))}</td>
                <td class="uac-muted">${esc(r.warehouse_code || r.company_name || '')}</td>
                <td>${esc(r.reason || '')}</td>
                <td>${r.before || r.after ? `<button class="uac-btn-sm" onclick="uacAuditDetails(${i})">Details</button>` : ''}</td>
            </tr>`).join('')}</tbody></table>` : '<div class="uac-empty">No records match.</div>';
        const pager = document.getElementById('uacAuditPager');
        pager.innerHTML = data.pages > 1 ? `
            <button class="uac-btn-sm" ${data.page <= 1 ? 'disabled' : ''} onclick="uacLoadAudit(${data.page - 1})">Previous</button>
            <span class="uac-muted">Page ${data.page} of ${data.pages} &middot; ${data.total} records</span>
            <button class="uac-btn-sm" ${data.page >= data.pages ? 'disabled' : ''} onclick="uacLoadAudit(${data.page + 1})">Next</button>`
            : `<span class="uac-muted">${data.total} record(s)</span>`;
    };

    window.uacAuditDetails = function (i) {
        const r = auditRows[i];
        if (!r) return;
        const block = (title, obj) => obj ? `<div class="aud-block"><div class="uac-subhead">${title}</div><pre>${esc(JSON.stringify(obj, null, 2))}</pre></div>` : '';
        modal(actionLabel(r.action), `
            <p class="uac-p uac-muted">${when(r.ts)} &middot; ${esc(r.actor_username || '-')} &middot; ${esc(r.warehouse_code || r.company_name || '')}${r.ip ? ' &middot; ' + esc(r.ip) : ''}</p>
            ${r.reason ? `<p class="uac-p"><b>Reason:</b> ${esc(r.reason)}</p>` : ''}
            ${block('Before', r.before)}${block('After', r.after)}`, []);
    };

    window.uacExportAudit = function () {
        const sel = document.getElementById('uacCompany');
        const cid = sel && sel.style.display !== 'none' ? '&company_id=' + encodeURIComponent(sel.value) : '';
        window.location.href = '/api/iam/audit/export?' + auditQuery(0) + cid;
    };

    window.loadUsersAccess = loadUsersAccess;
})();
