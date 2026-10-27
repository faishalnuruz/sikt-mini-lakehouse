"""The immutable landing zone: an S3 bucket nothing overwrites.

Production SIKT lands CDC batches and file drops on S3 with versioning and a
lifecycle policy. Locally the same semantics run against LocalStack's S3 with
boto3 — the exact client code that would talk to Amazon S3 in production, which
is the point: swapping the endpoint must be the only change.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config

from sikt.config import SETTINGS


def client():
    """A boto3 S3 client pointed at the local landing endpoint."""
    return boto3.client(
        "s3",
        endpoint_url=SETTINGS.s3_endpoint,
        aws_access_key_id=SETTINGS.s3_access_key,
        aws_secret_access_key=SETTINGS.s3_secret_key,
        config=Config(s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def ensure_bucket(bucket: str | None = None) -> str:
    """Create the landing bucket with versioning, as an audit trail requires."""
    name = bucket or SETTINGS.landing_bucket
    s3 = client()
    existing = [item["Name"] for item in s3.list_buckets().get("Buckets", [])]
    if name not in existing:
        s3.create_bucket(Bucket=name)
    versioning = s3.get_bucket_versioning(Bucket=name)
    if versioning.get("Status") != "Enabled":
        s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    return name


def object_key(prefix: str, name: str, moment: datetime | None = None) -> str:
    """Partitioned key: prefix/year=YYYY/month=MM/name — the S3 layout from FR2."""
    moment = moment or datetime.now(UTC)
    return f"{prefix}/year={moment.year}/month={moment.month:02d}/{name}"


def write_batch(prefix: str, name: str, records: list[dict], moment: datetime | None = None) -> str:
    """Write one CDC batch as JSON lines and return its key.

    Each batch gets a unique key and is never rewritten: landing is append-only
    by convention, and bucket versioning catches anything that violates it.
    """
    s3 = client()
    bucket = SETTINGS.landing_bucket
    key = object_key(prefix, name, moment)
    body = "\n".join(json.dumps(record, default=str) for record in records) + ("\n" if records else "")
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode())
    return key


def list_objects(prefix: str) -> list[str]:
    """Every landed object under a prefix, oldest first."""
    s3 = client()
    response = s3.list_objects_v2(Bucket=SETTINGS.landing_bucket, Prefix=prefix)
    return sorted(item["Key"] for item in response.get("Contents", []))


def read_object(key: str) -> list[dict]:
    """Read one landed batch back as records."""
    s3 = client()
    body = s3.get_object(Bucket=SETTINGS.landing_bucket, Key=key)["Body"].read().decode()
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def local_batch_path(name: str) -> Path:
    """Where a file drop (the Oracle Aset export) waits before being landed."""
    SETTINGS.aset_dir.mkdir(parents=True, exist_ok=True)
    return SETTINGS.aset_dir / name
