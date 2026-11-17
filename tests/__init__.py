# tests package
#
# RBAC Phase 0: the suite never touches the live database. Before any test module
# imports the app, the live DB is copied (read-only, SQLite backup API) to a private
# temp file and WARLOG_DB_PATH points the app at that copy. Secrets come from fixed
# test values, and .env is not loaded, so tests can never send real email.
import atexit
import os
import shutil
import sqlite3
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DB_PATH = os.path.join(_ROOT, "webapp", "skandha_wms.db")


def copy_live_db(dst: str) -> str:
    src = sqlite3.connect(f"file:{LIVE_DB_PATH}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


if not os.environ.get("WARLOG_TEST_DB_READY"):
    _TMP_DIR = tempfile.mkdtemp(prefix="warlog_tests_")
    TEST_DB_PATH = copy_live_db(os.path.join(_TMP_DIR, "skandha_wms_test.db"))
    os.environ["WARLOG_DB_PATH"] = TEST_DB_PATH
    os.environ["WARLOG_TEST_DB_READY"] = "1"
    atexit.register(shutil.rmtree, _TMP_DIR, ignore_errors=True)
else:
    TEST_DB_PATH = os.environ["WARLOG_DB_PATH"]

os.environ.setdefault("FLASK_SECRET_KEY", "warlog-test-secret-key-not-for-production")
os.environ["WARLOG_SKIP_DOTENV"] = "1"
os.environ["WARLOG_SKIP_MIGRATION_BACKUP"] = "1"  # test copies need no pre-migration backup
for _var in ("SMTP_USER", "SMTP_PASSWORD"):
    os.environ.pop(_var, None)

_WEBAPP = os.path.join(_ROOT, "webapp")
if _WEBAPP not in __import__("sys").path:
    __import__("sys").path.insert(0, _WEBAPP)


def prepare_test_db(db_path: str) -> str:
    """Applies the RBAC migration to a test copy and marks `admin` as having already
    replaced its default password, so the existing suite can keep signing in as
    admin/admin. Phase 1 tests that check the forced reset use their own fresh copy."""
    import rbac_migration
    import rbac_ownership
    rbac_migration.migrate(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with conn:  # RBAC Phase 3A: test copies approve the evidence-based ownership proposal
            if rbac_ownership.approved_proposal(conn) is None:
                rbac_ownership.approve(conn, approved_by="test fixture")
    finally:
        conn.close()
    rbac_migration.migrate(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("UPDATE users SET must_reset_password = 0 WHERE LOWER(username) = 'admin'")
            conn.execute("DELETE FROM login_attempts")
    finally:
        conn.close()
    return db_path


def session_for(username: str, db_path: str = None) -> dict:
    """A valid session['user'] (uid + session_version) for any user in a test database."""
    conn = sqlite3.connect(db_path or os.environ["WARLOG_DB_PATH"])
    try:
        uid, sv, company, wh = conn.execute(
            "SELECT id, session_version, company_name, assigned_warehouse_code FROM users WHERE LOWER(username) = LOWER(?)",
            (username,)).fetchone()
    finally:
        conn.close()
    return {"username": username, "company_name": company, "assigned_warehouse_code": wh or "WH-MAIN",
            "role": "Admin", "uid": uid, "sv": sv, "must_reset_password": False}


def scope_for(username: str, db_path: str = None):
    """The warehouse scope a request by `username` works in by default (its assigned warehouse)."""
    import rbac_scope
    conn = sqlite3.connect(db_path or os.environ["WARLOG_DB_PATH"])
    try:
        row = conn.execute("""SELECT w.company_id, w.id FROM users u
                              JOIN warehouses w ON UPPER(w.code) = UPPER(u.assigned_warehouse_code)
                              WHERE LOWER(u.username) = LOWER(?)""", (username,)).fetchone()
    finally:
        conn.close()
    return rbac_scope.Scope.warehouse(row[0], row[1])


def admin_session(db_path: str = None) -> dict:
    """A valid session['user'] for `admin` in the given test database (uid + session_version)."""
    conn = sqlite3.connect(db_path or os.environ["WARLOG_DB_PATH"])
    try:
        uid, sv, company, wh = conn.execute(
            "SELECT id, session_version, company_name, assigned_warehouse_code FROM users WHERE LOWER(username) = 'admin'"
        ).fetchone()
    finally:
        conn.close()
    return {"username": "admin", "company_name": company, "assigned_warehouse_code": wh or "WH-MAIN",
            "role": "Admin", "uid": uid, "sv": sv, "must_reset_password": False}


if not os.environ.get("WARLOG_TEST_DB_PREPARED"):
    prepare_test_db(TEST_DB_PATH)
    os.environ["WARLOG_TEST_DB_PREPARED"] = "1"
