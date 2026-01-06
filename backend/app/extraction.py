
import io
from typing import List, Dict, Any, TypedDict
import logging
from pypdf import PdfReader

logger = logging.getLogger(__name__)

class PageContent(TypedDict):
    page_number: int
    text: str

class DocumentContent(TypedDict):
    text: str # Full text
    pages: List[PageContent]

def extract_document_text(file_bytes: bytes, file_type: str) -> DocumentContent:
    """
    Extract text from file bytes based on file type.
    """
    logger.info(f"Extracting text from {file_type} file ({len(file_bytes)} bytes)")
    
    if file_type == "pdf":
        return extract_pdf(file_bytes)
    elif file_type in ["md", "txt", "markdown"]:
        return extract_text_file(file_bytes)
    else:
        # Fallback treat as text
        return extract_text_file(file_bytes)

def extract_pdf(file_bytes: bytes) -> DocumentContent:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        full_text = []
        
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append({
                "page_number": i + 1,
                "text": text
            })
            full_text.append(text)
            
        return {
            "text": "\n\n".join(full_text),
            "pages": pages
        }
    except Exception as e:
        logger.error(f"PDF Extraction failed: {e}")
        # Return empty or simplified error content
        return {"text": "", "pages": []}

def extract_text_file(file_bytes: bytes) -> DocumentContent:
    try:
        text = file_bytes.decode("utf-8", errors="replace")
        # For text files, we treat it as a single page or split logic?
        # Requirement: "best-effort extraction".
        # Let's return as Page 1.
        return {
            "text": text,
            "pages": [{"page_number": 1, "text": text}]
        }
    except Exception as e:
        logger.error(f"Text Extraction failed: {e}")
        return {"text": "", "pages": []}
