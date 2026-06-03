from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from admin.settings import DATABASE_URL


class Base(DeclarativeBase):
    """Base SQLAlchemy model class."""


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from admin import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_run_record_columns()


def _ensure_run_record_columns() -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("run_records")}
    missing_columns: list[str] = []
    if "progress_percent" not in existing_columns:
        missing_columns.append("ALTER TABLE run_records ADD COLUMN progress_percent FLOAT")
    if "progress_message" not in existing_columns:
        missing_columns.append("ALTER TABLE run_records ADD COLUMN progress_message VARCHAR(255)")

    if not missing_columns:
        return

    with engine.begin() as connection:
        for statement in missing_columns:
            connection.execute(text(statement))
