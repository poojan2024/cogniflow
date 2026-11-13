# Contextual AI Assistant (Gemini)

Code: `routers/assistant.py`, `services/{assistant_context,assistant_core,keyword_answer,gemini_client}.py`.
The assistant is an optional helper. Every other feature works without it.

## 1. What it does
Each activity has its own assistant. A question is answered only from that activity's stored data: documents (extracted text and facts),
notes, tasks with deadlines and priorities, reminders and expenses. It cannot change any data; it only answers.

## 2. Flow of `POST /activities/{id}/assistant/ask`
1. The activity must belong to the logged-in user (otherwise 404). A per-user limit (default 30 questions per hour) is checked (429).
2. The context is built from this activity only. Each item has a label such as `[Task 5]` or `[Doc 12]`. A size limit (24,000 characters) applies.
3. Mode `auto`: the strict system rules plus the context plus the question are sent to Gemini. Mode `local`: nothing is sent; keyword search answers.
4. The answer is checked: references such as `[Task 5]` must exist in the data that was sent; invented ones are listed in `unverified_references`.
5. The question and answer are stored (`ai_interactions`) and a line is added to the activity history.

## 3. How it is kept from inventing answers
The rules tell the model to use only the supplied data, to reply with the fixed sentence "I don't have that information in this activity's data."
when the data does not contain the answer, to cite labels, and to treat document text as data, not instructions. The temperature is low (0.2).
The response says `has_information: false` when that sentence is returned. These are safeguards, not guarantees (see limits).

## 4. When Gemini fails
| Situation | What the user gets | Stored status |
|---|---|---|
| No usable key configured | notice "not configured" + keyword answer | UNAVAILABLE |
| Invalid key / forbidden | notice to check GEMINI_API_KEY + keyword answer | UNAVAILABLE |
| Unknown model / rejected request | notice to check GEMINI_MODEL + keyword answer | UNAVAILABLE |
| Rate limit, network problem or timeout, server error (one retry) | notice + keyword answer | UNAVAILABLE |
| Answer blocked, empty or unreadable | notice + keyword answer | FAILED |
| Any unexpected error in the AI layer | generic notice + keyword answer (details only in the server log) | FAILED |
No error ever shows a stack trace, the key or the provider's response.

## 5. Keyword (non-AI) answers
`keyword_answer.py` never writes new sentences. Words such as "tasks", "documents", "expenses", "deadline", "reminders" select every item of that kind;
other words are matched against item text (rarer words weigh more). It lists the matching stored lines (with a short quote from notes or documents)
or says that nothing was found. Used as the fallback and as the privacy-friendly `local` mode.

## 6. Configuration (backend/.env, set by you; the project never writes this file)
```
GEMINI_API_KEY=your-key-from-aistudio.google.com
GEMINI_MODEL=gemini-2.5-flash          # optional
AI_MAX_QUESTIONS_PER_HOUR=30           # optional
```
The Gemini REST API is called with the Python standard library, so no extra package is needed.

## 7. Endpoints
`POST /activities/{id}/assistant/ask`, `GET /activities/{id}/assistant/history`, `DELETE /activities/{id}/assistant/history/{entry}`,
`GET /activities/{id}/assistant/context` (what would be sent), `GET /assistant/status` (is Gemini configured; never shows the key).

## 8. Testing
`test_gemini_client.py` (14 tests against a local fake Gemini server: request shape, key only in a header, every error kind, retry, timeout),
`test_assistant_core.py` and `test_keyword_answer.py` (25 pure tests), `test_assistant_api.py` (API behaviour with fake AI clients: grounding,
privacy of the prompt, every failure kind, logging, ownership, limits). Tests never contact Google.
**Not tested:** a real call to Google with a real key; the first real question must be tried by hand (see the README).

## 9. Limits (state these in the report)
- Answers depend on Gemini and can be wrong or incomplete even with the rules; citation checking only proves a cited item exists.
- Long activities are cut to the size limit, so some questions about old data may get "not available".
- Prompt injection from document text is reduced, not eliminated.
- Keyword mode has no understanding of meaning (no synonyms).
- Conversation memory is not kept: each question is answered on its own.

## 10. Viva answers
- **Is Cogniflow just a chatbot?** No. Authentication, activities, documents with OCR, the weighted priority algorithm, reminders, search and the dashboard work without any AI; the assistant is one optional part.
- **What data does the AI see?** Only the selected activity's stored data (see `privacy_and_data_protection.md`), and you can preview it.
- **What if Gemini is down?** The user is told why and gets a keyword answer built from the same data.
- **How do you stop it inventing?** Strict rules, an explicit "not available" answer, mandatory citations that are checked against the real data, and a low temperature. It still can't be guaranteed.
