"""Tests for Part 4: workspace Assistant and History, global Search, Notifications, cross-page navigation."""
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import st_stub  # noqa: E402

st = st_stub.install()

import api_client as api  # noqa: E402
import formatting as fmt  # noqa: E402
import navigation  # noqa: E402
import ui  # noqa: E402
from views import notifications, search, workspace, ws_assistant, ws_history  # noqa: E402

AID = 2
BACKEND_SEARCH = os.path.join(HERE, "..", "..", "backend", "app", "services", "search.py")


class Base(unittest.TestCase):
    def setUp(self):
        st.reset()
        st.session_state["token"] = "TOKEN"
        navigation._PAGES.clear()

    def errors(self):
        return [str(c) for c in st.called("error")]

    def all_text(self):
        return " ".join(str(c) for c in st.calls)

    def shown(self, *names):
        """The real text strings given to st.<name>() (not their repr, which would double the backslashes)."""
        return [str(a) for c in st.calls if not names or c[0] in names for a in c[1] if isinstance(a, str)]

    def assert_safe(self, texts):
        """No markdown image / link / HTML tag may survive once the backslash-escaped characters are removed."""
        for text in texts:
            visible = re.sub(r"\\.", "", text)            # '\!' '\[' ... are shown literally, so they are harmless
            for bad in ("![", "](", "<img", "<b>"):
                self.assertNotIn(bad, visible, text)


# ===================================================================== helpers
class HelperTests(unittest.TestCase):
    def test_history_icons_and_labels(self):
        self.assertEqual(fmt.history_icon("TASK_COMPLETED"), "✅")
        self.assertEqual(fmt.history_icon("SUGGESTION_REJECTED"), "🎯")
        self.assertEqual(fmt.history_icon("SOMETHING_NEW"), "•")
        self.assertEqual(fmt.nice("DOCUMENT_TEXT_CORRECTED"), "Document text corrected")

    def test_md_block_keeps_lines_but_blocks_markdown_tricks(self):
        out = fmt.md_block("line1\nline2 ![x](http://evil)")
        self.assertIn("  \n", out)
        self.assertNotIn("![x](", out)
        self.assertEqual(fmt.md_block(None), "")

    @unittest.skipUnless(os.path.isfile(BACKEND_SEARCH), "backend folder not found")
    def test_search_types_match_the_backend(self):
        source = open(BACKEND_SEARCH, encoding="utf-8").read()
        backend = re.search(r"SEARCH_TYPES\s*=\s*\(([^)]*)\)", source).group(1)
        self.assertEqual(re.findall(r'"(\w+)"', backend), list(fmt.SEARCH_TYPES))


class ApiTests(unittest.TestCase):
    def call(self, fn, *a, **k):
        res = mock.Mock(status_code=200, content=b"x")
        res.json.return_value = {}
        with mock.patch("requests.request", return_value=res) as req:
            fn(*a, **k)
        return req.call_args

    def test_ask_sends_mode_and_waits_longer_than_the_backend_does(self):
        c = self.call(api.ask_assistant, "T", 2, "When is it due?", "local")
        self.assertEqual((c.args[0], c.kwargs["json"]), ("POST", {"question": "When is it due?", "mode": "local"}))
        self.assertTrue(c.args[1].endswith("/activities/2/assistant/ask"))
        self.assertEqual(c.kwargs["timeout"], api.AI_TIMEOUT)
        self.assertGreater(api.AI_TIMEOUT, 30)   # the backend gives Gemini up to 30 s before falling back

    def test_paths(self):
        cases = [
            (api.assistant_status, ("T",), "GET", "/assistant/status"),
            (api.assistant_context, ("T", 2), "GET", "/activities/2/assistant/context"),
            (api.assistant_history, ("T", 2), "GET", "/activities/2/assistant/history"),
            (api.delete_interaction, ("T", 2, 8), "DELETE", "/activities/2/assistant/history/8"),
            (api.activity_history, ("T", 2), "GET", "/activities/2/history"),
            (api.search, ("T", "viva"), "GET", "/search"),
            (api.list_notifications, ("T",), "GET", "/notifications"),
            (api.mark_notification_read, ("T", 4), "POST", "/notifications/4/read"),
            (api.mark_all_notifications_read, ("T",), "POST", "/notifications/read-all"),
            (api.delete_notification, ("T", 4), "DELETE", "/notifications/4"),
        ]
        for fn, args, method, path in cases:
            c = self.call(fn, *args)
            self.assertEqual(c.args[0], method, fn.__name__)
            self.assertTrue(c.args[1].endswith(path), fn.__name__)

    def test_query_parameters(self):
        self.assertEqual(self.call(api.search, "T", "viva", limit=25).kwargs["params"], {"q": "viva", "limit": 25})
        self.assertEqual(self.call(api.search, "T", "viva", types="notes,tasks").kwargs["params"],
                         {"q": "viva", "limit": 10, "types": "notes,tasks"})
        self.assertEqual(self.call(api.list_notifications, "T", unread_only=True, page=2).kwargs["params"],
                         {"page": 2, "page_size": 20, "unread_only": "true"})
        self.assertEqual(self.call(api.list_notifications, "T").kwargs["params"], {"page": 1, "page_size": 20})


# ================================================================== navigation
class NavigationTests(Base):
    def test_go_activity_opens_workspace_on_a_section(self):
        navigation.register("activities", "ACTIVITIES_PAGE")
        st.session_state.update({"ws_section": "old", "ws_editing_task": 4})
        with self.assertRaises(st_stub.SwitchRequested) as cm:
            navigation.go_activity(7, workspace.NOTES)
        self.assertEqual(cm.exception.page, "ACTIVITIES_PAGE")
        self.assertEqual(st.session_state["open_activity_id"], 7)
        self.assertEqual(st.session_state["ws_section"], workspace.NOTES)
        self.assertNotIn("ws_editing_task", st.session_state)   # leftovers from another activity are cleared

    def test_go_document(self):
        navigation.register("documents", "DOCS_PAGE")
        st.session_state["doc_download"] = {"id": 1}
        with self.assertRaises(st_stub.SwitchRequested):
            navigation.go_document(9)
        self.assertEqual(st.session_state["doc_open_id"], 9)
        self.assertNotIn("doc_download", st.session_state)

    def test_unknown_page_fails_visibly(self):
        navigation.go("nowhere")
        self.assertTrue(self.errors())


# ================================================================== assistant
def status(configured=True):
    return {"provider": "gemini", "ai_configured": configured, "model": "gemini-2.5-flash",
            "max_questions_per_hour": 30, "note": "n"}


def answer(**over):
    base = {"id": 1, "question": "What is the deadline?", "answer": "The deadline is 1 Dec 2026 [Activity].",
            "source": "gemini", "ai_status": "ok", "notice": None, "has_information": True,
            "references": [{"label": "Activity", "kind": "activity", "title": "MCA Project"}],
            "unverified_references": [], "context_truncated": False, "created_at": "2026-10-14T05:00:00Z"}
    base.update(over)
    return base


def interactions(items=(), total=None):
    return {"items": list(items), "total": len(items) if total is None else total, "page": 1, "page_size": 5}


def interaction(i=8, **over):
    base = {"id": i, "question": "Old question?", "answer": "Old answer", "status": "SUCCESS", "source": "gemini",
            "note": None, "created_at": "2026-10-13T05:00:00Z"}
    base.update(over)
    return base


class AssistantTests(Base):
    def render(self, configured=True, history=None):
        with mock.patch.object(api, "assistant_status", return_value=status(configured)), \
             mock.patch.object(api, "assistant_history", return_value=history or interactions()) as h:
            ws_assistant.render(AID)
        return h

    def test_when_gemini_is_configured_privacy_is_stated(self):
        self.render(True)
        self.assertIn("gemini-2.5-flash", self.all_text())
        notice = [t for t in self.shown("caption") if "Privacy" in t]
        self.assertEqual(len(notice), 1)                                   # an explicit privacy statement is shown ...
        self.assertIn("tasks, notes, expenses and documents is sent to Google Gemini", notice[0])  # ... saying what is sent where

    def test_when_not_configured_it_defaults_to_local_and_says_everything_else_works(self):
        with mock.patch.object(api, "ask_assistant", return_value=answer(source="keyword", ai_status="not_used")) as ask:
            st.pressed.add("Ask"); st.inputs["Your question"] = "What is due?"
            self.render(False)
        self.assertIn("not set up", self.all_text())
        self.assertEqual(ask.call_args.args[3], "local")        # nothing is sent to Google by default
        self.assertNotIn("is sent to Google Gemini", self.all_text())

    def test_status_failure_does_not_break_the_section(self):
        with mock.patch.object(api, "assistant_status", side_effect=api.ApiError("Cannot reach the Cogniflow server.")), \
             mock.patch.object(api, "assistant_history", return_value=interactions()):
            ws_assistant.render(AID)
        self.assertTrue(self.errors())

    def test_ask_sends_question_and_mode_and_shows_the_answer(self):
        st.pressed.add("Ask")
        st.inputs.update({"Your question": "  What is the deadline? "})
        with mock.patch.object(api, "ask_assistant", return_value=answer()) as ask:
            self.render(True)
        self.assertEqual(ask.call_args.args, ("TOKEN", AID, "What is the deadline?", "auto"))
        self.assertEqual(st.session_state[ws_assistant.LAST_KEY]["source"], "gemini")
        self.assertIn("Answered by Gemini", self.all_text())

    def test_user_can_choose_local_mode_so_nothing_is_sent(self):
        st.pressed.add("Ask")
        st.inputs.update({"Your question": "Q?", "How should your question be answered?": "local"})
        with mock.patch.object(api, "ask_assistant", return_value=answer(source="keyword", ai_status="not_used")) as ask:
            self.render(True)
        self.assertEqual(ask.call_args.args[3], "local")
        self.assertNotIn("is sent to Google Gemini", self.all_text())
        self.assertFalse([t for t in self.shown("caption") if "Privacy" in t])   # nothing is sent, so no warning is needed

    def test_blank_question_is_not_sent(self):
        st.pressed.add("Ask"); st.inputs["Your question"] = "   "
        with mock.patch.object(api, "ask_assistant") as ask:
            self.render()
        ask.assert_not_called()
        self.assertTrue(self.errors())

    def test_example_button_asks_that_question(self):
        st.pressed.add("ws_ai_ex_0")
        with mock.patch.object(api, "ask_assistant", return_value=answer()) as ask:
            self.render()
        self.assertEqual(ask.call_args.args[2], ws_assistant.EXAMPLES[0])

    def test_nothing_is_asked_without_a_click(self):
        with mock.patch.object(api, "ask_assistant") as ask:
            self.render()
        ask.assert_not_called()

    def test_rate_limit_message_is_shown_and_no_answer_stored(self):
        st.pressed.add("Ask"); st.inputs["Your question"] = "Q?"
        with mock.patch.object(api, "ask_assistant", side_effect=api.ApiError("You have asked many questions in the last hour.", 429)):
            self.render()
        self.assertTrue(any("many questions" in e for e in self.errors()))
        self.assertNotIn(ws_assistant.LAST_KEY, st.session_state)

    # ---- the answer card
    def card(self, a):
        st.session_state[ws_assistant.LAST_KEY] = a
        self.render()

    def test_keyword_fallback_is_labelled_and_the_ai_problem_is_explained(self):
        self.card(answer(source="keyword", ai_status="unavailable", answer="Matching items:\n- Task 5",
                         notice="Gemini is not reachable right now. Showing a keyword-based answer instead."))
        self.assertIn("keyword search (no AI)", self.all_text())
        self.assertTrue(any("not reachable" in str(c) for c in st.called("warning")))

    def test_local_mode_notice_is_informational_not_a_warning(self):
        self.card(answer(source="keyword", ai_status="not_used", notice="Answered with keyword search only. Nothing was sent to Gemini."))
        self.assertFalse(st.called("warning"))
        self.assertTrue(st.called("info"))

    def test_missing_information_is_said_plainly(self):
        self.card(answer(has_information=False, answer="I don't have that information in this activity's data.", references=[]))
        self.assertIn("does not seem to contain that information", self.all_text())

    def test_invented_references_are_flagged(self):
        self.card(answer(unverified_references=["Task 99"], notice="Some references (Task 99) do not exist."))
        self.assertTrue(any("Task 99" in str(c) and "may be wrong" in str(c) for c in st.called("warning")))

    def test_references_and_truncation_are_shown(self):
        self.card(answer(context_truncated=True))
        self.assertIn("Based on 1 item", self.all_text())
        self.assertIn("MCA Project", self.all_text())
        self.assertIn("may be incomplete", self.all_text())

    def test_hostile_ai_output_cannot_load_images_or_links(self):
        evil = "Done. ![x](http://evil.example/p.png) [click](http://evil.example) <img src=x>"
        self.card(answer(answer=evil, question="![q](http://evil.example/q.png)"))
        texts = self.shown("markdown")
        self.assertTrue(any("evil.example" in t for t in texts))     # the text IS shown ...
        self.assert_safe(texts)                                        # ... but cannot act as an image, link or tag

    # ---- transparency
    def test_data_preview_is_only_fetched_when_asked_for(self):
        with mock.patch.object(api, "assistant_context") as ctx:
            self.render()
        ctx.assert_not_called()
        st.reset(); st.session_state["token"] = "T"; st.inputs["Show exactly what data would be used"] = True
        data = {"text": "[Activity] MCA Project", "char_count": 22, "truncated": False, "sources": [{"label": "Activity", "kind": "activity", "title": "x"}]}
        with mock.patch.object(api, "assistant_context", return_value=data) as ctx:
            self.render()
        ctx.assert_called_once_with("T", AID)
        self.assertIn("Only this is sent", self.all_text())

    # ---- earlier questions
    def test_earlier_questions_are_listed_and_deletable_with_confirmation(self):
        self.render(history=interactions([interaction(8)]))
        self.assertIn("Earlier questions (1)", self.all_text())
        st.reset(); st.session_state["token"] = "T"; st.pressed.add("ai_del_8")
        with mock.patch.object(api, "delete_interaction") as dele:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(history=interactions([interaction(8)]))
        dele.assert_not_called()
        st.pressed.clear(); st.pressed.add("ai_yes_8")
        with mock.patch.object(api, "delete_interaction", return_value=None) as dele:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(history=interactions([interaction(8)]))
        dele.assert_called_once_with("T", AID, 8)   # (this test resets the stand-in, so its token is "T")

    def test_no_history_means_no_section(self):
        self.render(history=interactions([]))
        self.assertNotIn("Earlier questions", self.all_text())


# ==================================================================== history
def event(i=1, **over):
    base = {"id": i, "action": "TASK_CREATED", "entity_type": "task", "entity_id": 5, "details": "Task “Write chapter 3” created",
            "created_at": "2026-10-14T05:00:00Z"}
    base.update(over)
    return base


def hist(items, total=None):
    return {"items": items, "total": len(items) if total is None else total, "page": 1, "page_size": 20}


class HistoryTests(Base):
    def render(self, data):
        with mock.patch.object(api, "activity_history", return_value=data) as m:
            ws_history.render(AID)
        return m

    def test_timeline(self):
        m = self.render(hist([event(1), event(2, action="SUGGESTION_REJECTED", details=None)]))
        self.assertEqual(m.call_args.args, ("TOKEN", AID))
        self.assertEqual(m.call_args.kwargs, {"page": 1, "page_size": 20})
        text = self.all_text()
        self.assertIn("Task created", text)
        self.assertIn("Suggestion rejected", text)
        self.assertIn("2 events, newest first", text)

    def test_empty(self):
        self.render(hist([]))
        self.assertIn("Nothing has happened yet", self.all_text())

    def test_details_from_documents_are_escaped(self):
        self.render(hist([event(details="Uploaded ![x](http://evil.example/t.png).pdf")]))
        texts = self.shown("write")
        self.assertTrue(any("evil.example" in t for t in texts))
        self.assert_safe(texts)

    def test_pager_and_clamp(self):
        self.render(hist([event()], total=45))
        self.assertTrue(any(c[0] == "number_input" and "1–3" in c[1][0] for c in st.calls))
        st.reset(); st.session_state.update({"token": "T", "ws_hist_page": 9})
        with self.assertRaises(st_stub.RerunRequested):
            self.render(hist([], total=5))
        self.assertEqual(st.session_state["ws_hist_page"], 1)

    def test_error_is_shown(self):
        with mock.patch.object(api, "activity_history", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            ws_history.render(AID)
        self.assertTrue(self.errors())


class WorkspaceSectionTests(Base):
    ACT = {"id": AID, "title": "P", "description": None, "activity_type": "PROJECT", "status": "ACTIVE",
           "priority": 3, "start_date": None, "deadline": None}

    def test_new_sections_exist_and_load_only_their_data(self):
        self.assertEqual(list(workspace.SECTIONS)[-2:], [workspace.ASSISTANT, workspace.HISTORY])
        st.inputs["Section"] = workspace.HISTORY
        with mock.patch.object(api, "get_activity", return_value=self.ACT), \
             mock.patch.object(api, "activity_history", return_value=hist([])) as h, \
             mock.patch.object(api, "list_tasks") as tasks, mock.patch.object(api, "assistant_status") as a:
            workspace.render(AID)
        h.assert_called_once(); tasks.assert_not_called(); a.assert_not_called()
        st.reset(); st.session_state["token"] = "T"; st.inputs["Section"] = workspace.ASSISTANT
        with mock.patch.object(api, "get_activity", return_value=self.ACT), \
             mock.patch.object(api, "assistant_status", return_value=status()) as a, \
             mock.patch.object(api, "assistant_history", return_value=interactions()), \
             mock.patch.object(api, "activity_history") as h:
            workspace.render(AID)
        a.assert_called_once(); h.assert_not_called()


# ===================================================================== search
def hit(kind="tasks", i=5, **over):
    base = {"type": kind, "id": i, "title": f"{kind} hit", "snippet": "…the viva is on Monday…", "activity_id": AID,
            "activity_title": "MCA Project", "document_id": None}
    base.update(over)
    return base


def results(hits, query="viva"):
    counts = {}
    for h in hits:
        counts[h["type"]] = counts.get(h["type"], 0) + 1
    return {"query": query, "total": len(hits), "counts": counts, "results": hits}


class SearchTests(Base):
    def render(self, query, data=None, **inputs):
        st.inputs["Search"] = query
        st.inputs.update(inputs)
        with mock.patch.object(api, "search", return_value=data if data is not None else results([])) as m:
            search.render()
        return m

    def test_empty_query_shows_hint_without_calling_the_api(self):
        m = self.render("")
        m.assert_not_called()
        self.assertIn("Search everything in one place", self.all_text())

    def test_one_character_is_not_searched(self):
        m = self.render("a")
        m.assert_not_called()
        self.assertIn("at least 2 characters", self.all_text())

    def test_no_place_selected(self):
        m = self.render("viva", **{"Look in": []})
        m.assert_not_called()
        self.assertIn("at least one place", self.all_text())

    def test_all_places_means_no_type_filter(self):
        m = self.render("  viva ", results([hit()]))
        self.assertEqual(m.call_args.args, ("TOKEN", "viva"))
        self.assertEqual(m.call_args.kwargs, {"types": None, "limit": 10})

    def test_subset_of_places_is_sent_as_comma_list(self):
        m = self.render("viva", results([hit()]), **{"Look in": ["notes", "tasks"], "Per type": 25})
        self.assertEqual(m.call_args.kwargs, {"types": "notes,tasks", "limit": 25})

    def test_results_grouped_in_a_fixed_order(self):
        self.render("viva", results([hit("tasks", 1), hit("activities", 2), hit("notes", 3)]))
        headings = [c[1][0] for c in st.called("subheader")]
        self.assertEqual(headings, ["Activities (1)", "Notes (1)", "Tasks (1)"])
        self.assertIn("3 results", self.all_text())

    def test_no_results_escapes_the_query(self):
        self.render("![x](http://evil.example/t.png)", results([], query="x"))
        self.assertIn("No results for", self.all_text())
        self.assert_safe(self.shown("markdown"))

    def test_hostile_titles_and_snippets_are_escaped(self):
        self.render("viva", results([hit(title="![x](http://evil.example/a.png)", snippet="[click](http://evil.example)")]))
        texts = self.shown("markdown", "caption")
        self.assertTrue(any("evil.example" in t for t in texts))
        self.assert_safe(texts)

    def test_backend_error_is_shown(self):
        st.inputs["Search"] = "viva"
        with mock.patch.object(api, "search", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            search.render()
        self.assertTrue(self.errors())

    # ---- Open buttons
    def open(self, h, expect_page):
        navigation.register("activities", "ACTIVITIES"); navigation.register("documents", "DOCUMENTS")
        st.pressed.add(f"search_open_{h['type']}_{h['id']}")
        with self.assertRaises(st_stub.SwitchRequested) as cm:
            self.render("viva", results([h]))
        self.assertEqual(cm.exception.page, expect_page)

    def test_task_note_and_expense_hits_open_the_right_workspace_section(self):
        for kind, section in (("tasks", workspace.TASKS), ("notes", workspace.NOTES), ("expenses", workspace.EXPENSES)):
            st.reset(); st.session_state["token"] = "T"
            self.open(hit(kind, 5, activity_id=7), "ACTIVITIES")
            self.assertEqual(st.session_state["open_activity_id"], 7, kind)
            self.assertEqual(st.session_state["ws_section"], section, kind)

    def test_activity_hit_opens_its_workspace(self):
        self.open(hit("activities", 4, activity_id=4), "ACTIVITIES")
        self.assertEqual(st.session_state["open_activity_id"], 4)

    def test_document_hit_opens_the_document(self):
        self.open(hit("documents", 12, activity_id=None, activity_title=None), "DOCUMENTS")
        self.assertEqual(st.session_state["doc_open_id"], 12)

    def test_extracted_information_hit_opens_its_document_not_the_item(self):
        self.open(hit("extracted", 99, document_id=12), "DOCUMENTS")
        self.assertEqual(st.session_state["doc_open_id"], 12)


# ============================================================== notifications
def notification(i=4, **over):
    base = {"id": i, "reminder_id": 1, "message": "Reminder: Submit report", "is_read": False, "created_at": "2026-10-14T05:00:00Z"}
    base.update(over)
    return base


def notif_page(items, unread=None, total=None):
    return {"items": items, "total": len(items) if total is None else total,
            "unread_count": sum(1 for i in items if not i["is_read"]) if unread is None else unread, "page": 1, "page_size": 20}


class NotificationTests(Base):
    def render(self, data):
        with mock.patch.object(api, "list_notifications", return_value=data) as m:
            notifications.render()
        return m

    def test_list_shows_unread_count_and_new_marker(self):
        m = self.render(notif_page([notification(1), notification(2, is_read=True)]))
        self.assertEqual(m.call_args.kwargs, {"unread_only": False, "page": 1, "page_size": 20})
        self.assertEqual(st.metrics["Unread"], 1)
        self.assertIn("Reminder: Submit report", self.all_text())

    def test_unread_filter(self):
        st.inputs["Show unread only"] = True
        m = self.render(notif_page([notification()]))
        self.assertTrue(m.call_args.kwargs["unread_only"])

    def test_empty_states(self):
        self.render(notif_page([]))
        self.assertIn("No notifications yet", self.all_text())
        st.reset(); st.session_state["token"] = "T"; st.inputs["Show unread only"] = True
        self.render(notif_page([]))
        self.assertIn("all caught up", self.all_text())

    def test_mark_one_read(self):
        st.pressed.add("notif_read_4")
        with mock.patch.object(api, "mark_notification_read", return_value=notification(is_read=True)) as r:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(notif_page([notification(4)]))
        r.assert_called_once_with("TOKEN", 4)

    def test_read_notifications_have_no_mark_button(self):
        st.pressed.add("notif_read_4")
        with mock.patch.object(api, "mark_notification_read") as r:
            self.render(notif_page([notification(4, is_read=True)]))
        r.assert_not_called()

    def test_mark_all_read(self):
        st.pressed.add("notif_read_all")
        with mock.patch.object(api, "mark_all_notifications_read", return_value={"updated": 2}) as r:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(notif_page([notification(1), notification(2)]))
        r.assert_called_once_with("TOKEN")
        self.assertIn("marked as read", st.session_state["flash_ok"])

    def test_mark_all_button_hidden_when_nothing_is_unread(self):
        st.pressed.add("notif_read_all")
        with mock.patch.object(api, "mark_all_notifications_read") as r:
            self.render(notif_page([notification(1, is_read=True)]))
        r.assert_not_called()

    def test_delete_needs_confirmation(self):
        st.pressed.add("notification_del_4")
        with mock.patch.object(api, "delete_notification") as d:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(notif_page([notification(4)]))
        d.assert_not_called()
        st.pressed.clear(); st.pressed.add("notification_yes_4")
        with mock.patch.object(api, "delete_notification", return_value=None) as d:
            with self.assertRaises(st_stub.RerunRequested):
                self.render(notif_page([notification(4)]))
        d.assert_called_once_with("TOKEN", 4)

    def test_message_is_escaped(self):
        self.render(notif_page([notification(message="Reminder: ![x](http://evil.example/a.png)")]))
        texts = self.shown("markdown")
        self.assertTrue(any("evil.example" in t for t in texts))
        self.assert_safe(texts)

    def test_page_clamp_and_error(self):
        st.session_state["notif_page"] = 4
        with self.assertRaises(st_stub.RerunRequested):
            self.render(notif_page([], total=3))
        self.assertEqual(st.session_state["notif_page"], 1)
        st.reset(); st.session_state["token"] = "T"
        with mock.patch.object(api, "list_notifications", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            notifications.render()
        self.assertTrue(self.errors())


if __name__ == "__main__":
    unittest.main()
