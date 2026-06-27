"""Rollback service — checkpoint list, diff, and restore."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RollbackService:
    def list_checkpoints(
        self,
        workspace: str | None,
        *,
        access=None,
    ) -> tuple[dict[str, Any], int | None]:
        if not workspace:
            return {"error": "workspace query parameter is required"}, 400
        try:
            from app.domain.rollback import list_checkpoints

            return list_checkpoints(workspace, access=access), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception as exc:
            logger.exception("rollback/list failed")
            return {"error": str(exc)}, 500

    def get_checkpoint_diff(
        self,
        workspace: str | None,
        checkpoint: str | None,
        *,
        access=None,
    ) -> tuple[dict[str, Any], int | None]:
        if not workspace or not checkpoint:
            return {"error": "workspace and checkpoint query parameters are required"}, 400
        try:
            from app.domain.rollback import get_checkpoint_diff

            return get_checkpoint_diff(workspace, checkpoint, access=access), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception as exc:
            logger.exception("rollback/diff failed")
            return {"error": str(exc)}, 500

    def restore_checkpoint(
        self,
        workspace: str | None,
        checkpoint: str | None,
        *,
        access=None,
    ) -> tuple[dict[str, Any], int | None]:
        if not workspace or not checkpoint:
            return {"error": "workspace and checkpoint are required"}, 400
        try:
            from app.domain.rollback import restore_checkpoint

            return restore_checkpoint(workspace, checkpoint, access=access), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception as exc:
            logger.exception("rollback/restore failed")
            return {"error": str(exc)}, 500
