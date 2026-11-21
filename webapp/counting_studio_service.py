"""
Counting Studio (AI Vision): count items without training.

  count_by_example(image, boxes)   "show it one item": the operator draws a box round 1-3
                                   items, YOLOE finds everything that looks like them
  count_by_example(image, [], refer=(example_image, example_boxes))
                                   the same, using an example saved for the product
  count_by_text(image, ["steel pipe end"])
                                   "type what to find": open-vocabulary detection finds the
                                   surest few, which then serve as examples for the rest

Model: Ultralytics YOLOE (yoloe-11s-seg.pt, local file; text search also needs the
MobileCLIP text encoder mobileclip_blt.ts, downloaded once). Two model copies are kept -
one per mode - because each mode reconfigures its model; a lock serialises use, so this
never runs inside camera frame loops and never blocks them (separate model objects).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = "yoloe-11s-seg.pt"
TEXT_ENCODER_FILE = "mobileclip_blt.ts"
MAX_ITEMS = 1500
DETAIL_SIZES = {"normal": 640, "high": 1024, "max": 1280}


class StudioError(Exception):
    pass


_lock = threading.Lock()
_models: Dict[str, Any] = {}
_text_classes: Tuple[str, ...] = ()


def _model_path() -> Optional[str]:
    for d in (HERE, os.path.dirname(HERE)):
        p = os.path.join(d, MODEL_FILE)
        if os.path.isfile(p):
            return p
    return None


def _text_encoder_ready() -> bool:
    return any(os.path.isfile(os.path.join(d, TEXT_ENCODER_FILE)) for d in (HERE, os.path.dirname(HERE), os.getcwd()))


def _device() -> str:
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def status() -> Dict[str, Any]:
    dev = _device()
    gpu = None
    if dev.startswith("cuda"):
        try:
            import torch
            gpu = torch.cuda.get_device_name(0)
        except Exception:
            gpu = None
    return {"model_ready": _model_path() is not None, "text_ready": _model_path() is not None and _text_encoder_ready(),
            "device": "GPU" if dev.startswith("cuda") else "CPU", "gpu_name": gpu, "model": MODEL_FILE}


def _get(kind: str):
    m = _models.get(kind)
    if m is None:
        path = _model_path()
        if not path:
            raise StudioError("The counting model isn't installed yet (yoloe-11s-seg.pt).")
        from ultralytics import YOLOE
        cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(path))   # the text encoder is looked up / saved next to the model
            m = YOLOE(path)
        finally:
            os.chdir(cwd)
        _models[kind] = m
    return m


# ----------------------------------------------------------------------------- helpers
def _to_items(result, size_filter: Optional[Tuple[float, float]] = None) -> List[Dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    xyxy = boxes.xyxy.cpu().numpy()
    conf = boxes.conf.cpu().numpy()
    items = []
    for (x1, y1, x2, y2), c in zip(xyxy, conf):
        area = max(1.0, float(x2 - x1) * float(y2 - y1))
        if size_filter and not (size_filter[0] <= area <= size_filter[1]):
            continue
        items.append({"x1": round(float(x1), 1), "y1": round(float(y1), 1), "x2": round(float(x2), 1),
                      "y2": round(float(y2), 1), "cx": round(float(x1 + x2) / 2, 1), "cy": round(float(y1 + y2) / 2, 1),
                      "conf": round(float(c), 3)})
    items = _drop_repeats(items)
    # reading order: top to bottom, then left to right (rows of roughly one item height)
    if items:
        h = float(np.median([i["y2"] - i["y1"] for i in items])) or 1.0
        items.sort(key=lambda i: (round(i["cy"] / (h * 0.7)), i["cx"]))
    return items[:MAX_ITEMS]


def _box_area(i: Dict[str, Any]) -> float:
    return max(1.0, (i["x2"] - i["x1"]) * (i["y2"] - i["y1"]))


def _overlap(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    return (max(0.0, min(a["x2"], b["x2"]) - max(a["x1"], b["x1"]))
            * max(0.0, min(a["y2"], b["y2"]) - max(a["y1"], b["y1"])))


def _drop_repeats(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Count each item once. The model's own overlap check misses two cases (a stack of 28 channels was
    marked 37): 1. a box drawn around two or more items that were also found one by one - the group box goes;
    2. the same item found twice at about the same size - the surer one stays. A box twice the size holding
    just one other box is kept: it may be the only box for the item beside it (carton stacks)."""
    singles = [g for g in items
               if sum(1 for o in items if o is not g and _box_area(o) < _box_area(g)
                      and _overlap(g, o) / _box_area(o) > 0.8) < 2]
    kept: List[Dict[str, Any]] = []
    for it in sorted(singles, key=lambda i: -i["conf"]):
        repeat = False
        for k in kept:
            if max(_box_area(it), _box_area(k)) / min(_box_area(it), _box_area(k)) > 1.6:
                continue
            if _overlap(it, k) / min(_box_area(it), _box_area(k)) > 0.6:
                repeat = True
                break
            kw, kh = (k["x2"] - k["x1"]) * 0.3, (k["y2"] - k["y1"]) * 0.3
            if k["x1"] + kw <= it["cx"] <= k["x2"] - kw and k["y1"] + kh <= it["cy"] <= k["y2"] - kh:
                repeat = True
                break
        if not repeat:
            kept.append(it)
    return kept


def _clean_boxes(boxes: Sequence[Sequence[float]], w: int, h: int) -> np.ndarray:
    out = []
    for b in boxes or []:
        try:
            x1, y1, x2, y2 = [float(v) for v in list(b)[:4]]
        except (TypeError, ValueError):
            continue
        x1, x2 = sorted((max(0.0, min(w - 1.0, x1)), max(0.0, min(w - 1.0, x2))))
        y1, y2 = sorted((max(0.0, min(h - 1.0, y1)), max(0.0, min(h - 1.0, y2))))
        if (x2 - x1) >= 4 and (y2 - y1) >= 4:
            out.append([x1, y1, x2, y2])
    return np.array(out[:10], dtype=np.float32)


def _size_band(boxes: np.ndarray) -> Tuple[float, float]:
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    med = float(np.median(areas))
    return med * 0.25, med * 4.0


def _run(image_bgr: np.ndarray, conf: float, detail: str, **kw):
    imgsz = DETAIL_SIZES.get(detail, 1024)
    return dict(source=image_bgr, conf=max(0.03, min(0.9, float(conf))), iou=0.5, imgsz=imgsz,
                max_det=MAX_ITEMS, device=_device(), verbose=False, **kw)


# ----------------------------------------------------------------------------- counting
def count_by_example(image_bgr: np.ndarray, boxes: Sequence[Sequence[float]], conf: float = 0.15,
                     detail: str = "high", similar_size: bool = True,
                     refer: Optional[Tuple[np.ndarray, Sequence[Sequence[float]]]] = None) -> Dict[str, Any]:
    if image_bgr is None or image_bgr.size == 0:
        raise StudioError("No photo to count.")
    h, w = image_bgr.shape[:2]
    if refer is not None:
        ref_img, ref_boxes = refer
        vp_boxes = _clean_boxes(ref_boxes, ref_img.shape[1], ref_img.shape[0])
    else:
        ref_img = None
        vp_boxes = _clean_boxes(boxes, w, h)
    if len(vp_boxes) == 0:
        raise StudioError("Draw a box around at least one item first.")
    from ultralytics.models.yolo.yoloe import YOLOEVPSegPredictor
    t0 = time.time()
    with _lock:
        model = _get("example")
        model.predictor = None   # a fresh predictor for each set of example boxes
        kwargs = _run(image_bgr, conf, detail, visual_prompts={"bboxes": vp_boxes, "cls": np.zeros(len(vp_boxes), dtype=np.int64)},
                      predictor=YOLOEVPSegPredictor)
        if ref_img is not None:
            kwargs["refer_image"] = ref_img
        results = model.predict(**kwargs)
    band = _size_band(vp_boxes) if similar_size else None
    if band is not None and ref_img is not None:
        # a saved example may come from a photo taken closer or further away: be lenient
        band = (band[0] * 0.25, band[1] * 4.0)
    items = _to_items(results[0], band)
    return {"mode": "example", "count": len(items), "items": items, "width": w, "height": h,
            "ms": int((time.time() - t0) * 1000), "examples": int(len(vp_boxes))}


def count_by_text(image_bgr: np.ndarray, prompts: Sequence[str], conf: float = 0.03,
                  detail: str = "high", follow_up: bool = True, follow_up_conf: float = 0.1) -> Dict[str, Any]:
    global _text_classes
    if image_bgr is None or image_bgr.size == 0:
        raise StudioError("No photo to count.")
    names = tuple(dict.fromkeys(" ".join(str(p).split())[:60] for p in (prompts or []) if str(p).strip()))[:5]
    if not names:
        raise StudioError("Type what to look for, e.g. \"steel pipe end\".")
    if not _text_encoder_ready():
        raise StudioError("Text search is still being set up (the text encoder is downloading). Try counting by example.")
    h, w = image_bgr.shape[:2]
    t0 = time.time()
    with _lock:
        model = _get("text")
        if names != _text_classes:
            cwd = os.getcwd()
            try:
                os.chdir(os.path.dirname(_model_path()))
                model.set_classes(list(names), model.get_text_pe(list(names)))
            finally:
                os.chdir(cwd)
            _text_classes = names
            model.predictor = None
        results = model.predict(**_run(image_bgr, conf, detail))
    items = _to_items(results[0])
    res = results[0]
    if getattr(res, "boxes", None) is not None and len(res.boxes):
        cls = res.boxes.cls.cpu().numpy().astype(int).tolist()
        # _to_items sorted the items; label by matching coordinates
        lookup = {}
        for (x1, y1, x2, y2), c in zip(res.boxes.xyxy.cpu().numpy(), cls):
            lookup[(round(float(x1), 1), round(float(y1), 1))] = names[c] if 0 <= c < len(names) else ""
        for it in items:
            it["label"] = lookup.get((it["x1"], it["y1"]), "")
    words_only = {"mode": "text", "count": len(items), "items": items, "width": w, "height": h,
                  "ms": int((time.time() - t0) * 1000), "prompts": list(names), "auto_examples": []}
    if not follow_up or not items:
        return words_only
    # Words alone are unsure on crowded stacks. Take the surest few matches of a similar size
    # as examples and let the (much stronger) example search find the rest.
    seeds = sorted(items, key=lambda i: -i["conf"])
    top = seeds[0]
    top_area = (top["x2"] - top["x1"]) * (top["y2"] - top["y1"])
    picked = [top]
    for it in seeds[1:]:
        a = (it["x2"] - it["x1"]) * (it["y2"] - it["y1"])
        if 0.4 * top_area <= a <= 2.5 * top_area:
            picked.append(it)
        if len(picked) == 3:
            break
    boxes = [[i["x1"], i["y1"], i["x2"], i["y2"]] for i in picked]
    res2 = count_by_example(image_bgr, boxes, conf=follow_up_conf, detail=detail, similar_size=True)
    if res2["count"] < len(items):
        return words_only
    res2.update({"mode": "text", "prompts": list(names), "auto_examples": boxes, "words_found": len(items),
                 "ms": int((time.time() - t0) * 1000)})
    return res2
