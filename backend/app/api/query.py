
import uuid
import logging
from typing import List, Optional, Any, Dict
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.search import search_service
from app.llm import get_llm_service, LLMService

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Request Models ---

class QueryFilters(BaseModel):
    date_range: Optional[Dict[str, Any]] = None # e.g. {"start": "...", "end": "..."} or raw text?
    # User requirement: "Accept: {query: str, filters: {date_range: {...}, source_type: [...]}}"
    # And Step 1: "Parse temporal expressions".
    # So user input might be raw text queries or structured?
    # "filters: {date_range: {...}}" implies structured.
    # But "Step 1: Parse temporal expressions (use simple regex for "last week", "yesterday")" 
    # usually applies to the QUERY string if natural language logic is embedded.
    # However, if the API Contract says input is filters dict, maybe frontend does parsing?
    # OR, the query string itself contains "last week". 
    # SDD 6.3 says "The phrase 'last week' is detected and resolved".
    # This implies we parse the query string for temporal cues.
    
    source_type: Optional[List[str]] = None
    document_ids: Optional[List[uuid.UUID]] = None

class QueryRequest(BaseModel):
    query: str
    filters: Optional[QueryFilters] = None

class Citation(BaseModel):
    citation_marker: str
    document_id: Optional[uuid.UUID]
    text_snippet: str
    page_number: Optional[int]
    score: float

class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation]

# --- Helper: Temporal Parsing ---
def parse_temporal_intent(query: str) -> Optional[datetime]:
    """
    Very basic rule-based temporal extraction from query string.
    Returns a 'start_date' datetime if a recency phrase is found.
    """
    query_lower = query.lower()
    now = datetime.utcnow()
    
    if "last week" in query_lower or "past week" in query_lower:
        return now - timedelta(days=7)
    if "yesterday" in query_lower:
        return now - timedelta(days=1)
    if "last month" in query_lower or "past month" in query_lower:
        return now - timedelta(days=30)
    if "last 24 hours" in query_lower:
        return now - timedelta(hours=24)
        
    return None

@router.post("/", response_model=QueryResponse)
async def query_endpoint(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    # In real auth, get user_id from token
):
    # Hardcoded Demo User
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    
    # 1. Temporal Parsing
    # Combine explicit filters with implicit query parsing
    start_date = None
    if request.filters and request.filters.date_range and "start" in request.filters.date_range:
        # Explicit filter
        try:
             start_date = date_parser.parse(request.filters.date_range["start"])
        except:
             pass
    else:
        # Implicit parsing
        start_date = parse_temporal_intent(request.query)

    search_filters = {}
    if start_date:
        search_filters["start_date"] = start_date
        logger.info(f"Applied temporal filter: >= {start_date}")

    if request.filters and request.filters.document_ids:
        search_filters["document_id"] = request.filters.document_ids

    # 2. Hybrid Search
    try:
        chunks = await search_service.hybrid_search(
            session=db,
            query=request.query,
            user_id=user_id,
            limit=10, # Top 10 for context
            filters=search_filters
        )
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # 3. LLM Generation
    llm_service = get_llm_service()
    
    if not chunks:
        return QueryResponse(answer="No relevant information found.", citations=[])
        
    result = llm_service.generate_answer(request.query, chunks)
    
    return QueryResponse(
        answer=result['answer'],
        citations=result['citations']
    )
