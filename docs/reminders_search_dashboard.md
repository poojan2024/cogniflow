# Reminders, Notifications, Global Search and Dashboard

Code: `routers/{reminders,notifications,search,dashboard}.py`, `services/{reminders,search,snippets,dashboard,dashboard_calc}.py`.
No AI is used in any of these features.

## 1. Reminders and notifications
- A reminder belongs to one activity and may be linked to one of that activity's tasks (task deadline, appointment, event, important date).
- **Time zones:** the reminder time must include an offset (for example `2026-10-12T09:00:00+05:30`). It is converted to UTC and stored in UTC, so
  there is no hidden "server time zone" assumption. Times without an offset are rejected.
- **Trigger logic (no scheduler):** whenever the user loads `/notifications` or `/dashboard`, each of THEIR reminders whose time has passed and
  that has not gone off yet is marked triggered and exactly one notification is created. Loading again never creates a duplicate.
  Rescheduling a reminder arms it again. Deleting a reminder keeps its notification.
- Notifications can be listed (paged, unread only), marked read, marked all read and deleted. Each belongs to one user.
- Limitation: a reminder only becomes a notification when the app is next opened; there is no e-mail, SMS or push message and no background worker.
  (Two requests arriving at the very same moment could in theory both create the notification; this is not guarded.)

## 2. Global search
`GET /search?q=...` searches the user's own activities (title, description), documents (file name, extracted text), extracted information
(value, source line), notes (title, content), tasks (title, description) and expenses (description, category).
`types=` limits the kinds, `limit=` (default 10, maximum 25) applies per type. Each hit has a type, a title, a snippet around the match and the
activity it belongs to. `%` and `_` typed by the user are matched literally. Activities and documents are filtered by `user_id`, everything else
through the owning activity, so another user's data cannot appear.
Method and limits: case-insensitive substring search (SQL ILIKE). There is no relevance ranking, no stemming and no typo tolerance. That is fine for
personal-organizer data sizes; a PostgreSQL trigram or full-text index would be the next step for large data.

## 3. Dashboard (`GET /dashboard`)
One call returns:
| Part | Meaning |
|---|---|
| overview | total and active activities, activities per status, open (pending or in progress) and completed tasks, overdue open tasks, open tasks per priority level (manual overrides included) |
| upcoming_deadlines | open activities and open tasks dated today to 30 days ahead, earliest first (at most 10) |
| high_priority_tasks | the 5 most urgent CRITICAL / HIGH open tasks with score and explanation, from the weighted priority algorithm |
| recent_documents, recent_activity | latest 5 documents and 10 history events |
| upcoming_reminders | next 5 reminders that have not gone off |
| expenses | exact total across all activities, by category (top 6) and by activity (top 5) |
| attention | unread notifications, documents waiting for an activity decision, documents that FAILED or NEED_REVIEW |
"Today" is the server's date. At most 2000 open tasks are scored (safety limit). The calculations (`dashboard_calc.py`) are pure functions with unit tests.

## 4. Testing
`tests/test_dashboard_helpers.py` (11 unit tests: deadlines, task summary, snippets). API tests: `test_reminders_api.py`, `test_search_api.py`,
`test_dashboard_api.py`, including ownership checks that another user's reminders, notifications, search hits and numbers never appear.
Results are reported only after the tests are actually run.

## 5. Viva answers
- **How do reminders work without a scheduler?** Due reminders are converted to notifications when the user opens the app; this avoids a background worker. The cost is no push or e-mail delivery.
- **Why store UTC?** One unambiguous time for every user; the offset is supplied by the client.
- **How does search stay private?** Every query is restricted to the logged-in user's own rows, and tests check another user cannot find the data.
