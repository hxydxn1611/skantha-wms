"""
RBAC Phase 7: audit trail, reasons, Copilot limits, RTMP stream key, background actors.

Plan acceptance covered here:
  * every sensitive action leaves an audit row (exceptional ones with a reason)
  * Copilot can't run an action the user lacks (in every RBAC mode)
  * a push without the stream key is refused
  (live-feed FPS is measured on the running server: scripts/measure_live_fps.py)
Runs on a private copy of the live database.
"""
import json
import time
import unittest

from tests.rtmp_fakes import FakeUpstream, connect_message, publish_message, push, video_message
from tests.test_rbac_phase5 import Phase5Base


class Phase7Base(Phase5Base):
    def audit_rows(self, action, **where):
        sql = "SELECT actor_username, company_id, warehouse_id, resource_id, reason, before_json, after_json FROM audit_logs WHERE action = ?"
        params = [action]
        for k, v in where.items():
            sql += f" AND {k} = ?"
            params.append(v)
        return self.sql(sql + " ORDER BY id DESC", tuple(params))

    def role_user(self, template, username):
        rid = self.sql("SELECT id FROM roles WHERE company_id = ? AND template_key = ?", (self.glass_wh[1], template))[0][0]
        self.invite_with_role("david", f"{username}@example.com", username, rid, self.glass_wh[0])
        return self.user_client(username)


class TestRtmpKeyGate(unittest.TestCase):
    def test_push_without_the_key_is_refused_and_no_frame_passes(self):
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp"))
        from rtmp_gate import RTMPKeyGate
        key = "Gate7TestKeyABCDEF123"
        up = FakeUpstream()
        gate = RTMPKeyGate(lambda: key, "127.0.0.1", 0, "127.0.0.1", up.port).start()
        try:
            self.assertFalse(push(gate.listen_port, [connect_message("live", "rtmp://h/live"), publish_message("cam"),
                                                     video_message()]))
            time.sleep(0.3)
            self.assertEqual(gate.refused, 1)
            self.assertTrue(all(b"\x17" not in bytes(d)[-300:] or len(d) < 250 for d in up.received))
            n = len(up.received)
            self.assertTrue(push(gate.listen_port, [connect_message(key, "rtmp://h/" + key), publish_message("cam"),
                                                    video_message()]))
            self.assertTrue(push(gate.listen_port, [connect_message("live", "rtmp://h/live"), publish_message(key),
                                                    video_message()]))
            time.sleep(0.3)
            self.assertEqual(gate.accepted, 2)
            self.assertTrue(all(len(d) > 400 for d in up.received[n:]))
            self.assertFalse(push(gate.listen_port, [video_message()]))
        finally:
            gate.stop()


class TestRtmpKeyVisibility(Phase7Base):
    def test_only_camera_configurers_see_the_key(self):
        import settings_service
        key = settings_service.rtmp_stream_key()
        self.assertEqual(key, settings_service.rtmp_stream_key())
        self.assertGreaterEqual(len(key), 16)
        full = self.get(self.client("david"), "/api/system/rtmp_status").get_json()["rtmp_url"]
        self.assertIn(key, full)
        masked = self.get(self.role_user("executive", "p7exec"), "/api/system/rtmp_status").get_json()["rtmp_url"]
        self.assertNotIn(key, masked)


class TestAuditTrail(Phase7Base):
    def test_gate_and_delivery_changes_are_audited_with_before_and_after(self):
        d = self.client("david", self.glass_wh[0])
        r = self.send(d, "POST", "/api/gate_passes", {"plate": "TN38P7AUD", "driver_name": "Audit Driver"})
        gp = r.get_json().get("gate_pass", r.get_json()).get("id") or r.get_json().get("id")
        self.assertTrue(gp, r.get_json())
        self.assertTrue(self.audit_rows("gate.pass_created", resource_id=str(gp)))
        r = self.send(d, "PUT", f"/api/gate_passes/{gp}", {"status": "Approved"})
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))
        rows = self.audit_rows("gate.entry_approved", resource_id=str(gp))
        self.assertTrue(rows, "status change to Approved must be audited as gate.entry_approved")
        actor, cid, wid, _, _, before, after = rows[0]
        self.assertEqual((actor, cid, wid), ("david", self.glass_wh[1], self.glass_wh[0]))
        self.assertNotEqual(json.loads(before)["status"], "Approved")
        self.assertEqual(json.loads(after)["status"], "Approved")
        for b, a in [(x[5], x[6]) for x in self.sql("SELECT action, resource_id, actor_username, company_id, warehouse_id, before_json, after_json FROM audit_logs")]:
            for blob in (b, a):
                self.assertNotIn('"otp', (blob or "").lower())
                self.assertNotIn("password", (blob or "").lower())
        self.send(d, "POST", "/api/deliveries", {"po_number": "PO-P7-AUDIT", "expected_date": "2026-12-01"})
        self.assertTrue(self.audit_rows("delivery.created", resource_id="PO-P7-AUDIT"))

    def test_exceptional_actions_need_a_reason_in_every_mode(self):
        inv = self.sql("SELECT id, quantity FROM inventory WHERE warehouse_id = ? LIMIT 1", (self.glass_wh[0],))[0]
        d = self.client("david", self.glass_wh[0])
        r = self.send(d, "PUT", f"/api/inventory/{inv[0]}", {"quantity": inv[1] + 1})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (400, "reason_required"))
        self.assertEqual(self.sql("SELECT quantity FROM inventory WHERE id = ?", (inv[0],))[0][0], inv[1])
        r = d.open(f"/api/inventory/{inv[0]}", method="PUT", json={"quantity": inv[1] + 1},
                   headers={"X-CSRF-Token": "t", "X-Warehouse-Id": str(self.glass_wh[0]), "X-Action-Reason": "recount found one more"})
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))
        rows = self.audit_rows("inventory.adjusted", resource_id=str(inv[0]))
        self.assertTrue(rows)
        self.assertEqual(rows[0][4], "recount found one more")
        self.assertEqual(json.loads(rows[0][5])["quantity"], inv[1])
        self.assertEqual(json.loads(rows[0][6])["quantity"], inv[1] + 1)
        # a template preview changes nothing, so it needs no reason
        r = self.send(d, "POST", "/api/industry_blueprints/apply", {"blueprint_key": "glass", "preview": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_activity_log_is_per_company(self):
        import db
        import rbac_scope
        with rbac_scope.using(rbac_scope.Scope.warehouse(self.glass_wh[1], self.glass_wh[0])):
            db.log_activity("CYCLE_COUNT_AUDIT", "BIN-P7", "glass only")
        with rbac_scope.using(rbac_scope.Scope.warehouse(self.glass_wh[1], self.glass_wh[0])):
            self.assertIn("BIN-P7", [a["target"] for a in db.get_activities()])
        with rbac_scope.using(self.leak_scope):
            self.assertNotIn("BIN-P7", [a["target"] for a in db.get_activities()])


class TestAuditScreen(Phase7Base):
    def test_audit_log_is_company_scoped_and_export_needs_permission(self):
        self.send(self.client("david"), "PUT", "/api/iam/company_settings", {"key": "audit.retention_days", "value": 400})
        rows = self.get(self.client("david"), "/api/iam/audit").get_json()["rows"]
        self.assertTrue(rows)
        self.assertEqual({r["company_id"] for r in rows}, {self.glass_wh[1]})
        leak = self.get(self.client("leakadmin"), "/api/iam/audit").get_json()["rows"]
        self.assertFalse(any(r["company_id"] == self.glass_wh[1] for r in leak))
        allrows = self.get(self.client("admin"), "/api/iam/audit?company_id=all").get_json()
        self.assertGreaterEqual(allrows["total"], len(rows))
        csv_resp = self.get(self.client("david"), "/api/iam/audit/export")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp.content_type)
        self.assertEqual(self.get(self.role_user("gate_security", "p7gate"), "/api/iam/audit").status_code, 403)

    def test_company_settings(self):
        d = self.client("david")
        s = self.get(d, "/api/iam/company_settings").get_json()["settings"]
        self.assertFalse(s["copilot.web_search"])            # H16: off by default
        self.assertTrue(self.send(d, "PUT", "/api/iam/company_settings", {"key": "copilot.web_search", "value": True}).get_json()["success"])
        self.assertTrue(self.get(d, "/api/iam/company_settings").get_json()["settings"]["copilot.web_search"])
        self.assertTrue(self.audit_rows("company.setting_changed", company_id=self.glass_wh[1]))
        self.assertEqual(self.send(d, "PUT", "/api/iam/company_settings", {"key": "audit.retention_days", "value": 5}).status_code, 400)
        self.assertEqual(self.get(self.client("leakadmin"), "/api/iam/company_settings").get_json()["settings"]["copilot.web_search"], False)


class TestCopilotLimits(Phase7Base):
    def test_copilot_actions_follow_permissions_in_audit_mode(self):
        exec_client = self.role_user("executive", "p7copilot")      # copilot.use, no gate.dock.admit
        r = self.send(exec_client, "POST", "/api/copilot/action", {"action": "admit_dock", "params": {"id": "GP-NONE"}})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (403, "permission_denied"))
        r = self.send(exec_client, "POST", "/api/copilot/action", {"action": "drop_tables", "params": {}})
        self.assertEqual(r.status_code, 400)

    def test_only_the_platform_admin_sets_the_ai_key_and_web_search_is_off(self):
        import copilot_service
        svc = copilot_service.get_copilot_service()
        before = svc.get_gemini_api_key()
        r = self.send(self.client("david"), "POST", "/api/copilot/chat",
                      {"message": "set key AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}).get_json()
        self.assertIn("Only the platform administrator", r["reply"])
        self.assertEqual(svc.get_gemini_api_key(), before)
        self.assertTrue(self.audit_rows("copilot.config_refused"))
        calls = []
        orig = copilot_service.urllib.request.urlopen if hasattr(copilot_service, "urllib") else None
        import urllib.request as ur
        real = ur.urlopen
        ur.urlopen = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError("blocked in test"))
        try:
            self.assertEqual(svc._search_web_knowledge("how to stack pallets"), [])
        finally:
            ur.urlopen = real
        self.assertEqual(calls, [], "web search must not run unless the company switched it on")
        q = copilot_service.WarlogCopilotService.sanitize_web_query(
            "rules for PO-SGG-4011 and TN 38 AB 1234, call 9876543210, mail x@y.com, ask david", ["david"])
        for leaked in ("4011", "1234", "9876543210", "x@y.com", "david"):
            self.assertNotIn(leaked, q)


class TestBackgroundActors(Phase7Base):
    def test_auto_dispatch_needs_permission_and_reason_and_background_work_is_system(self):
        g = self.role_user("gate_security", "p7auto")
        self.assertEqual(self.send(g, "POST", "/api/gate/auto_dispatch", {"enabled": True}).status_code, 403)
        d = self.client("david", self.glass_wh[0])
        r = self.send(d, "POST", "/api/gate/auto_dispatch", {"enabled": True})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (400, "reason_required"))
        r = d.open("/api/gate/auto_dispatch", method="POST", json={"enabled": True},
                   headers={"X-CSRF-Token": "t", "X-Warehouse-Id": str(self.glass_wh[0]), "X-Action-Reason": "night shift"})
        self.assertTrue(r.get_json()["success"], r.get_json())
        by = json.loads(self.sql("SELECT value_json FROM warehouse_settings WHERE warehouse_id = ? AND key = 'gate.auto_dispatch.enabled_by'",
                                 (self.glass_wh[0],))[0][0])
        self.assertEqual((by["username"], by["reason"]), ("david", "night shift"))
        # a gate pass made by ANPR in this warehouse is recorded as system:anpr / system:auto_dispatch
        import rbac_scope
        import vision_runtime_service as vrs
        with rbac_scope.using(rbac_scope.Scope.warehouse(self.glass_wh[1], self.glass_wh[0])):
            vrs._audit_background_gate_pass("CAM-001", "GP-P7SYS", {"plate": "TN01SYS", "status": "Sent to Dock",
                                                                    "dock": "Dock 1"}, True)
        self.assertEqual(self.audit_rows("gate.pass_created", resource_id="GP-P7SYS")[0][0], "system:anpr")
        row = self.audit_rows("gate.dock_admitted", resource_id="GP-P7SYS")[0]
        self.assertEqual(row[0], "system:auto_dispatch")
        self.assertEqual(json.loads(row[6])["auto_dispatch_enabled_by"], "david")
        self.send(d, "POST", "/api/gate/auto_dispatch", {"enabled": False})


if __name__ == "__main__":
    unittest.main()
