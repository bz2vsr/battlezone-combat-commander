from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, BigInteger, ForeignKey, DateTime, Integer, JSON, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    display_name: Mapped[Optional[String]] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[Optional[String]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_identities_provider_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    profile_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    nat_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    level_map_id: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    map_file: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mod_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionPlayer(Base):
    __tablename__ = "session_players"
    __table_args__ = (
        UniqueConstraint("session_id", "slot", name="uq_session_players_session_slot"),
        Index("ix_session_players_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), nullable=True)
    slot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_host: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    stats: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class Mod(Base):
    __tablename__ = "mods"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class Level(Base):
    __tablename__ = "levels"
    __table_args__ = (
        UniqueConstraint("mod_id", "map_file", name="uq_levels_mod_map"),
    )

    id: Mapped[str] = mapped_column(String(256), primary_key=True)  # f"{mod_id}:{map_file}"
    mod_id: Mapped[str] = mapped_column(String(32), index=True)
    map_file: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


