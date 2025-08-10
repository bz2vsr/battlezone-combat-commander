from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.util_base64 import decode_raknet_guid, b64_to_str, sanitize_text


def normalize_bzcc_sessions(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    sessions: List[Dict[str, Any]] = []
    items = payload.get("GET") or []
    for raw in items:
        nat = raw.get("g") or raw.get("NATNegID")
        if not nat or nat == "XXXXXXX@XX":
            continue
        try:
            nat_hex = decode_raknet_guid(nat).hex()
        except Exception:
            nat_hex = nat
        source = raw.get("proxySource") or "Rebellion"
        session_id = f"{source}:{nat_hex}"
        name = b64_to_str(raw.get("n", "")) or None
        tps = raw.get("tps") or raw.get("TPS")
        ver = raw.get("v") or raw.get("Version")
        cur_players = 0
        if isinstance(raw.get("pl"), list):
            cur_players = len([p for p in raw["pl"] if p is not None])
        # Players
        players = []
        raw_players = raw.get("pl") or []
        for idx, p in enumerate(raw_players):
            if p is None:
                continue
            pid = p.get("i")
            name = b64_to_str(p.get("n", "")) or None
            player = {
                "raw_id": pid,
                "steam_id": pid[1:] if isinstance(pid, str) and pid.startswith("S") else None,
                "gog_id": pid[1:] if isinstance(pid, str) and pid.startswith("G") else None,
                "name": name,
                "slot": p.get("t"),
                "stats": {
                    "kills": p.get("k"),
                    "deaths": p.get("d"),
                    "score": p.get("s"),
                },
            }
            players.append(player)

        sess = {
            "id": session_id,
            "source": source,
            "name": name,
            "tps": tps,
            "version": ver,
            "player_count": cur_players,
            "nat": nat,
            "players": players,
        }
        sessions.append(sess)
    return sessions


