"""
Console-only account recovery (RBAC plan H23). Needs access to the server's files;
there is no web route for any of this. Every action is written to audit_logs.

  Reset a password (prompts twice, nothing is echoed):
      py -3.14 scripts/rbac_recover.py reset --username admin
  Issue a one-time temporary password (must be changed at next login):
      py -3.14 scripts/rbac_recover.py reset --username admin --temporary
  Unlock and reactivate an account, and make it Platform Admin:
      py -3.14 scripts/rbac_recover.py reset --username admin --temporary --make-platform-admin
  Fresh install: create the first Platform Admin and its company:
      py -3.14 scripts/rbac_recover.py create --username owner --company "Skantha Industrial Solutions" --email you@example.com

Uses WARLOG_DB_PATH when set, otherwise webapp/skandha_wms.db.
"""
import argparse
import getpass
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import db  # noqa: E402
import rbac_migration  # noqa: E402
import auth_service  # noqa: E402


def _ask_password(username: str, company: str = "") -> str:
    while True:
        first = getpass.getpass("New password: ").strip()
        second = getpass.getpass("Repeat new password: ").strip()
        if first != second:
            print("The two passwords do not match. Try again.")
            continue
        err = auth_service.validate_new_password(first, username, company)
        if err:
            print(err)
            continue
        return first


def _temporary_password() -> str:
    return secrets.token_urlsafe(12)


def cmd_reset(args) -> int:
    user = auth_service.find_user(args.username)
    if not user:
        print(f"No user called {args.username!r}.")
        return 1
    password = _temporary_password() if args.temporary else _ask_password(user["username"], user.get("company_name") or "")
    conn = db.get_db()
    try:
        with conn:
            conn.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user["id"],))
            if args.make_platform_admin:
                conn.execute("UPDATE users SET is_platform_admin = 1 WHERE id = ?", (user["id"],))
            # A successful marker ends any lockout window for this username.
            conn.execute("INSERT INTO login_attempts (username_key, ip, success, reason) VALUES (?, 'console', 1, 'recovery')",
                         (auth_service.username_key(user["username"]),))
    finally:
        conn.close()
    auth_service.set_password(user["id"], password, clear_reset_flag=not args.temporary,
                              actor={"id": None, "username": "console"}, action="auth.recovery", ip="console")
    if args.temporary:
        conn = db.get_db()
        try:
            with conn:
                conn.execute("UPDATE users SET must_reset_password = 1 WHERE id = ?", (user["id"],))
        finally:
            conn.close()
        print(f"Temporary password for {user['username']}: {password}")
        print("It must be changed at the next sign-in. It is not stored anywhere else.")
    else:
        print(f"Password for {user['username']} updated. All existing sessions were signed out.")
    return 0


def cmd_create(args) -> int:
    if db.get_user_id_by_username(args.username):
        print(f"A user called {args.username!r} already exists. Use 'reset' instead.")
        return 1
    password = _temporary_password()
    if not db.create_user(args.username, password, email=args.email, company_name=args.company,
                          assigned_warehouse_code=None, role="Admin"):
        print("Could not create the user.")
        return 1
    user = auth_service.find_user(args.username)
    conn = db.get_db()
    try:
        with conn:
            company_id = rbac_migration.ensure_company(conn, args.company)
            conn.execute("UPDATE companies SET is_platform_owner = 1 WHERE id = ?", (company_id,))
            rbac_migration.assign_company_admin(conn, user["id"], company_id)
            conn.execute("UPDATE users SET is_platform_admin = 1, must_reset_password = 1 WHERE id = ?", (user["id"],))
    finally:
        conn.close()
    auth_service.audit("auth.recovery", actor_username="console", resource_type="user",
                       resource_id=str(user["id"]), reason="first platform admin created", ip="console")
    print(f"Created Platform Admin {args.username} for {args.company}.")
    print(f"Temporary password: {password}")
    print("It must be changed at the first sign-in. It is not stored anywhere else.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset", help="reset a password, unlock and reactivate an account")
    r.add_argument("--username", required=True)
    r.add_argument("--temporary", action="store_true", help="issue a one-time temporary password")
    r.add_argument("--make-platform-admin", action="store_true")
    c = sub.add_parser("create", help="create the first Platform Admin (fresh install)")
    c.add_argument("--username", required=True)
    c.add_argument("--company", required=True)
    c.add_argument("--email")
    args = ap.parse_args()
    rbac_migration.migrate(db.DB_PATH)
    return cmd_reset(args) if args.cmd == "reset" else cmd_create(args)


if __name__ == "__main__":
    sys.exit(main())
