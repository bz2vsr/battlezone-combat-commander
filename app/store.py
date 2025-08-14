from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import select

from app.db import session_scope
from app.models import Session, SessionPlayer, Mod, Level, SessionSnapshot, Identity, Player


# Reduce grace so killed sessions fall off quickly in UI
GRACE_SECONDS = 12  # consider sessions stale if not seen for this long


def utcnow() -> datetime:
    # store as naive UTC for simplicity; SQLAlchemy will handle TZ if configured
    return datetime.utcnow()


def save_sessions(normalized: List[Dict[str, Any]]) -> Dict[str, int]:
    now = utcnow()
    ids_seen = set()
    created = 0
    updated = 0
    players_upserted = 0
    levels_upserted = 0

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
                    attributes=s.get("attributes"),
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
                if s.get("attributes") is not None:
                    row.attributes = s.get("attributes")
                row.last_seen_at = now
                # If we marked this session as ended previously but we see it again, revive it
                if row.ended_at is not None:
                    row.ended_at = None
                updated += 1

            # Upsert session_players by (session_id, slot) to avoid duplicates
            # Upsert session players by slot; remove any stale rows not present now
            current_slots = set()
            for p in s.get("players", []) or []:
                slot = p.get("slot")
                if slot is None:
                    continue
                current_slots.add(slot)
                existing = db.execute(
                    select(SessionPlayer).where(SessionPlayer.session_id == row.id, SessionPlayer.slot == slot)
                ).scalar_one_or_none()
                payload_stats = {**(p.get("stats") or {}), **({"name": p.get("name")} if p.get("name") else {})}
                if p.get("steam_id"):
                    payload_stats["steam_id"] = p.get("steam_id")
                if existing is None:
                    sp = SessionPlayer(
                        session_id=row.id,
                        player_id=None,
                        slot=slot,
                        team_id=p.get("team_id"),
                        is_host=True if slot in (1, 6) else None,
                        stats=payload_stats,
                    )
                    db.add(sp)
                else:
                    existing.stats = payload_stats
                    existing.is_host = True if slot in (1, 6) else None
                    existing.team_id = p.get("team_id")
                players_upserted += 1
            # delete players whose slots disappeared
            if current_slots:
                db.query(SessionPlayer).filter(
                    SessionPlayer.session_id == row.id,
                    ~SessionPlayer.slot.in_(current_slots),
                ).delete(synchronize_session=False)

            # Append a snapshot
            snap = SessionSnapshot(
                session_id=row.id,
                observed_at=now,
                player_count=len(current_slots),
                state=row.state,
                map_file=row.map_file,
                mod_id=row.mod_id,
            )
            db.add(snap)

            # Upsert level and mod records minimally
            mod_id = s.get("mod")
            map_file = s.get("map_file")
            if mod_id:
                if db.get(Mod, mod_id) is None:
                    db.add(Mod(id=mod_id))
                if map_file:
                    lid = f"{mod_id}:{map_file}"
                    if db.get(Level, lid) is None:
                        db.add(Level(id=lid, mod_id=mod_id, map_file=map_file))
                        levels_upserted += 1

        # Optionally mark stale sessions as ended
        stale_cutoff = now - timedelta(seconds=GRACE_SECONDS)
        q = select(Session).where(Session.ended_at.is_(None), Session.last_seen_at < stale_cutoff)
        for stale in db.scalars(q):
            stale.ended_at = now

    return {"created": created, "updated": updated, "players": players_upserted, "levels": levels_upserted}


def get_current_sessions(max_age_seconds: int = 10) -> List[Dict[str, Any]]:
    now = utcnow()
    cutoff = now - timedelta(seconds=max_age_seconds)
    out: List[Dict[str, Any]] = []
    with session_scope() as db:
        q = select(Session).where(Session.last_seen_at >= cutoff, Session.ended_at.is_(None)).order_by(Session.last_seen_at.desc())
        for row in db.scalars(q):
            players: List[Dict[str, Any]] = []
            pq = select(SessionPlayer).where(SessionPlayer.session_id == row.id).order_by(SessionPlayer.slot)
            steam_ids: List[str] = []
            for sp in db.scalars(pq):
                info = {
                    "slot": sp.slot,
                    "is_host": sp.is_host,
                    "name": (sp.stats or {}).get("name"),
                    "score": (sp.stats or {}).get("score"),
                    "team_id": sp.team_id,
                }
                sid = (sp.stats or {}).get("steam_id")
                if sid:
                    info["steam_id"] = str(sid)
                    steam_ids.append(str(sid))
                players.append(info)

            # Batch-enrich Steam identities for this session
            if steam_ids:
                from sqlalchemy import select as _select
                mapping: Dict[str, Dict[str, Any]] = {}
                rows = db.execute(
                    _select(Identity, Player)
                    .where(Identity.provider == "steam", Identity.external_id.in_(steam_ids))
                    .join(Player, Identity.player_id == Player.id, isouter=True)
                ).all()
                for ident, player in rows:
                    mapping[str(ident.external_id)] = {
                        "id": str(ident.external_id),
                        "profile": ident.profile_url,
                        "nickname": (player.display_name if player else None),
                        "avatar": (player.avatar_url if player else None),
                    }
                for p in players:
                    sid = p.get("steam_id")
                    if sid and sid in mapping:
                        p["steam"] = mapping[sid]
            # Enriched level/mod if present
            level_name = None
            level_image = None
            if row.mod_id and row.map_file:
                lid = f"{row.mod_id}:{row.map_file}"
                lvl = db.get(Level, lid)
                if lvl:
                    level_name = lvl.name
                    level_image = lvl.image_url
            # Mod name/image/url
            mod_name = None
            mod_image = None
            mod_url = None
            if row.mod_id:
                mod_row = db.get(Mod, row.mod_id)
                if mod_row:
                    mod_name = mod_row.name
                    mod_image = mod_row.image_url
                try:
                    if row.mod_id and int(row.mod_id) > 0:
                        mod_url = f"http://steamcommunity.com/sharedfiles/filedetails/?id={row.mod_id}"
                except Exception:
                    mod_url = None
            # Fallback placeholder asset if level image missing
            placeholder_img = "/static/assets/placeholder-thumbnail-200x200.svg"
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
                "mod_name": mod_name,
                "mod_details": {"name": mod_name, "image": mod_image, "url": mod_url} if (mod_name or mod_image or mod_url) else None,
                "attributes": row.attributes,
                "level": {"name": level_name or (row.map_file or "(unknown)"), "image": level_image or placeholder_img} if (row.map_file or level_name or level_image) else None,
                "last_seen_at": (row.last_seen_at.isoformat() if row.last_seen_at else None),
                "players": players,
            })
    return out


def get_history_summary(minutes: int = 60) -> List[Dict[str, Any]]:
    """Return per-minute aggregates for the last N minutes.

    For each minute bucket: number of distinct sessions observed and total players.
    """
    now = utcnow()
    from datetime import timedelta
    cutoff = now - timedelta(minutes=max(1, minutes))
    points: Dict[str, Tuple[set, int]] = {}
    with session_scope() as db:
        q = select(SessionSnapshot).where(SessionSnapshot.observed_at >= cutoff).order_by(SessionSnapshot.observed_at)
        for row in db.scalars(q):
            bucket = row.observed_at.replace(second=0, microsecond=0).isoformat()
            if bucket not in points:
                points[bucket] = (set(), 0)
            s, p = points[bucket]
            if row.session_id:
                s.add(row.session_id)
            if isinstance(row.player_count, int):
                p += row.player_count
            points[bucket] = (s, p)
    # Convert to sorted list
    out: List[Dict[str, Any]] = []
    for t in sorted(points.keys()):
        s, p = points[t]
        out.append({"t": t, "sessions": len(s), "players": p})
    return out


def get_maps_summary(hours: int = 24) -> List[Dict[str, Any]]:
    """Top maps by distinct sessions and total player-count over the last N hours."""
    from datetime import timedelta
    now = utcnow()
    cutoff = now - timedelta(hours=max(1, hours))
    agg: Dict[str, Dict[str, Any]] = {}
    with session_scope() as db:
        q = select(SessionSnapshot).where(SessionSnapshot.observed_at >= cutoff)
        for row in db.scalars(q):
            key = row.map_file or "(unknown)"
            bucket = agg.setdefault(key, {"map_file": key, "sessions": set(), "players": 0})
            if row.session_id:
                bucket["sessions"].add(row.session_id)
            if isinstance(row.player_count, int):
                bucket["players"] += row.player_count
    # Convert sets to counts and sort
    out = []
    for v in agg.values():
        out.append({"map_file": v["map_file"], "sessions": len(v["sessions"]), "players": v["players"]})
    out.sort(key=lambda x: (x["sessions"], x["players"]), reverse=True)
    return out[:25]


def get_mods_summary(hours: int = 24) -> List[Dict[str, Any]]:
    """Top mods by distinct sessions and total player-count over the last N hours."""
    from datetime import timedelta
    now = utcnow()
    cutoff = now - timedelta(hours=max(1, hours))
    agg: Dict[str, Dict[str, Any]] = {}
    with session_scope() as db:
        q = select(SessionSnapshot).where(SessionSnapshot.observed_at >= cutoff)
        for row in db.scalars(q):
            key = row.mod_id or "0"
            bucket = agg.setdefault(key, {"mod": key, "sessions": set(), "players": 0})
            if row.session_id:
                bucket["sessions"].add(row.session_id)
            if isinstance(row.player_count, int):
                bucket["players"] += row.player_count
    out = []
    for v in agg.values():
        out.append({"mod": v["mod"], "sessions": len(v["sessions"]), "players": v["players"]})
    out.sort(key=lambda x: (x["sessions"], x["players"]), reverse=True)
    return out[:25]


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


def get_mod_catalog() -> Dict[str, Dict[str, Any]]:
    """Return a mapping of mod_id -> {name, image, url} for all known mods."""
    catalog: Dict[str, Dict[str, Any]] = {}
    with session_scope() as db:
        for m in db.query(Mod).all():
            url: str | None = None
            try:
                if m.id and int(m.id) > 0:
                    url = f"http://steamcommunity.com/sharedfiles/filedetails/?id={m.id}"
            except Exception:
                url = None
            catalog[m.id] = {
                "name": m.name,
                "image": m.image_url,
                "url": url,
            }
    return catalog


