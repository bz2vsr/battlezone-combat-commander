from __future__ import annotations

import contextlib
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextlib.contextmanager
def session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


