"""Activities page: list with search / filter / sort / paging, create, edit and delete (with confirmation)."""
import math
from typing import Optional

import streamlit as st

import api_client as api
import formatting as fmt
import ui
from views import workspace

PAGE_SIZE = 10
ALL = "All"


def _reset_page() -> None:
    st.session_state["act_page"] = 1


def _activity_form(key: str, activity: Optional[dict] = None) -> None:
    """The same form is used for creating (activity=None) and editing."""
    a = activity or {}
    editing = activity is not None
    with st.form(key, clear_on_submit=not editing):
        title = st.text_input("Title *", value=a.get("title", ""), max_chars=200)
        description = st.text_area("Description", value=a.get("description") or "", max_chars=5000, height=100)
        c1, c2, c3 = st.columns(3)
        activity_type = c1.selectbox(
            "Type", fmt.ACTIVITY_TYPES, format_func=fmt.nice,
            index=fmt.ACTIVITY_TYPES.index(a.get("activity_type", "CUSTOM")))
        status = c2.selectbox(
            "Status", fmt.ACTIVITY_STATUSES, format_func=fmt.nice,
            index=fmt.ACTIVITY_STATUSES.index(a.get("status", "ACTIVE")))
        priority = c3.slider("Priority (1 = low, 5 = high)", 1, 5, int(a.get("priority", 3)))
        d1, d2 = st.columns(2)
        start = d1.date_input("Start date", value=fmt.parse_date(a.get("start_date")), format="DD/MM/YYYY")
        deadline = d2.date_input("Deadline", value=fmt.parse_date(a.get("deadline")), format="DD/MM/YYYY")
        b1, b2 = st.columns([1, 1])
        saved = b1.form_submit_button("Save changes" if editing else "Create activity", type="primary")
        cancelled = b2.form_submit_button("Cancel") if editing else False

    if cancelled:
        st.session_state.pop("editing_id", None)
        st.rerun()
    if not saved:
        return
    if not title.strip():
        st.error("Please enter a title.")
        return
    if start and deadline and deadline < start:
        st.error("The deadline cannot be before the start date.")
        return
    payload = {
        "title": title.strip(), "description": description.strip() or None, "activity_type": activity_type,
        "status": status, "priority": priority, "start_date": start, "deadline": deadline,
    }
    if editing:
        ok, _ = ui.attempt(api.update_activity, a["id"], payload)
        message = "Activity updated."
    else:
        ok, _ = ui.attempt(api.create_activity, payload)
        message = "Activity created."
    if ok:
        st.session_state.pop("editing_id", None)
        ui.flash_ok(message)
        st.rerun()


def _activity_card(a: dict) -> None:
    activity_id = a["id"]
    with st.container(border=True):
        st.markdown(f"#### {a['title']}")
        st.markdown(f"{fmt.type_label(a['activity_type'])} · {fmt.status_label(a['status'])} · Priority: {fmt.priority_text(a['priority'])}")
        st.caption(f"Start: {fmt.format_date(a['start_date'])} · Deadline: {fmt.format_date(a['deadline'])}")
        if a.get("description"):
            st.write(fmt.short(a["description"], 220))

        if st.session_state.get("confirm_delete_id") == activity_id:
            st.warning("Delete this activity and everything inside it (documents, tasks, notes, expenses, reminders, history)? This cannot be undone.")
            y, n = st.columns(2)
            if y.button("Yes, delete it", key=f"del_yes_{activity_id}", type="primary"):
                ok, _ = ui.attempt(api.delete_activity, activity_id)
                if ok:
                    st.session_state.pop("confirm_delete_id", None)
                    ui.flash_ok("Activity deleted.")
                    st.rerun()
            if n.button("Keep it", key=f"del_no_{activity_id}"):
                st.session_state.pop("confirm_delete_id", None)
                st.rerun()
            return

        o, e, d, _ = st.columns([2, 1, 1, 5])
        if o.button("📂 Open workspace", key=f"open_{activity_id}", type="primary"):
            workspace.open_workspace(activity_id)
            st.rerun()
        if e.button("✏️ Edit", key=f"edit_{activity_id}"):
            st.session_state["editing_id"] = activity_id
            st.rerun()
        if d.button("🗑️ Delete", key=f"del_{activity_id}"):
            st.session_state["confirm_delete_id"] = activity_id
            st.rerun()


def render() -> None:
    open_id = st.session_state.get("open_activity_id")
    if open_id is not None:  # an activity workspace is open: show it instead of the list
        workspace.render(open_id)
        return

    st.title("🗂️ Activities")
    ui.show_flash()

    with st.expander("➕ New activity", expanded=False):
        _activity_form("create_activity_form")

    # ---- filters
    f1, f2, f3, f4 = st.columns([3, 2, 2, 2])
    q = f1.text_input("Search", placeholder="Search title or description", key="act_q", on_change=_reset_page)
    type_choice = f2.selectbox("Type", [ALL] + fmt.ACTIVITY_TYPES, format_func=lambda v: v if v == ALL else fmt.nice(v),
                               key="act_type", on_change=_reset_page)
    status_choice = f3.selectbox("Status", [ALL] + fmt.ACTIVITY_STATUSES, format_func=lambda v: v if v == ALL else fmt.nice(v),
                                 key="act_status", on_change=_reset_page)
    sort_label = f4.selectbox("Sort by", list(fmt.SORT_OPTIONS), key="act_sort", on_change=_reset_page)

    page = int(st.session_state.get("act_page", 1))
    with st.spinner("Loading activities…"):
        result = ui.call(
            api.list_activities, q=q,
            activity_type=None if type_choice == ALL else type_choice,
            status=None if status_choice == ALL else status_choice,
            sort=fmt.SORT_OPTIONS[sort_label], page=page, page_size=PAGE_SIZE,
        )
    if result is None:
        return

    total = result["total"]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    if page > pages:  # for example after deleting the last item of the last page
        st.session_state["act_page"] = pages
        st.rerun()

    editing_id = st.session_state.get("editing_id")
    if total == 0:
        filtered = bool(q.strip()) or type_choice != ALL or status_choice != ALL
        if filtered:
            ui.empty_state("🔍", "No matching activities", "Try a different search or clear the filters.")
        else:
            ui.empty_state("🗂️", "No activities yet", "Open “New activity” above to create your first one.")
        return

    st.caption(f"{total} activit{'y' if total == 1 else 'ies'}")
    for a in result["items"]:
        if editing_id == a["id"]:
            with st.container(border=True):
                st.markdown(f"#### Editing: {a['title']}")
                _activity_form(f"edit_activity_form_{a['id']}", a)
        else:
            _activity_card(a)

    if pages > 1:
        st.number_input(f"Page (1–{pages})", min_value=1, max_value=pages, step=1, key="act_page")
