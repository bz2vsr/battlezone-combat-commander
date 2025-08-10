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
        session_name = b64_to_str(raw.get("n", "")) or None
        tps = raw.get("tps") or raw.get("TPS")
        ver = raw.get("v") or raw.get("Version")
        map_file = raw.get("m") or raw.get("Map")
        mm = raw.get("mm") or ""
        mods = [m for m in str(mm).split(";") if m]
        mod = mods[0] if mods else ("0" if ver else None)
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
            player_name = b64_to_str(p.get("n", "")) or None
            player = {
                "raw_id": pid,
                "steam_id": pid[1:] if isinstance(pid, str) and pid.startswith("S") else None,
                "gog_id": pid[1:] if isinstance(pid, str) and pid.startswith("G") else None,
                "name": player_name,
                "slot": p.get("t"),
                "stats": {
                    "kills": p.get("k"),
                    "deaths": p.get("d"),
                    "score": p.get("s"),
                },
            }
            players.append(player)

        # Derive state from server info mode (si)
        server_info_mode = raw.get("si") or raw.get("ServerInfoMode")
        state = None
        if isinstance(server_info_mode, int):
            if server_info_mode in (1, 2):
                # If any player has non-zero stats, treat as InGame
                any_stats = any(
                    (p or {}).get("k") or (p or {}).get("d") or (p or {}).get("s")
                    for p in raw_players
                )
                state = "InGame" if any_stats else "PreGame"
            elif server_info_mode in (3, 4):
                state = "InGame"
            elif server_info_mode == 5:
                state = "PostGame"

        # NAT type mapping
        nat_type_raw = raw.get("NAT_TYPE") or raw.get("NATType")
        nat_type = None
        if isinstance(nat_type_raw, str):
            code = nat_type_raw
        elif isinstance(nat_type_raw, int):
            code = str(nat_type_raw)
        else:
            code = None
        if code is not None:
            nat_type = {
                "0": "NONE",
                "1": "FULL CONE",
                "2": "ADDRESS RESTRICTED",
                "3": "PORT RESTRICTED",
                "4": "SYMMETRIC",
                "5": "UNKNOWN",
                "6": "DETECTION IN PROGRESS",
                "7": "SUPPORTS UPNP",
            }.get(code, f"[{code}]")

        sess = {
            "id": session_id,
            "source": source,
            "name": session_name,
            "tps": tps,
            "version": ver,
            "player_count": cur_players,
            "nat": nat,
            "state": state,
            "nat_type": nat_type,
            "players": players,
            "map_file": map_file,
            "mod": mod,
            "mods": mods,
        }
        sessions.append(sess)
    return sessions


