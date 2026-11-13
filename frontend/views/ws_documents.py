"""Documents section of the activity workspace: upload straight into this activity and manage its documents.

Because the user chose the activity by uploading here, no activity is suggested for these documents.
"""
import streamlit as st

import api_client as api
import formatting as fmt
import ui
from views import doc_widgets

PAGE_SIZE = 10
OPEN_KEY = "ws_doc_open"


def render(activity_id: int) -> None:
    with st.expander("⬆️ Upload a document to this activity", expanded=True):
        doc_widgets.upload_form("ws_doc", activity_id, None, OPEN_KEY)

    open_id = st.session_state.get(OPEN_KEY)
    open_status = None
    if open_id is not None:
        open_status = doc_widgets.detail_panel(open_id, OPEN_KEY, None, in_workspace=True)

    page = int(st.session_state.get("ws_doc_page", 1))
    with st.spinner("Loading documents…"):
        result = ui.call(api.list_documents, activity_id=activity_id, page=page, page_size=PAGE_SIZE)
    if result is None:
        return
    total = result["total"]
    pages = max(1, -(-total // PAGE_SIZE))
    if page > pages:
        st.session_state["ws_doc_page"] = pages
        st.rerun()

    if total == 0:
        ui.empty_state("📄", "No documents in this activity yet",
                       "Upload one above. Text is read directly; scanned pages and photos are read with OCR.")
    else:
        st.caption(f"{total} document{'s' if total != 1 else ''}")
        doc_widgets.document_rows(result["items"], OPEN_KEY, "ws_doc")
        doc_widgets.pager(total, "ws_doc_page", PAGE_SIZE)

    busy = open_status in fmt.DOC_IN_PROGRESS or any(d["processing_status"] in fmt.DOC_IN_PROGRESS for d in result["items"])
    ui.poll_while(busy)
