
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import asyncio
import uuid
import logging
import sys
import os
from contextlib import asynccontextmanager

# Import necessary core components
from app.db import get_engine, AsyncSessionLocal
from app.config import get_settings
from worker import process_job

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Life-cycle management (optional, similar to main.py logic)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Any startup logic if needed
    yield
    # Any shutdown logic

app = FastAPI(title="Project Vision Worker Service", lifespan=lifespan)

class TaskPayload(BaseModel):
    job_id: str

@app.post("/internal/process")
async def process_task(payload: TaskPayload):
    """
    Worker endpoint triggered by Cloud Tasks.
    Arguments:
        payload: JSON body containing 'job_id'
    Returns:
        JSON status.
    """
    logger.info(f"Received processing request for job_id: {payload.job_id}")

    try:
        job_uuid = uuid.UUID(payload.job_id)
    except ValueError:
        logger.error(f"Invalid UUID format: {payload.job_id}")
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    # Reuse the same DB pattern as worker.py
    # We create a fresh session for this request/task
    try:
        async with AsyncSessionLocal() as session:
            # Reusing process_job from the shared worker module
            await process_job(session, job_uuid)
            
        return {"ok": True, "job_id": payload.job_id, "status": "processed"}

    except Exception as e:
        logger.error(f"Worker service failed for {payload.job_id}: {e}")
        # Return 200 even on application failure to prevent Cloud Tasks infinite retries?
        # Or let it fail 500 to retry? 
        # User constraint: "If job is already processing/completed, return 200."
        # Idempotency is handled inside process_job.
        # If it's a transient error, we might want to return 500 to let Cloud Tasks retry.
        # If it's a permanent error, logic inside process_job usually sets DB status to FAILED and re-raises.
        # Use HTTPException to allow Cloud Tasks to retry if configured.
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "ok"}
