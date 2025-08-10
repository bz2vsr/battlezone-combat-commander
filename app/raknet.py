from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from app.config import settings


def fetch_raknet_payload(timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    if not settings.raknet_url:
        return None
    headers = {
        "User-Agent": "BZCC-Collector/1.0 (+https://example.local)"
    }
    resp = requests.get(settings.raknet_url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


