"""Activity workspace: one activity = one place for its tasks, notes, expenses and reminders.

It is opened from the Activities page (the id of the open activity is kept in st.session_state["open_activity_id"]).
The sections are chosen with a horizontal selector instead of st.tabs: st.tabs jumps back to the first tab after every
save and runs all sections on every click, whereas the selector remembers the section and loads only the one in use.
"""
import streamlit as st

import api_client as api
import formatting as fmt
import ui
from views import ws_assistant, ws_documents, ws_expenses, ws_history, ws_notes, ws_reminders, ws_tasks

# section labels (also used by navigation.go_activity to open the workspace on a given section)
TASKS = "✅ Tasks"
DOCUMENTS = "📄 Documents"
NOTES = "📝 Notes"
EXPENSES = "💰 Expenses"
REMINDERS = "⏰ Reminders"
ASSISTANT = "🤖 Assistant"
HISTORY = "🕘 History"

SECTIONS = {
    TASKS: ws_tasks,
    DOCUMENTS: ws_documents,
    NOTES: ws_notes,
    EXPENSES: ws_expenses,
    REMINDERS: ws_reminders,
    ASSISTANT: ws_assistant,
    HISTORY: ws_history,
}


def open_workspace(activity_id: int) -> None:
    _clear_workspace_state()
    st.session_state["open_activity_id"] = activity_id


def close_workspace() -> None:
    """Back button callback."""
    _clear_workspace_state()
    st.session_state.pop("open_activity_id", None)


def _clear_workspace_state() -> None:
    """Forget every workspace-only value (selected section, filters, edit / confirm state)."""
    for key in [k for k in st.session_state if str(k).startswith("ws_")]:
        del st.session_state[key]


def render(activity_id: int) -> None:
    ok, activity = ui.attempt(api.get_activity, activity_id)
    if not ok:
        if ui.last_error_status() == 404:  # deleted meanwhile
            close_workspace()
            ui.flash_ok("That activity no longer exists.")
            st.rerun()
        st.button("← Back to all activities", on_click=close_workspace)
        return

    st.button("← Back to all activities", on_click=close_workspace)
    st.title(f"📂 {activity['title']}")
    st.markdown(f"{fmt.type_label(activity['activity_type'])} · {fmt.status_label(activity['status'])} · "
                f"Priority: {fmt.priority_text(activity['priority'])}")
    st.caption(f"Start: {fmt.format_date(activity['start_date'])} · Deadline: {fmt.format_date(activity['deadline'])}")
    if activity.get("description"):
        st.write(fmt.short(activity["description"], 400))
    ui.show_flash()

    section = st.radio("Section", list(SECTIONS), horizontal=True, key="ws_section", label_visibility="collapsed")
    st.divider()
    SECTIONS[section].render(activity_id)
