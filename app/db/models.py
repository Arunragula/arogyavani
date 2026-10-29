
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON
from pgvector.sqlalchemy import Vector
from app.db.database import Base, IS_POSTGRES

VECTOR_DIM = 768


class FamilyMember(Base):
    __tablename__ = "family_members"

    member_id = Column(String(50), primary_key=True, index=True)  # e.g., "self", "mom", "dad"
    display_name = Column(String(100), nullable=False)            # e.g., "Amma (Mom)"
    relationship = Column(String(50), default="Self")             # e.g., "Mother", "Father", "Self"
    age = Column(String(30), nullable=True)                       # e.g., "54 Years"
    gender = Column(String(20), nullable=True)                    # e.g., "Female"
    blood_group = Column(String(15), nullable=True)               # e.g., "B+"
    known_conditions = Column(Text, nullable=True)                # e.g., "Type 2 Diabetes, Thyroid"
    created_at = Column(DateTime, default=datetime.utcnow)


class MedicalReport(Base):
    __tablename__ = "medical_reports"

    report_id = Column(String(50), primary_key=True, index=True)
    member_id = Column(String(50), index=True, nullable=False, default="self")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    document_hash = Column(String(64), index=True, nullable=True)
    filenames = Column(JSON, nullable=False)
    language = Column(String(30), default="English")
    demographics_json = Column(JSON, nullable=True)
    clean_anonymized_text = Column(Text, nullable=False)
    ai_analysis_json = Column(JSON, nullable=False)
    translations_json = Column(JSON, nullable=True)
    embedding = Column(Vector(VECTOR_DIM) if IS_POSTGRES else JSON, nullable=True)


class QATrainingLog(Base):
    __tablename__ = "qa_training_logs"

    id = Column(String(50), primary_key=True, index=True)
    member_id = Column(String(50), index=True, nullable=False, default="self")
    created_at = Column(DateTime, default=datetime.utcnow)
    language = Column(String(30), default="English")
    user_question = Column(Text, nullable=False)
    ai_response_json = Column(JSON, nullable=False)