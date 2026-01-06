
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from typing import List, Dict, Any, TypedDict
import logging
from app.config import get_settings

logger = logging.getLogger(__name__)

class AnswerWithCitations(TypedDict):
    answer: str
    citations: List[Dict[str, Any]]

class LLMService:
    def __init__(self):
        self.settings = get_settings()
        try:
            vertexai.init(project=self.settings.GCP_PROJECT_ID, location=self.settings.GCP_REGION)
            # Using a specific stable version to avoid 404s on generic 'gemini-pro'
            self.model = GenerativeModel("gemini-2.5-flash")
        except Exception as e:
            logger.error(f"Failed to initialize Vertex AI: {e}")
            self.model = None

    def generate_answer(self, query: str, context_chunks: List[Dict[str, Any]]) -> AnswerWithCitations:
        """
        Generate answer using Gemini based on provided context chunks.
        """
        if not self.model:
             return {"answer": "LLM Service unavailable.", "citations": []}
             
        if not context_chunks:
            return {"answer": "No relevant information found.", "citations": []}

        # Format Context
        # Structure:
        # [Score: 0.XX] [Source: Doc Title (Page X)]
        # <text>
        
        context_str = ""
        citations = []
        
        for i, chunk in enumerate(context_chunks):
            # Create citation object
            meta = chunk.get('metadata', {})
            page = meta.get('page_number')
            source_ref = meta.get('source_ref', {})
            doc_id = chunk.get('document_id')
            
            # Simple citation marker
            citation_marker = f"[{i+1}]"
            
            # Append to prompt
            context_str += f"Source {citation_marker}:\n{chunk['text']}\n\n"
            
            citations.append({
                "citation_marker": citation_marker,
                "document_id": doc_id,
                "text_snippet": chunk['text'][:100] + "...",
                "page_number": page,
                "score": chunk.get('fusion_score') or chunk.get('score'),
                "method": chunk.get('method')
            })
            
        prompt = f"""You are an intelligent assistant for Project Vision.
Answer the user's question using ONLY the context provided below.
If the answer is not in the context, state that you do not have enough information.
Cite your sources using the [number] format provided in the context.

Context:
{context_str}

Question: {query}

Answer:"""

        try:
            response = self.model.generate_content(prompt)
            answer_text = response.text
            
            return {
                "answer": answer_text,
                "citations": citations
            }
        except Exception as e:
            logger.error(f"Gemini Generation failed: {e}")
            return {"answer": "Error generating answer.", "citations": []}

_llm_service = None
def get_llm_service():
    global _llm_service
    if not _llm_service:
        _llm_service = LLMService()
    return _llm_service
