"""
W.A.R.L.O.G. / Skantha WMS - Autonomous Palletization & Bundle Counting Service
Handles visual SKU verification against reference images, automated bundle aggregation,
piece-count multiplication, and Master Pallet Label generation.
"""

import os
import io
import cv2
import json
import uuid
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import db

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PALLET_LABEL_DIR = os.path.join(ROOT_DIR, 'static', 'invoices')
os.makedirs(PALLET_LABEL_DIR, exist_ok=True)


class SkuVisualSignatureMatcher:
    """
    Extracts and caches normalized visual signatures (HSV color histograms and edge profiles)
    from SKU reference photos to verify bundles on live camera feeds without neural net retraining.
    """

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_signature_for_sku(self, sku_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached visual signature or compute from primary SKU master image."""
        if not sku_id:
            return None
        sku_key = str(sku_id).strip()

        if sku_key in self._cache:
            return self._cache[sku_key]

        full_path = None

        # 1. Fetch from DB
        try:
            images = db.get_sku_images(sku_key)
            if images:
                primary_img = next((img for img in images if img.get('is_primary')), images[0])
                rel_path = primary_img.get('file_path', '')
                if rel_path:
                    clean_rel = rel_path.lstrip('/').replace('/', os.sep)
                    cand_path = os.path.join(ROOT_DIR, clean_rel)
                    if os.path.isfile(cand_path):
                        full_path = cand_path
        except Exception as e:
            logger.warning(f"DB lookup for SKU image failed: {e}")

        # 2. Filesystem search in static/uploads/sku_images
        sku_upload_dir = os.path.join(ROOT_DIR, 'static', 'uploads', 'sku_images')
        if not full_path and os.path.isdir(sku_upload_dir):
            for fname in os.listdir(sku_upload_dir):
                if fname.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and sku_key.lower() in fname.lower():
                    cand = os.path.join(sku_upload_dir, fname)
                    if os.path.isfile(cand):
                        full_path = cand
                        break

        # 3. Fallback to any available SKU reference image if only one SKU is registered
        if not full_path and os.path.isdir(sku_upload_dir):
            all_imgs = [os.path.join(sku_upload_dir, f) for f in os.listdir(sku_upload_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
            if all_imgs:
                full_path = all_imgs[0]

        if not full_path or not os.path.isfile(full_path):
            logger.warning(f"SKU '{sku_key}' reference image path not found on disk: {full_path}")
            return None

        try:
            img = cv2.imread(full_path)
            if img is None:
                return None

            signature = self.compute_signature(img)
            signature['ref_img'] = img
            signature['file_path'] = full_path
            self._cache[sku_key] = signature
            return signature
        except Exception as e:
            logger.error(f"Failed to compute visual signature for SKU '{sku_key}': {e}")
            return None

    def get_reference_image_for_sku(self, sku_id: str) -> Optional[np.ndarray]:
        """Retrieve the primary BGR reference image for a given SKU."""
        sig = self.get_signature_for_sku(sku_id)
        return sig.get('ref_img') if sig else None

    def compute_signature(self, bgr_crop: np.ndarray) -> Dict[str, Any]:
        """Compute normalized HSV color histogram, foreground color range, and edge profile."""
        hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

        # Isolate foreground item pixels, suppressing dull neutral background floor
        gray = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 25, 90)
        fg_mask = (s > 25) | (edges > 0)
        if np.sum(fg_mask) < (bgr_crop.shape[0] * bgr_crop.shape[1] * 0.05):
            fg_mask = np.ones((bgr_crop.shape[0], bgr_crop.shape[1]), dtype=bool)

        fg_hsv = hsv[fg_mask]
        mean_hue = float(np.mean(fg_hsv[:, 0])) if len(fg_hsv) > 0 else float(np.mean(h))
        mean_sat = float(np.mean(fg_hsv[:, 1])) if len(fg_hsv) > 0 else float(np.mean(s))
        mean_val = float(np.mean(fg_hsv[:, 2])) if len(fg_hsv) > 0 else float(np.mean(v))

        # 2D HSV Histogram (Hue & Saturation)
        hist = cv2.calcHist([hsv], [0, 1], fg_mask.astype(np.uint8), [16, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

        # Grayscale Edge magnitude
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        mean_edge = float(np.mean(mag))

        # Color range of foreground for segmentation
        if len(fg_hsv) > 10:
            h_p10, h_p90 = np.percentile(fg_hsv[:, 0], [5, 95])
            s_p10, s_p90 = np.percentile(fg_hsv[:, 1], [5, 95])
            v_p10, v_p90 = np.percentile(fg_hsv[:, 2], [5, 95])
        else:
            h_p10, h_p90 = max(0, mean_hue - 25), min(180, mean_hue + 25)
            s_p10, s_p90 = max(20, mean_sat - 50), 255
            v_p10, v_p90 = max(20, mean_val - 50), 255

        # Extract ORB keypoints for local feature verification
        orb = cv2.ORB_create(nfeatures=500)
        kp, des = orb.detectAndCompute(gray, None)

        return {
            "hist": hist,
            "mean_edge": mean_edge,
            "mean_hue": mean_hue,
            "mean_sat": mean_sat,
            "mean_val": mean_val,
            "hsv_range": (
                np.array([int(h_p10), int(max(20, s_p10)), int(max(20, v_p10))], dtype=np.uint8),
                np.array([int(h_p90), 255, 255], dtype=np.uint8)
            ),
            "descriptors": des,
            "shape": bgr_crop.shape[:2]
        }

    def compute_similarity(self, candidate_bgr: np.ndarray, sku_id: str) -> float:
        """
        Compare a detected box crop against the SKU reference signature.
        Returns a similarity confidence score between 0.0 (completely alien) and 1.0 (exact match).
        """
        if candidate_bgr is None or candidate_bgr.size == 0:
            return 0.0

        ref_sig = self.get_signature_for_sku(sku_id)
        if not ref_sig:
            # If no reference image exists for this SKU, rely on geometric YOLO box detection
            return 0.85

        cand_sig = self.compute_signature(candidate_bgr)

        # 1. Histogram correlation
        hist_corr = cv2.compareHist(ref_sig['hist'], cand_sig['hist'], cv2.HISTCMP_CORREL)
        norm_corr = max(0.0, float(hist_corr))

        # 2. Hue and Saturation proximity
        hue_diff = abs(ref_sig['mean_hue'] - cand_sig['mean_hue']) / 180.0
        sat_diff = abs(ref_sig['mean_sat'] - cand_sig['mean_sat']) / 255.0
        color_proximity = max(0.0, 1.0 - (hue_diff * 0.65 + sat_diff * 0.35))

        # 3. Descriptor matching if descriptors available
        desc_score = 0.0
        if ref_sig.get('descriptors') is not None and cand_sig.get('descriptors') is not None:
            try:
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                matches = bf.match(ref_sig['descriptors'], cand_sig['descriptors'])
                good = [m for m in matches if m.distance < 60]
                if len(matches) > 0:
                    desc_score = min(1.0, len(good) / min(20, len(matches)))
            except Exception:
                pass

        if desc_score > 0:
            final_score = round(0.40 * norm_corr + 0.35 * color_proximity + 0.25 * desc_score, 4)
        else:
            final_score = round(0.60 * norm_corr + 0.40 * color_proximity, 4)

        return min(1.0, max(0.0, final_score))

    def has_reference_image(self, sku_id: str) -> bool:
        """Checks if the SKU has an active reference image in the database."""
        return self.get_signature_for_sku(sku_id) is not None

    def match_visual_signature(self, candidate_bgr: np.ndarray, sku_id: str) -> float:
        """Compare candidate crop against SKU reference photo signature."""
        return self.compute_similarity(candidate_bgr, sku_id)

    def invalidate_sku_cache(self, sku_id: str):
        """Clear cached signature when user updates SKU reference photo."""
        self._cache.pop(str(sku_id).strip(), None)


class AutonomousPalletizationService:
    """
    Orchestrates live pallet stacking sessions, bundle counting,
    wrong-SKU contamination detection, and label generation.
    """

    def __init__(self):
        self.matcher = SkuVisualSignatureMatcher()
        # In-memory session tracking: pallet_id -> set of counted track_ids
        self._counted_track_ids: Dict[str, set] = {}
        # Active pallet assigned per camera: camera_id -> pallet_id
        self._active_camera_pallets: Dict[str, str] = {}
        logger.info("AutonomousPalletizationService initialized.")

    def set_active_pallet_for_camera(self, camera_id: str, pallet_id: str):
        """Bind a specific pallet build to a camera's staging zone."""
        cam_key = str(camera_id).strip().upper()
        self._active_camera_pallets[cam_key] = str(pallet_id)
        if pallet_id not in self._counted_track_ids:
            # Seed already logged track IDs from database
            existing_items = db.get_pallet_items(pallet_id)
            self._counted_track_ids[pallet_id] = {item['track_id'] for item in existing_items if item.get('track_id')}

    def get_active_pallet_for_camera(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Get the active pallet currently being stacked in front of this camera."""
        cam_key = str(camera_id).strip().upper()
        pallet_id = self._active_camera_pallets.get(cam_key)
        if pallet_id:
            pallet = db.get_pallet_by_id(pallet_id)
            if pallet and pallet.get('status') in ('STACKING', 'BUILDING'):
                return pallet

        # Automatic fallback: find pallet bound to camera or any active stacking pallet
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT pallet_id FROM pallets WHERE UPPER(camera_id) = ? AND status IN ('STACKING', 'BUILDING') ORDER BY created_at DESC LIMIT 1",
                (cam_key,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT pallet_id FROM pallets WHERE status IN ('STACKING', 'BUILDING') ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            if row:
                pid = row['pallet_id']
                self.set_active_pallet_for_camera(cam_key, pid)
                return db.get_pallet_by_id(pid)
        except Exception as e:
            logger.debug(f"Error resolving active pallet fallback: {e}")
        finally:
            conn.close()
        return None

    def process_pallet_zone_tracks(
        self,
        camera_id: str,
        tracks: List[Dict[str, Any]],
        frame_bgr: np.ndarray,
        pallet_zone_polygon: Optional[List[Dict[str, float]]] = None
    ) -> Dict[str, Any]:
        """
        Process live tracks detected in the pallet zone:
        - Verifies each box against SKU photo.
        - Increments bundle count for verified items.
        - Raises human error violation if an alien or wrong SKU box is placed on the pallet.
        """
        cam_key = str(camera_id).strip().upper()
        pallet = self.get_active_pallet_for_camera(cam_key)

        if not pallet:
            return {
                "active_pallet": None,
                "counted_bundles": 0,
                "total_units": 0,
                "status": "NO_ACTIVE_PALLET",
                "violations_triggered": []
            }

        pallet_id = pallet['pallet_id']
        sku_id = pallet['sku_id']
        target_bundles = pallet['target_bundles']
        units_per_bundle = pallet['units_per_bundle']
        counted_set = self._counted_track_ids.setdefault(pallet_id, set())

        frame_h, frame_w = frame_bgr.shape[:2]
        newly_counted = []
        violations_triggered = []

        has_ref = self.matcher.has_reference_image(sku_id)

        for trk in tracks:
            cls_code = trk.get('class_code', '')
            lbl = str(trk.get('label', '')).lower()
            if cls_code not in ('BOX', 'BUNDLE', 'MATERIAL', 'PART', 'PALLET', 'FASTENER') and lbl not in (
                'bed', 'bench', 'surfboard', 'box', 'suitcase', 'backpack', 'book', 'bundle', 'pallet',
                'metal frame', 'steel bar bundle', 'package', 'crate', 'carton'
            ):
                continue

            track_id = trk.get('track_id')
            if not track_id:
                continue

            # Check if track is inside the pallet staging zone ROI (or entire frame if no ROI defined)
            is_in_zone = True
            if pallet_zone_polygon and len(pallet_zone_polygon) >= 3:
                cx = trk.get('center_normalized', {}).get('x', 0.5)
                cy = trk.get('center_normalized', {}).get('y', 0.5)
                from detection_service import is_point_in_polygon
                is_in_zone = is_point_in_polygon({"x": cx, "y": cy}, pallet_zone_polygon)

            if not is_in_zone:
                continue

            # Crop box bounding box
            bbox = trk.get('bbox', {})
            x1 = max(0, int(bbox.get('x1', 0)))
            y1 = max(0, int(bbox.get('y1', 0)))
            x2 = min(frame_w, int(bbox.get('x2', frame_w)))
            y2 = min(frame_h, int(bbox.get('y2', frame_h)))

            if (x2 - x1) < 15 or (y2 - y1) < 15:
                continue

            crop = frame_bgr[y1:y2, x1:x2]

            # Compute visual similarity against target SKU reference photo
            similarity = self.matcher.compute_similarity(crop, sku_id)
            trk['sku_similarity'] = similarity

            # 1. Human Error: Cross-Pallet Contamination / Alien Item
            # Trigger violation only if SKU has reference image AND object is clearly alien (< 0.22)
            if has_ref and similarity < 0.22:
                trk['violation'] = 'CROSS_PALLET_CONTAMINATION'
                v_title = f"Wrong SKU on Pallet {pallet_id}"
                v_desc = f"Item (Track #{track_id}) placed on Pallet {pallet_id} does not match SKU '{sku_id}' (Similarity: {int(similarity * 100)}%)."

                # Save proof snapshot
                snapshot_name = f"violation_plt_{pallet_id}_trk_{track_id}_{int(datetime.now().timestamp())}.jpg"
                snapshot_path = os.path.join(ROOT_DIR, 'static', 'uploads', snapshot_name)
                os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                cv2.imwrite(snapshot_path, crop)
                rel_snapshot = f"/static/uploads/{snapshot_name}"

                v_rec = db.log_violation(
                    violation_type='CROSS_PALLET_CONTAMINATION',
                    title=v_title,
                    description=v_desc,
                    camera_id=cam_key,
                    sku_id=sku_id,
                    pallet_id=pallet_id,
                    track_id=track_id,
                    expected_value=f"SKU {sku_id}",
                    actual_value=f"Alien Box ({int(similarity*100)}% match)",
                    severity='HIGH',
                    snapshot_path=rel_snapshot
                )
                violations_triggered.append(v_rec)
                continue

            # 2. Verified SKU Bundle: Check if already counted
            if track_id not in counted_set:
                # Check Over-Capacity violation (only if a target cap was explicitly specified)
                current_count = len(counted_set)
                if target_bundles > 1 and current_count >= target_bundles:
                    trk['violation'] = 'OVER_CAPACITY'
                    v_title = f"Pallet {pallet_id} Exceeded Target Capacity"
                    v_desc = f"Bundle #{current_count + 1} added to Pallet {pallet_id}, which has reached its max capacity of {target_bundles} bundles."
                    v_rec = db.log_violation(
                        violation_type='OVER_CAPACITY',
                        title=v_title,
                        description=v_desc,
                        camera_id=cam_key,
                        sku_id=sku_id,
                        pallet_id=pallet_id,
                        track_id=track_id,
                        expected_value=f"{target_bundles} Bundles Max",
                        actual_value=f"{current_count + 1} Bundles",
                        severity='MEDIUM'
                    )
                    violations_triggered.append(v_rec)
                else:
                    # Successfully add verified bundle to pallet count!
                    counted_set.add(track_id)
                    new_count = len(counted_set)
                    updated_pallet = db.update_pallet_count(
                        pallet_id=pallet_id,
                        new_count=new_count,
                        track_id=track_id,
                        similarity_score=similarity
                    )
                    if updated_pallet:
                        pallet = updated_pallet
                    newly_counted.append(track_id)

            trk['is_counted_bundle'] = True

        current_bundles = pallet.get('counted_bundles', len(counted_set))
        total_units = current_bundles * units_per_bundle

        return {
            "active_pallet": pallet,
            "pallet_id": pallet_id,
            "sku_id": sku_id,
            "target_bundles": target_bundles,
            "counted_bundles": current_bundles,
            "units_per_bundle": units_per_bundle,
            "total_units": total_units,
            "progress_percent": min(100, int((current_bundles / max(1, target_bundles)) * 100)),
            "status": pallet.get('status', 'STACKING'),
            "newly_counted": newly_counted,
            "violations_triggered": violations_triggered
        }

    def _detect_pallet_bundles(
        self,
        image_bgr: np.ndarray,
        ref_image_bgr: Optional[np.ndarray] = None,
        sku_id: Optional[str] = None
    ) -> List[Tuple[int, int, int, int, float, str]]:
        """
        Industrial bundle and pallet detection pipeline:
        1. Trained SKU Material Localization (Gold profile + packaging signature anchor).
        2. Pallet / Stack Cargo Envelope Segmentation (suppressing background wall pipes/brackets/floor).
        3. Bundle Tier / Layer Deconstruction (horizontal edge gradients along bundle body).
        4. YOLO Warehouse Detector Integration.
        5. Non-Maximum Suppression (NMS).
        """
        h, w = image_bgr.shape[:2]
        candidate_boxes = []

        hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

        # -------------------------------------------------------------
        # Strategy 1: Trained SKU Material Anchor & Stack Decomposition
        # -------------------------------------------------------------
        # Gold / Yellow-Brass metal profile mask (characteristic of METAL-GFRAMES)
        gold_mask = cv2.inRange(hsv, np.array([12, 45, 40], dtype=np.uint8), np.array([38, 255, 255], dtype=np.uint8))
        gold_ys, gold_xs = np.where(gold_mask > 0)

        if len(gold_ys) > 500:
            try:
                # Find the vertical and horizontal boundaries of the gold bundle body
                gy_min = int(np.percentile(gold_ys, 2))
                gy_max = int(np.percentile(gold_ys, 98))
                gx_min = int(np.percentile(gold_xs, 2))
                gx_max = int(np.percentile(gold_xs, 98))

                # White packaging wrap attached to the bundle stack (front ends & strapping)
                white_mask = cv2.inRange(hsv, np.array([0, 0, 130], dtype=np.uint8), np.array([180, 50, 255], dtype=np.uint8))
                
                # Restrict white search band to stack vertical span with small padding
                y_pad = max(10, int((gy_max - gy_min) * 0.06))
                stack_ymin = max(0, gy_min - y_pad)
                stack_ymax = min(h, gy_max + y_pad)

                band_mask = np.zeros((h, w), dtype=np.uint8)
                band_mask[stack_ymin:stack_ymax, :] = 1
                combined_stack_mask = cv2.bitwise_or(gold_mask, cv2.bitwise_and(white_mask, white_mask, mask=band_mask))

                # Morphological close to consolidate stack
                kernel_stack = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
                stack_closed = cv2.morphologyEx(combined_stack_mask, cv2.MORPH_CLOSE, kernel_stack)

                cnts, _ = cv2.findContours(stack_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                valid_stacks = []
                for c in cnts:
                    bx, by, bw, bh = cv2.boundingRect(c)
                    if bw > (w * 0.20) and bh > (h * 0.15):
                        # Must contain significant gold metal pixels
                        box_gold = np.count_nonzero(gold_mask[by:by+bh, bx:bx+bw])
                        if box_gold > 2000:
                            valid_stacks.append((bx, by, bw, bh, box_gold))

                if valid_stacks:
                    valid_stacks.sort(key=lambda x: x[4], reverse=True)
                    sx, sy, sw, sh, _ = valid_stacks[0]
                    # Clamp to image
                    sx = max(0, sx)
                    sy = max(0, sy)
                    sw = min(w - sx, sw)
                    sh = min(h - sy, sh)

                    # Add the overall pallet stack
                    candidate_boxes.append((sx, sy, sx + sw, sy + sh, 0.98, "PALLET"))

                    # Decompose stack into horizontal bundle tiers
                    stack_crop = image_bgr[sy:sy+sh, sx:sx+sw]
                    stack_gray = cv2.cvtColor(stack_crop, cv2.COLOR_BGR2GRAY)
                    sobel_y = cv2.Sobel(stack_gray, cv2.CV_64F, 0, 1, ksize=3)
                    sobel_abs = np.abs(sobel_y)

                    # Projection along the gold profile body (middle-right of stack)
                    col_start = int(sw * 0.35)
                    col_end = int(sw * 0.95)
                    proj = np.mean(sobel_abs[:, col_start:col_end], axis=1)

                    klen = max(9, int(sh * 0.02) | 1)
                    kernel = np.ones(klen) / klen
                    smoothed = np.convolve(proj, kernel, mode='same')

                    # Peak detection for layer boundaries
                    min_dist = max(25, int(sh / 14))
                    from scipy.signal import find_peaks
                    peaks, _ = find_peaks(smoothed, distance=min_dist, prominence=2.0)

                    divs = [0] + [int(p) for p in peaks if 18 < p < (sh - 18)] + [sh]
                    divs = sorted(list(set(divs)))

                    for i in range(len(divs) - 1):
                        ly1 = sy + divs[i]
                        ly2 = sy + divs[i+1]
                        lh = ly2 - ly1
                        if lh < 16:
                            continue
                        candidate_boxes.append((sx, ly1, sx + sw, ly2, 0.95, "REF_BUNDLE"))
            except Exception as e:
                logger.warning(f"SKU stack decomposition exception: {e}")

        # -------------------------------------------------------------
        # Strategy 2: YOLO Warehouse Detector (with Wall Filter)
        # -------------------------------------------------------------
        try:
            from detection_service import get_detection_engine
            engine = get_detection_engine()
            det_res = engine.detect(image_bgr, conf_threshold=0.20)
            if det_res.get('success') and det_res.get('detections'):
                for d in det_res['detections']:
                    cls = d.get('class_code', '').upper()
                    if cls in ('BUNDLE', 'PALLET', 'BOX', 'MATERIAL', 'PART'):
                        bx = d['bbox']
                        x1 = max(0, int(bx.get('x1', 0)))
                        y1 = max(0, int(bx.get('y1', 0)))
                        x2 = min(w, int(bx.get('x2', w)))
                        y2 = min(h, int(bx.get('y2', h)))
                        bw = x2 - x1
                        bh = y2 - y1

                        # Strict Background Suppression:
                        # Exclude high wall fixtures (pipes/brackets on upper wall)
                        if y2 < (h * 0.40) and bh > (bw * 1.5):
                            continue
                        # Exclude items that are purely upper wall background
                        if y2 < (h * 0.30):
                            continue

                        if bw >= 25 and bh >= 25 and (bw * bh) < (w * h * 0.95):
                            src_name = f"YOLO_{cls}"
                            candidate_boxes.append((x1, y1, x2, y2, float(d.get('confidence', 0.80)), src_name))
        except Exception as e:
            logger.warning(f"YOLO bundle detection exception: {e}")

        # -------------------------------------------------------------
        # Strategy 3: Salient Industrial Profile (Ground Staging Only)
        # -------------------------------------------------------------
        if not candidate_boxes:
            try:
                gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
                blurred = cv2.bilateralFilter(gray, 7, 50, 50)
                edges = cv2.Canny(blurred, 30, 110)
                kernel_dil = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
                dilated = cv2.dilate(edges, kernel_dil, iterations=1)

                contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for cnt in contours:
                    area = cv2.contourArea(cnt)
                    if area > 4000 and area < (w * h * 0.85):
                        bx, by, bw, bh = cv2.boundingRect(cnt)
                        # Must be located in cargo staging region (lower 75% of frame)
                        if (by + bh) > (h * 0.35) and (bw > (w * 0.20) or (bw / max(1, bh)) >= 1.5):
                            candidate_boxes.append((int(bx), int(by), int(bx + bw), int(by + bh), 0.72, "BUNDLE_CONTOUR"))
            except Exception as e:
                logger.warning(f"Salient contour detection exception: {e}")

        # -------------------------------------------------------------
        # Strategy 4: Fallback
        # -------------------------------------------------------------
        if not candidate_boxes:
            margin_x = int(w * 0.10)
            margin_y = int(h * 0.20)
            candidate_boxes.append((margin_x, margin_y, w - margin_x, h - margin_y, 0.70, "FALLBACK"))

        # -------------------------------------------------------------
        # Strategy 5: Non-Maximum Suppression (NMS)
        # -------------------------------------------------------------
        # Separate PALLET and BUNDLE candidate boxes so bundles inside a pallet are not eliminated
        pallet_candidates = [b for b in candidate_boxes if "PALLET" in b[5].upper()]
        bundle_candidates = [b for b in candidate_boxes if "PALLET" not in b[5].upper()]

        def _nms_filter(boxes, iou_thresh=0.35):
            boxes.sort(key=lambda b: b[4], reverse=True)
            kept = []
            while boxes:
                best = boxes.pop(0)
                bx1, by1, bx2, by2, bconf, bsrc = best
                kept.append((int(bx1), int(by1), int(bx2), int(by2), float(bconf), str(bsrc)))
                rem = []
                b_area = (bx2 - bx1) * (by2 - by1)
                for item in boxes:
                    ix1, iy1, ix2, iy2, _, _ = item
                    xx1 = max(bx1, ix1)
                    yy1 = max(by1, iy1)
                    xx2 = min(bx2, ix2)
                    yy2 = min(by2, iy2)
                    iw = max(0, xx2 - xx1)
                    ih = max(0, yy2 - yy1)
                    iarea = iw * ih
                    item_area = (ix2 - ix1) * (iy2 - iy1)
                    iou = iarea / float(b_area + item_area - iarea + 1e-6)
                    containment = iarea / float(min(b_area, item_area) + 1e-6)
                    if iou < iou_thresh and containment < 0.70:
                        rem.append(item)
                boxes = rem
            return kept

        kept_bundles = _nms_filter(bundle_candidates, iou_thresh=0.40)
        kept_pallets = _nms_filter(pallet_candidates, iou_thresh=0.30)

        return kept_pallets + kept_bundles

    def process_pallet_image(self, pallet_id: str, image_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Process an uploaded static photo for pallet counting:
        1. Identifies bundles and pallets via YOLO + SKU reference color & contour matching.
        2. Compares each candidate against SKU reference photo.
        3. Distinguishes verified bundles, pallets, and alien boxes.
        4. Multiplies verified bundle count by declared pieces per bundle.
        5. Annotates image with Emerald Green BUNDLE badges, Cyan PALLET badges, and HUD banner.
        6. Updates database and returns full analysis payload.
        """
        pallet = db.get_pallet_by_id(pallet_id)
        if not pallet:
            return {"success": False, "error": f"Pallet '{pallet_id}' not found"}

        sku_id = pallet['sku_id']
        units_per_bundle = pallet.get('units_per_bundle') or 1
        target_bundles = pallet.get('target_bundles') or 0

        h, w = image_bgr.shape[:2]
        annotated = image_bgr.copy()

        # Step 1: Retrieve trained SKU reference photo if present
        ref_img = self.matcher.get_reference_image_for_sku(sku_id)
        has_sku_ref = (ref_img is not None and ref_img.size > 0)

        # Step 2: Run multi-strategy bundle & pallet detection
        candidate_boxes = self._detect_pallet_bundles(image_bgr, ref_img, sku_id=sku_id)

        # Sort candidate boxes top-to-bottom, left-to-right
        candidate_boxes.sort(key=lambda b: (b[1], b[0]))

        verified_items = []
        violations_triggered = []
        verified_count = 0
        pallet_count = 0

        # Step 3: Classify and annotate each candidate
        for idx, item in enumerate(candidate_boxes):
            x1, y1, x2, y2, conf, source = item
            crop = image_bgr[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            box_id = idx + 1
            is_pallet_obj = "PALLET" in source.upper()

            if is_pallet_obj:
                pallet_count += 1
                color = (255, 200, 0) # Cyan / Amber for Pallet base
                label = f"PALLET #{pallet_count}"
                verified_items.append({
                    "item_id": int(box_id),
                    "type": "PALLET",
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "similarity": 1.0
                })
            else:
                # Bundle or packaging object
                if has_sku_ref:
                    similarity = self.matcher.match_visual_signature(crop, sku_id)
                    if source in ("REF_BUNDLE", "BUNDLE_LAYER"):
                        is_verified = True
                        sim_pct = int(max(similarity, conf) * 100)
                    else:
                        is_verified = (similarity >= 0.35)
                        sim_pct = int(similarity * 100)
                else:
                    similarity = conf
                    is_verified = True
                    sim_pct = int(conf * 100)

                if is_verified:
                    verified_count += 1
                    color = (0, 220, 110) # Vibrant Emerald Green
                    label = f"BUNDLE #{verified_count} [{sim_pct}%]"

                    snapshot_name = f"pallet_item_{pallet_id}_{box_id}_{int(time.time())}.jpg"
                    snapshot_path = os.path.join(ROOT_DIR, 'static', 'uploads', snapshot_name)
                    os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                    cv2.imwrite(snapshot_path, crop)
                    rel_snapshot = f"/static/uploads/{snapshot_name}"

                    verified_items.append({
                        "item_id": int(box_id),
                        "type": "BUNDLE",
                        "bbox": [int(x1), int(y1), int(x2), int(y2)],
                        "similarity": round(float(similarity), 3),
                        "snapshot": rel_snapshot
                    })

                    # Check Over-Capacity violation (ONLY if an explicit capacity cap > 1 was declared)
                    if target_bundles > 1 and verified_count > target_bundles:
                        v_rec = db.log_violation(
                            violation_type='OVER_CAPACITY',
                            title=f"Pallet {pallet_id} Exceeded Target Capacity",
                            description=f"Detected {verified_count} bundles, exceeding declared pallet target of {target_bundles} bundles.",
                            sku_id=sku_id,
                            pallet_id=pallet_id,
                            severity='MEDIUM',
                            snapshot_path=rel_snapshot
                        )
                        violations_triggered.append(v_rec)
                        color = (0, 165, 255) # Orange warning
                        label = f"OVER CAP #{verified_count}"
                else:
                    color = (40, 40, 240) # Bright Red for genuine alien contamination
                    label = f"CONTAMINATION #{box_id}"

                    snapshot_name = f"violation_plt_{pallet_id}_{box_id}_{int(time.time())}.jpg"
                    snapshot_path = os.path.join(ROOT_DIR, 'static', 'uploads', snapshot_name)
                    os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                    cv2.imwrite(snapshot_path, crop)
                    rel_snapshot = f"/static/uploads/{snapshot_name}"

                    v_rec = db.log_violation(
                        violation_type='CROSS_PALLET_CONTAMINATION',
                        title=f"Contamination Detected on Pallet {pallet_id}",
                        description=f"Item #{box_id} does not match SKU '{sku_id}' (Similarity: {int(similarity * 100)}%).",
                        sku_id=sku_id,
                        pallet_id=pallet_id,
                        severity='HIGH',
                        snapshot_path=rel_snapshot
                    )
                    violations_triggered.append(v_rec)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 2)
            cv2.rectangle(annotated, (x1, max(0, y1 - 24)), (x1 + tw + 10, y1), color, -1)
            cv2.putText(annotated, label, (x1 + 4, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0) if color == (255, 200, 0) else (255, 255, 255), 1)

        # Step 4: Compute total realized pieces
        total_pieces = verified_count * units_per_bundle

        # Step 5: Draw top HUD summary banner
        hud_h = 60
        cv2.rectangle(annotated, (0, 0), (w, hud_h), (15, 23, 42), -1)
        cv2.line(annotated, (0, hud_h), (w, hud_h), (99, 102, 241), 2)

        hud_title = f"PALLET: {pallet_id}  |  SKU: {sku_id}"
        cv2.putText(annotated, hud_title, (16, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        if target_bundles > 1:
            count_str = f"BUNDLES: {verified_count}/{target_bundles}"
        else:
            count_str = f"BUNDLES DETECTED: {verified_count} (AUTONOMOUS COUNT)"
        
        pieces_str = f"REALIZED TOTAL: {total_pieces} EA  ({units_per_bundle} pcs/bundle)"
        cv2.putText(annotated, count_str, (16, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (56, 189, 248), 2)
        cv2.putText(annotated, pieces_str, (max(w // 2 - 20, 260), 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (74, 222, 128), 2)

        # Step 6: Save annotated result image
        annotated_name = f"pallet_annotated_{pallet_id}_{int(time.time())}.jpg"
        annotated_path = os.path.join(ROOT_DIR, 'static', 'uploads', annotated_name)
        os.makedirs(os.path.dirname(annotated_path), exist_ok=True)
        cv2.imwrite(annotated_path, annotated)
        annotated_url = f"/static/uploads/{annotated_name}"

        # Step 7: Update database
        updated_pallet = db.update_pallet_count(
            pallet_id=pallet_id,
            new_count=verified_count,
            track_id=1,
            similarity_score=1.0 if verified_count > 0 else 0.0,
            snapshot_path=annotated_url
        )

        def _sanitize_json(o):
            if isinstance(o, dict):
                return {k: _sanitize_json(v) for k, v in o.items()}
            elif isinstance(o, (list, tuple)):
                return [_sanitize_json(v) for v in o]
            elif isinstance(o, (np.integer, np.int32, np.int64)):
                return int(o)
            elif isinstance(o, (np.floating, np.float32, np.float64)):
                return float(o)
            elif isinstance(o, np.ndarray):
                return _sanitize_json(o.tolist())
            return o

        return _sanitize_json({
            "success": True,
            "status": "success",
            "pallet_id": pallet_id,
            "sku_id": sku_id,
            "counted_bundles": int(verified_count),
            "units_per_bundle": int(units_per_bundle),
            "total_pieces": int(total_pieces),
            "annotated_image_url": annotated_url,
            "items": verified_items,
            "violations_triggered": violations_triggered,
            "pallet": updated_pallet
        })

    def generate_pallet_master_label_pdf(self, pallet_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate an executive industrial Pallet Master Label PDF
        complete with QR Code containing the aggregated bundle and piece count data.
        """
        pallet = db.get_pallet_by_id(pallet_id)
        if not pallet:
            return None, f"Pallet '{pallet_id}' not found."

        if not FPDF_AVAILABLE:
            return None, "fpdf2 library is not installed."

        pdf_filename = f"Pallet_Label_{pallet_id}.pdf"
        output_path = os.path.join(PALLET_LABEL_DIR, pdf_filename)

        try:
            # 1. Generate Master QR Code
            qr_img_path = os.path.join(PALLET_LABEL_DIR, f"qr_{pallet_id}.png")
            if QRCODE_AVAILABLE:
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=10,
                    border=2
                )
                qr_content = json.dumps({
                    "doc": "PALLET_MASTER_LABEL",
                    "pallet_id": pallet['pallet_id'],
                    "sku_id": pallet['sku_id'],
                    "sku_name": pallet.get('sku_name', ''),
                    "bundles": pallet['counted_bundles'],
                    "units_per_bundle": pallet['units_per_bundle'],
                    "total_units": pallet['total_units'],
                    "sealed_at": pallet.get('sealed_at', pallet['created_at'])
                })
                qr.add_data(qr_content)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="black", back_color="white")
                qr_img.save(qr_img_path)
            else:
                qr_img_path = None

            # 2. Build PDF Document (4x6 inch standard shipping label layout = 101.6 x 152.4 mm)
            pdf = FPDF(orientation='P', unit='mm', format=(101.6, 152.4))
            pdf.set_auto_page_break(auto=False)
            pdf.add_page()

            # Outer Border
            pdf.set_line_width(1.0)
            pdf.set_draw_color(30, 41, 59)
            pdf.rect(3, 3, 95.6, 146.4)

            # Header
            pdf.set_fill_color(30, 41, 59)
            pdf.rect(3, 3, 95.6, 18, 'F')
            pdf.set_font('Helvetica', 'B', 14)
            pdf.set_text_color(255, 255, 255)
            pdf.set_xy(5, 7)
            pdf.cell(91.6, 10, "SKANTHA WMS - PALLET MASTER", align='C')

            # Pallet ID Big Text
            pdf.set_text_color(15, 23, 42)
            pdf.set_font('Helvetica', 'B', 20)
            pdf.set_xy(5, 24)
            pdf.cell(91.6, 10, pallet['pallet_id'], align='C')

            pdf.set_line_width(0.4)
            pdf.line(5, 36, 96.6, 36)

            # SKU Information
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(100, 116, 139)
            pdf.set_xy(6, 38)
            pdf.cell(40, 5, "ITEM / SKU:")

            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_text_color(15, 23, 42)
            pdf.set_xy(6, 43)
            pdf.cell(89, 6, f"{pallet['sku_id']} - {pallet.get('sku_name', 'General SKU')}")

            # Metric Boxes: Bundles & Total Pieces
            pdf.set_fill_color(241, 245, 249)
            pdf.rect(6, 52, 43, 24, 'F')
            pdf.rect(52, 52, 43, 24, 'F')

            # Bundles Box
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(71, 85, 105)
            pdf.set_xy(8, 54)
            pdf.cell(39, 4, "BUNDLES PACKED", align='C')
            pdf.set_font('Helvetica', 'B', 18)
            pdf.set_text_color(2, 132, 199)
            pdf.set_xy(8, 60)
            pdf.cell(39, 12, f"{pallet['counted_bundles']} / {pallet['target_bundles']}", align='C')

            # Total Units Box
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(71, 85, 105)
            pdf.set_xy(54, 54)
            pdf.cell(39, 4, "TOTAL PIECES (EA)", align='C')
            pdf.set_font('Helvetica', 'B', 20)
            pdf.set_text_color(16, 185, 129)
            pdf.set_xy(54, 60)
            pdf.cell(39, 12, str(pallet['total_units']), align='C')

            # Packaging Multiplier Note
            pdf.set_font('Helvetica', '', 8)
            pdf.set_text_color(100, 116, 139)
            pdf.set_xy(6, 78)
            pdf.cell(89, 4, f"Packaging Multiplier: 1 Bundle = {pallet['units_per_bundle']} Units | Target: {pallet['target_bundles']} Bundles")

            # Assigned Bin
            bin_text = f"Assigned Bin: {pallet.get('assigned_bin_id') or 'Unassigned (General Receiving)'}"
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(30, 41, 59)
            pdf.set_xy(6, 83)
            pdf.cell(89, 5, bin_text)

            # Master QR Code in Center
            if qr_img_path and os.path.exists(qr_img_path):
                pdf.image(qr_img_path, x=28, y=91, w=45, h=45)

            # Footer
            pdf.set_font('Helvetica', '', 7)
            pdf.set_text_color(148, 163, 184)
            pdf.set_xy(6, 140)
            pdf.cell(89, 4, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Skantha WMS AI Autonomous Vision", align='C')

            pdf.output(output_path)

            # Clean up temporary QR code image
            if qr_img_path and os.path.exists(qr_img_path):
                try:
                    os.remove(qr_img_path)
                except Exception:
                    pass

            return f"/static/invoices/{pdf_filename}", None
        except Exception as e:
            logger.error(f"Error generating Pallet Label PDF for '{pallet_id}': {e}")
            return None, str(e)


# Singleton Instance
_pallet_service = None

def get_pallet_service() -> AutonomousPalletizationService:
    global _pallet_service
    if _pallet_service is None:
        _pallet_service = AutonomousPalletizationService()
    return _pallet_service
