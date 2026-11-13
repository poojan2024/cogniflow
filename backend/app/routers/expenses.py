"""Expense tracking inside one activity. Manual entry always works (no AI or OCR needed)."""
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_owned_activity
from app.models import Activity, Expense
from app.schemas.organizer import ExpenseCreate, ExpenseList, ExpenseOut, ExpenseUpdate
from app.services.common import get_child_or_404
from app.services.history import log_event

router = APIRouter(prefix="/activities/{activity_id}/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)
):
    expense = Expense(activity_id=activity.id, **payload.model_dump())
    db.add(expense)
    db.flush()
    log_event(db, activity.id, "EXPENSE_ADDED", "expense", expense.id, f"Added expense '{expense.description}' ({expense.amount})")
    db.commit()
    db.refresh(expense)
    return expense


@router.get("", response_model=ExpenseList)
def list_expenses(activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    """All expenses of the activity (newest first) plus the exact total."""
    items = db.scalars(
        select(Expense).where(Expense.activity_id == activity.id).order_by(Expense.expense_date.desc(), Expense.id.desc())
    ).all()
    total = sum((Decimal(str(e.amount)) for e in items), Decimal("0")).quantize(Decimal("0.01"))
    return ExpenseList(items=items, count=len(items), total_amount=total)


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    return get_child_or_404(db, Expense, expense_id, activity.id, "Expense")


@router.patch("/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    expense = get_child_or_404(db, Expense, expense_id, activity.id, "Expense")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(expense, field, value)
    if changes:
        log_event(db, activity.id, "EXPENSE_UPDATED", "expense", expense.id, "Updated: " + ", ".join(sorted(changes)))
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    expense = get_child_or_404(db, Expense, expense_id, activity.id, "Expense")
    log_event(db, activity.id, "EXPENSE_DELETED", "expense", expense.id, f"Deleted expense '{expense.description}'")
    db.delete(expense)
    db.commit()
