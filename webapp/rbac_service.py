"""
Central authorization (RBAC Phase 2). Routes never check roles themselves.

  current_identity()          the validated user for this request (set by auth in before_request)
  current_warehouse_id()      the warehouse the request acts in (Phase 2: the session's assigned
                              warehouse; Phase 3 adds the per-tab X-Warehouse-Id header)
  effective_permissions()     union of the user's active assignments; cached on flask.g
  has_permission(key)         True/False for use inside a handler
  authorize_request()         the before_request check driven by rbac_routes
  require_permission(key)     decorator for handlers that need an extra check
  check_csrf()                double-submit token check for state-changing requests

RBAC_MODE (rbac_config): off -> nothing is checked here; audit -> decisions are logged as
`access.would_deny`, nothing is blocked; enforce -> 403 (missing permission) / 400 (missing
reason) / 403 (bad CSRF token).
"""
from __future__ import annotations

import functools
import hmac
import logging
import secrets
import threading
import time
from typing import Any, Dict, FrozenSet, Optional

from flask import g, jsonify, request, session

import auth_service
import db
import rbac_catalog
import rbac_config
import rbac_routes

logger = logging.getLogger(__name__)

CSRF_COOKIE = "XSRF-TOKEN"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DENY_LOG_INTERVAL_S = 600
_deny_log_seen: Dict[tuple, float] = {}
_deny_lock = threading.Lock()


def mode() -> str:
    return rbac_config.get_rbac_mode()


# ----------------------------------------------------------------------------- identity / scope
def current_identity() -> Optional[Dict[str, Any]]:
    return getattr(g, "current_user", None)


def accessible_warehouses(user: Optional[Dict[str, Any]] = None) -> list:
    """Warehouses this user may work in: every warehouse for the Platform Admin; otherwise all
    warehouses of companies where the user has a company-wide assignment, plus warehouses with a
    warehouse-level assignment. Suspended companies are excluded."""
    user = user or current_identity()
    if not user:
        return []
    cache_key = ("rbac_accessible", user["id"])
    cached = getattr(g, "rbac_accessible_cache", None)
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    conn = db.get_db()
    try:
        cols = "w.*"
        if user.get("is_platform_admin"):
            rows = conn.execute(f"""
                SELECT {cols} FROM warehouses w LEFT JOIN companies c ON c.id = w.company_id
                ORDER BY w.company_name, w.code""").fetchall()
        else:
            rows = conn.execute(f"""
                SELECT DISTINCT {cols} FROM warehouses w
                JOIN companies c ON c.id = w.company_id AND c.status = 'Active'
                JOIN user_warehouse_access a ON a.company_id = w.company_id AND a.user_id = ? AND a.status = 'Active'
                     AND (a.warehouse_id IS NULL OR a.warehouse_id = w.id)
                JOIN roles r ON r.id = a.role_id AND r.is_active = 1
                ORDER BY w.code""", (user["id"],)).fetchall()
    finally:
        conn.close()
    result = [dict(r) for r in rows]
    g.rbac_accessible_cache = (cache_key, result)
    return result


def has_company_wide_access(user: Dict[str, Any], company_id: Optional[int]) -> bool:
    if user.get("is_platform_admin"):
        return True
    conn = db.get_db()
    try:
        return conn.execute("""
            SELECT 1 FROM user_warehouse_access a JOIN roles r ON r.id = a.role_id AND r.is_active = 1
            WHERE a.user_id = ? AND a.company_id = ? AND a.status = 'Active' AND a.warehouse_id IS NULL
        """, (user["id"], company_id)).fetchone() is not None
    finally:
        conn.close()


def default_warehouse_id(user: Dict[str, Any], assigned_code: Optional[str] = None) -> Optional[int]:
    """The assigned warehouse if the user may use it, otherwise the first one they may use."""
    whs = accessible_warehouses(user)
    if assigned_code:
        for w in whs:
            if (w["code"] or "").upper() == assigned_code.upper():
                return w["id"]
    if user.get("is_platform_admin"):
        own = auth_service.user_company_id(user["id"])
        for w in whs:
            if w["company_id"] == own:
                return w["id"]
    return whs[0]["id"] if whs else None


def resolve_scope():
    """Decides which company/warehouse this request works in (RBAC Phase 3A, H11).

    Order: the tab's X-Warehouse-Id header (validated), then the session default, then the
    user's assigned warehouse. 'all' = this company's warehouses, read-only (D13);
    '*' = every company, Platform Admin only, read-only. Returns an error response or None."""
    import rbac_scope
    user = current_identity()
    if not user:
        return None
    header = (request.headers.get("X-Warehouse-Id") or "").strip()
    requested = header or str(session.get("warehouse_id") or "")
    whs = {w["id"]: w for w in accessible_warehouses(user)}
    own_company = auth_service.user_company_id(user["id"])
    scope = None
    if user.get("is_platform_admin"):
        # Platform Admin keeps full access to everything (read and write, every company).
        # The selected warehouse only decides where new, ownerless records are filed.
        wid = int(requested) if requested.isdigit() and int(requested) in whs else None
        if wid is None:
            wid = default_warehouse_id(user, (session.get("user") or {}).get("assigned_warehouse_code"))
        home = whs.get(wid) if wid else None
        if home is not None:
            session["warehouse_id"] = wid
        scope = rbac_scope.Scope.platform_full(home["company_id"] if home else None, wid if home else None)
        g.rbac_scope = scope
        g.rbac_warehouse_id = scope.warehouse_id
        rbac_scope.set_scope(scope)
        return None
    if requested == "*":
        if user.get("is_platform_admin"):
            scope = rbac_scope.Scope.platform_all()
    elif requested == "all":
        if own_company and has_company_wide_access(user, own_company):
            scope = rbac_scope.Scope.company_all(own_company)
    elif requested.isdigit() and int(requested) in whs:
        w = whs[int(requested)]
        if w["company_id"] is not None:
            scope = rbac_scope.Scope.warehouse(w["company_id"], w["id"])
    if scope is None and header:
        return _deny(403, "warehouse_scope_invalid", "You don't have access to that warehouse.")
    if scope is None:
        wid = default_warehouse_id(user, (session.get("user") or {}).get("assigned_warehouse_code"))
        if wid and whs.get(wid, {}).get("company_id") is not None:
            scope = rbac_scope.Scope.warehouse(whs[wid]["company_id"], wid)
            session["warehouse_id"] = wid
    g.rbac_scope = scope
    g.rbac_warehouse_id = scope.warehouse_id if scope else None
    rbac_scope.set_scope(scope)
    return None


def client_access(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the page needs to hide controls (RBAC Phase 6). Only a convenience for the UI:
    every API still checks permissions itself."""
    if not user:
        return {"permissions": [], "all": False, "is_platform_admin": False, "scope": None,
                "company_wide": False}
    perms = effective_permissions()
    company_perms = {k for k, p in rbac_catalog.PERMISSIONS_BY_KEY.items() if p.scope_level != "platform"}
    scope = current_scope()
    own_company = auth_service.user_company_id(user["id"])
    return {
        "permissions": sorted(perms),
        # everything inside the company: nothing in the UI needs hiding
        "all": bool(user.get("is_platform_admin")) or company_perms <= set(perms),
        "is_platform_admin": bool(user.get("is_platform_admin")),
        "scope": scope.kind if scope else None,
        "company_wide": bool(own_company) and has_company_wide_access(user, own_company),
    }


def current_scope():
    return getattr(g, "rbac_scope", None)


def current_warehouse_id() -> Optional[int]:
    if "rbac_warehouse_id" in g:
        return g.rbac_warehouse_id
    code = (session.get("user") or {}).get("assigned_warehouse_code")
    wid = None
    if code:
        conn = db.get_db()
        try:
            row = conn.execute("SELECT id FROM warehouses WHERE UPPER(code) = UPPER(?)", (code,)).fetchone()
            wid = row[0] if row else None
        finally:
            conn.close()
    g.rbac_warehouse_id = wid
    return wid


def permissions_for_user(user_id: int, is_platform_admin: bool, warehouse_id: Optional[int]) -> FrozenSet[str]:
    """Union of permissions from the user's active assignments that apply to `warehouse_id`
    (company-wide assignments always apply). Suspended companies and inactive roles grant nothing."""
    perms = set(rbac_catalog.builtin_permissions("platform_admin")) if is_platform_admin else set()
    conn = db.get_db()
    try:
        rows = conn.execute("""
            SELECT r.id, r.builtin_code
            FROM user_warehouse_access a
            JOIN roles r ON r.id = a.role_id AND r.is_active = 1
            JOIN companies c ON c.id = a.company_id AND c.status = 'Active'
            WHERE a.user_id = ? AND a.status = 'Active'
              AND (a.warehouse_id IS NULL OR a.warehouse_id = ?)
        """, (user_id, warehouse_id)).fetchall()
        custom_ids = []
        for role_id, builtin in rows:
            if builtin:
                perms |= rbac_catalog.builtin_permissions(builtin)
            else:
                custom_ids.append(role_id)
        if custom_ids:
            q = ",".join("?" * len(custom_ids))
            for (key,) in conn.execute(f"""
                SELECT rp.permission_key FROM role_permissions rp
                JOIN permissions p ON p.key = rp.permission_key AND p.retired = 0
                WHERE rp.role_id IN ({q})
            """, tuple(custom_ids)):
                spec = rbac_catalog.PERMISSIONS_BY_KEY.get(key)
                if spec and (spec.scope_level != "platform" or is_platform_admin):
                    perms.add(key)
    finally:
        conn.close()
    return frozenset(perms)


def effective_permissions() -> FrozenSet[str]:
    if "rbac_permissions" in g:
        return g.rbac_permissions
    user = current_identity()
    if not user:
        g.rbac_permissions = frozenset()
    else:
        g.rbac_permissions = permissions_for_user(user["id"], bool(user.get("is_platform_admin")),
                                                  current_warehouse_id())
    return g.rbac_permissions


def has_permission(key: str) -> bool:
    return key in effective_permissions()


# ----------------------------------------------------------------------------- decisions
def reason_needed(endpoint: Optional[str], key: Optional[str]) -> bool:
    """Exceptional actions need a written reason (Phase 7). A preview never does."""
    if request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict) and body.get("preview") is True:
            return False
    return (endpoint in rbac_routes.REASON_REQUIRED_ENDPOINTS
            or (key is not None and key in rbac_catalog.REASON_PERMISSIONS))


def _request_reason() -> str:
    reason = request.headers.get("X-Action-Reason") or ""
    if not reason and request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            reason = str(body.get("reason") or "")
    return reason.strip()


def _log_decision(action: str, key: Optional[str], detail: str, result: str) -> None:
    user = current_identity() or {}
    sig = (action, user.get("id"), request.endpoint, key)
    now = time.monotonic()
    with _deny_lock:
        last = _deny_log_seen.get(sig)
        if last is not None and now - last < _DENY_LOG_INTERVAL_S:
            return
        _deny_log_seen[sig] = now
    auth_service.audit(action, actor=user, company_id=auth_service.user_company_id(user["id"]) if user else None,
                       warehouse_id=current_warehouse_id() if user else None,
                       resource_type="route", resource_id=f"{request.method} {request.path}",
                       reason=detail, after={"permission": key, "endpoint": request.endpoint, "mode": mode()},
                       ip=request.remote_addr, result=result)


def _deny(status: int, code: str, message: str, key: Optional[str] = None):
    body = {"success": False, "error": message, "message": message, "error_code": code}
    if key:
        body["permission"] = key
        spec = rbac_catalog.PERMISSIONS_BY_KEY.get(key)
        if spec:
            body["permission_label"] = spec.label
    return jsonify(body), status


def decide(endpoint: Optional[str], method: str):
    """Returns (allowed, key, reason_code) for this endpoint and method."""
    if endpoint is None or endpoint in rbac_routes.PUBLIC_ENDPOINTS or endpoint in rbac_routes.AUTHENTICATED_ENDPOINTS:
        return True, None, None
    key = rbac_routes.permission_for(endpoint, method)
    if key is None:
        return False, None, "unmapped_route"
    held = effective_permissions()
    keys = rbac_routes.permission_keys(key)
    granted = next((k for k in keys if k in held), None)
    if granted:
        return True, granted, None
    return False, keys[0], "permission_denied"


def authorize_request():
    """Called from before_request once the session has been validated."""
    if mode() == "off":
        return None
    endpoint = request.endpoint
    allowed, key, why = decide(endpoint, request.method)
    enforcing = mode() == "enforce"
    if not allowed:
        _log_decision("access.denied" if enforcing else "access.would_deny", key, why or "", "denied")
        if enforcing:
            if why == "unmapped_route":
                return _deny(403, "permission_denied", "This action is not available.")
            spec = rbac_catalog.PERMISSIONS_BY_KEY.get(key)
            return _deny(403, "permission_denied",
                         f"You don't have permission: {spec.label if spec else key}.", key)
        return None

    spec = rbac_catalog.PERMISSIONS_BY_KEY.get(key) if key else None
    if request.method not in SAFE_METHODS and reason_needed(endpoint, key) and not _request_reason():
        # Phase 7: required in every mode (the page asks "why?" and sends it again)
        _log_decision("access.reason_missing", key, "reason required", "denied")
        return _deny(400, "reason_required", "Please give a short reason for this action.", key)
    if spec and spec.sensitive and request.method not in SAFE_METHODS:
        user = current_identity() or {}
        auth_service.audit("access.sensitive", actor=user, company_id=auth_service.user_company_id(user.get("id")) if user else None,
                           warehouse_id=current_warehouse_id(), resource_type="route",
                           resource_id=f"{request.method} {request.path}", reason=_request_reason() or None,
                           after={"permission": key}, ip=request.remote_addr)
    return None


def check_permission(key: str, *, reason_required: bool = False):
    """For use inside a handler: returns an error response to send, or None to continue."""
    if mode() == "off":
        return None
    enforcing = mode() == "enforce"
    if key not in effective_permissions():
        _log_decision("access.denied" if enforcing else "access.would_deny", key, "permission_denied", "denied")
        if enforcing:
            spec = rbac_catalog.PERMISSIONS_BY_KEY.get(key)
            return _deny(403, "permission_denied", f"You don't have permission: {spec.label if spec else key}.", key)
        return None
    if reason_required and not _request_reason():
        _log_decision("access.reason_missing", key, "reason required", "denied")
        return _deny(400, "reason_required", "Please give a short reason for this action.", key)
    return None


def require_permission(key: str, *, reason_required: bool = False):
    """Decorator for handlers that need a permission beyond the route map."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            denied = check_permission(key, reason_required=reason_required)
            return denied if denied is not None else fn(*args, **kwargs)
        return inner
    return wrap


# ----------------------------------------------------------------------------- record ownership (H13, H14)
_ID_FIELDS = {
    # URL parameter or body field -> (table, column) alternatives that identify a record
    "gp_id": [("gate_passes", "id")], "pass_id": [("gate_passes", "id")], "gate_pass_id": [("gate_passes", "id")],
    "po_number": [("expected_deliveries", "po_number")],
    "bin_id": [("bins", "bin_id")], "source_bin": [("bins", "bin_id")], "target_bin": [("bins", "bin_id")],
    "from_bin": [("bins", "bin_id")], "to_bin": [("bins", "bin_id")], "assigned_bin_id": [("bins", "bin_id")],
    "sku_id": [("skus", "sku_id")],
    "pallet_id": [("pallets", "pallet_id")],
    "camera_id": [("cameras", "camera_id"), ("cameras", "camera_code")],
    "cam_id": [("cameras", "camera_id"), ("cameras", "camera_code")],
    "order_id": [("outbound_orders", "id")],
    "violation_id": [("violations_log", "id")],
    "inv_id": [("inventory", "id")],
    "worker_code": [("trained_workers", "worker_code")],
    "image_id": [("sku_images", "id")],
    "profile_id": [("glass_measurement_profiles", "id")],
    "zone_id": [("vision_zones", "id")],
}
# (endpoint, method, field) of "create" requests: a code that belongs to someone else is
# answered with 409 "already in use" instead of 404 (it never says whose it is).
_CREATE_CODE_FIELDS = {
    ("api_add_sku", "POST", "sku_id"): "SKU code",
    ("api_add_bin", "POST", "bin_id"): "Bin",
    ("handle_deliveries", "POST", "po_number"): "PO number",
    ("add_camera", "POST", "camera_id"): "Camera ID",
}
_ENDPOINT_ARGS = {
    "handle_single_object_class": {"identifier": [("object_classes", "id"), ("object_classes", "code")]},
    "handle_single_vision_zone": {"identifier": [("vision_zones", "id"), ("vision_zones", "zone_code")]},
    "handle_vision_zone_cameras": {"identifier": [("vision_zones", "id"), ("vision_zones", "zone_code")]},
}


def _named_records():
    """(name, value) pairs for every record a request names in its URL, JSON body or form."""
    pairs = list((request.view_args or {}).items())
    body = request.get_json(silent=True) if request.is_json else None
    if isinstance(body, dict):
        pairs += [(k, v) for k, v in body.items() if k in _ID_FIELDS]
        params = body.get("params")
        if isinstance(params, dict):
            pairs += [(k, v) for k, v in params.items() if k in _ID_FIELDS]
            if request.endpoint == "api_copilot_action" and params.get("id"):
                pairs.append(("gp_id", params.get("id")))
    if request.form:
        pairs += [(k, v) for k, v in request.form.items() if k in _ID_FIELDS]
    return pairs


def check_record_scope():
    """404 when the request names a record that exists but belongs to another company/warehouse.
    Runs before the handler, so single-record reads and writes can't cross scopes (Phase 3A)."""
    import rbac_scope
    scope = current_scope()
    if scope is None or scope.unrestricted or not rbac_scope.isolation_enabled():
        return None
    pairs = _named_records()
    if not pairs:
        return None
    special = _ENDPOINT_ARGS.get(request.endpoint, {})
    conn = db.get_db()
    try:
        for name, value in pairs:
            if value in (None, "") or isinstance(value, (dict, list)):
                continue
            for table, column in special.get(name) or _ID_FIELDS.get(name, []):
                if not rbac_scope.owned_or_absent(conn, table, column, value):
                    _log_decision("access.out_of_scope", None, f"{name}={value}", "denied")
                    label = _CREATE_CODE_FIELDS.get((request.endpoint, request.method, name))
                    if label:
                        # Phase 3B: creating a record with a code someone else uses
                        return _deny(409, "code_in_use",
                                     f"{label} '{value}' is already in use. Please choose a different code.")
                    return _deny(404, "not_found", "Not found.")
    finally:
        conn.close()
    return None


_FILE_OWNER_COLUMNS = [
    ("sku_images", "file_path"), ("gate_passes", "photo"), ("gate_passes", "driver_photo"),
]


def check_file_scope(path: str):
    """RBAC Phase 3A (H5): a file that belongs to a record (SKU image, gate pass photo,
    invoice, pallet label) is served only within that record's scope. Files no record
    points to (temporary previews, snapshots) need only a signed-in session."""
    import os
    import rbac_scope
    scope = current_scope()
    if scope is None or scope.unrestricted or not rbac_scope.isolation_enabled():
        return None
    name = os.path.basename(path)
    checks = [(t, c, v) for t, c in _FILE_OWNER_COLUMNS for v in (path, path.lstrip("/"), name)]
    if path.startswith("/static/invoices/"):
        checks.append(("invoices", "pdf_path", name))
        if name.startswith("Pallet_Label_") and name.endswith(".pdf"):
            checks.append(("pallets", "pallet_id", name[len("Pallet_Label_"):-4]))
        if name.startswith("invoice_") and name.endswith(".pdf"):
            checks.append(("gate_passes", "id", name[len("invoice_"):-4]))
    conn = db.get_db()
    try:
        for table, column, value in checks:
            if not rbac_scope.owned_or_absent(conn, table, column, value):
                _log_decision("access.out_of_scope", None, f"file {path}", "denied")
                return _deny(404, "not_found", "Not found.")
    finally:
        conn.close()
    return None


# ----------------------------------------------------------------------------- CSRF (H9)
def csrf_token() -> str:
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf"] = tok
    return tok


def check_csrf():
    """Double-submit check on state-changing requests from signed-in sessions."""
    if mode() == "off" or request.method in SAFE_METHODS:
        return None
    if request.endpoint in rbac_routes.PUBLIC_ENDPOINTS:
        return None
    expected = session.get("csrf") or ""
    sent = request.headers.get(CSRF_HEADER) or ""
    if expected and sent and hmac.compare_digest(expected, sent):
        return None
    enforcing = mode() == "enforce"
    _log_decision("security.csrf_failed" if enforcing else "security.csrf_missing", None,
                  "missing" if not sent else "mismatch", "denied" if enforcing else "warning")
    if enforcing:
        return _deny(403, "csrf_failed", "Security token missing or expired. Reload the page and try again.")
    return None


def set_csrf_cookie(response):
    """Exposes the session's CSRF token to the page's JavaScript (not HttpOnly by design)."""
    if session.get("user") and session.get("csrf"):
        if request.cookies.get(CSRF_COOKIE) != session["csrf"]:
            response.set_cookie(CSRF_COOKIE, session["csrf"], samesite="Lax", httponly=False,
                                secure=request.is_secure, path="/")
    return response
