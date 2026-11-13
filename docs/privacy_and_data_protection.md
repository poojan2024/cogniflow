# Privacy and Data Protection

This document describes only what Cogniflow actually does today.

## 1. What is stored, and where
| Data | Where |
|---|---|
| Account: e-mail, name, bcrypt password hash | PostgreSQL (`users`) |
| Activities, tasks, notes, expenses, reminders, notifications, activity history | PostgreSQL |
| Uploaded files (PDF, PNG, JPG, TXT) | server disk, `backend/uploads/<user id>/<random name>` (outside any served folder) |
| Extracted text, extracted facts, OCR confidence, suggestions | PostgreSQL |
| Assistant questions and answers | PostgreSQL (`ai_interactions`), plus a short line in the activity history (first 120 characters of the question and which engine answered) |

Everything belongs to one user. Every endpoint checks ownership; another user's data returns "not found". Deleting an activity deletes its
tasks, notes, expenses, reminders, history and assistant conversations. Files are not encrypted at rest (a stated limitation).

## 2. Protection in place
bcrypt password hashing; short-lived JWTs signed with a secret from `.env`; per-request ownership checks; content-based file validation, size
limit, random file names and a path-traversal check; files only available through an authenticated download endpoint; generic error messages
(no stack traces); secrets only in `backend/.env` (git-ignored). The Gemini API key is held as a secret value, sent only in a request header to
Google, and never written to logs, responses or error messages (tests check this).

## 3. Which external services receive data
| Feature | External service? |
|---|---|
| Login, activities, tasks, notes, expenses, reminders, search, dashboard | None |
| Text extraction, OCR (Tesseract), information extraction, activity suggestions, priority scores | None. All of it runs on your own server |
| **Assistant question in mode `auto` with a Gemini key configured** | **Google Gemini** (the only external service) |
| Assistant question in mode `local`, or no Gemini key configured, or Gemini unavailable | None |

## 4. Exactly what is sent to Gemini (one request per question in mode `auto`)
**Sent:**
1. The fixed assistant rules (the system prompt).
2. The question you typed (up to 1000 characters).
3. The stored data of the ONE selected activity, built by `assistant_context.py`, at most 24,000 characters in total:
   - the activity's title, type, status, priority, start date, deadline and description;
   - up to 50 tasks (title, status, due date, importance, calculated priority, short description);
   - up to 20 reminders (title, time, whether triggered);
   - the expense total and up to 100 expenses (description, category, amount, date);
   - up to 30 notes (title and up to 1500 characters of content each);
   - up to 10 documents: file name, status, the extracted facts (dates, amounts, names, places) and up to 3000 characters of the extracted text each;
   - today's date.
4. The API key, in a request header, to authenticate to Google.

**Not sent:** other activities; other users' data; your e-mail, name, password hash or login token; the original uploaded files (images and PDFs
themselves; only the text already extracted from them); anything at all in mode `local`.

You can see the exact activity data for any activity before asking: `GET /activities/{id}/assistant/context`.
If the data is larger than the limit, the later parts (documents, then notes) are left out and the answer says that some data was not shown.

## 5. What Google does with it
Cogniflow cannot control this. How Google stores or uses content sent to the Gemini API depends on Google's current terms and on the account
plan used for the key, and those terms change. Read Google's current Gemini API terms before using the assistant with sensitive documents. If a
document must not leave your machine, do not use mode `auto` for that activity (use mode `local`), or do not configure a Gemini key.

## 6. Your controls
- Mode `local` on every question: nothing is sent anywhere.
- No `GEMINI_API_KEY` on the server: the assistant never contacts Google.
- Preview of the data before asking (`/assistant/context`).
- Delete any stored question and answer (`DELETE /activities/{id}/assistant/history/{entry}`), or delete the activity.
- Rate limit of 30 questions per user per hour (setting `AI_MAX_QUESTIONS_PER_HOUR`) so a key cannot be used up by accident.

## 7. Known risks and limits
- **Wrong answers.** Gemini can still make mistakes. The assistant is told to answer only from the data and to cite items; Cogniflow checks that
  every cited item really exists in the data sent and warns about invented references, but it cannot verify that an answer is correct.
- **Prompt injection.** Text inside an uploaded document could contain instructions aimed at the AI. The rules tell the model to treat all
  activity data as untrusted data, and the answer is only shown, never acted on (the assistant cannot change any data). This reduces the risk but
  does not remove it.
- Stored questions and answers may themselves contain personal information, and they are not encrypted at rest.
- There is no consent screen per activity; the user's choice is the mode and whether the server has a key.
