from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.reminder import as_utc
from app.services.assistant_core import MAX_QUESTION_CHARS


class AskRequest(BaseModel):
    question: str
    mode: Literal["auto", "local"] = "auto"  # "local" = keyword search only, nothing is sent to Gemini

    @field_validator("question")
    @classmethod
    def check_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Please type a question.")
        if len(v) > MAX_QUESTION_CHARS:
            raise ValueError(f"The question is too long (maximum {MAX_QUESTION_CHARS} characters).")
        return v


class ReferenceOut(BaseModel):
    label: str  # e.g. "Task 5", "Doc 12"
    kind: str
    title: str


class AnswerOut(BaseModel):
    id: int
    question: str
    answer: str
    source: Literal["gemini", "keyword"]  # who produced the answer
    ai_status: Literal["ok", "unavailable", "failed", "not_used"]
    notice: Optional[str]  # why the keyword answer was used, or what keyword mode means
    has_information: bool  # False when the answer says the data does not contain the information
    references: List[ReferenceOut]  # stored items the answer is based on
    unverified_references: List[str]  # references in the answer that do not exist in the data (possible mistakes)
    context_truncated: bool  # True when some activity data did not fit into the size limit
    created_at: datetime

    _utc = field_validator("created_at")(as_utc)


class InteractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    answer: Optional[str]
    status: str  # SUCCESS | FAILED | UNAVAILABLE
    source: Literal["gemini", "keyword"]
    note: Optional[str]
    created_at: datetime

    _utc = field_validator("created_at")(as_utc)


class InteractionPage(BaseModel):
    items: List[InteractionOut]
    total: int
    page: int
    page_size: int


class ContextOut(BaseModel):
    """Exactly the activity data that would be sent to Gemini together with a question."""

    text: str
    char_count: int
    truncated: bool
    sources: List[ReferenceOut]


class AssistantStatusOut(BaseModel):
    provider: str
    ai_configured: bool
    model: str
    max_questions_per_hour: int
    note: str
