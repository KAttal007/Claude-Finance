"""Immutable raw file store keyed by content hash (design doc 9.3).

Key layout: ``kind/yyyy/mm/sha256.ext``. Talks the S3 API through boto3, so MinIO locally and any
managed S3 service when hosted are a configuration change only. A local directory store is used
by tests and single-machine development.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from analekh.config import get_settings


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_key(kind: str, digest: str, ext: str, when: datetime | None = None) -> str:
    when = when or datetime.now(UTC)
    return f"{kind}/{when:%Y}/{when:%m}/{digest}.{ext.lstrip('.')}"


class ObjectStore(Protocol):
    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()


class S3Store:
    def __init__(self, client: Any = None) -> None:
        import boto3

        s = get_settings()
        self.bucket = s.minio_bucket
        scheme = "https" if s.minio_secure else "http"
        self.client = client or boto3.client(
            "s3",
            endpoint_url=f"{scheme}://{s.minio_endpoint}",
            aws_access_key_id=s.minio_access_key,
            aws_secret_access_key=s.minio_secret_key,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        if not self.exists(key):
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        body: bytes = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


def default_store() -> ObjectStore:
    return S3Store()
