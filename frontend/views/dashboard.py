"""Dashboard page: one call to GET /dashboard, shown as metrics, lists and charts."""
import pandas as pd
import streamlit as st

import api_client as api
import formatting as fmt
import ui


def render() -> None:
    st.title("📊 Dashboard")
    ui.show_flash()

    with st.spinner("Loading your dashboard…"):
        data = ui.call(api.dashboard)
    if data is None:
        st.caption("The dashboard could not be loaded. Check that the backend is running, then reload this page.")
        return

    overview = data["overview"]
    attention = data["attention"]

    # ---- things that need the user's attention
    notes = []
    if attention["unread_notifications"]:
        notes.append(f"🔔 {attention['unread_notifications']} unread notification(s)")
    if attention["pending_suggestions"]:
        notes.append(f"📎 {attention['pending_suggestions']} document(s) waiting for you to confirm or reject a suggested activity")
    if attention["documents_needing_review"]:
        notes.append(f"⚠️ {attention['documents_needing_review']} document(s) need review or failed processing")
    if notes:
        st.warning("  \n".join(notes))

    # ---- key numbers
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Activities", overview["total_activities"])
    c2.metric("Active", overview["active_activities"])
    c3.metric("Open tasks", overview["pending_tasks"])
    c4.metric("Overdue tasks", overview["overdue_tasks"])
    c5.metric("Completed tasks", overview["completed_tasks"])

    if overview["total_activities"] == 0:
        ui.empty_state("🗂️", "No activities yet", "Open the Activities page and create your first activity to get started.")
        return

    # ---- deadlines and priority tasks
    left, right = st.columns(2)
    with left:
        st.subheader("⏰ Upcoming deadlines")
        deadlines = data["upcoming_deadlines"]
        if not deadlines:
            st.caption("No upcoming deadlines.")
        for d in deadlines:
            kind = "Task" if d["kind"] == "task" else "Activity"
            with st.container(border=True):
                st.markdown(f"**{d['title']}**")
                st.caption(f"{kind} · {d['activity_title']} · {fmt.format_date(d['due_date'])} ({fmt.days_left_text(d['days_left'])})")
    with right:
        st.subheader("🔥 High-priority tasks")
        tasks = data["high_priority_tasks"]
        if not tasks:
            st.caption("No high-priority open tasks.")
        for t in tasks:
            with st.container(border=True):
                st.markdown(f"**{t['title']}**  \n{fmt.level_label(t['level'])} · score {t['score']:.1f}/100")
                st.caption(f"{t['activity_title']} · due {fmt.format_date(t['due_date'])}")
                with st.expander("Why this priority?"):
                    st.write(t["explanation"])

    # ---- charts
    st.subheader("📈 Overview")
    ch1, ch2, ch3 = st.columns(3)
    with ch1:
        st.markdown("**Open tasks by priority**")
        by_priority = overview["open_tasks_by_priority"]
        order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        if sum(by_priority.get(k, 0) for k in order) == 0:
            st.caption("No open tasks.")
        else:
            st.bar_chart(pd.DataFrame({"Tasks": [by_priority.get(k, 0) for k in order]}, index=[fmt.nice(k) for k in order]))
    with ch2:
        st.markdown("**Activities by status**")
        by_status = overview["activities_by_status"]
        if not by_status:
            st.caption("No activities.")
        else:
            st.bar_chart(pd.DataFrame({"Activities": list(by_status.values())}, index=[fmt.nice(k) for k in by_status]))
    with ch3:
        expenses = data["expenses"]
        st.markdown(f"**Expenses** · total {fmt.format_money(expenses['total'])}")
        if not expenses["by_category"]:
            st.caption("No expenses recorded.")
        else:
            st.bar_chart(pd.DataFrame(
                {"₹": [fmt.to_number(i["total"]) for i in expenses["by_category"]]},
                index=[i["label"] for i in expenses["by_category"]],
            ))

    # ---- recent items
    r1, r2, r3 = st.columns(3)
    with r1:
        st.subheader("📄 Recent documents")
        docs = data["recent_documents"]
        if not docs:
            st.caption("No documents uploaded yet.")
        for doc in docs:
            st.markdown(f"**{doc['original_filename']}**  \n{fmt.nice(doc['processing_status'])} · {fmt.format_datetime(doc['created_at'])}")
    with r2:
        st.subheader("🕘 Recent activity")
        events = data["recent_activity"]
        if not events:
            st.caption("Nothing has happened yet.")
        for ev in events:
            st.markdown(f"**{fmt.nice(ev['action'])}** · {ev['activity_title']}")
            st.caption(f"{fmt.short(ev.get('details'), 90)}  \n{fmt.format_datetime(ev['created_at'])}")
    with r3:
        st.subheader("🔔 Upcoming reminders")
        reminders = data["upcoming_reminders"]
        if not reminders:
            st.caption("No upcoming reminders.")
        for rem in reminders:
            st.markdown(f"**{rem['title']}**")
            st.caption(f"{rem['activity_title']} · {fmt.format_datetime(rem['remind_at'])}")
