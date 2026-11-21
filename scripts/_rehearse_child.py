"""Helper for rbac_rehearsal.py: boots ONE checkout of the app on a database copy and reads a
few screens as admin (and david). Prints one JSON line. Never touches the live database."""
import json
import os
import sys

repo, db_path, mode = sys.argv[1], sys.argv[2], sys.argv[3]
os.environ.update({"WARLOG_DB_PATH": db_path, "WARLOG_SKIP_DOTENV": "1", "WARLOG_SKIP_MIGRATION_BACKUP": "1",
                   "WARLOG_DISABLE_BACKGROUND_JOBS": "1", "RTMP_REQUIRE_KEY": "0", "RBAC_MODE": "audit",
                   "WARLOG_TEST_DB_PREPARED": "1",   # don't let the checkout's tests/ prepare its own copy
                   "FLASK_SECRET_KEY": "rehearsal-" + os.urandom(6).hex()})
sys.path.insert(0, os.path.join(repo, "webapp"))
sys.path.insert(0, repo)
os.chdir(repo)
out = {"repo": repo, "mode": mode, "ok": False, "screens": {}}
try:
    import app as app_module  # noqa: E402
    client = app_module.app.test_client()
    if mode == "rbac":
        import sqlite3

        def session_for(username, path):
            c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                uid, sv, comp, wh = c.execute("SELECT id, session_version, company_name, assigned_warehouse_code "
                                              "FROM users WHERE LOWER(username) = ?", (username.lower(),)).fetchone()
            finally:
                c.close()
            return {"username": username, "uid": uid, "sv": sv, "company_name": comp,
                    "assigned_warehouse_code": wh, "role": "Admin", "must_reset_password": False}
        users = ["admin", "david"]
    else:
        users = ["admin"]
    paths = ["/api/stats", "/api/skus", "/api/bins", "/api/deliveries", "/api/gate_passes", "/api/cameras",
             "/api/warehouses", "/api/inventory", "/api/vision/zones", "/api/object_classes"]
    for u in users:
        with client.session_transaction() as s:
            s["user"] = session_for(u, db_path) if mode == "rbac" else {"username": u, "company_name": "", "role": "Admin"}
            s["csrf"] = "t"
        for p in paths:
            out["screens"][f"{u} {p}"] = client.get(p).status_code
    out["login_page"] = app_module.app.test_client().get("/login").status_code   # a visitor, not signed in
    out["ok"] = all(v == 200 for v in out["screens"].values()) and out["login_page"] == 200
except Exception as e:  # report, don't hide
    out["error"] = f"{type(e).__name__}: {e}"
print("REHEARSAL_RESULT " + json.dumps(out), flush=True)
os._exit(0)
