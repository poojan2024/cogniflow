"""Login / registration screen."""
import streamlit as st

import api_client as api
import session


def show(ctrl) -> None:
    st.title("🌟Cogniflow")
    st.caption("An AI-assisted personal digital organizer: one activity, one workspace.")
    flash = st.session_state.pop("flash", None)
    if flash:
        st.info(flash)

    login_tab, register_tab = st.tabs(["Log in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary")
        if submitted:
            if not email.strip() or not password:
                st.error("Please enter your email and password.")
            else:
                try:
                    data = api.login_full(email, password)
                    user = api.me(data["access_token"])
                    session.start(ctrl, data["access_token"], user, data.get("expires_in"))
                except api.ApiError as e:
                    st.error(str(e))

    with register_tab:
        with st.form("register_form"):
            name = st.text_input("Full name")
            reg_email = st.text_input("Email", key="reg_email")
            reg_password = st.text_input(
                "Password", type="password", key="reg_password",
                help="At least 8 characters, with at least one letter and one digit.",
            )
            reg_submitted = st.form_submit_button("Create account", type="primary")
        if reg_submitted:
            if not name.strip() or not reg_email.strip() or not reg_password:
                st.error("Please fill in your name, email and password.")
            else:
                try:
                    api.register(reg_email, name, reg_password)
                    st.success("Account created. You can now log in from the 'Log in' tab.")
                except api.ApiError as e:
                    st.error(str(e))
