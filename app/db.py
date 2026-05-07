from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine


def create_sqlite_engine(db_url: str) -> object:
    # sqlite: connect_args is needed for multithreaded TestClient usage
    return create_engine(db_url, connect_args={"check_same_thread": False})


def init_db(engine: object) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(engine: object) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

