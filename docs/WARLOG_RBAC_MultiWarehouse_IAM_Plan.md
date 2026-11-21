# WARLOG / Skantha WMS — Multi-Site Data Isolation, Dynamic Per-Warehouse RBAC & OTP IAM Blueprint

> **Audience:** Lead Developer, Technical Approvers, and AI Coding Agents working on this repository.  
> **Goal:** Implement enterprise **Multi-Company + Multi-State/Warehouse Data Isolation**, **Dynamic Per-Warehouse RBAC** (supporting 3 roles in compact yards up to 15–30+ roles in enterprise hubs), **Role-Scoped Dashboard & AI Copilot**, **Salted Password Hashing**, and **OTP Staff Onboarding with Forced First-Login Password Reset** — with **zero regression** to live 120 FPS camera streaming or sub-15ms Gate ANPR.

---

## 1. Approved Product & Security Rules

1. **Dashboard & WARLOG AI Copilot Access**:
   - Enabled by default for all roles (`dashboard:view`, `copilot:use`), **strictly filtered by active warehouse & user permissions**:
     - **Frontline / Custom Roles** see Dashboard widgets and Copilot answers **only for their authorized warehouse and allowed domains** (e.g., a Gate Operator can ask Copilot about trucks/gate passes at their site, while requests for restricted modules, other warehouses, or unauthorized actions are denied cleanly by Copilot & API).
     - **Company Admin (`*`)** sees complete cross-warehouse / multi-state analytics, KPIs, and full Copilot intelligence + actions across the entire company.
2. **Company Registration vs. Team Invites (`login.html`)**:
   - **New Company Self-Signup (Allowed):** A brand-new company name not yet present in WARLOG can register via OTP email verification, automatically provisioning the Company workspace, initial Warehouse, default roles, and making the registrant **Company Admin**.
   - **Existing Company Guard (Admin-Invite Only):** If someone tries to register under a **company name that already exists**, self-registration is blocked (`409 / invite_required`) with: *"This company workspace already exists. Please ask your Company Admin to send you a One-Time Password (OTP) invite for your warehouse and role."* Only an existing **Company Admin** can add warehouses or invite staff into that company.

---

## 2. Current Baseline & Verified Constraints

| Component | Current State | Risk / Gap to Solve |
| :--- | :--- | :--- |
| **Auth Gate** | `webapp/app.py` (`enforce_authentication_and_session()`, `@app.before_request`) checks only if `session['user']['username']` exists (binary logged-in vs. `401`/redirect). | No permission check on any endpoint; `/api/warehouses/switch` allows any logged-in user to switch any warehouse. |
| **Passwords** | `webapp/db.py` (`get_user()`, `create_user()`) stores and compares **plaintext** strings (`AND password = ?`). Seed user is `admin` / `admin`. | Plaintext credentials in `skandha_wms.db`; must migrate smoothly without locking out `admin` or existing accounts. |
| **Multi-Warehouse State** | `webapp/db.py` `warehouses` table has `(code, name, city, operating_mode, industry, address, status, is_active, company_name)`. `set_active_warehouse()` flips a **global** `is_active = 1` row in SQLite. | No `state` / region column; concurrent sessions in two different warehouses overwrite each other's active warehouse. |
| **Data Isolation** | Core operational tables (`expected_deliveries`, `bins`, `inventory`, `gate_passes`, `vehicle_log`, `outbound_orders`, `cameras`, `pallets`, `vision_zones`, `vision_counting_submissions`, `skus`) lack `warehouse_code` / `company_name` isolation. | Records from Warehouse A and Warehouse B share the same tables. |
| **Staging Service** | `webapp/staging_perception_service.py` (`get_staging_service()`) holds a single global `_STAGING_SERVICE` singleton. | Staging target, placement count, and active camera angle are global rather than per-warehouse. |
| **Copilot Service** | `webapp/copilot_service.py` queries warehouse DB stats/tables without session permission or active warehouse isolation. | Must scope context and block restricted data/actions per caller permissions. |
| **OTP Mailer** | `webapp/app.py` already provides `send_verification_email()`, `store_email_otp()`, `verify_email_otp()`, `/api/auth/send_otp`, and `email_otps` table in SQLite. | Reused for staff invite OTPs. Hardcoded Gmail fallback defaults in `app.py` (`send_verification_email` & `/api/gate/invoice`) should be moved strictly to env vars. |
| **UI Views** | `webapp/templates/index.html` contains **12 `.view-section` views**: `dashboard-view`, `inbound-flow-view`, `outbound-view`, `deliveries-view`, `cameras-view`, `gate-passes-view`, `docks-view`, `warehouses-view`, `master-hub-view`, `ai-vision-view`, `ai-vision-master-view`, `palletization-view` + AI Copilot. | All 12 views currently render regardless of user role. |

---

## 3. Hard Invariants (DO NOT BREAK)

Any developer or agent implementing this plan **MUST preserve** these behaviors:

1. **120 FPS Camera Streaming & HTTP/1.1 Connection Pool Protection**:
   - Do **not** alter lazy `data-stream-src` attributes in `webapp/templates/index.html` or `window.syncVisibleStreams()` in `webapp/static/js/app_logic.js` / `webapp/static/js/staging_perception.js`.
   - Do **not** remove the 4-slot concurrent MJPEG cap in `cameras-view` (prevents browser 6-connection HTTP/1.1 exhaustion).
   - Keep `VisionRuntimeManager` (`webapp/vision_runtime_service.py`) and `active_cameras` (`webapp/app.py`) running by `camera_id` in background threads; multi-warehouse isolation filters **API visibility & assignment**, never interrupting active capture/inference threads.
2. **Sub-15ms Gate ANPR Pipeline**:
   - Do **not** inject SQLite queries or RBAC/session lookups inside `_capture_loop()`, `_worker_loop()`, `_run_live_gate_anpr_worker()`, or `generate_frames()` inner frame loops. Tag metadata (`camera_id -> warehouse_code, company_name`) only at registration/lookup boundaries.
3. **Zero-Downtime Migration on Existing `skandha_wms.db`**:
   - Add every new column via idempotent `ALTER TABLE ... ADD COLUMN ... DEFAULT ...` inside `init_db()` (`webapp/db.py`) and backfill safely (`WH-MAIN` / `'Skantha Industrial Solutions'`).
4. **Admin Recovery Guarantee**:
   - Every company retains an active `Admin` role carrying wildcard `["*"]` permissions; system prevents revoking `["*"]` or deleting the last active Admin of a company.

---

## 4. Target Architecture: `Company → State → Warehouse → Role → Permissions`

**Backend routes, Copilot queries, and UI components NEVER check role names** (e.g., `"Gate Guard"` or `"Manager"`).  
- **WARLOG code checks fixed Permission Keys** (`gate:operate`, `cameras:install`, etc.).
- **Roles are dynamic SQLite records per warehouse** created/enabled by Company Admin.
- Therefore, **Warehouse A** can enable **3 roles** covering 100% of WARLOG, while **Warehouse B** enables **15–30 custom roles** covering 100% of WARLOG — **zero code changes needed**.

### Atomic Permission Catalog (~22 Keys)

| Domain | Permission Keys | Covers (Routes & UI Views) |
| :--- | :--- | :--- |
| **Overview & AI** | `dashboard:view`, `copilot:use` | Role-scoped `dashboard-view`, `/api/stats`, `/api/telemetry/live`, `/api/copilot/*` |
| **Pre-Registration** | `deliveries:view`, `deliveries:write` | `deliveries-view`, `GET/POST/PUT /api/deliveries*` |
| **Gate & Docks** | `gate:view`, `gate:operate`, `gate:override`, `docks:view`, `docks:manage` | `gate-passes-view`, `docks-view`, `/api/gate_passes*`, `/api/gate/*`, `/api/vehicle_log` |
| **Inbound & Staging** | `inbound_staging:view`, `inbound_staging:count`, `inbound_staging:config` | `inbound-flow-view`, `/api/inbound/*`, `/api/staging/*` |
| **Outbound** | `outbound:view`, `outbound:dispatch` | `outbound-view`, `/api/outbound/*` |
| **Palletization** | `pallet:view`, `pallet:operate` | `palletization-view`, `/api/pallets/*` |
| **Master Hub & Stock** | `inventory:view`, `inventory:write`, `inventory:audit` | `master-hub-view`, `/api/bins*`, `/api/skus*`, `/api/cycle_count*`, `/api/violations*` |
| **Cameras & Vision AI** | `cameras:view`, `cameras:install`, `cameras:calibrate`, `vision_ai:view`, `vision_ai:config` | `cameras-view`, `ai-vision-view`, `ai-vision-master-view`, `/api/cameras*`, `/api/vision/*`, `/api/workers/*`, `/api/object_classes*`, `/api/sku_master*` |
| **Admin & Safety** | `warehouses:manage`, `users_roles:manage`, `records:delete` | `warehouses-view`, `/api/warehouses*`, `/api/iam/*`, destructive `DELETE` routes & resets |

---

## 5. Phased Implementation Plan

### Phase 1 — Schema Extensions, Password Hashing & Session Scoping
**Target Files:** `webapp/db.py`, `webapp/app.py`

1. **Password Hashing (`werkzeug.security`)**:
   - `create_user()` stores salted hashes via `generate_password_hash()`.
   - `get_user(username, password)` checks `is_active == 1`:
     - If stored password starts with `scrypt:` or `pbkdf2:`, verify via `check_password_hash()`.
     - **Legacy seamless upgrade:** Otherwise match plaintext once (`admin`/`admin`), immediately `UPDATE users SET password = generate_password_hash(password)`, and log in.
   - Add to `users`: `must_reset_password INTEGER DEFAULT 0`, `is_active INTEGER DEFAULT 1`, `invited_by TEXT`, `last_login_at TIMESTAMP`.

2. **State & Multi-Site IAM Schema (`webapp/db.py`)**:
   - `ALTER TABLE warehouses ADD COLUMN state TEXT DEFAULT 'Karnataka'`

```sql
CREATE TABLE IF NOT EXISTS rbac_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    warehouse_code TEXT NOT NULL,          -- '*' for company template or specific WH code
    role_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    permissions_json TEXT NOT NULL,        -- JSON array e.g. ["*"] or ["gate:view","gate:operate"]
    is_system_admin INTEGER DEFAULT 0,
    is_enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_name, warehouse_code, role_name)
);

CREATE TABLE IF NOT EXISTS user_warehouse_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    company_name TEXT NOT NULL,
    warehouse_code TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    is_default INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Active',          -- Active | Suspended
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(username, warehouse_code),
    FOREIGN KEY(role_id) REFERENCES rbac_roles(id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    warehouse_code TEXT,
    username TEXT NOT NULL,
    role_name TEXT,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    details_json TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

3. **Default Role Packs & Coverage Helper**:
   - `seed_warehouse_roles(company_name, warehouse_code, preset="3_role")`:
     - **`3_role` (Compact / Default)**: `Admin` (`["*"]`), `Supervisor / Manager`, `Operator` (includes `dashboard:view` + `copilot:use`).
     - **`5_role` (Standard)**: `Admin`, `Site Manager`, `Gate Operator`, `Floor Operator`, `Viewer`.
     - **`15_role` (Enterprise Pack)**: `Admin`, `Site Manager`, `Shift Supervisor`, `Gate Security`, `Dock Marshal`, `Inbound Clerk`, `Staging Counter`, `Forklift / MHE Lead`, `Putaway Operator`, `Picking Lead`, `Outbound Dispatch`, `Inventory Controller`, `Cycle Count Auditor`, `CCTV / Vision Technician`, `Read-Only Auditor`.
   - `get_role_coverage(company_name, warehouse_code)` returns `{ total_permissions, covered_permissions, admin_only_permissions }` for the live UI **Coverage Meter**.

4. **Session-Isolated Warehouse Context**:
   - Store `active_warehouse_code`, `active_warehouse_state`, `company_name`, `role_name`, `permissions`, `must_reset_password`, and `authorized_warehouses` inside `session['user']`.
   - Stop mutating global `warehouses.is_active` across concurrent user sessions during login/switch.

---

### Phase 2 — `rbac_service.py` & Request Enforcement Layer
**Target Files:** `webapp/rbac_service.py` *(new)*, `webapp/app.py`

1. **Create `webapp/rbac_service.py`**:
   - Define `PERMISSION_CATALOG` (canonical dict of all ~22 permission keys + UI labels + domain grouping).
   - `get_request_scope()` → `(company_name, warehouse_code, username, role_name, permissions, is_admin)`.
   - `@require_permission(perm_key, write_action=False)` decorator:
     - Checks auth (`401`), forced password reset (`403 password_reset_required`), warehouse membership, warehouse operational status (`Maintenance` / `Read-Only` blocks non-Admin writes with `403`), and `has_permission(perm_key)` (`403 forbidden`).
   - `log_audit_event(action, resource_type, resource_id, details=None)`.

2. **Update `enforce_authentication_and_session()` in `webapp/app.py`**:
   - When `must_reset_password == 1`, allow ONLY `/api/auth/force_reset_password`, `/api/auth/me`, `/api/logout`, `/logout`, `/login`, `/static/*`; block all other `/api/*` with `403 { "error_code": "password_reset_required" }`.
   - Keep `/video_feed/*`, `/api/staging/feed.mjpg` fast-path streaming free of DB/RBAC locks.

3. **Guard Self-Registration Against Existing Companies (`app.py`)**:
   - In `/api/auth/send_otp`, `/api/auth/verify_otp_and_register`, and `/api/register`:
     - Normalize `company_name` and check if a company already exists in `warehouses` or `users`.
     - If it **exists**, reject public self-registration (`409 { "error_code": "company_exists_invite_required", "message": "This company workspace already exists. Ask your Company Admin to send you an OTP invite." }`).
     - If it is **new**, proceed and grant the registering user **Company Admin (`*`)** for that company.

---

### Phase 3 — Full Multi-Site Data Isolation & Scoped Copilot (`Option 2`)
**Target Files:** `webapp/db.py`, `webapp/app.py`, `webapp/staging_perception_service.py`, `webapp/copilot_service.py`

1. **Scoping Columns via `init_db()` Migrations (`webapp/db.py`)**:
   - **Per-Warehouse Isolation** *(add `company_name`, `warehouse_code DEFAULT 'WH-MAIN'` + indexes)*:
     - `cameras`, `vision_zones`, `vision_zone_cameras`, `vision_zone_camera_rois`
     - `bins`, `inventory`, `expected_deliveries`, `gate_passes`, `vehicle_log`, `invoices`
     - `outbound_orders`, `outbound_items`, `pallets`, `pallet_items`, `violations_log`, `vision_counting_submissions`
   - **Per-Company Shared Catalog** *(add `company_name` + indexes)*:
     - `skus`, `sku_images`, `object_classes`, `glass_measurement_profiles`

2. **Query Scoping & IDOR Prevention**:
   - Filter all list/aggregate queries by `(company_name, warehouse_code)` from `get_request_scope()`.
   - Verify record ownership before single-item `GET/PUT/DELETE` (`/api/deliveries/<po>`, `/api/bins/<id>`, `/api/cameras/<id>`, `/api/vision/cameras/<id>/config`, `/api/pallets/<id>`, `/api/gate/checkout`).
   - Tag newly added cameras with active `(company_name, warehouse_code)`; keep `VisionRuntimeManager` threads uninterrupted.

3. **Per-Warehouse Staging Perception (`webapp/staging_perception_service.py`)**:
   - Replace global `_STAGING_SERVICE` singleton with:
     ```python
     _STAGING_SERVICES: Dict[str, StagingPerceptionService] = {}
     def get_staging_service(warehouse_code: str = "WH-MAIN") -> StagingPerceptionService: ...
     ```

4. **Role-Scoped Dashboard & Role-Scoped AI Copilot (`webapp/app.py`, `webapp/copilot_service.py`)**:
   - `/api/stats` & `/api/telemetry/live`:
     - Admin sees aggregate metrics across authorized/selected company warehouses.
     - Non-Admin sees metrics strictly scoped to their active `warehouse_code`, with module widgets masked/omitted for domains outside their `permissions`.
   - `/api/copilot/chat` & `/api/copilot/action` (`copilot_service.py`):
     - Pass `scope = { company_name, warehouse_code, permissions, is_admin }` into Copilot intent handlers.
     - Restrict data context and tool actions strictly to `scope.permissions` and `scope.warehouse_code` (or multi-warehouse for Company Admin); return clear access notice when a user queries restricted modules or other facilities.

---

### Phase 4 — IAM Onboarding UI, Warehouse Picker & Dynamic Role Studio
**Target Files:** `webapp/app.py`, `webapp/templates/login.html`, `webapp/templates/index.html`, `webapp/static/js/app_logic.js`

1. **IAM & Role Endpoints (`webapp/app.py`)**:
   - `GET /api/auth/me` — active user, active warehouse `(code, name, state, status)`, authorized warehouses grouped by state, role, `permissions`.
   - `POST /api/auth/force_reset_password` — sets hashed password, clears `must_reset_password = 0`, logs audit event.
   - `GET /api/iam/permissions` — returns `PERMISSION_CATALOG`.
   - `GET/POST /api/iam/warehouses/<wh_code>/roles`, `PUT/DELETE /api/iam/roles/<role_id>` — preset apply (`3_role`, `5_role`, `15_role`), clone across warehouses, custom role CRUD + live Coverage Meter.
   - `GET/POST /api/iam/users`, `PATCH /api/iam/users/<username>` — Admin invites user with 1+ `(warehouse_code, role_id)` assignments, generates single-use hashed OTP (`must_reset_password = 1`), and emails it via `send_verification_email()`.
   - `GET /api/iam/audit_logs` — Admin-only filterable audit log viewer.
   - Harden `POST /api/warehouses/switch` — validates user membership inside same `company_name` (or Company Admin), refreshes session `warehouse_code`, `role_name`, and `permissions`.

2. **Login UX (`webapp/templates/login.html`)**:
   - Inline **"Set Personal Password"** modal when `must_reset_password == 1`.
   - **State → Warehouse Picker** when user has >1 authorized warehouses.
   - Clear redirect message when attempting to register under an already-existing company name.

3. **IAM Hub & Role-Aware Dashboard (`index.html`, `app_logic.js`)**:
   - Admin **"Users, Roles & Access"** panel: Role Preset / Custom Builder + live **WARLOG Coverage Meter**, OTP Staff Invite modal, Audit Log table.
   - Header **Warehouse Switcher** grouped by **State** (`Karnataka`, `Maharashtra`, etc.) + facility status badge.
   - UI `window.hasPerm(key)` gating on tabs, dashboard KPI cards, Copilot suggestions, and mutation/delete buttons.

---

## 6. Verification & Acceptance Criteria

1. **Legacy Upgrade**: `admin` / `admin` logs in (`200`), upgrades to salted hash automatically, `WH-MAIN` retains all existing cameras/bins/deliveries.
2. **Same-Company Guard & OTP Onboarding**:
   - Self-registering under an existing company returns `409 company_exists_invite_required`.
   - New company self-signup grants Company Admin (`*`).
   - Invited user logs in with OTP → locked to `403 password_reset_required` until `/api/auth/force_reset_password` succeeds → single-use OTP burned.
3. **Role-Scoped Dashboard & Copilot**:
   - Gate Operator's Copilot answers Gate Pass questions for their warehouse, refuses Inventory Audit / User Delete / other-warehouse queries; Admin Copilot sees all company facilities.
4. **3-Role vs 15-Role Full Coverage & Data Isolation**:
   - WH-A (`3_role`) and WH-B (`15_role`) both show 100% capability coverage via `get_role_coverage()`.
   - Concurrent sessions in WH-A vs WH-B see strictly isolated bins, deliveries, gate passes, staging counts, and cameras; Company B sees `0` records / `403` on Company A IDs.
5. **120 FPS Streaming & ANPR Integrity**:
   - `/video_feed/CAM-001` and `/api/staging/feed.mjpg` stream smoothly with `syncVisibleStreams()` intact.
