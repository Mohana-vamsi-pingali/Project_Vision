import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Float,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentSourceType(str, enum.Enum):
    audio = "audio"
    pdf = "pdf"
    markdown = "markdown"
    text = "text"
    web = "web"
    image = "image"


class IngestionStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    user_id = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow
    )

    documents = relationship("Document", back_populates="user")
    jobs = relationship("Job", back_populates="user")
    chunks = relationship("Chunk", back_populates="user")


class Document(Base):
    __tablename__ = "documents"

    document_id = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type = mapped_column(
        Enum(
            DocumentSourceType,
            name="document_source_type",
            native_enum=True,
        ),
        nullable=False,
    )
    title = mapped_column(Text, nullable=False)
    source_uri = mapped_column(Text, nullable=False)
    ingested_at = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    content_created_at = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status = mapped_column(
        Enum(
            IngestionStatus,
            name="ingestion_status",
            native_enum=True,
        ),
        default=IngestionStatus.pending,
        nullable=False,
    )

    user = relationship("User", back_populates="documents")
    jobs = relationship("Job", back_populates="document")
    chunks = relationship("Chunk", back_populates="document")

    __table_args__ = (
        Index(
            "idx_documents_user_id_ingested_at",
            "user_id",
            "ingested_at",
            postgresql_using="btree",
        ),
    )


class Job(Base):
    __tablename__ = "jobs"

    job_id = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    status = mapped_column(
        Enum(
            IngestionStatus,
            name="ingestion_status",
            native_enum=True,
        ),
        default=IngestionStatus.pending,
        nullable=False,
    )
    error_message = mapped_column(Text, nullable=True)
    created_at = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="jobs")
    document = relationship("Document", back_populates="jobs")

    __table_args__ = (
        Index(
            "idx_jobs_user_id_created_at",
            "user_id",
            "created_at",
            postgresql_using="btree",
        ),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = mapped_column(Integer, nullable=False)
    text = mapped_column(Text, nullable=False)

    # Embedding stored inline using pgvector (dimension 768 for typical text models).
    embedding = mapped_column(
        Vector(768), nullable=True
    )

    source_ref = mapped_column(JSON, nullable=False)
    page_number = mapped_column(Integer, nullable=True)
    section_heading = mapped_column(Text, nullable=True)
    speaker = mapped_column(Text, nullable=True)
    # Actually explicit Float is better
    start_offset = mapped_column(Float, nullable=True)
    end_offset = mapped_column(Float, nullable=True)
    
    # Keeping content_time for absolute time if needed later
    content_time_start = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="chunks")
    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index(
            "idx_chunks_user_id_document_id",
            "user_id",
            "document_id",
            postgresql_using="btree",
        ),
        Index(
            "idx_chunks_document_id_chunk_index",
            "document_id",
            "chunk_index",
            postgresql_using="btree",
        ),
        Index(
            "idx_chunks_content_time",
            "start_offset",
            "end_offset",
            postgresql_using="btree",
        ),
        Index(
            "idx_chunks_embedding_l2",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": "100"},
            postgresql_ops={"embedding": "vector_l2_ops"},
        ),
        # Full-Text Search Index
        Index(
            "idx_chunks_text_tsv",
            sql_text("to_tsvector('english', text)"),
            postgresql_using="gin",
        ),
    )

