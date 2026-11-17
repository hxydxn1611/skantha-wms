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
for _var in ("SMTP_USER", "SMTP_PASSWORD"):
    os.environ.pop(_var, None)
