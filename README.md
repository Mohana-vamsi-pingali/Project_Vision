# Project Vision

TwinMind / Project Vision is a Retrieval-Augmented Generation (RAG) system capable of ingesting various document formats (PDF, Markdown, Audio) and answering queries using advanced vector search and LLMs.

## Overview

-   **Frontend**: React (Vite) + Tailwind CSS application. Supports drag-and-drop file upload (large files via Signed URLs), real-time job status polling, and a chat interface.
-   **Backend**: FastAPI (Python) service. Handles ingestion, text extraction, chunking, embedding generation (Vertex AI), and vector search (Cloud SQL / pgvector).
-   **Worker Service**: Dedicated Cloud Run service for background processing (transcription, embedding generation) triggered via Cloud Tasks.
-   **Database**: Cloud SQL (PostgreSQL) with `pgvector` extension.
-   **Infrastructure**: Google Cloud Platform (Cloud Run, Cloud SQL, Cloud Storage, Secret Manager, Cloud Build, Artifact Registry).

## Structure

```
.
├── backend/            # FastAPI Application & Worker
│   ├── app/            # Core logic (API, DB, Engines)
│   ├── init_db.py      # Database initialization script
│   ├── worker.py       # Legacy worker logic (refactored)
│   └── Dockerfile      # Backend container definition
├── frontend/           # React Application
│   ├── src/            # Frontend source code
│   └── Dockerfile      # Frontend container definition
└── .gitignore          # Global git ignore rules
```

## Implemented Scope

Implemented:
- PDF and Audio ingestion
- Asynchronous background processing via Cloud Tasks
- Transcription + chunking + embedding pipeline
- Vector search using pgvector
- Chat-based Q&A API
- Cloud Run deployment (API, Worker, Frontend)

Designed / Extensible:
- Web content ingestion
- Image ingestion with metadata-based retrieval
- Advanced hybrid retrieval strategies

## High-Level Flow

1. User uploads a file via the frontend.
2. Backend issues a Signed URL for direct upload to GCS.
3. Upload completion triggers an ingestion job.
4. API enqueues a Cloud Task for background processing.
5. Worker service:
   - Extracts text or transcribes audio
   - Chunks content with timestamps
   - Generates embeddings
   - Stores vectors in PostgreSQL (pgvector)
6. Queries retrieve relevant chunks and synthesize answers using an LLM.


## Prerequisites

-   Google Cloud Platform Project
-   `gcloud` CLI installed and authenticated
-   Docker (for local development)
-   PostgreSQL (local) or Cloud SQL Proxy

## Setup & Deployment

Detailed deployment instructions are available in the [Deployment Guide](deployment_guide.md) (if included) or follow the summary below.

### Local Development

1.  **Backend**:
    ```bash
    cd backend
    python -m venv venv
    source venv/bin/activate  # or venv\Scripts\activate on Windows
    pip install -r requirements.txt
    
    # Set environment variables in .env (see .env.example)
    uvicorn app.main:app --reload --port 8001
    ```

2.  **Frontend**:
    ```bash
    cd frontend
    npm install
    npm run dev
    ```

### Cloud Deployment (Google Cloud Run)

The system is designed to be deployed on Google Cloud Run.

1.  **Build Images**:
    ```bash
    gcloud builds submit --tag gcr.io/PROJECT/backend ./backend
    gcloud builds submit --tag gcr.io/PROJECT/frontend --build-arg VITE_API_URL="..." ./frontend
    ```

2.  **Deploy Services**:
    -   Deploy **Backend API** (Cloud Run Service)
    -   Deploy **Worker Service** (Cloud Run Service, internal ingress)
    -   Deploy **Frontend** (Cloud Run Service, public)

3.  **Config**:
    -   Set `JOB_RUNNER_MODE=cloudtasks` on the API.
    -   Configure `DATABASE_URL` and `GCS_BUCKET` secrets.
    -   Grant `Token Creator` role to the Service Account for Signed URLs.

## Security Note

-   **Secrets**: Never commit `.env` files. Use Google Secret Manager for production secrets.
-   **IAM**: Use dedicated Service Accounts with least-privilege permissions.

## License

[MIT](LICENSE)
