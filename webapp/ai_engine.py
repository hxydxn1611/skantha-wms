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
        self.tripwire_y = 240  # Legacy attribute preserved for compatibility
        self.tracked_centroids = {}
        
        # Thread-safe frame passing
        self.raw_frame = None
        self.latest_boxes = []
        self.lock = threading.Lock()

        if not hasattr(SmartCamera, 'vehicle_model'):
            print("Loading YOLOv8 (Attempting YOLO-World for Zero-Shot)...")
            try:
                SmartCamera.vehicle_model = YOLO('yolov8s-world.pt')
                SmartCamera.vehicle_model.set_classes([
                    "box", "bundle", "pallet", "car part", "engine block", 
                    "windshield", "bumper", "screw box", "steering wheel", 
                    "tire bundle", "hood", "truck", "forklift", "person", "license plate"
                ])
            except Exception as e:
                print("Falling back to yolov8n.pt due to error:", e)
                SmartCamera.vehicle_model = YOLO('yolov8n.pt')
            if os.environ.get("WARLOG_TEST_MODE") == "1":
                SmartCamera.ocr_reader = None
            else:
                print("Loading EasyOCR...")
                SmartCamera.ocr_reader = easyocr.Reader(['en'], gpu=False)

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

        # Support integer source for USB webcams (e.g. "0")
        is_usb = False
        if isinstance(cap_source, str) and cap_source.strip().isdigit():
            cap_source = int(cap_source.strip())
            is_usb = True
        elif isinstance(cap_source, str) and (cap_source.startswith("rtsp://") or cap_source.startswith("http://")):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;2000000"
            
        if is_usb and os.name == 'nt':
            # Attempt to grab the external USB webcam (index 1) first
            cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(cap_source)
            
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
                    cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        cap.release()
                        cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW)
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

    def _ai_loop(self):
        ocr_counter = 0
        self.tripwire_y = 240 # Middle of the 480p frame
        self.tracked_centroids = {}
        self.active_audits = {} # { track_id: (x, y) }
        
        while self.is_running:
            with self.lock:
                if self.raw_frame is None:
                    ai_frame = None
                else:
                    ai_frame = self.raw_frame.copy()
            
            if ai_frame is None:
                time.sleep(0.016)
                continue
            
            results = []
            if hasattr(SmartCamera, 'vehicle_model') and SmartCamera.vehicle_model is not None:
                try:
                    results = SmartCamera.vehicle_model.track(ai_frame, persist=True, conf=0.1, iou=0.4, verbose=False)
                except Exception:
                    try:
                        results = SmartCamera.vehicle_model(ai_frame, conf=0.1, iou=0.4, verbose=False)
                    except Exception:
                        results = []
                
            new_boxes = []
            box_count = 0
            car_part_count = 0
            
            for result in results:
                if result.boxes.id is not None:
                    track_ids = result.boxes.id.int().cpu().tolist()
                else:
                    track_ids = [None] * len(result.boxes)
                    
                for i, box in enumerate(result.boxes):
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    class_id = int(box.cls[0])
                    track_id = track_ids[i]
                    raw_type = SmartCamera.vehicle_model.names[class_id]
                    
                    if raw_type in ["bus", "truck"]:
                        vehicle_type = "Heavy Commercial (HCV)"
                    elif raw_type == "car":
                        vehicle_type = "Light Vehicle (LMV)"

                    # If it's a vehicle at the gate, try OCR occasionally
                    if self.location == 'Gate' and raw_type in ["bus", "truck", "car"]:
                        ocr_counter += 1
                        if ocr_counter % 15 == 0:
                            def run_ocr(frame, cam_id, cam_name, v_type, events):
                                try:
                                    id_svc = get_identity_service()
                                    res = id_svc.process_frame(frame, cam_id)
                                    for track in res.get('tracks', []):
                                        ident = track.get('identity', {})
                                        if ident.get('status') in ['IDENTIFIED', 'UNIDENTIFIED'] and ident.get('source') == 'OCR':
                                            plate_text = ident.get('value')
                                            if plate_text and len(plate_text) >= 4:
                                                if not any(e.get('plate') == plate_text for e in events):
                                                    event = {
                                                        "time": time.strftime("%H:%M:%S"),
                                                        "type": v_type,
                                                        "plate": plate_text,
                                                        "camera": cam_name
                                                    }
                                                    events.insert(0, event)
                                except Exception:
                                    pass
                            
                            threading.Thread(target=run_ocr, args=(ai_frame.copy(), self.camera_id, self.name, vehicle_type, self.events)).start()
                    elif raw_type == "person":
                        vehicle_type = "Worker"
                    elif raw_type in ["suitcase", "backpack", "handbag", "box", "carton", "bundle", "laptop", "book", "tv", "microwave", "oven", "refrigerator"]:
                        vehicle_type = "Box/Bundle"
                        box_count += 1
                    else:
                        vehicle_type = "Car Part"
                        car_part_count += 1
                        
                        # Part 5: Legacy tripwire / SmartCamera package counting is RETIRED.
                        # W.A.R.L.O.G. BOX_UNLOADED_AT_DOCK is the sole authoritative perception source.
                        # Centroids tracked only for visual preview if needed; no unload events or counters mutated.
                        if track_id is not None:
                            cx = int((x1 + x2) / 2)
                            cy = int((y1 + y2) / 2)
                            self.tracked_centroids[track_id] = (cx, cy)
                        
                    label = vehicle_type if track_id is None else f"{vehicle_type} #{track_id}"
                    new_boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "type": label, "is_package": vehicle_type in ["Car Part", "Box/Bundle"], "track_id": track_id})

            # Dynamic Spatial Clustering for Bundle / Pallet Piles
            package_boxes = [b for b in new_boxes if b.get('is_package')]
            clustered_count = 0
            pile_envelope = None
            
            if package_boxes:
                # Group packages by spatial proximity (overlapping or within 85px edge distance)
                n = len(package_boxes)
                adj = {idx: [] for idx in range(n)}
                for i in range(n):
                    b1 = package_boxes[i]
                    for j in range(i + 1, n):
                        b2 = package_boxes[j]
                        dx = max(0, max(b1['x1'], b2['x1']) - min(b1['x2'], b2['x2']))
                        dy = max(0, max(b1['y1'], b2['y1']) - min(b1['y2'], b2['y2']))
                        edge_dist = (dx**2 + dy**2)**0.5
                        if edge_dist <= 85: # Spatial adjacency threshold
                            adj[i].append(j)
                            adj[j].append(i)
                
                # Connected components
                visited = set()
                clusters = []
                for i in range(n):
                    if i not in visited:
                        comp = []
                        q = [i]
                        visited.add(i)
                        while q:
                            curr = q.pop(0)
                            comp.append(curr)
                            for nbr in adj[curr]:
                                if nbr not in visited:
                                    visited.add(nbr)
                                    q.append(nbr)
                        clusters.append([package_boxes[idx] for idx in comp])
                
                # Pick largest cluster as the primary pile
                clusters.sort(key=lambda c: len(c), reverse=True)
                primary_pile = clusters[0] if clusters else []
                clustered_count = len(primary_pile)
                
                # Mark pile membership on all boxes
                pile_ids = set(id(b) for b in primary_pile)
                for b in new_boxes:
                    b['in_pile'] = (id(b) in pile_ids)
                
                if primary_pile:
                    pile_envelope = {
                        'x1': max(0, min(b['x1'] for b in primary_pile)),
                        'y1': max(0, min(b['y1'] for b in primary_pile)),
                        'x2': min(640, max(b['x2'] for b in primary_pile)),
                        'y2': min(480, max(b['y2'] for b in primary_pile))
                    }
            else:
                for b in new_boxes:
                    b['in_pile'] = False

            # If camera is frozen in Review/Count mode, hold current frame and detections
            if self.is_frozen:
                time.sleep(0.04)
                continue

            # Universal Industrial Cross-Section & Piece Counter (Zero-Dataset Concept)
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
                                # NMS to merge overlapping multi-level hits
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
                                    # Stack Convex Hull Density Check:
                                    # Real warehouse stacks (pipes, tubes, bundles) have density >= 0.70 items / 1000px^2
                                    # Everyday rooms / tablecloths have density < 0.45 and get rejected
                                    hull = cv2.convexHull(np.array(final_pts, dtype=np.int32))
                                    h_area = cv2.contourArea(hull)
                                    density = len(final_pts) / (h_area / 1000.0) if h_area > 0 else 0

                                    if density >= 0.50 and len(final_pts) > len(best_points):
                                        best_points = final_pts
                                        current_med_diam = med_diam

                # Anti-Jitter Temporal Centroid Tracking (stops dots from jumping/running)
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
                            # Exponential Moving Average for smooth anchoring without jitter
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

                    # Increment missed for unmatched pins; prune only after 6 consecutive misses
                    to_remove = []
                    for tid, tdata in self.tracker_items.items():
                        if tid not in matched_ids:
                            tdata['missed'] += 1
                            if tdata['missed'] > 6:
                                to_remove.append(tid)
                    for tid in to_remove:
                        del self.tracker_items[tid]
                else:
                    # No stack in view: smoothly age out tracked pins
                    to_remove = []
                    for tid, tdata in self.tracker_items.items():
                        tdata['missed'] += 1
                        if tdata['missed'] > 3:
                            to_remove.append(tid)
                    for tid in to_remove:
                        del self.tracker_items[tid]

                # Stable confirmed pins (seen in >= 2 frames), or all active pins for instantaneous first frame
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
            except Exception:
                pass

            bar_layers = 0
            bar_peaks = []
            bar_bbox = None

            if detected_heads:
                clustered_count = len(detected_heads)
            elif bar_layers > 0:
                clustered_count = max(clustered_count, bar_layers)

            with self.lock:
                self.latest_boxes = new_boxes
                self.visible_boxes = box_count
                self.visible_car_parts = car_part_count
                self.visible_packages = box_count + car_part_count
                self.clustered_bundle_count = clustered_count
                self.primary_pile_envelope = pile_envelope
                self.detected_bar_layers = bar_layers
                self.bar_layer_peaks = bar_peaks
                self.bar_stack_bbox = bar_bbox
                self.detected_heads = detected_heads
                self.cluster_breakdown = cluster_breakdown
                self.head_count = len(detected_heads)

            time.sleep(0.016) # Faster loop for 60 FPS capabilities

    def get_frame(self):
        with self.lock:
            if self.is_frozen and self.frozen_jpeg is not None:
                return self.frozen_jpeg
            if self.raw_frame is None:
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Awaiting Camera Feed...", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
                ret, buf = cv2.imencode('.jpg', placeholder)
                return buf.tobytes() if ret else None
            display_frame = self.raw_frame.copy()
            boxes_to_draw = copy.deepcopy(self.latest_boxes)
            pile_envelope = copy.deepcopy(self.primary_pile_envelope)
            clustered_count = self.clustered_bundle_count
            bar_layers = self.detected_bar_layers
            bar_peaks = copy.deepcopy(self.bar_layer_peaks)
            bar_bbox = self.bar_stack_bbox
            detected_heads = copy.deepcopy(self.detected_heads)
            cluster_breakdown = copy.deepcopy(self.cluster_breakdown)
            is_frozen = self.is_frozen

        palette_bgr = [
            (220, 20, 220), # Purple
            (255, 144, 30), # Blue
            (50, 205, 50),  # Green
            (0, 140, 255)   # Orange
        ]

        # Priority 1: Reference-Grade Individual Head Pins & Summary Legend Card
        if detected_heads:
            # Draw individual pins
            for pin in detected_heads:
                px, py = pin['x'], pin['y']
                p_col = pin['color']
                cv2.circle(display_frame, (px, py), 5, (255, 255, 255), -1)
                cv2.circle(display_frame, (px, py), 4, p_col, -1)
                if len(detected_heads) <= 75:
                    cv2.putText(display_frame, str(pin['seq']), (px - 3, py + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.22, (255, 255, 255), 1)

            # Draw white HUD legend card in top-left matching reference image
            k_groups = len(cluster_breakdown)
            card_w, card_h = 165, 26 + (k_groups + 1) * 16
            cv2.rectangle(display_frame, (10, 38), (10 + card_w, 38 + card_h), (255, 255, 255), -1)
            cv2.rectangle(display_frame, (10, 38), (10 + card_w, 38 + card_h), (180, 180, 180), 1)

            y_pos = 54
            for ci, (b_name, b_count) in enumerate(cluster_breakdown.items()):
                b_col = palette_bgr[ci % len(palette_bgr)]
                cv2.circle(display_frame, (22, y_pos - 4), 4, b_col, -1)
                cv2.putText(display_frame, f"{b_name}: {b_count}", (32, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (20, 20, 20), 1)
                y_pos += 16
            cv2.putText(display_frame, f"TOTAL: {len(detected_heads)} pcs", (20, y_pos + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 200), 1)

        # Priority 2: Draw physical bar stack boundary and layer seams
        elif bar_bbox and bar_layers > 0:
            bsx, bsy, bsw, bsh = bar_bbox
            cv2.rectangle(display_frame, (bsx, bsy), (bsx + bsw, bsy + bsh), (0, 215, 255), 2)
            for i, py in enumerate(bar_peaks):
                cv2.line(display_frame, (bsx, py), (bsx + bsw, py), (0, 255, 200), 1)
                cv2.putText(display_frame, f"L{i+1}", (bsx + 6, py - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
            cv2.putText(display_frame, f"BAR STACK: {bar_layers} LAYERS", (bsx + 8, max(20, bsy - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 215, 255), 2)

        # Priority 3: Draw primary pile boundary envelope if detected
        elif pile_envelope and clustered_count > 0:
            px1, py1, px2, py2 = pile_envelope['x1'], pile_envelope['y1'], pile_envelope['x2'], pile_envelope['y2']
            cv2.rectangle(display_frame, (max(0, px1 - 6), max(0, py1 - 6)), (min(640, px2 + 6), min(480, py2 + 6)), (0, 255, 255), 2)
            cv2.putText(display_frame, f"PRIMARY PILE: {clustered_count} BUNDLES", (max(10, px1), max(25, py1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        if not detected_heads:
            for box in boxes_to_draw:
                if box.get('in_pile'):
                    color = (0, 230, 115) # Emerald green for primary pile
                elif box.get('is_package'):
                    color = (255, 140, 0) # Amber for stray/background packages
                else:
                    color = (200, 200, 200) # Gray/white for persons/other
                    
                x1, y1, x2, y2 = box['x1'], box['y1'], box['x2'], box['y2']
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(display_frame, box['type'], (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                
                # Draw centroid point
                if box.get('is_package'):
                    cx, cy = int((x1 + x2)/2), int((y1 + y2)/2)
                    cv2.circle(display_frame, (cx, cy), 3, (0, 255, 255), -1)

        # High-tech HUD banner at top of frame
        bin_label = f"BIN: {self.bin_id}" if self.bin_id else "BIN: UNASSIGNED"
        freeze_tag = " [FROZEN]" if is_frozen else ""
        if detected_heads:
            hud_text = f"{bin_label} | PILE: {len(detected_heads)} PCS ({len(cluster_breakdown)} GROUPS){freeze_tag}"
        elif bar_layers > 0:
            hud_text = f"{bin_label} | BARS: {bar_layers} LAYERS | PILE: {clustered_count} BUNDLES{freeze_tag}"
        else:
            hud_text = f"{bin_label} | PILE: {clustered_count} BUNDLES | TOTAL: {self.visible_packages}{freeze_tag}"
        cv2.rectangle(display_frame, (0, 0), (640, 32), (20, 20, 25), -1)
        hud_color = (0, 255, 200) if self.bin_id else (0, 220, 255)
        cv2.putText(display_frame, hud_text, (15, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, hud_color, 2)

        ret, buffer = cv2.imencode('.jpg', display_frame)
        jpeg_bytes = buffer.tobytes()
        with self.lock:
            self.frozen_jpeg = jpeg_bytes
        return jpeg_bytes
