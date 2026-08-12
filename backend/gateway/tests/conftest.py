import os

_DEFAULTS = {
    "GARDEVOIR_APP_NAME": "gateway",
    "GARDEVOIR_DATABASE__DSN": (
        "postgresql+psycopg://gardevoir:gardevoir@localhost:21010/gardevoir"
    ),
    "GARDEVOIR_CLICKHOUSE__HOST": "localhost",
    "GARDEVOIR_CLICKHOUSE__PORT": "21020",
    "GARDEVOIR_CLICKHOUSE__USER": "gardevoir",
    "GARDEVOIR_CLICKHOUSE__PASSWORD": "gardevoir",
    "GARDEVOIR_CLICKHOUSE__DATABASE": "gardevoir",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
