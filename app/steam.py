from __future__ import annotations

import itertools
from typing import Dict, Iterable, Optional, List

import requests

from app.config import settings
from app.db import session_scope
from app.models import Identity, Player


STEAM_SUMMARIES = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"


def chunked(iterable: Iterable[str], size: int) -> Iterable[List[str]]:
    it = iter(iterable)
    while True:
        buf = list(itertools.islice(it, size))
        if not buf:
            return
        yield buf


def enrich_steam_identities(steam_ids: Iterable[str]) -> Dict[str, int]:
    """Fetch Steam player summaries for given 64-bit IDs and upsert Identity/Player rows.

    Returns a dict with counts for logging.
    """
    api_key = settings.steam_api_key
    if not api_key:
        return {"updated": 0}
    updated = 0
    ids = [sid for sid in (steam_ids or []) if sid]
    if not ids:
        return {"updated": 0}

    with session_scope() as db:
        for batch in chunked(ids, 100):
            try:
                resp = requests.get(
                    STEAM_SUMMARIES,
                    params={"key": api_key, "steamids": ",".join(batch)},
                    timeout=8.0,
                )
                resp.raise_for_status()
                players = (resp.json() or {}).get("response", {}).get("players", [])
            except Exception:
                players = []
            for p in players:
                sid = str(p.get("steamid") or "").strip()
                if not sid:
                    continue
                persona = p.get("personaname")
                avatar = p.get("avatarfull") or p.get("avatar")
                profile = p.get("profileurl")

                ident = db.query(Identity).filter(Identity.provider == "steam", Identity.external_id == sid).first()
                if ident is None:
                    player = Player(display_name=persona, avatar_url=avatar)
                    db.add(player)
                    db.flush()
                    ident = Identity(player_id=player.id, provider="steam", external_id=sid, profile_url=profile, raw=None)
                    db.add(ident)
                    updated += 1
                else:
                    # update linked player
                    player = db.get(Player, ident.player_id) if ident.player_id else None
                    if player:
                        if persona and player.display_name != persona:
                            player.display_name = persona
                            updated += 1
                        if avatar and player.avatar_url != avatar:
                            player.avatar_url = avatar
                            updated += 1
                    if profile and ident.profile_url != profile:
                        ident.profile_url = profile
                        updated += 1

    return {"updated": updated}


