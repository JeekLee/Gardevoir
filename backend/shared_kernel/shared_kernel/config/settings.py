"""Application settings shared by every bounded context.

A BC subclasses ``BaseAppSettings`` and adds its own fields. Nested settings are
addressed with a double underscore, so the DSN comes from
``GARDEVOIR_DATABASE__DSN``.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DatabaseSettings(BaseModel):
    dsn: str
    echo: bool = False


class RedisSettings(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""


class ClickHouseSettings(BaseModel):
    host: str = "localhost"
    port: int = 8123
    user: str = "gardevoir"
    password: str = "gardevoir"
    database: str = "gardevoir"


class LogSettings(BaseModel):
    #: Validated up front so a typo fails at settings load with the field name
    #: attached, rather than inside configure_logging with "Unknown level".
    level: LogLevel = "INFO"
    json_output: bool = True

    @field_validator("level", mode="before")
    @classmethod
    def _normalise_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class BaseAppSettings(BaseSettings):
    app_name: str
    debug: bool = False

    database: DatabaseSettings
    clickhouse: ClickHouseSettings = Field(default_factory=ClickHouseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    log: LogSettings = Field(default_factory=LogSettings)

    model_config = SettingsConfigDict(
        env_prefix="GARDEVOIR_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )
