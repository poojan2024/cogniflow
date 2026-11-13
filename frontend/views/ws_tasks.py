"""Tasks tab of the activity workspace.

Every task comes from the backend together with its calculated priority (score, level, explanation and the four
weighted factors). This page only DISPLAYS that result and lets the user set or clear a manual override; the
score itself is always calculated by the backend algorithm (backend/app/services/priority.py), never here.
"""
from typing import Optional

import streamlit as st

import api_client as api
import formatting as fmt
import ui

ALL = "All"
AUTO = "Automatic (calculated)"
SORTS = {"Most urgent first": "priority", "Due date": "due"}


def _override_label(value: str) -> str:
    return value if value == AUTO else fmt.nice(value)


def _task_form(key: str, activity_id: int, task: Optional[dict] = None) -> None:
    """The same form creates (task=None) and edits a task."""
    t = task or {}
    editing = task is not None
    with st.form(key, clear_on_submit=not editing):
        title = st.text_input("Task title *", value=t.get("title", ""), max_chars=200, key=f"{key}_title")
        description = st.text_area("Description", value=t.get("description") or "", max_chars=5000, height=80,
                                   key=f"{key}_desc")
        c1, c2, c3 = st.columns(3)
        due = c1.date_input("Due date", value=fmt.parse_date(t.get("due_date")), format="DD/MM/YYYY", key=f"{key}_due")
        importance = c2.slider("Importance (1 = low, 5 = high)", 1, 5, int(t.get("importance", 3)), key=f"{key}_imp")
        status = c3.selectbox("Status", fmt.TASK_STATUSES, format_func=fmt.nice, key=f"{key}_status",
                              index=fmt.TASK_STATUSES.index(t.get("status", "PENDING")))
        override = AUTO
        if not editing:
            override = st.selectbox(
                "Priority override", [AUTO] + fmt.PRIORITY_LEVELS, format_func=_override_label, key=f"{key}_ovr",
                help="Leave on Automatic to let Cogniflow calculate the priority. You can change this later.")
        b1, b2 = st.columns(2)
        saved = b1.form_submit_button("Save changes" if editing else "Add task", type="primary")
        cancelled = b2.form_submit_button("Cancel") if editing else False

    if cancelled:
        st.session_state.pop("ws_editing_task", None)
        st.rerun()
    if not saved:
        return
    if not title.strip():
        st.error("Please enter a task title.")
        return
    payload = {"title": title.strip(), "description": description.strip() or None, "due_date": due,
               "importance": importance, "status": status}
    if editing:
        ok, _ = ui.attempt(api.update_task, activity_id, t["id"], payload)
        message = "Task updated."
    else:
        payload["manual_priority"] = None if override == AUTO else override
        ok, _ = ui.attempt(api.create_task, activity_id, payload)
        message = "Task added."
    if ok:
        st.session_state.pop("ws_editing_task", None)
        ui.flash_ok(message)
        st.rerun()


def _breakdown(activity_id: int, t: dict) -> None:
    """Score breakdown (how the number was calculated) and the manual override control."""
    p = t["priority"]
    with st.expander("Score breakdown & manual override"):
        if not p["is_active"]:
            st.write(p["explanation"])
            return

        formula = " + ".join(f"{f['weight']:.2f} × {f['name'].lower()}" for f in p["factors"])
        st.caption(f"Score (0–100) = 100 × ({formula}). Each factor is first scaled to 0–1.")
        for f in p["factors"]:
            name_col, bar_col, pts_col = st.columns([3, 3, 3])
            name_col.markdown(f"**{f['name']}**  \n{f['detail']}")
            bar_col.progress(min(1.0, max(0.0, float(f["normalized"]))))
            pts_col.markdown(f"{f['normalized']:.2f} × {f['weight']:.2f} → **{f['points']:.1f} points**")
        st.markdown(f"**Total: {p['score']:.1f} / 100 → calculated level: {fmt.nice(p['calculated_level'])}**")
        st.caption(f"Levels: {fmt.thresholds_text()}. These weights are design choices, not scientifically proven.")
        st.write(p["explanation"])

        st.divider()
        current = t.get("manual_priority")
        options = [AUTO] + fmt.PRIORITY_LEVELS
        choice = st.selectbox(
            "Priority override", options, index=options.index(current) if current in fmt.PRIORITY_LEVELS else 0,
            format_func=_override_label, key=f"ovr_{t['id']}",
            help="Overrides only the shown level. The calculated score stays visible above.")
        o1, o2 = st.columns(2)
        if o1.button("Apply override", key=f"ovr_apply_{t['id']}"):
            new_value = None if choice == AUTO else choice
            if new_value == current:
                st.info("Nothing to change.")
            else:
                ok, _ = ui.attempt(api.update_task, activity_id, t["id"], {"manual_priority": new_value})
                if ok:
                    ui.flash_ok("Priority override cleared." if new_value is None else f"Priority set to {fmt.nice(new_value)} manually.")
                    st.rerun()
        if current and o2.button("Reset to calculated", key=f"ovr_reset_{t['id']}"):
            ok, _ = ui.attempt(api.update_task, activity_id, t["id"], {"manual_priority": None})
            if ok:
                ui.flash_ok("Priority override cleared.")
                st.rerun()


def _task_card(activity_id: int, t: dict) -> None:
    p = t["priority"]
    task_id = t["id"]
    done = t["status"] == "COMPLETED"
    with st.container(border=True):
        st.markdown(f"~~{t['title']}~~" if done else f"**{t['title']}**")

        if p["is_active"]:
            tag = " · set manually" if p["is_overridden"] else ""
            head = f"{fmt.level_label(p['level'])}{tag} · score {p['score']:.1f}/100"
        else:
            head = ":gray[Completed]"
        days = fmt.days_until(t.get("due_date"))
        due = f"Due {fmt.format_date(t['due_date'])}" + (f" ({fmt.days_left_text(days)})" if days is not None and not done else "") \
            if t.get("due_date") else "No due date"
        st.markdown(f"{head} · {fmt.nice(t['status'])} · Importance {t['importance']}/5 · {due}")
        st.caption(p["explanation"])
        if t.get("description"):
            st.write(fmt.short(t["description"], 240))

        if st.session_state.get("ws_confirm_task") == task_id:  # full-width "are you sure?"
            ui.delete_controls("task", task_id, api.delete_task, (activity_id, task_id),
                               "Delete this task? Reminders linked to it are deleted too. This cannot be undone.",
                               "Task deleted.")
            return

        a1, a2, a3, a4 = st.columns([2, 2, 1, 2])
        if done:
            if a1.button("↩ Reopen", key=f"task_reopen_{task_id}"):
                ok, _ = ui.attempt(api.update_task, activity_id, task_id, {"status": "PENDING"})
                if ok:
                    ui.flash_ok("Task reopened.")
                    st.rerun()
        else:
            if a1.button("✔ Mark complete", key=f"task_done_{task_id}"):
                ok, _ = ui.attempt(api.update_task, activity_id, task_id, {"status": "COMPLETED"})
                if ok:
                    ui.flash_ok("Task completed.")
                    st.rerun()
            if t["status"] == "PENDING" and a2.button("▶ Start", key=f"task_start_{task_id}"):
                ok, _ = ui.attempt(api.update_task, activity_id, task_id, {"status": "IN_PROGRESS"})
                if ok:
                    ui.flash_ok("Task started.")
                    st.rerun()
        if a3.button("✏️ Edit", key=f"task_edit_{task_id}"):
            st.session_state["ws_editing_task"] = task_id
            st.rerun()
        with a4:
            ui.delete_controls("task", task_id, api.delete_task, (activity_id, task_id),
                               "Delete this task? Reminders linked to it are deleted too. This cannot be undone.",
                               "Task deleted.")
        _breakdown(activity_id, t)


def render(activity_id: int) -> None:
    with st.expander("➕ Add a task"):
        _task_form("ws_new_task_form", activity_id)

    f1, f2, f3 = st.columns(3)
    status_choice = f1.selectbox("Status", [ALL] + fmt.TASK_STATUSES, format_func=lambda v: v if v == ALL else fmt.nice(v),
                                 key="ws_tk_status")
    level_choice = f2.selectbox("Priority", [ALL] + fmt.PRIORITY_LEVELS, format_func=lambda v: v if v == ALL else fmt.nice(v),
                                key="ws_tk_level", help="Only open (not completed) tasks have a priority level.")
    sort_label = f3.selectbox("Sort by", list(SORTS), key="ws_tk_sort")

    with st.spinner("Loading tasks…"):
        tasks = ui.call(api.list_tasks, activity_id,
                        status_filter=None if status_choice == ALL else status_choice,
                        priority_level=None if level_choice == ALL else level_choice,
                        sort=SORTS[sort_label])
    if tasks is None:
        return

    if not tasks:
        if status_choice != ALL or level_choice != ALL:
            ui.empty_state("🔍", "No tasks match these filters", "Change or clear the filters above.")
        else:
            ui.empty_state("✅", "No tasks yet", "Open “Add a task” above. Cogniflow calculates a priority for every task.")
        return

    open_tasks = [t for t in tasks if t["priority"]["is_active"]]
    overdue = [t for t in open_tasks if (fmt.days_until(t.get("due_date")) or 0) < 0 and t.get("due_date")]
    m1, m2, m3 = st.columns(3)
    m1.metric("Shown", len(tasks))
    m2.metric("Open", len(open_tasks))
    m3.metric("Overdue", len(overdue))

    editing_id = st.session_state.get("ws_editing_task")
    for t in tasks:
        if editing_id == t["id"]:
            with st.container(border=True):
                st.markdown(f"#### Editing: {t['title']}")
                _task_form(f"ws_edit_task_form_{t['id']}", activity_id, t)
        else:
            _task_card(activity_id, t)
