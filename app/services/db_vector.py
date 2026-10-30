# app/services/db_vector.py
import os
import uuid
import hashlib
import numpy as np
from sqlalchemy import func
from app.db.database import engine, SessionLocal, Base, IS_POSTGRES, init_pgvector_extension
from app.db.models import VaultAccessRole, FamilyMember, MedicalReport
from app.services.embeddings import generate_local_embedding
from app.services.analyzer import translate_locked_report
from app.services.crypto_vault import (
    hash_invite_code,
    wrap_vault_key_for_role_code,
    encrypt_json_with_key,
    decrypt_json_with_key,
    encrypt_bytes_with_key,
    decrypt_bytes_with_key,
    compress_image_for_free_storage,
)

VAULT_FILES_DIR = "vault_uploads"
os.makedirs(VAULT_FILES_DIR, exist_ok=True)

init_pgvector_extension()
Base.metadata.create_all(bind=engine)


# =========================================================
# 1. COMPRESSED & ENCRYPTED FILE STORAGE
# =========================================================

def save_encrypted_files_to_vault(
    report_id: str, files_data: list, vault_key: bytes, prefix: str = "doc"
) -> list[dict]:
    """
    1. Compresses 6 MB images down to ~120 KB WebP.
    2. Encrypts the bytes with the user's secret AES-256 vault_key so nobody else can view them.
    """
    stored_files = []
    for idx, (orig_name, raw_bytes) in enumerate(files_data, start=1):
        compressed_bytes, mime_type = compress_image_for_free_storage(raw_bytes, orig_name)
        encrypted_bytes = encrypt_bytes_with_key(compressed_bytes, vault_key)

        file_id = f"{report_id}_{prefix}_{idx}.enc"
        filepath = os.path.join(VAULT_FILES_DIR, file_id)
        with open(filepath, "wb") as f:
            f.write(encrypted_bytes)

        stored_files.append({
            "file_id": file_id,
            "filename": orig_name,
            "mime_type": mime_type,
            "is_pdf": mime_type == "application/pdf",
            "size_kb": round(len(compressed_bytes) / 1024, 1),
        })
    return stored_files


def read_decrypted_vault_file(household_id: str, report_id: str, file_id: str, vault_key: bytes) -> tuple[bytes, str]:
    """Verifies household ownership and decrypts the requested image/PDF in memory."""
    db = SessionLocal()
    try:
        record = (
            db.query(MedicalReport)
            .filter(
                MedicalReport.report_id == report_id,
                MedicalReport.household_id == household_id,
            )
            .first()
        )
        if not record:
            raise FileNotFoundError("Record not found or access denied.")

        # Prevent path traversal
        safe_file_id = os.path.basename(file_id)
        if not safe_file_id.startswith(report_id):
            raise FileNotFoundError("Invalid file reference.")

        filepath = os.path.join(VAULT_FILES_DIR, safe_file_id)
        if not os.path.exists(filepath):
            raise FileNotFoundError("Encrypted file not found on storage.")

        with open(filepath, "rb") as f:
            encrypted_bytes = f.read()

        decrypted_bytes = decrypt_bytes_with_key(encrypted_bytes, vault_key)

        # Look up mime_type
        mime_type = "image/webp"
        for item in (record.filenames or []):
            if isinstance(item, dict) and item.get("file_id") == safe_file_id:
                mime_type = item.get("mime_type", "image/webp")
        return decrypted_bytes, mime_type
    finally:
        db.close()


# =========================================================
# 2. DETERMINISTIC HASH & ENCRYPTED REPORT STORAGE
# =========================================================

def compute_document_hash(household_id: str, member_id: str, doc_category: str, files_data: list) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"{household_id}:{member_id.lower().strip()}:{doc_category}:".encode("utf-8"))
    for _, file_bytes in files_data:
        hasher.update(file_bytes)
    return hasher.hexdigest()


def get_cached_report_by_hash(
    household_id: str, doc_hash: str, requested_language: str, vault_key: bytes
) -> dict | None:
    lang_key = requested_language.strip().capitalize()
    db = SessionLocal()
    try:
        record = (
            db.query(MedicalReport)
            .filter(
                MedicalReport.household_id == household_id,
                MedicalReport.document_hash == doc_hash,
            )
            .first()
        )
        if not record:
            return None

        canonical_json = decrypt_json_with_key(record.ai_analysis_enc, vault_key)
        translations = decrypt_json_with_key(record.translations_enc, vault_key) or {}
        if not translations and canonical_json:
            translations[record.language] = canonical_json

        if lang_key in translations:
            ai_output = translations[lang_key]
        else:
            ai_output = translate_locked_report(canonical_json, lang_key)
            translations[lang_key] = ai_output
            record.translations_enc = encrypt_json_with_key(translations, vault_key)
            record.language = lang_key
            db.commit()

        attached_rx = decrypt_json_with_key(record.attached_prescriptions_enc, vault_key) or []
        demographics = decrypt_json_with_key(record.demographics_enc, vault_key) or {}

        return {
            "report_id": record.report_id,
            "member_id": record.member_id,
            "date_uploaded": record.created_at.strftime("%d %b %Y, %I:%M %p") if record.created_at else "",
            "selected_language": lang_key,
            "loaded_from_vault_cache": True,
            "stored_files": record.filenames or [],
            "demographics": demographics,
            "ai_explanation": ai_output,
            "attached_prescriptions": attached_rx,
        }
    finally:
        db.close()


def ensure_member_exists(db, household_id: str, member_id: str, demographics: dict = None):
    clean_id = member_id.lower().strip()
    pk = f"{household_id}:{clean_id}"
    existing = db.query(FamilyMember).filter(FamilyMember.id == pk).first()
    if not existing:
        existing = FamilyMember(
            id=pk,
            household_id=household_id,
            member_id=clean_id,
            display_name=clean_id.capitalize(),
            relationship="Self" if clean_id == "self" else "Family Member",
            age=demographics.get("age") if demographics else None,
            gender=demographics.get("gender") if demographics else None,
        )
        db.add(existing)
        db.commit()


def save_report_to_db(
    household_id: str,
    vault_key: bytes,
    member_id: str,
    document_hash: str,
    files_data: list,
    language: str,
    demographics: dict,
    clean_text: str,
    ai_analysis: dict,
) -> dict:
    report_id = f"rep_{uuid.uuid4().hex}"
    clean_member = member_id.lower().strip()
    lang_key = language.strip().capitalize()

    stored_files = save_encrypted_files_to_vault(report_id, files_data, vault_key, prefix="page")

    searchable_summary = (
        f"Report Type: {ai_analysis.get('report_type', '')}\n"
        f"Overall: {ai_analysis.get('overall_status', '')}\n"
        f"Raw Text: {clean_text}"
    )
    embedding_vec = generate_local_embedding(searchable_summary)

    db = SessionLocal()
    try:
        ensure_member_exists(db, household_id, clean_member, demographics)

        new_report = MedicalReport(
            report_id=report_id,
            household_id=household_id,
            member_id=clean_member,
            document_hash=document_hash,
            filenames=stored_files,
            language=lang_key,
            demographics_enc=encrypt_json_with_key(demographics, vault_key),
            clean_text_enc=encrypt_json_with_key({"text": clean_text}, vault_key),
            ai_analysis_enc=encrypt_json_with_key(ai_analysis, vault_key),
            translations_enc=encrypt_json_with_key({lang_key: ai_analysis}, vault_key),
            attached_prescriptions_enc=encrypt_json_with_key([], vault_key),
            embedding=embedding_vec,
        )
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        return {
            "report_id": report_id,
            "date_uploaded": new_report.created_at.strftime("%d %b %Y, %I:%M %p"),
            "stored_files": stored_files,
            "attached_prescriptions": [],
        }
    finally:
        db.close()


# =========================================================
# 3. ATTACH PRESCRIBED MEDICINES DIRECTLY TO A LAB REPORT!
# =========================================================

def get_report_context_for_prescription(household_id: str, report_id: str, vault_key: bytes) -> str:
    """Fetches the Lab Report summary so the attached prescription knows which report it is treating!"""
    db = SessionLocal()
    try:
        record = (
            db.query(MedicalReport)
            .filter(MedicalReport.report_id == report_id, MedicalReport.household_id == household_id)
            .first()
        )
        if not record:
            return ""
        ai_data = decrypt_json_with_key(record.ai_analysis_enc, vault_key) or {}
        att = ai_data.get("attention_needed", [])
        att_str = ", ".join(f"{x.get('item')}: {x.get('your_value')}" for x in att)
        return f"Linked Lab Report: {ai_data.get('report_type', '')}. Findings needing attention: {att_str}"
    finally:
        db.close()


def attach_prescription_to_existing_report(
    household_id: str,
    vault_key: bytes,
    report_id: str,
    files_data: list,
    rx_analysis: dict,
) -> dict | None:
    """
    Links decoded prescribed medicines + compressed prescription images directly inside
    the parent Lab Report so both stay intact in one single Family Vault card!
    """
    db = SessionLocal()
    try:
        record = (
            db.query(MedicalReport)
            .filter(MedicalReport.report_id == report_id, MedicalReport.household_id == household_id)
            .first()
        )
        if not record:
            return None

        existing_rx_list = decrypt_json_with_key(record.attached_prescriptions_enc, vault_key)
        if not isinstance(existing_rx_list, list):
            existing_rx_list = []

        rx_idx = len(existing_rx_list) + 1
        rx_files = save_encrypted_files_to_vault(report_id, files_data, vault_key, prefix=f"rx{rx_idx}")

        # Also append rx_files to record.filenames so the file decryptor recognizes them
        all_files = list(record.filenames or []) + rx_files
        record.filenames = all_files

        new_rx_entry = {
            "rx_id": f"rx_{uuid.uuid4().hex[:8]}",
            "stored_files": rx_files,
            "prescription_guide": rx_analysis,
        }
        existing_rx_list.append(new_rx_entry)
        record.attached_prescriptions_enc = encrypt_json_with_key(existing_rx_list, vault_key)
        db.commit()

        return {
            "report_id": report_id,
            "attached_prescriptions": existing_rx_list,
        }
    finally:
        db.close()


# =========================================================
# 4. FAMILY VAULT TIMELINE, TRANSLATION & ROLE MANAGEMENT
# =========================================================

def translate_existing_vault_record(
    household_id: str, report_id: str, target_language: str, vault_key: bytes
) -> dict | None:
    lang_key = target_language.strip().capitalize()
    db = SessionLocal()
    try:
        record = (
            db.query(MedicalReport)
            .filter(MedicalReport.report_id == report_id, MedicalReport.household_id == household_id)
            .first()
        )
        if not record:
            return None

        canonical_json = decrypt_json_with_key(record.ai_analysis_enc, vault_key)
        translations = decrypt_json_with_key(record.translations_enc, vault_key) or {}
        if lang_key not in translations:
            translations[lang_key] = translate_locked_report(canonical_json, lang_key)
            record.translations_enc = encrypt_json_with_key(translations, vault_key)
            db.commit()

        return {
            "report_id": record.report_id,
            "member_id": record.member_id,
            "date_uploaded": record.created_at.strftime("%d %b %Y, %I:%M %p") if record.created_at else "",
            "selected_language": lang_key,
            "loaded_from_vault_cache": True,
            "stored_files": [f for f in (record.filenames or []) if "_page_" in f.get("file_id", "")],
            "demographics": decrypt_json_with_key(record.demographics_enc, vault_key) or {},
            "ai_explanation": translations[lang_key],
            "attached_prescriptions": decrypt_json_with_key(record.attached_prescriptions_enc, vault_key) or [],
        }
    finally:
        db.close()


def create_or_update_family_member(household_id: str, payload_dict: dict) -> dict:
    db = SessionLocal()
    try:
        clean_id = payload_dict["member_id"].lower().strip()
        pk = f"{household_id}:{clean_id}"
        member = db.query(FamilyMember).filter(FamilyMember.id == pk).first()
        if member:
            member.display_name = payload_dict["display_name"]
            member.relationship = payload_dict.get("relationship", member.relationship)
            member.age = payload_dict.get("age") or member.age
            member.gender = payload_dict.get("gender") or member.gender
            member.blood_group = payload_dict.get("blood_group") or member.blood_group
            member.known_conditions = payload_dict.get("known_conditions") or member.known_conditions
        else:
            member = FamilyMember(
                id=pk,
                household_id=household_id,
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


def list_all_family_members(household_id: str, allowed_member_id: str = "*") -> list:
    db = SessionLocal()
    try:
        ensure_member_exists(db, household_id, "self")
        query = db.query(FamilyMember).filter(FamilyMember.household_id == household_id)
        if allowed_member_id != "*":
            query = query.filter(FamilyMember.member_id == allowed_member_id)

        members = query.order_by(FamilyMember.created_at.asc()).all()
        result = []
        for m in members:
            count = (
                db.query(func.count(MedicalReport.report_id))
                .filter(
                    MedicalReport.household_id == household_id,
                    MedicalReport.member_id == m.member_id,
                )
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


def get_member_timeline(household_id: str, member_id: str, vault_key: bytes) -> dict:
    clean_id = member_id.lower().strip()
    pk = f"{household_id}:{clean_id}"
    db = SessionLocal()
    try:
        member = db.query(FamilyMember).filter(FamilyMember.id == pk).first()
        reports = (
            db.query(MedicalReport)
            .filter(
                MedicalReport.household_id == household_id,
                MedicalReport.member_id == clean_id,
            )
            .order_by(MedicalReport.created_at.desc())
            .all()
        )
        timeline = []
        for r in reports:
            ai_data = decrypt_json_with_key(r.ai_analysis_enc, vault_key) or {}
            attached_rx = decrypt_json_with_key(r.attached_prescriptions_enc, vault_key) or []
            page_files = [f for f in (r.filenames or []) if "_rx" not in f.get("file_id", "")]

            timeline.append({
                "report_id": r.report_id,
                "date_uploaded": r.created_at.strftime("%d %b %Y, %I:%M %p") if r.created_at else "",
                "category": ai_data.get("document_category", "lab_report"),
                "report_type": ai_data.get("report_type", "Medical Document"),
                "overall_status": ai_data.get("overall_status", ""),
                "language": r.language,
                "stored_files": page_files,
                "attached_prescriptions_count": len(attached_rx),
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


def get_single_vault_record(
    household_id: str, report_id: str, vault_key: bytes, language: str = None
) -> dict | None:
    if language:
        return translate_existing_vault_record(household_id, report_id, language, vault_key)

    db = SessionLocal()
    try:
        r = (
            db.query(MedicalReport)
            .filter(MedicalReport.report_id == report_id, MedicalReport.household_id == household_id)
            .first()
        )
        if not r:
            return None

        ai_data = decrypt_json_with_key(r.ai_analysis_enc, vault_key) or {}
        attached_rx = decrypt_json_with_key(r.attached_prescriptions_enc, vault_key) or []
        page_files = [f for f in (r.filenames or []) if "_rx" not in f.get("file_id", "")]

        return {
            "report_id": r.report_id,
            "member_id": r.member_id,
            "date_uploaded": r.created_at.strftime("%d %b %Y, %I:%M %p") if r.created_at else "",
            "selected_language": r.language,
            "stored_files": page_files,
            "demographics": decrypt_json_with_key(r.demographics_enc, vault_key) or {},
            "ai_explanation": ai_data,
            "attached_prescriptions": attached_rx,
        }
    finally:
        db.close()


def delete_vault_record(household_id: str, report_id: str) -> bool:
    """Deletes the DB row AND deletes all encrypted image/PDF files from storage!"""
    db = SessionLocal()
    try:
        r = (
            db.query(MedicalReport)
            .filter(MedicalReport.report_id == report_id, MedicalReport.household_id == household_id)
            .first()
        )
        if not r:
            return False

        for f_info in (r.filenames or []):
            if isinstance(f_info, dict) and f_info.get("file_id"):
                fpath = os.path.join(VAULT_FILES_DIR, os.path.basename(f_info["file_id"]))
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass

        db.delete(r)
        db.commit()
        return True
    finally:
        db.close()


def search_member_history_vectors(
    household_id: str, member_id: str, query: str, vault_key: bytes, top_k: int = 3
) -> list:
    query_vec = generate_local_embedding(query)
    clean_member = member_id.lower().strip()
    db = SessionLocal()
    try:
        rows = (
            db.query(MedicalReport)
            .filter(
                MedicalReport.household_id == household_id,
                MedicalReport.member_id == clean_member,
            )
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
            clean_obj = decrypt_json_with_key(r.clean_text_enc, vault_key) or {}
            ai_obj = decrypt_json_with_key(r.ai_analysis_enc, vault_key) or {}
            scored.append({
                "report_id": r.report_id,
                "date": r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
                "sim": sim,
                "clean_text": clean_obj.get("text", ""),
                "ai_summary": ai_obj.get("overall_status", ""),
            })
        scored.sort(key=lambda x: x["sim"], reverse=True)
        return scored[:top_k]
    finally:
        db.close()


# =========================================================
# 5. FAMILY VAULT ROLE MANAGEMENT (OWNER ASSIGNS ROLES)
# =========================================================

def create_family_role_code(household_id: str, vault_key: bytes, payload: dict) -> dict:
    """Allows the Vault Owner to create an 'editor' or 'viewer' share code for family members."""
    share_code = payload["share_code"].strip()
    code_hash = hash_invite_code(share_code)
    wrapped_key = wrap_vault_key_for_role_code(vault_key, share_code)

    db = SessionLocal()
    try:
        existing = db.query(VaultAccessRole).filter(VaultAccessRole.code_hash == code_hash).first()
        if existing:
            raise ValueError("This share code is already in use. Please pick a unique code.")

        role_entry = VaultAccessRole(
            code_hash=code_hash,
            household_id=household_id,
            label=payload["label"].strip(),
            role=payload["role"],
            allowed_member_id=payload.get("allowed_member_id", "*").lower().strip(),
            wrapped_vault_key=wrapped_key,
        )
        db.add(role_entry)
        db.commit()
        return {
            "label": role_entry.label,
            "role": role_entry.role,
            "allowed_member_id": role_entry.allowed_member_id,
        }
    finally:
        db.close()


def list_household_roles(household_id: str) -> list:
    db = SessionLocal()
    try:
        rows = (
            db.query(VaultAccessRole)
            .filter(VaultAccessRole.household_id == household_id)
            .order_by(VaultAccessRole.created_at.asc())
            .all()
        )
        return [
            {
                "role_id": r.code_hash[:12],
                "label": r.label,
                "role": r.role,
                "allowed_member_id": r.allowed_member_id,
                "created_at": r.created_at.strftime("%d %b %Y") if r.created_at else "",
            }
            for r in rows
        ]
    finally:
        db.close()


def revoke_household_role(household_id: str, role_id_prefix: str) -> bool:
    db = SessionLocal()
    try:
        rows = db.query(VaultAccessRole).filter(VaultAccessRole.household_id == household_id).all()
        for r in rows:
            if r.code_hash.startswith(role_id_prefix) and r.role != "owner":
                db.delete(r)
                db.commit()
                return True
        return False
    finally:
        db.close()