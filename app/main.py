from flask import Flask, jsonify, request
from app.store import get_current_sessions, get_session_detail
from app.config import settings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.secret_key

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/api/v1/sessions/current")
    def sessions_current():
        # Basic filter: ?state=InGame (case-insensitive)
        state = request.args.get("state")
        sessions = get_current_sessions()
        if state:
            s_norm = state.strip().lower()
            sessions = [s for s in sessions if (s.get("state") or "").lower() == s_norm]
        return jsonify({"sessions": sessions})

    @app.get("/api/v1/sessions/<path:sid>")
    def session_detail(sid: str):
        data = get_session_detail(sid)
        if data is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(data)

    return app


# WSGI entry point for Gunicorn
app = create_app()


