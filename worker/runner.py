import time
import sys
from app.config import settings
from app.raknet import fetch_raknet_payload


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
                    print(f"[worker] fetched payload with {len(payload.get('GET', []))} sessions", flush=True)
            except Exception as ex:
                print(f"[worker] poll error: {ex}", flush=True)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())


