"""Documents page: upload, watch processing, read the extracted information, confirm or reject the suggested activity."""
from typing import Optional

import streamlit as st

import api_client as api
import formatting as fmt
import ui
from views import doc_widgets

PAGE_SIZE = 10
OPEN_KEY = "doc_open_id"
ALL = "all"
UNASSIGNED = "unassigned"


def _reset_page() -> None:
    st.session_state["doc_page"] = 1


def render() -> None:
    st.title("📄 Documents")
    ui.show_flash()

    activities = ui.load_activities()
    if activities is None:
        st.caption("Your activities could not be loaded. Check that the backend is running, then reload this page.")
        return
    titles = {a["id"]: a["title"] for a in activities}

    with st.container(border=True):
        st.subheader("⬆️ Upload a document")
        doc_widgets.upload_form("doc", None, activities, OPEN_KEY)

    open_id = st.session_state.get(OPEN_KEY)
    open_status: Optional[str] = None
    if open_id is not None:
        st.subheader("Document details")
        open_status = doc_widgets.detail_panel(open_id, OPEN_KEY, activities)

    st.subheader("Your documents")
    f1, f2 = st.columns(2)
    scope_options = [ALL, UNASSIGNED] + list(titles)
    scope = f1.selectbox(
        "Show", scope_options, key="doc_scope", on_change=_reset_page,
        format_func=lambda v: "All documents" if v == ALL else "Not in an activity yet" if v == UNASSIGNED else f"In: {titles[v]}")
    status_choice = f2.selectbox(
        "Status", ["All"] + list(fmt._DOC_STATUS), key="doc_status", on_change=_reset_page,
        format_func=lambda v: v if v == "All" else fmt.nice(v))

    page = int(st.session_state.get("doc_page", 1))
    with st.spinner("Loading documents…"):
        result = ui.call(api.list_documents,
                         activity_id=scope if isinstance(scope, int) else None,
                         unassigned=scope == UNASSIGNED,
                         status=None if status_choice == "All" else status_choice,
                         page=page, page_size=PAGE_SIZE)
    if result is None:
        return

    total = result["total"]
    pages = max(1, -(-total // PAGE_SIZE))
    if page > pages:
        st.session_state["doc_page"] = pages
        st.rerun()

    if total == 0:
        if scope != ALL or status_choice != "All":
            ui.empty_state("🔍", "No documents match these filters", "Change or clear the filters above.")
        else:
            ui.empty_state("📄", "No documents yet", "Upload a PDF, photo, scan or text file above. "
                           "Cogniflow reads it, finds dates and amounts, and suggests which activity it belongs to.")
    else:
        st.caption(f"{total} document{'s' if total != 1 else ''}")
        doc_widgets.document_rows(result["items"], OPEN_KEY, "doc", titles)
        doc_widgets.pager(total, "doc_page", PAGE_SIZE)

    busy = open_status in fmt.DOC_IN_PROGRESS or any(d["processing_status"] in fmt.DOC_IN_PROGRESS for d in result["items"])
    ui.poll_while(busy)
