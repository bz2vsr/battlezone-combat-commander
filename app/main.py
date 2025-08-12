from flask import Flask, jsonify, request, Response, stream_with_context, render_template, redirect, session
import json
import time
from app.store import get_current_sessions, get_session_detail, get_history_summary, get_maps_summary, get_mods_summary
from app.store import get_mod_catalog
from app.migrate import create_all, ensure_alter_tables
from app.config import settings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.secret_key
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Ensure DB schema exists (idempotent)
    try:
        create_all()
        ensure_alter_tables()
    except Exception as ex:
        # Defer hard failure to first DB access; still log to console
        print(f"[app] schema init warning: {ex}", flush=True)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/admin/tools/health")
    def admin_health():
        from app.raknet import fetch_raknet_payload
        from app.config import settings as _settings
        ok_raknet = False
        try:
            payload = fetch_raknet_payload()
            ok_raknet = isinstance(payload, dict) and (payload.get("GET") is not None)
        except Exception:
            ok_raknet = False
        return jsonify({
            "raknet_ok": ok_raknet,
            "steam_api_key_present": bool(_settings.steam_api_key),
        })

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)

    @app.get("/api/v1/sessions/current")
    def sessions_current():
        # Basic filter: ?state=InGame (case-insensitive)
        state = request.args.get("state")
        nat_type = request.args.get("nat_type")
        min_players = request.args.get("min_players", type=int)
        q = request.args.get("q")
        mod = request.args.get("mod")

        sessions = get_current_sessions()
        if state:
            s_norm = state.strip().lower()
            sessions = [s for s in sessions if (s.get("state") or "").lower() == s_norm]
        if nat_type:
            n_norm = nat_type.strip().lower()
            sessions = [s for s in sessions if (s.get("nat_type") or "").lower() == n_norm]
        if isinstance(min_players, int):
            sessions = [s for s in sessions if len(s.get("players") or []) >= min_players]
        if mod:
            sessions = [s for s in sessions if (s.get("mod") or "") == mod]
        if q:
            q_norm = q.strip().lower()
            def _match(s):
                if (s.get("name") or "").lower().find(q_norm) >= 0:
                    return True
                for p in s.get("players") or []:
                    if ((p.get("name") or "").lower().find(q_norm) >= 0):
                        return True
                return False
            sessions = [s for s in sessions if _match(s)]
        return jsonify({"sessions": sessions})

    @app.get("/api/v1/sessions/<path:sid>")
    def session_detail(sid: str):
        data = get_session_detail(sid)
        if data is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(data)

    @app.get("/api/v1/stream/sessions")
    def stream_sessions():
        # Simple SSE stream with 5s updates from DB
        def _gen():
            last_payload = None
            while True:
                sessions = get_current_sessions()
                payload = json.dumps({"sessions": sessions})
                if payload != last_payload:
                    yield f"data: {payload}\n\n"
                    last_payload = payload
                time.sleep(5)
        return Response(stream_with_context(_gen()), mimetype="text/event-stream")

    @app.get("/api/v1/history/summary")
    def history_summary():
        minutes = request.args.get("minutes", default=60, type=int)
        return jsonify({"points": get_history_summary(minutes=minutes)})

    @app.get("/api/v1/history/maps")
    def history_maps():
        hours = request.args.get("hours", default=24, type=int)
        return jsonify({"items": get_maps_summary(hours=hours)})

    @app.get("/api/v1/history/mods")
    def history_mods():
        hours = request.args.get("hours", default=24, type=int)
        return jsonify({"items": get_mods_summary(hours=hours)})

    @app.get("/api/v1/mods")
    def mods_catalog():
        return jsonify({"mods": get_mod_catalog()})

    @app.get("/api/v1/players/online")
    def players_online():
        # Derive unique players across active sessions for sidebar presence
        sessions = get_current_sessions()
        seen = {}
        for s in sessions:
            for p in s.get("players") or []:
                key = None
                steam = (p.get("steam") or {})
                if steam.get("id"):
                    key = f"steam:{steam['id']}"
                elif p.get("name"):
                    key = f"name:{p['name']}"
                else:
                    continue
                if key not in seen:
                    seen[key] = {
                        "name": steam.get("nickname") or p.get("name") or "Player",
                        "steam": {
                            "id": steam.get("id"),
                            "nickname": steam.get("nickname"),
                            "avatar": steam.get("avatar"),
                            "url": steam.get("url"),
                        },
                        "in_game": True,
                    }
        players = list(seen.values())
        players.sort(key=lambda x: (x.get("steam", {}).get("nickname") or x.get("name") or "").lower())
        return jsonify({"players": players})

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html")

    # --- Steam SSO (OpenID 2.0) ---
    from app.auth import build_steam_login_redirect_url, verify_steam_openid_response

    @app.get("/auth/steam/login")
    def auth_steam_login():
        return redirect(build_steam_login_redirect_url())

    @app.get("/auth/steam/return")
    def auth_steam_return():
        steamid = verify_steam_openid_response(request)
        if not steamid:
            return redirect("/")
        # Upsert identity in DB
        from app.db import session_scope
        from app.models import Identity, Player
        from sqlalchemy import select
        with session_scope() as db:
            ident = db.execute(select(Identity).where(Identity.provider == "steam", Identity.external_id == str(steamid))).scalar_one_or_none()
            if ident is None:
                player = Player()
                db.add(player)
                db.flush()
                ident = Identity(player_id=player.id, provider="steam", external_id=str(steamid), profile_url=f"https://steamcommunity.com/profiles/{steamid}/")
                db.add(ident)
            # Best-effort profile sync for display name and avatar
            try:
                from app.steam import fetch_player_summaries
                res = fetch_player_summaries([str(steamid)]) or {}
                players = (res.get("response") or {}).get("players") or []
                if players:
                    p = players[0]
                    # Reload player instance (may be existing)
                    player = db.get(Player, ident.player_id)
                    if player:
                        player.display_name = p.get("personaname") or player.display_name
                        player.avatar_url = p.get("avatarfull") or player.avatar_url
                        db.flush()
            except Exception:
                pass
        session['uid'] = f"steam:{steamid}"
        return redirect("/")

    @app.post("/auth/logout")
    def auth_logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/v1/me")
    def me():
        uid = session.get('uid')
        if not uid:
            return jsonify({"user": None})
        provider, external_id = uid.split(":", 1)
        from app.db import session_scope
        from app.models import Identity, Player
        from sqlalchemy import select
        with session_scope() as db:
            row = db.execute(
                select(Identity, Player)
                .where(Identity.provider == provider, Identity.external_id == external_id)
                .join(Player, Identity.player_id == Player.id, isouter=True)
            ).first()
            if not row:
                return jsonify({"user": None})
            ident, player = row
            # Fallback: if no display_name, best-effort fetch from Steam now
            if provider == "steam" and player and not player.display_name:
                try:
                    from app.steam import fetch_player_summaries
                    res = fetch_player_summaries([external_id]) or {}
                    players = (res.get("response") or {}).get("players") or []
                    if players:
                        p = players[0]
                        player.display_name = p.get("personaname") or player.display_name
                        player.avatar_url = p.get("avatarfull") or player.avatar_url
                        db.flush()
                except Exception:
                    pass
            # Secondary fallback: derive name from most recent in-game session record
            if provider == "steam" and player and not player.display_name:
                try:
                    from sqlalchemy import text as _text
                    r = db.execute(_text(
                        """
                        SELECT stats->>'name' AS name
                        FROM session_players
                        WHERE stats->>'steam_id' = :e
                        ORDER BY id DESC LIMIT 1
                        """
                    ), {"e": external_id}).first()
                    if r and r[0]:
                        player.display_name = r[0]
                        db.flush()
                except Exception:
                    pass
            return jsonify({
                "user": {
                    "provider": provider,
                    "id": ident.external_id,
                    "profile": ident.profile_url,
                    "display_name": player.display_name if player else None,
                    "avatar": player.avatar_url if player else None,
                }
            })

    @app.get("/admin/tools/presence/peek")
    def admin_presence_peek():
        from app.db import session_scope
        from app.models import SitePresence
        from sqlalchemy import select as _select
        with session_scope() as db:
            rows = db.execute(_select(SitePresence).order_by(SitePresence.last_seen_at.desc()).limit(10)).scalars().all()
            return jsonify({
                "rows": [
                    {
                        "provider": r.provider,
                        "external_id": r.external_id,
                        "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
                    } for r in rows
                ]
            })

    @app.post("/api/v1/presence/heartbeat")
    def presence_heartbeat():
        # mark the logged-in user as active on the site (green dot)
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        provider, external_id = uid.split(":", 1)
        from app.db import session_scope
        from app.models import SitePresence
        from sqlalchemy import text as _text
        with session_scope() as db:
            # upsert via SQL for simplicity
            db.execute(_text(
                """
                INSERT INTO site_presence(provider, external_id, last_seen_at)
                VALUES (:p, :e, now())
                ON CONFLICT DO NOTHING;
                """
            ), {"p": provider, "e": external_id})
            db.execute(_text(
                """
                UPDATE site_presence SET last_seen_at = now()
                WHERE provider = :p AND external_id = :e
                """
            ), {"p": provider, "e": external_id})
        return jsonify({"ok": True})

    @app.get("/api/v1/players/site-online")
    def players_site_online():
        # list users with recent heartbeats (last 60s)
        from datetime import timedelta, datetime
        cutoff = datetime.utcnow() - timedelta(seconds=60)
        from app.db import session_scope
        from app.models import SitePresence, Identity, Player
        from sqlalchemy import select as _select
        with session_scope() as db:
            rows = db.execute(
                _select(SitePresence, Identity, Player)
                .where(SitePresence.last_seen_at >= cutoff)
                .join(Identity, (Identity.provider == SitePresence.provider) & (Identity.external_id == SitePresence.external_id), isouter=True)
                .join(Player, Identity.player_id == Player.id, isouter=True)
            ).all()
            out = []
            for pr, ident, player in rows:
                # If display name missing, derive from last seen session
                display_name = player.display_name if player else None
                avatar_url = player.avatar_url if player else None
                if pr.provider == "steam" and not display_name:
                    try:
                        from sqlalchemy import text as _text
                        r = db.execute(_text(
                            """
                            SELECT stats->>'name' AS name
                            FROM session_players
                            WHERE stats->>'steam_id' = :e
                            ORDER BY id DESC LIMIT 1
                            """
                        ), {"e": pr.external_id}).first()
                        if r and r[0]:
                            display_name = r[0]
                    except Exception:
                        pass
                out.append({
                    "provider": pr.provider,
                    "id": pr.external_id,
                    "display_name": display_name,
                    "avatar": avatar_url,
                    "profile": ident.profile_url if ident else None,
                })
            return jsonify({"players": out})

    # Simple Admin Tools (scaffold)
    @app.get("/admin")
    def admin_home():
        return render_template("admin.html")

    @app.get("/admin/tools/raknet/sample")
    def admin_raknet_sample():
        from app.raknet import fetch_raknet_payload
        try:
            payload = fetch_raknet_payload() or {}
            # Redact player names/ids for safety
            get_list = payload.get("GET") or []
            redacted = []
            for item in get_list:
                if not isinstance(item, dict):
                    continue
                clone = dict(item)
                if "pl" in clone:
                    clone["pl"] = len(clone.get("pl") or [])
                redacted.append({k: clone.get(k) for k in ["n", "v", "m", "g", "si", "tps", "mm", "pl"] if k in clone})
            return jsonify({"ok": True, "GET": redacted, "count": len(redacted)})
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)})

    return app


# WSGI entry point for Gunicorn
app = create_app()


