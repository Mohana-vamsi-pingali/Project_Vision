
import axios from 'axios';

// Parse base host from env, stripping any trailing slash
const ENV_HOST = (import.meta.env.VITE_API_URL || 'http://localhost:8001').replace(/\/+$/, '');
// Append /api to standardise requests (backend routers are at /api/...)
const API_BASE = `${ENV_HOST}/api`;

export interface Job {
    job_id: string;
    document_id: string;
    status: 'pending' | 'processing' | 'completed' | 'failed';
    error_message?: string;
    source_uri?: string;
    created_at?: string;
    updated_at?: string;
}

export interface Citation {
    citation_marker: string;
    document_id: string;
    text_snippet: string;
    page_number?: number;
    score: number;
}

export interface QueryResponse {
    answer: string;
    citations: Citation[];
}

// Direct Upload Types
export interface UploadUrlResponse {
    upload_url: string;
    gs_uri: string;
    object_path: string;
    expires_in_seconds: number;
}

export interface SubmitJobRequest {
    title: string;
    source_type: string;
    source_uri: string;
}

// Get Signed Upload URL
export const getUploadUrl = async (filename: string, contentType: string, sourceType: string): Promise<UploadUrlResponse> => {
    const response = await axios.post(`${API_BASE}/ingest/upload-url`, {
        filename,
        content_type: contentType,
        source_type: sourceType
    });
    return response.data;
};

// Submit Job (after direct upload)
export const submitJob = async (data: SubmitJobRequest): Promise<{ job_id: string; document_id: string; status: string }> => {
    const response = await axios.post(`${API_BASE}/ingest/submit`, data);
    return response.data;
};

// Helper to upload bytes to Signed URL with progress
export const uploadToSignedUrl = async (url: string, file: File, contentType: string, onProgress?: (percent: number) => void) => {
    await axios.put(url, file, {
        headers: {
            'Content-Type': contentType,
        },
        onUploadProgress: (progressEvent) => {
            if (onProgress && progressEvent.total) {
                const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                onProgress(percentCompleted);
            }
        }
    });
};

// Upload File (Legacy Multipart)
export const uploadFile = async (file: File): Promise<{ job_id: string; document_id: string }> => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post(`${API_BASE}/ingest/upload`, formData, {
        headers: {
            'Content-Type': 'multipart/form-data',
        },
    });
    return response.data;
};

// Get Job Status
export const getJobStatus = async (jobId: string): Promise<Job> => {
    const response = await axios.get(`${API_BASE}/jobs/${jobId}`);
    return response.data;
};

// Query
export const queryApi = async (query: string): Promise<QueryResponse> => {
    const response = await axios.post(`${API_BASE}/query/`, {
        query,
        filters: {} // Can extend later
    });
    return response.data;
};
