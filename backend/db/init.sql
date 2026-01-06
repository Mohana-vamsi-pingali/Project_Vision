-- Database initialization script for Project Vision
-- Enables required extensions, defines enums, tables, and indexes.

-- Extensions -----------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector


-- Enums ----------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_source_type') THEN
        CREATE TYPE document_source_type AS ENUM (
            'audio',
            'pdf',
            'markdown',
            'text',
            'web',
            'image'
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ingestion_status') THEN
        CREATE TYPE ingestion_status AS ENUM (
            'pending',
            'processing',
            'completed',
            'failed'
        );
    END IF;
END
$$;


-- Tables ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    user_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    document_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    source_type          document_source_type NOT NULL,
    title                TEXT NOT NULL,
    source_uri           TEXT NOT NULL,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_created_at   TIMESTAMPTZ,
    status               ingestion_status NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    document_id   UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    status        ingestion_status NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    document_id         UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index         INTEGER NOT NULL,
    text                TEXT NOT NULL,
    embedding           vector(768),
    source_ref          JSONB NOT NULL,
    page_number         INTEGER,
    section_heading     TEXT,
    speaker             TEXT,
    content_time_start  TIMESTAMPTZ,
    content_time_end    TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- Indexes --------------------------------------------------------------------

-- Multi-tenant / ownership scoping
CREATE INDEX IF NOT EXISTS idx_documents_user_id_ingested_at
    ON documents (user_id, ingested_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_user_id_created_at
    ON jobs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chunks_user_id_document_id
    ON chunks (user_id, document_id);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id_chunk_index
    ON chunks (document_id, chunk_index);

-- Temporal filtering on chunks
CREATE INDEX IF NOT EXISTS idx_chunks_content_time
    ON chunks (content_time_start, content_time_end);

-- Vector similarity search (pgvector ivfflat index)
-- Note: requires ANALYZE after loading data for best performance.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_l2
    ON chunks
    USING ivfflat (embedding vector_l2_ops)
    WITH (lists = 100);

