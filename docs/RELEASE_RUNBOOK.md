# WARLOG RBAC release runbook (Phase 8)

Everything here was rehearsed on copies of the production database before release
(`scripts/rbac_rehearsal.py`). Commands assume the repository root `D:\skantha-wms` and
`py -3.14`.

## 1. Before switching anything on

1. Full tests: `py -3.14 scripts/run_tests_safely.py`
   (only the old `test_glass_multiview` test_01 may fail; it predates RBAC).
2. Browser check per role (enforce mode, copy of the DB): `py -3.14 scripts/rbac_ui_pass.py`
3. Rehearsal (migration + restore + rollback on copies): `py -3.14 scripts/rbac_rehearsal.py`
4. Read the "would have been blocked" report: `py -3.14 scripts/rbac_enforce_review.py`
   Every line is something audit mode logged but let through. Each one must be either
   expected (the person really shouldn't do it) or fixed (give the role the permission)
   before enforce.

## 2. Switch to full blocking (enforce)

1. In `.env`: `RBAC_MODE=enforce`
2. Restart the server (stop it, then `py -3.14 run_production.py`).
3. Sign in as a Company Admin and as one role user; open each screen they use.

**Instant rollback:** set `RBAC_MODE=audit` (log only) or `RBAC_MODE=off` and restart.
No data changes; nothing to restore.

## 3. HTTPS (H8)

1. Install Caddy; use `deploy/Caddyfile` (instructions inside).
2. In `.env`: `HOST=127.0.0.1`, `BEHIND_TLS_PROXY=1`, `APP_BASE_URL=https://<address>/`
3. Restart WARLOG, then `caddy run --config deploy/Caddyfile`.
4. Check: `https://<address>/login` opens; the session cookie is marked Secure.

**Rollback:** remove `BEHIND_TLS_PROXY`, set `HOST=0.0.0.0`, restart; stop Caddy.

## 4. Camera RTMP port (H7)

The stream-key gate protects port 1935. Also limit the port to the camera subnet
(Windows, admin PowerShell; adjust the subnet):

    netsh advfirewall firewall add rule name="WARLOG RTMP cameras" dir=in action=allow protocol=TCP localport=1935 remoteip=192.168.1.0/24
    netsh advfirewall firewall add rule name="WARLOG RTMP block others" dir=in action=block protocol=TCP localport=1935

Cameras push to the address shown in Camera Junction (it contains the key). To change the
key, set `RTMP_STREAM_KEY=` in `.env` and restart, then update every camera.

## 5. Roll back the code

Every phase has a git tag (`rbac-phase0` ... `rbac-phase8`). An earlier RBAC tag ignores
the columns and tables later phases added, so the database stays as it is:

    git checkout rbac-phase7
    py -3.14 run_production.py

Return: `git checkout feature/rbac`. (Rehearsed: rbac-phase7 serves today's database.)

Going back to the code from **before RBAC** (`main`) also needs the pre-RBAC database:
that code can't read the hashed passwords. Restore the Phase 0 baseline snapshot
(`backups\baseline_20261117_103855\skandha_wms.snapshot.db`) with section 6 - anything
entered since then is lost, so this is a last resort. (Rehearsed: `main` serves the
restored pre-RBAC copy.)

## 6. Restore the database from a backup

Backups are written automatically before every migration step into `backups\`
(`pre_rbac_v1_<date>_<time>.db`, readable only by this Windows user).

1. Stop the server.
2. Keep the current file: `copy webapp\skandha_wms.db webapp\skandha_wms.db.before_restore`
3. Restore: `py -3.14 scripts/rbac_restore.py backups\pre_rbac_v1_<date>_<time>.db`
   (checks the backup's integrity, copies it in with SQLite's backup API, removes stale
   `-wal`/`-shm` files).
4. Start the server. Migrations re-apply only what the backup is missing (with a new backup).

## 7. Sign-off checklist

- [ ] Tests, browser check and rehearsal pass
- [ ] Enforce-review report read; every entry expected or fixed
- [ ] `RBAC_MODE=enforce` set, server restarted, spot-checked
- [ ] HTTPS in front (or consciously deferred)
- [ ] RTMP firewall rule (or ffmpeg not installed)
- [ ] Leaked Gmail app password revoked; new SMTP settings in `.env`
