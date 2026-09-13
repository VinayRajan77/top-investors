from pydantic import field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://topinvestors:topinvestors@postgres:5432/topinvestors"
    redis_url: str = "redis://redis:6379/0"
    admin_refresh_token: str = "change-me"
    sec_user_agent: str = "Top Investors contact@example.com"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @field_validator("database_url")
    @classmethod
    def render_postgres_url(cls, value: str) -> str:
        """Render supplies a standard Postgres URL; this app uses psycopg v3."""
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value
    class Config: env_file = ".env"
settings = Settings()
