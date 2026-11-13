"""History section of the activity workspace: a readable timeline of what happened in this activity."""
import streamlit as st

import api_client as api
import formatting as fmt
import ui

PAGE_SIZE = 20


def render(activity_id: int) -> None:
    page = int(st.session_state.get("ws_hist_page", 1))
    with st.spinner("Loading history…"):
        data = ui.call(api.activity_history, activity_id, page=page, page_size=PAGE_SIZE)
    if data is None:
        return
    total = data["total"]
    pages = max(1, -(-total // PAGE_SIZE))
    if page > pages:
        st.session_state["ws_hist_page"] = pages
        st.rerun()
    if total == 0:
        ui.empty_state("🕘", "Nothing has happened yet", "Uploads, tasks, notes, expenses and other changes appear here.")
        return

    st.caption(f"{total} event{'s' if total != 1 else ''}, newest first")
    for event in data["items"]:
        with st.container(border=True):
            st.markdown(f"{fmt.history_icon(event['action'])} **{fmt.nice(event['action'])}**")
            if event.get("details"):
                st.write(fmt.md_escape(event["details"]))
            st.caption(fmt.format_datetime(event["created_at"]))
    if pages > 1:
        st.number_input(f"Page (1–{pages})", min_value=1, max_value=pages, step=1, key="ws_hist_page")
