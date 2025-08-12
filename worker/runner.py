import time
import sys
from app.config import settings
from app.raknet import fetch_raknet_payload
from app.parser_bzcc import normalize_bzcc_sessions
from app.store import save_sessions
from app.steam import enrich_steam_identities
from app.enrich import enrich_sessions_levels
from app.assets import ensure_placeholder_asset
from flask_socketio import SocketIO


def main() -> int:
    # Placeholder loop to verify worker process wiring
    interval = max(1, settings.poll_interval_seconds)
    print(f"[worker] starting placeholder loop with interval={interval}s", flush=True)
    try:
        ensure_placeholder_asset()
        # Poll immediately on startup to prime the DB
        # socketio client for emit via Redis message queue
        sio = None
        try:
            if settings.redis_url:
                sio = SocketIO(message_queue=settings.redis_url)
        except Exception:
            sio = None
        while True:
            try:
                payload = fetch_raknet_payload()
                if payload is not None:
                    normalized = normalize_bzcc_sessions(payload)
                    for s in normalized:
                        if not s.get("name"):
                            s["name"] = None
                    stats = save_sessions(normalized)
                    try:
                        if normalized:
                            enrich = enrich_sessions_levels(normalized)
                            print(f"[worker] enrich levels/mods: {enrich}", flush=True)
                            # steam enrichment (collect seen steam IDs)
                            steam_ids = []
                            for s in normalized:
                                for p in s.get("players", []) or []:
                                    sid = p.get("steam_id")
                                    if sid:
                                        steam_ids.append(str(sid))
                            if steam_ids:
                                ste = enrich_steam_identities(steam_ids)
                                print(f"[worker] enrich steam: {ste}", flush=True)
                            else:
                                print("[worker] enrich steam: no steam ids in this tick", flush=True)
                    except Exception as ex:
                        print(f"[worker] enrich error: {ex}", flush=True)
                    print(f"[worker] upsert sessions: {stats}", flush=True)
                    # broadcast to websockets
                    try:
                        if sio:
                            sio.emit("sessions:update", {"sessions": normalized}, broadcast=True)
                    except Exception as ex:
                        print(f"[worker] ws emit error: {ex}", flush=True)
            except Exception as ex:
                print(f"[worker] poll error: {ex}", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())


