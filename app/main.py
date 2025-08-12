from flask import Flask, jsonify, request, Response, stream_with_context, render_template
import json
import time
from app.store import get_current_sessions, get_session_detail, get_history_summary, get_maps_summary, get_mods_summary
from app.migrate import create_all, ensure_alter_tables
from app.config import settings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.secret_key

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

    @app.get("/")
    def index():
        return render_template("index.html")

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


