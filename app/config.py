from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PORT: int = 9000
    BASE_PATH: str = "/gta"
    TZ: str = "Asia/Shanghai"

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@db:5432/dbname
    DATABASE_URL: str = "postgresql+psycopg://gta:gta@db:5432/gta"


settings = Settings()
