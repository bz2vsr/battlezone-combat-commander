import time
import sys
from app.config import settings


def main() -> int:
    # Placeholder loop to verify worker process wiring
    interval = max(1, settings.poll_interval_seconds)
    print(f"[worker] starting placeholder loop with interval={interval}s", flush=True)
    try:
        while True:
            time.sleep(interval)
            # No-op for now; real poller/enrichment to be implemented
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())


