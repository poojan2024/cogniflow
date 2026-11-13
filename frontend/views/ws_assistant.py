"""Assistant section of the activity workspace.

The assistant answers only from THIS activity's stored data. It is an extra, not a requirement: with Gemini switched off,
unavailable or rate-limited, the backend answers with a keyword search over the same data and says so, and every other
part of Cogniflow keeps working. Nothing is sent to Google unless the user leaves the mode on "Ask Gemini".

An AI answer is untrusted text (a document could contain instructions meant to trick the model into writing an image
link, for example), so it is escaped before it is shown.
"""
import streamlit as st

import api_client as api
import formatting as fmt
import ui

MODE_LABELS = {
    "auto": "Ask Gemini (this activity's data is sent to Google)",
    "local": "Keyword search only (nothing leaves your computer)",
}
EXAMPLES = [
    "What documents have I uploaded?",
    "What is the deadline?",
    "Which tasks are still pending?",
    "Summarize the important information from the uploaded documents.",
]
LAST_KEY = "ws_ai_last"
SOURCE_TEXT = {"gemini": "🤖 Answered by Gemini", "keyword": "🔎 Answered by keyword search (no AI)"}


def _ask(activity_id: int, question: str, mode: str) -> None:
    with st.spinner("Looking through this activity's data…"):
        ok, answer = ui.attempt(api.ask_assistant, activity_id, question, mode)
    if ok:
        st.session_state[LAST_KEY] = answer


def _answer_card(a: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**You asked:** {fmt.md_escape(a['question'])}")
        st.caption(SOURCE_TEXT.get(a["source"], a["source"]))
        if a.get("notice"):
            problem = a["ai_status"] in ("failed", "unavailable") or a.get("unverified_references")
            (st.warning if problem else st.info)(fmt.md_escape(a["notice"]))
        st.markdown(fmt.md_block(a["answer"]))
        if not a["has_information"]:
            st.caption("This activity's data does not seem to contain that information.")
        if a.get("unverified_references"):
            st.warning("These references are not in your data, so that part of the answer may be wrong: "
                       + fmt.md_escape(", ".join(a["unverified_references"])))
        if a.get("references"):
            with st.expander(f"Based on {len(a['references'])} item{'s' if len(a['references']) != 1 else ''} from this activity"):
                for r in a["references"]:
                    st.markdown(f"- **{fmt.md_escape(r['label'])}**: {fmt.md_escape(r['title'])}")
        if a.get("context_truncated"):
            st.caption("Only part of this activity's data fitted into the size limit, so the answer may be incomplete.")


def _show_context(activity_id: int) -> None:
    data = ui.call(api.assistant_context, activity_id)
    if data is None:
        return
    st.caption(f"{data['char_count']:,} characters from {len(data['sources'])} items"
               + (" (shortened to fit the limit)" if data["truncated"] else "")
               + ". Only this is sent, together with your question, and only in Gemini mode.")
    st.text_area("Data used to answer", value=data["text"], height=220, disabled=True, key="ws_ai_ctx_text")


def _history(activity_id: int) -> None:
    page = int(st.session_state.get("ws_ai_page", 1))
    data = ui.call(api.assistant_history, activity_id, page=page, page_size=5)
    if data is None:
        return
    total = data["total"]
    if total == 0:
        return
    st.subheader(f"Earlier questions ({total})")
    for item in data["items"]:
        source = "keyword" if item["source"] == "keyword" else "Gemini"
        with st.expander(f"{fmt.short(item['question'], 80)}  ·  {fmt.format_datetime(item['created_at'])}"):
            st.caption(f"Answered by {source}" + (f" · {fmt.md_escape(item['note'])}" if item.get("note") else ""))
            st.markdown(fmt.md_block(item.get("answer") or "(no answer was stored)"))
            ui.delete_controls("ai", item["id"], api.delete_interaction, (activity_id, item["id"]),
                               "Delete this question and answer? This cannot be undone.", "Question deleted.")
    pages = max(1, -(-total // 5))
    if pages > 1:
        st.number_input(f"Page (1–{pages})", min_value=1, max_value=pages, step=1, key="ws_ai_page")


def render(activity_id: int) -> None:
    status = ui.call(api.assistant_status)
    configured = bool(status and status["ai_configured"])
    if status is None:
        pass  # the error was already shown; the keyword mode may still work
    elif configured:
        st.info(f"Gemini is set up on this server (model {status['model']}). Up to {status['max_questions_per_hour']} "
                "questions per hour. Cogniflow works fully without it.")
    else:
        st.info("Gemini is not set up on this server, so questions are answered by keyword search over this activity's "
                "data. Everything else in Cogniflow works normally.")

    modes = list(MODE_LABELS)
    mode = st.radio("How should your question be answered?", modes, index=0 if configured else 1,
                    format_func=MODE_LABELS.get, key="ws_ai_mode")
    if mode == "auto" and configured:
        st.caption("🔒 Privacy: in this mode the text of this activity's tasks, notes, expenses and documents is sent to "
                   "Google Gemini with your question. Choose keyword search to keep everything on your computer.")

    if st.checkbox("Show exactly what data would be used", key="ws_ai_show_ctx"):
        _show_context(activity_id)

    st.markdown("**Try a question:**")
    cols = st.columns(2)
    for i, example in enumerate(EXAMPLES):
        if cols[i % 2].button(example, key=f"ws_ai_ex_{i}"):
            _ask(activity_id, example, mode)

    with st.form("ws_ai_form", clear_on_submit=True):
        question = st.text_area("Your question", max_chars=1000, height=80, key="ws_ai_question",
                                placeholder="For example: What is the project deadline?")
        asked = st.form_submit_button("Ask", type="primary")
    if asked:
        if not question.strip():
            st.error("Please type a question.")
        else:
            _ask(activity_id, question.strip(), mode)

    last = st.session_state.get(LAST_KEY)
    if last:
        _answer_card(last)
    _history(activity_id)
