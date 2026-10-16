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

        # Fetch primary image from DB
        images = db.get_sku_images(sku_key)
        if not images:
            return None

        # Look for primary image or fallback to first image
        primary_img = next((img for img in images if img.get('is_primary')), images[0])
        rel_path = primary_img.get('file_path', '')
        if not rel_path:
            return None

        # Normalize relative path to filesystem path
        clean_rel = rel_path.lstrip('/').replace('/', os.sep)
        full_path = os.path.join(ROOT_DIR, clean_rel)

        if not os.path.exists(full_path):
            logger.warning(f"SKU '{sku_key}' reference image path not found on disk: {full_path}")
            return None

        try:
            img = cv2.imread(full_path)
            if img is None:
                return None

            signature = self.compute_signature(img)
            self._cache[sku_key] = signature
            return signature
        except Exception as e:
            logger.error(f"Failed to compute visual signature for SKU '{sku_key}': {e}")
            return None

    def compute_signature(self, bgr_crop: np.ndarray) -> Dict[str, Any]:
        """Compute normalized HSV color histogram and gradient edge magnitude."""
        hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
        # 3D Histogram: 16 Hue bins, 8 Saturation bins, 8 Value bins
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [16, 8, 8], [0, 180, 0, 256, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

        # Grayscale Edge magnitude
        gray = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        mean_edge = float(np.mean(mag))

        return {
            "hist": hist,
            "mean_edge": mean_edge,
            "mean_hue": float(np.mean(hsv[:, :, 0])),
            "mean_sat": float(np.mean(hsv[:, :, 1]))
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

        # Histogram Correlation (returns -1.0 to 1.0)
        hist_corr = cv2.compareHist(ref_sig['hist'], cand_sig['hist'], cv2.HISTCMP_CORREL)
        norm_corr = max(0.0, float(hist_corr))

        # Hue and Saturation distance factor
        hue_diff = abs(ref_sig['mean_hue'] - cand_sig['mean_hue']) / 180.0
        sat_diff = abs(ref_sig['mean_sat'] - cand_sig['mean_sat']) / 255.0
        color_proximity = max(0.0, 1.0 - (hue_diff * 0.6 + sat_diff * 0.4))

        # Combined similarity score
        final_score = round(0.70 * norm_corr + 0.30 * color_proximity, 4)
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
            if pallet and pallet.get('status') == 'STACKING':
                return pallet
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

        for trk in tracks:
            cls_code = trk.get('class_code', '')
            # We evaluate BOX objects (bundles/cartons)
            if cls_code != 'BOX':
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
            if similarity < 0.45:
                trk['violation'] = 'CROSS_PALLET_CONTAMINATION'
                v_title = f"Wrong SKU on Pallet {pallet_id}"
                v_desc = f"Box (Track #{track_id}) placed on Pallet {pallet_id} does not match SKU '{sku_id}' (Similarity: {int(similarity * 100)}%)."

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
                if target_bundles > 0 and current_count >= target_bundles:
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

    def process_pallet_image(
        self,
        pallet_id: str,
        image_bgr: np.ndarray
    ) -> Dict[str, Any]:
        """
        Process an uploaded static photo for pallet counting:
        1. Identifies candidate bundle/carton objects via YOLO detector (or contour proposals).
        2. Compares each candidate against SKU reference photo.
        3. Identifies verified bundles vs alien boxes.
        4. Multiplies verified bundle count by declared pieces per bundle.
        5. Annotates image with emerald-green/red boxes and HUD banner.
        6. Updates database and returns full analysis payload.
        """
        pallet = db.get_pallet_by_id(pallet_id)
        if not pallet:
            return {"success": False, "error": f"Pallet '{pallet_id}' not found"}

        sku_id = pallet['sku_id']
        units_per_bundle = pallet['units_per_bundle'] or 1
        target_bundles = pallet['target_bundles'] or 0

        h, w = image_bgr.shape[:2]
        annotated = image_bgr.copy()

        # Step 1: Detect candidate boxes using YOLO
        candidate_boxes = []
        try:
            from detection_service import get_detection_engine
            det_res = get_detection_engine().detect(image_bgr, conf_threshold=0.15)
            if det_res.get('success') and det_res.get('detections'):
                for d in det_res['detections']:
                    cls = d.get('class_code', '')
                    lbl = str(d.get('label', '')).lower()
                    if cls in ('BOX', 'BUNDLE', 'PALLET', 'MATERIAL', 'PART') or lbl in ('box', 'suitcase', 'backpack', 'handbag', 'book', 'package'):
                        bx = d['bbox']
                        x1 = max(0, int(bx.get('x1', 0)))
                        y1 = max(0, int(bx.get('y1', 0)))
                        x2 = min(w, int(bx.get('x2', w)))
                        y2 = min(h, int(bx.get('y2', h)))
                        if (x2 - x1) >= 20 and (y2 - y1) >= 20:
                            candidate_boxes.append((x1, y1, x2, y2, d.get('confidence', 0.85)))
        except Exception as e:
            logger.warning(f"YOLO detection on pallet image exception: {e}")

        # Step 1.5: If YOLO found fewer than 2 boxes, use contour proposal fallback
        if len(candidate_boxes) < 2:
            try:
                gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                edged = cv2.Canny(blurred, 40, 150)
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
                dilated = cv2.dilate(edged, kernel, iterations=2)
                contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                min_area = (h * w) * 0.005 # At least 0.5% of frame
                max_area = (h * w) * 0.85  # At most 85% of frame
                for c in contours:
                    area = cv2.contourArea(c)
                    if min_area <= area <= max_area:
                        x, y, bw, bh = cv2.boundingRect(c)
                        aspect = bw / float(bh)
                        if 0.25 <= aspect <= 4.0:
                            # Avoid duplicate overlap
                            overlaps = False
                            for ex1, ey1, ex2, ey2, _ in candidate_boxes:
                                if abs(x - ex1) < 30 and abs(y - ey1) < 30:
                                    overlaps = True
                                    break
                            if not overlaps:
                                candidate_boxes.append((x, y, x + bw, y + bh, 0.75))
            except Exception as e:
                logger.warning(f"Contour proposal exception: {e}")

        # Fallback if no box found: treat center region as 1 bundle
        if not candidate_boxes:
            margin_x = int(w * 0.15)
            margin_y = int(h * 0.15)
            candidate_boxes.append((margin_x, margin_y, w - margin_x, h - margin_y, 0.65))

        # Sort candidate boxes by vertical position
        candidate_boxes.sort(key=lambda b: (b[1], b[0]))

        verified_items = []
        violations_triggered = []
        verified_count = 0
        has_sku_ref = self.matcher.has_reference_image(sku_id)

        # Step 2: Compare each box against SKU photo
        for idx, (x1, y1, x2, y2, conf) in enumerate(candidate_boxes):
            crop = image_bgr[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            if has_sku_ref:
                similarity = self.matcher.match_visual_signature(crop, sku_id)
                is_verified = (similarity >= 0.40)
            else:
                similarity = conf
                is_verified = True

            box_id = idx + 1
            if is_verified:
                verified_count += 1
                color = (0, 220, 110) # Emerald green
                label = f"VERIFIED #{verified_count} ({int(similarity*100)}%)"

                snapshot_name = f"pallet_item_{pallet_id}_{box_id}_{int(time.time())}.jpg"
                snapshot_path = os.path.join(ROOT_DIR, 'static', 'uploads', snapshot_name)
                os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                cv2.imwrite(snapshot_path, crop)
                rel_snapshot = f"/static/uploads/{snapshot_name}"

                verified_items.append({
                    "item_id": box_id,
                    "bbox": [x1, y1, x2, y2],
                    "similarity": round(float(similarity), 3),
                    "snapshot": rel_snapshot
                })

                # Check Over-Capacity violation
                if target_bundles > 0 and verified_count > target_bundles:
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
                color = (40, 40, 240) # Bright Red
                label = f"VIOLATION: WRONG SKU ({int(similarity*100)}%)"

                snapshot_name = f"violation_plt_{pallet_id}_{box_id}_{int(time.time())}.jpg"
                snapshot_path = os.path.join(ROOT_DIR, 'static', 'uploads', snapshot_name)
                os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                cv2.imwrite(snapshot_path, crop)
                rel_snapshot = f"/static/uploads/{snapshot_name}"

                v_rec = db.log_violation(
                    violation_type='CROSS_PALLET_CONTAMINATION',
                    title=f"Contamination Detected on Pallet {pallet_id}",
                    description=f"Box #{box_id} does not match SKU '{sku_id}' (Similarity: {int(similarity * 100)}%).",
                    sku_id=sku_id,
                    pallet_id=pallet_id,
                    severity='HIGH',
                    snapshot_path=rel_snapshot
                )
                violations_triggered.append(v_rec)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            cv2.rectangle(annotated, (x1, max(0, y1 - 24)), (x1 + tw + 10, y1), color, -1)
            cv2.putText(annotated, label, (x1 + 5, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        # Step 3: Compute pieces
        total_pieces = verified_count * units_per_bundle

        # Step 4: Draw top HUD summary
        hud_h = 60
        cv2.rectangle(annotated, (0, 0), (w, hud_h), (15, 23, 42), -1)
        cv2.line(annotated, (0, hud_h), (w, hud_h), (99, 102, 241), 2)

        hud_title = f"PALLET: {pallet_id}  |  SKU: {sku_id}"
        cv2.putText(annotated, hud_title, (16, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        if target_bundles > 0:
            count_str = f"BUNDLES: {verified_count}/{target_bundles}"
        else:
            count_str = f"BUNDLES DETECTED: {verified_count} (OPEN COUNT)"
        
        pieces_str = f"REALIZED TOTAL: {total_pieces} EA  ({units_per_bundle} pcs/bundle)"
        cv2.putText(annotated, count_str, (16, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (56, 189, 248), 2)
        cv2.putText(annotated, pieces_str, (max(w // 2 - 20, 260), 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (74, 222, 128), 2)

        # Step 5: Save annotated result image
        annotated_name = f"pallet_annotated_{pallet_id}_{int(time.time())}.jpg"
        annotated_path = os.path.join(ROOT_DIR, 'static', 'uploads', annotated_name)
        os.makedirs(os.path.dirname(annotated_path), exist_ok=True)
        cv2.imwrite(annotated_path, annotated)
        annotated_url = f"/static/uploads/{annotated_name}"

        # Step 6: Update database
        updated_pallet = db.update_pallet_count(
            pallet_id=pallet_id,
            new_count=verified_count,
            track_id=1,
            similarity_score=1.0 if verified_count > 0 else 0.0,
            snapshot_path=annotated_url
        )

        return {
            "success": True,
            "status": "success",
            "pallet_id": pallet_id,
            "sku_id": sku_id,
            "counted_bundles": verified_count,
            "units_per_bundle": units_per_bundle,
            "total_pieces": total_pieces,
            "annotated_image_url": annotated_url,
            "items": verified_items,
            "violations_triggered": violations_triggered,
            "pallet": updated_pallet
        }

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
