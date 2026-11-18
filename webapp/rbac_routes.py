"""
Route -> permission map (RBAC Phase 2).

Every Flask endpoint (view-function name) is listed exactly once:
  * PUBLIC_ENDPOINTS         - reachable without signing in
  * AUTHENTICATED_ENDPOINTS  - any signed-in user (no specific permission)
  * ROUTE_PERMISSIONS        - a permission key, either one key for every method or a
                               {METHOD: key} dict when reading and changing differ

tests/test_rbac_coverage.py fails if any registered endpoint is missing here or names a
key that is not in rbac_catalog. docs/rbac_route_map.csv is generated from this file
(scripts/rbac_route_map.py) for review.

REASON_REQUIRED_ENDPOINTS: exceptional operations that must carry a written reason
("reason" in the JSON body or the X-Action-Reason header). Audit mode logs a missing
reason; enforce mode rejects it with 400.
"""
from typing import List, Optional, Dict, Union

PermSpec = Union[str, Dict[str, str]]

PUBLIC_ENDPOINTS = frozenset({
    "static", "login_page", "logout", "api_logout", "api_login",
    "api_company_preview_recognition", "api_send_otp", "api_verify_otp_and_register",
    # Phase 4: invitation / password links (each needs a valid single-use token)
    "iam.accept_invite_page", "iam.forgot_password_page", "iam.reset_link_page", "iam.api_invite_info",
    "iam.api_accept_invite", "iam.api_forgot_password", "iam.api_reset_password", "iam.api_reset_link_status",
})

AUTHENTICATED_ENDPOINTS = frozenset({
    "index", "reset_password_page", "api_force_reset_password",
    # Warehouse picker. Phase 3 limits these to the user's assigned warehouses.
    "api_get_warehouses", "api_get_active_warehouse", "api_switch_warehouse",
    "api_auth_me",
    "iam.api_change_password",   # Phase 4: own password, needs the current one
})


def _rw(read: str, write: str, *write_methods: str) -> Dict[str, str]:
    """GET -> read, every listed write method -> write."""
    spec = {"GET": read, "HEAD": read}
    for m in write_methods or ("POST", "PUT", "PATCH", "DELETE"):
        spec[m] = write
    return spec


ROUTE_PERMISSIONS: Dict[str, PermSpec] = {
    # ------------------------------------------------------------ company setup / templates
    "api_company_auto_setup": "platform.companies.manage",   # creates a new company + facility
    "api_platform_companies": "platform.companies.manage",   # Companies & Owners overview (read-only)
    # Phase 4: users, invitations, assignments, companies (also enforced inside the handlers)
    "iam.api_iam_overview": "users.view",
    "iam.api_create_invitation": "users.invite",
    "iam.api_revoke_invitation": "users.invite",
    "iam.api_resend_invitation": "users.invite",
    "iam.api_edit_user": "users.edit",
    "iam.api_deactivate_user": "users.deactivate",
    "iam.api_activate_user": "users.deactivate",
    "iam.api_user_reset_link": "users.edit",
    "iam.api_add_assignment": "assignments.manage",
    "iam.api_revoke_assignment": "assignments.manage",
    "iam.api_list_roles": "roles.view",          # Phase 5: role builder
    "iam.api_create_role": "roles.manage",
    "iam.api_update_role": "roles.manage",
    "iam.api_preview_role": "roles.manage",
    "iam.api_deactivate_role": "roles.manage",
    "iam.api_activate_role": "roles.manage",
    "iam.api_audit_list": "audit.view",          # Phase 7: audit log
    "iam.api_audit_export": "audit.export",
    "iam.api_company_settings": "users.view",
    "iam.api_update_company_settings": "copilot.config|company.settings.manage",
    "iam.api_platform_create_company": "platform.companies.manage",
    "iam.api_platform_suspend_company": "platform.companies.manage",
    "iam.api_platform_activate_company": "platform.companies.manage",
    "api_get_industry_blueprints": "sku.view",
    "api_apply_industry_blueprint": "masterdata.blueprint.apply",
    "api_create_warehouse": "warehouses.manage",

    # ------------------------------------------------------------ dashboard
    "get_stats": "dashboard.view",
    "get_live_telemetry_endpoint": "dashboard.view",
    "get_alerts": "violations.view|gate.violation.view|dashboard.view",

    # ------------------------------------------------------------ pre-registration
    "handle_deliveries": {"GET": "deliveries.view|inbound.view|dock.view|gate.pass.view", "HEAD": "deliveries.view|inbound.view|dock.view|gate.pass.view", "POST": "deliveries.create"},
    "handle_single_delivery": {"GET": "deliveries.view", "HEAD": "deliveries.view", "PUT": "deliveries.edit",
                               "PATCH": "deliveries.edit", "DELETE": "deliveries.delete"},

    # ------------------------------------------------------------ gate
    "get_gate_passes": "gate.pass.view|inbound.view|dock.view|gate.dashboard.view",
    "create_gate_pass": "gate.vehicle.register",
    "register_walkin_vehicle": "gate.vehicle.register",
    "update_gate_pass": {"GET": "gate.pass.view", "HEAD": "gate.pass.view", "PUT": "gate.vehicle.edit",
                         "DELETE": "gate.override.manual"},
    "api_gate_pass_otp": "gate.otp.send",
    "verify_otp": "gate.otp.verify",
    "approve_all_matched_passes": "gate.entry.bulk_approve",
    "gate_auto_dispatch_toggle": {"GET": "gate.dashboard.view", "HEAD": "gate.dashboard.view",
                                  "POST": "gate.devices.configure"},
    "simulate_gate_arrival": "gate.devices.configure",
    "scan_gate_now": "gate.anpr.execute",
    "snap_and_read_gate": "gate.anpr.execute",
    "decode_ocr_endpoint": "gate.anpr.execute",
    "checkout": "gate.checkout.complete",
    "checkout_gate_pass": "gate.checkout.complete",
    "generate_invoice": "gate.documents.export",
    "get_invoices": "gate.documents.export",
    "get_gate_manifest": "gate.documents.export",
    "get_vehicle_logs": "gate.vehicle_log.view",
    "api_gate_multi_status": "gate.dashboard.view|gate.pass.view|dock.view|dashboard.view",

    # ------------------------------------------------------------ dock
    "unload_step": "dock.unload.execute",
    "auto_add_step": "dock.unload.execute",
    "api_dock_gate_pass_evidence": "dock.evidence.view",
    "api_dock_verification": "dock.view",
    "suggest_bin": "dock.view",

    # ------------------------------------------------------------ inbound and staging
    "api_inbound_simulate": "inbound.receipt.complete",
    "api_inbound_complete_receipt": "inbound.receipt.complete",
    "api_staging_status": "inbound.staging.view|inbound.view",
    "api_staging_cameras": "inbound.staging.view",
    "api_staging_feed_mjpg": "inbound.staging.view|inbound.view",
    "api_staging_frame_jpg": "inbound.staging.view",
    "api_staging_configure": "inbound.staging.configure",
    "api_staging_reset": "inbound.staging.reset",
    "api_staging_placement": "inbound.receipt.complete",

    # ------------------------------------------------------------ bins and inventory
    "api_get_bins": "bins.view|inventory.view|deliveries.view|pallet.view|dock.view|sku.view|inbound.view|outbound.view",
    "api_add_bin": "bins.create",
    "api_update_bin": "bins.edit",
    "api_get_bin_inventory": "inventory.view",
    "get_inventory": "inventory.view",
    "update_inventory": "inventory.adjust",
    "sync_camera_inventory": "inventory.adjust",
    "api_sync_audit_count": "inventory.adjust",
    "api_transfer_vision_inventory": "inventory.transfer",
    # Inventory section (inventory_routes.py; changes are also checked in the handlers)
    "stock.api_overview": "inventory.view",
    "stock.api_movements": "inventory.view",
    "stock.api_export": "inventory.export",
    "stock.api_adjust": "inventory.adjust",
    "stock.api_transfer": "inventory.transfer",
    "stock.api_min_level": "inventory.levels.manage",
    # AI Vision tools (vision_studio_routes.py; changes are also checked in the handlers)
    "vstudio.api_status": "vision.view|vision.counting.execute|sku.view",
    "vstudio.api_count": "vision.counting.execute",
    "vstudio.api_examples": "vision.view|vision.counting.execute|sku.view",
    "vstudio.api_save_example": "sku.edit",
    "vstudio.api_delete_example": "sku.edit",
    "vstudio.api_photo_search": "sku.create|sku.edit",
    "vstudio.api_photo_import": "sku.edit",

    # ------------------------------------------------------------ cycle count
    "audit_bin_cycle_count": "cyclecount.view",
    "get_cycle_count_activities": "cyclecount.view",
    "simulate_bin_cycle_count": "cyclecount.execute",
    "run_cycle_count": "cyclecount.execute",

    # ------------------------------------------------------------ outbound
    "handle_outbound": {"GET": "outbound.view", "HEAD": "outbound.view", "POST": "outbound.create"},
    "pick_outbound": "outbound.dispatch",
    "get_outbound_manifest": "outbound.view",

    # ------------------------------------------------------------ SKU and master data
    "api_get_skus": "sku.view|pallet.view|deliveries.view|inventory.view|vision.view|dock.view|inbound.view|outbound.view|bins.view",
    "api_add_sku": "sku.create",
    "api_update_sku_bundle_config": "sku.edit",
    "api_get_sku_master": "sku.view|pallet.view|deliveries.view|inventory.view|vision.view|dock.view|inbound.view|outbound.view|bins.view",
    "api_get_sku_detail": "sku.view",
    "api_save_sku": "sku.edit",
    "api_delete_sku": "sku.delete",
    "api_download_sku_template": "sku.import",
    "api_preview_sku_excel": "sku.import",
    "api_confirm_sku_excel_import": "sku.import",
    "api_preview_image_matches": "sku.edit",
    "api_upload_sku_images": "sku.edit",
    "api_delete_sku_image": "sku.edit",
    "api_set_sku_primary_image": "sku.edit",
    "api_get_vision_skus": "sku.view|pallet.view|deliveries.view|inventory.view|vision.view|dock.view|inbound.view|outbound.view|bins.view",
    "api_get_glass_profiles": "sku.view",
    "api_save_glass_profile": "sku.edit",
    "api_delete_glass_profile": "sku.edit",
    "handle_object_classes": _rw("vision.view|cameras.view|dashboard.view", "vision.classes.manage", "POST"),
    "handle_single_object_class": _rw("vision.view", "vision.classes.manage", "PUT", "PATCH", "DELETE"),

    # ------------------------------------------------------------ pallets and counting
    "api_get_pallets": "pallet.view",
    "api_get_single_pallet": "pallet.view",
    "api_get_pallet_label": "pallet.view",
    "api_create_pallet": "pallet.create",
    "api_delete_pallet": "pallet.delete",
    "api_seal_pallet": "pallet.seal",
    "api_camera_pallet_bind": {"GET": "pallet.view", "HEAD": "pallet.view", "POST": "pallet.create"},
    "api_update_pallet_count": "vision.counting.execute",
    "api_count_pallet_image": "vision.counting.execute",
    "api_count_pallet_pieces": "vision.counting.execute",
    "api_re_render_pallet_pieces": "vision.counting.execute",
    "api_count_pallet_bundles": "vision.counting.execute",
    "api_count_pallet_multiview": "vision.counting.execute",
    "api_resolve_counting_strategy": "vision.counting.execute",
    "api_multi_angle_count": "vision.counting.execute",
    "api_review_pallet_multiview": "vision.counting.review",

    # ------------------------------------------------------------ violations
    "api_get_violations": "violations.view|gate.violation.view|dashboard.view",
    "api_get_violations_summary": "violations.view|gate.violation.view|dashboard.view",
    "api_log_violation": "violations.manage",
    "api_resolve_violation": "violations.manage",
    "api_resolve_all_violations": "violations.manage",

    # ------------------------------------------------------------ cameras and streams
    "get_cameras": "cameras.view|dashboard.view|vision.view",
    "get_vision_cameras": "cameras.view|dashboard.view|vision.view",
    "get_single_vision_camera": "cameras.view",
    "api_system_rtmp_status": "cameras.view|dashboard.view|vision.view",
    "handle_vision_camera_config": _rw("cameras.view", "cameras.configure", "PUT", "POST"),
    "add_camera": "cameras.create",
    "delete_camera": "cameras.delete",
    "toggle_camera_freeze": "cameras.configure",
    "assign_camera_bin": "cameras.configure",
    "receive_camera_frame": "cameras.configure",
    "camera_ptz_endpoint": "cameras.ptz.control",
    "video_feed": "cameras.stream.view",
    "snap_camera": "cameras.stream.view",
    "api_camera_snapshot": "cameras.stream.view",
    "get_camera_preview_info": "cameras.stream.view",
    "get_camera_preview_image": "cameras.stream.view",
    "api_vision_runtime_camera_preview_jpg": "cameras.stream.view",

    # ------------------------------------------------------------ vision zones
    "get_zone_types": "vision.view",
    "get_zone_all_rois": "vision.view",
    "handle_vision_zones": _rw("vision.view|cameras.view|dashboard.view", "vision.zones.manage", "POST"),
    "handle_single_vision_zone": _rw("vision.view", "vision.zones.manage", "PUT", "PATCH", "DELETE"),
    "handle_vision_zone_cameras": _rw("vision.view", "vision.zones.manage", "PUT"),
    "handle_zone_camera_roi": _rw("vision.view", "vision.zones.manage", "POST", "PUT", "DELETE"),

    # ------------------------------------------------------------ vision runtime and detection
    "api_vision_runtime_status": "vision.view",
    "api_vision_runtime_cameras": "vision.view",
    "api_vision_runtime_camera_detail": "vision.view",
    "api_vision_dashboard_live": "vision.view|dashboard.view|cameras.view",
    "api_vision_runtime_camera_start": "vision.runtime.configure",
    "api_vision_runtime_camera_stop": "vision.runtime.configure",
    "api_vision_runtime_camera_restart": "vision.runtime.configure",
    "api_vision_runtime_start_all": "vision.runtime.configure",
    "api_vision_runtime_stop_all": "vision.runtime.configure",
    "api_vision_runtime_camera_test_step": "vision.runtime.configure",
    "api_detection_info": "vision.view",
    "api_detection_samples": "vision.view",
    "api_detection_config": _rw("vision.view", "vision.runtime.configure", "POST", "PUT"),
    "api_detection_test": "vision.runtime.configure",
    "api_detection_camera_single": "vision.view",
    "api_detection_camera_annotated_jpg": "vision.view",
    "api_vision_validate": "vision.counting.execute",

    # ------------------------------------------------------------ vision engine panels (status / diagnostics)
    **{f"api_{p}_status": "vision.view" for p in (
        "tracking", "identity", "validation", "association", "worker_box", "box_bin",
        "material_association")},
    **{f"api_{p}_{a}": "vision.runtime.configure" for p in (
        "tracking", "identity", "association", "worker_box", "box_bin",
        "material_association") for a in ("reset", "test", "sequence")},
    "api_validation_test": "vision.runtime.configure",
    **{f"api_{p}_camera_single": "vision.view" for p in (
        "tracking", "identity", "validation", "association", "worker_box", "box_bin")},
    **{f"api_{p}_camera_annotated_jpg": "vision.view" for p in (
        "tracking", "identity", "validation", "association", "worker_box", "box_bin",
        "material_association")},
    "api_validation_reset": "vision.runtime.configure",
    "api_material_association_camera": "vision.view",
    "api_material_association_by_material": "vision.traceability.view",
    "api_vision_events_status": "vision.view",
    "api_vision_events_reset": "vision.runtime.configure",
    "api_vision_events_test": "vision.runtime.configure",
    "api_vision_events_sequence": "vision.runtime.configure",
    "api_vision_events_camera_single": "vision.view",
    "api_vision_events_camera_annotated_jpg": "vision.view",
    "api_vision_events_material_timeline": "vision.traceability.view",
    "api_vision_traceability_status": "vision.traceability.view",
    "api_vision_traceability_reset": "vision.runtime.configure",
    "api_vision_traceability_test": "vision.runtime.configure",
    "api_vision_traceability_sequence": "vision.runtime.configure",
    "api_vision_traceability_materials": "vision.traceability.view",
    "api_vision_traceability_material_detail": "vision.traceability.view",
    "api_vision_traceability_material_timeline": "vision.traceability.view",
    "api_vision_traceability_camera": "vision.traceability.view",
    "api_vision_traceability_camera_annotated_jpg": "vision.traceability.view",

    # ------------------------------------------------------------ workers
    "api_list_trained_workers": "workers.view",
    "api_train_worker": "workers.enroll",
    "api_toggle_worker_names": "workers.enroll",
    "api_delete_trained_worker": "workers.delete",

    # ------------------------------------------------------------ integration and controlled actions
    "api_integration_overview": "integration.view|dashboard.view",
    "api_integration_delivery": "integration.view",
    "api_integration_gate_pass": "integration.view",
    "api_integration_material": "integration.view",
    "api_integration_dock": "integration.view",
    "api_integration_bin": "integration.view",
    "api_integration_camera": "integration.view",
    "api_integration_e2e_test_scenario": "integration.test.execute",
    "api_controlled_actions_recommendations": "wms.actions.view",
    "api_controlled_actions_preview": "wms.actions.view",
    "api_controlled_actions_audit": "wms.actions.view",
    "api_controlled_actions_status": "wms.actions.view",
    "api_controlled_actions_execute": "wms.actions.execute",
    "api_controlled_actions_reject": "wms.actions.reject",

    # ------------------------------------------------------------ copilot
    "api_copilot_chat": "copilot.use",
    "api_copilot_action": "copilot.use",   # plus the action's own permission (COPILOT_ACTION_PERMISSIONS)
}

# Each Copilot action also needs the permission of the operation it performs.
COPILOT_ACTION_PERMISSIONS = {
    "admit_dock": "gate.dock.admit",
    "manual_admit": "gate.manual_admission.authorize",
}

# Exceptional operations that must carry a written reason.
REASON_REQUIRED_ENDPOINTS = frozenset({
    "approve_all_matched_passes",   # bulk entry approval
    "update_inventory",             # manual stock adjustment
    "api_apply_industry_blueprint",
    "api_company_auto_setup",
})


def permission_keys(spec_key: Optional[str]) -> List[str]:
    """'a|b' (any one of several permissions, used for shared lookup reads) -> ['a', 'b']."""
    return [k for k in str(spec_key or "").split("|") if k]


def permission_for(endpoint: str, method: str):
    """The permission key for this endpoint and method, or None when unmapped.
    A key may be 'a|b': any one of those permissions opens the route (RBAC Phase 6)."""
    spec = ROUTE_PERMISSIONS.get(endpoint)
    if spec is None:
        return None
    if isinstance(spec, str):
        return spec
    return spec.get(method.upper()) or (spec.get("GET") if method.upper() in ("HEAD", "OPTIONS") else None)
