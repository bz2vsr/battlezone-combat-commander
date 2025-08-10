from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import select

from app.db import session_scope
from app.models import Session, SessionPlayer


GRACE_SECONDS = 120  # consider sessions stale if not seen for this long


def utcnow() -> datetime:
    # store as naive UTC for simplicity; SQLAlchemy will handle TZ if configured
    return datetime.utcnow()


def save_sessions(normalized: List[Dict[str, Any]]) -> Dict[str, int]:
    now = utcnow()
    ids_seen = set()
    created = 0
    updated = 0
    players_upserted = 0

    with session_scope() as db:
        for s in normalized:
            sid = s["id"]
            ids_seen.add(sid)
            row = db.get(Session, sid)
            if row is None:
                row = Session(
                    id=sid,
                    source=s.get("source"),
                    name=s.get("name"),
                    tps=s.get("tps"),
                    version=s.get("version"),
                    level_map_id=None,
                    attributes=None,
                    started_at=now,
                    last_seen_at=now,
                )
                db.add(row)
                created += 1
            else:
                row.name = s.get("name")
                row.tps = s.get("tps")
                row.version = s.get("version")
                row.last_seen_at = now
                updated += 1

            # Upsert minimal session_players (replace for simplicity now)
            db.query(SessionPlayer).filter(SessionPlayer.session_id == row.id).delete()
            for p in s.get("players", []) or []:
                sp = SessionPlayer(
                    session_id=row.id,
                    player_id=None,
                    slot=p.get("slot"),
                    team_id=None,
                    is_host=True if p.get("slot") == 1 else None,
                    stats=p.get("stats"),
                )
                db.add(sp)
                players_upserted += 1

        # Optionally mark stale sessions as ended
        stale_cutoff = now - timedelta(seconds=GRACE_SECONDS)
        q = select(Session).where(Session.ended_at.is_(None), Session.last_seen_at < stale_cutoff)
        for stale in db.scalars(q):
            stale.ended_at = now

    return {"created": created, "updated": updated, "players": players_upserted}


def get_current_sessions(max_age_seconds: int = 120) -> List[Dict[str, Any]]:
    now = utcnow()
    cutoff = now - timedelta(seconds=max_age_seconds)
    out: List[Dict[str, Any]] = []
    with session_scope() as db:
        q = select(Session).where(Session.last_seen_at >= cutoff, Session.ended_at.is_(None)).order_by(Session.last_seen_at.desc())
        for row in db.scalars(q):
            out.append(
                {
                    "id": row.id,
                    "source": row.source,
                    "name": row.name,
                    "tps": row.tps,
                    "version": row.version,
                    "last_seen_at": (row.last_seen_at.isoformat() if row.last_seen_at else None),
                }
            )
    return out


def get_session_detail(session_id: str) -> Dict[str, Any] | None:
    with session_scope() as db:
        row = db.get(Session, session_id)
        if row is None:
            return None
        players: List[Dict[str, Any]] = []
        pq = select(SessionPlayer).where(SessionPlayer.session_id == session_id)
        for sp in db.scalars(pq):
            players.append(
                {
                    "slot": sp.slot,
                    "team_id": sp.team_id,
                    "is_host": sp.is_host,
                    "stats": sp.stats,
                }
            )
        return {
            "id": row.id,
            "source": row.source,
            "name": row.name,
            "tps": row.tps,
            "version": row.version,
            "last_seen_at": (row.last_seen_at.isoformat() if row.last_seen_at else None),
            "players": players,
        }


