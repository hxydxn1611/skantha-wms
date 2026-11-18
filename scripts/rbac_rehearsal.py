"""
RBAC Phase 8 release rehearsal - on COPIES only (the live database is never opened for writing).

  py -3.14 scripts/rbac_rehearsal.py

A. Migration rehearsal: the pre-RBAC copy (Phase 0 baseline snapshot) is migrated through
   every step, the ownership approval is recorded (--keep-live, as in production), and the
   migration runs once more to prove it changes nothing. Row counts of every existing table
   must be unchanged; integrity and foreign keys OK; every user has a hashed password;
   every company has its starter roles; the automatic pre-migration backup is valid.
B. Restore rehearsal: the newest automatic backup is restored into a scratch file with
   scripts/rbac_restore.py's routine; integrity and row counts must match the backup.
C. Rollback rehearsal: the previous release (git tag rbac-phase7) is checked out into a temp
   worktree and serves a copy of today's database: admin and david read 10 screens each.
   The pre-RBAC code (main) serves the restored pre-RBAC backup the same way.
Writes backups/rehearsal_report_<date>.json and exits 0 when everything passed.
"""
import datetime
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "webapp"))
LIVE = os.path.join(ROOT, "webapp", "skandha_wms.db")
BASELINE_PTR = os.path.join(ROOT, "backups", "LATEST_BASELINE")
TMP = tempfile.mkdtemp(prefix="warlog_rehearsal_")
os.environ.update({"WARLOG_SKIP_DOTENV": "1", "WARLOG_BACKUP_DIR": os.path.join(TMP, "backups")})

report = {"started": datetime.datetime.now().isoformat(timespec="seconds"), "checks": {}}
failed = []


def check(name, ok, detail=None):
    report["checks"][name] = {"ok": bool(ok), "detail": detail}
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail not in (None, '') else ""))
    if not ok:
        failed.append(name)


def copy_db(src, dst):
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    return dst


def counts(path, tables=None):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = tables or [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in names}
    finally:
        c.close()


def db_checks(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("PRAGMA integrity_check").fetchone()[0], c.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        c.close()


# ----------------------------------------------------------------------------- A. migration
print("A. Migration rehearsal on the pre-RBAC copy")
baseline_dir = open(BASELINE_PTR, encoding="utf-8").read().strip()
pre = copy_db(os.path.join(baseline_dir, "skandha_wms.snapshot.db"), os.path.join(TMP, "pre_rbac.db"))
before = counts(pre)
import rbac_migration  # noqa: E402
import rbac_ownership  # noqa: E402

r1 = rbac_migration.migrate(pre)
conn = sqlite3.connect(pre)
with conn:
    rbac_ownership.approve(conn, approved_by="release rehearsal", mark_demo=False)
conn.close()
r2 = rbac_migration.migrate(pre)
r3 = rbac_migration.migrate(pre)
steps = [n for n, _ in rbac_migration.STEPS]
applied = r1["applied"] + r2["applied"]
check("all migration steps applied", applied == steps, f"{len(applied)}/{len(steps)} steps")
check("a second run changes nothing", r3["applied"] == [])
after = counts(pre, list(before))
changed = {t: (before[t], after[t]) for t in before if before[t] != after[t] and t != "email_otps"}
check("row counts of every existing table unchanged", not changed, changed or f"{len(before)} tables")
ok, fks = db_checks(pre)
check("integrity and foreign keys", ok == "ok" and not fks, ok if ok != "ok" else (fks[:3] or None))
c = sqlite3.connect(pre)
unhashed = c.execute("SELECT COUNT(*) FROM users WHERE COALESCE(password_hash, '') = '' OR COALESCE(password, '') != ''").fetchone()[0]
check("every user has a hashed password and no plain-text one", unhashed == 0, f"{c.execute('SELECT COUNT(*) FROM users').fetchone()[0]} users")
no_roles = c.execute("""SELECT name FROM companies co WHERE (SELECT COUNT(*) FROM roles r WHERE r.company_id = co.id
                        AND r.template_key IS NOT NULL) < 8""").fetchall()
check("every company has its 8 starter roles", not no_roles, [r[0] for r in no_roles] or None)
import rbac_scope  # noqa: E402
null_owned = {t: c.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id IS NULL").fetchone()[0] for t in rbac_scope.SCOPED_TABLES}
null_owned = {t: n for t, n in null_owned.items() if n}
check("ownership backfill left no row without an owner", not null_owned, null_owned or None)
c.close()
backups = glob.glob(os.path.join(TMP, "backups", "pre_rbac_v1_*.db"))
check("automatic pre-migration backup written and valid", backups and all(db_checks(b)[0] == "ok" for b in backups),
      f"{len(backups)} backup(s)")

# ----------------------------------------------------------------------------- B. restore
print("B. Restore rehearsal")
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("rbac_restore", os.path.join(ROOT, "scripts", "rbac_restore.py"))
rbac_restore = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rbac_restore)

newest = max(glob.glob(os.path.join(ROOT, "backups", "pre_rbac_v1_*.db")), key=os.path.getmtime)
target = os.path.join(TMP, "restored.db")
rbac_restore.restore(newest, target, keep_current=False)
check("backup restored with integrity ok", db_checks(target)[0] == "ok", os.path.basename(newest))
check("restored row counts match the backup", counts(target) == counts(newest))
r4 = rbac_migration.migrate(target)
check("migrations re-apply cleanly on the restored copy", db_checks(target)[0] == "ok", f"applied: {r4['applied'] or 'nothing'}")

# ----------------------------------------------------------------------------- C. rollback
print("C. Rollback rehearsal (previous release and pre-RBAC code)")


def worktree(ref):
    path = os.path.join(TMP, "wt_" + ref.replace("/", "_"))
    subprocess.run(["git", "-C", ROOT, "worktree", "add", "--detach", path, ref], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def child(repo, db, mode):
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "_rehearse_child.py"), repo, db, mode],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    line = next((x for x in proc.stdout.splitlines() if x.startswith("REHEARSAL_RESULT ")), None)
    return json.loads(line[len("REHEARSAL_RESULT "):]) if line else {"ok": False, "error": (proc.stderr or "")[-400:]}


trees = []
try:
    wt7 = worktree("rbac-phase7")
    trees.append(wt7)
    today = copy_db(LIVE, os.path.join(TMP, "today.db"))
    res = child(wt7, today, "rbac")
    bad = {k: v for k, v in res.get("screens", {}).items() if v != 200}
    check("previous release (rbac-phase7) serves today's database", res.get("ok"), res.get("error") or bad or "20 screens 200")

    wtm = worktree("main")
    trees.append(wtm)
    legacy_db = os.path.join(wtm, "webapp", "skandha_wms.db")   # pre-RBAC code has a fixed path
    pre_backup = min(glob.glob(os.path.join(ROOT, "backups", "pre_rbac_v1_*.db")), key=os.path.getmtime)
    rbac_restore.restore(os.path.join(baseline_dir, "skandha_wms.snapshot.db"), legacy_db, keep_current=False)
    res = child(wtm, legacy_db, "legacy")
    bad = {k: v for k, v in res.get("screens", {}).items() if v != 200}
    check("pre-RBAC code (main) serves the restored pre-RBAC copy", res.get("ok"), res.get("error") or bad or "10 screens 200")
finally:
    for t in trees:
        subprocess.run(["git", "-C", ROOT, "worktree", "remove", "--force", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", ROOT, "worktree", "prune"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

report["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
report["passed"] = not failed
out = os.path.join(ROOT, "backups", f"rehearsal_report_{datetime.date.today():%Y%m%d}.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=1)
print(f"\nRESULT: {'PASS' if not failed else 'FAIL'}  ({len(report['checks']) - len(failed)}/{len(report['checks'])} checks)")
print("report:", out)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
