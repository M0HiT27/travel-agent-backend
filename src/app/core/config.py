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

    # parse.bot redbus.com scraper. This is a separate scraper from the hotel one.
    parsebot_redbus_scraper_id: str

    # Gemini powers both the embeddings and the chat model for the RAG assistant.
    # 1536 dimensions rather than the model's native 3072: pgvector's HNSW/IVFFlat
    # indexes only support up to 2000, and this model truncates cleanly.
    # Changing the model or the dimension means re-ingesting every document.
    gemini_api_key: SecretStr | None = None
    gemini_embedding_model: str = "models/gemini-embedding-001"
    gemini_embedding_dimensions: int = 1536
    # Pinned rather than an alias like "gemini-flash-latest", so a model change is a
    # deliberate edit and not a surprise. gemini-2.5-flash is closed to new API keys.
    # Free-tier request quotas are counted per model, so switching models is also the
    # fastest way out of a 429. gemini-2.5-flash is closed to new API keys.
    gemini_chat_model: str = "gemini-3.6-flash"

    # Where ingested policy documents are stored and searched.
    documents_dir: str = "data/policies"
    vector_collection_name: str = "travel_policies"

    # Browser origins allowed to call this API. Comma-separated in .env.
    # These must be listed exactly: auth is cookie-based, and a browser refuses to send
    # cookies cross-origin to a wildcard "*". Defaults cover the usual Vite and CRA
    # dev servers; add the real domain before deploying.
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
