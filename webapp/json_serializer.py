import math
from typing import Any
import numpy as np


def to_json_safe(obj: Any, non_finite_fallback: float = 0.0) -> Any:
    """
    Centralized recursive serialization utility that converts supported NumPy,
    non-native scalars, and complex data structures into standard JSON-safe Python values.

    Handles:
    - np.int8, np.int16, np.int32, np.int64 -> native int
    - np.uint8, np.uint16, np.uint32, np.uint64 -> native int
    - np.float16, np.float32, np.float64 -> native float
    - np.bool_ -> native bool
    - np.ndarray -> recursive list via tolist()
    - non-finite floating-point values (NaN, Inf, -Inf) -> non_finite_fallback (default 0.0)
    - nested dictionaries (with stringified keys)
    - lists, tuples, and sets -> native lists
    - objects with to_dict() or __dict__ -> recursive dict conversion

    Preserves original data structures, keys, bounding boxes, coordinates, and metadata.
    """
    if obj is None:
        return None

    # Booleans (must check before int since bool subclasses int in Python)
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)

    # Integers (both Python int and all NumPy integer variants)
    if isinstance(obj, (int, np.integer)):
        return int(obj)

    # Floats (both Python float and all NumPy float variants)
    if isinstance(obj, (float, np.floating)):
        val = float(obj)
        if math.isnan(val) or math.isinf(val):
            return non_finite_fallback
        return val

    # NumPy ndarray
    if isinstance(obj, np.ndarray):
        return [to_json_safe(x, non_finite_fallback) for x in obj.tolist()]

    # Dictionaries
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v, non_finite_fallback) for k, v in obj.items()}

    # Lists, Tuples, Sets
    if isinstance(obj, (list, tuple, set)):
        return [to_json_safe(x, non_finite_fallback) for x in obj]

    # Custom objects with to_dict method
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        try:
            return to_json_safe(obj.to_dict(), non_finite_fallback)
        except Exception:
            pass

    # Custom class instances with __dict__
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        try:
            return to_json_safe(obj.__dict__, non_finite_fallback)
        except Exception:
            return str(obj)

    return obj

