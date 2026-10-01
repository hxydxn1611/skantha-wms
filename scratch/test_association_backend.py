"""
Comprehensive Backend Test Suite for Part 9: Truck <-> Box Association Foundation
Tests all 20 required behaviors and boundary conditions.
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

from association_service import (
    AssociationConfig,
    AssociationState,
    AssociationEvidence,
    TruckBoxAssociation,
    CameraAssociationSession,
    MultiObjectAssociationService,
    get_association_service
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
    print("=" * 70)
    print("AI VISION & TRACKING MASTER - PART 9 BACKEND VERIFICATION SUITE")
    print("=" * 70)

    results = []
    initial_db_checksum = get_db_checksum()

    # Shared Helper Data: Track fixtures
    def create_mock_truck(t_id=10, cx=0.30, cy=0.45, zone="DOCK-01", val_status="VALIDATED", ident_val="GP-1000"):
        return {
            "track_id": t_id,
            "class_code": "TRUCK",
            "confidence": 0.94,
            "bbox": {"x1": 180, "y1": 160, "x2": 420, "y2": 390},
            "bbox_normalized": {"x1": 0.18, "y1": 0.25, "x2": 0.42, "y2": 0.65},
            "center_normalized": [cx, cy],
            "roi": {"inside": True, "zone_code": zone},
            "roi_zone_code": zone,
            "identity": {"status": "IDENTIFIED" if ident_val else "UNIDENTIFIED", "value": ident_val, "source": "QR", "confidence": 0.99},
            "validation": {"status": val_status, "master_type": "TRUCK", "master_id": ident_val, "display_name": f"Truck {ident_val}"}
        }

    def create_mock_box(b_id=21, cx=0.38, cy=0.52, zone="DOCK-01", val_status="VALIDATED", ident_val="VLV-900"):
        return {
            "track_id": b_id,
            "class_code": "BOX",
            "confidence": 0.91,
            "bbox": {"x1": 390, "y1": 310, "x2": 480, "y2": 410},
            "bbox_normalized": {"x1": 0.39, "y1": 0.50, "x2": 0.48, "y2": 0.67},
            "center_normalized": [cx, cy],
            "roi": {"inside": True, "zone_code": zone},
            "roi_zone_code": zone,
            "identity": {"status": "IDENTIFIED" if ident_val else "UNIDENTIFIED", "value": ident_val, "source": "QR", "confidence": 0.98},
            "validation": {"status": val_status, "master_type": "BOX", "master_id": ident_val, "display_name": f"Box {ident_val}"}
        }

    # TEST 1: Single truck + box confirmation across multiple frames
    try:
        session = CameraAssociationSession("TEST-CAM-1")
        t1 = create_mock_truck()
        b1 = create_mock_box()
        # Feed 3 consecutive frames
        session.update([t1, b1], frame_index=1)
        session.update([t1, b1], frame_index=2)
        assocs = session.update([t1, b1], frame_index=3)
        p1 = len(assocs) == 1 and assocs[0].status == AssociationState.CONFIRMED and assocs[0].consecutive_frames == 3
        results.append((1, "Single truck + box confirmation across multiple frames", p1, f"Status={assocs[0].status}, Frames={assocs[0].consecutive_frames}, Score={assocs[0].association_score}"))
    except Exception as e:
        results.append((1, "Single truck + box confirmation across multiple frames", False, str(e)))

    # TEST 2: Same-zone requirement
    try:
        session = CameraAssociationSession("TEST-CAM-2")
        # Truck in DOCK-01, Box without zone
        t2 = create_mock_truck(zone="DOCK-01")
        b2 = create_mock_box(zone=None)
        b2["roi"] = {"inside": False, "zone_code": None}
        b2["roi_zone_code"] = None
        for f in range(1, 4):
            assocs = session.update([t2, b2], frame_index=f)
        # Should NOT be CONFIRMED because same_zone is False
        p2 = len(assocs) == 1 and assocs[0].status == AssociationState.CANDIDATE and not assocs[0].evidence.same_zone
        results.append((2, "Same-zone requirement prevents confirmation when zone is missing", p2, f"Status={assocs[0].status}, same_zone={assocs[0].evidence.same_zone}"))
    except Exception as e:
        results.append((2, "Same-zone requirement prevents confirmation when zone is missing", False, str(e)))

    # TEST 3: Multi-frame threshold (frame 1 -> CANDIDATE, frame 2 -> CANDIDATE, frame 3 -> CONFIRMED)
    try:
        session = CameraAssociationSession("TEST-CAM-3")
        t3 = create_mock_truck()
        b3 = create_mock_box()
        a1 = session.update([t3, b3], frame_index=1)
        stat1 = a1[0].status
        frames1 = a1[0].consecutive_frames
        s1 = stat1 == AssociationState.CANDIDATE and frames1 == 1

        a2 = session.update([t3, b3], frame_index=2)
        stat2 = a2[0].status
        frames2 = a2[0].consecutive_frames
        s2 = stat2 == AssociationState.CANDIDATE and frames2 == 2

        a3 = session.update([t3, b3], frame_index=3)
        stat3 = a3[0].status
        frames3 = a3[0].consecutive_frames
        s3 = stat3 == AssociationState.CONFIRMED and frames3 == 3

        p3 = s1 and s2 and s3
        results.append((3, "Multi-frame threshold progression (1: CANDIDATE -> 2: CANDIDATE -> 3: CONFIRMED)", p3, f"F1={stat1}, F2={stat2}, F3={stat3}"))
    except Exception as e:
        results.append((3, "Multi-frame threshold progression", False, str(e)))

    # TEST 4: Different-zone rejection
    try:
        session = CameraAssociationSession("TEST-CAM-4")
        t4 = create_mock_truck(zone="DOCK-01")
        b4 = create_mock_box(zone="STORAGE-01")
        assocs = session.update([t4, b4], frame_index=1)
        p4 = len(assocs) == 1 and assocs[0].status == AssociationState.REJECTED and assocs[0].evidence.same_zone is False
        results.append((4, "Different-zone rejection (DOCK-01 vs STORAGE-01)", p4, f"Status={assocs[0].status}, TruckZone={assocs[0].evidence.truck_zone}, BoxZone={assocs[0].evidence.box_zone}"))
    except Exception as e:
        results.append((4, "Different-zone rejection", False, str(e)))

    # TEST 5: Multiple trucks handling (independent pairwise candidates)
    try:
        session = CameraAssociationSession("TEST-CAM-5")
        t1 = create_mock_truck(t_id=10, cx=0.25, cy=0.40)
        t2 = create_mock_truck(t_id=11, cx=0.75, cy=0.40)
        b1 = create_mock_box(b_id=21, cx=0.28, cy=0.45)
        b2 = create_mock_box(b_id=22, cx=0.78, cy=0.45)
        assocs = session.update([t1, t2, b1, b2], frame_index=1)
        # Should have 4 pairwise combinations: (10, 21), (10, 22), (11, 21), (11, 22)
        pair_keys = {(a.truck_track_id, a.box_track_id) for a in assocs}
        p5 = len(pair_keys) == 4 and (10, 21) in pair_keys and (11, 22) in pair_keys
        results.append((5, "Multiple trucks independent pairwise candidates (2 Trucks x 2 Boxes = 4 Pairs)", p5, f"Pairs={pair_keys}"))
    except Exception as e:
        results.append((5, "Multiple trucks independent pairwise candidates", False, str(e)))

    # TEST 6: Multiple boxes associated with a single truck
    try:
        session = CameraAssociationSession("TEST-CAM-6")
        t1 = create_mock_truck(t_id=10, cx=0.30, cy=0.40)
        b1 = create_mock_box(b_id=21, cx=0.32, cy=0.44) # Near truck
        b2 = create_mock_box(b_id=22, cx=0.34, cy=0.48) # Also near truck
        for f in range(1, 4):
            assocs = session.update([t1, b1, b2], frame_index=f)
        confirmed_boxes = [a.box_track_id for a in assocs if a.status == AssociationState.CONFIRMED and a.truck_track_id == 10]
        p6 = len(confirmed_boxes) == 2 and 21 in confirmed_boxes and 22 in confirmed_boxes
        results.append((6, "Multiple boxes associated with a single truck (Truck #10 with Box #21 and Box #22)", p6, f"Confirmed Boxes={confirmed_boxes}"))
    except Exception as e:
        results.append((6, "Multiple boxes associated with a single truck", False, str(e)))

    # TEST 7: Ambiguous candidate handling (Two trucks equidistant to one box)
    try:
        session = CameraAssociationSession("TEST-CAM-7")
        # Box at cx=0.50, cy=0.50. Truck 1 at cx=0.42, Truck 2 at cx=0.58 (both dist = 0.08)
        t1 = create_mock_truck(t_id=10, cx=0.42, cy=0.50)
        t2 = create_mock_truck(t_id=11, cx=0.58, cy=0.50)
        b1 = create_mock_box(b_id=21, cx=0.50, cy=0.50)
        for f in range(1, 4):
            assocs = session.update([t1, t2, b1], frame_index=f)
        # Neither should be CONFIRMED because ambiguity flags both as CANDIDATE
        box_assocs = [a for a in assocs if a.box_track_id == 21]
        is_ambig = all(a.evidence.is_ambiguous for a in box_assocs)
        none_confirmed = all(a.status == AssociationState.CANDIDATE for a in box_assocs)
        p7 = is_ambig and none_confirmed and len(box_assocs) == 2
        results.append((7, "Ambiguous candidate handling preserves competing trucks without arbitrary winner", p7, f"IsAmbig={is_ambig}, Statuses={[a.status for a in box_assocs]}"))
    except Exception as e:
        results.append((7, "Ambiguous candidate handling", False, str(e)))

    # TEST 8: Truck disappearance / expiry
    try:
        session = CameraAssociationSession("TEST-CAM-8")
        t1 = create_mock_truck()
        b1 = create_mock_box()
        # Frames 1-3: both present -> CONFIRMED
        for f in range(1, 4):
            session.update([t1, b1], frame_index=f)
        # Frames 4-8: truck disappears, only box present
        for f in range(4, 9):
            assocs = session.update([b1], frame_index=f)
        assoc_pair = [a for a in assocs if a.truck_track_id == 10 and a.box_track_id == 21][0]
        p8 = assoc_pair.status == AssociationState.EXPIRED and assoc_pair.missed_frames >= 4
        results.append((8, "Truck disappearance transitions association to EXPIRED after timeout", p8, f"Status={assoc_pair.status}, MissedFrames={assoc_pair.missed_frames}"))
    except Exception as e:
        results.append((8, "Truck disappearance / expiry", False, str(e)))

    # TEST 9: Box disappearance / expiry
    try:
        session = CameraAssociationSession("TEST-CAM-9")
        t1 = create_mock_truck()
        b1 = create_mock_box()
        for f in range(1, 4):
            session.update([t1, b1], frame_index=f)
        # Frames 4-8: box disappears, only truck present
        for f in range(4, 9):
            assocs = session.update([t1], frame_index=f)
        assoc_pair = [a for a in assocs if a.truck_track_id == 10 and a.box_track_id == 21][0]
        p9 = assoc_pair.status == AssociationState.EXPIRED and assoc_pair.missed_frames >= 4
        results.append((9, "Box disappearance transitions association to EXPIRED after timeout", p9, f"Status={assoc_pair.status}, MissedFrames={assoc_pair.missed_frames}"))
    except Exception as e:
        results.append((9, "Box disappearance / expiry", False, str(e)))

    # TEST 10: Track-level association without validated identity
    try:
        session = CameraAssociationSession("TEST-CAM-10")
        t1 = create_mock_truck(val_status="NOT_APPLICABLE", ident_val=None)
        b1 = create_mock_box(val_status="NOT_APPLICABLE", ident_val=None)
        for f in range(1, 4):
            assocs = session.update([t1, b1], frame_index=f)
        assoc = assocs[0]
        p10 = assoc.status == AssociationState.CONFIRMED and assoc.real_world_association is None
        results.append((10, "Track-level association confirmed without claiming real-world identity", p10, f"Status={assoc.status}, RealWorldAssoc={assoc.real_world_association}"))
    except Exception as e:
        results.append((10, "Track-level association without validated identity", False, str(e)))

    # TEST 11: Validated truck + validated box produces real-world association
    try:
        session = CameraAssociationSession("TEST-CAM-11")
        t1 = create_mock_truck(val_status="VALIDATED", ident_val="GP-1000")
        b1 = create_mock_box(val_status="VALIDATED", ident_val="VLV-900")
        for f in range(1, 4):
            assocs = session.update([t1, b1], frame_index=f)
        assoc = assocs[0]
        rw = assoc.real_world_association
        p11 = (
            assoc.status == AssociationState.CONFIRMED and
            rw is not None and
            rw.get("truck_id") == "GP-1000" and
            rw.get("box_id") == "VLV-900" and
            rw.get("status") == "VALIDATED"
        )
        results.append((11, "Validated truck + validated box derives real-world association (GP-1000 <-> VLV-900)", p11, f"RW={rw}"))
    except Exception as e:
        results.append((11, "Validated truck + validated box", False, str(e)))

    # TEST 12: Validated truck + unregistered box does NOT claim real-world association
    try:
        session = CameraAssociationSession("TEST-CAM-12")
        t1 = create_mock_truck(val_status="VALIDATED", ident_val="GP-1000")
        b1 = create_mock_box(val_status="UNREGISTERED", ident_val="B999999")
        for f in range(1, 4):
            assocs = session.update([t1, b1], frame_index=f)
        assoc = assocs[0]
        p12 = assoc.status == AssociationState.CONFIRMED and assoc.real_world_association is None
        results.append((12, "Validated truck + unregistered box does NOT claim real-world association", p12, f"Status={assoc.status}, RealWorldAssoc={assoc.real_world_association}"))
    except Exception as e:
        results.append((12, "Validated truck + unregistered box", False, str(e)))

    # TEST 13: Duplicate pair handling (re-encountering same pair updates state instead of creating duplicates)
    try:
        session = CameraAssociationSession("TEST-CAM-13")
        t1 = create_mock_truck()
        b1 = create_mock_box()
        session.update([t1, b1], frame_index=1)
        session.update([t1, b1], frame_index=2)
        session.update([t1, b1], frame_index=3)
        # Key count in session.associations must remain exactly 1
        p13 = len(session.associations) == 1 and (10, 21) in session.associations
        results.append((13, "Duplicate pair handling updates existing in-memory association cleanly", p13, f"MapSize={len(session.associations)}"))
    except Exception as e:
        results.append((13, "Duplicate pair handling", False, str(e)))

    # TEST 14: Camera isolation (CAM-001 vs CAM-002)
    try:
        service = MultiObjectAssociationService()
        t1 = create_mock_truck()
        b1 = create_mock_box()
        # Feed CAM-001 for 3 frames -> CONFIRMED
        for f in range(1, 4):
            service.process_tracks([t1, b1], camera_id="CAM-001", frame_index=f)
        # Feed CAM-002 for only 1 frame -> CANDIDATE
        assocs_cam2, _ = service.process_tracks([t1, b1], camera_id="CAM-002", frame_index=1)
        sess1 = service.get_session("CAM-001")
        p14 = (
            sess1.associations[(10, 21)].status == AssociationState.CONFIRMED and
            assocs_cam2[0]["status"] == AssociationState.CANDIDATE and
            assocs_cam2[0]["evidence"]["consecutive_frames"] == 1
        )
        results.append((14, "Camera isolation: CAM-001 confirmed state does not leak into CAM-002", p14, f"CAM-1={sess1.associations[(10, 21)].status}, CAM-2={assocs_cam2[0]['status']}"))
    except Exception as e:
        results.append((14, "Camera isolation", False, str(e)))

    # TEST 15: Reset behavior
    try:
        service = MultiObjectAssociationService()
        t1 = create_mock_truck()
        b1 = create_mock_box()
        for f in range(1, 4):
            service.process_tracks([t1, b1], camera_id="CAM-TEST", frame_index=f)
        sess = service.get_session("CAM-TEST")
        pre_reset_cnt = len(sess.associations)
        service.reset_session("CAM-TEST")
        post_reset_cnt = len(sess.associations)
        p15 = pre_reset_cnt == 1 and post_reset_cnt == 0 and sess.frame_index == 0
        results.append((15, "Reset behavior cleanly clears in-memory camera session and resets counters", p15, f"Pre={pre_reset_cnt}, Post={post_reset_cnt}, FrameIdx={sess.frame_index}"))
    except Exception as e:
        results.append((15, "Reset behavior", False, str(e)))

    # TEST 16: API GET /api/vision/association/status
    try:
        status_code, body = make_request("/api/vision/association/status")
        p16 = (
            status_code == 200 and
            body.get("status") == "healthy" and
            "config" in body and
            body.get("database_access") == "ZERO-WRITES (Strictly In-Memory)" and
            "upstream_validation" in body
        )
        results.append((16, "API GET /api/vision/association/status returns healthy and correct schema", p16, f"StatusCode={status_code}, Access={body.get('database_access')}"))
    except Exception as e:
        results.append((16, "API status endpoint", False, str(e)))

    # TEST 17: API POST /api/vision/association/test
    try:
        payload = {
            "camera_id": "CAM-001",
            "source_type": "sample",
            "sample_scene": "association_truck_box_dock1.jpg"
        }
        status_code, body = make_request("/api/vision/association/test", method="POST", data=payload)
        p17 = (
            status_code == 200 and
            body.get("success") is True and
            "associations" in body and
            "performance" in body and
            "association_ms" in body.get("performance", {})
        )
        results.append((17, "API POST /api/vision/association/test executes perception pipeline with association layer", p17, f"StatusCode={status_code}, AssocsCount={len(body.get('associations', []))}"))
    except Exception as e:
        results.append((17, "API test endpoint", False, str(e)))

    # TEST 18: API POST /api/vision/association/sequence
    try:
        t1 = create_mock_truck()
        b1 = create_mock_box()
        # Send 5-frame synthetic sequence
        synthetic_seq = [[t1, b1] for _ in range(5)]
        payload = {
            "camera_id": "CAM-API-SEQ",
            "reset_session": True,
            "synthetic_tracks_sequence": synthetic_seq
        }
        status_code, body = make_request("/api/vision/association/sequence", method="POST", data=payload)
        p18 = (
            status_code == 200 and
            body.get("success") is True and
            len(body.get("history", [])) == 5 and
            body.get("final_associations", [])[0]["status"] == "CONFIRMED"
        )
        results.append((18, "API POST /api/vision/association/sequence runs multi-frame sequence to CONFIRMED", p18, f"StatusCode={status_code}, TotalFrames={body.get('total_frames')}, FinalStatus={body.get('final_associations', [{}])[0].get('status')}"))
    except Exception as e:
        results.append((18, "API sequence endpoint", False, str(e)))

    # TEST 19: Parts 5-8 regression verification
    try:
        # Check Part 5 /detection/info, Part 6 /tracking/status, Part 7 /identity/status, Part 8 /validation/status
        s5, b5 = make_request("/api/vision/detection/info")
        s6, b6 = make_request("/api/vision/tracking/status")
        s7, b7 = make_request("/api/vision/identity/status")
        s8, b8 = make_request("/api/vision/validation/status")
        p19 = (
            s5 == 200 and b5.get("success") is True and
            s6 == 200 and b6.get("success") is True and
            s7 == 200 and b7.get("success") is True and
            s8 == 200 and b8.get("status") == "healthy"
        )
        results.append((19, "Parts 5–8 Regression Check: Detection, Tracking, Identity, and Validation all healthy", p19, f"P5={s5}, P6={s6}, P7={s7}, P8={s8}"))
    except Exception as e:
        results.append((19, "Parts 5-8 regression", False, str(e)))

    # TEST 20: Zero database writes verification
    try:
        final_db_checksum = get_db_checksum()
        p20 = (initial_db_checksum is not None) and (initial_db_checksum == final_db_checksum)
        results.append((20, "Zero Database Writes: SQLite database MD5 checksum unchanged before and after tests", p20, f"InitMD5={initial_db_checksum}, FinalMD5={final_db_checksum}"))
    except Exception as e:
        results.append((20, "Zero database writes", False, str(e)))

    # Print summary
    print("\n" + "=" * 70)
    print("DETAILED TEST EXECUTION RESULTS:")
    print("=" * 70)
    all_passed = True
    for idx, title, passed, detail in results:
        print_result(idx, title, passed, detail)
        if not passed:
            all_passed = False

    print("=" * 70)
    passed_count = sum(1 for _, _, p, _ in results if p)
    print(f"SUMMARY: {passed_count}/{len(results)} TESTS PASSED ({'ALL PASS' if all_passed else 'FAILURES DETECTED'})")
    print("=" * 70)

    return all_passed

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
