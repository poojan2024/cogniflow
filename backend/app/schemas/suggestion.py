from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class SuggestionOut(BaseModel):
    id: int
    document_id: int
    activity_id: int
    activity_title: str
    activity_type: str
    score: float  # 0..100, a similarity score, NOT a probability
    confidence: Literal["strong", "moderate", "weak"]
    explanation: str  # plain-language reasons for the suggestion
    status: Literal["PENDING", "CONFIRMED", "REJECTED"]
    created_at: datetime
    resolved_at: Optional[datetime]
