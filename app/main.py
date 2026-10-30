# app/main.py
import os
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.db.database import engine, Base, IS_POSTGRES
from app.schemas.models import (
    SpeakRequest,
    DirectQuestionRequest,
    FamilyMemberCreate,
    RoleCodeCreate,
)
from app.services.extractor import extract_multiple_documents
from app.services.scrubber import scrub_personal_details
from app.services.analyzer import analyze_medical_report, answer_direct_health_question
from app.services.prescription import analyze_prescription_or_strip
from app.services.guardrails import (
    enforce_question_guardrail_precheck,
    enforce_extracted_text_guardrail,
    enforce_ai_output_guardrail,
)
from app.services.auth_limiter import (
    limiter,
    verify_vault_access,
    enforce_member_scope,
    require_write_permission,
    require_owner_permission,
    check_and_increment_daily_quota,
)
from app.services.db_vector import (
    compute_document_hash,
    get_cached_report_by_hash,
    translate_existing_vault_record,
    save_report_to_db,
    verify_and_get_parent_report_context,
    attach_prescription_to_existing_report,
    read_decrypted_vault_file,
    search_member_history_vectors,
    create_or_update_family_member,
    list_all_family_members,
    get_member_timeline,
    get_single_vault_record,
    delete_vault_record,
    create_family_role_code,
    list_household_roles,
    revoke_household_role,
)
from app.services.voice_tts import stream_voice_mp3_bytes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arogyavani")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For local SQLite dev/tests, ensure tables exist; on Postgres, Alembic manages schema
    if not IS_POSTGRES:
        Base.metadata.create_all(bind=engine)
    logger.info("ArogyaVani / CuraVault AI startup complete.")
    yield


app = FastAPI(title="ArogyaVani / CuraVault AI", version="8.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

os.makedirs("frontend/assets/images", exist_ok=True)
app.mount("/assets", StaticFiles(directory="frontend/assets"), name="assets")
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/healthz", include_in_schema=False)
def render_health_check():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def home_page():
    return FileResponse("frontend/index.html")


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse("frontend/login.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return FileResponse("frontend/dashboard.html")


@app.get("/about", include_in_schema=False)
def about_page():
    return FileResponse("frontend/about.html")


@app.get("/contact", include_in_schema=False)
def contact_page():
    return FileResponse("frontend/contact.html")


# ==========================================
# 1. AUTH CHECK & FAMILY ROLE MANAGEMENT
# ==========================================

@app.get("/api/v1/auth/me", tags=["1. Access & Roles"])
@limiter.limit("20/minute")
def verify_current_code(request: Request, auth: dict = Depends(verify_vault_access)):
    return {
        "authenticated": True,
        "role": auth["role"],
        "label": auth["label"],
        "allowed_member_id": auth["allowed_member_id"],
    }


@app.get("/api/v1/vault/roles", tags=["1. Access & Roles"])
def get_vault_roles(auth: dict = Depends(verify_vault_access)):
    require_owner_permission(auth)
    return {"roles": list_household_roles(auth["household_id"])}


@app.post("/api/v1/vault/roles", tags=["1. Access & Roles"])
def assign_family_role(payload: RoleCodeCreate, auth: dict = Depends(verify_vault_access)):
    require_owner_permission(auth)
    created = create_family_role_code(auth["household_id"], auth["vault_key"], payload.model_dump())
    return {"created": True, "role_info": created}


@app.delete("/api/v1/vault/roles/{role_id}", tags=["1. Access & Roles"])
def remove_family_role(role_id: str, auth: dict = Depends(verify_vault_access)):
    require_owner_permission(auth)
    if not revoke_household_role(auth["household_id"], role_id):
        raise HTTPException(status_code=404, detail="Role not found or cannot revoke owner.")
    return {"revoked": True}


# ==========================================
# 2. REPORT, PRESCRIPTION & LINKED RX ROUTES
# ==========================================

def _handle_medical_upload_sync(
    files: List[UploadFile],
    member_id: str,
    language: str,
    save_to_vault: bool,
    doc_category: str,
    auth: dict,
):
    require_write_permission(auth, member_id)
    files_data = [(f.filename or "upload.jpg", f.file.read()) for f in files]

    doc_hash = compute_document_hash(auth["household_id"], member_id, doc_category, files_data)
    cached = get_cached_report_by_hash(
        auth["household_id"],
        doc_hash,
        language,
        auth["vault_key"],
        allowed_member_id=auth["allowed_member_id"],
        on_new_translation_callback=lambda: check_and_increment_daily_quota(auth["household_id"], "report"),
    )
    if cached:
        return cached

    # P1 #6 Fix: Count EVERY new analysis before running OCR/Gemini (even if save_to_vault=False!)
    check_and_increment_daily_quota(auth["household_id"], "report")

    extraction_result = extract_multiple_documents(files_data)
    raw_text = extraction_result["combined_raw_text"]
    enforce_extracted_text_guardrail(raw_text, doc_category)

    scrub_result = scrub_personal_details(raw_text)

    if doc_category == "prescription":
        ai_analysis = analyze_prescription_or_strip(scrub_result["clean_text"], language)
    else:
        ai_analysis = analyze_medical_report(scrub_result["clean_text"], language)

    enforce_ai_output_guardrail(ai_analysis, mode=doc_category)

    if save_to_vault:
        db_info = save_report_to_db(
            household_id=auth["household_id"],
            vault_key=auth["vault_key"],
            member_id=member_id,
            document_hash=doc_hash,
            files_data=files_data,
            language=language,
            demographics=scrub_result["demographics_preserved"],
            clean_text=scrub_result["clean_text"],
            ai_analysis=ai_analysis,
        )
        return {
            "report_id": db_info["report_id"],
            "member_id": member_id,
            "date_uploaded": db_info["date_uploaded"],
            "selected_language": language,
            "saved_to_vault": True,
            "stored_files": db_info["stored_files"],
            "demographics": scrub_result["demographics_preserved"],
            "ai_explanation": ai_analysis,
            "attached_prescriptions": [],
        }

    return {
        "report_id": None,
        "member_id": member_id,
        "selected_language": language,
        "saved_to_vault": False,
        "stored_files": [],
        "demographics": scrub_result["demographics_preserved"],
        "ai_explanation": ai_analysis,
        "attached_prescriptions": [],
    }


@app.post("/api/v1/analyze-report", tags=["2. Medical Analyzers"])
@limiter.limit("20/minute")
def analyze_multi_page_report(
    request: Request,
    files: List[UploadFile] = File(...),
    member_id: str = Form("self"),
    language: str = Form("English"),
    privacy_consent: bool = Form(True),
    save_to_vault: bool = Form(True),
    auth: dict = Depends(verify_vault_access),
):
    if not privacy_consent:
        raise HTTPException(status_code=400, detail="Please accept the Privacy & Educational Consent checkbox.")
    return _handle_medical_upload_sync(files, member_id, language, save_to_vault, "lab_report", auth)


@app.post("/api/v1/analyze-prescription", tags=["2. Medical Analyzers"])
@limiter.limit("20/minute")
def decode_prescription_or_medicine_strip(
    request: Request,
    files: List[UploadFile] = File(...),
    member_id: str = Form("self"),
    language: str = Form("English"),
    privacy_consent: bool = Form(True),
    save_to_vault: bool = Form(True),
    auth: dict = Depends(verify_vault_access),
):
    if not privacy_consent:
        raise HTTPException(status_code=400, detail="Please accept the Privacy & Educational Consent checkbox.")
    return _handle_medical_upload_sync(files, member_id, language, save_to_vault, "prescription", auth)


@app.post("/api/v1/vault/records/{report_id}/attach-prescription", tags=["2. Medical Analyzers"])
@limiter.limit("20/minute")
def attach_prescribed_medicines_to_report(
    request: Request,
    report_id: str,
    files: List[UploadFile] = File(...),
    language: str = Form("English"),
    auth: dict = Depends(verify_vault_access),
):
    require_write_permission(auth)

    # P1 #11 Fix: Verify parent report exists AND matches allowed_member_id BEFORE spending Gemini quota!
    report_context = verify_and_get_parent_report_context(
        auth["household_id"], report_id, auth["vault_key"], auth["allowed_member_id"]
    )

    check_and_increment_daily_quota(auth["household_id"], "report")

    files_data = [(f.filename or "rx.jpg", f.file.read()) for f in files]
    extraction_result = extract_multiple_documents(files_data)
    raw_text = extraction_result["combined_raw_text"]
    enforce_extracted_text_guardrail(raw_text, "prescription")

    scrub_result = scrub_personal_details(raw_text)
    combined_input = f"{report_context}\n\n{scrub_result['clean_text']}"
    rx_analysis = analyze_prescription_or_strip(combined_input, language)
    enforce_ai_output_guardrail(rx_analysis, mode="prescription")

    return attach_prescription_to_existing_report(
        household_id=auth["household_id"],
        vault_key=auth["vault_key"],
        report_id=report_id,
        files_data=files_data,
        rx_analysis=rx_analysis,
        allowed_member_id=auth["allowed_member_id"],
    )


# ==========================================
# 3. ENCRYPTED FAMILY VAULT ROUTES
# ==========================================

@app.post("/api/v1/vault/members", tags=["3. Family Health Vault"])
def add_or_update_family_member(payload: FamilyMemberCreate, auth: dict = Depends(verify_vault_access)):
    require_write_permission(auth, payload.member_id)
    return create_or_update_family_member(auth["household_id"], payload.model_dump())


@app.get("/api/v1/vault/members", tags=["3. Family Health Vault"])
def get_all_family_members(auth: dict = Depends(verify_vault_access)):
    return {
        "role": auth["role"],
        "family_members": list_all_family_members(auth["household_id"], auth["allowed_member_id"]),
    }


@app.get("/api/v1/vault/members/{member_id}/timeline", tags=["3. Family Health Vault"])
def get_family_member_health_timeline(member_id: str, auth: dict = Depends(verify_vault_access)):
    enforce_member_scope(auth, member_id)
    return get_member_timeline(auth["household_id"], member_id, auth["vault_key"])


@app.get("/api/v1/vault/records/{report_id}", tags=["3. Family Health Vault"])
def open_stored_vault_record(
    report_id: str,
    language: Optional[str] = Query(None),
    auth: dict = Depends(verify_vault_access),
):
    record = get_single_vault_record(
        auth["household_id"],
        report_id,
        auth["vault_key"],
        language=language,
        allowed_member_id=auth["allowed_member_id"],
        on_new_translation_callback=lambda: check_and_increment_daily_quota(auth["household_id"], "report"),
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    return record


@app.post("/api/v1/vault/records/{report_id}/translate", tags=["3. Family Health Vault"])
def translate_open_record(
    report_id: str,
    language: str = Query("English"),
    auth: dict = Depends(verify_vault_access),
):
    record = translate_existing_vault_record(
        auth["household_id"],
        report_id,
        language,
        auth["vault_key"],
        allowed_member_id=auth["allowed_member_id"],
        on_new_translation_callback=lambda: check_and_increment_daily_quota(auth["household_id"], "report"),
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    return record


@app.get("/api/v1/vault/records/{report_id}/files/{file_id}", tags=["3. Family Health Vault"])
def get_decrypted_vault_document(
    report_id: str,
    file_id: str,
    auth: dict = Depends(verify_vault_access),
):
    try:
        decrypted_bytes, mime_type = read_decrypted_vault_file(
            auth["household_id"], report_id, file_id, auth["vault_key"], auth["allowed_member_id"]
        )
        return Response(content=decrypted_bytes, media_type=mime_type)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))


@app.delete("/api/v1/vault/records/{report_id}", tags=["3. Family Health Vault"])
def remove_vault_record(report_id: str, auth: dict = Depends(verify_vault_access)):
    require_owner_permission(auth)
    if not delete_vault_record(auth["household_id"], report_id):
        raise HTTPException(status_code=404, detail="Record not found.")
    return {"deleted": True, "report_id": report_id}


# ==========================================
# 4. DIRECT Q&A CHAT & MEMORY-STREAMED VOICE
# ==========================================

@app.post("/api/v1/ask-question", tags=["4. Q&A & Voice"])
@limiter.limit("20/minute")
def ask_direct_health_or_history_question(
    request: Request,
    payload: DirectQuestionRequest,
    auth: dict = Depends(verify_vault_access),
):
    # P1 #7 Fix: Enforce member restriction on /ask-question too!
    enforce_member_scope(auth, payload.member_id)
    enforce_question_guardrail_precheck(payload.question)
    check_and_increment_daily_quota(auth["household_id"], "question")

    past_reports = (
        search_member_history_vectors(
            auth["household_id"], payload.member_id, payload.question, auth["vault_key"], top_k=3
        )
        if payload.use_past_history
        else []
    )
    ai_response = answer_direct_health_question(payload.question, payload.language, past_reports)
    enforce_ai_output_guardrail(ai_response, mode="chat")

    return {"member_id": payload.member_id, "response": ai_response}


@app.post("/api/v1/speak", tags=["4. Q&A & Voice"])
@limiter.limit("20/minute")
async def generate_voice_on_demand(
    request: Request,
    payload: SpeakRequest,
    auth: dict = Depends(verify_vault_access),
):
    check_and_increment_daily_quota(auth["household_id"], "speech")
    audio_bytes = await stream_voice_mp3_bytes(payload.text, payload.language)
    return Response(content=audio_bytes, media_type="audio/mpeg")