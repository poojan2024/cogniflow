"""Small Streamlit helpers shared by all pages."""
import time

import streamlit as st

import api_client as api
import session


def attempt(fn, *args, **kwargs):
    """Run an API function with the logged-in token. Returns (ok, result).

    Needed for calls such as DELETE whose successful result is empty (None), so success and failure can be told apart.
    On failure a friendly message is shown. An expired / invalid token (401) logs the user out and returns to the
    login page, so no page ever shows a raw error or crashes.
    """
    try:
        result = fn(st.session_state["token"], *args, **kwargs)
        st.session_state.pop("_last_error_status", None)
        return True, result
    except api.ApiError as e:
        st.session_state["_last_error_status"] = e.status_code  # lets a page react to, for example, a 404
        if e.status_code == 401:
            session.request_logout("Your session has expired. Please log in again.")
            st.rerun()
        st.error(str(e))
        return False, None


def call(fn, *args, **kwargs):
    """Like attempt(), but returns only the result (None on failure). Use it for calls that return data."""
    return attempt(fn, *args, **kwargs)[1]


def show_flash() -> None:
    """One-time success / info message kept across st.rerun()."""
    message = st.session_state.pop("flash_ok", None)
    if message:
        st.success(message)


def flash_ok(message: str) -> None:
    st.session_state["flash_ok"] = message


def empty_state(icon: str, title: str, hint: str) -> None:
    with st.container(border=True):
        st.markdown(f"### {icon} {title}")
        st.caption(hint)


def last_error_status():
    return st.session_state.get("_last_error_status")


def delete_controls(name: str, item_id: int, fn, args: tuple, warning: str, success: str) -> None:
    """A Delete button that first asks "are you sure?". `fn(token, *args)` is the API call that deletes."""
    state_key = f"ws_confirm_{name}"
    if st.session_state.get(state_key) == item_id:
        st.warning(warning)
        yes, no = st.columns(2)
        if yes.button("Yes, delete", key=f"{name}_yes_{item_id}", type="primary"):
            ok, _ = attempt(fn, *args)
            if ok:
                st.session_state.pop(state_key, None)
                flash_ok(success)
                st.rerun()
        if no.button("Keep it", key=f"{name}_no_{item_id}"):
            st.session_state.pop(state_key, None)
            st.rerun()
        return
    if st.button("🗑️ Delete", key=f"{name}_del_{item_id}"):
        st.session_state[state_key] = item_id
        st.rerun()


def load_activities():
    """The user's activities (up to 100) for 'choose an activity' lists. None if the call failed."""
    result = call(api.list_activities, page_size=100)
    return None if result is None else result["items"]


def poll_while(in_progress: bool, key: str = "poll_count", interval: float = 2.0, max_polls: int = 40) -> None:
    """Reloads the page every few seconds while a document is still being processed.

    Stops after max_polls (about 80 seconds) so a stuck job can never reload the page forever; the user can press
    Refresh to start again. Call this at the very END of a page so everything is already drawn while it waits."""
    if not in_progress:
        st.session_state.pop(key, None)
        return
    polls = st.session_state.get(key, 0)
    if polls >= max_polls:
        st.info("This is taking longer than usual. Press “Refresh” to check again.")
        return
    st.session_state[key] = polls + 1
    time.sleep(interval)
    st.rerun()


def reset_polling(key: str = "poll_count") -> None:
    """Button callback for 'Refresh'."""
    st.session_state[key] = 0
