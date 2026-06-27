from __future__ import annotations

from typing import Any


def normalize_asr_payload_for_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """ตัด key ใหญ่ (tensor / ids / segments เต็มชุด) ก่อนยัด job metadata"""
    drop = {"output_ids", "generated_ids", "result", "segments"}
    return {k: v for k, v in payload.items() if k not in drop}
