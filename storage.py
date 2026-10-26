"""Where study documents are kept: a local folder (default) or an Amazon S3 bucket.

Both stores expose the same four things, so the rest of the app doesn't care which one is used:
    list_documents() -> list[DocInfo]
    save_document(name, data) -> saved_name
    load_document(name) -> bytes
    description (str)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from errors import friendly_aws_message

MAX_UPLOAD_MB = 15
ALLOWED_EXTENSIONS = {".pdf", ".txt"}  # .txt is only used for the bundled sample notes


class StorageError(Exception):
    """Raised with a message that is safe and helpful to show to the user."""


@dataclass(frozen=True)
class DocInfo:
    name: str
    size: int
    version: str  # changes whenever the file changes (used to know when to re-index)


def safe_filename(name: str) -> str:
    """Strip folders and odd characters so a file name can't escape the storage location."""
    base = os.path.basename(name.replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)
    base = re.sub(r"\s+", " ", base).strip(" .")
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise StorageError(f"'{name}' is not a supported file type. Please upload a PDF.")
    if not stem:
        raise StorageError("The file name is empty after cleaning. Please rename the file.")
    return stem[:100] + ext


def validate_upload(name: str, data: bytes) -> str:
    """Check size and type. Returns the cleaned file name or raises StorageError."""
    clean = safe_filename(name)
    if not data:
        raise StorageError(f"'{name}' is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise StorageError(f"'{name}' is larger than {MAX_UPLOAD_MB} MB. Please upload a smaller file.")
    if clean.endswith(".pdf") and b"%PDF" not in data[:1024]:
        raise StorageError(f"'{name}' does not look like a real PDF file.")
    return clean


class LocalStore:
    """Keeps documents in a folder on your computer. No AWS needed."""

    kind = "local"

    def __init__(self, root: str | os.PathLike = "data/local_docs"):
        self.root = Path(root)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"Could not create the local folder '{self.root}': {exc}") from exc

    @property
    def description(self) -> str:
        return f"Local folder ({self.root}) - no AWS needed"

    def list_documents(self) -> list[DocInfo]:
        docs = []
        for path in sorted(self.root.iterdir()):
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
                stat = path.stat()
                docs.append(DocInfo(path.name, stat.st_size, f"{stat.st_mtime_ns}-{stat.st_size}"))
        return docs

    def save_document(self, name: str, data: bytes) -> str:
        clean = validate_upload(name, data)
        try:
            (self.root / clean).write_bytes(data)
        except OSError as exc:
            raise StorageError(f"Could not save '{clean}': {exc}") from exc
        return clean

    def load_document(self, name: str) -> bytes:
        path = self.root / safe_filename(name)
        if not path.is_file():
            raise StorageError(f"Document '{name}' was not found.")
        return path.read_bytes()


class S3Store:
    """Keeps documents in an Amazon S3 bucket (needs AWS credentials)."""

    kind = "s3"

    def __init__(self, bucket: str, prefix: str = "studymate/", region: str | None = None, client=None):
        if not bucket:
            raise StorageError(
                "STUDYMATE_STORAGE is 's3' but STUDYMATE_S3_BUCKET is empty. "
                "Set it in .env (see AWS_SETUP.md) or switch back to STUDYMATE_STORAGE=local."
            )
        self.bucket = bucket
        prefix = prefix.lstrip("/")
        self.prefix = prefix if (not prefix or prefix.endswith("/")) else prefix + "/"
        self.region = region
        self._client = client

    @property
    def description(self) -> str:
        return f"Amazon S3 bucket '{self.bucket}' (prefix '{self.prefix}')"

    def _s3(self):
        if self._client is None:
            try:
                import boto3

                self._client = boto3.client("s3", region_name=self.region)
            except Exception as exc:  # e.g. NoRegionError, ProfileNotFound
                raise StorageError(friendly_aws_message(exc) or f"Could not start S3 client: {exc}") from exc
        return self._client

    @staticmethod
    def _wrap(exc: Exception) -> StorageError:
        return StorageError(friendly_aws_message(exc) or f"S3 error: {exc}")

    def list_documents(self) -> list[DocInfo]:
        s3 = self._s3()
        docs: list[DocInfo] = []
        token = None
        try:
            while True:
                kwargs = {"Bucket": self.bucket, "Prefix": self.prefix}
                if token:
                    kwargs["ContinuationToken"] = token
                resp = s3.list_objects_v2(**kwargs)
                for obj in resp.get("Contents", []):
                    name = obj["Key"][len(self.prefix):]
                    if not name or "/" in name:
                        continue
                    if os.path.splitext(name)[1].lower() not in ALLOWED_EXTENSIONS:
                        continue
                    docs.append(DocInfo(name, obj["Size"], f"{obj.get('ETag', '')}-{obj['Size']}"))
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break
        except StorageError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc
        return sorted(docs, key=lambda d: d.name)

    def save_document(self, name: str, data: bytes) -> str:
        clean = validate_upload(name, data)
        content_type = "application/pdf" if clean.endswith(".pdf") else "text/plain"
        try:
            self._s3().put_object(
                Bucket=self.bucket,
                Key=self.prefix + clean,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except StorageError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc
        return clean

    def load_document(self, name: str) -> bytes:
        try:
            resp = self._s3().get_object(Bucket=self.bucket, Key=self.prefix + safe_filename(name))
            return resp["Body"].read()
        except StorageError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc


def get_store():
    """Pick the storage backend from environment variables (default: local, no AWS)."""
    mode = os.getenv("STUDYMATE_STORAGE", "local").strip().lower()
    if mode == "s3":
        return S3Store(
            bucket=os.getenv("STUDYMATE_S3_BUCKET", "").strip(),
            prefix=os.getenv("STUDYMATE_S3_PREFIX", "studymate/"),
            region=os.getenv("AWS_REGION") or None,
        )
    if mode != "local":
        raise StorageError(f"STUDYMATE_STORAGE must be 'local' or 's3', not '{mode}'.")
    return LocalStore(os.getenv("STUDYMATE_LOCAL_DIR", "data/local_docs"))
