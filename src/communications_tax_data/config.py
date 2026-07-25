from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CTD_",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str | None = "sqlite:///./communications_tax_data.sqlite3"
    db_host: str | None = None
    db_port: int = 3306
    db_name: str = "apeirondb"
    db_user: str | None = None
    db_password: str | None = Field(default=None, repr=False)

    avalara_host: str = "10.3.201.136"
    avalara_port: int = 3306
    avalara_name: str = "apeiron"
    avalara_user: str | None = None
    avalara_password: str | None = Field(default=None, repr=False)

    http_timeout_seconds: float = 60.0
    user_agent: str = "Apeiron-CommunicationsTaxData/0.1 (+taxdata@apeiron.io)"
    log_level: str = "INFO"

    def primary_url(self) -> str | URL:
        if self.db_host:
            if not self.db_user:
                raise ValueError("CTD_DB_USER is required when CTD_DB_HOST is set")
            return URL.create(
                "mysql+pymysql",
                username=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                query={"charset": "utf8mb4"},
            )
        if not self.database_url:
            raise ValueError("Set CTD_DATABASE_URL or CTD_DB_HOST")
        return self.database_url

    def benchmark_url(self) -> URL:
        if not self.avalara_user or self.avalara_password is None:
            raise ValueError("CTD_AVALARA_USER and CTD_AVALARA_PASSWORD are required")
        return URL.create(
            "mysql+pymysql",
            username=self.avalara_user,
            password=self.avalara_password,
            host=self.avalara_host,
            port=self.avalara_port,
            database=self.avalara_name,
            query={"charset": "utf8mb3"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
