# app/services/auth_limiter.py
import os
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import Header, HTTPException, Depends
from sqlalchemy import func
from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv

from app.db.database import SessionLocal
from app.db.models import VaultAccessRole, MedicalReport, QATrainingLog
from app.services.crypto_vault import (
    hash_invite_code,
    derive_fernet_key_from_code,
    wrap_vault_key_for_role_code,
    unwrap_vault_key_with_role_code,
)

load_dotenv()

# Per-IP Rate Limiter (20 requests/minute as specified in the launch review)
limiter = Limiter(key_func=get_remote_address)

DAILY_LIMITS = {
    "report": 10,     # Max 10 report/prescription scans per household per day
    "question": 30,   # Max 30 health AI questions per household per day
    "speech": 30,     # Max 30 TTS speech requests per household per day
}


def get_configured_owner_codes() -> set[str]:
    raw = os.getenv("INVITE_CODES", "ARUN-FAMILY-2026,TEST-HOUSEHOLD-01")
    return {c.strip() for c in raw.split(",") if c.strip()}


def verify_vault_access(
    x_invite_code: str = Header(..., description="Household Invite Code or Role Share Code")
) -> dict:
    """
    Authenticates the user via X-Invite-Code without ever storing the raw code in DB.
    Returns:
      - household_id: Isolated tenant ID
      - role: 'owner' | 'editor' | 'viewer'
      - allowed_member_id: '*' or specific member_id (e.g., 'mom')
      - vault_key: 256-bit AES key in memory to decrypt/encrypt this household's vault
    """
    code = x_invite_code.strip()
    if not code:
        raise HTTPException(status_code=401, detail="Invite code is required.")

    code_hash = hash_invite_code(code)
    owner_codes = get_configured_owner_codes()

    db = SessionLocal()
    try:
        # 1. Check if this code already exists in VaultAccessRole table
        role_record = db.query(VaultAccessRole).filter(VaultAccessRole.code_hash == code_hash).first()

        if role_record:
            vault_key = unwrap_vault_key_with_role_code(role_record.wrapped_vault_key, code)
            return {
                "household_id": role_record.household_id,
                "role": role_record.role,
                "label": role_record.label,
                "allowed_member_id": role_record.allowed_member_id,
                "vault_key": vault_key,
            }

        # 2. If not in DB yet, check if it is a master owner code from .env INVITE_CODES
        if code in owner_codes:
            household_id = f"hh_{code_hash[:16]}"
            # Derive initial deterministic master key for this owner code
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

            return {
                "household_id": household_id,
                "role": "owner",
                "label": "Vault Creator (Owner)",
                "allowed_member_id": "*",
                "vault_key": master_key,
            }

        raise HTTPException(
            status_code=401,
            detail="Invalid Invite Code. Please enter a valid Household Invite Code or Family Role Code.",
        )
    finally:
        db.close()


def require_write_permission(auth: dict, target_member_id: str = "*"):
    """Ensures 'viewer' role cannot upload, edit, or delete, and checks member scope."""
    if auth["role"] == "viewer":
        raise HTTPException(
            status_code=403,
            detail="View-Only Access: Your code has 'Viewer' permission and cannot upload or modify records.",
        )
    if auth["allowed_member_id"] != "*" and target_member_id != "*":
        if auth["allowed_member_id"] != target_member_id.lower().strip():
            raise HTTPException(
                status_code=403,
                detail=f"Your access code is restricted to profile '{auth['allowed_member_id']}' only.",
            )


def require_owner_permission(auth: dict):
    """Only the Vault Creator ('owner') can delete records or assign family roles."""
    if auth["role"] != "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner Permission Required: Only the Vault Creator can delete records or manage family roles.",
        )


def check_and_increment_daily_quota(household_id: str, action: str):
    """
    Enforces daily household quotas from DB rows (survives Render restarts!):
    - 10 reports/prescriptions per day
    - 30 questions per day
    - 30 speech requests per day
    """
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    limit = DAILY_LIMITS.get(action, 20)

    db = SessionLocal()
    try:
        if action == "report":
            used = (
                db.query(func.count(MedicalReport.report_id))
                .filter(
                    MedicalReport.household_id == household_id,
                    MedicalReport.created_at >= since,
                )
                .scalar()
            )
        else:
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
                detail=f"Daily household limit reached ({limit} {action}s per day). Please try again tomorrow.",
            )

        if action in ("question", "speech"):
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