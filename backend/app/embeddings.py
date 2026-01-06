
from typing import List, Protocol, runtime_checkable
import logging
import random
import os
from tenacity import retry, stop_after_attempt, wait_exponential
from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel

from .config import get_settings

logger = logging.getLogger(__name__)

@runtime_checkable
class EmbeddingService(Protocol):
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        Returns a list of embedding vectors (list of floats).
        """
        ...

class VertexAIEmbeddingService(EmbeddingService):
    def __init__(self, project_id: str, region: str = "us-central1"):
        self.project_id = project_id
        self.region = region
        
        aiplatform.init(project=project_id, location=region)
        # Using text-embedding-004 (latest stable 768-dim model)
        self.model = TextEmbeddingModel.from_pretrained("text-embedding-004")
        
        # Configure batch limit from Env or default 128 (max 250)
        default_limit = 128
        try:
             env_limit = int(os.environ.get("EMBEDDING_BATCH_LIMIT", default_limit))
             # Cap at 250 as strict upper bound for Vertex AI
             self.batch_limit = min(env_limit, 250)
        except ValueError:
             self.batch_limit = default_limit

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generates embeddings for a batch of texts.
        Handles batching internal to the service to respect API limits (e.g. 250 instances per request).
        """
        if not texts:
            return []

        all_embeddings = []
        
        for i in range(0, len(texts), self.batch_limit):
            batch_texts = texts[i : i + self.batch_limit]
            logger.info(f"Generating embeddings for batch of {len(batch_texts)} texts")
            
            # Allow exceptions to propagate to retry decorator (e.g. Quota/Throttling)
            embeddings = self.model.get_embeddings(batch_texts)
            
            # Defensive Check: Ensure response length matches request length
            if len(embeddings) != len(batch_texts):
                error_msg = (
                    f"Embedding count mismatch. Requested: {len(batch_texts)}, "
                    f"Received: {len(embeddings)}. This indicates a partial failure or API issue."
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # embeddings is a list of TextEmbedding objects
            # extract values
            vectors = [e.values for e in embeddings]
            all_embeddings.extend(vectors)
            
        return all_embeddings

class MockEmbeddingService(EmbeddingService):
    def __init__(self, dim: int = 768):
        self.dim = dim

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        # Return random vectors
        logger.info(f"Mock generating embeddings for {len(texts)} texts")
        return [
            [random.random() for _ in range(self.dim)]
            for _ in texts
        ]

def get_embedding_service() -> EmbeddingService:
    settings = get_settings()
    
    if settings.GCP_PROJECT_ID:
        return VertexAIEmbeddingService(
            project_id=settings.GCP_PROJECT_ID,
            region=settings.GCP_REGION or "us-central1"
        )
        
    return MockEmbeddingService()
