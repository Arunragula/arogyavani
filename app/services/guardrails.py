# app/services/guardrails.py
import re
from fastapi import HTTPException

# 1. Blocks ONLY clear non-medical chat topics (coding, math, sports, politics, jailbreaks)
NON_MEDICAL_CHAT_REGEX = re.compile(
    r"\b("
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"write\s+(?:a\s+)?(?:python|java|javascript|c\+\+|html|sql|code|program|script)|"
    r"leetcode|bubble\s+sort|binary\s+search|"
    r"cricket\s+score|ipl\s+match|football\s+match|box\s+office|movie\s+review|"
    r"stock\s+market|share\s+price|crypto|bitcoin"
    r")\b",
    re.IGNORECASE,
)


def enforce_question_guardrail_precheck(question: str):
    clean_q = question.strip()
    if len(clean_q) < 2:
        raise HTTPException(
            status_code=400,
            detail="Please enter a health or medical question.",
        )
    if NON_MEDICAL_CHAT_REGEX.search(clean_q):
        raise HTTPException(
            status_code=400,
            detail="Please ask questions related to health, symptoms, medicines, or your medical reports only.",
        )


# 2. Substring match (no \b boundary) so OCR-glued words like "Haemoglobing/dL" or "Bloodpressure" always pass!
MEDICAL_ROOT_TERMS = [
    "hemoglobin", "haemoglobin", "glucose", "sugar", "r.b.s", "rbs", "hba1c", "cholesterol",
    "creatinine", "urea", "bilirubin", "sgot", "sgpt", "albumin", "protein", "thyroid", "tsh",
    "vitamin", "calcium", "iron", "platelet", "wbc", "rbc", "esr", "urine", "stool", "serology",
    "biochemistry", "hematology", "pathology", "hiv", "hbsag", "hcv", "vdrl", "tpha", "malaria",
    "mg/dl", "g/dl", "mmol", "iu/l", "mmhg", "normal", "negative", "positive", "absent", "nad",
    "x-ray", "xray", "mri", "ultrasound", "ecg", "blood", "pulse", "vision", "eye", "ear",
    "prescription", "tablet", "capsule", "syrup", "dosage", "composition", "paracetamol",
    "antibiotic", "1-0-1", "1-1-1", "hospital", "medical", "clinic", "diagnostic", "patient",
    "doctor", "candidate", "wafid", "examination", "investigation", "vaccine", "fit"
]

NON_MEDICAL_POISON_TERMS = [
    "curriculum vitae", "work experience", "technical skills", "bachelor of technology",
    "semester examination", "cgpa", "bank statement", "ifsc code", "closing balance",
    "electricity bill", "boarding pass", "pnr no", "import fastapi", "console.log("
]


def enforce_extracted_text_guardrail(raw_text: str, doc_category: str = "lab_report"):
    """Checks OCR text locally without failing on OCR-merged words."""
    lower_text = raw_text.lower().strip()
    if len(lower_text) < 10:
        raise HTTPException(
            status_code=400,
            detail="Could not read enough text. Please upload a clearer medical document image.",
        )

    med_hits = sum(1 for term in MEDICAL_ROOT_TERMS if term in lower_text)
    poison_hits = sum(1 for term in NON_MEDICAL_POISON_TERMS if term in lower_text)

    if poison_hits >= 2 and med_hits < 2:
        raise HTTPException(
            status_code=400,
            detail="This file appears to be a non-medical document (such as a resume, bill, or statement). Please upload a medical report or prescription.",
        )

    if med_hits == 0:
        raise HTTPException(
            status_code=400,
            detail="No medical terms, test values, or medicines were detected in this file. Please upload a valid health document.",
        )


def enforce_ai_output_guardrail(ai_output: dict, mode: str = "report"):
    """
    Only rejects if the AI explicitly set is_medical_related to False
    AND no medical tests/medicines were extracted.
    """
    # If real tests or medicines exist in the JSON, it IS valid—never reject it!
    has_tests = bool(
        ai_output.get("attention_needed")
        or ai_output.get("jargon_and_normal_tests_decoded")
        or ai_output.get("medicines_decoded")
    )
    if has_tests:
        return

    # Only reject if explicitly marked False by the AI
    if ai_output.get("is_medical_related") is False:
        reason = ai_output.get("rejection_reason") or (
            "Please ask questions or upload documents related to health, symptoms, or medical reports only."
        )
        raise HTTPException(status_code=400, detail=reason)