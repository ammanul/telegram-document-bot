from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import url as sa_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from server.app.config import DATABASE_URL

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable must be set for Postgres access.")


def _ensure_database_exists(database_url: str) -> None:
    """Ensure the target Postgres database exists.

    If the database specified in ``database_url`` does not exist, attempt to
    create it by connecting to the default ``postgres`` database on the same
    server. This is safe to call multiple times; concurrent calls may race,
    but only one will succeed in creating the database.
    """

    try:
        url_obj = sa_url.make_url(database_url)
    except Exception:
        # If the URL cannot be parsed, just let the normal engine creation fail later.
        return

    db_name = url_obj.database
    if not db_name:
        return

    admin_url = url_obj.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)

    try:
        with admin_engine.connect() as conn:
            # Check if database already exists
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if exists:
                return

            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except SQLAlchemyError:
        # If creation fails (e.g. due to race or permissions), we simply
        # proceed; subsequent connections will surface any real issues.
        return


_ensure_database_exists(DATABASE_URL)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False, class_=Session)

Base = declarative_base()


def get_session() -> Session:
    """Return a new SQLAlchemy session.

    Callers are responsible for closing the session (e.g. using a context manager).
    """
    return SessionLocal()


def get_session_ctx() -> Generator[Session, None, None]:
    """Context manager-style generator for use with ``with`` blocks.

    Example:
        with get_session_ctx() as session:
            ...
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
