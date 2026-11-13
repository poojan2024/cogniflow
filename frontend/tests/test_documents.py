"""Tests for the Documents page, the workspace Documents section and the shared document widgets."""
import importlib.util
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
import ui  # noqa: E402
from views import doc_widgets, documents, workspace, ws_documents  # noqa: E402

BACKEND = os.path.join(HERE, "..", "..", "backend", "app")
ACTS = [{"id": 2, "title": "MCA Final-Year Project"}, {"id": 3, "title": "Goa Trip"}]


class FakeUpload:
    def __init__(self, name="notice.pdf", data=b"%PDF-1.4 content", type_="application/pdf"):
        self.name, self._data, self.type = name, data, type_

    def getvalue(self):
        return self._data


def doc(i=7, **over):
    base = {"id": i, "activity_id": None, "original_filename": "notice.pdf", "mime_type": "application/pdf",
            "file_size": 2048, "processing_status": "PROCESSED", "extraction_method": "TEXT", "ocr_confidence": None,
            "error_message": None, "created_at": "2026-10-14T05:00:00Z", "processed_at": "2026-10-14T05:00:03Z",
            "extracted_text": "Project report due on 20 Oct 2026",
            "items": [{"id": 1, "info_type": "KEYWORD", "value": "project", "context": None, "source": "RULE"},
                      {"id": 2, "info_type": "DEADLINE", "value": "20 Oct 2026", "context": "report due on 20 Oct 2026", "source": "RULE"}]}
    base.update(over)
    return base


def sugg(i=11, **over):
    base = {"id": i, "document_id": 7, "activity_id": 2, "activity_title": "MCA Final-Year Project", "activity_type": "PROJECT",
            "score": 72.4, "confidence": "strong", "explanation": "Shares the words project, report.", "status": "PENDING",
            "created_at": "2026-10-14T05:00:04Z", "resolved_at": None}
    base.update(over)
    return base


def doc_page(items, total=None):
    return {"items": items, "total": len(items) if total is None else total, "page": 1, "page_size": 10}


class Base(unittest.TestCase):
    def setUp(self):
        st.reset()
        st.session_state["token"] = "TOKEN"

    def errors(self):
        return [str(c) for c in st.called("error")]

    def all_text(self):
        return " ".join(str(c) for c in st.calls)


# ======================================================== formatting / security
class FormattingTests(unittest.TestCase):
    def test_status_labels(self):
        self.assertEqual(fmt.doc_status_label("PROCESSED"), "✅ :green[Processed]")
        self.assertEqual(fmt.doc_status_label("NEEDS_REVIEW"), "⚠️ :orange[Needs review]")
        self.assertEqual(fmt.doc_status_label("FAILED"), "❌ :red[Failed]")

    def test_method_text(self):
        self.assertIn("real text", fmt.method_text({"extraction_method": "TEXT"}))
        self.assertEqual(fmt.method_text({"extraction_method": "OCR", "ocr_confidence": 87.4}),
                         "OCR (scanned page or image) · engine confidence 87/100")
        self.assertEqual(fmt.method_text({"extraction_method": "NONE"}), "No text extracted")

    def test_human_size(self):
        self.assertEqual(fmt.human_size(512), "512 B")
        self.assertEqual(fmt.human_size(1536), "1.5 KB")
        self.assertEqual(fmt.human_size(5 * 1024 * 1024), "5.0 MB")

    def test_md_escape_neutralises_images_links_and_html(self):
        evil = "![x](http://evil.example/p.png) [click](http://evil.example) <img src=x> *bold* `code`"
        out = fmt.md_escape(evil)
        for bad in ("![", "](", "<img", "**"):
            self.assertNotIn(bad, out.replace("\\!", "").replace("\\[", "").replace("\\]", "").replace("\\(", "").replace("\\<", "").replace("\\*", ""))
        self.assertEqual(fmt.md_escape("![x](u)"), "\\!\\[x\\]\\(u\\)")
        self.assertEqual(fmt.md_escape(None), "")
        self.assertEqual(fmt.md_escape("plain text 123"), "plain text 123")


@unittest.skipUnless(os.path.isfile(os.path.join(BACKEND, "services", "file_validation.py")), "backend folder not found")
class BackendContractTests(unittest.TestCase):
    def test_upload_types_and_size_match_the_backend(self):
        spec = importlib.util.spec_from_file_location("backend_file_validation", os.path.join(BACKEND, "services", "file_validation.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules["backend_file_validation"] = module
        spec.loader.exec_module(module)
        self.assertEqual(sorted(e.lstrip(".") for e in module.ALLOWED), sorted(fmt.UPLOAD_TYPES))
        config = open(os.path.join(BACKEND, "core", "config.py"), encoding="utf-8").read()
        self.assertEqual(int(re.search(r"max_upload_mb:\s*int\s*=\s*(\d+)", config).group(1)), fmt.MAX_UPLOAD_MB)


# ================================================================== API client
class ApiTests(unittest.TestCase):
    def call(self, fn, *a, **k):
        res = mock.Mock(status_code=200, content=b"x")
        res.json.return_value = {}
        with mock.patch("requests.request", return_value=res) as req:
            fn(*a, **k)
        return req.call_args

    def test_upload_is_multipart_with_activity_and_longer_timeout(self):
        c = self.call(api.upload_document, "T", "a.pdf", b"data", "application/pdf", 5)
        self.assertEqual(c.args[:2][0], "POST")
        self.assertEqual(c.kwargs["files"], {"file": ("a.pdf", b"data", "application/pdf")})
        self.assertEqual(c.kwargs["data"], {"activity_id": "5"})
        self.assertEqual(c.kwargs["timeout"], api.UPLOAD_TIMEOUT)
        c = self.call(api.upload_document, "T", "a.pdf", b"data", "application/pdf")
        self.assertIsNone(c.kwargs["data"])   # no activity -> Cogniflow may suggest one

    def test_paths(self):
        cases = [
            (api.list_documents, ("T",), "GET", "/documents"),
            (api.get_document, ("T", 7), "GET", "/documents/7"),
            (api.correct_document_text, ("T", 7, "x"), "PATCH", "/documents/7/text"),
            (api.reprocess_document, ("T", 7), "POST", "/documents/7/reprocess"),
            (api.assign_document, ("T", 7, 2), "PATCH", "/documents/7"),
            (api.delete_document_item, ("T", 7, 1), "DELETE", "/documents/7/items/1"),
            (api.delete_document, ("T", 7), "DELETE", "/documents/7"),
            (api.list_suggestions, ("T", 7), "GET", "/documents/7/suggestions"),
            (api.refresh_suggestions, ("T", 7), "POST", "/documents/7/suggestions"),
            (api.confirm_suggestion, ("T", 7, 11), "POST", "/documents/7/suggestions/11/confirm"),
            (api.reject_suggestion, ("T", 7, 11), "POST", "/documents/7/suggestions/11/reject"),
        ]
        for fn, args, method, path in cases:
            c = self.call(fn, *args)
            self.assertEqual(c.args[0], method, fn.__name__)
            self.assertTrue(c.args[1].endswith(path), fn.__name__)

    def test_assign_none_sends_explicit_null(self):
        self.assertEqual(self.call(api.assign_document, "T", 7, None).kwargs["json"], {"activity_id": None})

    def test_list_filters(self):
        c = self.call(api.list_documents, "T", unassigned=True, status="FAILED", page=2, page_size=5)
        self.assertEqual(c.kwargs["params"], {"page": 2, "page_size": 5, "unassigned": "true", "status": "FAILED"})

    def test_download_returns_bytes_and_maps_errors(self):
        ok = mock.Mock(status_code=200, content=b"FILEBYTES")
        with mock.patch("requests.get", return_value=ok):
            self.assertEqual(api.download_document("T", 7), b"FILEBYTES")
        bad = mock.Mock(status_code=404)
        bad.json.return_value = {"detail": "The stored file is missing."}
        with mock.patch("requests.get", return_value=bad):
            with self.assertRaises(api.ApiError) as cm:
                api.download_document("T", 7)
        self.assertEqual((str(cm.exception), cm.exception.status_code), ("The stored file is missing.", 404))


# ===================================================================== upload
class UploadTests(Base):
    def submit(self, prefix="doc", activity_id=None, activities=ACTS):
        st.pressed.add("Upload & process")
        doc_widgets.upload_form(prefix, activity_id, activities)

    def test_nothing_happens_until_submit(self):
        with mock.patch.object(api, "upload_document") as up:
            doc_widgets.upload_form("doc", None, ACTS)
        up.assert_not_called()

    def test_no_file_chosen(self):
        with mock.patch.object(api, "upload_document") as up:
            self.submit()
        up.assert_not_called()
        self.assertTrue(any("choose a file" in e for e in self.errors()))

    def test_empty_and_oversize_files_are_stopped_before_sending(self):
        for data, message in ((b"", "empty"), (b"x" * (fmt.MAX_UPLOAD_MB * 1024 * 1024 + 1), "larger than")):
            st.reset(); st.session_state["token"] = "T"
            st.inputs["Choose a document"] = FakeUpload(data=data)
            with mock.patch.object(api, "upload_document") as up:
                self.submit()
            up.assert_not_called()
            self.assertTrue(any(message in e for e in self.errors()), message)

    def test_upload_without_activity_lets_cogniflow_suggest(self):
        st.inputs["Choose a document"] = FakeUpload()
        with mock.patch.object(api, "upload_document", return_value=doc(9)) as up:
            with self.assertRaises(st_stub.RerunRequested):
                self.submit()
        self.assertEqual(up.call_args.args, ("TOKEN", "notice.pdf", b"%PDF-1.4 content", "application/pdf", None))
        self.assertEqual(st.session_state["doc_open_id"], 9)          # the new document opens by itself
        self.assertEqual(st.session_state["doc_upload_n"], 1)         # fresh, empty file box
        self.assertIn("Uploaded", st.session_state["flash_ok"])

    def test_upload_with_chosen_activity(self):
        st.inputs.update({"Choose a document": FakeUpload(), "Put it in": 3})
        with mock.patch.object(api, "upload_document", return_value=doc(9)) as up:
            with self.assertRaises(st_stub.RerunRequested):
                self.submit()
        self.assertEqual(up.call_args.args[-1], 3)

    def test_workspace_upload_is_fixed_to_its_activity(self):
        st.inputs["Choose a document"] = FakeUpload()
        with mock.patch.object(api, "upload_document", return_value=doc(9)) as up:
            with self.assertRaises(st_stub.RerunRequested):
                self.submit(prefix="ws_doc", activity_id=2, activities=None)
        self.assertEqual(up.call_args.args[-1], 2)

    def test_duplicate_file_shows_backend_message_and_stays(self):
        st.inputs["Choose a document"] = FakeUpload()
        with mock.patch.object(api, "upload_document", side_effect=api.ApiError("This file was already uploaded (document #4).", 409)):
            self.submit()
        self.assertTrue(any("already uploaded" in e for e in self.errors()))
        self.assertNotIn("doc_open_id", st.session_state)

    def test_unsupported_type_error_from_backend_is_shown(self):
        st.inputs["Choose a document"] = FakeUpload("virus.exe", b"MZ", "application/octet-stream")
        with mock.patch.object(api, "upload_document", side_effect=api.ApiError("This file type is not supported.", 400)):
            self.submit()
        self.assertTrue(self.errors())


# ====================================================================== page
class DocumentsPageTests(Base):
    def render(self, docs, activities=None, **kw):
        with mock.patch.object(api, "list_activities", return_value={"items": ACTS if activities is None else activities, "total": 2}), \
             mock.patch.object(api, "list_documents", return_value=docs) as listing, \
             mock.patch.object(ui.time, "sleep"):
            documents.render()
        return listing

    def test_empty_state(self):
        self.render(doc_page([]))
        self.assertIn("No documents yet", self.all_text())

    def test_filters_reach_the_backend(self):
        st.inputs.update({"Show": "unassigned", "Status": "FAILED"})
        m = self.render(doc_page([doc()]))
        self.assertEqual(m.call_args.kwargs, {"activity_id": None, "unassigned": True, "status": "FAILED", "page": 1, "page_size": 10})
        st.reset(); st.session_state["token"] = "T"; st.inputs["Show"] = 3
        m = self.render(doc_page([doc()]))
        self.assertEqual((m.call_args.kwargs["activity_id"], m.call_args.kwargs["unassigned"]), (3, False))

    def test_filtered_empty_state(self):
        st.inputs["Status"] = "FAILED"
        self.render(doc_page([]))
        self.assertIn("No documents match", self.all_text())

    def test_hostile_file_name_is_escaped(self):
        evil = "![x](http://evil.example/track.png).pdf"
        self.render(doc_page([doc(original_filename=evil)]))
        shown = " ".join(str(c) for c in st.called("markdown"))
        self.assertNotIn("![x](http", shown)
        self.assertIn("\\\\!\\\\[x\\\\]", shown)   # repr() doubles the backslashes

    def test_open_button_opens_the_details(self):
        st.pressed.add("doc_view_7")
        with self.assertRaises(st_stub.RerunRequested):
            self.render(doc_page([doc()]))
        self.assertEqual(st.session_state["doc_open_id"], 7)

    def test_activities_failing_to_load_is_not_a_crash(self):
        with mock.patch.object(api, "list_activities", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            documents.render()
        self.assertTrue(self.errors())

    # ---- polling
    def test_page_keeps_refreshing_while_a_document_is_processing(self):
        with self.assertRaises(st_stub.RerunRequested):
            self.render(doc_page([doc(processing_status="PROCESSING")]))
        self.assertEqual(st.session_state["poll_count"], 1)

    def test_polling_stops_when_everything_is_finished(self):
        st.session_state["poll_count"] = 5
        self.render(doc_page([doc(), doc(8, processing_status="FAILED")]))   # must not raise
        self.assertNotIn("poll_count", st.session_state)

    def test_polling_gives_up_after_the_limit_and_says_so(self):
        st.session_state["poll_count"] = 40
        self.render(doc_page([doc(processing_status="UPLOADED")]))           # must not raise or loop forever
        self.assertIn("taking longer", self.all_text())

    def test_refresh_button_restarts_polling(self):
        ui.reset_polling()
        self.assertEqual(st.session_state["poll_count"], 0)


# ===================================================================== detail
class DetailTests(Base):
    def panel(self, document, suggestions=None, activities=ACTS, in_workspace=False, open_key="doc_open_id"):
        ls = mock.Mock(return_value=suggestions or [])
        self.last_list_suggestions = ls           # set first: the panel may raise a rerun before returning
        with mock.patch.object(api, "get_document", return_value=document), \
             mock.patch.object(api, "list_suggestions", ls):
            return doc_widgets.detail_panel(document["id"], open_key, activities, in_workspace)

    def test_returns_status_for_polling(self):
        self.assertEqual(self.panel(doc(processing_status="PROCESSING")), "PROCESSING")

    def test_processing_shows_progress_message(self):
        self.panel(doc(processing_status="PROCESSING", extraction_method="NONE", extracted_text=None, items=[]))
        self.assertIn("reading this document", self.all_text())
        self.last_list_suggestions.assert_not_called()

    def test_failed_document_explains_and_can_be_reprocessed(self):
        failed = doc(processing_status="FAILED", extraction_method="NONE", extracted_text=None, items=[],
                     error_message="No text could be read from this image. You can type the text in manually.")
        self.panel(failed)
        self.assertTrue(any("No text could be read" in e for e in self.errors()))
        self.last_list_suggestions.assert_not_called()      # nothing to compare yet
        self.assertIn("No text is available", self.all_text())  # manual text entry is offered
        st.pressed.add("doc_reprocess_7")
        with mock.patch.object(api, "reprocess_document", return_value=failed) as rp:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(failed)
        rp.assert_called_once_with("TOKEN", 7)
        self.assertEqual(st.session_state["poll_count"], 0)

    def test_needs_review_warns_about_ocr_quality_and_explains_confidence(self):
        self.panel(doc(processing_status="NEEDS_REVIEW", extraction_method="OCR", ocr_confidence=41.0,
                       error_message="The scan is hard to read. Please check the text."))
        self.assertTrue(any("hard to read" in str(c) for c in st.called("warning")))
        self.assertIn("not a guarantee", self.all_text())
        self.assertIn("confidence 41/100", self.all_text())

    # ---- suggestion: confirm / reject
    def test_pending_suggestion_is_shown_with_reasons_and_no_action_taken(self):
        with mock.patch.object(api, "confirm_suggestion") as ok, mock.patch.object(api, "reject_suggestion") as no:
            self.panel(doc(), [sugg()])
        text = self.all_text()
        self.assertIn("Suggested activity: MCA Final-Year Project", text)
        self.assertIn("72/100", text)
        self.assertIn("Why was this suggested?", text)
        self.assertIn("not a probability", text)
        ok.assert_not_called(); no.assert_not_called()      # the system never moves a document on its own

    def test_confirm(self):
        st.pressed.add("sugg_ok_11")
        with mock.patch.object(api, "confirm_suggestion", return_value=doc(activity_id=2)) as ok:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc(), [sugg()])
        ok.assert_called_once_with("TOKEN", 7, 11)
        self.assertIn("MCA Final-Year Project", st.session_state["flash_ok"])

    def test_reject_moves_nothing_and_asks_for_manual_choice(self):
        st.pressed.add("sugg_no_11")
        with mock.patch.object(api, "reject_suggestion", return_value=[]) as no, \
             mock.patch.object(api, "assign_document") as assign:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc(), [sugg()])
        no.assert_called_once_with("TOKEN", 7, 11)
        assign.assert_not_called()
        self.assertIn("Nothing was moved", st.session_state["flash_ok"])
        self.assertIn("manually", st.session_state["flash_ok"])

    def test_confirm_error_is_shown(self):
        st.pressed.add("sugg_ok_11")
        with mock.patch.object(api, "confirm_suggestion", side_effect=api.ApiError("This suggestion was already confirmed.", 409)):
            self.panel(doc(), [sugg()])
        self.assertTrue(any("already confirmed" in e for e in self.errors()))

    def test_no_suggestion_found(self):
        self.panel(doc(), [])
        self.assertIn("No matching activity was found", self.all_text())

    def test_rejected_suggestions_are_not_offered_again(self):
        self.panel(doc(), [sugg(status="REJECTED")])
        self.assertIn("1 suggestion rejected earlier", self.all_text())
        self.assertIn("No matching activity was found", self.all_text())

    def test_recalculate(self):
        st.pressed.add("sugg_refresh_7")
        with mock.patch.object(api, "refresh_suggestions", return_value=[]) as rf:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc(), [])
        rf.assert_called_once_with("TOKEN", 7)

    # ---- manual assignment
    def test_manual_assignment(self):
        st.pressed.add("doc_assign_go_7")
        st.inputs["Choose activity"] = 3
        with mock.patch.object(api, "assign_document", return_value=doc(activity_id=3)) as assign:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc(), [])
        assign.assert_called_once_with("TOKEN", 7, 3)

    def test_manual_assignment_works_even_when_processing_failed(self):
        st.pressed.add("doc_assign_go_7")
        with mock.patch.object(api, "assign_document", return_value=doc()) as assign:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc(processing_status="FAILED", extraction_method="NONE", extracted_text=None, items=[]))
        assign.assert_called_once()

    def test_no_activities_gives_a_hint(self):
        self.panel(doc(), [], activities=[])
        self.assertIn("no activities yet", self.all_text())

    def test_assigned_document_has_no_suggestions_and_can_be_removed(self):
        st.pressed.add("doc_unassign_7")
        with mock.patch.object(api, "assign_document", return_value=doc()) as assign:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc(activity_id=2))
        self.last_list_suggestions.assert_not_called()
        assign.assert_called_once_with("TOKEN", 7, None)

    def test_removing_from_workspace_closes_the_panel(self):
        st.session_state["ws_doc_open"] = 7
        st.pressed.add("doc_unassign_7")
        with mock.patch.object(api, "assign_document", return_value=doc()):
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc(activity_id=2), activities=None, in_workspace=True, open_key="ws_doc_open")
        self.assertNotIn("ws_doc_open", st.session_state)

    # ---- extracted items and text
    def test_items_are_ordered_by_type_and_escaped(self):
        d = doc(items=[{"id": 1, "info_type": "KEYWORD", "value": "k", "context": None, "source": "RULE"},
                       {"id": 2, "info_type": "DEADLINE", "value": "![x](http://evil)", "context": "<b>ctx</b>", "source": "RULE"}])
        self.panel(d)
        shown = [c[1][0] for c in st.called("markdown") if "**Deadline:**" in c[1][0] or "**Keyword:**" in c[1][0]]
        self.assertEqual([s.split(":")[0] for s in shown], ["**Deadline", "**Keyword"])
        self.assertNotIn("![x](http", " ".join(shown))

    def test_delete_wrong_item(self):
        st.pressed.add("item_del_2")
        with mock.patch.object(api, "delete_document_item", return_value=None) as dele:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc())
        dele.assert_called_once_with("TOKEN", 7, 2)

    def test_save_corrected_text(self):
        st.pressed.add("doc_text_save_7")
        st.inputs["Text"] = "Corrected text with 25 Oct 2026"
        with mock.patch.object(api, "correct_document_text", return_value=doc()) as fix:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc())
        fix.assert_called_once_with("TOKEN", 7, "Corrected text with 25 Oct 2026")
        self.assertIn("refreshed", st.session_state["flash_ok"])

    def test_unchanged_or_blank_text_is_not_sent(self):
        for value, expected in (("Project report due on 20 Oct 2026", "No changes"), ("   ", "must not be empty")):
            st.reset(); st.session_state["token"] = "T"
            st.pressed.add("doc_text_save_7"); st.inputs["Text"] = value
            with mock.patch.object(api, "correct_document_text") as fix:
                self.panel(doc())
            fix.assert_not_called()
            self.assertIn(expected, self.all_text())

    def test_text_box_key_changes_when_saved_text_changes(self):
        """Otherwise Streamlit would keep showing the user's old edit instead of the newly saved text."""
        self.panel(doc(extracted_text="old"))
        key_old = st.called("text_area")[-1][2]["key"]
        st.calls.clear()
        self.panel(doc(extracted_text="new text"))
        key_new = st.called("text_area")[-1][2]["key"]
        self.assertNotEqual(key_old, key_new)
        st.calls.clear()
        self.panel(doc(extracted_text="new text"))
        self.assertEqual(st.called("text_area")[-1][2]["key"], key_new)   # stable while nothing changes

    # ---- download and delete
    def test_download_is_two_step_and_previews_images(self):
        st.pressed.add("doc_prep_7")
        img = doc(mime_type="image/png", original_filename="scan.png")
        with mock.patch.object(api, "download_document", return_value=b"PNGBYTES") as dl:
            self.panel(img)
        dl.assert_called_once_with("TOKEN", 7)
        self.assertEqual(st.session_state["doc_download"]["data"], b"PNGBYTES")
        st.pressed.clear(); st.calls.clear()
        self.panel(img)                       # next run: the save button and the image preview appear
        self.assertTrue(st.called("download_button"))
        self.assertTrue(st.called("image"))

    def test_download_not_fetched_until_asked(self):
        with mock.patch.object(api, "download_document") as dl:
            self.panel(doc())
        dl.assert_not_called()

    def test_delete_needs_confirmation(self):
        st.pressed.add("document_del_7")
        with mock.patch.object(api, "delete_document") as dele:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc())
        dele.assert_not_called()
        self.assertEqual(st.session_state["ws_confirm_document"], 7)
        st.pressed.clear(); st.pressed.add("document_yes_7")
        with mock.patch.object(api, "delete_document", return_value=None) as dele:
            with self.assertRaises(st_stub.RerunRequested):
                self.panel(doc())
        dele.assert_called_once_with("TOKEN", 7)
        self.assertEqual(st.session_state["flash_ok"], "Document deleted.")

    def test_keep_it_does_not_close_the_panel(self):
        st.session_state.update({"doc_open_id": 7, "ws_confirm_document": 7})
        st.pressed.add("document_no_7")
        with self.assertRaises(st_stub.RerunRequested):
            self.panel(doc())
        self.assertEqual(st.session_state["doc_open_id"], 7)
        self.assertNotIn("ws_confirm_document", st.session_state)

    def test_deleted_meanwhile_closes_panel_without_hiding_the_delete_message(self):
        st.session_state.update({"doc_open_id": 7, "flash_ok": "Document deleted."})
        with mock.patch.object(api, "get_document", side_effect=api.ApiError("Document not found.", 404)):
            with self.assertRaises(st_stub.RerunRequested):
                doc_widgets.detail_panel(7, "doc_open_id", ACTS)
        self.assertNotIn("doc_open_id", st.session_state)
        self.assertEqual(st.session_state["flash_ok"], "Document deleted.")

    def test_backend_error_loading_details_is_shown(self):
        with mock.patch.object(api, "get_document", side_effect=api.ApiError("Cannot reach the Cogniflow server.")):
            self.assertIsNone(doc_widgets.detail_panel(7, "doc_open_id", ACTS))
        self.assertTrue(self.errors())


# ================================================================ workspace
class WorkspaceDocumentsTests(Base):
    def test_section_exists_and_lists_only_this_activitys_documents(self):
        self.assertIn("📄 Documents", workspace.SECTIONS)
        st.inputs["Section"] = "📄 Documents"
        activity = {"id": 2, "title": "P", "description": None, "activity_type": "PROJECT", "status": "ACTIVE",
                    "priority": 3, "start_date": None, "deadline": None}
        with mock.patch.object(api, "get_activity", return_value=activity), \
             mock.patch.object(api, "list_documents", return_value=doc_page([doc(activity_id=2)])) as listing, \
             mock.patch.object(api, "list_tasks") as tasks:
            workspace.render(2)
        self.assertEqual(listing.call_args.kwargs["activity_id"], 2)
        tasks.assert_not_called()

    def test_empty_workspace_documents(self):
        with mock.patch.object(api, "list_documents", return_value=doc_page([])):
            ws_documents.render(2)
        self.assertIn("No documents in this activity yet", self.all_text())

    def test_workspace_polls_while_processing(self):
        with mock.patch.object(api, "list_documents", return_value=doc_page([doc(processing_status="PROCESSING")])), \
             mock.patch.object(ui.time, "sleep"):
            with self.assertRaises(st_stub.RerunRequested):
                ws_documents.render(2)

    def test_leaving_the_workspace_forgets_the_open_document(self):
        st.session_state.update({"ws_doc_open": 7, "ws_doc_upload_n": 2, "open_activity_id": 2})
        workspace.close_workspace()
        self.assertNotIn("ws_doc_open", st.session_state)


if __name__ == "__main__":
    unittest.main()
