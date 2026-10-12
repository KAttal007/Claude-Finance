"""Immutable raw file store keyed by content hash (design doc 7.2).

Key layout: ``kind/yyyy/mm/sha256.ext``. MinIO in Docker; a local directory for tests and dev.
"""

import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from t2r.config import get_settings


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


class MinioStore:
    def __init__(self) -> None:
        from minio import Minio

        s = get_settings()
        self.bucket = s.minio_bucket
        self.client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        if not self.exists(key):
            self.client.put_object(
                self.bucket, key, io.BytesIO(data), len(data), content_type=content_type
            )

    def get(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self.client.stat_object(self.bucket, key)
            return True
        except S3Error:
            return False


def default_store() -> ObjectStore:
    return MinioStore()
