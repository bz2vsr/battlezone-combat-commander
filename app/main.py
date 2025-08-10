from flask import Flask, jsonify
from app.raknet import fetch_raknet_payload
from app.parser_bzcc import normalize_bzcc_sessions
from app.config import settings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.secret_key

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/api/v1/sessions/current")
    def sessions_current():
        try:
            payload = fetch_raknet_payload()
            if not payload:
                return jsonify({"sessions": []})
            sessions = normalize_bzcc_sessions(payload)
            return jsonify({"sessions": sessions})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 502

    return app


# WSGI entry point for Gunicorn
app = create_app()


