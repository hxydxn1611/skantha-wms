"""
Admin parity test (RBAC preservation guarantee, items 1-2).

Replays the Phase 0 baseline with the CURRENT code:
  * the baseline DB snapshot is copied and the current app is started on the copy
  * the same ~50 GET endpoints are called as `admin`
  * responses must match the baseline (clock-driven values and RBAC-added keys ignored)
  * every baseline table keeps its rows and values (baseline columns only)
  * every baseline file under static/uploads|invoices|manifests still exists unchanged

Skipped when no baseline exists on this machine (backups/LATEST_BASELINE).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import rbac_snapshot as snap  # noqa: E402

POINTER = os.path.join(ROOT, "backups", "LATEST_BASELINE")


def _baseline_dir():
    if not os.path.exists(POINTER):
        return None
    with open(POINTER, encoding="utf-8") as fh:
        d = fh.read().strip()
    return d if os.path.isdir(d) else None


@unittest.skipUnless(_baseline_dir(), "no RBAC baseline on this machine (run scripts/rbac_snapshot.py baseline)")
class TestAdminParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = _baseline_dir()
        def load(name):
            with open(os.path.join(cls.base, name), encoding="utf-8") as fh:
                return json.load(fh)
        cls.base_api, cls.base_tables, cls.base_files = load("api.json"), load("tables.json"), load("files.json")
        cls._tmp = tempfile.mkdtemp(prefix="warlog_parity_")
        cls.work_db = os.path.join(cls._tmp, "parity.db")
        snap.copy_db(os.path.join(cls.base, "skandha_wms.snapshot.db"), cls.work_db)
        cls.current_api = snap.api_snapshot(cls.work_db, os.path.join(cls._tmp, "api_now.json"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_admin_sees_the_same_api_responses(self):
        diffs = snap.compare_api(self.base_api, self.current_api)
        self.assertEqual(diffs, [], "\n".join(diffs))

    def test_existing_rows_and_values_are_unchanged(self):
        # Both sides are fingerprinted the same way (baseline columns, minus the documented
        # deliberate changes in rbac_snapshot.PARITY_EXCLUDED_*), so only real changes show.
        cols = {t: v["columns"] for t, v in self.base_tables.items()}
        snapshot_db = os.path.join(self.base, "skandha_wms.snapshot.db")
        base = snap.table_fingerprints(snapshot_db, columns_by_table=cols,
                                       ignore_columns=snap.PARITY_EXCLUDED_COLUMNS)
        now = snap.table_fingerprints(self.work_db, columns_by_table=cols,
                                      ignore_columns=snap.PARITY_EXCLUDED_COLUMNS)
        changed = [f"{t}: {base[t]['count']} rows -> {now.get(t, {}).get('count')}"
                   for t in base if t not in snap.PARITY_EXCLUDED_TABLES
                   and (t not in now or now[t]["sha256"] != base[t]["sha256"])]
        self.assertEqual(changed, [], "\n".join(changed))

    def test_existing_files_are_unchanged(self):
        now = snap.file_hashes()
        missing = [p for p in self.base_files if p not in now]
        changed = [p for p in self.base_files if p in now and now[p] != self.base_files[p]]
        self.assertEqual(missing, [], f"{len(missing)} baseline files missing, e.g. {missing[:5]}")
        self.assertEqual(changed, [], f"{len(changed)} baseline files changed, e.g. {changed[:5]}")


if __name__ == "__main__":
    unittest.main()
