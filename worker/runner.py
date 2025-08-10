import time
import sys
from app.config import settings
from app.raknet import fetch_raknet_payload
from app.parser_bzcc import normalize_bzcc_sessions
from app.store import save_sessions
from app.enrich import enrich_sessions_levels


def main() -> int:
    # Placeholder loop to verify worker process wiring
    interval = max(1, settings.poll_interval_seconds)
    print(f"[worker] starting placeholder loop with interval={interval}s", flush=True)
    try:
        # Poll immediately on startup to prime the DB
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
                    except Exception as ex:
                        print(f"[worker] enrich error: {ex}", flush=True)
                    print(f"[worker] upsert sessions: {stats}", flush=True)
            except Exception as ex:
                print(f"[worker] poll error: {ex}", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())


