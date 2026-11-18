"""
AI Vision tools: Counting Studio + product photos from the internet.

  GET    /api/vision/studio/status            model / GPU / photo sources        vision.view | vision.counting.execute | sku.view
  POST   /api/vision/studio/count             count a photo (example or words)   vision.counting.execute
  GET    /api/vision/studio/examples          saved examples (?sku_id=)          vision.view | vision.counting.execute | sku.view
  POST   /api/vision/studio/examples          save an example for a product      sku.edit
  DELETE /api/vision/studio/examples/<id>     remove a saved example             sku.edit
  GET    /api/vision/photos/search            photo search (?q=&count=&page=&seen=)   sku.create | sku.edit
  POST   /api/vision/photos/import            save chosen photos to a product    sku.edit

Changes are checked here in every RBAC mode; reads follow the route map. Examples are
company data (like products); their images are served only inside the company.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import List

import cv2
import numpy as np
from flask import Blueprint, g, jsonify, request

import counting_studio_service as studio
import db
import image_search_service as photos
import rbac_scope
import rbac_service

logger = logging.getLogger(__name__)
bp = Blueprint("vstudio", __name__)

HERE = os.path.dirname(os.path.abspath(__file__))
SKU_IMAGE_DIR = os.path.join(HERE, "static", "uploads", "sku_images")
EXAMPLE_DIR = os.path.join(HERE, "static", "uploads", "count_examples")
MAX_SIDE = 2000


class ToolError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@bp.errorhandler(ToolError)
def _tool_error(e: ToolError):
    return jsonify({"success": False, "error": e.message, "message": e.message, "error_code": e.code}), e.status


def _actor() -> str:
    return str((g.get("current_user") or {}).get("username") or "unknown")


def _need(expr: str) -> None:
    if not g.get("current_user"):
        raise ToolError(401, "login_required", "Please sign in.")
    have = rbac_service.effective_permissions()
    if not any(k in have for k in expr.split("|")):
        raise ToolError(403, "permission_denied", "You don't have permission for this.")


def _writable():
    scope = rbac_service.current_scope()
    if scope is not None and scope.read_only:
        raise ToolError(403, "read_only_scope", "All locations is a read-only view. Pick one location in the top bar first.")
    return scope


def _sku(conn, sku_id: str):
    cond, params = rbac_scope.home_filter("skus")
    row = conn.execute(f"SELECT sku_id, name FROM skus WHERE sku_id = ?{cond}", (sku_id,) + params).fetchone()
    if not row:
        raise ToolError(404, "not_found", "That product was not found.")
    return row


def _read_image(field: str = "image"):
    f = request.files.get(field)
    if not f:
        raise ToolError(400, "invalid", "Add a photo first.")
    data = np.frombuffer(f.read(), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if img is None:
        raise ToolError(400, "invalid", "That file isn't a readable photo.")
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:   # the screen sends ≤1600 px; this is only a safety net
        s = MAX_SIDE / float(max(h, w))
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def _boxes(raw) -> List[List[float]]:
    try:
        val = json.loads(raw) if isinstance(raw, str) else (raw or [])
        return [[float(v) for v in b[:4]] for b in val if isinstance(b, (list, tuple)) and len(b) >= 4][:10]
    except (ValueError, TypeError):
        raise ToolError(400, "invalid", "The example boxes could not be read.")


def _sensitivity_to_conf(raw, mode: str) -> float:
    try:
        s = max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        s = 0.5
    # 0 = strict (few, sure), 1 = generous (find more, check more); geometric so the
    # middle ("Balanced") lands near 0.1, where most stacks count best
    hi, lo = 0.30, 0.03
    return round(hi * (lo / hi) ** s, 3)


def _rel_static(abs_path: str) -> str:
    return "/static/" + os.path.relpath(abs_path, os.path.join(HERE, "static")).replace("\\", "/")


# ----------------------------------------------------------------------------- studio
@bp.route("/api/vision/studio/status", methods=["GET"])
def api_status():
    return jsonify({"success": True, **studio.status(), "photo_sources": photos.providers_status()})


@bp.route("/api/vision/studio/count", methods=["POST"])
def api_count():
    _need("vision.counting.execute")
    mode = (request.form.get("mode") or "example").strip().lower()
    detail = (request.form.get("detail") or "high").strip().lower()
    image = _read_image()
    conf = _sensitivity_to_conf(request.form.get("sensitivity"), mode)
    try:
        if mode == "text":
            raw = request.form.get("prompts") or ""
            prompts = [p.strip() for p in re.split(r"[,\n;]", raw) if p.strip()]
            # words find a few sure items (fixed low bar); the slider steers the follow-up search
            conf = _sensitivity_to_conf(request.form.get("sensitivity"), "example")
            res = studio.count_by_text(image, prompts, conf=0.03, detail=detail, follow_up_conf=conf)
        else:
            refer = None
            ex_id = (request.form.get("example_id") or "").strip()
            if ex_id and not request.form.get("boxes", "").strip("[] "):
                conn = db.get_db()
                try:
                    cond, params = rbac_scope.home_filter("sku_count_examples")
                    ex = conn.execute(f"SELECT * FROM sku_count_examples WHERE id = ?{cond}", (int(ex_id),) + params).fetchone()
                finally:
                    conn.close()
                if not ex:
                    raise ToolError(404, "not_found", "That saved example was not found.")
                # image_path is "/static/uploads/count_examples/<file>.jpg", relative to this folder
                ref_img = cv2.imread(os.path.join(HERE, *ex["image_path"].lstrip("/").split("/")))
                if ref_img is None:
                    raise ToolError(404, "not_found", "The saved example photo is missing. Save the example again.")
                refer = (ref_img, json.loads(ex["boxes_json"]))
            res = studio.count_by_example(image, _boxes(request.form.get("boxes")), conf=conf, detail=detail,
                                          similar_size=(request.form.get("similar_size", "1") not in ("0", "false")),
                                          refer=refer)
    except studio.StudioError as e:
        raise ToolError(400, "invalid", str(e))
    res["success"] = True
    res["sensitivity_conf"] = conf
    return jsonify(res)


@bp.route("/api/vision/studio/examples", methods=["GET"])
def api_examples():
    sku_id = (request.args.get("sku_id") or "").strip()
    cond, params = rbac_scope.home_filter("sku_count_examples", "e")
    where, args = "", ()
    if sku_id:
        where, args = " AND e.sku_id = ?", (sku_id,)
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute(f"""
            SELECT e.id, e.sku_id, e.name, e.image_path, e.boxes_json, e.created_by, e.created_at, s.name AS sku_name
              FROM sku_count_examples e LEFT JOIN skus s ON s.sku_id = e.sku_id
             WHERE 1 = 1{cond}{where} ORDER BY e.id DESC LIMIT 200""", params + args)]
    finally:
        conn.close()
    for r in rows:
        r["boxes"] = json.loads(r.pop("boxes_json") or "[]")
    return jsonify({"success": True, "examples": rows})


@bp.route("/api/vision/studio/examples", methods=["POST"])
def api_save_example():
    _need("sku.edit")
    _writable()
    sku_id = (request.form.get("sku_id") or "").strip()
    boxes = _boxes(request.form.get("boxes"))
    if not sku_id:
        raise ToolError(400, "invalid", "Choose the product this example is for.")
    if not boxes:
        raise ToolError(400, "invalid", "Draw a box around at least one item first.")
    image = _read_image()
    name = (request.form.get("name") or "").strip()[:80] or None
    conn = db.get_db()
    try:
        _sku(conn, sku_id)
        os.makedirs(EXAMPLE_DIR, exist_ok=True)
        path = os.path.join(EXAMPLE_DIR, f"example_{uuid.uuid4().hex[:12]}.jpg")
        cv2.imwrite(path, image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        with conn:
            cur = conn.execute("INSERT INTO sku_count_examples (sku_id, name, image_path, boxes_json, created_by) "
                               "VALUES (?, ?, ?, ?, ?)", (sku_id, name, _rel_static(path), json.dumps(boxes), _actor()))
            ex_id = cur.lastrowid
    finally:
        conn.close()
    return jsonify({"success": True, "id": ex_id, "message": "Example saved. Next time, just pick the product and press Count."})


@bp.route("/api/vision/studio/examples/<int:example_id>", methods=["DELETE"])
def api_delete_example(example_id: int):
    _need("sku.edit")
    _writable()
    conn = db.get_db()
    try:
        cond, params = rbac_scope.home_filter("sku_count_examples")
        row = conn.execute(f"SELECT image_path FROM sku_count_examples WHERE id = ?{cond}", (example_id,) + params).fetchone()
        if not row:
            raise ToolError(404, "not_found", "That example was not found.")
        with conn:
            conn.execute("DELETE FROM sku_count_examples WHERE id = ?", (example_id,))
    finally:
        conn.close()
    try:
        p = os.path.join(HERE, *row["image_path"].lstrip("/").split("/"))
        if os.path.isfile(p) and os.path.dirname(os.path.abspath(p)) == os.path.abspath(EXAMPLE_DIR):
            os.remove(p)
    except OSError:
        pass
    return jsonify({"success": True, "message": "Example removed."})


# ----------------------------------------------------------------------------- photos from the internet
@bp.route("/api/vision/photos/search", methods=["GET"])
def api_photo_search():
    _need("sku.create|sku.edit")
    seen = [s for s in (request.args.get("seen") or "").split(",") if s][:300]
    try:
        count = int(request.args.get("count") or 10)
        page = int(request.args.get("page") or 1)
    except ValueError:
        count, page = 10, 1
    try:
        items, next_page = photos.search(request.args.get("q") or "", count=count, page=page, seen=seen)
    except photos.PhotoSearchError as e:
        raise ToolError(400, "search_failed", str(e))
    return jsonify({"success": True, "photos": items, "next_page": next_page, "sources": photos.providers_status()})


@bp.route("/api/vision/photos/import", methods=["POST"])
def api_photo_import():
    _need("sku.edit")
    _writable()
    body = request.get_json(silent=True) or {}
    sku_id = str(body.get("sku_id") or "").strip()
    items = [i for i in (body.get("items") or []) if isinstance(i, dict)][:20]
    if not sku_id or not items:
        raise ToolError(400, "invalid", "Choose a product and at least one photo.")
    conn = db.get_db()
    try:
        _sku(conn, sku_id)
    finally:
        conn.close()
    os.makedirs(SKU_IMAGE_DIR, exist_ok=True)
    saved, errors = [], []
    safe_sku = re.sub(r"[^A-Za-z0-9._-]", "_", sku_id).strip(".") or "SKU"
    for it in items:
        try:
            data = photos.import_photo(str(it.get("url") or ""))
        except photos.PhotoSearchError as e:
            errors.append(str(e))
            continue
        fname = f"{safe_sku}_web_{uuid.uuid4().hex[:8]}.jpg"
        path = os.path.join(SKU_IMAGE_DIR, fname)
        with open(path, "wb") as fh:
            fh.write(data)
        credit = f"{it.get('provider') or 'Web'} - {it.get('author') or 'unknown'}"[:120]
        rec, err = db.add_sku_image(sku_id=sku_id, filename=fname, original_filename=credit,
                                    file_path=f"/static/uploads/sku_images/{fname}", file_size=len(data),
                                    mime_type="image/jpeg", is_primary=0)
        if err:
            errors.append(err)
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            saved.append(rec)
    if not saved:
        raise ToolError(400, "import_failed", errors[0] if errors else "No photo could be saved.")
    return jsonify({"success": True, "saved": len(saved), "images": saved, "errors": errors,
                    "message": f"Added {len(saved)} photo{'s' if len(saved) != 1 else ''} to {sku_id}."})
