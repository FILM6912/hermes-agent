"""Upload repository — wraps api.upload multipart helpers."""

from __future__ import annotations

import io
from typing import Any


class UploadRepository:
    def process_multipart(
        self,
        *,
        body: bytes,
        content_type: str,
        content_length: int | None = None,
        extract: bool = False,
    ) -> tuple[dict[str, Any], int]:
        from app.domain.upload import process_multipart_upload

        length = content_length if content_length is not None else len(body)
        return process_multipart_upload(
            io.BytesIO(body),
            content_type,
            length,
            extract=extract,
        )
