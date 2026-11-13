import unittest
from datetime import date
from unittest import mock

import requests

import api_client as api


def fake_response(status=200, body=None, content=True):
    res = mock.Mock()
    res.status_code = status
    res.content = b"x" if content else b""
    res.json.return_value = body
    return res


class ApiClientTests(unittest.TestCase):
    def test_sends_bearer_token(self):
        with mock.patch("requests.request", return_value=fake_response(body={"ok": 1})) as req:
            api.dashboard("TOKEN")
        self.assertEqual(req.call_args.kwargs["headers"], {"Authorization": "Bearer TOKEN"})
        self.assertTrue(req.call_args.args[1].endswith("/dashboard"))

    def test_error_detail_is_returned_to_user(self):
        with mock.patch("requests.request", return_value=fake_response(401, {"detail": "Invalid email or password."})):
            with self.assertRaises(api.ApiError) as cm:
                api.login_full("a@b.com", "x")
        self.assertEqual(str(cm.exception), "Invalid email or password.")
        self.assertEqual(cm.exception.status_code, 401)

    def test_validation_errors_are_joined(self):
        body = {"detail": "Invalid input.", "errors": [{"field": "title", "message": "A"}, {"field": "x", "message": "B"}]}
        with mock.patch("requests.request", return_value=fake_response(422, body)):
            with self.assertRaises(api.ApiError) as cm:
                api.create_activity("T", {"title": ""})
        self.assertEqual(str(cm.exception), "A B")

    def test_non_json_error_body(self):
        res = fake_response(502)
        res.json.side_effect = ValueError()
        with mock.patch("requests.request", return_value=res):
            with self.assertRaises(api.ApiError) as cm:
                api.me("T")
        self.assertEqual(str(cm.exception), "Unexpected response from the server.")

    def test_unreachable_backend_gives_friendly_message(self):
        with mock.patch("requests.request", side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(api.ApiError) as cm:
                api.me("T")
        self.assertIn("backend is running", str(cm.exception))
        self.assertIsNone(cm.exception.status_code)

    def test_empty_204_response_returns_none(self):
        with mock.patch("requests.request", return_value=fake_response(204, content=False)):
            self.assertIsNone(api.delete_activity("T", 5))

    def test_list_activities_only_sends_set_filters(self):
        with mock.patch("requests.request", return_value=fake_response(body={"items": []})) as req:
            api.list_activities("T", q="  exam ", activity_type=None, status="ACTIVE", sort="deadline", page=2, page_size=10)
        self.assertEqual(req.call_args.kwargs["params"],
                         {"sort": "deadline", "page": 2, "page_size": 10, "q": "exam", "status": "ACTIVE"})

    def test_dates_are_sent_as_iso_strings_and_none_clears(self):
        with mock.patch("requests.request", return_value=fake_response(body={})) as req:
            api.update_activity("T", 3, {"deadline": date(2026, 11, 1), "start_date": None})
        self.assertEqual(req.call_args.kwargs["json"], {"deadline": "2026-11-01", "start_date": None})
        self.assertEqual(req.call_args.args[0], "PATCH")

    def test_login_still_returns_token_string(self):
        with mock.patch("requests.request", return_value=fake_response(body={"access_token": "abc", "expires_in": 3600})):
            self.assertEqual(api.login("a@b.com", "pw"), "abc")


class WorkspaceApiTests(unittest.TestCase):
    def call(self, fn, *args, **kwargs):
        with mock.patch("requests.request", return_value=fake_response(body={})) as req:
            fn(*args, **kwargs)
        return req.call_args

    def test_paths_and_methods(self):
        cases = [
            (api.list_tasks, ("T", 4), "GET", "/activities/4/tasks"),
            (api.create_task, ("T", 4, {"title": "x"}), "POST", "/activities/4/tasks"),
            (api.update_task, ("T", 4, 9, {}), "PATCH", "/activities/4/tasks/9"),
            (api.delete_task, ("T", 4, 9), "DELETE", "/activities/4/tasks/9"),
            (api.list_notes, ("T", 4), "GET", "/activities/4/notes"),
            (api.update_note, ("T", 4, 2, {}), "PATCH", "/activities/4/notes/2"),
            (api.delete_note, ("T", 4, 2), "DELETE", "/activities/4/notes/2"),
            (api.list_expenses, ("T", 4), "GET", "/activities/4/expenses"),
            (api.update_expense, ("T", 4, 7, {}), "PATCH", "/activities/4/expenses/7"),
            (api.delete_expense, ("T", 4, 7), "DELETE", "/activities/4/expenses/7"),
            (api.list_reminders, ("T", 4), "GET", "/activities/4/reminders"),
            (api.update_reminder, ("T", 4, 3, {}), "PATCH", "/activities/4/reminders/3"),
            (api.delete_reminder, ("T", 4, 3), "DELETE", "/activities/4/reminders/3"),
            (api.get_activity, ("T", 4), "GET", "/activities/4"),
        ]
        for fn, args, method, path in cases:
            call = self.call(fn, *args)
            self.assertEqual(call.args[0], method, fn.__name__)
            self.assertTrue(call.args[1].endswith(path), fn.__name__)
            self.assertEqual(call.kwargs["headers"], {"Authorization": "Bearer T"}, fn.__name__)

    def test_task_filters_only_sent_when_set(self):
        call = self.call(api.list_tasks, "T", 4, status_filter="PENDING", sort="due")
        self.assertEqual(call.kwargs["params"], {"sort": "due", "status_filter": "PENDING"})
        call = self.call(api.list_tasks, "T", 4)
        self.assertEqual(call.kwargs["params"], {"sort": "priority"})

    def test_clearing_manual_priority_sends_an_explicit_null(self):
        call = self.call(api.update_task, "T", 4, 9, {"manual_priority": None})
        self.assertEqual(call.kwargs["json"], {"manual_priority": None})   # the backend treats null as "clear the override"

    def test_money_and_datetimes_are_serialised(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        call = self.call(api.create_expense, "T", 4, {"amount": Decimal("1200.50"), "expense_date": date(2026, 10, 1)})
        self.assertEqual(call.kwargs["json"], {"amount": "1200.50", "expense_date": "2026-10-01"})
        call = self.call(api.create_reminder, "T", 4, {"remind_at": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)})
        self.assertEqual(call.kwargs["json"], {"remind_at": "2026-10-01T09:00:00+00:00"})

    def test_note_search_only_when_text_given(self):
        self.assertEqual(self.call(api.list_notes, "T", 4, q="  ").kwargs["params"], {})
        self.assertEqual(self.call(api.list_notes, "T", 4, q=" viva ").kwargs["params"], {"q": "viva"})


if __name__ == "__main__":
    unittest.main()
