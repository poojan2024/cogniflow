"""Notifications page. Opening it turns reminders whose time has passed into notifications (there is no background scheduler)."""
import streamlit as st

import api_client as api
import formatting as fmt
import ui

PAGE_SIZE = 20


def _reset_page() -> None:
    st.session_state["notif_page"] = 1


def render() -> None:
    st.title("🔔 Notifications")
    ui.show_flash()
    st.caption("A reminder appears here once its time has passed and you open Cogniflow.")

    unread_only = st.checkbox("Show unread only", key="notif_unread", on_change=_reset_page)
    page = int(st.session_state.get("notif_page", 1))
    with st.spinner("Loading notifications…"):
        data = ui.call(api.list_notifications, unread_only=unread_only, page=page, page_size=PAGE_SIZE)
    if data is None:
        return

    total = data["total"]
    pages = max(1, -(-total // PAGE_SIZE))
    if page > pages:
        st.session_state["notif_page"] = pages
        st.rerun()

    c1, c2 = st.columns([1, 1])
    c1.metric("Unread", data["unread_count"])
    if data["unread_count"] and c2.button("✔ Mark all as read", key="notif_read_all"):
        ok, _ = ui.attempt(api.mark_all_notifications_read)
        if ok:
            ui.flash_ok("All notifications marked as read.")
            st.rerun()

    if total == 0:
        if unread_only:
            ui.empty_state("✅", "No unread notifications", "You are all caught up.")
        else:
            ui.empty_state("🔔", "No notifications yet", "Create a reminder in an activity's workspace. It shows up here when its time has passed.")
        return

    for n in data["items"]:
        with st.container(border=True):
            if st.session_state.get("ws_confirm_notification") == n["id"]:
                ui.delete_controls("notification", n["id"], api.delete_notification, (n["id"],),
                                   "Delete this notification? This cannot be undone.", "Notification deleted.")
                continue
            c_text, c_read, c_del = st.columns([6, 2, 1])
            marker = "" if n["is_read"] else "🔵 "
            c_text.markdown(f"{marker}**{fmt.md_escape(n['message'])}**")
            c_text.caption(fmt.format_datetime(n["created_at"]) + ("" if n["is_read"] else " · new"))
            if not n["is_read"] and c_read.button("Mark as read", key=f"notif_read_{n['id']}"):
                ok, _ = ui.attempt(api.mark_notification_read, n["id"])
                if ok:
                    st.rerun()
            with c_del:
                ui.delete_controls("notification", n["id"], api.delete_notification, (n["id"],), "", "Notification deleted.")

    if pages > 1:
        st.number_input(f"Page (1–{pages})", min_value=1, max_value=pages, step=1, key="notif_page")
