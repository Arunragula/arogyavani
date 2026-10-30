# app/schemas/models.py
from pydantic import BaseModel, Field
from typing import Optional, List


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2500)
    language: str = Field("English", max_length=30)


class DirectQuestionRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000)
    member_id: str = Field("self", min_length=1, max_length=40)
    language: str = Field("English", max_length=30)
    use_past_history: bool = Field(True)


class FamilyMemberCreate(BaseModel):
    member_id: str = Field(..., min_length=1, max_length=40)
    display_name: str = Field(..., min_length=1, max_length=80)
    relationship: str = Field("Self", max_length=40)
    age: Optional[str] = Field(None, max_length=30)
    gender: Optional[str] = Field(None, max_length=20)
    blood_group: Optional[str] = Field(None, max_length=15)
    known_conditions: Optional[str] = Field(None, max_length=500)


class RoleCodeCreate(BaseModel):
    """P0 #3 Fix: Owner only chooses label, role, and member scope. Server generates the cryptographic code!"""
    label: str = Field(..., min_length=1, max_length=80, description="e.g., Mom's Phone (View Only)")
    role: str = Field("viewer", pattern="^(editor|viewer)$")
    allowed_member_id: str = Field("*", max_length=40)


# LLM Output Validation Schemas
class AttentionItemSchema(BaseModel):
    item: str = ""
    your_value: str = ""
    healthy_normal_range: str = "Standard"
    severity: str = "info"
    simple_explanation: str = ""


class NormalTestItemSchema(BaseModel):
    term_on_report: str = ""
    your_value: str = ""
    healthy_normal_range: str = "Normal"
    meaning_in_simple_words: str = ""


class ValidatedReportOutput(BaseModel):
    is_medical_related: bool = True
    rejection_reason: str = ""
    document_category: str = "lab_report"
    report_type: str = "Medical Report"
    overall_status: str = ""
    attention_needed: List[AttentionItemSchema] = []
    jargon_and_normal_tests_decoded: List[NormalTestItemSchema] = []
    questions_for_doctor: List[str] = []
    voice_summary_script: str = ""
    disclaimer: str = ""