"""Cogniflow Streamlit frontend. Run from the frontend/ folder:  streamlit run app.py

Structure: app.py (login gate + navigation) -> views/ (one file per page) -> ui.py / session.py / api_client.py.
Every page talks to the backend only through api_client.py; the backend decides what each user may see.
"""
import streamlit as st

st.set_page_config(page_title="Cogniflow", page_icon=" 🌟Cogniflow", layout="wide")

import auth_page  # noqa: E402
import navigation  # noqa: E402
import session  # noqa: E402
from views import activities, dashboard, documents, notifications, search  # noqa: E402

ctrl = session.cookie_controller()
session.init(ctrl)

# --- login gate. No st.rerun() here: after a successful login the same run simply continues. ---
if not session.is_logged_in():
    box = st.empty()
    with box.container():
        auth_page.show(ctrl)
    if session.is_logged_in():
        box.empty()
    else:
        st.stop()

user = st.session_state["user"]
st.sidebar.markdown("### 🌟Cogniflow")
st.sidebar.markdown(f"**{user['full_name']}**")
st.sidebar.caption(user["email"])
st.sidebar.button("Log out", on_click=session.request_logout, args=("You have been logged out.",))

pages = {
    "dashboard": st.Page(dashboard.render, title="Dashboard", icon="📊", url_path="dashboard", default=True),
    "activities": st.Page(activities.render, title="Activities", icon="🗂️", url_path="activities"),
    "documents": st.Page(documents.render, title="Documents", icon="📄", url_path="documents"),
    "search": st.Page(search.render, title="Search", icon="🔎", url_path="search"),
    "notifications": st.Page(notifications.render, title="Notifications", icon="🔔", url_path="notifications"),
}
for name, page in pages.items():
    navigation.register(name, page)  # lets other pages jump here (for example a search result -> its activity)

st.navigation(list(pages.values())).run()
