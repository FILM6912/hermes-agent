from __future__ import annotations

import json
import logging
import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from app.document_api.core.config import Settings

logger = logging.getLogger(__name__)


def _effective_prompt(settings: Settings, prompt: str | None) -> str | None:
    if prompt is not None and str(prompt).strip():
        return str(prompt).strip()
    return settings.asr_prompt.strip() or None


def _guess_mime(audio_path: str) -> str:
    guessed, _ = mimetypes.guess_type(audio_path)
    if guessed:
        return guessed
    suffix = Path(audio_path).suffix.lower()
    fallback = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".mpeg": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
    }
    return fallback.get(suffix, "application/octet-stream")


def _segments_from_verbose_json(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = body.get("segments")
    if not isinstance(raw_segments, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("Content") or item.get("content") or "").strip()
        if not text:
            continue
        out.append(
            {
                "Start": float(item.get("start", item.get("Start", 0.0)) or 0.0),
                "End": float(item.get("end", item.get("End", 0.0)) or 0.0),
                "Speaker": int(item.get("speaker", item.get("Speaker", 0)) or 0),
                "Content": text,
            }
        )
    return out


def asr_result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            if isinstance(item, dict):
                c = item.get("Content") or item.get("content") or item.get("text") or ""
                parts.append(str(c).strip())
            else:
                parts.append(str(item).strip())
        return "\n".join(f for f in parts if f).strip()
    if isinstance(result, dict):
        c = result.get("text") or result.get("Content") or result.get("content")
        if c is not None:
            return str(c).strip()
        return json.dumps(result, ensure_ascii=False)
    return str(result).strip()


def _transcribe_via_http(
    settings: Settings,
    audio_path: str,
    *,
    prompt: str | None = None,
    on_token: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    url = (settings.asr_api_url or "").strip()
    if not url:
        raise RuntimeError("ASR_API_URL is not configured")
    model = (settings.asr_model_id or "").strip()
    if not model:
        raise RuntimeError("ASR_MODEL_ID is not configured")

    eff_prompt = _effective_prompt(settings, prompt)
    data: dict[str, str] = {
        "model": model,
        "response_format": (settings.asr_response_format or "verbose_json").strip() or "verbose_json",
    }
    if eff_prompt:
        data["prompt"] = eff_prompt

    filename = Path(audio_path).name or "audio.wav"
    mime = _guess_mime(audio_path)
    logger.info("ASR HTTP: POST %s model=%s file=%s", url, model, filename)

    with open(audio_path, "rb") as audio_file:
        resp = requests.post(
            url,
            files={"file": (filename, audio_file, mime)},
            data=data,
            timeout=settings.asr_timeout,
        )

    if not resp.ok:
        detail = resp.text.strip() or resp.reason
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                detail = str(payload.get("error") or payload.get("detail") or payload.get("message") or detail)
        except ValueError:
            pass
        raise RuntimeError(f"ASR HTTP {resp.status_code}: {detail}")

    body = resp.json()
    if not isinstance(body, dict):
        raise RuntimeError("ASR HTTP response is not a JSON object")

    text = asr_result_to_text(body)
    segments = _segments_from_verbose_json(body)
    if on_token and text:
        on_token(text)

    return {
        "text": text,
        "segments": segments,
        "segment_count": len(segments),
        "decode_format_used": data["response_format"],
        "stopped_by_hallucination": False,
        "hallucination": None,
        "stream_text": text[:2000],
    }


def transcribe_audio_path_to_text(
    settings: Settings,
    audio_path: str,
    *,
    prompt: str | None = None,
) -> dict[str, Any]:
    """ถอดเสียงจาก path ผ่าน OpenAI-compatible ``/v1/audio/transcriptions`` HTTP API."""
    try:
        return _transcribe_via_http(settings, audio_path, prompt=prompt)
    except Exception as exc:
        logger.exception("ASR HTTP transcription failed for %s", audio_path)
        raise RuntimeError(str(exc).strip() or "ASR transcription failed") from exc


def transcribe_audio_path_streaming(
    settings: Settings,
    audio_path: str,
    *,
    prompt: str | None = None,
    on_token: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    ถอดเสียงผ่าน HTTP API — ส่งผลลัพธ์ทั้งก้อนให้ ``on_token`` ครั้งเดียวเมื่อเสร็จ
    (upstream ไม่รองรับ token streaming)
    """
    return _transcribe_via_http(
        settings,
        audio_path,
        prompt=prompt,
        on_token=on_token,
    )
