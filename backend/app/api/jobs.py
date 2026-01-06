
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models import Job, User

router = APIRouter()

# Placeholder user for MVP (Must match ingest.py)
DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

@router.get("/{job_id}", status_code=status.HTTP_200_OK)
async def get_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the status of an ingestion job.
    Scoping: Currently restricted to the DEMO_USER_ID.
    """
    query = select(Job).where(
        Job.job_id == job_id,
        Job.user_id == DEMO_USER_ID
    )
    result = await db.execute(query)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    return {
        "job_id": job.job_id,
        "document_id": job.document_id,
        "status": job.status,
        "error_message": job.error_message,
    }
