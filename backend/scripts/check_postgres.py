"""Checks that Cogniflow really behaves correctly on YOUR PostgreSQL database.

The automated test-suite runs on SQLite (fast, nothing to install). SQLite and PostgreSQL differ in important details
(time zones, exact decimals, case-insensitive search, foreign keys, CHECK constraints), so this script repeats the
database-dependent checks on the real thing and prints a PASS / FAIL table you can use as evidence in the report.

Run from the backend/ folder, with backend/.env pointing at PostgreSQL:

    python -m scripts.check_postgres

What it does to your data: it creates two throw-away users whose e-mail ends in "@example.invalid", works only with
their rows, and deletes them (and everything under them) at the end, even if a check fails. It never reads or changes
any other user's data. It also runs Base.metadata.create_all(), which only adds missing tables (same as init_db).
Exit code: 0 = everything passed, 1 = at least one check failed, 2 = the configured database is not PostgreSQL.
"""
import hashlib
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.database import DB_BACKEND, Base, SessionLocal, engine
from app.models import Activity, Document, Expense, Note, Reminder, Task, User
from app.services.search import SEARCH_TYPES, search_user_data

TAG = uuid.uuid4().hex[:10]
EMAIL_1 = f"pgcheck-{TAG}-1@example.invalid"
EMAIL_2 = f"pgcheck-{TAG}-2@example.invalid"
ctx = {}      # ids created during setup
results = []  # (name, passed, detail)


def check(name, function):
    try:
        detail = function()
        results.append((name, True, detail or ""))
    except Exception as exc:  # a failing check must not stop the others
        results.append((name, False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:180] if str(exc) else ''}"))


def expect_refused(add_rows):
    """The database itself must refuse the rows that add_rows(db) tries to write."""
    with SessionLocal() as db:
        try:
            add_rows(db)
            db.flush()  # sends the INSERT; PostgreSQL has to say no
        except IntegrityError:
            db.rollback()
            return "refused by the database, as expected"
        db.rollback()
    raise AssertionError("the database ACCEPTED data it should have refused")


def new_activity(db, user_id, title="PG check activity", **extra):
    activity = Activity(user_id=user_id, title=title, activity_type="PROJECT", **extra)
    db.add(activity)
    db.flush()
    return activity


# ------------------------------------------------------------------ the checks
def c_connection():
    with SessionLocal() as db:
        version = db.scalar(text("select version()"))
    return version.split(",")[0]


def c_tables():
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    missing = sorted(set(Base.metadata.tables) - existing)
    if missing:
        raise AssertionError("missing tables: " + ", ".join(missing))
    return f"{len(Base.metadata.tables)} tables present"


def c_schema_objects():
    inspector = inspect(engine)
    index_names = {i["name"] for i in inspector.get_indexes("activities")}
    unique_names = {u["name"] for u in inspector.get_unique_constraints("documents")}
    check_names = {c["name"] for c in inspector.get_check_constraints("activities")}
    problems = []
    if "ix_activities_user_status" not in index_names:
        problems.append("index ix_activities_user_status")
    if "uq_documents_user_sha256" not in unique_names:
        problems.append("unique constraint uq_documents_user_sha256")
    if not {"ck_activities_type", "ck_activities_priority"} <= check_names:
        problems.append("CHECK constraints on activities")
    if problems:
        raise AssertionError("not found in the database: " + "; ".join(problems))
    return "indexes, unique and CHECK constraints exist"


def setup():
    with SessionLocal() as db:
        u1 = User(email=EMAIL_1, full_name="PG Check One", password_hash="not-a-real-hash")
        u2 = User(email=EMAIL_2, full_name="PG Check Two", password_hash="not-a-real-hash")
        db.add_all([u1, u2])
        db.flush()
        a1 = new_activity(db, u1.id)
        a2 = new_activity(db, u2.id, title="Other user's activity")
        db.commit()
        ctx.update(user1=u1.id, user2=u2.id, act1=a1.id, act2=a2.id)
    return "two throw-away users and activities created"


def c_unique_email():
    return expect_refused(lambda db: db.add(User(email=EMAIL_1, full_name="Duplicate", password_hash="x")))


def c_check_constraints():
    outcomes = [
        expect_refused(lambda db: db.add(Activity(user_id=ctx["user1"], title="x", activity_type="NOT_A_TYPE"))),
        expect_refused(lambda db: db.add(Activity(user_id=ctx["user1"], title="x", activity_type="PROJECT", priority=9))),
        expect_refused(lambda db: db.add(Task(activity_id=ctx["act1"], title="x", importance=0))),
        expect_refused(lambda db: db.add(Expense(activity_id=ctx["act1"], description="x", amount=Decimal("-1"), expense_date=date.today()))),
    ]
    return f"{len(outcomes)} invalid rows refused (bad type, bad priority, bad importance, negative amount)"


def c_foreign_keys():
    return expect_refused(lambda db: db.add(Task(activity_id=-1, title="orphan")))


def c_timezone():
    stored = datetime(2030, 1, 1, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))  # 09:00 in India
    with SessionLocal() as db:
        reminder = Reminder(activity_id=ctx["act1"], title="tz check", remind_at=stored)
        db.add(reminder)
        db.commit()
        reminder_id = reminder.id
    with SessionLocal() as db:
        back = db.get(Reminder, reminder_id)
        if back.remind_at.tzinfo is None:
            raise AssertionError("the time came back WITHOUT a time zone")
        if back.remind_at != stored:
            raise AssertionError(f"different instant: stored {stored.isoformat()}, read {back.remind_at.isoformat()}")
        if back.created_at.tzinfo is None:
            raise AssertionError("created_at came back without a time zone")
    return f"{stored.isoformat()} read back as {back.remind_at.isoformat()} (same instant)"


def c_decimal_money():
    with SessionLocal() as db:
        for description, amount in (("a", "0.10"), ("b", "0.20"), ("c", "3000.00")):
            db.add(Expense(activity_id=ctx["act1"], description=description, amount=Decimal(amount), expense_date=date.today()))
        db.commit()
    with SessionLocal() as db:
        total = db.scalar(select(func.sum(Expense.amount)).where(Expense.activity_id == ctx["act1"]))
    if not isinstance(total, Decimal) or total != Decimal("3000.30"):
        raise AssertionError(f"total is {total!r}, expected Decimal('3000.30')")
    return f"0.10 + 0.20 + 3000.00 = {total} (exact Decimal; float arithmetic would give {0.1 + 0.2 + 3000.0!r})"


def c_dates_and_unicode():
    title = "₹ मासिक खर्च – ‘quotes’ ✓"
    with SessionLocal() as db:
        note = Note(activity_id=ctx["act1"], title=title, content="₹3,000 होटल")
        task = Task(activity_id=ctx["act1"], title="dates", due_date=date(2031, 2, 28))
        db.add_all([note, task])
        db.commit()
        note_id, task_id = note.id, task.id
    with SessionLocal() as db:
        if db.get(Note, note_id).title != title:
            raise AssertionError("Unicode text (₹, Hindi) was changed by the database")
        if db.get(Task, task_id).due_date != date(2031, 2, 28):
            raise AssertionError("a date column changed")
    return "₹ and Hindi text and DATE values round-trip unchanged"


def c_large_text():
    text_1mb = ("Cogniflow document text. " * 40_000)[:1_000_000]
    with SessionLocal() as db:
        doc = Document(user_id=ctx["user1"], original_filename="big.txt", stored_filename=f"pgcheck-{uuid.uuid4().hex}.txt",
                       mime_type="text/plain", file_size=len(text_1mb), sha256=hashlib.sha256(text_1mb.encode()).hexdigest(),
                       extracted_text=text_1mb)
        db.add(doc)
        db.commit()
        doc_id = doc.id
    with SessionLocal() as db:
        if db.get(Document, doc_id).extracted_text != text_1mb:
            raise AssertionError("1 MB of extracted text did not come back identical")
    return "1,000,000 characters of extracted text stored and read back identically"


def c_search_ilike():
    with SessionLocal() as db:
        db.add_all([
            Note(activity_id=ctx["act1"], title="Viva preparation", content="Prepare for the VIVA exam"),
            Note(activity_id=ctx["act1"], title="Discount 100% off", content="x"),
            Note(activity_id=ctx["act1"], title="Discount 100 percent", content="x"),
            Note(activity_id=ctx["act1"], title="file_name list", content="x"),
            Note(activity_id=ctx["act1"], title="fileXname list", content="x"),
        ])
        db.commit()
    with SessionLocal() as db:
        def titles(query):
            return sorted(h.title for h in search_user_data(db, ctx["user1"], query, SEARCH_TYPES, 25) if h.type == "notes")
        if "Viva preparation" not in titles("viva"):
            raise AssertionError("search is not case-insensitive (looking for 'viva')")
        if titles("100%") != ["Discount 100% off"]:
            raise AssertionError(f"'%' was treated as a wildcard: {titles('100%')}")
        if titles("file_name") != ["file_name list"]:
            raise AssertionError(f"'_' was treated as a wildcard: {titles('file_name')}")
    return "case-insensitive; '%' and '_' are matched literally"


def c_search_isolation():
    with SessionLocal() as db:
        db.add(Note(activity_id=ctx["act2"], title="Secret zebra plan", content="zebra"))
        db.add(Note(activity_id=ctx["act1"], title="Public zebra plan", content="zebra"))
        db.commit()
    with SessionLocal() as db:
        mine = [h.title for h in search_user_data(db, ctx["user1"], "zebra", SEARCH_TYPES, 25)]
        theirs = [h.title for h in search_user_data(db, ctx["user2"], "zebra", SEARCH_TYPES, 25)]
    if "Secret zebra plan" in mine:
        raise AssertionError("user 1's search returned user 2's note")
    if "Public zebra plan" in theirs:
        raise AssertionError("user 2's search returned user 1's note")
    return "each user finds only their own notes"


def c_document_unique_hash():
    digest = hashlib.sha256(uuid.uuid4().bytes).hexdigest()

    def add_rows(db):
        for _ in range(2):
            db.add(Document(user_id=ctx["user1"], original_filename="same.pdf", stored_filename=f"pgcheck-{uuid.uuid4().hex}.pdf",
                            mime_type="application/pdf", file_size=1, sha256=digest))
            db.flush()  # the second flush must fail

    return expect_refused(add_rows)


def c_cascade_delete():
    with SessionLocal() as db:
        activity = new_activity(db, ctx["user1"], title="cascade check")
        task = Task(activity_id=activity.id, title="t")
        db.add(task)
        db.flush()
        db.add_all([
            Note(activity_id=activity.id, title="n"),
            Expense(activity_id=activity.id, description="e", amount=Decimal("1.00"), expense_date=date.today()),
            Reminder(activity_id=activity.id, task_id=task.id, title="r", remind_at=datetime(2030, 1, 1, tzinfo=timezone.utc)),
            Document(user_id=ctx["user1"], activity_id=activity.id, original_filename="c.txt",
                     stored_filename=f"pgcheck-{uuid.uuid4().hex}.txt", mime_type="text/plain", file_size=1,
                     sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest()),
        ])
        db.commit()
        activity_id = activity.id
    with SessionLocal() as db:
        db.execute(delete(Activity).where(Activity.id == activity_id))  # a plain SQL DELETE: only the database can cascade
        db.commit()
    with SessionLocal() as db:
        left = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model).where(model.activity_id == activity_id))
            for model in (Task, Note, Expense, Reminder, Document)
        }
    if any(left.values()):
        raise AssertionError(f"rows left behind after deleting the activity: {left}")
    return "deleting an activity removed its tasks, notes, expenses, reminders and documents"


def cleanup():
    with SessionLocal() as db:
        db.execute(delete(User).where(User.email.in_([EMAIL_1, EMAIL_2])))  # plain SQL: cascades through the database
        db.commit()
    with SessionLocal() as db:
        left = db.scalar(select(func.count()).select_from(User).where(User.email.in_([EMAIL_1, EMAIL_2])))
        orphans = db.scalar(select(func.count()).select_from(Activity).where(Activity.id.in_([ctx.get("act1", -1), ctx.get("act2", -1)])))
    if left or orphans:
        raise AssertionError(f"test data was not fully removed (users: {left}, activities: {orphans})")
    return "throw-away users and everything under them deleted"


def main() -> int:
    if DB_BACKEND != "postgresql":
        print(f"The configured database is '{DB_BACKEND}', not PostgreSQL. Set DATABASE_URL in backend/.env first.")
        return 2
    print(f"Database: {engine.url.render_as_string(hide_password=True)}\n")
    try:
        Base.metadata.create_all(bind=engine)  # only adds missing tables
    except Exception as exc:  # most likely: PostgreSQL is not running, or the URL / password / database name is wrong
        print("Could not connect to the database or create the tables.")
        print(f"  {type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}")
        print("Check that PostgreSQL is running and that DATABASE_URL in backend/.env is correct.")
        return 1

    check("Connected to PostgreSQL", c_connection)
    check("All tables exist", c_tables)
    check("Indexes, unique and CHECK constraints exist", c_schema_objects)
    check("Test data created", setup)
    if "user1" in ctx:
        for name, function in (
            ("Unique e-mail is enforced", c_unique_email),
            ("CHECK constraints refuse bad data", c_check_constraints),
            ("Foreign keys are enforced", c_foreign_keys),
            ("Time zones survive a round trip", c_timezone),
            ("Money is exact (NUMERIC, Decimal)", c_decimal_money),
            ("Dates and Unicode (₹, Hindi) survive", c_dates_and_unicode),
            ("1 MB of extracted text survives", c_large_text),
            ("Search is case-insensitive and literal", c_search_ilike),
            ("Search never returns another user's data", c_search_isolation),
            ("Same file twice for one user is refused", c_document_unique_hash),
            ("Deleting an activity cascades (database level)", c_cascade_delete),
        ):
            check(name, function)
    check("Test data removed", cleanup)

    width = max(len(name) for name, _, _ in results)
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [name for name, passed, _ in results if not passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed" + (f"  -  FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        try:  # last-resort cleanup if something unexpected happened half-way
            with SessionLocal() as _db:
                _db.execute(delete(User).where(User.email.in_([EMAIL_1, EMAIL_2])))
                _db.commit()
        except Exception:
            pass
    sys.exit(code)
