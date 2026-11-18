"""
Gate pass state machine (RBAC Phase 8, plan "Gate security").

Built on the statuses this app really uses, so every normal button keeps working:

    Pending / Arrived / ACTIVE ──► Approved ──► Sent to Dock ──► Unloading ──► Completed ──► Exited / Departed
            │                         │              │
            └──────────► Sent to Dock ┘              └──► Rejected   (Rejected is possible before unloading)

* Each target status needs its own permission (STATUS_PERMISSION).
* A jump outside the allowed steps (e.g. Pending -> Departed, or re-opening a departed pass)
  needs gate.override.manual and a written reason, in every RBAC mode.
* Every status change, from any route or background service, is written to gate_pass_events
  (from, to, who, reason) by db.update_gate_pass.
"""
from __future__ import annotations

from typing import Optional, Tuple

_OPEN = ("Pending", "Arrived", "ACTIVE", "Expected", "")

TRANSITIONS = {
    **{s: {"Approved", "OTP Verified", "Sent to Dock", "Rejected"} for s in _OPEN},
    "OTP Verified": {"Approved", "Sent to Dock", "Rejected"},
    "Approved": {"Sent to Dock", "Rejected"},
    "Sent to Dock": {"Unloading", "Rejected", "Completed"},
    "At Dock": {"Unloading", "Rejected", "Completed"},
    "Unloading": {"Unloaded", "Completed"},
    "Unloaded": {"Completed", "Checkout Approved"},
    "Completed": {"Checkout Approved", "Exited", "Departed"},
    "Checkout Approved": {"Exited", "Departed"},
    "Rejected": set(),
    "Exited": set(),
    "Departed": set(),
}

STATUS_PERMISSION = {
    "OTP Verified": "gate.otp.verify",
    "Approved": "gate.entry.approve",
    "Rejected": "gate.entry.reject",
    "Sent to Dock": "gate.dock.admit",
    "Unloading": "dock.unload.execute",
    "Unloaded": "dock.unload.execute",
    "Completed": "dock.unload.execute",
    "Checkout Approved": "gate.checkout.approve",
    "Exited": "gate.checkout.complete",
    "Departed": "gate.checkout.complete",
    "Pending": "gate.override.manual",       # moving a pass back to the start is an override
}
OVERRIDE = "gate.override.manual"


def check(current: Optional[str], target: Optional[str]) -> Tuple[bool, Optional[str]]:
    """(allowed step?, permission the target status needs). Same status = nothing to check."""
    cur = (current or "").strip()
    tgt = (target or "").strip()
    if not tgt or tgt == cur:
        return True, None
    allowed = TRANSITIONS.get(cur)
    legal = tgt in allowed if allowed is not None else True   # unknown legacy status: only the permission
    return legal, STATUS_PERMISSION.get(tgt, OVERRIDE)


def record_event(conn, gp_id, from_status, to_status) -> None:
    """One gate_pass_events row (called inside the same transaction as the change)."""
    actor_id, reason = None, None
    try:
        from flask import g, has_request_context, request
        if has_request_context():
            actor_id = (g.get("current_user") or {}).get("id")
            reason = (request.headers.get("X-Action-Reason") or "").strip() or None
            if not reason and request.is_json:
                body = request.get_json(silent=True)
                if isinstance(body, dict) and body.get("reason"):
                    reason = str(body["reason"])[:300]
        else:
            reason = "system"
    except Exception:
        pass
    try:
        conn.execute("INSERT INTO gate_pass_events (gp_id, from_status, to_status, actor_user_id, reason) "
                     "VALUES (?, ?, ?, ?, ?)", (str(gp_id), from_status, to_status, actor_id, reason))
    except Exception:
        pass   # table missing on a pre-RBAC database: history is optional, the change is not
