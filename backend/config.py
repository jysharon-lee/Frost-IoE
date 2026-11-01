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

    # Statutory Food Hygiene Thresholds 
    TEMP_SAFE_THRESHOLD: float = -18.0     
    TEMP_WARNING_THRESHOLD: float = -15.0  

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