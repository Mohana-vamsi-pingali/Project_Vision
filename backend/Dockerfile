FROM python:3.10-slim
ARG CACHE_BUST=1
WORKDIR /app
# Install system dependencies (for pgvector/psycopg)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Default for Cloud Run Service (API)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]