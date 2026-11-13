"""Runs app.py itself (login gate + navigation) against the Streamlit stand-in."""
import os
import runpy
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import st_stub  # noqa: E402

st = st_stub.install()
import api_client as api  # noqa: E402

APP = os.path.join(HERE, "..", "app.py")


class AppGateTests(unittest.TestCase):
    def setUp(self):
        st.reset()

    def test_logged_out_user_sees_login_and_nothing_else(self):
        with self.assertRaises(st_stub.StopRequested):
            runpy.run_path(APP, run_name="__main__")
        self.assertFalse(st.called("navigation"))  # the app pages are never built for a visitor
        self.assertTrue(any(c[0] == "tabs" for c in st.calls) or st.called("title"))

    def test_logged_in_user_gets_navigation_with_five_pages(self):
        st.session_state.update({"token": "T", "user": {"full_name": "Asha", "email": "a@b.com"}})
        runpy.run_path(APP, run_name="__main__")
        nav = st.called("navigation")
        self.assertEqual(len(nav), 1)
        self.assertEqual(len(nav[0][1][0]), 5)  # Dashboard, Activities, Documents, Search, Notifications

    def test_pages_are_registered_for_cross_page_jumps(self):
        import navigation
        st.session_state.update({"token": "T", "user": {"full_name": "Asha", "email": "a@b.com"}})
        runpy.run_path(APP, run_name="__main__")
        self.assertEqual(set(navigation._PAGES), {"dashboard", "activities", "documents", "search", "notifications"})

    def test_login_continues_in_same_run_without_rerun(self):
        st.pressed.add("Log in")
        st.inputs.update({"Email": "a@b.com", "Password": "Secret123"})
        with mock.patch.object(api, "login_full", return_value={"access_token": "TOK", "expires_in": 3600}), \
             mock.patch.object(api, "me", return_value={"full_name": "Asha", "email": "a@b.com"}), \
             mock.patch.object(api, "dashboard", return_value={}):
            runpy.run_path(APP, run_name="__main__")  # must not raise RerunRequested / StopRequested
        self.assertEqual(st.session_state["token"], "TOK")
        self.assertTrue(st.called("navigation"))

    def test_blocked_login_shows_the_lockout_message_and_stays_logged_out(self):
        message = "Too many failed login attempts. Please wait 15 minutes and try again."
        st.pressed.add("Log in")
        st.inputs.update({"Email": "a@b.com", "Password": "whatever1"})
        with mock.patch.object(api, "login_full", side_effect=api.ApiError(message, 429)):
            with self.assertRaises(st_stub.StopRequested):
                runpy.run_path(APP, run_name="__main__")
        self.assertTrue(any(message in str(c) for c in st.called("error")))
        self.assertNotIn("token", st.session_state)

    def test_wrong_password_shows_error_and_stays_logged_out(self):
        st.pressed.add("Log in")
        st.inputs.update({"Email": "a@b.com", "Password": "bad"})
        with mock.patch.object(api, "login_full", side_effect=api.ApiError("Invalid email or password.", 401)):
            with self.assertRaises(st_stub.StopRequested):
                runpy.run_path(APP, run_name="__main__")
        self.assertTrue(st.called("error"))
        self.assertNotIn("token", st.session_state)


if __name__ == "__main__":
    unittest.main()
