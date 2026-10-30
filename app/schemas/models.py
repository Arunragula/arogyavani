# app/schemas/models.py
from pydantic import BaseModel, Field
from typing import Optional


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
    share_code: str = Field(
        ...,
        min_length=6,
        max_length=64,
        description="Secret code to give your family member (e.g., MOM-VIEW-2026)",
    )
    label: str = Field(..., min_length=1, max_length=80, description="e.g., Mom's Phone (View Only)")
    role: str = Field("viewer", pattern="^(editor|viewer)$", description="'editor' or 'viewer'")
    allowed_member_id: str = Field(
        "*",
        max_length=40,
        description="'*' for all family profiles, or a specific profile like 'mom'",
    )