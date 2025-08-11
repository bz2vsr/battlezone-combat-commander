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
        # Create mods and levels tables if not present
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS mods (
              id VARCHAR(32) PRIMARY KEY,
              name VARCHAR(256),
              image_url VARCHAR(512)
            );
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS levels (
              id VARCHAR(256) PRIMARY KEY,
              mod_id VARCHAR(32),
              map_file VARCHAR(128),
              name VARCHAR(256),
              image_url VARCHAR(512)
            );
            """
        ))
        conn.execute(text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_levels_mod_map'
              ) THEN
                ALTER TABLE levels ADD CONSTRAINT uq_levels_mod_map UNIQUE (mod_id, map_file);
              END IF;
            END $$;
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS session_snapshots (
              id SERIAL PRIMARY KEY,
              session_id VARCHAR(128),
              observed_at TIMESTAMPTZ DEFAULT now(),
              player_count INTEGER,
              state VARCHAR(32),
              map_file VARCHAR(128),
              mod_id VARCHAR(32)
            );
            CREATE INDEX IF NOT EXISTS ix_session_snapshots_session_time ON session_snapshots(session_id, observed_at);
            """
        ))
        conn.execute(text(
            """
            ALTER TABLE IF EXISTS sessions
            ADD COLUMN IF NOT EXISTS nat_type VARCHAR(32);
            """
        ))
        conn.execute(text(
            """
            ALTER TABLE IF EXISTS sessions
            ADD COLUMN IF NOT EXISTS map_file VARCHAR(128);
            """
        ))
        conn.execute(text(
            """
            ALTER TABLE IF EXISTS sessions
            ADD COLUMN IF NOT EXISTS mod_id VARCHAR(32);
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


