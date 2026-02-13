from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PORT: int = 9000
    BASE_PATH: str = "/gta"
    TZ: str = "Asia/Shanghai"
    JOBS_ENABLED: bool = True
    JOB_RETENTION_DAYS: int = 30
    JOB_WARMUP_ON_START: bool = True

    # Optional LLM (for Insight generation)
    INSIGHT_LLM_PROVIDER: str = "openai"  # openai|gemini|none
    INSIGHT_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@db:5432/dbname
    DATABASE_URL: str = "postgresql+psycopg://gta:gta@db:5432/gta"


settings = Settings()
