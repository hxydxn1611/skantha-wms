"""
Authentication and account security (RBAC Phase 1).

  * passwords: werkzeug hashing (scrypt), policy for new passwords
  * login: uniform errors (H22), per-username lockout and per-IP limit (H29)
  * sessions: `uid` + `session_version` checked on every request (D10, H20)
  * forced password reset for default/guessable passwords (H3)
  * email OTPs: stored as keyed hashes, send and verify limits
  * audit_logs writer for authentication events
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import sqlite3
from typing import Any, Dict, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

import db
import rbac_migration

logger = logging.getLogger(__name__)

LOGIN_WINDOW_MINUTES = 15
MAX_FAILURES_PER_USERNAME = 5
MAX_FAILURES_PER_IP = 20
OTP_SENDS_PER_EMAIL = 3
OTP_SEND_WINDOW_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
MIN_PASSWORD_LENGTH = 10

GENERIC_LOGIN_ERROR = "Invalid username or password."
LOCKED_LOGIN_ERROR = "Too many failed sign-in attempts. Try again in 15 minutes."

# A real hash of a random string: verifying against it costs the same as a real check,
# so unknown usernames cannot be told apart by response time.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


# ----------------------------------------------------------------------------- helpers
def username_key(identifier: Optional[str]) -> str:
    return str(identifier or "").strip().casefold()


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def validate_new_password(password: str, username: str = "", company_name: str = "") -> Optional[str]:
    """Returns an error message, or None when the password is acceptable."""
    pw = password or ""
    if len(pw) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    low = pw.strip().casefold()
    for banned in (username, company_name):
        if banned and low == str(banned).strip().casefold():
            return "Password must not be the same as your username or company name."
    if len(set(pw)) < 4:
        return "Password is too simple. Use a mix of letters, numbers or symbols."
    return None


def audit(action: str, *, actor: Optional[Dict[str, Any]] = None, actor_username: Optional[str] = None,
          company_id: Optional[int] = None, warehouse_id: Optional[int] = None,
          resource_type: Optional[str] = None, resource_id: Optional[str] = None,
          reason: Optional[str] = None, before: Any = None, after: Any = None,
          ip: Optional[str] = None, user_agent: Optional[str] = None, result: str = "success",
          conn: Optional[sqlite3.Connection] = None) -> None:
    """Appends one row to audit_logs. Never raises: auditing must not break the request.
    Passwords, OTPs and tokens must never be passed in before/after."""
    own = conn is None
    try:
        c = conn or db.get_db()
        try:
            c.execute("""
                INSERT INTO audit_logs (actor_user_id, actor_username, company_id, warehouse_id, action,
                    resource_type, resource_id, reason, before_json, after_json, ip, user_agent, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ((actor or {}).get("id"), actor_username or (actor or {}).get("username"),
                  company_id, warehouse_id, action, resource_type, resource_id, reason,
                  json.dumps(before, default=str) if before is not None else None,
                  json.dumps(after, default=str) if after is not None else None,
                  ip, (user_agent or "")[:300] or None, result))
            if own:
                c.commit()
        finally:
            if own:
                c.close()
    except Exception as e:
        logger.warning(f"[AUDIT] could not record {action}: {e}")


def user_company_id(user_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[int]:
    own = conn is None
    c = conn or db.get_db()
    try:
        row = c.execute("""
            SELECT company_id FROM user_company_access WHERE user_id = ? AND status = 'Active'
            ORDER BY id LIMIT 1
        """, (user_id,)).fetchone()
        return row[0] if row else None
    finally:
        if own:
            c.close()


# ----------------------------------------------------------------------------- users
def find_user(identifier: str) -> Optional[Dict[str, Any]]:
    """By username or email (case-insensitive), as the login form has always accepted."""
    key = username_key(identifier)
    if not key:
        return None
    conn = db.get_db()
    try:
        row = conn.execute("""
            SELECT * FROM users WHERE LOWER(username) = ? OR LOWER(email) = ?
            ORDER BY CASE WHEN LOWER(username) = ? THEN 0 ELSE 1 END LIMIT 1
        """, (key, key, key)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = db.get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def verify_user_password(user: Dict[str, Any], password: str) -> bool:
    stored = user.get("password_hash") or ""
    if stored:
        try:
            return check_password_hash(stored, password or "")
        except Exception:
            return False
    # Account created by code older than Phase 1 and not migrated yet: compare, then upgrade.
    legacy = user.get("password") or ""
    if legacy and hmac.compare_digest(legacy.encode(), (password or "").encode()):
        conn = db.get_db()
        try:
            with conn:
                conn.execute("UPDATE users SET password_hash = ?, password = '' WHERE id = ?",
                             (hash_password(password), user["id"]))
        finally:
            conn.close()
        return True
    return False


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Safe subset for the browser (no hashes, counters or tokens)."""
    return {k: user.get(k) for k in ("username", "email", "company_name", "assigned_warehouse_code", "role")}


# ----------------------------------------------------------------------------- login
def _recent_failures(conn: sqlite3.Connection, where: str, value: str) -> int:
    return conn.execute(f"""
        SELECT COUNT(*) FROM login_attempts
        WHERE {where} = ? AND success = 0
          AND ts > datetime('now', ?)
          AND ts > COALESCE((SELECT MAX(ts) FROM login_attempts
                             WHERE {where} = ? AND success = 1), '1970-01-01')
    """, (value, f"-{LOGIN_WINDOW_MINUTES} minutes", value)).fetchone()[0]


def _record_attempt(conn: sqlite3.Connection, ukey: str, ip: Optional[str], success: bool, reason: str) -> None:
    conn.execute("INSERT INTO login_attempts (username_key, ip, success, reason) VALUES (?, ?, ?, ?)",
                 (ukey, ip, 1 if success else 0, reason))


def authenticate(identifier: str, password: str, ip: Optional[str] = None,
                 user_agent: Optional[str] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Returns (status, user). status: ok | invalid | locked.
    Unknown usernames, wrong passwords and inactive accounts all look the same (H22)."""
    ukey = username_key(identifier)
    conn = db.get_db()
    try:
        if ukey and (_recent_failures(conn, "username_key", ukey) >= MAX_FAILURES_PER_USERNAME
                     or (ip and _recent_failures(conn, "ip", ip) >= MAX_FAILURES_PER_IP)):
            with conn:
                _record_attempt(conn, ukey, ip, False, "locked")
            audit("auth.locked", actor_username=ukey, ip=ip, user_agent=user_agent, result="denied")
            return "locked", None
    finally:
        conn.close()

    user = find_user(identifier) if ukey and password else None
    ok = verify_user_password(user, password) if user else (check_password_hash(_DUMMY_HASH, password or "x") and False)
    if ok and not user.get("is_active", 1):
        ok = False

    conn = db.get_db()
    try:
        with conn:
            _record_attempt(conn, ukey or "(empty)", ip, ok, "ok" if ok else "invalid")
            if user:
                if ok:
                    conn.execute("""UPDATE users SET failed_login_count = 0, locked_until = NULL,
                                    last_login_at = CURRENT_TIMESTAMP WHERE id = ?""", (user["id"],))
                else:
                    conn.execute("UPDATE users SET failed_login_count = failed_login_count + 1 WHERE id = ?",
                                 (user["id"],))
                    if _recent_failures(conn, "username_key", ukey) >= MAX_FAILURES_PER_USERNAME:
                        conn.execute(f"UPDATE users SET locked_until = datetime('now', '+{LOGIN_WINDOW_MINUTES} minutes') WHERE id = ?",
                                     (user["id"],))
    finally:
        conn.close()

    if not ok:
        audit("auth.login_failed", actor_username=ukey, ip=ip, user_agent=user_agent, result="denied")
        return "invalid", None
    fresh = get_user_by_id(user["id"])
    audit("auth.login", actor=fresh, company_id=user_company_id(fresh["id"]), ip=ip, user_agent=user_agent)
    return "ok", fresh


# ----------------------------------------------------------------------------- sessions
def session_payload(user: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What goes into session['user']: the keys the SPA has always used, plus uid/sv."""
    payload = {
        "username": user.get("username"),
        "email": user.get("email"),
        "company_name": user.get("company_name") or "WARLOG Intelligence Systems",
        "assigned_warehouse_code": user.get("assigned_warehouse_code") or "WH-MAIN",
        "role": user.get("role") or "Admin",
        "uid": user["id"],
        "sv": int(user.get("session_version") or 1),
        "must_reset_password": bool(user.get("must_reset_password")),
    }
    payload.update(extra or {})
    return payload


def load_session_user(session_user: Any) -> Optional[Dict[str, Any]]:
    """Validates session['user'] against the database (D10, H20).
    Sessions from before Phase 1 (no uid/sv), deactivated users and sessions whose
    version was bumped (password change, revocation) are rejected."""
    if not isinstance(session_user, dict):
        return None
    uid, sv = session_user.get("uid"), session_user.get("sv")
    if not isinstance(uid, int) or not isinstance(sv, int):
        return None
    conn = db.get_db()
    try:
        row = conn.execute("""
            SELECT id, username, company_name, is_active, session_version, must_reset_password, is_platform_admin
            FROM users WHERE id = ?
        """, (uid,)).fetchone()
    finally:
        conn.close()
    if not row or not row["is_active"] or int(row["session_version"]) != sv:
        return None
    return dict(row)


def set_password(user_id: int, new_password: str, *, clear_reset_flag: bool = True,
                 actor: Optional[Dict[str, Any]] = None, action: str = "auth.password_changed",
                 ip: Optional[str] = None) -> int:
    """Stores a new hash and bumps session_version (logs out every other session).
    Returns the new session version."""
    conn = db.get_db()
    try:
        with conn:
            conn.execute(f"""
                UPDATE users SET password_hash = ?, password = '',
                    must_reset_password = CASE WHEN ? THEN 0 ELSE must_reset_password END,
                    session_version = session_version + 1,
                    failed_login_count = 0, locked_until = NULL
                WHERE id = ?
            """, (hash_password(new_password), 1 if clear_reset_flag else 0, user_id))
            sv = conn.execute("SELECT session_version FROM users WHERE id = ?", (user_id,)).fetchone()[0]
    finally:
        conn.close()
    audit(action, actor=actor or {"id": user_id}, company_id=user_company_id(user_id),
          resource_type="user", resource_id=str(user_id), ip=ip)
    return int(sv)


# ----------------------------------------------------------------------------- signup
def company_exists(name: str) -> bool:
    key = rbac_migration.company_key(name)
    if not key:
        return False
    conn = db.get_db()
    try:
        if conn.execute("SELECT 1 FROM companies WHERE name_key = ?", (key,)).fetchone():
            return True
        for table in ("warehouses", "users"):
            for (n,) in conn.execute(f"SELECT DISTINCT company_name FROM {table} WHERE company_name IS NOT NULL"):
                if rbac_migration.company_key(n) == key:
                    return True
        return False
    finally:
        conn.close()


def provision_company_admin(user_id: int, company_name: str, warehouse_code: Optional[str]) -> int:
    """New-company signup: company row, warehouse link, membership, Company Admin role."""
    conn = db.get_db()
    try:
        with conn:
            company_id = rbac_migration.ensure_company(conn, company_name)
            if warehouse_code:
                conn.execute("UPDATE warehouses SET company_id = ? WHERE UPPER(code) = UPPER(?) AND company_id IS NULL",
                             (company_id, warehouse_code))
            rbac_migration.assign_company_admin(conn, user_id, company_id, created_by=user_id)
        return company_id
    finally:
        conn.close()


# ----------------------------------------------------------------------------- email OTP
hash_otp = db.hash_otp


def new_otp_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def otp_send_allowed(email: str) -> bool:
    conn = db.get_db()
    try:
        n = conn.execute("""
            SELECT COUNT(*) FROM email_otps
            WHERE LOWER(email) = LOWER(?) AND created_at > datetime('now', ?)
        """, (email.strip(), f"-{OTP_SEND_WINDOW_MINUTES} minutes")).fetchone()[0]
        return n < OTP_SENDS_PER_EMAIL
    finally:
        conn.close()
