"""
Users, invitations, passwords and companies (RBAC Phase 4).

Rules (RBAC plan, "Authentication and accounts", H12, H24):
  * Everything is per company. A Company Admin manages only their own company; the
    Platform Admin may name any company.
  * Soft delete only: users are deactivated, assignments revoked, companies suspended.
    History (audit, gate passes, stock ...) always stays.
  * Invitations: single-use link, token stored only as a SHA-256 hash, 72 h expiry.
    Accepting it sets the password (no reset needed afterwards).
  * Password reset links: single use, 30 min. A forgot-password request gets the same
    answer whether or not the account exists.
  * Deactivating a user (or suspending their company) ends their sessions on the next
    request (session_version bump + load_session_user checks).
  * Nobody changes their own access; the Platform Admin role is never assignable here;
    the last active Company Admin / Platform Admin can't be removed (database triggers).
  * Every change is written to audit_logs (never a password or token).
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import auth_service
import db
import mailer
import rbac_catalog
import rbac_migration

INVITE_HOURS = 72
RESET_MINUTES = 30
RESET_PER_ACCOUNT = 3          # reset emails per account per 30 min
RESET_PER_IP = 10              # forgot-password requests per IP per 15 min
# The built-in "User" role grants nothing, so it is hidden and no longer handed out
# (existing assignments keep working and stay visible until removed).
ASSIGNABLE_BUILTINS = ("company_admin",)

logger = logging.getLogger(__name__)


class IamError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ----------------------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def new_token() -> Tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, token_hash(raw)


def token_hash(raw: str) -> str:
    return hashlib.sha256(str(raw or "").encode()).hexdigest()


def _norm_email(email: Optional[str]) -> str:
    e = str(email or "").strip()
    if not e or "@" not in e or " " in e or len(e) > 254 or e.startswith("@") or e.endswith("@"):
        raise IamError(400, "invalid_email", "Enter a valid email address.")
    return e


def _conn():
    return db.get_db()


def _trigger_error(e: sqlite3.IntegrityError) -> IamError:
    msg = str(e)
    if "last_company_admin" in msg or "last_admin" in msg:
        return IamError(409, "last_company_admin",
                        "This is the company's last active Company Admin. Make someone else Company Admin first.")
    if "last_platform_admin" in msg:
        return IamError(409, "last_platform_admin", "This is the last active Platform Admin.")
    return IamError(409, "conflict", "That change conflicts with existing data.")


def company_row(conn, company_id: int) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not row:
        raise IamError(404, "not_found", "Company not found.")
    return dict(row)


def acting_company(actor: Dict[str, Any], requested: Any = None) -> int:
    """The company an admin request works on. Only the Platform Admin may name another company."""
    own = auth_service.user_company_id(actor["id"])
    if requested not in (None, "", "own"):
        try:
            cid = int(requested)
        except (TypeError, ValueError):
            raise IamError(400, "invalid_company", "Unknown company.")
        if cid != own and not actor.get("is_platform_admin"):
            raise IamError(404, "not_found", "Company not found.")
        return cid
    if own is None:
        raise IamError(400, "no_company", "Your account is not linked to a company.")
    return own


def _user_in_company(conn, user_id: int, company_id: int) -> Dict[str, Any]:
    row = conn.execute("""
        SELECT u.* FROM users u WHERE u.id = ? AND (
            EXISTS (SELECT 1 FROM user_company_access c WHERE c.user_id = u.id AND c.company_id = ?)
            OR EXISTS (SELECT 1 FROM user_warehouse_access a WHERE a.user_id = u.id AND a.company_id = ?))
    """, (user_id, company_id, company_id)).fetchone()
    if not row:
        raise IamError(404, "not_found", "User not found.")
    return dict(row)


def _guard_target(actor: Dict[str, Any], target: Dict[str, Any]) -> None:
    if target["id"] == actor["id"]:
        raise IamError(403, "self_change_forbidden", "You can't change your own access. Ask another admin.")
    if target.get("is_platform_admin") and not actor.get("is_platform_admin"):
        raise IamError(404, "not_found", "User not found.")


def _role(conn, role_id: Any, company_id: int) -> Dict[str, Any]:
    try:
        rid = int(role_id)
    except (TypeError, ValueError):
        raise IamError(400, "invalid_role", "Choose a role.")
    row = conn.execute("SELECT * FROM roles WHERE id = ? AND is_active = 1", (rid,)).fetchone()
    if not row:
        raise IamError(400, "invalid_role", "Choose a role.")
    r = dict(row)
    if r["is_builtin"]:
        if r["builtin_code"] not in ASSIGNABLE_BUILTINS:
            raise IamError(403, "role_not_assignable", "That role can't be assigned here.")
    elif r["company_id"] != company_id:
        raise IamError(400, "invalid_role", "Choose a role.")
    return r


def _warehouse(conn, warehouse_id: Any, company_id: int) -> Optional[Dict[str, Any]]:
    if warehouse_id in (None, "", "all", 0, "0"):
        return None
    try:
        wid = int(warehouse_id)
    except (TypeError, ValueError):
        raise IamError(400, "invalid_warehouse", "Choose a warehouse.")
    row = conn.execute("SELECT * FROM warehouses WHERE id = ? AND company_id = ?", (wid, company_id)).fetchone()
    if not row:
        raise IamError(400, "invalid_warehouse", "Choose a warehouse.")
    return dict(row)


def _bump_sessions(conn, user_ids: List[int]) -> None:
    for uid in user_ids:
        conn.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (uid,))


# ----------------------------------------------------------------------------- reads
def list_roles(company_id: int) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute("""
            SELECT id, name, description, is_builtin, builtin_code, company_id FROM roles
            WHERE is_active = 1 AND ((is_builtin = 1 AND builtin_code = 'company_admin')
                                     OR (is_builtin = 0 AND company_id = ?))
            ORDER BY is_builtin DESC, CASE builtin_code WHEN 'company_admin' THEN 0 ELSE 1 END, name
        """, (company_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_warehouses(company_id: int) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, code, name, city, status FROM warehouses WHERE company_id = ? ORDER BY code", (company_id,))]
    finally:
        conn.close()


def list_users(company_id: int) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        users = conn.execute("""
            SELECT DISTINCT u.id, u.username, u.email, u.is_active, u.is_platform_admin, u.last_login_at,
                   u.must_reset_password, u.locked_until
            FROM users u
            WHERE EXISTS (SELECT 1 FROM user_company_access c WHERE c.user_id = u.id AND c.company_id = ?)
               OR EXISTS (SELECT 1 FROM user_warehouse_access a WHERE a.user_id = u.id AND a.company_id = ?)
            ORDER BY u.username COLLATE NOCASE
        """, (company_id, company_id)).fetchall()
        assigns = conn.execute("""
            SELECT a.id, a.user_id, a.role_id, a.warehouse_id, a.status, r.name AS role_name, r.builtin_code,
                   w.code AS warehouse_code, w.name AS warehouse_name
            FROM user_warehouse_access a JOIN roles r ON r.id = a.role_id
            LEFT JOIN warehouses w ON w.id = a.warehouse_id
            WHERE a.company_id = ? ORDER BY a.id
        """, (company_id,)).fetchall()
    finally:
        conn.close()
    by_user: Dict[int, List[Dict[str, Any]]] = {}
    for a in assigns:
        by_user.setdefault(a["user_id"], []).append({
            "id": a["id"], "role_id": a["role_id"], "role": a["role_name"], "builtin_code": a["builtin_code"],
            "warehouse_id": a["warehouse_id"], "warehouse_code": a["warehouse_code"] or "All locations",
            "warehouse_name": a["warehouse_name"] or "", "status": a["status"]})
    out = []
    for u in users:
        d = dict(u)
        d["is_active"] = bool(d["is_active"])
        d["is_platform_admin"] = bool(d["is_platform_admin"])
        d["must_reset_password"] = bool(d["must_reset_password"])
        d["assignments"] = by_user.get(u["id"], [])
        d["role_label"] = auth_service.role_label(u["id"], d["is_platform_admin"])
        out.append(d)
    return out


def _invite_status(row: Dict[str, Any]) -> str:
    if row.get("accepted_at"):
        return "Accepted"
    if row.get("revoked_at"):
        return "Revoked"
    try:
        if datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") < _now():
            return "Expired"
    except Exception:
        return "Expired"
    return "Pending"


def list_invitations(company_id: int) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute("""
            SELECT i.id, i.email, i.role_id, i.warehouse_id, i.expires_at, i.accepted_at, i.revoked_at, i.created_at,
                   r.name AS role_name, w.code AS warehouse_code, u.username AS invited_by_name
            FROM invitations i JOIN roles r ON r.id = i.role_id
            LEFT JOIN warehouses w ON w.id = i.warehouse_id
            LEFT JOIN users u ON u.id = i.invited_by
            WHERE i.company_id = ? ORDER BY i.id DESC LIMIT 200
        """, (company_id,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["status"] = _invite_status(d)
        d["warehouse_code"] = d["warehouse_code"] or "All locations"
        out.append(d)
    return out


# ----------------------------------------------------------------------------- invitations
def _send_invite_email(email: str, company_name: str, role_name: str, link: str) -> Tuple[bool, str]:
    text, html_body = mailer.link_email(
        f"Invitation to {company_name}",
        f"You have been invited to join {company_name} on WARLOG as {role_name}. "
        f"Choose your username and password to get started.",
        link, "Accept invitation", f"This link works once and expires in {INVITE_HOURS} hours.")
    return mailer.send(email, f"You're invited to {company_name} on WARLOG", text, html_body)


def create_invitation(actor: Dict[str, Any], company_id: int, email: str, role_id: Any, warehouse_id: Any,
                      host_url: Optional[str] = None, ip: Optional[str] = None) -> Dict[str, Any]:
    email = _norm_email(email)
    conn = _conn()
    try:
        company = company_row(conn, company_id)
        if company["status"] != "Active":
            raise IamError(409, "company_suspended", "This company is suspended.")
        role = _role(conn, role_id, company_id)
        _check_can_grant(conn, actor, company_id, role_permission_set(conn, role))
        wh = _warehouse(conn, warehouse_id, company_id)
        if role.get("builtin_code") == "company_admin" and wh is not None:
            raise IamError(400, "company_admin_is_company_wide",
                           "Company Admin always covers every location of the company.")
        if conn.execute("SELECT 1 FROM users WHERE LOWER(email) = LOWER(?)", (email,)).fetchone():
            raise IamError(409, "email_in_use",
                           "That email already has a WARLOG account. Give that user access instead of inviting.")
        raw, th = new_token()
        expires = _ts(_now() + timedelta(hours=INVITE_HOURS))
        with conn:
            # one live invitation per email and company: older pending ones are revoked
            conn.execute("""UPDATE invitations SET revoked_at = CURRENT_TIMESTAMP
                            WHERE company_id = ? AND LOWER(email) = LOWER(?) AND accepted_at IS NULL AND revoked_at IS NULL""",
                         (company_id, email))
            cur = conn.execute("""
                INSERT INTO invitations (company_id, email, role_id, warehouse_id, token_hash, invited_by, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (company_id, email, role["id"], wh["id"] if wh else None, th, actor["id"], expires))
            inv_id = cur.lastrowid
    finally:
        conn.close()
    link = f"{mailer.base_url(host_url)}accept-invite?token={raw}"
    sent, msg = _send_invite_email(email, company["name"], role["name"], link)
    auth_service.audit("iam.user.invited", actor=actor, company_id=company_id, warehouse_id=wh["id"] if wh else None,
                       resource_type="invitation", resource_id=str(inv_id),
                       after={"email": email, "role": role["name"], "warehouse": wh["code"] if wh else "All locations",
                              "email_sent": sent}, ip=ip)
    result = {"id": inv_id, "email": email, "role": role["name"], "expires_at": expires, "email_sent": sent,
              "message": (f"Invitation emailed to {email}." if sent else
                          f"{msg} Copy the link below and send it to {email} yourself. It is shown only once.")}
    if not sent:
        result["invite_link"] = link  # shown once to the inviting admin, never stored
    return result


def revoke_invitation(actor: Dict[str, Any], company_id: int, invitation_id: int, ip: Optional[str] = None) -> None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM invitations WHERE id = ? AND company_id = ?", (invitation_id, company_id)).fetchone()
        if not row:
            raise IamError(404, "not_found", "Invitation not found.")
        if _invite_status(dict(row)) != "Pending":
            raise IamError(409, "not_pending", "Only a pending invitation can be revoked.")
        with conn:
            conn.execute("UPDATE invitations SET revoked_at = CURRENT_TIMESTAMP WHERE id = ?", (invitation_id,))
    finally:
        conn.close()
    auth_service.audit("iam.invitation.revoked", actor=actor, company_id=company_id,
                       resource_type="invitation", resource_id=str(invitation_id), ip=ip)


def resend_invitation(actor: Dict[str, Any], company_id: int, invitation_id: int,
                      host_url: Optional[str] = None, ip: Optional[str] = None) -> Dict[str, Any]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM invitations WHERE id = ? AND company_id = ?", (invitation_id, company_id)).fetchone()
    finally:
        conn.close()
    if not row:
        raise IamError(404, "not_found", "Invitation not found.")
    if row["accepted_at"]:
        raise IamError(409, "already_accepted", "That invitation was already accepted.")
    return create_invitation(actor, company_id, row["email"], row["role_id"], row["warehouse_id"], host_url, ip)


def _live_invitation(conn, raw_token: str) -> Dict[str, Any]:
    row = conn.execute("""
        SELECT i.*, c.name AS company_name, c.status AS company_status, r.name AS role_name, r.builtin_code,
               r.is_active AS role_active, w.code AS warehouse_code, w.name AS warehouse_name
        FROM invitations i JOIN companies c ON c.id = i.company_id JOIN roles r ON r.id = i.role_id
        LEFT JOIN warehouses w ON w.id = i.warehouse_id
        WHERE i.token_hash = ?""", (token_hash(raw_token),)).fetchone()
    if not row or _invite_status(dict(row)) != "Pending" or row["company_status"] != "Active" or not row["role_active"]:
        raise IamError(400, "invite_invalid", "This invitation link is invalid, already used or expired. Ask for a new one.")
    return dict(row)


def invitation_info(raw_token: str) -> Dict[str, Any]:
    conn = _conn()
    try:
        inv = _live_invitation(conn, raw_token)
    finally:
        conn.close()
    return {"email": inv["email"], "company_name": inv["company_name"], "role": inv["role_name"],
            "warehouse": inv["warehouse_code"] or "All locations", "expires_at": inv["expires_at"]}


def accept_invitation(raw_token: str, username: str, password: str, ip: Optional[str] = None) -> Dict[str, Any]:
    username = str(username or "").strip()
    if not (3 <= len(username) <= 40) or not all(ch.isalnum() or ch in "._-" for ch in username):
        raise IamError(400, "invalid_username", "Username: 3-40 letters, numbers, dots, dashes or underscores.")
    conn = _conn()
    try:
        inv = _live_invitation(conn, raw_token)
        err = auth_service.validate_new_password(password, username, inv["company_name"])
        if err:
            raise IamError(400, "weak_password", err)
        if conn.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
                        (username, username)).fetchone():
            raise IamError(409, "username_taken", "That username is taken. Choose another.")
        if conn.execute("SELECT 1 FROM users WHERE LOWER(email) = LOWER(?)", (inv["email"],)).fetchone():
            raise IamError(409, "email_in_use", "That email already has a WARLOG account.")
        wh_code = inv["warehouse_code"]
        if not wh_code:
            first = conn.execute("SELECT code FROM warehouses WHERE company_id = ? ORDER BY id LIMIT 1",
                                 (inv["company_id"],)).fetchone()
            wh_code = first[0] if first else None
        legacy_role = "Admin" if inv["builtin_code"] == "company_admin" else "User"
        with conn:
            # single use: claim the invitation first, inside the same transaction
            claimed = conn.execute("""UPDATE invitations SET accepted_at = CURRENT_TIMESTAMP
                                      WHERE id = ? AND accepted_at IS NULL AND revoked_at IS NULL""", (inv["id"],)).rowcount
            if claimed != 1:
                raise IamError(400, "invite_invalid", "This invitation link was already used.")
            cur = conn.execute("""
                INSERT INTO users (username, password, password_hash, company_name, assigned_warehouse_code, role,
                                   email, is_email_verified, must_reset_password, is_active, invited_by)
                VALUES (?, '', ?, ?, ?, ?, ?, 1, 0, 1, ?)""",
                (username, auth_service.hash_password(password), inv["company_name"], wh_code, legacy_role,
                 inv["email"], inv["invited_by"]))
            uid = cur.lastrowid
            conn.execute("""INSERT OR IGNORE INTO user_company_access (user_id, company_id, status, created_by)
                            VALUES (?, ?, 'Active', ?)""", (uid, inv["company_id"], inv["invited_by"]))
            conn.execute("""INSERT INTO user_warehouse_access (user_id, company_id, warehouse_id, role_id, is_default, status, created_by)
                            VALUES (?, ?, ?, ?, 1, 'Active', ?)""",
                         (uid, inv["company_id"], inv["warehouse_id"], inv["role_id"], inv["invited_by"]))
    finally:
        conn.close()
    auth_service.audit("iam.invitation.accepted", actor={"id": uid, "username": username}, company_id=inv["company_id"],
                       warehouse_id=inv["warehouse_id"], resource_type="user", resource_id=str(uid),
                       after={"username": username, "role": inv["role_name"]}, ip=ip)
    return {"username": username, "company_name": inv["company_name"]}


# ----------------------------------------------------------------------------- users
def set_user_active(actor: Dict[str, Any], company_id: int, user_id: int, active: bool,
                    reason: Optional[str] = None, ip: Optional[str] = None) -> None:
    if not active and not str(reason or "").strip():
        raise IamError(400, "reason_required", "Give a reason for deactivating this user.")
    conn = _conn()
    try:
        target = _user_in_company(conn, user_id, company_id)
        _guard_target(actor, target)
        try:
            with conn:
                conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))
                if not active:
                    _bump_sessions(conn, [user_id])
                else:
                    conn.execute("UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = ?", (user_id,))
        except sqlite3.IntegrityError as e:
            raise _trigger_error(e)
    finally:
        conn.close()
    auth_service.audit("iam.user.activated" if active else "iam.user.deactivated", actor=actor, company_id=company_id,
                       resource_type="user", resource_id=str(user_id), reason=reason,
                       before={"is_active": bool(target["is_active"])}, after={"is_active": active}, ip=ip)


def update_user(actor: Dict[str, Any], company_id: int, user_id: int, data: Dict[str, Any],
                ip: Optional[str] = None) -> None:
    conn = _conn()
    try:
        target = _user_in_company(conn, user_id, company_id)
        _guard_target(actor, target)
        changes = {}
        if "email" in data:
            email = _norm_email(data.get("email"))
            if conn.execute("SELECT 1 FROM users WHERE LOWER(email) = LOWER(?) AND id != ?", (email, user_id)).fetchone():
                raise IamError(409, "email_in_use", "That email already belongs to another account.")
            changes["email"] = email
        if not changes:
            raise IamError(400, "nothing_to_change", "Nothing to change.")
        with conn:
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (changes["email"], user_id))
    finally:
        conn.close()
    auth_service.audit("iam.user.edited", actor=actor, company_id=company_id, resource_type="user",
                       resource_id=str(user_id), before={"email": target.get("email")}, after=changes, ip=ip)


def add_assignment(actor: Dict[str, Any], company_id: int, user_id: int, role_id: Any, warehouse_id: Any,
                   ip: Optional[str] = None) -> Dict[str, Any]:
    conn = _conn()
    try:
        target = _user_in_company(conn, user_id, company_id)
        _guard_target(actor, target)
        role = _role(conn, role_id, company_id)
        _check_can_grant(conn, actor, company_id, role_permission_set(conn, role))
        wh = _warehouse(conn, warehouse_id, company_id)
        if role.get("builtin_code") == "company_admin" and wh is not None:
            raise IamError(400, "company_admin_is_company_wide",
                           "Company Admin always covers every location of the company.")
        wid = wh["id"] if wh else None
        existing = conn.execute("""SELECT id, status FROM user_warehouse_access
                                   WHERE user_id = ? AND company_id = ? AND role_id = ? AND warehouse_id IS ?""",
                                (user_id, company_id, role["id"], wid)).fetchone()
        with conn:
            conn.execute("""INSERT OR IGNORE INTO user_company_access (user_id, company_id, status, created_by)
                            VALUES (?, ?, 'Active', ?)""", (user_id, company_id, actor["id"]))
            if existing:
                if existing["status"] == "Active":
                    raise IamError(409, "already_assigned", "The user already has that role there.")
                conn.execute("UPDATE user_warehouse_access SET status = 'Active' WHERE id = ?", (existing["id"],))
                aid = existing["id"]
            else:
                aid = conn.execute("""INSERT INTO user_warehouse_access (user_id, company_id, warehouse_id, role_id,
                                      is_default, status, created_by) VALUES (?, ?, ?, ?, 0, 'Active', ?)""",
                                   (user_id, company_id, wid, role["id"], actor["id"])).lastrowid
    finally:
        conn.close()
    auth_service.audit("iam.assignment.granted", actor=actor, company_id=company_id, warehouse_id=wid,
                       resource_type="user", resource_id=str(user_id),
                       after={"role": role["name"], "warehouse": wh["code"] if wh else "All locations"}, ip=ip)
    return {"id": aid}


def revoke_assignment(actor: Dict[str, Any], company_id: int, assignment_id: int,
                      reason: Optional[str] = None, ip: Optional[str] = None) -> None:
    conn = _conn()
    try:
        a = conn.execute("""SELECT a.*, r.name AS role_name, w.code AS warehouse_code FROM user_warehouse_access a
                            JOIN roles r ON r.id = a.role_id LEFT JOIN warehouses w ON w.id = a.warehouse_id
                            WHERE a.id = ? AND a.company_id = ?""", (assignment_id, company_id)).fetchone()
        if not a:
            raise IamError(404, "not_found", "Assignment not found.")
        target = _user_in_company(conn, a["user_id"], company_id)
        _guard_target(actor, target)
        if a["status"] != "Active":
            raise IamError(409, "not_active", "That access is already removed.")
        try:
            with conn:
                conn.execute("UPDATE user_warehouse_access SET status = 'Revoked' WHERE id = ?", (assignment_id,))
        except sqlite3.IntegrityError as e:
            raise _trigger_error(e)
    finally:
        conn.close()
    auth_service.audit("iam.assignment.revoked", actor=actor, company_id=company_id, warehouse_id=a["warehouse_id"],
                       resource_type="user", resource_id=str(a["user_id"]), reason=reason,
                       before={"role": a["role_name"], "warehouse": a["warehouse_code"] or "All locations"}, ip=ip)


# ----------------------------------------------------------------------------- passwords
def _issue_reset(conn, user: Dict[str, Any], ip: Optional[str], host_url: Optional[str]) -> Tuple[str, bool]:
    raw, th = new_token()
    with conn:
        conn.execute("UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE user_id = ? AND used_at IS NULL",
                     (user["id"],))
        conn.execute("""INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, requested_ip)
                        VALUES (?, ?, ?, ?)""", (user["id"], th, _ts(_now() + timedelta(minutes=RESET_MINUTES)), ip))
    link = f"{mailer.base_url(host_url)}reset-password?token={raw}"
    sent = False
    if user.get("email"):
        text, html_body = mailer.link_email(
            "Password reset", f"Hello {user['username']}, use the button below to choose a new WARLOG password.",
            link, "Choose a new password", f"This link works once and expires in {RESET_MINUTES} minutes.")
        sent, _ = mailer.send(user["email"], "Reset your WARLOG password", text, html_body)
    return link, sent


def request_password_reset(identifier: str, ip: Optional[str] = None, host_url: Optional[str] = None) -> None:
    """Forgot password. Same outcome for the caller whether or not the account exists."""
    key = auth_service.username_key(identifier)
    conn = _conn()
    try:
        recent_ip = conn.execute("""SELECT COUNT(*) FROM audit_logs WHERE action = 'auth.reset_requested'
                                    AND ip = ? AND ts > datetime('now', '-15 minutes')""", (ip,)).fetchone()[0] if ip else 0
        user = auth_service.find_user(identifier) if key else None
        if recent_ip >= RESET_PER_IP:
            user = None
        if user and user.get("is_active"):
            recent = conn.execute("""SELECT COUNT(*) FROM password_reset_tokens WHERE user_id = ?
                                     AND created_at > datetime('now', '-30 minutes')""", (user["id"],)).fetchone()[0]
            if recent < RESET_PER_ACCOUNT:
                _, sent = _issue_reset(conn, user, ip, host_url)
                if not sent:
                    logger.warning(f"[AUTH] reset link for user id {user['id']} could not be emailed "
                                      "(no email on the account or SMTP not configured)")
    finally:
        conn.close()
    auth_service.audit("auth.reset_requested", actor_username=key or "(empty)", ip=ip)


def admin_send_reset(actor: Dict[str, Any], company_id: int, user_id: int, host_url: Optional[str] = None,
                     ip: Optional[str] = None) -> Dict[str, Any]:
    conn = _conn()
    try:
        target = _user_in_company(conn, user_id, company_id)
        _guard_target(actor, target)
        if not target["is_active"]:
            raise IamError(409, "user_inactive", "Activate the user first.")
        link, sent = _issue_reset(conn, target, ip, host_url)
    finally:
        conn.close()
    auth_service.audit("iam.user.reset_link_sent", actor=actor, company_id=company_id, resource_type="user",
                       resource_id=str(user_id), after={"email_sent": sent}, ip=ip)
    out = {"email_sent": sent,
           "message": (f"A reset link was emailed to {target['email']}." if sent else
                       "Email could not be sent. Copy this link and give it to the user. It is shown only once "
                       f"and expires in {RESET_MINUTES} minutes.")}
    if not sent:
        out["reset_link"] = link
    return out


def reset_token_valid(raw_token: str) -> bool:
    conn = _conn()
    try:
        return _reset_row(conn, raw_token) is not None
    finally:
        conn.close()


def _reset_row(conn, raw_token: str):
    row = conn.execute("""SELECT t.*, u.username, u.company_name, u.is_active FROM password_reset_tokens t
                          JOIN users u ON u.id = t.user_id WHERE t.token_hash = ?""", (token_hash(raw_token),)).fetchone()
    if not row or row["used_at"] or not row["is_active"]:
        return None
    try:
        if datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") < _now():
            return None
    except Exception:
        return None
    return row


def reset_with_token(raw_token: str, new_password: str, ip: Optional[str] = None) -> None:
    conn = _conn()
    try:
        row = _reset_row(conn, raw_token)
        if row is None:
            raise IamError(400, "reset_invalid", "This reset link is invalid, already used or expired. Ask for a new one.")
        err = auth_service.validate_new_password(new_password, row["username"], row["company_name"])
        if err:
            raise IamError(400, "weak_password", err)
        with conn:
            claimed = conn.execute("UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = ? AND used_at IS NULL",
                                   (row["id"],)).rowcount
        if claimed != 1:
            raise IamError(400, "reset_invalid", "This reset link was already used.")
    finally:
        conn.close()
    auth_service.set_password(row["user_id"], new_password, actor={"id": row["user_id"], "username": row["username"]},
                              action="auth.password_reset_by_link", ip=ip)


def change_password(user: Dict[str, Any], current_password: str, new_password: str,
                    ip: Optional[str] = None) -> int:
    full = auth_service.get_user_by_id(user["id"])
    if not full or not auth_service.verify_user_password(full, current_password or ""):
        raise IamError(400, "wrong_password", "Your current password is not correct.")
    err = auth_service.validate_new_password(new_password, full["username"], full.get("company_name") or "")
    if err:
        raise IamError(400, "weak_password", err)
    if auth_service.verify_user_password(full, new_password):
        raise IamError(400, "same_password", "Choose a password different from the current one.")
    return auth_service.set_password(full["id"], new_password, actor=full, ip=ip)


# ----------------------------------------------------------------------------- companies (Platform Admin)
def create_company(actor: Dict[str, Any], name: str, owner_email: str, city: Optional[str] = None,
                   host_url: Optional[str] = None, ip: Optional[str] = None) -> Dict[str, Any]:
    name = " ".join(str(name or "").split())
    if len(name) < 2:
        raise IamError(400, "invalid_name", "Enter the company name.")
    owner_email = _norm_email(owner_email)
    if auth_service.company_exists(name):
        raise IamError(409, "company_exists", "A company with that name already exists.")
    conn = _conn()
    try:
        with conn:
            company_id = rbac_migration.ensure_company(conn, name)
            base = "WH-" + ("".join(ch for ch in name.upper() if ch.isalnum())[:6] or "CO")
            code, n = base, 1
            while conn.execute("SELECT 1 FROM warehouses WHERE UPPER(code) = ?", (code,)).fetchone():
                n += 1
                code = f"{base}-{n}"
            conn.execute("""INSERT INTO warehouses (code, name, city, operating_mode, industry, status, is_active,
                                                    company_name, company_id)
                            VALUES (?, ?, ?, 'DEDICATED', 'General', 'Active', 0, ?, ?)""",
                         (code, f"{name} Main", (city or "").strip() or "Main", name, company_id))
    finally:
        conn.close()
    auth_service.audit("platform.company.created", actor=actor, company_id=company_id, resource_type="company",
                       resource_id=str(company_id), after={"name": name, "first_location": code}, ip=ip)
    conn = _conn()
    try:
        admin_role = rbac_migration.builtin_role_id(conn, "company_admin")
    finally:
        conn.close()
    invite = create_invitation(actor, company_id, owner_email, admin_role, None, host_url, ip)
    return {"company_id": company_id, "name": name, "first_location": code, "invitation": invite}


def set_company_status(actor: Dict[str, Any], company_id: int, active: bool, reason: Optional[str] = None,
                       ip: Optional[str] = None) -> None:
    if not active and not str(reason or "").strip():
        raise IamError(400, "reason_required", "Give a reason for suspending this company.")
    conn = _conn()
    try:
        company = company_row(conn, company_id)
        if company.get("is_platform_owner") and not active:
            raise IamError(409, "platform_owner", "The platform owner's company can't be suspended.")
        users = [r[0] for r in conn.execute("""
            SELECT DISTINCT user_id FROM user_company_access WHERE company_id = ?
            UNION SELECT DISTINCT user_id FROM user_warehouse_access WHERE company_id = ?""", (company_id, company_id))]
        with conn:
            conn.execute("UPDATE companies SET status = ? WHERE id = ?", ("Active" if active else "Suspended", company_id))
            if not active:
                platform = {r[0] for r in conn.execute("SELECT id FROM users WHERE is_platform_admin = 1")}
                _bump_sessions(conn, [u for u in users if u not in platform])
    finally:
        conn.close()
    auth_service.audit("platform.company.activated" if active else "platform.company.suspended", actor=actor,
                       company_id=company_id, resource_type="company", resource_id=str(company_id), reason=reason,
                       before={"status": company["status"]}, after={"status": "Active" if active else "Suspended"}, ip=ip)


# ----------------------------------------------------------------------------- roles (Phase 5)
MAX_ROLE_NAME = 60


def role_permission_set(conn, role: Dict[str, Any]) -> frozenset:
    """What a role grants inside a company (never platform permissions)."""
    if role.get("is_builtin"):
        return frozenset(k for k in rbac_catalog.builtin_permissions(role.get("builtin_code"))
                         if rbac_catalog.PERMISSIONS_BY_KEY[k].scope_level != "platform")
    keys = {r[0] for r in conn.execute("""
        SELECT rp.permission_key FROM role_permissions rp
        JOIN permissions p ON p.key = rp.permission_key AND p.retired = 0
        WHERE rp.role_id = ?""", (role["id"],))}
    return frozenset(k for k in keys if k in rbac_catalog.PERMISSIONS_BY_KEY
                     and rbac_catalog.PERMISSIONS_BY_KEY[k].scope_level != "platform")


def actor_company_permissions(conn, actor: Dict[str, Any], company_id: int) -> frozenset:
    """Everything the actor holds anywhere in this company (union of their active
    assignments there). The Platform Admin holds everything."""
    if actor.get("is_platform_admin"):
        return frozenset(k for k, p in rbac_catalog.PERMISSIONS_BY_KEY.items() if p.scope_level != "platform")
    held = set()
    for row in conn.execute("""
        SELECT r.* FROM user_warehouse_access a JOIN roles r ON r.id = a.role_id AND r.is_active = 1
        JOIN companies c ON c.id = a.company_id AND c.status = 'Active'
        WHERE a.user_id = ? AND a.company_id = ? AND a.status = 'Active'""", (actor["id"], company_id)):
        held |= role_permission_set(conn, dict(row))
    return frozenset(held)


def _check_can_grant(conn, actor: Dict[str, Any], company_id: int, keys) -> None:
    """H12: nobody grants (through a role, an invitation or an assignment) what they don't hold."""
    missing = set(keys) - actor_company_permissions(conn, actor, company_id)
    if missing:
        labels = sorted(rbac_catalog.PERMISSIONS_BY_KEY[k].label for k in missing
                        if k in rbac_catalog.PERMISSIONS_BY_KEY)
        more = f" and {len(labels) - 5} more" if len(labels) > 5 else ""
        raise IamError(403, "escalation_blocked",
                       "You can only grant permissions you have yourself. Missing: "
                       + ", ".join(labels[:5]) + more + ".")


def permission_catalog(actor: Dict[str, Any], company_id: int) -> List[Dict[str, Any]]:
    """The tick-box list for the role builder: every company/warehouse permission, grouped
    by module, with `grantable` = the actor holds it. Platform permissions are never listed."""
    conn = _conn()
    try:
        held = actor_company_permissions(conn, actor, company_id)
        retired = {r[0] for r in conn.execute("SELECT key FROM permissions WHERE retired = 1")}
    finally:
        conn.close()
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for p in rbac_catalog.PERMISSION_CATALOG:
        if p.scope_level == "platform" or p.key in retired:
            continue
        groups.setdefault(p.module, []).append({
            "key": p.key, "label": p.label, "action": p.action, "scope_level": p.scope_level,
            "sensitive": bool(p.sensitive), "grantable": p.key in held,
            "section": rbac_catalog.PERMISSION_SECTIONS.get(p.key, "")})
    return [{"module": m, "permissions": perms} for m, perms in groups.items()]


def _role_users(conn, role_id: int, company_id: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT DISTINCT u.id, u.username, u.is_active, COALESCE(w.code, 'All locations') AS warehouse_code
        FROM user_warehouse_access a JOIN users u ON u.id = a.user_id
        LEFT JOIN warehouses w ON w.id = a.warehouse_id
        WHERE a.role_id = ? AND a.status = 'Active'"""
    params: tuple = (role_id,)
    if company_id is not None:
        sql += " AND a.company_id = ?"
        params += (company_id,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY u.username COLLATE NOCASE", params)]


def list_roles_detailed(company_id: int) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute("""
            SELECT * FROM roles
            WHERE (is_builtin = 1 AND builtin_code = 'company_admin') OR (is_builtin = 0 AND company_id = ?)
               OR (is_builtin = 1 AND builtin_code = 'user' AND EXISTS (
                   SELECT 1 FROM user_warehouse_access a WHERE a.role_id = roles.id AND a.company_id = ?
                   AND a.status = 'Active'))
            ORDER BY is_builtin DESC, CASE builtin_code WHEN 'company_admin' THEN 0 ELSE 1 END, is_active DESC,
                     name COLLATE NOCASE""", (company_id, company_id))]
        out = []
        for r in rows:
            out.append({"id": r["id"], "name": r["name"], "description": r["description"] or "",
                        "is_builtin": bool(r["is_builtin"]), "builtin_code": r["builtin_code"],
                        "is_active": bool(r["is_active"]), "permissions": sorted(role_permission_set(conn, r)),
                        "users": _role_users(conn, r["id"], company_id), "updated_at": r.get("updated_at"),
                        "template_key": r.get("template_key"),
                        "template_permissions": sorted(set(rbac_catalog.STARTER_ROLES_BY_KEY[r["template_key"]][3]))
                        if r.get("template_key") in rbac_catalog.STARTER_ROLES_BY_KEY else None})
        return out
    finally:
        conn.close()


def _custom_role(conn, role_id: int, company_id: int) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    if not row:
        raise IamError(404, "not_found", "Role not found.")
    r = dict(row)
    if r["is_builtin"]:
        raise IamError(403, "builtin_read_only", "Built-in roles can't be changed. Create a custom role instead.")
    if r["company_id"] != company_id:
        raise IamError(404, "not_found", "Role not found.")
    return r


def _clean_role_input(conn, company_id: int, name: Any, description: Any, permissions: Any,
                      exclude_id: Optional[int] = None) -> Tuple[str, str, frozenset]:
    name = " ".join(str(name or "").split())
    if not (2 <= len(name) <= MAX_ROLE_NAME):
        raise IamError(400, "invalid_name", f"Role name: 2-{MAX_ROLE_NAME} characters.")
    reserved = {n.casefold() for _, n, _ in rbac_catalog.BUILTIN_ROLES} | {"super admin"}
    if name.casefold() in reserved:
        raise IamError(409, "name_taken", "That name belongs to a built-in role.")
    dup = conn.execute("SELECT 1 FROM roles WHERE company_id = ? AND LOWER(name) = LOWER(?) AND id IS NOT ?",
                       (company_id, name, exclude_id)).fetchone()
    if dup:
        raise IamError(409, "name_taken", "Your company already has a role with that name.")
    if not isinstance(permissions, (list, tuple)):
        raise IamError(400, "invalid_permissions", "Tick at least one permission.")
    keys = frozenset(str(k) for k in permissions)
    unknown = [k for k in keys if k not in rbac_catalog.PERMISSIONS_BY_KEY
               or rbac_catalog.PERMISSIONS_BY_KEY[k].scope_level == "platform"]
    if unknown:
        raise IamError(400, "unknown_permission", "Unknown permission: " + ", ".join(sorted(unknown)[:5]))
    if not keys:
        raise IamError(400, "invalid_permissions", "Tick at least one permission.")
    return name, str(description or "").strip()[:300], keys


def _labels(keys) -> List[str]:
    return sorted(rbac_catalog.PERMISSIONS_BY_KEY[k].label for k in keys if k in rbac_catalog.PERMISSIONS_BY_KEY)


def _diff(before: frozenset, after: frozenset) -> Dict[str, List[str]]:
    return {"added": _labels(after - before), "removed": _labels(before - after)}


def _forbid_own_role(conn, actor: Dict[str, Any], role_id: int) -> None:
    if conn.execute("SELECT 1 FROM user_warehouse_access WHERE user_id = ? AND role_id = ? AND status = 'Active'",
                    (actor["id"], role_id)).fetchone():
        raise IamError(403, "self_change_forbidden",
                       "You hold this role yourself, so you can't change it. Ask another admin.")


def create_role(actor: Dict[str, Any], company_id: int, data: Dict[str, Any], ip: Optional[str] = None) -> Dict[str, Any]:
    conn = _conn()
    try:
        name, desc, keys = _clean_role_input(conn, company_id, data.get("name"), data.get("description"),
                                             data.get("permissions"))
        _check_can_grant(conn, actor, company_id, keys)
        with conn:
            rid = conn.execute("""INSERT INTO roles (company_id, name, description, is_builtin, builtin_code,
                                  is_active, created_by) VALUES (?, ?, ?, 0, NULL, 1, ?)""",
                               (company_id, name, desc, actor["id"])).lastrowid
            conn.executemany("INSERT INTO role_permissions (role_id, permission_key) VALUES (?, ?)",
                             [(rid, k) for k in sorted(keys)])
    finally:
        conn.close()
    auth_service.audit("iam.role.created", actor=actor, company_id=company_id, resource_type="role",
                       resource_id=str(rid), after={"name": name, "permissions": sorted(keys)}, ip=ip)
    return {"id": rid, "name": name}


def preview_role_change(actor: Dict[str, Any], company_id: int, role_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Who is affected and what changes, before saving (nothing is written)."""
    conn = _conn()
    try:
        role = _custom_role(conn, role_id, company_id)
        before = role_permission_set(conn, role)
        after = before
        if "permissions" in data:
            _, _, after = _clean_role_input(conn, company_id, data.get("name") or role["name"], "",
                                            data.get("permissions"), exclude_id=role_id)
        if data.get("deactivate"):
            after = frozenset()
        users = _role_users(conn, role_id, company_id)
    finally:
        conn.close()
    return {"role": role["name"], "users": users, **_diff(before, after)}


def update_role(actor: Dict[str, Any], company_id: int, role_id: int, data: Dict[str, Any],
                ip: Optional[str] = None) -> Dict[str, Any]:
    conn = _conn()
    try:
        role = _custom_role(conn, role_id, company_id)
        _forbid_own_role(conn, actor, role_id)
        before = role_permission_set(conn, role)
        name, desc, keys = _clean_role_input(conn, company_id, data.get("name", role["name"]),
                                             data.get("description", role["description"]),
                                             data.get("permissions", sorted(before)), exclude_id=role_id)
        # only what is being ADDED must be held; removing permissions is always allowed
        _check_can_grant(conn, actor, company_id, keys - before)
        with conn:
            conn.execute("UPDATE roles SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (name, desc, role_id))
            conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
            conn.executemany("INSERT INTO role_permissions (role_id, permission_key) VALUES (?, ?)",
                             [(role_id, k) for k in sorted(keys)])
        users = _role_users(conn, role_id, company_id)
    finally:
        conn.close()
    change = _diff(before, keys)
    auth_service.audit("iam.role.updated", actor=actor, company_id=company_id, resource_type="role",
                       resource_id=str(role_id), reason=str(data.get("reason") or "") or None,
                       before={"name": role["name"], "permissions": sorted(before)},
                       after={"name": name, "permissions": sorted(keys), "users_affected": len(users)}, ip=ip)
    return {"id": role_id, "name": name, "users_affected": len(users), **change}


def set_role_active(actor: Dict[str, Any], company_id: int, role_id: int, active: bool,
                    reason: Optional[str] = None, ip: Optional[str] = None) -> Dict[str, Any]:
    if not active and not str(reason or "").strip():
        raise IamError(400, "reason_required", "Give a reason for deactivating this role.")
    conn = _conn()
    try:
        role = _custom_role(conn, role_id, company_id)
        _forbid_own_role(conn, actor, role_id)
        if active:
            _check_can_grant(conn, actor, company_id, role_permission_set(conn, role))
        with conn:
            conn.execute("UPDATE roles SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (1 if active else 0, role_id))
        users = _role_users(conn, role_id, company_id)
    finally:
        conn.close()
    auth_service.audit("iam.role.activated" if active else "iam.role.deactivated", actor=actor,
                       company_id=company_id, resource_type="role", resource_id=str(role_id), reason=reason,
                       before={"is_active": bool(role["is_active"])},
                       after={"is_active": active, "users_affected": len(users)}, ip=ip)
    return {"id": role_id, "users_affected": len(users)}


# ----------------------------------------------------------------------------- audit log (Phase 7)
AUDIT_PAGE = 50


def _audit_where(company_id: Optional[int], f: Dict[str, Any]) -> Tuple[str, list]:
    where, params = ["1=1"], []
    if company_id is not None:
        where.append("a.company_id = ?")
        params.append(company_id)
    if f.get("action"):
        where.append("a.action LIKE ?")
        params.append(str(f["action"]).strip() + "%")
    if f.get("actor"):
        where.append("LOWER(a.actor_username) LIKE ?")
        params.append("%" + str(f["actor"]).strip().lower() + "%")
    if f.get("q"):
        q = "%" + str(f["q"]).strip().lower() + "%"
        where.append("(LOWER(a.action) LIKE ? OR LOWER(COALESCE(a.resource_id,'')) LIKE ? OR LOWER(COALESCE(a.reason,'')) LIKE ?"
                     " OR LOWER(COALESCE(a.actor_username,'')) LIKE ?)")
        params += [q, q, q, q]
    if f.get("from"):
        where.append("a.ts >= ?")
        params.append(str(f["from"]) + (" 00:00:00" if len(str(f["from"])) == 10 else ""))
    if f.get("to"):
        where.append("a.ts <= ?")
        params.append(str(f["to"]) + (" 23:59:59" if len(str(f["to"])) == 10 else ""))
    if f.get("result"):
        where.append("a.result = ?")
        params.append(str(f["result"]))
    return " AND ".join(where), params


def list_audit(company_id: Optional[int], filters: Dict[str, Any], page: int = 1) -> Dict[str, Any]:
    """Company Admins see their own company's rows; the Platform Admin may pass None (all)."""
    where, params = _audit_where(company_id, filters)
    page = max(1, int(page or 1))
    conn = _conn()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM audit_logs a WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT a.id, a.ts, a.actor_username, a.action, a.resource_type, a.resource_id, a.reason,
                   a.before_json, a.after_json, a.ip, a.result, a.company_id, a.warehouse_id,
                   w.code AS warehouse_code, c.name AS company_name
            FROM audit_logs a LEFT JOIN warehouses w ON w.id = a.warehouse_id
            LEFT JOIN companies c ON c.id = a.company_id
            WHERE {where} ORDER BY a.id DESC LIMIT ? OFFSET ?""",
            params + [AUDIT_PAGE, (page - 1) * AUDIT_PAGE]).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("before_json", "after_json"):
            try:
                d[k[:-5]] = json.loads(d.pop(k)) if d.get(k) else None
            except ValueError:
                d[k[:-5]] = None
        out.append(d)
    return {"rows": out, "total": total, "page": page, "pages": max(1, -(-total // AUDIT_PAGE))}


def audit_csv(company_id: Optional[int], filters: Dict[str, Any], limit: int = 20000) -> str:
    import csv
    import io
    where, params = _audit_where(company_id, filters)
    conn = _conn()
    try:
        rows = conn.execute(f"""
            SELECT a.ts, a.actor_username, c.name, w.code, a.action, a.resource_type, a.resource_id, a.reason,
                   a.result, a.ip, a.before_json, a.after_json
            FROM audit_logs a LEFT JOIN warehouses w ON w.id = a.warehouse_id LEFT JOIN companies c ON c.id = a.company_id
            WHERE {where} ORDER BY a.id DESC LIMIT ?""", params + [int(limit)]).fetchall()
    finally:
        conn.close()
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["time (UTC)", "who", "company", "location", "action", "record type", "record", "reason",
                 "result", "ip", "before", "after"])
    for r in rows:
        # neutralise spreadsheet formulas in exported text
        wr.writerow(["'" + str(v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in r])
    return buf.getvalue()


def purge_old_audit_rows() -> int:
    """Retention (default 365 days, per company: audit.retention_days). Rows without a
    company use the default. Runs from a daily background job; never edits rows."""
    import settings_service
    conn = _conn()
    removed = 0
    try:
        companies = [r[0] for r in conn.execute("SELECT id FROM companies")]
        with conn:
            for cid in companies:
                days = int(settings_service.get_company(cid, "audit.retention_days") or 365)
                days = max(30, min(days, 3650))
                removed += conn.execute("DELETE FROM audit_logs WHERE company_id = ? AND ts < datetime('now', ?)",
                                        (cid, f"-{days} days")).rowcount
            removed += conn.execute("DELETE FROM audit_logs WHERE company_id IS NULL AND ts < datetime('now', '-365 days')").rowcount
    finally:
        conn.close()
    if removed:
        logger.info(f"[AUDIT] retention removed {removed} rows older than the retention period")
    return removed


def set_company_setting(actor: Dict[str, Any], company_id: int, key: str, value: Any,
                        ip: Optional[str] = None) -> Any:
    import settings_service
    if key == "copilot.web_search":
        value = bool(value)
    elif key == "audit.retention_days":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise IamError(400, "invalid_value", "Retention must be a number of days.")
        if not 30 <= value <= 3650:
            raise IamError(400, "invalid_value", "Retention must be between 30 and 3650 days.")
    else:
        raise IamError(400, "unknown_setting", "Unknown setting.")
    before = settings_service.get_company(company_id, key)
    settings_service.set_company(company_id, key, value, actor.get("id"))
    auth_service.audit("company.setting_changed", actor=actor, company_id=company_id, resource_type="company",
                       resource_id=str(company_id), before={key: before}, after={key: value}, ip=ip)
    return value


def roles_coverage_summary(company_id: int) -> Dict[str, Any]:
    """Computes live WARLOG permission coverage across active custom roles for a company."""
    all_keys = {k for k, p in rbac_catalog.PERMISSIONS_BY_KEY.items() if p.scope_level != "platform"}
    conn = _conn()
    try:
        rows = conn.execute("""
            SELECT DISTINCT rp.permission_key
            FROM roles r
            JOIN role_permissions rp ON rp.role_id = r.id
            WHERE r.company_id = ? AND r.is_active = 1
        """, (int(company_id),)).fetchall()
        covered = {r[0] for r in rows if r[0] in all_keys}
        active_custom = conn.execute(
            "SELECT COUNT(*) FROM roles WHERE company_id = ? AND is_active = 1", (int(company_id),)
        ).fetchone()[0]
    finally:
        conn.close()
    total = len(all_keys)
    cov_n = len(covered)
    pct = int(round(100.0 * cov_n / total)) if total else 100
    return {
        "company_id": int(company_id),
        "total_permissions": total,
        "covered_permissions": cov_n,
        "coverage_pct": pct,
        "active_custom_roles": int(active_custom),
    }


def apply_role_pack(actor: Dict[str, Any], company_id: int, pack_key: str,
                    ip: Optional[str] = None) -> Dict[str, Any]:
    """Applies a 3-role, 5-role, or 15-role preset pack for a company (idempotent create/reactivate)."""
    pack_key = (pack_key or "3_role").strip().lower()
    all_non_platform = sorted(k for k, p in rbac_catalog.PERMISSIONS_BY_KEY.items() if p.scope_level != "platform")
    starter = rbac_catalog.STARTER_ROLES_BY_KEY

    if pack_key == "3_role":
        specs = [
            ("Site Supervisor", "Compact supervisor role covering day-to-day warehouse operations.",
             starter["warehouse_manager"][3]),
            ("Warehouse Operator", "Frontline operator: gate, dock, inbound, outbound, palletization, stock & cameras.",
             tuple(sorted(set(starter["gate_incharge"][3]) | set(starter["dock_supervisor"][3]) | set(starter["inventory_controller"][3]) | set(starter["dispatch_operator"][3]) | set(starter["vision_operator"][3])))),
            ("Viewer / Executive", starter["executive"][2], starter["executive"][3]),
        ]
    elif pack_key == "5_role":
        specs = [
            (starter["warehouse_manager"][1], starter["warehouse_manager"][2], starter["warehouse_manager"][3]),
            (starter["gate_incharge"][1], starter["gate_incharge"][2], starter["gate_incharge"][3]),
            (starter["dock_supervisor"][1], starter["dock_supervisor"][2], starter["dock_supervisor"][3]),
            (starter["inventory_controller"][1], starter["inventory_controller"][2], starter["inventory_controller"][3]),
            (starter["dispatch_operator"][1], starter["dispatch_operator"][2], starter["dispatch_operator"][3]),
        ]
    elif pack_key == "15_role":
        specs = [(v[1], v[2], v[3]) for v in rbac_catalog.STARTER_ROLES] + [
            ("Shift Supervisor", "Cross-zone shift oversight across gate, docks, inbound and outbound.",
             starter["warehouse_manager"][3]),
            ("Forklift / MHE Lead", "Bin transfers, pallet moves and putaway execution.",
             ("dashboard.view", "bins.view", "inventory.view", "inventory.transfer", "pallet.view", "pallet.transfer")),
            ("Inbound Staging Counter", "Staging perception and verified receipt counting.",
             ("dashboard.view", "inbound.view", "inbound.staging.view", "pallet.view", "pallet.create", "vision.view", "vision.counting.execute")),
            ("Cycle Count Auditor", "Executes and approves physical inventory cycle counts.",
             ("dashboard.view", "sku.view", "bins.view", "inventory.view", "cyclecount.view", "cyclecount.execute", "cyclecount.approve")),
            ("CCTV / Vision Technician", "Installs, configures and calibrates cameras and vision zones.",
             ("dashboard.view", "cameras.view", "cameras.stream.view", "cameras.create", "cameras.configure", "cameras.ptz.control", "vision.view", "vision.zones.manage", "vision.classes.manage")),
            ("Safety & Violations Officer", "Reviews safety violations and warehouse exceptions.",
             ("dashboard.view", "violations.view", "violations.manage", "gate.violation.view", "gate.violation.manage")),
            ("Operations Copilot Lead", "Warehouse AI Copilot intelligence & reporting oversight.",
             tuple(sorted(set(starter["executive"][3]) | {"reports.export", "copilot.use"}))),
        ]
    else:
        raise IamError(400, "invalid_pack", "Choose 3_role, 5_role, or 15_role.")

    created = 0
    conn = _conn()
    try:
        with conn:
            for rname, rdesc, rperms in specs:
                valid_perms = [p for p in rperms if p in all_non_platform]
                row = conn.execute(
                    "SELECT id FROM roles WHERE company_id = ? AND LOWER(name) = LOWER(?)",
                    (int(company_id), rname)
                ).fetchone()
                if row:
                    rid = row[0]
                    conn.execute("UPDATE roles SET is_active = 1, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                 (rdesc, rid))
                else:
                    cur = conn.execute(
                        "INSERT INTO roles (company_id, name, description, is_builtin, is_active) VALUES (?, ?, ?, 0, 1)",
                        (int(company_id), rname, rdesc)
                    )
                    rid = cur.lastrowid
                    created += 1
                conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (rid,))
                conn.executemany(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_key) VALUES (?, ?)",
                    [(rid, pk) for pk in valid_perms]
                )
    finally:
        conn.close()

    auth_service.audit("role.pack_applied", actor=actor, company_id=company_id, resource_type="role_pack",
                       resource_id=pack_key, after={"pack": pack_key, "created": created}, ip=ip)
    return {"pack": pack_key, "created": created, "coverage": roles_coverage_summary(company_id)}
