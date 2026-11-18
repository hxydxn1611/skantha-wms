"""
RBAC Phase 8 (release): the remaining security tests from the plan's Testing list.

  * gate state machine: each step needs its permission; illegal jumps need the override
    permission and a reason; every change leaves a gate_pass_events row
  * concurrent sessions in two companies never cross over
  * growth: companies and warehouses added at runtime are isolated; nothing assumes a fixed list
  * templates: all 11 apply cleanly to two companies on the same template; re-apply is a no-op;
    an edited SKU survives a re-apply; nothing of the other company changes
  * camera frame loops make no RBAC / audit calls (static check of the loop bodies)
  * security headers on every response
Runs on a private copy of the live database; template images go to a temp folder.
"""
import ast
import json
import os
import shutil
import tempfile
import threading
import unittest

from tests.test_rbac_phase3a import GLASS_SKU, MARK
from tests.test_rbac_phase7 import Phase7Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestGateStateMachine(Phase7Base):
    def new_pass(self, client):
        r = self.send(client, "POST", "/api/gate_passes", {"plate": f"TN38P8{os.urandom(2).hex()}", "driver_name": "Flow"})
        body = r.get_json()
        return body.get("gate_pass", body).get("id") or body.get("id")

    def put(self, client, gp, status, reason=None):
        headers = {"X-CSRF-Token": "t", "X-Warehouse-Id": str(self.glass_wh[0])}
        if reason:
            headers["X-Action-Reason"] = reason
        return client.open(f"/api/gate_passes/{gp}", method="PUT", json={"status": status}, headers=headers)

    def test_normal_flow_and_history(self):
        d = self.client("david", self.glass_wh[0])
        gp = self.new_pass(d)
        for status in ("Sent to Dock", "Unloading", "Completed", "Exited"):
            r = self.put(d, gp, status)
            self.assertLess(r.status_code, 400, (status, r.get_data(as_text=True)))
        events = self.sql("SELECT from_status, to_status, actor_user_id FROM gate_pass_events WHERE gp_id = ? ORDER BY id", (gp,))
        self.assertEqual([e[1] for e in events], ["Sent to Dock", "Unloading", "Completed", "Exited"])
        david_id = self.sql("SELECT id FROM users WHERE username = 'david'")[0][0]
        self.assertTrue(all(e[2] == david_id for e in events))

    def test_illegal_jumps_need_override_and_reason(self):
        d = self.client("david", self.glass_wh[0])
        gp = self.new_pass(d)
        r = self.put(d, gp, "Departed")                       # Pending -> Departed skips everything
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (400, "reason_required"))
        self.assertEqual(self.sql("SELECT status FROM gate_passes WHERE id = ?", (gp,))[0][0], "Pending")
        r = self.put(d, gp, "Departed", reason="truck left without unloading")
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))
        ev = self.sql("SELECT from_status, to_status, reason FROM gate_pass_events WHERE gp_id = ?", (gp,))
        self.assertEqual(ev[-1], ("Pending", "Departed", "truck left without unloading"))
        # someone without the override permission can't jump at all
        g = self.role_user("gate_incharge", "p8gate")
        gp2 = self.new_pass(d)
        r = self.put(g, gp2, "Departed", reason="please")
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (409, "illegal_transition"))

    def test_each_step_needs_its_permission_in_enforce_mode(self):
        d = self.client("david", self.glass_wh[0])
        gp = self.new_pass(d)
        sec = self.role_user("gate_security", "p8sec")         # no gate.dock.admit
        self.cfg.RBAC_MODE = "enforce"
        try:
            r = self.put(sec, gp, "Sent to Dock")
            self.assertEqual(r.status_code, 403)
            self.assertEqual(self.sql("SELECT status FROM gate_passes WHERE id = ?", (gp,))[0][0], "Pending")
            self.assertLess(self.put(sec, gp, "Rejected").status_code, 400)   # gate.entry.reject is allowed
        finally:
            self.cfg.RBAC_MODE = "audit"


class TestConcurrentSessions(Phase7Base):
    def test_two_companies_interleaved_never_cross(self):
        glass = self.client("david", self.glass_wh[0])
        leak = self.client("leakadmin", self.leak_wh)
        problems = []

        def run(client, must_have, must_not, n=15):
            for _ in range(n):
                body = self.get(client, "/api/skus").get_data(as_text=True)
                if must_have not in body or must_not in body:
                    problems.append((must_have, must_not))

        t1 = threading.Thread(target=run, args=(glass, GLASS_SKU, MARK))
        t2 = threading.Thread(target=run, args=(leak, MARK, GLASS_SKU))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(problems, [])


class TestGrowth(Phase7Base):
    def test_new_companies_and_locations_at_runtime_are_isolated(self):
        a = self.client("admin")
        made = []
        for name in ("Growth Alpha Ltd", "Growth Beta Ltd"):
            out = self.send(a, "POST", "/api/platform/companies", {"name": name, "owner_email": f"{name[:12].replace(' ', '').lower()}@ex.com"}).get_json()
            self.assertTrue(out["success"], out)
            made.append(out)
        # a third location for an existing company, at any time
        r = self.send(self.client("david"), "POST", "/api/warehouses/create", {"name": "Growth Hub", "city": "Erode", "set_active": False})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertGreaterEqual(self.sql("SELECT COUNT(*) FROM warehouses WHERE company_id = ?", (self.glass_wh[1],))[0][0], 3)
        for out in made:
            cid = out["company_id"]
            wid = self.sql("SELECT id FROM warehouses WHERE company_id = ?", (cid,))[0][0]
            import rbac_scope
            with rbac_scope.using(rbac_scope.Scope.warehouse(cid, wid)):
                import db
                self.assertEqual(db.get_all_skus(), [])
                self.assertEqual(db.get_all_cameras(), [])
            self.assertEqual(self.sql("SELECT COUNT(*) FROM roles WHERE company_id = ? AND template_key IS NOT NULL", (cid,))[0][0], 8)
        # david still sees only his company
        names = {w["company_name"] for w in self.get(self.client("david"), "/api/warehouses").get_json()["warehouses"]}
        self.assertEqual(names, {"glass and brass"})


class TestAllTemplates(Phase7Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import industry_blueprint_service as bps
        cls.bps = bps
        cls._img = tempfile.mkdtemp(prefix="warlog_p8_img_")
        cls._saved_upload = bps.UPLOAD_DIR
        bps.UPLOAD_DIR = cls._img

    @classmethod
    def tearDownClass(cls):
        cls.bps.UPLOAD_DIR = cls._saved_upload
        shutil.rmtree(cls._img, ignore_errors=True)
        super().tearDownClass()

    def test_every_template_on_two_companies(self):
        import db
        a = self.client("admin")
        out = self.send(a, "POST", "/api/platform/companies", {"name": "Template Twin Co", "owner_email": "twin@ex.com"}).get_json()
        twin_cid = out["company_id"]
        twin_wid = self.sql("SELECT id FROM warehouses WHERE company_id = ?", (twin_cid,))[0][0]
        glass_before = self.sql("SELECT sku_id, name FROM skus WHERE company_id = ? ORDER BY sku_id", (self.glass_wh[1],))
        for key in self.bps.INDUSTRY_BLUEPRINTS:
            for wid in (self.leak_wh, twin_wid):
                res = self.bps.apply_industry_blueprint(key, warehouse_id=wid, db_path=db.DB_PATH)
                self.assertTrue(res["success"], (key, res))
                again = self.bps.apply_industry_blueprint(key, warehouse_id=wid, db_path=db.DB_PATH)
                self.assertEqual((again["skus_created"], again["classes_created"], again["zones_created"]), (0, 0, 0), key)
                self.assertEqual(again["deliveries_created"], 0)
        # each company has its own copy of every template SKU; codes never shared
        dup = self.sql("SELECT sku_id, COUNT(*) FROM skus GROUP BY sku_id HAVING COUNT(*) > 1")
        self.assertEqual(dup, [])
        # an edited SKU survives a re-apply
        sku = self.sql("SELECT sku_id FROM skus WHERE company_id = ? LIMIT 1", (self.leak_company,))[0][0]
        conn = __import__("sqlite3").connect(self.db_path)
        with conn:
            conn.execute("UPDATE skus SET name = 'EDITED BY USER' WHERE sku_id = ?", (sku,))
        conn.close()
        for key in self.bps.INDUSTRY_BLUEPRINTS:
            self.bps.apply_industry_blueprint(key, warehouse_id=self.leak_wh, db_path=db.DB_PATH)
        self.assertEqual(self.sql("SELECT name FROM skus WHERE sku_id = ?", (sku,))[0][0], "EDITED BY USER")
        # glass and brass untouched; no sample data without asking
        self.assertEqual(self.sql("SELECT sku_id, name FROM skus WHERE company_id = ? ORDER BY sku_id", (self.glass_wh[1],)), glass_before)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM expected_deliveries WHERE company_id IN (?, ?)", (self.leak_company, twin_cid))[0][0],
                         self.sql("SELECT COUNT(*) FROM expected_deliveries WHERE company_id IN (?, ?) AND po_number LIKE ?",
                                  (self.leak_company, twin_cid, f"PO-{MARK}%"))[0][0])


class TestFrameLoops(unittest.TestCase):
    LOOPS = {"webapp/app.py": ["generate_frames"], "webapp/ai_engine.py": ["_capture_loop"],
             "webapp/vision_runtime_service.py": ["_capture_loop", "_worker_loop"]}
    # generate_frames already looked a camera up in its fallback branch before RBAC (main)
    PRE_RBAC = {"generate_frames": {"db", "db.get_camera"}}

    def test_no_rbac_or_audit_calls_in_frame_loops(self):
        for rel, names in self.LOOPS.items():
            tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in names:
                    refs = set()
                    for n in ast.walk(node):
                        if isinstance(n, ast.Name):
                            refs.add(n.id)
                        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                            refs.add(f"{n.value.id}.{n.attr}")
                    rbac = {r for r in refs if r.split(".")[0] in ("rbac_service", "rbac_scope", "auth_service",
                                                                   "audit_events", "settings_service", "iam_service")}
                    self.assertEqual(rbac, set(), f"{rel}:{node.name}")
                    dbrefs = {r for r in refs if r.split(".")[0] in ("db", "sqlite3", "get_db")}
                    self.assertTrue(dbrefs <= self.PRE_RBAC.get(node.name, set()), f"{rel}:{node.name} {dbrefs}")


class TestSecurityHeaders(Phase7Base):
    def test_headers(self):
        r = self.get(self.client("david"), "/api/skus")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(r.headers.get("Referrer-Policy"), "same-origin")
        login = self.app_module.app.test_client().get("/login")
        self.assertEqual(login.headers.get("X-Frame-Options"), "SAMEORIGIN")


if __name__ == "__main__":
    unittest.main()
