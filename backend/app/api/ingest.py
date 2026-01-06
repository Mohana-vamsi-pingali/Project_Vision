import uuid
import os
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db import get_db
from app.models import Document, Job, IngestionStatus, DocumentSourceType, User
from app.storage import StorageBackend, get_default_storage
from app.job_runner import run_ingestion_job
from app.config import get_settings

router = APIRouter()

# Allowed file extensions
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".pdf", ".md", ".txt"}
# Placeholder user for MVP
DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def validate_file_extension(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {ALLOWED_EXTENSIONS}",
        )
    return ext.lower()


def determine_source_type(ext: str) -> DocumentSourceType:
    if ext in {".mp3", ".m4a", ".wav"}:
        return DocumentSourceType.audio
    elif ext == ".pdf":
        return DocumentSourceType.pdf
    elif ext == ".md":
        return DocumentSourceType.markdown
    elif ext == ".txt":
        return DocumentSourceType.text
    return DocumentSourceType.text  # Default fallback


class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str
    source_type: DocumentSourceType

class SubmitRequest(BaseModel):
    title: str
    source_type: DocumentSourceType
    source_uri: str



@router.post("/upload-url")
async def generate_upload_url(
    payload: UploadUrlRequest,
    storage: StorageBackend = Depends(get_default_storage),
):
    """
    Generate a V4 Signed URL for direct-to-GCS upload.
    Used for files > MAX_DIRECT_UPLOAD_BYTES.
    """
    settings = get_settings()
    
    # Generate a safe object path: {user_id}/{upload_id}/{safe_filename}
    upload_id = uuid.uuid4()
    # Sanitize filename strictly if needed, but GCS handles most
    object_path = f"{DEMO_USER_ID}/{upload_id}/{payload.filename}"
    
    expires_in_seconds = settings.SIGNED_URL_TTL_SECONDS
    
    try:
        url = storage.generate_signed_url(
            object_path=object_path,
            content_type=payload.content_type,
            expiration=timedelta(seconds=expires_in_seconds),
            method="PUT"
        )
        
        # We manually construct the gs:// URI or fetch bucket name from config if exposed?
        # Protocol exposes internal _bucket in GCSStorage but not protocol.
        # But we know the pattern: gs://BUCKET/PATH
        # Accessing settings.GCS_BUCKET directly is safe here since we are inside API.
        gs_uri = f"gs://{settings.GCS_BUCKET}/{object_path}"
        
        return {
            "upload_url": url,
            "gs_uri": gs_uri,
            "object_path": object_path,
            "expires_in_seconds": expires_in_seconds
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate signed URL: {str(e)}")


@router.post("/submit", status_code=status.HTTP_201_CREATED)
async def submit_ingestion_job(
    request: SubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a job for a file already uploaded to GCS.
    """
    # 1. Ensure User Exists
    user_query = await db.execute(select(User).where(User.user_id == DEMO_USER_ID))
    user = user_query.scalar_one_or_none()
    
    if not user:
        user = User(user_id=DEMO_USER_ID)
        db.add(user)
        try:
            await db.flush()
        except Exception:
            pass

    # 2. Create Document
    document_id = uuid.uuid4()
    doc = Document(
        document_id=document_id,
        user_id=DEMO_USER_ID,
        source_type=request.source_type,
        title=request.title,
        source_uri=request.source_uri,
        status=IngestionStatus.pending,
        ingested_at=datetime.utcnow(),
    )
    db.add(doc)

    # 3. Create Job
    job_id = uuid.uuid4()
    job = Job(
        job_id=job_id,
        user_id=DEMO_USER_ID,
        document_id=document_id,
        status=IngestionStatus.pending,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)

    try:
        await db.commit()
        # Trigger Processing
        run_ingestion_job(job_id)
        
        return {
            "job_id": str(job_id),
            "document_id": str(document_id),
            "status": "pending"
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {e}")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_default_storage),
):
    try:
        """
        Upload a file for ingestion.
        """
        settings = get_settings()
        
        # Check Content-Length (Advisory)
        # Note: Cloud Run web server might reject it before here if it's huge
        content_length = file.size # Starlette UploadFile exposes .size usage? No, headers.
        # Often file.size is valid if spooled.
        
        # Better: check request header if available?
        # Or just read file in chunks and check size.
        # But for MVP let's assume if it got here, it's small enough or we check now.
        
        # If the file is spooled to disk, we can get size.
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        
        if size > settings.MAX_DIRECT_UPLOAD_BYTES:
             raise HTTPException(
                 status_code=413, 
                 detail=f"File too large ({size} bytes). Max {settings.MAX_DIRECT_UPLOAD_BYTES}. Use signed URL upload flow."
             )

        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is missing")

        ext = validate_file_extension(file.filename)
        source_type = determine_source_type(ext)

        # 1. Read file content (in memory for MVP; stream for larger files in prod)
        try:
            content = await file.read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

        # 2. Upload to GCS
        document_id = uuid.uuid4()
        
        # Ensure demo user exists
        # Check if user exists
        user_query = await db.execute(select(User).where(User.user_id == DEMO_USER_ID))
        user = user_query.scalar_one_or_none()
        
        if not user:
            user = User(user_id=DEMO_USER_ID)
            db.add(user)
            # We need to flush/commit to ensure FK constraint is satisfied for doc
            try:
                await db.flush()
            except Exception:
                pass

        try:
            source_uri = storage.upload_raw_artifact(
                file_bytes=content,
                filename=file.filename,
                user_id=str(DEMO_USER_ID),
                document_id=str(document_id),
                content_type=file.content_type,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Storage upload failed: {e}")

        # 3. Create Document
        doc = Document(
            document_id=document_id,
            user_id=DEMO_USER_ID,
            source_type=source_type,
            title=file.filename,
            source_uri=source_uri,
            status=IngestionStatus.pending,
            ingested_at=datetime.utcnow(),
        )
        db.add(doc)

        # 4. Create Job
        job_id = uuid.uuid4()
        job = Job(
            job_id=job_id,
            user_id=DEMO_USER_ID,
            document_id=document_id,
            status=IngestionStatus.pending,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(job)

        try:
            await db.commit()
            
            # TRIGGER WORKER (AFTER COMMIT)
            run_ingestion_job(job_id)
            
        except Exception as e:
            # If commit fails, we rollback
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error (ensure user exists): {e}")

        return {
            "job_id": job_id,
            "document_id": document_id,
            "status": "pending",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise e
