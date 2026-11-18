"""
Stock history: who changed which stock, when, and why (Inventory section).

Every change to the `inventory` table writes one `stock_movements` row through database
triggers (migration rbac_v1/012_stock_ledger), whatever code made it: receiving, picking,
cycle counts, camera sync, controlled actions or the Inventory screen. Those rows start
without a person. This module fills that in from the request that caused them:

  begin()        before a write request: remember the newest history row
  finish(resp)   after it succeeded: rows added since then get the signed-in person,
                 the screen/endpoint that did it, a plain movement type and the reason

Background work (camera threads, schedulers) has no request, so its rows stay
'system'. Nothing here runs inside camera frame loops.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from flask import g, request

import db

logger = logging.getLogger(__name__)

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# endpoint -> movement type shown in the history ("created/change/removed" are the raw kinds)
ENDPOINT_TYPES = {
    "update_inventory": "adjust",
    "update_gate_pass": "receive",
    "unload_step": "receive",
    "auto_add_step": "receive",
    "api_inbound_complete_receipt": "receive",
    "pick_outbound": "pick",
    "run_cycle_count": "cycle_count",
    "api_sync_audit_count": "count_sync",
    "sync_camera_inventory": "count_sync",
    "api_transfer_vision_inventory": "vision_transfer",
    "api_controlled_actions_execute": "controlled_action",
    "api_apply_industry_blueprint": "demo_seed",
    "api_copilot_action": "copilot",
}

TYPE_LABELS = {
    "adjust": "Adjustment", "transfer_out": "Transfer out", "transfer_in": "Transfer in", "receive": "Received",
    "pick": "Picked / dispatched", "cycle_count": "Cycle count", "count_sync": "Count sync",
    "vision_transfer": "AI count posted", "controlled_action": "Controlled action", "demo_seed": "Demo data",
    "copilot": "Copilot action", "created": "New stock line", "change": "Quantity changed", "removed": "Line removed",
}


def _newest_id(conn) -> Optional[int]:
    try:
        return conn.execute("SELECT COALESCE(MAX(id), 0) FROM stock_movements").fetchone()[0]
    except sqlite3.OperationalError:   # table not created yet (before migration 012)
        return None


def mark(conn) -> Optional[int]:
    """The newest history row id; rows after it belong to the work that follows."""
    return _newest_id(conn)


def stamp(conn, after_id: int, actor: str, source: str, movement_type: Optional[str] = None,
          reason: Optional[str] = None, ref: Optional[str] = None, only_unowned: bool = True) -> int:
    """Puts the person/endpoint/type/reason on history rows added after `after_id`."""
    cond = " AND actor IS NULL" if only_unowned else ""
    cur = conn.execute(f"""
        UPDATE stock_movements
           SET actor = ?, source = ?,
               movement_type = CASE WHEN ? IS NOT NULL AND movement_type IN ('created', 'change', 'removed')
                                    THEN ? ELSE movement_type END,
               reason = COALESCE(reason, ?), ref = COALESCE(ref, ?)
         WHERE id > ?{cond}""", (actor, source, movement_type, movement_type, reason, ref, after_id))
    return cur.rowcount or 0


def _actor() -> str:
    user = g.get("current_user") or {}
    return str(user.get("username") or "unknown")


def begin() -> None:
    """Before a write request (after authentication): remember where the history stands."""
    if request.method not in _WRITE_METHODS or not request.path.startswith("/api/"):
        return
    if (request.endpoint or "").startswith("stock."):
        return   # the Inventory screen stamps its own rows inside its transaction
    try:
        conn = db.get_db()
        try:
            g.stock_mark = _newest_id(conn)
        finally:
            conn.close()
    except Exception as e:   # never block a request over the history
        logger.debug(f"[StockLedger] mark skipped: {e}")


def finish(response) -> None:
    """After a successful write request: name the person on the history rows it created."""
    after_id = g.pop("stock_mark", None) if "stock_mark" in g else None
    if after_id is None or response.status_code >= 400:
        return
    try:
        conn = db.get_db()
        try:
            if conn.execute("SELECT 1 FROM stock_movements WHERE id > ? AND actor IS NULL LIMIT 1",
                            (after_id,)).fetchone() is None:
                return
            import rbac_service
            reason = rbac_service._request_reason() or None
            with conn:
                stamp(conn, after_id, _actor(), request.endpoint or request.path,
                      ENDPOINT_TYPES.get(request.endpoint or ""), reason)
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[StockLedger] could not name the person on stock history: {e}")
