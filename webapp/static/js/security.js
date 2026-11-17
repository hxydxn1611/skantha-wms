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
        return originalFetch.call(this, input, init).then(function (response) {
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
})();
