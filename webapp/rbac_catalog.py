"""
WARLOG permission catalogue (RBAC plan, "Permission catalogue").

Single source of truth for every permission key. Keys are `module.resource.action`
and are synced into the `permissions` table at startup (rbac_migration.sync_catalog).
Custom roles can only reference keys listed here. Keys removed from this file are
marked retired in the DB, never deleted.

Sensitive permissions are excluded from any template by default, and every use is
audited with a reason (enforced from Phase 2).
"""
from typing import Dict, List, NamedTuple, Optional


class Permission(NamedTuple):
    key: str
    module: str
    action: str          # View | Create | Edit | Delete | Approve | Reject | Execute | Override | Export | Configure | Manage
    label: str
    scope_level: str     # platform | company | warehouse
    sensitive: bool = False
    description: str = ""


ACTIONS = ("View", "Create", "Edit", "Delete", "Approve", "Reject", "Execute",
           "Override", "Export", "Configure", "Manage")

W, C, P = "warehouse", "company", "platform"


def _p(key: str, module: str, action: str, label: str, scope: str = W,
       sensitive: bool = False, description: str = "") -> Permission:
    return Permission(key, module, action, label, scope, sensitive, description)


PERMISSION_CATALOG: List[Permission] = [
    # ---------------------------------------------------------------- Gate and security (23)
    _p("gate.dashboard.view", "Gate", "View", "View gate dashboard and live gate activity"),
    _p("gate.pass.view", "Gate", "View", "View gate passes"),
    _p("gate.vehicle_log.view", "Gate", "View", "View vehicle entry and exit history"),
    _p("gate.vehicle.register", "Gate", "Create", "Register walk-in vehicles and create gate passes"),
    _p("gate.vehicle.edit", "Gate", "Edit", "Edit vehicle, driver and load details"),
    _p("gate.driver.view", "Gate", "View", "View driver phone numbers and photos"),
    _p("gate.anpr.execute", "Gate", "Execute", "Run number-plate scans and ANPR reads"),
    _p("gate.otp.send", "Gate", "Execute", "Generate and send driver OTPs"),
    _p("gate.otp.verify", "Gate", "Execute", "Verify a driver OTP"),
    _p("gate.otp.override", "Gate", "Override", "Mark an OTP verified without the code (reason required)", sensitive=True),
    _p("gate.entry.approve", "Gate", "Approve", "Approve vehicle entry"),
    _p("gate.entry.reject", "Gate", "Reject", "Reject vehicle entry"),
    _p("gate.entry.bulk_approve", "Gate", "Approve", "Approve all matched pending passes at once", sensitive=True),
    _p("gate.dock.admit", "Gate", "Execute", "Send an approved vehicle to a dock"),
    _p("gate.manual_admission.authorize", "Gate", "Override", "Admit a vehicle without pre-registration or OTP (reason required)", sensitive=True),
    _p("gate.exception.approve", "Gate", "Approve", "Approve or reject gate exceptions", sensitive=True),
    _p("gate.violation.view", "Gate", "View", "View gate violations"),
    _p("gate.violation.manage", "Gate", "Manage", "Resolve or dismiss gate violations"),
    _p("gate.checkout.approve", "Gate", "Approve", "Approve vehicle exit after unloading is reconciled"),
    _p("gate.checkout.complete", "Gate", "Execute", "Record the physical vehicle exit"),
    _p("gate.override.manual", "Gate", "Override", "Force a gate status change outside the normal flow (reason required)", sensitive=True),
    _p("gate.documents.export", "Gate", "Export", "View and download gate manifests and invoices"),
    _p("gate.devices.configure", "Gate", "Configure", "Configure gate cameras, ANPR and simulation tools", sensitive=True),

    # ---------------------------------------------------------------- Dashboard and reports (3)
    _p("dashboard.view", "Dashboard", "View", "View the dashboard and live statistics"),
    _p("reports.view", "Dashboard", "View", "View reports"),
    _p("reports.export", "Dashboard", "Export", "Export reports"),

    # ---------------------------------------------------------------- Pre-registration (4)
    _p("deliveries.view", "Pre-registration", "View", "View expected deliveries"),
    _p("deliveries.create", "Pre-registration", "Create", "Create expected deliveries"),
    _p("deliveries.edit", "Pre-registration", "Edit", "Edit expected deliveries"),
    _p("deliveries.delete", "Pre-registration", "Delete", "Delete expected deliveries"),

    # ---------------------------------------------------------------- Dock (3)
    _p("dock.view", "Dock", "View", "View docks and unloading status"),
    _p("dock.unload.execute", "Dock", "Execute", "Record unloading steps"),
    _p("dock.evidence.view", "Dock", "View", "View dock evidence and verification"),

    # ---------------------------------------------------------------- Inbound and GRN (5)
    _p("inbound.view", "Inbound", "View", "View inbound flow"),
    _p("inbound.receipt.complete", "Inbound", "Execute", "Complete goods receipts (GRN)"),
    _p("inbound.staging.view", "Inbound", "View", "View the staging area and its feeds"),
    _p("inbound.staging.configure", "Inbound", "Configure", "Configure staging perception"),
    _p("inbound.staging.reset", "Inbound", "Manage", "Reset staging sessions"),

    # ---------------------------------------------------------------- Bins and locations (4)
    _p("bins.view", "Locations", "View", "View bins and locations"),
    _p("bins.create", "Locations", "Create", "Create bins"),
    _p("bins.edit", "Locations", "Edit", "Edit bins"),
    _p("bins.delete", "Locations", "Delete", "Delete bins"),

    # ---------------------------------------------------------------- SKU and master data (6)
    _p("sku.view", "Master data", "View", "View SKUs and master data", C),
    _p("sku.create", "Master data", "Create", "Create SKUs", C),
    _p("sku.edit", "Master data", "Edit", "Edit SKUs, images and bundle settings", C),
    _p("sku.delete", "Master data", "Delete", "Delete SKUs", C),
    _p("sku.import", "Master data", "Manage", "Import SKUs from spreadsheets", C),
    _p("masterdata.blueprint.apply", "Master data", "Manage", "Apply an industry template", C, sensitive=True),

    # ---------------------------------------------------------------- Inventory (4)
    _p("inventory.view", "Inventory", "View", "View stock"),
    _p("inventory.adjust", "Inventory", "Manage", "Adjust stock quantities", sensitive=True),
    _p("inventory.transfer", "Inventory", "Execute", "Transfer stock between bins"),
    _p("inventory.export", "Inventory", "Export", "Export stock"),

    # ---------------------------------------------------------------- Cycle count (3)
    _p("cyclecount.view", "Cycle count", "View", "View cycle counts"),
    _p("cyclecount.execute", "Cycle count", "Execute", "Submit cycle counts"),
    _p("cyclecount.approve", "Cycle count", "Approve", "Approve cycle count results"),

    # ---------------------------------------------------------------- Outbound (3)
    _p("outbound.view", "Outbound", "View", "View outbound orders"),
    _p("outbound.create", "Outbound", "Create", "Create outbound orders"),
    _p("outbound.dispatch", "Outbound", "Execute", "Dispatch outbound orders"),

    # ---------------------------------------------------------------- Pallets (5)
    _p("pallet.view", "Pallets", "View", "View pallets"),
    _p("pallet.create", "Pallets", "Create", "Create pallets"),
    _p("pallet.seal", "Pallets", "Execute", "Seal pallets"),
    _p("pallet.transfer", "Pallets", "Execute", "Transfer pallets"),
    _p("pallet.delete", "Pallets", "Delete", "Delete pallets"),

    # ---------------------------------------------------------------- AI vision and tracking (4)
    _p("vision.view", "AI vision", "View", "View AI vision, detection and tracking"),
    _p("vision.counting.execute", "AI vision", "Execute", "Run vision counting"),
    _p("vision.counting.review", "AI vision", "Approve", "Review and confirm vision counts"),
    _p("vision.traceability.view", "AI vision", "View", "View material traceability"),

    # ---------------------------------------------------------------- Vision configuration (3)
    _p("vision.zones.manage", "Vision configuration", "Manage", "Manage vision zones and ROIs"),
    _p("vision.classes.manage", "Vision configuration", "Manage", "Manage object classes", C),
    _p("vision.runtime.configure", "Vision configuration", "Configure", "Configure the AI vision runtime", sensitive=True),

    # ---------------------------------------------------------------- Cameras (6)
    _p("cameras.view", "Cameras", "View", "View cameras"),
    _p("cameras.stream.view", "Cameras", "View", "Watch live camera streams"),
    _p("cameras.create", "Cameras", "Create", "Add cameras"),
    _p("cameras.configure", "Cameras", "Configure", "Configure cameras"),
    _p("cameras.ptz.control", "Cameras", "Execute", "Control camera pan, tilt and zoom"),
    _p("cameras.delete", "Cameras", "Delete", "Remove cameras"),

    # ---------------------------------------------------------------- Workers (3)
    _p("workers.view", "Workers", "View", "View worker records and recognition", C),
    _p("workers.enroll", "Workers", "Create", "Enroll workers for recognition", C),
    _p("workers.delete", "Workers", "Delete", "Remove worker records", C),

    # ---------------------------------------------------------------- Violations and alerts (2)
    _p("violations.view", "Violations", "View", "View violations and alerts"),
    _p("violations.manage", "Violations", "Manage", "Resolve violations"),

    # ---------------------------------------------------------------- Copilot (2)
    _p("copilot.use", "Copilot", "Execute", "Use the AI Copilot"),
    _p("copilot.config", "Copilot", "Configure", "Configure the AI Copilot", C, sensitive=True),

    # ---------------------------------------------------------------- Controlled actions (3)
    _p("wms.actions.view", "Controlled actions", "View", "View controlled-action recommendations and audit"),
    _p("wms.actions.execute", "Controlled actions", "Execute", "Execute controlled actions"),
    _p("wms.actions.reject", "Controlled actions", "Reject", "Reject controlled actions"),

    # ---------------------------------------------------------------- Integration (2)
    _p("integration.view", "Integration", "View", "View integration overview"),
    _p("integration.test.execute", "Integration", "Execute", "Run end-to-end integration test scenarios", sensitive=True),

    # ---------------------------------------------------------------- Administration (12)
    _p("users.view", "Administration", "View", "View users", C),
    _p("users.invite", "Administration", "Create", "Invite users", C),
    _p("users.edit", "Administration", "Edit", "Edit users and reset their passwords", C),
    _p("users.deactivate", "Administration", "Manage", "Activate and deactivate users", C),
    _p("roles.view", "Administration", "View", "View roles", C),
    _p("roles.manage", "Administration", "Manage", "Create, edit and deactivate roles", C),
    _p("assignments.manage", "Administration", "Manage", "Assign roles to users per warehouse", C),
    _p("warehouses.view", "Administration", "View", "View warehouses", C),
    _p("warehouses.manage", "Administration", "Manage", "Create, edit and deactivate warehouses", C),
    _p("company.settings.manage", "Administration", "Configure", "Manage company settings", C),
    _p("audit.view", "Administration", "View", "View audit logs", C),
    _p("audit.export", "Administration", "Export", "Export audit logs", C),

    # ---------------------------------------------------------------- Platform (2) - Platform Admin only
    _p("platform.companies.manage", "Platform", "Manage", "Create, suspend and manage companies", P),
    _p("platform.system.view", "Platform", "View", "View platform system status", P),
]

PERMISSIONS_BY_KEY: Dict[str, Permission] = {p.key: p for p in PERMISSION_CATALOG}

# Built-in roles. Their permissions are resolved in code (never stored as rows), so
# permissions added to the catalogue later are included automatically.
BUILTIN_ROLES = (
    ("platform_admin", "Platform Admin", "Full access to every company, plus platform administration."),
    ("company_admin", "Company Admin", "Full access within one company. Never platform permissions."),
    ("user", "User", "No permissions by itself; gets them from the custom roles assigned to it."),
)


# Sub-sections inside the larger permission groups (only for display in the role builder;
# they are NOT roles). Permissions not listed here sit in their group without a sub-section.
PERMISSION_SECTIONS: Dict[str, str] = {}
for _section, _keys in (
    ("Monitoring", ("gate.dashboard.view", "gate.pass.view", "gate.vehicle_log.view", "gate.driver.view",
                    "gate.violation.view", "gate.documents.export")),
    ("Security desk (entry)", ("gate.vehicle.register", "gate.vehicle.edit", "gate.anpr.execute", "gate.otp.send",
                               "gate.otp.verify", "gate.entry.approve", "gate.entry.reject", "gate.dock.admit")),
    ("Exit & checkout", ("gate.checkout.approve", "gate.checkout.complete")),
    ("Gate in-charge (exceptions & overrides)", ("gate.otp.override", "gate.entry.bulk_approve",
                                                 "gate.manual_admission.authorize", "gate.exception.approve",
                                                 "gate.override.manual", "gate.violation.manage")),
    ("Gate devices", ("gate.devices.configure",)),
    ("Viewing", ("cameras.view", "cameras.stream.view", "cameras.ptz.control")),
    ("Camera setup", ("cameras.create", "cameras.configure", "cameras.delete")),
    ("People", ("users.view", "users.invite", "users.edit", "users.deactivate")),
    ("Roles & access", ("roles.view", "roles.manage", "assignments.manage")),
    ("Warehouses & company", ("warehouses.view", "warehouses.manage", "company.settings.manage")),
    ("Audit", ("audit.view", "audit.export")),
):
    for _k in _keys:
        PERMISSION_SECTIONS[_k] = _section

# Starter roles: created once for every company as ordinary custom roles (editable,
# renameable, deactivatable; "Restore defaults" brings these ticks back). No sensitive
# permission is ticked by default - an admin adds those deliberately.
_GATE_MONITOR = ("gate.dashboard.view", "gate.pass.view", "gate.vehicle_log.view", "gate.driver.view",
                 "gate.violation.view")
_GATE_DESK = ("gate.vehicle.register", "gate.vehicle.edit", "gate.anpr.execute", "gate.otp.send",
              "gate.otp.verify", "gate.entry.approve", "gate.entry.reject", "gate.checkout.complete")
_LIVE_CAMERAS = ("cameras.view", "cameras.stream.view")
STARTER_ROLES = (
    ("gate_security", "Gate Security",
     "Security desk: registers vehicles, reads plates, verifies driver OTPs, lets vehicles in and out.",
     ("dashboard.view", "deliveries.view") + _GATE_MONITOR + _GATE_DESK + _LIVE_CAMERAS),
    ("gate_incharge", "Gate In-charge",
     "Runs the gate: everything Gate Security does, plus dock dispatch, exit approval, violations and documents.",
     ("dashboard.view", "reports.view", "deliveries.view", "deliveries.create", "deliveries.edit", "violations.view")
     + _GATE_MONITOR + _GATE_DESK + _LIVE_CAMERAS
     + ("gate.dock.admit", "gate.checkout.approve", "gate.violation.manage", "gate.documents.export")),
    ("dock_supervisor", "Dock Supervisor",
     "Runs unloading at the docks: receipts, staging, pallets and vision counts.",
     ("dashboard.view", "gate.pass.view", "gate.dock.admit", "deliveries.view", "dock.view", "dock.unload.execute",
      "dock.evidence.view", "inbound.view", "inbound.receipt.complete", "inbound.staging.view", "bins.view",
      "inventory.view", "pallet.view", "pallet.create", "pallet.seal", "vision.view", "vision.counting.execute",
      "vision.counting.review", "violations.view") + _LIVE_CAMERAS),
    ("inventory_controller", "Inventory Controller",
     "Looks after stock: bins, transfers, cycle counts and pallets.",
     ("dashboard.view", "sku.view", "bins.view", "bins.create", "bins.edit", "inventory.view", "inventory.transfer",
      "inventory.export", "cyclecount.view", "cyclecount.execute", "pallet.view", "pallet.create", "pallet.seal",
      "pallet.transfer", "inbound.view", "outbound.view", "vision.traceability.view")),
    ("dispatch_operator", "Dispatch Operator",
     "Prepares and dispatches outbound orders.",
     ("dashboard.view", "sku.view", "bins.view", "inventory.view", "outbound.view", "outbound.create",
      "outbound.dispatch", "pallet.view", "pallet.transfer", "gate.pass.view")),
    ("vision_operator", "AI Vision Operator",
     "Runs AI counting and tracking, sets up zones and cameras, enrolls workers.",
     ("dashboard.view", "vision.view", "vision.counting.execute", "vision.counting.review", "vision.traceability.view",
      "vision.zones.manage", "cameras.configure", "cameras.ptz.control", "workers.view", "workers.enroll")
     + _LIVE_CAMERAS),
    ("warehouse_manager", "Warehouse Manager",
     "Manages day-to-day operations of a warehouse; sees users and roles but does not change them.",
     tuple(sorted({k for k, p in PERMISSIONS_BY_KEY.items()
                   if p.scope_level != P and not p.sensitive
                   and not k.startswith(("users.invite", "users.edit", "users.deactivate", "roles.manage",
                                         "assignments.manage", "warehouses.manage", "company.settings",
                                         "audit.export", "cameras.delete", "workers.delete", "sku.delete",
                                         "bins.delete", "pallet.delete", "deliveries.delete"))}))),
    ("executive", "Executive (view-only)",
     "Sees dashboards, reports and every operational screen, without changing anything.",
     ("dashboard.view", "reports.view", "reports.export", "gate.dashboard.view", "gate.pass.view",
      "gate.vehicle_log.view", "deliveries.view", "dock.view", "inbound.view", "bins.view", "sku.view",
      "inventory.view", "cyclecount.view", "outbound.view", "pallet.view", "vision.view",
      "vision.traceability.view", "violations.view", "warehouses.view", "copilot.use") + _LIVE_CAMERAS),
)
STARTER_ROLES_BY_KEY = {t[0]: t for t in STARTER_ROLES}

# Exceptional actions: every use needs a written reason, in every RBAC mode (Phase 7).
# The other sensitive permissions (AI runtime / test benches, camera simulation, Copilot
# config) are audited on every use but don't ask for a reason, so the AI lab stays usable.
REASON_PERMISSIONS = frozenset({
    "inventory.adjust", "gate.entry.bulk_approve", "gate.override.manual", "gate.otp.override",
    "gate.manual_admission.authorize", "gate.exception.approve", "masterdata.blueprint.apply",
    "integration.test.execute",
})


def builtin_permissions(builtin_code: Optional[str]) -> frozenset:
    if builtin_code == "platform_admin":
        return frozenset(PERMISSIONS_BY_KEY)
    if builtin_code == "company_admin":
        return frozenset(k for k, p in PERMISSIONS_BY_KEY.items() if p.scope_level != P)
    return frozenset()


def _self_check() -> None:
    keys = [p.key for p in PERMISSION_CATALOG]
    assert len(keys) == len(set(keys)), "duplicate permission keys"
    for p in PERMISSION_CATALOG:
        assert p.action in ACTIONS, p
        assert p.scope_level in (W, C, P), p
        assert p.key.count(".") >= 1 and p.key == p.key.lower(), p
    for k in PERMISSION_SECTIONS:
        assert k in PERMISSIONS_BY_KEY, f"section for unknown permission {k}"
    for key, name, _, perms in STARTER_ROLES:
        for k in perms:
            assert k in PERMISSIONS_BY_KEY, f"starter role {name}: unknown permission {k}"
            assert PERMISSIONS_BY_KEY[k].scope_level != P, f"starter role {name}: platform permission {k}"
            assert not PERMISSIONS_BY_KEY[k].sensitive, f"starter role {name}: sensitive permission {k}"


_self_check()
