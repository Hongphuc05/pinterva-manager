from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str | None = None):
    url = database_url or get_settings().validate_database_url()
    return create_engine(url, pool_pre_ping=True)


def build_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(
        bind=build_engine(database_url),
        autoflush=False,
        expire_on_commit=False,
    )
