"""
RBAC Phase 6 acceptance: a scripted pass over every screen, per role, in a real browser.

  py -3.14 scripts/rbac_ui_pass.py

Runs the app on a PRIVATE COPY of the live database (never the live file) with
RBAC_MODE=enforce, creates one person per test role, signs in as each in headless
Chrome, opens every screen their menu shows and records every request the page makes
that the server refuses with 'permission_denied'. Plan acceptance: for each role, no
visible screen runs into a refusal; admin sees every control (nothing hidden).
Exit code 0 = pass. A JSON report is written next to this script's temp folder.
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "webapp"))
os.environ["WARLOG_SKIP_DOTENV"] = "1"
os.environ.setdefault("FLASK_SECRET_KEY", "ui-pass-only-" + os.urandom(8).hex())

TMP = tempfile.mkdtemp(prefix="warlog_ui_pass_")
DB = os.path.join(TMP, "ui.db")
os.environ["WARLOG_DB_PATH"] = DB
os.environ["WARLOG_SKIP_MIGRATION_BACKUP"] = "1"

from tests import copy_live_db, prepare_test_db, session_for  # noqa: E402

copy_live_db(DB)
prepare_test_db(DB)

from werkzeug.security import generate_password_hash  # noqa: E402

PW = "Ui-Pass-Strong-2026"
ROLES = [  # (username, starter template)
    ("ui_gate", "gate_security"),
    ("ui_dock", "dock_supervisor"),
    ("ui_stock", "inventory_controller"),
    ("ui_exec", "executive"),
    ("ui_mgr", "warehouse_manager"),
]

import app as app_module  # noqa: E402
import db  # noqa: E402
import rbac_config  # noqa: E402
import rbac_scope  # noqa: E402

db.DB_PATH = DB
rbac_config.RBAC_MODE = "enforce"
rbac_scope.reset_isolation_cache()
flask_app = app_module.app

conn = sqlite3.connect(DB)
with conn:
    conn.execute("UPDATE users SET password_hash = ?, must_reset_password = 0 WHERE username IN ('admin', 'david')",
                 (generate_password_hash(PW),))
    conn.execute("DELETE FROM login_attempts")
glass_wh, glass_co = conn.execute("SELECT id, company_id FROM warehouses WHERE code = 'WH-GLASS-COI'").fetchone()
conn.close()

# create the role users through the real invitation flow
c = flask_app.test_client()
with c.session_transaction() as s:
    s["user"] = session_for("david", DB)
    s["csrf"] = "t"
for username, tkey in ROLES:
    rid = sqlite3.connect(DB).execute("SELECT id FROM roles WHERE company_id = ? AND template_key = ?",
                                      (glass_co, tkey)).fetchone()[0]
    r = c.post("/api/iam/invitations", json={"email": f"{username}@example.com", "role_id": rid,
                                              "warehouse_id": glass_wh},
               headers={"X-CSRF-Token": "t", "X-Warehouse-Id": str(glass_wh)})
    link = r.get_json()["invite_link"]
    token = re.search(r"token=([^&]+)", link).group(1)
    a = flask_app.test_client().post("/api/auth/accept_invite",
                                     json={"token": token, "username": username, "password": PW})
    assert a.get_json()["success"], a.get_json()

from werkzeug.serving import make_server  # noqa: E402

PORT = 5077
server = make_server("127.0.0.1", PORT, flask_app, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"

from playwright.sync_api import sync_playwright  # noqa: E402

report = {}
failed = False
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    for username in ["admin", "david"] + [u for u, _ in ROLES]:
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        refusals = []

        def on_response(resp, refusals=refusals):
            if resp.status == 403 and "/api/" in resp.url:
                try:
                    body = resp.json()
                except Exception:
                    body = {}
                if body.get("error_code") == "permission_denied":
                    refusals.append({"url": resp.url.replace(BASE, ""), "method": resp.request.method,
                                     "permission": body.get("permission")})

        page.on("response", on_response)
        r = ctx.request.post(BASE + "/api/login", data=json.dumps({"username": username, "password": PW}),
                             headers={"Content-Type": "application/json"})
        assert r.ok, (username, r.status, r.text())
        page.goto(BASE + "/")
        page.wait_for_timeout(2500)
        if os.environ.get("UI_PASS_SHOTS"):
            page.screenshot(path=os.path.join(os.environ["UI_PASS_SHOTS"], f"{username}.png"))
        visible = page.eval_on_selector_all(
            ".macos-dock-item[data-module]",
            "els => els.filter(e => !e.classList.contains('perm-hidden')).map(e => e.dataset.module)")
        hidden_count = page.eval_on_selector_all(".perm-hidden", "els => els.length")
        screens = {}
        for module in visible:
            if module == "copilot":
                continue
            before = len(refusals)
            page.evaluate(f"window.switchTab && window.switchTab({json.dumps(module)})")
            page.wait_for_timeout(1800)
            screens[module] = refusals[before:]
        if os.environ.get("UI_PASS_SHOTS") and username == "david":
            page.evaluate("window.switchTab('users-access')")
            page.wait_for_timeout(2500)
            page.evaluate("document.getElementById('uacSettingsPanel').scrollIntoView()")
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(os.environ["UI_PASS_SHOTS"], "david_audit.png"))
        entry = {"visible_modules": visible, "hidden_controls": hidden_count,
                 "refusals_on_load": [x for x in refusals if not any(x in v for v in screens.values())],
                 "refusals_by_screen": {k: v for k, v in screens.items() if v}}
        if username == "admin" and hidden_count:
            entry["problem"] = "admin has hidden controls"
            failed = True
        if refusals:
            failed = True
        report[username] = entry
        ctx.close()
    browser.close()
server.shutdown()

out = os.path.join(TMP, "ui_pass_report.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=1)
for u, e in report.items():
    n = len(e["refusals_on_load"]) + sum(len(v) for v in e["refusals_by_screen"].values())
    print(f"{u:10s} screens={len(e['visible_modules']):2d} hidden_controls={e['hidden_controls']:4d} refusals={n}"
          + (f"  <-- {e.get('problem')}" if e.get("problem") else ""))
    for where, items in [("on load", e["refusals_on_load"])] + list(e["refusals_by_screen"].items()):
        for x in {(i["method"], re.sub(r"\?.*", "", i["url"]), i["permission"]) for i in items}:
            print(f"      [{where}] {x[0]} {x[1]} needs {x[2]}")
print("report:", out)
print("RESULT:", "FAIL" if failed else "PASS")
shutil.rmtree(TMP, ignore_errors=True) if not failed else None
sys.exit(1 if failed else 0)
