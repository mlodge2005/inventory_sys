"""Environment configuration. Secrets are not stored here or in the database."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INVENTORY_",
        extra="ignore",
    )

    environment: str = "development"
    database_path: Path = Path("data/inventory.db")
    backup_dir: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origins: str = ""
    public_url: str = ""
    frontend_dist: Path | None = None
    log_level: str = "info"
    max_body_bytes: int = 2_000_000
    auto_migrate: bool = False

    @field_validator("port")
    @classmethod
    def _port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("port must be between 1 and 65535")
        return value

    @field_validator("environment")
    @classmethod
    def _environment(cls, value: str) -> str:
        allowed = {"development", "test", "production"}
        if value not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}")
        return value

    @property
    def resolved_database_path(self) -> Path:
        return self.database_path.expanduser().resolve()

    @property
    def resolved_backup_dir(self) -> Path:
        if self.backup_dir is not None:
            return self.backup_dir.expanduser().resolve()
        return self.resolved_database_path.parent / "backups"

    @property
    def resolved_frontend_dist(self) -> Path:
        if self.frontend_dist is not None:
            return self.frontend_dist.expanduser().resolve()
        return Path(__file__).resolve().parents[3] / "frontend" / "dist"

    @property
    def sqlalchemy_url(self) -> str:
        # sqlite:////absolute/path — Path.as_posix() already starts with /.
        return "sqlite:///" + self.resolved_database_path.as_posix()

    @property
    def allowed_origins_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
