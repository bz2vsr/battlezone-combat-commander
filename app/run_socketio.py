import os

# Apply eventlet monkey patching BEFORE importing the app/socketio
import eventlet
eventlet.monkey_patch()

from app.main import app, socketio


def main() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(app, host=host, port=port)


if __name__ == "__main__":
    main()


