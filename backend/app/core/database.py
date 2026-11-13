"""SQLAlchemy engine, session factory and declarative base.

The application database is PostgreSQL (DATABASE_URL in backend/.env).
SQLite is used ONLY by the automated tests, which set DATABASE_URL=sqlite:// themselves (see tests/conftest.py).
"""
import logging
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger("cogniflow")


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_url = make_url(_settings.database_url)  # raises a clear error if the URL is malformed
DB_BACKEND = _url.get_backend_name()  # "postgresql" for the real app, "sqlite" in tests

# check_same_thread is a SQLite-only option. It must never be passed to PostgreSQL (psycopg2 rejects it).
_connect_args = {"check_same_thread": False} if DB_BACKEND == "sqlite" else {}

engine = create_engine(_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)

logger.info("Database backend: %s (%s)", DB_BACKEND, _url.render_as_string(hide_password=True))


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory():
    """FastAPI dependency returning the session factory. Background tasks must open their own session,
    because the request session is closed once the response has been sent. Tests override this."""
    return SessionLocal