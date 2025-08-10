import os
from dotenv import load_dotenv

# Load .env automatically for local/dev usage
load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.flask_env = os.getenv("FLASK_ENV", "production")
        self.secret_key = os.getenv("SECRET_KEY", "dev")

        self.app_base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000")
        self.ws_allowed_origins = [s.strip() for s in os.getenv("WS_ALLOWED_ORIGINS", self.app_base_url).split(",") if s.strip()]

        self.raknet_url = os.getenv("RAKNET_URL")
        self.getdata_base = os.getenv("GETDATA_ENDPOINT_BASE")

        self.poll_interval_seconds = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
        self.enrichment_enabled = os.getenv("ENRICHMENT_ENABLED", "true").lower() == "true"

        self.assets_storage = os.getenv("ASSETS_STORAGE", "file")
        self.assets_cdn_base = os.getenv("ASSETS_CDN_BASE", "")

        self.database_url = os.getenv("DATABASE_URL")
        self.redis_url = os.getenv("REDIS_URL")

        self.steam_api_key = os.getenv("STEAM_API_KEY", "")
        self.gog_client_id = os.getenv("GOG_CLIENT_ID", "")
        self.gog_client_secret = os.getenv("GOG_CLIENT_SECRET", "")


settings = Settings()


