from __future__ import annotations

from datetime import timedelta
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from google.cloud import storage
import google.auth
import google.auth.impersonated_credentials

from .config import get_settings


@runtime_checkable
class StorageBackend(Protocol):
    """
    Minimal, unit-testable storage interface.

    Implementations must NOT log or inspect raw file contents beyond what is
    strictly necessary for upload, to preserve privacy guarantees.
    """

    def upload_raw_artifact(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        document_id: str,
        content_type: str | None = None,
    ) -> str:
        """
        Upload a raw artifact and return its GCS URI.
        """

    def generate_signed_url(
        self,
        object_path: str,
        content_type: str,
        expiration: timedelta,
        method: str = "PUT",
    ) -> str:
        """
        Generates a V4 signed URL for the given object path.
        """
        ...


@dataclass
class GCSStorage(StorageBackend):
    """
    Google Cloud Storage implementation using Application Default Credentials.

    Bucket name is read from environment via Settings.GCS_BUCKET. No key files
    are referenced in code; authentication is handled entirely by ADC.
    """

    bucket_name: str
    signer_email: str | None = None

    def __post_init__(self) -> None:
        if not self.bucket_name:
            raise RuntimeError("GCS_BUCKET is not configured")

        credentials = None
        if self.signer_email:
            # Use Impersonated Credentials for Signed URLs on Cloud Run
            # (Compute Engine credentials lack private keys)
            try:
                source_credentials, _ = google.auth.default()
                credentials = google.auth.impersonated_credentials.Credentials(
                    source_credentials=source_credentials,
                    target_principal=self.signer_email,
                    target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    lifetime=3600
                )
            except Exception as e:
                # Fallback or log? If user configured signer_email, they likely expect it to work.
                # But to avoid crashing if local without permissions?
                # We raise to fail fast.
                raise RuntimeError(f"Failed to create impersonated credentials for {self.signer_email}: {e}")

        # Construct a client using Application Default Credentials OR Impersonated Creds.
        self._client = storage.Client(credentials=credentials)
        self._bucket = self._client.bucket(self.bucket_name)

    @classmethod
    def from_settings(cls, settings) -> GCSStorage:
        return cls(
            bucket_name=settings.GCS_BUCKET,
            signer_email=settings.SIGNED_URL_SIGNER_SA
        )

    def upload_raw_artifact(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        document_id: str,
        content_type: str | None = None,
    ) -> str:
        # Normalize path segments to simple strings; callers should provide
        # UUIDs as strings. We do not log or otherwise expose file_bytes.
        user_segment = str(user_id)
        document_segment = str(document_id)

        object_path = f"{user_segment}/{document_segment}/{filename}"
        blob = self._bucket.blob(object_path)

        # NOTE: We intentionally avoid logging file contents for privacy.
        blob.upload_from_string(file_bytes, content_type=content_type)

        return f"gs://{self.bucket_name}/{object_path}"

    def generate_signed_url(
        self,
        object_path: str,
        content_type: str,
        expiration: timedelta,
        method: str = "PUT",
    ) -> str:
        blob = self._bucket.blob(object_path)
        
        # Use V4 signing. The environment (Service Account) must have token creator permissions.
        url = blob.generate_signed_url(
            version="v4",
            expiration=expiration,
            method=method,
            content_type=content_type,
        )
        return url


class InMemoryStorageMock(StorageBackend):
    """
    Simple in-memory storage mock for unit tests and local development.

    Stores artifacts in a dictionary keyed by their synthetic GCS URI.
    This is intentionally minimal and does not persist across process restarts.
    """

    def __init__(self, bucket_name: str = "mock-bucket") -> None:
        self.bucket_name = bucket_name
        self._store: dict[str, bytes] = {}

    def upload_raw_artifact(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        document_id: str,
        content_type: str | None = None,
    ) -> str:
        user_segment = str(user_id)
        document_segment = str(document_id)
        object_path = f"{user_segment}/{document_segment}/{filename}"

        uri = f"gs://{self.bucket_name}/{object_path}"
        # Store bytes in-memory; never log contents.
        self._store[uri] = file_bytes
        self._store[uri] = file_bytes
        return uri

    def generate_signed_url(
        self,
        object_path: str,
        content_type: str,
        expiration: timedelta,
        method: str = "PUT",
    ) -> str:
        return f"http://mock-storage/{self.bucket_name}/{object_path}?signed=true"

    def get_object(self, uri: str) -> bytes | None:
        """
        Test-only helper to retrieve stored bytes by URI.
        """

        return self._store.get(uri)


def get_default_storage() -> StorageBackend:
    """
    Factory for the default storage backend.

    In production this returns a GCS-backed implementation; tests can
    inject `InMemoryStorageMock` directly without touching configuration.
    """

    settings = get_settings()
    if not settings.GCS_BUCKET:
        raise RuntimeError("GCS_BUCKET must be set to use the default storage backend")

    return GCSStorage.from_settings(settings)

