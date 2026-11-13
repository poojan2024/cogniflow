"""Document screens shared by the Documents page and the workspace "Documents" section.

Flow shown to the user:  upload -> (background) text extraction or OCR -> extracted information -> suggested activity
-> the USER confirms or rejects (or picks an activity manually). Nothing is ever moved by the system on its own.

All text that comes out of a document (file name, extracted text, items) is untrusted: it is escaped with
fmt.md_escape before being shown as markdown, or shown in a plain text box.
"""
import zlib
from typing import Optional

import streamlit as st

import api_client as api
import formatting as fmt
import ui

IN_PROGRESS = fmt.DOC_IN_PROGRESS
SUGGEST_NONE = None


# ------------------------------------------------------------------ upload
def upload_form(prefix: str, activity_id: Optional[int] = None, activities: Optional[list] = None,
                open_key: str = "doc_open_id") -> None:
    """Upload box. activity_id fixes the target activity (workspace). Otherwise `activities` fills the 'Put it in' list,
    whose default is "no activity yet" so that Cogniflow can SUGGEST one for the user to confirm."""
    n = st.session_state.get(f"{prefix}_upload_n", 0)  # changing the number gives a fresh, empty file box after an upload
    with st.form(f"{prefix}_upload_form_{n}"):
        file = st.file_uploader(
            "Choose a document", type=fmt.UPLOAD_TYPES, key=f"{prefix}_file_{n}",
            help=f"PDF, PNG, JPG or TXT, up to {fmt.MAX_UPLOAD_MB} MB. Scanned pages and photos are read with OCR.")
        target = activity_id
        if activities is not None:
            ids = [SUGGEST_NONE] + [a["id"] for a in activities]
            titles = {a["id"]: a["title"] for a in activities}
            target = st.selectbox(
                "Put it in", ids, key=f"{prefix}_target_{n}",
                format_func=lambda i: "Let Cogniflow suggest an activity (you confirm)" if i is SUGGEST_NONE else titles[i])
        submitted = st.form_submit_button("Upload & process", type="primary")
    if not submitted:
        return
    if file is None:
        st.error("Please choose a file first.")
        return
    data = file.getvalue()
    if not data:
        st.error("This file is empty.")
        return
    if len(data) > fmt.MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"This file is larger than {fmt.MAX_UPLOAD_MB} MB. Please choose a smaller one.")
        return
    ok, document = ui.attempt(api.upload_document, file.name, data, file.type or "application/octet-stream", target)
    if ok:
        st.session_state[f"{prefix}_upload_n"] = n + 1
        st.session_state[open_key] = document["id"]
        ui.flash_ok("Uploaded. Cogniflow is now reading the document.")
        st.rerun()


# -------------------------------------------------------------------- list
def pager(total: int, key: str, page_size: int) -> None:
    pages = max(1, -(-total // page_size))
    if pages > 1:
        st.number_input(f"Page (1–{pages})", min_value=1, max_value=pages, step=1, key=key)


def document_rows(docs: list, open_key: str, prefix: str, activity_titles: Optional[dict] = None) -> None:
    for d in docs:
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 3, 1])
            where = ""
            if activity_titles is not None:
                title = activity_titles.get(d["activity_id"]) if d["activity_id"] else None
                where = f" · In: {fmt.md_escape(title)}" if title else (" · Not in an activity yet" if d["activity_id"] is None else " · In an activity")
            c1.markdown(f"**{fmt.md_escape(d['original_filename'])}**  \n"
                        f"{fmt.human_size(d['file_size'])} · {fmt.format_datetime(d['created_at'])}{where}")
            c2.markdown(f"{fmt.doc_status_label(d['processing_status'])}  \n{fmt.method_text(d)}")
            is_open = st.session_state.get(open_key) == d["id"]
            if c3.button("Close" if is_open else "Open", key=f"{prefix}_view_{d['id']}"):
                if is_open:
                    st.session_state.pop(open_key, None)
                    st.session_state.pop("doc_download", None)
                else:
                    st.session_state[open_key] = d["id"]
                    st.session_state.pop("doc_download", None)
                st.rerun()


# ------------------------------------------------------------------ detail
def detail_panel(doc_id: int, open_key: str, activities: Optional[list] = None, in_workspace: bool = False) -> Optional[str]:
    """Everything about one document. Returns its processing status (so the page can keep polling), or None."""
    ok, doc = ui.attempt(api.get_document, doc_id)
    if not ok:
        if ui.last_error_status() == 404:  # deleted meanwhile
            st.session_state.pop(open_key, None)
            st.session_state.setdefault("flash_ok", "That document no longer exists.")
            st.rerun()
        return None

    status = doc["processing_status"]
    with st.container(border=True):
        st.markdown(f"### 📄 {fmt.md_escape(doc['original_filename'])}")
        st.markdown(f"{fmt.doc_status_label(status)} · {fmt.human_size(doc['file_size'])} · "
                    f"Uploaded {fmt.format_datetime(doc['created_at'])}")
        st.caption(fmt.method_text(doc))
        if doc.get("extraction_method") == "OCR":
            st.caption("OCR confidence is the OCR engine's own estimate (0–100) of how sure it is about the characters. "
                       "It is not a guarantee that the text is correct.")

        _status_block(doc)
        if doc["activity_id"] is None:
            if status in ("PROCESSED", "NEEDS_REVIEW"):
                _suggestions_block(doc, activities or [])
            _manual_assign_block(doc, activities or [])
        else:
            _assigned_block(doc, activities, in_workspace, open_key)
        if status in ("PROCESSED", "NEEDS_REVIEW", "FAILED"):
            _items_block(doc)
            _text_block(doc)
        _actions_block(doc, open_key)
    return status


def _status_block(doc: dict) -> None:
    status = doc["processing_status"]
    doc_id = doc["id"]
    if status in IN_PROGRESS:
        st.info("⏳ Cogniflow is reading this document. This page updates by itself.")
        st.button("🔄 Refresh", key=f"doc_refresh_{doc_id}", on_click=ui.reset_polling)
    elif status == "FAILED":
        st.error(doc.get("error_message") or "Cogniflow could not read this document.")
        st.caption("You can try again, or type the text in below. Cogniflow can still find information in it "
                   "and suggest an activity.")
    elif status == "NEEDS_REVIEW":
        st.warning(doc.get("error_message") or "The text may contain mistakes. Please check it below.")
    if status in ("FAILED", "NEEDS_REVIEW") and st.button("🔁 Process again", key=f"doc_reprocess_{doc_id}"):
        ok, _ = ui.attempt(api.reprocess_document, doc_id)
        if ok:
            ui.reset_polling()
            ui.flash_ok("Processing started again.")
            st.rerun()


def _suggestions_block(doc: dict, activities: list) -> None:
    doc_id = doc["id"]
    suggestions = ui.call(api.list_suggestions, doc_id)
    if suggestions is None:
        return
    pending = [s for s in suggestions if s["status"] == "PENDING"]
    rejected = [s for s in suggestions if s["status"] == "REJECTED"]
    st.markdown("#### 🎯 Suggested activity")
    if not pending:
        st.info("No matching activity was found. Choose one yourself below, or create an activity and recalculate.")
    for s in pending:
        with st.container(border=True):
            st.markdown(f"**Suggested activity: {fmt.md_escape(s['activity_title'])}** ({fmt.nice(s['activity_type'])})")
            st.markdown(f"{fmt.match_label(s['confidence'])} · similarity score {s['score']:.0f}/100")
            st.caption("The score shows how similar the document is to the activity. It is not a probability, "
                       "and nothing is moved until you confirm.")
            with st.expander("Why was this suggested?", expanded=True):
                st.write(fmt.md_escape(s["explanation"]))
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("✅ Confirm", key=f"sugg_ok_{s['id']}", type="primary"):
                ok, _ = ui.attempt(api.confirm_suggestion, doc_id, s["id"])
                if ok:
                    ui.flash_ok(f"The document was added to “{s['activity_title']}”.")
                    st.rerun()
            if c2.button("❌ Reject", key=f"sugg_no_{s['id']}"):
                ok, _ = ui.attempt(api.reject_suggestion, doc_id, s["id"])
                if ok:
                    ui.flash_ok("Suggestion rejected. Nothing was moved. Choose an activity manually below.")
                    st.rerun()
    if rejected:
        st.caption(f"{len(rejected)} suggestion{'s' if len(rejected) != 1 else ''} rejected earlier.")
    if st.button("🔄 Recalculate suggestions", key=f"sugg_refresh_{doc_id}",
                 help="Useful after you create a new activity."):
        ok, _ = ui.attempt(api.refresh_suggestions, doc_id)
        if ok:
            st.rerun()


def _manual_assign_block(doc: dict, activities: list) -> None:
    st.markdown("#### 📂 Choose an activity yourself")
    if not activities:
        st.caption("You have no activities yet. Create one on the Activities page, then come back.")
        return
    titles = {a["id"]: a["title"] for a in activities}
    pick = st.selectbox("Choose activity", list(titles), format_func=titles.get, key=f"doc_assign_pick_{doc['id']}")
    if st.button("Add to this activity", key=f"doc_assign_go_{doc['id']}"):
        ok, _ = ui.attempt(api.assign_document, doc["id"], pick)
        if ok:
            ui.flash_ok(f"The document was added to “{titles[pick]}”.")
            st.rerun()


def _assigned_block(doc: dict, activities: Optional[list], in_workspace: bool, open_key: str) -> None:
    if in_workspace:
        where = "this activity"
    else:
        titles = {a["id"]: a["title"] for a in (activities or [])}
        where = f"“{fmt.md_escape(titles.get(doc['activity_id'], 'an activity'))}”"
    st.markdown(f"📂 In {where}")
    if st.button("Remove from activity", key=f"doc_unassign_{doc['id']}",
                 help="The document is kept; it just no longer belongs to an activity."):
        ok, _ = ui.attempt(api.assign_document, doc["id"], None)
        if ok:
            if in_workspace:
                st.session_state.pop(open_key, None)
            ui.flash_ok("The document was removed from the activity.")
            st.rerun()


def _items_block(doc: dict) -> None:
    st.markdown("#### 🔎 Extracted information")
    st.caption("Found automatically with rules (dates, amounts, names, …). Please check it, and delete anything wrong.")
    items = doc.get("items") or []
    if not items:
        st.caption("Nothing was extracted from this document.")
        return
    order = {t: i for i, t in enumerate(fmt.INFO_ORDER)}
    for item in sorted(items, key=lambda i: (order.get(i["info_type"], len(order)), i["id"])):
        c1, c2 = st.columns([8, 1])
        c1.markdown(f"**{fmt.nice(item['info_type'])}:** {fmt.md_escape(item['value'])}")
        if item.get("context"):
            c1.caption(fmt.md_escape(fmt.short(item["context"], 160)))
        if c2.button("✕", key=f"item_del_{item['id']}", help="Remove this wrong item"):
            ok, _ = ui.attempt(api.delete_document_item, doc["id"], item["id"])
            if ok:
                st.rerun()


def _text_block(doc: dict) -> None:
    status = doc["processing_status"]
    text = doc.get("extracted_text") or ""
    needs_attention = status in ("FAILED", "NEEDS_REVIEW") or not text
    with st.expander("📃 Extracted text (you can correct it)", expanded=needs_attention):
        if not text:
            st.warning("No text is available. Type or paste the document's text below.")
        # the key contains a fingerprint of the saved text, so the box shows the new text after a save or reprocess
        key = f"doc_text_{doc['id']}_{zlib.crc32(text.encode('utf-8'))}"
        edited = st.text_area("Text", value=text, height=260, max_chars=200_000, key=key)
        st.caption("Saving re-extracts the information and recalculates the suggested activity.")
        if st.button("💾 Save corrected text", key=f"doc_text_save_{doc['id']}"):
            if not edited.strip():
                st.error("Text must not be empty.")
            elif edited == text:
                st.info("No changes to save.")
            else:
                ok, _ = ui.attempt(api.correct_document_text, doc["id"], edited)
                if ok:
                    ui.flash_ok("Text saved. The information and suggestions were refreshed.")
                    st.rerun()


def _actions_block(doc: dict, open_key: str) -> None:
    doc_id = doc["id"]
    if st.session_state.get("ws_confirm_document") == doc_id:  # full-width "are you sure?"
        ui.delete_controls("document", doc_id, api.delete_document, (doc_id,),
                           "Delete this document, its extracted information and the stored file? This cannot be undone.",
                           "Document deleted.")
        return  # once deleted, detail_panel() sees a 404 and closes the panel by itself
    a1, a2, _ = st.columns([2, 1, 4])
    if a1.button("⬇️ Prepare download", key=f"doc_prep_{doc_id}"):
        ok, data = ui.attempt(api.download_document, doc_id)
        if ok:
            st.session_state["doc_download"] = {"id": doc_id, "data": data, "name": doc["original_filename"],
                                                "mime": doc["mime_type"]}
    with a2:
        ui.delete_controls("document", doc_id, api.delete_document, (doc_id,), "", "Document deleted.")
    ready = st.session_state.get("doc_download")
    if ready and ready["id"] == doc_id:
        st.download_button("Save the file to your computer", data=ready["data"], file_name=ready["name"],
                           mime=ready["mime"], key=f"doc_save_{doc_id}")
        if str(ready["mime"]).startswith("image/"):
            st.image(ready["data"], caption="The original image (compare it with the OCR text)")
