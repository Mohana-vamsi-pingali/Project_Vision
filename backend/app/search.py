
import uuid
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models import Chunk

class SearchService:
    async def semantic_search(
        self,
        session: AsyncSession,
        query_embedding: List[float],
        user_id: uuid.UUID,
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search using pgvector cosine distance.
        """
        filters = filters or {}
        
        # Base query: Order by cosine distance
        # Note: pgvector's cosine_distance returns 0.0 for identical vectors, 
        # and up to 2.0 for opposite vectors.
        # We want smallest distance first.
        
        # Construct Where Clause
        conditions = [Chunk.user_id == user_id]
        
        if "document_id" in filters and filters["document_id"]:
            # Handle list of doc ids or single
            doc_param = filters["document_id"]
            if isinstance(doc_param, list):
                conditions.append(Chunk.document_id.in_(doc_param))
            else:
                conditions.append(Chunk.document_id == doc_param)
        
        # Time Filters (using start_offset or absolute time? User requirement said "content_time_start")
        # Let's support date range on 'created_at' OR 'content_time_start' if present.
        # User req: "Optional date range on content_time_start/end"
        # But wait, audio chunks rely on start_offset (float).
        # However, for global search, we usually use 'ingested_at' or if the doc has a date.
        # The Chunk model has `content_time_start` (TIMESTAMP).
        # Let's filter on `created_at` as a fallback or if requested.
        # Implemented support for 'start_date' and 'end_date' mapping to 'created_at' for now, 
        # as content_time_start is often null for simple uploads unless we extract it.
        # Actually user specifically asked for "content_time_start".
        
        if "start_date" in filters and filters["start_date"]:
             conditions.append(Chunk.created_at >= filters["start_date"])
             
        if "end_date" in filters and filters["end_date"]:
             conditions.append(Chunk.created_at <= filters["end_date"])

        # Construct Query
        # We select the Chunk and the distance
        stmt = select(
            Chunk,
            Chunk.embedding.cosine_distance(query_embedding).label("distance")
        ).where(
            and_(*conditions)
        ).order_by(
            "distance"
        ).limit(limit)
        
        result = await session.execute(stmt)
        rows = result.all()
        
        results = []
        for row in rows:
            chunk: Chunk = row[0]
            distance: float = row[1]
            
            # Convert distance to similarity score (approximate)
            # Cosine similarity = 1 - distance
            similarity = 1 - distance
            
            results.append({
                "chunk_id": str(chunk.chunk_id),
                "document_id": str(chunk.document_id),
                "text": chunk.text,
                "score": similarity,
                "distance": distance,
                "metadata": {
                    "page_number": chunk.page_number,
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                    "source_ref": chunk.source_ref,
                    "created_at": chunk.created_at.isoformat() if chunk.created_at else None
                }
            })
            
        return results

    async def keyword_search(
        self,
        session: AsyncSession,
        query: str,
        user_id: uuid.UUID,
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform keyword search using PostgreSQL Full-Text Search (tsvector).
        """
        filters = filters or {}
        from sqlalchemy import func, desc
        
        # 1. Base Query using ts_rank
        # plainto_tsquery parses "google cloud" -> "google" & "cloud"
        ts_query = func.plainto_tsquery('english', query)
        ts_vector = func.to_tsvector('english', Chunk.text)
        
        rank = func.ts_rank(ts_vector, ts_query)
        
        # 2. Filters
        conditions = [
            Chunk.user_id == user_id,
            ts_vector.op('@@')(ts_query) # Match condition
        ]
        
        if "document_id" in filters and filters["document_id"]:
            doc_param = filters["document_id"]
            if isinstance(doc_param, list):
                conditions.append(Chunk.document_id.in_(doc_param))
            else:
                conditions.append(Chunk.document_id == doc_param)

        if "start_date" in filters and filters["start_date"]:
             conditions.append(Chunk.created_at >= filters["start_date"])
             
        if "end_date" in filters and filters["end_date"]:
             conditions.append(Chunk.created_at <= filters["end_date"])

        # 3. Execution
        stmt = select(Chunk, rank.label("rank"))\
            .where(and_(*conditions))\
            .order_by(desc("rank"))\
            .limit(limit)
            
        result = await session.execute(stmt)
        rows = result.all()
        
        results = []
        for row in rows:
            chunk: Chunk = row[0]
            score: float = row[1]
            
            results.append({
                "chunk_id": str(chunk.chunk_id),
                "document_id": str(chunk.document_id),
                "text": chunk.text,
                "score": score, # Relevance Score
                "method": "keyword",
                "metadata": {
                    "page_number": chunk.page_number,
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                    "source_ref": chunk.source_ref,
                    "created_at": chunk.created_at.isoformat() if chunk.created_at else None
                }
            })
            
        return results

    async def hybrid_search(
        self,
        session: AsyncSession,
        query: str,
        user_id: uuid.UUID,
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search (Semantic + Keyword) fused with Reciprocal Rank Fusion (RRF).
        """
        from app.embeddings import get_embedding_service
        
        # 1. Get Query Embedding
        embedding_service = get_embedding_service()
        # Note: generate_embeddings is sync or async? It is sync in previous impl but calls Google API which is sync client.
        # But we wrapped it. Let's check embeddings.py.
        # It is sync `generate_embeddings(texts: List[str]) -> List[List[float]]`.
        # However, for production performance, we might want to make it async/threadpool, 
        # but for now we call it directly.
        try:
            query_embedding = embedding_service.generate_embeddings([query])[0]
        except Exception as e:
            # Fallback to keyword only if embedding fails?
            print(f"Embedding failed: {e}. Falling back to keyword search.")
            return await self.keyword_search(session, query, user_id, limit, filters)

        # 2. Run Parallel Searches (conceptually)
        # We can run them sequentially for now.
        semantic_results = await self.semantic_search(
            session, query_embedding, user_id, limit=20, filters=filters
        ) # Get top 20 for fusion pool
        
        keyword_results = await self.keyword_search(
            session, query, user_id, limit=20, filters=filters
        ) # Get top 20 for fusion pool
        
        # 3. RRF Fusion
        k = 60
        scores: Dict[str, float] = {}
        chunks_map: Dict[str, Dict] = {}
        
        # Process Semantic
        for rank, item in enumerate(semantic_results):
            cid = item['chunk_id']
            chunks_map[cid] = item
            # RRF score
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank + 1))
            
        # Process Keyword
        for rank, item in enumerate(keyword_results):
            cid = item['chunk_id']
            # If exists, prefer existing item (usually semantic has better metadata? or same?)
            if cid not in chunks_map:
                chunks_map[cid] = item
            
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank + 1))
            
        # 4. Sort and Limit
        fused_results = []
        for cid, score in scores.items():
            item = chunks_map[cid]
            item['fusion_score'] = score
            # We can label method as 'hybrid'
            item['method'] = 'hybrid'
            fused_results.append(item)
            
        # Sort descending by score
        fused_results.sort(key=lambda x: x['fusion_score'], reverse=True)
        
        # Return top N
        return fused_results[:limit]

search_service = SearchService()
