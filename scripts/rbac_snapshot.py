"""
RBAC preservation tooling (Phase 0).

Captures a baseline of everything the `admin` account can see today so every
RBAC phase can prove it changed nothing that already works:

  * table fingerprints  - row count + SHA-256 of every row (baseline columns only)
  * file hashes         - every file under static/uploads, static/invoices, static/manifests
  * API snapshot        - JSON returned to `admin` by ~45 read-only GET endpoints

Usage (from the repo root):
  py -3.14 scripts/rbac_snapshot.py baseline            # backup + baseline of the live DB (read-only)
  py -3.14 scripts/rbac_snapshot.py api --db X --out Y  # internal: API snapshot in a fresh process

The live database is only ever READ (sqlite backup API on a read-only URI).
All API calls run against a private copy of the database.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(ROOT_DIR, "webapp")
LIVE_DB = os.path.join(WEBAPP_DIR, "skandha_wms.db")
BACKUP_ROOT = os.path.join(ROOT_DIR, "backups")
FILE_DIRS = [
    os.path.join(WEBAPP_DIR, "static", "uploads"),
    os.path.join(WEBAPP_DIR, "static", "invoices"),
    os.path.join(WEBAPP_DIR, "static", "manifests"),
]

# Read-only GET endpoints captured for the admin parity check.
API_ENDPOINTS: List[str] = [
    "/api/alerts", "/api/bins", "/api/cameras", "/api/cycle_count/activities",
    "/api/deliveries", "/api/gate/auto_dispatch", "/api/gate/multi_status",
    "/api/gate_passes", "/api/industry_blueprints", "/api/integration/overview",
    "/api/inventory", "/api/invoices", "/api/object_classes", "/api/outbound",
    "/api/pallets", "/api/pallets/glass-profiles", "/api/pallets/vision-skus",
    "/api/sku_master", "/api/skus", "/api/staging/cameras", "/api/staging/status",
    "/api/stats", "/api/system/rtmp_status", "/api/telemetry/live",
    "/api/vehicle_log", "/api/violations", "/api/violations/summary",
    "/api/vision/association/status", "/api/vision/box-bin/status",
    "/api/vision/cameras", "/api/vision/dashboard/live",
    "/api/vision/detection/config", "/api/vision/detection/info",
    "/api/vision/detection/samples", "/api/vision/events/status",
    "/api/vision/identity/status", "/api/vision/material-association/status",
    "/api/vision/runtime/cameras", "/api/vision/runtime/status",
    "/api/vision/traceability/materials", "/api/vision/traceability/status",
    "/api/vision/tracking/status", "/api/vision/validation/status",
    "/api/vision/worker-box/status", "/api/vision/zone_types", "/api/vision/zones",
    "/api/warehouses", "/api/warehouses/active",
    "/api/wms/controlled_actions/audit", "/api/wms/controlled_actions/recommendations",
    "/api/workers/trained",
]

# Endpoints whose values are live/synthetic by design: only their shape (keys) is compared.
SHAPE_ONLY_ENDPOINTS = {
    "/api/telemetry/live", "/api/gate/multi_status", "/api/vision/dashboard/live",
    "/api/vision/runtime/status", "/api/vision/runtime/cameras", "/api/system/rtmp_status",
    "/api/staging/status", "/api/staging/cameras", "/api/alerts", "/api/stats",
    "/api/vision/cameras", "/api/cameras", "/api/integration/overview",
    "/api/wms/controlled_actions/recommendations",
}
SHAPE_ONLY_SUFFIXES = ("/status",)

# Keys whose values change with the clock; ignored when comparing values.
VOLATILE_KEY_HINTS = ("time", "date", "_at", "timestamp", "uptime", "fps", "latency",
                      "elapsed", "age", "last_", "now", "ts", "duration", "expected_date")

ADMIN_SESSION = {
    "username": "admin",
    "company_name": "Skantha Industrial Solutions",
    "assigned_warehouse_code": "WH-MAIN",
    "role": "Admin",
}


# --------------------------------------------------------------------------- DB helpers
def copy_db(src: str, dst: str) -> None:
    """Consistent copy using the SQLite backup API; the source is opened read-only."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def _tables(conn: sqlite3.Connection) -> List[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def table_fingerprints(db_path: str, columns_by_table: Optional[Dict[str, List[str]]] = None,
                       ignore_columns: Optional[Dict[str, Iterable[str]]] = None) -> Dict[str, Any]:
    """Row count + checksum per table. With `columns_by_table`, only those columns are hashed,
    so columns added later (e.g. is_demo) never count as a change to existing data."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out: Dict[str, Any] = {}
    try:
        for t in _tables(conn):
            cols_now = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
            cols = [c for c in (columns_by_table or {}).get(t, cols_now) if c in cols_now]
            skip = set((ignore_columns or {}).get(t, ()))
            cols = [c for c in cols if c not in skip]
            h = hashlib.sha256()
            n = 0
            col_sql = ", ".join(f'"{c}"' for c in cols) or "1"
            for row in conn.execute(f'SELECT {col_sql} FROM "{t}" ORDER BY rowid'):
                h.update(repr(tuple(row)).encode("utf-8"))
                n += 1
            out[t] = {"count": n, "columns": cols, "sha256": h.hexdigest()}
    finally:
        conn.close()
    return out


def file_hashes(dirs: Iterable[str] = FILE_DIRS) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for base in dirs:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, WEBAPP_DIR).replace("\\", "/")
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                out[rel] = h.hexdigest()
    return out


# --------------------------------------------------------------------------- API helpers
def normalize(value: Any, shape_only: bool = False) -> Any:
    """Drop clock-driven values; in shape-only mode keep just the structure."""
    if isinstance(value, dict):
        res = {}
        for k, v in sorted(value.items()):
            lk = str(k).lower()
            if any(hint in lk for hint in VOLATILE_KEY_HINTS):
                res[k] = "<volatile>"
            else:
                res[k] = normalize(v, shape_only)
        return res
    if isinstance(value, list):
        if shape_only:
            return [normalize(value[0], True)] if value else []
        return [normalize(v, shape_only) for v in value]
    if shape_only:
        return type(value).__name__
    return value


def is_shape_only(path: str) -> bool:
    return path in SHAPE_ONLY_ENDPOINTS or path.endswith(SHAPE_ONLY_SUFFIXES)


def run_api_snapshot_inprocess(db_path: str) -> Dict[str, Any]:
    """Imports the app against `db_path` (never the live DB) and calls every endpoint as admin."""
    os.environ["WARLOG_DB_PATH"] = db_path
    os.environ.setdefault("FLASK_SECRET_KEY", "rbac-snapshot-only")
    os.environ.setdefault("WARLOG_SKIP_DOTENV", "1")
    os.environ.setdefault("WARLOG_SKIP_MIGRATION_BACKUP", "1")  # private copy; no backup needed
    sys.path.insert(0, WEBAPP_DIR)
    os.chdir(WEBAPP_DIR)
    import db  # noqa: E402  (older code has no env support: pin the path explicitly)
    db.DB_PATH = db_path
    scope_headers = {}
    try:  # RBAC Phase 3A+: apply the approved ownership on this private copy
        import rbac_migration  # noqa: E402
        import rbac_ownership  # noqa: E402
        import sqlite3 as _sq
        rbac_migration.migrate(db_path)
        _c = _sq.connect(db_path)
        with _c:
            if rbac_ownership.approved_proposal(_c) is None:
                rbac_ownership.approve(_c, approved_by="parity snapshot")
        _c.close()
        rbac_migration.migrate(db_path)
        # admin sees everything through the Platform Admin's read-only all-companies view
        scope_headers = {"X-Warehouse-Id": "*"}
    except ImportError:
        pass
    import app as app_module  # noqa: E402
    client = app_module.app.test_client()
    session_user = dict(ADMIN_SESSION)
    conn = db.get_db()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
        if "session_version" in cols:
            # RBAC Phase 1+: sessions need uid/sv. On this private copy only, admin is
            # treated as having already replaced its default password, so the snapshot
            # compares the data admin sees rather than the one-time reset screen.
            with conn:
                conn.execute("UPDATE users SET must_reset_password = 0 WHERE LOWER(username) = 'admin'")
            uid, sv = conn.execute("SELECT id, session_version FROM users WHERE LOWER(username) = 'admin'").fetchone()
            session_user.update({"uid": uid, "sv": sv, "must_reset_password": False})
    finally:
        conn.close()
    with client.session_transaction() as s:
        s["user"] = session_user
    result: Dict[str, Any] = {}
    for path in API_ENDPOINTS:
        try:
            r = client.get(path, headers=scope_headers)
            body: Any
            try:
                body = r.get_json(silent=True)
            except Exception:
                body = None
            if body is None:
                body = {"_non_json_bytes": len(r.data)}
            result[path] = {"status": r.status_code, "body": body}
        except Exception as e:  # recorded, never fatal
            result[path] = {"status": "EXC", "body": repr(e)}
    return result


def api_snapshot(db_path: str, out_file: str) -> Dict[str, Any]:
    """Runs the API snapshot in a fresh interpreter so module state never leaks between runs."""
    cmd = [sys.executable, os.path.abspath(__file__), "api", "--db", db_path, "--out", out_file]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(cmd, cwd=ROOT_DIR, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    if proc.returncode != 0 or not os.path.exists(out_file):
        raise RuntimeError(f"API snapshot failed (exit {proc.returncode}):\n{proc.stderr[-4000:]}")
    with open(out_file, "r", encoding="utf-8") as fh:
        return json.load(fh)


# Fields added by RBAC migrations. Extra keys in a response are invisible to the existing
# UI, so they are not treated as a change to what admin sees.
RBAC_ADDED_KEYS = frozenset({
    "is_demo", "company_id", "state",      # columns added by RBAC migrations
    "warehouse_id", "legacy_test",         # ownership columns (Phase 3A)
    "otp", "otp_generated",                # deliberately removed from responses in Phase 2 (H17)
    "otp_failed_attempts",                 # hardening: wrong gate-OTP tries per pass
})

# Deliberate Phase 1 data changes, excluded from the "existing rows unchanged" check:
#   users.password  plain-text passwords are moved to users.password_hash, then blanked (H3)
#   email_otps      old plain-text OTP codes are purged; new ones are stored hashed (H19)
PARITY_EXCLUDED_COLUMNS = {"users": ("password",)}
PARITY_EXCLUDED_TABLES = frozenset({"email_otps"})


def _strip_keys(value: Any, keys: frozenset) -> Any:
    if isinstance(value, dict):
        return {k: _strip_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_strip_keys(v, keys) for v in value]
    return value


# Phase 3A: the active warehouse is per session (and per tab) instead of one global flag,
# so these two endpoints legitimately report a different "active" warehouse.
SESSION_STATE_KEYS = {"/api/warehouses": frozenset({"is_active", "active_warehouse"}),
                      "/api/warehouses/active": frozenset({"is_active", "active_warehouse"}),
                      # Phase 7 (H7): the camera push address now carries the secret stream key
                      "/api/system/rtmp_status": frozenset({"rtmp_url", "key_required"})}


SUPERSET_LIST_ENDPOINTS = {"/api/warehouses": ("code", "warehouses")}


def compare_api(baseline: Dict[str, Any], current: Dict[str, Any],
                allowed_new_keys: frozenset = RBAC_ADDED_KEYS) -> List[str]:
    """Returns human-readable differences (empty list = parity)."""
    def keys_for(p):
        return allowed_new_keys | SESSION_STATE_KEYS.get(p, frozenset())
    baseline = {p: {**v, "body": _strip_keys(v["body"], keys_for(p))} for p, v in baseline.items()}
    current = {p: {**v, "body": _strip_keys(v["body"], keys_for(p))} for p, v in current.items()}
    diffs: List[str] = []
    for path, base in baseline.items():
        cur = current.get(path)
        if cur is None:
            diffs.append(f"{path}: missing from current snapshot")
            continue
        if base["status"] != cur["status"]:
            diffs.append(f"{path}: status {base['status']} -> {cur['status']}")
            continue
        so = is_shape_only(path)
        if path in SUPERSET_LIST_ENDPOINTS:
            # Platform Admin may now pick any company's warehouse: every warehouse listed
            # before must still be listed, unchanged; extra ones are expected.
            key, field = SUPERSET_LIST_ENDPOINTS[path]
            now = {w[key]: normalize(w, so) for w in (cur["body"] or {}).get(field, [])}
            for w in (base["body"] or {}).get(field, []):
                if now.get(w[key]) != normalize(w, so):
                    diffs.append(f"{path}: {w[key]} missing or changed")
            rest_b = {k: v for k, v in (base["body"] or {}).items() if k != field}
            rest_c = {k: v for k, v in (cur["body"] or {}).items() if k != field}
            if normalize(rest_b, so) != normalize(rest_c, so):
                diffs.append(f"{path}: response body differs")
            continue
        if normalize(base["body"], so) != normalize(cur["body"], so):
            diffs.append(f"{path}: response body differs")
    return diffs


# --------------------------------------------------------------------------- commands
def cmd_baseline(args: argparse.Namespace) -> int:
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(BACKUP_ROOT, f"baseline_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Full backup: DB (consistent copy) + uploads/invoices/manifests
    snap_db = os.path.join(out_dir, "skandha_wms.snapshot.db")
    copy_db(LIVE_DB, snap_db)
    files_dir = os.path.join(out_dir, "files")
    for d in FILE_DIRS:
        if os.path.isdir(d):
            shutil.copytree(d, os.path.join(files_dir, os.path.relpath(d, WEBAPP_DIR)), dirs_exist_ok=True)

    # 2. Fingerprints of the snapshot (identical content to live at this moment)
    tables = table_fingerprints(snap_db)
    files = file_hashes()

    # 3. API responses as admin, from a throw-away copy of the snapshot
    work_db = os.path.join(out_dir, "work_api.db")
    copy_db(snap_db, work_db)
    api = api_snapshot(work_db, os.path.join(out_dir, "api_raw.json"))
    os.remove(work_db)

    meta = {
        "created": stamp,
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR,
                                   capture_output=True, text=True).stdout.strip(),
        "live_db_sha256": hashlib.sha256(open(LIVE_DB, "rb").read()).hexdigest(),
        "tables": len(tables), "rows": sum(t["count"] for t in tables.values()),
        "files": len(files), "endpoints": len(api),
    }
    for name, data in (("tables.json", tables), ("files.json", files), ("api.json", api), ("meta.json", meta)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True, default=str)
    with open(os.path.join(BACKUP_ROOT, "LATEST_BASELINE"), "w", encoding="utf-8") as fh:
        fh.write(out_dir)
    print(json.dumps({"baseline_dir": out_dir, **meta}, indent=1))
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    result = run_api_snapshot_inprocess(os.path.abspath(args.db))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, default=str)
    os._exit(0)  # skip camera/runtime thread teardown


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline")
    p_api = sub.add_parser("api")
    p_api.add_argument("--db", required=True)
    p_api.add_argument("--out", required=True)
    args = ap.parse_args()
    return {"baseline": cmd_baseline, "api": cmd_api}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
