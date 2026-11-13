"""Expenses tab of the activity workspace. Manual entry only: it needs no AI and no OCR."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd
import streamlit as st

import api_client as api
import formatting as fmt
import ui

PRESET_CATEGORIES = ["Food", "Transport", "Accommodation", "Shopping", "Fees", "Study material", "Other"]
NO_CATEGORY = "(none)"


def _money_text(value: float) -> str:
    """Number typed in the form -> exact 2-decimal text for the API (no float rounding noise)."""
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return "0.00"


def _expense_form(key: str, activity_id: int, expense: Optional[dict] = None) -> None:
    x = expense or {}
    editing = expense is not None
    current_cat = x.get("category") or ""
    options = [NO_CATEGORY] + PRESET_CATEGORIES
    with st.form(key, clear_on_submit=not editing):
        description = st.text_input("Description *", value=x.get("description", ""), max_chars=255, key=f"{key}_desc")
        c1, c2, c3 = st.columns(3)
        amount = c1.number_input("Amount (₹) *", min_value=0.0, step=10.0, format="%.2f", key=f"{key}_amount",
                                 value=fmt.to_number(x.get("amount", 0)))
        when = c2.date_input("Date", value=fmt.parse_date(x.get("expense_date")) or date.today(), format="DD/MM/YYYY",
                             key=f"{key}_date")
        preset = c3.selectbox("Category", options, key=f"{key}_cat",
                              index=options.index(current_cat) if current_cat in options else 0)
        custom = st.text_input("Or type your own category", max_chars=50, key=f"{key}_custom",
                               value=current_cat if current_cat and current_cat not in options else "",
                               help="If filled in, this is used instead of the list above.")
        b1, b2 = st.columns(2)
        saved = b1.form_submit_button("Save changes" if editing else "Add expense", type="primary")
        cancelled = b2.form_submit_button("Cancel") if editing else False

    if cancelled:
        st.session_state.pop("ws_editing_expense", None)
        st.rerun()
    if not saved:
        return
    if not description.strip():
        st.error("Please enter a description.")
        return
    category = custom.strip() or (None if preset == NO_CATEGORY else preset)
    payload = {"description": description.strip(), "category": category, "amount": _money_text(amount), "expense_date": when}
    if editing:
        ok, _ = ui.attempt(api.update_expense, activity_id, x["id"], payload)
        message = "Expense updated."
    else:
        ok, _ = ui.attempt(api.create_expense, activity_id, payload)
        message = "Expense added."
    if ok:
        st.session_state.pop("ws_editing_expense", None)
        ui.flash_ok(message)
        st.rerun()


def _category_totals(items: list) -> dict:
    totals = defaultdict(lambda: Decimal("0"))
    for e in items:
        totals[e.get("category") or "Uncategorised"] += Decimal(str(e["amount"]))
    return dict(totals)


def _expense_row(activity_id: int, e: dict) -> None:
    expense_id = e["id"]
    with st.container(border=True):
        if st.session_state.get("ws_confirm_expense") == expense_id:
            ui.delete_controls("expense", expense_id, api.delete_expense, (activity_id, expense_id),
                               f"Delete the expense “{e['description']}”? This cannot be undone.", "Expense deleted.")
            return
        c1, c2, c3, c4 = st.columns([5, 2, 1, 1])
        c1.markdown(f"**{e['description']}**  \n{e.get('category') or 'Uncategorised'} · {fmt.format_date(e['expense_date'])}")
        c2.markdown(f"**{fmt.format_money(e['amount'])}**")
        if c3.button("✏️", key=f"expense_edit_{expense_id}", help="Edit"):
            st.session_state["ws_editing_expense"] = expense_id
            st.rerun()
        with c4:
            ui.delete_controls("expense", expense_id, api.delete_expense, (activity_id, expense_id), "", "Expense deleted.")


def render(activity_id: int) -> None:
    with st.expander("➕ Add an expense"):
        _expense_form("ws_new_expense_form", activity_id)

    with st.spinner("Loading expenses…"):
        data = ui.call(api.list_expenses, activity_id)
    if data is None:
        return
    items = data["items"]
    if not items:
        ui.empty_state("💰", "No expenses yet", "Open “Add an expense” above. The total for this activity is calculated for you.")
        return

    m1, m2 = st.columns(2)
    m1.metric("Total for this activity", fmt.format_money(data["total_amount"]))  # exact total from the backend
    m2.metric("Expenses recorded", data["count"])

    totals = _category_totals(items)
    if len(totals) > 1:
        st.markdown("**By category**")
        st.bar_chart(pd.DataFrame({"₹": [float(v) for v in totals.values()]}, index=list(totals.keys())))

    editing_id = st.session_state.get("ws_editing_expense")
    for e in items:
        if editing_id == e["id"]:
            with st.container(border=True):
                st.markdown(f"#### Editing: {e['description']}")
                _expense_form(f"ws_edit_expense_form_{e['id']}", activity_id, e)
        else:
            _expense_row(activity_id, e)
