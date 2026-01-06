import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """
    Minimal settings object driven by environment variables.

    This keeps configuration centralized and makes it easy to
    extend later as additional services are added.
    """

    def __init__(self) -> None:
        # Core database URL, expected to include pgvector-enabled Postgres
        # Using psycopg v3 driver for async FastAPI (better Windows support)
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set")
        self.DATABASE_URL = db_url.strip()

        # GCP / GCS configuration (unused in the MVP, but wired for future use)
        self.GCS_BUCKET: str | None = os.getenv("GCS_BUCKET")
        if self.GCS_BUCKET:
            self.GCS_BUCKET = self.GCS_BUCKET.strip().strip('"').strip("'")

        self.GCP_PROJECT_ID: str | None = os.getenv("GCP_PROJECT_ID")
        self.GCP_REGION: str | None = os.getenv("GCP_REGION")

        # Job Runner Configuration
        self.JOB_RUNNER_MODE: str = os.getenv("JOB_RUNNER_MODE", "local").lower()
        self.WORKER_PATH: str = os.getenv("WORKER_PATH", "worker.py")
        self.CLOUD_RUN_JOB_NAME: str | None = os.getenv("CLOUD_RUN_JOB_NAME")
        
        self.CLOUD_TASKS_QUEUE: str | None = os.getenv("CLOUD_TASKS_QUEUE")
        self.CLOUD_TASKS_LOCATION: str | None = os.getenv("CLOUD_TASKS_LOCATION", "us-central1")
        self.WORKER_SERVICE_URL: str | None = os.getenv("WORKER_SERVICE_URL")

        # Storage & Upload Configuration
        self.MAX_DIRECT_UPLOAD_BYTES: int = int(os.getenv("MAX_DIRECT_UPLOAD_BYTES", 10 * 1024 * 1024)) # 10MB
        self.SIGNED_URL_TTL_SECONDS: int = int(os.getenv("SIGNED_URL_TTL_SECONDS", 600)) # 10 mins
        # Service Account email for signing URLs (defaults to None, must be set for Cloud Run signing)
        self.SIGNED_URL_SIGNER_SA: str | None = os.getenv("SIGNED_URL_SIGNER_SA")



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached accessor so we only read env vars once.
    """

    return Settings()

