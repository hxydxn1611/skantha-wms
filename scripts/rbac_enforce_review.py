"""
Before switching RBAC_MODE to enforce: what would have been blocked? (read-only)

  py -3.14 scripts/rbac_enforce_review.py [days]

Audit mode lets every request through but logs 'access.would_deny' (missing permission),
'access.reason_missing' and 'security.csrf_missing'. This report groups them by person,
permission and screen/API so each line can be judged: expected (the person really shouldn't
do it) or a gap (give their role the permission) before enforce is switched on.
Opens the live database read-only.
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
db = os.path.join(ROOT, "webapp", "skandha_wms.db")
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
rows = c.execute("""
    SELECT a.action, COALESCE(a.actor_username, '-') AS who, COALESCE(co.name, '-') AS company,
           json_extract(a.after_json, '$.permission') AS permission,
           json_extract(a.after_json, '$.endpoint') AS endpoint,
           a.resource_id AS request, COUNT(*) AS n, MAX(a.ts) AS last_seen
    FROM audit_logs a LEFT JOIN companies co ON co.id = a.company_id
    WHERE a.action IN ('access.would_deny', 'access.reason_missing', 'security.csrf_missing')
      AND a.ts >= datetime('now', ?)
    GROUP BY a.action, who, permission, endpoint
    ORDER BY n DESC""", (f"-{days} days",)).fetchall()
users = {r[0]: r[1] for r in c.execute("SELECT username, is_platform_admin FROM users")}
c.close()

print(f"Would-be refusals in the last {days} days (audit mode let them through):\n")
if not rows:
    print("  none - switching to enforce changes nothing for what people did in this period.")
for r in rows:
    tag = {"access.would_deny": "NO PERMISSION", "access.reason_missing": "NO REASON",
           "security.csrf_missing": "NO CSRF TOKEN"}[r["action"]]
    print(f"  {r['n']:4d}x  {tag:14s} {r['who']:<14s} {r['company']:<28s} {r['permission'] or '':<28s} "
          f"{r['endpoint'] or ''}  (last {r['last_seen']})")
print("\nHow to read it: NO PERMISSION for a Company Admin or the Super Admin would be a bug "
      "(they hold everything); for a role user it is either intended or a permission to add to the role. "
      "NO CSRF TOKEN means a page or tool calling the API without the security token.")
