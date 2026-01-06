from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .config import Settings, get_settings
from .api import ingest, jobs

app = FastAPI(title="Project Vision API", version="0.1.0")

# Parse CORS_ORIGINS from env, defaulting to local dev ports
import os
cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
origins = [origin.strip() for origin in cors_origins_str.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
from .api import query
app.include_router(query.router, prefix="/api/query", tags=["query"])


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """
    Minimal health check endpoint.

    Returns a simple JSON payload indicating liveness.
    Environment-driven settings are injected to validate configuration wiring,
    but not surfaced in the response for security.
    """

    # Touch settings so misconfiguration fails fast on startup
    _ = settings.DATABASE_URL

    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    """
    Convenience root endpoint.
    """

    return {"message": "Project Vision API"}