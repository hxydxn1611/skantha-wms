"""
Comprehensive Backend Test Suite for Part 10: Worker <-> Box Association Foundation
Tests all 21 required behaviors, lifecycle states, and boundary conditions.
Every test produces PASS / FAIL.
"""

import os
import sys
import json
import time
import copy
import hashlib
import urllib.request
import urllib.error

# Add webapp directory to path
webapp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webapp")
if webapp_dir not in sys.path:
    sys.path.insert(0, webapp_dir)

from worker_box_association_service import (
    WorkerBoxAssociationConfig,
    AssociationState,
    WorkerBoxAssociationEvidence,
    WorkerBoxAssociation,
    CameraWorkerBoxAssociationSession,
    MultiObjectWorkerBoxAssociationService,
    get_worker_box_association_service
)
from db import get_db

BASE_URL = "http://127.0.0.1:5000"

def get_db_checksum():
    """Calculate MD5 checksum of SQLite database file to verify ZERO database writes."""
    db_path = os.path.join(webapp_dir, "skandha_wms.db")
    if not os.path.exists(db_path):
        return None
    with open(db_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def make_request(path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def print_result(idx, title, passed, detail=""):
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] Test {idx:02d}: {title}")
    if detail:
        print(f"        Detail: {detail}")

def run_all_tests():
    print("=" * 75)
    print("AI VISION & TRACKING MASTER - PART 10 BACKEND VERIFICATION SUITE")
    print("=" * 75)

    results = []
    initial_db_checksum = get_db_checksum()

    # Shared Helper Data: Track fixtures
    def create_mock_worker(w_id=7, cx=0.35, cy=0.45, zone="DOCK-01", val_status="VALIDATED", ident_val="Maddy"):
        return {
            "track_id": w_id,
            "class_code": "WORKER",
            "confidence": 0.95,
            "bbox": {"x1": 200, "y1": 150, "x2": 300, "y2": 400},
            "bbox_normalized": {"x1": 0.20, "y1": 0.25, "x2": 0.30, "y2": 0.65},
            "center_normalized": [cx, cy],
            "roi": {"inside": True, "zone_code": zone} if zone else {},
            "roi_zone_code": zone,
            "identity": {"status": "IDENTIFIED" if ident_val else "UNIDENTIFIED", "value": ident_val, "source": "QR", "confidence": 0.99},
            "validation": {"status": val_status, "master_type": "WORKER", "master_id": ident_val, "display_name": f"Authorized Personnel ({ident_val})"}
        }

    def create_mock_box(b_id=21, cx=0.40, cy=0.48, zone="DOCK-01", val_status="VALIDATED", ident_val="VLV-900"):
        return {
            "track_id": b_id,
            "class_code": "BOX",
            "confidence": 0.91,
            "bbox": {"x1": 340, "y1": 260, "x2": 450, "y2": 390},
            "bbox_normalized": {"x1": 0.34, "y1": 0.45, "x2": 0.45, "y2": 0.65},
            "center_normalized": [cx, cy],
            "roi": {"inside": True, "zone_code": zone} if zone else {},
            "roi_zone_code": zone,
            "identity": {"status": "IDENTIFIED" if ident_val else "UNIDENTIFIED", "value": ident_val, "source": "QR", "confidence": 0.98},
            "validation": {"status": val_status, "master_type": "BOX", "master_id": ident_val, "display_name": f"Box SKU: {ident_val}"}
        }

    # TEST 1: Single Worker + Box candidate (Frame 1)
    try:
        session = CameraWorkerBoxAssociationSession("TEST-CAM-1")
        w1 = create_mock_worker()
        b1 = create_mock_box()
        assocs = session.update([w1, b1], frame_index=1)
        passed = (len(assocs) == 1 and
                  assocs[0].status == AssociationState.CANDIDATE and
                  assocs[0].consecutive_frames == 1)
        print_result(1, "Single Worker + Box Candidate on First Frame", passed,
                     f"Status: {assocs[0].status}, Consecutive: {assocs[0].consecutive_frames}")
        results.append(passed)
    except Exception as e:
        print_result(1, "Single Worker + Box Candidate on First Frame", False, str(e))
        results.append(False)

    # TEST 2: Confirmation after required frames (>= 3 frames, same zone, score >= 0.70)
    try:
        # Frame 2
        session.update([w1, b1], frame_index=2)
        # Frame 3
        assocs = session.update([w1, b1], frame_index=3)
        a = assocs[0]
        passed = (a.status == AssociationState.CONFIRMED and
                  a.consecutive_frames == 3 and
                  a.association_score >= 0.70 and
                  a.evidence.same_zone and
                  a.evidence.spatial_proximity)
        print_result(2, "Confirmation After 3 Consecutive Frames", passed,
                     f"Status: {a.status}, Consecutive: {a.consecutive_frames}, Score: {a.association_score:.3f}")
        results.append(passed)
    except Exception as e:
        print_result(2, "Confirmation After 3 Consecutive Frames", False, str(e))
        results.append(False)

    # TEST 3: Missing zone prevents confirmation (remains CANDIDATE)
    try:
        session3 = CameraWorkerBoxAssociationSession("TEST-CAM-3")
        w_nozone = create_mock_worker(zone=None)
        b_nozone = create_mock_box(zone=None)
        for f in range(1, 6):
            assocs3 = session3.update([w_nozone, b_nozone], frame_index=f)
        a3 = assocs3[0]
        passed = (a3.status == AssociationState.CANDIDATE and
                  not a3.evidence.same_zone and
                  a3.evidence.worker_zone is None)
        print_result(3, "Missing Zone Prevents Confirmation (Remains CANDIDATE)", passed,
                     f"Status: {a3.status}, Consecutive: {a3.consecutive_frames}, Worker Zone: {a3.evidence.worker_zone}")
        results.append(passed)
    except Exception as e:
        print_result(3, "Missing Zone Prevents Confirmation", False, str(e))
        results.append(False)

    # TEST 4: Different-zone rejection (Worker in DOCK-01, Box in STORAGE-01)
    try:
        session4 = CameraWorkerBoxAssociationSession("TEST-CAM-4")
        w_dock = create_mock_worker(zone="DOCK-01")
        b_storage = create_mock_box(zone="STORAGE-01")
        assocs4 = session4.update([w_dock, b_storage], frame_index=1)
        a4 = assocs4[0]
        passed = (a4.status == AssociationState.REJECTED and
                  not a4.evidence.same_zone and
                  a4.evidence.worker_zone == "DOCK-01" and
                  a4.evidence.box_zone == "STORAGE-01")
        print_result(4, "Different-Zone Explicit Rejection", passed,
                     f"Status: {a4.status}, Worker: {a4.evidence.worker_zone}, Box: {a4.evidence.box_zone}")
        results.append(passed)
    except Exception as e:
        print_result(4, "Different-Zone Explicit Rejection", False, str(e))
        results.append(False)

    # TEST 5: Spatial distance rejection (Distance > max_normalized_distance 0.40)
    try:
        session5 = CameraWorkerBoxAssociationSession("TEST-CAM-5")
        w_far = create_mock_worker(cx=0.10, cy=0.10, zone="DOCK-01")
        b_far = create_mock_box(cx=0.85, cy=0.85, zone="DOCK-01")
        assocs5 = session5.update([w_far, b_far], frame_index=1)
        a5 = assocs5[0]
        passed = (a5.status == AssociationState.REJECTED and
                  not a5.evidence.spatial_proximity and
                  a5.evidence.normalized_distance > 0.40)
        print_result(5, "Spatial Distance Rejection (d > 0.40)", passed,
                     f"Status: {a5.status}, Normalized Dist: {a5.evidence.normalized_distance:.3f}")
        results.append(passed)
    except Exception as e:
        print_result(5, "Spatial Distance Rejection", False, str(e))
        results.append(False)

    # TEST 6: Temporal persistence score accumulation
    try:
        session6 = CameraWorkerBoxAssociationSession("TEST-CAM-6")
        w6 = create_mock_worker()
        b6 = create_mock_box()
        s1 = session6.update([w6, b6], frame_index=1)[0].evidence.temporal_persistence_score
        s2 = session6.update([w6, b6], frame_index=2)[0].evidence.temporal_persistence_score
        s3 = session6.update([w6, b6], frame_index=3)[0].evidence.temporal_persistence_score
        passed = (s1 < s2 < s3 and s3 == 1.0)
        print_result(6, "Temporal Persistence Score Accumulation", passed,
                     f"Frame 1: {s1:.2f}, Frame 2: {s2:.2f}, Frame 3: {s3:.2f}")
        results.append(passed)
    except Exception as e:
        print_result(6, "Temporal Persistence Score Accumulation", False, str(e))
        results.append(False)

    # TEST 7: Worker disappearance -> Timeout to EXPIRED
    try:
        session7 = CameraWorkerBoxAssociationSession("TEST-CAM-7")
        w7 = create_mock_worker()
        b7 = create_mock_box()
        # Establish confirmation across 3 frames
        for f in range(1, 4):
            session7.update([w7, b7], frame_index=f)

        # Worker departs; only Box remains in frame 4..7
        expired = False
        for f in range(4, 9):
            assocs7 = session7.update([b7], frame_index=f)
            for a in assocs7:
                if a.worker_track_id == 7 and a.box_track_id == 21:
                    if a.status == AssociationState.EXPIRED:
                        expired = True
                        break
        passed = expired and assocs7[0].missed_frames >= 4
        print_result(7, "Worker Disappearance Leads to EXPIRED State", passed,
                     f"Status: {assocs7[0].status}, Missed frames: {assocs7[0].missed_frames}")
        results.append(passed)
    except Exception as e:
        print_result(7, "Worker Disappearance Leads to EXPIRED", False, str(e))
        results.append(False)

    # TEST 8: Box disappearance -> Timeout to EXPIRED
    try:
        session8 = CameraWorkerBoxAssociationSession("TEST-CAM-8")
        w8 = create_mock_worker()
        b8 = create_mock_box()
        for f in range(1, 4):
            session8.update([w8, b8], frame_index=f)

        # Box departs; only Worker remains
        expired = False
        for f in range(4, 9):
            assocs8 = session8.update([w8], frame_index=f)
            for a in assocs8:
                if a.worker_track_id == 7 and a.box_track_id == 21:
                    if a.status == AssociationState.EXPIRED:
                        expired = True
                        break
        passed = expired and assocs8[0].missed_frames >= 4
        print_result(8, "Box Disappearance Leads to EXPIRED State", passed,
                     f"Status: {assocs8[0].status}, Missed frames: {assocs8[0].missed_frames}")
        results.append(passed)
    except Exception as e:
        print_result(8, "Box Disappearance Leads to EXPIRED", False, str(e))
        results.append(False)

    # TEST 9: Multiple workers evaluated independently
    try:
        session9 = CameraWorkerBoxAssociationSession("TEST-CAM-9")
        w9_1 = create_mock_worker(w_id=1, cx=0.30, cy=0.40)
        w9_2 = create_mock_worker(w_id=2, cx=0.70, cy=0.70)
        b9 = create_mock_box(b_id=10, cx=0.32, cy=0.42)

        assocs9 = session9.update([w9_1, w9_2, b9], frame_index=1)
        passed = (len(assocs9) == 2 and
                  {a.worker_track_id for a in assocs9} == {1, 2})
        print_result(9, "Multiple Workers Evaluated Independently", passed,
                     f"Pairs evaluated: {[f'W#{a.worker_track_id}<->B#{a.box_track_id}' for a in assocs9]}")
        results.append(passed)
    except Exception as e:
        print_result(9, "Multiple Workers Evaluated Independently", False, str(e))
        results.append(False)

    # TEST 10: Multiple boxes evaluated independently for single worker
    try:
        session10 = CameraWorkerBoxAssociationSession("TEST-CAM-10")
        w10 = create_mock_worker(w_id=7, cx=0.35, cy=0.45)
        b10_1 = create_mock_box(b_id=101, cx=0.38, cy=0.48)
        b10_2 = create_mock_box(b_id=102, cx=0.40, cy=0.50)

        for f in range(1, 4):
            assocs10 = session10.update([w10, b10_1, b10_2], frame_index=f)

        confirmed_boxes = [a.box_track_id for a in assocs10 if a.status == AssociationState.CONFIRMED]
        passed = len(assocs10) == 2 and len(confirmed_boxes) == 2
        print_result(10, "Multiple Boxes Independently Associated with Single Worker", passed,
                     f"Confirmed box track IDs: {confirmed_boxes}")
        results.append(passed)
    except Exception as e:
        print_result(10, "Multiple Boxes Independently Associated", False, str(e))
        results.append(False)

    # TEST 11: Multiple workers + Multiple boxes (Independent disjoint pairs)
    try:
        session11 = CameraWorkerBoxAssociationSession("TEST-CAM-11")
        w1 = create_mock_worker(w_id=1, cx=0.20, cy=0.30, zone="DOCK-01")
        b1 = create_mock_box(b_id=10, cx=0.22, cy=0.32, zone="DOCK-01")
        w2 = create_mock_worker(w_id=2, cx=0.75, cy=0.75, zone="STAGE-01")
        b2 = create_mock_box(b_id=20, cx=0.77, cy=0.77, zone="STAGE-01")

        for f in range(1, 4):
            assocs11 = session11.update([w1, b1, w2, b2], frame_index=f)

        # Pair (1, 10) confirmed in DOCK-01, Pair (2, 20) confirmed in STAGE-01, cross-pairs rejected by zone
        p1 = next(a for a in assocs11 if a.worker_track_id == 1 and a.box_track_id == 10)
        p2 = next(a for a in assocs11 if a.worker_track_id == 2 and a.box_track_id == 20)
        p_cross1 = next(a for a in assocs11 if a.worker_track_id == 1 and a.box_track_id == 20)

        passed = (p1.status == AssociationState.CONFIRMED and
                  p2.status == AssociationState.CONFIRMED and
                  p_cross1.status == AssociationState.REJECTED)
        print_result(11, "Multiple Workers + Multiple Boxes Disjoint Zones", passed,
                     f"P(1,10): {p1.status}, P(2,20): {p2.status}, P(1,20): {p_cross1.status}")
        results.append(passed)
    except Exception as e:
        print_result(11, "Multiple Workers + Multiple Boxes", False, str(e))
        results.append(False)

    # TEST 12: Ambiguity preservation (Equidistant competing workers)
    try:
        session12 = CameraWorkerBoxAssociationSession("TEST-CAM-12")
        # Worker 1 at x=0.25, Worker 2 at x=0.45, Box at x=0.35 (equidistant, distance=0.10)
        w1 = create_mock_worker(w_id=1, cx=0.25, cy=0.40)
        w2 = create_mock_worker(w_id=2, cx=0.45, cy=0.40)
        b = create_mock_box(b_id=50, cx=0.35, cy=0.40)

        for f in range(1, 5):
            assocs12 = session12.update([w1, w2, b], frame_index=f)

        a_w1 = next(a for a in assocs12 if a.worker_track_id == 1 and a.box_track_id == 50)
        a_w2 = next(a for a in assocs12 if a.worker_track_id == 2 and a.box_track_id == 50)

        passed = (a_w1.evidence.is_ambiguous and
                  a_w2.evidence.is_ambiguous and
                  a_w1.status == AssociationState.CANDIDATE and
                  a_w2.status == AssociationState.CANDIDATE and
                  1 in a_w2.evidence.competing_worker_ids and
                  2 in a_w1.evidence.competing_worker_ids)
        print_result(12, "Ambiguity Preservation (Competing Workers Remain CANDIDATE)", passed,
                     f"W1 Ambiguous: {a_w1.evidence.is_ambiguous}, W2 Ambiguous: {a_w2.evidence.is_ambiguous}")
        results.append(passed)
    except Exception as e:
        print_result(12, "Ambiguity Preservation", False, str(e))
        results.append(False)

    # TEST 13: Track-level association without real-world identity
    try:
        session13 = CameraWorkerBoxAssociationSession("TEST-CAM-13")
        w_unid = create_mock_worker(ident_val=None, val_status="NOT_APPLICABLE")
        b_unid = create_mock_box(ident_val=None, val_status="NOT_APPLICABLE")
        for f in range(1, 4):
            assocs13 = session13.update([w_unid, b_unid], frame_index=f)

        a13 = assocs13[0]
        passed = (a13.status == AssociationState.CONFIRMED and
                  a13.real_world_association is None and
                  a13.worker_identity.get("value") is None and
                  a13.box_identity.get("value") is None)
        print_result(13, "Track-Level Association Confirmed Without Identity", passed,
                     f"Track status: {a13.status}, Real-World Association: {a13.real_world_association}")
        results.append(passed)
    except Exception as e:
        print_result(13, "Track-Level Association Without Identity", False, str(e))
        results.append(False)

    # TEST 14: Validated Worker + Validated Box derives Real-World Association
    try:
        session14 = CameraWorkerBoxAssociationSession("TEST-CAM-14")
        w_val = create_mock_worker(ident_val="Maddy", val_status="VALIDATED")
        b_val = create_mock_box(ident_val="VLV-900", val_status="VALIDATED")
        for f in range(1, 4):
            assocs14 = session14.update([w_val, b_val], frame_index=f)

        a14 = assocs14[0]
        rw = a14.real_world_association
        passed = (a14.status == AssociationState.CONFIRMED and
                  rw is not None and
                  rw.get("worker_id") == "Maddy" and
                  rw.get("box_id") == "VLV-900" and
                  rw.get("status") == "VALIDATED")
        print_result(14, "Validated Worker + Validated Box Real-World Binding", passed,
                     f"Real-World: {rw}")
        results.append(passed)
    except Exception as e:
        print_result(14, "Validated Worker + Validated Box Binding", False, str(e))
        results.append(False)

    # TEST 15: Unidentified Worker does NOT claim real-world association
    try:
        session15 = CameraWorkerBoxAssociationSession("TEST-CAM-15")
        w_unid = create_mock_worker(ident_val=None, val_status="NOT_APPLICABLE")
        b_val = create_mock_box(ident_val="VLV-900", val_status="VALIDATED")
        for f in range(1, 4):
            assocs15 = session15.update([w_unid, b_val], frame_index=f)

        a15 = assocs15[0]
        passed = (a15.status == AssociationState.CONFIRMED and
                  a15.real_world_association is None)
        print_result(15, "Unidentified Worker Prevents Real-World Identity Claim", passed,
                     f"Track status: {a15.status}, Real-World: {a15.real_world_association}")
        results.append(passed)
    except Exception as e:
        print_result(15, "Unidentified Worker Prevents Real-World Claim", False, str(e))
        results.append(False)

    # TEST 16: Unregistered Box does NOT claim real-world association
    try:
        session16 = CameraWorkerBoxAssociationSession("TEST-CAM-16")
        w_val = create_mock_worker(ident_val="Maddy", val_status="VALIDATED")
        b_unreg = create_mock_box(ident_val="UNKNOWN-BOX-999", val_status="UNREGISTERED")
        for f in range(1, 4):
            assocs16 = session16.update([w_val, b_unreg], frame_index=f)

        a16 = assocs16[0]
        passed = (a16.status == AssociationState.CONFIRMED and
                  a16.real_world_association is None)
        print_result(16, "Unregistered Box Prevents Real-World Identity Claim", passed,
                     f"Track status: {a16.status}, Real-World: {a16.real_world_association}")
        results.append(passed)
    except Exception as e:
        print_result(16, "Unregistered Box Prevents Real-World Claim", False, str(e))
        results.append(False)

    # TEST 17: Camera isolation (Independent sessions)
    try:
        service = MultiObjectWorkerBoxAssociationService()
        sess_cam1 = service.get_session("CAM-001")
        sess_cam2 = service.get_session("CAM-002")

        w = create_mock_worker(w_id=7)
        b = create_mock_box(b_id=21)
        sess_cam1.update([w, b], frame_index=1)

        passed = (len(sess_cam1.associations) == 1 and
                  len(sess_cam2.associations) == 0)
        print_result(17, "Camera Isolation (Independent Sessions)", passed,
                     f"CAM-001 associations: {len(sess_cam1.associations)}, CAM-002: {len(sess_cam2.associations)}")
        results.append(passed)
    except Exception as e:
        print_result(17, "Camera Isolation", False, str(e))
        results.append(False)

    # TEST 18: Reset behavior
    try:
        sess = service.get_session("CAM-001")
        sess.reset()
        passed = (len(sess.associations) == 0 and sess.frame_index == 0)
        print_result(18, "Session Reset Behavior", passed,
                     f"Associations after reset: {len(sess.associations)}, Frame index: {sess.frame_index}")
        results.append(passed)
    except Exception as e:
        print_result(18, "Session Reset Behavior", False, str(e))
        results.append(False)

    # TEST 19: API Status, Test, and Sequence Endpoints
    try:
        # Status
        status_code, status_data = make_request("/api/vision/worker-box/status", method="GET")
        st_ok = (status_code == 200 and
                 status_data.get("status") == "healthy" and
                 status_data.get("database_access") == "ZERO-WRITES (Strictly In-Memory)")

        # Sequence with synthetic tracks
        seq_payload = {
            "camera_id": "CAM-001",
            "reset_session": True,
            "synthetic_tracks_sequence": [
                [create_mock_worker(), create_mock_box()],
                [create_mock_worker(), create_mock_box()],
                [create_mock_worker(), create_mock_box()]
            ]
        }
        seq_code, seq_data = make_request("/api/vision/worker-box/sequence", method="POST", data=seq_payload)
        seq_ok = (seq_code == 200 and
                  seq_data.get("success") and
                  seq_data.get("total_frames") == 3 and
                  seq_data.get("history")[-1]["confirmed_count"] == 1)

        passed = st_ok and seq_ok
        print_result(19, "REST API Endpoints (/status and /sequence)", passed,
                     f"Status API: {st_ok}, Sequence API confirmed: {seq_ok}")
        results.append(passed)
    except Exception as e:
        print_result(19, "REST API Endpoints", False, str(e))
        results.append(False)

    # TEST 20: Regression verification for Parts 5–9
    try:
        # Part 5 YOLO detection engine
        c5, r5 = make_request("/api/vision/detection/info", method="GET")
        p5 = (c5 == 200 and r5.get("success") is True)

        # Part 6 ByteTrack tracking status
        c6, r6 = make_request("/api/vision/tracking/status", method="GET")
        p6 = (c6 == 200 and r6.get("success") is True)

        # Part 7 Object Identity status
        c7, r7 = make_request("/api/vision/identity/status", method="GET")
        p7 = (c7 == 200 and r7.get("success") is True)

        # Part 8 Master-Data Validation status
        c8, r8 = make_request("/api/vision/validation/status", method="GET")
        p8 = (c8 == 200 and r8.get("status") == "healthy")

        # Part 9 Truck <-> Box Association status
        c9, r9 = make_request("/api/vision/association/status", method="GET")
        p9 = (c9 == 200 and r9.get("status") == "healthy")

        passed = p5 and p6 and p7 and p8 and p9
        print_result(20, "Parts 5–9 Upstream Pipeline Regression", passed,
                     f"Part 5: {p5}, Part 6: {p6}, Part 7: {p7}, Part 8: {p8}, Part 9: {p9}")
        results.append(passed)
    except Exception as e:
        print_result(20, "Parts 5–9 Upstream Pipeline Regression", False, str(e))
        results.append(False)

    # TEST 21: Zero Database Writes Verification (MD5 Checksum Comparison)
    try:
        final_db_checksum = get_db_checksum()
        db_conn = get_db()
        try:
            cur = db_conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [r[0] for r in cur.fetchall()]
            zero_tables_added = (len(tables) == 12)
            has_forbidden_tables = any(t in tables for t in [
                "worker_box_associations", "material_movements", "traceability_history", "worker_associations"
            ])
        finally:
            db_conn.close()

        checksum_matches = (initial_db_checksum == final_db_checksum)
        passed = checksum_matches and zero_tables_added and not has_forbidden_tables
        print_result(21, "Zero Database Writes & Schema Integrity", passed,
                     f"Initial MD5: {initial_db_checksum}, Final MD5: {final_db_checksum}, Tables: {len(tables)}")
        results.append(passed)
    except Exception as e:
        print_result(21, "Zero Database Writes Verification", False, str(e))
        results.append(False)

    print("=" * 75)
    total_passed = sum(results)
    total_tests = len(results)
    print(f"RESULTS SUMMARY: {total_passed} / {total_tests} Tests PASSED.")
    if total_passed == total_tests:
        print(">>> ALL PART 10 BACKEND VERIFICATION TESTS PASSED SUCCESSFULLY! <<<")
    else:
        print(">>> SOME TESTS FAILED. PLEASE REVIEW DETAILS ABOVE. <<<")
    print("=" * 75)

    return total_passed == total_tests

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
