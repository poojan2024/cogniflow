"""Global search page. The backend searches only the logged-in user's own data."""
import streamlit as st

import api_client as api
import formatting as fmt
import navigation
import ui
from views import workspace

# which workspace section shows a hit of this type
SECTION_FOR_TYPE = {"tasks": workspace.TASKS, "notes": workspace.NOTES, "expenses": workspace.EXPENSES}


def _open(hit: dict) -> None:
    """Jump to the thing that was found."""
    kind = hit["type"]
    if kind == "documents":
        navigation.go_document(hit["id"])
    elif kind == "extracted":
        navigation.go_document(hit["document_id"])
    elif kind == "activities":
        navigation.go_activity(hit["id"])
    elif hit.get("activity_id") is not None:
        navigation.go_activity(hit["activity_id"], SECTION_FOR_TYPE.get(kind))


def render() -> None:
    st.title("🔎 Search")
    st.caption("Searches only your own activities, documents, extracted information, notes, tasks and expenses.")

    query = st.text_input("Search", key="search_q", max_chars=100, placeholder="Type at least 2 characters and press Enter").strip()
    c1, c2 = st.columns([4, 1])
    all_types = list(fmt.SEARCH_TYPES)
    types = c1.multiselect("Look in", all_types, default=all_types, format_func=fmt.SEARCH_TYPES.get, key="search_types")
    limit = c2.selectbox("Per type", [10, 25], key="search_limit")

    if not query:
        ui.empty_state("🔎", "Search everything in one place",
                       "Try a project name, a date, a person from a document or an expense description.")
        return
    if len(query) < 2:
        st.info("Please type at least 2 characters.")
        return
    if not types:
        st.info("Choose at least one place to look in.")
        return

    with st.spinner("Searching…"):
        result = ui.call(api.search, query, types=None if set(types) == set(all_types) else ",".join(types), limit=limit)
    if result is None:
        return
    if result["total"] == 0:
        ui.empty_state("🤷", f"No results for “{fmt.md_escape(query)}”", "Try other words, or look in more places.")
        return

    st.caption(f"{result['total']} result{'s' if result['total'] != 1 else ''}")
    for kind in all_types:
        hits = [h for h in result["results"] if h["type"] == kind]
        if not hits:
            continue
        st.subheader(f"{fmt.SEARCH_TYPES[kind]} ({len(hits)})")
        for hit in hits:
            with st.container(border=True):
                c_text, c_btn = st.columns([6, 1])
                c_text.markdown(f"**{fmt.md_escape(hit['title'])}**")
                if hit.get("snippet"):
                    c_text.caption(fmt.md_escape(hit["snippet"]))
                if hit.get("activity_title"):
                    c_text.caption(f"In: {fmt.md_escape(hit['activity_title'])}")
                if c_btn.button("Open", key=f"search_open_{kind}_{hit['id']}"):
                    _open(hit)
