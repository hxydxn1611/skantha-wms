"""
Runs the full test suite and proves the live database was not touched.

  py -3.14 scripts/run_tests_safely.py [extra unittest args]

Exit code is non-zero if any test fails OR the live DB (or its WAL file) changed.
"""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "webapp", "skandha_wms.db")


def digest(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot():
    return {p: digest(p) for p in (LIVE, LIVE + "-wal")}


def main():
    before = snapshot()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."] + sys.argv[1:]
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    after = snapshot()
    untouched = before == after
    print("\n[run_tests_safely] live DB sha256 before:", before[LIVE])
    print("[run_tests_safely] live DB sha256 after: ", after[LIVE])
    print("[run_tests_safely] live DB untouched:", "YES" if untouched else "NO - INVESTIGATE")
    return 0 if (result.returncode == 0 and untouched) else 1


if __name__ == "__main__":
    sys.exit(main())
