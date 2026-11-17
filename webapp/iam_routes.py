"""
HTTP routes for users, invitations, passwords and companies (RBAC Phase 4).

Admin actions here are checked in EVERY RBAC mode (also 'audit'): they change who can
sign in and what they may do, so "log only" is not good enough. The permission keys are
the plan's: users.view / users.invite / users.edit / users.deactivate /
assignments.manage, and platform.companies.manage (Platform Admin only).
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, render_template, request, session

import iam_service
import rbac_service
from iam_service import IamError

bp = Blueprint("iam", __name__)


def _ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""


def _actor():
    return g.get("current_user") or {}


def _need(key: str):
    actor = _actor()
    if not actor:
        raise IamError(401, "login_required", "Please sign in.")
    if key.startswith("platform."):
        if not actor.get("is_platform_admin"):
            raise IamError(403, "permission_denied", "Platform Admin only.")
        return
    if key not in rbac_service.effective_permissions():
        raise IamError(403, "permission_denied", "You don't have permission for this.")


def _company():
    data = request.get_json(silent=True) or {}
    return iam_service.acting_company(_actor(), request.args.get("company_id") or data.get("company_id"))


def _body():
    return request.get_json(silent=True) or {}


@bp.errorhandler(IamError)
def _iam_error(e: IamError):
    return jsonify({"success": False, "error": e.message, "message": e.message, "error_code": e.code}), e.status


# ----------------------------------------------------------------------------- public pages
@bp.route("/accept-invite", methods=["GET"])
def accept_invite_page():
    return render_template("account_link.html", mode="invite")


@bp.route("/forgot-password", methods=["GET"])
def forgot_password_page():
    return render_template("account_link.html", mode="forgot")


@bp.route("/reset-password", methods=["GET"])
def reset_link_page():
    return render_template("account_link.html", mode="reset")


@bp.route("/api/auth/invite_info", methods=["GET"])
def api_invite_info():
    return jsonify({"success": True, "invitation": iam_service.invitation_info(request.args.get("token", ""))})


@bp.route("/api/auth/accept_invite", methods=["POST"])
def api_accept_invite():
    d = _body()
    if (d.get("password") or "") != (d.get("confirm_password") or d.get("password") or ""):
        raise IamError(400, "password_mismatch", "The two passwords do not match.")
    out = iam_service.accept_invitation(d.get("token", ""), d.get("username", ""), d.get("password", ""), _ip())
    return jsonify({"success": True, "message": f"Welcome to {out['company_name']}. You can sign in now.", **out})


@bp.route("/api/auth/forgot_password", methods=["POST"])
def api_forgot_password():
    iam_service.request_password_reset(_body().get("identifier", ""), _ip(), request.host_url)
    return jsonify({"success": True, "message": "If that account exists and has an email address, "
                                                "a reset link is on its way. It works for 30 minutes."})


@bp.route("/api/auth/reset_password", methods=["POST"])
def api_reset_password():
    d = _body()
    if (d.get("password") or "") != (d.get("confirm_password") or d.get("password") or ""):
        raise IamError(400, "password_mismatch", "The two passwords do not match.")
    iam_service.reset_with_token(d.get("token", ""), d.get("password", ""), _ip())
    return jsonify({"success": True, "message": "Password changed. You can sign in now."})


@bp.route("/api/auth/reset_link_status", methods=["GET"])
def api_reset_link_status():
    return jsonify({"success": True, "valid": iam_service.reset_token_valid(request.args.get("token", ""))})


# ----------------------------------------------------------------------------- signed in
@bp.route("/api/auth/change_password", methods=["POST"])
def api_change_password():
    d = _body()
    if (d.get("new_password") or "") != (d.get("confirm_password") or d.get("new_password") or ""):
        raise IamError(400, "password_mismatch", "The two new passwords do not match.")
    sv = iam_service.change_password(_actor(), d.get("current_password", ""), d.get("new_password", ""), _ip())
    # this session stays signed in; every other session of the account ends
    user = dict(session.get("user") or {})
    user["sv"] = sv
    session["user"] = user
    return jsonify({"success": True, "message": "Password changed. Other devices were signed out."})


# ----------------------------------------------------------------------------- users & access
@bp.route("/api/iam/overview", methods=["GET"])
def api_iam_overview():
    _need("users.view")
    cid = _company()
    actor = _actor()
    perms = rbac_service.effective_permissions()
    return jsonify({
        "success": True, "company_id": cid,
        "users": iam_service.list_users(cid),
        "invitations": iam_service.list_invitations(cid),
        "roles": iam_service.list_roles(cid),
        "warehouses": iam_service.list_warehouses(cid),
        "me": actor.get("id"),
        "can": {k: (bool(actor.get("is_platform_admin")) or k in perms)
                for k in ("users.invite", "users.edit", "users.deactivate", "assignments.manage")},
    })


@bp.route("/api/iam/invitations", methods=["POST"])
def api_create_invitation():
    _need("users.invite")
    d = _body()
    out = iam_service.create_invitation(_actor(), _company(), d.get("email"), d.get("role_id"), d.get("warehouse_id"),
                                        request.host_url, _ip())
    return jsonify({"success": True, **out})


@bp.route("/api/iam/invitations/<int:invitation_id>/revoke", methods=["POST"])
def api_revoke_invitation(invitation_id):
    _need("users.invite")
    iam_service.revoke_invitation(_actor(), _company(), invitation_id, _ip())
    return jsonify({"success": True, "message": "Invitation revoked."})


@bp.route("/api/iam/invitations/<int:invitation_id>/resend", methods=["POST"])
def api_resend_invitation(invitation_id):
    _need("users.invite")
    out = iam_service.resend_invitation(_actor(), _company(), invitation_id, request.host_url, _ip())
    return jsonify({"success": True, **out})


@bp.route("/api/iam/users/<int:user_id>", methods=["PATCH"])
def api_edit_user(user_id):
    _need("users.edit")
    iam_service.update_user(_actor(), _company(), user_id, _body(), _ip())
    return jsonify({"success": True, "message": "User updated."})


@bp.route("/api/iam/users/<int:user_id>/deactivate", methods=["POST"])
def api_deactivate_user(user_id):
    _need("users.deactivate")
    iam_service.set_user_active(_actor(), _company(), user_id, False, _body().get("reason"), _ip())
    return jsonify({"success": True, "message": "User deactivated and signed out."})


@bp.route("/api/iam/users/<int:user_id>/activate", methods=["POST"])
def api_activate_user(user_id):
    _need("users.deactivate")
    iam_service.set_user_active(_actor(), _company(), user_id, True, _body().get("reason"), _ip())
    return jsonify({"success": True, "message": "User activated."})


@bp.route("/api/iam/users/<int:user_id>/reset_link", methods=["POST"])
def api_user_reset_link(user_id):
    _need("users.edit")
    out = iam_service.admin_send_reset(_actor(), _company(), user_id, request.host_url, _ip())
    return jsonify({"success": True, **out})


@bp.route("/api/iam/users/<int:user_id>/assignments", methods=["POST"])
def api_add_assignment(user_id):
    _need("assignments.manage")
    d = _body()
    out = iam_service.add_assignment(_actor(), _company(), user_id, d.get("role_id"), d.get("warehouse_id"), _ip())
    return jsonify({"success": True, "message": "Access granted.", **out})


@bp.route("/api/iam/assignments/<int:assignment_id>/revoke", methods=["POST"])
def api_revoke_assignment(assignment_id):
    _need("assignments.manage")
    iam_service.revoke_assignment(_actor(), _company(), assignment_id, _body().get("reason"), _ip())
    return jsonify({"success": True, "message": "Access removed."})


# ----------------------------------------------------------------------------- roles (Phase 5)
@bp.route("/api/iam/roles", methods=["GET"])
def api_list_roles():
    _need("roles.view")
    cid = _company()
    actor = _actor()
    perms = rbac_service.effective_permissions()
    return jsonify({"success": True, "company_id": cid,
                    "roles": iam_service.list_roles_detailed(cid),
                    "catalog": iam_service.permission_catalog(actor, cid),
                    "can_manage": bool(actor.get("is_platform_admin")) or "roles.manage" in perms})


@bp.route("/api/iam/roles", methods=["POST"])
def api_create_role():
    _need("roles.manage")
    out = iam_service.create_role(_actor(), _company(), _body(), _ip())
    return jsonify({"success": True, "message": f"Role '{out['name']}' created.", **out})


@bp.route("/api/iam/roles/<int:role_id>", methods=["PUT"])
def api_update_role(role_id):
    _need("roles.manage")
    out = iam_service.update_role(_actor(), _company(), role_id, _body(), _ip())
    return jsonify({"success": True, "message": f"Role '{out['name']}' saved. "
                    f"{out['users_affected']} user(s) get the change on their next click.", **out})


@bp.route("/api/iam/roles/<int:role_id>/preview", methods=["POST"])
def api_preview_role(role_id):
    _need("roles.manage")
    return jsonify({"success": True, **iam_service.preview_role_change(_actor(), _company(), role_id, _body())})


@bp.route("/api/iam/roles/<int:role_id>/deactivate", methods=["POST"])
def api_deactivate_role(role_id):
    _need("roles.manage")
    out = iam_service.set_role_active(_actor(), _company(), role_id, False, _body().get("reason"), _ip())
    return jsonify({"success": True, "message": f"Role deactivated. {out['users_affected']} user(s) lost its "
                                                "permissions on their next click.", **out})


@bp.route("/api/iam/roles/<int:role_id>/activate", methods=["POST"])
def api_activate_role(role_id):
    _need("roles.manage")
    out = iam_service.set_role_active(_actor(), _company(), role_id, True, _body().get("reason"), _ip())
    return jsonify({"success": True, "message": "Role reactivated.", **out})


# ----------------------------------------------------------------------------- companies (Platform Admin)
@bp.route("/api/platform/companies", methods=["POST"])
def api_platform_create_company():
    _need("platform.companies.manage")
    d = _body()
    out = iam_service.create_company(_actor(), d.get("name"), d.get("owner_email"), d.get("city"),
                                     request.host_url, _ip())
    return jsonify({"success": True, **out})


@bp.route("/api/platform/companies/<int:company_id>/suspend", methods=["POST"])
def api_platform_suspend_company(company_id):
    _need("platform.companies.manage")
    iam_service.set_company_status(_actor(), company_id, False, _body().get("reason"), _ip())
    return jsonify({"success": True, "message": "Company suspended. Its users were signed out."})


@bp.route("/api/platform/companies/<int:company_id>/activate", methods=["POST"])
def api_platform_activate_company(company_id):
    _need("platform.companies.manage")
    iam_service.set_company_status(_actor(), company_id, True, _body().get("reason"), _ip())
    return jsonify({"success": True, "message": "Company reactivated."})


PUBLIC_PATHS = frozenset({
    "/accept-invite", "/forgot-password", "/reset-password",
    "/api/auth/invite_info", "/api/auth/accept_invite", "/api/auth/forgot_password",
    "/api/auth/reset_password", "/api/auth/reset_link_status",
})
