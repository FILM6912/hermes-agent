from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestImageItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str | None = None
    url: str | None = None


class IngestMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_filename: str | None = None
    image_count: int | None = None
    markdown_length: int | None = None
    converter_metadata: dict[str, Any] | None = None
    response_mode: str | None = None


class IngestUploadSummary(BaseModel):
    model_config = ConfigDict(extra="allow")


def upload_summary_as_dict(upload: IngestUploadSummary | dict[str, Any] | None) -> dict[str, Any]:
    """Normalize ``IngestResponse.upload`` — Pydantic may coerce dicts to ``IngestUploadSummary``."""
    if upload is None:
        return {}
    if isinstance(upload, dict):
        return upload
    return upload.model_dump()


class IngestResponse(BaseModel):
    source_filename: str
    markdown: str
    images: list[IngestImageItem] = Field(default_factory=list)
    metadata: IngestMetadata | dict[str, Any] = Field(default_factory=dict)
    upload: IngestUploadSummary | dict[str, Any] = Field(default_factory=dict)


class QueryResultRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_filename: str = ""
    chunk_index: int | None = None
    content: str = ""
    similarity: float | None = None
    hybrid_score: float | None = None
    rank: float | None = None
    rerank_score: float | None = None


class QueryRequest(BaseModel):
    query_text: str
    query_mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"
    docs: list[str] = Field(default_factory=list, description="document_name list")
    rrf_k: int = 60
    use_reranker: bool = Field(
        default=True,
        description="ใช้ Qwen3-VL-Reranker จัดอันดับผลลัพธ์ (hybrid/semantic)",
    )


class QueryResponse(BaseModel):
    query: str
    mode: str
    total: int
    results: list[QueryResultRow]
    results_text: str


class DocumentsListQuery(BaseModel):
    docs: list[str] | None = Field(
        default=None,
        description="document_name list (ไม่ส่งค่า = เลือกทั้งหมด)",
    )


class JobListQuery(BaseModel):
    only_pending: bool = Field(default=False, description="เฉพาะ queued/running")
    include_completed: bool = Field(
        default=False,
        description="รวม completed jobs (default false — job เสร็จจะหายจาก dashboard)",
    )
    include_failed: bool = Field(
        default=False,
        description="รวม failed jobs (default false — ดูที่ GET /jobs/errors)",
    )
    limit: int = Field(default=100, ge=1, le=500)


class JobErrorsListQuery(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    kind: str | None = Field(default=None, description="กรองตาม job kind")


class HealthResponse(BaseModel):
    status: str = "ok"


class ChunkContentDeleteResponse(BaseModel):
    message: str
    id: str


class ChunkMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")


class DocumentSummary(BaseModel):
    source_filename: str
    chunk_count: int
    folder_name: str | None = None
    llm_summary: str = ""


class DocumentFileEntry(BaseModel):
    id: int
    file_name: str
    source_file_url: str | None = None
    llm_summary: str = Field(default="", description="LLM-generated document summary when available")
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    approved_by: str | None = Field(default=None, description="Admin who approved KM ingest commit")
    approved_at: str | None = Field(default=None, description="When the document was approved for RAG")


class DocumentListItem(BaseModel):
    """Flat document row for search-tagged list API (one row per file)."""

    document_name: str
    source_filename: str
    llm_summary: str = ""
    source_file_url: str | None = None
    chunk_count: int = 0
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentListItem] = Field(default_factory=list)


class DocumentDetail(BaseModel):
    source_filename: str
    chunk_count: int
    folders: list[str] = Field(default_factory=list)
    image_paths: list[str] = Field(default_factory=list)
    source_file_url: str | None = None
    llm_summary: str = ""


class PendingIngestEntry(BaseModel):
    """รายการรอ commit embedding (หลังอัปโหลดชุดเอกสาร)"""

    id: str
    document_name: str
    source_filename: str
    llm_summary: str = ""
    status: str
    job_id: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    markdown_length: int = 0


class CommitPendingIngestResponse(BaseModel):
    status: str
    pending_ingest_id: str
    source_filename: str
    chunks_uploaded: int = 0
    embedding_used: bool = False
    errors: list[str] = Field(default_factory=list)


class CommitPendingBatchRequest(BaseModel):
    """Commit หลาย pending ingest ใน job เดียว — แสดงใน GET /jobs เป็นรายการไฟล์ครบ"""

    pending_ids: list[str] = Field(..., min_length=1, description="UUID จาก ingest-pending")


class PendingIngestRejectResponse(BaseModel):
    message: str
    pending_ingest_id: str
    document_name: str
    source_filename: str
    status: str = "rejected"


class DocumentMoveRequest(BaseModel):
    document_name: str


class DocumentMutationResponse(BaseModel):
    message: str
    source_filename: str
    folder_name: str | None = None
    deleted_chunks: int = 0
    deleted_images: int = 0


class DocumentFileUpsertRequest(BaseModel):
    source_filename: str
    folder_name: str = "default"


class DocumentFileUpdateRequest(BaseModel):
    folder_name: str


class DocumentSetEntry(BaseModel):
    id: str
    document_name: str
    files: list["DocumentFileEntry"] = Field(default_factory=list)


class DocumentSetMutationResponse(BaseModel):
    message: str
    id: str
    document_name: str
    files: list["DocumentFileEntry"] = Field(default_factory=list)


class DocumentSetMoveRequest(BaseModel):
    document_name: str


class RenameDocumentRequest(BaseModel):
    document_name: str
    new_document_name: str


class RenameFileRequest(BaseModel):
    document_name: str
    file_name: str
    new_file_name: str


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str
    message: str
    status_url: str
    document_name: str
    name: str = Field(default="")
    total_files: int = Field(default=1, description="Number of items in the background job")
    hint: str | None = Field(
        default=None,
        description="Short UX hint (e.g. poll status_url — the status in this response is only the accept-time snapshot)",
    )


class JobStatusResponse(BaseModel):
    job_id: str
    kind: str
    status: str
    revision: int = 0
    document_name: str | None = Field(
        default=None,
        description="Document set / folder name for this job",
    )
    files: list[str] = Field(
        default_factory=list,
        description="All file names in this job (full list, not only current_item)",
    )
    detail: str | None = None
    error: str | None = None
    total_items: int = 0
    completed_items: int = 0
    current_item: str | None = Field(
        default=None,
        description="File or item most recently updated (legacy single-file hint)",
    )
    active_items: list[str] = Field(
        default_factory=list,
        description="Files currently processing in parallel ingest slots",
    )
    pending_items: list[str] = Field(
        default_factory=list,
        description="Files waiting for a parallel ingest slot",
    )
    completed_files: list[str] = Field(
        default_factory=list,
        description="Files that finished ingest in this job",
    )
    active_slot_ids: list[str] = Field(
        default_factory=list,
        description="Unique slot ids for active_items (parallel to active_items)",
    )
    pending_slot_ids: list[str] = Field(
        default_factory=list,
        description="Unique slot ids for pending_items (parallel to pending_items)",
    )
    completed_slot_ids: list[str] = Field(
        default_factory=list,
        description="Unique slot ids for completed_files (parallel to completed_files)",
    )
    file_activity: dict[str, dict] = Field(
        default_factory=dict,
        description="Per-slot live step text and percent while active (keyed by slot id)",
    )
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    metadata: dict = Field(default_factory=dict)
    progress: dict = Field(default_factory=dict)
    llm_summary: str | None = Field(
        default=None,
        description="Optional ingest summary stored in job metadata",
    )
    llm_summary_error: str | None = Field(
        default=None,
        description="Error message when summary generation failed",
    )
    queue_position: int | None = Field(
        default=None,
        description="Position in queued jobs (1 = next), FIFO by created_at — null if not queued",
    )
    queue_waiting_total: int | None = Field(
        default=None,
        description="Total queued jobs on this server process at response time",
    )


class ChunkContentSummary(BaseModel):
    id: str
    chunk_index: int | None = None
    token_count: int = 0
    document_name: str | None = None
    content: str = Field(default="", description="เนื้อหา chunk เต็ม (เหมือน GET chunk เดี่ยว)")
    metadata: ChunkMetadata | dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ChunkContentListResponse(BaseModel):
    source_filename: str
    document_name: str
    chunks: list[ChunkContentSummary] = Field(default_factory=list)


class ChunkContentDetail(BaseModel):
    id: str
    chunk_index: int | None = None
    token_count: int = 0
    document_name: str | None = None
    content: str = ""
    metadata: ChunkMetadata | dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ChunkContentCreateRequest(BaseModel):
    content: str = Field(..., description="เนื้อหา chunk")
    chunk_index: int | None = Field(
        default=None,
        description="ถ้าไม่ส่ง จะใช้เลขถัดจาก chunk_index สูงสุดของไฟล์นี้",
    )
    re_embed: bool = Field(
        default=True,
        description="คำนวณ embedding ใหม่เมื่อมี embedding API",
    )


class ChunkContentUpdateRequest(BaseModel):
    content: str | None = Field(default=None, description="ถ้าไม่ส่ง จะไม่เปลี่ยนเนื้อหา")
    re_embed: bool = Field(
        default=True,
        description="เมื่อแก้ content แนะนำ true — คำนวณ embedding ใหม่",
    )


class ChunkContentMutationResponse(BaseModel):
    message: str
    id: str
    chunk_index: int | None = None
    token_count: int = 0
    embedding_applied: bool = False
    embedding_error: str | None = None


class TranscriptAudioRecord(BaseModel):
    """แถว transcript จากตาราง ``transcript`` (อัปโหลดจาก audio)"""

    id: str
    transcript_group: str = Field(description="Storage/document group (DB column document_name)")
    transcript_name: str
    content: str | None = None
    files: list[dict[str, Any]] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    audio_llm_summary: str | None = Field(
        default=None,
        description="LLM summary of the transcript (when LLM_ENABLED)",
    )
    audio_llm_report: str | None = Field(
        default=None,
        description="LLM formal report from the transcript (when LLM_ENABLED)",
    )
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str
    updated_at: str
    source_filename: str | None = Field(default=None, description="Audio file name from files[0].path")


class TranscriptAudioListResponse(BaseModel):
    transcript_group: str
    transcript_name: str
    total: int
    items: list[TranscriptAudioRecord]


class TranscriptAudioTranscriptSetEntry(BaseModel):
    transcript_name: str
    transcript_id: str = Field(default="")
    processing: bool = Field(
        description="True when the newest row in this set has non-empty content",
    )


class TranscriptAudioDocumentEntry(BaseModel):
    transcript_group: str
    transcript_sets: list[TranscriptAudioTranscriptSetEntry] = Field(default_factory=list)


class TranscriptAudioIndexResponse(BaseModel):
    total: int = Field(description="Total transcript sets across groups")
    transcript_group_count: int = Field(description="Number of distinct transcript_group values")
    transcript_groups: list[TranscriptAudioDocumentEntry] = Field(default_factory=list)


class TranscriptReportJobAcceptedResponse(BaseModel):
    job_id: str
    status: str
    message: str
    status_url: str
    transcript_group: str
    transcript_name: str
    total_files: int = Field(default=1, description="Number of items in the background job")
    hint: str | None = Field(
        default=None,
        description="Short UX hint (poll status_url for live progress)",
    )


class TranscriptAudioProcessRequest(BaseModel):
    transcript_ids: list[str] = Field(..., min_length=1, description="Transcript row UUIDs")
    asr_prompt: str = Field(default="", description="ASR prompt; overrides ASR_PROMPT in .env when set")
    force_reprocess: bool = Field(
        default=False,
        description="If true, re-run transcription and overwrite summary",
    )
