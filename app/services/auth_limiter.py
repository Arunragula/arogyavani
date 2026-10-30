# app/services/auth_limiter.py
import os
import time
import uuid
from datetime import datetime, timedelta
from fastapi import Header, HTTPException, Request
from sqlalchemy import func
from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv

from app.db.database import SessionLocal
from app.db.models import VaultAccessRole, QATrainingLog
from app.services.crypto_vault import (
    hash_invite_code,
    derive_fernet_key_from_code,
    wrap_vault_key_for_role_code,
    unwrap_vault_key_with_role_code,
)

load_dotenv()


def get_real_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=get_real_client_ip)

# Validate INVITE_CODES at startup (No public fallback allowed!)
_raw_codes = os.getenv("INVITE_CODES", "").strip()
if not _raw_codes:
    raise RuntimeError("CRITICAL CONFIG ERROR: INVITE_CODES environment variable must be set.")

CONFIGURED_OWNER_CODES = {c.strip() for c in _raw_codes.split(",") if c.strip()}
for _c in CONFIGURED_OWNER_CODES:
    if len(_c) < 12:
        raise RuntimeError("CRITICAL CONFIG ERROR: Every code in INVITE_CODES must be at least 12 characters long.")

DAILY_LIMITS = {
    "report": 10,     # Counts ALL analyses (reports, prescriptions, attached rx, translations)
    "question": 30,
    "speech": 30,
}

# P0 #1: Failed Auth Brute-Force Tracker (5 failed attempts -> 15 min lockout per IP)
_FAILED_ATTEMPTS: dict[str, list[float]] = {}
MAX_AUTH_FAILURES = 5
LOCKOUT_WINDOW_SECONDS = 15 * 60


def _check_ip_lockout(ip: str):
    now = time.time()
    attempts = [t for t in _FAILED_ATTEMPTS.get(ip, []) if now - t < LOCKOUT_WINDOW_SECONDS]
    _FAILED_ATTEMPTS[ip] = attempts
    if len(attempts) >= MAX_AUTH_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Too many failed invite code attempts. Please wait 15 minutes before trying again.",
        )


def _record_ip_failure(ip: str):
    now = time.time()
    attempts = [t for t in _FAILED_ATTEMPTS.get(ip, []) if now - t < LOCKOUT_WINDOW_SECONDS]
    attempts.append(now)
    _FAILED_ATTEMPTS[ip] = attempts


def _clear_ip_failures(ip: str):
    _FAILED_ATTEMPTS.pop(ip, None)


def verify_vault_access(
    request: Request,
    x_invite_code: str = Header(..., description="Household Invite Code or Server-Generated Role Code"),
) -> dict:
    client_ip = get_real_client_ip(request)
    _check_ip_lockout(client_ip)

    code = x_invite_code.strip()
    if not code:
        _record_ip_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invite code is required.")

    code_hash = hash_invite_code(code)

    db = SessionLocal()
    try:
        role_record = db.query(VaultAccessRole).filter(VaultAccessRole.code_hash == code_hash).first()

        if role_record:
            # P1 #8: If this is an 'owner' row, verify the code is STILL in INVITE_CODES env var!
            if role_record.role == "owner" and code not in CONFIGURED_OWNER_CODES:
                db.delete(role_record)
                db.commit()
                _record_ip_failure(client_ip)
                raise HTTPException(status_code=401, detail="This owner invite code has been revoked.")

            vault_key = unwrap_vault_key_with_role_code(role_record.wrapped_vault_key, code)
            _clear_ip_failures(client_ip)
            return {
                "household_id": role_record.household_id,
                "role": role_record.role,
                "label": role_record.label,
                "allowed_member_id": role_record.allowed_member_id,
                "vault_key": vault_key,
            }

        # First-time use of a valid Owner Code from INVITE_CODES
        if code in CONFIGURED_OWNER_CODES:
            household_id = f"hh_{code_hash[:16]}"
            master_key = derive_fernet_key_from_code(f"master:{code}")
            wrapped = wrap_vault_key_for_role_code(master_key, code)

            new_owner = VaultAccessRole(
                code_hash=code_hash,
                household_id=household_id,
                label="Vault Creator (Owner)",
                role="owner",
                allowed_member_id="*",
                wrapped_vault_key=wrapped,
            )
            db.add(new_owner)
            db.commit()
            _clear_ip_failures(client_ip)

            return {
                "household_id": household_id,
                "role": "owner",
                "label": "Vault Creator (Owner)",
                "allowed_member_id": "*",
                "vault_key": master_key,
            }

        _record_ip_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid Invite Code.")
    finally:
        db.close()


def enforce_member_scope(auth: dict, target_member_id: str):
    """P1 #7: Ensures a role code locked to e.g. 'mom' cannot access or query 'dad' or 'self'."""
    allowed = auth.get("allowed_member_id", "*")
    if allowed != "*" and allowed != target_member_id.lower().strip():
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Your code is restricted to family profile '{allowed}' only.",
        )


def require_write_permission(auth: dict, target_member_id: str = "*"):
    if auth["role"] == "viewer":
        raise HTTPException(
            status_code=403,
            detail="View-Only Access: Your code has 'Viewer' permission and cannot upload or modify records.",
        )
    if target_member_id != "*":
        enforce_member_scope(auth, target_member_id)


def require_owner_permission(auth: dict):
    if auth["role"] != "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner Permission Required: Only the Vault Creator can delete records or manage family roles.",
        )


def check_and_increment_daily_quota(household_id: str, action: str):
    """
    P1 #6 Fix: Logs EVERY analysis ('report', 'question', 'speech') in QATrainingLog
    so save_to_vault=false, attach-prescription, and translations cannot bypass daily quotas!
    """
    since = datetime.utcnow() - timedelta(hours=24)
    limit = DAILY_LIMITS.get(action, 20)

    db = SessionLocal()
    try:
        used = (
            db.query(func.count(QATrainingLog.id))
            .filter(
                QATrainingLog.household_id == household_id,
                QATrainingLog.action_type == action,
                QATrainingLog.created_at >= since,
            )
            .scalar()
        )

        if used >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Daily household limit reached ({limit} {action}s per 24 hours). Please try again tomorrow.",
            )

        db.add(
            QATrainingLog(
                id=str(uuid.uuid4()),
                household_id=household_id,
                action_type=action,
            )
        )
        db.commit()
    finally:
        db.close()