from flask import Flask, jsonify, request, Response, stream_with_context, render_template, redirect, session
import json
import time
import secrets
from app.store import get_current_sessions, get_session_detail, get_history_summary, get_maps_summary, get_mods_summary
from app.store import get_mod_catalog
from app.migrate import create_all, ensure_alter_tables
from app.config import settings
from flask_socketio import SocketIO
import os


socketio: SocketIO | None = None


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.secret_key
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    # Expose realtime flag to templates/JS (set by dev.ps1 -Realtime)
    app.config['REALTIME_ENABLED'] = bool(os.getenv('REALTIME'))
    app.config['TEAM_PICK_PRESENCE'] = {}

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
        from app.models import TeamPickSession, TeamPickPick, TeamPickParticipant, Identity, Player, SessionPlayer
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
            # Enrich Steam identities for picks, participants, and roster
            roster_rows = db.execute(
                _select(SessionPlayer).where(SessionPlayer.session_id == session_id).order_by(SessionPlayer.slot.asc())
            ).scalars().all()
            steam_ids: set[str] = set(p.player_steam_id for p in picks if p.player_steam_id)
            for r in roster_rows:
                sid = (r.stats or {}).get("steam_id")
                if sid:
                    steam_ids.add(str(sid))
            for r in parts:
                if r.provider == "steam" and r.external_id:
                    steam_ids.add(str(r.external_id))
            mapping: dict[str, dict] = {}
            if steam_ids:
                rows = db.execute(
                    _select(Identity, Player)
                    .where(Identity.provider == "steam", Identity.external_id.in_(list(steam_ids)))
                    .join(Player, Identity.player_id == Player.id, isouter=True)
                ).all()
                for ident, player in rows:
                    mapping[str(ident.external_id)] = {
                        "id": str(ident.external_id),
                        "profile": ident.profile_url,
                        "nickname": (player.display_name if player else None),
                        "avatar": (player.avatar_url if player else None),
                    }
            # Compute remaining eligible players and next team only if any remain
            commander_ids = set(str(r.external_id) for r in parts if r.role in ("commander1", "commander2") and r.provider == "steam")
            picked_ids = set(p.player_steam_id for p in picks if p.player_steam_id)
            remaining = 0
            for rr in roster_rows:
                sid = (rr.stats or {}).get("steam_id")
                if not sid:
                    continue
                sid = str(sid)
                if sid in commander_ids:
                    continue
                if sid in picked_ids:
                    continue
                remaining += 1
            next_team = None
            if tps.coin_winner_team is not None and remaining > 0:
                next_team = tps.coin_winner_team if (len(picks) % 2 == 0) else (2 if tps.coin_winner_team == 1 else 1)
            # Determine caller role
            me_role = None
            uid = session.get('uid')
            if uid:
                pvd, ext = uid.split(":", 1)
                for r in parts:
                    if r.provider == pvd and r.external_id == ext:
                        me_role = r.role
                        break
            # Build response
            from datetime import datetime as _dt, timedelta as _td
            presence = app.config.get('TEAM_PICK_PRESENCE', {})
            cutoff_ts = (_dt.utcnow() - _td(seconds=20)).timestamp()
            resp = {
                "id": tps.id,
                "game_session_id": tps.session_id,
                "state": tps.state,
                "coin_winner_team": tps.coin_winner_team,
                "next_team": next_team,
                "your_role": me_role,
                "picks_complete": remaining == 0,
                "max_team_size": 5,
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
                        "active": presence.get(f"{session_id}:{r.provider}:{r.external_id}", 0) >= cutoff_ts,
                        "steam": (mapping.get(str(r.external_id)) if r.provider == "steam" else None),
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
                "roster": [
                    {
                        "slot": rr.slot,
                        "team_id": rr.team_id,
                        "is_host": rr.is_host,
                        "name": (rr.stats or {}).get("name"),
                        "steam_id": (rr.stats or {}).get("steam_id"),
                        "steam": mapping.get(str((rr.stats or {}).get("steam_id"))) if (rr.stats or {}).get("steam_id") else None,
                    } for rr in roster_rows
                ],
            }
            return jsonify({"session": resp})

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
        from app.models import TeamPickSession, TeamPickParticipant, SessionPlayer, Session, SitePresence
        from sqlalchemy import select as _select
        with session_scope() as db:
            # Only allow for PreGame sessions
            sess_row = db.get(Session, session_id)
            if not sess_row or (sess_row.state or '').lower() != 'pregame'.lower():
                return jsonify({"ok": False, "error": "not_pregame"}), 400
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
            # Require both commanders to be recently present on the site (signed in)
            try:
                from datetime import datetime as _dt, timedelta as _td
                cutoff = _dt.utcnow() - _td(seconds=20)
                present_ids: set[str] = set()
                present_rows = db.execute(
                    _select(SitePresence).where(
                        (SitePresence.provider == 'steam') & (SitePresence.last_seen_at >= cutoff) & (SitePresence.external_id.in_([str(cmd1), str(cmd2)]))
                    )
                ).scalars().all()
                for pr in present_rows:
                    present_ids.add(str(pr.external_id))
                # Always count the caller as present if they are one of the commanders (even if heartbeat hasn't arrived yet)
                if creator_provider == 'steam' and str(creator_external) in (str(cmd1), str(cmd2)):
                    present_ids.add(str(creator_external))
                if len(present_ids) < 2:
                    return jsonify({"ok": False, "error": "both_commanders_required"}), 400
            except Exception:
                pass
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

    @app.post("/api/v1/team_picker/<path:session_id>/restart")
    def team_picker_restart(session_id: str):
        # Commander-only: cancel any existing pick session and start a new one with same commanders (or inferred)
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        creator_provider, creator_external = uid.split(":", 1)
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant, Session, SessionPlayer
        from sqlalchemy import select as _select
        with session_scope() as db:
            sess_row = db.get(Session, session_id)
            if not sess_row or (sess_row.state or '').lower() != 'pregame'.lower():
                return jsonify({"ok": False, "error": "not_pregame"}), 400
            # Find existing pick session (any state), and extract commanders if present
            existing = db.execute(
                _select(TeamPickSession).where(TeamPickSession.session_id == session_id).order_by(TeamPickSession.id.desc())
            ).scalars().first()
            cmd1 = None; cmd2 = None
            if existing:
                parts = db.execute(
                    _select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == existing.id)
                ).scalars().all()
                for pr in parts:
                    if pr.role == 'commander1' and pr.provider == 'steam':
                        cmd1 = pr.external_id
                    elif pr.role == 'commander2' and pr.provider == 'steam':
                        cmd2 = pr.external_id
                # Cancel any open session
                if existing.state == 'open':
                    from datetime import datetime as _dt
                    existing.state = 'canceled'
                    existing.closed_at = _dt.utcnow()
            # Infer commanders if missing
            if not cmd1 or not cmd2:
                rows = db.execute(
                    _select(SessionPlayer).where(SessionPlayer.session_id == session_id).order_by(SessionPlayer.slot.asc())
                ).scalars().all()
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
            # Ensure caller is one of the commanders
            if creator_provider == 'steam' and str(creator_external) not in (str(cmd1), str(cmd2)):
                return jsonify({"ok": False, "error": "forbidden"}), 403
            # Create new pick session
            tps = TeamPickSession(
                session_id=session_id,
                state="open",
                created_by_provider=creator_provider,
                created_by_external_id=creator_external,
            )
            db.add(tps)
            db.flush()
            db.add(TeamPickParticipant(pick_session_id=tps.id, provider='steam', external_id=str(cmd1), role='commander1'))
            db.add(TeamPickParticipant(pick_session_id=tps.id, provider='steam', external_id=str(cmd2), role='commander2'))
        try:
            if socketio:
                socketio.emit("team_picker:update", {"session_id": session_id, "action": "restart"}, room=f"team_picker:{session_id}", broadcast=True)
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
        from sqlalchemy import select as _select, text as _text
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
            winner = 1 if secrets.randbits(1) == 0 else 2
            # Atomic compare-and-set to avoid race
            r = db.execute(_text(
                """
                UPDATE team_pick_sessions SET coin_winner_team = :w
                WHERE id = :id AND state = 'open' AND coin_winner_team IS NULL
                """
            ), {"w": winner, "id": tps.id})
            if getattr(r, "rowcount", 0) != 1:
                return jsonify({"ok": False, "error": "already_tossed"}), 400
            tps.coin_winner_team = winner
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
            # Enforce team cap (max 5 including commander => at most 4 picks per team)
            team_counts = {1: 0, 2: 0}
            for e in existing:
                team_counts[e.team_id] = team_counts.get(e.team_id, 0) + 1
            if team_counts.get(next_team, 0) >= 4:
                return jsonify({"ok": False, "error": "team_full"}), 400
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
            else:
                # Dev convenience: in mock sessions, auto-accept the other commander
                if (settings.flask_env or "production").lower() != "production" and str(session_id).startswith("Dev:TP:"):
                    if part.role == "commander1":
                        tps.accepted_by_commander2 = True
                    elif part.role == "commander2":
                        tps.accepted_by_commander1 = True
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

    @app.post("/api/v1/team_picker/<path:session_id>/presence")
    def team_picker_presence(session_id: str):
        uid = session.get('uid')
        if not uid:
            return jsonify({"ok": False, "error": "not_authenticated"}), 401
        provider, external = uid.split(":", 1)
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant
        from sqlalchemy import select as _select
        with session_scope() as db:
            tps = db.execute(
                _select(TeamPickSession).where(TeamPickSession.session_id == session_id, TeamPickSession.state == 'open')
            ).scalars().first()
            if not tps:
                return jsonify({"ok": False})
            part = db.execute(
                _select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id, TeamPickParticipant.provider == provider, TeamPickParticipant.external_id == external)
            ).scalars().first()
            if not part:
                return jsonify({"ok": False, "error": "forbidden"}), 403
        from time import time as _time
        presence = app.config.get('TEAM_PICK_PRESENCE', {})
        presence[f"{session_id}:{provider}:{external}"] = _time()
        app.config['TEAM_PICK_PRESENCE'] = presence
        try:
            if socketio:
                socketio.emit("team_picker:presence", {"session_id": session_id}, room=f"team_picker:{session_id}", broadcast=True)
        except Exception:
            pass
        return jsonify({"ok": True})

    @app.get("/api/v1/team_picker/open_for_me")
    def team_picker_open_for_me():
        uid = session.get('uid')
        if not uid:
            return jsonify({"items": []})
        provider, external = uid.split(":", 1)
        from app.db import session_scope
        from app.models import TeamPickSession, TeamPickParticipant, Identity, Player, Session
        from sqlalchemy import select as _select
        from datetime import datetime as _dt, timedelta as _td
        with session_scope() as db:
            rows = db.execute(
                _select(TeamPickSession, TeamPickParticipant)
                .where(TeamPickSession.state == 'open')
                .join(TeamPickParticipant, TeamPickParticipant.pick_session_id == TeamPickSession.id)
                .join(Session, Session.id == TeamPickSession.session_id)
                .where(Session.state == 'PreGame')
            ).all()
            sessions: dict[str, dict] = {}
            for tps, part in rows:
                if part.provider == provider and part.external_id == external and part.role in ("commander1", "commander2"):
                    # Do not prompt the creator of the Team Picker session about their own start
                    if tps.created_by_provider == provider and tps.created_by_external_id == external:
                        continue
                    # Include created_at for recency filtering
                    sessions.setdefault(tps.session_id, {
                        "session_id": tps.session_id,
                        "state": tps.state,
                        "participants": [],
                        "created_by": {"provider": tps.created_by_provider, "id": tps.created_by_external_id},
                        "created_at_ts": (tps.created_at.timestamp() if getattr(tps, 'created_at', None) else 0)
                    })
            if not sessions:
                return jsonify({"items": []})
            ids = list(sessions.keys())
            parts = db.execute(
                _select(TeamPickSession, TeamPickParticipant)
                .where(TeamPickSession.session_id.in_(ids))
                .join(TeamPickParticipant, TeamPickParticipant.pick_session_id == TeamPickSession.id)
            ).all()
            steam_ids = [p.external_id for tps, p in parts if p.provider == 'steam']
            mapping = {}
            if steam_ids:
                idrows = db.execute(
                    _select(Identity, Player)
                    .where(Identity.provider == 'steam', Identity.external_id.in_(steam_ids))
                    .join(Player, Identity.player_id == Player.id, isouter=True)
                ).all()
                for ident, player in idrows:
                    mapping[str(ident.external_id)] = {
                        "id": str(ident.external_id),
                        "profile": ident.profile_url,
                        "nickname": (player.display_name if player else None),
                        "avatar": (player.avatar_url if player else None),
                    }
            presence = app.config.get('TEAM_PICK_PRESENCE', {})
            cutoff_ts = (_dt.utcnow() - _td(seconds=20)).timestamp()
            for tps, p in parts:
                if tps.session_id in sessions:
                    sessions[tps.session_id]["participants"].append({
                        "provider": p.provider,
                        "id": p.external_id,
                        "role": p.role,
                        "active": presence.get(f"{tps.session_id}:{p.provider}:{p.external_id}", 0) >= cutoff_ts,
                        "steam": mapping.get(str(p.external_id)) if p.provider == 'steam' else None,
                    })
            # Only notify when the other commander (creator) is present and the game is in PreGame
            filtered = []
            # Only show prompts for recently created Team Picker sessions to reflect a fresh "start" event
            PROMPT_WINDOW_SECONDS = 90
            now_ts = _dt.utcnow().timestamp()
            for item in sessions.values():
                my = next((pp for pp in item.get("participants", []) if pp.get("provider") == provider and str(pp.get("id")) == str(external) and pp.get("role") in ("commander1", "commander2")), None)
                if not my:
                    continue
                other = next((pp for pp in item.get("participants", []) if pp.get("role") in ("commander1", "commander2") and not (pp.get("provider") == provider and str(pp.get("id")) == str(external))), None)
                if not other:
                    continue
                # Must be created by the other commander
                created_by = item.get("created_by") or {}
                if not (created_by.get("provider") == other.get("provider") and str(created_by.get("id")) == str(other.get("id"))):
                    continue
                # Must be a recent start
                cat = float(item.get("created_at_ts") or 0)
                if (now_ts - cat) > PROMPT_WINDOW_SECONDS:
                    continue
                # Other commander must be active recently
                if not other.get("active"):
                    continue
                filtered.append(item)
            return jsonify({"items": filtered})

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
                # Remove any existing Team Picker sessions for this mock to ensure a clean start
                try:
                    from app.models import TeamPickSession as _TPS
                    from sqlalchemy import delete as _delete
                    db.execute(_delete(_TPS).where(_TPS.session_id == mock_id))
                except Exception:
                    pass
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
                # Seed 4 additional players per team (for STRAT 5 max with commanders)
                for i in range(2, 6):
                    upsert_player(i, 1, False, f"Player {i}", f"7656119900000000{i}")
                for i in range(7, 11):
                    upsert_player(i, 2, False, f"Player {i}", f"765611990000000{i}")
                # Ensure fake Steam identities exist for display (avatars/nicknames)
                from app.models import Identity, Player as _Player
                from sqlalchemy import select as _select2
                def ensure_identity(steam_id: str, display_name: str):
                    ident = db.execute(_select2(Identity).where(Identity.provider == "steam", Identity.external_id == str(steam_id))).scalar_one_or_none()
                    if ident is None:
                        p = _Player(display_name=display_name, avatar_url="/static/assets/placeholder-thumbnail-200x200.svg")
                        db.add(p); db.flush()
                        ident = Identity(player_id=p.id, provider="steam", external_id=str(steam_id), profile_url=f"https://steamcommunity.com/profiles/{steam_id}/")
                        db.add(ident)
                    else:
                        p = db.get(_Player, ident.player_id)
                        if p and not p.display_name:
                            p.display_name = display_name
                        if p and not p.avatar_url:
                            p.avatar_url = "/static/assets/placeholder-thumbnail-200x200.svg"
                    db.flush()
                if provider == "steam" and external_id:
                    ensure_identity(str(external_id), "You")
                ensure_identity("76561199000000000", "Commander 2")
                for i in range(2, 6):
                    ensure_identity(f"7656119900000000{i}", f"Player {i}")
                for i in range(7, 11):
                    ensure_identity(f"765611990000000{i}", f"Player {i}")
            try:
                if socketio:
                    socketio.emit("sessions:update", {"id": mock_id}, broadcast=True)
            except Exception:
                pass
            return jsonify({"ok": True, "session_id": mock_id})

        @app.post("/admin/dev/team_picker/<path:session_id>/auto_pick")
        def admin_dev_team_picker_auto_pick(session_id: str):
            # Auto-pick a random eligible player for the other commander (single-user testing helper)
            from app.db import session_scope
            from app.models import TeamPickSession, TeamPickPick, TeamPickParticipant, SessionPlayer
            from sqlalchemy import select as _select
            import random
            uid = session.get('uid')
            if not uid:
                return jsonify({"ok": False, "error": "not_authenticated"}), 401
            with session_scope() as db:
                tps = db.execute(
                    _select(TeamPickSession).where(TeamPickSession.session_id == session_id, TeamPickSession.state == "open")
                ).scalars().first()
                if not tps or tps.coin_winner_team is None:
                    return jsonify({"ok": False, "error": "not_ready"}), 400
                existing = db.execute(
                    _select(TeamPickPick).where(TeamPickPick.pick_session_id == tps.id).order_by(TeamPickPick.order_index.asc())
                ).scalars().all()
                # Determine whose turn
                next_team = tps.coin_winner_team if (len(existing) % 2 == 0) else (2 if tps.coin_winner_team == 1 else 1)
                # Auto-pick only if it's NOT the caller's team
                pvd, ext = uid.split(":", 1)
                my = db.execute(_select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id, TeamPickParticipant.provider == pvd, TeamPickParticipant.external_id == ext)).scalars().first()
                if my and ((my.role == "commander1" and next_team == 1) or (my.role == "commander2" and next_team == 2)):
                    return jsonify({"ok": False, "error": "your_turn"}), 400
                # Eligible roster = session players with steam_id not already picked
                picked_ids = set(p.player_steam_id for p in existing)
                roster = db.execute(_select(SessionPlayer).where(SessionPlayer.session_id == session_id)).scalars().all()
                # Exclude commanders from the pool
                commander_ids = set()
                parts = db.execute(_select(TeamPickParticipant).where(TeamPickParticipant.pick_session_id == tps.id)).scalars().all()
                for prt in parts:
                    if prt.role in ("commander1", "commander2") and prt.provider == "steam":
                        commander_ids.add(str(prt.external_id))
                pool = [str((r.stats or {}).get("steam_id"))
                        for r in roster
                        if (r.stats or {}).get("steam_id")
                        and str((r.stats or {}).get("steam_id")) not in picked_ids
                        and str((r.stats or {}).get("steam_id")) not in commander_ids]
                if not pool:
                    return jsonify({"ok": False, "error": "no_eligible"}), 400
                choice = random.choice(pool)
                # Reuse pick logic via insert
                from app.models import TeamPickPick as _Pick
                order_index = len(existing) + 1
                # Enforce cap
                team_counts = {1: 0, 2: 0}
                for e in existing:
                    team_counts[e.team_id] = team_counts.get(e.team_id, 0) + 1
                if team_counts.get(next_team, 0) >= 4:
                    return jsonify({"ok": False, "error": "team_full"}), 400
                db.add(_Pick(pick_session_id=tps.id, order_index=order_index, team_id=next_team, player_steam_id=choice, picked_by_provider="dev", picked_by_external_id="auto"))
            try:
                if socketio:
                    socketio.emit("team_picker:update", {"session_id": session_id, "action": "auto_pick"}, room=f"team_picker:{session_id}", broadcast=True)
            except Exception:
                pass
            return team_picker_get(session_id)

    return app


# WSGI entry point for Gunicorn
app = create_app()


