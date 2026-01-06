
from typing import List, TypedDict
import tiktoken
import nltk
from app.transcription import WordInfo

# Download nltk data if not present (idempotent)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab', quiet=True)


class ChunkMetadata(TypedDict):
    text: str
    start_time: float | None
    end_time: float | None
    chunk_index: int
    page_number: int | None
    metadata: dict | None

class ChunkingService:
    def __init__(self, model_name: str = "cl100k_base"):
        self.encoding = tiktoken.get_encoding(model_name)
    
    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def chunk_transcript(
        self, 
        transcript: str, 
        words: List[WordInfo], 
        max_tokens: int = 800, 
        overlap_tokens: int = 100
    ) -> List[ChunkMetadata]:
        """
        Semantically chunk transcript preserving timestamp boundaries.
        Strategy:
        1. Segment full transcript into sentences.
        2. Align sentences with word-level timestamps.
        3. Group sentences into chunks < max_tokens.
        4. Apply overlap.
        """
        
        # 1. Split into sentences
        # Note: nltk sent_tokenize is good, but we need to map back to 'words' list to get time.
        # This alignment can be tricky if punctuation differs. 
        # Simpler approach for alignment: 
        # Iterate through 'words' and build sentences by checking for punctuation in word.text?
        # Or just trust nltk and "consume" words from the list until they match the sentence text.
        
        sentences = nltk.sent_tokenize(transcript)
        
        sentence_objects = [] # List[{text, start, end, token_count}]
        current_word_idx = 0
        
        total_words = len(words)
        
        for sent_text in sentences:
            sent_start = None
            sent_end = None
            
            # Remove whitespace for matching
            target_chars = sent_text.replace(" ", "").lower()
            collected_chars = ""
            
            # Words consumed for this sentence
            sent_words = []
            
            while current_word_idx < total_words:
                w = words[current_word_idx]
                w_text_clean = w['text'].replace(" ", "").lower()
                
                # Heuristic: Match cleaned characters. 
                # Verification: This can be brittle if nltk normalizes text (e.g. quotes).
                # Fallback: Just consume words.
                
                if sent_start is None:
                    sent_start = w['start_time']
                
                sent_words.append(w)
                collected_chars += w_text_clean
                sent_end = w['end_time']
                
                current_word_idx += 1
                
                # Check if we have collected enough chars to match sentence
                # Note: target_chars might be slightly different due to punctuation handling.
                # A robust way is to just checking length or approximate match.
                # For MVP, let's assume loose alignment:
                # If collected length >= target length, we assume sentence end.
                if len(collected_chars) >= len(target_chars):
                    break
            
            if sent_words:
                # Reconstruct text from words to ensure fidelity to timestamps
                # (nltk might have normalized, so we prefer the word list text)
                # But typically we want the clean sentence.
                # Let's use the words' text joined by space for the chunk content 
                # to guarantee it matches the time range.
                real_sent_text = " ".join([w['text'] for w in sent_words])
                
                sentence_objects.append({
                    "text": real_sent_text,
                    "start_time": sent_start,
                    "end_time": sent_end,
                    "token_count": self.count_tokens(real_sent_text)
                })

        # 2. Group sentences into chunks
        chunks: List[ChunkMetadata] = []
        current_chunk_sents = []
        current_tokens = 0
        chunk_idx = 0
        
        i = 0
        while i < len(sentence_objects):
            sent = sentence_objects[i]
            
            # If adding this sentence exceeds max_tokens AND we have content, finalize current chunk
            if current_tokens + sent['token_count'] > max_tokens and current_chunk_sents:
                # Finalize chunk
                chunk_text = " ".join([s['text'] for s in current_chunk_sents])
                chunks.append({
                    "text": chunk_text,
                    "start_time": current_chunk_sents[0]['start_time'],
                    "end_time": current_chunk_sents[-1]['end_time'],
                    "chunk_index": chunk_idx
                })
                chunk_idx += 1
                
                # Handle Overlap
                # We want to keep the last N tokens worth of sentences for the next chunk.
                # Backtrack 'current_chunk_sents' to find overlap window
                overlap_buffer = []
                overlap_cnt = 0
                
                for s in reversed(current_chunk_sents):
                    if overlap_cnt + s['token_count'] <= overlap_tokens:
                        overlap_buffer.insert(0, s)
                        overlap_cnt += s['token_count']
                    else:
                        break
                
                current_chunk_sents = list(overlap_buffer)
                current_tokens = overlap_cnt
            
            current_chunk_sents.append(sent)
            current_tokens += sent['token_count']
            i += 1
            
        # Final chunk
        if current_chunk_sents:
            chunk_text = " ".join([s['text'] for s in current_chunk_sents])
            chunks.append({
                "text": chunk_text,
                "start_time": current_chunk_sents[0]['start_time'],
                "end_time": current_chunk_sents[-1]['end_time'],
                "chunk_index": chunk_idx
            })
            
        return chunks

    def chunk_document(
        self,
        pages: List[dict], # List[{page_number, text}]
        max_tokens: int = 800,
        overlap_tokens: int = 100
    ) -> List[ChunkMetadata]:
        """
        Chunk document pages respecting page boundaries (soft) and tokens (hard).
        Similar to transcript chunking but sources are pages.
        """
        # Convert pages to sentence objects with page metadata
        sentence_objects = []
        
        for page in pages:
            page_num = page['page_number']
            text = page['text']
            # Simple sentence splitting
            sentences = nltk.sent_tokenize(text)
            
            for s_text in sentences:
                sentence_objects.append({
                    "text": s_text,
                    "page_number": page_num,
                    "token_count": self.count_tokens(s_text)
                })
                
        # Group into chunks
        chunks: List[ChunkMetadata] = []
        current_chunk_sents = []
        current_tokens = 0
        chunk_idx = 0
        
        i = 0
        while i < len(sentence_objects):
            sent = sentence_objects[i]
            
            if current_tokens + sent['token_count'] > max_tokens and current_chunk_sents:
                chunk_text = " ".join([s['text'] for s in current_chunk_sents])
                
                # Determine page range
                start_page = current_chunk_sents[0]['page_number']
                end_page = current_chunk_sents[-1]['page_number']
                
                chunks.append({
                    "text": chunk_text,
                    "start_time": None,
                    "end_time": None,
                    "page_number": start_page, # Just primary page
                    "chunk_index": chunk_idx,
                    "metadata": {"start_page": start_page, "end_page": end_page}
                })
                chunk_idx += 1
                
                # Overlap logic
                overlap_buffer = []
                overlap_cnt = 0
                for s in reversed(current_chunk_sents):
                    if overlap_cnt + s['token_count'] <= overlap_tokens:
                        overlap_buffer.insert(0, s)
                        overlap_cnt += s['token_count']
                    else:
                        break
                current_chunk_sents = list(overlap_buffer)
                current_tokens = overlap_cnt
            
            current_chunk_sents.append(sent)
            current_tokens += sent['token_count']
            i += 1
            
        if current_chunk_sents:
            chunk_text = " ".join([s['text'] for s in current_chunk_sents])
            start_page = current_chunk_sents[0]['page_number']
            chunks.append({
                "text": chunk_text,
                "start_time": None,
                "end_time": None,
                "page_number": start_page,
                "chunk_index": chunk_idx,
                "metadata": {"start_page": start_page, "end_page": current_chunk_sents[-1]['page_number']}
            })
            
        return chunks

chunking_service = ChunkingService()
