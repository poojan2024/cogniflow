"""Orchestrates the document intelligence pipeline for one stored document:

    stored file -> text extraction / OCR -> text cleaning -> information extraction -> save result

The result (text + items + status) is stored, so a document is never processed twice by accident.
Activity matching and the confirm/reject suggestion come after this step (added in the next phase).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document, ExtractedInformation
from app.services import storage
from app.services.history import log_event
from app.services.info_extraction import extract_information
from app.services.suggestions import safe_generate_suggestions
from app.services.text_cleaning import clean_text
from app.services.text_extraction import extract_text

logger = logging.getLogger("cogniflow")

KIND_BY_MIME = {"application/pdf": "pdf", "image/png": "image", "image/jpeg": "image", "text/plain": "txt"}


def replace_rule_items(db: Session, document: Document, text: str) -> list:
    """Delete the automatically extracted items of a document and extract them again from `text`."""
    db.execute(delete(ExtractedInformation).where(
        ExtractedInformation.document_id == document.id, ExtractedInformation.source == "RULE"))
    items = extract_information(text)
    for item in items:
        db.add(ExtractedInformation(
            document_id=document.id, info_type=item.info_type, value=item.value, context=item.context, source="RULE"))
    return items


def process_document(db: Session, document: Document) -> None:
    """Run the pipeline and record the outcome. Never raises for ordinary extraction problems."""
    settings = get_settings()
    document.processing_status = "PROCESSING"
    document.error_message = None
    db.commit()

    path = storage.find(document.user_id, document.stored_filename)
    if path is None:
        result_status, message, text = "FAILED", "The stored file could not be found.", ""
        method, confidence = "NONE", None
    else:
        result = extract_text(
            path,
            KIND_BY_MIME.get(document.mime_type, ""),
            ocr_lang=settings.ocr_language,
            max_pdf_pages=settings.ocr_max_pdf_pages,
            min_confidence=settings.ocr_min_confidence,
            tesseract_cmd=settings.tesseract_cmd,
        )
        text = clean_text(result.text)
        result_status, message = result.status, result.message
        method, confidence = result.method, result.ocr_confidence
        if result_status != "FAILED" and not text:
            result_status, message = "FAILED", "No readable text could be found in this document."

    document.extraction_method = method
    document.ocr_confidence = confidence
    document.extracted_text = text or None
    document.error_message = message
    document.processing_status = result_status
    document.processed_at = datetime.now(timezone.utc)

    items = replace_rule_items(db, document, text) if text and result_status != "FAILED" else []
    count = len(items)

    if document.activity_id is not None:
        action = "DOCUMENT_PROCESSING_FAILED" if result_status == "FAILED" else "DOCUMENT_PROCESSED"
        detail = f"'{document.original_filename}': {result_status.lower()} via {method}, {count} items found"
        log_event(db, document.activity_id, action, "document", document.id, detail)
    db.commit()

    # Suggest which activity the document belongs to. This is only a suggestion (the user confirms or rejects),
    # and a matching problem can never undo the processing result that was just saved.
    if document.activity_id is None and text and result_status != "FAILED":
        safe_generate_suggestions(db, document, items)


def run_processing(document_id: int, session_factory: Callable[[], Session]) -> None:
    """Background-task entry point. Opens its own DB session because the request's session is already closed."""
    db = session_factory()
    try:
        document = db.get(Document, document_id)
        if document is not None:
            process_document(db, document)
    except Exception:
        logger.exception("Document processing crashed for document %s", document_id)
        try:
            db.rollback()
            document = db.get(Document, document_id)
            if document is not None:
                document.processing_status = "FAILED"
                document.error_message = "Processing failed unexpectedly. You can try Reprocess."
                db.commit()
        except Exception:
            logger.exception("Could not record the processing failure")
    finally:
        db.close()
