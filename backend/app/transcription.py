
from __future__ import annotations

import logging
from typing import Protocol, TypedDict, List, runtime_checkable

from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_settings

logger = logging.getLogger(__name__)

class WordInfo(TypedDict):
    text: str
    start_time: float
    end_time: float

class TranscriptionResult(TypedDict):
    transcript: str
    words: List[WordInfo]

@runtime_checkable
class TranscriptionService(Protocol):
    def transcribe_audio(self, gcs_uri: str) -> TranscriptionResult:
        """
        Transcribe audio from a GCS URI.
        """
        ...

class VertexAITranscriptionService(TranscriptionService):
    def __init__(self, project_id: str, region: str = "us-central1"):
        self.project_id = project_id
        self.region = region
        self.client = speech_v2.SpeechClient(
            client_options={"api_endpoint": f"{region}-speech.googleapis.com"}
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def transcribe_audio(self, gcs_uri: str) -> TranscriptionResult:
        logger.info(f"Starting transcription for {gcs_uri}")
        
        config = cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=["en-US"],
            model="chirp",  # Use Chirp model for best quality
            # Enable word timing offsets
            features=cloud_speech.RecognitionFeatures(
                enable_word_time_offsets=True,
            ),
        )

        request = cloud_speech.BatchRecognizeRequest(
            recognizer=f"projects/{self.project_id}/locations/{self.region}/recognizers/_",
            config=config,
            files=[cloud_speech.BatchRecognizeFileMetadata(uri=gcs_uri)],
            recognition_output_config=cloud_speech.RecognitionOutputConfig(
                inline_response_config=cloud_speech.InlineOutputConfig(),
            ),
        )

        # Long-running operation
        operation = self.client.batch_recognize(request=request)
        
        logger.info("Waiting for operation to complete...")
        response = operation.result(timeout=3000) # 50 minute timeout for safety

        # Process results
        full_transcript = []
        all_words: List[WordInfo] = []

        # BatchRecognize returns a map of results per file
        # We only sent one file
        for result_wrapper in response.results[gcs_uri].transcript.results:
            # Each 'result' is a portion of the transcript
            if not result_wrapper.alternatives:
                continue
                
            alt = result_wrapper.alternatives[0]
            full_transcript.append(alt.transcript)
            
            for word in alt.words:
                # Timestamps are typically generic objects (Duration/timedelta), need conversion
                start_sec = word.start_offset.total_seconds()
                end_sec = word.end_offset.total_seconds()
                
                all_words.append({
                    "text": word.word,
                    "start_time": start_sec,
                    "end_time": end_sec,
                })

        return {
            "transcript": " ".join(full_transcript),
            "words": all_words,
        }

class MockTranscriptionService(TranscriptionService):
    def transcribe_audio(self, gcs_uri: str) -> TranscriptionResult:
        logger.info(f"Mock transcribing {gcs_uri}")
        return {
            "transcript": "This is a mock transcription of the audio file.",
            "words": [
                {"text": "This", "start_time": 0.0, "end_time": 0.5},
                {"text": "is", "start_time": 0.5, "end_time": 1.0},
                {"text": "a", "start_time": 1.0, "end_time": 1.2},
                {"text": "mock", "start_time": 1.2, "end_time": 1.8},
                {"text": "transcription", "start_time": 1.8, "end_time": 2.5},
                {"text": "of", "start_time": 2.5, "end_time": 2.7},
                {"text": "the", "start_time": 2.7, "end_time": 3.0},
                {"text": "audio", "start_time": 3.0, "end_time": 3.5},
                {"text": "file.", "start_time": 3.5, "end_time": 4.0},
            ]
        }

def get_transcription_service() -> TranscriptionService:
    settings = get_settings()
    # For MVP/Dev, verify if we have credentials or force mock
    # If GCS_BUCKET implies prod, we might try Real service, but user asked for Mock for local testing.
    # We can use an env var or just default to Mock for safety unless explicitly configured.
    # Let's check for a specific flag or just enable Mock for now as requested for "local testing".
    
    # Ideally:
    if settings.GCP_PROJECT_ID:
       return VertexAITranscriptionService(settings.GCP_PROJECT_ID, settings.GCP_REGION or "us-central1")
    
    return MockTranscriptionService()
