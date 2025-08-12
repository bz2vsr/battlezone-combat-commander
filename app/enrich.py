from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple
import requests

from app.config import settings
from app.db import session_scope
from app.models import Level, Mod
from app.assets import mirror_asset


def _join_url(base: str, path: str) -> str:
    if not base:
        return path
    return base.rstrip('/') + '/' + path.lstrip('/')


def fetch_getdata(map_file: str, mod_id: str, timeout: float = 8.0) -> Optional[Dict]:
    if not settings.getdata_base:
        return None
    try:
        resp = requests.get(
            settings.getdata_base,
            params={"map": map_file, "mod": mod_id},
            headers={"User-Agent": "BZCC-Collector/1.0"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def enrich_sessions_levels(sessions: Iterable[Dict]) -> Dict[str, int]:
    """Fetch getdata for unique (mod,map) pairs and upsert level/mod names/images.

    Returns counts for logging.
    """
    seen: set[Tuple[str, str]] = set()
    updated_levels = 0
    updated_mods = 0
    asset_base: Optional[str] = None
    # Derive asset base from getdata_base (…/bzcc/getdata.php -> …/bzcc/)
    if settings.getdata_base and "/" in settings.getdata_base:
        asset_base = settings.getdata_base.rsplit("/", 1)[0] + "/"

    with session_scope() as db:
        for s in sessions:
            mod_id = s.get("mod")
            map_file = s.get("map_file")
            if not mod_id or not map_file:
                continue
            # Use lowercase map id for getdata parity with reference implementation
            map_file_query = map_file.lower()
            key = (mod_id, map_file_query)
            if key in seen:
                continue
            seen.add(key)

            data = fetch_getdata(map_file_query, mod_id)
            if not data:
                continue

            # Level details
            level_title = data.get("title") or None
            level_img_rel = data.get("image") or None
            level_img_src = _join_url(asset_base, level_img_rel) if level_img_rel else None
            level_img = mirror_asset(level_img_src) if level_img_src else None
            level_id = f"{mod_id}:{map_file}"
            level = db.get(Level, level_id)
            if level is None:
                level = Level(id=level_id, mod_id=mod_id, map_file=map_file, name=level_title, image_url=level_img)
                db.add(level)
                updated_levels += 1
            else:
                new_name = level_title or level.name
                new_img = level_img or level.image_url
                if new_name != level.name or new_img != level.image_url:
                    level.name = new_name
                    level.image_url = new_img
                    updated_levels += 1

            # Mod details (if present)
            mods = (data.get("mods") or {})
            mod_info = mods.get(str(mod_id)) if isinstance(mods, dict) else None
            if isinstance(mod_info, dict):
                m = db.get(Mod, mod_id)
                mname = mod_info.get("name") or mod_info.get("workshop_name") or None
                mimg_rel = mod_info.get("image") or None
                mimg_src = _join_url(asset_base, mimg_rel) if mimg_rel else None
                mimg = mirror_asset(mimg_src) if mimg_src else None
                if m is None:
                    db.add(Mod(id=mod_id, name=mname, image_url=mimg))
                    updated_mods += 1
                else:
                    new_name = mname or m.name
                    new_img = mimg or m.image_url
                    if new_name != m.name or new_img != m.image_url:
                        m.name = new_name
                        m.image_url = new_img
                        updated_mods += 1

    return {"levels": updated_levels, "mods": updated_mods}


