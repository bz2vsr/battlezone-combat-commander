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
        # Ensure unique constraints and indexes (idempotent where possible)
        conn.execute(text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_identities_provider_external'
              ) THEN
                ALTER TABLE IF EXISTS identities
                ADD CONSTRAINT uq_identities_provider_external UNIQUE (provider, external_id);
              END IF;
            END $$;
            """
        ))
        conn.execute(text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_session_players_session_slot'
              ) THEN
                ALTER TABLE IF EXISTS session_players
                ADD CONSTRAINT uq_session_players_session_slot UNIQUE (session_id, slot);
              END IF;
            END $$;
            """
        ))


if __name__ == "__main__":
    create_all()
    ensure_alter_tables()


