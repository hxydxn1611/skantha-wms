"""
AI Vision & Tracking Master - Consolidated Model Loading & Weights Management
Phase 1: Deterministic model path resolution, offline safety, duplicate prevention,
and shared in-memory detector caching.
"""

import os
import sys
import logging
import threading
from typing import Optional, Tuple, Dict, Any, List

logger = logging.getLogger(__name__)

# Canonical base directory (webapp) and project root directory
WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(WEBAPP_DIR)

# Default model configurations
DEFAULT_VERIFIED_MODEL = "yolo11n.pt"
CONFIGURED_MODEL_PREFERENCE = os.environ.get("VISION_MODEL_NAME", "yolo11s.pt")

# Model capability registry documenting actual trained datasets
MODEL_CAPABILITIES = {
    "yolo11s.pt": {
        "architecture": "Ultralytics YOLO11 Small",
        "dataset": "COCO 80-Class Pretrained",
        "natively_supported": ["person", "car", "truck", "bus", "motorcycle"],
        "proxy_classes": ["suitcase (box proxy)", "backpack (box proxy)"],
        "warehouse_native_classes": False,
        "notes": "Flagship YOLO11 weights. High accuracy multi-class detector."
    },
    "yolo11n.pt": {
        "architecture": "Ultralytics YOLO11 Nano",
        "dataset": "COCO 80-Class Pretrained",
        "natively_supported": ["person", "car", "truck", "bus"],
        "proxy_classes": ["suitcase", "backpack"],
        "warehouse_native_classes": False,
        "notes": "Verified local baseline weights. Lightweight YOLO11 weights."
    }
}

# Cache for shared model singletons to avoid duplicate memory allocation
_model_cache_lock = threading.Lock()
_shared_models: Dict[str, Any] = {}


def get_candidate_search_directories() -> List[str]:
    """
    Returns ordered deterministic candidate search directories for model weights.
    Independent of current working directory.
    """
    dirs = [
        WEBAPP_DIR,
        os.path.join(WEBAPP_DIR, "models"),
        PROJECT_ROOT,
        os.path.join(PROJECT_ROOT, "ml_pipeline"),
        os.path.join(PROJECT_ROOT, "models")
    ]
    # Filter to existing directories preserving order
    seen = set()
    valid_dirs = []
    for d in dirs:
        norm = os.path.normpath(os.path.abspath(d))
        if norm not in seen and os.path.isdir(norm):
            seen.add(norm)
            valid_dirs.append(norm)
    return valid_dirs


def resolve_model_path(model_name: str) -> Optional[str]:
    """
    Deterministically resolves the absolute path of a model file.
    Does NOT search external internet resources; only verifies local files.
    """
    if not model_name:
        return None

    clean_name = str(model_name).strip()

    # 1. Direct absolute path check
    if os.path.isabs(clean_name):
        if os.path.isfile(clean_name):
            return os.path.normpath(clean_name)
        return None

    # 2. Environment variable override
    env_path = os.environ.get("VISION_MODEL_PATH")
    if env_path and os.path.isfile(env_path) and os.path.basename(env_path).lower() == clean_name.lower():
        return os.path.normpath(os.path.abspath(env_path))

    # 3. Check candidate search directories
    for search_dir in get_candidate_search_directories():
        candidate_path = os.path.join(search_dir, clean_name)
        if os.path.isfile(candidate_path):
            return os.path.normpath(os.path.abspath(candidate_path))

    return None


def is_model_available(model_name: str) -> bool:
    """Check if model weights exist locally on disk."""
    return resolve_model_path(model_name) is not None


def get_available_local_models() -> List[Dict[str, Any]]:
    """Scan search paths and return all available local model weight files."""
    available = []
    seen_hashes = set()
    
    for search_dir in get_candidate_search_directories():
        try:
            for fname in os.listdir(search_dir):
                if fname.lower().endswith(('.pt', '.onnx', '.engine')):
                    full_p = os.path.join(search_dir, fname)
                    if os.path.isfile(full_p):
                        size_bytes = os.path.getsize(full_p)
                        key = (fname.lower(), size_bytes)
                        if key not in seen_hashes:
                            seen_hashes.add(key)
                            meta = MODEL_CAPABILITIES.get(fname.lower(), {
                                "architecture": "Custom / Unknown",
                                "dataset": "Custom Weights",
                                "warehouse_native_classes": True,
                                "notes": "Local model weights file."
                            })
                            available.append({
                                "filename": fname,
                                "path": full_p,
                                "size_bytes": size_bytes,
                                "metadata": meta
                            })
        except Exception:
            pass
    return available


def load_yolo_model(
    requested_model: Optional[str] = None,
    fallback_model: Optional[str] = DEFAULT_VERIFIED_MODEL,
    allow_fallback: bool = True,
    device: str = "cpu"
) -> Tuple[Optional[Any], str, Optional[str], Optional[str]]:
    """
    Safely loads a YOLO model strictly from local weights.
    NEVER silently downloads model weights at runtime.
    
    Returns:
        (model_instance, active_model_name, active_model_path, error_message)
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        err = "Ultralytics package is not installed."
        logger.error(err)
        return None, "", None, err

    target_name = (requested_model or CONFIGURED_MODEL_PREFERENCE).strip()
    resolved_path = resolve_model_path(target_name)

    # Case A: Requested model exists locally
    if resolved_path is not None:
        try:
            logger.info(f"Loading YOLO model '{target_name}' from local path: {resolved_path}")
            model = YOLO(resolved_path)
            return model, target_name, resolved_path, None
        except Exception as e:
            load_err = f"Failed to initialize YOLO model from '{resolved_path}': {e}"
            logger.error(load_err)
            if not allow_fallback or not fallback_model or fallback_model == target_name:
                return None, target_name, resolved_path, load_err
            # Proceed to fallback below
    else:
        load_err = (
            f"Configured model '{target_name}' was not found in any local search directory. "
            f"Runtime downloads are disabled to preserve stability."
        )
        logger.warning(load_err)
        if not allow_fallback or not fallback_model:
            return None, target_name, None, load_err

    # Case B: Fallback to explicitly configured local model
    fallback_path = resolve_model_path(fallback_model)
    if fallback_path is not None:
        try:
            logger.warning(
                f"Activating fallback model '{fallback_model}' at '{fallback_path}'. "
                f"Note: '{fallback_model}' does NOT support warehouse-specific classes without fine-tuning."
            )
            model = YOLO(fallback_path)
            return model, fallback_model, fallback_path, None
        except Exception as fb_err:
            combined_err = f"{load_err} | Fallback to '{fallback_model}' also failed: {fb_err}"
            logger.error(combined_err)
            return None, "", None, combined_err
    else:
        combined_err = (
            f"{load_err} | Fallback model '{fallback_model}' is also missing from local storage."
        )
        logger.error(combined_err)
        return None, "", None, combined_err


def get_shared_detector(
    requested_model: Optional[str] = None,
    fallback_model: Optional[str] = DEFAULT_VERIFIED_MODEL,
    allow_fallback: bool = True
) -> Tuple[Optional[Any], str, Optional[str]]:
    """
    Retrieves or initializes a thread-safe cached detector instance.
    Avoids duplicate in-memory PyTorch/YOLO allocations across runtimes.
    """
    target_name = (requested_model or CONFIGURED_MODEL_PREFERENCE).strip()
    cache_key = target_name.lower()

    with _model_cache_lock:
        if cache_key in _shared_models:
            entry = _shared_models[cache_key]
            return entry["model"], entry["name"], None

        model, active_name, path, err = load_yolo_model(
            requested_model=target_name,
            fallback_model=fallback_model,
            allow_fallback=allow_fallback
        )
        if model is not None:
            _shared_models[cache_key] = {
                "model": model,
                "name": active_name,
                "path": path
            }
            # Also register under active name if fell back
            if active_name.lower() != cache_key:
                _shared_models[active_name.lower()] = _shared_models[cache_key]
            return model, active_name, None
        return None, "", err
