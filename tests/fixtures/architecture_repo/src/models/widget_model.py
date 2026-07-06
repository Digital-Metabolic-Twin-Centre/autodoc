from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Widget(Base):
    __tablename__ = "widgets"

    @classmethod
    def query_all(cls):
        return []
