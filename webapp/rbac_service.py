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
    return (key in effective_permissions()), key, None if key in effective_permissions() else "permission_denied"


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
    if endpoint in rbac_routes.REASON_REQUIRED_ENDPOINTS and request.method not in SAFE_METHODS:
        if not _request_reason():
            _log_decision("access.reason_missing", key, "reason required", "denied" if enforcing else "warning")
            if enforcing:
                return _deny(400, "reason_required", "A reason is required for this action.", key)
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
        _log_decision("access.reason_missing", key, "reason required", "denied" if enforcing else "warning")
        if enforcing:
            return _deny(400, "reason_required", "A reason is required for this action.", key)
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
