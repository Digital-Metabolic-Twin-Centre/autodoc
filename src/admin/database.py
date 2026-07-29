import json

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from admin.settings import DATABASE_URL
from utils.redaction import redact_secrets


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
    scrub_sensitive_run_payloads()
    redact_leaked_secrets_from_run_records()


def scrub_sensitive_run_payloads() -> int:
    from admin.models import RunRecord

    scrubbed_count = 0
    with SessionLocal() as session:
        runs = session.query(RunRecord).filter(RunRecord.request_payload.is_not(None)).all()
        for run in runs:
            try:
                payload = json.loads(run.request_payload or "")
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or "token" not in payload:
                continue
            payload.pop("token", None)
            run.request_payload = json.dumps(payload, default=str, indent=2)
            session.add(run)
            scrubbed_count += 1
        if scrubbed_count:
            session.commit()
    return scrubbed_count


def redact_leaked_secrets_from_run_records() -> int:
    """
    Retroactively scrub any credentials already stored in run error messages.

    Older runs may have persisted a git-clone error containing an embedded
    access token before redaction was added; this cleans up rows already on
    disk in addition to preventing new leaks.

    Args:
        None.
    Returns:
        int: Number of run records that were rewritten.

    """
    from admin.models import RunRecord

    scrubbed_count = 0
    with SessionLocal() as session:
        runs = session.query(RunRecord).filter(RunRecord.error_message.is_not(None)).all()
        for run in runs:
            redacted = redact_secrets(run.error_message)
            if redacted != run.error_message:
                run.error_message = redacted
                session.add(run)
                scrubbed_count += 1
        if scrubbed_count:
            session.commit()
    return scrubbed_count


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
