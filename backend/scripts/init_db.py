"""Create all tables in the configured PostgreSQL database.

Run from the backend/ folder:   python -m scripts.init_db
Safe to re-run: existing tables are left untouched.
"""
from app.core.database import Base, engine
import app.models  # noqa: F401  (registers all models on Base.metadata)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tables ready:", ", ".join(sorted(Base.metadata.tables)))


if __name__ == "__main__":
    main()
