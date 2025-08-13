from flask import Flask, jsonify, request, Response, stream_with_context, render_template, redirect, session
import json
import time
import secrets
from app.store import get_current_sessions, get_session_detail, get_history_summary, get_maps_summary, get_mods_summary
from app.store import get_mod_catalog
from app.migrate import create_all, ensure_alter_tables
from app.config import settings
from flask_socketio import SocketIO


socketio: SocketIO | None = None


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

    # Initialize Socket.IO (Redis message queue for cross-process emit)
    global socketio
    if socketio is None:
        socketio = SocketIO(cors_allowed_origins=settings.ws_allowed_origins or "*",
                            message_queue=settings.redis_url or None,
                            async_mode="eventlet")
        socketio.init_app(app)

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
        # notify presence update
        try:
            if socketio:
                socketio.emit("presence:update", {"action": "logout"}, broadcast=True)
        except Exception:
            pass
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
        try:
            if socketio:
                socketio.emit("presence:update", {"provider": provider, "id": external_id}, broadcast=True)
        except Exception:
            pass
        return jsonify({"ok": True})

    @app.get("/api/v1/players/site-online")
    def players_site_online():
        # list users with recent heartbeats (last 20s) for snappier presence
        from datetime import timedelta, datetime
        cutoff = datetime.utcnow() - timedelta(seconds=20)
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

    # --- Team Picker (per TECHNICAL_SPEC.md Sections 4 & 5) ---
    @app.get("/api/v1/team_picker/<path:session_id>")
    def team_picker_get(session_id: str):
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickPick, TeamPickParticipant, Identity, Player
        from sqlalchemy import select as _select
        with session_scope() as db:
            tps = db.execute(
                _select(TeamPickSession)
                .where(TeamPickSession.session_id == session_id, TeamPickSession.state != "canceled")
                .order_by(TeamPickSession.id.desc())
            ).scalars().first()
            if not tps:
                return jsonify({"session": None})
            picks = db.execute(
                _select(TeamPickPick).where(TeamPickPick.pick_session_id == tps.id).order_by(TeamPickPick.order_index.asc())
            ).scalars().all()
            parts = db.execute(
                _select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id)
            ).scalars().all()
            # Enrich pick player Steam details
            steam_ids = [p.player_steam_id for p in picks if p.player_steam_id]
            mapping = {}
            if steam_ids:
                rows = db.execute(
                    _select(Identity, Player)
                    .where(Identity.provider == "steam", Identity.external_id.in_(steam_ids))
                    .join(Player, Identity.player_id == Player.id, isouter=True)
                ).all()
                for ident, player in rows:
                    mapping[str(ident.external_id)] = {
                        "id": str(ident.external_id),
                        "profile": ident.profile_url,
                        "nickname": (player.display_name if player else None),
                        "avatar": (player.avatar_url if player else None),
                    }
            return jsonify({
                "session": {
                    "id": tps.id,
                    "game_session_id": tps.session_id,
                    "state": tps.state,
                    "coin_winner_team": tps.coin_winner_team,
                    "created_at": tps.created_at.isoformat() if tps.created_at else None,
                    "closed_at": tps.closed_at.isoformat() if tps.closed_at else None,
                    "accepted": {
                        "commander1": bool(tps.accepted_by_commander1),
                        "commander2": bool(tps.accepted_by_commander2),
                    },
                    "participants": [
                        {
                            "provider": r.provider,
                            "id": r.external_id,
                            "role": r.role,
                        } for r in parts
                    ],
                    "picks": [
                        {
                            "order": p.order_index,
                            "team_id": p.team_id,
                            "player": {
                                "steam_id": p.player_steam_id,
                                "steam": mapping.get(p.player_steam_id),
                            },
                            "picked_at": p.picked_at.isoformat() if p.picked_at else None,
                        } for p in picks
                    ],
                }
            })

    @app.post("/api/v1/team_picker/<path:session_id>/start")
    def team_picker_start(session_id: str):
        # Creator must be logged in and one of the commanders
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        creator_provider, creator_external = uid.split(":", 1)
        payload = request.get_json(silent=True) or {}
        cmd1 = payload.get("commander1_id")
        cmd2 = payload.get("commander2_id")
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant, SessionPlayer
        from sqlalchemy import select as _select
        with session_scope() as db:
            # Infer commanders if not provided: use slots 1 and 6 steam_ids if available
            if not cmd1 or not cmd2:
                rows = db.execute(
                    _select(SessionPlayer).where(SessionPlayer.session_id == session_id).order_by(SessionPlayer.slot.asc())
                ).scalars().all()
                # Host heuristic already present (slots 1,6)
                cands = []
                for sp in rows:
                    if sp.is_host and sp.stats and sp.stats.get("steam_id"):
                        cands.append(str(sp.stats.get("steam_id")))
                if len(cands) >= 2:
                    if not cmd1:
                        cmd1 = cands[0]
                    if not cmd2:
                        cmd2 = cands[1]
            if not cmd1 or not cmd2:
                return jsonify({"ok": False, "error": "missing_commanders"}), 400
            if str(creator_provider) == "steam" and str(creator_external) not in (str(cmd1), str(cmd2)):
                # Only allow a commander to start
                return jsonify({"ok": False, "error": "forbidden"}), 403
            # Close any existing open sessions for this game session
            open_rows = db.execute(
                _select(TeamPickSession).where(TeamPickSession.session_id == session_id, TeamPickSession.state == "open")
            ).scalars().all()
            from datetime import datetime as _dt
            for r in open_rows:
                r.state = "canceled"
                r.closed_at = _dt.utcnow()
            # Create new pick session
            tps = TeamPickSession(
                session_id=session_id,
                state="open",
                created_by_provider=creator_provider,
                created_by_external_id=creator_external,
            )
            db.add(tps)
            db.flush()
            # Participants
            db.add(TeamPickParticipant(pick_session_id=tps.id, provider="steam", external_id=str(cmd1), role="commander1"))
            db.add(TeamPickParticipant(pick_session_id=tps.id, provider="steam", external_id=str(cmd2), role="commander2"))
            if str(creator_provider) == "steam" and str(creator_external) not in (str(cmd1), str(cmd2)):
                db.add(TeamPickParticipant(pick_session_id=tps.id, provider=creator_provider, external_id=creator_external, role="viewer"))
        try:
            if socketio:
                socketio.emit("team_picker:update", {"session_id": session_id, "action": "start"}, room=f"team_picker:{session_id}", broadcast=True)
        except Exception:
            pass
        return team_picker_get(session_id)

    @app.post("/api/v1/team_picker/<path:session_id>/coin_toss")
    def team_picker_coin_toss(session_id: str):
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        provider, external = uid.split(":", 1)
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant
        from sqlalchemy import select as _select
        with session_scope() as db:
            tps = db.execute(
                _select(TeamPickSession).where(TeamPickSession.session_id == session_id, TeamPickSession.state == "open")
            ).scalars().first()
            if not tps:
                return jsonify({"ok": False, "error": "not_found_or_closed"}), 404
            if tps.coin_winner_team is not None:
                return jsonify({"ok": False, "error": "already_tossed"}), 400
            part = db.execute(
                _select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id, TeamPickParticipant.provider == provider, TeamPickParticipant.external_id == external)
            ).scalars().first()
            if not part or part.role not in ("commander1", "commander2"):
                return jsonify({"ok": False, "error": "forbidden"}), 403
            tps.coin_winner_team = 1 if secrets.randbits(1) == 0 else 2
        try:
            if socketio:
                socketio.emit("team_picker:update", {"session_id": session_id, "action": "coin_toss", "team": tps.coin_winner_team}, room=f"team_picker:{session_id}", broadcast=True)
        except Exception:
            pass
        return team_picker_get(session_id)

    @app.post("/api/v1/team_picker/<path:session_id>/pick")
    def team_picker_pick(session_id: str):
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        provider, external = uid.split(":", 1)
        payload = request.get_json(silent=True) or {}
        steam_id = str(payload.get("player_steam_id") or "").strip()
        if not steam_id:
            return jsonify({"ok": False, "error": "missing_player_steam_id"}), 400
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant, TeamPickPick
        from sqlalchemy import select as _select
        with session_scope() as db:
            tps = db.execute(
                _select(TeamPickSession).where(TeamPickSession.session_id == session_id, TeamPickSession.state == "open")
            ).scalars().first()
            if not tps:
                return jsonify({"ok": False, "error": "not_found_or_closed"}), 404
            if tps.coin_winner_team is None:
                return jsonify({"ok": False, "error": "coin_required"}), 400
            # Determine caller role
            part = db.execute(
                _select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id, TeamPickParticipant.provider == provider, TeamPickParticipant.external_id == external)
            ).scalars().first()
            if not part or part.role not in ("commander1", "commander2"):
                return jsonify({"ok": False, "error": "forbidden"}), 403
            # Determine next team to pick
            existing = db.execute(
                _select(TeamPickPick).where(TeamPickPick.pick_session_id == tps.id).order_by(TeamPickPick.order_index.asc())
            ).scalars().all()
            order_index = len(existing) + 1
            # Starting team is coin_winner_team; alternate thereafter
            if len(existing) % 2 == 0:
                next_team = tps.coin_winner_team
            else:
                next_team = 2 if tps.coin_winner_team == 1 else 1
            # Only the corresponding commander may pick
            required_role = "commander1" if next_team == 1 else "commander2"
            if part.role != required_role:
                return jsonify({"ok": False, "error": "not_your_turn"}), 400
            # Prevent duplicate picks
            dup = db.execute(
                _select(TeamPickPick).where(TeamPickPick.pick_session_id == tps.id, TeamPickPick.player_steam_id == steam_id)
            ).scalars().first()
            if dup:
                return jsonify({"ok": False, "error": "already_picked"}), 400
            p = TeamPickPick(
                pick_session_id=tps.id,
                order_index=order_index,
                team_id=next_team,
                player_steam_id=steam_id,
                picked_by_provider=provider,
                picked_by_external_id=external,
            )
            db.add(p)
        try:
            if socketio:
                socketio.emit("team_picker:update", {"session_id": session_id, "action": "pick"}, room=f"team_picker:{session_id}", broadcast=True)
        except Exception:
            pass
        return team_picker_get(session_id)

    @app.post("/api/v1/team_picker/<path:session_id>/finalize")
    def team_picker_finalize(session_id: str):
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        provider, external = uid.split(":", 1)
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant
        from sqlalchemy import select as _select
        with session_scope() as db:
            tps = db.execute(
                _select(TeamPickSession).where(TeamPickSession.session_id == session_id, TeamPickSession.state == "open")
            ).scalars().first()
            if not tps:
                return jsonify({"ok": False, "error": "not_found_or_closed"}), 404
            part = db.execute(
                _select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id, TeamPickParticipant.provider == provider, TeamPickParticipant.external_id == external)
            ).scalars().first()
            if not part or part.role not in ("commander1", "commander2"):
                return jsonify({"ok": False, "error": "forbidden"}), 403
            if part.role == "commander1":
                tps.accepted_by_commander1 = True
            elif part.role == "commander2":
                tps.accepted_by_commander2 = True
            # If both accepted, finalize
            if tps.accepted_by_commander1 and tps.accepted_by_commander2:
                from datetime import datetime as _dt
                tps.state = "final"
                tps.closed_at = _dt.utcnow()
        try:
            if socketio:
                socketio.emit("team_picker:update", {"session_id": session_id, "action": "finalize"}, room=f"team_picker:{session_id}", broadcast=True)
        except Exception:
            pass
        return team_picker_get(session_id)

    @app.post("/api/v1/team_picker/<path:session_id>/cancel")
    def team_picker_cancel(session_id: str):
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        provider, external = uid.split(":", 1)
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant
        from sqlalchemy import select as _select
        with session_scope() as db:
            tps = db.execute(
                _select(TeamPickSession).where(TeamPickSession.session_id == session_id, TeamPickSession.state == "open")
            ).scalars().first()
            if not tps:
                return jsonify({"ok": False, "error": "not_found_or_closed"}), 404
            # Allow commanders or creator
            allowed = False
            if tps.created_by_provider == provider and tps.created_by_external_id == external:
                allowed = True
            else:
                part = db.execute(
                    _select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id, TeamPickParticipant.provider == provider, TeamPickParticipant.external_id == external)
                ).scalars().first()
                if part and part.role in ("commander1", "commander2"):
                    allowed = True
            if not allowed:
                return jsonify({"ok": False, "error": "forbidden"}), 403
            from datetime import datetime as _dt
            tps.state = "canceled"
            tps.closed_at = _dt.utcnow()
        try:
            if socketio:
                socketio.emit("team_picker:update", {"session_id": session_id, "action": "cancel"}, room=f"team_picker:{session_id}", broadcast=True)
        except Exception:
            pass
        return team_picker_get(session_id)

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

    # --- Dev utilities (non-production only) ---
    if (settings.flask_env or "production").lower() != "production":
        @app.post("/admin/dev/mock/session")
        def admin_dev_mock_session():
            # Create a synthetic session with the current user as commander1 and a fake second commander
            uid = session.get('uid')
            if not uid:
                return jsonify({"ok": False, "error": "not_authenticated"}), 401
            provider, external_id = uid.split(":", 1)
            from app.db import session_scope
            from app.models import Session, SessionPlayer
            from datetime import datetime as _dt
            mock_id = f"Dev:TP:{provider}:{external_id}"
            with session_scope() as db:
                row = db.get(Session, mock_id)
                if row is None:
                    row = Session(id=mock_id, source="dev", name="Dev Team Picker", state="PreGame", tps=30, version="dev", map_file="vsr4pool", mod_id="0", attributes={"max_players": 8}, started_at=_dt.utcnow())
                    db.add(row)
                row.last_seen_at = _dt.utcnow()
                row.ended_at = None
                # Seed players: two commanders as hosts (slots 1 and 6) + 6 others with fake steam ids
                def upsert_player(slot: int, team_id: int | None, is_host: bool, name: str, steam_id: str | None):
                    from sqlalchemy import select as _select
                    existing = db.execute(_select(SessionPlayer).where(SessionPlayer.session_id == row.id, SessionPlayer.slot == slot)).scalar_one_or_none()
                    stats = {"name": name}
                    if steam_id:
                        stats["steam_id"] = steam_id
                    if existing is None:
                        db.add(SessionPlayer(session_id=row.id, slot=slot, team_id=team_id, is_host=is_host, stats=stats))
                    else:
                        existing.team_id = team_id
                        existing.is_host = is_host
                        existing.stats = stats
                upsert_player(1, 1, True, "Commander 1", external_id if provider == "steam" else None)
                upsert_player(6, 2, True, "Commander 2", "76561199000000000")
                # Add 6 pickable players with fake steam ids
                for i in range(2, 6):
                    upsert_player(i, None, False, f"Player {i}", f"7656119900000000{i}")
                for i in range(7, 9):
                    upsert_player(i, None, False, f"Player {i}", f"765611990000000{i}")
            try:
                if socketio:
                    socketio.emit("sessions:update", {"id": mock_id}, broadcast=True)
            except Exception:
                pass
            return jsonify({"ok": True, "session_id": mock_id})

    return app


# WSGI entry point for Gunicorn
app = create_app()


