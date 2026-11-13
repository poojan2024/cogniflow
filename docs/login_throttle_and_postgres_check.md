# Login rate limiting and the PostgreSQL check

Two small additions made after the audit. Both describe only what is implemented.

## A. Login rate limiting (brute-force protection)

**Problem.** Without a limit, a program can try thousands of passwords against `POST /auth/login`.
bcrypt makes each guess slow, but an unlimited number of guesses is still a weakness.

**Rule (sliding window).** If the same email, coming from the same IP address, has failed to log in 5 times within the last
15 minutes, further login attempts are answered with `429 Too Many Requests` and a `Retry-After` header until the oldest of
those failures is more than 15 minutes old. A successful login clears the count. Both numbers can be changed with
`LOGIN_MAX_FAILURES` and `LOGIN_WINDOW_MINUTES` in `backend/.env` (they are not proven values; they are a common, reasonable default).

**Where it is.** `app/services/login_throttle.py` (the rule, pure Python), a few lines in `app/routers/auth.py` (the check
happens *before* any password work, and every failed login is recorded), two settings in `app/core/config.py`.

**Design choices to explain in the viva**
- *Key = email + IP, not just email.* If only the email counted, a stranger could lock a real user out by failing on purpose.
  With the IP included, only the attacker's own address is blocked.
- *Unknown emails are counted exactly like known ones*, and the lock-out message never mentions accounts or passwords, so the
  limiter cannot be used to discover which emails are registered (the login already hides this with equal timing and message).
- *In-memory counters.* Simple and explainable; no new database table, so no schema change. Memory is capped (10,000 keys,
  expired entries are dropped first) so an attacker cannot fill it.
- *Thread safe.* A lock protects the counters, because FastAPI runs normal endpoints in several threads.

**Honest limitations (put these in the Limitations chapter)**
- The counters reset when the server restarts and are not shared between several server processes (Cogniflow runs one).
- Behind a reverse proxy the server sees the proxy's address; proxy-aware IP handling is not implemented.
- It slows simple guessing; it does not stop an attacker who uses many IP addresses.
- Registration is not rate limited.

**Tests.** `backend/tests/test_login_throttle.py` (20 tests of the rule, using a fake clock so nothing really waits) and
`backend/tests/test_login_throttle_api.py` (12 tests through the HTTP API: 6th attempt refused, correct password also refused
while blocked, no password work while blocked, success resets, unknown emails limited the same way, case/space variations of an
email count as one, other accounts unaffected, existing tokens keep working, limits come from settings).
`tests/conftest.py` got one automatic fixture that empties the counters before every test.

## B. PostgreSQL check (`backend/scripts/check_postgres.py`)

**Why.** The automated test-suite uses SQLite so that it needs nothing installed. SQLite and PostgreSQL behave differently in
exactly the places Cogniflow depends on, so the same questions are asked of the real database.

**Run it** (from `backend/`, with `backend/.env` pointing at PostgreSQL):

    python -m scripts.check_postgres

It creates two throw-away users (e-mail ending `@example.invalid`), works only with their rows, and deletes them at the end
(even if a check fails). It never touches other data. Exit code 0 = all passed.

| Check | What it proves |
|---|---|
| Connected to PostgreSQL | the configured database really is PostgreSQL (prints the version) |
| All tables exist | the 12 tables were created |
| Indexes, unique and CHECK constraints exist | the schema objects from the design exist in the database |
| Unique e-mail is enforced | two accounts cannot share an e-mail |
| CHECK constraints refuse bad data | bad activity type, priority 9, importance 0, negative amount are refused by the database itself |
| Foreign keys are enforced | a task cannot point at an activity that does not exist |
| Time zones survive a round trip | a reminder time with a +05:30 offset is read back as the same instant, with a time zone |
| Money is exact | 0.10 + 0.20 + 3000.00 sums to exactly 3000.30 |
| Dates and Unicode survive | ₹, Hindi text and DATE values come back unchanged |
| 1 MB of extracted text survives | large OCR / PDF text is stored completely |
| Search is case-insensitive and literal | "viva" finds "VIVA"; `%` and `_` typed by the user are not wildcards |
| Search never returns another user's data | cross-user isolation holds on PostgreSQL |
| Same file twice for one user is refused | the unique (user, SHA-256) rule works |
| Deleting an activity cascades | a plain SQL DELETE removes its tasks, notes, expenses, reminders and documents |

**For the report.** Paste the table the script prints into the Testing chapter, with the date, PostgreSQL version and
the sentence "executed on the author's machine". Do not report a result you did not obtain: if a check fails, the failure is
a finding (fix it or list it as a limitation).

| Check | Expected | Actual (from your run) |
|---|---|---|
| ... | PASS | (paste) |
