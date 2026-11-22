import urllib.parse
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # InfluxDB Cloud credentials
    INFLUX_HOST: str = "https://us-east-1-1.aws.cloud2.influxdata.com"
    INFLUX_ORG: str = "Swinburne%20University"
    INFLUX_BUCKET: str = "FROST-IoE"
    INFLUX_TOKEN: str = ""

    USE_MOCK_DATA: bool = True

    # Newest reading older than this = node offline (no value, NO_DATA). 3x the MCU POLL_MS (10 s).
    STALE_AFTER_S: int = 30

    # Per-client zones/nodes/limits (relative to backend/). See sites/demo.json.
    SITE_CONFIG: str = "sites/demo.json"

    # Notification & Alert Engine Settings
    ALERTS_ENABLED: bool = True
    ALERT_POLL_INTERVAL_S: int = 60
    SUSTAINED_BREACH_MINUTES: float = 10.0
    OFFLINE_ALERT_AFTER_S: int = 180
    FORECAST_ALERTS_ENABLED: bool = True
    FORECAST_WARNING_MINUTES: float = 20.0

    # Email (SMTP) Settings
    EMAIL_ALERTS_ENABLED: bool = False
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USE_TLS: bool = True
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    ALERT_FROM_EMAIL: str = ""
    ALERT_RECIPIENTS: List[str] = []

    # Server & CORS Settings (allow frontend to connect)
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def clean_org(self) -> str:
        """Decodes URL-encoded org (e.g. 'Swinburne%20University' -> 'Swinburne University')"""
        return urllib.parse.unquote(self.INFLUX_ORG)

settings = Settings()