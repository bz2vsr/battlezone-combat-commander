from flask import Flask, jsonify
from app.config import settings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.secret_key

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    return app


# WSGI entry point for Gunicorn
app = create_app()


