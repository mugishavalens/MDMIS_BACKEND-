"""Organisation-scoped storage for raw sensor files (REQ-ING-007).

Keys are always built by the server as org/<org_id>/sensor-files/<yyyy>/<mm>/<uuid>/<name>,
so one organisation's files can never be addressed under another's path.
"""
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

DOWNLOAD_URL_TTL_SECONDS = 15 * 60  # REQ-ING-007: presigned URLs valid 15 minutes max


def build_key(org_id: uuid.UUID, filename: str) -> str:
    now = datetime.now(timezone.utc)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in Path(filename).name)[:120] or "file"
    return f"org/{org_id}/sensor-files/{now:%Y}/{now:%m}/{uuid.uuid4()}/{safe}"


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key.")
        return path

    def save(self, key: str, src_path: str) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_path, dest)

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def presigned_url(self, key: str, filename: str) -> str | None:
        return None  # served by the API instead, behind a short-lived token

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    def __init__(self):
        import boto3  # imported lazily so local development doesn't need S3 configured

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    def save(self, key: str, src_path: str) -> None:
        self.client.upload_file(src_path, self.bucket, key)

    def local_path(self, key: str) -> Path | None:
        return None

    def presigned_url(self, key: str, filename: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_storage = None


def get_storage():
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.storage_backend == "s3" else LocalStorage(settings.storage_dir)
    return _storage
