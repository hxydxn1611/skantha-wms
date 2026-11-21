"""
Data isolation by company and warehouse (RBAC Phase 3A).

A *scope* says whose data a piece of code may see and change:

  Scope.warehouse(company_id, warehouse_id)  one warehouse (the normal case)
  Scope.company_all(company_id)              every warehouse of one company - READ-ONLY (D13)
  Scope.platform_all()                       every company - READ-ONLY (D13)
  Scope.platform_full(company_id, wh_id)     Platform Admin: every company, read AND write.
                                             New rows without an owner go to the selected
                                             warehouse; nothing else is fenced.
  no scope (None)                            system code: startup, migrations, console tools

The scope lives in a thread-local. Requests set it in before_request and clear it on
teardown; camera/ANPR threads set it from the camera's warehouse (camera_scope()).

Enforcement layers
  1. Writes: every connection from db.get_db() made while a scope is active installs
     TEMP triggers before its first write. New rows are stamped with the scope's
     company/warehouse; updates and deletes of rows outside the scope are skipped
     (RAISE(IGNORE)); read-only scopes refuse every write. Nothing to remember per query.
  2. Reads: list queries add filter() conditions; single records named by a route are
     checked centrally (owned_or_absent) before the handler runs.

Isolation switches on only after the approved ownership backfill has been applied
(migration step rbac_v1/007_ownership_backfill); until then behaviour is unchanged.
"""
from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

COMPANY_TABLES = ("skus", "sku_images", "object_classes", "glass_measurement_profiles", "trained_workers",
                  "sku_count_examples", "sku_photo_queries")
WAREHOUSE_TABLES = ("bins", "inventory", "expected_deliveries", "gate_passes", "vehicle_log", "invoices",
                    "outbound_orders", "pallets", "violations_log", "vision_counting_submissions",
                    "cameras", "vision_zones", "stock_movements", "stock_min_levels")
# Warehouse tables created by a later migration step (born with their owner columns), so the
# older ownership steps skip them on a fresh database.
LATER_TABLES = ("stock_movements", "stock_min_levels", "sku_count_examples", "sku_photo_queries")
# child table -> (child column, parent table, parent column)
CHILD_TABLES: Dict[str, Tuple[str, str, str]] = {
    "outbound_items": ("order_id", "outbound_orders", "id"),
    "pallet_items": ("pallet_id", "pallets", "pallet_id"),
    "vision_camera_configs": ("camera_id", "cameras", "camera_id"),
    "vision_camera_object_classes": ("camera_id", "cameras", "camera_id"),
    "vision_zone_cameras": ("zone_id", "vision_zones", "id"),
    "vision_zone_camera_rois": ("zone_id", "vision_zones", "id"),
}
SCOPED_TABLES = COMPANY_TABLES + WAREHOUSE_TABLES

ISOLATION_STEP = "007_ownership_backfill"


@dataclass(frozen=True)
class Scope:
    kind: str                      # 'warehouse' | 'company_all' | 'platform_all' | 'platform_full'
    company_id: Optional[int] = None
    warehouse_id: Optional[int] = None

    @property
    def read_only(self) -> bool:
        return self.kind in ("company_all", "platform_all")

    @property
    def unrestricted(self) -> bool:
        """Sees every company's data (no read filters, no record checks)."""
        return self.kind in ("platform_all", "platform_full")

    @staticmethod
    def warehouse(company_id: int, warehouse_id: int) -> "Scope":
        return Scope("warehouse", int(company_id), int(warehouse_id))

    @staticmethod
    def company_all(company_id: int) -> "Scope":
        return Scope("company_all", int(company_id), None)

    @staticmethod
    def platform_all() -> "Scope":
        return Scope("platform_all", None, None)

    @staticmethod
    def platform_full(company_id: Optional[int], warehouse_id: Optional[int]) -> "Scope":
        return Scope("platform_full",
                     int(company_id) if company_id is not None else None,
                     int(warehouse_id) if warehouse_id is not None else None)


# ----------------------------------------------------------------------------- thread-local scope
_local = threading.local()


def get_scope() -> Optional[Scope]:
    return getattr(_local, "scope", None)


def set_scope(scope: Optional[Scope]) -> None:
    _local.scope = scope


def clear_scope() -> None:
    _local.scope = None


@contextlib.contextmanager
def using(scope: Optional[Scope]):
    prev = get_scope()
    set_scope(scope)
    try:
        yield scope
    finally:
        set_scope(prev)


# ----------------------------------------------------------------------------- isolation switch
_isolation_by_db: Dict[str, bool] = {}
_isolation_lock = threading.Lock()


def isolation_enabled(conn: Optional[sqlite3.Connection] = None) -> bool:
    """True once the approved ownership backfill has been applied to this database, unless
    RBAC_MODE=off (the instant rollback switch turns isolation off too; no data changes)."""
    import db
    import rbac_config
    if rbac_config.get_rbac_mode() == "off":
        return False
    key = db.DB_PATH
    val = _isolation_by_db.get(key)
    if val is not None:
        return val
    with _isolation_lock:
        val = _isolation_by_db.get(key)
        if val is None:
            val = _read_isolation_flag(conn)
            _isolation_by_db[key] = val
    return val


def _read_isolation_flag(conn: Optional[sqlite3.Connection]) -> bool:
    import db
    own = conn is None
    c = conn or sqlite3.connect(db.DB_PATH, timeout=15)
    try:
        row = c.execute("SELECT 1 FROM schema_migrations WHERE migration_set = 'rbac_v1' AND step = ?",
                        (ISOLATION_STEP,)).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
    finally:
        if own:
            c.close()


def reset_isolation_cache() -> None:
    _isolation_by_db.clear()


# ----------------------------------------------------------------------------- write fences
_WRITE_SQL = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|WITH)\b", re.IGNORECASE)


def _guard_sql(scope: Scope) -> str:
    """TEMP triggers for one connection. Literal integer ids only (never user text)."""
    out = []
    if scope.read_only:
        for t in SCOPED_TABLES + tuple(CHILD_TABLES):
            for op in ("INSERT", "UPDATE", "DELETE"):
                out.append(f"CREATE TEMP TRIGGER IF NOT EXISTS rbac_ro_{t}_{op.lower()} BEFORE {op} ON main.{t} "
                           f"BEGIN SELECT RAISE(ABORT, 'rbac_read_only_scope'); END;")
        return "\n".join(out)

    c, w = int(scope.company_id), int(scope.warehouse_id)
    for t in COMPANY_TABLES:
        out.append(f"""
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_ins_check BEFORE INSERT ON main.{t}
WHEN NEW.company_id IS NOT NULL AND NEW.company_id != {c}
BEGIN SELECT RAISE(ABORT, 'rbac_scope_violation'); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_stamp AFTER INSERT ON main.{t}
WHEN NEW.company_id IS NULL
BEGIN UPDATE {t} SET company_id = {c} WHERE rowid = NEW.rowid; END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_upd BEFORE UPDATE ON main.{t}
WHEN OLD.company_id IS NOT {c} AND NOT (OLD.company_id IS NULL AND NEW.company_id IS {c})
BEGIN SELECT RAISE(IGNORE); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_move BEFORE UPDATE OF company_id ON main.{t}
WHEN OLD.company_id IS {c} AND NEW.company_id IS NOT {c}
BEGIN SELECT RAISE(ABORT, 'rbac_scope_violation'); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_del BEFORE DELETE ON main.{t}
WHEN OLD.company_id IS NOT {c}
BEGIN SELECT RAISE(IGNORE); END;""")
    for t in WAREHOUSE_TABLES:
        out.append(f"""
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_ins_check BEFORE INSERT ON main.{t}
WHEN (NEW.warehouse_id IS NOT NULL AND NEW.warehouse_id != {w}) OR (NEW.company_id IS NOT NULL AND NEW.company_id != {c})
BEGIN SELECT RAISE(ABORT, 'rbac_scope_violation'); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_stamp AFTER INSERT ON main.{t}
WHEN NEW.warehouse_id IS NULL OR NEW.company_id IS NULL
BEGIN UPDATE {t} SET warehouse_id = COALESCE(warehouse_id, {w}), company_id = COALESCE(company_id, {c}) WHERE rowid = NEW.rowid; END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_upd BEFORE UPDATE ON main.{t}
WHEN OLD.warehouse_id IS NOT {w} AND NOT (OLD.warehouse_id IS NULL AND NEW.warehouse_id IS {w})
BEGIN SELECT RAISE(IGNORE); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_move BEFORE UPDATE OF warehouse_id, company_id ON main.{t}
WHEN OLD.warehouse_id IS {w} AND (NEW.warehouse_id IS NOT {w} OR NEW.company_id IS NOT {c})
BEGIN SELECT RAISE(ABORT, 'rbac_scope_violation'); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_del BEFORE DELETE ON main.{t}
WHEN OLD.warehouse_id IS NOT {w}
BEGIN SELECT RAISE(IGNORE); END;""")
    for t, (col, parent, pcol) in CHILD_TABLES.items():
        pcond = f"p.warehouse_id = {w}"
        out.append(f"""
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_ins_check BEFORE INSERT ON main.{t}
WHEN NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.{pcol} = NEW.{col} AND {pcond})
BEGIN SELECT RAISE(ABORT, 'rbac_scope_violation'); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_upd BEFORE UPDATE ON main.{t}
WHEN NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.{pcol} = OLD.{col} AND {pcond})
BEGIN SELECT RAISE(IGNORE); END;
CREATE TEMP TRIGGER IF NOT EXISTS rbac_{t}_del BEFORE DELETE ON main.{t}
WHEN NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.{pcol} = OLD.{col} AND {pcond})
BEGIN SELECT RAISE(IGNORE); END;""")
    return "\n".join(out)


_GUARD_CACHE: Dict[Scope, str] = {}


def guard_sql(scope: Scope) -> str:
    sql = _GUARD_CACHE.get(scope)
    if sql is None:
        sql = _guard_sql(scope)
        if len(_GUARD_CACHE) > 256:
            _GUARD_CACHE.clear()
        _GUARD_CACHE[scope] = sql
    return sql


class ScopedCursor(sqlite3.Cursor):
    def execute(self, sql, *args):
        self.connection._rbac_guard(sql)
        return super().execute(sql, *args)

    def executemany(self, sql, *args):
        self.connection._rbac_guard(sql)
        return super().executemany(sql, *args)

    def executescript(self, script):
        self.connection._rbac_guard("INSERT")
        return super().executescript(script)


class ScopedConnection(sqlite3.Connection):
    """sqlite3 connection that fences writes to the scope captured when it was opened.
    Guards are installed lazily, right before the first write statement."""
    _rbac_scope: Optional[Scope] = None
    _rbac_guarded: bool = False

    def _rbac_guard(self, sql) -> None:
        scope = self._rbac_scope
        if scope is None or self._rbac_guarded:
            return
        if isinstance(sql, str) and _WRITE_SQL.match(sql):
            self._rbac_guarded = True
            for stmt in guard_sql(scope).split("END;"):
                if stmt.strip():
                    sqlite3.Connection.execute(self, stmt + "END;")

    def cursor(self, factory=None):
        return super().cursor(factory or ScopedCursor)

    def execute(self, sql, *args):
        self._rbac_guard(sql)
        return super().execute(sql, *args)

    def executemany(self, sql, *args):
        self._rbac_guard(sql)
        return super().executemany(sql, *args)

    def executescript(self, script):
        self._rbac_guard("INSERT")
        return super().executescript(script)


def connection_scope() -> Optional[Scope]:
    """The scope a new connection should be fenced to (None = unrestricted)."""
    scope = get_scope()
    if scope is None:
        return None
    return scope if isolation_enabled() else None


# ----------------------------------------------------------------------------- read filters
def filter(table: str, alias: Optional[str] = None, scope: Optional[Scope] = None) -> Tuple[str, tuple]:
    """SQL condition (starting with ' AND ') and params limiting `table` to the scope.
    Empty when there is no scope, for the platform-wide view, or before isolation is on."""
    scope = scope if scope is not None else get_scope()
    if scope is None or scope.unrestricted or not isolation_enabled():
        return "", ()
    a = f"{alias}." if alias else ""
    if table in COMPANY_TABLES or scope.kind == "company_all":
        if table in CHILD_TABLES:
            col, parent, pcol = CHILD_TABLES[table]
            return (f" AND {a}{col} IN (SELECT {pcol} FROM {parent} WHERE company_id = ?)", (scope.company_id,))
        return f" AND {a}company_id = ?", (scope.company_id,)
    if table in WAREHOUSE_TABLES:
        return f" AND {a}warehouse_id = ?", (scope.warehouse_id,)
    if table in CHILD_TABLES:
        col, parent, pcol = CHILD_TABLES[table]
        return (f" AND {a}{col} IN (SELECT {pcol} FROM {parent} WHERE warehouse_id = ?)", (scope.warehouse_id,))
    return "", ()


def home_filter(table: str, alias: Optional[str] = None, scope: Optional[Scope] = None) -> Tuple[str, tuple]:
    """Like filter(), but the Platform Admin's full-access scope is narrowed to the
    selected warehouse (and its company). Used for 'is this code already taken here?'
    checks and for looking a record up by its code, where codes are unique per company
    (classes) or per warehouse (zones) since Phase 3B."""
    scope = scope if scope is not None else get_scope()
    if scope is not None and scope.kind == "platform_full" and isolation_enabled():
        if scope.company_id is None or scope.warehouse_id is None:
            return "", ()
        return filter(table, alias, Scope.warehouse(scope.company_id, scope.warehouse_id))
    return filter(table, alias, scope)


def owned_or_absent(conn: sqlite3.Connection, table: str, column: str, value) -> bool:
    """False when the record named by `value` exists but belongs to another scope.
    True when it is in scope or does not exist at all (the handler reports 'not found')."""
    scope = get_scope()
    if scope is None or scope.unrestricted or not isolation_enabled():
        return True
    if table not in SCOPED_TABLES and table not in CHILD_TABLES:
        return True
    if not conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,)).fetchone():
        return True
    cond, params = filter(table, scope=scope)
    return conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ?{cond} LIMIT 1", (value,) + params).fetchone() is not None


# ----------------------------------------------------------------------------- cameras (background threads)
_camera_map: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
_camera_lock = threading.Lock()


def refresh_camera_map() -> None:
    """camera_id -> (company_id, warehouse_id), loaded once per camera-registry change.
    Frame loops only read this dict (no database work inside capture/inference/ANPR)."""
    import db
    with using(None):
        conn = db.get_db()
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(cameras)")]
            if "warehouse_id" not in cols:
                return
            rows = conn.execute("SELECT camera_id, company_id, warehouse_id FROM cameras").fetchall()
        finally:
            conn.close()
    with _camera_lock:
        _camera_map.clear()
        for cid, comp, wh in rows:
            _camera_map[str(cid)] = (comp, wh)


def scope_for_camera(camera_id: str) -> Optional[Scope]:
    comp, wh = _camera_map.get(str(camera_id), (None, None))
    if comp is None or wh is None:
        return None
    return Scope.warehouse(comp, wh)


def camera_visible(camera_id: str, scope: Optional[Scope] = None) -> bool:
    """Whether a camera may be shown in the current scope. Cameras with no owner are shown
    only to unscoped code and the Platform Admin's all-companies view (fail closed)."""
    scope = scope if scope is not None else get_scope()
    if scope is None or scope.unrestricted or not isolation_enabled():
        return True
    comp, wh = _camera_map.get(str(camera_id), (None, None))
    if scope.kind == "company_all":
        return comp is not None and comp == scope.company_id
    return wh is not None and wh == scope.warehouse_id


@contextlib.contextmanager
def camera_scope(camera_id: str):
    """Run background work for a camera inside that camera's warehouse."""
    with using(scope_for_camera(camera_id)):
        yield
