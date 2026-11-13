"""Document management and the document-processing pipeline endpoints.

Upload returns immediately (status UPLOADED); OCR / extraction runs in a background task so the UI is never
blocked. Clients poll GET /documents/{id} until processing_status is PROCESSED, NEEDS_REVIEW or FAILED.
"""
import hashlib
from typing import Callable, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db, get_session_factory
from app.core.deps import get_current_user, get_owned_document
from app.models import Activity, Document, ExtractedInformation, User
from app.schemas.document import (
    DocumentAssign,
    DocumentDetail,
    DocumentOut,
    DocumentPage,
    DocumentStatus,
    ExtractedItemOut,
    TextCorrection,
)
from app.services import storage
from app.services.document_pipeline import replace_rule_items, run_processing
from app.services.file_validation import UploadRejected, validate_upload
from app.services.history import log_event
from app.services.suggestions import safe_generate_suggestions
from app.services.text_cleaning import clean_text

router = APIRouter(prefix="/documents", tags=["documents"])

_ITEM_ORDER = ["DOCUMENT_TYPE", "DEADLINE", "DATE", "AMOUNT", "PERSON", "LOCATION", "KEYWORD", "OTHER"]


def _owned_activity_or_404(db: Session, activity_id: int, user: User) -> Activity:
    activity = db.scalar(select(Activity).where(Activity.id == activity_id, Activity.user_id == user.id))
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found.")
    return activity


def _detail(document: Document) -> DocumentDetail:
    items = sorted(
        document.extracted_items,
        key=lambda i: (_ITEM_ORDER.index(i.info_type) if i.info_type in _ITEM_ORDER else 99, i.id),
    )
    base = DocumentOut.model_validate(document).model_dump()
    return DocumentDetail(
        **base,
        extracted_text=document.extracted_text,
        items=[ExtractedItemOut.model_validate(i) for i in items],
    )


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    activity_id: Optional[str] = Form(default=None, description="Optional: put the document straight into this activity"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    session_factory: Callable = Depends(get_session_factory),
):
    settings = get_settings()

    target_activity = None
    if activity_id is not None and activity_id.strip():
        if not activity_id.strip().isdigit():
            raise HTTPException(status_code=422, detail="activity_id must be a number.")
        target_activity = _owned_activity_or_404(db, int(activity_id), current_user)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)  # never read more than the limit (+1 byte to detect an oversize file)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"The file is too large. The maximum size is {settings.max_upload_mb} MB.")

    try:
        validated = validate_upload(file.filename, data)
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    digest = hashlib.sha256(data).hexdigest()
    duplicate = db.scalar(select(Document).where(Document.user_id == current_user.id, Document.sha256 == digest))
    if duplicate is not None:  # the same file is never stored or processed twice
        raise HTTPException(status_code=409, detail=f"This file was already uploaded (document #{duplicate.id}).")

    stored_name = storage.new_stored_filename(validated.extension)
    storage.save(current_user.id, stored_name, data)
    document = Document(
        user_id=current_user.id,
        activity_id=target_activity.id if target_activity else None,
        original_filename=validated.display_name,
        stored_filename=stored_name,
        mime_type=validated.mime_type,
        file_size=len(data),
        sha256=digest,
    )
    db.add(document)
    try:
        db.flush()
        if target_activity:
            log_event(db, target_activity.id, "DOCUMENT_UPLOADED", "document", document.id,
                      f"Uploaded '{document.original_filename}'")
        db.commit()
    except IntegrityError:
        db.rollback()
        storage.delete(current_user.id, stored_name)
        raise HTTPException(status_code=409, detail="This file was already uploaded.")
    db.refresh(document)

    background_tasks.add_task(run_processing, document.id, session_factory)
    return document


@router.get("", response_model=DocumentPage)
def list_documents(
    activity_id: Optional[int] = None,
    unassigned: bool = Query(default=False, description="Only documents not yet in any activity"),
    status_filter: Optional[DocumentStatus] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Document).where(Document.user_id == current_user.id)
    if activity_id is not None:
        _owned_activity_or_404(db, activity_id, current_user)
        stmt = stmt.where(Document.activity_id == activity_id)
    if unassigned:
        stmt = stmt.where(Document.activity_id.is_(None))
    if status_filter:
        stmt = stmt.where(Document.processing_status == status_filter)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Document.created_at.desc(), Document.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return DocumentPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document: Document = Depends(get_owned_document)):
    return _detail(document)


@router.get("/{document_id}/download")
def download_document(document: Document = Depends(get_owned_document)):
    path = storage.find(document.user_id, document.stored_filename)
    if path is None:
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    return FileResponse(
        path,
        media_type=document.mime_type,
        filename=document.original_filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.patch("/{document_id}/text", response_model=DocumentDetail)
def correct_text(
    payload: TextCorrection,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
):
    """Manual correction of the extracted/OCR text (or typing it in when OCR failed). Items are re-extracted."""
    text = clean_text(payload.text)
    if not text:
        raise HTTPException(status_code=422, detail="Text must not be empty.")
    document.extracted_text = text
    document.processing_status = "PROCESSED"
    document.error_message = None
    items = replace_rule_items(db, document, text)
    if document.activity_id is not None:
        log_event(db, document.activity_id, "DOCUMENT_TEXT_CORRECTED", "document", document.id,
                  f"Text of '{document.original_filename}' corrected manually")
    db.commit()
    safe_generate_suggestions(db, document, items)  # the corrected text may point to a different activity
    db.refresh(document)
    return _detail(document)


@router.post("/{document_id}/reprocess", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reprocess_document(
    background_tasks: BackgroundTasks,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
    session_factory: Callable = Depends(get_session_factory),
):
    """Run the pipeline again, only for FAILED / NEEDS_REVIEW documents (for example after installing Tesseract)."""
    if document.processing_status not in ("FAILED", "NEEDS_REVIEW"):
        raise HTTPException(status_code=409, detail="This document does not need to be processed again.")
    document.processing_status = "UPLOADED"
    document.error_message = None
    db.commit()
    db.refresh(document)
    background_tasks.add_task(run_processing, document.id, session_factory)
    return document


@router.patch("/{document_id}", response_model=DocumentOut)
def assign_document(
    payload: DocumentAssign,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Put the document into an activity (the user's own choice), or remove it from its activity with null."""
    if payload.activity_id is None:
        if document.activity_id is not None:
            log_event(db, document.activity_id, "DOCUMENT_UNASSIGNED", "document", document.id,
                      f"Removed '{document.original_filename}' from this activity")
        document.activity_id = None
    else:
        activity = _owned_activity_or_404(db, payload.activity_id, current_user)
        document.activity_id = activity.id
        log_event(db, activity.id, "DOCUMENT_ASSIGNED", "document", document.id,
                  f"Added '{document.original_filename}' to this activity")
    db.commit()
    db.refresh(document)
    return document


@router.delete("/{document_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_extracted_item(
    item_id: int,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
):
    """Remove one wrongly extracted item."""
    item = db.scalar(select(ExtractedInformation).where(
        ExtractedInformation.id == item_id, ExtractedInformation.document_id == document.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Extracted item not found.")
    db.delete(item)
    db.commit()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    user_id, stored_name = document.user_id, document.stored_filename
    if document.activity_id is not None:
        log_event(db, document.activity_id, "DOCUMENT_DELETED", "document", document.id,
                  f"Deleted '{document.original_filename}'")
    db.delete(document)
    db.commit()
    storage.delete(user_id, stored_name)
