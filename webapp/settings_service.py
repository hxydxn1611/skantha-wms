"""
Platform and per-company settings (RBAC Phase 7).

  platform_settings   one value per key for the whole installation (e.g. rtmp.stream_key)
  company_settings    one value per (company, key)  (e.g. copilot.web_search, audit.retention_days)

Values are stored as JSON. Reads never raise: before migration 010 has run they return
the default, so nothing breaks on an old database.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import string
import threading
from typing import Any, Optional

import db

COMPANY_DEFAULTS = {
    "copilot.web_search": False,     # H16: off by default
    "audit.retention_days": 365,
}

_lock = threading.Lock()
_rtmp_key_cache: Optional[str] = None


def _conn():
    return sqlite3.connect(db.DB_PATH, timeout=15)


def get_platform(key: str, default: Any = None) -> Any:
    try:
        c = _conn()
        try:
            row = c.execute("SELECT value_json FROM platform_settings WHERE key = ?", (key,)).fetchone()
        finally:
            c.close()
        return json.loads(row[0]) if row and row[0] is not None else default
    except (sqlite3.Error, ValueError):
        return default


def set_platform(key: str, value: Any, user_id: Optional[int] = None) -> None:
    c = _conn()
    try:
        with c:
            c.execute("""INSERT INTO platform_settings (key, value_json, updated_by, updated_at)
                         VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                         ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                         updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP""",
                      (key, json.dumps(value), user_id))
    finally:
        c.close()


def get_company(company_id: Optional[int], key: str) -> Any:
    default = COMPANY_DEFAULTS.get(key)
    if not company_id:
        return default
    try:
        c = _conn()
        try:
            row = c.execute("SELECT value_json FROM company_settings WHERE company_id = ? AND key = ?",
                            (company_id, key)).fetchone()
        finally:
            c.close()
        return json.loads(row[0]) if row and row[0] is not None else default
    except (sqlite3.Error, ValueError):
        return default


def set_company(company_id: int, key: str, value: Any, user_id: Optional[int] = None) -> None:
    if key not in COMPANY_DEFAULTS:
        raise KeyError(key)
    c = _conn()
    try:
        with c:
            c.execute("""INSERT INTO company_settings (company_id, key, value_json, updated_by, updated_at)
                         VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                         ON CONFLICT(company_id, key) DO UPDATE SET value_json = excluded.value_json,
                         updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP""",
                      (company_id, key, json.dumps(value), user_id))
    finally:
        c.close()


def company_settings(company_id: Optional[int]) -> dict:
    return {k: get_company(company_id, k) for k in COMPANY_DEFAULTS}


# ----------------------------------------------------------------------------- RTMP stream key (H7)
def rtmp_stream_key() -> str:
    """RTMP_STREAM_KEY from the environment, otherwise a random key generated once and kept
    in platform_settings. Cached in memory (the RTMP gate asks on every connection)."""
    global _rtmp_key_cache
    env = (os.environ.get("RTMP_STREAM_KEY") or "").strip()
    if env:
        return env
    if _rtmp_key_cache:
        return _rtmp_key_cache
    with _lock:
        if _rtmp_key_cache:
            return _rtmp_key_cache
        key = get_platform("rtmp.stream_key")
        if not key:
            alphabet = string.ascii_letters + string.digits
            key = "".join(secrets.choice(alphabet) for _ in range(20))
            try:
                set_platform("rtmp.stream_key", key)
            except sqlite3.Error:
                pass  # settings table not there yet: keep it for this run only
        _rtmp_key_cache = key
        return key


def rotate_rtmp_stream_key(user_id: Optional[int] = None) -> str:
    global _rtmp_key_cache
    alphabet = string.ascii_letters + string.digits
    key = "".join(secrets.choice(alphabet) for _ in range(20))
    set_platform("rtmp.stream_key", key, user_id)
    _rtmp_key_cache = key
    return key
