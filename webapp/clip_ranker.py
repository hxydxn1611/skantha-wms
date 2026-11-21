"""
CLIP ranking for "Find photos online" (AI Vision): does this photo actually show the product?

Stock-photo sites match words in tags, so "glass sheets" also returns wine glasses, glass
buildings and sheet music. CLIP (open_clip, ViT-B-32 trained on LAION-2B; runs locally on
the GPU, no key, no cost) looks at each preview and compares it with

    "a photo of <the search words>"   against everyday alternatives
    ("a photo of a drink", "... a building", "... food", "... sheet music", ...)

A photo is a good match only when CLIP thinks it shows the product more than any of those
alternatives. The score is the probability of the product description among all of them.

Loaded once on first use (about 600 MB, downloaded once into the Hugging Face cache) and
kept in memory; one lock serialises use. If open_clip is missing or anything fails, the
photo search simply keeps its tag-based ranking (score() returns None).
"""
from __future__ import annotations

import io
import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

MODEL_NAME = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"
GOOD = 0.45        # CLIP alone this sure: a match
LOOSE = 0.10       # CLIP alone below this, and the tags don't match either: dropped
TAG_FLOOR = 0.02   # tags match but CLIP is below this: only a loose match (glass is hard to see)

# everyday things stock photos show instead of warehouse goods
ALTERNATIVES = [
    "a drink or a drinking glass", "food on a plate", "a building or skyscraper", "a room interior with furniture",
    "a person or people", "an animal", "a landscape or nature scene", "sheet music or musical instruments",
    "a car or vehicle", "a city street", "flowers or plants", "an abstract background texture",
    "a computer, phone or electronics", "fire or flames", "a window of a house", "art or a painting",
    # industrial scenes, so a factory, crane or locomotive isn't taken for "steel pipes"
    "a factory or industrial building", "industrial machinery, a crane or a vehicle",
]

_lock = threading.Lock()
_state = {"model": None, "preprocess": None, "tokenizer": None, "device": "cpu", "failed": False}
_text_cache: dict = {}


def available() -> bool:
    if _state["failed"]:
        return False
    try:
        import open_clip  # noqa: F401
        return True
    except Exception:
        return False


def _load():
    if _state["model"] is not None:
        return
    import open_clip
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME, pretrained=PRETRAINED, device=device)
    model.eval()
    _state.update(model=model, preprocess=preprocess, tokenizer=open_clip.get_tokenizer(MODEL_NAME), device=device)
    logger.info(f"[CLIP] {MODEL_NAME}/{PRETRAINED} loaded on {device}")


def _text_features(query: str):
    import torch
    key = query.lower()
    hit = _text_cache.get(key)
    if hit is not None:
        return hit
    prompts = [f"a photo of {query}"] + [f"a photo of {a}" for a in ALTERNATIVES]
    tokens = _state["tokenizer"](prompts).to(_state["device"])
    with torch.no_grad():
        feats = _state["model"].encode_text(tokens).float()
        feats = feats / feats.norm(dim=-1, keepdim=True)
    if len(_text_cache) > 200:
        _text_cache.clear()
    _text_cache[key] = feats
    return feats


def score(query: str, images: List[bytes]) -> Optional[List[float]]:
    """Probability (0..1) that each image shows `query` rather than an everyday alternative.
    None when CLIP can't be used (the caller keeps its own ranking)."""
    if not images or not available():
        return None
    try:
        import torch
        from PIL import Image
        with _lock:
            _load()
            text = _text_features(query)
            batch, ok = [], []
            for b in images:
                try:
                    batch.append(_state["preprocess"](Image.open(io.BytesIO(b)).convert("RGB")))
                    ok.append(True)
                except Exception:
                    ok.append(False)
            probs_iter = iter([])
            if batch:
                with torch.no_grad():
                    feats = _state["model"].encode_image(torch.stack(batch).to(_state["device"])).float()
                    feats = feats / feats.norm(dim=-1, keepdim=True)
                    probs = (100.0 * feats @ text.T).softmax(dim=-1)[:, 0].tolist()
                probs_iter = iter(probs)
        return [round(next(probs_iter), 4) if good else 0.0 for good in ok]
    except Exception as e:
        logger.warning(f"[CLIP] ranking skipped: {e}")
        if "No module named" in str(e) or "pretrained" in str(e).lower():
            _state["failed"] = True
        return None
