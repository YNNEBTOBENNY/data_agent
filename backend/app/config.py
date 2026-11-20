from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 固定用 backend 目录下的，避免因 cwd 不同读不到配置
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "dev"
    secret_key: str = "change-me-in-production"
    token_ttl_hours: int = 8

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_timeout_seconds: int = 60

    meta_db_url: str = "sqlite:///./data/meta.db"

    sensitive_keywords: str = "password,token,secret,api_key,access_key,private_key,id_card,credit_card"

    @property
    def sensitive_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.sensitive_keywords.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
