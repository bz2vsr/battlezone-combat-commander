from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.util_base64 import decode_raknet_guid, b64_to_str


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
        sess = {
            "id": session_id,
            "source": source,
            "name": name,
            "tps": tps,
            "version": ver,
            "player_count": cur_players,
            "nat": nat,
        }
        sessions.append(sess)
    return sessions


