
import { useEffect, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText, CheckCircle, AlertCircle, Loader2, Send, BookOpen } from 'lucide-react'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { uploadFile, getJobStatus, queryApi, type Job, type Citation } from './api'

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

interface ChatMessage {
  role: 'user' | 'ai'
  content: string
  citations?: Citation[]
}

export function App() {
  // --- State ---
  const [jobs, setJobs] = useState<Job[]>([])
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([
    { role: 'ai', content: 'Hello! Upload a document or ask me a question about your existing knowledge base.' }
  ])
  const [queryInput, setQueryInput] = useState('')
  const [isQuerying, setIsQuerying] = useState(false)
  const [expandedCitation, setExpandedCitation] = useState<string | null>(null) // ID of expanded citation

  // --- Upload Logic ---
  // --- Upload Logic ---
  // Threshold: 10MB (matches backend MAX_DIRECT_UPLOAD_BYTES default)
  const MAX_DIRECT_BYTES = 10 * 1024 * 1024;

  const onDrop = async (acceptedFiles: File[]) => {
    for (const file of acceptedFiles) {
      // Optimistic update
      const tempId = Math.random().toString(36).substr(2, 9)
      const newJob: Job = {
        job_id: tempId,
        document_id: 'pending',
        status: 'pending',
        source_uri: file.name,
        created_at: new Date().toISOString()
      }
      setJobs(prev => [newJob, ...prev])

      try {
        // Strategy Check
        if (file.size > MAX_DIRECT_BYTES) {
          // Large File Strategy: Signed URL
          // 1. Get URL
          // Simple extension mapping for source_type (could be robustified)
          let sourceType = 'text';
          if (file.type.includes('pdf')) sourceType = 'pdf';
          else if (file.type.includes('audio')) sourceType = 'audio';
          else if (file.name.endsWith('.md')) sourceType = 'markdown';

          // Import these from api.ts if not auto-imported, or assume module scope availability if I edit imports?
          // I need to ensure imports are available. I'll rely on the existing imports + adding new ones.
          // Since I can't easily edit imports in this block, I will assume I need to fix imports separately or use the ones available.
          // Ah, I need to call getUploadUrl which is imported.
          const { getUploadUrl, uploadToSignedUrl, submitJob } = await import('./api');

          const urlData = await getUploadUrl(file.name, file.type || 'application/octet-stream', sourceType);

          // 2. Upload Bytes (PUT)
          await uploadToSignedUrl(urlData.upload_url, file, file.type || 'application/octet-stream', (pct) => {
            // Optional: Update UI with progress?
            // For now, just logging or maybe updating a temporary state in jobs list if I added a progress field
            console.log(`Uploading ${file.name}: ${pct}%`);
          });

          // 3. Submit Job
          const res = await submitJob({
            title: file.name,
            source_type: sourceType,
            source_uri: urlData.gs_uri
          });

          // Update state
          setJobs(prev => prev.map(j => j.job_id === tempId ? { ...j, job_id: res.job_id, document_id: res.document_id, status: 'processing' } : j))

        } else {
          // Small File Strategy: Legacy Multipart
          const res = await uploadFile(file)
          setJobs(prev => prev.map(j => j.job_id === tempId ? { ...j, job_id: res.job_id, document_id: res.document_id, status: 'processing' } : j))
        }

      } catch (e) {
        console.error(e);
        setJobs(prev => prev.map(j => j.job_id === tempId ? { ...j, status: 'failed', error_message: 'Upload failed' } : j))
      }
    }
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop })

  // --- Polling Logic ---
  useEffect(() => {
    const interval = setInterval(async () => {
      const pendingJobs = jobs.filter(j => j.status === 'pending' || j.status === 'processing')
      if (pendingJobs.length === 0) return

      for (const job of pendingJobs) {
        try {
          // Skip temp IDs
          if (job.job_id.length < 10) continue

          const status = await getJobStatus(job.job_id)
          if (status.status !== job.status) {
            setJobs(prev => prev.map(j => j.job_id === job.job_id ? { ...j, ...status } : j))
          }
        } catch (e) {
          console.error("Poll error", e)
        }
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [jobs])

  // --- Chat Logic ---
  const handleSend = async () => {
    if (!queryInput.trim() || isQuerying) return

    const userMsg: ChatMessage = { role: 'user', content: queryInput }
    setChatHistory(prev => [...prev, userMsg])
    setQueryInput('')
    setIsQuerying(true)

    try {
      const res = await queryApi(userMsg.content)
      const aiMsg: ChatMessage = {
        role: 'ai',
        content: res.answer,
        citations: res.citations
      }
      setChatHistory(prev => [...prev, aiMsg])
    } catch (e) {
      setChatHistory(prev => [...prev, { role: 'ai', content: 'Sorry, I encountered an error extracting the answer.' }])
    } finally {
      setIsQuerying(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden">

      {/* Sidebar: Ingestion */}
      <div className="w-80 border-r border-slate-800 flex flex-col bg-slate-900/50">
        <div className="p-4 border-b border-slate-800">
          <h1 className="text-xl font-bold flex items-center gap-2 text-indigo-400">
            <BookOpen className="w-6 h-6" />
            TwinMind
          </h1>
          <p className="text-xs text-slate-500 mt-1">Project Vision Ingestion</p>
        </div>

        {/* Upload Area */}
        <div className="p-4">
          <div
            {...getRootProps()}
            className={cn(
              "border-2 border-dashed border-slate-700 rounded-lg p-6 text-center cursor-pointer transition-colors",
              isDragActive ? "border-indigo-500 bg-indigo-500/10" : "hover:border-slate-600 hover:bg-slate-800/50"
            )}
          >
            <input {...getInputProps()} />
            <Upload className="w-8 h-8 mx-auto text-slate-400 mb-2" />
            <p className="text-sm text-slate-300 font-medium">Drop files here</p>
            <p className="text-xs text-slate-500 mt-1">PDF, TXT, MD, Audio</p>
          </div>
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto p-4 pt-0 space-y-3">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Sources</h2>
          {jobs.length === 0 && (
            <p className="text-sm text-slate-600 italic text-center py-4">No documents yet</p>
          )}
          {jobs.map(job => (
            <div key={job.job_id} className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-md border border-slate-800/50">
              <div className="p-2 bg-slate-700/50 rounded-full">
                <FileText className="w-4 h-4 text-indigo-300" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{job.source_uri || job.document_id}</p>
                <p className="text-xs text-slate-500 flex items-center gap-1">
                  {new Date(job.created_at || Date.now()).toLocaleTimeString()}
                </p>
              </div>
              <div>
                {job.status === 'completed' && <CheckCircle className="w-4 h-4 text-emerald-500" />}
                {(job.status === 'processing' || job.status === 'pending') && <Loader2 className="w-4 h-4 text-amber-500 animate-spin" />}
                {job.status === 'failed' && <AlertCircle className="w-4 h-4 text-red-500" />}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main: Chat */}
      <div className="flex-1 flex flex-col bg-slate-950 relative">
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/20 via-slate-950/0 to-slate-950/0 pointer-events-none" />

        {/* Header */}
        <div className="h-16 border-b border-slate-800 flex items-center px-6 z-10 backdrop-blur-sm bg-slate-950/80">
          <h2 className="font-semibold text-slate-200">Query Interface</h2>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 z-0">
          {chatHistory.map((msg, idx) => (
            <div key={idx} className={cn(
              "flex gap-4 max-w-4xl mx-auto",
              msg.role === 'user' ? "flex-row-reverse" : "flex-row"
            )}>
              {/* Avatar */}
              <div className={cn(
                "w-8 h-8 rounded-full flex items-center justify-center shrink-0",
                msg.role === 'user' ? "bg-indigo-600" : "bg-emerald-600"
              )}>
                {msg.role === 'user' ? <div className="text-xs">You</div> : <div className="text-xs">AI</div>}
              </div>

              {/* Bubble */}
              <div className={cn(
                "p-4 rounded-2xl max-w-[80%] space-y-2",
                msg.role === 'user' ? "bg-indigo-600/20 text-indigo-100 rounded-tr-none" : "bg-slate-800 text-slate-200 rounded-tl-none"
              )}>
                <div className="whitespace-pre-wrap leading-relaxed">
                  {msg.content}
                </div>

                {/* Citations */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-slate-700">
                    <p className="text-xs font-semibold text-slate-400 mb-2">Sources:</p>
                    <div className="flex flex-wrap gap-2">
                      {msg.citations.map((cit, cIdx) => (
                        <div key={cIdx} className="group relative">
                          <button
                            onClick={() => setExpandedCitation(expandedCitation === cit.citation_marker ? null : cit.citation_marker)}
                            className="px-2 py-1 bg-slate-900 hover:bg-slate-700 rounded text-xs text-indigo-300 border border-slate-700 transition-colors"
                          >
                            {cit.citation_marker} {cit.document_id ? 'Doc' : 'Unknown'}
                          </button>

                          {/* Expanded Card */}
                          {expandedCitation === cit.citation_marker && (
                            <div className="absolute bottom-full left-0 mb-2 w-64 p-3 bg-slate-900 border border-slate-700 rounded-lg shadow-xl z-20 text-xs">
                              <p className="font-semibold text-slate-300 mb-1">Snippet (Page {cit.page_number})</p>
                              <p className="text-slate-400 italic">"...{cit.text_snippet}..."</p>
                              <div className="mt-2 text-[10px] text-slate-500">
                                Score: {(cit.score * 100).toFixed(1)}%
                                {cit.document_id && <span className="block truncate mt-0.5">ID: {cit.document_id}</span>}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
          {isQuerying && (
            <div className="flex gap-4 max-w-4xl mx-auto">
              <div className="w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center">
                <Loader2 className="w-4 h-4 animate-spin text-white" />
              </div>
              <div className="p-4 rounded-2xl bg-slate-800 text-slate-400 rounded-tl-none animate-pulse">
                Thinking...
              </div>
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="p-4 border-t border-slate-800 bg-slate-950 z-10">
          <div className="max-w-4xl mx-auto relative">
            <input
              className="w-full bg-slate-900 border border-slate-700 text-slate-200 rounded-xl pl-4 pr-12 py-4 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all placeholder:text-slate-600 shadow-lg"
              placeholder="Ask anything about your documents..."
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isQuerying}
            />
            <button
              onClick={handleSend}
              disabled={!queryInput.trim() || isQuerying}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:hover:bg-indigo-600 text-white rounded-lg transition-colors"
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
          <p className="text-center text-xs text-slate-600 mt-3">
            TwinMind can make mistakes. Consider checking important information.
          </p>
        </div>
      </div>
    </div>
  )
}
