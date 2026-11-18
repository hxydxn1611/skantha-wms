"""
RBAC migration v1 (RBAC plan, "Migration" steps 1-5; Phase 1).

Additive and idempotent. Each step runs in its own transaction and is recorded in
`schema_migrations`, so a second run skips completed steps and changes nothing.
Before any pending step touches a database file, the file is backed up (SQLite
backup API) to the backups folder, whose access is restricted to the current user.

Steps
  001_schema          new IAM tables, users/warehouses/email_otps columns, indexes,
                      last-admin protection triggers
  002_companies       one `companies` row per distinct company name (case/space-insensitive)
  003_link_warehouses warehouses.company_id
  004_builtin_roles   Platform Admin, Company Admin, User
  005_users           hash every plain-text password (logins keep working), blank the
                      plain-text column, flag default passwords for reset, company
                      membership + Company Admin assignment, Platform Admin flag,
                      purge plain-text email OTPs
  006/007             ownership columns; approved ownership backfill (Phase 3A)
  008_per_company_codes  object class codes unique per company, zone codes unique per
                      warehouse (table rebuild, every row/id/link kept) (Phase 3B)
  009_starter_roles   starter roles for every company (editable custom roles) (Phase 5)
  010_settings_tables platform_settings, company_settings (Phase 7)
  011_gate_otp_attempts gate_passes.otp_failed_attempts (hardening)

The permission catalogue is synced on every run (idempotent upsert; removed keys retired).
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import sqlite3
import subprocess
import threading
from typing import Callable, Dict, List, Optional, Tuple

from werkzeug.security import generate_password_hash

import rbac_catalog

logger = logging.getLogger(__name__)

MIGRATION_SET = "rbac_v1"
_LOCK = threading.Lock()
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BACKUP_DIR = os.path.join(ROOT_DIR, "backups")


def platform_admin_username() -> str:
    """The account that becomes Platform Admin (RBAC decision D1). Configurable."""
    return (os.environ.get("WARLOG_PLATFORM_ADMIN_USERNAME") or "admin").strip()


def company_key(name: Optional[str]) -> str:
    """Case- and whitespace-insensitive company identity ('  Lion ' == 'lion')."""
    return " ".join(str(name or "").split()).casefold()


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company_key(name)).strip("-") or "company"


# ----------------------------------------------------------------------------- schema
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'Active',
    is_platform_owner INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS permissions (
    key TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    action TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT DEFAULT '',
    sensitive INTEGER NOT NULL DEFAULT 0,
    scope_level TEXT NOT NULL,
    retired INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    is_builtin INTEGER NOT NULL DEFAULT 0,
    builtin_code TEXT UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_roles_company_name ON roles(IFNULL(company_id, 0), name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_key TEXT NOT NULL REFERENCES permissions(key),
    PRIMARY KEY (role_id, permission_key)
);

CREATE TABLE IF NOT EXISTS user_company_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    status TEXT NOT NULL DEFAULT 'Active',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, company_id)
);

CREATE TABLE IF NOT EXISTS user_warehouse_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    warehouse_id INTEGER REFERENCES warehouses(id),      -- NULL = whole company
    role_id INTEGER NOT NULL REFERENCES roles(id),
    is_default INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Active',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_uwa_user_wh_role ON user_warehouse_access(user_id, IFNULL(warehouse_id, 0), role_id);
CREATE INDEX IF NOT EXISTS ix_uwa_company ON user_warehouse_access(company_id, status);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_user_id INTEGER,
    actor_username TEXT,
    company_id INTEGER,
    warehouse_id INTEGER,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    reason TEXT,
    before_json TEXT,
    after_json TEXT,
    ip TEXT,
    user_agent TEXT,
    result TEXT NOT NULL DEFAULT 'success'
);
CREATE INDEX IF NOT EXISTS ix_audit_company_ts ON audit_logs(company_id, ts);
CREATE INDEX IF NOT EXISTS ix_audit_action_ts ON audit_logs(action, ts);

CREATE TABLE IF NOT EXISTS invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    email TEXT NOT NULL,
    role_id INTEGER REFERENCES roles(id),
    warehouse_id INTEGER REFERENCES warehouses(id),
    token_hash TEXT NOT NULL UNIQUE,
    invited_by INTEGER REFERENCES users(id),
    expires_at TIMESTAMP NOT NULL,
    accepted_at TIMESTAMP,
    revoked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    requested_ip TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username_key TEXT NOT NULL,
    ip TEXT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    success INTEGER NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_login_attempts_user ON login_attempts(username_key, ts);
CREATE INDEX IF NOT EXISTS ix_login_attempts_ip ON login_attempts(ip, ts);

CREATE TABLE IF NOT EXISTS gate_pass_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gp_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    actor_user_id INTEGER,
    reason TEXT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_gate_pass_events_gp ON gate_pass_events(gp_id, ts);

CREATE TABLE IF NOT EXISTS warehouse_settings (
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    key TEXT NOT NULL,
    value_json TEXT,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (warehouse_id, key)
);
"""

ADDED_COLUMNS: List[Tuple[str, str, str]] = [
    ("users", "password_hash", "TEXT"),
    ("users", "must_reset_password", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "is_active", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "session_version", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "invited_by", "INTEGER"),
    ("users", "last_login_at", "TIMESTAMP"),
    ("users", "failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "locked_until", "TIMESTAMP"),
    ("users", "is_platform_admin", "INTEGER NOT NULL DEFAULT 0"),
    ("warehouses", "company_id", "INTEGER REFERENCES companies(id)"),
    ("warehouses", "state", "TEXT"),
    ("email_otps", "attempts", "INTEGER NOT NULL DEFAULT 0"),
]

# A company admin = an active, company-wide assignment of the built-in company_admin role.
_COMPANY_ADMIN_ROW = """
    SELECT 1 FROM user_warehouse_access a
    JOIN roles r ON r.id = a.role_id AND r.builtin_code = 'company_admin'
    WHERE a.status = 'Active' AND a.warehouse_id IS NULL
"""

TRIGGERS_SQL = f"""
-- Last-admin protection (RBAC plan, "Authentication and accounts"). Enforced in the
-- database so no code path can remove the last active admin.
CREATE TRIGGER IF NOT EXISTS trg_last_company_admin_user_deactivate
BEFORE UPDATE OF is_active ON users
WHEN OLD.is_active = 1 AND NEW.is_active = 0 AND EXISTS (
    SELECT 1 FROM user_warehouse_access a
    JOIN roles r ON r.id = a.role_id AND r.builtin_code = 'company_admin'
    WHERE a.user_id = OLD.id AND a.status = 'Active' AND a.warehouse_id IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM user_warehouse_access b
        JOIN roles rb ON rb.id = b.role_id AND rb.builtin_code = 'company_admin'
        JOIN users ub ON ub.id = b.user_id AND ub.is_active = 1
        WHERE b.company_id = a.company_id AND b.user_id != OLD.id
          AND b.status = 'Active' AND b.warehouse_id IS NULL))
BEGIN
    SELECT RAISE(ABORT, 'last_company_admin');
END;

CREATE TRIGGER IF NOT EXISTS trg_last_company_admin_assignment_update
BEFORE UPDATE OF status, role_id, warehouse_id ON user_warehouse_access
WHEN OLD.status = 'Active' AND OLD.warehouse_id IS NULL
  AND (NEW.status != 'Active' OR NEW.role_id != OLD.role_id OR NEW.warehouse_id IS NOT NULL)
  AND EXISTS (SELECT 1 FROM roles r WHERE r.id = OLD.role_id AND r.builtin_code = 'company_admin')
  AND EXISTS (SELECT 1 FROM users u WHERE u.id = OLD.user_id AND u.is_active = 1)
  AND NOT EXISTS (
    SELECT 1 FROM user_warehouse_access b
    JOIN roles rb ON rb.id = b.role_id AND rb.builtin_code = 'company_admin'
    JOIN users ub ON ub.id = b.user_id AND ub.is_active = 1
    WHERE b.company_id = OLD.company_id AND b.id != OLD.id
      AND b.status = 'Active' AND b.warehouse_id IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'last_company_admin');
END;

CREATE TRIGGER IF NOT EXISTS trg_last_company_admin_assignment_delete
BEFORE DELETE ON user_warehouse_access
WHEN OLD.status = 'Active' AND OLD.warehouse_id IS NULL
  AND EXISTS (SELECT 1 FROM roles r WHERE r.id = OLD.role_id AND r.builtin_code = 'company_admin')
  AND EXISTS (SELECT 1 FROM users u WHERE u.id = OLD.user_id AND u.is_active = 1)
  AND NOT EXISTS (
    SELECT 1 FROM user_warehouse_access b
    JOIN roles rb ON rb.id = b.role_id AND rb.builtin_code = 'company_admin'
    JOIN users ub ON ub.id = b.user_id AND ub.is_active = 1
    WHERE b.company_id = OLD.company_id AND b.id != OLD.id
      AND b.status = 'Active' AND b.warehouse_id IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'last_company_admin');
END;

CREATE TRIGGER IF NOT EXISTS trg_last_platform_admin_update
BEFORE UPDATE OF is_platform_admin, is_active ON users
WHEN OLD.is_platform_admin = 1 AND OLD.is_active = 1
  AND (NEW.is_platform_admin = 0 OR NEW.is_active = 0)
  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id != OLD.id AND u.is_platform_admin = 1 AND u.is_active = 1)
BEGIN
    SELECT RAISE(ABORT, 'last_platform_admin');
END;

CREATE TRIGGER IF NOT EXISTS trg_last_admin_user_delete
BEFORE DELETE ON users
WHEN (OLD.is_platform_admin = 1 AND OLD.is_active = 1
      AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id != OLD.id AND u.is_platform_admin = 1 AND u.is_active = 1))
  OR EXISTS (
    SELECT 1 FROM user_warehouse_access a
    JOIN roles r ON r.id = a.role_id AND r.builtin_code = 'company_admin'
    WHERE a.user_id = OLD.id AND a.status = 'Active' AND a.warehouse_id IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM user_warehouse_access b
        JOIN roles rb ON rb.id = b.role_id AND rb.builtin_code = 'company_admin'
        JOIN users ub ON ub.id = b.user_id AND ub.is_active = 1
        WHERE b.company_id = a.company_id AND b.user_id != OLD.id
          AND b.status = 'Active' AND b.warehouse_id IS NULL))
BEGIN
    SELECT RAISE(ABORT, 'last_admin');
END;
"""


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def _step_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    for table, col, decl in ADDED_COLUMNS:
        if col not in _columns(conn, table):
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {col} {decl}')
    conn.execute("CREATE INDEX IF NOT EXISTS ix_warehouses_company_id ON warehouses(company_id)")
    conn.executescript(TRIGGERS_SQL)


def _company_names(conn: sqlite3.Connection) -> List[str]:
    names: List[str] = []
    for sql in ("SELECT company_name FROM warehouses ORDER BY id",
                "SELECT company_name FROM users ORDER BY id"):
        names += [r[0] for r in conn.execute(sql) if r[0] and str(r[0]).strip()]
    return names


def ensure_company(conn: sqlite3.Connection, name: str) -> int:
    """Returns the id of the company called `name` (case/space-insensitive), creating it if needed."""
    key = company_key(name)
    row = conn.execute("SELECT id FROM companies WHERE name_key = ?", (key,)).fetchone()
    if row:
        return row[0]
    slug, n = _slugify(name), 1
    while conn.execute("SELECT 1 FROM companies WHERE slug = ?", (slug if n == 1 else f"{slug}-{n}",)).fetchone():
        n += 1
    slug = slug if n == 1 else f"{slug}-{n}"
    cur = conn.execute("INSERT INTO companies (name, name_key, slug) VALUES (?, ?, ?)",
                       (" ".join(str(name).split()), key, slug))
    ensure_starter_roles(conn, cur.lastrowid)
    return cur.lastrowid


def ensure_starter_roles(conn: sqlite3.Connection, company_id: int) -> int:
    """Creates the starter roles (rbac_catalog.STARTER_ROLES) a company doesn't have yet,
    as ordinary custom roles. A starter role the admin renamed, edited or deactivated is
    never recreated or reset; a role the admin already named the same way is left alone.
    No-op until migration 009 has added roles.template_key. Returns how many were created."""
    if "template_key" not in _columns(conn, "roles"):
        return 0
    if not conn.execute("SELECT 1 FROM permissions LIMIT 1").fetchone():
        return 0  # catalogue not synced yet (fresh install mid-migration); step 009 seeds later
    created = 0
    for tkey, name, desc, perms in rbac_catalog.STARTER_ROLES:
        if conn.execute("SELECT 1 FROM roles WHERE company_id = ? AND template_key = ?", (company_id, tkey)).fetchone():
            continue
        if conn.execute("SELECT 1 FROM roles WHERE company_id = ? AND LOWER(name) = LOWER(?)", (company_id, name)).fetchone():
            continue
        rid = conn.execute("""INSERT INTO roles (company_id, name, description, is_builtin, builtin_code, is_active,
                              template_key) VALUES (?, ?, ?, 0, NULL, 1, ?)""", (company_id, name, desc, tkey)).lastrowid
        conn.executemany("INSERT OR IGNORE INTO role_permissions (role_id, permission_key) VALUES (?, ?)",
                         [(rid, k) for k in sorted(set(perms))])
        created += 1
    return created


def _step_settings_tables(conn: sqlite3.Connection) -> None:
    """Phase 7: platform settings (e.g. the RTMP stream key) and per-company settings
    (e.g. Copilot web search, audit retention). Additive."""
    conn.execute("""CREATE TABLE IF NOT EXISTS platform_settings (
        key TEXT PRIMARY KEY, value_json TEXT, updated_by INTEGER, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS company_settings (
        company_id INTEGER NOT NULL REFERENCES companies(id), key TEXT NOT NULL, value_json TEXT,
        updated_by INTEGER, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (company_id, key))""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_ts ON audit_logs(ts)")


def _step_gate_otp_attempts(conn: sqlite3.Connection) -> None:
    """Hardening: wrong gate-OTP tries are counted per pass (5 tries, then the code is void)."""
    if "otp_failed_attempts" not in _columns(conn, "gate_passes"):
        conn.execute("ALTER TABLE gate_passes ADD COLUMN otp_failed_attempts INTEGER NOT NULL DEFAULT 0")


def _step_starter_roles(conn: sqlite3.Connection) -> None:
    """Phase 5: starter roles (Gate Security, Dock Supervisor, ...) for every company."""
    if "template_key" not in _columns(conn, "roles"):
        conn.execute("ALTER TABLE roles ADD COLUMN template_key TEXT")
    sync_catalog(conn)
    for (cid,) in conn.execute("SELECT id FROM companies ORDER BY id").fetchall():
        ensure_starter_roles(conn, cid)


def _step_companies(conn: sqlite3.Connection) -> None:
    for name in _company_names(conn):
        ensure_company(conn, name)
    row = conn.execute("SELECT company_name FROM users WHERE LOWER(username) = LOWER(?)",
                       (platform_admin_username(),)).fetchone()
    if row and row[0]:
        conn.execute("UPDATE companies SET is_platform_owner = 1 WHERE name_key = ?", (company_key(row[0]),))


def _step_link_warehouses(conn: sqlite3.Connection) -> None:
    for wid, cname in conn.execute("SELECT id, company_name FROM warehouses WHERE company_id IS NULL").fetchall():
        if cname and str(cname).strip():
            conn.execute("UPDATE warehouses SET company_id = ? WHERE id = ?", (ensure_company(conn, cname), wid))


def _step_builtin_roles(conn: sqlite3.Connection) -> None:
    for code, name, desc in rbac_catalog.BUILTIN_ROLES:
        conn.execute("""
            INSERT OR IGNORE INTO roles (company_id, name, description, is_builtin, builtin_code, is_active)
            VALUES (NULL, ?, ?, 1, ?, 1)
        """, (name, desc, code))


def builtin_role_id(conn: sqlite3.Connection, code: str) -> int:
    return conn.execute("SELECT id FROM roles WHERE builtin_code = ?", (code,)).fetchone()[0]


def must_reset_for(username: str, plain_password: str) -> bool:
    """Default or trivially guessable passwords must be replaced at next login."""
    p = (plain_password or "").strip().casefold()
    return p in {(username or "").strip().casefold(), "admin", "password", "123456", "12345678"}


def assign_company_admin(conn: sqlite3.Connection, user_id: int, company_id: int,
                         created_by: Optional[int] = None) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO user_company_access (user_id, company_id, status, created_by)
        VALUES (?, ?, 'Active', ?)
    """, (user_id, company_id, created_by))
    conn.execute("""
        INSERT OR IGNORE INTO user_warehouse_access (user_id, company_id, warehouse_id, role_id, is_default, status, created_by)
        VALUES (?, ?, NULL, ?, 1, 'Active', ?)
    """, (user_id, company_id, builtin_role_id(conn, "company_admin"), created_by))


def _step_users(conn: sqlite3.Connection) -> None:
    pa_name = platform_admin_username().casefold()
    users = conn.execute("""
        SELECT id, username, password, password_hash, company_name, assigned_warehouse_code, role
        FROM users ORDER BY id
    """).fetchall()
    for uid, username, plain, phash, cname, wh_code, role in users:
        if not phash and plain:
            conn.execute("""
                UPDATE users SET password_hash = ?, password = '', must_reset_password = ?
                WHERE id = ?
            """, (generate_password_hash(plain), 1 if must_reset_for(username, plain) else 0, uid))
        elif plain:
            conn.execute("UPDATE users SET password = '' WHERE id = ?", (uid,))

        company_id = ensure_company(conn, cname) if cname and str(cname).strip() else None
        if company_id is None and wh_code:
            row = conn.execute("SELECT company_id FROM warehouses WHERE UPPER(code) = UPPER(?)", (wh_code,)).fetchone()
            company_id = row[0] if row else None
        if company_id is not None:
            if (role or "Admin").strip().casefold() == "admin":
                assign_company_admin(conn, uid, company_id)
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO user_company_access (user_id, company_id, status) VALUES (?, ?, 'Active')
                """, (uid, company_id))
                wh = conn.execute("SELECT id FROM warehouses WHERE UPPER(code) = UPPER(?)", (wh_code or "",)).fetchone()
                conn.execute("""
                    INSERT OR IGNORE INTO user_warehouse_access (user_id, company_id, warehouse_id, role_id, is_default, status)
                    VALUES (?, ?, ?, ?, 1, 'Active')
                """, (uid, company_id, wh[0] if wh else None, builtin_role_id(conn, "user")))

        if (username or "").casefold() == pa_name:
            conn.execute("UPDATE users SET is_platform_admin = 1 WHERE id = ?", (uid,))

    # H19: old OTP rows hold plain-text codes; new codes are stored hashed.
    conn.execute("DELETE FROM email_otps")


def _step_ownership_columns(conn: sqlite3.Connection) -> None:
    """Phase 3A: nullable ownership columns, no defaults (a row without an owner is
    visible to the Platform Admin only - fail closed, never silently WH-MAIN)."""
    import rbac_scope
    # Created lazily by worker_recognition_service; same definition, so its own
    # CREATE TABLE IF NOT EXISTS stays a no-op (fresh installs).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trained_workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'Operator',
            photo_path TEXT,
            signature_json TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    for t in rbac_scope.COMPANY_TABLES:
        if "company_id" not in _columns(conn, t):
            conn.execute(f'ALTER TABLE "{t}" ADD COLUMN company_id INTEGER REFERENCES companies(id)')
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_company_id ON {t}(company_id)")
    for t in rbac_scope.WAREHOUSE_TABLES:
        if "company_id" not in _columns(conn, t):
            conn.execute(f'ALTER TABLE "{t}" ADD COLUMN company_id INTEGER REFERENCES companies(id)')
        if "warehouse_id" not in _columns(conn, t):
            conn.execute(f'ALTER TABLE "{t}" ADD COLUMN warehouse_id INTEGER REFERENCES warehouses(id)')
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_warehouse_id ON {t}(warehouse_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_company_id ON {t}(company_id)")
    for t in ("gate_passes", "vehicle_log"):
        if "legacy_test" not in _columns(conn, t):
            conn.execute(f'ALTER TABLE "{t}" ADD COLUMN legacy_test INTEGER NOT NULL DEFAULT 0')


def _ownership_approved(conn: sqlite3.Connection) -> bool:
    import rbac_ownership
    return rbac_ownership.approved_proposal(conn) is not None


def _step_ownership_backfill(conn: sqlite3.Connection) -> None:
    """Writes the ownership the owner approved (scripts/rbac_ownership.py approve).
    Row counts of every scoped table must be identical before and after."""
    import rbac_ownership
    import rbac_scope
    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in rbac_scope.SCOPED_TABLES + tuple(rbac_scope.CHILD_TABLES)}
    counts = rbac_ownership.apply(conn, rbac_ownership.approved_proposal(conn))
    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    if before != after:
        raise RuntimeError(f"ownership backfill changed row counts: {before} -> {after}")
    logger.info(f"[RBAC] ownership backfill: {counts}")


# ----------------------------------------------------------------------------- 008 (Phase 3B)
_NEW_OBJECT_CLASSES = """
    CREATE TABLE object_classes__new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'Active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        company_id INTEGER REFERENCES companies(id),
        UNIQUE(company_id, code)
    )"""
_NEW_CAMERA_CLASSES = """
    CREATE TABLE vision_camera_object_classes__new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT NOT NULL,
        class_code TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(camera_id, class_code),
        FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
    )"""
_NEW_VISION_ZONES = """
    CREATE TABLE vision_zones__new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zone_code TEXT NOT NULL,
        zone_name TEXT NOT NULL,
        zone_type TEXT NOT NULL,
        warehouse TEXT NOT NULL DEFAULT 'Warehouse A',
        description TEXT,
        status TEXT DEFAULT 'Active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        company_id INTEGER REFERENCES companies(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        UNIQUE(warehouse_id, zone_code)
    )"""
# A camera's class links follow its company's class: renaming or deleting a class
# (which a camera link used to do through ON UPDATE/DELETE CASCADE on the global code)
# now applies to that company's cameras only.
_CLASS_LINK_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_object_classes_code_rename AFTER UPDATE OF code ON object_classes
WHEN NEW.code IS NOT OLD.code
BEGIN
    UPDATE vision_camera_object_classes SET class_code = NEW.code
    WHERE class_code = OLD.code
      AND camera_id IN (SELECT camera_id FROM cameras WHERE company_id IS NEW.company_id);
END;
CREATE TRIGGER IF NOT EXISTS trg_object_classes_delete_links AFTER DELETE ON object_classes
BEGIN
    DELETE FROM vision_camera_object_classes
    WHERE class_code = OLD.code
      AND camera_id IN (SELECT camera_id FROM cameras WHERE company_id IS OLD.company_id);
END;
"""


def _rebuild(conn: sqlite3.Connection, table: str, create_sql: str, indexes: List[str]) -> None:
    """SQLite 12-step table rebuild (foreign keys are off for the whole step)."""
    old_cols = _columns(conn, table)
    conn.execute(create_sql)
    new_cols = _columns(conn, f"{table}__new")
    cols = ", ".join(f'"{c}"' for c in old_cols if c in new_cols)
    before = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    conn.execute(f'INSERT INTO "{table}__new" ({cols}) SELECT {cols} FROM "{table}"')
    after = conn.execute(f'SELECT COUNT(*) FROM "{table}__new"').fetchone()[0]
    if before != after:
        raise RuntimeError(f"rebuild of {table} changed row count {before} -> {after}")
    conn.execute(f'DROP TABLE "{table}"')
    conn.execute(f'ALTER TABLE "{table}__new" RENAME TO "{table}"')
    for ix in indexes:
        conn.execute(ix)


def _step_per_company_codes(conn: sqlite3.Connection) -> None:
    """Phase 3B: object class codes are unique per company (BOX, WORKER ... stay the
    detector's names for every company) and zone codes unique per warehouse.
    Only the uniqueness rule changes; every row, id and link is kept."""
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        _rebuild(conn, "object_classes", _NEW_OBJECT_CLASSES, [
            "CREATE INDEX IF NOT EXISTS idx_object_classes_code ON object_classes(code)",
            "CREATE INDEX IF NOT EXISTS idx_object_classes_status ON object_classes(status)",
            "CREATE INDEX IF NOT EXISTS ix_object_classes_company_id ON object_classes(company_id)",
        ])
        _rebuild(conn, "vision_camera_object_classes", _NEW_CAMERA_CLASSES, [
            "CREATE INDEX IF NOT EXISTS idx_vision_cam_obj_cam ON vision_camera_object_classes(camera_id)",
            "CREATE INDEX IF NOT EXISTS idx_vision_cam_obj_class ON vision_camera_object_classes(class_code)",
        ])
        _rebuild(conn, "vision_zones", _NEW_VISION_ZONES, [
            "CREATE INDEX IF NOT EXISTS idx_vision_zones_code ON vision_zones(zone_code)",
            "CREATE INDEX IF NOT EXISTS idx_vision_zones_type ON vision_zones(zone_type)",
            "CREATE INDEX IF NOT EXISTS idx_vision_zones_warehouse ON vision_zones(warehouse)",
            "CREATE INDEX IF NOT EXISTS idx_vision_zones_status ON vision_zones(status)",
            "CREATE INDEX IF NOT EXISTS ix_vision_zones_warehouse_id ON vision_zones(warehouse_id)",
            "CREATE INDEX IF NOT EXISTS ix_vision_zones_company_id ON vision_zones(company_id)",
        ])
        for stmt in _CLASS_LINK_TRIGGERS.split("END;"):
            if stmt.strip():
                conn.execute(stmt + "END;")
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"foreign key check failed after rebuild: {bad[:5]}")
    except Exception:
        conn.rollback()
        conn.execute("PRAGMA foreign_keys = ON")
        raise


STEPS: List[Tuple[str, Callable[[sqlite3.Connection], None]]] = [
    ("001_schema", _step_schema),
    ("002_companies", _step_companies),
    ("003_link_warehouses", _step_link_warehouses),
    ("004_builtin_roles", _step_builtin_roles),
    ("005_users", _step_users),
    ("006_ownership_columns", _step_ownership_columns),
    ("007_ownership_backfill", _step_ownership_backfill),
    ("008_per_company_codes", _step_per_company_codes),
    ("009_starter_roles", _step_starter_roles),
    ("010_settings_tables", _step_settings_tables),
    ("011_gate_otp_attempts", _step_gate_otp_attempts),
]
# Steps that wait for something (they stay pending, and trigger no backup, until ready).
STEP_READY: Dict[str, Callable[[sqlite3.Connection], bool]] = {
    "007_ownership_backfill": _ownership_approved,
}


def sync_catalog(conn: sqlite3.Connection) -> None:
    """Upserts the permission catalogue; keys no longer in code are retired, never deleted."""
    if "permissions" not in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
        return
    current = {r[0]: tuple(r[1:]) for r in conn.execute(
        "SELECT key, module, action, label, description, sensitive, scope_level, retired FROM permissions")}
    for p in rbac_catalog.PERMISSION_CATALOG:
        want = (p.module, p.action, p.label, p.description, int(p.sensitive), p.scope_level, 0)
        if current.get(p.key) != want:
            conn.execute("""
                INSERT INTO permissions (key, module, action, label, description, sensitive, scope_level, retired)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(key) DO UPDATE SET module = excluded.module, action = excluded.action,
                    label = excluded.label, description = excluded.description,
                    sensitive = excluded.sensitive, scope_level = excluded.scope_level, retired = 0
            """, (p.key, *want[:-1]))
    retired = set(current) - set(rbac_catalog.PERMISSIONS_BY_KEY)
    for key in retired:
        if current[key][-1] != 1:
            conn.execute("UPDATE permissions SET retired = 1 WHERE key = ?", (key,))


# ----------------------------------------------------------------------------- backups
def restrict_to_current_user(path: str) -> None:
    """Backups contain password data from before migration: only the current OS user may read them."""
    try:
        if os.name == "nt":
            user = os.environ.get("USERNAME")
            if user:
                subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        else:
            os.chmod(path, 0o700)
    except Exception as e:  # never block the migration on this
        logger.warning(f"[RBAC] Could not restrict permissions on {path}: {e}")


def backup_database(db_path: str) -> Optional[str]:
    backup_dir = os.environ.get("WARLOG_BACKUP_DIR") or DEFAULT_BACKUP_DIR
    os.makedirs(backup_dir, exist_ok=True)
    restrict_to_current_user(backup_dir)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"pre_{MIGRATION_SET}_{stamp}.db")
    src = sqlite3.connect(db_path, timeout=30)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    check = sqlite3.connect(dst)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        raise RuntimeError(f"Backup integrity check failed for {dst}: {ok}")
    logger.info(f"[RBAC] Pre-migration backup written to {dst}")
    return dst


# ----------------------------------------------------------------------------- runner
def applied_steps(conn: sqlite3.Connection) -> List[str]:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_set TEXT NOT NULL,
            step TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (migration_set, step)
        )
    """)
    return [r[0] for r in conn.execute("SELECT step FROM schema_migrations WHERE migration_set = ?", (MIGRATION_SET,))]


def migrate(db_path: str) -> Dict[str, object]:
    """Applies pending steps (backing up first) and syncs the catalogue. Safe to call repeatedly."""
    with _LOCK:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                done = applied_steps(conn)
            pending = []
            for name, _ in STEPS:
                if name in done:
                    continue
                if name in STEP_READY and not STEP_READY[name](conn):
                    break  # waits (e.g. for the owner's approval); later steps wait too
                pending.append(name)
            backup = None
            if pending and os.environ.get("WARLOG_SKIP_MIGRATION_BACKUP") != "1":
                backup = backup_database(db_path)
            for name, fn in STEPS:
                if name not in pending:
                    continue
                with conn:
                    fn(conn)
                    conn.execute("INSERT INTO schema_migrations (migration_set, step) VALUES (?, ?)",
                                 (MIGRATION_SET, name))
                conn.execute("PRAGMA foreign_keys = ON")
                logger.info(f"[RBAC] Migration step {MIGRATION_SET}/{name} applied")
            with conn:
                sync_catalog(conn)
            if pending:
                import rbac_scope
                rbac_scope.reset_isolation_cache()
            return {"applied": pending, "backup": backup}
        finally:
            conn.close()
