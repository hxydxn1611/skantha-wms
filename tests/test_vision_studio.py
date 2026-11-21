"""
AI Vision tools: Counting Studio (YOLOE, no training), saved examples, Weight Check wiring,
product photos from the internet.

  * count by example finds many items from 2-3 drawn boxes; words find sure seeds first
  * a saved example counts a product with no drawing; it is company data (other companies
    can't see or use it) and only sku.edit can save / remove it
  * counting needs vision.counting.execute, in every RBAC mode
  * photos are only ever downloaded from the photo services' own hosts; search never repeats
"""
import io
import os
import sqlite3
import unittest
from unittest import mock

from tests.test_rbac_phase7 import Phase7Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "webapp", "static", "samples", "sample_planks_cc0.jpg")
EXAMPLES = [[522, 405, 596, 445], [910, 525, 972, 568], [790, 397, 858, 426]]


def _model_ready():
    import counting_studio_service as s
    return s.status()["model_ready"]


class StudioBase(Phase7Base):
    def post_image(self, c, path, form, image=SAMPLE):
        headers = {"X-CSRF-Token": "t"}
        if c.wh is not None:
            headers["X-Warehouse-Id"] = str(c.wh)
        data = dict(form)
        data["image"] = (io.BytesIO(open(image, "rb").read()), "photo.jpg")
        return c.post(path, data=data, headers=headers, content_type="multipart/form-data")


class TestSchemaAndRoutes(StudioBase):
    def test_migration_and_route_map(self):
        names = {r[0] for r in self.sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("sku_count_examples", names)
        import rbac_routes
        for ep in ("vstudio.api_count", "vstudio.api_photo_search", "vstudio.api_photo_import",
                   "vstudio.api_save_example", "vstudio.api_delete_example", "vstudio.api_examples", "vstudio.api_status"):
            self.assertIn(ep, rbac_routes.ROUTE_PERMISSIONS)

    def test_status(self):
        r = self.get(self.client("david", self.glass_wh[0]), "/api/vision/studio/status")
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertIn("photo_sources", body)
        self.assertTrue(body["photo_sources"]["openverse"])


@unittest.skipUnless(os.path.isfile(SAMPLE), "sample photo missing")
class TestCounting(StudioBase):
    def setUp(self):
        super().setUp()
        if not _model_ready():
            self.skipTest("YOLOE model not installed")

    def test_count_by_example(self):
        import json
        d = self.client("david", self.glass_wh[0])
        r = self.post_image(d, "/api/vision/studio/count", {"mode": "example", "boxes": json.dumps(EXAMPLES),
                                                             "sensitivity": "0.5", "detail": "high"})
        body = r.get_json()
        self.assertTrue(body["success"], body)
        self.assertGreater(body["count"], 50)          # a chaotic stack of ~200 plank ends
        self.assertEqual(body["examples"], 3)
        r = self.post_image(d, "/api/vision/studio/count", {"mode": "example", "boxes": "[]"})
        self.assertEqual(r.status_code, 400)

    def test_count_needs_the_permission_in_audit_mode(self):
        import json
        self.cfg.RBAC_MODE = "audit"
        ic = self.role_user("inventory_controller", "vsinvctl")   # no vision.counting.execute
        r = self.post_image(ic, "/api/vision/studio/count", {"mode": "example", "boxes": json.dumps(EXAMPLES)})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (403, "permission_denied"))

    def test_saved_example_counts_without_drawing_and_stays_in_the_company(self):
        import json
        d = self.client("david", self.glass_wh[0])
        r = self.post_image(d, "/api/vision/studio/examples", {"sku_id": "GLS-FLT-04MM", "boxes": json.dumps(EXAMPLES),
                                                                "name": "test example"})
        body = r.get_json()
        self.assertTrue(body["success"], body)
        ex_id = body["id"]
        row = self.sql("SELECT company_id, image_path FROM sku_count_examples WHERE id = ?", (ex_id,))[0]
        self.assertEqual(row[0], self.glass_wh[1])
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "webapp", *row[1].lstrip("/").split("/"))))
        r = self.post_image(d, "/api/vision/studio/count", {"mode": "example", "example_id": str(ex_id)})
        self.assertGreater(r.get_json()["count"], 30, r.get_json())
        listed = self.get(d, "/api/vision/studio/examples?sku_id=GLS-FLT-04MM").get_json()["examples"]
        self.assertIn(ex_id, [e["id"] for e in listed])
        # another company: invisible, unusable, undeletable
        leak = self.client("leakadmin", self.leak_wh)
        self.assertNotIn(ex_id, [e["id"] for e in self.get(leak, "/api/vision/studio/examples").get_json()["examples"]])
        r = self.post_image(leak, "/api/vision/studio/count", {"mode": "example", "example_id": str(ex_id)})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.send(leak, "DELETE", f"/api/vision/studio/examples/{ex_id}").status_code, 404)
        # the owner removes it (row and file)
        r = self.send(d, "DELETE", f"/api/vision/studio/examples/{ex_id}")
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertFalse(self.sql("SELECT 1 FROM sku_count_examples WHERE id = ?", (ex_id,)))
        self.assertFalse(os.path.isfile(os.path.join(ROOT, "webapp", *row[1].lstrip("/").split("/"))))

    def test_words_find_seeds_then_examples(self):
        import counting_studio_service as s
        if not s.status()["text_ready"]:
            self.skipTest("text encoder not installed")
        d = self.client("david", self.glass_wh[0])
        r = self.post_image(d, "/api/vision/studio/count", {"mode": "text", "prompts": "wooden plank", "sensitivity": "0.5"})
        body = r.get_json()
        self.assertTrue(body["success"], body)
        self.assertGreater(body["count"], 30)
        self.assertTrue(body["auto_examples"])


class TestPhotos(StudioBase):
    def test_only_photo_service_hosts_are_downloaded(self):
        import image_search_service as s
        for bad in ("http://cdn.pixabay.com/x.jpg", "https://evil.example.com/x.jpg", "https://pixabay.com.evil.io/x.jpg",
                    "file:///etc/passwd", "https://127.0.0.1/x.jpg", "https://169.254.169.254/latest",
                    # Openverse photos come only through Openverse's own image service
                    "https://live.staticflickr.com/1/x.jpg", "https://upload.wikimedia.org/a/b.jpg"):
            self.assertFalse(s._allowed(bad), bad)
        for good in ("https://cdn.pixabay.com/photo/x.jpg", "https://images.pexels.com/photos/1/x.jpeg",
                     "https://api.openverse.org/v1/images/abc/thumb/?full_size=true"):
            self.assertTrue(s._allowed(good), good)
        d = self.client("david", self.glass_wh[0])
        r = self.send(d, "POST", "/api/vision/photos/import", {"sku_id": "GLS-FLT-04MM",
                                                               "items": [{"url": "https://evil.example.com/x.jpg"}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not from Pixabay", r.get_json()["error"])

    def test_search_mixes_sources_and_never_repeats(self):
        import image_search_service as s

        def fake(name):
            def fn(query, page):
                return [{"id": f"{name}:{page}-{i}", "provider": name, "thumb": "https://cdn.pixabay.com/t.jpg",
                         "url": "https://cdn.pixabay.com/u.jpg", "author": "a"} for i in range(20)]
            return fn
        with mock.patch.object(s, "PROVIDERS", (("pixabay", fake("pixabay")), ("pexels", fake("pexels")), ("openverse", fake("openverse")))), \
                mock.patch.dict(os.environ, {"PIXABAY_API_KEY": "k1", "PEXELS_API_KEY": "your-pexels-key"}):
            first, nxt = s.search("wooden plank", count=10)
            self.assertEqual(len(first), 10)
            # Pixabay and Openverse mixed; a template value ("your-pexels-key") is no key
            self.assertEqual({p["provider"] for p in first}, {"pixabay", "openverse"})
            more, _ = s.search("wooden plank", count=5, page=nxt, seen=[p["id"] for p in first])
            self.assertEqual(len(more), 5)
            self.assertFalse({p["id"] for p in more} & {p["id"] for p in first})

    def test_openverse_keeps_only_reusable_licences(self):
        import image_search_service as s

        def item(i, lic):
            return {"id": f"x{i}", "license": lic, "license_version": "2.0", "creator": "C", "source": "flickr",
                    "thumbnail": f"https://api.openverse.org/v1/images/x{i}/thumb/", "foreign_landing_url": "https://f"}
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"results": [item(1, "by"), item(2, "by-nd"), item(3, "cc0"), item(4, "by-nc"),
                                              item(5, "by-sa"), item(6, "pdm")]}
        with mock.patch.object(s, "_get", return_value=fake):
            got = s._openverse("plank", 1)
        self.assertEqual([g["license"] for g in got], ["CC BY 2.0", "CC0", "CC BY-SA 2.0", "Public Domain"])
        self.assertTrue(all(g["url"].startswith("https://api.openverse.org/") and g["url"].endswith("?full_size=true")
                            for g in got))
        self.assertEqual(got[0]["provider"], "Openverse (Flickr)")

    def test_import_needs_sku_edit(self):
        ex = self.role_user("executive", "vsexec")
        r = self.send(ex, "POST", "/api/vision/photos/import", {"sku_id": "GLS-FLT-04MM", "items": [{"url": "https://cdn.pixabay.com/x.jpg"}]})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.get(ex, "/api/vision/photos/search?q=plank").status_code, 403)


class TestFrontendWiring(unittest.TestCase):
    def test_tabs_and_dialog_hooks(self):
        html = open(os.path.join(ROOT, "webapp", "templates", "index.html"), encoding="utf-8").read()
        for needle in ('id="avTabs"', 'data-avpane="studio"', 'data-avpane="weight"', "skuModalFindPhotos()",
                       "skuImagesFindPhotos()", "js/vision_studio.js", 'class="glass-panel av-products"'):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
