"""Notes tab of the activity workspace: create, search, edit, delete."""
from typing import Optional

import streamlit as st

import api_client as api
import formatting as fmt
import ui


def _note_form(key: str, activity_id: int, note: Optional[dict] = None) -> None:
    n = note or {}
    editing = note is not None
    with st.form(key, clear_on_submit=not editing):
        title = st.text_input("Note title *", value=n.get("title", ""), max_chars=200, key=f"{key}_title")
        content = st.text_area("Content", value=n.get("content", ""), max_chars=20000, height=160, key=f"{key}_content")
        b1, b2 = st.columns(2)
        saved = b1.form_submit_button("Save changes" if editing else "Add note", type="primary")
        cancelled = b2.form_submit_button("Cancel") if editing else False

    if cancelled:
        st.session_state.pop("ws_editing_note", None)
        st.rerun()
    if not saved:
        return
    if not title.strip():
        st.error("Please enter a note title.")
        return
    payload = {"title": title.strip(), "content": content}
    if editing:
        ok, _ = ui.attempt(api.update_note, activity_id, n["id"], payload)
        message = "Note updated."
    else:
        ok, _ = ui.attempt(api.create_note, activity_id, payload)
        message = "Note added."
    if ok:
        st.session_state.pop("ws_editing_note", None)
        ui.flash_ok(message)
        st.rerun()


def _note_card(activity_id: int, n: dict) -> None:
    note_id = n["id"]
    with st.container(border=True):
        st.markdown(f"#### {n['title']}")
        st.caption(f"Updated {fmt.format_datetime(n['updated_at'])}")
        if n.get("content"):
            st.markdown(n["content"])  # Streamlit escapes any HTML in the text
        else:
            st.caption("(no content)")

        if st.session_state.get("ws_confirm_note") == note_id:
            ui.delete_controls("note", note_id, api.delete_note, (activity_id, note_id),
                               "Delete this note? This cannot be undone.", "Note deleted.")
            return
        e, d, _ = st.columns([1, 1, 5])
        if e.button("✏️ Edit", key=f"note_edit_{note_id}"):
            st.session_state["ws_editing_note"] = note_id
            st.rerun()
        with d:
            ui.delete_controls("note", note_id, api.delete_note, (activity_id, note_id),
                               "Delete this note? This cannot be undone.", "Note deleted.")


def render(activity_id: int) -> None:
    with st.expander("➕ Add a note"):
        _note_form("ws_new_note_form", activity_id)

    q = st.text_input("Search notes", placeholder="Search note titles and content", key="ws_note_q")
    with st.spinner("Loading notes…"):
        notes = ui.call(api.list_notes, activity_id, q=q)
    if notes is None:
        return
    if not notes:
        if q.strip():
            ui.empty_state("🔍", "No matching notes", "Try different words.")
        else:
            ui.empty_state("📝", "No notes yet", "Open “Add a note” above to write your first note for this activity.")
        return

    st.caption(f"{len(notes)} note{'s' if len(notes) != 1 else ''}")
    editing_id = st.session_state.get("ws_editing_note")
    for n in notes:
        if editing_id == n["id"]:
            with st.container(border=True):
                st.markdown(f"#### Editing: {n['title']}")
                _note_form(f"ws_edit_note_form_{n['id']}", activity_id, n)
        else:
            _note_card(activity_id, n)
