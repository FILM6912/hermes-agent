"""Upload service — thin layer over UploadRepository."""

from __future__ import annotations

from typing import Any

from app.repositories.upload import UploadRepository


class UploadService:
    def __init__(self, repository: UploadRepository | None = None) -> None:
        self._repo = repository or UploadRepository()

    def upload_multipart(
        self,
        *,
        body: bytes,
        content_type: str,
        content_length: int | None = None,
    ) -> tuple[dict[str, Any], int]:
        try:
            return self._repo.process_multipart(
                body=body,
                content_type=content_type,
                content_length=content_length,
            )
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception:
            import traceback

            print("[webui] upload error: " + traceback.format_exc(), flush=True)
            return {"error": "Upload failed"}, 500

    def upload_extract_multipart(
        self,
        *,
        body: bytes,
        content_type: str,
        content_length: int | None = None,
    ) -> tuple[dict[str, Any], int]:
        try:
            return self._repo.process_multipart(
                body=body,
                content_type=content_type,
                content_length=content_length,
                extract=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception:
            import traceback

            print("[webui] upload extract error: " + traceback.format_exc(), flush=True)
            return {"error": "Archive extraction failed"}, 500
