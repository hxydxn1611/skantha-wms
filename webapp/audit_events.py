"""
Audit trail for gate, stock and configuration changes (RBAC Phase 7).

One layer around the request cycle instead of edits in ~100 handlers:

  before_request  -> snapshot(): for a mapped write, load the record it touches (before)
  after_request   -> record():   if the response succeeded, load it again (after) and write
                                 one audit_logs row: who, company, warehouse, action, record,
                                 reason, before/after.

Only the fields listed per record type are stored, so passwords, OTPs, tokens and camera
stream URLs (which can contain camera passwords) never reach the audit log. Background
services write their own rows as actor 'system:<service>' (see vision_runtime_service).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from flask import g, request

import auth_service
import db

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- record loaders
_FIELDS = {
    "gate_pass": ("id", "status", "dock", "plate", "po_number", "activity", "driver_name", "type"),
    "delivery": ("po_number", "status", "vendor", "plate", "expected_date", "activity"),
    "inventory": ("id", "bin_id", "sku_id", "quantity", "batch_number"),
    "camera": ("camera_id", "name", "location", "bin_id", "camera_type", "vendor", "status"),
    "pallet": ("pallet_id", "sku_id", "status", "counted_bundles", "total_units", "target_bundles"),
    "bin": ("bin_id", "zone", "status", "max_volume", "max_weight"),
    "sku": ("sku_id", "name", "category", "status", "units_per_bundle", "target_bundles_per_pallet"),
}
_TABLES = {
    "gate_pass": ("gate_passes", "id"), "delivery": ("expected_deliveries", "po_number"),
    "inventory": ("inventory", "id"), "camera": ("cameras", "camera_id"), "pallet": ("pallets", "pallet_id"),
    "bin": ("bins", "bin_id"), "sku": ("skus", "sku_id"),
}


def _load(rtype: str, rid: Any) -> Optional[Dict[str, Any]]:
    if rid in (None, "") or rtype not in _TABLES:
        return None
    table, col = _TABLES[rtype]
    conn = db.get_db()
    try:
        row = conn.execute(f"SELECT * FROM {table} WHERE {col} = ?", (rid,)).fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    return {k: d.get(k) for k in _FIELDS[rtype] if k in d}


# ----------------------------------------------------------------------------- what is audited
# endpoint -> {method or '*': (action, record type, id sources)}
# id sources: 'arg:<url arg>', 'body:<json key>', 'resp:<dotted path in the JSON response>'
GATE_STATUS_ACTIONS = {
    "Approved": "gate.entry_approved", "Rejected": "gate.entry_rejected", "Sent to Dock": "gate.dock_admitted",
    "Unloading": "gate.unloading_started", "Unloaded": "gate.unloaded", "Checkout Approved": "gate.checkout_approved",
    "Departed": "gate.checkout_completed", "Completed": "gate.checkout_completed", "Exited": "gate.checkout_completed",
}

_GP = ("arg:gp_id", "body:gp_id", "body:id", "resp:gate_pass.id", "resp:id")
EVENTS: Dict[str, Dict[str, Tuple[str, Optional[str], Tuple[str, ...]]]] = {
    # gate
    "verify_otp": {"POST": ("gate.otp_verified", "gate_pass", _GP)},
    "approve_all_matched_passes": {"POST": ("gate.entry_bulk_approved", None, ())},
    "update_gate_pass": {"PUT": ("gate.pass_updated", "gate_pass", _GP),
                         "DELETE": ("gate.pass_deleted", "gate_pass", _GP)},
    "checkout": {"POST": ("gate.checkout_completed", "gate_pass", _GP)},
    "checkout_gate_pass": {"POST": ("gate.checkout_completed", "gate_pass", _GP)},
    "create_gate_pass": {"POST": ("gate.pass_created", "gate_pass", _GP)},
    "register_walkin_vehicle": {"POST": ("gate.pass_created", "gate_pass", _GP)},
    "gate_auto_dispatch_toggle": {"POST": ("gate.auto_dispatch_changed", None, ())},
    "simulate_gate_arrival": {"POST": ("gate.simulated_arrival", "gate_pass", _GP)},
    "unload_step": {"POST": ("dock.unload_step", "gate_pass", _GP)},
    "auto_add_step": {"POST": ("dock.unload_step", "gate_pass", _GP)},
    "api_copilot_action": {"POST": ("copilot.action", "gate_pass", ("body:params.id", "resp:gate_pass_id"))},
    # deliveries
    "handle_deliveries": {"POST": ("delivery.created", "delivery", ("body:po_number", "resp:delivery.po_number"))},
    "handle_single_delivery": {"PUT": ("delivery.updated", "delivery", ("arg:po_number",)),
                               "PATCH": ("delivery.updated", "delivery", ("arg:po_number",)),
                               "DELETE": ("delivery.deleted", "delivery", ("arg:po_number",))},
    # stock
    "update_inventory": {"PUT": ("inventory.adjusted", "inventory", ("arg:inv_id",))},
    "api_transfer_vision_inventory": {"POST": ("inventory.transferred", None, ())},
    "sync_camera_inventory": {"POST": ("inventory.adjusted", "camera", ("arg:camera_id",))},
    "api_sync_audit_count": {"POST": ("inventory.adjusted", None, ())},
    "run_cycle_count": {"POST": ("cyclecount.submitted", "bin", ("body:bin_id",))},
    "api_inbound_complete_receipt": {"POST": ("inbound.receipt_completed", "gate_pass", _GP)},
    "pick_outbound": {"POST": ("outbound.dispatched", None, ())},
    "handle_outbound": {"POST": ("outbound.created", None, ())},
    "api_create_pallet": {"POST": ("pallet.created", "pallet", ("resp:pallet.pallet_id", "resp:pallet_id"))},
    "api_seal_pallet": {"POST": ("pallet.sealed", "pallet", ("arg:pallet_id",))},
    "api_delete_pallet": {"DELETE": ("pallet.deleted", "pallet", ("arg:pallet_id",))},
    "api_add_bin": {"POST": ("bin.created", "bin", ("body:bin_id",))},
    "api_update_bin": {"*": ("bin.updated", "bin", ("arg:bin_id",))},
    # master data
    "api_add_sku": {"POST": ("sku.created", "sku", ("body:sku_id",))},
    "api_save_sku": {"POST": ("sku.saved", "sku", ("body:sku_id",))},
    "api_delete_sku": {"DELETE": ("sku.deleted", "sku", ("arg:sku_id",))},
    "api_confirm_sku_excel_import": {"POST": ("sku.imported", None, ())},
    "api_apply_industry_blueprint": {"POST": ("masterdata.blueprint_applied", None, ())},
    # configuration
    "add_camera": {"POST": ("camera.created", "camera", ("body:camera_id", "resp:camera.camera_id", "resp:camera_id"))},
    "delete_camera": {"DELETE": ("camera.deleted", "camera", ("arg:camera_id",))},
    "assign_camera_bin": {"POST": ("camera.configured", "camera", ("arg:camera_id",))},
    "toggle_camera_freeze": {"POST": ("camera.configured", "camera", ("arg:camera_id",))},
    "handle_vision_camera_config": {"*": ("camera.configured", "camera", ("arg:camera_id",))},
    "camera_ptz_endpoint": {"POST": ("camera.ptz", "camera", ("arg:camera_id",))},
    "api_detection_config": {"*": ("vision.runtime_changed", None, ())},
    "api_vision_runtime_start_all": {"POST": ("vision.runtime_changed", None, ())},
    "api_vision_runtime_stop_all": {"POST": ("vision.runtime_changed", None, ())},
    "api_vision_runtime_camera_start": {"POST": ("vision.runtime_changed", "camera", ("arg:camera_id",))},
    "api_vision_runtime_camera_stop": {"POST": ("vision.runtime_changed", "camera", ("arg:camera_id",))},
    "api_vision_runtime_camera_restart": {"POST": ("vision.runtime_changed", "camera", ("arg:camera_id",))},
    "handle_vision_zones": {"POST": ("vision.zone_created", None, ())},
    "handle_single_vision_zone": {"*": ("vision.zone_changed", None, ())},
    "handle_object_classes": {"POST": ("vision.class_created", None, ())},
    "handle_single_object_class": {"*": ("vision.class_changed", None, ())},
    "api_staging_configure": {"POST": ("staging.configured", None, ())},
    "api_staging_reset": {"POST": ("staging.reset", None, ())},
    "api_create_warehouse": {"POST": ("warehouse.created", None, ())},
    "api_switch_warehouse": {"POST": ("warehouse.switched", None, ())},
}

# request fields worth keeping when there is no record snapshot (never secrets)
_SAFE_BODY_KEYS = ("action", "bin_id", "sku_id", "quantity", "from_bin", "to_bin", "source_bin", "target_bin",
                   "status", "dock", "enabled", "code", "name", "zone_code", "camera_id", "pallet_id", "po_number",
                   "warehouse_code", "blueprint_key", "include_samples", "direction", "zoom", "order_id")
_SECRET_HINTS = ("password", "otp", "token", "secret", "url", "api_key")


def _event() -> Optional[Tuple[str, Optional[str], Tuple[str, ...]]]:
    spec = EVENTS.get(request.endpoint or "")
    if not spec:
        return None
    return spec.get(request.method) or spec.get("*")


def _dig(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _resolve_id(sources, response_json=None) -> Any:
    body = request.get_json(silent=True) if request.is_json else None
    for src in sources:
        kind, _, name = src.partition(":")
        val = None
        if kind == "arg":
            val = (request.view_args or {}).get(name)
        elif kind == "body" and isinstance(body, dict):
            val = _dig(body, name)
        elif kind == "resp" and isinstance(response_json, dict):
            val = _dig(response_json, name)
        if val not in (None, ""):
            return val
    return None


def _safe_body() -> Optional[Dict[str, Any]]:
    body = request.get_json(silent=True) if request.is_json else None
    if not isinstance(body, dict):
        return None
    out = {}
    for k in _SAFE_BODY_KEYS:
        if k in body and not any(h in k.lower() for h in _SECRET_HINTS):
            v = body[k]
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v if not isinstance(v, str) else v[:200]
    return out or None


def snapshot() -> None:
    """before_request: remember the record as it is before the change."""
    ev = _event()
    if not ev:
        return
    action, rtype, sources = ev
    g.audit_event = ev
    g.audit_before = _load(rtype, _resolve_id(sources)) if rtype else None


def record(response) -> None:
    """after_request: one audit row per successful mapped write. Never breaks the response."""
    ev = g.pop("audit_event", None)
    if not ev or response.status_code >= 400:
        return
    try:
        action, rtype, sources = ev
        resp_json = None
        if response.is_json:
            try:
                resp_json = response.get_json(silent=True)
            except Exception:
                resp_json = None
        if isinstance(resp_json, dict) and resp_json.get("success") is False:
            return
        rid = _resolve_id(sources, resp_json)
        before = g.pop("audit_before", None)
        after = _load(rtype, rid) if rtype else None
        if rtype == "gate_pass" and before and after and before.get("status") != after.get("status"):
            action = GATE_STATUS_ACTIONS.get(after.get("status"), action)
        if after is None and before is None:
            after = _safe_body()
        import rbac_service
        user = g.get("current_user") or {}
        auth_service.audit(
            action, actor=user, company_id=auth_service.user_company_id(user["id"]) if user.get("id") else None,
            warehouse_id=rbac_service.current_warehouse_id() if user else None,
            resource_type=rtype or (request.endpoint or ""), resource_id=str(rid) if rid not in (None, "") else None,
            reason=rbac_service._request_reason() or None, before=before, after=after,
            ip=request.remote_addr, user_agent=request.headers.get("User-Agent"))
    except Exception as e:  # auditing must never break a response
        logger.warning(f"[AUDIT] could not record {request.endpoint}: {e}")


def system_event(service: str, action: str, *, company_id=None, warehouse_id=None, resource_type=None,
                 resource_id=None, after=None, reason=None) -> None:
    """Background services (ANPR, auto-dispatch ...) record what they did as 'system:<service>'."""
    auth_service.audit(action, actor_username=f"system:{service}", company_id=company_id, warehouse_id=warehouse_id,
                       resource_type=resource_type, resource_id=str(resource_id) if resource_id is not None else None,
                       after=after, reason=reason, result="success")
