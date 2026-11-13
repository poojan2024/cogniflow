"""Jumping from one page to another (for example from a search result to the activity or document it belongs to).

st.switch_page needs the page object, so app.py registers the pages here on every run. The page objects only hold
the page function and its title (no user data), so sharing them in this module is safe.
"""
import streamlit as st

_PAGES = {}


def register(name: str, page) -> None:
    _PAGES[name] = page


def go(name: str) -> None:
    page = _PAGES.get(name)
    if page is None:  # should not happen; fail visibly instead of silently doing nothing
        st.error("That page is not available.")
        return
    st.switch_page(page)


def go_activity(activity_id: int, section: str = None) -> None:
    """Open an activity's workspace, optionally on a given section (the labels are defined in views/workspace.py)."""
    from views import workspace
    workspace.open_workspace(activity_id)
    if section:
        st.session_state["ws_section"] = section
    go("activities")


def go_document(document_id: int) -> None:
    """Open a document's details on the Documents page."""
    st.session_state["doc_open_id"] = document_id
    st.session_state.pop("doc_download", None)
    go("documents")
