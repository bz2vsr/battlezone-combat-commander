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
                    map_file=s.get("map_file"),
                    mod_id=s.get("mod"),
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
                row.state = s.get("state")
                row.nat_type = s.get("nat_type")
                row.map_file = s.get("map_file")
                row.mod_id = s.get("mod")
                row.last_seen_at = now
                # If we marked this session as ended previously but we see it again, revive it
                if row.ended_at is not None:
                    row.ended_at = None
                updated += 1

            # Upsert session_players by (session_id, slot) to avoid duplicates
            for p in s.get("players", []) or []:
                slot = p.get("slot")
                existing = db.execute(
                    select(SessionPlayer).where(SessionPlayer.session_id == row.id, SessionPlayer.slot == slot)
                ).scalar_one_or_none()
                payload_stats = {**(p.get("stats") or {}), **({"name": p.get("name")} if p.get("name") else {})}
                if existing is None:
                    sp = SessionPlayer(
                        session_id=row.id,
                        player_id=None,
                        slot=slot,
                        team_id=None,
                        is_host=True if slot == 1 else None,
                        stats=payload_stats,
                    )
                    db.add(sp)
                else:
                    existing.stats = payload_stats
                    existing.is_host = True if slot == 1 else None
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
            players: List[Dict[str, Any]] = []
            pq = select(SessionPlayer).where(SessionPlayer.session_id == row.id).order_by(SessionPlayer.slot)
            for sp in db.scalars(pq):
                players.append({
                    "slot": sp.slot,
                    "is_host": sp.is_host,
                    "name": (sp.stats or {}).get("name"),
                    "score": (sp.stats or {}).get("score"),
                })
            out.append({
                "id": row.id,
                "source": row.source,
                "name": row.name,
                "tps": row.tps,
                "version": row.version,
                "state": row.state,
                "nat_type": row.nat_type,
                "map_file": row.map_file,
                "mod": row.mod_id,
                "last_seen_at": (row.last_seen_at.isoformat() if row.last_seen_at else None),
                "players": players,
            })
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
            "state": row.state,
            "nat_type": row.nat_type,
            "state": row.state,
            "last_seen_at": (row.last_seen_at.isoformat() if row.last_seen_at else None),
            "players": players,
        }


