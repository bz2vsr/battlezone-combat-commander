import time
import sys
from app.config import settings
from app.raknet import fetch_raknet_payload
from app.parser_bzcc import normalize_bzcc_sessions
from app.store import save_sessions


def main() -> int:
    # Placeholder loop to verify worker process wiring
    interval = max(1, settings.poll_interval_seconds)
    print(f"[worker] starting placeholder loop with interval={interval}s", flush=True)
    try:
        while True:
            time.sleep(interval)
            try:
                payload = fetch_raknet_payload()
                if payload is not None:
                    normalized = normalize_bzcc_sessions(payload)
                    stats = save_sessions(normalized)
                    print(f"[worker] upsert sessions: {stats}", flush=True)
            except Exception as ex:
                print(f"[worker] poll error: {ex}", flush=True)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())


