from __future__ import annotations
import os
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = os.environ.get(
    "AFE_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "assets.db")
)
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


class Base(DeclarativeBase):
    pass


ENGINE = create_engine(f"sqlite:///{os.path.abspath(DB_PATH)}", echo=False)
SESSION_FACTORY = sessionmaker(ENGINE, expire_on_commit=False)


@event.listens_for(ENGINE, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    from ai_film_editor_nodes.lib.persistence import orm_models  # noqa: F401
    Base.metadata.create_all(ENGINE)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    with SESSION_FACTORY() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
