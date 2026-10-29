# app/services/db_vector.py
import os
import uuid
import hashlib
import numpy as np
from sqlalchemy import func, text
from sqlalchemy.orm.attributes import flag_modified
from app.db.database import engine, SessionLocal, Base, IS_POSTGRES, init_pgvector_extension
from app.db.models import FamilyMember, MedicalReport, QATrainingLog
from app.services.embeddings import generate_local_embedding
from app.services.analyzer import translate_locked_report

VAULT_FILES_DIR = "vault_uploads"
os.makedirs(VAULT_FILES_DIR, exist_ok=True)

init_pgvector_extension()
Base.metadata.create_all(bind=engine)


def auto_upgrade_sqlite_schema():
    """Ensures existing health_vault.db automatically gets new columns without errors."""
    if not IS_POSTGRES:
        with engine.connect() as conn:
            for col_name, col_type in [
                ("document_hash", "VARCHAR(64)"),
                ("translations_json", "JSON"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE medical_reports ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    pass


auto_upgrade_sqlite_schema()


def save_physical_files_to_vault(report_id: str, files_data: list) -> list[dict]:
    """
    Saves the actual uploaded images/PDFs to disk (`vault_uploads/`) so the patient
    can view or show the original report to their doctor months later.
    """
    stored_files = []
    for idx, (orig_name, file_bytes) in enumerate(files_data, start=1):
        ext = orig_name.split(".")[-1].lower() if "." in orig_name else "jpg"
        safe_name = f"{report_id}_page{idx}.{ext}"
        filepath = os.path.join(VAULT_FILES_DIR, safe_name)

        with open(filepath, "wb") as f:
            f.write(file_bytes)

        stored_files.append({
            "page": idx,
            "filename": orig_name,
            "url": f"/vault-files/{safe_name}",
            "is_pdf": ext == "pdf",
        })
    return stored_files


def normalize_stored_files(filenames_col) -> list[dict]:
    """Handles both new dict file objects and older string filenames gracefully."""
    if not filenames_col:
        return []
    normalized = []
    for item in filenames_col:
        if isinstance(item, dict):
            normalized.append(item)
        elif isinstance(item, str):
            normalized.append({"page": 1, "filename": item, "url": None, "is_pdf": item.lower().endswith(".pdf")})
    return normalized


def compute_document_hash(member_id: str, doc_category: str, files_data: list) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"{member_id.lower().strip()}:{doc_category}:".encode("utf-8"))
    for _, file_bytes in files_data:
        hasher.update(file_bytes)
    return hasher.hexdigest()


def get_cached_report_by_hash(doc_hash: str, requested_language: str) -> dict | None:
    lang_key = requested_language.strip().capitalize()
    db = SessionLocal()
    try:
        record = db.query(MedicalReport).filter(MedicalReport.document_hash == doc_hash).first()
        if not record:
            return None

        translations = dict(record.translations_json or {})
        if not translations and record.ai_analysis_json:
            translations[record.language] = record.ai_analysis_json

        if lang_key in translations:
            ai_output = translations[lang_key]
        else:
            ai_output = translate_locked_report(record.ai_analysis_json, lang_key)
            translations[lang_key] = ai_output
            record.translations_json = translations
            record.language = lang_key
            flag_modified(record, "translations_json")
            db.commit()

        return {
            "report_id": record.report_id,
            "member_id": record.member_id,
            "date_uploaded": record.created_at.strftime("%d %b %Y, %I:%M %p") if record.created_at else "",
            "selected_language": lang_key,
            "loaded_from_vault_cache": True,
            "stored_files": normalize_stored_files(record.filenames),
            "demographics": record.demographics_json,
            "ai_explanation": ai_output,
        }
    finally:
        db.close()


def translate_existing_vault_record(report_id: str, target_language: str) -> dict | None:
    lang_key = target_language.strip().capitalize()
    db = SessionLocal()
    try:
        record = db.query(MedicalReport).filter(MedicalReport.report_id == report_id).first()
        if not record:
            return None

        translations = dict(record.translations_json or {})
        if not translations and record.ai_analysis_json:
            translations[record.language or "English"] = record.ai_analysis_json

        if lang_key not in translations:
            translations[lang_key] = translate_locked_report(record.ai_analysis_json, lang_key)
            record.translations_json = translations
            flag_modified(record, "translations_json")
            db.commit()

        return {
            "report_id": record.report_id,
            "member_id": record.member_id,
            "date_uploaded": record.created_at.strftime("%d %b %Y, %I:%M %p") if record.created_at else "",
            "selected_language": lang_key,
            "loaded_from_vault_cache": True,
            "stored_files": normalize_stored_files(record.filenames),
            "demographics": record.demographics_json,
            "ai_explanation": translations[lang_key],
        }
    finally:
        db.close()


def ensure_member_exists(db, member_id: str, demographics: dict = None):
    clean_id = member_id.lower().strip()
    existing = db.query(FamilyMember).filter(FamilyMember.member_id == clean_id).first()
    if not existing:
        existing = FamilyMember(
            member_id=clean_id,
            display_name=clean_id.capitalize(),
            relationship="Self" if clean_id == "self" else "Family Member",
            age=demographics.get("age") if demographics else None,
            gender=demographics.get("gender") if demographics else None,
        )
        db.add(existing)
        db.commit()


def save_report_to_db(
    member_id: str,
    document_hash: str,
    files_data: list,
    language: str,
    demographics: dict,
    clean_text: str,
    ai_analysis: dict,
) -> dict:
    report_id = f"rep_{uuid.uuid4().hex[:10]}"
    clean_member = member_id.lower().strip()
    lang_key = language.strip().capitalize()

    # Save physical images/PDFs to vault_uploads/ so patient can show doctor later
    stored_files = save_physical_files_to_vault(report_id, files_data)

    searchable_summary = (
        f"Report Type: {ai_analysis.get('report_type', '')}\n"
        f"Overall: {ai_analysis.get('overall_status', '')}\n"
        f"Raw Text: {clean_text}"
    )
    embedding_vec = generate_local_embedding(searchable_summary)

    db = SessionLocal()
    try:
        ensure_member_exists(db, clean_member, demographics)

        new_report = MedicalReport(
            report_id=report_id,
            member_id=clean_member,
            document_hash=document_hash,
            filenames=stored_files,
            language=lang_key,
            demographics_json=demographics,
            clean_anonymized_text=clean_text,
            ai_analysis_json=ai_analysis,
            translations_json={lang_key: ai_analysis},
            embedding=embedding_vec,
        )
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        return {
            "report_id": report_id,
            "date_uploaded": new_report.created_at.strftime("%d %b %Y, %I:%M %p"),
            "stored_files": stored_files,
            "available_languages": [lang_key],
        }
    finally:
        db.close()


def create_or_update_family_member(payload_dict: dict) -> dict:
    db = SessionLocal()
    try:
        clean_id = payload_dict["member_id"].lower().strip()
        member = db.query(FamilyMember).filter(FamilyMember.member_id == clean_id).first()
        if member:
            member.display_name = payload_dict["display_name"]
            member.relationship = payload_dict.get("relationship", member.relationship)
            member.age = payload_dict.get("age") or member.age
            member.gender = payload_dict.get("gender") or member.gender
            member.blood_group = payload_dict.get("blood_group") or member.blood_group
            member.known_conditions = payload_dict.get("known_conditions") or member.known_conditions
        else:
            member = FamilyMember(
                member_id=clean_id,
                display_name=payload_dict["display_name"],
                relationship=payload_dict.get("relationship", "Family"),
                age=payload_dict.get("age"),
                gender=payload_dict.get("gender"),
                blood_group=payload_dict.get("blood_group"),
                known_conditions=payload_dict.get("known_conditions"),
            )
            db.add(member)
        db.commit()
        db.refresh(member)
        return {
            "member_id": member.member_id,
            "display_name": member.display_name,
            "relationship": member.relationship,
            "age": member.age,
            "gender": member.gender,
            "blood_group": member.blood_group,
            "known_conditions": member.known_conditions,
        }
    finally:
        db.close()


def list_all_family_members() -> list:
    db = SessionLocal()
    try:
        # Also include any member_ids that exist in medical_reports
        report_member_ids = [r[0] for r in db.query(MedicalReport.member_id).distinct().all() if r[0]]
        for m_id in report_member_ids:
            ensure_member_exists(db, m_id)

        members = db.query(FamilyMember).order_by(FamilyMember.created_at.asc()).all()
        result = []
        for m in members:
            count = (
                db.query(func.count(MedicalReport.report_id))
                .filter(MedicalReport.member_id == m.member_id)
                .scalar()
            )
            result.append({
                "member_id": m.member_id,
                "display_name": m.display_name,
                "relationship": m.relationship,
                "age": m.age,
                "gender": m.gender,
                "blood_group": m.blood_group,
                "known_conditions": m.known_conditions,
                "total_records_stored": count,
            })
        return result
    finally:
        db.close()


def get_member_timeline(member_id: str) -> dict:
    clean_id = member_id.lower().strip()
    db = SessionLocal()
    try:
        member = db.query(FamilyMember).filter(FamilyMember.member_id == clean_id).first()
        reports = (
            db.query(MedicalReport)
            .filter(MedicalReport.member_id == clean_id)
            .order_by(MedicalReport.created_at.desc())
            .all()
        )
        timeline = []
        for r in reports:
            ai_data = r.ai_analysis_json or {}
            category = ai_data.get("document_category", "lab_report")
            timeline.append({
                "report_id": r.report_id,
                "date_uploaded": r.created_at.strftime("%d %b %Y, %I:%M %p") if r.created_at else "Saved Record",
                "category": category,
                "report_type": ai_data.get("report_type", "Medical Document"),
                "overall_status": ai_data.get("overall_status", ""),
                "language": r.language,
                "stored_files": normalize_stored_files(r.filenames),
                "ai_explanation": ai_data,
            })

        return {
            "member_profile": {
                "member_id": clean_id,
                "display_name": member.display_name if member else clean_id.capitalize(),
                "relationship": member.relationship if member else "Self",
                "age": member.age if member else None,
                "gender": member.gender if member else None,
                "blood_group": member.blood_group if member else None,
                "known_conditions": member.known_conditions if member else None,
            },
            "total_records": len(timeline),
            "timeline": timeline,
        }
    finally:
        db.close()


def get_single_vault_record(report_id: str, language: str = None) -> dict:
    db = SessionLocal()
    try:
        r = db.query(MedicalReport).filter(MedicalReport.report_id == report_id).first()
        if not r:
            return None

        translations = dict(r.translations_json or {})
        if not translations and r.ai_analysis_json:
            translations[r.language or "English"] = r.ai_analysis_json

        target_lang = (language or r.language or "English").strip().capitalize()
        if target_lang in translations:
            ai_data = translations[target_lang]
        else:
            ai_data = r.ai_analysis_json

        return {
            "report_id": r.report_id,
            "member_id": r.member_id,
            "date_uploaded": r.created_at.strftime("%d %b %Y, %I:%M %p") if r.created_at else "",
            "selected_language": target_lang,
            "stored_files": normalize_stored_files(r.filenames),
            "demographics": r.demographics_json,
            "ai_explanation": ai_data,
        }
    finally:
        db.close()


def delete_vault_record(report_id: str) -> bool:
    db = SessionLocal()
    try:
        r = db.query(MedicalReport).filter(MedicalReport.report_id == report_id).first()
        if not r:
            return False
        db.delete(r)
        db.commit()
        return True
    finally:
        db.close()


def search_member_history_vectors(member_id: str, query: str, top_k: int = 3) -> list:
    query_vec = generate_local_embedding(query)
    clean_member = member_id.lower().strip()
    db = SessionLocal()
    try:
        rows = (
            db.query(MedicalReport)
            .filter(MedicalReport.member_id == clean_member)
            .order_by(MedicalReport.created_at.desc())
            .all()
        )
        if not rows:
            return []
        q_arr = np.array(query_vec, dtype=float)
        scored = []
        for r in rows:
            sim = (
                float(np.dot(q_arr, np.array(r.embedding, dtype=float)))
                if r.embedding and len(r.embedding) == len(q_arr)
                else 0.0
            )
            scored.append({
                "report_id": r.report_id,
                "date": r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
                "sim": sim,
                "clean_text": r.clean_anonymized_text,
                "ai_summary": (r.ai_analysis_json or {}).get("overall_status", ""),
            })
        scored.sort(key=lambda x: x["sim"], reverse=True)
        return scored[:top_k]
    finally:
        db.close()


def save_qa_log(member_id: str, language: str, question: str, ai_response: dict):
    db = SessionLocal()
    try:
        db.add(
            QATrainingLog(
                id=f"qa_{uuid.uuid4().hex[:10]}",
                member_id=member_id.lower().strip(),
                language=language,
                user_question=question,
                ai_response_json=ai_response,
            )
        )
        db.commit()
    finally:
        db.close()


def export_training_dataset() -> list:
    db = SessionLocal()
    try:
        rows = db.query(MedicalReport).all()
        return [
            {
                "instruction": f"Analyze this anonymized medical document in {r.language}.",
                "input": r.clean_anonymized_text,
                "output": r.ai_analysis_json,
            }
            for r in rows
        ]
    finally:
        db.close()