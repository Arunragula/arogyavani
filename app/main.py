# app/main.py
import os
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.schemas.models import SpeakRequest, DirectQuestionRequest, FamilyMemberCreate
from app.services.extractor import extract_multiple_documents
from app.services.scrubber import scrub_personal_details
from app.services.analyzer import analyze_medical_report, answer_direct_health_question
from app.services.prescription import analyze_prescription_or_strip
from app.services.db_vector import (
    compute_document_hash,
    get_cached_report_by_hash,
    translate_existing_vault_record,
    save_report_to_db,
    search_member_history_vectors,
    save_qa_log,
    export_training_dataset,
    create_or_update_family_member,
    list_all_family_members,
    get_member_timeline,
    get_single_vault_record,
    delete_vault_record,
)
from app.services.guardrails import (
    enforce_question_guardrail_precheck,
    enforce_extracted_text_guardrail,
    enforce_ai_output_guardrail,
)
from app.services.voice_tts import generate_voice_mp3, AUDIO_DIR
from app.services.db_vector import VAULT_FILES_DIR

app = FastAPI(title="CuraVault AI Platform", version="1.0.0")



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("frontend/assets/images", exist_ok=True)
app.mount("/assets", StaticFiles(directory="frontend/assets"), name="assets")
app.mount("/static", StaticFiles(directory="frontend"), name="static")

app.mount("/vault-files", StaticFiles(directory=VAULT_FILES_DIR), name="vault_files")

# Multi-Page HTML Routes
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
# 1. DETERMINISTIC REPORT & RX ANALYZERS
# ==========================================

async def _process_medical_upload(
    files: List[UploadFile], member_id: str, language: str, doc_category: str
):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed.")

    files_data = [(f.filename, await f.read()) for f in files]
    if not files_data:
        raise HTTPException(status_code=400, detail="Uploaded files are empty.")

    # Check SHA-256 Document Hash in DB first
    doc_hash = compute_document_hash(member_id, doc_category, files_data)
    cached = get_cached_report_by_hash(doc_hash, language)
    if cached:
        return cached

    # Extract text from image/PDF
    extraction_result = extract_multiple_documents(files_data)
    raw_text = extraction_result["combined_raw_text"]

    # 🛡️ GUARDRAIL CHECKPOINT 1 (Local OCR Text Gate — Blocks Resumes, Bills, Code, Non-Medical Images in 0ms!)
    enforce_extracted_text_guardrail(raw_text, doc_category)

    # Scrub PII locally
    scrub_result = scrub_personal_details(raw_text)

    # Analyze with Gemini Fallback Chain
    if doc_category == "prescription":
        ai_analysis = analyze_prescription_or_strip(scrub_result["clean_text"], language)
    else:
        ai_analysis = analyze_medical_report(scrub_result["clean_text"], language)

    # 🛡️ GUARDRAIL CHECKPOINT 2 & 3 (AI Confidence Score >= 75 + Non-Empty Medical Items Check!)
    enforce_ai_output_guardrail(ai_analysis, mode=doc_category)

    # Save to Family Vault DB ONLY if all 3 Guardrail Checkpoints pass!
    # Save to Family Vault DB + Save Original Images/PDFs to vault_uploads/
    db_info = save_report_to_db(
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
        "loaded_from_vault_cache": False,
        "stored_files": db_info["stored_files"],
        "demographics": scrub_result["demographics_preserved"],
        "ai_explanation": ai_analysis,
    }
@app.post("/api/v1/analyze-report", tags=["1. Medical Analyzers"])
async def analyze_multi_page_report(
    files: List[UploadFile] = File(...),
    member_id: str = Form("self"),
    language: str = Form("English"),
):
    return await _process_medical_upload(files, member_id, language, "lab_report")


@app.post("/api/v1/analyze-prescription", tags=["1. Medical Analyzers"])
async def decode_prescription_or_medicine_strip(
    files: List[UploadFile] = File(...),
    member_id: str = Form("self"),
    language: str = Form("English"),
):
    return await _process_medical_upload(files, member_id, language, "prescription")


# ==========================================
# 2. FAMILY VAULT & INSTANT TRANSLATION
# ==========================================

@app.post("/api/v1/vault/members", tags=["2. Family Health Vault"])
def add_or_update_family_member(payload: FamilyMemberCreate):
    return create_or_update_family_member(payload.model_dump())


@app.get("/api/v1/vault/members", tags=["2. Family Health Vault"])
def get_all_family_members():
    return {"family_members": list_all_family_members()}


@app.get("/api/v1/vault/members/{member_id}/timeline", tags=["2. Family Health Vault"])
def get_family_member_health_timeline(member_id: str):
    return get_member_timeline(member_id)


@app.get("/api/v1/vault/records/{report_id}", tags=["2. Family Health Vault"])
def open_stored_vault_record(report_id: str, language: Optional[str] = Query(None)):
    record = get_single_vault_record(report_id, language)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    return record


@app.post("/api/v1/vault/records/{report_id}/translate", tags=["2. Family Health Vault"])
def translate_open_record(report_id: str, language: str = Query("English")):
    """Translates an already-stored report into a new language while keeping all medical numbers locked."""
    record = translate_existing_vault_record(report_id, language)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    return record


@app.delete("/api/v1/vault/records/{report_id}", tags=["2. Family Health Vault"])
def remove_vault_record(report_id: str):
    if not delete_vault_record(report_id):
        raise HTTPException(status_code=404, detail="Record not found.")
    return {"deleted": True, "report_id": report_id}


# ==========================================
# 3. DIRECT Q&A CHAT & ON-DEMAND VOICE
# ==========================================

@app.post("/api/v1/ask-question", tags=["3. Q&A & Voice"])
async def ask_direct_health_or_history_question(payload: DirectQuestionRequest):
    # 🛡️ GUARDRAIL CHECKPOINT 1 (0ms Local Regex & Jailbreak Blocker)
    enforce_question_guardrail_precheck(payload.question)

    past_reports = (
        search_member_history_vectors(payload.member_id, payload.question, top_k=3)
        if payload.use_past_history
        else []
    )
    ai_response = answer_direct_health_question(payload.question, payload.language, past_reports)

    # 🛡️ GUARDRAIL CHECKPOINT 2 (AI Confidence Score >= 75 & Strict Domain Check)
    enforce_ai_output_guardrail(ai_response, mode="chat")

    save_qa_log(payload.member_id, payload.language, payload.question, ai_response)
    return {"member_id": payload.member_id, "response": ai_response}


@app.post("/api/v1/speak", tags=["3. Q&A & Voice"])
async def generate_voice_on_demand(payload: SpeakRequest):
    tts_result = await generate_voice_mp3(payload.text, payload.language)
    return {
        "audio_filename": tts_result["audio_filename"],
        "play_url": f"/api/v1/audio/{tts_result['audio_filename']}",
    }


@app.get("/api/v1/audio/{filename}", tags=["3. Q&A & Voice"])
async def play_generated_audio(filename: str):
    filepath = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Audio not found.")
    return FileResponse(filepath, media_type="audio/mpeg", filename=filename)


@app.get("/api/v1/training-dataset/export", tags=["3. Q&A & Voice"])
def get_collected_training_dataset():
    data = export_training_dataset()
    return {"total_training_records": len(data), "dataset": data}


