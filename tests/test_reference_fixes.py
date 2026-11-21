"""
2026-11-21: reference errors

  * every function a page button calls (onclick / onchange / oninput / onsubmit in the templates) must exist
    in the page scripts or templates - "Use Device Camera" (openDeviceCamPrompt) and the detection
    test-bench upload (previewDetectionUploadedFile) called functions that never existed
  * count_individual_pieces sent wrapped / non-glass bundle counts on with names from another function
    (angle1_bgr, angle2_bgr, has_distinct_side_view): NameError
"""
import os
import re
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
BUILTIN = {"if", "return", "alert", "confirm", "prompt", "event", "this", "document", "window", "setTimeout",
           "encodeURIComponent", "parseInt", "parseFloat", "String", "Number", "Boolean", "JSON", "Math", "fetch",
           "console", "preventDefault", "stopPropagation", "querySelector", "getElementById", "click", "focus",
           "remove", "toggle", "add", "closest", "select", "open", "close", "print", "reset", "submit", "location",
           "reload", "history", "back", "showToast"}


class TestPageHandlersExist(unittest.TestCase):
    def test_every_button_calls_a_function_that_exists(self):
        defined = set()
        js_dir = os.path.join(WEBAPP, "static", "js")
        for f in os.listdir(js_dir):
            if f.endswith(".js"):
                src = open(os.path.join(js_dir, f), encoding="utf-8", errors="replace").read()
                defined.update(re.findall(r"(?:window\.|function\s+|const\s+|let\s+|var\s+)([A-Za-z_$][\w$]*)\s*(?:=|\()", src))
        html = ""
        tdir = os.path.join(WEBAPP, "templates")
        for f in os.listdir(tdir):
            if f.endswith(".html"):
                html += open(os.path.join(tdir, f), encoding="utf-8", errors="replace").read()
        defined.update(a or b for a, b in re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(|window\.([A-Za-z_$][\w$]*)\s*=", html))
        called = set()
        for handler in re.findall(r'on(?:click|change|input|submit|keyup|keydown)="([^"]+)"', html):
            called.update(re.findall(r"(?:^|[;\s(!])([A-Za-z_$][\w$]*)\s*\(", handler))
        missing = sorted(c for c in called if c not in defined and c not in BUILTIN)
        self.assertEqual(missing, [], f"page buttons call functions that do not exist: {missing}")


class TestPieceCountRoutesBundles(unittest.TestCase):
    def test_wrapped_and_untinted_glass_bundles_count_without_name_errors(self):
        from pallet_vision_counting_service import get_pallet_vision_counting_service
        svc = get_pallet_vision_counting_service()
        img = np.full((240, 320, 3), 150, np.uint8)
        img[60:180, 80:240] = (90, 90, 90)
        for mat in ("wrapped_bundles", "glass_bundles"):
            try:
                svc.count_individual_pieces(img, material_type=mat, counting_mode="bundles")
            except NameError as e:          # anything else is the counter's business; a NameError is the bug
                self.fail(f"{mat}: {e}")


if __name__ == "__main__":
    unittest.main()
