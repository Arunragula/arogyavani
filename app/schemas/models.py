# app/schemas/models.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class SpeakRequest(BaseModel):
    text: str = Field(..., description="Text of the summary or individual card to convert to speech")
    language: str = Field("English", description="Language for voice accent (e.g. English, Hindi, Telugu, Arabic)")


class DirectQuestionRequest(BaseModel):
    question: str = Field(..., description="User's symptom question or question about past reports")
    member_id: str = Field("self", description="Family member profile ID (e.g., 'self', 'mom', 'dad')")
    language: str = Field("English", description="Language for the AI answer")
    use_past_history: bool = Field(True, description="Search Vector DB for this member's past reports")


class AttentionItem(BaseModel):
    item: str
    your_value: str
    healthy_normal_range: str
    severity: str
    simple_explanation: str


class DecodedTestItem(BaseModel):
    term_on_report: str
    your_value: str
    healthy_normal_range: str
    meaning_in_simple_words: str


class AIReportExplanation(BaseModel):
    report_type: str
    overall_status: str
    attention_needed: List[AttentionItem]
    jargon_and_normal_tests_decoded: List[DecodedTestItem]
    questions_for_doctor: List[str]
    voice_summary_script: str
    disclaimer: str
    meta: Optional[Dict[str, Any]] = None

class FamilyMemberCreate(BaseModel):
    member_id: str = Field(..., description="Unique ID like 'self', 'mom', 'dad', 'kid1'")
    display_name: str = Field(..., description="Nickname shown in UI, e.g., 'Amma (Mom)'")
    relationship: str = Field("Self", description="e.g., Self, Mother, Father, Spouse, Child")
    age: Optional[str] = Field(None, description="e.g., '52 Years'")
    gender: Optional[str] = Field(None, description="e.g., 'Female'")
    blood_group: Optional[str] = Field(None, description="e.g., 'O+'")
    known_conditions: Optional[str] = Field(None, description="e.g., 'BP, Diabetes, Vitamin D deficiency'")