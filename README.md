# Cogniflow – AI-Assisted Personal Digital Organizer

Activity-based organizer: one activity = one contextual workspace (documents, tasks, notes, expenses, reminders, history).
**Status:** backend complete and covered by an automated test suite (run `pytest -v` in `backend/`).
Frontend (Streamlit): all four planned parts are done. Part 1 (login that survives a browser refresh, Dashboard, Activities),
Part 2 (activity workspace: Tasks with priority-score breakdown and manual override, Notes, Expenses, Reminders),
Part 3 (Documents: upload, OCR / text extraction status, extracted information, suggested activity with confirm / reject,
manual text correction) and Part 4 (contextual AI assistant with keyword fallback, activity history, global search,
notifications).

Security hardening: login rate limiting (5 failed logins per email + IP in 15 minutes), see docs/login_throttle_and_postgres_check.md.

Design notes: docs/priority_algorithm.md, docs/document_pipeline.md, docs/activity_matching.md, docs/ai_assistant.md,
docs/privacy_and_data_protection.md, docs/reminders_search_dashboard.md.

## Layout
```
backend/   FastAPI API  (app/core, app/routers, app/schemas, app/services, app/models.py, tests/, scripts/)
frontend/  Streamlit UI  (app.py, auth_page.py, session.py, ui.py, api_client.py, formatting.py, views/, tests/)
legacy/    original prototype, kept for reference
```

## 1. PostgreSQL
Install PostgreSQL, then in `psql` (as the postgres user):
```sql
CREATE USER cogniflow_user WITH PASSWORD 'choose-a-password';
CREATE DATABASE cogniflow OWNER cogniflow_user;
```

## 2. Backend
Run all backend commands from the `backend/` folder.
```
python -m venv venv
venv\Scripts\activate            (Windows)   |   source venv/bin/activate   (Linux/macOS)
pip install -r requirements-dev.txt
copy .env.example .env           (Windows)   |   cp .env.example .env
```
Edit `.env`: set `DATABASE_URL` and a real `JWT_SECRET`
(`python -c "import secrets; print(secrets.token_urlsafe(48))"`). The app refuses to start with a weak or placeholder secret.
```
python -m scripts.init_db        # creates the tables
uvicorn app.main:app --reload    # API on http://127.0.0.1:8000  (docs at /docs)
```

### OCR prerequisite (Tesseract)
OCR needs the Tesseract program, which is not a Python package. Windows: install it (for example the UB Mannheim build)
and check with `tesseract --version`. The app finds it on PATH or at `C:\Program Files\Tesseract-OCR\tesseract.exe`;
otherwise set `TESSERACT_CMD` in `backend/.env`. Without it everything else still works and image documents are marked FAILED
with a clear message (use Reprocess after installing).

## 3. Frontend
Start the backend first. Then, in a second terminal, from the `frontend/` folder:
```
pip install -r frontend/requirements.txt      (or: pip install -r requirements.txt from inside frontend/)
streamlit run app.py                           # opens http://localhost:8501
```
Optional settings (environment variables): `COGNIFLOW_API_URL` (default `http://127.0.0.1:8000`) and
`COGNIFLOW_PERSIST_LOGIN=0` (turns the refresh-proof login off; a refresh then logs you out).

**Stay logged in after refresh.** The JWT is also stored in a browser cookie (package `streamlit-cookies-controller`) that
expires when the token expires. On refresh the token is re-checked with `GET /auth/me`. Honest trade-off: a cookie written
from the browser cannot be HttpOnly, so JavaScript on the page could read it; Cogniflow never renders user text as raw HTML,
and tokens live 60 minutes by default. Logout deletes the cookie.

**Pages (Part 1):** Dashboard (counts, attention banners, upcoming deadlines, high-priority tasks with the explanation of the
score, charts, recent documents / activity / reminders, expenses) and Activities (search, type / status / sort filters,
paging, create, edit, delete with confirmation).

**Activity workspace (Part 2):** press "Open workspace" on an activity. A selector at the top switches between
- Tasks: filters, the calculated priority with score and explanation, a "Score breakdown & manual override" panel
  (the four weighted factors as bars, points per factor, total and level), mark complete / reopen / start, edit, delete.
  The score is calculated by the backend algorithm only; the screen just displays it.
- Notes: add, search, edit, delete.
- Expenses: add, edit, delete, exact total from the backend, category chart.
- Reminders: add, edit, delete, optional link to a task, scheduled vs triggered. Times use the computer's time zone.
- Documents: upload straight into this activity and manage its documents (same screens as the Documents page below).

**Documents page (Part 3):** the main demo screen.
1. Upload a PDF / PNG / JPG / TXT (max 10 MB; the type and size are checked again by the backend from the real file content).
   Leave "Put it in" on "Let Cogniflow suggest an activity" to see the suggestion flow.
2. The page refreshes itself while the document is being read (text extraction, or OCR for scans and photos) and stops by
   itself after about 80 seconds; the "Refresh" button starts it again.
3. The details show the status, how the text was obtained (and the OCR engine's own confidence), the extracted information
   (dates, deadlines, amounts, names, ...), and the extracted text, which you can correct by hand. If OCR failed or is poor,
   you are told, nothing is invented, and you can type the text in or process the file again.
4. "Suggested activity" shows the activity, a similarity score (not a probability) and the reasons. Nothing is moved until you
   press Confirm. Reject keeps the document where it is, and you can then choose an activity yourself.
5. Download is two steps (prepare, then save) so files are only fetched when you ask. Delete asks for confirmation.

Text that comes out of a document (file name, extracted text and items) is untrusted, so it is escaped before it is shown:
a malicious PDF cannot make the page load a remote image or show a fake link.
Limits: the "choose an activity" lists show your first 100 activities.

**AI assistant (Part 4, workspace section "Assistant").** It answers only from the open activity's own data and is an extra:
every other feature works without it.
- Modes: "Ask Gemini" (this activity's tasks, notes, expenses and document text are sent to Google together with the question)
  or "Keyword search only" (nothing leaves the computer). If Gemini is not configured, the section says so and defaults to
  keyword search. "Show exactly what data would be used" previews what Gemini would receive.
- If Gemini is unavailable, rate-limited or fails, the backend answers by keyword search and the screen says why.
- Each answer shows who produced it, the stored items it is based on, and a warning for any reference that is not in the data.
  AI text is untrusted and escaped before display. Past questions can be reviewed and deleted.

**History** (workspace section): a newest-first timeline of what happened in the activity (uploads, suggestions confirmed or
rejected, tasks, notes, expenses, reminders, questions asked).

**Search** (sidebar): one box over activities, documents, extracted information, notes, tasks and expenses, with a choice of
places to look in. "Open" jumps to the activity (on the right section) or the document.

**Notifications** (sidebar): reminders whose time has passed appear when you open the page; mark one or all as read, delete
(with confirmation). There is no background scheduler and no unread badge in the sidebar (the Dashboard shows the count).

## 4. Tests
Backend, from `backend/`:  `pytest -v`   (uses in-memory SQLite, no PostgreSQL needed)
Login rate limiting only: `pytest tests/test_login_throttle.py tests/test_login_throttle_api.py -v`

**PostgreSQL check** (the tests above run on SQLite, this one runs on your real PostgreSQL). From `backend/`, with `.env` pointing at PostgreSQL:
`python -m scripts.check_postgres`  - prints a PASS / FAIL table and removes its own throw-away data. What each check proves and how to
use the output in the report: docs/login_throttle_and_postgres_check.md

Frontend, from `frontend/`:  `python -m unittest discover -s tests -t . -v`   (needs only `requests` and `pandas`; Streamlit itself is
replaced by a small stand-in, so these tests check the page logic and API calls, not how the page looks in a browser)

## Security notes (current phase)
- Passwords: bcrypt hashes only. JWT: HS256, signed with `JWT_SECRET` from `.env`, short expiry, algorithm pinned on decode.
- `.env` is git-ignored; never commit it.
- Logout = the client discards its token (JWTs are stateless).

## API overview (Phase 3)
All endpoints except `/auth/register`, `/auth/login` and `/health` need `Authorization: Bearer <token>`.
Open http://127.0.0.1:8000/docs, click **Authorize**, log in with email + password, and try them.

| Endpoint | Purpose |
|---|---|
| `POST/GET /activities` | create; list with `q`, `activity_type`, `status`, `sort`, `page`, `page_size` |
| `GET/PATCH/DELETE /activities/{id}` | view, edit, delete (deletes everything inside) |
| `GET /activities/{id}/history` | audit trail (paginated) |
| `/activities/{id}/tasks` | task CRUD with calculated `priority` (score, level, explanation); `?status_filter=`, `?priority_level=`, `?sort=due\|priority`; `manual_priority` override |
| `/activities/{id}/notes` | note CRUD, `?q=` search |
| `/activities/{id}/expenses` | expense CRUD, response includes the exact total |
| `POST /documents` | upload (multipart `file`, optional `activity_id`); returns at once, processing runs in the background |
| `GET /documents`, `GET /documents/{id}` | list (filters, pagination) / detail with extracted text and items |
| `GET /documents/{id}/download` | original file (owner only) |
| `PATCH /documents/{id}/text`, `POST /documents/{id}/reprocess`, `PATCH /documents/{id}`, `DELETE ...` | correct text, reprocess, assign to activity, delete |
| `GET/POST /documents/{id}/suggestions`, `POST .../{sid}/confirm`, `POST .../{sid}/reject` | explainable activity suggestions; nothing moves until you confirm |
| `/activities/{id}/reminders` | reminder CRUD (time must include a time zone offset) |
| `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | notifications; loading them triggers due reminders |
| `GET /search?q=` | global search over your own activities, documents, extracted info, notes, tasks, expenses |
| `GET /dashboard` | one-call summary: counts, deadlines, high-priority tasks, recent items, expenses |
| `POST /activities/{id}/assistant/ask`, `GET .../history`, `GET .../context`, `GET /assistant/status` | contextual assistant: answers only from the activity's data; `mode: "local"` sends nothing to Gemini |

Ownership rule: every nested route loads the activity with `WHERE id = ? AND user_id = <logged-in user>`;
another user's activity or item returns 404, so its existence is not revealed.

## Troubleshooting
- **Always start the API with `uvicorn app.main:app --reload` from `backend/`.** `uvicorn main:app` would load the OLD prototype
  files (`legacy/`), which cannot talk to PostgreSQL. If old `main.py`, `database.py`, `models.py`, `ocr.py`, `ai_service.py`
  or `app.py` still sit directly inside `backend/`, move them into `legacy/`.
- Check the connection: open http://127.0.0.1:8000/health/db - it must show `"database": "postgresql"`.
- If your PostgreSQL password contains `@ : / # %`, URL-encode it in `DATABASE_URL` (for example `@` becomes `%40`).
- The tests use their own in-memory SQLite database; the application itself always uses PostgreSQL.

## AI assistant setup (optional)
Without a key the assistant still works in keyword mode. To enable Gemini, add this line to your own `backend/.env` (the patch files
never contain or replace `.env`):
```
GEMINI_API_KEY=your-key-from-aistudio.google.com
```
Restart the API, then check `GET /assistant/status` shows `"ai_configured": true`. Read `docs/privacy_and_data_protection.md` first:
questions in mode `auto` send the selected activity's stored data to Google.

## Before you submit or upload to GitHub
Delete these (they are machine-specific or private, and are already in `.gitignore`):
`backend/venv/`, every `__pycache__/`, `.pytest_cache/` (root and backend), `cogniflow.db` (root and backend - old prototype
tables, not the current schema), `backend/uploads/` (real uploaded documents), and your private `backend/.env`.
`backend/.env.example` is the template: copy it to `backend/.env` and fill in your real `DATABASE_URL` and `JWT_SECRET`.
The `legacy/` folder is the original prototype; keep it out of the final submission or mention it only as history.
