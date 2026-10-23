import os
import cv2
import threading
import time
import copy
import numpy as np
from ultralytics import YOLO
import easyocr
from scipy.signal import find_peaks
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial import cKDTree
from identity_service import get_identity_service
from zone_engine import get_camera_tripwire, evaluate_tripwire_crossing

class SmartCamera:
    def __init__(self, camera_id, name, url, location, cam_type="IP Camera", vendor="Unknown", bin_id=None):
        self.camera_id = camera_id
        self.name = name
        self.url = url
        self.location = location
        self.cam_type = cam_type
        self.vendor = vendor
        self.bin_id = bin_id
        self.is_running = False
        self.events = []
        self.visible_packages = 0
        self.visible_boxes = 0
        self.visible_car_parts = 0
        self.clustered_bundle_count = 0
        self.primary_pile_envelope = None
        self.detected_bar_layers = 0
        self.bar_layer_peaks = []
        self.bar_stack_bbox = None
        self.detected_heads = []
        self.cluster_breakdown = {}
        self.head_count = 0
        self.is_frozen = False
        self.frozen_jpeg = None
        self.tracker_items = {}
        self.next_pin_id = 1
        self.last_package_count = 0
        self.consecutive_zeros = 0
        self.seen_package_ids = set()
        self.total_unloaded = 0
        
        # Phase 2: Database-driven dynamic tripwire (no hardcoded defaults)
        self.active_tripwire = None
        self.last_tripwire_check = 0.0
        self.tracked_centroids = {}

        # Gate Camera & ANPR Configuration (Gate camera strictly does NOT count items)
        loc_str = str(self.location or '').strip().lower()
        name_str = str(self.name or '').strip().lower()
        cid_str = str(self.camera_id or '').strip().lower()
        self.is_gate_camera = (loc_str == 'gate' or 'gate' in name_str or 'gate' in cid_str or 'anpr' in name_str)
        self.last_detected_plate = None
        self.last_gate_pass_id = None
        self.last_gate_pass_time = 0
        self.last_plate_prob = 0.0
        self.anpr_in_flight = False
        self.last_anpr_run_time = 0.0

        # Millisecond Real-Time Tracking & Motion Metrics
        self.inference_latency_ms = 0.0
        self.fps = 0.0
        self.track_trajectories = {}    # { track_id: [(x, y), ...] }
        self.track_motion_vectors = {}  # { track_id: (dx, dy) }
        self.track_last_seen = {}       # { track_id: frame_index }
        self.active_workers_count = 0
        self.active_stocks_count = 0

        # Smooth Directional Live Counting (Addition & Subtraction in Milliseconds)
        self.inbound_count = 0          # Inward crossing (+1 Stock In)
        self.outbound_count = 0         # Outward crossing (-1 Stock Out)
        self.net_stock_count = 0        # Inbound - Outbound
        self.counted_track_states = {}  # { track_id: 'IN' | 'OUT' }
        self.flash_counters = []        # Transient visual indicators for additions/subtractions
        
        # Thread-safe frame passing
        self.raw_frame = None
        self.latest_boxes = []
        self.lock = threading.Lock()

        if not hasattr(SmartCamera, 'vehicle_model') or SmartCamera.vehicle_model is None:
            try:
                from model_loader import get_shared_detector, DEFAULT_VERIFIED_MODEL
                model, active_name, err = get_shared_detector(
                    requested_model="yolo11s.pt",
                    fallback_model=DEFAULT_VERIFIED_MODEL,
                    allow_fallback=True
                )
                SmartCamera.vehicle_model = model
                SmartCamera.active_model_name = active_name or DEFAULT_VERIFIED_MODEL
                if err:
                    print(f"[SmartCamera] Model loader notice: {err}")
                else:
                    print(f"[SmartCamera] Successfully loaded detector '{SmartCamera.active_model_name}'!")
            except Exception as e_load:
                print(f"[SmartCamera] Model loading error: {e_load}")
                SmartCamera.vehicle_model = None
                SmartCamera.active_model_name = "None"

            if os.environ.get("WARLOG_TEST_MODE") == "1":
                SmartCamera.ocr_reader = None
            else:
                try:
                    from vision_runtime_service import get_gate_ocr_reader
                    SmartCamera.ocr_reader = get_gate_ocr_reader()
                except Exception as e_ocr:
                    print(f"Warning: EasyOCR failed to initialize: {e_ocr}")
                    SmartCamera.ocr_reader = None

    def toggle_freeze(self):
        with self.lock:
            self.is_frozen = not self.is_frozen
            return self.is_frozen

    def start(self):
        self.is_running = True
        
        # Thread 1: ONLY captures video from network/local device if not client-pushed
        if self.cam_type != "Device Camera":
            self.capture_thread = threading.Thread(target=self._capture_loop)
            self.capture_thread.daemon = True
            self.capture_thread.start()
        
        # Thread 2: ONLY runs AI in the background, doesn't block video
        self.ai_thread = threading.Thread(target=self._ai_loop)
        self.ai_thread.daemon = True
        self.ai_thread.start()

    def push_frame(self, frame):
        """Thread-safe injection of client frames (e.g. from laptop/phone device cameras)."""
        if frame is not None:
            if frame.shape[1] != 640 or frame.shape[0] != 480:
                frame = cv2.resize(frame, (640, 480))
            with self.lock:
                self.raw_frame = frame
            # Part 6: Publish to SharedFrameBus
            try:
                from vision_runtime_service import get_shared_frame_bus
                get_shared_frame_bus().publish_frame(self.camera_id, frame, source_type="PUSH_DEVICE")
            except Exception:
                pass

    def refresh_tripwire(self):
        """Forces immediate refresh of active tripwire configuration from database."""
        try:
            self.active_tripwire = get_camera_tripwire(self.camera_id, 640, 480)
            self.last_tripwire_check = time.time()
        except Exception as e:
            print(f"[{self.camera_id}] Error refreshing tripwire: {e}")

    def stop(self):
        self.is_running = False
        try:
            from vision_runtime_service import get_shared_frame_bus
            get_shared_frame_bus().mark_disconnected(self.camera_id, reason="Camera stopped")
        except Exception:
            pass

    def _capture_loop(self):
        # Support static image paths (for instant demo/testing)
        cap_source = self.url
        clean_src = str(cap_source).strip().strip('"').strip("'")
        resolved_path = clean_src
        if not os.path.isabs(resolved_path) and not clean_src.isdigit() and not clean_src.startswith(('http:', 'https:', 'rtsp:', 'device:')):
            for c in [os.path.abspath(clean_src), os.path.join(os.path.dirname(__file__), clean_src), os.path.join(os.path.dirname(os.path.dirname(__file__)), clean_src)]:
                if os.path.isfile(c):
                    resolved_path = c
                    break
        if os.path.isfile(resolved_path) and resolved_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')):
            img = cv2.imread(resolved_path)
            if img is not None:
                img_resized = cv2.resize(img, (640, 480))
                while self.is_running:
                    with self.lock:
                        self.raw_frame = img_resized
                    try:
                        from vision_runtime_service import get_shared_frame_bus
                        get_shared_frame_bus().publish_frame(self.camera_id, img_resized, source_type="CAMERA_JUNCTION_CAPTURE")
                    except Exception:
                        pass
                    time.sleep(0.05)
                return

        if not cap_source or str(cap_source).strip() in ("", "None") or str(cap_source).lower().startswith("device:"):
            while self.is_running:
                time.sleep(1.0)
            return

        # Support integer source for USB webcams (e.g. "0")
        is_usb = False
        if isinstance(cap_source, str) and cap_source.strip().isdigit():
            cap_source = int(cap_source.strip())
            is_usb = True
        elif isinstance(cap_source, str) and (cap_source.startswith("rtsp://") or cap_source.startswith("http://")):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;2000000"
            
        if is_usb and os.name == 'nt':
            # Try configured index first, fallback to 0 or 1
            cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                alt_idx = 0 if cap_source != 0 else 1
                cap = cv2.VideoCapture(alt_idx, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(0)
        else:
            final_src = cap_source
            if isinstance(final_src, str) and (final_src.startswith("rtsp://") or final_src.startswith("http://")):
                # Safely escape '#' in password to prevent URI fragment truncation without tripping OpenCV image pattern parser
                if '#' in final_src and '@' in final_src:
                    proto, rest = final_src.split('://', 1)
                    creds, host_path = rest.split('@', 1)
                    if ':' in creds:
                        user, pw = creds.split(':', 1)
                        # Replace # with %23
                        creds = f"{user}:{pw.replace('#', '%23')}"
                        final_src = f"{proto}://{creds}@{host_path}"
                cap = cv2.VideoCapture(final_src, cv2.CAP_FFMPEG)
            else:
                cap = cv2.VideoCapture(final_src)
            
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Reduce video lag by minimizing buffer
        while self.is_running:
            read_res = cap.read()
            if not isinstance(read_res, tuple) or len(read_res) != 2:
                time.sleep(0.5)
                continue
            ret, frame = read_res
            if not ret or frame is None:
                # If reading a video file, loop back to start
                if isinstance(cap_source, str) and os.path.isfile(clean_src):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    time.sleep(0.05)
                    continue
                time.sleep(1)
                if is_usb and os.name == 'nt':
                    cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        cap.release()
                        alt_idx = 0 if cap_source != 0 else 1
                        cap = cv2.VideoCapture(alt_idx, cv2.CAP_DSHOW)
                        if not cap.isOpened():
                            cap.release()
                            cap = cv2.VideoCapture(0)
                else:
                    cap = cv2.VideoCapture(cap_source)
                continue
            
            frame = cv2.resize(frame, (640, 480))
            
            # Save the latest raw frame safely
            with self.lock:
                self.raw_frame = frame

            # Part 6: Publish to SharedFrameBus
            try:
                from vision_runtime_service import get_shared_frame_bus
                get_shared_frame_bus().publish_frame(self.camera_id, frame, source_type="CAMERA_JUNCTION_CAPTURE")
            except Exception:
                pass
        cap.release()

    def _run_live_gate_anpr_worker(self, frame, vehicle_boxes):
        """Dedicated high-precision ANPR worker running on the LIVE feed.
        Extracts real license plates and auto-creates connected Gate Passes in DB."""
        try:
            import re, db
            fh, fw = frame.shape[:2]
            if fh < 80 or fw < 80:
                return

            candidate_crops = []
            v_type_candidate = "Heavy Commercial (HCV)"

            # 1. Inspect vehicle crops if detected by YOLO
            for vb in vehicle_boxes:
                x1, y1, x2, y2 = vb['x1'], vb['y1'], vb['x2'], vb['y2']
                vw = max(1, x2 - x1)
                vh = max(1, y2 - y1)
                if 'Light Vehicle' in vb.get('type', ''):
                    v_type_candidate = "Light Vehicle (LMV)"

                # Plate is typically mounted on lower 60% of the vehicle
                py1 = max(0, int(y1 + vh * 0.35))
                py2 = min(fh, y2)
                px1 = max(0, x1)
                px2 = min(fw, x2)
                v_crop = frame[py1:py2, px1:px2]
                if v_crop.size > 0:
                    candidate_crops.append(v_crop)

            # 2. Always inspect central frame (for close-up license plates, phones, printed test cards)
            center_crop = frame[int(fh * 0.10):int(fh * 0.90), int(fw * 0.10):int(fw * 0.90)]
            if center_crop.size > 0:
                candidate_crops.append(center_crop)

            # 3. Full frame fallback
            candidate_crops.append(frame)

            best_plate: str = ""
            best_prob: float = 0.0

            if hasattr(SmartCamera, 'ocr_reader') and SmartCamera.ocr_reader is not None:
                for crop in candidate_crops:
                    if best_plate != "":
                        break
                    ch, cw = crop.shape[:2]
                    if ch < 30 or cw < 60:
                        continue

                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    try:
                        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                        enhanced = clahe.apply(gray)
                    except Exception:
                        enhanced = gray

                    scale = 2.0 if max(ch, cw) < 350 else 1.2
                    resized = cv2.resize(enhanced, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                    filtered = cv2.bilateralFilter(resized, 7, 50, 50)

                    try:
                        ocr_res = SmartCamera.ocr_reader.readtext(filtered)
                    except Exception:
                        ocr_res = []

                    clean_tokens = []
                    for (_, text, prob) in ocr_res:
                        clean_text = "".join(c for c in text if c.isalnum()).upper()
                        if len(clean_text) >= 2 and prob > 0.15:
                            clean_tokens.append(clean_text)

                        # Match strict Indian license plate regex on token
                        m = re.search(r'[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{3,4}', clean_text)
                        if m and prob > 0.20:
                            if prob > best_prob:
                                best_plate = m.group(0)
                                best_prob = float(prob)
                        elif 4 <= len(clean_text) <= 12 and prob > 0.35:
                            has_num = any(c.isdigit() for c in clean_text)
                            has_alpha = any(c.isalpha() for c in clean_text)
                            if has_num and has_alpha and prob > best_prob:
                                best_plate = clean_text
                                best_prob = float(prob)

                    # Multi-line token recombination (e.g. ['MH', '12', 'PQ', '9988'] -> 'MH12PQ9988')
                    if not best_plate and clean_tokens:
                        combined = "".join(clean_tokens)
                        m = re.search(r'[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{3,4}', combined)
                        if m:
                            best_plate = m.group(0)
                            best_prob = 0.85
                        elif 5 <= len(combined) <= 12 and any(c.isdigit() for c in combined) and any(c.isalpha() for c in combined):
                            best_plate = combined
                            best_prob = 0.75

            # Standardize Indian format with hyphens (e.g. MH12PQ9988 -> MH-12-PQ-9988)
            if best_plate != "":
                m_ind = re.match(r'^([A-Z]{2})([0-9]{1,2})([A-Z]{1,3})([0-9]{3,4})$', best_plate)
                if m_ind:
                    best_plate = f"{m_ind.group(1)}-{m_ind.group(2)}-{m_ind.group(3)}-{m_ind.group(4)}"
                else:
                    m_short = re.match(r'^([A-Z]{2})([0-9]{2})([0-9]{4})$', best_plate)
                    if m_short:
                        best_plate = f"{m_short.group(1)}-{m_short.group(2)}-{m_short.group(3)}"

            # If a plate was detected from the live feed:
            if best_plate != "":
                now_t = time.time()
                # Deduplication: only issue a new pass if plate is different or > 45s since last pass
                if best_plate != self.last_detected_plate or (now_t - self.last_gate_pass_time) > 45.0:
                    existing_gp = db.get_pending_gate_pass_by_plate(best_plate)
                    if existing_gp:
                        gp_id = existing_gp.get('id', 'GP-PENDING')
                        print(f"[GATE ANPR LIVE] Linking active Gate Pass {gp_id} for live plate: {best_plate}")
                    else:
                        new_gp = db.create_gate_pass({
                            "plate": best_plate,
                            "type": v_type_candidate,
                            "activity": "Unloading",
                            "status": "Pending",
                            "driver_name": "Verified Driver",
                            "dock": "Dock 1"
                        })
                        gp_id = new_gp.get('id', 'GP-AUTO')
                        db.create_vehicle_log(gp_id, best_plate, "Verified Driver")
                        print(f"[GATE ANPR AUTO-PASS] Created Gate Pass {gp_id} from LIVE feed plate: {best_plate}")

                    with self.lock:
                        self.last_gate_pass_id = gp_id
                        self.last_detected_plate = best_plate
                        self.last_gate_pass_time = now_t
                        self.last_plate_prob = best_prob
                        
                        event = {
                            "time": time.strftime("%H:%M:%S"),
                            "type": v_type_candidate,
                            "plate": best_plate,
                            "gate_pass_id": gp_id,
                            "status": "GATE PASS ISSUED (LIVE FEED)",
                            "camera": self.name
                        }
                        self.events.insert(0, event)
            else:
                # No plate detected in frame
                now_t = time.time()
                if (now_t - self.last_gate_pass_time) > 12.0:
                    with self.lock:
                        self.last_detected_plate = None
                        self.last_gate_pass_id = None
        except Exception as e:
            print(f"[GATE ANPR WORKER ERROR]: {e}")
        finally:
            self.anpr_in_flight = False

    def _run_cross_section_counter(self, ai_frame: np.ndarray):
        """Universal Industrial Cross-Section & Piece Counter (Zero-Dataset Concept)
        Runs on demand in Freeze / Review mode without running YOLO."""
        detected_heads = []
        cluster_breakdown = {}
        palette_bgr = [
            (220, 20, 220), # Purple
            (255, 144, 30), # Blue
            (50, 205, 50),  # Green
            (0, 140, 255)   # Orange
        ]
        cluster_names = ['Top Layer', 'Left Bundle', 'Centre Bundle', 'Right Bundle']

        try:
            gray_f = cv2.cvtColor(ai_frame, cv2.COLOR_BGR2GRAY)
            filtered = cv2.bilateralFilter(gray_f, 7, 45, 45)

            th_dark = cv2.adaptiveThreshold(filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 23, 4)
            th_bright = cv2.adaptiveThreshold(filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 23, 4)

            kernel3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            best_points = []
            current_med_diam = 16.0

            for th_mask in [th_dark, th_bright]:
                clean_mask = cv2.morphologyEx(th_mask, cv2.MORPH_OPEN, kernel3)
                num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(clean_mask, connectivity=8)

                cands = []
                for i in range(1, num_labels):
                    area = stats[i, cv2.CC_STAT_AREA]
                    cw = stats[i, cv2.CC_STAT_WIDTH]
                    ch = stats[i, cv2.CC_STAT_HEIGHT]
                    aspect = float(cw) / ch if ch > 0 else 0
                    if 18 < area < 2500 and 0.4 < aspect < 2.5:
                        cands.append((centroids[i][0], centroids[i][1], max(cw, ch)))

                if len(cands) >= 8:
                    diams = [c[2] for c in cands]
                    med_diam = float(np.median(diams))
                    valid_c = [c for c in cands if 0.5 * med_diam <= c[2] <= 2.0 * med_diam]

                    if len(valid_c) >= 8:
                        pts_arr = np.array([[c[0], c[1]] for c in valid_c])
                        tree = cKDTree(pts_arr)
                        dense_items = [c for c in valid_c if len(tree.query_ball_point([c[0], c[1]], r=med_diam * 3.0)) >= 3]

                        if len(dense_items) >= 8:
                            tree_d = cKDTree(np.array([[c[0], c[1]] for c in dense_items]))
                            used_d = set()
                            final_pts = []
                            merge_r = max(8.0, med_diam * 0.75)
                            for idx, c in enumerate(dense_items):
                                if idx in used_d:
                                    continue
                                for n in tree_d.query_ball_point([c[0], c[1]], r=merge_r):
                                    used_d.add(n)
                                final_pts.append((int(c[0]), int(c[1])))

                            if len(final_pts) >= 8:
                                hull = cv2.convexHull(np.array(final_pts, dtype=np.int32))
                                h_area = cv2.contourArea(hull)
                                density = len(final_pts) / (h_area / 1000.0) if h_area > 0 else 0

                                if density >= 0.50 and len(final_pts) > len(best_points):
                                    best_points = final_pts
                                    current_med_diam = med_diam

            if len(best_points) >= 6:
                matched_ids = set()
                match_dist = max(14.0, current_med_diam * 0.75)

                for pt in best_points:
                    px, py = pt
                    best_tid, best_d = None, float('inf')
                    for tid, tdata in self.tracker_items.items():
                        if tid in matched_ids:
                            continue
                        d = np.hypot(px - tdata['x'], py - tdata['y'])
                        if d < match_dist and d < best_d:
                            best_tid, best_d = tid, d
                    if best_tid is not None:
                        matched_ids.add(best_tid)
                        self.tracker_items[best_tid]['x'] = 0.85 * self.tracker_items[best_tid]['x'] + 0.15 * px
                        self.tracker_items[best_tid]['y'] = 0.85 * self.tracker_items[best_tid]['y'] + 0.15 * py
                        self.tracker_items[best_tid]['hits'] += 1
                        self.tracker_items[best_tid]['missed'] = 0
                    else:
                        self.tracker_items[self.next_pin_id] = {
                            'x': float(px),
                            'y': float(py),
                            'hits': 1,
                            'missed': 0
                        }
                        self.next_pin_id += 1

                to_remove = []
                for tid, tdata in self.tracker_items.items():
                    if tid not in matched_ids:
                        tdata['missed'] += 1
                        if tdata['missed'] > 6:
                            to_remove.append(tid)
                for tid in to_remove:
                    del self.tracker_items[tid]

            stable_pins = [
                (tid, tdata['x'], tdata['y'])
                for tid, tdata in self.tracker_items.items()
                if tdata['hits'] >= 2 and tdata['missed'] <= 2
            ]
            if len(stable_pins) < 4:
                stable_pins = [
                    (tid, tdata['x'], tdata['y'])
                    for tid, tdata in self.tracker_items.items()
                    if tdata['missed'] <= 1
                ]

            if len(stable_pins) >= 4:
                coords = np.array([[p[1], p[2]] for p in stable_pins])
                k_clusters = min(4, max(1, len(stable_pins) // 25))
                Z = linkage(coords, method='ward')
                c_labels = fcluster(Z, t=k_clusters, criterion='maxclust')

                sorted_order = sorted(range(len(stable_pins)), key=lambda i: (stable_pins[i][2], stable_pins[i][1]))
                c_counts = {ci: 0 for ci in range(1, k_clusters + 1)}
                pins = []
                for seq, idx in enumerate(sorted_order, 1):
                    tid, px, py = stable_pins[idx]
                    c_id = int(c_labels[idx])
                    c_counts[c_id] += 1
                    pins.append({
                        'id': tid,
                        'x': int(round(px)),
                        'y': int(round(py)),
                        'seq': seq,
                        'cluster_id': c_id,
                        'color': palette_bgr[(c_id - 1) % len(palette_bgr)]
                    })

                detected_heads = pins
                for ci in range(1, k_clusters + 1):
                    c_name = cluster_names[ci - 1] if ci - 1 < len(cluster_names) else f'Bundle {ci}'
                    cluster_breakdown[c_name] = c_counts[ci]

            with self.lock:
                self.detected_heads = detected_heads
                self.cluster_breakdown = cluster_breakdown
                self.head_count = len(detected_heads)
                if detected_heads:
                    self.clustered_bundle_count = len(detected_heads)
        except Exception:
            pass

    def _ai_loop(self):
        """Authoritative Perception Synchronization Loop.
        Delegates detection, tracking, ANPR, and tripwire counting to VisionRuntimeManager.
        Eliminates duplicate YOLO inference loops while keeping SmartCamera synchronized."""
        try:
            from vision_runtime_service import get_vision_runtime_manager
            mgr = get_vision_runtime_manager()
        except Exception:
            mgr = None

        sess = None
        if mgr:
            sess = mgr.get_session(self.camera_id)
            if not sess:
                sess = mgr.get_or_create_session(
                    camera_id=self.camera_id,
                    name=self.name,
                    location=self.location,
                    stream_url=self.url or "",
                    configured_fps=10,
                    test_mode=(os.environ.get("WARLOG_TEST_MODE") == "1" or not bool(self.url))
                )
            if sess and not sess.is_running and self.is_running:
                sess.start()

        while self.is_running:
            if mgr and not sess:
                sess = mgr.get_session(self.camera_id)
                if sess and not sess.is_running:
                    sess.start()

            if sess:
                state = sess.get_perception_state()
                with self.lock:
                    self.latest_boxes = state.get("latest_boxes", [])
                    self.visible_boxes = state.get("visible_boxes", 0)
                    self.visible_packages = state.get("visible_packages", 0)
                    self.active_workers_count = state.get("active_workers_count", 0)
                    self.active_stocks_count = state.get("active_stocks_count", 0)
                    self.inbound_count = state.get("inbound_count", 0)
                    self.outbound_count = state.get("outbound_count", 0)
                    self.net_stock_count = state.get("net_stock_count", 0)
                    self.flash_counters = state.get("flash_counters", [])
                    self.track_trajectories = state.get("track_trajectories", {})
                    self.track_motion_vectors = state.get("track_motion_vectors", {})
                    self.last_detected_plate = state.get("last_detected_plate")
                    self.last_gate_pass_id = state.get("last_gate_pass_id")
                    self.events = state.get("events", [])
                    self.inference_latency_ms = state.get("inference_latency_ms", 0.0)
                    self.fps = state.get("fps", 0.0)

            # Universal Industrial Cross-Section & Piece Counter (Zero-Dataset Concept)
            # Active in Freeze review mode without running YOLO
            if self.is_frozen and self.raw_frame is not None:
                self._run_cross_section_counter(self.raw_frame)

            time.sleep(0.02)

    def get_frame(self):
        with self.lock:
            if self.is_frozen and self.frozen_jpeg is not None:
                return self.frozen_jpeg

        # 1. Authoritative canonical VisionRuntimeSession annotated frame
        try:
            from vision_runtime_service import get_vision_runtime_manager
            sess = get_vision_runtime_manager().get_session(self.camera_id)
            if sess and sess.latest_annotated_jpeg:
                return sess.latest_annotated_jpeg
        except Exception:
            pass

        # 2. Fallback local rendering with synchronized state
        with self.lock:
            if self.raw_frame is None:
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Awaiting Camera Feed...", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
                ret, buf = cv2.imencode('.jpg', placeholder)
                return buf.tobytes() if ret else None
            display_frame = self.raw_frame.copy()
            boxes_to_draw = copy.deepcopy(self.latest_boxes)
            trajectories = copy.deepcopy(self.track_trajectories)
            motion_vectors = copy.deepcopy(self.track_motion_vectors)
            flash_counters = copy.deepcopy(self.flash_counters)
            is_frozen = self.is_frozen
            is_gate = self.is_gate_camera
            last_plate = self.last_detected_plate
            last_gp = self.last_gate_pass_id
            inbound = self.inbound_count
            outbound = self.outbound_count
            net_stock = self.net_stock_count
            workers = self.active_workers_count
            latency_ms = self.inference_latency_ms

        # =========================================================================
        # 1. GATE CAMERA DISPLAY: ANPR & Vehicle Access Control (ZERO Counting HUD)
        # =========================================================================
        if is_gate:
            # Top Banner
            cv2.rectangle(display_frame, (0, 0), (640, 36), (20, 24, 32), -1)
            cv2.putText(display_frame, "GATE 01 | ANPR & VEHICLE ACCESS CONTROL | ZERO COUNTING", (14, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 255), 2)
            cv2.putText(display_frame, f"{latency_ms}ms", (570, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 128), 1)

            # Draw vehicle bounding boxes
            for box in boxes_to_draw:
                x1, y1, x2, y2 = box['x1'], box['y1'], box['x2'], box['y2']
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 128), 2)
                cv2.putText(display_frame, box['type'], (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 128), 2)

            # Prominent License Plate & Gate Pass Card (Bottom Left)
            card_x, card_y = 14, 375
            cv2.rectangle(display_frame, (card_x, card_y), (card_x + 360, card_y + 90), (15, 18, 24), -1)
            cv2.rectangle(display_frame, (card_x, card_y), (card_x + 360, card_y + 90), (0, 220, 255), 1)

            if last_plate:
                # Realistic License Plate Badge
                cv2.rectangle(display_frame, (card_x + 10, card_y + 10), (card_x + 235, card_y + 44), (245, 230, 60), -1)
                cv2.rectangle(display_frame, (card_x + 10, card_y + 10), (card_x + 235, card_y + 44), (10, 10, 10), 2)
                # IND blue strip
                cv2.rectangle(display_frame, (card_x + 10, card_y + 10), (card_x + 36, card_y + 44), (180, 50, 0), -1)
                cv2.putText(display_frame, "IND", (card_x + 12, card_y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)
                # Plate number
                cv2.putText(display_frame, last_plate, (card_x + 42, card_y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (10, 10, 10), 2)

                # Gate pass status
                pass_text = f"GATE PASS: {last_gp or 'GENERATING...'}"
                cv2.putText(display_frame, pass_text, (card_x + 10, card_y + 64), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 128), 2)
                cv2.putText(display_frame, "STATUS: LIVE ARRIVAL (PASS CREATED)", (card_x + 10, card_y + 82), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
            else:
                cv2.putText(display_frame, "LIVE ANPR ACTIVE", (card_x + 12, card_y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (0, 220, 255), 2)
                cv2.putText(display_frame, "Monitoring Live Feed for Incoming Vehicle/Plate", (card_x + 12, card_y + 54), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)
                cv2.putText(display_frame, "Gate pass will auto-generate upon plate detection", (card_x + 12, card_y + 74), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (140, 140, 140), 1)
                
                # Dynamic visual scanning laser across the card
                scan_offset = int((time.time() * 120) % 330)
                cv2.line(display_frame, (card_x + 10 + scan_offset, card_y + 6), (card_x + 10 + scan_offset, card_y + 84), (0, 220, 255), 1)

            ret, buffer = cv2.imencode('.jpg', display_frame)
            jpeg_bytes = buffer.tobytes()
            with self.lock:
                self.frozen_jpeg = jpeg_bytes
            return jpeg_bytes

        # =========================================================================
        # 2. WAREHOUSE CAMERA DISPLAY: LIVE Multi-Object Tracking & Millisecond Counting
        # =========================================================================
        # Draw Database-Configured Directional Tripwire Line (if configured and enabled)
        if self.active_tripwire and self.active_tripwire.get('is_enabled'):
            p1 = self.active_tripwire['p1']
            p2 = self.active_tripwire['p2']
            dir_mode = self.active_tripwire.get('crossing_direction', 'BOTH')
            cv2.line(display_frame, p1, p2, (0, 220, 255), 2)
            cv2.circle(display_frame, p1, 4, (0, 255, 255), -1)
            cv2.circle(display_frame, p2, 4, (0, 255, 255), -1)

            mid_x = int((p1[0] + p2[0]) / 2)
            mid_y = int((p1[1] + p2[1]) / 2)
            z_label = self.active_tripwire.get('zone_code', 'TRIPWIRE')
            if dir_mode == 'BOTH':
                cv2.putText(display_frame, f"[{z_label}] IN (+1) >>>", (max(10, mid_x - 120), max(20, mid_y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 128), 1)
                cv2.putText(display_frame, f"<<< OUT (-1)", (min(display_frame.shape[1] - 140, mid_x + 10), min(display_frame.shape[0] - 10, mid_y + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 140, 255), 1)
            elif dir_mode == 'INBOUND_ONLY':
                cv2.putText(display_frame, f"[{z_label}] IN (+1) >>>", (max(10, mid_x - 80), max(20, mid_y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 128), 1)
            elif dir_mode == 'OUTBOUND_ONLY':
                cv2.putText(display_frame, f"[{z_label}] <<< OUT (-1)", (max(10, mid_x - 80), min(display_frame.shape[0] - 10, mid_y + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 140, 255), 1)

        # Draw Live Motion Trails (Trajectories)
        for tid, points in trajectories.items():
            if len(points) >= 2:
                vec = motion_vectors.get(tid, (0, 0))
                speed = (vec[0]**2 + vec[1]**2)**0.5
                trail_color = (0, 255, 128) if speed > 1.5 else (0, 180, 255)
                for p_idx in range(1, len(points)):
                    p1 = points[p_idx - 1]
                    p2 = points[p_idx]
                    thickness = max(1, int(p_idx / 4))
                    cv2.line(display_frame, p1, p2, trail_color, thickness)

        # Draw Detected Objects (Workers in Cyan, Stocks in Emerald Green)
        for box in boxes_to_draw:
            x1, y1, x2, y2 = box['x1'], box['y1'], box['x2'], box['y2']
            is_person = box.get('is_person', False)
            color = (255, 200, 0) if is_person else (0, 255, 128) # Cyan for person, Emerald for stock

            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_frame, box['type'], (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # Centroid point & motion vector arrow
            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
            cv2.circle(display_frame, (cx, cy), 3, (255, 255, 255), -1)

            tid = box.get('track_id')
            if tid in motion_vectors:
                mv_x, mv_y = motion_vectors[tid]
                if abs(mv_x) > 1 or abs(mv_y) > 1:
                    arrow_end = (cx + int(mv_x * 2.5), cy + int(mv_y * 2.5))
                    cv2.arrowedLine(display_frame, (cx, cy), arrow_end, color, 2, tipLength=0.35)

        # Draw Floating Flash Indicators for Additions & Subtractions
        for fc in flash_counters:
            f_text = fc.get('text', '')
            fx, fy = fc.get('pos', (320, 240))
            f_col = fc.get('color', (0, 255, 128))
            cv2.putText(display_frame, f_text, (max(10, fx - 50), max(25, fy - 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 3)
            cv2.putText(display_frame, f_text, (max(10, fx - 50), max(25, fy - 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, f_col, 2)

        # High-tech Warehouse Top HUD Banner
        cam_tag = self.name or self.camera_id
        freeze_tag = " [FROZEN]" if is_frozen else ""
        hud_text = f"[{cam_tag}] LIVE ({latency_ms}ms) | IN: +{inbound} | OUT: -{outbound} | NET STOCK: {net_stock} | WORKERS: {workers}{freeze_tag}"

        cv2.rectangle(display_frame, (0, 0), (640, 32), (18, 22, 28), -1)
        cv2.putText(display_frame, hud_text, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 200), 2)

        ret, buffer = cv2.imencode('.jpg', display_frame)
        jpeg_bytes = buffer.tobytes()
        with self.lock:
            self.frozen_jpeg = jpeg_bytes
        return jpeg_bytes
