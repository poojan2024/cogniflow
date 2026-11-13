"""Reminders tab of the activity workspace.

A reminder becomes a notification when its time has passed and the user next opens the Dashboard or Notifications
(the backend has no background scheduler; see services/reminders.py). The backend requires a time-zone offset on
every reminder time, so the date and time typed here are converted using the computer's own time zone.
"""
from datetime import date, datetime, time
from typing import Optional

import streamlit as st

import api_client as api
import formatting as fmt
import ui

NO_TASK = None


def _tz_caption() -> str:
    return f"Times use your computer's time zone ({datetime.now().astimezone().strftime('%Z, UTC%z')})."


def _reminder_form(key: str, activity_id: int, tasks: list, reminder: Optional[dict] = None) -> None:
    r = reminder or {}
    editing = reminder is not None
    local = fmt.to_local(r.get("remind_at"))
    task_ids = [NO_TASK] + [t["id"] for t in tasks]
    titles = {t["id"]: t["title"] for t in tasks}
    with st.form(key, clear_on_submit=not editing):
        title = st.text_input("Reminder *", value=r.get("title", ""), max_chars=200, key=f"{key}_title")
        c1, c2 = st.columns(2)
        day = c1.date_input("Date", value=local.date() if local else date.today(), format="DD/MM/YYYY", key=f"{key}_date")
        at = c2.time_input("Time", value=local.time().replace(second=0, microsecond=0) if local else time(9, 0),
                           step=300, key=f"{key}_time")
        linked = st.selectbox(
            "Linked task (optional)", task_ids, key=f"{key}_task",
            index=task_ids.index(r.get("task_id")) if r.get("task_id") in task_ids else 0,
            format_func=lambda i: "None" if i is NO_TASK else titles.get(i, f"Task #{i}"))
        st.caption(_tz_caption())
        b1, b2 = st.columns(2)
        saved = b1.form_submit_button("Save changes" if editing else "Add reminder", type="primary")
        cancelled = b2.form_submit_button("Cancel") if editing else False

    if cancelled:
        st.session_state.pop("ws_editing_reminder", None)
        st.rerun()
    if not saved:
        return
    if not title.strip():
        st.error("Please enter what the reminder is for.")
        return
    payload = {"title": title.strip(), "remind_at": fmt.local_iso(day, at), "task_id": linked}
    if editing:
        ok, _ = ui.attempt(api.update_reminder, activity_id, r["id"], payload)
        message = "Reminder updated."
    else:
        ok, _ = ui.attempt(api.create_reminder, activity_id, payload)
        message = "Reminder added."
    if ok:
        if fmt.is_past(day, at):
            message += " Its time has already passed, so it will show up in Notifications the next time you open the Dashboard."
        st.session_state.pop("ws_editing_reminder", None)
        ui.flash_ok(message)
        st.rerun()


def _reminder_card(activity_id: int, r: dict, task_titles: dict) -> None:
    reminder_id = r["id"]
    with st.container(border=True):
        state = "✅ Triggered (see Notifications)" if r["is_triggered"] else "⏳ Scheduled"
        st.markdown(f"**{r['title']}**")
        linked = f" · Task: {task_titles.get(r['task_id'], 'a deleted task')}" if r.get("task_id") else ""
        st.caption(f"{fmt.format_datetime(r['remind_at'])} · {state}{linked}")

        if st.session_state.get("ws_confirm_reminder") == reminder_id:
            ui.delete_controls("reminder", reminder_id, api.delete_reminder, (activity_id, reminder_id),
                               "Delete this reminder? This cannot be undone.", "Reminder deleted.")
            return
        e, d, _ = st.columns([1, 1, 5])
        if e.button("✏️ Edit", key=f"reminder_edit_{reminder_id}"):
            st.session_state["ws_editing_reminder"] = reminder_id
            st.rerun()
        with d:
            ui.delete_controls("reminder", reminder_id, api.delete_reminder, (activity_id, reminder_id),
                               "Delete this reminder? This cannot be undone.", "Reminder deleted.")


def render(activity_id: int) -> None:
    with st.spinner("Loading reminders…"):
        reminders = ui.call(api.list_reminders, activity_id)
        tasks = ui.call(api.list_tasks, activity_id, sort="due") if reminders is not None else None
    if reminders is None:
        return
    tasks = tasks or []  # the task list is only needed for the optional link; reminders work without it

    with st.expander("➕ Add a reminder"):
        _reminder_form("ws_new_reminder_form", activity_id, tasks)

    if not reminders:
        ui.empty_state("⏰", "No reminders yet", "Open “Add a reminder” above for a deadline, appointment or important date.")
        return

    task_titles = {t["id"]: t["title"] for t in tasks}
    editing_id = st.session_state.get("ws_editing_reminder")

    def show(group: list) -> None:
        for r in group:
            if editing_id == r["id"]:
                with st.container(border=True):
                    st.markdown(f"#### Editing: {r['title']}")
                    _reminder_form(f"ws_edit_reminder_form_{r['id']}", activity_id, tasks, r)
            else:
                _reminder_card(activity_id, r, task_titles)

    upcoming = [r for r in reminders if not r["is_triggered"]]
    past = [r for r in reminders if r["is_triggered"]]
    st.subheader(f"Scheduled ({len(upcoming)})")
    if upcoming:
        show(upcoming)
    else:
        st.caption("No scheduled reminders.")
    if past:
        st.subheader(f"Already triggered ({len(past)})")
        show(past)
