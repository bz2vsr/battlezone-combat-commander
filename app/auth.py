from __future__ import annotations

import re
from urllib.parse import urlencode
import requests
from flask import Request

from app.config import settings


STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login"


def _app_base_url() -> str:
    base = settings.app_base_url.rstrip("/") if settings.app_base_url else "http://localhost:5000"
    return base


def build_steam_login_redirect_url() -> str:
    """Return the URL to redirect the browser to Steam OpenID provider.

    Uses OpenID 2.0 immediate=false flow.
    """
    return_to = f"{_app_base_url()}/auth/steam/return"
    realm = _app_base_url()
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return f"{STEAM_OPENID_ENDPOINT}?{urlencode(params)}"


def verify_steam_openid_response(req: Request) -> str | None:
    """Verify OpenID response with Steam and return steamid64 if valid.

    Implements provider verification by posting back with mode=check_authentication.
    """
    if req.args.get("openid.mode") != "id_res":
        return None

    # Post back all received openid.* params with mode=check_authentication
    data = {k: v for k, v in req.args.items() if k.startswith("openid.")}
    data["openid.mode"] = "check_authentication"
    r = requests.post(STEAM_OPENID_ENDPOINT, data=data, timeout=10)
    if r.status_code != 200:
        return None
    body = r.text or ""
    if "is_valid:true" not in body:
        return None

    claimed = req.args.get("openid.claimed_id") or ""
    m = re.search(r"https?://steamcommunity\.com/openid/id/(\d+)$", claimed)
    return m.group(1) if m else None


