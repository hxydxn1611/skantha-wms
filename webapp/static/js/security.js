/*
 * WARLOG request security (RBAC Phase 2, H9).
 * Adds the session's CSRF token (from the XSRF-TOKEN cookie) to every same-origin
 * request that changes data. Loaded before any other script, so every existing
 * fetch() call in the app gets the header without being changed.
 */
(function () {
    if (window.__warlogCsrfInstalled) return;
    window.__warlogCsrfInstalled = true;

    var SAFE_METHODS = /^(GET|HEAD|OPTIONS)$/i;
    var WAREHOUSE_KEY = 'warlog_warehouse_id';

    /* RBAC Phase 3A: each browser tab keeps its own working warehouse, so switching in
       one tab never changes what another tab is working on. */
    function tabWarehouse() {
        try {
            var v = sessionStorage.getItem(WAREHOUSE_KEY);
            if (!v) {
                var meta = document.querySelector('meta[name="warlog-warehouse-id"]');
                if (meta && meta.content) {
                    v = meta.content;
                    sessionStorage.setItem(WAREHOUSE_KEY, v);
                }
            }
            return v || '';
        } catch (e) { return ''; }
    }

    window.warlogSetTabWarehouse = function (id) {
        try { if (id !== undefined && id !== null && id !== '') sessionStorage.setItem(WAREHOUSE_KEY, String(id)); }
        catch (e) {}
    };
    window.warlogTabWarehouse = tabWarehouse;

    function csrfToken() {
        var m = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function isSameOrigin(url) {
        try { return new URL(url, window.location.href).origin === window.location.origin; }
        catch (e) { return false; }
    }

    var originalFetch = window.fetch;
    window.fetch = function (input, init) {
        try {
            var isRequest = (typeof Request !== 'undefined') && (input instanceof Request);
            var method = (init && init.method) || (isRequest ? input.method : 'GET');
            var url = isRequest ? input.url : String(input);
            if (isSameOrigin(url)) {
                var token = SAFE_METHODS.test(method) ? '' : csrfToken();
                var wh = tabWarehouse();
                if (token || wh) {
                    init = Object.assign({}, init || {});
                    var headers = new Headers(init.headers || (isRequest ? input.headers : undefined));
                    if (token && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', token);
                    if (wh && !headers.has('X-Warehouse-Id')) headers.set('X-Warehouse-Id', wh);
                    init.headers = headers;
                }
            }
        } catch (e) { /* never block a request because of this helper */ }
        var reqMethod = 'GET', reqUrl = '';
        try {
            reqMethod = String((init && init.method) || ((typeof Request !== 'undefined' && input instanceof Request) ? input.method : 'GET')).toUpperCase();
            reqUrl = (typeof Request !== 'undefined' && input instanceof Request) ? input.url : String(input);
        } catch (e) {}
        var retryInit = init;
        return originalFetch.call(this, input, init).then(function (response) {
            // RBAC Phase 7: exceptional actions need a reason - ask once and send it again.
            if (response.status === 400 && !SAFE_METHODS.test(reqMethod) && !(typeof Request !== 'undefined' && input instanceof Request)) {
                return response.clone().json().then(function (body) {
                    if (!body || body.error_code !== 'reason_required') return response;
                    return askReason(body.permission_label || '').then(function (reason) {
                        if (!reason) return response;
                        var next = Object.assign({}, retryInit || {});
                        var h = new Headers(next.headers || undefined);
                        h.set('X-Action-Reason', reason);
                        next.headers = h;
                        return window.fetch(input, next);
                    });
                }).catch(function () { return response; });
            }
            return response;
        }).then(function (response) {
            // RBAC Phase 6: an action the server refused gets a short, plain message.
            // Background reads stay quiet; the Users & Access screens show their own messages.
            if (response.status === 403 && !SAFE_METHODS.test(reqMethod) && reqUrl.indexOf('/api/iam/') === -1
                    && reqUrl.indexOf('/api/platform/') === -1) {
                response.clone().json().then(function (body) {
                    var code = body && body.error_code;
                    if ((code === 'permission_denied' || code === 'read_only_view') && typeof window.warlogToast === 'function') {
                        window.warlogToast(body.message || body.error || "You don't have permission for that.", 'warning');
                    }
                }).catch(function () {});
            }
            // The tab's warehouse is no longer available to this user: fall back to the default.
            if (response.status === 403 && !window.__warlogWarehouseReset) {
                response.clone().json().then(function (body) {
                    if (body && body.error_code === 'warehouse_scope_invalid') {
                        window.__warlogWarehouseReset = true;
                        try { sessionStorage.removeItem(WAREHOUSE_KEY); } catch (e) {}
                        window.location.reload();
                    }
                }).catch(function () {});
            }
            return response;
        });
    };

    window.warlogCsrfToken = csrfToken;

    /* RBAC Phase 7: a small "why?" dialog for exceptional actions. Resolves to the reason,
       or '' when cancelled. */
    function askReason(label) {
        return new Promise(function (resolve) {
            var wrap = document.createElement('div');
            wrap.setAttribute('role', 'dialog');
            wrap.setAttribute('aria-modal', 'true');
            wrap.style.cssText = 'position:fixed;inset:0;z-index:12000;display:flex;align-items:center;justify-content:center;' +
                'padding:16px;background:rgba(15,23,42,0.5);backdrop-filter:blur(3px);font-family:inherit;';
            wrap.innerHTML =
                '<div style="width:100%;max-width:420px;background:var(--panel-bg,#fff);color:var(--text-main,#0f172a);' +
                'border:1px solid var(--border-light,#e2e8f0);border-radius:16px;box-shadow:0 30px 70px rgba(15,23,42,.3);padding:22px 24px;">' +
                '<div style="font-size:1.05rem;font-weight:700;margin-bottom:4px;">Why are you doing this?</div>' +
                '<div class="wl-reason-sub" style="font-size:.82rem;color:var(--text-muted,#64748b);margin-bottom:14px;"></div>' +
                '<textarea maxlength="300" rows="3" style="width:100%;box-sizing:border-box;padding:10px 12px;border-radius:10px;' +
                'border:1px solid var(--border-light,#e2e8f0);background:var(--panel-bg,#fff);color:var(--text-main,#0f172a);' +
                'font:inherit;font-size:.9rem;resize:vertical;margin:0;" placeholder="A short reason, kept in the audit log"></textarea>' +
                '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px;">' +
                '<button type="button" data-a="cancel" style="padding:9px 16px;border-radius:9px;border:1px solid var(--border-light,#e2e8f0);' +
                'background:var(--panel-subtle,#f1f5f9);color:var(--text-main,#0f172a);font-weight:600;cursor:pointer;">Cancel</button>' +
                '<button type="button" data-a="ok" style="padding:9px 16px;border-radius:9px;border:none;background:var(--accent,#2563eb);' +
                'color:#fff;font-weight:600;cursor:pointer;">Continue</button></div></div>';
            wrap.querySelector('.wl-reason-sub').textContent =
                (label ? label + '. ' : '') + 'This is an exceptional action, so it is recorded with your reason.';
            document.body.appendChild(wrap);
            var ta = wrap.querySelector('textarea');
            setTimeout(function () { ta.focus(); }, 30);
            function done(v) { wrap.remove(); resolve(v); }
            wrap.querySelector('[data-a="cancel"]').onclick = function () { done(''); };
            wrap.querySelector('[data-a="ok"]').onclick = function () {
                var v = ta.value.trim();
                if (!v) { ta.focus(); ta.style.borderColor = '#ef4444'; return; }
                done(v);
            };
            ta.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); wrap.querySelector('[data-a="ok"]').click(); }
                if (e.key === 'Escape') done('');
            });
        });
    }
    window.warlogAskReason = askReason;
})();
