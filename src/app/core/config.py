from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "travel-agent"
    debug: bool = False

    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "travel_agent"

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    cookie_name: str = "access_token"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # Duffel flight search. SecretStr keeps the key out of logs and error dumps.
    duffel_api_key: SecretStr | None = None
    duffel_api_url: str = "https://api.duffel.com"
    duffel_api_version: str = "v2"
    duffel_timeout_seconds: float = 30.0

    # parse.bot hotel search. One scraper exposes both operations we use
    # (autocomplete_destination and search_hotels), hence a single id.
    # Scraping is slower than a JSON API, so the timeout is higher than Duffel's.
    parsebot_api_key: SecretStr | None = None
    parsebot_api_url: str = "https://api.parse.bot"
    parsebot_hotel_scraper_id: str
    parsebot_timeout_seconds: float = 60.0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
