from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentStatus = Literal["UPLOADED", "PROCESSING", "PROCESSED", "NEEDS_REVIEW", "FAILED"]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: Optional[int]  # None until the document is assigned to an activity
    original_filename: str
    mime_type: str
    file_size: int
    processing_status: DocumentStatus
    extraction_method: str  # TEXT | OCR | NONE
    ocr_confidence: Optional[float]  # real OCR engine confidence 0..100, None if OCR was not used
    error_message: Optional[str]  # user-safe explanation for FAILED / NEEDS_REVIEW
    created_at: datetime
    processed_at: Optional[datetime]


class ExtractedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    info_type: str
    value: str
    context: Optional[str]
    source: str


class DocumentDetail(DocumentOut):
    extracted_text: Optional[str]
    items: List[ExtractedItemOut]


class DocumentPage(BaseModel):
    items: List[DocumentOut]
    total: int
    page: int
    page_size: int


class TextCorrection(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Text must not be empty.")
        return v


class DocumentAssign(BaseModel):
    activity_id: Optional[int] = None  # null removes the document from its activity
