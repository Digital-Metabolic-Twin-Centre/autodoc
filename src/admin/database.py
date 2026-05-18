from sqlalchemy import create_engine
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
