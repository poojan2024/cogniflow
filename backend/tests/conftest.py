"""Test setup. Tests use an in-memory SQLite database, so PostgreSQL is not needed to run them.

Environment variables are set BEFORE the app is imported, because settings are read at import time.
"""
import atexit
import os
import shutil
import tempfile

_UPLOAD_DIR = tempfile.mkdtemp(prefix="cogniflow_test_uploads_")  # uploaded test files never touch backend/uploads
atexit.register(shutil.rmtree, _UPLOAD_DIR, ignore_errors=True)

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["UPLOAD_DIR"] = _UPLOAD_DIR
os.environ["JWT_SECRET"] = "test-secret-only-for-pytest-0123456789abcdef"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["GEMINI_API_KEY"] = ""  # real environment variables beat backend/.env, so tests never use a real key

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.database import Base, get_db, get_session_factory  # noqa: E402
from app.core.deps import get_ai_client  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_login_throttle():
    """Failed-login counters live in memory for the whole test run; start every test with an empty table."""
    from app.services.login_throttle import login_throttle

    login_throttle.reset()
    yield
    login_throttle.reset()


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # SQLite ignores FKs unless asked; PostgreSQL always enforces them
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        db_session.expire_all()  # background tasks write through another session; never serve stale rows
        yield db_session

    def override_session_factory():
        # The pipeline's background task opens its own session, on the same in-memory test database.
        return sessionmaker(bind=db_session.get_bind(), autoflush=False)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = override_session_factory
    app.dependency_overrides[get_ai_client] = lambda: None  # default: no AI; assistant tests install their own fakes
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---- helpers shared by test files -------------------------------------------------
PASSWORD = "Passw0rdOK"


def register(client, email="alice@example.com", password=PASSWORD, name="Alice"):
    return client.post("/auth/register", json={"email": email, "full_name": name, "password": password})


def login(client, email="alice@example.com", password=PASSWORD):
    return client.post("/auth/login", data={"username": email, "password": password})


def auth_header(client, email="alice@example.com", password=PASSWORD):
    token = login(client, email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def make_activity(client, headers, **overrides):
    body = {"title": "MCA Final-Year Project", "activity_type": "PROJECT", "priority": 4}
    body.update(overrides)
    res = client.post("/activities", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture()
def alice(client):
    """Headers of a registered, logged-in user (alice)."""
    register(client, "alice@example.com", name="Alice")
    return auth_header(client, "alice@example.com")


@pytest.fixture()
def bob(client):
    """Headers of a second, different user (bob)."""
    register(client, "bob@example.com", name="Bob")
    return auth_header(client, "bob@example.com")
