"""Application settings shared by every bounded context.

A BC subclasses ``BaseAppSettings`` and adds its own fields. Nested settings are
addressed with a double underscore, so the DSN comes from
``GARDEVOIR_DATABASE__DSN``.
"""

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    dsn: str
    echo: bool = False


class ClickHouseSettings(BaseModel):
    host: str = "localhost"
    port: int = 8123
    user: str = "gardevoir"
    password: str = "gardevoir"
    database: str = "gardevoir"


class LogSettings(BaseModel):
    level: str = "INFO"
    json_output: bool = True


class BaseAppSettings(BaseSettings):
    app_name: str
    debug: bool = False

    database: DatabaseSettings
    clickhouse: ClickHouseSettings = Field(default_factory=ClickHouseSettings)
    log: LogSettings = Field(default_factory=LogSettings)

    model_config = SettingsConfigDict(
        env_prefix="GARDEVOIR_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )
