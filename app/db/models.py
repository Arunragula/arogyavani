# app/db/models.py
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, LargeBinary
from pgvector.sqlalchemy import Vector
from app.db.database import Base, IS_POSTGRES

VECTOR_DIM = 768


class VaultAccessRole(Base):
    __tablename__ = "vault_access_roles"

    code_hash = Column(String(64), primary_key=True, index=True)
    household_id = Column(String(64), index=True, nullable=False)
    label = Column(String(100), default="Vault Owner")
    role = Column(String(20), nullable=False, default="owner")
    allowed_member_id = Column(String(50), default="*")
    wrapped_vault_key = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class FamilyMember(Base):
    __tablename__ = "family_members"

    id = Column(String(80), primary_key=True, index=True)
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

    demographics_enc = Column(Text, nullable=True)
    clean_text_enc = Column(Text, nullable=False)
    ai_analysis_enc = Column(Text, nullable=False)
    translations_enc = Column(Text, nullable=True)
    attached_prescriptions_enc = Column(Text, nullable=True)

    embedding = Column(Vector(VECTOR_DIM) if IS_POSTGRES else JSON, nullable=True)


class VaultFileBlob(Base):
    """
    Stores the ~120 KB compressed, AES-256 encrypted file bytes directly in Neon Postgres
    so Render container restarts/deploys NEVER lose uploaded report images!
    """
    __tablename__ = "vault_file_blobs"

    file_id = Column(String(90), primary_key=True, index=True)
    report_id = Column(String(64), index=True, nullable=False)
    household_id = Column(String(64), index=True, nullable=False)
    mime_type = Column(String(50), default="image/webp")
    encrypted_bytes = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class QATrainingLog(Base):
    """Tracks all daily household quotas ('report', 'question', 'speech') so save_to_vault=false cannot bypass limits."""
    __tablename__ = "qa_training_logs"

    id = Column(String(64), primary_key=True, index=True)
    household_id = Column(String(64), index=True, nullable=False)
    action_type = Column(String(20), index=True, default="question")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)