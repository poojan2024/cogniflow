"""Tests for the activity workspace (Tasks, Notes, Expenses, Reminders) using the Streamlit stand-in."""
import importlib.util
import os
import sys
import unittest
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import st_stub  # noqa: E402

st = st_stub.install()

import api_client as api  # noqa: E402
import formatting as fmt  # noqa: E402
from views import activities, workspace, ws_expenses, ws_notes, ws_reminders, ws_tasks  # noqa: E402

AID = 1
PRIORITY_PY = os.path.join(HERE, "..", "..", "backend", "app", "services", "priority.py")


def load_backend_priority():
    spec = importlib.util.spec_from_file_location("backend_priority", PRIORITY_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend_priority"] = module
    spec.loader.exec_module(module)
    return module


def prio(level="HIGH", score=70.0, overridden=False, active=True, calculated=None):
    factors = [] if not active else [
        {"name": "Deadline urgency", "detail": "due in 3 days", "normalized": 0.79, "weight": 0.40, "points": 31.4},
        {"name": "Task importance", "detail": "4/5", "normalized": 0.75, "weight": 0.30, "points": 22.5},
        {"name": "Activity priority", "detail": "3/5", "normalized": 0.5, "weight": 0.15, "points": 7.5},
        {"name": "Overdue / status", "detail": "not started", "normalized": 0.5, "weight": 0.15, "points": 7.5},
    ]
    return {"score": score if active else 0.0, "level": level, "calculated_level": calculated or level,
            "is_overridden": overridden, "is_active": active, "explanation": f"{level.capitalize()} priority because...",
            "factors": factors}


def task(i=5, **over):
    base = {"id": i, "activity_id": AID, "title": f"Task {i}", "description": None, "due_date": "2026-10-20",
            "importance": 4, "status": "PENDING", "manual_priority": None, "completed_at": None,
            "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z", "priority": prio()}
    base.update(over)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        st.reset()
        st.session_state["token"] = "TOKEN"

    def errors(self):
        return [str(c) for c in st.called("error")]


# ============================================================ formatting helpers
class HelperTests(unittest.TestCase):
    def test_local_iso_carries_a_timezone_offset(self):
        iso = fmt.local_iso(date(2026, 10, 15), time(9, 30, 45))
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.utcoffset())          # the backend rejects times without an offset
        self.assertEqual((parsed.hour, parsed.minute, parsed.second), (9, 30, 0))

    def test_to_local_roundtrip(self):
        iso = fmt.local_iso(date(2026, 10, 15), time(9, 30))
        back = fmt.to_local(iso)
        self.assertEqual((back.date(), back.time().replace(tzinfo=None)), (date(2026, 10, 15), time(9, 30)))
        self.assertIsNone(fmt.to_local(None))
        self.assertIsNone(fmt.to_local("garbage"))

    def test_days_until(self):
        today = date(2026, 10, 14)
        self.assertEqual(fmt.days_until("2026-10-16", today), 2)
        self.assertEqual(fmt.days_until("2026-10-10", today), -4)
        self.assertIsNone(fmt.days_until(None, today))

    def test_is_past(self):
        self.assertTrue(fmt.is_past(date(2020, 1, 1), time(9, 0)))
        self.assertFalse(fmt.is_past(date.today() + timedelta(days=30), time(9, 0)))

    def test_thresholds_text(self):
        self.assertEqual(fmt.thresholds_text(), "Critical from 80, High from 60, Medium from 35, otherwise Low")


@unittest.skipUnless(os.path.isfile(PRIORITY_PY), "backend/app/services/priority.py not found next to the frontend folder")
class BackendContractTests(Base):
    """The screen must explain the SAME rules the backend applies, and must cope with the backend's real output."""

    def test_levels_and_thresholds_match_backend(self):
        backend = load_backend_priority()
        self.assertEqual(list(backend.LEVELS), fmt.PRIORITY_LEVELS)
        self.assertEqual(tuple((lvl, int(m)) for lvl, m in backend.LEVEL_THRESHOLDS), fmt.LEVEL_THRESHOLDS)

    def test_screen_renders_real_algorithm_output_for_the_four_demo_cases(self):
        backend = load_backend_priority()
        today = date(2026, 10, 14)
        cases = {
            "far deadline, low importance": dict(due_date=today + timedelta(30), importance=1, status="PENDING", activity_priority=2),
            "approaching, high importance": dict(due_date=today + timedelta(3), importance=4, status="PENDING", activity_priority=3),
            "overdue, high importance": dict(due_date=today - timedelta(2), importance=5, status="PENDING", activity_priority=5),
            "completed": dict(due_date=today - timedelta(2), importance=5, status="COMPLETED", activity_priority=5),
        }
        for i, (name, kw) in enumerate(cases.items(), start=1):
            result = backend.calculate_priority(today=today, **kw)
            payload = {**asdict(result), "factors": [asdict(f) for f in result.factors]}  # same conversion the router does
            t = task(i, title=name, status=kw["status"], priority=payload, due_date=kw["due_date"].isoformat())
            st.reset(); st.session_state["token"] = "T"
            with mock.patch.object(api, "list_tasks", return_value=[t]):
                ws_tasks.render(AID)                      # must not raise
            bars = len(st.called("progress"))
            self.assertEqual(bars, 4 if result.is_active else 0, name)
            self.assertFalse(st.called("error"), name)
            self.assertTrue(any(f"{result.score:.1f}" in str(c) for c in st.calls) or not result.is_active, name)


# ================================================================== tasks tab
class TasksTests(Base):
    def render(self, tasks, **patch):
        with mock.patch.object(api, "list_tasks", return_value=tasks) as m:
            ws_tasks.render(AID)
        return m

    def test_lists_tasks_sorted_by_priority_by_default(self):
        m = self.render([task(1), task(2)])
        self.assertEqual(m.call_args.args, ("TOKEN", AID))
        self.assertEqual(m.call_args.kwargs, {"status_filter": None, "priority_level": None, "sort": "priority"})
        self.assertEqual(len(st.called("progress")), 8)   # 4 factor bars per open task
        self.assertEqual(st.metrics["Open"], 2)

    def test_filters_are_sent_to_the_backend(self):
        st.inputs.update({"Status": "PENDING", "Priority": "HIGH", "Sort by": "Due date"})
        m = self.render([task()])
        self.assertEqual(m.call_args.kwargs, {"status_filter": "PENDING", "priority_level": "HIGH", "sort": "due"})

    def test_empty_states(self):
        self.render([])
        self.assertTrue(any("No tasks yet" in str(c) for c in st.calls))
        st.reset(); st.session_state["token"] = "T"; st.inputs["Status"] = "COMPLETED"
        self.render([])
        self.assertTrue(any("No tasks match" in str(c) for c in st.calls))

    def test_completed_task_has_no_score_bars(self):
        self.render([task(7, status="COMPLETED", priority=prio(active=False, level="LOW"))])
        self.assertEqual(len(st.called("progress")), 0)
        self.assertTrue(any("Completed" in str(c) for c in st.calls))

    def test_overdue_metric_counts_only_open_overdue_tasks(self):
        past = (date.today() - timedelta(days=3)).isoformat()
        self.render([task(1, due_date=past), task(2, due_date=past, status="COMPLETED", priority=prio(active=False)),
                     task(3, due_date=None)])
        self.assertEqual(st.metrics["Overdue"], 1)

    def test_manual_override_is_labelled(self):
        self.render([task(1, manual_priority="CRITICAL", priority=prio("CRITICAL", 40.0, overridden=True, calculated="MEDIUM"))])
        self.assertTrue(any("set manually" in str(c) for c in st.calls))

    # ---- create
    def test_create_requires_a_title(self):
        st.pressed.add("Add task")
        with mock.patch.object(api, "create_task") as create:
            self.render([])
        create.assert_not_called()
        self.assertTrue(any("task title" in e for e in self.errors()))

    def test_create_task_payload_defaults_to_automatic_priority(self):
        st.pressed.add("Add task")
        st.inputs["Task title *"] = "  Write chapter 3 "
        with mock.patch.object(api, "create_task", return_value=task()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([])
        payload = create.call_args.args[2]
        self.assertEqual(create.call_args.args[:2], ("TOKEN", AID))
        self.assertEqual(payload["title"], "Write chapter 3")
        self.assertEqual(payload["importance"], 3)
        self.assertEqual(payload["status"], "PENDING")
        self.assertIsNone(payload["manual_priority"])
        self.assertEqual(st.session_state["flash_ok"], "Task added.")

    def test_create_task_with_manual_priority(self):
        st.pressed.add("Add task")
        st.inputs.update({"Task title *": "X", "Priority override": "HIGH"})
        with mock.patch.object(api, "create_task", return_value=task()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([])
        self.assertEqual(create.call_args.args[2]["manual_priority"], "HIGH")

    def test_create_server_error_shown_without_rerun(self):
        st.pressed.add("Add task")
        st.inputs["Task title *"] = "X"
        with mock.patch.object(api, "create_task", side_effect=api.ApiError("Invalid input.", 422)):
            self.render([])
        self.assertTrue(self.errors())
        self.assertNotIn("flash_ok", st.session_state)

    # ---- status buttons
    def test_mark_complete(self):
        st.pressed.add("task_done_5")
        with mock.patch.object(api, "update_task", return_value=task()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5)])
        self.assertEqual(upd.call_args.args, ("TOKEN", AID, 5, {"status": "COMPLETED"}))

    def test_reopen_and_start(self):
        st.pressed.add("task_reopen_5")
        with mock.patch.object(api, "update_task", return_value=task()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5, status="COMPLETED", priority=prio(active=False))])
        self.assertEqual(upd.call_args.args[3], {"status": "PENDING"})
        st.reset(); st.session_state["token"] = "T"; st.pressed.add("task_start_5")
        with mock.patch.object(api, "update_task", return_value=task()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5)])
        self.assertEqual(upd.call_args.args[3], {"status": "IN_PROGRESS"})

    # ---- manual override
    def test_apply_manual_override(self):
        st.pressed.add("ovr_apply_5")
        st.inputs["Priority override"] = "CRITICAL"
        with mock.patch.object(api, "update_task", return_value=task()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5)])
        self.assertEqual(upd.call_args.args, ("TOKEN", AID, 5, {"manual_priority": "CRITICAL"}))
        self.assertIn("Critical", st.session_state["flash_ok"])

    def test_choosing_automatic_clears_the_override(self):
        st.pressed.add("ovr_apply_5")
        st.inputs["Priority override"] = ws_tasks.AUTO
        with mock.patch.object(api, "update_task", return_value=task()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5, manual_priority="HIGH", priority=prio("HIGH", 30, overridden=True, calculated="LOW"))])
        self.assertEqual(upd.call_args.args[3], {"manual_priority": None})

    def test_unchanged_override_makes_no_api_call(self):
        st.pressed.add("ovr_apply_5")
        st.inputs["Priority override"] = ws_tasks.AUTO
        with mock.patch.object(api, "update_task") as upd:
            self.render([task(5)])
        upd.assert_not_called()

    def test_reset_to_calculated(self):
        st.pressed.add("ovr_reset_5")
        with mock.patch.object(api, "update_task", return_value=task()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5, manual_priority="HIGH", priority=prio("HIGH", 30, overridden=True, calculated="LOW"))])
        self.assertEqual(upd.call_args.args[3], {"manual_priority": None})

    def test_reset_button_only_exists_when_overridden(self):
        st.pressed.add("ovr_reset_5")
        with mock.patch.object(api, "update_task") as upd:
            self.render([task(5)])  # no override -> no reset button, so pressing it does nothing
        upd.assert_not_called()

    # ---- edit / delete
    def test_edit_saves_without_touching_the_override(self):
        st.session_state["ws_editing_task"] = 5
        st.pressed.add("Save changes")
        st.inputs["Task title *"] = "Renamed"
        with mock.patch.object(api, "update_task", return_value=task()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5, manual_priority="HIGH", priority=prio("HIGH", 30, overridden=True, calculated="LOW"))])
        payload = upd.call_args.args[3]
        self.assertEqual(payload["title"], "Renamed")
        self.assertNotIn("manual_priority", payload)   # an edit must never silently drop the user's override
        self.assertNotIn("ws_editing_task", st.session_state)

    def test_delete_asks_first_then_deletes(self):
        st.pressed.add("task_del_5")
        with mock.patch.object(api, "delete_task") as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5)])
        delete.assert_not_called()
        self.assertEqual(st.session_state["ws_confirm_task"], 5)

        st.pressed.clear(); st.pressed.add("task_yes_5")
        with mock.patch.object(api, "delete_task", return_value=None) as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([task(5)])
        delete.assert_called_once_with("TOKEN", AID, 5)
        self.assertEqual(st.session_state["flash_ok"], "Task deleted.")

    def test_delete_failure_keeps_confirmation(self):
        st.session_state["ws_confirm_task"] = 5
        st.pressed.add("task_yes_5")
        with mock.patch.object(api, "delete_task", side_effect=api.ApiError("Task not found.", 404)):
            self.render([task(5)])
        self.assertTrue(self.errors())
        self.assertNotIn("flash_ok", st.session_state)

    def test_backend_error_loading_tasks_is_shown(self):
        with mock.patch.object(api, "list_tasks", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            ws_tasks.render(AID)
        self.assertTrue(self.errors())


# ================================================================== notes tab
def note(i=3, **over):
    base = {"id": i, "activity_id": AID, "title": f"Note {i}", "content": "hello **world**",
            "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z"}
    base.update(over)
    return base


class NotesTests(Base):
    def render(self, notes):
        with mock.patch.object(api, "list_notes", return_value=notes) as m:
            ws_notes.render(AID)
        return m

    def test_list_and_search_term_is_sent(self):
        st.inputs["Search notes"] = "viva"
        m = self.render([note(1), note(2)])
        self.assertEqual(m.call_args.args, ("TOKEN", AID))
        self.assertEqual(m.call_args.kwargs, {"q": "viva"})

    def test_empty_states(self):
        self.render([])
        self.assertTrue(any("No notes yet" in str(c) for c in st.calls))
        st.reset(); st.session_state["token"] = "T"; st.inputs["Search notes"] = "zzz"
        self.render([])
        self.assertTrue(any("No matching notes" in str(c) for c in st.calls))

    def test_create_requires_title(self):
        st.pressed.add("Add note")
        with mock.patch.object(api, "create_note") as create:
            self.render([])
        create.assert_not_called()
        self.assertTrue(self.errors())

    def test_create_note(self):
        st.pressed.add("Add note")
        st.inputs.update({"Note title *": " Ideas ", "Content": "line1\nline2"})
        with mock.patch.object(api, "create_note", return_value=note()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([])
        self.assertEqual(create.call_args.args, ("TOKEN", AID, {"title": "Ideas", "content": "line1\nline2"}))

    def test_edit_note(self):
        st.session_state["ws_editing_note"] = 3
        st.pressed.add("Save changes")
        st.inputs["Note title *"] = "New title"
        with mock.patch.object(api, "update_note", return_value=note()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([note(3)])
        self.assertEqual(upd.call_args.args[:3], ("TOKEN", AID, 3))
        self.assertEqual(upd.call_args.args[3]["title"], "New title")

    def test_delete_note_needs_confirmation(self):
        st.pressed.add("note_del_3")
        with mock.patch.object(api, "delete_note") as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([note(3)])
        delete.assert_not_called()
        st.pressed.clear(); st.pressed.add("note_yes_3")
        with mock.patch.object(api, "delete_note", return_value=None) as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([note(3)])
        delete.assert_called_once_with("TOKEN", AID, 3)


# ============================================================== expenses tab
def expense(i=9, **over):
    base = {"id": i, "activity_id": AID, "description": f"Expense {i}", "category": "Food", "amount": "800.00",
            "expense_date": "2026-10-10", "created_at": "2026-10-10T00:00:00Z"}
    base.update(over)
    return base


def expense_list(items, total):
    return {"items": items, "count": len(items), "total_amount": total}


class ExpensesTests(Base):
    def render(self, data):
        with mock.patch.object(api, "list_expenses", return_value=data) as m:
            ws_expenses.render(AID)
        return m

    def test_total_comes_from_the_backend_and_is_shown_in_rupees(self):
        items = [expense(1, category="Accommodation", amount="3000.00"), expense(2, category="Transport", amount="1200.00"),
                 expense(3, category="Food", amount="800.00")]
        self.render(expense_list(items, "5000.00"))
        self.assertEqual(st.metrics["Total for this activity"], "₹5,000.00")
        self.assertEqual(st.metrics["Expenses recorded"], 3)
        self.assertTrue(st.called("bar_chart"))

    def test_empty_state(self):
        self.render(expense_list([], "0.00"))
        self.assertTrue(any("No expenses yet" in str(c) for c in st.calls))

    def test_category_totals_use_exact_decimals(self):
        from decimal import Decimal
        totals = ws_expenses._category_totals([expense(1, amount="0.10"), expense(2, amount="0.20"), expense(3, category=None, amount="1.00")])
        self.assertEqual(totals["Food"], Decimal("0.30"))      # float arithmetic would give 0.30000000000000004
        self.assertEqual(totals["Uncategorised"], Decimal("1.00"))

    def test_money_text_is_exact(self):
        self.assertEqual(ws_expenses._money_text(0.1 + 0.2), "0.30")
        self.assertEqual(ws_expenses._money_text(1200.5), "1200.50")
        self.assertEqual(ws_expenses._money_text(3000), "3000.00")

    def test_add_expense_payload(self):
        st.pressed.add("Add expense")
        st.inputs.update({"Description *": " Hotel ", "Amount (₹) *": 3000.0, "Category": "Accommodation",
                          "Date": date(2026, 10, 10)})
        with mock.patch.object(api, "create_expense", return_value=expense()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(expense_list([], "0.00"))
        self.assertEqual(create.call_args.args, ("TOKEN", AID, {
            "description": "Hotel", "category": "Accommodation", "amount": "3000.00", "expense_date": date(2026, 10, 10)}))

    def test_custom_category_overrides_the_list_and_none_means_no_category(self):
        st.pressed.add("Add expense")
        st.inputs.update({"Description *": "Visa", "Category": "Food", "Or type your own category": "Paperwork"})
        with mock.patch.object(api, "create_expense", return_value=expense()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(expense_list([], "0.00"))
        self.assertEqual(create.call_args.args[2]["category"], "Paperwork")
        st.reset(); st.session_state["token"] = "T"; st.pressed.add("Add expense")
        st.inputs.update({"Description *": "Misc", "Category": ws_expenses.NO_CATEGORY})
        with mock.patch.object(api, "create_expense", return_value=expense()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(expense_list([], "0.00"))
        self.assertIsNone(create.call_args.args[2]["category"])

    def test_add_requires_description(self):
        st.pressed.add("Add expense")
        with mock.patch.object(api, "create_expense") as create:
            self.render(expense_list([], "0.00"))
        create.assert_not_called()
        self.assertTrue(self.errors())

    def test_edit_expense(self):
        st.session_state["ws_editing_expense"] = 9
        st.pressed.add("Save changes")
        st.inputs["Amount (₹) *"] = 950.25
        with mock.patch.object(api, "update_expense", return_value=expense()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(expense_list([expense(9)], "800.00"))
        self.assertEqual(upd.call_args.args[:3], ("TOKEN", AID, 9))
        self.assertEqual(upd.call_args.args[3]["amount"], "950.25")

    def test_delete_expense_needs_confirmation(self):
        st.pressed.add("expense_del_9")
        with mock.patch.object(api, "delete_expense") as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(expense_list([expense(9)], "800.00"))
        delete.assert_not_called()
        st.pressed.clear(); st.pressed.add("expense_yes_9")
        with mock.patch.object(api, "delete_expense", return_value=None) as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(expense_list([expense(9)], "800.00"))
        delete.assert_called_once_with("TOKEN", AID, 9)


# ============================================================= reminders tab
def reminder(i=4, **over):
    base = {"id": i, "activity_id": AID, "task_id": None, "title": f"Reminder {i}", "remind_at": "2036-10-15T04:00:00Z",
            "is_triggered": False, "created_at": "2026-10-01T00:00:00Z"}
    base.update(over)
    return base


class RemindersTests(Base):
    def render(self, reminders, tasks=None):
        with mock.patch.object(api, "list_reminders", return_value=reminders), \
             mock.patch.object(api, "list_tasks", return_value=tasks or []):
            ws_reminders.render(AID)

    def test_groups_scheduled_and_triggered(self):
        self.render([reminder(1), reminder(2, is_triggered=True)])
        headings = [c[1][0] for c in st.called("subheader")]
        self.assertEqual(headings, ["Scheduled (1)", "Already triggered (1)"])

    def test_empty_state(self):
        self.render([])
        self.assertTrue(any("No reminders yet" in str(c) for c in st.calls))

    def test_create_sends_timezone_aware_time_and_task_link(self):
        st.pressed.add("Add reminder")
        st.inputs.update({"Reminder *": "Submit report", "Date": date(2036, 10, 15), "Time": time(9, 0),
                          "Linked task (optional)": 5})
        with mock.patch.object(api, "create_reminder", return_value=reminder()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([], tasks=[task(5)])
        payload = create.call_args.args[2]
        self.assertEqual(payload["title"], "Submit report")
        self.assertEqual(payload["task_id"], 5)
        parsed = datetime.fromisoformat(payload["remind_at"])
        self.assertIsNotNone(parsed.utcoffset())
        self.assertEqual((parsed.year, parsed.hour, parsed.minute), (2036, 9, 0))
        self.assertEqual(st.session_state["flash_ok"], "Reminder added.")

    def test_past_time_gets_an_explanation(self):
        st.pressed.add("Add reminder")
        st.inputs.update({"Reminder *": "Old", "Date": date(2020, 1, 1), "Time": time(9, 0)})
        with mock.patch.object(api, "create_reminder", return_value=reminder()):
            with self.assertRaises(st_stub.RerunRequested):
                self.render([])
        self.assertIn("already passed", st.session_state["flash_ok"])

    def test_create_requires_title(self):
        st.pressed.add("Add reminder")
        with mock.patch.object(api, "create_reminder") as create:
            self.render([])
        create.assert_not_called()
        self.assertTrue(self.errors())

    def test_reminders_still_work_if_the_task_list_cannot_be_loaded(self):
        with mock.patch.object(api, "list_reminders", return_value=[reminder(1)]), \
             mock.patch.object(api, "list_tasks", side_effect=api.ApiError("boom", 500)):
            ws_reminders.render(AID)
        self.assertTrue(any("Scheduled (1)" in str(c) for c in st.called("subheader")))

    def test_edit_and_unlink_task(self):
        st.session_state["ws_editing_reminder"] = 4
        st.pressed.add("Save changes")
        st.inputs["Linked task (optional)"] = None
        with mock.patch.object(api, "update_reminder", return_value=reminder()) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([reminder(4, task_id=5)], tasks=[task(5)])
        self.assertEqual(upd.call_args.args[:3], ("TOKEN", AID, 4))
        self.assertIsNone(upd.call_args.args[3]["task_id"])   # null unlinks the task

    def test_delete_reminder_needs_confirmation(self):
        st.pressed.add("reminder_del_4")
        with mock.patch.object(api, "delete_reminder") as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([reminder(4)])
        delete.assert_not_called()
        st.pressed.clear(); st.pressed.add("reminder_yes_4")
        with mock.patch.object(api, "delete_reminder", return_value=None) as delete:
            with self.assertRaises(st_stub.RerunRequested):
                self.render([reminder(4)])
        delete.assert_called_once_with("TOKEN", AID, 4)


# ================================================================ workspace
ACTIVITY = {"id": AID, "title": "MCA Final-Year Project", "description": "Cogniflow", "activity_type": "PROJECT",
            "status": "ACTIVE", "priority": 4, "start_date": "2026-09-01", "deadline": "2026-12-01",
            "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}


class WorkspaceTests(Base):
    def test_default_section_is_tasks(self):
        with mock.patch.object(api, "get_activity", return_value=ACTIVITY), \
             mock.patch.object(api, "list_tasks", return_value=[]) as tasks, \
             mock.patch.object(api, "list_notes") as notes:
            workspace.render(AID)
        tasks.assert_called_once()
        notes.assert_not_called()      # only the open section is loaded

    def test_each_section_loads_only_its_own_data(self):
        expectations = {
            "📝 Notes": ("list_notes", []),
            "💰 Expenses": ("list_expenses", expense_list([], "0.00")),
            "⏰ Reminders": ("list_reminders", []),
        }
        for label, (fn, value) in expectations.items():
            st.reset(); st.session_state["token"] = "T"; st.inputs["Section"] = label
            with mock.patch.object(api, "get_activity", return_value=ACTIVITY), \
                 mock.patch.object(api, "list_tasks", return_value=[]) as tasks, \
                 mock.patch.object(api, fn, return_value=value) as target:
                workspace.render(AID)
            target.assert_called_once()
            if label != "⏰ Reminders":   # reminders also read tasks, only to offer the optional link
                tasks.assert_not_called()

    def test_deleted_activity_returns_to_list(self):
        st.session_state["open_activity_id"] = AID
        with mock.patch.object(api, "get_activity", side_effect=api.ApiError("Activity not found.", 404)):
            with self.assertRaises(st_stub.RerunRequested):
                workspace.render(AID)
        self.assertNotIn("open_activity_id", st.session_state)

    def test_backend_down_keeps_workspace_and_shows_error(self):
        st.session_state["open_activity_id"] = AID
        with mock.patch.object(api, "get_activity", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            workspace.render(AID)
        self.assertTrue(self.errors())
        self.assertEqual(st.session_state["open_activity_id"], AID)

    def test_open_and_close_reset_workspace_state(self):
        st.session_state.update({"ws_section": "📝 Notes", "ws_editing_task": 3, "ws_confirm_note": 1, "act_page": 2})
        workspace.open_workspace(7)
        self.assertEqual(st.session_state["open_activity_id"], 7)
        self.assertNotIn("ws_section", st.session_state)
        self.assertNotIn("ws_editing_task", st.session_state)
        self.assertEqual(st.session_state["act_page"], 2)       # the Activities list keeps its own page
        workspace.close_workspace()
        self.assertNotIn("open_activity_id", st.session_state)

    def test_activities_page_opens_workspace_button(self):
        st.pressed.add("open_3")
        page = {"items": [dict(ACTIVITY, id=3)], "total": 1, "page": 1, "page_size": 10}
        with mock.patch.object(api, "list_activities", return_value=page):
            with self.assertRaises(st_stub.RerunRequested):
                activities.render()
        self.assertEqual(st.session_state["open_activity_id"], 3)

    def test_activities_page_shows_workspace_when_one_is_open(self):
        st.session_state["open_activity_id"] = AID
        with mock.patch.object(api, "get_activity", return_value=ACTIVITY) as get, \
             mock.patch.object(api, "list_tasks", return_value=[]), \
             mock.patch.object(api, "list_activities") as listing:
            activities.render()
        get.assert_called_once_with("TOKEN", AID)
        listing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
