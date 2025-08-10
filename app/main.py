from flask import Flask, jsonify
from app.store import get_current_sessions
from app.config import settings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.secret_key

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/api/v1/sessions/current")
    def sessions_current():
        sessions = get_current_sessions()
        return jsonify({"sessions": sessions})

    return app


# WSGI entry point for Gunicorn
app = create_app()


