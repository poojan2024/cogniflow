"""Cogniflow database schema (SQLAlchemy 2.0, designed for PostgreSQL).

Ownership model (important for security and for the viva):
  * `users` own `activities` (activities.user_id) and `documents` (documents.user_id).
  * Everything else (tasks, notes, expenses, reminders, history, ...) belongs to ONE activity,
    so ownership is always checked by first loading the activity with
    `WHERE id = :id AND user_id = :current_user`.  This keeps the schema normalized
    (no duplicated user_id on every table).
  * A document has its own user_id because it can exist BEFORE it is assigned to an activity
    (the upload -> suggestion -> confirm/reject flow). activity_id is NULL until confirmed.

Only generic SQL types are used, so the same models also run on SQLite for automated tests.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# ---------------------------------------------------------------------------
# Allowed values (enforced in the database with CHECK constraints)
# ---------------------------------------------------------------------------
ACTIVITY_TYPES = ("PROJECT", "EXAM", "TRIP", "MEETING", "APPOINTMENT", "EVENT", "PERSONAL", "CUSTOM")
ACTIVITY_STATUSES = ("NOT_STARTED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED")
TASK_STATUSES = ("PENDING", "IN_PROGRESS", "COMPLETED")
PRIORITY_LABELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
DOCUMENT_STATUSES = ("UPLOADED", "PROCESSING", "PROCESSED", "NEEDS_REVIEW", "FAILED")
EXTRACTION_METHODS = ("TEXT", "OCR", "NONE")
INFO_TYPES = ("DOCUMENT_TYPE", "DATE", "DEADLINE", "AMOUNT", "PERSON", "LOCATION", "KEYWORD", "OTHER")
INFO_SOURCES = ("RULE", "AI", "USER")
SUGGESTION_STATUSES = ("PENDING", "CONFIRMED", "REJECTED")
AI_STATUSES = ("SUCCESS", "FAILED", "UNAVAILABLE")


def _in(column: str, values: tuple, name: str) -> CheckConstraint:
    """CHECK (column IN (...)) built from trusted constants above."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UpdatedMixin(CreatedMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class User(CreatedMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # bcrypt hash, never the password
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    activities: Mapped[List["Activity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    documents: Mapped[List["Document"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    notifications: Mapped[List["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# Activities (the central entity: one activity = one contextual workspace)
# ---------------------------------------------------------------------------
class Activity(UpdatedMixin, Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False, default="CUSTOM", server_default="CUSTOM")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3, server_default="3")  # 1 (low) .. 5 (high)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    deadline: Mapped[Optional[date]] = mapped_column(Date)

    user: Mapped["User"] = relationship(back_populates="activities")
    # No delete-orphan here: a document may legitimately have activity_id = NULL (pending suggestion).
    documents: Mapped[List["Document"]] = relationship(back_populates="activity", cascade="all", passive_deletes=True)
    tasks: Mapped[List["Task"]] = relationship(back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)
    notes: Mapped[List["Note"]] = relationship(back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)
    expenses: Mapped[List["Expense"]] = relationship(back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)
    reminders: Mapped[List["Reminder"]] = relationship(back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)
    history: Mapped[List["ActivityHistory"]] = relationship(back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)
    ai_interactions: Mapped[List["AIInteraction"]] = relationship(back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        _in("activity_type", ACTIVITY_TYPES, "ck_activities_type"),
        _in("status", ACTIVITY_STATUSES, "ck_activities_status"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_activities_priority"),
        CheckConstraint(
            "start_date IS NULL OR deadline IS NULL OR deadline >= start_date", name="ck_activities_dates"
        ),
        Index("ix_activities_user_status", "user_id", "status"),
        Index("ix_activities_user_deadline", "user_id", "deadline"),
    )


# ---------------------------------------------------------------------------
# Documents and document intelligence
# ---------------------------------------------------------------------------
class Document(CreatedMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"))  # NULL until confirmed
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)  # random name on disk
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)  # detects re-uploads of the same file
    processing_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UPLOADED", server_default="UPLOADED")
    extraction_method: Mapped[str] = mapped_column(String(10), nullable=False, default="NONE", server_default="NONE")
    extracted_text: Mapped[Optional[str]] = mapped_column(Text)  # stored so the file is never re-processed
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float)  # real OCR engine confidence, NULL if not OCR
    error_message: Mapped[Optional[str]] = mapped_column(String(255))  # user-safe message, no stack traces
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="documents")
    activity: Mapped[Optional["Activity"]] = relationship(back_populates="documents")
    extracted_items: Mapped[List["ExtractedInformation"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    suggestions: Mapped[List["ActivitySuggestion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        _in("processing_status", DOCUMENT_STATUSES, "ck_documents_status"),
        _in("extraction_method", EXTRACTION_METHODS, "ck_documents_method"),
        CheckConstraint("file_size >= 0", name="ck_documents_size"),
        UniqueConstraint("user_id", "sha256", name="uq_documents_user_sha256"),
        Index("ix_documents_user", "user_id"),
        Index("ix_documents_activity", "activity_id"),
    )


class ExtractedInformation(CreatedMixin, Base):
    __tablename__ = "extracted_information"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    info_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[str]] = mapped_column(String(300))  # surrounding text, so the user can verify it
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="RULE", server_default="RULE")

    document: Mapped["Document"] = relationship(back_populates="extracted_items")

    __table_args__ = (
        _in("info_type", INFO_TYPES, "ck_extracted_type"),
        _in("source", INFO_SOURCES, "ck_extracted_source"),
        Index("ix_extracted_document", "document_id"),
    )


class ActivitySuggestion(CreatedMixin, Base):
    """A suggested document -> activity match. Nothing is moved until the user confirms."""

    __tablename__ = "activity_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)  # human-readable "why was this suggested"
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING", server_default="PENDING")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    document: Mapped["Document"] = relationship(back_populates="suggestions")
    activity: Mapped["Activity"] = relationship()

    __table_args__ = (
        _in("status", SUGGESTION_STATUSES, "ck_suggestions_status"),
        Index("ix_suggestions_document", "document_id"),
    )


# ---------------------------------------------------------------------------
# Organizer entities (all belong to one activity)
# ---------------------------------------------------------------------------
class Task(UpdatedMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3, server_default="3")  # 1..5
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="PENDING", server_default="PENDING")
    # Optional user override of the calculated priority. The score itself is computed on demand
    # (deterministic function of the task + activity), so it is never stored and never goes stale.
    manual_priority: Mapped[Optional[str]] = mapped_column(String(10))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    activity: Mapped["Activity"] = relationship(back_populates="tasks")

    __table_args__ = (
        _in("status", TASK_STATUSES, "ck_tasks_status"),
        CheckConstraint("importance BETWEEN 1 AND 5", name="ck_tasks_importance"),
        CheckConstraint(
            "manual_priority IS NULL OR manual_priority IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')",
            name="ck_tasks_manual_priority",
        ),
        Index("ix_tasks_activity_status", "activity_id", "status"),
        Index("ix_tasks_activity_due", "activity_id", "due_date"),
    )


class Note(UpdatedMixin, Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    activity: Mapped["Activity"] = relationship(back_populates="notes")

    __table_args__ = (Index("ix_notes_activity", "activity_id"),)


class Expense(CreatedMixin, Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # exact decimal, never float/string
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)

    activity: Mapped["Activity"] = relationship(back_populates="expenses")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_expenses_amount"),
        Index("ix_expenses_activity_date", "activity_id", "expense_date"),
    )


class Reminder(CreatedMixin, Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    activity: Mapped["Activity"] = relationship(back_populates="reminders")

    __table_args__ = (Index("ix_reminders_due", "is_triggered", "remind_at"),)


class Notification(CreatedMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reminder_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reminders.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    user: Mapped["User"] = relationship(back_populates="notifications")

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)


# ---------------------------------------------------------------------------
# History (audit trail) and AI interaction log
# ---------------------------------------------------------------------------
class ActivityHistory(CreatedMixin, Base):
    __tablename__ = "activity_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. DOCUMENT_UPLOADED, SUGGESTION_CONFIRMED
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    details: Mapped[Optional[str]] = mapped_column(Text)

    activity: Mapped["Activity"] = relationship(back_populates="history")

    __table_args__ = (Index("ix_history_activity_created", "activity_id", "created_at"),)


class AIInteraction(CreatedMixin, Base):
    __tablename__ = "ai_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="SUCCESS", server_default="SUCCESS")
    error_message: Mapped[Optional[str]] = mapped_column(String(255))

    activity: Mapped["Activity"] = relationship(back_populates="ai_interactions")

    __table_args__ = (
        _in("status", AI_STATUSES, "ck_ai_status"),
        Index("ix_ai_activity_created", "activity_id", "created_at"),
    )
