"""
Cloud Run Job Worker

This worker is designed to be executed as a Google Cloud Run Job.
It processes a single ingestion job and then exits.

Usage:
    The worker expects the 'JOB_ID' environment variable to be set.
    
    Example (Cloud Run / Local):
        export JOB_ID="<uuid>"
        python worker.py
        
    Windows PowerShell:
        $env:JOB_ID="<uuid>"
        python worker.py

Behavior:
    1. Reads JOB_ID from environment.
    2. Connects to the database.
    3. Atomically claims the job (UPDATE ... WHERE status='pending').
    4. If claim successful, processes the job (Transcribe/Extract -> Chunk -> Embed -> Store).
    5. Updates Job status to 'completed' or 'failed'.
    6. Exits with code 0 (Success) or 1 (Failure/Error).
"""

import asyncio
import logging
import os
import sys
import uuid
import traceback
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import Chunk, Document, DocumentSourceType, IngestionStatus, Job
from app.transcription import get_transcription_service
from app.chunking import chunking_service
from app.embeddings import get_embedding_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

class WorkerError(Exception):
    """Custom exception for worker failures to distinguish from system errors."""
    pass

async def process_job(session: AsyncSession, job_id: uuid.UUID):    
    try:
        # 1. Atomic Job Claiming
        # Attempt to flip status from Pending -> Processing
        stmt = (
            update(Job)
            .where(Job.job_id == job_id, Job.status == IngestionStatus.pending)
            .values(status=IngestionStatus.processing, updated_at=datetime.utcnow())
        )
        result = await session.execute(stmt)
        
        if result.rowcount == 0:
            await session.rollback()
            # Could not claim job. Either it doesn't exist, or it's not pending.
            # Let's verify if it exists for better logging
            stmt_check = select(Job).where(Job.job_id == job_id)
            job_check = (await session.execute(stmt_check)).scalar_one_or_none()
            
            if not job_check:
                logger.error(f"Job not found: {job_id}")
                raise WorkerError(f"Job not found: {job_id}")
            else:
                logger.info(f"Job {job_id} already claimed or not pending (Status: {job_check.status}). Exiting.")
                return # Exit gracefully, job is handled by someone else or done

        # Only commit if we successfully claimed the row
        await session.commit()
    
        logger.info(f"Claimed Job {job_id}. Starting processing...")

        # Reload Job to get details
        job = (await session.execute(select(Job).where(Job.job_id == job_id))).scalar_one()

        # 2. Get Document and File Info
        stmt = select(Document).where(Document.document_id == job.document_id)
        result = await session.execute(stmt)
        document = result.scalar_one_or_none()
        
        if not document:
            raise ValueError(f"Document {job.document_id} not found")
            
        # Initialize services
        transcription_service = get_transcription_service()
        embedding_service = get_embedding_service()
        
        chunks_data = [] 
        
        # 3. Process based on Source Type
        if document.source_type == DocumentSourceType.audio:
            logger.info(f"Transcribing audio from {document.source_uri}")
            transcription = transcription_service.transcribe_audio(document.source_uri)
            logger.info(f"Transcription complete. Chunking {len(transcription['words'])} words...")
            
            chunks_data = chunking_service.chunk_transcript(
                transcript=transcription['transcript'],
                words=transcription['words']
            )
            
        elif document.source_type in (DocumentSourceType.text, DocumentSourceType.markdown, DocumentSourceType.pdf):
            logger.info(f"Downloading document from {document.source_uri}")
            
            # Download Logic
            from google.cloud import storage as gcs
            if document.source_uri.startswith("gs://"):
                parts = document.source_uri[5:].split("/", 1)
                bucket_name = parts[0]
                blob_name = parts[1]
                
                storage_client = gcs.Client()
                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                file_bytes = blob.download_as_bytes()
                
                # Extract Text
                from app.extraction import extract_document_text
                
                ext = document.title.split(".")[-1].lower() if "." in document.title else "txt"
                if document.source_type == DocumentSourceType.pdf: ext = "pdf"
                
                extracted_content = extract_document_text(file_bytes, ext)
                chunks_data = chunking_service.chunk_document(pages=extracted_content['pages'])
            else:
                 logger.warning(f"Protocol not supported for {document.source_uri}, returning empty chunks.")
                 chunks_data = []
        
        # Safety Check: Empty Extraction
        if not chunks_data:
            raise RuntimeError(f"No chunks produced from document {job.document_id}. Source may be empty or unreadable.")
            
        logger.info(f"Generated {len(chunks_data)} chunks. Generating embeddings...")
        
        # 4. Generate Embeddings
        texts = [c['text'] for c in chunks_data]
        embeddings = embedding_service.generate_embeddings(texts)
        
        # Safety Check: Embedding Mismatch
        if len(embeddings) != len(chunks_data):
            raise RuntimeError(
                f"Embedding count mismatch! Chunks: {len(chunks_data)}, Embeddings: {len(embeddings)}. "
                "This implies a partial failure in embedding service."
            )
        
        # 5. Store Chunks
        logger.info(f"Storing {len(embeddings)} encoded chunks...")
        
        for i, chunk_meta in enumerate(chunks_data):
            # Check for duplicates (Idempotency)
            stmt = select(Chunk).where(
                Chunk.document_id == job.document_id,
                Chunk.chunk_index == chunk_meta['chunk_index']
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            if existing:
                existing.text = chunk_meta['text']
                existing.embedding = embeddings[i]
                existing.start_offset = chunk_meta.get('start_time')
                existing.end_offset = chunk_meta.get('end_time')
                existing.page_number = chunk_meta.get('page_number')
                existing.updated_at = datetime.utcnow()
            else:
                new_chunk = Chunk(
                    chunk_id=uuid.uuid4(),
                    user_id=job.user_id,
                    document_id=job.document_id,
                    chunk_index=chunk_meta['chunk_index'],
                    text=chunk_meta['text'],
                    embedding=embeddings[i],
                    start_offset=chunk_meta.get('start_time'),
                    end_offset=chunk_meta.get('end_time'),
                    page_number=chunk_meta.get('page_number'),
                    source_ref=chunk_meta.get('metadata', {}), 
                    created_at=datetime.utcnow()
                )
                session.add(new_chunk)
        
        # 6. Complete Job
        job.status = IngestionStatus.completed
        job.updated_at = datetime.utcnow()
        await session.commit()
        
        logger.info(f"Job completed: {job.job_id}")
        
    except Exception as e:
        logger.error(f"Job processing failed: {e}")
        
        # Rollback any active transactions
        await session.rollback()
        
        # Set Failed Status
        try:
             stmt = (
                 update(Job)
                 .where(Job.job_id == job_id)
                 .values(
                     status=IngestionStatus.failed,
                     error_message=str(e),
                     updated_at=datetime.utcnow()
                 )
             )
             await session.execute(stmt)
             await session.commit()
             logger.info("Updated job status to FAILED.")
        except Exception as commit_error:
             logger.error(f"CRITICAL: Failed to save job failure status: {commit_error}")
        
        # Re-raise exception to signal failure to __main__
        raise

async def run_once(job_id: uuid.UUID):
    logger.info(f"Worker starting execution for JOB_ID: {job_id}")
    settings = get_settings()
    
    # DB Engine Tuning for Cloud Run (Ephemeral)
    engine = create_async_engine(
        settings.DATABASE_URL, 
        echo=False,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=1800
    )
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with AsyncSessionLocal() as session:
            await process_job(session, job_id)
            
    finally:
        await engine.dispose()

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    job_id_str = os.environ.get("JOB_ID")
    if not job_id_str:
        logger.error("JOB_ID environment variable not set. Usage: export JOB_ID=<uuid>")
        sys.exit(1)
        
    try:
        job_id = uuid.UUID(job_id_str)
    except ValueError:
        logger.error(f"Invalid JOB_ID format: {job_id_str}")
        sys.exit(1)
        
    try:
        asyncio.run(run_once(job_id))
        sys.exit(0) # Success
    except Exception as e:
        logger.error(f"Worker execution failed: {e}")
        sys.exit(1) # Failure
