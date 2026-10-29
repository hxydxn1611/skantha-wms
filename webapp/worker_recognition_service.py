"""
W.A.R.L.O.G. / Skantha WMS - Live Worker Recognition & Training Service
Allows enrolling/training warehouse workers from the live camera feed or uploaded photos,
and recognizes workers in real time to display their names on the live video feed.
"""

import os
import json
import time
import uuid
import base64
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np
import db

logger = logging.getLogger("worker_recognition_service")
logger.setLevel(logging.INFO)

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_UPLOAD_DIR = os.path.join(ROOT_DIR, "static", "uploads", "workers")
os.makedirs(WORKER_UPLOAD_DIR, exist_ok=True)


class WorkerRecognitionService:
    """
    Combines OpenCV Haar Face Detection, facial spatial-gradient descriptors,
    and upper/lower torso appearance histograms with temporal Track-ID locking
    for real-time worker name recognition on live CCTV / Wi-Fi camera feeds.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.show_worker_names: bool = True
        self._workers_cache: List[Dict[str, Any]] = []
        self._cache_loaded = False
        # Per-(camera_id, track_id) smoothed identity cache:
        # { (camera_id, track_id): {"name": str, "worker_code": str, "role": str, "score": float, "updated_at": float} }
        self._track_bindings: Dict[Tuple[str, Any], Dict[str, Any]] = {}
        self._face_cascade = None
        try:
            cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            if os.path.isfile(cascade_path):
                self._face_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception as e:
            logger.warning(f"Face cascade init warning: {e}")

        self._ensure_table()
        self.reload_workers()

    def _ensure_table(self):
        try:
            conn = db.get_db()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trained_workers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT DEFAULT 'Operator',
                    photo_path TEXT,
                    signature_json TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to initialize trained_workers table: {e}")

    def reload_workers(self) -> List[Dict[str, Any]]:
        """Loads all active trained workers and their precomputed signatures into memory."""
        with self.lock:
            self._ensure_table()
            workers = []
            try:
                conn = db.get_db()
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, worker_code, name, role, photo_path, signature_json, created_at "
                    "FROM trained_workers WHERE is_active = 1 ORDER BY id DESC"
                )
                rows = cur.fetchall()
                conn.close()
                for r in rows:
                    sig_raw = r[5]
                    sig = {}
                    if sig_raw:
                        try:
                            sig = json.loads(sig_raw)
                        except Exception:
                            sig = {}
                    workers.append({
                        "id": r[0],
                        "worker_code": r[1],
                        "name": r[2],
                        "role": r[3] or "Operator",
                        "photo_path": r[4] or "",
                        "signature": sig,
                        "created_at": r[6]
                    })
            except Exception as e:
                logger.warning(f"Error loading trained workers: {e}")
            self._workers_cache = workers
            self._cache_loaded = True
            return workers

    def list_workers(self) -> List[Dict[str, Any]]:
        with self.lock:
            if not self._cache_loaded:
                self.reload_workers()
            return [
                {
                    "id": w["id"],
                    "worker_code": w["worker_code"],
                    "name": w["name"],
                    "role": w["role"],
                    "photo_path": w["photo_path"],
                    "created_at": w["created_at"]
                }
                for w in self._workers_cache
            ]

    def set_show_worker_names(self, enabled: bool) -> bool:
        with self.lock:
            self.show_worker_names = bool(enabled)
            return self.show_worker_names

    def extract_signature(self, person_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Extracts a multi-part visual signature from a person/worker image or crop:
        1) Face vector (64-D spatial illumination-normalized gradient + intensity profile if face detected)
        2) Upper-body / shirt HSV histogram (64-D normalized vector)
        3) Lower-body HSV histogram (32-D normalized vector)
        """
        if person_bgr is None or person_bgr.size == 0:
            return {}

        h, w = person_bgr.shape[:2]
        if h < 16 or w < 16:
            return {}

        std_crop = cv2.resize(person_bgr, (96, 192))
        hsv = cv2.cvtColor(std_crop, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(std_crop, cv2.COLOR_BGR2GRAY)

        # 1. Try face detection on upper half of crop (or full image if portrait)
        face_vec: List[float] = []
        if self._face_cascade is not None:
            try:
                upper_gray = gray[:110, :]
                faces = self._face_cascade.detectMultiScale(
                    upper_gray, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20)
                )
                if len(faces) == 0:
                    faces = self._face_cascade.detectMultiScale(
                        gray, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20)
                    )
                if len(faces) > 0:
                    # Pick largest face
                    fx, fy, fw, fh = max(faces, key=lambda b: b[2] * b[3])
                    face_patch = gray[fy:fy + fh, fx:fx + fw]
                    if face_patch.size > 0:
                        face_norm = cv2.resize(face_patch, (16, 16))
                        face_norm = cv2.equalizeHist(face_norm)
                        vec = face_norm.flatten().astype(np.float32)
                        norm = float(np.linalg.norm(vec))
                        if norm > 1e-6:
                            vec = vec / norm
                        face_vec = [round(float(x), 4) for x in vec]
            except Exception:
                pass

        # If no Haar face detected, take head/face zone (top 10%..32%, center 25%..75% width)
        if not face_vec:
            head_patch = gray[12:60, 24:72]
            head_norm = cv2.resize(head_patch, (8, 8))
            head_norm = cv2.equalizeHist(head_norm)
            vec = head_norm.flatten().astype(np.float32)
            norm = float(np.linalg.norm(vec))
            if norm > 1e-6:
                vec = vec / norm
            face_vec = [round(float(x), 4) for x in vec]

        # 2. Upper-body / Torso HSV Histogram (rows 30% to 68%, cols 15% to 85%)
        upper_hsv = hsv[56:130, 14:82]
        hist_upper = cv2.calcHist([upper_hsv], [0, 1], None, [12, 6], [0, 180, 0, 256]).flatten().astype(np.float32)
        u_norm = float(np.linalg.norm(hist_upper))
        if u_norm > 1e-6:
            hist_upper = hist_upper / u_norm
        upper_vec = [round(float(x), 4) for x in hist_upper]

        # 3. Lower-body HSV Histogram (rows 68% to 95%, cols 15% to 85%)
        lower_hsv = hsv[130:182, 14:82]
        hist_lower = cv2.calcHist([lower_hsv], [0, 1], None, [8, 4], [0, 180, 0, 256]).flatten().astype(np.float32)
        l_norm = float(np.linalg.norm(hist_lower))
        if l_norm > 1e-6:
            hist_lower = hist_lower / l_norm
        lower_vec = [round(float(x), 4) for x in hist_lower]

        return {
            "face_vec": face_vec,
            "upper_vec": upper_vec,
            "lower_vec": lower_vec
        }

    @staticmethod
    def _cosine_sim(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom <= 1e-6:
            return 0.0
        return float(np.dot(a, b) / denom)

    def compare_signatures(self, sig1: Dict[str, Any], sig2: Dict[str, Any]) -> float:
        if not sig1 or not sig2:
            return 0.0
        f_sim = self._cosine_sim(sig1.get("face_vec", []), sig2.get("face_vec", []))
        u_sim = self._cosine_sim(sig1.get("upper_vec", []), sig2.get("upper_vec", []))
        l_sim = self._cosine_sim(sig1.get("lower_vec", []), sig2.get("lower_vec", []))

        # Weighted combination of upper-torso appearance, face/head structure, and lower-body
        if f_sim > 0:
            score = 0.35 * f_sim + 0.45 * u_sim + 0.20 * l_sim
        else:
            score = 0.70 * u_sim + 0.30 * l_sim
        return round(max(0.0, min(1.0, score)), 4)

    def train_worker(
        self,
        name: str,
        role: str = "Operator",
        frame_bgr: Optional[np.ndarray] = None,
        camera_id: Optional[str] = None,
        track_id: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Enrolls or updates a worker profile from either a provided image/crop or a live camera feed.
        """
        clean_name = (name or "").strip()
        if not clean_name:
            return {"success": False, "message": "Worker name is required."}

        clean_role = (role or "Operator").strip() or "Operator"
        person_crop = None
        bound_tid = track_id

        # If camera_id provided without frame_bgr, grab from live camera session
        if frame_bgr is None and camera_id:
            try:
                from vision_runtime_service import get_vision_runtime_manager, get_shared_frame_bus
                mgr = get_vision_runtime_manager()
                sess = mgr.get_session(camera_id)
                if sess and sess.latest_raw_frame is not None:
                    frame_bgr = sess.latest_raw_frame.copy()
                    # Find worker bounding box in latest_boxes
                    worker_boxes = [b for b in (sess.latest_boxes or []) if b.get("is_person")]
                    if worker_boxes:
                        chosen = None
                        if bound_tid is not None:
                            chosen = next((b for b in worker_boxes if str(b.get("track_id")) == str(bound_tid)), None)
                        if chosen is None:
                            # Pick largest worker box in frame
                            chosen = max(worker_boxes, key=lambda b: (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]))
                        if chosen:
                            fh, fw = frame_bgr.shape[:2]
                            x1, y1 = max(0, int(chosen["x1"])), max(0, int(chosen["y1"]))
                            x2, y2 = min(fw, int(chosen["x2"])), min(fh, int(chosen["y2"]))
                            if (x2 - x1) > 16 and (y2 - y1) > 16:
                                person_crop = frame_bgr[y1:y2, x1:x2].copy()
                                bound_tid = chosen.get("track_id")
                if frame_bgr is None:
                    frame_bgr = get_shared_frame_bus().get_latest_frame(camera_id, copy=True, max_age_seconds=30.0)
            except Exception as e:
                logger.warning(f"Live camera frame fetch for worker training failed: {e}")

        if frame_bgr is None or frame_bgr.size == 0:
            return {"success": False, "message": "No image or live camera frame available to train worker."}

        if person_crop is None:
            # Check if YOLO detects a person in the uploaded/captured image
            fh, fw = frame_bgr.shape[:2]
            person_crop = frame_bgr.copy()
            try:
                from detection_service import get_detection_engine
                det = get_detection_engine().detect(image_input=frame_bgr, conf_threshold=0.15)
                p_dets = [
                    d for d in (det.get("detections") or [])
                    if str(d.get("class_code", "")).upper() in ("WORKER", "PERSON")
                ]
                if p_dets:
                    best_d = max(p_dets, key=lambda d: (d["bbox"]["x2"] - d["bbox"]["x1"]) * (d["bbox"]["y2"] - d["bbox"]["y1"]))
                    bb = best_d["bbox"]
                    x1, y1 = max(0, int(bb["x1"])), max(0, int(bb["y1"]))
                    x2, y2 = min(fw, int(bb["x2"])), min(fh, int(bb["y2"]))
                    if (x2 - x1) > 20 and (y2 - y1) > 20:
                        person_crop = frame_bgr[y1:y2, x1:x2].copy()
            except Exception:
                pass

        sig = self.extract_signature(person_crop)
        worker_code = f"WRK-{uuid.uuid4().hex[:6].upper()}"
        fname = f"{worker_code.lower()}_{int(time.time())}.jpg"
        abs_photo_path = os.path.join(WORKER_UPLOAD_DIR, fname)
        rel_photo_path = f"/static/uploads/workers/{fname}"

        try:
            cv2.imwrite(abs_photo_path, person_crop)
        except Exception as e:
            logger.warning(f"Could not save worker photo: {e}")

        try:
            conn = db.get_db()
            cur = conn.cursor()
            # Check if worker with same name already exists; if so, update their profile
            cur.execute("SELECT id, worker_code FROM trained_workers WHERE LOWER(name) = LOWER(?) AND is_active = 1", (clean_name,))
            existing = cur.fetchone()
            if existing:
                worker_code = existing[1]
                cur.execute(
                    "UPDATE trained_workers SET role = ?, photo_path = ?, signature_json = ? WHERE id = ?",
                    (clean_role, rel_photo_path, json.dumps(sig), existing[0])
                )
            else:
                cur.execute(
                    "INSERT INTO trained_workers (worker_code, name, role, photo_path, signature_json, is_active) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (worker_code, clean_name, clean_role, rel_photo_path, json.dumps(sig))
                )
            conn.commit()
            conn.close()
        except Exception as e:
            return {"success": False, "message": f"Database error saving trained worker: {e}"}

        self.reload_workers()

        # Immediately bind to active track on this camera if available
        if camera_id and bound_tid is not None:
            with self.lock:
                self._track_bindings[(str(camera_id), bound_tid)] = {
                    "name": clean_name,
                    "worker_code": worker_code,
                    "role": clean_role,
                    "score": 0.99,
                    "updated_at": time.time()
                }

        return {
            "success": True,
            "worker": {
                "worker_code": worker_code,
                "name": clean_name,
                "role": clean_role,
                "photo_path": rel_photo_path
            },
            "message": f"Worker '{clean_name}' trained and activated for live feed recognition!"
        }

    def delete_worker(self, worker_code: str) -> bool:
        with self.lock:
            try:
                conn = db.get_db()
                conn.execute("DELETE FROM trained_workers WHERE worker_code = ? OR CAST(id AS TEXT) = ?", (worker_code, str(worker_code)))
                conn.commit()
                conn.close()
                # Clear bindings for this worker
                to_del = [k for k, v in self._track_bindings.items() if v.get("worker_code") == worker_code]
                for k in to_del:
                    self._track_bindings.pop(k, None)
                self.reload_workers()
                return True
            except Exception as e:
                logger.warning(f"Error deleting worker {worker_code}: {e}")
                return False

    def identify_worker(
        self,
        frame_bgr: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        camera_id: str,
        track_id: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Matches a detected person bounding box against enrolled workers.
        Uses temporal track binding so recognized worker names remain rock-solid while moving.
        """
        with self.lock:
            if not self.show_worker_names:
                return None
            if not self._cache_loaded:
                self.reload_workers()
            if not self._workers_cache:
                return None

            now = time.time()
            bind_key = (str(camera_id), track_id)

            # Reuse recent binding for this track_id (re-verify every 3.5 seconds)
            existing_bind = self._track_bindings.get(bind_key)
            if existing_bind and (now - existing_bind.get("updated_at", 0.0)) < 3.5:
                return existing_bind

            workers_snapshot = list(self._workers_cache)

        if frame_bgr is None or frame_bgr.size == 0:
            return existing_bind

        fh, fw = frame_bgr.shape[:2]
        cx1, cy1 = max(0, min(fw - 2, int(x1))), max(0, min(fh - 2, int(y1)))
        cx2, cy2 = max(cx1 + 2, min(fw, int(x2))), max(cy1 + 2, min(fh, int(y2)))
        crop = frame_bgr[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return existing_bind

        cand_sig = self.extract_signature(crop)
        if not cand_sig:
            return existing_bind

        best_worker = None
        best_score = -1.0
        for w in workers_snapshot:
            ref_sig = w.get("signature") or {}
            sc = self.compare_signatures(cand_sig, ref_sig)
            if sc > best_score:
                best_score = sc
                best_worker = w

        # Threshold: 0.42 if multiple workers, or 0.32 if only 1 worker is enrolled
        min_thresh = 0.32 if len(workers_snapshot) == 1 else 0.42
        if best_worker and best_score >= min_thresh:
            match_info = {
                "name": best_worker["name"],
                "worker_code": best_worker["worker_code"],
                "role": best_worker["role"],
                "score": best_score,
                "updated_at": now
            }
            with self.lock:
                self._track_bindings[bind_key] = match_info
            return match_info

        return existing_bind


_SERVICE_INSTANCE: Optional[WorkerRecognitionService] = None
_SERVICE_LOCK = threading.Lock()


def get_worker_recognition_service() -> WorkerRecognitionService:
    global _SERVICE_INSTANCE
    with _SERVICE_LOCK:
        if _SERVICE_INSTANCE is None:
            _SERVICE_INSTANCE = WorkerRecognitionService()
        return _SERVICE_INSTANCE

