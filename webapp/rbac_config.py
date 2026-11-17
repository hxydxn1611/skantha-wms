"""
RBAC rollout switch (RBAC plan D12).

RBAC_MODE (environment or .env), read once at startup:
  off      - only today's login check runs (default until Phase 2 ships)
  audit    - permission checks run and log `access.would_deny`, nothing is blocked
  enforce  - missing permissions are refused with 403

Phase 0 only provides the switch. Nothing reads it to block requests yet.
"""
import logging
import os

logger = logging.getLogger(__name__)

RBAC_MODES = ("off", "audit", "enforce")
_DEFAULT_MODE = "off"


def _read_mode() -> str:
    raw = (os.environ.get("RBAC_MODE") or _DEFAULT_MODE).strip().lower()
    if raw not in RBAC_MODES:
        logger.warning("RBAC_MODE=%r is not one of %s; using %r", raw, RBAC_MODES, _DEFAULT_MODE)
        return _DEFAULT_MODE
    return raw


RBAC_MODE = _read_mode()


def get_rbac_mode() -> str:
    return RBAC_MODE


def is_enforcing() -> bool:
    return RBAC_MODE == "enforce"


def is_auditing() -> bool:
    return RBAC_MODE in ("audit", "enforce")
