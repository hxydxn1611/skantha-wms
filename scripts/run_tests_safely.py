"""
Runs the full test suite and proves nothing live was damaged.

  py -3.14 scripts/run_tests_safely.py [extra unittest args]

* The live database is never used: tests/__init__.py points the app at a private copy.
  This script hashes the live DB (and its WAL file) before and after to prove it.
* Some existing tests write previews and labels into webapp/static (uploads, invoices,
  manifests), and the vision counting service prunes old preview images there
  (it keeps the newest 20). To protect existing files, those folders are copied before
  the run; afterwards every file that was deleted or changed is restored. Files the
  run created are left in place (never deleted), since the live server may write there too.

Always run tests through this script. Exit code is non-zero if a test fails, the live
DB changed, or a live file could not be restored.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
LIVE = os.path.join(WEBAPP, "skandha_wms.db")
GUARDED_DIRS = [os.path.join(WEBAPP, "static", d) for d in ("uploads", "invoices", "manifests")]


def digest(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def db_snapshot():
    return {p: digest(p) for p in (LIVE, LIVE + "-wal")}


def file_index(base):
    out = {}
    for root, _, files in os.walk(base):
        for f in files:
            p = os.path.join(root, f)
            st = os.stat(p)
            out[os.path.relpath(p, base)] = (st.st_size, st.st_mtime_ns)
    return out


def main():
    guard_dir = tempfile.mkdtemp(prefix="warlog_static_guard_")
    before_index = {}
    for d in GUARDED_DIRS:
        if os.path.isdir(d):
            shutil.copytree(d, os.path.join(guard_dir, os.path.basename(d)))
            before_index[d] = file_index(d)

    before = db_snapshot()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."] + sys.argv[1:]
    try:
        result = subprocess.run(cmd, cwd=ROOT, env=env)
    finally:
        restored, failed, created = 0, 0, 0
        for d, index in before_index.items():
            now = file_index(d) if os.path.isdir(d) else {}
            created += len(set(now) - set(index))
            for rel, meta in index.items():
                if now.get(rel) != meta:
                    src = os.path.join(guard_dir, os.path.basename(d), rel)
                    dst = os.path.join(d, rel)
                    try:
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        restored += 1
                    except OSError as e:
                        failed += 1
                        print(f"[run_tests_safely] could not restore {dst}: {e}")
        shutil.rmtree(guard_dir, ignore_errors=True)

    after = db_snapshot()
    untouched = before == after
    print("\n[run_tests_safely] live DB sha256 before:", before[LIVE])
    print("[run_tests_safely] live DB sha256 after: ", after[LIVE])
    print("[run_tests_safely] live DB untouched:", "YES" if untouched else "NO - INVESTIGATE")
    print(f"[run_tests_safely] live static files: {restored} restored after the run, "
          f"{failed} could not be restored, {created} new files left in place")
    return 0 if (result.returncode == 0 and untouched and failed == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
