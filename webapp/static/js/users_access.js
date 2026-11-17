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
        if (typeof window.showToast === 'function') window.showToast(text, kind || 'info');
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
    function modal(title, bodyHtml, actions) {
        closeModal();
        const wrap = document.createElement('div');
        wrap.id = 'uacModal';
        wrap.className = 'uac-modal-backdrop';
        wrap.innerHTML = `
            <div class="uac-modal" role="dialog" aria-modal="true" aria-labelledby="uacModalTitle">
                <div class="uac-modal-head">
                    <h3 id="uacModalTitle">${esc(title)}</h3>
                    <button type="button" class="uac-x" aria-label="Close" onclick="window.__uacClose()">&times;</button>
                </div>
                <div class="uac-modal-body">${bodyHtml}</div>
                <div class="uac-modal-msg" id="uacModalMsg" role="alert"></div>
                <div class="uac-modal-actions">
                    <button type="button" class="uac-btn" onclick="window.__uacClose()">Cancel</button>
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
        if (window.currentUser && (window.currentUser.role_label === 'Super Admin')) await loadCompanies();
        try {
            uac = await api('GET', '/api/iam/overview');
            const sel = document.getElementById('uacCompany');
            if (sel && sel.style.display !== 'none' && !sel.value) sel.value = uac.company_id;
            render();
        } catch (err) {
            usersEl.innerHTML = `<div class="uac-empty uac-error">${esc(err.message)}</div>`;
            document.getElementById('uacInvites').innerHTML = '';
        }
    }

    function render() {
        const can = uac.can || {};
        const inviteBtn = document.getElementById('uacInviteBtn');
        if (inviteBtn) inviteBtn.style.display = can['users.invite'] ? '' : 'none';

        const rows = uac.users.map(u => {
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
        document.getElementById('uacUsers').innerHTML = uac.users.length
            ? `<table class="uac-table"><thead><tr><th>User</th><th>Email</th><th>Access (role &middot; location)</th><th>Status</th><th>Last sign-in</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
            : '<div class="uac-empty">No users yet. Invite someone to get started.</div>';

        const inv = uac.invitations.map(i => {
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
        document.getElementById('uacInvites').innerHTML = uac.invitations.length
            ? `<table class="uac-table"><thead><tr><th>Email</th><th>Role &middot; location</th><th>Status</th><th>Invited by</th><th>Sent</th><th>Expires</th><th></th></tr></thead><tbody>${inv}</tbody></table>`
            : '<div class="uac-empty">No invitations yet.</div>';
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
    window.openInviteModal = function () {
        if (!uac) return;
        modal('Invite a user', `
            <label class="uac-label" for="invEmail">Email</label>
            <input id="invEmail" class="uac-input" type="email" placeholder="name@company.com" autocomplete="off">
            ${roleWarehouseFields('inv')}
            <p class="uac-p uac-muted">They get a link that works once, for 72 hours, to choose their own username and password.</p>`,
            [{ label: 'Send invitation', primary: true, run: async () => {
                const out = await api('POST', '/api/iam/invitations', {
                    email: document.getElementById('invEmail').value.trim(),
                    role_id: document.getElementById('invRole').value,
                    warehouse_id: document.getElementById('invWh').value || null
                });
                await loadUsersAccess();
                if (out.invite_link) showLinkOnce('Invitation created', out.message, out.invite_link);
                else { closeModal(); toast(out.message, 'success'); }
            } }]);
        uacRoleChanged('inv');
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

    window.loadUsersAccess = loadUsersAccess;
})();
