from sqlalchemy import text

from app.db import engine
from app.models import Base


def create_all() -> None:
    Base.metadata.create_all(bind=engine)


def ensure_alter_tables() -> None:
    # Add newly introduced columns if they don't exist
    with engine.begin() as conn:
        conn.execute(text(
            """
            ALTER TABLE IF EXISTS sessions
            ADD COLUMN IF NOT EXISTS state VARCHAR(32);
            """
        ))
        conn.execute(text(
            """
            ALTER TABLE IF EXISTS sessions
            ADD COLUMN IF NOT EXISTS nat_type VARCHAR(32);
            """
        ))


if __name__ == "__main__":
    create_all()
    ensure_alter_tables()


