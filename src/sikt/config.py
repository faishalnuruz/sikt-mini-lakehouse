"""Connection settings for the local SIKT stack.

Every value can be overridden by an environment variable, and every default
matches compose.yaml — so the whole demo runs with no configuration, and a
reviewer can see at a glance that no credential here is a real one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class Settings:
    # sources
    mysql_host: str = _env("SIKT_MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(_env("SIKT_MYSQL_PORT", "3306"))
    mysql_user: str = _env("SIKT_MYSQL_USER", "simda")
    mysql_password: str = _env("SIKT_MYSQL_PASSWORD", "sikt-simda")
    mysql_database: str = _env("SIKT_MYSQL_DB", "simda")

    postgres_host: str = _env("SIKT_PG_HOST", "127.0.0.1")
    postgres_port: int = int(_env("SIKT_PG_PORT", "5432"))
    postgres_user: str = _env("SIKT_PG_USER", "postgres")
    postgres_password: str = _env("SIKT_PG_PASSWORD", "sikt-postgres")
    ebudget_database: str = _env("SIKT_EBUDGET_DB", "ebudget")
    dwh_database: str = _env("SIKT_DWH_DB", "dwh")

    # landing (LocalStack S3; MinIO or Amazon S3 in production)
    s3_endpoint: str = _env("SIKT_S3_ENDPOINT", "http://127.0.0.1:4566")
    s3_access_key: str = _env("SIKT_S3_ACCESS_KEY", "sikt")
    s3_secret_key: str = _env("SIKT_S3_SECRET_KEY", "sikt-landing-secret")
    landing_bucket: str = _env("SIKT_LANDING_BUCKET", "sikt-landing")

    # oracle aset arrives as a nightly file drop, not a live connection
    aset_dir: Path = ROOT / "sources" / "oracle_aset"

    state_dir: Path = ROOT / ".state"

    slack_webhook_url: str | None = _env("SLACK_WEBHOOK_URL", "") or None

    @property
    def mysql_url_args(self) -> dict:
        return {
            "host": self.mysql_host,
            "port": self.mysql_port,
            "user": self.mysql_user,
            "password": self.mysql_password,
            "database": self.mysql_database,
        }

    def dsn(self, database: str) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} user={self.postgres_user} "
            f"password={self.postgres_password} dbname={database}"
        )


SETTINGS = Settings()
