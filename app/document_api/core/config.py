from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_database: str = "postgres"
    pg_user: str = "postgres"
    pg_password: str = ""
    pg_sslmode: str = "disable"

    supabase_url: str = ""
    supabase_service_key: str = ""
    hermes_webui_public_url: str = Field(
        default="",
        validation_alias=AliasChoices("HERMES_WEBUI_PUBLIC_URL", "DOCUMENT_PUBLIC_BASE_URL"),
        description="Public WebUI base URL for stored document/storage links (not Supabase host)",
    )
    hermes_webui_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("HERMES_WEBUI_HOST"),
    )
    hermes_webui_port: int = Field(
        default=8787,
        validation_alias=AliasChoices("HERMES_WEBUI_PORT"),
    )
    supabase_storage_bucket: str = "document-images"
    supabase_transcript_bucket: str = "transcript"
    supabase_table_name: str = "langflow"
    supabase_query_name: str = "match_documents"

    chunk_size: int = Field(default=1500, validation_alias=AliasChoices("CHUNK_TOKEN_SIZE", "CHUNK_SIZE"))
    chunk_overlap: int = Field(default=200, validation_alias=AliasChoices("CHUNK_TOKEN_OVERLAP", "CHUNK_OVERLAP"))
    split_text: str = "\\n\\n"

    hf_models_dir: str = Field(
        default="",
        validation_alias=AliasChoices("HF_MODELS_DIR", "MODELS_DIR"),
        description="Base directory for mounted local HF snapshots (e.g. /models)",
    )

    embedding_enabled: bool = Field(default=False, validation_alias=AliasChoices("EMBEDDING_ENABLED"))
    embedding_backend: str = Field(
        default="auto",
        validation_alias=AliasChoices("EMBEDDING_BACKEND"),
        description="auto | huggingface | vllm | openai | ollama",
    )
    embedding_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("EMBEDDING_API_KEY", "OPENAI_EMBEDDING_API_KEY"),
    )
    embedding_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("EMBEDDING_BASE_URL", "OPENAI_EMBEDDING_BASE_URL"),
    )
    embedding_model: str = Field(
        default="Qwen/Qwen3-VL-Embedding-2B",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL"),
    )
    embedding_model_path: str = Field(
        default="",
        validation_alias=AliasChoices("EMBEDDING_MODEL_PATH"),
        description="Optional local path override (e.g. /models/Qwen3-VL-Embedding-2B)",
    )
    embedding_load_bits: int = Field(
        default=16,
        validation_alias=AliasChoices("EMBEDDING_LOAD_BITS", "EMBEDDING_BITS"),
        description="4, 8, or 16 (bf16) — Hugging Face local load only",
    )
    embedding_dimensions: int = Field(default=0, validation_alias=AliasChoices("EMBEDDING_DIMENSIONS"))
    embedding_query_instruction: str = Field(
        default="Retrieve images or text relevant to the user's query.",
        validation_alias=AliasChoices("EMBEDDING_QUERY_INSTRUCTION"),
    )
    embedding_document_instruction: str = Field(
        default="Represent the user's input.",
        validation_alias=AliasChoices("EMBEDDING_DOCUMENT_INSTRUCTION"),
    )

    reranker_enabled: bool = Field(default=True, validation_alias=AliasChoices("RERANKER_ENABLED"))
    reranker_backend: str = Field(
        default="auto",
        validation_alias=AliasChoices("RERANKER_BACKEND"),
        description="auto | huggingface | vllm | http",
    )
    reranker_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("RERANKER_API_KEY", "OPENAI_RERANKER_API_KEY"),
    )
    reranker_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("RERANKER_BASE_URL", "OPENAI_RERANKER_BASE_URL"),
    )
    reranker_model: str = Field(
        default="Qwen/Qwen3-VL-Reranker-2B",
        validation_alias=AliasChoices("RERANKER_MODEL"),
    )
    reranker_model_path: str = Field(
        default="",
        validation_alias=AliasChoices("RERANKER_MODEL_PATH"),
        description="Optional local path override (e.g. /models/Qwen3-VL-Reranker-2B)",
    )
    reranker_load_bits: int = Field(
        default=16,
        validation_alias=AliasChoices("RERANKER_LOAD_BITS", "RERANKER_BITS"),
        description="4, 8, or 16 (bf16) — Hugging Face local load only",
    )
    reranker_prompt: str = Field(
        default="Retrieve images or text relevant to the user's query.",
        validation_alias=AliasChoices("RERANKER_PROMPT"),
    )
    reranker_candidates: int = Field(
        default=50,
        validation_alias=AliasChoices("RERANKER_CANDIDATES"),
        description="จำนวน candidate จาก vector search ก่อน rerank",
    )

    rename_move_workers: int = 8

    llm_api_key: str = Field(default="", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("LLM_MODEL", "TOC_LLM_MODEL", "TOC_MODEL", "OPENAI_MODEL"),
    )
    llm_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("LLM_ENABLED", "TOC_LLM_ENABLED"),
    )
    enable_llm_rearrange: bool = Field(default=False, validation_alias=AliasChoices("ENABLE_LLM_REARRANGE"))

    test_pipeline_llm_organize_timing: str = Field(
        default="before_chunk",
        validation_alias=AliasChoices("TEST_PIPELINE_LLM_ORGANIZE_TIMING"),
        description="before_chunk | after_chunk — when LLM organize runs in /api/v1/test/pipeline",
    )
    test_pipeline_organize_model: str = Field(
        default="",
        validation_alias=AliasChoices("TEST_PIPELINE_ORGANIZE_MODEL"),
        description="Optional LLM model override for test pipeline organize step (defaults to LLM_MODEL)",
    )

    @field_validator("enable_llm_rearrange", mode="before")
    @classmethod
    def _coerce_enable_llm_rearrange(cls, v: object) -> bool:
        if v is True:
            return True
        if v is False or v is None:
            return False
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("", "false", "0", "no", "off", "none", "disabled"):
                return False
            if s in ("true", "1", "yes", "on", "enabled"):
                return True
        return False

    asr_enabled: bool = Field(default=False, validation_alias=AliasChoices("ASR_ENABLED"))
    asr_api_url: str = Field(
        default="http://192.168.99.1:9786/v1/audio/transcriptions",
        validation_alias=AliasChoices("ASR_API_URL"),
        description="OpenAI-compatible audio transcription endpoint",
    )
    asr_model_id: str = Field(
        default="FILM6912/monsoon-whisper-medium-gigaspeech2-ct2",
        validation_alias=AliasChoices("ASR_MODEL_ID", "ASR_MODEL"),
        description="Model id sent as ``model`` in the transcription request",
    )
    asr_response_format: str = Field(
        default="verbose_json",
        validation_alias=AliasChoices("ASR_RESPONSE_FORMAT"),
    )
    asr_timeout: float = Field(default=600.0, validation_alias=AliasChoices("ASR_TIMEOUT"))
    asr_prompt: str = Field(default="", validation_alias=AliasChoices("ASR_PROMPT"))

    ingest_defer_vector_until_admin: bool = Field(
        default=True,
        validation_alias=AliasChoices("INGEST_DEFER_VECTOR_UNTIL_ADMIN"),
        description="อัปโหลดชุดเอกสาร: แปลงแล้วรอ commit ก่อน embedding ลง vector DB",
    )
    ingest_max_parallel_files: int = Field(
        default=5,
        validation_alias=AliasChoices("INGEST_MAX_PARALLEL_FILES"),
        description="จำนวนไฟล์ที่แปลงพร้อมกันต่อ job อัปโหลด (ที่เหลือรอในคิว)",
    )
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL"),
        description="ระดับ log ของ document API (DEBUG, INFO, WARNING, …)",
    )

    mcp_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("MCP_ENABLED"),
        description="Expose document search/list endpoints as MCP tools via fastapi-mcp",
    )
    mcp_mount_path: str = Field(
        default="/mcp",
        validation_alias=AliasChoices("MCP_MOUNT_PATH"),
        description="HTTP mount path for FastApiMCP (Streamable HTTP transport)",
    )
    mcp_km_number_of_results: int = Field(
        default=5,
        ge=1,
        validation_alias=AliasChoices("MCP_KM_NUMBER_OF_RESULTS", "MCP_KM_SEARCH_RESULTS"),
        description="Default document search hit count for MCP KM tools when callers omit number_of_results",
    )
    mcp_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MCP_API_KEY", "MCP_SERVICE_API_KEY"),
        description="Permanent Bearer token for service/admin MCP clients (full RAG access)",
    )
    mcp_require_bearer: bool = Field(
        default=True,
        validation_alias=AliasChoices("MCP_REQUIRE_BEARER"),
        description="When MCP is enabled, require Bearer auth on /mcp and search tools",
    )


def default_mcp_km_number_of_results() -> int:
    """Resolved default for MCP KM / document search result count."""
    return max(1, int(get_settings().mcp_km_number_of_results or 5))


def get_settings() -> Settings:
    """โหลด Settings จาก .env ทุกครั้ง — แก้ค่าใน .env แล้วคำขอถัดไปจะเห็นค่าใหม่โดยไม่ต้องรีสตาร์ท."""
    return Settings()
