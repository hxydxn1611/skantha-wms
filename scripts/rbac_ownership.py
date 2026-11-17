"""
Ownership of existing data (RBAC Phase 3A): dry run, then approval.

  py -3.14 scripts/rbac_ownership.py propose
      Read-only. Works on a private copy of the live database and writes the full proposal
      (every row, its owner and the evidence) to backups/rbac_ownership_proposal.json.

  py -3.14 scripts/rbac_ownership.py approve --by "<your name>"
      Records the approval in the live database (table rbac_ownership_approval). Nothing else
      is changed now: the next server start applies it (migration step 007, which backs the
      database up first) and switches data isolation on.

Uses WARLOG_DB_PATH when set, otherwise webapp/skandha_wms.db.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "webapp"))
os.environ.setdefault("WARLOG_SKIP_DOTENV", "1")

import db  # noqa: E402
import rbac_migration  # noqa: E402
import rbac_ownership  # noqa: E402


def _private_copy() -> str:
    tmp = tempfile.mkdtemp(prefix="warlog_ownership_")
    dst = os.path.join(tmp, "copy.db")
    src = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def cmd_propose(_args) -> int:
    copy = _private_copy()
    try:
        os.environ["WARLOG_SKIP_MIGRATION_BACKUP"] = "1"
        rbac_migration.migrate(copy)  # schema steps on the copy only
        conn = sqlite3.connect(copy)
        try:
            proposal = rbac_ownership.propose(conn)
        finally:
            conn.close()
    finally:
        shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
    out = os.path.join(ROOT, "backups", "rbac_ownership_proposal.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(proposal, fh, indent=1, sort_keys=True)
    print("Proposed ownership (nothing has been written):")
    for line in rbac_ownership.summarize(proposal):
        print("  " + line)
    print(f"Full proposal with evidence per row: {out}")
    return 0


def cmd_approve(args) -> int:
    conn = sqlite3.connect(db.DB_PATH, timeout=30)
    try:
        with conn:
            rbac_migration.migrate(db.DB_PATH)  # makes sure the ownership columns exist
            proposal = rbac_ownership.approve(conn, approved_by=args.by)
    finally:
        conn.close()
    print("Approved. The next server start applies this ownership and switches data isolation on:")
    for line in rbac_ownership.summarize(proposal):
        print("  " + line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("propose")
    a = sub.add_parser("approve")
    a.add_argument("--by", required=True)
    args = ap.parse_args()
    return {"propose": cmd_propose, "approve": cmd_approve}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
