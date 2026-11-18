"""
Restore the WARLOG database from a backup (RBAC Phase 8 runbook, section 6).

  py -3.14 scripts/rbac_restore.py <backup.db> [--target webapp/skandha_wms.db] [--force]

* Refuses while the server answers on http://127.0.0.1:5000 (stop it first), unless --force.
* Checks the backup with PRAGMA integrity_check before touching anything.
* Keeps the current file as <target>.before_restore_<time>.
* Copies with SQLite's backup API and removes stale -wal / -shm files of the target.
"""
import argparse
import datetime
import os
import shutil
import sqlite3
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TARGET = os.path.join(ROOT, "webapp", "skandha_wms.db")


def server_running(url="http://127.0.0.1:5000/login") -> bool:
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


def integrity(path: str) -> str:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return c.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        c.close()


def restore(backup: str, target: str = DEFAULT_TARGET, keep_current: bool = True) -> dict:
    if not os.path.exists(backup):
        raise FileNotFoundError(backup)
    ok = integrity(backup)
    if ok != "ok":
        raise RuntimeError(f"backup failed its integrity check: {ok}")
    kept = None
    if keep_current and os.path.exists(target):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        kept = f"{target}.before_restore_{stamp}"
        src = sqlite3.connect(target)
        dst = sqlite3.connect(kept)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    for suffix in ("-wal", "-shm"):
        if os.path.exists(target + suffix):
            os.remove(target + suffix)
    src = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    after = integrity(target)
    if after != "ok":
        raise RuntimeError(f"restored database failed its integrity check: {after}")
    return {"restored_from": backup, "target": target, "previous_kept_as": kept}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backup")
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--force", action="store_true", help="restore even though the server seems to be running")
    args = ap.parse_args()
    if os.path.abspath(args.target) == os.path.abspath(DEFAULT_TARGET) and server_running() and not args.force:
        print("The WARLOG server is running. Stop it first (or use --force).")
        return 2
    out = restore(args.backup, args.target)
    print("Restored. Integrity: ok")
    for k, v in out.items():
        print(f"  {k}: {v}")
    print("Start the server; migrations re-apply only what the backup is missing (with a new backup first).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
