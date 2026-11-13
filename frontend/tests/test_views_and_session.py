import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import st_stub  # noqa: E402

st = st_stub.install()

import api_client as api  # noqa: E402
import session  # noqa: E402
import ui  # noqa: E402
from views import activities, dashboard  # noqa: E402

DASH = {
    "today": "2026-10-14",
    "overview": {"total_activities": 3, "active_activities": 2, "activities_by_status": {"ACTIVE": 2, "COMPLETED": 1},
                 "pending_tasks": 4, "completed_tasks": 1, "overdue_tasks": 1,
                 "open_tasks_by_priority": {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 2, "LOW": 0}},
    "upcoming_deadlines": [{"kind": "task", "id": 1, "title": "Write chapter 3", "activity_id": 1,
                            "activity_title": "MCA Project", "due_date": "2026-10-16", "days_left": 2}],
    "high_priority_tasks": [{"id": 1, "title": "Write chapter 3", "activity_id": 1, "activity_title": "MCA Project",
                             "due_date": "2026-10-16", "level": "CRITICAL", "score": 91.5, "explanation": "Critical because..."}],
    "recent_documents": [{"id": 1, "original_filename": "notice.pdf", "processing_status": "PROCESSED",
                          "activity_id": None, "created_at": "2026-10-14T05:00:00Z"}],
    "recent_activity": [{"action": "TASK_CREATED", "entity_type": "task", "details": None, "activity_id": 1,
                         "activity_title": "MCA Project", "created_at": "2026-10-14T05:00:00Z"}],
    "upcoming_reminders": [{"id": 1, "title": "Submit", "remind_at": "2026-10-15T04:00:00Z",
                            "activity_id": 1, "activity_title": "MCA Project"}],
    "expenses": {"total": "5000.00", "by_category": [{"label": "Hotel", "total": "3000.00"}, {"label": "Food", "total": "2000.00"}],
                 "by_activity": [{"label": "Trip", "total": "5000.00"}]},
    "attention": {"unread_notifications": 2, "pending_suggestions": 1, "documents_needing_review": 0},
}
EMPTY_DASH = dict(DASH, overview={**DASH["overview"], "total_activities": 0, "active_activities": 0,
                                  "activities_by_status": {}, "pending_tasks": 0, "completed_tasks": 0, "overdue_tasks": 0,
                                  "open_tasks_by_priority": {}},
                  upcoming_deadlines=[], high_priority_tasks=[], recent_documents=[], recent_activity=[],
                  upcoming_reminders=[], expenses={"total": "0.00", "by_category": [], "by_activity": []},
                  attention={"unread_notifications": 0, "pending_suggestions": 0, "documents_needing_review": 0})


def activity(i=1, **over):
    base = {"id": i, "title": f"Activity {i}", "description": "desc", "activity_type": "PROJECT", "status": "ACTIVE",
            "priority": 4, "start_date": "2026-10-01", "deadline": "2026-12-01",
            "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z"}
    base.update(over)
    return base


def page(items, total=None):
    return {"items": items, "total": len(items) if total is None else total, "page": 1, "page_size": 10}


class Base(unittest.TestCase):
    def setUp(self):
        st.reset()
        st.session_state["token"] = "TOKEN"


class DashboardTests(Base):
    def test_renders_full_data(self):
        with mock.patch.object(api, "dashboard", return_value=DASH):
            dashboard.render()
        self.assertEqual(st.metrics["Activities"], 3)
        self.assertEqual(st.metrics["Overdue tasks"], 1)
        self.assertTrue(st.called("warning"))  # attention banner
        self.assertFalse(st.called("error"))

    def test_empty_account_shows_empty_state(self):
        with mock.patch.object(api, "dashboard", return_value=EMPTY_DASH):
            dashboard.render()
        self.assertTrue(any("No activities yet" in str(c) for c in st.calls))

    def test_backend_down_shows_message_not_crash(self):
        with mock.patch.object(api, "dashboard", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            dashboard.render()
        self.assertTrue(st.called("error"))

    def test_expired_token_logs_out(self):
        with mock.patch.object(api, "dashboard", side_effect=api.ApiError("expired", 401)):
            with self.assertRaises(st_stub.RerunRequested):
                dashboard.render()
        self.assertTrue(st.session_state["_do_logout"])
        self.assertIn("expired", st.session_state["flash"])


class ActivitiesTests(Base):
    def test_lists_activities(self):
        with mock.patch.object(api, "list_activities", return_value=page([activity(1), activity(2)])) as m:
            activities.render()
        self.assertEqual(m.call_args.args[0], "TOKEN")
        self.assertEqual(m.call_args.kwargs["page"], 1)
        self.assertIsNone(m.call_args.kwargs["activity_type"])
        self.assertIsNone(m.call_args.kwargs["status"])

    def test_filters_are_passed_to_api(self):
        st.inputs.update({"Type": "EXAM", "Status": "ON_HOLD", "Sort by": "Deadline", "Search": "viva"})
        with mock.patch.object(api, "list_activities", return_value=page([activity()])) as m:
            activities.render()
        k = m.call_args.kwargs
        self.assertEqual((k["activity_type"], k["status"], k["sort"], k["q"]), ("EXAM", "ON_HOLD", "deadline", "viva"))

    def test_empty_list_and_empty_search(self):
        with mock.patch.object(api, "list_activities", return_value=page([])):
            activities.render()
        self.assertTrue(any("No activities yet" in str(c) for c in st.calls))
        st.reset(); st.session_state["token"] = "T"; st.inputs["Search"] = "zzz"
        with mock.patch.object(api, "list_activities", return_value=page([])):
            activities.render()
        self.assertTrue(any("No matching activities" in str(c) for c in st.calls))

    def test_pager_appears_only_when_needed(self):
        with mock.patch.object(api, "list_activities", return_value=page([activity()], total=25)):
            activities.render()
        self.assertTrue(any(c[0] == "number_input" and "1–3" in c[1][0] for c in st.calls))

    def test_page_beyond_last_is_clamped(self):
        st.session_state["act_page"] = 5
        with mock.patch.object(api, "list_activities", return_value=page([], total=3)):
            with self.assertRaises(st_stub.RerunRequested):
                activities.render()
        self.assertEqual(st.session_state["act_page"], 1)

    def test_create_requires_title(self):
        st.pressed.add("Create activity")
        with mock.patch.object(api, "list_activities", return_value=page([])), \
             mock.patch.object(api, "create_activity") as create:
            activities.render()
        create.assert_not_called()
        self.assertTrue(any("enter a title" in str(c) for c in st.called("error")))

    def test_create_rejects_deadline_before_start(self):
        from datetime import date
        st.pressed.add("Create activity")
        st.inputs.update({"Title *": "X", "Start date": date(2026, 11, 1), "Deadline": date(2026, 10, 1)})
        with mock.patch.object(api, "list_activities", return_value=page([])), \
             mock.patch.object(api, "create_activity") as create:
            activities.render()
        create.assert_not_called()
        self.assertTrue(any("before the start date" in str(c) for c in st.called("error")))

    def test_create_success_calls_api_and_reruns(self):
        st.pressed.add("Create activity")
        st.inputs["Title *"] = "  Exam prep  "
        with mock.patch.object(api, "list_activities", return_value=page([])), \
             mock.patch.object(api, "create_activity", return_value=activity()) as create:
            with self.assertRaises(st_stub.RerunRequested):
                activities.render()
        payload = create.call_args.args[1]
        self.assertEqual(payload["title"], "Exam prep")
        self.assertEqual(payload["activity_type"], "CUSTOM")
        self.assertEqual(payload["priority"], 3)
        self.assertEqual(st.session_state["flash_ok"], "Activity created.")

    def test_create_server_error_is_shown_and_no_rerun(self):
        st.pressed.add("Create activity")
        st.inputs["Title *"] = "X"
        with mock.patch.object(api, "list_activities", return_value=page([])), \
             mock.patch.object(api, "create_activity", side_effect=api.ApiError("Invalid input.", 422)):
            activities.render()  # must not raise
        self.assertTrue(st.called("error"))
        self.assertNotIn("flash_ok", st.session_state)

    def test_edit_mode_shows_form_and_saves(self):
        st.session_state["editing_id"] = 7
        st.pressed.add("Save changes")
        with mock.patch.object(api, "list_activities", return_value=page([activity(7)])), \
             mock.patch.object(api, "update_activity", return_value=activity(7)) as upd:
            with self.assertRaises(st_stub.RerunRequested):
                activities.render()
        self.assertEqual(upd.call_args.args[1], 7)
        self.assertNotIn("editing_id", st.session_state)
        self.assertEqual(st.session_state["flash_ok"], "Activity updated.")

    def test_delete_needs_confirmation(self):
        st.pressed.add("del_3")
        with mock.patch.object(api, "list_activities", return_value=page([activity(3)])), \
             mock.patch.object(api, "delete_activity") as delete:
            with self.assertRaises(st_stub.RerunRequested):
                activities.render()
        delete.assert_not_called()  # first click only asks "are you sure?"
        self.assertEqual(st.session_state["confirm_delete_id"], 3)

    def test_delete_confirmed(self):
        st.session_state["confirm_delete_id"] = 3
        st.pressed.add("del_yes_3")
        with mock.patch.object(api, "list_activities", return_value=page([activity(3)])), \
             mock.patch.object(api, "delete_activity", return_value=None) as delete:  # 204 -> None
            with self.assertRaises(st_stub.RerunRequested):
                activities.render()
        delete.assert_called_once_with("TOKEN", 3)
        self.assertEqual(st.session_state["flash_ok"], "Activity deleted.")

    def test_delete_failure_keeps_confirmation_and_shows_error(self):
        st.session_state["confirm_delete_id"] = 3
        st.pressed.add("del_yes_3")
        with mock.patch.object(api, "list_activities", return_value=page([activity(3)])), \
             mock.patch.object(api, "delete_activity", side_effect=api.ApiError("Activity not found.", 404)):
            activities.render()
        self.assertTrue(st.called("error"))
        self.assertNotIn("flash_ok", st.session_state)

    def test_delete_cancelled(self):
        st.session_state["confirm_delete_id"] = 3
        st.pressed.add("del_no_3")
        with mock.patch.object(api, "list_activities", return_value=page([activity(3)])), \
             mock.patch.object(api, "delete_activity") as delete:
            with self.assertRaises(st_stub.RerunRequested):
                activities.render()
        delete.assert_not_called()
        self.assertNotIn("confirm_delete_id", st.session_state)


class FakeCookies:
    def __init__(self, value=None):
        self.store = {} if value is None else {session.COOKIE_NAME: value}
        self.removed = 0

    def get(self, name):
        return self.store.get(name)

    def set(self, name, value, **kw):
        self.store[name] = value
        self.kw = kw

    def remove(self, name):
        self.removed += 1
        self.store.pop(name, None)


class SessionTests(unittest.TestCase):
    def setUp(self):
        st.reset()

    def test_refresh_restores_login_from_valid_cookie(self):
        ctrl = FakeCookies("GOOD")
        with mock.patch.object(api, "me", return_value={"full_name": "Asha", "email": "a@b.com"}) as me:
            session.init(ctrl)
        me.assert_called_once_with("GOOD")
        self.assertEqual(st.session_state["token"], "GOOD")
        self.assertTrue(session.is_logged_in())

    def test_expired_cookie_is_deleted_and_user_stays_logged_out(self):
        ctrl = FakeCookies("OLD")
        with mock.patch.object(api, "me", side_effect=api.ApiError("expired", 401)):
            session.init(ctrl)
        self.assertFalse(session.is_logged_in())
        self.assertEqual(ctrl.removed, 1)

    def test_backend_down_keeps_cookie(self):
        ctrl = FakeCookies("GOOD")
        with mock.patch.object(api, "me", side_effect=api.ApiError("Cannot reach", None)):
            session.init(ctrl)
        self.assertFalse(session.is_logged_in())
        self.assertEqual(ctrl.removed, 0)

    def test_no_cookie_no_login(self):
        session.init(FakeCookies())
        self.assertFalse(session.is_logged_in())

    def test_no_cookie_helper_installed_is_fine(self):
        session.init(None)
        self.assertFalse(session.is_logged_in())

    def test_logout_clears_session_and_cookie_and_blocks_restore(self):
        ctrl = FakeCookies("GOOD")
        st.session_state.update({"token": "GOOD", "user": {}})
        session.request_logout("bye")
        with mock.patch.object(api, "me") as me:
            session.init(ctrl)                    # run 1: logout processed
            self.assertFalse(session.is_logged_in())
            self.assertEqual(ctrl.removed, 1)
            ctrl.store[session.COOKIE_NAME] = "GOOD"   # pretend the browser has not deleted it yet
            session.init(ctrl)                    # run 2: must NOT log in again from the stale cookie
            self.assertFalse(session.is_logged_in())
            me.assert_not_called()
            ctrl.store.clear()                    # browser deleted the cookie
            session.init(ctrl)
            self.assertNotIn("_logged_out", st.session_state)

    def test_start_sets_cookie_with_token_lifetime(self):
        ctrl = FakeCookies()
        session.start(ctrl, "NEWTOKEN", {"full_name": "A"}, 3600)
        self.assertEqual(ctrl.store[session.COOKIE_NAME], "NEWTOKEN")
        self.assertEqual(ctrl.kw["max_age"], 3600)
        self.assertEqual(ctrl.kw["same_site"], "strict")
        self.assertTrue(session.is_logged_in())

    def test_broken_cookie_helper_never_crashes_login(self):
        class Broken(FakeCookies):
            def set(self, *a, **k):
                raise RuntimeError("component failed")
        session.start(Broken(), "T", {}, 60)
        self.assertTrue(session.is_logged_in())


if __name__ == "__main__":
    unittest.main()
