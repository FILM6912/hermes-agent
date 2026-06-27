"""Shared helpers for normalized WebUI table repositories."""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

from app.storage.connection import Backend, db_connection
from app.storage.dialect import SQLITE, Dialect
from app.storage.timestamps import utc_now


class RepositoryBase:
    """Base class for Supabase-backed normalized repositories."""

    backend: Backend = "supabase"

    @staticmethod
    def new_id(*, seed: str | None = None) -> str:
        if seed:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
        return uuid.uuid4().hex

    @staticmethod
    def now(dialect: Dialect | None = None) -> Any:
        return utc_now(dialect or SQLITE)

    def connection(self) -> Iterator[tuple[Any, Any]]:
        return db_connection(backend=self.backend)

    @staticmethod
    def json_loads(raw: str | None, default: Any = None) -> Any:
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)
