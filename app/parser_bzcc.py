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
        # Decode session name from base64; preserve punctuation like '?'
        _n = raw.get("n", "")
        # Only use base64-decoded text; if decode fails, leave None (avoid leaking raw base64)
        # Trim decoded title and collapse internal runs of whitespace
        title = b64_to_str(_n)
        if title:
            title = " ".join(title.split())
        session_name = title or None
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
            player_name_raw = b64_to_str(p.get("n", "")) or None
            player_name = player_name_raw
            slot_val = p.get("t")
            team_val = None
            if isinstance(slot_val, int):
                if 1 <= slot_val <= 5:
                    team_val = 1
                elif 6 <= slot_val <= 10:
                    team_val = 2
            player = {
                "raw_id": pid,
                "steam_id": pid[1:] if isinstance(pid, str) and pid.startswith("S") else None,
                "gog_id": pid[1:] if isinstance(pid, str) and pid.startswith("G") else None,
                "name": player_name,
                "slot": slot_val,
                "team_id": team_val,
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

        # NAT type mapping (RakNet field is 't' in payload; C# maps from string digit)
        nat_type_raw = raw.get("t") or raw.get("NAT_TYPE") or raw.get("NATType")
        nat_type = None
        if isinstance(nat_type_raw, int) or (isinstance(nat_type_raw, str) and nat_type_raw.isdigit()):
            code = str(nat_type_raw)
            nat_type = {
                "0": "None",
                "1": "Full Cone",
                "2": "Address Restricted",
                "3": "Port Restricted",
                "4": "Symmetric",
                "5": "Unknown",
                "6": "Detection In Progress",
                "7": "Supports UPNP",
            }.get(code, None)
        elif isinstance(nat_type_raw, str):
            # Use provided text, normalized to Title Case
            nat_type = nat_type_raw.replace("_", " ").strip().title() or None

        # Additional attributes: ping/time rules
        attributes = {}
        max_ping = raw.get("pgm") or raw.get("MaxPing")
        if isinstance(max_ping, (int, str)) and str(max_ping).isdigit():
            attributes["max_ping"] = int(max_ping)
        worst_ping = raw.get("pg") or raw.get("MaxPingSeen")
        if isinstance(worst_ping, (int, str)) and str(worst_ping).isdigit():
            attributes["worst_ping"] = int(worst_ping)
        time_limit = raw.get("ti") or raw.get("TimeLimit")
        if isinstance(time_limit, (int, str)) and str(time_limit).isdigit():
            attributes["time_limit"] = int(time_limit)
        kill_limit = raw.get("ki") or raw.get("KillLimit")
        if isinstance(kill_limit, (int, str)) and str(kill_limit).isdigit():
            attributes["kill_limit"] = int(kill_limit)

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
            "attributes": attributes or None,
        }
        sessions.append(sess)
    return sessions


