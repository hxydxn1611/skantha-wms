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
            if (!SAFE_METHODS.test(method) && isSameOrigin(url)) {
                var token = csrfToken();
                if (token) {
                    init = Object.assign({}, init || {});
                    var headers = new Headers(init.headers || (isRequest ? input.headers : undefined));
                    if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', token);
                    init.headers = headers;
                }
            }
        } catch (e) { /* never block a request because of this helper */ }
        return originalFetch.call(this, input, init);
    };

    window.warlogCsrfToken = csrfToken;
})();
