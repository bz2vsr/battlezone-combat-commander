from __future__ import annotations

import hashlib
import mimetypes
import os
from typing import Optional

import requests

from app.config import settings


ASSETS_DIR = os.path.join(os.path.dirname(__file__), "static", "assets")


def _ensure_dir() -> None:
    os.makedirs(ASSETS_DIR, exist_ok=True)


def _ext_from_content_type(ct: Optional[str]) -> str:
    if not ct:
        return ".bin"
    if ";" in ct:
        ct = ct.split(";", 1)[0]
    ext = mimetypes.guess_extension(ct.strip()) or ".bin"
    # normalize jpeg to .jpg
    if ext == ".jpe":
        ext = ".jpg"
    return ext


def _public_url(filename: str) -> str:
    if settings.assets_cdn_base:
        return f"{settings.assets_cdn_base.rstrip('/')}/assets/{filename}"
    # Flask serves /static from app/static by default
    return f"/static/assets/{filename}"


def mirror_asset(url: str, timeout: float = 10.0) -> Optional[str]:
    """Download an image and save to static/assets/<sha256>.<ext>.

    Returns public URL (CDN base if configured, else /static path). Returns None on failure.
    """
    if not url:
        return None
    try:
        _ensure_dir()
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        data = resp.content
        sha = hashlib.sha256(data).hexdigest()
        ext = _ext_from_content_type(resp.headers.get("Content-Type"))
        filename = f"{sha}{ext}"
        path = os.path.join(ASSETS_DIR, filename)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        return _public_url(filename)
    except Exception:
        return None


