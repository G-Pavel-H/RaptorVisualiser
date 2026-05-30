from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = ""
    mongodb_uri: str = ""
    mongodb_db: str = "raptor_viz"
    frontend_origin: str = "http://localhost:4200"

    # Spend caps (USD). Refused at SAFETY_MARGIN * cap (e.g. 0.9 * cap).
    daily_usd_cap: float = 1.0
    per_ip_usd_cap: float = 0.1
    safety_margin: float = 0.9

    # Concurrency ceiling across every OpenAI call from every build.
    openai_max_concurrency: int = 8

    # Max characters accepted in a single build's input.
    max_input_chars: int = 20_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
