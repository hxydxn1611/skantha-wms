"""
Writes docs/rbac_route_map.csv: every route, its methods, and the permission each
method needs (RBAC plan, "Backend enforcement"). Generated from the live url_map and
webapp/rbac_routes.py so the review copy can never drift from the code.

  py -3.14 scripts/rbac_route_map.py
"""
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
OUT = os.path.join(ROOT, "docs", "rbac_route_map.csv")


def build_rows(url_map):
    import rbac_catalog
    import rbac_routes
    rows = []
    for rule in sorted(url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        if rule.endpoint == "static":
            continue
        for method in sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")):
            if rule.endpoint in rbac_routes.PUBLIC_ENDPOINTS:
                key, access = "", "public"
            elif rule.endpoint in rbac_routes.AUTHENTICATED_ENDPOINTS:
                key, access = "", "any signed-in user"
            else:
                key = rbac_routes.permission_for(rule.endpoint, method) or "UNMAPPED"
                access = "permission"
            spec = rbac_catalog.PERMISSIONS_BY_KEY.get(rbac_routes.permission_keys(key)[0] if key else key)
            rows.append({
                "rule": rule.rule, "method": method, "endpoint": rule.endpoint, "access": access,
                "permission": key, "module": spec.module if spec else "",
                "scope": spec.scope_level if spec else "",
                "sensitive": "yes" if spec and spec.sensitive else "",
                "reason_required": "yes" if rule.endpoint in rbac_routes.REASON_REQUIRED_ENDPOINTS
                                   and method not in ("GET", "HEAD") else "",
            })
    return rows


def render_csv(rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main() -> int:
    import shutil
    import sqlite3
    import tempfile
    tmp = tempfile.mkdtemp(prefix="warlog_routemap_")
    live = os.path.join(WEBAPP, "skandha_wms.db")
    copy = os.path.join(tmp, "routemap.db")
    s = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    d = sqlite3.connect(copy)
    s.backup(d)
    d.close()
    s.close()
    os.environ["WARLOG_DB_PATH"] = copy
    os.environ.setdefault("WARLOG_SKIP_MIGRATION_BACKUP", "1")
    sys.path.insert(0, WEBAPP)
    os.chdir(WEBAPP)
    import app as app_module
    rows = build_rows(app_module.app.url_map)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write(render_csv(rows))
    print(f"{len(rows)} route/method rows written to {OUT}")
    shutil.rmtree(tmp, ignore_errors=True)
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
