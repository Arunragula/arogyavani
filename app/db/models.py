# app/db/models.py
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON
from pgvector.sqlalchemy import Vector
from app.db.database import Base, IS_POSTGRES

VECTOR_DIM = 768


class VaultAccessRole(Base):
    """
    Stores Role-Based Access Codes for a Family Vault:
    - role: 'owner' (creator), 'editor' (can upload/view), 'viewer' (read/listen only)
    - allowed_member_id: '*' (all family members) OR specific member like 'mom'
    - wrapped_vault_key: AES-256 master key wrapped with this user's secret code
    """
    __tablename__ = "vault_access_roles"

    code_hash = Column(String(64), primary_key=True, index=True)  # SHA-256 of the invite/share code
    household_id = Column(String(64), index=True, nullable=False)
    label = Column(String(100), default="Vault Owner")            # e.g., "Mom (Viewer Only)", "Spouse (Editor)"
    role = Column(String(20), nullable=False, default="owner")    # 'owner' | 'editor' | 'viewer'
    allowed_member_id = Column(String(50), default="*")           # '*' or specific profile like 'mom'
    wrapped_vault_key = Column(Text, nullable=False)              # Zero-knowledge wrapped key
    created_at = Column(DateTime, default=datetime.utcnow)


class FamilyMember(Base):
    __tablename__ = "family_members"

    id = Column(String(80), primary_key=True, index=True)         # "{household_id}:{member_id}"
    household_id = Column(String(64), index=True, nullable=False)
    member_id = Column(String(50), index=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    relationship = Column(String(50), default="Self")
    age = Column(String(30), nullable=True)
    gender = Column(String(20), nullable=True)
    blood_group = Column(String(15), nullable=True)
    known_conditions = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MedicalReport(Base):
    __tablename__ = "medical_reports"

    report_id = Column(String(64), primary_key=True, index=True)
    household_id = Column(String(64), index=True, nullable=False)
    member_id = Column(String(50), index=True, nullable=False, default="self")
    document_hash = Column(String(64), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    filenames = Column(JSON, nullable=False)
    language = Column(String(30), default="English")

    # ZERO-KNOWLEDGE ENCRYPTED COLUMNS (Unreadable in DB without user's secret code!)
    demographics_enc = Column(Text, nullable=True)
    clean_text_enc = Column(Text, nullable=False)
    ai_analysis_enc = Column(Text, nullable=False)
    translations_enc = Column(Text, nullable=True)
    attached_prescriptions_enc = Column(Text, nullable=True)  # <-- Linked Prescriptions under this Report!

    embedding = Column(Vector(VECTOR_DIM) if IS_POSTGRES else JSON, nullable=True)


class QATrainingLog(Base):
    """Used strictly for counting daily per-household question & speech quotas."""
    __tablename__ = "qa_training_logs"

    id = Column(String(64), primary_key=True, index=True)
    household_id = Column(String(64), index=True, nullable=False)
    action_type = Column(String(20), index=True, default="question")  # 'question' or 'speech'
    created_at = Column(DateTime, default=datetime.utcnow, index=True)