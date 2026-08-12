"""Centralised application configuration.

Every environment variable the app needs is declared here exactly once.
Nothing else in the codebase should call os.environ directly — import
`settings` from this module instead. That gives us one place to look when
we ask "where does this value come from?".
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    APP_NAME: str = "AI Productivity Agents API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # ---- Groq (required from Phase 4 onwards) ----
    # No default value: a fake API key is worse than no API key, because it
    # turns a clear "missing config" error into a confusing "401 from Groq".
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ---- MongoDB Atlas (required from Phase 3 onwards) ----
    MONGODB_URI: str | None = None
    MONGODB_DB_NAME: str = "ai_productivity_agents"

    # ---- Authentication (required from Phase 8 onwards) ----
    JWT_SECRET: str | None = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # ---- CORS ----
    # Stored as a comma-separated string rather than a list. pydantic-settings
    # tries to JSON-decode list fields, so `CORS_ORIGINS=http://localhost:5173`
    # in a .env file would raise a parse error. Splitting it ourselves keeps
    # the .env file readable.
    CORS_ORIGINS: str = "http://localhost:5173"

    # ---- Uploads ----
    MAX_UPLOAD_MB: int = 10

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS split into the list FastAPI's middleware expects."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        """MAX_UPLOAD_MB converted to bytes, for comparing against file sizes."""
        return self.MAX_UPLOAD_MB * 1024 * 1024

    def missing_secrets(self) -> list[str]:
        """Names of secrets that are not configured yet.

        Used only to print a startup warning. These are optional during
        Phase 2 and become required as later phases land.
        """
        required = {
            "GROQ_API_KEY": self.GROQ_API_KEY,
            "MONGODB_URI": self.MONGODB_URI,
            "JWT_SECRET": self.JWT_SECRET,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton.

    lru_cache means the .env file is read once per process rather than on
    every import, and every module shares the same object.
    """
    return Settings()


settings = get_settings()
